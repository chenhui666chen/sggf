import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.schemas.audiobook import AudiobookProjectCreate, CharacterVoiceConfig


def test_create_request_defaults_to_script_only_generation() -> None:
    request = AudiobookProjectCreate(
        project_id=1,
        chapter_ids=[1],
    )

    assert request.generation_mode == "script_only"


def test_character_voice_config_only_keeps_model_and_voice_reference() -> None:
    config = CharacterVoiceConfig(
        character_name="旁白",
        voice_id="mimo_clone:unit",
        tts_model="mimo-v2.5-tts-voiceclone",
        volume=72,
        speed=1.4,
        pitch=35,
        voice_type="cold",
        voice_clone_data_url="data:audio/wav;base64,STALE",
        mimo_voice_asset_id="unit",
    )

    assert config.model_dump() == {
        "character_name": "旁白",
        "voice_id": "mimo_clone:unit",
        "tts_model": "mimo-v2.5-tts-voiceclone",
    }
