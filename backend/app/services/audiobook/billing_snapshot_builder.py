"""计价事实快照构建器（GUIDE 验收 19/23：入队前捕获不可变 pricing snapshot）。

billing_snapshot 是 run 级不可变计价事实：
- ``prices``：用量维度键（seed_scene/tts/asr/remix）→ 单价 + 计量单位 + provider/model。
  币种由价格字段名表达（``price_per_second_yuan``/``price_per_char_yuan``），
  ``unit`` 值域与 ``ck_billing_usage_ledger_unit`` 一致（second|char，R19/P1-1）。
- 计价策略字段（points_per_yuan/user_price_basis/user_price_rate/...）对齐
  ``PointsPricingPolicyConfig`` 实际字段（R8/R9 六步闭环①）。

本模块是 usage_kind → pricing_key → unit 映射的唯一常量表（R18/P1-3：
快照生成/ledger transition service/人工收敛校验/测试四处同源，禁止重复硬编码）。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.audiobook.scene_engine.scene_billing import (
    get_seed_audio_price_per_second_yuan,
)
from app.services.audiobook.tts_model_ids import get_audiobook_tts_model_price_per_10k
from app.services.points_pricing_policy import (
    PointsPricingPolicyConfig,
    get_points_pricing_policy_snapshot,
    resolve_module_user_price_rate,
)

logger = logging.getLogger(__name__)

# 结算公式版本（随公式变更递增）
SETTLEMENT_FORMULA_VERSION = 1

# usage_kind → pricing_key → unit 唯一映射表（R18/P1-3 四处同源的事实源）
USAGE_KIND_PRICING_MAP: Dict[str, Dict[str, str]] = {
    "seed_render": {"pricing_key": "seed_scene", "unit": "second"},
    "tts_chars": {"pricing_key": "tts", "unit": "char"},
    "asr_seconds": {"pricing_key": "asr", "unit": "second"},
    "remix": {"pricing_key": "remix", "unit": "second"},
}

# 计价键 → 计量单位（与 USAGE_KIND_PRICING_MAP 同源）
PRICING_KEY_UNITS: Dict[str, str] = {
    "seed_scene": "second",
    "tts": "char",
    "asr": "second",
    "remix": "second",
}

# 计价键 → 默认供应商（快照内 provider 标识）
DEFAULT_PRICING_KEY_PROVIDERS: Dict[str, str] = {
    "seed_scene": "dashscope_seed",
    "tts": "minimax_tts",
    "asr": "volcengine_asr",
    "remix": "local_remix",
}

# 计价键 → 默认模型
DEFAULT_PRICING_KEY_MODELS: Dict[str, str] = {
    "seed_scene": "seed-audio-1.0-multilingual",
    "tts": "minimax-speech-2.8-hd",
    "asr": "seed-asr",
    "remix": "local_remix",
}


def resolve_pricing_key_for_usage_kind(usage_kind: str) -> Optional[str]:
    """usage_kind → pricing_key（唯一映射表）。"""
    entry = USAGE_KIND_PRICING_MAP.get(str(usage_kind or "").strip())
    return entry["pricing_key"] if entry else None


def resolve_unit_for_usage_kind(usage_kind: str) -> Optional[str]:
    """usage_kind → unit（唯一映射表）。"""
    entry = USAGE_KIND_PRICING_MAP.get(str(usage_kind or "").strip())
    return entry["unit"] if entry else None


def resolve_unit_for_pricing_key(pricing_key: str) -> Optional[str]:
    """pricing_key → unit（唯一映射表）。"""
    return PRICING_KEY_UNITS.get(str(pricing_key or "").strip())


def resolve_tts_price_per_char_yuan(tts_model: Optional[str]) -> Optional[float]:
    """TTS 单价：元/字符（price_per_10k 元/万字符 → /10000）。"""
    price_per_10k = get_audiobook_tts_model_price_per_10k(tts_model or "")
    if price_per_10k is None:
        return None
    try:
        return round(float(price_per_10k) / 10000.0, 8)
    except (TypeError, ValueError):
        return None


def resolve_seed_price_per_second_yuan() -> Optional[float]:
    """Seed 单价：元/秒。"""
    rate = get_seed_audio_price_per_second_yuan()
    if rate is None:
        return None
    return round(float(rate), 8)


def _pricing_policy_fields(
    config: PointsPricingPolicyConfig,
    *,
    module_key: str,
) -> Dict[str, Any]:
    return {
        "points_per_yuan": max(int(config.points_per_yuan), 1),
        "user_price_basis": str(config.user_price_basis or "public_list_price"),
        "user_price_rate": round(max(float(config.user_price_rate), 0.0), 4),
        "provider_discount_capture_rate": round(
            min(max(float(config.provider_discount_capture_rate), 0.0), 1.0), 4
        ),
        "provider_discount_rate": round(
            min(max(float(config.provider_discount_rate), 0.0), 1.0), 4
        ) if hasattr(config, "provider_discount_rate") else 1.0,
        "provider_discount_source": str(
            getattr(config, "provider_discount_source", "") or ""
        ),
        "freeze_buffer_rate": round(
            min(max(float(config.freeze_buffer_rate), 0.0), 1.0), 4
        ),
        "margin_warning_rate": round(
            min(max(float(config.margin_warning_rate), 0.0), 1.0), 4
        ),
        "negative_margin_block_enabled": bool(
            getattr(config, "negative_margin_block_enabled", True)
        ),
        "module_user_price_rate": round(
            max(resolve_module_user_price_rate(pricing_config=config, module_key=module_key), 0.0),
            4,
        ),
    }


def build_billing_snapshot(
    db: Session,
    *,
    audiobook_project_id: int,
    run_type: str,
    tts_model: Optional[str] = None,
    engine_mode: str = "legacy_stems",
    seed_provider: Optional[str] = None,
    asr_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 run 级不可变 billing_snapshot。

    计价键集合按 run_type 裁剪：
    - seed_scene 引擎 → seed_scene + tts（fallback）+ asr；
    - legacy_stems → tts + asr + remix。

    返回结构（GUIDE 验收 19/23 对齐 PointsPricingPolicyConfig 实际字段）：
    ``{"snapshot_id", "captured_at", "prices", "points_per_yuan", ...}``
    """
    normalized_run_type = str(run_type or "").strip().lower()
    normalized_engine_mode = str(engine_mode or "legacy_stems").strip().lower()

    prices: Dict[str, Any] = {}

    if normalized_engine_mode == "seed_scene":
        seed_rate = resolve_seed_price_per_second_yuan()
        if seed_rate is not None:
            prices["seed_scene"] = {
                "unit": "second",
                "price_per_second_yuan": seed_rate,
                "provider": seed_provider or DEFAULT_PRICING_KEY_PROVIDERS["seed_scene"],
                "model": DEFAULT_PRICING_KEY_MODELS["seed_scene"],
            }
        tts_rate = resolve_tts_price_per_char_yuan(tts_model)
        if tts_rate is not None:
            prices["tts"] = {
                "unit": "char",
                "price_per_char_yuan": tts_rate,
                "provider": DEFAULT_PRICING_KEY_PROVIDERS["tts"],
                "model": tts_model or DEFAULT_PRICING_KEY_MODELS["tts"],
            }
    else:
        tts_rate = resolve_tts_price_per_char_yuan(tts_model)
        if tts_rate is not None:
            prices["tts"] = {
                "unit": "char",
                "price_per_char_yuan": tts_rate,
                "provider": DEFAULT_PRICING_KEY_PROVIDERS["tts"],
                "model": tts_model or DEFAULT_PRICING_KEY_MODELS["tts"],
            }

    # asr/remix 单价暂按固定默认（费率未配置时缺省 0——transition 校验会拒绝无单价的
    # succeeded 转态进入 manual_reconciliation，符合 fail-closed）
    if normalized_engine_mode == "seed_scene":
        prices["asr"] = {
            "unit": "second",
            "price_per_second_yuan": 0.0,
            "provider": asr_provider or DEFAULT_PRICING_KEY_PROVIDERS["asr"],
            "model": DEFAULT_PRICING_KEY_MODELS["asr"],
        }
    prices["remix"] = {
        "unit": "second",
        "price_per_second_yuan": 0.0,
        "provider": DEFAULT_PRICING_KEY_PROVIDERS["remix"],
        "model": DEFAULT_PRICING_KEY_MODELS["remix"],
    }

    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    policy_fields = _pricing_policy_fields(
        pricing_snapshot.config,
        module_key="audiobook",
    )

    snapshot: Dict[str, Any] = {
        "snapshot_id": f"bs-{uuid.uuid4().hex[:16]}",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "audiobook_project_id": int(audiobook_project_id),
        "run_type": normalized_run_type,
        "engine_mode": normalized_engine_mode,
        "settlement_formula_version": SETTLEMENT_FORMULA_VERSION,
        "prices": prices,
        **policy_fields,
    }

    # 确定性指纹：参与快照幂等判定（同输入 → 同指纹）
    fingerprint = hashlib.sha256(
        str(
            {
                "run_type": normalized_run_type,
                "engine_mode": normalized_engine_mode,
                "tts_model": tts_model,
                "prices": prices,
                "points_per_yuan": policy_fields["points_per_yuan"],
                "user_price_rate": policy_fields["user_price_rate"],
            }
        ).encode("utf-8")
    ).hexdigest()
    snapshot["snapshot_fingerprint"] = fingerprint
    return snapshot


def compute_settle_amounts(
    snapshot: Dict[str, Any],
    *,
    pricing_key: str,
    quantity: float,
) -> Dict[str, Any]:
    """按计价快照计算单条 ledger 的结算金额。

    返回 ``{"amount_yuan": float, "unit_price_yuan": float, "ok": bool}``。
    """
    prices = snapshot.get("prices") if isinstance(snapshot, dict) else None
    if not isinstance(prices, dict):
        return {"amount_yuan": 0.0, "unit_price_yuan": 0.0, "ok": False}

    price_entry = prices.get(str(pricing_key or "").strip())
    if not isinstance(price_entry, dict):
        return {"amount_yuan": 0.0, "unit_price_yuan": 0.0, "ok": False}

    unit = str(price_entry.get("unit") or "").strip()
    if unit == "second":
        unit_price = _safe_float(price_entry.get("price_per_second_yuan"))
    elif unit == "char":
        unit_price = _safe_float(price_entry.get("price_per_char_yuan"))
    else:
        unit_price = 0.0

    if unit_price <= 0:
        return {"amount_yuan": 0.0, "unit_price_yuan": 0.0, "ok": False}

    amount_yuan = round(float(quantity) * unit_price, 6)
    return {
        "amount_yuan": amount_yuan,
        "unit_price_yuan": unit_price,
        "ok": True,
    }


def convert_yuan_to_points(
    snapshot: Dict[str, Any],
    *,
    amount_yuan: float,
) -> float:
    """元 → 积分（按快照内冻结的计价策略字段）。"""
    points_per_yuan = max(int(snapshot.get("points_per_yuan") or 100), 1)
    user_price_rate = max(float(snapshot.get("module_user_price_rate") or snapshot.get("user_price_rate") or 1.0), 0.0)
    return round(max(float(amount_yuan), 0.0) * points_per_yuan * user_price_rate, 2)


def _safe_float(value: Any) -> float:
    try:
        return round(float(value), 8)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "DEFAULT_PRICING_KEY_MODELS",
    "DEFAULT_PRICING_KEY_PROVIDERS",
    "PRICING_KEY_UNITS",
    "SETTLEMENT_FORMULA_VERSION",
    "USAGE_KIND_PRICING_MAP",
    "build_billing_snapshot",
    "compute_settle_amounts",
    "convert_yuan_to_points",
    "resolve_pricing_key_for_usage_kind",
    "resolve_seed_price_per_second_yuan",
    "resolve_tts_price_per_char_yuan",
    "resolve_unit_for_pricing_key",
    "resolve_unit_for_usage_kind",
]
