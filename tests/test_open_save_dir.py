# -*- coding: utf-8 -*-
"""「打开保存目录 / 打开设置路径」按钮的回归测试。"""
import os
import tempfile
import unittest
from unittest import mock

import aimouse_voice_panel as vp


class _FakeLabel:
    def __init__(self):
        self.values = {}

    def configure(self, **kw):
        self.values.update(kw)


class TestOpenSaveDir(unittest.TestCase):
    def _window(self, save_dir):
        win = vp.VoiceWindow.__new__(vp.VoiceWindow)
        win.cfg = {"save_dir": save_dir}
        win.status = _FakeLabel()
        return win

    def test_opens_configured_dir(self):
        d = tempfile.mkdtemp(prefix="vh_open_dir_")
        win = self._window(d)
        with mock.patch.object(vp.os, "startfile", create=True) as start:
            win._open_save_dir()
        start.assert_called_once_with(d)
        self.assertIn("已打开", win.status.values.get("text", ""))

    def test_creates_dir_if_missing(self):
        d = os.path.join(tempfile.mkdtemp(prefix="vh_open_new_"), "new")
        win = self._window(d)
        with mock.patch.object(vp.os, "startfile", create=True):
            win._open_save_dir()
        self.assertTrue(os.path.isdir(d))

    def test_error_is_reported(self):
        win = self._window(os.path.join(tempfile.gettempdir(), "vh_dir"))
        with mock.patch.object(vp.os, "startfile", create=True,
                               side_effect=OSError("boom")), \
                mock.patch.object(vp.messagebox, "showerror") as err:
            win._open_save_dir()
        err.assert_called_once()


class TestSettingsOpenPath(unittest.TestCase):
    def _dialog(self, path):
        dlg = vp.VoiceSettingsDialog.__new__(vp.VoiceSettingsDialog)
        var = mock.Mock()
        var.get.return_value = path
        dlg.vars = {"save_dir": var}
        return dlg

    def test_opens_existing_path(self):
        d = tempfile.mkdtemp(prefix="vh_cfg_open_")
        dlg = self._dialog(d)
        with mock.patch.object(vp.os, "startfile", create=True) as start:
            dlg._open_path("save_dir")
        start.assert_called_once_with(d)

    def test_missing_path_shows_hint(self):
        dlg = self._dialog(os.path.join(tempfile.gettempdir(),
                                        "vh_not_exists_xyz"))
        with mock.patch.object(vp.messagebox, "showinfo") as info:
            dlg._open_path("save_dir")
        info.assert_called_once()
        self.assertIn("目录不存在", info.call_args[0][1])

    def test_empty_path_is_noop(self):
        dlg = self._dialog("")
        with mock.patch.object(vp.os, "startfile", create=True) as start:
            dlg._open_path("save_dir")
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
