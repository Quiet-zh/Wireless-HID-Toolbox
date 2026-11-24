# -*- coding: utf-8 -*-
"""纯协议单元测试（不访问硬件）：python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eweadn_proto as p  # noqa: E402


class ChecksumTest(unittest.TestCase):
    def test_online_frame_matches_capture(self):
        # 真机抓包：08 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4A
        self.assertEqual(p.build_frame(p.CMD_DEVICE_ONLINE),
                         bytes.fromhex("08 03 00 00 00 00 00 00 00 00 00 00 00 00 00 00 4a"))

    def test_battery_frame_matches_capture(self):
        # 真机抓包：08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49
        self.assertEqual(p.build_frame(p.CMD_BATTERY),
                         bytes.fromhex("08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49"))

    def test_checksum_with_payload(self):
        frame = p.build_frame(3, b"\x01")
        self.assertEqual(frame[0], 8)
        self.assertEqual(frame[5], 1)
        self.assertEqual(frame[16], (0x4D - sum(frame[1:16])) & 0xFF)

    def test_payload_too_long(self):
        with self.assertRaises(ValueError):
            p.build_frame(1, b"\x00" * 11)


class ParseTest(unittest.TestCase):
    REAL_BATTERY = bytes.fromhex(
        "08 04 00 00 00 02 5a 00 0f d1 00 00 00 00 00 00 0d")

    def test_normalize_with_and_without_report_id(self):
        self.assertEqual(p.normalize_report(self.REAL_BATTERY)[:4],
                         bytes.fromhex("04 00 00 00"))
        no_id = self.REAL_BATTERY[1:]
        self.assertEqual(p.normalize_report(no_id)[:4],
                         bytes.fromhex("04 00 00 00"))

    def test_parse_battery_capture(self):
        info = p.parse_status(p.normalize_report(self.REAL_BATTERY))
        self.assertEqual(info["cmd"], 4)
        self.assertEqual(info["status"], 0)
        self.assertEqual(info["level"], 90)
        self.assertFalse(info["charging"])
        self.assertEqual(info["voltage_mv"], 4049)

    def test_voltage_curve(self):
        self.assertEqual(p.voltage_to_percent(4049), 87)   # E-HUB 显示值
        self.assertEqual(p.voltage_to_percent(4000), 75)
        self.assertEqual(p.voltage_to_percent(3840), 45)
        self.assertEqual(p.voltage_to_percent(4110), 100)
        self.assertEqual(p.voltage_to_percent(4200), 100)
        self.assertEqual(p.voltage_to_percent(3000), 1)

    def test_voltage_curve_monotonic(self):
        values = [p.voltage_to_percent(mv) for mv in range(3000, 4200, 5)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(0 <= v <= 100 for v in values))


if __name__ == "__main__":
    unittest.main()
