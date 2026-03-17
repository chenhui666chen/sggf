"""merge_multiple_heads

Revision ID: d1d5ec080e06
Revises: add_project_display_no
Create Date: 2026-03-16 11:18:23.555039

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1d5ec080e06'
down_revision: Union[str, None] = 'add_project_display_no'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
