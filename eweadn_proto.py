# -*- coding: utf-8 -*-
"""
eweadn_proto.py —— 迈从 / EWEADN 8K（VID 0x3554, PID 0xF517）电量协议。

协议来自对 EWEADN E-HUB（Electron 版）WebHID 前端代码的逆向，
并使用本机真实设备回包验证。属于「匠盟（Jiangmeng）」方案鼠标的
16 字节私有报文：

    请求（HID Output Report，Report ID = 0x08）：
        08 | cmd | 00 00 | len | payload[0..10] | checksum
        - cmd       命令字（0x03 = 查询在线状态，0x04 = 查询电量）
        - len       payload 长度
        - checksum  = (0x55 - (0x08 + sum(bytes[0..14]))) & 0xFF
                    = (0x4D - sum(bytes[0..14])) & 0xFF
        整帧 17 字节（含 Report ID），有效载荷 16 字节。

    回复（HID Input Report，Report ID = 0x08）：
        [0]     0x08（ReadFile 读出来带 Report ID；WebHID 的 data 不含）
        [1]     命令字（与请求相同）
        [2]     状态：0x00 成功，0x01 不支持 / 失败
        [3..4]  保留
        [5]     电量百分比（设备自己算的，0~100）
        [6]     充电状态：1 = 正在充电
        [7..8]  电池电压，大端，单位 mV
        [9..14] 保留
        [15]    校验和

设备端会优先用电压查表算电量（见 VOLTAGE_CURVE），与 E-HUB 界面一致。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import hid_win
import device_lock

VID = 0x3554
PID = 0xF517
PRODUCT_NAME = "EWEADN 8K"

# 真正跑私有协议的顶层集合：usage page 0xFF02 / usage 0x0002，
# 输入 / 输出报告都是 17 字节（1 字节 Report ID + 16 字节报文）。
USAGE_PAGE = 0xFF02
USAGE = 0x0002

REPORT_ID = 0x08
PACKET_SIZE = 16
FRAME_SIZE = PACKET_SIZE + 1  # 含 Report ID

CMD_DEVICE_ONLINE = 0x03
CMD_BATTERY = 0x04

# 与 E-HUB 前端一致的电压 -> 电量曲线（单位 mV，5% 一档）
VOLTAGE_CURVE = [
    3050, 3420, 3480, 3540, 3600, 3660, 3720, 3760, 3800, 3840, 3880,
    3920, 3940, 3960, 3980, 4000, 4020, 4040, 4060, 4080, 4110,
]


class EweadnError(RuntimeError):
    """读取失败（找不到设备 / 接口被独占 / 鼠标休眠等）。"""


@dataclass
class BatteryReading:
    percent: int
    level_raw: int
    charging: bool
    voltage_mv: int
    online: bool
    percent_source: str          # "voltage" 或 "level"
    raw: bytes = field(default=b"", repr=False)
    timestamp: float = field(default_factory=time.time)

    @property
    def voltage_v(self) -> float:
        return self.voltage_mv / 1000.0

    def to_dict(self) -> dict:
        return {
            "product": PRODUCT_NAME,
            "vid": f"0x{VID:04X}",
            "pid": f"0x{PID:04X}",
            "percent": self.percent,
            "level_raw": self.level_raw,
            "charging": self.charging,
            "voltage_mv": self.voltage_mv,
            "voltage_v": round(self.voltage_v, 3),
            "online": self.online,
            "percent_source": self.percent_source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 报文构造 / 解析
# ---------------------------------------------------------------------------
def checksum(packet: bytes) -> int:
    """16 字节报文的第 15 字节 = (0x4D - sum(bytes[0..14])) & 0xFF。

    等价于厂商前端里的 `0x55 - (sum + ReportId)`：设备把 Report ID 0x08
    也计入了校验和。
    """
    return (0x4D - (sum(packet[:15]) & 0xFF)) & 0xFF


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    """构造一条发往设备的 17 字节 Output Report（含 Report ID）。"""
    if not 0 <= cmd <= 0xFF:
        raise ValueError("cmd 必须在 0..255")
    if len(payload) > 10:
        raise ValueError("payload 最长 10 字节（报文只有 16 字节）")
    pkt = bytearray(PACKET_SIZE)
    pkt[0] = cmd
    pkt[4] = len(payload)
    pkt[5:5 + len(payload)] = payload
    pkt[15] = checksum(pkt)
    return bytes([REPORT_ID]) + bytes(pkt)


def normalize_report(raw: bytes) -> Optional[bytes]:
    """把 ReadFile 读到的 17 字节报文归一化成 16 字节（去掉 Report ID）。

    兼容两种驱动行为：带 Report ID / 不带 Report ID。
    """
    if not raw:
        return None
    if raw[0] == REPORT_ID and len(raw) >= PACKET_SIZE + 1:
        return bytes(raw[1:1 + PACKET_SIZE])
    if len(raw) >= PACKET_SIZE:
        return bytes(raw[:PACKET_SIZE])
    return None


def parse_status(body: bytes) -> dict:
    """解析一条 16 字节回复。"""
    if len(body) < PACKET_SIZE:
        raise ValueError("回复长度不足 16 字节")
    return {
        "cmd": body[0],
        "status": body[1],
        "level": body[5],
        "charging": body[6] == 1,
        "voltage_mv": (body[7] << 8) | body[8],
    }


def voltage_to_percent(voltage_mv: int) -> int:
    """按厂商曲线把电压换算成 1~100 的百分比（与 E-HUB 显示基本一致）。

    厂商原实现是分段线性插值，但在 0% / 15% 边界有 +1 的修正，
    会导致 3051 mV 显示 0%、3541 mV 反而比 3540 mV 低 1%。
    这里保留曲线、去掉边界抖动，并限制在 1~100。
    """
    table = VOLTAGE_CURVE
    if voltage_mv >= table[-1]:
        return 100
    if voltage_mv <= table[0]:
        return 1
    # 找到第一个比电压大的档位
    idx = next(i for i, mv in enumerate(table) if voltage_mv < mv)
    step = (table[idx] - table[idx - 1]) / 5.0
    pct = (voltage_mv - table[idx - 1]) / step + 5 * (idx - 1)
    return max(1, min(100, int(round(pct))))


# ---------------------------------------------------------------------------
# 设备发现
# ---------------------------------------------------------------------------
def find_interfaces() -> list:
    """枚举本机上属于 EWEADN 8K 的 HID 接口。"""
    try:
        items = hid_win.enumerate_hid()
    except Exception as exc:  # setupapi 偶尔会被安全软件拦截
        raise EweadnError(f"枚举 HID 设备失败：{exc}") from exc
    return [it for it in items if (it.vid, it.pid) == (VID, PID)]


def find_control_interface():
    """找到跑私有协议的 0xFF02/0x0002 集合；找不到返回 None。"""
    candidates = [
        it for it in find_interfaces()
        if it.usage_page == USAGE_PAGE and it.usage == USAGE
        and it.output_len >= FRAME_SIZE and it.input_len >= FRAME_SIZE
    ]
    if not candidates:
        return None
    # 同型号可能插多个接收器，优先 col05（协议集合），否则取第一个
    candidates.sort(key=lambda it: ("col05" not in it.path.lower(), it.path))
    return candidates[0]


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------
def _read_matching(dev: "hid_win.HidDevice", cmd: int, timeout: float) -> Optional[bytes]:
    """在 timeout 内等待一条指定命令字的回复，返回归一化后的 16 字节报文。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = dev.read_input(timeout_ms=120)
        if not raw:
            continue
        body = normalize_report(raw)
        if body and body[0] == cmd:
            return body
    return None


@device_lock.locked
def read_battery(interface=None, timeout: float = 1.2,
                 retries: int = 3, debug: bool = False) -> BatteryReading:
    """读取一次电量。

    interface 为 None 时自动发现；也可传入 find_control_interface() 的结果。
    鼠标休眠 / 未连接时抛 EweadnError。
    """
    root_error = None
    for attempt in range(1, retries + 1):
        iface = interface or find_control_interface()
        if iface is None:
            raise EweadnError(
                "没有找到 EWEADN 8K 的 0xFF02 私有接口。\n"
                "请确认接收器已插好、鼠标已开机并与接收器配对。"
            )
        dev = None
        try:
            dev = hid_win.HidDevice(iface.path, write=True)
            if not dev.write_access:
                raise EweadnError(
                    "HID 接口被独占，无法发送指令。请退出 EWEADN E-HUB 后重试。"
                )
            dev.drain()

            # 1) 查询在线状态（顺便唤醒鼠标）
            dev.write_output(build_frame(CMD_DEVICE_ONLINE))
            online_body = _read_matching(dev, CMD_DEVICE_ONLINE, timeout)
            if debug:
                print("  [debug] online  :", (online_body or b"").hex(" "))
            online = bool(online_body and online_body[1] == 0 and online_body[5] == 1)
            if not online:
                raise EweadnError("鼠标处于休眠 / 未连接状态，请动一下鼠标后重试。")

            # 2) 查询电量
            dev.write_output(build_frame(CMD_BATTERY))
            body = _read_matching(dev, CMD_BATTERY, timeout)
            if debug:
                print("  [debug] battery :", (body or b"").hex(" "))
            if body is None:
                raise EweadnError("电量查询超时，请动一下鼠标后重试。")
            if body[1] != 0:
                raise EweadnError(f"设备返回错误状态 0x{body[1]:02X}（可能不支持该指令）。")

            info = parse_status(body)
            voltage = info["voltage_mv"]
            if voltage > 0:
                percent, source = voltage_to_percent(voltage), "voltage"
            else:
                percent, source = max(0, min(100, info["level"])), "level"

            return BatteryReading(
                percent=percent,
                level_raw=info["level"],
                charging=info["charging"],
                voltage_mv=voltage,
                online=True,
                percent_source=source,
                raw=body,
            )
        except EweadnError as exc:
            root_error = exc
            if debug:
                print(f"  [debug] 第 {attempt} 次失败：{exc}")
            time.sleep(0.15)
        except (hid_win.HidError, OSError) as exc:
            root_error = EweadnError(f"HID 读写失败：{exc}")
            if debug:
                print(f"  [debug] 第 {attempt} 次异常：{exc}")
            time.sleep(0.15)
        finally:
            if dev is not None:
                dev.close()

    raise root_error or EweadnError("读取失败")


if __name__ == "__main__":
    reading = read_battery(debug=True)
    print(reading.to_dict())
