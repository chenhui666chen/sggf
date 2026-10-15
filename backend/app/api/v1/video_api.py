import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.permissions import require_super_admin
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.video_api import VideoApiApplication
from app.schemas.video_api import (
    VideoApiApplicationCreate,
    VideoApiApplicationListResponse,
    VideoApiApplicationResponse,
    VideoApiAdminStatusUpdate,
    VideoApiQuotaUpdate,
    VideoGatewayMetricsResponse,
)
from app.services.video_gateway_client import VideoGatewayClient, VideoGatewayUnavailable

def prevent_api_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/v1/video-api", tags=["video-api"],
                   dependencies=[Depends(prevent_api_cache)])
logger = logging.getLogger(__name__)
PLAN_LIMITS = {
    "standard": {"rate_limit_per_second": 1, "burst_capacity": 5, "max_active_jobs": 5, "lifetime_task_limit": 100},
    "professional": {"rate_limit_per_second": 5, "burst_capacity": 20, "max_active_jobs": 20, "lifetime_task_limit": 100},
    "enterprise": {"rate_limit_per_second": 20, "burst_capacity": 100, "max_active_jobs": 100, "lifetime_task_limit": 100},
}


@router.get("/admin/metrics", response_model=VideoGatewayMetricsResponse)
async def admin_metrics(
    window_hours: int = 24,
    current_user: User = Depends(require_super_admin),
):
    if window_hours < 1 or window_hours > 168:
        raise HTTPException(status_code=422, detail="统计窗口必须在 1 到 168 小时之间")
    try:
        return await VideoGatewayClient().metrics_overview(window_hours=window_hours)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频网关监控暂不可用") from exc


def _response(item: VideoApiApplication, *, api_key: str | None = None):
    return VideoApiApplicationResponse(
        id=item.id, name=item.name, status=item.status, plan_code=item.plan_code,
        rate_limit_per_second=item.rate_limit_per_second,
        burst_capacity=item.burst_capacity, max_active_jobs=item.max_active_jobs,
        max_parallel_attempts=item.max_parallel_attempts,
        lifetime_task_limit=item.lifetime_task_limit,
        api_key_prefix=item.api_key_prefix, daily_budget=item.daily_budget,
        monthly_budget=item.monthly_budget, created_at=item.created_at,
        updated_at=item.updated_at, api_key=api_key)


async def _commit_application(db: Session, item: VideoApiApplication, gateway: VideoGatewayClient):
    client_id = item.gateway_client_id
    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError as exc:
        db.rollback()
        try:
            await gateway.set_status(client_id, enabled=False)
        except VideoGatewayUnavailable:
            logger.exception("应用写库失败且网关禁用补偿失败: gateway_client_id=%s", client_id)
        raise HTTPException(status_code=503, detail="应用保存失败，已请求暂停调用，请稍后重试") from exc


@router.get("/applications", response_model=VideoApiApplicationListResponse)
async def list_applications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(VideoApiApplication).filter(VideoApiApplication.user_id == current_user.id).order_by(VideoApiApplication.id.desc()).all()
    return {"items": [_response(item) for item in items]}


@router.post("/applications", response_model=VideoApiApplicationResponse, status_code=201)
async def create_application(payload: VideoApiApplicationCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(User.id).filter(User.id == current_user.id).with_for_update().one()
    if db.query(VideoApiApplication).filter(VideoApiApplication.user_id == current_user.id).count() >= 10:
        raise HTTPException(status_code=409, detail="每个用户最多创建 10 个 API 应用")
    limits = PLAN_LIMITS.get(payload.plan_code)
    if limits is None:
        raise HTTPException(status_code=422, detail="不支持的 API 套餐")
    try:
        gateway = VideoGatewayClient()
        remote = await gateway.create_client(name=payload.name, limits={
            **limits, "max_parallel_attempts": 2, "enabled": False})
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    item = VideoApiApplication(
        user_id=current_user.id, gateway_client_id=remote["id"], name=payload.name,
        status="pending", plan_code=payload.plan_code, api_key_hash=remote["api_key_hash"],
        api_key_prefix=remote["api_key_prefix"], **limits, max_parallel_attempts=2)
    db.add(item)
    await _commit_application(db, item, gateway)
    return _response(item, api_key=remote["api_key"])


@router.post("/applications/{application_id}/rotate-key", response_model=VideoApiApplicationResponse)
async def rotate_application_key(application_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(VideoApiApplication).filter(VideoApiApplication.id == application_id, VideoApiApplication.user_id == current_user.id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    if item.status == "revoked":
        raise HTTPException(status_code=409, detail="已吊销的应用不能轮换 Key")
    try:
        gateway = VideoGatewayClient()
        remote = await gateway.rotate_key(item.gateway_client_id)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    item.api_key_hash = remote["api_key_hash"]
    item.api_key_prefix = remote["api_key_prefix"]
    await _commit_application(db, item, gateway)
    return _response(item, api_key=remote["api_key"])


@router.post("/applications/{application_id}/revoke", response_model=VideoApiApplicationResponse)
async def revoke_application(application_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await _set_application_status(application_id, current_user, db, "revoked", False)


async def _set_application_status(application_id: int, current_user: User, db: Session, app_status: str, enabled: bool):
    item = db.query(VideoApiApplication).filter(VideoApiApplication.id == application_id, VideoApiApplication.user_id == current_user.id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    try:
        gateway = VideoGatewayClient()
        await gateway.set_status(item.gateway_client_id, enabled=enabled)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    item.status = app_status
    await _commit_application(db, item, gateway)
    return _response(item)


@router.get("/admin/applications", response_model=VideoApiApplicationListResponse)
async def admin_list_applications(current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    items = db.query(VideoApiApplication).order_by(VideoApiApplication.id.desc()).all()
    return {"items": [_response(item) for item in items]}


@router.post("/admin/applications/{application_id}/suspend", response_model=VideoApiApplicationResponse)
async def admin_suspend_application(application_id: int, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    item = db.query(VideoApiApplication).filter(VideoApiApplication.id == application_id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    if item.status == "revoked":
        raise HTTPException(status_code=409, detail="已吊销的应用不能恢复")
    try:
        gateway = VideoGatewayClient()
        await gateway.set_status(item.gateway_client_id, enabled=False)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    item.status = "suspended"
    await _commit_application(db, item, gateway)
    return _response(item)


@router.post("/admin/applications/{application_id}/status", response_model=VideoApiApplicationResponse)
async def admin_update_application_status(
    application_id: int,
    payload: VideoApiAdminStatusUpdate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    item = db.query(VideoApiApplication).filter(VideoApiApplication.id == application_id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    if item.status == "revoked" and payload.status != "revoked":
        raise HTTPException(status_code=409, detail="已吊销的应用不能恢复")
    enabled = payload.status == "active"
    try:
        gateway = VideoGatewayClient()
        await gateway.set_status(item.gateway_client_id, enabled=enabled)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    item.status = payload.status
    await _commit_application(db, item, gateway)
    return _response(item)


@router.patch("/admin/applications/{application_id}/quota", response_model=VideoApiApplicationResponse)
async def admin_update_application_quota(
    application_id: int,
    payload: VideoApiQuotaUpdate,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    item = db.query(VideoApiApplication).filter(VideoApiApplication.id == application_id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    limits = payload.model_dump(mode="json", exclude_none=True)
    if not limits:
        return _response(item)
    try:
        gateway = VideoGatewayClient()
        await gateway.update_limits(item.gateway_client_id, limits)
    except VideoGatewayUnavailable as exc:
        raise HTTPException(status_code=503, detail="视频 API 服务暂不可用") from exc
    for key, value in limits.items():
        setattr(item, key, value)
    await _commit_application(db, item, gateway)
    return _response(item)
