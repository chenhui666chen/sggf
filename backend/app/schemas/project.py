"""
项目和章节Schema
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class ProjectBase(BaseModel):
    """项目基础Schema"""
    title: str
    description: Optional[str] = None
    genre: Optional[str] = None


class ProjectCreate(ProjectBase):
    """项目创建Schema"""
    pass


class ProjectUpdate(BaseModel):
    """项目更新Schema"""
    title: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    status: Optional[str] = None


class ProjectResponse(ProjectBase):
    """项目响应Schema"""
    id: int
    user_id: int
    status: str
    word_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ChapterBase(BaseModel):
    """章节基础Schema"""
    chapter_number: int
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None  # 核心事件摘要
    summary_data: Optional[str] = None  # 结构化摘要数据(JSON)


class ChapterCreate(BaseModel):
    """章节创建Schema - 需要project_id"""
    project_id: int
    chapter_number: Optional[int] = None  # 可选，后端自动计算
    title: Optional[str] = None  # 可选，默认自动生成
    content: Optional[str] = None


class ChapterUpdate(BaseModel):
    """章节更新Schema"""
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None  # 核心事件摘要
    summary_data: Optional[str] = None  # 结构化摘要数据(JSON)


class ChapterResponse(ChapterBase):
    """章节响应Schema"""
    id: int
    project_id: int
    status: str
    word_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    """项目详情响应Schema"""
    chapters: List[ChapterResponse] = []


class ChapterRevisionResponse(BaseModel):
    """版本历史响应Schema"""
    id: int
    chapter_id: int
    content: str
    word_count: int
    revision_note: Optional[str] = None
    created_at: datetime
    created_by: Optional[int] = None
    
    class Config:
        from_attributes = True

