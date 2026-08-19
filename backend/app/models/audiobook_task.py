"""
Audiobook task metadata stored for Celery job tracking.
"""
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class AudiobookTask(Base):
    """Persistent queue/job state for audiobook background tasks."""

    __tablename__ = "audiobook_tasks"

    id = Column(Integer, primary_key=True, index=True)
    celery_task_id = Column(String(128), unique=True, index=True, nullable=True)

    audiobook_project_id = Column(
        Integer, ForeignKey("audiobook_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)

    task_type = Column(String(32), nullable=False)  # full | script_only | audio_from_scripts
    # 扩至 32 容纳父聚合值 completed_with_partial_failure（GUIDE §1.1；值域 CHECK 两阶段收窄由迁移施加）
    status = Column(String(32), default="pending", nullable=False)
    current_stage = Column(String(64), nullable=True)
    progress = Column(Float, default=0.0)
    completed_units = Column(Integer, default=0)
    total_units = Column(Integer, default=0)

    detail_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    audiobook_project = relationship(
        "AudiobookProject", back_populates="tasks", lazy="joined"
    )
    chapter = relationship("Chapter", lazy="select")

    def as_dict(self) -> dict:
        """Convenience method for API serialization."""
        return {
            "id": self.id,
            "celery_task_id": self.celery_task_id,
            "audiobook_project_id": self.audiobook_project_id,
            "chapter_id": self.chapter_id,
            "task_type": self.task_type,
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress,
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "detail": self.detail_json or {},
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AudiobookTask id={self.id} type={self.task_type} "
            f"status={self.status} project={self.audiobook_project_id}>"
        )
