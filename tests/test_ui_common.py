# -*- coding: utf-8 -*-
"""按需滚动条组件的 GUI 回归测试。"""
import unittest

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover
    tk = None
    ttk = None

from ui_common import attach_auto_scrollbar  # noqa: E402


@unittest.skipIf(tk is None, "当前 Python 无 tkinter")
class TestAutoScrollbarListbox(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("340x240")
        self.root.update()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _make(self, count):
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        lb = tk.Listbox(frame)
        lb.pack(side="left", fill="both", expand=True)
        bar = attach_auto_scrollbar(frame, lb, orient="vertical",
                                    layout="pack", side="right", fill="y")
        for i in range(count):
            lb.insert("end", "item %d" % i)
        frame.update_idletasks()
        self.root.update()
        bar.refresh()
        self.root.update()
        return lb, bar

    def test_hidden_when_content_fits(self):
        _lb, bar = self._make(3)
        self.assertFalse(bar.visible)

    def test_shown_when_content_overflows(self):
        _lb, bar = self._make(120)
        self.assertTrue(bar.visible)

    def test_hides_again_after_content_removed(self):
        lb, bar = self._make(120)
        self.assertTrue(bar.visible)
        lb.delete(0, "end")
        for i in range(2):
            lb.insert("end", "item %d" % i)
        self.root.update()
        bar.refresh()
        self.root.update()
        self.assertFalse(bar.visible)


@unittest.skipIf(tk is None, "当前 Python 无 tkinter")
class TestAutoScrollbarHorizontal(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("300x180")
        self.root.update()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_horizontal_hidden_then_shown(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="none", height=4, width=20)
        text.grid(row=0, column=0, sticky="nsew")
        bar = attach_auto_scrollbar(frame, text, orient="horizontal",
                                    layout="grid", row=1, column=0,
                                    sticky="ew")
        text.insert("1.0", "short")
        self.root.update()
        bar.refresh()
        self.assertFalse(bar.visible)

        text.delete("1.0", "end")
        text.insert("1.0", "x" * 400)
        self.root.update()
        bar.refresh()
        self.root.update()
        self.assertTrue(bar.visible)


class TestAutoScrollbarFallback(unittest.TestCase):
    """无 tkinter 环境下模块仍应可导入。"""

    def test_module_has_api(self):
        self.assertTrue(callable(attach_auto_scrollbar))
        from ui_common import AutoScrollbar
        self.assertTrue(hasattr(AutoScrollbar, "refresh"))


if __name__ == "__main__":
    unittest.main()
