from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.project import Chapter
from app.services.chapter_adaptation_assets import build_drama_source_text
from app.services.dreamweaver.config_lock import apply_vision_review_qc_config
from app.services.dreamweaver.video_generation import resolve_video_generation_controls
from pipeline.media_presets import infer_dreamweaver_video_engine_from_model_id
from adapters.adapter_helpers import get_model_info

from app.api.v1.dreamweaver_api._helpers_env import _env_flag
from app.api.v1.dreamweaver_api._schemas import RunRequest


def _load_project_chapters(
    db: Session, *, project_id: int, chapter_ids: List[int] | None
) -> List[Chapter]:
    chapter_query = db.query(Chapter).filter(Chapter.project_id == project_id)
    if chapter_ids:
        chapter_query = chapter_query.filter(Chapter.id.in_(chapter_ids))
    return chapter_query.order_by(Chapter.chapter_number.asc()).all()


def _build_source_text(chapters: List[Chapter]) -> str:
    return build_drama_source_text(chapters)


def _quality_mode_to_runtime_config(quality_mode: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    mode = (quality_mode or "").strip().lower()
    if mode == "quality":
        return (
            {
                "t2i_candidates": 2,
                "mid_candidates": 2,
                "image_selector": "semantic",
                "keep_candidates": False,
                "image_edit_policy": "auto",
                "image_edit_min_prompt_similarity": 0.12,
                "head_use_image_edit": True,
                "tail_use_image_edit": True,
                "mid_use_image_edit": True,
                "ref_selector": "vlm",
                "ref_max_images": 8,
                "head_ref_rewrite": True,
                "tail_ref_rewrite": True,
                "mid_ref_rewrite": True,
            },
            {
                "enable_semantic_qc": True,
                "semantic_frames": "head",
                "semantic_sample_rate": 0.6,
                "semantic_max_checks": 12,
            },
            {
                "engine": "wan_auto",
                "fps": 30,
                "motion_bucket_id": 127,
            },
        )
    if mode == "cost":
        return (
            {
                "t2i_candidates": 1,
                "mid_candidates": 1,
                "image_selector": "first",
                "keep_candidates": False,
                "head_use_image_edit": False,
                "tail_use_image_edit": False,
                "mid_use_image_edit": False,
                "ref_selector": "recent",
            },
            {
                "enable_semantic_qc": False,
            },
            {
                "engine": "ffmpeg_slideshow",
            },
        )
    return {}, {}, {}


def _infer_video_engine_from_model_id(model_id: Any) -> str:
    return infer_dreamweaver_video_engine_from_model_id(model_id)


def _resolve_registered_dreamweaver_model_id(*candidates: Any, fallback: str) -> str:
    normalized_fallback = str(fallback or "").strip()
    seen: set[str] = set()
    for raw_candidate in [*candidates, normalized_fallback]:
        candidate = str(raw_candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if isinstance(get_model_info(candidate), dict):
            return candidate
    return normalized_fallback


def _build_dreamweaver_runtime_config_from_request(request: RunRequest) -> Dict[str, Any]:
    runtime_config: Dict[str, Any] = {}

    if isinstance(request.quality_mode, str) and request.quality_mode.strip():
        image_config, qc_config, video_config = _quality_mode_to_runtime_config(request.quality_mode)
        runtime_config.update(
            {
                "quality_mode": request.quality_mode.strip().lower(),
                "image_config": image_config,
                "qc_config": qc_config,
                "video_config": video_config,
            }
        )
    if request.smart_tuning is not None:
        runtime_config["smart_tuning"] = bool(request.smart_tuning)
    if isinstance(request.ab_variant, str) and request.ab_variant.strip():
        runtime_config["ab_variant"] = request.ab_variant.strip()
    if request.qc_allow_fail is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["allow_fail"] = bool(request.qc_allow_fail)
        runtime_config["qc_config"] = qc_cfg
    if isinstance(request.style_preset, str) and request.style_preset.strip():
        runtime_config["style_preset"] = request.style_preset.strip()
    if isinstance(request.image_ratio, str) and request.image_ratio.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["ratio"] = request.image_ratio.strip()
        runtime_config["image_config"] = image_cfg
    if isinstance(request.image_resolution, str) and request.image_resolution.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["resolution"] = request.image_resolution.strip()
        runtime_config["image_config"] = image_cfg
    if isinstance(request.image_model, str) and request.image_model.strip():
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["adapter"] = request.image_model.strip()
        runtime_config["image_config"] = image_cfg
    if isinstance(request.vision_model, str) and request.vision_model.strip():
        vision_model = request.vision_model.strip()
        image_cfg = runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}
        image_cfg["vlm_adapter"] = vision_model
        runtime_config["image_config"] = image_cfg

        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg = apply_vision_review_qc_config(qc_cfg, enabled=None, vision_model=vision_model)
        runtime_config["qc_config"] = qc_cfg
    if request.enable_vision_review is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg = apply_vision_review_qc_config(
            qc_cfg,
            enabled=bool(request.enable_vision_review),
            vision_model=request.vision_model,
        )
        runtime_config["qc_config"] = qc_cfg
    if request.enable_safety_audit is not None:
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["enable_safety_audit"] = bool(request.enable_safety_audit)
        runtime_config["qc_config"] = qc_cfg
    if isinstance(request.safety_fail_policy, str) and request.safety_fail_policy.strip():
        qc_cfg = runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}
        qc_cfg["safety_fail_policy"] = request.safety_fail_policy.strip().lower()
        runtime_config["qc_config"] = qc_cfg
    if request.video_fps is not None:
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["fps"] = int(request.video_fps)
        runtime_config["video_config"] = video_cfg
    if isinstance(request.video_model, str) and request.video_model.strip():
        video_model = request.video_model.strip()
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["adapter"] = video_model
        inferred_engine = _infer_video_engine_from_model_id(video_model)
        if inferred_engine:
            video_cfg["engine"] = inferred_engine
        runtime_config["video_config"] = video_cfg
    if isinstance(request.video_edit_model, str) and request.video_edit_model.strip():
        video_edit_cfg = (
            runtime_config.get("video_edit_config") if isinstance(runtime_config.get("video_edit_config"), dict) else {}
        )
        video_edit_cfg["adapter"] = request.video_edit_model.strip()
        runtime_config["video_edit_config"] = video_edit_cfg
    if request.enable_video_edit is not None:
        video_edit_cfg = (
            runtime_config.get("video_edit_config") if isinstance(runtime_config.get("video_edit_config"), dict) else {}
        )
        video_edit_cfg["enabled"] = bool(request.enable_video_edit)
        runtime_config["video_edit_config"] = video_edit_cfg
    if request.video_require_confirmation is not None:
        video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
        video_cfg["require_confirmation"] = bool(request.video_require_confirmation)
        runtime_config["video_config"] = video_cfg

    prompt_review_required = request.prompt_review_required
    if prompt_review_required is None:
        prompt_review_required = _env_flag("DREAMWEAVER_PROMPT_REVIEW_REQUIRED", default=False)
    runtime_config["prompt_review_required"] = bool(prompt_review_required)
    if prompt_review_required:
        runtime_config["prompt_review"] = {"approved": False}

    video_cfg = runtime_config.get("video_config") if isinstance(runtime_config.get("video_config"), dict) else {}
    if not isinstance(video_cfg.get("provider_mode"), str) or not str(video_cfg.get("provider_mode") or "").strip():
        video_cfg["provider_mode"] = str(os.getenv("DREAMWEAVER_VIDEO_PROVIDER_MODE") or "wan_only").strip().lower() or "wan_only"
    if not isinstance(video_cfg.get("selector_mode"), str) or not str(video_cfg.get("selector_mode") or "").strip():
        video_cfg["selector_mode"] = str(os.getenv("DREAMWEAVER_VIDEO_SELECTOR_MODE") or "off").strip().lower() or "off"
    if "allow_kling_omni" not in video_cfg:
        video_cfg["allow_kling_omni"] = _env_flag("DREAMWEAVER_ALLOW_KLING_OMNI", default=False)
    if "enable_kling_video_provider" not in video_cfg:
        video_cfg["enable_kling_video_provider"] = _env_flag(
            "DREAMWEAVER_ENABLE_KLING_VIDEO_PROVIDER",
            default=False,
        )
    if "allow_subject_bridge" not in video_cfg:
        video_cfg["allow_subject_bridge"] = _env_flag("DREAMWEAVER_ALLOW_SUBJECT_BRIDGE", default=False)
    if "allow_subject_bridge_auto_sync" not in video_cfg:
        video_cfg["allow_subject_bridge_auto_sync"] = _env_flag(
            "DREAMWEAVER_ALLOW_SUBJECT_BRIDGE_AUTO_SYNC",
            default=False,
        )
    runtime_config["video_config"] = resolve_video_generation_controls(video_cfg)

    return runtime_config
