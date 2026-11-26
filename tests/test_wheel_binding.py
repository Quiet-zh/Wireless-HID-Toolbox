# -*- coding: utf-8 -*-
"""设置对话框滚轮绑定回归：不得使用 bind_all 造成销毁后 TclError 刷屏。"""
import unittest

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None

import aimouse_voice_panel as vp  # noqa: E402


@unittest.skipIf(tk is None, "当前 Python 无 tkinter")
class TestSettingsWheelBinding(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.geometry("980x660")
        self.dlg = None

    def tearDown(self):
        if self.dlg is not None:
            try:
                self.dlg.destroy()
            except tk.TclError:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _dialog(self):
        self.dlg = vp.VoiceSettingsDialog(
            self.root, vp.load_config(), lambda _cfg: None)
        self.root.update()
        return self.dlg

    def test_dialog_does_not_add_global_binding(self):
        before = self.root.bind_all("<MouseWheel>")
        dlg = self._dialog()
        self.assertEqual(self.root.bind_all("<MouseWheel>"), before)
        # 绑定应落在对话框自身（toplevel），子控件事件可经 bindtags 冒泡
        self.assertNotEqual(dlg.bind("<MouseWheel>"), "")

    def test_global_binding_absent_after_destroy(self):
        dlg = self._dialog()
        dlg.destroy()
        self.dlg = None
        self.root.update()
        self.assertEqual(self.root.bind_all("<MouseWheel>"), "")

    def test_wheel_inside_dialog_does_not_raise(self):
        dlg = self._dialog()
        try:
            dlg.event_generate("<MouseWheel>", delta=-120)
            self.root.update()
        except tk.TclError as exc:
            self.fail("对话框内滚轮抛异常: %r" % (exc,))

    def test_repeated_open_close_leaves_no_global_binding(self):
        for _ in range(3):
            dlg = self._dialog()
            dlg.destroy()
            self.dlg = None
        self.root.update()
        self.assertEqual(self.root.bind_all("<MouseWheel>"), "")


if __name__ == "__main__":
    unittest.main()
