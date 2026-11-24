# -*- coding: utf-8 -*-
"""版本号与打包脚本的一致性测试。"""
import re
import unittest
from pathlib import Path

import version

ROOT = Path(__file__).resolve().parent.parent


class TestVersionPackaging(unittest.TestCase):
    def test_version_is_semver(self):
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(tuple(int(x) for x in version.__version__.split(".")),
                         version.VERSION_TUPLE[:3])

    def test_version_info_matches(self):
        text = (ROOT / "version_info.txt").read_text(encoding="utf-8-sig")
        parts = version.__version__.split(".")
        expected = f"filevers=({parts[0]}, {parts[1]}, {parts[2]}, 0)"
        self.assertIn(expected, text)
        self.assertIn(f"FileVersion', '{version.__version__}.0'", text)

    def test_build_script_modes(self):
        text = (ROOT / "build_exe.bat").read_text(encoding="utf-8-sig")
        self.assertIn('set "MODE=onefile"', text)
        self.assertIn("--%MODE%", text)
        self.assertIn("onefile", text)
        self.assertIn("onedir", text)


if __name__ == "__main__":
    unittest.main()
