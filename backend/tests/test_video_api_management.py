import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import video_api
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.video_api import VideoApiApplication
from app.services.video_gateway_client import VideoGatewayClient
from router_gateway.api import create_app
from router_gateway.db import Base as GatewayBase, JobRepository


@pytest.fixture
def management(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    gateway_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    User.__table__.create(engine)
    VideoApiApplication.__table__.create(engine)
    GatewayBase.metadata.create_all(gateway_engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    repo = JobRepository(sessionmaker(gateway_engine, expire_on_commit=False))
    gateway_app = create_app(None, resolve_client=repo.get_client_by_api_key,
                             admin_repo=repo, internal_token="test-internal-token")

    class LocalGatewayClient(VideoGatewayClient):
        async def _request(self, method, path, **kwargs):
            async with AsyncClient(transport=ASGITransport(app=gateway_app), base_url="http://gateway") as client:
                response = await client.request(method, path,
                    headers={"X-Gateway-Internal-Token": "test-internal-token"}, **kwargs)
            response.raise_for_status()
            return response.json()

    monkeypatch.setattr(video_api, "VideoGatewayClient", LocalGatewayClient)
    app = FastAPI()
    app.include_router(video_api.router)
    identity = SimpleNamespace(id=1, roles=[])

    def session_dependency():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: identity
    with sessions() as session:
        session.add_all([User(id=1, username="owner"), User(id=2, username="other")])
        session.commit()
    yield SimpleNamespace(client=TestClient(app), identity=identity, sessions=sessions, repo=repo)
    engine.dispose()
    gateway_engine.dispose()


def test_application_is_disabled_until_super_admin_approves(management):
    response = management.client.post("/api/v1/video-api/applications", json={"name": "partner", "plan_code": "enterprise"})
    assert response.status_code == 201
    issued = response.json()
    assert issued["status"] == "pending"
    assert management.repo.get_client_by_api_key(issued["api_key"]).enabled is False
    management.identity.roles = [SimpleNamespace(code="super_admin")]
    approved = management.client.post(f"/api/v1/video-api/admin/applications/{issued['id']}/status", json={"status": "active"})
    assert approved.status_code == 200
    assert management.repo.get_client_by_api_key(issued["api_key"]).enabled is True
    assert response.headers['cache-control'] == 'no-store'


def test_user_ownership_key_redaction_and_revocation(management):
    issued = management.client.post("/api/v1/video-api/applications", json={"name": "partner"}).json()
    listing = management.client.get("/api/v1/video-api/applications")
    assert issued["api_key"] not in listing.text
    assert "api_key_hash" not in listing.text
    with management.sessions() as session:
        row = session.get(VideoApiApplication, issued["id"])
        assert row.api_key_hash != issued["api_key"]
    management.identity.id = 2
    assert management.client.get("/api/v1/video-api/applications").json()["items"] == []
    for action in ("rotate-key", "revoke"):
        assert management.client.post(f"/api/v1/video-api/applications/{issued['id']}/{action}").status_code == 404
    management.identity.id = 1
    assert management.client.post(f"/api/v1/video-api/applications/{issued['id']}/revoke").status_code == 200
    assert management.client.post(f"/api/v1/video-api/applications/{issued['id']}/rotate-key").status_code == 409
    management.identity.roles = [SimpleNamespace(code="super_admin")]
    assert management.client.post(f"/api/v1/video-api/admin/applications/{issued['id']}/status", json={"status": "active"}).status_code == 409


@pytest.mark.parametrize("role", ["user", "admin"])
def test_admin_boundary_for_lists_metrics_and_quota(management, role):
    management.identity.roles = [SimpleNamespace(code=role)]
    for path in ("applications", "metrics"):
        assert management.client.get(f"/api/v1/video-api/admin/{path}").status_code == 403
    assert management.client.patch("/api/v1/video-api/admin/applications/1/quota", json={"max_active_jobs": 100}).status_code == 403


def test_quota_validation_and_gateway_sync(management):
    issued = management.client.post("/api/v1/video-api/applications", json={"name": "partner"}).json()
    management.identity.roles = [SimpleNamespace(code="super_admin")]
    path = f"/api/v1/video-api/admin/applications/{issued['id']}/quota"
    assert management.client.patch(path, json={"max_active_jobs": 0}).status_code == 422
    assert management.client.patch(path, json={"enabled": True}).status_code == 422
    response = management.client.patch(path, json={"max_active_jobs": 50, "max_parallel_attempts": 1})
    assert response.status_code == 200
    assert response.json()["max_active_jobs"] == 50
    remote = management.repo.get_client_by_api_key(issued["api_key"])
    assert remote.max_active_jobs == 50 and remote.max_parallel_attempts == 1


def test_trial_total_quota_is_visible_and_admin_changes_sync_to_gateway(management):
    issued = management.client.post("/api/v1/video-api/applications", json={"name": "trial"}).json()
    assert issued["lifetime_task_limit"] == 100
    management.identity.roles = [SimpleNamespace(code="super_admin")]
    path = f"/api/v1/video-api/admin/applications/{issued['id']}/quota"
    assert management.client.patch(path, json={"lifetime_task_limit": 0}).status_code == 422
    updated = management.client.patch(path, json={"lifetime_task_limit": 500})
    assert updated.status_code == 200
    assert updated.json()["lifetime_task_limit"] == 500
    assert management.repo.get_client_by_api_key(issued["api_key"]).lifetime_task_limit == 500


def test_super_admin_metrics_response_and_window_validation(management):
    management.identity.roles = [SimpleNamespace(code="super_admin")]
    response = management.client.get("/api/v1/video-api/admin/metrics", params={"window_hours": 48})
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["window_hours"] == 48
    assert metrics["active_jobs"] == metrics["pending_jobs"] == 0
    assert metrics["route_event_count"] == metrics["sampled_event_count"] == 0
    assert metrics["total_cost"] is None
    assert metrics["unknown_cost_attempts"] == 0
    assert metrics["providers"] == metrics["routes"] == metrics["clients"] == []
    assert response.headers["cache-control"] == "no-store"
    for window_hours in (0, 169):
        assert management.client.get("/api/v1/video-api/admin/metrics", params={"window_hours": window_hours}).status_code == 422


def test_failed_local_commit_disables_gateway_client(management, monkeypatch):
    with management.sessions() as session:
        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("test failure")))
        with pytest.raises(Exception) as raised:
            asyncio.run(video_api.create_application(
                video_api.VideoApiApplicationCreate(name="partner"), management.identity, session))
        assert raised.value.status_code == 503
    with management.repo._sf() as session:
        from router_gateway.db import Client
        assert all(not client.enabled for client in session.query(Client).all())


def test_failed_approval_commit_cannot_leave_enabled_client(management, monkeypatch):
    issued = management.client.post('/api/v1/video-api/applications', json={'name': 'partner'}).json()
    management.identity.roles = [SimpleNamespace(code='super_admin')]
    with management.sessions() as session:
        monkeypatch.setattr(session, 'commit', lambda: (_ for _ in ()).throw(SQLAlchemyError('test failure')))
        with pytest.raises(Exception) as raised:
            asyncio.run(video_api.admin_update_application_status(issued['id'],
                video_api.VideoApiAdminStatusUpdate(status='active'), management.identity, session))
        assert raised.value.status_code == 503
    assert management.repo.get_client_by_api_key(issued['api_key']).enabled is False
