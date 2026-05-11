from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, Iterable, List, Optional

from .pause_tags import split_pause_tag_text


RENDER_PLAN_VERSION = 1
DEFAULT_RENDER_CHUNK_MAX_CHARS = 420
MIN_RENDER_CHUNK_MAX_CHARS = 80

_SENTENCE_BOUNDARIES = set("。！？!?")
_PHRASE_BOUNDARIES = set("，,、；;：:—–")
_CLOSING_PUNCTUATION = set("\"'”’）】》」』")


@dataclass(frozen=True)
class RenderChunk:
    index: int
    render_id: str
    source_segment_indices: List[int]
    text: str
    speaker: str
    emotion: str
    voice_params: Dict[str, Any]
    segment_type: str = ""
    performance_notes: str = ""
    cache_key: str = ""
    text_hash: str = ""


def build_render_plan(
    script_segments: Iterable[Any],
    *,
    max_chunk_chars: Optional[int] = None,
) -> List[RenderChunk]:
    chunks: List[RenderChunk] = []
    chunk_char_limit = _resolve_chunk_char_limit(max_chunk_chars)
    for index, segment in enumerate(list(script_segments or [])):
        original_text = str(getattr(segment, "text", "") or "")
        pause_parts = split_pause_tag_text(original_text)
        pause_tag_applied = any(part.applied for part in pause_parts)
        voice_params = _segment_voice_params(segment)
        if pause_tag_applied:
            voice_params.setdefault("original_tts_text", original_text)
            voice_params["pause_tag_applied"] = True
        performance_notes = str(getattr(segment, "performance_notes", "") or "").strip()
        if performance_notes:
            voice_params.setdefault("performance_notes", performance_notes)

        speaker = str(getattr(segment, "speaker", "") or voice_params.get("segment_speaker") or "").strip()
        emotion = str(
            getattr(segment, "instruct_emotion", "")
            or getattr(segment, "emotion", "")
            or voice_params.get("instruct_emotion")
            or voice_params.get("emotion")
            or "neutral"
        ).strip() or "neutral"
        segment_type = str(getattr(segment, "type", "") or voice_params.get("segment_type") or "").strip()

        render_text_parts: List[tuple[str, Optional[int]]] = []
        if not pause_parts:
            render_text_parts.append(("", None))
        for pause_part in pause_parts:
            text_parts = split_render_text(pause_part.text, max_chars=chunk_char_limit) or [""]
            for text_part_index, chunk_text in enumerate(text_parts):
                pause_after_ms = (
                    pause_part.pause_after_ms
                    if text_part_index == len(text_parts) - 1
                    else None
                )
                render_text_parts.append((chunk_text, pause_after_ms))

        total_parts = len(render_text_parts)
        for source_chunk_index, (chunk_text, pause_after_ms) in enumerate(render_text_parts):
            chunk_voice_params = _voice_params_for_chunk(
                voice_params,
                source_index=index,
                source_chunk_index=source_chunk_index,
                source_chunk_count=total_parts,
                chunk_text=chunk_text,
            )
            if pause_after_ms is not None:
                chunk_voice_params["pause_after_ms"] = pause_after_ms
            chunk_index = len(chunks)
            text_hash = _hash_text(chunk_text)
            cache_key = _build_cache_key(
                text=chunk_text,
                speaker=speaker,
                emotion=emotion,
                voice_params=chunk_voice_params,
                segment_type=segment_type,
                performance_notes=performance_notes,
            )
            chunks.append(
                RenderChunk(
                    index=chunk_index,
                    render_id=f"chunk_{chunk_index:05d}_{cache_key[:12]}",
                    source_segment_indices=[index],
                    text=chunk_text,
                    speaker=speaker,
                    emotion=emotion,
                    voice_params=chunk_voice_params,
                    segment_type=segment_type,
                    performance_notes=performance_notes,
                    cache_key=cache_key,
                    text_hash=text_hash,
                )
            )
    return chunks


def render_plan_to_payload(render_chunks: Iterable[RenderChunk]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for chunk in render_chunks or []:
        payload.append(
            {
                "index": int(chunk.index),
                "render_id": chunk.render_id,
                "source_segment_indices": list(chunk.source_segment_indices or []),
                "cache_key": chunk.cache_key,
                "text_hash": chunk.text_hash,
                "speaker": chunk.speaker,
                "emotion": chunk.emotion,
                "segment_type": chunk.segment_type,
                "char_count": len(chunk.text or ""),
                "text_preview": (chunk.text or "")[:80],
            }
        )
    return payload


def render_chunks_to_timing_segments_payload(render_chunks: Iterable[RenderChunk]) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    for chunk in render_chunks or []:
        voice_params = dict(chunk.voice_params or {})
        payload.append(
            {
                "type": chunk.segment_type or voice_params.get("segment_type") or "narration",
                "text": chunk.text or "",
                "speaker": chunk.speaker or voice_params.get("segment_speaker") or "旁白",
                "emotion": chunk.emotion or voice_params.get("emotion") or "neutral",
                "performance_notes": chunk.performance_notes or voice_params.get("performance_notes") or "",
                "voice_params": voice_params,
                "source_segment_indices": list(chunk.source_segment_indices or []),
                "render_chunk_index": int(chunk.index),
            }
        )
    return payload


def split_render_text(text: str, *, max_chars: Optional[int] = None) -> List[str]:
    source = str(text or "")
    if not source:
        return []
    char_limit = _resolve_chunk_char_limit(max_chars)
    if char_limit <= 0 or len(source) <= char_limit:
        return [source]

    units = _split_text_units(source)
    chunks: List[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if len(unit) > char_limit:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_unit(unit, char_limit))
            continue
        if current and len(current) + len(unit) > char_limit:
            chunks.append(current.strip())
            current = unit.lstrip()
        else:
            current += unit
    if current.strip():
        chunks.append(current.strip())
    return chunks or [source]


def extract_render_signatures(checkpoint_data: Optional[Dict[str, Any]]) -> Dict[int, str]:
    checkpoint = dict(checkpoint_data or {})
    render_plan = checkpoint.get("render_plan") or []
    if isinstance(render_plan, dict):
        render_plan = list(render_plan.values())
    if not isinstance(render_plan, list):
        return {}

    signatures: Dict[int, str] = {}
    for item in render_plan:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError, OverflowError):
            continue
        if index < 0:
            continue
        cache_key = str(item.get("cache_key") or "").strip()
        if cache_key:
            signatures[index] = cache_key
    return signatures


def _segment_voice_params(segment: Any) -> Dict[str, Any]:
    raw_params = getattr(segment, "voice_params", None)
    if not isinstance(raw_params, dict):
        return {}
    return _jsonable_dict(raw_params)


def _build_cache_key(
    *,
    text: str,
    speaker: str,
    emotion: str,
    voice_params: Dict[str, Any],
    segment_type: str,
    performance_notes: str,
) -> str:
    signature_payload = {
        "version": RENDER_PLAN_VERSION,
        "text": text,
        "speaker": speaker,
        "emotion": emotion,
        "voice_params": _signature_voice_params(voice_params),
        "segment_type": segment_type,
        "performance_notes": performance_notes,
    }
    serialized = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _signature_voice_params(voice_params: Dict[str, Any]) -> Dict[str, Any]:
    ignored_keys = {
        "mixer_segment_type",
        "pause_before",
        "pause_after",
        "pause_after_ms",
        "pause_tag_applied",
        "original_tts_text",
        "normalized_text_applied",
        "render_chunk_split",
        "render_chunk_reason",
        "source_chunk_count",
        "source_chunk_index",
        "source_segment_index",
    }
    return {
        key: value
        for key, value in sorted(_jsonable_dict(voice_params).items())
        if key not in ignored_keys
    }


def _hash_text(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:12]


def _voice_params_for_chunk(
    voice_params: Dict[str, Any],
    *,
    source_index: int,
    source_chunk_index: int,
    source_chunk_count: int,
    chunk_text: str,
) -> Dict[str, Any]:
    chunk_params = dict(voice_params or {})
    if source_chunk_count <= 1:
        return chunk_params

    chunk_params["render_chunk_split"] = True
    chunk_params["source_segment_index"] = int(source_index)
    chunk_params["source_chunk_index"] = int(source_chunk_index)
    chunk_params["source_chunk_count"] = int(source_chunk_count)
    chunk_params["render_chunk_reason"] = _infer_mixer_segment_type(chunk_text)
    chunk_params["mixer_segment_type"] = chunk_params["render_chunk_reason"]

    if source_chunk_index > 0:
        chunk_params.pop("pause_before", None)
    if source_chunk_index < source_chunk_count - 1:
        chunk_params.pop("pause_after", None)
        chunk_params.pop("pause_after_ms", None)

    return chunk_params


def _infer_mixer_segment_type(text: str) -> str:
    stripped = str(text or "").rstrip()
    if not stripped:
        return "sentence"
    last = stripped[-1]
    if last in _SENTENCE_BOUNDARIES:
        return "sentence"
    if last in _PHRASE_BOUNDARIES:
        return "phrase"
    return "phrase"


def _split_text_units(text: str) -> List[str]:
    units: List[str] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        is_boundary = char in _SENTENCE_BOUNDARIES or char in _PHRASE_BOUNDARIES or char in {"\n", "\r"}
        if not is_boundary:
            index += 1
            continue

        end = index + 1
        while end < len(text) and text[end] in _CLOSING_PUNCTUATION:
            end += 1
        while end < len(text) and text[end].isspace():
            end += 1
        units.append(text[start:end])
        start = end
        index = end

    if start < len(text):
        units.append(text[start:])
    return units or [text]


def _split_long_unit(text: str, max_chars: int) -> List[str]:
    remaining = str(text or "").strip()
    if not remaining:
        return []

    chunks: List[str] = []
    while len(remaining) > max_chars:
        cut_index = _find_safe_cut_index(remaining, max_chars)
        chunks.append(remaining[:cut_index].strip())
        remaining = remaining[cut_index:].lstrip()
    if remaining:
        chunks.append(remaining.strip())
    return chunks


def _find_safe_cut_index(text: str, max_chars: int) -> int:
    lower_bound = max(1, min(max_chars // 2, max_chars - 1))
    window = text[:max_chars]
    for pattern in (r"[，,、；;：:—–]", r"\s+"):
        matches = list(re.finditer(pattern, window))
        for match in reversed(matches):
            if match.end() >= lower_bound:
                return match.end()
    return max_chars


def _resolve_chunk_char_limit(value: Optional[int]) -> int:
    candidate = value
    if candidate is None:
        raw_env = os.getenv("AUDIOBOOK_RENDER_CHUNK_MAX_CHARS")
        if raw_env is not None:
            try:
                candidate = int(raw_env)
            except (TypeError, ValueError, OverflowError):
                candidate = None
    if candidate is None:
        candidate = DEFAULT_RENDER_CHUNK_MAX_CHARS
    try:
        resolved = int(candidate)
    except (TypeError, ValueError, OverflowError):
        resolved = DEFAULT_RENDER_CHUNK_MAX_CHARS
    if resolved <= 0:
        return 0
    return max(MIN_RENDER_CHUNK_MAX_CHARS, resolved)


def _jsonable_dict(value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        str(key): _jsonable(raw_value)
        for key, raw_value in dict(value or {}).items()
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(raw_value) for key, raw_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = [
    "DEFAULT_RENDER_CHUNK_MAX_CHARS",
    "MIN_RENDER_CHUNK_MAX_CHARS",
    "RENDER_PLAN_VERSION",
    "RenderChunk",
    "build_render_plan",
    "extract_render_signatures",
    "render_plan_to_payload",
    "render_chunks_to_timing_segments_payload",
    "split_render_text",
]
