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
from app.services.audiobook.narration_styles import (
    find_narration_style_preset,
    get_narration_style_preset,
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

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)


def build_test_client() -> CompatTestClient:
    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        username="narration_route_user",
        email="narration_route@example.com",
        password_hash="hash",
        is_active=True,
    )
    return CompatTestClient(app)


def test_narration_styles_route_returns_dynamic_catalog_entries():
    response = build_test_client().get("/api/v1/audiobook/narration-styles")

    assert response.status_code == 200
    styles = response.json()
    by_id = {style["id"]: style for style in styles}
    assert set(by_id) >= {"professional", "dramatic", "relaxing", "expressive", "custom"}
    assert by_id["professional"]["name"] == "专业播报"
    assert by_id["custom"]["name"] == "自定义"
    assert "qwen3-tts-instruct-flash" in by_id["professional"]["supported_models"]
    assert "qwen3-tts-instruct-flash" not in by_id["dramatic"]["supported_models"]


def test_narration_style_lookup_separates_strict_find_from_generation_fallback():
    assert find_narration_style_preset("  DRAMATIC  ")["id"] == "dramatic"
    assert find_narration_style_preset("unknown_style") is None
    assert get_narration_style_preset("unknown_style")["id"] == "professional"
