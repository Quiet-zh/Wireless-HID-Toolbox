# -*- coding: utf-8 -*-
"""语音窗口的配置层单元测试（不创建窗口）。"""
import os
import tempfile
import unittest
from unittest.mock import patch

import aimouse_voice_panel as avp


class TestParamDefs(unittest.TestCase):
    def test_fields_complete(self):
        for item in avp.PARAM_DEFS:
            self.assertEqual(len(item), 8)
            key, label, desc, default, lo, hi, step, kind = item
            self.assertTrue(key)
            self.assertTrue(label)
            self.assertTrue(desc)
            self.assertIn(kind, ("int", "bool", "path"))

    def test_defaults_match(self):
        for key, label, desc, default, *_rest in avp.PARAM_DEFS:
            self.assertEqual(avp.DEFAULTS[key], default)

    def test_numeric_ranges(self):
        for key, label, desc, default, lo, hi, step, kind in avp.PARAM_DEFS:
            if kind in ("int", "bool"):
                self.assertIsNotNone(lo)
                self.assertIsNotNone(hi)
                self.assertLessEqual(lo, default)
                self.assertLessEqual(default, hi)
                self.assertGreater(step, 0)


class TestVoiceConfig(unittest.TestCase):
    def test_defaults_loaded_when_missing(self):
        with patch.object(avp, "CONFIG_PATH",
                          os.path.join(tempfile.gettempdir(),
                                       "no_such_voice_cfg.json")):
            cfg = avp.load_config()
            for key in avp.DEFAULTS:
                self.assertIn(key, cfg)

    def test_roundtrip(self):
        path = os.path.join(tempfile.gettempdir(), "voice_cfg_test.json")
        try:
            with patch.object(avp, "CONFIG_PATH", path):
                cfg = avp.load_config()
                cfg["highpass"] = 250
                cfg["denoise"] = 60
                avp.save_config(cfg)
                again = avp.load_config()
                self.assertEqual(again["highpass"], 250)
                self.assertEqual(again["denoise"], 60)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_unknown_keys_ignored(self):
        path = os.path.join(tempfile.gettempdir(), "voice_cfg_extra.json")
        try:
            import json
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"highpass": 300, "bogus": 1}, fh)
            with patch.object(avp, "CONFIG_PATH", path):
                cfg = avp.load_config()
                self.assertEqual(cfg["highpass"], 300)
                self.assertNotIn("bogus", cfg)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
