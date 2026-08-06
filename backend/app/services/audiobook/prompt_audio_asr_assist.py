from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.models.audiobook import ChapterAudio
from app.services.audiobook.stt_verifier import STTVerifier
from app.services.audiobook.voice_identity_policy import (
    is_current_voice_identity_snapshot,
)


def _is_truthy(value: Any) -> bool:
    return value is True or (
        isinstance(value, str)
        and value.strip().lower() in {"1", "true", "yes"}
    )


def _load_script_segments(chapter_audio: ChapterAudio) -> List[Dict[str, Any]]:
    raw_script = str(getattr(chapter_audio, "script_json", "") or "").strip()
    if not raw_script:
        return []

    try:
        payload = json.loads(raw_script)
    except (json.JSONDecodeError, TypeError):
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("segments", "script_segments", "script"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _segment_voice_params(segment: Dict[str, Any]) -> Dict[str, Any]:
    voice_params = segment.get("voice_params")
    return voice_params if isinstance(voice_params, dict) else {}


def _current_segment_snapshot(segment: Dict[str, Any]) -> Dict[str, Any]:
    voice_params = _segment_voice_params(segment)
    snapshot = voice_params.get("provider_prompt_snapshot")
    expected_model = str(
        voice_params.get("resolved_tts_model")
        or voice_params.get("tts_model")
        or segment.get("tts_model")
        or ""
    ).strip()
    expected_voice = str(
        voice_params.get("speaker") or voice_params.get("voice_id") or ""
    ).strip()
    if not is_current_voice_identity_snapshot(
        snapshot,
        model=expected_model or None,
        voice_id=expected_voice or None,
    ):
        return {}
    return dict(snapshot)


def _segment_model(segment: Dict[str, Any]) -> str:
    voice_params = _segment_voice_params(segment)
    snapshot = _current_segment_snapshot(segment)
    if snapshot:
        model = str(snapshot.get("model") or "").strip()
        if model:
            return model
    for key in ("resolved_tts_model", "tts_model"):
        model = str(voice_params.get(key) or "").strip()
        if model:
            return model
    return str(segment.get("tts_model") or "").strip()


def _segment_inline_tag_strategy(segment: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = _current_segment_snapshot(segment)
    provider_prompt = snapshot.get("provider_prompt") if snapshot else None
    strategy = provider_prompt.get("inline_tag_strategy") if isinstance(provider_prompt, dict) else None
    return strategy if isinstance(strategy, dict) else {}


def _collect_tags(strategy: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    seen: set[str] = set()
    for key in ("style_tags", "inline_tags"):
        raw_tags = strategy.get(key)
        if not isinstance(raw_tags, list):
            continue
        for tag in raw_tags:
            tag_text = str(tag or "").strip()
            tag_key = tag_text.casefold()
            if not tag_text or tag_key in seen:
                continue
            seen.add(tag_key)
            tags.append(tag_text)
    return tags


def _text_for_segments(script_segments: List[Dict[str, Any]], indices: List[int]) -> str:
    texts: List[str] = []
    for index in indices:
        if index < 0 or index >= len(script_segments):
            continue
        text = str(script_segments[index].get("text") or "").strip()
        if text:
            texts.append(text)
    return " ".join(texts)


def _target_segment_indices(
    *,
    script_segments: List[Dict[str, Any]],
    model: str,
    model_entry: Dict[str, Any],
) -> List[int]:
    raw_indices = model_entry.get("manual_review_segment_indices")
    if isinstance(raw_indices, list):
        indices = [
            int(index)
            for index in raw_indices
            if isinstance(index, int) and 0 <= index < len(script_segments)
        ]
        if indices:
            return indices

    return [
        index
        for index, segment in enumerate(script_segments)
        if _segment_model(segment) == model
    ]


def build_asr_assist_signal(
    *,
    chapter_audio: ChapterAudio,
    model: str,
    model_entry: Dict[str, Any],
    transcript: str,
    source: str = "manual_transcript",
) -> Dict[str, Any]:
    normalized_transcript = str(transcript or "").strip()
    if not normalized_transcript:
        return {"available": False, "reason": "empty_transcript"}

    script_segments = _load_script_segments(chapter_audio)
    if not script_segments:
        return {"available": False, "reason": "missing_script_segments"}

    segment_indices = _target_segment_indices(
        script_segments=script_segments,
        model=model,
        model_entry=model_entry,
    )
    if not segment_indices:
        return {"available": False, "reason": "missing_model_segments"}

    expected_text = _text_for_segments(script_segments, segment_indices)
    if not expected_text:
        return {"available": False, "reason": "missing_expected_text"}

    verifier = STTVerifier(enable_whisper=False)
    normalized_compare_transcript = verifier._normalize_compare_text(normalized_transcript)
    tags: List[str] = []
    use_tag_parser = False
    for index in segment_indices:
        strategy = _segment_inline_tag_strategy(script_segments[index])
        use_tag_parser = use_tag_parser or _is_truthy(strategy.get("use_tag_parser"))
        tags.extend(_collect_tags(strategy))

    matched_tags: List[str] = []
    seen_tag_keys: set[str] = set()
    for tag in tags:
        normalized_tag = verifier._normalize_compare_text(tag)
        if not normalized_tag:
            continue
        tag_key = normalized_tag.casefold()
        if tag_key in seen_tag_keys:
            continue
        if tag_key in normalized_compare_transcript.split() or tag_key in normalized_compare_transcript:
            seen_tag_keys.add(tag_key)
            matched_tags.append(tag)

    similarity_score = verifier._calculate_similarity(expected_text, normalized_transcript)
    word_error_rate = verifier._calculate_word_error_rate(expected_text, normalized_transcript)
    detected_tag_residue = bool(matched_tags)

    return {
        "available": True,
        "source": str(source or "").strip() or "manual_transcript",
        "segment_indices": segment_indices,
        "expected_text": expected_text,
        "transcript_text": normalized_transcript,
        "similarity_score": round(similarity_score, 4),
        "word_error_rate": round(word_error_rate, 4),
        "detected_tag_residue": detected_tag_residue,
        "matched_tags": matched_tags,
        "suggested_text_contamination": detected_tag_residue,
        "suggested_tag_parse_success": (
            not detected_tag_residue if use_tag_parser else None
        ),
    }
