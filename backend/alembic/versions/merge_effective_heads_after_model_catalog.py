"""merge effective heads after model catalog

Revision ID: merge_effective_heads_after_model_catalog
Revises: add_admin_rbac, add_audiobook_delete_audit, add_book_parser_tables, add_deleted_at_to_chapters, add_dreamweaver_run_events, add_epic_framework_fields, add_model_catalog_tables, add_phone_field, add_script_fields, create_project_settings_table
Create Date: 2026-03-20

"""

from __future__ import annotations


revision = "merge_effective_heads_after_model_catalog"
down_revision = (
    "add_admin_rbac",
    "add_audiobook_delete_audit",
    "add_book_parser_tables",
    "add_deleted_at_to_chapters",
    "add_dreamweaver_run_events",
    "add_epic_framework_fields",
    "add_model_catalog_tables",
    "add_phone_field",
    "add_script_fields",
    "create_project_settings_table",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
