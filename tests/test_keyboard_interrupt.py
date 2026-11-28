# -*- coding: utf-8 -*-
"""Ctrl+C 撞上 vosk 导入时不打 traceback 的回归测试。"""
import builtins
import unittest
from unittest import mock

import aimouse_voice_panel as vp
import main as app_main
import voice_service as vs


class TestVoskImportInterrupt(unittest.TestCase):
    def test_available_catches_keyboard_interrupt(self):
        real_import = builtins.__import__

        def interrupting_import(name, *args, **kwargs):
            if name == "vosk":
                raise KeyboardInterrupt
            return real_import(name, *args, **kwargs)

        with mock.patch.object(builtins, "__import__", interrupting_import):
            engine = vp.AsrEngine("any_dir")
            self.assertFalse(engine.available())   # 不应抛 KeyboardInterrupt
        self.assertEqual(engine.error, "已中断")

    def test_quiet_vosk_catches_interrupt(self):
        real_import = builtins.__import__

        def interrupting_import(name, *args, **kwargs):
            if name == "vosk":
                raise KeyboardInterrupt
            return real_import(name, *args, **kwargs)

        old = vs._VOSK_QUIET
        vs._VOSK_QUIET = False
        try:
            with mock.patch.object(builtins, "__import__", interrupting_import):
                vp._quiet_vosk()                   # 不应抛
            self.assertFalse(vs._VOSK_QUIET)
        finally:
            vs._VOSK_QUIET = old


class TestEntryInterrupt(unittest.TestCase):
    def test_main_returns_130_on_interrupt(self):
        with mock.patch.object(app_main, "_main",
                               side_effect=KeyboardInterrupt):
            self.assertEqual(app_main.main([]), 130)

    def test_main_passes_through_normal_return(self):
        with mock.patch.object(app_main, "_main", return_value=0):
            self.assertEqual(app_main.main([]), 0)

    def test_main_passes_through_args(self):
        with mock.patch.object(app_main, "_main", return_value=7) as m:
            self.assertEqual(app_main.main(["--tool", "tray"]), 7)
            m.assert_called_once_with(["--tool", "tray"])


if __name__ == "__main__":
    unittest.main()
