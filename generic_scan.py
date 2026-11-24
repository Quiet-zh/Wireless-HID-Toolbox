# -*- coding: utf-8 -*-
"""generic_scan.py —— 扫描并读取所有已收录协议的 2.4G 外设。

    python generic_scan.py            # 扫描一次，打印每台设备
    python generic_scan.py --list     # 只列出命中的协议，不读设备
    python generic_scan.py --json     # JSON
    python generic_scan.py --watch 60 # 每 60 秒扫描
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import generic_protocols as gp


def _line(r: gp.Reading) -> str:
    pct = f"{r.percent}%" if r.percent is not None else "--"
    extra = r.charging_text
    if r.voltage_mv:
        extra += f" · {r.voltage_mv} mV"
    return (f"{r.name}（{r.key}）  {pct}  {extra}  [{r.source}]"
            + (f"  {r.detail}" if r.detail else ""))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="多厂商 2.4G 外设电量扫描")
    parser.add_argument("--list", action="store_true", help="只列接口/命中的协议")
    parser.add_argument("--protocols", action="store_true",
                        help="列出内置协议表（不需要设备）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--watch", type=float, metavar="SECONDS",
                        help="循环扫描间隔")
    parser.add_argument("--debug", action="store_true", help="打印未识别设备")
    args = parser.parse_args(argv)

    if args.protocols:
        rows = []
        for s in sorted(gp.SPECS, key=lambda x: (x.kind, x.vid, x.pids)):
            pids = ("任意" if s.any_pid else
                    "/".join(f"{p:04X}" for p in s.pids) or "任意")
            rows.append({"name": s.name, "kind": s.kind,
                         "vid": f"0x{s.vid:04X}", "pids": pids,
                         "usage_page": (f"0x{s.usage_page:04X}"
                                        if s.usage_page is not None else ""),
                         "notes": s.notes})
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(f"{r['vid']}:{r['pids']}  {r['name']}  [{r['kind']}]")
        return 0

    if args.list:
        rows = gp.list_supported()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        for row in rows:
            protos = "、".join(row["protocols"]) if row["protocols"] else "未收录"
            print(f"{row['key']}  {row['name']}  "
                  f"({row['interfaces']} 个接口)  →  {protos}")
        return 0

    def once() -> int:
        readings = gp.scan()
        if args.json:
            print(json.dumps([r.to_dict() for r in readings],
                             ensure_ascii=False, indent=2))
        elif readings:
            for i, r in enumerate(readings, 1):
                print(f"[{i}] {_line(r)}")
        else:
            print("没有发现已收录协议的设备（可用 --list 看接口）。")
            return 2
        if args.debug:
            known = {r.key for r in readings}
            for row in gp.list_supported():
                if row["key"] not in known:
                    print(f"    未识别：{row['key']} {row['name']}",
                          file=sys.stderr)
        return 0

    if args.watch is None:
        return once()

    interval = max(5.0, args.watch)
    print(f"每 {interval:g} 秒扫描一次，Ctrl+C 退出。")
    try:
        while True:
            stamp = time.strftime("%H:%M:%S")
            print(f"--- {stamp} ---")
            once()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
