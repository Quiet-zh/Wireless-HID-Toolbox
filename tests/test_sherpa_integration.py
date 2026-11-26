# -*- coding: utf-8 -*-
"""tests/test_sherpa_integration.py —— 真实模型 + 真实录音的端到端验证。

和单元测试不同，这里跑真实链路：设备帧 → LocalStreamDecoder（XOR + 跨帧
连续 IMA）→ sherpa 流式引擎 → 文本，也就是语音面板 `_on_audio` 走的那条路。

需要本机装有 sherpa-onnx 且已下载模型，否则整体 skip（CI / 新机器上不失败）：

    python tools/download_models.py
"""
import os
import unittest

import aimouse_voice as av

ROOT = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"),
    "ExtBatteryTray", "models")

# 真实设备录音（Frida 抓包里的 0x1B 帧），真值「测试语音输入一二三」
CAPTURE = os.path.join(
    os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp",
    "frida_record.jsonl")


def _load_frames(path):
    import json
    frames = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                raw = bytes.fromhex(rec.get("hex") or "")
            except (ValueError, TypeError):
                continue
            if len(raw) == av.FRAME_SIZE and raw[0] == av.FRAME_ID:
                frames.append(raw)
    return frames


def _sherpa_available():
    try:
        import sherpa_onnx  # noqa: F401
    except Exception:
        return False
    import aimouse_sherpa_asr as sasr
    return sasr.SherpaAsrEngine(ROOT).stream_ready()


@unittest.skipUnless(_sherpa_available(), "需要 sherpa-onnx 与流式模型")
class TestRealCaptureStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import aimouse_sherpa_asr as sasr
        cls.eng = sasr.SherpaAsrEngine(ROOT)
        cls.eng.preload(stream=True)

    def test_stream_pipeline_produces_text(self):
        """真实录音走面板同款链路后应出中文文本，且包含「语音输入」。"""
        if not os.path.isfile(CAPTURE):
            self.skipTest("缺少真实抓包文件")
        frames = _load_frames(CAPTURE)
        self.assertGreater(len(frames), 1000)

        self.assertTrue(self.eng.begin())
        decoder = av.LocalStreamDecoder()
        for frame in frames:
            pcm = av.samples_to_pcm16(decoder.feed(frame))
            self.eng.feed(pcm)
        text = self.eng.finish()
        self.assertTrue(text, "流式识别结果为空")
        self.assertIn("语音输入", text)

    def test_leading_silence_is_gated(self):
        """门控应丢掉 1 秒以上的前导静音，同时保留全部有声段。"""
        if not os.path.isfile(CAPTURE):
            self.skipTest("缺少真实抓包文件")
        frames = _load_frames(CAPTURE)
        samples = av.decode_frames_local(frames)
        start = av.find_onset(samples)
        # 实测约 1.46s；给足余量，只要落在合理区间即可
        self.assertGreater(start, av.SAMPLE_RATE * 0.8)
        self.assertLess(start, av.SAMPLE_RATE * 1.6)
        self.assertGreater(len(samples) - start, av.SAMPLE_RATE * 3)

    def test_gate_drops_less_than_whole(self):
        """流式门控只丢前导静音，不会把有效的 3 秒语音一起丢掉。"""
        if not os.path.isfile(CAPTURE):
            self.skipTest("缺少真实抓包文件")
        frames = _load_frames(CAPTURE)
        gate = av.OnsetGate()
        decoder = av.LocalStreamDecoder()
        kept = 0
        for frame in frames:
            # 必须用同一个增量解码器，逐帧独立解码会丢掉跨帧 predictor
            pcm = av.samples_to_pcm16(decoder.feed(frame))
            kept += len(gate.push(pcm))
        kept += len(gate.flush())
        # 5.35s 录音裁掉约 1.3s 静音后仍应有 3.8s 左右
        self.assertGreater(kept / 2 / av.SAMPLE_RATE, 3.0)


def _offline_available():
    import aimouse_sherpa_asr as sasr
    return sasr.SherpaAsrEngine(ROOT).offline_ready()


@unittest.skipUnless(_sherpa_available() and _offline_available(),
                     "需要 sherpa-onnx 与 SenseVoice 模型")
class TestRefineEndToEnd(unittest.TestCase):
    """流式出字 + SenseVoice 定稿：最终文本应完全正确。"""

    @classmethod
    def setUpClass(cls):
        import aimouse_sherpa_asr as sasr
        cls.eng = sasr.SherpaAsrEngine(ROOT)
        cls.eng.preload()

    def test_refine_recovers_full_sentence(self):
        if not os.path.isfile(CAPTURE):
            self.skipTest("缺少真实抓包文件")
        frames = _load_frames(CAPTURE)
        self.assertTrue(self.eng.begin())
        decoder = av.LocalStreamDecoder()
        for frame in frames:
            self.eng.feed(av.samples_to_pcm16(decoder.feed(frame)))
        stream_text = self.eng.finish()
        self.assertTrue(stream_text)

        # 面板收尾时就是这条路：take_pcm → SenseVoice 重识别
        pcm = self.eng.take_pcm()
        refined = self.eng.transcribe_samples(av.pcm16_to_samples(pcm))
        self.assertTrue(refined)
        # 真值「测试语音输入一二三」，SenseVoice 开 ITN 后给出阿拉伯数字
        self.assertIn("测试语音输入", refined)
        self.assertIn("123", refined)

    def test_take_pcm_empty_after_finish(self):
        """精修取过一次后缓冲要清空，下一段录音从头累积。"""
        self.eng.take_pcm()
        self.assertEqual(self.eng.take_pcm(), b"")


@unittest.skipUnless(_offline_available(), "需要 sherpa-onnx 与 SenseVoice 模型")
class TestOfflinePathEndToEnd(unittest.TestCase):
    """整段模式（stream_asr=0）：不喂流式，直接 SenseVoice。"""

    @classmethod
    def setUpClass(cls):
        import aimouse_sherpa_asr as sasr
        cls.eng = sasr.SherpaAsrEngine(ROOT)
        cls.eng.preload(False)

    def test_transcribe_samples_full_sentence(self):
        if not os.path.isfile(CAPTURE):
            self.skipTest("缺少真实抓包文件")
        frames = _load_frames(CAPTURE)
        samples = av.decode_frames_local(frames)
        text = self.eng.transcribe_samples(samples) or ""
        self.assertIn("测试语音输入", text)
        self.assertIn("123", text)


if __name__ == "__main__":
    unittest.main()
