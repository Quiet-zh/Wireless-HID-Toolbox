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
            win._publish_text("测试语音输入", same_segment=True)
        send.assert_not_called()          # 完全一致无需退格，也不重输
        typ.assert_not_called()

    def test_corrects_tail(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试鱼音"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True) as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音", same_segment=True)
        self.assertEqual(len(send.call_args[0][0]), 4)   # 退 2 字 × (down,up)
        typ.assert_called_once_with("语音", TARGET)
        win._set_text.assert_called_once_with("测试语音")

    def test_exact_match_does_not_type_twice(self):
        """核心回归：流式已完整键入且最终结果一致 → 不能再整段输入一次。"""
        win = _window(1, TARGET)
        win._typed_partial = "测试语音输入"
        with mock.patch.object(vp.vt, "send_inputs") as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音输入", same_segment=True)
        send.assert_not_called()          # 退格数为 0，不该调用 send_inputs
        typ.assert_not_called()           # 绝不能重复键入

    def test_prefix_growth_only_types_suffix(self):
        """流式键入了「测试」，最终是「测试语音」→ 只补「语音」，不整段。"""
        win = _window(1, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs") as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音", same_segment=True)
        send.assert_not_called()
        typ.assert_called_once_with("语音", TARGET)

    def test_backspace_failure_retypes_full(self):
        win = _window(1, TARGET)
        win._typed_partial = "测试鱼音"
        with mock.patch.object(vp.vt, "send_inputs", return_value=False), \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音", same_segment=True)
        typ.assert_called_once_with("测试语音", TARGET)

    def test_switch_off_types_none(self):
        win = _window(0, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs") as send, \
                mock.patch.object(vp.vt, "type_text",
                                  return_value=(True, "ok")) as typ:
            win._publish_text("测试语音", same_segment=True)
        send.assert_not_called()
        typ.assert_not_called()

    def test_state_keeps_typed_text_after_publish(self):
        """发布后要记住「输入框里现在是什么」，精修才能只删差异。

        这里不能清空：清空会让收尾精修误判成「没键入过」而整段重打，
        输入框里就出现两遍（v1.23.0 的实测 bug）。
        """
        win = _window(1, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True), \
                mock.patch.object(vp.vt, "type_text", return_value=(True, "ok")):
            win._publish_text("测试", same_segment=True)
        self.assertEqual(win._typed_partial, "测试")
        self.assertFalse(win._stream_type_failed)

    def test_failed_typing_clears_state(self):
        """键入失败时输入框状态不可知，必须清空标记以免下次误退格删用户内容。"""
        win = _window(1, TARGET)
        win._typed_partial = "测试"
        with mock.patch.object(vp.vt, "send_inputs", return_value=True), \
                mock.patch.object(vp.vt, "type_text", return_value=(False, "失败")):
            win._publish_text("测试呀", same_segment=True)
        self.assertEqual(win._typed_partial, "")

    def test_refine_only_deletes_difference(self):
        """同一段录音的二次发布（精修）：退格差异部分再重打，而不是整段追加。"""
        win = _window(1, TARGET)
        win._typed_partial = "赤试语音输入一二三"     # 流式已键入的内容
        typed = []
        backspaces = []
        with mock.patch.object(vp.vt, "type_text",
                               side_effect=lambda t, _tg: (typed.append(t), (True, "ok"))[1]), \
                mock.patch.object(vp.vt, "send_inputs",
                                  side_effect=lambda inputs: (backspaces.append(len(inputs)), True)[1]), \
                mock.patch.object(vp.vt, "build_backspace_inputs",
                                  side_effect=lambda n: [None] * n):
            win._publish_text("测试语音输入123。", same_segment=True)
        # 首字就不同 → 全部退格（4 个 INPUT 一个汉字）后重打完整新文本
        self.assertTrue(backspaces)
        self.assertEqual(typed, ["测试语音输入123。"])
        self.assertEqual(win._typed_partial, "测试语音输入123。")

    def test_refine_appends_only_new_tail(self):
        """精修结果只是流式结果的延长时：不删字，只补尾巴。"""
        win = _window(1, TARGET)
        win._typed_partial = "测试语音输入"
        typed = []
        with mock.patch.object(vp.vt, "type_text",
                               side_effect=lambda t, _tg: (typed.append(t), (True, "ok"))[1]), \
                mock.patch.object(vp.vt, "send_inputs", return_value=True):
            win._publish_text("测试语音输入123。", same_segment=True)
        self.assertEqual(typed, ["123。"])
        self.assertEqual(win._typed_partial, "测试语音输入123。")


class _FakeInputBox:
    """模拟焦点输入框：type_text 追加、send_inputs 按退格删字符。"""

    def __init__(self):
        self.text = ""
        self.type_calls = []
        self.backspace_calls = []

    def type_text(self, text, _target):
        self.text += text
        self.type_calls.append(text)
        return True, "ok"

    def send_inputs(self, inputs):
        if not inputs:
            return False
        # 一次退格 = down + up 两个 INPUT
        self.backspace_calls.append(len(inputs) // 2)
        self.text = self.text[:len(self.text) - len(inputs) // 2]
        return True

    @staticmethod
    def build_backspace_inputs(n):
        return [None] * (n * 2)


class TestStreamThenRefineEndToEnd(unittest.TestCase):
    """完整一段：流式实时键入 → 收尾发布 → 高精度精修，输入框只留最终文本。

    这是 v1.23.0 实测到的 bug 场景：发布时把「已键入内容」清掉了，精修
    到达就当成「没键入过」整段再打一遍，输入框里出现两遍。
    """

    def _run(self, stream_steps, final, refined):
        win = _window(1, TARGET)
        box = _FakeInputBox()
        with mock.patch.object(vp.vt, "type_text", box.type_text), \
                mock.patch.object(vp.vt, "send_inputs", box.send_inputs), \
                mock.patch.object(vp.vt, "build_backspace_inputs",
                                  box.build_backspace_inputs):
            for step in stream_steps:
                win._type_stream_partial(step)
            after_stream = box.text
            win._publish_text(final, same_segment=True)          # 收尾先发流式结果
            after_final = box.text
            if refined is not None:
                win._publish_text(refined, same_segment=True)    # 精修结果到达
        return box, after_stream, after_final

    def test_input_box_ends_with_refined_text_only(self):
        box, after_stream, after_final = self._run(
            ["赤试", "赤试语音", "赤试语音输入", "赤试语音输入一二三"],
            "赤试语音输入一二三",
            "测试语音输入123。")
        self.assertEqual(after_stream, "赤试语音输入一二三")
        self.assertEqual(after_final, "赤试语音输入一二三")   # 发布不重复
        self.assertEqual(box.text, "测试语音输入123。")       # 精修是替换不是追加

    def test_refine_deletes_exactly_typed_length(self):
        box, _, _ = self._run(
            ["赤试语音输入一二三"], "赤试语音输入一二三", "测试语音输入123。")
        # 首字即不同 → 退格掉流式那 9 个字，再打 10 个字
        self.assertEqual(box.backspace_calls, [9])
        self.assertEqual(box.text, "测试语音输入123。")

    def test_identical_refine_types_nothing(self):
        """精修与流式一致时不该有任何键击。"""
        box, _, _ = self._run(
            ["测试语音输入一二三"], "测试语音输入一二三", "测试语音输入一二三")
        self.assertEqual(box.type_calls, ["测试语音输入一二三"])
        self.assertEqual(box.backspace_calls, [])

    def test_no_refine_keeps_stream_text(self):
        box, _, _ = self._run(
            ["赤试语音输入一二三"], "赤试语音输入一二三", None)
        self.assertEqual(box.text, "赤试语音输入一二三")
        self.assertEqual(box.backspace_calls, [])

    def test_plain_publish_never_backspaces(self):
        """手动转文字属于「新内容」：就算有上一段的键入记录也绝不能退格。

        否则会把用户自己打的字一起删掉。
        """
        win = _window(1, TARGET)
        win._typed_partial = "上一段录音的内容"
        box = _FakeInputBox()
        box.text = "用户自己打的字"
        with mock.patch.object(vp.vt, "type_text", box.type_text), \
                mock.patch.object(vp.vt, "send_inputs", box.send_inputs), \
                mock.patch.object(vp.vt, "build_backspace_inputs",
                                  box.build_backspace_inputs):
            win._publish_text("手动转文字结果")      # same_segment 默认 False
        self.assertEqual(box.backspace_calls, [])
        self.assertEqual(box.text, "用户自己打的字手动转文字结果")
        self.assertEqual(win._typed_partial, "")


if __name__ == "__main__":
    unittest.main()
