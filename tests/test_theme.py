# -*- coding: utf-8 -*-
"""主题配色映射的纯数据测试（不创建 Tk 窗口）。"""
import unittest

import theme


class TestThemeMaps(unittest.TestCase):
    def test_panel_core_colors(self):
        self.assertEqual(theme.PANEL_LIGHT["#0f1115"], "#f4f5fa")
        self.assertEqual(theme.PANEL_LIGHT["#171a21"], "#ffffff")
        self.assertEqual(theme.PANEL_LIGHT["#f5f7fa"], "#1f2333")
        self.assertIn("#0f1115", theme.PANEL_DARK.values())

    def test_tool_core_colors(self):
        self.assertEqual(theme.TOOL_DARK["#f4f5fa"], "#0f1115")
        self.assertEqual(theme.TOOL_DARK["#ffffff"], "#171a21")
        self.assertEqual(theme.TOOL_DARK["#1f2333"], "#f5f7fa")
        self.assertIn("#f4f5fa", theme.TOOL_LIGHT.values())

    def test_maps_cover_real_palette(self):
        # 主题切换依赖这些主色；缺少它们会导致局部还是白底/深字。
        for color in ("#0f1115", "#171a21", "#252b37", "#f5f7fa",
                      "#a3aab8", "#5ddc8a", "#ff6b6b"):
            self.assertIn(color, theme.PANEL_LIGHT)
        for color in ("#f4f5fa", "#ffffff", "#1f2333", "#e4e7f1",
                      "#635bff", "#f59e0b"):
            self.assertIn(color, theme.TOOL_DARK)

    def test_inverse_is_nonempty(self):
        self.assertTrue(theme.PANEL_DARK)
        self.assertTrue(theme.TOOL_LIGHT)
        self.assertTrue(all(k.startswith("#") or k.isalpha()
                            for k in theme.PANEL_DARK))


if __name__ == "__main__":
    unittest.main()
