from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel
from pipeline.media_presets import (
    infer_dreamweaver_video_engine_from_model_id,
    normalize_frame_ratio,
    normalize_image_resolution,
)
from pipeline.style_presets import normalize_style_preset

LIBRARY_ANCHOR_STATUS = "library"
LOCK_SCAN_LIMIT = 50
VISION_REVIEW_FLAG_KEYS = (
    "enable_semantic_qc",
    "enable_state_qc",
    "enable_camera_continuity_qc",
    "enable_video_clip_qc",
)
VISION_REVIEW_DEFAULTS: Dict[str, Any] = {
    "semantic_frames": "head",
    "semantic_sample_rate": 0.35,
    "semantic_max_checks": 12,
    "state_sample_rate": 0.25,
    "state_max_checks": 8,
    "video_clip_threshold": 6.5,
    "video_clip_sample_rate": 0.35,
    "video_clip_max_checks": 6,
}


@dataclass(frozen=True)
class DreamweaverProjectLockedGenerationConfig:
    locked: bool
    style_preset: str
    image_ratio: str
    image_resolution: str
    image_model: Optional[str] = None
    video_model: Optional[str] = None
    vision_model: Optional[str] = None
    video_edit_model: Optional[str] = None
    enable_video_edit: Optional[bool] = None
    enable_vision_review: Optional[bool] = None
    enable_safety_audit: Optional[bool] = None
    safety_fail_policy: Optional[str] = None
    source_run_id: Optional[str] = None


class DreamweaverProjectConfigLockedError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        locked: DreamweaverProjectLockedGenerationConfig,
        requested: Dict[str, Any],
        mismatches: Dict[str, Dict[str, Any]],
    ) -> None:
        super().__init__(message)
        self.locked = locked
        self.requested = requested
        self.mismatches = mismatches


def _normalize_optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _normalize_safety_fail_policy(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"block", "fail", "deny", "hard", "strict"}:
        return "block"
    if raw in {"warn", "warning", "soft", "allow", "ignore"}:
        return "warn"
    return raw


def _is_missing_qc_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def apply_vision_review_qc_config(
    target: Dict[str, Any],
    *,
    enabled: Optional[bool],
    vision_model: Optional[str] = None,
) -> Dict[str, Any]:
    qc_cfg = dict(target) if isinstance(target, dict) else {}

    resolved_model = _normalize_optional_text(vision_model)
    if resolved_model:
        qc_cfg["semantic_vlm_adapter"] = resolved_model
        qc_cfg["state_vlm_adapter"] = resolved_model
        qc_cfg["video_clip_vlm_adapter"] = resolved_model

    if enabled is None:
        return qc_cfg

    qc_cfg["enable_vision_review"] = bool(enabled)
    if enabled:
        for key in VISION_REVIEW_FLAG_KEYS:
            qc_cfg[key] = True
        for key, value in VISION_REVIEW_DEFAULTS.items():
            if _is_missing_qc_value(qc_cfg.get(key)):
                qc_cfg[key] = value
        return qc_cfg

    for key in VISION_REVIEW_FLAG_KEYS:
        qc_cfg[key] = False
    return qc_cfg


def serialize_locked_generation_config(locked: DreamweaverProjectLockedGenerationConfig) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "style_preset": locked.style_preset,
        "image_ratio": locked.image_ratio,
        "image_resolution": locked.image_resolution,
        "source_run_id": locked.source_run_id,
    }
    if locked.image_model:
        payload["image_model"] = locked.image_model
    if locked.video_model:
        payload["video_model"] = locked.video_model
    if locked.vision_model:
        payload["vision_model"] = locked.vision_model
    if locked.video_edit_model:
        payload["video_edit_model"] = locked.video_edit_model
    if locked.enable_video_edit is not None:
        payload["enable_video_edit"] = bool(locked.enable_video_edit)
    if locked.enable_vision_review is not None:
        payload["enable_vision_review"] = bool(locked.enable_vision_review)
    if locked.enable_safety_audit is not None:
        payload["enable_safety_audit"] = bool(locked.enable_safety_audit)
    if locked.safety_fail_policy:
        payload["safety_fail_policy"] = locked.safety_fail_policy
    return payload


def _extract_generation_config_from_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    def _from_scope(scope: Any) -> Dict[str, Any]:
        if not isinstance(scope, dict):
            return {}
        style_raw = scope.get("style_preset") if isinstance(scope.get("style_preset"), str) else None
        image_cfg = scope.get("image_config") if isinstance(scope.get("image_config"), dict) else {}
        video_cfg = scope.get("video_config") if isinstance(scope.get("video_config"), dict) else {}
        qc_cfg = scope.get("qc_config") if isinstance(scope.get("qc_config"), dict) else {}
        video_edit_cfg = scope.get("video_edit_config") if isinstance(scope.get("video_edit_config"), dict) else {}
        ratio_raw = image_cfg.get("ratio") if isinstance(image_cfg.get("ratio"), str) else None
        resolution_raw = image_cfg.get("resolution") if isinstance(image_cfg.get("resolution"), str) else None
        return {
            "style_preset": style_raw,
            "image_ratio": ratio_raw,
            "image_resolution": resolution_raw,
            "image_model": _normalize_optional_text(image_cfg.get("adapter")),
            "video_model": _normalize_optional_text(video_cfg.get("adapter")),
            "vision_model": (
                _normalize_optional_text(image_cfg.get("vlm_adapter"))
                or _normalize_optional_text(qc_cfg.get("semantic_vlm_adapter"))
                or _normalize_optional_text(qc_cfg.get("state_vlm_adapter"))
                or _normalize_optional_text(qc_cfg.get("video_clip_vlm_adapter"))
            ),
            "video_edit_model": _normalize_optional_text(video_edit_cfg.get("adapter")),
            "enable_video_edit": (
                bool(video_edit_cfg.get("enabled"))
                if isinstance(video_edit_cfg.get("enabled"), bool)
                else None
            ),
            "enable_vision_review": (
                bool(qc_cfg.get("enable_vision_review"))
                if isinstance(qc_cfg.get("enable_vision_review"), bool)
                else None
            ),
            "enable_safety_audit": (
                bool(qc_cfg.get("enable_safety_audit"))
                if isinstance(qc_cfg.get("enable_safety_audit"), bool)
                else None
            ),
            "safety_fail_policy": _normalize_safety_fail_policy(qc_cfg.get("safety_fail_policy")),
        }

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else None
    runtime_values = _from_scope(runtime_cfg)
    has_any = any(
        value is not None and (not isinstance(value, str) or bool(value.strip()))
        for value in runtime_values.values()
    )
    if has_any:
        return runtime_values

    # Legacy fallback: older contract versions may have persisted the generation config at the top-level.
    return _from_scope(contract)


def get_project_locked_generation_config(
    session: Session,
    *,
    project_id: int,
    user_id: int,
) -> DreamweaverProjectLockedGenerationConfig:
    default_style = normalize_style_preset(None)
    default_ratio = normalize_frame_ratio(None)
    default_resolution = normalize_image_resolution(None)

    rows = (
        session.query(DreamweaverProjectModel)
        .filter(
            DreamweaverProjectModel.source_project_id == project_id,
            DreamweaverProjectModel.user_id == user_id,
            # "library" anchor row is not a real run; it should not lock project generation config.
            DreamweaverProjectModel.status != LIBRARY_ANCHOR_STATUS,
        )
        .order_by(DreamweaverProjectModel.updated_at.desc())
        .limit(LOCK_SCAN_LIMIT)
        .all()
    )
    if not rows:
        return DreamweaverProjectLockedGenerationConfig(
            locked=False,
            style_preset=default_style,
            image_ratio=default_ratio,
            image_resolution=default_resolution,
            image_model=None,
            video_model=None,
            vision_model=None,
            video_edit_model=None,
            enable_video_edit=None,
            enable_vision_review=None,
            enable_safety_audit=None,
            safety_fail_policy=None,
            source_run_id=None,
        )

    fallback_run_id = str(rows[0].run_id)
    for row in rows:
        contract = row.contract_json if isinstance(row.contract_json, dict) else None
        if not contract:
            continue
        values = _extract_generation_config_from_contract(contract)
        has_any = any(
            value is not None and (not isinstance(value, str) or bool(value.strip()))
            for value in values.values()
        )
        if not has_any:
            continue
        return DreamweaverProjectLockedGenerationConfig(
            locked=True,
            style_preset=normalize_style_preset(values.get("style_preset")),
            image_ratio=normalize_frame_ratio(values.get("image_ratio")),
            image_resolution=normalize_image_resolution(values.get("image_resolution")),
            image_model=_normalize_optional_text(values.get("image_model")),
            video_model=_normalize_optional_text(values.get("video_model")),
            vision_model=_normalize_optional_text(values.get("vision_model")),
            video_edit_model=_normalize_optional_text(values.get("video_edit_model")),
            enable_video_edit=values.get("enable_video_edit")
            if isinstance(values.get("enable_video_edit"), bool)
            else None,
            enable_vision_review=values.get("enable_vision_review")
            if isinstance(values.get("enable_vision_review"), bool)
            else None,
            enable_safety_audit=values.get("enable_safety_audit")
            if isinstance(values.get("enable_safety_audit"), bool)
            else None,
            safety_fail_policy=_normalize_safety_fail_policy(values.get("safety_fail_policy")),
            source_run_id=str(row.run_id),
        )

    return DreamweaverProjectLockedGenerationConfig(
        locked=False,
        style_preset=default_style,
        image_ratio=default_ratio,
        image_resolution=default_resolution,
        image_model=None,
        video_model=None,
        vision_model=None,
        video_edit_model=None,
        enable_video_edit=None,
        enable_vision_review=None,
        enable_safety_audit=None,
        safety_fail_policy=None,
        source_run_id=fallback_run_id,
    )


def enforce_locked_generation_config_compatible(
    locked: DreamweaverProjectLockedGenerationConfig,
    *,
    style_preset: Optional[str],
    image_ratio: Optional[str],
    image_resolution: Optional[str],
    image_model: Optional[str] = None,
    video_model: Optional[str] = None,
    vision_model: Optional[str] = None,
    video_edit_model: Optional[str] = None,
    enable_video_edit: Optional[bool] = None,
    enable_vision_review: Optional[bool] = None,
    enable_safety_audit: Optional[bool] = None,
    safety_fail_policy: Optional[str] = None,
) -> None:
    if not locked.locked:
        return

    requested = {
        "style_preset": style_preset.strip() if isinstance(style_preset, str) else None,
        "image_ratio": image_ratio.strip() if isinstance(image_ratio, str) else None,
        "image_resolution": image_resolution.strip() if isinstance(image_resolution, str) else None,
        "image_model": image_model.strip() if isinstance(image_model, str) else None,
        "video_model": video_model.strip() if isinstance(video_model, str) else None,
        "vision_model": vision_model.strip() if isinstance(vision_model, str) else None,
        "video_edit_model": video_edit_model.strip() if isinstance(video_edit_model, str) else None,
        "enable_video_edit": bool(enable_video_edit) if isinstance(enable_video_edit, bool) else None,
        "enable_vision_review": bool(enable_vision_review) if isinstance(enable_vision_review, bool) else None,
        "enable_safety_audit": bool(enable_safety_audit) if isinstance(enable_safety_audit, bool) else None,
        "safety_fail_policy": _normalize_safety_fail_policy(safety_fail_policy),
    }

    mismatches: Dict[str, Dict[str, Any]] = {}
    if requested["style_preset"] and normalize_style_preset(requested["style_preset"]) != locked.style_preset:
        mismatches["style_preset"] = {
            "locked": locked.style_preset,
            "requested": normalize_style_preset(requested["style_preset"]),
        }
    if requested["image_ratio"] and normalize_frame_ratio(requested["image_ratio"]) != locked.image_ratio:
        mismatches["image_ratio"] = {
            "locked": locked.image_ratio,
            "requested": normalize_frame_ratio(requested["image_ratio"]),
        }
    if requested["image_resolution"] and normalize_image_resolution(requested["image_resolution"]) != locked.image_resolution:
        mismatches["image_resolution"] = {
            "locked": locked.image_resolution,
            "requested": normalize_image_resolution(requested["image_resolution"]),
        }
    if requested["image_model"] and locked.image_model and requested["image_model"] != locked.image_model:
        mismatches["image_model"] = {
            "locked": locked.image_model,
            "requested": requested["image_model"],
        }
    if requested["video_model"] and locked.video_model and requested["video_model"] != locked.video_model:
        mismatches["video_model"] = {
            "locked": locked.video_model,
            "requested": requested["video_model"],
        }
    if requested["vision_model"] and locked.vision_model and requested["vision_model"] != locked.vision_model:
        mismatches["vision_model"] = {
            "locked": locked.vision_model,
            "requested": requested["vision_model"],
        }
    if requested["video_edit_model"] and locked.video_edit_model and requested["video_edit_model"] != locked.video_edit_model:
        mismatches["video_edit_model"] = {
            "locked": locked.video_edit_model,
            "requested": requested["video_edit_model"],
        }
    if requested["enable_video_edit"] is not None and locked.enable_video_edit is not None and requested["enable_video_edit"] != locked.enable_video_edit:
        mismatches["enable_video_edit"] = {
            "locked": locked.enable_video_edit,
            "requested": requested["enable_video_edit"],
        }
    if requested["enable_vision_review"] is not None and locked.enable_vision_review is not None and requested["enable_vision_review"] != locked.enable_vision_review:
        mismatches["enable_vision_review"] = {
            "locked": locked.enable_vision_review,
            "requested": requested["enable_vision_review"],
        }
    if requested["enable_safety_audit"] is not None and locked.enable_safety_audit is not None and requested["enable_safety_audit"] != locked.enable_safety_audit:
        mismatches["enable_safety_audit"] = {
            "locked": locked.enable_safety_audit,
            "requested": requested["enable_safety_audit"],
        }
    if requested["safety_fail_policy"] and locked.safety_fail_policy and requested["safety_fail_policy"] != locked.safety_fail_policy:
        mismatches["safety_fail_policy"] = {
            "locked": locked.safety_fail_policy,
            "requested": requested["safety_fail_policy"],
        }

    if mismatches:
        raise DreamweaverProjectConfigLockedError(
            "project generation config locked",
            locked=locked,
            requested=requested,
            mismatches=mismatches,
        )


def apply_locked_generation_config(
    target: Dict[str, Any],
    locked: DreamweaverProjectLockedGenerationConfig,
) -> Dict[str, Any]:
    if not locked.locked:
        return target

    target["style_preset"] = locked.style_preset
    image_cfg = target.get("image_config") if isinstance(target.get("image_config"), dict) else {}
    image_cfg["ratio"] = locked.image_ratio
    image_cfg["resolution"] = locked.image_resolution
    if locked.image_model:
        image_cfg["adapter"] = locked.image_model
    if locked.vision_model:
        image_cfg["vlm_adapter"] = locked.vision_model
    target["image_config"] = image_cfg

    video_cfg = target.get("video_config") if isinstance(target.get("video_config"), dict) else {}
    if locked.video_model:
        video_cfg["adapter"] = locked.video_model
        inferred_engine = infer_dreamweaver_video_engine_from_model_id(locked.video_model)
        if inferred_engine:
            video_cfg["engine"] = inferred_engine
        target["video_config"] = video_cfg

    qc_cfg = target.get("qc_config") if isinstance(target.get("qc_config"), dict) else {}
    qc_cfg = apply_vision_review_qc_config(
        qc_cfg,
        enabled=locked.enable_vision_review,
        vision_model=locked.vision_model,
    )
    if locked.enable_safety_audit is not None:
        qc_cfg["enable_safety_audit"] = bool(locked.enable_safety_audit)
    if locked.safety_fail_policy:
        qc_cfg["safety_fail_policy"] = locked.safety_fail_policy
    if qc_cfg:
        target["qc_config"] = qc_cfg

    video_edit_cfg = target.get("video_edit_config") if isinstance(target.get("video_edit_config"), dict) else {}
    if locked.video_edit_model:
        video_edit_cfg["adapter"] = locked.video_edit_model
    if locked.enable_video_edit is not None:
        video_edit_cfg["enabled"] = bool(locked.enable_video_edit)
    if video_edit_cfg:
        target["video_edit_config"] = video_edit_cfg
    return target
