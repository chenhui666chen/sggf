"""add chapter summary fields to existing table

Revision ID: add_chapter_summary_fields_to_existing_table
Revises: add_chapter_summary
Create Date: 2025-10-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_chapter_summary_fields_to_existing_table'
down_revision = 'add_chapter_summary'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加章节摘要字段到现有表"""
    # 检查chapters表是否存在
    conn = op.get_bind()
    
    # 检查表是否存在
    result = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='chapters'")).fetchone()
    if not result:
        # 如果表不存在，创建表结构（包含新字段）
        op.create_table(
            'chapters',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('chapter_number', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('summary', sa.Text(), nullable=True, comment='核心事件摘要'),
            sa.Column('summary_data', sa.Text(), nullable=True, comment='结构化摘要数据(JSON)'),
            sa.Column('status', sa.String(50), default='draft'),
            sa.Column('word_count', sa.Integer(), default=0),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE')
        )
    else:
        # 如果表存在，添加新字段
        try:
            # 添加 summary 字段 - 核心事件摘要
            op.add_column('chapters', sa.Column('summary', sa.Text(), nullable=True, comment='核心事件摘要'))
        except Exception as e:
            print(f"⚠️ 添加 summary 字段时出错（可能已存在）: {e}")
        
        try:
            # 添加 summary_data 字段 - 结构化摘要数据(JSON)
            op.add_column('chapters', sa.Column('summary_data', sa.Text(), nullable=True, comment='结构化摘要数据(JSON)'))
        except Exception as e:
            print(f"⚠️ 添加 summary_data 字段时出错（可能已存在）: {e}")


def downgrade() -> None:
    """删除章节摘要字段"""
    # 检查字段是否存在再删除
    conn = op.get_bind()
    
    # 检查 summary 字段是否存在
    try:
        result = conn.execute(sa.text("PRAGMA table_info(chapters)")).fetchall()
        column_names = [row[1] for row in result]
        
        if 'summary' in column_names:
            op.drop_column('chapters', 'summary')
        
        if 'summary_data' in column_names:
            op.drop_column('chapters', 'summary_data')
    except Exception as e:
        print(f"⚠️ 删除字段时出错: {e}")
