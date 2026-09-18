import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT_DIR.parent
for path in (REPO_ROOT, ROOT_DIR):
    normalized_path = str(path)
    if normalized_path not in sys.path:
        sys.path.insert(0, normalized_path)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import app.core.security as security
from app.api.v1 import auth as auth_api
from app.api.v1.admin import router as admin_router
from app.api.v1.user_center import router as user_center_router
from app.core.security import create_access_token
from app.db.base import Base, get_db
from app.models.admin_log import AdminOperationLog
from app.models.audit_log import AuditLog
from app.models.audiobook import AudiobookProject
from app.models.dreamweaver import DreamweaverProject
from app.models.password_history import PasswordHistory
from app.models.project import Chapter, Project
from app.models.role import Permission, Role, role_permissions, user_roles
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs) -> Response:
        return self.request("PATCH", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Role.__table__,
            Permission.__table__,
            user_roles,
            role_permissions,
            AdminOperationLog.__table__,
            AuditLog.__table__,
            PasswordHistory.__table__,
            Project.__table__,
            Chapter.__table__,
            UserAssetRecord.__table__,
            AudiobookProject.__table__,
            DreamweaverProject.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(user_center_router)
    app.include_router(auth_api.router)

    # 本文件走真实 get_current_user 链路（不 override），jti 吊销校验依赖 Redis，
    # 测试环境必须替换为内存 fake（P1-3.5）
    security.jti_revocation_service = _FakeJtiService()

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[security.get_db] = override_get_db
    return CompatTestClient(app), testing_session_local


class _FakeJtiService:
    """测试用内存 jti 吊销服务，替代 Redis 实现（P1-3.5）。"""

    def __init__(self):
        self.revoked: set[str] = set()

    async def revoke(self, jti: str, exp: int) -> None:
        self.revoked.add(jti)

    async def is_revoked(self, jti: str) -> bool:
        return jti in self.revoked


def build_auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def create_user(session_factory: sessionmaker, *, username: str, email: str) -> User:
    db = session_factory()
    try:
        user = User(username=username, email=email, full_name=username, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def create_role(session_factory: sessionmaker, *, name: str, code: str) -> Role:
    db = session_factory()
    try:
        role = Role(name=name, code=code, description=f"{name} role", is_active=True, is_system=False)
        db.add(role)
        db.commit()
        db.refresh(role)
        return role
    finally:
        db.close()


def assign_role(session_factory: sessionmaker, *, user_id: int, role_id: int) -> None:
    db = session_factory()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        role = db.query(Role).filter(Role.id == role_id).first()
        if user is None or role is None:
            raise RuntimeError("用户或角色不存在")
        user.roles.append(role)
        db.add(user)
        db.commit()
    finally:
        db.close()


def create_project(session_factory: sessionmaker, *, user_id: int, display_no: int, title: str) -> Project:
    db = session_factory()
    try:
        project = Project(user_id=user_id, display_no=display_no, title=title)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project
    finally:
        db.close()


def create_user_asset(
    session_factory: sessionmaker,
    *,
    user_id: int,
    title: str,
    source_uri: str,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> UserAssetRecord:
    db = session_factory()
    try:
        asset_uuid = f"asset-studio-{abs(hash((user_id, title, source_uri)))}"
        asset = UserAssetRecord(
            user_id=user_id,
            source_module="asset_studio",
            asset_kind="image",
            asset_class="reusable",
            asset_uuid=asset_uuid,
            storage_mode="durable_cloud",
            title=title,
            source_uri=source_uri,
            preview_uri=source_uri,
            download_uri=source_uri,
            tags=[],
            metadata_json={},
            source_payload_json={},
            is_favorite=False,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    finally:
        db.close()


def create_points_billing_event(
    session_factory: sessionmaker,
    *,
    operator_user_id: int,
    operator_username: str,
    target_user_id: int,
    billing_key: str,
    module_key: str,
    event_kind: str,
    amount_points: float,
    amount_yuan: float | None,
    title: str,
    summary: str,
    project_id: int | None = None,
    audiobook_project_id: int | None = None,
    run_id: str | None = None,
    stage: str | None = None,
    pricing_status: str | None = None,
    task_status: str | None = None,
    action_path: str | None = None,
    action_label: str | None = None,
    operating_snapshot: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> AdminOperationLog:
    operation_type_map = {
        "freeze": "POINTS_BILLING_FREEZE",
        "settle": "POINTS_BILLING_SETTLE",
        "release": "POINTS_BILLING_RELEASE",
    }
    db = session_factory()
    try:
        log = AdminOperationLog(
            user_id=operator_user_id,
            username=operator_username,
            operation_type=operation_type_map[event_kind],
            resource_type="USER_POINTS_BILLING",
            resource_id=target_user_id,
            operation_desc=f"create points billing {event_kind}",
            request_method="SYSTEM",
            request_path="/internal/tests/points-billing",
            request_params={
                "billing_key": billing_key,
                "module_key": module_key,
                "event_kind": event_kind,
                "target_user_id": target_user_id,
                "project_id": project_id,
                "audiobook_project_id": audiobook_project_id,
                "run_id": run_id,
                "stage": stage,
                "pricing_status": pricing_status,
                "task_status": task_status,
                "action_path": action_path,
                "action_label": action_label,
                "amount_points": amount_points,
                "amount_yuan": amount_yuan,
                "title": title,
                "summary": summary,
                "operating_snapshot": operating_snapshot,
            },
            response_status=201,
            ip_address="127.0.0.1",
            user_agent="pytest",
            duration_ms=0,
            error_message=None,
            created_at=created_at,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
    finally:
        db.close()


def test_admin_can_create_and_list_user_points_adjustments():
    client, session_factory = build_test_client()
    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    response = client.post(
        f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        headers=build_auth_headers(admin.id),
        json={
            "delta": 20,
            "reason": "补发活动积分",
            "adjustment_type": "manual_grant",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["target_user_id"] == target_user.id
    assert payload["operator_user_id"] == admin.id
    assert payload["delta"] == 20.0
    assert payload["reason"] == "补发活动积分"
    assert payload["adjustment_type"] == "manual_grant"

    list_response = client.get(
        f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        headers=build_auth_headers(admin.id),
    )
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["delta"] == 20.0
    assert items[0]["operator_username"] == admin.username


def test_admin_points_account_reflects_positive_manual_adjustment():
    client, session_factory = build_test_client()

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    create_adjustment_response = client.post(
        f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        headers=build_auth_headers(admin.id),
        json={
            "delta": 20,
            "reason": "补发活动积分",
            "adjustment_type": "manual_grant",
        },
    )
    assert create_adjustment_response.status_code == 201

    account_response = client.get(
        f"/api/v1/admin/users/{target_user.id}/points-account",
        headers=build_auth_headers(admin.id),
    )
    assert account_response.status_code == 200
    payload = account_response.json()

    assert payload["target_user_id"] == target_user.id
    assert payload["status"] == "partial"
    assert payload["balance"] == 20.0
    assert payload["frozen"] == 0.0
    assert payload["available"] == 20.0
    assert payload["connected_source_count"] == 1
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["source_label"] == "人工补发 / 充值 / 扣减"
    assert payload["entries"][0]["amount"] == 20.0
    assert payload["entries"][0]["direction"] == "income"


def test_admin_points_adjustment_rejects_expired_positive_grant():
    client, session_factory = build_test_client()

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    response = client.post(
        f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        headers=build_auth_headers(admin.id),
        json={
            "delta": 20,
            "reason": "过期补发不应入账",
            "adjustment_type": "manual_grant",
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "正向积分调整的过期时间必须晚于当前时间"


def test_admin_can_list_user_points_billing_events():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)
    project = create_project(session_factory, user_id=target_user.id, display_no=1, title="计费事件项目")

    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="dreamweaver:run-1",
        module_key="dreamweaver",
        event_kind="freeze",
        amount_points=200.4,
        amount_yuan=1.67,
        title="短剧运行 run-1",
        summary="任务开始时冻结积分",
        project_id=project.id,
        run_id="run-1",
        stage="storyboard",
        pricing_status="estimated",
        task_status="running",
        action_path=f"/drama/{project.id}",
        action_label="查看短剧模块",
        created_at=now - timedelta(minutes=2),
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="dreamweaver:run-1",
        module_key="dreamweaver",
        event_kind="settle",
        amount_points=182.4,
        amount_yuan=1.52,
        title="短剧运行 run-1",
        summary="任务完成后按合同快照结算",
        project_id=project.id,
        run_id="run-1",
        stage="delivery",
        pricing_status="actual",
        task_status="completed",
        action_path=f"/drama/{project.id}",
        action_label="查看短剧模块",
        operating_snapshot={
            "module_key": "dreamweaver",
            "provider_key": None,
            "user_basis_yuan": 1.52,
            "user_billed_yuan": 1.52,
            "supplier_list_price_yuan": 1.52,
            "supplier_discount_rate": 0.2,
            "supplier_discount_rate_source": "env:POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT",
            "supplier_discounted_cost_yuan": 1.22,
            "supplier_discount_yuan": 0.3,
            "captured_discount_yuan": 0.3,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 1.52,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": 0.3,
            "platform_margin_rate": 0.2,
            "margin_status": "healthy",
            "negative_margin_blocked": False,
        },
        created_at=now - timedelta(minutes=1),
    )

    response = client.get(
        f"/api/v1/admin/users/{target_user.id}/points-billing-events?limit=10",
        headers=build_auth_headers(admin.id),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2

    latest_item = items[0]
    assert latest_item["event_kind"] == "settle"
    assert latest_item["event_label"] == "结算"
    assert latest_item["module_key"] == "dreamweaver"
    assert latest_item["module_label"] == "短剧"
    assert latest_item["billing_key"] == "dreamweaver:run-1"
    assert latest_item["amount_points"] == 182.4
    assert latest_item["amount_yuan"] == 1.52
    assert latest_item["run_id"] == "run-1"
    assert latest_item["pricing_status"] == "actual"
    assert latest_item["task_status"] == "completed"
    assert latest_item["action_path"] == f"/drama/{project.id}"
    assert latest_item["action_label"] == "查看短剧模块"
    assert latest_item["operating_snapshot"] is not None
    assert latest_item["operating_snapshot"]["module_label"] == "短剧"
    assert latest_item["operating_snapshot"]["supplier_discount_rate"] == 0.2
    assert latest_item["operating_snapshot"]["platform_margin_rate"] == 0.2

    freeze_item = items[1]
    assert freeze_item["event_kind"] == "freeze"
    assert freeze_item["event_label"] == "冻结"
    assert freeze_item["operating_snapshot"] is None


def test_admin_can_filter_global_points_billing_events():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    other_user = create_user(session_factory, username="other_user", email="other@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)
    project = create_project(session_factory, user_id=target_user.id, display_no=1, title="全局计费筛选项目")
    other_project = create_project(session_factory, user_id=other_user.id, display_no=2, title="其他项目")

    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="dreamweaver:run-warning",
        module_key="dreamweaver",
        event_kind="settle",
        amount_points=182.4,
        amount_yuan=1.52,
        title="短剧运行 run-warning",
        summary="关键字 warning task",
        project_id=project.id,
        run_id="run-warning",
        stage="delivery",
        pricing_status="actual",
        task_status="completed",
        operating_snapshot={
            "module_key": "dreamweaver",
            "provider_key": None,
            "user_basis_yuan": 1.52,
            "user_billed_yuan": 1.52,
            "supplier_list_price_yuan": 1.52,
            "supplier_discount_rate": 0.05,
            "supplier_discount_rate_source": "env:POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT",
            "supplier_discounted_cost_yuan": 1.44,
            "supplier_discount_yuan": 0.08,
            "captured_discount_yuan": 0.08,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 1.52,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": 0.08,
            "platform_margin_rate": 0.0526,
            "margin_status": "warning",
            "negative_margin_blocked": False,
        },
        created_at=now - timedelta(minutes=2),
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="audiobook:1",
        module_key="audiobook",
        event_kind="settle",
        amount_points=96.0,
        amount_yuan=0.8,
        title="有声书项目 #1",
        summary="用于排除的有声书事件",
        project_id=project.id,
        audiobook_project_id=1,
        pricing_status="actual",
        task_status="completed",
        operating_snapshot={
            "module_key": "audiobook",
            "provider_key": "aliyun",
            "user_basis_yuan": 0.8,
            "user_billed_yuan": 0.8,
            "supplier_list_price_yuan": 0.8,
            "supplier_discount_rate": 0.35,
            "supplier_discount_rate_source": "env:POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT",
            "supplier_discounted_cost_yuan": 0.52,
            "supplier_discount_yuan": 0.28,
            "captured_discount_yuan": 0.28,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 0.8,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": 0.28,
            "platform_margin_rate": 0.35,
            "margin_status": "healthy",
            "negative_margin_blocked": False,
        },
        created_at=now - timedelta(minutes=1),
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=other_user.id,
        operator_username=other_user.username,
        target_user_id=other_user.id,
        billing_key="dreamweaver:run-other",
        module_key="dreamweaver",
        event_kind="freeze",
        amount_points=220.0,
        amount_yuan=1.83,
        title="短剧运行 run-other",
        summary="其他用户事件",
        project_id=other_project.id,
        run_id="run-other",
        stage="storyboard",
        pricing_status="estimated",
        task_status="running",
        created_at=now,
    )

    response = client.get(
        f"/api/v1/admin/billing/points-events?page=1&page_size=10&user_id={target_user.id}&module_key=dreamweaver&event_kind=settle&margin_status=warning&keyword=run-warning",
        headers=build_auth_headers(admin.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total_pages"] == 1
    assert len(payload["items"]) == 1
    assert payload["summary"]["recent_7d_settle_count"] == 1
    assert payload["summary"]["settle_event_count"] == 1
    assert payload["summary"]["warning_event_count"] == 1
    assert payload["summary"]["negative_event_count"] == 0
    assert len(payload["summary"]["module_summaries"]) == 1
    assert payload["summary"]["module_summaries"][0]["module_key"] == "dreamweaver"

    item = payload["items"][0]
    assert item["target_user_id"] == target_user.id
    assert item["module_key"] == "dreamweaver"
    assert item["event_kind"] == "settle"
    assert item["billing_key"] == "dreamweaver:run-warning"
    assert item["run_id"] == "run-warning"
    assert item["operating_snapshot"] is not None
    assert item["operating_snapshot"]["margin_status"] == "warning"


def test_admin_global_points_billing_summary_ignores_list_event_and_margin_filters():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)
    project = create_project(session_factory, user_id=target_user.id, display_no=1, title="聚合概览项目")

    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="dreamweaver:run-warning",
        module_key="dreamweaver",
        event_kind="settle",
        amount_points=182.4,
        amount_yuan=1.52,
        title="短剧运行 run-warning",
        summary="低毛利样本",
        project_id=project.id,
        run_id="run-warning",
        stage="delivery",
        pricing_status="actual",
        task_status="completed",
        operating_snapshot={
            "module_key": "dreamweaver",
            "provider_key": None,
            "user_basis_yuan": 1.52,
            "user_billed_yuan": 1.52,
            "supplier_list_price_yuan": 1.52,
            "supplier_discount_rate": 0.05,
            "supplier_discount_rate_source": "env:POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT",
            "supplier_discounted_cost_yuan": 1.44,
            "supplier_discount_yuan": 0.08,
            "captured_discount_yuan": 0.08,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 1.52,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": 0.08,
            "platform_margin_rate": 0.0526,
            "margin_status": "warning",
            "negative_margin_blocked": False,
        },
        created_at=now - timedelta(minutes=10),
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="dreamweaver:run-negative",
        module_key="dreamweaver",
        event_kind="settle",
        amount_points=240.0,
        amount_yuan=2.0,
        title="短剧运行 run-negative",
        summary="负毛利样本",
        project_id=project.id,
        run_id="run-negative",
        stage="delivery",
        pricing_status="actual",
        task_status="completed",
        operating_snapshot={
            "module_key": "dreamweaver",
            "provider_key": None,
            "user_basis_yuan": 2.0,
            "user_billed_yuan": 2.0,
            "supplier_list_price_yuan": 2.0,
            "supplier_discount_rate": -0.1,
            "supplier_discount_rate_source": "manual:test-negative",
            "supplier_discounted_cost_yuan": 2.2,
            "supplier_discount_yuan": -0.2,
            "captured_discount_yuan": -0.2,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 2.0,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": -0.2,
            "platform_margin_rate": -0.1,
            "margin_status": "negative",
            "negative_margin_blocked": True,
        },
        created_at=now - timedelta(days=1),
    )
    create_points_billing_event(
        session_factory,
        operator_user_id=target_user.id,
        operator_username=target_user.username,
        target_user_id=target_user.id,
        billing_key="audiobook:old-healthy",
        module_key="audiobook",
        event_kind="settle",
        amount_points=96.0,
        amount_yuan=0.8,
        title="有声书项目 old-healthy",
        summary="较早的健康毛利样本",
        project_id=project.id,
        audiobook_project_id=9,
        pricing_status="actual",
        task_status="completed",
        operating_snapshot={
            "module_key": "audiobook",
            "provider_key": "aliyun",
            "user_basis_yuan": 0.8,
            "user_billed_yuan": 0.8,
            "supplier_list_price_yuan": 0.8,
            "supplier_discount_rate": 0.35,
            "supplier_discount_rate_source": "env:POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT",
            "supplier_discounted_cost_yuan": 0.52,
            "supplier_discount_yuan": 0.28,
            "captured_discount_yuan": 0.28,
            "shared_discount_yuan": 0.0,
            "policy_target_user_billed_yuan": 0.8,
            "policy_alignment_gap_yuan": 0.0,
            "platform_gross_profit_yuan": 0.28,
            "platform_margin_rate": 0.35,
            "margin_status": "healthy",
            "negative_margin_blocked": False,
        },
        created_at=now - timedelta(days=8),
    )

    response = client.get(
        f"/api/v1/admin/billing/points-events?page=1&page_size=10&user_id={target_user.id}&event_kind=freeze&margin_status=negative",
        headers=build_auth_headers(admin.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["items"] == []

    summary = payload["summary"]
    assert summary["recent_7d_settle_count"] == 2
    assert summary["settle_event_count"] == 3
    assert summary["warning_event_count"] == 1
    assert summary["negative_event_count"] == 1
    assert abs(summary["total_user_billed_yuan"] - 4.32) < 1e-9
    assert abs(summary["total_platform_gross_profit_yuan"] - 0.16) < 1e-9
    assert len(summary["module_summaries"]) == 2

    dreamweaver_summary = summary["module_summaries"][0]
    assert dreamweaver_summary["module_key"] == "dreamweaver"
    assert dreamweaver_summary["settle_event_count"] == 2
    assert dreamweaver_summary["warning_event_count"] == 1
    assert dreamweaver_summary["negative_event_count"] == 1
    assert abs(dreamweaver_summary["total_user_billed_yuan"] - 3.52) < 1e-9
    assert abs(dreamweaver_summary["total_platform_gross_profit_yuan"] - (-0.12)) < 1e-9

    audiobook_summary = summary["module_summaries"][1]
    assert audiobook_summary["module_key"] == "audiobook"
    assert audiobook_summary["settle_event_count"] == 1
    assert audiobook_summary["warning_event_count"] == 0
    assert audiobook_summary["negative_event_count"] == 0
    assert abs(audiobook_summary["total_user_billed_yuan"] - 0.8) < 1e-9
    assert abs(audiobook_summary["total_platform_gross_profit_yuan"] - 0.28) < 1e-9


def test_manual_points_adjustment_is_reflected_in_user_center_points_account():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    target_user = create_user(session_factory, username="target_user", email="target@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    project = create_project(session_factory, user_id=target_user.id, display_no=1, title="目标项目")
    create_user_asset(
        session_factory,
        user_id=target_user.id,
        title="基础资产",
        source_uri="https://example.com/assets/base.png",
        created_at=now,
        updated_at=now,
    )

    create_adjustment_response = client.post(
        f"/api/v1/admin/users/{target_user.id}/points-adjustments",
        headers=build_auth_headers(admin.id),
        json={
            "delta": -1.5,
            "reason": "纠正重复补发",
            "adjustment_type": "manual_deduction",
        },
    )
    assert create_adjustment_response.status_code == 201

    overview_response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(target_user.id),
    )
    assert overview_response.status_code == 200
    payload = overview_response.json()

    assert payload["connected_overview"]["project_count"] == 1
    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == 1.5
    assert payload["points_account"]["frozen"] == 0.0
    assert payload["points_account"]["connected_source_count"] == 2
    assert payload["points_rules"]["source"] == "default"
    connected_keys = {item["key"] for item in payload["benefits"]["connected_items"]}
    assert "points-account" in connected_keys
    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert points_entries["manual-adjustment-1"]["direction"] == "expense"
    assert points_entries["manual-adjustment-1"]["status"] == "active"
    assert points_entries["manual-adjustment-1"]["source_label"] == "人工补发 / 充值 / 扣减"


def test_super_admin_can_read_and_update_points_rules():
    client, session_factory = build_test_client()
    super_admin = create_user(session_factory, username="super_admin_user", email="super_admin@example.com")
    super_admin_role = create_role(session_factory, name="瓒呯骇绠＄悊鍛?", code="super_admin")
    assign_role(session_factory, user_id=super_admin.id, role_id=super_admin_role.id)

    initial_response = client.get(
        "/api/v1/admin/system/points-rules",
        headers=build_auth_headers(super_admin.id),
    )
    assert initial_response.status_code == 200
    initial_payload = initial_response.json()
    assert initial_payload["source"] == "default"
    assert initial_payload["updated_at"] is None
    assert initial_payload["updated_by_username"] is None

    update_response = client.put(
        "/api/v1/admin/system/points-rules",
        headers=build_auth_headers(super_admin.id),
        json={
            "reusable_asset_reward": 4.5,
            "deliverable_asset_reward": 12,
            "audiobook_completion_reward": 9,
            "dreamweaver_completion_reward": 6.5,
            "running_audiobook_frozen": 3,
            "running_dreamweaver_frozen": 2.5,
            "reward_ttl_days": 45,
            "expiring_notice_days": 10,
        },
    )
    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["source"] == "admin_log"
    assert updated_payload["reusable_asset_reward"] == 4.5
    assert updated_payload["reward_ttl_days"] == 45
    assert updated_payload["expiring_notice_days"] == 10
    assert updated_payload["updated_by_user_id"] == super_admin.id
    assert updated_payload["updated_by_username"] == super_admin.username
    assert updated_payload["updated_at"] is not None

    latest_response = client.get(
        "/api/v1/admin/system/points-rules",
        headers=build_auth_headers(super_admin.id),
    )
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["source"] == "admin_log"
    assert latest_payload["deliverable_asset_reward"] == 12.0
    assert latest_payload["running_dreamweaver_frozen"] == 2.5


def test_admin_points_rules_requires_super_admin():
    client, session_factory = build_test_client()
    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    admin_role = create_role(session_factory, name="绠＄悊鍛?", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    response = client.get(
        "/api/v1/admin/system/points-rules",
        headers=build_auth_headers(admin.id),
    )
    assert response.status_code == 403


def test_super_admin_can_read_and_update_points_pricing_policy():
    client, session_factory = build_test_client()
    super_admin = create_user(session_factory, username="super_admin_user", email="super_admin@example.com")
    super_admin_role = create_role(session_factory, name="鐡掑懐楠囩粻锛勬倞閸?", code="super_admin")
    assign_role(session_factory, user_id=super_admin.id, role_id=super_admin_role.id)

    initial_response = client.get(
        "/api/v1/admin/system/points-pricing-policy",
        headers=build_auth_headers(super_admin.id),
    )
    assert initial_response.status_code == 200
    initial_payload = initial_response.json()
    assert initial_payload["source"] == "default"
    assert initial_payload["updated_at"] is None
    assert initial_payload["updated_by_username"] is None
    assert initial_payload["points_per_yuan"] == 100
    assert initial_payload["user_price_basis"] == "public_list_price"
    assert initial_payload["user_price_rate"] == 1.0
    assert initial_payload["provider_discount_capture_rate"] == 1.0
    assert initial_payload["freeze_buffer_rate"] == 0.05
    assert initial_payload["margin_warning_rate"] == 0.15
    assert initial_payload["negative_margin_block_enabled"] is True

    update_response = client.put(
        "/api/v1/admin/system/points-pricing-policy",
        headers=build_auth_headers(super_admin.id),
        json={
            "points_per_yuan": 120,
            "user_price_basis": "standard_price_table",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 0.9,
            "freeze_buffer_rate": 0.08,
            "margin_warning_rate": 0.12,
            "negative_margin_block_enabled": False,
        },
    )
    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["source"] == "admin_log"
    assert updated_payload["points_per_yuan"] == 120
    assert updated_payload["user_price_basis"] == "standard_price_table"
    assert updated_payload["user_price_rate"] == 1.0
    assert updated_payload["provider_discount_capture_rate"] == 0.9
    assert updated_payload["freeze_buffer_rate"] == 0.08
    assert updated_payload["margin_warning_rate"] == 0.12
    assert updated_payload["negative_margin_block_enabled"] is False
    assert updated_payload["updated_by_user_id"] == super_admin.id
    assert updated_payload["updated_by_username"] == super_admin.username
    assert updated_payload["updated_at"] is not None

    latest_response = client.get(
        "/api/v1/admin/system/points-pricing-policy",
        headers=build_auth_headers(super_admin.id),
    )
    assert latest_response.status_code == 200
    latest_payload = latest_response.json()
    assert latest_payload["source"] == "admin_log"
    assert latest_payload["points_per_yuan"] == 120
    assert latest_payload["provider_discount_capture_rate"] == 0.9
    assert latest_payload["negative_margin_block_enabled"] is False


def test_points_pricing_policy_response_includes_operating_snapshots():
    original_audiobook_discount_env = os.environ.get("POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT")
    original_dreamweaver_discount_env = os.environ.get("POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT")
    os.environ["POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT"] = "0.35"
    os.environ["POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"] = "0.2"

    try:
        client, session_factory = build_test_client()
        super_admin = create_user(session_factory, username="super_admin_user", email="super_admin@example.com")
        super_admin_role = create_role(session_factory, name="瓒呯骇绠＄悊鍛?", code="super_admin")
        assign_role(session_factory, user_id=super_admin.id, role_id=super_admin_role.id)

        response = client.get(
            "/api/v1/admin/system/points-pricing-policy",
            headers=build_auth_headers(super_admin.id),
        )
        assert response.status_code == 200

        payload = response.json()
        operating_snapshots = {item["module_key"]: item for item in payload["operating_snapshots"]}

        assert set(operating_snapshots.keys()) == {
            "audiobook",
            "dreamweaver",
            "novel",
            "book_parser",
            "asset_studio",
        }

        audiobook_snapshot = operating_snapshots["audiobook"]
        assert audiobook_snapshot["module_label"] == "有声书"
        assert audiobook_snapshot["supplier_list_price_yuan"] == 1.0
        assert audiobook_snapshot["supplier_discount_rate"] == 0.35
        assert audiobook_snapshot["supplier_discount_rate_source"] == "env:POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT"
        assert audiobook_snapshot["supplier_discounted_cost_yuan"] == 0.65
        assert audiobook_snapshot["platform_gross_profit_yuan"] == 0.35
        assert audiobook_snapshot["platform_margin_rate"] == 0.35

        dreamweaver_snapshot = operating_snapshots["dreamweaver"]
        assert dreamweaver_snapshot["module_label"] == "短剧"
        assert dreamweaver_snapshot["supplier_list_price_yuan"] == 1.0
        assert dreamweaver_snapshot["supplier_discount_rate"] == 0.2
        assert dreamweaver_snapshot["supplier_discount_rate_source"] == "env:POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"
        assert dreamweaver_snapshot["supplier_discounted_cost_yuan"] == 0.8
        assert dreamweaver_snapshot["platform_gross_profit_yuan"] == 0.2
        assert dreamweaver_snapshot["platform_margin_rate"] == 0.2
        assert dreamweaver_snapshot["margin_status"] == "healthy"
        assert dreamweaver_snapshot["negative_margin_blocked"] is False

        assert operating_snapshots["novel"]["module_label"] == "小说协同"
        assert operating_snapshots["book_parser"]["module_label"] == "拆书分析"
        assert operating_snapshots["asset_studio"]["module_label"] == "资产生成"
    finally:
        if original_audiobook_discount_env is None:
            os.environ.pop("POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT", None)
        else:
            os.environ["POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_DEFAULT"] = original_audiobook_discount_env

        if original_dreamweaver_discount_env is None:
            os.environ.pop("POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT", None)
        else:
            os.environ["POINTS_POLICY_DREAMWEAVER_PROVIDER_DISCOUNT_RATE_DEFAULT"] = original_dreamweaver_discount_env


def test_admin_points_pricing_policy_requires_super_admin():
    client, session_factory = build_test_client()
    admin = create_user(session_factory, username="admin_user", email="admin@example.com")
    admin_role = create_role(session_factory, name="缁狅紕鎮婇崨?", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    response = client.get(
        "/api/v1/admin/system/points-pricing-policy",
        headers=build_auth_headers(admin.id),
    )
    assert response.status_code == 403


def test_admin_disable_user_increments_token_version():
    """管理员禁用账号必须递增 token_version，使该用户全部已签发 JWT 立即失效。"""
    from app.api.v1.admin.users import update_user_status
    from app.schemas.admin import UserStatusUpdate

    _, session_factory = build_test_client()
    target = create_user(session_factory, username="disable_me", email="disable_me@example.com")
    admin = create_user(session_factory, username="admin_tv", email="admin_tv@example.com")
    assert target.token_version == 1

    db = session_factory()
    try:
        asyncio.run(
            update_user_status(
                user_id=target.id,
                status_data=UserStatusUpdate(is_active=False),
                current_user=admin,
                db=db,
            )
        )
    finally:
        db.close()

    db = session_factory()
    try:
        u = db.query(User).filter(User.id == target.id).first()
        assert u.is_active is False
        assert u.token_version == 2  # 禁用必须吊销全部已签发 JWT
    finally:
        db.close()


def test_disable_then_reenable_user_revokes_old_token_end_to_end():
    """走 HTTP 层验证：禁用→重新启用后，禁用前签发的旧 JWT 调 /me 仍 401（tv 递增生效）。"""
    client, session_factory = build_test_client()
    target = create_user(session_factory, username="e2e_target", email="e2e_target@example.com")
    admin = create_user(session_factory, username="e2e_admin", email="e2e_admin@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=admin.id, role_id=admin_role.id)

    # 禁用前签发的旧 token（tv=1）
    old_target_token = create_access_token(data={"sub": str(target.id), "tv": 1})

    disable_resp = client.patch(
        f"/api/v1/admin/users/{target.id}/status",
        json={"is_active": False},
        headers=build_auth_headers(admin.id),
    )
    assert disable_resp.status_code == 200

    enable_resp = client.patch(
        f"/api/v1/admin/users/{target.id}/status",
        json={"is_active": True},
        headers=build_auth_headers(admin.id),
    )
    assert enable_resp.status_code == 200

    # 旧 token（tv=1）应已被 tv 递增吊销：重新启用后仍 401（不复活）
    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {old_target_token}"},
    )
    assert me_resp.status_code == 401


# ============================================================
# P1-3.9 提权防护（2026-08-28 批次 4）
# ============================================================

def _make_admin_user(session_factory, *, username: str, email: str, role_code: str) -> User:
    """创建带指定角色码的管理员（admin / super_admin）并返回。

    测试环境无 seed 迁移，按需自建系统角色（生产环境由 3.9 seed 迁移预置）。
    """
    user = create_user(session_factory, username=username, email=email)
    role = ensure_role(session_factory, code=role_code)
    assign_role(session_factory, user_id=user.id, role_id=role.id)
    return user


def ensure_role(session_factory, *, code: str, name: str | None = None) -> Role:
    """按 code 查找系统角色，不存在则创建（模拟 3.9 seed 迁移预置效果）。"""
    db = session_factory()
    try:
        role = db.query(Role).filter(Role.code == code).first()
    finally:
        db.close()
    if role is not None:
        return role
    return create_role(session_factory, name=name or code, code=code)


def test_admin_cannot_assign_super_admin_role():
    """提权防护：普通 admin 不得给任何人（含自己）分配 super_admin 角色。"""
    client, session_factory = build_test_client()
    admin = _make_admin_user(session_factory, username="ops_admin", email="ops@example.com", role_code="admin")
    target = create_user(session_factory, username="target_user", email="target@example.com")
    super_admin_role = ensure_role(session_factory, code="super_admin")

    # admin 尝试给目标用户分配 super_admin -> 403
    resp = client.post(
        f"/api/v1/admin/users/{target.id}/roles",
        json={"role_ids": [super_admin_role.id]},
        headers=build_auth_headers(admin.id),
    )
    assert resp.status_code == 403

    # admin 尝试通过创建用户接口分配 super_admin -> 403
    create_resp = client.post(
        "/api/v1/admin/users",
        json={
            "username": "new_user",
            "email": "new@example.com",
            "password": "Pass123456",
            "role_ids": [super_admin_role.id],
        },
        headers=build_auth_headers(admin.id),
    )
    assert create_resp.status_code == 403


def test_admin_can_assign_non_super_admin_roles():
    """admin 仍可分配 user/admin 等非超管角色（日常管理能力保留）。"""
    client, session_factory = build_test_client()
    admin = _make_admin_user(session_factory, username="ops_admin2", email="ops2@example.com", role_code="admin")
    target = create_user(session_factory, username="target_user2", email="target2@example.com")
    admin_role = ensure_role(session_factory, code="admin")

    resp = client.post(
        f"/api/v1/admin/users/{target.id}/roles",
        json={"role_ids": [admin_role.id]},
        headers=build_auth_headers(admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["roles"][0]["code"] == "admin"


def test_super_admin_can_assign_super_admin_role():
    """super_admin 仍可分配 super_admin 角色（超管治理能力保留）。"""
    client, session_factory = build_test_client()
    super_admin = _make_admin_user(
        session_factory, username="root_admin", email="root@example.com", role_code="super_admin"
    )
    target = create_user(session_factory, username="target_user3", email="target3@example.com")
    super_admin_role = ensure_role(session_factory, code="super_admin")

    resp = client.post(
        f"/api/v1/admin/users/{target.id}/roles",
        json={"role_ids": [super_admin_role.id]},
        headers=build_auth_headers(super_admin.id),
    )
    assert resp.status_code == 200
    assert resp.json()["roles"][0]["code"] == "super_admin"


def test_admin_cannot_edit_target_roles_to_super_admin():
    """提权防护：update_user 走 role_ids 同样不得给目标赋 super_admin。"""
    client, session_factory = build_test_client()
    admin = _make_admin_user(session_factory, username="ops_admin3", email="ops3@example.com", role_code="admin")
    target = create_user(session_factory, username="target_user4", email="target4@example.com")
    super_admin_role = ensure_role(session_factory, code="super_admin")

    resp = client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"role_ids": [super_admin_role.id]},
        headers=build_auth_headers(admin.id),
    )
    assert resp.status_code == 403


def test_sql_query_execute_requires_super_admin():
    """任意 SQL 执行端点只能 super_admin 使用，普通 admin 403。"""
    client, session_factory = build_test_client()
    admin = _make_admin_user(session_factory, username="ops_admin4", email="ops4@example.com", role_code="admin")
    super_admin = _make_admin_user(
        session_factory, username="root_admin2", email="root2@example.com", role_code="super_admin"
    )

    # admin 不可执行
    denied = client.post(
        "/api/v1/admin/query/execute",
        params={"sql": "SELECT 1"},
        headers=build_auth_headers(admin.id),
    )
    assert denied.status_code == 403

    # super_admin 权限放行：进入执行逻辑。
    # 注：测试库为 sqlite，不支持 PG 的 SET statement_timeout，执行阶段会 500；
    # 本测试只验证权限边界（admin 拒 / super_admin 放行），生产 PostgreSQL 下返回 200。
    allowed = client.post(
        "/api/v1/admin/query/execute",
        params={"sql": "SELECT 1"},
        headers=build_auth_headers(super_admin.id),
    )
    assert allowed.status_code not in (403, 401)


def test_admin_create_user_records_password_history():
    """管理员创建用户必须登记初始密码入历史（评审 #3）：否则该用户可改回初始密码。"""
    from app.services.password_history_service import hash_password_for_history

    client, session_factory = build_test_client()
    admin = _make_admin_user(
        session_factory, username="admin_hist", email="ah@example.com", role_code="admin"
    )
    response = client.post(
        "/api/v1/admin/users",
        json={
            "username": "managed_user",
            "email": "mu@example.com",
            "password": "Managed1x",
        },
        headers=build_auth_headers(admin.id),
    )
    assert response.status_code == 201

    db = session_factory()
    try:
        user = db.query(User).filter(User.username == "managed_user").first()
        assert user is not None
        rows = db.query(PasswordHistory).filter(PasswordHistory.user_id == user.id).all()
        assert len(rows) == 1
        assert rows[0].password_pepper_hash == hash_password_for_history("Managed1x")
    finally:
        db.close()


def test_audit_logs_endpoint_admin_only_and_masked():
    """审计日志查询（P2-4.4）：仅管理员可查；返回 IP/UA 为脱敏哈希。"""
    from app.services.audit_log_service import record_audit

    client, session_factory = build_test_client()
    super_admin = _make_admin_user(
        session_factory, username="audit_root", email="audit_root@example.com", role_code="super_admin"
    )
    regular = create_user(session_factory, username="audit_user", email="audit_user@example.com")

    db = session_factory()
    try:
        record_audit(
            db,
            event_type="login",
            user_id=regular.id,
            ip="203.0.113.9",
            user_agent="Mozilla/5.0 audit-agent",
        )
    finally:
        db.close()

    # 普通用户 403
    denied = client.get(
        "/api/v1/admin/audit/audit-logs", headers=build_auth_headers(regular.id)
    )
    assert denied.status_code == 403

    # 超管可查，且无明文 IP/UA
    ok = client.get(
        "/api/v1/admin/audit/audit-logs", headers=build_auth_headers(super_admin.id)
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["event_type"] == "login"
    assert item["user_id"] == regular.id
    assert item["ip_hash"] and "203.0.113.9" not in str(item["ip_hash"])
    assert item["user_agent_hash"] and "Mozilla" not in str(item["user_agent_hash"])


def test_admin_user_list_includes_oauth_user_without_email():
    """回归：OAuth 用户 email 为 NULL 时用户列表仍应 200（曾因 UserAdminResponse.email 必填而整页 500）。"""
    client, session_factory = build_test_client()
    admin = _make_admin_user(
        session_factory, username="list_admin", email="list_admin@example.com", role_code="admin"
    )

    # OAuth 建号路径（app/services/oauth_service.py）不写邮箱
    db = session_factory()
    try:
        oauth_user = User(username="oauth_user", email=None, full_name="oauth_user", is_active=True)
        db.add(oauth_user)
        db.commit()
        db.refresh(oauth_user)
    finally:
        db.close()

    response = client.get(
        "/api/v1/admin/users",
        params={"page": 1, "page_size": 10},
        headers=build_auth_headers(admin.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    matched = [item for item in payload["items"] if item["id"] == oauth_user.id]
    assert len(matched) == 1
    assert matched[0]["username"] == "oauth_user"
    assert matched[0]["email"] is None
