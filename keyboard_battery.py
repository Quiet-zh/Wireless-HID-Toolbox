# -*- coding: utf-8 -*-
"""keyboard_battery.py —— 读取 PMO WAVE75 键盘电量（有线 / 2.4G）。

    python keyboard_battery.py --once
    python keyboard_battery.py --json
    python keyboard_battery.py --watch 30
    python keyboard_battery.py --debug

注意：
  * 键盘必须是 PMO HUB 官方固件（键盘 + 接收器都升级）。
  * QMK/VIA 固件没有主机侧电量命令，只能用 Fn+Backspace 看数字键灯。
  * 2.4G 模式下 dongle 负责转发；官方固件实测可读。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pmo_proto as pmo


def _format(reading: pmo.KeyboardBattery) -> str:
    return (
        f"{pmo.PRODUCT_NAME} ({pmo.VID:04X}:"
        f"{(pmo.PID_DONGLE if reading.dongle else pmo.PID_WIRED):04X})  "
        f"电量 {reading.percent}%（{reading.charging_text}）"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="读取 PMO WAVE75 键盘电量")
    parser.add_argument("--once", action="store_true", help="读一次后退出（默认）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="循环读取，间隔秒数")
    parser.add_argument("--debug", action="store_true", help="打印原始报文")
    args = parser.parse_args(argv)

    if args.watch is None:
        try:
            reading = pmo.read_battery(debug=args.debug)
        except pmo.PmoError as exc:
            if args.json:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            else:
                print(f"[读取失败] {exc}", file=sys.stderr)
            return 2
        print(json.dumps(reading.to_dict(), ensure_ascii=False, indent=2)
              if args.json else _format(reading))
        return 0

    interval = max(2.0, args.watch)
    print(f"每 {interval:g} 秒刷新一次，Ctrl+C 退出。")
    try:
        while True:
            try:
                reading = pmo.read_battery(debug=args.debug)
                print(f"[{time.strftime('%H:%M:%S')}] {_format(reading)}")
            except pmo.PmoError as exc:
                print(f"[{time.strftime('%H:%M:%S')}] [读取失败] {exc}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
