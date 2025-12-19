"""add script fields to chapter audios

Revision ID: add_script_fields
Revises: add_audiobook_models
Create Date: 2025-12-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_script_fields'
down_revision = 'add_audio_config_to_projects'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加任务ID字段
    op.add_column('chapter_audios', sa.Column('task_id', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_chapter_audios_task_id'), 'chapter_audios', ['task_id'], unique=False)
    
    # 添加剧本和评审字段
    op.add_column('chapter_audios', sa.Column('script_json', sa.Text(), nullable=True))
    op.add_column('chapter_audios', sa.Column('script_review_json', sa.Text(), nullable=True))
    op.add_column('chapter_audios', sa.Column('script_status', sa.String(length=20), nullable=True, server_default='pending'))
    op.add_column('chapter_audios', sa.Column('final_audio_review_json', sa.Text(), nullable=True))


def downgrade() -> None:
    # 删除添加的字段
    op.drop_column('chapter_audios', 'final_audio_review_json')
    op.drop_column('chapter_audios', 'script_status')
    op.drop_column('chapter_audios', 'script_review_json')
    op.drop_column('chapter_audios', 'script_json')
    op.drop_index(op.f('ix_chapter_audios_task_id'), table_name='chapter_audios')
    op.drop_column('chapter_audios', 'task_id')
