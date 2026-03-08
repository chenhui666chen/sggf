from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.model_adapters import ModelAdapterFactory

from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)
from agents.painter import _generate_edit_with_candidates, _generate_t2i_with_candidates
from pipeline.media_presets import ensure_media_payload, normalize_frame_ratio, resolve_frame_size
from pipeline.style_presets import ensure_style_payload


_CHARACTER_BACKGROUND_LINE = "背景：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。"
_CHARACTER_CONSTRAINT_LINE = "约束：无文字，无水印，无logo，无边框，无拼贴。"


def _character_compose_line(view: str) -> str:
    if view == "side":
        return "构图：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。"
    if view == "back":
        return "构图：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。"
    return "构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。"


def _character_consistency_line(view: str) -> str:
    if view == "side":
        return "一致性要求：与正面图保持同一角色身份锚点，不改变灰白背头、冷峻眉眼与紧抿薄唇，不改变深色高领制服与金色徽章，不改变肩部半透明数据流黑袍。"
    if view == "back":
        return "一致性要求：与正面和侧面图保持同一角色身份锚点，不改变发型轮廓、制服版型与配色、金色徽章位置及肩部半透明数据流黑袍。"
    return "一致性要求：角色身份锚点必须保持一致，不改变灰白背头、冷峻眉眼与紧抿薄唇，不改变深色高领制服与金色徽章，不改变肩部半透明数据流黑袍。"


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


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


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
        return (
            f"风格：{style}（严格保持一致，不要混合风格）\n"
            f"画幅：{ratio_norm}\n"
            f"角色：{name}\n"
            f"人物设定：{descriptor}\n"
            f"{_character_compose_line(v)}\n"
            f"{_CHARACTER_BACKGROUND_LINE}\n"
            f"{_character_consistency_line(v)}\n"
            f"{_CHARACTER_CONSTRAINT_LINE}"
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


def _append_character_prompt_constraints(
    prompt: str,
    *,
    view: Optional[str],
    full_body: bool,
    clean_background: bool,
) -> str:
    text = str(prompt or "").strip()
    if not text:
        return text

    hints: List[str] = []
    if full_body:
        hints.append(_character_compose_line(str(view or "front").strip().lower()))
    if clean_background:
        hints.append(_CHARACTER_BACKGROUND_LINE)

    v = str(view or "front").strip().lower()
    hints.append(_character_consistency_line(v))
    hints.append(_CHARACTER_CONSTRAINT_LINE)

    existing = text.lower()
    merged = text
    for hint in hints:
        hint_plain = "".join(ch for ch in hint.lower() if not ch.isspace())
        existing_plain = "".join(ch for ch in existing if not ch.isspace())
        if hint_plain in existing_plain:
            continue
        merged = f"{merged}\n{hint}"
        existing = merged.lower()
    return merged.strip()


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

    manual_mode = _env_flag("DREAMWEAVER_LIBRARY_MANUAL", True)
    ctx.payload["asset_library_manual"] = bool(manual_mode)

    asset_parallelism = _parse_int(os.getenv("DREAMWEAVER_ASSET_LIBRARY_PARALLELISM"), 1)
    asset_parallelism = max(1, min(int(asset_parallelism), 8))

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

    if manual_mode:
        unapproved_roles: List[str] = []
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
            asset = existing_by_role.get(role)
            if isinstance(asset, dict):
                meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
                if not bool(meta.get("approved")):
                    unapproved_roles.append(role)

        ctx.payload["project_assets"] = [existing_by_role[r] for r in sorted(existing_by_role.keys())]
        ctx.payload["asset_library"] = {
            "project_id": project_id,
            "generated": ready_count,
            "skipped": 0,
            "required_count": len(required_roles),
            "ready_count": ready_count,
            "pending_count": pending_count,
            "unapproved_count": len(unapproved_roles),
            "generated_this_call": 0,
            "force_regenerate": False,
            "regenerate_roles_count": len(regen_role_set),
            "regenerate_pending": len(regen_role_set),
            "current": None,
        }
        ctx.payload["asset_library_done"] = True
        ctx.payload["asset_library_requires_review"] = bool(pending_count > 0 or unapproved_roles)
        return

    factory = ModelAdapterFactory()
    t2i = factory.get_adapter("wan_t2i")
    image_edit_adapter_name = resolve_image_edit_adapter_name(
        image_cfg,
        purpose="library_character_view",
        default_adapter="wan_image_edit",
    )
    force_view_chain_image_edit = _env_flag("DREAMWEAVER_LIBRARY_VIEW_CHAIN_FORCE_IMAGE_EDIT", True)
    enable_back_multi_ref = _env_flag("DREAMWEAVER_LIBRARY_VIEW_CHAIN_BACK_MULTI_REF", True)
    character_full_body = _env_flag("DREAMWEAVER_LIBRARY_CHARACTER_FULL_BODY", True)
    character_clean_background = _env_flag("DREAMWEAVER_LIBRARY_CLEAN_BACKGROUND", True)
    image_edit_multi_ref = resolve_image_edit_multi_ref(image_cfg=image_cfg, adapter_name=image_edit_adapter_name)
    image_edit_ref_max_images = resolve_image_edit_ref_max_images(image_cfg=image_cfg, default_max=2)
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
                dependencies: List[Tuple[str, Path]] = []
                front_role = _build_role("character", entity_id, view="front")
                front_path = _output_path(root, "character", entity_id, view="front")
                dependencies.append((front_role, front_path))
                if view_str == "back":
                    side_role = _build_role("character", entity_id, view="side")
                    side_path = _output_path(root, "character", entity_id, view="side")
                    dependencies.append((side_role, side_path))

                blocked = False
                for dep_role, dep_path in dependencies:
                    if regenerate_only:
                        if dep_role in regen_role_set:
                            if dep_role not in regen_processed:
                                blocked = True
                                break
                        elif not _asset_exists(existing_by_role.get(dep_role), expected=dep_path):
                            blocked = True
                            break
                    elif force_regenerate:
                        if dep_role not in processed_roles:
                            blocked = True
                            break
                    elif not _asset_exists(existing_by_role.get(dep_role), expected=dep_path):
                        blocked = True
                        break
                if blocked:
                    continue

            prompt = _build_prompt(entity_type, name, descriptor, style_prompt, frame_ratio, view=view_str)
            if entity_type == "character":
                prompt = _append_character_prompt_constraints(
                    prompt,
                    view=view_str,
                    full_body=character_full_body,
                    clean_background=character_clean_background,
                )
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
        edit_reference_images: List[Dict[str, Any]] = []
        force_view_edit = bool(
            force_view_chain_image_edit
            and entity_type == "character"
            and view in {"side", "back"}
        )
        generation_meta: Dict[str, Any] = {}
        if entity_type == "character" and view in {"side", "back"}:
            front_role = _build_role("character", entity_id, view="front")
            side_role = _build_role("character", entity_id, view="side")
            front_expected = _output_path(root, "character", entity_id, view="front")
            side_expected = _output_path(root, "character", entity_id, view="side")

            def _resolve_chain_path(role_name: str, expected_path: Path) -> Optional[Path]:
                if expected_path.exists():
                    return expected_path
                existing_asset = existing_by_role.get(role_name) if isinstance(existing_by_role.get(role_name), dict) else None
                if not isinstance(existing_asset, dict):
                    return None
                resolved_path = _resolve_uri_path(existing_asset.get("uri"))
                if isinstance(resolved_path, Path) and resolved_path.exists():
                    return resolved_path
                return None

            front_path = _resolve_chain_path(front_role, front_expected)
            side_path = _resolve_chain_path(side_role, side_expected)

            if view == "side":
                edit_base_role = front_role
                edit_base = front_path
            elif view == "back":
                edit_base_role = side_role
                edit_base = side_path
                if front_path is not None and enable_back_multi_ref:
                    edit_reference_images.append(
                        {
                            "path": front_path,
                            "desc": f"front character view ({name or entity_id})",
                            "role": front_role,
                        }
                    )

            if not (isinstance(edit_base, Path) and edit_base.exists()):
                edit_base = None

        try:
            if force_view_edit:
                if edit_base is None:
                    raise RuntimeError(f"missing view-chain edit base for role={role}")
                if local_image_edit is None:
                    raise RuntimeError("image_edit adapter unavailable for forced view-chain role")

            if edit_base is not None and local_image_edit is not None:
                via = "image_edit"
                use_multi_ref = bool(view == "back" and enable_back_multi_ref and image_edit_multi_ref)
                generation_meta = _generate_edit_with_candidates(
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
                    reference_images=edit_reference_images if use_multi_ref else None,
                    keep_candidates=keep_candidates,
                    bypass_hash_cache=bypass_hash_cache,
                    use_multi_ref=use_multi_ref,
                    max_ref_images=max(1, int(image_edit_ref_max_images)),
                )
            else:
                generation_meta = _generate_t2i_with_candidates(
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
            "view_chain_force_image_edit": bool(force_view_edit),
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
            if edit_reference_images:
                refs_meta: List[Dict[str, str]] = []
                for item in edit_reference_images:
                    if not isinstance(item, dict):
                        continue
                    raw_path = item.get("path")
                    path_text = str(raw_path) if isinstance(raw_path, Path) else str(raw_path or "").strip()
                    if not path_text:
                        continue
                    refs_meta.append(
                        {
                            "role": str(item.get("role") or "").strip(),
                            "uri": path_text,
                            "desc": str(item.get("desc") or "").strip(),
                        }
                    )
                if refs_meta:
                    meta["edit_refs"] = refs_meta
        if isinstance(generation_meta, dict) and generation_meta:
            meta["generation"] = generation_meta
            if bool(generation_meta.get("safety_blocked")):
                meta["safety_blocked"] = True
                meta["safety_error"] = str(generation_meta.get("safety_error") or "")
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
