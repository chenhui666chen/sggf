from __future__ import annotations

import asyncio
import logging
import os
import json
import math
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status, Response, Query, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_delete_audit import AudiobookDeleteAudit
from app.models.character import Character
from app.models.audiobook_task import AudiobookTask
from app.schemas.audiobook import (
    AudiobookProjectCreate,
    GenerateAudioFromScriptsRequest,
    ChapterScriptUpdateRequest,
    AudiobookProjectResponse,
    ChapterAudioResponse,
    CharacterVoiceConfig,
    TTSPreviewRequest,
    ScriptSegmentPreviewRequest,
    SegmentRegenerateRequest,
    SegmentReviewRequest,
    AudiobookTaskStatus,
    CosyVoiceCloneCreateRequest,
    ChapterReviewStatus,
    NarrationStylePreset,
    SubtitleDownloadResponse,
    GenerationCheckpointResponse,
    SmartChunkConfig,
    ChunkStats,
    ChunkPreviewResponse,
    VoiceTypePresetResponse,
    VoiceTypeRecommendationRequest,
    VoiceTypeRecommendationResponse,
)
from app.celery_app import celery_app
from app.services.audiobook import AudiobookEngine
from app.services.audiobook.audio_mixer import AudioMixer
from app.services.audiobook.agents import SoundEffectDesigner
from app.services.audiobook.tts_engine import RetryConfig
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_manager_factory import create_voice_manager
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.project_audio_config import (
    parse_project_audio_config,
    get_characters_for_model,
    get_audio_fx,
)
from app.services.audiobook.cosyvoice_clone_client import (
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    delete_cosyvoice_clone,
    get_clone_display_name,
    list_cosyvoice_v3_plus_clones,
    save_clone_display_name,
    upload_cosyvoice_v3_plus_clone_sample,
)
from app.services.audiobook.narration_styles import get_all_narration_styles, get_narration_style_preset, apply_narration_style_to_tts_params
from app.services.audiobook.subtitle_generator import SubtitleGenerator, SubtitleEntry
from app.services.audiobook.smart_chunker import SmartChunker, TextChunk
from app.services.audiobook.voice_types import (
    get_all_voice_types,
    get_voice_type_preset,
    recommend_voice_type,
    apply_voice_type_to_tts_params,
    create_character_voice_profile,
)
from app.services.audiobook.sse_progress import sse_tracker, create_progress_handler
from app.services.audiobook.smart_retrier import SmartRetrier, RetryConfig, retry_tts_call
from app.services.audiobook.preview_generator import PreviewGenerator, default_preview_generator
from app.services.audiobook.app_service import AudiobookAppService
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from app.services.audiobook.task_support import (
    build_generation_checkpoint_payload as _build_generation_checkpoint_payload,
    build_task_status_response,
    enqueue_chapter_runs as _enqueue_chapter_runs,
    ensure_audiobook_points_precheck_passed as _ensure_audiobook_points_precheck_passed,
)
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_freeze,
)
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regenerate")
async def regenerate_segment(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentRegenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单个片段重新生成
    
    功能：
    1. 重新调用 TTS API 生成该片段的新音频
    2. 替换原有的片段音频
    3. 可选：使用不同的 TTS 模型/音色/情感
    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    checkpoint_payload = _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="章节音频记录不存在")
    
    # 加载剧本片段
    try:
        segments = json.loads(chapter_audio.script_json)
    except:
        raise HTTPException(status_code=500, detail="章节剧本数据损坏")
    
    if segment_index < 0 or segment_index >= len(segments):
        raise HTTPException(status_code=404, detail="片段索引无效")
    
    segment = segments[segment_index]
    
    # 构建 TTS 请求参数
    tts_model = request.tts_model or (chapter_audio.tts_model or "qwen3-tts-flash")
    voice_id = request.voice_id or segment.get("voice_id", "longxiaochun")
    emotion = request.emotion or segment.get("emotion", "neutral")
    
    # 创建 TTS 引擎
    engine = create_tts_engine(
        model=tts_model,
        retry_config=RetryConfig(max_retries=3, base_delay=1.0),
    )
    
    voice_params = {
        "speaker": voice_id,
        "emotion": emotion,
    }
    
    # 调用 TTS
    text = segment.get("text", "")
    audio_bytes = await engine.synthesize(text, voice_params=voice_params)
    
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS 生成失败")
    
    # 保存新音频（覆盖原音频）
    try:
        output_dir = chapter_audio.get_audio_dir()
        os.makedirs(output_dir, exist_ok=True)
        
        audio_filename = f"segment_{segment_index}_regenerated.mp3"
        audio_path = os.path.join(output_dir, audio_filename)
        
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        
        # 更新 segment 中的音频路径
        segment["audio_path"] = audio_path
        segment["regenerated"] = True
        segment["regenerated_at"] = datetime.utcnow().isoformat()
        if request.reason:
            segment["regenerate_reason"] = request.reason
        
        # 保存更新后的剧本
        chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
        db.commit()
        
        logger.info(
            f"✅ 片段重新生成成功: chapter_id={chapter_id}, "
            f"segment_index={segment_index}, model={tts_model}"
        )
        
        return {
            "success": True,
            "segment_index": segment_index,
            "audio_path": audio_path,
            "audio_size": len(audio_bytes),
            "model_used": tts_model,
        }
    
    except Exception as e:
        logger.error(f"❌ 保存重新生成的音频失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存音频失败: {str(e)}")


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/review")
async def review_segment(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """片段审查/评分
    
    功能：
    1. 记录片段的质量评分和备注
    2. 标记需要重新生成的片段
    3. 更新章节整体审查状态
    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="有声书项目不存在")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="无权限访问")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="章节音频记录不存在")
    
    # 加载审查记录
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            review_data = json.loads(chapter_audio.segment_reviews_json)
        except:
            pass
    
    # 记录审查结果
    review_key = str(segment_index)
    review_data[review_key] = {
        "quality_score": request.quality_score,
        "notes": request.notes,
        "needs_regenerate": request.needs_regenerate,
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewed_by": current_user.id,
    }
    
    chapter_audio.segment_reviews_json = json.dumps(review_data, ensure_ascii=False)
    db.commit()
    
    return {
        "success": True,
        "segment_index": segment_index,
        "review_saved": True,
    }


