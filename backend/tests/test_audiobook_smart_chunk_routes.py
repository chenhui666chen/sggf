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
        username="smart_chunk_route_user",
        email="smart_chunk_route@example.com",
        password_hash="hash",
        is_active=True,
    )
    return CompatTestClient(app)


def test_smart_chunk_preview_returns_chunk_stats_and_chunk_metadata():
    response = build_test_client().post(
        "/api/v1/audiobook/smart-chunk/preview?max_tokens=8&min_tokens=1",
        json=[
            {
                "type": "narration",
                "speaker": "narrator",
                "text": "第一句很短。",
            },
            {
                "type": "dialogue",
                "speaker": "Alice",
                "text": "第二句也很短。",
            },
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["original_segments"] == 2
    assert payload["chunked_segments"] >= 1
    assert payload["total_tokens"] > 0
    assert len(payload["chunks"]) == payload["chunked_segments"]
    assert payload["stats"]["total_chunks"] == payload["chunked_segments"]
    assert payload["stats"]["total_tokens"] == payload["total_tokens"]
    assert payload["stats"]["max_tokens_in_chunk"] >= payload["stats"]["min_tokens_in_chunk"]
    assert all("estimated_tokens" in chunk for chunk in payload["chunks"])


def test_smart_chunk_estimate_reports_token_count_and_limit():
    response = build_test_client().post(
        "/api/v1/audiobook/smart-chunk/estimate",
        json={"text": "她推开门，低声说：你终于来了。"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text_length"] == len("她推开门，低声说：你终于来了。")
    assert payload["estimated_tokens"] > 0
    assert payload["needs_chunking"] is False
    assert payload["max_tokens"] == 1800


def test_voice_types_route_returns_catalog_entries():
    response = build_test_client().get("/api/v1/audiobook/voice-types")

    assert response.status_code == 200
    voice_types = response.json()
    by_type = {item["voice_type"]: item for item in voice_types}
    assert "gentle" in by_type
    assert by_type["gentle"]["name"] == "温柔"
    assert "compatible_personalities" in by_type["gentle"]
    assert "suitable_scenarios" in by_type["gentle"]


def test_voice_type_detail_route_returns_full_profile_and_404_for_unknown_type():
    client = build_test_client()

    response = client.get("/api/v1/audiobook/voice-types/gentle")
    missing_response = client.get("/api/v1/audiobook/voice-types/unknown_type")

    assert response.status_code == 200
    payload = response.json()
    assert payload["voice_type"] == "gentle"
    assert payload["name"] == "温柔"
    assert payload["speed_modifier"] == 0.9
    assert payload["preferred_gender"] == "female"
    assert payload["default_emotion"] == "calm"
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "声音类型不存在"


def test_voice_type_recommendation_prefers_matching_personality_gender_and_age():
    response = build_test_client().post(
        "/api/v1/audiobook/voice-types/recommend",
        json={
            "personality": "emotional",
            "gender": "female",
            "age_range": "adult",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character_name"] is None
    assert payload["recommended_types"][0] == "gentle"
    assert len(payload["recommended_types"]) <= 3
