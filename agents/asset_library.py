from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adapters.adapter_helpers import create_runtime_client, get_model_info

from agents.image_edit_utils import (
    resolve_image_edit_adapter_name,
    resolve_image_edit_multi_ref,
    resolve_image_edit_ref_max_images,
)
from agents.painter import _generate_edit_with_candidates, _generate_t2i_with_candidates
from pipeline.media_presets import ensure_media_payload, normalize_frame_ratio, resolve_frame_size
from pipeline.style_presets import ensure_style_payload


_CHARACTER_BACKGROUND_LINE = "Background: solid color, clean frame, no scene elements, no clutter, no text, no extra people."
_CHARACTER_CONSTRAINT_LINE = "Constraints: no text, no watermark, no logo, no border, no collage."
_CHARACTER_VIEW_ORDER_DEFAULT = ["front", "bust_front", "side", "bust_three_quarter", "bust_side", "back"]
_CHARACTER_VIEW_DEPENDENCIES = {
    "bust_front": ["front"],
    "side": ["front", "bust_front"],
    "bust_three_quarter": ["bust_front", "side"],
    "bust_side": ["bust_three_quarter", "side"],
    "back": ["side", "front", "bust_front"],
}
_CHARACTER_VIEW_BASE = {
    "bust_front": "front",
    "side": "front",
    "bust_three_quarter": "bust_front",
    "bust_side": "bust_three_quarter",
    "back": "side",
}
_CHARACTER_VIEW_EXTRA_REFS = {
    "bust_front": [],
    "side": ["bust_front"],
    "bust_three_quarter": ["front", "side"],
    "bust_side": ["side", "bust_front"],
    "back": ["front", "bust_front"],
}
_CHARACTER_VIEW_CN_LABEL = {
    "front": "front full-body",
    "side": "side full-body",
    "back": "back full-body",
    "bust_front": "front bust",
    "bust_three_quarter": "bust 3/4",
    "bust_side": "side bust",
}


def _character_compose_line(view: str) -> str:
    if view == "side":
        return "Composition: side-view full-body single-character sheet."
    if view == "back":
        return "Composition: back-view full-body single-character sheet."
    if view == "bust_front":
        return "Composition: front-view bust portrait, keep face and shoulder outfit details."
    if view == "bust_three_quarter":
        return "Composition: 3/4-view bust portrait."
    if view == "bust_side":
        return "Composition: side-view bust portrait."
    return "Composition: front-view full-body single-character sheet."


def _character_consistency_line(view: str) -> str:
    if view == "side":
        return "Consistency: keep the same identity anchors as front view."
    if view == "back":
        return "Consistency: keep hairstyle outline and outfit structure aligned with front/side."
    if view == "bust_front":
        return "Consistency: keep facial features and upper-body clothing details aligned."
    if view == "bust_three_quarter":
        return "Consistency: align with front bust and side full-body references."
    if view == "bust_side":
        return "Consistency: align with bust 3/4 and side full-body references."
    return "Consistency: keep identity anchors stable across all views."


def _is_character_view(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "front",
        "side",
        "back",
        "bust_front",
        "bust_three_quarter",
        "bust_side",
    }


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_str(value: Any, default: str) -> str:
    return str(value) if value is not None else default


def _workspace_root() -> Path:
    # asset_library.py -> agents -> workspace_root
    return Path(__file__).resolve().parents[1]


def _backend_root() -> Path:
    return (_workspace_root() / "backend").resolve()


_CROWD_TOKENS = (
    "crowd",
    "extra",
    "extras",
    "group",
    "people",
    "bystander",
    "background people",
    "npc",
)
_CROWD_MULTI_PERSON_PATTERN = re.compile(
    r"(?:[2-9]\\d*|[0-9]+)\s*(?:people|persons)|multi(?:-| )person|group|crowd|bystander[s]?|background people|npc[s]?|extra[s]?"
)


def _normalize_match_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _is_crowd_character_entity(*, name: Any, descriptor: Any = None, importance: Any = None) -> bool:
    compact = "|".join(
        [
            _normalize_match_token(name),
            _normalize_match_token(descriptor),
            _normalize_match_token(importance),
        ]
    )
    if not compact or compact == "|":
        return False
    if any(token in compact for token in _CROWD_TOKENS):
        return True
    return bool(_CROWD_MULTI_PERSON_PATTERN.search(compact))


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


def _resolve_registered_runtime_model_id(
    cfg: Dict[str, Any],
    *,
    key: str,
    env_name: str,
    default: str,
) -> Optional[str]:
    candidates: List[str] = []
    if isinstance(cfg, dict):
        raw_cfg = str(cfg.get(key) or "").strip()
        if raw_cfg:
            candidates.append(raw_cfg)

    raw_env = str(os.getenv(env_name) or "").strip()
    if raw_env:
        candidates.append(raw_env)

    raw_default = str(default or "").strip()
    if raw_default:
        candidates.append(raw_default)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if isinstance(get_model_info(candidate), dict):
            return candidate
    return raw_default or None


def _parse_character_views_env() -> List[str]:
    raw = str(
        os.getenv(
            "DREAMWEAVER_LIBRARY_CHARACTER_VIEWS",
            ",".join(_CHARACTER_VIEW_ORDER_DEFAULT),
        )
        or ""
    ).strip().lower()
    views = [v.strip() for v in raw.split(",") if v.strip()]
    picked: List[str] = []
    for v in views:
        if not _is_character_view(v):
            continue
        if v in picked:
            continue
        picked.append(v)
    if "front" not in picked:
        picked.insert(0, "front")
    ordered: List[str] = []
    # Keep deterministic chain order while respecting user-defined subset.
    for v in _CHARACTER_VIEW_ORDER_DEFAULT:
        if v in picked and v not in ordered:
            ordered.append(v)
    for v in picked:
        if v not in ordered:
            ordered.append(v)
    return ordered


def _build_role(entity_type: str, entity_id: int, *, view: Optional[str] = None) -> str:
    t = (entity_type or "").strip().lower()
    if t == "character":
        v = str(view or "front").strip().lower()
        if v == "side":
            return f"lib_character_portrait_side:{int(entity_id)}"
        if v == "back":
            return f"lib_character_portrait_back:{int(entity_id)}"
        if v == "bust_front":
            return f"lib_character_portrait_bust:{int(entity_id)}"
        if v == "bust_three_quarter":
            return f"lib_character_portrait_bust_three_quarter:{int(entity_id)}"
        if v == "bust_side":
            return f"lib_character_portrait_bust_side:{int(entity_id)}"
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
        "DREAMWEAVER_LIBRARY_STYLE", "cinematic realism, unified style, high detail"
    )
    ratio_norm = normalize_frame_ratio(ratio)
    name = (name or "").strip()
    descriptor = (descriptor or "").strip()

    if entity_type == "character":
        v = str(view or "front").strip().lower()
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Character: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            f"{_character_compose_line(v)}\\n"
            f"{_CHARACTER_BACKGROUND_LINE}\\n"
            f"{_character_consistency_line(v)}\\n"
            f"{_CHARACTER_CONSTRAINT_LINE}"
        )
    if entity_type == "scene":
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Scene: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            "Requirements: environment concept only, no characters, clean composition.\\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    if entity_type == "prop":
        return (
            f"Style: {style}\\n"
            f"Ratio: {ratio_norm}\\n"
            f"Prop: {name}\\n"
            f"Descriptor: {descriptor}\\n"
            "Requirements: single-object closeup, clean background, clear material details.\\n"
            "Constraints: no text, no watermark, no logo, no border, no collage."
        )
    return f"Style: {style}\\nRatio: {ratio_norm}\\n{name}\\n{descriptor}\\nConstraints: no text, no watermark, no logo, no border, no collage."


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
    backend_runs = _backend_root() / "runs"
    if backend_runs.exists():
        return backend_runs / "library" / f"project_{int(project_id)}"
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
        elif v == "bust_front":
            filename = f"{int(entity_id)}_bust.png"
        elif v == "bust_three_quarter":
            filename = f"{int(entity_id)}_bust_34.png"
        elif v == "bust_side":
            filename = f"{int(entity_id)}_bust_side.png"
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
            importance = _safe_str(item.get("importance") or item.get("importance_level"), "").strip()
            if entity_type == "character" and _is_crowd_character_entity(name=name, descriptor=descriptor, importance=importance):
                continue
            entities.append((entity_type, eid, name, descriptor))
    return entities


def _resolve_uri_path(uri: Any) -> Optional[Path]:
    if not isinstance(uri, str) or not uri.strip():
        return None
    p = Path(str(uri)).expanduser()
    if not p.is_absolute():
        candidates = [
            Path.cwd() / p,
            _backend_root() / p,
            _workspace_root() / p,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        p = candidates[0]
    return p


def _asset_exists(existing: Any, *, expected: Optional[Path] = None) -> bool:
    if expected is not None and expected.exists():
        return True
    if not isinstance(existing, dict):
        return False
    p = _resolve_uri_path(existing.get("uri"))
    return bool(p and p.exists())


def _build_character_view_summary(
    *,
    role_specs: List[Dict[str, Any]],
    existing_by_role: Dict[str, Dict[str, Any]],
    root: Path,
) -> List[Dict[str, Any]]:
    summary_by_entity: Dict[int, Dict[str, Any]] = {}
    for spec_item in role_specs:
        entity_type = str(spec_item.get("entity_type") or "").strip().lower()
        if entity_type != "character":
            continue
        try:
            entity_id = int(spec_item.get("entity_id") or 0)
        except Exception:  # noqa: BLE001
            continue
        if entity_id <= 0:
            continue
        name = str(spec_item.get("entity_name") or "").strip()
        view = spec_item.get("view")
        view_str = str(view).strip().lower() if isinstance(view, str) and view.strip() else ""
        role = str(spec_item.get("role") or "").strip()
        if not role or not view_str:
            continue

        expected = _output_path(root, "character", entity_id, view=view_str)
        ready = _asset_exists(existing_by_role.get(role), expected=expected)
        item = summary_by_entity.setdefault(
            entity_id,
            {
                "entity_id": int(entity_id),
                "entity_name": name,
                "required_views": [],
                "ready_views": [],
                "missing_views": [],
            },
        )
        if view_str not in item["required_views"]:
            item["required_views"].append(view_str)
        target_list = item["ready_views"] if ready else item["missing_views"]
        if view_str not in target_list:
            target_list.append(view_str)

    out: List[Dict[str, Any]] = []
    for entity_id in sorted(summary_by_entity.keys()):
        item = summary_by_entity[entity_id]
        # Keep order stable and aligned with configured view order.
        ordered_required = [v for v in _CHARACTER_VIEW_ORDER_DEFAULT if v in item["required_views"]]
        for v in item["required_views"]:
            if v not in ordered_required:
                ordered_required.append(v)
        item["required_views"] = ordered_required
        item["ready_views"] = [v for v in ordered_required if v in item["ready_views"]]
        item["missing_views"] = [v for v in ordered_required if v in item["missing_views"]]
        out.append(item)
    return out


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
    # Explicit regenerate requests should bypass passive/manual-only mode.
    manual_mode = bool(manual_mode and not force_regenerate and not bool(regen_role_set))
    ctx.payload["asset_library_manual"] = bool(manual_mode)
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

        character_view_summary = _build_character_view_summary(
            role_specs=role_specs,
            existing_by_role=existing_by_role,
            root=root,
        )
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
            "manual_mode": True,
            "character_views": list(character_views),
            "character_view_summary": character_view_summary,
        }
        ctx.payload["asset_library_done"] = True
        ctx.payload["asset_library_requires_review"] = bool(pending_count > 0 or unapproved_roles)
        return

    t2i_model_id = _resolve_registered_runtime_model_id(
        image_cfg,
        key="adapter",
        env_name="DREAMWEAVER_T2I_MODEL",
        default="wan2.6-t2i",
    ) or "wan2.6-t2i"
    t2i = create_runtime_client(t2i_model_id)
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
        image_edit_adapter = create_runtime_client(image_edit_adapter_name)
    except Exception:  # noqa: BLE001
        image_edit_adapter = None

    vlm_model_id = None
    vlm_adapter = None
    if selector in {"vlm", "semantic"}:
        vlm_model_id = _resolve_registered_runtime_model_id(
            image_cfg,
            key="vlm_adapter",
            env_name="DREAMWEAVER_VLM_ADAPTER",
            default="qwen3_vl_plus",
        )
        if vlm_model_id:
            try:
                vlm_adapter = create_runtime_client(vlm_model_id)
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
                        # Match style/ratio/size to avoid mixing inconsistent asset variants.
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

            if entity_type == "character" and view_str in _CHARACTER_VIEW_DEPENDENCIES:
                dependencies: List[Tuple[str, Path]] = []
                for dep_view in _CHARACTER_VIEW_DEPENDENCIES.get(view_str, []):
                    dep_role = _build_role("character", entity_id, view=dep_view)
                    dep_path = _output_path(root, "character", entity_id, view=dep_view)
                    dependencies.append((dep_role, dep_path))

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
            local_t2i = create_runtime_client(t2i_model_id)
            if selector in {"vlm", "semantic"} and vlm_model_id:
                try:
                    local_vlm = create_runtime_client(vlm_model_id)
                except Exception:  # noqa: BLE001
                    local_vlm = None
            try:
                local_image_edit = create_runtime_client(image_edit_adapter_name)
            except Exception:  # noqa: BLE001
                local_image_edit = None

        via = "t2i"
        edit_base: Optional[Path] = None
        edit_base_role = ""
        edit_reference_images: List[Dict[str, Any]] = []
        force_view_edit = bool(
            force_view_chain_image_edit
            and entity_type == "character"
            and view in _CHARACTER_VIEW_DEPENDENCIES
        )
        generation_meta: Dict[str, Any] = {}
        if entity_type == "character" and view in _CHARACTER_VIEW_DEPENDENCIES:
            dependency_views = _CHARACTER_VIEW_DEPENDENCIES.get(view, [])
            base_view = _CHARACTER_VIEW_BASE.get(view or "")
            extra_ref_views = _CHARACTER_VIEW_EXTRA_REFS.get(view, [])

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

            chain_paths: Dict[str, Optional[Path]] = {}
            for dep_view in dependency_views:
                dep_role = _build_role("character", entity_id, view=dep_view)
                dep_expected = _output_path(root, "character", entity_id, view=dep_view)
                chain_paths[dep_view] = _resolve_chain_path(dep_role, dep_expected)

            if base_view:
                edit_base_role = _build_role("character", entity_id, view=base_view)
                edit_base = chain_paths.get(base_view)

            for ref_view in extra_ref_views:
                ref_path = chain_paths.get(ref_view)
                if ref_path is None or ref_view == base_view:
                    continue
                ref_role = _build_role("character", entity_id, view=ref_view)
                edit_reference_images.append(
                    {
                        "path": ref_path,
                        "desc": f"{_CHARACTER_VIEW_CN_LABEL.get(ref_view, ref_view)} reference ({name or entity_id})",
                        "role": ref_role,
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
                allow_multi_ref = bool(view != "back" or enable_back_multi_ref)
                use_multi_ref = bool(edit_reference_images and allow_multi_ref and image_edit_multi_ref)
                generation_meta = _generate_edit_with_candidates(
                    adapter=local_image_edit,
                    image_path=edit_base,
                    edit_prompt=prompt,
                    reference_desc=f"{_CHARACTER_VIEW_CN_LABEL.get(_CHARACTER_VIEW_BASE.get(view or ''), 'base')} ({name or entity_id})",
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
            "image_model": image_edit_adapter_name if via == "image_edit" else t2i_model_id,
            "negative_prompt": style_negative_prompt,
            "approved": False,
        }
        if vlm_model_id:
            meta["vision_model"] = vlm_model_id
        if via == "image_edit":
            meta["t2i_fallback_model"] = t2i_model_id
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

    character_view_summary = _build_character_view_summary(
        role_specs=role_specs,
        existing_by_role=existing_by_role,
        root=root,
    )
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
        "manual_mode": False,
        "character_views": list(character_views),
        "character_view_summary": character_view_summary,
    }
    ctx.payload["asset_library_done"] = done
    ctx.payload["asset_library_requires_review"] = bool(done and unapproved_roles)
    if done:
        ctx.payload.pop("asset_library_force_regenerate", None)
        ctx.payload.pop("asset_library_progress", None)
        ctx.payload.pop("asset_library_regenerate_roles", None)
        ctx.payload.pop("asset_library_regenerate_progress", None)



