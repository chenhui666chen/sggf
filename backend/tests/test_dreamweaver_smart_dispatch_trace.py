from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _disable_smart_tuning(monkeypatch, state_machine) -> None:
    monkeypatch.setattr(state_machine, "apply_smart_tuning", lambda payload, stage: None)


def test_state_machine_keyframes_stage_writes_smart_dispatch_trace(monkeypatch) -> None:
    from pipeline import state_machine

    _disable_smart_tuning(monkeypatch, state_machine)

    def _fake_run_keyframes(ctx) -> None:
        ctx.payload["keyframes"] = [
            {
                "path": "runs/dw_trace_keyframes_001/shot_001_head.png",
                "spec": {"prompt": "hero portrait"},
                "meta": {
                    "role": "head",
                    "via": "t2i",
                    "decision": {"mode": "t2i"},
                    "ref": {"rewrite": {"prompt": "hero portrait cinematic light"}},
                },
            },
            {
                "path": "runs/dw_trace_keyframes_001/shot_001_tail.png",
                "spec": {"prompt": "hero turns"},
                "meta": {
                    "role": "tail",
                    "via": "image_edit",
                    "decision": {"mode": "image_edit"},
                    "ref": {"rewrite": {"edit_prompt": "hero turns with motion blur"}},
                },
            },
        ]

    monkeypatch.setattr(state_machine.painter, "run_keyframes", _fake_run_keyframes)

    ctx = state_machine.RunContext(
        run_id="dw_trace_keyframes_001",
        state=state_machine.State.KEYFRAMES,
        payload={
            "quality_mode": "quality",
            "image_config": {
                "adapter": "qwen-image-3.0",
                "image_edit_adapter": "wan_image_edit",
            },
        },
    )

    result = state_machine.step(ctx)
    trace = result.payload["smart_dispatch_trace"]

    assert result.state == state_machine.State.MIDFRAMES
    assert trace["stage"] == "keyframes"
    assert trace["strategy"] == "quality"
    assert trace["intent"]["modality"] == "text_to_image"
    assert trace["routing"]["selected_model"] == "qwen-image-3.0"
    assert trace["routing"]["fallback_models"] == ["wan_image_edit"]
    assert trace["execution"]["resolved_model"] == "qwen-image-3.0"
    assert trace["execution"]["attempted_models"] == ["qwen-image-3.0", "wan_image_edit"]
    assert trace["execution"]["prompt"]["prompt_changed"] is True
    assert trace["phases"][0]["stage"] == "keyframes"


def test_state_machine_midframes_stage_writes_smart_dispatch_trace(monkeypatch) -> None:
    from pipeline import state_machine

    _disable_smart_tuning(monkeypatch, state_machine)

    def _fake_run_midframes(ctx) -> None:
        ctx.payload["midframes"] = [
            {
                "path": "runs/dw_trace_midframes_001/shot_001_mid.png",
                "spec": {"prompt": "middle frame"},
                "meta": {
                    "role": "mid",
                    "via": "image_edit",
                    "decision": {"mode": "image_edit"},
                    "ref": {"rewrite": {"edit_prompt": "middle frame with bridge motion"}},
                },
            }
        ]

    monkeypatch.setattr(state_machine.painter, "run_midframes", _fake_run_midframes)

    ctx = state_machine.RunContext(
        run_id="dw_trace_midframes_001",
        state=state_machine.State.MIDFRAMES,
        payload={
            "quality_mode": "cost",
            "image_config": {
                "adapter": "qwen-image-3.0",
                "image_edit_adapter": "qwen_image_edit",
            },
        },
    )

    result = state_machine.step(ctx)
    trace = result.payload["smart_dispatch_trace"]

    assert result.state == state_machine.State.VIDEO
    assert trace["stage"] == "midframes"
    assert trace["strategy"] == "cost"
    assert trace["intent"]["modality"] == "image_edit"
    assert trace["routing"]["selected_model"] == "qwen_image_edit"
    assert trace["execution"]["resolved_model"] == "qwen_image_edit"
    assert trace["execution"]["attempted_models"] == ["qwen_image_edit"]
    assert trace["execution"]["prompt"]["prompt_changed"] is True
    assert trace["phases"][0]["stage"] == "midframes"


def test_state_machine_video_stage_writes_real_provider_trace(monkeypatch) -> None:
    from pipeline import state_machine

    _disable_smart_tuning(monkeypatch, state_machine)

    def _fake_run_video(ctx) -> None:
        ctx.payload["video_provider_trace"] = {
            "provider_mode": "auto",
            "selector_mode": "shadow",
            "allow_kling_omni": True,
            "enable_kling_video_provider": False,
            "allow_subject_bridge": True,
            "shots": [
                {
                    "shot_id": "shot_001",
                    "recommended_provider": "kling",
                    "applied_provider": "wan",
                    "route": "kling_omni",
                    "reason": "subject_refs",
                    "shadowed": True,
                }
            ],
        }
        ctx.payload["video_clips"] = [
            {
                "path": "runs/dw_trace_video_001/shot_001.mp4",
                "meta": {
                    "engine": "wan_auto",
                    "adapter": "wan3.0-video",
                    "via": "wan3.0-video",
                    "prompt": "cinematic hero turns back to camera",
                },
            }
        ]
        ctx.payload["video_done"] = False

    monkeypatch.setattr(state_machine.dreamweaver, "run_video", _fake_run_video)

    ctx = state_machine.RunContext(
        run_id="dw_trace_video_001",
        state=state_machine.State.VIDEO,
        payload={
            "quality_mode": "quality",
            "video_config": {
                "adapter": "wan3.0-video",
                "engine": "wan_auto",
                "provider_mode": "auto",
                "selector_mode": "shadow",
                "allow_kling_omni": True,
                "enable_kling_video_provider": False,
                "allow_subject_bridge": True,
            },
            "storyboard": [
                {
                    "shot_id": "shot_001",
                    "desc": "hero turns back",
                    "shot_schema_v2_meta": {
                        "video_prompt_generated": "cinematic hero turns back to camera",
                    },
                }
            ],
        },
    )

    result = state_machine.step(ctx)
    trace = result.payload["smart_dispatch_trace"]

    assert result.state == state_machine.State.WAITING_VIDEO_CONFIRMATION
    assert trace["stage"] == "video"
    # wan3.0-video 是 all-in-one，引擎归为 wan_auto，无法再推断 i2v/t2v，modality 落到通用值
    assert trace["intent"]["modality"] == "video_generation"
    assert trace["routing"]["selected_model"] == "wan3.0-video"
    assert "kling_omni" in trace["routing"]["fallback_models"]
    assert trace["execution"]["resolved_model"] == "wan3.0-video"
    assert trace["execution"]["attempted_models"] == ["wan3.0-video"]
    assert trace["execution"]["adapter"]["provider_mode"] == "auto"
    assert trace["execution"]["prompt"]["prompt_changed"] is True
    assert trace["phases"][0]["stage"] == "video"


def test_state_machine_edit_stage_writes_video_edit_trace(monkeypatch) -> None:
    from pipeline import state_machine

    _disable_smart_tuning(monkeypatch, state_machine)

    def _fake_editor_run(ctx) -> None:
        ctx.payload["video_clips"] = [
            {
                "path": "runs/dw_trace_edit_001/shot_001.mp4",
                "meta": {
                    "edited": True,
                    "edit_model": "wan3.0-video",
                    "edit_feature": "video-remix",
                    "edit_feature_reason": "temporal_consistency_repair",
                    "edit_prompt": "repair shaky hero motion and restore subject consistency",
                    "via": "video_edit",
                },
            }
        ]
        ctx.payload["video_edit_attempted_shot_ids"] = ["shot_001"]
        ctx.payload["video_edit_failed_shot_ids"] = []
        ctx.payload["video_edit_result"] = {
            "status": "edited",
            "enabled": True,
            "source": "autoqc",
            "reason": "video_clip_quality_below_threshold",
            "model_id": "wan3.0-video",
            "edit_feature": "auto",
            "default_edit_feature": "style-transfer",
            "requested_count": 1,
            "edited_count": 1,
            "failed_count": 0,
            "target_shot_ids": ["shot_001"],
            "feature_counts": {"video-remix": 1},
        }

    monkeypatch.setattr(state_machine.editor, "run", _fake_editor_run)

    ctx = state_machine.RunContext(
        run_id="dw_trace_edit_001",
        state=state_machine.State.EDIT,
        payload={
            "quality_mode": "quality",
            "video_edit_config": {"enabled": True, "adapter": "wan3.0-video"},
        },
    )

    result = state_machine.step(ctx)
    trace = result.payload["smart_dispatch_trace"]

    assert result.state == state_machine.State.REVIEW
    assert trace["stage"] == "edit"
    assert trace["intent"]["modality"] == "video_edit"
    assert trace["routing"]["selected_model"] == "wan3.0-video"
    assert trace["execution"]["resolved_model"] == "wan3.0-video"
    assert trace["execution"]["attempted_models"] == ["wan3.0-video"]
    assert trace["execution"]["adapter"]["status"] == "edited"
    assert trace["execution"]["adapter"]["edited_count"] == 1
    assert trace["execution"]["adapter"]["feature_counts"] == {"video-remix": 1}
    assert trace["execution"]["prompt"]["prompt_changed"] is True
    assert trace["phases"][0]["stage"] == "edit"


def test_state_machine_review_stage_writes_safety_model_trace(monkeypatch) -> None:
    from pipeline import state_machine

    _disable_smart_tuning(monkeypatch, state_machine)
    autoqc_calls: list[dict] = []

    def _fake_auditor_run(ctx):
        result = {
            "pass": False,
            "issues": [{"category": "safety", "message": "unsafe video"}],
            "failure_type": "safety_audit_failed",
            "safety_audit": {
                "enabled": True,
                "executed": True,
                "unsafe": True,
                "blocked": True,
                "warn_only": False,
                "fail_policy": "block",
                "model_id": "qwen3.8-omni-flash",
                "analysis_type": "safety",
                "summary": "unsafe video",
                "issues": ["unsafe video"],
                "categories": ["violence"],
                "warnings": [],
            },
        }
        ctx.payload["audit"] = result
        return result

    monkeypatch.setattr(state_machine.auditor, "run", _fake_auditor_run)
    monkeypatch.setattr(
        state_machine.autoqc,
        "run",
        lambda payload: autoqc_calls.append(dict(payload)) or {"pass": True, "failures": [], "route": None},
    )

    ctx = state_machine.RunContext(
        run_id="dw_trace_review_001",
        state=state_machine.State.REVIEW,
        payload={"quality_mode": "cost"},
    )

    result = state_machine.step(ctx)
    trace = result.payload["smart_dispatch_trace"]

    assert result.state == state_machine.State.FAILED
    assert autoqc_calls == []
    assert trace["stage"] == "review"
    assert trace["intent"]["modality"] == "video_analysis"
    assert trace["routing"]["selected_model"] == "qwen3.8-omni-flash"
    assert trace["execution"]["resolved_model"] == "qwen3.8-omni-flash"
    assert trace["execution"]["attempted_models"] == ["qwen3.8-omni-flash"]
    assert trace["execution"]["adapter"]["blocked"] is True
    assert trace["phases"][0]["stage"] == "review"
