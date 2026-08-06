import json
import os
import sys
import asyncio
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.tts_engine import TTSEngine
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    STEPAUDIO_25_TTS_MODEL,
)
from app.services.audiobook.tts_style_control import build_model_style_control
from app.services.audiobook.segment_direction_service import assist_segment_direction
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.segment_synthesis_contract import (
    compile_segment_synthesis_input,
    sanitize_segment_override,
)
from app.services.audiobook.voice_manager import VoiceProfile
from app.services.audiobook.voice_identity_policy import (
    VOICE_IDENTITY_POLICY_VERSION,
    filter_fixed_voice_identity_tags,
    is_current_voice_identity_snapshot,
    is_voice_design_creation_request,
    sanitize_fixed_voice_performance_text,
    sanitize_fixed_voice_scene_text,
    sanitize_fixed_voice_ssml_text,
)


def test_mimo_voice_design_asset_is_not_treated_as_a_new_voice_design_request() -> None:
    assert is_voice_design_creation_request(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {"voice_design_prompt": "青年女性声线"},
    ) is True
    assert is_voice_design_creation_request(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {
            "speaker": "mimo_design:asset-1",
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "青年女性声线",
        },
    ) is False


def test_mimo_saved_design_asset_keeps_identity_prompt_and_only_adds_performance() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {
            "speaker": "mimo_design:asset-1",
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "青年女性，中音，声线清晰，适合旁白",
            "performance_notes": "改成老人声，语速缓慢，句尾拖长。",
        },
        "neutral",
    )

    content = control.messages[0]["content"]
    assert "青年女性，中音，声线清晰，适合旁白" in content
    assert "固定声音设定保持不变" in content
    assert "老人声" not in content
    assert "语速缓慢" in content
    assert "句尾拖长" in content


def test_mimo_saved_design_asset_segment_contract_keeps_baseline_and_drops_pitch() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "改成老人声，语速缓慢，句尾拖长。",
            "voice_params": {
                "speaker": "mimo_design:asset-1",
                "mimo_voice_asset_id": "asset-1",
                "pitch": 20,
                "pitch_ratio": 0.8,
            },
        },
        tts_model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        voice_id="mimo_design:asset-1",
        emotion="neutral",
        preview_type="voice",
        server_owned_voice_params={
            "mimo_voice_asset_id": "asset-1",
            "voice_design_prompt": "青年女性，中音，声线清晰，适合旁白",
        },
    )

    params = compiled["voice_params"]
    prompt = params["provider_prompt_snapshot"]["provider_prompt"]["messages"][0][
        "content"
    ]
    assert "pitch" not in params
    assert "pitch_ratio" not in params
    assert params["voice_design_prompt"] == "青年女性，中音，声线清晰，适合旁白"
    assert "固定声音设定保持不变" in prompt
    assert "老人声" not in prompt
    assert "语速缓慢" in prompt


def test_segment_override_recursively_drops_fixed_voice_identity_controls() -> None:
    sanitized = sanitize_segment_override(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "pitch": 0.8,
            "voice_description": "客户端伪造的音色描述",
            "voice_params": {
                "speaker": "mimo_design:asset-1",
                "mimo_voice_asset_id": "asset-1",
                "rate": 0.9,
                "pitch": 0.8,
                "pitch_ratio": 0.7,
                "pitch_semitones": -4,
                "character_base_pitch": 42,
                "voice_description": "客户端伪造的音色描述",
                "voice_design_prompt": "客户端伪造的设计配方",
                "custom": {
                    "pitch": 1.2,
                    "voice_design_prompt": "嵌套伪造配方",
                },
            },
        }
    )

    assert sanitized is not None
    assert "pitch" not in sanitized
    assert "voice_description" not in sanitized
    params = sanitized["voice_params"]
    assert params["speaker"] == "mimo_design:asset-1"
    assert params["mimo_voice_asset_id"] == "asset-1"
    assert params["rate"] == 0.9
    for field_name in (
        "pitch",
        "pitch_ratio",
        "pitch_semitones",
        "character_base_pitch",
        "voice_description",
        "voice_design_prompt",
    ):
        assert field_name not in params
        assert field_name not in params["custom"]


def test_seed_fixed_voice_prompt_locks_identity_and_deduplicates_performance_notes() -> None:
    notes = "因重伤而短暂沙哑，语速缓慢，重读‘痛’字，句尾拖长。"

    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": (
                "性别：男性，年龄感：青年，音调：中音，语速：中速，"
                "情绪：calm，特点：吐字清晰，用途：有声书旁白"
            ),
            "instruct_emotion": "极度痛苦与绝望",
            "performance_notes": notes,
            "delivery_plan": {
                "pace": "slow",
                "pitch": "lower",
                "pause_strategy": "句尾停顿",
                "director_guidance": notes,
            },
        },
        "neutral",
    )

    context = control.provider_fields["context_texts"][0]

    assert "保持" in context
    assert "原音色" in context
    assert "说话人身份" in context
    assert "临时" in context and "沙哑" in context
    assert context.count("因重伤，仅在原音色基础上轻微、短暂表现沙哑") == 1
    assert "情绪：calm" not in context


def test_fixed_voice_style_rebuild_does_not_reintroduce_pitch_from_delivery_wording() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "performance_notes": "压低语气，语速缓慢，重读痛字。",
            "delivery_plan": {},
        },
        "neutral",
    )

    context = control.provider_fields["context_texts"][0]

    assert "音调=lower" not in context
    assert "音调=higher" not in context
    assert "压低语气" in context


def test_fixed_voice_ssml_removes_pitch_and_voice_identity_controls_but_keeps_text() -> None:
    cleaned, blocked = sanitize_fixed_voice_ssml_text(
        '<speak pitch="low"><voice name="old"><prosody pitch="-3st">痛。</prosody></voice></speak>'
    )

    assert "痛。" in cleaned
    assert "pitch" not in cleaned.lower()
    assert "voice name" not in cleaned.lower()
    assert blocked


def test_fixed_voice_ssml_keeps_text_and_performance_controls_while_removing_indirect_pitch() -> None:
    cleaned, blocked = sanitize_fixed_voice_ssml_text(
        '<speak><pitch level="-3st">痛。</pitch>'
        '<prosody rate="80%" volume="soft" range="wide" contour="(0%,low)(100%,high)">'
        '仍要克制。</prosody><break time="300ms"/></speak>'
    )

    assert "痛。" in cleaned
    assert "仍要克制。" in cleaned
    assert 'rate="80%"' in cleaned
    assert 'volume="soft"' in cleaned
    assert '<break time="300ms"/>' in cleaned
    assert "pitch" not in cleaned.lower()
    assert "range=" not in cleaned.lower()
    assert "contour=" not in cleaned.lower()
    assert blocked


def test_fixed_voice_server_generated_ssml_never_adds_pitch_control() -> None:
    engine = TTSEngine(
        enable_cache=False,
        model="cosyvoice-v3.5-plus",
        request_delay=0,
    )

    rendered = engine._render_ssml_text(
        "痛。",
        {
            "speaker": "unit-voice",
            "rate": 0.8,
            "volume": 47,
            "pitch": 0.7,
            "character_base_pitch": 50,
            "pause_before": 0.3,
            "pause_after": 0.5,
        },
    )

    assert 'rate="1.00"' in rendered
    assert 'volume="47"' in rendered
    assert '<break time="300ms"/>' in rendered
    assert '<break time="500ms"/>' in rendered
    assert "pitch=" not in rendered.lower()


def test_fixed_voice_ssml_unwraps_pitch_elements_and_removes_pitch_contours() -> None:
    cleaned, blocked = sanitize_fixed_voice_ssml_text(
        '<speak><pitch level="low">痛。</pitch>'
        '<prosody contour="(0%, -20%)" range="x-low" rate="slow">别动。</prosody>'
        '<break time="300ms"/></speak>'
    )

    assert "痛。" in cleaned
    assert "别动。" in cleaned
    assert "<pitch" not in cleaned.lower()
    assert "contour=" not in cleaned.lower()
    assert "range=" not in cleaned.lower()
    assert 'rate="slow"' in cleaned
    assert '<break time="300ms"' in cleaned
    assert blocked


def test_low_level_fixed_voice_engine_filters_identity_controls_before_provider() -> None:
    engine = TTSEngine(
        model="qwen3-tts-instruct-flash",
        enable_cache=False,
        request_delay=0,
    )
    captured: dict[str, object] = {}

    async def fake_call(text: str, params: dict) -> bytes:
        captured["text"] = text
        captured["params"] = dict(params)
        return b"unit-audio"

    engine._call_tts_api = fake_call

    result = asyncio.run(
        engine.synthesize(
            '<speak><prosody pitch="-4st" rate="slow">痛。</prosody></speak>',
            {
                "speaker": "Neil",
                "pitch": 32,
                "speed": 1.1,
                "rate": 1.1,
                "character_base_speed": 1.0,
                "voice_description": "苍老男性，低沉沙哑",
                "voice_design_prompt": "改成陌生老人的声音",
                "provider_prompt_snapshot": {
                    "provider_prompt": {"instructions": "旧提示：切换童声"}
                },
                "instruction": "改成老太太的嗓音，语速缓慢，重读痛字",
            },
            "改成男声",
        )
    )

    params = captured["params"]
    assert result == b"unit-audio"
    assert "pitch" not in params
    assert "speed" not in params
    assert "rate" not in params
    assert "character_base_speed" not in params
    assert "voice_description" not in params
    assert "voice_design_prompt" not in params
    assert "provider_prompt_snapshot" not in params
    assert "老太太" not in params["instruction"]
    assert "语速缓慢" in params["instruction"]
    assert params["emotion"] == "neutral"
    assert "痛。" in captured["text"]
    assert "pitch=" not in captured["text"]
    assert 'rate="slow"' in captured["text"]


def test_low_level_voice_design_engine_keeps_explicit_voice_design_controls() -> None:
    engine = TTSEngine(
        model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        enable_cache=False,
        request_delay=0,
    )
    captured: dict[str, object] = {}

    async def fake_call(text: str, params: dict) -> bytes:
        captured["text"] = text
        captured["params"] = dict(params)
        return b"unit-audio"

    engine._call_tts_api = fake_call

    asyncio.run(
        engine.synthesize(
            "设计试听。",
            {
                "speaker": "",
                "pitch": 38,
                "speed": 1.1,
                "rate": 1.1,
                "character_base_speed": 1.0,
                "voice_description": "年长女性，沙哑低沉",
                "voice_design_prompt": "设计一位年长女性的声音",
            },
            "neutral",
        )
    )

    params = captured["params"]
    assert params["pitch"] == 38
    assert params["voice_description"] == "年长女性，沙哑低沉"
    assert params["voice_design_prompt"] == "设计一位年长女性的声音"
    assert "speed" not in params
    assert "rate" not in params
    assert "character_base_speed" not in params


def test_fixed_voice_prompt_does_not_send_voice_profile_back_to_tts() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "voice_description": (
                "性别：男性，年龄感：青年，音调：中音，语速：中速，"
                "情绪：calm，特点：吐字清晰，用途：有声书旁白"
            ),
            "performance_notes": "语速缓慢，重读‘痛’字。",
        },
        "sad",
    )

    context = control.provider_fields["context_texts"][0]

    assert "声音描述：" not in context
    assert "性别：男性" not in context
    assert "年龄感：青年" not in context
    assert "特点：吐字清晰" not in context
    assert "语速缓慢" in context


def test_fixed_voice_prompt_removes_timbre_replacement_but_keeps_delivery() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "segment_type": "narration",
            "performance_notes": (
                "语速缓慢，改成苍老男性童声，声音永久沙哑，"
                "声音低沉，重读‘痛’字，句尾拖长。"
            ),
            "instructions": "换成少女音并使用空灵声线。",
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"]

    for forbidden in (
        "改成苍老男性童声",
        "声音永久沙哑",
        "换成少女音",
        "空灵声线",
    ):
        assert forbidden not in instruction
    assert "语速缓慢" in instruction
    assert "语气压低" in instruction
    assert "重读‘痛’字" in instruction
    assert "句尾拖长" in instruction
    assert any("已忽略" in warning for warning in control.warnings)


def test_fixed_voice_prompt_normalizes_injury_hoarseness_to_original_voice() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "performance_notes": "因重伤而声音沙哑，语速缓慢，声音虚弱。",
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"]

    assert "仅在原音色基础上轻微、短暂表现沙哑" in instruction
    assert "语速缓慢" in instruction
    assert "声音虚弱" in instruction


def test_fixed_voice_prompt_links_adjacent_illness_and_hoarseness_clauses() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "performance_notes": "因为感冒，声音沙哑，语速偏慢。",
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"]

    assert "因感冒，仅在原音色基础上轻微、短暂表现沙哑" in instruction
    assert "语速偏慢" in instruction


def test_fixed_voice_prompt_filters_english_voice_identity_changes() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "performance_notes": (
                "Use an elderly male voice and deep voice, then slow down and stress pain."
            ),
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"].lower()

    assert "elderly male voice" not in instruction
    assert "deep voice" not in instruction
    assert any("已忽略" in warning for warning in control.warnings)


def test_fixed_voice_policy_filters_case_insensitive_english_hoarseness() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "Hoarse but slow, then keep the ending restrained."
    )
    safe_tags, blocked_tags = filter_fixed_voice_identity_tags(
        ["HUSKY VOICE", "Hoarse", "slow"]
    )

    assert "hoarse" not in cleaned.lower()
    assert "slow" in cleaned.lower()
    assert blocked
    assert safe_tags == ["slow"]
    assert blocked_tags == ["HUSKY VOICE", "Hoarse"]


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("苍老疲惫，语速缓慢", "语速缓慢"),
        ("少女般羞涩，轻声表达", "轻声表达"),
        ("像老人一样虚弱但克制", ""),
        ("elderly and tired, speak slowly", "speak slowly"),
    ),
)
def test_fixed_voice_performance_fields_reject_demographic_voice_descriptors(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    for forbidden in ("苍老", "少女", "老人", "elderly"):
        assert forbidden.casefold() not in cleaned.casefold()
    if retained_performance:
        assert retained_performance in cleaned
    assert blocked


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("年长的声音，语速缓慢", "语速缓慢"),
        ("年幼的声音，轻声表达", "轻声表达"),
        ("年轻男子，保持克制", "保持克制"),
        ("年轻女子的语气，句尾拖长", "句尾拖长"),
        ("成熟男性，语速放慢", "语速放慢"),
        ("女性化，停顿半秒", "停顿半秒"),
        ("breathy voice, slow pace", "slow pace"),
        ("airy timbre, pause at the end", "pause at the end"),
    ),
)
def test_fixed_voice_performance_rejects_derived_identity_descriptors(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert retained_performance in cleaned
    assert blocked
    for forbidden in (
        "年长",
        "年幼",
        "年轻男子",
        "年轻女子",
        "成熟男性",
        "女性化",
        "breathy voice",
        "airy timbre",
    ):
        assert forbidden.casefold() not in cleaned.casefold()


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("改成奶音，语速放慢", "语速放慢"),
        ("使用娃娃音，轻声表达", "轻声表达"),
        ("老奶奶声音，保持克制", "保持克制"),
        ("girl voice, speak slowly", "speak slowly"),
        ("baby voice, keep the ending restrained", "keep the ending restrained"),
        ("granny voice, pause at the end", "pause at the end"),
    ),
)
def test_fixed_voice_performance_fields_reject_voice_identity_synonyms(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    for forbidden in (
        "奶音",
        "娃娃音",
        "老奶奶",
        "girl voice",
        "baby voice",
        "granny voice",
    ):
        assert forbidden.casefold() not in cleaned.casefold()
    assert retained_performance in cleaned
    assert blocked


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("音高降低，语速缓慢", "语速缓慢"),
        ("把声音调低三度，句尾拖长", "句尾拖长"),
        ("基础音高降低，保持克制", "保持克制"),
        ("使用假声，停顿半秒", "停顿半秒"),
        ("切换成萝莉声，语速放慢", "语速放慢"),
        ("用御姐声说，重读痛字", "重读痛字"),
        ("像幼童一样说话，句尾减弱", "句尾减弱"),
        ("改成老太太的嗓音，保持缓慢", "保持缓慢"),
        ("lower pitch by three semitones, speak slowly", "speak slowly"),
        ("use falsetto, pause at the end", "pause at the end"),
    ),
)
def test_fixed_voice_performance_rejects_pitch_and_voice_conversion_commands(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert retained_performance in cleaned
    assert blocked
    assert not any(
        forbidden in cleaned
        for forbidden in (
            "音高",
            "调低三度",
            "假声",
            "萝莉声",
            "御姐声",
            "幼童",
            "老太太",
            "pitch",
            "falsetto",
        )
    )


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("声音变得很低，保持沉重", "保持沉重"),
        ("声调偏低，语速缓慢", "语速缓慢"),
        ("声调偏高，句尾减弱", "句尾减弱"),
        ("用低三度的发声，重读痛字", "重读痛字"),
    ),
)
def test_fixed_voice_performance_rejects_indirect_pitch_commands(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert retained_performance in cleaned
    assert blocked
    assert not any(term in cleaned for term in ("变得很低", "偏低", "偏高", "低三度"))


@pytest.mark.parametrize(
    ("instruction", "retained_performance"),
    (
        ("使用东北口音，语速缓慢", "语速缓慢"),
        ("模仿周杰伦的声音，句尾拖长", "句尾拖长"),
        ("使用成熟嗓音，停顿半秒", "停顿半秒"),
        ("声音更尖细，重读痛字", "重读痛字"),
        ("switch to a British accent, speak slowly", "speak slowly"),
        ("imitate another person's voice, pause at the end", "pause at the end"),
        ("make the voice more nasal, keep the ending restrained", "keep the ending restrained"),
    ),
)
def test_fixed_voice_performance_rejects_accent_imitation_and_timbre_commands(
    instruction: str,
    retained_performance: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert retained_performance in cleaned
    assert blocked
    for forbidden in (
        "东北口音",
        "周杰伦",
        "成熟嗓音",
        "尖细",
        "British accent",
        "another person's voice",
        "voice more nasal",
    ):
        assert forbidden.casefold() not in cleaned.casefold()


def test_fixed_voice_performance_normalizes_ambiguous_tone_words_to_delivery_controls() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "音调低沉，低沉压抑地说，高亢地喊出。"
    )

    assert "音调低沉" not in cleaned
    assert "低沉压抑" not in cleaned
    assert "高亢" not in cleaned
    assert "收紧语势并保持沉重" in cleaned
    assert "压低语气并保持压抑" in cleaned
    assert "提高情绪强度" in cleaned
    assert blocked == []


@pytest.mark.parametrize(
    ("instruction", "expected"),
    (
        (
            "受伤后用粗粝嗓音说，句尾减弱",
            "因受伤，仅在原音色基础上轻微、短暂表现沙哑",
        ),
        (
            "raspy because of a cold, slow pace",
            "因感冒，仅在原音色基础上轻微、短暂表现沙哑",
        ),
    ),
)
def test_fixed_voice_temporary_texture_variants_are_scoped_to_original_voice(
    instruction: str,
    expected: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert expected in cleaned
    assert "粗粝" not in cleaned
    assert "raspy" not in cleaned.lower()
    assert not blocked


def test_fixed_voice_temporary_hoarseness_keeps_other_delivery_instructions() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "因感冒，声音低沉沙哑，语速缓慢，句尾减弱。"
    )

    assert "因感冒，仅在原音色基础上轻微、短暂表现沙哑" in cleaned
    assert "语气压低" in cleaned
    assert "语速缓慢" in cleaned
    assert "句尾减弱" in cleaned
    assert not blocked


@pytest.mark.parametrize(
    ("instruction", "retained"),
    (
        ("gravelly voice, slow pace", "slow pace"),
        ("用破锣嗓说，语速缓慢", "语速缓慢"),
    ),
)
def test_fixed_voice_unscoped_texture_variants_are_removed(
    instruction: str,
    retained: str,
) -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(instruction)

    assert "gravelly" not in cleaned.lower()
    assert "破锣嗓" not in cleaned
    assert retained in cleaned
    assert blocked


def test_fixed_voice_policy_does_not_borrow_injury_state_from_another_subject() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "重伤的敌人倒地，随后主角恢复平静，声音沙哑。"
    )

    assert "仅在原音色基础上" not in cleaned
    assert "沙哑" not in cleaned
    assert "声音沙哑" in blocked


def test_fixed_voice_policy_requires_explicit_temporary_state_for_hoarseness() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "仅在原音色基础上轻微表现沙哑，语速放慢。"
    )

    assert "沙哑" not in cleaned
    assert "语速放慢" in cleaned
    assert blocked


def test_fixed_voice_policy_uses_english_state_word_boundaries() -> None:
    cleaned, blocked = sanitize_fixed_voice_performance_text(
        "Scolding the prisoner, Hoarse but controlled."
    )

    assert "hoarse" not in cleaned.lower()
    assert "原音色基础" not in cleaned
    assert blocked

    cold_tone_cleaned, cold_tone_blocked = sanitize_fixed_voice_performance_text(
        "Keep a cold tone, Hoarse but controlled."
    )
    assert "hoarse" not in cold_tone_cleaned.lower()
    assert "原音色基础" not in cold_tone_cleaned
    assert cold_tone_blocked


@pytest.mark.parametrize(
    "scene",
    (
        "老人院里保持压抑氛围",
        "回忆青年时期的往事",
        "中年危机主题，保持克制",
        "老太太走进房间，环境安静",
        "幼童在庭院里奔跑",
    ),
)
def test_fixed_voice_policy_preserves_non_voice_scene_demographics(scene: str) -> None:
    cleaned, blocked = sanitize_fixed_voice_scene_text(scene)

    assert cleaned == scene
    assert blocked == []


def test_fixed_voice_prompt_rejects_top_level_and_nested_identity_segment_types() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "童声",
            "delivery_plan": {
                "segment_type": "老人声",
                "pace": "slow",
            },
        },
        "sad",
    )

    context = control.provider_fields["context_texts"][0]

    assert "童声" not in context
    assert "老人声" not in context
    assert any("已忽略" in warning for warning in control.warnings)


def test_fixed_voice_prompt_preserves_supported_inner_monologue_segment_type() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "陆衍",
            "segment_type": "inner_monologue",
            "performance_notes": "语速缓慢，保持克制。",
        },
        "sad",
    )

    context = control.provider_fields["context_texts"][0]

    assert "片段类型：inner_monologue" in context
    assert not any("inner_monologue" in warning for warning in control.warnings)


def test_fixed_voice_audio_tags_reject_voice_texture_and_identity_synonyms() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "style_control_method": "audio_tags",
            "style_tags": [
                "紧张",
                "低沉",
                "甜美",
                "girl voice",
                "奶音",
                "音高降低三度",
                "假声",
            ],
            "inline_audio_tags": [
                "低语",
                "高亢",
                "稚嫩",
                "baby voice",
                "娃娃音",
                "萝莉声",
            ],
        },
        "fearful",
    )

    assert "紧张" in control.provider_fields["inline_tag_strategy"]["style_tags"]
    assert "低语" in control.text_prefix
    for forbidden in (
        "低沉",
        "高亢",
        "甜美",
        "稚嫩",
        "girl voice",
        "baby voice",
        "奶音",
        "娃娃音",
        "音高降低三度",
        "假声",
        "萝莉声",
    ):
        assert forbidden.casefold() not in control.text_prefix.casefold()
    assert any("已忽略" in warning for warning in control.warnings)


def test_fixed_voice_prompt_rejects_identity_commands_in_structured_plan_fields() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "delivery_plan": {
                "text": "痛。",
                "delivery_mode": "改成童声",
                "pace": "老人声",
                "pitch": "deep voice",
                "intensity": "少女音",
                "stress_words": ["换成苍老男声", "痛"],
            },
        },
        "sad",
    )

    context = control.provider_fields["context_texts"][0]
    for forbidden in ("童声", "老人声", "deep voice", "少女音", "苍老男声"):
        assert forbidden not in context
    assert "重读词：痛" in context
    assert any("已忽略" in warning for warning in control.warnings)


def test_mimo_prompt_sanitizes_emotion_and_descriptive_speaker_identity() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_MODEL,
        {
            "speaker": "冰糖",
            "segment_speaker": "老者",
            "segment_type": "dialogue",
            "instruct_emotion": "苍老男声，永久沙哑",
            "performance_notes": "语速缓慢，保持克制。",
        },
        "苍老男声，永久沙哑",
    )

    prompt = control.messages[0]["content"]
    assert "苍老男声" not in prompt
    assert "永久沙哑" not in prompt
    assert "角色：当前角色" in prompt
    assert "语速缓慢" in prompt


def test_mimo_director_prompt_locks_preset_voice_identity() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_MODEL,
        {
            "speaker": "冰糖",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "performance_notes": "因生病而轻微沙哑，但仍保持克制叙述。",
        },
        "sad",
    )

    prompt = control.messages[0]["content"]

    assert "保持" in prompt
    assert "原音色" in prompt
    assert "说话人身份" in prompt
    assert "轻微、短暂表现沙哑" in prompt


def test_mimo_audio_tags_drop_identity_transformations_and_keep_performance_tags() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_MODEL,
        {
            "speaker": "冰糖",
            "style_control_method": "audio_tags",
            "style_tags": ["紧张", "老年男声"],
            "inline_audio_tags": [
                "低语",
                "童声",
                "因生病轻微沙哑",
                "童声且因生病轻微沙哑",
            ],
        },
        "fearful",
    )

    assert "老年男声" not in control.text_prefix
    assert "童声" not in control.text_prefix
    assert "童声且因生病轻微沙哑" not in control.text_prefix
    assert "紧张" in control.provider_fields["inline_tag_strategy"]["style_tags"]
    assert "低语" in control.text_prefix
    assert "沙哑" not in control.text_prefix
    assert "因生病，仅在原音色基础上轻微、短暂表现沙哑" in control.messages[0]["content"]
    assert any("音色身份" in warning for warning in control.warnings)


def test_seed_audio_tags_drop_identity_transformations_and_keep_temporary_texture() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "style_control_method": "audio_tags",
            "style_tags": ["紧张", "老年男声"],
            "inline_audio_tags": ["低语", "童声", "因生病轻微沙哑"],
        },
        "fearful",
    )

    assert "老年男声" not in control.text_prefix
    assert "童声" not in control.text_prefix
    assert "紧张" in control.provider_fields["inline_tag_strategy"]["style_tags"]
    assert "低语" in control.text_prefix
    assert "沙哑" not in control.text_prefix
    assert (
        "因生病，仅在原音色基础上轻微、短暂表现沙哑"
        in control.provider_fields["context_texts"][0]
    )
    assert any("已忽略" in warning for warning in control.warnings)


def test_stepaudio_audio_tags_drop_identity_transformations_and_keep_temporary_texture() -> None:
    control = build_model_style_control(
        STEPAUDIO_25_TTS_MODEL,
        {
            "speaker": "default",
            "inline_audio_tags": ["低语", "童声", "因生病轻微沙哑"],
            "delivery_plan": {
                "micro_tags": ["吸气", "老年男声"],
                "emotion_mix": ["压抑"],
            },
        },
        "fearful",
    )

    assert "童声" not in control.text_prefix
    assert "老年男声" not in control.text_prefix
    assert "低语" in control.text_prefix
    assert "吸气" in control.text_prefix
    assert "压抑" in control.text_prefix
    assert "沙哑" not in control.text_prefix
    assert (
        "因生病，仅在原音色基础上轻微、短暂表现沙哑"
        in control.provider_fields["instruction"]
    )
    assert any("已忽略" in warning for warning in control.warnings)


def test_mimo_audio_tag_payload_sends_identity_guard_before_performance() -> None:
    engine = TTSEngine(model=MIMO_V25_TTS_MODEL, enable_cache=False, request_delay=0)

    payload = engine._build_mimo_chat_payload(
        model=MIMO_V25_TTS_MODEL,
        text="别回头。",
        voice="冰糖",
        voice_params={
            "speaker": "冰糖",
            "style_control_method": "audio_tags",
            "style_tags": ["紧张"],
            "inline_audio_tags": ["低语"],
        },
    )

    assert payload["messages"][0]["role"] == "user"
    assert "保持" in payload["messages"][0]["content"]
    assert "原音色" in payload["messages"][0]["content"]
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "（紧张）[低语]别回头。",
    }


def test_explicit_only_temporary_texture_still_gets_original_voice_guard() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "instructions": "因重伤而短暂沙哑，语速缓慢。",
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"]
    assert "沙哑等临时质感仅在原音色基础上轻度表现" in instruction
    assert "因重伤，仅在原音色基础上轻微、短暂表现沙哑，语速缓慢" in instruction


def test_english_temporary_hoarseness_does_not_conflict_with_identity_guard() -> None:
    control = build_model_style_control(
        "qwen3-tts-instruct-flash",
        {
            "speaker": "Neil",
            "instructions": "Because of an injury, Hoarse but controlled.",
        },
        "sad",
    )

    instruction = control.provider_fields["instructions"]

    assert "因受伤，仅在原音色基础上轻微、短暂表现沙哑" in instruction
    assert "未明确为短暂状态的沙哑要求应忽略" not in instruction


def test_legacy_prompt_snapshot_without_identity_policy_version_is_rebuilt() -> None:
    engine = TTSEngine(
        model="qwen3-tts-instruct-flash",
        enable_cache=False,
        request_delay=0,
    )

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="别回头。",
        voice_id="Neil",
        voice_params={
            "instructions": "语速缓慢，保持克制。",
            "provider_prompt_snapshot": {
                "provider_prompt": {"instructions": "旧快照：改成苍老沙哑的陌生人"}
            },
        },
    )

    instruction = payload["parameters"]["instructions"]
    assert "旧快照" not in instruction
    assert instruction.startswith("音色约束：保持已选音色")
    assert "语速缓慢，保持克制" in instruction


def test_current_voice_identity_snapshot_requires_version_model_and_voice() -> None:
    snapshot = {
        "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION,
        "model": "seed-tts-2.0-expressive",
        "voice_id": "voice-a",
    }

    assert is_current_voice_identity_snapshot(
        snapshot,
        model="seed-tts-2.0-expressive",
        voice_id="voice-a",
    )
    assert not is_current_voice_identity_snapshot(
        {**snapshot, "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION - 1},
        model="seed-tts-2.0-expressive",
        voice_id="voice-a",
    )
    assert not is_current_voice_identity_snapshot(
        snapshot,
        model="qwen3-tts-instruct-flash",
        voice_id="voice-a",
    )
    assert not is_current_voice_identity_snapshot(
        snapshot,
        model="seed-tts-2.0-expressive",
        voice_id="voice-b",
    )


def test_segment_preview_rejects_stale_compiled_prompt_snapshot() -> None:
    service = object.__new__(SegmentPreviewService)
    service.tts_model = "seed-tts-2.0-expressive"
    segment = {
        "instruct_emotion": "sad",
        "voice_params": {
            "speaker": "voice-a",
            "tts_model": "seed-tts-2.0-expressive",
            "delivery_plan": {"pace": "slow"},
            "provider_prompt_snapshot": {
                "voice_identity_policy_version": VOICE_IDENTITY_POLICY_VERSION - 1,
                "model": "seed-tts-2.0-expressive",
                "voice_id": "voice-a",
                "provider_prompt": {"instructions": "旧策略提示"},
            },
        },
    }

    assert service._resolve_compiled_voice_params(segment) is None


def test_qwen_low_budget_uses_complete_compact_identity_guard() -> None:
    engine = TTSEngine(
        model="qwen3-tts-instruct-flash",
        enable_cache=False,
        request_delay=0,
    )

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="长" * 555,
        voice_id="Neil",
        voice_params={"instructions": "语速缓慢并保持克制。"},
    )

    instruction = payload["parameters"]["instructions"]
    assert instruction.startswith("保持已选音色身份和基础声线，仅调整表演")
    assert "音色约束：保持已选音色的说话人身…" not in instruction


def test_qwen_refit_compacts_identity_guard_to_preserve_performance() -> None:
    engine = TTSEngine(
        model="qwen3-tts-instruct-flash",
        enable_cache=False,
        request_delay=0,
    )

    payload = engine._build_qwen_http_payload(
        model="qwen3-tts-instruct-flash",
        text="长" * 520,
        voice_id="Neil",
        voice_params={"instructions": "语速缓慢，重读痛字，句尾拖长。"},
    )

    instruction = payload["parameters"]["instructions"]
    assert instruction.startswith("保持已选音色身份和基础声线，仅调整表演")
    assert "语速缓慢" in instruction


def test_minimax_basic_mode_does_not_derive_pitch_shift_from_performance_prompt() -> None:
    control = build_model_style_control(
        "minimax-speech-2.8-hd",
        {
            "pitch": 0,
            "speed": 1.0,
            "volume": 50,
            "delivery_plan": {
                "pace": "slow",
                "pitch": "lower",
                "intensity": "low",
            },
        },
        "sad",
    )

    settings = control.provider_fields["basic_voice_settings"]

    assert "pitch" not in settings
    assert settings["speed"] == 0.9
    assert settings["volume"] == 44

    engine = TTSEngine(
        model="minimax-speech-2.8-hd",
        enable_cache=False,
        request_delay=0,
    )
    payload = engine._build_minimax_http_payload(
        model="minimax-speech-2.8-hd",
        text="测试。",
        voice="unit-voice",
        voice_params={
            "pitch": 80,
            "delivery_plan": {"pitch": "higher"},
        },
    )

    assert payload["input"]["voice_setting"]["pitch"] == 0


def test_voice_profile_does_not_emit_character_pitch_across_emotions() -> None:
    profile = VoiceProfile(
        voice_id="unit-voice",
        character_name="旁白",
        gender="male",
        age_group="young",
        personality="calm",
        tts_speaker_id="unit-voice",
        pitch_base=43,
        speed_base=1.0,
        volume_base=50,
    )

    assert "pitch" not in profile.get_tts_params("sad")
    assert "pitch" not in profile.get_tts_params("angry")


def test_segment_contract_drops_legacy_segment_pitch_instead_of_restoring_it() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "压低语气，保持克制。",
            "voice_params": {
                "speaker": "unit-voice",
                "pitch": 0.9,
                "pitch_ratio": 0.8,
                "pitch_semitones": -3,
                "character_base_pitch": 50,
            },
        },
        tts_model="seed-tts-2.0-expressive",
        voice_id="unit-voice",
        emotion="fearful",
        preview_type="voice",
    )

    params = compiled["voice_params"]
    assert "pitch" not in params
    assert "pitch_ratio" not in params
    assert "pitch_semitones" not in params
    assert "pitch" not in params["delivery_plan"]


def test_segment_contract_drops_client_owned_fixed_voice_asset_payloads() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "语速缓慢，句尾拖长。",
            "voice_params": {
                "speaker": "mimo_design:asset-1",
                "mimo_voice_asset_id": "asset-1",
                "voice_design_prompt": "客户端伪造的老人声",
                "voice_description": "客户端伪造的老人声",
                "voice_clone_data_url": "data:audio/wav;base64,CLIENT",
            },
        },
        tts_model=MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        voice_id="mimo_design:asset-1",
        emotion="neutral",
        preview_type="voice",
    )

    serialized = json.dumps(compiled, ensure_ascii=False)
    assert "客户端伪造的老人声" not in serialized
    assert "data:audio/wav;base64,CLIENT" not in serialized
    assert "voice_design_prompt" not in compiled["voice_params"]
    assert "voice_description" not in compiled["voice_params"]
    assert "voice_clone_data_url" not in compiled["voice_params"]


def test_fixed_voice_delivery_plan_never_encodes_segment_pitch_changes() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "痛意沿着肩胛骨炸开。",
            "performance_notes": "音调低沉，声线更低更沉，语速缓慢，重读痛字。",
            "voice_params": {
                "speaker": "unit-voice",
                "character_base_pitch": 50,
            },
        },
        tts_model="seed-tts-2.0-expressive",
        voice_id="unit-voice",
        emotion="sad",
        preview_type="voice",
    )

    params = compiled["voice_params"]
    serialized = json.dumps(params, ensure_ascii=False)

    assert "pitch" not in params
    assert "pitch" not in params["delivery_plan"]
    assert "音调=lower" not in serialized
    assert "声线更低" not in serialized
    assert "收紧语势" in serialized


def test_segment_contract_drops_client_controlled_seed_tag_parser() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "[童声]别回头。",
            "voice_params": {
                "speaker": "unit-voice",
                "use_tag_parser": True,
                "style_control_method": "labels",
            },
        },
        tts_model="seed-tts-2.0-expressive",
        voice_id="unit-voice",
        emotion="fearful",
        preview_type="voice",
    )

    params = compiled["voice_params"]

    assert "use_tag_parser" not in params
    assert "style_control_method" not in params
    assert params["provider_prompt_snapshot"]["provider_prompt"].get("use_tag_parser") is not True


def test_segment_contract_persists_only_sanitized_fixed_voice_performance_controls() -> None:
    compiled = compile_segment_synthesis_input(
        {
            "type": "narration",
            "speaker": "旁白",
            "text": "别回头。",
            "performance_notes": "苍老疲惫，声音低沉沙哑，语速缓慢。",
            "voice_params": {"speaker": "unit-voice"},
        },
        tts_model="seed-tts-2.0-expressive",
        voice_id="unit-voice",
        emotion="fearful",
        preview_type="voice",
    )

    params = compiled["voice_params"]
    serialized_contract = json.dumps(params, ensure_ascii=False)

    assert compiled["segment"]["performance_notes"] == "苍老疲惫，声音低沉沙哑，语速缓慢。"
    assert params["performance_notes"] == "语气压低，语速缓慢"
    for forbidden in ("苍老", "沙哑", "声音低沉"):
        assert forbidden not in serialized_contract


def test_fixed_narrator_role_drops_segment_level_voice_adjectives() -> None:
    control = build_model_style_control(
        "seed-tts-2.0-expressive",
        {
            "speaker": "zh_male_yuanboxiaoshu_uranus_bigtts",
            "segment_speaker": "旁白",
            "segment_type": "narration",
            "instruct_role": "低沉压抑且沙哑的有声书旁白",
            "instruct_identity": "故事讲述者",
            "performance_notes": "语速缓慢，表现痛苦。",
        },
        "sad",
    )

    context = control.provider_fields["context_texts"][0]
    assert "角色设定：有声书旁白" in context
    assert "低沉压抑且沙哑的有声书旁白" not in context


def test_mimo_voice_design_remains_an_explicit_voice_creation_path() -> None:
    control = build_model_style_control(
        MIMO_V25_TTS_VOICE_DESIGN_MODEL,
        {
            "voice_description": "青年女性，中音偏低，声线清晰。",
            "performance_notes": "语速缓慢，句尾轻微气声。",
        },
        "calm",
    )

    prompt = control.messages[0]["content"]

    assert "青年女性，中音偏低，声线清晰。" in prompt
    assert "保持原音色" not in prompt


@pytest.mark.asyncio
async def test_segment_direction_assist_cannot_rewrite_role_or_identity() -> None:
    class _RoleChangingLLM:
        async def chat(self, **_kwargs):
            return """{
              "intent": {"pace": "slow", "emotion_primary": "sad"},
              "patch": {
                "instruct_emotion": "sad",
                "instruct_scene": "水牢",
                "instruct_role": "苍老沙哑的陌生旁白",
                "instruct_identity": "另一位故事讲述者",
                "voice_params": {"rate": 0.8, "pitch": 0.9}
              }
            }"""

    result = await assist_segment_direction(
        cue_type="voice",
        description="语速缓慢，表现痛苦，但保持原来的旁白音色。",
        segment={"speaker": "旁白", "type": "narration"},
        tts_model="seed-tts-2.0-expressive",
        llm_client=_RoleChangingLLM(),
    )

    patch = result["patch"]

    assert patch["instruct_emotion"] == "sad"
    assert patch["instruct_scene"] == "水牢"
    assert "instruct_role" not in patch
    assert "instruct_identity" not in patch
    assert result["intent"]["pace"] == "slow"
    assert "voice_params" not in patch
