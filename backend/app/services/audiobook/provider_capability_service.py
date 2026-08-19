"""供应商派发能力配置服务（GUIDE §1.1 R11/P1-3）。

核心职责：
- ``seed_provider_capabilities``：初始化/更新已知供应商的派发能力声明。
- ``get_provider_capability``：查询单个供应商能力。
- ``get_all_capabilities``：查询全部供应商能力。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.audiobook import ProviderDispatchCapability

logger = logging.getLogger(__name__)

# 已知供应商能力声明（对齐 provider_recovery.RECOVERY_METHODS）
# accepts_idempotency_key: 是否接受外部幂等键
# returns_request_id: 是否返回供应商 request ID
# supports_request_query: 是否支持按 request ID 查询结果
# has_recoverable_result_url: 是否有可恢复的临时结果 URL
KNOWN_PROVIDER_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "dashscope_seed": {
        "accepts_idempotency_key": True,
        "returns_request_id": True,
        "supports_request_query": True,
        "has_recoverable_result_url": True,
    },
    "aliyun_tts": {
        "accepts_idempotency_key": False,
        "returns_request_id": True,
        "supports_request_query": False,
        "has_recoverable_result_url": False,
    },
    "volcengine_tts": {
        "accepts_idempotency_key": True,
        "returns_request_id": True,
        "supports_request_query": True,
        "has_recoverable_result_url": False,
    },
    "minimax_tts": {
        "accepts_idempotency_key": False,
        "returns_request_id": True,
        "supports_request_query": False,
        "has_recoverable_result_url": False,
    },
    "cosyvoice": {
        "accepts_idempotency_key": True,
        "returns_request_id": True,
        "supports_request_query": True,
        "has_recoverable_result_url": True,
    },
    "fallback_local": {
        "accepts_idempotency_key": False,
        "returns_request_id": False,
        "supports_request_query": False,
        "has_recoverable_result_url": False,
    },
}


def seed_provider_capabilities(db: Session) -> int:
    """初始化/更新已知供应商的派发能力声明。

    返回新增或更新的行数。
    """
    upserted = 0
    for provider, caps in KNOWN_PROVIDER_CAPABILITIES.items():
        existing = (
            db.query(ProviderDispatchCapability)
            .filter(ProviderDispatchCapability.provider == provider)
            .first()
        )
        if existing is None:
            db.add(
                ProviderDispatchCapability(
                    provider=provider,
                    accepts_idempotency_key=caps["accepts_idempotency_key"],
                    returns_request_id=caps["returns_request_id"],
                    supports_request_query=caps["supports_request_query"],
                    has_recoverable_result_url=caps["has_recoverable_result_url"],
                )
            )
        else:
            existing.accepts_idempotency_key = caps["accepts_idempotency_key"]
            existing.returns_request_id = caps["returns_request_id"]
            existing.supports_request_query = caps["supports_request_query"]
            existing.has_recoverable_result_url = caps["has_recoverable_result_url"]
        upserted += 1

    if upserted:
        db.flush()
        logger.info("供应商派发能力声明更新 %s 行", upserted)
    return upserted


def get_provider_capability(
    db: Session, *, provider: str
) -> Optional[ProviderDispatchCapability]:
    """查询单个供应商能力声明。"""
    return (
        db.query(ProviderDispatchCapability)
        .filter(ProviderDispatchCapability.provider == provider)
        .first()
    )


def get_all_capabilities(db: Session) -> list[ProviderDispatchCapability]:
    """查询全部供应商能力声明。"""
    return db.query(ProviderDispatchCapability).all()


__all__ = [
    "KNOWN_PROVIDER_CAPABILITIES",
    "get_all_capabilities",
    "get_provider_capability",
    "seed_provider_capabilities",
]
