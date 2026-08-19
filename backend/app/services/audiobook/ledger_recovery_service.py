"""ledger 恢复证据持久化与恢复决策服务（GUIDE R12/P1-3，R13/P0-b，验收 70）。

- ``persist_result_url_evidence``：结果 URL 落库（encrypted_result_url +
  result_url_expires_at + result_url_persisted_at + commit_stage='result_persisted'）。
- ``decide_recovery_method``：按本次调用时持久化的**实际证据**决策恢复方式——
  禁止用当前能力表配置重新解释历史调用（capability_snapshot_json 优先）；
  仅"支持声明"而无实际证据的调用不自动重放。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.billing_usage_ledger import BillingUsageLedger
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

# 恢复方法值域（对齐 provider_recovery.RECOVERY_METHODS + manual）
RECOVERY_METHOD_QUERY = "request_query"
RECOVERY_METHOD_URL = "temporary_url"
RECOVERY_METHOD_REPLAY = "replay"
RECOVERY_METHOD_MANUAL = "manual"
RECOVERY_METHODS = frozenset(
    {RECOVERY_METHOD_QUERY, RECOVERY_METHOD_URL, RECOVERY_METHOD_REPLAY, RECOVERY_METHOD_MANUAL}
)


def persist_result_url_evidence(
    db: Session,
    *,
    ledger_id: int,
    encrypted_url: str,
    expires_at,
) -> Dict[str, Any]:
    """结果 URL 落库（R13/P0-b：encrypted_result_url/result_url_expires_at）。

    同时置 ``result_url_persisted_at`` 与 ``commit_stage='result_persisted'``
    （提交阶段 rank 3，R18/P1-1 单调不减）。
    返回 ``{"ok": bool, "reason": str}``。
    """
    if not encrypted_url:
        return {"ok": False, "reason": "empty_result_url"}
    ledger = (
        db.query(BillingUsageLedger)
        .filter(BillingUsageLedger.id == ledger_id)
        .first()
    )
    if ledger is None:
        return {"ok": False, "reason": "ledger_not_found"}

    now = utc_now()
    ledger.encrypted_result_url = str(encrypted_url)
    ledger.result_url_expires_at = expires_at
    ledger.result_url_persisted_at = now
    # commit_stage 单调推进：pre_call(1) → post_call(2) → result_persisted(3)
    if (ledger.commit_stage or "pre_call") != "result_persisted":
        ledger.commit_stage = "result_persisted"
    db.flush()
    return {"ok": True, "reason": "result_url_persisted"}


def _snapshot_capability(ledger: BillingUsageLedger) -> Dict[str, Any]:
    """读取调用时能力快照（无快照时按不支持处理，fail-closed）。"""
    snapshot = ledger.capability_snapshot_json
    return snapshot if isinstance(snapshot, dict) else {}


def decide_recovery_method(
    ledger: BillingUsageLedger,
    *,
    current_capability: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """按持久化实际证据决策恢复方式（R12/P1-3，R13/P0-b）。

    决策顺序（对齐 GUIDE §1.1 恢复语义）：
    ① 已持有 provider_request_id → request_query（能力声明 supports_request_query
       且调用时快照支持；仅"当前支持"但调用时未获得 ID 不进入本分支）；
    ② 已持有 encrypted_result_url 且 result_url_persisted_at 非空 → temporary_url
       （未过期时）；
    ③ idempotency_key_sent=true 且调用时能力快照 accepts_idempotency_key → replay
       （可安全重放，不产生第二笔费用）；
    ④ 无任何实际证据 → manual（人工对账，零二次调用）。

    返回 ``{"method": str, "evidence": str}``。current_capability 仅作日志/审计
    参考，不参与决策（历史调用以 capability_snapshot_json 为准）。
    """
    capability = _snapshot_capability(ledger)
    now = utc_now()

    provider_request_id = str(ledger.provider_request_id or "").strip()
    if provider_request_id:
        if bool(capability.get("supports_request_query")):
            return {
                "method": RECOVERY_METHOD_QUERY,
                "evidence": f"provider_request_id={provider_request_id}",
            }
        # 调用时未声明可查询：即使当前支持也不 query（历史调用按历史能力）
        logger.warning(
            "ledger_id=%s 有 request_id 但调用时能力不支持查询，回退后续决策",
            ledger.id,
        )

    result_url = str(ledger.encrypted_result_url or "").strip()
    if result_url and ledger.result_url_persisted_at is not None:
        if ledger.result_url_expires_at is None or ledger.result_url_expires_at > now:
            return {
                "method": RECOVERY_METHOD_URL,
                "evidence": "encrypted_result_url_persisted",
            }
        logger.warning(
            "ledger_id=%s 结果 URL 已过期，回退后续决策", ledger.id,
        )

    if ledger.idempotency_key_sent and bool(capability.get("accepts_idempotency_key")):
        return {
            "method": RECOVERY_METHOD_REPLAY,
            "evidence": "idempotency_key_sent_and_accepted",
        }

    # 无实际证据：不自动重放，人工对账（零二次调用承诺仅对支持幂等/可查询的
    # provider 成立，R11/P1-3）
    return {
        "method": RECOVERY_METHOD_MANUAL,
        "evidence": "no_recoverable_evidence",
    }


__all__ = [
    "RECOVERY_METHODS",
    "RECOVERY_METHOD_MANUAL",
    "RECOVERY_METHOD_QUERY",
    "RECOVERY_METHOD_REPLAY",
    "RECOVERY_METHOD_URL",
    "decide_recovery_method",
    "persist_result_url_evidence",
]
