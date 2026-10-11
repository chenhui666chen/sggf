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

def run_keyframes(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    adapter = _resolve_runtime_model_id(
        image_cfg,
        key="adapter",
        env_name="DREAMWEAVER_T2I_MODEL",
        default="qwen-image-3.0-pro",
    ) or "qwen-image-3.0-pro"
    run_dir = _ensure_run_dir(ctx)
    frame_width, frame_height, frame_ratio = resolve_frame_size(image_cfg)

    candidate_count = _cfg_int(image_cfg, "t2i_candidates", env_name="DREAMWEAVER_T2I_CANDIDATES", default=1)
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
    qc_cfg = ctx.payload.get("qc_config") if isinstance(ctx.payload.get("qc_config"), dict) else {}
    try:
        max_subject_pos_delta = float(qc_cfg.get("max_subject_pos_delta") or 0.1)
    except Exception:  # noqa: BLE001
        max_subject_pos_delta = 0.1
    selector = _cfg_str(image_cfg, "image_selector", env_name="DREAMWEAVER_IMAGE_SELECTOR", default="first").strip().lower()
    keep_candidates = _cfg_flag(image_cfg, "keep_candidates", env_name="DREAMWEAVER_KEEP_CANDIDATES", default=False)
    max_refs = _cfg_int(image_cfg, "ref_max_images", env_name="DREAMWEAVER_REF_MAX_IMAGES", default=8)
    ref_history_tails = _cfg_int(image_cfg, "ref_history_tails", env_name="DREAMWEAVER_REF_HISTORY_TAILS", default=0)
    ref_history_tails = max(0, min(int(ref_history_tails), 12))
    ref_text_prefilter = _cfg_flag(image_cfg, "ref_text_prefilter", env_name="DREAMWEAVER_REF_TEXT_PREFILTER", default=True)
    ref_text_prefilter_pool = _cfg_int(image_cfg, "ref_text_prefilter_pool", env_name="DREAMWEAVER_REF_TEXT_PREFILTER_POOL", default=24)
    ref_text_prefilter_pool = max(int(max_refs), min(int(ref_text_prefilter_pool), 60))
    skip_tail_small_variation = _cfg_flag(
        image_cfg,
        "skip_tail_small_variation",
        env_name="DREAMWEAVER_SKIP_TAIL_SMALL_VARIATION",
        default=True,
    )
    variation_driven_image_edit = _cfg_flag(
        image_cfg,
        "variation_driven_image_edit",
        env_name="DREAMWEAVER_VARIATION_DRIVEN_IMAGE_EDIT",
        default=True,
    )

    use_head_image_edit = _cfg_flag(image_cfg, "head_use_image_edit", env_name="DREAMWEAVER_HEAD_USE_IMAGE_EDIT", default=False)
    use_tail_image_edit = _cfg_flag(image_cfg, "tail_use_image_edit", env_name="DREAMWEAVER_TAIL_USE_IMAGE_EDIT", default=False)
    enable_multiperson_fusion = _cfg_flag(
        image_cfg,
        "multiperson_fusion",
        env_name="DREAMWEAVER_ENABLE_MULTIPERSON_FUSION",
        default=False,
    )
    multiperson_fusion_use_anchor_scene = _cfg_flag(
        image_cfg,
        "multiperson_fusion_use_anchor_scene",
        env_name="DREAMWEAVER_MULTIPERSON_FUSION_USE_ANCHOR_SCENE",
        default=True,
    )
    multiperson_fusion_max_persons = _cfg_int(
        image_cfg,
        "multiperson_fusion_max_persons",
        env_name="DREAMWEAVER_MULTIPERSON_FUSION_MAX_PERSONS",
        default=3,
    )
    multiperson_fusion_max_persons = max(0, min(int(multiperson_fusion_max_persons), 6))
    ref_selector = _cfg_str(image_cfg, "ref_selector", env_name="DREAMWEAVER_REF_SELECTOR", default="recent").strip().lower()
    head_ref_rewrite = _cfg_flag(image_cfg, "head_ref_rewrite", env_name="DREAMWEAVER_HEAD_REF_REWRITE", default=True)
    tail_ref_rewrite = _cfg_flag(image_cfg, "tail_ref_rewrite", env_name="DREAMWEAVER_TAIL_REF_REWRITE", default=True)
    image_edit_adapter_name_head = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_head",
        default_adapter="wan_image_edit",
    )
    image_edit_adapter_name_tail = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="keyframe_tail",
        default_adapter="wan_image_edit",
    )
    image_edit_multi_ref_head = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_head,
    )
    image_edit_multi_ref_tail = resolve_image_edit_multi_ref(
        image_cfg=image_cfg,
        adapter_name=image_edit_adapter_name_tail,
    )
    image_edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg)
    max_refs_for_edit = max_refs
    if _is_qwen_image_edit_adapter_name(image_edit_adapter_name_head) or _is_qwen_image_edit_adapter_name(
        image_edit_adapter_name_tail
    ):
        max_refs_for_edit = min(int(max_refs_for_edit), 2)
        image_edit_ref_max_images = min(int(image_edit_ref_max_images), 2)

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

    lib_assets = _library_assets_from_payload(ctx.payload)

    image_edit_strength = _cfg_float(image_cfg, "image_edit_strength", env_name="DREAMWEAVER_IMAGE_EDIT_STRENGTH", default=0.65)
    image_edit_guidance = _cfg_float(image_cfg, "image_edit_guidance", env_name="DREAMWEAVER_IMAGE_EDIT_GUIDANCE", default=7.5)

    style_negative_prompt = str(ctx.payload.get("style_negative_prompt") or "").strip()

    semantic_index = None
    semantic_cfg: Optional[Dict[str, Any]] = None
    try:
        from agents.semantic_asset_index import SemanticAssetIndex, is_semantic_retrieval_enabled, semantic_retrieval_config

        project_id = int(ctx.payload.get("project_id") or 0)
        if project_id > 0 and is_semantic_retrieval_enabled(image_cfg=image_cfg):
            semantic_cfg = semantic_retrieval_config(image_cfg)
            semantic_index = SemanticAssetIndex(
                project_id=project_id,
                db_path=Path(semantic_cfg["db_path"]),
                dim=int(semantic_cfg.get("dim") or 256),
                max_items_per_project=int(semantic_cfg.get("max_items_per_project") or 5000),
                text_max_chars=int(semantic_cfg.get("text_max_chars") or 800),
            )

            # 预热：把已审核通过的素材库图写入索引（同项目二次生成即可直接命中）
            lib_items: List[Dict[str, Any]] = []
            for asset in lib_assets:
                if not isinstance(asset, dict):
                    continue
                path = asset.get("path")
                if not isinstance(path, Path) or not path.exists():
                    continue
                role = str(asset.get("role") or "").strip()
                entity_type = str(asset.get("entity_type") or "").strip()
                name = str(asset.get("entity_name") or "").strip()
                descriptor = str(asset.get("descriptor") or "").strip()
                text = " ".join([s for s in [entity_type, name, role, descriptor] if s]).strip()
                if not text:
                    continue
                lib_items.append(
                    {
                        "kind": "library_asset",
                        "path": path,
                        "text": text,
                        "meta": {
                            "role": role,
                            "entity_type": entity_type,
                            "entity_name": name,
                            "descriptor": descriptor,
                        },
                    }
                )
                if len(lib_items) >= 200:
                    break
            if lib_items:
                semantic_index.add_many(lib_items)
    except Exception:  # noqa: BLE001
        semantic_index = None
        semantic_cfg = None

    storyboard = ctx.payload.get("storyboard", [])
    camera_tree = ctx.payload.get("camera_tree")
    if not isinstance(camera_tree, list) or not any(isinstance(n, dict) and isinstance(n.get("cam_idx"), int) for n in camera_tree):
        camera_tree = build_camera_tree(storyboard if isinstance(storyboard, list) else [])
    camera_parent_map = build_camera_parent_map(camera_tree)
    if camera_tree:
        ctx.payload["camera_tree"] = camera_tree

    camera_states = ctx.payload.get("camera_states")
    needs_rebuild_camera_states = not isinstance(camera_states, list) or not camera_states
    if not needs_rebuild_camera_states:
        has_dep_fields = False
        for track in camera_states:
            if not isinstance(track, dict):
                continue
            states = track.get("states") if isinstance(track.get("states"), list) else []
            for state in states:
                if not isinstance(state, dict):
                    continue
                if "depends_on_state_ids" in state or "anchor_shot_id" in state or "anchor_source" in state:
                    has_dep_fields = True
                    break
            if has_dep_fields:
                break
        if not has_dep_fields:
            needs_rebuild_camera_states = True

    if needs_rebuild_camera_states:
        camera_states = build_camera_states(
            storyboard if isinstance(storyboard, list) else [],
            camera_tree if isinstance(camera_tree, list) and camera_tree else None,
        )
    if camera_states:
        ctx.payload["camera_states"] = camera_states

    camera_state_by_shot_id: Dict[str, Dict[str, Any]] = {}
    for track in camera_states or []:
        if not isinstance(track, dict):
            continue
        states = track.get("states") if isinstance(track.get("states"), list) else []
        for state in states:
            if not isinstance(state, dict):
                continue
            sid = str(state.get("shot_id") or state.get("state_id") or "").strip()
            if not sid or sid in camera_state_by_shot_id:
                continue
            camera_state_by_shot_id[sid] = state

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

    def _shot_key_and_role(path: str) -> Tuple[Optional[str], Optional[str]]:
        p = Path(path)
        stem = p.stem
        suffix = p.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            return None, None
        if stem.endswith("_head"):
            return stem[: -len("_head")], "head"
        if stem.endswith("_tail"):
            return stem[: -len("_tail")], "tail"
        if stem.endswith("_mid"):
            return stem[: -len("_mid")], "mid"
        return None, None

    existing_keyframes_by_shot: Dict[str, Dict[str, Dict[str, Any]]] = {}
    existing_keyframes_raw = ctx.payload.get("keyframes")
    if not isinstance(existing_keyframes_raw, list):
        existing_keyframes_raw = []
    for f in existing_keyframes_raw:
        if not isinstance(f, dict):
            continue
        path = f.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        shot_key, role = _shot_key_and_role(path)
        if not shot_key or role not in {"head", "tail"}:
            continue
        existing_keyframes_by_shot.setdefault(shot_key, {})[role] = f

    keyframes_parallelism = _cfg_int(
        image_cfg,
        "shot_parallelism",
        env_name="DREAMWEAVER_KEYFRAMES_PARALLELISM",
        default=1,
    )
    if not isinstance(storyboard, list):
        keyframes_parallelism = 1
    keyframes_parallelism = max(1, min(int(keyframes_parallelism), len(storyboard) if isinstance(storyboard, list) else 1))
    if isinstance(storyboard, list) and storyboard:
        plans: List[Dict[str, Any]] = []
        shot_history_by_cam: Dict[int, List[str]] = {}
        prev_tail_prompt_by_shot: Dict[str, str] = {}
        tail_spec_by_shot: Dict[str, Dict[str, Any]] = {}
        lf_vis_by_shot: Dict[str, List[str]] = {}

        for item in storyboard:
            if not isinstance(item, dict):
                continue
            shot_id = str(item.get("shot_id") or "")
            cam_idx = 0
            try:
                cam_idx = int(item.get("cam_idx") or item.get("camera_index") or 0)
            except Exception:  # noqa: BLE001
                cam_idx = 0
            parent_cam_idx = camera_parent_map.get(cam_idx)
            head_spec = item.get("head_frame")
            tail_spec = item.get("tail_frame")
            if not shot_id or not isinstance(head_spec, dict) or not isinstance(tail_spec, dict):
                raise ValueError("invalid storyboard item: missing shot_id/head_frame/tail_frame")

            ff_vis_char_ids = _as_str_list(item.get("ff_vis_char_ids"))
            lf_vis_char_ids = _as_str_list(item.get("lf_vis_char_ids"))

            # R-pre 候选择优门位（Phase 2.4）：高价值 beat 双候选，普通镜头沿用基础配置
            from agents.painter_pkg._r_pre import r_pre_candidate_count
            shot_candidate_count = r_pre_candidate_count(item, candidate_count)
            shot_edit_candidates = max(1, min(int(image_edit_candidates), int(shot_candidate_count)))

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

            head_prompt = _apply_prompt_fragment(str(head_spec.get("prompt") or ""), prompt_fragment)
            tail_prompt = _apply_prompt_fragment(str(tail_spec.get("prompt") or ""), prompt_fragment)
            state_before = str(item.get("state_before") or "").strip()
            state_after = str(item.get("state_after") or "").strip()
            if state_before:
                head_prompt = _apply_prompt_fragment(head_prompt, f"状态约束（镜头开始）：{state_before}")
            if state_after:
                tail_prompt = _apply_prompt_fragment(tail_prompt, f"状态约束（镜头结束）：{state_after}")
            tail_prompt_for_state = tail_prompt or head_prompt

            state = camera_state_by_shot_id.get(shot_id)
            anchor_shot_id: Optional[str] = None
            anchor_source = "none"
            depends_on_state_ids: List[str] = []
            if isinstance(state, dict):
                raw_anchor = state.get("anchor_shot_id")
                if isinstance(raw_anchor, str) and raw_anchor.strip():
                    anchor_shot_id = raw_anchor.strip()
                anchor_source = str(state.get("anchor_source") or "none").strip() or "none"
                depends_on_state_ids = _as_str_list(state.get("depends_on_state_ids"))
            if not depends_on_state_ids and isinstance(anchor_shot_id, str) and anchor_shot_id.strip():
                depends_on_state_ids = [anchor_shot_id.strip()]

            head_base_desc = ""
            head_base_spec: Optional[Dict[str, Any]] = None
            head_base_visible_chars: List[str] = []
            if anchor_shot_id:
                base_prompt = str(prev_tail_prompt_by_shot.get(anchor_shot_id) or "").strip()
                head_base_spec = tail_spec_by_shot.get(anchor_shot_id) if isinstance(tail_spec_by_shot.get(anchor_shot_id), dict) else None
                head_base_visible_chars = _as_str_list(lf_vis_by_shot.get(anchor_shot_id))
                if anchor_source == "camera_last_tail":
                    head_base_desc = f"同相机{cam_idx} 上一次镜头{anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "camera_tree_parent_shot":
                    head_base_desc = f"相机树依赖：父相机{parent_cam_idx} 镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "parent_camera_tail":
                    head_base_desc = f"父相机{parent_cam_idx} 镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"
                elif anchor_source == "previous_shot_tail":
                    head_base_desc = f"上一镜头 {anchor_shot_id} 的尾帧；prompt={base_prompt[:80]}"

            history_refs: List[Dict[str, Any]] = []
            if ref_history_tails > 0:
                def _push_history(cam: Optional[int], *, label: str) -> None:
                    if not isinstance(cam, int):
                        return
                    hist = shot_history_by_cam.get(int(cam))
                    if not isinstance(hist, list) or not hist:
                        return
                    for sid in reversed(hist[-ref_history_tails:]):
                        if not isinstance(sid, str) or not sid.strip():
                            continue
                        base_prompt = str(prev_tail_prompt_by_shot.get(sid) or "").strip()
                        desc = f"{label} 镜头{sid} 的尾帧；prompt={base_prompt[:80]}" if base_prompt else f"{label} 镜头{sid} 的尾帧"
                        history_refs.append({"path": run_dir / f"{sid}_tail.png", "desc": desc})

                _push_history(int(cam_idx), label=f"同相机{cam_idx} 历史")
                if isinstance(parent_cam_idx, int):
                    _push_history(int(parent_cam_idx), label=f"父相机{parent_cam_idx} 历史")

            semantic_retrieval: Optional[Dict[str, Any]] = None
            if semantic_index is not None and isinstance(semantic_cfg, dict):
                try:
                    exclude_paths: List[Path] = []
                    for ref in ref_images + history_refs:
                        p = ref.get("path") if isinstance(ref, dict) else None
                        if isinstance(p, Path):
                            exclude_paths.append(p)

                    hits = semantic_index.query(
                        text=head_prompt or str(head_spec.get("prompt") or ""),
                        top_k=int(semantic_cfg.get("top_k") or 0),
                        min_score=float(semantic_cfg.get("min_score") or 0.0),
                        kinds=["frame", "library_asset"],
                        exclude_paths=exclude_paths,
                    )
                    _bump_telemetry_counter(ctx.payload, "semantic_retrieval_queries", 1)

                    max_add = max(0, int(semantic_cfg.get("max_additional_refs") or 0))
                    added = 0
                    add_library: List[Dict[str, Any]] = []
                    add_history: List[Dict[str, Any]] = []
                    hit_meta: List[Dict[str, Any]] = []
                    existing_roles: set[str] = set()
                    for group_key in ("character_assets", "scene_assets", "prop_assets"):
                        group = asset_match.get(group_key) if isinstance(asset_match.get(group_key), list) else []
                        for item0 in group:
                            if not isinstance(item0, dict):
                                continue
                            r0 = str(item0.get("role") or "").strip()
                            if r0:
                                existing_roles.add(r0)
                    for h in hits:
                        if max_add and added >= max_add:
                            break
                        path = getattr(h, "path", None)
                        if not isinstance(path, Path) or not path.exists():
                            continue
                        kind = str(getattr(h, "kind", "") or "").strip() or "frame"
                        score = float(getattr(h, "score", 0.0))
                        meta = getattr(h, "meta", {}) if isinstance(getattr(h, "meta", None), dict) else {}
                        label = meta.get("role") or meta.get("frame_role") or meta.get("entity_name") or meta.get("entity_type") or kind
                        label = str(label or "").strip()
                        desc = f"[语义检索] score={score:.3f} {label}"
                        cand = {"path": path, "desc": desc}
                        if kind == "library_asset":
                            add_library.append(cand)
                            role = str(meta.get("role") or "").strip()
                            entity_type = str(meta.get("entity_type") or "").strip().lower()
                            entity_name = str(meta.get("entity_name") or "").strip()
                            descriptor = str(meta.get("descriptor") or "").strip()
                            if role and role not in existing_roles and entity_type in {"character", "scene", "prop"}:
                                asset_item = {
                                    "role": role,
                                    "entity_type": entity_type,
                                    "entity_name": entity_name,
                                    "descriptor": descriptor,
                                    "path": path,
                                    "desc": desc,
                                }
                                if entity_type == "character":
                                    asset_match.setdefault("character_assets", [])
                                    if isinstance(asset_match.get("character_assets"), list):
                                        asset_match["character_assets"].append(asset_item)
                                elif entity_type == "scene":
                                    asset_match.setdefault("scene_assets", [])
                                    if isinstance(asset_match.get("scene_assets"), list):
                                        asset_match["scene_assets"].append(asset_item)
                                else:
                                    asset_match.setdefault("prop_assets", [])
                                    if isinstance(asset_match.get("prop_assets"), list):
                                        asset_match["prop_assets"].append(asset_item)
                                existing_roles.add(role)
                        else:
                            add_history.append(cand)
                        hit_meta.append(
                            {
                                "score": score,
                                "kind": kind,
                                "uri": str(path),
                                "label": label,
                                "meta": meta,
                            }
                        )
                        added += 1

                    if hit_meta:
                        _bump_telemetry_counter(ctx.payload, "semantic_retrieval_hits", len(hit_meta))
                    if add_library:
                        ref_images = add_library + ref_images
                    if add_history:
                        history_refs = add_history + history_refs

                    if hit_meta:
                        semantic_retrieval = {
                            "enabled": True,
                            "query": (head_prompt or str(head_spec.get("prompt") or "")).strip()[:240],
                            "top_k": int(semantic_cfg.get("top_k") or 0),
                            "min_score": float(semantic_cfg.get("min_score") or 0.0),
                            "added_refs": int(added),
                            "hits": hit_meta,
                        }
                except Exception as exc:  # noqa: BLE001
                    semantic_retrieval = {"enabled": True, "error": str(exc)}

            library_refs_meta = _ref_images_meta(ref_images)

            variation_type = str(item.get("variation_type") or "").strip().lower()
            if variation_type not in {"small", "medium", "large"}:
                variation_type = ""
            variation_reason = str(item.get("variation_reason") or "").replace("\n", " ").strip()
            if len(variation_reason) > 240:
                variation_reason = variation_reason[:240]

            bypass_hash_cache = bool(regen_shot_set and shot_id in regen_shot_set)
            plans.append(
                {
                    "shot_id": shot_id,
                    "cam_idx": int(cam_idx),
                    "parent_cam_idx": parent_cam_idx,
                    "head_spec": head_spec,
                    "tail_spec": tail_spec,
                    "ff_vis_char_ids": ff_vis_char_ids,
                    "lf_vis_char_ids": lf_vis_char_ids,
                    "ref_images": ref_images,
                    "library_refs_meta": library_refs_meta,
                    "asset_match": asset_match,
                    "prompt_fragment": prompt_fragment,
                    "head_prompt": head_prompt,
                    "tail_prompt": tail_prompt,
                    "variation_type": variation_type,
                    "variation_reason": variation_reason,
                    "anchor_shot_id": anchor_shot_id,
                    "anchor_source": anchor_source,
                    "depends_on_state_ids": depends_on_state_ids,
                    "history_refs": history_refs,
                    "head_base_desc": head_base_desc,
                    "head_base_spec": head_base_spec,
                    "head_base_visible_chars": head_base_visible_chars,
                    "bypass_hash_cache": bypass_hash_cache,
                    "semantic_retrieval": semantic_retrieval,
                }
            )

            prev_tail_prompt_by_shot[shot_id] = tail_prompt_for_state
            tail_spec_by_shot[shot_id] = tail_spec
            lf_vis_by_shot[shot_id] = lf_vis_char_ids
            shot_history_by_cam.setdefault(int(cam_idx), []).append(shot_id)

        results_by_shot: Dict[str, Dict[str, Dict[str, Any]]] = {}
        completed: set[str] = set()
        remaining: Dict[str, Dict[str, Any]] = {}
        for plan in plans:
            shot_id = str(plan.get("shot_id") or "")
            if not shot_id:
                continue
            head_path = run_dir / f"{shot_id}_head.png"
            tail_path = run_dir / f"{shot_id}_tail.png"
            if regen_shot_set and shot_id not in regen_shot_set:
                existing = existing_keyframes_by_shot.get(shot_id) if isinstance(existing_keyframes_by_shot.get(shot_id), dict) else None
                existing_head = existing.get("head") if isinstance(existing, dict) else None
                existing_tail = existing.get("tail") if isinstance(existing, dict) else None
                if isinstance(existing_head, dict) and isinstance(existing_tail, dict) and head_path.exists() and tail_path.exists():
                    results_by_shot[shot_id] = {"head": existing_head, "tail": existing_tail}
                    completed.add(shot_id)
                    continue
            remaining[shot_id] = plan

        def _render_one(shot_plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
            shot_id = str(shot_plan.get("shot_id") or "")
            cam_idx = int(shot_plan.get("cam_idx") or 0)
            parent_cam_idx = shot_plan.get("parent_cam_idx")
            head_spec = shot_plan.get("head_spec")
            tail_spec = shot_plan.get("tail_spec")
            if not shot_id or not isinstance(head_spec, dict) or not isinstance(tail_spec, dict):
                raise ValueError("invalid shot_plan: missing shot_id/head_spec/tail_spec")

            ff_vis_char_ids = _as_str_list(shot_plan.get("ff_vis_char_ids"))
            lf_vis_char_ids = _as_str_list(shot_plan.get("lf_vis_char_ids"))
            ref_images = shot_plan.get("ref_images", [])
            constraints = shot_plan.get("constraints", [])
            library_refs_meta = shot_plan.get("library_refs_meta", [])
            history_refs = shot_plan.get("history_refs", [])
            asset_match = shot_plan.get("asset_match") if isinstance(shot_plan.get("asset_match"), dict) else {}
            semantic_retrieval = (
                shot_plan.get("semantic_retrieval")
                if isinstance(shot_plan.get("semantic_retrieval"), dict)
                else None
            )

            head_prompt = str(shot_plan.get("head_prompt") or "")
            tail_prompt = str(shot_plan.get("tail_prompt") or "")
            variation_type = str(shot_plan.get("variation_type") or "").strip().lower()
            if variation_type not in {"small", "medium", "large"}:
                variation_type = ""
            variation_reason = str(shot_plan.get("variation_reason") or "").replace("\n", " ").strip()

            anchor_shot_id = shot_plan.get("anchor_shot_id")
            anchor_source = str(shot_plan.get("anchor_source") or "none")
            head_base_desc = str(shot_plan.get("head_base_desc") or "").strip()
            head_base_spec = shot_plan.get("head_base_spec") if isinstance(shot_plan.get("head_base_spec"), dict) else None
            head_base_visible_chars = _as_str_list(shot_plan.get("head_base_visible_chars"))
            bypass_hash_cache = bool(shot_plan.get("bypass_hash_cache"))

            head_path = run_dir / f"{shot_id}_head.png"
            tail_path = run_dir / f"{shot_id}_tail.png"

            head_base_path: Optional[Path] = None
            if isinstance(anchor_shot_id, str) and anchor_shot_id.strip():
                head_base_path = run_dir / f"{anchor_shot_id}_tail.png"

            local_t2i = adapter

            local_image_edit_adapters: Dict[str, Any] = {}
            if use_head_image_edit:
                local_image_edit_adapters[image_edit_adapter_name_head] = (
                    image_edit_adapter_name_head if _model_client_available(image_edit_adapter_name_head) else None
                )
            if use_tail_image_edit and image_edit_adapter_name_tail not in local_image_edit_adapters:
                local_image_edit_adapters[image_edit_adapter_name_tail] = (
                    image_edit_adapter_name_tail if _model_client_available(image_edit_adapter_name_tail) else None
                )

            local_vlm_adapter = None
            if selector in {"vlm", "semantic"} or ref_selector == "vlm":
                local_vlm_adapter = vlm_adapter

            def _normalize_ref_list(raw: Any) -> List[Dict[str, Any]]:
                out: List[Dict[str, Any]] = []
                if not isinstance(raw, list):
                    return out
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path")
                    if not isinstance(path, Path):
                        continue
                    desc = str(item.get("desc") or "").strip()
                    out.append({"path": path, "desc": desc})
                    if len(out) >= 200:
                        break
                return out

            ref_images = _normalize_ref_list(ref_images)
            history_refs = _normalize_ref_list(history_refs)
            library_index_by_uri: Dict[str, int] = {}
            for idx, ref in enumerate(ref_images):
                path = ref.get("path")
                if isinstance(path, Path):
                    library_index_by_uri[str(path)] = idx

            def _build_rewrite_pool(
                *,
                anchor: Optional[Dict[str, Any]],
                drop: Optional[Dict[str, Any]] = None,
                selection_refs: Optional[List[Dict[str, Any]]] = None,
            ) -> List[Dict[str, Any]]:
                others: List[Dict[str, Any]] = []
                others.extend(history_refs)
                if selection_refs:
                    others.extend(selection_refs)
                else:
                    others.extend(ref_images)
                if drop is not None:
                    others = _drop_anchor_from_refs(others, drop)
                pool = _merge_reference_images(anchor=anchor, others=others)
                if ref_text_prefilter_pool > 0 and len(pool) > int(ref_text_prefilter_pool):
                    pool = pool[: int(ref_text_prefilter_pool)]
                return pool

            def _select_rewrite_subset(
                pool: List[Dict[str, Any]],
                *,
                frame_description: str,
                enable_prefilter: bool,
            ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[int]]:
                if not pool:
                    return [], None, []
                keep = max(1, int(max_refs))
                if not enable_prefilter or local_vlm_adapter is None or len(pool) <= keep:
                    subset = pool[:keep]
                    return subset, None, list(range(len(subset)))

                pre = _vlm_prefilter_reference_images_text_only(
                    vlm_adapter=local_vlm_adapter,
                    frame_description=frame_description,
                    candidates=pool,
                    max_keep=keep,
                )
                _bump_telemetry_counter(ctx.payload, "vlm_text_prefilter_calls", 1)

                indices: List[int] = []
                if isinstance(pre, dict):
                    raw = pre.get("selected_ref_indices")
                    if isinstance(raw, list):
                        for item in raw:
                            if not isinstance(item, int):
                                continue
                            if item < 0 or item >= len(pool):
                                continue
                            if item in indices:
                                continue
                            indices.append(item)
                            if len(indices) >= min(keep, len(pool)):
                                break

                if indices:
                    return [pool[i] for i in indices], pre, indices

                subset = pool[:keep]
                return subset, None, list(range(len(subset)))

            def _selected_pool_indices_from_pick(pick: Optional[Dict[str, Any]], subset_to_pool: List[int]) -> List[int]:
                if not isinstance(pick, dict):
                    return []
                raw = pick.get("selected_ref_indices")
                if not isinstance(raw, list):
                    return []
                out: List[int] = []
                for item in raw:
                    if not isinstance(item, int):
                        continue
                    if item < 0 or item >= len(subset_to_pool):
                        continue
                    pool_idx = subset_to_pool[item]
                    if pool_idx in out:
                        continue
                    out.append(pool_idx)
                    if len(out) >= min(8, len(subset_to_pool)):
                        break
                return out

            def _selected_library_indices_from_pool(pool: List[Dict[str, Any]], pool_indices: List[int]) -> List[int]:
                out: List[int] = []
                for pidx in pool_indices:
                    if not isinstance(pidx, int) or pidx < 0 or pidx >= len(pool):
                        continue
                    path = pool[pidx].get("path")
                    if not isinstance(path, Path):
                        continue
                    lib_idx = library_index_by_uri.get(str(path))
                    if lib_idx is None or lib_idx in out:
                        continue
                    out.append(lib_idx)
                return out

            try:
                head_via = "t2i"
                head_ref: Optional[Dict[str, Any]] = None
                head_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
                head_anchor: Optional[Dict[str, Any]] = None
                if head_base_path is not None and head_base_desc:
                    head_anchor = {"path": head_base_path, "desc": head_base_desc}
                require_head_anchor = bool(isinstance(anchor_shot_id, str) and anchor_shot_id.strip())
                head_ref_pack, head_ref_issues_raw = _build_reference_pack(anchor=head_anchor, match=asset_match)
                head_ref_issues = _normalize_ref_issues(head_ref_issues_raw, require_anchor=require_head_anchor)
                head_selector, head_selector_degraded_reason = _selector_with_ref_issues(
                    selector,
                    vlm_adapter=local_vlm_adapter,
                    ref_issues=head_ref_issues,
                )
                head_edit_ref_pack = _drop_anchor_from_refs(head_ref_pack, head_anchor)

                head_extra_meta: Dict[str, Any] = {}
                if semantic_retrieval:
                    head_extra_meta["semantic_retrieval"] = semantic_retrieval
                fused_head_path: Optional[Path] = None
                if enable_multiperson_fusion:
                    _bump_telemetry_counter(ctx.payload, "multiperson_fusion_attempts", 1)
                    fused_head_path, fusion_meta = _try_generate_multiperson_fusion_head(
                        shot_id=shot_id,
                        output_path=head_path,
                        head_prompt=head_prompt,
                        style_negative_prompt=style_negative_prompt,
                        asset_match=asset_match,
                        head_anchor=head_anchor,
                        use_anchor_scene=multiperson_fusion_use_anchor_scene,
                        max_persons=multiperson_fusion_max_persons,
                        keep_candidates=keep_candidates,
                    )
                    head_extra_meta["multiperson_fusion"] = fusion_meta
                    if isinstance(fusion_meta, dict):
                        status = str(fusion_meta.get("status") or "").strip().lower()
                        if status == "success":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_success", 1)
                            steps = fusion_meta.get("steps") if isinstance(fusion_meta.get("steps"), list) else []
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_steps", len(steps))
                        elif status == "failed":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_failed", 1)
                        elif status == "skipped":
                            _bump_telemetry_counter(ctx.payload, "multiperson_fusion_skipped", 1)
                    if fused_head_path is not None:
                        head_via = "multiperson_fusion"
                        head_decision = {
                            "mode": "multiperson_fusion",
                            "reason": "多人物融合生成 head",
                            "cam_idx": cam_idx,
                            "parent_cam_idx": parent_cam_idx,
                            "anchor_source": anchor_source,
                        }
                        head_ref = {
                            "base": {"uri": str(head_base_path), "desc": head_base_desc} if head_anchor else None,
                            "library_refs": library_refs_meta,
                            "selection_refs": _ref_images_meta(head_ref_pack),
                            "issues": head_ref_issues,
                        }
                        head_meta = {"candidate_count": 1, "selected": 0, "selector": "single"}

                if fused_head_path is None:
                    head_image_edit_adapter = local_image_edit_adapters.get(image_edit_adapter_name_head)
                    if use_head_image_edit and head_image_edit_adapter is None:
                        head_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
                    elif use_head_image_edit:
                        head_decision = _decide_image_mode(
                            policy=image_edit_policy,
                            base_image_path=head_base_path,
                            base_spec=head_base_spec,
                            target_spec=head_spec,
                            base_visible_chars=head_base_visible_chars,
                            target_visible_chars=ff_vis_char_ids,
                            max_subject_pos_delta=max_subject_pos_delta,
                            min_prompt_similarity=image_edit_min_prompt_similarity,
                            default_ratio=frame_ratio,
                        )
                    head_decision = {**head_decision, "cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}

                    if (
                        head_decision.get("mode") == "image_edit"
                        and head_image_edit_adapter is not None
                        and head_base_path is not None
                        and head_base_path.exists()
                    ):
                        base_desc = head_base_desc or f"基准图：{str(head_base_path)}"
                        edit_prompt = head_prompt
                        ref_pick = None
                        rewrite_pool = _build_rewrite_pool(anchor=None, drop={"path": head_base_path, "desc": base_desc}, selection_refs=head_edit_ref_pack)
                        rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                            rewrite_pool,
                            frame_description=head_prompt,
                            enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None),
                        )
                        if ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_head", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(rewrite_subset) + 1)
                            ref_pick = _vlm_build_edit_prompt_from_base_and_refs(
                                vlm_adapter=local_vlm_adapter,
                                base_image_path=head_base_path,
                                base_image_desc=base_desc,
                                target_description=head_prompt,
                                reference_images=rewrite_subset,
                                max_refs=max_refs_for_edit,
                            )
                            if isinstance(ref_pick, dict) and isinstance(ref_pick.get("edit_prompt"), str):
                                edit_prompt = str(ref_pick.get("edit_prompt") or head_prompt)

                        selected_pool_indices = _selected_pool_indices_from_pick(ref_pick, subset_to_pool)
                        selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                        if selected_library_indices:
                            selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                            selected_ref_indices: Optional[List[int]] = selected_library_indices
                        else:
                            selected_ref_images, selected_ref_indices = ref_images, None
                        selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]
                        selection_refs = head_ref_pack
                        head_ref = {
                            "base": {"uri": str(head_base_path), "desc": base_desc},
                            "library_refs": library_refs_meta,
                            "selected_library_ref_indices": selected_ref_indices,
                            "selected_library_refs": _ref_images_meta(selected_ref_images),
                            "rewrite_candidates": _ref_images_meta(rewrite_pool),
                            "rewrite_prefilter": rewrite_prefilter,
                            "selected_rewrite_ref_indices": selected_pool_indices or None,
                            "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                            "selection_refs": _ref_images_meta(selection_refs),
                            "issues": head_ref_issues,
                            "rewrite": ref_pick,
                        }

                        try:
                            head_meta = _generate_edit_with_candidates(
                                adapter=head_image_edit_adapter,
                                image_path=head_base_path,
                                edit_prompt=edit_prompt,
                                reference_desc=base_desc,
                                strength=image_edit_strength,
                                guidance_scale=image_edit_guidance,
                                base_seed=head_spec.get("seed"),
                                ctx=ctx,
                                shot_id=shot_id,
                                role="head",
                                output_path=head_path,
                                candidate_count=shot_edit_candidates,
                                parallelism=candidate_parallelism,
                                selector=head_selector,
                                vlm_adapter=local_vlm_adapter,
                                vlm_criteria=vlm_criteria,
                                reference_images=head_edit_ref_pack,
                                keep_candidates=keep_candidates,
                                bypass_hash_cache=bypass_hash_cache,
                                use_multi_ref=image_edit_multi_ref_head,
                                max_ref_images=image_edit_ref_max_images,
                            )
                            head_via = "image_edit"
                        except Exception as exc:  # noqa: BLE001
                            head_meta = _generate_t2i_with_candidates(
                                adapter=local_t2i,
                                prompt=head_prompt,
                                negative_prompt=style_negative_prompt,
                                width=frame_width,
                                height=frame_height,
                                base_seed=head_spec.get("seed"),
                                ctx=ctx,
                                shot_id=shot_id,
                                role="head",
                                output_path=head_path,
                                candidate_count=shot_candidate_count,
                                parallelism=candidate_parallelism,
                                selector=head_selector,
                                vlm_adapter=local_vlm_adapter,
                                vlm_criteria=vlm_criteria,
                                reference_images=selection_refs,
                                keep_candidates=keep_candidates,
                                bypass_hash_cache=bypass_hash_cache,
                            )
                            head_meta["fallback_error"] = str(exc)
                            head_via = "image_edit_fallback"
                    else:
                        rewritten = None
                        prompt_for_t2i = head_prompt
                        rewrite_anchor = None
                        if head_base_path is not None and head_base_path.exists():
                            rewrite_anchor = {"path": head_base_path, "desc": head_base_desc or f"基准图：{str(head_base_path)}"}
                        rewrite_pool = _build_rewrite_pool(anchor=rewrite_anchor, selection_refs=head_ref_pack)
                        rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                            rewrite_pool,
                            frame_description=head_prompt,
                            enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None),
                        )
                        selected_pool_indices: List[int] = []
                        if ref_selector == "vlm" and head_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                            _bump_telemetry_counter(ctx.payload, "vlm_rewrite_t2i_calls", 1)
                            _bump_telemetry_counter(ctx.payload, "vlm_rewrite_t2i_ref_images", len(rewrite_subset))
                            rewritten = _vlm_rewrite_t2i_prompt_from_references(
                                vlm_adapter=local_vlm_adapter,
                                frame_description=head_prompt,
                                reference_images=rewrite_subset,
                                max_refs=max_refs,
                            )
                            selected_pool_indices = _selected_pool_indices_from_pick(rewritten, subset_to_pool)
                            if isinstance(rewritten, dict) and isinstance(rewritten.get("prompt"), str):
                                prompt_for_t2i = str(rewritten.get("prompt") or head_prompt)

                        selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                        if selected_library_indices:
                            selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                            selected_ref_indices = selected_library_indices
                        else:
                            selected_ref_images, selected_ref_indices = ref_images, None
                        selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]

                        selection_refs = head_ref_pack
                        if head_anchor or ref_images or history_refs or rewritten:
                            head_ref = {
                                "base": {"uri": str(head_base_path), "desc": head_base_desc} if head_anchor else None,
                                "library_refs": library_refs_meta,
                                "selected_library_ref_indices": selected_ref_indices,
                                "selected_library_refs": _ref_images_meta(selected_ref_images),
                                "rewrite_candidates": _ref_images_meta(rewrite_pool),
                                "rewrite_prefilter": rewrite_prefilter,
                                "selected_rewrite_ref_indices": selected_pool_indices or None,
                                "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                                "selection_refs": _ref_images_meta(selection_refs),
                                "issues": head_ref_issues,
                                "rewrite": rewritten,
                            }

                        head_meta = _generate_t2i_with_candidates(
                            adapter=local_t2i,
                            prompt=prompt_for_t2i,
                            negative_prompt=style_negative_prompt,
                            width=frame_width,
                            height=frame_height,
                            base_seed=head_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="head",
                            output_path=head_path,
                            candidate_count=shot_candidate_count,
                            parallelism=candidate_parallelism,
                            selector=head_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=selection_refs if selection_refs else ref_images,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                        )

                head_meta.update(head_extra_meta)
                head_meta["selector_requested"] = selector
                head_meta["selector_effective"] = "multiperson_fusion" if head_via == "multiperson_fusion" else head_selector
                if head_via != "multiperson_fusion":
                    if head_selector_degraded_reason:
                        head_meta["selector_degraded_reason"] = head_selector_degraded_reason
                else:
                    head_meta["selector_degraded_reason"] = "not_applicable"
                if head_ref_issues:
                    head_meta["ref_issues"] = head_ref_issues
                head_meta["camera"] = {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}
                if variation_type:
                    head_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                head_frame = {
                    "path": str(head_path),
                    "ratio": str(head_spec.get("ratio") or frame_ratio),
                    "spec": head_spec,
                    "meta": {"role": "head", "via": head_via, "ref": head_ref, "decision": head_decision, **head_meta},
                }

                if skip_tail_small_variation and variation_type == "small" and head_path.exists():
                    tail_path.write_bytes(head_path.read_bytes())
                    tail_meta: Dict[str, Any] = {
                        "candidate_count": 0,
                        "selected": None,
                        "selector": "reuse_head",
                        "selector_requested": selector,
                        "selector_effective": "reuse_head",
                        "camera": {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source},
                    }
                    if variation_type:
                        tail_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                    tail_decision = {"mode": "reuse_head", "reason": "variation_type=small"}
                    tail_frame = {
                        "path": str(tail_path),
                        "ratio": str(tail_spec.get("ratio") or frame_ratio),
                        "spec": tail_spec,
                        "meta": {"role": "tail", "via": "reuse_head", "ref": None, "decision": tail_decision, **tail_meta},
                    }
                    return {"head": head_frame, "tail": tail_frame}

                tail_decision = {"mode": "t2i", "reason": "未启用图像编辑"}
                tail_ref: Optional[Dict[str, Any]] = None
                tail_anchor_desc = f"本镜头{shot_id} 的head；prompt={(head_prompt or '')[:80]}"
                tail_anchor = {"path": head_path, "desc": tail_anchor_desc}
                tail_ref_pack, tail_ref_issues_raw = _build_reference_pack(anchor=tail_anchor, match=asset_match)
                tail_ref_issues = _normalize_ref_issues(tail_ref_issues_raw, require_anchor=True)
                tail_selector, tail_selector_degraded_reason = _selector_with_ref_issues(
                    selector,
                    vlm_adapter=local_vlm_adapter,
                    ref_issues=tail_ref_issues,
                )
                tail_edit_ref_pack = _drop_anchor_from_refs(tail_ref_pack, tail_anchor)
                tail_image_edit_adapter = local_image_edit_adapters.get(image_edit_adapter_name_tail)
                if use_tail_image_edit and tail_image_edit_adapter is None:
                    tail_decision = {"mode": "t2i", "reason": "图像编辑模型不可用"}
                elif use_tail_image_edit:
                    if variation_driven_image_edit and variation_type == "large":
                        tail_decision = {"mode": "t2i", "reason": "variation_type=large"}
                    else:
                        tail_decision = _decide_image_mode(
                            policy=image_edit_policy,
                            base_image_path=head_path,
                            base_spec=head_spec,
                            target_spec=tail_spec,
                            base_visible_chars=ff_vis_char_ids,
                            target_visible_chars=lf_vis_char_ids,
                            max_subject_pos_delta=max_subject_pos_delta,
                            min_prompt_similarity=image_edit_min_prompt_similarity,
                            default_ratio=frame_ratio,
                        )

                if tail_decision.get("mode") == "image_edit" and tail_image_edit_adapter is not None:
                    tail_desc = tail_anchor_desc
                    tail_edit_prompt = tail_prompt or head_prompt
                    tail_rewrite = None
                    rewrite_pool = _build_rewrite_pool(anchor=None, drop={"path": head_path, "desc": tail_desc}, selection_refs=tail_edit_ref_pack)
                    rewrite_subset, rewrite_prefilter, subset_to_pool = _select_rewrite_subset(
                        rewrite_pool,
                        frame_description=tail_edit_prompt,
                        enable_prefilter=bool(ref_text_prefilter and ref_selector == "vlm" and tail_ref_rewrite and local_vlm_adapter is not None),
                    )
                    if ref_selector == "vlm" and tail_ref_rewrite and local_vlm_adapter is not None and rewrite_subset:
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls", 1)
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_calls_tail", 1)
                        _bump_telemetry_counter(ctx.payload, "vlm_edit_prompt_images", len(rewrite_subset) + 1)
                        tail_rewrite = _vlm_build_edit_prompt_from_base_and_refs(
                            vlm_adapter=local_vlm_adapter,
                            base_image_path=head_path,
                            base_image_desc=tail_desc,
                            target_description=tail_edit_prompt,
                            reference_images=rewrite_subset,
                            max_refs=max_refs_for_edit,
                        )
                        if isinstance(tail_rewrite, dict) and isinstance(tail_rewrite.get("edit_prompt"), str):
                            tail_edit_prompt = str(tail_rewrite.get("edit_prompt") or tail_edit_prompt)

                    selected_pool_indices = _selected_pool_indices_from_pick(tail_rewrite, subset_to_pool)
                    selected_library_indices = _selected_library_indices_from_pool(rewrite_pool, selected_pool_indices)
                    if selected_library_indices:
                        selected_ref_images = [ref_images[i] for i in selected_library_indices if 0 <= i < len(ref_images)]
                        selected_ref_indices: Optional[List[int]] = selected_library_indices
                    else:
                        selected_ref_images, selected_ref_indices = ref_images, None
                    selected_rewrite_refs = [rewrite_pool[i] for i in selected_pool_indices if 0 <= i < len(rewrite_pool)]
                    selection_refs = tail_ref_pack
                    tail_ref = {
                        "base": {"uri": str(head_path), "desc": tail_desc},
                        "library_refs": library_refs_meta,
                        "selected_library_ref_indices": selected_ref_indices,
                        "selected_library_refs": _ref_images_meta(selected_ref_images),
                        "rewrite_candidates": _ref_images_meta(rewrite_pool),
                        "rewrite_prefilter": rewrite_prefilter,
                        "selected_rewrite_ref_indices": selected_pool_indices or None,
                        "selected_rewrite_refs": _ref_images_meta(selected_rewrite_refs),
                        "selection_refs": _ref_images_meta(selection_refs),
                        "issues": tail_ref_issues,
                        "rewrite": tail_rewrite,
                    }

                    try:
                        tail_meta = _generate_edit_with_candidates(
                            adapter=tail_image_edit_adapter,
                            image_path=head_path,
                            edit_prompt=tail_edit_prompt,
                            reference_desc=tail_desc,
                            strength=image_edit_strength,
                            guidance_scale=image_edit_guidance,
                            base_seed=tail_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="tail",
                            output_path=tail_path,
                            candidate_count=shot_edit_candidates,
                            parallelism=candidate_parallelism,
                            selector=tail_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=tail_edit_ref_pack,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                            use_multi_ref=image_edit_multi_ref_tail,
                            max_ref_images=image_edit_ref_max_images,
                        )
                        tail_via = "image_edit"
                    except Exception as exc:  # noqa: BLE001
                        tail_meta = _generate_t2i_with_candidates(
                            adapter=local_t2i,
                            prompt=tail_prompt,
                            negative_prompt=style_negative_prompt,
                            width=frame_width,
                            height=frame_height,
                            base_seed=tail_spec.get("seed"),
                            ctx=ctx,
                            shot_id=shot_id,
                            role="tail",
                            output_path=tail_path,
                            candidate_count=shot_candidate_count,
                            parallelism=candidate_parallelism,
                            selector=tail_selector,
                            vlm_adapter=local_vlm_adapter,
                            vlm_criteria=vlm_criteria,
                            reference_images=selection_refs if selection_refs else ref_images,
                            keep_candidates=keep_candidates,
                            bypass_hash_cache=bypass_hash_cache,
                        )
                        tail_meta["fallback_error"] = str(exc)
                        tail_via = "image_edit_fallback"
                else:
                    selection_refs = tail_ref_pack
                    if selection_refs or ref_images:
                        tail_ref = {
                            "base": {"uri": str(head_path), "desc": tail_anchor_desc},
                            "library_refs": library_refs_meta,
                            "selected_library_ref_indices": None,
                            "selected_library_refs": _ref_images_meta(ref_images),
                            "selection_refs": _ref_images_meta(selection_refs),
                            "issues": tail_ref_issues,
                            "rewrite": None,
                        }
                    tail_meta = _generate_t2i_with_candidates(
                        adapter=local_t2i,
                        prompt=tail_prompt,
                        negative_prompt=style_negative_prompt,
                        width=frame_width,
                        height=frame_height,
                        base_seed=tail_spec.get("seed"),
                        ctx=ctx,
                        shot_id=shot_id,
                        role="tail",
                        output_path=tail_path,
                        candidate_count=shot_candidate_count,
                        parallelism=candidate_parallelism,
                        selector=tail_selector,
                        vlm_adapter=local_vlm_adapter,
                        vlm_criteria=vlm_criteria,
                        reference_images=selection_refs if selection_refs else ref_images,
                        keep_candidates=keep_candidates,
                        bypass_hash_cache=bypass_hash_cache,
                    )
                    tail_via = "t2i"

                tail_meta["selector_requested"] = selector
                tail_meta["selector_effective"] = tail_selector
                if tail_selector_degraded_reason:
                    tail_meta["selector_degraded_reason"] = tail_selector_degraded_reason
                if tail_ref_issues:
                    tail_meta["ref_issues"] = tail_ref_issues
                if semantic_retrieval:
                    tail_meta["semantic_retrieval"] = semantic_retrieval
                tail_meta["camera"] = {"cam_idx": cam_idx, "parent_cam_idx": parent_cam_idx, "anchor_source": anchor_source}
                if variation_type:
                    tail_meta["variation"] = {"type": variation_type, "reason": variation_reason}
                tail_frame = {
                    "path": str(tail_path),
                    "ratio": str(tail_spec.get("ratio") or frame_ratio),
                    "spec": tail_spec,
                    "meta": {"role": "tail", "via": tail_via, "ref": tail_ref, "decision": tail_decision, **tail_meta},
                }
                return {"head": head_frame, "tail": tail_frame}
            finally:
                _close_adapter_session(local_t2i)
                if local_image_edit_adapters:
                    closed: set[int] = set()
                    for item in local_image_edit_adapters.values():
                        if item is None:
                            continue
                        key = id(item)
                        if key in closed:
                            continue
                        closed.add(key)
                        _close_adapter_session(item)
                if local_vlm_adapter is not None:
                    _close_adapter_session(local_vlm_adapter)

        futures: Dict[Any, str] = {}
        with ThreadPoolExecutor(max_workers=keyframes_parallelism) as pool:
            while remaining or futures:
                submitted = True
                while submitted and len(futures) < keyframes_parallelism:
                    submitted = False
                    for shot_id, plan in list(remaining.items()):
                        deps = _as_str_list(plan.get("depends_on_state_ids"))
                        if any(dep not in completed for dep in deps):
                            continue
                        futures[pool.submit(_render_one, plan)] = shot_id
                        remaining.pop(shot_id, None)
                        submitted = True
                        break

                if not futures:
                    pending = [str(p.get("shot_id") or "") for p in plans if str(p.get("shot_id") or "") in remaining][:5]
                    raise RuntimeError(f"keyframes parallel scheduling stuck (pending={pending})")

                done_futs, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
                for fut in done_futs:
                    shot_id = futures.pop(fut)
                    results_by_shot[shot_id] = fut.result()
                    completed.add(shot_id)

        frames: List[Dict[str, Any]] = []
        for plan in plans:
            shot_id = str(plan.get("shot_id") or "")
            pair = results_by_shot.get(shot_id)
            if not isinstance(pair, dict) or not isinstance(pair.get("head"), dict) or not isinstance(pair.get("tail"), dict):
                raise RuntimeError(f"missing keyframes result for shot {shot_id}")
            frames.append(pair["head"])
            frames.append(pair["tail"])

        if semantic_index is not None:
            try:
                index_items = _semantic_index_items_from_frames(frames=frames, run_id=str(ctx.run_id), max_items=400)
                if index_items:
                    semantic_index.add_many(index_items)
            except Exception:  # noqa: BLE001
                pass

        camera_states = ctx.payload.get("camera_states")
        if not isinstance(camera_states, list) or not camera_states:
            camera_states = build_camera_states(
                storyboard if isinstance(storyboard, list) else [],
                camera_tree if isinstance(camera_tree, list) and camera_tree else None,
            )

        head_by_shot_id: Dict[str, Dict[str, Any]] = {}
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            meta = frame.get("meta") if isinstance(frame.get("meta"), dict) else {}
            if meta.get("role") != "head":
                continue
            path = frame.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            stem = Path(path).stem
            shot_key = stem[: -len("_head")] if stem.endswith("_head") else stem
            if shot_key and shot_key not in head_by_shot_id:
                head_by_shot_id[shot_key] = frame

        camera_scenes: List[Dict[str, Any]] = []
        for track in camera_states:
            if not isinstance(track, dict) or not isinstance(track.get("cam_idx"), int):
                continue
            cam_idx = int(track["cam_idx"])
            shot_id = str(track.get("first_state_id") or "").strip()
            if not shot_id:
                continue
            head = head_by_shot_id.get(shot_id)
            if not isinstance(head, dict):
                continue

            meta = head.get("meta") if isinstance(head.get("meta"), dict) else {}
            camera_meta = meta.get("camera") if isinstance(meta.get("camera"), dict) else {}
            ref_meta = meta.get("ref") if isinstance(meta.get("ref"), dict) else {}
            base_ref = ref_meta.get("base") if isinstance(ref_meta.get("base"), dict) else {}

            states = track.get("states") if isinstance(track.get("states"), list) else []
            shot_pos = None
            if states and isinstance(states[0], dict):
                sp = states[0].get("shot_pos")
                if isinstance(sp, int):
                    shot_pos = int(sp)

            parent_cam_idx = track.get("parent_cam_idx")
            parent_shot_id = track.get("parent_shot_id")
            camera_scenes.append(
                {
                    "cam_idx": cam_idx,
                    "shot_id": shot_id,
                    "shot_pos": shot_pos,
                    "scene_uri": str(head.get("path") or ""),
                    "via": str(meta.get("via") or "").strip() or None,
                    "anchor_source": str(camera_meta.get("anchor_source") or "").strip() or None,
                    "anchor_base_uri": str(base_ref.get("uri") or "").strip() or None,
                    "parent_cam_idx": int(parent_cam_idx) if isinstance(parent_cam_idx, int) else None,
                    "parent_shot_id": str(parent_shot_id).strip() if isinstance(parent_shot_id, str) and parent_shot_id.strip() else None,
                }
            )

        if camera_scenes:
            ctx.payload["camera_scenes"] = camera_scenes

        ctx.payload["keyframes"] = frames
        if semantic_index is not None:
            semantic_index.close()
        return

    ctx.payload["keyframes"] = []
    if semantic_index is not None:
        semantic_index.close()
    return

