from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def load_dreamweaver_module():
    imports_path = BACKEND_ROOT / "app" / "api" / "v1" / "dreamweaver_api" / "_imports.py"
    spec = spec_from_file_location("test_dreamweaver_video_generation_module", imports_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 DreamWeaver imports 模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_dreamweaver_video_generation_module", module)
    spec.loader.exec_module(module)
    return module


def test_runtime_config_includes_video_generation_selector_defaults(monkeypatch) -> None:
    dreamweaver = load_dreamweaver_module()

    monkeypatch.delenv("DREAMWEAVER_VIDEO_PROVIDER_MODE", raising=False)
    monkeypatch.delenv("DREAMWEAVER_VIDEO_SELECTOR_MODE", raising=False)
    monkeypatch.delenv("DREAMWEAVER_ALLOW_KLING_OMNI", raising=False)
    monkeypatch.delenv("DREAMWEAVER_ENABLE_KLING_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("DREAMWEAVER_ALLOW_SUBJECT_BRIDGE", raising=False)
    monkeypatch.delenv("DREAMWEAVER_ALLOW_SUBJECT_BRIDGE_AUTO_SYNC", raising=False)

    request = dreamweaver.RunRequest(project_id=1, chapter_ids=[1])
    runtime_config = dreamweaver._build_dreamweaver_runtime_config_from_request(request)

    assert runtime_config["video_config"]["provider_mode"] == "wan_only"
    assert runtime_config["video_config"]["selector_mode"] == "off"
    assert runtime_config["video_config"]["allow_kling_omni"] is False
    assert runtime_config["video_config"]["enable_kling_video_provider"] is False
    assert runtime_config["video_config"]["allow_subject_bridge"] is False
    assert runtime_config["video_config"]["allow_subject_bridge_auto_sync"] is False


def test_runtime_config_maps_selected_models_into_runtime_blocks() -> None:
    dreamweaver = load_dreamweaver_module()

    request = dreamweaver.RunRequest(
        project_id=1,
        chapter_ids=[1],
        image_model="qwen-image-2.0-pro",
        video_model="wan2.7-i2v",
        video_edit_model="wan2.7-videoedit",
        vision_model="qwen3-vl-plus",
        enable_video_edit=True,
        enable_vision_review=False,
    )
    runtime_config = dreamweaver._build_dreamweaver_runtime_config_from_request(request)

    assert runtime_config["image_config"]["adapter"] == "qwen-image-2.0-pro"
    assert runtime_config["image_config"]["vlm_adapter"] == "qwen3-vl-plus"
    assert runtime_config["qc_config"]["semantic_vlm_adapter"] == "qwen3-vl-plus"
    assert runtime_config["qc_config"]["state_vlm_adapter"] == "qwen3-vl-plus"
    assert runtime_config["qc_config"]["video_clip_vlm_adapter"] == "qwen3-vl-plus"
    assert runtime_config["qc_config"]["enable_vision_review"] is False
    assert runtime_config["qc_config"]["enable_semantic_qc"] is False
    assert runtime_config["qc_config"]["enable_state_qc"] is False
    assert runtime_config["qc_config"]["enable_camera_continuity_qc"] is False
    assert runtime_config["qc_config"]["enable_video_clip_qc"] is False
    assert runtime_config["video_config"]["adapter"] == "wan2.7-i2v"
    assert runtime_config["video_config"]["engine"] == "wan2.7-i2v"
    assert runtime_config["video_edit_config"]["adapter"] == "wan2.7-videoedit"
    assert runtime_config["video_edit_config"]["enabled"] is True


def test_runtime_config_maps_safety_audit_settings_into_qc_config() -> None:
    dreamweaver = load_dreamweaver_module()

    request = dreamweaver.RunRequest(
        project_id=1,
        chapter_ids=[1],
        vision_model="qwen3-vl-plus",
        enable_safety_audit=True,
        safety_fail_policy="block",
    )
    runtime_config = dreamweaver._build_dreamweaver_runtime_config_from_request(request)

    assert runtime_config["image_config"]["vlm_adapter"] == "qwen3-vl-plus"
    assert runtime_config["qc_config"]["enable_safety_audit"] is True
    assert runtime_config["qc_config"]["safety_fail_policy"] == "block"


def test_runtime_config_infers_t2v_engine_for_non_i2v_video_models() -> None:
    dreamweaver = load_dreamweaver_module()

    request = dreamweaver.RunRequest(
        project_id=1,
        chapter_ids=[1],
        video_model="doubao-seedance-2-0",
    )
    runtime_config = dreamweaver._build_dreamweaver_runtime_config_from_request(request)

    assert runtime_config["video_config"]["adapter"] == "doubao-seedance-2-0"
    assert runtime_config["video_config"]["engine"] == "wan2.7-t2v"


def test_resolve_registered_dreamweaver_model_id_prefers_first_registered(monkeypatch) -> None:
    dreamweaver = load_dreamweaver_module()

    monkeypatch.setattr(
        dreamweaver,
        "get_model_info",
        lambda model_id: {"id": model_id} if model_id in {"qwen-image-2.0-pro", "wan2.6-t2i"} else None,
    )

    resolved = dreamweaver._resolve_registered_dreamweaver_model_id(
        "missing-model",
        "qwen-image-2.0-pro",
        fallback="wan2.6-t2i",
    )

    assert resolved == "qwen-image-2.0-pro"


def test_resolve_registered_dreamweaver_model_id_falls_back_to_default(monkeypatch) -> None:
    dreamweaver = load_dreamweaver_module()

    monkeypatch.setattr(
        dreamweaver,
        "get_model_info",
        lambda model_id: {"id": model_id} if model_id == "wan2.6-t2i" else None,
    )

    resolved = dreamweaver._resolve_registered_dreamweaver_model_id(
        "missing-model",
        "",
        fallback="wan2.6-t2i",
    )

    assert resolved == "wan2.6-t2i"


def test_resolve_video_generation_controls_normalizes_legacy_engine_aliases() -> None:
    from app.services.dreamweaver.video_generation import resolve_video_generation_controls

    assert resolve_video_generation_controls({"engine": "wan_i2v"})["engine"] == "wan2.7-i2v"
    assert resolve_video_generation_controls({"engine": "wan27_t2v"})["engine"] == "wan2.7-t2v"
    assert resolve_video_generation_controls({"engine": "auto"})["engine"] == "wan_auto"


def test_dreamweaver_run_preflight_blocks_active_selector_mode() -> None:
    from app.services.dreamweaver.video_generation import build_dreamweaver_run_preflight

    preflight = build_dreamweaver_run_preflight(
        quality_mode="quality",
        smart_tuning=False,
        qc_allow_fail=False,
        video_require_confirmation=False,
        runtime_config={
            "video_config": {
                "engine": "wan_auto",
                "provider_mode": "auto",
                "selector_mode": "active",
                "allow_kling_omni": True,
            }
        },
    )

    assert preflight.allowed is False
    assert any(item.code == "selector_active_not_available" for item in preflight.errors())
    assert any(item.code == "quality_mode_without_smart_tuning" for item in preflight.warnings())


def test_dreamweaver_run_preflight_blocks_explicit_kling_provider_when_executor_disabled() -> None:
    from app.services.dreamweaver.video_generation import build_dreamweaver_run_preflight

    preflight = build_dreamweaver_run_preflight(
        quality_mode=None,
        smart_tuning=True,
        qc_allow_fail=False,
        video_require_confirmation=False,
        runtime_config={
            "video_config": {
                "engine": "wan_auto",
                "provider_mode": "kling_omni",
                "selector_mode": "off",
                "allow_kling_omni": True,
                "enable_kling_video_provider": False,
            }
        },
    )

    assert preflight.allowed is False
    assert any(item.code == "kling_video_provider_disabled" for item in preflight.errors())


def test_dreamweaver_run_preflight_uses_canonical_selector_engine_hint() -> None:
    from app.services.dreamweaver.video_generation import build_dreamweaver_run_preflight

    preflight = build_dreamweaver_run_preflight(
        quality_mode=None,
        smart_tuning=True,
        qc_allow_fail=False,
        video_require_confirmation=False,
        runtime_config={
            "video_config": {
                "engine": "wan2.7-t2v",
                "provider_mode": "wan_only",
                "selector_mode": "shadow",
            }
        },
    )

    warnings = [item for item in preflight.warnings() if item.code == "selector_engine_unsupported"]
    assert len(warnings) == 1
    assert "wan2.7-i2v" in warnings[0].message
    assert "wan_i2v" not in warnings[0].message


def test_video_provider_trace_marks_bridge_shot_as_kling_shadow_candidate(tmp_path) -> None:
    from app.services.dreamweaver.video_generation import build_video_provider_trace

    head = tmp_path / "shot_001_head.png"
    tail = tmp_path / "shot_001_tail.png"
    head.write_bytes(b"head")
    tail.write_bytes(b"tail")

    trace = build_video_provider_trace(
        storyboard=[
            {
                "shot_id": "shot_001",
                "desc": "角色转身接镜",
            }
        ],
        jobs_by_shot={
            "shot_001": {
                "shot_id": "shot_001",
                "requires_bridge": True,
                "inputs": {
                    "head": str(head),
                    "mid": "",
                    "tail": str(tail),
                },
            }
        },
        video_config={
            "engine": "wan_auto",
            "provider_mode": "auto",
            "selector_mode": "shadow",
            "allow_kling_omni": True,
        },
    )

    assert trace["provider_mode"] == "auto"
    assert trace["selector_mode"] == "shadow"
    assert len(trace["shots"]) == 1

    shot_trace = trace["shots"][0]
    assert shot_trace["shot_id"] == "shot_001"
    assert shot_trace["recommended_provider"] == "kling"
    assert shot_trace["applied_provider"] == "wan"
    assert shot_trace["route"] == "kling_omni"
    assert shot_trace["shadowed"] is True


def test_build_subject_refs_from_character_assets_extracts_kling_subject_refs() -> None:
    from app.services.dreamweaver.video_generation import build_subject_refs_from_character_assets

    refs = build_subject_refs_from_character_assets(
        [
            {
                "asset_id": 11,
                "role": "lib_character_portrait:7",
                "entity_type": "character",
                "entity_id": 7,
                "entity_name": "阿青",
                "view": "front",
                "uri": "runs/library/project_1/characters/7.png",
                "provider_refs": {
                    "kling": {
                        "element_id": "el_123",
                        "source_asset_uri": "runs/library/project_1/characters/7.png",
                    }
                },
            },
            {
                "asset_id": 12,
                "role": "lib_character_portrait_side:7",
                "entity_type": "character",
                "entity_id": 7,
                "entity_name": "阿青",
                "view": "side",
                "uri": "runs/library/project_1/characters/7_side.png",
                "provider_refs": {
                    "kling": {
                        "element_id": "el_123",
                        "source_asset_uri": "runs/library/project_1/characters/7_side.png",
                    }
                },
            },
        ],
        provider="kling",
        max_subject_refs=3,
    )

    assert len(refs) == 1
    assert refs[0]["provider"] == "kling"
    assert refs[0]["subject_id"] == "el_123"
    assert refs[0]["entity_id"] == 7
    assert refs[0]["role"] == "lib_character_portrait:7"


def test_ensure_subject_refs_for_character_assets_auto_syncs_once_per_entity(monkeypatch, tmp_path) -> None:
    from app.services.dreamweaver.video_generation import ensure_subject_refs_for_character_assets
    from app.services.dreamweaver.video_generation import subject_bridge as subject_bridge_module

    front = tmp_path / "aqing_front.png"
    side = tmp_path / "aqing_side.png"
    front.write_bytes(b"front")
    side.write_bytes(b"side")

    class _FakeElement:
        def __init__(self) -> None:
            self.element_id = "el_auto_sync_001"
            self.element_name = "阿青"
            self.element_description = "黑发少年，面部清秀。"
            self.reference_type = "image_refer"

    calls = []

    def _fake_create_and_wait(self, request, **kwargs):
        calls.append(request)
        assert request.name == "阿青"
        assert request.frontal_image == str(front)
        assert str(side) in request.refer_images
        return [_FakeElement()]

    monkeypatch.setattr(subject_bridge_module.KlingElementAPI, "create_and_wait", _fake_create_and_wait)

    assets = [
        {
            "asset_id": 11,
            "role": "lib_character_portrait:7",
            "entity_type": "character",
            "entity_id": 7,
            "entity_name": "阿青",
            "descriptor": "黑发少年，面部清秀。",
            "view": "front",
            "uri": str(front),
            "path": front,
            "provider_refs": {},
        },
        {
            "asset_id": 12,
            "role": "lib_character_portrait_side:7",
            "entity_type": "character",
            "entity_id": 7,
            "entity_name": "阿青",
            "descriptor": "黑发少年，面部清秀。",
            "view": "side",
            "uri": str(side),
            "path": side,
            "provider_refs": {},
        },
    ]

    refs = ensure_subject_refs_for_character_assets(
        assets,
        provider="kling",
        max_subject_refs=3,
        auto_sync=True,
    )

    assert len(calls) == 1
    assert len(refs) == 1
    assert refs[0]["subject_id"] == "el_auto_sync_001"
    assert assets[0]["provider_refs"]["kling"]["element_id"] == "el_auto_sync_001"
    assert assets[1]["provider_refs"]["kling"]["element_id"] == "el_auto_sync_001"


def test_build_kling_omni_plan_includes_subject_ids_and_reference_frames(tmp_path) -> None:
    from app.services.dreamweaver.video_generation import build_kling_omni_plan

    head = tmp_path / "shot_003_head.png"
    mid = tmp_path / "shot_003_mid.png"
    tail = tmp_path / "shot_003_tail.png"
    head.write_bytes(b"head")
    mid.write_bytes(b"mid")
    tail.write_bytes(b"tail")

    plan = build_kling_omni_plan(
        shot={
            "shot_id": "shot_003",
            "desc": "阿青在雨夜回头",
            "provider_subject_refs": [
                {
                    "provider": "kling",
                    "subject_id": "el_789",
                }
            ],
        },
        job={
            "shot_id": "shot_003",
            "requires_bridge": False,
            "inputs": {
                "head": str(head),
                "mid": str(mid),
                "tail": str(tail),
            },
        },
    )

    assert plan is not None
    assert plan["subject_ids"] == ["el_789"]
    assert [item["image_type"] for item in plan["reference_frames"]] == ["first_frame", "end_frame", "reference"]
    assert plan["request_preview"]["image_types"] == "first_frame,end_frame,reference"
    assert plan["request_preview"]["element_ids"] == ["el_789"]
    assert "<<<image_1>>>" in plan["prompt"]
    assert "<<<element_1>>>" in plan["prompt"]


def test_video_provider_trace_uses_multi_reference_frames_signal(tmp_path) -> None:
    from app.services.dreamweaver.video_generation import apply_kling_omni_hints_to_job, build_video_provider_trace

    head = tmp_path / "shot_004_head.png"
    tail = tmp_path / "shot_004_tail.png"
    head.write_bytes(b"head")
    tail.write_bytes(b"tail")

    shot = {
        "shot_id": "shot_004",
        "desc": "主角推门入镜",
    }
    job = apply_kling_omni_hints_to_job(
        {
            "shot_id": "shot_004",
            "requires_bridge": False,
            "inputs": {
                "head": str(head),
                "mid": "",
                "tail": str(tail),
            },
        },
        shot=shot,
    )

    trace = build_video_provider_trace(
        storyboard=[shot],
        jobs_by_shot={"shot_004": job},
        video_config={
            "engine": "wan_auto",
            "provider_mode": "auto",
            "selector_mode": "shadow",
            "allow_kling_omni": True,
        },
    )

    assert len(trace["shots"]) == 1
    shot_trace = trace["shots"][0]
    assert shot_trace["recommended_provider"] == "kling"
    assert shot_trace["reason"] == "multi_reference_frames"


def test_video_provider_trace_marks_explicit_kling_provider_as_applied() -> None:
    from app.services.dreamweaver.video_generation import build_video_provider_trace

    trace = build_video_provider_trace(
        storyboard=[{"shot_id": "shot_005", "desc": "主角雨中慢慢转身"}],
        jobs_by_shot={"shot_005": {"shot_id": "shot_005", "requires_bridge": False, "inputs": {}}},
        video_config={
            "engine": "ffmpeg_slideshow",
            "provider_mode": "kling_omni",
            "selector_mode": "off",
            "allow_kling_omni": True,
            "enable_kling_video_provider": True,
        },
    )

    assert len(trace["shots"]) == 1
    shot_trace = trace["shots"][0]
    assert shot_trace["recommended_provider"] == "kling"
    assert shot_trace["applied_provider"] == "kling"
    assert shot_trace["route"] == "kling_omni"
    assert shot_trace["reason"] == "provider_mode_explicit"


def test_video_provider_trace_uses_subject_refs_when_subject_bridge_enabled() -> None:
    from app.services.dreamweaver.video_generation import build_video_provider_trace

    trace = build_video_provider_trace(
        storyboard=[
            {
                "shot_id": "shot_002",
                "desc": "主角站立特写",
                "provider_subject_refs": [
                    {
                        "provider": "kling",
                        "subject_id": "el_456",
                        "entity_id": 8,
                    }
                ],
            }
        ],
        jobs_by_shot={"shot_002": {"shot_id": "shot_002", "requires_bridge": False, "inputs": {}}},
        video_config={
            "engine": "wan_auto",
            "provider_mode": "auto",
            "selector_mode": "shadow",
            "allow_kling_omni": True,
            "allow_subject_bridge": True,
        },
    )

    assert len(trace["shots"]) == 1
    shot_trace = trace["shots"][0]
    assert shot_trace["recommended_provider"] == "kling"
    assert shot_trace["reason"] == "subject_refs"


def test_build_contract_from_payload_persists_preflight_provider_and_dispatch_trace() -> None:
    from app.services.dreamweaver.persistence import build_contract_from_payload

    contract = build_contract_from_payload(
        run_id="drama_1_123",
        source_project_id=1,
        user_id=7,
        payload={
            "storyboard": [
                {
                    "shot_id": "shot_001",
                    "scene_id": "scene_001",
                    "desc": "主角回头看向镜头",
                    "duration_s": 3.5,
                    "head_frame": {"prompt": "主角正面特写", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
                    "tail_frame": {"prompt": "主角回头定格", "ratio": "16:9", "subject_pos": {"x": 0.5, "y": 0.5}},
                }
            ],
            "preflight": {
                "allowed": True,
                "errors": [],
                "warnings": [
                    {
                        "level": "warning",
                        "code": "quality_mode_without_smart_tuning",
                        "message": "高质量模式建议开启智能调参。",
                    }
                ],
                "resolved_video_config": {
                    "provider_mode": "auto",
                    "selector_mode": "shadow",
                    "allow_kling_omni": True,
                },
            },
            "video_provider_trace": {
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
            },
            "smart_dispatch_trace": {
                "stage": "executed",
                "strategy": "quality",
                "intent": {
                    "task_id": "task-smart-dispatch",
                    "modality": "text_to_video",
                    "prompt": "主角回头看向镜头",
                    "confidence": 0.94,
                },
                "routing": {
                    "selected_model": "wan2.7-t2v",
                    "fallback_models": ["kling-omni-v1"],
                    "strategy": "quality",
                },
                "execution": {
                    "resolved_model": "wan2.7-t2v",
                    "attempted_models": ["wan2.7-t2v"],
                    "timed_out": False,
                },
            },
        },
    )

    runtime = contract.runtime_config
    assert runtime["preflight"]["allowed"] is True
    assert runtime["preflight"]["warnings"][0]["code"] == "quality_mode_without_smart_tuning"
    assert runtime["video_provider_trace"]["provider_mode"] == "auto"
    assert runtime["video_provider_trace"]["shots"][0]["shot_id"] == "shot_001"
    assert runtime["smart_dispatch_trace"]["strategy"] == "quality"
    assert runtime["smart_dispatch_trace"]["routing"]["selected_model"] == "wan2.7-t2v"
