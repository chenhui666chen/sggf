import asyncio
import os
import sys
from datetime import datetime, timezone
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
from app.models.project import Project
from app.models.user import User
from app.models.user_asset_record import UserAssetRecord


def load_user_assets_module():
    user_assets_path = ROOT_DIR / "app" / "api" / "v1" / "user_assets.py"
    spec = spec_from_file_location("test_user_assets_module", user_assets_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载用户资产路由模块")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


user_assets = load_user_assets_module()


class CompatTestClient:
    """兼容 httpx 0.28+ 的轻量测试客户端。"""

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
        tables=[User.__table__, Project.__table__, UserAssetRecord.__table__],
    )

    app = FastAPI()
    app.include_router(user_assets.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[user_assets.get_db] = override_get_db
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


def create_asset(
    session_factory: sessionmaker,
    *,
    user_id: int,
    project_id: int | None = None,
    source_module: str = "asset_studio",
    asset_kind: str = "image",
    asset_class: str = "reusable",
    title: str = "测试资产",
    description: str | None = None,
    file_url: str = "https://example.com/assets/demo.png",
    preview_url: str | None = None,
    model_id: str | None = None,
    generation_mode: str | None = None,
    tags: list[str] | None = None,
    is_favorite: bool = False,
    archived_at: datetime | None = None,
) -> UserAssetRecord:
    db = session_factory()
    try:
        asset = UserAssetRecord(
            user_id=user_id,
            project_id=project_id,
            source_module=source_module,
            asset_kind=asset_kind,
            asset_class=asset_class,
            title=title,
            description=description,
            file_url=file_url,
            preview_url=preview_url or file_url,
            model_id=model_id,
            generation_mode=generation_mode,
            tags=list(tags or []),
            metadata_json={},
            source_payload_json={},
            is_favorite=is_favorite,
            archived_at=archived_at,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    finally:
        db.close()


def build_auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def test_list_user_assets_only_returns_current_users_active_assets():
    client, session_factory = build_test_client()
    current_user = create_user(session_factory, username="asset_owner", email="asset_owner@example.com")
    other_user = create_user(session_factory, username="other_owner", email="other_owner@example.com")

    create_asset(
        session_factory,
        user_id=current_user.id,
        title="当前用户可见资产",
        file_url="https://example.com/assets/visible.png",
    )
    create_asset(
        session_factory,
        user_id=current_user.id,
        title="当前用户已归档资产",
        file_url="https://example.com/assets/archived.png",
        archived_at=datetime.now(timezone.utc),
    )
    create_asset(
        session_factory,
        user_id=other_user.id,
        title="其他用户资产",
        file_url="https://example.com/assets/other.png",
    )

    response = client.get(
        "/api/v1/user-assets",
        headers=build_auth_headers(current_user.id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "当前用户可见资产"
    assert payload[0]["user_id"] == current_user.id


def test_create_user_asset_persists_record_and_uses_file_url_as_preview_by_default():
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="asset_writer", email="asset_writer@example.com")
    project = create_project(
        session_factory,
        user_id=user.id,
        display_no=1,
        title="资产测试项目",
    )

    response = client.post(
        "/api/v1/user-assets",
        headers=build_auth_headers(user.id),
        json={
            "project_id": project.id,
            "source_module": "asset_studio",
            "asset_kind": "image",
            "asset_class": "reusable",
            "title": "封面图",
            "description": "主视觉封面",
            "file_url": "https://example.com/assets/cover.png",
            "model_id": "demo-image-model",
            "generation_mode": "text_to_image",
            "tags": ["封面", "视觉"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "封面图"
    assert payload["project_id"] == project.id
    assert payload["preview_url"] == "https://example.com/assets/cover.png"
    assert payload["tags"] == ["封面", "视觉"]


def test_create_user_asset_rejects_project_not_owned_by_current_user():
    client, session_factory = build_test_client()
    current_user = create_user(session_factory, username="current_user", email="current_user@example.com")
    other_user = create_user(session_factory, username="project_owner", email="project_owner@example.com")
    foreign_project = create_project(
        session_factory,
        user_id=other_user.id,
        display_no=1,
        title="他人项目",
    )

    response = client.post(
        "/api/v1/user-assets",
        headers=build_auth_headers(current_user.id),
        json={
            "project_id": foreign_project.id,
            "source_module": "asset_studio",
            "asset_kind": "image",
            "asset_class": "reusable",
            "title": "不应收录成功",
            "file_url": "https://example.com/assets/blocked.png",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_create_user_asset_upserts_existing_record_by_source_kind_and_file_url():
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="upsert_user", email="upsert_user@example.com")
    project = create_project(
        session_factory,
        user_id=user.id,
        display_no=1,
        title="可复用资产项目",
    )
    existing = create_asset(
        session_factory,
        user_id=user.id,
        project_id=project.id,
        source_module="asset_studio",
        asset_kind="image",
        asset_class="reusable",
        title="旧标题",
        description="旧描述",
        file_url="https://example.com/assets/reuse.png",
        tags=["旧标签"],
        is_favorite=False,
    )

    response = client.post(
        "/api/v1/user-assets",
        headers=build_auth_headers(user.id),
        json={
            "project_id": project.id,
            "source_module": "asset_studio",
            "asset_kind": "image",
            "asset_class": "deliverable",
            "title": "新标题",
            "description": "新描述",
            "file_url": "https://example.com/assets/reuse.png",
            "preview_url": "https://example.com/assets/reuse-preview.png",
            "tags": ["重点", "海报"],
            "is_favorite": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == existing.id
    assert payload["title"] == "新标题"
    assert payload["asset_class"] == "deliverable"
    assert payload["is_favorite"] is True
    assert payload["preview_url"] == "https://example.com/assets/reuse-preview.png"

    db = session_factory()
    try:
        rows = db.query(UserAssetRecord).filter(UserAssetRecord.user_id == user.id).all()
        assert len(rows) == 1
        assert rows[0].title == "新标题"
        assert rows[0].tags == ["重点", "海报"]
    finally:
        db.close()


def test_update_user_asset_supports_favorite_deliverable_and_archive_flags():
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="editor_user", email="editor_user@example.com")
    asset = create_asset(
        session_factory,
        user_id=user.id,
        title="待更新资产",
        file_url="https://example.com/assets/editable.png",
    )

    archive_response = client.patch(
        f"/api/v1/user-assets/{asset.id}",
        headers=build_auth_headers(user.id),
        json={
            "asset_class": "deliverable",
            "is_favorite": True,
            "archived": True,
        },
    )

    assert archive_response.status_code == 200
    archive_payload = archive_response.json()
    assert archive_payload["asset_class"] == "deliverable"
    assert archive_payload["is_favorite"] is True
    assert archive_payload["archived_at"] is not None

    restore_response = client.patch(
        f"/api/v1/user-assets/{asset.id}",
        headers=build_auth_headers(user.id),
        json={
            "archived": False,
            "title": "已恢复资产",
        },
    )

    assert restore_response.status_code == 200
    restore_payload = restore_response.json()
    assert restore_payload["title"] == "已恢复资产"
    assert restore_payload["archived_at"] is None


def test_update_user_asset_rejects_non_owner_access():
    client, session_factory = build_test_client()
    owner = create_user(session_factory, username="asset_owner_user", email="asset_owner_user@example.com")
    intruder = create_user(session_factory, username="intruder_user", email="intruder_user@example.com")
    asset = create_asset(
        session_factory,
        user_id=owner.id,
        title="私有资产",
        file_url="https://example.com/assets/private.png",
    )

    response = client.patch(
        f"/api/v1/user-assets/{asset.id}",
        headers=build_auth_headers(intruder.id),
        json={"is_favorite": True},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User asset not found"


def test_batch_update_user_assets_updates_multiple_records_in_one_request():
    client, session_factory = build_test_client()
    user = create_user(session_factory, username="batch_user", email="batch_user@example.com")
    first_asset = create_asset(
        session_factory,
        user_id=user.id,
        title="批量资产 A",
        file_url="https://example.com/assets/batch-a.png",
        tags=["初始"],
    )
    second_asset = create_asset(
        session_factory,
        user_id=user.id,
        title="批量资产 B",
        file_url="https://example.com/assets/batch-b.png",
        tags=["旧标签"],
    )

    response = client.patch(
        "/api/v1/user-assets/batch",
        headers=build_auth_headers(user.id),
        json={
            "asset_ids": [first_asset.id, second_asset.id],
            "updates": {
                "is_favorite": True,
                "asset_class": "deliverable",
                "tags": ["成品", "精选", "成品"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated_count"] == 2
    assert payload["asset_ids"] == [first_asset.id, second_asset.id]
    assert len(payload["assets"]) == 2
    assert all(item["is_favorite"] is True for item in payload["assets"])
    assert all(item["asset_class"] == "deliverable" for item in payload["assets"])
    assert all(item["tags"] == ["成品", "精选"] for item in payload["assets"])

    db = session_factory()
    try:
        updated_assets = (
            db.query(UserAssetRecord)
            .filter(UserAssetRecord.id.in_([first_asset.id, second_asset.id]))
            .order_by(UserAssetRecord.id.asc())
            .all()
        )
        assert len(updated_assets) == 2
        assert all(asset.is_favorite is True for asset in updated_assets)
        assert all(asset.asset_class == "deliverable" for asset in updated_assets)
        assert all(asset.tags == ["成品", "精选"] for asset in updated_assets)
    finally:
        db.close()


def test_batch_update_user_assets_rejects_non_owned_asset_and_keeps_existing_data():
    client, session_factory = build_test_client()
    owner = create_user(session_factory, username="batch_owner", email="batch_owner@example.com")
    intruder = create_user(session_factory, username="batch_intruder", email="batch_intruder@example.com")
    owned_asset = create_asset(
        session_factory,
        user_id=owner.id,
        title="所有者资产",
        file_url="https://example.com/assets/owner-batch.png",
        is_favorite=False,
    )
    foreign_asset = create_asset(
        session_factory,
        user_id=intruder.id,
        title="他人资产",
        file_url="https://example.com/assets/foreign-batch.png",
        is_favorite=False,
    )

    response = client.patch(
        "/api/v1/user-assets/batch",
        headers=build_auth_headers(owner.id),
        json={
            "asset_ids": [owned_asset.id, foreign_asset.id],
            "updates": {
                "is_favorite": True,
            },
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User asset not found"

    db = session_factory()
    try:
        refreshed_owned_asset = db.query(UserAssetRecord).filter(UserAssetRecord.id == owned_asset.id).first()
        assert refreshed_owned_asset is not None
        assert refreshed_owned_asset.is_favorite is False
    finally:
        db.close()
