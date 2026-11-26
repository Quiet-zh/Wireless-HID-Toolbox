# -*- coding: utf-8 -*-
"""tests/test_onset_gate.py —— 前导静音裁剪 / 语音起点门控。

背景：设备按下语音键后有 1~1.5 秒纯底噪，这段静音喂给 ASR 会让模型
在句首「听出」不存在的字。用真实录音验证过，裁掉后整句准确率明显提升。
"""
import struct
import unittest

import aimouse_voice as av
import aimouse_voice_panel as vp

RATE = av.SAMPLE_RATE


def silence(ms, amp=0):
    """生成一段静音（amp=0 为绝对静音，否则是低幅底噪）。"""
    return [amp if i % 2 else -amp for i in range(int(RATE * ms / 1000))]


def tone(ms, amp=8000):
    """生成一段方波，模拟语音能量。"""
    n = int(RATE * ms / 1000)
    return [amp if (i // 80) % 2 == 0 else -amp for i in range(n)]


class TestRms(unittest.TestCase):
    def test_samples_rms(self):
        self.assertEqual(av.samples_rms([]), 0.0)
        self.assertAlmostEqual(av.samples_rms([3, 4]), (12.5) ** 0.5)

    def test_pcm_rms_matches(self):
        samples = [100, -100, 200, -200]
        pcm = av.samples_to_pcm16(samples)
        self.assertAlmostEqual(av.pcm_rms(pcm), av.samples_rms(samples))


class TestFindOnset(unittest.TestCase):
    def test_finds_speech_start(self):
        samples = silence(1000, 300) + tone(500)
        start = av.find_onset(samples, threshold=3000)
        # 起点=语音开始处 - back(120ms) + 已判定窗口补偿
        self.assertLessEqual(start, int(RATE * 1.0))
        self.assertGreater(start, int(RATE * 0.8))

    def test_leading_silence_trimmed(self):
        samples = silence(1500, 300) + tone(800)
        trimmed = av.trim_leading_silence(samples, threshold=3000)
        self.assertLess(len(trimmed), len(samples))
        self.assertGreater(len(trimmed), int(RATE * 0.7))

    def test_all_silence_returns_original(self):
        samples = silence(1000, 100)
        self.assertEqual(av.find_onset(samples), 0)
        self.assertEqual(len(av.trim_leading_silence(samples)), len(samples))

    def test_speech_at_start_not_trimmed(self):
        samples = tone(600)
        self.assertEqual(av.find_onset(samples, threshold=3000), 0)
        self.assertEqual(av.trim_leading_silence(samples), samples)

    def test_back_keeps_weak_onset(self):
        """弱起辅音不能被削掉：起点要落在语音之前若干毫秒。"""
        samples = silence(800, 200) + tone(400)
        start = av.find_onset(samples, threshold=3000, back_sec=0.12)
        self.assertLess(start, int(RATE * 0.8))

    def test_empty_input(self):
        self.assertEqual(av.find_onset([]), 0)
        self.assertEqual(av.trim_leading_silence([]), [])

    def test_trim_pcm_keeps_alignment(self):
        samples = silence(600, 200) + tone(400)
        pcm = av.samples_to_pcm16(samples)
        out = av.trim_pcm(pcm)
        self.assertEqual(len(out) % 2, 0)
        self.assertLess(len(out), len(pcm))


class TestOnsetGate(unittest.TestCase):
    def _push_all(self, gate, samples, chunk=56):
        out = bytearray()
        for i in range(0, len(samples), chunk):
            out.extend(gate.push(av.samples_to_pcm16(samples[i:i + chunk])))
        return out

    def test_drops_leading_silence(self):
        samples = silence(1200, 300) + tone(600)
        gate = av.OnsetGate(threshold=3000)
        out = self._push_all(gate, samples)
        self.assertTrue(gate.opened)
        self.assertLess(len(av.pcm16_to_samples(out)), len(samples))
        # 起点回退 120ms，所以保留长度应接近 语音 600ms + 120ms 的量级
        self.assertGreater(len(av.pcm16_to_samples(out)), int(RATE * 0.5))
        self.assertGreater(gate.dropped_sec, 0.8)

    def test_first_syllable_not_lost(self):
        """门控开启时返回的数据必须包含语音起点之前的回退窗口。"""
        samples = silence(1000, 300) + tone(400)
        gate = av.OnsetGate(threshold=3000)
        out = self._push_all(gate, samples)
        kept = av.pcm16_to_samples(out)
        # 保留段开头应是静音（回退区），随后才是方波
        self.assertTrue(any(abs(v) < 1000 for v in kept[:200]))
        self.assertTrue(any(abs(v) > 3000 for v in kept))

    def test_passthrough_after_open(self):
        gate = av.OnsetGate(threshold=3000)
        gate.push(av.samples_to_pcm16(tone(300)))
        self.assertTrue(gate.opened)
        chunk = av.samples_to_pcm16([1, 2, 3])
        self.assertEqual(gate.push(chunk), chunk)

    def test_max_wait_releases_everything(self):
        """一直没检测到起点（说话太小声）时，等满 max_wait 全部放行。"""
        gate = av.OnsetGate(threshold=3000, max_wait_sec=0.5)
        quiet = silence(700, 100)
        out = self._push_all(gate, quiet)
        self.assertTrue(gate.opened)
        self.assertEqual(len(av.pcm16_to_samples(out)), len(quiet))

    def test_reset(self):
        gate = av.OnsetGate(threshold=3000)
        gate.push(av.samples_to_pcm16(tone(300)))
        self.assertTrue(gate.opened)
        gate.reset()
        self.assertFalse(gate.opened)
        self.assertEqual(gate.push(b""), b"")
        # reset 后重新门控：静音仍被拦
        gate.push(av.samples_to_pcm16(silence(100, 200)))
        self.assertFalse(gate.opened)

    def test_empty_push(self):
        gate = av.OnsetGate(threshold=3000)
        self.assertEqual(gate.push(b""), b"")
        self.assertFalse(gate.opened)

    def test_dropped_sec_zero_before_open(self):
        gate = av.OnsetGate(threshold=3000)
        gate.push(av.samples_to_pcm16(silence(100, 100)))
        self.assertEqual(gate.dropped_sec, 0.0)

    def test_flush_returns_buffered_audio(self):
        """收尾必须能把还没放行的缓冲取出来，否则小声说话等于没输入。"""
        gate = av.OnsetGate(threshold=3000)
        quiet = silence(300, 150)          # 低于阈值，门控一直不开
        pcm = av.samples_to_pcm16(quiet)
        self.assertEqual(gate.push(pcm), b"")
        self.assertFalse(gate.opened)
        rest = gate.flush()
        self.assertEqual(rest, pcm)
        self.assertTrue(gate.opened)

    def test_flush_is_idempotent(self):
        gate = av.OnsetGate(threshold=3000)
        gate.push(av.samples_to_pcm16(silence(200, 150)))
        self.assertTrue(gate.flush())
        self.assertEqual(gate.flush(), b"")

    def test_flush_after_open_returns_nothing(self):
        gate = av.OnsetGate(threshold=3000)
        gate.push(av.samples_to_pcm16(tone(300)))
        self.assertTrue(gate.opened)
        self.assertEqual(gate.flush(), b"")

    def test_quiet_utterance_survives_flush(self):
        """整段都很轻：门控不开，但 flush 后数据完整，识别才不会空。"""
        gate = av.OnsetGate(threshold=3000)
        quiet = silence(400, 200)
        got = bytearray()
        for i in range(0, len(quiet), 56):
            got.extend(gate.push(av.samples_to_pcm16(quiet[i:i + 56])))
        got.extend(gate.flush())
        self.assertEqual(len(av.pcm16_to_samples(got)), len(quiet))


class TestOnsetWithRealFrames(unittest.TestCase):
    """用设备真实帧验证：底噪段应被裁掉，且保留有效语音。"""

    FRAMES = [
        "1bc0ac49be8090081ca0a3e3c13348e05ac30a74811d0bda2bf709c065235e4a9a",
        "1bc91230be3d1918283423716a905da06bd9197e4019c1c792d5cc10cc23c2cce3",
        "1b07172cbe3615381a08e3e6e4a161a94a63104da72d32d9c365090bee916b4468",
        "1b09ec2abe1210b1adecc2c35c3a41f8db6e525dd13133dacee288a14fa882d3f0",
    ]

    def test_real_frames_decode_unchanged(self):
        """门控是新增能力，不能改动解码结果（回归保护）。"""
        frames = [bytes.fromhex(h) for h in self.FRAMES]
        out = av.decode_frames_local(frames)
        self.assertEqual(len(out), 4 * av.SAMPLES_PER_FRAME)
        self.assertEqual(out[:12], [-7, -8, -7, -7, -10, -9, -8, -8, -8, -8, -8, -8])

    def test_gate_on_real_silence_like_audio(self):
        """4 帧真实底噪不该被判成语音起点（自适应阈值下同样成立）。"""
        frames = [bytes.fromhex(h) for h in self.FRAMES]
        samples = av.decode_frames_local(frames)
        self.assertEqual(av.find_onset(samples), 0)
        gate = av.OnsetGate()          # 自适应模式
        for i in range(0, len(samples), 56):
            gate.push(av.samples_to_pcm16(samples[i:i + 56]))
        self.assertFalse(gate.opened)


class TestAutoThreshold(unittest.TestCase):
    """自适应阈值：底噪取已见窗口的最小能量 × 倍数。"""

    def test_empty_uses_min_threshold(self):
        self.assertEqual(av.auto_threshold([]), av.ONSET_MIN_THRESHOLD)

    def test_floor_times_factor(self):
        # 底噪 300 × 倍数（3.5）明显高于绝对下限，阈值应取倍数结果
        self.assertAlmostEqual(av.auto_threshold([300, 5000, 8000]),
                               300 * av.ONSET_FLOOR_FACTOR)

    def test_min_threshold_floor(self):
        # 底噪极低（7）时用绝对下限，否则门控形同虚设
        self.assertEqual(av.auto_threshold([7, 5000]), av.ONSET_MIN_THRESHOLD)

    def test_uses_min_not_percentile(self):
        """整段都是语音（没有静音）时，最小值取到谷底，阈值才可能被越过。"""
        windows = [8000, 2000, 8000, 2000]       # 音节起伏
        th = av.auto_threshold(windows)
        self.assertEqual(th, 2000 * av.ONSET_FLOOR_FACTOR)
        self.assertGreater(max(windows), th)

    def test_gate_opens_on_speech_with_dips(self):
        """有起伏的真实感语音：自适应也能打开门控。"""
        samples = silence(600, 300) + tone(600)
        gate = av.OnsetGate()
        for i in range(0, len(samples), 56):
            gate.push(av.samples_to_pcm16(samples[i:i + 56]))
        self.assertTrue(gate.opened)
        self.assertGreater(gate.dropped_sec, 0.3)

    def test_gate_stays_closed_on_pure_silence(self):
        gate = av.OnsetGate()
        samples = silence(1200, 300)
        for i in range(0, len(samples), 56):
            gate.push(av.samples_to_pcm16(samples[i:i + 56]))
        self.assertFalse(gate.opened)

    def test_quiet_recording_still_released(self):
        """底噪很低（数字静音）时不至于让门控把整段吞掉。"""
        gate = av.OnsetGate(max_wait_sec=0.5)
        samples = silence(800, 5)
        kept = 0
        for i in range(0, len(samples), 56):
            kept += len(gate.push(av.samples_to_pcm16(samples[i:i + 56])))
        kept += len(gate.flush())
        self.assertEqual(kept // 2, len(samples))


class TestOnsetConfig(unittest.TestCase):
    """设置项 → 门控参数的翻译（onset_gate / onset_factor）。"""

    def test_default_is_adaptive(self):
        self.assertEqual(vp.onset_kwargs({}),
                         {"floor_factor": av.ONSET_FLOOR_FACTOR})

    def test_disabled_returns_none(self):
        self.assertIsNone(vp.onset_kwargs({"onset_gate": 0}))

    def test_factor_is_scaled_by_ten(self):
        self.assertEqual(vp.onset_kwargs({"onset_factor": 45}),
                         {"floor_factor": 4.5})

    def test_factor_clamped(self):
        self.assertEqual(
            vp.onset_kwargs({"onset_factor": 1})["floor_factor"], 1.0)
        self.assertEqual(
            vp.onset_kwargs({"onset_factor": 999})["floor_factor"], 10.0)

    def test_bad_value_falls_back(self):
        self.assertEqual(
            vp.onset_kwargs({"onset_factor": "x"})["floor_factor"],
            av.ONSET_FLOOR_FACTOR)

    def test_kwargs_feed_gate(self):
        """设置翻译出来的参数能被 OnsetGate 直接接受。"""
        gate = av.OnsetGate(**vp.onset_kwargs({"onset_factor": 40}))
        self.assertAlmostEqual(gate.floor_factor, 4.0)


if __name__ == "__main__":
    unittest.main()
