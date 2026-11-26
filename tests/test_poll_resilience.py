# -*- coding: utf-8 -*-
"""事件轮询健壮性与音频帧自动开始的回归测试。

核心回归：任何单个事件抛异常都不能让 _poll 的 after() 调度丢失，
否则整个语音功能会静默失效（无 WAV、无转写、无输入）。
"""
import queue
import time
import unittest
from unittest import mock

import aimouse_voice_panel as vp


class _FakeLabel:
    def __init__(self):
        self.values = {}

    def configure(self, **kw):
        self.values.update(kw)


def _window():
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win.events = queue.Queue()
    win._focus_poll_at = time.monotonic()   # 跳过 0.4s 焦点轮询
    win._focus_target = None
    win.after = mock.Mock()
    win.status = _FakeLabel()
    win._dispatch = mock.Mock()
    return win


class TestPollResilience(unittest.TestCase):
    def test_event_error_still_reschedules(self):
        win = _window()
        win.events.put(("audio", b"\x1b"))
        win._dispatch.side_effect = RuntimeError("boom")
        win._poll()
        win.after.assert_called_once()
        self.assertEqual(win.after.call_args[0][1], win._poll)

    def test_multiple_errors_do_not_stop_polling(self):
        win = _window()
        for _ in range(5):
            win.events.put(("audio", b"\x1b"))
        win._dispatch.side_effect = RuntimeError("boom")
        win._poll()
        self.assertEqual(win._dispatch.call_count, 5)
        win.after.assert_called_once()

    def test_empty_queue_uses_normal_delay(self):
        win = _window()
        win._poll()
        self.assertEqual(win.after.call_args[0][0], 40)

    def test_backlog_uses_immediate_reschedule(self):
        win = _window()
        for _ in range(200):
            win.events.put(("audio", b"\x1b"))
        win._poll()
        self.assertEqual(win.after.call_args[0][0], 0)
        self.assertEqual(win._dispatch.call_count, 120)
        self.assertEqual(win.events.qsize(), 80)

    def test_focus_poll_error_does_not_stop_polling(self):
        win = _window()
        win._focus_poll_at = 0.0
        with mock.patch.object(vp.vt, "track_focus",
                               side_effect=RuntimeError("win32")):
            win._poll()
        win.after.assert_called_once()

    def test_status_configure_error_is_contained(self):
        win = _window()
        win.events.put(("audio", b"\x1b"))
        win._dispatch.side_effect = RuntimeError("boom")
        win.status.configure = mock.Mock(side_effect=RuntimeError("tk"))
        win._poll()
        win.after.assert_called_once()


class TestAudioFrameAutoStart(unittest.TestCase):
    def test_audio_frame_starts_recording_without_status_frame(self):
        rec = vp.Recorder(queue.Queue())
        rec._on_audio_frame(b"\x1b" + bytes(32), now=200.0)
        self.assertTrue(rec._recording)
        self.assertEqual(rec._start_ts, 200.0)
        kinds = []
        while True:
            try:
                kinds.append(rec.events.get_nowait()[0])
            except queue.Empty:
                break
        self.assertEqual(kinds, ["start", "audio"])

    def test_tail_frames_ignored_during_cooldown(self):
        rec = vp.Recorder(queue.Queue())
        rec._recording = True
        rec._start_ts = 100.0
        rec._last_ts = 100.0
        rec._frames = [b"\x1b" + bytes(32)]
        rec._finish("按键抬起", now=100.2)
        self.assertAlmostEqual(rec._cooldown_until, 100.7)
        # 冷却期内的尾部帧不应重新开录
        rec._on_audio_frame(b"\x1b" + bytes(32), now=100.4)
        self.assertFalse(rec._recording)
        # 冷却期之后可以重新开始
        rec._on_audio_frame(b"\x1b" + bytes(32), now=100.8)
        self.assertTrue(rec._recording)

    def test_already_recording_appends(self):
        rec = vp.Recorder(queue.Queue())
        rec._recording = True
        rec._start_ts = 1.0
        rec._last_ts = 1.0
        rec._on_audio_frame(b"\x1b" + bytes(32), now=1.1)
        self.assertEqual(len(rec._frames), 1)
        self.assertEqual(rec._last_ts, 1.1)


if __name__ == "__main__":
    unittest.main()
