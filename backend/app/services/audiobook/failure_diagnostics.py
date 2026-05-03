from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.utils.datetime_utils import utc_now


FAILURE_DIAGNOSTIC_SCHEMA_VERSION = 1
DEFAULT_TEXT_PREVIEW_CHARS = 160
MAX_ERROR_MESSAGE_CHARS = 1000


def clip_text_preview(text: Any, max_chars: int = DEFAULT_TEXT_PREVIEW_CHARS) -> str:
    normalized = " ".join(str(text or "").split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    raw_dict = getattr(value, "__dict__", None)
    if isinstance(raw_dict, dict):
        return {
            key: item
            for key, item in raw_dict.items()
            if isinstance(key, str) and not key.startswith("_")
        }
    return {}


def _get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _safe_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except Exception:
        return None
    if number < 0:
        return None
    return number


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _iter_index_values(values: Any) -> Iterable[int]:
    if isinstance(values, dict):
        raw_values = values.keys()
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    seen: set[int] = set()
    for raw_value in raw_values:
        index = _safe_int(raw_value)
        if index is None or index in seen:
            continue
        seen.add(index)
        yield index


def _extract_indices_from_segments(segments: Any) -> List[int]:
    if not isinstance(segments, dict):
        return []
    indices: List[int] = []
    seen: set[int] = set()
    for raw_key, raw_segment in segments.items():
        segment = raw_segment if isinstance(raw_segment, dict) else {}
        index = _safe_int(segment.get("index", raw_key))
        if index is None or index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return sorted(indices)


def _extract_temp_cache(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    temp_segment_cache = payload.get("temp_segment_cache")
    return dict(temp_segment_cache) if isinstance(temp_segment_cache, dict) else {}


def _extract_completed_segment_indices(
    *,
    result: Optional[Dict[str, Any]],
    checkpoint: Optional[Dict[str, Any]],
) -> List[int]:
    indices: set[int] = set()
    sources: List[Dict[str, Any]] = []

    if isinstance(checkpoint, dict):
        sources.append(checkpoint)
    if isinstance(result, dict):
        sources.append(result)
        stats = result.get("stats")
        if isinstance(stats, dict):
            sources.append(stats)
        temp_cache = _extract_temp_cache(result)
        if temp_cache:
            sources.append(temp_cache)

    for source in sources:
        for index in _iter_index_values(source.get("completed_segment_indices")):
            indices.add(index)
        for index in _iter_index_values(source.get("cached_audio_paths")):
            indices.add(index)
        for index in _extract_indices_from_segments(source.get("segments")):
            indices.add(index)

    return sorted(indices)


def _count_cached_segments(
    *,
    result: Optional[Dict[str, Any]],
    checkpoint: Optional[Dict[str, Any]],
) -> int:
    temp_cache = _extract_temp_cache(result)
    for source in (temp_cache, checkpoint if isinstance(checkpoint, dict) else {}):
        cached_paths = source.get("cached_audio_paths") if isinstance(source, dict) else None
        if isinstance(cached_paths, dict) and cached_paths:
            return len(list(_iter_index_values(cached_paths)))
        segments = source.get("segments") if isinstance(source, dict) else None
        if isinstance(segments, dict) and segments:
            return len(_extract_indices_from_segments(segments))
    return 0


def _extract_render_plan(
    *,
    result: Optional[Dict[str, Any]],
    checkpoint: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    for source in (_extract_temp_cache(result), checkpoint if isinstance(checkpoint, dict) else {}):
        render_plan = source.get("render_plan") if isinstance(source, dict) else None
        if isinstance(render_plan, list):
            return [
                dict(item)
                for item in render_plan
                if isinstance(item, dict)
            ]
    return []


def _resolve_total_render_segments(
    *,
    script_segments: List[Any],
    result: Optional[Dict[str, Any]],
    checkpoint: Optional[Dict[str, Any]],
    render_plan: List[Dict[str, Any]],
) -> int:
    candidates: List[Any] = []
    temp_cache = _extract_temp_cache(result)
    candidates.extend(
        [
            temp_cache.get("render_chunk_count"),
            temp_cache.get("total_segments"),
            checkpoint.get("render_chunk_count") if isinstance(checkpoint, dict) else None,
            checkpoint.get("total_segments") if isinstance(checkpoint, dict) else None,
        ]
    )
    if isinstance(result, dict):
        candidates.append(result.get("total_segments"))
        stats = result.get("stats")
        if isinstance(stats, dict):
            candidates.append(stats.get("total_segments"))
            parse_stats = stats.get("parse_stats")
            if isinstance(parse_stats, dict):
                candidates.append(parse_stats.get("total_segments"))

    for candidate in candidates:
        total = _safe_int(candidate)
        if total is not None and total > 0:
            return total
    if render_plan:
        return len(render_plan)
    return len(script_segments)


def _extract_explicit_failed_index(result: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(result, dict):
        return None

    candidate_keys = (
        "failed_render_chunk_index",
        "failed_segment_index",
        "segment_index",
        "utterance_index",
    )
    for key in candidate_keys:
        index = _safe_int(result.get(key))
        if index is not None:
            return index

    for nested_key in ("error_context", "failed_segment", "failed_utterance"):
        nested = result.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in candidate_keys:
            index = _safe_int(nested.get(key))
            if index is not None:
                return index

    return None


def _infer_failed_render_chunk_index(
    *,
    result: Optional[Dict[str, Any]],
    completed_indices: List[int],
    total_render_segments: int,
) -> Optional[int]:
    explicit_index = _extract_explicit_failed_index(result)
    if explicit_index is not None:
        return explicit_index

    if total_render_segments <= 0:
        return None
    completed = set(completed_indices)
    for index in range(total_render_segments):
        if index not in completed:
            return index
    return None


def _source_segment_indices_for_render_chunk(
    *,
    render_plan: List[Dict[str, Any]],
    render_chunk_index: Optional[int],
    script_segment_count: int,
) -> List[int]:
    if render_chunk_index is None:
        return []

    for entry in render_plan:
        entry_index = _safe_int(entry.get("index"))
        if entry_index != render_chunk_index:
            continue
        raw_source_indices = entry.get("source_segment_indices")
        indices = list(_iter_index_values(raw_source_indices))
        return [
            index
            for index in indices
            if index < script_segment_count
        ]

    if render_chunk_index < script_segment_count:
        return [render_chunk_index]
    return []


def _voice_identifier_from_segment(segment: Any) -> str:
    data = _as_mapping(segment)
    voice_params = data.get("voice_params")
    if not isinstance(voice_params, dict):
        voice_params = {}
    for key in (
        "voice_id",
        "speaker_id",
        "speaker",
        "voice",
        "voice_name",
        "provider_voice_id",
    ):
        value = _safe_str(voice_params.get(key) or data.get(key))
        if value:
            return value
    return ""


def _build_failed_segment_context(
    *,
    script_segments: List[Any],
    source_segment_indices: List[int],
) -> Optional[Dict[str, Any]]:
    if not source_segment_indices:
        return None

    index = source_segment_indices[0]
    if index < 0 or index >= len(script_segments):
        return None

    segment = script_segments[index]
    return {
        "index": index,
        "speaker": _safe_str(_get_value(segment, "speaker")),
        "emotion": _safe_str(
            _get_value(segment, "instruct_emotion")
            or _get_value(segment, "emotion")
        ),
        "type": _safe_str(_get_value(segment, "type")),
        "text_preview": clip_text_preview(_get_value(segment, "text")),
        "voice_id": _voice_identifier_from_segment(segment),
    }


def _error_message_from(
    *,
    result: Optional[Dict[str, Any]],
    exception: Optional[BaseException],
) -> str:
    if exception is not None:
        return clip_text_preview(str(exception), MAX_ERROR_MESSAGE_CHARS)
    if isinstance(result, dict):
        return clip_text_preview(result.get("error") or "unknown_error", MAX_ERROR_MESSAGE_CHARS)
    return "unknown_error"


def _error_type_from(
    *,
    result: Optional[Dict[str, Any]],
    exception: Optional[BaseException],
) -> str:
    if exception is not None:
        return type(exception).__name__
    if isinstance(result, dict):
        for key in ("error_type", "exception_type"):
            value = _safe_str(result.get(key))
            if value:
                return value
    return ""


def build_chapter_failure_diagnostic(
    *,
    stage: str,
    chapter_id: int,
    chapter_title: Optional[str] = None,
    chapter_number: Optional[int] = None,
    script_segments: Optional[Iterable[Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    exception: Optional[BaseException] = None,
    resume_checkpoint: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    segment_list = list(script_segments or [])
    checkpoint = dict(resume_checkpoint or {}) if isinstance(resume_checkpoint, dict) else {}
    render_plan = _extract_render_plan(result=result, checkpoint=checkpoint)
    completed_indices = _extract_completed_segment_indices(
        result=result,
        checkpoint=checkpoint,
    )
    total_render_segments = _resolve_total_render_segments(
        script_segments=segment_list,
        result=result,
        checkpoint=checkpoint,
        render_plan=render_plan,
    )
    failed_render_chunk_index = _infer_failed_render_chunk_index(
        result=result,
        completed_indices=completed_indices,
        total_render_segments=total_render_segments,
    )
    source_segment_indices = _source_segment_indices_for_render_chunk(
        render_plan=render_plan,
        render_chunk_index=failed_render_chunk_index,
        script_segment_count=len(segment_list),
    )
    failed_segment = _build_failed_segment_context(
        script_segments=segment_list,
        source_segment_indices=source_segment_indices,
    )
    resolved_task_id = (
        _safe_str(task_id)
        or _safe_str(result.get("task_id") if isinstance(result, dict) else None)
        or _safe_str(checkpoint.get("engine_task_id"))
    )

    diagnostic: Dict[str, Any] = {
        "schema_version": FAILURE_DIAGNOSTIC_SCHEMA_VERSION,
        "stage": _safe_str(stage),
        "chapter_id": chapter_id,
        "chapter_title": _safe_str(chapter_title),
        "chapter_number": _safe_int(chapter_number),
        "error_message": _error_message_from(result=result, exception=exception),
        "error_type": _error_type_from(result=result, exception=exception),
        "failed_render_chunk_index": failed_render_chunk_index,
        "failed_segment_index": source_segment_indices[0] if source_segment_indices else None,
        "failed_source_segment_indices": source_segment_indices,
        "failed_segment": failed_segment,
        "completed_segment_count": len(completed_indices),
        "completed_segment_indices": completed_indices,
        "cached_segment_count": _count_cached_segments(result=result, checkpoint=checkpoint),
        "total_segment_count": total_render_segments,
        "script_segment_count": len(segment_list),
        "engine_task_id": resolved_task_id or None,
        "generated_at": utc_now().isoformat(),
    }
    return diagnostic


def attach_failure_diagnostic_to_checkpoint_patch(
    checkpoint_patch: Optional[Dict[str, Any]],
    diagnostic: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    patch = dict(checkpoint_patch or {})
    if not isinstance(diagnostic, dict) or not diagnostic:
        return patch

    patch["failure_diagnostic"] = diagnostic
    failed_index = _safe_int(diagnostic.get("failed_render_chunk_index"))
    if failed_index is None:
        return patch

    failed_indices = set(_iter_index_values(patch.get("failed_segment_indices")))
    failed_indices.add(failed_index)
    patch["failed_segment_indices"] = sorted(failed_indices)
    return patch


__all__ = [
    "FAILURE_DIAGNOSTIC_SCHEMA_VERSION",
    "attach_failure_diagnostic_to_checkpoint_patch",
    "build_chapter_failure_diagnostic",
    "clip_text_preview",
]
