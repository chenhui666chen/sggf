from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline.media_presets import normalize_frame_ratio
from pipeline.style_presets import normalize_style_preset


def _parse_entity_id_from_role(role: Any) -> Optional[int]:
    text = str(role or "").strip()
    if ":" not in text:
        return None
    _, raw_id = text.split(":", 1)
    try:
        return int(raw_id)
    except Exception:  # noqa: BLE001
        return None


def _coerce_character_view(value: Any) -> Optional[str]:
    v = str(value or "").strip().lower()
    if v in {"front", "side", "back"}:
        return v
    return None


def _infer_character_view_from_role(role: Any) -> Optional[str]:
    text = str(role or "").strip()
    if text.startswith("lib_character_portrait_side"):
        return "side"
    if text.startswith("lib_character_portrait_back"):
        return "back"
    if text.startswith("lib_character_portrait"):
        return "front"
    return None


def _infer_shot_character_view_prefs(text: str) -> List[str]:
    """
    从镜头文本中推断更需要的“角色参考视角”，用于按需注入 side/back 角色卡。
    说明（KISS）：
    - 仅做关键词触发，不做复杂 NLP；
    - 未触发时返回空列表（保持默认只用正面角色卡）。
    """
    t = str(text or "").lower()
    prefs: List[str] = []
    back_keywords = ("背面", "背影", "背对", "背身", "from behind", "back view", "rear view")
    side_keywords = ("侧面", "侧身", "侧脸", "侧视", "profile", "side view")
    back_hits = any(k in t for k in back_keywords)
    side_hits = any(k in t for k in side_keywords)
    if back_hits:
        prefs.append("back")
    if side_hits:
        prefs.append("side")
    return prefs


def library_assets_from_payload(payload: Any) -> List[Dict[str, Any]]:
    """
    从 payload.project_assets 中提取“已审核可用”的素材库资产（角色/场景/道具卡）。

    设计目标（KISS）：
    - 只做过滤与结构化，不引入额外推理；
    - 避免跨 style_preset / ratio 复用导致风格/构图漂移。
    """
    if not isinstance(payload, dict):
        return []
    items = payload.get("project_assets")
    if not isinstance(items, list):
        return []

    current_style_preset = normalize_style_preset(payload.get("style_preset") if isinstance(payload.get("style_preset"), str) else None)

    image_cfg = payload.get("image_config") if isinstance(payload.get("image_config"), dict) else {}
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

        asset_style_preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
        if current_style_preset and asset_style_preset and asset_style_preset != current_style_preset:
            continue

        asset_ratio = str(meta.get("ratio") or "").strip()
        if current_ratio:
            if not asset_ratio:
                continue
            if normalize_frame_ratio(asset_ratio, default=current_ratio) != current_ratio:
                continue

        entity_type = str(meta.get("entity_type") or "").strip().lower()
        if not entity_type:
            # 向后兼容：根据 role 推断类型
            if role.startswith("lib_character_portrait"):
                entity_type = "character"
            elif role.startswith("lib_scene_card"):
                entity_type = "scene"
            elif role.startswith("lib_prop_card"):
                entity_type = "prop"
            else:
                entity_type = "unknown"

        entity_id = None
        try:
            entity_id = int(meta.get("entity_id")) if meta.get("entity_id") is not None else None
        except Exception:  # noqa: BLE001
            entity_id = None
        if entity_id is None:
            entity_id = _parse_entity_id_from_role(role)

        view: Optional[str] = None
        if entity_type == "character":
            view = _coerce_character_view(meta.get("view")) or _infer_character_view_from_role(role) or "front"

        name = str(meta.get("entity_name") or meta.get("name") or "").strip()
        descriptor = str(meta.get("descriptor") or "").strip()
        path = Path(uri)
        if not path.exists():
            continue

        # 用于 VLM/调试的短描述：带标签，避免“参考图 0/1”不可读
        tag = "素材"
        if entity_type == "character":
            tag = "角色卡"
        elif entity_type == "scene":
            tag = "场景卡"
        elif entity_type == "prop":
            tag = "道具卡"
        short_desc = descriptor.replace("\n", " ").strip()
        if len(short_desc) > 80:
            short_desc = short_desc[:80]
        label = f"[{tag}] {name}" if name else f"[{tag}] {role}"
        if short_desc:
            label = f"{label}：{short_desc}"
        if entity_type == "character":
            view_tag = {"front": "正面", "side": "侧面", "back": "背面"}.get(view or "front", "正面")
            label = label.replace(f"[{tag}]", f"[{tag}][{view_tag}]", 1)

        assets.append(
            {
                "role": role,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "entity_name": name or role,
                "descriptor": descriptor,
                "view": view,
                "path": path,
                "desc": label,
            }
        )
    return assets


def _as_str_list(value: Any, *, limit: int = 12) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        s = str(item).strip()
        if not s or s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def match_library_assets_for_shot(
    *,
    shot: Dict[str, Any],
    library_assets: List[Dict[str, Any]],
    max_character_refs: int = 4,
) -> Dict[str, Any]:
    """
    选取与镜头相关的角色卡/场景卡/道具卡，并生成“稳定的角色/场景 prompt 片段”。
    """
    max_character_refs = max(0, int(max_character_refs))

    explicit_chars = _as_str_list(shot.get("ff_vis_char_ids")) + _as_str_list(shot.get("lf_vis_char_ids"))
    explicit_chars = [c for i, c in enumerate(explicit_chars) if c and c not in explicit_chars[:i]]

    text = " ".join(
        [
            str(shot.get("visual_desc") or ""),
            str(shot.get("desc") or ""),
            str(shot.get("ff_desc") or ""),
            str(shot.get("lf_desc") or ""),
        ]
    )

    character_assets: List[Dict[str, Any]] = []
    scene_assets: List[Dict[str, Any]] = []
    prop_assets: List[Dict[str, Any]] = []

    # 角色卡可能包含多视角，按 entity_id/name 聚合，避免“同一角色多视角”导致 prompt_fragment 重复
    char_groups: Dict[str, Dict[str, Dict[str, Any]]] = {}
    char_name_by_key: Dict[str, str] = {}
    char_insertion_order: List[str] = []
    matched_by_text: set[str] = set()

    for asset in library_assets:
        et = str(asset.get("entity_type") or "").strip().lower()
        name = str(asset.get("entity_name") or "").strip()
        if et == "character":
            raw_key = asset.get("entity_id")
            key = str(raw_key).strip() if raw_key is not None else ""
            if not key:
                key = name or str(asset.get("role") or "").strip()
            if not key:
                continue

            if key not in char_groups:
                char_groups[key] = {}
                char_insertion_order.append(key)
                char_name_by_key[key] = name

            view = str(asset.get("view") or "").strip().lower()
            if view not in {"front", "side", "back"}:
                view = _infer_character_view_from_role(asset.get("role")) or "front"
            char_groups[key].setdefault(view, asset)

            if name and name in text:
                matched_by_text.add(key)
        elif et == "scene":
            if name and name in text:
                scene_assets.append(asset)
        elif et == "prop":
            if name and name in text:
                prop_assets.append(asset)

    matched_keys: List[str] = []

    def _push_key(k: str) -> None:
        if k and k not in matched_keys:
            matched_keys.append(k)

    # 显式角色顺序优先
    for c in explicit_chars:
        if not c:
            continue
        for k in char_insertion_order:
            if char_name_by_key.get(k) == c:
                _push_key(k)

    # 其次：文本命中
    for k in char_insertion_order:
        if k in matched_by_text:
            _push_key(k)

    # 先保证“每个命中角色至少 1 张正面卡”（或退化任意可用卡），再按视角补齐 side/back
    view_prefs = _infer_shot_character_view_prefs(text)
    if max_character_refs > 0 and matched_keys and char_groups:
        seen_roles: set[str] = set()

        def _push_asset(a: Optional[Dict[str, Any]]) -> None:
            if not isinstance(a, dict):
                return
            role = str(a.get("role") or "").strip()
            if not role or role in seen_roles:
                return
            seen_roles.add(role)
            character_assets.append(a)

        def _front_or_any(group: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            for v in ("front", "side", "back"):
                a = group.get(v)
                if isinstance(a, dict):
                    return a
            return None

        for k in matched_keys:
            if len(character_assets) >= max_character_refs:
                break
            _push_asset(_front_or_any(char_groups.get(k) or {}))

        # 主角色补齐：按 prefs 逐个尝试（例如背面/侧面）
        if view_prefs and len(character_assets) < max_character_refs:
            primary = matched_keys[0]
            group = char_groups.get(primary) or {}
            for v in view_prefs:
                if len(character_assets) >= max_character_refs:
                    break
                _push_asset(group.get(v))

            # 次要角色只补首选视角 1 张，避免挤占角色覆盖面（KISS）
            if len(character_assets) < max_character_refs and len(matched_keys) > 1:
                secondary_view = view_prefs[0]
                for k in matched_keys[1:]:
                    if len(character_assets) >= max_character_refs:
                        break
                    _push_asset((char_groups.get(k) or {}).get(secondary_view))

    # 场景卡兜底：未命中时也尽量带一张（用于风格/空间一致性）
    if not scene_assets:
        for asset in library_assets:
            if str(asset.get("entity_type") or "").strip().lower() == "scene":
                scene_assets.append(asset)
                break

    # 去重（按 role）
    def _dedupe_by_role(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[str] = set()
        out: List[Dict[str, Any]] = []
        for it in items:
            role = str(it.get("role") or "").strip()
            if not role or role in seen:
                continue
            seen.add(role)
            out.append(it)
        return out

    character_assets = _dedupe_by_role(character_assets)[:max_character_refs] if max_character_refs else []
    scene_assets = _dedupe_by_role(scene_assets)[:1]
    prop_assets = _dedupe_by_role(prop_assets)[:2]

    issues: List[str] = []
    if explicit_chars and not character_assets:
        issues.append("missing_character_card")
    if not scene_assets:
        issues.append("missing_scene_card")

    def _format_entity_line(asset: Dict[str, Any]) -> str:
        name = str(asset.get("entity_name") or "").strip()
        desc = str(asset.get("descriptor") or "").replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:120]
        if name and desc:
            return f"- {name}：{desc}"
        if name:
            return f"- {name}"
        if desc:
            return f"- {desc}"
        return "- (unknown)"

    fragment_parts: List[str] = []
    fragment_char_entities: List[Dict[str, Any]] = []
    seen_char_entities: set[str] = set()
    for a in character_assets:
        if not isinstance(a, dict):
            continue
        k = str(a.get("entity_id") or a.get("entity_name") or a.get("role") or "").strip()
        if not k or k in seen_char_entities:
            continue
        seen_char_entities.add(k)
        fragment_char_entities.append(a)

    if fragment_char_entities:
        fragment_parts.append("人物设定（固定，必须保持一致）：")
        fragment_parts.extend([_format_entity_line(a) for a in fragment_char_entities])
    if scene_assets:
        fragment_parts.append("场景设定（固定，必须保持一致）：")
        fragment_parts.extend([_format_entity_line(a) for a in scene_assets])
    if prop_assets:
        fragment_parts.append("道具设定（固定，尽量保持一致）：")
        fragment_parts.extend([_format_entity_line(a) for a in prop_assets])

    fragment = "\n".join(fragment_parts).strip()

    return {
        "character_assets": character_assets,
        "scene_assets": scene_assets,
        "prop_assets": prop_assets,
        "issues": issues,
        "prompt_fragment": fragment,
    }


def apply_prompt_fragment(prompt: str, fragment: str) -> str:
    base = str(prompt or "").strip()
    frag = str(fragment or "").strip()
    if not frag:
        return base
    if not base:
        return frag
    return f"{base}\n\n{frag}"


def build_reference_pack(
    *,
    anchor: Optional[Dict[str, Any]],
    match: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    按“锚点卡 + 角色卡 + 场景卡”的顺序组织参考集，并输出缺失项提示。

    说明：
    - 这里的 reference pack 主要用于 VLM（选优/重写/评估）；
    - 底层 T2I/I2V 不一定支持图片条件，但把参考集结构化可用于“导演式评估”与调试。
    """
    issues: List[str] = []
    match_issues = match.get("issues") if isinstance(match.get("issues"), list) else []
    for issue in match_issues:
        if isinstance(issue, str) and issue.strip() and issue not in issues:
            issues.append(issue.strip())

    anchor_path = anchor.get("path") if isinstance(anchor, dict) else None
    anchor_valid = isinstance(anchor_path, Path) and anchor_path.exists()
    if not anchor_valid:
        issues.append("missing_anchor_card")

    character_assets = match.get("character_assets") if isinstance(match.get("character_assets"), list) else []
    scene_assets = match.get("scene_assets") if isinstance(match.get("scene_assets"), list) else []

    refs: List[Dict[str, Any]] = []

    def _push(ref: Optional[Dict[str, Any]]) -> None:
        if not isinstance(ref, dict):
            return
        path = ref.get("path")
        if not isinstance(path, Path) or not path.exists():
            return
        refs.append({"path": path, "desc": str(ref.get("desc") or "").strip()})

    if anchor_valid:
        _push(anchor)
    for asset in character_assets:
        _push({"path": asset.get("path"), "desc": asset.get("desc")})
    for asset in scene_assets:
        _push({"path": asset.get("path"), "desc": asset.get("desc")})

    # 补充少量道具卡（非强制）
    for asset in match.get("prop_assets") if isinstance(match.get("prop_assets"), list) else []:
        if len(refs) >= 8:
            break
        _push({"path": asset.get("path"), "desc": asset.get("desc")})

    # 去重，保序
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.get("path"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(ref)

    return deduped, issues
