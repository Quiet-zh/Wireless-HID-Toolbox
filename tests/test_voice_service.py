# -*- coding: utf-8 -*-
"""语音独立组件（voice_service）的单元测试。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import aimouse_voice_panel as vp
import voice_service as vs


class _FakeAsr:
    def __init__(self, stream_text="", offline_text="测试语音输入",
                 name="vosk", offline=True):
        self.name = name
        self.error = ""
        self.stream_text = stream_text
        self.offline_text = offline_text
        self.offline = offline
        self.fed = []
        self.begun = False

    def begin(self):
        self.begun = True
        return True

    def feed(self, pcm):
        self.fed.append(pcm)

    def finish(self):
        return self.stream_text

    def transcribe_samples(self, samples):
        return self.offline_text

    def offline_ready(self):
        return self.offline


def _service(cfg=None, **kwargs):
    cfg = cfg or {"stream_asr": 1, "asr_refine": 0, "max_seconds": 30,
                  "highpass": 0, "peak": 26000, "onset_gate": 1}
    return vs.VoiceInputService(cfg=cfg, **kwargs)


class TestPanelAliases(unittest.TestCase):
    def test_shared_classes(self):
        self.assertIs(vp.AsrEngine, vs.AsrEngine)
        self.assertIs(vp.Recorder, vs.Recorder)
        self.assertIs(vp.make_asr_engine, vs.make_asr_engine)
        self.assertEqual(vp.DEFAULTS, vs.DEFAULTS)
        self.assertIs(vp._MODEL_CACHE, vs._MODEL_CACHE)

    def test_config_path_argument(self):
        path = os.path.join(tempfile.gettempdir(), "voice_service_test.json")
        try:
            cfg = vs.load_config(path)
            cfg["highpass"] = 321
            vs.save_config(cfg, path)
            self.assertEqual(vs.load_config(path)["highpass"], 321)
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestVoiceInputService(unittest.TestCase):
    def test_start_without_interface(self):
        svc = _service()
        with mock.patch.object(vs.avc, "find_interface", return_value=None):
            self.assertFalse(svc.start())
        self.assertIn("0xFF91", svc.last_error)
        svc.stop()

    def test_stop_without_start_is_noop(self):
        _service().stop()

    def test_segment_without_frames_reports(self):
        status = []
        svc = _service(on_status=status.append)
        svc._on_segment([], 0.0, "按键抬起")
        self.assertTrue(any("没录到音频" in text for text in status))

    def test_segment_mode_does_not_start_asr(self):
        svc = _service(cfg={"stream_asr": 0})
        svc.asr = _FakeAsr()
        svc._on_start()
        self.assertIsNone(svc._decoder)
        self.assertFalse(svc.asr.begun)

    def test_stream_mode_starts_decoder_and_asr(self):
        svc = _service(cfg={"stream_asr": 1})
        svc.asr = _FakeAsr()
        svc._on_start()
        self.assertIsNotNone(svc._decoder)
        # begin 在后台线程，等它跑完
        for _ in range(50):
            if svc.asr.begun:
                break
            import time
            time.sleep(0.01)
        self.assertTrue(svc.asr.begun)

    def test_audio_feeds_asr(self):
        svc = _service(cfg={"stream_asr": 1})
        svc.asr = _FakeAsr()
        svc._asr_active = True
        svc._decoder = vs.av.LocalStreamDecoder()
        svc._on_audio(b"\x1b" + bytes(32))
        self.assertEqual(len(svc.asr.fed), 1)

    def test_segment_types_text(self):
        svc = _service(cfg={"stream_asr": 0})
        svc.asr = _FakeAsr(offline_text="测试语音输入123")
        svc._focus_target = object()
        texts = []
        svc.on_text = texts.append
        with mock.patch.object(vs.av, "decode_frames_local",
                               return_value=[0] * 16000), \
                mock.patch.object(vs.vt, "type_text",
                                  return_value=(True, "已键入")) as typed:
            svc._on_segment([b"frame"], 1.0, "按键抬起")
        self.assertEqual(texts, ["测试语音输入123"])
        typed.assert_called_once()
        self.assertEqual(typed.call_args[0][0], "测试语音输入123")

    def test_segment_refines_with_sensevoice(self):
        svc = _service(cfg={"stream_asr": 1, "asr_refine": 1})
        svc.asr = _FakeAsr(stream_text="流式结果", offline_text="精修结果",
                           name="sherpa", offline=True)
        svc._asr_active = True
        svc._focus_target = object()
        texts = []
        svc.on_text = texts.append
        with mock.patch.object(vs.av, "decode_frames_local",
                               return_value=[0] * 1600), \
                mock.patch.object(vs.vt, "type_text",
                                  return_value=(True, "")):
            svc._on_segment([b"frame"], 0.1, "按键抬起")
        self.assertEqual(texts, ["精修结果"])

    def test_typing_without_target_reports(self):
        status = []
        svc = _service(on_status=status.append)
        svc._focus_target = None
        svc._type_text("你好")
        self.assertTrue(any("未检测到外部输入框" in text for text in status))

    def test_typing_unsupported(self):
        status = []
        svc = _service(on_status=status.append)
        with mock.patch.object(vs.vt, "supported", return_value=False):
            svc._type_text("你好")
        self.assertTrue(any("仅支持 Windows" in text for text in status))


class TestConfigDefaults(unittest.TestCase):
    def test_stream_default(self):
        self.assertEqual(vs.DEFAULTS["stream_asr"], 1)
        self.assertEqual(vs.DEFAULTS["asr_refine"], 1)
        self.assertEqual(vs.DEFAULTS["onset_gate"], 1)

    def test_parameter_count(self):
        self.assertGreaterEqual(len(vs.PARAM_DEFS), 19)


if __name__ == "__main__":
    unittest.main()
