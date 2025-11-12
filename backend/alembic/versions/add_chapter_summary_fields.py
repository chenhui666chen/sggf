"""add chapter summary fields

Revision ID: add_chapter_summary
Revises: 
Create Date: 2025-10-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_chapter_summary'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加章节摘要字段"""
    # 添加 summary 字段 - 核心事件摘要
    op.add_column('chapters', sa.Column('summary', sa.Text(), nullable=True, comment='核心事件摘要'))
    
    # 添加 summary_data 字段 - 结构化摘要数据(JSON)
    op.add_column('chapters', sa.Column('summary_data', sa.Text(), nullable=True, comment='结构化摘要数据(JSON)'))


def downgrade() -> None:
    """删除章节摘要字段"""
    op.drop_column('chapters', 'summary_data')
    op.drop_column('chapters', 'summary')
