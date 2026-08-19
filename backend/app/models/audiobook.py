"""
有声书数据库模型
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

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
    total_duration = Column(Float, default=0.0)
    total_size = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # 引擎隔离（GUIDE §2.1；Contract 态：NOT NULL+CHECK+索引由 Contract 迁移施加）
    # server_default 与 DB 对齐：ORM 未显式赋值时省略列，由数据库默认兜底
    engine_mode = Column(String(20), nullable=False, server_default="legacy_stems")
    engine_config_snapshot = Column(Text, nullable=True)
    engine_config_fingerprint = Column(String(64), nullable=True, index=True)
    # 无 server_default（GUIDE R19/P2-1）：新记录由应用服务创建批次时显式写入；
    # NOT NULL 待全部构造点改造完成后由后续 Contract 步骤施加（当前仅收窄 CHECK）
    snapshot_status = Column(String(20), nullable=True)

    # 关系
    project = relationship("Project", back_populates="audiobook_projects")
    chapter_audios = relationship(
        "ChapterAudio",
        back_populates="audiobook_project",
        cascade="all, delete-orphan",
    )
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

    # id 参与双指针复合外键本地列，SQLAlchemy 会隐式关闭自增；显式保持与 dev 库 SERIAL 一致
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)

    # 叙事风格预设
    narration_style = Column(String(50), default="professional")  # professional/dramatic/relaxing/expressive/custom
    narration_style_prompt = Column(Text, nullable=True)

    # 字幕同步
    subtitle_path = Column(String(500), nullable=True)
    subtitle_format = Column(String(20), default="srt")  # srt/ass/vtt

    # 音频信息
    audio_path = Column(String(500))
    duration = Column(Float, default=0.0)
    file_size = Column(Integer, default=0)

    # 元数据
    segment_count = Column(Integer, default=0)
    dialogue_count = Column(Integer, default=0)
    narration_count = Column(Integer, default=0)
    character_count = Column(Integer, default=0)

    # 统计
    generation_time = Column(Float, default=0.0)
    tts_cost = Column(Float, default=0.0)
    cache_hit_rate = Column(Float, default=0.0)

    # 剧本与评审
    script_json = Column(Text, nullable=True)
    script_review_json = Column(Text, nullable=True)
    script_status = Column(String(20), default="pending")  # pending/reviewed/approved
    final_audio_review_json = Column(Text, nullable=True)
    segment_reviews_json = Column(Text, nullable=True)
    script_review_version = Column(String(64), nullable=True)  # dialogue 审批审核版本（§2.9，R8）

    # 渲染状态与双指针发布（GUIDE §2.4，Expand 态全部可空）
    render_status = Column(String(32), nullable=True)  # 仅 seed_scene 使用
    render_status_detail = Column(JSON, nullable=True)
    desired_run_id = Column(Integer, nullable=True)
    published_run_id = Column(Integer, nullable=True)
    published_input_signature = Column(String(64), nullable=True)
    published_provenance = Column(String(20), nullable=True)  # published | legacy_unverified

    # 来源审计（§2.1 复制合同持久化落点，R7）
    source_audiobook_project_id = Column(Integer, nullable=True)
    source_chapter_audio_id = Column(Integer, nullable=True)
    source_script_hash = Column(String(64), nullable=True)
    source_script_review_version = Column(String(64), nullable=True)
    source_provenance_json = Column(JSON, nullable=True)

    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        # 唯一 active（R10/P0-4）：同一批次同一章节至多一条未软删除记录。
        # 与 Contract 迁移 `contract_audiobook_isolation_schema` 施加的
        # 部分唯一索引一致（模型声明保证 create_all/测试环境同样生效；
        # sqlite_where 缺失时 SQLite 会退化为全表唯一，拒绝软删后重建）
        Index(
            "uq_chapter_audio_active_unique",
            "audiobook_project_id",
            "chapter_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # 双指针复合外键（R10/P1-1）：RESTRICT——被引用 run 行不可物理删除；
        # 终态 run 墓碑化策略落在 repository/service 层（R11/P2-2）
        ForeignKeyConstraint(
            ["desired_run_id", "id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_chapter_audio_desired_run",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["published_run_id", "id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_chapter_audio_published_run",
            ondelete="RESTRICT",
            use_alter=True,
        ),
    )

    # 关系
    audiobook_project = relationship("AudiobookProject", back_populates="chapter_audios")
    chapter = relationship("Chapter")


class ChapterAudioRun(Base):
    """章节音频生成运行态"""

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

    # 运行作用域与快照（GUIDE §1.1，Expand 态可空；回填与 NOT NULL 属 Migrate/Contract）
    chapter_audio_id = Column(Integer, ForeignKey("chapter_audios.id", use_alter=True), nullable=True)
    engine_mode_snapshot = Column(String(20), nullable=True)
    run_input_snapshot = Column(Text, nullable=True)
    revision_set_hash = Column(String(64), nullable=True)
    input_signature = Column(String(64), nullable=True)

    # 可靠派发状态机（§2.1 六步第 4 步，R10/P0-1；值域 CHECK 由 Contract 施加）
    dispatch_status = Column(String(16), nullable=False, server_default="pending")
    predecessor_run_id = Column(Integer, ForeignKey("chapter_audio_runs.id", use_alter=True), nullable=True)
    dispatch_attempts = Column(Integer, nullable=True)
    next_dispatch_at = Column(DateTime(timezone=True), nullable=True)
    dispatch_claim_token = Column(String(64), nullable=True)
    dispatch_claimed_at = Column(DateTime(timezone=True), nullable=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)

    # worker 消费租约（R11/P1-1：CAS 认领/heartbeat 续期/过期接管）
    claim_token = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)

    # 三维状态投影（§2.4）：本次运行结果状态，运行结束时写入
    result_render_status = Column(String(32), nullable=True)
    result_render_detail = Column(JSON, nullable=True)

    # 计费封口与计费账户（R17/P0、R17/P1-3）
    billing_finalized_at = Column(DateTime(timezone=True), nullable=True)
    billing_account_user_id = Column(Integer, nullable=True)

    # run 墓碑化（R12/P1-4）：任何 run 只墓碑化、永不物理删除
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

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

    __table_args__ = (
        # 复合唯一键（R8/R9 运行作用域）：供 outputs/artifacts 复合外键与
        # ChapterAudio 双指针复合外键引用；(id) 已为主键，恒成立
        UniqueConstraint("id", "chapter_audio_id", name="uq_chapter_audio_run_scope"),
    )

    audiobook_project = relationship("AudiobookProject", back_populates="runs")
    chapter = relationship("Chapter")


class ChapterAudioOutput(Base):
    """run 级输出登记表（GUIDE §2.4 规则 3/4，R8 完整模型）"""

    __tablename__ = "chapter_audio_outputs"

    id = Column(Integer, primary_key=True)
    # 每 run 至多一条（R13/P1-c：RESTRICT 替代 CASCADE，与迁移合同一致）
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    chapter_audio_id = Column(Integer, ForeignKey("chapter_audios.id", ondelete="RESTRICT"), nullable=False, index=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    status = Column(String(16), nullable=False, server_default="staged")  # staged | published | superseded
    file_status = Column(String(16), nullable=False, server_default="present")  # present | purged | missing
    purged_at = Column(DateTime(timezone=True), nullable=True)
    audio_path = Column(String(500), nullable=False)
    duration = Column(Float, nullable=True)
    file_size = Column(Integer, nullable=True)
    subtitle_path = Column(String(500), nullable=True)
    subtitle_format = Column(String(16), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('staged','published','superseded')", name="ck_chapter_audio_output_status"),
        CheckConstraint("file_status IN ('present','purged','missing')", name="ck_chapter_audio_output_file_status"),
        # published 时整章可导出字段必须齐全
        CheckConstraint(
            "status <> 'published' OR (audio_path IS NOT NULL AND duration IS NOT NULL AND file_size IS NOT NULL)",
            name="ck_chapter_audio_output_published_fields",
        ),
        # 每个 chapter_audio_id 至多一条 published（部分唯一索引）
        Index(
            "uq_chapter_audio_output_published",
            "chapter_audio_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
            sqlite_where=text("status = 'published'"),
        ),
        # run 与输出必须属于同一运行作用域（复合外键 → runs 复合唯一键，R9/P0-3）
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_chapter_audio_output_run_scope",
        ),
    )


class SceneEditRevision(Base):
    """场景编辑 revision（§2.9 双表设计表一：严格 append-only，无 is_head 列，禁 UPDATE/DELETE）"""

    __tablename__ = "scene_edit_revisions"

    id = Column(Integer, primary_key=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    base_run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=True)
    # 链前驱（R7：单事实表示，不存 parent_revision_hash，hash 经 JOIN）
    parent_revision_id = Column(Integer, nullable=True)
    edit_type = Column(String(32), nullable=False)  # dialogue | director_override | voice_binding
    payload = Column(Text, nullable=False)
    affected_anchors = Column(Text, nullable=True)
    input_signature = Column(String(64), nullable=False)  # payload 内容规范化签名（幂等去重）
    revision_hash = Column(String(64), nullable=False)  # 链节点签名（含父引用），全表唯一
    operator_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("revision_hash", name="uq_scene_edit_revision_hash"),
        # 复合唯一键：供 head 表与自引用 parent 外键引用作用域（R7）
        UniqueConstraint(
            "id", "audiobook_project_id", "chapter_id", "edit_type",
            name="uq_scene_edit_revision_scope",
        ),
        # 自引用复合外键：parent 必须与子行同 (project, chapter, edit_type)（R7）
        ForeignKeyConstraint(
            ["parent_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
            [
                "scene_edit_revisions.id", "scene_edit_revisions.audiobook_project_id",
                "scene_edit_revisions.chapter_id", "scene_edit_revisions.edit_type",
            ],
            name="fk_scene_edit_revision_parent_scope",
        ),
    )


class SceneEditRevisionHead(Base):
    """场景编辑 head（§2.9 双表设计表二：每 (project, chapter, edit_type) 一行，可 UPDATE，提供稳定行锁）"""

    __tablename__ = "scene_edit_revision_heads"

    id = Column(Integer, primary_key=True)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    edit_type = Column(String(32), nullable=False)
    head_revision_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("audiobook_project_id", "chapter_id", "edit_type", name="uq_scene_edit_head"),
        # 复合外键：head 指向的 revision 必须与 head 行同作用域（R7）
        ForeignKeyConstraint(
            ["head_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
            [
                "scene_edit_revisions.id", "scene_edit_revisions.audiobook_project_id",
                "scene_edit_revisions.chapter_id", "scene_edit_revisions.edit_type",
            ],
            name="fk_scene_edit_head_revision_scope",
        ),
    )


class SceneAudioArtifact(Base):
    """场景音频正式 artifact 登记（GUIDE §2.14）"""

    __tablename__ = "scene_audio_artifacts"

    id = Column(Integer, primary_key=True)
    artifact_id = Column(String(64), unique=True, nullable=False)
    audiobook_project_id = Column(Integer, ForeignKey("audiobook_projects.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    # 发布作用域（R8）
    chapter_audio_id = Column(Integer, ForeignKey("chapter_audios.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False)
    scene_id = Column(String(64), nullable=False)  # 生成期 scene_id（展示用）
    segment_keys = Column(Text, nullable=True)  # 稳定锚点（JSON 数组）
    scene_topology_hash = Column(String(64), nullable=False)
    content_digest = Column(String(64), nullable=False)  # 文件 sha256
    stored_rel_path = Column(String(500), nullable=False)  # artifact 存储相对路径
    source_run_path = Column(String(500), nullable=True)  # 原始运行目录路径（审计）
    source_kind = Column(String(32), nullable=False, server_default="seed")  # seed | legacy_fallback | manual
    status = Column(String(16), nullable=False, server_default="staged")  # staged | active | superseded
    duration_s = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('staged','active','superseded')",
            name="ck_scene_audio_artifact_status",
        ),
        CheckConstraint(
            "source_kind IN ('seed','legacy_fallback','manual')",
            name="ck_scene_audio_artifact_source_kind",
        ),
        # 部分唯一索引：每 run 每 scene 至多一条未删除登记（§2.14）
        Index(
            "uq_scene_audio_artifact_run_scene",
            "run_id",
            "scene_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # 复合外键（R8；R9 收紧为运行作用域）：run 与 artifact 必须属于同一 chapter_audio
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_scene_audio_artifact_run_scope",
        ),
    )


class AudiobookTaskDispatch(Base):
    """任务-派发父子关系（R12/P1-1：仅存父子关系与展示投影，单一事实源为 ChapterAudioRun）"""

    __tablename__ = "audiobook_task_dispatches"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("audiobook_tasks.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("chapter_audio_runs.id"), nullable=False, unique=True)
    chapter_audio_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 复合外键：子派发的 chapter_audio_id 必须属于该 run（R12/P1-1）
        ForeignKeyConstraint(
            ["run_id", "chapter_audio_id"],
            ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
            name="fk_audiobook_task_dispatch_run_scope",
        ),
    )


class ProviderDispatchCapability(Base):
    """供应商派发能力声明（R11/P1-3，对齐 provider_recovery.RECOVERY_METHODS）"""

    __tablename__ = "provider_dispatch_capabilities"

    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False, unique=True)
    accepts_idempotency_key = Column(Boolean, nullable=False, server_default="false")
    returns_request_id = Column(Boolean, nullable=False, server_default="false")
    supports_request_query = Column(Boolean, nullable=False, server_default="false")
    has_recoverable_result_url = Column(Boolean, nullable=False, server_default="false")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
