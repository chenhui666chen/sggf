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
    QWEN_AUDIO_31_TTS_FLASH_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_3_TTS_MODEL,
    SUPPORTED_AUDIOBOOK_TTS_MODELS,
    get_audiobook_tts_model_metadata,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_style_capabilities,
    get_audiobook_tts_model_price_per_10k,
    is_supported_audiobook_tts_model,
    list_supported_audiobook_tts_models,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.narration_styles import get_all_narration_styles
from app.services.audiobook.tts_engine_pkg import TTSEngine
from app.services.audiobook.tts_style_control import normalize_emotion_for_model
from app.services.audiobook.voice_catalog import _filename_for_model, get_voice_entry, load_voice_catalog_for_model
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

# 退役线名不再由产品代码持有，只作为“旧写法必须折叠到 3.1 且不得出现在任何注册表”
# 这一反向断言的事实出现在测试里。
RETIRED_QWEN3_SPELLING = "qwen3-tts-instruct-flash"


@pytest.mark.parametrize(
    ("model_id", "expected_price", "expected_status", "expected_basis"),
    [
        # 默认模型 Qwen-Audio 3.1 按 token 计费，万字价是折算口径，必须与公开刊例价区分标注。
        (DEFAULT_AUDIOBOOK_TTS_MODEL, 0.4, "public_postpaid", "derived_from_token_price"),
        ("cosyvoice-v3.5-plus", 1.5, "public_postpaid", "public_list_price"),
        (MINIMAX_SPEECH_28_TURBO_MODEL, 2.0, "public_postpaid", "public_list_price"),
        (MINIMAX_SPEECH_28_HD_MODEL, 3.5, "public_postpaid", "public_list_price"),
        (MIMO_V25_TTS_MODEL, 0.0, "limited_time_free", "public_list_price"),
        (MIMO_V25_TTS_VOICE_DESIGN_MODEL, 0.0, "limited_time_free", "public_list_price"),
        (MIMO_V25_TTS_VOICE_CLONE_MODEL, 0.0, "limited_time_free", "public_list_price"),
        (STEPAUDIO_3_TTS_MODEL, 2.5, "public_postpaid", "public_list_price"),
        (SEED_TTS_20_EXPRESSIVE_MODEL, 3.0, "public_postpaid", "public_list_price"),
    ],
)
def test_audiobook_tts_catalog_uses_public_postpaid_user_prices(
    model_id: str,
    expected_price: float,
    expected_status: str,
    expected_basis: str,
) -> None:
    metadata = get_audiobook_tts_model_metadata(model_id)

    assert get_audiobook_tts_model_price_per_10k(model_id) == expected_price
    assert metadata["pricing_status"] == expected_status
    assert metadata["pricing_basis"] == expected_basis


def test_audiobook_tts_catalog_records_fixed_custom_voice_fees() -> None:
    minimax = get_audiobook_tts_model_metadata(MINIMAX_SPEECH_28_TURBO_MODEL)
    stepaudio = get_audiobook_tts_model_metadata(STEPAUDIO_3_TTS_MODEL)
    seed_tts = get_audiobook_tts_model_metadata(SEED_TTS_20_EXPRESSIVE_MODEL)

    assert minimax["custom_voice_pricing"]["first_formal_use_yuan"] == 9.9
    assert stepaudio["custom_voice_pricing"]["formal_clone_success_yuan"] == 9.9
    assert seed_tts["custom_voice_pricing"] == {
        "postpaid_slot_first_formal_use_yuan": 138.0,
        "preview_price_per_10k": 3.0,
        "unused_preview_retention_days": 7,
    }


def test_seed_tts_voice_clone_is_declared_unsupported_across_sources() -> None:
    """复刻链路未实现，任何一处重新声明为支持都会让档案与代码再次分叉。"""
    assert (
        get_audiobook_tts_style_capabilities(SEED_TTS_20_EXPRESSIVE_MODEL)[
            "supports_voice_clone"
        ]
        is False
    )
    assert (
        get_audiobook_tts_model_metadata(SEED_TTS_20_EXPRESSIVE_MODEL)["capabilities"][
            "supports_voice_clone"
        ]
        is False
    )
    assert (
        create_voice_manager(SEED_TTS_20_EXPRESSIVE_MODEL).get_model_info()["supports_voice_clone"]
        is False
    )


def test_stepaudio_streaming_is_declared_unsupported_across_sources() -> None:
    """上游流式未取证、合成链路只发非流式 /audio/speech，两处声明必须同步为不支持。"""
    assert (
        get_audiobook_tts_style_capabilities(STEPAUDIO_3_TTS_MODEL)["supports_streaming"] is False
    )
    assert (
        get_audiobook_tts_model_metadata(STEPAUDIO_3_TTS_MODEL)["capabilities"]["supports_streaming"]
        is False
    )


def _stepaudio_archive_card() -> dict:
    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    data = yaml.safe_load((repo_root / "config" / "models.yaml").read_text(encoding="utf-8"))
    for card in data["models"]:
        if card.get("id") == STEPAUDIO_3_TTS_MODEL:
            return card
    raise AssertionError(f"config/models.yaml 缺少模型 {STEPAUDIO_3_TTS_MODEL}")


def _stepaudio_frontend_instruction_budget() -> int:
    """从前端兜底表里抠出 stepaudio 的 instructionBudget 字面量。"""
    import re

    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root / "frontend" / "src" / "pages" / "audiobook" / "ttsModels.ts"
    ).read_text(encoding="utf-8")
    block_start = source.index(f"'{STEPAUDIO_3_TTS_MODEL}': {{")
    block = source[block_start + len(f"'{STEPAUDIO_3_TTS_MODEL}': {{") :]
    next_model = re.search(r"\n  '[^']+': \{", block)
    if next_model:
        block = block[: next_model.start()]
    match = re.search(r"instructionBudget: (\d+|null)", block)
    assert match is not None, "前端兜底表缺少 stepaudio 的 instructionBudget"
    return int(match.group(1))


def test_stepaudio_budget_and_transport_declarations_agree_across_all_fact_sources() -> None:
    """instruction/输入额度与流式声明共 5 处事实源：档案卡（constraints + contextual_control）、
    能力矩阵、引擎硬截断、前端兜底表、场景引擎喂 LLM 的表演提示词。只改其中一层就会出现
    「代码放宽了、档案还写旧值」或反过来的静默漂移，这里一次钉死跨源一致。"""
    from app.services.audiobook.tts_engine_pkg._aliyun_mixin import (
        STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS,
        STEPAUDIO_TTS_MAX_INPUT_CHARS,
    )

    card = _stepaudio_archive_card()
    style_capabilities = get_audiobook_tts_style_capabilities(STEPAUDIO_3_TTS_MODEL)

    assert STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS == 500
    assert card["constraints"]["instruction_max_chars"] == STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS
    assert (
        card["detailed_specs"]["voice_synthesis"]["contextual_control"]["global_context"]["max_chars"]
        == STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS
    )
    assert style_capabilities["instruction_budget"] == STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS
    assert _stepaudio_frontend_instruction_budget() == STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS

    assert card["constraints"]["max_input_chars"] == STEPAUDIO_TTS_MAX_INPUT_CHARS

    assert style_capabilities["supports_streaming"] is False
    assert any(
        "supports_streaming 已按未支持声明" in limitation for limitation in card["limitations"]
    )

    # 第 5 处：场景引擎提示词是散文不是配置字段，按常量名 grep 抓不到，必须单独钉。
    repo_root = Path(__file__).resolve().parents[2]
    scene_prompt = (
        repo_root
        / "backend"
        / "app"
        / "services"
        / "audiobook"
        / "script_adapter_pkg"
        / "_transform.py"
    ).read_text(encoding="utf-8")
    assert f"全局语境 instruction 上限 {STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS} 字符" in scene_prompt
    assert "上限 200 字符" not in scene_prompt


@pytest.mark.parametrize(
    ("model_id", "expected_price"),
    [
        (DEFAULT_AUDIOBOOK_TTS_MODEL, 0.4),
        ("cosyvoice-v3.5-plus", 1.5),
        (MINIMAX_SPEECH_28_TURBO_MODEL, 2.0),
        (MINIMAX_SPEECH_28_HD_MODEL, 3.5),
        (MIMO_V25_TTS_MODEL, 0.0),
        (MIMO_V25_TTS_VOICE_DESIGN_MODEL, 0.0),
        (MIMO_V25_TTS_VOICE_CLONE_MODEL, 0.0),
        (STEPAUDIO_3_TTS_MODEL, 2.5),
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
    assert normalize_audiobook_tts_model("StepAudio-3-TTS") == STEPAUDIO_3_TTS_MODEL
    assert normalize_audiobook_tts_model("stepaudio_3_tts") == STEPAUDIO_3_TTS_MODEL
    assert normalize_audiobook_tts_model("stepfun/stepaudio-3-tts") == STEPAUDIO_3_TTS_MODEL
    assert normalize_audiobook_tts_model("seed-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("doubao/seed-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("doubao-tts-2.0-expressive") == SEED_TTS_20_EXPRESSIVE_MODEL
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-hd", default="") == ""
    assert normalize_audiobook_tts_model("mimo-v2.5-tts-turbo", default="") == ""
    assert is_supported_audiobook_tts_model("MiniMax/speech-2.8-hd") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-voicedesign") is True
    assert is_supported_audiobook_tts_model("mimo-v2.5-tts-voiceclone") is True
    assert is_supported_audiobook_tts_model("stepaudio-3-tts") is True
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
    assert get_audiobook_tts_runtime_model_id(STEPAUDIO_3_TTS_MODEL) == STEPAUDIO_3_TTS_MODEL
    assert get_audiobook_tts_runtime_model_id(SEED_TTS_20_EXPRESSIVE_MODEL) == SEED_TTS_20_EXPRESSIVE_MODEL


def test_audiobook_tts_model_style_capabilities_are_exposed() -> None:
    qwen_caps = get_audiobook_tts_style_capabilities(DEFAULT_AUDIOBOOK_TTS_MODEL)
    assert qwen_caps["model_family"] == "qwen"
    assert qwen_caps["preferred_style_control_mode"] == "natural_language"
    assert qwen_caps["style_control_modes"] == ["natural_language"]
    assert qwen_caps["supports_voice_description"] is True
    assert qwen_caps["supports_audio_tags"] is False
    assert qwen_caps["instruction_budget"] == 1200
    # 默认模型（Qwen-Audio 3.1）没有服务端情绪枚举：情绪只进自然语言指令，不做枚举降级。
    assert not qwen_caps["supported_emotions"]

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

    stepaudio_caps = get_audiobook_tts_style_capabilities(STEPAUDIO_3_TTS_MODEL)
    assert stepaudio_caps["model_family"] == "stepaudio"
    assert stepaudio_caps["preferred_style_control_mode"] == "global_context"
    assert stepaudio_caps["style_control_modes"] == ["global_context", "inline_context", "natural_language"]
    assert stepaudio_caps["supports_voice_description"] is True
    assert stepaudio_caps["supports_audio_tags"] is False
    assert stepaudio_caps["supports_emotion_mixing"] is True
    assert stepaudio_caps["supports_micro_tags"] is True
    assert stepaudio_caps["supports_word_level_control"] is True
    assert stepaudio_caps["supports_voice_clone"] is True
    assert stepaudio_caps["supports_streaming"] is False
    assert stepaudio_caps["instruction_budget"] == 500
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
    assert seed_caps["supports_voice_clone"] is False
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


def test_mimo_preset_card_does_not_advertise_unconsumable_streaming() -> None:
    """supports_streaming 记录的是上游协议能力；面向用户的文案只能写我方真能交付的能力。"""
    metadata = get_audiobook_tts_model_metadata(MIMO_V25_TTS_MODEL)

    assert metadata["capabilities"]["supports_streaming"] is True
    assert "低延迟流式" not in metadata["features"]
    assert "流式" not in metadata["catalog_note"]


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
    engine = TTSEngine(model="stepaudio-3-tts")

    assert engine._normalize_emotion("fearful") == "fearful"
    assert engine._normalize_emotion("disgusted") == "disgusted"

    qwen_engine = TTSEngine(model="qwen-audio-3.1-tts-flash")
    # 3.1 能力矩阵不声明情绪枚举：fearful/tense 一律原样进入自然语言指令，不做枚举降级。
    assert qwen_engine._normalize_emotion("fearful") == "fearful"
    assert qwen_engine._normalize_emotion("tense") == "tense"


def test_narrator_speed_is_stable_across_emotions() -> None:
    """旁白语速不应随逐段 emotion 标签机械变速（导致忽快忽慢），
    情绪层次交给风格指令/performance_notes 表达；
    不支持指令的模型上，角色台词仍保留情感变速。"""
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
    assert "speed" not in narrator.get_tts_params("fearful")
    assert "speed" not in narrator.get_tts_params("sad")

    # 不支持指令的模型（basic 模式）：角色台词保留情感数值变速
    role = VoiceProfile(
        voice_id="role_voice",
        character_name="张三",
        gender="male",
        age_group="adult",
        personality="calm",
        tts_model=MINIMAX_SPEECH_28_HD_MODEL,
        tts_speaker_id="minimax_role",
        speed_base=1.0,
    )
    assert role.get_tts_params("fearful")["speed"] == pytest.approx(1.15)
    assert role.get_tts_params("sad")["speed"] == pytest.approx(0.85)

    # 支持指令的模型：角色语速只由表演指令表达，不再发送数值基线。
    instruct_role = VoiceProfile(
        voice_id="role_voice_instruct",
        character_name="张三",
        gender="male",
        age_group="adult",
        personality="calm",
        tts_model="seed-tts-2.0-expressive",
        tts_speaker_id="seed_role",
        speed_base=1.0,
    )
    assert "speed" not in instruct_role.get_tts_params("fearful")


def test_tts_speed_control_capability_separates_semantic_and_basic_models() -> None:
    for model in (
        "qwen-audio-3.1-tts-flash",
        "cosyvoice-v3.5-plus",
        "mimo-v2.5-tts",
        "mimo-v2.5-tts-voicedesign",
        "mimo-v2.5-tts-voiceclone",
        "stepaudio-3-tts",
        "seed-tts-2.0-expressive",
    ):
        assert tts_model_ids.model_supports_instruct_style_control(model) is True
        assert tts_model_ids.model_uses_basic_numeric_speed_control(model) is False

    for model in (MINIMAX_SPEECH_28_HD_MODEL, MINIMAX_SPEECH_28_TURBO_MODEL):
        assert tts_model_ids.model_supports_instruct_style_control(model) is False
        assert tts_model_ids.model_uses_basic_numeric_speed_control(model) is True

    assert tts_model_ids.model_uses_basic_numeric_speed_control("unknown-model") is False


def test_minimax_voice_catalog_accepts_registry_model_id_alias() -> None:
    catalog = load_voice_catalog_for_model("MiniMax/speech-2.8-hd")
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == MINIMAX_SPEECH_28_HD_MODEL
    assert "male-qn-qingse" in voice_ids
    assert "Cherry" not in voice_ids


def test_stepaudio_voice_catalog_contains_official_contextual_tts_voices() -> None:
    catalog = load_voice_catalog_for_model(STEPAUDIO_3_TTS_MODEL)
    voice_ids = {voice["id"] for voice in catalog["voices"]}

    assert catalog["meta"]["model"] == STEPAUDIO_3_TTS_MODEL
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
        "ICL_uranus_zh_female_keainvsheng_tob",
        "ICL_uranus_zh_female_tiaopigongzhu_tob",
        "ICL_uranus_zh_male_shuanglangshaonian_tob",
        "ICL_uranus_zh_male_tiancaitongzhuo_tob",
        "en_male_tim_uranus_bigtts",
        "zh_male_xuanyijieshuo_uranus_bigtts",
    }.issubset(voice_ids)
    tag_ready = {
        voice["id"]
        for voice in catalog["voices"]
        if voice.get("supports_inline_voice_labels")
    }
    assert {
        "ICL_uranus_zh_female_keainvsheng_tob",
        "ICL_uranus_zh_female_tiaopigongzhu_tob",
        "ICL_uranus_zh_male_shuanglangshaonian_tob",
        "ICL_uranus_zh_male_tiancaitongzhuo_tob",
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
    assert profile.pitch_base == 50
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
    assert "speed" not in params


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
    manager = create_voice_manager("stepfun/stepaudio-3-tts")

    assert isinstance(manager, StepAudioVoiceManager)
    assert manager.model == STEPAUDIO_3_TTS_MODEL
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


def test_tts_preview_ignores_voice_type_identity_params_for_fixed_voice() -> None:
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
    assert "rate" not in params
    assert "speed" not in params
    assert "pitch" not in params
    assert params["volume"] == 50
    assert "emotion" not in params


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


def test_fixed_voice_preview_drops_asset_injected_voice_design_fields(monkeypatch) -> None:
    def fake_merge(config, **_kwargs):
        return {
            **config,
            "voice_clone_data_url": "data:audio/wav;base64,AAAA",
            "voice_description": "苍老男性，低沉沙哑",
            "voice_design_prompt": "改成陌生老人的声音",
            "provider_prompt_snapshot": {"provider_prompt": {"instructions": "旧提示"}},
        }

    monkeypatch.setattr(routes_tts, "merge_mimo_voice_asset_tts_params", fake_merge)
    request = TTSPreviewRequest(
        text="试听文本",
        voice_id="mimo_clone:unit",
        model="mimo-v2.5-tts-voiceclone",
    )

    params = routes_tts._build_preview_voice_params(
        request,
        "mimo_clone:unit",
        model_name="mimo-v2.5-tts-voiceclone",
    )

    assert params["voice_clone_data_url"] == "data:audio/wav;base64,AAAA"
    assert "voice_description" not in params
    assert "voice_design_prompt" not in params
    assert "provider_prompt_snapshot" not in params


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
        QWEN_AUDIO_31_TTS_FLASH_MODEL,
        "cosyvoice-v3.5-plus",
        MINIMAX_SPEECH_28_HD_MODEL,
        MINIMAX_SPEECH_28_TURBO_MODEL,
        MIMO_V25_TTS_MODEL,
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
        STEPAUDIO_3_TTS_MODEL,
        SEED_TTS_20_EXPRESSIVE_MODEL,
    ]


def test_qwen_audio_31_flash_is_registered_with_measured_contract() -> None:
    assert normalize_audiobook_tts_model("Qwen-Audio-3.1-TTS-Flash") == QWEN_AUDIO_31_TTS_FLASH_MODEL
    assert normalize_audiobook_tts_model("qwen-audio-3.1-tts") == QWEN_AUDIO_31_TTS_FLASH_MODEL
    # Next 尚未接入有声书，未知后缀写法必须回退默认模型而不是误路由到 3.1。
    assert normalize_audiobook_tts_model("qwen-audio-3.1-tts-next") == DEFAULT_AUDIOBOOK_TTS_MODEL
    assert get_audiobook_tts_runtime_model_id(QWEN_AUDIO_31_TTS_FLASH_MODEL) == QWEN_AUDIO_31_TTS_FLASH_MODEL

    metadata = get_audiobook_tts_model_metadata(QWEN_AUDIO_31_TTS_FLASH_MODEL)
    assert metadata["price_per_10k"] == 0.4
    assert metadata["pricing_basis"] == "derived_from_token_price"
    assert metadata["capabilities"]["has_system_voices"] is True

    capabilities = get_audiobook_tts_style_capabilities(QWEN_AUDIO_31_TTS_FLASH_MODEL)
    assert capabilities["preferred_style_control_mode"] == "natural_language"
    assert capabilities["instruction_budget"] == 1200
    # 未声明 supported_emotions：情感只进入自然语言指令，不做服务端枚举降级。
    assert not capabilities["supported_emotions"]


def test_qwen_audio_31_voice_catalog_is_the_default_voice_source() -> None:
    voices = load_voice_catalog_for_model(QWEN_AUDIO_31_TTS_FLASH_MODEL)["voices"]
    assert len(voices) == 68
    assert all(str(voice["id"]).endswith("_v3.1") for voice in voices)
    assert load_voice_catalog_for_model(DEFAULT_AUDIOBOOK_TTS_MODEL)["voices"] == voices
    # 默认模型必须解析到 3.1 音色目录文件，而不是历史 Qwen3 音色表。
    assert _filename_for_model(DEFAULT_AUDIOBOOK_TTS_MODEL) == "qwen_audio_3_1_tts_voices.json"


def test_retired_qwen3_voice_ids_are_rejected_by_the_default_catalog() -> None:
    # 3.1 与 Qwen3 音色零交集：旧音色名在默认目录查不到，由目录校验显式重置，而不是静默发错音色。
    assert get_voice_entry("Neil", model=DEFAULT_AUDIOBOOK_TTS_MODEL) is None
    assert get_voice_entry("Cherry", model=DEFAULT_AUDIOBOOK_TTS_MODEL) is None


def test_qwen3_tts_is_retired_from_every_registration_table() -> None:
    retired = RETIRED_QWEN3_SPELLING

    assert DEFAULT_AUDIOBOOK_TTS_MODEL == QWEN_AUDIO_31_TTS_FLASH_MODEL
    assert retired not in SUPPORTED_AUDIOBOOK_TTS_MODELS
    assert retired not in tts_model_ids.SUPPORTED_AUDIOBOOK_TTS_MODEL_ORDER
    assert retired not in tts_model_ids.AUDIOBOOK_TTS_RUNTIME_MODEL_IDS
    assert retired not in tts_model_ids.AUDIOBOOK_TTS_STYLE_CAPABILITIES
    assert retired not in tts_model_ids.AUDIOBOOK_TTS_MODEL_CATALOG

    registered = list_supported_audiobook_tts_models()
    assert registered.count(QWEN_AUDIO_31_TTS_FLASH_MODEL) == 1
    assert set(registered) == SUPPORTED_AUDIOBOOK_TTS_MODELS
    assert retired not in registered


def test_retired_qwen3_spellings_fold_to_qwen_audio_31() -> None:
    # 库内与历史配置仍可能写着 Qwen3 写法：归一必须落到 3.1，不允许静默回退成不可用模型。
    for spelling in (
        "qwen3-tts-instruct-flash",
        "qwen3-tts-flash",
        "qwen3-tts-plus",
        "qwen3-tts",
        "qwen3_tts",
        "QWEN3-TTS-Instruct-Flash",
    ):
        assert normalize_audiobook_tts_model(spelling) == QWEN_AUDIO_31_TTS_FLASH_MODEL
        assert is_supported_audiobook_tts_model(spelling) is True

    assert get_audiobook_tts_runtime_model_id(RETIRED_QWEN3_SPELLING) == QWEN_AUDIO_31_TTS_FLASH_MODEL
    # 归一到 3.1 后必须使用 3.1 的万字折算价，不能继续按 Qwen3 的 0.8 元记账。
    assert get_audiobook_tts_model_price_per_10k(RETIRED_QWEN3_SPELLING) == 0.4


def test_default_model_keeps_free_form_emotion_labels() -> None:
    # 3.1 没有服务端情绪枚举：情绪标签必须原样进入自然语言指令，不做枚举降级。
    assert normalize_emotion_for_model("压抑克制", DEFAULT_AUDIOBOOK_TTS_MODEL) == "压抑克制"
    assert normalize_emotion_for_model("tense", DEFAULT_AUDIOBOOK_TTS_MODEL) == "tense"


def test_voice_manager_factory_recognizes_qwen_audio_31_voices() -> None:
    assert get_model_for_voice("longanhuan_v3.1") == QWEN_AUDIO_31_TTS_FLASH_MODEL
    assert QWEN_AUDIO_31_TTS_FLASH_MODEL in list_supported_models()


def test_narration_style_supported_models_are_registered() -> None:
    for style in get_all_narration_styles():
        assert set(style["supported_models"]).issubset(SUPPORTED_AUDIOBOOK_TTS_MODELS)


def test_tts_engine_normalizes_legacy_model_on_init() -> None:
    engine = TTSEngine(model="qwen3-tts-plus")

    assert engine.model == DEFAULT_AUDIOBOOK_TTS_MODEL
    # 退役后旧写法不再落到 Qwen3 合成路径，而是走 3.1 的 SpeechSynthesizer 路径。
    assert engine._is_qwen_audio_31_model() is True
    assert not hasattr(engine, "_is_qwen_instruct_model")


def test_mimo_models_are_registered_for_audiobook_runtime_selection() -> None:
    runtime = get_media_runtime()

    for model_id in (
        MIMO_V25_TTS_MODEL,
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        MIMO_V25_TTS_VOICE_CLONE_MODEL,
        STEPAUDIO_3_TTS_MODEL,
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
    assert models[STEPAUDIO_3_TTS_MODEL]["runtime_status"] == "ready"
    assert models[STEPAUDIO_3_TTS_MODEL]["runtime_model_id"] == STEPAUDIO_3_TTS_MODEL
    assert models[STEPAUDIO_3_TTS_MODEL]["runtime_error"] is None
    assert models[STEPAUDIO_3_TTS_MODEL]["catalog_status"] == "ready"
    assert models[STEPAUDIO_3_TTS_MODEL]["voice_count"] == load_voice_catalog_for_model(
        STEPAUDIO_3_TTS_MODEL
    )["meta"]["voice_count"]
    assert models[STEPAUDIO_3_TTS_MODEL]["price_per_10k"] == 2.5
    assert "全局语境" in models[STEPAUDIO_3_TTS_MODEL]["features"]
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["runtime_status"] == "ready"
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["runtime_model_id"] == SEED_TTS_20_EXPRESSIVE_MODEL
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["catalog_status"] == "ready"
    assert models[SEED_TTS_20_EXPRESSIVE_MODEL]["voice_count"] == load_voice_catalog_for_model(
        SEED_TTS_20_EXPRESSIVE_MODEL
    )["meta"]["voice_count"]
    assert "对话式TTS" in models[SEED_TTS_20_EXPRESSIVE_MODEL]["features"]
    assert f"{models[DEFAULT_AUDIOBOOK_TTS_MODEL]['voice_count']} 个" in models[
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
