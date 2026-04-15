import asyncio
import os
import sys
from datetime import datetime
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
from app.api.v1 import user_center
from app.core.security import create_access_token
from app.db.base import Base, get_db
from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Chapter, Project
from app.models.role import Role, user_roles
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
            raise RuntimeError("user or role not found")
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
    file_url: str,
    asset_class: str = "reusable",
    archived_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> UserAssetRecord:
    db = session_factory()
    try:
        asset = UserAssetRecord(
            user_id=user_id,
            source_module="asset_studio",
            asset_kind="image",
            asset_class=asset_class,
            title=title,
            file_url=file_url,
            preview_url=file_url,
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
            operation_desc="update points rules",
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
            operation_desc="update points pricing policy",
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


__all__ = [
    "CompatTestClient",
    "assign_role",
    "build_auth_headers",
    "build_test_client",
    "create_audiobook_project",
    "create_chapter",
    "create_dreamweaver_run",
    "create_points_billing_event",
    "create_points_pricing_policy_snapshot",
    "create_points_rule_snapshot",
    "create_project",
    "create_role",
    "create_user",
    "create_user_asset",
]
