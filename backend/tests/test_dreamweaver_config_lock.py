from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def load_dreamweaver_module():
    dreamweaver_path = BACKEND_ROOT / "app" / "api" / "v1" / "dreamweaver.py"
    spec = spec_from_file_location("test_dreamweaver_config_lock_dreamweaver_module", dreamweaver_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 DreamWeaver 路由模块")

    module = module_from_spec(spec)
    sys.modules.setdefault("test_dreamweaver_config_lock_dreamweaver_module", module)
    spec.loader.exec_module(module)
    return module


def test_extract_generation_config_from_contract_includes_model_and_toggle_fields() -> None:
    from app.services.dreamweaver.config_lock import _extract_generation_config_from_contract

    values = _extract_generation_config_from_contract(
        {
            "runtime_config": {
                "style_preset": "anime",
                "image_config": {
                    "ratio": "9:16",
                    "resolution": "1080p",
                    "adapter": "qwen-image-2.0-pro",
                    "vlm_adapter": "qwen3-vl-plus",
                },
                "video_config": {
                    "adapter": "wan2.7-i2v",
                },
                "qc_config": {
                    "semantic_vlm_adapter": "qwen3-vl-plus",
                    "state_vlm_adapter": "qwen3-vl-plus",
                    "video_clip_vlm_adapter": "qwen3-vl-plus",
                    "enable_vision_review": False,
                    "enable_safety_audit": True,
                    "safety_fail_policy": "block",
                },
                "video_edit_config": {
                    "adapter": "wan2.7-videoedit",
                    "enabled": True,
                },
            }
        }
    )

    assert values == {
        "style_preset": "anime",
        "image_ratio": "9:16",
        "image_resolution": "1080p",
        "image_model": "qwen-image-2.0-pro",
        "video_model": "wan2.7-i2v",
        "vision_model": "qwen3-vl-plus",
        "video_edit_model": "wan2.7-videoedit",
        "enable_video_edit": True,
        "enable_vision_review": False,
        "enable_safety_audit": True,
        "safety_fail_policy": "block",
    }


def test_enforce_locked_generation_config_compatible_detects_model_mismatches() -> None:
    from app.services.dreamweaver.config_lock import (
        DreamweaverProjectConfigLockedError,
        DreamweaverProjectLockedGenerationConfig,
        enforce_locked_generation_config_compatible,
    )

    locked = DreamweaverProjectLockedGenerationConfig(
        locked=True,
        style_preset="cinematic_realistic",
        image_ratio="16:9",
        image_resolution="720p",
        image_model="qwen-image-2.0-pro",
        video_model="wan2.7-i2v",
        vision_model="qwen3-vl-plus",
        video_edit_model="wan2.7-videoedit",
        enable_video_edit=True,
        enable_vision_review=False,
        enable_safety_audit=True,
        safety_fail_policy="warn",
        source_run_id="dw_run_001",
    )

    with pytest.raises(DreamweaverProjectConfigLockedError) as exc_info:
        enforce_locked_generation_config_compatible(
            locked,
            style_preset="cinematic_realistic",
            image_ratio="16:9",
            image_resolution="720p",
            image_model="other-image-model",
            video_model="wan2.7-t2v",
            vision_model="other-vision-model",
            video_edit_model="other-edit-model",
            enable_video_edit=False,
            enable_vision_review=True,
            enable_safety_audit=False,
            safety_fail_policy="block",
        )

    assert exc_info.value.requested["image_model"] == "other-image-model"
    assert exc_info.value.mismatches == {
        "image_model": {
            "locked": "qwen-image-2.0-pro",
            "requested": "other-image-model",
        },
        "video_model": {
            "locked": "wan2.7-i2v",
            "requested": "wan2.7-t2v",
        },
        "vision_model": {
            "locked": "qwen3-vl-plus",
            "requested": "other-vision-model",
        },
        "video_edit_model": {
            "locked": "wan2.7-videoedit",
            "requested": "other-edit-model",
        },
        "enable_video_edit": {
            "locked": True,
            "requested": False,
        },
        "enable_vision_review": {
            "locked": False,
            "requested": True,
        },
        "enable_safety_audit": {
            "locked": True,
            "requested": False,
        },
        "safety_fail_policy": {
            "locked": "warn",
            "requested": "block",
        },
    }


def test_apply_locked_generation_config_injects_models_and_infers_video_engine() -> None:
    from app.services.dreamweaver.config_lock import (
        DreamweaverProjectLockedGenerationConfig,
        apply_locked_generation_config,
    )

    locked = DreamweaverProjectLockedGenerationConfig(
        locked=True,
        style_preset="anime",
        image_ratio="9:16",
        image_resolution="1080p",
        image_model="qwen-image-2.0-pro",
        video_model="doubao-seedance-2-0",
        vision_model="qwen3-vl-plus",
        video_edit_model="wan2.7-videoedit",
        enable_video_edit=True,
        enable_vision_review=False,
        enable_safety_audit=True,
        safety_fail_policy="block",
        source_run_id="dw_run_002",
    )

    target = apply_locked_generation_config(
        {
            "image_config": {},
            "video_config": {},
            "qc_config": {},
            "video_edit_config": {},
        },
        locked,
    )

    assert target["style_preset"] == "anime"
    assert target["image_config"] == {
        "ratio": "9:16",
        "resolution": "1080p",
        "adapter": "qwen-image-2.0-pro",
        "vlm_adapter": "qwen3-vl-plus",
    }
    assert target["video_config"] == {
        "adapter": "doubao-seedance-2-0",
        "engine": "wan2.7-t2v",
    }
    assert target["qc_config"] == {
        "semantic_vlm_adapter": "qwen3-vl-plus",
        "state_vlm_adapter": "qwen3-vl-plus",
        "video_clip_vlm_adapter": "qwen3-vl-plus",
        "enable_vision_review": False,
        "enable_semantic_qc": False,
        "enable_state_qc": False,
        "enable_camera_continuity_qc": False,
        "enable_video_clip_qc": False,
        "enable_safety_audit": True,
        "safety_fail_policy": "block",
    }
    assert target["video_edit_config"] == {
        "adapter": "wan2.7-videoedit",
        "enabled": True,
    }


def test_locked_generation_config_error_detail_serializes_model_fields() -> None:
    from app.services.dreamweaver.config_lock import (
        DreamweaverProjectConfigLockedError,
        DreamweaverProjectLockedGenerationConfig,
    )

    dreamweaver = load_dreamweaver_module()
    locked = DreamweaverProjectLockedGenerationConfig(
        locked=True,
        style_preset="cinematic_realistic",
        image_ratio="16:9",
        image_resolution="720p",
        image_model="qwen-image-2.0-pro",
        video_model="wan2.7-i2v",
        vision_model="qwen3-vl-plus",
        video_edit_model="wan2.7-videoedit",
        enable_video_edit=True,
        enable_vision_review=False,
        enable_safety_audit=True,
        safety_fail_policy="block",
        source_run_id="dw_run_003",
    )
    exc = DreamweaverProjectConfigLockedError(
        "project generation config locked",
        locked=locked,
        requested={"image_model": "other-image-model"},
        mismatches={"image_model": {"locked": "qwen-image-2.0-pro", "requested": "other-image-model"}},
    )

    detail = dreamweaver._locked_generation_config_error_detail("locked", exc)

    assert detail == {
        "message": "locked",
        "locked": {
            "style_preset": "cinematic_realistic",
            "image_ratio": "16:9",
            "image_resolution": "720p",
            "source_run_id": "dw_run_003",
            "image_model": "qwen-image-2.0-pro",
            "video_model": "wan2.7-i2v",
            "vision_model": "qwen3-vl-plus",
            "video_edit_model": "wan2.7-videoedit",
            "enable_video_edit": True,
            "enable_vision_review": False,
            "enable_safety_audit": True,
            "safety_fail_policy": "block",
        },
        "requested": {"image_model": "other-image-model"},
        "mismatches": {
            "image_model": {
                "locked": "qwen-image-2.0-pro",
                "requested": "other-image-model",
            }
        },
    }
