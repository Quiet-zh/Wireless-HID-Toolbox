# -*- coding: utf-8 -*-
"""tools/download_models.py —— 下载 sherpa-onnx 中文识别模型。

只用标准库（urllib），不依赖 requests，避免给运行环境加负担。

用法：
    python tools/download_models.py               # 下载全部（流式 + 整段）
    python tools/download_models.py --stream      # 只下载流式 paraformer
    python tools/download_models.py --offline     # 只下载 SenseVoice
    python tools/download_models.py --force       # 已存在也重下

模型落在 %APPDATA%\\ExtBatteryTray\\models\\ 下，与 Vosk 模型同级。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

MIRROR = "https://hf-mirror.com/csukuangfj"
OFFICIAL = "https://huggingface.co/csukuangfj"

ROOT = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"),
    "ExtBatteryTray",
    "models",
)

# (模型仓库, 相对路径, 落地子目录)
STREAM_REPO = "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
OFFLINE_REPO = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

STREAM_FILES = [
    ("encoder.int8.onnx", 165462184),
    ("decoder.int8.onnx", 71664561),
    ("tokens.txt", 75756),
]

OFFLINE_FILES = [
    ("model.int8.onnx", 239233841),
    ("tokens.txt", 315894),
]


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _download(url: str, dest: str, expect: int = 0) -> bool:
    """下载到 dest.tmp，成功后改名。避免半截文件被误当成可用模型。"""
    tmp = dest + ".tmp"
    print(f"  -> {os.path.basename(dest)} ({_human(expect)})")
    req = urllib.request.Request(url, headers={"User-Agent": "WirelessHIDToolbox"})
    t0 = time.time()
    got = 0
    last = 0.0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or expect or 0)
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - last >= 1.0 and total:
                    pct = got * 100.0 / total
                    speed = got / max(now - t0, 1e-6)
                    sys.stdout.write(
                        f"\r     {pct:5.1f}%  {_human(got)}/{_human(total)}  "
                        f"{_human(speed)}/s   "
                    )
                    sys.stdout.flush()
                    last = now
        sys.stdout.write("\r" + " " * 66 + "\r")
        if expect and got < expect * 0.98:
            print(f"     ✗ 大小不符：{_human(got)} / 预期 {_human(expect)}")
            os.remove(tmp)
            return False
        os.replace(tmp, dest)
        print(f"     ✓ 完成 {_human(got)}")
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"\n     ✗ 失败：{exc}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def fetch(repo: str, files, subdir: str, force: bool = False) -> bool:
    target = os.path.join(ROOT, subdir)
    os.makedirs(target, exist_ok=True)
    print(f"[{subdir}]")
    ok = True
    for name, size in files:
        dest = os.path.join(target, name)
        if not force and os.path.exists(dest) and os.path.getsize(dest) == size:
            print(f"  = {name} 已存在，跳过")
            continue
        if not _download(f"{MIRROR}/{repo}/resolve/main/{name}", dest, size):
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 sherpa-onnx 中文识别模型")
    ap.add_argument("--stream", action="store_true", help="只下载流式 paraformer")
    ap.add_argument("--offline", action="store_true", help="只下载 SenseVoice 整段模型")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()

    want_stream = args.stream or not (args.stream or args.offline)
    want_offline = args.offline or not (args.stream or args.offline)

    print(f"模型目录：{ROOT}\n")
    ok = True
    if want_stream:
        ok &= fetch(STREAM_REPO, STREAM_FILES, STREAM_REPO, args.force)
        print()
    if want_offline:
        ok &= fetch(OFFLINE_REPO, OFFLINE_FILES, OFFLINE_REPO, args.force)
        print()

    print("全部就绪 ✓" if ok else "有文件未下载成功 ✗，可重跑本脚本续传")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
