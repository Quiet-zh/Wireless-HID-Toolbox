# -*- coding: utf-8 -*-
"""device_registry.py —— 面板/托盘共用的设备目录与快照。

* 设备是否显示卡片、是否显示托盘图标，都保存在
  `%APPDATA%\\ExtBatteryTray\\config.json` 的 `devices` 里；
* 每次刷新用 generic_protocols 扫描，失败时回退到 last_state 缓存；
* 面板和托盘都只消费 DeviceSnapshot，不再各自写死设备。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import device_lock
import generic_protocols as gp
import last_state
import tray_common as tc

PRIMARY = {
    "3554:F517": {"name": "EWEADN 8K", "order": 10, "kind": "mouse"},
    "36B0:WAVE75": {"name": "PMO WAVE75", "order": 20, "kind": "keyboard"},
    "248A:60AB": {"name": "魔声 AI 垂直鼠标",
                  "order": 25, "kind": "mouse"},
    "1EA7:0064": {"name": "英菲克 F15 无线鼠标",
                  "order": 30, "kind": "mouse"},
    "1A2C:7FFF": {"name": "狼蛛 S99 三模键盘",
                  "order": 40, "kind": "keyboard"},
}

# 旧显示名 → 新显示名：已有配置里仍叫旧名字时，_ensure() 自动迁移
NAME_RENAMES = {
    "Monster AiMouse": "魔声 AI 垂直鼠标",
}

DEVICE_KINDS = ("mouse", "keyboard")
KIND_LABELS = {"mouse": "鼠标", "keyboard": "键盘"}


def infer_kind(key: str, name: str = "") -> str:
    text = f"{key} {name}".lower()
    if key.startswith(("36B0", "1A2C")) or "wave" in text \
            or "keyboard" in text or "键盘" in text:
        return "keyboard"
    if key in ("3554:F517", "046D:C53F", "248A:60AB", "1EA7:0064") \
            or "mouse" in text or "aimouse" in text or "monster" in text \
            or "魔声" in text or "垂直" in text or "鼠标" in text:
        return "mouse"
    return "mouse"


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, "鼠标")


@dataclass
class DeviceSnapshot:
    key: str
    name: str
    vid: int
    pid: int
    percent: Optional[int] = None
    charging: Optional[bool] = None
    status: str = "unknown"
    voltage_mv: Optional[int] = None
    source: str = ""
    link: str = "—"
    detail: str = ""
    updated: float = 0.0
    stale: bool = False
    present: bool = False
    show: bool = True
    tray: bool = True
    kind: str = "mouse"

    @property
    def charging_text(self) -> str:
        if self.status == "full":
            return "已充满"
        if self.charging is True:
            return "充电中"
        if self.charging is False:
            return "未充电"
        return "—"

    @property
    def updated_text(self) -> str:
        if not self.updated:
            return "还没有读到数据"
        stamp = time.strftime("%H:%M:%S", time.localtime(self.updated))
        return f"{'缓存于' if self.stale else '更新于'} {stamp}"

    @property
    def subtitle(self) -> str:
        return f"{self.key} · {self.source or '未知来源'}"


def _ids(key: str) -> tuple[int, int]:
    if key.startswith("36B0"):
        return 0x36B0, 0x3002
    try:
        a, b = key.split(":")
        return int(a, 16), int(b, 16)
    except Exception:
        return 0, 0


def canonical_key(key: str, vid: int, pid: int) -> str:
    if vid == 0x36B0:
        return "36B0:WAVE75"
    if vid == 0x3554 and pid == 0xF517:
        return "3554:F517"
    return key


def friendly_name(key: str, fallback: str) -> str:
    if key in PRIMARY:
        return PRIMARY[key]["name"]
    if key == "046D:C53F":
        return "罗技 G304 / Lightspeed"
    return fallback or key


def _short_source(source: str) -> str:
    source = (source or "").strip()
    if "罗技" in source or "HID++" in source:
        return "罗技 HID++"
    if "EWEADN" in source:
        return "EWEADN"
    if "魔声" in source or "AiMouse" in source or "Monster" in source:
        return "魔声 AI 垂直鼠标"
    if "PMO" in source or "RDR" in source:
        return "PMO RDR"
    if "MCHOSE" in source:
        return "MCHOSE"
    if "ATK" in source:
        return "ATK"
    if "DARKRIM" in source or "杰理" in source:
        return "杰理 JL"
    if "Endgame" in source:
        return "Endgame"
    if "VAXEE" in source:
        return "VAXEE"
    if "Nordic" in source:
        return "Nordic"
    if "抓包" in source:
        return "抓包"
    if "标准" in source:
        return "标准 HID"
    return source.split("（")[0][:18] or "未知"


def _link_for(key: str, source: str, detail: str, status: str) -> str:
    if key.startswith("36B0"):
        return "USB" if "USB" in detail else "2.4G"
    if "HID++" in source or "罗技" in source:
        return "HID++"
    if "有线" in detail or status == "wired":
        return "有线"
    return "2.4G"


def _ensure(cfg: dict) -> dict:
    devs = cfg.get("devices")
    if not isinstance(devs, dict):
        devs = {}
    changed = False
    for key, meta in PRIMARY.items():
        if key not in devs:
            devs[key] = {"name": meta["name"], "show": True, "tray": True,
                         "order": meta["order"], "kind": meta["kind"]}
            changed = True
    for key, meta in devs.items():
        if not isinstance(meta, dict):
            continue
        name = meta.get("name")
        if isinstance(name, str) and name in NAME_RENAMES:
            meta["name"] = NAME_RENAMES[name]
            changed = True
        if not meta.get("kind"):
            meta["kind"] = infer_kind(key, meta.get("name", ""))
            changed = True
    cfg["devices"] = devs
    if changed:
        tc.save_config(cfg)
    return devs


def _next_order(devs: dict) -> int:
    orders = [int(v.get("order", 0)) for v in devs.values()
              if isinstance(v, dict)]
    return (max(orders) if orders else 0) + 10


def _meta_defaults(devs: dict) -> dict:
    return {"show": True, "tray": True, "order": _next_order(devs)}


def snapshot(fast: bool = False) -> list[DeviceSnapshot]:
    """扫描一次并返回所有已知设备的快照（含休眠缓存/离线占位）。"""
    cfg = tc.load_config()
    devs = _ensure(cfg)
    changed = False

    readings: list[gp.Reading] = []
    try:
        with device_lock.scan_lock(timeout_ms=100 if fast else 400):
            readings = gp.scan(fast=fast)
    except Exception:
        readings = []

    by_key: dict[str, gp.Reading] = {}
    for r in readings:
        key = canonical_key(r.key, r.vid, r.pid)
        by_key[key] = r
        if key not in devs:
            devs[key] = {
                "name": friendly_name(key, r.name),
                "kind": infer_kind(key, r.name),
                **_meta_defaults(devs),
            }
            changed = True
        elif not devs[key].get("name"):
            devs[key]["name"] = friendly_name(key, r.name)
            changed = True

    out: list[DeviceSnapshot] = []
    for key, meta in sorted(devs.items(),
                            key=lambda kv: (int(kv[1].get("order", 0)), kv[0])):
        if not isinstance(meta, dict):
            continue
        if meta.get("deleted"):
            continue
        r = by_key.get(key)
        show = bool(meta.get("show", True))
        tray = bool(meta.get("tray", True))
        kind = meta.get("kind") or infer_kind(key, meta.get("name", ""))
        name = meta.get("name") or friendly_name(key, key)
        if r is not None:
            if r.percent is not None:
                last_state.save(key, r.percent, _short_source(r.source))
            out.append(DeviceSnapshot(
                key=key, name=name, vid=r.vid, pid=r.pid,
                percent=r.percent, charging=r.charging, status=r.status,
                voltage_mv=r.voltage_mv, source=_short_source(r.source),
                link=_link_for(key, r.source, r.detail, r.status),
                detail=r.detail, updated=time.time(), stale=False,
                present=True, show=show, tray=tray, kind=kind))
            continue

        last = last_state.get(key)
        if last is None and key == "3554:F517":
            last = last_state.get("mouse")
        elif last is None and key == "36B0:WAVE75":
            last = last_state.get("keyboard")
        if last is not None:
            vid, pid = _ids(key)
            out.append(DeviceSnapshot(
                key=key, name=name, vid=vid, pid=pid, percent=last["percent"],
                charging=None, status="休眠", source="上次缓存",
                link="—", detail=last.get("detail", ""),
                updated=float(last["ts"]), stale=True, present=False,
                show=show, tray=tray, kind=kind))
            continue

        vid, pid = _ids(key)
        out.append(DeviceSnapshot(
            key=key, name=name, vid=vid, pid=pid, percent=None,
            charging=None, status="未连接", source="", link="—",
            detail="还没有发现这个设备", updated=0.0, stale=False,
            present=False, show=show, tray=tray, kind=kind))

    if changed:
        tc.save_config(cfg)
    return out


def known_devices() -> list[dict]:
    """给设置窗口用：所有已登记设备（含当前不在线的）。"""
    cfg = tc.load_config()
    devs = _ensure(cfg)
    out = []
    for key, meta in sorted(devs.items(),
                            key=lambda kv: (int(kv[1].get("order", 0)), kv[0])):
        if not isinstance(meta, dict):
            continue
        if meta.get("deleted"):
            continue
        out.append({
            "key": key,
            "name": meta.get("name") or friendly_name(key, key),
            "show": bool(meta.get("show", True)),
            "tray": bool(meta.get("tray", True)),
            "order": int(meta.get("order", 0)),
            "kind": meta.get("kind") or infer_kind(key,
                                                   meta.get("name", "")),
        })
    return out


def set_flags(key: str, show: Optional[bool] = None,
              tray: Optional[bool] = None) -> None:
    cfg = tc.load_config()
    devs = _ensure(cfg)
    meta = devs.setdefault(key, {
        "name": friendly_name(key, key), **_meta_defaults(devs)})
    if show is not None:
        meta["show"] = bool(show)
    if tray is not None:
        meta["tray"] = bool(tray)
    tc.save_config(cfg)


def set_name(key: str, name: str) -> None:
    cfg = tc.load_config()
    devs = _ensure(cfg)
    devs.setdefault(key, {"show": True, "tray": True,
                          "order": _next_order(devs)})["name"] = name.strip()
    tc.save_config(cfg)


def set_kind(key: str, kind: str) -> None:
    if kind not in DEVICE_KINDS:
        raise ValueError("设备类型只能是 mouse 或 keyboard")
    cfg = tc.load_config()
    devs = _ensure(cfg)
    meta = devs.setdefault(key, {
        "name": friendly_name(key, key), "show": True, "tray": True,
        "order": _next_order(devs), "kind": infer_kind(key),
    })
    meta["kind"] = kind
    tc.save_config(cfg)


def delete_device(key: str) -> None:
    """从设置列表和面板/托盘中删除；扫描时不会自动恢复。"""
    cfg = tc.load_config()
    devs = _ensure(cfg)
    meta = devs.setdefault(key, {
        "name": friendly_name(key, key), "show": True, "tray": True,
        "order": _next_order(devs), "kind": infer_kind(key),
    })
    meta["deleted"] = True
    meta["show"] = False
    meta["tray"] = False
    tc.save_config(cfg)


def restore_deleted_devices() -> int:
    """清除删除标记，恢复被删设备；返回恢复数量。"""
    cfg = tc.load_config()
    devs = _ensure(cfg)
    count = 0
    for meta in devs.values():
        if isinstance(meta, dict) and meta.get("deleted"):
            meta.pop("deleted", None)
            meta["show"] = True
            meta["tray"] = True
            count += 1
    if count:
        tc.save_config(cfg)
    return count
