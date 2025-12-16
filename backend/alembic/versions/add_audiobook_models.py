"""add audiobook models

Revision ID: add_audiobook_models
Revises: 
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_audiobook_models'
down_revision = None  # 需要设置为最新的revision
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建有声书项目表
    op.create_table(
        'audiobook_projects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('tts_provider', sa.String(length=20), nullable=True),
        sa.Column('voice_mapping', sa.JSON(), nullable=True),
        sa.Column('enable_cache', sa.Boolean(), nullable=True),
        sa.Column('total_chapters', sa.Integer(), nullable=True),
        sa.Column('completed_chapters', sa.Integer(), nullable=True),
        sa.Column('failed_chapters', sa.Integer(), nullable=True),
        sa.Column('total_duration', sa.Float(), nullable=True),
        sa.Column('total_size', sa.Integer(), nullable=True),
        sa.Column('total_cost', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audiobook_projects_id'), 'audiobook_projects', ['id'], unique=False)

    # 创建章节音频表
    op.create_table(
        'chapter_audios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audiobook_project_id', sa.Integer(), nullable=False),
        sa.Column('chapter_id', sa.Integer(), nullable=False),
        sa.Column('audio_path', sa.String(length=500), nullable=True),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('segment_count', sa.Integer(), nullable=True),
        sa.Column('dialogue_count', sa.Integer(), nullable=True),
        sa.Column('narration_count', sa.Integer(), nullable=True),
        sa.Column('character_count', sa.Integer(), nullable=True),
        sa.Column('generation_time', sa.Float(), nullable=True),
        sa.Column('tts_cost', sa.Float(), nullable=True),
        sa.Column('cache_hit_rate', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['audiobook_project_id'], ['audiobook_projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chapter_audios_id'), 'chapter_audios', ['id'], unique=False)


def downgrade() -> None:
    # 删除表
    op.drop_index(op.f('ix_chapter_audios_id'), table_name='chapter_audios')
    op.drop_table('chapter_audios')
    op.drop_index(op.f('ix_audiobook_projects_id'), table_name='audiobook_projects')
    op.drop_table('audiobook_projects')
