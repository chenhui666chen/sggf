from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


def test_instruction_compactor_keeps_budget_and_reports_dropped_fields() -> None:
    from app.services.audiobook.tts_prompt_strategy import compact_instruction_parts

    instruction, budget, warnings = compact_instruction_parts(
        [
            "说话角色：岑霜",
            "情绪目标：克制的悲伤，不哭腔，轻轻发颤",
            "场景氛围：" + "祠堂阴影里，她要逼退对方。" * 8,
            "演绎要求：句间留白，尾音轻颤。",
        ],
        budget=80,
    )

    assert len(instruction) <= 80
    assert instruction.startswith("说话角色：岑霜；情绪目标：克制的悲伤")
    assert budget["limit"] == 80
    assert budget["used"] == len(instruction)
    assert budget["truncated"] is True
    assert "演绎要求：句间留白，尾音轻颤。" in budget["dropped_fields"]
    assert warnings == ["instruction 已按 80 字预算压缩"]


def test_stepaudio_pause_renderer_prefers_explicit_pause_and_dedupes_tags() -> None:
    from app.services.audiobook.tts_prompt_strategy import render_stepaudio_inline_prefix

    prefix = render_stepaudio_inline_prefix(
        {
            "pause_before": 1.25,
            "inline_audio_tags": ["低语", "低语"],
            "delivery_plan": {
                "pause_profile": "dramatic",
                "micro_tags": ["吸气", "低语"],
                "emotion_mix": ["压抑"],
            },
        },
    )

    assert prefix == "（停顿1.25秒）（低语）（吸气）（压抑）"


def test_template_renderer_prioritizes_narration_rhythm_before_character_context() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    parts = build_common_prompt_parts(
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
        emotion="neutral",
        model="qwen-audio-3.1-tts-flash",
    )

    joined = "；".join(parts)
    assert parts[0].startswith("音色约束：保持已选音色")
    assert "旁白模板：讲述者视角，信息清晰，情感随剧情起伏" in joined
    assert "说话角色：" not in joined
    assert joined.index("音色约束：") < joined.index("旁白模板：")
    assert joined.index("韵律控制：") < joined.index("停顿策略：句尾留白")
    assert joined.index("停顿策略：句尾留白") < joined.index("情绪目标：tense")
    assert joined.index("情绪目标：tense") < joined.index("角色设定：全知叙述者")


def test_cosyvoice_prompt_parts_prioritize_short_performance_cues() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    parts = build_common_prompt_parts(
        {
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": "性别：女性，年龄感：青年，音调：中低音，语速：中等，情绪：冷静克制，特点：吐字清晰、气息稳定，用途：有声书旁白",
            "instruct_emotion": "surprised",
            "performance_notes": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "先压住情绪，指纹二字前短暂停顿，结尾加重但不要喊。",
                "stress_words": ["新鲜的指纹"],
                "emotion_primary": "surprised",
            },
        },
        emotion="neutral",
        model="cosyvoice-v3.5-plus",
    )

    assert parts[0] == "原音色不变;仅表演"
    assert "act=压住情绪,加重不喊" in parts
    assert "emotion=surprised" in parts
    assert "重读=新鲜的指纹" in parts
    assert "pause=新鲜的指纹前短停" in parts
    assert not any("声音描述" in part or "性别：女性" in part for part in parts)


def test_stepaudio_prompt_parts_prioritize_global_performance_cues_before_long_context() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    parts = build_common_prompt_parts(
        {
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": "性别：女性，年龄感：青年，音调：中低音，语速：中等，情绪：冷静克制，特点：吐字清晰、气息稳定，用途：有声书旁白。" * 4,
            "instruct_role": "全知叙述者",
            "instruct_scene": "密室揭示关键证据，所有人都屏住呼吸。",
            "instruct_emotion": "压抑的惊惧",
            "performance_notes": "压低声音，真相两个字前短停，结尾加重但不要喊。",
            "delivery_plan": {
                "pause_profile": "dramatic",
                "pause_strategy": "真相前短停，句尾留白",
                "stress_words": ["真相"],
                "director_guidance": "真相前短停，结尾保持克制。",
            },
        },
        emotion="neutral",
        model="stepaudio-3-tts",
    )

    joined = "；".join(parts)

    assert parts[0].startswith("音色约束：保持已选音色")
    assert "情绪目标：压抑的惊惧" in joined
    assert "演绎要求：压低声音，真相两个字前短停，结尾加重但不要喊" in joined
    assert "停顿策略：真相前短停，句尾留白" in joined
    assert "重读词：真相" in joined
    assert "导演指导：真相前短停，结尾保持克制" in joined
    assert "声音描述：" not in joined
    assert "性别：女性" not in joined
    assert joined.index("音色约束：") < joined.index("情绪目标：压抑的惊惧")
    assert joined.index("情绪目标：压抑的惊惧") < joined.index("演绎要求：压低声音")


def test_fixed_voice_prompt_parts_filter_unqualified_hoarseness_and_voice_profile() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    voice_params = {
        "segment_speaker": "旁白",
        "segment_type": "narration",
        "voice_description": "VOICE_PROFILE_MUST_NOT_REACH_TTS",
        "performance_notes": "声音沙哑、虚弱，句尾带少量气声。",
    }

    for model in (
        "qwen-audio-3.1-tts-flash",
        "seed-tts-2.0-expressive",
        "stepaudio-3-tts",
        "cosyvoice-v3.5-plus",
    ):
        parts = build_common_prompt_parts(voice_params, model=model)
        joined = "；".join(parts)
        if model == "cosyvoice-v3.5-plus":
            assert joined.startswith("原音色不变;仅表演")
        else:
            assert "已选音色" in joined
            assert "身份" in joined
            assert "年龄" in joined
            assert "声线" in joined
            assert "辨识度" in joined
        assert "表演" in joined
        assert "VOICE_PROFILE_MUST_NOT_REACH_TTS" not in joined
        assert not any(
            "沙哑" in part and part.startswith(("演绎要求：", "act="))
            for part in parts
        )
        assert "虚弱" in joined
        assert "气声" in joined
        assert "轻度" in joined


def test_common_prompt_parts_sanitize_fallback_emotion_identity_text() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    parts = build_common_prompt_parts(
        {"segment_type": "narration", "segment_speaker": "旁白"},
        emotion="苍老男声，永久沙哑",
        model="seed-tts-2.0-expressive",
    )
    joined = "；".join(parts)

    assert "苍老男声" not in joined
    assert "永久沙哑" not in joined
    assert joined.startswith("音色约束：保持已选音色")


def test_fixed_voice_prompt_parts_allow_temporary_hoarseness_only_on_original_voice() -> None:
    from app.services.audiobook.tts_prompt_strategy import build_common_prompt_parts

    voice_params = {
        "segment_speaker": "旁白",
        "segment_type": "narration",
        "performance_notes": "因重伤失血而声音轻微沙哑，句尾逐渐减弱。",
    }

    for model in (
        "qwen-audio-3.1-tts-flash",
        "seed-tts-2.0-expressive",
        "stepaudio-3-tts",
        "cosyvoice-v3.5-plus",
    ):
        parts = build_common_prompt_parts(voice_params, model=model)
        joined = "；".join(parts)

        assert "沙哑" in joined
        assert "原音色基础" in joined or "原声轻度" in joined
        assert "轻微" in joined or "轻度" in joined
        assert "短暂" in joined or "原声轻度" in joined
