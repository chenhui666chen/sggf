"""add epic framework fields to project_settings

Revision ID: add_epic_framework_fields
Revises: 
Create Date: 2025-12-12

为支持长篇框架模式下的框架与细纲分离存储，添加以下字段：
- epic_framework: 存储长篇框架（纯框架结构）
- epic_framework_generated_at: 框架生成时间
- epic_volumes_detail: 存储已扩展的卷细纲（JSON格式）

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_epic_framework_fields'
down_revision = None  # 填写上一个迁移的revision
depends_on = None


def upgrade():
    """添加长篇框架相关字段"""
    # 为 project_settings 表添加新字段
    op.execute("""
        ALTER TABLE project_settings
        ADD COLUMN epic_framework TEXT;
    """)
    
    op.execute("""
        ALTER TABLE project_settings
        ADD COLUMN epic_framework_generated_at TIMESTAMP;
    """)
    
    op.execute("""
        ALTER TABLE project_settings
        ADD COLUMN epic_volumes_detail TEXT;
    """)
    
    print("✅ 已添加 epic_framework, epic_framework_generated_at, epic_volumes_detail 字段")


def downgrade():
    """回滚：删除长篇框架相关字段"""
    op.execute("""
        ALTER TABLE project_settings
        DROP COLUMN IF EXISTS epic_framework;
    """)
    
    op.execute("""
        ALTER TABLE project_settings
        DROP COLUMN IF EXISTS epic_framework_generated_at;
    """)
    
    op.execute("""
        ALTER TABLE project_settings
        DROP COLUMN IF EXISTS epic_volumes_detail;
    """)
    
    print("✅ 已删除长篇框架相关字段")
