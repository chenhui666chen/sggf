"""
鑰崇晹鏄熸渤 - 鏈夊０涔_敓鎴怉PI

鍔熻兘锛?
1. 鍒涘缓鏈夊０涔__鐩?
2. 鐢熸垚绔犺妭闊抽_
3. 鏌ヨ_鐢熸垚杩涘害
4. 涓嬭浇闊抽_鏂囦欢
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
        module_label="鏈夊０涔",
        default_message="鏈夊０涔_Н鍒嗛_妫_鏈__氳繃",
    )
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def serialize_dataclass_to_dict(obj):
    """閫掑綊灏哾ataclass瀵硅薄杞_崲涓哄瓧鍏革紝鐢ㄤ簬JSON搴忓垪鍖"""
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
    """绠_鍗曞寘瑁咃紝閬垮厤鍦ㄤ换鍔_嚱鏁颁腑閲嶅_鍒ょ_銆"""
    if tracker is None:
        return
    tracker.update_stage(stage, completed, total, message, detail)


def _build_progress_handler(tracker, chapter_ids: List[int]):
    """灏?AudiobookEngine 鐨勭珷鑺傜骇浠诲姟杩涘害鏄犲皠鍒?Celery 浠诲姟杩借釜銆"""
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
        message = f"绔犺妭 {chapter_positions.get(chapter_id, '')}/{total} 路 {stage_name}"
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
# 璇存槑锛氭湁澹颁功鐩稿叧鐨勮_姹?鍝嶅簲妯_瀷宸茶縼绉昏嚦 app.schemas.audiobook 妯_潡銆?


@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """鍚堟垚涓_灏忔_闊抽_鐢ㄤ簬鍓嶇_璇曞惉"""
    # 绠_鍗曢槻鎶わ細闄愬埗鏂囨湰闀垮害
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="鏂囨湰涓嶈兘涓虹_")
    if len(text) > 200:
        text = text[:200]

    # 閫夋嫨妯_瀷锛氶粯璁や娇鐢?qwen3-tts-flash锛屽彲鍒囨崲涓?cosyvoice-v3-plus
    model_name = (request.model or "qwen3-tts-flash").strip()
    if model_name not in {"qwen3-tts-flash", "cosyvoice-v3-plus"}:
        model_name = "qwen3-tts-flash"

    # 璇曞惉鍦烘櫙浼樺厛鈥滃揩閫熸仮澶嶁_濊_岄潪闀挎椂闂寸瓑寰咃細
    # - 棰濆_澶?1 娆￠噸璇曪紙搴斿_鍋跺彂鏂_繛锛?
    # - 鍩虹_閫_閬挎洿灏忥紝閬垮厤鍓嶇_绛夊緟杩囦箙
    preview_retry = RetryConfig(max_retries=4, base_delay=1.0, max_delay=8.0, exponential_base=2.0, jitter=True)
    # 灏嗗墠绔_殑 voice_id锛堝_ 'male_young_energetic'锛夋槧灏勪负鐪熷疄鐨?TTS 闊宠壊ID
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
        logger.warning("TTS璇曞惉澶辫触: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS鏈嶅姟鏆傛椂涓嶅彲鐢_紝璇风◢鍚庨噸璇", "retryable": True},
        ) from exc
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS鏈嶅姟鏆傛椂涓嶅彲鐢_紝璇风◢鍚庨噸璇", "retryable": True},
        )

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.get("/tts/models")
async def list_tts_models(
    current_user: User = Depends(get_current_user),
):
    """鍒楀嚭鎵_鏈夋敮鎸佺殑 TTS 妯_瀷鍙婂叾鍩烘湰淇_伅"""
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
        "qwen3-tts-flash": "楂樻_т环姣旓紝49闊宠壊锛岄_傚悎鎵归噺鐢熸垚",
        "qwen3-tts-plus": "楂樿川閲忥紝鏀_寔SSML",
        "cosyvoice-v3-plus": "椤剁骇闊宠川锛屾儏缁_帶鍒讹紝Instruct妯_紡",
        "minimax-speech-2.8-hd": "鏈_楂橀煶璐_紝璇_皵璇嶆爣绛撅紝100+闊宠壊",
        "minimax-speech-2.8-turbo": "浼樼_闊宠川锛岄珮鎬т环姣旓紝楂樺苟鍙",
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
        "qwen3-tts-flash": ["楂樻_т环姣", "49闊宠壊", "鎵归噺鍚堟垚"],
        "qwen3-tts-plus": ["楂樿川閲", "SSML鏀_寔"],
        "cosyvoice-v3-plus": ["椤剁骇闊宠川", "鎯呯华鎺у埗", "Instruct妯_紡"],
        "minimax-speech-2.8-hd": ["鏈_楂橀煶璐", "璇_皵璇嶆爣绛", "100+闊宠壊", "娣峰悎闊宠壊"],
        "minimax-speech-2.8-turbo": ["浼樼_闊宠川", "楂樻_т环姣", "楂樺苟鍙"],
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

    # cosyvoice-v3-plus锛氬悎骞垛_滃畼鏂瑰唴缃_煶鑹测_濅笌鈥滃_鍒婚煶鑹测_濓紙DashScope VoiceEnrollmentService锛?
    if model == "cosyvoice-v3-plus":
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend([c.to_voice_preset(get_clone_display_name(c.voice_id)) for c in clones])
        except CosyVoiceCloneError:
            # 鏈_厤缃?API Key 绛夋儏鍐典笅锛屼笉闃诲_椤甸潰浣跨敤鍐呯疆闊宠壊
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
    """鍒涘缓 cosyvoice-v3-plus 澶嶅埢闊宠壊銆?

    璇存槑锛欴ashScope 鍏嬮殕鎺ュ彛瑕佹眰 input.url 涓哄叕缃戝彲璁块棶鍦板潃鎴?oss:// 涓存椂 URL銆?
    """
    try:
        import hashlib
        import re
        import secrets

        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 涓嶈兘涓虹_")

        prefix = (request.prefix or "").strip()
        if not prefix:
            # 鐢熸垚绛栫暐锛?
            # - 鍏佽_ name 浠绘剰瀛楃_锛堝惈涓_枃锛夛紝浣?prefix 蹇呴_婊¤冻 SDK 瑕佹眰锛氬瓧姣?鏁板瓧/涓嬪垝绾匡紝1~32
            # - 娉ㄦ剰锛歝osyvoice clone 瑕佹眰 prefix 鏈_闀?10 涓_瓧绗?
            # - 灏介噺浠?name 鎻愬彇鍙__鐗囨_锛屽惁鍒欓__鍖栦负 v锛屽啀鎷兼帴 hash 鎻愬崌鍞_竴鎬?
            slug = re.sub(r"[^A-Za-z0-9_]+", "_", display_name).strip("_").lower()
            base = (slug[:4] if slug else "v").strip("_") or "v"
            uid = str(getattr(current_user, "id", "0"))
            # 闃茬_鎾烇細鍔犱竴涓_ǔ瀹?hash 鐗囨_锛堥伩鍏嶅悓鍚嶅悓鐢ㄦ埛棰戠箒鐢熸垚瀹屽叏涓_鑷达級
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
    """涓婁紶鏈_湴闊抽_锛岀敓鎴愪复鏃?oss:// URL銆"""
    try:
        content = await file.read()
        if not content:
            raise CosyVoiceCloneError("file 涓嶈兘涓虹_")
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
    """鍒楀嚭 cosyvoice-v3-plus 鐨勫_鍒婚煶鑹诧紙褰撳墠 API Key 缁村害锛夈_"""
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
    """鍒犻櫎 cosyvoice-v3-plus 澶嶅埢闊宠壊銆"""
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
    """鍒涘缓鏈夊０涔__鐩_苟鍚_姩鐢熸垚浠诲姟銆?

    宸ヤ綔娴侊細
    1. 閫氳繃搴旂敤鏈嶅姟鏍￠獙椤圭洰涓庣珷鑺傦紝骞跺垱寤烘湁澹颁功椤圭洰璁板綍
    2. 鏍规嵁 generation_mode 鍚_姩瀵瑰簲鐨勫悗鍙扮敓鎴愪换鍔?    """
    service = AudiobookAppService(db=db, current_user=current_user)
# 4. 鍚庡彴鍚_姩鐢熸垚浠诲姟锛堥_氳繃 Celery 闃熷垪锛
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
            logger.warning("璁板綍鏈夊０涔_Н鍒嗗喕缁撳け璐,audiobook_project_id=%s: %s", audiobook_project.id, exc)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project.id,
        "job_id": async_result.id,
        "task_type": job_type,
        "message": "鏈夊０涔_敓鎴愪换鍔_凡杩涘叆闃熷垪",
        "total_chapters": len(request.chapter_ids),
    }


@router.get("/projects/{audiobook_project_id:int}", response_model=dict)
async def get_audiobook_project(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """鑾峰彇鏈夊０涔__鐩__鎯"""
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪",
        )

    # 楠岃瘉鏉冮檺
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂",
        )

    # 鑾峰彇绔犺妭闊抽_鍒楄_
    chapter_audios = ChapterAudioRepository.list_by_audiobook_project(db, audiobook_project_id)

    # 鍙栫珷鑺傜紪鍙凤紝鐢ㄤ簬鍓嶇_鈥滄寜绔犺妭缂栧彿璺ㄨ_褰曞悎骞堕煶棰戔_?
    chapter_ids = [ca.chapter_id for ca in chapter_audios]
    chapter_number_by_id = {}
    if chapter_ids:
        from app.models.project import Chapter  # 閬垮厤椤跺眰寰_幆渚濊禆

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
	                "task_id": ca.task_id,  # 鏂板_锛氳繑鍥瀟ask_id
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
    include_chapter_audios: bool = Query(False, description="鏄_惁鍖呭惈绔犺妭闊抽_鍒楄_"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """鑾峰彇椤圭洰鐨勬墍鏈夋湁澹颁功椤圭洰"""
    # 楠岃瘉鏉冮檺
    project = ProjectRepository.get_user_project(db, current_user.id, project_id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="椤圭洰涓嶅瓨鍦ㄦ垨鏃犳潈闄",
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
    """鑾峰彇鐢ㄦ埛鐨勬墍鏈夋湁澹颁功椤圭洰锛堢敤浜庢湁澹板皬璇翠华琛ㄧ洏锛"""
    audiobook_projects = AudiobookProjectRepository.list_by_user(db, current_user.id)
    
    # 鑾峰彇椤圭洰璇_粏淇_伅
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
    """瑙_彂鍩轰簬宸茬敓鎴愬墽鏈_殑绔犺妭闊抽_鐢熸垚锛堜袱闃舵_娴佺▼绗?闃舵_锛夈_?

    - 濡傛灉鏈_樉寮忔寚瀹?chapter_ids锛屽垯榛樿_閫夋嫨璇ユ湁澹颁功椤圭洰涓?script_status == "approved" 涓斿凡瀛樺湪 script_json 鐨勭珷鑺傘_?
    - 濡傛灉鏄惧紡鎸囧畾 chapter_ids锛屽垯璇锋眰闃舵_浠呰_姹傚_搴旂珷鑺傚瓨鍦?script_json锛涙墽琛岄樁娈典粛浼氳繃婊ゆ湭閫氳繃璇勫_鐨勭珷鑺傘_?    """
    # 1. 楠岃瘉鏈夊０涔__鐩_槸鍚_瓨鍦?
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪",
        )

    # 2. 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂",
        )

    # 3. 閫夊彇闇_瑕佺敓鎴愰煶棰戠殑绔犺妭
    if request.chapter_ids:
        # 鏄惧紡鎸囧畾绔犺妭锛氬彧杩囨护鏈夊墽鏈_殑绔犺妭
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.chapter_id.in_(request.chapter_ids),
            ChapterAudio.script_json.isnot(None),
        ).all()
    else:
        # 鏈_寚瀹氱珷鑺傦細榛樿_閫夋嫨 script_status == "approved" 鐨勭珷鑺?
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id,
            ChapterAudio.script_json.isnot(None),
            ChapterAudio.script_status == "approved",
        ).all()

    if not chapter_audios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="娌_湁鍙_敓鎴愰煶棰戠殑绔犺妭锛岃_鍏堝畬鎴愬墽鏈_敓鎴愪笌瀹_牳",
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

    # 4. 鍚_姩鍚庡彴浠诲姟
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
        logger.warning("璁板綍浜岄樁娈垫湁澹颁功绉_垎鍐荤粨澶辫触 audiobook_project_id=%s: %s", audiobook_project_id, exc)

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "chapter_ids": target_chapter_ids,
        "job_id": async_result.id,
        "message": "宸插惎鍔ㄥ熀浜庡墽鏈_殑闊抽_鐢熸垚浠诲姟",
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
    鍒犻櫎鏈夊０涔__鐩_紙鏀_寔杞_垹闄ゅ拰纭_垹闄わ級
    
    宸ヤ綔娴侊細
    1. 楠岃瘉鏉冮檺
    2. 鎵ц_杞_垹闄ゅ苟璁板綍瀹¤_鏃ュ織
    3. 鍙__夛細鍒犻櫎鐗_悊鏂囦欢锛坉elete_files=true鏃讹級
    """
    logger.info(f"馃棏锔鐢ㄦ埛 {current_user.id} 璇锋眰鍒犻櫎鏈夊０涔__鐩 audiobook_project_id={audiobook_project_id}, delete_files={delete_files}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None
        if payload.get("delete_files") is not None:
            delete_files = bool(payload.get("delete_files"))

    # 1. 楠岃瘉鏈夊０涔__鐩_潈闄?
    audiobook_project = db.query(AudiobookProject).filter(AudiobookProject.id == audiobook_project_id).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )
    
    # 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愬垹闄ゆ_椤圭洰"
        )
    
    # 2. 鎵ц_杞_垹闄ゅ苟璁板綍瀹¤_鏃ュ織
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
            detail="鏈夊０涔__鐩_笉瀛樺湪鎴栧凡琚_垹闄"
        )
    
    # 3. 鍙__夛細鍒犻櫎鐗_悊鏂囦欢
    deleted_files = 0
    failed_files = []
    
    if delete_files:
        # 鑾峰彇鎵_鏈夌珷鑺傞煶棰戝苟鍒犻櫎鏂囦欢
        chapter_audios = db.query(ChapterAudio).filter(
            ChapterAudio.audiobook_project_id == audiobook_project_id
        ).all()
        
        for chapter_audio in chapter_audios:
            if chapter_audio.audio_path and os.path.exists(chapter_audio.audio_path):
                try:
                    os.remove(chapter_audio.audio_path)
                    deleted_files += 1
                    logger.info(f"鉁鍒犻櫎鏂囦欢: {chapter_audio.audio_path}")
                except Exception as e:
                    logger.error(f"鉂鍒犻櫎鏂囦欢澶辫触: {chapter_audio.audio_path}, 閿欒_: {e}")
                    failed_files.append(chapter_audio.audio_path)
    
    logger.info(f"鉁鏈夊０涔__鐩_蒋鍒犻櫎鎴愬姛: audiobook_project_id={audiobook_project_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "鏈夊０涔__鐩_凡鍒犻櫎",
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
    鍒犻櫎绔犺妭闊抽_锛堟敮鎸佽蒋鍒犻櫎鍜岀‖鍒犻櫎锛?
    
    宸ヤ綔娴侊細
    1. 楠岃瘉鏉冮檺
    2. 鎵ц_杞_垹闄ゅ苟璁板綍瀹¤_鏃ュ織
    3. 鍙__夛細鍒犻櫎鐗_悊鏂囦欢锛坉elete_file=true鏃讹級
    """
    logger.info(f"馃棏锔鐢ㄦ埛 {current_user.id} 璇锋眰鍒犻櫎绔犺妭闊抽_: chapter_audio_id={chapter_audio_id}, delete_file={delete_file}")
    
    if isinstance(payload, dict):
        if payload.get("delete_reason") is not None:
            raw_reason = str(payload.get("delete_reason") or "").strip()
            delete_reason = raw_reason or None

        raw_delete_file = payload.get("delete_file")
        if raw_delete_file is None:
            raw_delete_file = payload.get("delete_files")
        if raw_delete_file is not None:
            delete_file = bool(raw_delete_file)

    # 1. 鑾峰彇绔犺妭闊抽_
    chapter_audio = ChapterAudioRepository.get_by_id(db, chapter_audio_id)
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭闊抽_涓嶅瓨鍦"
        )
    
    # 2. 楠岃瘉鏉冮檺
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愬垹闄ゆ_绔犺妭闊抽_"
        )
    
    # 3. 鎵ц_杞_垹闄ゅ苟璁板綍瀹¤_鏃ュ織
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
            detail="绔犺妭闊抽_涓嶅瓨鍦ㄦ垨宸茶_鍒犻櫎"
        )
    
    # 4. 鍙__夛細鍒犻櫎鐗_悊鏂囦欢
    deleted_file = False
    failed_file = None
    
    if delete_file and chapter_audio.audio_path:
        if os.path.exists(chapter_audio.audio_path):
            try:
                os.remove(chapter_audio.audio_path)
                deleted_file = True
                logger.info(f"鉁鍒犻櫎鏂囦欢: {chapter_audio.audio_path}")
            except Exception as e:
                logger.error(f"鉂鍒犻櫎鏂囦欢澶辫触: {chapter_audio.audio_path}, 閿欒_: {e}")
                failed_file = chapter_audio.audio_path
    
    logger.info(f"鉁绔犺妭闊抽_杞_垹闄ゆ垚鍔 chapter_audio_id={chapter_audio_id}, audit_id={audit_log.id}")
    
    return {
        "success": True,
        "message": "绔犺妭闊抽_宸插垹闄",
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
    鎭㈠_宸插垹闄ょ殑鏈夊０涔__鐩?
    
    宸ヤ綔娴侊細
    1. 楠岃瘉鏉冮檺
    2. 鎭㈠_椤圭洰鍙婂叧鑱旂殑绔犺妭闊抽_
    3. 鏇存柊瀹¤_鏃ュ織
    """
    logger.info(f"鈾伙笍 鐢ㄦ埛 {current_user.id} 璇锋眰鎭㈠_鏈夊０涔__鐩 audiobook_project_id={audiobook_project_id}")
    
    # 1. 楠岃瘉鏈夊０涔__鐩_槸鍚_瓨鍦?
    audiobook_project = AudiobookProjectRepository.get_by_id(db, audiobook_project_id)
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )

    # 2. 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = ProjectRepository.get_user_project(db, current_user.id, audiobook_project.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愭仮澶嶆_椤圭洰"
        )

    # 3. 鎭㈠_椤圭洰
    restored_project = AudiobookProjectRepository.restore(
        db=db,
        audiobook_project_id=audiobook_project_id,
        user_id=current_user.id
    )
    
    if not restored_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="椤圭洰涓嶅瓨鍦ㄦ垨鏈__鍒犻櫎"
        )
    
    logger.info(f"鉁鏈夊０涔__鐩_仮澶嶆垚鍔 audiobook_project_id={audiobook_project_id}")
    
    return {
        "success": True,
        "message": "鏈夊０涔__鐩_凡鎭㈠_",
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
    鎭㈠_宸插垹闄ょ殑绔犺妭闊抽_
    
    宸ヤ綔娴侊細
    1. 楠岃瘉鏉冮檺
    2. 鎭㈠_绔犺妭闊抽_
    3. 鏇存柊瀹¤_鏃ュ織
    """
    logger.info(f"鈾伙笍 鐢ㄦ埛 {current_user.id} 璇锋眰鎭㈠_绔犺妭闊抽_: chapter_audio_id={chapter_audio_id}")
    
    # 1. 鑾峰彇绔犺妭闊抽_
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.id == chapter_audio_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭闊抽_涓嶅瓨鍦"
        )
    
    # 2. 楠岃瘉鏉冮檺
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == chapter_audio.audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愭仮澶嶆_绔犺妭闊抽_"
        )
    
    # 3. 鎭㈠_绔犺妭闊抽_
    restored_audio = ChapterAudioRepository.restore(
        db=db,
        chapter_audio_id=chapter_audio_id,
        user_id=current_user.id
    )
    
    if not restored_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭闊抽_涓嶅瓨鍦ㄦ垨鏈__鍒犻櫎"
        )
    
    logger.info(f"鉁绔犺妭闊抽_鎭㈠_鎴愬姛: chapter_audio_id={chapter_audio_id}")
    
    return {
        "success": True,
        "message": "绔犺妭闊抽_宸叉仮澶",
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
    鑾峰彇鐢ㄦ埛宸插垹闄ょ殑鏈夊０涔__鐩_垪琛_紙鍥炴敹绔欙級
    
    杩斿洖锛氬凡鍒犻櫎鐨勯_鐩_垪琛_紝鍖呭惈瀹¤_淇_伅
    """
    logger.info(f"馃搵 鐢ㄦ埛 {current_user.id} 鏌ヨ_宸插垹闄ら_鐩_垪琛")
    
    # 鑾峰彇宸插垹闄ょ殑椤圭洰
    deleted_projects = AudiobookProjectRepository.list_deleted(
        db=db,
        user_id=current_user.id,
        limit=limit
    )
    
    # 鑾峰彇瀹¤_鏃ュ織
    project_ids = [p.id for p in deleted_projects]
    audit_logs = db.query(AudiobookDeleteAudit).filter(
        AudiobookDeleteAudit.target_id.in_(project_ids),
        AudiobookDeleteAudit.delete_type == 'project'
    ).all()
    
    # 鏋勫缓瀹¤_鏃ュ織鏄犲皠
    audit_map = {log.target_id: log for log in audit_logs}
    
    # 鏋勫缓鍝嶅簲
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
    
    logger.info(f"鉁鏌ヨ_鍒{len(result)} 涓_凡鍒犻櫎椤圭洰")
    
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
    """鏌ヨ_鎸囧畾浠诲姟鐨勬寔涔呭寲闃熷垪鐘舵_併_"""
    task = AudiobookTaskRepository.get_task_for_user(db, task_id, current_user.id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"浠诲姟涓嶅瓨鍦 {task_id}",
        )
    return build_task_status_response(task)


@router.get("/tasks", response_model=List[AudiobookTaskStatus])
async def list_all_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鍒楀嚭褰撳墠鐢ㄦ埛鏈_杩戠殑鏈夊０涔_悗鍙颁换鍔__"""
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
    涓嬭浇绔犺妭闊抽_鏂囦欢
    
    杩斿洖锛歁P3闊抽_鏂囦欢娴?
    """
    logger.info(f"馃帶 鐢ㄦ埛 {current_user.id} 涓嬭浇闊抽_: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 楠岃瘉鏈夊０涔__鐩_潈闄?
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )
    
    # 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂"
        )
    
    # 2. 鑾峰彇绔犺妭闊抽_璁板綍
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭闊抽_涓嶅瓨鍦"
        )
    
    # 3. 妫_鏌ユ枃浠舵槸鍚_瓨鍦?
    if not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="闊抽_鏂囦欢璺_緞涓嶅瓨鍦"
        )
    
    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"闊抽_鏂囦欢涓嶅瓨鍦 {file_path}"
        )
    
    # 4. 鑾峰彇绔犺妭鏍囬_浣滀负鏂囦欢鍚?
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    filename = f"绗{chapter.chapter_number}绔{chapter.title}.mp3" if chapter else f"chapter_{chapter_id}.mp3"
    
    # URL缂栫爜鏂囦欢鍚嶏紙鏀_寔涓_枃锛?
    encoded_filename = quote(filename)
    
    logger.info(f"鉁杩斿洖闊抽_鏂囦欢: {file_path}")
    
    # 5. 杩斿洖鏂囦欢
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=filename,  # 淇濈暀鍘熷_鏂囦欢鍚嶏紙渚涙祻瑙堝櫒鏄剧ず锛?
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
    娴佸紡鎾_斁绔犺妭闊抽_锛堢敤浜庡湪绾挎挱鏀撅級
    
    杩斿洖锛氶煶棰戞枃浠舵祦锛堟敮鎸丷ange璇锋眰锛?
    """
    logger.info(f"馃幍 鐢ㄦ埛 {current_user.id} 鍦ㄧ嚎鎾_斁: audiobook_project_id={audiobook_project_id}, chapter_id={chapter_id}")
    
    # 1. 楠岃瘉鏉冮檺锛堝悓涓嬭浇鎺ュ彛锛?
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪"
        )
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂"
        )
    
    # 2. 鑾峰彇闊抽_鏂囦欢璺_緞
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id
    ).first()
    
    if not chapter_audio or not chapter_audio.audio_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭闊抽_涓嶅瓨鍦"
        )
    
    file_path = chapter_audio.audio_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"闊抽_鏂囦欢涓嶅瓨鍦 {file_path}"
        )
    
    logger.info(f"鉁娴佸紡鎾_斁鏂囦欢: {file_path}")
    
    # 3. 杩斿洖鏂囦欢娴侊紙inline妯_紡锛屾祻瑙堝櫒鐩存帴鎾_斁锛?
    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range"
        }
    )


# ==================== 鍓ф湰缂栬緫涓庨煶棰戠敓鎴愶紙涓ら樁娈电浉鍏筹級 ====================

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def get_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鑾峰彇鎸囧畾绔犺妭鐨勬湁澹板墽鏈_笌璇勫_缁撴灉銆?

    浠呰繑鍥炴渶杩戜竴娆＄敓鎴?淇濆瓨鐨勫墽鏈_揩鐓э紝涓嶅仛鐗堟湰鍘嗗彶銆?
    """
    # 楠岃瘉鏈夊０涔__鐩?
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪",
        )

    # 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂",
        )

    # 鑾峰彇绔犺妭鍓ф湰璁板綍
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
                "鈾伙笍 绔犺妭 %s 澶嶇敤鍘嗗彶鍓ф湰渚,audiobook_project_id=%s 浣跨敤",
                chapter_id,
                audiobook_project_id,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="绔犺妭鍓ф湰涓嶅瓨鍦_紝璇峰厛鐢熸垚鍓ф湰",
            )

    try:
        script_segments = json.loads(chapter_audio.script_json)
    except Exception as e:
        logger.error(f"鉂瑙ｆ瀽绔犺妭鍓ф湰JSON澶辫触 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="绔犺妭鍓ф湰鏁版嵁鎹熷潖锛岃_灏濊瘯閲嶆柊鐢熸垚",
        )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except Exception as e:
            logger.warning(f"鈿狅笍 瑙ｆ瀽绔犺妭鍓ф湰璇勫_JSON澶辫触 chapter_id={chapter_id}: {e}")

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
    """鏇存柊鎸囧畾绔犺妭鐨勬湁澹板墽鏈__?

    - script_segments锛氳_鐩栧啓鍏ユ渶杩戜竴娆_墽鏈_揩鐓?
    - script_status锛氬彲閫夛紝pending/reviewed/approved
    """
    # 楠岃瘉鏈夊０涔__鐩?
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()

    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪",
        )

    # 楠岃瘉鍘熷_椤圭洰鏉冮檺
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂",
        )

    # 楠岃瘉绔犺妭鏄_惁灞炰簬璇ラ_鐩?
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.project_id == project.id,
    ).first()

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭涓嶅瓨鍦ㄦ垨涓嶅睘浜庤_椤圭洰",
        )

    # 鑾峰彇鎴栧垱寤虹珷鑺傞煶棰戣_褰?
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

    # 瑕嗙洊鍐欏叆鍓ф湰
    try:
        chapter_audio.script_json = json.dumps(
            request.script_segments or [], ensure_ascii=False
        )
    except Exception as e:
        logger.error(f"鉂搴忓垪鍖栫珷鑺傚墽鏈_け璐,chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="鍓ф湰鏁版嵁鏍煎紡涓嶅悎娉",
        )

    # 鏇存柊鑴氭湰鐘舵_侊紙濡傛湁锛?
    if request.script_status:
        if request.script_status not in {"pending", "reviewed", "approved"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="鏃犳晥鐨剆cript_status锛屽繀椤讳负 pending/reviewed/approved",
            )
        chapter_audio.script_status = request.script_status

    # 鍓ф湰鍙樺寲鍚庯紝娓呯_鏈_缁堥煶棰戣瘎瀹★紝闃叉_娣锋穯
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
    """鍗曟_鍓ф湰鐗囨_闊抽_璇曞惉锛堜笉钀藉簱锛"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="鏈夊０涔__鐩_笉瀛樺湪",
        )

    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="鏃犳潈闄愯_闂",
        )

    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.project_id == project.id,
    ).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="绔犺妭涓嶅瓨鍦ㄦ垨涓嶅睘浜庤_椤圭洰",
        )

    segment = request.segment or {}
    if not isinstance(segment, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="segment 鏁版嵁鏍煎紡涓嶆_纭",
        )

    text = str(segment.get("text") or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="鍙拌瘝涓嶈兘涓虹_",
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
            logger.warning("鍗曟_闊宠壊鏄犲皠澶辫触: %s", exc)

    speaker = str(segment.get("speaker") or "鏃佺櫧").strip() or "鏃佺櫧"
    if speaker in {"鏃佺櫧", "narrator", "Narrator"}:
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
                logger.warning(" 璇曞惉闊虫晥鏂囦欢涓嶅瓨鍦 %s", effect_path or file_ref)
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
                logger.warning(" 鍙犲姞璇曞惉闊虫晥澶辫触 %s: %s", effect_path, exc)
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
        if any(key in raw for key in ["sad", "鎮", "浼"]):
            return "sad"
        if any(key in raw for key in ["happy", "joy", "娆", "涔"]):
            return "joyful"
        if any(key in raw for key in ["tense", "angry", "fear", "绱у紶", "鎭愭儳", "鎰ゆ_"]):
            return "tense"
        if any(key in raw for key in ["romantic", "love", "娴_极"]):
            return "romantic"
        if any(key in raw for key in ["mysterious", "绁炵_"]):
            return "mysterious"
        if any(key in raw for key in ["epic", "鍙茶瘲", "瀹忓ぇ"]):
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
            logger.warning(" 璇诲彇闊充箰绱㈠紩澶辫触: %s", exc)
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
            logger.warning(" 璇曞惉閰嶄箰鏂囦欢涓嶅瓨鍦 %s", music_path)
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
            logger.warning(" 鍙犲姞璇曞惉閰嶄箰澶辫触 %s: %s", music_path, exc)
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
            logger.warning("鍗曟_TTS璇曞惉澶辫触: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS鏈嶅姟鏆傛椂涓嶅彲鐢_紝璇风◢鍚庨噸璇", "retryable": True},
            ) from exc

        if not voice_audio:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"message": "TTS鏈嶅姟鏆傛椂涓嶅彲鐢_紝璇风◢鍚庨噸璇", "retryable": True},
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
                detail="璇ョ墖娈垫湭閰嶇疆闊虫晥锛屾棤娉曡瘯鍚_煶鏁",
            )

    music_cue = None
    if preview_type in {"bgm", "mix"}:
        music_cue = normalize_music_cue(segment)
        if preview_type == "bgm" and not music_cue:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="璇ョ墖娈垫湭閰嶇疆閰嶄箰锛屾棤娉曡瘯鍚_厤涔",
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
                detail="闊抽_娣烽煶缁勪欢涓嶅彲鐢_紝鏃犳硶鐢熸垚璇曞惉闊抽_",
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
            detail="璇曞惉闊抽_鐢熸垚澶辫触锛岃_绋嶅悗閲嶈瘯",
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
    """鍗曚釜鐗囨_閲嶆柊鐢熸垚
    
    鍔熻兘锛?    1. 閲嶆柊璋冪敤 TTS API 鐢熸垚璇ョ墖娈电殑鏂伴煶棰?    2. 鏇挎崲鍘熸湁鐨勭墖娈甸煶棰?    3. 鍙__夛細浣跨敤涓嶅悓鐨?TTS 妯_瀷/闊宠壊/鎯呮劅
    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
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
        raise HTTPException(status_code=404, detail="绔犺妭闊抽_璁板綍涓嶅瓨鍦")
    
    # 鍔犺浇鍓ф湰鐗囨_
    try:
        segments = json.loads(chapter_audio.script_json)
    except:
        raise HTTPException(status_code=500, detail="绔犺妭鍓ф湰鏁版嵁鎹熷潖")
    
    if segment_index < 0 or segment_index >= len(segments):
        raise HTTPException(status_code=404, detail="鐗囨_绱㈠紩鏃犳晥")
    
    segment = segments[segment_index]
    
    # 鏋勫缓 TTS 璇锋眰鍙傛暟
    tts_model = request.tts_model or (chapter_audio.tts_model or "qwen3-tts-flash")
    voice_id = request.voice_id or segment.get("voice_id", "longxiaochun")
    emotion = request.emotion or segment.get("emotion", "neutral")
    
    # 鍒涘缓 TTS 寮曟搸
    engine = create_tts_engine(
        model=tts_model,
        retry_config=RetryConfig(max_retries=3, base_delay=1.0),
    )
    
    voice_params = {
        "speaker": voice_id,
        "emotion": emotion,
    }
    
    # 璋冪敤 TTS
    text = segment.get("text", "")
    audio_bytes = await engine.synthesize(text, voice_params=voice_params)
    
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS 鐢熸垚澶辫触")
    
    # 淇濆瓨鏂伴煶棰戯紙瑕嗙洊鍘熼煶棰戯級
    try:
        output_dir = chapter_audio.get_audio_dir()
        os.makedirs(output_dir, exist_ok=True)
        
        audio_filename = f"segment_{segment_index}_regenerated.mp3"
        audio_path = os.path.join(output_dir, audio_filename)
        
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        
        # 鏇存柊 segment 涓_殑闊抽_璺_緞
        segment["audio_path"] = audio_path
        segment["regenerated"] = True
        segment["regenerated_at"] = datetime.utcnow().isoformat()
        if request.reason:
            segment["regenerate_reason"] = request.reason
        
        # 淇濆瓨鏇存柊鍚庣殑鍓ф湰
        chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
        db.commit()
        
        logger.info(
            f"鉁鐗囨_閲嶆柊鐢熸垚鎴愬姛: chapter_id={chapter_id}, "
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
        logger.error(f"鉂淇濆瓨閲嶆柊鐢熸垚鐨勯煶棰戝け璐 {e}")
        raise HTTPException(status_code=500, detail=f"淇濆瓨闊抽_澶辫触: {str(e)}")


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/review")
async def review_segment(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鐗囨_瀹_煡/璇勫垎
    
    鍔熻兘锛?    1. 璁板綍鐗囨_鐨勮川閲忚瘎鍒嗗拰澶囨敞
    2. 鏍囪_闇_瑕侀噸鏂扮敓鎴愮殑鐗囨_
    3. 鏇存柊绔犺妭鏁翠綋瀹_煡鐘舵_?    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="绔犺妭闊抽_璁板綍涓嶅瓨鍦")
    
    # 鍔犺浇瀹_煡璁板綍
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            review_data = json.loads(chapter_audio.segment_reviews_json)
        except:
            pass
    
    # 璁板綍瀹_煡缁撴灉
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
    """鑾峰彇绔犺妭鏁翠綋瀹_煡鐘舵_?    
    杩斿洖锛?    - 鎬荤墖娈垫暟
    - 宸插_鏌ョ墖娈垫暟
    - 骞冲潎璐ㄩ噺璇勫垎
    - 鏍囪_闇_瑕侀噸鏂扮敓鎴愮殑鐗囨_绱㈠紩
    """
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="绔犺妭闊抽_璁板綍涓嶅瓨鍦")
    
# 鍔犺浇鍓ф湰鍜屽_鏌ヨ_褰
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
    
    # 璁＄畻骞冲潎璐ㄩ噺璇勫垎
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
    """鑾峰彇鎵_鏈夊彊浜嬮_鏍奸_璁惧垪琛"""
    return get_all_narration_styles()


@router.get("/narration-styles/{style_id}")
async def get_narration_style(
    style_id: str,
    current_user: User = Depends(get_current_user),
):
    """鑾峰彇鎸囧畾鍙欎簨椋庢牸棰勮_璇_儏"""
    preset = get_narration_style_preset(style_id)
    if not preset:
        raise HTTPException(status_code=404, detail="鍙欎簨椋庢牸棰勮_涓嶅瓨鍦")
    return preset


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/subtitle")
async def get_chapter_subtitle(
    audiobook_project_id: int,
    chapter_id: int,
    format: str = Query("srt", regex="^(srt|vtt|ass)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鑾峰彇绔犺妭瀛楀箷鏂囦欢"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="绔犺妭闊抽_璁板綍涓嶅瓨鍦")
    
    if not chapter_audio.subtitle_path:
        raise HTTPException(status_code=404, detail="瀛楀箷鏂囦欢涓嶅瓨鍦")
    
    subtitle_file = chapter_audio.subtitle_path
    if format == "vtt":
        subtitle_file = subtitle_file.replace(".srt", ".vtt")
    elif format == "ass":
        subtitle_file = subtitle_file.replace(".srt", ".ass")
    
    if not os.path.exists(subtitle_file):
        raise HTTPException(status_code=404, detail="瀛楀箷鏂囦欢涓嶅瓨鍦")
    
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
    """鑾峰彇鐢熸垚鏂_偣淇_伅锛堢敤浜庢柇鐐圭画浼狅級"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
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
    """浠庢柇鐐圭户缁_敓鎴愮珷鑺傞煶棰"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
    chapter_audio = db.query(ChapterAudio).filter(
        ChapterAudio.audiobook_project_id == audiobook_project_id,
        ChapterAudio.chapter_id == chapter_id,
    ).first()
    if not chapter_audio:
        raise HTTPException(status_code=404, detail="绔犺妭闊抽_璁板綍涓嶅瓨鍦")
    
    checkpoint_payload = _build_generation_checkpoint_payload(
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        run_type=None,
        db=db,
        audiobook_project_id=audiobook_project_id,
    )
    if not checkpoint_payload["can_resume"]:
        raise HTTPException(status_code=400, detail="濞屸剝婀侀崣顖涗划婢跺秶娈戦悽鐔稿灇鏉_稑瀹")

    logger.info(
        "Resume requested for audiobook_project_id=%s chapter_id=%s run_id=%s completed=%s/%s",
        audiobook_project_id,
        chapter_id,
        checkpoint_payload.get("run_id"),
        checkpoint_payload.get("completed_segments"),
        checkpoint_payload.get("total_segments"),
    )

    return {
        "message": "Latest checkpoint metadata loaded.",
        "run_id": checkpoint_payload.get("run_id"),
        "run_status": checkpoint_payload.get("run_status"),
        "current_stage": checkpoint_payload.get("current_stage"),
        "completed_segments": checkpoint_payload.get("completed_segments"),
        "total_segments": checkpoint_payload.get("total_segments"),
        "completed_segment_indices": checkpoint_payload.get("completed_segment_indices"),
        "cached_audio_paths": checkpoint_payload.get("cached_audio_paths"),
        "checkpoint_source": checkpoint_payload.get("checkpoint_source"),
    }

    if not chapter_audio.generation_progress_json:
        raise HTTPException(status_code=400, detail="娌_湁鍙_仮澶嶇殑鐢熸垚杩涘害")
    
    progress_data = json.loads(chapter_audio.generation_progress_json)
    completed_indices = progress_data.get("completed_segment_indices", [])
    cached_paths = progress_data.get("cached_audio_paths", {})
    
    logger.info(f"馃攧 鎭㈠_绔犺妭 {chapter_id} 鐢熸垚: 宸插畬鎴{len(completed_indices)} 涓_墖娈")
    
    return {
        "message": "宸叉仮澶嶇敓鎴愯繘搴",
        "completed_segments": len(completed_indices),
        "cached_audio_paths": cached_paths,
    }


@router.get("/projects/{audiobook_project_id:int}/browser-player")
async def get_browser_player_data(
    audiobook_project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """鑾峰彇娴忚_鍣ㄦ挱鏀惧櫒鎵_闇_鏁版嵁锛堢珷鑺傚垪琛ㄣ_侀煶棰慤RL銆佸瓧骞昒RL锛"""
    audiobook_project = db.query(AudiobookProject).filter(
        AudiobookProject.id == audiobook_project_id
    ).first()
    if not audiobook_project:
        raise HTTPException(status_code=404, detail="鏈夊０涔__鐩_笉瀛樺湪")
    
    project = db.query(Project).filter(
        Project.id == audiobook_project.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="鏃犳潈闄愯_闂")
    
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
    """棰勮_鏅鸿兘鍒嗗潡缁撴灉锛堜笉瀹為檯鎵ц_锛?
    Args:
        segments: 鍘熷_鍓ф湰鐗囨_鍒楄_
        max_tokens: 鍗曚釜鍒嗗潡鏈_澶?token 鏁?        min_tokens: 鏈_灏忓垎鍧?token 鏁?    """
    chunker = SmartChunker(max_tokens=max_tokens, min_tokens=min_tokens)

# 瀵圭墖娈靛垪琛ㄨ繘琛屽垎鍧
    chunked_segments = chunker.chunk_segments(segments)

    # 璁＄畻缁熻_淇_伅
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
    """浼扮畻鏂囨湰鐨?token 鏁伴噺"""
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
    """鑾峰彇鎵_鏈夊０闊崇被鍨嬮_璁惧垪琛"""
    return get_all_voice_types()


@router.get("/voice-types/{voice_type}")
async def get_voice_type_detail(
    voice_type: str,
    current_user: User = Depends(get_current_user),
):
    """鑾峰彇鎸囧畾澹伴煶绫诲瀷璇_儏"""
    preset = get_voice_type_preset(voice_type)
    if not preset:
        raise HTTPException(status_code=404, detail="澹伴煶绫诲瀷涓嶅瓨鍦")
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
    """鏍规嵁瑙掕壊灞炴_ф帹鑽愬０闊崇被鍨"""
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
    """SSE 瀹炴椂杩涘害鎺ㄩ_佺_鐐?
    瀹㈡埛绔_繛鎺ュ悗灏嗘寔缁_帴鏀朵换鍔¤繘搴_簨浠?    """
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
    """蹇__熺敓鎴愯瘯鍚_墖娈碉紙鍓?2 鍙ワ級

    Args:
        text: 瀹屾暣鏂囨湰
        voice_id: 闊宠壊 ID
        tts_model: TTS 妯_瀷
        emotion: 鎯呮劅鍙傛暟
        speed: 璇__熷弬鏁?    """
    try:
        # 鍒濆_鍖?TTS 寮曟搸
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")
        engine = AudiobookEngine(
            enable_cache=False,
            max_concurrent=1,
            llm_client=llm_client,
            tts_model=tts_model,
        )

        # 鐢熸垚棰勮_
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
        logger.error(f"鉂棰勮_鐢熸垚澶辫触: {e}")
        raise HTTPException(status_code=500, detail=f"棰勮_鐢熸垚澶辫触: {str(e)}")


@router.post("/retries/config")
async def configure_retry(
    max_retries: int = Body(3, embed=True),
    initial_delay: float = Body(1.0, embed=True),
    backoff_factor: float = Body(2.0, embed=True),
    enable_degraded: bool = Body(True, embed=True),
    current_user: User = Depends(get_current_user),
):
    """閰嶇疆閲嶈瘯绛栫暐

    Args:
        max_retries: 鏈_澶ч噸璇曟_鏁?        initial_delay: 鍒濆_寤惰繜锛堢_锛?        backoff_factor: 閫_閬垮洜瀛?        enable_degraded: 鏄_惁鍚_敤闄嶇骇
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor,
        enable_degraded=enable_degraded,
    )
    return {
        "message": "閲嶈瘯閰嶇疆宸叉洿鏂",
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
    force_regenerate: bool = False,  # 馃啎 鏂板_鍙傛暟锛氭槸鍚_己鍒堕噸鏂扮敓鎴愬墽鏈?
    tracker=None,
):
    """鍚庡彴鐢熸垚鏈夊０涔__愬墽鏈?璇勫_銆戜换鍔★紙涓嶆墽琛孴TS鍜屾贩闊筹級銆?

    娴佺▼锛?
    1. 鍒濆_鍖朅udiobookEngine
    2. 閫愮珷鐢熸垚鍓ф湰涓庤川閲忚瘎瀹?
    3. 灏嗙粨鏋滆_鐩栧啓鍏?ChapterAudio.script_json/script_review_json
    """
    from app.db.base import SessionLocal
    db = SessionLocal()

    try:
        logger.info(f"馃摑 寮_濮嬪悗鍙扮敓鎴愭湁澹颁功鍓ф湰: audiobook_project_id={audiobook_project_id}")

        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()

        if not audiobook_project:
            logger.error(f"鉂鏈夊０涔__鐩_笉瀛樺湪: {audiobook_project_id}")
            return

        audiobook_project.status = "processing"
        db.commit()

        # 鍒濆_鍖栧紩鎿?
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

        # 搴旂敤椤圭洰绾ч煶棰戦厤缃_紙瑙掕壊闊宠壊 + 闊虫晥/BGM锛?
        try:
            project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
            if project and project.audio_config:
                try:
                    from app.services.audiobook.project_audio_config import parse_project_audio_config
                    config_data = parse_project_audio_config(project.audio_config or "")
                except Exception as parse_err:
                    logger.warning(f"鈿狅笍 瑙ｆ瀽椤圭洰绾ч煶棰戦厤缃_け璐 {parse_err}")
                    config_data = {}
                
                # 馃噲 1. 先从数据库加载已有的音色分配（确保跨章节一致性）
                if audiobook_project.voice_mapping:
                    try:
                        existing_voice_mapping = audiobook_project.voice_mapping
                        if isinstance(existing_voice_mapping, str):
                            existing_voice_mapping = json.loads(existing_voice_mapping)
                        if isinstance(existing_voice_mapping, dict) and existing_voice_mapping:
                            engine.voice_manager.load_from_db(existing_voice_mapping)
                            logger.info(f"馃搧 从数据库加载音色分配: {len(existing_voice_mapping)} 个角色")
                    except Exception as load_err:
                        logger.warning(f"鈿狅笍 从数据库加载音色分配失败: {load_err}")
                
                # 2. 应用用户配置的音色配置（覆盖数据库中的配置）
                effective_voice_mapping = {}
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
                    logger.info(f"鉁[鍓ф湰闃舵_] 鍔犺浇瑙掕壊闊抽厤缃 {name} -> {item.get('voice_id')}")
                
                if effective_voice_mapping:
                    try:
                        engine.voice_manager.apply_project_voice_mapping(
                            effective_voice_mapping,
                            character_profiles=character_profiles,
                        )
                        logger.info(f"馃帥 [鍓ф湰闃舵_] 宸插姞杞借_鑹查煶閰嶇疆: {len(effective_voice_mapping)} 涓__鑹")
                    except Exception as e:
                        logger.warning(f"鈿狅笍 [鍓ф湰闃舵_] 搴旂敤瑙掕壊闊抽厤缃_け璐 {e}")
                
                # 2. 搴旂敤闊虫晥/BGM閰嶇疆
                audio_fx = get_audio_fx(config_data)
                if audio_fx:
                    try:
                        engine.apply_audio_fx_config(audio_fx)
                        logger.info("馃帤 [鍓ф湰闃舵_] 宸插姞杞介_鐩_骇闊虫晥/BGM 閰嶇疆")
                    except Exception as e:
                        logger.warning(f"鈿狅笍 [鍓ф湰闃舵_] 搴旂敤椤圭洰绾ч煶鏁,BGM 閰嶇疆澶辫触: {e}")
        except Exception as e:
            logger.warning(f"鈿狅笍 [鍓ф湰闃舵_] 鍔犺浇椤圭洰绾ч煶棰戦厤缃_け璐 {e}")

        # 鑾峰彇椤圭洰瑙掕壊鍒楄〃锛堝寘鍚畬鏁存。妗堬級
        from app.models.character import Character
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [c.name for c in characters if c.name]
        
        # 馃噲 鏋勫缓瀹屾暣瑙掕壊妗ｆ锛堢敤浜庡墽鏈敼缂栧拰闊宠壊鍒嗛厤锛
        character_profiles = []
        for c in characters:
            if not c.name:
                continue
            profile = {
                "name": c.name,
                "gender": c.gender,
                "age": c.age,
                "role": c.role,
                "role_position": c.role_position,
                "importance_level": c.importance_level,
                "faction": c.faction,
                "summary": c.summary,
                "tags": None,
                "relations": None,
            }
            if c.tags:
                try:
                    profile["tags"] = json.loads(c.tags) if isinstance(c.tags, str) else c.tags
                except (json.JSONDecodeError, TypeError):
                    profile["tags"] = []
            if c.relations:
                try:
                    from app.services.character_runtime_context import build_character_relations_payload
                    relations_data = build_character_relations_payload(c.relations)
                    profile["relations"] = relations_data.get("current_summary") if relations_data else None
                except Exception:
                    profile["relations"] = None
            character_profiles.append(profile)

        logger.info(f"馃摑 鍓ф湰闃舵瑙掕壊鍒楄〃: {character_list}")
        logger.info(f"馃摑 瑙掕壊妗ｆ鏁伴噺: {len(character_profiles)}")

        # 閫愮珷鐢熸垚鍓ф湰涓庤瘎瀹?
        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(f"馃摉 [鑴氭湰闃舵_] 澶勭悊绔犺妭 {i}/{len(chapter_ids)}: chapter_id={chapter_id}")

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"鈿狅笍 绔犺妭涓嶅瓨鍦 {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="script_only",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                    )
                    continue

                # 馃啎 鎸佷箙鍖栦紭鍖栵細妫_鏌ユ槸鍚_凡鏈夊墽鏈?
                chapter_audio = db.query(ChapterAudio).filter(
                    ChapterAudio.audiobook_project_id == audiobook_project_id,
                    ChapterAudio.chapter_id == chapter_id,
                ).first()

                # 濡傛灉绔犺妭宸叉湁鍓ф湰涓旀湭寮哄埗閲嶇敓鎴愶紝鍒欐牴鎹_墽鏈_姸鎬佸喅瀹氭槸鍚_烦杩?
                if chapter_audio and chapter_audio.script_json and not force_regenerate:
                    if chapter_audio.script_status in ["reviewed", "approved"]:
                        logger.info(f"鉁[璺宠繃] 绔犺妭 {chapter_id} 宸叉湁{chapter_audio.script_status}鍓ф湰锛屼繚鎸佷笉鍙")
                        audiobook_project.completed_chapters += 1
                        _update_chapter_run_state(
                            db,
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                            run_type="script_only",
                            status="completed",
                            current_stage="completed",
                            progress=1.0,
                            total_segment_count=chapter_audio.segment_count or 0,
                            completed_segment_count=chapter_audio.segment_count or 0,
                            checkpoint_patch={
                                "reuse_existing_script": True,
                                "script_status": chapter_audio.script_status,
                            },
                        )
                        db.commit()
                        continue
                    else:
                        logger.info(f"馃攧 [瑕嗙洊] 绔犺妭 {chapter_id} 鍓ф湰鐘舵_佷负{chapter_audio.script_status}锛屽皢閲嶆柊鐢熸垚")
                elif force_regenerate and chapter_audio and chapter_audio.script_json:
                    logger.info(f"馃攧 [寮哄埗閲嶇敓鎴怾 绔犺妭 {chapter_id} 灏嗚_鐩栫幇鏈夊墽鏈")

                result = await engine.prepare_chapter_script(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    character_profiles=character_profiles,
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

                gen_time_str = stats.get("generation_time", "0绉")
                try:
                    chapter_audio.generation_time = float(str(gen_time_str).replace("绉", ""))
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
                # 馃敡 淇__锛氬彧鍦ㄩ_娆＄敓鎴愭垨寮哄埗閲嶇敓鎴愭椂璁剧疆涓簆ending锛岄伩鍏嶈_鐩栫敤鎴锋墜鍔ㄨ_缃_殑鐘舵_?
                if not chapter_audio.script_status or force_regenerate:
                    chapter_audio.script_status = "pending"
                else:
# 淇濈暀鍘熸湁鐘舵_侊紙approved/reviewed锛
                    logger.info(f"   鉁?淇濈暀绔犺妭 {chapter_id} 鍓ф湰鐘舵_? {chapter_audio.script_status}")

                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="script_only",
                    status="completed",
                    current_stage="completed",
                    progress=1.0,
                    total_segment_count=parse_stats.get("total_segments", 0),
                    completed_segment_count=parse_stats.get("total_segments", 0),
                    checkpoint_patch={
                        "engine_task_id": result.get("task_id"),
                        "script_status": chapter_audio.script_status,
                    },
                )
                audiobook_project.completed_chapters += 1
                
                # 🆕 保存音色分配到数据库（确保跨章节一致性）
                try:
                    voice_mapping_to_save = engine.voice_manager.export_to_db()
                    if voice_mapping_to_save:
                        # 合并现有的voice_mapping和新的分配
                        existing_mapping = audiobook_project.voice_mapping or {}
                        if isinstance(existing_mapping, str):
                            try:
                                existing_mapping = json.loads(existing_mapping)
                            except (json.JSONDecodeError, TypeError):
                                existing_mapping = {}
                        
                        # 新分配的音色优先（用户手动配置的保留）
                        merged_mapping = {**existing_mapping, **voice_mapping_to_save}
                        audiobook_project.voice_mapping = merged_mapping
                        
                        logger.info(f"💾 已保存音色分配到数据库: {len(voice_mapping_to_save)} 个角色")
                except Exception as save_err:
                    logger.warning(f"⚠️ 保存音色分配到数据库失败: {save_err}")
                
                db.commit()

            except Exception as e:
                logger.error(f"鉂[鑴氭湰闃舵_] 绔犺妭 {chapter_id} 澶勭悊寮傚父: {e}")
                audiobook_project.failed_chapters += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="script_only",
                    status="failed",
                    current_stage="failed",
                    progress=0.0,
                    error_message=str(e),
                )
                db.commit()
                import traceback
                traceback.print_exc()

        audiobook_project.status = "completed"
        db.commit()

        logger.info("馃帀 鏈夊０涔_墽鏈_敓鎴愬畬鎴")
        logger.info(
            f"   - 鎴愬姛: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}"
        )

    finally:
        db.close()


async def generate_audiobook_audio_from_scripts_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-flash",
    tracker=None,
):
    """鍚庡彴鐢熸垚鏈夊０涔_煶棰戜换鍔★紙鍩轰簬宸茬敓鎴?浜哄伐瀹_牳鍚庣殑鍓ф湰锛夈_?

    鐢ㄤ簬涓ら樁娈垫祦绋嬬殑绗?闃舵_锛?
    1. 璇诲彇 ChapterAudio.script_json 浣滀负鏈夊０鍓ф湰
    2. 璋冪敤 AudiobookEngine.generate_chapter_audio_from_script 鐢熸垚闊抽_
    3. 鏇存柊 ChapterAudio.audio_path/duration/file_size/final_audio_review_json 绛夊瓧娈?
    """
    from app.db.base import SessionLocal
    db = SessionLocal()

    try:
        logger.info(
            f"馃帣锔寮_濮嬪熀浜庡墽鏈_殑鏈夊０涔_煶棰戠敓鎴 audiobook_project_id={audiobook_project_id}, chapters={chapter_ids}"
        )

        # 1. 鑾峰彇鏈夊０涔__鐩?
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()

        if not audiobook_project:
            logger.error(f"鉂鏈夊０涔__鐩_笉瀛樺湪: {audiobook_project_id}")
            return

        # 2. 閲嶇疆骞舵爣璁扮姸鎬?
        audiobook_project.status = "processing"
        audiobook_project.completed_chapters = 0
        audiobook_project.failed_chapters = 0
        audiobook_project.total_duration = 0.0
        audiobook_project.total_cost = 0.0
        db.commit()

        # 3. 鍒濆_鍖栧紩鎿?
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

        # 鑾峰彇椤圭洰涓庣珷鑺備俊鎭_紙鐢ㄤ簬鏂囦欢璺_緞鍜岄_鏉愶級
        project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
        novel_genre = (project.genre or "绉戝够") if project else "绉戝够"
        novel_theme = (project.sub_genre or "鏈_煡涓婚_") if project else "鏈_煡涓婚_"

        # 璁＄畻鏈__鐢熸垚搴斿綋浣跨敤鐨勮_鑹查煶閰嶇疆锛?
        # 浠ュ凡鏈夌殑 audiobook_project.voice_mapping 涓哄熀纭_锛屽彔鍔犳渶鏂扮殑 Project.audio_config.characters锛堝_鏈夛級锛?
        # 鍚庤_呬紭鍏堢骇鏇撮珮锛岀‘淇濅簩闃舵_鐢熸垚涔熻兘搴旂敤鏈_鏂扮殑鍓嶇_閰嶇疆锛堜緥濡傝嫃濞滃コ澹帮級銆?
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
                        logger.warning("鈿狅笍 璺宠繃鏃犲悕绉扮殑瑙掕壊闊抽厤缃__")
                        continue
                    effective_voice_mapping[name] = {
                        "voice_id": item.get("voice_id"),
                        "volume": item.get("volume", 50),
                        "speed": item.get("speed"),
                        "pitch": item.get("pitch"),
                    }
            except Exception as e:
                logger.warning(f"鈿狅笍 鍚堝苟椤圭洰绾ц_鑹查煶閰嶇疆澶辫触锛屽皢缁х画浣跨敤宸叉湁 voice_mapping: {e}")

        # 搴旂敤瑙掕壊闊抽厤缃_埌寮曟搸锛堝_鏈夛級
        if effective_voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(effective_voice_mapping)
                logger.info(
                    f"馃帥 宸插姞杞借_鑹查煶閰嶇疆: {len(effective_voice_mapping)} 涓__鑹"
                )
            except Exception as e:
                logger.warning(f"鈿狅笍 搴旂敤瑙掕壊闊抽厤缃_け璐 {e}")

        # 搴旂敤椤圭洰绾ч煶鏁?BGM 閰嶇疆锛堝_鏈夛級
        audio_fx = None
        if project and project.audio_config:
            try:
                from app.services.audiobook.project_audio_config import parse_project_audio_config
                config_data = parse_project_audio_config(project.audio_config or "")
                audio_fx = get_audio_fx(config_data)
            except Exception as parse_err:
                logger.warning(f"鈿狅笍 瑙ｆ瀽椤圭洰绾ч煶棰戦厤缃_け璐 {parse_err}")

        if audio_fx:
            try:
                engine.apply_audio_fx_config(audio_fx)
                logger.info("馃帤 宸插姞杞介_鐩_骇闊虫晥/BGM 閰嶇疆")
            except Exception as e:
                logger.warning(f"鈿狅笍 搴旂敤椤圭洰绾ч煶鏁,BGM 閰嶇疆澶辫触: {e}")

        total_duration = 0.0
        total_cost = 0.0

        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(
                    f"馃摉 [闊抽_闃舵_] 澶勭悊绔犺妭 {i}/{len(chapter_ids)}: chapter_id={chapter_id}"
                )

                # 璇诲彇绔犺妭涓庤剼鏈?
                chapter_audio = db.query(ChapterAudio).filter(
                    ChapterAudio.audiobook_project_id == audiobook_project_id,
                    ChapterAudio.chapter_id == chapter_id,
                ).first()

                if not chapter_audio or not chapter_audio.script_json:
                    logger.warning(
                        f"鈿狅笍 绔犺妭 {chapter_id} 缂哄皯鍓ф湰鏁版嵁(script_json涓虹_)锛岃烦杩囪_绔犺妭"
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="script_missing",
                    )
                    db.commit()
                    continue

                script_status = (chapter_audio.script_status or "").lower()
                if script_status != "approved":
                    logger.warning(
                        f"鈿狅笍 绔犺妭 {chapter_id} 鍓ф湰灏氭湭閫氳繃璇勫_(script_status={chapter_audio.script_status})锛岃烦杩囬煶棰戠敓鎴"
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"script_not_approved:{chapter_audio.script_status}",
                    )
                    db.commit()
                    continue

                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"鈿狅笍 绔犺妭涓嶅瓨鍦 {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                    )
                    db.commit()
                    continue

                try:
                    script_segments_data = json.loads(chapter_audio.script_json)
                except Exception as parse_err:
                    logger.error(f"鉂瑙ｆ瀽绔犺妭鍓ф湰JSON澶辫触 chapter_id={chapter_id}: {parse_err}")
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"invalid_script_json:{parse_err}",
                    )
                    db.commit()
                    continue

                if not isinstance(script_segments_data, list):
                    logger.warning(
                        f"鈿狅笍 绔犺妭 {chapter_id} 鍓ф湰鏁版嵁鏍煎紡寮傚父锛屾湡鏈涗负鍒楄_锛屽疄闄呬负 {type(script_segments_data)}"
                    )
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=f"invalid_script_payload:{type(script_segments_data)}",
                    )
                    db.commit()
                    continue

                # 鐢熸垚杈撳嚭璺_緞
                output_path = f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3"

                # 璋冪敤寮曟搸鐢熸垚闊抽_
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
                logger.info(f"馃幆 [闊抽_闃舵_] Chapter {chapter_id} TaskID: {task_id}")

                if result.get("success"):
                    stats = result.get("stats") or {}
                    parse_stats = stats.get("parse_stats") or {}
                    tts_stats = stats.get("tts_stats") or {}

                    # 鏇存柊绔犺妭闊抽_璁板綍锛堣_鐩栧啓鍏ワ級
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

                    gen_time_str = stats.get("generation_time", "0绉")
                    try:
                        chapter_audio.generation_time = float(
                            str(gen_time_str).replace("绉", "")
                        )
                    except Exception:
                        pass

                    cost_str = tts_stats.get("estimated_cost", "楼0.00")
                    try:
                        chapter_audio.tts_cost = float(
                            str(cost_str).replace("楼", "").replace("$", "")
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
                                f"鈿狅笍 搴忓垪鍖栨渶缁堥煶棰戣瘎瀹＄粨鏋滃け璐,chapter_id={chapter_id}: {dump_err}"
                            )

                    audiobook_project.completed_chapters += 1
                    total_duration += result.get("duration") or 0.0
                    try:
                        total_cost += float(
                            str(cost_str).replace("楼", "").replace("$", "")
                        )
                    except Exception:
                        pass

                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="completed",
                        current_stage="completed",
                        progress=1.0,
                        total_segment_count=parse_stats.get("total_segments", chapter_audio.segment_count or 0),
                        completed_segment_count=parse_stats.get("total_segments", chapter_audio.segment_count or 0),
                        checkpoint_patch={
                            "engine_task_id": task_id,
                            "output_path": output_path,
                        },
                    )

                    logger.info(f"鉁绔犺妭 {chapter_id} 闊抽_鐢熸垚鎴愬姛")
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error(
                        f"鉂绔犺妭 {chapter_id} 闊抽_鐢熸垚澶辫触: {result.get('error')}"
                    )
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="audio_from_scripts",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=str(result.get("error") or "audio_generation_failed"),
                    )

                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()

            except Exception as e:
                logger.error(f"鉂绔犺妭 {chapter_id} 闊抽_闃舵_澶勭悊寮傚父: {e}")
                audiobook_project.failed_chapters += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="audio_from_scripts",
                    status="failed",
                    current_stage="failed",
                    progress=0.0,
                    error_message=str(e),
                )
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
            logger.warning("璁板綍鏈夊０涔_Н鍒嗙粨绠楀け璐,audiobook_project_id=%s: %s", audiobook_project_id, exc)

        logger.info("馃帀 鍩轰簬鍓ф湰鐨勬湁澹颁功闊抽_鐢熸垚瀹屾垚!")
        logger.info(
            f"   - 鎴愬姛: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}"
        )
        logger.info(f"   - 鎬绘椂闀 {total_duration:.1f}绉")
        logger.info(f"   - 鎬绘垚鏈 楼{total_cost:.2f}")

    except Exception as e:
        logger.error(f"鉂鍩轰簬鍓ф湰鐨勫悗鍙扮敓鎴愪换鍔_け璐 {e}")
        import traceback
        traceback.print_exc()

        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="鏈夊０涔_煶棰戠敓鎴愬け璐ワ紝宸查噴鏀惧喕缁撶Н鍒嗐_",
                )
            except Exception as release_exc:
                logger.warning("閲婃斁鏈夊０涔_喕缁撶Н鍒嗗け璐,audiobook_project_id=%s: %s", audiobook_project_id, release_exc)

    finally:
        db.close()


async def generate_audiobook_background(
    audiobook_project_id: int,
    chapter_ids: List[int],
    tts_model: str = "qwen3-tts-flash",
    tracker=None,
):
    """
    鍚庡彴鐢熸垚鏈夊０涔_换鍔?
    
    娴佺▼锛?
    1. 鍒濆_鍖朅udiobookEngine
    2. 閫愮珷鐢熸垚闊抽_
    3. 鏇存柊杩涘害鍜岀姸鎬?
    4. 淇濆瓨闊抽_鏂囦欢
    """
    from app.db.base import SessionLocal
    db = SessionLocal()
    
    try:
        logger.info(f"馃帣锔寮_濮嬪悗鍙扮敓鎴愭湁澹颁功: audiobook_project_id={audiobook_project_id}")
        
        # 鏇存柊鐘舵_佷负澶勭悊涓?
        audiobook_project = db.query(AudiobookProject).filter(
            AudiobookProject.id == audiobook_project_id
        ).first()
        
        if not audiobook_project:
            logger.error(f"鉂鏈夊０涔__鐩_笉瀛樺湪: {audiobook_project_id}")
            return
        
        audiobook_project.status = "processing"
        db.commit()
        
        # 鍒濆_鍖栧紩鎿庯紙浣跨敤鍏ㄥ眬瀹炰緥锛?
        from app.services.audiobook import get_engine_instance, set_engine_instance
        from core.unified_llm_client import get_llm_client
        
        # 鍒涘缓LLM瀹㈡埛绔_紙蹇呴渶锛?
        llm_client = get_llm_client(strategy="conservative")
        
        progress_handler = _build_progress_handler(tracker, chapter_ids)

        engine = AudiobookEngine(
            enable_cache=audiobook_project.enable_cache,
            max_concurrent=1,  # 闄嶄綆骞跺彂閬垮厤闄愭祦
            llm_client=llm_client,  # 蹇呴_浼犲叆LLM瀹㈡埛绔?
            tts_model=tts_model,
            progress_handler=progress_handler,
        )
        # 璁剧疆涓哄叏灞_瀹炰緥锛屼緵鐘舵_佹煡璇_娇鐢?
        set_engine_instance(engine)

        # 搴旂敤椤圭洰绾ч煶鏁?BGM 閰嶇疆锛堝_鏈夛級
        try:
            project = db.query(Project).filter(Project.id == audiobook_project.project_id).first()
            if project and project.audio_config:
                try:
                    from app.services.audiobook.project_audio_config import parse_project_audio_config
                    config_data = parse_project_audio_config(project.audio_config or "")
                except Exception as parse_err:
                    logger.warning(f"鈿狅笍 瑙ｆ瀽椤圭洰绾ч煶棰戦厤缃_け璐 {parse_err}")
                    config_data = {}
                from app.services.audiobook.project_audio_config import get_audio_fx
                audio_fx = get_audio_fx(config_data)
                if audio_fx:
                    try:
                        engine.apply_audio_fx_config(audio_fx)
                        logger.info("馃帤 宸插姞杞介_鐩_骇闊虫晥/BGM 閰嶇疆")
                    except Exception as e:
                        logger.warning(f"鈿狅笍 搴旂敤椤圭洰绾ч煶鏁,BGM 閰嶇疆澶辫触: {e}")
        except Exception as e:
            logger.warning(f"鈿狅笍 鍔犺浇椤圭洰绾ч煶棰戦厤缃_け璐 {e}")
        
        # 搴旂敤椤圭洰绾ц_鑹查煶閰嶇疆锛堝_鏈夛級
        if audiobook_project.voice_mapping:
            try:
                engine.voice_manager.apply_project_voice_mapping(audiobook_project.voice_mapping)
                logger.info(f"馃帥 宸插姞杞介_鐩_骇瑙掕壊闊抽厤缃 {len(audiobook_project.voice_mapping)} 涓__鑹")
            except Exception as e:
                logger.warning(f"鈿狅笍 搴旂敤椤圭洰绾ц_鑹查煶閰嶇疆澶辫触: {e}")
        
        # 鑾峰彇椤圭洰瑙掕壊鍒楄_
        from app.models.character import Character
        characters = db.query(Character).filter(
            Character.project_id == audiobook_project.project_id
        ).all()
        character_list = [c.name for c in characters if c.name]
        
        logger.info(f"馃摑 瑙掕壊鍒楄_: {character_list}")
        
        # 閫愮珷鐢熸垚
        total_duration = 0.0
        total_cost = 0.0
        
        for i, chapter_id in enumerate(chapter_ids, 1):
            try:
                logger.info(f"馃摉 澶勭悊绔犺妭 {i}/{len(chapter_ids)}: chapter_id={chapter_id}")
                
                # 鑾峰彇绔犺妭鍐呭_
                chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
                if not chapter:
                    logger.warning(f"鈿狅笍 绔犺妭涓嶅瓨鍦 {chapter_id}")
                    audiobook_project.failed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message="chapter_not_found",
                    )
                    continue
                
                # 鐢熸垚闊抽_
                result = await engine.generate_chapter_audio(
                    chapter_content=chapter.content or "",
                    chapter_id=chapter_id,
                    character_list=character_list,
                    output_path=f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3",
                    chapter_title=chapter.title or "",
                    chapter_summary=chapter.summary or "",
                    summary_data=chapter.summary_data,
                )
                
                # 璁板綍task_id鍒版暟鎹_簱锛堝彲閫夛級
                task_id = result.get('task_id')
                logger.info(f"馃幆 TaskID: {task_id}")
                
                if result["success"]:
                    # 馃啎 鑾峰彇鎴栧垱寤虹珷鑺傞煶棰戣_褰曪紙閬垮厤瑕嗙洊宸叉湁鍓ф湰锛?
                    chapter_audio = db.query(ChapterAudio).filter(
                        ChapterAudio.audiobook_project_id == audiobook_project_id,
                        ChapterAudio.chapter_id == chapter_id,
                    ).first()
                    
                    if not chapter_audio:
                        # 棣栨_鐢熸垚锛氬垱寤烘柊璁板綍
                        chapter_audio = ChapterAudio(
                            audiobook_project_id=audiobook_project_id,
                            chapter_id=chapter_id,
                        )
                        db.add(chapter_audio)
                        logger.info(f"馃啎 鍒涘缓鏂扮殑绔犺妭闊抽_璁板綍: chapter_id={chapter_id}")
                    else:
                        # 馃敟 閲嶈_锛氫繚鐣欏凡鏈夌殑鍓ф湰鏁版嵁
                        logger.info(f"鈾伙笍 鏇存柊宸叉湁绔犺妭闊抽_璁板綍: chapter_id={chapter_id}")
                        if chapter_audio.script_json:
                            logger.info(f"   鉁淇濈暀宸叉湁鍓ф湰锛坰tatus={chapter_audio.script_status}锛")
                    
                    # 鏇存柊闊抽_鐩稿叧瀛楁_锛堜笉瑕嗙洊鍓ф湰锛?
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
                    
                    gen_time_str = stats.get("generation_time", "0绉")
                    try:
                        chapter_audio.generation_time = float(str(gen_time_str).replace("绉", ""))
                    except Exception:
                        pass
                    
                    cost_str = tts_stats.get("estimated_cost", "楼0.00")
                    try:
                        chapter_audio.tts_cost = float(
                            str(cost_str).replace("楼", "").replace("$", "")
                        )
                    except Exception:
                        pass
                    
                    total_duration += result["duration"]
                    try:
                        total_cost += float(str(cost_str).replace("楼", "").replace("$", ""))
                    except Exception:
                        pass
                    
                    audiobook_project.completed_chapters += 1
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="completed",
                        current_stage="completed",
                        progress=1.0,
                        total_segment_count=parse_stats.get("total_segments", 0),
                        completed_segment_count=parse_stats.get("total_segments", 0),
                        checkpoint_patch={
                            "engine_task_id": task_id,
                            "output_path": f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3",
                        },
                    )
                    logger.info(f"鉁绔犺妭 {chapter_id} 鐢熸垚鎴愬姛")
                else:
                    audiobook_project.failed_chapters += 1
                    logger.error(f"鉂绔犺妭 {chapter_id} 鐢熸垚澶辫触: {result.get('error')}")
                    _update_chapter_run_state(
                        db,
                        audiobook_project_id=audiobook_project_id,
                        chapter_id=chapter_id,
                        run_type="full",
                        status="failed",
                        current_stage="failed",
                        progress=0.0,
                        error_message=str(result.get("error") or "full_generation_failed"),
                    )
                
                # 鏇存柊杩涘害
                audiobook_project.total_duration = total_duration
                audiobook_project.total_cost = total_cost
                db.commit()
                
            except Exception as e:
                logger.error(f"鉂绔犺妭 {chapter_id} 澶勭悊寮傚父: {e}")
                audiobook_project.failed_chapters += 1
                _update_chapter_run_state(
                    db,
                    audiobook_project_id=audiobook_project_id,
                    chapter_id=chapter_id,
                    run_type="full",
                    status="failed",
                    current_stage="failed",
                    progress=0.0,
                    error_message=str(e),
                )
                db.commit()
                import traceback
                traceback.print_exc()
        
        # 鏇存柊鏈_缁堢姸鎬?
        audiobook_project.status = "completed"
        audiobook_project.total_duration = total_duration
        audiobook_project.total_cost = total_cost
        db.commit()

        try:
            record_audiobook_billing_settle(db=db, audiobook_project_id=audiobook_project_id)
        except Exception as exc:
            logger.warning("璁板綍鏈夊０涔_Н鍒嗙粨绠楀け璐,audiobook_project_id=%s: %s", audiobook_project_id, exc)

        logger.info(f"馃帀 鏈夊０涔_敓鎴愬畬鎴")
        logger.info(f"   - 鎴愬姛: {audiobook_project.completed_chapters}/{audiobook_project.total_chapters}")
        logger.info(f"   - 鎬绘椂闀 {total_duration:.1f}绉")
        logger.info(f"   - 鎬绘垚鏈 楼{total_cost:.2f}")
        
    except Exception as e:
        logger.error(f"鉂鍚庡彴鐢熸垚浠诲姟澶辫触: {e}")
        import traceback
        traceback.print_exc()
        
        # 鏇存柊鐘舵_佷负澶辫触
        if audiobook_project:
            audiobook_project.status = "failed"
            db.commit()
            try:
                record_audiobook_billing_release(
                    db=db,
                    audiobook_project_id=audiobook_project_id,
                    reason="鏈夊０涔_敓鎴愬け璐ワ紝宸查噴鏀惧喕缁撶Н鍒嗐_",
                )
            except Exception as release_exc:
                logger.warning("閲婃斁鏈夊０涔_喕缁撶Н鍒嗗け璐,audiobook_project_id=%s: %s", audiobook_project_id, release_exc)
    
    finally:
        db.close()

