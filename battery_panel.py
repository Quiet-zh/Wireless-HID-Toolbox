# -*- coding: utf-8 -*-
"""battery_panel.py —— EWEADN 8K 鼠标 + PMO WAVE75 键盘电量面板。

    python battery_panel.py
    python battery_panel.py --demo    # 用演示数据预览界面
"""
from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import eweadn_proto as mouse_proto
import pmo_proto as kb_proto
import tray_common as tc

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
ACCENT_KB = "#a78bfa"

INTERVALS = {"30 秒": 30, "60 秒": 60, "2 分钟": 120, "5 分钟": 300}


def level_color(percent: int) -> str:
    if percent >= 60:
        return GREEN
    if percent >= 30:
        return AMBER
    return RED


def interval_label(seconds: int) -> str:
    for label, value in INTERVALS.items():
        if value == seconds:
            return label
    return "60 秒"


class DeviceCard(tk.Frame):
    def __init__(self, parent, name: str, subtitle: str, code: str,
                 accent: str, demo_note: str = ""):
        super().__init__(parent, bg=CARD, highlightbackground=CARD_EDGE,
                         highlightthickness=1)
        self.accent = accent

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(head, text=name, bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        tk.Label(head, text=subtitle, bg=CARD, fg=FAINT,
                 font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(8, 0), pady=(3, 0))
        tk.Label(head, text=code, bg=CARD, fg=FAINT,
                 font=("Consolas", 9)).pack(side="right", pady=(3, 0))

        self.percent_label = tk.Label(self, text="--", bg=CARD, fg=TEXT,
                                      font=("Microsoft YaHei UI", 58, "bold"))
        self.percent_label.pack(pady=(12, 0))

        self.state_label = tk.Label(self, text="正在连接…", bg=CARD, fg=SUB,
                                    font=("Microsoft YaHei UI", 10))
        self.state_label.pack(pady=(0, 10))

        self.bar = tk.Canvas(self, width=360, height=13, bg=CARD,
                             highlightthickness=0)
        self.bar.pack()
        self.bar.create_rectangle(0, 0, 360, 13, fill="#242a35", outline="")
        self._bar_fill = self.bar.create_rectangle(0, 0, 0, 13, fill=accent, outline="")

        info = tk.Frame(self, bg=CARD)
        info.pack(fill="x", padx=22, pady=(16, 4))
        self.info_values = []
        for i in range(3):
            box = tk.Frame(info, bg=CARD)
            box.grid(row=0, column=i, sticky="nsew")
            info.grid_columnconfigure(i, weight=1)
            lab = tk.Label(box, text="—", bg=CARD, fg=FAINT,
                           font=("Microsoft YaHei UI", 8))
            lab.pack()
            val = tk.Label(box, text="--", bg=CARD, fg=TEXT,
                           font=("Microsoft YaHei UI", 10, "bold"))
            val.pack(pady=(2, 0))
            self.info_values.append((lab, val))

        self.time_label = tk.Label(self, text="", bg=CARD, fg=FAINT,
                                   font=("Microsoft YaHei UI", 8))
        self.time_label.pack(pady=(16, 14))

    def update_reading(self, percent: int, state: str, color: str,
                       info: list[tuple[str, str]], time_text: str):
        self.percent_label.configure(text=f"{percent}%", fg=color)
        self.state_label.configure(text=state, fg=color if state.startswith("⚡") else SUB)
        self.bar.coords(self._bar_fill, 0, 0, 360 * percent / 100.0, 13)
        self.bar.itemconfigure(self._bar_fill, fill=color)
        for (label, value), (lab_w, val_w) in zip(info, self.info_values):
            lab_w.configure(text=label)
            val_w.configure(text=value)
        self.time_label.configure(text=time_text)

    def update_error(self, message: str, hint: str = ""):
        self.percent_label.configure(text="--", fg=FAINT)
        self.state_label.configure(text=message, fg=RED)
        self.bar.coords(self._bar_fill, 0, 0, 0, 13)
        for lab_w, val_w in self.info_values:
            val_w.configure(text="--")
        self.time_label.configure(text=hint, fg=FAINT)


class BatteryPanel(tk.Tk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self._busy = False
        self._closing = False
        self._after_id = None
        self._queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()
        self._demo_percent = 47
        self._tray_checked = False
        cfg = tc.load_config()
        self._initial_interval = int(cfg.get("interval", 60) or 60)
        self.autostart_var = tk.BooleanVar(value=tc.is_autostart_enabled())

        self.title("外设电量")
        self.configure(bg=BG)
        self.geometry("940x560")
        self.minsize(900, 540)
        self.resizable(True, True)
        self._center()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._pump)
        self.after(200, self.refresh)
        if not demo:
            self.after(500, self._ensure_tray)

    def _center(self):
        self.update_idletasks()
        w, h = 940, 560
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

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 6))
        tk.Label(header, text="外设电量", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        tk.Label(header, text="本机 HID 读取 · 自动刷新", bg=BG, fg=FAINT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0), pady=(4, 0))

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        cards.grid_columnconfigure(0, weight=1, uniform="card")
        cards.grid_columnconfigure(1, weight=1, uniform="card")
        cards.grid_rowconfigure(0, weight=1)

        self.mouse_card = DeviceCard(
            cards, "EWEADN 8K", "S9 V2 Master · 匠盟", "3554:F517", ACCENT)
        self.mouse_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.kb_card = DeviceCard(
            cards, "PMO WAVE75", "75% RGB · 三模", "36B0:3002", ACCENT_KB)
        self.kb_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

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

        self.interval_var = tk.StringVar(value=interval_label(self._initial_interval))
        combo = ttk.Combobox(controls, textvariable=self.interval_var,
                             values=list(INTERVALS), state="readonly", width=7,
                             font=("Microsoft YaHei UI", 9))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_interval_changed())

        tk.Checkbutton(
            controls, text="开机自启", variable=self.autostart_var, bg=BG, fg=SUB,
            selectcolor=BG, activebackground=BG, activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
            command=self._toggle_autostart).pack(side="left", padx=(14, 8))

        tk.Button(controls, text="桌面链接", command=self._desktop_links,
                  bg="#242a35", fg=SUB, activebackground="#2d3543",
                  activeforeground=TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=(0, 6))

        tk.Button(controls, text="退出托盘", command=self._quit_tray,
                  bg="#242a35", fg=SUB, activebackground="#2d3543",
                  activeforeground=TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=10, pady=3,
                  cursor="hand2").pack(side="left")

        self.status_dot = tk.Label(controls, text="●", bg=BG, fg=FAINT,
                                   font=("Microsoft YaHei UI", 9))
        self.status_dot.pack(side="right", padx=(0, 4))
        self.status_label = tk.Label(controls, text="", bg=BG, fg=FAINT,
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side="right")

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
        result = {"mouse": None, "kb": None, "mouse_err": None, "kb_err": None}
        try:
            result["mouse"] = mouse_proto.read_battery(retries=2)
        except mouse_proto.EweadnError as exc:
            result["mouse_err"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            result["mouse_err"] = f"未知错误：{exc}"
        try:
            result["kb"] = kb_proto.read_battery(retries=2)
        except kb_proto.PmoError as exc:
            result["kb_err"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            result["kb_err"] = f"未知错误：{exc}"
        self._queue.put(result)

    def _demo_result(self):
        self._demo_percent = 85 if self._demo_percent == 47 else 47
        mouse = mouse_proto.BatteryReading(
            percent=self._demo_percent, level_raw=self._demo_percent,
            charging=False, voltage_mv=4040, online=True,
            percent_source="voltage")
        kb = kb_proto.KeyboardBattery(
            percent=65 if self._demo_percent == 85 else 35, charging=0, link=0,
            raw=b"", dongle=True, timestamp=time.time())
        self._queue.put({"mouse": mouse, "kb": kb, "mouse_err": None, "kb_err": None})

    def _pump(self):
        if self._closing:
            return
        try:
            while True:
                result = self._queue.get_nowait()
                self._apply(result)
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "status":
                    self.status_label.configure(text=payload, fg=FAINT)
                    self.status_dot.configure(fg=GREEN if "已" in payload else RED)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _apply(self, result):
        self._busy = False
        self.refresh_btn.configure(state="normal", text="立即刷新")
        stamp = time.strftime("%H:%M:%S")

        mouse = result.get("mouse")
        if mouse:
            color = level_color(mouse.percent)
            self.mouse_card.update_reading(
                mouse.percent,
                "⚡ 充电中" if mouse.charging else "已连接 · 无线使用中",
                color,
                [("电压", f"{mouse.voltage_v:.3f} V"),
                 ("状态", "充电中" if mouse.charging else "未充电"),
                 ("设备自报", f"{mouse.level_raw}%")],
                f"更新于 {stamp} · HID 0xFF02/0x0002")
        else:
            msg = (result.get("mouse_err") or "读取失败").splitlines()[0]
            self.mouse_card.update_error(
                _short_mouse(msg),
                "动一下鼠标或按一下按键唤醒" if "休眠" in msg or "未连接" in msg else "")

        kb = result.get("kb")
        if kb:
            color = level_color(kb.percent)
            self.kb_card.update_reading(
                kb.percent,
                "⚡ 充电中" if kb.charging == 1 else (
                    "已充满" if kb.charging == 2 else "已连接 · 2.4G" if kb.dongle else "已连接 · USB"),
                color,
                [("连接", "2.4G" if kb.dongle else "USB"),
                 ("充电", kb.charging_text),
                 ("协议", "RDR AA 30")],
                f"更新于 {stamp} · HID 0xFF60/0x0061")
        else:
            msg = (result.get("kb_err") or "读取失败").splitlines()[0]
            self.kb_card.update_error(_short_kb(msg), "键盘休眠或当前固件不支持")

        any_ok = bool(mouse or kb)
        any_err = bool(result.get("mouse_err") or result.get("kb_err"))
        if any_ok:
            self.status_dot.configure(fg=GREEN if not any_err else AMBER)
            self.status_label.configure(text=f"已更新 {stamp}", fg=FAINT)
        else:
            self.status_dot.configure(fg=RED)
            self.status_label.configure(text="设备暂时没有响应", fg=RED)
        self._schedule_next()

    def _ensure_tray(self):
        if self._tray_checked:
            return
        self._tray_checked = True
        if tc.is_tray_running():
            self._ui_queue.put(("status", "托盘已在运行"))
            return

        def worker():
            ok = tc.start_tray_app()
            self._ui_queue.put(("status", "托盘已启动" if ok else "托盘启动失败"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_interval_changed(self):
        seconds = INTERVALS.get(self.interval_var.get(), 60)
        cfg = tc.load_config()
        cfg["interval"] = seconds
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)
        self._schedule_next()

    def _toggle_autostart(self):
        try:
            tc.set_autostart(bool(self.autostart_var.get()))
        except Exception as exc:  # noqa: BLE001
            self.status_label.configure(text=f"开机自启设置失败：{exc}", fg=RED)
        actual = tc.is_autostart_enabled()
        self.autostart_var.set(actual)
        self.status_label.configure(
            text="开机自启已开启" if actual else "开机自启已关闭",
            fg=GREEN if actual else FAINT)

    def _desktop_links(self):
        result = tc.install_desktop_links()
        errors = result.get("errors") or []
        if errors:
            self.status_label.configure(text=f"桌面链接：{errors[0]}", fg=RED)
        else:
            self.status_label.configure(text="桌面链接已创建（目录 + 启动脚本）", fg=GREEN)

    def _quit_tray(self):
        ok = tc.post_to_tray(tc.MSG_QUIT)
        self.status_label.configure(
            text="已通知托盘退出" if ok else "托盘没在运行",
            fg=FAINT if ok else RED)

    def _schedule_next(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._closing or not self.auto_var.get():
            return
        seconds = INTERVALS.get(self.interval_var.get(), 60)
        self._after_id = self.after(seconds * 1000, self.refresh)

    def _on_close(self):
        self._closing = True
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
        self.destroy()


def _short_mouse(message: str) -> str:
    if "休眠" in message or "未连接" in message:
        return "鼠标休眠"
    if "独占" in message:
        return "接口被占用"
    if "没有找到" in message:
        return "未找到鼠标"
    return message[:12]


def _short_kb(message: str) -> str:
    if "QMK" in message:
        return "需 PMO 固件"
    if "2.4G dongle" in message or "USB 线" in message:
        return "请用 USB 连接"
    if "没有找到" in message:
        return "未找到键盘"
    if "没有响应" in message:
        return "键盘休眠"
    return message[:12]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="外设电量面板（鼠标 + 键盘）")
    parser.add_argument("--demo", action="store_true", help="用演示数据预览界面")
    args = parser.parse_args(argv)
    app = BatteryPanel(demo=args.demo)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
