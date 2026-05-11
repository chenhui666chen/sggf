from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.dreamweaver.library import (
    build_library_prompt,
    parse_library_role,
)

logger = logging.getLogger(__name__)

_CHARACTER_VIEW_PREFIX_TO_VIEW = {
    "lib_character_portrait": "front",
    "lib_character_portrait_side": "side",
    "lib_character_portrait_back": "back",
    "lib_character_portrait_bust": "bust_front",
    "lib_character_portrait_bust_three_quarter": "bust_three_quarter",
    "lib_character_portrait_bust_side": "bust_side",
}
_CHARACTER_VIEW_TO_PREFIX = {value: key for key, value in _CHARACTER_VIEW_PREFIX_TO_VIEW.items()}
_CHARACTER_VIEW_SEED_BASE = {
    "side": "front",
    "back": "side",
    "bust_front": "front",
    "bust_three_quarter": "bust_front",
    "bust_side": "bust_three_quarter",
}
_CHARACTER_VIEW_REFERENCE_EXTRA = {
    "side": ["bust_front"],
    "back": ["front", "bust_front"],
    "bust_front": [],
    "bust_three_quarter": ["front", "side"],
    "bust_side": ["side", "bust_front"],
}


def _character_view_from_role(role: str) -> str:
    prefix = str(role or "").strip().split(":", 1)[0]
    return _CHARACTER_VIEW_PREFIX_TO_VIEW.get(prefix, "default")


def _character_role_for_view(*, entity_id: int, view: str) -> str:
    prefix = _CHARACTER_VIEW_TO_PREFIX.get(str(view or "").strip().lower())
    if not prefix:
        raise ValueError(f"unsupported character view: {view!r}")
    return f"{prefix}:{int(entity_id)}"


def _build_library_prompt(
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str] = None,
    ratio: Optional[str] = None,
) -> str:
    return build_library_prompt(
        entity_type=entity_type,
        name=name,
        descriptor=descriptor,
        style_prompt=style_prompt,
        ratio=ratio,
    )


def _augment_library_prompt_for_role(*, role: str, prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""

    prefix = str(role or "").strip().split(":", 1)[0]
    if prefix not in _CHARACTER_VIEW_PREFIX_TO_VIEW:
        return text

    def _norm_key(s: str) -> str:
        lowered = str(s or "").strip().lower()
        return "".join(ch for ch in lowered if ch.isalnum())

    hints: List[str] = [
        "背景：纯色背景，画面干净，无场景杂物、无文字、无水印、无 logo。",
        "约束：单人主体，完整构图，避免裁切关键部位。",
    ]
    if prefix == "lib_character_portrait_side":
        hints.append("构图：侧面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：与正面图保持同一角色身份锚点，重点保持发型、五官、服装和配件一致。")
    elif prefix == "lib_character_portrait_back":
        hints.append("构图：背面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：与正面和侧面图保持同一角色身份锚点，重点保持发型轮廓、服装版型与配色一致。")
    elif prefix == "lib_character_portrait_bust":
        hints.append("构图：正面半身单人肖像（胸像到腰部），面部为主并保留肩颈与上半身服饰结构。")
        hints.append("一致性要求：与全身正面保持同一角色身份锚点，重点保持五官、发型、领口与肩颈服饰细节一致。")
    elif prefix == "lib_character_portrait_bust_three_quarter":
        hints.append("构图：3/4 视角半身单人肖像（胸像到腰部），面部为主并清晰呈现肩颈与上半身服饰结构。")
        hints.append("一致性要求：与半身正面和全身侧面保持同一角色身份锚点，重点保持侧脸轮廓与上半身服饰结构一致。")
    elif prefix == "lib_character_portrait_bust_side":
        hints.append("构图：侧面半身单人肖像（胸像到腰部），突出侧脸轮廓并保留肩颈与上半身服饰结构。")
        hints.append("一致性要求：与半身 3/4 和全身侧面保持同一角色身份锚点，重点保持侧脸轮廓、发型与肩颈服饰细节一致。")
    else:
        hints.append("构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不被裁切。")
        hints.append("一致性要求：保持角色身份锚点稳定，突出发型、五官、服装与配件特征。")

    merged = text
    existing_key = _norm_key(text)
    for hint in hints:
        hint_key = _norm_key(hint)
        if hint_key and hint_key in existing_key:
            continue
        merged = f"{merged}\n{hint}"
        existing_key = _norm_key(merged)
    return merged.strip()


def _merge_descriptor_texts(*parts: Any, limit: int = 1400) -> str:
    seen: set[str] = set()
    merged: List[str] = []
    for part in parts:
        if not isinstance(part, str):
            continue
        text = part.replace("\r", "\n").strip()
        if not text:
            continue

        normalized = text.replace("\uFF0C", ",").replace("\uFF1B", ";").replace("\n", ";")
        chunks = [seg.strip(" \n\t,;.") for seg in normalized.replace(",", ";").split(";")]
        for chunk in chunks:
            if not chunk:
                continue
            key = "".join(chunk.split()).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(chunk)

    if not merged:
        return ""
    out = "; ".join(merged)
    return out[: max(32, int(limit))]


def _meta_prompt_text(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("prompt") or meta.get("suggested_prompt") or "").strip()


def _meta_descriptor_text(meta: Dict[str, Any]) -> str:
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("descriptor") or "").strip()


def _is_placeholder_entity_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.fullmatch(r"[?\s]+", text):
        return True
    lowered = text.lower()
    if lowered in {"unknown", "n/a", "na"}:
        return True
    if text in {"未知", "未命名", "角色", "人物", "角色名"}:
        return True
    if text.startswith("lib_"):
        return True
    return False


def _resolve_character_view_prompt_seed(
    *,
    role: str,
    assets_by_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    view = _character_view_from_role(role)
    if view not in _CHARACTER_VIEW_SEED_BASE:
        return {}

    try:
        _entity_type, entity_id = parse_library_role(role)
    except Exception as e:
        logger.debug("Failed to parse library role '%s' for view prompt seed: %s", role, e)
        return {}

    front_role = _character_role_for_view(entity_id=int(entity_id), view="front")
    base_view = _CHARACTER_VIEW_SEED_BASE.get(view, "front")
    base_role = _character_role_for_view(entity_id=int(entity_id), view=base_view)

    def _asset_meta(role_name: str) -> Dict[str, Any]:
        asset = assets_by_role.get(role_name) if isinstance(assets_by_role.get(role_name), dict) else {}
        return asset.get("meta") if isinstance(asset.get("meta"), dict) else {}

    front_meta = _asset_meta(front_role)
    base_meta = _asset_meta(base_role)
    seed_role = base_role if base_meta else front_role
    seed_meta = base_meta if base_meta else front_meta

    seed_prompt = _meta_prompt_text(seed_meta) or _meta_prompt_text(front_meta)
    anchor_descriptor = _meta_descriptor_text(front_meta) or _meta_descriptor_text(seed_meta)

    ref_roles: List[str] = []
    ref_views = [base_view] + _CHARACTER_VIEW_REFERENCE_EXTRA.get(view, [])
    for ref_view in ref_views:
        ref_role = _character_role_for_view(entity_id=int(entity_id), view=ref_view)
        ref_meta = _asset_meta(ref_role)
        if ref_meta and ref_role not in ref_roles:
            ref_roles.append(ref_role)
    if front_meta and front_role not in ref_roles:
        ref_roles.append(front_role)

    return {
        "seed_role": seed_role,
        "seed_prompt": seed_prompt,
        "anchor_descriptor": anchor_descriptor,
        "reference_roles": ref_roles,
    }


def _resolve_prompt_seed_for_role(
    *,
    role: str,
    assets_by_role: Dict[str, Dict[str, Any]],
    request_prompt: str,
    current_prompt: str,
    descriptor: str,
    force_view_chain_seed: bool = False,
) -> Tuple[str, str, Dict[str, Any], bool]:
    request_prompt_text = str(request_prompt or "").strip()
    current_prompt_text = str(current_prompt or "").strip()
    seed_info = _resolve_character_view_prompt_seed(role=role, assets_by_role=assets_by_role)
    if not isinstance(seed_info, dict):
        seed_info = {}

    seed_prompt = str(seed_info.get("seed_prompt") or "").strip()
    anchor_descriptor = str(seed_info.get("anchor_descriptor") or "").strip()
    manual_override = bool(request_prompt_text and request_prompt_text != current_prompt_text)
    raw_prompt = request_prompt_text or current_prompt_text

    if force_view_chain_seed and seed_prompt:
        manual_override = False
        raw_prompt = seed_prompt

    if seed_prompt and not manual_override:
        raw_prompt = seed_prompt
    if anchor_descriptor:
        descriptor = _merge_descriptor_texts(anchor_descriptor, descriptor, limit=1400)

    return raw_prompt, descriptor, seed_info, manual_override


def _attach_view_chain_prompt_meta(
    meta: Dict[str, Any],
    *,
    seed_info: Dict[str, Any],
    manual_override: bool,
) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        return {}

    seed_role = str(seed_info.get("seed_role") or "").strip() if isinstance(seed_info, dict) else ""
    reference_roles = []
    if isinstance(seed_info, dict) and isinstance(seed_info.get("reference_roles"), list):
        reference_roles = [str(item).strip() for item in seed_info.get("reference_roles", []) if str(item).strip()]

    if seed_role:
        meta["view_chain_prompt_seed_role"] = seed_role
    if reference_roles:
        meta["view_chain_reference_roles"] = reference_roles
    meta["view_chain_manual_prompt_override"] = bool(manual_override)
    return meta
