from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from app.api.v1.audiobook_api import router as audiobook_router
from app.api.v1.audiobook_api import routes_segment_direction
from app.schemas.audiobook import SegmentDirectionAssistRequest


def test_segment_direction_routes_are_registered():
    paths = {route.path for route in audiobook_router.routes}

    assert (
        "/api/v1/audiobook/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/"
        "segments/{segment_index:int}/direction-assist"
    ) in paths
    assert (
        "/api/v1/audiobook/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/"
        "segments/{segment_index:int}/direction-audio/analyze"
    ) in paths
    assert (
        "/api/v1/audiobook/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/"
        "segments/{segment_index:int}/direction-audio/transcribe"
    ) not in paths


def test_direction_audio_analyze_requires_non_empty_segment_text(monkeypatch):
    monkeypatch.setattr(
        routes_segment_direction,
        "_load_stored_segment",
        lambda **_kwargs: {"text": "   "},
    )

    upload = UploadFile(filename="reading.webm", file=__import__("io").BytesIO(b"fake"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            routes_segment_direction.analyze_segment_direction_recording(
                audiobook_project_id=1,
                chapter_id=2,
                segment_index=0,
                file=upload,
                tts_model=None,
                owned=object(),
            )
        )
    assert error.value.status_code == 400
    assert "台词为空" in str(error.value.detail)


def test_direction_audio_analyze_forwards_expected_text_and_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        routes_segment_direction,
        "_load_stored_segment",
        lambda **_kwargs: {"text": "他痛得几乎说不出话来。"},
    )

    class _OmniProvider:
        name = "qwen_omni"

    monkeypatch.setattr(
        routes_segment_direction,
        "create_prompt_audio_asr_provider",
        lambda alias: captured.setdefault("alias", alias) or _OmniProvider(),
    )

    async def fake_analyze(**kwargs):
        captured.update(kwargs)
        return {"source": "omni_reading"}

    monkeypatch.setattr(
        routes_segment_direction,
        "analyze_segment_direction_reading",
        fake_analyze,
    )

    upload = UploadFile(filename="reading.webm", file=__import__("io").BytesIO(b"fake"))
    payload = asyncio.run(
        routes_segment_direction.analyze_segment_direction_recording(
            audiobook_project_id=1,
            chapter_id=2,
            segment_index=0,
            file=upload,
            tts_model="seed-tts-2.0-expressive",
            owned=object(),
        )
    )

    assert payload == {"source": "omni_reading"}
    assert captured["alias"] == "qwen_omni"
    assert captured["expected_text"] == "他痛得几乎说不出话来。"
    assert captured["tts_model"] == "seed-tts-2.0-expressive"
    assert captured["segment"] == {"text": "他痛得几乎说不出话来。"}


def test_segment_direction_request_has_a_closed_bounded_contract():
    request = SegmentDirectionAssistRequest(
        cue_type="voice",
        description="慢速、低沉，重读痛字",
        segment={"text": "痛。"},
        tts_model="seed-tts-2.0-expressive",
    )

    assert request.cue_type == "voice"
    assert request.description == "慢速、低沉，重读痛字"

    with pytest.raises(ValidationError):
        SegmentDirectionAssistRequest(
            cue_type="mix",
            description="不支持的类型",
            segment={},
        )

    with pytest.raises(ValidationError):
        SegmentDirectionAssistRequest(
            cue_type="voice",
            description="x" * 1001,
            segment={},
        )

    with pytest.raises(ValidationError):
        SegmentDirectionAssistRequest(
            cue_type="voice",
            description="有效描述",
            segment={},
            provider_prompt_snapshot={"mode": "injected"},
        )


def test_direction_assist_sanitizes_server_owned_and_compiled_segment_fields(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        routes_segment_direction,
        "_load_stored_segment",
        lambda **_kwargs: {
            "text": "stored text",
            "audio_path": "backend/audiobooks/private.mp3",
            "voice_params": {
                "speaker": "stored-speaker",
                "delivery_plan": {"provider": "stale"},
            },
        },
    )
    monkeypatch.setattr(routes_segment_direction, "get_llm_client", lambda **_kwargs: None)

    async def fake_assist_segment_direction(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(
        routes_segment_direction,
        "assist_segment_direction",
        fake_assist_segment_direction,
    )

    payload = asyncio.run(
        routes_segment_direction.create_segment_direction_assist(
            audiobook_project_id=1,
            chapter_id=2,
            segment_index=0,
            request=SegmentDirectionAssistRequest(
                cue_type="voice",
                description="slow and restrained",
                segment={
                    "text": "client text",
                    "audio_path": "C:/outside/injected.mp3",
                    "voice_params": {
                        "speaker": "client-speaker",
                        "provider_prompt_snapshot": {"mode": "injected"},
                    },
                },
            ),
            owned=object(),
        )
    )

    assert payload == {"success": True}
    assert captured["segment"] == {
        "text": "client text",
        "voice_params": {"speaker": "client-speaker"},
    }
