import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import routes_tts
from app.services.audiobook.cosyvoice_clone_client import CosyVoiceClone


LOGGER_NAME = "app.api.v1.audiobook_api.routes_tts"


def test_model_catalog_logs_clone_list_failure_without_blocking(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        routes_tts,
        "load_voice_catalog_for_model",
        lambda model: {"voices": [], "meta": {"model": model, "voice_count": 0}},
    )

    def fail_clone_list(**_kwargs):
        raise routes_tts.CosyVoiceCloneError("missing api key")

    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", fail_clone_list)

    with caplog.at_level("INFO", logger=LOGGER_NAME):
        voice_count, catalog_status, catalog_error = routes_tts._build_model_voice_catalog_status(
            routes_tts.COSYVOICE_V35_PLUS_MODEL_ID
        )

    assert voice_count == 0
    assert catalog_status == "ready"
    assert catalog_error is None
    assert "CosyVoice 自定义音色列表不可用" in caplog.text
    assert "missing api key" in caplog.text


def test_list_tts_voices_logs_clone_list_failure_and_returns_static_catalog(monkeypatch, caplog) -> None:
    static_voice = {"id": "static-voice", "name": "Static Voice", "speaker": "static-voice"}
    monkeypatch.setattr(
        routes_tts,
        "load_voice_catalog_for_model",
        lambda model: {
            "voices": [static_voice],
            "meta": {"model": model, "updated_at": "unit-test", "source": "unit"},
        },
    )

    def fail_clone_list(**_kwargs):
        raise routes_tts.CosyVoiceCloneError("missing api key")

    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", fail_clone_list)

    with caplog.at_level("INFO", logger=LOGGER_NAME):
        payload = asyncio.run(
            routes_tts.list_tts_voices(
                model=routes_tts.COSYVOICE_V35_PLUS_MODEL_ID,
                current_user=SimpleNamespace(id=1),
            )
        )

    assert payload["model"] == routes_tts.COSYVOICE_V35_PLUS_MODEL_ID
    assert payload["voice_count"] == 1
    assert payload["voices"] == [static_voice]
    assert "CosyVoice 自定义音色列表不可用" in caplog.text
    assert "missing api key" in caplog.text


def test_list_tts_voices_merges_cosyvoice_custom_clone_and_design_voices(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_tts,
        "load_voice_catalog_for_model",
        lambda model: {
            "voices": [],
            "meta": {"model": model, "updated_at": "unit-test", "source": "unit"},
        },
    )
    monkeypatch.setattr(
        routes_tts,
        "list_cosyvoice_v3_plus_clones",
        lambda **_kwargs: (
            [
                CosyVoiceClone(
                    voice_id="cosyvoice-v3.5-plus-vclone-111",
                    status="OK",
                    gmt_create="2026-01-01T00:00:00Z",
                    custom_type="clone",
                ),
                CosyVoiceClone(
                    voice_id="cosyvoice-v3.5-plus-vdesign-222",
                    status="OK",
                    gmt_create="2026-01-02T00:00:00Z",
                    custom_type="design",
                    voice_prompt="温柔的女声",
                    preview_text="你好",
                ),
            ],
            {"cached": False},
        ),
    )
    monkeypatch.setattr(
        routes_tts,
        "get_clone_display_name",
        lambda voice_id: {
            "cosyvoice-v3.5-plus-vclone-111": "克隆甲",
            "cosyvoice-v3.5-plus-vdesign-222": "设计乙",
            }.get(voice_id),
        )
    monkeypatch.setattr(
        routes_tts,
        "get_clone_owner_user_id",
        lambda _voice_id: 1,
    )

    payload = asyncio.run(
        routes_tts.list_tts_voices(
            model=routes_tts.COSYVOICE_V35_PLUS_MODEL_ID,
            current_user=SimpleNamespace(id=1),
        )
    )

    assert payload["model"] == routes_tts.COSYVOICE_V35_PLUS_MODEL_ID
    assert payload["voice_count"] == 2
    assert [voice["id"] for voice in payload["voices"]] == [
        "cosyvoice-v3.5-plus-vclone-111",
        "cosyvoice-v3.5-plus-vdesign-222",
    ]
    assert {voice["customType"] for voice in payload["voices"]} == {"clone", "design"}
    assert all(voice["category"] == "custom" for voice in payload["voices"])
    assert payload["voices"][0]["speaker"] == "cosyvoice-v3.5-plus-vclone-111"
    assert payload["voices"][1]["label"] == "设计-设计乙"


def test_upload_clone_audio_logs_close_failure_without_blocking(monkeypatch, caplog) -> None:
    class UploadFileWithFailingClose:
        filename = "voice.wav"
        content_type = "audio/wav"

        async def read(self):
            return b"audio-bytes"

        async def close(self):
            raise RuntimeError("close failed")

    def fake_upload_sample(**kwargs):
        return {
            "filename": kwargs["filename"],
            "content_type": kwargs["content_type"],
            "url": "oss://unit-test/voice.wav",
        }

    monkeypatch.setattr(routes_tts, "upload_cosyvoice_v3_plus_clone_sample", fake_upload_sample)

    with caplog.at_level("DEBUG", logger=LOGGER_NAME):
        payload = asyncio.run(
            routes_tts.upload_cosyvoice_v3_plus_clone_audio(
                file=UploadFileWithFailingClose(),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert payload == {
        "filename": "voice.wav",
        "content_type": "audio/wav",
        "url": "oss://unit-test/voice.wav",
    }
    assert "关闭 CosyVoice 上传文件失败" in caplog.text
    assert "close failed" in caplog.text
