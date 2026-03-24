from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


UserCenterPointsAccountStatus = Literal["planned", "partial"]
UserCenterBenefitStatus = Literal["connected", "planned"]
UserCenterPointsRuleSource = Literal["default", "admin_log"]
UserCenterPricingBasis = Literal["public_list_price", "standard_price_table"]
UserCenterPointsEntryDirection = Literal["income", "expense", "hold"]
UserCenterPointsEntryStatus = Literal["active", "expired", "frozen"]
UserCenterTaskBillingTaskStatus = Literal["running", "completed"]
UserCenterTaskBillingPricingStatus = Literal["actual", "estimated", "pending"]


class UserCenterPointsAccount(BaseModel):
    balance: float | None = None
    frozen: float | None = None
    expiring_soon: float | None = None
    status: UserCenterPointsAccountStatus = "planned"
    connected_source_count: int = 0
    pending_source_count: int = 0


class UserCenterConnectedOverview(BaseModel):
    project_count: int = 0
    user_asset_count: int = 0
    audiobook_project_count: int = 0
    audiobook_total_cost: float = 0.0
    dreamweaver_run_count: int = 0


class UserCenterBenefitItem(BaseModel):
    key: str
    label: str
    summary: str
    status: UserCenterBenefitStatus


class UserCenterBenefitsOverview(BaseModel):
    connected_items: list[UserCenterBenefitItem] = Field(default_factory=list)
    planned_items: list[UserCenterBenefitItem] = Field(default_factory=list)


class UserCenterLedgerEntry(BaseModel):
    key: str
    module_label: str
    event_label: str
    title: str
    summary: str
    amount: float
    occurred_at: datetime | None = None
    project_label: str | None = None
    action_path: str | None = None
    action_label: str | None = None


class UserCenterPendingLedgerSignal(BaseModel):
    key: str
    module_label: str
    signal_label: str
    summary: str
    action_path: str | None = None
    action_label: str | None = None


class UserCenterLedgerOverview(BaseModel):
    connected_entries: list[UserCenterLedgerEntry] = Field(default_factory=list)
    pending_signals: list[UserCenterPendingLedgerSignal] = Field(default_factory=list)


class UserCenterPointsRuleOverview(BaseModel):
    reusable_asset_reward: float
    deliverable_asset_reward: float
    audiobook_completion_reward: float
    dreamweaver_completion_reward: float
    running_audiobook_frozen: float
    running_dreamweaver_frozen: float
    reward_ttl_days: int
    expiring_notice_days: int
    source: UserCenterPointsRuleSource = "default"
    updated_at: datetime | None = None
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None


class UserCenterPointsPricingPolicyOverview(BaseModel):
    points_per_yuan: int
    user_price_basis: UserCenterPricingBasis = "public_list_price"
    user_price_rate: float
    freeze_buffer_rate: float
    source: UserCenterPointsRuleSource = "default"
    updated_at: datetime | None = None
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None


class UserCenterPointsEntry(BaseModel):
    key: str
    source_key: str
    source_label: str
    title: str
    summary: str
    amount: float
    direction: UserCenterPointsEntryDirection
    status: UserCenterPointsEntryStatus
    occurred_at: datetime | None = None
    expires_at: datetime | None = None
    action_path: str | None = None
    action_label: str | None = None


class UserCenterTaskBillingItem(BaseModel):
    key: str
    module_key: str
    module_label: str
    title: str
    summary: str
    task_status: UserCenterTaskBillingTaskStatus
    pricing_status: UserCenterTaskBillingPricingStatus
    actual_yuan: float | None = None
    actual_points: float | None = None
    estimated_yuan: float | None = None
    estimated_points: float | None = None
    suggested_frozen_points: float | None = None
    occurred_at: datetime | None = None
    action_path: str | None = None
    action_label: str | None = None


class UserCenterTaskBillingOverview(BaseModel):
    actual_spend_yuan: float = 0.0
    actual_spend_points: float = 0.0
    estimated_running_spend_yuan: float = 0.0
    estimated_running_spend_points: float = 0.0
    suggested_frozen_points: float = 0.0
    actual_task_count: int = 0
    estimated_task_count: int = 0
    pending_task_count: int = 0
    items: list[UserCenterTaskBillingItem] = Field(default_factory=list)


class UserCenterPointsOverviewResponse(BaseModel):
    points_account: UserCenterPointsAccount
    points_rules: UserCenterPointsRuleOverview
    pricing_policy: UserCenterPointsPricingPolicyOverview
    points_entries: list[UserCenterPointsEntry] = Field(default_factory=list)
    connected_overview: UserCenterConnectedOverview
    benefits: UserCenterBenefitsOverview
    ledger: UserCenterLedgerOverview
    task_billing: UserCenterTaskBillingOverview
