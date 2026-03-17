"""add project display number

Revision ID: add_project_display_no
Revises: merge_heads
Create Date: 2026-03-15

"""
from alembic import op
import sqlalchemy as sa


revision = "add_project_display_no"
down_revision = "merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add stable per-user project display numbers."""
    op.add_column("projects", sa.Column("display_no", sa.Integer(), nullable=True))

    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY created_at ASC, id ASC
                ) AS display_no
            FROM projects
        )
        UPDATE projects AS p
        SET display_no = numbered.display_no
        FROM numbered
        WHERE p.id = numbered.id
        """
    )

    op.alter_column("projects", "display_no", nullable=False)
    op.create_unique_constraint(
        "uq_projects_user_display_no",
        "projects",
        ["user_id", "display_no"],
    )


def downgrade() -> None:
    """Remove stable per-user project display numbers."""
    op.drop_constraint("uq_projects_user_display_no", "projects", type_="unique")
    op.drop_column("projects", "display_no")
