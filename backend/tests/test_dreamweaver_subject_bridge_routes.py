from __future__ import annotations

import asyncio
import os
import sys
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
from app.models.admin_log import AdminOperationLog
from app.models.dreamweaver import DreamweaverAsset, DreamweaverProject
from app.models.project import Project
from app.models.role import Role, user_roles
from app.models.user import User


def load_dreamweaver_module():
    dreamweaver_path = ROOT_DIR / "app" / "api" / "v1" / "dreamweaver_api" / "_imports.py"
    spec = spec_from_file_location("test_dreamweaver_subject_bridge_module", dreamweaver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 DreamWeaver imports 模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_dreamweaver_subject_bridge_module", module)
    spec.loader.exec_module(module)
    return module


dreamweaver = load_dreamweaver_module()


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
            DreamweaverProject.__table__,
            DreamweaverAsset.__table__,
        ],
    )

    app = FastAPI()
    app.include_router(dreamweaver.router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[dreamweaver.get_db] = override_get_db
    return CompatTestClient(app), testing_session_local, app


def _seed_library_asset(session_factory: sessionmaker) -> tuple[User, Project, DreamweaverProject, DreamweaverAsset]:
    db = session_factory()
    try:
        user = User(username="dw_subject_user", email="dw_subject_user@example.com", full_name="dw_subject_user", is_active=True)
        db.add(user)
        db.flush()

        project = Project(user_id=int(user.id), display_no=1, title="主体桥接测试项目")
        db.add(project)
        db.flush()

        dw_project = DreamweaverProject(
            run_id="drama_1_123456",
            source_project_id=int(project.id),
            user_id=int(user.id),
            status="completed",
            state="DONE",
            stage="done",
            progress=100,
        )
        db.add(dw_project)
        db.flush()

        asset = DreamweaverAsset(
            dreamweaver_project_id=int(dw_project.id),
            asset_type="image",
            role="lib_character_portrait:7",
            uri="runs/library/project_1/characters/7.png",
            meta_json={"approved": True},
        )
        db.add(asset)
        db.commit()
        db.refresh(user)
        db.refresh(project)
        db.refresh(dw_project)
        db.refresh(asset)
        return user, project, dw_project, asset
    finally:
        db.close()


def test_update_library_asset_provider_ref_persists_subject_id() -> None:
    client, session_factory, app = build_test_client()
    user, _project, _dw_project, asset = _seed_library_asset(session_factory)
    app.dependency_overrides[dreamweaver.get_current_user] = lambda: user

    response = client.post(
        f"/api/v1/dreamweaver/library/assets/{asset.id}/provider-ref",
        json={"provider": "kling", "subject_id": "el_manual_001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "kling"
    assert data["subject_id"] == "el_manual_001"
    assert data["provider_refs"]["kling"]["element_id"] == "el_manual_001"

    db = session_factory()
    try:
        refreshed = db.query(DreamweaverAsset).filter(DreamweaverAsset.id == asset.id).first()
        assert refreshed is not None
        meta = dict(refreshed.meta_json or {})
        provider_refs = dict(meta.get("provider_refs") or {})
        assert provider_refs["kling"]["element_id"] == "el_manual_001"
        assert provider_refs["kling"]["source"] == "manual_bind"
    finally:
        db.close()


def test_sync_library_asset_provider_ref_writes_synced_subject_id(monkeypatch, tmp_path) -> None:
    from app.services.dreamweaver.video_generation import subject_bridge as subject_bridge_module

    client, session_factory, app = build_test_client()
    user, _project, _dw_project, asset = _seed_library_asset(session_factory)
    app.dependency_overrides[dreamweaver.get_current_user] = lambda: user

    runs_dir = ROOT_DIR / "runs" / "test_subject_bridge"
    runs_dir.mkdir(parents=True, exist_ok=True)
    frontal = runs_dir / "7.png"
    frontal.write_bytes(b"\x89PNG\r\n\x1a\nsync")

    db = session_factory()
    try:
        asset_row = db.query(DreamweaverAsset).filter(DreamweaverAsset.id == asset.id).first()
        assert asset_row is not None
        asset_row.uri = "runs/test_subject_bridge/7.png"
        asset_row.meta_json = {
            "approved": True,
            "entity_type": "character",
            "entity_id": 7,
            "entity_name": "阿青",
            "descriptor": "黑发少年，面部清秀。",
        }
        db.add(asset_row)
        db.commit()
    finally:
        db.close()

    class _FakeElement:
        def __init__(self) -> None:
            self.element_id = "el_sync_001"
            self.element_name = "阿青"
            self.element_description = "黑发少年，面部清秀。"
            self.reference_type = "image_refer"

    def _fake_create_and_wait(self, request, **kwargs):
        assert request.name == "阿青"
        assert request.frontal_image.endswith("runs\\test_subject_bridge\\7.png") or request.frontal_image.endswith("runs/test_subject_bridge/7.png")
        return [_FakeElement()]

    monkeypatch.setattr(subject_bridge_module.KlingElementAPI, "create_and_wait", _fake_create_and_wait)

    response = client.post(
        f"/api/v1/dreamweaver/library/assets/{asset.id}/provider-ref/sync",
        json={"provider": "kling", "include_related_views": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "kling"
    assert data["subject_id"] == "el_sync_001"
    assert data["provider_refs"]["kling"]["element_id"] == "el_sync_001"
    assert data["provider_refs"]["kling"]["source"] == "provider_sync"

    db = session_factory()
    try:
        refreshed = db.query(DreamweaverAsset).filter(DreamweaverAsset.id == asset.id).first()
        assert refreshed is not None
        meta = dict(refreshed.meta_json or {})
        provider_refs = dict(meta.get("provider_refs") or {})
        assert provider_refs["kling"]["element_id"] == "el_sync_001"
        assert provider_refs["kling"]["source"] == "provider_sync"
    finally:
        db.close()
