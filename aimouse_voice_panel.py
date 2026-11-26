# -*- coding: utf-8 -*-
"""aimouse_voice_panel.py —— 魔声 AI 垂直鼠标 语音窗口。

主界面「魔声 AI 垂直鼠标」卡片上的「语音」按钮打开本窗口：

* **开始监测 / 结束监测**：长按鼠标语音键开始录制，松开自动保存一条音频
* **录音列表**：点击选中，可播放 / 停止 / 删除 / 转文字
* **实时区域**：录制中显示音量与实时识别文字
* **设置**：参数名 + 中文描述 + 输入框 + 加减按钮，点「保存」才生效

语音识别使用可选的 Vosk 离线引擎（`pip install vosk` + 中文模型），
未安装时自动降级为「仅录音」，不影响其他功能。
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import wave
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import aimouse_voice as av
import aimouse_voice_capture as avc
import hid_win as hw
import theme
import tray_common as tc
import voice_typing as vt
from ui_common import attach_auto_scrollbar

BG = "#0f1115"
CARD = "#171a21"
CARD_EDGE = "#252b37"
TRACK = "#2a303c"
TEXT = "#f5f7fa"
SUB = "#a3aab8"
FAINT = "#6f7788"
GREEN = "#5ddc8a"
AMBER = "#f5c451"
RED = "#ff6b6b"
MUTED = "#7d8499"

CONFIG_PATH = os.path.join(tc.RUNTIME_DIR, "voice_config.json")
DEFAULT_MODEL = os.path.join(tc.RUNTIME_DIR, "models", "vosk-model-small-cn-0.22")
BIG_MODEL_DIR = os.path.join(tc.RUNTIME_DIR, "models", "vosk-model-cn-0.22")
# sherpa-onnx 模型根目录：其下自动探测 streaming-paraformer / sense-voice
DEFAULT_SHERPA_ROOT = os.path.join(tc.RUNTIME_DIR, "models")
DEFAULT_SAVE = os.path.join(tc.RUNTIME_DIR, "voice")

# Vosk 模型按目录全局缓存：大模型首次加载需 30~50 秒，
# 重开窗口 / 保存设置 / 开始监测都不应重复加载。
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()
_VOSK_QUIET = False


def normalize_asr_text(text: str) -> str:
    """规整识别结果：去掉中文词之间的空格，英文单词间空格保留。

    实现在 :func:`aimouse_voice.normalize_asr_text`（Vosk / sherpa 共用），
    这里保留同名函数，历史调用与测试无需改动。
    """
    return av.normalize_asr_text(text)


def _quiet_vosk() -> None:
    """Kaldi/Vosk 默认往 stderr 打大量模型加载日志，静音一次即可。"""
    global _VOSK_QUIET
    if _VOSK_QUIET:
        return
    try:
        from vosk import SetLogLevel
        SetLogLevel(-1)
        _VOSK_QUIET = True
    except (KeyboardInterrupt, Exception):
        pass

# (键, 参数名, 中文描述, 默认值, 最小, 最大, 步长, 类型)
PARAM_DEFS = [
    ("highpass", "高通截止频率", "去除低频轰鸣；0 表示关闭，单位 Hz",
     150, 0, 1000, 10, "int"),
    ("peak", "归一化峰值", "输出音量上限；越小越不容易削波",
     26000, 1000, 32000, 1000, "int"),
    ("denoise", "降噪强度", "0 关闭；越大越干净，但可能有回音；需 noisereduce",
     0, 0, 100, 5, "int"),
    ("auto_transcribe", "自动转文字", "录制结束后自动识别（1 开 / 0 关）",
     1, 0, 1, 1, "bool"),
    ("stream_asr", "流式转文字", "1=边说边转（实时显示）；0=松开语音键后整段识别一次",
     1, 0, 1, 1, "bool"),
    ("max_seconds", "单次最长录制", "超过该秒数自动结束并保存",
     30, 5, 120, 5, "int"),
    ("save_audio", "保存语音文件", "1=录音保存为 WAV；0=只转文字不保存",
     1, 0, 1, 1, "bool"),
    ("save_dir", "音频保存目录", "录制文件存放位置（保存语音开启时有效）",
     DEFAULT_SAVE, None, None, None, "path"),
    ("model_dir", "识别模型目录", "Vosk 中文模型所在目录",
     DEFAULT_MODEL, None, None, None, "path"),
    ("asr_engine", "识别引擎", "0 自动(sherpa优先) 1 强制sherpa 2 仅Vosk",
     0, 0, 2, 1, "int"),
    ("sherpa_model_dir", "sherpa模型目录",
     "含 streaming-paraformer / sense-voice 子目录的根目录（自动探测）",
     DEFAULT_SHERPA_ROOT, None, None, None, "path"),
    ("asr_backend", "识别后端", "0 自动(本地优先) 1 仅Vosk 2 剪贴板 3 云端",
     0, 0, 3, 1, "int"),
    ("local_only", "纯本地模式", "1=只用本地 Vosk，完全不联网/不读剪贴板；0=按识别后端设置",
     1, 0, 1, 1, "bool"),
    ("voice_typing", "语音输入到焦点", "1=识别后把文字键入当前焦点输入框；说话前请先点好目标输入框",
     0, 0, 1, 1, "bool"),
    ("asr_grammar", "识别词表(可选)", "逗号分隔的候选词；留空=通用识别，填了可显著提升固定命令准确率",
     "", None, None, None, "text"),
]

DEFAULTS = {d[0]: d[3] for d in PARAM_DEFS}


def themed(color: str) -> str:
    if theme.current() == "light":
        return theme.PANEL_LIGHT.get(color.lower(), color)
    return color


# ---------------------------------------------------------------------------
# 剪贴板桥接（兜底后端：复用官方驱动的识别结果，零依赖）
# ---------------------------------------------------------------------------
def clipboard_sequence() -> int:
    """剪贴板序列号；官方识别完成后会写入剪贴板使序列号变化。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def clipboard_text() -> str:
    """读取剪贴板 Unicode 文本。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def wait_clipboard_result(before: int, timeout: float = 2.0) -> str:
    """等待剪贴板变化并返回新文本；超时返回空串。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if clipboard_sequence() != before:
            text = clipboard_text().strip()
            if text:
                return text
        time.sleep(0.05)
    return ""


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    cfg[key] = data[key]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


# ---------------------------------------------------------------------------
# 语音识别（可选）
# ---------------------------------------------------------------------------
class AsrEngine:
    """Vosk 离线识别封装；不可用时全部返回 None。"""

    def __init__(self, model_dir: str, grammar: str = ""):
        self.model_dir = model_dir
        self.grammar = grammar or ""
        self._model = None
        self._rec = None
        self._gate = None            # 前导静音门控（begin 时创建）
        self._lock = threading.Lock()
        self.error = ""

    def available(self) -> bool:
        try:
            import vosk  # noqa: F401
        except KeyboardInterrupt:
            # Ctrl+C 恰好落在模块导入锁上（后台线程首次 import vosk 较慢）：
            # 视为用户中断，安静返回，不让 KeyboardInterrupt 冒泡到 Tk 回调
            self.error = "已中断"
            return False
        except Exception:
            self.error = "未安装 vosk"
            return False
        _quiet_vosk()
        if not os.path.isdir(self.model_dir):
            self.error = "模型目录不存在"
            return False
        return True

    def _ensure_model(self):
        if self._model is None:
            with _MODEL_LOCK:
                model = _MODEL_CACHE.get(self.model_dir)
                if model is None:
                    _quiet_vosk()
                    from vosk import Model
                    model = Model(self.model_dir)
                    _MODEL_CACHE[self.model_dir] = model
                self._model = model
        return self._model

    def preload(self, stream: Optional[bool] = None) -> bool:
        """后台预热模型；避免录音开始时才加载（大模型尤其明显）。

        ``stream`` 参数仅为与 sherpa 引擎接口对齐，Vosk 只有一个模型，
        忽略该参数。
        """
        if not self.available():
            return False
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def _grammar_supported(self) -> bool:
        """Vosk 完整版大模型不支持 runtime grammar，仅 small 系列可用。"""
        return "small" in os.path.basename(
            os.path.normpath(self.model_dir)).lower()

    @property
    def name(self) -> str:
        """引擎标识，与 sherpa 引擎保持一致。"""
        return "vosk"

    @property
    def label(self) -> str:
        return "Vosk"

    def grammar_supported(self) -> bool:
        """供面板统一查询；sherpa 引擎同名方法固定返回 False。"""
        return self._grammar_supported()

    def _make_rec(self, KaldiRecognizer):
        """构造识别器；设置了词表且模型支持时启用 Vosk grammar 约束。"""
        model = self._ensure_model()
        words = [w for w in re.split(r"[,，\s]+", self.grammar.strip()) if w]
        if words and self._grammar_supported():
            return KaldiRecognizer(
                model, av.SAMPLE_RATE,
                json.dumps(words + ["[unk]"], ensure_ascii=False))
        return KaldiRecognizer(model, av.SAMPLE_RATE)

    def begin(self) -> bool:
        """开始一次流式识别。"""
        if not self.available():
            return False
        try:
            from vosk import KaldiRecognizer
            self._rec = self._make_rec(KaldiRecognizer)
            self._gate = av.OnsetGate()
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    def feed(self, pcm: bytes) -> None:
        """喂一段 PCM（每秒数百次，只投递不解析，避免重复 JSON 解码）。

        前导静音先由 :class:`aimouse_voice.OnsetGate` 拦下：设备按下语音键
        后有 1 秒多纯底噪，喂给模型会让句首「听出」不存在的字。
        """
        with self._lock:
            if self._rec is None:
                return
            gate = getattr(self, "_gate", None)
            data = gate.push(pcm) if gate is not None else pcm
            if not data:
                return
            try:
                self._rec.AcceptWaveform(data)
            except Exception:
                pass

    def partial(self) -> str:
        """取当前部分识别结果；由 UI 以约 10Hz 节流调用。"""
        with self._lock:
            if self._rec is None:
                return ""
            try:
                return normalize_asr_text(
                    json.loads(self._rec.PartialResult()).get("partial", ""))
            except Exception:
                return ""

    def finish(self) -> str:
        with self._lock:
            if self._rec is None:
                return ""
            # 门控还没打开（说话太轻/太短）时先把缓冲补喂，否则等于没输入
            gate = self._gate
            if gate is not None and not gate.opened:
                rest = gate.flush()
                if rest:
                    try:
                        self._rec.AcceptWaveform(rest)
                    except Exception:
                        pass
            try:
                text = normalize_asr_text(
                    json.loads(self._rec.FinalResult()).get("text", ""))
            except Exception:
                text = ""
            self._rec = None
            self._gate = None
            return text

    def transcribe_samples(self, samples: list[int]) -> Optional[str]:
        """对内存中的 PCM 样本做一次性识别（不保存 WAV 时使用）。"""
        if not self.available() or not samples:
            return None
        try:
            from vosk import KaldiRecognizer
            rec = self._make_rec(KaldiRecognizer)
            # 前导静音必须裁掉，否则句首容易被识别成不存在的字
            pcm = av.samples_to_pcm16(av.trim_leading_silence(samples))
            for i in range(0, len(pcm), 4000):
                rec.AcceptWaveform(pcm[i:i + 4000])
            return normalize_asr_text(
                json.loads(rec.FinalResult()).get("text", ""))
        except Exception as exc:
            self.error = str(exc)
            return None

    def transcribe_file(self, wav_path: str) -> Optional[str]:
        """对已有 WAV 做一次性识别。"""
        if not self.available():
            return None
        try:
            from vosk import KaldiRecognizer
            rec = self._make_rec(KaldiRecognizer)
            with wave.open(wav_path, "rb") as fh:
                raw = fh.readframes(fh.getnframes())
            # 同上：只裁整段开头的前导静音
            pcm = av.trim_pcm(raw)
            for i in range(0, len(pcm), 4000):
                rec.AcceptWaveform(pcm[i:i + 4000])
            return normalize_asr_text(
                json.loads(rec.FinalResult()).get("text", ""))
        except Exception as exc:
            self.error = str(exc)
            return None


def make_asr_engine(cfg: dict):
    """按配置创建识别引擎，sherpa 不可用时自动回退 Vosk。

    ``asr_engine``：0 自动（sherpa 优先）/ 1 强制 sherpa / 2 仅 Vosk。
    强制 sherpa 但依赖或模型缺失时仍回退 Vosk，并把原因写进 ``error``，
    界面上能直接看到「为什么没用上 sherpa」，不会静默降级。
    """
    prefer = int(cfg.get("asr_engine", 0) or 0)
    model_dir = cfg.get("model_dir", DEFAULT_MODEL)
    grammar = cfg.get("asr_grammar", "")
    if prefer in (0, 1):
        root = cfg.get("sherpa_model_dir") or DEFAULT_SHERPA_ROOT
        try:
            import aimouse_sherpa_asr as sasr
        except Exception as exc:      # 模块本身出问题也不能拖垮语音
            sasr = None
            sherpa_error = "无法导入 aimouse_sherpa_asr：%s" % exc
        else:
            eng = sasr.SherpaAsrEngine(root, grammar)
            if eng.available():
                return eng
            sherpa_error = eng.error or "不可用"
        fallback = AsrEngine(model_dir, grammar)
        if prefer == 1:
            fallback.error = "sherpa %s，已回退 Vosk" % sherpa_error
        else:
            # 自动模式：不算错误，但记下原因，界面提示可下载模型提升准确率
            fallback.sherpa_hint = sherpa_error
        return fallback
    return AsrEngine(model_dir, grammar)


def asr_engine_key(cfg: dict) -> tuple:
    """配置指纹：变了才重建引擎，避免每次保存设置都重新加载模型。"""
    return (int(cfg.get("asr_engine", 0) or 0),
            cfg.get("model_dir", DEFAULT_MODEL),
            cfg.get("sherpa_model_dir") or DEFAULT_SHERPA_ROOT,
            cfg.get("asr_grammar", ""))


# ---------------------------------------------------------------------------
# 录制线程
# ---------------------------------------------------------------------------
class Recorder(threading.Thread):
    """监听 0xFF91：录音开始/结束由 05 62 / 05 63 状态帧驱动。"""

    def __init__(self, events: queue.Queue, max_seconds: int = 30):
        super().__init__(daemon=True, name="aimouse-recorder")
        self.events = events
        self.max_seconds = max_seconds
        self._stop = threading.Event()
        self._recording = False
        self._frames: list[bytes] = []
        self._start_ts = 0.0
        self._last_ts = 0.0
        self._finish_at = 0.0      # 按键抬起后的延迟收尾时间戳
        self._cooldown_until = 0.0  # 收尾后的静默期，忽略尾部音频帧

    def stop(self) -> None:
        self._stop.set()

    def _finish(self, reason: str = "", now: float | None = None) -> None:
        if not self._recording:
            return
        when = time.monotonic() if now is None else now
        self._recording = False
        frames = self._frames
        self._frames = []
        self._cooldown_until = when + 0.5
        dur = when - self._start_ts
        self.events.put(("segment", frames, dur, reason))

    def note_key(self, arg: int, now: float) -> None:
        """记录「长按抬起」：安排 150ms 后收尾，不再等设备补发状态帧。"""
        if arg in (0x38, 0x32) and self._recording and not self._finish_at:
            self._finish_at = now + 0.15

    def _check_finish(self, now: float) -> None:
        """收尾判定，必须在每轮循环开头调用（音频帧分支会 continue）。"""
        if self._finish_at and now >= self._finish_at:
            self._finish("按键抬起", now)
            self._finish_at = 0.0
        elif self._recording:
            if now - self._last_ts > 0.6:
                self._finish("音频中断", now)
            elif now - self._start_ts > self.max_seconds:
                self._finish("达到时长上限", now)

    def _on_audio_frame(self, data: bytes, now: float) -> None:
        """处理一条 0x1B 音频帧；必要时自动进入录制。"""
        if not self._recording:
            # 兜底：部分模式设备直接推音频帧、不补 0x05/0x62 开始帧；
            # 收尾后 0.5s 内的尾部帧忽略，避免反复开录
            if now < self._cooldown_until:
                return
            self._recording = True
            self._frames = []
            self._start_ts = now
            self._finish_at = 0.0
            self.events.put(("start", None))
        self._frames.append(data)
        self._last_ts = now
        self.events.put(("audio", data))

    def run(self) -> None:
        iface = avc.find_interface()
        if iface is None:
            self.events.put(("error", "没有找到 248A:60AB 的 0xFF91 接口"))
            return
        try:
            with hw.HidDevice(iface.path, write=False) as dev:
                while not self._stop.is_set():
                    now = time.monotonic()
                    # 收尾判定必须放在循环开头：音频帧分支会 continue，
                    # 若放在末尾，设备持续发 0x1B 帧时永远检查不到。
                    self._check_finish(now)
                    report = dev.read_input(timeout_ms=80)
                    if report:
                        data = bytes(report)
                        if data[:1] == b"\x1b":
                            self._on_audio_frame(data, now)
                            continue
                        if len(data) >= 4 and data[:2] == b"\x0c\x4d":
                            cmd, arg = data[2], data[3]
                            if cmd == 0x05 and arg == 0x62:
                                if not self._recording:
                                    self._recording = True
                                    self._frames = []
                                    self._start_ts = now
                                    self._last_ts = now
                                    self._finish_at = 0.0
                                    self.events.put(("start", None))
                            elif cmd == 0x05 and arg == 0x63:
                                self._finish(now=now)
                                self._finish_at = 0.0
                            elif cmd == 0x04:
                                self.events.put(("key", arg))
                                self.note_key(arg, now)
        except Exception as exc:
            self.events.put(("error", "录音线程异常: %r" % exc))
        finally:
            self._finish("监测结束")


# ---------------------------------------------------------------------------
# 设置对话框
# ---------------------------------------------------------------------------
class VoiceSettingsDialog(tk.Toplevel):
    """参数名 + 中文描述 + 输入框 + 加减按钮；保存后才生效。"""

    def __init__(self, parent, cfg: dict, on_save):
        super().__init__(parent)
        self.title("语音设置 · 魔声 AI 垂直鼠标")
        self.configure(bg=themed(BG))
        self.cfg = dict(cfg)
        self.on_save = on_save
        self.vars: dict[str, tk.StringVar] = {}
        self._build()
        theme.apply_new(self, "panel")
        self.transient(parent)
        self.grab_set()
        self.geometry("720x620")

    def _build(self) -> None:
        head = tk.Frame(self, bg=themed(BG))
        head.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(head, text="语音参数", bg=themed(BG), fg=themed(TEXT),
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        tk.Label(head, text="修改后点「保存」才会生效", bg=themed(BG),
                 fg=themed(FAINT),
                 font=("Microsoft YaHei UI", 9)).pack(side="right")

        body = tk.Frame(self, bg=themed(BG))
        body.pack(fill="both", expand=True, padx=20, pady=8)
        canvas = tk.Canvas(body, bg=themed(BG), highlightthickness=0)
        inner = tk.Frame(canvas, bg=themed(BG))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.pack(side="left", fill="both", expand=True)
        # 纵向滚动条仅在参数行总高超过对话框可视高度时显示
        attach_auto_scrollbar(body, canvas, orient="vertical",
                              layout="pack", side="right", fill="y")
        # 绑定到对话框自身（Tk 的 bindtags 会让子控件的滚轮事件冒泡到
        # toplevel），而不是 bind_all：后者是全局绑定，窗口销毁后不会自动
        # 解绑，之后每次滚轮都会引用已销毁的 canvas 抛 TclError。
        def on_wheel(event, c=canvas):
            try:
                if c.winfo_exists():
                    c.yview_scroll(int(-event.delta / 120), "units")
            except tk.TclError:
                pass
        self.bind("<MouseWheel>", on_wheel)

        for key, label, desc, default, lo, hi, step, kind in PARAM_DEFS:
            self._add_param(inner, key, label, desc, lo, hi, step, kind)

        foot = tk.Frame(self, bg=themed(BG))
        foot.pack(fill="x", padx=20, pady=(4, 16))
        tk.Button(foot, text="保存", command=self._save, bg=themed(GREEN),
                  fg="#0b2c18", activebackground=themed(GREEN),
                  relief="flat", font=("Microsoft YaHei UI", 10, "bold"),
                  padx=22, pady=6).pack(side="right")
        tk.Button(foot, text="取消", command=self.destroy, bg=themed(TRACK),
                  fg=themed(SUB), activebackground=themed(CARD_EDGE),
                  relief="flat", font=("Microsoft YaHei UI", 10),
                  padx=18, pady=6).pack(side="right", padx=(0, 10))
        tk.Button(foot, text="恢复默认", command=self._reset,
                  bg=themed(TRACK), fg=themed(SUB),
                  activebackground=themed(CARD_EDGE), relief="flat",
                  font=("Microsoft YaHei UI", 9),
                  padx=14, pady=6).pack(side="left")

    def _add_param(self, parent, key, label, desc, lo, hi, step, kind) -> None:
        box = tk.Frame(parent, bg=themed(CARD), highlightbackground=themed(
            CARD_EDGE), highlightthickness=1)
        box.pack(fill="x", pady=6)
        top = tk.Frame(box, bg=themed(CARD))
        top.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(top, text=label, bg=themed(CARD), fg=themed(TEXT),
                 font=("Microsoft YaHei UI", 10, "bold"),
                 anchor="w").pack(side="left")
        tk.Label(top, text=key, bg=themed(CARD), fg=themed(FAINT),
                 font=("Consolas", 8), anchor="e").pack(side="right")
        tk.Label(box, text=desc, bg=themed(CARD), fg=themed(SUB),
                 font=("Microsoft YaHei UI", 8), anchor="w",
                 justify="left", wraplength=620).pack(fill="x", padx=14)

        row = tk.Frame(box, bg=themed(CARD))
        row.pack(fill="x", padx=14, pady=(6, 12))
        var = tk.StringVar(value=str(self.cfg.get(key, "")))
        self.vars[key] = var

        if kind == "text":
            tk.Entry(row, textvariable=var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Microsoft YaHei UI", 9),
                     width=52).pack(side="left", fill="x", expand=True, ipady=4)
            tk.Label(row, text="留空为通用识别", bg=themed(CARD),
                     fg=themed(FAINT),
                     font=("Microsoft YaHei UI", 8)).pack(side="left", padx=10)
            return

        if kind == "path":
            entry = tk.Entry(row, textvariable=var, bg=themed(TRACK),
                             fg=themed(TEXT), insertbackground=themed(TEXT),
                             relief="flat", font=("Consolas", 9), width=62)
            entry.pack(side="left", fill="x", expand=True, ipady=4)
            tk.Button(row, text="浏览…", command=lambda k=key: self._browse(k),
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9), padx=10).pack(
                side="left", padx=(8, 0))
            tk.Button(row, text="📁 打开",
                      command=lambda k=key: self._open_path(k),
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9), padx=10).pack(
                side="left", padx=(6, 0))
            return

        def bump(delta, v=var, s=step, lo_=lo, hi_=hi):
            try:
                cur = int(float(v.get()))
            except ValueError:
                cur = lo_ or 0
            cur += delta * (s or 1)
            if lo_ is not None:
                cur = max(lo_, cur)
            if hi_ is not None:
                cur = min(hi_, cur)
            v.set(str(cur))

        tk.Button(row, text="◀", command=lambda v=var: bump(-1),
                  bg=themed(TRACK), fg=themed(TEXT), relief="flat",
                  font=("Microsoft YaHei UI", 9), width=3).pack(side="left")
        entry = tk.Entry(row, textvariable=var, bg=themed(TRACK),
                         fg=themed(TEXT), insertbackground=themed(TEXT),
                         relief="flat", justify="center",
                         font=("Consolas", 10), width=10)
        entry.pack(side="left", padx=6, ipady=3)
        tk.Button(row, text="▶", command=lambda v=var: bump(1),
                  bg=themed(TRACK), fg=themed(TEXT), relief="flat",
                  font=("Microsoft YaHei UI", 9), width=3).pack(side="left")
        if lo is not None and hi is not None:
            tk.Label(row, text="范围 %s ~ %s" % (lo, hi), bg=themed(CARD),
                     fg=themed(FAINT),
                     font=("Microsoft YaHei UI", 8)).pack(side="left", padx=12)

    def _browse(self, key: str) -> None:
        if key.endswith("_dir"):
            path = filedialog.askdirectory(initialdir=self.vars[key].get() or ".")
            if path:
                self.vars[key].set(path)

    def _open_path(self, key: str) -> None:
        """在资源管理器中打开设置里的路径（save_dir / model_dir）。"""
        path = self.vars[key].get().strip()
        if not path:
            return
        if not os.path.isdir(path):
            messagebox.showinfo("提示", "目录不存在：\n%s" % path,
                                parent=self)
            return
        try:
            starter = getattr(os, "startfile", None)
            if starter is None:
                messagebox.showinfo("提示", "仅支持 Windows 资源管理器",
                                    parent=self)
                return
            starter(path)
        except Exception as exc:
            messagebox.showerror("打开失败",
                                 "无法打开 %s：\n%r" % (path, exc),
                                 parent=self)

    def _reset(self) -> None:
        for key, var in self.vars.items():
            var.set(str(DEFAULTS[key]))

    def _save(self) -> None:
        cfg = dict(self.cfg)
        for key, label, desc, default, lo, hi, step, kind in PARAM_DEFS:
            raw = self.vars[key].get().strip()
            if kind in ("path", "text"):
                cfg[key] = raw
                continue
            try:
                value = int(float(raw))
            except ValueError:
                messagebox.showwarning("参数无效",
                                       "%s 需要填数字" % label, parent=self)
                return
            if lo is not None:
                value = max(lo, value)
            if hi is not None:
                value = min(hi, value)
            cfg[key] = value
        self.on_save(cfg)
        self.destroy()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class VoiceWindow(tk.Toplevel):
    def __init__(self, parent, on_close=None):
        super().__init__(parent)
        self.title("魔声 AI 垂直鼠标 · 语音")
        self.configure(bg=themed(BG))
        self.geometry("980x660")
        self.minsize(860, 560)
        self._on_close_cb = on_close
        self.cfg = load_config()
        self.events: queue.Queue = queue.Queue()
        self.recorder: Optional[Recorder] = None
        self.asr = make_asr_engine(self.cfg)
        self._asr_key = asr_engine_key(self.cfg)
        self._asr_active = False
        self._partial = ""
        self._playing = False
        self._clip_before = 0
        self._focus_target = None       # 最近一次的非本进程前台窗口
        self._focus_poll_at = 0.0
        self._ui_tick = 0.0             # 音量条/部分结果节流时间戳
        self._stream_decoder = None      # 流式模式用的跨帧连续解码器
        self.selected: Optional[str] = None
        self._build()
        self._refresh_mode()
        theme.apply_new(self, "panel")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll()

    # -- UI ---------------------------------------------------------------
    def _build(self) -> None:
        head = tk.Frame(self, bg=themed(BG))
        head.pack(fill="x", padx=18, pady=(14, 6))
        self.btn_toggle = tk.Button(
            head, text="● 开始监测", command=self._toggle_monitor,
            bg=themed(GREEN), fg="#0b2c18", activebackground=themed(GREEN),
            relief="flat", font=("Microsoft YaHei UI", 11, "bold"),
            padx=20, pady=7)
        self.btn_toggle.pack(side="left")
        self.status = tk.Label(head, text="待机", bg=themed(BG),
                               fg=themed(FAINT),
                               font=("Microsoft YaHei UI", 10))
        self.status.pack(side="left", padx=16)
        self.mode_label = tk.Label(head, text="", bg=themed(BG),
                                   fg=themed(GREEN),
                                   font=("Microsoft YaHei UI", 9))
        self.mode_label.pack(side="left", padx=8)
        tk.Button(head, text="⚙ 设置", command=self._open_settings,
                  bg=themed(TRACK), fg=themed(SUB),
                  activebackground=themed(CARD_EDGE), relief="flat",
                  font=("Microsoft YaHei UI", 10), padx=16,
                  pady=6).pack(side="right")

        body = tk.Frame(self, bg=themed(BG))
        body.pack(fill="both", expand=True, padx=18, pady=(0, 8))

        left = tk.Frame(body, bg=themed(BG))
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="录音列表", bg=themed(BG), fg=themed(SUB),
                 font=("Microsoft YaHei UI", 9, "bold"),
                 anchor="w").pack(fill="x")
        wrap = tk.Frame(left, bg=themed(CARD), highlightbackground=themed(
            CARD_EDGE), highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.listbox = tk.Listbox(
            wrap, bg=themed(CARD), fg=themed(TEXT), selectbackground=themed(
                CARD_EDGE), selectforeground=themed(TEXT), relief="flat",
            highlightthickness=0, font=("Consolas", 9), activestyle="none")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(8, 0),
                          pady=8)
        # 纵向滚动条仅在录音条数超过列表可视高度时显示
        self.list_scroll = attach_auto_scrollbar(
            wrap, self.listbox, orient="vertical", layout="pack",
            side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = tk.Frame(body, bg=themed(BG))
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))
        tk.Label(right, text="实时状态", bg=themed(BG), fg=themed(SUB),
                 font=("Microsoft YaHei UI", 9, "bold"),
                 anchor="w").pack(fill="x")
        meter_box = tk.Frame(right, bg=themed(CARD), highlightbackground=themed(
            CARD_EDGE), highlightthickness=1)
        meter_box.pack(fill="x", pady=(4, 8))
        self.meter = tk.Canvas(meter_box, height=16, bg=themed(TRACK),
                               highlightthickness=0)
        self.meter.pack(fill="x", padx=12, pady=(12, 4))
        self.meter_fill = self.meter.create_rectangle(0, 0, 0, 16,
                                                      fill=themed(GREEN),
                                                      outline="")
        self.meter_text = tk.Label(meter_box, text="0.0 秒 · 未录音",
                                   bg=themed(CARD), fg=themed(FAINT),
                                   font=("Microsoft YaHei UI", 9),
                                   anchor="w")
        self.meter_text.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(right, text="识别文字", bg=themed(BG), fg=themed(SUB),
                 font=("Microsoft YaHei UI", 9, "bold"),
                 anchor="w").pack(fill="x")
        self.text = tk.Text(right, height=8, bg=themed(CARD),
                            fg=themed(TEXT), insertbackground=themed(TEXT),
                            relief="flat", wrap="word",
                            font=("Microsoft YaHei UI", 10), padx=10, pady=8)
        self.text.pack(fill="both", expand=True, pady=(4, 8))
        self.text.insert("1.0", "（录制或转文字的结果会显示在这里）")
        self.asr_hint = tk.Label(right, text="", bg=themed(BG),
                                 fg=themed(AMBER),
                                 font=("Microsoft YaHei UI", 8), anchor="w")
        self.asr_hint.pack(fill="x")

        foot = tk.Frame(self, bg=themed(BG))
        foot.pack(fill="x", padx=18, pady=(0, 14))
        for text, cmd, color in (("▶ 播放", self._play, GREEN),
                                 ("■ 停止", self._stop_play, AMBER),
                                 ("📝 转文字", self._transcribe, SUB),
                                 ("🗑 删除", self._delete, RED),
                                 ("📁 目录", self._open_save_dir, SUB)):
            tk.Button(foot, text=text, command=cmd, bg=themed(TRACK),
                      fg=themed(color), activebackground=themed(CARD_EDGE),
                      relief="flat", font=("Microsoft YaHei UI", 10),
                      padx=16, pady=6).pack(side="left", padx=(0, 8))
        self.count_label = tk.Label(foot, text="", bg=themed(BG),
                                    fg=themed(FAINT),
                                    font=("Microsoft YaHei UI", 8))
        self.count_label.pack(side="right")

        self._refresh_list()

    # -- 监测 -------------------------------------------------------------
    def _toggle_monitor(self) -> None:
        if self.recorder is None:
            self._start_monitor()
        else:
            self._stop_monitor()

    def _sync_asr(self, warm: bool = True) -> None:
        """配置没变就复用实例（避免重新加载模型），并后台预热。"""
        key = asr_engine_key(self.cfg)
        if getattr(self, "asr", None) is None or getattr(self, "_asr_key", None) != key:
            self.asr = make_asr_engine(self.cfg)
            self._asr_key = key
        else:
            # 仅词表变化不需要重建引擎（sherpa 忽略词表，Vosk 下次 begin 生效）
            self.asr.grammar = self.cfg.get("asr_grammar", "")
        if warm:
            # 流式模式只需加载流式模型；两个 sherpa 模型同时驻留约 400MB
            want_stream = bool(int(self.cfg.get("stream_asr", 1) or 0))
            eng = self.asr
            threading.Thread(target=eng.preload, args=(want_stream,),
                             daemon=True).start()

    def _start_monitor(self) -> None:
        self.cfg = load_config()
        self._sync_asr()
        self._refresh_mode()
        self.recorder = Recorder(self.events,
                                 int(self.cfg.get("max_seconds", 30)))
        self.recorder.start()
        self.btn_toggle.configure(text="■ 结束监测", bg=themed(RED),
                                  fg="#2b0b0b")
        self.status.configure(text="监测中 · 按住鼠标语音键说话", fg=themed(GREEN))
        if not self.asr.available():
            self.asr_hint.configure(
                text="未启用语音识别（%s）：仅录音。"
                     "装上 sherpa-onnx 或 vosk 及中文模型后可用。"
                     % (self.asr.error or "不可用"))

    def _stop_monitor(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()
            self.recorder = None
        self.btn_toggle.configure(text="● 开始监测", bg=themed(GREEN),
                                  fg="#0b2c18")
        self.status.configure(text="已结束监测", fg=themed(FAINT))

    # -- 事件轮询 ---------------------------------------------------------
    def _dispatch(self, item) -> None:
        """分发单个队列事件；异常由 _poll 隔离，不能拖垮轮询链。"""
        kind = item[0]
        if kind == "start":
            self._on_rec_start()
        elif kind == "audio":
            self._on_audio(item[1])
        elif kind == "segment":
            self._on_segment(item[1], item[2], item[3])
        elif kind == "key":
            self._on_key(item[1])
        elif kind == "error":
            self.status.configure(text=item[1], fg=themed(RED))
        elif kind == "asr_ready":
            self._asr_active = True
        elif kind == "asr_text":
            self._publish_text(item[1])
        elif kind == "asr_backend":
            self.asr_hint.configure(text="识别来源：%s" % item[1])
            self.status.configure(text="识别完成 · %s" % item[1],
                                  fg=themed(GREEN))
        elif kind == "asr_unavailable":
            self.asr_hint.configure(text=item[1])

    def _poll(self) -> None:
        try:
            # 持续记录用户最近停留的「外部」输入框（每 0.4 秒一次）
            now = time.monotonic()
            if now - self._focus_poll_at >= 0.4:
                self._focus_poll_at = now
                try:
                    target = vt.track_focus(exclude_pid=os.getpid())
                    if target is not None:
                        self._focus_target = target
                except Exception:
                    pass
            budget = 120      # 单轮上限，避免音频帧洪泛饿死 segment/其它事件
            while budget > 0:
                try:
                    item = self.events.get_nowait()
                except queue.Empty:
                    break
                budget -= 1
                try:
                    self._dispatch(item)
                except Exception as exc:
                    # 单个事件失败只记录，绝不能让 after() 调度丢失
                    msg = "[voice] 事件 %s 处理失败: %r" % (item[0], exc)
                    print(msg, file=sys.stderr, flush=True)
                    try:
                        self.status.configure(text=msg[:60], fg=themed(RED))
                    except Exception:
                        pass
        finally:
            # 无论上面发生什么，都必须重新调度，否则整个语音功能静默失效
            try:
                self.after(0 if not self.events.empty() else 40, self._poll)
            except tk.TclError:
                pass

    def _on_rec_start(self) -> None:
        self._partial = ""
        self._asr_active = False
        self._reset_stream_typing()
        # 记录剪贴板基线：官方驱动识别完成后会写入剪贴板
        self._clip_before = clipboard_sequence()
        streaming = bool(int(self.cfg.get("stream_asr", 1) or 0))
        self.status.configure(
            text=("● 录音中…（实时转写）" if streaming
                  else "● 录音中…（松开后转写）"),
            fg=themed(RED))
        self._set_text("")
        if not streaming:
            # 整段模式：录音期间完全不加载识别器，松开后对 WAV 识别一次
            self._stream_decoder = None
            return
        # 流式模式：用与 decode_frames_local 完全一致的增量解码器，
        # 否则喂给 Vosk 的是未解扰的 ADPCM 噪声（旧版 decode_frame 的坑）
        self._stream_decoder = av.LocalStreamDecoder()

        def init_asr():
            if self.asr.begin():
                self.events.put(("asr_ready", None))
            else:
                self.events.put(("asr_unavailable",
                                 "语音识别不可用（%s），本条只保存音频。"
                                 % (self.asr.error or "未知原因")))
        threading.Thread(target=init_asr, daemon=True).start()

    def _on_audio(self, frame: bytes) -> None:
        decoder = getattr(self, "_stream_decoder", None)
        # 流式模式用 XOR 解扰 + 跨帧连续 IMA 的正确 PCM；
        # 整段模式不喂 ASR，用轻量单帧解码仅显示音量条
        samples = (decoder.feed(frame) if decoder is not None
                   else av.decode_frame(frame))
        if not samples:
            return
        if self._asr_active:
            # 每帧都要喂（连续流不能丢），但不解析部分结果
            self.asr.feed(av.samples_to_pcm16(samples))
        # 音量条与部分结果约 10Hz 更新即可，避免每秒数百次 Tk 刷新
        now = time.monotonic()
        if now - self._ui_tick < 0.1:
            return
        self._ui_tick = now
        peak = max(abs(s) for s in samples) or 1
        width = self.meter.winfo_width() or 300
        self.meter.coords(self.meter_fill, 0, 0,
                          int(width * min(1.0, peak / 30000)), 16)
        self.meter.itemconfigure(
            self.meter_fill,
            fill=themed(GREEN if peak < 24000 else AMBER))
        if self._asr_active:
            partial = self.asr.partial()
            if partial and partial != self._partial:
                self._partial = partial
                self._set_text(partial)
                # 「语音输入到焦点」开启时，边说边把稳定增量键入输入框
                self._type_stream_partial(partial)

    def _on_key(self, arg: int) -> None:
        label = {0x33: "单击（回车/发送）", 0x37: "长按按下", 0x31: "长按按下",
                 0x38: "长按抬起", 0x32: "长按抬起"}.get(
                     arg, "按键 0x%02X" % arg)
        if arg in (0x37, 0x31):
            self.status.configure(text="● 录音中… (%s)" % label,
                                  fg=themed(RED))
        elif arg in (0x38, 0x32):
            self.status.configure(text="松开 · 处理中…", fg=themed(AMBER))

    def _on_segment(self, frames: list, duration: float, reason: str) -> None:
        had_stream = self._asr_active      # 流式识别是否真的跑过
        final = ""
        if had_stream:
            final = self.asr.finish()
        self._asr_active = False
        self._stream_decoder = None        # 下一段录音重建，避免状态串段
        if not final:
            self._reset_stream_typing()    # 本段没有最终结果，清空流式键入状态
        self.meter.coords(self.meter_fill, 0, 0, 0, 16)
        if not frames:
            self.status.configure(text="没录到音频（%s）" % (reason or "无数据"),
                                  fg=themed(AMBER))
            return
        samples = av.decode_frames_local(frames)
        cutoff = int(self.cfg.get("highpass", 0) or 0)
        if cutoff > 0:
            samples = av.highpass(samples, cutoff=cutoff)
        peak = int(self.cfg.get("peak", 26000) or 26000)
        samples = av.normalize(samples, peak)
        # 可选降噪
        strength = int(self.cfg.get("denoise", 0) or 0)
        if strength > 0:
            samples = self._denoise(samples, strength)
        real = len(samples) / av.SAMPLE_RATE
        save_audio = bool(int(self.cfg.get("save_audio", 1) or 0))
        if save_audio:
            save_dir = self.cfg.get("save_dir") or DEFAULT_SAVE
            os.makedirs(save_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(save_dir, "voice_%s.wav" % stamp)
            av.save_wav(path, samples)
            self._refresh_list()
            self.selected = path
            self._sync_selection()
            self.meter_text.configure(text="%.1f 秒 · 已保存" % real)
            self.status.configure(
                text="已保存 · %.1f 秒（%s）" % (real, reason or "正常结束"),
                fg=themed(GREEN))
        else:
            self.meter_text.configure(text="%.1f 秒 · 未保存" % real)
            self.status.configure(
                text="已录制 %.1f 秒（不保存语音）" % real, fg=themed(GREEN))
        if final:
            self._publish_text(final)
        elif self._partial:
            self._set_text(self._partial)
        # 有最终结果就绝不重复识别；没结果且自动转文字开着才回退整段识别
        auto = int(self.cfg.get("auto_transcribe", 1) or 0)
        if final:
            return
        if auto:
            self.asr_hint.configure(
                text=("流式未得到文字，已回退整段识别" if had_stream
                      else "松开后整段识别中…"))
            if save_audio:
                self._transcribe(allow_clipboard=True)
            else:
                # 没存 WAV：直接用刚录的 PCM 做整段识别（纯本地 Vosk）
                self._transcribe_samples(samples)
        else:
            self.asr_hint.configure(
                text="本段未识别到文字（自动转文字已关闭）")

    def _transcribe_samples(self, samples: list[int]) -> None:
        """不保存 WAV 时的整段识别：内存 PCM → 本地引擎 → asr_text 事件。"""
        def work():
            text = (self.asr.transcribe_samples(samples)
                    if self.asr.available() else None)
            if text:
                self.events.put(("asr_text", text))
                self.events.put(("asr_backend",
                                 "%s（内存音频）" % getattr(self.asr, "label", "Vosk")))
            else:
                self.events.put(("asr_unavailable",
                                 "整段识别未得到文字（未保存语音，仅本地识别）"))
        threading.Thread(target=work, daemon=True).start()

    def _denoise(self, samples: list[int], strength: int) -> list[int]:
        try:
            import numpy as np
            import noisereduce as nr
        except Exception:
            self.asr_hint.configure(text="降噪需要 noisereduce，已跳过")
            return samples
        try:
            x = np.asarray(samples, dtype=np.float32)
            y = nr.reduce_noise(y=x, sr=av.SAMPLE_RATE, stationary=False,
                                prop_decrease=strength / 100.0,
                                n_fft=512, win_length=512, hop_length=128,
                                time_mask_smooth_ms=50,
                                freq_mask_smooth_hz=200)
            return [int(v) for v in y]
        except Exception:
            return samples

    def _set_text(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)

    def _reset_stream_typing(self) -> None:
        """每段录音开始时清空流式键入状态。"""
        self._typed_partial = ""     # 已经键入到输入框的、稳定的部分结果
        self._stream_type_failed = False

    def _type_stream_partial(self, partial: str) -> None:
        """流式输入：只键入比上次稳定前缀多出来的部分。

        Vosk 的 PartialResult 是**整句假设**，每次都从头返回；直接整段键入
        会重复。策略：找到已键入前缀与当前 partial 的最长公共前缀，
        只键入新增后缀；假设回退时不撤字（避免误删用户内容），
        等最终结果到达时在 ``_publish_text`` 里用退格纠正。
        """
        if not partial:
            return
        if not int(self.cfg.get("voice_typing", 0) or 0):
            return
        if self._stream_type_failed or not vt.supported():
            return
        target = self._focus_target
        if target is None:
            return
        typed = getattr(self, "_typed_partial", "")
        # 只信任「已键入内容 + 新增后缀」这种前缀式增长
        if not partial.startswith(typed):
            return
        delta = partial[len(typed):]
        if not delta:
            return
        ok, _msg = vt.type_text(delta, target)
        if ok:
            self._typed_partial = partial
        else:
            self._stream_type_failed = True
            self.asr_hint.configure(text="流式输入失败，本段停止自动键入")

    def _publish_text(self, value: str) -> None:
        """显示最终识别结果；开关打开时同时键入外部焦点输入框。"""
        value = normalize_asr_text(value)   # 兜底云端/剪贴板等所有来源
        if not value:
            self._reset_stream_typing()
            return
        self._set_text(value)               # 界面始终显示完整最终结果

        if not int(self.cfg.get("voice_typing", 0) or 0):
            self._reset_stream_typing()
            return
        if not vt.supported():
            self.asr_hint.configure(text="语音输入仅支持 Windows")
            self._reset_stream_typing()
            return
        target = self._focus_target
        if target is None:
            self.asr_hint.configure(
                text="语音输入：未检测到外部输入框，请说话前先点好目标输入框")
            self.status.configure(text="未检测到外部输入框", fg=themed(AMBER))
            self._reset_stream_typing()
            return

        # 流式已键入一部分：只纠正差异，不重复整段
        typed = getattr(self, "_typed_partial", "")
        to_type = value
        if typed and not self._stream_type_failed:
            common = 0
            for a, b in zip(typed, value):
                if a != b:
                    break
                common += 1
            backspaces = len(typed) - common
            # 退格数为 0（流式输入已是最终结果）时 send_inputs([]) 会返回
            # False，不能据此判定「纠正失败」而整段重输 —— 那样会输入两次
            if backspaces == 0:
                to_type = value[common:]
            elif vt.send_inputs(vt.build_backspace_inputs(backspaces)):
                to_type = value[common:]
            else:
                to_type = value          # 退格失败，退回整段键入

        self._reset_stream_typing()
        if not to_type:
            self.asr_hint.configure(text="语音输入：已实时键入完成")
            self.status.configure(text="已键入焦点输入框", fg=themed(GREEN))
            return
        ok, msg = vt.type_text(to_type, target)
        self.asr_hint.configure(text="语音输入：%s" % msg)
        self.status.configure(text=("已键入焦点输入框" if ok else "键入失败"),
                              fg=themed(GREEN if ok else AMBER))

    # -- 列表与操作 -------------------------------------------------------
    def _refresh_list(self) -> None:
        save_dir = self.cfg.get("save_dir") or DEFAULT_SAVE
        self.listbox.delete(0, "end")
        self._paths: list[str] = []
        if not os.path.isdir(save_dir):
            self.count_label.configure(text="0 条")
            self._refresh_list_scroll()
            return
        files = sorted((f for f in os.listdir(save_dir)
                        if f.lower().endswith(".wav")), reverse=True)
        for name in files:
            path = os.path.join(save_dir, name)
            self._paths.append(path)
            self.listbox.insert("end", "  %s   %s" % (name, self._duration(path)))
        self.count_label.configure(text="%d 条" % len(files))
        self._refresh_list_scroll()

    def _refresh_list_scroll(self) -> None:
        """列表内容变化后重新判定滚动条显隐（等布局完成再算）。"""
        bar = getattr(self, "list_scroll", None)
        if bar is not None:
            try:
                self.after_idle(bar.refresh)
            except tk.TclError:
                pass

    def _open_save_dir(self) -> None:
        """在资源管理器中打开当前音频保存目录。"""
        save_dir = self.cfg.get("save_dir") or DEFAULT_SAVE
        try:
            os.makedirs(save_dir, exist_ok=True)
            starter = getattr(os, "startfile", None)
            if starter is None:
                messagebox.showinfo("提示", "仅支持 Windows 资源管理器",
                                    parent=self)
                return
            starter(save_dir)
            self.status.configure(text="已打开保存目录", fg=themed(GREEN))
        except Exception as exc:
            messagebox.showerror(
                "打开失败", "无法打开目录：\n%s\n\n%r" % (save_dir, exc),
                parent=self)

    @staticmethod
    def _duration(path: str) -> str:
        try:
            # 16kHz / 16bit / 单声道 WAV：44 字节头 + 32000 字节/秒。
            # 列表可能有很多录音，直接按文件大小估算，避免逐个 wave.open。
            seconds = (os.path.getsize(path) - 44) / 32000.0
            if 0 <= seconds < 3600:
                return "%5.1fs" % seconds
            with wave.open(path, "rb") as fh:
                seconds = fh.getnframes() / float(fh.getframerate())
            return "%5.1fs" % seconds
        except Exception:
            return "  ?  "

    def _on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self._paths):
            self.selected = self._paths[sel[0]]
            self.status.configure(text="已选中 %s" %
                                  os.path.basename(self.selected),
                                  fg=themed(SUB))

    def _sync_selection(self) -> None:
        if not self.selected:
            return
        for i, path in enumerate(self._paths):
            if path == self.selected:
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.see(i)
                break

    def _play(self) -> None:
        if not self.selected or not os.path.exists(self.selected):
            messagebox.showinfo("提示", "请先选中一条录音", parent=self)
            return
        try:
            import winsound
            winsound.PlaySound(self.selected,
                               winsound.SND_FILENAME | winsound.SND_ASYNC)
            self._playing = True
            self.status.configure(text="播放中 · %s" %
                                  os.path.basename(self.selected),
                                  fg=themed(GREEN))
        except Exception as exc:
            messagebox.showerror("播放失败", str(exc), parent=self)

    def _stop_play(self) -> None:
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
            self._playing = False
            self.status.configure(text="已停止播放", fg=themed(FAINT))
        except Exception:
            pass

    def _delete(self) -> None:
        if not self.selected or not os.path.exists(self.selected):
            messagebox.showinfo("提示", "请先选中一条录音", parent=self)
            return
        name = os.path.basename(self.selected)
        if not messagebox.askyesno("删除录音",
                                   "确定删除 %s 吗？此操作不可恢复。" % name,
                                   parent=self):
            return
        try:
            os.remove(self.selected)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            return
        self.selected = None
        self._refresh_list()
        self.status.configure(text="已删除 %s" % name, fg=themed(FAINT))

    def _refresh_mode(self) -> None:
        """刷新顶部模式徽标与实时区的解码/后端提示。"""
        local = int(self.cfg.get("local_only", 1) or 0)
        eng_label = getattr(self.asr, "label", "Vosk")
        if local:
            backend = "仅本地 %s" % eng_label
        else:
            backend = {0: "本地优先", 1: "Vosk", 2: "剪贴板",
                       3: "云端 ASR"}.get(
                int(self.cfg.get("asr_backend", 0) or 0), "自动")
            if backend == "Vosk":
                backend = eng_label
        gram = ("词表限制" if (self.cfg.get("asr_grammar", "") or "").strip()
                else "通用识别")
        has_grammar = bool((self.cfg.get("asr_grammar", "") or "").strip())
        # 大模型 / sherpa 都不支持 runtime grammar
        if has_grammar and not self.asr.grammar_supported():
            gram = "词表不适用(当前引擎)" if \
                getattr(self.asr, "name", "vosk") != "vosk" else "词表不适用(大模型)"
        big_ready = os.path.isdir(BIG_MODEL_DIR)
        using_big = os.path.normpath(
            self.cfg.get("model_dir", DEFAULT_MODEL)) == os.path.normpath(
                BIG_MODEL_DIR)
        typing_on = bool(int(self.cfg.get("voice_typing", 0) or 0))
        streaming = bool(int(self.cfg.get("stream_asr", 1) or 0))
        model = self._model_caption()
        parts = ["🟢 纯本地解码", backend, gram]
        if using_big and getattr(self.asr, "name", "vosk") == "vosk":
            parts.append("大模型")
        parts.append("实时转写" if streaming else "整段转写")
        if typing_on:
            parts.append("⌨语音输入")
        self.mode_label.configure(text=" · ".join(parts))
        hint = "解码：纯本地（XOR+连续 IMA）｜识别：%s｜模式：%s｜模型：%s" % (
            backend, "边说边转" if streaming else "松开后整段识别", model)
        if (big_ready and not using_big
                and getattr(self.asr, "name", "vosk") == "vosk"):
            hint += "｜已装大模型，可在设置里把 model_dir 指向 vosk-model-cn-0.22"
        # 自动模式下退回 Vosk 时，提示有更高准确率的引擎可装
        if getattr(self.asr, "sherpa_hint", ""):
            hint += "｜未启用 sherpa（%s），可跑 tools\\download_models.py 下载模型提升准确率" % (
                self.asr.sherpa_hint)
        # 引擎不可用的原因由 _start_monitor / _refresh_asr_state 提示，
        # 这里不调 available()（首次 import vosk 很慢，会卡住界面刷新）
        self.asr_hint.configure(text=hint)

    def _model_caption(self) -> str:
        """当前引擎实际使用的模型名，用于底部提示。"""
        if getattr(self.asr, "name", "vosk") == "sherpa":
            parts = []
            if getattr(self.asr, "stream_ready", lambda: False)():
                parts.append("paraformer 流式")
            if getattr(self.asr, "offline_ready", lambda: False)():
                parts.append("SenseVoice 整段")
            return " + ".join(parts) or "未就绪"
        return os.path.basename(os.path.normpath(
            self.cfg.get("model_dir", DEFAULT_MODEL)))

    def _backend_chain(self, allow_clipboard: bool) -> list[str]:
        """按设置返回识别后端优先级；纯本地模式强制只用 Vosk。"""
        if int(self.cfg.get("local_only", 1) or 0):
            return ["vosk"]
        mode = int(self.cfg.get("asr_backend", 0) or 0)
        if mode == 1:
            return ["vosk"]
        if mode == 2:
            return ["clipboard"] if allow_clipboard else []
        if mode == 3:
            return ["cloud"]
        # 本地优先：Vosk 可用时完全不联网、不读剪贴板
        chain = ["vosk", "cloud"]
        if allow_clipboard:
            chain.append("clipboard")
        return chain

    def _transcribe(self, allow_clipboard: bool = False) -> None:
        if not self.selected or not os.path.exists(self.selected):
            hint = ("当前「保存语音」已关闭，本轮没有可转文字的录音文件。\n"
                    "请在设置里开启「保存语音」，或直接按住语音键重新录制。"
                    if not bool(int(self.cfg.get("save_audio", 1) or 0))
                    else "请先选中一条录音")
            messagebox.showinfo("提示", hint, parent=self)
            return
        chain = self._backend_chain(allow_clipboard)
        if not chain:
            messagebox.showinfo(
                "提示", "当前后端「剪贴板桥接」只在刚录制完时可用；\n"
                "请在设置里改成「自动 / Vosk / 云端」。", parent=self)
            return
        self.status.configure(text="识别中…", fg=themed(AMBER))
        path = self.selected
        before = self._clip_before if allow_clipboard else 0

        labels = {"cloud": "云端 ASR", "vosk": "Vosk",
                  "clipboard": "剪贴板桥接"}

        def work():
            text = None
            used = ""
            for backend in chain:
                if backend == "cloud":
                    try:
                        import aimouse_cloud_asr as ca
                        text = ca.transcribe_wav(path)
                    except Exception:
                        text = None
                elif backend == "vosk":
                    text = (self.asr.transcribe_file(path)
                            if self.asr.available() else None)
                elif backend == "clipboard":
                    text = wait_clipboard_result(before, timeout=2.5) or None
                if text:
                    used = labels.get(backend, backend)
                    break
            if text:
                self.events.put(("asr_text", text))
                self.events.put(("asr_backend", used))
            else:
                self.events.put(("asr_unavailable",
                                 "未得到识别结果（已尝试：%s）"
                                 % "、".join(labels.get(b, b) for b in chain)))
        threading.Thread(target=work, daemon=True).start()

    # -- 设置 -------------------------------------------------------------
    def _open_settings(self) -> None:
        def done(cfg):
            save_config(cfg)
            self.cfg = cfg
            self._sync_asr()
            self._refresh_mode()
            self._refresh_list()
            self.status.configure(text="设置已保存", fg=themed(GREEN))
        VoiceSettingsDialog(self, self.cfg, done)

    def _close(self) -> None:
        self._stop_monitor()
        self._stop_play()
        try:
            theme.apply_new(self, "panel")
        except Exception:
            pass
        if self._on_close_cb:
            self._on_close_cb()
        self.destroy()


def open_window(parent, on_close=None) -> VoiceWindow:
    return VoiceWindow(parent, on_close=on_close)
