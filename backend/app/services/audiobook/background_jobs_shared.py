from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.services.audiobook import AudiobookEngine, set_engine_instance
from app.services.audiobook.failure_diagnostics import (
    attach_failure_diagnostic_to_checkpoint_patch,
    build_chapter_failure_diagnostic,
)
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.subtitle_generator import SubtitleGenerator
from app.services.audiobook.task_support import (
    StageTracker,
    build_progress_handler as _build_progress_handler,
    serialize_dataclass_to_dict,
    update_chapter_run_state as _update_chapter_run_state,
)
from app.services.audiobook.tts_cost_utils import parse_tts_cost_yuan
from app.services.audiobook.temp_segment_janitor import finalize_completed_chapter_run_temp_assets
from app.services.user_center_points_events import (
    record_audiobook_billing_release,
    record_audiobook_billing_settle,
)


logger = logging.getLogger(__name__)


@dataclass
class AudiobookProjectAudioTotals:
    completed_chapters: int = 0
    total_duration: float = 0.0
    total_cost: float = 0.0
    total_size: int = 0


@dataclass
class ChapterGenerationOutputContext:
    resume_checkpoint: Dict[str, Any]
    output_format: str
    generate_subtitle: bool
    output_path: str
    tts_progress_callback: Callable[[Dict[str, Any]], None]


_SUPPORTED_AUDIO_OUTPUT_FORMATS = {"mp3", "wav", "m4b"}


def normalize_audiobook_output_format(value: Optional[str]) -> str:
    normalized = str(value or "mp3").strip().lower().lstrip(".")
    if normalized == "m4a":
        normalized = "m4b"
    if normalized not in _SUPPORTED_AUDIO_OUTPUT_FORMATS:
        return "mp3"
    return normalized


def build_chapter_audio_output_path(
    *,
    project_id: int,
    chapter_number: int,
    output_format: Optional[str] = None,
) -> str:
    extension = normalize_audiobook_output_format(output_format)
    return f"audiobooks/project_{project_id}/chapter_{chapter_number:03d}.{extension}"


def build_subtitle_artifact_paths(output_path: str) -> Dict[str, str]:
    base_path = Path(output_path).with_suffix("")
    return {
        "srt": f"{base_path}.srt",
        "vtt": f"{base_path}.vtt",
        "ass": f"{base_path}.ass",
        "audacity_labels": f"{base_path}.labels.txt",
    }


def generate_subtitle_artifacts(
    *,
    script_segments: Any,
    segment_timings: Any,
    output_path: str,
    title: str = "Audiobook",
) -> Dict[str, Any]:
    normalized_segments = serialize_dataclass_to_dict(script_segments or [])
    if not isinstance(normalized_segments, list):
        return {"generated": False, "reason": "invalid_script_segments"}
    if not isinstance(segment_timings, list) or not segment_timings:
        return {"generated": False, "reason": "missing_segment_timings"}

    paths = build_subtitle_artifact_paths(output_path)
    entries = SubtitleGenerator.from_segment_timings(normalized_segments, segment_timings)
    if not entries:
        return {"generated": False, "reason": "empty_subtitle_entries", "paths": paths}

    SubtitleGenerator.generate_srt(entries, paths["srt"])
    SubtitleGenerator.generate_vtt(entries, paths["vtt"])
    SubtitleGenerator.generate_ass(entries, paths["ass"], title=title or "Audiobook")
    SubtitleGenerator.generate_audacity_labels(entries, paths["audacity_labels"])

    return {
        "generated": True,
        "entry_count": len(entries),
        "paths": paths,
        "subtitle_path": paths["srt"],
        "subtitle_format": "srt",
    }


def generate_and_apply_subtitle_artifacts(
    *,
    chapter_audio: ChapterAudio,
    result: Dict[str, Any],
    fallback_script_segments: Any,
    output_path: str,
    title: str,
    generate_subtitle: bool,
) -> Dict[str, Any]:
    subtitle_segments_payload = result.get("timing_segments_payload") or fallback_script_segments
    subtitle_artifacts = (
        generate_subtitle_artifacts(
            script_segments=subtitle_segments_payload,
            segment_timings=result.get("segment_timings") or [],
            output_path=output_path,
            title=title,
        )
        if generate_subtitle
        else {"generated": False, "reason": "disabled_by_request"}
    )
    result["subtitle_artifacts"] = subtitle_artifacts
    if subtitle_artifacts.get("generated"):
        chapter_audio.subtitle_path = subtitle_artifacts.get("subtitle_path")
        chapter_audio.subtitle_format = subtitle_artifacts.get("subtitle_format") or "srt"
    return subtitle_artifacts


def create_background_engine(
    *,
    audiobook_project: AudiobookProject,
    chapter_ids: List[int],
    tts_model: str,
    tracker: Optional[StageTracker],
) -> AudiobookEngine:
    from core.unified_llm_client import get_llm_client

    llm_client = get_llm_client(strategy="conservative")
    progress_handler = _build_progress_handler(tracker, chapter_ids)
    engine = AudiobookEngine(
        enable_cache=audiobook_project.enable_cache,
        max_concurrent=1,
        llm_client=llm_client,
        tts_model=tts_model,
        progress_handler=progress_handler,
    )
    set_engine_instance(engine)
    return engine


def parse_duration_seconds(raw_value: Any) -> Optional[float]:
    try:
        return float(str(raw_value).replace("秒", ""))
    except Exception:
        return None


def parse_estimated_cost(raw_value: Any) -> Optional[float]:
    return parse_tts_cost_yuan(raw_value)


def apply_chapter_audio_generation_result(
    *,
    chapter_audio: ChapterAudio,
    result: Dict[str, Any],
    output_path: str,
    preserve_existing_counts: bool = False,
    require_audio_metrics: bool = False,
    logger: Any = None,
    chapter_id: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    raw_stats = result.get("stats") or {}
    stats = raw_stats if isinstance(raw_stats, dict) else {}
    raw_parse_stats = stats.get("parse_stats") or {}
    raw_tts_stats = stats.get("tts_stats") or {}
    parse_stats = raw_parse_stats if isinstance(raw_parse_stats, dict) else {}
    tts_stats = raw_tts_stats if isinstance(raw_tts_stats, dict) else {}

    chapter_audio.audio_path = output_path
    if require_audio_metrics:
        chapter_audio.duration = result["duration"]
        chapter_audio.file_size = result["file_size"]
    else:
        chapter_audio.duration = result.get("duration") or 0.0
        chapter_audio.file_size = result.get("file_size") or 0

    count_defaults = {
        "total_segments": chapter_audio.segment_count if preserve_existing_counts else 0,
        "dialogue_count": chapter_audio.dialogue_count if preserve_existing_counts else 0,
        "narration_count": chapter_audio.narration_count if preserve_existing_counts else 0,
    }
    chapter_audio.segment_count = parse_stats.get(
        "total_segments",
        count_defaults["total_segments"],
    )
    chapter_audio.dialogue_count = parse_stats.get(
        "dialogue_count",
        count_defaults["dialogue_count"],
    )
    chapter_audio.narration_count = parse_stats.get(
        "narration_count",
        count_defaults["narration_count"],
    )

    generation_time = parse_duration_seconds(stats.get("generation_time", "0秒"))
    if generation_time is not None:
        chapter_audio.generation_time = generation_time

    raw_cost = tts_stats.get("estimated_cost_yuan")
    if raw_cost is None:
        raw_cost = tts_stats.get("estimated_cost", "¥0.00")
    cost = parse_estimated_cost(raw_cost)
    if cost is not None:
        chapter_audio.tts_cost = cost

    final_audio_review = stats.get("final_audio_review")
    if final_audio_review is not None:
        try:
            chapter_audio.final_audio_review_json = json.dumps(
                final_audio_review,
                ensure_ascii=False,
            )
        except Exception as dump_err:
            if logger is not None:
                logger.warning(
                    "⚠️ 序列化最终音频评审结果失败 chapter_id=%s: %s",
                    chapter_id,
                    dump_err,
                )

    return {
        "stats": stats,
        "parse_stats": parse_stats,
        "tts_stats": tts_stats,
    }


def build_checkpoint_patch_from_generation_result(
    *,
    result: Optional[Dict[str, Any]],
    task_id: Optional[str],
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    patch: Dict[str, Any] = {}
    if task_id:
        patch["engine_task_id"] = task_id
    if output_path:
        patch["output_path"] = output_path
    if not isinstance(result, dict):
        return patch

    segment_timings = result.get("segment_timings")
    if isinstance(segment_timings, list) and segment_timings:
        patch["segment_timings"] = segment_timings

    subtitle_artifacts = result.get("subtitle_artifacts")
    if isinstance(subtitle_artifacts, dict) and subtitle_artifacts:
        patch["subtitle_artifacts"] = subtitle_artifacts

    effect_timeline = result.get("effect_timeline")
    if isinstance(effect_timeline, dict) and isinstance(effect_timeline.get("timeline"), list):
        patch["effect_timeline"] = effect_timeline

    scene_checkpoints = result.get("scene_checkpoints")
    if isinstance(scene_checkpoints, dict) and scene_checkpoints:
        patch["scene_checkpoints"] = {
            str(scene_id): dict(checkpoint)
            for scene_id, checkpoint in scene_checkpoints.items()
            if scene_id is not None and isinstance(checkpoint, dict)
        }

    temp_segment_cache = result.get("temp_segment_cache")
    if not isinstance(temp_segment_cache, dict):
        return patch

    temp_asset_prefix = temp_segment_cache.get("temp_asset_prefix")
    if isinstance(temp_asset_prefix, str) and temp_asset_prefix:
        patch["temp_asset_prefix"] = temp_asset_prefix

    cached_audio_paths = temp_segment_cache.get("cached_audio_paths")
    if isinstance(cached_audio_paths, dict) and cached_audio_paths:
        patch["cached_audio_paths"] = cached_audio_paths
        completed_segment_indices: List[int] = []
        for raw_index in cached_audio_paths.keys():
            try:
                index = int(raw_index)
            except Exception:
                continue
            if index < 0:
                continue
            completed_segment_indices.append(index)
        if completed_segment_indices:
            patch["completed_segment_indices"] = sorted(set(completed_segment_indices))

    segments = temp_segment_cache.get("segments")
    if isinstance(segments, dict) and segments:
        patch["segments"] = segments

    segment_statuses = temp_segment_cache.get("segment_statuses")
    if isinstance(segment_statuses, dict) and segment_statuses:
        patch["segment_statuses"] = segment_statuses

    failed_segment_indices = temp_segment_cache.get("failed_segment_indices")
    if isinstance(failed_segment_indices, list) and failed_segment_indices:
        normalized_failed_indices: List[int] = []
        for raw_index in failed_segment_indices:
            try:
                index = int(raw_index)
            except Exception:
                continue
            if index < 0:
                continue
            normalized_failed_indices.append(index)
        if normalized_failed_indices:
            patch["failed_segment_indices"] = sorted(set(normalized_failed_indices))

    failed_segment_errors = temp_segment_cache.get("failed_segment_errors")
    if isinstance(failed_segment_errors, dict) and failed_segment_errors:
        patch["failed_segment_errors"] = failed_segment_errors

    for key in ("render_plan_version", "render_chunk_count", "render_plan"):
        value = temp_segment_cache.get(key)
        if value:
            patch[key] = value

    return patch


def mark_chapter_generation_failed(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    stage: str,
    chapter: Any = None,
    script_segments: Any = None,
    result: Optional[Dict[str, Any]] = None,
    exception: Optional[BaseException] = None,
    resume_checkpoint: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    default_error_message: str = "generation_failed",
) -> Dict[str, Any]:
    safe_result = result if isinstance(result, dict) else None
    failure_stats = safe_result.get("stats") if safe_result else {}
    failure_parse_stats = (
        failure_stats.get("parse_stats") if isinstance(failure_stats, dict) else {}
    )
    if not isinstance(failure_parse_stats, dict):
        failure_parse_stats = {}

    chapter_title = getattr(chapter, "title", None) if chapter is not None else None
    chapter_number = (
        getattr(chapter, "chapter_number", None) if chapter is not None else None
    )
    normalized_script_segments = script_segments if isinstance(script_segments, list) else []

    checkpoint_patch = build_checkpoint_patch_from_generation_result(
        result=safe_result,
        task_id=task_id,
    )
    failure_diagnostic = build_chapter_failure_diagnostic(
        stage=stage,
        chapter_id=chapter_id,
        chapter_title=chapter_title,
        chapter_number=chapter_number,
        script_segments=normalized_script_segments,
        result=safe_result,
        exception=exception,
        resume_checkpoint=resume_checkpoint if isinstance(resume_checkpoint, dict) else {},
        task_id=task_id,
    )
    checkpoint_patch = attach_failure_diagnostic_to_checkpoint_patch(
        checkpoint_patch,
        failure_diagnostic,
    )
    failure_total_segments = (
        failure_diagnostic.get("total_segment_count")
        or failure_parse_stats.get("total_segments")
    )
    error_message = (
        str(exception)
        if exception is not None
        else str((safe_result or {}).get("error") or default_error_message)
    )

    _update_chapter_run_state(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
        status="failed",
        current_stage="failed",
        progress=0.0,
        total_segment_count=failure_total_segments,
        checkpoint_patch=checkpoint_patch,
        error_message=error_message,
    )

    return {
        "checkpoint_patch": checkpoint_patch,
        "failure_diagnostic": failure_diagnostic,
        "total_segment_count": failure_total_segments,
        "error_message": error_message,
    }


def compute_audio_project_totals(chapter_audios: List[Any]) -> AudiobookProjectAudioTotals:
    totals = AudiobookProjectAudioTotals()
    for chapter_audio in chapter_audios or []:
        audio_path = str(getattr(chapter_audio, "audio_path", "") or "").strip()
        if not audio_path:
            continue

        totals.completed_chapters += 1
        try:
            totals.total_duration += float(getattr(chapter_audio, "duration", 0.0) or 0.0)
        except Exception:
            pass
        try:
            totals.total_cost += float(getattr(chapter_audio, "tts_cost", 0.0) or 0.0)
        except Exception:
            pass
        try:
            totals.total_size += int(getattr(chapter_audio, "file_size", 0) or 0)
        except Exception:
            pass
    return totals


def refresh_audiobook_project_audio_totals(
    db: Session,
    *,
    audiobook_project: AudiobookProject,
    failed_chapters: Optional[int] = None,
) -> AudiobookProjectAudioTotals:
    db.flush()
    chapter_audios = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.audiobook_project_id == audiobook_project.id,
            ChapterAudio.deleted_at.is_(None),
        )
        .all()
    )
    totals = compute_audio_project_totals(chapter_audios)
    audiobook_project.completed_chapters = totals.completed_chapters
    audiobook_project.total_duration = totals.total_duration
    audiobook_project.total_cost = totals.total_cost
    audiobook_project.total_size = totals.total_size
    if failed_chapters is not None:
        audiobook_project.failed_chapters = failed_chapters
    return totals


def mark_chapter_preflight_failed(
    db: Session,
    *,
    audiobook_project: AudiobookProject,
    chapter_id: int,
    run_type: str,
    error_message: str,
    failed_chapters: int,
) -> int:
    next_failed_chapters = failed_chapters + 1
    _update_chapter_run_state(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter_id,
        run_type=run_type,
        status="failed",
        current_stage="failed",
        progress=0.0,
        error_message=error_message,
    )
    refresh_audiobook_project_audio_totals(
        db,
        audiobook_project=audiobook_project,
        failed_chapters=next_failed_chapters,
    )
    return next_failed_chapters


def settle_audiobook_project_billing(
    logger: Any,
    db: Session,
    *,
    audiobook_project_id: int,
) -> None:
    try:
        record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project_id)
    except Exception as exc:
        logger.warning(
            "记录有声书积分结算失败 audiobook_project_id=%s: %s",
            audiobook_project_id,
            exc,
        )


def release_audiobook_project_billing(
    logger: Any,
    db: Session,
    *,
    audiobook_project_id: int,
    reason: str,
) -> None:
    try:
        record_audiobook_billing_release(
            db=db,
            audiobook_project_id=audiobook_project_id,
            reason=reason,
        )
    except Exception as exc:
        logger.warning(
            "释放有声书冻结积分失败 audiobook_project_id=%s: %s",
            audiobook_project_id,
            exc,
        )


def prune_completed_run_temp_assets(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
) -> Dict[str, Any]:
    run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    if not run:
        return {
            "run_id": None,
            "chapter_id": chapter_id,
            "removed_temp_files": 0,
            "cleanup_skipped": "run_not_found",
        }

    summary = finalize_completed_chapter_run_temp_assets(run)
    db.add(run)
    return summary


def prune_and_log_completed_run_temp_assets(
    logger: Any,
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
) -> Dict[str, Any]:
    cleanup_summary = prune_completed_run_temp_assets(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    if cleanup_summary.get("cleanup_skipped"):
        logger.warning(
            "Completed run temp cleanup skipped: chapter_id=%s, reason=%s",
            chapter_id,
            cleanup_summary.get("cleanup_skipped"),
        )
    else:
        logger.info(
            "Completed run temp assets pruned: chapter_id=%s, run_id=%s, removed_temp_files=%s",
            chapter_id,
            cleanup_summary.get("run_id"),
            cleanup_summary.get("removed_temp_files"),
        )
    return cleanup_summary


def persist_chapter_run_tts_progress(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    task_id: Optional[str],
    total_segment_count: int,
    completed_segment_indices: List[int],
    temp_segment_cache: Optional[Dict[str, Any]],
    scene_checkpoints: Optional[Dict[str, Any]] = None,
) -> None:
    if total_segment_count <= 0:
        return

    normalized_completed_segment_indices = sorted(
        {
            int(index)
            for index in (completed_segment_indices or [])
            if isinstance(index, int) or (isinstance(index, str) and str(index).isdigit())
        }
    )
    completed_segment_count = len(normalized_completed_segment_indices)
    progress = (
        float(completed_segment_count) / float(total_segment_count)
        if total_segment_count > 0
        else 0.0
    )

    checkpoint_patch = build_checkpoint_patch_from_generation_result(
        result={
            "temp_segment_cache": temp_segment_cache or {},
            "scene_checkpoints": scene_checkpoints or {},
        },
        task_id=task_id,
    )
    if normalized_completed_segment_indices:
        checkpoint_patch["completed_segment_indices"] = normalized_completed_segment_indices

    current_stage = (
        "scene_rendering"
        if scene_checkpoints is not None
        else "tts_synthesis"
    )

    _update_chapter_run_state(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
        status="running",
        current_stage=current_stage,
        progress=progress,
        total_segment_count=total_segment_count,
        completed_segment_count=completed_segment_count,
        checkpoint_patch=checkpoint_patch,
    )


def get_latest_run_checkpoint_json(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
) -> Dict[str, Any]:
    run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    checkpoint_json = getattr(run, "checkpoint_json", None)
    return dict(checkpoint_json or {}) if isinstance(checkpoint_json, dict) else {}


def prepare_chapter_generation_output_context(
    db: Session,
    *,
    engine: Any,
    audiobook_project: AudiobookProject,
    chapter_id: int,
    chapter_number: int,
    run_type: str,
) -> ChapterGenerationOutputContext:
    resume_checkpoint = get_latest_run_checkpoint_json(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    output_format = normalize_audiobook_output_format(
        resume_checkpoint.get("output_format")
    )
    generate_subtitle = resume_checkpoint.get("generate_subtitle", True) is not False

    apply_narration_style_config = getattr(engine, "apply_narration_style_config", None)
    if callable(apply_narration_style_config):
        apply_narration_style_config(
            resume_checkpoint.get("narration_style"),
            resume_checkpoint.get("narration_style_prompt"),
        )

    output_path = build_chapter_audio_output_path(
        project_id=audiobook_project.project_id,
        chapter_number=chapter_number,
        output_format=output_format,
    )

    def handle_tts_progress(progress_payload: Dict[str, Any]) -> None:
        payload = progress_payload or {}
        persist_chapter_run_tts_progress(
            db,
            audiobook_project_id=audiobook_project.id,
            chapter_id=chapter_id,
            run_type=run_type,
            task_id=payload.get("task_id"),
            total_segment_count=int(payload.get("total_segments") or 0),
            completed_segment_indices=payload.get("completed_segment_indices") or [],
            temp_segment_cache=payload.get("temp_segment_cache"),
            scene_checkpoints=payload.get("scene_checkpoints"),
        )

    return ChapterGenerationOutputContext(
        resume_checkpoint=resume_checkpoint,
        output_format=output_format,
        generate_subtitle=generate_subtitle,
        output_path=output_path,
        tts_progress_callback=handle_tts_progress,
    )


__all__ = [
    "AudiobookProjectAudioTotals",
    "apply_chapter_audio_generation_result",
    "build_checkpoint_patch_from_generation_result",
    "build_chapter_audio_output_path",
    "build_subtitle_artifact_paths",
    "compute_audio_project_totals",
    "create_background_engine",
    "generate_and_apply_subtitle_artifacts",
    "generate_subtitle_artifacts",
    "get_latest_run_checkpoint_json",
    "mark_chapter_generation_failed",
    "mark_chapter_preflight_failed",
    "normalize_audiobook_output_format",
    "parse_duration_seconds",
    "parse_estimated_cost",
    "persist_chapter_run_tts_progress",
    "prepare_chapter_generation_output_context",
    "prune_and_log_completed_run_temp_assets",
    "prune_completed_run_temp_assets",
    "refresh_audiobook_project_audio_totals",
    "release_audiobook_project_billing",
    "settle_audiobook_project_billing",
]
