"""
项目API路由
"""
from fastapi import APIRouter, Body, Depends, HTTPException, status, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from typing import Dict, List, Literal, Optional
import logging
import re
from pydantic import BaseModel, ValidationError
import json
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.character import Character
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse,
    ChapterCreate, ChapterUpdate, ChapterResponse
)
from app.schemas.review_config import (
    MultiModelReviewConfig,
    ReviewConfigResponse,
    ReviewConfigUpdate,
)
from app.core.security import get_current_user
from app.services.workflow_context_builder import WorkflowContextBuilder
from app.services.audiobook.project_audio_config import (
    get_audio_engine_mode,
    get_audio_fx,
    get_characters_for_model,
    get_engine_branch,
    get_scene_generation_preferences,
    get_seed_audio_model,
    parse_project_audio_config,
    resolve_engine_mode,
    set_audio_fx,
    set_audio_engine_mode,
    set_seed_audio_model,
    set_characters_for_model,
    set_engine_branch,
)
from app.services.audiobook.tts_model_ids import normalize_audiobook_tts_model
from app.services.audiobook.chapter_character_scope import select_chapter_characters
from app.services.audiobook.voice_auto_assignment import AutoVoiceAssignmentPool

logger = logging.getLogger("uvicorn.error")


class CharacterAudioConfig(BaseModel):
    """单个角色的音频配置"""
    character_id: int
    name: str
    voice_id: str
    volume: Optional[int] = None
    speed: Optional[float] = None
    pitch: Optional[int] = None
    tts_model: Optional[str] = None
    voice_type: Optional[str] = None
    personality: Optional[str] = None
    emotion_tendency: Optional[str] = None
    voice_clone_data_url: Optional[str] = None
    voice_design_prompt: Optional[str] = None
    mimo_voice_asset_id: Optional[str] = None
    stepaudio_voice_asset_id: Optional[str] = None
    source: Optional[str] = None  # "user" | "ai_suggest" | None
    reference_source: Optional[str] = None
    reference_audio_url: Optional[str] = None
    voice_pool_publication_id: Optional[str] = None


class AudioFxConfig(BaseModel):
    """项目级音效与配乐配置"""
    enable_sound_effects: bool = True
    enable_music: bool = True
    sound_effect_density: str = "medium"  # low/medium/high/off
    music_density: str = "medium"  # low/medium/high/off
    bgm_theme: Optional[str] = None
    bgm_style: Optional[str] = None
    # 配乐基准音量（dB）：-27 继续压低配乐确保人声清晰；旧版默认 -36 曾导致配乐几乎不可闻
    base_bgm_volume: float = -27.0
    intelligent_balance: bool = True
    bgm_crossfade_ms: int = 0
    sound_effect_ducking: bool = True
    sound_effect_priority: str = "dialogue"  # dialogue/sfx
    sound_effect_ducking_threshold_dbfs: float = -35.0
    # ducking 衰减：-4dB 保留人声优先同时让归一化后的触发音可穿透对白（旧值 -6 曾致掩蔽）
    sound_effect_ducking_reduction_db: float = -4.0
    sound_effect_ducking_chunk_ms: int = 250


class SceneGenerationPreferences(BaseModel):
    """场景生成创作偏好（仅 seed_scene）"""
    music_enabled: bool = True
    music_style: Optional[str] = None
    soundscape_intensity: str = "medium"
    performance_style: str = "cinematic"
    timeline_mode: str = "natural"
    terminal_policy: str = "manual_review"
    semantic_review_enabled: bool = True
    semantic_review_mode: str = "shadow"


class EngineTtsModelConfig(BaseModel):
    """引擎分支下单个 TTS 模型的角色配置"""
    characters: List[CharacterAudioConfig] = []


class EngineBranchConfig(BaseModel):
    """引擎分支配置"""
    tts_models: Optional[Dict[str, EngineTtsModelConfig]] = None
    audio_fx: Optional[AudioFxConfig] = None
    scene_generation_preferences: Optional[SceneGenerationPreferences] = None


class ProjectAudioConfig(BaseModel):
    """项目级音频配置"""
    characters: List[CharacterAudioConfig] = []
    audio_fx: Optional[AudioFxConfig] = None
    audio_engine_mode: Optional[Literal["legacy_stems", "seed_scene", "auto"]] = None
    seed_audio_model: Optional[Literal["seed-audio-1.0", "seed-audio-1.0-multilingual"]] = None
    engines: Optional[Dict[str, EngineBranchConfig]] = None


class EnginePreferencesResponse(BaseModel):
    """引擎创作偏好响应"""
    engine_mode: str
    scene_generation_preferences: Optional[SceneGenerationPreferences] = None
    audio_fx: Optional[AudioFxConfig] = None


PERSISTED_CHARACTER_AUDIO_CONFIG_FIELDS = (
    "character_id",
    "name",
    "voice_id",
    "tts_model",
)


def _resolve_character_audio_voice_id(config: CharacterAudioConfig) -> str:
    voice_id = str(config.voice_id or "").strip()
    if voice_id:
        return voice_id

    tts_model = normalize_audiobook_tts_model(config.tts_model)
    mimo_voice_asset_id = str(config.mimo_voice_asset_id or "").strip()
    if mimo_voice_asset_id:
        if tts_model == "mimo-v2.5-tts-voicedesign":
            return f"mimo_design:{mimo_voice_asset_id}"
        if tts_model == "mimo-v2.5-tts-voiceclone":
            return f"mimo_clone:{mimo_voice_asset_id}"

    stepaudio_voice_asset_id = str(config.stepaudio_voice_asset_id or "").strip()
    if stepaudio_voice_asset_id and tts_model == "stepaudio-2.5-tts":
        return f"stepaudio_clone:{stepaudio_voice_asset_id}"

    return voice_id


def _dump_persisted_character_audio_config(config: CharacterAudioConfig) -> dict:
    data = config.model_dump(
        include=set(PERSISTED_CHARACTER_AUDIO_CONFIG_FIELDS),
        exclude_none=True,
    )
    data["voice_id"] = _resolve_character_audio_voice_id(config)
    return data


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

AVAILABLE_REVIEW_PRESETS = ["balanced_3", "key_chapter_5", "deep_7"]


def _allocate_next_display_no(db: Session, *, user_id: int) -> int:
    """为同一用户分配稳定递增的展示序号。"""
    db.execute(
        select(User.id)
        .where(User.id == user_id)
        .with_for_update()
    ).scalar_one()

    current_max = (
        db.query(func.max(Project.display_no))
        .filter(Project.user_id == user_id)
        .scalar()
    )
    return int(current_max or 0) + 1


def _is_untitled_project(title: Optional[str]) -> bool:
    normalized_title = (title or "").strip()
    return not normalized_title or normalized_title == "未命名项目"


def _get_owned_project(db: Session, project_id: int, current_user: User) -> Project:
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _load_review_config(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _review_config_response(config: dict) -> ReviewConfigResponse:
    try:
        multi_model_review = MultiModelReviewConfig(**(config.get("multi_model_review") or {}))
    except ValidationError:
        logger.warning("项目评审配置格式无效，已回退默认配置")
        multi_model_review = MultiModelReviewConfig()

    return ReviewConfigResponse(
        multi_model_review=multi_model_review,
        available_presets=AVAILABLE_REVIEW_PRESETS,
    )


def _sync_project_title_from_saved_concept(db: Session, project: Project) -> bool:
    if not _is_untitled_project(project.title):
        return False

    concept_text = WorkflowContextBuilder(db).read_stage_content(
        project.id,
        "concept",
        pretty_json=True,
    )
    if not concept_text:
        return False

    from app.api.v1.workflow import _extract_project_title_from_concept

    extracted_title = _extract_project_title_from_concept(concept_text)
    if not extracted_title:
        return False

    project.title = extracted_title
    db.add(project)
    return True


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的所有项目"""
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.display_no.asc(), Project.id.asc())
        .all()
    )

    updated_projects = [project for project in projects if _sync_project_title_from_saved_concept(db, project)]
    if updated_projects:
        db.commit()
        for project in updated_projects:
            db.refresh(project)

    return projects


@router.post("", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新项目"""
    project = Project(
        display_no=_allocate_next_display_no(db, user_id=current_user.id),
        user_id=current_user.id,
        title=project_data.title,
        description=project_data.description,
        genre=project_data.genre,
        sub_genre=project_data.sub_genre,
        planned_length_type=project_data.planned_length_type,
        planned_chapters_min=project_data.planned_chapters_min,
        planned_chapters_max=project_data.planned_chapters_max,
        user_outline_plan=project_data.user_outline_plan
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目详情"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    if _sync_project_title_from_saved_concept(db, project):
        db.commit()
        db.refresh(project)
    
    # 不需要手动赋值，SQLAlchemy的relationship会自动加载
    # chapters = db.query(Chapter).filter(Chapter.project_id == project_id).all()
    # project.chapters = chapters  # ❌ 删除这行，使用relationship自动加载
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    project_data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新项目"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    for key, value in project_data.dict(exclude_unset=True).items():
        setattr(project, key, value)
    
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除项目及所有关联数据
    
    级联删除内容：
    1. 数据库记录（通过 CASCADE 自动删除）：
       - chapters（章节）
       - knowledge_base（知识库条目）
       - memories（记忆记录）
       - reviews（评审记录，通过 chapter 级联）
    2. 原始 SQL 表（需要手动删除）：
       - project_settings（项目设置）
       - workflow_sessions（工作流会话）
       - generation_history（生成历史）
    3. ChromaDB 向量数据（需要手动清理）
    """
    import logging
    import os
    import shutil
    from pathlib import Path
    
    logger = logging.getLogger("uvicorn.error")
    
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    logger.info(f"🗑️ 开始删除项目: project_id={project_id}, title={project.title}")
    
    # 🧹 步骤0：删除原始 SQL 表记录（没有级联配置的表）
    try:
        from sqlalchemy import text
        
        logger.info(f"   📁 步骤0: 清理原始 SQL 表记录")
        
        # 删除 project_settings
        try:
            delete_settings = text("DELETE FROM project_settings WHERE project_id = :project_id")
            db.execute(delete_settings, {"project_id": project_id})
            db.commit()
            logger.info(f"   ✅ 已删除 project_settings 表记录")
        except Exception as e:
            logger.warning(f"   ⚠️ project_settings 删除失败: {e}")
            db.rollback()
        
        # 删除 workflow_sessions
        try:
            delete_sessions = text("DELETE FROM workflow_sessions WHERE project_id = :project_id")
            db.execute(delete_sessions, {"project_id": project_id})
            db.commit()
            logger.info(f"   ✅ 已删除 workflow_sessions 表记录")
        except Exception as e:
            logger.warning(f"   ⚠️ workflow_sessions 删除失败: {e}")
            db.rollback()
        
        # 删除 generation_history
        try:
            delete_history = text("DELETE FROM generation_history WHERE project_id = :project_id")
            db.execute(delete_history, {"project_id": project_id})
            db.commit()
            logger.info(f"   ✅ 已删除 generation_history 表记录")
        except Exception as e:
            logger.warning(f"   ⚠️ generation_history 删除失败: {e}")
            db.rollback()
        
        # 删除 chapter_plans
        try:
            delete_plans = text("DELETE FROM chapter_plans WHERE project_id = :project_id")
            db.execute(delete_plans, {"project_id": project_id})
            db.commit()
            logger.info(f"   ✅ 已删除 chapter_plans 表记录")
        except Exception as e:
            logger.warning(f"   ⚠️ chapter_plans 删除失败: {e}")
            db.rollback()
        
    except Exception as e:
        logger.error(f"   ❌ 原始 SQL 表清理失败: {e}")
        # 不阻塞删除流程，继续执行
    
    # 🧹 步骤1：清理 ChromaDB 向量数据
    try:
        from app.services.agents.knowledge_base import NovelKnowledgeBase

        logger.info(f"   💾 步骤1: 清理 ChromaDB 向量数据 (project_id: {project_id})")

        # 使用 NovelKnowledgeBase 的 delete_project 方法
        try:
            kb = NovelKnowledgeBase()
            deleted_count = kb.delete_project(project_id)

            if deleted_count > 0:
                logger.info(f"   ✅ 已从向量库删除 {deleted_count} 个文档")
            else:
                logger.info(f"   ℹ️  没有找到需要删除的向量文档")

        except Exception as e:
            logger.warning(f"   ⚠️ 向量库清理失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    except Exception as e:
        logger.error(f"   ❌ ChromaDB 清理失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        # 不阻塞删除流程，继续执行
    
    # 📁 步骤3：删除项目（数据库级联会自动删除关联数据）
    logger.info(f"   📁 步骤3: 删除数据库记录（级联删除 chapters, knowledge_base, memories, reviews）")
    db.delete(project)
    db.commit()
    
    logger.info(f"✅ 项目删除完成: project_id={project_id}")
    
    return {
        "message": "Project deleted successfully",
        "project_id": project_id,
        "cleaned": {
            "database": True,  # chapters, knowledge_base, memories, reviews
            "raw_sql_tables": True,  # project_settings, workflow_sessions, generation_history
            "chromadb": True,  # vector data
        }
    }


@router.get("/{project_id}/audio-config", response_model=ProjectAudioConfig, response_model_exclude_none=True)
async def get_project_audio_config(
    project_id: int,
    tts_model: str = Query("qwen3-tts-instruct-flash"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAudioConfig:
    """获取项目级音频配置"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    data = parse_project_audio_config(project.audio_config or "")
    resolved_mode = resolve_engine_mode(data)

    characters = [
        _dump_persisted_character_audio_config(CharacterAudioConfig(**item))
        for item in get_characters_for_model(data, tts_model, engine_mode=resolved_mode)
    ]
    audio_fx = get_audio_fx(data, engine_mode=resolved_mode)

    # 按当前引擎分支构建完整的 engines 字段供前端消费
    engines_raw = data.get("engines")
    engines = None
    if isinstance(engines_raw, dict):
        engines = engines_raw

    return ProjectAudioConfig(
        characters=characters,
        audio_fx=audio_fx,
        audio_engine_mode=resolved_mode,
        seed_audio_model=get_seed_audio_model(data),
        engines=engines,
    )


@router.put("/{project_id}/audio-config", response_model=ProjectAudioConfig, response_model_exclude_none=True)
async def update_project_audio_config(
    project_id: int,
    config: ProjectAudioConfig,
    tts_model: str = Query("qwen3-tts-instruct-flash"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAudioConfig:
    """更新项目级音频配置"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    data = parse_project_audio_config(project.audio_config or "")
    # 先落 audio_engine_mode，使 resolved_mode 反映本次请求的目标引擎
    # （GUIDE §2.2：前端切换引擎后保存到目标分支）
    if config.audio_engine_mode is not None:
        set_audio_engine_mode(data, config.audio_engine_mode)
    resolved_mode = resolve_engine_mode(data)

    characters = [
        _dump_persisted_character_audio_config(c)
        for c in (config.characters or [])
    ]
    if config.engines is not None:
        # 新客户端：engines 分支显式写入（engines.{mode}.tts_models.{model}.characters），
        # 顶层 characters/audio_fx 不落位，避免空列表清空其他引擎分支
        for mode, branch in config.engines.items():
            set_engine_branch(data, mode, branch.model_dump(exclude_none=True) if branch else {})
    else:
        # 旧客户端：顶层 characters/audio_fx 按当前引擎分支落位（向后兼容）
        set_characters_for_model(data, tts_model, characters, engine_mode=resolved_mode)
        set_audio_fx(
            data,
            config.audio_fx.model_dump(exclude_none=True) if config.audio_fx else None,
            engine_mode=resolved_mode,
        )
    if config.seed_audio_model is not None:
        set_seed_audio_model(data, config.seed_audio_model)
    project.audio_config = json.dumps(data, ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    # 重新读回已保存的分支数据（含 engines 字段）
    saved_data = parse_project_audio_config(project.audio_config or "")
    saved_engines_raw = saved_data.get("engines")
    saved_engines = None
    if isinstance(saved_engines_raw, dict):
        saved_engines = saved_engines_raw

    return ProjectAudioConfig(
        characters=characters,
        audio_fx=config.audio_fx,
        audio_engine_mode=resolved_mode,
        seed_audio_model=get_seed_audio_model(data),
        engines=saved_engines,
    )


@router.get("/{project_id}/review-config", response_model=ReviewConfigResponse)
async def get_project_review_config(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewConfigResponse:
    """获取项目级评审高级功能配置。"""
    project = _get_owned_project(db, project_id, current_user)
    return _review_config_response(_load_review_config(project.review_config))


@router.put("/{project_id}/review-config", response_model=ReviewConfigResponse)
async def update_project_review_config(
    project_id: int,
    config: ReviewConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReviewConfigResponse:
    """更新项目级评审高级功能配置。"""
    project = _get_owned_project(db, project_id, current_user)
    incoming = config.multi_model_review

    data = _load_review_config(project.review_config)
    data["multi_model_review"] = incoming.model_dump(exclude_none=True)
    project.review_config = json.dumps(data, ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    return _review_config_response(data)


@router.post("/{project_id}/audio-config/auto-voices", response_model=ProjectAudioConfig)
async def auto_assign_project_audio_voices(
    project_id: int,
    tts_model: str = Query("qwen3-tts-instruct-flash"),
    chapter_ids: Optional[List[int]] = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectAudioConfig:
    """基于结构化人物档案自动为项目生成推荐声线配置。

    规则：
    - 已有且未标记为 ai_suggest 的角色配置视为用户手动配置，保留不动。
    - 对于缺少配置或来源为 ai_suggest 的角色，根据 Character 信息调用 VoiceManager 分配音色。
    - 保留现有的 audio_fx 配置。
    """
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # 解析现有 audio_config
    data = parse_project_audio_config(project.audio_config or "")
    resolved_mode = resolve_engine_mode(data)
    existing_characters = get_characters_for_model(data, tts_model, engine_mode=resolved_mode)
    audio_fx = get_audio_fx(data, engine_mode=resolved_mode)

    # 载入项目角色，并按本次所选章节收敛推荐范围。
    characters = (
        db.query(Character)
        .filter(
            Character.project_id == project_id,
            Character.archived_at.is_(None),
        )
        .order_by(Character.id)
        .all()
    )
    scoped_character_ids = None
    if chapter_ids:
        normalized_chapter_ids = list(dict.fromkeys(chapter_ids))
        selected_chapters = (
            db.query(Chapter)
            .filter(
                Chapter.project_id == project_id,
                Chapter.id.in_(normalized_chapter_ids),
                Chapter.deleted_at.is_(None),
            )
            .all()
        )
        if len(selected_chapters) != len(normalized_chapter_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="部分章节不存在",
            )
        characters, scope = select_chapter_characters(
            chapters=selected_chapters,
            characters=characters,
        )
        scoped_character_ids = {item.character_id for item in scope.characters}

    # 建立已有配置索引
    manual_configs_by_id = {}
    ai_configs_by_id = {}
    other_entries = []
    preserved_out_of_scope_entries = []

    for item in existing_characters:
        if not isinstance(item, dict):
            continue
        cid = item.get("character_id")
        if scoped_character_ids is not None and cid not in scoped_character_ids:
            preserved_out_of_scope_entries.append(item)
            continue
        source = item.get("source")
        # 旁白或未知 ID 的条目直接保留
        if cid is None or cid == 0:
            other_entries.append(item)
            continue
        if source == "user":
            manual_configs_by_id[cid] = item
        else:
            ai_configs_by_id[cid] = item

    llm_client = None
    try:
        from core.unified_llm_client import get_llm_client

        llm_client = get_llm_client(strategy="conservative")
        logger.info(f"✅ LLM 客户端初始化成功，将为角色声线推荐提供智能分析")
    except Exception as e:
        logger.warning(f"⚠️ LLM 客户端初始化失败：{e}，将使用规则推断模式")
        llm_client = None

    auto_voice_pool = AutoVoiceAssignmentPool(
        preferred_model=tts_model,
        llm_client=llm_client,
        existing_assignments=[*manual_configs_by_id.values(), *other_entries],
    )
    logger.info(
        "🎙️ 自动声线推荐池初始化完成，候选模型=%s，LLM 支持=%s",
        auto_voice_pool.model_order,
        "启用" if llm_client else "禁用",
    )
    result_characters = []

    # 先保留范围外已有配置，再放入本次范围内的“其他”条目（如旁白）。
    result_characters.extend(preserved_out_of_scope_entries)
    result_characters.extend(other_entries)

    def _normalize_text(value: Optional[str]) -> str:
        return str(value).strip() if value else ""

    def _parse_tags(raw: Optional[str]) -> List[str]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
            if isinstance(data, dict):
                values: List[str] = []
                for item in data.values():
                    if isinstance(item, list):
                        values.extend([str(v).strip() for v in item if str(v).strip()])
                    elif item is not None:
                        values.append(str(item).strip())
                return [v for v in values if v]
        except Exception:
            pass
        return [part for part in re.split(r"[，,;/|\\s]+", raw) if part]

    def _infer_gender(char: Character, text_lower: str) -> str:
        gender_raw = _normalize_text(char.gender).lower()
        if gender_raw in ("男", "male", "m", "man", "boy"):
            return "male"
        if gender_raw in ("女", "female", "f", "woman", "girl"):
            return "female"

        female_keywords = (
            "女", "女性", "女人", "女孩", "少女", "小姐", "夫人", "太太", "公主", "王后",
            "女主", "姐姐", "妹妹", "阿姨", "奶奶", "婆婆", "她",
            "female", "woman", "girl", "miss", "queen", "princess",
        )
        male_keywords = (
            "男", "男性", "男人", "男孩", "少年", "先生", "少爷", "公子", "王子",
            "男主", "哥哥", "弟弟", "大叔", "爷爷", "他",
            "male", "man", "boy", "sir", "king", "prince",
        )
        female_hit = any(k in text_lower for k in female_keywords)
        male_hit = any(k in text_lower for k in male_keywords)
        if female_hit ^ male_hit:
            return "female" if female_hit else "male"

        name = _normalize_text(char.name)
        female_chars = (
            "娜", "婷", "芝", "霞", "雪", "梅", "芳", "琳", "雯", "瑜",
            "娥", "妮", "蕾", "莉", "慧", "敏", "静", "涵", "娟", "珊",
            "洁", "雅", "怡",
        )
        male_chars = (
            "昊", "浩", "强", "伟", "军", "明", "建", "凌", "龙", "杰",
            "博", "宇", "峰", "辉", "宏", "俊", "瑞",
        )
        if name.endswith(female_chars):
            return "female"
        if name.endswith(male_chars):
            return "male"
        return "unknown"

    def _infer_age_group(char: Character, text_lower: str) -> Optional[str]:
        if char.age is not None:
            age = char.age
            if age < 12:
                return "child"
            if age < 18:
                return "teen"
            if age < 30:
                return "young"
            if age < 60:
                return "adult"
            return "elder"

        elder_keywords = ("老者", "老人", "老头", "老伯", "老太", "老奶", "爷爷", "奶奶", "婆婆", "大爷")
        child_keywords = ("儿童", "孩童", "幼童", "小孩", "娃娃", "宝宝", "孩子")
        teen_keywords = ("少年", "少女", "青少年", "学生", "高中生")
        young_keywords = ("青年", "年轻", "小伙", "小哥", "小妹", "姑娘", "小姐", "少侠")
        adult_keywords = ("中年", "成熟", "大叔", "大姐", "少妇", "壮年")

        if any(k in text_lower for k in elder_keywords):
            return "elder"
        if any(k in text_lower for k in child_keywords):
            return "child"
        if any(k in text_lower for k in teen_keywords):
            return "teen"
        if any(k in text_lower for k in young_keywords):
            return "young"
        if any(k in text_lower for k in adult_keywords):
            return "adult"
        return None

    def _infer_personality(text_lower: str) -> Optional[str]:
        personality_map = [
            ("serious", ("严肃", "威严", "刚毅", "果断", "冷酷", "强势", "霸道", "冷峻", "阴沉", "狠辣", "威猛")),
            ("gentle", ("温柔", "温顺", "善良", "柔和", "恬静", "乖巧", "甜美", "亲切", "软萌", "可爱")),
            ("energetic", ("活泼", "开朗", "阳光", "热血", "冲动", "豪爽", "外向", "爽朗", "元气", "俏皮", "顽皮")),
            ("calm", ("冷静", "沉稳", "稳重", "理性", "内敛", "淡定", "谨慎", "沉着", "克制")),
        ]
        for personality, keywords in personality_map:
            if any(k in text_lower for k in keywords):
                return personality
        return None

    def _build_traits_from_character(char: Character) -> dict:
        """从角色信息中构建特征字典，优先使用结构化字段"""
        tags = _parse_tags(char.tags)
        role = _normalize_text(char.role)
        role_position = _normalize_text(getattr(char, "role_position", None))
        importance = _normalize_text(char.importance_level)
        summary = _normalize_text(char.summary)
        profile = _normalize_text(char.profile)
        faction = _normalize_text(char.faction)

        # 构建完整的上下文文本（用于 LLM 分析和关键词匹配）
        text_parts = [char.name, role, role_position, importance, summary, profile, faction, " ".join(tags)]
        text = " ".join([_normalize_text(p) for p in text_parts if _normalize_text(p)])
        text_lower = text.lower()

        traits: dict = {}
        
        # 1. 优先使用结构化字段
        gender_raw = _normalize_text(char.gender).lower()
        if gender_raw in ("男", "male", "m", "man", "boy"):
            traits["gender"] = "male"
        elif gender_raw in ("女", "female", "f", "woman", "girl"):
            traits["gender"] = "female"
        else:
            # 使用关键词推断
            traits["gender"] = _infer_gender(char, text_lower)
        
        # 2. 优先使用年龄字段
        if char.age is not None:
            age = char.age
            if age < 12:
                traits["age_group"] = "child"
            elif age < 18:
                traits["age_group"] = "teen"
            elif age < 30:
                traits["age_group"] = "young"
            elif age < 60:
                traits["age_group"] = "adult"
            else:
                traits["age_group"] = "elder"
        else:
            age_group = _infer_age_group(char, text_lower)
            traits["age_group"] = age_group or "unknown"
        
        # 3. 性格推断：优先从 profile/summary 中提取
        personality = _infer_personality(text_lower)
        if not personality:
            # 从角色重要性推断
            if "主角" in importance or "核心" in importance or role_position == "主角":
                personality = "energetic"
            elif any(keyword in importance for keyword in ("边缘", "群众", "次要")):
                personality = "calm"
        if personality:
            traits["personality"] = personality
        
        # 4. 构建详细的上下文信息（用于 LLM 分析）
        context_parts = []
        if role:
            context_parts.append(f"故事立场：{role}")
        if role_position:
            context_parts.append(f"角色定位：{role_position}")
        if importance:
            context_parts.append(f"重要程度：{importance}")
        if summary:
            context_parts.append(f"角色简介：{summary}")
        if profile:
            context_parts.append(f"详细设定：{profile}")
        if faction:
            context_parts.append(f"所属势力：{faction}")
        if tags:
            context_parts.append(f"标签：{', '.join(tags)}")
        
        if context_parts:
            traits["context"] = "；".join(context_parts)
        
        logger.debug(f"📊 角色 '{char.name}' 特征分析结果：{traits}")
        
        return traits

    for char in characters:
        existing_manual = manual_configs_by_id.get(char.id)
        if existing_manual and existing_manual.get("voice_id"):
            # 用户手动配置优先，直接保留
            logger.info(f"✅ 角色 '{char.name}' 已有手动配置，跳过智能推荐")
            result_characters.append(existing_manual)
            continue

        logger.info(f"🔍 开始为角色 '{char.name}' 进行智能声线分析...")
        traits = _build_traits_from_character(char)
        logger.info(f"📊 角色 '{char.name}' 特征：{traits}")
        
        # 如果有 LLM 客户端，记录 LLM 调用状态
        if llm_client:
            logger.info(f"🤖 将使用 LLM 进行智能特征分析")
        else:
            logger.info(f"📖 将使用规则推断模式")
        
        assignment = auto_voice_pool.assign(char.name, traits or None)
        profile = assignment.profile
        
        logger.info(
            "🎤 角色 '%s' 分配音色: %s (model=%s, reused_voice_id=%s)",
            char.name,
            profile.voice_id,
            assignment.model,
            assignment.reused_voice_id,
        )

        result_characters.append(
            {
                "character_id": char.id,
                "name": char.name,
                "voice_id": profile.voice_id,
                "tts_model": assignment.model,
                "source": "ai_suggest",
            }
        )

    # 更新并保存配置
    new_config = {
        "characters": result_characters,
        "audio_fx": audio_fx,
    }
    project.audio_config = json.dumps(new_config, ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    set_characters_for_model(data, tts_model, result_characters, engine_mode=resolved_mode)
    set_audio_fx(data, audio_fx, engine_mode=resolved_mode)
    project.audio_config = json.dumps(data, ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    # 重新读回已保存的分支数据用于响应
    saved_data = parse_project_audio_config(project.audio_config or "")
    saved_engines_raw = saved_data.get("engines")
    saved_engines = None
    if isinstance(saved_engines_raw, dict):
        saved_engines = saved_engines_raw

    return ProjectAudioConfig(
        characters=result_characters,
        audio_fx=audio_fx,
        audio_engine_mode=resolved_mode,
        seed_audio_model=get_seed_audio_model(data),
        engines=saved_engines,
    )


@router.get("/{project_id}/audio-config/engine-preferences", response_model=EnginePreferencesResponse)
async def get_project_audio_engine_preferences(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EnginePreferencesResponse:
    """获取当前引擎的创作偏好。

    - seed_scene 返回 scene_generation_preferences
    - legacy_stems 返回 audio_fx
    """
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    data = parse_project_audio_config(project.audio_config or "")
    resolved_mode = resolve_engine_mode(data)

    scene_prefs = None
    audio_fx = None

    if resolved_mode == "seed_scene":
        raw_prefs = get_scene_generation_preferences(data, resolved_mode)
        if raw_prefs:
            scene_prefs = SceneGenerationPreferences(**raw_prefs)
    else:
        raw_fx = get_audio_fx(data, engine_mode=resolved_mode)
        if raw_fx:
            audio_fx = AudioFxConfig(**raw_fx)

    return EnginePreferencesResponse(
        engine_mode=resolved_mode,
        scene_generation_preferences=scene_prefs,
        audio_fx=audio_fx,
    )


# 章节路由
@router.get("/{project_id}/chapters", response_model=List[ChapterResponse])
async def list_chapters(
    project_id: int,
    sort_order: str = Query("asc", description="排序方式: asc(正序) 或 desc(倒序)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的所有章节"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 根据排序参数查询章节
    query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if sort_order == "desc":
        chapters = query.order_by(Chapter.chapter_number.desc()).all()
    else:
        chapters = query.order_by(Chapter.chapter_number.asc()).all()

    return chapters


@router.post("/{project_id}/chapters", response_model=ChapterResponse)
async def create_chapter(
    project_id: int,
    chapter_data: ChapterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新章节"""
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    chapter = Chapter(
        project_id=project_id,
        chapter_number=chapter_data.chapter_number,
        title=chapter_data.title,
        content=chapter_data.content,
        word_count=len(chapter_data.content.split()) if chapter_data.content else 0
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


# ===========================
# 导出 API 端点
# ===========================

@router.get("/{project_id}/export/all/txt")
async def export_all_chapters_txt(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """一键导出所有章节为TXT格式（UTF-8编码）"""
    from fastapi.responses import Response
    from urllib.parse import quote
    
    # 验证项目存在且属于当前用户
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 获取所有章节，按章节号正序排列
    chapters = db.query(Chapter).filter(
        Chapter.project_id == project_id
    ).order_by(Chapter.chapter_number.asc()).all()
    
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chapters found in this project"
        )
    
    # 生成TXT内容
    content_parts = [
        f"《{project.title}》\n",
        f"\n{'=' * 50}\n\n"
    ]
    
    total_words = 0
    for chapter in chapters:
        content_parts.append(f"{chapter.title}\n")
        content_parts.append(f"\n{chapter.content or ''}\n")
        content_parts.append(f"\n{'=' * 50}\n\n")
        total_words += chapter.word_count or 0
    
    # 添加统计信息
    content_parts.append(f"\n\n共 {len(chapters)} 章，约 {total_words} 字\n")
    
    content = "".join(content_parts)
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{project.title}_全文.txt")
    
    return Response(
        content=content.encode('utf-8'),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )


@router.get("/{project_id}/export/all/docx")
async def export_all_chapters_docx(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """一键导出所有章节为DOCX格式（专业排版）"""
    from fastapi.responses import StreamingResponse
    from urllib.parse import quote
    from io import BytesIO
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
    
    # 验证项目存在且属于当前用户
    project = db.query(Project).filter(
        (Project.id == project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 获取所有章节，按章节号正序排列
    chapters = db.query(Chapter).filter(
        Chapter.project_id == project_id
    ).order_by(Chapter.chapter_number.asc()).all()
    
    if not chapters:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chapters found in this project"
        )
    
    # 创建DOCX文档
    doc = Document()
    
    # 添加书名标题（居中、加粗、22磅）
    book_title = doc.add_paragraph(f"《{project.title}》")
    book_title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    book_title_run = book_title.runs[0]
    book_title_run.bold = True
    book_title_run.font.size = Pt(22)
    
    # 添加空行
    doc.add_paragraph()
    doc.add_paragraph()
    
    total_words = 0
    for i, chapter in enumerate(chapters):
        # 添加章节标题（居中、加粗、16磅）
        chapter_title = doc.add_paragraph(chapter.title)
        chapter_title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        chapter_title_run = chapter_title.runs[0]
        chapter_title_run.bold = True
        chapter_title_run.font.size = Pt(16)
        
        # 添加空行
        doc.add_paragraph()
        
        # 添加正文（按段落分割）
        if chapter.content:
            paragraphs = chapter.content.split('\n')
            for para_text in paragraphs:
                if para_text.strip():
                    para = doc.add_paragraph(para_text.strip())
                    # 设置正文格式：首行缩进2字符
                    para.paragraph_format.first_line_indent = Inches(0.5)
        
        total_words += chapter.word_count or 0
        
        # 如果不是最后一章，添加分隔
        if i < len(chapters) - 1:
            doc.add_paragraph()
            separator = doc.add_paragraph('\u2500' * 30)  # ─── 分隔线
            separator.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            doc.add_paragraph()
    
    # 添加统计信息
    doc.add_paragraph()
    doc.add_paragraph()
    stats = doc.add_paragraph(f"共 {len(chapters)} 章，约 {total_words} 字")
    stats.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    
    # 将文档保存到BytesIO
    docx_io = BytesIO()
    doc.save(docx_io)
    docx_io.seek(0)
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{project.title}_全文.docx")
    
    return StreamingResponse(
        docx_io,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )
