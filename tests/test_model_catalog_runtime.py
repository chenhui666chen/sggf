from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def test_runtime_signal_blocks_recent_failed_model(monkeypatch, tmp_path) -> None:
    from core.model_catalog_runtime import ModelCatalogRuntimeIndex

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "demo-model": {
                        "verification_status": "failed",
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    index = ModelCatalogRuntimeIndex()
    signal = index.get_signal("demo-model")

    assert signal.blocked is True
    assert signal.stale is False
    assert signal.reason == "catalog_verification_failed_recent"
    assert signal.priority == -1
    assert signal.age_hours is not None


def test_runtime_signal_does_not_block_stale_failed_model(monkeypatch, tmp_path) -> None:
    from core.model_catalog_runtime import ModelCatalogRuntimeIndex

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "demo-model": {
                        "verification_status": "failed",
                        "last_verified_at": (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))
    monkeypatch.setenv("MODEL_CATALOG_MAX_SIGNAL_AGE_HOURS", "1")
    monkeypatch.setenv("MODEL_CATALOG_FAILURE_BLOCK_HOURS", "72")

    index = ModelCatalogRuntimeIndex()
    signal = index.get_signal("demo-model")

    assert signal.blocked is False
    assert signal.stale is True
    assert signal.reason == "catalog_signal_stale"
    assert signal.priority == 0
    assert signal.age_hours is not None


def test_runtime_index_reads_task_constraints(monkeypatch, tmp_path) -> None:
    from core.model_catalog_runtime import ModelCatalogRuntimeIndex

    snapshot_path = tmp_path / "model_catalog_runtime.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "demo-model": {
                        "verification_status": "verified",
                        "last_verified_at": datetime.now(timezone.utc).isoformat(),
                        "task_constraints": {
                            "duration_values": [3.0, 5.0, 10.0],
                            "ratio_values": ["16:9", "1:1"],
                            "min_width": 480,
                            "max_width": 1920,
                            "min_height": 480,
                            "max_height": 1080,
                        },
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_CATALOG_RUNTIME_SNAPSHOT_PATH", str(snapshot_path))

    index = ModelCatalogRuntimeIndex()
    constraints = index.get_task_constraints("demo-model")

    assert constraints["duration_values"] == [3.0, 5.0, 10.0]
    assert constraints["ratio_values"] == ["16:9", "1:1"]
    assert constraints["max_width"] == 1920
