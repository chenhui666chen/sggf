"""add audiobook delete audit model

Revision ID: add_audiobook_delete_audit
Revises: add_deleted_at_to_audiobook_models
Create Date: 2025-01-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_audiobook_delete_audit'
down_revision = 'add_deleted_at_to_audiobook_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建有声书删除审计日志表
    op.create_table(
        'audiobook_delete_audits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('delete_type', sa.String(length=20), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('user_name', sa.String(length=100), nullable=True),
        sa.Column('snapshot_json', sa.JSON(), nullable=True),
        sa.Column('delete_reason', sa.Text(), nullable=True),
        sa.Column('file_count', sa.Integer(), nullable=True),
        sa.Column('total_size', sa.Integer(), nullable=True),
        sa.Column('affected_chapters', sa.Integer(), nullable=True),
        sa.Column('affected_tasks', sa.Integer(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=False),
        sa.Column('restored_at', sa.DateTime(), nullable=True),
        sa.Column('restored_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['restored_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audiobook_delete_audits_id'), 'audiobook_delete_audits', ['id'], unique=False)


def downgrade() -> None:
    # 删除表
    op.drop_index(op.f('ix_audiobook_delete_audits_id'), table_name='audiobook_delete_audits')
    op.drop_table('audiobook_delete_audits')
