# -*- coding: utf-8 -*-
"""last_state.py —— 记住每台设备最后一次成功读到的电量。

设备休眠 / 暂时读不到时，面板和托盘显示“上次电量 + 上次更新时间”，
而不是直接变成 --。数据放在 %APPDATA%\\ExtBatteryTray\\last_<key>.json，
不写日志，不落设备隐私数据。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _app_dir() -> str:
    root = os.environ.get("APPDATA") or BASE_DIR
    path = os.path.join(root, "ExtBatteryTray")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = BASE_DIR
    return path


APP_DIR = _app_dir()


def _path(key: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key)
    return os.path.join(APP_DIR, f"last_{safe}.json")


def save(key: str, percent: int, detail: str = "") -> None:
    data = {
        "percent": max(0, min(100, int(percent))),
        "ts": time.time(),
        "detail": detail,
    }
    try:
        fd, tmp = tempfile.mkstemp(prefix="last_", suffix=".tmp", dir=APP_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _path(key))
    except OSError:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def get(key: str) -> dict | None:
    try:
        with open(_path(key), "r", encoding="utf-8") as f:
            data = json.load(f)
        percent = int(data.get("percent"))
        ts = float(data.get("ts", 0))
        if 0 <= percent <= 100 and ts > 0:
            return {"percent": percent, "ts": ts,
                    "detail": str(data.get("detail", ""))}
    except Exception:
        pass
    return None


TRANSIENT_ERRORS = ("休眠", "超时", "没有响应", "未连接")


def fallback(key: str, error: str) -> dict | None:
    """只在“休眠/超时/没响应”这类临时状态下回退到上次电量。"""
    if any(token in (error or "") for token in TRANSIENT_ERRORS):
        return get(key)
    return None


def stamp(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def age_text(ts: float) -> str:
    return f"上次更新 {stamp(ts)}"
