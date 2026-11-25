# -*- coding: utf-8 -*-
"""独立验证纯本地解码链路（零第三方依赖）。

用法：
    python tools/verify_local_decode.py

用 Frida 抓到的 4 条真实 33B 0x1B 帧作为 fixture，
验证 XOR 还原 + 跨帧连续 IMA 的输出与固化期望一致，
并打印波形统计（正常应与官方 PCM 接近：RMS ~9000、差中位 ~500、饱和 ~1%）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aimouse_voice as av  # noqa: E402

FRAME_HEX = [
    "1bc0ac49be8090081ca0a3e3c13348e05ac30a74811d0bda2bf709c065235e4a9a",
    "1bc91230be3d1918283423716a905da06bd9197e4019c1c792d5cc10cc23c2cce3",
    "1b07172cbe3615381a08e3e6e4a161a94a63104da72d32d9c365090bee916b4468",
    "1b09ec2abe1210b1adecc2c35c3a41f8db6e525dd13133dacee288a14fa882d3f0",
]
EXPECTED_HEAD = [-7, -8, -7, -7, -10, -9, -8, -8, -8, -8, -8, -8]
EXPECTED_TAIL = [-10, -8, -9, -19]


def main() -> int:
    frames = [bytes.fromhex(h) for h in FRAME_HEX]
    print("XOR 密钥 (%dB):" % len(av.ADPCM_XOR_MASK),
          " ".join("0x%02X" % b for b in av.ADPCM_XOR_MASK))

    out = av.decode_frames_local(frames)
    print("解码样本: %d (期望 %d)" % (len(out), 4 * av.SAMPLES_PER_FRAME))
    ok = True
    if len(out) != 4 * av.SAMPLES_PER_FRAME:
        ok = False
    if out[:12] != EXPECTED_HEAD:
        print("  ⚠️ 前 12 样本不匹配:", out[:12])
        ok = False
    if out[-4:] != EXPECTED_TAIL:
        print("  ⚠️ 末 4 样本不匹配:", out[-4:])
        ok = False

    diffs = [abs(out[i] - out[i - 1]) for i in range(1, len(out))]
    diffs.sort()
    median = diffs[len(diffs) // 2] if diffs else 0
    rms = (sum(v * v for v in out) / len(out)) ** 0.5
    sat = 100.0 * sum(1 for v in out if abs(v) >= 32767) / len(out)
    print("波形: RMS=%.0f  相邻差中位=%d  饱和=%.1f%%" % (rms, median, sat))
    print("前 12 样本:", out[:12])
    print("\n%s" % ("✅ 纯本地解码链路验证通过" if ok else "❌ 验证失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
