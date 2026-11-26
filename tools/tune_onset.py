# -*- coding: utf-8 -*-
"""tools/tune_onset.py —— 调前导静音门控参数（阈值 / 底噪倍数）。

**为什么用真实录音而不是单条派生**：手头若只有一条录音，直接调到最优必然
过拟合（阈值恰好卡在它那段底噪上）。这里优先用语音窗口保存目录里的全部
真实录音；没有录音时才退化为从 Frida 抓包派生变体。

**标注怎么来**：用 SenseVoice（实测中文最准）对裁过静音的整段音频识别一次
作为「伪真值」，再用流式引擎在不同门控参数下的结果算字错率。基准本身有
少量错误，但用来**横向比较参数**足够。

用法：
    python tools/tune_onset.py                  # 用 %APPDATA% 下的真实录音
    python tools/tune_onset.py --wav-dir D:\\x    # 指定目录
    python tools/tune_onset.py --quick          # 小网格
    python tools/tune_onset.py --engine vosk    # 换引擎
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import os
import random
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aimouse_voice as av  # noqa: E402

ROOT = os.path.join(os.environ.get("APPDATA") or "", "ExtBatteryTray", "models")
VOICE_DIR = os.path.join(os.environ.get("APPDATA") or "", "ExtBatteryTray", "voice")
CAPTURE = os.path.join(
    os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp",
    "frida_record.jsonl")

PUNCT = "。，、！？；：,.!?;: "


def norm(text: str) -> str:
    for ch in PUNCT:
        text = text.replace(ch, "")
    return text.strip()


def edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(text: str, truth: str) -> float:
    got, ref = norm(text or ""), norm(truth or "")
    if not ref:
        return 0.0 if not got else 1.0
    return edit_distance(got, ref) / len(ref)


def read_wav(path):
    with wave.open(path, "rb") as fh:
        n, rate = fh.getnframes(), fh.getframerate()
        raw = fh.readframes(n)
    samples = av.pcm16_to_samples(raw)
    if rate != av.SAMPLE_RATE:
        pcm = av.samples_to_pcm16(samples)
        samples = av.pcm16_to_samples(
            _resample_simple(pcm, rate, av.SAMPLE_RATE))
    return samples


def _resample_simple(pcm, src, dst):
    samples = av.pcm16_to_samples(pcm)
    if not samples or src == dst:
        return pcm
    ratio = dst / float(src)
    out = []
    last = len(samples) - 1
    for i in range(int(len(samples) * ratio)):
        pos = i / ratio
        left = int(pos)
        if left >= last:
            out.append(samples[last])
            continue
        frac = pos - left
        out.append(int(samples[left] + (samples[left + 1] - samples[left]) * frac))
    return av.samples_to_pcm16(out)


def load_real_recordings(wav_dir):
    """读真实录音；跳过空文件与过短的。"""
    items = []
    for path in sorted(glob.glob(os.path.join(wav_dir, "*.wav"))):
        try:
            samples = read_wav(path)
        except Exception:
            continue
        if len(samples) < av.SAMPLE_RATE * 0.3:
            continue
        items.append((os.path.basename(path), samples))
    return items


def load_frame_capture(path):
    """退化路径：从抓包派生多场景变体。"""
    frames = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                raw = bytes.fromhex(rec.get("hex") or "")
            except (ValueError, TypeError):
                continue
            if len(raw) == av.FRAME_SIZE and raw[0] == av.FRAME_ID:
                frames.append(raw)
    base = av.decode_frames_local(frames)
    if not base:
        return []

    def silence(ms, amp):
        n = int(av.SAMPLE_RATE * ms / 1000)
        rnd = random.Random(7)
        return [max(-32768, min(32767,
                                (amp if i % 2 else -amp)
                                + rnd.randint(-amp // 3, amp // 3)))
                for i in range(n)]

    rnd = random.Random(11)
    return [
        ("原始", base),
        ("静音×2", silence(1500, 400) + base),
        ("静音÷2", base[int(av.SAMPLE_RATE * 0.7):]),
        ("无静音", base[int(av.SAMPLE_RATE * 1.55):]),
        ("高底噪", silence(1400, 1500) + base),
        ("小声", [int(s * 0.45) for s in base]),
        ("叠噪", [max(-32768, min(32767, s + rnd.randint(-900, 900)))
                  for s in base]),
    ]


class Runner:
    def __init__(self, engine):
        self.engine = engine
        self._eng = None
        self._off = None

    def load(self):
        if self.engine == "sherpa":
            import aimouse_sherpa_asr as sasr
            self._eng = sasr.SherpaAsrEngine(ROOT)
            if not self._eng.stream_ready():
                raise SystemExit("未找到 sherpa 流式模型")
            self._off = self._eng
            self._off.preload()
        else:
            import aimouse_voice_panel as vp
            self._eng = vp.AsrEngine(os.path.join(ROOT, "vosk-model-small-cn-0.22"))
            if not self._eng.available():
                raise SystemExit("Vosk 不可用")
            self._eng.preload()
        return self

    def truth(self, samples):
        """SenseVoice 裁静音后识别，作为伪真值。"""
        if self._off is not None and getattr(self._off, "offline_ready", lambda: False)():
            return self._off.transcribe_samples(samples) or ""
        return ""

    def stream(self, samples, threshold, floor_factor):
        """走引擎自己的门控（不要在外面再套一层，否则会双重裁剪）。"""
        if threshold > 0:
            self._eng.onset_kwargs = {"threshold": threshold}
        else:
            self._eng.onset_kwargs = {"floor_factor": floor_factor}
        if not self._eng.begin():
            return "", 0.0
        gate = getattr(self._eng, "_gate", None)
        chunk = av.SAMPLES_PER_FRAME
        for i in range(0, len(samples), chunk):
            self._eng.feed(av.samples_to_pcm16(samples[i:i + chunk]))
        text = self._eng.finish()
        return text, (gate.dropped_sec if gate is not None else 0.0)


def main() -> int:
    ap = argparse.ArgumentParser(description="调前导静音门控参数")
    ap.add_argument("--wav-dir", default=VOICE_DIR)
    ap.add_argument("--engine", default="sherpa", choices=["sherpa", "vosk"])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只用前 N 条")
    args = ap.parse_args()

    items = load_real_recordings(args.wav_dir)
    source = "真实录音"
    if not items:
        items = load_frame_capture(CAPTURE)
        source = "抓包派生"
    if not items:
        print("没有可用音频：既没有录音，也没有抓包文件")
        return 1
    if args.limit:
        items = items[:args.limit]
    print(f"数据源：{source}，共 {len(items)} 条")

    runner = Runner(args.engine).load()
    print("模型加载完成，生成伪真值…")
    t0 = time.perf_counter()
    truths = {}
    for name, samples in items:
        truths[name] = runner.truth(samples)
    print(f"伪真值 {len(truths)} 条（{time.perf_counter() - t0:.1f}s）\n")

    if args.quick:
        combos = [(0, 3.0), (0, 4.5), (0, 6.0), (3000, 4.5)]
    else:
        combos = [(0, f) for f in (2.0, 3.0, 3.5, 4.5, 5.5, 6.5, 8.0)]
        combos += [(t, 4.5) for t in (600, 1000, 1500, 2500, 3000, 4000)]

    rows = []
    for idx, (th, factor) in enumerate(combos, 1):
        errs, dropped, empty = [], [], 0
        for name, samples in items:
            text, drop = runner.stream(samples, th, factor)
            errs.append(cer(text, truths[name]))
            dropped.append(drop)
            if not norm(text):
                empty += 1
        mean = sum(errs) / len(errs)
        rows.append((mean, max(errs), th, factor,
                     sum(dropped) / len(dropped), empty))
        sys.stdout.write("\r  %d/%d  %s" % (idx, len(combos), " " * 40))
        sys.stdout.flush()
    print("\n")

    rows.sort(key=lambda r: (r[0], r[1]))
    print("=" * 78)
    print("%-8s %-8s %-9s %-9s %-9s %s" % (
        "固定阈值", "底噪倍数", "平均CER", "最差CER", "平均裁掉", "空结果"))
    print("-" * 78)
    for mean, worst, th, factor, drop, empty in rows:
        label = str(th) if th > 0 else "自适应"
        print("%-8s %-8.1f %-9.3f %-9.3f %-9.2fs %d" % (
            label, factor, mean, worst, drop, empty))
    best = rows[0]
    print("\n最优：固定阈值=%s 底噪倍数=%.1f 平均CER=%.3f" % (
        best[2] if best[2] > 0 else "自适应", best[3], best[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
