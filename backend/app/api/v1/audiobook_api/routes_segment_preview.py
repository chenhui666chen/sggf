from __future__ import annotations

from fastapi import Depends, HTTPException, Response, status

from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import ScriptSegmentPreviewRequest
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.repository import ChapterRepository
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/preview")
async def preview_script_segment_audio(
    audiobook_project_id: int,
    chapter_id: int,
    request: ScriptSegmentPreviewRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """单段剧本片段音频试听（不落库）"""
    db = owned.db
    project = owned.project
    audiobook_project = owned.audiobook_project

    chapter = ChapterRepository.get_active_project_chapter(
        db,
        project_id=project.id,
        chapter_id=chapter_id,
    )
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )

    segment = request.segment or {}
    if not isinstance(segment, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="segment 数据格式不正确",
        )

    tts_model = normalize_audiobook_tts_model(request.tts_model)

    preview_type = str(request.preview_type or "voice").strip().lower()
    if preview_type not in {"voice", "sfx", "bgm", "mix"}:
        preview_type = "voice"

    runtime_config = resolve_project_audio_runtime_config(
        project,
        tts_model=tts_model,
        base_voice_mapping=audiobook_project.voice_mapping or {},
    )
    preview_service = SegmentPreviewService(
        tts_model=tts_model,
        voice_mapping=runtime_config.voice_mapping,
        audio_fx=runtime_config.audio_fx,
        synthesize_speech=runtime_synthesize_speech,
    )
    result = await preview_service.generate_preview(segment, preview_type=preview_type)

    return Response(content=result.audio, media_type=result.media_type)
