import asyncio
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1 import model_catalog


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

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


class StubSyncService:
    def __init__(self):
        self.calls: list[dict] = []

    def sync_catalog(
        self,
        db,
        *,
        force_refresh: bool = True,
        model_keys: list[str] | None = None,
        max_verification_age_hours: float | None = None,
    ) -> dict:
        self.calls.append(
            {
                "db": db,
                "force_refresh": force_refresh,
                "model_keys": model_keys,
                "max_verification_age_hours": max_verification_age_hours,
            }
        )
        return {
            "processed": 0,
            "verified": 0,
            "partial": 0,
            "failed": 0,
            "skipped": 1,
            "skipped_recent": 1,
            "cache_hits": 2,
            "network_requests": 1,
            "cached_response_count": 1,
        }


def build_test_client() -> tuple[CompatTestClient, object]:
    app = FastAPI()
    app.include_router(model_catalog.router)

    dummy_db = object()
    app.dependency_overrides[model_catalog.get_current_user] = lambda: object()
    app.dependency_overrides[model_catalog.get_db] = lambda: dummy_db
    return CompatTestClient(app), dummy_db


def test_sync_model_catalog_route_passes_ttl_to_service(monkeypatch):
    stub_service = StubSyncService()
    monkeypatch.setattr(model_catalog, "get_model_catalog_sync_service", lambda: stub_service)

    client, dummy_db = build_test_client()
    response = client.post(
        "/api/v1/model-catalog/sync",
        json={
            "force_refresh": False,
            "model_keys": ["qwen3-max"],
            "max_verification_age_hours": 24,
        },
    )

    assert response.status_code == 200
    assert response.json()["skipped_recent"] == 1
    assert stub_service.calls == [
        {
            "db": dummy_db,
            "force_refresh": False,
            "model_keys": ["qwen3-max"],
            "max_verification_age_hours": 24,
        }
    ]
