# -*- coding: utf-8 -*-
"""诊断工具：监听 0xFF91 接口，打印设备实际发出的帧序列。

用法（先关掉语音窗口的「开始监测」，避免两个进程抢接口）：

    python tools\\diagnose_voice.py 10

运行时**按住鼠标语音键说一句话再松开**，脚本会打印每一帧的类型、
cmd/arg 与字节，用来确认「开始 / 结束 / 抬起」帧到底长什么样。
"""
from __future__ import annotations

import collections
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aimouse_voice_capture as avc  # noqa: E402
import hid_win as hw  # noqa: E402


def main(seconds: float = 10.0) -> int:
    iface = avc.find_interface()
    if iface is None:
        print("❌ 没找到 248A:60AB 的 0xFF91 接口；请检查接收器是否插好。")
        return 1
    print("接口:", iface.path)
    print("监听 %.0f 秒… 请【按住语音键说一句话再松开】" % seconds, flush=True)
    print("-" * 72, flush=True)
    counter: collections.Counter = collections.Counter()
    try:
        with hw.HidDevice(iface.path, write=False) as dev:
            t0 = time.monotonic()
            last = t0
            while time.monotonic() - t0 < seconds:
                report = dev.read_input(timeout_ms=80)
                if not report:
                    continue
                data = bytes(report)
                now = time.monotonic() - t0
                tag = ""
                if data[:1] == b"\x1b":
                    tag = "音频帧"
                elif data[:2] == b"\x0c\x4d" and len(data) >= 4:
                    cmd, arg = data[2], data[3]
                    names = {(0x05, 0x62): "★ 录音开始",
                             (0x05, 0x63): "★ 录音结束",
                             (0x04, 0x38): "★ 长按抬起",
                             (0x04, 0x32): "★ 长按抬起",
                             (0x04, 0x37): "长按按下",
                             (0x04, 0x31): "长按按下"}
                    tag = names.get((cmd, arg),
                                    "控制帧 cmd=%02X arg=%02X" % (cmd, arg))
                else:
                    tag = "其它"
                counter[tag.split(" cmd=")[0]] += 1
                # 音频帧太多，只每 0.25 秒打一条，避免刷屏
                if data[:1] == b"\x1b" and now - last < 0.25:
                    continue
                last = now
                print("%6.3fs  %-22s %s" % (now, tag, data[:16].hex()),
                      flush=True)
    except Exception as exc:
        print("❌ 监听失败:", repr(exc))
        return 1
    print("-" * 72, flush=True)
    print("帧类型统计:", dict(counter), flush=True)
    print("\n判断依据：")
    print("  · 有「★ 录音开始」→ 按状态帧开始；没有但出现「音频帧」")
    print("    → 新版已支持「见音频帧自动开录」")
    print("  · 松开后有「★ 录音结束」或「★ 长按抬起」→ 立即收尾")
    print("  · 都没有 → 靠 0.6 秒音频中断超时收尾")
    return 0


if __name__ == "__main__":
    try:
        secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    except ValueError:
        secs = 10.0
    raise SystemExit(main(secs))
