# -*- coding: utf-8 -*-
"""window_behavior.py —— 让独立工具窗口也遵守主界面的“×”设置。

独立进程（鼠标键盘测试、HID 调试台）关闭时：
  current → 只关自己
  all     → 请求主面板关闭所有可见窗口（托盘保留）
  exit    → 确认后请求主面板完全退出；主面板不在则退出托盘
"""
from __future__ import annotations

from tkinter import messagebox

import tray_common as tc


def handle_close(root) -> None:
    mode = tc.load_config().get("window", {}).get("close", "current")
    if mode == "exit":
        if not messagebox.askyesno(
                "退出应用",
                "将关闭托盘和本应用的所有窗口。\n\n确定完全退出吗？",
                parent=root):
            return
        if tc.panel_hwnd():
            tc.request_app_action("exit")
        else:
            tc.post_to_tray(tc.MSG_QUIT)
        root.destroy()
        return
    if mode == "all":
        if tc.panel_hwnd():
            tc.request_app_action("all")
        root.destroy()
        return
    # current：如果主面板已经不在、托盘也没运行，这是最后一个界面
    if not tc.is_tray_running() and not tc.panel_hwnd():
        if messagebox.askyesno(
                "常驻托盘",
                "托盘当前没有运行。\n\n是否启动常驻托盘？\n"
                "选择「否」将直接退出本工具。",
                parent=root):
            tc.start_tray_app()
    root.destroy()
