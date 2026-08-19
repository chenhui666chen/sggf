"""expand audiobook engine isolation schema

Expand 发布单元（GUIDE R19/P1-2）：新增可空列与新表，不收紧任何存量约束。
NOT NULL、部分唯一索引（重复 active）、收窄 CHECK 属 Contract 单元；
历史回填、canonical 去重合并属 Migrate 单元（独立幂等任务）。
幂等可重复执行；允许旧版本实例继续运行；无需维护窗口。

Revision ID: expand_audiobook_isolation_schema
Revises: expand_canonical_migration_progress
Create Date: 2026-08-15

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "expand_audiobook_isolation_schema"
down_revision = "expand_canonical_migration_progress"
branch_labels = None
depends_on = None


# AudiobookTask 两阶段 CHECK 第一步（R14/P1-b）：旧值域 ∪ 新聚合值域 ∪ 暂停态并存
_TASK_STATUS_STAGE1_VALUES = (
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "completed_with_partial_failure",
    "pause_requested",
    "paused",
)


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}


def _constraint_names(bind, table_name: str) -> set[str]:
    rows = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:tbl AS regclass)"
        ),
        {"tbl": table_name},
    )
    return {str(row[0]) for row in rows}


def _add_columns(table_name: str, columns: list[sa.Column]) -> None:
    bind = op.get_bind()
    existing = _column_names(sa.inspect(bind), table_name)
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)
        existing = _column_names(sa.inspect(bind), table_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── audiobook_projects：引擎隔离列（§2.1，Expand 态全部可空，snapshot_status 无 server_default）
    _add_columns(
        "audiobook_projects",
        [
            sa.Column("engine_mode", sa.String(length=20), nullable=True),
            sa.Column("engine_config_snapshot", sa.Text(), nullable=True),
            sa.Column("engine_config_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("snapshot_status", sa.String(length=20), nullable=True),
        ],
    )
    inspector = sa.inspect(bind)
    if "ix_audiobook_projects_engine_config_fingerprint" not in _index_names(inspector, "audiobook_projects"):
        op.create_index(
            "ix_audiobook_projects_engine_config_fingerprint",
            "audiobook_projects",
            ["engine_config_fingerprint"],
        )

    # ── chapter_audios：渲染状态、双指针与来源审计列（§2.4/§2.1）
    _add_columns(
        "chapter_audios",
        [
            sa.Column("script_review_version", sa.String(length=64), nullable=True),
            sa.Column("render_status", sa.String(length=32), nullable=True),
            sa.Column("render_status_detail", sa.JSON(), nullable=True),
            sa.Column("desired_run_id", sa.Integer(), nullable=True),
            sa.Column("published_run_id", sa.Integer(), nullable=True),
            sa.Column("published_input_signature", sa.String(length=64), nullable=True),
            sa.Column("published_provenance", sa.String(length=20), nullable=True),
            sa.Column("source_audiobook_project_id", sa.Integer(), nullable=True),
            sa.Column("source_chapter_audio_id", sa.Integer(), nullable=True),
            sa.Column("source_script_hash", sa.String(length=64), nullable=True),
            sa.Column("source_script_review_version", sa.String(length=64), nullable=True),
            sa.Column("source_provenance_json", sa.JSON(), nullable=True),
        ],
    )

    # ── chapter_audio_runs：运行作用域、派发、租约、计费封口列（§1.1）
    _add_columns(
        "chapter_audio_runs",
        [
            sa.Column(
                "chapter_audio_id",
                sa.Integer(),
                sa.ForeignKey("chapter_audios.id", use_alter=True),
                nullable=True,
            ),
            sa.Column("engine_mode_snapshot", sa.String(length=20), nullable=True),
            sa.Column("run_input_snapshot", sa.Text(), nullable=True),
            sa.Column("revision_set_hash", sa.String(length=64), nullable=True),
            sa.Column("input_signature", sa.String(length=64), nullable=True),
            sa.Column("dispatch_status", sa.String(length=16), nullable=True),
            sa.Column(
                "predecessor_run_id",
                sa.Integer(),
                sa.ForeignKey("chapter_audio_runs.id", use_alter=True),
                nullable=True,
            ),
            sa.Column("dispatch_attempts", sa.Integer(), nullable=True),
            sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatch_claim_token", sa.String(length=64), nullable=True),
            sa.Column("dispatch_claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claim_token", sa.String(length=64), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("result_render_status", sa.String(length=32), nullable=True),
            sa.Column("result_render_detail", sa.JSON(), nullable=True),
            sa.Column("billing_finalized_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("billing_account_user_id", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        ],
    )
    inspector = sa.inspect(bind)
    if "ix_chapter_audio_runs_deleted_at" not in _index_names(inspector, "chapter_audio_runs"):
        op.create_index("ix_chapter_audio_runs_deleted_at", "chapter_audio_runs", ["deleted_at"])

    # 复合唯一键（R8/R9 运行作用域）：供 outputs/artifacts/双指针复合外键引用
    run_constraints = _constraint_names(bind, "chapter_audio_runs")
    if "uq_chapter_audio_run_scope" not in run_constraints:
        op.create_unique_constraint(
            "uq_chapter_audio_run_scope", "chapter_audio_runs", ["id", "chapter_audio_id"]
        )

    # 双指针复合外键（R10/P1-1，RESTRICT；指向 runs 复合唯一键）
    ca_constraints = _constraint_names(bind, "chapter_audios")
    if "fk_chapter_audio_desired_run" not in ca_constraints:
        op.create_foreign_key(
            "fk_chapter_audio_desired_run",
            "chapter_audios",
            "chapter_audio_runs",
            ["desired_run_id", "id"],
            ["id", "chapter_audio_id"],
            ondelete="RESTRICT",
        )
    if "fk_chapter_audio_published_run" not in ca_constraints:
        op.create_foreign_key(
            "fk_chapter_audio_published_run",
            "chapter_audios",
            "chapter_audio_runs",
            ["published_run_id", "id"],
            ["id", "chapter_audio_id"],
            ondelete="RESTRICT",
        )

    # ── chapter_audio_outputs（§2.4 规则 3/4 run 级输出登记，R8/R13）
    inspector = sa.inspect(bind)
    if not inspector.has_table("chapter_audio_outputs"):
        op.create_table(
            "chapter_audio_outputs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "run_id",
                sa.Integer(),
                sa.ForeignKey("chapter_audio_runs.id", ondelete="RESTRICT"),
                nullable=False,
                unique=True,
            ),
            sa.Column(
                "chapter_audio_id",
                sa.Integer(),
                sa.ForeignKey("chapter_audios.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "audiobook_project_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_projects.id"),
                nullable=False,
            ),
            sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id"), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="staged"),
            sa.Column("file_status", sa.String(length=16), nullable=False, server_default="present"),
            sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("audio_path", sa.String(length=500), nullable=False),
            sa.Column("duration", sa.Float(), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("subtitle_path", sa.String(length=500), nullable=True),
            sa.Column("subtitle_format", sa.String(length=16), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.CheckConstraint(
                "status IN ('staged','published','superseded')", name="ck_chapter_audio_output_status"
            ),
            sa.CheckConstraint(
                "file_status IN ('present','purged','missing')", name="ck_chapter_audio_output_file_status"
            ),
            sa.CheckConstraint(
                "status <> 'published' OR (audio_path IS NOT NULL AND duration IS NOT NULL AND file_size IS NOT NULL)",
                name="ck_chapter_audio_output_published_fields",
            ),
            sa.ForeignKeyConstraint(
                ["run_id", "chapter_audio_id"],
                ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
                name="fk_chapter_audio_output_run_scope",
            ),
        )
        op.create_index("ix_chapter_audio_outputs_chapter_audio_id", "chapter_audio_outputs", ["chapter_audio_id"])
        op.create_index(
            "uq_chapter_audio_output_published",
            "chapter_audio_outputs",
            ["chapter_audio_id"],
            unique=True,
            postgresql_where=sa.text("status = 'published'"),
        )

    # ── scene_edit_revisions / heads（§2.9 双表设计，R7）
    inspector = sa.inspect(bind)
    if not inspector.has_table("scene_edit_revisions"):
        op.create_table(
            "scene_edit_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "audiobook_project_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_projects.id"),
                nullable=False,
            ),
            sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id"), nullable=False),
            sa.Column("base_run_id", sa.Integer(), sa.ForeignKey("chapter_audio_runs.id"), nullable=True),
            sa.Column("parent_revision_id", sa.Integer(), nullable=True),
            sa.Column("edit_type", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("affected_anchors", sa.Text(), nullable=True),
            sa.Column("input_signature", sa.String(length=64), nullable=False),
            sa.Column("revision_hash", sa.String(length=64), nullable=False),
            sa.Column("operator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint("revision_hash", name="uq_scene_edit_revision_hash"),
            sa.UniqueConstraint(
                "id", "audiobook_project_id", "chapter_id", "edit_type", name="uq_scene_edit_revision_scope"
            ),
            sa.ForeignKeyConstraint(
                ["parent_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
                [
                    "scene_edit_revisions.id",
                    "scene_edit_revisions.audiobook_project_id",
                    "scene_edit_revisions.chapter_id",
                    "scene_edit_revisions.edit_type",
                ],
                name="fk_scene_edit_revision_parent_scope",
            ),
        )
        op.create_index(
            "ix_scene_edit_revisions_audiobook_project_id", "scene_edit_revisions", ["audiobook_project_id"]
        )
        op.create_index("ix_scene_edit_revisions_chapter_id", "scene_edit_revisions", ["chapter_id"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("scene_edit_revision_heads"):
        op.create_table(
            "scene_edit_revision_heads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "audiobook_project_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_projects.id"),
                nullable=False,
            ),
            sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id"), nullable=False),
            sa.Column("edit_type", sa.String(length=32), nullable=False),
            sa.Column("head_revision_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "audiobook_project_id", "chapter_id", "edit_type", name="uq_scene_edit_head"
            ),
            sa.ForeignKeyConstraint(
                ["head_revision_id", "audiobook_project_id", "chapter_id", "edit_type"],
                [
                    "scene_edit_revisions.id",
                    "scene_edit_revisions.audiobook_project_id",
                    "scene_edit_revisions.chapter_id",
                    "scene_edit_revisions.edit_type",
                ],
                name="fk_scene_edit_head_revision_scope",
            ),
        )

    # ── scene_audio_artifacts（§2.14，R8/R9 运行作用域）
    inspector = sa.inspect(bind)
    if not inspector.has_table("scene_audio_artifacts"):
        op.create_table(
            "scene_audio_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("artifact_id", sa.String(length=64), nullable=False, unique=True),
            sa.Column(
                "audiobook_project_id",
                sa.Integer(),
                sa.ForeignKey("audiobook_projects.id"),
                nullable=False,
            ),
            sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id"), nullable=False),
            sa.Column(
                "chapter_audio_id", sa.Integer(), sa.ForeignKey("chapter_audios.id"), nullable=False
            ),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("chapter_audio_runs.id"), nullable=False),
            sa.Column("scene_id", sa.String(length=64), nullable=False),
            sa.Column("segment_keys", sa.Text(), nullable=True),
            sa.Column("scene_topology_hash", sa.String(length=64), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
            sa.Column("stored_rel_path", sa.String(length=500), nullable=False),
            sa.Column("source_run_path", sa.String(length=500), nullable=True),
            sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="seed"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="staged"),
            sa.Column("duration_s", sa.Float(), server_default="0.0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('staged','active','superseded')", name="ck_scene_audio_artifact_status"
            ),
            sa.CheckConstraint(
                "source_kind IN ('seed','legacy_fallback','manual')",
                name="ck_scene_audio_artifact_source_kind",
            ),
            sa.ForeignKeyConstraint(
                ["run_id", "chapter_audio_id"],
                ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
                name="fk_scene_audio_artifact_run_scope",
            ),
        )
        for column in ("audiobook_project_id", "chapter_id", "chapter_audio_id"):
            op.create_index(f"ix_scene_audio_artifacts_{column}", "scene_audio_artifacts", [column])
        op.create_index(
            "uq_scene_audio_artifact_run_scene",
            "scene_audio_artifacts",
            ["run_id", "scene_id"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )

    # ── audiobook_task_dispatches（R12/P1-1 父子关系 + 展示投影）
    inspector = sa.inspect(bind)
    if not inspector.has_table("audiobook_task_dispatches"):
        op.create_table(
            "audiobook_task_dispatches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "task_id", sa.Integer(), sa.ForeignKey("audiobook_tasks.id"), nullable=False
            ),
            sa.Column(
                "run_id",
                sa.Integer(),
                sa.ForeignKey("chapter_audio_runs.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("chapter_audio_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(
                ["run_id", "chapter_audio_id"],
                ["chapter_audio_runs.id", "chapter_audio_runs.chapter_audio_id"],
                name="fk_audiobook_task_dispatch_run_scope",
            ),
        )
        op.create_index("ix_audiobook_task_dispatches_task_id", "audiobook_task_dispatches", ["task_id"])

    # ── provider_dispatch_capabilities（R11/P1-3 能力声明）
    inspector = sa.inspect(bind)
    if not inspector.has_table("provider_dispatch_capabilities"):
        op.create_table(
            "provider_dispatch_capabilities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=32), nullable=False, unique=True),
            sa.Column("accepts_idempotency_key", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("returns_request_id", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("supports_request_query", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "has_recoverable_result_url", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

    # ── billing_usage_ledger（R9/P1-3、R11/P1-2 四态、R16/P0、R17/P1-4）
    inspector = sa.inspect(bind)
    if not inspector.has_table("billing_usage_ledger"):
        op.create_table(
            "billing_usage_ledger",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("chapter_audio_runs.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("attempt_key", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("pricing_key", sa.String(length=64), nullable=True),
            sa.Column("provider_request_id", sa.String(length=64), nullable=True),
            sa.Column("encrypted_result_url", sa.Text(), nullable=True),
            sa.Column("result_url_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("usage_kind", sa.String(length=32), nullable=False),
            sa.Column("quantity", sa.Numeric(20, 6), nullable=True),
            sa.Column("unit", sa.String(length=16), nullable=False),
            sa.Column("billing_snapshot_id", sa.String(length=64), nullable=True),
            sa.Column(
                "idempotency_key_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("recovery_method", sa.String(length=32), nullable=True),
            sa.Column("result_url_persisted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("capability_snapshot_json", sa.JSON(), nullable=True),
            sa.Column("commit_stage", sa.String(length=16), nullable=False, server_default="pre_call"),
            sa.Column(
                "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint("run_id", "attempt_key", name="uq_billing_usage_ledger_attempt"),
            sa.CheckConstraint(
                "status IN ('pending','succeeded','confirmed_failed','manual_reconciliation')",
                name="ck_billing_usage_ledger_status",
            ),
            sa.CheckConstraint(
                "usage_kind IN ('seed_render','tts_chars','asr_seconds','remix')",
                name="ck_billing_usage_ledger_usage_kind",
            ),
            sa.CheckConstraint(
                "status <> 'succeeded' OR (quantity IS NOT NULL AND quantity > 0 "
                "AND pricing_key IS NOT NULL AND billing_snapshot_id IS NOT NULL)",
                name="ck_billing_usage_ledger_succeeded_fields",
            ),
            sa.CheckConstraint("unit IN ('second','char')", name="ck_billing_usage_ledger_unit"),
            sa.CheckConstraint(
                "commit_stage IN ('pre_call','post_call','result_persisted')",
                name="ck_billing_usage_ledger_commit_stage",
            ),
        )
        op.create_index("ix_billing_usage_ledger_run_id", "billing_usage_ledger", ["run_id"])
        op.create_index(
            "uq_billing_usage_ledger_dedup",
            "billing_usage_ledger",
            ["run_id", "provider", "provider_request_id", "usage_kind"],
            unique=True,
            postgresql_where=sa.text("provider_request_id IS NOT NULL"),
        )

    # ── ledger_reconciliation_audits（R16/P2-1 完整约束模型，append-only）
    inspector = sa.inspect(bind)
    if not inspector.has_table("ledger_reconciliation_audits"):
        op.create_table(
            "ledger_reconciliation_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "ledger_id",
                sa.Integer(),
                sa.ForeignKey("billing_usage_ledger.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "from_status",
                sa.String(length=32),
                nullable=False,
                server_default="manual_reconciliation",
            ),
            sa.Column("to_status", sa.String(length=32), nullable=False),
            sa.Column("operator_user_id", sa.Integer(), nullable=False),
            sa.Column("operator_username", sa.String(length=64), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("confirmed_quantity", sa.Numeric(20, 6), nullable=True),
            sa.Column("previous_provider_request_id", sa.String(length=64), nullable=True),
            sa.Column("new_provider_request_id", sa.String(length=64), nullable=True),
            sa.Column("previous_commit_stage", sa.String(length=16), nullable=True),
            sa.Column("new_commit_stage", sa.String(length=16), nullable=True),
            sa.Column("recovery_method", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column(
                "reconciled_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "from_status = 'manual_reconciliation'", name="ck_ledger_reconciliation_audits_from"
            ),
            sa.CheckConstraint(
                "to_status IN ('succeeded','confirmed_failed')", name="ck_ledger_reconciliation_audits_to"
            ),
            sa.CheckConstraint(
                "to_status <> 'succeeded' OR (confirmed_quantity IS NOT NULL AND confirmed_quantity > 0)",
                name="ck_ledger_reconciliation_audits_quantity",
            ),
            sa.CheckConstraint(
                "to_status <> 'confirmed_failed' OR confirmed_quantity IS NULL",
                name="ck_ledger_reconciliation_audits_quantity_null",
            ),
            sa.CheckConstraint(
                "previous_commit_stage IS NULL OR previous_commit_stage IN ('pre_call','post_call','result_persisted')",
                name="ck_ledger_reconciliation_audits_prev_stage",
            ),
            sa.CheckConstraint(
                "new_commit_stage IS NULL OR new_commit_stage IN ('pre_call','post_call','result_persisted')",
                name="ck_ledger_reconciliation_audits_new_stage",
            ),
            sa.CheckConstraint(
                "to_status <> 'succeeded' OR (new_commit_stage IS NOT NULL AND previous_commit_stage IS NOT NULL "
                "AND CASE new_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END "
                ">= CASE previous_commit_stage WHEN 'pre_call' THEN 1 WHEN 'post_call' THEN 2 ELSE 3 END)",
                name="ck_ledger_reconciliation_audits_stage_monotonic",
            ),
            sa.CheckConstraint(
                "recovery_method IN ('manual')", name="ck_ledger_reconciliation_audits_recovery"
            ),
        )
        op.create_index(
            "ix_ledger_reconciliation_audits_ledger_id", "ledger_reconciliation_audits", ["ledger_id"]
        )

    # ── append-only 数据库级保护（R19/P2-2 推荐 trigger 方案）
    bind.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION trg_fn_ledger_reconciliation_audits_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'ledger_reconciliation_audits is append-only (R19/P2-1)';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ledger_reconciliation_audits_append_only'
                ) THEN
                    CREATE TRIGGER trg_ledger_reconciliation_audits_append_only
                    BEFORE UPDATE OR DELETE ON ledger_reconciliation_audits
                    FOR EACH ROW EXECUTE FUNCTION trg_fn_ledger_reconciliation_audits_append_only();
                END IF;
            END $$;
            """
        )
    )
    bind.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION trg_fn_scene_edit_revisions_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'scene_edit_revisions is append-only (GUIDE §2.9)';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_scene_edit_revisions_append_only'
                ) THEN
                    CREATE TRIGGER trg_scene_edit_revisions_append_only
                    BEFORE UPDATE OR DELETE ON scene_edit_revisions
                    FOR EACH ROW EXECUTE FUNCTION trg_fn_scene_edit_revisions_append_only();
                END IF;
            END $$;
            """
        )
    )

    # ── audiobook_tasks.status 扩容 + 两阶段 CHECK 第一步（R14/P1-b）
    bind.execute(sa.text("ALTER TABLE audiobook_tasks ALTER COLUMN status TYPE VARCHAR(32)"))
    unexpected = bind.execute(
        sa.text("SELECT DISTINCT status FROM audiobook_tasks WHERE status IS NOT NULL")
    )
    unexpected_values = {
        str(row[0]) for row in unexpected if str(row[0]) not in _TASK_STATUS_STAGE1_VALUES
    }
    if unexpected_values:
        raise RuntimeError(
            "audiobook_tasks.status contains values outside stage-1 CHECK domain; "
            f"clean up before applying CHECK: {sorted(unexpected_values)}"
        )
    task_constraints = _constraint_names(bind, "audiobook_tasks")
    if "ck_audiobook_tasks_status_stage1" not in task_constraints:
        op.create_check_constraint(
            "ck_audiobook_tasks_status_stage1",
            "audiobook_tasks",
            "status IN ('pending','running','completed','failed','cancelled',"
            "'completed_with_partial_failure','pause_requested','paused')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for trigger, table in (
        ("trg_ledger_reconciliation_audits_append_only", "ledger_reconciliation_audits"),
        ("trg_scene_edit_revisions_append_only", "scene_edit_revisions"),
    ):
        if inspector.has_table(table):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS trg_fn_ledger_reconciliation_audits_append_only()"))
    bind.execute(sa.text("DROP FUNCTION IF EXISTS trg_fn_scene_edit_revisions_append_only()"))

    if inspector.has_table("audiobook_tasks"):
        constraints = _constraint_names(bind, "audiobook_tasks")
        if "ck_audiobook_tasks_status_stage1" in constraints:
            op.drop_constraint("ck_audiobook_tasks_status_stage1", "audiobook_tasks", type_="check")
        bind.execute(sa.text("ALTER TABLE audiobook_tasks ALTER COLUMN status TYPE VARCHAR(20)"))

    for table in (
        "ledger_reconciliation_audits",
        "billing_usage_ledger",
        "provider_dispatch_capabilities",
        "audiobook_task_dispatches",
        "scene_audio_artifacts",
        "scene_edit_revision_heads",
        "scene_edit_revisions",
        "chapter_audio_outputs",
    ):
        if sa.inspect(bind).has_table(table):
            op.drop_table(table)

    if sa.inspect(bind).has_table("chapter_audios"):
        constraints = _constraint_names(bind, "chapter_audios")
        for name in ("fk_chapter_audio_published_run", "fk_chapter_audio_desired_run"):
            if name in constraints:
                op.drop_constraint(name, "chapter_audios", type_="foreignkey")
        columns = _column_names(sa.inspect(bind), "chapter_audios")
        for column in (
            "source_provenance_json",
            "source_script_review_version",
            "source_script_hash",
            "source_chapter_audio_id",
            "source_audiobook_project_id",
            "published_provenance",
            "published_input_signature",
            "published_run_id",
            "desired_run_id",
            "render_status_detail",
            "render_status",
            "script_review_version",
        ):
            if column in columns:
                op.drop_column("chapter_audios", column)

    if sa.inspect(bind).has_table("chapter_audio_runs"):
        constraints = _constraint_names(bind, "chapter_audio_runs")
        if "uq_chapter_audio_run_scope" in constraints:
            op.drop_constraint("uq_chapter_audio_run_scope", "chapter_audio_runs", type_="unique")
        indexes = _index_names(sa.inspect(bind), "chapter_audio_runs")
        if "ix_chapter_audio_runs_deleted_at" in indexes:
            op.drop_index("ix_chapter_audio_runs_deleted_at", table_name="chapter_audio_runs")
        columns = _column_names(sa.inspect(bind), "chapter_audio_runs")
        for column in (
            "deleted_at",
            "billing_account_user_id",
            "billing_finalized_at",
            "result_render_detail",
            "result_render_status",
            "lease_expires_at",
            "claimed_at",
            "claim_token",
            "dispatched_at",
            "dispatch_claimed_at",
            "dispatch_claim_token",
            "next_dispatch_at",
            "dispatch_attempts",
            "predecessor_run_id",
            "dispatch_status",
            "input_signature",
            "revision_set_hash",
            "run_input_snapshot",
            "engine_mode_snapshot",
            "chapter_audio_id",
        ):
            if column in columns:
                op.drop_column("chapter_audio_runs", column)

    if sa.inspect(bind).has_table("audiobook_projects"):
        indexes = _index_names(sa.inspect(bind), "audiobook_projects")
        if "ix_audiobook_projects_engine_config_fingerprint" in indexes:
            op.drop_index(
                "ix_audiobook_projects_engine_config_fingerprint", table_name="audiobook_projects"
            )
        columns = _column_names(sa.inspect(bind), "audiobook_projects")
        for column in (
            "snapshot_status",
            "engine_config_fingerprint",
            "engine_config_snapshot",
            "engine_mode",
        ):
            if column in columns:
                op.drop_column("audiobook_projects", column)
