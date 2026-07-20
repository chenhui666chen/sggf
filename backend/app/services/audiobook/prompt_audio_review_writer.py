from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from app.models.audiobook import ChapterAudio
from app.services.audiobook.prompt_audio_asr_assist import build_asr_assist_signal
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


class PromptAudioReviewError(ValueError):
    """Raised when prompt/audio review data cannot be updated."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_final_audio_review_payload(chapter_audio: ChapterAudio) -> Dict[str, Any]:
    if not chapter_audio.final_audio_review_json:
        raise PromptAudioReviewError("final_audio_review_missing", "最终音频评审不存在")

    try:
        payload = json.loads(chapter_audio.final_audio_review_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "最终音频评审 JSON 损坏: chapter_audio_id=%s error=%s",
            getattr(chapter_audio, "id", None),
            exc,
        )
        raise PromptAudioReviewError("final_audio_review_invalid_json", "最终音频评审数据损坏") from exc

    if not isinstance(payload, dict):
        logger.warning(
            "最终音频评审 JSON 不是对象: chapter_audio_id=%s payload_type=%s",
            getattr(chapter_audio, "id", None),
            type(payload).__name__,
        )
        raise PromptAudioReviewError("final_audio_review_invalid_shape", "最终音频评审数据损坏")

    return payload


def resolve_prompt_audio_quality_model(
    final_audio_review: Dict[str, Any],
    model: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    prompt_audio_quality = final_audio_review.get("prompt_audio_quality")
    if not isinstance(prompt_audio_quality, dict):
        raise PromptAudioReviewError("prompt_audio_quality_missing", "prompt_audio_quality 不存在")

    by_model = prompt_audio_quality.get("by_model")
    if not isinstance(by_model, dict):
        raise PromptAudioReviewError("prompt_audio_quality_by_model_missing", "prompt_audio_quality.by_model 不存在")

    model_entry = by_model.get(model)
    if not isinstance(model_entry, dict):
        raise PromptAudioReviewError("prompt_audio_quality_model_missing", "模型质量回写条目不存在")

    return prompt_audio_quality, model_entry


def select_prompt_audio_review_model(final_audio_review: Dict[str, Any], preferred_model: Optional[str] = None) -> str:
    prompt_audio_quality = final_audio_review.get("prompt_audio_quality")
    if not isinstance(prompt_audio_quality, dict):
        raise PromptAudioReviewError("prompt_audio_quality_missing", "prompt_audio_quality 不存在")

    by_model = prompt_audio_quality.get("by_model")
    if not isinstance(by_model, dict) or not by_model:
        raise PromptAudioReviewError("prompt_audio_quality_by_model_missing", "prompt_audio_quality.by_model 不存在")

    normalized_preferred = str(preferred_model or "").strip()
    if normalized_preferred:
        if isinstance(by_model.get(normalized_preferred), dict):
            return normalized_preferred
        raise PromptAudioReviewError("prompt_audio_quality_model_missing", "模型质量回写条目不存在")

    for model, entry in by_model.items():
        if not isinstance(entry, dict):
            continue
        indices = entry.get("manual_review_segment_indices")
        if isinstance(indices, list) and indices:
            return str(model)

    for model, entry in by_model.items():
        if isinstance(entry, dict):
            return str(model)

    raise PromptAudioReviewError("prompt_audio_quality_model_missing", "模型质量回写条目不存在")


def apply_prompt_audio_manual_review_fields(
    *,
    chapter_audio: ChapterAudio,
    model: str,
    field_values: Dict[str, Any],
    reviewed_by: Optional[int] = None,
    transcript_source: str = "manual_transcript",
    asr_provider: Optional[str] = None,
    asr_provider_model: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    final_audio_review = load_final_audio_review_payload(chapter_audio)
    prompt_audio_quality, model_entry = resolve_prompt_audio_quality_model(
        final_audio_review,
        model,
    )

    manual_review_fields = model_entry.get("manual_review_fields")
    if not isinstance(manual_review_fields, dict):
        manual_review_fields = {}

    for field_name in (
        "tag_parse_success",
        "text_contamination",
        "score",
        "notes",
    ):
        if field_name in field_values:
            manual_review_fields[field_name] = field_values[field_name]

    if "asr_transcript" in field_values:
        transcript = field_values.get("asr_transcript")
        manual_review_fields["asr_transcript"] = transcript
        if transcript:
            manual_review_fields["asr_assist"] = build_asr_assist_signal(
                chapter_audio=chapter_audio,
                model=model,
                model_entry=model_entry,
                transcript=str(transcript),
                source=transcript_source,
            )
            if asr_provider:
                manual_review_fields["asr_provider"] = asr_provider
            if asr_provider_model:
                manual_review_fields["asr_provider_model"] = asr_provider_model
        else:
            manual_review_fields.pop("asr_assist", None)
            manual_review_fields.pop("asr_provider", None)
            manual_review_fields.pop("asr_provider_model", None)

    manual_review_fields["reviewed_at"] = utc_now().isoformat()
    manual_review_fields["reviewed_by"] = reviewed_by
    model_entry["manual_review_fields"] = manual_review_fields
    chapter_audio.final_audio_review_json = json.dumps(final_audio_review, ensure_ascii=False)
    return prompt_audio_quality, manual_review_fields
