from __future__ import annotations

import json
import logging
from typing import Any, Dict, Tuple

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import resolve_owned_chapter_audio
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.audiobook import ChapterAudio
from app.models.user import User
from app.schemas.audiobook import PromptAudioManualReviewRequest, PromptAudioTranscriptQueueRequest
from app.services.audiobook.prompt_audio_review_writer import (
    PromptAudioReviewError,
    apply_prompt_audio_manual_review_fields,
)
from app.services.audiobook.prompt_audio_transcript_queue import (
    queue_prompt_audio_transcript_task,
)


logger = logging.getLogger(__name__)


def _load_final_audio_review_payload(chapter_audio: ChapterAudio) -> Dict[str, Any]:
    if not chapter_audio.final_audio_review_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="最终音频评审不存在",
        )

    try:
        payload = json.loads(chapter_audio.final_audio_review_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "最终音频评审 JSON 损坏: chapter_audio_id=%s error=%s",
            getattr(chapter_audio, "id", None),
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="最终音频评审数据损坏",
        ) from exc

    if not isinstance(payload, dict):
        logger.warning(
            "最终音频评审 JSON 不是对象: chapter_audio_id=%s payload_type=%s",
            getattr(chapter_audio, "id", None),
            type(payload).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="最终音频评审数据损坏",
        )

    return payload


def _resolve_prompt_audio_quality_model(
    final_audio_review: Dict[str, Any],
    model: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    prompt_audio_quality = final_audio_review.get("prompt_audio_quality")
    if not isinstance(prompt_audio_quality, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="prompt_audio_quality 不存在",
        )

    by_model = prompt_audio_quality.get("by_model")
    if not isinstance(by_model, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="prompt_audio_quality.by_model 不存在",
        )

    model_entry = by_model.get(model)
    if not isinstance(model_entry, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="模型质量回写条目不存在",
        )

    return prompt_audio_quality, model_entry


def _merge_manual_review_fields(
    model_entry: Dict[str, Any],
    request: PromptAudioManualReviewRequest,
    current_user: User,
    *,
    chapter_audio: ChapterAudio,
    model: str,
) -> Dict[str, Any]:
    field_values = {
        field_name: getattr(request, field_name)
        for field_name in (
            "tag_parse_success",
            "text_contamination",
            "score",
            "notes",
            "asr_transcript",
        )
        if field_name in request.model_fields_set
    }
    _prompt_audio_quality, manual_review_fields = apply_prompt_audio_manual_review_fields(
        chapter_audio=chapter_audio,
        model=model,
        field_values=field_values,
        reviewed_by=current_user.id,
    )
    return manual_review_fields


@router.patch("/chapter-audios/{chapter_audio_id:int}/prompt-audio-review", response_model=dict)
async def update_prompt_audio_manual_review(
    chapter_audio_id: int,
    request: PromptAudioManualReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned_audio = resolve_owned_chapter_audio(
        db=db,
        current_user=current_user,
        chapter_audio_id=chapter_audio_id,
    )
    chapter_audio = owned_audio.chapter_audio
    field_values = {
        field_name: getattr(request, field_name)
        for field_name in (
            "tag_parse_success",
            "text_contamination",
            "score",
            "notes",
            "asr_transcript",
        )
        if field_name in request.model_fields_set
    }
    try:
        prompt_audio_quality, manual_review_fields = apply_prompt_audio_manual_review_fields(
            chapter_audio=chapter_audio,
            model=request.model,
            field_values=field_values,
            reviewed_by=current_user.id,
        )
    except PromptAudioReviewError as exc:
        if exc.code in {"prompt_audio_quality_missing", "prompt_audio_quality_by_model_missing", "prompt_audio_quality_model_missing"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    db.refresh(chapter_audio)

    return {
        "success": True,
        "chapter_audio_id": chapter_audio.id,
        "model": request.model,
        "manual_review_fields": manual_review_fields,
        "prompt_audio_quality": prompt_audio_quality,
    }


@router.post("/chapter-audios/{chapter_audio_id:int}/prompt-audio-transcript/queue", response_model=dict)
async def queue_prompt_audio_transcript(
    chapter_audio_id: int,
    request: PromptAudioTranscriptQueueRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned_audio = resolve_owned_chapter_audio(
        db=db,
        current_user=current_user,
        chapter_audio_id=chapter_audio_id,
    )
    payload = request or PromptAudioTranscriptQueueRequest()
    return queue_prompt_audio_transcript_task(
        db,
        chapter_audio=owned_audio.chapter_audio,
        provider=payload.provider,
        target_model=payload.model,
        confirm_cost=payload.confirm_cost,
    )
