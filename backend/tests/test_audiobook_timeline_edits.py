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
            "sfx-0-0": {"startUnit": 50, "durationUnits": 25},
            "music-0-1": {"startUnit": 25, "durationUnits": 125},
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
    assert edited_effect["editor_timeline_key"] == "sfx-0-0"

    assert untouched_effect["timestamp"] == pytest.approx(5.0)
    assert untouched_effect.get("editor_timeline_key") is None

    assert edited_music["timestamp"] == pytest.approx(1.0)
    assert edited_music["duration"] == pytest.approx(6.0)
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
