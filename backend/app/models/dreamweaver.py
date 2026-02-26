from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class DreamweaverProject(Base):
    __tablename__ = "dreamweaver_projects"

    id = Column(Integer, primary_key=True, index=True)

    run_id = Column(String(128), unique=True, nullable=False, index=True)
    source_project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    schema_version = Column(String(32), nullable=False, default="0.1.0")

    status = Column(String(32), nullable=False, default="running")  # running|completed|failed
    state = Column(String(32), nullable=True)
    stage = Column(String(32), nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    error_type = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    contract_json = Column(JSON, nullable=True, comment="强类型契约快照（Project/Episode/Shot/Asset）")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DreamweaverEpisode(Base):
    __tablename__ = "dreamweaver_episodes"

    id = Column(Integer, primary_key=True, index=True)
    dreamweaver_project_id = Column(
        Integer, ForeignKey("dreamweaver_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    episode_index = Column(Integer, nullable=False, default=1)
    title = Column(String(255), nullable=False, default="Episode 1")
    schema_version = Column(String(32), nullable=False, default="0.1.0")

    constraints_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DreamweaverShot(Base):
    __tablename__ = "dreamweaver_shots"

    id = Column(Integer, primary_key=True, index=True)
    episode_id = Column(Integer, ForeignKey("dreamweaver_episodes.id", ondelete="CASCADE"), nullable=False, index=True)

    shot_index = Column(Integer, nullable=False)
    scene_id = Column(String(64), nullable=False)
    shot_key = Column(String(128), nullable=False, index=True)
    description = Column(Text, nullable=True)
    duration_s = Column(Float, nullable=False, default=3.0)

    schema_version = Column(String(32), nullable=False, default="0.1.0")
    head_frame_json = Column(JSON, nullable=True)
    tail_frame_json = Column(JSON, nullable=True)
    constraints_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DreamweaverAsset(Base):
    __tablename__ = "dreamweaver_assets"

    id = Column(Integer, primary_key=True, index=True)

    dreamweaver_project_id = Column(
        Integer, ForeignKey("dreamweaver_projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id = Column(Integer, ForeignKey("dreamweaver_episodes.id", ondelete="CASCADE"), nullable=True, index=True)
    shot_id = Column(Integer, ForeignKey("dreamweaver_shots.id", ondelete="CASCADE"), nullable=True, index=True)

    asset_type = Column(String(32), nullable=False)  # image|video|audio|qc_report|anchor
    role = Column(String(64), nullable=False)  # head_frame|tail_frame|mid_frame|clip|merged|...
    uri = Column(Text, nullable=False)

    schema_version = Column(String(32), nullable=False, default="0.1.0")
    meta_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DreamweaverRunEvent(Base):
    __tablename__ = "dreamweaver_run_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    stage = Column(String(32), nullable=True)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
