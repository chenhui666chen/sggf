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
        ("qwen_audio_asr_flash", "qwen-audio-3.1-asr-flash"): (
            0.00004,
            "derived_from_token_price",
        ),
        ("aliyun", "paraformer-v2"): (0.00008, "public_postpaid"),
        ("doubao", "volc.bigasr.auc"): (2.3 / 3600, "public_postpaid"),
        ("doubao", "volc.seedasr.auc"): (0.8 / 3600, "public_postpaid"),
    }

    for identity, (expected_rate, expected_basis) in expected.items():
        pricing = get_prompt_audio_asr_pricing(*identity)
        assert pricing is not None
        assert pricing.yuan_per_second == expected_rate
        assert pricing.pricing_basis == expected_basis
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


def test_qwen_audio_asr_second_price_is_derived_from_token_rates() -> None:
    """3.1 不按秒计价：秒价必须由官方 Token 折算规则推出，且只能往高估不能低估。

    官方规则（百炼模型价格「千问Audio」，2026-10-11 核对）：1 秒音频 = 25 Token，
    不足 1 秒按 25 Token 计；刊例 0.8 元/百万输入 Token、2.7 元/百万输出 Token。
    输出侧按中文朗读实测约 6 Token/秒估算。
    """
    from app.services.audiobook.prompt_audio_asr_pricing import (
        get_prompt_audio_asr_pricing,
    )

    pricing = get_prompt_audio_asr_pricing(
        "qwen_audio_asr_flash",
        "qwen-audio-3.1-asr-flash",
    )

    assert pricing is not None
    derived = (25 * 0.8 + 6 * 2.7) / 1_000_000
    assert pricing.yuan_per_second >= derived
    assert pricing.yuan_per_second <= round(derived * 1.5, 6)


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
