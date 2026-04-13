"""
评审Schema
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


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

    model_config = ConfigDict(from_attributes=True)
