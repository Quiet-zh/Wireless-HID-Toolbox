# -*- coding: utf-8 -*-
"""keyboard_view.py —— 104 键全配列键盘示意图。

只做显示和按键高亮，不读取/记录键盘内容；Raw Input 事件由 mouse_events 提供。
"""
from __future__ import annotations

import tkinter as tk

import theme

BG = "#f7f8fc"
KEY = "#ffffff"
KEY_EDGE = "#d9deec"
KEY_TEXT = "#353b52"
ACCENT = "#635bff"
ACCENT_DARK = "#4f46e5"
ACCENT_SOFT = "#e7e5ff"
MUTED = "#8b90a3"

UI = "Microsoft YaHei UI"

# (label, vk, x, y, w, h) —— x/y 以键位单位计，104 键 ANSI
KEYS = [
    # 功能行
    ("Esc", 0x1B, 0, 0, 1, 1),
    ("F1", 0x70, 2, 0, 1, 1), ("F2", 0x71, 3, 0, 1, 1),
    ("F3", 0x72, 4, 0, 1, 1), ("F4", 0x73, 5, 0, 1, 1),
    ("F5", 0x74, 6.25, 0, 1, 1), ("F6", 0x75, 7.25, 0, 1, 1),
    ("F7", 0x76, 8.25, 0, 1, 1), ("F8", 0x77, 9.25, 0, 1, 1),
    ("F9", 0x78, 10.5, 0, 1, 1), ("F10", 0x79, 11.5, 0, 1, 1),
    ("F11", 0x7A, 12.5, 0, 1, 1), ("F12", 0x7B, 13.5, 0, 1, 1),
    ("PrtSc", 0x2C, 15.5, 0, 1, 1), ("ScrLk", 0x91, 16.5, 0, 1, 1),
    ("Pause", 0x13, 17.5, 0, 1, 1),

    # 数字行 + 导航 + 小键盘上排
    ("`", 0xC0, 0, 1, 1, 1),
    ("1", 0x31, 1, 1, 1, 1), ("2", 0x32, 2, 1, 1, 1),
    ("3", 0x33, 3, 1, 1, 1), ("4", 0x34, 4, 1, 1, 1),
    ("5", 0x35, 5, 1, 1, 1), ("6", 0x36, 6, 1, 1, 1),
    ("7", 0x37, 7, 1, 1, 1), ("8", 0x38, 8, 1, 1, 1),
    ("9", 0x39, 9, 1, 1, 1), ("0", 0x30, 10, 1, 1, 1),
    ("-", 0xBD, 11, 1, 1, 1), ("=", 0xBB, 12, 1, 1, 1),
    ("Bksp", 0x08, 13, 1, 2, 1),
    ("Ins", 0x2D, 15.5, 1, 1, 1), ("Home", 0x24, 16.5, 1, 1, 1),
    ("PgUp", 0x21, 17.5, 1, 1, 1),
    ("Num", 0x90, 19.5, 1, 1, 1), ("/", 0x6F, 20.5, 1, 1, 1),
    ("*", 0x6A, 21.5, 1, 1, 1), ("-", 0x6D, 22.5, 1, 1, 1),

    # Q 行 + 导航 + 小键盘 7/8/9/+
    ("Tab", 0x09, 0, 2, 1.5, 1),
    ("Q", 0x51, 1.5, 2, 1, 1), ("W", 0x57, 2.5, 2, 1, 1),
    ("E", 0x45, 3.5, 2, 1, 1), ("R", 0x52, 4.5, 2, 1, 1),
    ("T", 0x54, 5.5, 2, 1, 1), ("Y", 0x59, 6.5, 2, 1, 1),
    ("U", 0x55, 7.5, 2, 1, 1), ("I", 0x49, 8.5, 2, 1, 1),
    ("O", 0x4F, 9.5, 2, 1, 1), ("P", 0x50, 10.5, 2, 1, 1),
    ("[", 0xDB, 11.5, 2, 1, 1), ("]", 0xDD, 12.5, 2, 1, 1),
    ("\\", 0xDC, 13.5, 2, 1.5, 1),
    ("Del", 0x2E, 15.5, 2, 1, 1), ("End", 0x23, 16.5, 2, 1, 1),
    ("PgDn", 0x22, 17.5, 2, 1, 1),
    ("7", 0x67, 19.5, 2, 1, 1), ("8", 0x68, 20.5, 2, 1, 1),
    ("9", 0x69, 21.5, 2, 1, 1), ("+", 0x6B, 22.5, 2, 1, 2),

    # A 行 + 小键盘 4/5/6
    ("Caps", 0x14, 0, 3, 1.75, 1),
    ("A", 0x41, 1.75, 3, 1, 1), ("S", 0x53, 2.75, 3, 1, 1),
    ("D", 0x44, 3.75, 3, 1, 1), ("F", 0x46, 4.75, 3, 1, 1),
    ("G", 0x47, 5.75, 3, 1, 1), ("H", 0x48, 6.75, 3, 1, 1),
    ("J", 0x4A, 7.75, 3, 1, 1), ("K", 0x4B, 8.75, 3, 1, 1),
    ("L", 0x4C, 9.75, 3, 1, 1),
    (";", 0xBA, 10.75, 3, 1, 1), ("'", 0xDE, 11.75, 3, 1, 1),
    ("Enter", 0x0D, 12.75, 3, 2.25, 1),
    ("4", 0x64, 19.5, 3, 1, 1), ("5", 0x65, 20.5, 3, 1, 1),
    ("6", 0x66, 21.5, 3, 1, 1),

    # Z 行 + 方向 + 小键盘 1/2/3/Enter
    ("Shift", 0x10, 0, 4, 2.25, 1),
    ("Z", 0x5A, 2.25, 4, 1, 1), ("X", 0x58, 3.25, 4, 1, 1),
    ("C", 0x43, 4.25, 4, 1, 1), ("V", 0x56, 5.25, 4, 1, 1),
    ("B", 0x42, 6.25, 4, 1, 1), ("N", 0x4E, 7.25, 4, 1, 1),
    ("M", 0x4D, 8.25, 4, 1, 1),
    (",", 0xBC, 9.25, 4, 1, 1), (".", 0xBE, 10.25, 4, 1, 1),
    ("/", 0xBF, 11.25, 4, 1, 1),
    ("Shift", 0x10, 12.25, 4, 2.75, 1),
    ("Up", 0x26, 16.5, 4, 1, 1),
    ("1", 0x61, 19.5, 4, 1, 1), ("2", 0x62, 20.5, 4, 1, 1),
    ("3", 0x63, 21.5, 4, 1, 1), ("Enter", 0x0D, 22.5, 4, 1, 2),

    # 底行 + 方向 + 小键盘 0/.
    ("Ctrl", 0x11, 0, 5, 1.25, 1), ("Win", 0x5B, 1.25, 5, 1.25, 1),
    ("Alt", 0x12, 2.5, 5, 1.25, 1), ("Space", 0x20, 3.75, 5, 6.25, 1),
    ("Alt", 0x12, 10, 5, 1.25, 1), ("Win", 0x5B, 11.25, 5, 1.25, 1),
    ("Menu", 0x5D, 12.5, 5, 1.25, 1), ("Ctrl", 0x11, 13.75, 5, 1.25, 1),
    ("Left", 0x25, 15.5, 5, 1, 1), ("Down", 0x28, 16.5, 5, 1, 1),
    ("Right", 0x27, 17.5, 5, 1, 1),
    ("0", 0x60, 19.5, 5, 2, 1), (".", 0x6E, 21.5, 5, 1, 1),
]


class KeyboardView(tk.Canvas):
    """104 键全配列示意图；按 VK 高亮，锁定键保留底色。"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, highlightthickness=0, **kwargs)
        self._items: dict[int, list[int]] = {}
        self._pressed: set[int] = set()
        self._locks: set[int] = set()
        self._unit = 26
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_key(self, vk: int, pressed: bool) -> None:
        if pressed:
            self._pressed.add(vk)
        else:
            self._pressed.discard(vk)
        self._paint(vk)

    def set_lock(self, vk: int, locked: bool) -> None:
        if locked:
            self._locks.add(vk)
        else:
            self._locks.discard(vk)
        self._paint(vk)

    def reset(self) -> None:
        self._pressed.clear()
        self._locks.clear()
        for vk in self._items:
            self._paint(vk)

    def _colors(self):
        if theme.current() == "dark":
            return {
                "key": "#171a21", "edge": "#2a303c", "text": "#a3aab8",
                "lock": "#2b2a55", "lock_edge": "#635bff",
                "lock_text": "#c7c3ff",
            }
        return {
            "key": KEY, "edge": KEY_EDGE, "text": KEY_TEXT,
            "lock": ACCENT_SOFT, "lock_edge": ACCENT,
            "lock_text": ACCENT_DARK,
        }

    def redraw(self) -> None:
        self.delete("all")
        self._items.clear()
        colors = self._colors()
        w = max(self.winfo_width(), 640)
        h = max(self.winfo_height(), 240)
        unit = min((w - 22) / 23.5, (h - 18) / 6.0)
        self._unit = unit
        ox = max(6, (w - 23.5 * unit) / 2)
        oy = max(6, (h - 6.0 * unit) / 2)
        gap = max(1, unit * 0.07)
        font = (UI, max(6, int(unit * 0.23)))
        for label, vk, x, y, kw, kh in KEYS:
            x1 = ox + x * unit + gap / 2
            y1 = oy + y * unit + gap / 2
            x2 = ox + (x + kw) * unit - gap / 2
            y2 = oy + (y + kh) * unit - gap / 2
            rect = self.create_rectangle(x1, y1, x2, y2,
                                         fill=colors["key"],
                                         outline=colors["edge"], width=1)
            text = self.create_text((x1 + x2) / 2, (y1 + y2) / 2,
                                    text=label, fill=colors["text"], font=font)
            self._items.setdefault(vk, []).extend([rect, text])
        for vk in set(self._items):
            self._paint(vk)

    def _paint(self, vk: int) -> None:
        items = self._items.get(vk)
        if not items:
            return
        colors = self._colors()
        if vk in self._pressed:
            fill, outline, fg = ACCENT, ACCENT_DARK, "#ffffff"
        elif vk in self._locks:
            fill, outline = colors["lock"], colors["lock_edge"]
            fg = colors["lock_text"]
        else:
            fill, outline, fg = colors["key"], colors["edge"], colors["text"]
        for i, item in enumerate(items):
            if i % 2 == 0:
                self.itemconfigure(item, fill=fill, outline=outline)
            else:
                self.itemconfigure(item, fill=fg)
