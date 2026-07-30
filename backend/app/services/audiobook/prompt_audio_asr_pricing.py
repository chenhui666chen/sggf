"""Verified public postpaid prices for prompt-audio ASR providers."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptAudioAsrPricing:
    provider: str
    model: str
    yuan_per_second: float
    pricing_source: str
    pricing_basis: str = "public_postpaid"


@dataclass(frozen=True)
class PromptAudioAsrBudgetPolicy:
    timeout_seconds: float = 300.0
    max_attempts_per_scene: int = 2
    max_cost_yuan_per_scene: float = 0.2


_PUBLIC_POSTPAID_PRICES = {
    ("funasr_flash", "fun-asr-flash-2026-06-15"): PromptAudioAsrPricing(
        provider="funasr_flash",
        model="fun-asr-flash-2026-06-15",
        yuan_per_second=0.00022,
        pricing_source="aliyun_model_studio_public_price_2026-07-24",
    ),
    ("aliyun", "paraformer-v2"): PromptAudioAsrPricing(
        provider="aliyun",
        model="paraformer-v2",
        yuan_per_second=0.00008,
        pricing_source="aliyun_model_studio_public_price_2026-07-24",
    ),
    ("doubao", "volc.bigasr.auc"): PromptAudioAsrPricing(
        provider="doubao",
        model="volc.bigasr.auc",
        yuan_per_second=2.3 / 3600,
        pricing_source="volcengine_public_postpaid_2026-07-24",
    ),
    ("doubao", "volc.seedasr.auc"): PromptAudioAsrPricing(
        provider="doubao",
        model="volc.seedasr.auc",
        yuan_per_second=0.8 / 3600,
        pricing_source="volcengine_public_postpaid_2026-07-24",
    ),
}


def get_prompt_audio_asr_pricing(
    provider: str,
    model: str,
) -> PromptAudioAsrPricing | None:
    identity = (str(provider or "").strip().lower(), str(model or "").strip())
    return _PUBLIC_POSTPAID_PRICES.get(identity)


def estimate_prompt_audio_asr_cost_yuan(
    *,
    provider: str,
    model: str,
    duration_seconds: float,
) -> float | None:
    pricing = get_prompt_audio_asr_pricing(provider, model)
    if pricing is None:
        return None
    try:
        duration = float(duration_seconds)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return 0.0
    return round(duration * pricing.yuan_per_second, 6)


def load_prompt_audio_asr_budget_policy() -> PromptAudioAsrBudgetPolicy:
    return PromptAudioAsrBudgetPolicy(
        timeout_seconds=_environment_float(
            "PROMPT_AUDIO_ASR_TIMEOUT_SECONDS",
            300.0,
            minimum=0.001,
        ),
        max_attempts_per_scene=_environment_int(
            "PROMPT_AUDIO_ASR_MAX_ATTEMPTS_PER_SCENE",
            2,
            minimum=0,
        ),
        max_cost_yuan_per_scene=_environment_float(
            "PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE",
            0.2,
            minimum=0.0,
        ),
    )


def _environment_float(name: str, default: float, *, minimum: float) -> float:
    raw_value = str(os.getenv(name) or "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _environment_int(name: str, default: int, *, minimum: int) -> int:
    raw_value = str(os.getenv(name) or "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


__all__ = [
    "PromptAudioAsrBudgetPolicy",
    "PromptAudioAsrPricing",
    "estimate_prompt_audio_asr_cost_yuan",
    "get_prompt_audio_asr_pricing",
    "load_prompt_audio_asr_budget_policy",
]
