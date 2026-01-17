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
from urllib.parse import quote
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Body, Depends, HTTPException, status, Response, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.audiobook import AudiobookProject, ChapterAudio
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
    AudiobookTaskStatus,
    CosyVoiceCloneCreateRequest,
)
from app.celery_app import celery_app
from app.services.audiobook import AudiobookEngine
from app.services.audiobook.tts_engine import RetryConfig, TTSEngine
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_catalog import get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.cosyvoice_clone_client import (
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    delete_cosyvoice_clone,
    get_clone_display_name,
    list_cosyvoice_v3_plus_clones,
    save_clone_display_name,
)
from app.services.audiobook.app_service import AudiobookAppService
from app.services.audiobook.repository import (
    AudiobookProjectRepository,
    ChapterAudioRepository,
    ProjectRepository,
    AudiobookTaskRepository,
)
from dataclasses import asdict, is_dataclass

logger = logging.getLogger(__name__)


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
    engine = TTSEngine(
        enable_cache=False,
        max_concurrent=1,
        model=model_name,
        request_delay=0.0,
        retry_config=preview_retry,
    )
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
        audio_bytes = await engine.synthesize(text, voice_params)
    except Exception as exc:
        logger.warning("TTS预览失败: %s", exc)
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


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = "qwen3-tts-flash",
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = (model or "qwen3-tts-flash").strip()
    if model not in {"qwen3-tts-flash", "cosyvoice-v3-plus"}:
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

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址。
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建有声书项目并启动生成任务。

    工作流：
    1. 通过应用服务校验项目与章节，并创建有声书项目记录
    2. 根据 generation_mode 启动对应的后台生成任务
    """
    service = AudiobookAppService(db=db, current_user=current_user)
    audiobook_project = service.create_audiobook_project(request)

    # 4. 后台启动生成任务（通过 Celery 队列）
    job_type = "script_only" if getattr(request, "generation_mode", "full") == "script_only" else "full"
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

    return {
        "success": True,
        "audiobook_project_id": audiobook_project.id,
        "job_id": async_result.id,
        "task_type": job_type,
        "message": "有声书生成任务已进入队列",
        "total_chapters": len(request.chapter_ids),
    }


@router.get("/projects/{audiobook_project_id}", response_model=dict)
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


@router.get("/projects/by-project/{project_id}")
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


@router.post("/projects/{audiobook_project_id}/generate-audio-from-scripts", response_model=dict)
async def trigger_generate_audio_from_scripts(
    audiobook_project_id: int,
    request: GenerateAudioFromScriptsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """触发基于已生成剧本的章节音频生成（两阶段流程第2阶段）。

    - 如果未显式指定 chapter_ids，则默认选择该有声书项目下 script_status == "approved" 且已存在 script_json 的章节。
    - 如果显式指定 chapter_ids，则仅要求对应章节存在 script_json（不强制检查 script_status），用于高级/调试场景。
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

    return {
        "success": True,
        "audiobook_project_id": audiobook_project_id,
        "chapter_ids": target_chapter_ids,
        "job_id": async_result.id,
        "message": "已启动基于剧本的音频生成任务",
    }



@router.delete("/projects/{audiobook_project_id}")
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


@router.delete("/chapter-audios/{chapter_audio_id}")
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


@router.post("/projects/{audiobook_project_id}/restore")
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
        "restored_at": datetime.utcnow().isoformat()
    }


@router.post("/chapter-audios/{chapter_audio_id}/restore")
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
        "restored_at": datetime.utcnow().isoformat()
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

@router.get("/projects/{audiobook_project_id}/chapters/{chapter_id}/script", response_model=dict)
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


@router.put("/projects/{audiobook_project_id}/chapters/{chapter_id}/script", response_model=dict)
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
        from app.services.llm_client import get_llm_client

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
        from app.services.llm_client import get_llm_client

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
                logger.info(f"🔍 [调试] 项目音频配置: {get_characters_for_model(config_data, tts_model)}")
                for item in get_characters_for_model(config_data, tts_model):
                    name = item.get("name")
                    if not name:
                        logger.warning(f"⚠️ [调试] 跳过无名称的配置项: {item}")
                        continue
                    effective_voice_mapping[name] = {
                        "voice_id": item.get("voice_id"),
                        "volume": item.get("volume", 50),
                        "speed": item.get("speed"),
                        "pitch": item.get("pitch"),
                    }
                    logger.info(f"✅ [调试] 加载角色音配置: {name} -> {item.get('voice_id')}")
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
        from app.services.llm_client import get_llm_client
        
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
                    output_path=f"audiobooks/project_{audiobook_project.project_id}/chapter_{chapter.chapter_number:03d}.mp3"
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
    
    finally:
        db.close()
