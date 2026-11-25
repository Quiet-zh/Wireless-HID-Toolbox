# -*- coding: utf-8 -*-
"""aimouse_voice 的纯数据单元测试（不访问硬件）。"""
import struct
import unittest

import aimouse_voice as av


def audio_frame(data_byte=0x00, pred=0, index=0, fid=0x1B, fill=0xBE):
    """构造一条合法音频帧：0x1B + int16 pred + index + 0xBE + 28B 数据。"""
    head = bytes([fid]) + struct.pack('<h', pred) + bytes([index, fill])
    return head + bytes([data_byte]) * 28


class TestFrameDetect(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(av.is_audio_frame(audio_frame()))

    def test_wrong_id(self):
        self.assertFalse(av.is_audio_frame(audio_frame(fid=0x0C)))

    def test_short(self):
        self.assertFalse(av.is_audio_frame(b'\x1b\x00'))


class TestDecode(unittest.TestCase):
    def test_frame_length(self):
        self.assertEqual(len(av.decode_frame(audio_frame())), 56)

    def test_silence(self):
        # pred=0、数据全 0 → 输出全 0
        self.assertEqual(av.decode_frame(audio_frame(0x00)), [0] * 56)

    def test_ramp(self):
        # nibble=1 时 diff=step>>2=1，且 index 保持在 0 → 每步 +1
        self.assertEqual(av.decode_frame(audio_frame(0x11)),
                         list(range(1, 57)))

    def test_negative_nibble(self):
        # nibble=8 是符号位，pred=0 时得到 -0，序列不增长
        self.assertEqual(set(av.decode_frame(audio_frame(0x88))), {0})

    def test_invalid(self):
        self.assertEqual(av.decode_frame(b'\x0c\x4d'), [])


class TestSegments(unittest.TestCase):
    def test_decode_frames_concat(self):
        self.assertEqual(len(av.decode_frames([audio_frame()] * 3)), 168)

    def test_split_by_gap(self):
        mixed = ([audio_frame()] * 5 + [b'\x00' * 33] * 20
                 + [audio_frame()] * 5)
        segs = av.split_segments(mixed, gap_frames=12)
        self.assertEqual([len(s) for s in segs], [5, 5])

    def test_no_false_split(self):
        segs = av.split_segments([audio_frame()] * 4, gap_frames=12)
        self.assertEqual(len(segs), 1)


class TestOutput(unittest.TestCase):
    def test_pcm16_little_endian(self):
        self.assertEqual(av.samples_to_pcm16([1, -1]), b'\x01\x00\xff\xff')

    def test_wav_header(self):
        pcm = b'\x00\x00' * 4
        wav = av.pcm16_to_wav(pcm)
        self.assertEqual(len(wav), 44 + len(pcm))
        self.assertEqual(wav[:4], b'RIFF')
        self.assertEqual(wav[8:12], b'WAVE')
        self.assertEqual(struct.unpack('<I', wav[40:44])[0], len(pcm))

    def test_normalize_peak(self):
        out = av.normalize([100, -200, 50])
        self.assertEqual(max(abs(x) for x in out), 26000)

    def test_highpass_removes_dc(self):
        out = av.highpass([1000] * 200, cutoff=150)
        self.assertLess(abs(out[-1]), 10)

    def test_empty_inputs(self):
        self.assertEqual(av.highpass([]), [])
        self.assertEqual(av.normalize([]), [])


if __name__ == '__main__':
    unittest.main()
