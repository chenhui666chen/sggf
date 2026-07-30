import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.projects import (
    CharacterAudioConfig,
    ProjectAudioConfig,
    _dump_persisted_character_audio_config,
)
from app.services.audiobook.project_audio_config import (
    get_audio_engine_mode,
    get_seed_audio_model,
    set_audio_engine_mode,
    set_seed_audio_model,
)


def test_persisted_character_audio_config_only_keeps_model_and_voice_reference():
    config = CharacterAudioConfig(
        character_id=1,
        name="RuntimeRole",
        voice_id="Neil",
        volume=72,
        speed=1.4,
        pitch=35,
        tts_model="qwen3-tts-instruct-flash",
        voice_type="cold",
        personality="rational",
        emotion_tendency="negative",
        voice_clone_data_url="data:audio/wav;base64,AAAA",
        mimo_voice_asset_id="mimo_clone_unit",
        stepaudio_voice_asset_id="stepaudio_clone_unit",
        source="user",
    )

    assert _dump_persisted_character_audio_config(config) == {
        "character_id": 1,
        "name": "RuntimeRole",
        "voice_id": "Neil",
        "tts_model": "qwen3-tts-instruct-flash",
    }


def test_persisted_character_audio_config_hydrates_legacy_asset_ids_as_voice_references():
    mimo_config = CharacterAudioConfig(
        character_id=2,
        name="ReusableDesign",
        voice_id="",
        tts_model="mimo-v2.5-tts-voicedesign",
        voice_design_prompt="legacy inline prompt",
        mimo_voice_asset_id="mimo_design_unit",
    )
    stepaudio_config = CharacterAudioConfig(
        character_id=3,
        name="ReusableStepAudioClone",
        voice_id="",
        tts_model="stepaudio-2.5-tts",
        stepaudio_voice_asset_id="stepaudio_clone_unit",
    )

    assert _dump_persisted_character_audio_config(mimo_config) == {
        "character_id": 2,
        "name": "ReusableDesign",
        "voice_id": "mimo_design:mimo_design_unit",
        "tts_model": "mimo-v2.5-tts-voicedesign",
    }
    assert _dump_persisted_character_audio_config(stepaudio_config) == {
        "character_id": 3,
        "name": "ReusableStepAudioClone",
        "voice_id": "stepaudio_clone:stepaudio_clone_unit",
        "tts_model": "stepaudio-2.5-tts",
    }


def test_project_audio_config_validates_and_persists_scene_engine_mode():
    data = {}

    set_audio_engine_mode(data, "seed_scene")

    assert get_audio_engine_mode(data) == "seed_scene"
    assert ProjectAudioConfig(
        characters=[],
        audio_engine_mode="seed_scene",
    ).audio_engine_mode == "seed_scene"


def test_project_audio_config_rejects_unknown_scene_engine_mode():
    with pytest.raises(ValidationError):
        ProjectAudioConfig(
            characters=[],
            audio_engine_mode="unbounded-experiment",
        )

    with pytest.raises(ValueError, match="unsupported audio_engine_mode"):
        set_audio_engine_mode({}, "unbounded-experiment")


def test_project_audio_config_validates_and_persists_seed_audio_model():
    data = {}

    set_seed_audio_model(data, "seed-audio-1.0")

    assert get_seed_audio_model(data) == "seed-audio-1.0"
    assert ProjectAudioConfig(
        characters=[],
        seed_audio_model="seed-audio-1.0",
    ).seed_audio_model == "seed-audio-1.0"


def test_project_audio_config_disables_multilingual_seed_audio_model():
    # multilingual 变体已实现但暂不启用：set 拒绝、get 回退默认、schema 校验失败。
    with pytest.raises(ValueError, match="unsupported seed_audio_model"):
        set_seed_audio_model({}, "seed-audio-1.0-multilingual")

    assert (
        get_seed_audio_model({"seed_audio_model": "seed-audio-1.0-multilingual"})
        == "seed-audio-1.0"
    )

    with pytest.raises(ValidationError):
        ProjectAudioConfig(
            characters=[],
            seed_audio_model="seed-audio-1.0-multilingual",
        )


def test_project_audio_config_rejects_unknown_seed_audio_model():
    with pytest.raises(ValidationError):
        ProjectAudioConfig(characters=[], seed_audio_model="seed-audio-next")

    with pytest.raises(ValueError, match="unsupported seed_audio_model"):
        set_seed_audio_model({}, "seed-audio-next")
