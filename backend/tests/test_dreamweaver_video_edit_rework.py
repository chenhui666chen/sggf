from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_autoqc_routes_video_clip_failure_to_edit_when_video_edit_enabled(monkeypatch) -> None:
    from pipeline.autoqc_pkg._routing import _route_from_failures
    from pipeline.autoqc_pkg._dataclasses import AutoQCFailure
    from adapters import adapter_helpers

    monkeypatch.setattr(adapter_helpers, "get_model_info", lambda model_id: {"id": model_id})

    failure = AutoQCFailure(
        failure_type="video_clip_quality_below_threshold",
        severity="hard",
        message="video clip vision review below threshold",
        shot_key="shot_001",
        meta={
            "path": "runs/demo/shot_001.mp4",
            "review_score": 5.9,
            "threshold": 7.0,
            "issues": ["画面抖动", "主体一致性不足"],
            "summary": "整体观感不稳定",
        },
    )
    route = _route_from_failures(
        failures=[failure],
        payload={
            "storyboard": [{"shot_id": "shot_001", "desc": "主角推门进入房间"}],
            "video_edit_config": {"enabled": True, "adapter": "wan3.0-video"},
        },
    )

    assert route is not None
    assert route.target_state == "EDIT"
    assert route.action == "repair_video_clips"
    assert route.patch["video_edit_config"]["adapter"] == "wan3.0-video"
    assert route.patch["video_edit_plan"]["target_shot_ids"] == ["shot_001"]
    assert route.patch["video_edit_plan"]["edit_feature"] == "video-remix"
    assert route.patch["video_edit_plan"]["items"][0]["issues"] == ["画面抖动", "主体一致性不足"]
    assert route.patch["video_edit_plan"]["items"][0]["edit_feature"] == "video-remix"
    assert route.patch["video_edit_plan"]["items"][0]["edit_feature_reason"] == "temporal_consistency_repair"


def test_autoqc_infers_video_extend_for_transition_break_issues(monkeypatch) -> None:
    from pipeline.autoqc_pkg._routing import _route_from_failures
    from pipeline.autoqc_pkg._dataclasses import AutoQCFailure
    from adapters import adapter_helpers

    monkeypatch.setattr(adapter_helpers, "get_model_info", lambda model_id: {"id": model_id})

    failure = AutoQCFailure(
        failure_type="video_clip_quality_below_threshold",
        severity="hard",
        message="video clip vision review below threshold",
        shot_key="shot_002",
        meta={
            "path": "runs/demo/shot_002.mp4",
            "review_score": 6.0,
            "threshold": 7.0,
            "issues": ["结尾截断", "首尾衔接不自然"],
            "summary": "片段收尾不完整，需要补足过渡",
        },
    )
    route = _route_from_failures(
        failures=[failure],
        payload={
            "storyboard": [{"shot_id": "shot_002", "desc": "主角转身离开房间"}],
            "video_edit_config": {"enabled": True, "adapter": "wan3.0-video"},
        },
    )

    assert route is not None
    assert route.target_state == "EDIT"
    assert route.patch["video_edit_plan"]["edit_feature"] == "video-extend"
    assert route.patch["video_edit_plan"]["items"][0]["edit_feature"] == "video-extend"
    assert route.patch["video_edit_plan"]["items"][0]["edit_feature_reason"] == "continuation_repair"


def test_autoqc_falls_back_to_video_when_shot_already_attempted_video_edit(monkeypatch) -> None:
    from pipeline.autoqc_pkg._routing import _route_from_failures
    from pipeline.autoqc_pkg._dataclasses import AutoQCFailure
    from adapters import adapter_helpers

    monkeypatch.setattr(adapter_helpers, "get_model_info", lambda model_id: {"id": model_id})

    failure = AutoQCFailure(
        failure_type="video_clip_quality_below_threshold",
        severity="hard",
        message="video clip vision review below threshold",
        shot_key="shot_001",
        meta={
            "path": "runs/demo/shot_001.mp4",
            "review_score": 5.9,
            "threshold": 7.0,
            "issues": ["画面抖动"],
            "summary": "整体观感不稳定",
        },
    )
    route = _route_from_failures(
        failures=[failure],
        payload={
            "video_edit_config": {"enabled": True, "adapter": "wan3.0-video"},
            "video_edit_attempted_shot_ids": ["shot_001"],
        },
    )

    assert route is not None
    assert route.target_state == "VIDEO"
    assert route.action == "rerun_video"


def test_editor_run_applies_video_edit_plan_and_replaces_clip(monkeypatch, tmp_path: Path) -> None:
    from agents import editor

    monkeypatch.chdir(tmp_path)

    run_id = "dw_edit_001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    clip_path = run_dir / "shot_001.mp4"
    clip_path.write_bytes(b"original-clip")
    head_path = run_dir / "shot_001_head.png"
    head_path.write_bytes(b"head")

    edit_calls: list[dict] = []

    def _fake_edit_video_request(**kwargs):
        edit_calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            data={"video_base64": base64.b64encode(b"edited-clip").decode("ascii")},
            outputs=[],
            model_id=kwargs.get("model_id"),
            error=None,
        )

    def _fake_run_ffmpeg(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"merged-video")

    monkeypatch.setattr(editor, "_run_video_edit_request", _fake_edit_video_request)
    monkeypatch.setattr(editor, "_run_ffmpeg", _fake_run_ffmpeg)

    ctx = SimpleNamespace(
        run_id=run_id,
        payload={
            "enable_subtitles": False,
            "image_config": {"ratio": "16:9", "resolution": "720p"},
            "storyboard": [{"shot_id": "shot_001", "desc": "主角推门进入房间", "duration_s": 5.0}],
            "keyframes": [{"path": str(head_path)}],
            "video_clips": [
                {
                    "path": str(clip_path),
                    "duration": 5.0,
                    "head": str(head_path),
                    "meta": {
                        "engine": "wan2.7-i2v",
                        "adapter": "wan3.0-video",
                        "motion_prompt": "主角推门进入房间，镜头平稳推进",
                    },
                }
            ],
            "video_edit_config": {"enabled": True, "adapter": "wan3.0-video"},
            "video_edit_plan": {
                "source": "autoqc",
                "reason": "video_clip_quality_below_threshold",
                "edit_feature": "auto",
                "target_shot_ids": ["shot_001"],
                "items": [
                    {
                        "shot_id": "shot_001",
                        "review_score": 5.8,
                        "threshold": 7.0,
                        "issues": ["画面抖动", "主体一致性不足"],
                        "summary": "需要做轻量修复",
                        "shot_desc": "主角推门进入房间",
                        "edit_feature": "video-remix",
                        "edit_feature_reason": "temporal_consistency_repair",
                    }
                ],
            },
        },
    )

    editor.run(ctx)

    assert len(edit_calls) == 1
    assert edit_calls[0]["model_id"] == "wan3.0-video"
    assert edit_calls[0]["edit_feature"] == "video-remix"
    assert edit_calls[0]["reference_images"] == [str(head_path)]
    assert edit_calls[0]["video_path"] == str(clip_path)

    edited_clip = ctx.payload["video_clips"][0]
    assert edited_clip["path"].endswith("edited_clips\\shot_001.mp4") or edited_clip["path"].endswith("edited_clips/shot_001.mp4")
    assert Path(edited_clip["path"]).exists()
    assert edited_clip["meta"]["edited"] is True
    assert edited_clip["meta"]["edit_model"] == "wan3.0-video"
    assert edited_clip["meta"]["edit_feature"] == "video-remix"
    assert edited_clip["meta"]["edit_feature_reason"] == "temporal_consistency_repair"
    assert edited_clip["meta"]["edited_from_path"] == str(clip_path)

    assert ctx.payload["video_edit_result"]["edited_count"] == 1
    assert ctx.payload["video_edit_result"]["failed_count"] == 0
    assert ctx.payload["video_edit_result"]["edit_feature"] == "auto"
    assert ctx.payload["video_edit_result"]["default_edit_feature"] == "style-transfer"
    assert ctx.payload["video_edit_result"]["feature_counts"] == {"video-remix": 1}
    assert ctx.payload["video_edit_result"]["items"][0]["edit_feature"] == "video-remix"
    assert ctx.payload["video_edit_attempted_shot_ids"] == ["shot_001"]
    assert ctx.payload["video_edit_failed_shot_ids"] == []
    assert Path(ctx.payload["merged_video"]).exists()


def test_restart_reset_clears_video_edit_tracking_for_regenerated_shots() -> None:
    from pipeline.restart_reset import apply_restart_reset

    payload = {
        "video_clips": [{"path": "runs/demo/shot_001.mp4"}, {"path": "runs/demo/shot_002.mp4"}],
        "merged_video": "runs/demo/merged.mp4",
        "regenerate_shot_ids": ["shot_001"],
        "video_edit_attempted_shot_ids": ["shot_001", "shot_002"],
        "video_edit_failed_shot_ids": ["shot_001"],
        "video_edit_result": {"edited_count": 1},
    }

    apply_restart_reset(payload, start_state="VIDEO", reset_policy="downstream")

    assert payload["video_edit_attempted_shot_ids"] == ["shot_002"]
    assert "video_edit_failed_shot_ids" not in payload
    assert "video_edit_result" not in payload
