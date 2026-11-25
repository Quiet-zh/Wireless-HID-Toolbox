# -*- coding: utf-8 -*-
"""device_registry 的纯数据单元测试。"""
import copy
import time
import unittest
from unittest.mock import patch

import device_registry as dr


class TestRegistry(unittest.TestCase):
    def test_canonical_key(self):
        self.assertEqual(dr.canonical_key("36B0:3002", 0x36B0, 0x3002),
                         "36B0:WAVE75")
        self.assertEqual(dr.canonical_key("36B0:3009", 0x36B0, 0x3009),
                         "36B0:WAVE75")
        self.assertEqual(dr.canonical_key("3554:F517", 0x3554, 0xF517),
                         "3554:F517")
        self.assertEqual(dr.canonical_key("046D:C53F", 0x046D, 0xC53F),
                         "046D:C53F")

    def test_ids(self):
        self.assertEqual(dr._ids("36B0:WAVE75"), (0x36B0, 0x3002))
        self.assertEqual(dr._ids("3554:F517"), (0x3554, 0xF517))

    def test_friendly_name(self):
        self.assertEqual(dr.friendly_name("046D:C53F", "USB Receiver"),
                         "罗技 G304 / Lightspeed")
        self.assertEqual(dr.friendly_name("3554:F517", ""), "EWEADN 8K")

    def test_kind_labels(self):
        self.assertEqual(dr.infer_kind("3554:F517", "EWEADN 8K"), "mouse")
        self.assertEqual(dr.infer_kind("36B0:WAVE75", "PMO WAVE75"),
                         "keyboard")
        self.assertEqual(dr.kind_label("mouse"), "鼠标")
        self.assertEqual(dr.kind_label("keyboard"), "键盘")

    def test_aimouse_registered(self):
        # 魔声 AI 垂直鼠标（248A:60AB）为本机 2.4G 鼠标，已登记到设备目录
        self.assertIn("248A:60AB", dr.PRIMARY)
        meta = dr.PRIMARY["248A:60AB"]
        self.assertEqual(meta["name"], "魔声 AI 垂直鼠标")
        self.assertEqual(meta["kind"], "mouse")
        self.assertEqual(dr.canonical_key("248A:60AB", 0x248A, 0x60AB),
                         "248A:60AB")
        self.assertEqual(dr._ids("248A:60AB"), (0x248A, 0x60AB))
        self.assertEqual(dr.friendly_name("248A:60AB", "AiMouse"),
                         "魔声 AI 垂直鼠标")
        self.assertEqual(dr.infer_kind("248A:60AB", "魔声 AI 垂直鼠标"),
                         "mouse")
        # 不依赖已知 key，靠“魔声/垂直”中文关键字也能判为鼠标
        self.assertEqual(dr.infer_kind("9999:8888", "魔声 AI 垂直鼠标"),
                         "mouse")

    def test_old_aimouse_name_migrates(self):
        # 已有配置里仍叫旧名字时，_ensure() 自动迁移为新名字
        cfg = {"devices": {
            "248A:60AB": {"name": "Monster AiMouse", "show": True,
                          "tray": True, "order": 25, "kind": "mouse"},
        }}

        def load():
            return copy.deepcopy(cfg)

        def save(value):
            cfg.clear()
            cfg.update(copy.deepcopy(value))

        with patch.object(dr.tc, "load_config", side_effect=load), \
                patch.object(dr.tc, "save_config", side_effect=save):
            rows = dr.known_devices()
        row = [d for d in rows if d["key"] == "248A:60AB"][0]
        self.assertEqual(row["name"], "魔声 AI 垂直鼠标")
        # 旧缓存的 source 文本也会缩短成新名字
        self.assertEqual(dr._short_source("Monster AiMouse 0xFF91（实验）"),
                         "魔声 AI 垂直鼠标")

    def test_infike_f15_registered(self):
        # 英菲克 F15 无线鼠标（1EA7:0064）为本机 2.4G 鼠标，仅登记
        self.assertIn("1EA7:0064", dr.PRIMARY)
        meta = dr.PRIMARY["1EA7:0064"]
        self.assertEqual(meta["name"], "英菲克 F15 无线鼠标")
        self.assertEqual(meta["kind"], "mouse")
        self.assertEqual(dr.canonical_key("1EA7:0064", 0x1EA7, 0x0064),
                         "1EA7:0064")
        self.assertEqual(dr._ids("1EA7:0064"), (0x1EA7, 0x0064))
        self.assertEqual(dr.friendly_name("1EA7:0064", "USB Receiver"),
                         "英菲克 F15 无线鼠标")
        self.assertEqual(dr.infer_kind("1EA7:0064", "英菲克 F15 无线鼠标"),
                         "mouse")

    def test_aulol_s99_registered(self):
        # 狼蛛 S99 三模键盘（1A2C:7FFF，产品名 2.4G Wireless Device）仅登记
        self.assertIn("1A2C:7FFF", dr.PRIMARY)
        meta = dr.PRIMARY["1A2C:7FFF"]
        self.assertEqual(meta["name"], "狼蛛 S99 三模键盘")
        self.assertEqual(meta["kind"], "keyboard")
        self.assertEqual(dr.canonical_key("1A2C:7FFF", 0x1A2C, 0x7FFF),
                         "1A2C:7FFF")
        self.assertEqual(dr._ids("1A2C:7FFF"), (0x1A2C, 0x7FFF))
        self.assertEqual(
            dr.friendly_name("1A2C:7FFF", "2.4G Wireless Device"),
            "狼蛛 S99 三模键盘")
        # 产品名不含 keyboard/键盘 关键字，必须靠 VID 前缀判定为键盘
        self.assertEqual(
            dr.infer_kind("1A2C:7FFF", "2.4G Wireless Device"), "keyboard")

    def test_kind_delete_restore_with_fake_config(self):
        cfg = {"devices": {}}

        def load():
            return copy.deepcopy(cfg)

        def save(value):
            cfg.clear()
            cfg.update(copy.deepcopy(value))

        with patch.object(dr.tc, "load_config", side_effect=load), \
                patch.object(dr.tc, "save_config", side_effect=save):
            dr.set_kind("046D:C53F", "keyboard")
            row = [d for d in dr.known_devices()
                   if d["key"] == "046D:C53F"][0]
            self.assertEqual(row["kind"], "keyboard")

            dr.delete_device("046D:C53F")
            keys = [d["key"] for d in dr.known_devices()]
            self.assertNotIn("046D:C53F", keys)

            restored = dr.restore_deleted_devices()
            self.assertEqual(restored, 1)
            row = [d for d in dr.known_devices()
                   if d["key"] == "046D:C53F"][0]
            self.assertTrue(row["show"])
            self.assertTrue(row["tray"])

    def test_snapshot_text(self):
        s = dr.DeviceSnapshot(
            key="3554:F517", name="EWEADN 8K", vid=0x3554, pid=0xF517,
            percent=85, charging=False, status="discharging",
            source="EWEADN", link="2.4G", updated=time.time(),
            present=True)
        self.assertEqual(s.charging_text, "未充电")
        self.assertIn("更新于", s.updated_text)
        self.assertEqual(s.subtitle, "3554:F517 · EWEADN")

    def test_stale_text(self):
        s = dr.DeviceSnapshot(
            key="3554:F517", name="EWEADN 8K", vid=0x3554, pid=0xF517,
            percent=84, charging=None, status="休眠", source="上次缓存",
            updated=time.time() - 60, stale=True, present=False)
        self.assertEqual(s.charging_text, "—")
        self.assertTrue(s.updated_text.startswith("缓存于"))
        self.assertEqual(s.subtitle, "3554:F517 · 上次缓存")


if __name__ == "__main__":
    unittest.main()
