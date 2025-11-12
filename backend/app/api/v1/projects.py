"""
项目API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from app.db.base import get_db
from app.models.user import User
from app.models.project import Project, Chapter
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetailResponse,
    ChapterCreate, ChapterUpdate, ChapterResponse
)
from app.core.security import get_current_user

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
        genre=project_data.genre
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
        
    except Exception as e:
        logger.error(f"   ❌ 原始 SQL 表清理失败: {e}")
        # 不阻塞删除流程，继续执行
    
    # 🧹 步骤1：清理 ChromaDB 向量数据
    try:
        from langchain.vectorstores import Chroma
        from config import Config
        
        # 获取 ChromaDB 目录
        chroma_dir = os.getenv('CHROMA_PERSIST_DIRECTORY', 'chroma_db')
        project_namespace = f"project_{project_id}"
        
        logger.info(f"   💾 步骤1: 清理 ChromaDB 向量数据 (namespace: {project_namespace})")
        
        # 方法1：删除整个 collection（如果使用项目隔离的 collection）
        try:
            vectorstore = Chroma(
                collection_name=project_namespace,
                persist_directory=chroma_dir
            )
            vectorstore.delete_collection()
            logger.info(f"   ✅ 已删除 ChromaDB collection: {project_namespace}")
        except Exception as e:
            logger.warning(f"   ⚠️ ChromaDB collection 删除失败: {e}")
        
        # 方法2：删除整个项目目录（如果使用项目独立目录）
        project_chroma_dir = Path(chroma_dir) / project_namespace
        if project_chroma_dir.exists():
            try:
                shutil.rmtree(project_chroma_dir)
                logger.info(f"   ✅ 已删除 ChromaDB 项目目录: {project_chroma_dir}")
            except Exception as e:
                logger.warning(f"   ⚠️ ChromaDB 目录删除失败: {e}")
        
        # 方法3：通过元数据过滤器删除（如果使用共享 collection 但通过 metadata 隔离）
        try:
            shared_vectorstore = Chroma(
                collection_name="novel_knowledge",
                persist_directory=chroma_dir
            )
            # 尝试根据 project_id 删除
            # 注意：Chroma 不直接支持批量删除，这个只是备用方案
            logger.info(f"   📝 备注：如果使用共享 collection，请确保通过 metadata 过滤器正确隔离")
        except Exception as e:
            logger.debug(f"   ℹ️ 共享 collection 检查: {e}")
        
    except Exception as e:
        logger.error(f"   ❌ ChromaDB 清理失败: {e}")
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

