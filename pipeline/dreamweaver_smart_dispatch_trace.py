from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from agents.image_edit_utils import resolve_image_edit_adapter_name
from pipeline.media_presets import (
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_engine,
)


TRACE_KEY = "smart_dispatch_trace"
PHASES_KEY = "phases"


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _trim_or_none(value: Any) -> Optional[str]:
    text = _clean_text(value)
    return text or None


def _int_or(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _unique_strings(values: Iterable[Any]) -> List[str]:
    items: List[str] = []
    for value in values:
        text = _clean_text(value)
        if not text or text in items:
            continue
        items.append(text)
    return items


def _resolve_strategy(payload: Dict[str, Any], existing_trace: Optional[Dict[str, Any]] = None) -> str:
    raw = _clean_text(payload.get("quality_mode")).lower()
    if raw in {"quality", "cost", "balanced"}:
        return raw
    if isinstance(existing_trace, dict):
        existing = _clean_text(existing_trace.get("strategy")).lower()
        if existing in {"quality", "cost", "balanced"}:
            return existing
    return "balanced"


def _model_usage_order(model_ids: Iterable[Any]) -> Tuple[List[str], Dict[str, int]]:
    counts: Dict[str, int] = {}
    first_seen: Dict[str, int] = {}
    order: List[str] = []
    for idx, value in enumerate(model_ids):
        model_id = _clean_text(value)
        if not model_id:
            continue
        counts[model_id] = counts.get(model_id, 0) + 1
        first_seen.setdefault(model_id, idx)
    if not counts:
        return [], {}
    order = sorted(counts, key=lambda item: (-counts[item], first_seen[item], item))
    return order, counts


def _build_candidate_scores(model_ids: Iterable[Any], *, selected_model: Optional[str]) -> List[Dict[str, Any]]:
    order, counts = _model_usage_order(model_ids)
    scores: List[Dict[str, Any]] = []
    for idx, model_id in enumerate(order):
        scores.append(
            {
                "rank": idx + 1,
                "model_id": model_id,
                "total_score": float(counts.get(model_id, 0)),
                "selected": bool(selected_model and model_id == selected_model),
                "is_fallback": bool(selected_model and model_id != selected_model),
            }
        )
    return scores


def _choose_primary_model(model_ids: Iterable[Any]) -> Optional[str]:
    order, _counts = _model_usage_order(model_ids)
    return order[0] if order else None


def _build_fallback_chain(attempted_models: List[str]) -> Optional[Dict[str, Any]]:
    if not attempted_models:
        return None
    return {
        "total_attempts": len(attempted_models),
        "attempts": [
            {
                "attempt": idx + 1,
                "model_id": model_id,
            }
            for idx, model_id in enumerate(attempted_models)
        ],
    }


def _prompts_differ(before: Optional[str], after: Optional[str]) -> Optional[bool]:
    left = _clean_text(before)
    right = _clean_text(after)
    if not left and not right:
        return None
    if not left or not right:
        return bool(left != right)
    return left != right


def _build_prompt_trace(
    *,
    stage: str,
    model_id: Optional[str],
    prompt_before: Optional[str],
    prompt_after: Optional[str],
) -> Dict[str, Any]:
    changed = _prompts_differ(prompt_before, prompt_after)
    return {
        "stage": stage,
        "model_id": model_id,
        "prompt_before": _trim_or_none(prompt_before),
        "prompt_after": _trim_or_none(prompt_after) or _trim_or_none(prompt_before),
        "prompt_changed": changed,
    }


def _build_intent(
    *,
    payload: Dict[str, Any],
    modality: str,
    prompt: Optional[str],
) -> Dict[str, Any]:
    return {
        "task_id": _trim_or_none(payload.get("run_id")),
        "modality": modality,
        "prompt": _trim_or_none(prompt),
        "confidence": 1.0,
        "parse_errors": [],
    }


def _phase_stats(
    *,
    stage: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"stage": stage, "source": "dreamweaver_stage_artifacts"}
    if isinstance(extra, dict) and extra:
        base.update(extra)
    return base


def _pick_prompt_pair_from_records(records: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    for item in records:
        changed = item.get("prompt_changed")
        before = _trim_or_none(item.get("prompt_before"))
        after = _trim_or_none(item.get("prompt_after"))
        if changed is True and (before or after):
            return before, after
    for item in records:
        before = _trim_or_none(item.get("prompt_before"))
        after = _trim_or_none(item.get("prompt_after"))
        if before or after:
            return before, after
    return None, None


def _resolve_frame_model_id(*, payload: Dict[str, Any], role: str, via: str, mode: str) -> Optional[str]:
    image_cfg = _as_dict(payload.get("image_config"))
    t2i_model = _clean_text(image_cfg.get("adapter")) or "wan2.6-t2i"
    normalized_role = _clean_text(role).lower()
    normalized_via = _clean_text(via).lower()
    normalized_mode = _clean_text(mode).lower()

    if normalized_via == "multiperson_fusion" or normalized_mode == "multiperson_fusion":
        return "qwen_multiperson_fusion"
    if normalized_mode == "image_edit" or normalized_via == "image_edit":
        purpose = {
            "head": "keyframe_head",
            "tail": "keyframe_tail",
            "mid": "keyframe_mid",
        }.get(normalized_role, "keyframe_mid")
        return resolve_image_edit_adapter_name(
            image_cfg,
            purpose=purpose,
            default_adapter="wan_image_edit",
        )
    if normalized_mode == "reuse_head" or normalized_via == "reuse_head":
        return None
    return t2i_model


def _collect_frame_records(payload: Dict[str, Any], *, key: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for frame in _as_list(payload.get(key)):
        if not isinstance(frame, dict):
            continue
        meta = _as_dict(frame.get("meta"))
        spec = _as_dict(frame.get("spec"))
        ref = _as_dict(meta.get("ref"))
        rewrite = _as_dict(ref.get("rewrite"))
        role = _clean_text(meta.get("role"))
        via = _clean_text(meta.get("via"))
        decision = _as_dict(meta.get("decision"))
        mode = _clean_text(decision.get("mode")) or via
        prompt_before = _trim_or_none(spec.get("prompt"))
        prompt_after = _trim_or_none(rewrite.get("edit_prompt")) or _trim_or_none(rewrite.get("prompt")) or prompt_before
        records.append(
            {
                "role": role,
                "via": via,
                "mode": mode,
                "model_id": _resolve_frame_model_id(payload=payload, role=role, via=via, mode=mode),
                "prompt_before": prompt_before,
                "prompt_after": prompt_after,
                "prompt_changed": _prompts_differ(prompt_before, prompt_after),
                "safety_blocked": bool(meta.get("safety_blocked")),
            }
        )
    return records


def _build_frame_phase_trace(payload: Dict[str, Any], *, stage: str, key: str, default_modality: str) -> Dict[str, Any]:
    records = _collect_frame_records(payload, key=key)
    attempted_models = _unique_strings(item.get("model_id") for item in records)
    actual_model = _choose_primary_model(item.get("model_id") for item in records)
    image_cfg = _as_dict(payload.get("image_config"))
    selected_model = actual_model or _trim_or_none(image_cfg.get("adapter")) or "wan2.6-t2i"
    fallback_models = [item for item in attempted_models if item != selected_model]
    prompt_before, prompt_after = _pick_prompt_pair_from_records(records)
    prompt = _build_prompt_trace(
        stage=stage,
        model_id=actual_model or selected_model,
        prompt_before=prompt_before,
        prompt_after=prompt_after,
    )
    safety_blocked_count = sum(1 for item in records if item.get("safety_blocked"))
    reasons = _unique_strings(
        [
            "derived_from_frame_artifacts",
            *[f"mode:{item.get('mode')}" for item in records],
            *[f"via:{item.get('via')}" for item in records],
        ]
    )
    modality = default_modality
    if stage == "midframes" and any(_clean_text(item.get("mode")).lower() == "image_edit" for item in records):
        modality = "image_edit"

    routing = {
        "selected_model": selected_model,
        "fallback_models": fallback_models,
        "score": float(len(records)) if records else None,
        "base_score": float(len(records)) if records else None,
        "strategy": _resolve_strategy(payload),
        "candidate_scores": _build_candidate_scores((item.get("model_id") for item in records), selected_model=selected_model),
        "reasons": reasons,
    }
    execution = {
        "strategy": _resolve_strategy(payload),
        "resolved_model": actual_model or (result_model if attempted_models else None),
        "attempted_models": attempted_models,
        "timed_out": False,
        "prompt": prompt,
        "adapter": _phase_stats(
            stage=stage,
            extra={
                "frame_count": len(records),
                "roles": _unique_strings(item.get("role") for item in records),
                "modes": _unique_strings(item.get("mode") for item in records),
                "safety_blocked_count": safety_blocked_count,
            },
        ),
        "fallback_chain": _build_fallback_chain(attempted_models),
    }
    return {
        "stage": stage,
        "strategy": _resolve_strategy(payload),
        "intent": _build_intent(payload=payload, modality=modality, prompt=prompt.get("prompt_after") or prompt.get("prompt_before")),
        "routing": routing,
        "execution": execution,
    }


def _extract_storyboard_video_prompt_pair(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    for shot in _as_list(payload.get("storyboard")):
        if not isinstance(shot, dict):
            continue
        shot_meta = _as_dict(shot.get("shot_schema_v2_meta"))
        if not shot_meta:
            shot_schema = _as_dict(shot.get("shot_schema_v2"))
            shot_meta = _as_dict(shot_schema.get("meta"))
        prompt_after = _trim_or_none(shot_meta.get("video_prompt_generated"))
        if not prompt_after:
            continue
        prompt_before = (
            _trim_or_none(shot.get("video_prompt_override"))
            or _trim_or_none(shot.get("prompt"))
            or _trim_or_none(shot.get("desc"))
            or _trim_or_none(shot.get("motion_desc"))
        )
        return prompt_before, prompt_after
    return None, None


def _collect_video_clip_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    video_cfg = _as_dict(payload.get("video_config"))
    records: List[Dict[str, Any]] = []
    for clip in _as_list(payload.get("video_clips")):
        if not isinstance(clip, dict):
            continue
        meta = _as_dict(clip.get("meta"))
        model_id = (
            _trim_or_none(meta.get("adapter"))
            or _trim_or_none(meta.get("model"))
            or _trim_or_none(meta.get("engine"))
            or _trim_or_none(meta.get("via"))
            or _trim_or_none(video_cfg.get("adapter"))
        )
        engine = _trim_or_none(meta.get("engine")) or _trim_or_none(video_cfg.get("engine"))
        records.append(
            {
                "model_id": model_id,
                "engine": engine,
                "via": _trim_or_none(meta.get("via")),
                "provider": _trim_or_none(meta.get("provider")),
                "request_mode": _trim_or_none(meta.get("request_mode")),
                "prompt_after": _trim_or_none(meta.get("prompt")) or _trim_or_none(meta.get("motion_prompt")),
            }
        )
    return records


def _infer_video_modality(payload: Dict[str, Any], records: List[Dict[str, Any]]) -> str:
    request_modes = _unique_strings(item.get("request_mode") for item in records)
    if request_modes:
        if all(mode == "image_to_video" for mode in request_modes):
            return "image_to_video"
        if all(mode == "text_to_video" for mode in request_modes):
            return "text_to_video"

    engines = _unique_strings(item.get("engine") for item in records)
    if not engines:
        engine = normalize_dreamweaver_video_engine(_as_dict(payload.get("video_config")).get("engine"))
        engines = [engine] if engine else []

    if engines and all(is_dreamweaver_i2v_engine(item) for item in engines):
        return "image_to_video"
    if engines and all(is_dreamweaver_t2v_engine(item) for item in engines):
        return "text_to_video"
    return "video_generation"


def _build_video_phase_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
    records = _collect_video_clip_records(payload)
    attempted_models = _unique_strings(item.get("model_id") for item in records)
    actual_model = _choose_primary_model(item.get("model_id") for item in records)
    video_cfg = _as_dict(payload.get("video_config"))
    selected_model = actual_model or _trim_or_none(video_cfg.get("adapter")) or _trim_or_none(video_cfg.get("engine"))

    provider_trace = _as_dict(payload.get("video_provider_trace"))
    provider_shots = _as_list(provider_trace.get("shots"))
    shadow_models: List[str] = []
    reason_tokens: List[str] = ["derived_from_video_artifacts"]
    shadowed_shot_count = 0
    for shot in provider_shots:
        if not isinstance(shot, dict):
            continue
        recommended_provider = _clean_text(shot.get("recommended_provider")).lower()
        applied_provider = _clean_text(shot.get("applied_provider")).lower()
        route = _clean_text(shot.get("route"))
        reason = _clean_text(shot.get("reason"))
        if reason:
            reason_tokens.append(f"reason:{reason}")
        if route:
            reason_tokens.append(f"route:{route}")
        if bool(shot.get("shadowed")):
            shadowed_shot_count += 1
        if recommended_provider and recommended_provider != applied_provider:
            shadow_models.append(route or recommended_provider)

    fallback_models = _unique_strings([item for item in attempted_models if item != selected_model] + shadow_models)
    prompt_before, prompt_after = _extract_storyboard_video_prompt_pair(payload)
    if not prompt_after:
        prompt_after = next((item.get("prompt_after") for item in records if _trim_or_none(item.get("prompt_after"))), None)
    prompt = _build_prompt_trace(
        stage="video",
        model_id=actual_model or selected_model,
        prompt_before=prompt_before,
        prompt_after=prompt_after,
    )
    routing = {
        "selected_model": selected_model,
        "fallback_models": fallback_models,
        "score": float(len(records)) if records else None,
        "base_score": float(len(records)) if records else None,
        "strategy": _resolve_strategy(payload),
        "candidate_scores": _build_candidate_scores((item.get("model_id") for item in records), selected_model=selected_model),
        "reasons": _unique_strings(
            [
                *reason_tokens,
                f"provider_mode:{provider_trace.get('provider_mode')}" if provider_trace else "",
                f"selector_mode:{provider_trace.get('selector_mode')}" if provider_trace else "",
                *[f"engine:{item.get('engine')}" for item in records],
                *[f"via:{item.get('via')}" for item in records],
            ]
        ),
    }
    execution = {
        "strategy": _resolve_strategy(payload),
        "resolved_model": actual_model,
        "attempted_models": attempted_models,
        "timed_out": False,
        "prompt": prompt,
        "adapter": _phase_stats(
            stage="video",
            extra={
                "clip_count": len(records),
                "engines": _unique_strings(item.get("engine") for item in records),
                "provider_mode": _trim_or_none(provider_trace.get("provider_mode")),
                "selector_mode": _trim_or_none(provider_trace.get("selector_mode")),
                "actual_providers": _unique_strings(item.get("provider") for item in records),
                "shadowed_shot_count": shadowed_shot_count,
                "video_done": bool(payload.get("video_done")),
            },
        ),
        "fallback_chain": _build_fallback_chain(attempted_models),
    }
    return {
        "stage": "video",
        "strategy": _resolve_strategy(payload),
        "intent": _build_intent(
            payload=payload,
            modality=_infer_video_modality(payload, records),
            prompt=prompt.get("prompt_after") or prompt.get("prompt_before"),
        ),
        "routing": routing,
        "execution": execution,
    }


def _collect_video_edit_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for clip in _as_list(payload.get("video_clips")):
        if not isinstance(clip, dict):
            continue
        meta = _as_dict(clip.get("meta"))
        model_id = _trim_or_none(meta.get("edit_model"))
        edit_feature = _trim_or_none(meta.get("edit_feature"))
        prompt_after = _trim_or_none(meta.get("edit_prompt"))
        edited = bool(meta.get("edited")) or bool(model_id) or bool(edit_feature) or bool(prompt_after)
        if not edited:
            continue
        records.append(
            {
                "model_id": model_id,
                "edit_feature": edit_feature,
                "edit_feature_reason": _trim_or_none(meta.get("edit_feature_reason")),
                "prompt_after": prompt_after,
                "via": _trim_or_none(meta.get("via")),
            }
        )
    return records


def _build_edit_phase_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
    edit_result = _as_dict(payload.get("video_edit_result"))
    edit_cfg = _as_dict(payload.get("video_edit_config"))
    records = _collect_video_edit_records(payload)

    result_model = _trim_or_none(edit_result.get("model_id")) or _trim_or_none(edit_cfg.get("adapter"))
    requested_count = _int_or(edit_result.get("requested_count"), len(_as_list(edit_result.get("target_shot_ids"))))
    edited_count = _int_or(edit_result.get("edited_count"), len(records))
    failed_count = _int_or(edit_result.get("failed_count"))
    enabled = bool(edit_result.get("enabled")) if edit_result else bool(edit_cfg.get("enabled"))
    attempted_models = _unique_strings(
        [
            *(item.get("model_id") for item in records),
            result_model if result_model and enabled and requested_count > 0 else None,
        ]
    )
    actual_model = _choose_primary_model(item.get("model_id") for item in records) or (result_model if attempted_models else None)
    selected_model = actual_model or (result_model if result_model and (requested_count > 0 or enabled) else None)
    fallback_models = [item for item in attempted_models if item != selected_model]
    prompt_after = next((item.get("prompt_after") for item in records if _trim_or_none(item.get("prompt_after"))), None)
    prompt = _build_prompt_trace(stage="edit", model_id=actual_model or selected_model, prompt_before=None, prompt_after=prompt_after)
    feature_counts = _as_dict(edit_result.get("feature_counts"))
    status = _trim_or_none(edit_result.get("status")) or ("edited" if edited_count > 0 else "pass_through")

    routing = {
        "selected_model": selected_model,
        "fallback_models": fallback_models,
        "score": float(requested_count or edited_count) if (requested_count or edited_count) else None,
        "base_score": float(requested_count or edited_count) if (requested_count or edited_count) else None,
        "strategy": _resolve_strategy(payload),
        "candidate_scores": _build_candidate_scores(attempted_models or ([selected_model] if selected_model else []), selected_model=selected_model),
        "reasons": _unique_strings(
            [
                "derived_from_video_edit_artifacts",
                f"status:{status}" if status else "",
                f"source:{edit_result.get('source')}" if edit_result else "",
                f"reason:{edit_result.get('reason')}" if edit_result else "",
                *[f"feature:{item.get('edit_feature')}" for item in records],
                *[f"feature:{key}" for key in feature_counts.keys()],
            ]
        ),
    }
    execution = {
        "strategy": _resolve_strategy(payload),
        "resolved_model": actual_model,
        "attempted_models": attempted_models,
        "timed_out": False,
        "prompt": prompt,
        "adapter": _phase_stats(
            stage="edit",
            extra={
                "enabled": enabled,
                "status": status,
                "source": _trim_or_none(edit_result.get("source")),
                "reason": _trim_or_none(edit_result.get("reason")),
                "edit_feature": _trim_or_none(edit_result.get("edit_feature")),
                "default_edit_feature": _trim_or_none(edit_result.get("default_edit_feature")),
                "requested_count": requested_count,
                "edited_count": edited_count,
                "failed_count": failed_count,
                "target_shot_ids": _as_list(edit_result.get("target_shot_ids")),
                "attempted_shot_ids": _as_list(payload.get("video_edit_attempted_shot_ids")),
                "failed_shot_ids": _as_list(payload.get("video_edit_failed_shot_ids")),
                "feature_counts": feature_counts,
            },
        ),
        "fallback_chain": _build_fallback_chain(attempted_models),
    }
    return {
        "stage": "edit",
        "strategy": _resolve_strategy(payload),
        "intent": _build_intent(
            payload=payload,
            modality="video_edit",
            prompt=prompt.get("prompt_after"),
        ),
        "routing": routing,
        "execution": execution,
    }


def _build_review_phase_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
    audit = _as_dict(payload.get("audit"))
    safety_audit = _as_dict(audit.get("safety_audit"))
    model_id = _trim_or_none(safety_audit.get("model_id"))
    enabled = bool(safety_audit.get("enabled"))
    executed = bool(safety_audit.get("executed"))
    attempted_models = [model_id] if model_id and executed else []
    selected_model = model_id if (enabled or executed) else None
    prompt = _build_prompt_trace(stage="review", model_id=model_id, prompt_before=None, prompt_after=None)
    routing = {
        "selected_model": selected_model,
        "fallback_models": [],
        "score": 1.0 if selected_model else None,
        "base_score": 1.0 if selected_model else None,
        "strategy": _resolve_strategy(payload),
        "candidate_scores": _build_candidate_scores(attempted_models or ([selected_model] if selected_model else []), selected_model=selected_model),
        "reasons": _unique_strings(
            [
                "derived_from_review_artifacts",
                f"analysis_type:{safety_audit.get('analysis_type')}" if safety_audit else "",
                "safety_blocked" if safety_audit.get("blocked") else "",
                "warn_only" if safety_audit.get("warn_only") else "",
                *(_as_list(safety_audit.get("warnings"))),
                *(_as_list(safety_audit.get("categories"))),
            ]
        ),
    }
    execution = {
        "strategy": _resolve_strategy(payload),
        "resolved_model": model_id if executed else None,
        "attempted_models": attempted_models,
        "timed_out": False,
        "prompt": prompt,
        "adapter": _phase_stats(
            stage="review",
            extra={
                "enabled": enabled,
                "executed": executed,
                "blocked": bool(safety_audit.get("blocked")),
                "warn_only": bool(safety_audit.get("warn_only")),
                "fail_policy": _trim_or_none(safety_audit.get("fail_policy")),
                "analysis_type": _trim_or_none(safety_audit.get("analysis_type")),
                "categories": _as_list(safety_audit.get("categories")),
                "warnings": _as_list(safety_audit.get("warnings")),
            },
        ),
        "fallback_chain": _build_fallback_chain(attempted_models),
    }
    return {
        "stage": "review",
        "strategy": _resolve_strategy(payload),
        "intent": _build_intent(
            payload=payload,
            modality="video_analysis",
            prompt=_trim_or_none(safety_audit.get("summary")),
        ),
        "routing": routing,
        "execution": execution,
    }


def _build_phase_trace(payload: Dict[str, Any], *, stage: str) -> Optional[Dict[str, Any]]:
    if stage == "keyframes":
        return _build_frame_phase_trace(payload, stage=stage, key="keyframes", default_modality="text_to_image")
    if stage == "midframes":
        return _build_frame_phase_trace(payload, stage=stage, key="midframes", default_modality="text_to_image")
    if stage == "video":
        return _build_video_phase_trace(payload)
    if stage == "edit":
        return _build_edit_phase_trace(payload)
    if stage == "review":
        return _build_review_phase_trace(payload)
    return None


def initialize_dreamweaver_smart_dispatch_trace(payload: Dict[str, Any]) -> Dict[str, Any]:
    existing = payload.get(TRACE_KEY)
    trace = dict(existing) if isinstance(existing, dict) else {}
    strategy = _resolve_strategy(payload, trace)
    trace["stage"] = _trim_or_none(trace.get("stage")) or "init"
    trace["strategy"] = strategy

    intent = _as_dict(trace.get("intent"))
    intent.setdefault("task_id", _trim_or_none(payload.get("run_id")))
    intent.setdefault("modality", None)
    intent.setdefault("prompt", None)
    intent.setdefault("confidence", None)
    intent.setdefault("parse_errors", [])
    trace["intent"] = intent

    routing = _as_dict(trace.get("routing"))
    routing.setdefault("selected_model", None)
    routing.setdefault("fallback_models", [])
    routing.setdefault("strategy", strategy)
    routing.setdefault("candidate_scores", [])
    trace["routing"] = routing

    execution = _as_dict(trace.get("execution"))
    execution.setdefault("strategy", strategy)
    execution.setdefault("resolved_model", None)
    execution.setdefault("attempted_models", [])
    execution.setdefault("timed_out", None)
    execution.setdefault("prompt", None)
    execution.setdefault("adapter", None)
    execution.setdefault("fallback_chain", None)
    trace["execution"] = execution

    phases = _as_list(trace.get(PHASES_KEY))
    trace[PHASES_KEY] = [item for item in phases if isinstance(item, dict)]
    payload[TRACE_KEY] = trace
    return trace


def refresh_dreamweaver_smart_dispatch_trace(payload: Dict[str, Any], *, stage: str) -> Dict[str, Any]:
    trace = initialize_dreamweaver_smart_dispatch_trace(payload)
    phase = _build_phase_trace(payload, stage=stage)
    if phase is None:
        trace["stage"] = stage
        trace["strategy"] = _resolve_strategy(payload, trace)
        payload[TRACE_KEY] = trace
        return trace

    trace["stage"] = phase["stage"]
    trace["strategy"] = phase["strategy"]
    trace["intent"] = phase["intent"]
    trace["routing"] = phase["routing"]
    trace["execution"] = phase["execution"]

    phases = _as_list(trace.get(PHASES_KEY))
    updated = False
    for idx, item in enumerate(phases):
        if not isinstance(item, dict):
            continue
        if _clean_text(item.get("stage")) == phase["stage"]:
            phases[idx] = phase
            updated = True
            break
    if not updated:
        phases.append(phase)
    trace[PHASES_KEY] = phases
    payload[TRACE_KEY] = trace
    return trace
