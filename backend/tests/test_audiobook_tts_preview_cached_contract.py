import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import routes_tts
from app.scripts import warmup_tts_voice_previews
from app.services.audiobook import voice_catalog
from app.services.audiobook.tts_preview_cache import build_default_preview_cache_key


class DummyRequest:
    def __init__(self) -> None:
        self.model = "cosyvoice-v3.5-plus"
        self.voice_id = "unit-voice"
        self.text = "试听文本"
        self.volume = 50
        self.speed = 1.0
        self.pitch = 50
        self.voice_type = ""
        self.instruction = ""
        self.voice_clone_data_url = ""
        self.voice_design_prompt = ""
        self.mimo_voice_asset_id = ""
        self.stepaudio_voice_asset_id = ""
        self.word_timestamp_enabled = False
        self.phoneme_timestamp_enabled = False


def test_preview_cached_returns_json_audio_url_when_oss_cache_hits(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "get_voice_entry", lambda *_, **__: {"speaker": "unit-voice"})
    monkeypatch.setattr(routes_tts, "check_oss_preview_exists", lambda cache_key, ext="mp3": "https://cdn.example/preview.mp3")

    async def fail_synthesize(**_kwargs):
        raise AssertionError("runtime_synthesize_speech should not be called on cache hit")

    monkeypatch.setattr(routes_tts, "runtime_synthesize_speech", fail_synthesize)
    monkeypatch.setattr(routes_tts, "get_current_user", lambda: SimpleNamespace(id=1))

    response = asyncio.run(routes_tts.tts_preview_cached(DummyRequest(), current_user=SimpleNamespace(id=1)))

    assert response == {
        "audio_url": "https://cdn.example/preview.mp3",
        "blob": None,
        "cache_hit": True,
        "storage": "oss",
        "response_format": "mp3",
    }


def test_docker_compose_uses_headable_oss_driver_for_shared_preview_cache() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER: aliyun_oss" in compose_text
    assert "AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER: dashscope_oss" not in compose_text


def test_deploy_script_validates_headable_oss_driver_for_shared_preview_cache() -> None:
    deploy_script = (PROJECT_ROOT / "deploy_sync_improved.ps1").read_text(encoding="utf-8")

    assert "printenv AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER" in deploy_script
    assert "Expected 'aliyun_oss'" in deploy_script
    assert "AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET" in deploy_script
    assert "AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT" in deploy_script
    assert "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID" in deploy_script
    assert "AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET" in deploy_script
    assert "Aliyun OSS audio library config missing in backend container" in deploy_script
    assert "TTS preview shared cache requires a HEAD-capable OSS driver" in deploy_script


def test_deploy_config_uploads_frontend_src_json_assets() -> None:
    deploy_config = json.loads((PROJECT_ROOT / "deploy_config.json").read_text(encoding="utf-8"))
    frontend_includes = deploy_config["sync_rules"]["frontend"]["include"]

    assert "frontend/src/**/*.json" in frontend_includes


def test_preview_cached_returns_blob_when_oss_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "get_voice_entry", lambda *_, **__: {"speaker": "unit-voice"})
    monkeypatch.setattr(routes_tts, "check_oss_preview_exists", lambda cache_key, ext="mp3": None)
    monkeypatch.setattr(routes_tts, "upload_preview_to_oss", lambda **kwargs: None)

    async def synthesize(**_kwargs):
        return b"RIFFunit-audio"

    monkeypatch.setattr(routes_tts, "runtime_synthesize_speech", synthesize)

    response = asyncio.run(routes_tts.tts_preview_cached(DummyRequest(), current_user=SimpleNamespace(id=1)))

    assert response["audio_url"] is None
    assert response["cache_hit"] is False
    assert response["storage"] == "blob"
    assert response["response_format"] == "wav"
    assert response["blob"] == base64.b64encode(b"RIFFunit-audio").decode("utf-8")


def test_preview_cached_does_not_touch_preview_cache_for_non_preview_paths(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "_build_preview_cache_key", lambda **_: (_ for _ in ()).throw(AssertionError("preview cache key should not be built here")))

    async def synthesize(**_kwargs):
        return b"RIFFunit-audio"

    monkeypatch.setattr(routes_tts, "runtime_synthesize_speech", synthesize)

    request = routes_tts.TTSPreviewRequest(
        text="正式合成",
        voice_id="unit-voice",
        volume=50,
        speed=1.0,
        pitch=50,
    )

    response = asyncio.run(routes_tts.tts_preview(request, current_user=SimpleNamespace(id=1)))

    assert response.media_type == "audio/wav"


def test_warmup_preview_cache_key_matches_default_preview_request() -> None:
    model_name = "qwen3-tts-instruct-flash"
    voice_id = "Vincent"

    request = routes_tts.TTSPreviewRequest(
        text=routes_tts.DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
        voice_id=voice_id,
        model=model_name,
    )
    text = routes_tts._resolve_preview_text(request, model_name)
    speaker_id = routes_tts._resolve_preview_speaker_id(request, model_name)
    route_voice_params = routes_tts._build_preview_voice_params(request, speaker_id)
    route_cache_key = routes_tts._build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=text,
        volume=int(request.volume),
        speed=float(request.speed or 1.0),
        pitch=int(request.pitch or 50),
        emotion=str(route_voice_params.get("emotion") or "neutral"),
        voice_type=str(request.voice_type or ""),
        mimo_voice_asset_id=str(getattr(request, "mimo_voice_asset_id", "") or ""),
        stepaudio_voice_asset_id=str(getattr(request, "stepaudio_voice_asset_id", "") or ""),
        voice_params=route_voice_params,
    )

    warmup_speaker_id = warmup_tts_voice_previews._resolve_speaker_id(voice_id, model_name)
    warmup_voice_params = warmup_tts_voice_previews._build_voice_params(
        voice_id,
        model_name,
        warmup_speaker_id,
    )
    warmup_cache_key = warmup_tts_voice_previews._build_cache_key(
        model_name,
        warmup_speaker_id,
        warmup_voice_params,
        voice_id,
    )

    assert warmup_voice_params == route_voice_params
    assert warmup_cache_key == route_cache_key


def test_shared_default_preview_cache_identity_matches_route_and_warmup() -> None:
    model_name = "qwen3-tts-instruct-flash"
    voice_id = "Vincent"
    request = routes_tts.TTSPreviewRequest(
        text=routes_tts.DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
        voice_id=voice_id,
        model=model_name,
        volume=50,
    )
    text = routes_tts._resolve_preview_text(request, model_name)
    speaker_id = routes_tts._resolve_preview_speaker_id(request, model_name)
    voice_params = routes_tts._build_preview_voice_params(request, speaker_id)
    route_key = routes_tts._build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=text,
        volume=50,
        speed=1.0,
        pitch=50,
        emotion="neutral",
        voice_type="",
        voice_params=voice_params,
    )

    assert build_default_preview_cache_key(model=model_name, voice_id=voice_id) == route_key


def test_preview_cache_key_is_shared_across_users_for_same_fixed_preview(monkeypatch) -> None:
    model_name = "qwen3-tts-instruct-flash"
    voice_id = "Vincent"
    captured_cache_keys: list[str] = []
    original_build_preview_cache_key = routes_tts._build_preview_cache_key

    def capture_cache_key(**kwargs):
        cache_key = original_build_preview_cache_key(**kwargs)
        captured_cache_keys.append(cache_key)
        return cache_key

    monkeypatch.setattr(routes_tts, "check_oss_preview_exists", lambda cache_key, ext="mp3": "https://cdn.example/preview.mp3")
    monkeypatch.setattr(routes_tts, "_build_preview_cache_key", capture_cache_key)

    request = routes_tts.TTSPreviewRequest(
        text=routes_tts.DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
        voice_id=voice_id,
        model=model_name,
    )

    asyncio.run(routes_tts.tts_preview_cached(request, current_user=SimpleNamespace(id=1)))
    asyncio.run(routes_tts.tts_preview_cached(request, current_user=SimpleNamespace(id=2)))

    assert len(captured_cache_keys) == 2
    assert captured_cache_keys[0] == captured_cache_keys[1]


def test_preview_quote_uses_voice_specific_preview_text(monkeypatch) -> None:
    monkeypatch.setattr(voice_catalog, "_load_preview_quotes", lambda: ["fallback preview text"])
    monkeypatch.setattr(
        voice_catalog,
        "load_voice_catalog_for_model",
        lambda _model: {
            "voices": [
                {
                    "id": "unit-voice",
                    "speaker": "unit-voice",
                    "preview_text": "专用试听文本",
                }
            ]
        },
    )

    assert voice_catalog.get_preview_quote_for_voice("stepaudio-2.5-tts", "unit-voice") == "专用试听文本"


def test_stepaudio_blocked_voice_uses_safe_preview_text() -> None:
    model_name = "stepaudio-2.5-tts"
    voice_id = "shenchennanyin"
    expected_text = "清晨的风轻轻吹过，故事在耳边慢慢展开。"

    request = routes_tts.TTSPreviewRequest(
        text=routes_tts.DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
        voice_id=voice_id,
        model=model_name,
    )

    assert routes_tts._resolve_preview_text(request, model_name) == expected_text
    assert warmup_tts_voice_previews._get_preview_text(model_name, voice_id) == expected_text
