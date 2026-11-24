# -*- coding: utf-8 -*-
"""mouse_test_gui.py —— 鼠标键盘测试（可视化）。

    python mouse_test_gui.py
    python mouse_test_gui.py --demo    # 自动生成演示事件，便于预览界面

事件来自 mouse_events.RawInputListener（Windows Raw Input）。
当系统里有多个鼠标/键盘时，可以在对应页签选择要监听的设备。
"""
from __future__ import annotations

import argparse
import ctypes
import queue
import random
import time
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

import mouse_events as me
from keyboard_view import KeyboardView

BG = "#f4f5fa"
CARD = "#ffffff"
BORDER = "#e4e7f1"
CHIP = "#f7f8fc"
TEXT = "#1f2333"
MUTED = "#8b90a3"
FAINT = "#b3b8c8"
ACCENT = "#635bff"
ACCENT_DARK = "#4f46e5"
ACCENT_SOFT = "#eef0ff"
DARK = "#1b2233"
DARK_BODY = "#232b3d"
DARK_BTN = "#38435d"
DARK_LINE = "#4b566f"
GREEN = "#10b981"
AMBER = "#f59e0b"
RED = "#ef4444"

UI = "Microsoft YaHei UI"
MONO = "Consolas"

BUTTON_LABELS = [("left", "左键"), ("middle", "中键"), ("right", "右键"),
                 ("side1", "后退"), ("side2", "前进")]


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    r = min(r, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class MouseTestApp(tk.Tk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.events: queue.Queue = queue.Queue()
        self.listener = None
        self.listener_error = None
        self.test_devices = me.list_test_devices()
        self.mouse_var = tk.StringVar(value="全部鼠标")
        self.keyboard_var = tk.StringVar(value="全部键盘")
        self.mouse_combo = None
        self.keyboard_combo = None
        self._init_device_choices()

        self.active_tab = "mouse"
        self.tiles = {}
        self.highlights = {}
        self.double_ms = tk.IntVar(value=500)

        self.total_clicks = 0
        self.double_clicks = 0
        self.click_times = deque()
        self.last_click = None          # (button, ts) 用于双击
        self.prev_click_ts = None       # 上一次按下（任意键）
        self.last_interval_ms = None

        self.wheel_up = 0
        self.wheel_down = 0
        self.key_count = 0
        self.max_rollover = 0
        self.active_keys: set[int] = set()
        self.locks: set[int] = set()
        self.last_move = (0, 0)
        self.last_screen = (0, 0)
        self.demo_step = 0
        self.pad_xy = None
        self.pressed_buttons = set()

        self.title("鼠标键盘测试")
        self.geometry("1180x760")
        self.minsize(1000, 680)
        self.configure(bg=BG)
        self._center()

        self._build_banner()
        self._build_tabs()
        self._build_mouse_page()
        self._build_keyboard_page()
        self._show_tab("mouse")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if not demo:
            self._start_listener()
        self.after(16, self._pump)
        self.after(200, self._tick_cps)
        if demo:
            self.after(600, self._demo_tick)

    # ------------------------------------------------------------- devices
    def _devices(self, kind: str) -> list[dict]:
        return [d for d in self.test_devices if d["kind"] == kind]

    def _init_device_choices(self):
        for kind, var in (("mouse", self.mouse_var),
                          ("keyboard", self.keyboard_var)):
            devs = self._devices(kind)
            if len(devs) == 1:
                var.set(devs[0]["label"])
            else:
                var.set("全部鼠标" if kind == "mouse" else "全部键盘")

    def _selector(self, parent, kind: str):
        devs = self._devices(kind)
        if len(devs) <= 1:
            return
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="监听设备", bg=BG, fg=MUTED,
                 font=(UI, 9)).pack(side="left")
        var = self.mouse_var if kind == "mouse" else self.keyboard_var
        options = (["全部鼠标" if kind == "mouse" else "全部键盘"]
                   + [d["label"] for d in devs])
        combo = ttk.Combobox(row, textvariable=var, values=options,
                             state="readonly", width=30, font=(UI, 9))
        combo.pack(side="left", padx=(8, 6))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._restart_listener())
        tk.Button(row, text="刷新", command=self._refresh_devices,
                  bg=CHIP, fg=MUTED,
                  relief="flat", bd=0, font=(UI, 8), padx=8, pady=2,
                  cursor="hand2").pack(side="left")
        if kind == "mouse":
            self.mouse_combo = combo
        else:
            self.keyboard_combo = combo

    def _refresh_devices(self):
        self.test_devices = me.list_test_devices()
        for kind, combo, var in (("mouse", self.mouse_combo, self.mouse_var),
                                 ("keyboard", self.keyboard_combo,
                                  self.keyboard_var)):
            devs = self._devices(kind)
            all_text = "全部鼠标" if kind == "mouse" else "全部键盘"
            if combo is not None:
                values = [all_text] + [d["label"] for d in devs]
                combo.configure(values=values)
                if var.get() not in values:
                    var.set(all_text)
            elif len(devs) == 1:
                var.set(devs[0]["label"])
            elif not devs:
                var.set(all_text)
        self._restart_listener()

    def _allowed_handles(self) -> set[int]:
        allowed: set[int] = set()
        for kind, var in (("mouse", self.mouse_var),
                          ("keyboard", self.keyboard_var)):
            devs = self._devices(kind)
            all_text = "全部鼠标" if kind == "mouse" else "全部键盘"
            choice = var.get()
            if choice == all_text or len(devs) <= 1:
                for d in devs:
                    allowed.update(d["handles"])
            else:
                for d in devs:
                    if d["label"] == choice:
                        allowed.update(d["handles"])
                        break
        return allowed

    # ------------------------------------------------------------- window
    def _center(self):
        self.update_idletasks()
        w, h = 1180, 760
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    def _build_banner(self):
        bar = tk.Frame(self, bg=ACCENT_SOFT, height=40)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="●  鼠标键盘测试", bg=ACCENT_SOFT, fg=ACCENT,
                 font=(UI, 10, "bold")).pack(side="left", padx=22)
        tk.Label(bar, text="Raw Input  ·  只读  ·  不记录、不落盘",
                 bg=ACCENT_SOFT, fg="#7a76c9", font=(UI, 9)).pack(side="right", padx=22)

    def _build_tabs(self):
        wrap = tk.Frame(self, bg=CARD)
        wrap.pack(fill="x", padx=24, pady=(16, 0))
        self.tab_widgets = {}
        for key, text in (("mouse", "鼠标测试"), ("keyboard", "键盘测试")):
            box = tk.Frame(wrap, bg=CARD)
            box.pack(side="left")
            lbl = tk.Label(box, text=text, bg=CARD, fg=MUTED,
                           font=(UI, 11, "bold"), padx=18, pady=10, cursor="hand2")
            lbl.pack()
            line = tk.Frame(box, bg=CARD, height=2)
            line.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, k=key: self._show_tab(k))
            self.tab_widgets[key] = (lbl, line)

    def _build_mouse_page(self):
        self.page_mouse = tk.Frame(self, bg=BG)
        self.page_mouse.grid_columnconfigure(0, weight=3)
        self.page_mouse.grid_columnconfigure(1, weight=2)
        self.page_mouse.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self.page_mouse, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(24, 10), pady=14)
        right = tk.Frame(self.page_mouse, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 24), pady=14)

        # 标题
        head = tk.Frame(left, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="◉", bg=BG, fg=ACCENT,
                 font=(UI, 13, "bold")).pack(side="left")
        tk.Label(head, text=" 鼠标测试区域", bg=BG, fg=TEXT,
                 font=(UI, 13, "bold")).pack(side="left")
        tk.Label(left, text="在此区域内点击、滚动或移动鼠标进行测试",
                 bg=BG, fg=MUTED, font=(UI, 9)).pack(anchor="w", pady=(4, 6))
        self._selector(left, "mouse")
        tk.Label(left, text="示意图为通用 5 键；不同型号的 DPI/宏键通常不走标准 Raw Input，"
                            "需要厂商协议才能单独点亮",
                 bg=BG, fg=FAINT, font=(UI, 8), anchor="w",
                 wraplength=700, justify="left").pack(fill="x", pady=(0, 6))

        self.pad = tk.Canvas(left, bg=BG, highlightthickness=0, height=360)
        self.pad.pack(fill="both", expand=True)
        self.pad.bind("<Configure>", self._redraw_pad)

        # 五个按键指示
        btn_row = tk.Frame(left, bg=BG)
        btn_row.pack(fill="x", pady=(14, 0))
        for key, label in BUTTON_LABELS:
            self._make_tile(btn_row, key, label)

        self._build_wheel_card(right)
        self._build_coord_card(right)
        self._build_stats_card(right)

    def _card(self, parent):
        f = tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                     highlightthickness=1)
        return f

    def _card_head(self, card, title):
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=16, pady=(13, 0))
        tk.Label(row, text="◈", bg=CARD, fg=ACCENT,
                 font=(UI, 9, "bold")).pack(side="left")
        tk.Label(row, text=" " + title, bg=CARD, fg=TEXT,
                 font=(UI, 10, "bold")).pack(side="left")
        return row

    def _build_wheel_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x")
        row = self._card_head(card, "滚轮")
        tk.Label(row, text="", bg=CARD).pack(side="right")

        body = tk.Frame(card, bg=CARD)
        body.pack(fill="x", padx=16, pady=(10, 14))
        self.wheel_boxes = {}
        for idx, (key, arrow, text) in enumerate(
                (("up", "↑", "向上滚动"), ("down", "↓", "向下滚动"))):
            box = tk.Frame(body, bg=CHIP, highlightbackground=BORDER,
                           highlightthickness=1)
            box.grid(row=0, column=idx, sticky="nsew",
                     padx=(0, 5) if idx == 0 else (5, 0))
            body.grid_columnconfigure(idx, weight=1)
            arrow_lbl = tk.Label(box, text=arrow, bg=CHIP, fg="#c5cad9",
                                 font=(UI, 20))
            arrow_lbl.pack(pady=(6, 0))
            name_lbl = tk.Label(box, text=text, bg=CHIP, fg=MUTED, font=(UI, 9))
            name_lbl.pack()
            count_lbl = tk.Label(box, text="0", bg=CHIP, fg=TEXT,
                                 font=(UI, 15, "bold"))
            count_lbl.pack(pady=(2, 8))
            self.wheel_boxes[key] = {
                "widgets": [box, box, arrow_lbl, name_lbl, count_lbl],
                "count": count_lbl,
            }

    def _build_coord_card(self, parent):
        card = self._card(parent)
        card.pack(fill="x", pady=12)
        self._card_head(card, "鼠标坐标")

        grid = tk.Frame(card, bg=CARD)
        grid.pack(fill="x", padx=16, pady=(8, 14))
        self.coord_labels = {}
        items = [("Client", "client"), ("Page", "page"),
                 ("Screen", "screen"), ("Offset", "offset")]
        for i, (label, key) in enumerate(items):
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=CHIP)
            cell.grid(row=r, column=c, sticky="nsew",
                      padx=(0, 4) if c == 0 else (4, 0), pady=3)
            grid.grid_columnconfigure(c, weight=1)
            tk.Label(cell, text=label, bg=CHIP, fg=MUTED, font=(UI, 9),
                     width=7, anchor="w").pack(side="left", padx=(8, 0), pady=5)
            val = tk.Label(cell, text="-, -", bg=CHIP, fg=TEXT,
                           font=(MONO, 10), anchor="w")
            val.pack(side="left", padx=(2, 8), pady=5)
            self.coord_labels[key] = val

        move = tk.Frame(grid, bg=CHIP)
        move.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=3)
        tk.Label(move, text="Movement", bg=CHIP, fg=MUTED, font=(UI, 9),
                 width=9, anchor="w").pack(side="left", padx=(8, 0), pady=5)
        self.coord_labels["movement"] = tk.Label(
            move, text="+0, +0", bg=CHIP, fg=TEXT, font=(MONO, 10))
        self.coord_labels["movement"].pack(side="left", padx=(0, 8), pady=5)

    def _build_stats_card(self, parent):
        card = self._card(parent)
        card.pack(fill="both", expand=True)
        row = self._card_head(card, "点击统计")
        reset = tk.Label(row, text="↻ 重置统计", bg=CARD, fg=MUTED,
                         font=(UI, 9), cursor="hand2")
        reset.pack(side="right")
        reset.bind("<Button-1>", lambda _e: self._reset_stats())

        stats = tk.Frame(card, bg=CARD)
        stats.pack(fill="x", padx=16, pady=(12, 8))
        self.stat_labels = {}
        spec = [("total", "总点击数", TEXT), ("double", "双击次数", AMBER),
                ("cps", "每秒点击", GREEN)]
        for i, (key, label, color) in enumerate(spec):
            box = tk.Frame(stats, bg=CHIP)
            box.grid(row=0, column=i, sticky="nsew",
                     padx=(0, 4) if i < 2 else (4, 0))
            stats.grid_columnconfigure(i, weight=1)
            tk.Label(box, text=label, bg=CHIP, fg=MUTED, font=(UI, 8)).pack(pady=(7, 0))
            val = tk.Label(box, text="0", bg=CHIP, fg=color, font=(UI, 18, "bold"))
            val.pack(pady=(0, 7))
            self.stat_labels[key] = val

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(4, 8))

        thr = tk.Frame(card, bg=CARD)
        thr.pack(fill="x", padx=16, pady=3)
        tk.Label(thr, text="双击判定延时", bg=CARD, fg=MUTED,
                 font=(UI, 9)).pack(side="left")
        self.thr_spin = tk.Spinbox(
            thr, from_=100, to=1000, increment=50, width=5,
            textvariable=self.double_ms, font=(UI, 9), relief="flat",
            bg=CHIP, fg=TEXT, buttonbackground=CHIP, highlightthickness=0,
            justify="center")
        tk.Label(thr, text="ms", bg=CARD, fg=MUTED, font=(UI, 9)).pack(
            side="right", padx=(2, 2))
        self.thr_spin.pack(side="right")

        gap = tk.Frame(card, bg=CARD)
        gap.pack(fill="x", padx=16, pady=(3, 12))
        tk.Label(gap, text="两次点击间隔", bg=CARD, fg=MUTED,
                 font=(UI, 9)).pack(side="left")
        self.interval_label = tk.Label(gap, text="- ms", bg=CARD, fg=TEXT,
                                       font=(UI, 9, "bold"))
        self.interval_label.pack(side="right", padx=(0, 2))

    # ------------------------------------------------------------- tiles
    def _make_tile(self, parent, key, label):
        c = tk.Canvas(parent, width=92, height=92, bg=BG,
                      highlightthickness=0)
        c.pack(side="left", padx=(0, 12))
        bg_id = round_rect(c, 2, 2, 90, 90, 14, fill="#f1f3f9", outline=BORDER)
        icon = []
        icon.append(round_rect(c, 36, 18, 56, 50, 10, fill="#9aa2b6", outline=""))
        icon.append(c.create_line(46, 19, 46, 34, fill="#f1f3f9", width=2))
        icon.append(c.create_oval(41, 38, 51, 46, fill="#f1f3f9", outline=""))
        label_id = c.create_text(46, 72, text=label, fill="#6b7280",
                                 font=(UI, 9))
        self.tiles[key] = {
            "canvas": c, "bg": bg_id, "icon": icon, "label": label_id,
        }

    def _set_tile_pressed(self, key, pressed):
        tile = self.tiles.get(key)
        if not tile:
            return
        c = tile["canvas"]
        if pressed:
            c.itemconfigure(tile["bg"], fill=ACCENT, outline=ACCENT)
            for item in tile["icon"]:
                c.itemconfigure(item, fill="white")
            c.itemconfigure(tile["label"], fill="white")
        else:
            c.itemconfigure(tile["bg"], fill="#f1f3f9", outline=BORDER)
            c.itemconfigure(tile["icon"][0], fill="#9aa2b6")
            c.itemconfigure(tile["icon"][1], fill="#f1f3f9")
            c.itemconfigure(tile["icon"][2], fill="#f1f3f9")
            c.itemconfigure(tile["label"], fill="#6b7280")

    # ---------------------------------------------------------------- pad
    def _redraw_pad(self, _event=None):
        self.pad.delete("all")
        w = max(self.pad.winfo_width(), 100)
        h = max(self.pad.winfo_height(), 100)
        round_rect(self.pad, 1, 1, w - 1, h - 1, 18, fill=DARK,
                   outline="#2a3247", tags="pad")
        self._draw_mouse(w / 2, h / 2 - 18)
        for key in self.pressed_buttons:
            self._set_mouse_highlight(key, True)
        self.pad.tag_raise("mouse")

    def _draw_mouse(self, cx, cy):
        pad = self.pad
        # 机身
        round_rect(pad, cx - 60, cy - 90, cx + 60, cy + 90, 38,
                   fill=DARK_BODY, outline=DARK_LINE, width=2, tags="mouse")
        # 左右键
        round_rect(pad, cx - 56, cy - 86, cx - 4, cy - 8, 24,
                   fill=DARK_BTN, outline="", tags="mouse")
        round_rect(pad, cx + 4, cy - 86, cx + 56, cy - 8, 24,
                   fill=DARK_BTN, outline="", tags="mouse")
        pad.create_line(cx, cy - 86, cx, cy - 8, fill="#1b2233", width=4,
                        tags="mouse")
        # 滚轮
        round_rect(pad, cx - 9, cy - 62, cx + 9, cy - 20, 9,
                   fill="#5b6788", outline="#3a4560", tags="mouse")
        # 侧键
        round_rect(pad, cx - 68, cy - 10, cx - 56, cy + 18, 6,
                   fill=DARK_BTN, outline="", tags="mouse")
        round_rect(pad, cx - 68, cy + 26, cx - 56, cy + 54, 6,
                   fill=DARK_BTN, outline="", tags="mouse")
        # 底部指示灯
        pad.create_oval(cx - 3, cy + 64, cx + 3, cy + 70,
                        fill="#3d4660", outline="", tags="mouse")

        # 高亮层放在机身之上
        self.highlights = {
            "left": round_rect(pad, cx - 56, cy - 86, cx - 10, cy - 8, 24,
                               fill=ACCENT, outline="", state="hidden", tags="mouse"),
            "right": round_rect(pad, cx + 10, cy - 86, cx + 56, cy - 8, 24,
                                fill=ACCENT, outline="", state="hidden", tags="mouse"),
            "middle": round_rect(pad, cx - 9, cy - 62, cx + 9, cy - 20, 9,
                                 fill=ACCENT, outline="", state="hidden", tags="mouse"),
            "side1": round_rect(pad, cx - 68, cy - 10, cx - 56, cy + 18, 6,
                                fill=ACCENT, outline="", state="hidden", tags="mouse"),
            "side2": round_rect(pad, cx - 68, cy + 26, cx - 56, cy + 54, 6,
                                fill=ACCENT, outline="", state="hidden", tags="mouse"),
        }

        pad.create_text(cx, cy + 110, text="鼠标测试", fill="#5c6886",
                        font=(UI, 9), tags="mouse")
        pad.create_text(cx, cy + 128, text="Raw Input", fill="#454f68",
                        font=(UI, 8), tags="mouse")
        self.pad_xy = pad.create_text(
            16, max(self.pad.winfo_height() - 14, 20), text="X: -, Y: -",
            anchor="sw", fill="#7d89a3", font=(MONO, 10), tags="xy")

    def _set_mouse_highlight(self, key, pressed):
        item = self.highlights.get(key)
        if item:
            self.pad.itemconfigure(item, state="normal" if pressed else "hidden")

    # ------------------------------------------------------------ keyboard
    def _build_keyboard_page(self):
        self.page_keyboard = tk.Frame(self, bg=BG)
        card = self._card(self.page_keyboard)
        card.pack(fill="both", expand=True, padx=24, pady=14)

        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=24, pady=(16, 0))
        tk.Label(head, text="⌨", bg=CARD, fg=ACCENT,
                 font=(UI, 14)).pack(side="left")
        tk.Label(head, text=" 键盘测试区域", bg=CARD, fg=TEXT,
                 font=(UI, 13, "bold")).pack(side="left")
        tk.Label(head, text="全配列 104 键 · 按下亮起 · 松开熄灭",
                 bg=CARD, fg=MUTED, font=(UI, 8)).pack(side="right")
        tk.Label(card, text="按键盘上的任意键进行测试（键值只显示，不记录、不落盘）",
                 bg=CARD, fg=MUTED, font=(UI, 9)).pack(anchor="w", padx=24, pady=(4, 0))
        self._selector(card, "keyboard")

        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=24, pady=(8, 16))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=CHIP, highlightbackground=BORDER,
                        highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.kb_view = KeyboardView(left)
        self.kb_view.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        status = tk.Frame(left, bg=CHIP)
        status.pack(fill="x", padx=10, pady=(0, 8))
        self.key_big = tk.Label(status, text="—", bg=CHIP, fg=TEXT,
                                font=(UI, 15, "bold"), width=12, anchor="w")
        self.key_big.pack(side="left")
        self.key_meta = tk.Label(status, text="等待按键…", bg=CHIP, fg=MUTED,
                                 font=(MONO, 9), anchor="w")
        self.key_meta.pack(side="left", padx=(8, 0))
        tk.Button(status, text="重置", command=self._reset_keyboard,
                  bg=CARD, fg=MUTED, relief="flat", bd=0,
                  font=(UI, 8), padx=8, pady=2,
                  cursor="hand2").pack(side="right")

        right = tk.Frame(body, bg=CARD)
        right.grid(row=0, column=1, sticky="nsew")
        self.key_count_label = tk.Label(right, text="按键次数  0", bg=CARD,
                                        fg=TEXT, font=(UI, 11, "bold"))
        self.key_count_label.pack(anchor="w")
        self.rollover_label = tk.Label(right, text="同时按下  0  ·  最大 0",
                                       bg=CARD, fg=MUTED, font=(UI, 9))
        self.rollover_label.pack(anchor="w", pady=(4, 0))
        self.lock_label = tk.Label(right, text="Caps —   Num —   Scroll —",
                                   bg=CARD, fg=MUTED, font=(UI, 9))
        self.lock_label.pack(anchor="w", pady=(2, 8))
        tk.Label(right, text="最近按键", bg=CARD, fg=MUTED,
                 font=(UI, 9)).pack(anchor="w", pady=(4, 4))
        self.key_list = tk.Listbox(
            right, font=(MONO, 9), relief="flat", bg=CHIP, fg=TEXT,
            selectbackground=CHIP, selectforeground=TEXT,
            highlightthickness=1, highlightbackground=BORDER, height=12)
        self.key_list.pack(fill="both", expand=True)

    # -------------------------------------------------------------- tabs
    def _show_tab(self, key):
        self.active_tab = key
        for k, (lbl, line) in self.tab_widgets.items():
            active = k == key
            lbl.configure(fg=ACCENT if active else MUTED)
            line.configure(bg=ACCENT if active else CARD)
        self.page_mouse.pack_forget()
        self.page_keyboard.pack_forget()
        page = self.page_mouse if key == "mouse" else self.page_keyboard
        page.pack(fill="both", expand=True)

    # ----------------------------------------------------------- listener
    def _start_listener(self):
        try:
            self.listener_error = None
            self.listener = me.RawInputListener(
                self.events.put, handles=self._allowed_handles())
            self.listener.start()
        except Exception as exc:  # noqa: BLE001
            self.listener_error = str(exc)

    def _restart_listener(self):
        if self.demo:
            return
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        try:
            while True:
                self.events.get_nowait()
        except queue.Empty:
            pass
        self._start_listener()

    # -------------------------------------------------------------- queue
    def _pump(self):
        try:
            for _ in range(600):
                ev = self.events.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self.after(12, self._pump)

    def _handle_event(self, ev):
        kind = ev.get("type")
        if kind == "move":
            self.last_move = (ev["dx"], ev["dy"])
            self._update_coords(ev)
        elif kind == "button":
            self._update_coords(ev)
            self._on_button(ev)
        elif kind == "wheel":
            self._update_coords(ev)
            self._on_wheel(ev)
        elif kind == "key":
            self._on_key(ev)

    def _update_coords(self, ev):
        sx, sy = ev.get("screen", (0, 0))
        self.last_screen = (sx, sy)
        px, py = self.pad.winfo_rootx(), self.pad.winfo_rooty()
        pw, ph = self.pad.winfo_width(), self.pad.winfo_height()
        client = (sx - px, sy - py)
        page = (sx - self.winfo_rootx(), sy - self.winfo_rooty())
        offset = (client[0] - pw // 2, client[1] - ph // 2)
        self.coord_labels["client"].configure(text=f"{client[0]}, {client[1]}")
        self.coord_labels["page"].configure(text=f"{page[0]}, {page[1]}")
        self.coord_labels["screen"].configure(text=f"{sx}, {sy}")
        self.coord_labels["offset"].configure(text=f"{offset[0]}, {offset[1]}")
        dx, dy = self.last_move
        self.coord_labels["movement"].configure(text=f"{dx:+d}, {dy:+d}")
        if 0 <= client[0] < pw and 0 <= client[1] < ph:
            if self.pad_xy is not None:
                self.pad.itemconfigure(self.pad_xy,
                                       text=f"X: {client[0]}, Y: {client[1]}")
        else:
            if self.pad_xy is not None:
                self.pad.itemconfigure(self.pad_xy, text="X: -, Y: -")

    def _on_button(self, ev):
        key, action = ev["button"], ev["action"]
        pressed = action == "down"
        if pressed:
            self.pressed_buttons.add(key)
        else:
            self.pressed_buttons.discard(key)
        self._set_tile_pressed(key, pressed)
        self._set_mouse_highlight(key, pressed)
        if not pressed:
            return
        now = time.time()
        self.total_clicks += 1
        self.click_times.append(now)
        if len(self.click_times) > 200:
            self.click_times.popleft()
        if self.prev_click_ts is not None:
            self.last_interval_ms = int(round((now - self.prev_click_ts) * 1000))
        self.prev_click_ts = now

        try:
            threshold_ms = int(self.double_ms.get())
        except (tk.TclError, ValueError, TypeError):
            threshold_ms = 500
        threshold = max(100, min(1000, threshold_ms)) / 1000.0
        if (self.last_click and self.last_click[0] == key
                and now - self.last_click[1] <= threshold):
            self.double_clicks += 1
            self.last_click = None
        else:
            self.last_click = (key, now)

        self._refresh_click_labels()
        self._ripple(ev)

    def _on_wheel(self, ev):
        if ev.get("horizontal"):
            return
        if ev["delta"] > 0:
            self.wheel_up += 1
            self.wheel_boxes["up"]["count"].configure(text=str(self.wheel_up))
            self._flash_wheel("up")
        else:
            self.wheel_down += 1
            self.wheel_boxes["down"]["count"].configure(text=str(self.wheel_down))
            self._flash_wheel("down")

    def _flash_wheel(self, key):
        box = self.wheel_boxes[key]
        for w in box["widgets"]:
            try:
                w.configure(bg=ACCENT_SOFT)
            except tk.TclError:
                pass
        self.after(160, lambda: self._unflash_wheel(key))

    def _unflash_wheel(self, key):
        box = self.wheel_boxes[key]
        for w in box["widgets"]:
            try:
                w.configure(bg=CHIP)
            except tk.TclError:
                pass

    def _refresh_click_labels(self):
        self.stat_labels["total"].configure(text=str(self.total_clicks))
        self.stat_labels["double"].configure(text=str(self.double_clicks))
        self.interval_label.configure(
            text=f"{self.last_interval_ms} ms" if self.last_interval_ms is not None else "- ms")

    def _tick_cps(self):
        now = time.time()
        while self.click_times and now - self.click_times[0] > 1.0:
            self.click_times.popleft()
        self.stat_labels["cps"].configure(text=str(len(self.click_times)))
        self.after(200, self._tick_cps)

    def _reset_stats(self):
        self.total_clicks = 0
        self.double_clicks = 0
        self.click_times.clear()
        self.last_click = None
        self.prev_click_ts = None
        self.last_interval_ms = None
        self._refresh_click_labels()
        self.stat_labels["cps"].configure(text="0")

    def _ripple(self, ev):
        sx, sy = ev.get("screen", (0, 0))
        px, py = self.pad.winfo_rootx(), self.pad.winfo_rooty()
        x, y = sx - px, sy - py
        if not (0 <= x < self.pad.winfo_width() and 0 <= y < self.pad.winfo_height()):
            return
        item = self.pad.create_oval(x - 5, y - 5, x + 5, y + 5,
                                    outline=ACCENT, width=2, tags="ripple")
        steps = [("#8b86ff", 9), ("#7a75f0", 15), ("#6a65d0", 21)]

        def grow(i=0):
            if i >= len(steps):
                self.pad.delete(item)
                return
            color, r = steps[i]
            self.pad.coords(item, x - r, y - r, x + r, y + r)
            self.pad.itemconfigure(item, outline=color)
            self.after(55, lambda: grow(i + 1))
        grow()

    # ------------------------------------------------------------- keyboard
    def _on_key(self, ev):
        vk = int(ev.get("vk", 0) or 0)
        name = ev.get("name", "?")
        down = ev.get("action") == "down"
        if down:
            self.kb_view.set_key(vk, True)
            if vk not in self.active_keys:
                self.active_keys.add(vk)
                self.key_count += 1
                self.max_rollover = max(self.max_rollover,
                                        len(self.active_keys))
                self.key_list.insert(
                    0, f"{name:<12} VK 0x{vk:02X}")
                if self.key_list.size() > 12:
                    self.key_list.delete(12, tk.END)
                if vk in (0x14, 0x90, 0x91):      # Caps / Num / Scroll
                    if vk in self.locks:
                        self.locks.discard(vk)
                    else:
                        self.locks.add(vk)
                    self.kb_view.set_lock(vk, vk in self.locks)
            self.key_big.configure(text=name)
            self.key_meta.configure(
                text=f"VK 0x{vk:02X}   scan 0x{ev.get('scan', 0):02X}")
        else:
            self.active_keys.discard(vk)
            self.kb_view.set_key(vk, False)
        self._update_keyboard_stats()

    def _update_keyboard_stats(self):
        self.key_count_label.configure(text=f"按键次数  {self.key_count}")
        self.rollover_label.configure(
            text=f"同时按下  {len(self.active_keys)}  ·  "
                 f"最大 {self.max_rollover}")
        names = {"Caps": 0x14, "Num": 0x90, "Scroll": 0x91}
        self.lock_label.configure(
            text="   ".join(
                f"{label} {'ON' if vk in self.locks else '—'}"
                for label, vk in names.items()))

    def _reset_keyboard(self):
        self.active_keys.clear()
        self.locks.clear()
        self.key_count = 0
        self.max_rollover = 0
        self.kb_view.reset()
        self.key_big.configure(text="—")
        self.key_meta.configure(text="等待按键…")
        self.key_list.delete(0, tk.END)
        self._update_keyboard_stats()

    # ----------------------------------------------------------------- demo
    def _demo_tick(self):
        if not self.demo:
            return
        self.demo_step += 1
        w = max(self.pad.winfo_width(), 200)
        h = max(self.pad.winfo_height(), 200)
        sx = self.pad.winfo_rootx() + w // 2 + random.randint(-60, 60)
        sy = self.pad.winfo_rooty() + h // 2 + random.randint(-50, 50)
        base = {"screen": (sx, sy), "eweadn": True, "handle": 0, "ts": time.time()}
        step = self.demo_step % 8
        if step in (0, 4):
            self.events.put(dict(base, type="move", dx=random.randint(-40, 40),
                                 dy=random.randint(-40, 40)))
        elif step == 1:
            self.events.put(dict(base, type="button", button="left", action="down"))
        elif step == 2:
            self.events.put(dict(base, type="button", button="left", action="up"))
        elif step == 3:
            self.events.put(dict(base, type="wheel", delta=120, horizontal=False))
        elif step == 5:
            self.events.put(dict(base, type="button", button="right", action="down"))
        elif step == 6:
            self.events.put(dict(base, type="button", button="right", action="up"))
        elif step == 7:
            self.events.put(dict(base, type="move", dx=random.randint(-30, 30),
                                 dy=random.randint(-30, 30)))
            self.events.put(dict(base, type="wheel", delta=-120, horizontal=False))
        self.after(650, self._demo_tick)

    # ---------------------------------------------------------------- close
    def _on_close(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
        self.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="鼠标键盘测试")
    parser.add_argument("--demo", action="store_true", help="自动生成演示事件")
    args = parser.parse_args(argv)
    enable_dpi_awareness()
    app = MouseTestApp(demo=args.demo)
    if app.listener_error:
        messagebox.showerror("Raw Input", f"监听启动失败：\n{app.listener_error}")
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
