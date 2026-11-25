# -*- coding: utf-8 -*-
"""aimouse_voice_capture.py —— 从 Monster AiMouse 抓取语音并解码保存。

监听 `0xFF91` 私有口：长按语音键时接收 ADPCM 帧，松开后自动解码成 WAV。

    python aimouse_voice_capture.py --seconds 30
    python aimouse_voice_capture.py --seconds 30 --out my_voice.wav
    python aimouse_voice_capture.py --seconds 30 --filter   # 轻度高通后再保存
    python aimouse_voice_capture.py --seconds 30 --list     # 只列设备后退出

只读取设备，不发送任何写操作。
"""
from __future__ import annotations

import argparse
import os
import time

import aimouse_voice as av
import hid_win as hw

VID = 0x248A
PID = 0x60AB
CONTROL_PREFIX = b"\x0c\x4d"
GAP_SECONDS = 0.45


def find_interface():
    """定位 0xFF91 私有音频接口；找不到返回 None。"""
    for d in hw.enumerate_hid():
        if d.vid == VID and d.pid == PID and d.usage_page == 0xFF91:
            return d
    return None


def capture(seconds: float, gap: float = GAP_SECONDS,
            verbose: bool = True) -> list[list[bytes]]:
    """监听指定秒数，返回按录音段分组的音频帧列表。"""
    iface = find_interface()
    if iface is None:
        raise SystemExit("没有找到 248A:60AB 的 0xFF91 接口，请确认鼠标已连接。")

    segments: list[list[bytes]] = []
    current: list[bytes] = []
    last_seen = 0.0
    t0 = time.monotonic()
    deadline = t0 + max(1.0, seconds)

    with hw.HidDevice(iface.path, write=False) as dev:
        if verbose:
            print("监听 %.0f 秒，请长按鼠标语音键说话…" % seconds, flush=True)
        while time.monotonic() < deadline:
            now = time.monotonic() - t0
            report = dev.read_input(timeout_ms=80)
            if report:
                data = bytes(report)
                if data[:1] == b"\x1b":
                    if current and now - last_seen > gap:
                        segments.append(current)
                        current = []
                        if verbose:
                            print("[%6.2fs] 新录音段" % now, flush=True)
                    current.append(data)
                    last_seen = now
                elif data[:2] == CONTROL_PREFIX and verbose and len(data) >= 4:
                    cmd, arg = data[2], data[3]
                    if cmd == 0x04:
                        label = {0x33: "单击", 0x37: "长按按下",
                                 0x38: "长按抬起"}.get(arg, "按键 0x%02X" % arg)
                        print("[%6.2fs] %s" % (now, label), flush=True)
                    elif cmd == 0x05 and arg in (0x62, 0x63):
                        print("[%6.2fs] %s" % (now, "录音开始" if arg == 0x62
                                               else "录音结束"), flush=True)
            elif current and now - last_seen > gap:
                segments.append(current)
                current = []
        if current:
            segments.append(current)
    return segments


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="从 Monster AiMouse 0xFF91 抓取语音并解码为 WAV")
    parser.add_argument("--seconds", type=float, default=30,
                        help="监听时长（秒），默认 30")
    parser.add_argument("--out", default="aimouse_voice.wav",
                        help="输出 WAV 路径；多段时自动加 _1/_2 后缀")
    parser.add_argument("--filter", action="store_true",
                        help="保存前做 150Hz 高通，去除低频轰鸣")
    parser.add_argument("--no-normalize", action="store_true",
                        help="不做峰值归一化")
    parser.add_argument("--list", action="store_true",
                        help="只列出 0xFF91 接口后退出")
    args = parser.parse_args(argv)

    if args.list:
        iface = find_interface()
        if iface is None:
            print("未找到 248A:60AB 的 0xFF91 接口")
            return 1
        print("0xFF91 接口: %s" % iface.path)
        return 0

    segments = capture(args.seconds)
    audio = [s for s in segments if s]
    if not audio:
        print("没有录到语音（未检测到长按语音键）。")
        return 2

    base, ext = os.path.splitext(args.out)
    total = 0
    for index, frames in enumerate(audio, 1):
        samples = av.decode_frames(frames)
        if args.filter:
            samples = av.highpass(samples, cutoff=150)
        if not args.no_normalize:
            samples = av.normalize(samples)
        path = args.out if len(audio) == 1 else "%s_%d%s" % (base, index, ext)
        count = av.save_wav(path, samples)
        total += count
        print("第 %d 段: %.2f 秒 -> %s" % (index, count / av.SAMPLE_RATE, path))

    print("完成，共 %d 段，%.2f 秒音频。" %
          (len(audio), total / av.SAMPLE_RATE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
