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

from app.db.base import Base, get_db
from app.core.security import get_current_user
from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject, ChapterAudio
from app.models.audiobook_task import AudiobookTask
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Chapter, Project
from app.models.role import Role, user_roles
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord
from app.api.v1.audiobook_api import routes_projects as audiobook_routes_projects


def load_audiobook_module():
    audiobook_path = ROOT_DIR / "app" / "api" / "v1" / "audiobook.py"
    spec = spec_from_file_location("test_audiobook_module", audiobook_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载有声书路由模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_audiobook_module", module)
    spec.loader.exec_module(module)
    return module


audiobook = load_audiobook_module()


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from user_center_test_helpers import (
    create_chapter,
    create_points_pricing_policy_snapshot,
    create_points_rule_snapshot,
    create_project,
    create_user,
    create_user_asset,
)


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

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def build_test_client() -> tuple[CompatTestClient, sessionmaker, FastAPI]:
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
            ChapterAudio.__table__,
            AudiobookTask.__table__,
            DreamweaverProject.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(audiobook.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app), testing_session_local, app


def _seed_points_snapshots(
    session_factory,
    *,
    operator_user_id: int,
    operator_username: str,
    now: datetime,
    reusable_asset_reward: float,
    running_audiobook_frozen: float = 2.0,
    user_price_rate: float = 1.0,
    freeze_buffer_rate: float = 0.1,
    negative_margin_block_enabled: bool = True,
) -> None:
    create_points_rule_snapshot(
        session_factory,
        operator_user_id=operator_user_id,
        operator_username=operator_username,
        payload={
            "reusable_asset_reward": reusable_asset_reward,
            "deliverable_asset_reward": 10.0,
            "audiobook_completion_reward": 8.0,
            "dreamweaver_completion_reward": 5.0,
            "running_audiobook_frozen": running_audiobook_frozen,
            "running_dreamweaver_frozen": 2.0,
            "reward_ttl_days": 30,
            "expiring_notice_days": 7,
        },
        created_at=now - timedelta(minutes=6),
    )
    create_points_pricing_policy_snapshot(
        session_factory,
        operator_user_id=operator_user_id,
        operator_username=operator_username,
        payload={
            "points_per_yuan": 100,
            "user_price_basis": "public_list_price",
            "user_price_rate": user_price_rate,
            "provider_discount_capture_rate": 1.0,
            "freeze_buffer_rate": freeze_buffer_rate,
            "margin_warning_rate": 0.15,
            "negative_margin_block_enabled": negative_margin_block_enabled,
        },
        created_at=now - timedelta(minutes=5),
    )


def _count_audiobook_projects(session_factory) -> int:
    db = session_factory()
    try:
        return int(db.query(AudiobookProject).count())
    finally:
        db.close()


def _count_audiobook_tasks(session_factory) -> int:
    db = session_factory()
    try:
        return int(db.query(AudiobookTask).count())
    finally:
        db.close()


def test_audiobook_create_project_blocks_with_structured_precheck_error(monkeypatch):
    client, session_factory, app = build_test_client()
    now = datetime.now(timezone.utc)

    user = create_user(session_factory, username="ab_route_low_user", email="ab_route_low@example.com")
    operator = create_user(session_factory, username="ab_route_low_admin", email="ab_route_low_admin@example.com")
    app.dependency_overrides[get_current_user] = lambda: user

    project = create_project(session_factory, user_id=user.id, display_no=1, title="有声书路由余额不足项目")
    chapter = create_chapter(
        session_factory,
        project_id=project.id,
        chapter_number=1,
        title="第一章",
        content="癸" * 10000,
    )
    create_user_asset(
        session_factory,
        user_id=user.id,
        title="有声书路由低余额资产",
        source_uri="https://example.com/ab-route-low.png",
        created_at=now,
        updated_at=now,
    )
    _seed_points_snapshots(
        session_factory,
        operator_user_id=operator.id,
        operator_username=operator.username,
        now=now,
        reusable_asset_reward=20.0,
    )

    def _should_not_create_project(self, request, *, prepared=None):
        raise AssertionError("预检失败后不应继续创建有声书项目")

    monkeypatch.setattr(
        audiobook_routes_projects.AudiobookAppService,
        "create_audiobook_project",
        _should_not_create_project,
    )

    response = client.post(
        "/api/v1/audiobook/projects",
        json={
            "project_id": project.id,
            "chapter_ids": [chapter.id],
            "tts_provider": "aliyun",
            "generation_mode": "full",
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["module_key"] == "audiobook"
    assert detail["module_label"] == "有声书"
    assert detail["failure_code"] == "insufficient_available_points"
    assert detail["allowed"] is False
    assert detail["available_points"] == 20.0
    assert detail["effective_available_points"] == 20.0
    assert detail["additional_frozen_points"] > detail["available_points"]
    assert "当前可用 20.00 积分" in detail["message"]
    assert _count_audiobook_projects(session_factory) == 0
    assert _count_audiobook_tasks(session_factory) == 0
