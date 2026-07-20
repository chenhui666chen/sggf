from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")


def _segment(
    text: str,
    *,
    speaker: str = "旁白",
    segment_type: str = "narration",
    emotion: str = "neutral",
    voice_params: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        speaker=speaker,
        type=segment_type,
        emotion=emotion,
        performance_notes="",
        voice_params=dict(voice_params or {}),
    )


def test_chapter_cadence_maps_story_transitions_to_explainable_timeline_pauses() -> None:
    from app.services.audiobook.chapter_cadence import apply_chapter_cadence

    segments = [
        _segment("雨停了，巷子里只剩水声。"),
        _segment("陆衍推开门。"),
        _segment("等等。", speaker="岑霜", segment_type="dialogue"),
        _segment("真相终于浮出水面。", emotion="surprised"),
        _segment("与此同时，巷口的灯全灭了。", emotion="mysterious"),
        _segment("他们谁也没有回头。"),
    ]

    apply_chapter_cadence(segments)

    assert segments[0].voice_params["cadence_profile"] == "continuation"
    assert segments[1].voice_params["cadence_profile"] == "speaker_turn"
    assert segments[2].voice_params["cadence_profile"] == "reveal"
    assert segments[3].voice_params["cadence_profile"] == "scene_transition"
    assert segments[0].voice_params["timeline_pause_after_ms"] < segments[1].voice_params["timeline_pause_after_ms"]
    assert segments[1].voice_params["timeline_pause_after_ms"] < segments[2].voice_params["timeline_pause_after_ms"]
    assert segments[2].voice_params["timeline_pause_after_ms"] < segments[3].voice_params["timeline_pause_after_ms"]
    assert "换人" in segments[1].voice_params["cadence_reason"]
    assert "揭示" in segments[2].voice_params["cadence_reason"]
    assert "转场" in segments[3].voice_params["cadence_reason"]
    assert "timeline_pause_after_ms" not in segments[-1].voice_params


def test_chapter_cadence_preserves_structural_pause_override_and_exposes_model_guidance() -> None:
    from app.services.audiobook.chapter_cadence import apply_chapter_cadence
    from app.services.audiobook.tts_delivery_plan import (
        build_delivery_plan,
        delivery_plan_instruction_parts,
    )

    segment = _segment(
        "门后没有人。",
        emotion="tense",
        voice_params={"pause_after_ms": 1250},
    )
    following = _segment("可脚步声还在靠近。", emotion="fearful")

    apply_chapter_cadence([segment, following])

    assert segment.voice_params["timeline_pause_after_ms"] == 1250
    assert segment.voice_params["cadence_profile"] == "explicit"
    assert segment.voice_params["cadence_reason"] == "保留结构化停顿标记"

    plan = build_delivery_plan(
        segment=segment,
        voice_params=segment.voice_params,
        model="qwen3-tts-instruct-flash",
        emotion="tense",
    )
    assert plan["timeline_pause_after_ms"] == 1250
    assert plan["cadence_profile"] == "explicit"
    assert any(part.startswith("剧情节奏：") for part in delivery_plan_instruction_parts(plan))


def test_chapter_cadence_keeps_script_pause_after_as_a_minimum_without_losing_story_beats() -> None:
    from app.services.audiobook.chapter_cadence import apply_chapter_cadence

    segments = [
        _segment("他放下了那封信。", voice_params={"pause_after": 1.2}),
        _segment("下一秒，门外传来急促的脚步声。"),
        _segment("与此同时，走廊尽头的灯灭了。"),
        _segment("谁也没有说话。"),
    ]

    apply_chapter_cadence(segments)

    assert segments[0].voice_params["timeline_pause_after_ms"] == 1200
    assert segments[0].voice_params["cadence_profile"] == "script_pause"
    assert segments[1].voice_params["timeline_pause_after_ms"] == 1050
    assert segments[1].voice_params["cadence_profile"] == "scene_transition"


def test_mixer_pause_builder_prefers_chapter_timeline_pause_without_reusing_tts_pause_after() -> None:
    from app.services.audiobook.engine_pkg._script_utils_mixin import ScriptUtilsMixin

    segments = [
        _segment(
            "真相浮出水面。",
            voice_params={
                "pause_after": 0.3,
                "timeline_pause_after_ms": 820,
            },
        ),
        _segment("下一句。", voice_params={"pause_after": 1.2}),
    ]

    pauses = ScriptUtilsMixin()._build_mixer_pause_after_ms(segments)

    assert pauses == [820, None]


def test_render_chunk_split_keeps_chapter_pause_only_on_the_final_chunk() -> None:
    from app.services.audiobook.render_plan import build_render_plan

    segment = _segment(
        "第一段旁白交代夜色压下来，巷子里只剩水声，陆衍没有回头。"
        "第二段旁白继续交代他握紧手里的信，脚步却越来越近，谁也不知道门后有什么。"
        "第三段旁白落在门锁轻响的一瞬，所有人都屏住了呼吸。",
        voice_params={
            "timeline_pause_after_ms": 920,
            "cadence_profile": "reveal",
            "cadence_reason": "揭示信息前后留白，给听众消化关键事实",
        },
    )

    chunks = build_render_plan([segment], max_chunk_chars=80)

    assert len(chunks) >= 2
    assert all("timeline_pause_after_ms" not in chunk.voice_params for chunk in chunks[:-1])
    assert chunks[-1].voice_params["timeline_pause_after_ms"] == 920


def test_tts_batch_item_keeps_chapter_pause_for_mixing_but_removes_provider_boundary_breaks() -> None:
    from app.services.audiobook.engine_pkg._tts_mixin import TTSMixin

    class DummyEngine(TTSMixin):
        tts_model = "qwen3-tts-instruct-flash"

    segment = _segment(
        "门后没有人。",
        voice_params={
            "timeline_boundary_managed": True,
            "timeline_pause_after_ms": 820,
            "pause_before": 0.4,
            "pause_after": 0.6,
        },
    )

    voice_params = DummyEngine()._build_tts_batch_item(segment)["voice_params"]

    assert voice_params["timeline_pause_after_ms"] == 820
    assert "pause_before" not in voice_params
    assert "pause_after" not in voice_params
