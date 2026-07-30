import asyncio
import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import routes_tts
from app.api.v1.audiobook_api.routes_tts import list_tts_models, list_tts_voices
from app.schemas.audiobook import CosyVoiceCloneCreateRequest, TTSPreviewRequest
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    SUPPORTED_AUDIOBOOK_TTS_MODELS,
    get_audiobook_tts_model_metadata,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_style_capabilities,
    get_audiobook_tts_model_price_per_10k,
    is_supported_audiobook_tts_model,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.narration_styles import get_all_narration_styles
from app.services.audiobook.tts_engine_pkg import TTSEngine
from app.services.audiobook.tts_style_control import normalize_emotion_for_model
from app.services.audiobook.voice_catalog import load_voice_catalog_for_model
from app.services.audiobook.voice_auto_assignment import AutoVoiceAssignmentPool
from app.services.audiobook.voice_manager_factory import create_voice_manager, get_model_for_voice, list_supported_models
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_manager_mimo import MiMoVoiceManager
from app.services.audiobook import voice_manager_cosyvoice_v3_plus as cosyvoice_v3_plus
from app.services.audiobook import tts_model_ids
from app.services.audiobook.engine_pkg._tts_mixin import (
    TTSMixin,
    subtract_tts_cost_stats,
)
from app.services.audiobook.voice_manager_minimax import MiniMaxVoiceManager
from app.services.audiobook.voice_manager_stepaudio import StepAudioVoiceManager
from core.unified_media_runtime import create_tts_engine, get_media_runtime
from core.model_resolution import normalize_model_id


@pytest.mark.parametrize(
    ("model_id", "expected_price", "expected_status"),
    [
        (DEFAULT_AUDIOBOOK_TTS_MODEL, 0.8, "public_postpaid"),
        ("cosyvoice-v3.5-plus", 1.5, "public_postpaid"),
        (MINIMAX_SPEECH_28_TURBO_MODEL, 2.0, "public_postpaid"),
        (MINIMAX_SPEECH_28_HD_MODEL, 3.5, "public_postpaid"),
        (MIMO_V25_TTS_MODEL, 0.0, "limited_time_free"),
        (MIMO_V25_TTS_VOICE_DESIGN_MODEL, 0.0, "limited_time_free"),
        (MIMO_V25_TTS_VOICE_CLONE_MODEL, 0.0, "limited_time_free"),
        (STEPAUDIO_25_TTS_MODEL, 5.8, "public_postpaid"),
        (SEED_TTS_20_EXPRESSIVE_MODEL, 3.0, "public_postpaid"),
    ],
)
def test_audiobook_tts_catalog_uses_public_postpaid_user_prices(
    model_id: str,
    expected_price: float,
    expected_status: str,
) -> None:
    metadata = get_audiobook_tts_model_metadata(model_id)

    assert get_audiobook_tts_model_price_per_10k(model_id) == expected_price
    assert metadata["pricing_status"] == expected_status
    assert metadata["pricing_basis"] == "public_list_price"


def test_audiobook_tts_catalog_records_fixed_custom_voice_fees() -> None:
    minimax = get_audiobook_tts_model_metadata(MINIMAX_SPEECH_28_TURBO_MODEL)
    stepaudio = get_audiobook_tts_model_metadata(STEPAUDIO_25_TTS_MODEL)
    seed_tts = get_audiobook_tts_model_metadata(SEED_TTS_20_EXPRESSIVE_MODEL)

    assert minimax["custom_voice_pricing"]["first_formal_use_yuan"] == 9.9
    assert stepaudio["custom_voice_pricing"]["formal_clone_success_yuan"] == 9.9
    assert seed_tts["custom_voice_pricing"] == {
        "postpaid_slot_first_formal_use_yuan": 138.0,
        "preview_price_per_10k": 3.0,
        "unused_preview_retention_days": 7,
    }


@pytest.mark.parametrize(
    ("model_id", "expected_price"),
    [
        (DEFAULT_AUDIOBOOK_TTS_MODEL, 0.8),
        ("cosyvoice-v3.5-plus", 1.5),
        (MINIMAX_SPEECH_28_TURBO_MODEL, 2.0),
        (MINIMAX_SPEECH_28_HD_MODEL, 3.5),
        (MIMO_V25_TTS_MODEL, 0.0),
        (MIMO_V25_TTS_VOICE_DESIGN_MODEL, 0.0),
        (MIMO_V25_TTS_VOICE_CLONE_MODEL, 0.0),
        (STEPAUDIO_25_TTS_MODEL, 5.8),
        (SEED_TTS_20_EXPRESSIVE_MODEL, 3.0),
    ],
)
def test_tts_runtime_engine_uses_catalog_price(model_id: str, expected_price: float) -> None:
    engine = TTSEngine(enable_cache=False, request_delay=0, model=model_id)

    assert engine.price_per_10k == expected_price


def test_mixed_model_cost_stats_include_every_runtime_engine() -> None:
    class FakeEngine:
        def __init__(self, model: str, stats: dict[str, object]) -> None:
            self.model = model
            self._stats = stats

        def get_cost_stats(self) -> dict[str, object]:
            return dict(self._stats)

    harness = TTSMixin()
    harness.tts_engine = FakeEngine(
        DEFAULT_AUDIOBOOK_TTS_MODEL,
        {
            "total_characters": 1000,
            "total_segments": 2,
            "cache_hits": 1,
            "api_calls": 1,
            "failed_segments": 0,
            "failed_characters": 0,
            "estimated_cost": "¥0.08",
        },
    )
    harness._tts_engines_by_model = {
        MINIMAX_SPEECH_28_TURBO_MODEL: FakeEngine(
            MINIMAX_SPEECH_28_TURBO_MODEL,
            {
                "total_characters": 10000,
                "total_segments": 1,
                "cache_hits": 0,
                "api_calls": 1,
                "failed_segments": 1,
                "failed_characters": 30,
                "estimated_cost": "¥2.00",
            },
        )
    }

    stats = harness._aggregate_tts_cost_stats()

    assert stats["total_characters"] == 11000
    assert stats["total_segments"] == 3
    assert stats["cache_hits"] == 1
    assert stats["cache_hit_rate"] == "33.3%"
    assert stats["api_calls"] == 2
    assert stats["failed_segments"] == 1
    assert stats["failed_characters"] == 30
    assert stats["estimated_cost"] == "¥2.08"
    assert set(stats["by_model"]) == {
        DEFAULT_AUDIOBOOK_TTS_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
    }


def test_tts_cost_stats_can_be_scoped_to_current_chapter() -> None:
    baseline = {
        "total_characters": 11000,
        "total_segments": 3,
        "cache_hits": 1,
        "api_calls": 2,
        "failed_segments": 1,
        "failed_characters": 30,
        "estimated_cost_yuan": 2.08,
        "estimated_cost": "¥2.08",
        "by_model": {
            DEFAULT_AUDIOBOOK_TTS_MODEL: {
                "total_characters": 1000,
                "total_segments": 2,
                "cache_hits": 1,
                "api_calls": 1,
                "failed_segments": 0,
                "failed_characters": 0,
                "estimated_cost_yuan": 0.08,
                "estimated_cost": "¥0.08",
            },
            MINIMAX_SPEECH_28_TURBO_MODEL: {
                "total_characters": 10000,
                "total_segments": 1,
                "cache_hits": 0,
                "api_calls": 1,
                "failed_segments": 1,
                "failed_characters": 30,
                "estimated_cost_yuan": 2.0,
                "estimated_cost": "¥2.00",
            },
        },
    }
    current = {
        "total_characters": 21000,
        "total_segments": 5,
        "cache_hits": 2,
        "api_calls": 3,
        "failed_segments": 1,
        "failed_characters": 30,
        "estimated_cost_yuan": 3.08,
        "estimated_cost": "¥3.08",
        "by_model": {
            **baseline["by_model"],
            DEFAULT_AUDIOBOOK_TTS_MODEL: {
                "total_characters": 11000,
                "total_segments": 4,
                "cache_hits": 2,
                "api_calls": 2,
                "failed_segments": 0,
                "failed_characters": 0,
                "estimated_cost_yuan": 1.08,
                "estimated_cost": "¥1.08",
            },
        },
    }

    chapter = subtract_tts_cost_stats(current, baseline)

    assert chapter["total_characters"] == 10000
    assert chapter["total_segments"] == 2
    assert chapter["cache_hits"] == 1
    assert chapter["cache_hit_rate"] == "50.0%"
    assert chapter["api_calls"] == 1
    assert chapter["failed_segments"] == 0
    assert chapter["failed_characters"] == 0
    assert chapter["estimated_cost_yuan"] == 1.0
    assert chapter["estimated_cost"] == "¥1.00"
    assert set(chapter["by_model"]) == {DEFAULT_AUDIOBOOK_TTS_MODEL}


def test_audiobook_tts_model_normalization_keeps_business_model_ids() -> None:
    assert normalize_audiobook_tts_model("MiniMax/speech-2.8-hd") == MINIMAX_SPEECH_28_HD_MODEL
    assert normalize_audiobook_tts_model("MiniMax/speech-2.8-turbo") == MINIMAX_SPEECH_28_TURBO_MODEL
    assert normalize_audiobook_tts_model("minimax-speech-2.8") == MINIMAX_SPEECH_28_HD_MODEL
    assert normalize_audiobook_tts_model("qwen3-tts-flash") == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert normalize_audiobook_tts_model("qwen3-tts-plus") == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert normalize_audiobook_tts_model("MiMo/V2.5-TTS") == MIMO_V25_TTS_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-voicedesign") == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-voice-design") == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-voiceclone") == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-voice-clone") == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert normalize_audiobook_tts_model("StepAudio-2.5-TTS") == STEPAUDIO_25_TTS_MODEL
    assert normalize_audiobook_tts_model("stepaudio_2_5_tts") == STEPAUDIO_25_TTS_MODEL
    assert normalize_audiobook_tts_model("stepfun/stepaudio-2.5-tts") == STEPAUDIO_25_TTS_MODEL
    assert normalize_audiobook_tts_model("seed-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("doubao/seed-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("doubao-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-hd", default="") == ""
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-turbo", default="") == ""
    assert is_supported_audiobook_tts_model("MiniMax/speech-2.8-hd") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-voicedesign") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-voiceclone") is True
    assert is_supported_audiobook_tts_model("stepaudio-2.5-tts") is True
    assert is_supported_audiobook_tts_model("seed-tts-2.0-expressive") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-hd") is False
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-turbo") is False
    assert is_supported_audiobook_tts_model("unknown-tts-model") is False
    assert normalize_model_id("MiniMax/speech-2.8-hd") == "MiniMax/speech-2.8-hd"
    assert get_audiobook_tts_runtime_model_id(MINIMAX_SPEECH_28_HD_MODEL) == "MiniMax/speech-2.8-hd"
    assert get_audiobook_tts_runtime_model_id(MINIMAX_SPEECH_28_TURBO_MODEL) == "MiniMax/speech-2.8-turbo"
    assert get_audiobook_tts_runtime_model_id(MIMO_V25_TTS_MODEL) == MIMO_V25_TTS_MODEL
    assert get_audiobook_tts_runtime_model_id(MIMO_V25_TTS_VOICE_DESIGN_MODEL) == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert get_audiobook_tts_runtime_model_id(MIMO_V25_TTS_VOICE_CLONE_MODEL) == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert get_audiobook_tts_runtime_model_id(STEPAUDIO_25_TTS_MODEL) == STEPAUDIO_25_TTS_MODEL
    assert get_audiobook_tts_runtime_model_id(SEED_TTS_20_EXPRESSIVE_MODEL) == SEED_TTS_20_EXPRESSIVE_MODEL


def test_audiobook_tts_model_style_capabilities_are_exposed() -> None:
    qwen_caps = get_audiobook_tts_style_capabilities(DEFAULT_AUDIOBOOK_TTS_MODEL)
    assert qwen_caps["model_family"] == "qwen"
    assert qwen_caps["preferred_style_control_mode"] == "natural_language"
    assert qwen_caps["style_control_modes"] == ["natural_language"]
    assert qwen_caps["supports_voice_description"] is True
    assert qwen_caps["supports_audio_tags"] is False
    assert qwen_caps["instruction_budget"] == 600
    assert qwen_caps["supported_emotions"] == [
        "neutral",
        "happy",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "disgusted",
    ]

    mimo_caps = get_audiobook_tts_style_capabilities(MIMO_V25_TTS_MODEL)
    assert mimo_caps["model_family"] == "mimo"
    assert mimo_caps["preferred_style_control_mode"] == "director"
    assert mimo_caps["style_control_modes"] == ["director", "audio_tags", "natural_language"]
    assert mimo_caps["supports_director_mode"] is True
    assert mimo_caps["supports_audio_tags"] is True
    assert mimo_caps["supports_emotion_mixing"] is True
    assert mimo_caps["supports_micro_tags"] is True
    assert mimo_caps["supports_word_level_control"] is True
    assert mimo_caps["control_message_roles"] == {
        "director": "user",
        "audio_tags": "assistant",
        "natural_language": "user",
    }
    assert mimo_caps["has_system_voices"] is True
    assert mimo_caps["supports_singing"] is True
    assert mimo_caps["supports_streaming"] is True
    assert mimo_caps["supports_voice_design"] is False
    assert mimo_caps["supports_voice_clone"] is False

    design_caps = get_audiobook_tts_style_capabilities(MIMO_V25_TTS_VOICE_DESIGN_MODEL)
    assert design_caps["model_family"] == "mimo"
    assert design_caps["preferred_style_control_mode"] == "voice_design"
    assert design_caps["style_control_modes"] == ["voice_design", "natural_language"]
    assert design_caps["has_system_voices"] is False
    assert design_caps["requires_custom_voice"] is True
    assert design_caps["supports_voice_design"] is True
    assert design_caps["supports_voice_clone"] is False
    assert design_caps["supports_director_mode"] is False
    assert design_caps["supports_audio_tags"] is False
    assert design_caps["supports_micro_tags"] is False
    assert design_caps["supports_word_level_control"] is False
    assert design_caps["supports_singing"] is False
    assert design_caps["control_message_roles"] == {
        "voice_design": "user",
        "natural_language": "user",
    }

    clone_caps = get_audiobook_tts_style_capabilities(MIMO_V25_TTS_VOICE_CLONE_MODEL)
    assert clone_caps["model_family"] == "mimo"
    assert clone_caps["style_control_modes"] == ["director", "audio_tags", "natural_language"]
    assert clone_caps["preferred_style_control_mode"] == "director"
    assert clone_caps["has_system_voices"] is False
    assert clone_caps["requires_custom_voice"] is True
    assert clone_caps["supports_voice_clone"] is True
    assert clone_caps["supports_voice_design"] is False
    assert clone_caps["supports_director_mode"] is True
    assert clone_caps["supports_audio_tags"] is True
    assert clone_caps["supports_singing"] is False
    assert clone_caps["control_message_roles"]["voice_clone"] == "audio.voice"

    stepaudio_caps = get_audiobook_tts_style_capabilities(STEPAUDIO_25_TTS_MODEL)
    assert stepaudio_caps["model_family"] == "stepaudio"
    assert stepaudio_caps["preferred_style_control_mode"] == "global_context"
    assert stepaudio_caps["style_control_modes"] == ["global_context", "inline_context", "natural_language"]
    assert stepaudio_caps["supports_voice_description"] is True
    assert stepaudio_caps["supports_audio_tags"] is False
    assert stepaudio_caps["supports_emotion_mixing"] is True
    assert stepaudio_caps["supports_micro_tags"] is True
    assert stepaudio_caps["supports_word_level_control"] is True
    assert stepaudio_caps["supports_voice_clone"] is True
    assert stepaudio_caps["supports_streaming"] is True
    assert stepaudio_caps["instruction_budget"] == 200
    assert stepaudio_caps["max_input_chars"] == 1000
    assert stepaudio_caps["control_message_roles"] == {
        "global_context": "parameters.instruction",
        "inline_context": "input.parentheses",
        "natural_language": "parameters.instruction",
    }

    seed_caps = get_audiobook_tts_style_capabilities(SEED_TTS_20_EXPRESSIVE_MODEL)
    assert seed_caps["model_family"] == "doubao"
    assert seed_caps["preferred_style_control_mode"] == "query_response"
    assert seed_caps["style_control_modes"] == ["query_response", "audio_tags", "natural_language"]
    assert seed_caps["supports_voice_description"] is True
    assert seed_caps["supports_emotion_mixing"] is True
    assert seed_caps["supports_micro_tags"] is True
    assert seed_caps["supports_voice_clone"] is True
    assert seed_caps["supports_streaming"] is True
    assert seed_caps["control_message_roles"] == {
        "query_response": "additions.context_texts",
        "audio_tags": "req_params.text + req_params.use_tag_parser",
        "natural_language": "additions.context_texts",
    }

    minimax_caps = get_audiobook_tts_style_capabilities(MINIMAX_SPEECH_28_HD_MODEL)
    assert minimax_caps["model_family"] == "minimax"
    assert minimax_caps["preferred_style_control_mode"] == "basic"
    assert minimax_caps["style_control_modes"] == ["basic"]
    assert minimax_caps["supports_audio_tags"] is False
    assert minimax_caps["supports_voice_clone"] is True
    assert minimax_caps["supported_emotions"] == []

    unknown_caps = get_audiobook_tts_style_capabilities("unknown-tts")
    assert unknown_caps["model_family"] == "generic"
    assert unknown_caps["preferred_style_control_mode"] == "natural_language"


def test_audiobook_tts_model_metadata_returns_independent_capability_copy() -> None:
    metadata = get_audiobook_tts_model_metadata(MIMO_V25_TTS_MODEL)
    metadata["capabilities"]["style_control_modes"].append("broken")

    fresh = get_audiobook_tts_model_metadata(MIMO_V25_TTS_MODEL)

    assert "broken" not in fresh["capabilities"]["style_control_modes"]


def test_tts_emotion_normalization_uses_model_capability_matrix(monkeypatch) -> None:
    original_caps = tts_model_ids.get_audiobook_tts_style_capabilities("cosyvoice-v3.5-plus")
    monkeypatch.setitem(
        tts_model_ids.AUDIOBOOK_TTS_STYLE_CAPABILITIES,
        "cosyvoice-v3.5-plus",
        {
            **original_caps,
            "supported_emotions": ["neutral", "fearful"],
            "emotion_aliases": {"panicked": "fearful"},
        },
    )

    engine = TTSEngine(model="cosyvoice-v3.5-plus")

    assert tts_model_ids.normalize_audiobook_tts_emotion("panicked", "cosyvoice-v3.5-plus") == "fearful"
    assert normalize_emotion_for_model("panicked", "cosyvoice-v3.5-plus") == "fearful"
    assert engine._normalize_emotion("panicked") == "fearful"


def test_stepaudio_emotion_is_not_downgraded_by_generic_aliyun_mapping() -> None:
    """stepaudio/mimo 等模型的情感只进入风格指令文本，不是阿里云 API 枚举，
    不应被硬编码降级表把 fearful/disgusted 降成 tense/angry。"""
    engine = TTSEngine(model="stepaudio-2.5-tts")

    assert engine._normalize_emotion("fearful") == "fearful"
    assert engine._normalize_emotion("disgusted") == "disgusted"

    qwen_engine = TTSEngine(model="qwen3-tts-instruct-flash")
    # qwen 能力矩阵显式声明支持 fearful，不应降级；tense 按矩阵别名归一到 fearful
    assert qwen_engine._normalize_emotion("fearful") == "fearful"
    assert qwen_engine._normalize_emotion("tense") == "fearful"


def test_narrator_speed_is_stable_across_emotions() -> None:
    """旁白语速不应随逐段 emotion 标签机械变速（导致忽快忽慢），
    情绪层次交给风格指令/performance_notes 表达；角色台词仍保留情感变速。"""
    from app.services.audiobook.voice_manager import VoiceProfile

    narrator = VoiceProfile(
        voice_id="narrator_voice",
        character_name="旁白",
        gender="male",
        age_group="adult",
        personality="calm",
        tts_speaker_id="stepaudio_narrator",
        speed_base=1.0,
    )
    assert narrator.get_tts_params("fearful")["speed"] == 1.0
    assert narrator.get_tts_params("sad")["speed"] == 1.0

    role = VoiceProfile(
        voice_id="role_voice",
        character_name="张三",
        gender="male",
        age_group="adult",
        personality="calm",
        tts_speaker_id="stepaudio_role",
        speed_base=1.0,
    )
    assert role.get_tts_params("fearful")["speed"] == pytest.approx(1.15)
    assert role.get_tts_params("sad")["speed"] == pytest.approx(0.85)


def test_minimax_voice_catalog_accepts_registry_model_id_alias() -> None:
    catalog = load_voice_catalog_for_model("MiniMax/speech-2.8-hd")
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == MINIMAX_SPEECH_28_HD_MODEL
    assert "male-qn-qingse" in voice_ids
    assert "Cherry" not in voice_ids


def test_stepaudio_voice_catalog_contains_official_contextual_tts_voices() -> None:
    catalog = load_voice_catalog_for_model(STEPAUDIO_25_TTS_MODEL)
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == STEPAUDIO_25_TTS_MODEL
    assert catalog["meta"]["voice_count"] == 36
    assert {
        "vibrant-youth",
        "lively-girl",
        "soft-spoken-gentleman",
        "magnetic-voiced-male",
        "cixingnansheng",
        "wenrounvsheng",
        "shuangkuainansheng",
        "huolinvsheng",
    }.issubset(voice_ids)


def test_seed_tts_voice_catalog_contains_doubao_20_expressive_voices() -> None:
    catalog = load_voice_catalog_for_model(SEED_TTS_20_EXPRESSIVE_MODEL)
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == SEED_TTS_20_EXPRESSIVE_MODEL
    assert catalog["meta"]["voice_count"] == len(catalog["voices"])
    assert catalog["meta"]["voice_count"] >= 99
    assert {
        "zh_female_vv_uranus_bigtts",
        "saturn_zh_female_keainvsheng_tob",
        "saturn_zh_female_tiaopigongzhu_tob",
        "saturn_zh_male_shuanglangshaonian_tob",
        "saturn_zh_male_tiancaitongzhuo_tob",
        "en_male_tim_uranus_bigtts",
        "zh_male_xuanyijieshuo_uranus_bigtts",
    }.issubset(voice_ids)
    tag_ready = {
        voice["id"]
        for voice in catalog["voices"]
        if voice.get("supports_inline_voice_labels")
    }
    assert {
        "saturn_zh_female_keainvsheng_tob",
        "saturn_zh_female_tiaopigongzhu_tob",
        "saturn_zh_male_shuanglangshaonian_tob",
        "saturn_zh_male_tiancaitongzhuo_tob",
    }.issubset(tag_ready)


def test_voice_manager_factory_keeps_minimax_manager_after_registry_alias() -> None:
    manager = create_voice_manager("MiniMax/speech-2.8-hd")

    assert isinstance(manager, MiniMaxVoiceManager)
    narrator_params = manager.get_narrator_voice().get_tts_params("calm")
    assigned_params = manager.assign_voice("Alice", {"gender": "female"}).get_tts_params("happy")

    assert narrator_params["speaker"] == "male-qn-qingse"
    assert assigned_params["speaker"].startswith("female-")
    assert get_model_for_voice("male-qn-qingse") == MINIMAX_SPEECH_28_HD_MODEL


def test_minimax_project_mapping_applies_voice_type_params() -> None:
    manager = MiniMaxVoiceManager()

    manager.apply_project_voice_mapping({
        "Hero": {
            "voice_id": "male-qn-qingse",
            "volume": 50,
            "speed": 1.0,
            "pitch": 50,
            "voice_type": "lively",
        },
    })

    profile = manager.get_voice("Hero")
    assert profile.tts_speaker_id == "male-qn-qingse"
    assert profile.speed_base == pytest.approx(1.15)
    assert profile.pitch_base == 52
    assert profile.volume_base == 50
    assert profile.default_emotion == "happy"


def test_mimo_voice_clone_mapping_preserves_audio_voice_data_url() -> None:
    manager = MiMoVoiceManager(MIMO_V25_TTS_VOICE_CLONE_MODEL)

    manager.apply_project_voice_mapping({
        "CloneHero": {
            "voice_id": "",
            "tts_model": MIMO_V25_TTS_VOICE_CLONE_MODEL,
            "voice_clone_data_url": "data:audio/wav;base64,AAAA",
            "volume": 64,
        },
    })

    profile = manager.get_voice("CloneHero")
    params = profile.get_tts_params("calm")

    assert profile.tts_model == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert params["speaker"] == ""
    assert params["voice_clone_data_url"] == "data:audio/wav;base64,AAAA"
    assert params["volume"] == 64


def test_mimo_voice_design_mapping_preserves_design_prompt() -> None:
    manager = MiMoVoiceManager(MIMO_V25_TTS_VOICE_DESIGN_MODEL)

    manager.apply_project_voice_mapping({
        "DesignHero": {
            "voice_id": "",
            "tts_model": MIMO_V25_TTS_VOICE_DESIGN_MODEL,
            "voice_design_prompt": "青年女性，中音，语速中等，清亮但克制，适合有声书对白",
            "speed": 1.05,
        },
    })

    profile = manager.get_voice("DesignHero")
    params = profile.get_tts_params("calm")

    assert profile.tts_model == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert params["speaker"] == ""
    assert params["voice_design_prompt"] == "青年女性，中音，语速中等，清亮但克制，适合有声书对白"
    assert params["speed"] == pytest.approx(1.05)


def test_qwen_voice_manager_prefers_unused_voice_for_same_traits() -> None:
    manager = VoiceManager()

    first = manager.assign_voice("秦川", {"gender": "male", "age_group": "young", "personality": "calm"})
    second = manager.assign_voice("周明", {"gender": "male", "age_group": "young", "personality": "calm"})

    assert first.voice_id != second.voice_id
    assert first.gender == "male"
    assert second.gender == "male"


def test_minimax_voice_manager_prefers_unused_voice_for_same_traits() -> None:
    manager = MiniMaxVoiceManager()

    first = manager.assign_voice("林夏", {"gender": "female", "age_group": "young"})
    second = manager.assign_voice("许晴", {"gender": "female", "age_group": "young"})

    assert first.voice_id != second.voice_id
    assert first.gender == "female"
    assert second.gender == "female"


def test_minimax_voice_manager_keeps_requested_turbo_model() -> None:
    manager = create_voice_manager(MINIMAX_SPEECH_28_TURBO_MODEL)

    profile = manager.assign_voice("林夏", {"gender": "female", "age_group": "young"})

    assert isinstance(manager, MiniMaxVoiceManager)
    assert manager.model == MINIMAX_SPEECH_28_TURBO_MODEL
    assert profile.tts_model == MINIMAX_SPEECH_28_TURBO_MODEL


def test_minimax_voice_manager_keeps_created_custom_voice_id() -> None:
    manager = MiniMaxVoiceManager(model=MINIMAX_SPEECH_28_HD_MODEL)

    manager.apply_project_voice_mapping({
        "主角": {
            "voice_id": "mmx_0123456789abcdef",
            "tts_model": MINIMAX_SPEECH_28_HD_MODEL,
        }
    })

    profile = manager.get_voice("主角")
    assert profile is not None
    assert profile.voice_id == "mmx_0123456789abcdef"
    assert profile.tts_speaker_id == "mmx_0123456789abcdef"
    assert profile.get_tts_params("calm")["speaker"] == "mmx_0123456789abcdef"


def test_voice_manager_factory_routes_mimo_inline_custom_voice_models() -> None:
    clone_manager = create_voice_manager(MIMO_V25_TTS_VOICE_CLONE_MODEL)
    design_manager = create_voice_manager(MIMO_V25_TTS_VOICE_DESIGN_MODEL)

    assert isinstance(clone_manager, MiMoVoiceManager)
    assert clone_manager.model == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert isinstance(design_manager, MiMoVoiceManager)
    assert design_manager.model == MIMO_V25_TTS_VOICE_DESIGN_MODEL


def test_voice_manager_factory_routes_stepaudio_contextual_tts_model() -> None:
    manager = create_voice_manager("stepfun/stepaudio-2.5-tts")

    assert isinstance(manager, StepAudioVoiceManager)
    assert manager.model == STEPAUDIO_25_TTS_MODEL
    assert manager.get_narrator_voice().tts_speaker_id == "cixingnansheng"
    assert manager.get_model_info()["supports_inline_context"] is True


def test_voice_manager_factory_routes_seed_tts_expressive_model() -> None:
    manager = create_voice_manager("doubao/seed-tts-2.0-expressive")

    assert manager.model == SEED_TTS_20_EXPRESSIVE_MODEL
    assert manager.get_narrator_voice().tts_speaker_id == "zh_female_vv_uranus_bigtts"
    assert manager.get_model_info()["supports_query_response"] is True


def test_seed_tts_voice_manager_preserves_explicit_clone_speaker_id() -> None:
    manager = create_voice_manager(SEED_TTS_20_EXPRESSIVE_MODEL)
    clone_speaker_id = "S_account_voice_clone_001"

    manager.apply_project_voice_mapping({
        "女主": {
            "voice_id": clone_speaker_id,
            "tts_model": SEED_TTS_20_EXPRESSIVE_MODEL,
            "gender": "female",
        },
    })

    profile = manager.get_voice("女主")
    assert profile is not None
    assert profile.voice_id == clone_speaker_id
    assert profile.tts_speaker_id == clone_speaker_id
    assert profile.get_tts_params("calm")["speaker"] == clone_speaker_id


def test_auto_voice_assignment_pool_falls_back_to_other_model_when_primary_is_exhausted() -> None:
    qwen_voice_ids = [
        voice["id"]
        for voice in load_voice_catalog_for_model(DEFAULT_AUDIOBOOK_TTS_MODEL)["voices"]
    ]
    pool = AutoVoiceAssignmentPool(
        preferred_model=DEFAULT_AUDIOBOOK_TTS_MODEL,
        existing_assignments=[
            {"voice_id": voice_id, "tts_model": DEFAULT_AUDIOBOOK_TTS_MODEL}
            for voice_id in qwen_voice_ids
        ],
    )

    assignment = pool.assign("新角色", {"gender": "male", "age_group": "young", "personality": "calm"})

    assert assignment.model != DEFAULT_AUDIOBOOK_TTS_MODEL
    assert assignment.profile.tts_model == assignment.model
    assert assignment.profile.voice_id not in qwen_voice_ids


def test_qwen_voice_manager_loads_cross_model_project_mapping() -> None:
    manager = VoiceManager()

    manager.apply_project_voice_mapping({
        "跨模型角色": {
            "voice_id": "male-qn-qingse",
            "tts_model": MINIMAX_SPEECH_28_HD_MODEL,
            "volume": 58,
        },
    })

    profile = manager.get_voice("跨模型角色")
    assert profile is not None
    assert profile.voice_id == "male-qn-qingse"
    assert profile.tts_speaker_id == "male-qn-qingse"
    assert profile.tts_model == MINIMAX_SPEECH_28_HD_MODEL
    assert profile.volume_base == 58


def test_tts_preview_applies_voice_type_params() -> None:
    request = TTSPreviewRequest(
        text="试听文本",
        voice_id="Neil",
        volume=50,
        speed=1.0,
        pitch=50,
        voice_type="powerful",
    )

    params = routes_tts._build_preview_voice_params(request, "Neil")

    assert params["speaker"] == "Neil"
    assert params["rate"] == pytest.approx(1.0)
    assert params["speed"] == pytest.approx(1.0)
    assert params["pitch"] == 48
    assert params["volume"] == 60
    assert params["emotion"] == "angry"


def test_tts_preview_expands_asset_reference_from_voice_id(monkeypatch) -> None:
    captured = {}

    def fake_merge(config, **_kwargs):
        captured.update(config)
        return {**config, "voice_clone_data_url": "data:audio/wav;base64,AAAA"}

    monkeypatch.setattr(routes_tts, "merge_mimo_voice_asset_tts_params", fake_merge)
    request = TTSPreviewRequest(
        text="试听文本",
        voice_id="mimo_clone:unit",
        model="mimo-v2.5-tts-voiceclone",
    )

    params = routes_tts._build_preview_voice_params(request, "mimo_clone:unit")

    assert captured["mimo_voice_asset_id"] == "mimo_clone:unit"
    assert captured["voice_id"] == "mimo_clone:unit"
    assert params["voice_clone_data_url"] == "data:audio/wav;base64,AAAA"


def test_cosyvoice_voice_manager_logs_clone_catalog_failure(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        cosyvoice_v3_plus,
        "list_supported_voices",
        lambda _model: [
            {
                "id": "unit-voice",
                "speaker": "unit-voice",
                "category": "narrator",
                "default_params": {"volume": 50, "speed": 1.0, "pitch": 50},
            }
        ],
    )

    def fail_clone_list(**_kwargs):
        raise cosyvoice_v3_plus.CosyVoiceCloneError("missing api key")

    monkeypatch.setattr(cosyvoice_v3_plus, "list_cosyvoice_v3_plus_clones", fail_clone_list)

    with caplog.at_level("INFO", logger="app.services.audiobook.voice_manager_cosyvoice_v3_plus"):
        manager = cosyvoice_v3_plus.CosyVoiceV3PlusVoiceManager()

    assert manager.get_narrator_voice().tts_speaker_id == "unit-voice"
    assert "CosyVoice 自定义音色列表不可用" in caplog.text
    assert "missing api key" in caplog.text


def test_cosyvoice_voice_manager_logs_invalid_numeric_overrides(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        cosyvoice_v3_plus,
        "list_supported_voices",
        lambda _model: [
            {
                "id": "unit-voice",
                "speaker": "unit-voice",
                "category": "narrator",
                "default_params": {"volume": 50, "speed": 1.0, "pitch": 50},
            }
        ],
    )
    monkeypatch.setattr(cosyvoice_v3_plus, "list_cosyvoice_v3_plus_clones", lambda **_kwargs: ([], {}))

    manager = cosyvoice_v3_plus.CosyVoiceV3PlusVoiceManager()

    with caplog.at_level("DEBUG", logger="app.services.audiobook.voice_manager_cosyvoice_v3_plus"):
        manager.apply_project_voice_mapping(
            {
                "Hero": {
                    "voice_id": "unit-voice",
                    "volume": "loud",
                    "speed": "fast",
                    "pitch": "high",
                }
            }
        )

    profile = manager.get_voice("Hero")
    assert profile.volume_base == 50
    assert profile.speed_base == pytest.approx(1.0)
    assert profile.pitch_base == 50
    assert "忽略无效 CosyVoice 音色参数" in caplog.text
    assert "field=volume" in caplog.text
    assert "field=speed" in caplog.text
    assert "field=pitch" in caplog.text


def test_supported_tts_models_do_not_advertise_unregistered_qwen_plus() -> None:
    supported = list_supported_models()

    assert "qwen3-tts-plus" not in supported
    assert supported == [
        DEFAULT_AUDIOBOOK_TTS_MODEL,
        "cosyvoice-v3.5-plus",
        MINIMAX_SPEECH_28_HD_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
        MIMO_V25_TTS_MODEL,
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
        STEPAUDIO_25_TTS_MODEL,
        SEED_TTS_20_EXPRESSIVE_MODEL,
    ]


def test_narration_style_supported_models_are_registered() -> None:
    for style in get_all_narration_styles():
        assert set(style["supported_models"]).issubset(SUPPORTED_AUDIOBOOK_TTS_MODELS)


def test_tts_engine_normalizes_legacy_model_on_init() -> None:
    engine = TTSEngine(model="qwen3-tts-plus")

    assert engine.model == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert engine._is_qwen_instruct_model() is True


def test_mimo_models_are_registered_for_audiobook_runtime_selection() -> None:
    runtime = get_media_runtime()

    for model_id in (
        MIMO_V25_TTS_MODEL,
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
        STEPAUDIO_25_TTS_MODEL,
        SEED_TTS_20_EXPRESSIVE_MODEL,
    ):
        spec = runtime.select_model(
            operation="synthesize_speech",
            modality="text_to_speech",
            preferred_model=model_id,
        )
        engine = create_tts_engine(model_id=model_id)

        assert spec.id == model_id
        assert engine.model == model_id


def test_mimo_custom_voice_models_return_empty_voice_catalogs() -> None:
    for model_id in (
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
    ):
        catalog = asyncio.run(list_tts_voices(model=model_id, current_user=object()))

        assert catalog["model"] == model_id
        assert catalog["voice_count"] == 0
        assert catalog["voices"] == []


def test_cosyvoice_clone_endpoint_uses_shared_prefix_builder(monkeypatch) -> None:
    captured: dict[str, object] = {}
    current_user = SimpleNamespace(id=7)

    def fake_build_prefix(display_name, user):
        captured["builder_args"] = (display_name, user.id)
        return "sharedpfx"

    def fake_create_clone(*, prefix, audio_url):
        captured["clone_args"] = (prefix, audio_url)
        return {"voice_id": "voice-1"}

    monkeypatch.setattr(routes_tts, "_build_cosyvoice_voice_prefix", fake_build_prefix)
    monkeypatch.setattr(routes_tts, "create_cosyvoice_v3_plus_clone", fake_create_clone)
    monkeypatch.setattr(routes_tts, "save_clone_display_name", lambda **_: None)

    result = asyncio.run(
        routes_tts.create_cosyvoice_v3_plus_voice_clone(
            request=CosyVoiceCloneCreateRequest(name=" 星河旁白 ", url="oss://voices/sample.wav"),
            current_user=current_user,
        )
    )

    assert captured["builder_args"] == ("星河旁白", 7)
    assert captured["clone_args"] == ("sharedpfx", "oss://voices/sample.wav")
    assert result["voice_id"] == "voice-1"
    assert result["display_name"] == "星河旁白"


def test_cosyvoice_prefix_builder_uses_sha256_digest(monkeypatch) -> None:
    monkeypatch.setattr("secrets.token_hex", lambda _size: "ff")

    prefix = routes_tts._build_cosyvoice_voice_prefix("星河旁白", SimpleNamespace(id=7))
    expected_digest = hashlib.sha256("7:星河旁白".encode("utf-8")).hexdigest()[:6]

    assert prefix == f"v{expected_digest}ff"


def test_tts_models_endpoint_uses_catalog_counts_and_supported_models(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert "qwen3-tts-plus" not in models
    assert MINIMAX_SPEECH_28_HD_MODEL in models
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["price_per_10k"] == get_audiobook_tts_model_price_per_10k(
        MINIMAX_SPEECH_28_HD_MODEL
    )
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_status"] == "ready"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_model_id"] == "MiniMax/speech-2.8-hd"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_error"] is None
    assert models["cosyvoice-v3.5-plus"]["capabilities"]["requires_custom_voice"] is True
    assert models["cosyvoice-v3.5-plus"]["capabilities"]["supports_voice_clone"] is True
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["capabilities"]["has_system_voices"] is True
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_status"] == "ready"
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_error"] is None
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_note"]
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["voice_count"] == load_voice_catalog_for_model(
        DEFAULT_AUDIOBOOK_TTS_MODEL
    )["meta"]["voice_count"]
    assert models[MIMO_V25_TTS_MODEL]["runtime_status"] == "ready"
    assert models[MIMO_V25_TTS_MODEL]["runtime_model_id"] == MIMO_V25_TTS_MODEL
    assert models[MIMO_V25_TTS_MODEL]["runtime_error"] is None
    assert models[MIMO_V25_TTS_MODEL]["catalog_status"] == "ready"
    assert models[MIMO_V25_TTS_MODEL]["voice_count"] == load_voice_catalog_for_model(
        MIMO_V25_TTS_MODEL
    )["meta"]["voice_count"]
    assert models[MIMO_V25_TTS_VOICE_DESIGN_MODEL]["runtime_status"] == "ready"
    assert models[MIMO_V25_TTS_VOICE_DESIGN_MODEL]["runtime_model_id"] == MIMO_V25_TTS_VOICE_DESIGN_MODEL
    assert models[MIMO_V25_TTS_VOICE_DESIGN_MODEL]["runtime_error"] is None
    assert models[MIMO_V25_TTS_VOICE_DESIGN_MODEL]["catalog_status"] == "not_applicable"
    assert models[MIMO_V25_TTS_VOICE_DESIGN_MODEL]["voice_count"] == 0
    assert models[MIMO_V25_TTS_VOICE_CLONE_MODEL]["runtime_status"] == "ready"
    assert models[MIMO_V25_TTS_VOICE_CLONE_MODEL]["runtime_model_id"] == MIMO_V25_TTS_VOICE_CLONE_MODEL
    assert models[MIMO_V25_TTS_VOICE_CLONE_MODEL]["runtime_error"] is None
    assert models[MIMO_V25_TTS_VOICE_CLONE_MODEL]["catalog_status"] == "not_applicable"
    assert models[MIMO_V25_TTS_VOICE_CLONE_MODEL]["voice_count"] == 0
    assert models[STEPAUDIO_25_TTS_MODEL]["runtime_status"] == "ready"
    assert models[STEPAUDIO_25_TTS_MODEL]["runtime_model_id"] == STEPAUDIO_25_TTS_MODEL
    assert models[STEPAUDIO_25_TTS_MODEL]["runtime_error"] is None
    assert models[STEPAUDIO_25_TTS_MODEL]["catalog_status"] == "ready"
    assert models[STEPAUDIO_25_TTS_MODEL]["voice_count"] == load_voice_catalog_for_model(
        STEPAUDIO_25_TTS_MODEL
    )["meta"]["voice_count"]
    assert models[STEPAUDIO_25_TTS_MODEL]["price_per_10k"] == 5.8
    assert "全局语境" in models[STEPAUDIO_25_TTS_MODEL]["features"]
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["runtime_status"] == "ready"
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["runtime_model_id"] == SEED_TTS_20_EXPRESSIVE_MODEL
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["catalog_status"] == "ready"
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["voice_count"] == load_voice_catalog_for_model(
        SEED_TTS_20_EXPRESSIVE_MODEL
    )["meta"]["voice_count"]
    assert "对话式TTS" in models[SEED_TTS_20_EXPRESSIVE_MODEL]["features"]
    assert f"{models[DEFAULT_AUDIOBOOK_TTS_MODEL]['voice_count']} 个可用音色" in models[
        DEFAULT_AUDIOBOOK_TTS_MODEL
    ]["description"]
    assert f"{models[MINIMAX_SPEECH_28_HD_MODEL]['voice_count']} 音色" in models[
        MINIMAX_SPEECH_28_HD_MODEL
    ]["features"]


def test_tts_models_endpoint_keeps_model_when_voice_catalog_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))
    original_loader = routes_tts.load_voice_catalog_for_model

    def fail_minimax_catalog(model: str):
        if model == MINIMAX_SPEECH_28_TURBO_MODEL:
            raise RuntimeError("broken catalog")
        return original_loader(model)

    monkeypatch.setattr(routes_tts, "load_voice_catalog_for_model", fail_minimax_catalog)

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert MINIMAX_SPEECH_28_TURBO_MODEL in models
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["catalog_status"] == "unavailable"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["catalog_error"] == "音色目录加载失败，请检查后端 voice catalog 配置"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["voice_count"] == 0
    assert models[DEFAULT_AUDIOBOOK_TTS_MODEL]["catalog_status"] == "ready"


def test_tts_models_endpoint_exposes_runtime_registration_status(monkeypatch) -> None:
    monkeypatch.setattr(routes_tts, "list_cosyvoice_v3_plus_clones", lambda **_: ([], {}))
    original_runtime = routes_tts.get_media_runtime()

    class RuntimeProxy:
        def select_model(self, **kwargs):
            if kwargs.get("preferred_model") == "MiniMax/speech-2.8-turbo":
                raise ValueError("runtime missing")
            return original_runtime.select_model(**kwargs)

    monkeypatch.setattr(routes_tts, "get_media_runtime", lambda: RuntimeProxy())

    payload = asyncio.run(list_tts_models(current_user=object()))
    models = {model["id"]: model for model in payload["models"]}

    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_model_id"] == "MiniMax/speech-2.8-turbo"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_status"] == "unavailable"
    assert models[MINIMAX_SPEECH_28_TURBO_MODEL]["runtime_error"] == "TTS 运行时模型未注册或不可用"
    assert models[MINIMAX_SPEECH_28_HD_MODEL]["runtime_status"] == "ready"
