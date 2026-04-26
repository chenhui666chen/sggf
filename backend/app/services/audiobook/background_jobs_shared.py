from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio
from app.services.audiobook import AudiobookEngine, set_engine_instance
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.task_support import (
    StageTracker,
    build_progress_handler as _build_progress_handler,
    update_chapter_run_state as _update_chapter_run_state,
)
from app.services.audiobook.temp_segment_janitor import finalize_completed_chapter_run_temp_assets


@dataclass
class AudiobookProjectAudioTotals:
    completed_chapters: int = 0
    total_duration: float = 0.0
    total_cost: float = 0.0
    total_size: int = 0


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
    try:
        return float(str(raw_value).replace("¥", "").replace("$", ""))
    except Exception:
        return None


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

    return patch


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
        result={"temp_segment_cache": temp_segment_cache or {}},
        task_id=task_id,
    )
    if normalized_completed_segment_indices:
        checkpoint_patch["completed_segment_indices"] = normalized_completed_segment_indices

    _update_chapter_run_state(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
        status="running",
        current_stage="tts_synthesis",
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


__all__ = [
    "AudiobookProjectAudioTotals",
    "build_checkpoint_patch_from_generation_result",
    "compute_audio_project_totals",
    "create_background_engine",
    "get_latest_run_checkpoint_json",
    "parse_duration_seconds",
    "parse_estimated_cost",
    "persist_chapter_run_tts_progress",
    "prune_completed_run_temp_assets",
    "refresh_audiobook_project_audio_totals",
]
