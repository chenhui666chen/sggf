"""音色画像自动打标：真实试听音频 → 客观层 → 双模型受控枚举打标 → 画像 JSON 落盘。

链路（每条音色）：
1. 取音频：本地缓存 → OSS 试听缓存 → 真实 TTS 合成并回传 OSS（与前端试听同一缓存键）；
2. 客观层：时长/静音/能量校验 + qwen-audio-3.1-asr-flash 逐字转写与试听文本比对；
3. 打标：豆包（主）与 qwen3.8-omni-flash（参考）各听一次，原始响应落盘以保幂等；
4. 落盘：shared/<目录名>_voice_profiles.json，标签只取主模型，参考结果进 reference 字段。

画像条目一律 review_status=candidate：模型产出不是已审核画像，高曝光/低置信度项留给人耳。

运行方式（在 backend/ 目录下）：
    python -m app.scripts.tag_voice_profiles --models mimo-v2.5-tts --limit-per-model 3 --dry-run
    python -m app.scripts.tag_voice_profiles --models mimo-v2.5-tts --confirm-paid
    python -m app.scripts.tag_voice_profiles --all --confirm-paid
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.env_loader import load_project_env  # noqa: E402

load_project_env(override=False)

import httpx  # noqa: E402

from app.schemas.voice_tags import TAXONOMY_VERSION  # noqa: E402
from app.services.audiobook.prompt_audio_asr_provider import (  # noqa: E402
    PromptAudioAsrProviderError,
    create_prompt_audio_asr_provider,
)
from app.services.audiobook.tts_model_ids import (  # noqa: E402
    get_audiobook_tts_model_metadata,
    list_supported_audiobook_tts_models,
)
from app.services.audiobook.tts_output_validator import validate_tts_audio  # noqa: E402
from app.services.audiobook.tts_preview_cache import (  # noqa: E402
    check_oss_preview_exists,
    upload_preview_to_oss,
)
from app.services.audiobook.voice_catalog import (  # noqa: E402
    _profile_filename_for_model,
    _resolve_voice_library_path,
    get_preview_quote_for_voice,
    load_voice_catalog_for_model,
)
from app.services.audiobook.voice_profile_tagging import (  # noqa: E402
    PRIMARY_SCORER,
    REFERENCE_SCORER,
    build_sidecar_document,
    fold_suspected_asr_repeat,
    profile_entry_from_judgements,
    tag_voice_profile,
    transcript_similarity,
)

# 试听音频与原始响应缓存目录：命中即跳过合成与付费调用。
DATA_DIR = PROJECT_ROOT / "backend" / "data" / "voice_profile_tagging"
AUDIO_DIR = DATA_DIR / "audio"
RAW_DIR = DATA_DIR / "raw"
SHARED_DIR = PROJECT_ROOT / "shared"

PREVIEW_VOLUME = 50
PREVIEW_SPEED = 1.0
# 逐字转写门槛：低于该相似度说明音频没读出这句话，听感标签不可信。
MIN_TRANSCRIPT_SIMILARITY = 0.90
# 批次合格线：ready 画像占比低于该值即判定"线不合格"，停止放量。
MIN_BATCH_READY_RATIO = 0.60


@dataclass(frozen=True)
class VoiceJob:
    model: str
    voice_id: str
    label: str
    preview_text: str
    cache_key: str
    profile_filename: str


def _iter_system_voice_models() -> List[str]:
    result: List[str] = []
    for model in list_supported_audiobook_tts_models():
        meta = get_audiobook_tts_model_metadata(model)
        capabilities = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
        if capabilities.get("has_system_voices", False):
            result.append(model)
    return result


def _build_preview_request(model: str, voice_id: str, text: str):
    from app.api.v1.audiobook_api import routes_tts
    from app.schemas.audiobook import TTSPreviewRequest

    request = TTSPreviewRequest(text=text, voice_id=voice_id, model=model, volume=PREVIEW_VOLUME)
    speaker_id = routes_tts._resolve_preview_speaker_id(request, model)
    return request, speaker_id, routes_tts._build_preview_voice_params(request, speaker_id)


def _preview_cache_key(model: str, voice_id: str, text: str) -> str:
    """复用线上试听接口的键推导，保证打标读到的就是前端听到的那条音频。"""
    from app.services.audiobook.tts_preview_cache import _build_preview_cache_key

    request, speaker_id, voice_params = _build_preview_request(model, voice_id, text)
    return _build_preview_cache_key(
        model=model,
        voice_id=speaker_id,
        text=request.text,
        volume=PREVIEW_VOLUME,
        speed=PREVIEW_SPEED,
        emotion=str(voice_params.get("emotion") or "neutral"),
        voice_type="",
        mimo_voice_asset_id="",
        stepaudio_voice_asset_id="",
        voice_params=voice_params,
    )


def _iter_jobs(models: Iterable[str], *, limit: int, skip_ready: bool) -> Tuple[List[VoiceJob], List[str]]:
    """展开待打标音色；共用同一画像文件的模型（minimax hd/turbo）按文件维度跳过已合格条目。"""
    ready_by_file = _ready_identity_by_file() if skip_ready else {}
    jobs: List[VoiceJob] = []
    notes: List[str] = []
    for model in models:
        try:
            catalog = load_voice_catalog_for_model(model)
        except Exception as exc:
            notes.append(f"{model}: 音色目录加载失败 {exc}")
            continue
        profile_filename = _profile_filename_for_model(model)
        selected = [
            voice
            for voice in (catalog.get("voices") or [])
            if str(voice.get("id") or voice.get("speaker") or "").strip()
        ]
        if skip_ready:
            ready = ready_by_file.get(profile_filename, set())
            before = len(selected)
            selected = [
                voice for voice in selected
                if f"{model}|{voice.get('id') or voice.get('speaker')}" not in ready
            ]
            if before != len(selected):
                notes.append(f"{model}: 跳过 {before - len(selected)} 条已合格画像")
        if limit > 0:
            selected = selected[:limit]
        for voice in selected:
            voice_id = str(voice.get("id") or voice.get("speaker")).strip()
            text = get_preview_quote_for_voice(model, voice_id)
            jobs.append(
                VoiceJob(
                    model=model,
                    voice_id=voice_id,
                    label=str(voice.get("label") or voice_id),
                    preview_text=text,
                    cache_key=_preview_cache_key(model, voice_id, text),
                    profile_filename=profile_filename,
                )
            )
    return jobs, notes


def _ready_identity_by_file() -> Dict[str, set]:
    """已有 ready 且同词表版本的画像条目，按画像文件分组，供幂等跳过。"""
    filenames = {_profile_filename_for_model(model) for model in _iter_system_voice_models()}
    grouped: Dict[str, set] = {}
    for filename in sorted(filenames):
        path = SHARED_DIR / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profiles = payload.get("voice_profiles") or {}
        if not isinstance(profiles, dict):
            continue
        grouped[filename] = {
            f"{profile.get('model')}|{voice_id}"
            for voice_id, profile in profiles.items()
            if isinstance(profile, dict)
            and profile.get("profile_status") == "ready"
            and profile.get("taxonomy_version") == TAXONOMY_VERSION
        }
    return grouped


def _local_audio(job: VoiceJob) -> Tuple[bytes, Path] | None:
    for ext in ("mp3", "wav"):
        candidate = AUDIO_DIR / f"{job.cache_key}.{ext}"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate.read_bytes(), candidate
    return None


def _download(url: str) -> bytes | None:
    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    return response.content if response.status_code < 400 and response.content else None


async def _acquire_audio(job: VoiceJob) -> Tuple[bytes, Path, str, str | None]:
    """返回 (音频, 本地路径, 来源, 线上地址)；本地 → OSS 缓存 → 真实合成并回传 OSS。"""
    cached = _local_audio(job)
    if cached is not None:
        audio_bytes, path = cached
        return audio_bytes, path, "local_cache", None

    for ext in ("mp3", "wav"):
        url = check_oss_preview_exists(job.cache_key, ext=ext)
        if not url:
            continue
        payload = _download(url)
        if payload:
            path = AUDIO_DIR / f"{job.cache_key}.{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return payload, path, "oss_cache", url

    from app.api.v1.audiobook_api import routes_tts
    from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

    _, _, voice_params = _build_preview_request(job.model, job.voice_id, job.preview_text)
    audio_bytes = await runtime_synthesize_speech(
        text=job.preview_text,
        voice_params=voice_params,
        emotion=str(voice_params.get("emotion") or "neutral"),
        model_id=job.model,
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=routes_tts._PREVIEW_RETRY_CONFIG,
    )
    if not audio_bytes:
        raise RuntimeError("empty audio from synthesis")
    ext = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    path = AUDIO_DIR / f"{job.cache_key}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio_bytes)
    return audio_bytes, path, "synthesized", upload_preview_to_oss(
        audio_bytes=audio_bytes, cache_key=job.cache_key, response_format=ext
    )


def _objective_gate(
    job: VoiceJob, audio_bytes: bytes, audio_path: Path, source: str, asr
) -> Dict[str, Any]:
    check = validate_tts_audio(audio_bytes, job.preview_text)
    objective: Dict[str, Any] = {
        "passed": bool(check.passed),
        "reason": check.reason,
        "audio_source": source,
        "duration_ms": check.duration_ms,
        "expected_duration_ms": check.expected_duration_ms,
        "silence_ratio": round(check.silence_ratio, 4),
        "rms_dbfs": round(check.rms_dbfs, 2),
        "transcript_similarity": None,
        "transcript": None,
    }
    if not objective["passed"]:
        return objective
    if asr is None:
        return {**objective, "passed": False, "reason": "asr_provider_unavailable"}
    try:
        result = asr.transcribe(str(audio_path))
    except PromptAudioAsrProviderError as exc:
        return {**objective, "passed": False, "reason": f"asr_failed:{exc.code}"}
    except Exception as exc:
        return {**objective, "passed": False, "reason": f"asr_error:{type(exc).__name__}"}
    similarity = transcript_similarity(expected=job.preview_text, transcript=result.transcript)
    objective["transcript_similarity"] = round(similarity, 4)
    objective["transcript"] = result.transcript
    if similarity < MIN_TRANSCRIPT_SIMILARITY:
        voiced_ms = check.duration_ms * (1 - check.silence_ratio)
        fold = fold_suspected_asr_repeat(
            expected=job.preview_text, transcript=result.transcript, voiced_duration_ms=voiced_ms
        )
        if fold is None or fold.similarity < MIN_TRANSCRIPT_SIMILARITY:
            return {**objective, "passed": False, "reason": "transcript_mismatch"}
        # 折叠只在这条路上发生：转写需要的朗读时长已经超出实测发声时长，物理上不可能念得出。
        return {
            **objective,
            "transcript_similarity": round(fold.similarity, 4),
            "transcript_similarity_raw": round(similarity, 4),
            "asr_repeat_suspect": True,
            "asr_repeat_removed": fold.removed_block,
        }
    return objective


def _catalog_revision(catalog_filename: str) -> str:
    path = _resolve_voice_library_path(catalog_filename)
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_existing_entries(profile_filename: str) -> Dict[str, Any]:
    """已落盘条目要保留：分批放量时同一文件里会有别的模型/批次的画像。"""
    path = SHARED_DIR / profile_filename
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = payload.get("voice_profiles") or {}
    if not isinstance(entries, dict):
        return {}
    return {
        str(voice_id): dict(profile)
        for voice_id, profile in entries.items()
        if isinstance(profile, dict)
    }


def _api_keys() -> Dict[str, str]:
    qwen_key = (os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY") or "").strip()
    doubao_key = (os.getenv("VOLCENGINE_API_KEY") or os.getenv("DOUBAO_API_KEY") or "").strip()
    return {PRIMARY_SCORER: doubao_key, REFERENCE_SCORER: qwen_key}


async def _process_job(job: VoiceJob, *, asr, keys: Dict[str, str]) -> Dict[str, Any]:
    audio_bytes, audio_path, source, oss_url = await _acquire_audio(job)
    objective = _objective_gate(job, audio_bytes, audio_path, source, asr)
    primary = None
    reference = None
    if objective["passed"]:
        try:
            primary, reference, _ = tag_voice_profile(
                audio_path=audio_path,
                text=job.preview_text,
                model=job.model,
                voice_id=job.voice_id,
                api_keys=keys,
                cache_dir=RAW_DIR,
            )
        except ValueError as exc:
            # 主模型不可用记成 pending 而不是丢行：客观层数据仍然值得留档，
            # 且原始响应缓存已写入的部分不会在重跑时再次扣费。
            print(f"    主模型打标失败: {exc}")
    entry = profile_entry_from_judgements(
        model=job.model,
        voice_id=job.voice_id,
        preview_text=job.preview_text,
        audio_sha256=hashlib.sha256(audio_bytes).hexdigest(),
        primary=primary,
        reference=reference,
        objective=objective,
    )
    return {
        "entry": entry,
        "profile_filename": job.profile_filename,
        "label": job.label,
        "voice_id": job.voice_id,
        "model": job.model,
        "audio_path": audio_path.relative_to(PROJECT_ROOT).as_posix(),
        "oss_url": oss_url,
    }


def _print_report(rows: List[Dict[str, Any]], written: Dict[str, int]) -> int:
    if not rows:
        print("\n[无产出] 本次没有成功处理的条目。")
        return 3
    ready = [row for row in rows if row["entry"]["profile_status"] == "ready"]
    rejected = [row for row in rows if row["entry"]["profile_status"] != "ready"]
    print("\n" + "=" * 72)
    print(f"处理 {len(rows)} 条：合格并落标签 {len(ready)} 条，不合格 {len(rejected)} 条")
    for filename, count in written.items():
        print(f"  画像文件 {filename}: 本次写入 {count} 条")
    if rejected:
        print(f"\n不合格清单（{len(rejected)} 条）：")
        for row in rejected:
            objective = row["entry"]["objective"]
            print(
                f"  - {row['model']} {row['label']} ({row['voice_id']})："
                f"reason={objective.get('reason')} "
                f"similarity={objective.get('transcript_similarity')}\n"
                f"      本地={row['audio_path']} 线上={row.get('oss_url') or '（命中本地缓存，未取线上地址）'}"
            )
    ratio = len(ready) / len(rows)
    print(f"\n批次合格率 {ratio:.1%}（合格线 {MIN_BATCH_READY_RATIO:.0%}）")
    return 0 if ratio >= MIN_BATCH_READY_RATIO else 4


async def _run(jobs: List[VoiceJob], *, asr, keys: Dict[str, str]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    grouped: Dict[str, Dict[str, Any]] = {}
    for index, job in enumerate(jobs, start=1):
        try:
            row = await _process_job(job, asr=asr, keys=keys)
        except Exception as exc:
            print(f"[{index}/{len(jobs)}] {job.model} {job.label} 处理异常: {type(exc).__name__}: {exc}")
            continue
        grouped.setdefault(job.profile_filename, _load_existing_entries(job.profile_filename))[job.voice_id] = row["entry"]
        rows.append(row)
        entry = row["entry"]
        print(
            f"[{index}/{len(jobs)}] {job.model} {job.label}: {entry['profile_status']} "
            f"similarity={entry['objective'].get('transcript_similarity')} tags={len(entry['tags'])}"
        )
    return rows, grouped


def main() -> int:
    parser = argparse.ArgumentParser(description="音色画像自动打标")
    parser.add_argument("--models", default="", help="逗号分隔的模型 ID")
    parser.add_argument("--all", action="store_true", help="覆盖全部提供系统音色的模型")
    parser.add_argument("--limit-per-model", type=int, default=0, help="每个模型最多处理条数，0 不限")
    parser.add_argument("--force-ready", action="store_true", help="重打已合格的画像")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不发起任何调用")
    parser.add_argument("--confirm-paid", action="store_true", help="真实发出 TTS/ASR/打标调用")
    args = parser.parse_args()

    targets = _iter_system_voice_models()
    if not args.all:
        requested = [item.strip() for item in args.models.split(",") if item.strip()]
        if not requested:
            print("[错误] 需要 --models 或 --all")
            return 2
        missing = [m for m in requested if m not in targets]
        targets = [m for m in targets if m in requested]
        if missing:
            print(f"[警告] 忽略不存在或无系统音色的模型: {missing}")

    jobs, notes = _iter_jobs(targets, limit=args.limit_per_model, skip_ready=not args.force_ready)
    for note in notes:
        print(f"[提示] {note}")
    print(f"待打标 {len(jobs)} 条，画像文件: {sorted({job.profile_filename for job in jobs})}")

    if args.dry_run:
        local_hits = sum(1 for job in jobs if _local_audio(job) is not None)
        print(f"  本地音频命中 {local_hits} 条，需走 OSS/合成的上游 {len(jobs) - local_hits} 条")
        for job in jobs:
            print(f"  - {job.model} {job.label} ({job.voice_id}) 文本={len(job.preview_text)}字 key={job.cache_key[:12]}")
        return 0
    if not args.confirm_paid:
        print("[停止] 未加 --confirm-paid，不发起付费调用。")
        return 2

    keys = _api_keys()
    for scorer in (PRIMARY_SCORER, REFERENCE_SCORER):
        print(f"  {scorer} key: {'ok' if keys.get(scorer) else 'missing'}")
    if not keys.get(PRIMARY_SCORER):
        print("[停止] 主评分模型密钥缺失。")
        return 2
    # 客观层必须拿逐字转写，不能被 env 默认评分器（qwen_omni）带走：后者会把要求复述成转写。
    asr = create_prompt_audio_asr_provider("qwen_audio_asr_flash")
    if asr is None or not getattr(asr, "configured", False):
        print("[停止] qwen-audio ASR 未配置，客观层无法校验逐字保真。")
        return 2
    print(f"  ASR: {asr.name}/{asr.model}")

    rows, grouped = asyncio.run(_run(jobs, asr=asr, keys=keys))

    written: Dict[str, int] = {}
    for filename, entries in grouped.items():
        catalog_filename = filename.replace("_voice_profiles.json", "_voices.json")
        document = build_sidecar_document(
            model=",".join(sorted({row["model"] for row in rows if row["profile_filename"] == filename})),
            catalog_filename=catalog_filename,
            catalog_revision=_catalog_revision(catalog_filename),
            entries=entries,
        )
        path = SHARED_DIR / filename
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written[filename] = sum(1 for row in rows if row["profile_filename"] == filename)
        print(f"画像落盘 {path.relative_to(PROJECT_ROOT).as_posix()}（累计 {len(entries)} 条）")

    return _print_report(rows, written)


if __name__ == "__main__":
    sys.exit(main())
