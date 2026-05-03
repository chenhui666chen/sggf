from __future__ import annotations

import math

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.project import Chapter, Project
from app.models.user import User
from app.schemas.user_center import (
    UserCenterBenefitItem,
    UserCenterBenefitsOverview,
    UserCenterConnectedOverview,
    UserCenterLedgerEntry,
    UserCenterLedgerOverview,
    UserCenterPendingLedgerSignal,
    UserCenterPointsAccount,
    UserCenterPointsEntry,
    UserCenterPointsOverviewResponse,
    UserCenterPointsPricingPolicyOverview,
    UserCenterPointsRuleOverview,
    UserCenterTaskBillingItem,
    UserCenterTaskBillingOverview,
)
from app.services.points_pricing_policy import get_points_pricing_policy_snapshot
from app.services.user_center_points import (
    POINTS_SOURCE_LABELS,
    UserCenterPointsAccountSnapshot,
    UserCenterPointsBundleSnapshot,
    UserCenterPointsEntrySnapshot,
    UserCenterPointsRuleSnapshot,
)
from app.services.user_center_task_billing import (
    UserCenterPricingPolicyOverviewSnapshot,
    UserCenterTaskBillingItemSnapshot,
    UserCenterTaskBillingOverviewSnapshot,
    build_user_center_pricing_policy_overview,
    build_user_center_task_billing_overview,
)
from app.services.user_points_read_model import build_user_points_read_model


router = APIRouter(prefix="/api/v1/user-center", tags=["user-center"])


def _to_finite_float(value: object | None) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if math.isfinite(amount) else 0.0


def _normalize_text(value: object | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _points_rule_snapshot_to_response(snapshot: UserCenterPointsRuleSnapshot) -> UserCenterPointsRuleOverview:
    payload = snapshot.config.to_payload()
    return UserCenterPointsRuleOverview(
        **payload,
        source=snapshot.source,
        updated_at=snapshot.updated_at,
        updated_by_user_id=snapshot.updated_by_user_id,
        updated_by_username=snapshot.updated_by_username,
    )


def _pricing_policy_snapshot_to_response(
    snapshot: UserCenterPricingPolicyOverviewSnapshot,
) -> UserCenterPointsPricingPolicyOverview:
    return UserCenterPointsPricingPolicyOverview(
        points_per_yuan=snapshot.points_per_yuan,
        user_price_basis=snapshot.user_price_basis,
        user_price_rate=snapshot.user_price_rate,
        freeze_buffer_rate=snapshot.freeze_buffer_rate,
        source=snapshot.source,
        updated_at=snapshot.updated_at,
        updated_by_user_id=snapshot.updated_by_user_id,
        updated_by_username=snapshot.updated_by_username,
    )


def _points_entry_snapshot_to_response(snapshot: UserCenterPointsEntrySnapshot) -> UserCenterPointsEntry:
    return UserCenterPointsEntry(
        key=snapshot.key,
        source_key=snapshot.source_key,
        source_label=POINTS_SOURCE_LABELS.get(snapshot.source_key, snapshot.source_key),
        title=snapshot.title,
        summary=snapshot.summary,
        amount=snapshot.amount,
        direction=snapshot.direction,
        status=snapshot.status,
        occurred_at=snapshot.occurred_at,
        expires_at=snapshot.expires_at,
        action_path=snapshot.action_path,
        action_label=snapshot.action_label,
    )


def _task_billing_item_snapshot_to_response(snapshot: UserCenterTaskBillingItemSnapshot) -> UserCenterTaskBillingItem:
    return UserCenterTaskBillingItem(
        key=snapshot.key,
        module_key=snapshot.module_key,
        module_label=snapshot.module_label,
        title=snapshot.title,
        summary=snapshot.summary,
        task_status=snapshot.task_status,
        pricing_status=snapshot.pricing_status,
        actual_yuan=snapshot.actual_yuan,
        actual_points=snapshot.actual_points,
        estimated_yuan=snapshot.estimated_yuan,
        estimated_points=snapshot.estimated_points,
        suggested_frozen_points=snapshot.suggested_frozen_points,
        occurred_at=snapshot.occurred_at,
        action_path=snapshot.action_path,
        action_label=snapshot.action_label,
    )


def _task_billing_overview_snapshot_to_response(
    snapshot: UserCenterTaskBillingOverviewSnapshot,
) -> UserCenterTaskBillingOverview:
    return UserCenterTaskBillingOverview(
        actual_spend_yuan=snapshot.actual_spend_yuan,
        actual_spend_points=snapshot.actual_spend_points,
        estimated_running_spend_yuan=snapshot.estimated_running_spend_yuan,
        estimated_running_spend_points=snapshot.estimated_running_spend_points,
        suggested_frozen_points=snapshot.suggested_frozen_points,
        actual_task_count=snapshot.actual_task_count,
        estimated_task_count=snapshot.estimated_task_count,
        pending_task_count=snapshot.pending_task_count,
        items=[_task_billing_item_snapshot_to_response(item) for item in snapshot.items],
    )


def _build_connected_benefits(
    *,
    has_admin_role: bool,
    role_names: list[str],
    project_count: int,
    audiobook_project_count: int,
    user_asset_count: int,
    points_snapshot: UserCenterPointsAccountSnapshot,
) -> list[UserCenterBenefitItem]:
    role_summary = " / ".join(role_names) or ("管理员角色已生效" if has_admin_role else "标准创作者角色已生效")

    items = [
        UserCenterBenefitItem(
            key="identity",
            label="管理员身份" if has_admin_role else "创作者身份",
            summary=role_summary,
            status="connected",
        ),
        UserCenterBenefitItem(
            key="novel-workbench",
            label="小说创作工作台",
            summary=f"已识别 {project_count} 个小说项目入口。",
            status="connected",
        ),
        UserCenterBenefitItem(
            key="audiobook-production",
            label="有声书生产能力",
            summary=f"已识别 {audiobook_project_count} 个有声书项目，并可汇总 TTS 成本。",
            status="connected",
        ),
        UserCenterBenefitItem(
            key="asset-center",
            label="用户资产归档",
            summary=f"当前用户中心已收纳 {user_asset_count} 项资产。",
            status="connected",
        ),
        UserCenterBenefitItem(
            key="model-catalog",
            label="模型中心访问",
            summary="模型目录、能力描述与推荐入口已经可用。",
            status="connected",
        ),
    ]

    if points_snapshot.connected_source_count > 0:
        source_labels = [
            POINTS_SOURCE_LABELS[source_key]
            for source_key in points_snapshot.connected_source_keys
            if source_key in POINTS_SOURCE_LABELS
        ]
        source_summary = " / ".join(source_labels) or "真实业务事件"
        expiring_summary = (
            f"，其中 {points_snapshot.expiring_soon:.2f} 积分即将过期"
            if points_snapshot.expiring_soon > 0
            else ""
        )
        items.append(
            UserCenterBenefitItem(
                key="points-account",
                label="积分试运行账户",
                summary=(
                    f"已按 {source_summary} 结算试运行积分，当前余额 {points_snapshot.balance:.2f}，"
                    f"冻结 {points_snapshot.frozen:.2f}{expiring_summary}。"
                ),
                status="connected",
            )
        )

    if has_admin_role:
        items.append(
            UserCenterBenefitItem(
                key="admin-console",
                label="控制台权限",
                summary="管理员控制台入口已开放，可用于治理与巡检。",
                status="connected",
            )
        )

    return items


def _build_planned_benefits(*, include_points_ledger: bool) -> list[UserCenterBenefitItem]:
    items: list[UserCenterBenefitItem] = []
    if include_points_ledger:
        items.append(
            UserCenterBenefitItem(
                key="points-ledger",
                label="积分余额 / 冻结 / 到期",
                summary="待接真实积分账本后展示余额、冻结和即将过期积分。",
                status="planned",
            )
        )

    items.extend(
        [
            UserCenterBenefitItem(
                key="model-quota",
                label="模型额度池",
                summary="待接模型与供应商维度的额度、配额和超额规则。",
                status="planned",
            ),
            UserCenterBenefitItem(
                key="membership-tier",
                label="会员等级 / 优先队列",
                summary="待接会员等级、优先队列和专属权益编排能力。",
                status="planned",
            ),
            UserCenterBenefitItem(
                key="payment-orders",
                label="充值订单 / 对账争议",
                summary="待接支付订单、充值流水和争议追踪链路。",
                status="planned",
            ),
        ]
    )
    return items


def _build_pending_signals(
    *,
    dreamweaver_run_count: int,
    user_asset_count: int,
    has_admin_role: bool,
    points_snapshot: UserCenterPointsAccountSnapshot,
) -> list[UserCenterPendingLedgerSignal]:
    points_signal_label = "充值 / 补发规则待接入" if points_snapshot.connected_source_count > 0 else "余额字段待接入"
    points_signal_summary = (
        "当前积分账户已支持基于真实业务事件的奖励结算，但充值订单、人工补发争议与正式流水仍待接入。"
        if points_snapshot.connected_source_count > 0
        else "当前仅保留积分账户位置和账本边界，等待真实积分系统进一步接入。"
    )

    return [
        UserCenterPendingLedgerSignal(
            key="dreamweaver-ledger",
            module_label="短剧生成",
            signal_label=f"{dreamweaver_run_count} 条 run 记录",
            summary=(
                "已识别短剧生成活动，但尚未接入真实金额成本或权益扣减账本。"
                if dreamweaver_run_count > 0
                else "账本位已预留，后续可直接接入短剧生成成本与权益消耗。"
            ),
            action_path="/drama" if has_admin_role else None,
            action_label="查看短剧模块" if has_admin_role else None,
        ),
        UserCenterPendingLedgerSignal(
            key="asset-ledger",
            module_label="用户资产",
            signal_label=f"{user_asset_count} 项资产",
            summary="已识别资产收录与归档行为，后续可继续补齐权益消耗、人工补发和账单对账链路。",
            action_path="/user-center",
            action_label="查看资产中心",
        ),
        UserCenterPendingLedgerSignal(
            key="points-ledger",
            module_label="积分账户",
            signal_label=points_signal_label,
            summary=points_signal_summary,
            action_path="/user-center",
            action_label="查看账户规则",
        ),
    ]


@router.get("/points-overview", response_model=UserCenterPointsOverviewResponse)
async def get_user_center_points_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_names = [
        role_name
        for role_name in (_normalize_text(getattr(role, "name", None)) for role in (current_user.roles or []))
        if role_name
    ]
    has_admin_role = any(
        (_normalize_text(getattr(role, "code", None)) or "").lower() in {"admin", "super_admin"}
        for role in (current_user.roles or [])
    )

    project_count = int(
        db.query(func.count(Project.id))
        .filter(Project.user_id == current_user.id)
        .scalar()
        or 0
    )

    points_read_model = build_user_points_read_model(db=db, user_id=current_user.id)
    user_asset_rows = list(points_read_model.user_asset_rows)
    user_asset_count = len(user_asset_rows)

    dreamweaver_rows = list(points_read_model.dreamweaver_rows)
    dreamweaver_run_count = len(dreamweaver_rows)

    audiobook_rows = list(points_read_model.audiobook_rows)
    points_rule_snapshot = points_read_model.points_rule_snapshot
    pricing_policy_snapshot = get_points_pricing_policy_snapshot(db=db)
    points_bundle: UserCenterPointsBundleSnapshot = points_read_model.points_bundle
    pricing_policy_overview = build_user_center_pricing_policy_overview(pricing_policy_snapshot)
    points_snapshot = points_bundle.account

    connected_entries: list[UserCenterLedgerEntry] = []
    audiobook_total_cost = 0.0

    audiobook_project_ids = sorted(
        {
            int(getattr(row, "project_id", 0) or 0)
            for row in audiobook_rows
            if int(getattr(row, "project_id", 0) or 0) > 0
        }
    )
    chapter_rows = []
    if audiobook_project_ids:
        chapter_rows = (
            db.query(
                Chapter.project_id.label("project_id"),
                Chapter.word_count.label("word_count"),
                Chapter.content.label("content"),
            )
            .filter(
                Chapter.project_id.in_(audiobook_project_ids),
                Chapter.deleted_at.is_(None),
            )
            .all()
        )

    task_billing_overview = build_user_center_task_billing_overview(
        audiobook_rows=list(audiobook_rows),
        dreamweaver_rows=list(dreamweaver_rows),
        chapter_rows=list(chapter_rows),
        pricing_config=pricing_policy_snapshot.config,
    )

    for row in audiobook_rows:
        total_cost = _to_finite_float(row.total_cost)
        audiobook_total_cost += total_cost
        if total_cost <= 0:
            continue

        project_title = _normalize_text(row.project_title)
        title = project_title or f"有声书项目 {row.id}"
        completed_chapters = int(row.completed_chapters or 0)
        total_chapters = int(row.total_chapters or 0)

        connected_entries.append(
            UserCenterLedgerEntry(
                key=f"audiobook-ledger-{row.id}",
                module_label="有声书",
                event_label="TTS 成本",
                title=title,
                summary=f"已完成 {completed_chapters}/{total_chapters} 章节，当前总成本 ￥{total_cost:.2f}。",
                amount=round(total_cost, 2),
                occurred_at=row.updated_at or row.created_at,
                project_label=project_title,
                action_path=f"/audiobook/{row.project_id}" if row.project_id else "/audiobook-dashboard",
                action_label="查看有声书项目",
            )
        )

    audiobook_project_count = len(audiobook_rows)
    pending_signals = _build_pending_signals(
        dreamweaver_run_count=dreamweaver_run_count,
        user_asset_count=user_asset_count,
        has_admin_role=has_admin_role,
        points_snapshot=points_snapshot,
    )

    account_is_live = points_snapshot.connected_source_count > 0
    pending_source_count = len(pending_signals)

    return UserCenterPointsOverviewResponse(
        points_account=UserCenterPointsAccount(
            balance=points_snapshot.balance if account_is_live else None,
            frozen=points_snapshot.frozen if account_is_live else None,
            expiring_soon=points_snapshot.expiring_soon if account_is_live else None,
            status="partial" if account_is_live else "planned",
            connected_source_count=points_snapshot.connected_source_count,
            pending_source_count=pending_source_count,
        ),
        points_rules=_points_rule_snapshot_to_response(points_rule_snapshot),
        pricing_policy=_pricing_policy_snapshot_to_response(pricing_policy_overview),
        points_entries=[_points_entry_snapshot_to_response(entry) for entry in points_bundle.entries],
        connected_overview=UserCenterConnectedOverview(
            project_count=project_count,
            user_asset_count=user_asset_count,
            audiobook_project_count=audiobook_project_count,
            audiobook_total_cost=round(audiobook_total_cost, 2),
            dreamweaver_run_count=dreamweaver_run_count,
        ),
        benefits=UserCenterBenefitsOverview(
            connected_items=_build_connected_benefits(
                has_admin_role=has_admin_role,
                role_names=role_names,
                project_count=project_count,
                audiobook_project_count=audiobook_project_count,
                user_asset_count=user_asset_count,
                points_snapshot=points_snapshot,
            ),
            planned_items=_build_planned_benefits(include_points_ledger=not account_is_live),
        ),
        ledger=UserCenterLedgerOverview(
            connected_entries=connected_entries,
            pending_signals=pending_signals,
        ),
        task_billing=_task_billing_overview_snapshot_to_response(task_billing_overview),
    )
