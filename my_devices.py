# -*- coding: utf-8 -*-
"""my_devices.py —— 两台设备的统一电量入口（对应 README 验收标准 1）。

    python my_devices.py --once
    python my_devices.py --json
    python my_devices.py --watch 30
    python my_devices.py --debug
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import eweadn_proto as mouse_proto
import pmo_proto as kb_proto
import hid_win
import tray_common as tc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read_once(debug: bool = False) -> dict:
    out = {"mouse": None, "keyboard": None,
           "mouse_error": None, "keyboard_error": None}
    try:
        out["mouse"] = mouse_proto.read_battery(debug=debug)
    except mouse_proto.EweadnError as exc:
        out["mouse_error"] = str(exc)
    try:
        out["keyboard"] = kb_proto.read_battery(debug=debug)
    except kb_proto.PmoError as exc:
        out["keyboard_error"] = str(exc)
    return out


def _mouse_line(result) -> str:
    if result is None:
        return "EWEADN 8K: 读取失败"
    charge = "充电中" if result.charging else "未充电"
    return (f"EWEADN 8K: 电量 {result.percent}%"
            f"（{result.voltage_v:.3f} V，{charge}）")


def _kb_line(result) -> str:
    if result is None:
        return "PMO WAVE75: 读取失败"
    link = "2.4G" if result.dongle else "USB"
    return (f"PMO WAVE75: 电量 {result.percent}%"
            f"（{result.charging_text}，{link}）")


def list_devices() -> int:
    items = hid_win.enumerate_hid()
    print(f"{len(items)} 个 HID 接口：")
    for it in items:
        print(f"{it.vid:04X}:{it.pid:04X}  "
              f"usage=0x{it.usage_page:04X}:0x{it.usage:04X}  "
              f"in/out/feat={it.input_len}/{it.output_len}/{it.feature_len}  "
              f"{it.product or '(无产品名)'}  {it.path}")
    return 0


def install() -> int:
    tc.set_autostart(True)
    result = tc.install_desktop_links()
    status = tc.autostart_status()
    cfg = tc.load_config()
    cfg["autostart"] = status["enabled"]
    tc.save_config(cfg)
    print("开机自启：", "已启用" if status["enabled"] else "未启用")
    print("启动项：", status["shortcut"])
    print("桌面：", "目录", result.get("folder") or "失败")
    for name, kind in (result.get("links") or {}).items():
        print(f"      {name} -> {kind}")
    for err in result.get("errors") or []:
        print("  错误：", err)
    return 0


def open_panel() -> int:
    subprocess.Popen([tc.pythonw_path(), os.path.join(BASE_DIR, "battery_panel.py")],
                     cwd=BASE_DIR, creationflags=0x00000008)
    print("已打开电量面板")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="读取 EWEADN 8K 鼠标 / PMO WAVE75 键盘电量")
    parser.add_argument("--once", action="store_true", help="读一次后退出（默认）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="循环读取间隔")
    parser.add_argument("--debug", action="store_true", help="打印读取过程")
    parser.add_argument("--list", action="store_true", help="列出所有 HID 接口")
    parser.add_argument("--panel", action="store_true", help="打开电量面板")
    parser.add_argument("--install", action="store_true", help="开机自启 + 桌面链接")
    args = parser.parse_args(argv)

    if args.list:
        return list_devices()
    if args.install:
        return install()
    if args.panel:
        return open_panel()

    if args.watch is None:
        result = read_once(args.debug)
        if args.json:
            payload = {
                "mouse": result["mouse"].to_dict() if result["mouse"] else None,
                "keyboard": result["keyboard"].to_dict() if result["keyboard"] else None,
                "errors": {"mouse": result["mouse_error"],
                           "keyboard": result["keyboard_error"]},
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(_mouse_line(result["mouse"]))
            print(_kb_line(result["keyboard"]))
            for key, err in (("mouse", result["mouse_error"]),
                             ("keyboard", result["keyboard_error"])):
                if err:
                    print(f"  [{key}] {err.splitlines()[0]}", file=sys.stderr)
        return 0 if (result["mouse"] or result["keyboard"]) else 2

    interval = max(2.0, args.watch)
    print(f"每 {interval:g} 秒刷新一次，Ctrl+C 退出。")
    try:
        while True:
            result = read_once(args.debug)
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {_mouse_line(result['mouse'])}")
            print(f"[{stamp}] {_kb_line(result['keyboard'])}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
