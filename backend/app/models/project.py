"""
项目模型
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.memory import Memory


class Project(Base):
    """项目表"""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft, writing, reviewing, published
    word_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now())

    # 关系定义（添加级联删除）
    chapters: Mapped[List["Chapter"]] = relationship(
        "Chapter",
        back_populates="project",
        lazy="select",
        cascade="all, delete-orphan"  # 级联删除章节
    )
    memories: Mapped[List["Memory"]] = relationship(
        "Memory",
        lazy="select",
        cascade="all, delete-orphan"  # 级联删除记忆
    )

    def __repr__(self):
        return f"<Project {self.title}>"


class Chapter(Base):
    """章节表"""
    __tablename__ = "chapters"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),  # 添加级联删除
        nullable=False
    )
    chapter_number: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # 章节摘要相关字段
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="核心事件摘要")
    summary_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="结构化摘要数据(JSON)")
    
    status: Mapped[str] = mapped_column(String(50), default="draft")  # draft, writing, reviewing, published
    word_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now())
    
    # 关系定义
    project: Mapped["Project"] = relationship("Project", back_populates="chapters")
    revisions: Mapped[List["ChapterRevision"]] = relationship(
        "ChapterRevision",
        back_populates="chapter",
        lazy="select",
        cascade="all, delete-orphan"  # 级联删除版本历史
    )
    
    def __repr__(self):
        return f"<Chapter {self.title}>"


class ChapterRevision(Base):
    """章节版本历史表"""
    __tablename__ = "chapter_revisions"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(default=0)
    revision_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(),
        index=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    # 关系定义
    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="revisions")
    
    def __repr__(self):
        return f"<ChapterRevision id={self.id} chapter_id={self.chapter_id}>"

