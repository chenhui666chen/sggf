from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import Depends, File, Form, HTTPException, UploadFile, status

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import SegmentDirectionAssistRequest
from app.services.audiobook.prompt_audio_asr_provider import (
    PromptAudioAsrProviderError,
    create_prompt_audio_asr_provider,
)
from app.services.audiobook.repository import ChapterRepository
from app.services.audiobook.segment_direction_service import (
    analyze_segment_direction_reading,
    assist_segment_direction,
)
from app.services.audiobook.segment_synthesis_contract import sanitize_segment_override
from core.unified_llm_client import get_llm_client


MAX_SEGMENT_DIRECTION_AUDIO_BYTES = 10 * 1024 * 1024


def _load_stored_segment(
    *,
    owned: OwnedAudiobookProject,
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
) -> Dict[str, Any]:
    chapter = ChapterRepository.get_active_project_chapter(
        owned.db,
        project_id=owned.project.id,
        chapter_id=chapter_id,
    )
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在或不属于该项目")
    chapter_audio = get_active_chapter_audio_for_project(
        db=owned.db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    try:
        payload = json.loads(chapter_audio.script_json or "[]")
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="章节剧本数据损坏") from exc
    segments = payload if isinstance(payload, list) else payload.get("segments", []) if isinstance(payload, dict) else []
    if not isinstance(segments, list) or segment_index < 0 or segment_index >= len(segments):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="片段不存在")
    stored = segments[segment_index]
    return dict(stored) if isinstance(stored, dict) else {}


@router.post(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/direction-assist",
    response_model=dict,
)
async def create_segment_direction_assist(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentDirectionAssistRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    stored_segment = _load_stored_segment(
        owned=owned,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
    )
    effective_segment = sanitize_segment_override(
        {**stored_segment, **dict(request.segment or {})}
    ) or {}
    try:
        llm_client = get_llm_client(strategy="conservative")
    except Exception:
        llm_client = None
    try:
        return await assist_segment_direction(
            cue_type=request.cue_type,
            description=request.description,
            segment=effective_segment,
            tts_model=request.tts_model,
            llm_client=llm_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/direction-audio/analyze",
    response_model=dict,
)
async def analyze_segment_direction_recording(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    file: UploadFile = File(...),
    tts_model: Optional[str] = Form(default=None),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    stored_segment = _load_stored_segment(
        owned=owned,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
    )
    expected_text = str(stored_segment.get("text") or "").strip()
    if not expected_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="片段台词为空，无法分析朗读")
    content_type = str(file.content_type or "").strip().lower()
    if content_type and not content_type.startswith("audio/") and content_type != "application/octet-stream":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="仅支持音频录音文件")
    audio_bytes = await file.read(MAX_SEGMENT_DIRECTION_AUDIO_BYTES + 1)
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="录音不能为空")
    if len(audio_bytes) > MAX_SEGMENT_DIRECTION_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="录音超过 10MB，请缩短后重试")

    # 朗读分析固定使用 qwen3.5-omni 音频理解，不走提示音频评审的默认 provider。
    try:
        asr_provider = create_prompt_audio_asr_provider("qwen_omni")
    except PromptAudioAsrProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if asr_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未配置 qwen-omni 音频理解服务（QWEN_OMNI_DIRECTION_API_KEY 或 DASHSCOPE_API_KEY）",
        )
    try:
        return await analyze_segment_direction_reading(
            audio_bytes=audio_bytes,
            filename=file.filename or "reading.webm",
            expected_text=expected_text,
            segment=stored_segment,
            tts_model=tts_model,
            provider=asr_provider,
        )
    except PromptAudioAsrProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
