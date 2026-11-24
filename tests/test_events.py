# -*- coding: utf-8 -*-
"""Raw Input 事件解析的单元测试（不注册真实设备）。"""
import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mouse_events as me  # noqa: E402


def mouse_input(dx=0, dy=0, button_flags=0, button_data=0):
    ri = me.RAWINPUT()
    ri.header.dwType = me.RIM_TYPEMOUSE
    ri.data.mouse.usFlags = 0
    ri.data.mouse.lLastX = dx
    ri.data.mouse.lLastY = dy
    ri.data.mouse.u.bt.usButtonFlags = button_flags
    ri.data.mouse.u.bt.usButtonData = button_data
    return ri


def keyboard_input(vkey, message=0x0100, scan=0x1E):
    ri = me.RAWINPUT()
    ri.header.dwType = me.RIM_TYPEKEYBOARD
    ri.data.keyboard.VKey = vkey
    ri.data.keyboard.Message = message
    ri.data.keyboard.MakeCode = scan
    return ri


class MouseEventTest(unittest.TestCase):
    def setUp(self):
        self.mon = me.Monitor(accept_all=True)

    def test_move_accumulates(self):
        self.mon.on_mouse(mouse_input(3, -4))
        self.mon.on_mouse(mouse_input(2, 1))
        self.assertEqual(self.mon.move_dx, 5)
        self.assertEqual(self.mon.move_dy, -3)
        self.assertEqual(self.mon.move_reports, 2)

    def test_left_click_prints(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mon.on_mouse(mouse_input(button_flags=0x0001))
            self.mon.on_mouse(mouse_input(button_flags=0x0002))
        out = buf.getvalue()
        self.assertIn("left", out)
        self.assertIn("down", out)
        self.assertIn("up", out)

    def test_side_button(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mon.on_mouse(mouse_input(button_flags=0x0040))
        self.assertIn("side1", buf.getvalue())

    def test_wheel(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mon.on_mouse(mouse_input(button_flags=me.WHEEL, button_data=120))
            self.mon.on_mouse(mouse_input(button_flags=me.WHEEL,
                                          button_data=(0xFFFF - 119)))
        out = buf.getvalue()
        self.assertIn("up", out)
        self.assertIn("down", out)

    def test_keyboard_volume_key(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.mon.on_keyboard(keyboard_input(0xAD))
        self.assertIn("VolumeMute", buf.getvalue())
        self.assertIn("down", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
