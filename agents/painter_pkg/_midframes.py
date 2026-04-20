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

from agents.painter_pkg._utils import *
from agents.painter_pkg._t2i_pipeline import _generate_t2i_with_candidates
from agents.painter_pkg._edit_pipeline import _generate_edit_with_candidates, _collect_reference_image_paths
from agents.painter_pkg._library import (
    _library_assets,
    _match_library_refs_for_shot,
    _append_consistency_constraints,
    _ref_images_meta,
    _normalize_ref_issues,
    _selector_with_ref_issues,
    _drop_anchor_from_refs,
    _try_generate_multiperson_fusion_head,
)
from agents.painter_pkg._keyframes import run_keyframes

def run_midframes(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    run_dir = _ensure_run_dir(ctx)

    video_cfg = ctx.payload.get("video_config") if isinstance(ctx.payload.get("video_config"), dict) else {}
    video_engine = normalize_dreamweaver_video_engine(video_cfg.get("engine") or os.getenv("DREAMWEAVER_VIDEO_ENGINE") or "")
    if is_dreamweaver_generated_video_engine(video_engine):
        # Wan2.7 视频生成（I2V/T2V）不会用到 midframes；跳过以减少成本与耗时。
        ctx.payload["midframes"] = []
        return

    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    adapter = _resolve_runtime_model_id(
        image_cfg,
        key="adapter",
        env_name="DREAMWEAVER_T2I_MODEL",
        default="wan2.6-t2i",
    ) or "wan2.6-t2i"
    frame_width, frame_height, frame_ratio = resolve_frame_size(image_cfg)

    t2i_candidates = _cfg_int(image_cfg, "t2i_candidates", env_name="DREAMWEAVER_T2I_CANDIDATES", default=1)
    candidate_count = _cfg_int(image_cfg, "mid_candidates", env_name="DREAMWEAVER_MID_CANDIDATES", default=t2i_candidates)
    candidate_parallelism = _cfg_int(
        image_cfg,
        "candidate_parallelism",
        env_name="DREAMWEAVER_CANDIDATE_PARALLELISM",
        default=0,
    )
    if candidate_parallelism <= 0:
        candidate_parallelism = 2 if candidate_count > 1 else 1
    candidate_parallelism = max(1, min(int(candidate_parallelism), int(candidate_count)))
    image_edit_policy = _cfg_str(
        image_cfg,
        "image_edit_policy",
        env_name="DREAMWEAVER_IMAGE_EDIT_POLICY",
        default="auto",
    ).strip().lower()
    image_edit_min_prompt_similarity = _cfg_float(
        image_cfg,
        "image_edit_min_prompt_similarity",
        env_name="DREAMWEAVER_IMAGE_EDIT_MIN_PROMPT_SIMILARITY",
        default=0.0,
    )
    image_edit_min_prompt_similarity = max(0.0, min(float(image_edit_min_prompt_similarity), 1.0))
    image_edit_candidates = _cfg_int(
        image_cfg,
        "image_edit_candidates",
        env_name="DREAMWEAVER_IMAGE_EDIT_CANDIDATES",
        default=0,
    )
    if image_edit_candidates <= 0:
        image_edit_candidates = 1 if candidate_count <= 1 else min(2, int(candidate_count))
    image_edit_candidates = max(1, min(int(image_edit_candidates), int(candidate_count)))
    selector = _cfg_str(image_cfg, "image_selector", env_name="DREAMWEAVER_IMAGE_SELECTOR", default="first").strip().lower()
    keep_candidates = _cfg_flag(image_cfg, "keep_candidates", env_name="DREAMWEAVER_KEEP_CANDIDATES", default=False)
    max_refs = _cfg_int(image_cfg, "ref_max_images", env_name="DREAMWEAVER_REF_MAX_IMAGES", default=8)
    ref_selector = _cfg_str(image_cfg, "ref_selector", env_name="DREAMWEAVER_REF_SELECTOR", default="recent").strip().lower()
    mid_ref_rewrite = _cfg_flag(image_cfg, "mid_ref_rewrite", env_name="DREAMWEAVER_MID_REF_REWRITE", default=True)
    mid_min_variation = _cfg_str(image_cfg, "mid_min_variation", env_name="DREAMWEAVER_MID_MIN_VARIATION", default="medium").strip().lower()
    if mid_min_variation not in {"small", "medium", "large"}:
        mid_min_variation = "small"
    mid_min_variation_rank = {"small": 0, "medium": 1, "large": 2}.get(mid_min_variation, 0)

    use_mid_image_edit = _cfg_flag(image_cfg, "mid_use_image_edit", env_name="DREAMWEAVER_MID_USE_IMAGE_EDIT", default=False)
    image_edit_adapter_name_mid = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_mid",
        default_adapter="wan_image_edit",
    )
    image_edit_multi_ref_mid = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_mid,
    )
    image_edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg)
    max_refs_for_edit = max_refs
    if _is_qwen_image_edit_adapter_name(image_edit_adapter_name_mid):
        max_refs_for_edit = min(int(max_refs_for_edit), 2)
        image_edit_ref_max_images = min(int(image_edit_ref_max_images), 2)
    image_edit_adapter = None
    if use_mid_image_edit:
        image_edit_adapter = image_edit_adapter_name_mid if _model_client_available(image_edit_adapter_name_mid) else None

    vlm_adapter = None
    if selector in {"vlm", "semantic"} or ref_selector == "vlm":
        vlm_adapter = _resolve_runtime_model_id(
            image_cfg,
            key="vlm_adapter",
            env_name="DREAMWEAVER_VLM_ADAPTER",
            default="qwen3_vl_plus",
            require_available=True,
        )
    vlm_criteria = [
        s.strip()
        for s in os.getenv("DREAMWEAVER_VLM_CRITERIA", "clarity,composition,lighting,color,style").split(",")
        if s.strip()
    ]

    image_edit_strength = _cfg_float(image_cfg, "image_edit_strength", env_name="DREAMWEAVER_IMAGE_EDIT_STRENGTH", default=0.65)
    image_edit_guidance = _cfg_float(image_cfg, "image_edit_guidance", env_name="DREAMWEAVER_IMAGE_EDIT_GUIDANCE", default=7.5)

    style_prompt = str(ctx.payload.get("style_prompt") or "").strip() or "写实风格，电影质感，光影真实，高清细节，统一风格"
    style_negative_prompt = str(ctx.payload.get("style_negative_prompt") or "").strip()
    lib_assets = _library_assets_from_payload(ctx.payload)

    regen_shots_raw = ctx.payload.get("regenerate_shot_ids")
    regen_shots: List[str] = []
    if isinstance(regen_shots_raw, list):
        for item in regen_shots_raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in regen_shots:
                continue
            regen_shots.append(s)
            if len(regen_shots) >= 200:
                break
    regen_shot_set = set(regen_shots)

    existing_mid_by_shot: Dict[str, Dict[str, Any]] = {}
    existing_mid_raw = ctx.payload.get("midframes")
    if not isinstance(existing_mid_raw, list):
        existing_mid_raw = []
    for f in existing_mid_raw:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        p = Path(path)
        stem = p.stem
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not stem.endswith("_mid"):
            continue
        shot_key = stem[: -len("_mid")]
        if shot_key:
            existing_mid_by_shot[shot_key] = f

    mids: List[Dict[str, Any]] = []
    for item in ctx.payload.get("storyboard", []):
        if not isinstance(item, dict):
            continue
        shot_id = str(item.get("shot_id") or "")
        if not shot_id:
            continue
        shot_variation = str(item.get("variation_type") or "").strip().lower()
        shot_variation_rank = {"small": 0, "medium": 1, "large": 2}.get(shot_variation, 99)
        if shot_variation_rank < mid_min_variation_rank:
            continue
        ff_vis_char_ids = _as_str_list(item.get("ff_vis_char_ids"))
        mid_path = run_dir / f"{shot_id}_mid.png"
        if regen_shot_set and shot_id not in regen_shot_set:
            existing_mid = existing_mid_by_shot.get(shot_id)
            if isinstance(existing_mid, dict) and mid_path.exists():
                mids.append(existing_mid)
                continue
        bypass_hash_cache = bool(regen_shot_set and shot_id in regen_shot_set)
        prompt = str(item.get("desc") or "")
        asset_match = _match_library_assets_for_shot(
            shot=item,
            library_assets=lib_assets,
            max_character_refs=min(4, int(max_refs)),
        )
        prompt_fragment = str(asset_match.get("prompt_fragment") or "").strip()
        ref_images: List[Dict[str, Any]] = []
        for asset in (
            (asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else [])
            + (asset_match.get("scene_assets") if isinstance(asset_match.get("scene_assets"), list) else [])
            + (asset_match.get("prop_assets") if isinstance(asset_match.get("prop_assets"), list) else [])
        ):
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if not isinstance(path, Path) or not path.exists():
                continue
            ref_images.append({"path": path, "desc": str(asset.get("desc") or "").strip()})
            if len(ref_images) >= max(0, int(max_refs)):
                break
        library_refs_meta = _ref_images_meta(ref_images)
        mid_spec: Dict[str, Any] = {
            "prompt": f"{prompt}，过渡帧，{style_prompt}，{frame_ratio}",
            "ratio": frame_ratio,
            "subject_pos": {"x": 0.5, "y": 0.5},
        }
        base_prompt = prompt
        head_frame = item.get("head_frame")
        if isinstance(head_frame, dict) and head_frame.get("prompt"):
            base_prompt = str(head_frame.get("prompt") or prompt)
        mid_spec["prompt"] = _apply_prompt_fragment(
            f"{base_prompt}，中间过渡帧，{style_prompt}，{frame_ratio}",
            prompt_fragment,
        )
        head_path = run_dir / f"{shot_id}_head.png"
        mid_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
        mid_ref: Optional[Dict[str, Any]] = None
        mid_anchor_desc = f"本镜头 {shot_id} 的 head；prompt={base_prompt[:80]}"
        mid_anchor = {"path": head_path, "desc": mid_anchor_desc}
        mid_anchor_for_pack = mid_anchor if head_path.exists() else None
        mid_ref_pack, mid_ref_issues_raw = _build_reference_pack(anchor=mid_anchor_for_pack, match=asset_match)
        mid_ref_issues = _normalize_ref_issues(mid_ref_issues_raw, require_anchor=bool(mid_anchor_for_pack))
        mid_selector, mid_selector_degraded_reason = _selector_with_ref_issues(
            selector,
            vlm_adapter=vlm_adapter,
            ref_issues=mid_ref_issues,
        )
        mid_edit_ref_pack = _drop_anchor_from_refs(mid_ref_pack, mid_anchor_for_pack)
        if use_mid_image_edit and image_edit_adapter is None:
            mid_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
        elif use_mid_image_edit:
            mid_decision = _decide_image_mode(
                policy=image_edit_policy,
                base_image_path=head_path,
                base_spec=head_frame if isinstance(head_frame, dict) else None,
                target_spec=mid_spec,
                base_visible_chars=ff_vis_char_ids,
                target_visible_chars=ff_vis_char_ids,
                max_subject_pos_delta=0.0,
                min_prompt_similarity=image_edit_min_prompt_similarity,
                default_ratio=frame_ratio,
            )

        if mid_decision.get("mode") == "image_edit" and image_edit_adapter is not None and head_path.exists():
            mid_desc = mid_anchor_desc
            mid_edit_prompt = str(mid_spec["prompt"])
            mid_rewrite = None
            if ref_selector == "vlm" and mid_ref_rewrite and vlm_adapter is not None and ref_images:
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_mid", 1)
                _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(ref_images) + 1)
                mid_rewrite = _vlm_build_edit_prompt_from_base_and_refs(
                    vlm_adapter=vlm_adapter,
                    base_image_path=head_path,
                    base_image_desc=mid_desc,
                    target_description=mid_edit_prompt,
                    reference_images=ref_images,
                    max_refs=max_refs_for_edit,
                )
                if isinstance(mid_rewrite, dict) and isinstance(mid_rewrite.get("edit_prompt"), str):
                    mid_edit_prompt = str(mid_rewrite.get("edit_prompt") or mid_edit_prompt)

            selected_ref_images, selected_ref_indices = _selected_ref_images_from_pick(ref_images, mid_rewrite)
            selection_refs = mid_ref_pack
            mid_ref = {
                "base": {"uri": str(head_path), "desc": mid_desc},
                "library_refs": library_refs_meta,
                "selected_library_ref_indices": selected_ref_indices,
                "selected_library_refs": _ref_images_meta(selected_ref_images),
                "selection_refs": _ref_images_meta(selection_refs),
                "issues": mid_ref_issues,
                "rewrite": mid_rewrite,
            }
            try:
                mid_meta = _generate_edit_with_candidates(
                    adapter=image_edit_adapter,
                    image_path=head_path,
                    edit_prompt=mid_edit_prompt,
                    reference_desc=mid_desc,
                    strength=image_edit_strength,
                    guidance_scale=image_edit_guidance,
                    base_seed=None,
                    ctx=ctx,
                    shot_id=shot_id,
                    role="mid",
                    output_path=mid_path,
                    candidate_count=image_edit_candidates,
                    parallelism=candidate_parallelism,
                    selector=mid_selector,
                    vlm_adapter=vlm_adapter,
                    vlm_criteria=vlm_criteria,
                    reference_images=mid_edit_ref_pack,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                    use_multi_ref=image_edit_multi_ref_mid,
                    max_ref_images=image_edit_ref_max_images,
                )
            except Exception as exc:  # noqa: BLE001
                mid_meta = _generate_t2i_with_candidates(
                    adapter=adapter,
                    prompt=str(mid_spec["prompt"]),
                    negative_prompt=style_negative_prompt,
                    width=frame_width,
                    height=frame_height,
                    base_seed=None,
                    ctx=ctx,
                    shot_id=shot_id,
                    role="mid",
                    output_path=mid_path,
                    candidate_count=candidate_count,
                    parallelism=candidate_parallelism,
                    selector=mid_selector,
                    vlm_adapter=vlm_adapter,
                    vlm_criteria=vlm_criteria,
                    reference_images=selection_refs if selection_refs else ref_images,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                )
                mid_meta["fallback_error"] = str(exc)
        else:
            selection_refs = mid_ref_pack
            if selection_refs or ref_images:
                mid_ref = {
                    "base": {"uri": str(head_path), "desc": mid_anchor_desc} if head_path.exists() else None,
                    "library_refs": library_refs_meta,
                    "selected_library_ref_indices": None,
                    "selected_library_refs": _ref_images_meta(ref_images),
                    "selection_refs": _ref_images_meta(selection_refs),
                    "issues": mid_ref_issues,
                    "rewrite": None,
                }
            mid_meta = _generate_t2i_with_candidates(
                adapter=adapter,
                prompt=str(mid_spec["prompt"]),
                negative_prompt=style_negative_prompt,
                width=frame_width,
                height=frame_height,
                base_seed=None,
                ctx=ctx,
                shot_id=shot_id,
                role="mid",
                output_path=mid_path,
                candidate_count=candidate_count,
                parallelism=candidate_parallelism,
                selector=mid_selector,
                vlm_adapter=vlm_adapter,
                vlm_criteria=vlm_criteria,
                reference_images=selection_refs if selection_refs else ref_images,
                keep_candidates=keep_candidates,
                bypass_hash_cache=bypass_hash_cache,
            )

        mid_meta["selector_requested"] = selector
        mid_meta["selector_effective"] = mid_selector
        if mid_selector_degraded_reason:
            mid_meta["selector_degraded_reason"] = mid_selector_degraded_reason
        if mid_ref_issues:
            mid_meta["ref_issues"] = mid_ref_issues
        if shot_variation in {"small", "medium", "large"}:
            mid_meta["variation"] = {
                "type": shot_variation,
                "reason": str(item.get("variation_reason") or "").replace("\n", " ").strip(),
            }
        mids.append(
            {
                "path": str(mid_path),
                "ratio": frame_ratio,
                "spec": mid_spec,
                "meta": {"role": "mid", "ref": mid_ref, "decision": mid_decision, **mid_meta},
            }
        )
    ctx.payload["midframes"] = mids

    semantic_index = None
    try:
        from agents.semantic_asset_index import SemanticAssetIndex, is_semantic_retrieval_enabled, semantic_retrieval_config

        project_id = int(ctx.payload.get("project_id") or 0)
        if project_id > 0 and mids and is_semantic_retrieval_enabled(image_cfg=image_cfg):
            semantic_cfg = semantic_retrieval_config(image_cfg)
            semantic_index = SemanticAssetIndex(
                project_id=project_id,
                db_path=Path(semantic_cfg["db_path"]),
                dim=int(semantic_cfg.get("dim") or 256),
                max_items_per_project=int(semantic_cfg.get("max_items_per_project") or 5000),
                text_max_chars=int(semantic_cfg.get("text_max_chars") or 800),
            )
            index_items = _semantic_index_items_from_frames(frames=mids, run_id=str(ctx.run_id), max_items=400)
            if index_items:
                semantic_index.add_many(index_items)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if semantic_index is not None:
            semantic_index.close()
