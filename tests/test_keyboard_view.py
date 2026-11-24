# -*- coding: utf-8 -*-
"""键盘全配列布局的纯数据测试。"""
import unittest

import keyboard_view as kv


class KeyboardLayoutTest(unittest.TestCase):
    def test_key_count(self):
        self.assertEqual(len(kv.KEYS), 104)

    def test_bounds(self):
        for label, vk, x, y, w, h in kv.KEYS:
            self.assertLessEqual(x + w, 23.5, label)
            self.assertLessEqual(y + h, 6.0, label)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)

    def test_core_keys(self):
        labels = {k[0] for k in kv.KEYS}
        vks = {k[1] for k in kv.KEYS}
        for label in ("Esc", "F12", "Space", "Enter", "Num", "PgUp", "Right"):
            self.assertIn(label, labels)
        for vk in (0x1B, 0x41, 0x5A, 0x20, 0x0D, 0x90, 0x60):
            self.assertIn(vk, vks)


if __name__ == "__main__":
    unittest.main()
