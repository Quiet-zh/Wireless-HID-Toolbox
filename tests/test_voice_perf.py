# -*- coding: utf-8 -*-
"""录制收尾与转文字性能相关回归测试。

重点覆盖「松开语音键后一直显示处理中」的卡死 bug：
长按抬起帧必须能独立触发收尾，且收尾判定不受音频帧 continue 影响。
"""
import os
import queue
import tempfile
import unittest
from unittest import mock

import aimouse_voice as av
import aimouse_voice_panel as vp


def _recording_recorder(start=100.0):
    rec = vp.Recorder(queue.Queue(), max_seconds=30)
    rec._recording = True
    rec._start_ts = start
    rec._last_ts = start
    rec._frames = [b"\x1b" + bytes(32)] * 3
    return rec


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


class TestRecorderFinish(unittest.TestCase):
    def test_key_up_schedules_finish(self):
        rec = _recording_recorder()
        rec.note_key(0x38, now=105.0)
        self.assertAlmostEqual(rec._finish_at, 105.15)
        rec.note_key(0x32, now=105.05)      # 重复抬起不覆盖
        self.assertAlmostEqual(rec._finish_at, 105.15)

    def test_key_up_ignored_when_not_recording(self):
        rec = vp.Recorder(queue.Queue())
        rec.note_key(0x38, now=10.0)
        self.assertEqual(rec._finish_at, 0.0)

    def test_no_finish_before_grace(self):
        rec = _recording_recorder(start=105.0)   # 刚收到音频帧
        rec.note_key(0x38, now=105.0)
        rec._check_finish(105.14)          # 音频帧 continue 期间也会调用
        self.assertEqual(_drain(rec.events), [])
        self.assertTrue(rec._recording)

    def test_finish_at_grace_without_status_frame(self):
        """核心回归：只有 0x04/0x38 抬起帧，没有 0x05/0x63 也必须收尾。"""
        rec = _recording_recorder(start=105.0)
        rec.note_key(0x38, now=105.0)
        rec._check_finish(105.10)
        rec._check_finish(105.16)
        events = _drain(rec.events)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "segment")
        self.assertEqual(events[0][3], "按键抬起")
        self.assertFalse(rec._recording)
        self.assertEqual(rec._finish_at, 0.0)

    def test_audio_frames_do_not_block_finish(self):
        """音频帧分支会 continue，收尾判定放在循环开头仍会执行。"""
        rec = _recording_recorder(start=105.0)
        rec.note_key(0x32, now=105.0)
        for t in (105.02, 105.04, 105.08, 105.12, 105.16):
            rec._check_finish(t)           # 模拟每轮循环开头
        self.assertEqual(_drain(rec.events)[0][3], "按键抬起")

    def test_audio_gap_timeout_is_short(self):
        rec = _recording_recorder(start=100.0)
        rec._last_ts = 100.0
        rec._check_finish(100.59)
        self.assertEqual(_drain(rec.events), [])
        rec._check_finish(100.61)
        self.assertEqual(_drain(rec.events)[0][3], "音频中断")

    def test_max_seconds_timeout(self):
        rec = vp.Recorder(queue.Queue(), max_seconds=2)
        rec._recording = True
        rec._start_ts = 0.0
        rec._last_ts = 1.9
        rec._check_finish(2.1)
        self.assertEqual(_drain(rec.events)[0][3], "达到时长上限")


class TestModelCache(unittest.TestCase):
    def setUp(self):
        vp._MODEL_CACHE.clear()

    def tearDown(self):
        vp._MODEL_CACHE.clear()

    def test_same_dir_loads_once(self):
        with mock.patch.object(vp.AsrEngine, "available", return_value=True), \
                mock.patch.dict("sys.modules", {"vosk": mock.MagicMock()}) as m:
            vosk = m["vosk"]
            a = vp.AsrEngine("dir1")
            b = vp.AsrEngine("dir1")
            self.assertTrue(a.preload())
            self.assertTrue(b.preload())
            vosk.Model.assert_called_once_with("dir1")
            self.assertIs(a._model, b._model)

    def test_preload_failure_is_captured(self):
        with mock.patch.object(vp.AsrEngine, "available", return_value=True), \
                mock.patch.object(vp.AsrEngine, "_ensure_model",
                                  side_effect=RuntimeError("boom")):
            e = vp.AsrEngine("dir2")
            self.assertFalse(e.preload())
            self.assertIn("boom", e.error)


class TestFeedPartial(unittest.TestCase):
    def test_feed_only_accepts_waveform(self):
        e = vp.AsrEngine("d")
        e._rec = mock.Mock()
        e._rec.PartialResult.return_value = '{"partial": "你好"}'
        e.feed(b"pcm")
        e._rec.AcceptWaveform.assert_called_once_with(b"pcm")
        e._rec.PartialResult.assert_not_called()
        self.assertEqual(e.partial(), "你好")


class TestSyncAsr(unittest.TestCase):
    def test_reuses_instance_when_model_unchanged(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.asr = vp.AsrEngine("d", "")
        win.cfg = {"model_dir": "d", "asr_grammar": "测试,语音"}
        win._sync_asr(warm=False)
        self.assertIs(win.asr.model_dir, "d")
        self.assertEqual(win.asr.grammar, "测试,语音")

    def test_rebuilds_when_model_changed(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        old = vp.AsrEngine("d1", "")
        win.asr = old
        win.cfg = {"model_dir": "d2", "asr_grammar": ""}
        win._sync_asr(warm=False)
        self.assertIsNot(win.asr, old)
        self.assertEqual(win.asr.model_dir, "d2")


class TestNoDoubleTranscribe(unittest.TestCase):
    def _window(self, asr_active, final=""):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.asr = mock.Mock()
        win.asr.finish.return_value = final
        win.asr_hint = mock.Mock()
        win.status = mock.Mock()
        win.meter = mock.Mock()
        win.meter.winfo_width.return_value = 300
        win.meter_fill = 1
        win.meter_text = mock.Mock()
        win.listbox = mock.Mock()
        win._paths = []
        win.cfg = {"highpass": 0, "peak": 26000, "denoise": 0,
                    "auto_transcribe": 1, "voice_typing": 0,
                    "save_dir": tempfile.mkdtemp(prefix="vh_perf_")}
        win._asr_active = asr_active
        win._partial = ""
        win.selected = None
        win._set_text = mock.Mock()
        win._publish_text = mock.Mock()
        win._refresh_list = mock.Mock()
        win._sync_selection = mock.Mock()
        win._transcribe = mock.Mock()
        return win

    def test_stream_empty_falls_back_to_file(self):
        """流式没出文字时回退整段识别一次，保证用户能拿到结果。"""
        win = self._window(asr_active=True, final="")
        frame = b"\x1b" + bytes(32)
        win._on_segment([frame], 1.0, "按键抬起")
        win.asr.finish.assert_called_once()
        win._transcribe.assert_called_once()

    def test_stream_never_started_falls_back(self):
        win = self._window(asr_active=False)
        frame = b"\x1b" + bytes(32)
        win._on_segment([frame], 1.0, "音频中断")
        win._transcribe.assert_called_once()

    def test_final_text_published(self):
        win = self._window(asr_active=True, final="测试语音输入")
        frame = b"\x1b" + bytes(32)
        win._on_segment([frame], 1.0, "按键抬起")
        win._publish_text.assert_called_once_with("测试语音输入")
        win._transcribe.assert_not_called()


class TestDurationEstimate(unittest.TestCase):
    def test_estimate_matches_wave_header(self):
        path = os.path.join(tempfile.mkdtemp(prefix="vh_dur_"), "x.wav")
        av.save_wav(path, [0] * 16000)      # 1 秒
        self.assertEqual(vp.VoiceWindow._duration(path).strip(), "1.0s")

    def test_bad_path_fallback(self):
        self.assertEqual(vp.VoiceWindow._duration("no_such_file.wav").strip(),
                         "?")


if __name__ == "__main__":
    unittest.main()
