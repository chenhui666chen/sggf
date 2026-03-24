from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.permissions import require_super_admin
from app.db.base import get_db
from app.models.admin_log import AdminOperationLog
from app.models.user import User
from app.schemas.admin import (
    SystemPointsPricingPolicyResponse,
    SystemPointsPricingPolicyUpdate,
    SystemPointsRuleConfigResponse,
    SystemPointsRuleConfigUpdate,
)
from app.services.points_pricing_policy import (
    POINTS_PRICING_POLICY_OPERATION_TYPE,
    POINTS_PRICING_POLICY_RESOURCE_ID,
    POINTS_PRICING_POLICY_RESOURCE_TYPE,
    PointsPricingPolicyConfig,
    PointsPricingPolicySnapshot,
    build_points_pricing_policy_operating_snapshots,
    get_points_pricing_policy_snapshot,
)
from app.services.user_center_points import (
    POINTS_RULES_OPERATION_TYPE,
    POINTS_RULES_RESOURCE_ID,
    POINTS_RULES_RESOURCE_TYPE,
    UserCenterPointsRuleConfig,
    UserCenterPointsRuleSnapshot,
    get_user_center_points_rule_snapshot,
)


router = APIRouter()


def _points_rule_snapshot_to_response(snapshot: UserCenterPointsRuleSnapshot) -> SystemPointsRuleConfigResponse:
    payload = snapshot.config.to_payload()
    return SystemPointsRuleConfigResponse(
        **payload,
        source=snapshot.source,
        updated_at=snapshot.updated_at,
        updated_by_user_id=snapshot.updated_by_user_id,
        updated_by_username=snapshot.updated_by_username,
    )


def _points_pricing_policy_snapshot_to_response(
    snapshot: PointsPricingPolicySnapshot,
) -> SystemPointsPricingPolicyResponse:
    payload = snapshot.config.to_payload()
    return SystemPointsPricingPolicyResponse(
        **payload,
        source=snapshot.source,
        updated_at=snapshot.updated_at,
        updated_by_user_id=snapshot.updated_by_user_id,
        updated_by_username=snapshot.updated_by_username,
        operating_snapshots=build_points_pricing_policy_operating_snapshots(
            pricing_config=snapshot.config,
        ),
    )


@router.get("/points-rules", response_model=SystemPointsRuleConfigResponse)
async def get_points_rules(
    _current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    snapshot = get_user_center_points_rule_snapshot(db=db)
    return _points_rule_snapshot_to_response(snapshot)


@router.put("/points-rules", response_model=SystemPointsRuleConfigResponse)
async def update_points_rules(
    rule_data: SystemPointsRuleConfigUpdate,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    config = UserCenterPointsRuleConfig(**rule_data.model_dump())
    payload = config.to_payload()

    log = AdminOperationLog(
        user_id=current_user.id,
        username=current_user.username,
        operation_type=POINTS_RULES_OPERATION_TYPE,
        resource_type=POINTS_RULES_RESOURCE_TYPE,
        resource_id=POINTS_RULES_RESOURCE_ID,
        operation_desc="更新积分规则配置",
        request_method="PUT",
        request_path="/api/v1/admin/system/points-rules",
        request_params=payload,
        response_status=status.HTTP_200_OK,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent"),
        duration_ms=0,
        error_message=None,
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    snapshot = get_user_center_points_rule_snapshot(logs=[log])
    return _points_rule_snapshot_to_response(snapshot)


@router.get("/points-pricing-policy", response_model=SystemPointsPricingPolicyResponse)
async def get_points_pricing_policy(
    _current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    snapshot = get_points_pricing_policy_snapshot(db=db)
    return _points_pricing_policy_snapshot_to_response(snapshot)


@router.put("/points-pricing-policy", response_model=SystemPointsPricingPolicyResponse)
async def update_points_pricing_policy(
    policy_data: SystemPointsPricingPolicyUpdate,
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    config = PointsPricingPolicyConfig(**policy_data.model_dump())
    payload = config.to_payload()

    log = AdminOperationLog(
        user_id=current_user.id,
        username=current_user.username,
        operation_type=POINTS_PRICING_POLICY_OPERATION_TYPE,
        resource_type=POINTS_PRICING_POLICY_RESOURCE_TYPE,
        resource_id=POINTS_PRICING_POLICY_RESOURCE_ID,
        operation_desc="更新积分定价策略",
        request_method="PUT",
        request_path="/api/v1/admin/system/points-pricing-policy",
        request_params=payload,
        response_status=status.HTTP_200_OK,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent"),
        duration_ms=0,
        error_message=None,
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    snapshot = get_points_pricing_policy_snapshot(logs=[log])
    return _points_pricing_policy_snapshot_to_response(snapshot)
