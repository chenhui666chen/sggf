"""模型中心数据库同步服务。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.model_catalog import ModelCatalogEntry

SYNC_FIELDS = (
    "name",
    "provider",
    "category",
    "subcategory",
    "model_family",
    "config_source",
    "status",
    "summary",
    "recommended_scenarios",
    "limitations",
    "integration_notes",
    "documentation_url",
    "source_urls",
    "tags",
    "modalities",
    "capabilities_json",
    "constraints_json",
    "performance_json",
    "routing_json",
    "default_params_json",
    "raw_config_json",
    "total_source_count",
)


def sync_model_catalog_entries(
    db: Session,
    payloads: list[dict[str, Any]],
    *,
    prune_stale: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    existing_entries = {
        str(entry.model_key).strip(): entry
        for entry in db.query(ModelCatalogEntry).all()
        if str(getattr(entry, "model_key", "")).strip()
    }

    created = 0
    updated = 0
    expected_keys = {str(payload["model_key"]).strip() for payload in payloads}

    for payload in payloads:
        model_key = str(payload["model_key"]).strip()
        entry = existing_entries.get(model_key)
        if entry is None:
            db.add(
                ModelCatalogEntry(
                    **payload,
                    last_synced_at=current_time,
                    last_verified_at=None,
                )
            )
            created += 1
            continue

        for field in SYNC_FIELDS:
            setattr(entry, field, payload[field])

        if not entry.verification_status:
            entry.verification_status = "pending"
        if not entry.verification_scope:
            entry.verification_scope = "bootstrap_pending"
        if entry.verification_score is None:
            entry.verification_score = 0.0
        if not entry.verification_notes:
            entry.verification_notes = payload.get("verification_notes")
        entry.last_synced_at = current_time
        updated += 1

    stale_model_keys = sorted(set(existing_entries) - expected_keys)
    deleted = 0
    if prune_stale:
        for model_key in stale_model_keys:
            db.delete(existing_entries[model_key])
            deleted += 1

    return {
        "total": len(payloads),
        "created": created,
        "updated": updated,
        "stale_count": len(stale_model_keys),
        "stale_model_keys": stale_model_keys,
        "deleted": deleted,
        "prune_stale": prune_stale,
    }
