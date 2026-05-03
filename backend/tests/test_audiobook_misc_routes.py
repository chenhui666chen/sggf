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
from app.api.v1.audiobook_api import routes_misc
from app.core.security import get_current_user
from app.models.user import User
from app.services.audiobook.smart_retrier import RetryConfig


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


def test_preview_file_route_reads_generated_audio_file(monkeypatch, tmp_path):
    preview_id = "abc_123"
    preview_file = tmp_path / f"preview_{preview_id}.mp3"
    preview_file.write_bytes(b"ID3preview-audio")
    monkeypatch.setattr(routes_misc.default_preview_generator, "output_dir", str(tmp_path))

    response = build_test_client().get(f"/api/v1/audiobook/previews/{preview_id}")

    assert response.status_code == 200
    assert response.content == b"ID3preview-audio"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["content-disposition"] == "inline"


def test_preview_file_route_rejects_invalid_preview_id(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_misc.default_preview_generator, "output_dir", str(tmp_path))

    response = build_test_client().get("/api/v1/audiobook/previews/bad.id")

    assert response.status_code == 400
    assert response.json()["detail"] == "无效的预览ID"


def test_preview_file_route_returns_404_for_missing_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_misc.default_preview_generator, "output_dir", str(tmp_path))

    response = build_test_client().get("/api/v1/audiobook/previews/missing_preview")

    assert response.status_code == 404
    assert response.json()["detail"] == "预览音频不存在"


def test_retry_config_route_updates_default_retrier_config():
    old_config = routes_misc.default_retrier.config
    try:
        response = build_test_client().post(
            "/api/v1/audiobook/retries/config",
            json={
                "max_retries": 5,
                "initial_delay": 1.5,
                "backoff_factor": 1.75,
                "enable_degraded": False,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["message"] == "默认重试配置已更新"
        assert payload["config"] == {
            "max_retries": 5,
            "initial_delay": 1.5,
            "backoff_factor": 1.75,
            "enable_degraded": False,
        }
        assert routes_misc.default_retrier.config.max_retries == 5
        assert routes_misc.default_retrier.config.initial_delay == 1.5
        assert routes_misc.default_retrier.config.backoff_factor == 1.75
        assert routes_misc.default_retrier.config.enable_degraded is False
    finally:
        routes_misc.default_retrier.config = old_config or RetryConfig()
