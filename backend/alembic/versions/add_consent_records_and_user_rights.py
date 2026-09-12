"""数据权利（P2 4.3）：users 软删除/同意版本字段 + consent_records 同意记录表

- users 增加：deleted_at（注销软删除时间戳，5.3 冷静期后匿名化）、consent_version（5.2 当前同意版本）；
- 新表 consent_records：版本化、可审计的同意记录（注销后永久保留，不设级联删除）；
- 均不涉及存量数据重写，可安全在任意环境执行。

Revision ID: add_consent_records_and_user_rights
Revises: add_audit_logs
Create Date: 2026-09-01
"""
import sqlalchemy as sa
from alembic import op


revision = "add_consent_records_and_user_rights"
down_revision = "add_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("consent_version", sa.String(length=20), nullable=True))

    op.create_table(
        "consent_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("consent_type", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_consent_records_id"), "consent_records", ["id"], unique=False)
    op.create_index(op.f("ix_consent_records_user_id"), "consent_records", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_consent_records_consent_type"), "consent_records", ["consent_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_consent_records_consent_type"), table_name="consent_records")
    op.drop_index(op.f("ix_consent_records_user_id"), table_name="consent_records")
    op.drop_index(op.f("ix_consent_records_id"), table_name="consent_records")
    op.drop_table("consent_records")
    op.drop_column("users", "consent_version")
    op.drop_column("users", "deleted_at")
