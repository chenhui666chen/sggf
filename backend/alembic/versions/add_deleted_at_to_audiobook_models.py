"""add deleted_at to audiobook models

Revision ID: add_deleted_at_to_audiobook_models
Revises: add_audiobook_models
Create Date: 2025-01-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_deleted_at_to_audiobook_models'
down_revision = 'add_audiobook_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为audiobook_projects表添加deleted_at字段
    op.add_column(
        'audiobook_projects',
        sa.Column('deleted_at', sa.DateTime(), nullable=True)
    )
    op.create_index('ix_audiobook_projects_deleted_at', 'audiobook_projects', ['deleted_at'])
    
    # 为chapter_audios表添加deleted_at字段
    op.add_column(
        'chapter_audios',
        sa.Column('deleted_at', sa.DateTime(), nullable=True)
    )
    op.create_index('ix_chapter_audios_deleted_at', 'chapter_audios', ['deleted_at'])


def downgrade() -> None:
    # 删除索引和字段
    op.drop_index('ix_chapter_audios_deleted_at', table_name='chapter_audios')
    op.drop_column('chapter_audios', 'deleted_at')
    
    op.drop_index('ix_audiobook_projects_deleted_at', table_name='audiobook_projects')
    op.drop_column('audiobook_projects', 'deleted_at')
