# -*- coding: utf-8 -*-
"""流式语音输入的增量键入回归。

Vosk partial 是整句假设（每次从头返回），必须只键入稳定增量；
最终结果到达时用退格纠正差异，不能重复整段。
"""
import unittest
from unittest import mock

import aimouse_voice_panel as vp
import voice_typing as vt


class _Label:
    def configure(self, **kw):
        pass


def _window(voice_typing=1, target=None):
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win.cfg = {"voice_typing": voice_typing}
    win.asr_hint = _Label()
    win.status = _Label()
    win._focus_target = target
    win._set_text = mock.Mock()
    win._stream_type_failed = False
    win._typed_partial = ""
    return win


TARGET = vt.FocusTarget(1, 1, 1, 1)


class TestBackspaceInputs(unittest.TestCase):
    def test_count_and_flags(self):
        items = vt.build_backspace_inputs(2)
        self.assertEqual(len(items), 4)     # 2 次 × (down, up)
        self.assertEqual(items[0].u.ki.wVk, vt.VK_BACK)
        self.assertEqual(items[0].u.ki.dwFlags, 0)
        self.assertEqual(items[1].u.ki.dwFlags, vt.KEYEVENTF_KEYUP)

    def test_zero_and_negative(self):
        self.assertEqual(vt.build_backspace_inputs(0), [])
        self.assertEqual(vt.build_backspace_inputs(-3), [])

    def test_capped(self):
        self.assertEqual(len(vt.build_backspace_inputs(vt.MAX_CHARS + 10)),
                         vt.MAX_CHARS * 2)


class TestStreamPartialTyping(unittest.TestCase):
    def test_switch_off_does_not_type(self):
        win = _window(0, TARGET)
        with mock.patch.object(vp.vt, "type_text") as typ:
            win._type_stream_partial("测试")
        typ.assert_not_called()

    def test_no_target_does_not_type(self):
        win = _window(1, None)
        with mock.patch.object(vp.vt, "type_text") as typ:
            win._type_stream_partial("测试")
        typ.assert_not_called()

    def test_types_only_delta(self):
        win = _window(1, TARGET)
        with mock.patch.object(vp.vt, "type_text",
                               return_value=(True, "ok")) as typ:
            win._type_stream_partial("测试")
            win._type_stream_partial("测试语音")
            win._type_stream_partial("测试语音输入")
        self.assertEqual([c[0][0] for c in typ.call_args_list],
                         ["测试", "语音", "输入"])
        self.assertEqual(win._typed_partial, "测试语音输入")

    def test_repeated_partial_not_retyped(self):
        win = _window(1, TARGET)
        with mock.patch.object(vp.vt, "type_text",
                               return_value=(True, "ok")) as typ:
            win._type_stream_partial("测试")
            win._type_stream_partial("测试")
            win._type_stream_partial("测试")
        self.assertEqual(typ.call_count, 1)

    def test_revised_hypothesis_not_retyped(self):
        """假设改写了（不再是已键入内容的前缀）→ 不撤字，等最终结果。"""
        win = _window(1, TARGET)
        with mock.patch.object(vp.vt, "type_text",
                               return_value=(True, "ok")) as typ:
            win._type_stream_partial("测试语音")
            win._type_stream_partial("测试鱼音")   # 改写
        self.assertEqual(typ.call_count, 1)

    def test_failure_stops_typing_for_this_segment(self):
        win = _window(1, TARGET)
        with mock.patch.object(vp.vt, "type_text",
                               return_value=(False, "fail")) as typ:
            win._type_stream_partial("测试")
            win._type_stream_partial("测试语音")
        self.assertEqual(typ.call_count, 1)
        self.assertTrue(win._stream_type_failed)

    def test_empty_partial(self):
        win = _window(1, TARGET)
        with mock.patch.object(vp.vt, "type_text") as typ:
            win._type_stream_partial("")
        typ.assert_not_called()


class TestFinalCorrection(unittest.TestCase):
    def test_same_as_typed_no_retype(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试语音输入"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True) as send, \
                mock.patch.object(vp.vt, "type_text") as typ:
            win._publish_text("测试语音输入")
        send.assert_called_once()
        self.assertEqual(len(send.call_args[0][0]), 0)   # 0 次退格
        typ.assert_not_called()

    def test_corrects_tail(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试鱼音"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True) as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音")
        self.assertEqual(len(send.call_args[0][0]), 4)   # 退 2 字 × (down,up)
        typ.assert_called_once_with("语音", TARGET)
        win._set_text.assert_called_once_with("测试语音")

    def test_backspace_failure_retypes_full(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试鱼音"
        with mock.patch.object(vp.vt, "send_inputs", return_value=False), \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音")
        typ.assert_called_once_with("测试语音", TARGET)

    def test_switch_off_types_none(self):
        win = _window(0, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs") as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音")
        send.assert_not_called()
        typ.assert_not_called()

    def test_state_reset_after_publish(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True), \
                mock.patch.object(vp.vt, "type_text", return_value=(True, "ok")):
            win._publish_text("测试")
        self.assertEqual(win._typed_partial, "")
        self.assertFalse(win._stream_type_failed)


if __name__ == "__main__":
    unittest.main()
