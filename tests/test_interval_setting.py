# -*- coding: utf-8 -*-
"""刷新间隔可输入设置：秒数解析、范围限制、分钟显示转换。"""
import unittest

import battery_panel as bp


class TestParseInterval(unittest.TestCase):
    def test_plain_number_is_seconds(self):
        for text, expected in (("1", 1), ("10", 10), ("45", 45),
                               ("60", 60), ("90", 90), ("120", 120),
                               ("3600", 3600), ("  75  ", 75)):
            self.assertEqual(bp.parse_interval(text), expected, text)

    def test_minute_text(self):
        for text, expected in (("2 分钟", 120), ("1.5 分钟", 90),
                               ("5分", 300), ("1m", 60), ("10 秒", 10),
                               ("30s", 30), ("60秒", 60)):
            self.assertEqual(bp.parse_interval(text), expected, text)

    def test_preset_labels(self):
        for label, seconds in bp.INTERVALS.items():
            self.assertEqual(bp.parse_interval(label), seconds, label)

    def test_new_10_seconds_preset(self):
        self.assertIn("10 秒", bp.INTERVALS)
        self.assertEqual(bp.INTERVALS["10 秒"], 10)

    def test_out_of_range_rejected(self):
        for text in ("0", "-5", "3601", "7200", "1 小时", "abc", "", None):
            self.assertIsNone(bp.parse_interval(text), text)

    def test_decimal_seconds_rounds(self):
        self.assertEqual(bp.parse_interval("1.4"), 1)
        self.assertEqual(bp.parse_interval("1.6"), 2)


class TestIntervalLabel(unittest.TestCase):
    def test_presets_keep_original_label(self):
        for label, seconds in bp.INTERVALS.items():
            self.assertEqual(bp.interval_label(seconds), label, seconds)

    def test_custom_seconds(self):
        self.assertEqual(bp.interval_label(1), "1 秒")
        self.assertEqual(bp.interval_label(45), "45 秒")
        self.assertEqual(bp.interval_label(60), "60 秒")

    def test_over_60_becomes_minutes(self):
        self.assertEqual(bp.interval_label(90), "1.5 分钟")
        self.assertEqual(bp.interval_label(120), "2 分钟")
        self.assertEqual(bp.interval_label(300), "5 分钟")
        self.assertEqual(bp.interval_label(3600), "60 分钟")
        self.assertEqual(bp.interval_label(61), "1.02 分钟")
        self.assertEqual(bp.interval_label(75), "1.25 分钟")

    def test_clamped(self):
        self.assertEqual(bp.interval_label(0), "1 秒")
        self.assertEqual(bp.interval_label(99999), "60 分钟")


class TestIntervalChanged(unittest.TestCase):
    def test_input_number_persists_seconds(self):
        import copy
        import tempfile
        from unittest import mock
        cfg = {"interval": 60}
        fake_parent = mock.Mock()
        dlg = bp.SettingsWindow.__new__(bp.SettingsWindow)
        dlg.parent = fake_parent
        dlg.interval_var = mock.Mock()
        dlg.interval_var.get.return_value = "90"
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(cfg)), \
                mock.patch.object(bp.tc, "save_config",
                                  side_effect=lambda v: cfg.update(v)), \
                mock.patch.object(bp.tc, "post_to_tray"), \
                mock.patch.object(bp.messagebox, "showinfo") as info:
            dlg._interval_changed()
        self.assertEqual(cfg["interval"], 90)
        dlg.interval_var.set.assert_called_once_with("1.5 分钟")
        info.assert_not_called()
        fake_parent._schedule_next.assert_called_once()

    def test_invalid_input_restores_and_hints(self):
        import copy
        from unittest import mock
        cfg = {"interval": 60}
        dlg = bp.SettingsWindow.__new__(bp.SettingsWindow)
        dlg.parent = None
        dlg.interval_var = mock.Mock()
        dlg.interval_var.get.return_value = "abc"
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(cfg)), \
                mock.patch.object(bp.messagebox, "showinfo") as info:
            dlg._interval_changed()
        dlg.interval_var.set.assert_called_once_with("60 秒")
        info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
