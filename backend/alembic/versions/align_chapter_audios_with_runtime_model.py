"""align chapter audios with runtime model

Revision ID: align_chapter_audios_with_runtime_model
Revises: remove_legacy_chapter_audio_runtime_fields
Create Date: 2026-04-23

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "align_chapter_audios_with_runtime_model"
down_revision = "remove_legacy_chapter_audio_runtime_fields"
branch_labels = None
depends_on = None


def _get_column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Backfill legacy schema drift so chapter_audios matches the ORM model."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("chapter_audios"):
        return

    column_names = _get_column_names(inspector, "chapter_audios")

    with op.batch_alter_table("chapter_audios") as batch_op:
        if "narration_style" not in column_names:
            batch_op.add_column(
                sa.Column(
                    "narration_style",
                    sa.String(length=50),
                    nullable=True,
                    server_default=sa.text("'professional'"),
                )
            )
        if "narration_style_prompt" not in column_names:
            batch_op.add_column(sa.Column("narration_style_prompt", sa.Text(), nullable=True))
        if "subtitle_path" not in column_names:
            batch_op.add_column(sa.Column("subtitle_path", sa.String(length=500), nullable=True))
        if "subtitle_format" not in column_names:
            batch_op.add_column(
                sa.Column(
                    "subtitle_format",
                    sa.String(length=20),
                    nullable=True,
                    server_default=sa.text("'srt'"),
                )
            )
        if "segment_reviews_json" not in column_names:
            batch_op.add_column(sa.Column("segment_reviews_json", sa.Text(), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE chapter_audios
            SET narration_style = :default_style
            WHERE narration_style IS NULL
            """
        ),
        {"default_style": "professional"},
    )
    bind.execute(
        sa.text(
            """
            UPDATE chapter_audios
            SET subtitle_format = :default_format
            WHERE subtitle_format IS NULL
            """
        ),
        {"default_format": "srt"},
    )


def downgrade() -> None:
    """Drop the runtime-model alignment columns from chapter_audios."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("chapter_audios"):
        return

    column_names = _get_column_names(inspector, "chapter_audios")

    with op.batch_alter_table("chapter_audios") as batch_op:
        if "segment_reviews_json" in column_names:
            batch_op.drop_column("segment_reviews_json")
        if "subtitle_format" in column_names:
            batch_op.drop_column("subtitle_format")
        if "subtitle_path" in column_names:
            batch_op.drop_column("subtitle_path")
        if "narration_style_prompt" in column_names:
            batch_op.drop_column("narration_style_prompt")
        if "narration_style" in column_names:
            batch_op.drop_column("narration_style")
