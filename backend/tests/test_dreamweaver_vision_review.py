from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_dreamweaver_module():
    dreamweaver_path = BACKEND_ROOT / "app" / "api" / "v1" / "dreamweaver_api" / "_imports.py"
    spec = spec_from_file_location("test_dreamweaver_vision_review_module", dreamweaver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 DreamWeaver imports 模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_dreamweaver_vision_review_module", module)
    spec.loader.exec_module(module)
    return module


def _build_autoqc_payload(tmp_path: Path, *, qc_config: dict | None = None) -> dict:
    head = tmp_path / "shot_001_head.png"
    tail = tmp_path / "shot_001_tail.png"
    clip = tmp_path / "shot_001.mp4"
    head.write_bytes(b"head")
    tail.write_bytes(b"tail")
    clip.write_bytes(b"clip")

    return {
        "run_id": "dw_run_vision_001",
        "quality_mode": "quality",
        "storyboard": [
            {
                "shot_id": "shot_001",
                "head_frame": {
                    "ratio": "16:9",
                    "subject_pos": {"x": 0.5, "y": 0.5},
                    "prompt": "主角站在窗边，画面清晰稳定",
                },
                "tail_frame": {
                    "ratio": "16:9",
                    "subject_pos": {"x": 0.5, "y": 0.5},
                    "prompt": "主角仍站在窗边，动作自然连续",
                },
            }
        ],
        "keyframes": [
            {"path": str(head)},
            {"path": str(tail)},
        ],
        "video_clips": [
            {
                "path": str(clip),
                "meta": {
                    "adapter": "wan3.0-video",
                    "engine": "wan2.7-i2v",
                },
            }
        ],
        "video_config": {
            "adapter": "wan3.0-video",
            "engine": "wan2.7-i2v",
        },
        "qc_config": dict(qc_config or {}),
    }


def test_runtime_config_enable_vision_review_seeds_child_qc_defaults() -> None:
    dreamweaver = load_dreamweaver_module()

    request = dreamweaver.RunRequest(
        project_id=1,
        chapter_ids=[1],
        quality_mode="cost",
        vision_model="qwen3-vl-plus",
        enable_vision_review=True,
    )
    runtime_config = dreamweaver._build_dreamweaver_runtime_config_from_request(request)
    qc_config = runtime_config["qc_config"]

    assert qc_config["enable_vision_review"] is True
    assert qc_config["enable_semantic_qc"] is True
    assert qc_config["enable_state_qc"] is True
    assert qc_config["enable_camera_continuity_qc"] is True
    assert qc_config["enable_video_clip_qc"] is True
    assert qc_config["semantic_frames"] == "head"
    assert qc_config["semantic_sample_rate"] == 0.35
    assert qc_config["semantic_max_checks"] == 12
    assert qc_config["state_sample_rate"] == 0.25
    assert qc_config["state_max_checks"] == 8
    assert qc_config["video_clip_threshold"] == 6.5
    assert qc_config["video_clip_sample_rate"] == 0.35
    assert qc_config["video_clip_max_checks"] == 6
    assert qc_config["video_clip_vlm_adapter"] == "qwen3-vl-plus"


def test_autoqc_master_switch_false_skips_video_clip_review(monkeypatch, tmp_path: Path) -> None:
    from pipeline import autoqc
    from pipeline.autoqc_pkg import _video_edit
    from adapters import adapter_helpers

    calls: list[dict] = []

    def _fake_analyze_video(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, data={"overall_score": 9.0}, model_id=kwargs.get("model_id"))

    monkeypatch.setattr(adapter_helpers, "analyze_video", _fake_analyze_video)
    monkeypatch.setattr(_video_edit, "_submit_qc_feedback", lambda report, payload: None)

    payload = _build_autoqc_payload(
        tmp_path,
        qc_config={
            "enable_vision_review": False,
            "enable_video_clip_qc": True,
            "video_clip_vlm_adapter": "qwen3-vl-plus",
        },
    )
    result = autoqc.run(payload)

    assert result["pass"] is True
    assert calls == []
    assert result["config"]["enable_video_clip_qc"] is False
    assert result["config"]["video_clip_checks_done"] == 0


def test_autoqc_video_clip_review_failure_routes_back_to_video(monkeypatch, tmp_path: Path) -> None:
    from pipeline import autoqc
    from pipeline.autoqc_pkg import _video_edit
    from adapters import adapter_helpers

    monkeypatch.setattr(adapter_helpers, "get_model_info", lambda model_id: {"id": model_id})
    monkeypatch.setattr(
        adapter_helpers,
        "analyze_video",
        lambda **kwargs: SimpleNamespace(
            success=True,
            data={"overall_score": 5.6, "issues": ["画面抖动", "主体一致性不足"]},
            model_id=kwargs.get("model_id"),
            error=None,
            error_code=None,
        ),
    )
    monkeypatch.setattr(_video_edit, "_submit_qc_feedback", lambda report, payload: None)

    payload = _build_autoqc_payload(
        tmp_path,
        qc_config={
            "enable_vision_review": True,
            "enable_semantic_qc": False,
            "enable_state_qc": False,
            "enable_camera_continuity_qc": False,
            "enable_video_clip_qc": True,
            "video_clip_vlm_adapter": "qwen3-vl-plus",
            "video_clip_threshold": 7.0,
            "video_clip_sample_rate": 1.0,
            "video_clip_max_checks": 4,
        },
    )
    result = autoqc.run(payload)

    assert result["pass"] is False
    assert result["config"]["video_clip_checks_done"] == 1
    assert "video_clip_quality_below_threshold" in {item["failure_type"] for item in result["failures"]}
    assert result["route"]["target_state"] == "VIDEO"
    assert result["route"]["action"] == "rerun_video"
    assert result["route"]["patch"]["regenerate_shot_ids"] == ["shot_001"]


def test_submit_qc_feedback_infers_model_from_video_config(monkeypatch) -> None:
    from app.tasks import feedback_tasks
    from pipeline.autoqc_pkg._video_edit import _submit_qc_feedback
    from pipeline.autoqc_pkg._dataclasses import AutoQCReport

    calls: list[dict] = []

    class _FakeTask:
        def delay(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(feedback_tasks, "collect_qc_feedback_task", _FakeTask())

    report = AutoQCReport(
        pass_=True,
        overall_score=0.92,
        shots={},
        failures=[],
        route=None,
        config={},
    )

    _submit_qc_feedback(
        report,
        {
            "modality": "text_to_video",
            "video_config": {"adapter": "wan3.0-video"},
        },
    )

    assert len(calls) == 1
    assert calls[0]["model_id"] == "wan3.0-video"
    assert calls[0]["task_type"] == "text_to_video"
