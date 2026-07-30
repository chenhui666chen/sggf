from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.main import app, application


SETTINGS_AUTO_MERGE_PATH = "/api/v1/projects/{project_id}/auto-merge-settings"
VOICE_POOL_PUBLIC_PATH = "/api/v1/audiobook/voice-pool/public"


def test_full_application_openapi_schema_is_generated():
    app.openapi_schema = None

    schema = app.openapi()

    assert SETTINGS_AUTO_MERGE_PATH in schema["paths"]
    assert VOICE_POOL_PUBLIC_PATH in schema["paths"]
    assert "AutoMergeRequest" in schema["components"]["schemas"]


async def _get_openapi_json():
    transport = ASGITransport(app=application)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get("/openapi.json")


def test_deployed_application_exposes_openapi_json():
    app.openapi_schema = None

    response = asyncio.run(_get_openapi_json())

    assert response.status_code == 200
    schema = response.json()
    assert SETTINGS_AUTO_MERGE_PATH in schema["paths"]
    assert VOICE_POOL_PUBLIC_PATH in schema["paths"]
