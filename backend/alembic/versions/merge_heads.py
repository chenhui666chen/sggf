"""merge heads

Revision ID: merge_heads
Revises: add_admin_rbac, add_audiobook_delete_audit, add_book_parser_tables, add_deleted_at_to_chapters, add_dreamweaver_run_events, add_epic_framework_fields, add_phone_field, add_script_fields, create_project_settings_table
Create Date: 2026-03-13

"""
from alembic import op
import sqlalchemy as sa


revision = 'merge_heads'
down_revision = None
branch_labels = None
depends_on = [
    'add_admin_rbac',
    'add_audiobook_delete_audit',
    'add_book_parser_tables',
    'add_deleted_at_to_chapters',
    'add_dreamweaver_run_events',
    'add_epic_framework_fields',
    'add_phone_field',
    'add_script_fields',
    'create_project_settings_table',
]


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
