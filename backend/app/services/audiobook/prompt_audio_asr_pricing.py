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


# qwen-audio-3.1-asr-flash 不按音频秒数计价，而是按输入/输出 Token 计价：
# 0.8 元/百万输入 Token、2.7 元/百万输出 Token（百炼「千问Audio」刊例，2026-10-11 核对）。
# 官方折算规则：1 秒音频 = 25 Token，不足 1 秒按 25 Token 计。
# 输出侧按中文朗读实测约 6 Token/秒估算，合计 25×0.8 + 6×2.7 = 36.2 元/百万 Token
# ≈ 3.62e-5 元/秒；成本闸门保守取 4.0e-5 元/秒，宁可高估也不放过超额调用。
_PUBLIC_POSTPAID_PRICES = {
    ("qwen_audio_asr_flash", "qwen-audio-3.1-asr-flash"): PromptAudioAsrPricing(
        provider="qwen_audio_asr_flash",
        model="qwen-audio-3.1-asr-flash",
        yuan_per_second=0.00004,
        pricing_source="aliyun_model_studio_qwen_audio_asr_token_price_2026-10-11",
        pricing_basis="derived_from_token_price",
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
