# -*- coding: utf-8 -*-
"""battery_panel.py —— 外设电量面板（设备卡片可选 / 托盘图标独立设置）。

刷新链路：device_registry.snapshot() -> DeviceCard.update()
设置窗口：设备卡片/托盘图标、常驻托盘、开机自启、刷新间隔、工具入口。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import device_registry as dr
import generic_protocols as gp
import tray_common as tc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BG = "#0f1115"
CARD = "#171a21"
CARD_EDGE = "#252b37"
TRACK = "#2a303c"
TEXT = "#f5f7fa"
SUB = "#a3aab8"
FAINT = "#6f7788"
GREEN = "#5ddc8a"
AMBER = "#f5c451"
RED = "#ff6b6b"
MUTED = "#7d8499"

INTERVALS = {"30 秒": 30, "60 秒": 60, "2 分钟": 120, "5 分钟": 300,
             "10 分钟": 600, "30 分钟": 1800}


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


# --------------------------------------------------------------------------
# 统一设备卡片
# --------------------------------------------------------------------------


class DeviceCard(tk.Frame):
    """所有设备共用同一套字段：连接 / 充电 / 电压 / 数据源。"""

    def __init__(self, parent, snap: dr.DeviceSnapshot):
        super().__init__(parent, bg=CARD, width=440, height=205,
                         highlightbackground=CARD_EDGE, highlightthickness=1)
        self.grid_propagate(False)
        self.key = snap.key

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x", padx=16, pady=(12, 0))
        self.name_label = tk.Label(head, text=snap.name, bg=CARD, fg=TEXT,
                                   font=("Microsoft YaHei UI", 13, "bold"),
                                   anchor="w")
        self.name_label.pack(side="left")
        self.status_label = tk.Label(head, text="", bg=CARD, fg=FAINT,
                                     font=("Microsoft YaHei UI", 9), anchor="e")
        self.status_label.pack(side="right")

        self.sub_label = tk.Label(self, text=snap.subtitle, bg=CARD, fg=FAINT,
                                  font=("Consolas", 8), anchor="w")
        self.sub_label.pack(fill="x", padx=16, pady=(2, 0))

        body = tk.Frame(self, bg=CARD)
        body.pack(fill="x", padx=16, pady=(4, 0))
        self.percent_label = tk.Label(body, text="--", bg=CARD, fg=MUTED,
                                      font=("Microsoft YaHei UI", 40, "bold"),
                                      width=5, anchor="w")
        self.percent_label.pack(side="left", anchor="n")

        right = tk.Frame(body, bg=CARD)
        right.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.bar = tk.Canvas(right, width=250, height=12, bg=TRACK,
                             highlightthickness=0)
        self.bar.pack(fill="x", pady=(14, 6))
        self.bar_fill = self.bar.create_rectangle(0, 0, 0, 12, fill=TRACK,
                                                  outline="")
        self.hint = tk.Label(right, text="", bg=CARD, fg=FAINT,
                             font=("Microsoft YaHei UI", 8), anchor="w")
        self.hint.pack(fill="x")

        info = tk.Frame(self, bg=CARD)
        info.pack(fill="x", padx=16, pady=(4, 0))
        self.info_values = {}
        for label in ("连接", "充电", "电压", "数据源"):
            cell = tk.Frame(info, bg=CARD)
            cell.pack(side="left", expand=True, fill="x")
            tk.Label(cell, text=label, bg=CARD, fg=FAINT,
                     font=("Microsoft YaHei UI", 8), anchor="w").pack(fill="x")
            val = tk.Label(cell, text="—", bg=CARD, fg=SUB,
                           font=("Microsoft YaHei UI", 9, "bold"), anchor="w")
            val.pack(fill="x")
            self.info_values[label] = val

        self.time_label = tk.Label(self, text="", bg=CARD, fg=FAINT,
                                   font=("Microsoft YaHei UI", 8), anchor="w")
        self.time_label.pack(fill="x", padx=16, pady=(4, 0))

    def update_reading(self, snap: dr.DeviceSnapshot) -> None:
        self.key = snap.key
        self.name_label.configure(text=snap.name)
        self.sub_label.configure(
            text=f"{snap.key} · {snap.source or '等待设备'}")
        if snap.present:
            if snap.charging is True:
                state, color = "充电中", GREEN
            elif snap.status == "full":
                state, color = "已充满", GREEN
            elif snap.status == "wired":
                state, color = "有线连接", GREEN
            else:
                state, color = "已连接", FAINT
        elif snap.stale:
            stamp = time.strftime("%H:%M", time.localtime(snap.updated))
            state, color = f"休眠 · 上次更新 {stamp}", AMBER
        else:
            state, color = "未连接", RED if snap.show else FAINT
        self.status_label.configure(text=state, fg=color)

        pct = snap.percent
        if pct is None:
            self.percent_label.configure(text="--", fg=MUTED)
            self.bar.coords(self.bar_fill, 0, 0, 0, 12)
            self.bar.itemconfigure(self.bar_fill, fill=TRACK)
        else:
            color = MUTED if (snap.stale or not snap.present) else level_color(pct)
            self.percent_label.configure(text=f"{pct}%", fg=color)
            self.bar.coords(self.bar_fill, 0, 0, max(1, 250 * pct / 100), 12)
            self.bar.itemconfigure(self.bar_fill,
                                   fill=color if not snap.stale else "#5d6675")
        self.hint.configure(
            text=("缓存值 · 设备唤醒后自动更新" if snap.stale else
                  "只读查询 · 不修改设备设置" if snap.present else
                  "设备暂时不在线"))
        self.info_values["连接"].configure(text=snap.link or "—")
        self.info_values["充电"].configure(text=snap.charging_text)
        self.info_values["电压"].configure(
            text=f"{snap.voltage_mv / 1000:.3f} V" if snap.voltage_mv else "—")
        self.info_values["数据源"].configure(text=snap.source or "—")
        self.time_label.configure(text=snap.updated_text)


# --------------------------------------------------------------------------
# 主面板
# --------------------------------------------------------------------------


class BatteryPanel(tk.Tk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.title(tc.UI_TITLE)
        self.geometry("940x700")
        self.minsize(880, 620)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()
        self._busy = False
        self._pending_refresh = False
        self._closing = False
        self._after_id = None
        self._pump_id = None
        self._poll_id = None
        self._timers = set()
        self.snapshots: list[dr.DeviceSnapshot] = []
        self.cards: dict[str, DeviceCard] = {}
        self._tool_pids: set[int] = set()
        self._demo_snaps = self._make_demo()

        self.auto_var = tk.BooleanVar(value=True)
        self._build_ui()
        user32 = ctypes.windll.user32
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        self._hwnd = int(user32.GetAncestor(
            ctypes.c_void_p(self.winfo_id()), 2) or 0)
        tc.write_panel_hwnd(self._hwnd)
        self._hidden = False
        self._hiding = False
        self._hide_pending = False
        self._tray_stopping = False
        self._tray_notice_until = 0.0
        self._pending_close_action = None
        self._poll_id = self._later(300, self._poll_show)
        self._pump_id = self._later(100, self._pump)
        self.bind("<Unmap>", self._on_unmap)
        if demo:
            self._apply_snaps(self._demo_snaps)
        else:
            self._later(150, self.refresh)
            self._later(400, self._update_tray_button)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(head, text="外设电量", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left")
        tk.Label(head, text="可选设备卡片 · 每设备独立托盘图标",
                 bg=BG, fg=FAINT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left",
                                                      padx=(12, 0), pady=(6, 0))
        tk.Button(head, text="⚙ 设置", command=self._open_settings,
                  bg="#242a35", fg=SUB, activebackground="#2d3543",
                  activeforeground=TEXT, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                  cursor="hand2").pack(side="right")

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=14, pady=(4, 0))
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self.scroll = ttk.Scrollbar(wrap, orient="vertical",
                                    command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._scroll_visible = False
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.scroll.grid_remove()

        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner,
                                                  anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all(
            "<MouseWheel>", self._on_wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all(
            "<MouseWheel>"))
        self.inner.grid_columnconfigure(0, weight=1)
        self.inner.grid_columnconfigure(1, weight=1)

        self.empty_label = tk.Label(
            self.inner, text="没有勾选任何设备卡片\n点右上角「⚙ 设置」选择要显示的设备",
            bg=BG, fg=FAINT, justify="center",
            font=("Microsoft YaHei UI", 11))

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=(6, 10))
        self.refresh_btn = tk.Button(
            bar, text="立即刷新", command=self.refresh, bg="#4f8cff", fg="white",
            activebackground="#6aa0ff", activeforeground="white", relief="flat",
            bd=0, font=("Microsoft YaHei UI", 9, "bold"), padx=16, pady=5,
            cursor="hand2")
        self.refresh_btn.pack(side="left")
        tk.Checkbutton(
            bar, text="自动刷新", variable=self.auto_var, bg=BG, fg=SUB,
            selectcolor=BG, activebackground=BG, activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
            command=self._schedule_next).pack(side="left", padx=(14, 0))
        self.tray_btn = tk.Button(
            bar, text="常驻托盘", command=self._toggle_tray,
            bg="#1f8f4e", fg="white", activebackground="#2ecc71",
            activeforeground="white", relief="flat", bd=0,
            font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=5,
            cursor="hand2")
        self.tray_btn.pack(side="left", padx=(14, 0))
        self.status_dot = tk.Label(bar, text="●", bg=BG, fg=FAINT,
                                   font=("Microsoft YaHei UI", 9))
        self.status_dot.pack(side="right", padx=(0, 5))
        self.status_label = tk.Label(bar, text="准备就绪", bg=BG, fg=FAINT,
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side="right")

    def _on_inner_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar_visibility()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)
        self._update_scrollbar_visibility()

    def _update_scrollbar_visibility(self):
        """滚动条只在内容高度超过可视区域时出现。"""
        try:
            if not self.winfo_exists():
                return
            bbox = self.canvas.bbox("all")
            view_h = self.canvas.winfo_height()
            content_h = (bbox[3] - bbox[1]) if bbox else 0
            need = content_h > view_h + 1
            if need == self._scroll_visible:
                return
            self._scroll_visible = need
            if need:
                self.scroll.grid()
            else:
                self.scroll.grid_remove()
                self.canvas.yview_moveto(0)
        except tk.TclError:
            pass

    def _on_wheel(self, event):
        if self._scroll_visible:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ------------------------------------------------------------- 刷新
    def refresh(self):
        if self.demo:
            self._apply_snaps(self._demo_snaps)
            return
        if self._busy or self._closing:
            return
        self._busy = True
        self.refresh_btn.configure(state="disabled", text="读取中…")
        self.status_label.configure(text="正在读取设备…", fg=FAINT)
        self.status_dot.configure(fg=AMBER)

        def worker():
            try:
                snaps = dr.snapshot(fast=True)
            except Exception as exc:  # noqa: BLE001
                self._queue.put(("error", str(exc)))
            else:
                self._queue.put(("snaps", snaps))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        if self._closing:
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "snaps":
                    self._apply_snaps(payload)
                else:
                    self._busy = False
                    self.refresh_btn.configure(state="normal", text="立即刷新")
                    self.status_label.configure(text=f"读取失败：{payload}", fg=RED)
                    self.status_dot.configure(fg=RED)
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "tray":
                    self._busy = False
                    if payload:
                        self._tray_stopping = False
                        self._tray_notice_until = 0.0
                    self.status_label.configure(
                        text="托盘已启动" if payload else "托盘启动失败",
                        fg=GREEN if payload else RED)
                    self._update_tray_button()
                elif kind == "tray_then_hide":
                    if payload:
                        self._update_tray_button()
                        self._hide_now()
                    else:
                        self._hiding = False
                        self.status_label.configure(text="托盘启动失败，无法最小化",
                                                    fg=RED)
                        self.status_dot.configure(fg=RED)
                elif kind == "tray_for_close":
                    mode = self._pending_close_action or "current"
                    self._pending_close_action = None
                    if payload:
                        self._update_tray_button()
                    self._perform_close(mode)
                elif kind == "settings":
                    self.status_label.configure(text=payload, fg=FAINT)
        except queue.Empty:
            pass
        self._pump_id = self._later(100, self._pump)

    def _apply_snaps(self, snaps):
        self._busy = False
        self.refresh_btn.configure(state="normal", text="立即刷新")
        self.snapshots = snaps
        self._sync_cards()
        stamp = time.strftime("%H:%M:%S")
        visible = sum(1 for s in snaps if s.show)
        if time.monotonic() >= self._tray_notice_until:
            self.status_label.configure(text=f"已更新 {stamp} · {visible} 张卡片",
                                        fg=FAINT)
            self.status_dot.configure(fg=GREEN)
        self._schedule_next()
        if self._pending_refresh:
            self._pending_refresh = False
            self._later(100, self.refresh)

    def _sync_cards(self):
        visible = [s for s in self.snapshots if s.show]
        wanted = {s.key for s in visible}
        for key in list(self.cards):
            if key not in wanted:
                self.cards.pop(key).destroy()
        for i, snap in enumerate(visible):
            card = self.cards.get(snap.key)
            if card is None:
                card = DeviceCard(self.inner, snap)
                self.cards[snap.key] = card
            card.update_reading(snap)
            card.grid_configure(row=i // 2, column=i % 2, padx=6, pady=6,
                                sticky="nsew")
        if visible:
            self.empty_label.grid_forget()
        else:
            self.empty_label.grid(row=0, column=0, columnspan=2, pady=80)
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar_visibility()

    def _schedule_next(self):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._closing or self.demo or not self.auto_var.get():
            return
        seconds = int(tc.load_config().get("interval", 60) or 60)
        self._after_id = self._later(max(10, seconds) * 1000, self.refresh)

    # ------------------------------------------------------------- 托盘
    def _update_tray_button(self):
        running = tc.is_tray_running()
        if running:
            self.tray_btn.configure(
                text="退出托盘", bg="#5a2328", fg="#ffb4b4",
                activebackground="#7a2d34", activeforeground="white")
            self.status_dot.configure(fg=GREEN)
            if self._tray_stopping:
                self.status_label.configure(text="托盘仍在运行", fg=AMBER)
        else:
            self.tray_btn.configure(
                text="常驻托盘", bg="#1f8f4e", fg="white",
                activebackground="#2ecc71", activeforeground="white")
            if self._tray_stopping:
                self._tray_stopping = False
                self._tray_notice_until = time.monotonic() + 3.0
                self.status_label.configure(text="托盘已退出", fg=FAINT)
                self.status_dot.configure(fg=FAINT)

    def _toggle_tray(self):
        if tc.is_tray_running():
            tc.post_to_tray(tc.MSG_QUIT)
            self._tray_stopping = True
            self.status_label.configure(text="正在退出托盘…", fg=FAINT)
            self._later(900, self._update_tray_button)
            self._later(2200, self._update_tray_button)
            return

        self._tray_stopping = False
        self._tray_notice_until = 0.0
        def worker():
            ok = tc.start_tray_app()
            self._ui_queue.put(("tray", ok))

        threading.Thread(target=worker, daemon=True).start()
        self._later(800, self._update_tray_button)
        self._later(2200, self._update_tray_button)

    def _on_unmap(self, _event=None):
        """标题栏最小化：按设置缩到托盘，或正常收起到任务栏。"""
        if self._closing or self._hidden or self._hide_pending:
            return
        mode = tc.load_config().get("window", {}).get("minimize", "tray")
        if mode != "tray":
            return
        try:
            if self.state() == "iconic":
                self._hide_pending = True
                self._later(10, self._deferred_hide)
        except tk.TclError:
            pass

    def _deferred_hide(self):
        self._hide_pending = False
        if not self._closing and not self._hidden:
            self._hide_to_tray()

    def _hide_to_tray(self):
        if self._closing or self._hiding or self._hidden:
            return
        self._hiding = True
        if tc.is_tray_running():
            self._hide_now()
            return
        self.status_label.configure(text="正在启动常驻托盘…", fg=FAINT)
        self.status_dot.configure(fg=AMBER)

        def worker():
            ok = tc.start_tray_app()
            self._ui_queue.put(("tray_then_hide", ok))

        threading.Thread(target=worker, daemon=True).start()

    def _hide_now(self):
        # 先标记 hidden，再 withdraw：避免 withdraw 产生的 <Unmap>
        # 再次触发最小化/启动托盘，造成重复图标。
        self._hidden = True
        self._hiding = False
        tc.write_panel_hwnd(self._hwnd)
        self.withdraw()

    def _poll_show(self):
        if self._closing:
            return
        if tc.consume_panel_show():
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
                self._hidden = False
            except tk.TclError:
                pass
        action = tc.consume_app_action()
        if action == "all":
            self._close_all_visible()
            return
        if action == "exit":
            self._exit_app(ask=False)
            return
        self._poll_id = self._later(300, self._poll_show)

    # ------------------------------------------------------------- 设置
    def _open_settings(self):
        SettingsWindow(self, demo=self.demo, on_change=self._settings_changed)

    def _settings_changed(self):
        self._apply_config_flags()
        if not self.demo:
            if self._busy:
                self._pending_refresh = True
            else:
                self._later(120, self.refresh)
        self._update_tray_button()

    def _apply_config_flags(self):
        """设置里改卡片/托盘开关后，立即反映到已经渲染的卡片，不必等扫描。"""
        meta = {d["key"]: d for d in dr.known_devices()}
        for snap in self.snapshots:
            m = meta.get(snap.key)
            if not m:
                continue
            snap.show = bool(m["show"])
            snap.tray = bool(m["tray"])
        self._sync_cards()

    # ------------------------------------------------------------- 退出
    def _close_all_visible(self):
        """关闭主面板、设置/弹窗，以及由本应用打开的工具窗口；托盘保留。"""
        self._stop_tools()
        for child in list(self.winfo_children()):
            if isinstance(child, tk.Toplevel):
                try:
                    child.destroy()
                except tk.TclError:
                    pass
        self._on_close()

    def _visible_toplevels(self):
        out = []
        for child in self.winfo_children():
            if not isinstance(child, tk.Toplevel):
                continue
            try:
                if child.winfo_exists() and child.winfo_viewable():
                    out.append(child)
            except tk.TclError:
                pass
        return out

    def _is_last_window(self) -> bool:
        """托盘未运行时判断：当前是不是最后一个可见的应用窗口。"""
        if any(tc.pid_alive(pid) for pid in self._tool_pids):
            return False
        return not self._visible_toplevels()

    def _perform_close(self, mode: str):
        if not tc.is_tray_running() and self._is_last_window():
            self._exit_app(ask=False)
            return
        if mode == "all":
            self._close_all_visible()
        else:
            self._on_close()

    def _on_window_close(self):
        mode = tc.load_config().get("window", {}).get("close", "current")
        if mode == "exit":
            self._exit_app()
            return
        if tc.is_tray_running():
            self._perform_close(mode)
            return

        keep = messagebox.askyesno(
            "常驻托盘",
            "托盘当前没有运行。\n\n是否启动常驻托盘？\n"
            "选择「否」且这是最后一个窗口时，将完全退出应用。",
            parent=self)
        if not keep:
            self._perform_close(mode)
            return
        self._pending_close_action = mode
        self.status_label.configure(text="正在启动常驻托盘…", fg=FAINT)

        def worker():
            ok = tc.start_tray_app()
            self._ui_queue.put(("tray_for_close", ok))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_tools(self):
        for pid in list(self._tool_pids):
            try:
                if tc.pid_alive(pid):
                    tc.kill_pid(pid)
            except Exception:
                pass
            self._tool_pids.discard(pid)

    def _later(self, ms, func):
        aid = self.after(ms, func)
        self._timers.add(aid)
        return aid

    def _cancel_after(self):
        for name in ("_after_id", "_pump_id", "_poll_id"):
            aid = getattr(self, name, None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        for aid in list(self._timers):
            try:
                self.after_cancel(aid)
            except tk.TclError:
                pass
        self._timers.clear()

    def _exit_app(self, ask: bool = True):
        if ask and not messagebox.askyesno(
                "退出应用",
                "将退出托盘、本面板，以及由本应用打开的测试/调试窗口。\n\n"
                "确定要完全退出吗？",
                parent=self):
            return
        self._closing = True
        self._cancel_after()
        self._stop_tools()
        if tc.is_tray_running():
            tc.post_to_tray(tc.MSG_QUIT)
            end = time.monotonic() + 2.0
            while time.monotonic() < end and tc.is_tray_running():
                time.sleep(0.1)
            if tc.is_tray_running():
                tc.force_kill_tray()
        tc.clear_panel_hwnd(self._hwnd)
        tc.consume_panel_show()
        self.destroy()

    def _on_close(self):
        self._closing = True
        self._cancel_after()
        tc.clear_panel_hwnd(self._hwnd)
        tc.consume_panel_show()
        self.destroy()

    # ------------------------------------------------------------- demo
    @staticmethod
    def _make_demo() -> list[dr.DeviceSnapshot]:
        now = time.time()
        return [
            dr.DeviceSnapshot(
                key="3554:F517", name="EWEADN 8K", vid=0x3554, pid=0xF517,
                percent=85, charging=False, status="discharging",
                voltage_mv=4040, source="EWEADN", link="2.4G",
                detail="设备自报 85%", updated=now, stale=False,
                present=True, show=True, tray=True),
            dr.DeviceSnapshot(
                key="36B0:WAVE75", name="PMO WAVE75", vid=0x36B0, pid=0x3002,
                percent=65, charging=False, status="discharging",
                voltage_mv=None, source="PMO RDR", link="2.4G",
                detail="未充电", updated=now, stale=False,
                present=True, show=True, tray=True),
            dr.DeviceSnapshot(
                key="046D:C53F", name="罗技 G304 / Lightspeed",
                vid=0x046D, pid=0xC53F, percent=90, charging=False,
                status="discharging", voltage_mv=None, source="罗技 HID++",
                link="HID++", detail="设备索引 1", updated=now,
                stale=False, present=True, show=True, tray=True),
        ]


# --------------------------------------------------------------------------
# 设置窗口
# --------------------------------------------------------------------------


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: BatteryPanel, demo: bool = False,
                 on_change=None):
        super().__init__(parent)
        self.parent = parent
        self.demo = demo
        self.on_change = on_change
        self.title(f"{tc.UI_TITLE} · 设置")
        self.geometry("660x860")
        self.minsize(620, 700)
        self.configure(bg=BG)
        self.transient(parent)
        self.device_vars = []
        self._timer_id = None
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._build()

    def destroy(self):
        if self._timer_id is not None:
            try:
                self.after_cancel(self._timer_id)
            except tk.TclError:
                pass
            self._timer_id = None
        super().destroy()

    def _on_window_close(self):
        mode = tc.load_config().get("window", {}).get("close", "current")
        if mode == "exit":
            self.parent._exit_app()
        elif mode == "all":
            self.parent._close_all_visible()
        else:
            self.destroy()

    def _close_dialog(self, win):
        mode = tc.load_config().get("window", {}).get("close", "current")
        if mode == "exit":
            self.parent._exit_app()
        elif mode == "all":
            self.parent._close_all_visible()
        else:
            win.destroy()

    def _build(self):
        tk.Label(self, text="设置", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(
            anchor="w", padx=18, pady=(14, 4))
        tk.Label(self, text="设备卡片 / 托盘图标 / 窗口按钮 / 启动与工具",
                 bg=BG, fg=FAINT,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(8, 0))

        # 设备
        dev_box = tk.LabelFrame(body, text=" 设备卡片与托盘图标 ",
                                bg=BG, fg=SUB, bd=0,
                                font=("Microsoft YaHei UI", 9, "bold"))
        dev_box.pack(fill="x", pady=(0, 8))
        self.dev_list = tk.Frame(dev_box, bg=BG)
        self.dev_list.pack(fill="x", padx=8, pady=6)
        tk.Button(dev_box, text="扫描并刷新列表", command=self._rescan_devices,
                  bg="#242a35", fg=SUB, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=10, pady=3,
                  cursor="hand2").pack(anchor="w", padx=8, pady=(0, 8))
        self._reload_devices()

        # 托盘
        tray_box = tk.LabelFrame(body, text=" 常驻托盘 ", bg=BG, fg=SUB, bd=0,
                                 font=("Microsoft YaHei UI", 9, "bold"))
        tray_box.pack(fill="x", pady=(0, 8))
        row = tk.Frame(tray_box, bg=BG)
        row.pack(fill="x", padx=8, pady=8)
        self.tray_btn = tk.Button(
            row, text="启动常驻托盘", command=self._toggle_tray,
            bg="#1f8f4e", fg="white", relief="flat", bd=0,
            font=("Microsoft YaHei UI", 9, "bold"), padx=12, pady=4,
            cursor="hand2")
        self.tray_btn.pack(side="left")
        self.tray_state = tk.Label(row, text="", bg=BG, fg=FAINT,
                                   font=("Microsoft YaHei UI", 9))
        self.tray_state.pack(side="left", padx=(10, 0))
        self._refresh_tray_state()

        # 启动
        boot_box = tk.LabelFrame(body, text=" 开机与入口 ", bg=BG, fg=SUB, bd=0,
                                 font=("Microsoft YaHei UI", 9, "bold"))
        boot_box.pack(fill="x", pady=(0, 8))
        row = tk.Frame(boot_box, bg=BG)
        row.pack(fill="x", padx=8, pady=8)
        self.autostart_var = tk.BooleanVar(value=tc.is_autostart_enabled())
        tk.Checkbutton(
            row, text="开机自启", variable=self.autostart_var, bg=BG, fg=SUB,
            selectcolor=BG, activebackground=BG, activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9), bd=0, highlightthickness=0,
            command=self._toggle_autostart).pack(side="left")
        tk.Button(row, text="创建桌面链接", command=self._desktop_links,
                  bg="#242a35", fg=SUB, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=10, pady=3,
                  cursor="hand2").pack(side="left", padx=(12, 0))
        self.boot_msg = tk.Label(boot_box, text="", bg=BG, fg=FAINT,
                                 font=("Microsoft YaHei UI", 8), anchor="w")
        self.boot_msg.pack(fill="x", padx=8, pady=(0, 6))

        # 刷新
        refresh_box = tk.LabelFrame(body, text=" 刷新 ", bg=BG, fg=SUB, bd=0,
                                    font=("Microsoft YaHei UI", 9, "bold"))
        refresh_box.pack(fill="x", pady=(0, 8))
        row = tk.Frame(refresh_box, bg=BG)
        row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="托盘/面板间隔", bg=BG, fg=SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.interval_var = tk.StringVar(
            value=interval_label(int(tc.load_config().get("interval", 60) or 60)))
        combo = ttk.Combobox(row, textvariable=self.interval_var, width=8,
                             values=list(INTERVALS), state="readonly",
                             font=("Microsoft YaHei UI", 9))
        combo.pack(side="left", padx=(8, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self._interval_changed())

        # 窗口按钮行为
        win_box = tk.LabelFrame(body, text=" 标题栏按钮 ", bg=BG, fg=SUB, bd=0,
                                font=("Microsoft YaHei UI", 9, "bold"))
        win_box.pack(fill="x", pady=(0, 8))
        win_cfg = tc.load_config().get("window", {})
        self.min_mode = tk.StringVar(
            value=win_cfg.get("minimize", "tray"))
        self.close_mode = tk.StringVar(
            value=win_cfg.get("close", "current"))
        row = tk.Frame(win_box, bg=BG)
        row.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(row, text="最小化（-）", bg=BG, fg=SUB, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(side="left")
        for text, value in (("最小化到托盘", "tray"),
                            ("正常收起窗口", "taskbar")):
            tk.Radiobutton(
                row, text=text, variable=self.min_mode, value=value,
                bg=BG, fg=SUB, selectcolor=BG, activebackground=BG,
                activeforeground=TEXT, font=("Microsoft YaHei UI", 9),
                bd=0, highlightthickness=0,
                command=self._save_window_behavior).pack(side="left",
                                                         padx=(0, 10))
        row = tk.Frame(win_box, bg=BG)
        row.pack(fill="x", padx=8, pady=(2, 8))
        tk.Label(row, text="关闭（×）", bg=BG, fg=SUB, width=11,
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(side="left")
        for text, value in (("仅关闭主界面", "current"),
                            ("关闭所有可见窗口", "all"),
                            ("完全退出应用", "exit")):
            tk.Radiobutton(
                row, text=text, variable=self.close_mode, value=value,
                bg=BG, fg=SUB, selectcolor=BG, activebackground=BG,
                activeforeground=TEXT, font=("Microsoft YaHei UI", 9),
                bd=0, highlightthickness=0,
                command=self._save_window_behavior).pack(side="left",
                                                         padx=(0, 8))

        # 工具
        tool_box = tk.LabelFrame(body, text=" 工具 ", bg=BG, fg=SUB, bd=0,
                                 font=("Microsoft YaHei UI", 9, "bold"))
        tool_box.pack(fill="x", pady=(0, 8))
        tools = [
            ("扫描全部设备", self._scan_all),
            ("查看协议表", self._protocols),
            ("鼠标键盘测试", lambda: self._launch("mouse_test_gui.py")),
            ("HID 调试台", lambda: self._launch("app.py")),
            ("打开项目目录", lambda: os.startfile(BASE_DIR)),
            ("打开配置目录", lambda: os.startfile(tc.RUNTIME_DIR)),
        ]
        grid = tk.Frame(tool_box, bg=BG)
        grid.pack(fill="x", padx=8, pady=8)
        for i, (text, cmd) in enumerate(tools):
            tk.Button(grid, text=text, command=cmd, bg="#242a35", fg=SUB,
                      relief="flat", bd=0, font=("Microsoft YaHei UI", 9),
                      padx=10, pady=4, cursor="hand2").grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 8), pady=3)

        tk.Button(self, text="关闭", command=self.destroy, bg="#242a35",
                  fg=SUB, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=18, pady=5,
                  cursor="hand2").pack(anchor="e", padx=18, pady=(4, 12))

    # ---- 设备列表
    def _rescan_devices(self):
        self.boot_msg.configure(text="正在扫描设备…", fg=FAINT)
        try:
            dr.snapshot(fast=True)
        except Exception as exc:  # noqa: BLE001
            self.boot_msg.configure(text=f"扫描失败：{exc}", fg=RED)
            return
        self._reload_devices()
        self.boot_msg.configure(text="设备列表已刷新", fg=GREEN)

    def _reload_devices(self):
        for child in self.dev_list.winfo_children():
            child.destroy()
        self.device_vars = []
        if self.demo:
            rows = [{"key": s.key, "name": s.name, "show": True, "tray": True}
                    for s in BatteryPanel._make_demo()]
        else:
            rows = dr.known_devices()
        if not rows:
            tk.Label(self.dev_list, text="没有已知设备，先扫描一次", bg=BG,
                     fg=FAINT, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
            return
        for row in rows:
            frame = tk.Frame(self.dev_list, bg=BG)
            frame.pack(fill="x", pady=2)
            tk.Label(frame, text=row["name"], bg=BG, fg=TEXT, width=22,
                     anchor="w", font=("Microsoft YaHei UI", 9, "bold")).pack(
                side="left")
            tk.Label(frame, text=row["key"], bg=BG, fg=FAINT, width=13,
                     anchor="w", font=("Consolas", 8)).pack(side="left")
            show_var = tk.BooleanVar(value=row["show"])
            tray_var = tk.BooleanVar(value=row["tray"])
            self.device_vars.append((row["key"], show_var, tray_var))
            tk.Checkbutton(frame, text="卡片", variable=show_var, bg=BG,
                           fg=SUB, selectcolor=BG, activebackground=BG,
                           activeforeground=TEXT, bd=0, highlightthickness=0,
                           font=("Microsoft YaHei UI", 8),
                           command=lambda k=row["key"], v=show_var:
                           self._set_flag(k, "show", v)).pack(side="left",
                                                              padx=(6, 0))
            tk.Checkbutton(frame, text="托盘", variable=tray_var, bg=BG,
                           fg=SUB, selectcolor=BG, activebackground=BG,
                           activeforeground=TEXT, bd=0, highlightthickness=0,
                           font=("Microsoft YaHei UI", 8),
                           command=lambda k=row["key"], v=tray_var:
                           self._set_flag(k, "tray", v)).pack(side="left",
                                                               padx=(8, 0))

    def _set_flag(self, key, field, var):
        try:
            if field == "show":
                dr.set_flags(key, show=var.get())
            else:
                dr.set_flags(key, tray=var.get())
            tc.post_to_tray(tc.MSG_RELOAD)
            if self.on_change:
                self.on_change()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("设置", str(exc), parent=self)

    # ---- 托盘
    def _refresh_tray_state(self):
        running = tc.is_tray_running()
        self.tray_btn.configure(text="退出托盘" if running else "启动常驻托盘",
                                bg="#a33" if running else "#1f8f4e")
        self.tray_state.configure(text="运行中" if running else "未运行",
                                  fg=GREEN if running else FAINT)

    def _toggle_tray(self):
        self.parent._toggle_tray()
        self._timer_id = self.after(1200, self._refresh_tray_state)

    # ---- 启动
    def _toggle_autostart(self):
        try:
            tc.set_autostart(bool(self.autostart_var.get()))
            cfg = tc.load_config()
            cfg["autostart"] = tc.is_autostart_enabled()
            tc.save_config(cfg)
        except Exception as exc:  # noqa: BLE001
            self.boot_msg.configure(text=f"设置失败：{exc}", fg=RED)
            self.autostart_var.set(tc.is_autostart_enabled())
            return
        enabled = tc.is_autostart_enabled()
        self.autostart_var.set(enabled)
        self.boot_msg.configure(text="开机自启已开启" if enabled else "开机自启已关闭",
                                fg=GREEN if enabled else FAINT)

    def _desktop_links(self):
        result = tc.install_desktop_links()
        errors = result.get("errors") or []
        self.boot_msg.configure(
            text=f"桌面链接失败：{errors[0]}" if errors else "桌面链接已创建",
            fg=RED if errors else GREEN)

    def _save_window_behavior(self):
        cfg = tc.load_config()
        cfg["window"] = {"minimize": self.min_mode.get(),
                         "close": self.close_mode.get()}
        tc.save_config(cfg)
        self.boot_msg.configure(
            text=f"窗口按钮：- → {self.min_mode.get()}，× → {self.close_mode.get()}",
            fg=GREEN)

    def _interval_changed(self):
        seconds = INTERVALS.get(self.interval_var.get(), 60)
        cfg = tc.load_config()
        cfg["interval"] = seconds
        tc.save_config(cfg)
        tc.post_to_tray(tc.MSG_RELOAD)
        if self.parent:
            self.parent._schedule_next()

    # ---- 工具
    def _scan_all(self):
        self.parent.refresh()
        self.boot_msg.configure(text="正在扫描全部设备…", fg=FAINT)

    def _protocols(self):
        win = tk.Toplevel(self)
        win.title("内置协议表")
        win.geometry("760x460")
        win.configure(bg=BG)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_dialog(win))
        text = tk.Text(win, bg="#10131a", fg=SUB, relief="flat",
                       font=("Consolas", 9), wrap="none", padx=10, pady=8)
        text.pack(fill="both", expand=True)
        for s in sorted(gp.SPECS, key=lambda x: (x.kind, x.vid)):
            pids = ("任意" if s.any_pid else "/".join(f"{p:04X}" for p in s.pids)
                    or "任意")
            text.insert("end", f"{s.vid:04X}:{pids}  {s.name}  [{s.kind}]\n")
        text.configure(state="disabled")

    def _launch(self, script):
        try:
            proc = tc.launch_tool(script)
            if proc is not None:
                self.parent._tool_pids.add(proc.pid)
            self.boot_msg.configure(text=f"已打开 {script}", fg=GREEN)
        except Exception as exc:  # noqa: BLE001
            self.boot_msg.configure(text=f"打开失败：{exc}", fg=RED)


# --------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="外设电量面板")
    parser.add_argument("--demo", action="store_true", help="演示数据预览")
    args = parser.parse_args(argv)
    app = BatteryPanel(demo=args.demo)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
