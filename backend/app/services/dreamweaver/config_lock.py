from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.dreamweaver import DreamweaverProject as DreamweaverProjectModel
from pipeline.media_presets import normalize_frame_ratio, normalize_image_resolution
from pipeline.style_presets import normalize_style_preset

LIBRARY_ANCHOR_STATUS = "library"
LOCK_SCAN_LIMIT = 50


@dataclass(frozen=True)
class DreamweaverProjectLockedGenerationConfig:
    locked: bool
    style_preset: str
    image_ratio: str
    image_resolution: str
    source_run_id: Optional[str] = None


class DreamweaverProjectConfigLockedError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        locked: DreamweaverProjectLockedGenerationConfig,
        requested: Dict[str, Optional[str]],
        mismatches: Dict[str, Dict[str, str]],
    ) -> None:
        super().__init__(message)
        self.locked = locked
        self.requested = requested
        self.mismatches = mismatches


def _extract_generation_config_from_contract(contract: Dict[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    def _from_scope(scope: Any) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not isinstance(scope, dict):
            return None, None, None
        style_raw = scope.get("style_preset") if isinstance(scope.get("style_preset"), str) else None
        image_cfg = scope.get("image_config") if isinstance(scope.get("image_config"), dict) else {}
        ratio_raw = image_cfg.get("ratio") if isinstance(image_cfg.get("ratio"), str) else None
        resolution_raw = image_cfg.get("resolution") if isinstance(image_cfg.get("resolution"), str) else None
        return style_raw, ratio_raw, resolution_raw

    runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else None
    style_raw, ratio_raw, resolution_raw = _from_scope(runtime_cfg)
    has_any = bool((style_raw or "").strip()) or bool((ratio_raw or "").strip()) or bool((resolution_raw or "").strip())
    if has_any:
        return style_raw, ratio_raw, resolution_raw

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
            source_run_id=None,
        )

    fallback_run_id = str(rows[0].run_id)
    for row in rows:
        contract = row.contract_json if isinstance(row.contract_json, dict) else None
        if not contract:
            continue
        style_raw, ratio_raw, resolution_raw = _extract_generation_config_from_contract(contract)
        has_any = bool((style_raw or "").strip()) or bool((ratio_raw or "").strip()) or bool((resolution_raw or "").strip())
        if not has_any:
            continue
        return DreamweaverProjectLockedGenerationConfig(
            locked=True,
            style_preset=normalize_style_preset(style_raw),
            image_ratio=normalize_frame_ratio(ratio_raw),
            image_resolution=normalize_image_resolution(resolution_raw),
            source_run_id=str(row.run_id),
        )

    return DreamweaverProjectLockedGenerationConfig(
        locked=False,
        style_preset=default_style,
        image_ratio=default_ratio,
        image_resolution=default_resolution,
        source_run_id=fallback_run_id,
    )


def enforce_locked_generation_config_compatible(
    locked: DreamweaverProjectLockedGenerationConfig,
    *,
    style_preset: Optional[str],
    image_ratio: Optional[str],
    image_resolution: Optional[str],
) -> None:
    if not locked.locked:
        return

    requested = {
        "style_preset": style_preset.strip() if isinstance(style_preset, str) else None,
        "image_ratio": image_ratio.strip() if isinstance(image_ratio, str) else None,
        "image_resolution": image_resolution.strip() if isinstance(image_resolution, str) else None,
    }

    mismatches: Dict[str, Dict[str, str]] = {}
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
    target["image_config"] = image_cfg
    return target
