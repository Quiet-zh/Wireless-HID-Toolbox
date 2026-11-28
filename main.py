# -*- coding: utf-8 -*-
"""main.py —— Wireless HID Toolbox 统一入口。

源码运行：
    python main.py                 # 主显示界面
    python main.py --tool mouse-test
    python main.py --tool mouse-map
    python main.py --tool mouse-remap
    python main.py --tool hid-debug
    python main.py --tool tray

PyInstaller 打包后 exe 默认启动主显示界面；设置里的工具通过
`exe --tool <name>` 打开，不需要外部 .py 文件。
"""
from __future__ import annotations

import argparse

from version import __version__, APP_DISPLAY_NAME


def main(argv=None) -> int:
    """统一入口；Ctrl+C 直接安静退出，不把 KeyboardInterrupt 打成 traceback。"""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        try:
            print("\n已中断，退出。")
        except Exception:
            pass
        return 130


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Wireless HID Toolbox")
    parser.add_argument("--version", action="store_true", help="打印版本")
    parser.add_argument(
        "--tool", default="panel",
        choices=["panel", "tray", "mouse-test", "hid-debug",
                 "mouse-map", "mouse-remap"],
        help="启动哪个界面/进程")
    args, rest = parser.parse_known_args(argv)

    if args.version:
        print(f"{APP_DISPLAY_NAME} v{__version__}")
        return 0

    if (args.tool in ("panel", "tray")
            and not any(flag in rest for flag in
                        ("--version", "-V", "--help", "-h"))):
        # 鼠标按键映射启用时，让常驻映射守护进程随之启动（幂等）；
        # 只查版本/帮助时不要拉起后台。
        try:
            import mouse_remap
            mouse_remap.ensure_daemon_if_enabled()
        except Exception:
            pass

    if args.tool == "mouse-remap":
        import mouse_remap_daemon
        return mouse_remap_daemon.main(rest)
    if args.tool == "mouse-map":
        import mouse_mapping_panel
        return mouse_mapping_panel.main(rest)
    if args.tool == "tray":
        import tray_app
        return tray_app.main(rest)
    if args.tool == "mouse-test":
        import mouse_test_gui
        return mouse_test_gui.main(rest)
    if args.tool == "hid-debug":
        import app
        app.main()
        return 0
    import battery_panel
    return battery_panel.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
