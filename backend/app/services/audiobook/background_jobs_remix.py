"""章节整章重新混音（remix）后台任务。

从 script_json 读取各片段的持久化音频（工作台/管线生成），
按引擎一致的混音链路（分段装载 → 音效/配乐时间线叠加 → 转码 → 原子写盘）
重新混合出整章音频，并重建字幕、更新章节产物与 ``chapter_remix`` run 状态。

缺失检查由端点同步执行（``collect_chapter_remix_missing_segments``），
用户在确认缺失后仍可 force 混音：缺失片段跳过装载，其余片段正常混合。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun
from app.models.project import Project
from app.services.audiobook.atomic_files import write_bytes_atomic
from app.services.audiobook.background_jobs_shared import (
    build_chapter_audio_output_path,
    get_latest_run_checkpoint_json,
)
from app.services.audiobook.chapter_segment_assets import (
    is_persistent_segment_asset_ref,
    load_persistent_segment_audio,
    persistent_segment_audio_exists,
    segment_audio_signature_status,
)
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.task_support import (
    update_chapter_run_state as _update_chapter_run_state,
)

logger = logging.getLogger(__name__)

CHAPTER_REMIX_RUN_TYPE = "chapter_remix"
_REMIX_CHECKPOINT_RUN_TYPES = ("audio_from_scripts", "full")
_DEFAULT_REMIX_TTS_MODEL = "qwen3-tts-instruct-flash"


def _parse_chapter_segments(chapter_audio: Any) -> List[Dict[str, Any]]:
    try:
        segments = json.loads(getattr(chapter_audio, "script_json", None) or "[]")
    except (TypeError, ValueError):
        return []
    return segments if isinstance(segments, list) else []


def _segment_audio_signature_is_current(segment: Dict[str, Any]) -> bool:
    """片段已保存音频签名是否可安全用于混音。

    只有可按当前文本、音色和表演参数精确复现的 ``current`` 签名
    才能进入整章混音。``stale`` 与 ``unverifiable`` 都按缺失处理，
    但不会删除其持久化音频文件。
    """
    return segment_audio_signature_status(segment) == "current"


def _persistent_asset_unavailable_reason(asset_ref: str) -> Optional[str]:
    if not asset_ref:
        return None
    if not is_persistent_segment_asset_ref(asset_ref):
        return "expired_temporary_audio"
    if not persistent_segment_audio_exists(asset_ref):
        return "file_missing"
    return None


def collect_chapter_remix_missing_segments(chapter_audio: Any) -> List[Dict[str, Any]]:
    """检查章节剧本中每个片段的持久化音频是否可用，返回缺失列表。

    缺失原因：未生成音频（no_audio_path）、仅剩已过期临时音频
    （expired_temporary_audio）、持久化文件不存在（file_missing）、
    音频与当前文本/音色参数不匹配（stale_audio）。
    """
    missing: List[Dict[str, Any]] = []
    segments = _parse_chapter_segments(chapter_audio)
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            missing.append(
                {
                    "index": index,
                    "speaker": "",
                    "text_preview": "",
                    "reason": "invalid_segment",
                }
            )
            continue
        item_base = {
            "index": index,
            "speaker": str(segment.get("speaker") or ""),
            "text_preview": str(segment.get("text") or "")[:40],
        }
        mix_ref = str(segment.get("mix_audio_path") or "").strip()
        mix_reason = _persistent_asset_unavailable_reason(mix_ref)
        mix_available = bool(mix_ref and mix_reason is None)
        if mix_reason:
            missing.append({**item_base, "reason": mix_reason, "asset_type": "mix"})

        if not mix_available:
            audio_ref = str(segment.get("audio_path") or "").strip()
            reason = _persistent_asset_unavailable_reason(audio_ref)
            if not audio_ref:
                reason = "no_audio_path"
            elif reason is None and not _segment_audio_signature_is_current(segment):
                reason = "stale_audio"
            if reason:
                missing.append({**item_base, "reason": reason})

            for asset_type, field in (
                ("sfx", "sfx_audio_path"),
                ("bgm", "bgm_audio_path"),
            ):
                asset_ref = str(segment.get(field) or "").strip()
                asset_reason = _persistent_asset_unavailable_reason(asset_ref)
                if asset_reason:
                    missing.append(
                        {
                            **item_base,
                            "reason": asset_reason,
                            "asset_type": asset_type,
                        }
                    )
    return missing


def _clamp_overlong_scene_loop_cues(
    timeline_container: Any,
    segment_timings: List[Dict[str, Any]],
) -> Any:
    """收束场景类循环音效的过长 duration，避免锁链等环境音从章头响到章尾。

    历史版本会把剧本标注的环境音拉伸到下一环境音/章尾；存量 checkpoint
    中已持久化的超长时长在重新混音时按所属片段结尾（+5s 宽限）收束。
    全章环境床（scene_id=ambient 等无法解析出片段索引）不受影响。
    """
    if not isinstance(timeline_container, dict):
        return timeline_container
    items = timeline_container.get("timeline")
    if not isinstance(items, list) or not items:
        return timeline_container

    ends_by_index: Dict[int, float] = {}
    for timing in segment_timings or []:
        if not isinstance(timing, dict):
            continue
        try:
            index = int(timing.get("index", len(ends_by_index)))
            end = float(timing.get("end") or 0.0)
        except (TypeError, ValueError):
            continue
        if end > 0.0:
            ends_by_index[index] = max(ends_by_index.get(index, 0.0), end)

    grace_seconds = 5.0
    fallback_max_seconds = 120.0
    for item in items:
        if not isinstance(item, dict) or not item.get("loop"):
            continue
        # 工作台手动调整的条目以用户为准，不自动收束
        if item.get("editor_timeline_key"):
            continue
        scene_index = _parse_scene_loop_cue_index(str(item.get("scene_id") or ""))
        if scene_index is None:
            continue
        try:
            start = float(item.get("timestamp") or 0.0)
            duration = float(item.get("duration") or 0.0)
        except (TypeError, ValueError):
            continue
        scene_end = ends_by_index.get(scene_index)
        limit_end = (
            scene_end + grace_seconds
            if scene_end is not None
            else start + fallback_max_seconds
        )
        if duration > max(0.0, limit_end - start):
            item["duration"] = max(0.0, limit_end - start)
    return timeline_container


def _parse_scene_loop_cue_index(scene_id: str) -> Optional[int]:
    for prefix in ("scene_", "climax_", "shift_"):
        if scene_id.startswith(prefix):
            try:
                return int(scene_id[len(prefix):])
            except ValueError:
                return None
    return None


def _rescale_timeline_for_new_duration(
    timeline_container: Any,
    *,
    old_timings: List[Dict[str, Any]],
    new_timings: List[Dict[str, Any]],
) -> Any:
    """片段时长变化后，按新旧总时长比例重锚定音效/配乐时间线。

    仅缩放 timestamp/duration；时长变化在 0.5% 以内视为未变化，原样返回。
    """
    if not isinstance(timeline_container, dict):
        return timeline_container
    items = timeline_container.get("timeline")
    if not isinstance(items, list) or not items:
        return timeline_container

    def _total_seconds(timings: List[Dict[str, Any]]) -> float:
        total = 0.0
        for timing in timings:
            if not isinstance(timing, dict):
                continue
            try:
                total = max(total, float(timing.get("end") or 0.0))
            except (TypeError, ValueError):
                continue
        return total

    old_total = _total_seconds(old_timings)
    new_total = _total_seconds(new_timings)
    if old_total <= 0.0 or new_total <= 0.0:
        return timeline_container
    factor = new_total / old_total

    def _timings_by_index(timings: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
        indexed: Dict[int, Dict[str, float]] = {}
        for fallback_index, timing in enumerate(timings):
            if not isinstance(timing, dict):
                continue
            try:
                index = int(timing.get("index", fallback_index))
                start = max(0.0, float(timing.get("start") or 0.0))
                end = float(timing.get("end") or 0.0)
                duration = float(timing.get("duration") or 0.0)
            except (TypeError, ValueError):
                continue
            if end <= start and duration > 0.0:
                end = start + duration
            indexed[index] = {
                "start": start,
                "end": max(start, end),
            }
        return indexed

    old_by_index = _timings_by_index(old_timings)
    new_by_index = _timings_by_index(new_timings)

    rescaled_items: List[Any] = []
    for item in items:
        if not isinstance(item, dict):
            rescaled_items.append(item)
            continue
        new_item = dict(item)
        segment_index = _timeline_item_segment_index(item)
        old_timing = old_by_index.get(segment_index) if segment_index is not None else None
        new_timing = new_by_index.get(segment_index) if segment_index is not None else None
        timestamp = new_item.get("timestamp")
        if old_timing and new_timing and isinstance(timestamp, (int, float)):
            relative_seconds = max(0.0, float(timestamp) - old_timing["start"])
            new_item["timestamp"] = round(new_timing["start"] + relative_seconds, 3)
        else:
            for field in ("timestamp", "duration"):
                value = new_item.get(field)
                if isinstance(value, (int, float)):
                    new_item[field] = round(float(value) * factor, 3)
        rescaled_items.append(new_item)

    rescaled = dict(timeline_container)
    rescaled["timeline"] = rescaled_items
    return rescaled


def _timeline_item_segment_index(item: Any) -> Optional[int]:
    if not isinstance(item, dict):
        return None

    for field in ("segment_index", "source_segment_index", "source_index"):
        value = item.get(field)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            pass

    scene_id = str(item.get("scene_id") or "").strip().lower()
    for prefix in ("scene_", "climax_", "shift_"):
        if scene_id.startswith(prefix):
            try:
                return int(scene_id[len(prefix):])
            except (TypeError, ValueError):
                return None

    editor_key = str(item.get("editor_timeline_key") or "").strip().lower()
    key_parts = editor_key.split("-")
    if len(key_parts) >= 2 and key_parts[0] in {"sfx", "music"}:
        try:
            return int(key_parts[1])
        except (TypeError, ValueError):
            return None
    return None


def _without_overridden_segment_timeline_items(
    timeline_container: Any,
    *,
    overridden_segment_indices: Set[int],
) -> Any:
    """移除已由工作台持久化 stem/mix 覆盖的旧 checkpoint 条目。"""
    if not overridden_segment_indices or not isinstance(timeline_container, dict):
        return timeline_container
    items = timeline_container.get("timeline")
    if not isinstance(items, list):
        return timeline_container

    filtered_items = [
        item
        for item in items
        if _timeline_item_segment_index(item) not in overridden_segment_indices
    ]
    filtered = dict(timeline_container)
    filtered["timeline"] = filtered_items
    if "total_effects" in filtered:
        filtered["total_effects"] = len(filtered_items)
    if "total_cues" in filtered:
        filtered["total_cues"] = len(filtered_items)
    return filtered


def _load_segment_remix_sources(segment: Dict[str, Any]) -> Dict[str, Any]:
    """读取片段最新持久化资产；mix 是完整片段，优先于分轨资产。"""
    def load_registered_asset(asset_ref: str) -> Optional[bytes]:
        if not asset_ref or not is_persistent_segment_asset_ref(asset_ref):
            return None
        return load_persistent_segment_audio(asset_ref)

    mix_ref = str(segment.get("mix_audio_path") or "").strip()
    sfx_ref = str(segment.get("sfx_audio_path") or "").strip()
    bgm_ref = str(segment.get("bgm_audio_path") or "").strip()

    mix_audio = load_registered_asset(mix_ref)
    if mix_audio:
        return {
            "base_audio": mix_audio,
            "sfx_audio": None,
            "bgm_audio": None,
            "uses_mix": True,
            "overrides_sfx": True,
            "overrides_bgm": True,
        }

    voice_ref = str(segment.get("audio_path") or "").strip()
    return {
        "base_audio": load_registered_asset(voice_ref),
        "sfx_audio": load_registered_asset(sfx_ref),
        "bgm_audio": load_registered_asset(bgm_ref),
        "uses_mix": False,
        # 路径存在即代表工作台已接管该轨；文件丢失时也不得回退到旧 checkpoint。
        "overrides_sfx": bool(mix_ref or sfx_ref),
        "overrides_bgm": bool(mix_ref or bgm_ref),
    }


def _compose_segment_remix_sources(mixer: Any, sources: Dict[str, Any]) -> bytes:
    base_audio = sources.get("base_audio") or b""
    if not base_audio or sources.get("uses_mix"):
        return base_audio

    sfx_audio = sources.get("sfx_audio")
    add_sound_effect = getattr(mixer, "add_sound_effect", None)
    if sfx_audio and callable(add_sound_effect):
        try:
            base_audio = add_sound_effect(
                base_audio,
                sfx_audio,
                position_ms=0,
                effect_volume_offset=0,
                ducking_enabled=False,
            )
        except Exception as exc:
            logger.warning("整章重混叠加片段持久化音效 stem 失败: %s", exc)

    bgm_audio = sources.get("bgm_audio")
    add_background_music = getattr(mixer, "add_background_music", None)
    if bgm_audio and callable(add_background_music):
        try:
            base_audio = add_background_music(
                base_audio,
                bgm_audio,
                bgm_volume_offset=0,
                position_ms=0,
                loop_fill=False,
            )
        except Exception as exc:
            logger.warning("整章重混叠加片段持久化配乐 stem 失败: %s", exc)
    return base_audio


def _create_remix_engine() -> Any:
    from app.services.audiobook import AudiobookEngine
    from core.unified_llm_client import get_llm_client

    return AudiobookEngine(
        enable_cache=False,
        max_concurrent=1,
        llm_client=get_llm_client(strategy="conservative"),
    )


def _cleanup_previous_chapter_artifacts(
    previous_audio_path: str,
    *,
    extra_paths: Optional[List[str]] = None,
) -> None:
    """尽力删除旧整章音频及其字幕产物（路径变更时调用）。"""
    from pathlib import Path

    from app.services.audiobook.background_jobs_shared import (
        build_subtitle_artifact_paths,
    )

    candidates = [previous_audio_path, *(extra_paths or [])]
    try:
        candidates.extend(build_subtitle_artifact_paths(previous_audio_path).values())
    except Exception:
        pass
    for raw_path in candidates:
        try:
            target = Path(str(raw_path))
            if not target.is_absolute():
                target = Path(__file__).resolve().parents[4] / target
            if target.is_file():
                target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("删除旧整章产物失败 path=%s error=%s", raw_path, exc)


def perform_chapter_remix(
    *,
    chapter_audio: Any,
    chapter_number: int,
    audiobook_project: Any,
    force: bool,
    output_format: str = "mp3",
    generate_subtitle: bool = True,
    engine: Any = None,
    checkpoint: Optional[Dict[str, Any]] = None,
    audio_fx: Optional[Dict[str, Any]] = None,
    run_state_updater: Optional[Callable[..., None]] = None,
    write_output: Optional[Callable[[str, bytes], None]] = None,
    before_write_output: Optional[Callable[[str, bytes], bool]] = None,
    generate_subtitle_artifacts: Optional[Callable[..., Dict[str, Any]]] = None,
    run_id: Optional[int] = None,
    on_output_ready: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """执行整章重新混音（纯逻辑，依赖注入便于测试）。

    ``run_state_updater`` 缺省时使用 task_support 的 run 状态更新（需 db 会话闭包）；
    ``write_output`` 缺省时原子写盘；``before_write_output`` 可在写盘前确认
    章节产物仍然有效；``generate_subtitle_artifacts`` 缺省时
    按 output_path 重建字幕；``run_id`` 提供时输出落 run 级路径；
    ``on_output_ready`` 在 run 置 completed 后回调（输出登记 + 发布，由调用方实现）。
    """
    from app.services.audiobook.background_jobs_shared import (
        generate_subtitle_artifacts as _default_subtitle_artifacts,
    )

    run_state_updater = run_state_updater or (lambda **kwargs: None)
    write_output = write_output or write_bytes_atomic
    generate_subtitle_artifacts = generate_subtitle_artifacts or _default_subtitle_artifacts

    segments = _parse_chapter_segments(chapter_audio)
    missing_segments = collect_chapter_remix_missing_segments(chapter_audio)

    def mark_run(status: str, *, progress: float, checkpoint_patch: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
        current_stage = (
            "completed"
            if status == "completed"
            else "cancelled"
            if status in {"cancelled", "canceled"}
            else "failed"
        )
        run_state_updater(
            run_type=CHAPTER_REMIX_RUN_TYPE,
            status=status,
            current_stage=current_stage,
            progress=progress,
            checkpoint_patch=checkpoint_patch or {},
            error_message=error_message,
        )

    if missing_segments and not force:
        logger.info("整章混音因片段缺失中止: missing=%s", [m["index"] for m in missing_segments])
        mark_run(
            "failed",
            progress=0.0,
            checkpoint_patch={"missing_segments": missing_segments},
            error_message="missing_segments",
        )
        return {
            "success": False,
            "missing_segments": missing_segments,
            "error": "missing_segments",
        }

    segment_remix_sources: List[Dict[str, Any]] = []
    overridden_sfx_segments: Set[int] = set()
    overridden_bgm_segments: Set[int] = set()
    # 强制模式下，签名过期（stale_audio）的片段不混入旧音频，按缺失处理
    stale_indices = {
        int(item.get("index"))
        for item in missing_segments
        if item.get("reason") == "stale_audio"
    }
    for segment_pos, segment in enumerate(segments):
        if not isinstance(segment, dict):
            segment_remix_sources.append({"base_audio": b""})
            continue
        sources = _load_segment_remix_sources(segment)
        if sources.get("overrides_sfx"):
            overridden_sfx_segments.add(segment_pos)
        if sources.get("overrides_bgm"):
            overridden_bgm_segments.add(segment_pos)
        if force and segment_pos in stale_indices:
            sources = dict(sources)
            sources["base_audio"] = b""
            sources["sfx_audio"] = None
            sources["bgm_audio"] = None
        segment_remix_sources.append(sources)

    if not any(source.get("base_audio") for source in segment_remix_sources):
        mark_run(
            "failed",
            progress=0.0,
            checkpoint_patch={"missing_segments": missing_segments},
            error_message="no_audio_available",
        )
        return {
            "success": False,
            "missing_segments": missing_segments,
            "error": "no_audio_available",
        }

    if engine is None:
        engine = _create_remix_engine()

    mixer = engine.audio_mixer
    audio_bytes_list = [
        _compose_segment_remix_sources(mixer, sources)
        for sources in segment_remix_sources
    ]

    apply_audio_fx = getattr(engine, "apply_audio_fx_config", None)
    if audio_fx and callable(apply_audio_fx):
        try:
            apply_audio_fx(audio_fx)
        except Exception as exc:
            logger.warning("整章混音应用音效配置失败: %s", exc)

    normalized_segments = [
        _normalize_segment(segment) if isinstance(segment, dict) else segment
        for segment in segments
    ]
    build_segment_types = getattr(engine, "_build_mixer_segment_types", None)
    segment_types = (
        build_segment_types(normalized_segments)
        if callable(build_segment_types)
        else [None] * len(audio_bytes_list)
    )
    build_pause_after_ms = getattr(engine, "_build_mixer_pause_after_ms", None)
    pause_after_ms = (
        build_pause_after_ms(normalized_segments)
        if callable(build_pause_after_ms)
        else [None] * len(audio_bytes_list)
    )

    build_segment_timeline = getattr(mixer, "build_segment_timeline", None)
    segment_timings: List[Dict[str, Any]] = []
    if callable(build_segment_timeline):
        try:
            segment_timings = build_segment_timeline(
                audio_bytes_list,
                segment_types=segment_types,
                pause_after_ms=pause_after_ms,
            )
        except TypeError:
            segment_timings = build_segment_timeline(
                audio_bytes_list,
                segment_types=segment_types,
            )
        segment_timings = segment_timings or []

    mix_chapter = getattr(mixer, "mix_chapter", None)
    if not callable(mix_chapter):
        mark_run(
            "failed",
            progress=0.0,
            checkpoint_patch={"missing_segments": missing_segments},
            error_message="mixer_unavailable",
        )
        return {"success": False, "missing_segments": missing_segments, "error": "mixer_unavailable"}
    try:
        final_audio = mix_chapter(
            audio_bytes_list,
            output_format=output_format,
            segment_types=segment_types,
            pause_after_ms=pause_after_ms,
        )
    except TypeError:
        final_audio = mix_chapter(
            audio_bytes_list,
            output_format=output_format,
            segment_types=segment_types,
        )

    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    old_segment_timings = checkpoint.get("segment_timings")
    old_segment_timings = (
        old_segment_timings if isinstance(old_segment_timings, list) else []
    )
    apply_sound_effects = getattr(engine, "_apply_sound_effects", None)
    effect_timeline = checkpoint.get("effect_timeline")
    # 片段时长变化后按新 timing 重锚定，避免音效/配乐整体错位
    if old_segment_timings and segment_timings:
        effect_timeline = _rescale_timeline_for_new_duration(
            effect_timeline,
            old_timings=old_segment_timings,
            new_timings=segment_timings,
        )
    effect_timeline = _without_overridden_segment_timeline_items(
        effect_timeline,
        overridden_segment_indices=overridden_sfx_segments,
    )
    effect_timeline = _clamp_overlong_scene_loop_cues(effect_timeline, segment_timings)
    if (
        callable(apply_sound_effects)
        and isinstance(effect_timeline, dict)
        and isinstance(effect_timeline.get("timeline"), list)
    ):
        try:
            final_audio = apply_sound_effects(final_audio, effect_timeline)
        except Exception as exc:
            logger.warning("整章混音叠加音效失败: %s", exc)

    apply_background_music = getattr(engine, "_apply_background_music", None)
    music_timeline = checkpoint.get("music_timeline")
    if old_segment_timings and segment_timings:
        music_timeline = _rescale_timeline_for_new_duration(
            music_timeline,
            old_timings=old_segment_timings,
            new_timings=segment_timings,
        )
    music_timeline = _without_overridden_segment_timeline_items(
        music_timeline,
        overridden_segment_indices=overridden_bgm_segments,
    )
    if (
        callable(apply_background_music)
        and isinstance(music_timeline, dict)
        and isinstance(music_timeline.get("timeline"), list)
    ):
        try:
            final_audio = apply_background_music(final_audio, music_timeline)
        except Exception as exc:
            logger.warning("整章混音叠加配乐失败: %s", exc)

    transcode_audio = getattr(mixer, "transcode_audio", None)
    if callable(transcode_audio):
        final_audio = transcode_audio(final_audio, output_format=output_format)

    if not final_audio:
        mark_run(
            "failed",
            progress=0.0,
            checkpoint_patch={"missing_segments": missing_segments},
            error_message="empty_mixed_audio",
        )
        return {"success": False, "missing_segments": missing_segments, "error": "empty_mixed_audio"}

    output_path = build_chapter_audio_output_path(
        project_id=getattr(audiobook_project, "project_id", None),
        chapter_number=chapter_number,
        output_format=output_format,
        audiobook_project_id=getattr(audiobook_project, "id", None),
        run_id=run_id,
    )
    if before_write_output is not None:
        try:
            can_write = bool(before_write_output(output_path, final_audio))
        except Exception as exc:
            logger.warning("写盘前章节产物校验失败: %s", exc)
            can_write = False
        if not can_write:
            mark_run(
                "cancelled",
                progress=0.0,
                checkpoint_patch={},
                error_message="chapter_audio_not_found",
            )
            return {
                "success": False,
                "error": "chapter_audio_not_found",
                "missing_segments": missing_segments,
            }
    write_output(output_path, final_audio)

    def abort_if_output_target_inactive(
        subtitle_artifacts: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """写盘后再次确认章节仍有效，并回收本次可能留下的文件。"""
        if before_write_output is None:
            return None
        try:
            still_active = bool(before_write_output(output_path, final_audio))
        except Exception as exc:
            logger.warning("写盘后章节产物校验失败: %s", exc)
            still_active = False
        if still_active:
            return None

        subtitle_path = ""
        if isinstance(subtitle_artifacts, dict):
            subtitle_path = str(subtitle_artifacts.get("subtitle_path") or "").strip()
        _cleanup_previous_chapter_artifacts(
            output_path,
            extra_paths=[subtitle_path] if subtitle_path else None,
        )
        mark_run(
            "cancelled",
            progress=0.0,
            checkpoint_patch={},
            error_message="chapter_audio_not_found",
        )
        return {
            "success": False,
            "error": "chapter_audio_not_found",
            "missing_segments": missing_segments,
        }

    post_write_abort = abort_if_output_target_inactive()
    if post_write_abort is not None:
        return post_write_abort

    # 输出路径变化时回收旧整章音频与字幕产物，避免孤儿文件
    previous_audio_path = str(getattr(chapter_audio, "audio_path", "") or "").strip()
    if previous_audio_path and previous_audio_path != output_path:
        _cleanup_previous_chapter_artifacts(previous_audio_path)

    get_audio_info = getattr(mixer, "get_audio_info", None)
    audio_info = get_audio_info(final_audio) if callable(get_audio_info) else {}
    duration_seconds = float((audio_info or {}).get("duration_seconds") or 0.0)

    subtitle_artifacts: Dict[str, Any] = {"generated": False, "reason": "disabled_by_request"}
    if generate_subtitle and segment_timings:
        subtitle_artifacts = generate_subtitle_artifacts(
            script_segments=normalized_segments,
            segment_timings=segment_timings,
            output_path=output_path,
            title=f"Chapter {chapter_number}",
        ) or subtitle_artifacts
        if subtitle_artifacts.get("generated"):
            subtitle_artifacts["subtitle_format"] = subtitle_artifacts.get("subtitle_format") or "srt"

    post_subtitle_abort = abort_if_output_target_inactive(subtitle_artifacts)
    if post_subtitle_abort is not None:
        return post_subtitle_abort

    checkpoint_patch = {
        "output_path": output_path,
        "segment_timings": segment_timings,
        "subtitle_artifacts": subtitle_artifacts,
    }
    if effect_timeline:
        checkpoint_patch["effect_timeline"] = effect_timeline
    if music_timeline:
        checkpoint_patch["music_timeline"] = music_timeline
    if missing_segments:
        checkpoint_patch["missing_segments"] = missing_segments

    # 终态写回必须先于 on_output_ready：发布协议谓词要求 run.status=completed，
    # 顺序颠倒会让 publish_legacy_chapter_output 永远命中 run_not_completed
    mark_run("completed", progress=1.0, checkpoint_patch=checkpoint_patch)

    # §1.5/R8：不再直写 ChapterAudio 镜像列——输出登记（staged）与发布由
    # on_output_ready 回调经发布事务完成（镜像列只由发布事务改写）
    if on_output_ready is not None:
        try:
            on_output_ready(
                {
                    "output_path": output_path,
                    "duration": duration_seconds,
                    "file_size": len(final_audio),
                    "subtitle_artifacts": subtitle_artifacts,
                    "segment_timings": segment_timings,
                    "missing_segments": missing_segments,
                }
            )
        except Exception as exc:
            logger.error("整章混音输出登记/发布失败: %s", exc)

    logger.info(
        "✅ 整章重新混音完成: chapter_id=%s duration=%.1fs segments=%d missing=%d",
        getattr(chapter_audio, "id", None),
        duration_seconds,
        len(audio_bytes_list),
        len(missing_segments),
    )
    return {
        "success": True,
        "output_path": output_path,
        "duration": duration_seconds,
        "file_size": len(final_audio),
        "segment_timings": segment_timings,
        "missing_segments": missing_segments,
    }


def _normalize_segment(segment: Dict[str, Any]) -> Any:
    from types import SimpleNamespace

    try:
        return SimpleNamespace(**segment)
    except TypeError:
        return segment


def _resolve_checkpoint_run_type(db: Session, *, audiobook_project_id: int, chapter_id: int) -> Optional[Dict[str, Any]]:
    for run_type in _REMIX_CHECKPOINT_RUN_TYPES:
        checkpoint = get_latest_run_checkpoint_json(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
        )
        if isinstance(checkpoint, dict) and checkpoint:
            return checkpoint
    return None


def run_chapter_remix_background(
    *,
    audiobook_project_id: int,
    chapter_id: int,
    force: bool,
    output_format: str = "mp3",
    generate_subtitle: bool = True,
    run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """后台执行整章重新混音（由端点 BackgroundTasks 触发）。

    ``run_id`` 为路由预创建的运行记录 ID，所有状态更新按该 ID 定向
    写入，避免与其他并发任务互相覆盖。
    """
    db: Session = SessionLocal()
    try:
        chapter_audio = (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == audiobook_project_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .first()
        )
        if chapter_audio is None:
            # 章节产物在排队期间被删除：把已置为 running 的 run 标记为取消，
            # 避免前端长期停留在“混音中”
            if run_id is not None:
                try:
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type=CHAPTER_REMIX_RUN_TYPE,
                        status="cancelled",
                        current_stage="cancelled",
                        progress=0.0,
                        run_id=run_id,
                        error_message="chapter_audio_not_found",
                    )
                    db.commit()
                except Exception:
                    db.rollback()
            return {"success": False, "error": "chapter_audio_not_found"}

        audiobook_project = (
            db.query(AudiobookProject)
            .filter(AudiobookProject.id == audiobook_project_id)
            .first()
        )
        chapter_number = 1
        try:
            chapter_number = int(getattr(chapter_audio.chapter, "chapter_number", None) or 1)
        except (TypeError, ValueError):
            pass

        checkpoint = _resolve_checkpoint_run_type(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )

        audio_fx: Optional[Dict[str, Any]] = None
        try:
            from app.services.audiobook.project_audio_config import (
                parse_engine_config_snapshot,
            )
            from app.services.audiobook.project_audio_runtime import (
                resolve_from_snapshot,
            )

            # §1.5：从批次快照解析运行时配置（冻结事实，不读实时可变配置）
            batch_snapshot = parse_engine_config_snapshot(
                getattr(audiobook_project, "engine_config_snapshot", None)
            )
            if batch_snapshot:
                runtime_config = resolve_from_snapshot(
                    batch_snapshot,
                    tts_model=_DEFAULT_REMIX_TTS_MODEL,
                )
            else:
                # 无批次快照（legacy_unverified 等）：回退实时解析（读兼容）
                project = (
                    db.query(Project)
                    .filter(Project.id == audiobook_project.project_id)
                    .first()
                )
                runtime_config = resolve_project_audio_runtime_config(
                    project=project,
                    tts_model=_DEFAULT_REMIX_TTS_MODEL,
                    base_voice_mapping=getattr(audiobook_project, "voice_mapping", None) or {},
                )
            audio_fx = getattr(runtime_config, "audio_fx", None) or None
        except Exception as exc:
            logger.warning("整章混音解析项目音效配置失败: %s", exc)

        def chapter_audio_is_active() -> bool:
            """读取最新行，避免删除后继续写出章节产物。"""
            with db.no_autoflush:
                fresh_chapter_audio = (
                    db.query(ChapterAudio)
                    .filter(
                        ChapterAudio.id == chapter_audio.id,
                        ChapterAudio.audiobook_project_id == audiobook_project_id,
                        ChapterAudio.chapter_id == chapter_id,
                        ChapterAudio.deleted_at.is_(None),
                    )
                    .populate_existing()
                    .first()
                )
            if fresh_chapter_audio is None:
                return False
            if run_id is not None:
                with db.no_autoflush:
                    current_run = (
                        db.query(ChapterAudioRun)
                        .filter(ChapterAudioRun.id == run_id)
                        .populate_existing()
                        .first()
                    )
                if current_run is not None and str(current_run.status or "") in {
                    "cancelled",
                    "canceled",
                }:
                    return False
            return True

        def run_state_updater(**kwargs: Any) -> None:
            requested_status = str(kwargs.get("status") or "")
            if requested_status not in {"cancelled", "canceled"} and not chapter_audio_is_active():
                logger.info(
                    "章节产物已删除，忽略重混音状态更新: audiobook_project_id=%s chapter_id=%s status=%s",
                    audiobook_project_id,
                    chapter_id,
                    requested_status,
                )
                return
            _update_chapter_run_state(
                db,
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                run_id=run_id,
                **kwargs,
            )

        def on_output_ready(output_info: Dict[str, Any]) -> None:
            """run 置 completed 后登记 staged 输出并执行 legacy 发布协议（§1.5/R8）。

            与 run 终态写回同事务：upsert ChapterAudioOutput（staged）→
            publish_legacy_chapter_output（CAS 镜像列 + supersede 旧输出）。
            """
            if run_id is None:
                return
            from app.services.audiobook.chapter_output_publish import (
                publish_legacy_chapter_output,
                upsert_staged_chapter_output,
            )

            try:
                # 补全 run 运行作用域（历史/直建 run 可能缺 chapter_audio_id）
                current_run = (
                    db.query(ChapterAudioRun)
                    .filter(ChapterAudioRun.id == run_id)
                    .first()
                )
                if current_run is not None and current_run.chapter_audio_id is None:
                    current_run.chapter_audio_id = chapter_audio.id
                    db.flush()

                # remix 端点预创建 run 时不推进 desired_run_id（仅派发流程推进），
                # 而发布 CAS 要求 desired_run_id == run_id；产物就绪即推进。
                # 单调守卫：desired 已指向更新（id 更大）的 run 时不抢占，
                # 避免晚完成的旧 remix 覆盖新任务的发布权
                if chapter_audio.desired_run_id != run_id and (
                    chapter_audio.desired_run_id is None
                    or chapter_audio.desired_run_id < run_id
                ):
                    chapter_audio.desired_run_id = run_id
                    db.flush()

                subtitle_artifacts = output_info.get("subtitle_artifacts") or {}
                subtitle_path = (
                    str(subtitle_artifacts.get("subtitle_path") or "").strip()
                    if subtitle_artifacts.get("generated")
                    else None
                )
                upsert_staged_chapter_output(
                    db,
                    run_id=run_id,
                    chapter_audio_id=chapter_audio.id,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    audio_path=output_info.get("output_path") or "",
                    duration=output_info.get("duration"),
                    file_size=output_info.get("file_size"),
                    subtitle_path=subtitle_path,
                    subtitle_format=(
                        str(subtitle_artifacts.get("subtitle_format") or "srt")
                        if subtitle_path
                        else None
                    ),
                )
                publish_result = publish_legacy_chapter_output(
                    db,
                    run_id=run_id,
                    chapter_audio_id=chapter_audio.id,
                    render_status="completed",
                )
                logger.info(
                    "整章混音发布结果: %s", publish_result,
                )
            except Exception as exc:
                logger.error("整章混音输出登记/发布异常: %s", exc)

        result = perform_chapter_remix(
            chapter_audio=chapter_audio,
            chapter_number=chapter_number,
            audiobook_project=audiobook_project,
            force=force,
            output_format=output_format,
            generate_subtitle=generate_subtitle,
            checkpoint=checkpoint,
            audio_fx=audio_fx,
            run_state_updater=run_state_updater,
            before_write_output=lambda _path, _data: chapter_audio_is_active(),
            run_id=run_id,
            on_output_ready=on_output_ready,
        )
        if result.get("error") == "chapter_audio_not_found":
            # 章节可能在写盘竞态中被软删除；不要把会话中残留的对象变更刷回数据库。
            db.rollback()
        else:
            db.commit()
        return result
    except Exception as exc:
        logger.error("❌ 整章重新混音失败: %s", exc)
        try:
            _update_chapter_run_state(
                db,
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                run_type=CHAPTER_REMIX_RUN_TYPE,
                status="failed",
                current_stage="failed",
                progress=0.0,
                run_id=run_id,
                error_message=str(exc),
            )
            db.commit()
        except Exception:
            db.rollback()
        return {"success": False, "error": str(exc)}
    finally:
        db.close()


__all__ = [
    "CHAPTER_REMIX_RUN_TYPE",
    "collect_chapter_remix_missing_segments",
    "perform_chapter_remix",
    "run_chapter_remix_background",
]
