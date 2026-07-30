import base64
import asyncio
import json
import sys
from pathlib import Path

import pytest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.audiobook_api import router as audiobook_router
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook.mimo_voice_assets import (
    MiMoVoiceAssetError,
    MiMoVoiceAssetStore,
    resolve_mimo_voice_asset_tts_params,
)
from app.services.audiobook.project_audio_runtime import build_character_voice_mapping_item
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
)
from app.services.audiobook.voice_manager_mimo import MiMoVoiceManager


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

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def build_test_client() -> CompatTestClient:
    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        username="mimo_voice_asset_user",
        email="mimo@example.com",
        password_hash="hash",
        is_active=True,
    )
    app.dependency_overrides[get_db] = lambda: object()
    return CompatTestClient(app)


def test_mimo_design_asset_is_saved_as_reusable_voice_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)

    asset = store.create_design_asset(
        name="calm narrator",
        voice_design_prompt=(
            "female young adult, medium-low pitch, calm and restrained, "
            "clear diction, suitable for audiobook narration"
        ),
        description="main narrator",
    )

    presets = [item.to_voice_preset() for item in store.list_assets(model=MIMO_V25_TTS_VOICE_DESIGN_MODEL)]
    params = resolve_mimo_voice_asset_tts_params(asset.id)

    assert asset.asset_type == "design"
    assert asset.model == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert presets == [
        {
            "id": f"mimo_design:{asset.id}",
            "speaker": f"mimo_design:{asset.id}",
            "label": "calm narrator",
            "category": "custom",
            "customType": "design",
            "description": "main narrator",
            "style": "voice_design",
            "default_params": {"volume": 50, "speed": 1.0, "pitch": 50},
        }
    ]
    assert params["voice_design_prompt"] == asset.voice_design_prompt
    assert params["voice_description"] == asset.voice_design_prompt


def test_mimo_clone_asset_stores_audio_file_and_resolves_data_url(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    sample_bytes = b"RIFFunit-test-wav"
    sample_data_url = "data:audio/wav;base64," + base64.b64encode(sample_bytes).decode("ascii")

    asset = store.create_clone_asset(
        name="hero clone",
        audio_data_url=sample_data_url,
        description="authorized sample",
    )

    index_payload = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    params = resolve_mimo_voice_asset_tts_params(asset.id)
    presets = [item.to_voice_preset() for item in store.list_assets(model=MIMO_V25_TTS_VOICE_CLONE_MODEL)]

    assert asset.asset_type == "clone"
    assert asset.model == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert (tmp_path / asset.audio_path).read_bytes() == sample_bytes
    assert sample_data_url not in json.dumps(index_payload)
    assert presets[0]["id"] == f"mimo_clone:{asset.id}"
    assert presets[0]["customType"] == "clone"
    assert params["voice_clone_data_url"] == sample_data_url


def test_mimo_clone_asset_can_be_saved_from_uploaded_audio_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    sample_bytes = b"ID3unit-test-mp3"

    asset = store.create_clone_asset_from_bytes(
        name="uploaded clone",
        audio_bytes=sample_bytes,
        mime_type="audio/mpeg",
    )

    params = resolve_mimo_voice_asset_tts_params(asset.id)

    assert asset.asset_type == "clone"
    assert asset.model == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert asset.mime_type == "audio/mpeg"
    assert (tmp_path / asset.audio_path).read_bytes() == sample_bytes
    assert params["voice_clone_data_url"] == "data:audio/mpeg;base64," + base64.b64encode(sample_bytes).decode("ascii")


def test_mimo_clone_asset_strips_parameters_from_supported_uploaded_mime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    sample_bytes = b"RIFFunit-test-wav"

    asset = store.create_clone_asset_from_bytes(
        name="recorded wav",
        audio_bytes=sample_bytes,
        mime_type="audio/wav;codec=pcm",
    )
    params = resolve_mimo_voice_asset_tts_params(asset.id)

    assert asset.mime_type == "audio/wav"
    assert params["voice_clone_data_url"] == "data:audio/wav;base64," + base64.b64encode(sample_bytes).decode("ascii")
    assert ";codec=pcm" not in params["voice_clone_data_url"]


def test_mimo_clone_asset_rejects_uploaded_unsupported_audio_formats(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)

    for mime_type in ("audio/webm;codecs=opus", "audio/x-m4a", "audio/mp4"):
        with pytest.raises(MiMoVoiceAssetError, match="MiMo Voice Clone 仅支持 mp3 或 wav"):
            store.create_clone_asset_from_bytes(
                name="unsupported clone",
                audio_bytes=b"unsupported",
                mime_type=mime_type,
            )


def test_mimo_clone_asset_rejects_data_url_with_unsupported_audio_format(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    sample_data_url = "data:audio/webm;codecs=opus;base64," + base64.b64encode(b"webm-opus").decode("ascii")

    with pytest.raises(MiMoVoiceAssetError, match="MiMo Voice Clone 仅支持 mp3 或 wav"):
        store.create_clone_asset(
            name="data url webm",
            audio_data_url=sample_data_url,
        )


def test_mimo_clone_asset_rejects_existing_unsupported_mime_when_resolving(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    sample_bytes = b"legacy-webm-opus"
    sample_path = tmp_path / "clone_samples" / "legacy.webm"
    sample_path.parent.mkdir(parents=True)
    sample_path.write_bytes(sample_bytes)
    (tmp_path / "index.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "mimo_clone_legacy",
                        "name": "legacy recorded webm",
                        "asset_type": "clone",
                        "model": MIMO_V25_TTS_VOICE_CLONE_MODEL,
                        "mime_type": "audio/webm;codecs=opus",
                        "audio_path": "clone_samples/legacy.webm",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MiMoVoiceAssetError, match="MiMo Voice Clone 仅支持 mp3 或 wav"):
        resolve_mimo_voice_asset_tts_params("mimo_clone_legacy")


def test_mimo_clone_asset_upload_route_saves_file_without_json_base64(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    sample_bytes = b"RIFFuploaded-wav"

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/mimo/clone-assets/upload",
        data={"name": "uploaded route clone"},
        files={"file": ("sample.wav", sample_bytes, "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    asset = payload["asset"]
    assert asset["name"] == "uploaded route clone"
    assert asset["mime_type"] == "audio/wav"
    assert (tmp_path / asset["audio_path"]).read_bytes() == sample_bytes


def test_mimo_clone_asset_upload_route_rejects_unsupported_format(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )

    response = build_test_client().post(
        "/api/v1/audiobook/tts/voices/mimo/clone-assets/upload",
        data={"name": "uploaded route clone"},
        files={"file": ("sample.m4a", b"m4a-bytes", "audio/x-m4a")},
    )

    assert response.status_code == 400
    assert "MiMo Voice Clone 仅支持 mp3 或 wav" in response.text


def test_mimo_voice_asset_id_is_preserved_and_expanded_by_voice_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    asset = store.create_design_asset(
        name="asset prompt",
        voice_design_prompt="young female, medium pitch, calm audiobook voice",
    )
    mapping_item = build_character_voice_mapping_item(
        {
            "voice_id": f"mimo_design:{asset.id}",
            "mimo_voice_asset_id": asset.id,
            "tts_model": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        },
        tts_model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    )
    manager = MiMoVoiceManager(MIMO_V25_TTS_VOICE_DESIGN_MODEL)

    manager.apply_project_voice_mapping({"Narrator": mapping_item})
    params = manager.get_voice("Narrator").get_tts_params("calm")

    assert mapping_item["mimo_voice_asset_id"] == asset.id
    assert params["mimo_voice_asset_id"] == asset.id
    assert params["voice_design_prompt"] == "young female, medium pitch, calm audiobook voice"


def test_base_voice_manager_resolves_mimo_design_cross_model_voice(tmp_path, monkeypatch):
    """混合模型项目：主 manager 为基类 VoiceManager 时，per-character 的 mimo 自定义
    音色不应被当作未知组合跳过，而应解析出 asset 信息随 profile 带到下游。"""
    monkeypatch.setattr(
        "app.services.audiobook.mimo_voice_assets.DEFAULT_MIMO_VOICE_ASSET_DIR",
        tmp_path,
    )
    store = MiMoVoiceAssetStore(tmp_path)
    asset = store.create_design_asset(
        name="cross model asset",
        voice_design_prompt="middle-aged male, low pitch, wise elder audiobook voice",
    )

    from app.services.audiobook.voice_manager import VoiceManager

    manager = VoiceManager()
    manager.apply_project_voice_mapping(
        {
            "纪老药": {
                "voice_id": f"mimo_design:{asset.id}",
                "tts_model": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
                "volume": 50,
            }
        }
    )

    profile = manager.get_voice("纪老药")
    assert profile is not None, "mimo 自定义音色角色不应被跳过"
    params = profile.get_tts_params("calm")
    assert params["mimo_voice_asset_id"] == asset.id
    assert params["voice_design_prompt"] == "middle-aged male, low pitch, wise elder audiobook voice"


def test_mimo_assets_are_isolated_by_owner(tmp_path):
    store = MiMoVoiceAssetStore(tmp_path)
    first = store.create_design_asset(
        name="owner one",
        voice_design_prompt="calm adult narrator",
        owner_user_id=7,
    )
    second = store.create_design_asset(
        name="owner two",
        voice_design_prompt="bright young narrator",
        owner_user_id=8,
    )

    assert [asset.id for asset in store.list_assets(owner_user_id=7)] == [first.id]
    assert [asset.id for asset in store.list_assets(owner_user_id=8)] == [second.id]
    with pytest.raises(MiMoVoiceAssetError, match="does not belong"):
        store.resolve_tts_params(second.id, owner_user_id=7)
