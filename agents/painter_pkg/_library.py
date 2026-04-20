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
    _cfg_str,
    _clone_adapter_instance,
    _close_adapter_session,
    _model_client_available,
    _resolve_runtime_model_id,
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
    _semantic_index_items_from_frames,
    _write_video_from_generation_result,
    _env_float,
    _cfg_float,
    _normalize_safety_strategy,
    _supports_multi_image_client,
    _as_str_list,
    _try_parse_json_object,
    _mime_from_path,
    _file_to_data_url,
    _PNG_PLACEHOLDER_B64,
)
from agents.painter_pkg._t2i_pipeline import _generate_t2i_with_candidates
from agents.painter_pkg._edit_pipeline import _generate_edit_with_candidates, _collect_reference_image_paths

def _library_assets(ctx: Any) -> List[Dict[str, Any]]:
    items = ctx.payload.get("project_assets")
    if not isinstance(items, list):
        return []

    current_style_preset = str(ctx.payload.get("style_preset") or "").strip()
    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    current_ratio = str(image_cfg.get("ratio") or "").strip()
    if current_ratio:
        current_ratio = normalize_frame_ratio(current_ratio)

    assets: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        uri = item.get("uri")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if not isinstance(role, str) or not role.startswith("lib_"):
            continue
        if not isinstance(uri, str) or not uri:
            continue
        if not bool(meta.get("approved")):
            continue

        # 避免跨风格复用已审核素材导致“写实/动漫混用”。
        asset_style_preset = str(meta.get("style_preset") or "").strip()
        if current_style_preset:
            if not asset_style_preset:
                continue
            if asset_style_preset != current_style_preset:
                continue

        # 避免跨画幅复用素材导致构图/尺寸不一致。
        asset_ratio = str(meta.get("ratio") or "").strip()
        if current_ratio:
            if not asset_ratio:
                continue
            if normalize_frame_ratio(asset_ratio, default=current_ratio) != current_ratio:
                continue

        entity_type = str(meta.get("entity_type") or "")
        if not entity_type:
            if role.startswith("lib_character_portrait"):
                entity_type = "character"
            elif role.startswith("lib_scene_card"):
                entity_type = "scene"
            elif role.startswith("lib_prop_card"):
                entity_type = "prop"
            else:
                entity_type = "unknown"

        name = str(meta.get("entity_name") or meta.get("name") or "").strip()
        descriptor = str(meta.get("descriptor") or "").strip()
        path = Path(uri)
        if not path.exists():
            continue
        assets.append(
            {
                "role": role,
                "entity_type": entity_type,
                "entity_name": name or role,
                "descriptor": descriptor,
                "path": path,
                "desc": f"{entity_type}:{name}" if name else role,
            }
        )
    return assets


def _match_library_refs_for_shot(
    *,
    shot: Dict[str, Any],
    library_assets: List[Dict[str, Any]],
    max_refs: int = 8,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    def _norm_names(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            if not isinstance(item, (str, int)):
                continue
            name = str(item).strip()
            if not name or name in out:
                continue
            out.append(name)
            if len(out) >= 12:
                break
        return out

    explicit_chars = _norm_names(shot.get("ff_vis_char_ids")) + _norm_names(shot.get("lf_vis_char_ids"))
    explicit_chars = [c for i, c in enumerate(explicit_chars) if c and c not in explicit_chars[:i]]

    text = " ".join(
        [
            str(shot.get("visual_desc") or ""),
            str(shot.get("desc") or ""),
            str(shot.get("ff_desc") or ""),
            str(shot.get("lf_desc") or ""),
        ]
    )

    matches: List[Dict[str, Any]] = []
    # 1) 强约束：若 storyboard 提供了可见人物名单，则优先用人物 AnchorSet
    if explicit_chars:
        for asset in library_assets:
            if str(asset.get("entity_type")) != "character":
                continue
            name = str(asset.get("entity_name") or "").strip()
            if name and name in explicit_chars:
                matches.append(asset)

    # 2) 弱匹配：从文本中命中实体名
    for asset in library_assets:
        name = str(asset.get("entity_name") or "").strip()
        if name and name in text:
            matches.append(asset)

    if not any(str(a.get("entity_type")) == "scene" for a in matches):
        for asset in library_assets:
            if str(asset.get("entity_type")) == "scene":
                matches.append(asset)
                break

    order = {"character": 0, "scene": 1, "prop": 2}
    # 去重：按 role 保留第一个
    seen_roles: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for asset in matches:
        role = str(asset.get("role") or "").strip()
        if not role or role in seen_roles:
            continue
        seen_roles.add(role)
        deduped.append(asset)

    matches = sorted(deduped, key=lambda a: order.get(str(a.get("entity_type")), 99))[: max(0, int(max_refs))]

    ref_images: List[Dict[str, Any]] = []
    constraints: List[str] = []
    for asset in matches:
        path = asset.get("path")
        if isinstance(path, Path) and path.exists():
            ref_images.append({"path": path, "desc": str(asset.get("desc") or "")})
        label = str(asset.get("entity_type") or "")
        name = str(asset.get("entity_name") or "")
        desc = str(asset.get("descriptor") or "")[:80].strip()
        if name:
            constraints.append(f"- {label}：{name}：{desc}")
    return ref_images, constraints


def _append_consistency_constraints(prompt: str, constraints: List[str]) -> str:
    base = (prompt or "").strip()
    if not constraints:
        return base
    return f"{base}\n\n一致性约束（必须遵守）：\n" + "\n".join(constraints)


def _ref_images_meta(ref_images: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for ref in ref_images or []:
        if not isinstance(ref, dict):
            continue
        path = ref.get("path")
        if not isinstance(path, Path):
            continue
        desc = str(ref.get("desc") or "").strip()
        out.append({"uri": str(path), "desc": desc})
    return out


def _normalize_ref_issues(issues: Any, *, require_anchor: bool) -> List[str]:
    out: List[str] = []
    if isinstance(issues, list):
        for item in issues:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if not s or s in out:
                continue
            out.append(s)
            if len(out) >= 16:
                break

    if not require_anchor and "missing_anchor_card" in out:
        out = [s for s in out if s != "missing_anchor_card"]
    return out


def _selector_with_ref_issues(selector: str, *, vlm_adapter: Any, ref_issues: List[str]) -> Tuple[str, Optional[str]]:
    sel = (selector or "first").strip().lower() or "first"
    if sel != "semantic":
        return sel, None
    if vlm_adapter is None:
        return "file_size", "no_vlm_adapter"
    if any(i in {"missing_character_card", "missing_scene_card", "missing_anchor_card"} for i in (ref_issues or [])):
        return "vlm", "missing_required_refs"
    return sel, None


def _drop_anchor_from_refs(refs: List[Dict[str, Any]], anchor: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not refs:
        return []
    anchor_path = anchor.get("path") if isinstance(anchor, dict) else None
    if not isinstance(anchor_path, Path):
        return refs
    return [r for r in refs if isinstance(r, dict) and r.get("path") != anchor_path]


def _try_generate_multiperson_fusion_head(
    *,
    shot_id: str,
    output_path: Path,
    head_prompt: str,
    style_negative_prompt: str,
    asset_match: Dict[str, Any],
    head_anchor: Optional[Dict[str, Any]],
    use_anchor_scene: bool,
    max_persons: int,
    keep_candidates: bool,
) -> Tuple[Optional[Path], Dict[str, Any]]:
    max_persons = int(max_persons)
    if max_persons < 2:
        return None, {"status": "skipped", "reason": "max_persons_lt_2"}

    character_assets = asset_match.get("character_assets") if isinstance(asset_match.get("character_assets"), list) else []
    scene_assets = asset_match.get("scene_assets") if isinstance(asset_match.get("scene_assets"), list) else []

    person_cards: List[Dict[str, Any]] = []
    for asset in character_assets:
        if not isinstance(asset, dict):
            continue
        path = asset.get("path")
        if not isinstance(path, Path) or not path.exists():
            continue
        person_cards.append(asset)
        if len(person_cards) >= max_persons:
            break

    if len(person_cards) < 2:
        return None, {"status": "skipped", "reason": "insufficient_character_cards", "found": len(person_cards)}

    base_scene_path: Optional[Path] = None
    base_scene_source = "none"
    if use_anchor_scene:
        anchor_path = head_anchor.get("path") if isinstance(head_anchor, dict) else None
        if isinstance(anchor_path, Path) and anchor_path.exists():
            base_scene_path = anchor_path
            base_scene_source = "anchor_tail"

    if base_scene_path is None:
        for asset in scene_assets:
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if not isinstance(path, Path) or not path.exists():
                continue
            base_scene_path = path
            base_scene_source = "scene_card"
            break

    if base_scene_path is None:
        return None, {"status": "skipped", "reason": "missing_scene_base"}

    if not _model_client_available("qwen_multiperson_fusion"):
        return None, {"status": "failed", "reason": "adapter_unavailable", "error": "model_not_registered"}

    cand_dir = output_path.parent / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    fusion_dir = cand_dir / "multiperson_fusion"
    fusion_dir.mkdir(parents=True, exist_ok=True)

    base_prompt = str(head_prompt or "").strip()
    base_prompt = _apply_prompt_fragment(
        base_prompt,
        "任务：将输入的人物自然融合到场景中，保持角色身份、服饰细节一致；保持风格、光照、视角一致；避免新增无关人物与文字水印。",
    )

    current_scene_path = base_scene_path
    steps: List[Dict[str, Any]] = []
    try:
        for idx, asset in enumerate(person_cards):
            person_path = asset.get("path")
            if not isinstance(person_path, Path) or not person_path.exists():
                raise RuntimeError(f"invalid person card path at idx={idx}")
            person_name = str(asset.get("entity_name") or "").strip()
            descriptor = str(asset.get("descriptor") or "").replace("\n", " ").strip()
            if len(descriptor) > 120:
                descriptor = descriptor[:120]
            person_hint = person_name or str(asset.get("role") or f"person_{idx}").strip()
            if descriptor:
                person_hint = f"{person_hint}：{descriptor}"

            step_prompt = _apply_prompt_fragment(base_prompt, f"当前融合人物（必须出现且保持一致）：{person_hint}")
            out_step_path = fusion_dir / f"{shot_id}_head_fuse_{idx+1}.png"

            result = match_scene_with_model(
                person_image_path=str(person_path),
                target_scene_path=str(current_scene_path),
                scene_prompt=step_prompt,
                n=1,
                negative_prompt=style_negative_prompt,
                prompt_extend=True,
                watermark=False,
                model_id="qwen_multiperson_fusion",
            )
            _write_image_from_generation_result(result, out_step_path)

            steps.append(
                {
                    "idx": int(idx),
                    "person": {"uri": str(person_path), "name": person_name, "desc": str(asset.get("desc") or "").strip()},
                    "scene_in": str(current_scene_path),
                    "scene_out": str(out_step_path),
                }
            )
            current_scene_path = out_step_path

        output_path.write_bytes(current_scene_path.read_bytes())

        if not keep_candidates:
            for step in steps:
                try:
                    out_uri = str(step.get("scene_out") or "")
                    if out_uri and Path(out_uri).exists():
                        Path(out_uri).unlink()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "failed", "reason": "fusion_error", "error": str(exc), "steps": steps}
    return (
        output_path,
        {
            "status": "success",
            "scene_base": {"uri": str(base_scene_path), "source": base_scene_source},
            "persons": [{"uri": str(a.get("path")), "name": str(a.get("entity_name") or "").strip(), "desc": str(a.get("desc") or "").strip()} for a in person_cards],
            "steps": steps,
        },
    )

