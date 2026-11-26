# -*- coding: utf-8 -*-
"""tools/download_models.py —— 下载 sherpa-onnx 中文识别模型。

只用标准库（urllib + threading），不依赖 requests，避免给运行环境加负担。

**多线程分段下载**：hf-mirror 单连接常被限到几十 KB/s，多连接可以叠加带宽
（实测 6 并发从 18 KB/s 提到 1.4 MB/s）。分片各自落到 ``.partN``，全部完成
后按顺序拼接到 ``.tmp``，校验大小无误才改名为正式文件——中途断掉不会留下
一个「看起来能用其实是半截」的模型。

用法：
    python tools/download_models.py               # 流式 + 整段都下
    python tools/download_models.py --stream      # 只下流式 paraformer
    python tools/download_models.py --offline     # 只下 SenseVoice
    python tools/download_models.py --force       # 已存在也重下
    python tools/download_models.py --jobs 8      # 并发连接数（默认 6）

模型落在 %APPDATA%\\ExtBatteryTray\\models\\ 下，与 Vosk 模型同级。
重复运行会跳过已完成的文件，并从未下完的字节处续传。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
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

UA = {"User-Agent": "WirelessHIDToolbox/1.21"}
MIN_PARALLEL = 8 << 20        # 小于 8MB 不值得开多线程
DEFAULT_JOBS = 6


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _head_size(url: str) -> int:
    """取远端文件大小；失败返回 0（调用方退化为单连接）。"""
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _fetch_range(url: str, start: int, end: int, dest: str,
                 progress: dict, key: str, stop: threading.Event) -> bool:
    """下载 [start, end] 区间到 dest（dest 已存在则续传尾部）。"""
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    want = end - start + 1
    if have >= want:
        progress[key] = have
        return True
    headers = dict(UA)
    headers["Range"] = "bytes=%d-%d" % (start + have, end)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp, \
                open(dest, "ab") as fh:
            while not stop.is_set():
                chunk = resp.read(1 << 15)
                if not chunk:
                    break
                fh.write(chunk)
                have += len(chunk)
                progress[key] = have
        return have >= want
    except Exception:
        return False


def _download_parallel(url: str, tmp: str, total: int, jobs: int) -> bool:
    """把 [已有字节, total) 切成 jobs 段并发下载，再顺序拼接进 tmp。"""
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if have >= total:
        return True
    rest = total - have
    if rest < MIN_PARALLEL:
        jobs = 1
    seg = rest // jobs
    ranges = []
    for i in range(jobs):
        start = have + i * seg
        end = start + seg - 1 if i < jobs - 1 else total - 1
        ranges.append((i, start, end))

    progress = {i: 0 for i in range(jobs)}
    # 分片文件名带上区间：用户改了 --jobs 再续传时，边界会变，
    # 若沿用旧的 .partN 会把不同区间的数据拼到一起，文件就废了
    parts = [tmp + ".part%d-%d" % (start, end) for _, start, end in ranges]
    stop = threading.Event()

    def reporter():
        last = -1
        while not stop.is_set():
            got = have + sum(progress.values())
            if got != last:
                pct = got * 100.0 / total
                sys.stdout.write("\r     %5.1f%%  %s / %s   " % (
                    pct, _human(got), _human(total)))
                sys.stdout.flush()
                last = got
            time.sleep(0.5)

    rep = threading.Thread(target=reporter, daemon=True)
    rep.start()

    threads = []
    for (i, start, end), part in zip(ranges, parts):
        t = threading.Thread(
            target=_fetch_range,
            args=(url, start, end, part, progress, i, stop),
            daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    stop.set()
    rep.join(timeout=1.0)
    sys.stdout.write("\r" + " " * 72 + "\r")

    ok = all(progress[i] >= (end - start + 1)
             for i, start, end in ranges)
    if not ok:
        sys.stdout.write("     部分分片未完成，可重跑续传\n")
        return False

    try:
        with open(tmp, "ab") as out:
            for part in parts:
                with open(part, "rb") as fh:
                    while True:
                        buf = fh.read(1 << 20)
                        if not buf:
                            break
                        out.write(buf)
        for part in parts:
            os.remove(part)
    except OSError as exc:
        print("     拼接失败：%s" % exc)
        return False
    return os.path.getsize(tmp) >= total


def _download(url: str, dest: str, expect: int = 0, jobs: int = DEFAULT_JOBS) -> bool:
    """下载到 dest.tmp，成功后改名。避免半截文件被误当成可用模型。"""
    tmp = dest + ".tmp"
    total = expect or _head_size(url)
    print(f"  -> {os.path.basename(dest)} ({_human(total)})")
    t0 = time.time()

    ok = _download_parallel(url, tmp, total, jobs)
    if not ok:
        if os.path.exists(tmp):
            print("     失败：已下载 %s，重跑本脚本可续传"
                  % _human(os.path.getsize(tmp)))
        return False

    size = os.path.getsize(tmp)
    if total and size < total * 0.98:
        print("     ✗ 大小不符：%s / 预期 %s" % (_human(size), _human(total)))
        return False
    os.replace(tmp, dest)
    dt = max(time.time() - t0, 1e-6)
    print("     ✓ 完成 %s（%s/s）" % (_human(size), _human(size / dt)))
    return True


def fetch(repo: str, files, subdir: str, force: bool = False,
          jobs: int = DEFAULT_JOBS) -> bool:
    target = os.path.join(ROOT, subdir)
    os.makedirs(target, exist_ok=True)
    print(f"[{subdir}]")
    ok = True
    for name, size in files:
        dest = os.path.join(target, name)
        if (not force and os.path.exists(dest)
                and os.path.getsize(dest) == size):
            print(f"  = {name} 已存在，跳过")
            continue
        if not _download(f"{MIRROR}/{repo}/resolve/main/{name}",
                         dest, size, jobs):
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 sherpa-onnx 中文识别模型")
    ap.add_argument("--stream", action="store_true", help="只下载流式 paraformer")
    ap.add_argument("--offline", action="store_true", help="只下载 SenseVoice 整段模型")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help="并发连接数（默认 6；单连接被限速时很有用）")
    args = ap.parse_args()

    want_stream = args.stream or not (args.stream or args.offline)
    want_offline = args.offline or not (args.stream or args.offline)

    print(f"模型目录：{ROOT}")
    print(f"并发连接：{args.jobs}\n")
    ok = True
    if want_stream:
        ok &= fetch(STREAM_REPO, STREAM_FILES, STREAM_REPO, args.force, args.jobs)
        print()
    if want_offline:
        ok &= fetch(OFFLINE_REPO, OFFLINE_FILES, OFFLINE_REPO, args.force, args.jobs)
        print()

    print("全部就绪 ✓" if ok else "有文件未下载成功 ✗，可重跑本脚本续传")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
