import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.v1.projects import CharacterAudioConfig, _dump_persisted_character_audio_config


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
