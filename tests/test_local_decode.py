# -*- coding: utf-8 -*-
"""纯本地解码（XOR 还原 + 跨帧连续 IMA）的回归测试。

fixture 来自 Frida 逐帧配对抓到的真实 33B 0x1B 帧；
期望样本由 decode_frames_local 计算并固化，用于防止解码逻辑被改坏。
"""
import unittest

import aimouse_voice as av

FRAME_HEX = [
    "1bc0ac49be8090081ca0a3e3c13348e05ac30a74811d0bda2bf709c065235e4a9a",
    "1bc91230be3d1918283423716a905da06bd9197e4019c1c792d5cc10cc23c2cce3",
    "1b07172cbe3615381a08e3e6e4a161a94a63104da72d32d9c365090bee916b4468",
    "1b09ec2abe1210b1adecc2c35c3a41f8db6e525dd13133dacee288a14fa882d3f0",
]
FRAMES = [bytes.fromhex(h) for h in FRAME_HEX]

EXPECTED_HEAD = [-7, -8, -7, -7, -10, -9, -8, -8, -8, -8, -8, -8]
EXPECTED_TAIL = [-10, -8, -9, -19]

EXPECTED_MASK = bytes((
    0x0C, 0x90, 0x12, 0x9D, 0x20, 0xA3, 0x6B, 0x41,
    0xBB, 0x40, 0x68, 0x5A, 0x4B, 0x12, 0xF4, 0x11,
    0x03, 0x9A, 0x4B, 0x12, 0xF6, 0x11, 0x03, 0x76,
    0x0A, 0x12, 0xD4, 0x48,
))


class TestXorMask(unittest.TestCase):
    def test_mask_length(self):
        self.assertEqual(len(av.ADPCM_XOR_MASK), 28)
        self.assertEqual(len(av.ADPCM_XOR_MASK), av.SAMPLES_PER_FRAME // 2)

    def test_mask_value(self):
        self.assertEqual(av.ADPCM_XOR_MASK, EXPECTED_MASK)


class TestLocalDecode(unittest.TestCase):
    def test_output_length(self):
        self.assertEqual(len(av.decode_frames_local(FRAMES)), 4 * 56)

    def test_fixture_head_and_tail(self):
        out = av.decode_frames_local(FRAMES)
        self.assertEqual(out[:12], EXPECTED_HEAD)
        self.assertEqual(out[-4:], EXPECTED_TAIL)

    def test_deterministic(self):
        self.assertEqual(av.decode_frames_local(FRAMES),
                         av.decode_frames_local(FRAMES))

    def test_continuous_state(self):
        # 同一帧单独解码与接在其它帧之后解码，状态不同 => 结果不同
        alone = av.decode_frames_local([FRAMES[2]])
        together = av.decode_frames_local(FRAMES)[112:168]
        self.assertEqual(len(alone), 56)
        self.assertEqual(len(together), 56)
        self.assertNotEqual(alone, together)

    def test_skips_non_audio_frames(self):
        out = av.decode_frames_local([b"\x0c\x4d", FRAMES[0], b"short"])
        self.assertEqual(len(out), 56)

    def test_custom_initial_state(self):
        a = av.decode_frames_local(FRAMES, pred0=0, index0=0)
        b = av.decode_frames_local(FRAMES, pred0=1000, index0=48)
        self.assertEqual(len(a), len(b))
        self.assertNotEqual(a, b)

    def test_legacy_decode_unchanged(self):
        # 旧函数保持「每帧独立重置」语义
        self.assertEqual(len(av.decode_frames([FRAMES[0]] * 3)), 168)
        self.assertEqual(len(av.decode_frame(FRAMES[0])), 56)


if __name__ == "__main__":
    unittest.main()
