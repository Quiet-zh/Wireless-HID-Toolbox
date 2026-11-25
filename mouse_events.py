# -*- coding: utf-8 -*-
"""mouse_events.py —— 用 Windows Raw Input 监控 EWEADN 鼠标的按键 / 移动 / 滚轮。

    python mouse_events.py --list              # 列出 Raw Input 设备
    python mouse_events.py --seconds 20        # 只监视 EWEADN（默认）
    python mouse_events.py --all --seconds 10  # 监视所有鼠标/键盘（调试用）
    python mouse_events.py --stats             # 每秒打印一次速率统计

为什么不用 HID ReadFile？
    鼠标 / 键盘的顶层集合被 Windows 独占，普通进程打不开；
    系统给的标准做法是 Raw Input（WM_INPUT），可以后台接收、能区分设备，
    而且不需要驱动、不需要管理员权限。
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

VID = 0x3554
PID = 0xF517
VID_PID_TAG = f"vid_{VID:04x}&pid_{PID:04x}"

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIDEV_INPUTSINK = 0x00000100
MOUSE_MOVE_ABSOLUTE = 0x00000001
PM_REMOVE = 0x0001
HWND_MESSAGE = -3

# RAWMOUSE.usButtonFlags
BUTTON_EVENTS = [
    (0x0001, "left", "down"),
    (0x0002, "left", "up"),
    (0x0004, "right", "down"),
    (0x0008, "right", "up"),
    (0x0010, "middle", "down"),
    (0x0020, "middle", "up"),
    (0x0040, "side1", "down"),
    (0x0080, "side1", "up"),
    (0x0100, "side2", "down"),
    (0x0200, "side2", "up"),
]
WHEEL = 0x0400
HWHEEL = 0x0800

VK_NAMES = {
    0x01: "LButton", 0x02: "RButton", 0x04: "MButton", 0x05: "XButton1",
    0x06: "XButton2", 0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x14: "CapsLock",
    0x1B: "Esc", 0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End",
    0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "Win", 0x5C: "WinRight", 0x5D: "Menu",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
    0xA6: "BrowserBack", 0xA7: "BrowserForward", 0xA8: "BrowserRefresh",
    0xA9: "BrowserStop", 0xAA: "BrowserSearch", 0xAB: "BrowserFavorites",
    0xAC: "BrowserHome", 0xAD: "VolumeMute", 0xAE: "VolumeDown",
    0xAF: "VolumeUp", 0xB0: "MediaNext", 0xB1: "MediaPrev",
    0xB2: "MediaStop", 0xB3: "MediaPlayPause", 0xB4: "LaunchMail",
    0xB5: "LaunchMedia", 0xB6: "LaunchApp1", 0xB7: "LaunchApp2",
}


# ---------------------------------------------------------------------------
# Win32 结构
# ---------------------------------------------------------------------------
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class _BUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wintypes.USHORT),
                ("usButtonData", wintypes.USHORT)]


class _BUTTONUNION(ctypes.Union):
    _fields_ = [("ulButtons", wintypes.ULONG), ("bt", _BUTTONS)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("_pad", wintypes.USHORT),
        ("u", _BUTTONUNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWHID(ctypes.Structure):
    _fields_ = [
        ("dwSizeHid", wintypes.DWORD),
        ("dwCount", wintypes.DWORD),
        ("bRawData", ctypes.c_ubyte * 1),
    ]


class _RAWUNION(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD), ("hid", RAWHID)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", _RAWUNION)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

# 函数签名
user32.DefWindowProcW.restype = wintypes.LPARAM
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.RegisterRawInputDevices.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [
    wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICELIST), ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = [
    wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(wintypes.UINT)]
user32.PeekMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND,
    wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = wintypes.LPARAM
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DestroyWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def cursor_pos():
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return 0, 0


def _wndproc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_WNDPROC_REF = WNDPROC(_wndproc)


# ---------------------------------------------------------------------------
# 设备枚举 / 窗口
# ---------------------------------------------------------------------------
def list_raw_devices():
    """返回 [(handle, type, name), ...]。"""
    count = wintypes.UINT(0)
    user32.GetRawInputDeviceList(None, ctypes.byref(count),
                                 ctypes.sizeof(RAWINPUTDEVICELIST))
    if not count.value:
        return []
    arr = (RAWINPUTDEVICELIST * count.value)()
    got = user32.GetRawInputDeviceList(arr, ctypes.byref(count),
                                       ctypes.sizeof(RAWINPUTDEVICELIST))
    items = []
    for i in range(got):
        dev = arr[i]
        size = wintypes.UINT(0)
        user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, None,
                                      ctypes.byref(size))
        name = ""
        if size.value:
            buf = ctypes.create_unicode_buffer(size.value)
            user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, buf,
                                          ctypes.byref(size))
            name = buf.value
        items.append((int(dev.hDevice or 0), int(dev.dwType), name))
    return items


def list_test_devices() -> list[dict]:
    """按物理设备聚合 Raw Input，只归入一个类别（鼠标或键盘）。

    复合接收器（例如罗技接收器、键盘的 Consumer 集合）会同时暴露
    mouse/keyboard 两种 Raw Input 接口；如果按接口类型分别列出，就会出现
    “鼠标列表里有键盘设备”的错位。这里按 VID:PID 聚合后，按已知设备类型/
    产品名/可用接口选一个主类别，只把该类别的句柄给测试界面。
    """
    import re
    try:
        import hid_win
        names = {}
        for d in hid_win.enumerate_hid():
            if d.product:
                names[(d.vid, d.pid)] = d.product
    except Exception:
        names = {}

    known_kind = {
        "3554:F517": "mouse",
        "36B0:3002": "keyboard",
        "36B0:3009": "keyboard",
        "046D:C53F": "mouse",
        "248A:60AB": "mouse",
        "2F4C:1006": "keyboard",
    }
    known_label = {
        "3554:F517": "EWEADN 8K",
        "36B0:3002": "PMO WAVE75",
        "36B0:3009": "PMO WAVE75（USB）",
        "046D:C53F": "罗技 G304 / Lightspeed",
        "248A:60AB": "Monster AiMouse",
        "2F4C:1006": "COLORFUL 键盘",
    }

    raw: dict[str, dict] = {}
    for handle, typ, name in list_raw_devices():
        if typ == RIM_TYPEMOUSE:
            kind = "mouse"
        elif typ == RIM_TYPEKEYBOARD:
            kind = "keyboard"
        else:
            continue
        m = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", name, re.I)
        if m:
            vid, pid = int(m.group(1), 16), int(m.group(2), 16)
            base = f"{vid:04X}:{pid:04X}"
            product = names.get((vid, pid), "")
        elif "ROOT#MOUSE" in name.upper():
            base, product = "ROOT:MOUSE", "系统默认鼠标"
        elif "ROOT#KEYBOARD" in name.upper():
            base, product = "ROOT:KEYBOARD", "系统默认键盘"
        else:
            base, product = f"DEV:{(name or str(handle))[-12:]}", ""
        g = raw.setdefault(base, {
            "base": base, "product": product,
            "mouse": [], "keyboard": [],
        })
        g[kind].append(handle)

    out = []
    for base, g in raw.items():
        # ROOT#MOUSE / ROOT#KEYBOARD 是系统聚合设备，实际事件来自具体
        # HID 句柄；选了它反而收不到事件，不放进选择列表。
        if base in ("ROOT:MOUSE", "ROOT:KEYBOARD"):
            continue
        if base in known_kind:
            kind = known_kind[base]
        else:
            text = (g["product"] or "").lower()
            if "keyboard" in text or "键盘" in text:
                kind = "keyboard"
            elif "mouse" in text or "鼠标" in text:
                kind = "mouse"
            elif g["mouse"] and not g["keyboard"]:
                kind = "mouse"
            elif g["keyboard"] and not g["mouse"]:
                kind = "keyboard"
            else:
                # 未知复合设备：按“键盘优先”归一个主类别，避免双列表重复
                kind = "keyboard"
        handles = g[kind]
        if not handles:
            # 已知类型对应的集合不存在时退回另一个集合
            kind = "keyboard" if kind == "mouse" else "mouse"
            handles = g[kind]
        if not handles:
            continue
        label = known_label.get(base) or g["product"] or base
        out.append({
            "key": f"{base}:{kind}",
            "kind": kind,
            "base": base,
            "label": label,
            "handles": handles,
        })

    out.sort(key=lambda d: (0 if d["kind"] == "mouse" else 1, d["label"]))
    return out


def create_message_window():
    hinst = kernel32.GetModuleHandleW(None)
    class_name = f"WirelessHidRaw_{id(_WNDPROC_REF):x}"
    wc = WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(_WNDPROC_REF, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.lpszClassName = class_name
    if not user32.RegisterClassW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        # 1410 = ERROR_CLASS_ALREADY_EXISTS。类在进程内只注册一次，
        # 切换监听设备重启 listener 时会命中；窗口仍然可以创建。
        if err not in (0, 1410):
            raise OSError(f"RegisterClassW 失败: {err}")
    hwnd = user32.CreateWindowExW(
        0, class_name, "Wireless HID test raw input", 0, 0, 0, 0, 0,
        wintypes.HWND(HWND_MESSAGE), None, hinst, None)
    if not hwnd:
        raise OSError(f"CreateWindowExW 失败: {ctypes.get_last_error()}")
    return hwnd


def register_devices(hwnd):
    devs = (RAWINPUTDEVICE * 2)()
    devs[0].usUsagePage = 0x01
    devs[0].usUsage = 0x02          # mouse
    devs[0].dwFlags = RIDEV_INPUTSINK
    devs[0].hwndTarget = hwnd
    devs[1].usUsagePage = 0x01
    devs[1].usUsage = 0x06          # keyboard
    devs[1].dwFlags = RIDEV_INPUTSINK
    devs[1].hwndTarget = hwnd
    if not user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        raise OSError(f"RegisterRawInputDevices 失败: {ctypes.get_last_error()}")


# ---------------------------------------------------------------------------
# 监视器
# ---------------------------------------------------------------------------
class Monitor:
    def __init__(self, accept_all: bool = False, show_stats: bool = False):
        self.accept_all = accept_all
        self.show_stats = show_stats
        self.handles = {}
        self.moves = []
        self.move_dx = 0
        self.move_dy = 0
        self.move_reports = 0
        self.last_flush = time.monotonic()
        self.counters = {"reports": 0, "moves": 0, "buttons": 0, "wheel": 0}
        self.last_stats = time.monotonic()
        self._known = {}
        self._buf = ctypes.create_string_buffer(256)

    def discover(self):
        for handle, typ, name in list_raw_devices():
            low = name.lower()
            if typ in (RIM_TYPEMOUSE, RIM_TYPEKEYBOARD):
                self._known[handle] = name
                if VID_PID_TAG in low:
                    self.handles[handle] = name
        if not self.handles:
            print("提示：没找到 3554:F517 的 Raw Input 设备；可加 --all 调试。")
        else:
            print(f"已锁定 {len(self.handles)} 个 EWEADN Raw Input 接口：")
            for h, name in self.handles.items():
                print(f"  handle=0x{h:016X}  {name}")

    def flush_moves(self, force=False):
        now = time.monotonic()
        if not self.move_reports:
            return
        if force or now - self.last_flush >= 0.05:
            print(f"[{_stamp()}] mouse   move  dx={self.move_dx:+d} dy={self.move_dy:+d}"
                  f"  ({self.move_reports} 包)")
            self.move_dx = self.move_dy = 0
            self.move_reports = 0
            self.last_flush = now

    def on_mouse(self, ri: RAWINPUT):
        m = ri.data.mouse
        self.counters["reports"] += 1
        flags = m.usFlags
        if not (flags & MOUSE_MOVE_ABSOLUTE):
            dx, dy = m.lLastX, m.lLastY
            if dx or dy:
                self.move_dx += dx
                self.move_dy += dy
                self.move_reports += 1
                self.counters["moves"] += 1
        btn = m.u.bt.usButtonFlags
        data = m.u.bt.usButtonData
        for mask, name, action in BUTTON_EVENTS:
            if btn & mask:
                self.flush_moves(force=True)
                print(f"[{_stamp()}] mouse   {name:<6} {action}")
                self.counters["buttons"] += 1
        if btn & WHEEL:
            delta = ctypes.c_short(data).value
            self.flush_moves(force=True)
            direction = "up" if delta > 0 else "down"
            print(f"[{_stamp()}] mouse   wheel   {direction} ({delta:+d})")
            self.counters["wheel"] += 1
        if btn & HWHEEL:
            delta = ctypes.c_short(data).value
            self.flush_moves(force=True)
            direction = "right" if delta > 0 else "left"
            print(f"[{_stamp()}] mouse   hwheel  {direction} ({delta:+d})")
            self.counters["wheel"] += 1
        self.flush_moves()

    def on_keyboard(self, ri: RAWINPUT):
        k = ri.data.keyboard
        self.counters["reports"] += 1
        if k.Message not in (0x0100, 0x0101, 0x0104, 0x0105):  # key down/up
            return
        action = "down" if k.Message in (0x0100, 0x0104) else "up"
        name = VK_NAMES.get(k.VKey, f"VK_0x{k.VKey:02X}")
        self.flush_moves(force=True)
        print(f"[{_stamp()}] key     {name:<10} {action}  (scan=0x{k.MakeCode:02X})")

    def maybe_stats(self):
        if not self.show_stats:
            return
        now = time.monotonic()
        if now - self.last_stats >= 1.0:
            dt = now - self.last_stats
            c = self.counters
            print(f"[{_stamp()}] # {c['reports']/dt:6.0f} 包/秒 | "
                  f"移动 {c['moves']/dt:6.0f}/秒 | 按键 {c['buttons']:3d} | 滚轮 {c['wheel']:3d}")
            self.counters = {"reports": 0, "moves": 0, "buttons": 0, "wheel": 0}
            self.last_stats = now

    def process(self, lparam):
        size = wintypes.UINT(len(self._buf))
        got = user32.GetRawInputData(lparam, RID_INPUT, self._buf,
                                     ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER))
        if got in (0, 0xFFFFFFFF) or got > len(self._buf):
            return
        ri = ctypes.cast(self._buf, ctypes.POINTER(RAWINPUT)).contents
        handle = int(ri.header.hDevice or 0)
        if not self.accept_all and handle not in self.handles:
            return
        if ri.header.dwType == RIM_TYPEMOUSE:
            self.on_mouse(ri)
        elif ri.header.dwType == RIM_TYPEKEYBOARD:
            self.on_keyboard(ri)


def _stamp():
    return time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def run(seconds: float, accept_all: bool, show_stats: bool):
    hwnd = create_message_window()
    register_devices(hwnd)
    mon = Monitor(accept_all=accept_all, show_stats=show_stats)
    mon.discover()
    print("开始监听（Ctrl+C 退出）…" if not seconds else f"监听 {seconds:g} 秒…")
    msg = wintypes.MSG()
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                break
            got = False
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                got = True
                if msg.message == WM_INPUT:
                    mon.process(msg.lParam)
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            mon.maybe_stats()
            if not got:
                time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    finally:
        mon.flush_moves(force=True)
        print("监听结束。")


def parse_mouse_report(ri):
    """把一条 RAWMOUSE 拆成事件 dict 列表。"""
    events = []
    m = ri.data.mouse
    if not (m.usFlags & MOUSE_MOVE_ABSOLUTE):
        if m.lLastX or m.lLastY:
            events.append({"type": "move", "dx": int(m.lLastX), "dy": int(m.lLastY)})
    btn = m.u.bt.usButtonFlags
    data = m.u.bt.usButtonData
    for mask, name, action in BUTTON_EVENTS:
        if btn & mask:
            events.append({"type": "button", "button": name, "action": action})
    if btn & WHEEL:
        events.append({"type": "wheel", "delta": ctypes.c_short(data).value,
                       "horizontal": False})
    if btn & HWHEEL:
        events.append({"type": "wheel", "delta": ctypes.c_short(data).value,
                       "horizontal": True})
    return events


def parse_keyboard_report(ri):
    k = ri.data.keyboard
    if k.Message not in (0x0100, 0x0101, 0x0104, 0x0105):
        return None
    return {
        "type": "key",
        "vk": int(k.VKey),
        "name": VK_NAMES.get(k.VKey, f"VK_0x{k.VKey:02X}"),
        "scan": int(k.MakeCode),
        "action": "down" if k.Message in (0x0100, 0x0104) else "up",
    }


class RawInputListener:
    """在后台线程里跑 Raw Input 消息循环，通过 callback 推送事件 dict。

    事件字段：type（move/button/wheel/key）、handle、eweadn、ts、screen。
    """

    def __init__(self, callback, accept_all=False, handles=None):
        self.callback = callback
        self.accept_all = accept_all
        self.eweadn_handles = set()
        self.allowed_handles = set(handles) if handles is not None else None
        self.hwnd = None
        self.error = None
        self._buf = ctypes.create_string_buffer(256)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._thread = None

    def start(self, timeout=3.0):
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="rawinput-listener")
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("Raw Input 监听线程启动超时")
        if self.error:
            raise self.error

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._stopped.wait(1.5)

    def _run(self):
        hwnd = None
        try:
            hwnd = create_message_window()
            register_devices(hwnd)
            self.eweadn_handles = {
                h for h, typ, name in list_raw_devices()
                if typ in (RIM_TYPEMOUSE, RIM_TYPEKEYBOARD)
                and VID_PID_TAG in name.lower()
            }
            if self.allowed_handles is None and not self.accept_all:
                self.allowed_handles = set(self.eweadn_handles)
            self.hwnd = hwnd
            self._ready.set()
            msg = wintypes.MSG()
            while not self._stop.is_set():
                got = False
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    got = True
                    if msg.message == WM_INPUT:
                        self._process(msg.lParam)
                    else:
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                if not got:
                    time.sleep(0.001)
        except Exception as exc:  # noqa: BLE001 - 交给主线程处理
            self.error = exc
            self._ready.set()
        finally:
            if hwnd:
                user32.DestroyWindow(hwnd)
            self._stopped.set()

    def _process(self, lparam):
        size = wintypes.UINT(len(self._buf))
        got = user32.GetRawInputData(lparam, RID_INPUT, self._buf,
                                     ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER))
        if got in (0, 0xFFFFFFFF) or got > len(self._buf):
            return
        ri = ctypes.cast(self._buf, ctypes.POINTER(RAWINPUT)).contents
        handle = int(ri.header.hDevice or 0)
        is_eweadn = handle in self.eweadn_handles
        # hDevice=0 是 SendInput/注入事件（没有具体设备），不能按句柄过滤
        if handle and self.allowed_handles is not None \
                and handle not in self.allowed_handles:
            return
        if self.allowed_handles is None and not self.accept_all and not is_eweadn:
            return
        base = {
            "handle": handle,
            "eweadn": is_eweadn,
            "screen": cursor_pos(),
            "ts": time.time(),
        }
        if ri.header.dwType == RIM_TYPEMOUSE:
            for ev in parse_mouse_report(ri):
                ev.update(base)
                self.callback(ev)
        elif ri.header.dwType == RIM_TYPEKEYBOARD:
            ev = parse_keyboard_report(ri)
            if ev:
                ev.update(base)
                self.callback(ev)


def list_devices():
    print("Raw Input 设备：")
    for handle, typ, name in list_raw_devices():
        kind = {RIM_TYPEMOUSE: "mouse", RIM_TYPEKEYBOARD: "keyboard"}.get(typ, str(typ))
        mark = "  <-- EWEADN" if VID_PID_TAG in name.lower() else ""
        print(f"  handle=0x{handle:016X}  {kind:<8} {name}{mark}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="监控 EWEADN 鼠标 Raw Input 事件")
    parser.add_argument("--list", action="store_true", help="列出 Raw Input 设备后退出")
    parser.add_argument("--seconds", type=float, default=0, help="监听时长（默认一直监听）")
    parser.add_argument("--all", action="store_true", help="不过滤设备，显示所有鼠标/键盘")
    parser.add_argument("--stats", action="store_true", help="每秒打印速率统计")
    args = parser.parse_args(argv)
    if args.list:
        list_devices()
        return 0
    run(args.seconds, args.all, args.stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
