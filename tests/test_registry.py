# -*- coding: utf-8 -*-
"""device_registry 的纯数据单元测试。"""
import time
import unittest

import device_registry as dr


class TestRegistry(unittest.TestCase):
    def test_canonical_key(self):
        self.assertEqual(dr.canonical_key("36B0:3002", 0x36B0, 0x3002),
                         "36B0:WAVE75")
        self.assertEqual(dr.canonical_key("36B0:3009", 0x36B0, 0x3009),
                         "36B0:WAVE75")
        self.assertEqual(dr.canonical_key("3554:F517", 0x3554, 0xF517),
                         "3554:F517")
        self.assertEqual(dr.canonical_key("046D:C53F", 0x046D, 0xC53F),
                         "046D:C53F")

    def test_ids(self):
        self.assertEqual(dr._ids("36B0:WAVE75"), (0x36B0, 0x3002))
        self.assertEqual(dr._ids("3554:F517"), (0x3554, 0xF517))

    def test_friendly_name(self):
        self.assertEqual(dr.friendly_name("046D:C53F", "USB Receiver"),
                         "罗技 G304 / Lightspeed")
        self.assertEqual(dr.friendly_name("3554:F517", ""), "EWEADN 8K")

    def test_snapshot_text(self):
        s = dr.DeviceSnapshot(
            key="3554:F517", name="EWEADN 8K", vid=0x3554, pid=0xF517,
            percent=85, charging=False, status="discharging",
            source="EWEADN", link="2.4G", updated=time.time(),
            present=True)
        self.assertEqual(s.charging_text, "未充电")
        self.assertIn("更新于", s.updated_text)
        self.assertEqual(s.subtitle, "3554:F517 · EWEADN")

    def test_stale_text(self):
        s = dr.DeviceSnapshot(
            key="3554:F517", name="EWEADN 8K", vid=0x3554, pid=0xF517,
            percent=84, charging=None, status="休眠", source="上次缓存",
            updated=time.time() - 60, stale=True, present=False)
        self.assertEqual(s.charging_text, "—")
        self.assertTrue(s.updated_text.startswith("缓存于"))
        self.assertEqual(s.subtitle, "3554:F517 · 上次缓存")


if __name__ == "__main__":
    unittest.main()
