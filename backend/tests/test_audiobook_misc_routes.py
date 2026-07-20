from __future__ import annotations

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

from app.api.v1.audiobook_api import router as audiobook_router
from app.core.security import get_current_user
from app.models.user import User


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


def build_test_client() -> CompatTestClient:
    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        username="misc_route_user",
        email="misc_route@example.com",
        password_hash="hash",
        is_active=True,
    )
    return CompatTestClient(app)


def build_route_path_set() -> set[str]:
    app = FastAPI()
    app.include_router(audiobook_router)
    return {str(getattr(route, "path", "")) for route in app.routes}


def test_legacy_preview_generate_route_is_removed():
    response = build_test_client().post(
        "/api/v1/audiobook/previews/generate",
        json={
            "text": "试听文本",
            "voice_id": "voice-1",
            "tts_model": "qwen3-tts-instruct-flash",
        },
    )

    assert response.status_code == 404


def test_legacy_preview_file_route_is_removed():
    response = build_test_client().get("/api/v1/audiobook/previews/missing_preview")

    assert response.status_code == 404


def test_retry_config_route_is_not_exposed():
    response = build_test_client().post(
        "/api/v1/audiobook/retries/config",
        json={
            "max_retries": 5,
            "initial_delay": 1.5,
            "backoff_factor": 1.75,
            "enable_degraded": False,
        },
    )

    assert response.status_code == 404


def test_legacy_preview_routes_are_not_registered_but_sse_is_not_deprecated():
    app = FastAPI()
    app.include_router(audiobook_router)
    schema = app.openapi()

    assert "/api/v1/audiobook/previews/generate" not in schema["paths"]
    assert "/api/v1/audiobook/previews/{preview_id}" not in schema["paths"]
    assert (
        schema["paths"]["/api/v1/audiobook/tasks/{task_id}/stream"]["get"].get("deprecated")
        is not True
    )


def test_unused_detail_routes_are_not_registered():
    paths = build_route_path_set()

    assert "/api/v1/audiobook/narration-styles/{style_id}" not in paths
    assert "/api/v1/audiobook/voice-types/{voice_type}" not in paths


def test_legacy_cosyvoice_v3_plus_alias_routes_are_not_registered():
    paths = build_route_path_set()

    assert not any("/cosyvoice-v3-plus/" in path for path in paths)


def test_source_project_character_scope_route_is_registered():
    paths = build_route_path_set()

    assert "/api/v1/audiobook/source-projects/{project_id:int}/character-scope" in paths
