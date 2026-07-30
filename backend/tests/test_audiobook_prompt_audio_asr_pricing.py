from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


def test_prompt_audio_asr_public_postpaid_prices_use_verified_sources() -> None:
    from app.services.audiobook.prompt_audio_asr_pricing import (
        estimate_prompt_audio_asr_cost_yuan,
        get_prompt_audio_asr_pricing,
    )

    expected = {
        ("funasr_flash", "fun-asr-flash-2026-06-15"): 0.00022,
        ("aliyun", "paraformer-v2"): 0.00008,
        ("doubao", "volc.bigasr.auc"): 2.3 / 3600,
        ("doubao", "volc.seedasr.auc"): 0.8 / 3600,
    }

    for identity, expected_rate in expected.items():
        pricing = get_prompt_audio_asr_pricing(*identity)
        assert pricing is not None
        assert pricing.yuan_per_second == expected_rate
        assert pricing.pricing_basis == "public_postpaid"
        assert pricing.pricing_source
        assert estimate_prompt_audio_asr_cost_yuan(
            provider=identity[0],
            model=identity[1],
            duration_seconds=120,
        ) == round(expected_rate * 120, 6)

    assert get_prompt_audio_asr_pricing("unknown", "unknown") is None
    assert (
        estimate_prompt_audio_asr_cost_yuan(
            provider="unknown",
            model="unknown",
            duration_seconds=120,
        )
        is None
    )


def test_prompt_audio_asr_budget_policy_reads_environment(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_pricing import (
        load_prompt_audio_asr_budget_policy,
    )

    monkeypatch.setenv("PROMPT_AUDIO_ASR_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PROMPT_AUDIO_ASR_MAX_ATTEMPTS_PER_SCENE", "1")
    monkeypatch.setenv("PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE", "0.05")

    policy = load_prompt_audio_asr_budget_policy()

    assert policy.timeout_seconds == 45.0
    assert policy.max_attempts_per_scene == 1
    assert policy.max_cost_yuan_per_scene == 0.05


def test_prompt_audio_asr_budget_policy_rejects_non_finite_values(monkeypatch) -> None:
    from app.services.audiobook.prompt_audio_asr_pricing import (
        load_prompt_audio_asr_budget_policy,
    )

    monkeypatch.setenv("PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE", "nan")

    with pytest.raises(ValueError, match="PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE"):
        load_prompt_audio_asr_budget_policy()
