# -*- coding: utf-8 -*-
"""启动首屏缓存与「HID 在线但没读到电量」不算休眠的回归测试。"""
import copy
import time
import unittest
from unittest import mock

import device_registry as dr


class FakeIface:
    def __init__(self, vid, pid):
        self.vid = vid
        self.pid = pid


def _cfg_with_aimouse():
    return {"devices": {"248A:60AB": {
        "name": "魔声 AI 垂直鼠标", "show": True, "tray": True, "order": 5,
    }}}


class TestCachedSnapshot(unittest.TestCase):
    def test_cached_snapshot_needs_no_hid(self):
        cfg = _cfg_with_aimouse()
        with mock.patch.object(dr.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(cfg)), \
                mock.patch.object(dr.last_state, "get",
                                  side_effect=lambda key: (
                                      {"percent": 87, "ts": time.time() - 30,
                                       "detail": "0xFF91"}
                                      if key == "248A:60AB" else None)):
            snaps = dr.cached_snapshot()
        self.assertEqual(len(snaps), 1)
        s = snaps[0]
        self.assertEqual(s.percent, 87)
        self.assertTrue(s.stale)
        self.assertEqual(s.status, "读取中")
        self.assertFalse(s.present)

    def test_cached_snapshot_skips_devices_without_cache(self):
        cfg = _cfg_with_aimouse()
        with mock.patch.object(dr.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(cfg)), \
                mock.patch.object(dr.last_state, "get", return_value=None):
            self.assertEqual(dr.cached_snapshot(), [])


class TestOnlineButNoReading(unittest.TestCase):
    def test_hid_online_with_cache_is_not_sleeping(self):
        """魔声 0xFF91 HID 在线但一轮没读到电量帧 → 不是休眠。"""
        cfg = _cfg_with_aimouse()

        def load():
            return copy.deepcopy(cfg)

        def save(value):
            cfg.clear()
            cfg.update(copy.deepcopy(value))

        with mock.patch.object(dr.tc, "load_config", side_effect=load), \
                mock.patch.object(dr.tc, "save_config", side_effect=save), \
                mock.patch.object(dr.hid_win, "enumerate_hid",
                                  return_value=[FakeIface(0x248A, 0x60AB)]), \
                mock.patch.object(dr.gp, "scan", return_value=[]), \
                mock.patch.object(dr.last_state, "get",
                                  return_value={"percent": 92,
                                                "ts": time.time() - 60,
                                                "detail": "0xFF91"}):
            snaps = dr.snapshot(fast=True)
        mouse = [s for s in snaps if s.key == "248A:60AB"][0]
        self.assertEqual(mouse.status, "在线 · 等待电量")
        self.assertTrue(mouse.present)
        self.assertTrue(mouse.stale)
        self.assertNotEqual(mouse.status, "休眠")

    def test_really_offline_still_sleeping(self):
        """HID 不在枚举里 → 才是休眠。"""
        cfg = _cfg_with_aimouse()

        def load():
            return copy.deepcopy(cfg)

        def save(value):
            cfg.clear()
            cfg.update(copy.deepcopy(value))

        with mock.patch.object(dr.tc, "load_config", side_effect=load), \
                mock.patch.object(dr.tc, "save_config", side_effect=save), \
                mock.patch.object(dr.hid_win, "enumerate_hid",
                                  return_value=[]), \
                mock.patch.object(dr.gp, "scan", return_value=[]), \
                mock.patch.object(dr.last_state, "get",
                                  return_value={"percent": 50,
                                                "ts": time.time() - 600,
                                                "detail": ""}):
            snaps = dr.snapshot(fast=True)
        mouse = [s for s in snaps if s.key == "248A:60AB"][0]
        self.assertEqual(mouse.status, "休眠")
        self.assertFalse(mouse.present)
        self.assertTrue(mouse.stale)


if __name__ == "__main__":
    unittest.main()
