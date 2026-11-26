# -*- coding: utf-8 -*-
"""语音输入功能测试：Unicode 键入构造、焦点过滤、开关分支。"""
import ctypes
import unittest
from unittest import mock

import aimouse_voice_panel as vp
import voice_typing as vt


class TestUnicodeInputs(unittest.TestCase):
    def test_input_struct_size(self):
        # Win64 下 INPUT 必须为 40 字节，否则 SendInput 会失败
        self.assertEqual(ctypes.sizeof(vt.INPUT), 40)

    def test_ascii_and_chinese(self):
        items = vt.build_unicode_inputs("中A")
        self.assertEqual(len(items), 4)       # 2 字符 × (down, up)
        self.assertEqual(items[0].u.ki.wScan, ord("中"))
        self.assertEqual(items[0].u.ki.dwFlags, vt.KEYEVENTF_UNICODE)
        self.assertEqual(items[1].u.ki.dwFlags,
                         vt.KEYEVENTF_UNICODE | vt.KEYEVENTF_KEYUP)
        self.assertEqual(items[2].u.ki.wScan, ord("A"))
        self.assertTrue(all(i.type == vt.INPUT_KEYBOARD for i in items))

    def test_surrogate_pair(self):
        items = vt.build_unicode_inputs("😸")
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].u.ki.wScan, 0xD83D)
        self.assertEqual(items[2].u.ki.wScan, 0xDE38)

    def test_empty(self):
        self.assertEqual(vt.build_unicode_inputs(""), [])
        self.assertEqual(vt.build_unicode_inputs(None), [])

    def test_newline_becomes_space(self):
        items = vt.build_unicode_inputs("a\nb\tc")
        scans = [items[i].u.ki.wScan for i in range(0, len(items), 2)]
        self.assertEqual(scans, [ord("a"), ord(" "), ord("b"),
                                 ord(" "), ord("c")])

    def test_length_cap(self):
        items = vt.build_unicode_inputs("x" * (vt.MAX_CHARS + 50))
        self.assertEqual(len(items), vt.MAX_CHARS * 2)


class TestTypeTextGuards(unittest.TestCase):
    def test_empty_text_no_send(self):
        with mock.patch.object(vt, "send_inputs") as send:
            ok, msg = vt.type_text("   ")
            self.assertFalse(ok)
            send.assert_not_called()

    def test_unsupported_platform(self):
        with mock.patch.object(vt, "supported", return_value=False), \
                mock.patch.object(vt, "send_inputs") as send:
            ok, _ = vt.type_text("测试")
            self.assertFalse(ok)
            send.assert_not_called()


class _FakeLabel:
    def __init__(self):
        self.values = {}

    def configure(self, **kw):
        self.values.update(kw)


def _make_window(cfg, target):
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win.cfg = cfg
    win.asr_hint = _FakeLabel()
    win.status = _FakeLabel()
    win._focus_target = target
    win._shown = []
    win._set_text = lambda value: win._shown.append(value)
    return win


class TestPublishText(unittest.TestCase):
    def test_param_exists_and_default_off(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "voice_typing")
        self.assertEqual(item[3], 0)
        self.assertEqual(item[7], "bool")

    def test_switch_off_only_displays(self):
        win = _make_window({"voice_typing": 0}, vt.FocusTarget(1, 2, 3, 4))
        with mock.patch.object(vp.vt, "type_text") as typed:
            win._publish_text("测试语音输入")
        self.assertEqual(win._shown, ["测试语音输入"])
        typed.assert_not_called()

    def test_switch_on_types_into_target(self):
        target = vt.FocusTarget(1, 2, 3, 4)
        win = _make_window({"voice_typing": 1}, target)
        with mock.patch.object(vp.vt, "type_text",
                               return_value=(True, "已键入焦点输入框")) as typed:
            win._publish_text("测试语音输入")
        self.assertEqual(win._shown, ["测试语音输入"])
        typed.assert_called_once_with("测试语音输入", target)
        self.assertIn("已键入", win.asr_hint.values.get("text", ""))

    def test_switch_on_without_target_skips_typing(self):
        win = _make_window({"voice_typing": 1}, None)
        with mock.patch.object(vp.vt, "type_text") as typed:
            win._publish_text("测试")
        typed.assert_not_called()
        self.assertIn("未检测到外部输入框",
                      win.asr_hint.values.get("text", ""))

    def test_empty_text_does_nothing(self):
        win = _make_window({"voice_typing": 1}, vt.FocusTarget(1, 2, 3, 4))
        with mock.patch.object(vp.vt, "type_text") as typed:
            win._publish_text("")
        self.assertEqual(win._shown, [])
        typed.assert_not_called()


class TestFocusTarget(unittest.TestCase):
    def test_dataclass_fields(self):
        t = vt.FocusTarget(10, 20, 30, 40)
        self.assertEqual((t.hwnd, t.focus_hwnd, t.pid, t.tid), (10, 20, 30, 40))

    def test_track_focus_excludes_own_pid(self):
        fake = vt.FocusTarget(10, 20, 999, 40)
        with mock.patch.object(vt, "current_focus", return_value=fake), \
                mock.patch.object(vt, "is_typable_window", return_value=True):
            self.assertIsNone(vt.track_focus(exclude_pid=999))
            self.assertEqual(vt.track_focus(exclude_pid=1), fake)

    def test_track_focus_excludes_system_window(self):
        fake = vt.FocusTarget(10, 20, 999, 40)
        with mock.patch.object(vt, "current_focus", return_value=fake), \
                mock.patch.object(vt, "is_typable_window", return_value=False):
            self.assertIsNone(vt.track_focus(exclude_pid=1))

    def test_is_typable_window_filters_lock_screen(self):
        fake = vt.FocusTarget(10, 20, 999, 40)
        with mock.patch.object(vt, "window_class",
                               return_value="Windows.UI.Core.CoreWindow"):
            self.assertFalse(vt.is_typable_window(fake))
        with mock.patch.object(vt, "window_class", return_value=""), \
                mock.patch.object(vt, "window_text",
                                  return_value="Windows 默认锁屏界面"):
            self.assertFalse(vt.is_typable_window(fake))
        with mock.patch.object(vt, "window_class", return_value="Notepad"), \
                mock.patch.object(vt, "window_text",
                                  return_value="无标题 - 记事本"):
            self.assertTrue(vt.is_typable_window(fake))
        self.assertFalse(vt.is_typable_window(None))


if __name__ == "__main__":
    unittest.main()
