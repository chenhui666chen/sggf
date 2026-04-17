from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from pipeline.media_presets import DREAMWEAVER_AUTO_ENGINE, DREAMWEAVER_I2V_ENGINE

from .contracts import (
    ProviderSelection,
    count_truthy,
    resolve_video_generation_controls,
)


_SELECTOR_SUPPORTED_ENGINES = {DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_AUTO_ENGINE}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _collect_subject_refs(shot: Mapping[str, Any], job: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for source in (
        shot.get("provider_subject_refs"),
        shot.get("subject_refs"),
        job.get("provider_subject_refs"),
    ):
        if not isinstance(source, list):
            continue
        for item in source:
            if item not in values:
                values.append(item)
    return values


def _existing_reference_count(job: Mapping[str, Any]) -> int:
    inputs = job.get("inputs") if isinstance(job.get("inputs"), Mapping) else {}
    if not isinstance(inputs, Mapping):
        return 0
    refs = []
    for key in ("head", "mid", "tail"):
        value = inputs.get(key)
        if not isinstance(value, str) or not value.strip():
            refs.append(False)
            continue
        refs.append(Path(value).exists())
    return count_truthy(refs)


def select_video_provider_for_shot(
    *,
    shot: Mapping[str, Any],
    job: Optional[Mapping[str, Any]],
    video_config: Mapping[str, Any],
) -> ProviderSelection:
    resolved = resolve_video_generation_controls(video_config)
    shot_id = str(shot.get("shot_id") or "").strip()
    provider_mode = str(resolved.get("provider_mode") or "wan_only")
    selector_mode = str(resolved.get("selector_mode") or "off")
    allow_kling_omni = bool(resolved.get("allow_kling_omni"))
    enable_kling_video_provider = bool(resolved.get("enable_kling_video_provider"))
    engine = _normalize_text(resolved.get("engine"))
    job_payload = dict(job or {})

    if provider_mode == "kling_omni":
        if not allow_kling_omni:
            return ProviderSelection(
                shot_id=shot_id,
                requested_provider_mode=provider_mode,
                selector_mode=selector_mode,
                recommended_provider="wan",
                applied_provider="wan",
                route="wan",
                reason="kling_omni_not_enabled",
                metadata={"engine": engine or "unknown"},
            )
        if not enable_kling_video_provider:
            return ProviderSelection(
                shot_id=shot_id,
                requested_provider_mode=provider_mode,
                selector_mode=selector_mode,
                recommended_provider="wan",
                applied_provider="wan",
                route="wan",
                reason="kling_video_provider_disabled",
                metadata={"engine": engine or "unknown"},
            )
        return ProviderSelection(
            shot_id=shot_id,
            requested_provider_mode=provider_mode,
            selector_mode=selector_mode,
            recommended_provider="kling",
            applied_provider="kling",
            route="kling_omni",
            reason="provider_mode_explicit",
            metadata={"engine": engine or "unknown"},
        )

    if engine not in _SELECTOR_SUPPORTED_ENGINES:
        return ProviderSelection(
            shot_id=shot_id,
            requested_provider_mode=provider_mode,
            selector_mode=selector_mode,
            recommended_provider="wan",
            applied_provider="wan",
            route="wan",
            reason="engine_not_supported_for_selector",
            metadata={"engine": engine or "unknown"},
        )

    if selector_mode == "off":
        return ProviderSelection(
            shot_id=shot_id,
            requested_provider_mode=provider_mode,
            selector_mode=selector_mode,
            recommended_provider="wan",
            applied_provider="wan",
            route="wan",
            reason="selector_mode_off",
        )

    if not allow_kling_omni:
        return ProviderSelection(
            shot_id=shot_id,
            requested_provider_mode=provider_mode,
            selector_mode=selector_mode,
            recommended_provider="wan",
            applied_provider="wan",
            route="wan",
            reason="kling_omni_not_enabled",
            metadata={"engine": engine or "unknown"},
        )

    requires_bridge = bool(job_payload.get("requires_bridge"))
    allow_subject_bridge = bool(resolved.get("allow_subject_bridge"))
    subject_refs = _collect_subject_refs(shot, job_payload) if allow_subject_bridge else []
    reference_count = _existing_reference_count(job_payload)
    reasons: list[str] = []
    if requires_bridge:
        reasons.append("bridge_transition")
    if subject_refs:
        reasons.append("subject_refs")
    explicit_reference_frames = job_payload.get("omni_reference_frames")
    if isinstance(explicit_reference_frames, list) and len(explicit_reference_frames) >= 2:
        reasons.append("multi_reference_frames")

    if provider_mode in {"auto", "kling_omni"} and reasons:
        return ProviderSelection(
            shot_id=shot_id,
            requested_provider_mode=provider_mode,
            selector_mode=selector_mode,
            recommended_provider="kling",
            applied_provider="wan",
            route="kling_omni",
            reason="+".join(reasons),
            shadowed=True,
            metadata={
                "engine": engine or "unknown",
                "requires_bridge": requires_bridge,
                "subject_ref_count": len(subject_refs),
                "reference_count": reference_count,
            },
        )

    return ProviderSelection(
        shot_id=shot_id,
        requested_provider_mode=provider_mode,
        selector_mode=selector_mode,
        recommended_provider="wan",
        applied_provider="wan",
        route="wan",
        reason="insufficient_kling_signals",
        metadata={
            "engine": engine or "unknown",
            "requires_bridge": requires_bridge,
            "subject_ref_count": len(subject_refs),
            "reference_count": reference_count,
        },
    )


def build_video_provider_trace(
    *,
    storyboard: Any,
    jobs_by_shot: Mapping[str, Mapping[str, Any]],
    video_config: Optional[Mapping[str, Any]],
    requested_shot_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    resolved = resolve_video_generation_controls(video_config)
    requested = {str(item).strip() for item in (requested_shot_ids or []) if str(item).strip()}
    shots: list[Dict[str, Any]] = []

    if isinstance(storyboard, list):
        for item in storyboard:
            if not isinstance(item, Mapping):
                continue
            shot_id = str(item.get("shot_id") or "").strip()
            if not shot_id:
                continue
            if requested and shot_id not in requested:
                continue
            selection = select_video_provider_for_shot(
                shot=item,
                job=jobs_by_shot.get(shot_id),
                video_config=resolved,
            )
            shots.append(selection.to_dict())

    return {
        "provider_mode": resolved.get("provider_mode", "wan_only"),
        "selector_mode": resolved.get("selector_mode", "off"),
        "allow_kling_omni": bool(resolved.get("allow_kling_omni")),
        "enable_kling_video_provider": bool(resolved.get("enable_kling_video_provider")),
        "allow_subject_bridge": bool(resolved.get("allow_subject_bridge")),
        "shots": shots,
    }
