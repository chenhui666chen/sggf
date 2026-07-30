from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.provider_attempt_ledger import (
    ProviderAttemptLedger,
)
from app.services.audiobook.scene_engine.scene_billing import (
    build_seed_scene_billing_summary,
)


def test_provider_attempt_ledger_is_idempotent_across_instances(tmp_path: Path) -> None:
    ledger_path = tmp_path / "provider-attempts.jsonl"
    first = ProviderAttemptLedger(ledger_path)

    assert first.record(
        {
            "provider_request_id": "request-1",
            "scene_id": "scene_0001",
            "model": "seed-audio-1.0",
            "attempt": 1,
            "original_duration": 12.5,
        }
    ) is True
    assert first.record(
        {
            "provider_request_id": "request-1",
            "scene_id": "scene_0001",
            "model": "seed-audio-1.0",
            "attempt": 1,
            "original_duration": 99.0,
        }
    ) is False

    reopened = ProviderAttemptLedger(ledger_path)

    assert reopened.records() == (
        {
            "provider_request_id": "request-1",
            "scene_id": "scene_0001",
            "model": "seed-audio-1.0",
            "attempt": 1,
            "original_duration": 12.5,
        },
    )
    assert len(ledger_path.read_text(encoding="utf-8").splitlines()) == 1


def test_seed_scene_billing_prefers_deduplicated_provider_attempt_ledger(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN", "0.02")
    attempts = (
        {
            "provider_request_id": "request-1",
            "model": "seed-audio-1.0-multilingual",
            "original_duration": 12.5,
        },
        {
            "provider_request_id": "request-1",
            "model": "seed-audio-1.0-multilingual",
            "original_duration": 12.5,
        },
        {
            "provider_request_id": "request-2",
            "model": "seed-audio-1.0-multilingual",
            "original_duration": 7.5,
        },
    )

    summary = build_seed_scene_billing_summary(
        {"scene_0001": {"billing_duration_s": 999.0}},
        provider_attempts=attempts,
        model="seed-audio-1.0-multilingual",
    )

    assert summary["model"] == "seed-audio-1.0-multilingual"
    assert summary["billable_duration_s"] == 20.0
    assert summary["provider_request_count"] == 2
    assert summary["actual_cost_yuan"] == 0.3333
