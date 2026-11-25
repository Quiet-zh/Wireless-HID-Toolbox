# -*- coding: utf-8 -*-
"""云端 ASR 协议与兜底后端的纯数据单元测试（不联网、不建窗口）。"""
import base64
import os
import struct
import tempfile
import unittest

import aimouse_cloud_asr as ca
import aimouse_voice_panel as vp


class TestCloudCredentials(unittest.TestCase):
    def test_masked_never_leaks_key(self):
        cred = ca.CloudCredentials("SECRET_KEY_32_CHARS_abcdefghijk",
                                   "00-E0-1D-92-E4-6E", "ML20251020021000A3")
        masked = cred.masked()
        self.assertNotIn("SECRET", masked)
        self.assertIn("ML2025", masked)

    def test_common_fields(self):
        cred = ca.CloudCredentials("k", "d", "s")
        common = cred.common()
        for key in ("apiKey", "clientId", "deviceNo", "serialNo",
                    "language", "dwa", "ptt"):
            self.assertIn(key, common)
        self.assertEqual(common["language"], "ZH_CN")

    def test_client_id_unique(self):
        a = ca.CloudCredentials("k", "d", "s")
        b = ca.CloudCredentials("k", "d", "s")
        self.assertNotEqual(a.client_id, b.client_id)


class TestFrameBuilding(unittest.TestCase):
    def setUp(self):
        self.cred = ca.CloudCredentials("k", "d", "s")
        # 3 块多一点：2016*3 + 100
        self.pcm = b"\x01\x00" * (ca.CHUNK_BYTES // 2 * 3 + 50)

    def test_split_sizes(self):
        chunks = ca.split_pcm(self.pcm)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(len(chunks[0]), ca.CHUNK_BYTES)
        self.assertEqual(len(chunks[-1]), 100)

    def test_first_and_last_flags(self):
        frames = ca.build_frames(self.pcm, self.cred)
        self.assertEqual(len(frames), 4)
        self.assertTrue(frames[0]["start"])
        self.assertFalse(frames[0]["end"])
        self.assertTrue(frames[-1]["end"])
        self.assertFalse(frames[-1]["start"])
        for mid in frames[1:-1]:
            self.assertFalse(mid["start"])
            self.assertFalse(mid["end"])

    def test_every_frame_has_audio(self):
        frames = ca.build_frames(self.pcm, self.cred)
        for frame in frames:
            self.assertTrue(frame["content"])
            raw = base64.b64decode(frame["content"])
            self.assertGreater(len(raw), 0)
            self.assertLessEqual(len(raw), ca.CHUNK_BYTES)

    def test_frame_fields_exact(self):
        frames = ca.build_frames(self.pcm[:100], self.cred)
        self.assertEqual(set(frames[0].keys()), set(ca.FRAME_FIELDS))

    def test_empty_pcm(self):
        self.assertEqual(ca.build_frames(b"", self.cred), [])


class TestResponseParsing(unittest.TestCase):
    def test_mid(self):
        raw = '{"data":{"type":"MID","text":"次试","sn":"x"},"message":"操作成功"}'
        self.assertEqual(ca.parse_response(raw), ("MID", "次试", "操作成功"))

    def test_last(self):
        raw = '{"data":{"type":"LAST","text":"测试语音输入1。"},"message":"操作成功"}'
        self.assertEqual(ca.parse_response(raw)[0], "LAST")

    def test_invalid(self):
        self.assertEqual(ca.parse_response("not json"), ("", "", ""))


class TestWavReading(unittest.TestCase):
    def test_transcribe_wav_rejects_bad_header(self):
        path = os.path.join(tempfile.gettempdir(), "not_a_wav.bin")
        with open(path, "wb") as fh:
            fh.write(b"garbage")
        try:
            self.assertIsNone(ca.transcribe_wav(path))
        finally:
            os.remove(path)


class TestBackendSettings(unittest.TestCase):
    def test_asr_backend_param_present(self):
        keys = [d[0] for d in vp.PARAM_DEFS]
        self.assertIn("asr_backend", keys)

    def test_asr_backend_range(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "asr_backend")
        _key, _label, _desc, default, lo, hi, step, kind = item
        self.assertEqual(kind, "int")
        self.assertEqual((lo, hi, step), (0, 3, 1))
        self.assertLessEqual(lo, default)
        self.assertLessEqual(default, hi)

    def test_backend_chain_modes(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"asr_backend": 0, "local_only": 0}
        self.assertEqual(win._backend_chain(False), ["vosk", "cloud"])
        self.assertEqual(win._backend_chain(True),
                         ["vosk", "cloud", "clipboard"])
        win.cfg = {"asr_backend": 1, "local_only": 0}
        self.assertEqual(win._backend_chain(False), ["vosk"])
        win.cfg = {"asr_backend": 2, "local_only": 0}
        self.assertEqual(win._backend_chain(True), ["clipboard"])
        win.cfg = {"asr_backend": 3, "local_only": 0}
        self.assertEqual(win._backend_chain(False), ["cloud"])

    def test_local_only_forces_vosk(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        for mode in (0, 1, 2, 3):
            win.cfg = {"asr_backend": mode, "local_only": 1}
            self.assertEqual(win._backend_chain(True), ["vosk"])

    def test_local_only_default(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "local_only")
        self.assertEqual(item[3], 1)
        self.assertEqual(item[7], "bool")

    def test_clipboard_helpers_callable(self):
        self.assertIsInstance(vp.clipboard_sequence(), int)
        self.assertIsInstance(vp.clipboard_text(), str)


class TestGrammarSettings(unittest.TestCase):
    def test_grammar_param_present(self):
        item = next(d for d in vp.PARAM_DEFS if d[0] == "asr_grammar")
        self.assertEqual(item[7], "text")
        self.assertEqual(item[3], "")

    def test_engine_keeps_grammar(self):
        engine = vp.AsrEngine("some_dir", "测试,语音,输入,一二三")
        self.assertEqual(engine.grammar, "测试,语音,输入,一二三")

    def test_engine_default_grammar_empty(self):
        self.assertEqual(vp.AsrEngine("some_dir").grammar, "")

    def test_grammar_word_split(self):
        # 逗号/中文逗号/空白都应能切分
        import re
        for text in ("测试,语音,输入", "测试，语音，输入", "测试 语音 输入"):
            words = [w for w in re.split(r"[,，\s]+", text.strip()) if w]
            self.assertEqual(words, ["测试", "语音", "输入"])

    def test_big_model_dir_defined(self):
        self.assertTrue(vp.BIG_MODEL_DIR.endswith("vosk-model-cn-0.22"))

    def test_grammar_only_on_small_model(self):
        self.assertTrue(vp.AsrEngine(
            "vosk-model-small-cn-0.22")._grammar_supported())
        self.assertFalse(vp.AsrEngine(
            "vosk-model-cn-0.22")._grammar_supported())

    def test_param_count(self):
        self.assertGreaterEqual(len(vp.PARAM_DEFS), 10)


if __name__ == "__main__":
    unittest.main()
