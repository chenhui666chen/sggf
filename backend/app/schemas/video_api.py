from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class VideoApiApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    plan_code: str = Field(default="standard", pattern=r"^[a-z][a-z0-9_-]{0,39}$")


class VideoApiApplicationResponse(BaseModel):
    id: int
    name: str
    status: str
    plan_code: str
    rate_limit_per_second: int
    burst_capacity: int
    max_active_jobs: int
    max_parallel_attempts: int
    lifetime_task_limit: int
    api_key_prefix: str
    daily_budget: Decimal | None = None
    monthly_budget: Decimal | None = None
    created_at: datetime
    updated_at: datetime
    api_key: str | None = None
    model_config = ConfigDict(from_attributes=True)


class VideoApiApplicationListResponse(BaseModel):
    items: list[VideoApiApplicationResponse]


class VideoApiAdminStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|suspended|revoked)$")


class VideoApiQuotaUpdate(BaseModel):
    rate_limit_per_second: int | None = Field(default=None, ge=1, le=10000)
    burst_capacity: int | None = Field(default=None, ge=1, le=100000)
    max_active_jobs: int | None = Field(default=None, ge=1, le=100000)
    max_parallel_attempts: int | None = Field(default=None, ge=1, le=16)
    lifetime_task_limit: int | None = Field(default=None, ge=1, le=100000000)
    daily_budget: Decimal | None = Field(default=None, ge=0)
    monthly_budget: Decimal | None = Field(default=None, ge=0)
    model_config = ConfigDict(extra="forbid")


class VideoGatewayOverviewResponse(BaseModel):
    total_applications: int
    active_applications: int
    suspended_applications: int
    revoked_applications: int


class VideoGatewayMetricsResponse(BaseModel):
    window_hours: int
    route_event_count: int
    success_rate: float
    p50_latency_seconds: float
    p95_latency_seconds: float
    active_jobs: int
    total_cost: Decimal | None
    unknown_cost_attempts: int
    pending_jobs: int
    sampled_event_count: int
    providers: list[dict]
    routes: list[dict]
    clients: list[dict]
    quality: dict = Field(default_factory=dict)
