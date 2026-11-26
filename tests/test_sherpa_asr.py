# -*- coding: utf-8 -*-
"""tests/test_sherpa_asr.py —— sherpa-onnx 引擎适配层单元测试。

用临时目录伪造模型文件结构，不依赖真实模型下载，
也不要求本机装了 sherpa-onnx（未装时测降级路径）。
"""
import os
import struct
import tempfile
import unittest
from unittest import mock

import aimouse_sherpa_asr as sasr
import aimouse_voice as av
import aimouse_voice_panel as vp


def _touch(path, size=8):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)


class _TmpModels(unittest.TestCase):
    """建一棵假的模型目录树：<root>/sherpa-onnx-xxx/。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def make_stream(self, name="sherpa-onnx-streaming-paraformer-bilingual-zh-en"):
        d = os.path.join(self.root, name)
        _touch(os.path.join(d, "encoder.int8.onnx"))
        _touch(os.path.join(d, "decoder.int8.onnx"))
        _touch(os.path.join(d, "tokens.txt"))
        return d

    def make_offline(self, name="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"):
        d = os.path.join(self.root, name)
        _touch(os.path.join(d, "model.int8.onnx"))
        _touch(os.path.join(d, "tokens.txt"))
        return d


class TestFindModelDirs(_TmpModels):
    def test_finds_both(self):
        s = self.make_stream()
        o = self.make_offline()
        self.assertEqual(sasr.find_model_dirs(self.root), (s, o))

    def test_tolerates_missing_prefix(self):
        self.make_stream("streaming-paraformer-zh")
        self.make_offline("sense-voice-small")
        s, o = sasr.find_model_dirs(self.root)
        self.assertTrue(s.endswith("streaming-paraformer-zh"))
        self.assertTrue(o.endswith("sense-voice-small"))

    def test_empty_root(self):
        self.assertEqual(sasr.find_model_dirs(self.root), ("", ""))
        self.assertEqual(sasr.find_model_dirs(os.path.join(self.root, "nope")),
                         ("", ""))

    def test_ignores_unrelated_dirs(self):
        os.makedirs(os.path.join(self.root, "vosk-model-small-cn-0.22"))
        self.assertEqual(sasr.find_model_dirs(self.root), ("", ""))


class TestPickModelFile(_TmpModels):
    def test_prefers_int8(self):
        d = os.path.join(self.root, "m")
        _touch(os.path.join(d, "model.onnx"))
        _touch(os.path.join(d, "model.int8.onnx"))
        self.assertTrue(sasr._pick_model_file(d, "model").endswith(
            "model.int8.onnx"))

    def test_falls_back_to_fp32(self):
        d = os.path.join(self.root, "m")
        _touch(os.path.join(d, "encoder.onnx"))
        self.assertTrue(sasr._pick_model_file(d, "encoder").endswith(
            "encoder.onnx"))

    def test_missing_returns_empty(self):
        d = os.path.join(self.root, "m")
        os.makedirs(d)
        self.assertEqual(sasr._pick_model_file(d, "encoder"), "")


class TestReadiness(_TmpModels):
    def test_stream_ready(self):
        d = self.make_stream()
        e = sasr.SherpaAsrEngine(self.root)
        self.assertEqual(e.stream_dir, d)
        self.assertTrue(e.stream_ready())

    def test_stream_missing_decoder(self):
        d = self.make_stream()
        os.remove(os.path.join(d, "decoder.int8.onnx"))
        self.assertFalse(sasr.SherpaAsrEngine(self.root).stream_ready())

    def test_stream_missing_tokens(self):
        d = self.make_stream()
        os.remove(os.path.join(d, "tokens.txt"))
        self.assertFalse(sasr.SherpaAsrEngine(self.root).stream_ready())

    def test_offline_ready(self):
        d = self.make_offline()
        e = sasr.SherpaAsrEngine(self.root)
        self.assertEqual(e.offline_dir, d)
        self.assertTrue(e.offline_ready())

    def test_explicit_dirs_override_probe(self):
        self.make_stream()
        custom = self.make_offline("custom-offline")
        e = sasr.SherpaAsrEngine(self.root, offline_dir=custom)
        self.assertEqual(e.offline_dir, custom)


class TestAvailable(_TmpModels):
    def test_false_when_no_models(self):
        e = sasr.SherpaAsrEngine(self.root)
        self.assertFalse(e.available())
        self.assertTrue(e.error)

    def test_false_when_sherpa_missing(self):
        self.make_stream()
        e = sasr.SherpaAsrEngine(self.root)
        with mock.patch.dict("sys.modules", {"sherpa_onnx": None}):
            self.assertFalse(e.available())
        self.assertIn("sherpa-onnx", e.error)

    def test_names(self):
        e = sasr.SherpaAsrEngine(self.root)
        self.assertEqual(e.name, "sherpa")
        self.assertEqual(e.label, "sherpa-onnx")
        self.assertFalse(e.grammar_supported())


class TestSafeWithoutModels(_TmpModels):
    """没模型时所有方法都要安静返回，不能抛异常打断录音。"""

    def setUp(self):
        super().setUp()
        self.eng = sasr.SherpaAsrEngine(self.root)

    def test_begin_false(self):
        self.assertFalse(self.eng.begin())
        self.assertTrue(self.eng.error)

    def test_feed_partial_finish_empty(self):
        self.eng.feed(b"\x01\x02")
        self.assertEqual(self.eng.partial(), "")
        self.assertEqual(self.eng.finish(), "")

    def test_transcribe_samples_none(self):
        self.assertIsNone(self.eng.transcribe_samples([1, 2, 3]))

    def test_transcribe_file_none(self):
        self.assertIsNone(self.eng.transcribe_file(os.path.join(
            self.root, "nope.wav")))

    def test_preload_false(self):
        self.assertFalse(self.eng.preload())


class TestProfile(_TmpModels):
    """有模型文件但不装 sherpa 时，preload 只报错不崩。"""

    def test_preload_reports_error(self):
        self.make_stream()
        e = sasr.SherpaAsrEngine(self.root)
        with mock.patch.dict("sys.modules", {"sherpa_onnx": None}):
            self.assertFalse(e.preload())


class TestAudioPrep(unittest.TestCase):
    def test_stereo_to_mono(self):
        left = [100, 200, 300]
        inter = []
        for v in left:
            inter.extend([v, v])
        raw = struct.pack("<%dh" % len(inter), *inter)
        out = sasr.SherpaAsrEngine._to_mono16(raw, 2, 2)
        self.assertEqual(av.pcm16_to_samples(out), left)

    def test_8bit_unsigned(self):
        raw = bytes([128, 255, 0])
        out = sasr.SherpaAsrEngine._to_mono16(raw, 1, 1)
        self.assertEqual(av.pcm16_to_samples(out), [0, 32512, -32768])

    def test_passthrough_16bit_mono(self):
        raw = struct.pack("<3h", 1, 2, 3)
        self.assertEqual(sasr.SherpaAsrEngine._to_mono16(raw, 1, 2), raw)

    def test_resample_length(self):
        samples = [0] * 8000
        pcm = av.samples_to_pcm16(samples)
        out = sasr.SherpaAsrEngine._resample(pcm, 8000, 16000)
        self.assertEqual(len(av.pcm16_to_samples(out)), 16000)

    def test_resample_same_rate_passthrough(self):
        pcm = av.samples_to_pcm16([5, 6, 7])
        self.assertEqual(sasr.SherpaAsrEngine._resample(pcm, 16000, 16000), pcm)


class TestTakePcm(_TmpModels):
    def test_take_clears_buffer(self):
        self.make_stream()
        e = sasr.SherpaAsrEngine(self.root)
        e.feed(b"abc")
        self.assertEqual(e.take_pcm(), b"abc")
        self.assertEqual(e.take_pcm(), b"")


class TestFinishFlushesGate(_TmpModels):
    """门控未打开时收尾必须把缓冲补喂给引擎，否则整段录音白录。"""

    def _engine_with_fake_stream(self):
        self.make_stream()
        eng = sasr.SherpaAsrEngine(self.root)
        stream = mock.Mock()
        rec = mock.Mock()
        rec.get_result.return_value = "你好"
        rec.is_ready.return_value = False
        eng._stream = stream
        eng._online = rec
        eng._gate = av.OnsetGate(threshold=3000)
        return eng, stream, rec

    def test_flushes_when_gate_closed(self):
        eng, stream, _ = self._engine_with_fake_stream()
        quiet = av.samples_to_pcm16([0] * 400)
        eng.feed(quiet)                       # 太轻，门控不打开
        self.assertFalse(eng._gate.opened)
        text = eng.finish()
        self.assertEqual(text, "你好")
        # 一次补喂缓冲 + 一次补尾部静音
        self.assertGreaterEqual(stream.accept_waveform.call_count, 2)

    def test_no_double_feed_when_gate_open(self):
        eng, stream, _ = self._engine_with_fake_stream()
        eng.feed(av.samples_to_pcm16([9000] * 4000))   # 高能量，门控打开
        self.assertTrue(eng._gate.opened)
        before = stream.accept_waveform.call_count
        eng.finish()
        # 只多了尾部静音那一次，没有重复补喂缓冲
        self.assertEqual(stream.accept_waveform.call_count, before + 1)

    def test_finish_without_session(self):
        self.make_stream()
        eng = sasr.SherpaAsrEngine(self.root)
        self.assertEqual(eng.finish(), "")


class TestMakeAsrEngine(_TmpModels):
    """面板工厂：按配置选引擎，缺依赖时回退 Vosk。"""

    def test_force_vosk(self):
        cfg = {"asr_engine": 2, "model_dir": "d", "asr_grammar": ""}
        self.assertIsInstance(vp.make_asr_engine(cfg), vp.AsrEngine)

    def test_auto_falls_back_to_vosk_without_models(self):
        cfg = {"asr_engine": 0, "model_dir": "d", "asr_grammar": "",
               "sherpa_model_dir": self.root}
        self.assertIsInstance(vp.make_asr_engine(cfg), vp.AsrEngine)

    def test_force_sherpa_falls_back_with_reason(self):
        cfg = {"asr_engine": 1, "model_dir": "d", "asr_grammar": "",
               "sherpa_model_dir": self.root}
        eng = vp.make_asr_engine(cfg)
        self.assertIsInstance(eng, vp.AsrEngine)
        self.assertIn("回退", eng.error)

    def test_auto_records_sherpa_hint(self):
        """自动模式退回 Vosk 时记下原因，界面据此提示可下载模型。"""
        cfg = {"asr_engine": 0, "model_dir": "d", "asr_grammar": "",
               "sherpa_model_dir": self.root}
        eng = vp.make_asr_engine(cfg)
        self.assertTrue(getattr(eng, "sherpa_hint", ""))
        # 自动模式不该把回退当成错误弹给用户
        self.assertEqual(eng.error, "")

    def test_force_sherpa_has_no_hint(self):
        cfg = {"asr_engine": 1, "model_dir": "d", "asr_grammar": "",
               "sherpa_model_dir": self.root}
        eng = vp.make_asr_engine(cfg)
        self.assertEqual(getattr(eng, "sherpa_hint", ""), "")

    def test_engine_key_changes_with_preference(self):
        a = vp.asr_engine_key({"asr_engine": 0, "model_dir": "d"})
        b = vp.asr_engine_key({"asr_engine": 2, "model_dir": "d"})
        self.assertNotEqual(a, b)

    def test_engine_key_stable(self):
        cfg = {"asr_engine": 2, "model_dir": "d", "asr_grammar": "a,b"}
        self.assertEqual(vp.asr_engine_key(cfg), vp.asr_engine_key(dict(cfg)))


class TestRefine(unittest.TestCase):
    """收尾精修：流式出结果后用 SenseVoice 定稿。"""

    def _window(self, name="sherpa", refine=1, offline=True, pcm=b"\x01\x02"):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        eng = mock.Mock()
        eng.name = name
        eng.offline_ready.return_value = offline
        eng.take_pcm.return_value = pcm
        eng.transcribe_samples.return_value = "测试语音输入123。"
        win.asr = eng
        win.cfg = {"asr_refine": refine}
        win.events = mock.Mock()
        return win, eng

    def test_skips_vosk_engine(self):
        win, eng = self._window(name="vosk")
        win._refine_async("刺试语音输入语二三")
        eng.take_pcm.assert_not_called()
        win.events.put.assert_not_called()

    def test_skips_when_disabled(self):
        win, eng = self._window(refine=0)
        win._refine_async("x")
        eng.take_pcm.assert_not_called()

    def test_skips_without_offline_model(self):
        win, eng = self._window(offline=False)
        win._refine_async("x")
        eng.take_pcm.assert_not_called()

    def test_emits_event_on_success(self):
        win, eng = self._window()
        win._refine_async("刺试语音输入语二三")
        kind, payload = win.events.put.call_args[0][0]
        self.assertEqual(kind, "asr_refine")
        fallback, better, err = payload
        self.assertEqual(fallback, "刺试语音输入语二三")
        self.assertEqual(better, "测试语音输入123。")
        self.assertEqual(err, "")

    def test_emits_event_on_error(self):
        win, eng = self._window()
        eng.transcribe_samples.side_effect = RuntimeError("boom")
        win._refine_async("x")
        kind, payload = win.events.put.call_args[0][0]
        self.assertEqual(kind, "asr_refine")
        self.assertIn("boom", payload[2])

    def test_skips_when_no_pcm(self):
        win, eng = self._window(pcm=b"")
        win._refine_async("x")
        win.events.put.assert_not_called()


class TestDispatchRefineEvent(unittest.TestCase):
    """收尾精修结果到达时：不同才覆盖，相同只更新提示。"""

    def _window(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.asr_hint = mock.Mock()
        win._publish_text = mock.Mock()
        return win

    def test_overwrites_when_different(self):
        win = self._window()
        win._dispatch(("asr_refine", ("刺试语音输入语二三", "测试语音输入123。", "")))
        win._publish_text.assert_called_once_with("测试语音输入123。")
        self.assertIn("校正", win.asr_hint.configure.call_args[1]["text"])

    def test_no_republish_when_same(self):
        win = self._window()
        win._dispatch(("asr_refine", ("测试语音输入123。", "测试语音输入123。", "")))
        win._publish_text.assert_not_called()
        self.assertIn("复核", win.asr_hint.configure.call_args[1]["text"])

    def test_reports_error(self):
        win = self._window()
        win._dispatch(("asr_refine", ("x", "", "boom")))
        win._publish_text.assert_not_called()
        self.assertIn("boom", win.asr_hint.configure.call_args[1]["text"])


class TestVoskEngineNames(unittest.TestCase):
    def test_label_and_grammar(self):
        e = vp.AsrEngine("whatever/vosk-model-small-cn-0.22")
        self.assertEqual(e.name, "vosk")
        self.assertEqual(e.label, "Vosk")
        self.assertTrue(e.grammar_supported())

    def test_big_model_has_no_grammar(self):
        e = vp.AsrEngine("whatever/vosk-model-cn-0.22")
        self.assertFalse(e.grammar_supported())


class TestNormalizeShared(unittest.TestCase):
    """归一化函数下移到 aimouse_voice 后，面板导出仍是同一行为。"""

    def test_panel_forwards(self):
        for s in ("测试 语音 输入", "hello world", "", None, "测试 ABC 123 输入"):
            self.assertEqual(vp.normalize_asr_text(s), av.normalize_asr_text(s))

    def test_pcm_roundtrip(self):
        samples = [0, 1, -1, 32767, -32768]
        self.assertEqual(av.pcm16_to_samples(av.samples_to_pcm16(samples)),
                         samples)

    def test_pcm_odd_length_safe(self):
        self.assertEqual(av.pcm16_to_samples(b"\x01\x02\x03"),
                         av.pcm16_to_samples(b"\x01\x02"))


if __name__ == "__main__":
    unittest.main()
