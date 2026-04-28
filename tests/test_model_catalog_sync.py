from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for candidate in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _make_payload(model_key: str, name: str) -> dict:
    return {
        "model_key": model_key,
        "name": name,
        "provider": "demo-provider",
        "category": "image",
        "subcategory": None,
        "model_family": None,
        "config_source": "models.yaml",
        "status": "active",
        "summary": f"{name} summary",
        "recommended_scenarios": ["demo"],
        "limitations": ["demo-limit"],
        "integration_notes": ["demo-note"],
        "documentation_url": "https://example.com/docs",
        "source_urls": ["https://example.com/docs"],
        "tags": ["image"],
        "modalities": ["text_to_image"],
        "capabilities_json": [],
        "constraints_json": {},
        "performance_json": {},
        "routing_json": {},
        "default_params_json": {},
        "raw_config_json": {"category_label": "图像生成"},
        "verification_status": "pending",
        "verification_scope": "bootstrap_pending",
        "verification_score": 0.0,
        "total_source_count": 1,
        "reachable_source_count": 0,
        "verified_source_count": 0,
        "verification_notes": "pending",
    }


def _build_session():
    from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

    engine = create_engine("sqlite:///:memory:")
    ModelCatalogEntry.__table__.create(engine, checkfirst=True)
    ModelCatalogSource.__table__.create(engine, checkfirst=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return session_factory()


def test_sync_model_catalog_entries_reports_stale_without_pruning() -> None:
    from app.models.model_catalog import ModelCatalogEntry
    from app.services.model_catalog_sync import sync_model_catalog_entries

    db = _build_session()
    try:
        db.add(
            ModelCatalogEntry(
                **{
                    **_make_payload("legacy-model", "Legacy Model"),
                    "verification_status": "verified",
                    "verification_scope": "manual_review",
                    "verification_score": 0.88,
                    "verification_notes": "legacy verified",
                }
            )
        )
        db.add(
            ModelCatalogEntry(
                **{
                    **_make_payload("current-model", "Old Name"),
                    "verification_status": "verified",
                    "verification_scope": "manual_review",
                    "verification_score": 0.93,
                    "verification_notes": "keep status",
                }
            )
        )
        db.commit()

        result = sync_model_catalog_entries(
            db,
            [_make_payload("current-model", "Current Name"), _make_payload("new-model", "New Model")],
            prune_stale=False,
            now=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        )
        db.commit()

        assert result["created"] == 1
        assert result["updated"] == 1
        assert result["stale_count"] == 1
        assert result["deleted"] == 0
        assert result["stale_model_keys"] == ["legacy-model"]

        updated_current = db.query(ModelCatalogEntry).filter_by(model_key="current-model").one()
        assert updated_current.name == "Current Name"
        assert updated_current.verification_status == "verified"
        assert updated_current.verification_scope == "manual_review"
        assert updated_current.verification_score == 0.93
        assert updated_current.verification_notes == "keep status"

        legacy_entry = db.query(ModelCatalogEntry).filter_by(model_key="legacy-model").one_or_none()
        assert legacy_entry is not None
    finally:
        db.close()


def test_sync_model_catalog_entries_can_prune_stale_entries() -> None:
    from app.models.model_catalog import ModelCatalogEntry
    from app.services.model_catalog_sync import sync_model_catalog_entries

    db = _build_session()
    try:
        db.add(ModelCatalogEntry(**_make_payload("legacy-model", "Legacy Model")))
        db.commit()

        result = sync_model_catalog_entries(
            db,
            [_make_payload("current-model", "Current Name")],
            prune_stale=True,
            now=datetime(2026, 4, 28, 12, 0, tzinfo=timezone.utc),
        )
        db.commit()

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["stale_count"] == 1
        assert result["deleted"] == 1
        assert result["stale_model_keys"] == ["legacy-model"]
        assert db.query(ModelCatalogEntry).filter_by(model_key="legacy-model").one_or_none() is None
        assert db.query(ModelCatalogEntry).filter_by(model_key="current-model").one_or_none() is not None
    finally:
        db.close()
