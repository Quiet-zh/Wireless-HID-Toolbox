# -*- coding: utf-8 -*-
"""tests/test_monitor_on_close.py —— 关闭语音窗口后是否继续监测。

默认（`monitor_on_close=0`）关窗即停止监测，与旧行为一致；
设 1 时关窗只把窗口隐藏（withdraw），录音线程与事件轮询继续跑，
再点主界面 🎤 用 deiconify 召回。
"""
import unittest
from unittest import mock

import aimouse_voice_panel as vp


def _window(monitor_on_close=0, recording=True):
    win = vp.VoiceWindow.__new__(vp.VoiceWindow)
    win.cfg = {"monitor_on_close": monitor_on_close}
    win.recorder = mock.Mock() if recording else None
    win._on_close_cb = None
    win._on_hidden_cb = None
    return win


class TestParamDefinition(unittest.TestCase):
    def test_param_exists_with_default_off(self):
        item = next((p for p in vp.PARAM_DEFS if p[0] == "monitor_on_close"),
                    None)
        self.assertIsNotNone(item)
        self.assertEqual(item[3], 0)          # 默认 0：关闭即停止

    def test_param_is_bool_and_ranged(self):
        item = next(p for p in vp.PARAM_DEFS if p[0] == "monitor_on_close")
        self.assertEqual(item[7], "bool")
        self.assertEqual((item[4], item[5]), (0, 1))


class TestKeepMonitoringDecision(unittest.TestCase):
    def test_off_never_keeps(self):
        win = _window(0, recording=True)
        self.assertFalse(win._keep_monitoring_on_close())

    def test_on_and_recording_keeps(self):
        win = _window(1, recording=True)
        self.assertTrue(win._keep_monitoring_on_close())

    def test_on_but_not_recording_does_not_keep(self):
        """没在监测时关窗就该正常退出，不留看不见的隐藏窗口。"""
        win = _window(1, recording=False)
        self.assertFalse(win._keep_monitoring_on_close())

    def test_missing_key_defaults_to_off(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {}
        win.recorder = mock.Mock()
        self.assertFalse(win._keep_monitoring_on_close())


class TestCloseBehaviour(unittest.TestCase):
    def test_close_withdraws_when_keeping(self):
        win = _window(1, recording=True)
        win.withdraw = mock.Mock()
        win.shutdown = mock.Mock()
        hidden = mock.Mock()
        win._on_hidden_cb = hidden
        win._close()
        win.withdraw.assert_called_once()
        win.shutdown.assert_not_called()
        hidden.assert_called_once()             # 通知主界面提示「仍在监测」
        # 录音线程不能停
        win.recorder.stop.assert_not_called()

    def test_hidden_callback_error_is_swallowed(self):
        """提示回调出错不能影响隐藏与继续监测。"""
        win = _window(1, recording=True)
        win.withdraw = mock.Mock()
        win.shutdown = mock.Mock()
        win._on_hidden_cb = mock.Mock(side_effect=RuntimeError("boom"))
        win._close()
        win.withdraw.assert_called_once()
        win.shutdown.assert_not_called()

    def test_close_shuts_down_when_off(self):
        win = _window(0, recording=True)
        win.withdraw = mock.Mock()
        win.shutdown = mock.Mock()
        win._close()
        win.shutdown.assert_called_once()
        win.withdraw.assert_not_called()

    def test_close_shuts_down_when_not_recording(self):
        win = _window(1, recording=False)
        win.withdraw = mock.Mock()
        win.shutdown = mock.Mock()
        win._close()
        win.shutdown.assert_called_once()


class TestShutdown(unittest.TestCase):
    def test_shutdown_stops_everything(self):
        win = _window(1, recording=True)
        cb = mock.Mock()
        win._on_close_cb = cb
        win._stop_monitor = mock.Mock()
        win._stop_play = mock.Mock()
        win.destroy = mock.Mock()
        with mock.patch.object(vp.theme, "apply_new", side_effect=RuntimeError):
            win.shutdown()          # 主题异常也不能阻断关闭
        win._stop_monitor.assert_called_once()
        win._stop_play.assert_called_once()
        cb.assert_called_once()
        win.destroy.assert_called_once()


class TestMapRefresh(unittest.TestCase):
    def test_refresh_on_show(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win._refresh_list = mock.Mock()
        win._refresh_mode = mock.Mock()
        win._on_map(mock.Mock(widget=win))
        win._refresh_list.assert_called_once()
        win._refresh_mode.assert_called_once()

    def test_ignores_child_widget_map(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win._refresh_list = mock.Mock()
        win._refresh_mode = mock.Mock()
        win._on_map(mock.Mock(widget=object()))   # 子控件的 Map 不算
        win._refresh_list.assert_not_called()

    def test_tolerates_destroyed_window(self):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win._refresh_list = mock.Mock(side_effect=vp.tk.TclError("gone"))
        win._refresh_mode = mock.Mock()
        win._on_map(None)                 # 不该抛出去
        win._refresh_mode.assert_not_called()


class TestPanelDestroyStopsRecorder(unittest.TestCase):
    """主面板销毁时会连带销毁隐藏的语音窗口，录音线程要先停掉。"""

    def test_destroy_stops_voice_recorder(self):
        import battery_panel as bp
        panel = bp.BatteryPanel.__new__(bp.BatteryPanel)
        rec = mock.Mock()
        panel._voice_win = mock.Mock(recorder=rec)
        with mock.patch.object(bp.tk.Tk, "destroy") as tk_destroy:
            panel.destroy()
        rec.stop.assert_called_once()
        tk_destroy.assert_called_once()

    def test_destroy_without_voice_window(self):
        import battery_panel as bp
        panel = bp.BatteryPanel.__new__(bp.BatteryPanel)
        panel._voice_win = None
        with mock.patch.object(bp.tk.Tk, "destroy") as tk_destroy:
            panel.destroy()
        tk_destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
