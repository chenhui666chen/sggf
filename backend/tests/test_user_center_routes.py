import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import app.core.security as security
from app.core.security import create_access_token
from app.db.base import Base, get_db
from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Chapter, Project
from app.models.role import Role, user_roles
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord
from app.services.user_center_points_events import (
    record_dreamweaver_billing_release,
    record_dreamweaver_billing_settle,
)


def load_user_center_module():
    user_center_path = ROOT_DIR / "app" / "api" / "v1" / "user_center.py"
    spec = spec_from_file_location("test_user_center_module", user_center_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载用户中心路由模块")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


user_center = load_user_center_module()


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
            user_roles,
            AdminOperationLog.__table__,
            Project.__table__,
            Chapter.__table__,
            UserAssetRecord.__table__,
            AudiobookProject.__table__,
            DreamweaverProject.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(user_center.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[user_center.get_db] = override_get_db
    app.dependency_overrides[security.get_db] = override_get_db
    return CompatTestClient(app), testing_session_local


def create_user(
    session_factory: sessionmaker,
    *,
    username: str,
    email: str,
    is_active: bool = True,
) -> User:
    db = session_factory()
    try:
        user = User(
            username=username,
            email=email,
            full_name=username,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def create_role(
    session_factory: sessionmaker,
    *,
    name: str,
    code: str,
) -> Role:
    db = session_factory()
    try:
        role = Role(
            name=name,
            code=code,
            description=f"{name} role",
            is_active=True,
            is_system=False,
        )
        db.add(role)
        db.commit()
        db.refresh(role)
        return role
    finally:
        db.close()


def assign_role(
    session_factory: sessionmaker,
    *,
    user_id: int,
    role_id: int,
) -> None:
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


def create_project(
    session_factory: sessionmaker,
    *,
    user_id: int,
    display_no: int,
    title: str,
) -> Project:
    db = session_factory()
    try:
        project = Project(
            user_id=user_id,
            display_no=display_no,
            title=title,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project
    finally:
        db.close()


def create_chapter(
    session_factory: sessionmaker,
    *,
    project_id: int,
    chapter_number: int,
    title: str,
    content: str = "",
    word_count: int | None = None,
) -> Chapter:
    db = session_factory()
    try:
        chapter = Chapter(
            project_id=project_id,
            chapter_number=chapter_number,
            title=title,
            content=content,
            word_count=word_count if word_count is not None else len(content),
        )
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter
    finally:
        db.close()


def create_user_asset(
    session_factory: sessionmaker,
    *,
    user_id: int,
    title: str,
    source_uri: str,
    asset_class: str = "reusable",
    archived_at: datetime | None = None,
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
            asset_class=asset_class,
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
            archived_at=archived_at,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    finally:
        db.close()


def create_audiobook_project(
    session_factory: sessionmaker,
    *,
    project_id: int,
    status: str = "completed",
    total_chapters: int = 0,
    completed_chapters: int = 0,
    total_cost: float = 0.0,
    tts_provider: str = "aliyun",
    deleted_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> AudiobookProject:
    db = session_factory()
    try:
        audiobook_project = AudiobookProject(
            project_id=project_id,
            status=status,
            tts_provider=tts_provider,
            total_chapters=total_chapters,
            completed_chapters=completed_chapters,
            total_cost=total_cost,
            deleted_at=deleted_at,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(audiobook_project)
        db.commit()
        db.refresh(audiobook_project)
        return audiobook_project
    finally:
        db.close()


def create_dreamweaver_run(
    session_factory: sessionmaker,
    *,
    user_id: int,
    project_id: int,
    run_id: str,
    status: str = "completed",
    stage: str | None = None,
    contract_json: dict[str, object] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> DreamweaverProject:
    db = session_factory()
    try:
        run = DreamweaverProject(
            run_id=run_id,
            source_project_id=project_id,
            user_id=user_id,
            status=status,
            stage=stage,
            contract_json=contract_json,
            created_at=created_at,
            updated_at=updated_at,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    finally:
        db.close()


def create_points_rule_snapshot(
    session_factory: sessionmaker,
    *,
    operator_user_id: int,
    operator_username: str,
    payload: dict[str, object],
    created_at: datetime | None = None,
) -> AdminOperationLog:
    db = session_factory()
    try:
        log = AdminOperationLog(
            user_id=operator_user_id,
            username=operator_username,
            operation_type="POINTS_RULES_UPDATE",
            resource_type="SYSTEM_POINTS_RULES",
            resource_id=0,
            operation_desc="更新积分规则配置",
            request_method="PUT",
            request_path="/api/v1/admin/system/points-rules",
            request_params=payload,
            response_status=200,
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


def create_points_pricing_policy_snapshot(
    session_factory: sessionmaker,
    *,
    operator_user_id: int,
    operator_username: str,
    payload: dict[str, object],
    created_at: datetime | None = None,
) -> AdminOperationLog:
    db = session_factory()
    try:
        log = AdminOperationLog(
            user_id=operator_user_id,
            username=operator_username,
            operation_type="POINTS_PRICING_POLICY_UPDATE",
            resource_type="SYSTEM_POINTS_PRICING_POLICY",
            resource_id=0,
            operation_desc="更新积分定价策略",
            request_method="PUT",
            request_path="/api/v1/admin/system/points-pricing-policy",
            request_params=payload,
            response_status=200,
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
    amount_yuan: float | None = None,
    title: str,
    summary: str,
    project_id: int | None = None,
    audiobook_project_id: int | None = None,
    run_id: str | None = None,
    action_path: str | None = None,
    action_label: str | None = None,
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
                "amount_points": amount_points,
                "amount_yuan": amount_yuan,
                "title": title,
                "summary": summary,
                "action_path": action_path,
                "action_label": action_label,
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


def build_auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def test_points_overview_returns_rule_based_account_and_admin_benefits():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    owner = create_user(session_factory, username="owner", email="owner@example.com")
    other_user = create_user(session_factory, username="other", email="other@example.com")
    admin_role = create_role(session_factory, name="管理员", code="admin")
    assign_role(session_factory, user_id=owner.id, role_id=admin_role.id)

    project_a = create_project(session_factory, user_id=owner.id, display_no=1, title="项目 A")
    project_b = create_project(session_factory, user_id=owner.id, display_no=2, title="项目 B")
    other_project = create_project(session_factory, user_id=other_user.id, display_no=1, title="其他项目")

    create_user_asset(
        session_factory,
        user_id=owner.id,
        title="资产 A",
        source_uri="https://example.com/assets/a.png",
        created_at=now - timedelta(days=25),
        updated_at=now - timedelta(days=25),
    )
    create_user_asset(
        session_factory,
        user_id=owner.id,
        title="资产 B",
        source_uri="https://example.com/assets/b.png",
        archived_at=now,
        created_at=now,
        updated_at=now,
    )
    create_user_asset(
        session_factory,
        user_id=other_user.id,
        title="其他资产",
        source_uri="https://example.com/assets/other.png",
    )

    audiobook_paid = create_audiobook_project(
        session_factory,
        project_id=project_a.id,
        total_chapters=10,
        completed_chapters=8,
        total_cost=19.8,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    create_audiobook_project(
        session_factory,
        project_id=project_b.id,
        total_chapters=5,
        completed_chapters=0,
        total_cost=0,
        created_at=now,
        updated_at=now,
    )
    create_audiobook_project(
        session_factory,
        project_id=project_a.id,
        total_chapters=3,
        completed_chapters=3,
        total_cost=88.5,
        deleted_at=now,
    )
    create_audiobook_project(
        session_factory,
        project_id=other_project.id,
        total_chapters=12,
        completed_chapters=12,
        total_cost=36.6,
    )

    create_dreamweaver_run(
        session_factory,
        user_id=owner.id,
        project_id=project_a.id,
        run_id="dw-owner-1",
        status="completed",
        created_at=now,
        updated_at=now,
    )
    create_dreamweaver_run(
        session_factory,
        user_id=other_user.id,
        project_id=other_project.id,
        run_id="dw-other-1",
        status="completed",
    )

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(owner.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"] == {
        "balance": 16.0,
        "frozen": 0.0,
        "expiring_soon": 3.0,
        "status": "partial",
        "connected_source_count": 3,
        "pending_source_count": 3,
    }
    assert payload["points_rules"]["source"] == "default"
    assert payload["points_rules"]["reward_ttl_days"] == 30
    assert payload["points_rules"]["expiring_notice_days"] == 7
    assert payload["points_rules"]["updated_at"] is None

    assert payload["connected_overview"] == {
        "project_count": 2,
        "user_asset_count": 2,
        "audiobook_project_count": 2,
        "audiobook_total_cost": 19.8,
        "dreamweaver_run_count": 1,
    }

    connected_keys = {item["key"] for item in payload["benefits"]["connected_items"]}
    assert "identity" in connected_keys
    assert "admin-console" in connected_keys
    assert "points-account" in connected_keys

    planned_keys = {item["key"] for item in payload["benefits"]["planned_items"]}
    assert planned_keys == {"model-quota", "membership-tier", "payment-orders"}

    connected_entries = payload["ledger"]["connected_entries"]
    assert len(connected_entries) == 1
    assert connected_entries[0]["key"] == f"audiobook-ledger-{audiobook_paid.id}"
    assert connected_entries[0]["module_label"] == "有声书"
    assert connected_entries[0]["event_label"] == "TTS 成本"
    assert connected_entries[0]["title"] == "项目 A"
    assert connected_entries[0]["amount"] == 19.8
    assert connected_entries[0]["action_path"] == f"/audiobook/{project_a.id}"

    pending_signals = {item["key"]: item for item in payload["ledger"]["pending_signals"]}
    assert pending_signals["dreamweaver-ledger"]["signal_label"] == "1 条 run 记录"
    assert pending_signals["dreamweaver-ledger"]["action_path"] == "/drama"
    assert pending_signals["asset-ledger"]["signal_label"] == "2 项资产"
    assert pending_signals["points-ledger"]["signal_label"] == "充值 / 补发规则待接入"

    assert len(payload["points_entries"]) == 3
    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert points_entries["audiobook-reward-1"]["source_label"] == "有声书完成"
    assert points_entries["audiobook-reward-1"]["direction"] == "income"
    assert points_entries["audiobook-reward-1"]["status"] == "active"
    assert points_entries["dreamweaver-reward-dw-owner-1"]["source_label"] == "短剧运行"
    assert points_entries["dreamweaver-reward-dw-owner-1"]["title"] == "项目 A"


def test_points_overview_returns_planned_status_when_no_connected_source():
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="plain_user", email="plain_user@example.com")

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"] == {
        "balance": None,
        "frozen": None,
        "expiring_soon": None,
        "status": "planned",
        "connected_source_count": 0,
        "pending_source_count": 3,
    }
    assert payload["connected_overview"] == {
        "project_count": 0,
        "user_asset_count": 0,
        "audiobook_project_count": 0,
        "audiobook_total_cost": 0.0,
        "dreamweaver_run_count": 0,
    }

    connected_keys = {item["key"] for item in payload["benefits"]["connected_items"]}
    assert "admin-console" not in connected_keys
    assert "points-account" not in connected_keys
    assert "identity" in connected_keys

    planned_keys = {item["key"] for item in payload["benefits"]["planned_items"]}
    assert planned_keys == {"points-ledger", "model-quota", "membership-tier", "payment-orders"}
    assert payload["points_entries"] == []
    assert payload["ledger"]["connected_entries"] == []
    assert len(payload["ledger"]["pending_signals"]) == 3


def test_points_overview_uses_latest_admin_rule_snapshot_and_points_entries():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="rules_user", email="rules_user@example.com")
    operator = create_user(session_factory, username="rules_admin", email="rules_admin@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="规则验证项目")

    create_user_asset(
        session_factory,
        user_id=user.id,
        title="长期资产",
        source_uri="https://example.com/assets/rules.png",
        created_at=now - timedelta(days=55),
        updated_at=now - timedelta(days=55),
    )
    create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-rules-1",
        status="completed",
        stage="delivery",
        created_at=now,
        updated_at=now,
    )
    create_points_rule_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "reusable_asset_reward": 4.5,
            "dreamweaver_completion_reward": 12,
            "reward_ttl_days": 60,
            "expiring_notice_days": 10,
        },
        created_at=now - timedelta(minutes=5),
    )

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == 16.5
    assert payload["points_account"]["frozen"] == 0.0
    assert payload["points_account"]["expiring_soon"] == 4.5
    assert payload["points_account"]["connected_source_count"] == 2

    assert payload["points_rules"]["source"] == "admin_log"
    assert payload["points_rules"]["reusable_asset_reward"] == 4.5
    assert payload["points_rules"]["dreamweaver_completion_reward"] == 12.0
    assert payload["points_rules"]["reward_ttl_days"] == 60
    assert payload["points_rules"]["expiring_notice_days"] == 10
    assert payload["points_rules"]["updated_by_user_id"] == operator.id
    assert payload["points_rules"]["updated_by_username"] == operator.username
    assert payload["points_rules"]["updated_at"] is not None

    assert len(payload["points_entries"]) == 2
    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert points_entries["dreamweaver-reward-dw-rules-1"]["title"] == "规则验证项目"
    assert points_entries["dreamweaver-reward-dw-rules-1"]["direction"] == "income"
    assert points_entries["dreamweaver-reward-dw-rules-1"]["status"] == "active"
    assert points_entries["user-asset-1"]["amount"] == 4.5
    assert points_entries["user-asset-1"]["status"] == "active"
    assert points_entries["user-asset-1"]["expires_at"] is not None


def test_points_overview_exposes_frozen_points_for_running_tasks():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="runner", email="runner@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="运行中项目")

    create_user_asset(
        session_factory,
        user_id=user.id,
        title="运行中资产",
        source_uri="https://example.com/assets/running.png",
        created_at=now,
        updated_at=now,
    )
    create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="running",
        total_chapters=8,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-running-1",
        status="running",
        stage="storyboard",
        created_at=now,
        updated_at=now,
    )

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == 3.0
    assert payload["points_account"]["frozen"] == 4.0
    assert payload["points_account"]["expiring_soon"] == 0.0
    assert payload["points_account"]["connected_source_count"] == 3
    assert payload["ledger"]["connected_entries"] == []

    assert len(payload["points_entries"]) == 3
    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert points_entries["user-asset-1"]["status"] == "active"
    assert points_entries["audiobook-frozen-1"]["direction"] == "hold"
    assert points_entries["audiobook-frozen-1"]["status"] == "frozen"
    assert points_entries["dreamweaver-frozen-dw-running-1"]["direction"] == "hold"
    assert points_entries["dreamweaver-frozen-dw-running-1"]["status"] == "frozen"


def test_points_overview_includes_pricing_policy_and_task_billing_read_model():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="billing_user", email="billing@example.com")
    operator = create_user(session_factory, username="billing_admin", email="billing_admin@example.com")

    settled_project = create_project(session_factory, user_id=user.id, display_no=1, title="已结算有声书")
    running_project = create_project(session_factory, user_id=user.id, display_no=2, title="运行中有声书")
    drama_project = create_project(session_factory, user_id=user.id, display_no=3, title="运行中短剧")

    create_chapter(
        session_factory,
        project_id=running_project.id,
        chapter_number=1,
        title="第一章",
        content="甲" * 12000,
    )
    create_chapter(
        session_factory,
        project_id=running_project.id,
        chapter_number=2,
        title="第二章",
        content="乙" * 8000,
    )

    create_audiobook_project(
        session_factory,
        project_id=settled_project.id,
        status="completed",
        total_chapters=10,
        completed_chapters=10,
        total_cost=19.8,
        created_at=now - timedelta(days=1),
        updated_at=now - timedelta(days=1),
    )
    create_audiobook_project(
        session_factory,
        project_id=running_project.id,
        status="running",
        total_chapters=2,
        completed_chapters=0,
        total_cost=0.0,
        tts_provider="aliyun",
        created_at=now,
        updated_at=now,
    )
    create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=drama_project.id,
        run_id="dw-billing-1",
        status="running",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [
                {
                    "shots": [
                        {"shot_key": "shot-1"},
                        {"shot_key": "shot-2"},
                        {"shot_key": "shot-3"},
                    ]
                }
            ],
        },
        created_at=now,
        updated_at=now,
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        payload={
            "points_per_yuan": 120,
            "user_price_basis": "public_list_price",
            "user_price_rate": 1.0,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": 0.1,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": True,
        },
        created_at=now - timedelta(minutes=3),
    )

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["pricing_policy"]["points_per_yuan"] == 120
    assert payload["pricing_policy"]["user_price_basis"] == "public_list_price"
    assert payload["pricing_policy"]["user_price_rate"] == 1.0
    assert payload["pricing_policy"]["freeze_buffer_rate"] == 0.1
    assert payload["pricing_policy"]["source"] == "admin_log"
    assert payload["pricing_policy"]["updated_by_username"] == operator.username

    task_billing = payload["task_billing"]
    assert task_billing["actual_spend_yuan"] == 19.8
    assert task_billing["actual_spend_points"] == 2376.0
    assert task_billing["estimated_running_spend_yuan"] == 4.14
    assert task_billing["estimated_running_spend_points"] == 496.8
    assert task_billing["suggested_frozen_points"] == 546.48
    assert task_billing["actual_task_count"] == 1
    assert task_billing["estimated_task_count"] == 2
    assert task_billing["pending_task_count"] == 0

    task_items = {item["key"]: item for item in task_billing["items"]}
    assert task_items["audiobook-billing-1"]["pricing_status"] == "actual"
    assert task_items["audiobook-billing-1"]["actual_points"] == 2376.0
    assert task_items["audiobook-billing-2"]["pricing_status"] == "estimated"
    assert task_items["audiobook-billing-2"]["estimated_yuan"] == 2.0
    assert task_items["audiobook-billing-2"]["estimated_points"] == 240.0
    assert task_items["audiobook-billing-2"]["suggested_frozen_points"] == 264.0
    assert task_items["dreamweaver-billing-dw-billing-1"]["pricing_status"] == "estimated"
    assert task_items["dreamweaver-billing-dw-billing-1"]["estimated_yuan"] == 2.14
    assert task_items["dreamweaver-billing-dw-billing-1"]["estimated_points"] == 256.8
    assert task_items["dreamweaver-billing-dw-billing-1"]["suggested_frozen_points"] == 282.48
    assert task_items["dreamweaver-billing-dw-billing-1"]["action_path"] == f"/drama/{drama_project.id}"


def test_points_overview_prefers_formal_billing_events_for_freeze_and_settlement():
    client, session_factory = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="formal_user", email="formal@example.com")
    project = create_project(session_factory, user_id=user.id, display_no=1, title="正式结算项目")

    create_user_asset(
        session_factory,
        user_id=user.id,
        title="正式资产",
        source_uri="https://example.com/assets/formal.png",
        created_at=now,
        updated_at=now,
    )
    audiobook_project = create_audiobook_project(
        session_factory,
        project_id=project.id,
        status="running",
        total_chapters=2,
        completed_chapters=0,
        total_cost=0.0,
        created_at=now,
        updated_at=now,
    )
    dreamweaver_run = create_dreamweaver_run(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        run_id="dw-formal-1",
        status="running",
        stage="storyboard",
        contract_json={
            "runtime_config": {"quality_mode": "quality"},
            "episodes": [{"shots": [{"shot_key": "shot-1"}, {"shot_key": "shot-2"}]}],
        },
        created_at=now,
        updated_at=now,
    )

    audiobook_freeze_log = create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"audiobook:{audiobook_project.id}",
        module_key="audiobook",
        event_kind="freeze",
        amount_points=4.8,
        amount_yuan=0.04,
        title="正式结算项目",
        summary="有声书任务已生成正式冻结积分",
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
        action_path=f"/audiobook/{project.id}",
        action_label="查看有声书项目",
        created_at=now + timedelta(minutes=1),
    )
    audiobook_settle_log = create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"audiobook:{audiobook_project.id}",
        module_key="audiobook",
        event_kind="settle",
        amount_points=3.6,
        amount_yuan=0.03,
        title="正式结算项目",
        summary="有声书任务已按实际成本完成积分结算",
        project_id=project.id,
        audiobook_project_id=audiobook_project.id,
        action_path=f"/audiobook/{project.id}",
        action_label="查看有声书项目",
        created_at=now + timedelta(minutes=2),
    )
    dreamweaver_freeze_log = create_points_billing_event(
        session_factory,
        operator_user_id=user.id,
        operator_username=user.username,
        target_user_id=user.id,
        billing_key=f"dreamweaver:{dreamweaver_run.run_id}",
        module_key="dreamweaver",
        event_kind="freeze",
        amount_points=1.8,
        amount_yuan=0.02,
        title="正式结算项目",
        summary="短剧任务已生成正式冻结积分",
        project_id=project.id,
        run_id=dreamweaver_run.run_id,
        action_path=f"/drama/{project.id}",
        action_label="查看短剧模块",
        created_at=now + timedelta(minutes=3),
    )

    response = client.get(
        "/api/v1/user-center/points-overview",
        headers=build_auth_headers(user.id),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["points_account"]["status"] == "partial"
    assert payload["points_account"]["balance"] == -0.6
    assert payload["points_account"]["frozen"] == 1.8
    assert payload["points_account"]["connected_source_count"] == 3

    points_entries = {item["key"]: item for item in payload["points_entries"]}
    assert "audiobook-frozen-1" not in points_entries
    assert "dreamweaver-frozen-dw-formal-1" not in points_entries

    audiobook_freeze_key = f"points-billing-freeze-{audiobook_freeze_log.id}"
    audiobook_settle_key = f"points-billing-settle-{audiobook_settle_log.id}"
    dreamweaver_freeze_key = f"points-billing-freeze-{dreamweaver_freeze_log.id}"

    assert points_entries[audiobook_freeze_key]["direction"] == "hold"
    assert points_entries[audiobook_freeze_key]["status"] == "frozen"
    assert points_entries[audiobook_settle_key]["direction"] == "expense"
    assert points_entries[audiobook_settle_key]["status"] == "active"
    assert points_entries[dreamweaver_freeze_key]["amount"] == 1.8
    assert points_entries[dreamweaver_freeze_key]["source_label"] == "短剧运行"
