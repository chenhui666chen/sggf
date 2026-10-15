"""批次音频的逐字转写驱动器（付费；作为写法测评客观层入口长期留存，不随任务清理）。

客观层里"正文标签有没有被朗读出口"只能由 ASR 逐字判定（时长只能证明被采纳，
不能证明没被念出来），而每一批提示词写法测评都要用这一步。此前它是一次性脚本、
按清理条款删除后每批都得重写，因此升格为留存脚本，与 probe_tts_gate_scoring.py 对称：
两者都只吃批次目录里的 manifest，产物落在同一目录内。

判据口径（与 docs/TTS_PROMPT_EVIDENCE_20261010.md §20 一致）：
- expected 取 manifest 的 `spoken_text`（干净台词）。正文带标签的条目必须显式带该字段，
  否则相似度会把标签当成漏字；缺字段直接报错，不猜。
- 相似度低于门槛时先看"转写所需朗读时长 vs 实测发声时长"：只有物理上装不下那段重复
  才折叠 ASR 整句重复幻觉（新 ASR 已实测会整句复读并假拒合格音频）。
- `tag_words_in_transcript` 只在转写里出现**完整标签词组**时置真，用于批量侦测
  "标签被朗读出口"；转写成同音汉字时该位不置真，仍需逐条看 transcript。

用法（backend/ 下）：
    python -m app.scripts.probe_tts_batch_asr --probe-dir backend/data/tts_debug/b4_qwen31_tag_scan
    python -m app.scripts.probe_tts_batch_asr --probe-dir backend/data/tts_debug/b4_qwen31_tag_scan --confirm-paid
    python -m app.scripts.probe_tts_batch_asr --probe-dir ... --keys t01_amazed,t03_trembling --confirm-paid
    python -m app.scripts.probe_tts_batch_asr --probe-dir ... --confirm-paid --force   # 重转写已存在的条目
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrap_environment() -> tuple[Path, Path]:
    backend_root = Path(__file__).resolve().parents[2]
    project_root = backend_root.parent
    for path in (backend_root, project_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from app.core.env_loader import load_project_env

    load_project_env(override=False)
    return project_root, backend_root


PROJECT_ROOT, BACKEND_ROOT = _bootstrap_environment()

from app.services.audiobook.prompt_audio_asr_provider import (  # noqa: E402
    PromptAudioAsrProviderError,
    create_prompt_audio_asr_provider,
)
from app.services.audiobook.tts_output_validator import validate_tts_audio  # noqa: E402
from app.services.audiobook.voice_profile_tagging import (  # noqa: E402
    fold_suspected_asr_repeat,
    transcript_similarity,
)

DEFAULT_PROBE_DIR = PROJECT_ROOT / "backend/data/tts_debug/b4_qwen31_tag_scan"
DEFAULT_ASR_PROVIDER = "qwen_audio_asr_flash"
# 逐字转写门槛，与 tag_voice_profiles 的画像门禁同值，避免两处口径漂移。
MIN_TRANSCRIPT_SIMILARITY = 0.90

_TAG_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


def _tag_words_from_input(input_text: str) -> List[str]:
    """抽出正文里所有 `[...]` 标签内的词组（去重、保序），用于批量侦测标签泄漏。"""
    seen: List[str] = []
    for match in _TAG_TOKEN_RE.finditer(input_text or ""):
        token = match.group(1).strip().casefold()
        if token and token not in seen:
            seen.append(token)
    return seen


def _tag_leaked_into_transcript(tags: List[str], transcript: str) -> bool:
    """转写（压掉空白、忽略大小写）里是否整段出现了标签词组。"""
    if not tags:
        return False
    haystack = re.sub(r"\s+", "", str(transcript or "")).casefold()
    return any(re.sub(r"\s+", "", tag) in haystack for tag in tags)


def _targets_from_manifest(
    manifest: Path, wanted: Optional[set], out_dir: Path, force: bool
) -> List[Dict[str, Any]]:
    if not manifest.exists():
        raise SystemExit(f"manifest 不存在：{manifest}（先用 probe_tts_capability_gates 跑批次）")
    targets: List[Dict[str, Any]] = []
    for row in json.loads(manifest.read_text(encoding="utf-8")):
        key = str(row.get("key") or "")
        if not key or (wanted and key not in wanted):
            continue
        if int(row.get("http_status") or 0) != 200 or not row.get("audio_file"):
            continue
        audio = PROJECT_ROOT / str(row["audio_file"])
        if not audio.is_file():
            print(f"[skip] {key} 音频文件不存在：{audio}")
            continue
        expected = str(row.get("spoken_text") or "")
        if not expected:
            print(f"[skip] {key} manifest 缺 spoken_text，无法做逐字对照（不能拿带标签的 text 当台词）")
            continue
        if not force and (out_dir / f"{key}.json").exists():
            continue
        targets.append({"key": key, "audio": audio, "expected": expected, "row": row})
    return targets


def _transcribe_one(target: Dict[str, Any], provider: Any, batch: str) -> Dict[str, Any]:
    audio: Path = target["audio"]
    row = target["row"]
    expected = target["expected"]
    payload_input = (row.get("payload") or {}).get("input") or {}
    started = time.perf_counter()
    provider_name = DEFAULT_ASR_PROVIDER
    try:
        result = provider.transcribe(str(audio))
    except PromptAudioAsrProviderError as exc:
        error: Optional[str] = f"asr_failed:{exc.code}"
        transcript = ""
    except Exception as exc:  # noqa: BLE001
        error = f"asr_error:{type(exc).__name__}"
        transcript = ""
    else:
        error = None
        transcript = str(result.transcript or "")
        provider_name = str(result.provider or DEFAULT_ASR_PROVIDER)
    similarity_raw = (
        round(transcript_similarity(expected=expected, transcript=transcript), 4) if transcript else 0.0
    )
    similarity = similarity_raw
    repeat_suspect = False
    if transcript and similarity_raw < MIN_TRANSCRIPT_SIMILARITY:
        audio_bytes = audio.read_bytes()
        check = validate_tts_audio(audio_bytes, expected)
        voiced_ms = float(check.duration_ms or 0) * (1 - float(check.silence_ratio or 0))
        fold = fold_suspected_asr_repeat(
            expected=expected, transcript=transcript, voiced_duration_ms=voiced_ms
        )
        if fold is not None and fold.similarity >= similarity_raw:
            similarity = round(fold.similarity, 4)
            repeat_suspect = True
            if not error:
                error = "asr_repeat_suspect"
    tags = _tag_words_from_input(str(payload_input.get("text") or ""))
    return {
        "key": target["key"],
        "batch": batch,
        "audio": str(audio.relative_to(BACKEND_ROOT)),
        "duration_ms": row.get("duration_ms"),
        "expected_text": expected,
        "input_text": payload_input.get("text"),
        "input_instruction": payload_input.get("instruction"),
        "asr_provider": provider_name,
        "asr_ms": round((time.perf_counter() - started) * 1000),
        "transcript": transcript,
        "similarity": similarity,
        "similarity_raw": similarity_raw,
        "asr_repeat_suspect": repeat_suspect,
        "tag_words_in_transcript": _tag_leaked_into_transcript(tags, transcript),
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-dir", default=str(DEFAULT_PROBE_DIR), help="批次目录（含 manifest.json）")
    parser.add_argument("--manifest", default="", help="覆盖 manifest 路径，默认 <probe-dir>/manifest.json")
    parser.add_argument("--keys", default="", help="只转写这些 key（逗号分隔），默认全批")
    parser.add_argument("--provider", default=DEFAULT_ASR_PROVIDER, help="ASR provider 名")
    parser.add_argument("--force", action="store_true", help="重转写 asr/ 下已存在的条目")
    parser.add_argument("--confirm-paid", action="store_true", help="真实发出转写请求（会扣费）")
    args = parser.parse_args()

    probe_dir = Path(args.probe_dir)
    if not probe_dir.is_absolute():
        probe_dir = PROJECT_ROOT / probe_dir
    manifest = Path(args.manifest) if args.manifest else probe_dir / "manifest.json"
    if args.manifest and not manifest.is_absolute():
        manifest = PROJECT_ROOT / manifest
    out_dir = probe_dir / "asr"
    wanted = {k.strip() for k in args.keys.split(",") if k.strip()} or None

    targets = _targets_from_manifest(manifest, wanted, out_dir, args.force)
    print(f"批次目录：{probe_dir.relative_to(PROJECT_ROOT)}")
    print(f"待转写 {len(targets)} 条（已存在且不 --force 的条目不计入）")
    for target in targets:
        print(f"  {target['key']:<28} {target['audio'].name}")
    if not targets:
        return 0
    if not args.confirm_paid:
        print("\nDRY-RUN：未发出任何网络请求。确认后加 --confirm-paid 执行。")
        return 0

    provider = create_prompt_audio_asr_provider(args.provider)
    if provider is None:
        raise SystemExit(f"ASR provider 未配置或不可用：{args.provider}")

    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for target in targets:
        entry = _transcribe_one(target, provider, probe_dir.name)
        path = out_dir / f"{entry['key']}.json"
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(entry)
        print(
            f"{entry['key']:<28} sim={entry['similarity']:<7} "
            f"ms={str(entry['duration_ms']):<7} leak={int(entry['tag_words_in_transcript'])}  {entry['transcript'][:40]}"
        )

    print(
        f"\n{'key':<28} {'sim':>6} {'raw':>6} {'ms':>7} {'leak':>5}  error"
    )
    for e in rows:
        print(
            f"{e['key']:<28} {e['similarity']:>6} {e['similarity_raw']:>6} "
            f"{str(e['duration_ms'] or '-'):>7} {int(e['tag_words_in_transcript']):>5}  {e['error'] or ''}"
        )
    print(f"\nasr 目录: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
