# -*- coding: utf-8 -*-
"""theme.py —— 白天/黑夜主题切换。

每个窗口保留自己的“原始配色”（主面板是深色，鼠标测试/HID 调试台是浅色），
切换时按颜色映射递归重绘控件和 Canvas 图元，因此不需要重建窗口或丢状态。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import tray_common as tc

LIGHT = "light"
DARK = "dark"


def current() -> str:
    value = tc.load_config().get("theme", DARK)
    return value if value in (LIGHT, DARK) else DARK


def _invert(mapping: dict[str, str]) -> dict[str, str]:
    out = {}
    for old, new in mapping.items():
        out.setdefault(new.lower(), old.lower())
    return out


# 主面板：深色 -> 浅色
PANEL_LIGHT = {
    "#0f1115": "#f4f5fa",
    "#10131a": "#f7f8fc",
    "#171a21": "#ffffff",
    "#1f8f4e": "#10b981",
    "#242a35": "#e7e9f0",
    "#252b37": "#e4e7f1",
    "#2a303c": "#e7e9f0",
    "#2d3543": "#d7dceb",
    "#2ecc71": "#34d399",
    "#4f8cff": "#4f8cff",
    "#5a2328": "#f3d6d6",
    "#5d6675": "#8b90a3",
    "#5ddc8a": "#059669",
    "#6aa0ff": "#6aa0ff",
    "#6f7788": "#9aa0b0",
    "#7a2d34": "#e7b4b4",
    "#7d8499": "#6b7280",
    "#a3aab8": "#4b5563",
    "#f5c451": "#d97706",
    "#f5f7fa": "#1f2333",
    "#ff6b6b": "#dc2626",
    "#ffb4b4": "#b42318",
}
PANEL_DARK = _invert(PANEL_LIGHT)

# 工具窗口：浅色 -> 深色
TOOL_DARK = {
    "#f4f5fa": "#0f1115",
    "#f4f5f8": "#0f1115",
    "#ffffff": "#171a21",
    "#f7f8fc": "#1e232e",
    "#eef0ff": "#2b2a55",
    "#e4e7f1": "#252b37",
    "#e7e9f0": "#2a303c",
    "#d7dceb": "#2a303c",
    "#d8dbe6": "#2a303c",
    "#d9deec": "#2a303c",
    "#c5cad9": "#3a4150",
    "#1f2333": "#f5f7fa",
    "#353b52": "#a3aab8",
    "#8b90a3": "#a3aab8",
    "#7b8194": "#a3aab8",
    "#9aa0b0": "#6f7788",
    "#b3b8c8": "#6f7788",
    "#5d6675": "#8b90a3",
    "#6f7788": "#9aa0b0",
    "#7d89a3": "#a3aab8",
    "#6b7280": "#aab1c2",
    "#9aa2b6": "#7e879c",
    "#f1f3f9": "#232936",
    "#1b2233": "#0b0e14",
    "#232b3d": "#1c2333",
    "#38435d": "#303a50",
    "#2a3247": "#1c2333",
    "#3a4560": "#4b566f",
    "#3d4660": "#4b566f",
    "#454f68": "#6f7788",
    "#4b566f": "#6f7788",
    "#5b6788": "#6b7791",
    "#5c6886": "#7d89a3",
    "#7a76c9": "#8b86ff",
    "#e7e5ff": "#2b2a55",
    "#10131a": "#0b0e14",
    "#f3d6d6": "#5a2328",
    "#333": "#f5f7fa",
    "#222": "#f5f7fa",
    "#a33": "#ff8a8a",
    "#000": "#f5f7fa",
    "black": "#f5f7fa",
    "white": "#171a21",
    "#4f8cff": "#4f8cff",
    "#10b981": "#10b981",
    "#f59e0b": "#f59e0b",
    "#ef4444": "#ef4444",
    "#635bff": "#635bff",
    "#4f46e5": "#4f46e5",
    "#8b86ff": "#8b86ff",
    "#6a65d0": "#6a65d0",
    "#7a75f0": "#7a75f0",
}
TOOL_LIGHT = _invert(TOOL_DARK)


def _mapping_for(current_theme: str, target: str, family: str):
    if current_theme == target:
        return {}
    if family == "panel":
        return PANEL_LIGHT if target == LIGHT else PANEL_DARK
    return TOOL_DARK if target == DARK else TOOL_LIGHT


def _color(value):
    return value.lower() if isinstance(value, str) else value


def _ttk_style(root, target: str):
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        if target == DARK:
            bg, card, text = "#0f1115", "#171a21", "#f5f7fa"
            border, muted = "#2a303c", "#a3aab8"
        else:
            bg, card, text = "#f4f5fa", "#ffffff", "#1f2333"
            border, muted = "#e4e7f1", "#6b7280"
        style.configure("TCombobox", fieldbackground=card, background=card,
                        foreground=text, arrowcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.map("TCombobox",
                  fieldbackground=[("readonly", card)],
                  foreground=[("readonly", text)],
                  selectbackground=[("readonly", "#635bff")],
                  selectforeground=[("readonly", "#ffffff")])
        style.configure("Vertical.TScrollbar", background=card, troughcolor=bg,
                        arrowcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.configure("Horizontal.TScrollbar", background=card, troughcolor=bg,
                        arrowcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.configure("TScrollbar", background=card, troughcolor=bg,
                        arrowcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.configure("Treeview", background=card, fieldbackground=card,
                        foreground=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.map("Treeview",
                  background=[("selected", "#635bff")],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=bg, foreground=muted,
                        bordercolor=border, relief="flat")
        style.map("Treeview.Heading",
                  background=[("active", border)],
                  foreground=[("active", text)])
        style.configure("TNotebook", background=bg, bordercolor=border,
                        tabmargins=(2, 2, 2, 0))
        style.configure("TNotebook.Tab", background=card, foreground=muted,
                        padding=(10, 4), bordercolor=border)
        style.map("TNotebook.Tab",
                  background=[("selected", card), ("active", card)],
                  foreground=[("selected", text), ("active", text)])
        style.configure("TLabelframe", background=bg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=muted)
        style.configure("TEntry", fieldbackground=card, foreground=text,
                        insertcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.configure("TSpinbox", fieldbackground=card, foreground=text,
                        arrowcolor=text, bordercolor=border,
                        lightcolor=border, darkcolor=border)
        style.configure("TPanedwindow", background=bg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("TButton", background=card, foreground=text,
                        bordercolor=border)
        style.map("TButton",
                  background=[("active", border)],
                  foreground=[("disabled", muted)])
        style.configure("TCheckbutton", background=bg, foreground=text,
                        indicatorbackground=card)
        style.configure("TRadiobutton", background=bg, foreground=text,
                        indicatorbackground=card)
    except tk.TclError:
        pass


def _recolor_widget(widget, mapping: dict[str, str]):
    if not mapping:
        return
    bg_options = {
        "background", "activebackground", "selectbackground",
        "highlightbackground", "troughcolor", "readonlybackground",
        "selectcolor",
    }
    fg_options = {
        "foreground", "activeforeground", "selectforeground",
        "highlightcolor", "insertbackground", "disabledforeground",
    }
    options = tuple(bg_options | fg_options)
    updates = {}
    for opt in options:
        try:
            value = widget.cget(opt)
        except tk.TclError:
            continue
        color = _color(value)
        new = mapping.get(color)
        # 按钮上的白字不能跟着“白色卡片”一起变深。
        if opt in fg_options and color in ("#ffffff", "white"):
            new = None
        if new:
            updates[opt] = new
    if updates:
        try:
            widget.configure(**updates)
        except tk.TclError:
            pass

    if isinstance(widget, tk.Text):
        for tag in widget.tag_names():
            for opt in ("foreground", "background"):
                try:
                    value = widget.tag_cget(tag, opt)
                except tk.TclError:
                    continue
                color = _color(value)
                new = mapping.get(color)
                if opt == "foreground" and color in ("#ffffff", "white"):
                    new = None
                if new:
                    try:
                        widget.tag_configure(tag, **{opt: new})
                    except tk.TclError:
                        pass


def _recolor_canvas(canvas: tk.Canvas, mapping: dict[str, str]):
    if not mapping:
        return
    for item in canvas.find_all():
        updates = {}
        for opt in ("fill", "outline", "activefill", "activeoutline",
                    "disabledfill", "disabledoutline"):
            try:
                value = canvas.itemcget(item, opt)
            except tk.TclError:
                continue
            new = mapping.get(_color(value))
            if new:
                updates[opt] = new
        if updates:
            try:
                canvas.itemconfigure(item, **updates)
            except tk.TclError:
                pass


def recolor_tree(widget, mapping: dict[str, str]):
    if not mapping:
        return
    _recolor_widget(widget, mapping)
    if isinstance(widget, tk.Canvas):
        _recolor_canvas(widget, mapping)
    for child in widget.winfo_children():
        recolor_tree(child, mapping)


def apply_theme(root, target: str, family: str = "panel"):
    if target not in (LIGHT, DARK):
        target = DARK
    current_theme = getattr(root, "_theme_name", DARK if family == "panel" else LIGHT)
    mapping = _mapping_for(current_theme, target, family)
    if mapping:
        recolor_tree(root, mapping)
    root._theme_name = target
    root._theme_family = family
    _ttk_style(root, target)
    try:
        root.configure(bg="#f4f5fa" if target == LIGHT else "#0f1115")
    except tk.TclError:
        pass
    if hasattr(root, "theme_btn") and root.theme_btn.winfo_exists():
        root.theme_btn.configure(
            text="☀ 白天" if target == DARK else "🌙 黑夜")


def apply_new(widget, family: str = "panel"):
    """刚创建的控件：按它自己的原始配色立即对齐当前主题。"""
    canonical = DARK if family == "panel" else LIGHT
    target = current()
    mapping = _mapping_for(canonical, target, family)
    if mapping:
        recolor_tree(widget, mapping)
    try:
        widget._theme_name = target
        widget._theme_family = family
    except tk.TclError:
        pass


def setup(root, family: str = "panel", on_change=None):
    """初始化主题与轮询：设置改变后，所有已打开窗口 1 秒内自动重绘。"""
    root._theme_family = family
    root._theme_name = DARK if family == "panel" else LIGHT
    target = current()
    if target != root._theme_name:
        apply_theme(root, target, family)
    else:
        _ttk_style(root, target)
    if on_change:
        try:
            on_change()
        except Exception:
            pass

    def poll():
        try:
            if not root.winfo_exists():
                return
            target_theme = current()
            if target_theme != getattr(root, "_theme_name", target):
                apply_theme(root, target_theme, family)
                if on_change:
                    try:
                        on_change()
                    except Exception:
                        pass
            root._theme_after = root.after(1000, poll)
        except tk.TclError:
            pass

    root._theme_after = root.after(1000, poll)

    def cancel(_event):
        aid = getattr(root, "_theme_after", None)
        if aid is not None:
            try:
                root.after_cancel(aid)
            except tk.TclError:
                pass
            root._theme_after = None

    root.bind("<Destroy>", cancel, add="+")
    return root._theme_name
