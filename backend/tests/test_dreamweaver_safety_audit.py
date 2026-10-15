from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _build_audit_ctx(merged_video: Path, *, qc_config: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        payload={
            "merged_video": str(merged_video),
            "qc_config": dict(qc_config or {}),
        }
    )


def test_auditor_skips_safety_audit_when_disabled(monkeypatch, tmp_path: Path) -> None:
    from agents import auditor

    merged_video = tmp_path / "merged.mp4"
    merged_video.write_bytes(b"x" * 2048)

    calls: list[dict] = []

    def _fake_analyze_video(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, data={"unsafe": True}, model_id=kwargs.get("model_id"))

    monkeypatch.setattr(auditor, "analyze_video", _fake_analyze_video)

    result = auditor.run(_build_audit_ctx(merged_video, qc_config={"enable_safety_audit": False}))

    assert result["pass"] is True
    assert result["failure_type"] is None
    assert result["issues"] == []
    assert result["safety_audit"]["enabled"] is False
    assert result["safety_audit"]["executed"] is False
    assert calls == []


def test_auditor_blocks_on_unsafe_video_when_policy_is_block(monkeypatch, tmp_path: Path) -> None:
    from agents import auditor

    merged_video = tmp_path / "merged.mp4"
    merged_video.write_bytes(b"x" * 2048)

    monkeypatch.setattr(auditor, "get_model_info", lambda model_id: {"id": model_id})
    monkeypatch.setattr(
        auditor,
        "analyze_video",
        lambda **kwargs: SimpleNamespace(
            success=True,
            data={
                "unsafe": True,
                "categories": ["violence"],
                "severity": "high",
                "summary": "包含明显暴力伤害镜头",
                "issues": ["出现血腥和暴力伤害内容"],
            },
            model_id=kwargs.get("model_id"),
            metadata={},
            error=None,
            error_code=None,
            message="",
        ),
    )

    result = auditor.run(
        _build_audit_ctx(
            merged_video,
            qc_config={
                "enable_safety_audit": True,
                "safety_vlm_adapter": "qwen3.8-omni-flash",
                "safety_fail_policy": "block",
            },
        )
    )

    assert result["pass"] is False
    assert result["failure_type"] == "safety_audit_failed"
    assert result["safety_audit"]["enabled"] is True
    assert result["safety_audit"]["executed"] is True
    assert result["safety_audit"]["unsafe"] is True
    assert result["safety_audit"]["blocked"] is True
    assert result["safety_audit"]["categories"] == ["violence"]
    assert result["safety_audit"]["severity"] == "high"
    assert result["issues"][-1]["category"] == "safety"


def test_state_machine_review_fails_fast_when_safety_audit_blocks(monkeypatch) -> None:
    from pipeline import state_machine

    autoqc_calls: list[dict] = []

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": False,
            "issues": [{"category": "safety", "message": "unsafe video"}],
            "failure_type": "safety_audit_failed",
            "safety_audit": {
                "enabled": True,
                "executed": True,
                "unsafe": True,
                "blocked": True,
                "fail_policy": "block",
                "summary": "unsafe video",
                "issues": ["unsafe video"],
                "categories": ["violence"],
                "severity": "high",
            },
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: autoqc_calls.append(dict(payload)) or {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(run_id="dw_safety_block_001", state=state_machine.State.REVIEW, payload={})
    result = state_machine.step(ctx)

    assert result.state == state_machine.State.FAILED
    assert result.payload["rework_reason"]["type"] == "safety_audit_failed"
    assert result.payload["error"] == "unsafe video"
    assert result.payload["error_type"] == "SafetyAuditFailed"
    assert result.payload["autoqc"]["skipped"] is True
    assert autoqc_calls == []


def test_state_machine_review_keeps_pipeline_done_when_safety_audit_is_warn_only(monkeypatch) -> None:
    from pipeline import state_machine

    autoqc_calls: list[dict] = []

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": True,
            "issues": [],
            "failure_type": None,
            "safety_audit": {
                "enabled": True,
                "executed": True,
                "unsafe": True,
                "blocked": False,
                "fail_policy": "warn",
                "summary": "warn only",
                "issues": ["warn only"],
                "categories": ["violence"],
                "severity": "high",
            },
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: autoqc_calls.append(dict(payload)) or {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(run_id="dw_safety_warn_001", state=state_machine.State.REVIEW, payload={})
    result = state_machine.step(ctx)

    assert result.state == state_machine.State.DONE
    assert len(autoqc_calls) == 1
    assert result.payload["autoqc"]["pass"] is True


def test_state_machine_review_routes_output_audit_failure_to_video_rework(monkeypatch) -> None:
    from pipeline import state_machine

    autoqc_calls: list[dict] = []

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": False,
            "issues": [{"category": "output", "message": "merged_video missing"}],
            "failure_type": "output_audit_failed",
            "safety_audit": {"enabled": False, "executed": False},
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: autoqc_calls.append(dict(payload)) or {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(run_id="dw_output_audit_001", state=state_machine.State.REVIEW, payload={})
    result = state_machine.step(ctx)

    assert result.state == state_machine.State.REWORK
    assert len(autoqc_calls) == 1
    assert result.payload["rework_reason"]["type"] == "output_audit_failed"
    assert result.payload["rework_route"]["target_state"] == "VIDEO"
    assert result.payload["rework_route"]["action"] == "rerun_video"
    assert result.payload["rework_route"]["reason"] == "output_audit_failed"


def test_state_machine_review_routes_output_audit_failure_to_edit_remerge_when_clips_are_complete(monkeypatch) -> None:
    from pipeline import state_machine

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": False,
            "issues": [{"category": "output", "message": "merged_video too small"}],
            "failure_type": "output_audit_failed",
            "safety_audit": {"enabled": False, "executed": False},
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(
        run_id="dw_output_audit_edit_001",
        state=state_machine.State.REVIEW,
        payload={
            "storyboard": [
                {"shot_id": "shot_001"},
                {"shot_id": "shot_002"},
            ],
            "video_clips": [
                {"path": "runs/demo/shot_001.mp4"},
                {"path": "runs/demo/shot_002.mp4"},
            ],
            "merged_video": "runs/demo/merged.mp4",
        },
    )

    result = state_machine.step(ctx)

    assert result.state == state_machine.State.REWORK
    assert result.payload["rework_reason"]["type"] == "output_audit_failed"
    assert result.payload["rework_route"]["target_state"] == "EDIT"
    assert result.payload["rework_route"]["action"] == "rebuild_merged_video"
    assert result.payload["rework_route"]["reason"] == "output_audit_failed"
    assert "patch" not in result.payload["rework_route"]


def test_state_machine_rework_applies_output_audit_edit_route_without_dropping_clips(monkeypatch) -> None:
    from pipeline import state_machine

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": False,
            "issues": [{"category": "output", "message": "merged_video file missing"}],
            "failure_type": "output_audit_failed",
            "safety_audit": {"enabled": False, "executed": False},
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: {"pass": True, "failures": [], "route": None},
    )

    payload = {
        "storyboard": [
            {"shot_id": "shot_001"},
            {"shot_id": "shot_002"},
        ],
        "video_clips": [
            {"path": "runs/demo/shot_001.mp4"},
            {"path": "runs/demo/shot_002.mp4"},
        ],
        "merged_video": "runs/demo/merged.mp4",
        "video_edit_attempted_shot_ids": ["shot_001"],
    }
    ctx = state_machine.RunContext(
        run_id="dw_output_audit_edit_002",
        state=state_machine.State.REVIEW,
        payload=payload,
    )

    review_result = state_machine.step(ctx)

    assert review_result.state == state_machine.State.REWORK
    assert review_result.payload["rework_route"]["target_state"] == "EDIT"

    rework_result = state_machine.step(review_result)

    assert rework_result.state == state_machine.State.EDIT
    assert "merged_video" not in rework_result.payload
    assert rework_result.payload["video_clips"] == payload["video_clips"]
    assert rework_result.payload["video_edit_attempted_shot_ids"] == ["shot_001"]
    assert "regenerate_shot_ids" not in rework_result.payload


def test_state_machine_rework_applies_output_audit_video_route_with_regen_shots_when_clips_incomplete(monkeypatch) -> None:
    from pipeline import state_machine

    monkeypatch.setattr(
        state_machine.auditor,
        "run",
        lambda ctx: {
            "pass": False,
            "issues": [{"category": "output", "message": "merged_video missing"}],
            "failure_type": "output_audit_failed",
            "safety_audit": {"enabled": False, "executed": False},
        },
    )
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(
        run_id="dw_output_audit_002",
        state=state_machine.State.REVIEW,
        payload={
            "storyboard": [
                {"shot_id": "shot_001"},
                {"shot_id": "shot_002"},
                {"shot_id": "shot_003"},
            ],
            "video_clips": [
                {"path": "runs/demo/shot_001.mp4"},
                {"path": "runs/demo/shot_002.mp4"},
            ],
            "merged_video": "runs/demo/merged.mp4",
            "video_edit_attempted_shot_ids": ["shot_001", "shot_002"],
            "video_edit_failed_shot_ids": ["shot_001"],
        },
    )

    review_result = state_machine.step(ctx)

    assert review_result.state == state_machine.State.REWORK
    assert review_result.payload["rework_route"]["patch"]["regenerate_shot_ids"] == ["shot_001"]

    rework_result = state_machine.step(review_result)

    assert rework_result.state == state_machine.State.VIDEO
    assert rework_result.payload["regenerate_shot_ids"] == ["shot_001"]
    assert "merged_video" not in rework_result.payload
    assert rework_result.payload["video_clips"] == [{"path": "runs/demo/shot_002.mp4"}]
    assert rework_result.payload["video_edit_attempted_shot_ids"] == ["shot_002"]
    assert "video_edit_failed_shot_ids" not in rework_result.payload
