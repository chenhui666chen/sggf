from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Chapter
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


def is_audiobook_project_active(db: Session, *, audiobook_project_id: int) -> bool:
    """返回有声书项目是否仍可接收后台任务写入。"""
    with db.no_autoflush:
        return (
            db.query(AudiobookProject)
            .filter(
                AudiobookProject.id == audiobook_project_id,
                AudiobookProject.deleted_at.is_(None),
            )
            .populate_existing()
            .first()
            is not None
        )


def is_chapter_generation_target_active(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio_id: Optional[int] = None,
    run_id: Optional[int] = None,
) -> bool:
    """在生成结果写入前重新确认目标仍属于活动产物。

    后台任务通常会在 TTS/LLM 调用期间持有数分钟以前读取的 ORM 对象。
    删除接口可能在此期间软删除项目或章节音频，因此不能仅依赖内存对象
    的 ``deleted_at`` 值。``populate_existing`` 强制从数据库刷新当前状态。
    ``chapter_audio_id`` 为空表示允许首轮生成新记录；非空时则要求原记录
    仍然存在且未被删除，防止删除后把旧对象重新写活。提供 ``run_id`` 时，
    删除流程写入的不可恢复取消状态同样视为目标失效，可覆盖尚未创建
    ``ChapterAudio`` 的首次生成。
    """
    with db.no_autoflush:
        audiobook_project = (
            db.query(AudiobookProject)
            .filter(
                AudiobookProject.id == audiobook_project_id,
                AudiobookProject.deleted_at.is_(None),
            )
            .populate_existing()
            .first()
        )
        if audiobook_project is None:
            return False

        chapter = (
            db.query(Chapter)
            .filter(
                Chapter.id == chapter_id,
                Chapter.deleted_at.is_(None),
            )
            .populate_existing()
            .first()
        )
        if chapter is None:
            return False

        if run_id is not None:
            run = (
                db.query(ChapterAudioRun)
                .filter(
                    ChapterAudioRun.id == run_id,
                    ChapterAudioRun.audiobook_project_id == audiobook_project_id,
                    ChapterAudioRun.chapter_id == chapter_id,
                )
                .populate_existing()
                .first()
            )
            if run is None:
                return False
            if str(run.status or "").strip().lower() in {
                "cancelled",
                "canceled",
                "expired",
            }:
                return False
            if (
                not bool(run.resumable)
                and str(run.error_message or "").strip() == "chapter_output_deleted"
            ):
                return False

        if chapter_audio_id is None:
            return True

        chapter_audio = (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.id == chapter_audio_id,
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .populate_existing()
            .first()
        )
        return chapter_audio is not None


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
    audiobook_project_id: Optional[int] = None,
) -> str:
    extension = normalize_audiobook_output_format(output_format)
    # 同一小说项目可派生多个有声书项目，输出路径必须包含
    # audiobook_project_id 隔离，否则不同有声书会互相覆盖整章音频
    if audiobook_project_id:
        return (
            f"audiobooks/project_{project_id}/"
            f"audiobook_{int(audiobook_project_id)}/"
            f"chapter_{chapter_number:03d}.{extension}"
        )
    return f"audiobooks/project_{project_id}/chapter_{chapter_number:03d}.{extension}"


def build_subtitle_artifact_paths(output_path: str) -> Dict[str, str]:
    base_path = Path(output_path).with_suffix("")
    return {
        "srt": f"{base_path}.srt",
        "vtt": f"{base_path}.vtt",
        "ass": f"{base_path}.ass",
        "audacity_labels": f"{base_path}.labels.txt",
    }


def cleanup_aborted_chapter_generation_artifacts(
    *,
    output_path: Optional[str],
    result: Optional[Dict[str, Any]] = None,
    persistent_asset_refs: Optional[Iterable[str]] = None,
) -> Dict[str, int]:
    """回收目标失效后由本次生成留下的整章、字幕及片段资产。"""
    from app.services.audiobook.project_exporter import resolve_existing_audio_path
    from app.services.audiobook.temp_segment_store import delete_temp_segment_prefix

    candidates: List[str] = []
    normalized_output_path = str(output_path or "").strip()
    if normalized_output_path:
        candidates.append(normalized_output_path)
        candidates.extend(build_subtitle_artifact_paths(normalized_output_path).values())

    safe_result = result if isinstance(result, dict) else {}
    subtitle_artifacts = safe_result.get("subtitle_artifacts")
    if isinstance(subtitle_artifacts, dict):
        subtitle_path = str(subtitle_artifacts.get("subtitle_path") or "").strip()
        if subtitle_path:
            candidates.append(subtitle_path)
        subtitle_paths = subtitle_artifacts.get("paths")
        if isinstance(subtitle_paths, dict):
            candidates.extend(
                str(path).strip()
                for path in subtitle_paths.values()
                if str(path or "").strip()
            )

    removed_output_files = 0
    seen_paths: set[str] = set()
    for raw_path in candidates:
        resolved = resolve_existing_audio_path(raw_path)
        if resolved is None:
            continue
        key = resolved.as_posix().lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        try:
            resolved.unlink(missing_ok=True)
            removed_output_files += 1
        except OSError as exc:
            logger.warning("回收已中止章节生成文件失败: path=%s error=%s", resolved, exc)

    removed_temp_files = 0
    temp_cache = safe_result.get("temp_segment_cache")
    if isinstance(temp_cache, dict):
        temp_asset_prefix = str(temp_cache.get("temp_asset_prefix") or "").strip()
        if temp_asset_prefix:
            try:
                removed_temp_files = int(
                    max(delete_temp_segment_prefix(temp_asset_prefix, temp_cache), 0)
                )
            except Exception as exc:
                logger.warning(
                    "回收已中止章节生成临时片段失败: prefix=%s error=%s",
                    temp_asset_prefix,
                    exc,
                )

    summary = {
        "removed_output_files": removed_output_files,
        "removed_temp_files": removed_temp_files,
    }
    normalized_persistent_refs = {
        str(asset_ref or "").strip()
        for asset_ref in (persistent_asset_refs or [])
        if str(asset_ref or "").strip()
    }
    if normalized_persistent_refs:
        from app.services.audiobook.chapter_segment_assets import (
            delete_segment_asset_refs,
        )

        try:
            summary["removed_persistent_files"] = int(
                max(delete_segment_asset_refs(normalized_persistent_refs), 0)
            )
        except Exception as exc:
            logger.warning(
                "回收已中止章节生成持久片段失败: refs=%s error=%s",
                len(normalized_persistent_refs),
                exc,
            )
            summary["removed_persistent_files"] = 0
    return summary


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

    music_timeline = result.get("music_timeline")
    if isinstance(music_timeline, dict) and isinstance(music_timeline.get("timeline"), list):
        patch["music_timeline"] = music_timeline

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

    # 缺失片段人类可读报告（含源剧本索引/角色/请求音色/错误类型），
    # 供前端“部分片段失败可重试”弹窗直接展示。
    missing_segments = result.get("missing_segments")
    if isinstance(missing_segments, list) and missing_segments:
        patch["missing_segments"] = missing_segments

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
    run_id: Optional[int] = None,
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
        run_id=run_id,
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
    run_id: Optional[int] = None,
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
        run_id=run_id,
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
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    run = None
    if run_id is not None:
        run = ChapterAudioRunRepository.get_run_by_id(db, run_id=run_id)
        if run is not None and (
            run.audiobook_project_id != audiobook_project_id
            or run.chapter_id != chapter_id
        ):
            run = None
    if run is None:
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
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    cleanup_summary = prune_completed_run_temp_assets(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
        run_id=run_id,
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
    run_id: Optional[int] = None,
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
        run_id=run_id,
    )


def get_latest_run_checkpoint_json(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    run = None
    if run_id is not None:
        run = ChapterAudioRunRepository.get_run_by_id(db, run_id=run_id)
        if run is not None and (
            run.audiobook_project_id != audiobook_project_id
            or run.chapter_id != chapter_id
        ):
            run = None
    if run is None:
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
    run_id: Optional[int] = None,
) -> ChapterGenerationOutputContext:
    resume_checkpoint = get_latest_run_checkpoint_json(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_id=chapter_id,
        run_type=run_type,
        run_id=run_id,
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
        audiobook_project_id=audiobook_project.id,
    )
    logger.info(
        "📁 章节生成输出上下文: audiobook_project_id=%s chapter_id=%s "
        "run_type=%s run_id=%s output_path=%s",
        audiobook_project.id,
        chapter_id,
        run_type,
        run_id,
        output_path,
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
            run_id=run_id,
        )

    return ChapterGenerationOutputContext(
        resume_checkpoint=resume_checkpoint,
        output_format=output_format,
        generate_subtitle=generate_subtitle,
        output_path=output_path,
        tts_progress_callback=handle_tts_progress,
    )


def merge_workbench_segment_audio_into_checkpoint(
    *,
    script_segments: List[Any],
    resume_checkpoint: Optional[Dict[str, Any]],
    default_tts_model: Optional[str] = None,
) -> Dict[str, Any]:
    """把编辑工作台已生成保存的片段音频合并进 resume checkpoint。

    仅注入同时满足以下条件的持久化片段（引擎按 render chunk 签名 remap 复用）：

    - 片段 ``audio_path`` 为持久化资产 ref（不受 run 临时资产过期清理影响）；
    - 片段 ``audio_cache_key`` 与当前剧本对应 render chunk 的签名一致；
    - 该片段的每个 render chunk 均为其独占（未与其他片段合并）；
    - 单 chunk 片段直接使用片段音频；多 chunk 片段要求存在与全部
      chunk 签名一一对应的持久化单块音频（``audio_chunk_cache_paths``）；
    - 持久化文件仍然存在。

    工作台片段放入当前 checkpoint，原 run checkpoint 挂到 ``source_checkpoint``，
    引擎的双源合并机制保证两份音频源都可复用且工作台音频优先。
    无可注入片段时原样返回原 checkpoint。
    """
    from app.services.audiobook.chapter_segment_assets import (
        _normalize_segment_for_render_plan,
        combine_chunk_cache_keys,
        is_persistent_segment_asset_ref,
        persistent_segment_audio_exists,
    )
    from app.services.audiobook.engine_pkg._tts_mixin import (
        QWEN_RENDER_CHUNK_MAX_CHARS,
        _is_qwen_tts_model,
        _item_tts_model,
    )
    from app.services.audiobook.render_plan import (
        build_render_plan,
        render_plan_to_payload,
    )

    base_checkpoint = dict(resume_checkpoint) if isinstance(resume_checkpoint, dict) else {}
    raw_segments = list(script_segments or [])
    if not raw_segments:
        return base_checkpoint

    # 与引擎 _build_render_chunks 保持一致的分块策略，保证签名可比对
    normalized_segments = [
        _normalize_segment_for_render_plan(segment) for segment in raw_segments
    ]
    segment_models = [_item_tts_model(item) for item in normalized_segments]
    has_qwen_model = _is_qwen_tts_model(default_tts_model) or any(
        _is_qwen_tts_model(model) for model in segment_models if model
    )
    max_chunk_chars = QWEN_RENDER_CHUNK_MAX_CHARS if has_qwen_model else None
    render_chunks = build_render_plan(normalized_segments, max_chunk_chars=max_chunk_chars)
    if not render_chunks:
        return base_checkpoint

    seed_paths: Dict[int, str] = {}
    # 片段级复用要求片段全部 render chunk 均为其独占；
    # 存在跨片段合并 chunk 的片段无法按块注入，整体跳过
    chunks_by_segment: Dict[int, List[Any]] = {}
    for chunk in render_chunks:
        source_indices = list(chunk.source_segment_indices or [])
        if len(source_indices) != 1:
            continue
        chunks_by_segment.setdefault(source_indices[0], []).append(chunk)
    for chunk in render_chunks:
        source_indices = list(chunk.source_segment_indices or [])
        if len(source_indices) == 1:
            continue
        for shared_index in source_indices:
            chunks_by_segment.pop(shared_index, None)
    for segment_index in sorted(chunks_by_segment):
        segment_chunks = sorted(chunks_by_segment[segment_index], key=lambda c: int(c.index))
        if not 0 <= segment_index < len(raw_segments):
            continue
        segment = raw_segments[segment_index]
        if not isinstance(segment, dict):
            continue
        audio_ref = str(segment.get("audio_path") or "").strip()
        if not audio_ref or not is_persistent_segment_asset_ref(audio_ref):
            continue
        stored_key = str(segment.get("audio_cache_key") or "").strip()
        chunk_keys = [str(chunk.cache_key or "").strip() for chunk in segment_chunks]
        if not stored_key or not all(chunk_keys):
            continue
        if stored_key != combine_chunk_cache_keys(chunk_keys):
            continue
        if len(segment_chunks) == 1:
            chunk = segment_chunks[0]
            if stored_key != str(chunk.cache_key or "").strip():
                continue
            if not persistent_segment_audio_exists(audio_ref):
                logger.info(
                    "工作台片段持久化文件缺失，跳过复用: segment_index=%s ref=%s",
                    segment_index,
                    audio_ref,
                )
                continue
            seed_paths[int(chunk.index)] = audio_ref
            continue
        # 多 chunk 片段：要求存在与全部 chunk 签名一一对应的持久化单块音频
        chunk_cache_paths = segment.get("audio_chunk_cache_paths")
        if not isinstance(chunk_cache_paths, dict) or not chunk_cache_paths:
            continue
        chunk_refs: Dict[int, str] = {}
        for chunk in segment_chunks:
            chunk_key = str(chunk.cache_key or "").strip()
            chunk_ref = str(chunk_cache_paths.get(chunk_key) or "").strip()
            if not chunk_ref or not is_persistent_segment_asset_ref(chunk_ref):
                chunk_refs = {}
                break
            if not persistent_segment_audio_exists(chunk_ref):
                logger.info(
                    "工作台片段 chunk 持久化文件缺失，跳过复用: "
                    "segment_index=%s chunk=%s ref=%s",
                    segment_index,
                    chunk.index,
                    chunk_ref,
                )
                chunk_refs = {}
                break
            chunk_refs[int(chunk.index)] = chunk_ref
        seed_paths.update(chunk_refs)

    if not seed_paths:
        return base_checkpoint

    seed_checkpoint = dict(base_checkpoint)
    seed_checkpoint["cached_audio_paths"] = seed_paths
    seed_checkpoint["render_plan"] = render_plan_to_payload(render_chunks)
    seed_checkpoint["total_segments"] = len(render_chunks)
    seed_checkpoint["completed_segment_indices"] = sorted(seed_paths)
    if base_checkpoint:
        seed_checkpoint["source_checkpoint"] = base_checkpoint
    logger.info(
        "🎯 工作台片段音频并入 resume checkpoint: reused=%d total_chunks=%d",
        len(seed_paths),
        len(render_chunks),
    )
    return seed_checkpoint


__all__ = [
    "AudiobookProjectAudioTotals",
    "apply_chapter_audio_generation_result",
    "build_checkpoint_patch_from_generation_result",
    "build_chapter_audio_output_path",
    "build_subtitle_artifact_paths",
    "cleanup_aborted_chapter_generation_artifacts",
    "compute_audio_project_totals",
    "create_background_engine",
    "generate_and_apply_subtitle_artifacts",
    "generate_subtitle_artifacts",
    "get_latest_run_checkpoint_json",
    "is_audiobook_project_active",
    "is_chapter_generation_target_active",
    "mark_chapter_generation_failed",
    "mark_chapter_preflight_failed",
    "merge_workbench_segment_audio_into_checkpoint",
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
