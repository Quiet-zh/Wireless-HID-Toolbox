# -*- coding: utf-8 -*-
"""鼠标按键映射界面的轻量 GUI 回归（不启动后台、不装钩子）。"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import tkinter as tk
except Exception:          # pragma: no cover
    tk = None

import mouse_remap as mr
import mouse_mapping_panel as mp


@unittest.skipIf(tk is None, "缺少 tkinter")
class TestMappingWindow(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.path = os.path.join(tempfile.gettempdir(),
                                 "mm_ui_test_config.json")
        try:
            os.remove(self.path)
        except OSError:
            pass

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_device_list_and_bindings(self):
        mice = [{"key": "3554:F517", "label": "测试鼠标", "connected": True,
                 "voice": False, "handles": [1]}]
        with mock.patch.object(mr, "list_mice", return_value=mice):
            win = mp.MouseMappingWindow(
                self.root, config_path=self.path, manage_daemon=False,
                auto_pause=False)
            self.root.update()
            self.assertEqual(len(win._devices), 1)
            self.assertEqual(win._current_key, "3554:F517")
            rows = win.tree.get_children()
            self.assertEqual(len(rows), len(mr.BUTTONS))
            mr.set_binding(win.cfg, "3554:F517", "测试鼠标", "side1",
                           "press", {"type": "key", "keys": "ctrl+c"})
            win._refresh_bindings()
            values = win.tree.item("side1", "values")
            self.assertIn("侧键 1", values)
            self.assertEqual(values[2], "键盘按键")
            win.destroy()
            self.root.update()

    def test_voice_key_row(self):
        mice = [{"key": "248A:60AB", "label": "魔声", "connected": True,
                 "voice": True, "handles": [2]}]
        with mock.patch.object(mr, "list_mice", return_value=mice):
            win = mp.MouseMappingWindow(
                self.root, config_path=self.path, manage_daemon=False,
                auto_pause=False)
            self.root.update()
            rows = win.tree.get_children()
            self.assertIn(mr.VOICE_KEY, rows)
            self.assertEqual(len(rows), len(mr.BUTTONS) + 1)
            win.destroy()
            self.root.update()

    def test_exit_flag_does_not_restart_daemon(self):
        mice = [{"key": "3554:F517", "label": "测试鼠标", "connected": True,
                 "voice": False, "handles": [1]}]
        with mock.patch.object(mr, "list_mice", return_value=mice):
            win = mp.MouseMappingWindow(
                self.root, config_path=self.path, manage_daemon=True,
                auto_pause=False)
            self.root.update()
            win.cfg["enabled"] = True
            mr.set_binding(win.cfg, "3554:F517", "测试鼠标", "side1",
                           "press", {"type": "key", "keys": "ctrl+c"})
            win._paused = True
            self.root._exiting_all = True
            with mock.patch.object(mr, "start_daemon") as start:
                win._resume_if_needed()
            start.assert_not_called()
            win.destroy()
            self.root.update()

    def test_offline_configured_device_still_listed(self):
        cfg = mr.default_config()
        mr.ensure_device(cfg, "046D:C53F", "离线鼠标")
        mr.save_config(cfg, self.path)
        with mock.patch.object(mr, "list_mice", return_value=[]):
            win = mp.MouseMappingWindow(
                self.root, config_path=self.path, manage_daemon=False,
                auto_pause=False)
            self.root.update()
            self.assertEqual([d["key"] for d in win._devices],
                             ["046D:C53F"])
            self.assertFalse(win._devices[0]["connected"])
            win.destroy()
            self.root.update()


@unittest.skipIf(tk is None, "缺少 tkinter")
class TestKeyCaptureDialog(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_ctrl_c(self):
        dialog = mp.KeyCaptureDialog(self.root)
        dialog._on_key(SimpleNamespace(keysym="c", state=0x4))
        self.assertEqual(dialog.result, "ctrl+c")
        dialog.destroy()

    def test_escape_is_a_key(self):
        dialog = mp.KeyCaptureDialog(self.root)
        dialog._on_key(SimpleNamespace(keysym="Escape", state=0))
        self.assertEqual(dialog.result, "esc")
        dialog.destroy()

    def test_modifier_alone_not_accepted(self):
        dialog = mp.KeyCaptureDialog(self.root)
        dialog._on_key(SimpleNamespace(keysym="Control_L", state=0x4))
        self.assertIsNone(dialog.result)
        dialog.destroy()

    def test_symbol_and_numpad_names(self):
        dialog = mp.KeyCaptureDialog(self.root)
        dialog._on_key(SimpleNamespace(keysym="minus", state=0))
        self.assertEqual(dialog.result, "-")
        dialog._on_key(SimpleNamespace(keysym="KP_5", state=0))
        self.assertEqual(dialog.result, "numpad5")
        dialog.destroy()


@unittest.skipIf(tk is None, "缺少 tkinter")
class TestBindingDialog(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_voice_button_locks_type_and_trigger(self):
        device = {"key": "248A:60AB", "label": "魔声", "voice": True}
        dialog = mp.BindingDialog(self.root, device)
        self.root.update()
        dialog._button_combo.set("语音键（长按）")
        dialog._button_changed()
        self.root.update()
        self.assertEqual(tuple(dialog._type_combo["values"]), ("语音输入",))
        self.assertEqual(dialog._trigger_combo.get(), "按住（松开结束）")
        dialog.destroy()

    def test_save_returns_action(self):
        device = {"key": "3554:F517", "label": "鼠标", "voice": False}
        dialog = mp.BindingDialog(self.root, device)
        self.root.update()
        dialog._button_combo.set("侧键 2")
        dialog._button_changed()
        dialog._type_combo.set("键盘按键")
        dialog._type_changed()
        self.root.update()
        dialog.keys_var.set("ctrl+shift+esc")
        dialog._save()
        self.assertEqual(dialog.result["button"], "side2")
        self.assertEqual(dialog.result["trigger"], "press")
        self.assertEqual(dialog.result["action"],
                         {"type": "key", "keys": "ctrl+shift+esc"})


if __name__ == "__main__":
    unittest.main()
