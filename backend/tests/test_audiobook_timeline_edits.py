import pytest

from app.services.audiobook.engine_pkg._timeline_mixin import TimelineMixin


class TimelineHarness(TimelineMixin):
    def __init__(self):
        self._last_effect_timeline = None
        self._last_music_timeline = None


def test_apply_editor_timeline_edits_maps_ui_units_to_actual_seconds():
    harness = TimelineHarness()
    harness._last_effect_timeline = {
        "timeline": [
            {
                "scene_id": "scene_0",
                "timestamp": 0.0,
                "duration": 2.0,
                "description": "door",
            },
            {
                "scene_id": "scene_1",
                "timestamp": 5.0,
                "duration": 2.0,
                "description": "wind",
            },
        ],
    }
    harness._last_music_timeline = {
        "timeline": [
            {
                "scene_id": "scene_0",
                "timestamp": 0.0,
                "duration": 8.0,
                "description": "theme",
            },
        ],
    }

    harness._apply_editor_timeline_edits(
        {
            "sfx-0-0": {"startUnit": 50, "durationUnits": 25, "volume": 0.35},
            "music-0-1": {"startUnit": 25, "durationUnits": 125, "volume": 0.18},
            "script-voice-0": {"startUnit": 0, "durationUnits": 999},
            "sfx-99-0": {"startUnit": 10, "durationUnits": 20},
        },
        segment_units=[100, 100],
        actual_durations=[4.0, 6.0],
    )

    edited_effect = harness._last_effect_timeline["timeline"][0]
    untouched_effect = harness._last_effect_timeline["timeline"][1]
    edited_music = harness._last_music_timeline["timeline"][0]

    assert edited_effect["timestamp"] == pytest.approx(2.0)
    assert edited_effect["duration"] == pytest.approx(1.0)
    assert edited_effect["volume"] == pytest.approx(0.35)
    assert edited_effect["editor_timeline_key"] == "sfx-0-0"

    assert untouched_effect["timestamp"] == pytest.approx(5.0)
    assert untouched_effect.get("editor_timeline_key") is None

    assert edited_music["timestamp"] == pytest.approx(1.0)
    assert edited_music["duration"] == pytest.approx(6.0)
    assert edited_music["volume"] == pytest.approx(0.18)
    assert edited_music["editor_timeline_key"] == "music-0-1"


def test_apply_editor_timeline_edits_ignores_invalid_payloads():
    harness = TimelineHarness()
    harness._last_effect_timeline = {
        "timeline": [
            {"scene_id": "scene_0", "timestamp": 0.0, "duration": 2.0},
        ],
    }

    harness._apply_editor_timeline_edits(
        {
            "sfx-0-0": {"startUnit": -1, "durationUnits": 25},
            "music-0-0": {"startUnit": 0, "durationUnits": 0},
            "bad": {"startUnit": 0, "durationUnits": 25},
        },
        segment_units=[100],
        actual_durations=[4.0],
    )

    assert harness._last_effect_timeline["timeline"][0] == {
        "scene_id": "scene_0",
        "timestamp": 0.0,
        "duration": 2.0,
    }


def test_realign_mixed_timing_moves_automatic_effects_after_inserted_pause():
    harness = TimelineHarness()
    harness._last_effect_timeline = {
        "timeline": [
            {"scene_id": "scene_1", "timestamp": 1.0, "duration": 0.5},
        ],
    }
    harness._last_music_timeline = {"timeline": []}
    segments = [
        type("Segment", (), {"text": "第一句。"})(),
        type("Segment", (), {"text": "第二句。"})(),
    ]
    mixer_segments = [
        type("Chunk", (), {"source_segment_indices": [0]})(),
        type("Chunk", (), {"source_segment_indices": [1]})(),
    ]
    harness._estimate_segment_durations = lambda values: [1.0 for _ in values]

    harness._realign_timelines_with_mixed_timing(
        segments,
        mixer_segments,
        [
            {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
            {"index": 1, "start": 1.82, "end": 2.82, "duration": 1.0},
        ],
    )

    assert harness._last_effect_timeline["timeline"][0]["timestamp"] == pytest.approx(1.82)


def test_realign_mixed_timing_uses_source_indices_when_a_render_chunk_has_no_audio():
    harness = TimelineHarness()
    harness._last_effect_timeline = {
        "timeline": [
            {"scene_id": "scene_2", "timestamp": 2.0, "duration": 0.5},
        ],
    }
    harness._last_music_timeline = {"timeline": []}
    segments = [
        type("Segment", (), {"text": "第一句。"})(),
        type("Segment", (), {"text": "失败的第二句。"})(),
        type("Segment", (), {"text": "第三句。"})(),
    ]
    mixer_segments = [
        type("Chunk", (), {"source_segment_indices": [0]})(),
        type("Chunk", (), {"source_segment_indices": [1]})(),
        type("Chunk", (), {"source_segment_indices": [2]})(),
    ]
    harness._estimate_segment_durations = lambda values: [1.0 for _ in values]

    harness._realign_timelines_with_mixed_timing(
        segments,
        mixer_segments,
        [
            {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
            {"index": 2, "start": 2.15, "end": 3.15, "duration": 1.0},
        ],
    )

    assert harness._last_effect_timeline["timeline"][0]["timestamp"] == pytest.approx(2.15)


def test_realign_mixed_timing_keeps_manual_editor_position_authoritative():
    harness = TimelineHarness()
    harness._last_effect_timeline = {
        "timeline": [
            {
                "scene_id": "scene_1",
                "timestamp": 9.5,
                "duration": 0.5,
                "editor_timeline_key": "sfx-1-0",
            },
        ],
    }
    harness._last_music_timeline = {"timeline": []}
    segments = [
        type("Segment", (), {"text": "第一句。"})(),
        type("Segment", (), {"text": "第二句。"})(),
    ]
    mixer_segments = [
        type("Chunk", (), {"source_segment_indices": [0]})(),
        type("Chunk", (), {"source_segment_indices": [1]})(),
    ]
    harness._estimate_segment_durations = lambda values: [1.0 for _ in values]

    harness._realign_timelines_with_mixed_timing(
        segments,
        mixer_segments,
        [
            {"index": 0, "start": 0.0, "end": 1.0, "duration": 1.0},
            {"index": 1, "start": 1.82, "end": 2.82, "duration": 1.0},
        ],
    )

    assert harness._last_effect_timeline["timeline"][0]["timestamp"] == pytest.approx(9.5)


def test_realign_environment_cue_stays_within_its_scene():
    """剧本标注的场景环境音只覆盖所属场景+宽限，不被拉伸到章尾。"""
    harness = TimelineHarness()
    timeline = {
        "timeline": [
            {
                "scene_id": "scene_0",
                "timestamp": 0.5,
                "duration": 2.0,
                "type": "environment",
                "loop": True,
            },
        ],
    }

    result = harness._align_timeline_with_audio(
        timeline,
        estimated_offsets=[{"start": 0.0, "duration": 1.0}, {"start": 1.0, "duration": 1.0}],
        actual_offsets=[{"start": 0.0, "duration": 4.0}, {"start": 4.0, "duration": 60.0}],
        total_actual_duration=64.0,
        align_environment=True,
    )

    item = result["timeline"][0]
    assert item["timestamp"] == pytest.approx(0.5)
    # 所属场景 4s + 5s 宽限，而非 64s 章尾
    assert item["duration"] == pytest.approx(4.0 + 5.0 - 0.5)
    assert item["loop"] is True


def test_realign_ambient_bed_still_covers_full_chapter():
    """全章环境床（scene_id=ambient）保持覆盖到章节结尾的行为。"""
    harness = TimelineHarness()
    timeline = {
        "timeline": [
            {
                "scene_id": "ambient",
                "timestamp": 0.0,
                "duration": 10.0,
                "type": "environment",
                "loop": True,
            },
        ],
    }

    result = harness._align_timeline_with_audio(
        timeline,
        estimated_offsets=[{"start": 0.0, "duration": 1.0}],
        actual_offsets=[{"start": 0.0, "duration": 64.0}],
        total_actual_duration=64.0,
        align_environment=True,
    )

    assert result["timeline"][0]["duration"] == pytest.approx(64.0)
