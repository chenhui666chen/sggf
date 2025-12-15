"""create project_settings table

Revision ID: create_project_settings_table
Revises: 
Create Date: 2025-12-15

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_project_settings_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """创建 project_settings 表"""
    op.create_table(
        'project_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('concept', sa.Text(), nullable=True),
        sa.Column('world_setting', sa.Text(), nullable=True),
        sa.Column('characters', sa.Text(), nullable=True),
        sa.Column('plot_outline', sa.Text(), nullable=True),
        sa.Column('chapter_draft', sa.Text(), nullable=True),
        sa.Column('review_report', sa.Text(), nullable=True),
        sa.Column('final_version', sa.Text(), nullable=True),
        sa.Column('stage_one_status', sa.String(20), default='pending'),
        sa.Column('stage_two_status', sa.String(20), default='pending'),
        sa.Column('stage_three_status', sa.String(20), default='pending'),
        sa.Column('stage_four_status', sa.String(20), default='pending'),
        sa.Column('stage_five_status', sa.String(20), default='pending'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    
    # 创建索引
    op.create_index('ix_project_settings_project_id', 'project_settings', ['project_id'])


def downgrade():
    """删除 project_settings 表"""
    op.drop_index('ix_project_settings_project_id', table_name='project_settings')
    op.drop_table('project_settings')