# -*- coding: utf-8 -*-
"""增量解码器回归：流式识别必须与整段识别喂同一份正确 PCM。

历史 bug：流式路径用 ``decode_frame()``（每帧独立、**不做 XOR 解扰**），
把加扰噪声喂给 Vosk，导致流式永远识别不出文字，而整段/手动转文字正常。
"""
import unittest
from unittest import mock

import aimouse_voice as av
import aimouse_voice_panel as vp
from tests.test_local_decode import FRAMES, EXPECTED_HEAD, EXPECTED_TAIL


class TestLocalStreamDecoder(unittest.TestCase):
    def test_matches_batch_decode_byte_for_byte(self):
        dec = av.LocalStreamDecoder()
        streamed = []
        for frame in FRAMES:
            streamed.extend(dec.feed(frame))
        self.assertEqual(streamed, av.decode_frames_local(FRAMES))

    def test_prefix_matches_batch_prefix(self):
        """增量喂到第 N 帧，结果必须等于整段解码的前 N 帧。"""
        dec = av.LocalStreamDecoder()
        for n in range(1, len(FRAMES) + 1):
            dec.reset()
            got = []
            for frame in FRAMES[:n]:
                got.extend(dec.feed(frame))
            self.assertEqual(got, av.decode_frames_local(FRAMES[:n]))

    def test_each_frame_yields_56_samples(self):
        dec = av.LocalStreamDecoder()
        for frame in FRAMES:
            self.assertEqual(len(dec.feed(frame)), av.SAMPLES_PER_FRAME)

    def test_state_is_kept_across_frames(self):
        dec = av.LocalStreamDecoder()
        dec.feed(FRAMES[0])
        self.assertNotEqual((dec.pred, dec.index), (0, 0))

    def test_invalid_frame_returns_empty(self):
        dec = av.LocalStreamDecoder()
        self.assertEqual(dec.feed(b"\x00" * 33), [])
        self.assertEqual(dec.feed(b"\x1b"), [])

    def test_reset(self):
        dec = av.LocalStreamDecoder()
        dec.feed(FRAMES[0])
        dec.reset()
        self.assertEqual((dec.pred, dec.index), (0, 0))

    def test_expected_head_and_tail(self):
        out = av.decode_frames_local(FRAMES)
        self.assertEqual(out[:12], EXPECTED_HEAD)
        self.assertEqual(out[-4:], EXPECTED_TAIL)


def _stream_window():
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win._stream_decoder = av.LocalStreamDecoder()
    win._asr_active = True
    win._ui_tick = 0.0
    win._partial = ""
    win.meter = mock.Mock()
    win.meter.winfo_width.return_value = 300
    win.meter_fill = 1
    win.asr = mock.Mock()
    win.asr.partial.return_value = ""
    win._set_text = mock.Mock()
    return win


class TestStreamFeedsCorrectPcm(unittest.TestCase):
    def test_stream_feeds_xor_decoded_pcm(self):
        """核心回归：流式喂给 Vosk 的必须是解扰 + 跨帧连续的正确波形。"""
        win = _stream_window()
        win._on_audio(FRAMES[0])
        pcm = win.asr.feed.call_args[0][0]
        expected = av.samples_to_pcm16(av.LocalStreamDecoder().feed(FRAMES[0]))
        self.assertEqual(pcm, expected)

    def test_stream_does_not_feed_old_broken_decode(self):
        win = _stream_window()
        win._on_audio(FRAMES[0])
        pcm = win.asr.feed.call_args[0][0]
        broken = av.samples_to_pcm16(av.decode_frame(FRAMES[0]))
        self.assertNotEqual(pcm, broken)

    def test_segment_mode_has_no_decoder(self):
        """整段模式不喂流，音量条用轻量单帧解码即可。"""
        win = _stream_window()
        win._stream_decoder = None
        win._asr_active = False
        win._on_audio(FRAMES[0])
        win.asr.feed.assert_not_called()

    def test_decoder_state_advances_per_frame(self):
        win = _stream_window()
        dec = win._stream_decoder
        self.assertEqual((dec.pred, dec.index), (0, 0))
        win._on_audio(FRAMES[0])
        self.assertNotEqual((dec.pred, dec.index), (0, 0))


if __name__ == "__main__":
    unittest.main()
