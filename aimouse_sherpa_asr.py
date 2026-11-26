# -*- coding: utf-8 -*-
"""aimouse_sherpa_asr.py —— 基于 sherpa-onnx 的本地语音识别引擎。

替代 Vosk 的高精度后端，分两条路径：

* **流式**（边说边出字）：``sherpa-onnx-streaming-paraformer-bilingual-zh-en``
  流式 Paraformer，中英混说，首字延迟几十毫秒，CPU 实时率远小于 1。
* **整段**（松开语音键后一次识别）：``sherpa-onnx-sense-voice-zh-en-ja-ko-yue``
  SenseVoice-Small（int8 约 230MB），中文准确率明显高于 Vosk 小模型，
  自带标点与逆文本规整（ITN）。

对外接口与 :class:`aimouse_voice_panel.AsrEngine` 完全一致，可直接替换：

    available() / preload() / begin() / feed(pcm) / partial() / finish()
    transcribe_samples(samples) / transcribe_file(wav_path)

设计取舍：

* **不依赖 numpy**。sherpa 的 ``accept_waveform`` 接受任意 ``Sequence[float]``，
  用纯 Python list 即可，省掉一个重量级依赖（打包体积和启动时间都受益）。
* **模型按目录全局缓存**。首次加载 SenseVoice 约 1~2 秒，重开窗口 /
  保存设置 / 下次录音都应复用同一份实例。
* **缺依赖 / 缺模型时全部返回 None 或空串**，由调用方回退到 Vosk，
  绝不抛异常打断录音。

模型文件放 ``%APPDATA%\\ExtBatteryTray\\models\\<仓库名>\\``，
可用 ``python tools/download_models.py`` 一键下载。
"""

from __future__ import annotations

import os
import threading
import wave
from typing import Optional

import aimouse_voice as av

# SenseVoice 是定长上下文模型，单段过长会掉准确率，超过就切段拼接
_OFFLINE_CHUNK_SEC = 25.0
_OFFLINE_OVERLAP_SEC = 0.4
# 流式 Paraformer 收尾要补一点静音，否则末尾一两个字容易丢
_TAIL_PAD_SEC = 0.3

_ENGINE_CACHE: dict[str, object] = {}
_ENGINE_LOCK = threading.Lock()


def _num_threads() -> int:
    """CPU 线程数：留一半给界面，2~4 之间取值。"""
    try:
        cores = os.cpu_count() or 2
    except Exception:
        cores = 2
    return max(1, min(4, cores // 2 or 1))


def _pick_model_file(directory: str, *stems: str) -> str:
    """在目录里找优先 int8 的 onnx 文件；找不到返回空串。

    先精确匹配 ``<stem>.int8.onnx`` / ``<stem>.onnx``，再按前缀匹配
    （zipformer 一类模型文件名自带 epoch 后缀，如
    ``encoder-epoch-99-avg-1.int8.onnx``）。**不做任意 .onnx 兜底**，
    否则缺 decoder 时会把 encoder 误当成 decoder。
    """
    for stem in stems:
        for suffix in (".int8.onnx", ".onnx"):
            path = os.path.join(directory, stem + suffix)
            if os.path.isfile(path):
                return path
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".onnx"))
    except OSError:
        return ""
    for stem in stems:
        for name in names:
            if name.startswith(stem):
                if ".int8." in name:
                    return os.path.join(directory, name)
        for name in names:
            if name.startswith(stem):
                return os.path.join(directory, name)
    return ""


def find_model_dirs(root: str) -> tuple[str, str]:
    """在模型根目录下自动探测（流式目录, 整段目录）；缺的返回空串。

    目录名不写死，兼容 ``xxx`` 与 ``sherpa-onnx-xxx`` 两种命名。
    """
    stream_dir = ""
    offline_dir = ""
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return "", ""
    for name in entries:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        low = name.lower()
        if not stream_dir and "paraformer" in low and "streaming" in low:
            stream_dir = path
        elif not offline_dir and ("sense-voice" in low or "sense_voice" in low):
            offline_dir = path
    return stream_dir, offline_dir


class SherpaAsrEngine:
    """sherpa-onnx 识别封装；不可用时全部返回 None，由调用方回退 Vosk。"""

    def __init__(self, model_dir: str, grammar: str = "",
                 stream_dir: str = "", offline_dir: str = "",
                 language: str = "auto"):
        # model_dir 是模型根目录（兼容 AsrEngine 的单目录构造习惯）
        self.model_dir = model_dir
        self.grammar = grammar or ""
        self.language = language or "auto"
        auto_stream, auto_offline = find_model_dirs(model_dir)
        self.stream_dir = stream_dir or auto_stream
        self.offline_dir = offline_dir or auto_offline
        self._online = None          # OnlineRecognizer
        self._offline = None         # OfflineRecognizer
        self._stream = None          # 当前流式会话
        self._gate = None            # 前导静音门控
        self._pcm = bytearray()      # 本次会话累积的 PCM（整段精修用）
        self._lock = threading.Lock()
        self.error = ""
        # 前导静音门控参数：面板按设置写入；None 表示不启用（feed 不做任何裁剪）
        self.onset_kwargs: Optional[dict] = {}

    # -- 可用性 --------------------------------------------------------
    def stream_ready(self) -> bool:
        """流式模型是否齐备。"""
        d = self.stream_dir
        if not d or not os.path.isdir(d):
            return False
        return bool(_pick_model_file(d, "encoder")
                    and _pick_model_file(d, "decoder")
                    and os.path.isfile(os.path.join(d, "tokens.txt")))

    def offline_ready(self) -> bool:
        """整段模型是否齐备。"""
        d = self.offline_dir
        if not d or not os.path.isdir(d):
            return False
        return bool(_pick_model_file(d, "model")
                    and os.path.isfile(os.path.join(d, "tokens.txt")))

    def available(self) -> bool:
        try:
            import sherpa_onnx  # noqa: F401
        except KeyboardInterrupt:
            # Ctrl+C 落在模块导入锁上：视作中断，安静返回
            self.error = "已中断"
            return False
        except Exception:
            self.error = "未安装 sherpa-onnx"
            return False
        if not (self.stream_ready() or self.offline_ready()):
            self.error = "未找到 sherpa 模型目录"
            return False
        return True

    @property
    def name(self) -> str:
        """引擎标识，面板据此显示识别来源。"""
        return "sherpa"

    @property
    def label(self) -> str:
        """引擎中文名，用于界面提示。"""
        return "sherpa-onnx"

    def grammar_supported(self) -> bool:
        """sherpa 不支持 Vosk 那种 runtime 词表约束（热词需另配）。"""
        return False

    # -- 模型加载（全局缓存）-------------------------------------------
    def _get_online(self):
        if self._online is not None:
            return self._online
        import sherpa_onnx
        key = "online|" + os.path.abspath(self.stream_dir)
        with _ENGINE_LOCK:
            rec = _ENGINE_CACHE.get(key)
            if rec is None:
                d = self.stream_dir
                rec = sherpa_onnx.OnlineRecognizer.from_paraformer(
                    encoder=_pick_model_file(d, "encoder"),
                    decoder=_pick_model_file(d, "decoder"),
                    tokens=os.path.join(d, "tokens.txt"),
                    num_threads=_num_threads(),
                    sample_rate=av.SAMPLE_RATE,
                    feature_dim=80,
                    # 端点检测交给按键语义（按下/抬起）控制，引擎内不切句
                    enable_endpoint_detection=False,
                    decoding_method="greedy_search",
                    provider="cpu",
                )
                _ENGINE_CACHE[key] = rec
        self._online = rec
        return rec

    def _get_offline(self):
        if self._offline is not None:
            return self._offline
        import sherpa_onnx
        key = "offline|" + os.path.abspath(self.offline_dir)
        with _ENGINE_LOCK:
            rec = _ENGINE_CACHE.get(key)
            if rec is None:
                d = self.offline_dir
                rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=_pick_model_file(d, "model"),
                    tokens=os.path.join(d, "tokens.txt"),
                    num_threads=_num_threads(),
                    sample_rate=av.SAMPLE_RATE,
                    feature_dim=80,
                    decoding_method="greedy_search",
                    provider="cpu",
                    language=self.language,
                    # ITN：数字转阿拉伯数字、补标点，适合直接输入到输入框
                    use_itn=True,
                )
                _ENGINE_CACHE[key] = rec
        self._offline = rec
        return rec

    def preload(self, stream: Optional[bool] = None) -> bool:
        """后台预热模型。

        ``stream=True`` 只加载流式（边说边转用不到 SenseVoice），
        ``False`` 只加载整段，``None`` 两个都加载。
        按模式只加载一个是刻意的：两个模型同时驻留约 400MB，
        流式模式下没必要常占用 SenseVoice 那份内存。
        """
        if not self.available():
            return False
        ok = False
        try:
            if stream is not False and self.stream_ready():
                self._get_online()
                ok = True
            if stream is not True and self.offline_ready():
                self._get_offline()
                ok = True
            return ok
        except Exception as exc:
            self.error = str(exc)
            return False

    def preload_offline(self) -> bool:
        """单独预热整段模型（SenseVoice 首次加载较慢，可在空闲时提前加载）。"""
        if not self.offline_ready():
            return False
        try:
            self._get_offline()
            return True
        except Exception as exc:
            self.error = str(exc)
            return False

    # -- 流式会话 ------------------------------------------------------
    def begin(self) -> bool:
        """开始一次流式识别。"""
        if not self.stream_ready():
            self.error = "未找到流式模型"
            return False
        try:
            rec = self._get_online()
            stream = rec.create_stream()
        except (KeyboardInterrupt, Exception) as exc:
            self.error = str(exc) or "流式模型加载失败"
            return False
        with self._lock:
            self._stream = stream
            # onset_kwargs 为 None 表示用户关掉了前导静音门控
            self._gate = (av.OnsetGate(**self.onset_kwargs)
                          if self.onset_kwargs is not None else None)
            self._pcm = bytearray()
            self.error = ""
        return True

    def feed(self, pcm: bytes) -> None:
        """喂一段 int16 PCM（每帧约 3.5ms）。

        前导静音由 :class:`aimouse_voice.OnsetGate` 拦下——设备按下语音键后
        有 1 秒多纯底噪，直接喂给模型会让开头「听出」不存在的字。
        """
        if not pcm:
            return
        with self._lock:
            # 门控丢的是前导静音，整段精修仍要用完整 PCM，所以先存原始数据
            self._pcm.extend(pcm)
            stream = self._stream
            if stream is None:
                return
            gate = self._gate
            ready = gate.push(pcm) if gate is not None else pcm
            if not ready:
                return
            try:
                stream.accept_waveform(av.SAMPLE_RATE, av.pcm16_to_samples(ready))
                rec = self._online
                while rec is not None and rec.is_ready(stream):
                    rec.decode_stream(stream)
            except Exception:
                pass

    def partial(self) -> str:
        """取当前部分识别结果；UI 以约 10Hz 节流调用。"""
        with self._lock:
            stream = self._stream
            rec = self._online
            if stream is None or rec is None:
                return ""
            try:
                return av.normalize_asr_text(rec.get_result(stream))
            except Exception:
                return ""

    def finish(self) -> str:
        """结束本段并返回文本：补尾部静音后解一次，取最终结果。"""
        with self._lock:
            stream = self._stream
            rec = self._online
            gate = self._gate
            self._stream = None
            self._gate = None
            if stream is None or rec is None:
                return ""
            try:
                # 门控还没打开（说话太轻/太短）时，缓冲里的音频要先补喂，
                # 否则收尾时这段录音等于没送进引擎，结果会是空
                if gate is not None and not gate.opened:
                    rest = gate.flush()
                    if rest:
                        stream.accept_waveform(
                            av.SAMPLE_RATE, av.pcm16_to_samples(rest))
                pad = [0.0] * int(av.SAMPLE_RATE * _TAIL_PAD_SEC)
                stream.accept_waveform(av.SAMPLE_RATE, pad)
                while rec.is_ready(stream):
                    rec.decode_stream(stream)
                return av.normalize_asr_text(rec.get_result(stream))
            except Exception as exc:
                self.error = str(exc)
                return ""

    def take_pcm(self) -> bytes:
        """取走本段累积的 PCM（面板做整段精修时用）。"""
        with self._lock:
            data = bytes(self._pcm)
            self._pcm = bytearray()
        return data

    # -- 整段识别 ------------------------------------------------------
    def _decode_pcm(self, pcm: bytes) -> str:
        """SenseVoice 解码一段 PCM（int16 bytes）。调用方负责裁前导静音。"""
        rec = self._get_offline()
        samples = av.pcm16_to_samples(pcm)
        if not samples:
            return ""
        wave_in = [s / 32768.0 for s in samples]
        stream = rec.create_stream()
        stream.accept_waveform(av.SAMPLE_RATE, wave_in)
        rec.decode_stream(stream)
        return av.normalize_asr_text(getattr(stream.result, "text", "") or "")

    def transcribe_samples(self, samples: list[int]) -> Optional[str]:
        """对内存中的样本做一次性识别（整段模式 / 流式收尾精修）。"""
        if not samples or not self.offline_ready():
            return None
        try:
            # 前导静音不裁会让模型在句首「听出」不存在的字
            pcm = av.samples_to_pcm16(av.trim_leading_silence(samples))
            return self._decode_pcm(pcm)
        except Exception as exc:
            self.error = str(exc)
            return None

    def transcribe_file(self, wav_path: str) -> Optional[str]:
        """对已有 WAV 做一次性识别；超长音频按段切分后拼接。"""
        if not self.offline_ready():
            return None
        try:
            with wave.open(wav_path, "rb") as fh:
                channels = fh.getnchannels()
                width = fh.getsampwidth()
                rate = fh.getframerate()
                raw = fh.readframes(fh.getnframes())
        except Exception as exc:
            self.error = str(exc)
            return None

        pcm = self._to_mono16(raw, channels, width)
        if rate != av.SAMPLE_RATE and rate > 0:
            pcm = self._resample(pcm, rate, av.SAMPLE_RATE)
        try:
            return self._decode_long(pcm) or ""
        except Exception as exc:
            self.error = str(exc)
            return None

    # -- 音频预处理 ----------------------------------------------------
    @staticmethod
    def _to_mono16(raw: bytes, channels: int, width: int) -> bytes:
        """多声道 / 多位深统一成单声道 16bit。"""
        if channels == 1 and width == 2:
            return raw
        import struct
        if width == 1:      # 8bit 无符号
            samples = [(b - 128) * 256 for b in raw]
        elif width == 2:
            usable = len(raw) - len(raw) % 2
            samples = list(struct.unpack(f"<{usable // 2}h", raw[:usable]))
        elif width == 4:    # 32bit 整数
            usable = len(raw) - len(raw) % 4
            samples = [v >> 16 for v in
                       struct.unpack(f"<{usable // 4}i", raw[:usable])]
        else:
            return b""
        if channels > 1:
            mono = [samples[i]
                    for i in range(0, len(samples), channels)]
            samples = mono
        return av.samples_to_pcm16(samples)

    @staticmethod
    def _resample(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
        """线性插值重采样（设备侧固定 16k，这里只是兜底）。"""
        samples = av.pcm16_to_samples(pcm)
        if not samples or src_rate == dst_rate:
            return pcm
        ratio = dst_rate / float(src_rate)
        out_len = int(len(samples) * ratio)
        out: list[int] = []
        last = len(samples) - 1
        for i in range(out_len):
            pos = i / ratio
            left = int(pos)
            if left >= last:
                out.append(samples[last])
                continue
            frac = pos - left
            a = samples[left]
            b = samples[left + 1]
            out.append(int(a + (b - a) * frac))
        return av.samples_to_pcm16(out)

    def _decode_long(self, pcm: bytes) -> str:
        """长音频按 25s 切段（带 0.4s 重叠），避免定长模型掉字。"""
        pcm = av.trim_pcm(pcm)      # 只在整段开头裁一次，中间段不能裁
        total = len(pcm) // 2
        limit = int(av.SAMPLE_RATE * _OFFLINE_CHUNK_SEC)
        if total <= limit:
            return self._decode_pcm(pcm)
        step = int(av.SAMPLE_RATE * (_OFFLINE_CHUNK_SEC - _OFFLINE_OVERLAP_SEC))
        pieces: list[str] = []
        start = 0
        while start < total:
            end = min(start + limit, total)
            pieces.append(self._decode_pcm(pcm[start * 2:end * 2]))
            if end >= total:
                break
            start += step
        return "".join(p for p in pieces if p)


def create_engine(model_dir: str, grammar: str = "") -> SherpaAsrEngine:
    """按模型根目录创建引擎（供面板统一入口调用）。"""
    return SherpaAsrEngine(model_dir, grammar)
