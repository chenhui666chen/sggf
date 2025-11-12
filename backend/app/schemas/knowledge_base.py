"""
知识库和评审Schema
"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class KnowledgeBaseBase(BaseModel):
    """知识库基础Schema"""
    type: str  # 'world', 'character', 'plot'
    name: str
    content: Optional[str] = None


class KnowledgeBaseCreate(KnowledgeBaseBase):
    """知识库创建Schema"""
    pass


class KnowledgeBaseUpdate(BaseModel):
    """知识库更新Schema"""
    name: Optional[str] = None
    content: Optional[str] = None


class KnowledgeBaseResponse(KnowledgeBaseBase):
    """知识库响应Schema"""
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ReviewBase(BaseModel):
    """评审基础Schema"""
    overall_score: Optional[int] = None
    story_score: Optional[int] = None
    character_score: Optional[int] = None
    language_score: Optional[int] = None
    structure_score: Optional[int] = None
    innovation_score: Optional[int] = None
    feedback: Optional[str] = None
    suggestions: Optional[str] = None
    strengths: Optional[str] = None


class ReviewCreate(ReviewBase):
    """评审创建Schema"""
    pass


class ReviewUpdate(BaseModel):
    """评审更新Schema"""
    feedback: Optional[str] = None
    suggestions: Optional[str] = None


class ReviewResponse(ReviewBase):
    """评审响应Schema"""
    id: int
    chapter_id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

