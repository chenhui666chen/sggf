from __future__ import annotations

from pathlib import Path

from pipeline.autoqc import run as autoqc_run


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_autoqc_pass_and_route(tmp_path: Path):
    run_dir = tmp_path / "runs" / "r1"
    _touch(run_dir / "S1-1_head.png")
    _touch(run_dir / "S1-1_tail.png")

    payload = {
        "storyboard": [
            {
                "scene_id": "S1",
                "shot_id": "S1-1",
                "desc": "shot",
                "duration_s": 3.0,
                "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
                "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
            }
        ],
        "keyframes": [
            {"path": str(run_dir / "S1-1_head.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}}},
            {"path": str(run_dir / "S1-1_tail.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}}},
        ],
    }

    report = autoqc_run(payload)
    assert report["pass"] is True
    assert report["route"] is None
    assert report["overall_score"] >= 0.9
    assert report["shots"]["S1-1"]["pass"] is True


def test_autoqc_missing_tail_routes_to_keyframes(tmp_path: Path):
    run_dir = tmp_path / "runs" / "r2"
    _touch(run_dir / "S1-1_head.png")

    payload = {
        "storyboard": [
            {
                "scene_id": "S1",
                "shot_id": "S1-1",
                "desc": "shot",
                "duration_s": 3.0,
                "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
                "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
            }
        ],
        "keyframes": [
            {"path": str(run_dir / "S1-1_head.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}}},
            {"path": str(run_dir / "S1-1_tail.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}}},
        ],
    }

    report = autoqc_run(payload)
    assert report["pass"] is False
    assert report["route"]["target_state"] == "STORYBOARD"
    assert "missing_tail_frame" in report["route"]["failure_types"]


def test_autoqc_continuity_break_routes_to_script(tmp_path: Path):
    run_dir = tmp_path / "runs" / "r3"
    for name in ("S1-1_head.png", "S1-1_tail.png", "S1-2_head.png", "S1-2_tail.png"):
        _touch(run_dir / name)

    payload = {
        "storyboard": [
            {
                "scene_id": "S1",
                "shot_id": "S1-1",
                "desc": "shot 1",
                "duration_s": 3.0,
                "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 0.0, "y": 0.0}},
                "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 0.0, "y": 0.0}},
            },
            {
                "scene_id": "S1",
                "shot_id": "S1-2",
                "desc": "shot 2",
                "duration_s": 3.0,
                "head_frame": {"prompt": "head", "ratio": "16:9", "subject_pos": {"x": 1.0, "y": 1.0}},
                "tail_frame": {"prompt": "tail", "ratio": "16:9", "subject_pos": {"x": 1.0, "y": 1.0}},
            },
        ],
        "keyframes": [
            {"path": str(run_dir / "S1-1_head.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.0, "y": 0.0}}},
            {"path": str(run_dir / "S1-1_tail.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 0.0, "y": 0.0}}},
            {"path": str(run_dir / "S1-2_head.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 1.0, "y": 1.0}}},
            {"path": str(run_dir / "S1-2_tail.png"), "ratio": "16:9", "spec": {"ratio": "16:9", "subject_pos": {"x": 1.0, "y": 1.0}}},
        ],
    }

    report = autoqc_run(payload)
    assert report["pass"] is False
    assert report["route"]["target_state"] == "SCRIPT"
    assert "cross_shot_continuity_break" in report["route"]["failure_types"]

