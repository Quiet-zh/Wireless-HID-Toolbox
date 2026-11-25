# -*- coding: utf-8 -*-
"""aimouse_cloud_asr.py —— Monster AiMouse 官方云端 ASR 协议实现（实验性）。

逆向自 AiMouse.exe 与 `ws://asr.miclink.net/ws` 的实际通信：

* 每帧一个扁平 JSON，固定字段：
  ``apiKey`` / ``clientId`` / ``content`` / ``deviceNo`` / ``dwa`` / ``end`` /
  ``language`` / ``ptt`` / ``serialNo`` / ``start``
* ``content`` 是 **base64 编码的 16bit 小端 PCM**，每帧 2016 字节
  （1008 样本 = 63ms @16kHz）
* **首帧** ``start=True`` 带第一块音频；**末帧** ``end=True`` 带剩余音频
  （可短于 2016 字节）；中间帧 ``start=end=False``
* 帧间隔约 63ms，服务端流式返回 ``type=MID`` 中间结果与 ``type=LAST`` 最终结果

认证用的 ``apiKey`` 是**运行时动态值**（静态常量全部无效）。本模块支持：
1. 由调用方直接传入凭据（推荐，显式配置）；
2. 未传入时可选地**只读**扫描 AiMouse.exe 进程内存，提取驱动当前使用的凭据。

`websockets` 是可选依赖；未安装时所有接口安全降级，不影响项目其余功能。
对外只发用户自己的音频到用户自己设备的官方服务，不做其他外部动作。
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import struct
import uuid
from typing import Callable, Optional

ASR_URL = "ws://asr.miclink.net/ws"
CHUNK_BYTES = 2016          # 1008 samples * 2 bytes
FRAME_INTERVAL = 0.063      # 63ms
DEFAULT_LANGUAGE = "ZH_CN"

FRAME_FIELDS = ("apiKey", "clientId", "content", "deviceNo", "dwa", "end",
                "language", "ptt", "serialNo", "start")


# ---------------------------------------------------------------------------
# 凭据
# ---------------------------------------------------------------------------
class CloudCredentials:
    """云端 ASR 所需凭据；api_key 为运行时动态值。"""

    def __init__(self, api_key: str, device_no: str, serial_no: str,
                 language: str = DEFAULT_LANGUAGE, dwa: str = "wpgs",
                 ptt: str = "1", client_id: Optional[str] = None):
        self.api_key = api_key
        self.device_no = device_no
        self.serial_no = serial_no
        self.language = language
        self.dwa = dwa
        self.ptt = ptt
        self.client_id = client_id or str(uuid.uuid4())

    def common(self) -> dict:
        return {
            "apiKey": self.api_key,
            "clientId": self.client_id,
            "deviceNo": self.device_no,
            "serialNo": self.serial_no,
            "language": self.language,
            "dwa": self.dwa,
            "ptt": self.ptt,
        }

    def masked(self) -> str:
        """用于日志/界面的脱敏描述（不暴露 apiKey）。"""
        return "deviceNo=%s serialNo=%s" % (self.device_no, self.serial_no)


def websockets_available() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 可选：只读扫描驱动进程内存，提取运行时凭据
# ---------------------------------------------------------------------------
class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wt.DWORD), ("Protect", wt.DWORD), ("Type", wt.DWORD)]


MEM_COMMIT, MEM_PRIVATE = 0x1000, 0x20000
READABLE_PROTECT = (0x02, 0x04, 0x20, 0x40)
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
TH32CS_SNAPPROCESS = 0x00000002


def _driver_pids(kernel32) -> list[int]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    out = []
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        if "aimouse" in entry.szExeFile.lower():
            out.append(entry.th32ProcessID)
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return out


def _read_regions(kernel32, handle, small_only: bool = True):
    mbi = _MBI()
    kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                        ctypes.POINTER(_MBI), ctypes.c_size_t]
    kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_size_t)]
    addr = 0
    while addr < 0x7FFFFFFF:
        if not kernel32.VirtualQueryEx(handle, ctypes.c_void_p(addr),
                                       ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize
        if size == 0:
            break
        if (mbi.State == MEM_COMMIT
                and (mbi.Protect & 0xFF) in READABLE_PROTECT
                and (not small_only or size <= 8 * 1024 * 1024)):
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t(0)
            if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf,
                                          size, ctypes.byref(got)):
                yield buf.raw[:got.value]
        addr = base + size


def read_driver_credentials() -> Optional[CloudCredentials]:
    """只读扫描 AiMouse.exe 进程内存，返回驱动当前使用的凭据。

    找不到（驱动未运行 / 权限不足 / 非 Windows）时返回 None。
    """
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wt.HANDLE
        for pid in _driver_pids(kernel32):
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not handle:
                continue
            try:
                for data in _read_regions(kernel32, handle):
                    if b'"apiKey"' not in data:
                        continue
                    pos = 0
                    while True:
                        i = data.find(b'"apiKey"', pos)
                        if i < 0:
                            break
                        pos = i + 8
                        start = data.rfind(b"{", max(0, i - 500), i)
                        end = data.find(b"}", start)
                        if start < 0 or end < 0 or end - start > 300000:
                            continue
                        try:
                            obj = json.loads(data[start:end + 1].decode(
                                "utf-8", "ignore"))
                        except Exception:
                            continue
                        if all(k in obj for k in ("apiKey", "deviceNo",
                                                  "serialNo")):
                            return CloudCredentials(
                                api_key=obj["apiKey"],
                                device_no=obj["deviceNo"],
                                serial_no=obj["serialNo"],
                                language=obj.get("language", DEFAULT_LANGUAGE),
                                dwa=obj.get("dwa", "wpgs"),
                                ptt=str(obj.get("ptt", "1")),
                                client_id=obj.get("clientId"))
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# 帧构造（纯函数，便于单元测试）
# ---------------------------------------------------------------------------
def split_pcm(pcm: bytes, chunk_bytes: int = CHUNK_BYTES) -> list[bytes]:
    """把裸 PCM16 按 2016 字节分块；最后一块可短。"""
    return [pcm[i:i + chunk_bytes]
            for i in range(0, len(pcm), chunk_bytes)]


def build_frames(pcm: bytes, cred: CloudCredentials,
                 chunk_bytes: int = CHUNK_BYTES) -> list[dict]:
    """构造完整请求帧序列（首帧/末帧同样带音频）。"""
    chunks = split_pcm(pcm, chunk_bytes)
    frames = []
    for index, chunk in enumerate(chunks):
        frame = cred.common()
        frame["start"] = index == 0
        frame["end"] = index == len(chunks) - 1
        frame["content"] = base64.b64encode(chunk).decode("ascii")
        frames.append(frame)
    return frames


def parse_response(raw: str) -> tuple[str, str, str]:
    """解析服务端响应 -> (type, text, message)。"""
    try:
        data = json.loads(raw)
    except Exception:
        return ("", "", "")
    inner = data.get("data") or {}
    return (str(inner.get("type", "")), str(inner.get("text", "")),
            str(data.get("message", "")))


# ---------------------------------------------------------------------------
# 识别
# ---------------------------------------------------------------------------
def transcribe_pcm(pcm: bytes,
                   cred: Optional[CloudCredentials] = None,
                   on_partial: Optional[Callable[[str], None]] = None,
                   url: str = ASR_URL,
                   interval: float = FRAME_INTERVAL,
                   timeout: float = 10.0) -> Optional[str]:
    """把裸 PCM16 送到云端识别，返回最终文字。

    凭据为空时尝试从驱动进程内存读取；不可用则返回 None（调用方应降级）。
    """
    if not websockets_available():
        return None
    if cred is None:
        cred = read_driver_credentials()
    if cred is None or not cred.api_key:
        return None
    frames = build_frames(pcm, cred)
    if not frames:
        return None

    import asyncio
    import websockets

    async def _run() -> Optional[str]:
        texts = []
        try:
            async with websockets.connect(url, open_timeout=8,
                                          close_timeout=1) as ws:
                for frame in frames:
                    await ws.send(json.dumps(frame, ensure_ascii=False))
                    if interval:
                        await asyncio.sleep(interval)
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except Exception:
                        break
                    kind, text, _msg = parse_response(raw)
                    if text:
                        texts.append(text)
                        if on_partial and kind == "MID":
                            on_partial(text)
                    if kind == "LAST":
                        break
        except Exception:
            return None
        return texts[-1] if texts else ""

    try:
        return asyncio.run(_run())
    except Exception:
        return None


def transcribe_wav(path: str, **kwargs) -> Optional[str]:
    """从 WAV 文件读取 PCM 后送云端识别。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(44)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        with open(path, "rb") as fh:
            data = fh.read()
        pos = data.find(b"data")
        if pos < 0:
            return None
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        pcm = data[pos + 8:pos + 8 + size]
        return transcribe_pcm(pcm, **kwargs)
    except Exception:
        return None
