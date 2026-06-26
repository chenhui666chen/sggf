import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.project_audio_runtime import (
    build_character_voice_mapping_item,
    normalize_base_voice_mapping,
    resolve_project_audio_runtime_config,
)


def test_build_character_voice_mapping_item_keeps_voice_asset_fields_only():
    voice_design_prompt = "young female audiobook voice"
    item = {
        "voice_id": "voice-a",
        "volume": 61,
        "speed": 1.1,
        "pitch": -1,
        "tts_model": "custom-model",
        "voice_type": "warm",
        "personality": "calm",
        "emotion_tendency": "gentle",
        "voice_clone_data_url": "data:audio/wav;base64,AAAA",
        "voice_design_prompt": voice_design_prompt,
    }

    assert build_character_voice_mapping_item(item, tts_model="fallback-model") == {
        "voice_id": "voice-a",
        "tts_model": "custom-model",
        "voice_clone_data_url": "data:audio/wav;base64,AAAA",
        "voice_design_prompt": voice_design_prompt,
    }


def test_build_character_voice_mapping_item_omits_role_level_profiling_and_tuning_defaults():
    item = {
        "voice_id": "voice-a",
        "tts_model": "custom-model",
        "voice_clone_data_url": "data:audio/wav;base64,AAAA",
        "voice_design_prompt": None,
    }

    assert build_character_voice_mapping_item(item, tts_model="fallback-model") == {
        "voice_id": "voice-a",
        "tts_model": "custom-model",
        "voice_clone_data_url": "data:audio/wav;base64,AAAA",
    }


def test_resolve_project_audio_runtime_config_merges_base_then_project_model_config():
    project = SimpleNamespace(
        audio_config=json.dumps(
            {
                "tts_models": {
                    "qwen3-tts-instruct-flash": {
                        "characters": [
                            {"name": "旁白", "voice_id": "new-narrator", "volume": 70},
                            {"name": "", "voice_id": "ignored"},
                        ]
                    }
                },
                "audio_fx": {"enabled": True, "bgm": {"volume": 0.2}},
            },
            ensure_ascii=False,
        )
    )

    runtime = resolve_project_audio_runtime_config(
        project,
        tts_model="qwen3-tts-instruct-flash",
        base_voice_mapping={
            "旁白": {"voice_id": "old-narrator", "volume": 50},
            "旧角色": {"voice_id": "old-role"},
        },
    )

    assert runtime.voice_mapping["旁白"]["voice_id"] == "new-narrator"
    assert "volume" not in runtime.voice_mapping["旁白"]
    assert runtime.voice_mapping["旧角色"]["voice_id"] == "old-role"
    assert "" not in runtime.voice_mapping
    assert runtime.audio_fx == {"enabled": True, "bgm": {"volume": 0.2}}
    assert len(runtime.character_items) == 2


def test_resolve_project_audio_runtime_config_supports_legacy_model_keys():
    project = SimpleNamespace(
        audio_config=json.dumps(
            {
                "tts_models": {
                    "cosyvoice-v3-plus": {
                        "characters": [{"name": "角色A", "voice_id": "cosy-a"}]
                    }
                }
            },
            ensure_ascii=False,
        )
    )

    runtime = resolve_project_audio_runtime_config(
        project,
        tts_model="cosyvoice-v3.5-plus",
    )

    assert runtime.voice_mapping["角色A"]["voice_id"] == "cosy-a"
    assert runtime.voice_mapping["角色A"]["tts_model"] == "cosyvoice-v3.5-plus"


def test_resolve_project_audio_runtime_config_tolerates_empty_or_invalid_config(caplog):
    with caplog.at_level("WARNING", logger="app.services.audiobook.project_audio_config"):
        runtime = resolve_project_audio_runtime_config(
            SimpleNamespace(audio_config="{invalid"),
            tts_model="qwen3-tts-instruct-flash",
            base_voice_mapping={"保留角色": {"voice_id": "existing"}},
        )

    assert runtime.raw_config == {}
    assert runtime.audio_fx == {}
    assert runtime.character_items == []
    assert runtime.voice_mapping == {"保留角色": {"voice_id": "existing"}}
    assert "项目音频配置 JSON 损坏，已忽略" in caplog.text


def test_normalize_base_voice_mapping_accepts_json_string_and_ignores_invalid_items():
    raw_mapping = json.dumps(
        {
            "角色A": {"voice_id": "voice-a"},
            "角色B": None,
            "角色C": "invalid",
        },
        ensure_ascii=False,
    )

    assert normalize_base_voice_mapping(raw_mapping) == {"角色A": {"voice_id": "voice-a"}}
    assert normalize_base_voice_mapping("not-json") == {}
