# -*- coding: utf-8 -*-
"""aimouse_voice.py —— 魔声 AI 垂直鼠标 0xFF91 私有口的 ADPCM 语音解码。

从 2.4G 鼠标接收器回传的 33 字节 HID 帧中还原 16kHz / 16bit 单声道语音。

帧结构（实测 + 反汇编 AiMouse.exe 0x4E6890 处的解码函数确认）::

    [0]      0x1B        帧标识
    [1:3]    设备侧状态  不是解码器的 predictor（勿直接用于解码）
    [3]      设备侧状态
    [4]      0xBE        保留字节
    [5:33]   加扰数据    28 字节，需先 XOR ADPCM_XOR_MASK 才是 IMA ADPCM

每帧 56 样本 @16000Hz = 3.5ms，与实测帧率（约 280 帧/秒）一致。

**真实语音请用 :func:`decode_frames_local`**：先按位置异或还原 28 字节，
再以跨帧连续的 predictor/step_index 做标准 IMA 解码（低 4 位先）。
该函数完全本地、零第三方依赖，不需要云端 ASR、官方驱动或剪贴板。
:func:`decode_frame` / :func:`decode_frames` 保留为未加扰流的旧实现。

只读解析，不写设备。
"""
from __future__ import annotations

import re
import struct
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# IMA ADPCM 表（与 AiMouse.exe .rdata 0x3DEEA0 / 0x3DEF78 处内容一致）
# ---------------------------------------------------------------------------
INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8,
               -1, -1, -1, -1, 2, 4, 6, 8)

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
    157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544,
    598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707,
    1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
    5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289,
    16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)

FRAME_SIZE = 33          # 一条 HID input report
AUDIO_OFFSET = 5         # ADPCM 数据起点
SAMPLES_PER_FRAME = 56   # 28 字节 × 2 个 nibble
SAMPLE_RATE = 16000
FRAME_ID = 0x1B

# 设备侧对 ADPCM 数据做的固定加扰密钥（28 字节，按位置 XOR）。
# 由 Frida 逐帧配对求出：同一次录音里 hid[5+j] XOR decode_buf[4+j]
# 在 966 帧上 100% 恒定；用该密钥还原后，解码结果与官方输出逐样本零误差。
# 详见 docs/AiMouse-RE-Notes.md。
ADPCM_XOR_MASK = bytes((
    0x0C, 0x90, 0x12, 0x9D, 0x20, 0xA3, 0x6B, 0x41,
    0xBB, 0x40, 0x68, 0x5A, 0x4B, 0x12, 0xF4, 0x11,
    0x03, 0x9A, 0x4B, 0x12, 0xF6, 0x11, 0x03, 0x76,
    0x0A, 0x12, 0xD4, 0x48,
))


def is_audio_frame(frame: bytes) -> bool:
    """判断一条 0xFF91 报文是否是音频帧（首字节 0x1B）。"""
    return len(frame) >= FRAME_SIZE and frame[0] == FRAME_ID


def decode_frame(frame: bytes) -> list[int]:
    """解一帧 ADPCM，返回 56 个 16bit 样本（每帧独立重置 predictor）。

    非法帧返回空列表。
    """
    if not is_audio_frame(frame):
        return []
    pred = struct.unpack("<h", frame[1:3])[0]
    index = max(0, min(88, frame[3]))
    out: list[int] = []
    for byte in frame[AUDIO_OFFSET:FRAME_SIZE]:
        # 低 4 位先，再高 4 位（与反汇编里的 byte>>=4 顺序一致）
        for nib in (byte & 0x0F, (byte >> 4) & 0x0F):
            step = STEP_TABLE[index]
            diff = step >> 3
            if nib & 4:
                diff += step
            if nib & 2:
                diff += step >> 1
            if nib & 1:
                diff += step >> 2
            pred = pred - diff if nib & 8 else pred + diff
            if pred > 32767:
                pred = 32767
            elif pred < -32768:
                pred = -32768
            index = max(0, min(88, index + INDEX_TABLE[nib]))
            out.append(pred)
    return out


def decode_frames(frames: Iterable[bytes]) -> list[int]:
    """连续解码多帧，返回拼接后的样本序列。

    注意：这是**旧版「每帧独立重置 predictor」**的实现，用于未加扰的
    标准 IMA 流或单元测试。真实的魔声 AI 垂直鼠标请用
    :func:`decode_frames_local`。
    """
    samples: list[int] = []
    for frame in frames:
        samples.extend(decode_frame(frame))
    return samples


class LocalStreamDecoder:
    """逐帧增量解码：XOR 解扰 + 跨帧连续 IMA。

    与 :func:`decode_frames_local` **字节级一致**，但 predictor / step_index
    在实例里跨帧保留，适合一边收 HID 帧一边喂给流式 ASR。
    每帧 ``feed()`` 返回 56 个 16bit 样本；非法帧返回空列表。
    """

    def __init__(self, pred0: int = 0, index0: int = 0):
        self.reset(pred0, index0)

    def reset(self, pred0: int = 0, index0: int = 0) -> None:
        self.pred = pred0
        self.index = max(0, min(88, index0))

    def feed(self, frame: bytes) -> list[int]:
        if not is_audio_frame(frame):
            return []
        out: list[int] = []
        for pos, raw in enumerate(frame[AUDIO_OFFSET:FRAME_SIZE]):
            byte = raw ^ ADPCM_XOR_MASK[pos]
            for nib in (byte & 0x0F, (byte >> 4) & 0x0F):
                step = STEP_TABLE[self.index]
                diff = step >> 3
                if nib & 4:
                    diff += step
                if nib & 2:
                    diff += step >> 1
                if nib & 1:
                    diff += step >> 2
                self.pred = (self.pred - diff if nib & 8
                             else self.pred + diff)
                if self.pred > 32767:
                    self.pred = 32767
                elif self.pred < -32768:
                    self.pred = -32768
                self.index = max(0, min(88, self.index + INDEX_TABLE[nib]))
                out.append(self.pred)
        return out

    def feed_all(self, frames: Iterable[bytes]) -> list[int]:
        out: list[int] = []
        for frame in frames:
            out.extend(self.feed(frame))
        return out


def decode_frames_local(frames: Iterable[bytes],
                        pred0: int = 0, index0: int = 0) -> list[int]:
    """**纯本地**还原设备语音（不需要云端、官方驱动或剪贴板）。

    与官方驱动 `decode()` 的行为一致（Frida 逐样本验证 40/40 零误差）：

    * 每帧 ``[5:33]`` 的 28 字节先按位置 XOR :data:`ADPCM_XOR_MASK`；
    * ``predictor`` / ``step_index`` **跨帧连续**，只在整段开始时初始化
      （默认 0/0；IMA 自适应会迅速收敛，实测不影响识别）；
    * 帧头 ``[1:4]`` 是设备侧状态，**不参与**解码。

    返回 16bit 样本列表，每帧 56 个。非法帧跳过。
    流式识别请用等价的增量类 :class:`LocalStreamDecoder`。
    """
    return LocalStreamDecoder(pred0, index0).feed_all(frames)


def split_segments(frames: list[bytes], gap_frames: int = 12) -> list[list[bytes]]:
    """按连续段切分音频帧（中间断档超过 gap_frames 视为两次录音）。"""
    segments: list[list[bytes]] = []
    current: list[bytes] = []
    missing = 0
    for frame in frames:
        if is_audio_frame(frame):
            if missing > gap_frames and current:
                segments.append(current)
                current = []
            missing = 0
            current.append(frame)
        else:
            missing += 1
    if current:
        segments.append(current)
    return segments


def samples_to_pcm16(samples: Iterable[int]) -> bytes:
    """样本序列 -> little-endian 16bit PCM 字节流。"""
    return b"".join(struct.pack("<h", s) for s in samples)


_CJK_CHAR = r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]"


def normalize_asr_text(text: str) -> str:
    """规整识别结果：去掉中文词之间的空格，英文单词间空格保留。

    Vosk 中文模型把 ``text`` 按词用空格拼接（「测试 语音 输入 一二三」）；
    语音输入场景需要连续文本。中文与数字之间的空格也一并去掉。

    sherpa-onnx 的中文输出本身是连续文本，这里同样适用（幂等）。
    """
    if not text:
        return ""
    # CJK 前后的空格一律去掉（「测试 语音」/「语音 123」/「123 输入」）
    text = re.sub(rf"(?<={_CJK_CHAR})\s+(?=\S)", "", text)
    text = re.sub(rf"(?<=\S)\s+(?={_CJK_CHAR})", "", text)
    # 数字与字母、数字与数字之间的空格也去掉（「ABC 123」→「ABC123」）
    text = re.sub(r"(?<=\d)\s+(?=[A-Za-z0-9])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9])\s+(?=\d)", "", text)
    # 英文单词之间的空格保留（「hello world」原样）
    return text.strip()


def pcm16_to_samples(pcm: bytes) -> list[int]:
    """little-endian 16bit PCM 字节流 -> 样本列表。"""
    if not pcm:
        return []
    usable = len(pcm) - (len(pcm) % 2)
    return list(struct.unpack(f"<{usable // 2}h", pcm[:usable]))


# ---------------------------------------------------------------------------
# 语音起点门控（前导静音裁剪）
#
# 实测结论：设备按下语音键后有 1~1.5 秒纯底噪，这段静音喂给 ASR 会让模型
# 在开头「听出」不存在的字（Vosk 小模型→「此事」/ sherpa→「请世」），
# 整句准确率被拉低。裁掉前导静音后同一段音频：
#
#   Vosk 大模型   是语音输入一二三  →  测试语音输入一二三
#   sherpa 流式   请世是语音输入与二 →  刺试语音输入一二三
#
# 阈值取底噪（RMS≈500~900）的数倍，连续两个 20ms 窗口超标才认作起点，
# 起点前面再回退 120ms，避免削掉「测」这类弱起爆破音。
# ---------------------------------------------------------------------------
ONSET_HOP = 320             # 判定窗口 320 样本 = 20ms @16kHz
ONSET_RMS_THRESHOLD = 3000  # 语音起点能量阈值（底噪的 4~6 倍）
ONSET_NEED = 2              # 连续多少个窗口超标才认定起点
ONSET_BACK_SEC = 0.12       # 起点前额外保留的时长
ONSET_MAX_WAIT_SEC = 2.5    # 等这么久仍无起点就直接放行（避免吞掉整段）


def pcm_rms(pcm: bytes) -> float:
    """一段 int16 PCM 的均方根能量。"""
    samples = pcm16_to_samples(pcm)
    return samples_rms(samples)


def samples_rms(samples) -> float:
    if not samples:
        return 0.0
    return (sum(v * v for v in samples) / len(samples)) ** 0.5


def find_onset(samples, threshold: float = ONSET_RMS_THRESHOLD,
               hop: int = ONSET_HOP, need: int = ONSET_NEED,
               back_sec: float = ONSET_BACK_SEC,
               rate: int = SAMPLE_RATE) -> int:
    """返回语音起点样本下标；找不到返回 0。

    连续 ``need`` 个窗口超过 ``threshold`` 才算起点。认定后回退
    ``need-1`` 个窗口 + ``back_sec``，确保判定期本身和弱起辅音都不被削掉。
    """
    if not samples:
        return 0
    hits = 0
    for i in range(0, len(samples) - hop + 1, hop):
        if samples_rms(samples[i:i + hop]) > threshold:
            hits += 1
            if hits >= need:
                # i 是当前窗口起点；回退前面已判定通过的窗口 + back_sec
                start = i - (hits - 1) * hop - int(rate * back_sec)
                return max(0, start)
        else:
            hits = 0
    return 0


def trim_leading_silence(samples, **kw) -> list[int]:
    """裁掉前导静音；整段都是静音时原样返回（交给下游判定为空）。"""
    start = find_onset(samples, **kw)
    return list(samples[start:]) if start else list(samples)


def trim_pcm(pcm: bytes, **kw) -> bytes:
    """按字节流裁前导静音（供整段识别路径使用）。"""
    if not pcm:
        return pcm
    start = find_onset(pcm16_to_samples(pcm), **kw)
    return pcm[start * 2:] if start else pcm


class OnsetGate:
    """流式喂数据时的语音起点门控：起点之前的静音不交给识别引擎。

    实时性开销只有 ``ONSET_NEED × 20ms``，且起点会回退 ``back_sec``，
    所以不会丢掉第一个字。等满 ``max_wait_sec`` 还没检测到起点时
    直接放行全部缓冲，避免小声说话 / 环境噪声偏低时整段被吞。
    """

    def __init__(self, threshold: float = ONSET_RMS_THRESHOLD,
                 hop: int = ONSET_HOP, need: int = ONSET_NEED,
                 back_sec: float = ONSET_BACK_SEC,
                 max_wait_sec: float = ONSET_MAX_WAIT_SEC,
                 rate: int = SAMPLE_RATE):
        self.threshold = threshold
        self.hop = max(hop, 2)
        self.need = max(need, 1)
        self.back_sec = back_sec
        self.max_wait_sec = max_wait_sec
        self.rate = rate
        self._buf = bytearray()
        self._scan = 0
        self._hits = 0
        self._wait = 0.0
        self._dropped = 0
        self.opened = False

    def reset(self) -> None:
        self._buf = bytearray()
        self._scan = 0
        self._hits = 0
        self._wait = 0.0
        self._dropped = 0
        self.opened = False

    @property
    def dropped_sec(self) -> float:
        """已丢弃的前导静音时长（诊断用）。"""
        if not self.opened or not self._dropped:
            return 0.0
        return self._dropped / 2.0 / self.rate

    def push(self, pcm: bytes) -> bytes:
        """投递一段 PCM；返回本次应交给引擎的数据（可能为空）。"""
        if not pcm:
            return b""
        if self.opened:
            return pcm
        self._buf.extend(pcm)
        self._wait += len(pcm) / 2.0 / self.rate
        hop_bytes = self.hop * 2
        while self._scan + hop_bytes <= len(self._buf):
            seg = bytes(self._buf[self._scan:self._scan + hop_bytes])
            if pcm_rms(seg) > self.threshold:
                self._hits += 1
            else:
                self._hits = 0
            self._scan += hop_bytes
            if self._hits >= self.need:
                self.opened = True
                break

        if self.opened:
            # _scan 已越过 need 个窗口，回退这些窗口 + back_sec
            start = self._scan - self.need * self.hop - int(
                self.rate * self.back_sec)
            start = max(0, start)
            start -= start % 2          # 保证按 16bit 对齐
            self._dropped = start
            out = bytes(self._buf[start:])
            self._buf = bytearray()
            return out
        if self._wait >= self.max_wait_sec:
            self.opened = True
            self._dropped = 0
            out = bytes(self._buf)
            self._buf = bytearray()
            return out
        return b""


def pcm16_to_wav(pcm: bytes, rate: int = SAMPLE_RATE,
                 channels: int = 1, bits: int = 16) -> bytes:
    """给裸 PCM 加上 44 字节 WAV 头。"""
    block_align = channels * bits // 8
    byte_rate = rate * block_align
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, channels, rate,
                          byte_rate, block_align, bits)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def save_wav(path: str, samples: Iterable[int],
             rate: int = SAMPLE_RATE) -> int:
    """把样本写成 16bit 单声道 WAV，返回写入的样本数。"""
    data = list(samples)
    pcm = samples_to_pcm16(data)
    with open(path, "wb") as fh:
        fh.write(pcm16_to_wav(pcm, rate))
    return len(data)


def highpass(samples: list[int], cutoff: float = 150.0,
             rate: int = SAMPLE_RATE, passes: int = 2) -> list[int]:
    """一阶高通（级联 passes 次），去直流与低频轰鸣。

    纯标准库实现；用于送 ASR 前做轻度预处理，不会像谱减那样产生音乐噪声。
    """
    if not samples:
        return []
    import math
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / rate
    alpha = rc / (rc + dt)
    out = [float(s) for s in samples]
    for _ in range(max(1, passes)):
        nxt = [0.0] * len(out)
        prev_x = out[0]
        prev_y = out[0]
        for i in range(1, len(out)):
            x = out[i]
            y = alpha * (prev_y + x - prev_x)
            nxt[i] = y
            prev_x = x
            prev_y = y
        nxt[0] = nxt[1] if len(nxt) > 1 else 0.0
        out = nxt
    return [int(round(v)) for v in out]


def normalize(samples: list[int], peak: int = 26000) -> list[int]:
    """按峰值归一化，避免硬削波。"""
    if not samples:
        return []
    mx = max(abs(s) for s in samples) or 1
    return [int(round(s / mx * peak)) for s in samples]
