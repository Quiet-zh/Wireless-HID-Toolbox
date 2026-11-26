# -*- coding: utf-8 -*-
"""「保存语音」开关回归：默认开；关闭后不写 WAV 但仍能转文字。"""
import os
import tempfile
import unittest
from unittest import mock

import aimouse_voice as av
import aimouse_voice_panel as vp


def _window(save_audio, asr_active=False, final="", auto=1):
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win.cfg = {"save_audio": save_audio, "save_dir": tempfile.mkdtemp(
        prefix="vh_save_"), "auto_transcribe": auto, "voice_typing": 0,
        "highpass": 0, "peak": 26000, "denoise": 0}
    win._asr_active = asr_active
    win._stream_decoder = None
    win._partial = ""
    win.selected = None
    win.asr = mock.Mock()
    win.asr.finish.return_value = final
    win.asr.available.return_value = True
    win.asr.transcribe_samples.return_value = "内存识别结果"
    win.asr_hint = mock.Mock()
    win.status = mock.Mock()
    win.meter = mock.Mock()
    win.meter.winfo_width.return_value = 300
    win.meter_fill = 1
    win.meter_text = mock.Mock()
    win.listbox = mock.Mock()
    win._paths = []
    win._set_text = mock.Mock()
    win._publish_text = mock.Mock()
    win._refresh_list = mock.Mock()
    win._sync_selection = mock.Mock()
    win._transcribe_samples = mock.Mock()
    win.events = mock.Mock()
    return win


class TestSaveAudioParam(unittest.TestCase):
    def test_present_and_default_on(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "save_audio")
        self.assertEqual(item[3], 1)
        self.assertEqual(item[7], "bool")

    def test_param_count(self):
        self.assertGreaterEqual(len(vp.PARAM_DEFS), 13)


class TestOnSegment(unittest.TestCase):
    FRAMES = [b"\x1b" + bytes(32)]

    def test_save_on_writes_wav(self):
        win = _window(1)
        win._transcribe = mock.Mock()
        with mock.patch.object(vp.av, "save_wav") as save:
            win._on_segment(self.FRAMES, 1.0, "按键抬起")
        save.assert_called_once()
        self.assertIsNotNone(win.selected)
        win._transcribe_samples.assert_not_called()

    def test_save_off_does_not_write_wav(self):
        win = _window(0)
        with mock.patch.object(vp.av, "save_wav") as save:
            win._on_segment(self.FRAMES, 1.0, "按键抬起")
        save.assert_not_called()
        self.assertIsNone(win.selected)

    def test_save_off_still_recognizes_from_memory(self):
        win = _window(0, final="", auto=1)
        with mock.patch.object(vp.av, "save_wav") as save:
            win._on_segment(self.FRAMES, 1.0, "按键抬起")
        save.assert_not_called()
        win._transcribe_samples.assert_called_once()
        args = win._transcribe_samples.call_args[0][0]
        self.assertIsInstance(args, list)
        self.assertGreater(len(args), 0)

    def test_save_off_with_final_does_not_retranscribe(self):
        win = _window(0, asr_active=True, final="测试结果", auto=1)
        with mock.patch.object(vp.av, "save_wav"):
            win._on_segment(self.FRAMES, 1.0, "按键抬起")
        win._publish_text.assert_called_once_with("测试结果", same_segment=True)
        win._transcribe_samples.assert_not_called()

    def test_save_off_no_dir_created(self):
        win = _window(0)
        with mock.patch.object(vp.av, "save_wav"), \
                mock.patch.object(vp.os, "makedirs") as mk:
            win._on_segment(self.FRAMES, 1.0, "按键抬起")
        mk.assert_not_called()


class TestTranscribeSamples(unittest.TestCase):
    def test_publishes_text(self):
        win = _window(0)
        win._transcribe_samples = vp.VoiceWindow._transcribe_samples.__get__(
            win, vp.VoiceWindow)   # 恢复真方法（工厂默认用 mock 隔离）
        win.events = mock.Mock()
        # 用 mock 线程把 work() 同步跑掉，避免异步断言竞态
        with mock.patch.object(vp.threading, "Thread",
                               side_effect=lambda target, **kw:
                               mock.Mock(start=lambda: target())):
            win._transcribe_samples([1, 2, 3])
        win.asr.transcribe_samples.assert_called_once_with([1, 2, 3])
        self.assertEqual(win.events.put.call_count, 2)


class TestManualTranscribeHint(unittest.TestCase):
    def test_save_off_hint(self):
        win = _window(0)
        with mock.patch.object(vp.messagebox, "showinfo") as info:
            win._transcribe()
        self.assertIn("保存语音", info.call_args[0][1])

    def test_save_on_hint(self):
        win = _window(1)
        with mock.patch.object(vp.messagebox, "showinfo") as info:
            win._transcribe()
        self.assertEqual(info.call_args[0][1], "请先选中一条录音")


if __name__ == "__main__":
    unittest.main()
