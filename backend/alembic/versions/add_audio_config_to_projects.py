"""add audio_config to projects

Revision ID: add_audio_config_to_projects
Revises: add_genre_planning_to_projects
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_audio_config_to_projects"
down_revision = "add_genre_planning_to_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加项目级音频配置字段到 projects 表"""
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "audio_config",
                sa.Text(),
                nullable=True,
                comment="项目级音频配置(JSON)",
            )
        )


def downgrade() -> None:
    """移除项目级音频配置字段"""
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("audio_config")
