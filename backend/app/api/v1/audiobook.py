"""
耳畔星河 - 有声书生成API

功能：
1. 创建有声书项目
2. 生成章节音频
3. 查询生成进度
4. 下载音频文件
"""
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
    ChapterAudioRunRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from app.services.points_task_precheck import (
    build_audiobook_task_points_precheck,
    build_task_points_precheck_error_detail,
)
from app.services.user_center_points_events import (
    record_audiobook_billing_freeze,
    record_audiobook_billing_release,
    record_audiobook_billing_settle,
)
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech
from dataclasses import asdict, is_dataclass

logger = logging.getLogger(__name__)


def _ensure_audiobook_points_precheck_passed(precheck: object) -> None:
    if bool(getattr(precheck, "allowed", False)):
        return
    detail = build_task_points_precheck_error_detail(
        precheck=precheck,
        module_key="audiobook",
        module_label="有声书",
        default_message="有声书积分预检未通过",
    )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def serialize_dataclass_to_dict(obj):
    """递归将dataclass对象转换为字典，用于JSON序列化"""
    if is_dataclass(obj):
        return asdict(obj)
    elif isinstance(obj, list):
        return [serialize_dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize_dataclass_to_dict(value) for key, value in obj.items()}
    else:
        return obj


def build_task_status_response(task: AudiobookTask) -> AudiobookTaskStatus:
    """Convert ORM object to API schema."""
    return AudiobookTaskStatus(
        celery_task_id=task.celery_task_id,
        audiobook_project_id=task.audiobook_project_id,
        chapter_id=task.chapter_id,
        task_type=task.task_type,
        status=task.status,
        current_stage=task.current_stage,
        progress=task.progress or 0.0,
        completed_units=task.completed_units or 0,
        total_units=task.total_units or 0,
        detail=task.detail_json or {},
        error_message=task.error_message,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        finished_at=task.finished_at.isoformat() if task.finished_at else None,
    )


def _tracker_update(tracker, stage: str, completed: int, total: int, message: Optional[str] = None, detail: Optional[dict] = None):
    """简单包装，避免在任务函数中重复判空。"""
    if tracker is None:
        return
    tracker.update_stage(stage, completed, total, message, detail)


def _build_progress_handler(tracker, chapter_ids: List[int]):
    """将 AudiobookEngine 的章节级任务进度映射到 Celery 任务追踪。"""
    if tracker is None:
        return None

    total = max(len(chapter_ids) or 0, 1)
    chapter_positions: Dict[int, int] = {chapter_id: idx + 1 for idx, chapter_id in enumerate(chapter_ids)}
    chapter_completed: Dict[int, bool] = {}

    def handle_progress(snapshot: Dict[str, Any]):
        stage = snapshot.get("current_stage")
        chapter_id = snapshot.get("chapter_id")
        if not stage or chapter_id is None:
            return

        if snapshot.get("status") == "completed":
            chapter_completed[chapter_id] = True
        completed_units = sum(1 for finished in chapter_completed.values() if finished)

        detail_payload = {
            "chapter_id": chapter_id,
            "task_id": snapshot.get("task_id"),
            "overall_progress": snapshot.get("overall_progress"),
            "stages": snapshot.get("stages"),
            "status": snapshot.get("status"),
            "chapter_index": chapter_positions.get(chapter_id),
            "chapter_total": total,
        }
        stage_name = stage if isinstance(stage, str) else str(stage)
        message = f"章节 {chapter_positions.get(chapter_id, '?')}/{total} · {stage_name}"
        _tracker_update(tracker, stage_name, completed_units, total, message, detail_payload)

    return handle_progress


def _safe_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _enqueue_chapter_runs(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_ids: List[int],
    run_type: str,
    celery_task_id: Optional[str],
    tts_model: Optional[str] = None,
    output_format: Optional[str] = None,
    narration_style: Optional[str] = None,
    narration_style_prompt: Optional[str] = None,
) -> None:
    normalized_ids = [chapter_id for chapter_id in dict.fromkeys(chapter_ids or []) if chapter_id is not None]
    if not normalized_ids:
        return
    ChapterAudioRunRepository.create_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=normalized_ids,
        run_type=run_type,
        celery_task_id=celery_task_id,
        status="queued",
        current_stage="queued",
        tts_model=tts_model,
        output_format=output_format,
        narration_style=narration_style,
        narration_style_prompt=narration_style_prompt,
        resumable=True,
    )


def _update_chapter_run_state(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    run_type: str,
    status: str,
    current_stage: str,
    progress: float,
    celery_task_id: Optional[str] = None,
    total_segment_count: Optional[int] = None,
    completed_segment_count: Optional[int] = None,
    checkpoint_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )
    if not run:
        run = ChapterAudioRunRepository.create_run(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
            celery_task_id=celery_task_id,
            status=status,
            current_stage=current_stage,
            progress=progress,
        )

    checkpoint_json = dict(run.checkpoint_json or {})
    if checkpoint_patch:
        checkpoint_json.update(checkpoint_patch)

    changes: Dict[str, Any] = {
        "status": status,
        "current_stage": current_stage,
        "progress": progress,
        "celery_task_id": celery_task_id or run.celery_task_id,
        "checkpoint_json": checkpoint_json,
        "error_message": error_message,
    }
    if total_segment_count is not None:
        changes["total_segment_count"] = total_segment_count
    if completed_segment_count is not None:
        changes["completed_segment_count"] = completed_segment_count
    if status in {"running"} and run.started_at is None:
        changes["started_at"] = utc_now()
    if status in {"completed", "failed"}:
        changes["finished_at"] = utc_now()
    ChapterAudioRunRepository.update_run(db, run, **changes)


def _build_generation_checkpoint_payload(
    *,
    chapter_id: int,
    chapter_audio: Optional[ChapterAudio],
    run_type: Optional[str],
    db: Session,
    audiobook_project_id: int,
) -> Dict[str, Any]:
    chapter_run = ChapterAudioRunRepository.get_latest_run(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_type=run_type,
    )

    checkpoint_source = "none"
    checkpoint_data: Dict[str, Any] = {}
    if chapter_run and isinstance(chapter_run.checkpoint_json, dict) and chapter_run.checkpoint_json:
        checkpoint_data = dict(chapter_run.checkpoint_json)
        checkpoint_source = "chapter_audio_run"
    elif chapter_audio and chapter_audio.generation_progress_json:
        checkpoint_data = _safe_json_dict(chapter_audio.generation_progress_json)
        if checkpoint_data:
            checkpoint_source = "legacy_chapter_audio"

    completed_indices = checkpoint_data.get("completed_segment_indices") or []
    cached_paths = checkpoint_data.get("cached_audio_paths") or {}

    total_segments = 0
    if chapter_run and (chapter_run.total_segment_count or 0) > 0:
        total_segments = int(chapter_run.total_segment_count or 0)
    elif chapter_audio and (chapter_audio.segment_count or 0) > 0:
        total_segments = int(chapter_audio.segment_count or 0)
    else:
        total_segments = int(checkpoint_data.get("total_segments") or 0)

    completed_count = len(completed_indices)
    if chapter_run and (chapter_run.completed_segment_count or 0) > completed_count:
        completed_count = int(chapter_run.completed_segment_count or 0)
    if chapter_run and chapter_run.status == "completed" and total_segments > 0:
        completed_count = total_segments

    estimated_remaining = None
    if chapter_audio and chapter_audio.generation_time and total_segments > 0 and completed_count < total_segments:
        avg_time_per_segment = chapter_audio.generation_time / total_segments
        remaining_segments = total_segments - completed_count
        estimated_remaining = avg_time_per_segment * remaining_segments

    has_resume_material = bool(completed_indices or cached_paths)
    can_resume = bool(
        has_resume_material
        and (total_segments == 0 or completed_count < total_segments)
        and (chapter_run.resumable if chapter_run else True)
        and (not chapter_run or chapter_run.status not in {"completed", "failed"})
    )

    return {
        "chapter_id": chapter_id,
        "total_segments": total_segments,
        "completed_segments": completed_count,
        "completed_segment_indices": completed_indices,
        "cached_audio_paths": cached_paths,
        "can_resume": can_resume,
        "estimated_remaining_time": estimated_remaining,
        "run_id": chapter_run.id if chapter_run else None,
        "run_status": chapter_run.status if chapter_run else None,
        "current_stage": chapter_run.current_stage if chapter_run else None,
        "celery_task_id": chapter_run.celery_task_id if chapter_run else None,
        "checkpoint_source": checkpoint_source,
    }

router = APIRouter(prefix="/api/v1/audiobook", tags=["audiobook"])


# ==================== Pydantic Schemas ====================
# 说明：有声书相关的请求/响应模型已迁移至 app.schemas.audiobook 模块。


@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """合成一小段音频用于前端试听"""
    # 简单防护：限制文本长度
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")
    if len(text) > 200:
        text = text[:200]

    # 选择模型：默认使用 qwen3-tts-flash，可切换为 cosyvoice-v3-plus
    model_name = (request.model or "qwen3-tts-flash").strip()
    if model_name not in {"qwen3-tts-flash", "cosyvoice-v3-plus"}:
        model_name = "qwen3-tts-flash"

    # 试听场景优先“快速恢复”而非长时间等待：
    # - 额外多 1 次重试（应对偶发断连）
    # - 基础退避更小，避免前端等待过久
    preview_retry = RetryConfig(max_retries=4, base_delay=1.0, max_delay=8.0, exponential_base=2.0, jitter=True)
    # 将前端的 voice_id（如 'male_young_energetic'）映射为真实的 TTS 音色ID
    if model_name == "qwen3-tts-flash":
        preset = VoiceManager.PRESET_VOICES.get(request.voice_id)
        speaker_id = preset["tts_speaker_id"] if preset else request.voice_id
    else:
        entry = get_voice_entry(request.voice_id, model=model_name)
        speaker_id = entry.get("speaker") if entry else request.voice_id

    voice_params: dict = {
        "speaker": speaker_id,
        "volume": request.volume,
    }
    if request.speed is not None:
        voice_params["rate"] = request.speed
    if request.pitch is not None:
        voice_params["pitch"] = request.pitch

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except Exception as exc:
        logger.warning("TTS试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/tts/models")
async def list_tts_models(
    current_user: User = Depends(get_current_user),
):
    """列出所有支持的 TTS 模型及其基本信息"""
    from app.services.audiobook.voice_manager_factory import list_all_models, MODEL_VOICE_MAPPING
    from app.services.audiobook.voice_catalog import load_voice_catalog_for_model
    
    models = []
    for model_name in list_all_models():
        try:
            catalog = load_voice_catalog_for_model(model_name)
            voices = catalog.get("voices", [])
            meta = catalog.get("meta", {})
            models.append({
                "id": model_name,
                "name": _get_model_display_name(model_name),
                "description": _get_model_description(model_name),
                "voice_count": meta.get("voice_count", len(voices)),
                "price_per_10k": _get_model_price(model_name),
                "features": _get_model_features(model_name),
            })
        except Exception:
            pass
    
    return {"models": models}


def _get_model_display_name(model: str) -> str:
    names = {
        "qwen3-tts-flash": "Qwen3-TTS Flash",
        "qwen3-tts-plus": "Qwen3-TTS Plus",
        "cosyvoice-v3-plus": "CosyVoice v3 Plus",
        "minimax-speech-2.8-hd": "MiniMax Speech 2.8 HD",
        "minimax-speech-2.8-turbo": "MiniMax Speech 2.8 Turbo",
    }
    return names.get(model, model)


def _get_model_description(model: str) -> str:
    descriptions = {
        "qwen3-tts-flash": "高性价比，49音色，适合批量生成",
        "qwen3-tts-plus": "高质量，支持SSML",
        "cosyvoice-v3-plus": "顶级音质，情绪控制，Instruct模式",
        "minimax-speech-2.8-hd": "最高音质，语气词标签，100+音色",
        "minimax-speech-2.8-turbo": "优秀音质，高性价比，高并发",
    }
    return descriptions.get(model, "")


def _get_model_price(model: str) -> float:
    prices = {
        "qwen3-tts-flash": 1.0,
        "qwen3-tts-plus": 2.0,
        "cosyvoice-v3-plus": 2.0,
        "minimax-speech-2.8-hd": 6.0,
        "minimax-speech-2.8-turbo": 3.0,
    }
    return prices.get(model, 1.0)


def _get_model_features(model: str) -> list:
    features_map = {
        "qwen3-tts-flash": ["高性价比", "49音色", "批量合成"],
        "qwen3-tts-plus": ["高质量", "SSML支持"],
        "cosyvoice-v3-plus": ["顶级音质", "情绪控制", "Instruct模式"],
        "minimax-speech-2.8-hd": ["最高音质", "语气词标签", "100+音色", "混合音色"],
        "minimax-speech-2.8-turbo": ["优秀音质", "高性价比", "高并发"],
    }
    return features_map.get(model, [])


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = "qwen3-tts-flash",
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = (model or "qwen3-tts-flash").strip()
    if model not in {"qwen3-tts-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"}:
        if model.startswith("minimax-speech"):
            model = "minimax-speech-2.8-hd"
        elif model.startswith("qwen3-tts"):
            model = "qwen3-tts-flash"
        else:
            model = "qwen3-tts-flash"
    catalog = load_voice_catalog_for_model(model)
    meta = catalog.get("meta") or {}
    voices = list(catalog.get("voices") or [])

    # cosyvoice-v3-plus：合并“官方内置音色”与“复刻音色”（DashScope VoiceEnrollmentService）
    if model == "cosyvoice-v3-plus":
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend([c.to_voice_preset(get_clone_display_name(c.voice_id)) for c in clones])
        except CosyVoiceCloneError:
            # 未配置 API Key 等情况下，不阻塞页面使用内置音色
            pass
    return {
        "model": meta.get("model", "qwen3-tts-flash"),
        "updated_at": meta.get("updated_at"),
        "source": meta.get("source"),
        "voice_count": len(voices),
        "voices": voices,
    }


@router.post("/tts/voices/cosyvoice-v3-plus/clones")
async def create_cosyvoice_v3_plus_voice_clone(
    request: CosyVoiceCloneCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 cosyvoice-v3-plus 复刻音色。

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址或 oss:// 临时 URL。
    """
    try:
        import hashlib
        import re
        import secrets

        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip()
        if not prefix:
            # 生成策略：
            # - 允许 name 任意字符（含中文），但 prefix 必须满足 SDK 要求：字母/数字/下划线，1~32
            # - 注意：cosyvoice clone 要求 prefix 最长 10 个字符
            # - 尽量从 name 提取可读片段，否则退化为 v，再拼接 hash 提升唯一性
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", display_name).strip("_").lower()
            base = (slug[:4] if slug else "v").strip("_") or "v"
            uid = str(getattr(current_user, "id", "0"))
            # 防碰撞：加一个稳定 hash 片段（避免同名同用户频繁生成完全一致）
            h = hashlib.sha1(f"{uid}:{display_name}".encode("utf-8")).hexdigest()[:6]  # noqa: S324
            rand = secrets.token_hex(1)  # 2 hex chars
            prefix = f"{base}{h}{rand}"[:10]

        result = create_cosyvoice_v3_plus_clone(prefix=prefix, audio_url=request.url)
        save_clone_display_name(voice_id=result.get("voice_id", ""), display_name=display_name)
        result["display_name"] = display_name
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3-plus/clones/upload")
async def upload_cosyvoice_v3_plus_clone_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传本地音频，生成临时 oss:// URL。"""
    try:
        content = await file.read()
        if not content:
            raise CosyVoiceCloneError("file 不能为空")
        return upload_cosyvoice_v3_plus_clone_sample(
            filename=file.filename or "audio",
            content=content,
            content_type=file.content_type,
        )
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass


@router.get("/tts/voices/cosyvoice-v3-plus/clones")
async def list_cosyvoice_v3_plus_voice_clones(
    prefix: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 cosyvoice-v3-plus 的复刻音色（当前 API Key 维度）。"""
    try:
        clones, meta = list_cosyvoice_v3_plus_clones(prefix=prefix)
        return {
            "meta": meta,
            "voices": [
                {
                    "voice_id": c.voice_id,
                    "status": c.status,
                    "gmt_create": c.gmt_create,
                    "gmt_modified": c.gmt_modified,
                }
                for c in clones
            ],
        }
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/cosyvoice-v3-plus/clones/{voice_id}")
async def delete_cosyvoice_v3_plus_voice_clone(
    voice_id: str,
    current_user: User = Depends(get_current_user),
):
    """删除 cosyvoice-v3-plus 复刻音色。"""
    try:
        return delete_cosyvoice_clone(voice_id=voice_id)
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ==================== API Endpoints ====================

@router.post("/projects", response_model=dict)
async def create_audiobook_project(
    request: AudiobookProjectCreate,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建有声书项目并启动生成任务。

    工作流：
    1. 通过应用服务校验项目与章节，并创建有声书项目记录
    2. 根据 generation_mode 启动对应的后台生成任务
    """
    service = AudiobookAppService(db=db, current_user=current_user)
    # 4. 后台启动生成任务（通过 Celery 队列）
    job_type = "script_only" if getattr(request, "generation_mode", "full") == "script_only" else "full"
    prepared_request = service.prepare_audiobook_project_creation(request)
    if job_type != "script_only":
        precheck = build_audiobook_task_points_precheck(
            db=db,
            user_id=current_user.id,
            project_id=prepared_request.project.id,
            project_title=prepared_request.project.title,
            chapter_ids=list(request.chapter_ids or []),
            tts_provider=request.tts_provider,
        )
        _ensure_audiobook_points_precheck_passed(precheck)

    audiobook_project = service.create_audiobook_project(request, prepared=prepared_request)
    task_record = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_id=None,
        task_type=job_type,
        total_units=len(request.chapter_ids),
    )
    tts_model = (request.tts_model or "qwen3-tts-flash").strip()
    if job_type == "script_only":
        signature = celery_app.signature(
            "audiobook.run_script_only",
            args=[
                task_record.id,
                audiobook_project.id,
                request.chapter_ids,
                tts_model,
                request.force_regenerate_script,
            ],
        )
    else:
        signature = celery_app.signature(
            "audiobook.run_full",
            args=[
                task_record.id,
                audiobook_project.id,
                request.chapter_ids,
                tts_model,
            ],
        )
    async_result = signature.delay()
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, async_result.id)
    _enqueue_chapter_runs(
        db,
        audiobook_project_id=audiobook_project.id,
        chapter_ids=list(request.chapter_ids or []),
        run_type=job_type,
        celery_task_id=async_result.id,
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
    )

    if job_type != "script_only":
        try:
            record_audiobook_billing_freeze(
                db=db,
                actor_user_id=current_user.id,
                actor_username=current_user.username,
                audiobook_project_id=audiobook_project.id,
                chapter_ids=list(request.chapter_ids or []),
                request_context=raw_request,
            )
        except Exception as exc:
            logger.warning("记录有声书积分冻结失败 audiobook_project_id=%s: %s", audiobook_project.id, exc)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project.id,
        "job_id": async_result.id,
        "task_type": job_type,
        "message": "有声书生成任务已进入队列",
        "total_chapters": len(request.chapter_ids),
    }


@router.get("/projects/{audiobook_project_id:int}", response_model=dict)
async def get_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取有声书项目详情"""
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证权限
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 获取章节音频列表
    chapter_audios = ChapterAudioRepository.list_by_audiobook_project(db, audiobook_project_id)

    # 取章节编号，用于前端“按章节编号跨记录合并音频”
    chapter_ids = [ca.chapter_id for ca in chapter_audios]
    chapter_number_by_id = {}
    if chapter_ids:
        from app.models.project import Chapter  # 避免顶层循环依赖

        rows = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(Chapter.id.in_(chapter_ids))
            .all()
        )
        chapter_number_by_id = {cid: cnum for cid, cnum in rows}

    return {
        "id": audiobook_project.id,
        "project_id": audiobook_project.project_id,
        "status": audiobook_project.status,
        "total_chapters": audiobook_project.total_chapters,
        "completed_chapters": audiobook_project.completed_chapters,
        "failed_chapters": audiobook_project.failed_chapters,
        "total_duration": audiobook_project.total_duration,
        "total_cost": audiobook_project.total_cost,
        "created_at": audiobook_project.created_at.isoformat() if audiobook_project.created_at else None,
	        "chapter_audios": [
	            {
	                "id": ca.id,
	                "chapter_id": ca.chapter_id,
	                "chapter_number": chapter_number_by_id.get(ca.chapter_id),
	                "task_id": ca.task_id,  # 新增：返回task_id
	                "audio_path": ca.audio_path,
	                "duration": ca.duration,
	                "file_size": ca.file_size,
                "script_status": ca.script_status or "pending",
                "has_script": bool(ca.script_json),
                "has_review": bool(ca.script_review_json),
            }
            for ca in chapter_audios
        ],
    }


@router.get("/projects/by-project/{project_id:int}")
async def list_audiobook_projects(
    project_id: int,
    include_chapter_audios: bool = Query(False, description="是否包含章节音频列表"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的所有有声书项目"""
    # 验证权限
    project = ProjectRepository.get_user_project(db, current_user.id, project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或无权限",
        )

    audiobook_projects = AudiobookProjectRepository.list_by_project(db, project_id)

    if not include_chapter_audios:
        return [
            {
                "id": ap.id,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "total_duration": ap.total_duration,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
            }
            for ap in audiobook_projects
        ]

    audiobook_project_ids = [ap.id for ap in audiobook_projects]
    chapter_audios: List[ChapterAudio] = []
    if audiobook_project_ids:
        chapter_audios = (
            db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id.in_(audiobook_project_ids),
                ChapterAudio.deleted_at.is_(None),
            )
            .all()
        )

    audios_by_project: Dict[int, List[ChapterAudio]] = {}
    chapter_ids: List[int] = []
    for ca in chapter_audios:
        audios_by_project.setdefault(ca.audiobook_project_id, []).append(ca)
        chapter_ids.append(ca.chapter_id)

    chapter_number_by_id: Dict[int, int] = {}
    if chapter_ids:
        rows = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(Chapter.id.in_(list(set(chapter_ids))))
            .all()
        )
        chapter_number_by_id = {cid: cnum for cid, cnum in rows}

    results: List[Dict[str, Any]] = []
    for ap in audiobook_projects:
        audios = audios_by_project.get(ap.id, [])
        audios.sort(key=lambda ca: chapter_number_by_id.get(ca.chapter_id) or 0)

        results.append(
            {
                "id": ap.id,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "total_duration": ap.total_duration,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
                "chapter_audios": [
                    {
                        "id": ca.id,
                        "chapter_id": ca.chapter_id,
                        "chapter_number": chapter_number_by_id.get(ca.chapter_id),
                        "task_id": ca.task_id,
                        "audio_path": ca.audio_path,
                        "duration": ca.duration,
                        "file_size": ca.file_size,
                        "script_status": ca.script_status or "pending",
                        "has_script": bool(ca.script_json),
                        "has_review": bool(ca.script_review_json),
                    }
                    for ca in audios
                ],
            }
        )

    return results


@router.get("/projects")
async def list_user_audiobook_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的所有有声书项目（用于有声小说仪表盘）"""
    audiobook_projects = AudiobookProjectRepository.list_by_user(db, current_user.id)
    
    # 获取项目详细信息
    result = []
    for ap in audiobook_projects:
        project = ProjectRepository.get_user_project(db, current_user.id, ap.project_id)
        if project:
            result.append({
                "id": ap.id,
                "project_id": ap.project_id,
                "project_title": project.title,
                "project_description": project.description,
                "status": ap.status,
                "total_chapters": ap.total_chapters,
                "completed_chapters": ap.completed_chapters,
                "failed_chapters": ap.failed_chapters,
                "total_duration": ap.total_duration,
                "total_cost": ap.total_cost,
                "created_at": ap.created_at.isoformat() if ap.created_at else None,
                "updated_at": ap.updated_at.isoformat() if ap.updated_at else None,
            })
    
    return result


@router.post("/projects/{audiobook_project_id:int}/generate-audio-from-scripts", response_model=dict)
async def trigger_generate_audio_from_scripts(
    audiobook_project_id: int,
    request: GenerateAudioFromScriptsRequest,
    raw_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """触发基于已生成剧本的章节音频生成（两阶段流程第2阶段）。

    - 如果未显式指定 chapter_ids，则默认选择该有声书项目下 script_status == "approved" 且已存在 script_json 的章节。
    - 如果显式指定 chapter_ids，则请求阶段仅要求对应章节存在 script_json；执行阶段仍会过滤未通过评审的章节。
    """
    # 1. 验证有声书项目是否存在
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 2. 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 3. 选取需要生成音频的章节
    if request.chapter_ids:
        # 显式指定章节：只过滤有剧本的章节
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id.in_(request.chapter_ids),
            ChapterAudio.script_json.isnot(None),
        ).all()
    else:
        # 未指定章节：默认选择 script_status == "approved" 的章节
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.script_json.isnot(None),
            ChapterAudio.script_status == "approved",
        ).all()

    if not chapter_audios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可生成音频的章节，请先完成剧本生成与审核",
        )

    target_chapter_ids = [ca.chapter_id for ca in chapter_audios]
    precheck = build_audiobook_task_points_precheck(
        db=db,
        user_id=current_user.id,
        project_id=project.id,
        project_title=project.title,
        chapter_ids=target_chapter_ids,
        tts_provider=audiobook_project.tts_provider,
        audiobook_project_id=audiobook_project_id,
    )
    _ensure_audiobook_points_precheck_passed(precheck)

    # 4. 启动后台任务
    task_record = AudiobookTaskRepository.create_task(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=None,
        task_type="audio_from_scripts",
        total_units=len(target_chapter_ids),
    )
    tts_model = (request.tts_model or "qwen3-tts-flash").strip()
    signature = celery_app.signature(
        "audiobook.run_audio_from_scripts",
        args=[
            task_record.id,
            audiobook_project_id,
            target_chapter_ids,
            tts_model,
        ],
    )
    async_result = signature.delay()
    AudiobookTaskRepository.attach_celery_id(db, task_record.id, async_result.id)
    _enqueue_chapter_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_ids=target_chapter_ids,
        run_type="audio_from_scripts",
        celery_task_id=async_result.id,
        tts_model=tts_model,
        output_format=request.output_format,
        narration_style=request.narration_style,
        narration_style_prompt=request.narration_style_prompt,
    )

    try:
        record_audiobook_billing_freeze(
            db=db,
            actor_user_id=current_user.id,
            actor_username=current_user.username,
            audiobook_project_id=audiobook_project_id,
            chapter_ids=target_chapter_ids,
            request_context=raw_request,
        )
    except Exception as exc:
        logger.warning("记录二阶段有声书积分冻结失败 audiobook_project_id=%s: %s", audiobook_project_id, exc)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "chapter_ids": target_chapter_ids,
        "job_id": async_result.id,
        "message": "已启动基于剧本的音频生成任务",
    }



@router.delete("/projects/{audiobook_project_id:int}")
async def delete_audiobook_project(
    audiobook_project_id: int,
    delete_reason: Optional[str] = None,
    delete_files: bool = False,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除有声书项目（支持软删除和硬删除）
    
    工作流：
    1. 验证权限
    2. 执行软删除并记录审计日志
    3. 可选：删除物理文件（delete_files=true时）
    """
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除有声书项目: audiobook_project_id={audiobook_project_id}, delete_files={delete_files}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None
        if payload.get("delete_files") is not None:
            delete_files = bool(payload.get("delete_files"))

    # 1. 验证有声书项目权限
    audiobook_project = db.query(AudiobookProject).filter(AudiobookProject.id == audiobook_project_id).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限删除此项目"
        )
    
    # 2. 执行软删除并记录审计日志
    audit_log = AudiobookProjectRepository.soft_delete(
        db=db,
        audiobook_project_id=audiobook_project_id,
        user_id=current_user.id,
        user_name=current_user.username,
        delete_reason=delete_reason
    )
    
    if not audit_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在或已被删除"
        )
    
    # 3. 可选：删除物理文件
    deleted_files = 0
    failed_files = []
    
    if delete_files:
        # 获取所有章节音频并删除文件
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id
        ).all()
        
        for chapter_audio in chapter_audios:
            if chapter_audio.audio_path and os.path.exists(chapter_audio.audio_path):
                try:
                    os.remove(chapter_audio.audio_path)
                    deleted_files += 1
                    logger.info(f"✅ 删除文件: {chapter_audio.audio_path}")
                except Exception as e:
                    logger.error(f"❌ 删除文件失败: {chapter_audio.audio_path}, 错误: {e}")
                    failed_files.append(chapter_audio.audio_path)
    
    logger.info(f"✅ 有声书项目软删除成功: audiobook_project_id={audiobook_project_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "有声书项目已删除",
        "audit_id": audit_log.id,
        "deleted_files": deleted_files,
        "failed_files": failed_files,
        "affected_chapters": audit_log.affected_chapters,
        "affected_tasks": audit_log.affected_tasks,
        "total_size": audit_log.total_size
    }


@router.delete("/chapter-audios/{chapter_audio_id:int}")
async def delete_chapter_audio(
    chapter_audio_id: int,
    delete_reason: Optional[str] = None,
    delete_file: bool = False,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除章节音频（支持软删除和硬删除）
    
    工作流：
    1. 验证权限
    2. 执行软删除并记录审计日志
    3. 可选：删除物理文件（delete_file=true时）
    """
    logger.info(f"🗑️ 用户 {current_user.id} 请求删除章节音频: chapter_audio_id={chapter_audio_id}, delete_file={delete_file}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None

        raw_delete_file = payload.get("delete_file")
        if raw_delete_file is None:
            raw_delete_file = payload.get("delete_files")
        if raw_delete_file is not None:
            delete_file = bool(raw_delete_file)

    # 1. 获取章节音频
    chapter_audio = ChapterAudioRepository.get_by_id(db, chapter_audio_id)
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 2. 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限删除此章节音频"
        )
    
    # 3. 执行软删除并记录审计日志
    audit_log = ChapterAudioRepository.soft_delete(
        db=db,
        chapter_audio_id=chapter_audio_id,
        user_id=current_user.id,
        user_name=current_user.username,
        delete_reason=delete_reason
    )
    
    if not audit_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在或已被删除"
        )
    
    # 4. 可选：删除物理文件
    deleted_file = False
    failed_file = None
    
    if delete_file and chapter_audio.audio_path:
        if os.path.exists(chapter_audio.audio_path):
            try:
                os.remove(chapter_audio.audio_path)
                deleted_file = True
                logger.info(f"✅ 删除文件: {chapter_audio.audio_path}")
            except Exception as e:
                logger.error(f"❌ 删除文件失败: {chapter_audio.audio_path}, 错误: {e}")
                failed_file = chapter_audio.audio_path
    
    logger.info(f"✅ 章节音频软删除成功: chapter_audio_id={chapter_audio_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "章节音频已删除",
        "audit_id": audit_log.id,
        "deleted_file": deleted_file,
        "failed_file": failed_file,
        "affected_tasks": audit_log.affected_tasks,
        "file_size": audit_log.total_size
    }


@router.post("/projects/{audiobook_project_id:int}/restore")
async def restore_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    恢复已删除的有声书项目
    
    工作流：
    1. 验证权限
    2. 恢复项目及关联的章节音频
    3. 更新审计日志
    """
    logger.info(f"♻️ 用户 {current_user.id} 请求恢复有声书项目: audiobook_project_id={audiobook_project_id}")
    
    # 1. 验证有声书项目是否存在
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )

    # 2. 验证原始项目权限
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限恢复此项目"
        )

    # 3. 恢复项目
    restored_project = AudiobookProjectRepository.restore(
        db=db,
        audiobook_project_id=audiobook_project_id,
        user_id=current_user.id
    )
    
    if not restored_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="项目不存在或未被删除"
        )
    
    logger.info(f"✅ 有声书项目恢复成功: audiobook_project_id={audiobook_project_id}")
    
    return {
        "success": True,
        "message": "有声书项目已恢复",
        "project_id": restored_project.id,
        "restored_at": utc_now().isoformat()
    }


@router.post("/chapter-audios/{chapter_audio_id:int}/restore")
async def restore_chapter_audio(
    chapter_audio_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    恢复已删除的章节音频
    
    工作流：
    1. 验证权限
    2. 恢复章节音频
    3. 更新审计日志
    """
    logger.info(f"♻️ 用户 {current_user.id} 请求恢复章节音频: chapter_audio_id={chapter_audio_id}")
    
    # 1. 获取章节音频
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.id == chapter_audio_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 2. 验证权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限恢复此章节音频"
        )
    
    # 3. 恢复章节音频
    restored_audio = ChapterAudioRepository.restore(
        db=db,
        chapter_audio_id=chapter_audio_id,
        user_id=current_user.id
    )
    
    if not restored_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在或未被删除"
        )
    
    logger.info(f"✅ 章节音频恢复成功: chapter_audio_id={chapter_audio_id}")
    
    return {
        "success": True,
        "message": "章节音频已恢复",
        "chapter_audio_id": restored_audio.id,
        "restored_at": utc_now().isoformat()
    }


@router.get("/projects/deleted")
async def list_deleted_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 50
):
    """
    获取用户已删除的有声书项目列表（回收站）
    
    返回：已删除的项目列表，包含审计信息
    """
    logger.info(f"📋 用户 {current_user.id} 查询已删除项目列表")
    
    # 获取已删除的项目
    deleted_projects = AudiobookProjectRepository.list_deleted(
        db=db,
        user_id=current_user.id,
        limit=limit
    )
    
    # 获取审计日志
    project_ids = [p.id for p in deleted_projects]
    audit_logs = db.query(AudiobookDeleteAudit).filter(
        AudiobookDeleteAudit.target_id.in_(project_ids),
        AudiobookDeleteAudit.delete_type == 'project'
    ).all()
    
    # 构建审计日志映射
    audit_map = {log.target_id: log for log in audit_logs}
    
    # 构建响应
    result = []
    source_project_ids = list({p.project_id for p in deleted_projects})
    source_title_by_id: Dict[int, str] = {}
    if source_project_ids:
        rows = (
            db.query(Project.id, Project.title)
            .filter(Project.id.in_(source_project_ids))
            .all()
        )
        source_title_by_id = {pid: title for pid, title in rows}

    for project in deleted_projects:
        audit = audit_map.get(project.id)
        result.append({
            "id": project.id,
            "project_id": project.project_id,
            "project_title": source_title_by_id.get(project.project_id),
            "status": project.status,
            "total_chapters": project.total_chapters,
            "completed_chapters": project.completed_chapters,
            "total_duration": project.total_duration,
            "deleted_at": project.deleted_at.isoformat() if project.deleted_at else None,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "audit_id": audit.id if audit else None,
            "delete_reason": audit.delete_reason if audit else None,
            "affected_chapters": audit.affected_chapters if audit else 0,
            "affected_tasks": audit.affected_tasks if audit else 0,
            "total_size": audit.total_size if audit else 0,
            "restored_at": audit.restored_at.isoformat() if audit and audit.restored_at else None,
        })
    
    logger.info(f"✅ 查询到 {len(result)} 个已删除项目")
    
    return {
        "success": True,
        "count": len(result),
        "projects": result
    }


@router.get("/tasks/{task_id}/status", response_model=AudiobookTaskStatus)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询指定任务的持久化队列状态。"""
    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )
    return build_task_status_response(task)


@router.get("/tasks", response_model=List[AudiobookTaskStatus])
async def list_all_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户最近的有声书后台任务。"""
    tasks = AudiobookTaskRepository.list_tasks_for_user(db, current_user.id)
    return [build_task_status_response(task) for task in tasks]


@router.get("/download/{audiobook_project_id}/{chapter_id}")
async def download_chapter_audio(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    下载章节音频文件
    
    返回：MP3音频文件流
    """
    logger.info(f"🎧 用户 {current_user.id} 下载音频: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 验证有声书项目权限
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 2. 获取章节音频记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    # 3. 检查文件是否存在
    if not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音频文件路径不存在"
        )
    
    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"音频文件不存在: {file_path}"
        )
    
    # 4. 获取章节标题作为文件名
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    filename = f"第{chapter.chapter_number}章-{chapter.title}.mp3" if chapter else f"chapter_{chapter_id}.mp3"
    
    # URL编码文件名（支持中文）
    encoded_filename = quote(filename)
    
    logger.info(f"✅ 返回音频文件: {file_path}")
    
    # 5. 返回文件
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=filename,  # 保留原始文件名（供浏览器显示）
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.get("/stream/{audiobook_project_id}/{chapter_id}")
async def stream_chapter_audio(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    流式播放章节音频（用于在线播放）
    
    返回：音频文件流（支持Range请求）
    """
    logger.info(f"🎵 用户 {current_user.id} 在线播放: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 验证权限（同下载接口）
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问"
        )
    
    # 2. 获取音频文件路径
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio or not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节音频不存在"
        )
    
    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"音频文件不存在: {file_path}"
        )
    
    logger.info(f"✅ 流式播放文件: {file_path}")
    
    # 3. 返回文件流（inline模式，浏览器直接播放）
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range"
        }
    )


# ==================== 剧本编辑与音频生成（两阶段相关） ====================

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def get_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取指定章节的有声剧本与评审结果。

    仅返回最近一次生成/保存的剧本快照，不做版本历史。
    """
    # 验证有声书项目
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 获取章节剧本记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()

    if not chapter_audio or not chapter_audio.script_json:
        fallback = (
            db.query(ChapterAudio)
            .join(AudiobookProject, ChapterAudio.audiobook_project_id == AudiobookProject.id)
            .filter(
                AudiobookProject.project_id == project.id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.script_json.isnot(None),
            )
            .order_by(ChapterAudio.updated_at.desc())
            .first()
        )

        if fallback:
            if not chapter_audio:
                chapter_audio = ChapterAudio(
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                )
                db.add(chapter_audio)

            chapter_audio.script_json = fallback.script_json
            chapter_audio.script_review_json = fallback.script_review_json
            chapter_audio.script_status = fallback.script_status or "pending"
            chapter_audio.segment_count = fallback.segment_count
            chapter_audio.dialogue_count = fallback.dialogue_count
            chapter_audio.narration_count = fallback.narration_count
            chapter_audio.character_count = fallback.character_count
            db.commit()
            logger.info(
                "♻️ 章节 %s 复用历史剧本供 audiobook_project_id=%s 使用",
                chapter_id,
                audiobook_project_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="章节剧本不存在，请先生成剧本",
            )

    try:
        script_segments = json.loads(chapter_audio.script_json)
    except Exception as e:
        logger.error(f"❌ 解析章节剧本JSON失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="章节剧本数据损坏，请尝试重新生成",
        )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except Exception as e:
            logger.warning(f"⚠️ 解析章节剧本评审JSON失败 chapter_id={chapter_id}: {e}")

    return {
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status or "pending",
        "script_segments": script_segments,
        "script_review": script_review,
    }


@router.put("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def update_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    request: ChapterScriptUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新指定章节的有声剧本。

    - script_segments：覆盖写入最近一次剧本快照
    - script_status：可选，pending/reviewed/approved
    """
    # 验证有声书项目
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    # 验证原始项目权限
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    # 验证章节是否属于该项目
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.project_id == project.id,
    ).first()

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )

    # 获取或创建章节音频记录
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()

    if not chapter_audio:
        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        db.add(chapter_audio)

    # 覆盖写入剧本
    try:
        chapter_audio.script_json = json.dumps(
            request.script_segments or [], ensure_ascii=False
        )
    except Exception as e:
        logger.error(f"❌ 序列化章节剧本失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="剧本数据格式不合法",
        )

    # 更新脚本状态（如有）
    if request.script_status:
        if request.script_status not in {"pending", "reviewed", "approved"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的script_status，必须为 pending/reviewed/approved",
            )
        chapter_audio.script_status = request.script_status

    # 剧本变化后，清空最终音频评审，防止混淆
    chapter_audio.final_audio_review_json = None

    db.commit()
    db.refresh(chapter_audio)

    return {
        "success": True,
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status,
    }


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/preview")
async def preview_script_segment_audio(
    audiobook_project_id: int,
    chapter_id: int,
    request: ScriptSegmentPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单段剧本片段音频试听（不落库）"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="有声书项目不存在",
        )

    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问",
        )

    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.project_id == project.id,
    ).first()
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

    text = str(segment.get("text") or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="台词不能为空",
        )

    tts_model = (request.tts_model or "qwen3-tts-flash").strip()
    if tts_model not in {"qwen3-tts-flash", "cosyvoice-v3-plus", "minimax-speech-2.8-hd", "minimax-speech-2.8-turbo"}:
        if tts_model.startswith("minimax-speech"):
            tts_model = "minimax-speech-2.8-hd"
        elif tts_model.startswith("qwen3-tts"):
            tts_model = "qwen3-tts-flash"
        else:
            tts_model = "qwen3-tts-flash"

    preview_type = str(request.preview_type or "voice").strip().lower()
    if preview_type not in {"voice", "sfx", "bgm", "mix"}:
        preview_type = "voice"

    voice_manager = create_voice_manager(tts_model=tts_model, llm_client=None)
    effective_voice_mapping = dict(audiobook_project.voice_mapping or {})

    config_data = {}
    if project.audio_config:
        config_data = parse_project_audio_config(project.audio_config or "")
    audio_fx = get_audio_fx(config_data) or {}
    for item in get_characters_for_model(config_data, tts_model):
        name = item.get("name")
        if not name:
            continue
        effective_voice_mapping[name] = {
            "voice_id": item.get("voice_id"),
            "volume": item.get("volume", 50),
            "speed": item.get("speed"),
            "pitch": item.get("pitch"),
        }

    if effective_voice_mapping:
        try:
            voice_manager.apply_project_voice_mapping(effective_voice_mapping)
        except Exception as exc:
            logger.warning("单段音色映射失败: %s", exc)

    speaker = str(segment.get("speaker") or "旁白").strip() or "旁白"
    if speaker in {"旁白", "narrator", "Narrator"}:
        voice_profile = voice_manager.get_narrator_voice()
    else:
        voice_profile = voice_manager.get_voice(speaker)
        if not voice_profile:
            voice_profile = voice_manager.assign_voice(speaker)

    emotion = str(segment.get("emotion") or "neutral").strip() or "neutral"
    instruct_emotion = str(segment.get("instruct_emotion") or "").strip()
    emotion_for_params = instruct_emotion or emotion

    voice_params_dict = voice_profile.get_tts_params(emotion_for_params)
    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}
    for key, value in segment_voice_params.items():
        if value is None or key == "speaker":
            continue
        voice_params_dict[key] = value

    if "rate" not in voice_params_dict and "speed" in voice_params_dict:
        voice_params_dict["rate"] = voice_params_dict["speed"]

    voice_params_dict["pause_before"] = segment_voice_params.get(
        "pause_before",
        segment.get("pause_before", 0.0),
    )
    voice_params_dict["pause_after"] = segment_voice_params.get(
        "pause_after",
        segment.get("pause_after", 0.0),
    )

    voice_params_dict["segment_speaker"] = speaker
    voice_params_dict["segment_type"] = segment.get("type", "")
    voice_params_dict["instruct_emotion"] = instruct_emotion
    voice_params_dict["instruct_scene"] = str(segment.get("instruct_scene") or "").strip()
    voice_params_dict["instruct_role"] = str(segment.get("instruct_role") or "").strip()
    voice_params_dict["instruct_identity"] = str(segment.get("instruct_identity") or "").strip()

    if (
        instruct_emotion
        or voice_params_dict["instruct_scene"]
        or voice_params_dict["instruct_role"]
        or voice_params_dict["instruct_identity"]
    ):
        voice_params_dict["use_instruct_mode"] = True

    def estimate_duration_seconds(text_value: str) -> float:
        return max(3.0, len(text_value) / 10.0)

    def normalize_sound_effects(segment_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        raw_effects = segment_data.get("sound_effects")
        if isinstance(raw_effects, list) and raw_effects:
            for effect in raw_effects:
                if not effect:
                    continue
                if isinstance(effect, dict):
                    name = effect.get("name") or effect.get("effect_id") or effect.get("id")
                    if not name:
                        continue
                    specs.append(
                        {
                            "name": str(name).strip(),
                            "volume": effect.get("volume"),
                            "delay": effect.get("delay", effect.get("start_time", 0.0)),
                            "duration": effect.get("duration"),
                            "fade_in": effect.get("fade_in"),
                            "fade_out": effect.get("fade_out"),
                            "layer": effect.get("layer"),
                            "timing": effect.get("timing"),
                            "file": effect.get("file") or effect.get("audio_file"),
                        }
                    )
                else:
                    name = str(effect).strip()
                    if name:
                        specs.append({"name": name})
        else:
            simple = segment_data.get("sound_effects_simple") or []
            if isinstance(simple, list):
                for name in simple:
                    if not name:
                        continue
                    specs.append({"name": str(name).strip()})
            elif isinstance(simple, str) and simple.strip():
                for name in simple.split(","):
                    if not name.strip():
                        continue
                    specs.append({"name": name.strip()})
        return specs

    def build_effect_timeline(effect_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not effect_specs:
            return []
        designer = SoundEffectDesigner(llm_client=None)
        timeline: List[Dict[str, Any]] = []
        for spec in effect_specs:
            name = spec.get("name")
            if not name:
                continue
            cue = designer._match_effect(str(name), 0.0, "preview")
            layer = str(spec.get("layer") or "").strip().lower()
            effect_type = cue.effect_type.value if cue else "action"
            if layer in {"bottom", "atmosphere", "environment", "ambient"}:
                effect_type = "environment"
            file_ref = spec.get("file") or (cue.audio_file if cue else "")
            if not file_ref:
                continue
            timeline.append(
                {
                    "timestamp": float(spec.get("delay") or 0.0),
                    "type": effect_type,
                    "description": str(name),
                    "file": file_ref,
                    "volume": spec.get("volume", cue.volume if cue else 0.5),
                    "duration": spec.get("duration", cue.duration if cue else None),
                    "fade_in": spec.get("fade_in", cue.fade_in if cue else 0.0),
                    "fade_out": spec.get("fade_out", cue.fade_out if cue else 0.0),
                    "loop": bool(
                        spec.get("timing") == "continuous"
                        or spec.get("loop")
                        or (cue.loop if cue else False)
                        or effect_type == "environment"
                    ),
                }
            )
        return timeline

    def resolve_effect_path(file_ref: str, name_hint: str, base_dir: Path) -> Optional[Path]:
        if not file_ref:
            return None
        effect_path = Path(file_ref)
        if not effect_path.is_absolute():
            effect_path = base_dir / file_ref
        if effect_path.exists():
            return effect_path
        candidate_name = Path(file_ref).stem or name_hint
        if candidate_name:
            for candidate in (base_dir / "sound_effects").rglob(f"{candidate_name}.*"):
                return candidate
        return None

    def apply_sound_effects_preview(
        base_audio: bytes,
        timeline: List[Dict[str, Any]],
        audio_mixer: AudioMixer,
        base_dir: Path,
    ) -> bytes:
        if not base_audio or not timeline:
            return base_audio
        mixed_audio = base_audio
        ducking_enabled = audio_fx.get("sound_effect_ducking", True)
        ducking_priority = audio_fx.get("sound_effect_priority", "dialogue")
        ducking_threshold_dbfs = audio_fx.get("sound_effect_ducking_threshold_dbfs", -35.0)
        ducking_reduction_db = audio_fx.get("sound_effect_ducking_reduction_db", -6.0)
        ducking_chunk_ms = audio_fx.get("sound_effect_ducking_chunk_ms", 250)
        base_gain_map = {
            "environment": -14.0,
            "action": -14.0,
            "emotion": -16.0,
            "transition": -18.0,
        }
        for item in timeline:
            file_ref = item.get("file")
            effect_path = resolve_effect_path(
                str(file_ref or ""), str(item.get("description") or ""), base_dir
            )
            if not effect_path or not effect_path.exists():
                logger.warning("?? 试听音效文件不存在: %s", effect_path or file_ref)
                continue

            effect_type_str = item.get("type", "action")
            base_gain = base_gain_map.get(effect_type_str, -16.0)
            timeline_volume = item.get("volume", 0.5)
            try:
                timeline_volume = float(timeline_volume)
            except (TypeError, ValueError):
                timeline_volume = 0.5
            timeline_volume = max(0.05, min(1.0, timeline_volume))
            relative = timeline_volume / 0.5
            volume_adjust_db = 20 * math.log10(relative)
            effect_volume_offset = base_gain + volume_adjust_db

            duration = item.get("duration")
            fade_in = item.get("fade_in", 0.0)
            fade_out = item.get("fade_out", 0.0)
            loop = bool(item.get("loop")) or effect_type_str == "environment"

            try:
                with effect_path.open("rb") as f:
                    effect_bytes = f.read()
                position_ms = int(float(item.get("timestamp") or 0.0) * 1000)
                effect_duration_ms = None
                try:
                    if duration is not None:
                        duration_val = float(duration)
                        if duration_val <= 0:
                            effect_duration_ms = None
                        else:
                            effect_duration_ms = int(duration_val * 1000)
                except (TypeError, ValueError):
                    effect_duration_ms = None
                fade_in_ms = int(float(fade_in) * 1000) if fade_in else 0
                fade_out_ms = int(float(fade_out) * 1000) if fade_out else 0
                mixed_audio = audio_mixer.add_sound_effect(
                    mixed_audio,
                    effect_bytes,
                    position_ms=position_ms,
                    effect_volume_offset=effect_volume_offset,
                    effect_duration_ms=effect_duration_ms,
                    fade_in_ms=fade_in_ms,
                    fade_out_ms=fade_out_ms,
                    loop_fill=bool(loop),
                    ducking_enabled=bool(ducking_enabled),
                    ducking_priority=str(ducking_priority or "dialogue"),
                    ducking_threshold_dbfs=float(ducking_threshold_dbfs),
                    ducking_reduction_db=float(ducking_reduction_db),
                    ducking_chunk_ms=int(ducking_chunk_ms),
                )
            except Exception as exc:
                logger.warning("?? 叠加试听音效失败 %s: %s", effect_path, exc)
        return mixed_audio

    def normalize_music_cue(segment_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raw_cue = segment_data.get("music_cue")
        if isinstance(raw_cue, dict):
            style = raw_cue.get("style") or raw_cue.get("name") or raw_cue.get("cue")
            file_ref = raw_cue.get("file") or raw_cue.get("audio_file")
            return {
                "style": str(style or "").strip(),
                "file": file_ref,
                "volume": raw_cue.get("volume", 0.2),
                "fade_in": raw_cue.get("fade_in", 0.0),
                "fade_out": raw_cue.get("fade_out", 0.0),
                "duration": raw_cue.get("duration"),
                "start_time": raw_cue.get("start_time", 0.0),
                "sync_with_dialogue": raw_cue.get("sync_with_dialogue", True),
                "dialogue_volume_reduction": raw_cue.get("dialogue_volume_reduction", 0.0),
                "mood": raw_cue.get("mood"),
            }
        if isinstance(raw_cue, str) and raw_cue.strip():
            return {
                "style": raw_cue.strip(),
                "file": None,
                "volume": 0.2,
                "fade_in": 0.0,
                "fade_out": 0.0,
                "duration": None,
                "start_time": 0.0,
                "sync_with_dialogue": True,
                "dialogue_volume_reduction": 0.0,
                "mood": None,
            }
        simple_cue = segment_data.get("music_cue_simple")
        if isinstance(simple_cue, str) and simple_cue.strip():
            return {
                "style": simple_cue.strip(),
                "file": None,
                "volume": 0.2,
                "fade_in": 0.0,
                "fade_out": 0.0,
                "duration": None,
                "start_time": 0.0,
                "sync_with_dialogue": True,
                "dialogue_volume_reduction": 0.0,
                "mood": None,
            }
        return None

    def infer_music_mood(emotion_value: str) -> str:
        raw = (emotion_value or "").lower()
        if any(key in raw for key in ["sad", "悲", "伤"]):
            return "sad"
        if any(key in raw for key in ["happy", "joy", "欢", "乐"]):
            return "joyful"
        if any(key in raw for key in ["tense", "angry", "fear", "紧张", "恐惧", "愤怒"]):
            return "tense"
        if any(key in raw for key in ["romantic", "love", "浪漫"]):
            return "romantic"
        if any(key in raw for key in ["mysterious", "神秘"]):
            return "mysterious"
        if any(key in raw for key in ["epic", "史诗", "宏大"]):
            return "epic"
        return "peaceful"

    def load_music_index(base_dir: Path) -> List[Dict[str, Any]]:
        index_path = base_dir / "music_index.json"
        if not index_path.exists():
            return []
        try:
            raw = index_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("?? 读取音乐索引失败: %s", exc)
            return []

    def resolve_music_path(
        file_ref: Optional[str],
        style_hint: str,
        mood_hint: str,
        base_dir: Path,
        music_index: List[Dict[str, Any]],
    ) -> Optional[Path]:
        if file_ref:
            music_path = Path(file_ref)
            if not music_path.is_absolute():
                music_path = base_dir / file_ref
            if music_path.exists():
                return music_path
            candidate_name = Path(file_ref).stem
            if candidate_name:
                for candidate in (base_dir / "music_cache").rglob(f"{candidate_name}.*"):
                    return candidate

        style_hint = (style_hint or "").strip()
        mood_hint = (mood_hint or "").strip().lower()

        if music_index:
            if style_hint:
                for entry in music_index:
                    style = str(entry.get("style") or "").strip()
                    if style and (style_hint in style or style in style_hint):
                        file_path = entry.get("file_path")
                        if file_path and Path(file_path).exists():
                            return Path(file_path)
            if mood_hint:
                for entry in music_index:
                    if str(entry.get("mood") or "").strip().lower() == mood_hint:
                        file_path = entry.get("file_path")
                        if file_path and Path(file_path).exists():
                            return Path(file_path)
            for entry in music_index:
                file_path = entry.get("file_path")
                if file_path and Path(file_path).exists():
                    return Path(file_path)

        for candidate in (base_dir / "music_cache").rglob("*.mp3"):
            return candidate
        return None

    def apply_background_music_preview(
        base_audio: bytes,
        cue: Dict[str, Any],
        audio_mixer: AudioMixer,
        base_dir: Path,
        duration_seconds: float,
    ) -> bytes:
        if not base_audio or not cue:
            return base_audio
        music_index = load_music_index(base_dir)
        mood_hint = str(cue.get("mood") or infer_music_mood(emotion)).strip()
        style_hint = str(cue.get("style") or "").strip()
        music_path = resolve_music_path(
            cue.get("file"),
            style_hint,
            mood_hint,
            base_dir,
            music_index,
        )
        if not music_path or not music_path.exists():
            logger.warning("?? 试听配乐文件不存在: %s", music_path)
            return base_audio

        base_bgm_volume_db = audio_fx.get("base_bgm_volume", -36)
        try:
            volume_val = float(cue.get("volume", 0.2))
        except (TypeError, ValueError):
            volume_val = 0.2
        volume_val = max(0.05, min(1.0, volume_val))
        relative = volume_val / 0.2
        volume_adjust_db = 20 * math.log10(relative) if relative > 0 else -40
        bgm_volume_offset = base_bgm_volume_db + volume_adjust_db - 3

        try:
            bgm_crossfade_ms = int(audio_fx.get("bgm_crossfade_ms") or 0)
        except Exception:
            bgm_crossfade_ms = 0
        if bgm_crossfade_ms < 0:
            bgm_crossfade_ms = 0

        try:
            with music_path.open("rb") as f:
                bgm_bytes = f.read()
            start_ms = max(0, int(float(cue.get("start_time") or 0.0) * 1000))
            duration_ms = None
            try:
                if cue.get("duration") is not None:
                    duration_ms = max(0, int(float(cue.get("duration") or 0.0) * 1000))
                else:
                    duration_ms = max(0, int(duration_seconds * 1000))
            except (TypeError, ValueError):
                duration_ms = None
            fade_in_ms = max(0, int(float(cue.get("fade_in") or 0.0) * 1000))
            fade_out_ms = max(0, int(float(cue.get("fade_out") or 0.0) * 1000))
            if bgm_crossfade_ms > 0:
                fade_in_ms = max(fade_in_ms, bgm_crossfade_ms)
                fade_out_ms = max(fade_out_ms, bgm_crossfade_ms)

            return audio_mixer.add_background_music(
                base_audio,
                bgm_bytes,
                bgm_volume_offset=int(bgm_volume_offset),
                position_ms=start_ms,
                duration_ms=duration_ms,
                fade_in_ms=fade_in_ms,
                fade_out_ms=fade_out_ms,
                loop_fill=True,
                sync_with_dialogue=bool(cue.get("sync_with_dialogue", True)),
                dialogue_volume_reduction=float(cue.get("dialogue_volume_reduction") or 0.0),
            )
        except Exception as exc:
            logger.warning("?? 叠加试听配乐失败 %s: %s", music_path, exc)
            return base_audio

    voice_audio: Optional[bytes] = None
    if preview_type in {"voice", "mix"}:
        preview_retry = RetryConfig(
            max_retries=4,
            base_delay=1.0,
            max_delay=8.0,
            exponential_base=2.0,
            jitter=True,
        )
        try:
            voice_audio = await runtime_synthesize_speech(
                text=text,
                voice_params=voice_params_dict,
                emotion=emotion_for_params,
                model_id=tts_model,
                enable_cache=False,
                max_concurrent=1,
                request_delay=0.0,
                retry_config=preview_retry,
            )
        except Exception as exc:
            logger.warning("单段TTS试听失败: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
            ) from exc

        if not voice_audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
            )

        if preview_type == "voice":
            media_type = "audio/wav" if voice_audio.startswith(b"RIFF") else "audio/mpeg"
            return Response(content=voice_audio, media_type=media_type)

    audio_mixer = AudioMixer()
    base_dir = Path(__file__).resolve().parents[3] / "data" / "audio_library"
    estimated_duration = estimate_duration_seconds(text)

    effect_timeline: List[Dict[str, Any]] = []
    if preview_type in {"sfx", "mix"}:
        effect_specs = normalize_sound_effects(segment)
        effect_timeline = build_effect_timeline(effect_specs)
        if preview_type == "sfx" and not effect_timeline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该片段未配置音效，无法试听音效",
            )

    music_cue = None
    if preview_type in {"bgm", "mix"}:
        music_cue = normalize_music_cue(segment)
        if preview_type == "bgm" and not music_cue:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该片段未配置配乐，无法试听配乐",
            )

    base_duration = estimated_duration
    if effect_timeline:
        for item in effect_timeline:
            item_duration = item.get("duration")
            try:
                if item_duration is None:
                    item_duration = estimated_duration if item.get("loop") else 2.0
                item_duration = float(item_duration or 0.0)
            except (TypeError, ValueError):
                item_duration = 0.0
            try:
                timestamp = float(item.get("timestamp") or 0.0)
            except (TypeError, ValueError):
                timestamp = 0.0
            base_duration = max(base_duration, timestamp + max(0.0, item_duration))
    if music_cue:
        try:
            start_time = float(music_cue.get("start_time") or 0.0)
        except (TypeError, ValueError):
            start_time = 0.0
        cue_duration = music_cue.get("duration")
        try:
            cue_duration = float(cue_duration) if cue_duration is not None else estimated_duration
        except (TypeError, ValueError):
            cue_duration = estimated_duration
        base_duration = max(base_duration, start_time + max(0.0, cue_duration))

    if preview_type in {"sfx", "bgm"}:
        base_audio = audio_mixer.create_silence(
            int(max(1.0, base_duration) * 1000),
            output_format="mp3",
            bitrate="128k",
        )
        if not base_audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="音频混音组件不可用，无法生成试听音频",
            )
    else:
        base_audio = voice_audio or b""

    mixed_audio = base_audio
    if effect_timeline:
        mixed_audio = apply_sound_effects_preview(
            mixed_audio,
            effect_timeline,
            audio_mixer,
            base_dir,
        )
    if music_cue:
        mixed_audio = apply_background_music_preview(
            mixed_audio,
            music_cue,
            audio_mixer,
            base_dir,
            base_duration,
        )

    if not mixed_audio:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="试听音频生成失败，请稍后重试",
        )

    return Response(content=mixed_audio, media_type="audio/mpeg")


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


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/review-status")
async def get_chapter_review_status(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节整体审查状态
    
    返回：
    - 总片段数
    - 已审查片段数
    - 平均质量评分
    - 标记需要重新生成的片段索引
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
    
    # 加载剧本和审查记录
    try:
        segments = json.loads(chapter_audio.script_json)
    except:
        segments = []
    
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            review_data = json.loads(chapter_audio.segment_reviews_json)
        except:
            pass
    
    total_segments = len(segments)
    reviewed_segments = len(review_data)
    
    # 计算平均质量评分
    scores = []
    flagged = []
    for idx, review in review_data.items():
        if review.get("quality_score"):
            scores.append(review["quality_score"])
        if review.get("needs_regenerate"):
            flagged.append(int(idx))
    
    avg_score = sum(scores) / len(scores) if scores else None
    
    return {
        "chapter_id": chapter_id,
        "total_segments": total_segments,
        "reviewed_segments": reviewed_segments,
        "avg_quality_score": avg_score,
        "flagged_segments": flagged,
    }


@router.get("/narration-styles")
async def list_narration_styles(
    current_user: User = Depends(get_current_user),
):
    """获取所有叙事风格预设列表"""
    return get_all_narration_styles()


@router.get("/narration-styles/{style_id}")
async def get_narration_style(
    style_id: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定叙事风格预设详情"""
    preset = get_narration_style_preset(style_id)
    if not preset:
        raise HTTPException(status_code=404, detail="叙事风格预设不存在")
    return preset


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/subtitle")
async def get_chapter_subtitle(
    audiobook_project_id: int,
    chapter_id: int,
    format: str = Query("srt", regex="^(srt|vtt|ass)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节字幕文件"""
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
    
    if not chapter_audio.subtitle_path:
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    subtitle_file = chapter_audio.subtitle_path
    if format == "vtt":
        subtitle_file = subtitle_file.replace(".srt", ".vtt")
    elif format == "ass":
        subtitle_file = subtitle_file.replace(".srt", ".ass")
    
    if not os.path.exists(subtitle_file):
        raise HTTPException(status_code=404, detail="字幕文件不存在")
    
    return FileResponse(
        subtitle_file,
        media_type="text/plain",
        filename=f"chapter_{chapter_id}.{format}",
    )


@router.get(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/checkpoint",
    response_model=GenerationCheckpointResponse,
)
async def get_generation_checkpoint(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取生成断点信息（用于断点续传）"""
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
    return _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/resume-generation")
async def resume_chapter_generation(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从断点继续生成章节音频"""
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
    
    if not chapter_audio.generation_progress_json:
        raise HTTPException(status_code=400, detail="没有可恢复的生成进度")
    
    progress_data = json.loads(chapter_audio.generation_progress_json)
    completed_indices = progress_data.get("completed_segment_indices", [])
    cached_paths = progress_data.get("cached_audio_paths", {})
    
    logger.info(f"🔄 恢复章节 {chapter_id} 生成: 已完成 {len(completed_indices)} 个片段")
    
    return {
        "message": "已恢复生成进度",
        "completed_segments": len(completed_indices),
        "cached_audio_paths": cached_paths,
    }


@router.get("/projects/{audiobook_project_id:int}/browser-player")
async def get_browser_player_data(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取浏览器播放器所需数据（章节列表、音频URL、字幕URL）"""
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
    
    chapters_data = []
    for chapter_audio in audiobook_project.chapter_audios:
        chapter = db.query(Chapter).filter(Chapter.id == chapter_audio.chapter_id).first()
        if not chapter:
            continue
        
        chapter_info = {
            "chapter_id": chapter_audio.chapter_id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "audio_url": f"/api/v1/audiobook/download/{audiobook_project_id}/{chapter_audio.chapter_id}",
            "duration": chapter_audio.duration,
            "has_subtitle": bool(chapter_audio.subtitle_path and os.path.exists(chapter_audio.subtitle_path)),
            "subtitle_url": f"/api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_audio.chapter_id}/subtitle" if chapter_audio.subtitle_path else None,
        }
        
        if chapter_audio.script_json:
            try:
                chapter_info["segments"] = json.loads(chapter_audio.script_json)
            except:
                chapter_info["segments"] = []
        
        chapters_data.append(chapter_info)
    
    return {
        "project_id": audiobook_project_id,
        "project_title": project.title,
        "chapters": chapters_data,
        "total_duration": audiobook_project.total_duration,
    }


@router.post("/smart-chunk/preview")
async def preview_smart_chunking(
    segments: List[dict],
    max_tokens: int = 1800,
    min_tokens: int = 50,
    current_user: User = Depends(get_current_user),
):
    """预览智能分块结果（不实际执行）

    Args:
        segments: 原始剧本片段列表
        max_tokens: 单个分块最大 token 数
        min_tokens: 最小分块 token 数
    """
    chunker = SmartChunker(max_tokens=max_tokens, min_tokens=min_tokens)

    # 对片段列表进行分块
    chunked_segments = chunker.chunk_segments(segments)

    # 计算统计信息
    total_tokens = sum(chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments)
    token_list = [chunker.estimate_tokens(s.get("text", "")) for s in chunked_segments]

    stats = {
        "total_chunks": len(chunked_segments),
        "total_tokens": total_tokens,
        "avg_tokens_per_chunk": total_tokens / len(chunked_segments) if chunked_segments else 0,
        "max_tokens_in_chunk": max(token_list) if token_list else 0,
        "min_tokens_in_chunk": min(token_list) if token_list else 0,
    }

    return {
        "original_segments": len(segments),
        "chunked_segments": len(chunked_segments),
        "total_tokens": total_tokens,
        "chunks": chunked_segments,
        "stats": stats,
    }


@router.post("/smart-chunk/estimate")
async def estimate_text_tokens(
    text: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
):
    """估算文本的 token 数量"""
    chunker = SmartChunker()
    estimated = chunker.estimate_tokens(text)
    needs_chunking = chunker.needs_chunking(text)

    return {
        "text_length": len(text),
        "estimated_tokens": estimated,
        "needs_chunking": needs_chunking,
        "max_tokens": chunker.max_tokens,
    }


@router.get("/voice-types")
async def list_voice_types(
    current_user: User = Depends(get_current_user),
):
    """获取所有声音类型预设列表"""
    return get_all_voice_types()


@router.get("/voice-types/{voice_type}")
async def get_voice_type_detail(
    voice_type: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定声音类型详情"""
    preset = get_voice_type_preset(voice_type)
    if not preset:
        raise HTTPException(status_code=404, detail="声音类型不存在")
    return {
        "voice_type": preset.voice_type,
        "name": preset.name,
        "description": preset.description,
        "speed_modifier": preset.speed_modifier,
        "pitch_modifier": preset.pitch_modifier,
        "volume_modifier": preset.volume_modifier,
        "emotion_intensity": preset.emotion_intensity,
        "emotion_tendency": preset.emotion_tendency,
        "default_emotion": preset.default_emotion,
        "preferred_gender": preset.preferred_gender,
        "preferred_age_range": preset.preferred_age_range,
        "compatible_personalities": preset.compatible_personalities,
        "suitable_scenarios": preset.suitable_scenarios,
    }


@router.post("/voice-types/recommend")
async def recommend_voice_types(
    request: VoiceTypeRecommendationRequest,
    current_user: User = Depends(get_current_user),
):
    """根据角色属性推荐声音类型"""
    recommended = recommend_voice_type(
        personality=request.personality,
        gender=request.gender,
        age_range=request.age_range,
    )
    return {
        "recommended_types": recommended,
        "character_name": None,
    }


@router.get("/tasks/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """SSE 实时进度推送端点

    客户端连接后将持续接收任务进度事件
    """
    from fastapi.responses import StreamingResponse

    async def event_generator():
        async for event in sse_tracker.stream_events(task_id):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/previews/generate")
async def generate_preview(
    text: str = Body(..., embed=True),
    voice_id: str = Body(..., embed=True),
    tts_model: str = Body("qwen3-tts-flash", embed=True),
    emotion: Optional[str] = Body(None, embed=True),
    speed: Optional[float] = Body(None, embed=True),
    current_user: User = Depends(get_current_user),
):
    """快速生成试听片段（前 2 句）

    Args:
        text: 完整文本
        voice_id: 音色 ID
        tts_model: TTS 模型
        emotion: 情感参数
        speed: 语速参数
    """
    try:
        # 初始化 TTS 引擎
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")
        engine = AudiobookEngine(
            enable_cache=False,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
        )

        # 生成预览
        preview = default_preview_generator.generate_preview(
            text=text,
            voice_id=voice_id,
            tts_engine=engine,
            emotion=emotion,
            speed=speed,
        )

        return {
            "success": True,
            "preview": preview,
        }

    except Exception as e:
        logger.error(f"❌ 预览生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"预览生成失败: {str(e)}")


@router.post("/retries/config")
async def configure_retry(
    max_retries: int = Body(3, embed=True),
    initial_delay: float = Body(1.0, embed=True),
    backoff_factor: float = Body(2.0, embed=True),
    enable_degraded: bool = Body(True, embed=True),
    current_user: User = Depends(get_current_user),
):
    """配置重试策略

    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避因子
        enable_degraded: 是否启用降级
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        enable_degraded=enable_degraded,
    )
    return {
        "message": "重试配置已更新",
        "config": {
            "max_retries": config.max_retries,
            "initial_delay": config.initial_delay,
            "backoff_factor": config.backoff_factor,
            "enable_degraded": config.enable_degraded,
        },
    }


# ==================== Background Tasks ====================

async def generate_audiobook_scripts_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-flash",
    force_regenerate: bool = False,  # 🆕 新增参数：是否强制重新生成剧本
    tracker=None,
):
    """后台生成有声书【剧本+评审】任务（不执行TTS和混音）。

    流程：
    1. 初始化AudiobookEngine
    2. 逐章生成剧本与质量评审
    3. 将结果覆盖写入 ChapterAudio.script_json/script_review_json
    """
    from app.db.base import SessionLocal
    db = SessionLocal()

    try:
        logger.info(f"📝 开始后台生成有声书剧本: audiobook_project_id={audiobook_project_id}")

        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()

        if not audiobook_project:
            logger.error(f"❌ 有声书项目不存在: {audiobook_project_id}")
            return

        audiobook_project.status = "processing"
        db.commit()

        # 初始化引擎
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")

        progress_handler = _build_progress_handler(tracker, chapter_ids)

        engine = AudiobookEngine(
            enable_cache=audiobook_project.enable_cache,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
            progress_handler=progress_handler,
        )
        set_engine_instance(engine)

        # 应用项目级音频配置（角色音色 + 音效/BGM）
        try:
            project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
            if project and project.audio_config:
                try:
                    from app.services.audiobook.project_audio_config import parse_project_audio_config
                    config_data = parse_project_audio_config(project.audio_config or "")
                except Exception as parse_err:
                    logger.warning(f"⚠️ 解析项目级音频配置失败: {parse_err}")
                    config_data = {}
                
                # 1. 应用角色音色配置（先加载，确保剧本阶段也能使用正确的音色）
                effective_voice_mapping = dict(audiobook_project.voice_mapping or {})
                from app.services.audiobook.project_audio_config import get_characters_for_model, get_audio_fx
                for item in get_characters_for_model(config_data, tts_model):
                    name = item.get("name")
                    if not name:
                        continue
                    effective_voice_mapping[name] = {
                        "voice_id": item.get("voice_id"),
                        "volume": item.get("volume", 50),
                        "speed": item.get("speed"),
                        "pitch": item.get("pitch"),
                    }
                    logger.info(f"✅ [剧本阶段] 加载角色音配置: {name} -> {item.get('voice_id')}")
                
                if effective_voice_mapping:
                    try:
                        engine.voice_manager.apply_project_voice_mapping(effective_voice_mapping)
                        logger.info(f"🎛 [剧本阶段] 已加载角色音配置: {len(effective_voice_mapping)} 个角色")
                    except Exception as e:
                        logger.warning(f"⚠️ [剧本阶段] 应用角色音配置失败: {e}")
                
                # 2. 应用音效/BGM配置
                audio_fx = get_audio_fx(config_data)
                if audio_fx:
                    try:
                        engine.apply_audio_fx_config(audio_fx)
                        logger.info("🎚 [剧本阶段] 已加载项目级音效/BGM 配置")
                    except Exception as e:
                        logger.warning(f"⚠️ [剧本阶段] 应用项目级音效/BGM 配置失败: {e}")
        except Exception as e:
            logger.warning(f"⚠️ [剧本阶段] 加载项目级音频配置失败: {e}")

        # 获取项目角色列表
        from app.models.character import Character
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [c.name for c in characters if c.name]

        logger.info(f"📝 剧本阶段角色列表: {character_list}")

        # 逐章生成剧本与评审
        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(f"📖 [脚本阶段] 处理章节 {i}/{len(chapter_ids)}: chapter_id={chapter_id}")

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"⚠️ 章节不存在: {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    continue

                # 🆕 持久化优化：检查是否已有剧本
                chapter_audio = db.query(ChapterAudio).filter(
                    ChapterAudio.audiobook_project_id == audiobook_project_id,
                    ChapterAudio.chapter_id == chapter_id,
                ).first()

                # 如果章节已有剧本且未强制重生成，则根据剧本状态决定是否跳过
                if chapter_audio and chapter_audio.script_json and not force_regenerate:
                    if chapter_audio.script_status in ["reviewed", "approved"]:
                        logger.info(f"✅ [跳过] 章节 {chapter_id} 已有{chapter_audio.script_status}剧本，保持不变")
                        audiobook_project.completed_chapters += 1
                        db.commit()
                        continue
                    else:
                        logger.info(f"🔄 [覆盖] 章节 {chapter_id} 剧本状态为{chapter_audio.script_status}，将重新生成")
                elif force_regenerate and chapter_audio and chapter_audio.script_json:
                    logger.info(f"🔄 [强制重生成] 章节 {chapter_id} 将覆盖现有剧本")

                result = await engine.prepare_chapter_script(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    audiobook_project_id=audiobook_project_id,
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                )

                # upsert ChapterAudio
                if not chapter_audio:
                    chapter_audio = ChapterAudio(
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                    )
                    db.add(chapter_audio)

                chapter_audio.task_id = result.get("task_id")
                stats = result.get("stats", {})
                parse_stats = stats.get("parse_stats", {})

                chapter_audio.segment_count = parse_stats.get("total_segments", 0)
                chapter_audio.dialogue_count = parse_stats.get("dialogue_count", 0)
                chapter_audio.narration_count = parse_stats.get("narration_count", 0)
                chapter_audio.character_count = stats.get("characters", 0)

                gen_time_str = stats.get("generation_time", "0秒")
                try:
                    chapter_audio.generation_time = float(str(gen_time_str).replace("秒", ""))
                except Exception:
                    pass

                chapter_audio.script_json = json.dumps(
                    serialize_dataclass_to_dict(result.get("script_segments") or []),
                    ensure_ascii=False
                )
                chapter_audio.script_review_json = json.dumps(
                    serialize_dataclass_to_dict(result.get("quality_report") or {}),
                    ensure_ascii=False
                )
                # 🔧 修复：只在首次生成或强制重生成时设置为pending，避免覆盖用户手动设置的状态
                if not chapter_audio.script_status or force_regenerate:
                    chapter_audio.script_status = "pending"
                else:
                    # 保留原有状态（approved/reviewed）
                    logger.info(f"   ✅ 保留章节 {chapter_id} 剧本状态: {chapter_audio.script_status}")

                audiobook_project.completed_chapters += 1
                db.commit()

            except Exception as e:
                logger.error(f"❌ [脚本阶段] 章节 {chapter_id} 处理异常: {e}")
                audiobook_project.failed_chapters += 1
                db.commit()
                import traceback
                traceback.print_exc()

        audiobook_project.status = "completed"
        db.commit()

        logger.info("🎉 有声书剧本生成完成!")
        logger.info(
            f"   - 成功: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}"
        )

    finally:
        db.close()


async def generate_audiobook_audio_from_scripts_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-flash",
    tracker=None,
):
    """后台生成有声书音频任务（基于已生成/人工审核后的剧本）。

    用于两阶段流程的第2阶段：
    1. 读取 ChapterAudio.script_json 作为有声剧本
    2. 调用 AudiobookEngine.generate_chapter_audio_from_script 生成音频
    3. 更新 ChapterAudio.audio_path/duration/file_size/final_audio_review_json 等字段
    """
    from app.db.base import SessionLocal
    db = SessionLocal()

    try:
        logger.info(
            f"🎙️ 开始基于剧本的有声书音频生成: audiobook_project_id={audiobook_project_id}, chapters={chapter_ids}"
        )

        # 1. 获取有声书项目
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()

        if not audiobook_project:
            logger.error(f"❌ 有声书项目不存在: {audiobook_project_id}")
            return

        # 2. 重置并标记状态
        audiobook_project.status = "processing"
        audiobook_project.completed_chapters = 0
        audiobook_project.failed_chapters = 0
        audiobook_project.total_duration = 0.0
        audiobook_project.total_cost = 0.0
        db.commit()

        # 3. 初始化引擎
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")

        progress_handler = _build_progress_handler(tracker, chapter_ids)

        engine = AudiobookEngine(
            enable_cache=audiobook_project.enable_cache,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
            progress_handler=progress_handler,
        )
        set_engine_instance(engine)

        # 获取项目与章节信息（用于文件路径和题材）
        project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
        novel_genre = (project.genre or "科幻") if project else "科幻"
        novel_theme = (project.sub_genre or "未知主题") if project else "未知主题"

        # 计算本次生成应当使用的角色音配置：
        # 以已有的 audiobook_project.voice_mapping 为基础，叠加最新的 Project.audio_config.characters（如有），
        # 后者优先级更高，确保二阶段生成也能应用最新的前端配置（例如苏娜女声）。
        effective_voice_mapping = dict(audiobook_project.voice_mapping or {})
        from app.services.audiobook.project_audio_config import get_audio_fx, get_characters_for_model
        if project and project.audio_config:
            try:
                from app.services.audiobook.project_audio_config import parse_project_audio_config
                config_data = parse_project_audio_config(project.audio_config or "")
                characters = get_characters_for_model(config_data, tts_model)
                for item in characters:
                    name = item.get("name")
                    if not name:
                        logger.warning("⚠️ 跳过无名称的角色音配置项")
                        continue
                    effective_voice_mapping[name] = {
                        "voice_id": item.get("voice_id"),
                        "volume": item.get("volume", 50),
                        "speed": item.get("speed"),
                        "pitch": item.get("pitch"),
                    }
            except Exception as e:
                logger.warning(f"⚠️ 合并项目级角色音配置失败，将继续使用已有 voice_mapping: {e}")

        # 应用角色音配置到引擎（如有）
        if effective_voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(effective_voice_mapping)
                logger.info(
                    f"🎛 已加载角色音配置: {len(effective_voice_mapping)} 个角色"
                )
            except Exception as e:
                logger.warning(f"⚠️ 应用角色音配置失败: {e}")

        # 应用项目级音效/BGM 配置（如有）
        audio_fx = None
        if project and project.audio_config:
            try:
                from app.services.audiobook.project_audio_config import parse_project_audio_config
                config_data = parse_project_audio_config(project.audio_config or "")
                audio_fx = get_audio_fx(config_data)
            except Exception as parse_err:
                logger.warning(f"⚠️ 解析项目级音频配置失败: {parse_err}")

        if audio_fx:
            try:
                engine.apply_audio_fx_config(audio_fx)
                logger.info("🎚 已加载项目级音效/BGM 配置")
            except Exception as e:
                logger.warning(f"⚠️ 应用项目级音效/BGM 配置失败: {e}")

        total_duration = 0.0
        total_cost = 0.0

        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(
                    f"📖 [音频阶段] 处理章节 {i}/{len(chapter_ids)}: chapter_id={chapter_id}"
                )

                # 读取章节与脚本
                chapter_audio = db.query(ChapterAudio).filter(
                    ChapterAudio.audiobook_project_id == audiobook_project_id,
                    ChapterAudio.chapter_id == chapter_id,
                ).first()

                if not chapter_audio or not chapter_audio.script_json:
                    logger.warning(
                        f"⚠️ 章节 {chapter_id} 缺少剧本数据(script_json为空)，跳过该章节"
                    )
                    audiobook_project.failed_chapters += 1
                    db.commit()
                    continue

                script_status = (chapter_audio.script_status or "").lower()
                if script_status != "approved":
                    logger.warning(
                        f"⚠️ 章节 {chapter_id} 剧本尚未通过评审(script_status={chapter_audio.script_status})，跳过音频生成"
                    )
                    audiobook_project.failed_chapters += 1
                    db.commit()
                    continue

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"⚠️ 章节不存在: {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    db.commit()
                    continue

                try:
                    script_segments_data = json.loads(chapter_audio.script_json)
                except Exception as parse_err:
                    logger.error(f"❌ 解析章节剧本JSON失败 chapter_id={chapter_id}: {parse_err}")
                    audiobook_project.failed_chapters += 1
                    db.commit()
                    continue

                if not isinstance(script_segments_data, list):
                    logger.warning(
                        f"⚠️ 章节 {chapter_id} 剧本数据格式异常，期望为列表，实际为 {type(script_segments_data)}"
                    )
                    audiobook_project.failed_chapters += 1
                    db.commit()
                    continue

                # 生成输出路径
                output_path = f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3"

                # 调用引擎生成音频
                result = await engine.generate_chapter_audio_from_script(
                    script_segments_data=script_segments_data,
                    chapter_id=chapter_id,
                    output_path=output_path,
                    novel_genre=novel_genre,
                    novel_theme=novel_theme,
                    enable_quality_review=True,
                    audiobook_project_id=audiobook_project_id,
                )

                task_id = result.get("task_id")
                logger.info(f"🎯 [音频阶段] Chapter {chapter_id} TaskID: {task_id}")

                if result.get("success"):
                    stats = result.get("stats") or {}
                    parse_stats = stats.get("parse_stats") or {}
                    tts_stats = stats.get("tts_stats") or {}

                    # 更新章节音频记录（覆盖写入）
                    chapter_audio.task_id = task_id
                    chapter_audio.audio_path = output_path
                    chapter_audio.duration = result.get("duration") or 0.0
                    chapter_audio.file_size = result.get("file_size") or 0
                    chapter_audio.segment_count = parse_stats.get(
                        "total_segments", chapter_audio.segment_count
                    )
                    chapter_audio.dialogue_count = parse_stats.get(
                        "dialogue_count", chapter_audio.dialogue_count
                    )
                    chapter_audio.narration_count = parse_stats.get(
                        "narration_count", chapter_audio.narration_count
                    )

                    gen_time_str = stats.get("generation_time", "0秒")
                    try:
                        chapter_audio.generation_time = float(
                            str(gen_time_str).replace("秒", "")
                        )
                    except Exception:
                        pass

                    cost_str = tts_stats.get("estimated_cost", "¥0.00")
                    try:
                        chapter_audio.tts_cost = float(
                            str(cost_str).replace("¥", "").replace("$", "")
                        )
                    except Exception:
                        pass

                    final_audio_review = stats.get("final_audio_review")
                    if final_audio_review is not None:
                        try:
                            chapter_audio.final_audio_review_json = json.dumps(
                                final_audio_review, ensure_ascii=False
                            )
                        except Exception as dump_err:
                            logger.warning(
                                f"⚠️ 序列化最终音频评审结果失败 chapter_id={chapter_id}: {dump_err}"
                            )

                    audiobook_project.completed_chapters += 1
                    total_duration += result.get("duration") or 0.0
                    try:
                        total_cost += float(
                            str(cost_str).replace("¥", "").replace("$", "")
                        )
                    except Exception:
                        pass

                    logger.info(f"✅ 章节 {chapter_id} 音频生成成功")
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error(
                        f"❌ 章节 {chapter_id} 音频生成失败: {result.get('error')}"
                    )

                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()

            except Exception as e:
                logger.error(f"❌ 章节 {chapter_id} 音频阶段处理异常: {e}")
                audiobook_project.failed_chapters += 1
                db.commit()
                import traceback
                traceback.print_exc()

        audiobook_project.status = "completed"
        audiobook_project.total_duration = total_duration
        audiobook_project.total_cost = total_cost
        db.commit()

        try:
            record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project_id)
        except Exception as exc:
            logger.warning("记录有声书积分结算失败 audiobook_project_id=%s: %s", audiobook_project_id, exc)

        logger.info("🎉 基于剧本的有声书音频生成完成!")
        logger.info(
            f"   - 成功: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}"
        )
        logger.info(f"   - 总时长: {total_duration:.1f}秒")
        logger.info(f"   - 总成本: ¥{total_cost:.2f}")

    except Exception as e:
        logger.error(f"❌ 基于剧本的后台生成任务失败: {e}")
        import traceback
        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书音频生成失败，已释放冻结积分。",
                )
            except Exception as release_exc:
                logger.warning("释放有声书冻结积分失败 audiobook_project_id=%s: %s", audiobook_project_id, release_exc)

    finally:
        db.close()


async def generate_audiobook_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-flash",
    tracker=None,
):
    """
    后台生成有声书任务
    
    流程：
    1. 初始化AudiobookEngine
    2. 逐章生成音频
    3. 更新进度和状态
    4. 保存音频文件
    """
    from app.db.base import SessionLocal
    db = SessionLocal()
    
    try:
        logger.info(f"🎙️ 开始后台生成有声书: audiobook_project_id={audiobook_project_id}")
        
        # 更新状态为处理中
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()
        
        if not audiobook_project:
            logger.error(f"❌ 有声书项目不存在: {audiobook_project_id}")
            return
        
        audiobook_project.status = "processing"
        db.commit()
        
        # 初始化引擎（使用全局实例）
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client
        
        # 创建LLM客户端（必需）
        llm_client = get_llm_client(strategy="conservative")
        
        progress_handler = _build_progress_handler(tracker, chapter_ids)

        engine = AudiobookEngine(
            enable_cache=audiobook_project.enable_cache,
            max_concurrent=1,  # 降低并发避免限流
            llm_client=llm_client,  # 必须传入LLM客户端
            tts_model=tts_model,
            progress_handler=progress_handler,
        )
        # 设置为全局实例，供状态查询使用
        set_engine_instance(engine)

        # 应用项目级音效/BGM 配置（如有）
        try:
            project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
            if project and project.audio_config:
                try:
                    from app.services.audiobook.project_audio_config import parse_project_audio_config
                    config_data = parse_project_audio_config(project.audio_config or "")
                except Exception as parse_err:
                    logger.warning(f"⚠️ 解析项目级音频配置失败: {parse_err}")
                    config_data = {}
                from app.services.audiobook.project_audio_config import get_audio_fx
                audio_fx = get_audio_fx(config_data)
                if audio_fx:
                    try:
                        engine.apply_audio_fx_config(audio_fx)
                        logger.info("🎚 已加载项目级音效/BGM 配置")
                    except Exception as e:
                        logger.warning(f"⚠️ 应用项目级音效/BGM 配置失败: {e}")
        except Exception as e:
            logger.warning(f"⚠️ 加载项目级音频配置失败: {e}")
        
        # 应用项目级角色音配置（如有）
        if audiobook_project.voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(audiobook_project.voice_mapping)
                logger.info(f"🎛 已加载项目级角色音配置: {len(audiobook_project.voice_mapping)} 个角色")
            except Exception as e:
                logger.warning(f"⚠️ 应用项目级角色音配置失败: {e}")
        
        # 获取项目角色列表
        from app.models.character import Character
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [c.name for c in characters if c.name]
        
        logger.info(f"📝 角色列表: {character_list}")
        
        # 逐章生成
        total_duration = 0.0
        total_cost = 0.0
        
        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(f"📖 处理章节 {i}/{len(chapter_ids)}: chapter_id={chapter_id}")
                
                # 获取章节内容
                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"⚠️ 章节不存在: {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    continue
                
                # 生成音频
                result = await engine.generate_chapter_audio(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    output_path=f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3",
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                )
                
                # 记录task_id到数据库（可选）
                task_id = result.get('task_id')
                logger.info(f"🎯 TaskID: {task_id}")
                
                if result["success"]:
                    # 🆕 获取或创建章节音频记录（避免覆盖已有剧本）
                    chapter_audio = db.query(ChapterAudio).filter(
                        ChapterAudio.audiobook_project_id == audiobook_project_id,
                        ChapterAudio.chapter_id == chapter_id,
                    ).first()
                    
                    if not chapter_audio:
                        # 首次生成：创建新记录
                        chapter_audio = ChapterAudio(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                        )
                        db.add(chapter_audio)
                        logger.info(f"🆕 创建新的章节音频记录: chapter_id={chapter_id}")
                    else:
                        # 🔥 重要：保留已有的剧本数据
                        logger.info(f"♻️ 更新已有章节音频记录: chapter_id={chapter_id}")
                        if chapter_audio.script_json:
                            logger.info(f"   ✅ 保留已有剧本（status={chapter_audio.script_status}）")
                    
                    # 更新音频相关字段（不覆盖剧本）
                    chapter_audio.task_id = task_id
                    chapter_audio.audio_path = f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3"
                    chapter_audio.duration = result["duration"]
                    chapter_audio.file_size = result["file_size"]
                    
                    stats = result.get("stats", {})
                    parse_stats = stats.get("parse_stats", {})
                    tts_stats = stats.get("tts_stats", {})

                    script_payload = result.get("script_segments_payload") or []
                    if script_payload:
                        chapter_audio.script_json = json.dumps(
                            serialize_dataclass_to_dict(script_payload), ensure_ascii=False
                        )
                        chapter_audio.script_status = "pending"
                        quality_detail = result.get("quality_report_detail")
                        if quality_detail:
                            chapter_audio.script_review_json = json.dumps(
                                serialize_dataclass_to_dict(quality_detail), ensure_ascii=False
                            )
                    
                    chapter_audio.segment_count = parse_stats.get("total_segments", 0)
                    chapter_audio.dialogue_count = parse_stats.get("dialogue_count", 0)
                    chapter_audio.narration_count = parse_stats.get("narration_count", 0)
                    
                    gen_time_str = stats.get("generation_time", "0秒")
                    try:
                        chapter_audio.generation_time = float(str(gen_time_str).replace("秒", ""))
                    except Exception:
                        pass
                    
                    cost_str = tts_stats.get("estimated_cost", "¥0.00")
                    try:
                        chapter_audio.tts_cost = float(
                            str(cost_str).replace("¥", "").replace("$", "")
                        )
                    except Exception:
                        pass
                    
                    total_duration += result["duration"]
                    try:
                        total_cost += float(str(cost_str).replace("¥", "").replace("$", ""))
                    except Exception:
                        pass
                    
                    audiobook_project.completed_chapters += 1
                    logger.info(f"✅ 章节 {chapter_id} 生成成功")
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error(f"❌ 章节 {chapter_id} 生成失败: {result.get('error')}")
                
                # 更新进度
                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()
                
            except Exception as e:
                logger.error(f"❌ 章节 {chapter_id} 处理异常: {e}")
                audiobook_project.failed_chapters += 1
                db.commit()
                import traceback
                traceback.print_exc()
        
        # 更新最终状态
        audiobook_project.status = "completed"
        audiobook_project.total_duration = total_duration
        audiobook_project.total_cost = total_cost
        db.commit()

        try:
            record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project_id)
        except Exception as exc:
            logger.warning("记录有声书积分结算失败 audiobook_project_id=%s: %s", audiobook_project_id, exc)

        logger.info(f"🎉 有声书生成完成!")
        logger.info(f"   - 成功: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}")
        logger.info(f"   - 总时长: {total_duration:.1f}秒")
        logger.info(f"   - 总成本: ¥{total_cost:.2f}")
        
    except Exception as e:
        logger.error(f"❌ 后台生成任务失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 更新状态为失败
        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="有声书生成失败，已释放冻结积分。",
                )
            except Exception as release_exc:
                logger.warning("释放有声书冻结积分失败 audiobook_project_id=%s: %s", audiobook_project_id, release_exc)
    
    finally:
        db.close()

