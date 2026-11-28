# -*- coding: utf-8 -*-
"""mouse_remap.py —— 鼠标按键映射（拦截物理按键 → 触发自定义事件）。

设计要点
--------
* **设备识别**：Windows Raw Input 能区分 ``VID:PID``，但拿不到“拦截权”；
  Low-Level Mouse Hook（``WH_MOUSE_LL``）能拦截，却拿不到设备。
  两者放在不同线程里：钩子拦截时最多等 12ms，等 Raw Input 线程送来
  同一次物理按键，再决定「吞掉并触发」还是「放行」。
* **设备选择**：每个设备独立开关；只拦截已启用设备上已绑定的按键。
  多鼠标同时连接时按 VID:PID 区分；识别不到设备时只有在「仅一台鼠标」
  的保守场景下才按映射处理，避免误吞别的鼠标。
* **动作**：鼠标原有功能（单击/双击/长按）、键盘组合、打开应用、
  组合事件、宏定义、语音输入（仅魔声 248A:60AB 的语音键）。
* **后台**：真正的监听跑在独立进程 ``main.py --tool mouse-remap`` 里，
  单实例互斥；关掉配置窗口不影响映射。配置写入后守护进程自动热重载。

本模块不创建 Tk 窗口（界面在 ``mouse_mapping_panel.py``），
可在测试里直接导入纯函数做校验。
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes
from typing import Optional

import mouse_events as me
import tray_common as tc
import voice_typing as vt

try:
    import hid_win
except Exception:              # pragma: no cover - 只在异常环境触发
    hid_win = None

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
CONFIG_PATH = os.environ.get(
    "MOUSE_MAP_CONFIG", os.path.join(tc.RUNTIME_DIR, "mouse_map.json"))
STATUS_PATH = os.environ.get(
    "MOUSE_MAP_STATUS", os.path.join(tc.RUNTIME_DIR, "mouse_map_status.json"))
STOP_PATH = os.environ.get(
    "MOUSE_MAP_STOP", os.path.join(tc.RUNTIME_DIR, "mouse_map.stop"))
MUTEX_NAME = "Local\\ExtBatteryTrayMouseRemap"

VOICE_DEVICE = "248A:60AB"
VOICE_KEY = "voice_key"

BUTTONS = [
    ("left", "左键"),
    ("right", "右键"),
    ("middle", "中键"),
    ("side1", "侧键 1"),
    ("side2", "侧键 2"),
    ("wheel_up", "滚轮上滚"),
    ("wheel_down", "滚轮下滚"),
]
BUTTON_LABELS = dict(BUTTONS)
BUTTON_LABELS[VOICE_KEY] = "语音键（长按）"
VOICE_BUTTONS = [(VOICE_KEY, BUTTON_LABELS[VOICE_KEY])]

TRIGGERS = [("press", "按下触发"), ("hold", "按住（松开结束）")]
TRIGGER_LABELS = dict(TRIGGERS)

MOUSE_FUNCTIONS = [
    ("left_click", "左键单击"),
    ("right_click", "右键单击"),
    ("middle_click", "中键单击"),
    ("left_double", "左键双击"),
    ("right_double", "右键双击"),
    ("left_long", "左键长按（0.6 秒）"),
    ("right_long", "右键长按（0.6 秒）"),
    ("side1_click", "侧键 1 单击"),
    ("side2_click", "侧键 2 单击"),
    ("side1_double", "侧键 1 双击"),
    ("side2_double", "侧键 2 双击"),
    ("wheel_up", "滚轮上滚"),
    ("wheel_down", "滚轮下滚"),
]
MOUSE_FUNCTION_LABELS = dict(MOUSE_FUNCTIONS)

ACTION_TYPES = [
    ("mouse", "鼠标功能"),
    ("key", "键盘按键"),
    ("system", "系统动作"),
    ("app", "打开应用"),
    ("combo", "组合事件"),
    ("macro", "宏定义"),
    ("voice_input", "语音输入"),
]
ACTION_LABELS = dict(ACTION_TYPES)

# 系统动作：语义化的一步到位操作，省得用户自己查虚拟键码或拼组合键。
# 规格三元组 (执行方式, 参数)：
#   ("vk", 虚拟键码)  —— 单发一个扩展键（媒体/浏览器/音量键必须带
#                        KEYEVENTF_EXTENDEDKEY，否则收不到）
#   ("combo", 组合键) —— 复用 send_key_combo
#   ("call", 名称)    —— 调 Win32 API（目前只有锁屏）
SYSTEM_ACTIONS = [
    # 浏览器 / 资源管理器导航
    ("browser_back", "后退", ("vk", 0xA6)),
    ("browser_forward", "前进", ("vk", 0xA7)),
    ("browser_refresh", "刷新", ("vk", 0xA8)),
    ("browser_stop", "停止加载", ("vk", 0xA9)),
    ("browser_search", "打开搜索", ("vk", 0xAA)),
    ("browser_favorites", "打开收藏夹", ("vk", 0xAB)),
    ("browser_home", "浏览器主页", ("vk", 0xAC)),
    # 媒体与音量
    ("media_play_pause", "播放 / 暂停", ("vk", 0xB3)),
    ("media_next", "下一曲", ("vk", 0xB0)),
    ("media_prev", "上一曲", ("vk", 0xB1)),
    ("media_stop_play", "停止播放", ("vk", 0xB2)),
    ("volume_up", "音量增大", ("vk", 0xAF)),
    ("volume_down", "音量减小", ("vk", 0xAE)),
    ("volume_mute", "静音切换", ("vk", 0xAD)),
    ("launch_media", "打开媒体播放器", ("vk", 0xB5)),
    # 窗口与桌面
    ("show_desktop", "显示桌面", ("combo", "win+d")),
    ("switch_window", "切换窗口", ("combo", "alt+tab")),
    ("task_manager", "任务管理器", ("combo", "ctrl+shift+esc")),
    ("screenshot", "截图（系统）", ("combo", "win+shift+s")),
    ("lock_screen", "锁定屏幕", ("call", "lock")),
    # 编辑快捷键
    ("copy", "复制", ("combo", "ctrl+c")),
    ("paste", "粘贴", ("combo", "ctrl+v")),
    ("cut", "剪切", ("combo", "ctrl+x")),
    ("undo", "撤销", ("combo", "ctrl+z")),
    ("redo", "重做", ("combo", "ctrl+y")),
    ("select_all", "全选", ("combo", "ctrl+a")),
    ("save", "保存", ("combo", "ctrl+s")),
    ("find", "查找", ("combo", "ctrl+f")),
    # 标签页
    ("new_tab", "新建标签页", ("combo", "ctrl+t")),
    ("close_tab", "关闭标签页", ("combo", "ctrl+w")),
    ("reopen_tab", "恢复关闭的标签页", ("combo", "ctrl+shift+t")),
]
SYSTEM_ACTION_LABELS = {key: label for key, label, _spec in SYSTEM_ACTIONS}
SYSTEM_ACTION_SPECS = {key: spec for key, _label, spec in SYSTEM_ACTIONS}

STEP_KINDS = [
    ("key", "按键"),
    ("mouse", "鼠标"),
    ("app", "打开应用"),
    ("text", "输入文字"),
    ("wait", "等待"),
]
STEP_LABELS = dict(STEP_KINDS)

KNOWN_LABELS = {
    "3554:F517": "EWEADN 8K",
    "36B0:3002": "PMO WAVE75",
    "36B0:3009": "PMO WAVE75（USB）",
    "046D:C53F": "罗技 G304 / Lightspeed",
    "248A:60AB": "魔声 AI 垂直鼠标",
    "2F4C:1006": "COLORFUL 键盘",
    "1EA7:0064": "英菲克 F15 无线鼠标",
    "1A2C:7FFF": "狼蛛 S99 三模键盘",
}

# SendInput 鼠标标志
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002
WHEEL_DELTA = 120

# WH_MOUSE_LL
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002
WM_QUIT = 0x0012
KEYEVENTF_EXTENDEDKEY = 0x0001

HOOK_MATCH_TIMEOUT = 0.012      # 等 Raw Input 识别设备的窗口（秒）
_RECENT_RAW_TTL = 2.0
_HOOK_BUTTON_MESSAGES = frozenset({
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP,
    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MOUSEWHEEL,
    WM_XBUTTONDOWN, WM_XBUTTONUP,
})


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _now() -> float:
    return time.monotonic()


def button_label(button: str) -> str:
    return BUTTON_LABELS.get(button, button)


def action_label(action_type: str) -> str:
    return ACTION_LABELS.get(action_type, action_type)


def system_action_label(action_id: str) -> str:
    return SYSTEM_ACTION_LABELS.get(action_id, action_id or "")


def trigger_label(trigger: str) -> str:
    return TRIGGER_LABELS.get(trigger, trigger)


def mouse_function_label(function: str) -> str:
    return MOUSE_FUNCTION_LABELS.get(function, function)


def device_key_from_name(name: str) -> str:
    """从 Raw Input 设备路径解析 ``VID:PID``；解析不到返回空串。"""
    if not name:
        return ""
    match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", name, re.I)
    if match:
        return "%04X:%04X" % (int(match.group(1), 16),
                              int(match.group(2), 16))
    low = name.upper()
    if "ROOT#MOUSE" in low:
        return "ROOT:MOUSE"
    return ""


def is_voice_device(device_key: str) -> bool:
    return (device_key or "").upper() == VOICE_DEVICE


def list_mice() -> list[dict]:
    """枚举当前连接的鼠标（按 VID:PID 聚合），返回 key/label/handles。

    与 ``mouse_events.list_test_devices`` 的差别：这里只关心鼠标接口，
    不把复合设备的鼠标集合归到键盘类别，保证“所有鼠标都能配置”。
    """
    labels = {}
    try:
        for item in me.list_test_devices():
            labels[item.get("base", "")] = item.get("label", "")
    except Exception:
        pass
    products = {}
    if hid_win is not None:
        try:
            for dev in hid_win.enumerate_hid():
                if getattr(dev, "product", ""):
                    products[(dev.vid, dev.pid)] = dev.product
        except Exception:
            pass

    groups: dict[str, dict] = {}
    for handle, typ, name in me.list_raw_devices():
        if typ != me.RIM_TYPEMOUSE:
            continue
        key = device_key_from_name(name)
        if not key or key in ("ROOT:MOUSE", "ROOT:KEYBOARD"):
            continue
        group = groups.setdefault(key, {
            "key": key, "label": "", "handles": [],
        })
        group["handles"].append(int(handle))
        if not group["label"]:
            group["label"] = (labels.get(key) or KNOWN_LABELS.get(key)
                              or _product_for(key, products) or key)

    out = []
    for key, group in groups.items():
        group["label"] = (KNOWN_LABELS.get(key) or labels.get(key)
                          or group["label"] or key)
        group["connected"] = True
        group["voice"] = is_voice_device(key)
        out.append(group)
    out.sort(key=lambda item: (0 if item.get("voice") else 1,
                               item.get("label", "")))
    return out


def _product_for(key: str, products: dict) -> str:
    try:
        vid_text, pid_text = key.split(":", 1)
        return products.get((int(vid_text, 16), int(pid_text, 16)), "")
    except Exception:
        return ""


def connected_device_keys() -> set[str]:
    return {item["key"] for item in list_mice()}


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def default_config() -> dict:
    return {"version": 1, "enabled": False, "devices": {}}


def load_config(path: str | None = None) -> dict:
    path = path or CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = None
    return normalize_config(data)


def save_config(cfg: dict, path: str | None = None) -> bool:
    path = path or CONFIG_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(normalize_config(cfg), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def config_mtime(path: str | None = None) -> float:
    try:
        return os.path.getmtime(path or CONFIG_PATH)
    except OSError:
        return 0.0


def normalize_config(data) -> dict:
    out = default_config()
    if not isinstance(data, dict):
        return out
    out["enabled"] = bool(data.get("enabled", False))
    devices = data.get("devices")
    if not isinstance(devices, dict):
        return out
    valid_buttons = set(BUTTON_LABELS)
    for key, dev in devices.items():
        if not isinstance(dev, dict):
            continue
        key = str(key).upper()
        out_dev = {
            "name": str(dev.get("name") or KNOWN_LABELS.get(key) or key),
            "enabled": bool(dev.get("enabled", True)),
            "bindings": {},
        }
        raw = dev.get("bindings")
        if isinstance(raw, dict):
            for button, binding in raw.items():
                button = str(button)
                if button not in valid_buttons or not isinstance(binding, dict):
                    continue
                action = binding.get("action")
                if not isinstance(action, dict):
                    continue
                trigger = binding.get("trigger", "press")
                if trigger not in dict(TRIGGERS):
                    trigger = "press"
                out_dev["bindings"][button] = {
                    "button": button,
                    "trigger": trigger,
                    "action": normalize_action(action),
                    "updated": float(binding.get("updated") or 0),
                }
        out["devices"][key] = out_dev
    return out


def normalize_action(action: dict) -> dict:
    action = dict(action or {})
    kind = action.get("type", "")
    if kind == "mouse":
        return {"type": "mouse",
                "function": str(action.get("function") or "left_click")}
    if kind == "key":
        return {"type": "key", "keys": str(action.get("keys") or "")}
    if kind == "app":
        return {"type": "app", "path": str(action.get("path") or ""),
                "args": str(action.get("args") or "")}
    if kind in ("combo", "macro"):
        steps = []
        for step in action.get("steps") or []:
            steps.append(normalize_step(step))
        return {"type": kind, "steps": steps}
    if kind == "voice_input":
        return {"type": "voice_input", "mode": "input"}
    return dict(action)


def normalize_step(step) -> dict:
    if not isinstance(step, dict):
        step = {}
    kind = str(step.get("kind") or "key")
    if kind not in dict(STEP_KINDS):
        kind = "key"
    try:
        delay = int(step.get("delay_ms") or 0)
    except (TypeError, ValueError):
        delay = 0
    return {
        "kind": kind,
        "value": str(step.get("value") if step.get("value") is not None
                     else ""),
        "args": str(step.get("args") or ""),
        "delay_ms": max(0, min(delay, 600000)),
    }


def ensure_device(cfg: dict, device_key: str, name: str = "") -> dict:
    device_key = str(device_key).upper()
    devices = cfg.setdefault("devices", {})
    dev = devices.get(device_key)
    if not isinstance(dev, dict):
        dev = {"name": name or KNOWN_LABELS.get(device_key) or device_key,
               "enabled": True, "bindings": {}}
        devices[device_key] = dev
    if name and not dev.get("name"):
        dev["name"] = name
    dev.setdefault("enabled", True)
    dev.setdefault("bindings", {})
    return dev


def set_binding(cfg: dict, device_key: str, name: str, button: str,
                trigger: str, action: dict) -> dict:
    dev = ensure_device(cfg, device_key, name)
    dev["bindings"][button] = {
        "button": button,
        "trigger": trigger,
        "action": normalize_action(action),
        "updated": time.time(),
    }
    return cfg


def remove_binding(cfg: dict, device_key: str, button: str) -> bool:
    dev = cfg.get("devices", {}).get(str(device_key).upper())
    if not isinstance(dev, dict):
        return False
    bindings = dev.get("bindings", {})
    if button in bindings:
        bindings.pop(button, None)
        return True
    return False


def binding_at(cfg: dict, device_key: str, button: str) -> Optional[dict]:
    dev = cfg.get("devices", {}).get(str(device_key).upper())
    if not isinstance(dev, dict) or not dev.get("enabled", True):
        return None
    return (dev.get("bindings") or {}).get(button)


def enabled_bindings(cfg: dict):
    """迭代 (设备 key, 设备名, 按键, 绑定)，只包含启用设备。"""
    if not cfg.get("enabled"):
        return
    for key, dev in (cfg.get("devices") or {}).items():
        if not isinstance(dev, dict) or not dev.get("enabled", True):
            continue
        for button, binding in (dev.get("bindings") or {}).items():
            if isinstance(binding, dict):
                yield key, dev.get("name", key), button, binding


def has_any_binding(cfg: dict) -> bool:
    return any(True for _ in enabled_bindings(cfg))


def voice_binding(cfg: dict):
    """返回启用的语音键绑定 (device_key, binding)；没有返回 None。"""
    for key, name, button, binding in enabled_bindings(cfg) or []:
        if key == VOICE_DEVICE and button == VOICE_KEY:
            action = binding.get("action") or {}
            if action.get("type") == "voice_input":
                return key, binding
    return None


def action_has_mouse(action: dict) -> bool:
    """动作里是否包含会移动/点击真实鼠标的步骤（用于安全提示）。"""
    action = action or {}
    if action.get("type") == "mouse":
        return True
    if action.get("type") in ("combo", "macro"):
        return any((step or {}).get("kind") == "mouse"
                   for step in action.get("steps") or [])
    return False


def action_summary(action: dict) -> str:
    action = action or {}
    kind = action.get("type")
    if kind == "mouse":
        return mouse_function_label(action.get("function", ""))
    if kind == "key":
        return "按键 " + (action.get("keys") or "（未设置）")
    if kind == "app":
        path = action.get("path") or ""
        args = action.get("args") or ""
        name = os.path.basename(path.rstrip("\\/")) or path or "（未设置）"
        return "打开 %s%s" % (name, (" " + args) if args else "")
    if kind == "system":
        return system_action_label(action.get("action", "")) or "（未选择）"
    if kind == "combo":
        return "组合事件（%d 步）" % len(action.get("steps") or [])
    if kind == "macro":
        return "宏定义（%d 步）" % len(action.get("steps") or [])
    if kind == "voice_input":
        return "语音输入到焦点输入框"
    return action_label(kind or "?")


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def validate_action(action: dict, device_key: str = "",
                    button: str = "") -> tuple[bool, str]:
    action = action or {}
    kind = action.get("type")
    if kind not in dict(ACTION_TYPES):
        return False, "未知事件类型"
    if kind == "voice_input":
        if not is_voice_device(device_key):
            return False, "语音输入仅支持魔声 AI 垂直鼠标（248A:60AB）"
        if button != VOICE_KEY:
            return False, "语音输入只能绑定到魔声鼠标的语音键"
        return True, ""
    if button == VOICE_KEY:
        return False, "语音键只能绑定「语音输入」"
    if kind == "mouse":
        if action.get("function") not in MOUSE_FUNCTION_LABELS:
            return False, "请选择鼠标功能"
        return True, ""
    if kind == "key":
        sequence, error = parse_key_combo(action.get("keys", ""))
        if error:
            return False, error
        if not sequence:
            return False, "请填写按键组合"
        return True, ""
    if kind == "system":
        if action.get("action") not in SYSTEM_ACTION_LABELS:
            return False, "请选择系统动作"
        return True, ""
    if kind == "app":
        if not (action.get("path") or "").strip():
            return False, "请选择要打开的应用"
        return True, ""
    if kind in ("combo", "macro"):
        steps = action.get("steps") or []
        if not steps:
            return False, "请至少添加一个步骤"
        for index, step in enumerate(steps, 1):
            ok, error = validate_step(step, macro=(kind == "macro"))
            if not ok:
                return False, "第 %d 步：%s" % (index, error)
        return True, ""
    return False, "未知事件类型"


def validate_step(step: dict, macro: bool = True) -> tuple[bool, str]:
    kind = step.get("kind")
    value = (step.get("value") or "").strip()
    if kind not in dict(STEP_KINDS):
        return False, "未知步骤类型"
    if kind == "wait":
        try:
            ms = int(value)
        except (TypeError, ValueError):
            return False, "等待时间需要填毫秒数"
        if ms < 0 or ms > 600000:
            return False, "等待时间需在 0~600000 毫秒之间"
        return True, ""
    if not value and kind not in ("text",):
        return False, "步骤内容不能为空"
    if kind == "key":
        sequence, error = parse_key_combo(value)
        return (False, error) if error else (True, "")
    if kind == "mouse":
        if value not in MOUSE_FUNCTION_LABELS:
            return False, "请选择鼠标功能"
        return True, ""
    if kind == "app":
        return True, ""
    if kind == "text":
        if not macro:
            return False, "组合事件不支持「输入文字」，请改用宏定义"
        if not value:
            return False, "文字内容不能为空"
        return True, ""
    return False, "未知步骤类型"


def validate_binding(device_key: str, button: str, trigger: str,
                     action: dict) -> tuple[bool, str]:
    if button not in BUTTON_LABELS:
        return False, "未知鼠标按键"
    if trigger not in dict(TRIGGERS):
        return False, "未知触发方式"
    ok, error = validate_action(action, device_key, button)
    if not ok:
        return False, error
    if button == VOICE_KEY and trigger != "hold":
        return False, "语音键必须使用「按住」触发"
    if trigger == "hold" and button != VOICE_KEY:
        return False, "「按住」触发只用于语音键"
    return True, ""


# ---------------------------------------------------------------------------
# 键盘组合
# ---------------------------------------------------------------------------
MODIFIER_KEYS = {
    "ctrl": (0x11, False), "control": (0x11, False),
    "lctrl": (0xA2, False), "rctrl": (0xA3, True),
    "shift": (0x10, False), "lshift": (0xA0, False),
    "rshift": (0xA1, False),
    "alt": (0x12, False), "lalt": (0xA4, False), "ralt": (0xA5, True),
    "win": (0x5B, True), "meta": (0x5B, True), "lwin": (0x5B, True),
    "rwin": (0x5C, True),
}

NAMED_KEYS = {
    "backspace": (0x08, False), "tab": (0x09, False),
    "enter": (0x0D, False), "return": (0x0D, False),
    "esc": (0x1B, False), "escape": (0x1B, False),
    "space": (0x20, False), "spacebar": (0x20, False),
    "pageup": (0x21, True), "pagedown": (0x22, True),
    "end": (0x23, True), "home": (0x24, True),
    "left": (0x25, True), "up": (0x26, True),
    "right": (0x27, True), "down": (0x28, True),
    "insert": (0x2D, True), "delete": (0x2E, True),
    "printscreen": (0x2C, True), "pause": (0x13, False),
    "capslock": (0x14, False), "numlock": (0x90, True),
    "scrolllock": (0x91, False), "apps": (0x5D, True),
    "volumeup": (0xAF, True), "volumedown": (0xAE, True),
    "volumemute": (0xAD, True),
    "medianext": (0xB0, True), "mediaprev": (0xB1, True),
    "mediastop": (0xB2, True), "mediaplaypause": (0xB3, True),
    "numpad0": (0x60, False), "numpad1": (0x61, False),
    "numpad2": (0x62, False), "numpad3": (0x63, False),
    "numpad4": (0x64, False), "numpad5": (0x65, False),
    "numpad6": (0x66, False), "numpad7": (0x67, False),
    "numpad8": (0x68, False), "numpad9": (0x69, False),
    "multiply": (0x6A, False), "add": (0x6B, False),
    "separator": (0x6C, False), "subtract": (0x6D, False),
    "decimal": (0x6E, False), "divide": (0x6F, True),
    "`": (0xC0, False), "~": (0xC0, False),
    "-": (0xBD, False), "=": (0xBB, False),
    "[": (0xDB, False), "]": (0xDD, False),
    "\\": (0xDC, False), ";": (0xBA, False),
    "'": (0xDE, False), ",": (0xBC, False),
    ".": (0xBE, False), "/": (0xBF, False),
}
for _index in range(1, 25):
    NAMED_KEYS["f%d" % _index] = (0x6F + _index, False)


def _key_token(token: str) -> Optional[tuple[int, bool]]:
    low = token.strip().lower()
    if not low:
        return None
    if low in MODIFIER_KEYS:
        return MODIFIER_KEYS[low]
    if low in NAMED_KEYS:
        return NAMED_KEYS[low]
    if len(token) == 1:
        char = token
        if char.isalpha():
            return (ord(char.upper()), False)
        if char.isdigit():
            return (ord(char), False)
    return None


def parse_key_combo(text: str) -> tuple[list[tuple[int, bool]], str]:
    """把 ``ctrl+shift+c`` 解析成 [(vk, extended), ...]（按下顺序）。

    返回 ``(序列, 错误)``；错误非空时序列为空。修饰键按书写顺序，
    主键放在最后；执行时先按下全部、再逆序松开。
    """
    text = (text or "").strip()
    if not text:
        return [], "请填写按键组合"
    tokens = [part for part in re.split(r"\+", text) if part.strip()]
    if not tokens:
        return [], "请填写按键组合"
    sequence: list[tuple[int, bool]] = []
    main_seen = False
    for index, token in enumerate(tokens):
        low = token.strip().lower()
        mod = MODIFIER_KEYS.get(low)
        if mod is not None:
            if main_seen:
                return [], "修饰键必须写在主键前面"
            sequence.append(mod)
            continue
        key = _key_token(token)
        if key is None:
            return [], "无法识别的按键：%s" % token.strip()
        if index != len(tokens) - 1:
            return [], "组合键只能有一个主键"
        main_seen = True
        sequence.append(key)
    if not main_seen:
        return [], "组合键缺少主键（例如 ctrl+c）"
    return sequence, ""


def build_key_inputs(text: str) -> list:
    """构造按键组合的 SendInput 数组；解析失败抛 ValueError。"""
    sequence, error = parse_key_combo(text)
    if error:
        raise ValueError(error)
    inputs = []
    for vk, extended in sequence:
        inputs.append(_key_input(vk, down=True, extended=extended))
    for vk, extended in reversed(sequence):
        inputs.append(_key_input(vk, down=False, extended=extended))
    return inputs


def _key_input(vk: int, down: bool, extended: bool = False):
    item = vt.INPUT()
    item.type = vt.INPUT_KEYBOARD
    item.u.ki.wVk = int(vk) & 0xFFFF
    item.u.ki.wScan = 0
    flags = 0 if down else vt.KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    item.u.ki.dwFlags = flags
    item.u.ki.time = 0
    item.u.ki.dwExtraInfo = None
    return item


def send_key_combo(text: str) -> tuple[bool, str]:
    try:
        inputs = build_key_inputs(text)
    except ValueError as exc:
        return False, str(exc)
    ok = vt.send_inputs(inputs)
    return (ok, "已发送按键 %s" % text if ok else "SendInput 被拒绝")


def _system_call(name: str) -> tuple[bool, str]:
    """调用 Win32 API 类的系统动作。"""
    if name == "lock":
        try:
            ok = bool(ctypes.windll.user32.LockWorkStation())
        except Exception as exc:
            return False, "锁屏失败：%r" % (exc,)
        return (True, "已锁定屏幕") if ok else (False, "锁屏被系统拒绝")
    return False, "未知系统调用"


def send_system_action(action_id: str) -> tuple[bool, str]:
    """执行一个系统动作（浏览器导航 / 媒体控制 / 音量 / 快捷键）。"""
    spec = SYSTEM_ACTION_SPECS.get(action_id)
    if spec is None:
        return False, "未知系统动作"
    label = system_action_label(action_id)
    kind, arg = spec
    if kind == "combo":
        ok, msg = send_key_combo(arg)
        return ok, msg if ok else "%s失败：%s" % (label, msg)
    if kind == "call":
        return _system_call(arg)
    # 单键：媒体/浏览器/音量键都是扩展键，必须带 KEYEVENTF_EXTENDEDKEY，
    # 否则前台程序收不到（这是这类键最容易踩的坑）
    inputs = [_key_input(arg, True, extended=True),
              _key_input(arg, False, extended=True)]
    ok = vt.send_inputs(inputs)
    return (ok, "已发送%s" % label) if ok else (False, "SendInput 被拒绝")


# ---------------------------------------------------------------------------
# 鼠标功能
# ---------------------------------------------------------------------------
def _mouse_input(flags: int, data: int = 0):
    item = vt.INPUT()
    item.type = 0                      # INPUT_MOUSE
    item.u.mi.dx = 0
    item.u.mi.dy = 0
    item.u.mi.mouseData = int(data) & 0xFFFFFFFF
    item.u.mi.dwFlags = flags
    item.u.mi.time = 0
    item.u.mi.dwExtraInfo = None
    return item


def _click_inputs(button: str, down: bool) -> list:
    if button == "left":
        return [_mouse_input(MOUSEEVENTF_LEFTDOWN if down
                             else MOUSEEVENTF_LEFTUP)]
    if button == "right":
        return [_mouse_input(MOUSEEVENTF_RIGHTDOWN if down
                             else MOUSEEVENTF_RIGHTUP)]
    if button == "middle":
        return [_mouse_input(MOUSEEVENTF_MIDDLEDOWN if down
                             else MOUSEEVENTF_MIDDLEUP)]
    if button == "side1":
        return [_mouse_input(MOUSEEVENTF_XDOWN if down
                             else MOUSEEVENTF_XUP, XBUTTON1)]
    if button == "side2":
        return [_mouse_input(MOUSEEVENTF_XDOWN if down
                             else MOUSEEVENTF_XUP, XBUTTON2)]
    return []


def send_mouse_click(button: str = "left") -> bool:
    inputs = _click_inputs(button, True) + _click_inputs(button, False)
    return vt.send_inputs(inputs)


def send_mouse_function(function: str) -> tuple[bool, str]:
    if function not in MOUSE_FUNCTION_LABELS:
        return False, "未知鼠标功能"
    if function.endswith("_click"):
        button = function[:-6]
        ok = send_mouse_click(button)
        return (ok, "已发送%s" % mouse_function_label(function)
                if ok else "SendInput 被拒绝")
    if function.endswith("_double"):
        button = function[:-7]
        ok = send_mouse_click(button)
        if ok:
            time.sleep(0.08)
            ok = send_mouse_click(button)
        return (ok, "已发送%s" % mouse_function_label(function)
                if ok else "SendInput 被拒绝")
    if function.endswith("_long"):
        button = function[:-5]
        ok = vt.send_inputs(_click_inputs(button, True))
        if ok:
            time.sleep(0.6)
            vt.send_inputs(_click_inputs(button, False))
        return (ok, "已发送%s" % mouse_function_label(function)
                if ok else "SendInput 被拒绝")
    if function in ("wheel_up", "wheel_down"):
        delta = WHEEL_DELTA if function == "wheel_up" else -WHEEL_DELTA
        data = (delta & 0xFFFF) << 16
        ok = vt.send_inputs([_mouse_input(MOUSEEVENTF_WHEEL, data)])
        return (ok, "已发送%s" % mouse_function_label(function)
                if ok else "SendInput 被拒绝")
    return False, "未知鼠标功能"


# ---------------------------------------------------------------------------
# 动作执行
# ---------------------------------------------------------------------------
def launch_app(path: str, args: str = "") -> tuple[bool, str]:
    path = (path or "").strip().strip('"')
    path = os.path.expandvars(os.path.expanduser(path))
    if not path:
        return False, "应用路径为空"
    args = (args or "").strip()
    try:
        if args:
            if path.lower().endswith(".lnk"):
                # 快捷方式只能交给 ShellExecute；忽略参数并提示
                starter = getattr(os, "startfile", None)
                if starter is None:
                    return False, "当前环境无法启动快捷方式"
                starter(path)
                return True, "已打开 %s（快捷方式参数已忽略）" % (
                    os.path.basename(path) or path)
            argv = [path] + shlex.split(args, posix=False)
            if path.lower().endswith((".bat", ".cmd")):
                # CreateProcess 不能直接执行批处理，必须经 cmd /c
                argv = [os.environ.get("COMSPEC", "cmd.exe"), "/c"] + argv
            subprocess.Popen(argv, cwd=os.path.dirname(path) or None,
                             close_fds=True)
        else:
            starter = getattr(os, "startfile", None)
            if starter is None:
                subprocess.Popen([path], cwd=os.path.dirname(path) or None,
                                 close_fds=True)
            else:
                starter(path)
        return True, "已打开 %s" % (os.path.basename(path) or path)
    except Exception as exc:
        return False, "打开失败：%r" % (exc,)


def execute_action(action: dict, logger=None) -> tuple[bool, str]:
    """同步执行一个事件动作；返回 (成功, 说明)。"""
    action = action or {}
    kind = action.get("type")
    log = logger or (lambda _msg: None)
    if kind == "mouse":
        ok, msg = send_mouse_function(action.get("function", ""))
        log(msg)
        return ok, msg
    if kind == "key":
        ok, msg = send_key_combo(action.get("keys", ""))
        log(msg)
        return ok, msg
    if kind == "system":
        ok, msg = send_system_action(action.get("action", ""))
        log(msg)
        return ok, msg
    if kind == "app":
        ok, msg = launch_app(action.get("path", ""), action.get("args", ""))
        log(msg)
        return ok, msg
    if kind in ("combo", "macro"):
        return execute_steps(action.get("steps") or [], logger)
    if kind == "voice_input":
        msg = "语音输入由语音键触发，不能直接执行"
        log(msg)
        return False, msg
    msg = "未知事件类型"
    log(msg)
    return False, msg


def execute_steps(steps: list, logger=None) -> tuple[bool, str]:
    log = logger or (lambda _msg: None)
    for index, step in enumerate(steps, 1):
        kind = step.get("kind")
        value = step.get("value") or ""
        if kind == "wait":
            try:
                ms = int(value)
            except (TypeError, ValueError):
                ms = 0
            time.sleep(max(0, min(ms, 600000)) / 1000.0)
            continue
        if kind == "text":
            ok, msg = vt.type_text(value)
        elif kind == "key":
            ok, msg = send_key_combo(value)
        elif kind == "mouse":
            ok, msg = send_mouse_function(value)
        elif kind == "app":
            ok, msg = launch_app(value, step.get("args", ""))
        else:
            ok, msg = False, "未知步骤类型"
        log("第 %d 步：%s" % (index, msg))
        if not ok:
            return False, "第 %d 步失败：%s" % (index, msg)
        delay = int(step.get("delay_ms") or 0)
        if delay > 0:
            time.sleep(min(delay, 600000) / 1000.0)
    return True, "已完成 %d 步" % len(steps)


class ActionRunner:
    """串行执行动作的后台线程；绝不阻塞鼠标钩子。"""

    def __init__(self, logger=None):
        self._queue: queue.Queue = queue.Queue()
        self._logger = logger or (lambda _msg: None)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="mouse-remap-actions")
        self._last_ok = True
        self._last_message = ""

    def start(self) -> None:
        self._thread.start()

    def submit(self, action: dict) -> None:
        self._queue.put(action)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                action = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                ok, message = execute_action(action, self._logger)
                self._last_ok = ok
                self._last_message = message
            except Exception as exc:
                self._last_ok = False
                self._last_message = "动作异常：%r" % (exc,)
                self._logger(self._last_message)

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    @property
    def last_message(self) -> str:
        return self._last_message


# ---------------------------------------------------------------------------
# Raw Input 事件缓冲（给钩子做设备关联）
# ---------------------------------------------------------------------------
class RawEvent:
    __slots__ = ("ts", "handle", "button", "action", "consumed")

    def __init__(self, ts: float, handle: int, button: str, action: str):
        self.ts = ts
        self.handle = handle
        self.button = button
        self.action = action
        self.consumed = False


class RawEventBuffer:
    """保存最近 2 秒的 Raw Input 按键，钩子用它关联设备。"""

    def __init__(self):
        self._items: deque[RawEvent] = deque()
        self._cond = threading.Condition()

    def push(self, handle: int, button: str, action: str,
             ts: float | None = None) -> None:
        ts = _now() if ts is None else ts
        with self._cond:
            self._items.append(RawEvent(ts, int(handle or 0), button, action))
            cutoff = ts - _RECENT_RAW_TTL
            while self._items and self._items[0].ts < cutoff:
                self._items.popleft()
            self._cond.notify_all()

    def wait_match(self, button: str, action: str, since: float,
                   timeout: float = HOOK_MATCH_TIMEOUT) -> Optional[RawEvent]:
        deadline = since + max(0.0, timeout)
        with self._cond:
            while True:
                best = None
                for item in self._items:
                    if item.consumed:
                        continue
                    if item.button != button or item.action != action:
                        continue
                    if item.ts < since - 0.05:
                        continue
                    best = item
                    break
                if best is not None:
                    best.consumed = True
                    return best
                remaining = deadline - _now()
                if remaining <= 0:
                    return None
                self._cond.wait(min(remaining, 0.005))

    def clear(self) -> None:
        with self._cond:
            self._items.clear()


# ---------------------------------------------------------------------------
# Low-Level Mouse Hook
# ---------------------------------------------------------------------------
_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", _POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


_USER32.SetWindowsHookExW.restype = ctypes.c_void_p
_USER32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC,
                                      wintypes.HINSTANCE, wintypes.DWORD]
_USER32.CallNextHookEx.restype = ctypes.c_ssize_t
_USER32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM]
_USER32.UnhookWindowsHookEx.restype = wintypes.BOOL
_USER32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_USER32.GetMessageW.restype = wintypes.BOOL
_USER32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
_USER32.PostThreadMessageW.restype = wintypes.BOOL
_USER32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
_USER32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_USER32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_KERNEL32.GetModuleHandleW.restype = wintypes.HINSTANCE
_KERNEL32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_KERNEL32.GetCurrentThreadId.restype = wintypes.DWORD


class MouseHook(threading.Thread):
    """在独立线程安装 WH_MOUSE_LL；``decide`` 返回 True 表示吞掉事件。"""

    def __init__(self, decide):
        super().__init__(daemon=True, name="mouse-remap-hook")
        self.decide = decide
        self.error = ""
        self._hook = None
        self._proc = _HOOKPROC(self._callback)
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._thread_id = 0
        self._running = False

    def start(self, timeout: float = 2.0) -> bool:
        super().start()
        if not self._ready.wait(timeout):
            raise RuntimeError("鼠标钩子启动超时")
        if self.error:
            raise RuntimeError(self.error)
        return True

    def stop(self) -> None:
        self._running = False
        tid = self._thread_id
        if tid:
            _USER32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if self.is_alive():
            self._stopped.wait(2.0)

    def _callback(self, ncode, wparam, lparam):
        if ncode < 0 or not self._running:
            return _USER32.CallNextHookEx(None, ncode, wparam, lparam)
        # 鼠标移动占绝大多数；先用 wparam 粗筛，避免每个移动报告都做
        # ctypes 结构体转换（8K 回报率下差异明显）。
        if wparam not in _HOOK_BUTTON_MESSAGES:
            return _USER32.CallNextHookEx(None, ncode, wparam, lparam)
        try:
            info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            if info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED):
                return _USER32.CallNextHookEx(None, ncode, wparam, lparam)
            parsed = _parse_hook_message(int(wparam), int(info.mouseData))
            if parsed is None:
                return _USER32.CallNextHookEx(None, ncode, wparam, lparam)
            button, action = parsed
            if self.decide(button, action, _now()):
                return 1
        except Exception:
            pass
        return _USER32.CallNextHookEx(None, ncode, wparam, lparam)

    def run(self) -> None:
        try:
            self._thread_id = int(_KERNEL32.GetCurrentThreadId())
            hinst = _KERNEL32.GetModuleHandleW(None)
            self._hook = _USER32.SetWindowsHookExW(
                WH_MOUSE_LL, self._proc, hinst, 0)
            if not self._hook:
                self.error = ("SetWindowsHookExW 失败：%d"
                              % ctypes.get_last_error())
                self._running = False
                self._ready.set()
                return
            self._running = True
            self._ready.set()
            msg = wintypes.MSG()
            while _USER32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _USER32.TranslateMessage(ctypes.byref(msg))
                _USER32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.error = "鼠标钩子异常：%r" % (exc,)
            self._ready.set()
        finally:
            self._running = False
            if self._hook:
                try:
                    _USER32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
                except Exception:
                    pass
                self._hook = None
            self._stopped.set()


def _parse_hook_message(wparam: int, mouse_data: int):
    """把钩子消息解析成 (button, action)；不认识的返回 None。"""
    if wparam == WM_LBUTTONDOWN:
        return "left", "down"
    if wparam == WM_LBUTTONUP:
        return "left", "up"
    if wparam == WM_RBUTTONDOWN:
        return "right", "down"
    if wparam == WM_RBUTTONUP:
        return "right", "up"
    if wparam == WM_MBUTTONDOWN:
        return "middle", "down"
    if wparam == WM_MBUTTONUP:
        return "middle", "up"
    if wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        xbutton = (mouse_data >> 16) & 0xFFFF
        button = "side1" if xbutton == XBUTTON1 else "side2"
        return button, "down" if wparam == WM_XBUTTONDOWN else "up"
    if wparam == WM_MOUSEWHEEL:
        delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
        return ("wheel_up" if delta > 0 else "wheel_down"), "down"
    return None


# ---------------------------------------------------------------------------
# 映射引擎
# ---------------------------------------------------------------------------
class RemapEngine:
    """Raw Input + 鼠标钩子 + 动作执行 + 语音输入。"""

    def __init__(self, cfg: dict | None = None, logger=None):
        self.cfg = normalize_config(cfg or load_config())
        self.logger = logger or (lambda _msg: None)
        self._lock = threading.RLock()
        self._running = False
        self._hook: Optional[MouseHook] = None
        self._raw = None
        self._raw_ok = False
        self._runner = ActionRunner(self.logger)
        self._rawbuf = RawEventBuffer()
        self._mice: list[dict] = []
        self._handle_keys: dict[int, str] = {}
        self._suppressed: set[str] = set()
        self._maint_thread: Optional[threading.Thread] = None
        self._voice = None
        self._voice_status = ""
        self._voice_cfg_mtime = 0.0
        self._last_action = ""
        self._last_error = ""
        self._started_at = 0.0
        self._unmatched = 0
        self._bindings_count = 0
        self._voice_text = ""
        self._cfg_mtime = config_mtime()
        # 钩子线程每个事件都读它；不要在钩子里 deepcopy 配置
        self._snapshot: dict[str, list[tuple[str, dict]]] = \
            self._build_snapshot()

    # -- 生命周期 ------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            self.cfg = normalize_config(self.cfg)
            self._snapshot = self._build_snapshot()
            self._running = True
            self._started_at = time.time()
            self._bindings_count = sum(
                1 for _ in enabled_bindings(self.cfg) or [])
            self._runner.start()
            self._refresh_mice()
            try:
                self._raw = me.RawInputListener(self._on_raw_event,
                                                accept_all=True)
                self._raw.start()
                self._raw_ok = True
            except Exception as exc:
                self._raw_ok = False
                self._last_error = "Raw Input 启动失败：%r" % (exc,)
                self.logger(self._last_error)
            try:
                self._hook = MouseHook(self._decide)
                self._hook.start()
            except Exception as exc:
                self._last_error = "鼠标钩子启动失败：%r" % (exc,)
                self.logger(self._last_error)
                self.stop()
                return False
            self._maint_thread = threading.Thread(
                target=self._maintain, daemon=True,
                name="mouse-remap-maintain")
            self._maint_thread.start()
            self._maybe_voice()
            return True

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        hook = self._hook
        self._hook = None
        if hook is not None:
            try:
                hook.stop()
            except Exception:
                pass
        raw = self._raw
        self._raw = None
        if raw is not None:
            try:
                raw.stop()
            except Exception:
                pass
        self._raw_ok = False
        self._stop_voice()
        self._runner.stop()

    def reload(self, cfg: dict) -> None:
        with self._lock:
            self.cfg = normalize_config(cfg)
            self._bindings_count = sum(
                1 for _ in enabled_bindings(self.cfg) or [])
            self._snapshot = self._build_snapshot()
            self._last_error = ""
        self._suppressed.clear()
        self._maybe_voice()

    def _build_snapshot(self) -> dict[str, list[tuple[str, dict]]]:
        snapshot: dict[str, list[tuple[str, dict]]] = {}
        for key, _name, button, binding in enabled_bindings(self.cfg) or []:
            snapshot.setdefault(button, []).append((key, binding))
        return snapshot

    # -- 设备 ----------------------------------------------------------
    def _refresh_mice(self) -> None:
        try:
            mice = list_mice()
        except Exception:
            mice = []
        handle_keys = {}
        for item in mice:
            for handle in item.get("handles") or []:
                handle_keys[int(handle)] = item["key"]
        with self._lock:
            self._mice = mice
            self._handle_keys = handle_keys

    def _maintain(self) -> None:
        last_refresh = 0.0
        while self._running:
            now = _now()
            if now - last_refresh >= 2.0:
                last_refresh = now
                self._refresh_mice()
                self._maybe_voice()
            time.sleep(0.25)

    # -- Raw Input -----------------------------------------------------
    def _on_raw_event(self, event: dict) -> None:
        # handle=0 是 SendInput/注入事件，不能用来关联物理设备；否则动作
        # 自己注入的点击会污染下一次物理按键的匹配。
        handle = int(event.get("handle") or 0)
        if not handle:
            return
        if event.get("type") == "button":
            self._rawbuf.push(handle, event.get("button", ""),
                              event.get("action", ""), _now())
        elif event.get("type") == "wheel":
            if event.get("horizontal"):
                return                 # 横向滚轮未映射，别污染纵向匹配
            delta = int(event.get("delta") or 0)
            button = "wheel_up" if delta > 0 else "wheel_down"
            self._rawbuf.push(handle, button, "down", _now())

    # -- 钩子决策 ------------------------------------------------------
    def _candidate_bindings(self, button: str) -> list[tuple[str, dict]]:
        # 快照在 reload 时整体替换，钩子线程只读，不需要加锁/deepcopy
        if not self.cfg.get("enabled"):
            return []
        return list(self._snapshot.get(button, ()))

    def _decide(self, button: str, action: str, ts: float) -> bool:
        candidates = self._candidate_bindings(button)
        if not candidates:
            return False
        if action == "up":
            if button in self._suppressed:
                self._suppressed.discard(button)
                return True
            return False
        # 滚轮只有 down、没有配对 up；普通按键的 up 由上面的分支处理
        raw = self._rawbuf.wait_match(button, action, ts)
        device_key = ""
        if raw is not None and raw.handle:
            with self._lock:
                device_key = self._handle_keys.get(raw.handle, "")
        chosen = None
        if device_key:
            chosen = next((item for item in candidates
                           if item[0] == device_key), None)
            if chosen is None:
                return False
        else:
            connected = {item["key"] for item in self._mice}
            mapped = [item for item in candidates if item[0] in connected]
            if len(connected) == 1 and len(mapped) == 1:
                chosen = mapped[0]
            elif not connected and len(candidates) == 1:
                chosen = candidates[0]
            else:
                self._unmatched += 1
                return False
        device_key, binding = chosen
        if button != "wheel_up" and button != "wheel_down":
            self._suppressed.add(button)
        trigger = binding.get("trigger", "press")
        action_obj = binding.get("action") or {}
        if action_obj.get("type") == "voice_input" or trigger == "hold":
            # 语音输入由 HID 语音键驱动，钩子只负责吞掉；正常不会走到这里
            return True
        self._runner.submit(action_obj)
        self._last_action = "%s · %s · %s" % (
            device_key, button_label(button), action_summary(action_obj))
        return True

    # -- 语音 ----------------------------------------------------------
    def _maybe_voice(self) -> None:
        if not self._running:
            return
        need = voice_binding(self.cfg) is not None
        if not need:
            self._stop_voice()
            return
        try:
            mtime = os.path.getmtime(os.path.join(
                tc.RUNTIME_DIR, "voice_config.json"))
        except OSError:
            mtime = 0.0
        if (self._voice is not None and mtime == self._voice_cfg_mtime
                and getattr(self._voice, "alive", lambda: True)()):
            return
        self._stop_voice()
        try:
            import voice_service as vs
            cfg = vs.load_config()
            service = vs.VoiceInputService(
                cfg=cfg, on_status=self._on_voice_status,
                on_text=self._on_voice_text)
            if service.start():
                self._voice = service
                self._voice_cfg_mtime = mtime
                self._last_error = ""
            else:
                self._last_error = service.last_error or "语音输入启动失败"
        except Exception as exc:
            self._last_error = "语音输入组件异常：%r" % (exc,)
            self.logger(self._last_error)

    def _stop_voice(self) -> None:
        service = self._voice
        self._voice = None
        if service is not None:
            try:
                service.stop()
            except Exception:
                pass

    def _on_voice_status(self, text: str) -> None:
        self._voice_status = text
        self.logger("[voice] " + text)

    def _on_voice_text(self, text: str) -> None:
        self._voice_text = text
        self._last_action = "语音输入 · %s" % text

    # -- 状态 ----------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            mice = [{"key": item["key"], "label": item["label"],
                     "voice": bool(item.get("voice"))}
                    for item in self._mice]
            voice_on = self._voice is not None
            return {
                "running": bool(self._running),
                "pid": os.getpid(),
                "started_at": self._started_at,
                "hook": bool(self._hook is not None and self._hook.is_alive()),
                "raw": bool(self._raw_ok),
                "voice": voice_on,
                "voice_status": self._voice_status,
                "voice_text": self._voice_text,
                "devices": mice,
                "bindings": self._bindings_count,
                "last_action": self._last_action,
                "last_result": self._runner.last_message,
                "last_error": self._last_error,
                "unmatched": self._unmatched,
                "updated_at": time.time(),
                "config_mtime": self._cfg_mtime,
            }


# ---------------------------------------------------------------------------
# 守护进程 / 状态文件
# ---------------------------------------------------------------------------
def write_status(status: dict, path: str | None = None) -> None:
    path = path or STATUS_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(status, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def read_status(path: str | None = None) -> dict:
    try:
        with open(path or STATUS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def daemon_pid() -> int:
    status = read_status()
    try:
        pid = int(status.get("pid") or 0)
    except (TypeError, ValueError):
        return 0
    if not pid or not tc.pid_alive(pid):
        return 0
    # PID 可能被系统复用：确认它确实是本工具的 python / exe 进程，
    # 避免 stop_daemon 误杀无关进程。
    try:
        image = (tc.process_image(pid) or "").lower()
    except Exception:
        image = ""
    if image and "python" not in image and "wirelesshidtoolbox" not in image:
        return 0
    return pid


def daemon_running() -> bool:
    return daemon_pid() > 0


def stop_daemon(wait: float = 4.0) -> bool:
    pid = daemon_pid()
    try:
        with open(STOP_PATH, "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
    except OSError:
        pass
    deadline = time.monotonic() + max(0.5, wait)
    while time.monotonic() < deadline:
        if not daemon_pid():
            break
        time.sleep(0.1)
    alive = daemon_pid()
    if alive:
        try:
            tc.kill_pid(alive)
        except Exception:
            pass
    try:
        os.remove(STOP_PATH)
    except OSError:
        pass
    return not daemon_pid()


def _daemon_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tool", "mouse-remap"]
    return [tc.pythonw_path(), os.path.join(tc.BASE_DIR, "main.py"),
            "--tool", "mouse-remap"]


def start_daemon(wait: float = 3.0) -> dict:
    """启动后台映射进程；返回 {ok, pid, message}。"""
    pid = daemon_pid()
    if pid:
        return {"ok": True, "pid": pid, "message": "按键映射已在运行"}
    try:
        os.remove(STOP_PATH)
    except OSError:
        pass
    cmd = _daemon_command()
    try:
        flags = 0x08000000 if os.name == "nt" else 0
        subprocess.Popen(
            cmd, cwd=tc.BASE_DIR, close_fds=True, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except Exception as exc:
        return {"ok": False, "pid": 0, "message": "启动失败：%r" % (exc,)}
    deadline = time.monotonic() + max(0.5, wait)
    while time.monotonic() < deadline:
        pid = daemon_pid()
        if pid:
            return {"ok": True, "pid": pid, "message": "按键映射已启动"}
        time.sleep(0.1)
    status = read_status()
    message = status.get("last_error") or "已启动，等待状态回报"
    return {"ok": False, "pid": daemon_pid(),
            "message": message}


def ensure_daemon_if_enabled() -> None:
    """面板/托盘启动时调用：配置启用且有绑定才拉起守护进程。"""
    try:
        cfg = load_config()
    except Exception:
        return
    if not cfg.get("enabled") or not has_any_binding(cfg):
        return
    if daemon_running():
        return
    threading.Thread(target=start_daemon, kwargs={"wait": 2.0},
                     daemon=True, name="mouse-remap-start").start()


def apply_config(cfg: dict) -> dict:
    """保存配置并让后台生效：启用则启动，禁用则停止。"""
    ok = save_config(cfg)
    if not ok:
        return {"ok": False, "message": "配置保存失败"}
    if cfg.get("enabled") and has_any_binding(cfg):
        return start_daemon()
    stopped = stop_daemon()
    return {"ok": True, "message": "已保存（映射已停用）" if stopped
            else "已保存（停止旧进程失败）"}


# ---------------------------------------------------------------------------
# 守护进程入口
# ---------------------------------------------------------------------------
_instance_handle = None


def acquire_instance() -> bool:
    """获取单实例互斥；已有实例返回 False。"""
    global _instance_handle
    try:
        _KERNEL32.CreateMutexW.restype = ctypes.c_void_p
        _KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                           wintypes.LPCWSTR]
        _instance_handle = _KERNEL32.CreateMutexW(None, False, MUTEX_NAME)
        return ctypes.get_last_error() != 183
    except Exception:
        return True


def run_daemon(duration: float | None = None) -> int:
    if not acquire_instance():
        return 0
    try:
        os.remove(STOP_PATH)
    except OSError:
        pass
    cfg = load_config()
    engine = RemapEngine(cfg, logger=lambda msg: None)
    if not cfg.get("enabled") or not has_any_binding(cfg):
        write_status({"running": False, "pid": 0,
                      "updated_at": time.time(),
                      "last_error": "映射未启用或没有绑定"})
        return 0
    if not engine.start():
        write_status(engine.status())
        return 1
    deadline = time.monotonic() + duration if duration else None
    last_mtime = config_mtime()
    last_write = 0.0
    try:
        while True:
            time.sleep(0.4)
            if os.path.exists(STOP_PATH):
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            mtime = config_mtime()
            if mtime and mtime != last_mtime:
                last_mtime = mtime
                new_cfg = load_config()
                engine.reload(new_cfg)
                if not new_cfg.get("enabled") or not has_any_binding(new_cfg):
                    break
            engine._cfg_mtime = last_mtime
            now = time.monotonic()
            if now - last_write >= 1.0:
                last_write = now
                write_status(engine.status())
    finally:
        engine.stop()
        status = engine.status()
        status["running"] = False
        status["updated_at"] = time.time()
        write_status(status)
        try:
            os.remove(STOP_PATH)
        except OSError:
            pass
    return 0
