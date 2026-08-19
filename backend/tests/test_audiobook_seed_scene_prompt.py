from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.models import (
    SceneAudioEvent,
    SceneVoiceProfile,
)
from app.services.audiobook.scene_engine.prompt_compiler import ScenePromptCompiler
from app.services.audiobook.script_adapter_pkg._dataclasses import MusicCue, ScriptSegment, SoundEffect


def test_compiler_preserves_dialogue_order_and_reference_mapping() -> None:
    compiler = ScenePromptCompiler()
    segments = [
        ScriptSegment(
            type="dialogue",
            text="把头抬起来。我得记住你现在的样子。",
            speaker="太后",
            emotion="angry",
            performance_notes="缓慢、冷酷且充满命令感",
        ),
        ScriptSegment(
            type="dialogue",
            text="遵旨。",
            speaker="御医",
            emotion="neutral",
            performance_notes="恭敬、顺从，正式清晰",
        ),
    ]
    voices = [
        SceneVoiceProfile("御医", "中年男性，浑厚、略微沙哑、谦逊", {"speaker": "doctor"}),
        SceneVoiceProfile("未出场角色", "青年女性，清亮", {"speaker": "unused"}),
        SceneVoiceProfile("太后", "55岁左右，端庄优雅、威严冷酷", {"speaker": "empress"}),
    ]

    result = compiler.compile_segments(
        segments,
        voice_profiles=voices,
        scene_description="深夜宫殿内殿，空间空旷，整体压抑紧张",
    )

    assert result.expected_texts == (
        "把头抬起来。我得记住你现在的样子。",
        "遵旨。",
    )
    assert result.references == ({"speaker": "empress"}, {"speaker": "doctor"})
    assert (
        "太后 的声音参考 @音频1，以参考中的声音身份为准；"
        "仅按当前剧情调整情绪、语气、音量、语速和停顿。"
    ) in result.prompt
    assert (
        "御医 的声音参考 @音频2，以参考中的声音身份为准；"
        "仅按当前剧情调整情绪、语气、音量、语速和停顿。"
    ) in result.prompt
    assert "55岁左右" not in result.prompt
    assert "浑厚、略微沙哑" not in result.prompt
    assert "未出场角色" not in result.prompt
    assert result.prompt.index("把头抬起来") < result.prompt.index("遵旨")
    assert re.findall(r"说[道|：]*：“([^”]+)”", result.prompt) == list(result.expected_texts)


def test_compiler_separates_vocalization_from_sfx_and_spoken_text() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="不要啊！",
        speaker="俘虏",
        emotion="fearful",
        performance_notes="极其惊恐地尖叫，随后急促喘息并痛苦吞咽",
        sound_effects=[SoundEffect(name="一声金属质感的刀光唰声", layer="action")],
    )

    result = compiler.compile_segments(
        [segment],
        voice_profiles=[SceneVoiceProfile("俘虏", "大妈，朴素、略带沙哑，嗓音亲和")],
    )

    speech, vocalization, sound_effect = result.events
    assert speech.kind == "speech"
    assert speech.exact_text == "不要啊！"
    assert vocalization.kind == "vocalization"
    assert vocalization.exact_text is None
    assert "喘息" in (vocalization.performance or "")
    assert "吞咽" in (vocalization.performance or "")
    assert sound_effect.kind == "sfx"
    assert sound_effect.exact_text is None
    assert re.findall(r"：“([^”]+)”", result.prompt) == ["不要啊！"]
    assert "喘息" in result.prompt
    assert "刀光唰声" in result.prompt


def test_compiler_sanitizes_segment_performance_before_seed_scene_prompt() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="narration",
        text="痛意沿着肩胛骨炸开。",
        speaker="旁白",
        emotion="sad",
        performance_notes=(
            "改成老爷爷声，音调低沉，声音永久沙哑，"
            "语速缓慢，重读痛字，句尾拖长。"
        ),
    )

    result = compiler.compile_segments([segment])

    for forbidden in ("老爷爷声", "音调低沉", "永久沙哑", "声线", "音色"):
        assert forbidden not in result.prompt
    assert "语速缓慢" in result.prompt
    assert "重读痛字" in result.prompt
    assert "句尾拖长" in result.prompt
    assert "收紧语势" in result.prompt


def test_compiler_keeps_illness_hoarseness_temporary_and_bound_to_original_voice() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="我没事。",
        speaker="陆衍",
        emotion="sad",
        performance_notes="因重伤而声音沙哑，语速缓慢。",
    )

    result = compiler.compile_segments([segment])

    assert "因重伤，仅在原音色基础上轻微、短暂表现沙哑" in result.prompt
    assert "语速缓慢" in result.prompt


def test_compiler_does_not_treat_descriptive_speaker_label_as_a_new_voice() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="我没事。",
        speaker="老爷爷声",
        emotion="sad",
        performance_notes="语速缓慢，保持克制。",
    )

    result = compiler.compile_segments([segment])

    assert "老爷爷声" not in result.prompt
    # §9.2：无显式动作时用中性模板，不再套用“用……的方式说道”。
    assert "当前角色说道：“我没事。”（语速缓慢，保持克制）" in result.prompt


def test_compiler_renders_music_changes_and_until_text_anchor_in_order() -> None:
    compiler = ScenePromptCompiler()
    events = [
        SceneAudioEvent(
            kind="music",
            anchor="before",
            acoustic="音乐以紧张弦乐和低频鼓点进入，对白出现时降低",
        ),
        SceneAudioEvent(
            kind="speech",
            anchor="during",
            speaker="男主",
            exact_text="脑子进水啊？有本事自己查啊！有病啊！三八！",
            performance="愤怒拔高，随后轻蔑地压低声线",
        ),
        SceneAudioEvent(
            kind="sfx",
            anchor="until_text",
            acoustic="木地板上的快速脚步声",
            related_text="三八",
        ),
        SceneAudioEvent(kind="music", anchor="after", acoustic="音乐停止"),
    ]

    result = compiler.compile_events(
        events,
        voice_profiles=[SceneVoiceProfile("男主", "中年男性，港式普通话，警察")],
    )

    assert result.prompt.index("紧张弦乐") < result.prompt.index("脑子进水")
    # §9.4：中性措辞，related_text 为目标台词子串。
    assert "持续至对应台词中的“三八”说完" in result.prompt
    assert result.prompt.index("持续至对应台词") < result.prompt.index("音乐停止")


def test_compiler_returns_split_requirement_without_removing_dialogue() -> None:
    compiler = ScenePromptCompiler(max_prompt_chars=280)
    exact_text = "我们都不起眼，没有人在乎我们。" * 12
    events = [
        SceneAudioEvent(
            kind="speech",
            anchor="during",
            speaker="女主",
            exact_text=exact_text,
            performance="落寞伤感，语速逐渐变慢，中间有明显停顿",
        )
    ]

    result = compiler.compile_events(
        events,
        voice_profiles=[SceneVoiceProfile("女主", "青年女子，音调偏低，有些沙哑")],
    )

    assert result.requires_split is True
    assert result.split_reason == "prompt_exceeds_budget"
    assert exact_text in result.prompt
    assert result.expected_texts == (exact_text,)


def test_compiler_rejects_more_than_three_references() -> None:
    compiler = ScenePromptCompiler()
    events = [
        SceneAudioEvent(kind="speech", anchor="during", speaker=name, exact_text=f"{name}的台词。")
        for name in ("甲", "乙", "丙", "丁")
    ]
    voices = [
        SceneVoiceProfile(name, "清晰自然", {"speaker": f"speaker-{index}"})
        for index, name in enumerate(("甲", "乙", "丙", "丁"), start=1)
    ]

    with pytest.raises(ValueError, match="at most 3 references"):
        compiler.compile_events(events, voice_profiles=voices)


def test_compiler_emits_scene_state_and_deduplicates_contiguous_context() -> None:
    compiler = ScenePromptCompiler()
    segments = [
        ScriptSegment(
            type="narration",
            text="夜雨敲打着窗棂。",
            speaker="旁白",
            emotion="mysterious",
            instruct_scene="深夜木屋，窗外雨声持续，室内空旷而有轻微回响",
        ),
        ScriptSegment(
            type="dialogue",
            text="谁在外面？",
            speaker="沈砚",
            emotion="tense",
            instruct_scene="深夜木屋，窗外雨声持续，室内空旷而有轻微回响",
        ),
    ]

    result = compiler.compile_segments(segments)

    assert result.prompt.count("深夜木屋，窗外雨声持续") == 1
    assert result.prompt.index("深夜木屋") < result.prompt.index("夜雨敲打")
    assert "环境与空间状态切换为" in result.prompt


def test_compiler_preserves_seed_relative_timing_and_music_stop() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="停车！",
        speaker="女警察",
        emotion="angry",
        performance_notes="突然拔高音量，急促命令",
        sound_effects=[
            SoundEffect(
                name="一声尖锐的汽车刹车声",
                timing="after",
                delay=0.4,
                duration=2.5,
                fade_out=0.3,
            )
        ],
        music_cue=MusicCue(style="音乐停止"),
    )

    result = compiler.compile_segments([segment])

    assert "音乐停止" in result.prompt
    assert "音乐以音乐停止进入" not in result.prompt
    assert result.prompt.index("停车！") < result.prompt.index("汽车刹车声")
    assert "延后约0.4秒" in result.prompt
    assert "持续约2.5秒" in result.prompt
    assert "末尾约0.3秒淡出" in result.prompt


def test_compiler_orders_pre_scene_audio_before_speech() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="进来。",
        speaker="太后",
        emotion="cold",
        sound_effects=[
            SoundEffect(name="两声布鞋踏上木台阶", timing="before"),
            SoundEffect(
                name="殿外持续的风雨声",
                layer="bottom",
                timing="continuous",
                duration=12.0,
            ),
        ],
    )

    result = compiler.compile_segments([segment])

    assert result.prompt.index("布鞋踏上木台阶") < result.prompt.index("进来。")
    assert result.prompt.index("殿外持续的风雨声") < result.prompt.index("进来。")
    assert "持续到场景结束" in result.prompt


def test_compiler_deduplicates_unchanged_music_cues_across_segments() -> None:
    compiler = ScenePromptCompiler()
    cue = MusicCue(style="铜管低音与定音鼓营造压抑紧张氛围", fade_in=1.5)
    segments = [
        ScriptSegment(
            type="narration",
            text="卫兵押着俘虏走进大殿。",
            speaker="旁白",
            emotion="tense",
            music_cue=cue,
        ),
        ScriptSegment(
            type="dialogue",
            text="把头抬起来。",
            speaker="太后",
            emotion="cold",
            music_cue=cue,
        ),
    ]

    result = compiler.compile_segments(segments)

    assert result.prompt.count("铜管低音与定音鼓") == 1


# ---------- P3 叙事流编译风格（官方 seed-audio 示例对齐） ----------


def test_compiler_renders_narrative_flow_without_numbered_list() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="进来。",
        speaker="太后",
        emotion="cold",
        sound_effects=[SoundEffect(name="两声布鞋踏上木台阶", timing="before")],
    )

    result = compiler.compile_segments([segment])

    # 去掉编号清单，正文为连贯叙事行
    assert "1. " not in result.prompt
    lines = [line for line in result.prompt.splitlines() if "“进来。”" in line]
    assert len(lines) == 1
    # 前导音效内联到台词同句（官方风格：伴随X，{说话人}说道）
    assert "伴随着两声布鞋踏上木台阶，太后说道：“进来。”" in lines[0]


def test_compiler_anchors_after_sfx_and_stop_music_to_speech_line() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="停车！",
        speaker="女警察",
        emotion="angry",
        performance_notes="突然拔高音量，急促命令",
        sound_effects=[
            SoundEffect(
                name="一声尖锐的汽车刹车声",
                timing="after",
                delay=0.4,
            )
        ],
        music_cue=MusicCue(style="音乐停止"),
    )

    result = compiler.compile_segments([segment])

    lines = [line for line in result.prompt.splitlines() if "“停车！”" in line]
    assert len(lines) == 1
    line = lines[0]
    # 台词、随后音效、音乐停止动态锚定同句，顺序与叙事一致
    assert "随后是一声尖锐的汽车刹车声" in line
    assert "此时，音乐停止" in line
    assert line.index("停车！") < line.index("汽车刹车声") < line.index("音乐停止")


def test_compiler_inlines_during_sfx_into_speech_line() -> None:
    compiler = ScenePromptCompiler()
    segment = ScriptSegment(
        type="dialogue",
        text="谁在外头？",
        speaker="沈砚",
        emotion="tense",
        sound_effects=[SoundEffect(name="木门被缓缓推开的吱呀声", timing="trigger")],
    )

    result = compiler.compile_segments([segment])

    lines = [line for line in result.prompt.splitlines() if "“谁在外头？”" in line]
    assert len(lines) == 1
    assert "伴随木门被缓缓推开的吱呀声" in lines[0]
    assert "台词期间伴随" not in result.prompt
