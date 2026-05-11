from __future__ import annotations

from types import SimpleNamespace

from app.services.audiobook.pause_tags import (
    DEFAULT_BREAK_MS,
    DEFAULT_PARAGRAPH_PAUSE_MS,
    DEFAULT_PAUSE_MS,
    MAX_PAUSE_MS,
    split_pause_tag_text,
    strip_pause_tags,
    strip_spoken_pause_directives,
)
from app.services.audiobook.render_plan import build_render_plan


def test_strip_pause_tags_removes_bracket_tags_and_uses_defaults():
    pause_result = strip_pause_tags("他停下[pause]继续说。")
    break_result = strip_pause_tags("门外一响。[break]她回过头。")

    assert pause_result.text == "他停下继续说。"
    assert pause_result.pause_after_ms == DEFAULT_PAUSE_MS
    assert pause_result.applied is True
    assert break_result.text == "门外一响。她回过头。"
    assert break_result.pause_after_ms == DEFAULT_BREAK_MS


def test_strip_pause_tags_accepts_percent_paragraph_pause_marker():
    result = strip_pause_tags("第一段%P%第二段")

    assert result.text == "第一段第二段"
    assert result.pause_after_ms == DEFAULT_PARAGRAPH_PAUSE_MS
    assert result.applied is True


def test_strip_pause_tags_parses_seconds_ms_and_ssml_break():
    assert strip_pause_tags("A[pause:2.5]B").pause_after_ms == 2500
    assert strip_pause_tags("A[pause:2000ms]B").pause_after_ms == 2000
    assert strip_pause_tags("A<break time=\"750ms\"/>B").pause_after_ms == 750
    assert strip_pause_tags("A<break time='3s'></break>B").pause_after_ms == 3000


def test_strip_pause_tags_uses_largest_pause_and_clamps_duration():
    result = strip_pause_tags("A[pause:2]B[pause:60s]C[break]")

    assert result.text == "A B C"
    assert result.pause_after_ms == MAX_PAUSE_MS


def test_strip_pause_tags_removes_spoken_pause_directives():
    result = strip_pause_tags("必须走。（停顿一秒）继续。")

    assert result.text == "必须走。继续。"
    assert result.pause_after_ms == 1000
    assert result.applied is True


def test_strip_pause_tags_splits_standalone_spoken_pause_directives():
    parts = split_pause_tag_text("必须走。停顿三秒。继续。")

    assert [(part.text, part.pause_after_ms) for part in parts] == [
        ("必须走。", 3000),
        ("继续。", None),
    ]


def test_strip_pause_tags_does_not_remove_narrative_pause_verbs():
    result = strip_pause_tags("他停顿了一下，才开口。")

    assert result.text == "他停顿了一下，才开口。"
    assert result.pause_after_ms is None
    assert result.applied is False


def test_strip_spoken_pause_directives_preserves_structural_pause_tags():
    result = strip_spoken_pause_directives("他停下[pause:2s]继续说。（停顿一秒）")

    assert result.text == "他停下[pause:2s]继续说。"
    assert result.pause_after_ms == 1000
    assert result.applied is True


def test_split_pause_tag_text_keeps_internal_pause_position():
    parts = split_pause_tag_text("她停下[pause:2]继续说。[break]门外一响。")

    assert [(part.text, part.pause_after_ms) for part in parts] == [
        ("她停下", 2000),
        ("继续说。", DEFAULT_BREAK_MS),
        ("门外一响。", None),
    ]


def test_render_plan_strips_pause_tags_before_tts_and_records_pause_override():
    segment = SimpleNamespace(
        text="她没有立刻回答。[pause:2]只是看着窗外。",
        speaker="旁白",
        emotion="neutral",
        performance_notes="压低声音",
        voice_params={"speaker": "voice-a", "pause_after": 0.3},
        type="narration",
    )

    chunks = build_render_plan([segment])

    assert len(chunks) == 2
    assert chunks[0].text == "她没有立刻回答。"
    assert chunks[0].voice_params["pause_after_ms"] == 2000
    assert chunks[0].voice_params["pause_tag_applied"] is True
    assert chunks[0].voice_params["original_tts_text"] == segment.text
    assert chunks[0].voice_params["performance_notes"] == "压低声音"
    assert chunks[1].text == "只是看着窗外。"
    assert "pause_after_ms" not in chunks[1].voice_params
