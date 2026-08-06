from __future__ import annotations

from fastapi import Depends, HTTPException, Response, status

from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import ScriptSegmentPreviewRequest
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.mimo_voice_assets import merge_mimo_voice_asset_tts_params
from app.services.audiobook.repository import ChapterRepository
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.segment_synthesis_contract import (
    compile_segment_synthesis_input,
    resolve_server_owned_mimo_design_params,
    sanitize_segment_override,
)
from app.services.audiobook.tts_delivery_plan import resolve_segment_tts_model
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

    segment = sanitize_segment_override(request.segment or {}) or {}
    if not isinstance(segment, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="segment 数据格式不正确",
        )

    preview_type = str(request.preview_type or "voice").strip().lower()
    if preview_type not in {"voice", "sfx", "bgm", "mix"}:
        preview_type = "voice"

    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}
    # 片段绑定模型与候选、整章生成使用同一来源；页面模型只作为回退。
    tts_model = resolve_segment_tts_model(segment_voice_params, request.tts_model)

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

    voice_id = str(
        segment_voice_params.get("speaker")
        or segment.get("voice_id")
        or ""
    ).strip()
    emotion = str(
        segment.get("instruct_emotion")
        or segment.get("emotion")
        or "neutral"
    )
    if preview_type in {"voice", "mix"} and not voice_id:
        resolver = getattr(preview_service, "resolve_voice_params", None)
        if callable(resolver):
            resolved_emotion, resolved_voice_params = resolver(segment)
            emotion = str(resolved_emotion or emotion)
            if isinstance(resolved_voice_params, dict):
                voice_id = str(resolved_voice_params.get("speaker") or voice_id)

    server_owned_voice_params = {}
    if preview_type in {"voice", "mix"}:
        try:
            server_owned_voice_params = resolve_server_owned_mimo_design_params(
                tts_model=tts_model,
                voice_id=voice_id,
                owner_user_id=owned.current_user.id,
                merge_asset_params=merge_mimo_voice_asset_tts_params,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    compiled = compile_segment_synthesis_input(
        segment,
        tts_model=tts_model,
        voice_id=voice_id,
        emotion=emotion,
        preview_type=preview_type,
        server_owned_voice_params=server_owned_voice_params,
    )
    result = await preview_service.generate_preview(
        compiled["segment"], preview_type=preview_type
    )

    return Response(content=result.audio, media_type=result.media_type)
