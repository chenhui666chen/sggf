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


def test_voice_pool_public_tag_filters_are_query_params():
    """多标签筛选必须落在 query 上。

    FastAPI 会把没有 Annotated 标记的 list 形参识别成请求体；GET 请求体被静默忽略，
    筛选参数就成了永远不生效的假开关，只有 spec 层能提前抓到。
    """
    app.openapi_schema = None
    operation = app.openapi()["paths"][VOICE_POOL_PUBLIC_PATH]["get"]

    assert "requestBody" not in operation

    parameters = {item["name"]: item for item in operation["parameters"]}
    for name in ("timbre_tags", "scenario_tags", "emotion_tags"):
        assert parameters[name]["in"] == "query"
        assert parameters[name]["required"] is False
