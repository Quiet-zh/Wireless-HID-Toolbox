# -*- coding: utf-8 -*-
"""voice_service.py —— 语音监听独立组件（不依赖 Tk）。

从 ``aimouse_voice_panel.py`` 抽出的可复用核心：

* :class:`Recorder`            监听 0xFF91，按语音键状态切分录音段
* :class:`AsrEngine`           Vosk 离线识别（sherpa 由 ``make_asr_engine`` 选择）
* :class:`VoiceInputService`   按住语音键说话 → 识别 → 键入焦点输入框

语音窗口继续复用这里的类与配置；本模块不 import tkinter，
后台的鼠标按键映射守护进程可以直接创建 :class:`VoiceInputService`。
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import wave
from typing import Optional

import aimouse_voice as av
import aimouse_voice_capture as avc
import hid_win as hw
import tray_common as tc
import voice_typing as vt

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
    ("asr_refine", "收尾高精度校正",
     "1=松手后用 SenseVoice 再识别一次定稿（约 0.2 秒，更准、带标点）；0=只用流式结果",
     1, 0, 1, 1, "bool"),
    ("onset_gate", "前导静音门控",
     "1=按能量裁掉开头底噪再识别（句首不再「听出」假字）；0=原样送引擎",
     1, 0, 1, 1, "bool"),
    ("onset_factor", "门控灵敏度",
     "底噪的多少倍算开始说话（单位 0.1 倍：35=3.5 倍）；越大裁得越多，太大可能削掉轻声",
     35, 10, 100, 5, "int"),
    ("max_seconds", "单次最长录制", "超过该秒数自动结束并保存",
     30, 5, 120, 5, "int"),
    ("monitor_on_close", "关闭界面后仍监测",
     "1=关闭语音窗口后继续监听语音键（窗口隐藏，点🎤可再打开）；0=关闭即停止监测",
     0, 0, 1, 1, "bool"),
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


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def load_config(path: str | None = None) -> dict:
    """读取语音配置；``path`` 为空时用默认 CONFIG_PATH。

    显式传路径是为了让语音面板保留 ``CONFIG_PATH`` 可 patch 的测试习惯。
    """
    cfg = dict(DEFAULTS)
    path = path or CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    cfg[key] = data[key]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict, path: str | None = None) -> None:
    path = path or CONFIG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


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
        # 前导静音门控参数：面板按设置写入；None 表示不启用
        self.onset_kwargs: Optional[dict] = {}

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
            self._gate = (av.OnsetGate(**self.onset_kwargs)
                          if self.onset_kwargs is not None else None)
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


def onset_kwargs(cfg: dict):
    """把设置里的门控参数翻译成 :class:`aimouse_voice.OnsetGate` 的入参。

    ``onset_gate=0`` 返回 None，引擎据此完全不裁剪。
    ``onset_factor`` 用整数存 0.1 倍（25 表示底噪的 2.5 倍），
    方便复用现有「输入框 + 加减按钮」的参数行。
    """
    if not int(cfg.get("onset_gate", 1) or 0):
        return None
    try:
        factor = int(cfg.get("onset_factor", 35) or 35) / 10.0
    except (TypeError, ValueError):
        factor = av.ONSET_FLOOR_FACTOR
    return {"floor_factor": max(1.0, min(factor, 10.0))}

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
# 独立语音输入服务（鼠标按键映射使用）
# ---------------------------------------------------------------------------
VOICE_VID_PID = (0x248A, 0x60AB)


class VoiceInputService:
    """按住魔声语音键说话 → 识别 → 键入当前焦点输入框。

    与语音窗口共享 :class:`Recorder` / :class:`AsrEngine` / 配置文件，
    但不依赖 Tk，也不需要窗口：鼠标按键映射的「语音输入」动作创建本类后，
    按住语音键即可说话，松开后自动出字并键入。

    只适用于 ``248A:60AB``：该设备的 0x1B 音频帧只在按住语音键期间上报，
    其他鼠标没有可用的麦克风通道，因此配置层只允许把语音输入绑定到语音键。
    """

    def __init__(self, cfg: dict | None = None, on_status=None,
                 on_text=None):
        self.cfg = dict(cfg) if cfg else load_config()
        self.on_status = on_status or (lambda _text: None)
        self.on_text = on_text or (lambda _text: None)
        self.events: queue.Queue = queue.Queue()
        self.recorder: Optional[Recorder] = None
        self.asr = None
        self.running = False
        self.last_text = ""
        self.last_error = ""
        self._stop = threading.Event()
        self._thread = None
        self._decoder = None
        self._partial = ""
        self._asr_active = False
        self._focus_target = None
        self._focus_poll_at = 0.0
        self._segment_gen = 0
        self._lock = threading.Lock()

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> bool:
        """打开 0xFF91 并开始监听语音键；失败返回 False。"""
        if self.running:
            return True
        # 上一次会话/失败重试可能留下旧事件，先清空，避免重启后把旧音频
        # 再识别一遍并重复键入。
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass
        if avc.find_interface() is None:
            self.last_error = "未找到 248A:60AB 的 0xFF91 语音接口"
            self.on_status(self.last_error)
            return False
        self.asr = make_asr_engine(self.cfg)
        self.asr.onset_kwargs = onset_kwargs(self.cfg)
        threading.Thread(target=self._preload, daemon=True,
                         name="voice-input-preload").start()
        self.recorder = Recorder(self.events,
                                 int(self.cfg.get("max_seconds", 30) or 30))
        try:
            self.recorder.start()
        except Exception as exc:      # 设备被别的进程独占等
            self.last_error = "语音监听启动失败：%r" % (exc,)
            self.on_status(self.last_error)
            self.recorder = None
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="voice-input-service")
        self._thread.start()
        self.running = True
        self.on_status("语音输入待命 · 按住语音键说话")
        return True

    def alive(self) -> bool:
        """录音线程与事件泵都还活着才算可用。"""
        return (self.running and self.recorder is not None
                and self.recorder.is_alive() and self._thread is not None
                and self._thread.is_alive())

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop.set()
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recorder = None
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self.on_status("语音输入已停止")

    def _preload(self) -> None:
        try:
            streaming = bool(int(self.cfg.get("stream_asr", 1) or 0))
            refine = bool(int(self.cfg.get("asr_refine", 1) or 0))
            if not streaming:
                target = False
            elif refine:
                target = None
            else:
                target = True
            self.asr.preload(target)
        except Exception:
            pass

    # -- 事件循环 ------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            if now - self._focus_poll_at >= 0.4:
                self._focus_poll_at = now
                try:
                    target = vt.track_focus(exclude_pid=os.getpid())
                    if target is not None:
                        self._focus_target = target
                except Exception:
                    pass
            try:
                item = self.events.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._dispatch(item)
            except Exception as exc:
                self.last_error = "语音事件 %s 处理失败：%r" % (item[0], exc)
                self.on_status(self.last_error)

    def _dispatch(self, item) -> None:
        kind = item[0]
        if kind == "start":
            self._on_start()
        elif kind == "audio":
            self._on_audio(item[1])
        elif kind == "segment":
            self._on_segment(item[1], item[2], item[3])
        elif kind == "key":
            self._on_key(item[1])
        elif kind == "error":
            self.last_error = str(item[1])
            self.on_status(self.last_error)
        elif kind == "asr_ready":
            self._asr_active = True
        elif kind == "asr_unavailable":
            self.last_error = str(item[1])
            self.on_status(self.last_error)

    def _on_start(self) -> None:
        self._partial = ""
        self._asr_active = False
        self._segment_gen += 1
        # 说话前先点好目标输入框；这里再抓一次，避免用很久以前的窗口
        try:
            target = vt.track_focus(exclude_pid=os.getpid())
            if target is not None:
                self._focus_target = target
        except Exception:
            pass
        streaming = bool(int(self.cfg.get("stream_asr", 1) or 0))
        self.on_status("语音输入：录音中…" if streaming
                       else "语音输入：录音中（松开后识别）…")
        if not streaming:
            self._decoder = None
            return
        self._decoder = av.LocalStreamDecoder()

        def init() -> None:
            if self.asr is not None and self.asr.begin():
                self.events.put(("asr_ready", None))
            else:
                self.events.put((
                    "asr_unavailable",
                    "语音识别不可用（%s），本条只显示文字"
                    % (getattr(self.asr, "error", "") or "未知原因"),
                ))

        threading.Thread(target=init, daemon=True,
                         name="voice-input-asr-init").start()

    def _on_audio(self, frame: bytes) -> None:
        decoder = self._decoder
        if decoder is None:
            return
        samples = decoder.feed(frame)
        if not samples or not self._asr_active or self.asr is None:
            return
        self.asr.feed(av.samples_to_pcm16(samples))

    def _on_key(self, arg: int) -> None:
        if arg in (0x37, 0x31):
            self.on_status("语音输入：录音中…")
        elif arg in (0x38, 0x32):
            self.on_status("语音输入：松开 · 识别中…")

    def _on_segment(self, frames: list, duration: float, reason: str) -> None:
        had_stream = self._asr_active
        final = ""
        if had_stream and self.asr is not None:
            final = self.asr.finish()
        self._asr_active = False
        self._decoder = None
        if not frames:
            self.on_status("语音输入：没录到音频（%s）" % (reason or "无数据"))
            return
        samples = av.decode_frames_local(frames)
        cutoff = int(self.cfg.get("highpass", 0) or 0)
        if cutoff > 0:
            samples = av.highpass(samples, cutoff=cutoff)
        peak = int(self.cfg.get("peak", 26000) or 26000)
        samples = av.normalize(samples, peak)
        if not final:
            final = self._transcribe_samples(samples) or ""
        if final and self._should_refine():
            final = self._refine(samples) or final
        text = normalize_asr_text(final)
        if not text:
            self.last_error = "语音输入：没有识别到文字"
            self.on_status(self.last_error)
            return
        if self._stop.is_set():
            return
        self.last_text = text
        self.on_text(text)
        self._type_text(text)

    def _transcribe_samples(self, samples: list[int]) -> str:
        if self.asr is None:
            return ""
        try:
            return self.asr.transcribe_samples(samples) or ""
        except Exception as exc:
            self.last_error = "整段识别失败：%r" % (exc,)
            return ""

    def _should_refine(self) -> bool:
        if not bool(int(self.cfg.get("asr_refine", 1) or 0)):
            return False
        eng = self.asr
        return (getattr(eng, "name", "vosk") == "sherpa"
                and getattr(eng, "offline_ready", lambda: False)())

    def _refine(self, samples: list[int]) -> str:
        """用 SenseVoice 对已解码 PCM 再识别一次；失败返回空串。"""
        try:
            better = self.asr.transcribe_samples(samples)
            return normalize_asr_text(better or "")
        except Exception:
            return ""

    def _type_text(self, text: str) -> None:
        if not vt.supported():
            self.on_status("语音输入仅支持 Windows")
            return
        target = self._focus_target
        if target is None:
            self.on_status("未检测到外部输入框，已识别但未键入：%s" % text)
            return
        ok, msg = vt.type_text(text, target)
        self.on_status(("已键入焦点输入框：%s" % text) if ok
                       else ("键入失败：%s" % msg))
