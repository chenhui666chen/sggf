"""add character genre_fields_json column

Revision ID: add_character_genre_fields_json
Revises: add_character_role_position
Create Date: 2026-04-10

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_character_genre_fields_json"
down_revision = "correct_character_story_stance_false_positives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "genre_fields_json" not in existing_columns:
        op.add_column(
            "characters",
            sa.Column(
                "genre_fields_json",
                sa.Text(),
                nullable=True,
                comment="题材专属字段(JSON)，键名由 genre_registry 定义",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "genre_fields_json" in existing_columns:
        op.drop_column("characters", "genre_fields_json")
