"""
项目API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import json
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.character import Character
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse,
    ChapterCreate, ChapterUpdate, ChapterResponse
)
from app.core.security import get_current_user
from app.services.audiobook.voice_manager import VoiceManager


class CharacterAudioConfig(BaseModel):
    """单个角色的音频配置"""
    character_id: int
    name: str
    voice_id: str
    volume: int = 50
    speed: Optional[float] = None
    pitch: Optional[int] = None
    source: Optional[str] = None  # "user" | "ai_suggest" | None


class AudioFxConfig(BaseModel):
    """项目级音效与配乐配置"""
    enable_sound_effects: bool = True
    enable_music: bool = True
    sound_effect_density: str = "medium"  # low/medium/high/off
    music_density: str = "medium"  # low/medium/high/off


class ProjectAudioConfig(BaseModel):
    """项目级音频配置"""
    characters: List[CharacterAudioConfig] = []
    audio_fx: Optional[AudioFxConfig] = None


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=List[ProjectResponse])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取用户的所有项目"""
    projects = db.query(Project).filter(Project.user_id == current_user.id).all()
    return projects


@router.post("", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新项目"""
    project = Project(
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


@router.get("/{project_id}/audio-config", response_model=ProjectAudioConfig)
async def get_project_audio_config(
    project_id: int,
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

    raw = project.audio_config or ""
    data: dict = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

    characters = data.get("characters") or []
    audio_fx = data.get("audio_fx") or None
    # 让 Pydantic 处理具体字段校验
    return ProjectAudioConfig(characters=characters, audio_fx=audio_fx)


@router.put("/{project_id}/audio-config", response_model=ProjectAudioConfig)
async def update_project_audio_config(
    project_id: int,
    config: ProjectAudioConfig,
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

    project.audio_config = json.dumps(config.dict(), ensure_ascii=False)
    db.add(project)
    db.commit()
    db.refresh(project)

    return config


@router.post("/{project_id}/audio-config/auto-voices", response_model=ProjectAudioConfig)
async def auto_assign_project_audio_voices(
    project_id: int,
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
    raw = project.audio_config or ""
    data: dict = {}
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

    existing_characters = data.get("characters") or []
    audio_fx = data.get("audio_fx") or None

    # 建立已有配置索引
    manual_configs_by_id = {}
    ai_configs_by_id = {}
    other_entries = []

    for item in existing_characters:
        if not isinstance(item, dict):
            continue
        cid = item.get("character_id")
        source = item.get("source")
        # 旁白或未知 ID 的条目直接保留
        if cid is None or cid == 0:
            other_entries.append(item)
            continue
        if source == "ai_suggest":
            ai_configs_by_id[cid] = item
        else:
            manual_configs_by_id[cid] = item

    # 载入项目角色
    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .order_by(Character.id)
        .all()
    )

    vm = VoiceManager()
    result_characters = []

    # 先放入“其他”条目（如旁白）
    result_characters.extend(other_entries)

    def _build_traits_from_character(char: Character) -> dict:
        traits: dict = {}
        gender = (char.gender or "").strip().lower()
        if gender in ("男", "male", "m", "man", "boy"):
            traits["gender"] = "male"
        elif gender in ("女", "female", "f", "woman", "girl"):
            traits["gender"] = "female"

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

        # 简单用重要程度影响性格倾向
        importance = (char.importance_level or "").strip()
        if importance:
            if "主角" in importance or "重要" in importance:
                traits.setdefault("personality", "energetic")
            elif "龙套" in importance or "群众" in importance:
                traits.setdefault("personality", "calm")

        return traits

    for char in characters:
        existing_manual = manual_configs_by_id.get(char.id)
        if existing_manual and existing_manual.get("voice_id"):
            # 用户手动配置优先，直接保留
            result_characters.append(existing_manual)
            continue

        traits = _build_traits_from_character(char)
        profile = vm.assign_voice(char.name, character_info=traits or None)

        result_characters.append(
            {
                "character_id": char.id,
                "name": char.name,
                "voice_id": profile.voice_id,
                "volume": profile.volume_base,
                "speed": profile.speed_base,
                "pitch": profile.pitch_base,
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

    return ProjectAudioConfig(characters=result_characters, audio_fx=audio_fx)


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

