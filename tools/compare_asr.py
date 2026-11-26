# -*- coding: utf-8 -*-
"""tools/compare_asr.py —— 用真实设备录音对比 Vosk / sherpa-onnx 识别效果。

数据来源：Frida 抓到的 0xFF91 报文序列（默认 ``%TEMP%\\frida_record.jsonl``），
其中 33 字节、首字节 0x1B 的即为音频帧。用 :func:`aimouse_voice.decode_frames_local`
还原成 16k/16bit PCM，再分别交给各引擎识别。

用法：
    python tools/compare_asr.py                    # 用默认数据集，跑全部引擎
    python tools/compare_asr.py --jsonl xxx.jsonl  # 指定抓包文件
    python tools/compare_asr.py --only sherpa      # 只跑 sherpa
    python tools/compare_asr.py --wav out.wav      # 顺便导出还原后的 WAV

没有安装的引擎会跳过，不影响其余对比。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aimouse_voice as av  # noqa: E402

ROOT = os.path.join(os.environ.get("APPDATA") or "", "ExtBatteryTray", "models")
VOSK_SMALL = os.path.join(ROOT, "vosk-model-small-cn-0.22")
VOSK_BIG = os.path.join(ROOT, "vosk-model-cn-0.22")


def load_frames(path: str) -> list[bytes]:
    """从抓包文件里取出 0x1B 音频帧（33 字节）。"""
    frames: list[bytes] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            h = rec.get("hex") or ""
            if len(h) % 2:
                continue
            try:
                raw = bytes.fromhex(h)
            except ValueError:
                continue
            if len(raw) == av.FRAME_SIZE and raw[0] == av.FRAME_ID:
                frames.append(raw)
    return frames


def run_vosk(samples: list[int], model_dir: str, label: str) -> None:
    """走面板真实的 AsrEngine 路径（含前导静音裁剪），而不是直连 Kaldi。"""
    if not os.path.isdir(model_dir):
        print(f"[Vosk {label}] 模型目录不存在，跳过：{model_dir}")
        return
    import aimouse_voice_panel as vp
    eng = vp.AsrEngine(model_dir)
    if not eng.available():
        print(f"[Vosk {label}] 不可用（{eng.error}），跳过")
        return

    t0 = time.perf_counter()
    eng.preload()
    load_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    text = eng.transcribe_samples(samples) or ""
    used_ms = (time.perf_counter() - t0) * 1000
    dur = len(samples) / av.SAMPLE_RATE
    print(f"[Vosk {label}] 加载 {load_ms:.0f}ms  识别 {used_ms:.0f}ms  "
          f"RTF={used_ms / 1000 / max(dur, 1e-6):.3f}")
    print(f"  → {text or '（空）'}")


def run_sherpa_stream(frames: list[bytes], model_dir: str) -> None:
    """模拟真实录音：逐帧喂给流式引擎，最后取 finish 结果。"""
    try:
        import aimouse_sherpa_asr as sasr
    except Exception as exc:
        print(f"[sherpa 流式] 导入失败：{exc}")
        return
    eng = sasr.SherpaAsrEngine(model_dir)
    if not eng.stream_ready():
        print(f"[sherpa 流式] 未找到流式模型，跳过（{eng.stream_dir or model_dir}）")
        return

    t0 = time.perf_counter()
    eng.preload()
    load_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    if not eng.begin():
        print(f"[sherpa 流式] 启动失败：{eng.error}")
        return
    partials: list[str] = []
    decoder = av.LocalStreamDecoder()
    for idx, frame in enumerate(frames):
        pcm = av.samples_to_pcm16(decoder.feed(frame))
        eng.feed(pcm)
        if idx % 60 == 0:                     # 约每 0.2s 取一次中间结果
            p = eng.partial()
            if p and (not partials or p != partials[-1]):
                partials.append(p)
    text = eng.finish()
    used_ms = (time.perf_counter() - t0) * 1000
    dur = len(frames) * av.SAMPLES_PER_FRAME / av.SAMPLE_RATE
    print(f"[sherpa 流式] 加载 {load_ms:.0f}ms  识别 {used_ms:.0f}ms  "
          f"RTF={used_ms / 1000 / max(dur, 1e-6):.3f}")
    if partials:
        print(f"  中间结果：{' | '.join(partials[-4:])}")
    print(f"  → {text or '（空）'}")


def run_sherpa_offline(samples: list[int], model_dir: str) -> None:
    try:
        import aimouse_sherpa_asr as sasr
    except Exception as exc:
        print(f"[sherpa 整段] 导入失败：{exc}")
        return
    eng = sasr.SherpaAsrEngine(model_dir)
    if not eng.offline_ready():
        print(f"[sherpa 整段] 未找到 SenseVoice 模型，跳过（{eng.offline_dir or model_dir}）")
        return

    t0 = time.perf_counter()
    if not eng.preload_offline():
        print(f"[sherpa 整段] 模型加载失败：{eng.error}")
        return
    load_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    text = eng.transcribe_samples(samples) or ""
    used_ms = (time.perf_counter() - t0) * 1000
    dur = len(samples) / av.SAMPLE_RATE
    print(f"[sherpa 整段] 加载 {load_ms:.0f}ms  识别 {used_ms:.0f}ms  "
          f"RTF={used_ms / 1000 / max(dur, 1e-6):.3f}")
    print(f"  → {text or '（空）'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="对比 Vosk 与 sherpa-onnx 识别效果")
    ap.add_argument("--jsonl", default=os.path.join(
        os.environ.get("TEMP") or "/tmp", "frida_record.jsonl"))
    ap.add_argument("--wav", default="", help="把还原出的音频另存为 WAV")
    ap.add_argument("--only", default="", help="vosk / sherpa / sherpa-stream")
    args = ap.parse_args()

    if not os.path.isfile(args.jsonl):
        print(f"抓包文件不存在：{args.jsonl}")
        return 1
    frames = load_frames(args.jsonl)
    if not frames:
        print("未从抓包文件里找到 0x1B 音频帧")
        return 1

    samples = av.decode_frames_local(frames)
    dur = len(samples) / av.SAMPLE_RATE
    rms = (sum(v * v for v in samples) / max(len(samples), 1)) ** 0.5
    print(f"数据集：{len(frames)} 帧 / {len(samples)} 样本 / {dur:.2f}s / RMS={rms:.0f}\n")

    if args.wav:
        av.save_wav(args.wav, samples)
        print(f"已导出 WAV：{args.wav}\n")

    only = args.only.strip().lower()
    if not only or only == "vosk":
        run_vosk(samples, VOSK_SMALL, "小模型")
        run_vosk(samples, VOSK_BIG, "大模型")
        print()
    if not only or only == "sherpa-stream":
        run_sherpa_stream(frames, ROOT)
        print()
    if not only or only == "sherpa":
        run_sherpa_offline(samples, ROOT)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
