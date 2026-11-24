# -*- coding: utf-8 -*-
"""eweadn_battery.py —— 命令行读取 EWEADN 8K 鼠标电量。

用法：
    python eweadn_battery.py                # 读一次，打印一行
    python eweadn_battery.py --json         # 读一次，输出 JSON
    python eweadn_battery.py --watch 30     # 每 30 秒读一次（Ctrl+C 退出）
    python eweadn_battery.py --debug        # 打印原始收发报文
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import eweadn_proto as proto


def _format(reading: proto.BatteryReading) -> str:
    charge = "充电中" if reading.charging else "未充电"
    return (
        f"{proto.PRODUCT_NAME} ({proto.VID:04X}:{proto.PID:04X})  "
        f"电量 {reading.percent}%  "
        f"({reading.voltage_v:.3f} V · {charge})"
    )


def _one(debug: bool) -> int:
    try:
        reading = proto.read_battery(debug=debug)
    except proto.EweadnError as exc:
        print(f"[读取失败] {exc}", file=sys.stderr)
        return 2
    print(_format(reading))
    if debug:
        print("  原始回复:", reading.raw.hex(" "))
        print("  设备自报电量:", reading.level_raw, "%  取值来源:", reading.percent_source)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="读取迈从 EWEADN 8K (3554:F517) 鼠标电量")
    parser.add_argument("--once", action="store_true", help="读一次后退出（默认行为）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="循环读取，间隔秒数（最小 2 秒）")
    parser.add_argument("--debug", action="store_true", help="打印原始报文")
    args = parser.parse_args(argv)

    if args.watch is None:
        try:
            reading = proto.read_battery(debug=args.debug)
        except proto.EweadnError as exc:
            if args.json:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            else:
                print(f"[读取失败] {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(reading.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(_format(reading))
        return 0

    interval = max(2.0, args.watch)
    print(f"每 {interval:g} 秒刷新一次，Ctrl+C 退出。")
    try:
        while True:
            try:
                reading = proto.read_battery(debug=args.debug)
                stamp = time.strftime("%H:%M:%S")
                if args.json:
                    print(json.dumps(reading.to_dict(), ensure_ascii=False))
                else:
                    print(f"[{stamp}] {_format(reading)}")
            except proto.EweadnError as exc:
                stamp = time.strftime("%H:%M:%S")
                print(f"[{stamp}] [读取失败] {exc}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
