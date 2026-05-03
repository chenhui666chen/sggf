from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.audiobook.failure_diagnostics import (  # noqa: E402
    attach_failure_diagnostic_to_checkpoint_patch,
    build_chapter_failure_diagnostic,
    clip_text_preview,
)


def test_failure_diagnostic_maps_render_chunk_to_source_segment():
    script_segments = [
        {
            "type": "narration",
            "speaker": "旁白",
            "emotion": "neutral",
            "text": "星河在舷窗外缓慢旋转。",
            "voice_params": {"voice_id": "narrator_voice"},
        },
        {
            "type": "dialogue",
            "speaker": "林澈",
            "emotion": "fearful",
            "text": "等等，推进器的温度还在升高。",
            "voice_params": {"speaker": "lin_voice"},
        },
    ]
    result = {
        "task_id": "task_123",
        "error": "TTS provider returned empty audio",
        "temp_segment_cache": {
            "cached_audio_paths": {
                "0": "segment_0.mp3",
                "1": "segment_1.mp3",
            },
            "render_chunk_count": 3,
            "render_plan": [
                {"index": 0, "source_segment_indices": [0]},
                {"index": 1, "source_segment_indices": [1]},
                {"index": 2, "source_segment_indices": [1]},
            ],
        },
    }

    diagnostic = build_chapter_failure_diagnostic(
        stage="audio_from_scripts",
        chapter_id=7,
        chapter_title="失控推进器",
        chapter_number=3,
        script_segments=script_segments,
        result=result,
    )

    assert diagnostic["stage"] == "audio_from_scripts"
    assert diagnostic["chapter_id"] == 7
    assert diagnostic["failed_render_chunk_index"] == 2
    assert diagnostic["failed_segment_index"] == 1
    assert diagnostic["failed_source_segment_indices"] == [1]
    assert diagnostic["completed_segment_count"] == 2
    assert diagnostic["cached_segment_count"] == 2
    assert diagnostic["total_segment_count"] == 3
    assert diagnostic["failed_segment"] == {
        "index": 1,
        "speaker": "林澈",
        "emotion": "fearful",
        "type": "dialogue",
        "text_preview": "等等，推进器的温度还在升高。",
        "voice_id": "lin_voice",
    }
    assert diagnostic["engine_task_id"] == "task_123"
    assert diagnostic["error_message"] == "TTS provider returned empty audio"


def test_failure_diagnostic_uses_exception_type_and_object_segments():
    script_segments = [
        SimpleNamespace(
            type="narration",
            speaker="旁白",
            emotion="neutral",
            text="A" * 220,
            voice_params={"speaker_id": "voice-a"},
        )
    ]

    diagnostic = build_chapter_failure_diagnostic(
        stage="full",
        chapter_id=1,
        script_segments=script_segments,
        exception=RuntimeError("mixer failed"),
        resume_checkpoint={"total_segments": 1},
    )

    assert diagnostic["error_type"] == "RuntimeError"
    assert diagnostic["error_message"] == "mixer failed"
    assert diagnostic["failed_render_chunk_index"] == 0
    assert diagnostic["failed_segment"]["voice_id"] == "voice-a"
    assert diagnostic["failed_segment"]["text_preview"] == ("A" * 160) + "..."


def test_attach_failure_diagnostic_merges_failed_segment_indices():
    diagnostic = {
        "failed_render_chunk_index": 2,
        "error_message": "failed",
    }

    patch = attach_failure_diagnostic_to_checkpoint_patch(
        {"failed_segment_indices": [1, "2"], "engine_task_id": "task_123"},
        diagnostic,
    )

    assert patch["failure_diagnostic"] == diagnostic
    assert patch["failed_segment_indices"] == [1, 2]
    assert patch["engine_task_id"] == "task_123"


def test_clip_text_preview_normalizes_whitespace_and_clips():
    assert clip_text_preview("  第一行\n\n第二行  ", max_chars=20) == "第一行 第二行"
    assert clip_text_preview("abcdef", max_chars=3) == "abc..."
