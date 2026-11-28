# -*- coding: utf-8 -*-
"""mouse_mapping_panel.py —— 鼠标按键映射配置界面。

打开方式：
* 主界面「🖱 按键映射」按钮
* 设置 → 工具 → 鼠标按键映射
* ``python main.py --tool mouse-map``

界面逻辑：
1. 左侧选择任意已连接鼠标（离线但配置过的设备也会列出）；
2. 右侧为该鼠标启用映射、添加 / 修改 / 删除按键绑定；
3. 每个绑定 = 鼠标按键 + 触发方式 + 事件（鼠标功能 / 键盘按键 /
   打开应用 / 组合事件 / 宏定义 / 语音输入）；
4. 保存立即写盘。配置窗口打开期间后台映射会暂停，关闭后自动恢复，
   避免把左键映射后无法操作本窗口。
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import mouse_remap as mr
import theme
import tray_common as tc
from ui_common import attach_auto_scrollbar

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


def themed(color: str) -> str:
    if theme.current() == "light":
        return theme.PANEL_LIGHT.get(color.lower(), color)
    return color


def _label_to_key(pairs, label: str) -> str:
    for key, text in pairs:
        if text == label:
            return key
    return ""


def _key_to_label(pairs, key: str) -> str:
    for item_key, text in pairs:
        if item_key == key:
            return text
    return key


# 系统动作的补充说明：告诉用户这个动作到底发什么、作用在哪
_SYSTEM_HINTS = {
    "browser_back": "等价于鼠标侧键的后退：浏览器、资源管理器返回上一页",
    "browser_forward": "等价于鼠标侧键的前进：返回刚才后退掉的那一页",
    "browser_refresh": "刷新当前页面（F5 的系统键版本，浏览器通用）",
    "browser_stop": "停止加载当前页面",
    "browser_search": "唤起系统搜索键（部分浏览器/播放器有响应）",
    "browser_favorites": "打开浏览器收藏夹（取决于浏览器是否响应）",
    "browser_home": "回到浏览器主页",
    "media_play_pause": "播放 / 暂停当前媒体，前台是播放器或浏览器都有效",
    "media_next": "切到下一曲",
    "media_prev": "切回上一曲",
    "media_stop_play": "停止播放（不是暂停）",
    "volume_up": "系统音量增大一档",
    "volume_down": "系统音量减小一档",
    "volume_mute": "静音 / 取消静音切换",
    "launch_media": "打开系统默认媒体播放器",
    "show_desktop": "Win+D：最小化所有窗口显示桌面",
    "switch_window": "Alt+Tab：切换到上一个窗口",
    "task_manager": "Ctrl+Shift+Esc：打开任务管理器",
    "screenshot": "Win+Shift+S：系统截图并进入标注",
    "lock_screen": "直接锁屏（调用 LockWorkStation，不走快捷键）",
    "copy": "Ctrl+C：复制当前选中内容",
    "paste": "Ctrl+V：粘贴剪贴板内容",
    "cut": "Ctrl+X：剪切当前选中内容",
    "undo": "Ctrl+Z：撤销",
    "redo": "Ctrl+Y：重做",
    "select_all": "Ctrl+A：全选",
    "save": "Ctrl+S：保存",
    "find": "Ctrl+F：查找",
    "new_tab": "Ctrl+T：新建标签页 / 新窗口",
    "close_tab": "Ctrl+W：关闭当前标签页 / 窗口",
    "reopen_tab": "Ctrl+Shift+T：恢复刚关掉的标签页",
}


def _system_action_desc(action_id: str) -> str:
    return _SYSTEM_HINTS.get(action_id, "")


# ---------------------------------------------------------------------------
# 按键捕获
# ---------------------------------------------------------------------------
class KeyCaptureDialog(tk.Toplevel):
    """按下要触发的组合键，捕获为 ``ctrl+shift+c`` 这样的字符串。"""

    SPECIAL = {
        "Return": "enter", "KP_Enter": "enter", "Escape": "esc",
        "BackSpace": "backspace", "Tab": "tab", "space": "space",
        "Delete": "delete", "Insert": "insert", "Home": "home",
        "End": "end", "Prior": "pageup", "Next": "pagedown",
        "Left": "left", "Right": "right", "Up": "up", "Down": "down",
        "Print": "printscreen", "Pause": "pause", "Caps_Lock": "capslock",
        "Num_Lock": "numlock", "Scroll_Lock": "scrolllock",
        "Menu": "apps",
        # Tk 对符号键用的是名字而不是字符
        "minus": "-", "equal": "=", "plus": "=", "underscore": "-",
        "bracketleft": "[", "bracketright": "]", "braceleft": "[",
        "braceright": "]", "backslash": "\\", "bar": "\\",
        "semicolon": ";", "colon": ";", "apostrophe": "'",
        "quotedbl": "'", "comma": ",", "less": ",", "period": ".",
        "greater": ".", "slash": "/", "question": "/", "grave": "`",
        "asciitilde": "`", "exclam": "1", "at": "2", "numbersign": "3",
        "dollar": "4", "percent": "5", "asciicircum": "6",
        "ampersand": "7", "asterisk": "8", "parenleft": "9",
        "parenright": "0",
        "KP_0": "numpad0", "KP_1": "numpad1", "KP_2": "numpad2",
        "KP_3": "numpad3", "KP_4": "numpad4", "KP_5": "numpad5",
        "KP_6": "numpad6", "KP_7": "numpad7", "KP_8": "numpad8",
        "KP_9": "numpad9", "KP_Add": "add", "KP_Subtract": "subtract",
        "KP_Multiply": "multiply", "KP_Divide": "divide",
        "KP_Decimal": "decimal",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.title("捕获按键")
        self.configure(bg=themed(BG))
        self.resizable(False, False)
        self.result: Optional[str] = None
        self._mods: list[str] = []
        self.transient(parent)
        self.grab_set()
        tk.Label(self, text="请按下要触发的按键组合", bg=themed(BG),
                 fg=themed(TEXT),
                 font=("Microsoft YaHei UI", 12, "bold")).pack(
            padx=28, pady=(20, 6))
        tk.Label(self, text="例如 Ctrl+C、Ctrl+Shift+Esc、Alt+F4；\n"
                            "Esc 本身也可以作为按键。",
                 bg=themed(BG), fg=themed(FAINT),
                 font=("Microsoft YaHei UI", 9), justify="center").pack(
            padx=28, pady=(0, 10))
        self.preview = tk.Label(self, text="等待按键…", bg=themed(CARD),
                                fg=themed(GREEN),
                                font=("Consolas", 14, "bold"), width=28,
                                pady=14)
        self.preview.pack(padx=28, pady=(0, 12), fill="x")
        row = tk.Frame(self, bg=themed(BG))
        row.pack(padx=28, pady=(0, 18), fill="x")
        tk.Button(row, text="取消", command=self.destroy, bg=themed(TRACK),
                  fg=themed(SUB), relief="flat",
                  font=("Microsoft YaHei UI", 10), padx=18,
                  pady=6).pack(side="right")
        tk.Button(row, text="确定", command=self._accept, bg=themed(GREEN),
                  fg="#0b2c18", relief="flat",
                  font=("Microsoft YaHei UI", 10, "bold"), padx=22,
                  pady=6).pack(side="right", padx=(0, 10))
        self.bind("<KeyPress>", self._on_key)
        self.bind("<Map>", self._on_map, add="+")

    def _on_map(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self:
            return
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _on_key(self, event):
        keysym = event.keysym
        modifiers = []
        state = int(event.state or 0)
        if state & 0x0004:
            modifiers.append("ctrl")
        if state & 0x0001:
            modifiers.append("shift")
        if state & 0x20000:                         # Windows: Alt
            modifiers.append("alt")
        if state & 0x0040:                          # 部分 Tk 的 Win 键
            modifiers.append("win")
        if keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                      "Alt_L", "Alt_R", "Super_L", "Super_R",
                      "Win_L", "Win_R", "Meta_L", "Meta_R"):
            self.preview.configure(text="+".join(modifiers) + "+…")
            return "break"
        main = self.SPECIAL.get(keysym)
        if main is None:
            if len(keysym) == 1:
                main = keysym.lower()
            elif keysym.upper().startswith("F") and keysym[1:].isdigit():
                main = keysym.lower()
            else:
                main = keysym.lower()
        combo = "+".join(modifiers + [main])
        if not modifiers and len(combo) == 1 and combo.isalpha():
            combo = combo
        self.preview.configure(text=combo)
        self.result = combo
        return "break"

    def _accept(self):
        if not self.result:
            messagebox.showinfo("提示", "请先按下一个按键组合", parent=self)
            return
        self.destroy()


# ---------------------------------------------------------------------------
# 步骤编辑（组合事件 / 宏定义）
# ---------------------------------------------------------------------------
class StepDialog(tk.Toplevel):
    def __init__(self, parent, macro: bool = True, step: Optional[dict] = None):
        super().__init__(parent)
        self.title("编辑步骤")
        self.configure(bg=themed(BG))
        self.macro = macro
        self.result: Optional[dict] = None
        self.step = step or {"kind": "key", "value": "", "args": "",
                             "delay_ms": 0}
        self.kind_var = tk.StringVar(
            value=mr.STEP_LABELS.get(self.step.get("kind"), "按键"))
        self.value_var = tk.StringVar(value=self.step.get("value", ""))
        self.args_var = tk.StringVar(value=self.step.get("args", ""))
        self.delay_var = tk.StringVar(value=str(self.step.get("delay_ms", 0)))
        self._body = None
        self.transient(parent)
        self.grab_set()
        self._build()
        theme.apply_new(self, "panel")
        self.geometry("560x330")
        self.minsize(520, 300)

    def _build(self):
        head = tk.Frame(self, bg=themed(BG))
        head.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(head, text="步骤类型", bg=themed(BG), fg=themed(SUB),
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        kinds = [(k, t) for k, t in mr.STEP_KINDS
                 if self.macro or k != "text"]
        combo = ttk.Combobox(head, state="readonly", width=12,
                             values=[t for _k, t in kinds],
                             font=("Microsoft YaHei UI", 10))
        combo.set(mr.STEP_LABELS.get(self.step.get("kind"), "按键"))
        combo.pack(side="left", padx=(8, 0))
        combo.bind("<<ComboboxSelected>>", self._kind_changed)
        self._kinds = kinds
        self._kind_combo = combo
        self._body = tk.Frame(self, bg=themed(BG))
        self._body.pack(fill="both", expand=True, padx=20, pady=4)
        self._render_body(self._current_kind())
        foot = tk.Frame(self, bg=themed(BG))
        foot.pack(fill="x", padx=20, pady=(4, 14))
        tk.Button(foot, text="保存", command=self._save, bg=themed(GREEN),
                  fg="#0b2c18", relief="flat",
                  font=("Microsoft YaHei UI", 10, "bold"), padx=20,
                  pady=6).pack(side="right")
        tk.Button(foot, text="取消", command=self.destroy, bg=themed(TRACK),
                  fg=themed(SUB), relief="flat",
                  font=("Microsoft YaHei UI", 10), padx=16,
                  pady=6).pack(side="right", padx=(0, 10))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _current_kind(self) -> str:
        label = self._kind_combo.get()
        for key, text in self._kinds:
            if text == label:
                return key
        return "key"

    def _kind_changed(self, _event=None):
        for child in self._body.winfo_children():
            child.destroy()
        self._render_body(self._current_kind())

    def _render_body(self, kind: str):
        self.kind_var.set(mr.STEP_LABELS.get(kind, kind))
        if hasattr(self, "_kind_combo"):
            self._kind_combo.set(mr.STEP_LABELS.get(kind, kind))
        row = tk.Frame(self._body, bg=themed(BG))
        row.pack(fill="x", pady=(8, 4))
        if kind == "key":
            tk.Label(row, text="按键组合", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.value_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 10)).pack(
                side="left", fill="x", expand=True, ipady=4)
            tk.Button(row, text="捕获按键", command=self._capture,
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9),
                      padx=10).pack(side="left", padx=(8, 0))
        elif kind == "mouse":
            tk.Label(row, text="鼠标功能", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            current = mr.mouse_function_label(self.value_var.get()) \
                if self.value_var.get() else mr.MOUSE_FUNCTIONS[0][1]
            combo = ttk.Combobox(
                row, state="readonly", width=26,
                values=[text for _k, text in mr.MOUSE_FUNCTIONS],
                font=("Microsoft YaHei UI", 10))
            combo.set(current)
            combo.pack(side="left", ipady=2)
            self._func_combo = combo
        elif kind == "app":
            tk.Label(row, text="应用路径", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.value_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 9)).pack(
                side="left", fill="x", expand=True, ipady=4)
            tk.Button(row, text="浏览…", command=self._browse,
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9),
                      padx=10).pack(side="left", padx=(8, 0))
            row2 = tk.Frame(self._body, bg=themed(BG))
            row2.pack(fill="x", pady=4)
            tk.Label(row2, text="启动参数", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row2, textvariable=self.args_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 9)).pack(
                side="left", fill="x", expand=True, ipady=4)
        elif kind == "text":
            tk.Label(row, text="文字内容", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.value_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Microsoft YaHei UI", 9)).pack(
                side="left", fill="x", expand=True, ipady=4)
        elif kind == "wait":
            tk.Label(row, text="等待毫秒", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.value_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 10), width=12).pack(
                side="left", ipady=4)
            tk.Label(row, text="（0~600000）", bg=themed(BG),
                     fg=themed(FAINT),
                     font=("Microsoft YaHei UI", 8)).pack(side="left",
                                                          padx=(8, 0))

        if kind != "wait":
            delay_row = tk.Frame(self._body, bg=themed(BG))
            delay_row.pack(fill="x", pady=(10, 0))
            tk.Label(delay_row, text="之后等待", bg=themed(BG),
                     fg=themed(SUB), font=("Microsoft YaHei UI", 9)).pack(
                side="left")
            tk.Entry(delay_row, textvariable=self.delay_var,
                     bg=themed(TRACK), fg=themed(TEXT),
                     insertbackground=themed(TEXT), relief="flat",
                     font=("Consolas", 10), width=10).pack(
                side="left", padx=(8, 0), ipady=3)
            tk.Label(delay_row, text="毫秒", bg=themed(BG), fg=themed(FAINT),
                     font=("Microsoft YaHei UI", 8)).pack(side="left",
                                                          padx=(4, 0))
        else:
            self.delay_var.set("0")

    def _capture(self):
        dialog = KeyCaptureDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.value_var.set(dialog.result)

    def _browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择要打开的应用",
            filetypes=[("程序/快捷方式", "*.exe *.lnk *.bat *.cmd *.py"),
                       ("所有文件", "*.*")])
        if path:
            self.value_var.set(path)

    def _collect(self, kind: str) -> dict:
        if kind == "mouse":
            label = getattr(self, "_func_combo", None)
            value = ""
            if label is not None:
                value = _label_to_key(mr.MOUSE_FUNCTIONS, label.get())
            if not value:
                value = self.value_var.get()
        else:
            value = self.value_var.get().strip()
        step = {
            "kind": kind,
            "value": value,
            "args": self.args_var.get().strip() if kind == "app" else "",
            "delay_ms": 0,
        }
        if kind != "wait":
            try:
                step["delay_ms"] = max(0, min(600000,
                                              int(self.delay_var.get() or 0)))
            except ValueError:
                step["delay_ms"] = 0
        return step

    def _save(self):
        kind = self._current_kind()
        step = self._collect(kind)
        ok, error = mr.validate_step(step, macro=self.macro)
        if not ok:
            messagebox.showwarning("步骤无效", error, parent=self)
            return
        self.result = step
        self.destroy()


# ---------------------------------------------------------------------------
# 绑定编辑
# ---------------------------------------------------------------------------
class BindingDialog(tk.Toplevel):
    def __init__(self, parent, device: dict, preset_button: str = "",
                 binding: Optional[dict] = None):
        super().__init__(parent)
        self.device = device
        self.binding = binding
        self.result: Optional[dict] = None
        self.title("编辑按键映射" if binding else "添加按键映射")
        self.configure(bg=themed(BG))
        self.geometry("640x620")
        self.minsize(600, 520)
        self.transient(parent)
        self.grab_set()

        buttons = list(mr.BUTTONS)
        if device.get("voice"):
            buttons += mr.VOICE_BUTTONS
        self._button_pairs = buttons
        current = (binding or {}).get("button") or preset_button or buttons[0][0]
        self.button_var = tk.StringVar(value=_key_to_label(buttons, current))
        self.trigger_var = tk.StringVar(
            value=mr.TRIGGER_LABELS.get((binding or {}).get("trigger", "press"),
                                        "按下触发"))
        self.type_var = tk.StringVar(value="鼠标功能")
        self.func_var = tk.StringVar(value=mr.MOUSE_FUNCTIONS[0][0])
        self.sys_var = tk.StringVar(value=mr.SYSTEM_ACTIONS[0][0])
        self.keys_var = tk.StringVar(value="")
        self.path_var = tk.StringVar(value="")
        self.args_var = tk.StringVar(value="")
        self.steps = list((binding or {}).get("action", {}).get("steps") or [])
        self._body = None
        self._steps_box = None
        self._build()
        theme.apply_new(self, "panel")
        self._sync_button_options()
        if binding:
            action = binding.get("action") or {}
            self._load_action(action)

    # -- UI -------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=themed(BG))
        head.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(head, text=self.device.get("label") or self.device.get("key"),
                 bg=themed(BG), fg=themed(TEXT),
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        tk.Label(head, text=self.device.get("key", ""), bg=themed(BG),
                 fg=themed(FAINT),
                 font=("Consolas", 9)).pack(side="left", padx=(10, 0))

        form = tk.Frame(self, bg=themed(BG))
        form.pack(fill="x", padx=20, pady=(8, 0))
        self._row(form, 0, "鼠标按键", self._button_combo(form))
        self._row(form, 1, "触发方式", self._trigger_combo(form))
        self._row(form, 2, "事件类型", self._type_combo(form))

        self._body = tk.Frame(self, bg=themed(BG))
        self._body.pack(fill="both", expand=True, padx=20, pady=(6, 4))

        foot = tk.Frame(self, bg=themed(BG))
        foot.pack(fill="x", padx=20, pady=(4, 16))
        tk.Button(foot, text="保存", command=self._save, bg=themed(GREEN),
                  fg="#0b2c18", relief="flat",
                  font=("Microsoft YaHei UI", 10, "bold"), padx=22,
                  pady=6).pack(side="right")
        tk.Button(foot, text="取消", command=self.destroy, bg=themed(TRACK),
                  fg=themed(SUB), relief="flat",
                  font=("Microsoft YaHei UI", 10), padx=18,
                  pady=6).pack(side="right", padx=(0, 10))
        self.bind("<Escape>", lambda _e: self.destroy())

    def _row(self, parent, row: int, label: str, widget):
        tk.Label(parent, text=label, bg=themed(BG), fg=themed(SUB), width=9,
                 anchor="w", font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky="w", pady=5)
        widget.grid(row=row, column=1, sticky="w", pady=5)

    def _button_combo(self, parent):
        combo = ttk.Combobox(
            parent, state="readonly", width=26,
            values=[text for _key, text in self._button_pairs],
            font=("Microsoft YaHei UI", 10))
        combo.set(self.button_var.get())
        combo.bind("<<ComboboxSelected>>", self._button_changed)
        self._button_combo = combo
        return combo

    def _trigger_combo(self, parent):
        combo = ttk.Combobox(parent, state="readonly", width=26,
                             values=[text for _k, text in mr.TRIGGERS],
                             font=("Microsoft YaHei UI", 10))
        combo.set(self.trigger_var.get())
        combo.bind("<<ComboboxSelected>>", self._trigger_changed)
        self._trigger_combo = combo
        return combo

    def _type_combo(self, parent):
        combo = ttk.Combobox(parent, state="readonly", width=26,
                             values=[text for _k, text in mr.ACTION_TYPES],
                             font=("Microsoft YaHei UI", 10))
        combo.set(self.type_var.get())
        combo.bind("<<ComboboxSelected>>", self._type_changed)
        self._type_combo = combo
        return combo

    # -- 选项联动 -------------------------------------------------------
    def _selected_button(self) -> str:
        # 直接用 Combobox 当前文本；button_var 只是初始值，不会随选择更新
        return _label_to_key(self._button_pairs, self._button_combo.get())

    def _is_voice_button(self) -> bool:
        return self._selected_button() == mr.VOICE_KEY

    def _button_changed(self, _event=None):
        self._sync_button_options()

    def _trigger_changed(self, _event=None):
        self._sync_button_options()

    def _sync_button_options(self):
        voice = self._is_voice_button()
        trigger_values = ["按住（松开结束）"] if voice else ["按下触发"]
        self._trigger_combo.configure(values=trigger_values)
        if self._trigger_combo.get() not in trigger_values:
            self._trigger_combo.set(trigger_values[0])
        types = [("voice_input", "语音输入")] if voice else \
            [(k, t) for k, t in mr.ACTION_TYPES if k != "voice_input"]
        type_values = [text for _k, text in types]
        self._type_combo.configure(values=type_values)
        self._types = types
        if self._type_combo.get() not in type_values:
            self._type_combo.set(type_values[-1] if voice else
                                 type_values[0])
        self._render_body()

    def _type_changed(self, _event=None):
        self._render_body()

    def _selected_type(self) -> str:
        return _label_to_key(getattr(self, "_types", mr.ACTION_TYPES),
                             self._type_combo.get()) or "mouse"

    # -- 事件参数 -------------------------------------------------------
    def _render_body(self):
        if self._body is None:
            return
        for child in self._body.winfo_children():
            child.destroy()
        kind = self._selected_type()
        if kind == "voice_input":
            box = tk.Frame(self._body, bg=themed(CARD),
                           highlightbackground=themed(CARD_EDGE),
                           highlightthickness=1)
            box.pack(fill="x", pady=6)
            tk.Label(box, text="按住魔声鼠标语音键说话，松开后自动识别并键入"
                               "当前焦点输入框。",
                     bg=themed(CARD), fg=themed(TEXT), anchor="w",
                     font=("Microsoft YaHei UI", 10, "bold"),
                     wraplength=540, justify="left").pack(
                fill="x", padx=14, pady=(12, 2))
            tk.Label(box, text="语音参数沿用「语音窗口 → ⚙ 设置」里的配置"
                               "（模型、流式、门控等）。\n"
                               "语音输入只能绑定到语音键；其他鼠标没有麦克风"
                               "音频通道。",
                     bg=themed(CARD), fg=themed(SUB), anchor="w",
                     font=("Microsoft YaHei UI", 8), wraplength=540,
                     justify="left").pack(fill="x", padx=14, pady=(0, 12))
            return
        if kind == "mouse":
            row = tk.Frame(self._body, bg=themed(BG))
            row.pack(fill="x", pady=8)
            tk.Label(row, text="鼠标功能", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            combo = ttk.Combobox(
                row, state="readonly", width=26,
                values=[text for _k, text in mr.MOUSE_FUNCTIONS],
                font=("Microsoft YaHei UI", 10))
            combo.set(mr.mouse_function_label(self.func_var.get()))
            combo.pack(side="left")
            self._func_combo = combo
            return
        if kind == "key":
            row = tk.Frame(self._body, bg=themed(BG))
            row.pack(fill="x", pady=8)
            tk.Label(row, text="按键组合", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.keys_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 10), width=30).pack(
                side="left", ipady=4)
            tk.Button(row, text="捕获按键", command=self._capture_key,
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9), padx=10).pack(
                side="left", padx=(8, 0))
            tk.Label(self._body, text="支持组合键，例如 ctrl+c、ctrl+shift+esc、"
                                     "alt+f4、f5、win+r。",
                     bg=themed(BG), fg=themed(FAINT), anchor="w",
                     font=("Microsoft YaHei UI", 8)).pack(fill="x")
            return
        if kind == "system":
            row = tk.Frame(self._body, bg=themed(BG))
            row.pack(fill="x", pady=(8, 2))
            tk.Label(row, text="系统动作", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            combo = ttk.Combobox(
                row, state="readonly", width=26,
                values=[text for _k, text, _s in mr.SYSTEM_ACTIONS],
                font=("Microsoft YaHei UI", 10))
            combo.set(mr.system_action_label(self.sys_var.get()))
            combo.pack(side="left")
            self._sys_combo = combo

            desc = tk.Label(
                self._body, text=_system_action_desc(self.sys_var.get()),
                bg=themed(BG), fg=themed(FAINT), anchor="w",
                font=("Microsoft YaHei UI", 8), wraplength=540,
                justify="left")
            desc.pack(fill="x", pady=(4, 0))

            def on_pick(_event=None, c=combo, d=desc):
                picked = _label_to_key(
                    [(k, t) for k, t, _s in mr.SYSTEM_ACTIONS], c.get())
                if picked:
                    self.sys_var.set(picked)
                    d.configure(text=_system_action_desc(picked))

            combo.bind("<<ComboboxSelected>>", on_pick)
            tk.Label(self._body,
                     text="浏览器前进/后退、媒体控制、音量键直接走系统通道，"
                          "不用装驱动；编辑类走标准快捷键，对当前焦点窗口生效。",
                     bg=themed(BG), fg=themed(FAINT), anchor="w",
                     font=("Microsoft YaHei UI", 8), wraplength=540,
                     justify="left").pack(fill="x", pady=(2, 0))
            return
        if kind == "app":
            row = tk.Frame(self._body, bg=themed(BG))
            row.pack(fill="x", pady=(8, 2))
            tk.Label(row, text="应用路径", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row, textvariable=self.path_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 9)).pack(
                side="left", fill="x", expand=True, ipady=4)
            tk.Button(row, text="浏览…", command=self._browse_app,
                      bg=themed(TRACK), fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9), padx=10).pack(
                side="left", padx=(8, 0))
            row2 = tk.Frame(self._body, bg=themed(BG))
            row2.pack(fill="x", pady=2)
            tk.Label(row2, text="启动参数", bg=themed(BG), fg=themed(SUB),
                     width=9, anchor="w",
                     font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Entry(row2, textvariable=self.args_var, bg=themed(TRACK),
                     fg=themed(TEXT), insertbackground=themed(TEXT),
                     relief="flat", font=("Consolas", 9)).pack(
                side="left", fill="x", expand=True, ipady=4)
            return
        if kind in ("combo", "macro"):
            self._render_steps(body_kind=kind)
            return

    def _render_steps(self, body_kind: str):
        tk.Label(self._body,
                 text="按顺序执行；「之后等待」用于组合动作之间的间隔。",
                 bg=themed(BG), fg=themed(FAINT), anchor="w",
                 font=("Microsoft YaHei UI", 8)).pack(fill="x", pady=(4, 2))
        wrap = tk.Frame(self._body, bg=themed(CARD),
                        highlightbackground=themed(CARD_EDGE),
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=4)
        box = tk.Listbox(wrap, bg=themed(CARD), fg=themed(TEXT),
                         selectbackground=themed(CARD_EDGE),
                         selectforeground=themed(TEXT), relief="flat",
                         highlightthickness=0, font=("Consolas", 9),
                         activestyle="none", height=7)
        box.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        attach_auto_scrollbar(wrap, box, orient="vertical", layout="pack",
                              side="right", fill="y")
        self._steps_box = box
        self._refresh_steps()
        bar = tk.Frame(self._body, bg=themed(BG))
        bar.pack(fill="x", pady=(2, 0))
        for text, cmd in (("添加步骤", self._add_step),
                          ("修改", self._edit_step),
                          ("删除", self._del_step),
                          ("上移", lambda: self._move_step(-1)),
                          ("下移", lambda: self._move_step(1))):
            tk.Button(bar, text=text, command=cmd, bg=themed(TRACK),
                      fg=themed(SUB), relief="flat",
                      font=("Microsoft YaHei UI", 9), padx=9,
                      pady=3).pack(side="left", padx=(0, 6))
        self._macro_mode = (body_kind == "macro")

    def _refresh_steps(self):
        if self._steps_box is None:
            return
        self._steps_box.delete(0, "end")
        for index, step in enumerate(self.steps, 1):
            kind = mr.STEP_LABELS.get(step.get("kind"), step.get("kind"))
            value = step.get("value", "")
            if step.get("kind") == "mouse":
                value = mr.mouse_function_label(value)
            if step.get("kind") == "wait":
                text = "%d. %s %s 毫秒" % (index, kind, value)
            else:
                delay = int(step.get("delay_ms") or 0)
                text = "%d. %s %s" % (index, kind, value)
                if delay:
                    text += "  → 等待 %d 毫秒" % delay
            self._steps_box.insert("end", "  " + text)

    def _selected_step(self) -> Optional[int]:
        if self._steps_box is None:
            return None
        selection = self._steps_box.curselection()
        return int(selection[0]) if selection else None

    def _add_step(self):
        dialog = StepDialog(self, macro=getattr(self, "_macro_mode", True))
        self.wait_window(dialog)
        if dialog.result:
            self.steps.append(dialog.result)
            self._refresh_steps()

    def _edit_step(self):
        index = self._selected_step()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个步骤", parent=self)
            return
        dialog = StepDialog(self, macro=getattr(self, "_macro_mode", True),
                            step=self.steps[index])
        self.wait_window(dialog)
        if dialog.result:
            self.steps[index] = dialog.result
            self._refresh_steps()

    def _del_step(self):
        index = self._selected_step()
        if index is None:
            messagebox.showinfo("提示", "请先选中一个步骤", parent=self)
            return
        self.steps.pop(index)
        self._refresh_steps()

    def _move_step(self, delta: int):
        index = self._selected_step()
        if index is None:
            return
        target = index + delta
        if 0 <= target < len(self.steps):
            self.steps[index], self.steps[target] = \
                self.steps[target], self.steps[index]
            self._refresh_steps()
            self._steps_box.selection_set(target)

    def _capture_key(self):
        dialog = KeyCaptureDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.keys_var.set(dialog.result)

    def _browse_app(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择要打开的应用",
            filetypes=[("程序/快捷方式", "*.exe *.lnk *.bat *.cmd *.py"),
                       ("所有文件", "*.*")])
        if path:
            self.path_var.set(path)

    # -- 载入 / 保存 ----------------------------------------------------
    def _load_action(self, action: dict):
        kind = action.get("type", "mouse")
        self.type_var.set(mr.action_label(kind))
        self._type_combo.set(mr.action_label(kind))
        if kind == "mouse":
            self.func_var.set(action.get("function", "left_click"))
        elif kind == "key":
            self.keys_var.set(action.get("keys", ""))
        elif kind == "system":
            self.sys_var.set(action.get("action", mr.SYSTEM_ACTIONS[0][0]))
        elif kind == "app":
            self.path_var.set(action.get("path", ""))
            self.args_var.set(action.get("args", ""))
        elif kind in ("combo", "macro"):
            self.steps = list(action.get("steps") or [])
        self._sync_button_options()

    def _collect_action(self) -> dict:
        kind = self._selected_type()
        if kind == "mouse":
            function = _label_to_key(
                mr.MOUSE_FUNCTIONS, self._func_combo.get()) \
                if hasattr(self, "_func_combo") else self.func_var.get()
            return {"type": "mouse", "function": function}
        if kind == "key":
            return {"type": "key", "keys": self.keys_var.get().strip()}
        if kind == "system":
            action_id = self.sys_var.get()
            if hasattr(self, "_sys_combo"):
                action_id = _label_to_key(
                    [(k, t) for k, t, _s in mr.SYSTEM_ACTIONS],
                    self._sys_combo.get()) or action_id
            return {"type": "system", "action": action_id}
        if kind == "app":
            return {"type": "app", "path": self.path_var.get().strip(),
                    "args": self.args_var.get().strip()}
        if kind in ("combo", "macro"):
            return {"type": kind,
                    "steps": [dict(step) for step in self.steps]}
        if kind == "voice_input":
            return {"type": "voice_input", "mode": "input"}
        return {"type": kind}

    def _save(self):
        button = self._selected_button()
        trigger = _label_to_key(mr.TRIGGERS, self._trigger_combo.get()) or "press"
        action = self._collect_action()
        ok, error = mr.validate_binding(self.device.get("key", ""), button,
                                        trigger, action)
        if not ok:
            messagebox.showwarning("映射无效", error, parent=self)
            return
        self.result = {"button": button, "trigger": trigger,
                       "action": action}
        self.destroy()


# ---------------------------------------------------------------------------
# 主界面
# ---------------------------------------------------------------------------
class MouseMappingWindow(tk.Toplevel):
    def __init__(self, parent, on_close=None, config_path: str | None = None,
                 auto_pause: bool = True, manage_daemon: bool = True):
        super().__init__(parent)
        self.title(f"{tc.UI_TITLE} · 鼠标按键映射")
        self.configure(bg=BG)
        self.geometry("1020x700")
        self.minsize(900, 580)
        self._on_close_cb = on_close
        self._config_path = config_path
        self._manage_daemon = manage_daemon
        self._auto_pause = auto_pause
        self.cfg = mr.load_config(config_path)
        self._devices: list[dict] = []
        self._current_key = ""
        self._paused = False
        self._keep_paused = False
        self._destroyed = False
        self._poll_id = None
        self._ui_queue: queue.Queue = queue.Queue()

        self.enabled_var = tk.BooleanVar(value=bool(self.cfg.get("enabled")))
        self.device_enabled_var = tk.BooleanVar(value=True)
        self._build()
        theme.apply_new(self, "panel")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._refresh_devices()
        self._poll_status()
        self.after(100, self._maybe_autopause)

    # -- UI -------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 4))
        tk.Label(head, text="鼠标按键映射", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
        tk.Label(head, text="拦截原鼠标按键 → 触发自定义事件",
                 bg=BG, fg=FAINT,
                 font=("Microsoft YaHei UI", 9)).pack(side="left",
                                                      padx=(12, 0))
        tk.Button(head, text="关闭", command=self._close, bg="#242a35",
                  fg=SUB, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                  cursor="hand2").pack(side="right")
        tk.Button(head, text="刷新设备", command=self._refresh_devices,
                  bg="#242a35", fg=SUB, relief="flat", bd=0,
                  font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                  cursor="hand2").pack(side="right", padx=(0, 8))

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=18, pady=(4, 6))
        tk.Checkbutton(
            top, text="启用按键映射（后台守护进程）",
            variable=self.enabled_var, command=self._toggle_enabled,
            bg=BG, fg=TEXT, selectcolor=BG, activebackground=BG,
            activeforeground=TEXT, font=("Microsoft YaHei UI", 10, "bold"),
            bd=0, highlightthickness=0).pack(side="left")
        self.pause_btn = tk.Button(
            top, text="暂停映射", command=self._toggle_pause, bg="#242a35",
            fg=SUB, relief="flat", bd=0,
            font=("Microsoft YaHei UI", 9), padx=12, pady=3,
            cursor="hand2")
        self.pause_btn.pack(side="left", padx=(14, 0))
        self.daemon_label = tk.Label(top, text="后台：读取中…", bg=BG,
                                     fg=FAINT,
                                     font=("Microsoft YaHei UI", 9))
        self.daemon_label.pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 8))

        left = tk.Frame(body, bg=BG, width=260)
        left.pack(side="left", fill="y")
        tk.Label(left, text="鼠标设备（●在线 ○离线）", bg=BG, fg=SUB,
                 font=("Microsoft YaHei UI", 9, "bold"),
                 anchor="w").pack(fill="x")
        wrap = tk.Frame(left, bg=CARD, highlightbackground=CARD_EDGE,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.dev_list = tk.Listbox(
            wrap, bg=CARD, fg=TEXT, selectbackground=CARD_EDGE,
            selectforeground=TEXT, relief="flat", highlightthickness=0,
            font=("Microsoft YaHei UI", 10), activestyle="none",
            exportselection=False)
        self.dev_list.pack(side="left", fill="both", expand=True,
                           padx=(8, 0), pady=8)
        attach_auto_scrollbar(wrap, self.dev_list, orient="vertical",
                              layout="pack", side="right", fill="y")
        self.dev_list.bind("<<ListboxSelect>>", self._on_device_select)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.dev_label = tk.Label(right, text="请选择鼠标", bg=BG, fg=TEXT,
                                  font=("Microsoft YaHei UI", 14, "bold"),
                                  anchor="w")
        self.dev_label.pack(fill="x")
        self.dev_hint = tk.Label(right, text="", bg=BG, fg=FAINT,
                                 font=("Consolas", 9), anchor="w")
        self.dev_hint.pack(fill="x", pady=(0, 6))
        dev_row = tk.Frame(right, bg=BG)
        dev_row.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            dev_row, text="启用此鼠标的映射", variable=self.device_enabled_var,
            command=self._toggle_device, bg=BG, fg=SUB, selectcolor=BG,
            activebackground=BG, activeforeground=TEXT,
            font=("Microsoft YaHei UI", 9), bd=0,
            highlightthickness=0).pack(side="left")

        bar = tk.Frame(right, bg=BG)
        bar.pack(fill="x", pady=(2, 6))
        for text, cmd in (("添加映射", self._add_binding),
                          ("修改", self._edit_binding),
                          ("删除", self._delete_binding),
                          ("▶ 测试", self._test_binding)):
            tk.Button(bar, text=text, command=cmd, bg="#242a35", fg=SUB,
                      relief="flat", bd=0,
                      font=("Microsoft YaHei UI", 9), padx=12, pady=4,
                      cursor="hand2").pack(side="left", padx=(0, 8))

        tree_wrap = tk.Frame(right, bg=CARD, highlightbackground=CARD_EDGE,
                             highlightthickness=1)
        tree_wrap.pack(fill="both", expand=True)
        columns = ("button", "trigger", "type", "summary")
        self.tree = ttk.Treeview(tree_wrap, columns=columns, show="headings",
                                 selectmode="browse")
        for column, text, width in (("button", "按键", 130),
                                    ("trigger", "触发", 120),
                                    ("type", "事件", 130),
                                    ("summary", "摘要", 330)):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0),
                       pady=8)
        attach_auto_scrollbar(tree_wrap, self.tree, orient="vertical",
                              layout="pack", side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._edit_binding())
        self.tree.tag_configure("unbound", foreground=themed(FAINT))

        self.voice_hint = tk.Label(
            right, text="语音输入只支持魔声 AI 垂直鼠标，且只能绑定语音键。",
            bg=BG, fg=themed(AMBER), anchor="w",
            font=("Microsoft YaHei UI", 8))
        self.voice_hint.pack(fill="x", pady=(4, 0))

        self.message = tk.Label(self, text="", bg=BG, fg=FAINT, anchor="w",
                                font=("Microsoft YaHei UI", 9))
        self.message.pack(fill="x", padx=18, pady=(0, 4))
        self.foot_hint = tk.Label(
            self, text="配置期间后台映射已暂停；关闭本窗口后自动恢复。",
            bg=BG, fg=themed(FAINT), anchor="w",
            font=("Microsoft YaHei UI", 8))
        self.foot_hint.pack(fill="x", padx=18, pady=(0, 12))

    # -- 数据 -----------------------------------------------------------
    def _refresh_devices(self):
        try:
            connected = {item["key"]: item for item in mr.list_mice()}
        except Exception:
            connected = {}
        merged: dict[str, dict] = {}
        for key, item in connected.items():
            merged[key] = {"key": key, "label": item.get("label") or key,
                           "connected": True,
                           "voice": bool(item.get("voice"))}
        for key, dev in (self.cfg.get("devices") or {}).items():
            if key in merged:
                merged[key]["configured"] = True
                continue
            merged[key] = {"key": key, "label": dev.get("name") or key,
                           "connected": False,
                           "voice": mr.is_voice_device(key),
                           "configured": True}
        devices = sorted(
            merged.values(),
            key=lambda item: (0 if item["connected"] else 1,
                              0 if item.get("voice") else 1,
                              item["label"]))
        self._devices = devices
        self.dev_list.delete(0, "end")
        if not devices:
            self.dev_list.insert("end", "  （未检测到鼠标）")
            self._current_key = ""
            self._refresh_bindings()
            return
        selected_index = 0
        for index, item in enumerate(devices):
            mark = "●" if item["connected"] else "○"
            voice = " 🎤" if item.get("voice") else ""
            self.dev_list.insert("end", "  %s %s%s" % (mark, item["label"],
                                                        voice))
            if item["key"] == self._current_key:
                selected_index = index
        if not self._current_key:
            self._current_key = devices[0]["key"]
        self.dev_list.selection_clear(0, "end")
        self.dev_list.selection_set(selected_index)
        self.dev_list.see(selected_index)
        self._on_device_select(notify=False)

    def _current_device(self) -> Optional[dict]:
        for item in self._devices:
            if item["key"] == self._current_key:
                return item
        return None

    def _on_device_select(self, _event=None, notify=True):
        selection = self.dev_list.curselection()
        if selection and selection[0] < len(self._devices):
            self._current_key = self._devices[selection[0]]["key"]
        device = self._current_device()
        if device is None:
            self.dev_label.configure(text="请选择鼠标")
            self.dev_hint.configure(text="")
            self.device_enabled_var.set(False)
            self._refresh_bindings()
            return
        self.dev_label.configure(text=device["label"])
        state = "已连接" if device["connected"] else "未连接（配置仍保留）"
        self.dev_hint.configure(text="%s · %s%s" % (
            device["key"], state, " · 支持语音键" if device.get("voice") else ""))
        dev_cfg = (self.cfg.get("devices") or {}).get(device["key"]) or {}
        self.device_enabled_var.set(bool(dev_cfg.get("enabled", True)))
        self._refresh_bindings()
        self.voice_hint.configure(
            text=("语音输入只支持此鼠标，且只能绑定语音键。"
                  if device.get("voice") else
                  "此鼠标不支持语音输入（只有魔声 248A:60AB 有麦克风音频通道）。"),
            fg=themed(GREEN if device.get("voice") else FAINT))

    def _refresh_bindings(self):
        self.tree.delete(*self.tree.get_children())
        device = self._current_device()
        if device is None:
            return
        dev = (self.cfg.get("devices") or {}).get(device["key"], {})
        bindings = dev.get("bindings") or {}
        buttons = list(mr.BUTTONS)
        if device.get("voice"):
            buttons += mr.VOICE_BUTTONS
        for button, label in buttons:
            binding = bindings.get(button)
            if binding:
                action = binding.get("action") or {}
                kind = action.get("type", "")
                self.tree.insert(
                    "", "end", iid=button,
                    values=(label,
                            mr.trigger_label(binding.get("trigger", "press")),
                            mr.action_label(kind),
                            mr.action_summary(action)))
            else:
                self.tree.insert("", "end", iid=button,
                                 values=(label, "—", "—", "未绑定"),
                                 tags=("unbound",))

    # -- 操作 -----------------------------------------------------------
    def _save(self) -> bool:
        ok = mr.save_config(self.cfg, self._config_path)
        if not ok:
            self.message.configure(text="配置保存失败", fg=themed(RED))
        return ok

    def _after_change(self, message: str = "已保存"):
        self._save()
        # 只要在配置窗口里改过东西，就保持后台暂停，关闭窗口时统一恢复；
        # 否则刚把左键映射成别的动作，下一次点击本窗口就被拦截了。
        if (self._manage_daemon and self.cfg.get("enabled")
                and not self._paused):
            self._paused = True
            self._keep_paused = False
            try:
                mr.stop_daemon()
            except Exception:
                pass
        self._refresh_devices()
        self._refresh_bindings()
        self.message.configure(text=message, fg=themed(GREEN))

    def _toggle_enabled(self):
        self.cfg["enabled"] = bool(self.enabled_var.get())
        if self._manage_daemon and not self.cfg["enabled"]:
            try:
                mr.stop_daemon()
            except Exception:
                pass
            self._paused = False
            self._keep_paused = False
        elif self._manage_daemon:
            # 配置窗口打开期间保持暂停；关闭窗口时统一拉起
            self._paused = True
            self._keep_paused = False
            try:
                mr.stop_daemon()
            except Exception:
                pass
        self._save()
        self.message.configure(
            text="已启用按键映射；关闭配置窗口后后台生效"
            if self.cfg["enabled"] else "已停用按键映射",
            fg=themed(GREEN))

    def _toggle_device(self):
        device = self._current_device()
        if device is None:
            return
        dev = mr.ensure_device(self.cfg, device["key"], device["label"])
        dev["enabled"] = bool(self.device_enabled_var.get())
        self._after_change("已保存此鼠标的启用状态")

    def _add_binding(self):
        device = self._current_device()
        if device is None:
            return
        preset = ""
        selection = self.tree.selection()
        if selection:
            preset = selection[0]
        dialog = BindingDialog(self, device, preset_button=preset)
        self.wait_window(dialog)
        if not dialog.result:
            return
        result = dialog.result
        existing = (self.cfg.get("devices", {}).get(device["key"], {})
                    .get("bindings", {}).get(result["button"]))
        if existing and not messagebox.askyesno(
                "覆盖映射",
                "%s 已经绑定了一个事件，要用新事件覆盖吗？"
                % mr.button_label(result["button"]), parent=self):
            return
        mr.set_binding(self.cfg, device["key"], device["label"],
                       result["button"], result["trigger"], result["action"])
        self._current_key = device["key"]
        self._after_change("已添加映射：%s → %s" % (
            mr.button_label(result["button"]),
            mr.action_summary(result["action"])))

    def _edit_binding(self):
        device = self._current_device()
        if device is None:
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一条映射", parent=self)
            return
        button = selection[0]
        binding = (self.cfg.get("devices", {}).get(device["key"], {})
                   .get("bindings", {}).get(button))
        if not binding:
            messagebox.showinfo("提示", "这条尚未绑定，点「添加映射」创建",
                                parent=self)
            return
        dialog = BindingDialog(self, device, preset_button=button,
                               binding=binding)
        self.wait_window(dialog)
        if not dialog.result:
            return
        result = dialog.result
        if result["button"] != button:
            other = (self.cfg.get("devices", {}).get(device["key"], {})
                     .get("bindings", {}).get(result["button"]))
            if other and not messagebox.askyesno(
                    "覆盖映射",
                    "%s 已经绑定了一个事件，要用新事件覆盖吗？"
                    % mr.button_label(result["button"]), parent=self):
                return
            mr.remove_binding(self.cfg, device["key"], button)
        mr.set_binding(self.cfg, device["key"], device["label"],
                       result["button"], result["trigger"], result["action"])
        self._after_change("已修改映射")

    def _delete_binding(self):
        device = self._current_device()
        if device is None:
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一条映射", parent=self)
            return
        button = selection[0]
        binding = (self.cfg.get("devices", {}).get(device["key"], {})
                   .get("bindings", {}).get(button))
        if not binding:
            messagebox.showinfo("提示", "这条尚未绑定", parent=self)
            return
        if not messagebox.askyesno(
                "删除映射", "确定删除 %s 的映射吗？" % mr.button_label(button),
                parent=self):
            return
        mr.remove_binding(self.cfg, device["key"], button)
        self._after_change("已删除映射")

    def _test_binding(self):
        device = self._current_device()
        if device is None:
            return
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中一条映射", parent=self)
            return
        button = selection[0]
        binding = (self.cfg.get("devices", {}).get(device["key"], {})
                   .get("bindings", {}).get(button))
        if not binding:
            messagebox.showinfo("提示", "这条尚未绑定", parent=self)
            return
        action = binding.get("action") or {}
        if action.get("type") == "voice_input":
            messagebox.showinfo(
                "语音输入", "语音输入需要按住鼠标语音键说话，无法在这里直接测试。",
                parent=self)
            return
        if mr.action_has_mouse(action):
            messagebox.showinfo(
                "鼠标动作",
                "这个事件会点击/移动真实鼠标；在这里测试可能点到本窗口。\n"
                "请关闭配置窗口后，按绑定按键实际测试。",
                parent=self)
            return
        self.message.configure(text="正在执行：%s" % mr.action_summary(action),
                               fg=themed(AMBER))

        def work():
            ok, msg = mr.execute_action(action)
            # Tk 调用只留给主线程；后台线程通过队列回传结果
            self._ui_queue.put(("test", ok, msg))

        threading.Thread(target=work, daemon=True).start()

    # -- 守护进程状态 ---------------------------------------------------
    def _maybe_autopause(self):
        if not self._manage_daemon or not self._auto_pause:
            return
        if not self.cfg.get("enabled") or not mr.has_any_binding(self.cfg):
            return
        try:
            mr.stop_daemon()
        except Exception:
            return
        self._paused = True
        self._keep_paused = False
        self.foot_hint.configure(
            text="配置期间后台映射已暂停；关闭本窗口后自动恢复。",
            fg=themed(FAINT))
        self.message.configure(text="后台映射已暂停，方便安全配置",
                               fg=themed(AMBER))

    def _toggle_pause(self):
        if self._paused:
            result = mr.start_daemon()
            self._paused = False
            self._keep_paused = False
            self.message.configure(
                text="后台映射已恢复" if result.get("ok") else
                result.get("message", "启动失败"),
                fg=themed(GREEN if result.get("ok") else RED))
        else:
            self._paused = True
            self._keep_paused = True
            mr.stop_daemon()
            self.message.configure(text="后台映射已暂停", fg=themed(AMBER))
        self.pause_btn.configure(text="恢复映射" if self._paused else "暂停映射")

    def _resume_if_needed(self):
        if not self._manage_daemon or not self._paused or self._keep_paused:
            return
        # 主面板「完全退出」正在销毁子窗口：不要再拉起后台映射
        if getattr(self.master, "_exiting_all", False):
            return
        if not self.cfg.get("enabled") or not mr.has_any_binding(self.cfg):
            return
        try:
            # 不阻塞 Tk 主线程：关闭窗口后让守护进程在后台起来
            threading.Thread(target=mr.start_daemon, kwargs={"wait": 2.0},
                             daemon=True, name="mouse-remap-start").start()
        except Exception:
            pass

    def _close(self):
        if self._destroyed:
            return
        self._destroyed = True
        self._save()
        self._resume_if_needed()
        if self._on_close_cb:
            try:
                self._on_close_cb()
            except Exception:
                pass
        self.destroy()

    def destroy(self):
        if not self._destroyed:
            self._destroyed = True
            self._save()
            self._resume_if_needed()
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        super().destroy()

    def _poll_status(self):
        try:
            while True:
                try:
                    item = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "test":
                    _kind, ok, msg = item
                    self.message.configure(
                        text=("测试成功：" if ok else "测试失败：") + msg,
                        fg=themed(GREEN if ok else RED))
            status = mr.read_status()
            pid = mr.daemon_pid()
            if pid:
                flags = ["钩子✓" if status.get("hook") else "钩子✗",
                         "Raw✓" if status.get("raw") else "Raw✗"]
                if status.get("voice"):
                    flags.append("语音✓")
                try:
                    unmatched = int(status.get("unmatched") or 0)
                except (TypeError, ValueError):
                    unmatched = 0
                if unmatched:
                    flags.append("未识别设备 %d" % unmatched)
                text = "后台：运行中 · PID %d" % pid
                if flags:
                    text += " · " + " ".join(flags)
                self.daemon_label.configure(text=text, fg=themed(GREEN))
                if status.get("last_error"):
                    self.message.configure(
                        text="后台错误：%s" % status["last_error"],
                        fg=themed(RED))
                elif status.get("last_action"):
                    result = status.get("last_result") or ""
                    text = "最近动作：%s" % status["last_action"]
                    if result:
                        text += " · %s" % result
                    failed = "失败" in result or "异常" in result
                    self.message.configure(
                        text=text,
                        fg=themed(RED if failed else SUB))
            elif self._paused:
                self.daemon_label.configure(text="后台：已暂停（配置中）",
                                            fg=themed(AMBER))
            else:
                self.daemon_label.configure(text="后台：未运行",
                                            fg=themed(FAINT))
            self.pause_btn.configure(
                text="恢复映射" if self._paused else "暂停映射")
        except Exception:
            # 状态文件/进程查询出问题也不能让轮询链断掉
            pass
        finally:
            try:
                self._poll_id = self.after(1000, self._poll_status)
            except tk.TclError:
                pass


def open_window(parent, on_close=None, config_path=None,
                auto_pause=True) -> MouseMappingWindow:
    return MouseMappingWindow(parent, on_close=on_close,
                              config_path=config_path,
                              auto_pause=auto_pause)


def main(argv=None) -> int:
    import argparse
    from version import __version__
    parser = argparse.ArgumentParser(description="鼠标按键映射")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print("Wireless HID Toolbox v%s" % __version__)
        return 0
    root = tk.Tk()
    root.withdraw()
    root.configure(bg=BG)
    theme.setup(root, "panel")
    # 独立进程打开时，关闭映射窗口要结束 Tk 主循环，否则隐藏的 root
    # 会让进程一直挂着。
    MouseMappingWindow(root, on_close=lambda: root.after(0, root.destroy))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
