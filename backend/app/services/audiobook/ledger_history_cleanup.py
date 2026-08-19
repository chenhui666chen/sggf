"""历史 ledger 清洗服务（GUIDE R17/P1-4，验收 85）。

施加收紧 CHECK 前必须完成：
1. 扫描 ``status='succeeded'`` 且（``pricing_key IS NULL`` OR ``billing_snapshot_id IS NULL``）
   的历史记录：
   - 优先从所属 run 的 ``run_input_snapshot.billing_context.billing_snapshot``
     确定性恢复（snapshot_id 可匹配且 pricing_key 存在于 ``prices`` → 回填两列）；
   - 无法恢复的置 ``status='manual_reconciliation'``（显式进入人工对账、
     拒绝自动结算，而非 NULL 静默放行）。
2. 历史 ``unit`` 非 ``second``/``char`` 值域的行清洗归一化，无法归一的置
   ``manual_reconciliation``。

全部清洗完成后才可施加 ``ck_billing_usage_ledger_succeeded_fields`` 收紧版
与 ``ck_billing_usage_ledger_unit`` 新 CHECK（本服务只做数据清洗，不收窄约束）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudioRun
from app.models.billing_usage_ledger import BillingUsageLedger

logger = logging.getLogger(__name__)

VALID_UNITS = ("second", "char")


def _parse_billing_snapshot(run_input_snapshot: Optional[str]) -> Optional[Dict[str, Any]]:
    """从 run_input_snapshot 解析不可变计价快照。"""
    if not run_input_snapshot:
        return None
    try:
        payload = json.loads(run_input_snapshot)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    signed = payload.get("signed_payload")
    if not isinstance(signed, dict):
        return None
    billing_ctx = signed.get("billing_context")
    if not isinstance(billing_ctx, dict):
        return None
    snapshot = billing_ctx.get("billing_snapshot")
    return snapshot if isinstance(snapshot, dict) else None


def _try_restore_pricing_facts(
    ledger: BillingUsageLedger,
    run: ChapterAudioRun,
) -> bool:
    """从 run_input_snapshot 确定性恢复 pricing_key/billing_snapshot_id。"""
    snapshot = _parse_billing_snapshot(getattr(run, "run_input_snapshot", None))
    if not snapshot:
        return False
    snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
    if not snapshot_id:
        return False
    prices = snapshot.get("prices")
    if not isinstance(prices, dict):
        return False

    usage_kind = str(ledger.usage_kind or "").strip()
    # usage_kind → pricing_key 映射（与 billing_snapshot_builder 唯一映射表同源）
    from app.services.audiobook.billing_snapshot_builder import (
        resolve_pricing_key_for_usage_kind,
    )

    pricing_key = resolve_pricing_key_for_usage_kind(usage_kind)
    if not pricing_key:
        # usage_kind 无法映射：从 snapshot.prices 键集合尝试匹配
        if usage_kind in prices:
            pricing_key = usage_kind
    if not pricing_key or pricing_key not in prices:
        return False

    ledger.pricing_key = pricing_key
    ledger.billing_snapshot_id = snapshot_id
    return True


def run_ledger_history_cleanup(session: Session) -> Dict[str, Any]:
    """执行历史 ledger 清洗，返回报告。

    幂等：已清洗记录（定价事实齐全、unit 合法）不再处理。
    """
    report: Dict[str, Any] = {
        "scanned": 0,
        "restored_from_snapshot": 0,
        "manual_reconciliation": 0,
        "unit_normalized": 0,
        "unit_unrecoverable": 0,
    }

    candidates = session.execute(
        select(BillingUsageLedger)
        .where(
            (BillingUsageLedger.status == "succeeded")
            & (
                (BillingUsageLedger.pricing_key.is_(None))
                | (BillingUsageLedger.billing_snapshot_id.is_(None))
                | (BillingUsageLedger.unit.notin_(VALID_UNITS))
            )
        )
        .order_by(BillingUsageLedger.id.asc())
    ).scalars().all()

    for ledger in candidates:
        report["scanned"] += 1
        run = session.execute(
            select(ChapterAudioRun).where(ChapterAudioRun.id == ledger.run_id)
        ).scalar_one_or_none()

        # ① 缺定价事实：尝试从快照恢复
        pricing_missing = (
            ledger.pricing_key is None or ledger.billing_snapshot_id is None
        )
        if pricing_missing:
            if run is not None and _try_restore_pricing_facts(ledger, run):
                report["restored_from_snapshot"] += 1
            else:
                # 无法恢复 → 显式人工对账（拒绝自动结算，R17/P1-4）
                ledger.status = "manual_reconciliation"
                report["manual_reconciliation"] += 1
                continue

        # ② unit 值域清洗
        unit = str(ledger.unit or "").strip()
        if unit not in VALID_UNITS:
            normalized = _normalize_unit(unit)
            if normalized in VALID_UNITS:
                ledger.unit = normalized
                report["unit_normalized"] += 1
            else:
                ledger.status = "manual_reconciliation"
                report["unit_unrecoverable"] += 1

    if report["scanned"]:
        session.flush()
        logger.info("ledger 历史清洗: %s", report)
    return report


def _normalize_unit(raw: str) -> str:
    """单位归一化：/s、/second、秒 等变体 → second；char/字 → char。"""
    value = str(raw or "").strip().lower()
    value = value.replace(" ", "").replace("/", "")
    if value in {"s", "sec", "seconds", "秒", "秒/次"}:
        return "second"
    if value in {"c", "ch", "chars", "字", "字符", "个字符"}:
        return "char"
    return value


__all__ = [
    "VALID_UNITS",
    "run_ledger_history_cleanup",
]
