import asyncio
import json
import sys
from pathlib import Path

import pytest
import httpx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.audiobook_api import router as audiobook_router
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook.project_audio_runtime import build_character_voice_mapping_item
from app.services.audiobook.stepaudio_voice_assets import (
    StepAudioVoiceAssetError,
    StepAudioVoiceAssetStore,
    resolve_stepaudio_voice_asset_tts_params,
)
from app.services.audiobook.tts_engine import TTSEngine, TTSUserInputError
from app.services.audiobook.tts_model_ids import STEPAUDIO_25_TTS_MODEL


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

    def delete(self, url: str, **kwargs) -> Response:
        return self.request("DELETE", url, **kwargs)


def build_test_client() -> CompatTestClient:
    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        username="stepaudio_voice_asset_user",
        email="stepaudio@example.com",
        password_hash="hash",
        is_active=True,
    )
    app.dependency_overrides[get_db] = lambda: object()
    return CompatTestClient(app)


def test_stepaudio_clone_asset_stores_audio_file_without_json_base64(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = StepAudioVoiceAssetStore(tmp_path)
    sample_bytes = b"RIFFunit-test-wav"

    asset = store.create_clone_asset_from_bytes(
        name="hero reference",
        audio_bytes=sample_bytes,
        mime_type="audio/wav;codec=pcm",
        sample_text="今天天气不错",
        file_id="file-unit-test",
        description="authorized sample",
    )

    index_payload = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    params = resolve_stepaudio_voice_asset_tts_params(asset.id)
    presets = [item.to_voice_preset() for item in store.list_assets(model=STEPAUDIO_25_TTS_MODEL)]

    assert asset.asset_type == "clone"
    assert asset.model == STEPAUDIO_25_TTS_MODEL
    assert asset.mime_type == "audio/wav"
    assert (tmp_path / asset.audio_path).read_bytes() == sample_bytes
    assert sample_bytes.decode("latin1") not in json.dumps(index_payload)
    assert presets[0]["id"] == f"stepaudio_clone:{asset.id}"
    assert presets[0]["customType"] == "clone"
    assert presets[0]["provider"] == "stepaudio"
    assert params["stepaudio_voice_asset_id"] == asset.id
    assert params["stepaudio_voice_file_id"] == "file-unit-test"
    assert params["stepaudio_voice_sample_text"] == "今天天气不错"
    assert params["voice_sample_path"] == str((tmp_path / asset.audio_path).resolve())


def test_stepaudio_assets_are_isolated_by_owner(tmp_path):
    store = StepAudioVoiceAssetStore(tmp_path)
    first = store.create_clone_asset_from_bytes(
        name="owner one",
        audio_bytes=b"RIFFowner-one",
        mime_type="audio/wav",
        owner_user_id=7,
    )
    second = store.create_clone_asset_from_bytes(
        name="owner two",
        audio_bytes=b"RIFFowner-two",
        mime_type="audio/wav",
        owner_user_id=8,
    )

    assert [asset.id for asset in store.list_assets(owner_user_id=7)] == [first.id]
    assert [asset.id for asset in store.list_assets(owner_user_id=8)] == [second.id]
    with pytest.raises(StepAudioVoiceAssetError, match="does not belong"):
        store.resolve_tts_params(second.id, owner_user_id=7)


def test_stepaudio_clone_asset_without_file_id_is_marked_unavailable_for_synthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = StepAudioVoiceAssetStore(tmp_path)

    asset = store.create_clone_asset_from_bytes(
        name="local reference only",
        audio_bytes=b"RIFFlocal-only",
        mime_type="audio/wav",
    )

    preset = asset.to_voice_preset()

    assert preset["id"] == f"stepaudio_clone:{asset.id}"
    assert preset["disabled"] is True
    assert "file_id" in preset["disabledReason"]


def test_stepaudio_clone_asset_with_file_id_is_available_for_synthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = StepAudioVoiceAssetStore(tmp_path)

    asset = store.create_clone_asset_from_bytes(
        name="preview-ready reference",
        audio_bytes=b"RIFFpreview-ready",
        mime_type="audio/wav",
        file_id="file-ready",
    )

    preset = asset.to_voice_preset()

    assert preset["id"] == f"stepaudio_clone:{asset.id}"
    assert "pitch" not in preset["default_params"]
    assert "disabled" not in preset
    assert "disabledReason" not in preset


def test_stepaudio_clone_asset_rejects_unsupported_audio_format(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = StepAudioVoiceAssetStore(tmp_path)

    with pytest.raises(StepAudioVoiceAssetError, match="StepAudio Voice Clone"):
        store.create_clone_asset_from_bytes(
            name="unsupported reference",
            audio_bytes=b"webm",
            mime_type="audio/webm;codecs=opus",
        )


def test_stepaudio_clone_asset_upload_route_saves_file_and_lists_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    monkeypatch.setenv("STEP_API_KEY", "unit-step-key")

    class FailingStepFunAsyncClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("manual StepAudio file_id must not call StepFun file upload")

    monkeypatch.setattr(httpx, "AsyncClient", FailingStepFunAsyncClient)
    sample_bytes = b"ID3uploaded-mp3"
    client = build_test_client()

    upload_response = client.post(
        "/api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload",
        data={
            "name": "uploaded route reference",
            "sample_text": "智能阶跃，十倍每一个人的可能",
            "file_id": "file-uploaded",
        },
        files={"file": ("sample.mp3", sample_bytes, "audio/mpeg")},
    )
    list_response = client.get(
        f"/api/v1/audiobook/tts/voices?model={STEPAUDIO_25_TTS_MODEL}",
    )

    assert upload_response.status_code == 200
    asset = upload_response.json()["asset"]
    assert asset["name"] == "uploaded route reference"
    assert asset["mime_type"] == "audio/mpeg"
    assert asset["file_id"] == "file-uploaded"
    assert (tmp_path / asset["audio_path"]).read_bytes() == sample_bytes

    assert list_response.status_code == 200
    voices = list_response.json()["voices"]
    assert any(voice["id"] == f"stepaudio_clone:{asset['id']}" for voice in voices)


def test_stepaudio_clone_asset_upload_route_auto_uploads_file_id_with_step_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    monkeypatch.setenv("STEP_API_KEY", "unit-step-key")
    monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
    monkeypatch.setenv("STEPAUDIO_TTS_BASE_URL", "https://unit.stepfun.test/v1/")
    upload_calls = []

    class FakeStepFunAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers=None, data=None, files=None):
            upload_calls.append(
                {
                    "url": url,
                    "headers": dict(headers or {}),
                    "data": dict(data or {}),
                    "files": files,
                    "timeout": self.kwargs.get("timeout"),
                }
            )
            return httpx.Response(
                200,
                json={"id": "file-auto"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeStepFunAsyncClient)
    sample_bytes = b"RIFFuploaded-wav"

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload",
        data={
            "name": "auto uploaded reference",
            "sample_text": "智能阶跃，十倍每一个人的可能",
        },
        files={"file": ("voice.wav", sample_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    assert len(upload_calls) == 1
    call = upload_calls[0]
    assert call["url"] == "https://unit.stepfun.test/v1/files"
    assert call["headers"]["Authorization"] == "Bearer unit-step-key"
    assert call["data"]["purpose"] == "storage"
    assert call["files"]["file"] == ("voice.wav", sample_bytes, "audio/wav")
    payload = response.json()
    assert payload["asset"]["file_id"] == "file-auto"
    assert "disabled" not in payload["voice"]


def test_stepaudio_clone_asset_preview_route_returns_audio_without_saving_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    monkeypatch.setenv("STEP_API_KEY", "unit-step-key")
    monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
    monkeypatch.setenv("STEPAUDIO_TTS_BASE_URL", "https://unit.stepfun.test/v1/")
    sample_bytes = b"RIFFuploaded-wav"
    preview_calls = []

    async def fake_upload_stepaudio_voice_reference_file(**kwargs):
        return "file-preview"

    async def fake_stepaudio_voice_preview(self, **kwargs):
        preview_calls.append(kwargs)
        return b"preview-audio"

    monkeypatch.setattr(
        "app.api.v1.audiobook_api.routes_tts.upload_stepaudio_voice_reference_file",
        fake_upload_stepaudio_voice_reference_file,
    )
    monkeypatch.setattr(
        TTSEngine,
        "_call_stepaudio_voice_preview_http",
        fake_stepaudio_voice_preview,
    )

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/stepaudio/clone-assets/preview",
        data={
            "name": "preview only reference",
            "sample_text": "智能阶跃，十倍每一个人的可能",
            "preview_text": "这是一段试听。",
        },
        files={"file": ("voice.wav", sample_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["file_id"] == "file-preview"
    assert payload["sample_text"] == "智能阶跃，十倍每一个人的可能"
    assert payload["audio_mime_type"] == "audio/mpeg"
    assert payload["audio_data_base64"] == "cHJldmlldy1hdWRpbw=="
    index_path = tmp_path / "index.json"
    if index_path.exists():
        assert json.loads(index_path.read_text(encoding="utf-8"))["assets"] == []
    assert preview_calls == [
        {
            "model": STEPAUDIO_25_TTS_MODEL,
            "api_key": "unit-step-key",
            "text": "这是一段试听。",
            "file_id": "file-preview",
            "sample_text": "智能阶跃，十倍每一个人的可能",
            "instruction": "语气自然，语速中等，保持参考音色特征",
        }
    ]


def test_stepaudio_clone_asset_preview_route_requires_sample_text(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/stepaudio/clone-assets/preview",
        data={"name": "missing transcript"},
        files={"file": ("voice.wav", b"RIFFuploaded-wav", "audio/wav")},
    )

    assert response.status_code == 400
    assert "sample_text" in response.text


def test_stepaudio_clone_asset_upload_route_rejects_unsupported_format(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload",
        data={"name": "uploaded route reference"},
        files={"file": ("sample.m4a", b"m4a-bytes", "audio/x-m4a")},
    )

    assert response.status_code == 400
    assert "StepAudio Voice Clone" in response.text


def test_stepaudio_preview_route_returns_user_error_for_cer_mismatch(monkeypatch):
    async def fake_synthesize_speech(**kwargs):
        raise TTSUserInputError(
            "StepAudio Voice Clone reference audio and sample_text do not match. Provider detail: CER_NOT_PASS",
            code="stepaudio_clone_sample_text_mismatch",
        )

    def fake_merge_stepaudio_voice_asset_tts_params(voice_params, **_kwargs):
        return {
            **voice_params,
            "stepaudio_voice_file_id": "file-unit",
            "stepaudio_voice_sample_text": "wrong sample words",
        }

    monkeypatch.setattr(
        "app.api.v1.audiobook_api.routes_tts.runtime_synthesize_speech",
        fake_synthesize_speech,
    )
    monkeypatch.setattr(
        "app.api.v1.audiobook_api.routes_tts.merge_stepaudio_voice_asset_tts_params",
        fake_merge_stepaudio_voice_asset_tts_params,
    )

    response = build_test_client().post(
        "/api/v1/audiobook/tts/preview",
        json={
            "text": "preview line",
            "voice_id": "stepaudio_clone:stepaudio_clone_unit",
            "model": STEPAUDIO_25_TTS_MODEL,
            "stepaudio_voice_asset_id": "stepaudio_clone_unit",
            "volume": 50,
            "speed": 1.0,
            "pitch": 50,
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "stepaudio_clone_sample_text_mismatch"
    assert detail["retryable"] is False
    assert "sample_text" in detail["message"]
    assert "CER_NOT_PASS" in detail["message"]


def test_stepaudio_clone_asset_delete_route_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.stepaudio_voice_assets.DEFAULT_STEPAUDIO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = StepAudioVoiceAssetStore(tmp_path)
    asset = store.create_clone_asset_from_bytes(
        name="delete me",
        audio_bytes=b"RIFFdelete-wav",
        mime_type="audio/wav",
        owner_user_id=1,
    )

    response = build_test_client().delete(f"/api/v1/audiobook/tts/voices/stepaudio/assets/{asset.id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "asset_id": asset.id}
    assert not (tmp_path / asset.audio_path).exists()


def test_stepaudio_voice_asset_id_is_preserved_in_project_voice_mapping():
    mapping_item = build_character_voice_mapping_item(
        {
            "voice_id": "stepaudio_clone:stepaudio_clone_saved",
            "stepaudio_voice_asset_id": "stepaudio_clone_saved",
            "tts_model": STEPAUDIO_25_TTS_MODEL,
        },
        tts_model=STEPAUDIO_25_TTS_MODEL,
    )

    assert mapping_item["voice_id"] == "stepaudio_clone:stepaudio_clone_saved"
    assert mapping_item["stepaudio_voice_asset_id"] == "stepaudio_clone_saved"
