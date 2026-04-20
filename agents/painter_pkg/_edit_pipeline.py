from __future__ import annotations

import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
import difflib
import json
import hashlib
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from adapters.adapter_helpers import (
    SimpleGenerationResult as GenerationResult,
    chat_messages,
    edit_image,
    generate_image,
    get_model_info,
    match_scene as match_scene_with_model,
    model_supports_capability,
)
from agents.best_image_selector import select_best_candidate as _select_best_candidate
from agents.camera_states import build_camera_states
from agents.camera_tree import build_camera_parent_map, build_camera_tree
from agents.reference_image_selector import (
    merge_reference_images as _merge_reference_images,
    selected_ref_images_from_pick as _selected_ref_images_from_pick,
    vlm_prefilter_reference_images_text_only as _vlm_prefilter_reference_images_text_only,
    vlm_build_edit_prompt_from_base_and_refs as _vlm_build_edit_prompt_from_base_and_refs,
    vlm_rewrite_t2i_prompt_from_references as _vlm_rewrite_t2i_prompt_from_references,
)
from agents.prompt_fragments import (
    apply_prompt_fragment as _apply_prompt_fragment,
    build_reference_pack as _build_reference_pack,
    library_assets_from_payload as _library_assets_from_payload,
    match_library_assets_for_shot as _match_library_assets_for_shot,
)
from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)
from pipeline.media_presets import (
    is_dreamweaver_generated_video_engine,
    normalize_dreamweaver_video_engine,
    ensure_media_payload,
    normalize_frame_ratio,
    resolve_frame_size,
)
from pipeline.artifacts_io import download_url_to_path as _download_url_to_path
from pipeline.style_presets import ensure_style_payload

from agents.painter_pkg._utils import (
    _ensure_run_dir,
    _ensure_telemetry_counters,
    _bump_telemetry_counter,
    _write_image_from_generation_result,
    _env_flag,
    _env_int,
    _cfg_flag,
    _cfg_int,
    _cfg_float,
    _cfg_str,
    _clone_adapter_instance,
    _close_adapter_session,
    _model_client_available,
    _resolve_runtime_model_id,
    _supports_multi_image_client,
    _generate_t2i_result,
    _generate_edit_result,
    _generate_candidates,
    _spec_prompt,
    _normalize_prompt_for_similarity,
    _prompt_similarity,
    _frame_ratio,
    _subject_pos,
    _subject_pos_delta,
    _decide_image_mode,
    _stable_seed,
    _derive_seed,
    _hash_cache_enabled,
    _hash_cache_dir,
    _adapter_fingerprint,
    _hash_cache_key,
    _try_restore_from_hash_cache,
    _save_to_hash_cache,
    _extract_score,
    _vlm_chat_json,
    _vlm_select_best_candidate_semantic,
    _clamp_prompt_text,
    _is_qwen_image_edit_adapter_name,
    _is_qwen_image_edit_adapter,
    _apply_image_edit_prompt_constraints,
    _finalize_candidates,
    _sanitize_prompt_for_safety,
    _is_safety_block_error,
    _write_png_placeholder,
)
from agents.painter_pkg._t2i_pipeline import _generate_t2i_with_candidates

def _collect_reference_image_paths(
    reference_images: Optional[List[Dict[str, Any]]],
    base_path: Path,
    max_images: int,
) -> List[str]:
    if not reference_images or max_images <= 0:
        return []
    base_str = str(base_path)
    seen: set[str] = set()
    out: List[str] = []
    for item in reference_images:
        if not isinstance(item, dict):
            continue
        raw = item.get("path")
        if isinstance(raw, Path):
            path_str = str(raw)
        elif isinstance(raw, str):
            path_str = raw.strip()
        else:
            continue
        if not path_str or path_str == base_str or path_str in seen:
            continue
        if not path_str.startswith(("http://", "https://")) and not Path(path_str).exists():
            continue
        seen.add(path_str)
        out.append(path_str)
        if len(out) >= int(max_images):
            break
    return out


def _generate_edit_with_candidates(
    *,
    adapter: Any,
    image_path: Path,
    edit_prompt: str,
    reference_desc: Optional[str] = None,
    strength: float,
    guidance_scale: float,
    base_seed: Any,
    ctx: Any,
    shot_id: str,
    role: str,
    output_path: Path,
    candidate_count: int,
    parallelism: int = 1,
    selector: str,
    vlm_adapter: Any,
    vlm_criteria: List[str],
    reference_images: Optional[List[Dict[str, Any]]] = None,
    keep_candidates: bool,
    enable_hash_cache: Optional[bool] = None,
    bypass_hash_cache: bool = False,
    use_multi_ref: bool = False,
    max_ref_images: int = 3,
) -> Dict[str, Any]:
    cache_enabled = _hash_cache_enabled(enable_hash_cache) and not bool(bypass_hash_cache)
    payload = ctx.payload if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict) else None
    raw_edit_prompt = edit_prompt
    edit_prompt, safety_meta = _sanitize_prompt_for_safety(edit_prompt)
    aggressive_edit_prompt: Optional[str] = None
    if _env_flag("DREAMWEAVER_SAFETY_AGGRESSIVE_FALLBACK", True):
        try:
            from adapters.content_safety_checker import check_and_fix_prompt

            aggressive_edit_prompt, _, _ = check_and_fix_prompt(raw_edit_prompt, strategy="aggressive")
            if not aggressive_edit_prompt or aggressive_edit_prompt == edit_prompt:
                aggressive_edit_prompt = None
        except Exception:  # noqa: BLE001
            aggressive_edit_prompt = None
    if payload is not None and safety_meta.get("issues"):
        _bump_telemetry_counter(payload, "image_edit_safety_fixes", 1)
    base_image_hash = ""
    if cache_enabled:
        base_image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    supports_multi_ref = _supports_multi_image_client(adapter)
    if _is_qwen_image_edit_adapter(adapter):
        max_ref_images = min(int(max_ref_images), 2)
    ref_paths = (
        _collect_reference_image_paths(reference_images, image_path, max_ref_images)
        if use_multi_ref and supports_multi_ref
        else []
    )
    if not ref_paths:
        use_multi_ref = False
    edit_prompt = _apply_image_edit_prompt_constraints(
        prompt=edit_prompt,
        adapter=adapter,
        ref_count=len(ref_paths),
    )
    ref_hashes: List[str] = []
    if cache_enabled and use_multi_ref:
        for ref_path in ref_paths:
            if ref_path.startswith(("http://", "https://")):
                ref_hashes.append(ref_path)
                continue
            try:
                ref_hashes.append(hashlib.sha256(Path(ref_path).read_bytes()).hexdigest())
            except Exception:  # noqa: BLE001
                continue
    if candidate_count <= 1:
        seed_value = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=0)
        cache_key = None
        if cache_enabled:
            cache_payload = {
                "kind": "image_edit",
                "adapter": _adapter_fingerprint(adapter),
                "image_sha256": base_image_hash,
                "edit_prompt": edit_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed_value),
            }
            if use_multi_ref:
                cache_payload["ref_images"] = ref_hashes
            cache_key = _hash_cache_key(cache_payload)
            if _try_restore_from_hash_cache(key=cache_key, out_path=output_path):
                if payload is not None:
                    _bump_telemetry_counter(payload, "image_edit_cache_hits", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "single",
                    "seed": seed_value,
                    "cache_hit": True,
                    "cache_key": cache_key,
                }
            if payload is not None:
                _bump_telemetry_counter(payload, "image_edit_cache_misses", 1)

        if payload is not None:
            _bump_telemetry_counter(payload, "image_edit_generate_calls", 1)
        used_fallback = False
        try:
            try:
                if use_multi_ref:
                    result = _generate_edit_result(
                        adapter=adapter,
                        image_path=image_path,
                        edit_prompt=edit_prompt,
                        strength=strength,
                        guidance_scale=guidance_scale,
                        seed=seed_value,
                        reference_images=ref_paths,
                    )
                else:
                    result = _generate_edit_result(
                        adapter=adapter,
                        image_path=image_path,
                        edit_prompt=edit_prompt,
                        strength=strength,
                        guidance_scale=guidance_scale,
                        seed=seed_value,
                    )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text) and aggressive_edit_prompt:
                    if use_multi_ref:
                        result = _generate_edit_result(
                            adapter=adapter,
                            image_path=image_path,
                            edit_prompt=aggressive_edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed_value,
                            reference_images=ref_paths,
                        )
                    else:
                        result = _generate_edit_result(
                            adapter=adapter,
                            image_path=image_path,
                            edit_prompt=aggressive_edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed_value,
                        )
                    used_fallback = True
                    if payload is not None:
                        _bump_telemetry_counter(payload, "image_edit_safety_retries", 1)
                else:
                    raise
            _write_image_from_generation_result(result, output_path)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if _is_safety_block_error(error_text):
                _write_png_placeholder(output_path, width=None, height=None)
                if payload is not None:
                    _bump_telemetry_counter(payload, "image_edit_safety_blocked", 1)
                return {
                    "candidate_count": 1,
                    "selected": 0,
                    "selector": "safety_placeholder",
                    "seed": seed_value,
                    "cache_hit": False if cache_enabled else None,
                    "cache_key": cache_key,
                    "safety_blocked": True,
                    "safety_error": error_text,
                }
            raise
        if used_fallback:
            cache_key = None
        if cache_enabled and cache_key:
            _save_to_hash_cache(key=cache_key, src_path=output_path)
        return {
            "candidate_count": 1,
            "selected": 0,
            "selector": "single",
            "seed": seed_value,
            "cache_hit": False if cache_enabled else None,
            "cache_key": cache_key,
        }

    cand_dir = output_path.parent / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    cache_hits = 0
    if cache_enabled:
        try:
            cache_dir = _hash_cache_dir()
            for idx in range(int(candidate_count)):
                seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
                cache_payload = {
                    "kind": "image_edit",
                    "adapter": _adapter_fingerprint(adapter),
                    "image_sha256": base_image_hash,
                    "edit_prompt": edit_prompt,
                    "strength": float(strength),
                    "guidance_scale": float(guidance_scale),
                    "seed": int(seed),
                }
                if use_multi_ref:
                    cache_payload["ref_images"] = ref_hashes
                key = _hash_cache_key(cache_payload)
                if (cache_dir / f"{key}.png").exists():
                    cache_hits += 1
        except Exception:  # noqa: BLE001
            cache_hits = 0

    workers = 1
    try:
        workers = int(parallelism)
    except Exception:  # noqa: BLE001
        workers = 1
    workers = max(1, min(workers, candidate_count))
    if workers > 1:
        probe = _clone_adapter_instance(adapter)
        if probe is None:
            workers = 1
        else:
            _close_adapter_session(probe)

    safety_blocked_any = False
    safety_error_sample: Optional[str] = None

    def _generate_one(idx: int) -> Path:
        nonlocal safety_blocked_any, safety_error_sample
        seed = _derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx)
        cand_path = cand_dir / f"{shot_id}_{role}_c{idx}.png"
        cache_key = None
        if cache_enabled:
            cache_payload = {
                "kind": "image_edit",
                "adapter": _adapter_fingerprint(adapter),
                "image_sha256": base_image_hash,
                "edit_prompt": edit_prompt,
                "strength": float(strength),
                "guidance_scale": float(guidance_scale),
                "seed": int(seed),
            }
            if use_multi_ref:
                cache_payload["ref_images"] = ref_hashes
            cache_key = _hash_cache_key(cache_payload)
            if _try_restore_from_hash_cache(key=cache_key, out_path=cand_path):
                return cand_path
        local_adapter = adapter
        if workers > 1:
            cloned = _clone_adapter_instance(adapter)
            if cloned is None:
                raise RuntimeError("adapter clone failed for parallel candidate generation")
            local_adapter = cloned
        try:
            used_fallback = False
            try:
                try:
                    if use_multi_ref:
                        result = _generate_edit_result(
                            adapter=local_adapter,
                            image_path=image_path,
                            edit_prompt=edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed,
                            reference_images=ref_paths,
                        )
                    else:
                        result = _generate_edit_result(
                            adapter=local_adapter,
                            image_path=image_path,
                            edit_prompt=edit_prompt,
                            strength=strength,
                            guidance_scale=guidance_scale,
                            seed=seed,
                        )
                except Exception as exc:  # noqa: BLE001
                    error_text = str(exc)
                    if _is_safety_block_error(error_text) and aggressive_edit_prompt:
                        if use_multi_ref:
                            result = _generate_edit_result(
                                adapter=local_adapter,
                                image_path=image_path,
                                edit_prompt=aggressive_edit_prompt,
                                strength=strength,
                                guidance_scale=guidance_scale,
                                seed=seed,
                                reference_images=ref_paths,
                            )
                        else:
                            result = _generate_edit_result(
                                adapter=local_adapter,
                                image_path=image_path,
                                edit_prompt=aggressive_edit_prompt,
                                strength=strength,
                                guidance_scale=guidance_scale,
                                seed=seed,
                            )
                        used_fallback = True
                        if payload is not None:
                            _bump_telemetry_counter(payload, "image_edit_safety_retries", 1)
                    else:
                        raise
                _write_image_from_generation_result(result, cand_path)
                if used_fallback:
                    cache_key = None
                if cache_enabled and cache_key:
                    _save_to_hash_cache(key=cache_key, src_path=cand_path)
                return cand_path
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                if _is_safety_block_error(error_text):
                    safety_blocked_any = True
                    if safety_error_sample is None:
                        safety_error_sample = error_text
                    _write_png_placeholder(cand_path, width=None, height=None)
                    return cand_path
                raise
        finally:
            if local_adapter is not adapter:
                _close_adapter_session(local_adapter)

    candidate_paths = _generate_candidates(candidate_count=candidate_count, parallelism=workers, generate_one=_generate_one)

    ref_desc = str(reference_desc or f"参考图（{image_path.name}）").strip()
    refs = [{"path": image_path, "desc": ref_desc}]
    if isinstance(reference_images, list) and reference_images:
        refs.extend(reference_images)
    pick = _select_best_candidate(
        candidate_paths=candidate_paths,
        selector=selector,
        vlm_adapter=vlm_adapter,
        vlm_criteria=vlm_criteria,
        target_description=edit_prompt,
        reference_images=refs,
        bump_telemetry=(
            (lambda n, d=1: _bump_telemetry_counter(ctx.payload, str(n), int(d)))
            if hasattr(ctx, "payload") and isinstance(getattr(ctx, "payload", None), dict)
            else None
        ),
    )
    candidate_seeds = [_derive_seed(base_seed=base_seed, ctx=ctx, shot_id=shot_id, role=role, idx=idx) for idx in range(candidate_count)]
    _finalize_candidates(
        candidate_paths=candidate_paths,
        output_path=output_path,
        best_index=int(pick["best_index"]),
        keep_candidates=keep_candidates,
    )
    if payload is not None:
        _bump_telemetry_counter(payload, "image_edit_generate_calls", int(candidate_count) - int(cache_hits))
        if cache_enabled:
            _bump_telemetry_counter(payload, "image_edit_cache_hits", int(cache_hits))
            _bump_telemetry_counter(payload, "image_edit_cache_misses", int(candidate_count) - int(cache_hits))
        if safety_blocked_any:
            _bump_telemetry_counter(payload, "image_edit_safety_blocked", 1)
    out = {
        "candidate_count": candidate_count,
        "selected": int(pick["best_index"]),
        "selector": pick["reason"],
        "scores": pick.get("scores"),
        "base_seed": base_seed if isinstance(base_seed, int) else None,
        "candidate_seeds": candidate_seeds,
        "selected_seed": candidate_seeds[int(pick["best_index"])] if isinstance(pick.get("best_index"), int) and 0 <= int(pick["best_index"]) < len(candidate_seeds) else None,
    }
    if safety_blocked_any:
        out["safety_blocked"] = True
        if safety_error_sample:
            out["safety_error"] = safety_error_sample
    if keep_candidates:
        out["candidates"] = [str(p) for p in candidate_paths]
    return out

