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
    assert "语速偏慢" in delivery_plan["style_instruction"]
    assert "哽咽" in delivery_plan["micro_tags"]
    assert "director_guidance" not in delivery_plan


def test_tts_batch_item_rebuilds_prompt_snapshot_from_current_direction() -> None:
    class DummyEngine(TTSMixin):
        tts_model = "qwen3-tts-instruct-flash"

    segment = SimpleNamespace(
        text="The current line.",
        type="narration",
        speaker="narrator",
        emotion="neutral",
        instruct_emotion="neutral",
        instruct_scene="current scene",
        instruct_role="current narrator",
        instruct_identity="storyteller",
        performance_notes="CURRENT_DIRECTION slow and restrained",
        voice_params={
            "speaker": "Cherry",
            "tts_model": "qwen3-tts-instruct-flash",
            "performance_notes": "STALE_DIRECTION",
            "instructions": "STALE_PROVIDER_INSTRUCTIONS",
            "context_texts": ["STALE_PROVIDER_CONTEXT"],
            "messages": [{"role": "user", "content": "STALE_PROVIDER_MESSAGE"}],
            "text_prefix": "STALE_PROVIDER_PREFIX",
            "delivery_plan": {"director_guidance": "STALE_DIRECTION"},
            "provider_prompt_snapshot": {
                "model": "qwen3-tts-instruct-flash",
                "voice_id": "stale-voice",
                "provider_prompt": {"instructions": "STALE_PROVIDER_PROMPT"},
            },
        },
    )

    item = DummyEngine()._build_tts_batch_item(segment)
    voice_params = item["voice_params"]
    delivery_plan = voice_params["delivery_plan"]
    snapshot = voice_params["provider_prompt_snapshot"]

    assert voice_params["performance_notes"] == "CURRENT_DIRECTION slow and restrained"
    assert delivery_plan["style_instruction"] == "CURRENT_DIRECTION slow and restrained"
    assert "director_guidance" not in delivery_plan
    assert snapshot["voice_id"] == "Cherry"
    assert snapshot["delivery_plan"]["style_instruction"] == (
        "CURRENT_DIRECTION slow and restrained"
    )
    assert "director_guidance" not in snapshot["delivery_plan"]
    assert "CURRENT_DIRECTION slow and restrained" in str(snapshot["provider_prompt"])
    assert "STALE_PROVIDER_PROMPT" not in str(snapshot["provider_prompt"])
    assert "STALE_PROVIDER_" not in str(snapshot)


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
    assert instructions.startswith("音色约束：保持已选音色")
    assert "朗读方式：sob" in instructions
    assert "情绪层次：压抑、悲伤" in instructions
    assert "微表演标签：哽咽、低语" in instructions
    assert "重读词：撑不住" in instructions
    assert "导演指导：压低声音，语速偏慢，在“撑不住”处轻微加重" in instructions


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

    assert "旁白模板：讲述者视角，信息清晰，情感随剧情起伏" in instructions
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

    assert instructions.startswith("音色约束：保持已选音色")
    assert instructions.index("音色约束：") < instructions.index("说话角色：岑霜")
    assert "对白模板：突出角色身份、情绪强度与场景张力" in instructions
    assert instructions.index("角色设定：百年门阀岑家的现任大当家") < instructions.index("情绪目标：fearful")
    assert instructions.index("情绪目标：fearful") < instructions.index("场景氛围：祠堂阴影里，她要逼退对方")
    assert instructions.index("场景氛围：祠堂阴影里，她要逼退对方") < instructions.index("韵律控制：")


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

    assert instructions.startswith("音色约束：保持已选音色")
    assert "内心独白模板：贴近心理活动，低强度、近耳感" in instructions
    assert instructions.index("情绪目标：fearful") < instructions.index("演绎要求：近耳低声，像只对自己承认")
    assert instructions.index("演绎要求：近耳低声，像只对自己承认") < instructions.index("角色设定：长期压抑情绪的继承人")
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

    qwen_instructions = qwen_control.provider_fields["instructions"]
    cosy_instructions = cosy_control.provider_fields["instructions"]

    assert qwen_instructions.startswith("音色约束：保持已选音色")
    assert "情绪目标：fearful" in qwen_instructions
    assert cosy_instructions.startswith("原音色不变;仅表演")
    assert "emotion=fearful" in cosy_instructions
    assert "act=压低声音" in cosy_instructions
    assert "情绪目标：fearful" not in cosy_instructions


def test_style_control_compacts_limited_instruction_without_cutting_mid_field() -> None:
    scene_details = "；".join(
        f"祠堂场景细节{i}要求用冷硬阶级壁垒逼退对方" for i in range(1, 9)
    )
    performance_details = "；".join(
        f"第{i}处语速极慢并在真心尾音加轻微气音" for i in range(1, 9)
    )
    control = build_model_style_control(
        "stepaudio-2.5-tts",
        {
            "segment_speaker": "岑霜",
            "segment_type": "dialogue",
            "instruct_role": "百年门阀岑家的现任大当家",
            "instruct_scene": scene_details,
            "instruct_emotion": "克制的悲伤，不哭腔，轻轻发颤",
            "performance_notes": performance_details,
        },
        "sad",
    )

    instruction = control.provider_fields["instruction"]

    assert len(instruction) <= 200
    assert instruction.startswith("音色约束：保持已选音色")
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


def test_provider_prompt_snapshot_drops_segment_pitch_controls() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {"performance_notes": "语速缓慢，重读关键词。"},
        "neutral",
    )
    delivery_plan = {
        "pace": "slow",
        "speed": 1.1,
        "rate": 1.1,
        "character_base_speed": 1.0,
        "pitch": "lower",
        "pitch_ratio": 0.8,
        "pitch_semitones": -3,
        "character_base_pitch": 50,
    }

    snapshot = build_provider_prompt_snapshot(
        model="qwen3-tts-instruct-flash",
        voice_id="Cherry",
        style_control=control,
        delivery_plan=delivery_plan,
    )

    assert snapshot["delivery_plan"] == {"pace": "slow"}
    assert delivery_plan["pitch"] == "lower"


def test_instruction_model_does_not_infer_semantic_pace_from_legacy_numeric_speed() -> None:
    plan = build_delivery_plan(
        segment=SimpleNamespace(
            type="narration",
            speaker="旁白",
            text="风从门缝里灌了进来。",
            performance_notes="保持克制地讲述。",
            emotion="neutral",
        ),
        voice_params={"speed": 1.1, "rate": 1.1},
        model="seed-tts-2.0-expressive",
        emotion="neutral",
    )

    assert plan["pace"] == "medium"


def test_basic_model_can_infer_pace_from_numeric_speed_fallback() -> None:
    plan = build_delivery_plan(
        segment=SimpleNamespace(
            type="narration",
            speaker="旁白",
            text="风从门缝里灌了进来。",
            performance_notes="保持克制地讲述。",
            emotion="neutral",
        ),
        voice_params={"speed": 1.1},
        model="minimax-speech-2.8-hd",
        emotion="neutral",
    )

    assert plan["pace"] == "fast"


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
                "micro_tags": ["哽咽", "低语", "童声"],
            },
        },
        "sad",
    )

    assert control.mode == "mimo_audio_tags"
    assistant_content = prepare_text_for_style_control("我真的撑不住了。", control)
    provider_messages = [
        *control.messages,
        {"role": "assistant", "content": assistant_content},
    ]

    assert [message["role"] for message in provider_messages] == ["user", "assistant"]
    assert control.messages[0]["content"].startswith("音色约束：保持已选音色")
    assert control.text_prefix == "（sad，压抑，悲伤）[哽咽][低语]"
    assert assistant_content == "（sad，压抑，悲伤）[哽咽][低语]我真的撑不住了。"
    assert "童声" not in str(provider_messages)


def test_build_delivery_plan_extracts_stress_words_and_keeps_ending_length_separate_from_pause() -> None:
    segment = SimpleNamespace(
        type="narration",
        speaker="旁白",
        text="痛。",
        performance_notes="语速缓慢，重读'痛'字，句尾拖长，营造痛苦氛围。",
        instruct_emotion="sad",
        instruct_scene="水牢",
        instruct_role="旁白",
        instruct_identity="讲述者",
        emotion="sad",
    )

    plan = build_delivery_plan(
        segment=segment,
        voice_params={},
        model="seed-tts-2.0-expressive",
        emotion="sad",
    )

    assert plan["stress_words"] == ["痛"]
    assert plan["ending_style"] == "lengthened"
    assert "pause_strategy" not in plan


def test_build_delivery_plan_separates_performance_notes_from_director_and_pause_fields() -> None:
    segment = SimpleNamespace(
        type="narration",
        speaker="旁白",
        text="只听到哗啦一声沉重的金属撞击声。",
        performance_notes="语速中等偏慢，声音沙哑，'哗啦'处加重，句尾停顿。",
        instruct_emotion="neutral",
        instruct_scene="水牢",
        instruct_role="有声书旁白",
        instruct_identity="讲述者",
        emotion="neutral",
    )

    plan = build_delivery_plan(
        segment=segment,
        voice_params={},
        model="seed-tts-2.0-expressive",
        emotion="neutral",
    )

    assert plan["style_instruction"] == segment.performance_notes
    assert "director_guidance" not in plan
    assert plan["pause_strategy"] == "句尾停顿"


def test_build_delivery_plan_keeps_distinct_explicit_director_guidance() -> None:
    segment = SimpleNamespace(
        type="dialogue",
        speaker="陆衍",
        text="别过来。",
        performance_notes="声音虚弱，句尾留白。",
        instruct_emotion="fearful",
        instruct_scene="水牢",
        instruct_role="受伤的囚徒",
        instruct_identity="陆衍",
        emotion="fearful",
    )

    plan = build_delivery_plan(
        segment=segment,
        voice_params={"instructions": "保持克制，不要喊叫。"},
        model="qwen3-tts-instruct-flash",
        emotion="fearful",
    )

    assert plan["director_guidance"] == "保持克制，不要喊叫。"
    assert plan["pause_strategy"] == "句尾留白"
