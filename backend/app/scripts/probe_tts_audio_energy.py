"""批次音频的本地能量剖面分析（离线、零成本；作为客观层第二步长期留存）。

为什么需要它：ASR 逐字只能回答"标签文字有没有被念出来"，回答不了"时长放大是
怎么来的"。§20.2 的 3.1 结论靠的就是这条区分——字数不变而发声块变长＝被放慢，
出现额外发声块＝插入的事件（或被朗读出口的东西）。富语言类标签（[sighing]、
[gasp]、[laughing]）的"真发声"与"念出标签词"在总时长上长得一模一样，只有段结构
能分开：真发声会在句界处多出一段独立短发声块，念字则把整句推后。

口径与 docs/TTS_PROMPT_EVIDENCE_20261010.md §20.3 一致，逐字照抄以免跨批漂移：
20 ms 帧 RMS、阈值取峰值 − 35 dB、连续 ≥3 帧成段、段间隔 ≥120 ms 记一次停顿。

但这条阈值是**按每条自身峰值**定的，等于逐条归一，所以它量不到"整体更响/更轻"
（§23.6：`[shouting]` 发声量倒数第四却靠 +2.2 dB 响度拿到人耳强档，`[whispers]`
和 `[asmr]` 把音量压低 9–10 dB、人耳反而判无/弱）。因此本脚本同时输出**绝对口径**
的 `peak_db`（dBFS，相对满量程）与 `voiced_rms_dbfs`（发声段帧 RMS 的均值转 dBFS），
这两列可跨条、跨批直接相减，配合 `--baseline` 会打印相对基线的 Δ 响度。

用法（backend/ 下）：
    python -m app.scripts.probe_tts_audio_energy --probe-dir backend/data/tts_debug/b4_qwen31_tag_scan
    python -m app.scripts.probe_tts_audio_energy --probe-dir ... --keys t08_like_dracula,p05_laughing
    python -m app.scripts.probe_tts_audio_energy --probe-dir ... --baseline backend/data/tts_debug/b3_qwen31_writing/q4_qwen31_baseline.wav
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

FRAME_MS = 20
THRESHOLD_BELOW_PEAK_DB = 35.0
MIN_FRAME_RUN = 3
MIN_GAP_MS = 120


def _read_frames(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    """返回 (逐帧 RMS 的 dBFS 数组, 逐帧 RMS 的线性数组, 帧长 ms)。"""
    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        rate = audio.getframerate()
        frames = audio.readframes(audio.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32, 8: np.int64}[sample_width]
    data = np.frombuffer(frames, dtype=dtype).astype(np.float64)
    if sample_width == 1:
        data -= 128.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    data /= float(2 ** (8 * sample_width - 1))
    frame_samples = max(1, int(rate * FRAME_MS / 1000))
    usable = (len(data) // frame_samples) * frame_samples
    if usable == 0:
        empty = np.array([], dtype=float)
        return empty, empty, float(FRAME_MS)
    rms = np.sqrt((data[:usable].reshape(-1, frame_samples) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    return db, rms, float(FRAME_MS)


def _segments(db: np.ndarray, frame_ms: float) -> Dict[str, Any]:
    if db.size == 0:
        return {"peak_db": None, "threshold_db": None, "segments": [], "gaps": []}
    threshold = float(db.max()) - THRESHOLD_BELOW_PEAK_DB
    above = db >= threshold
    runs: List[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(above):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            if index - start >= MIN_FRAME_RUN:
                runs.append((start, index))
            start = None
    if start is not None and len(above) - start >= MIN_FRAME_RUN:
        runs.append((start, len(above)))

    merged: List[tuple[int, int]] = []
    gaps: List[int] = []
    for run_start, run_end in runs:
        if merged and (run_start - merged[-1][1]) * frame_ms < MIN_GAP_MS:
            merged[-1] = (merged[-1][0], run_end)
            continue
        if merged:
            gaps.append(round((run_start - merged[-1][1]) * frame_ms))
        merged.append((run_start, run_end))

    segments = [
        {
            "start_ms": round(begin * frame_ms),
            "duration_ms": round((end - begin) * frame_ms),
        }
        for begin, end in merged
    ]
    return {
        "peak_db": round(float(db.max()), 2),
        "threshold_db": round(threshold, 2),
        "segments": segments,
        "gaps": gaps,
    }


def _analyze(path: Path) -> Optional[Dict[str, Any]]:
    db, rms, frame_ms = _read_frames(path)
    profile = _segments(db, frame_ms)
    if profile["peak_db"] is None:
        return None
    voiced = sum(segment["duration_ms"] for segment in profile["segments"])
    total_ms = round(db.size * frame_ms)
    above = db >= profile["threshold_db"]
    voiced_rms_dbfs = (
        round(float(20 * np.log10(max(float(rms[above].mean()), 1e-9))), 2)
        if above.any()
        else None
    )
    return {
        "audio": path.name,
        "total_ms": total_ms,
        "voiced_ms": voiced,
        "voiced_ratio": round(voiced / total_ms, 4) if total_ms else 0.0,
        "silence_ms": total_ms - voiced,
        "segment_count": len(profile["segments"]),
        "segment_durations_ms": [segment["duration_ms"] for segment in profile["segments"]],
        "segment_starts_ms": [segment["start_ms"] for segment in profile["segments"]],
        "pause_gaps_ms": profile["gaps"],
        **{key: profile[key] for key in ("peak_db", "threshold_db")},
        "voiced_rms_dbfs": voiced_rms_dbfs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-dir", required=True, help="批次目录（内含 *.wav 与 manifest.json）")
    parser.add_argument("--keys", default="", help="只分析这些 key（逗号分隔），默认全批")
    parser.add_argument("--baseline", default="", help="额外分析一条基线 wav（对照用）")
    args = parser.parse_args()

    root = Path(args.probe_dir)
    project_root = Path(__file__).resolve().parents[3]
    if not root.is_absolute():
        root = project_root / args.probe_dir
    root = root.resolve()
    wanted = {k.strip() for k in args.keys.split(",") if k.strip()}

    targets = [path for path in sorted(root.glob("*.wav")) if not wanted or path.stem in wanted]
    if args.baseline:
        baseline = Path(args.baseline)
        if not baseline.is_absolute():
            baseline = project_root / baseline
        baseline = baseline.resolve()
        if baseline.is_file():
            targets.append(baseline)
        else:
            print(f"[warn] 基线不存在：{baseline}")
    if not targets:
        print(f"没有 wav：{root}")
        return 1

    out_dir = root / "energy"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for path in targets:
        entry = _analyze(path)
        if entry is None:
            print(f"[skip] {path.name} 无有效帧")
            continue
        rows.append(entry)
        (out_dir / f"{path.stem}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    base_key = Path(args.baseline).stem if args.baseline else ""
    base = next((e for e in rows if Path(e["audio"]).stem == base_key), None)
    print(
        f"{'key':<30}{'total':>7}{'voiced':>8}{'ratio':>7}{'seg':>5}{'dBFS':>9}{'ΔdB':>7}  "
        "段时长(ms) / 停顿(ms)"
    )
    for e in rows:
        stem = Path(e["audio"]).stem
        dbfs = e["voiced_rms_dbfs"]
        delta = (
            round(dbfs - base["voiced_rms_dbfs"], 2)
            if dbfs is not None and base and base["voiced_rms_dbfs"] is not None and stem != base_key
            else None
        )
        print(
            f"{stem:<30}{e['total_ms']:>7}{e['voiced_ms']:>8}"
            f"{e['voiced_ratio']:>7}{e['segment_count']:>5}"
            f"{'' if dbfs is None else dbfs:>9}{'' if delta is None else delta:>7}  "
            f"{e['segment_durations_ms']} / {e['pause_gaps_ms']}"
        )
    if base and base_key:
        print(f"\nΔdB 基准：{base_key} 的 voiced_rms_dbfs = {base['voiced_rms_dbfs']}")
    print(f"产物目录: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
