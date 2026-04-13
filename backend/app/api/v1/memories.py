"""
记忆管理API路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.db.base import get_db
from app.models.user import User
from app.models.project import Project
from app.models.memory import Memory
from app.core.security import get_current_user, get_current_user_optional

router = APIRouter(prefix="/api/v1/projects", tags=["memories"])


# 请求/响应模型
class MemoryCreate(BaseModel):
    messages: List[Dict[str, Any]] | None = None
    current_chapter: int | None = None
    current_scene: str | None = None
    active_characters: List[str] | None = None
    writing_goal: str | None = None


class MemoryUpdate(BaseModel):
    messages: List[Dict[str, Any]] | None = None
    current_chapter: int | None = None
    current_scene: str | None = None
    active_characters: List[str] | None = None
    writing_goal: str | None = None


class MemoryResponse(BaseModel):
    id: int
    project_id: int
    user_id: int
    messages: List[Dict[str, Any]] | None
    current_chapter: int | None
    current_scene: str | None
    active_characters: List[str] | None
    writing_goal: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/{project_id}/memories", response_model=List[MemoryResponse])
async def get_project_memories(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的所有记忆快照"""
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 查询所有记忆
    memories = db.query(Memory).filter(
        Memory.project_id == project_id
    ).order_by(Memory.updated_at.desc()).all()
    
    return memories


@router.get("/{project_id}/memories/latest", response_model=MemoryResponse | None)
async def get_latest_memory(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取项目的最新记忆快照"""
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 获取最新记忆
    memory = db.query(Memory).filter(
        Memory.project_id == project_id
    ).order_by(Memory.updated_at.desc()).first()
    
    return memory


@router.post("/{project_id}/memories", response_model=MemoryResponse)
async def save_memory(
    project_id: int,
    memory_data: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """保存新的记忆快照"""
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 创建记忆记录
    memory = Memory(
        project_id=project_id,
        user_id=current_user.id,
        messages=memory_data.messages,
        current_chapter=memory_data.current_chapter,
        current_scene=memory_data.current_scene,
        active_characters=memory_data.active_characters,
        writing_goal=memory_data.writing_goal
    )
    
    db.add(memory)
    db.commit()
    db.refresh(memory)
    
    return memory


@router.put("/{project_id}/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    project_id: int,
    memory_id: int,
    memory_data: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新记忆快照"""
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 查找记忆
    memory = db.query(Memory).filter(
        Memory.id == memory_id,
        Memory.project_id == project_id
    ).first()
    
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found"
        )
    
    # 更新字段
    for key, value in memory_data.dict(exclude_unset=True).items():
        setattr(memory, key, value)
    
    db.add(memory)
    db.commit()
    db.refresh(memory)
    
    return memory


@router.delete("/{project_id}/memories/{memory_id}")
async def delete_memory(
    project_id: int,
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除记忆快照"""
    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # 查找记忆
    memory = db.query(Memory).filter(
        Memory.id == memory_id,
        Memory.project_id == project_id
    ).first()
    
    if not memory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found"
        )
    
    db.delete(memory)
    db.commit()
    
    return {"message": "Memory deleted successfully"}


@router.post("/{project_id}/memories/auto-save", response_model=MemoryResponse)
async def auto_save_memory(
    project_id: int,
    memory_data: MemoryCreate,
    token: str | None = None,  # 🆕 支持 query parameter token（用于 sendBeacon）
    current_user: User | None = Depends(get_current_user_optional),  # 🔧 使用可选验证
    db: Session = Depends(get_db)
):
    """
    自动保存记忆（覆盖最新的记忆或创建新记忆）
    用于工作流程中的自动保存功能

    支持两种认证方式：
    1. Header Authorization: Bearer <token>（正常请求）
    2. Query Parameter: ?token=<token>（sendBeacon 请求）
    """
    from app.core.security import verify_token

    # 🆕 如果使用 query parameter token，验证并获取用户
    user = current_user
    if user is None and token:
        try:
            payload = verify_token(token)
            user_id = payload.get("sub")
            if user_id:
                user = db.query(User).filter(User.id == int(user_id)).first()
        except Exception:
            pass

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    # 验证项目所有权
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # 查找最新记忆
    latest_memory = db.query(Memory).filter(
        Memory.project_id == project_id
    ).order_by(Memory.updated_at.desc()).first()

    # 🆕 消息数量上限
    MAX_MESSAGES = 50

    if latest_memory:
        # 🔧 修复：合并消息而不是替换（避免丢失后端追加的消息）
        existing_messages = latest_memory.messages or []
        new_messages = memory_data.messages or []

        # 去重：根据 timestamp 过滤已存在的消息
        existing_timestamps = {m.get('timestamp') for m in existing_messages if m.get('timestamp')}
        merged_messages = existing_messages + [
            m for m in new_messages
            if m.get('timestamp') not in existing_timestamps
        ]

        # 限制消息数量（保留最近 MAX_MESSAGES 条）
        if len(merged_messages) > MAX_MESSAGES:
            merged_messages = merged_messages[-MAX_MESSAGES:]

        latest_memory.messages = merged_messages

        # 更新其他字段（非 messages 字段）
        if memory_data.current_chapter is not None:
            latest_memory.current_chapter = memory_data.current_chapter
        if memory_data.current_scene is not None:
            latest_memory.current_scene = memory_data.current_scene
        if memory_data.active_characters is not None:
            latest_memory.active_characters = memory_data.active_characters
        if memory_data.writing_goal is not None:
            latest_memory.writing_goal = memory_data.writing_goal

        db.add(latest_memory)
        db.commit()
        db.refresh(latest_memory)
        return latest_memory
    else:
        # 创建新记忆
        new_messages = memory_data.messages or []
        # 限制消息数量
        if len(new_messages) > MAX_MESSAGES:
            new_messages = new_messages[-MAX_MESSAGES:]

        memory = Memory(
            project_id=project_id,
            user_id=user.id,
            messages=new_messages,
            current_chapter=memory_data.current_chapter,
            current_scene=memory_data.current_scene,
            active_characters=memory_data.active_characters,
            writing_goal=memory_data.writing_goal
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory
