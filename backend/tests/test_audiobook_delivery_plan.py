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
    build_provider_prompt_snapshot,
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
            "speaker": "mimo_default",
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
    assert delivery_plan["tts_model"] == "mimo-v2.5-tts"
    assert delivery_plan["voice_id"] == "mimo_default"
    assert delivery_plan["text"] == "她压低声音说，我真的撑不住了。"
    assert delivery_plan["model_family"] == "mimo"
    assert delivery_plan["model_control_preference"] == "director"
    assert delivery_plan["delivery_mode"] in {"dialogue", "sob"}
    assert delivery_plan["emotion"] == "sad"
    assert delivery_plan["pace"] == "slow"
    assert delivery_plan["pause_profile"] == "dramatic"
    assert delivery_plan["intensity"] == "medium"
    assert "压低声音" in delivery_plan["style_instruction"]
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


def test_narration_template_prioritizes_rhythm_pause_and_stable_narrator_voice() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "instruct_role": "全知叙述者",
            "instruct_scene": "破败街区的雨夜",
            "instruct_emotion": "tense",
            "performance_notes": "保持克制叙述，句尾留白。",
            "delivery_plan": {
                "delivery_mode": "narration",
                "pace": "slow",
                "intensity": "low",
                "pause_strategy": "句尾留白",
                "emotion_primary": "tense",
            },
        },
        "neutral",
    )

    instructions = control.provider_fields["instructions"]

    assert "旁白模板：讲述者视角，信息清晰，语气稳定" in instructions
    assert "说话角色：" not in instructions
    rhythm_index = instructions.index("韵律控制：")
    assert rhythm_index < instructions.index("停顿策略：句尾留白")
    assert instructions.index("停顿策略：句尾留白") < instructions.index("情绪目标：fearful")
    assert instructions.index("情绪目标：fearful") < instructions.index("角色设定：全知叙述者")


def test_dialogue_template_prioritizes_character_emotion_scene_before_rhythm() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "百年门阀岑家的现任大当家",
            "instruct_scene": "祠堂阴影里，她要逼退对方。",
            "instruct_emotion": "tense",
            "performance_notes": "压低声音，语速偏慢。",
            "delivery_plan": {
                "delivery_mode": "dialogue",
                "pace": "slow",
                "intensity": "medium",
            },
        },
        "neutral",
    )

    instructions = control.provider_fields["instructions"]

    assert instructions.startswith("说话角色：岑霜")
    assert "对白模板：突出角色身份、情绪强度与场景张力" in instructions
    assert instructions.index("角色设定：百年门阀岑家的现任大当家") < instructions.index("情绪目标：fearful")
    assert instructions.index("情绪目标：fearful") < instructions.index("场景氛围：祠堂阴影里，她要逼退对方。")
    assert instructions.index("场景氛围：祠堂阴影里，她要逼退对方。") < instructions.index("韵律控制：")


def test_monologue_template_prioritizes_inner_emotion_and_near_ear_delivery() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "岑霜",
            "segment_type": "monologue",
            "instruct_role": "长期压抑情绪的继承人",
            "instruct_scene": "空无一人的偏殿",
            "instruct_emotion": "压抑的恐惧",
            "performance_notes": "近耳低声，像只对自己承认。",
            "delivery_plan": {
                "delivery_mode": "monologue",
                "pace": "slow",
                "intensity": "low",
                "micro_tags": ["低语"],
            },
        },
        "neutral",
    )

    instructions = control.provider_fields["instructions"]

    assert "内心独白模板：贴近心理活动，低强度、近耳感" in instructions
    assert instructions.index("情绪目标：fearful") < instructions.index("演绎要求：近耳低声，像只对自己承认。")
    assert instructions.index("演绎要求：近耳低声，像只对自己承认。") < instructions.index("角色设定：长期压抑情绪的继承人")
    assert instructions.index("角色设定：长期压抑情绪的继承人") < instructions.index("韵律控制：")


def test_model_style_control_normalizes_emotion_with_model_capabilities() -> None:
    qwen_control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_emotion": "tense",
            "performance_notes": "压低声音，句尾留白。",
        },
        "neutral",
    )
    cosy_control = build_model_style_control(
        "cosyvoice-v3.5-plus",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_emotion": "tense",
            "performance_notes": "压低声音，句尾留白。",
        },
        "neutral",
    )

    assert "情绪目标：fearful" in qwen_control.provider_fields["instructions"]
    assert cosy_control.provider_fields["instructions"].startswith("emotion=fearful")
    assert "act=压低声音" in cosy_control.provider_fields["instructions"]
    assert "情绪目标：fearful" not in cosy_control.provider_fields["instructions"]


def test_style_control_compacts_limited_instruction_without_cutting_mid_field() -> None:
    control = build_model_style_control(
        "stepaudio-2.5-tts",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "百年门阀岑家的现任大当家",
            "instruct_scene": "祠堂阴影里，她要用冷硬阶级壁垒逼退对方。" * 6,
            "instruct_emotion": "克制的悲伤，不哭腔，轻轻发颤",
            "performance_notes": "语速极慢，句间留长停顿，在“真心”尾音加轻微气音。" * 6,
        },
        "sad",
    )

    instruction = control.provider_fields["instruction"]

    assert len(instruction) <= 200
    assert instruction.endswith(("。", "！", "？", "”")) or "…" in instruction
    assert "说话角色：岑霜" in instruction
    assert "情绪目标：克制的悲伤，不哭腔，轻轻发颤" in instruction
    assert any("已按 200 字预算压缩" in warning for warning in control.warnings)


def test_provider_prompt_snapshot_exposes_budget_prompt_and_warnings() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_emotion": "紧张又愤怒",
            "performance_notes": "压低声音，句尾留白。",
        },
        "tense",
    )

    snapshot = build_provider_prompt_snapshot(
        model="qwen3-tts-instruct-flash",
        voice_id="Cherry",
        style_control=control,
        delivery_plan={
            "emotion": "紧张又愤怒",
            "pace": "slow",
            "pause_profile": "dramatic",
            "intensity": "medium",
        },
    )

    assert snapshot["model"] == "qwen3-tts-instruct-flash"
    assert snapshot["voice_id"] == "Cherry"
    assert snapshot["mode"] == "natural_language"
    assert snapshot["provider_prompt"]["instructions"] == control.provider_fields["instructions"]
    assert snapshot["provider_prompt"]["messages"] == []
    assert snapshot["provider_prompt"]["context_texts"] == []
    assert snapshot["budget"]["limit"] == 600
    assert snapshot["budget"]["used"] == len(control.provider_fields["instructions"])
    assert snapshot["budget"]["truncated"] is False


def test_provider_prompt_snapshot_exposes_inline_tag_strategy() -> None:
    control = build_model_style_control(
        "mimo-v2.5-tts",
        {
            "style_control_method": "audio_tags",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["低语"],
            "delivery_plan": {
                "micro_tags": ["吸气"],
            },
        },
        "fearful",
    )

    snapshot = build_provider_prompt_snapshot(
        model="mimo-v2.5-tts",
        voice_id="mimo_default",
        style_control=control,
        delivery_plan={"emotion": "fearful"},
    )

    assert snapshot["provider_prompt"]["text_prefix"] == "（紧张）[低语][吸气]"
    assert snapshot["provider_prompt"]["inline_tag_strategy"] == {
        "model_family": "mimo",
        "placement": "assistant_prefix",
        "style_tags": ["紧张"],
        "inline_tags": ["低语", "吸气"],
        "use_tag_parser": False,
    }


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
