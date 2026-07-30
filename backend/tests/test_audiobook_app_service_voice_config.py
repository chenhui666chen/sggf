import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.schemas.audiobook import CharacterVoiceConfig
from app.services.audiobook.app_service import AudiobookAppService
import app.services.audiobook.app_service as app_service_module


def test_request_voice_config_only_keeps_model_and_voice_reference() -> None:
    service = object.__new__(AudiobookAppService)
    voice_mapping = {}

    service._apply_request_voice_config(
        voice_mapping,
        [
            CharacterVoiceConfig(
                character_name="CloneRole",
                voice_id="mimo_clone:unit",
                volume=64,
                tts_model="mimo-v2.5-tts-voiceclone",
                voice_clone_data_url="data:audio/wav;base64,AAAA",
            ),
            CharacterVoiceConfig(
                character_name="DesignRole",
                voice_id="mimo_design:unit",
                volume=58,
                tts_model="mimo-v2.5-tts-voicedesign",
                voice_design_prompt="青年女性，中音，语速中等，清亮但克制，适合有声书对白",
            ),
        ],
    )

    assert voice_mapping == {
        "CloneRole": {
            "voice_id": "mimo_clone:unit",
            "tts_model": "mimo-v2.5-tts-voiceclone",
        },
        "DesignRole": {
            "voice_id": "mimo_design:unit",
            "tts_model": "mimo-v2.5-tts-voicedesign",
        },
    }


def test_request_voice_config_omits_unset_role_level_profiling_and_tuning_fields() -> None:
    service = object.__new__(AudiobookAppService)
    voice_mapping = {}

    service._apply_request_voice_config(
        voice_mapping,
        [
            CharacterVoiceConfig(
                character_name="RuntimeDirectedRole",
                voice_id="Neil",
                tts_model="qwen3-tts-instruct-flash",
            ),
        ],
    )

    assert voice_mapping["RuntimeDirectedRole"] == {
        "voice_id": "Neil",
        "tts_model": "qwen3-tts-instruct-flash",
    }


def test_private_reference_is_resolved_from_owned_database_asset(monkeypatch) -> None:
    service = object.__new__(AudiobookAppService)
    service.db = object()
    service.current_user = SimpleNamespace(id=7)
    def validate_references(_db, *, owner_user_id, voice_mapping):
        assert owner_user_id == 7
        voice_mapping["女主"].update(
            {
                "reference_audio_url": "https://oss.example.com/private/reference.mp3",
                "voice_reference_owner_user_id": 7,
                "voice_id": "mimo_design:owned",
                "tts_model": "mimo-v2.5-tts-voicedesign",
            }
        )

    monkeypatch.setattr(app_service_module, "validate_project_voice_references", validate_references)
    voice_mapping = {}

    service._apply_request_voice_config(
        voice_mapping,
        [
            CharacterVoiceConfig(
                character_name="女主",
                voice_id="client-spoofed-id",
                tts_model="client-spoofed-model",
                reference_source="user_private",
                reference_audio_url="https://attacker.example/spoof.mp3",
                voice_reference_asset_id="ug-owned",
            )
        ],
    )

    assert voice_mapping["女主"] == {
        "voice_id": "mimo_design:owned",
        "tts_model": "mimo-v2.5-tts-voicedesign",
        "reference_source": "user_private",
        "reference_audio_url": "https://oss.example.com/private/reference.mp3",
        "voice_reference_asset_id": "ug-owned",
        "voice_reference_owner_user_id": 7,
    }


def test_private_reference_rejects_unowned_or_revoked_asset(monkeypatch) -> None:
    service = object.__new__(AudiobookAppService)
    service.db = object()
    service.current_user = SimpleNamespace(id=7)
    monkeypatch.setattr(
        app_service_module,
        "validate_project_voice_references",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("已撤销")),
    )

    with pytest.raises(HTTPException) as exc_info:
        service._apply_request_voice_config(
            {},
            [
                CharacterVoiceConfig(
                    character_name="女主",
                    voice_id="private:foreign",
                    reference_source="user_private",
                    voice_reference_asset_id="ug-foreign",
                )
            ],
        )

    assert exc_info.value.status_code == 403


def test_auto_assign_voices_only_assigns_explicitly_scoped_characters(monkeypatch) -> None:
    assigned_names: list[str] = []

    class FakePool:
        def __init__(self, **_kwargs) -> None:
            pass

        def assign(self, name, _traits):
            assigned_names.append(name)
            return SimpleNamespace(
                profile=SimpleNamespace(voice_id=f"voice-{name}"),
                model="qwen3-tts-instruct-flash",
            )

    monkeypatch.setattr(app_service_module, "AutoVoiceAssignmentPool", FakePool)

    service = object.__new__(AudiobookAppService)
    service.character_repo = SimpleNamespace(
        list_by_project=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("显式传入章节人物时不应再次查询全项目人物")
        )
    )
    service.db = object()
    voice_mapping = {}
    scoped_character = SimpleNamespace(
        id=1,
        name="裴世清",
        gender="男",
        age=30,
        importance_level="主角",
    )

    service._auto_assign_voices(
        3,
        voice_mapping,
        "qwen3-tts-instruct-flash",
        characters=[scoped_character],
    )

    assert assigned_names == ["裴世清"]
    assert set(voice_mapping) == {"裴世清"}
