import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin
from app.services.audiobook.tts_delivery_plan import build_delivery_plan, preferred_control_mode
from app.services.audiobook.tts_style_control import (
    build_model_style_control,
    prepare_text_for_style_control,
)


def test_tts_batch_item_resolves_segment_model_before_delivery_planning() -> None:
    class DummyEngine(TTSMixin):
        tts_model = "qwen3-tts-instruct-flash"

    segment = SimpleNamespace(
        text="她压低声音说，我真的撑不住了。",
        type="dialogue",
        speaker="岑霜",
        emotion="sad",
        instruct_emotion="sad",
        instruct_scene="雨夜逃亡后短暂停下",
        instruct_role="长期压抑情绪的继承人",
        instruct_identity="女主角",
        performance_notes="压低声音，语速偏慢，句尾带一点哽咽并留白。",
        voice_params={
            "tts_model": "mimo-v2.5-tts",
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_emotion": "sad",
            "instruct_scene": "雨夜逃亡后短暂停下",
            "instruct_role": "长期压抑情绪的继承人",
        },
    )

    item = DummyEngine()._build_tts_batch_item(segment)
    voice_params = item["voice_params"]
    delivery_plan = voice_params.get("delivery_plan")

    assert voice_params.get("resolved_tts_model") == "mimo-v2.5-tts"
    assert isinstance(delivery_plan, dict)
    assert delivery_plan["model"] == "mimo-v2.5-tts"
    assert delivery_plan["model_family"] == "mimo"
    assert delivery_plan["model_control_preference"] == "director"
    assert delivery_plan["delivery_mode"] in {"dialogue", "sob"}
    assert "哽咽" in delivery_plan["micro_tags"]
    assert "语速偏慢" in delivery_plan["director_guidance"]


def test_model_style_control_consumes_delivery_plan_for_natural_language_models() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "长期压抑情绪的继承人",
            "instruct_scene": "雨夜逃亡后短暂停下",
            "performance_notes": "句尾带一点哽咽并留白。",
            "delivery_plan": {
                "delivery_mode": "sob",
                "pace": "slow",
                "pitch": "lower",
                "intensity": "medium",
                "emotion_primary": "sad",
                "emotion_mix": ["压抑", "悲伤"],
                "micro_tags": ["哽咽", "低语"],
                "pause_strategy": "句尾留白",
                "stress_words": ["撑不住"],
                "director_guidance": "压低声音，语速偏慢，在“撑不住”处轻微加重。",
            },
        },
        "sad",
    )

    instructions = control.provider_fields["instructions"]

    assert control.mode == "natural_language"
    assert "朗读方式：sob" in instructions
    assert "情绪层次：压抑、悲伤" in instructions
    assert "微表演标签：哽咽、低语" in instructions
    assert "重读词：撑不住" in instructions
    assert "导演指导：压低声音，语速偏慢，在“撑不住”处轻微加重。" in instructions


def test_delivery_plan_uses_model_style_capabilities_for_control_preference() -> None:
    qwen_plan = build_delivery_plan(
        voice_params={
            "tts_model": "qwen3-tts-instruct-flash",
            "style_control_method": "audio_tags",
            "performance_notes": "低语，句尾留白。",
        },
        emotion="sad",
    )

    assert qwen_plan["model_family"] == "qwen"
    assert qwen_plan["model_control_preference"] == "natural_language"
    assert qwen_plan["model_style_control_modes"] == ["natural_language"]
    assert qwen_plan["supports_audio_tags"] is False

    assert preferred_control_mode("mimo-v2.5-tts", {"style_control_method": "audio_tags"}) == "audio_tags"
    assert preferred_control_mode("minimax-speech-2.8-hd", {"style_control_method": "audio_tags"}) == "basic"


def test_mimo_audio_tags_can_use_delivery_plan_micro_tags() -> None:
    control = build_model_style_control(
        "mimo-v2.5-tts",
        {
            "style_control_method": "audio_tags",
            "delivery_plan": {
                "emotion_primary": "sad",
                "emotion_mix": ["压抑", "悲伤"],
                "micro_tags": ["哽咽", "低语"],
            },
        },
        "sad",
    )

    assert control.mode == "mimo_audio_tags"
    assert control.messages == [{"role": "assistant", "content": "（sad，压抑，悲伤）[哽咽][低语]"}]
    assert prepare_text_for_style_control("我真的撑不住了。", control) == "（sad，压抑，悲伤）[哽咽][低语]我真的撑不住了。"
