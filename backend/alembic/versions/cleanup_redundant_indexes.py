"""cleanup redundant indexes

Revision ID: cleanup_redundant_indexes
Revises: add_character_genre_fields_json
Create Date: 2026-04-16

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "cleanup_redundant_indexes"
down_revision = "add_character_genre_fields_json"
branch_labels = None
depends_on = None


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    query = sa.text(
        """
        select 1
        from pg_indexes
        where schemaname = 'public'
          and tablename = :table_name
          and indexname = :index_name
        limit 1
        """
    )
    return bind.execute(query, {"table_name": table_name, "index_name": index_name}).scalar() is not None


def _constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    query = sa.text(
        """
        select 1
        from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        join pg_namespace n on n.oid = t.relnamespace
        where n.nspname = 'public'
          and t.relname = :table_name
          and c.conname = :constraint_name
        limit 1
        """
    )
    return bind.execute(query, {"table_name": table_name, "constraint_name": constraint_name}).scalar() is not None


def _index_is_unique(bind, index_name: str) -> bool:
    query = sa.text(
        """
        select ix.indisunique
        from pg_class i
        join pg_namespace n on n.oid = i.relnamespace
        join pg_index ix on ix.indexrelid = i.oid
        where n.nspname = 'public'
          and i.relname = :index_name
        limit 1
        """
    )
    return bool(bind.execute(query, {"index_name": index_name}).scalar())


def upgrade() -> None:
    """Remove redundant indexes and normalize model_key uniqueness."""

    bind = op.get_bind()

    constraint_name = "uq_model_catalog_entries_model_key"
    unique_index_name = "ix_model_catalog_entries_model_key"

    if not _constraint_exists(bind, "model_catalog_entries", constraint_name):
        if _index_exists(bind, "model_catalog_entries", unique_index_name) and _index_is_unique(bind, unique_index_name):
            op.execute(
                sa.text(
                    """
                    alter table model_catalog_entries
                    add constraint uq_model_catalog_entries_model_key
                    unique using index ix_model_catalog_entries_model_key
                    """
                )
            )
        else:
            op.create_unique_constraint(
                constraint_name,
                "model_catalog_entries",
                ["model_key"],
            )

    redundant_indexes = (
        ("model_catalog_entries", "ix_model_catalog_entries_id", ["id"]),
        ("model_catalog_sources", "ix_model_catalog_sources_id", ["id"]),
        ("user_asset_records", "ix_user_asset_records_id", ["id"]),
        ("model_catalog_entries", unique_index_name, ["model_key"]),
    )

    for table_name, index_name, _columns in redundant_indexes:
        if _index_exists(bind, table_name, index_name):
            op.drop_index(index_name, table_name=table_name)


def downgrade() -> None:
    """Restore indexes removed by this cleanup migration."""

    bind = op.get_bind()

    indexes_to_restore = (
        ("model_catalog_entries", "ix_model_catalog_entries_id", ["id"]),
        ("model_catalog_sources", "ix_model_catalog_sources_id", ["id"]),
        ("user_asset_records", "ix_user_asset_records_id", ["id"]),
        ("model_catalog_entries", "ix_model_catalog_entries_model_key", ["model_key"]),
    )

    for table_name, index_name, columns in indexes_to_restore:
        if not _index_exists(bind, table_name, index_name):
            op.create_index(index_name, table_name, columns, unique=False)
