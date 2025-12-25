"""add deleted_at to chapters table

Revision ID: add_deleted_at_to_chapters
Revises: add_chapter_summary_fields_to_existing_table
Create Date: 2025-01-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_deleted_at_to_chapters'
down_revision = 'initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为chapters表添加deleted_at字段以支持软删除功能"""
    # 检查chapters表是否存在
    conn = op.get_bind()
    
    # 检查表是否存在
    result = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='chapters'")).fetchone()
    if not result:
        print("⚠️ chapters表不存在，跳过添加deleted_at字段")
        return
    
    # 检查deleted_at字段是否已存在
    try:
        result = conn.execute(sa.text("PRAGMA table_info(chapters)")).fetchall()
        column_names = [row[1] for row in result]
        
        if 'deleted_at' in column_names:
            print("⚠️ chapters表的deleted_at字段已存在，跳过添加")
            return
    except Exception as e:
        print(f"⚠️ 检查字段时出错: {e}")
    
    # 添加 deleted_at 字段
    try:
        op.add_column(
            'chapters',
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='软删除时间')
        )
        print("✅ 成功为chapters表添加deleted_at字段")
    except Exception as e:
        print(f"❌ 添加deleted_at字段时出错: {e}")
        raise


def downgrade() -> None:
    """删除chapters表的deleted_at字段"""
    # 检查字段是否存在再删除
    conn = op.get_bind()
    
    try:
        result = conn.execute(sa.text("PRAGMA table_info(chapters)")).fetchall()
        column_names = [row[1] for row in result]
        
        if 'deleted_at' in column_names:
            op.drop_column('chapters', 'deleted_at')
            print("✅ 成功删除chapters表的deleted_at字段")
        else:
            print("⚠️ chapters表的deleted_at字段不存在，跳过删除")
    except Exception as e:
        print(f"❌ 删除deleted_at字段时出错: {e}")
        raise
