# -*- coding: utf-8 -*-
"""Vosk/Kaldi 日志静音的回归测试。"""
import unittest
from unittest import mock

import aimouse_voice_panel as vp
import voice_service as vs


class TestQuietVosk(unittest.TestCase):
    def setUp(self):
        vs._VOSK_QUIET = False

    def tearDown(self):
        vs._VOSK_QUIET = False

    def test_sets_log_level_once(self):
        fake = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"vosk": fake}):
            vp._quiet_vosk()
            vp._quiet_vosk()
        fake.SetLogLevel.assert_called_once_with(-1)
        self.assertTrue(vs._VOSK_QUIET)

    def test_missing_api_is_ignored(self):
        fake = mock.Mock(spec=[])       # 没有 SetLogLevel
        with mock.patch.dict("sys.modules", {"vosk": fake}):
            vp._quiet_vosk()            # 不应抛异常
        self.assertFalse(vs._VOSK_QUIET)

    def test_available_triggers_quiet(self):
        fake = mock.MagicMock()
        with mock.patch.dict("sys.modules", {"vosk": fake}), \
                mock.patch.object(vs.os.path, "isdir", return_value=True):
            engine = vp.AsrEngine("some_dir")
            self.assertTrue(engine.available())
        fake.SetLogLevel.assert_called_once_with(-1)


if __name__ == "__main__":
    unittest.main()
