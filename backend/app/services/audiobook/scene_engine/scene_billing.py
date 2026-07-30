"""Seed Audio scene billing summaries based on provider billable duration."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.audiobook.project_audio_config import DEFAULT_SEED_AUDIO_MODEL


SEED_AUDIO_MODEL = DEFAULT_SEED_AUDIO_MODEL
DEFAULT_SEED_AUDIO_PRICE_PER_MINUTE_YUAN = 1.0
# 最低计费单位（秒）：0 表示纯线性按秒（当前默认口径）。真实账单确认后改此默认值或设置
# 环境变量 DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S 即可，无需改动结算逻辑。
DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S = 0.0


def resolve_seed_audio_billing_increment_s() -> float:
    """返回按调用向上取整的最低计费单位（秒）；无效或未配置时回退线性口径 0.0。"""
    raw = os.getenv("DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S")
    if raw is None or not str(raw).strip():
        return DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S
    return value


def _quantize_billable_duration(duration: float, increment: float) -> float:
    """把单次调用时长向上取整到最低计费单位；增量<=0 时保持线性原值。

    正时长在启用增量时至少计一个单位，即同时满足“向上取整到增量”和“单次最低一个单位”。
    """
    if not math.isfinite(duration) or duration <= 0:
        return 0.0
    if increment <= 0:
        return duration
    units = math.ceil(duration / increment)
    return round(units * increment, 6)


@dataclass(frozen=True)
class SeedAudioPricing:
    price_per_second_yuan: float
    price_per_minute_yuan: float
    source: str


def resolve_seed_audio_pricing() -> SeedAudioPricing | None:
    return SeedAudioPricing(
        price_per_second_yuan=(
            DEFAULT_SEED_AUDIO_PRICE_PER_MINUTE_YUAN / 60
        ),
        price_per_minute_yuan=DEFAULT_SEED_AUDIO_PRICE_PER_MINUTE_YUAN,
        source="volcengine_public_postpaid",
    )


def get_seed_audio_price_per_second_yuan() -> float | None:
    pricing = resolve_seed_audio_pricing()
    return pricing.price_per_second_yuan if pricing is not None else None


def build_seed_scene_billing_summary(
    checkpoints: Mapping[str, Mapping[str, Any]] | None,
    *,
    provider_attempts: Sequence[Mapping[str, Any]] | None = None,
    model: str = SEED_AUDIO_MODEL,
) -> dict[str, Any]:
    total_duration = 0.0
    request_ids: set[str] = set()
    deduplicated_attempts: dict[str, Mapping[str, Any]] = {}
    increment = resolve_seed_audio_billing_increment_s()
    for attempt in provider_attempts or ():
        if not isinstance(attempt, Mapping):
            continue
        request_id = str(
            attempt.get("provider_request_id") or attempt.get("request_id") or ""
        ).strip()
        if request_id and request_id not in deduplicated_attempts:
            deduplicated_attempts[request_id] = attempt

    if deduplicated_attempts:
        for request_id, attempt in deduplicated_attempts.items():
            request_ids.add(request_id)
            try:
                duration = float(attempt.get("original_duration") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if math.isfinite(duration) and duration > 0:
                total_duration += _quantize_billable_duration(duration, increment)
    else:
        for checkpoint in (checkpoints or {}).values():
            if not isinstance(checkpoint, Mapping):
                continue
            try:
                duration = float(checkpoint.get("billing_duration_s") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if math.isfinite(duration) and duration > 0:
                total_duration += _quantize_billable_duration(duration, increment)
            for value in checkpoint.get("provider_request_ids") or ():
                request_id = str(value or "").strip()
                if request_id:
                    request_ids.add(request_id)

    pricing = resolve_seed_audio_pricing()
    rate = pricing.price_per_second_yuan if pricing is not None else None
    return {
        "model": str(model or SEED_AUDIO_MODEL),
        "pricing_status": "configured" if rate is not None else "rate_unconfigured",
        "pricing_source": pricing.source if pricing is not None else None,
        "pricing_basis": "public_list_price",
        "price_per_second_yuan": rate,
        "price_per_minute_yuan": (
            round(pricing.price_per_minute_yuan, 6)
            if pricing is not None
            else None
        ),
        "billing_increment_s": round(increment, 6),
        "billable_duration_s": round(total_duration, 4),
        "provider_request_count": len(request_ids),
        "actual_cost_yuan": (
            round(total_duration * rate, 4)
            if rate is not None
            else None
        ),
    }


__all__ = [
    "DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S",
    "DEFAULT_SEED_AUDIO_PRICE_PER_MINUTE_YUAN",
    "SEED_AUDIO_MODEL",
    "SeedAudioPricing",
    "build_seed_scene_billing_summary",
    "get_seed_audio_price_per_second_yuan",
    "resolve_seed_audio_billing_increment_s",
    "resolve_seed_audio_pricing",
]
