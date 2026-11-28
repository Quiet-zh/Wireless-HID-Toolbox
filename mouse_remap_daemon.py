# -*- coding: utf-8 -*-
"""mouse_remap_daemon.py —— 鼠标按键映射后台守护进程。

由主面板、托盘或映射配置界面自动拉起：

    python main.py --tool mouse-remap          # 前台运行（调试）
    python main.py --tool mouse-remap --status # 打印状态
    python main.py --tool mouse-remap --stop   # 停止后台实例
    python main.py --tool mouse-remap --diagnose

单实例（命名互斥），配置变化自动热重载，状态写到
``%APPDATA%\\ExtBatteryTray\\mouse_map_status.json``。
"""
from __future__ import annotations

import argparse
import json
import sys

import mouse_remap as mr
from version import __version__


def _print_status() -> int:
    status = mr.read_status()
    if not status:
        print("没有状态文件（后台映射未启动过）")
        return 1
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def _diagnose() -> int:
    cfg = mr.load_config()
    report = {
        "version": __version__,
        "config_path": mr.CONFIG_PATH,
        "status_path": mr.STATUS_PATH,
        "config": cfg,
        "bindings": sum(1 for _ in mr.enabled_bindings(cfg) or []),
        "mice": mr.list_mice(),
        "daemon_pid": mr.daemon_pid(),
        "status": mr.read_status(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="鼠标按键映射后台")
    parser.add_argument("--status", action="store_true", help="打印运行状态")
    parser.add_argument("--stop", action="store_true", help="停止后台实例")
    parser.add_argument("--start", action="store_true", help="启动后台实例")
    parser.add_argument("--diagnose", action="store_true",
                        help="打印配置/设备/状态诊断")
    parser.add_argument("--duration", type=float, default=0,
                        help="只运行指定秒数（测试用；0=一直运行）")
    parser.add_argument("--version", action="store_true", help="打印版本")
    args = parser.parse_args(argv)

    if args.version:
        print("Wireless HID Toolbox v%s" % __version__)
        return 0
    if args.status:
        return _print_status()
    if args.diagnose:
        return _diagnose()
    if args.stop:
        ok = mr.stop_daemon()
        print("已停止后台映射" if ok else "停止失败/后台未运行")
        return 0 if ok else 1
    if args.start:
        result = mr.start_daemon()
        print(result.get("message", ""))
        return 0 if result.get("ok") else 1
    return mr.run_daemon(duration=args.duration or None)


if __name__ == "__main__":
    sys.exit(main())
