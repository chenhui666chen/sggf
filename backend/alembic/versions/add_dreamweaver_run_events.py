"""add dreamweaver run events table

Revision ID: add_dreamweaver_run_events
Revises: add_third_party_login_fields
Create Date: 2026-02-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_dreamweaver_run_events"
down_revision = "add_third_party_login_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """create dreamweaver_run_events"""
    op.create_table(
        "dreamweaver_run_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_dreamweaver_run_events_run_id"), "dreamweaver_run_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_dreamweaver_run_events_project_id"), "dreamweaver_run_events", ["project_id"], unique=False)
    op.create_index(op.f("ix_dreamweaver_run_events_user_id"), "dreamweaver_run_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_dreamweaver_run_events_created_at"), "dreamweaver_run_events", ["created_at"], unique=False)


def downgrade() -> None:
    """drop dreamweaver_run_events"""
    op.drop_index(op.f("ix_dreamweaver_run_events_created_at"), table_name="dreamweaver_run_events")
    op.drop_index(op.f("ix_dreamweaver_run_events_user_id"), table_name="dreamweaver_run_events")
    op.drop_index(op.f("ix_dreamweaver_run_events_project_id"), table_name="dreamweaver_run_events")
    op.drop_index(op.f("ix_dreamweaver_run_events_run_id"), table_name="dreamweaver_run_events")
    op.drop_table("dreamweaver_run_events")
