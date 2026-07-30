from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.audiobook.scene_engine.models import SceneVoiceProfile
from app.services.audiobook.scene_engine.planner import ScenePlanner
from app.services.audiobook.scene_engine.voice_reference_resolver import VoiceReferenceResolver
from app.services.audiobook.script_adapter_pkg._dataclasses import ScriptSegment


def _dialogue(speaker: str, text: str) -> ScriptSegment:
    return ScriptSegment(
        type="dialogue",
        text=text,
        speaker=speaker,
        emotion="tense",
        performance_notes="紧张、清晰，保持角色身份",
    )


def test_scene_planner_splits_before_fourth_stable_reference() -> None:
    planner = ScenePlanner()
    names = ("旁白", "太后", "御医", "俘虏")
    segments = [_dialogue(name, f"{name}正在推进当前剧情，这句台词必须完整保留。") for name in names]
    voices = [
        SceneVoiceProfile(name, "清晰且可辨识", {"speaker": f"seed-{index}"})
        for index, name in enumerate(names, start=1)
    ]

    plans = planner.plan(
        segments,
        voice_profiles=voices,
        scene_description="宫殿内殿，气氛紧张",
    )

    assert [plan.source_segment_indices for plan in plans] == [(0, 1, 2), (3,)]
    assert all(len(plan.references) <= 3 for plan in plans)
    assert [plan.scene_id for plan in plans] == ["scene_0001", "scene_0002"]
    assert plans[0].speaker_names == ("旁白", "太后", "御医")
    assert "俘虏" not in plans[0].prompt
    assert "俘虏正在推进当前剧情" in plans[1].expected_text


def test_scene_planner_keeps_regular_scenes_near_target_duration() -> None:
    planner = ScenePlanner()
    segments = [
        ScriptSegment(
            type="narration",
            text=f"第{index}段" + "风声压过巷口，脚步贴着墙根追来。" * 8,
            speaker="旁白",
            emotion="tense",
            performance_notes="低沉克制，保持推进感",
        )
        for index in range(1, 7)
    ]

    plans = planner.plan(
        segments,
        voice_profiles=[SceneVoiceProfile("旁白", "沉稳克制", {"speaker": "narrator"})],
    )

    assert [len(plan.source_segment_indices) for plan in plans] == [2, 2, 2]
    assert all(45 <= plan.expected_duration_s <= 75 for plan in plans)
    assert tuple(index for plan in plans for index in plan.source_segment_indices) == tuple(range(6))


def test_scene_planner_preserves_expected_vocalizations_from_compiled_events() -> None:
    planner = ScenePlanner(
        target_min_duration_s=1,
        target_max_duration_s=30,
        soft_max_duration_s=60,
        hard_max_duration_s=90,
    )
    segments = [
        ScriptSegment(
            type="dialogue",
            text="我不会答应你。",
            speaker="女主",
            emotion="afraid",
            performance_notes="声音哽咽，期间带着急促喘息",
        )
    ]

    plan = planner.plan(segments)[0]

    assert plan.expected_vocalizations == ("哽咽", "喘息")


def test_scene_planner_avoids_recompiling_every_short_candidate() -> None:
    planner = ScenePlanner(
        target_min_duration_s=10000,
        target_max_duration_s=20000,
        soft_max_duration_s=30000,
        hard_max_duration_s=40000,
        prompt_max_chars=100000,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text=f"第{index}段风吹过长街。",
            speaker="旁白",
            emotion="neutral",
        )
        for index in range(120)
    ]
    compile_calls = 0
    original_compile = planner.compiler.compile_segments

    def count_compile(*args, **kwargs):
        nonlocal compile_calls
        compile_calls += 1
        return original_compile(*args, **kwargs)

    planner.compiler.compile_segments = count_compile

    plans = planner.plan(segments)

    assert len(plans) == 1
    assert plans[0].source_segment_indices == tuple(range(120))
    assert compile_calls <= 2


def test_scene_planner_splits_at_explicit_scene_change_after_minimum_duration() -> None:
    planner = ScenePlanner(
        target_min_duration_s=10,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="宫灯下，侍从垂手等候。",
            speaker="旁白",
            emotion="tense",
            pause_after=5,
            instruct_scene="深夜宫殿内殿",
        ),
        ScriptSegment(
            type="dialogue",
            text="太后抬起头，冷冷问道：人带来了吗？",
            speaker="太后",
            emotion="tense",
            pause_after=5,
            instruct_scene="深夜宫殿内殿",
        ),
        ScriptSegment(
            type="narration",
            text="天色微明，城门在晨雾中缓缓开启。",
            speaker="旁白",
            emotion="calm",
            instruct_scene="清晨城门",
        ),
    ]

    plans = planner.plan(segments)

    assert [plan.source_segment_indices for plan in plans] == [(0, 1), (2,)]


def test_scene_planner_keeps_short_scene_change_with_previous_context() -> None:
    planner = ScenePlanner(
        target_min_duration_s=20,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="他推开内殿的门。",
            speaker="旁白",
            emotion="tense",
            instruct_scene="深夜宫殿内殿",
        ),
        ScriptSegment(
            type="narration",
            text="门外已经是清晨，卫兵正列队换岗。",
            speaker="旁白",
            emotion="calm",
            instruct_scene="清晨城门",
        ),
    ]

    plans = planner.plan(segments)

    assert [plan.source_segment_indices for plan in plans] == [(0, 1)]


def test_scene_planner_splits_when_new_speaker_starts_new_emotion_phase() -> None:
    planner = ScenePlanner(
        target_min_duration_s=10,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="审讯室里只剩钟表的滴答声。",
            speaker="旁白",
            emotion="tense",
            pause_after=5,
        ),
        ScriptSegment(
            type="dialogue",
            text="男子压低声音，再次追问证据的下落。",
            speaker="男子1",
            emotion="tense",
            pause_after=5,
        ),
        ScriptSegment(
            type="dialogue",
            text="女子忽然笑了，平静地承认自己早已知情。",
            speaker="女子",
            emotion="relieved",
        ),
    ]

    plans = planner.plan(segments)

    assert [plan.source_segment_indices for plan in plans] == [(0, 1), (2,)]


def test_scene_planner_splits_at_music_phase_change_after_minimum_duration() -> None:
    planner = ScenePlanner(
        target_min_duration_s=10,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="雨声笼罩着空旷的站台。",
            speaker="旁白",
            emotion="sad",
            pause_after=5,
            music_cue_simple="低沉弦乐持续铺底",
        ),
        ScriptSegment(
            type="dialogue",
            text="她望向远处，轻声说自己不会再回来。",
            speaker="女主",
            emotion="sad",
            pause_after=5,
            music_cue_simple="低沉弦乐持续铺底",
        ),
        ScriptSegment(
            type="narration",
            text="列车驶入站台，铜管和鼓点骤然增强。",
            speaker="旁白",
            emotion="urgent",
            music_cue_simple="紧张铜管与鼓点渐强",
        ),
    ]

    plans = planner.plan(segments)

    assert [plan.source_segment_indices for plan in plans] == [(0, 1), (2,)]


def test_scene_planner_falls_back_single_segment_that_exceeds_prompt_budget() -> None:
    planner = ScenePlanner(prompt_max_chars=420)
    text = "她回忆起那个明晃晃的下午。" * 30
    segment = ScriptSegment(
        type="narration",
        text=text,
        speaker="旁白",
        emotion="sad",
        performance_notes="轻柔、伤感，语速逐渐变慢",
    )

    plans = planner.plan(
        [segment],
        voice_profiles=[SceneVoiceProfile("旁白", "低沉、略带沙哑", {"speaker": "narrator"})],
    )

    assert len(plans) == 1
    assert plans[0].render_mode == "legacy_stems"
    assert plans[0].fallback_reason == "prompt_exceeds_budget"
    assert plans[0].expected_text == text


def test_scene_planner_recompiles_existing_topology_with_materialized_reference() -> None:
    planner = ScenePlanner()
    segments = [_dialogue("女主", "雨落在窗台上，她终于说出了藏了多年的真相。")]
    topology_plan = planner.plan(
        segments,
        voice_profiles=[
            SceneVoiceProfile(
                "女主",
                "青年女性，低沉克制",
                {"audio_url": "https://assets.example/preview.mp3"},
            )
        ],
    )[0]

    final_plan = planner.recompile_plan(
        topology_plan,
        segments,
        voice_profiles=[
            SceneVoiceProfile(
                "女主",
                "青年女性，低沉克制",
                {"audio_data": "MATERIALIZED_AUDIO"},
            )
        ],
    )

    assert final_plan.scene_id == topology_plan.scene_id
    assert final_plan.source_segment_indices == topology_plan.source_segment_indices
    assert final_plan.references == ({"audio_data": "MATERIALIZED_AUDIO"},)
    assert final_plan.reference_hashes != topology_plan.reference_hashes


def test_scene_planner_splits_failed_plan_at_explicit_semantic_boundary() -> None:
    planner = ScenePlanner(
        target_min_duration_s=60,
        target_max_duration_s=100,
        soft_max_duration_s=110,
        hard_max_duration_s=120,
    )
    segments = [
        ScriptSegment(
            type="narration",
            text="内殿的烛火忽然熄灭。",
            speaker="旁白",
            emotion="tense",
            instruct_scene="深夜内殿",
        ),
        ScriptSegment(
            type="narration",
            text="城门外已经泛起晨光。",
            speaker="旁白",
            emotion="calm",
            instruct_scene="清晨城门",
        ),
        ScriptSegment(
            type="dialogue",
            text="卫兵抬手示意众人停下。",
            speaker="卫兵",
            emotion="calm",
            instruct_scene="清晨城门",
        ),
        ScriptSegment(
            type="narration",
            text="车队在薄雾中缓缓靠近。",
            speaker="旁白",
            emotion="calm",
            instruct_scene="清晨城门",
        ),
    ]
    plan = planner.plan(segments)[0]

    split_plans = planner.split_plan_once(plan, segments)

    assert [item.scene_id for item in split_plans] == [
        "scene_0001_split_01",
        "scene_0001_split_02",
    ]
    assert [item.source_segment_indices for item in split_plans] == [
        (0,),
        (1, 2, 3),
    ]


def test_voice_reference_resolver_rejects_other_provider_official_voice() -> None:
    resolver = VoiceReferenceResolver()

    with pytest.raises(ValueError, match="不接受其他供应商官方音色试听"):
        resolver.resolve(
            ["太后", "御医"],
            voice_mapping={
                "太后": {
                    "voice_id": "zh_female_vv_uranus_bigtts",
                    "tts_model": "seed-tts-2.0-expressive",
                    "voice_description": "55岁左右，端庄优雅、威严",
                },
                "御医": {
                    "voice_id": "Cherry",
                    "tts_model": "qwen3-tts-instruct-flash",
                    "voice_description": "中年男性，浑厚、略微沙哑",
                },
            },
        )


def test_voice_reference_resolver_keeps_doubao_clone_id_as_speaker() -> None:
    resolver = VoiceReferenceResolver()
    clone_speaker_id = "S_account_voice_clone_001"

    profiles = resolver.resolve(
        ["女主"],
        voice_mapping={
            "女主": {
                "voice_id": clone_speaker_id,
                "tts_model": "seed-tts-2.0-expressive",
                "preview_audio_url": "https://assets.example/tts-preview/clone.mp3",
            }
        },
    )

    assert profiles[0].provider_reference == {"speaker": clone_speaker_id}


def test_voice_reference_resolver_uses_audio_asset_for_other_tts_model() -> None:
    resolver = VoiceReferenceResolver()

    profiles = resolver.resolve(
        ["男主"],
        voice_mapping={
            "男主": {
                "voice_id": "cosyvoice-v3.5-plus-demo",
                "tts_model": "cosyvoice-v3.5-plus",
                "reference_audio_url": "https://assets.example/voices/male-lead.mp3",
                "reference_source": "user_private",
                "voice_description": "中年男性，港式普通话，低沉有力",
            }
        },
    )

    assert profiles == (
        SceneVoiceProfile(
            "男主",
            "中年男性，港式普通话，低沉有力",
            {"audio_url": "https://assets.example/voices/male-lead.mp3"},
        ),
    )


def test_voice_reference_resolver_uses_existing_preview_url_for_other_tts_model() -> None:
    resolver = VoiceReferenceResolver()

    profiles = resolver.resolve(
        ["御医"],
        voice_mapping={
            "御医": {
                "voice_id": "Cherry",
                "tts_model": "qwen3-tts-instruct-flash",
                "preview_audio_url": "https://assets.example/tts-preview/qwen-cherry.mp3",
                "reference_source": "user_private",
                "voice_description": "中年男性，浑厚、略微沙哑、谦逊",
            }
        },
    )

    assert profiles[0].provider_reference == {
        "audio_url": "https://assets.example/tts-preview/qwen-cherry.mp3"
    }


def test_voice_reference_resolver_uses_existing_preview_base64_for_other_tts_model() -> None:
    resolver = VoiceReferenceResolver()

    profiles = resolver.resolve(
        ["女主"],
        voice_mapping={
            "女主": {
                "voice_id": "male-qn-qingse",
                "tts_model": "MiniMax/speech-2.8-hd",
                "preview": {"blob": "data:audio/mpeg;base64,PREVIEW_AUDIO"},
                "reference_source": "user_private",
            }
        },
    )

    assert profiles[0].provider_reference == {"audio_data": "PREVIEW_AUDIO"}


def test_voice_reference_resolver_prefers_current_preview_over_legacy_reference() -> None:
    resolver = VoiceReferenceResolver()

    profiles = resolver.resolve(
        ["男子1"],
        voice_mapping={
            "男子1": {
                "voice_id": "Cherry",
                "tts_model": "qwen3-tts-instruct-flash",
                "reference_audio_url": "https://assets.example/legacy-reference.mp3",
                "preview_audio_url": "https://assets.example/current-preview.mp3",
                "reference_source": "user_private",
            }
        },
    )

    assert profiles[0].provider_reference == {
        "audio_url": "https://assets.example/current-preview.mp3"
    }
