# -*- coding: utf-8 -*-
"""generic_protocols.py —— 多厂商 2.4G 外设电量协议库。

协议来自（按项目 README / PROTOCOLS.md 收录）：
  * 2.4G-battery-viewer：ATK/VXE、Endgame、VAXEE、Nordic、罗技 HID++、DARKRIM 杰理
  * EZ2.4G：ATK 1/2、MCHOSE V9/A5/A7/gmouse/Z75S、XIBERIA、Rapoo、杰理、罗技
  * 以及本机已有的 EWEADN 8K、PMO WAVE75

只发送只读查询，不写设备配置。每个协议都先按 VID/PID/usage 精确匹配，
匹配不到再走标准 HID 电量字段。扫描入口见 generic_scan.py。
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

import hid_win as hw
from hid_win import HidDevice, HidError, HidInterface, HidP_Feature

# --------------------------------------------------------------------------
# 结果
# --------------------------------------------------------------------------


@dataclass
class Reading:
    name: str = ""
    vid: int = 0
    pid: int = 0
    usage_page: int = 0
    percent: Optional[int] = None
    charging: Optional[bool] = None
    status: str = "unknown"
    voltage_mv: Optional[int] = None
    source: str = ""
    detail: str = ""
    raw: bytes = b""
    ok: bool = True

    @property
    def key(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}"

    @property
    def charging_text(self) -> str:
        if self.charging is True:
            return "充电中"
        if self.status == "full":
            return "已充满"
        if self.charging is False:
            return "未充电"
        return "未知"

    def to_dict(self) -> dict:
        return {
            "name": self.name, "key": self.key,
            "vid": f"0x{self.vid:04X}", "pid": f"0x{self.pid:04X}",
            "usage_page": f"0x{self.usage_page:04X}",
            "percent": self.percent, "charging": self.charging,
            "status": self.status, "voltage_mv": self.voltage_mv,
            "source": self.source, "detail": self.detail,
        }


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


def _iface_name(ifaces: list[HidInterface]) -> str:
    for d in ifaces:
        if d.product:
            return d.product
    return "未知 2.4G 设备"


def _usage_ok(d: HidInterface, page: Optional[int], usage: Optional[int]) -> bool:
    if page is not None and d.usage_page != page:
        return False
    if usage is not None and d.usage != usage:
        return False
    return True


def interface_number(path: str) -> Optional[int]:
    m = re.search(r"mi_([0-9a-f]{2})", path or "", re.I)
    return int(m.group(1), 16) if m else None


def select(ifaces: list[HidInterface], page: Optional[int] = None,
           usage: Optional[int] = None, min_input: int = 0,
           min_output: int = 0, min_feature: int = 0,
           interface: Optional[int] = None) -> list[HidInterface]:
    out = []
    for d in ifaces:
        if not _usage_ok(d, page, usage):
            continue
        if d.input_len < min_input or d.output_len < min_output:
            continue
        if d.feature_len < min_feature:
            continue
        if interface is not None:
            num = interface_number(d.path)
            if num is not None and num != interface:
                continue
        out.append(d)
    return out


# --------------------------------------------------------------------------
# 帧构造 / 解析（纯函数，方便单元测试）
# --------------------------------------------------------------------------


def atk1_checksum(report_id: int, cmd: bytes) -> int:
    total = report_id + sum(cmd[:15])
    return (0x55 - (total & 0xFF)) & 0xFF


def atk1_request(report_id: int = 0x08, total: int = 17) -> bytes:
    cmd = bytearray([0x04] + [0x00] * 15)
    cmd[15] = atk1_checksum(report_id, bytes(cmd))
    body = bytes([report_id]) + bytes(cmd)
    return body + bytes(max(0, total - len(body)))


def atk1_valid(rep: bytes) -> bool:
    return (len(rep) >= 17 and rep[0] == 0x08 and rep[1] == 0x04
            and (sum(rep[:16]) + rep[16]) & 0xFF == 0x55)


def atk2_request(report_id: int = 0x08, total: int = 64) -> bytes:
    body = bytes([report_id, 0x7D, 0x72, 0x02, 0x00, 0x01, 0x07, 0x01])
    return body + bytes(max(0, total - len(body)))


def atk2_valid(rep: bytes) -> bool:
    return len(rep) > 7 and rep[1] == 0x72 and rep[5] == 0x07


def mchose_a5_request(total: int = 65) -> bytes:
    buf = bytearray(total)
    buf[3] = 0x02
    buf[4] = 0x02
    buf[6] = 0x83
    return bytes(buf)


def parse_mchose_a5(rep: bytes) -> tuple[Optional[int], Optional[int]]:
    if len(rep) < 9 or rep[8] > 100:
        return None, None
    return int(rep[8]), int(rep[7])


def mchose_a7_request(report_id: int = 0x11, total: int = 64) -> bytes:
    buf = bytearray(total)
    buf[0] = report_id
    raw = bytes([0x06] + [0x00] * 19)
    for i, b in enumerate(raw):
        if 1 + i < total:
            buf[1 + i] = b ^ 0xFF
    return bytes(buf)


def parse_mchose_a7(rep: bytes) -> tuple[Optional[int], Optional[int]]:
    if len(rep) < 13:
        return None, None
    raw = bytes(b ^ 0xFF for b in rep)
    payload = raw[2:]
    if len(payload) < 11 or payload[9] > 100:
        return None, None
    return int(payload[9]), int(payload[10])


def gmouse_request(total: int = 65) -> bytes:
    buf = bytearray(total)
    buf[0:9] = bytes([0x00, 0x55, 0x30, 0xA5, 0x0B, 0x2E, 0x01, 0x01, 0x01])
    return bytes(buf)


def parse_gmouse(rep: bytes) -> tuple[Optional[int], Optional[bool]]:
    if len(rep) < 10:
        return None, None
    off = 0 if rep[0:2] == b"\xaa\x30" else (1 if len(rep) > 1 and rep[1:3] == b"\xaa\x30" else -1)
    if off < 0 or len(rep) <= off + 9:
        return None, None
    level = rep[off + 8]
    if level > 100:
        return None, None
    return int(level), rep[off + 9] != 0


def z75s_request(total: int = 20) -> bytes:
    body = bytes([0x13, 0x4A, 0x01, 0x00]) + bytes(15)
    body = body[:total - 1]
    return body + bytes([sum(body) & 0xFF])


def parse_z75s(rep: bytes) -> Optional[int]:
    if len(rep) < 6 or rep[5] > 100:
        return None
    return int(rep[5])


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_jl_frame(seq: int, payload: bytes, report_id: int = 0x00,
                   total: int = 65, sub: int = 0x02, ch: int = 0x10,
                   frag: int = 0, more: int = 0) -> bytes:
    f = bytearray(total)
    f[0] = report_id & 0xFF
    f[1] = 0xFE
    f[2] = seq & 0xFF
    f[3] = ch
    f[4] = 0x00
    f[5] = sub
    f[6] = frag
    f[7] = more
    f[8] = len(payload) & 0xFF
    f[9] = (len(payload) >> 8) & 0xFF
    f[10:10 + len(payload)] = payload
    crc = crc16_ccitt(bytes(f[1:10 + len(payload)]))
    f[10 + len(payload)] = (crc >> 8) & 0xFF
    f[11 + len(payload)] = crc & 0xFF
    return bytes(f)


def parse_jl_frame(report: bytes) -> Optional[dict]:
    if len(report) < 12 or report[1] != 0xFE:
        return None
    ln = report[8] | (report[9] << 8)
    if 10 + ln + 2 > len(report):
        return None
    payload = report[10:10 + ln]
    crc = (report[10 + ln] << 8) | report[11 + ln]
    return {"seq": report[2], "ch": report[3], "sub": report[5],
            "frag": report[6], "more": report[7], "payload": payload,
            "crc_ok": crc == crc16_ccitt(report[1:10 + ln])}


def jl_tlvs(payload: bytes) -> list[tuple[int, bytes]]:
    out = []
    i = 0
    while i + 2 <= len(payload):
        t, ln = payload[i], payload[i + 1]
        out.append((t, payload[i + 2:i + 2 + ln]))
        i += 2 + ln
    return out


def zowie_percent(mv: int) -> int:
    points = [(3500, 0), (3680, 10), (3760, 25), (3890, 50),
              (4000, 75), (4200, 100)]
    if mv <= points[0][0]:
        return 0
    if mv >= points[-1][0]:
        return 100
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= mv <= x1:
            return _clamp(round(y0 + (y1 - y0) * (mv - x0) / (x1 - x0)))
    return 0


# --------------------------------------------------------------------------
# 协议描述
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    name: str
    kind: str
    vid: int
    pids: tuple = ()
    any_pid: bool = False
    usage_page: Optional[int] = None
    usage: Optional[int] = None
    min_input: int = 0
    min_output: int = 0
    min_feature: int = 0
    interface: Optional[int] = None
    priority: int = 50
    notes: str = ""

    def matches(self, ifaces: list[HidInterface]) -> bool:
        if not ifaces or ifaces[0].vid != self.vid:
            return False
        pid = ifaces[0].pid
        if not self.any_pid and self.pids and pid not in self.pids:
            return False
        if self.kind == "zowie":
            return bool(select(ifaces, 0xFF03, min_output=16)) and \
                bool(select(ifaces, 0xFF04, min_input=16))
        return bool(select(ifaces, self.usage_page, self.usage,
                           self.min_input, self.min_output, self.min_feature,
                           self.interface))


SPECS: list[Spec] = [
    # ---- 本机已有的两个设备，扫描时也显示 ----
    Spec("EWEADN 8K（本机鼠标）", "eweadn", 0x3554, (0xF517,),
         usage_page=0xFF02, min_output=17, priority=5),
    Spec("PMO WAVE75（本机键盘）", "pmo", 0x36B0, (0x3002, 0x3009),
         usage_page=0xFF60, priority=5),

    # ---- ATK / VXE / VGN ----
    Spec("ATK/VXE 协议 1（17B/0x55）", "atk1", 0x373B,
         pids=(0x1278, 0x128E, 0x1216, 0x10C9),
         usage_page=0xFF02, min_input=17, min_output=17, priority=20),
    Spec("Dareu A950（ATK 1）", "atk1", 0x260D, (0x1175,),
         usage_page=0xFF02, min_input=17, min_output=17, priority=20),
    Spec("VXE/VGN（ATK 1）", "atk1", 0x3554, (0x1216, 0xFB34),
         usage_page=0xFF02, min_input=17, min_output=17, priority=20),
    Spec("ATK/VXE 协议 2（64B/0x72）", "atk2", 0x373B, any_pid=True,
         usage_page=0xFF05, min_input=7, min_output=64, priority=25),
    Spec("ATK/VXE 协议 2（64B/0x72）", "atk2", 0x3554, any_pid=True,
         usage_page=0xFF05, min_input=7, min_output=64, priority=25),

    # ---- MCHOSE ----
    Spec("MCHOSE V9 Turbo / Turbo+", "mchose_v9", 0x3837, (0x600D, 0x600A),
         usage_page=0xFF90, min_output=64, priority=20),
    Spec("MCHOSE V9 Turbo / Turbo+", "mchose_v9", 0x1837, (0x600D,),
         usage_page=0xFF90, min_output=64, priority=20),
    Spec("MCHOSE A5 / AX5", "mchose_a5", 0x2023,
         (0xF012, 0xF013, 0xF015, 0xF016, 0xF017, 0xF018, 0xF019,
          0xF021, 0xF022, 0xF023, 0xF024, 0xF025, 0xF026),
         min_feature=65, interface=2, priority=20),
    Spec("MCHOSE A7 compatible", "mchose_a7", 0x5253, (0x1021,),
         min_feature=64, priority=20),
    Spec("MCHOSE gmouse（G3/A7e/G7）", "mchose_gmouse", 0xA8A5, any_pid=True,
         usage_page=0xFF01, min_output=64, priority=22),
    Spec("MCHOSE gmouse（G3/A7e/G7）", "mchose_gmouse", 0xA8A4, any_pid=True,
         usage_page=0xFF01, min_output=64, priority=22),
    Spec("MCHOSE gmouse（G3/A7e/G7）", "mchose_gmouse", 0x3837, any_pid=True,
         usage_page=0xFF01, min_output=64, priority=22),
    Spec("MCHOSE Z75S 键盘", "mchose_z75s", 0x258A, (0x01BB,),
         usage_page=0xFF02, min_input=20, min_output=20, priority=20),

    # ---- 其他厂商 ----
    Spec("ATK N9V2 耳机", "mchose_v9", 0x373B, (0x1262,),
         usage_page=0xFF90, min_output=64, priority=20),
    Spec("XIBERIA T7", "xiberia", 0x36F9, any_pid=True,
         usage_page=0xFF00, min_output=64, priority=20),
    Spec("Rapoo VT3S", "rapoo", 0x24AE, (0x1411,),
         usage_page=0xFF00, usage=0x0002, min_input=19, priority=20),
    Spec("Endgame Gear（XM2w/OP1W）", "endgame", 0x3367, any_pid=True,
         usage_page=0xFF01, min_feature=64, priority=20),
    Spec("VAXEE / ZYGEN", "vaxee", 0x3057, any_pid=True,
         usage_page=0xFF05, min_feature=64, priority=20),
    Spec("Nordic nRF 接收器", "nordic", 0x1915, any_pid=True,
         usage_page=0xFFA0, min_feature=32, priority=20),
    Spec("罗技 HID++ 2.0", "logitech", 0x046D, any_pid=True,
         min_output=7, priority=20),
    Spec("DARKRIM / 杰理 JL_RCSP", "darkrim", 0x3654, (0x6901,),
         usage_page=0xFF02, usage=0x0002, min_output=65, priority=20),
    Spec("ZOWIE DW（实验）", "zowie", 0x04A5, (0x800A,), priority=30),
]


# --------------------------------------------------------------------------
# 读取辅助
# --------------------------------------------------------------------------


def _read_until(dev: HidDevice, seconds: float, predicate: Callable[[bytes], bool],
                timeout_ms: int = 200) -> Optional[bytes]:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rep = dev.read_input(timeout_ms=timeout_ms)
        if rep and predicate(rep):
            return rep
    return None


def _send_and_read(ifaces: list[HidInterface], req: bytes, seconds: float,
                   predicate: Callable[[bytes], bool],
                   usage_page: Optional[int] = None,
                   min_output: int = 0) -> Optional[bytes]:
    cand = select(ifaces, usage_page, min_output=min_output)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                dev.drain()
                payload = req
                if len(payload) < d.output_len:
                    payload = payload + bytes(d.output_len - len(payload))
                dev.write_output(payload)
                rep = _read_until(dev, seconds, predicate)
                if rep:
                    return rep
        except HidError:
            continue
    return None


def _reading(ifaces, percent: Optional[int], source: str, detail: str = "",
             raw: bytes = b"", charging: Optional[bool] = None,
             status: str = "unknown", voltage_mv: Optional[int] = None) -> Reading:
    d = ifaces[0]
    return Reading(name=_iface_name(ifaces), vid=d.vid, pid=d.pid,
                   usage_page=d.usage_page, percent=percent,
                   charging=charging, status=status, voltage_mv=voltage_mv,
                   source=source, detail=detail, raw=raw)


# --------------------------------------------------------------------------
# 各协议读取
# --------------------------------------------------------------------------


def read_eweadn(spec: Spec, ifaces: list[HidInterface],
                fast: bool = False) -> Optional[Reading]:
    import eweadn_proto as proto
    try:
        r = proto.read_battery(retries=1, timeout=0.45 if fast else 1.2)
    except Exception:
        return None
    d = ifaces[0]
    return Reading(name=_iface_name(ifaces), vid=d.vid, pid=d.pid,
                   usage_page=0xFF02, percent=r.percent, charging=r.charging,
                   status="charging" if r.charging else "discharging",
                   voltage_mv=r.voltage_mv, source="EWEADN 0xFF02（本机协议）",
                   detail=f"设备自报 {r.level_raw}% · {r.voltage_v:.3f} V")


def read_pmo(spec: Spec, ifaces: list[HidInterface],
             fast: bool = False) -> Optional[Reading]:
    import pmo_proto as proto
    try:
        r = proto.read_battery(retries=1, timeout=0.45 if fast else 1.2)
    except Exception:
        return None
    d = ifaces[0]
    return Reading(name=_iface_name(ifaces), vid=d.vid, pid=d.pid,
                   usage_page=0xFF60, percent=r.percent,
                   charging=(r.charging == 1),
                   status="charging" if r.charging == 1 else (
                       "full" if r.charging == 2 else "discharging"),
                   source="PMO RDR 0xFF60（本机协议）",
                   detail=f"{r.charging_text} · {'2.4G' if r.dongle else 'USB'}")


def read_atk1(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF02, min_input=17, min_output=17)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                for _ in range(3):
                    dev.drain()
                    dev.write_output(atk1_request(0x08, max(17, d.output_len)))
                    rep = _read_until(dev, 0.8, atk1_valid)
                    if rep:
                        wired = len(rep) > 7 and rep[7] != 0
                        return _reading(ifaces, _clamp(rep[6]),
                                        "ATK 协议 1（0xFF02/17B）",
                                        f"电量字节=0x{rep[6]:02X}；"
                                        f"{'有线' if wired else '无线'}",
                                        rep, charging=None,
                                        status="wired" if wired else "discharging")
        except HidError:
            continue
    return None


def read_atk2(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF05, min_output=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                for _ in range(3):
                    dev.drain()
                    dev.write_output(atk2_request(0x08, max(64, d.output_len)))
                    rep = _read_until(dev, 0.8, atk2_valid)
                    if rep:
                        return _reading(ifaces, _clamp(rep[7]),
                                        "ATK 协议 2（0xFF05/64B）",
                                        f"回复 {rep[:12].hex(' ')}", rep)
        except HidError:
            continue
    return None


def read_mchose_v9(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF90, min_output=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                req = bytes([0x55, 0x65, 0x01]) + bytes(
                    max(0, d.output_len - 3))
                dev.drain()
                dev.write_output(req)
                rep = _read_until(
                    dev, 1.2,
                    lambda r: (len(r) >= 3 and r[0] == 0x55 and r[1] == 0x65
                               and r[2] <= 100))
                if rep:
                    raw_state = rep[3] if len(rep) > 3 else 0
                    st = {0x02: "discharging", 0x03: "charging",
                          0x04: "full"}.get(raw_state, "unknown")
                    return _reading(ifaces, rep[2],
                                    "MCHOSE 0x55/0x65（0xFF90）",
                                    f"状态=0x{raw_state:02X}", rep,
                                    charging=st == "charging",
                                    status=st)
        except HidError:
            continue
    return None


def read_mchose_a5(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, min_feature=65, interface=2)
    if not cand:
        cand = select(ifaces, min_feature=65)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                req = mchose_a5_request(max(65, d.feature_len))
                for _ in range(3):
                    dev.set_feature_report(req)
                    time.sleep(0.06)
                    rep = dev.get_feature_report(0x00, max(65, d.feature_len))
                    pct, code = parse_mchose_a5(rep)
                    if pct is not None:
                        status = {0: "discharging", 1: "charging",
                                  2: "full"}.get(code, "unknown")
                        return _reading(ifaces, pct,
                                        "MCHOSE A5/AX5 Feature 0x83",
                                        f"充电状态={code}", rep,
                                        charging=True if code == 1 else (
                                            False if code == 0 else None),
                                        status=status)
        except HidError:
            continue
    return None


def read_mchose_a7(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, min_feature=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                req = mchose_a7_request(0x11, max(64, d.feature_len))
                dev.set_feature_report(req)
                time.sleep(0.2)
                rep = dev.get_feature_report(0x11, max(64, d.feature_len))
                pct, code = parse_mchose_a7(rep)
                if pct is not None:
                    status = {0: "discharging", 1: "charging",
                              2: "full"}.get(code, "unknown")
                    return _reading(ifaces, pct, "MCHOSE A7（Feature 0x11）",
                                    "响应整体 XOR 0xFF", rep,
                                    charging=True if code == 1 else (
                                        False if code == 0 else None),
                                    status=status)
        except HidError:
            continue
    return None


def read_mchose_gmouse(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF01, min_output=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                dev.drain()
                dev.write_output(gmouse_request(max(65, d.output_len)))
                rep = _read_until(
                    dev, 1.5,
                    lambda r: (len(r) >= 10
                               and (r[0:2] == b"\xaa\x30"
                                    or (len(r) > 1 and r[1:3] == b"\xaa\x30"))))
                if rep:
                    pct, ch = parse_gmouse(rep)
                    if pct is not None:
                        return _reading(ifaces, pct, "MCHOSE gmouse（0xAA30）",
                                        f"回复 {rep[:20].hex(' ')}", rep,
                                        charging=ch,
                                        status="charging" if ch else "discharging")
        except HidError:
            continue
    return None


def read_mchose_z75s(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    req = z75s_request(20)
    rep = _send_and_read(ifaces, req, 1.2,
                         lambda r: parse_z75s(r) is not None,
                         usage_page=0xFF02, min_output=20)
    if rep:
        return _reading(ifaces, parse_z75s(rep),
                        "MCHOSE Z75S（0x13/0x4A）",
                        f"校验和=0x{req[-1]:02X}", rep)
    return None


def read_xiberia(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    req = bytes([0x55, 0x65, 0x00]) + bytes(61)
    rep = _send_and_read(ifaces, req, 1.2,
                         lambda r: len(r) > 3 and r[0] == 0x55 and r[1] == 0x65
                         and r[3] <= 100,
                         usage_page=0xFF00, min_output=64)
    if rep:
        return _reading(ifaces, rep[3], "XIBERIA T7（0x55/0x65）",
                        f"回复 {rep[:8].hex(' ')}", rep)
    return None


def read_rapoo(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF00, usage=0x0002, min_input=19)
    for d in cand:
        try:
            with HidDevice(d.path, write=False) as dev:
                rep = _read_until(dev, 3.0,
                                  lambda r: len(r) > 8 and r[8] <= 100 and r[7] in (1, 2, 3))
                if rep:
                    st = {1: "discharging", 2: "charging", 3: "charging"}[rep[7]]
                    return _reading(ifaces, rep[8], "Rapoo VT3S（主动上报）",
                                    f"状态字节=0x{rep[7]:02X}", rep,
                                    charging=st == "charging", status=st)
        except HidError:
            continue
    return None


def read_endgame(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF01, min_feature=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                for _ in range(3):
                    dev.set_feature_report(bytes([0xA1, 0xB4]) + bytes(62))
                    time.sleep(0.3)
                    rep = dev.get_feature_report(0xA1, 64)
                    if len(rep) > 17 and rep[1] == 0x01 and rep[16] <= 100:
                        mv = rep[17] | (rep[18] << 8) if len(rep) > 18 else None
                        return _reading(ifaces, rep[16],
                                        "Endgame Gear（Feature 0xA1）",
                                        f"状态=0x{rep[1]:02X}", rep,
                                        voltage_mv=mv if mv and 2000 <= mv <= 5000 else None)
        except HidError:
            continue
    return None


def read_vaxee(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF05, min_feature=64)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                for _ in range(2):
                    dev.set_feature_report(bytes([0x0E, 0xA5, 0x0B, 0x01, 0x01]) + bytes(59))
                    time.sleep(0.15)
                    rep = dev.get_feature_report(0x0E, 64)
                    if len(rep) > 5 and rep[5] <= 20:
                        return _reading(ifaces, _clamp(rep[5] * 5),
                                        "VAXEE / ZYGEN（Feature 0x0E）",
                                        f"原始步进={rep[5]}", rep)
        except HidError:
            continue
    return None


def read_nordic(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFFA0, min_feature=32)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                req = bytes([0x05, 0x15, 0x00, 0x00, 0x01]) + bytes(27)
                dev.set_feature_report(req)
                time.sleep(0.1)
                rep = dev.get_feature_report(0x05, 32)
                if len(rep) > 9 and rep[9] <= 100:
                    return _reading(ifaces, rep[9], "Nordic nRF（Feature 0x05）",
                                    f"回复 {rep[:12].hex(' ')}", rep)
        except HidError:
            continue
    return None


def read_darkrim(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    cand = select(ifaces, 0xFF02, usage=0x0002, min_output=65)
    if not cand:
        cand = select(ifaces, 0xFF02, min_output=65)
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                frame = build_jl_frame(0, b"\x01\x00", 0, 65)
                dev.drain()
                dev.write_output(frame)
                end = time.monotonic() + 0.8
                while time.monotonic() < end:
                    rep = dev.read_input(timeout_ms=150)
                    fr = parse_jl_frame(rep) if rep else None
                    if not fr:
                        continue
                    for t, v in jl_tlvs(fr["payload"]):
                        if t == 0x01 and v and v[0] <= 100:
                            return _reading(ifaces, v[0],
                                            "DARKRIM / 杰理 JL_RCSP",
                                            f"TLV 0x01={v.hex(' ')}", rep)
                # 3654:6901 也有厂商把它当 MCHOSE 耳机；JL 失败时试一次 55 65
                if d.output_len >= 64:
                    req = bytes([0x55, 0x65, 0x01]) + bytes(d.output_len - 3)
                    dev.drain()
                    dev.write_output(req)
                    rep = _read_until(
                        dev, 0.8,
                        lambda r: (len(r) >= 3 and r[0] == 0x55
                                   and r[1] == 0x65 and r[2] <= 100))
                    if rep:
                        return _reading(ifaces, rep[2],
                                        "MCHOSE 0x55/0x65（DARKRIM 兼容）",
                                        f"回复 {rep[:8].hex(' ')}", rep)
        except HidError:
            continue
    return None


def _hidpp_error(report: bytes) -> Optional[int]:
    if len(report) < 4:
        return None
    return report[4] if report[3] & 0x80 and len(report) > 4 else (
        0xFF if report[3] & 0x80 else None)


def _hidpp_call(dev: HidDevice, rid: int, index: int, feature_index: int,
                function: int, params: list, timeout_ms: int = 260,
                total_len: Optional[int] = None) -> Optional[bytes]:
    body = [rid, index, feature_index, ((function & 0x0F) << 4) | 0x01] + list(params)
    length = total_len or (20 if rid == 0x11 else 7)
    body = (body + [0] * length)[:length]
    try:
        dev.write_output(bytes(body))
    except HidError:
        return None
    end = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < end:
        rep = dev.read_input(timeout_ms=120)
        if not rep or len(rep) < 4:
            continue
        if rep[0] != rid or rep[1] != index or rep[2] != feature_index:
            continue
        if ((rep[3] >> 4) & 0x0F) != function:
            continue
        return rep
    return None


def _hidpp_feature(dev: HidDevice, rid: int, index: int, feature_id: int) -> Optional[int]:
    rep = _hidpp_call(dev, rid, index, 0x00, 0x00,
                      [feature_id >> 8, feature_id & 0xFF])
    if not rep or _hidpp_error(rep) is not None:
        return None
    for pos in (6, 4, 5):
        if len(rep) > pos and rep[pos]:
            return rep[pos]
    return None


def _logitech_one(dev: HidDevice, rid: int, index: int) -> Optional[Reading]:
    status_map = {0: ("discharging", False), 1: ("charging", True),
                  2: ("charging", True), 3: ("full", False),
                  4: ("charging", True)}
    fidx = _hidpp_feature(dev, rid, index, 0x1000)
    if fidx:
        rep = _hidpp_call(dev, rid, index, fidx, 0x00, [])
        if rep and _hidpp_error(rep) is None and len(rep) >= 7:
            level, st = rep[4], rep[6]
            status, charging = status_map.get(st, ("unknown", None))
            if level == 0 and status == "charging":
                level = 80
            return Reading(name="罗技 HID++ 设备", percent=_clamp(level),
                           charging=charging, status=status,
                           source="罗技 HID++ 2.0（0x1000）",
                           detail=f"设备索引 {index} 状态={st}", raw=rep)
    fidx = _hidpp_feature(dev, rid, index, 0x1004)
    if fidx:
        rep = _hidpp_call(dev, rid, index, fidx, 0x00, [])
        if rep and _hidpp_error(rep) is None and len(rep) >= 6:
            level, st = rep[4], rep[5]
            status, charging = status_map.get(st, ("unknown", None))
            return Reading(name="罗技 HID++ 设备", percent=_clamp(level),
                           charging=charging, status=status,
                           source="罗技 HID++ 2.0（0x1004）",
                           detail=f"设备索引 {index} 状态={st}", raw=rep)
    fidx = _hidpp_feature(dev, rid, index, 0x1001)
    if fidx:
        rep = _hidpp_call(dev, rid, index, fidx, 0x00, [])
        if rep and _hidpp_error(rep) is None and len(rep) >= 6:
            mv = rep[4] | (rep[5] << 8)
            if 2000 <= mv <= 5000:
                return Reading(name="罗技 HID++ 设备", percent=None,
                               voltage_mv=mv, source="罗技 HID++ 2.0（0x1001）",
                               detail=f"电压 {mv} mV（该机型不直接给百分比）",
                               raw=rep)
    return None


def read_logitech(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    # HID++ 只在厂商集合上；优先 20/32 字节长报文接口（0xFF00:0x0002/0x0004），
    # 不要先试键盘集合，否则每次要等 7 个索引 × 260ms 超时。
    cand = [d for d in ifaces
            if d.vid == 0x046D and d.output_len and d.usage_page >= 0xFF00]
    cand.sort(key=lambda d: (d.output_len < 20,
                             d.usage not in (0x0002, 0x0004),
                             -d.output_len))
    for d in cand:
        try:
            with HidDevice(d.path, write=True) as dev:
                rids = [0x11] if d.output_len >= 20 else [0x10]
                if d.output_len >= 20:
                    rids.append(0x10)
                for rid in rids:
                    need = 20 if rid == 0x11 else 7
                    if dev.caps.OutputReportByteLength and \
                            dev.caps.OutputReportByteLength < need:
                        continue
                    for index in (1, 2, 3, 4, 5, 6, 0xFF):
                        r = _logitech_one(dev, rid, index)
                        if r:
                            r.name = _iface_name(ifaces)
                            r.vid, r.pid = d.vid, d.pid
                            r.usage_page = d.usage_page
                            return r
        except HidError:
            continue
    return None


def read_zowie(spec: Spec, ifaces: list[HidInterface]) -> Optional[Reading]:
    outs = select(ifaces, 0xFF03, min_output=16)
    ins = select(ifaces, 0xFF04, min_input=16)
    if not outs or not ins:
        return None
    try:
        with HidDevice(outs[0].path, write=True) as dev:
            dev.write_output(bytes([0x08, 0xB4, 0x15]) + bytes(13))
    except HidError:
        return None
    try:
        with HidDevice(ins[0].path, write=False) as dev:
            end = time.monotonic() + 1.5
            while time.monotonic() < end:
                rep = dev.read_input(timeout_ms=200)
                if not rep or len(rep) < 3:
                    continue
                idx = 1 if rep[0] == 0x09 else 0
                if len(rep) < idx + 3:
                    continue
                mv = (rep[idx] << 8 | rep[idx + 1]) * 10
                if 2500 <= mv <= 5000:
                    return _reading(ifaces, zowie_percent(mv),
                                    "ZOWIE DW（Feature 0xFF03/0xFF04，实验）",
                                    f"电压 {mv} mV", rep, voltage_mv=mv)
    except HidError:
        return None
    return None


# --------------------------------------------------------------------------
# 抓包学习的协议（可选文件）
# --------------------------------------------------------------------------

_APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.dirname(__file__),
                        "ExtBatteryTray")
CAPTURED_FILE = os.path.join(_APP_DIR, "captured.json")


def captured_protocols() -> dict:
    """读取 %APPDATA%\\ExtBatteryTray\\captured.json。

    格式：
      {"373B:1278": {"requests": ["08 04 ... 49"], "offset": 6}}
    可选 invert=true、name。
    """
    try:
        with open(CAPTURED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_captured(proto: dict, ifaces: list[HidInterface]) -> Optional[Reading]:
    off = int(proto.get("offset", 2))
    requests = proto.get("requests") or ([proto["request"]] if proto.get("request") else [])
    if isinstance(requests, str):
        requests = [requests]
    reqs = []
    for text in requests:
        try:
            raw = bytes.fromhex(str(text).replace(" ", ""))
        except ValueError:
            continue
        if len(raw) >= 2:
            reqs.append(raw)
    for req in reqs:
        for d in ifaces:
            if d.output_len < len(req) or d.input_len <= off:
                continue
            try:
                with HidDevice(d.path, write=True) as dev:
                    dev.drain()
                    buf = req + bytes(max(0, d.output_len - len(req)))
                    dev.write_output(buf)
                    end = time.monotonic() + 1.2
                    while time.monotonic() < end:
                        rep = dev.read_input(timeout_ms=200)
                        if not rep or len(rep) <= off:
                            continue
                        val = rep[off]
                        if not 0 <= val <= 100:
                            continue
                        if proto.get("invert"):
                            val = 100 - val
                        return _reading(ifaces, val, "抓包协议（captured.json）",
                                        f"请求 {req.hex(' ')} 回复 {rep[:12].hex(' ')}",
                                        rep)
            except HidError:
                continue
    return None


# --------------------------------------------------------------------------
# 标准 HID 电量字段
# --------------------------------------------------------------------------


def read_standard(ifaces: list[HidInterface]) -> Optional[Reading]:
    for d in ifaces:
        if not d.feature_len:
            continue
        try:
            with HidDevice(d.path, write=False) as dev:
                for cap in dev.value_caps(HidP_Feature):
                    usage = cap.u.NotRange.Usage if not cap.IsRange else cap.u.Range.UsageMin
                    if (cap.UsagePage, usage) not in (
                            (0x0006, 0x0020), (0x000D, 0x003B), (0x0085, 0x0065)):
                        continue
                    rep = dev.get_feature_report(cap.ReportID,
                                                 d.feature_len or 64)
                    val = dev.usage_value(HidP_Feature, rep, cap)
                    if val is None:
                        continue
                    if cap.LogicalMax and cap.LogicalMax > 0:
                        pct = _clamp(round(val * 100 / cap.LogicalMax))
                    else:
                        pct = _clamp(val * 100 / 255 if val > 100 else val)
                    return _reading(ifaces, pct, "标准 HID 电量字段",
                                    f"UsagePage=0x{cap.UsagePage:04X} "
                                    f"Usage=0x{usage:04X} 原值={val}", rep)
        except HidError:
            continue
    return None


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


READERS: dict[str, Callable[[Spec, list[HidInterface]], Optional[Reading]]] = {
    "eweadn": read_eweadn,
    "pmo": read_pmo,
    "atk1": read_atk1,
    "atk2": read_atk2,
    "mchose_v9": read_mchose_v9,
    "mchose_a5": read_mchose_a5,
    "mchose_a7": read_mchose_a7,
    "mchose_gmouse": read_mchose_gmouse,
    "mchose_z75s": read_mchose_z75s,
    "xiberia": read_xiberia,
    "rapoo": read_rapoo,
    "endgame": read_endgame,
    "vaxee": read_vaxee,
    "nordic": read_nordic,
    "logitech": read_logitech,
    "darkrim": read_darkrim,
    "zowie": read_zowie,
}


def groups(ifaces: Optional[list[HidInterface]] = None) -> dict[tuple[int, int], list[HidInterface]]:
    ifaces = ifaces if ifaces is not None else hw.enumerate_hid()
    out: dict[tuple[int, int], list[HidInterface]] = {}
    for d in ifaces:
        out.setdefault((d.vid, d.pid), []).append(d)
    return out


def matching_specs(ifaces: list[HidInterface]) -> list[Spec]:
    return [s for s in SPECS if s.matches(ifaces)]


def _scan_group(key: tuple[int, int], group: list[HidInterface],
                include_standard: bool, fast: bool) -> Optional[Reading]:
    for spec in sorted(SPECS, key=lambda s: s.priority):
        if not spec.matches(group):
            continue
        try:
            if spec.kind in ("eweadn", "pmo"):
                r = READERS[spec.kind](spec, group, fast=fast)
            else:
                r = READERS[spec.kind](spec, group)
        except Exception:
            r = None
        if r and r.ok:
            if not r.name:
                r.name = _iface_name(group)
            return r
    proto = captured_protocols().get(f"{key[0]:04X}:{key[1]:04X}")
    if proto:
        r = read_captured(proto, group)
        if r:
            return r
    if include_standard:
        return read_standard(group)
    return None


def scan(ifaces: Optional[list[HidInterface]] = None,
         include_standard: bool = True,
         fast: bool = False) -> list[Reading]:
    """并行扫描各设备；fast 会缩短已知设备的等待超时。"""
    groups_ = groups(ifaces)
    items = sorted(groups_.items())
    if not items:
        return []
    workers = min(4, len(items))
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="hid-scan") as pool:
        results = list(pool.map(
            lambda kv: _scan_group(kv[0], kv[1], include_standard, fast),
            items))
    return [r for r in results if r is not None]


def list_supported(ifaces: Optional[list[HidInterface]] = None) -> list[dict]:
    """列出每个 VID:PID 命中的协议；用于 --list。"""
    groups_ = groups(ifaces)
    captured = captured_protocols()
    out = []
    for key in sorted(groups_):
        group = groups_[key]
        specs = matching_specs(group)
        names = [s.name for s in specs]
        if f"{key[0]:04X}:{key[1]:04X}" in captured:
            names.append("抓包协议（captured.json）")
        elif not names and any(d.feature_len for d in group):
            names.append("标准 HID 电量（回退）")
        out.append({
            "key": f"{key[0]:04X}:{key[1]:04X}",
            "name": _iface_name(group),
            "interfaces": len(group),
            "protocols": names,
        })
    return out
