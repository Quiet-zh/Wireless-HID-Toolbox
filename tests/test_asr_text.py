# -*- coding: utf-8 -*-
"""识别结果中文空格规整的回归测试。"""
import unittest
from unittest import mock

import aimouse_voice_panel as vp


class TestNormalizeAsrText(unittest.TestCase):
    def test_chinese_spaces_removed(self):
        self.assertEqual(vp.normalize_asr_text("测试 语音 输入 一二三"),
                         "测试语音输入一二三")
        self.assertEqual(vp.normalize_asr_text("是 语音 输入 一 二 三"),
                         "是语音输入一二三")

    def test_mixed_cjk_ascii(self):
        self.assertEqual(vp.normalize_asr_text("测试 ABC 123 输入"),
                         "测试ABC123输入")

    def test_english_words_keep_spaces(self):
        self.assertEqual(vp.normalize_asr_text("hello world"), "hello world")
        self.assertEqual(vp.normalize_asr_text("hello  world"), "hello  world")

    def test_multiple_whitespace_between_cjk(self):
        self.assertEqual(vp.normalize_asr_text("测试   语音\t输入"),
                         "测试语音输入")

    def test_empty_is_safe(self):
        self.assertEqual(vp.normalize_asr_text(""), "")
        self.assertEqual(vp.normalize_asr_text(None), "")

    def test_strip_outer_spaces(self):
        self.assertEqual(vp.normalize_asr_text("  测试 语音  "), "测试语音")

    def test_idempotent(self):
        once = vp.normalize_asr_text("测试 语音 输入")
        self.assertEqual(vp.normalize_asr_text(once), once)


class TestAsrEngineOutputs(unittest.TestCase):
    def test_partial_normalized(self):
        e = vp.AsrEngine("d")
        e._rec = mock.Mock()
        e._rec.PartialResult.return_value = '{"partial": "测试 语音 输入"}'
        self.assertEqual(e.partial(), "测试语音输入")

    def test_finish_normalized(self):
        e = vp.AsrEngine("d")
        e._rec = mock.Mock()
        e._rec.FinalResult.return_value = '{"text": "测试 语音 输入 一二三"}'
        self.assertEqual(e.finish(), "测试语音输入一二三")

    def test_transcribe_file_normalized(self):
        e = vp.AsrEngine("d")
        e.available = mock.Mock(return_value=True)
        rec = mock.Mock()
        rec.FinalResult.return_value = '{"text": "测试 语音 输入"}'
        e._make_rec = mock.Mock(return_value=rec)
        fake_wave = mock.MagicMock()
        fake_wave.__enter__.return_value.readframes.return_value = b""
        with mock.patch("wave.open", return_value=fake_wave):
            self.assertEqual(e.transcribe_file("x.wav"), "测试语音输入")


class TestPublishTextNormalizes(unittest.TestCase):
    def test_all_sources_go_through_normalizer(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"voice_typing": 0}
        win._set_text = mock.Mock()
        win._publish_text("测试 语音 输入 一二三")
        win._set_text.assert_called_once_with("测试语音输入一二三")

    def test_empty_after_normalize_is_ignored(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"voice_typing": 0}
        win._set_text = mock.Mock()
        win._publish_text("   ")
        win._set_text.assert_not_called()


if __name__ == "__main__":
    unittest.main()
