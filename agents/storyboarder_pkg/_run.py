from __future__ import annotations

import difflib
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_tree, build_camera_tree_llm
from agents.llm_client import (
    chat_completions,
    env_flag,
    extract_json_object,
    llm_stream_context,
    pick_model,
    resolve_llm_runtime_config,
)
from pipeline.media_presets import (
    DREAMWEAVER_AUTO_ENGINE,
    DREAMWEAVER_I2V_ENGINE,
    DREAMWEAVER_T2V_ENGINE,
    ensure_media_payload,
    is_dreamweaver_auto_engine,
    is_dreamweaver_i2v_engine,
    is_dreamweaver_t2v_engine,
    normalize_dreamweaver_video_duration_s,
    normalize_dreamweaver_video_engine,
    normalize_frame_ratio,
)
from pipeline.style_presets import ensure_style_payload

def run(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    source_text = str(ctx.payload.get("script_text") or ctx.payload.get("source_text") or "")
    style_preset = str(ctx.payload.get("style_preset") or "")
    style_prompt = str(ctx.payload.get("style_prompt") or "")
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    ratio = str(image_cfg.get("ratio") or "")
    quality_mode = str(ctx.payload.get("quality_mode") or "").strip().lower()
    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    video_engine = normalize_dreamweaver_video_engine(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "")
    uses_i2v_engine = is_dreamweaver_i2v_engine(video_engine)
    uses_t2v_engine = is_dreamweaver_t2v_engine(video_engine)
    uses_auto_engine = is_dreamweaver_auto_engine(video_engine)
    # Wan2.7 视频（I2V/T2V）通常需要将“镜头”量化为 5/10/15s 容器，并在单个 prompt 内用 subshots 表达多分镜。
    uses_video_containers = bool(uses_i2v_engine or uses_t2v_engine)
    engine_label = DREAMWEAVER_I2V_ENGINE if uses_i2v_engine else (DREAMWEAVER_T2V_ENGINE if uses_t2v_engine else "slideshow")
    if uses_auto_engine:
        uses_video_containers = True
        engine_label = DREAMWEAVER_AUTO_ENGINE

    enable_llm = env_flag("DREAMWEAVER_STORYBOARD_ENABLE_LLM", default=True)
    require_llm = env_flag("DREAMWEAVER_LLM_ONLY", default=False) or env_flag("DREAMWEAVER_STORYBOARD_REQUIRE_LLM", default=False)

    model = pick_model(primary_env="DREAMWEAVER_STORYBOARD_MODEL", fallback_env="DREAMWEAVER_SCRIPT_MODEL", default="qwen3.7-plus")
    llm_runtime = resolve_llm_runtime_config(model)
    api_key = llm_runtime.api_key
    base_url = llm_runtime.base_url
    timeout_s = int(os.getenv("DREAMWEAVER_STORYBOARD_TIMEOUT", "180") or "180")
    max_shots_raw = _env_int("DREAMWEAVER_STORYBOARD_MAX_SHOTS", 0)
    safety_max_shots = _storyboard_safety_max_shots(quality_mode=quality_mode)
    if max_shots_raw > 0:
        max_shots = max(1, int(max_shots_raw))
        max_shots_mode = "fixed"
    elif max_shots_raw < 0:
        # 允许 LLM 自主决定分镜数量，但仍保留 safety 上限防止输出失控。
        max_shots = None
        max_shots_mode = "unbounded"
    else:
        max_shots = _auto_max_shots_from_script(script_text=source_text, quality_mode=quality_mode)
        max_shots_mode = "auto"

    can_llm = bool(enable_llm and api_key and base_url)
    if require_llm and not can_llm:
        raise RuntimeError(
            f"storyboard require LLM but {llm_runtime.api_key_env}/{llm_runtime.base_url_env} missing"
        )

    min_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MIN_SHOT_S", 5.0 if uses_video_containers else 3.0)
    max_shot_s = _env_float("DREAMWEAVER_STORYBOARD_MAX_SHOT_S", 15.0 if uses_video_containers else 10.0)
    if uses_video_containers:
        min_shot_s = max(5.0, float(min_shot_s))
        max_shot_s = min(15.0, float(max_shot_s))
        if max_shot_s < min_shot_s:
            max_shot_s = min_shot_s
        # Wan2.7 视频通常只支持离散时长（5/10/15s），min/max 也需要归一化，避免出现 7s 这类无法落地的配置。
        min_shot_s = normalize_dreamweaver_video_duration_s(min_shot_s, default=5.0)
        max_shot_s = normalize_dreamweaver_video_duration_s(max_shot_s, default=15.0)
        if max_shot_s < min_shot_s:
            max_shot_s = min_shot_s

    base_s = _env_float("DREAMWEAVER_STORYBOARD_BASE_S", 2.0)
    cps = _env_float("DREAMWEAVER_STORYBOARD_CHARS_PER_SECOND", 20.0)

    shot_cap = int(max_shots) if isinstance(max_shots, int) and max_shots > 0 else int(max(1, int(safety_max_shots)))
    targets = _auto_storyboard_targets(
        source_text=source_text,
        quality_mode=quality_mode,
        uses_video_containers=uses_video_containers,
        engine_label=engine_label,
        min_shot_s=float(min_shot_s),
        max_shot_s=float(max_shot_s),
        shot_cap=shot_cap,
    )

    mode = "rule"
    llm_error: str | None = None
    llm_warnings: List[str] = []
    rebalance: Dict[str, Any] = {"enabled": False}
    storyboard: List[Dict[str, Any]] = []

    def _postprocess(sb: List[Dict[str, Any]]) -> Dict[str, Any]:
        _auto_adjust_storyboard_durations(sb, min_s=min_shot_s, max_s=max_shot_s, base_s=base_s, cps=cps)
        if uses_video_containers:
            for item in sb:
                if not isinstance(item, dict):
                    continue
                item["duration_s"] = normalize_dreamweaver_video_duration_s(item.get("duration_s"), default=float(min_shot_s))
        rebalance = _rebalance_storyboard_total_duration(
            sb,
            target_total_s=targets.get("target_total_s") if targets.get("enabled") else None,
            min_s=min_shot_s,
            max_s=max_shot_s,
            uses_video_containers=uses_video_containers,
            engine_label=engine_label,
            tolerance=0.15,
        )
        if uses_video_containers:
            _ensure_video_subshots_for_storyboard(sb)
        return rebalance

    too_short = ""
    if can_llm:
        retries_default = 1 if quality_mode == "quality" else 0
        max_retries = max(0, _env_int("DREAMWEAVER_STORYBOARD_LLM_RETRIES", retries_default))
        retry_reason: Optional[str] = None
        for attempt in range(max_retries + 1):
            try:
                character_profiles = ctx.payload.get("character_profiles")
                audio_markers = ctx.payload.get("audio_markers")
                storyboard = _llm_storyboard(
                    ctx,
                    source_text=source_text,
                    style_preset=style_preset,
                    style_prompt=style_prompt,
                    ratio=ratio,
                    entities=ctx.payload.get("script_entities"),
                    max_shots=max_shots,
                    safety_max_shots=safety_max_shots,
                    min_shots_hint=int(targets.get("min_shots_hint") or 0),
                    hint_max_shots=int(targets.get("hint_max_shots") or 0),
                    target_total_s=targets.get("target_total_s"),
                    uses_video_containers=uses_video_containers,
                    min_shot_s=float(min_shot_s),
                    max_shot_s=float(max_shot_s),
                    retry_reason=retry_reason,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=timeout_s,
                    character_profiles=character_profiles,
                    audio_markers=audio_markers,
                )
                mode = "llm"
            except Exception as exc:  # noqa: BLE001
                llm_error = f"{exc.__class__.__name__}: {exc}"
                if require_llm:
                    raise RuntimeError(f"storyboard LLM failed: {exc}") from exc
                storyboard = []
                break

            rebalance = _postprocess(storyboard)
            too_short = _storyboard_too_short_reason(
                storyboard,
                min_shots_hint=int(targets.get("min_shots_hint") or 0),
                target_total_s=targets.get("target_total_s"),
                tolerance=0.2,
            )
            if too_short and attempt < max_retries:
                llm_warnings.append(f"storyboard too short: {too_short}")
                retry_reason = too_short
                continue
            if too_short:
                llm_warnings.append(f"storyboard too short: {too_short}")
            break

        if (not storyboard) or (too_short and not require_llm):
            storyboard = _build_rule_storyboard(
                source_text=source_text,
                style_preset=style_preset,
                style_prompt=style_prompt,
                ratio=ratio,
                entities=ctx.payload.get("script_entities"),
                max_segments=shot_cap,
                min_segments=int(targets.get("min_shots_hint") or 0),
                uses_video_containers=uses_video_containers,
            )
            mode = "llm_fallback" if mode == "llm" else "rule_fallback"
            rebalance = _postprocess(storyboard)
    else:
        storyboard = _build_rule_storyboard(
            source_text=source_text,
            style_preset=style_preset,
            style_prompt=style_prompt,
            ratio=ratio,
            entities=ctx.payload.get("script_entities"),
            max_segments=shot_cap,
            min_segments=int(targets.get("min_shots_hint") or 0),
            uses_video_containers=uses_video_containers,
        )
        mode = "rule"
        rebalance = _postprocess(storyboard)

    qc_cfg = ctx.payload.get("qc_config") if isinstance(ctx.payload.get("qc_config"), dict) else {}
    max_pos_delta = qc_cfg.get("max_subject_pos_delta")
    try:
        max_pos_delta_value = float(max_pos_delta) if max_pos_delta is not None else 0.1
    except Exception:  # noqa: BLE001
        max_pos_delta_value = 0.1
    _smooth_storyboard_subject_pos(storyboard, max_delta=max_pos_delta_value)
    ctx.payload["storyboard_subject_pos"] = {"mode": "smooth", "max_delta": max_pos_delta_value}

    camera_tree_mode = str(os.getenv("DREAMWEAVER_CAMERA_TREE_MODE", "heuristic") or "heuristic").strip().lower()
    camera_tree = build_camera_tree(storyboard if isinstance(storyboard, list) else [])
    camera_tree_generation: Dict[str, Any] = {"mode": "heuristic", "model": None, "error": None}
    if camera_tree_mode == "llm":
        if can_llm:
            try:
                llm_tree = build_camera_tree_llm(
                    storyboard if isinstance(storyboard, list) else [],
                    ctx=ctx,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    timeout_s=min(120, int(timeout_s)),
                    max_shots_per_camera=int(os.getenv("DREAMWEAVER_CAMERA_TREE_LLM_MAX_SHOTS_PER_CAMERA", "6") or "6"),
                )
                if llm_tree:
                    camera_tree = llm_tree
                    camera_tree_generation = {"mode": "llm", "model": model, "error": None}
            except Exception as exc:  # noqa: BLE001
                camera_tree_generation = {"mode": "heuristic_fallback", "model": model, "error": str(exc)}
        else:
            camera_tree_generation = {"mode": "heuristic_fallback", "model": None, "error": "LLM not available"}
    if camera_tree:
        ctx.payload["camera_tree"] = camera_tree
        ctx.payload["camera_tree_generation"] = camera_tree_generation

    camera_states = build_camera_states(storyboard if isinstance(storyboard, list) else [], camera_tree if camera_tree else None)
    if camera_states:
        ctx.payload["camera_states"] = camera_states

    ctx.payload["storyboard"] = storyboard
    ctx.payload["storyboard_generation"] = {
        "mode": mode,
        "model": model if str(mode).startswith("llm") else None,
        "llm_error": llm_error,
        "llm_warnings": llm_warnings,
        "max_shots": max_shots,
        "max_shots_mode": max_shots_mode,
        "safety_max_shots": safety_max_shots,
        "targets": targets,
        "duration_rebalance": rebalance,
    }
