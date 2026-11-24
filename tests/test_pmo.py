# -*- coding: utf-8 -*-
"""PMO WAVE75 协议纯函数测试（不访问硬件）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pmo_proto as p  # noqa: E402


class FrameTest(unittest.TestCase):
    def test_start_frame_dongle(self):
        f = p._build_frame(p.CMD_START, 24, 32)
        self.assertEqual(len(f), 33)
        self.assertEqual(f[0], 0x00)
        self.assertEqual(f[1], 0xAA)
        self.assertEqual(f[2], 0x10)
        self.assertEqual(f[5], 24)  # payload[4] = size

    def test_battery_frame_wired(self):
        f = p._build_frame(p.CMD_BATTERY, 56, 64)
        self.assertEqual(len(f), 65)
        self.assertEqual(f[1], 0xAA)
        self.assertEqual(f[2], 0x30)
        self.assertEqual(f[5], 56)

    def test_normalize(self):
        self.assertEqual(p._normalize(bytes([0]) + bytes([0xAA, 0x30])),
                         bytes([0xAA, 0x30]))
        self.assertEqual(p._normalize(bytes([0xFF, 0x10])),
                         bytes([0xFF, 0x10]))


class BatteryDataTest(unittest.TestCase):
    def test_charging_text(self):
        for value, text in [(0, "未充电"), (1, "充电中"), (2, "已充满")]:
            b = p.KeyboardBattery(percent=80, charging=value, link=0,
                                  raw=b"", dongle=False, timestamp=0)
            self.assertEqual(b.charging_text, text)


if __name__ == "__main__":
    unittest.main()
