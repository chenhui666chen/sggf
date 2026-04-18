"""
有声书数据库模型
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class AudiobookProject(Base):
    """有声书项目表"""
    __tablename__ = "audiobook_projects"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    # 状态
    status = Column(String(20), default="pending")  # pending/processing/completed/failed
    
    # 配置
    tts_provider = Column(String(20), default="aliyun")
    voice_mapping = Column(JSON, default={})  # {character_name: voice_profile}
    enable_cache = Column(Boolean, default=True)
    
    # 统计
    total_chapters = Column(Integer, default=0)
    completed_chapters = Column(Integer, default=0)
    failed_chapters = Column(Integer, default=0)
    
    total_duration = Column(Float, default=0.0)  # 秒
    total_size = Column(Integer, default=0)  # 字节
    total_cost = Column(Float, default=0.0)  # 元
    
    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    project = relationship("Project", back_populates="audiobook_projects")
    chapter_audios = relationship("ChapterAudio", back_populates="audiobook_project", cascade="all, delete-orphan")
    runs = relationship(
        "ChapterAudioRun",
        back_populates="audiobook_project",
        cascade="all, delete-orphan",
        lazy="select",
    )
    tasks = relationship(
        "AudiobookTask",
        back_populates="audiobook_project",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ChapterAudio(Base):
    """章节音频表"""
    __tablename__ = "chapter_audios"

    id = Column(Integer, primary_key=True, index=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    
    # 新增：任务状态追踪
    task_id = Column(String(100), nullable=True, index=True)  # 任务ID，用于查询实时状态
    
    # 生成进度缓存（断点续传）
    generation_progress_json = Column(Text, nullable=True)  # 存储已完成的片段索引列表和缓存信息
    
    # 叙事风格预设
    narration_style = Column(String(50), default="professional")  # professional/dramatic/relaxing/expressive/custom
    narration_style_prompt = Column(Text, nullable=True)  # 自定义叙事风格prompt
    
    # 字幕同步
    subtitle_path = Column(String(500), nullable=True)  # SRT字幕文件路径
    subtitle_format = Column(String(20), default="srt")  # srt/ass/vtt
    
    # 音频信息
    audio_path = Column(String(500))  # 相对路径或URL
    duration = Column(Float, default=0.0)  # 秒
    file_size = Column(Integer, default=0)  # 字节
    
    # 元数据
    segment_count = Column(Integer, default=0)  # 片段数
    dialogue_count = Column(Integer, default=0)  # 对话数
    narration_count = Column(Integer, default=0)  # 旁白数
    character_count = Column(Integer, default=0)  # 参与角色数
    
    # 统计
    generation_time = Column(Float, default=0.0)  # 生成耗时（秒）
    tts_cost = Column(Float, default=0.0)  # TTS成本（元）
    cache_hit_rate = Column(Float, default=0.0)  # 缓存命中率

    # 剧本与评审（仅保留最近一次生成结果，可被新一轮覆盖）
    script_json = Column(Text, nullable=True)  # 存储有声剧本片段列表（JSON字符串）
    script_review_json = Column(Text, nullable=True)  # 存储剧本质量评审报告（JSON字符串）
    script_status = Column(String(20), default="pending")  # pending/reviewed/approved
    final_audio_review_json = Column(Text, nullable=True)  # 最终音频评审结果（JSON字符串）
    segment_reviews_json = Column(Text, nullable=True)  # 片段级审查记录（segment_index -> {quality_score, notes, needs_regenerate}）
    
    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    audiobook_project = relationship("AudiobookProject", back_populates="chapter_audios")
    chapter = relationship("Chapter")


class ChapterAudioRun(Base):
    """章节音频生成运行态。"""

    __tablename__ = "chapter_audio_runs"

    id = Column(Integer, primary_key=True, index=True)
    audiobook_project_id = Column(
        Integer,
        ForeignKey("audiobook_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id = Column(
        Integer,
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    run_type = Column(String(32), nullable=False)
    celery_task_id = Column(String(128), nullable=True, index=True)
    status = Column(String(20), default="pending", nullable=False)
    current_stage = Column(String(64), nullable=True)
    progress = Column(Float, default=0.0)
    completed_segment_count = Column(Integer, default=0)
    total_segment_count = Column(Integer, default=0)

    tts_model = Column(String(120), nullable=True)
    output_format = Column(String(20), nullable=True)
    narration_style = Column(String(50), nullable=True)
    narration_style_prompt = Column(Text, nullable=True)
    voice_config_hash = Column(String(128), nullable=True)
    audio_fx_hash = Column(String(128), nullable=True)
    script_hash = Column(String(128), nullable=True)

    resumable = Column(Boolean, default=True, nullable=False)
    checkpoint_json = Column(JSON, nullable=True)
    temp_asset_prefix = Column(String(500), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)

    audiobook_project = relationship("AudiobookProject", back_populates="runs")
    chapter = relationship("Chapter")
