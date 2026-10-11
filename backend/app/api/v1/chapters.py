"""
章节API路由
"""
from typing import cast, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter, ChapterRevision
from app.schemas.project import ChapterUpdate, ChapterResponse, ChapterCreate, ChapterRevisionResponse
from app.core.security import get_current_user
from app.utils.datetime_utils import ensure_utc_datetime, utc_now
from app.services.chapter_creation import create_project_chapter
import re
from io import BytesIO
from datetime import datetime
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

router = APIRouter(prefix="/api/v1/chapters", tags=["chapters"])


def _serialize_deleted_chapter(chapter: Chapter, project_name: Optional[str] = None) -> dict:
    """将已删除章节转换为前端可直接消费的稳定结构。"""
    return {
        "id": chapter.id,
        "project_id": chapter.project_id,
        "project_name": project_name,
        "chapter_number": chapter.chapter_number,
        "title": chapter.title,
        "content": chapter.content or "",
        "word_count": chapter.word_count or 0,
        "created_at": chapter.created_at.isoformat() if chapter.created_at else None,
        "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
        "deleted_at": chapter.deleted_at.isoformat() if chapter.deleted_at else None,
        "status": chapter.status,
    }


@router.post("/", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
async def create_chapter(
    chapter_data: ChapterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建章节"""
    # 验证项目存在且属于当前用户
    project = db.query(Project).filter(
        (Project.id == chapter_data.project_id) & (Project.user_id == current_user.id)
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 与 POST /api/v1/projects/{id}/chapters 共用同一套创建逻辑
    return create_project_chapter(
        db,
        chapter_data.project_id,
        content=chapter_data.content,
        chapter_number=chapter_data.chapter_number,
        title=chapter_data.title,
    )


@router.get("/{chapter_id:int}", response_model=ChapterResponse)
async def get_chapter(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取章节详情"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    return chapter


@router.put("/{chapter_id:int}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: int,
    chapter_data: ChapterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 更新字段
    content_updated = False
    old_content = ""  # 🆕 保存修改前的内容
    
    if chapter_data.title is not None:
        chapter.title = cast(str, chapter_data.title)  # type: ignore[assignment]
    if chapter_data.content is not None:
        # 🆕 保存前先创建版本快照
        if chapter.content and chapter.content != chapter_data.content:
            old_content = chapter.content  # 🆕 记录旧内容
            revision = ChapterRevision(
                chapter_id=chapter_id,
                content=chapter.content,
                word_count=chapter.word_count,
                revision_note="手动保存前的版本",
                created_by=current_user.id
            )
            db.add(revision)
            content_updated = True

        chapter.content = cast(str, chapter_data.content)  # type: ignore[assignment]
        # 🔧 修复：使用正确的中文字数统计
        import re
        chapter.word_count = len(re.sub(r'\s', '', chapter_data.content))  # type: ignore[assignment]
    if chapter_data.status is not None:
        chapter.status = cast(str, chapter_data.status)  # type: ignore[assignment]

    db.add(chapter)
    db.commit()
    db.refresh(chapter)

    # 🆕 Phase 2: 智能差异检测 - 自动追踪人物/设定关联
    if content_updated:
        try:
            from app.services.auto_tracking import AutoTrackingService
            import logging
            
            logger = logging.getLogger("uvicorn.error")
            logger.info(f"   🔄 检测章节内容变化并更新追踪...")
            
            # 1. 人物出场智能更新
            char_result = AutoTrackingService.update_character_appearances_smart(
                chapter_id=chapter_id,
                old_content=old_content,  # 即使为空字符串也可以触发初始追踪
                new_content=chapter_data.content,
                project_id=chapter.project_id,
                db=db
            )
            logger.info(
                f"   ✅ 人物追踪: 新增{char_result['added']}个, "
                f"移除{char_result['removed']}个, "
                f"未变{char_result['unchanged']}个"
            )
            
            # 2. 设定项引用智能更新
            setting_result = AutoTrackingService.update_setting_references_smart(
                chapter_id=chapter_id,
                old_content=old_content,  # 即使为空字符串也可以触发初始追踪
                new_content=chapter_data.content,
                project_id=chapter.project_id,
                db=db
            )
            logger.info(
                f"   ✅ 设定追踪: 新增{setting_result['added']}个, "
                f"移除{setting_result['removed']}个, "
                f"未变{setting_result['unchanged']}个"
            )
            
            # 3. 🆕 高级关联追踪
            relation_result = AutoTrackingService.update_character_item_relations(
                chapter_id=chapter_id,
                chapter_content=chapter_data.content,
                project_id=chapter.project_id,
                db=db
            )
            logger.info(
                f"   ✅ 高级关联: 功法{relation_result['techniques']}个, "
                f"法宝{relation_result['artifacts']}个, "
                f"地点{relation_result['locations']}个"
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.warning(f"⚠️ 智能追踪失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    # 🚀 Phase 5: 启动后台任务（统一提取 + 摘要生成）
    if content_updated and chapter_data.content:
        try:
            from app.services.chapter_post_save import start_chapter_post_save_task
            import logging
            
            logger = logging.getLogger("uvicorn.error")
            logger.info(f"   🚀 启动后台任务：统一提取 + 摘要生成...")
            
            # 启动后台异步任务
            start_chapter_post_save_task(
                chapter_id=chapter.id,
                chapter_title=chapter.title,
                chapter_content=chapter_data.content,
                chapter_number=chapter.chapter_number,
                project_id=chapter.project_id,
                generate_summary=True
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.warning(f"⚠️ 启动后台任务失败（不影响章节更新）: {e}")

    # 🆕 同步更新向量库
    if content_updated:
        try:
            from app.services.agents.knowledge_base import NovelKnowledgeBase
            from app.services.vector_sync import sync_to_vector_db
            import logging

            logger = logging.getLogger("uvicorn.error")
            logger.info(f"   🔄 同步更新向量库中的章节数据...")

            # 先删除旧的向量数据
            kb = NovelKnowledgeBase()
            deleted_count = kb.delete_chapter(
                chapter_number=chapter.chapter_number,
                project_id=chapter.project_id
            )

            if deleted_count > 0:
                logger.info(f"   ✅ 已删除旧版本 {deleted_count} 个文档")

            # 添加新的向量数据
            sync_to_vector_db(
                kb_type="chapter",
                name=f"第{chapter.chapter_number}章 {chapter.title}",
                content=chapter.content,
                metadata={
                    "project_id": str(chapter.project_id),
                    "chapter_number": str(chapter.chapter_number)
                }
            )

            logger.info(f"   ✅ 已同步新版本到向量库")

        except Exception as e:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.warning(f"⚠️ 更新章节时同步向量库失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    # 🆕 内容进化器：收集编辑量反馈（用户保存时统计修改比例）
    if content_updated and old_content and chapter_data.content:
        try:
            from app.services.content_evolution import get_engine
            import logging
            
            logger = logging.getLogger("uvicorn.error")
            evolution_engine = get_engine()
            edit_ratio = await evolution_engine.on_chapter_save(
                chapter_id=chapter.id,
                original_content=old_content,
                final_content=chapter_data.content,
            )
            if edit_ratio is not None:
                logger.debug(f"   📊 内容进化器：编辑比例 {edit_ratio:.2%}")
        except Exception as evo_err:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.debug(f"   ⚠️ 内容进化器反馈收集失败（不影响主流程）: {evo_err}")

    # 🎉 Phase 6: 触发体系自动检测（异步后台执行，不阻塞）
    if content_updated and chapter_data.content:
        try:
            from app.api.v1.workflow import trigger_auto_system_detection
            import asyncio
            import logging
            
            logger = logging.getLogger("uvicorn.error")
            logger.info(f"   🎉 触发体系自动检测（章节 {chapter.chapter_number}）...")
            
            # 异步后台执行，不阻塞主流程
            asyncio.create_task(
                trigger_auto_system_detection(
                    project_id=chapter.project_id,
                    content=chapter_data.content,
                    content_type="chapter",
                    db=db
                )
            )
            
        except Exception as e:
            import logging
            logger = logging.getLogger("uvicorn.error")
            logger.warning(f"⚠️ 触发体系检测失败（不影响章节更新）: {e}")

    return chapter


@router.delete("/{chapter_id:int}")
async def delete_chapter(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 🆕 清理记忆数据：如果某个记忆的 current_chapter 指向被删除的章节，将其置为 NULL
    from app.models.memory import Memory
    db.query(Memory).filter(
        (Memory.project_id == chapter.project_id) &
        (Memory.current_chapter == chapter.chapter_number)
    ).update({Memory.current_chapter: None})

    # 🆕 清理Character表的追踪数据
    try:
        from app.models.character import Character
        import json
        import logging
        logger = logging.getLogger("uvicorn.error")
        
        logger.info(f"   🧹 清理人物追踪数据...")
        
        # 获取该项目的所有人物
        characters = db.query(Character).filter(
            Character.project_id == chapter.project_id
        ).all()
        
        cleaned_characters = 0
        for character in characters:
            updated = False
            
            # 清理 appearance_chapters
            if character.appearance_chapters:
                appearance_chapters = json.loads(character.appearance_chapters)
                if chapter.id in appearance_chapters:
                    appearance_chapters.remove(chapter.id)
                    character.appearance_chapters = json.dumps(appearance_chapters)
                    updated = True
                    
                    # 重新计算 first_mention_chapter_id 和 last_appearance_chapter_id
                    if appearance_chapters:
                        character.first_mention_chapter_id = min(appearance_chapters)
                        character.last_appearance_chapter_id = max(appearance_chapters)
                    else:
                        character.first_mention_chapter_id = None
                        character.last_appearance_chapter_id = None
            
            # 清理外键字段
            if character.first_mention_chapter_id == chapter.id:
                character.first_mention_chapter_id = None
                updated = True
            
            if character.last_appearance_chapter_id == chapter.id:
                character.last_appearance_chapter_id = None
                updated = True
            
            if updated:
                cleaned_characters += 1
        
        if cleaned_characters > 0:
            db.commit()
            logger.info(f"   ✅ 已清理 {cleaned_characters} 个人物的追踪数据")
        else:
            logger.info(f"   ℹ️  无需清理人物追踪数据")
    
    except Exception as e:
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 清理人物追踪数据失败（不影响删除）: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        db.rollback()
    
    # 🆕 清理SettingItem表的追踪数据
    try:
        from app.models.setting import SettingItem
        import json
        import logging
        logger = logging.getLogger("uvicorn.error")
        
        logger.info(f"   🧹 清理设定追踪数据...")
        
        # 获取该项目的所有设定项
        from app.models.setting import SettingCollection
        setting_items = db.query(SettingItem).join(
            SettingCollection
        ).filter(
            SettingCollection.project_id == chapter.project_id
        ).all()
        
        cleaned_settings = 0
        for setting_item in setting_items:
            if setting_item.referenced_chapters:
                referenced_chapters = json.loads(setting_item.referenced_chapters)
                if chapter.id in referenced_chapters:
                    referenced_chapters.remove(chapter.id)
                    setting_item.referenced_chapters = json.dumps(referenced_chapters)
                    # 🆕 增量 -1（不为负）而非 len() 重算：保留 DreamWeaver 等
                    # 非章节来源写入的 usage_count（修复 P3-1 计数脱节）
                    setting_item.usage_count = max(0, (setting_item.usage_count or 1) - 1)
                    # last_referenced_at 保持不变（保留最后一次真实引用时间）
                    cleaned_settings += 1
        
        if cleaned_settings > 0:
            db.commit()
            logger.info(f"   ✅ 已清理 {cleaned_settings} 个设定项的追踪数据")
        else:
            logger.info(f"   ℹ️  无需清理设定追踪数据")
    
    except Exception as e:
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 清理设定追踪数据失败（不影响删除）: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        db.rollback()
    
    # 🆕 清理KnowledgeGraphEdge表（可选）
    try:
        from app.models.graph import KnowledgeGraphEdge
        import logging
        logger = logging.getLogger("uvicorn.error")
        
        logger.info(f"   🧹 清理知识图谱关系...")
        
        # 注意：这里只是记录，因为关系边本身不直接存储章节ID
        # 如果未来需要追踪关系的来源章节，可以在这里添加逻辑
        logger.info(f"   ℹ️  知识图谱关系不直接关联章节，跳过")
    
    except Exception as e:
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 检查知识图谱失败（不影响删除）: {e}")

    # 🆕 同步删除向量库中的相关向量数据
    try:
        from app.services.agents.knowledge_base import NovelKnowledgeBase
        import logging
        logger = logging.getLogger("uvicorn.error")

        logger.info(f"   🗑️  同步删除向量库中的章节数据...")

        # 使用知识库的删除方法
        kb = NovelKnowledgeBase()
        deleted_count = kb.delete_chapter(
            chapter_number=chapter.chapter_number,
            project_id=chapter.project_id
        )

        if deleted_count > 0:
            logger.info(f"   ✅ 已从向量库删除 {deleted_count} 个文档")
        else:
            logger.info(f"   ℹ️  向量库中未找到第{chapter.chapter_number}章的数据")

    except Exception as e:
        # 不中断主流程，记录错误
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.warning(f"⚠️ 删除章节时清理向量库失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    
    # 🆕 内容进化器：收集保留率反馈（章节被删除 = 不满意）
    try:
        from app.services.content_evolution import get_engine
        import logging

        logger = logging.getLogger("uvicorn.error")
        evolution_engine = get_engine()
        await evolution_engine.on_chapter_delete(chapter_id=chapter.id)
        logger.debug(f"   📊 内容进化器：已记录删除反馈")
    except Exception as evo_err:
        import logging
        logger = logging.getLogger("uvicorn.error")
        logger.debug(f"   ⚠️ 内容进化器反馈收集失败（不影响主流程）: {evo_err}")

    # 彻底删除章节（级联删除版本历史）
    db.delete(chapter)
    db.commit()

    return {
        "message": "Chapter deleted successfully",
        "chapter_id": chapter.id,
        "chapter_number": chapter.chapter_number
    }


@router.post("/{chapter_id:int}/restore")
async def restore_chapter(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """恢复已删除的章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查章节是否已被删除
    if chapter.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chapter is not deleted"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 恢复章节（清除deleted_at字段）
    chapter.deleted_at = None
    db.commit()
    db.refresh(chapter)
    
    return {
        "message": "Chapter restored successfully",
        "chapter_id": chapter.id,
        "chapter_number": chapter.chapter_number,
        "restored_at": datetime.now()
    }


@router.get("/deleted")
async def get_deleted_chapters(
    project_id: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取已删除章节列表，支持按项目查询或跨项目聚合。"""
    if project_id <= 0:
        rows = (
            db.query(Chapter, Project.title)
            .join(Project, Project.id == Chapter.project_id)
            .filter(
                Project.user_id == current_user.id,
                Chapter.deleted_at.isnot(None),
            )
            .order_by(Chapter.deleted_at.desc())
            .all()
        )

        deleted_chapters = [
            _serialize_deleted_chapter(chapter, project_name)
            for chapter, project_name in rows
        ]

        return {
            "project_id": None,
            "deleted_chapters": deleted_chapters,
            "count": len(deleted_chapters)
        }

    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    chapters = db.query(Chapter).filter(
        (Chapter.project_id == project_id) &
        (Chapter.deleted_at.isnot(None))
    ).order_by(Chapter.deleted_at.desc()).all()

    deleted_chapters = [
        _serialize_deleted_chapter(chapter, project.title)
        for chapter in chapters
    ]

    return {
        "project_id": project_id,
        "deleted_chapters": deleted_chapters,
        "count": len(deleted_chapters)
    }


@router.post("/{chapter_id:int}/auto-save")
async def auto_save_chapter(
    chapter_id: int,
    chapter_data: ChapterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """自动保存章节"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 检查权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated project not found"
        )
    
    # 类型断言：在此时project已经确认不为None
    project_user_id: int = cast(int, project.user_id)
    current_user_id: int = cast(int, current_user.id)
    
    if project_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 更新内容
    if chapter_data.content is not None:
        # 🆕 自动保存时也创建版本快照（但频率较低，每5分钟最多1次）
        from datetime import timedelta
        should_create_revision = True
        
        # 检查最近的版本是否在5分钟内
        latest_revision = db.query(ChapterRevision).filter(
            ChapterRevision.chapter_id == chapter_id
        ).order_by(ChapterRevision.created_at.desc()).first()
        
        if latest_revision and latest_revision.created_at:
            latest_revision_at = ensure_utc_datetime(latest_revision.created_at)
            if latest_revision_at and utc_now() - latest_revision_at < timedelta(minutes=5):
                should_create_revision = False
        
        # 如果内容变化且距离上次版本超过5分钟，创建版本
        if should_create_revision and chapter.content and chapter.content != chapter_data.content:
            revision = ChapterRevision(
                chapter_id=chapter_id,
                content=chapter.content,
                word_count=chapter.word_count,
                revision_note="自动保存的版本",
                created_by=current_user.id
            )
            db.add(revision)
        
        chapter.content = cast(str, chapter_data.content)  # type: ignore[assignment]
        # 🔧 修复：使用正确的中文字数统计（移除空白字符后的字符数）
        import re
        chapter.word_count = len(re.sub(r'\s', '', chapter_data.content))  # type: ignore[assignment]
    
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    
    return {
        "message": "Chapter auto-saved successfully",
        "chapter": ChapterResponse.from_orm(chapter)
    }


# ===========================
# 版本历史API端点
# ===========================

@router.get("/{chapter_id:int}/revisions", response_model=List[ChapterRevisionResponse])
async def get_chapter_revisions(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取章节的所有版本历史（按时间倒序）"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 获取版本历史（按时间倒序）
    revisions = db.query(ChapterRevision).filter(
        ChapterRevision.chapter_id == chapter_id
    ).order_by(ChapterRevision.created_at.desc()).all()
    
    return revisions


@router.post("/{chapter_id:int}/revisions/{revision_id:int}/restore", response_model=ChapterResponse)
async def restore_chapter_revision(
    chapter_id: int,
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """从历史版本恢复章节内容"""
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 获取版本历史
    revision = db.query(ChapterRevision).filter(
        (ChapterRevision.id == revision_id) & 
        (ChapterRevision.chapter_id == chapter_id)
    ).first()
    
    if revision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revision not found"
        )
    
    # 保存当前版本到历史
    if chapter.content:
        current_revision = ChapterRevision(
            chapter_id=chapter_id,
            content=chapter.content,
            word_count=chapter.word_count,
            revision_note="恢复前的版本",
            created_by=current_user.id
        )
        db.add(current_revision)
    
    # 恢复内容
    chapter.content = cast(str, revision.content)  # type: ignore[assignment]
    chapter.word_count = revision.word_count  # type: ignore[assignment]
    
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    
    return chapter


# ===========================
# 导出API端点
# ===========================

@router.get("/{chapter_id:int}/export/txt")
async def export_chapter_txt(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """导出章节为TXT格式（UTF-8编码）"""
    from urllib.parse import quote
    
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 生成TXT内容（UTF-8编码）
    content = f"{chapter.title}\n\n{chapter.content or ''}"
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{chapter.title}.txt")
    
    # 返回TXT文件
    return Response(
        content=content.encode('utf-8'),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )


@router.get("/{chapter_id:int}/export/docx")
async def export_chapter_docx(
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """导出章节为DOCX格式（专业排版）"""
    from urllib.parse import quote
    
    chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found"
        )
    
    # 验证权限
    project = db.query(Project).filter(Project.id == chapter.project_id).first()
    if project is None or project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # 创建DOCX文档
    doc = Document()
    
    # 添加标题（居中、加粗、16磅）
    title_para = doc.add_paragraph(chapter.title)
    title_para.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    title_run = title_para.runs[0]
    title_run.bold = True
    title_run.font.size = Pt(16)
    
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
    
    # 将文档保存到BytesIO
    docx_io = BytesIO()
    doc.save(docx_io)
    docx_io.seek(0)
    
    # 对文件名进行URL编码以支持中文
    filename_encoded = quote(f"{chapter.title}.docx")
    
    # 返回DOCX文件
    return StreamingResponse(
        docx_io,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )
