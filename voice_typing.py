# -*- coding: utf-8 -*-
"""voice_typing.py —— 把语音识别结果键入当前焦点输入框。

纯 Windows API（ctypes），零第三方依赖。用于在「语音输入」开关打开时，
把识别出的文字自动键入用户当前聚焦的输入框（任意程序，不限于本工具箱）。

原理：

* 用 ``GetForegroundWindow`` + ``GetGUIThreadInfo`` 记录最近一个**非本进程**
  的前台窗口及其焦点控件（避免把文字打进工具箱自己的窗口）。
* 用 ``SendInput`` 的 ``KEYEVENTF_UNICODE`` 逐字符发送，中文可直接输入；
  非 BMP 字符（emoji）自动拆成 UTF-16 surrogate 对。
* 如果目标窗口已不在前台，先尝试 ``SetForegroundWindow`` 恢复；
  失败时用 ``AttachThreadInput`` 兜底。

只有设置里的 ``voice_typing`` 开关打开时才会调用本模块，默认不动作。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time
from dataclasses import dataclass
from typing import Optional

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_BACK = 0x08
SW_RESTORE = 9
MAX_CHARS = 2000          # 单次键入上限，避免长文本卡住输入队列

# 不该接收键入的系统窗口（类名 / 标题关键词）
NON_TYPABLE_CLASSES = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd",
    "Windows.UI.Core.CoreWindow", "LockScreenBackstop",
    "MultitaskingViewFrame", "ForegroundStaging", "NativeHWNDHost",
})
NON_TYPABLE_TITLES = ("锁屏", "Lock Screen", "Program Manager")


# ---------------------------------------------------------------------------
# Win32 结构
# ---------------------------------------------------------------------------
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG),
                ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD),
                ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT),
                ("hi", _HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND),
                ("rcCaret", _RECT)]


@dataclass
class FocusTarget:
    """最近一次记录的外部前台窗口。"""
    hwnd: int
    focus_hwnd: int
    pid: int
    tid: int


_user32_cache = None
_kernel32_cache = None


def _dlls():
    global _user32_cache, _kernel32_cache
    if os.name != "nt":
        raise OSError("voice_typing 仅支持 Windows")
    if _user32_cache is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        u.GetForegroundWindow.restype = wt.HWND
        u.GetForegroundWindow.argtypes = []
        u.GetWindowThreadProcessId.restype = wt.DWORD
        u.GetWindowThreadProcessId.argtypes = [wt.HWND,
                                               ctypes.POINTER(wt.DWORD)]
        u.GetGUIThreadInfo.restype = wt.BOOL
        u.GetGUIThreadInfo.argtypes = [wt.DWORD,
                                       ctypes.POINTER(GUITHREADINFO)]
        u.GetClassNameW.restype = ctypes.c_int
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.SendInput.restype = wt.UINT
        u.SendInput.argtypes = [wt.UINT, ctypes.c_void_p, ctypes.c_int]
        u.SetForegroundWindow.restype = wt.BOOL
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.IsIconic.restype = wt.BOOL
        u.IsIconic.argtypes = [wt.HWND]
        u.ShowWindow.restype = wt.BOOL
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u.BringWindowToTop.restype = wt.BOOL
        u.BringWindowToTop.argtypes = [wt.HWND]
        u.AttachThreadInput.restype = wt.BOOL
        u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        k.GetCurrentThreadId.restype = wt.DWORD
        _user32_cache, _kernel32_cache = u, k
    return _user32_cache, _kernel32_cache


def supported() -> bool:
    return os.name == "nt"


# ---------------------------------------------------------------------------
# 焦点捕获
# ---------------------------------------------------------------------------
def current_focus() -> Optional[FocusTarget]:
    """返回当前前台窗口信息；无前台窗口时返回 None。"""
    try:
        u, _k = _dlls()
    except OSError:
        return None
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wt.DWORD(0)
    tid = u.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    focus = 0
    if tid and u.GetGUIThreadInfo(tid, ctypes.byref(info)):
        focus = info.hwndFocus or info.hwndActive or 0
    return FocusTarget(hwnd=int(hwnd or 0),
                       focus_hwnd=int(focus or hwnd or 0),
                       pid=int(pid.value), tid=int(tid))


def track_focus(exclude_pid: Optional[int] = None) -> Optional[FocusTarget]:
    """若当前前台窗口不属于 ``exclude_pid``（通常是本进程），返回它。

    用于轮询记录「用户最后停留的外部输入框」；系统/锁屏类窗口会被排除，
    避免把识别文字误键入桌面或锁屏界面。
    """
    target = current_focus()
    if target is None:
        return None
    if exclude_pid is not None and target.pid == exclude_pid:
        return None
    if not is_typable_window(target):
        return None
    return target


def window_class(hwnd: int) -> str:
    """取窗口类名；失败返回空串。"""
    try:
        u, _k = _dlls()
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(wt.HWND(hwnd), buf, 256)
        return buf.value or ""
    except Exception:
        return ""


def window_text(hwnd: int) -> str:
    """取窗口标题；失败返回空串。"""
    try:
        u, _k = _dlls()
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(wt.HWND(hwnd), buf, 512)
        return buf.value or ""
    except Exception:
        return ""


def is_typable_window(target: Optional[FocusTarget]) -> bool:
    """排除桌面、任务栏、锁屏等不该接收键入的窗口。"""
    if not target or not target.hwnd:
        return False
    if window_class(target.hwnd) in NON_TYPABLE_CLASSES:
        return False
    title = window_text(target.hwnd)
    if any(key in title for key in NON_TYPABLE_TITLES):
        return False
    return True


# ---------------------------------------------------------------------------
# Unicode 键入
# ---------------------------------------------------------------------------
def _make_input(scan: int, up: bool) -> INPUT:
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki.wVk = 0
    item.u.ki.wScan = scan & 0xFFFF
    item.u.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    item.u.ki.time = 0
    item.u.ki.dwExtraInfo = None
    return item


def _utf16_units(ch: str) -> list[int]:
    code = ord(ch)
    if code <= 0xFFFF:
        return [code]
    code -= 0x10000
    return [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]


def build_unicode_inputs(text: str) -> list[INPUT]:
    """把文本转成 SendInput 需要的 INPUT 数组（纯函数，便于测试）。"""
    out: list[INPUT] = []
    for ch in (text or "")[:MAX_CHARS]:
        if ch in ("\r", "\n", "\t"):
            ch = " "          # 避免误触发回车提交或跳出输入框
        for unit in _utf16_units(ch):
            out.append(_make_input(unit, False))
            out.append(_make_input(unit, True))
    return out


def build_backspace_inputs(count: int) -> list[INPUT]:
    """构造 ``count`` 次退格（流式输入纠正假设时用）。"""
    out: list[INPUT] = []
    for _ in range(max(0, min(int(count), MAX_CHARS))):
        down = INPUT()
        down.type = INPUT_KEYBOARD
        down.u.ki.wVk = VK_BACK
        down.u.ki.wScan = 0
        down.u.ki.dwFlags = 0
        up = INPUT()
        up.type = INPUT_KEYBOARD
        up.u.ki.wVk = VK_BACK
        up.u.ki.wScan = 0
        up.u.ki.dwFlags = KEYEVENTF_KEYUP
        out.extend((down, up))
    return out


def send_inputs(inputs: list[INPUT]) -> bool:
    """真正调用 SendInput；返回是否全部成功投递。"""
    if not inputs:
        return False
    try:
        u, _k = _dlls()
    except OSError:
        return False
    count = len(inputs)
    arr = (INPUT * count)(*inputs)
    sent = u.SendInput(count, ctypes.cast(arr, ctypes.c_void_p),
                       ctypes.sizeof(INPUT))
    return int(sent) == count


def activate_window(hwnd: int) -> bool:
    """把目标窗口恢复到前台；失败时用 AttachThreadInput 兜底。"""
    try:
        u, k = _dlls()
    except OSError:
        return False
    if not hwnd:
        return False
    h = wt.HWND(hwnd)
    try:
        if u.IsIconic(h):
            u.ShowWindow(h, SW_RESTORE)
        if int(u.GetForegroundWindow() or 0) == hwnd:
            return True
        if u.SetForegroundWindow(h):
            return True
        fg = u.GetForegroundWindow()
        fg_tid = u.GetWindowThreadProcessId(fg, None) if fg else 0
        cur_tid = k.GetCurrentThreadId()
        if fg_tid and fg_tid != cur_tid:
            u.AttachThreadInput(cur_tid, fg_tid, True)
            ok = u.SetForegroundWindow(h)
            u.BringWindowToTop(h)
            u.AttachThreadInput(cur_tid, fg_tid, False)
            return bool(ok)
    except Exception:
        return False
    return False


def type_text(text: str, target: Optional[FocusTarget] = None) -> tuple[bool, str]:
    """把 ``text`` 键入目标窗口的焦点输入框。

    返回 ``(是否成功, 中文说明)``。target 为 None 时直接发给当前前台窗口。
    """
    if not text or not text.strip():
        return False, "没有可键入的文字"
    if not supported():
        return False, "仅支持 Windows"
    inputs = build_unicode_inputs(text)
    if not inputs:
        return False, "文字为空"

    if target is not None:
        if not is_typable_window(target):
            return False, "目标窗口不可键入（系统/锁屏界面），已跳过"
        cur = current_focus()
        if cur is None or cur.hwnd != target.hwnd:
            if not activate_window(target.hwnd):
                return False, "无法恢复目标窗口，已跳过键入"
            time.sleep(0.06)      # 等窗口完成激活，避免字符打到别处

    ok = send_inputs(inputs)
    return (ok, "已键入焦点输入框" if ok else "SendInput 被拒绝，已跳过键入")
