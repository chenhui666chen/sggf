"""add chapter audio runs

Revision ID: add_chapter_audio_runs
Revises: rebuild_user_asset_records_local_first
Create Date: 2026-04-19

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_chapter_audio_runs"
down_revision = "rebuild_user_asset_records_local_first"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chapter_audio_runs for audiobook runtime state."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("chapter_audio_runs"):
        return

    op.create_table(
        "chapter_audio_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audiobook_project_id", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("completed_segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tts_model", sa.String(length=120), nullable=True),
        sa.Column("output_format", sa.String(length=20), nullable=True),
        sa.Column("narration_style", sa.String(length=50), nullable=True),
        sa.Column("narration_style_prompt", sa.Text(), nullable=True),
        sa.Column("voice_config_hash", sa.String(length=128), nullable=True),
        sa.Column("audio_fx_hash", sa.String(length=128), nullable=True),
        sa.Column("script_hash", sa.String(length=128), nullable=True),
        sa.Column("resumable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("checkpoint_json", sa.JSON(), nullable=True),
        sa.Column("temp_asset_prefix", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["audiobook_project_id"], ["audiobook_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_chapter_audio_runs_audiobook_project_id",
        "chapter_audio_runs",
        ["audiobook_project_id"],
        unique=False,
    )
    op.create_index(
        "ix_chapter_audio_runs_chapter_id",
        "chapter_audio_runs",
        ["chapter_id"],
        unique=False,
    )
    op.create_index(
        "ix_chapter_audio_runs_celery_task_id",
        "chapter_audio_runs",
        ["celery_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_chapter_audio_runs_expires_at",
        "chapter_audio_runs",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop chapter_audio_runs."""

    op.drop_index("ix_chapter_audio_runs_expires_at", table_name="chapter_audio_runs")
    op.drop_index("ix_chapter_audio_runs_celery_task_id", table_name="chapter_audio_runs")
    op.drop_index("ix_chapter_audio_runs_chapter_id", table_name="chapter_audio_runs")
    op.drop_index("ix_chapter_audio_runs_audiobook_project_id", table_name="chapter_audio_runs")
    op.drop_table("chapter_audio_runs")
