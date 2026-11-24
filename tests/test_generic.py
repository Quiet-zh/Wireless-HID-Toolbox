# -*- coding: utf-8 -*-
"""generic_protocols 的纯协议单元测试（不访问硬件）。"""
import unittest

import generic_protocols as gp
from hid_win import HidInterface


def iface(vid=0x373B, pid=0x1278, usage_page=0xFF02, usage=0x0002,
          input_len=17, output_len=17, feature_len=0, path="mi_00"):
    return HidInterface(path=path, vid=vid, pid=pid, version=0,
                        usage_page=usage_page, usage=usage,
                        input_len=input_len, output_len=output_len,
                        feature_len=feature_len, product="Test",
                        manufacturer="", serial="")


class TestAtk(unittest.TestCase):
    def test_atk1_request(self):
        req = gp.atk1_request()
        self.assertEqual(req[0], 0x08)
        self.assertEqual(req[1], 0x04)
        self.assertEqual(req[16], 0x49)
        self.assertEqual(len(req), 17)

    def test_atk1_valid(self):
        rep = bytearray(17)
        rep[0], rep[1], rep[5], rep[6] = 0x08, 0x04, 0x02, 90
        rep[16] = (0x55 - sum(rep[:16])) & 0xFF
        self.assertTrue(gp.atk1_valid(bytes(rep)))
        rep[6] = 91
        self.assertFalse(gp.atk1_valid(bytes(rep)))

    def test_atk2(self):
        rep = bytearray(64)
        rep[0], rep[1], rep[5], rep[7] = 0x08, 0x72, 0x07, 55
        self.assertTrue(gp.atk2_valid(bytes(rep)))
        self.assertEqual(gp.atk2_request()[1:8],
                         bytes([0x7D, 0x72, 0x02, 0x00, 0x01, 0x07, 0x01]))


class TestMchose(unittest.TestCase):
    def test_a5(self):
        req = gp.mchose_a5_request(65)
        self.assertEqual((req[3], req[4], req[6]), (0x02, 0x02, 0x83))
        rep = bytearray(65)
        rep[7], rep[8] = 1, 75
        self.assertEqual(gp.parse_mchose_a5(bytes(rep)), (75, 1))

    def test_a7(self):
        req = gp.mchose_a7_request()
        self.assertEqual(req[0], 0x11)
        self.assertEqual(req[1], 0x06 ^ 0xFF)
        plain = bytearray(64)
        plain[11], plain[12] = 66, 0
        rep = bytes(b ^ 0xFF for b in plain)
        self.assertEqual(gp.parse_mchose_a7(rep), (66, 0))

    def test_gmouse(self):
        req = gp.gmouse_request()
        self.assertEqual(req[1:9], bytes([0x55, 0x30, 0xA5, 0x0B,
                                          0x2E, 0x01, 0x01, 0x01]))
        rep = bytes([0xAA, 0x30]) + bytes(6) + bytes([80, 1]) + bytes(10)
        self.assertEqual(gp.parse_gmouse(rep), (80, True))

    def test_z75s(self):
        req = gp.z75s_request()
        self.assertEqual(len(req), 20)
        self.assertEqual(req[-1], sum(req[:-1]) & 0xFF)
        rep = bytearray(20)
        rep[5] = 61
        self.assertEqual(gp.parse_z75s(bytes(rep)), 61)


class TestJl(unittest.TestCase):
    def test_frame_roundtrip(self):
        frame = gp.build_jl_frame(3, b"\x01\x01\x46", 0, 65)
        parsed = gp.parse_jl_frame(frame)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["crc_ok"])
        self.assertEqual(gp.jl_tlvs(parsed["payload"]),
                         [(0x01, b"\x46")])

    def test_bad_crc(self):
        frame = bytearray(gp.build_jl_frame(0, b"\x01\x01\x46", 0, 65))
        frame[12] ^= 0xFF
        parsed = gp.parse_jl_frame(bytes(frame))
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["crc_ok"])


class TestZowie(unittest.TestCase):
    def test_curve(self):
        self.assertEqual(gp.zowie_percent(3500), 0)
        self.assertEqual(gp.zowie_percent(3890), 50)
        self.assertEqual(gp.zowie_percent(4200), 100)
        self.assertEqual(gp.zowie_percent(9999), 100)


class TestMatching(unittest.TestCase):
    def test_atk_does_not_match_eweadn(self):
        group = [iface(vid=0x3554, pid=0xF517)]
        self.assertFalse(any(s.kind == "atk1" and s.matches(group)
                             for s in gp.SPECS))
        self.assertTrue(any(s.kind == "eweadn" and s.matches(group)
                            for s in gp.SPECS))

    def test_atk_matches(self):
        group = [iface()]
        self.assertTrue(any(s.kind == "atk1" and s.matches(group)
                            for s in gp.SPECS))


if __name__ == "__main__":
    unittest.main()
