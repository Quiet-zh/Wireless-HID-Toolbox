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
import sys
import time

import eweadn_proto as mouse_proto
import pmo_proto as kb_proto


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="读取 EWEADN 8K 鼠标 / PMO WAVE75 键盘电量")
    parser.add_argument("--once", action="store_true", help="读一次后退出（默认）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--watch", type=float, metavar="SECONDS", help="循环读取间隔")
    parser.add_argument("--debug", action="store_true", help="打印读取过程")
    args = parser.parse_args(argv)

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
