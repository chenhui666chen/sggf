import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.schemas.audiobook import CharacterVoiceConfig
from app.services.audiobook.app_service import AudiobookAppService


def test_request_voice_config_preserves_mimo_inline_custom_voice_fields() -> None:
    service = object.__new__(AudiobookAppService)
    voice_mapping = {}

    service._apply_request_voice_config(
        voice_mapping,
        [
            CharacterVoiceConfig(
                character_name="CloneRole",
                voice_id="",
                volume=64,
                tts_model="mimo-v2.5-tts-voiceclone",
                voice_clone_data_url="data:audio/wav;base64,AAAA",
            ),
            CharacterVoiceConfig(
                character_name="DesignRole",
                voice_id="",
                volume=58,
                tts_model="mimo-v2.5-tts-voicedesign",
                voice_design_prompt="青年女性，中音，语速中等，清亮但克制，适合有声书对白",
            ),
        ],
    )

    assert voice_mapping["CloneRole"]["voice_clone_data_url"] == "data:audio/wav;base64,AAAA"
    assert voice_mapping["CloneRole"]["voice_id"] == ""
    assert voice_mapping["DesignRole"]["voice_design_prompt"] == "青年女性，中音，语速中等，清亮但克制，适合有声书对白"
    assert voice_mapping["DesignRole"]["voice_id"] == ""


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
