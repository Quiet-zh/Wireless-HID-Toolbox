# -*- coding: utf-8 -*-
"""debug_tool.py —— EWEADN 8K 协议调试工具。

    python debug_tool.py list             # 列出本机 EWEADN 的所有 HID 接口
    python debug_tool.py read             # 读电量，并打印原始收发报文
    python debug_tool.py monitor 10       # 监听 10 秒 Input Report（含 E-HUB 的流量）
    python debug_tool.py send 4           # 发送命令 0x04（电量）
    python debug_tool.py send 3 ""        # 发送命令 0x03（在线状态）
    python debug_tool.py wake 15          # 连续查询在线状态，用来确认鼠标是否醒着
"""
from __future__ import annotations

import argparse
import time

import hid_win
import eweadn_proto as proto


def cmd_list(_args):
    items = proto.find_interfaces()
    if not items:
        print("没有找到 3554:F517 设备。")
        return 1
    print(f"找到 {len(items)} 个 HID 接口：\n")
    for it in items:
        marker = "  <-- 私有协议" if (it.usage_page == proto.USAGE_PAGE
                                       and it.usage == proto.USAGE) else ""
        print(f"{it.path}\n"
              f"    usage=0x{it.usage_page:04X}:0x{it.usage:04X}  "
              f"in={it.input_len} out={it.output_len} feature={it.feature_len}"
              f"{marker}")
    return 0


def _open():
    iface = proto.find_control_interface()
    if iface is None:
        raise SystemExit("没有找到 0xFF02/0x0002 私有接口。")
    return hid_win.HidDevice(iface.path, write=True)


def cmd_read(_args):
    reading = proto.read_battery(debug=True)
    print(reading.to_dict())
    return 0


def cmd_monitor(args):
    dev = _open()
    seconds = args.seconds
    print(f"监听 {seconds:g} 秒（Ctrl+C 退出）…")
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < seconds:
            raw = dev.read_input(timeout_ms=200)
            if raw:
                print(time.strftime("%H:%M:%S"), raw.hex(" "))
    except KeyboardInterrupt:
        pass
    finally:
        dev.close()
    return 0


def cmd_send(args):
    payload = bytes.fromhex(args.payload.replace(" ", "")) if args.payload else b""
    frame = proto.build_frame(args.cmd, payload)
    print("发送:", frame.hex(" "))
    dev = _open()
    try:
        dev.drain()
        dev.write_output(frame)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            raw = dev.read_input(timeout_ms=150)
            if raw:
                body = proto.normalize_report(raw)
                tag = ""
                if body:
                    tag = f"  cmd=0x{body[0]:02X} status=0x{body[1]:02X}"
                print("接收:", raw.hex(" "), tag)
    finally:
        dev.close()
    return 0


def cmd_wake(args):
    dev = _open()
    print(f"连续查询在线状态 {args.seconds:g} 秒…（动一下鼠标可唤醒）")
    t0 = time.monotonic()
    last = 0.0
    try:
        dev.drain()
        while time.monotonic() - t0 < args.seconds:
            now = time.monotonic()
            if now - last > 0.5:
                dev.write_output(proto.build_frame(proto.CMD_DEVICE_ONLINE))
                last = now
            raw = dev.read_input(timeout_ms=50)
            if raw:
                body = proto.normalize_report(raw)
                if body and body[0] == proto.CMD_DEVICE_ONLINE:
                    print(time.strftime("%H:%M:%S"), "online =", body[5])
                    if body[5] == 1:
                        print("鼠标已唤醒，可以读取电量了。")
                        return 0
    finally:
        dev.close()
    print("仍未唤醒：鼠标可能已休眠 / 关机，请移动鼠标或按一下按键。")
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EWEADN 8K 协议调试工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="列出 HID 接口")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("read", help="读取电量")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("monitor", help="监听 Input Report")
    p.add_argument("seconds", type=float, nargs="?", default=10)
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("send", help="发送原始命令")
    p.add_argument("cmd", type=lambda s: int(s, 0))
    p.add_argument("payload", nargs="?", default="", help="十六进制 payload，如 0102")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("wake", help="查询在线状态（确认鼠标是否醒着）")
    p.add_argument("seconds", type=float, nargs="?", default=15)
    p.set_defaults(func=cmd_wake)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except proto.EweadnError as exc:
        print(f"[失败] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
