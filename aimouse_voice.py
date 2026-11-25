# -*- coding: utf-8 -*-
"""aimouse_voice.py —— Monster AiMouse 0xFF91 私有口的 ADPCM 语音解码。

从 2.4G 鼠标接收器回传的 33 字节 HID 帧中还原 16kHz / 16bit 单声道语音。

帧结构（实测 + 反汇编 AiMouse.exe 0x4E6890 处的解码函数确认）::

    [0]      0x1B        帧标识
    [1:3]    predictor   int16 小端，本帧解码起点
    [3]      step_index  0..88（越界按 0/88 截断）
    [4]      0xBE        保留字节
    [5:33]   ADPCM 数据  28 字节 = 56 个 4-bit 样本（低 4 位先）

每帧 56 样本 @16000Hz = 3.5ms，与实测帧率（约 280 帧/秒）一致。

只读解析，不写设备。纯标准库实现，不引入第三方依赖。
"""
from __future__ import annotations

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
    """连续解码多帧，返回拼接后的样本序列。"""
    samples: list[int] = []
    for frame in frames:
        samples.extend(decode_frame(frame))
    return samples


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
