from __future__ import annotations

import sys
from pathlib import Path

# 让测试可以 import backend/app 下的包（app.*）
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from pipeline.state_machine import State  # noqa: E402
from app.tasks.dreamweaver_tasks import _artifact_summary, _stage_artifacts  # noqa: E402


def test_artifact_summary_includes_last_paths_and_rework_reason():
    payload = {
        "plan": {"text": "x"},
        "storyboard": [{"shot_id": "1"}, {"shot_id": "2"}],
        "keyframes": [{"path": "runs/r1/a.png"}, {"path": "runs/r1/b.png"}],
        "midframes": [{"path": "runs/r1/m.png"}],
        "video_clips": [{"path": "runs/r1/1.mp4"}, {"path": "runs/r1/2.mp4"}],
        "merged_video": "runs/r1/merged.mp4",
        "audit": {"pass": False, "issues": [{"x": 1}]},
        "rework_reason": {"type": "audit_failed", "issues": [{"x": 1}]},
    }

    summary = _artifact_summary(payload)
    assert summary["has_plan"] is True
    assert summary["storyboard_count"] == 2
    assert summary["keyframes_count"] == 2
    assert summary["last_keyframe_path"] == "runs/r1/b.png"
    assert summary["keyframes_tail_paths"] == ["runs/r1/a.png", "runs/r1/b.png"]
    assert summary["midframes_count"] == 1
    assert summary["last_midframe_path"] == "runs/r1/m.png"
    assert summary["midframes_tail_paths"] == ["runs/r1/m.png"]
    assert summary["video_clips_count"] == 2
    assert summary["last_video_clip_path"] == "runs/r1/2.mp4"
    assert summary["video_clips_tail_paths"] == ["runs/r1/1.mp4", "runs/r1/2.mp4"]
    assert summary["merged_video"] == "runs/r1/merged.mp4"
    assert summary["audit_pass"] is False
    assert summary["rework_reason"] == {"type": "audit_failed", "issues": [{"x": 1}]}


def test_stage_artifacts_include_paths_for_current_stage():
    payload = {
        "keyframes": [{"path": "runs/r1/a.png"}, {"path": "runs/r1/b.png"}],
    }
    stage = _stage_artifacts(State.KEYFRAMES, payload)
    assert stage["stage"] == "keyframes"
    assert stage["keyframes_paths"] == ["runs/r1/a.png", "runs/r1/b.png"]
