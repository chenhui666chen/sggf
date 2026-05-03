"""
管理控制台专用 Schema
"""
from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user_center import UserCenterPointsEntry


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    description: Optional[str] = None


class RoleCreate(RoleBase):
    permission_ids: List[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permission_ids: Optional[List[int]] = None


class RoleResponse(RoleBase):
    id: int
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime
    permissions: List["PermissionResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class PermissionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z_:\*]+$")
    resource: str = Field(..., min_length=1, max_length=50)
    action: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[int] = None


class PermissionResponse(PermissionBase):
    id: int
    created_at: datetime
    children: Optional[List["PermissionResponse"]] = None

    model_config = ConfigDict(from_attributes=True)


class UserAdminResponse(BaseModel):
    id: int
    username: str
    email: str
    phone: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: List[RoleResponse] = []

    model_config = ConfigDict(from_attributes=True)


class UserListQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    search: Optional[str] = None
    is_active: Optional[bool] = None
    role_code: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None


class UserCreateByAdmin(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)


class UserUpdateByAdmin(BaseModel):
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role_ids: Optional[List[int]] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserRoleUpdate(BaseModel):
    role_ids: List[int]


class UserPointsAdjustmentCreate(BaseModel):
    delta: float = Field(..., description="正数表示补发或充值，负数表示扣减")
    reason: str = Field(..., min_length=1, max_length=200)
    adjustment_type: str = Field(default="manual_grant", min_length=1, max_length=50)
    expires_at: Optional[datetime] = None


class UserPointsAdjustmentResponse(BaseModel):
    id: int
    target_user_id: int
    operator_user_id: int
    operator_username: str
    delta: float
    reason: str
    adjustment_type: str
    expires_at: Optional[datetime] = None
    created_at: datetime


class AdminOperationLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    operation_type: str
    resource_type: str
    resource_id: Optional[int] = None
    operation_desc: str
    request_method: str
    request_path: str
    response_status: int
    ip_address: str
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminLoginLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    login_type: str
    login_status: str
    ip_address: str
    failure_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LogQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    user_id: Optional[int] = None
    operation_type: Optional[str] = None
    resource_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class StatsOverview(BaseModel):
    total_users: int
    new_users_today: int
    active_users_30d: int
    total_projects: int
    active_projects: int
    total_audiobook_tasks: int
    admin_operations_today: int


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int


class UserListResponse(PaginatedResponse):
    items: List[UserAdminResponse]


class UserPointsAdjustmentListResponse(BaseModel):
    items: List[UserPointsAdjustmentResponse]


class UserPointsAccountOverviewResponse(BaseModel):
    target_user_id: int
    balance: Optional[float] = None
    frozen: Optional[float] = None
    available: Optional[float] = None
    expiring_soon: Optional[float] = None
    status: Literal["planned", "partial"] = "planned"
    connected_source_count: int = 0
    entries: List[UserCenterPointsEntry] = Field(default_factory=list)


SystemPointsRuleSource = Literal["default", "admin_log"]
PointsPricingBasis = Literal["public_list_price", "standard_price_table"]
PointsPricingMarginStatus = Literal["healthy", "warning", "negative"]
PointsBillingEventKind = Literal["freeze", "settle", "release"]


class SystemPointsRuleConfigBase(BaseModel):
    reusable_asset_reward: float = Field(..., ge=0)
    deliverable_asset_reward: float = Field(..., ge=0)
    audiobook_completion_reward: float = Field(..., ge=0)
    dreamweaver_completion_reward: float = Field(..., ge=0)
    running_audiobook_frozen: float = Field(..., ge=0)
    running_dreamweaver_frozen: float = Field(..., ge=0)
    reward_ttl_days: int = Field(..., ge=1, le=3650)
    expiring_notice_days: int = Field(..., ge=0, le=3650)


class SystemPointsRuleConfigUpdate(SystemPointsRuleConfigBase):
    pass


class SystemPointsRuleConfigResponse(SystemPointsRuleConfigBase):
    source: SystemPointsRuleSource = "default"
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None
    updated_by_username: Optional[str] = None


class SystemPointsPricingPolicyBase(BaseModel):
    points_per_yuan: int = Field(..., ge=1, le=100000)
    user_price_basis: PointsPricingBasis = "public_list_price"
    user_price_rate: float = Field(..., ge=0, le=10)
    provider_discount_capture_rate: float = Field(..., ge=0, le=1)
    freeze_buffer_rate: float = Field(..., ge=0, le=1)
    margin_warning_rate: float = Field(..., ge=0, le=1)
    negative_margin_block_enabled: bool


class SystemPointsPricingPolicyUpdate(SystemPointsPricingPolicyBase):
    pass


class SystemPointsPricingOperatingSnapshotResponse(BaseModel):
    module_key: str
    module_label: str
    provider_key: Optional[str] = None
    user_basis_yuan: float
    user_billed_yuan: float
    supplier_list_price_yuan: float
    supplier_discount_rate: float
    supplier_discount_rate_source: str
    supplier_discounted_cost_yuan: float
    supplier_discount_yuan: float
    captured_discount_yuan: float
    shared_discount_yuan: float
    policy_target_user_billed_yuan: float
    policy_alignment_gap_yuan: float
    platform_gross_profit_yuan: float
    platform_margin_rate: Optional[float] = None
    margin_status: PointsPricingMarginStatus
    negative_margin_blocked: bool


class UserPointsBillingEventResponse(BaseModel):
    id: int
    target_user_id: int
    operator_user_id: int
    operator_username: str
    operation_type: str
    module_key: str
    module_label: str
    event_kind: PointsBillingEventKind
    event_label: str
    billing_key: str
    title: str
    summary: str
    amount_points: float
    amount_yuan: Optional[float] = None
    pricing_status: Optional[str] = None
    task_status: Optional[str] = None
    project_id: Optional[int] = None
    audiobook_project_id: Optional[int] = None
    run_id: Optional[str] = None
    stage: Optional[str] = None
    action_path: Optional[str] = None
    action_label: Optional[str] = None
    created_at: datetime
    operating_snapshot: Optional[SystemPointsPricingOperatingSnapshotResponse] = None


class UserPointsBillingEventListResponse(BaseModel):
    items: List[UserPointsBillingEventResponse]


class SystemPointsPricingPolicyResponse(SystemPointsPricingPolicyBase):
    source: SystemPointsRuleSource = "default"
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None
    updated_by_username: Optional[str] = None
    operating_snapshots: List[SystemPointsPricingOperatingSnapshotResponse] = Field(default_factory=list)


class RoleListResponse(PaginatedResponse):
    items: List[RoleResponse]


class AdminPointsBillingModuleSummaryResponse(BaseModel):
    module_key: str
    module_label: str
    settle_event_count: int
    warning_event_count: int
    negative_event_count: int
    total_user_billed_yuan: float
    total_platform_gross_profit_yuan: float
    blended_margin_rate: Optional[float] = None


class AdminPointsBillingSummaryResponse(BaseModel):
    recent_7d_settle_count: int
    settle_event_count: int
    warning_event_count: int
    negative_event_count: int
    total_user_billed_yuan: float
    total_platform_gross_profit_yuan: float
    blended_margin_rate: Optional[float] = None
    module_summaries: List[AdminPointsBillingModuleSummaryResponse] = Field(default_factory=list)


class AdminPointsBillingEventListResponse(PaginatedResponse):
    summary: AdminPointsBillingSummaryResponse
    items: List[UserPointsBillingEventResponse]


class OperationLogListResponse(PaginatedResponse):
    items: List[AdminOperationLogResponse]


class LoginLogListResponse(PaginatedResponse):
    items: List[AdminLoginLogResponse]


RoleResponse.model_rebuild()
PermissionResponse.model_rebuild()
