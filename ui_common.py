# -*- coding: utf-8 -*-
"""ui_common.py —— UI 通用约定与组件。

**滚动条约定（项目强制）**：纵向、横向滚动条一律只在内容超出
对应可视区域时才显示；内容未超出时隐藏，不占位置。

适用于 tk.Listbox / tk.Text / tk.Canvas / ttk.Treeview 等支持
``xview`` / ``yview`` 与 ``*scrollcommand`` 的控件。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

__all__ = ["AutoScrollbar", "attach_auto_scrollbar"]


class AutoScrollbar:
    """按需显示的滚动条。

    :param parent: 滚动条的父容器
    :param widget: 被滚动的控件
    :param orient: ``"vertical"`` / ``"horizontal"``
    :param layout: ``"pack"`` / ``"grid"``（决定显示与隐藏的方式）
    :param kw: 传给 ``pack`` / ``grid`` 的布局参数（显示时使用）

    内部用 ``*scrollcommand`` 回调 + ``<Configure>`` 双重触发，
    并带滞回区间，避免临界尺寸下反复显隐抖动。
    """

    SHOW_THRESHOLD = 0.985   # 未显示时：可见比例低于此值才显示
    HIDE_THRESHOLD = 0.999   # 已显示时：几乎全部可见才隐藏

    def __init__(self, parent, widget, orient: str = "vertical",
                 layout: str = "pack", **kw):
        self.parent = parent
        self.widget = widget
        self.orient = orient
        self.layout = layout
        self.kw = kw
        self.visible = False

        view = widget.yview if orient == "vertical" else widget.xview
        self.bar = ttk.Scrollbar(parent, orient=orient, command=view)

        def on_scroll(first, last):
            self.bar.set(first, last)
            try:
                span = float(last) - float(first)
            except (TypeError, ValueError):
                return
            self._apply(span)

        if orient == "vertical":
            widget.configure(yscrollcommand=on_scroll)
        else:
            widget.configure(xscrollcommand=on_scroll)

        widget.bind("<Configure>", lambda _e: self.refresh(), add="+")
        if layout == "grid":
            # 先放置一次以记住 grid 位置，再移除（grid_remove 会保留参数）
            self.bar.grid(**kw)
            self.bar.grid_remove()
        try:
            parent.after_idle(self.refresh)
        except tk.TclError:
            pass

    def _apply(self, span: float) -> None:
        """按滞回区间决定是否切换显隐。"""
        if self.visible:
            need = span < self.HIDE_THRESHOLD
        else:
            need = span < self.SHOW_THRESHOLD
        if need == self.visible:
            return
        self.visible = need
        try:
            if need:
                if self.layout == "grid":
                    self.bar.grid(**self.kw)
                else:
                    self.bar.pack(**self.kw)
            else:
                if self.layout == "grid":
                    self.bar.grid_remove()
                else:
                    self.bar.pack_forget()
                # 归位，避免隐藏后残留偏移
                (self.widget.yview_moveto(0) if self.orient == "vertical"
                 else self.widget.xview_moveto(0))
        except tk.TclError:
            pass

    def refresh(self) -> None:
        """主动重新计算（窗口尺寸变化、内容更新后可调用）。"""
        try:
            if not self.widget.winfo_exists():
                return
            view = (self.widget.yview if self.orient == "vertical"
                    else self.widget.xview)
            first, last = view()
            self._apply(float(last) - float(first))
        except (tk.TclError, TypeError, ValueError):
            pass


def attach_auto_scrollbar(parent, widget, orient: str = "vertical",
                          layout: str = "pack", **kw) -> AutoScrollbar:
    """给 ``widget`` 挂一个按需显示的滚动条并返回它。"""
    return AutoScrollbar(parent, widget, orient=orient, layout=layout, **kw)
