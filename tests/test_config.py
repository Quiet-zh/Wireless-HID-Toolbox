# -*- coding: utf-8 -*-
"""配置合并与主题默认值的纯数据测试。"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import theme
import tray_common as tc


class TestConfig(unittest.TestCase):
    def test_defaults_include_theme_and_window(self):
        self.assertIn("theme", tc.DEFAULT_CONFIG)
        self.assertEqual(tc.DEFAULT_CONFIG["theme"], "dark")
        for key in ("minimize", "close"):
            self.assertIn(key, tc.DEFAULT_CONFIG["window"])

    def test_partial_window_config_merges_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"theme": "light",
                           "window": {"minimize": "taskbar"}}, f)
            with patch.object(tc, "CONFIG_PATH", path), \
                    patch.object(tc, "LEGACY_CONFIG_PATH",
                                 os.path.join(tmp, "legacy.json")):
                cfg = tc.load_config()
        self.assertEqual(cfg["theme"], "light")
        self.assertEqual(cfg["window"]["minimize"], "taskbar")
        self.assertEqual(cfg["window"]["close"], "current")

    def test_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with patch.object(tc, "CONFIG_PATH", path), \
                    patch.object(tc, "LEGACY_CONFIG_PATH",
                                 os.path.join(tmp, "legacy.json")):
                cfg = tc.load_config()
                cfg["theme"] = "light"
                cfg["window"]["close"] = "all"
                tc.save_config(cfg)
                loaded = tc.load_config()
        self.assertEqual(loaded["theme"], "light")
        self.assertEqual(loaded["window"]["close"], "all")

    def test_theme_current_fallback(self):
        with patch.object(theme.tc, "load_config",
                          return_value={"theme": "light"}):
            self.assertEqual(theme.current(), "light")
        with patch.object(theme.tc, "load_config",
                          return_value={"theme": "???"}):
            self.assertEqual(theme.current(), "dark")


if __name__ == "__main__":
    unittest.main()
