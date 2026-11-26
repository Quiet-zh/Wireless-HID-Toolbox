# -*- coding: utf-8 -*-
"""未连接设备默认不显示的回归测试（面板卡片 + 托盘图标）。"""
import copy
import unittest
from unittest import mock

import battery_panel as bp
import device_registry as dr
import tray_common as tc


def _snap(key, present, status="未连接", show=True, tray=True):
    return dr.DeviceSnapshot(key=key, name=key, vid=0, pid=0, percent=50,
                             status=status, present=present, show=show,
                             tray=tray)


class TestConfigDefault(unittest.TestCase):
    def test_default_is_hidden(self):
        self.assertFalse(tc.DEFAULT_CONFIG.get("show_offline", False))


class TestPanelFilter(unittest.TestCase):
    def _panel(self, snaps, show_offline):
        panel = bp.BatteryPanel.__new__(bp.BatteryPanel)
        panel.snapshots = snaps
        panel.cards = {}
        panel.empty_label = mock.Mock()
        panel.inner = mock.Mock()
        panel.canvas = mock.Mock()
        panel.canvas.bbox.return_value = None
        panel.inner.update_idletasks = mock.Mock()
        panel._update_scrollbar_visibility = mock.Mock()
        panel._later = mock.Mock()
        return panel

    def test_offline_hidden_by_default(self):
        panel = self._panel([
            _snap("online:1", True),
            _snap("offline:2", False),
        ], False)
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(
                                   {"show_offline": False})), \
                mock.patch.object(bp, "DeviceCard", side_effect=lambda *a, **k:
                                  mock.Mock()), \
                mock.patch.object(bp.theme, "apply_new"):
            panel._sync_cards()
        self.assertEqual(set(panel.cards), {"online:1"})

    def test_offline_shown_when_enabled(self):
        panel = self._panel([
            _snap("online:1", True),
            _snap("offline:2", False),
        ], True)
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(
                                   {"show_offline": True})), \
                mock.patch.object(bp, "DeviceCard", side_effect=lambda *a, **k:
                                  mock.Mock()), \
                mock.patch.object(bp.theme, "apply_new"):
            panel._sync_cards()
        self.assertEqual(set(panel.cards), {"online:1", "offline:2"})

    def test_startup_placeholder_still_visible(self):
        """启动缓存占位（status=读取中）不能被隐藏，避免首屏闪空。"""
        panel = self._panel([_snap("startup:1", False, status="读取中")], False)
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(
                                   {"show_offline": False})), \
                mock.patch.object(bp, "DeviceCard", side_effect=lambda *a, **k:
                                  mock.Mock()), \
                mock.patch.object(bp.theme, "apply_new"):
            panel._sync_cards()
        self.assertIn("startup:1", panel.cards)

    def test_manually_hidden_device_stays_hidden(self):
        panel = self._panel([_snap("hidden:1", True, show=False)], True)
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(
                                   {"show_offline": True})), \
                mock.patch.object(bp, "DeviceCard", side_effect=lambda *a, **k:
                                  mock.Mock()), \
                mock.patch.object(bp.theme, "apply_new"):
            panel._sync_cards()
        self.assertEqual(panel.cards, {})


class TestSettingsToggle(unittest.TestCase):
    def test_toggle_persists_and_refreshes(self):
        cfg = {"show_offline": False}
        dlg = bp.SettingsWindow.__new__(bp.SettingsWindow)
        dlg.show_offline_var = mock.Mock()
        dlg.show_offline_var.get.return_value = True
        parent = mock.Mock()
        parent.snapshots = []
        parent._apply_snaps = mock.Mock()
        dlg.parent = parent
        with mock.patch.object(bp.tc, "load_config",
                               side_effect=lambda: copy.deepcopy(cfg)), \
                mock.patch.object(bp.tc, "save_config",
                                  side_effect=lambda v: cfg.update(v)), \
                mock.patch.object(bp.tc, "post_to_tray"):
            dlg._toggle_show_offline()
        self.assertTrue(cfg["show_offline"])
        parent._apply_snaps.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
