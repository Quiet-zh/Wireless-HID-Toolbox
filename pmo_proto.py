# -*- coding: utf-8 -*-
"""pmo_proto.py —— PMO WAVE75 / RDRCTMZT 2.4G 键盘电量协议。

设备：VID 0x36B0，2.4G dongle PID 0x3002（WAVE75 有线模式 PID 0x3009）。
接口：HID usage page 0xFF60 / usage 0x61（raw HID，无 Report ID 编号，
      dongle 32 字节、有线 64 字节）。

协议（RDR / RDMCTMZT，PMO HUB 2.1.1 与 Linux hid-rdmctmzt 驱动一致）：

    AA 10 ...   开始会话（0x10）
    AA 30 ...   读电量（0x30）
    AA 11 ...   结束会话（0x11）
    AA D0 ...   dongle 链路状态（0xD0，dongle 自己回复）

报文第 4 字节是负载长度：2.4G 用 24，有线用 56。
回复：byte 0 = 0xAA，byte 1 = 命令，byte 7 = 0x55 成功 / 0x0F 拒绝，
      byte 8 = 电量 0~100，byte 9 = 充电状态（0 放电 / 1 充电 / 2 充满），
      byte 13 = 链路状态（0x02 表示 dongle 与键盘未连接）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import hid_win

VID = 0x36B0
PID_DONGLE = 0x3002
PID_WIRED = 0x3009
PRODUCT_NAME = "PMO WAVE75"
USAGE_PAGE = 0xFF60
USAGE = 0x61

REPORT_ID = 0x00
PREFIX = 0xAA
CMD_START = 0x10
CMD_BATTERY = 0x30
CMD_STOP = 0x11
CMD_LINK = 0xD0

STATUS_OK = 0x55
STATUS_REFUSED = 0x0F
LINK_NONE = 0x02

CHARGE_NAMES = {0: "未充电", 1: "充电中", 2: "已充满"}


class PmoError(RuntimeError):
    pass


@dataclass
class KeyboardBattery:
    percent: int
    charging: int
    link: int
    raw: bytes
    dongle: bool
    timestamp: float

    @property
    def charging_text(self) -> str:
        return CHARGE_NAMES.get(self.charging, "未知")

    @property
    def online(self) -> bool:
        return self.percent > 0 and self.link != LINK_NONE

    def to_dict(self) -> dict:
        return {
            "product": PRODUCT_NAME,
            "vid": f"0x{VID:04X}",
            "pid": f"0x{(PID_DONGLE if self.dongle else PID_WIRED):04X}",
            "percent": self.percent,
            "charging": self.charging,
            "charging_text": self.charging_text,
            "link": self.link,
            "online": self.online,
            "timestamp": self.timestamp,
        }


def find_interfaces() -> list:
    try:
        items = hid_win.enumerate_hid()
    except Exception as exc:  # noqa: BLE001
        raise PmoError(f"枚举 HID 设备失败：{exc}") from exc
    return [it for it in items
            if it.vid == VID and it.pid in (PID_DONGLE, PID_WIRED)
            and it.usage_page == USAGE_PAGE and it.usage == USAGE]


def find_interface():
    items = find_interfaces()
    if not items:
        return None
    # 同时插着 dongle 和有线键盘时优先 dongle，其次按路径稳定排序
    items.sort(key=lambda it: (it.pid != PID_DONGLE, it.path))
    return items[0]


def _build_frame(cmd: int, payload_size: int, total_payload: int) -> bytes:
    """构造 HID 报文：1 字节 Report ID 0 + total_payload 字节负载。"""
    payload = bytearray(total_payload)
    payload[0] = PREFIX
    payload[1] = cmd
    payload[4] = payload_size
    return bytes([REPORT_ID]) + bytes(payload)


def _normalize(raw: bytes) -> bytes:
    if raw and raw[0] == REPORT_ID and len(raw) > 1:
        return bytes(raw[1:])
    return bytes(raw)


def _read_reply(dev, cmd: int, timeout: float) -> bytes | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = dev.read_input(timeout_ms=120)
        if not raw:
            continue
        body = _normalize(raw)
        # RDR 正常回复以 0xAA 开头；QMK/VIA 固件会用 0xFF 表示“不支持该命令”
        if len(body) >= 8 and body[1] == cmd and body[0] in (PREFIX, 0xFF):
            return body
    return None


def _command(dev, cmd: int, payload_size: int, total_payload: int,
             timeout: float = 1.2) -> bytes | None:
    dev.write_output(_build_frame(cmd, payload_size, total_payload),
                     use_hidd=False)
    return _read_reply(dev, cmd, timeout)


def read_battery(interface=None, timeout: float = 1.2,
                 retries: int = 3, debug: bool = False) -> KeyboardBattery:
    """读取一次 WAVE75 电量。键盘休眠 / 未连 2.4G 时抛 PmoError。"""
    last_error = None
    for attempt in range(1, retries + 1):
        iface = interface or find_interface()
        if iface is None:
            raise PmoError(
                "没有找到 PMO WAVE75 的 0xFF60/0x61 接口。\n"
                "请确认 2.4G dongle 已插好，或键盘已用 USB 连接。"
            )
        total = max(iface.output_len - 1, 32)
        payload_size = 56 if total >= 64 else 24
        dev = None
        try:
            dev = hid_win.HidDevice(iface.path, write=True)
            if not dev.write_access:
                raise PmoError("HID 接口被独占，无法发送指令。请退出 PMO HUB / VIA 网页后重试。")
            dev.drain()

            # 1) 开始会话
            start = _command(dev, CMD_START, payload_size, total, timeout)
            if debug:
                print("  [debug] start :", (start or b"").hex(" "))
            if start and start[0] == 0xFF and start[1] == CMD_START:
                raise PmoError(
                    "键盘当前是 QMK/VIA 固件：VIA 可以改键，但固件没有实现主机侧电量命令，"
                    "只能按 Fn+Backspace 用数字键灯看电量。\n"
                    "要在这台电脑上读电量，需要刷回 PMO HUB 官方固件。"
                )
            if not start:
                if iface.pid == PID_DONGLE:
                    raise PmoError(
                        "2.4G dongle 不转发厂商 HID 命令（官方驱动和 VIA 在 2.4G 下也连不上），"
                        "请用 USB 线连接键盘后再读电量。"
                    )
                raise PmoError("键盘没有响应（可能休眠或接口被占用），请按一下键盘后重试。")
            if start[7] != STATUS_OK:
                raise PmoError(f"开始会话被拒绝：status=0x{start[7]:02X}")

            # 2) 读电量
            body = _command(dev, CMD_BATTERY, payload_size, total, timeout)
            if debug:
                print("  [debug] battery:", (body or b"").hex(" "))
            if body is None:
                raise PmoError("电量查询超时，请按一下键盘后重试。")
            if body[7] != STATUS_OK:
                raise PmoError(f"设备返回状态 0x{body[7]:02X}，电量尚未就绪。")

            percent = min(100, max(0, body[8]))
            charging = body[9]
            link = body[13] if len(body) > 13 else 0

            # 3) 结束会话（失败不影响结果）
            try:
                _command(dev, CMD_STOP, payload_size, total, timeout=0.5)
            except Exception:
                pass

            return KeyboardBattery(
                percent=percent,
                charging=charging,
                link=link,
                raw=body,
                dongle=(iface.pid == PID_DONGLE),
                timestamp=time.time(),
            )
        except PmoError as exc:
            last_error = exc
        except (hid_win.HidError, OSError) as exc:
            last_error = PmoError(f"HID 读写失败：{exc}")
        finally:
            if dev is not None:
                dev.close()
        if debug:
            print(f"  [debug] 第 {attempt} 次失败：{last_error}")
        time.sleep(0.2)
    raise last_error or PmoError("读取失败")


if __name__ == "__main__":
    print(read_battery(debug=True).to_dict())
