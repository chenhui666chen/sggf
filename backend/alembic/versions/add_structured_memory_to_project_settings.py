"""add structured memory fields to project_settings

Revision ID: add_structured_memory_to_project_settings
Revises: d1d5ec080e06
Create Date: 2026-03-17

"""

from alembic import op


revision = "add_structured_memory_to_project_settings"
down_revision = "d1d5ec080e06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add structured memory persistence columns."""
    op.execute(
        """
        ALTER TABLE project_settings
        ADD COLUMN IF NOT EXISTS structured_memory TEXT;
        """
    )

    op.execute(
        """
        ALTER TABLE project_settings
        ADD COLUMN IF NOT EXISTS structured_memory_updated_at TIMESTAMP;
        """
    )


def downgrade() -> None:
    """Remove structured memory persistence columns."""
    op.execute(
        """
        ALTER TABLE project_settings
        DROP COLUMN IF EXISTS structured_memory_updated_at;
        """
    )

    op.execute(
        """
        ALTER TABLE project_settings
        DROP COLUMN IF EXISTS structured_memory;
        """
    )
