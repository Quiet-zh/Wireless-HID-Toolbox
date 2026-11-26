# -*- coding: utf-8 -*-
"""流式 / 整段转文字开关的回归测试。"""
import unittest
from unittest import mock

import aimouse_voice_panel as vp


class _FakeLabel:
    def __init__(self):
        self.values = {}

    def configure(self, **kw):
        self.values.update(kw)


class TestStreamParam(unittest.TestCase):
    def test_param_present_and_default_on(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "stream_asr")
        self.assertEqual(item[3], 1)
        self.assertEqual(item[7], "bool")

    def test_param_count(self):
        self.assertGreaterEqual(len(vp.PARAM_DEFS), 12)


class TestRecStartModes(unittest.TestCase):
    def _window(self, streaming):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"stream_asr": 1 if streaming else 0}
        win._partial = ""
        win._asr_active = False
        win._clip_before = 0
        win.status = _FakeLabel()
        win.asr_hint = _FakeLabel()
        win._set_text = mock.Mock()
        win.asr = mock.Mock()
        return win

    def test_stream_mode_starts_recognizer(self):
        win = self._window(True)
        with mock.patch.object(vp, "clipboard_sequence", return_value=0), \
                mock.patch.object(vp.threading, "Thread") as thread:
            win._on_rec_start()
        thread.assert_called_once()
        self.assertIn("实时转写", win.status.values["text"])

    def test_segment_mode_skips_recognizer(self):
        """整段模式：录音期间完全不加载识别器，松开后才识别。"""
        win = self._window(False)
        with mock.patch.object(vp, "clipboard_sequence", return_value=0), \
                mock.patch.object(vp.threading, "Thread") as thread:
            win._on_rec_start()
        thread.assert_not_called()
        self.assertFalse(win._asr_active)
        self.assertIn("松开后转写", win.status.values["text"])
        win.asr.begin.assert_not_called()

    def test_segment_mode_still_clears_text(self):
        win = self._window(False)
        with mock.patch.object(vp, "clipboard_sequence", return_value=0), \
                mock.patch.object(vp.threading, "Thread"):
            win._on_rec_start()
        win._set_text.assert_called_once_with("")


class TestModeBadge(unittest.TestCase):
    def _window(self, streaming):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"local_only": 1, "asr_backend": 0, "asr_grammar": "",
                   "model_dir": vp.DEFAULT_MODEL, "voice_typing": 0,
                   "stream_asr": 1 if streaming else 0}
        win.asr = vp.AsrEngine(vp.DEFAULT_MODEL, "")
        win.mode_label = _FakeLabel()
        win.asr_hint = _FakeLabel()
        return win

    def test_badge_stream(self):
        win = self._window(True)
        win._refresh_mode()
        self.assertIn("实时转写", win.mode_label.values["text"])
        self.assertIn("边说边转", win.asr_hint.values["text"])

    def test_badge_segment(self):
        win = self._window(False)
        win._refresh_mode()
        self.assertIn("整段转写", win.mode_label.values["text"])
        self.assertIn("松开后整段识别", win.asr_hint.values["text"])


class TestAudioFeedGating(unittest.TestCase):
    def _window(self, active):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win._asr_active = active
        win._ui_tick = 0.0
        win._partial = ""
        win.meter = mock.Mock()
        win.meter.winfo_width.return_value = 300
        win.meter_fill = 1
        win.asr = mock.Mock()
        win.asr.partial.return_value = "测试"
        win._set_text = mock.Mock()
        win.cfg = {"voice_typing": 0}      # 流式输入默认关，避免触发键入
        win._focus_target = None
        win._typed_partial = ""
        win._stream_type_failed = False
        win.asr_hint = mock.Mock()
        return win

    def test_segment_mode_does_not_feed(self):
        win = self._window(False)
        win._on_audio(b"\x1b" + bytes(32))
        win.asr.feed.assert_not_called()

    def test_stream_mode_feeds(self):
        win = self._window(True)
        win._on_audio(b"\x1b" + bytes(32))
        win.asr.feed.assert_called_once()


class TestSegmentModeTranscribes(unittest.TestCase):
    def test_no_stream_triggers_file_transcribe(self):
        # 复用已有回归：had_stream=False 时必须补一次整段识别
        from tests.test_voice_perf import TestNoDoubleTranscribe
        case = TestNoDoubleTranscribe("test_stream_never_started_falls_back")
        case.test_stream_never_started_falls_back()


if __name__ == "__main__":
    unittest.main()
