"""add character role_position field

Revision ID: add_character_role_position
Revises: add_user_asset_records
Create Date: 2026-04-08

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "add_character_role_position"
down_revision = "add_user_asset_records"
branch_labels = None
depends_on = None


CANONICAL_STANCES = ("主角方", "反派方", "中立方", "亦正亦邪")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "role_position" not in existing_columns:
        op.add_column(
            "characters",
            sa.Column("role_position", sa.String(length=100), nullable=True, comment="角色定位：主角/盟友/导师/对手/情报角色等"),
        )

    canonical_list = ", ".join(f"'{value}'" for value in CANONICAL_STANCES)

    op.execute(
        sa.text(
            f"""
            UPDATE characters
            SET role_position = role
            WHERE role_position IS NULL
              AND role IS NOT NULL
              AND TRIM(role) <> ''
              AND role NOT IN ({canonical_list})
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE characters
            SET role = CASE
                WHEN role LIKE '%亦正亦邪%' THEN '亦正亦邪'
                WHEN role LIKE '%中立%' OR role LIKE '%旁观%' OR role LIKE '%游离%' THEN '中立方'
                WHEN role LIKE '%对手%' OR role LIKE '%反派%' OR role LIKE '%敌%' OR role LIKE '%宿敌%' OR role LIKE '%追杀者%' THEN '反派方'
                WHEN role LIKE '%主角%' OR role LIKE '%盟友%' OR role LIKE '%导师%' OR role LIKE '%同伴%' OR role LIKE '%队友%' OR role LIKE '%支持%' OR role LIKE '%助力%' THEN '主角方'
                ELSE role
            END
            WHERE role IS NOT NULL
              AND TRIM(role) <> ''
              AND role NOT IN ({canonical_list})
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("characters"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("characters")}
    if "role_position" in existing_columns:
        op.drop_column("characters", "role_position")
