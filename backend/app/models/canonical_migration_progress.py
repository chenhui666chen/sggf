"""canonical 去重合并迁移进度表（GUIDE R22/P1-1 方案 A：三态值域，全局单实例）"""

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint

from app.db.base import Base


class AudiobookCanonicalMigrationProgress(Base):
    """迁移进度专用表——结构化迁移报告的唯一事实源（R20/P2-1、R21/P1-1、R22/P1-1）。

    status 值域仅 pending/completed/failed：本版默认全局单实例，
    不存在 running/租约/接管分支（R22/P1-1 方案 A）；
    确需多实例并行时须同步扩展 CHECK 值域并单列设计。
    """

    __tablename__ = "audiobook_canonical_migration_progress"

    id = Column(Integer, primary_key=True)
    migration_version = Column(String(64), nullable=False)
    audiobook_project_id = Column(Integer, nullable=False, index=True)
    chapter_id = Column(Integer, nullable=False, index=True)
    canonical_chapter_audio_id = Column(Integer, nullable=True)
    source_row_ids = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, server_default="pending")
    completed_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, server_default="0", default=0)
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_failed_at = Column(DateTime(timezone=True), nullable=True)
    last_error_code = Column(String(64), nullable=True)
    failure_detail = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','completed','failed')",
            name="ck_audiobook_canonical_migration_progress_status",
        ),
        UniqueConstraint(
            "migration_version",
            "audiobook_project_id",
            "chapter_id",
            name="uq_canonical_migration_progress_group",
        ),
    )
