"""Add finite cumulative quotas for invited video API applications."""
from alembic import op
import sqlalchemy as sa

revision = "add_video_api_trial_quota"
down_revision = "add_video_api_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_api_applications", sa.Column(
        "lifetime_task_limit", sa.Integer(), nullable=False, server_default="100"))


def downgrade() -> None:
    op.drop_column("video_api_applications", "lifetime_task_limit")
