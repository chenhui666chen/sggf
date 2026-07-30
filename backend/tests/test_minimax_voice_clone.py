import asyncio
import importlib
import importlib.util
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


MODULE_NAME = "app.services.audiobook.minimax_voice_clone_client"


def _load_clone_module():
    spec = importlib.util.find_spec(MODULE_NAME)
    assert spec is not None, "MiniMax 音色复刻客户端尚未实现"
    return importlib.import_module(MODULE_NAME)


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_minimax_voice_clone_uses_dashscope_voice_clone_contract(monkeypatch):
    clone_module = _load_clone_module()
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(
            {
                "request_id": "req-body",
                "output": {
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                    "data": {"audio": b"preview-mp3".hex()},
                },
            },
            headers={"X-DashScope-Request-Id": "req-header"},
        )

    monkeypatch.setattr(clone_module.httpx, "post", fake_post)

    result = clone_module.create_minimax_voice_clone(
        model="minimax-speech-2.8-hd",
        voice_id="mmx_0123456789abcdef",
        audio_url="https://oss.example.test/reference.wav",
        sample_text="你说是什么就是什么",
        api_key="unit-dashscope-key",
    )

    assert calls == [
        {
            "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
            "json": {
                "model": "MiniMax/speech-2.8-hd",
                "input": {
                    "action": "voice_clone",
                    "voice_id": "mmx_0123456789abcdef",
                    "audio_url": "https://oss.example.test/reference.wav",
                    "text": "你说是什么就是什么",
                },
            },
            "headers": {
                "Authorization": "Bearer unit-dashscope-key",
                "Content-Type": "application/json",
            },
            "timeout": 120.0,
        }
    ]
    assert result["voice_id"] == "mmx_0123456789abcdef"
    assert result["provider_model"] == "MiniMax/speech-2.8-hd"
    assert result["provider_request_id"] == "req-body"
    assert result["preview_audio_bytes"] == b"preview-mp3"


def test_minimax_voice_clone_rejects_provider_business_error(monkeypatch):
    clone_module = _load_clone_module()

    monkeypatch.setattr(
        clone_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "output": {
                    "base_resp": {
                        "status_code": 1001,
                        "status_msg": "reference transcript mismatch",
                    }
                }
            }
        ),
    )

    with pytest.raises(clone_module.MiniMaxVoiceCloneError, match="reference transcript mismatch"):
        clone_module.create_minimax_voice_clone(
            model="minimax-speech-2.8-hd",
            voice_id="mmx_0123456789abcdef",
            audio_url="https://oss.example.test/reference.wav",
            sample_text="错误逐字稿",
            api_key="unit-dashscope-key",
        )


def test_minimax_voice_clone_store_isolates_users_and_models(tmp_path):
    clone_module = _load_clone_module()
    store = clone_module.MiniMaxVoiceCloneStore(tmp_path)

    hd_clone = clone_module.MiniMaxVoiceClone(
        owner_user_id="7",
        voice_id="mmx_aaaaaaaaaaaaaaaa",
        name="主角",
        model="minimax-speech-2.8-hd",
        sample_text="这是主角参考音频。",
        created_at="2026-07-22T10:00:00+00:00",
        provider_request_id="req-hd",
    )
    other_user_clone = clone_module.MiniMaxVoiceClone(
        owner_user_id="8",
        voice_id="mmx_bbbbbbbbbbbbbbbb",
        name="其他用户",
        model="minimax-speech-2.8-hd",
        sample_text="这是其他用户参考音频。",
        created_at="2026-07-22T10:01:00+00:00",
        provider_request_id="req-other",
    )
    store.save(hd_clone)
    store.save(other_user_clone)

    current_user = store.list(owner_user_id="7", model="minimax-speech-2.8-hd")
    assert current_user == [hd_clone]
    assert current_user[0].to_voice_preset() == {
        "id": "mmx_aaaaaaaaaaaaaaaa",
        "speaker": "mmx_aaaaaaaaaaaaaaaa",
        "label": "复刻-主角",
        "category": "custom",
        "customType": "clone",
        "provider": "minimax",
        "description": "MiniMax Speech 2.8 HD 复刻音色；创建时间: 2026-07-22T10:00:00+00:00",
        "default_params": {"volume": 50, "speed": 1.0, "pitch": 0},
    }
    payload = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "audio_url" not in json.dumps(payload)
    assert "preview_audio" not in json.dumps(payload)


def test_minimax_clone_route_returns_explicit_billing_notice(monkeypatch):
    clone_module = _load_clone_module()
    routes_tts = importlib.import_module("app.api.v1.audiobook_api.routes_tts")
    route = getattr(routes_tts, "create_minimax_voice_clone_from_upload", None)
    assert callable(route), "MiniMax 上传复刻路由尚未实现"

    def fake_create_from_bytes(**kwargs):
        assert kwargs["owner_user_id"] == "7"
        assert kwargs["model"] == "minimax-speech-2.8-hd"
        assert kwargs["sample_text"] == "你说是什么就是什么"
        return {
            "clone": clone_module.MiniMaxVoiceClone(
                owner_user_id="7",
                voice_id="mmx_0123456789abcdef",
                name="主角",
                model="minimax-speech-2.8-hd",
                sample_text="你说是什么就是什么",
                created_at="2026-07-22T10:00:00+00:00",
                provider_request_id="req-unit",
            ),
            "preview_audio_bytes": b"preview-mp3",
            "preview_audio_url": "",
        }

    monkeypatch.setattr(routes_tts, "create_minimax_voice_clone_from_bytes", fake_create_from_bytes)
    upload = UploadFile(
        filename="voice.wav",
        file=BytesIO(b"RIFFunit"),
        headers=Headers({"content-type": "audio/wav"}),
    )

    response = asyncio.run(
        route(
            file=upload,
            name="主角",
            sample_text="你说是什么就是什么",
            model="minimax-speech-2.8-hd",
            current_user=SimpleNamespace(id=7),
        )
    )

    assert response["voice_id"] == "mmx_0123456789abcdef"
    assert response["preview_price_per_10k"] == 3.5
    assert response["first_formal_use_fee_yuan"] == 9.9
    assert response["preview_audio_data_base64"] == "cHJldmlldy1tcDM="
    assert "首次用于正式语音合成" in response["billing_notice"]
    assert "9.9" in response["billing_notice"]


def test_tts_voice_catalog_only_merges_current_users_minimax_clones(tmp_path, monkeypatch):
    clone_module = _load_clone_module()
    routes_tts = importlib.import_module("app.api.v1.audiobook_api.routes_tts")
    monkeypatch.setattr(clone_module, "DEFAULT_MINIMAX_VOICE_CLONE_DIR", tmp_path)
    store = clone_module.MiniMaxVoiceCloneStore()
    for owner, voice_id, name in (
        ("7", "mmx_aaaaaaaaaaaaaaaa", "当前用户主角"),
        ("8", "mmx_bbbbbbbbbbbbbbbb", "其他用户角色"),
    ):
        store.save(
            clone_module.MiniMaxVoiceClone(
                owner_user_id=owner,
                voice_id=voice_id,
                name=name,
                model="minimax-speech-2.8-hd",
                sample_text="参考音频逐字内容",
                created_at="2026-07-22T10:00:00+00:00",
            )
        )

    payload = asyncio.run(
        routes_tts.list_tts_voices(
            model="minimax-speech-2.8-hd",
            current_user=SimpleNamespace(id=7),
        )
    )
    voice_ids = {voice["id"] for voice in payload["voices"]}

    assert "mmx_aaaaaaaaaaaaaaaa" in voice_ids
    assert "mmx_bbbbbbbbbbbbbbbb" not in voice_ids


def test_dashscope_adapter_passes_requested_minimax_custom_voice(monkeypatch):
    adapter_module = importlib.import_module("adapters.dashscope.tts")
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append(json)
        return FakeResponse(
            {
                "output": {
                    "base_resp": {"status_code": 0},
                    "data": {"audio": b"tts-audio".hex()},
                }
            }
        )

    monkeypatch.setattr(adapter_module, "DASHSCOPE_API_KEY", "unit-key")
    monkeypatch.setattr(adapter_module.requests, "post", fake_post)

    adapter_class = adapter_module.MiniMaxSpeechHDAdapter
    result = adapter_class(adapter_class.get_model_spec()).generate(
        prompt="正式合成文本",
        speaker="mmx_0123456789abcdef",
    )

    assert result.success is True
    assert calls[0]["input"]["voice_setting"]["voice_id"] == "mmx_0123456789abcdef"
