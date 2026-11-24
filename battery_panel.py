# -*- coding: utf-8 -*-
"""battery_panel.py —— EWEADN 8K 鼠标电量面板（Tkinter，零第三方依赖）。

    python battery_panel.py
    python battery_panel.py --demo    # 用假数据预览界面
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import eweadn_proto as proto

BG = "#0f1115"
CARD = "#171a21"
CARD_EDGE = "#232833"
TEXT = "#f5f7fa"
SUB = "#9aa4b2"
FAINT = "#5d6675"
GREEN = "#3ddc97"
AMBER = "#f5c451"
RED = "#ff5c7a"
ACCENT = "#4f8cff"

INTERVALS = {"30 秒": 30, "60 秒": 60, "2 分钟": 120, "5 分钟": 300}


def level_color(percent: int) -> str:
    if percent >= 60:
        return GREEN
    if percent >= 30:
        return AMBER
    return RED


def _short_reason(message: str) -> str:
    """把长错误信息压成状态栏能放下的一句话。"""
    if "休眠" in message or "未连接" in message:
        return "鼠标休眠"
    if "独占" in message:
        return "接口被占用"
    if "没有找到" in message:
        return "未找到设备"
    if "超时" in message:
        return "读取超时"
    return (message.splitlines()[0] if message else "读取失败")[:10]


class BatteryPanel(tk.Tk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self._busy = False
        self._closing = False
        self._after_id = None
        self._queue: queue.Queue = queue.Queue()
        self._demo_percent = 47

        self.title("EWEADN 8K 电量")
        self.configure(bg=BG)
        self.geometry("480x462")
        self.resizable(False, False)
        self._center()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(200, self.refresh)

    # ------------------------------------------------------------------ UI
    def _center(self):
        self.update_idletasks()
        w, h = 480, 462
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                        foreground=TEXT, arrowcolor=SUB, bordercolor=CARD_EDGE,
                        lightcolor=CARD, darkcolor=CARD, padding=2)
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", TEXT)])

        # 顶部标题
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 6))
        tk.Label(header, text="EWEADN 8K", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        tk.Label(header, text="S9 V2 Master · 匠盟方案", bg=BG, fg=FAINT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0), pady=(4, 0))
        tk.Label(header, text="3554:F517", bg=BG, fg=FAINT,
                 font=("Consolas", 9)).pack(side="right", pady=(4, 0))

        # 卡片
        card = tk.Frame(self, bg=CARD, highlightbackground=CARD_EDGE,
                        highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(8, 12))

        self.percent_label = tk.Label(
            card, text="--", bg=CARD, fg=TEXT,
            font=("Microsoft YaHei UI", 76, "bold"))
        self.percent_label.pack(pady=(18, 0))

        self.state_label = tk.Label(card, text="正在连接设备…", bg=CARD, fg=SUB,
                                    font=("Microsoft YaHei UI", 11))
        self.state_label.pack(pady=(0, 12))

        self.bar = tk.Canvas(card, width=360, height=14, bg=CARD,
                             highlightthickness=0)
        self.bar.pack()
        self.bar.create_rectangle(0, 0, 360, 14, fill="#242a35", outline="")
        self._bar_fill = self.bar.create_rectangle(0, 0, 0, 14, fill=GREEN, outline="")

        info = tk.Frame(card, bg=CARD)
        info.pack(fill="x", padx=34, pady=(18, 4))
        self.voltage_label = self._info_column(info, "电压", "--")
        self.charge_label = self._info_column(info, "状态", "--")
        self.raw_label = self._info_column(info, "设备自报", "--")

        self.time_label = tk.Label(card, text="", bg=CARD, fg=FAINT,
                                   font=("Microsoft YaHei UI", 9))
        self.time_label.pack(pady=(10, 0))

        # 底部控制条
        controls = tk.Frame(self, bg=BG)
        controls.pack(fill="x", padx=24, pady=(0, 18))

        self.refresh_btn = tk.Button(
            controls, text="立即刷新", command=self.refresh,
            bg=ACCENT, fg="white", activebackground="#3d78e0",
            activeforeground="white", relief="flat", bd=0,
            font=("Microsoft YaHei UI", 10, "bold"), padx=18, pady=6,
            cursor="hand2")
        self.refresh_btn.pack(side="left")

        self.auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            controls, text="自动刷新", variable=self.auto_var, bg=BG, fg=SUB,
            selectcolor=BG, activebackground=BG, activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
            command=self._schedule_next).pack(side="left", padx=(14, 6))

        self.interval_var = tk.StringVar(value="60 秒")
        combo = ttk.Combobox(controls, textvariable=self.interval_var,
                             values=list(INTERVALS), state="readonly", width=7,
                             font=("Microsoft YaHei UI", 9))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_next())

        self.status_dot = tk.Label(controls, text="●", bg=BG, fg=FAINT,
                                   font=("Microsoft YaHei UI", 9))
        self.status_dot.pack(side="right", padx=(0, 4))
        self.status_label = tk.Label(controls, text="", bg=BG, fg=FAINT,
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side="right")

    def _info_column(self, parent, title: str, value: str) -> tk.Label:
        box = tk.Frame(parent, bg=CARD)
        box.pack(side="left", expand=True, fill="x")
        tk.Label(box, text=title, bg=CARD, fg=FAINT,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="center")
        lab = tk.Label(box, text=value, bg=CARD, fg=TEXT,
                       font=("Microsoft YaHei UI", 12, "bold"))
        lab.pack(anchor="center", pady=(2, 0))
        return lab

    # -------------------------------------------------------------- refresh
    def refresh(self):
        if self._closing or self._busy:
            return
        self._busy = True
        self.refresh_btn.configure(state="disabled", text="读取中…")
        if self.demo:
            self.after(250, self._demo_result)
            return
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            reading = proto.read_battery()
            self._queue.put(("ok", reading))
        except proto.EweadnError as exc:
            self._queue.put(("err", str(exc)))
        except Exception as exc:  # noqa: BLE001 - 面板需要兜底，不能崩
            self._queue.put(("err", f"未知错误：{exc}"))

    def _demo_result(self):
        # 首次 87%，之后在 47% 之间切换，用来预览刷新动画
        self._demo_percent = 87 if self._demo_percent == 47 else 47
        r = proto.BatteryReading(
            percent=self._demo_percent, level_raw=90, charging=False,
            voltage_mv=4049, online=True, percent_source="voltage")
        self._queue.put(("ok", r))

    def _pump(self):
        if self._closing:
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "ok":
                    self._apply_reading(payload)
                else:
                    self._apply_error(str(payload))
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _apply_reading(self, r: proto.BatteryReading):
        self._busy = False
        self.refresh_btn.configure(state="normal", text="立即刷新")
        color = level_color(r.percent)
        self.percent_label.configure(text=f"{r.percent}%", fg=color)
        self._bar_fill_color(color)
        self.bar.coords(self._bar_fill, 0, 0, 360 * r.percent / 100.0, 14)
        self.state_label.configure(
            text="⚡ 充电中" if r.charging else "已连接 · 无线使用中",
            fg=GREEN if r.charging else SUB)
        self.voltage_label.configure(text=f"{r.voltage_v:.3f} V")
        self.charge_label.configure(text="充电中" if r.charging else "未充电",
                                    fg=GREEN if r.charging else TEXT)
        self.raw_label.configure(text=f"{r.level_raw}%")
        self.time_label.configure(
            text="更新于 " + time.strftime("%H:%M:%S") + " · 数据来自 HID 0xFF02/0x0002")
        self.status_dot.configure(fg=GREEN)
        self.status_label.configure(text="设备在线", fg=FAINT)
        self._schedule_next()

    def _bar_fill_color(self, color: str):
        self.bar.itemconfigure(self._bar_fill, fill=color)

    def _apply_error(self, message: str):
        self._busy = False
        self.refresh_btn.configure(state="normal", text="立即刷新")
        self.percent_label.configure(text="--", fg=FAINT)
        self.bar.coords(self._bar_fill, 0, 0, 0, 14)
        self.state_label.configure(text="设备暂时没有响应", fg=RED)
        self.voltage_label.configure(text="--")
        self.charge_label.configure(text="--")
        self.raw_label.configure(text="--")
        self.time_label.configure(text="动一下鼠标或按一下按键即可唤醒", fg=SUB)
        self.status_dot.configure(fg=RED)
        self.status_label.configure(text=_short_reason(message), fg=RED)
        self._schedule_next()

    def _schedule_next(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._closing or not self.auto_var.get():
            return
        seconds = INTERVALS.get(self.interval_var.get(), 60)
        self._after_id = self.after(seconds * 1000, self.refresh)

    # ---------------------------------------------------------------- close
    def _on_close(self):
        self._closing = True
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EWEADN 8K 电量面板")
    parser.add_argument("--demo", action="store_true", help="用演示数据预览界面")
    args = parser.parse_args(argv)
    app = BatteryPanel(demo=args.demo)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
