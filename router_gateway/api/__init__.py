# -*- coding: utf-8 -*-
"""g5 最小 HTTP 边界（OpenAI 视频风格子集）。

- POST /v1/videos → 202 + Location；意图矛盾/风险前置拒绝/能力不支持 → 422；
- GET  /v1/tasks/{id} → 统一状态 accepted/running/succeeded/failed/unsupported；
- 错误响应只暴露稳定错误码与固定中文文案，绝不回传供应商、URL、key、原始堆栈。
"""
from __future__ import annotations

import os
import re
import secrets
import urllib.parse
from decimal import Decimal
from typing import Optional

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..assembly import build_gateway
from ..catalog.intent import IntentError
from ..catalog import load_catalog
from ..orchestrator.service import JobView, OrchestratorError
from .auth import InvalidApiKey, make_require_client
from ..assets.safe_fetch import SafeFetchError, validate_public_url
from ..db import ClientConcurrencyLimitExceeded, ClientTaskLimitExceeded, IdempotencyKeyConflict
from ..quota import RateLimitExceeded, RateLimiterUnavailable

# g5b 防滥用上限（服务器不经手素材字节，仅收公网 URL）
MAX_PROMPT_CHARS = 8000
MAX_REFERENCE_PER_GROUP = 30   # 覆盖台账已实证最大单组槽位（贰春 30 图）
MAX_TOTAL_REFERENCES = 40      # 图/视/音混合总数天花板
MAX_REFERENCE_URL_LENGTH = 2048
# 参考视频时长硬上限：与已实证的最严供应商约束（wan3 ≤15s）对齐
MAX_REFERENCE_VIDEO_SECONDS = 15.0
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

# semantic_error → 对外错误码与固定文案（不含任何上游细节）
_ERROR_MESSAGES = {
    "invalid_api_key": "无效或已禁用的 API Key",
    "invalid_request": "请求参数不合法，请检查后重试",
    "invalid_intent": "请求参数与素材结构不一致，请检查后重试",
    "unsupported_capability": "当前模型/分辨率/时长/比例组合暂不支持",
    "content_risk_blocked": "内容未通过安全审核，任务已被拒绝",
    "content_safety_unavailable": "内容安全服务暂不可用，请稍后重试",
    "all_candidates_failed": "视频生成失败，请稍后重试或更换参数",
    "upstream_unknown": "上游结果异常，任务未完成",
    "deadline_exceeded": "已超过等待时限，任务未完成",
    "idempotency_key_reused": "幂等键已用于另一份请求",
    "client_concurrency_limit_exceeded": "该应用的活动任务数已达到上限",
    "client_task_limit_exceeded": "该应用的累计任务额度已用完，请联系管理员",
    "client_rate_limit_exceeded": "该应用的请求速率已超过上限，请稍后重试",
    "rate_limiter_unavailable": "请求限流服务暂不可用，请稍后重试",
}

# 内部状态 → 对外统一状态
_STATUS_MAP = {
    "pending": "accepted",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
}

# 提交阶段应作为客户端错误（422）返回的终态码
_CLIENT_ERRORS = {"unsupported_capability", "content_risk_blocked"}


class ReferenceAsset(BaseModel):
    """g5b 单个参考素材：只收公网可读 URL，服务器不经手文件字节。"""

    url: str = Field(min_length=1, max_length=MAX_REFERENCE_URL_LENGTH)
    # 仅参考视频需要的时长元数据（用于"参考视频≤15s"类前置校验）
    duration_seconds: Optional[float] = Field(default=None, gt=0)
    model_config = ConfigDict(extra="forbid")


class VideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Optional[str] = None
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    duration_seconds: int = Field(gt=0)
    resolution: str
    aspect_ratio: str
    allow_switch: bool = True
    allow_hedge: bool = False
    deadline_seconds: Optional[int] = Field(default=None, gt=0)
    # g5b：显式 mode 可选；不传由编排器按素材结构 resolve_mode 仲裁
    mode: Optional[str] = None
    reference_images: list[ReferenceAsset] = Field(default_factory=list)
    reference_videos: list[ReferenceAsset] = Field(default_factory=list)
    reference_audios: list[ReferenceAsset] = Field(default_factory=list)


class InvalidRequest(Exception):
    """通过 Pydantic 之后的请求级校验失败（URL scheme/素材数量/视频时长）。"""


class ClientLimitsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_limit_per_second: int | None = Field(default=None, ge=1, le=10000)
    burst_capacity: int | None = Field(default=None, ge=1, le=100000)
    max_active_jobs: int | None = Field(default=None, ge=1, le=100000)
    max_parallel_attempts: int | None = Field(default=None, ge=1, le=16)
    lifetime_task_limit: int | None = Field(default=None, ge=1, le=100000000)
    daily_task_limit: int | None = Field(default=None, ge=1)
    monthly_task_limit: int | None = Field(default=None, ge=1)
    daily_budget: Decimal | None = Field(default=None, ge=0, lt=100000000)
    monthly_budget: Decimal | None = Field(default=None, ge=0, lt=100000000)


class InternalClientCreate(ClientLimitsUpdate):
    name: str = Field(min_length=1, max_length=100)
    enabled: StrictBool = True


class InternalClientStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


def _validate_idempotency_key(value: Optional[str]) -> str:
    if value is None or not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise InvalidRequest("invalid or missing idempotency key")
    return value


def _error_body(code: str) -> dict:
    return {"error": {"code": code, "message": _ERROR_MESSAGES[code]}}


def _validate_references(req: VideoCreate) -> None:
    """防滥用与公网 URL 校验；任一不满足抛 InvalidRequest（边界拒绝，不产生费用）。"""
    groups = (req.reference_images, req.reference_videos,
              req.reference_audios)
    if sum(len(g) for g in groups) > MAX_TOTAL_REFERENCES:
        raise InvalidRequest("too many reference assets")
    for group in groups:
        if len(group) > MAX_REFERENCE_PER_GROUP:
            raise InvalidRequest("too many assets in one reference group")
        for item in group:
            parts = urllib.parse.urlsplit(item.url)
            if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
                raise InvalidRequest("reference url must be public http(s)")
            try:
                validate_public_url(item.url, resolve_dns=False)
            except SafeFetchError as exc:
                raise InvalidRequest(str(exc)) from exc
    for item in req.reference_videos:
        if (item.duration_seconds is not None
                and item.duration_seconds > MAX_REFERENCE_VIDEO_SECONDS):
            raise InvalidRequest("reference video longer than 15s")


def _task_body(view: JobView) -> dict:
    # 能力不支持对外呈现独立状态 unsupported
    if (view.status == "failed"
            and view.semantic_error == "unsupported_capability"):
        status = "unsupported"
    else:
        status = _STATUS_MAP[view.status]
    body = {"id": view.id, "status": status,
            "quality_group": view.quality_group, "content_url": None,
            "error": None}
    if view.content_url:
        body["content_url"] = view.content_url
    if view.status == "failed" and view.semantic_error:
        code = view.semantic_error
        body["error"] = {"code": code,
                         "message": _ERROR_MESSAGES.get(code, "视频生成失败")}
    return body


def create_app(orchestrator, *, resolve_client, rate_limiter=None,
               admin_repo=None, internal_token: str = "", routes=None,
               configured_providers=None, expose_docs: bool = True) -> FastAPI:
    # 生产/预发关闭交互式文档与 OpenAPI schema（避免接口结构对公网裸露）
    doc_kwargs = {} if expose_docs else {
        "docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="router_gateway", version="g5a", **doc_kwargs)
    require_client = make_require_client(resolve_client)

    @app.exception_handler(InvalidApiKey)
    async def _on_invalid_api_key(request: Request, exc: InvalidApiKey):
        # 无 header / key 错误或已禁用：固定 401，不回显 key、不泄露任何内部细节
        return JSONResponse(
            status_code=401, content=_error_body("invalid_api_key"),
            headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(InvalidRequest)
    async def _on_invalid_request(request: Request, exc: InvalidRequest):
        # 请求级校验失败（URL/数量/时长）：固定 422，不回显具体拒绝原因
        return JSONResponse(status_code=422,
                            content=_error_body("invalid_request"))

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request,
                                   exc: RequestValidationError):
        # Pydantic 结构错误统一为稳定错误体，不向前端泄露字段级校验细节
        return JSONResponse(status_code=422,
                            content=_error_body("invalid_request"))

    @app.exception_handler(IntentError)
    async def _on_intent_error(request: Request, exc: IntentError):
        return JSONResponse(status_code=422,
                            content=_error_body("invalid_intent"))

    @app.exception_handler(OrchestratorError)
    async def _on_orchestrator_error(request: Request, exc: OrchestratorError):
        # 仅用于未预期的编排器错误；job not found 在 GET 内单独映射 404
        return JSONResponse(status_code=500,
                            content=_error_body("upstream_unknown"))

    @app.exception_handler(IdempotencyKeyConflict)
    async def _on_idempotency_conflict(request: Request,
                                       exc: IdempotencyKeyConflict):
        return JSONResponse(status_code=409,
                            content=_error_body("idempotency_key_reused"))

    @app.exception_handler(ClientConcurrencyLimitExceeded)
    async def _on_concurrency_limit(request: Request,
                                    exc: ClientConcurrencyLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {
                "code": "client_concurrency_limit_exceeded",
                "message": _ERROR_MESSAGES["client_concurrency_limit_exceeded"],
                "current": exc.current,
                "limit": exc.limit,
            }},
            headers={"Retry-After": "10"})

    @app.exception_handler(ClientTaskLimitExceeded)
    async def _on_task_limit(request: Request, exc: ClientTaskLimitExceeded):
        return JSONResponse(status_code=429, content={"error": {
            "code": "client_task_limit_exceeded",
            "message": _ERROR_MESSAGES["client_task_limit_exceeded"],
            "current": exc.current, "limit": exc.limit,
        }})

    @app.exception_handler(RateLimitExceeded)
    async def _on_rate_limit(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": {
                "code": "client_rate_limit_exceeded",
                "message": _ERROR_MESSAGES["client_rate_limit_exceeded"],
                "retry_after_seconds": exc.retry_after,
            }},
            headers={"Retry-After": str(exc.retry_after)})

    @app.exception_handler(RateLimiterUnavailable)
    async def _on_rate_limiter_unavailable(request: Request,
                                           exc: RateLimiterUnavailable):
        return JSONResponse(
            status_code=503,
            content=_error_body("rate_limiter_unavailable"),
            headers={"Retry-After": "5"})

    @app.get("/health", include_in_schema=False,
             response_class=PlainTextResponse)
    async def health():
        return "gateway healthy"

    def require_internal(request: Request) -> None:
        supplied = request.headers.get("x-gateway-internal-token", "")
        if not internal_token or not secrets.compare_digest(supplied, internal_token):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")

    def client_payload(client, *, api_key: str | None = None) -> dict:
        return {
            "id": client.id,
            "name": client.name,
            "enabled": client.enabled,
            "rate_limit_per_second": client.rate_limit_per_second,
            "burst_capacity": client.burst_capacity,
            "max_active_jobs": client.max_active_jobs,
            "max_parallel_attempts": client.max_parallel_attempts,
            "lifetime_task_limit": client.lifetime_task_limit,
            "api_key_prefix": (api_key or client.api_key).replace("keyhash:", "")[:8],
            "api_key_hash": client.api_key_hash,
            **({"api_key": api_key} if api_key else {}),
        }

    @app.post("/internal/clients", include_in_schema=False)
    def create_internal_client(payload: InternalClientCreate,
                               internal=Depends(require_internal)):
        if admin_repo is None:
            raise RuntimeError("internal admin repository unavailable")
        api_key = secrets.token_urlsafe(32)
        limits = payload.model_dump(exclude_none=True, exclude={"name"})
        client = admin_repo.create_client(payload.name, api_key, **limits)
        return client_payload(client, api_key=api_key)

    @app.post("/internal/clients/{client_id}/rotate-key", include_in_schema=False)
    def rotate_internal_client_key(client_id: str, internal=Depends(require_internal)):
        if admin_repo is None:
            raise RuntimeError("internal admin repository unavailable")
        api_key = secrets.token_urlsafe(32)
        client = admin_repo.rotate_client_key(client_id, api_key)
        if client is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        return client_payload(client, api_key=api_key)

    @app.post("/internal/clients/{client_id}/status", include_in_schema=False)
    def update_internal_client_status(client_id: str, payload: InternalClientStatus,
                                      internal=Depends(require_internal)):
        if admin_repo is None:
            raise RuntimeError("internal admin repository unavailable")
        client = admin_repo.set_client_enabled(client_id, payload.enabled)
        if client is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        return client_payload(client)

    @app.patch("/internal/clients/{client_id}/limits", include_in_schema=False)
    def update_internal_client_limits(client_id: str, payload: ClientLimitsUpdate,
                                      internal=Depends(require_internal)):
        if admin_repo is None:
            raise RuntimeError("internal admin repository unavailable")
        limits = payload.model_dump(exclude_none=True)
        client = admin_repo.update_client_limits(client_id, **limits)
        if client is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not found")
        return client_payload(client)

    @app.get("/internal/metrics/overview", include_in_schema=False)
    def internal_metrics_overview(request: Request, window_hours: int = 24):
        require_internal(request)
        if admin_repo is None:
            raise RuntimeError("internal admin repository unavailable")
        result = admin_repo.gateway_metrics(window_hours=window_hours)
        result["providers"] = [
            {"provider": provider, "configured": provider in (configured_providers or ())}
            for provider in sorted({route.provider for route in (routes or ())})]
        sampled = {item["route_id"]: item for item in result["routes"]}
        for route in routes or ():
            item = sampled.setdefault(route.route_id, {
                "route_id": route.route_id, "samples": 0, "success_rate": None,
                "p50_latency_seconds": None, "p95_latency_seconds": None,
                "total_cost": None})
            item.update(provider=route.provider, quality_group=route.quality_group,
                        enabled=route.enabled, standby=route.standby,
                        configured=route.provider in (configured_providers or ()))
        result["routes"] = list(sampled.values())
        return result

    @app.post("/v1/videos", status_code=202)
    def create_video(req: VideoCreate, request: Request,
                           client=Depends(require_client)):
        if rate_limiter is not None:
            rate_limiter.check(
                key=client.id,
                rate=getattr(client, "rate_limit_per_second", 1),
                burst=getattr(client, "burst_capacity", 5))
        idempotency_key = _validate_idempotency_key(
            request.headers.get("idempotency-key"))
        _validate_references(req)
        spec = {
            "prompt": req.prompt,
            "duration_seconds": req.duration_seconds,
            "resolution": req.resolution.lower(),
            "aspect_ratio": req.aspect_ratio,
            # mode 不显式传时为 None，由编排器 resolve_mode 按素材结构仲裁；
            # 空素材仲裁结果即 text，g5a 行为保持等价
            "mode": req.mode,
            "quality_group": req.model,
            "reference_images": tuple(a.url for a in req.reference_images),
            "reference_videos": tuple(a.url for a in req.reference_videos),
            "reference_audios": tuple(a.url for a in req.reference_audios),
            # x-client-key 降级为可选终端用户标识透传，不参与鉴权
            "end_user_key": request.headers.get("x-client-key"),
            "allow_switch": req.allow_switch,
            "allow_hedge": req.allow_hedge,
            "deadline_seconds": req.deadline_seconds,
            "max_parallel_attempts": max(
                1, int(getattr(client, "max_parallel_attempts", 2) or 2)),
        }
        # client_key 传内部稳定主键 client.id，绝不使用原始 api_key
        try:
            view = orchestrator.submit_job(
                client.id, idempotency_key, spec)
        except IdempotencyKeyConflict:
            raise

        if view.status == "failed" and view.semantic_error == "content_safety_unavailable":
            return JSONResponse(status_code=503,
                                content=_error_body("content_safety_unavailable"))
        if view.status == "failed" and view.semantic_error in _CLIENT_ERRORS:
            return JSONResponse(status_code=422,
                                content=_error_body(view.semantic_error))
        if view.status == "failed":
            # 提交阶段即耗尽候选等非客户端错误：502 + 脱敏通用码
            code = view.semantic_error or "all_candidates_failed"
            return JSONResponse(
                status_code=502,
                content={"error": {"code": code,
                                   "message": _ERROR_MESSAGES.get(
                                       code, "视频生成失败")}})
        return JSONResponse(status_code=202,
                            content=_task_body(view),
                            headers={"location": f"/v1/tasks/{view.id}"})

    @app.get("/v1/tasks/{job_id}")
    def get_task(job_id: str, client=Depends(require_client)):
        if rate_limiter is not None:
            query_rate = max(20, int(getattr(client, "max_active_jobs", 5)) * 2)
            rate_limiter.check(key=f"query:{client.id}", rate=query_rate,
                               burst=query_rate * 2)
        try:
            # 归属隔离：只查属于该 client 的任务，他人任务与不存在同样 404
            view = orchestrator.get_view(job_id, client.id)
        except OrchestratorError:
            return JSONResponse(status_code=404,
                                content={"error": {"code": "task_not_found",
                                                   "message": "任务不存在"}})
        return _task_body(view)

    return app


def main() -> None:
    """进程入口：python -m router_gateway.api

    主机/端口取 ROUTER_GATEWAY_HTTP_HOST / ROUTER_GATEWAY_HTTP_PORT。
    """
    internal_token = os.getenv("ROUTER_GATEWAY_INTERNAL_TOKEN", "").strip()
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env in {"production", "staging"} and not internal_token:
        raise RuntimeError(
            "production/staging requires ROUTER_GATEWAY_INTERNAL_TOKEN")
    gateway = build_gateway()
    app = create_app(gateway.orchestrator,
                     resolve_client=gateway.repo.get_client_by_api_key,
                     rate_limiter=gateway.rate_limiter,
                     admin_repo=gateway.repo,
                     internal_token=internal_token,
                     routes=load_catalog(),
                     configured_providers=set(gateway.adapters),
                     expose_docs=app_env not in {"production", "staging"})
    uvicorn.run(app,
                host=os.getenv("ROUTER_GATEWAY_HTTP_HOST", "127.0.0.1"),
                port=int(os.getenv("ROUTER_GATEWAY_HTTP_PORT", "8088")))


if __name__ == "__main__":
    main()
