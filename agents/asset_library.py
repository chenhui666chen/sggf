from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.model_adapters import ModelAdapterFactory

from agents.painter import _generate_edit_with_candidates, _generate_t2i_with_candidates
from pipeline.media_presets import ensure_media_payload, normalize_frame_ratio, resolve_frame_size
from pipeline.style_presets import ensure_style_payload


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_str(value: Any, default: str) -> str:
    return str(value) if value is not None else default


def _close_adapter_session(adapter: Any) -> None:
    session = getattr(adapter, "session", None)
    try:
        if session is not None:
            session.close()
    except Exception:  # noqa: BLE001
        pass


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float(default)


def _parse_character_views_env() -> List[str]:
    raw = str(os.getenv("DREAMWEAVER_LIBRARY_CHARACTER_VIEWS", "front,side,back") or "").strip().lower()
    views = [v.strip() for v in raw.split(",") if v.strip()]
    picked: List[str] = []
    for v in views:
        if v not in {"front", "side", "back"}:
            continue
        if v in picked:
            continue
        picked.append(v)
    if "front" not in picked:
        picked.insert(0, "front")
    return picked


def _build_role(entity_type: str, entity_id: int, *, view: Optional[str] = None) -> str:
    t = (entity_type or "").strip().lower()
    if t == "character":
        v = str(view or "front").strip().lower()
        if v == "side":
            return f"lib_character_portrait_side:{int(entity_id)}"
        if v == "back":
            return f"lib_character_portrait_back:{int(entity_id)}"
        return f"lib_character_portrait:{int(entity_id)}"
    if t == "scene":
        return f"lib_scene_card:{int(entity_id)}"
    if t == "prop":
        return f"lib_prop_card:{int(entity_id)}"
    raise ValueError(f"unsupported entity_type: {entity_type!r}")


def _build_prompt(
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: str,
    ratio: str,
    *,
    view: Optional[str] = None,
) -> str:
    style = (style_prompt or "").strip() or os.getenv(
        "DREAMWEAVER_LIBRARY_STYLE", "写实风格，电影质感，光影真实，高清细节，统一风格"
    )
    ratio_norm = normalize_frame_ratio(ratio)
    name = (name or "").strip()
    descriptor = (descriptor or "").strip()

    if entity_type == "character":
        v = str(view or "front").strip().lower()
        view_line = "视角：正面"
        view_hint = "正面或三分之二正面，脸部特征清晰可辨。"
        if v == "side":
            view_line = "视角：侧面"
            view_hint = "侧面视角（profile），保持与正面一致的发型/服装/配色，尽量保留可识别特征。"
        elif v == "back":
            view_line = "视角：背面"
            view_hint = "背面视角（back view），重点展示发型、服装与体态轮廓，严格保持与正面一致。"
        return (
            f"风格：{style}（严格保持一致，不要混合风格）\n"
            f"画幅：{ratio_norm}\n"
            f"{view_line}\n"
            f"角色：{name}\n"
            f"人物设定：{descriptor}\n"
            f"要求：单人角色立绘/肖像，主体清晰，{view_hint}避免多余人物与文字水印，背景干净。\n"
            "约束：无文字，无水印，无logo，无边框，无拼贴。"
        )
    if entity_type == "scene":
        return (
            f"风格：{style}（严格保持一致，不要混合风格）\n"
            f"画幅：{ratio_norm}\n"
            f"场景：{name}\n"
            f"场景设定：{descriptor}\n"
            "要求：无人物的环境概念图，空间结构清晰，避免文字水印。\n"
            "约束：无文字，无水印，无logo，无边框，无拼贴。"
        )
    if entity_type == "prop":
        return (
            f"风格：{style}（严格保持一致，不要混合风格）\n"
            f"画幅：{ratio_norm}\n"
            f"道具：{name}\n"
            f"道具设定：{descriptor}\n"
            "要求：单一物品特写，材质细节清晰，背景简洁干净，避免文字水印。\n"
            "约束：无文字，无水印，无logo，无边框，无拼贴。"
        )
    return f"风格：{style}\n画幅：{ratio_norm}\n{name}\n{descriptor}\n约束：无文字，无水印，无logo，无边框，无拼贴。"


def _library_root(project_id: int) -> Path:
    return Path("runs") / "library" / f"project_{int(project_id)}"


def _output_path(root: Path, entity_type: str, entity_id: int, *, view: Optional[str] = None) -> Path:
    sub = "misc"
    if entity_type == "character":
        sub = "characters"
    elif entity_type == "scene":
        sub = "scenes"
    elif entity_type == "prop":
        sub = "props"
    filename = f"{int(entity_id)}.png"
    if entity_type == "character":
        v = str(view or "front").strip().lower()
        if v == "side":
            filename = f"{int(entity_id)}_side.png"
        elif v == "back":
            filename = f"{int(entity_id)}_back.png"
    return root / sub / filename


def _index_existing_assets(project_assets: Any) -> Dict[str, Dict[str, Any]]:
    assets: Dict[str, Dict[str, Any]] = {}
    if not isinstance(project_assets, list):
        return assets
    for item in project_assets:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if not isinstance(role, str) or not role:
            continue
        assets[role] = item
    return assets


def _iter_spec_entities(spec: Dict[str, Any]) -> List[Tuple[str, int, str, str]]:
    entities: List[Tuple[str, int, str, str]] = []
    for key, entity_type in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_id = item.get("entity_id")
            try:
                eid = int(entity_id)
            except Exception:  # noqa: BLE001
                continue
            name = _safe_str(item.get("name"), "").strip()
            if not name:
                continue
            descriptor = _safe_str(item.get("descriptor"), "").strip()
            entities.append((entity_type, eid, name, descriptor))
    return entities


def _resolve_uri_path(uri: Any) -> Optional[Path]:
    if not isinstance(uri, str) or not uri.strip():
        return None
    p = Path(str(uri)).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def _asset_exists(existing: Any, *, expected: Optional[Path] = None) -> bool:
    if expected is not None and expected.exists():
        return True
    if not isinstance(existing, dict):
        return False
    p = _resolve_uri_path(existing.get("uri"))
    return bool(p and p.exists())


def run(ctx: Any) -> None:
    ensure_style_payload(ctx.payload)
    ensure_media_payload(ctx.payload)

    project_id = _safe_int(ctx.payload.get("project_id"), 0)
    if project_id <= 0:
        ctx.payload["asset_library"] = {"generated": 0, "skipped": 0, "reason": "missing project_id"}
        ctx.payload["asset_library_done"] = True
        ctx.payload["asset_library_requires_review"] = False
        return

    spec = ctx.payload.get("asset_library_spec") if isinstance(ctx.payload.get("asset_library_spec"), dict) else None
    if not isinstance(spec, dict):
        ctx.payload["asset_library"] = {"generated": 0, "skipped": 0, "reason": "missing asset_library_spec"}
        ctx.payload["asset_library_done"] = True
        ctx.payload["asset_library_requires_review"] = False
        return

    image_cfg = ctx.payload.get("image_config") if isinstance(ctx.payload.get("image_config"), dict) else {}
    frame_width, frame_height, frame_ratio = resolve_frame_size(image_cfg)
    frame_resolution = _safe_str(image_cfg.get("resolution"), "").strip()
    candidate_count = max(1, _safe_int(image_cfg.get("t2i_candidates"), 1))
    selector = _safe_str(image_cfg.get("image_selector"), "first").strip().lower()
    keep_candidates = bool(image_cfg.get("keep_candidates", False))

    asset_parallelism = _parse_int(os.getenv("DREAMWEAVER_ASSET_LIBRARY_PARALLELISM"), 1)
    asset_parallelism = max(1, min(int(asset_parallelism), 8))

    factory = ModelAdapterFactory()
    t2i = factory.get_adapter("wan_t2i")
    image_edit_adapter_name = os.getenv("DREAMWEAVER_IMAGE_EDIT_ADAPTER", "wan_image_edit")
    image_edit_strength = _parse_float(image_cfg.get("image_edit_strength") or os.getenv("DREAMWEAVER_IMAGE_EDIT_STRENGTH") or 0.65, 0.65)
    image_edit_guidance = _parse_float(image_cfg.get("image_edit_guidance") or os.getenv("DREAMWEAVER_IMAGE_EDIT_GUIDANCE") or 7.5, 7.5)
    image_edit_strength = max(0.0, min(float(image_edit_strength), 1.0))
    image_edit_guidance = max(0.1, min(float(image_edit_guidance), 50.0))
    try:
        image_edit_adapter = factory.get_adapter(image_edit_adapter_name)
    except Exception:  # noqa: BLE001
        image_edit_adapter = None

    vlm_adapter = None
    if selector in {"vlm", "semantic"}:
        try:
            vlm_adapter = factory.get_adapter(os.getenv("DREAMWEAVER_VLM_ADAPTER", "qwen3_vl_plus"))
        except Exception:  # noqa: BLE001
            vlm_adapter = None
    vlm_criteria = [
        s.strip()
        for s in os.getenv("DREAMWEAVER_VLM_CRITERIA", "clarity,composition,lighting,color,style").split(",")
        if s.strip()
    ]

    root = _library_root(project_id)
    _ensure_dir(root)

    existing_by_role = _index_existing_assets(ctx.payload.get("project_assets"))
    force_regenerate = bool(ctx.payload.get("asset_library_force_regenerate"))
    regen_roles_raw = ctx.payload.get("asset_library_regenerate_roles")
    regen_roles: List[str] = []
    if isinstance(regen_roles_raw, list):
        for item in regen_roles_raw:
            if not isinstance(item, (str, int)):
                continue
            s = str(item).strip()
            if not s or s in regen_roles:
                continue
            regen_roles.append(s)
            if len(regen_roles) >= 200:
                break
    regen_role_set = set(regen_roles)
    style_prompt = str(ctx.payload.get("style_prompt") or "")
    style_preset = str(ctx.payload.get("style_preset") or "").strip()
    style_negative_prompt = str(ctx.payload.get("style_negative_prompt") or "").strip()
    enforce_style = str(os.getenv("DREAMWEAVER_LIBRARY_ENFORCE_STYLE", "1") or "").strip().lower() not in {"0", "false", "no"}

    entities = _iter_spec_entities(spec)
    character_views = _parse_character_views_env()
    role_specs: List[Dict[str, Any]] = []
    for entity_type, entity_id, name, descriptor in entities:
        if entity_type == "character":
            for v in character_views:
                role_specs.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": int(entity_id),
                        "entity_name": name,
                        "descriptor": descriptor,
                        "view": v,
                        "role": _build_role(entity_type, entity_id, view=v),
                    }
                )
        else:
            role_specs.append(
                {
                    "entity_type": entity_type,
                    "entity_id": int(entity_id),
                    "entity_name": name,
                    "descriptor": descriptor,
                    "view": None,
                    "role": _build_role(entity_type, entity_id),
                }
            )
    required_roles: List[str] = [str(s.get("role") or "") for s in role_specs if str(s.get("role") or "").strip()]
    if regen_role_set:
        required_role_set = set(required_roles)
        regen_role_set = {r for r in regen_role_set if r in required_role_set}

    progress = (
        ctx.payload.get("asset_library_progress")
        if isinstance(ctx.payload.get("asset_library_progress"), dict)
        else {}
    )
    signature = "|".join(required_roles)
    if progress.get("signature") != signature or bool(progress.get("force_regenerate")) != force_regenerate:
        progress = {"signature": signature, "force_regenerate": force_regenerate, "processed_roles": []}
    processed_roles = {
        str(r)
        for r in (progress.get("processed_roles") if isinstance(progress.get("processed_roles"), list) else [])
        if isinstance(r, str) and r
    }

    regen_progress = (
        ctx.payload.get("asset_library_regenerate_progress")
        if isinstance(ctx.payload.get("asset_library_regenerate_progress"), dict)
        else {}
    )
    regen_signature = "|".join(sorted(regen_role_set))
    if regen_progress.get("signature") != regen_signature:
        regen_progress = {"signature": regen_signature, "processed_roles": []}
    regen_processed = {
        str(r)
        for r in (regen_progress.get("processed_roles") if isinstance(regen_progress.get("processed_roles"), list) else [])
        if isinstance(r, str) and r
    }

    generated_this_call = 0
    current: Optional[Dict[str, Any]] = None

    def _candidate_job_list(*, regenerate_only: bool) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        for spec_item in role_specs:
            entity_type = str(spec_item.get("entity_type") or "").strip()
            entity_id = int(spec_item.get("entity_id") or 0)
            name = str(spec_item.get("entity_name") or "").strip()
            descriptor = str(spec_item.get("descriptor") or "").strip()
            view = spec_item.get("view")
            view_str = str(view).strip().lower() if isinstance(view, str) and view.strip() else None
            role = str(spec_item.get("role") or "").strip()
            if not role:
                continue
            out_path = _output_path(root, entity_type, entity_id, view=view_str)
            _ensure_dir(out_path.parent)
            existing = existing_by_role.get(role)

            if regenerate_only:
                if role not in regen_role_set or role in regen_processed:
                    continue
            else:
                if role in regen_role_set:
                    continue
                if force_regenerate:
                    if role in processed_roles:
                        continue
                else:
                    if _asset_exists(existing, expected=out_path):
                        if not isinstance(existing, dict):
                            existing_by_role[role] = {
                                "asset_type": "image",
                                "role": role,
                                "uri": str(out_path),
                                "meta": {
                                    "entity_type": entity_type,
                                    "entity_id": int(entity_id),
                                    "entity_name": name,
                                    "descriptor": descriptor,
                                    "view": view_str,
                                    "style_preset": style_preset,
                                    "style_prompt": style_prompt,
                                    "ratio": frame_ratio,
                                    "resolution": frame_resolution,
                                    "width": int(frame_width),
                                    "height": int(frame_height),
                                    "negative_prompt": style_negative_prompt,
                                    "approved": False,
                                },
                            }
                            existing = existing_by_role.get(role)
                        if not enforce_style:
                            continue
                        meta = (
                            existing.get("meta")
                            if isinstance(existing, dict) and isinstance(existing.get("meta"), dict)
                            else {}
                        )
                        existing_style = str(meta.get("style_preset") or "").strip()
                        existing_ratio = str(meta.get("ratio") or "").strip()
                        existing_width = _safe_int(meta.get("width"), 0)
                        existing_height = _safe_int(meta.get("height"), 0)
                        # 风格/画幅一致则跳过；不一致/未知则覆盖重生成，避免混合风格或画幅不一致（即便该素材已被审核通过）。
                        style_ok = (not existing_style) or existing_style == style_preset
                        ratio_ok = (not existing_ratio) or normalize_frame_ratio(existing_ratio) == normalize_frame_ratio(frame_ratio)
                        size_ok = (existing_width <= 0 or existing_width == int(frame_width)) and (
                            existing_height <= 0 or existing_height == int(frame_height)
                        )
                        if style_ok and ratio_ok and size_ok:
                            meta_updated = False
                            if style_preset and not str(meta.get("style_preset") or "").strip():
                                meta["style_preset"] = style_preset
                                meta_updated = True
                            if style_prompt and not str(meta.get("style_prompt") or "").strip():
                                meta["style_prompt"] = style_prompt
                                meta_updated = True
                            if frame_ratio and not str(meta.get("ratio") or "").strip():
                                meta["ratio"] = frame_ratio
                                meta_updated = True
                            if frame_resolution and not str(meta.get("resolution") or "").strip():
                                meta["resolution"] = frame_resolution
                                meta_updated = True
                            if int(frame_width) > 0 and _safe_int(meta.get("width"), 0) <= 0:
                                meta["width"] = int(frame_width)
                                meta_updated = True
                            if int(frame_height) > 0 and _safe_int(meta.get("height"), 0) <= 0:
                                meta["height"] = int(frame_height)
                                meta_updated = True
                            if style_negative_prompt and not str(meta.get("negative_prompt") or "").strip():
                                meta["negative_prompt"] = style_negative_prompt
                                meta_updated = True
                            if meta_updated and isinstance(existing, dict):
                                existing["meta"] = meta
                            continue

            if entity_type == "character" and view_str in {"side", "back"}:
                front_role = _build_role("character", entity_id, view="front")
                front_path = _output_path(root, "character", entity_id, view="front")
                if regenerate_only:
                    if front_role in regen_role_set and front_role not in regen_processed:
                        continue
                elif force_regenerate:
                    if front_role not in processed_roles:
                        continue
                else:
                    if not _asset_exists(existing_by_role.get(front_role), expected=front_path):
                        continue

            prompt = _build_prompt(entity_type, name, descriptor, style_prompt, frame_ratio, view=view_str)
            jobs.append(
                {
                    "entity_type": entity_type,
                    "entity_id": int(entity_id),
                    "entity_name": name,
                    "descriptor": descriptor,
                    "view": view_str,
                    "role": role,
                    "output_path": str(out_path),
                    "prompt": prompt,
                }
            )
            if len(jobs) >= 200:
                break
        return jobs

    regen_jobs = _candidate_job_list(regenerate_only=True)
    normal_jobs = [] if regen_jobs else _candidate_job_list(regenerate_only=False)

    jobs = (regen_jobs if regen_jobs else normal_jobs)[:asset_parallelism]
    bypass_hash_cache = bool(force_regenerate or regen_jobs)

    def _render_one(job: Dict[str, Any]) -> Dict[str, Any]:
        entity_type = str(job["entity_type"])
        entity_id = int(job["entity_id"])
        name = str(job["entity_name"])
        descriptor = str(job["descriptor"])
        view = str(job.get("view") or "").strip().lower() or None
        role = str(job["role"])
        out_path = Path(str(job["output_path"]))
        prompt = str(job["prompt"])

        local_t2i = t2i
        local_vlm = vlm_adapter
        local_image_edit = image_edit_adapter
        if asset_parallelism > 1:
            local_factory = ModelAdapterFactory()
            local_t2i = local_factory.get_adapter("wan_t2i")
            if selector in {"vlm", "semantic"}:
                try:
                    local_vlm = local_factory.get_adapter(os.getenv("DREAMWEAVER_VLM_ADAPTER", "qwen3_vl_plus"))
                except Exception:  # noqa: BLE001
                    local_vlm = None
            try:
                local_image_edit = local_factory.get_adapter(image_edit_adapter_name)
            except Exception:  # noqa: BLE001
                local_image_edit = None

        via = "t2i"
        edit_base: Optional[Path] = None
        edit_base_role = ""
        if entity_type == "character" and view in {"side", "back"}:
            edit_base_role = _build_role("character", entity_id, view="front")
            base_expected = _output_path(root, "character", entity_id, view="front")
            if base_expected.exists():
                edit_base = base_expected
            else:
                existing_base = existing_by_role.get(edit_base_role) if isinstance(existing_by_role.get(edit_base_role), dict) else None
                if isinstance(existing_base, dict):
                    edit_base = _resolve_uri_path(existing_base.get("uri"))
            if not (isinstance(edit_base, Path) and edit_base.exists()):
                edit_base = None

        try:
            if edit_base is not None and local_image_edit is not None:
                via = "image_edit"
                _generate_edit_with_candidates(
                    adapter=local_image_edit,
                    image_path=edit_base,
                    edit_prompt=prompt,
                    reference_desc=f"正面角色卡（{name or entity_id}）",
                    strength=float(image_edit_strength),
                    guidance_scale=float(image_edit_guidance),
                    base_seed=None,
                    ctx=ctx,
                    shot_id=f"LIB-{entity_type}-{entity_id}-{view}" if view else f"LIB-{entity_type}-{entity_id}",
                    role=role.replace(":", "_"),
                    output_path=out_path,
                    candidate_count=candidate_count,
                    selector=selector,
                    vlm_adapter=local_vlm,
                    vlm_criteria=vlm_criteria,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                )
            else:
                _generate_t2i_with_candidates(
                    adapter=local_t2i,
                    prompt=prompt,
                    negative_prompt=style_negative_prompt,
                    width=frame_width,
                    height=frame_height,
                    base_seed=None,
                    ctx=ctx,
                    shot_id=f"LIB-{entity_type}-{entity_id}-{view}" if view else f"LIB-{entity_type}-{entity_id}",
                    role=role.replace(":", "_"),
                    output_path=out_path,
                    candidate_count=candidate_count,
                    selector=selector,
                    vlm_adapter=local_vlm,
                    vlm_criteria=vlm_criteria,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                )
        finally:
            if local_t2i is not t2i:
                _close_adapter_session(local_t2i)
            if local_vlm is not vlm_adapter and local_vlm is not None:
                _close_adapter_session(local_vlm)
            if local_image_edit is not image_edit_adapter and local_image_edit is not None:
                _close_adapter_session(local_image_edit)

        meta = {
            "entity_type": entity_type,
            "entity_id": int(entity_id),
            "entity_name": name,
            "descriptor": descriptor,
            "view": view,
            "prompt": prompt,
            "via": via,
            "style_preset": style_preset,
            "style_prompt": style_prompt,
            "ratio": frame_ratio,
            "resolution": frame_resolution,
            "width": int(frame_width),
            "height": int(frame_height),
            "negative_prompt": style_negative_prompt,
            "approved": False,
        }
        if via == "image_edit" and edit_base is not None:
            meta["edit_base"] = {"role": edit_base_role, "uri": str(edit_base)}
            meta["image_edit"] = {
                "adapter": image_edit_adapter_name,
                "strength": float(image_edit_strength),
                "guidance_scale": float(image_edit_guidance),
            }
        return {
            "entity_type": entity_type,
            "entity_id": int(entity_id),
            "entity_name": name,
            "role": role,
            "output_path": str(out_path),
            "asset": {"asset_type": "image", "role": role, "uri": str(out_path), "meta": meta},
        }

    if jobs:
        if asset_parallelism <= 1 or len(jobs) <= 1:
            results = [_render_one(job) for job in jobs]
        else:
            ordered: List[Optional[Dict[str, Any]]] = [None] * len(jobs)
            with ThreadPoolExecutor(max_workers=min(asset_parallelism, len(jobs))) as pool:
                futures = {pool.submit(_render_one, job): idx for idx, job in enumerate(jobs)}
                for fut in as_completed(futures):
                    idx = futures[fut]
                    ordered[idx] = fut.result()
            results = [r for r in ordered if isinstance(r, dict)]

        for r in results:
            role = str(r.get("role") or "")
            asset = r.get("asset")
            if not role or not isinstance(asset, dict):
                continue
            existing_by_role[role] = asset
            current = {
                "entity_type": r.get("entity_type"),
                "entity_id": r.get("entity_id"),
                "entity_name": r.get("entity_name"),
                "role": role,
                "output_path": str(r.get("output_path") or ""),
            }
            if regen_jobs:
                regen_processed.add(role)
            else:
                processed_roles.add(role)
            generated_this_call += 1

    unapproved_roles: List[str] = []
    for role in required_roles:
        asset = existing_by_role.get(role)
        if not isinstance(asset, dict):
            continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        if not bool(meta.get("approved")):
            unapproved_roles.append(role)

    project_assets = [existing_by_role[r] for r in sorted(existing_by_role.keys())]
    ctx.payload["project_assets"] = project_assets

    if force_regenerate:
        pending_count = max(0, len(required_roles) - len(processed_roles))
        ready_count = len(required_roles) - pending_count
    else:
        ready_count = 0
        pending_count = 0
        for spec_item in role_specs:
            entity_type = str(spec_item.get("entity_type") or "").strip()
            entity_id = int(spec_item.get("entity_id") or 0)
            view = spec_item.get("view")
            view_str = str(view).strip().lower() if isinstance(view, str) and view.strip() else None
            role = str(spec_item.get("role") or "").strip()
            if not role:
                continue
            out_path = _output_path(root, entity_type, entity_id, view=view_str)
            if _asset_exists(existing_by_role.get(role), expected=out_path):
                ready_count += 1
            else:
                pending_count += 1

    regen_pending = len([r for r in regen_role_set if r and r not in regen_processed])
    regen_done = bool(regen_role_set) and regen_pending == 0
    done = pending_count == 0 and regen_pending == 0
    progress["signature"] = signature
    progress["force_regenerate"] = force_regenerate
    progress["processed_roles"] = sorted(processed_roles)
    ctx.payload["asset_library_progress"] = progress
    regen_progress["signature"] = regen_signature
    regen_progress["processed_roles"] = sorted(regen_processed)
    if regen_role_set and not regen_done:
        ctx.payload["asset_library_regenerate_progress"] = regen_progress
    else:
        ctx.payload.pop("asset_library_regenerate_progress", None)
    if regen_done:
        ctx.payload.pop("asset_library_regenerate_roles", None)

    ctx.payload["asset_library"] = {
        "project_id": project_id,
        "generated": ready_count,
        "skipped": 0,
        "required_count": len(required_roles),
        "ready_count": ready_count,
        "pending_count": pending_count,
        "unapproved_count": len(unapproved_roles),
        "generated_this_call": generated_this_call,
        "force_regenerate": force_regenerate,
        "regenerate_roles_count": len(regen_role_set),
        "regenerate_pending": regen_pending,
        "current": current,
    }
    ctx.payload["asset_library_done"] = done
    ctx.payload["asset_library_requires_review"] = bool(done and unapproved_roles)
    if done:
        ctx.payload.pop("asset_library_force_regenerate", None)
        ctx.payload.pop("asset_library_progress", None)
        ctx.payload.pop("asset_library_regenerate_roles", None)
        ctx.payload.pop("asset_library_regenerate_progress", None)
