"""add video API applications"""
from alembic import op
import sqlalchemy as sa

revision = "add_video_api_applications"
down_revision = "add_chapter_project_number_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_api_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gateway_client_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("plan_code", sa.String(length=40), nullable=False, server_default="standard"),
        sa.Column("rate_limit_per_second", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("burst_capacity", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_active_jobs", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_parallel_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("api_key_prefix", sa.String(length=16), nullable=False),
        sa.Column("daily_budget", sa.Numeric(12, 4), nullable=True),
        sa.Column("monthly_budget", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("gateway_client_id"),
        sa.UniqueConstraint("api_key_hash"),
    )
    op.create_index("ix_video_api_applications_user_id", "video_api_applications", ["user_id"])
    op.create_index("ix_video_api_applications_gateway_client_id", "video_api_applications", ["gateway_client_id"])


def downgrade() -> None:
    op.drop_index("ix_video_api_applications_gateway_client_id", table_name="video_api_applications")
    op.drop_index("ix_video_api_applications_user_id", table_name="video_api_applications")
    op.drop_table("video_api_applications")
