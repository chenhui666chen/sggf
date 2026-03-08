from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.dreamweaver import DreamweaverAsset, DreamweaverProject
from app.models.setting import SettingCollection, SettingItem

from pipeline.media_presets import normalize_frame_ratio, normalize_image_resolution, resolve_frame_size
from pipeline.style_presets import normalize_style_preset, style_prompt_for_preset


LIB_ROLE_PREFIX = "lib_"
LIBRARY_ANCHOR_STATUS = "library"


def _backend_root_dir() -> Path:
    # library.py -> dreamweaver -> services -> app -> backend_root
    return Path(__file__).resolve().parents[3]


def _normalize_local_asset_uri(uri: str) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    if "://" in text:
        return text
    return text.replace("\\", "/")


def runs_root_path() -> Path:
    return (_backend_root_dir() / "runs").resolve()


def build_library_role(*, entity_type: str, entity_id: int) -> str:
    t = (entity_type or "").strip().lower()
    if t == "character":
        return f"lib_character_portrait:{int(entity_id)}"
    if t == "scene":
        return f"lib_scene_card:{int(entity_id)}"
    if t == "prop":
        return f"lib_prop_card:{int(entity_id)}"
    raise ValueError(f"unsupported entity_type: {entity_type!r}")


def is_library_role(role: str) -> bool:
    return isinstance(role, str) and role.startswith(LIB_ROLE_PREFIX)


def build_library_prompt(
    *,
    entity_type: str,
    name: str,
    descriptor: str,
    style_prompt: Optional[str],
    ratio: Optional[str],
) -> str:
    style = (style_prompt or "").strip() or style_prompt_for_preset(None)
    ratio_norm = normalize_frame_ratio(ratio)
    name = (name or "").strip()
    descriptor = (descriptor or "").strip()

    if entity_type == "character":
        return (
            f"人物设定：{descriptor}\n"
            "构图：正面全身单人立绘，头顶到脚底完整入镜，四肢完整不裁切。\n"
            f"风格：{style}（严格保持一致，不要混合风格）\n"
            f"画幅：{ratio_norm}\n"
            "背景：纯灰色背景板，背景完全干净，无场景元素、无杂物、无文字、无多余人物。\n"
            "一致性要求：角色身份锚点保持一致，突出发型、五官、服饰与配件等可识别特征。\n"
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


def _importance_rank(raw: Optional[str]) -> int:
    if not raw:
        return 0
    text = str(raw)
    if "主" in text:
        return 3
    if "重要" in text:
        return 2
    if "次" in text or "配" in text:
        return 1
    return 0


def _coalesce_text(*parts: Optional[str], limit: int = 200) -> str:
    buf: List[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            buf.append(part.strip())
    joined = "；".join(buf)
    return joined[:limit]


@dataclass(frozen=True)
class LibraryEntity:
    entity_type: str  # character|scene|prop
    entity_id: int
    name: str
    descriptor: str

    @property
    def role(self) -> str:
        return build_library_role(entity_type=self.entity_type, entity_id=self.entity_id)


def build_library_spec(
    db: Session,
    *,
    project_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .all()
    )
    characters_sorted = sorted(
        characters,
        key=lambda c: (-_importance_rank(getattr(c, "importance_level", None)), int(getattr(c, "id", 0))),
    )[: max(0, int(max_characters))]

    character_entities: List[LibraryEntity] = []
    for c in characters_sorted:
        name = str(getattr(c, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(c, "summary", None), getattr(c, "profile", None), limit=640)
        if not descriptor:
            descriptor = _coalesce_text(getattr(c, "gender", None), str(getattr(c, "age", "") or ""), limit=120)
        character_entities.append(
            LibraryEntity(entity_type="character", entity_id=int(c.id), name=name, descriptor=descriptor)
        )

    def _items_by_category(category: str, limit: int) -> List[SettingItem]:
        col_ids = [
            int(c.id)
            for c in (
                db.query(SettingCollection)
                .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
                .all()
            )
        ]
        if not col_ids:
            return []
        q = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(col_ids))
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.usage_count.desc(), SettingItem.updated_at.desc(), SettingItem.id.asc())
        )
        return q.limit(max(0, int(limit))).all()

    scene_items = _items_by_category("map_system", max_scenes)
    prop_items = _items_by_category("artifact_system", max_props)

    scene_entities: List[LibraryEntity] = []
    for item in scene_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        scene_entities.append(
            LibraryEntity(entity_type="scene", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    prop_entities: List[LibraryEntity] = []
    for item in prop_items:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        descriptor = _coalesce_text(getattr(item, "summary", None), getattr(item, "content", None), limit=420)
        prop_entities.append(
            LibraryEntity(entity_type="prop", entity_id=int(item.id), name=name, descriptor=descriptor)
        )

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def build_library_spec_from_script_entities(
    db: Session,
    *,
    project_id: int,
    entities: Dict[str, Any],
) -> Dict[str, Any]:
    """
    基于单次剧本抽取的 script_entities 构建“本章节用到的”素材库 spec：
    - 角色：Character（project_id + name）
    - 场景：SettingItem（category=map_system）
    - 道具：SettingItem（category=artifact_system）

    说明：script_entities 以 name 为主键做对齐；若未能在项目库中命中，则该实体会被跳过。
    """
    if not isinstance(entities, dict):
        entities = {}

    def _pick_named_items(raw: Any) -> List[Tuple[str, str]]:
        items = raw if isinstance(raw, list) else []
        seen: set[str] = set()
        out: List[Tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            descriptor = str(item.get("descriptor") or "").strip()
            out.append((name, descriptor))
        return out

    # 1) Characters
    character_pairs = _pick_named_items(entities.get("characters"))
    character_names = [name for name, _ in character_pairs]
    characters_by_name: Dict[str, Character] = {}
    if character_names:
        rows = db.query(Character).filter(Character.project_id == project_id, Character.name.in_(character_names)).all()
        characters_by_name = {str(getattr(c, "name", "") or ""): c for c in rows if str(getattr(c, "name", "") or "").strip()}

    character_entities: List[LibraryEntity] = []
    for name, descriptor in character_pairs:
        row = characters_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "profile", None), limit=640)
        if not resolved:
            resolved = _coalesce_text(getattr(row, "gender", None), str(getattr(row, "age", "") or ""), limit=120)
        character_entities.append(LibraryEntity(entity_type="character", entity_id=int(row.id), name=name, descriptor=resolved))

    def _setting_items_by_name(category: str, names: List[str]) -> Dict[str, SettingItem]:
        if not names:
            return {}
        col_ids = [
            int(c.id)
            for c in (
                db.query(SettingCollection)
                .filter(SettingCollection.project_id == project_id, SettingCollection.category == category)
                .all()
            )
            if getattr(c, "id", None) is not None
        ]
        if not col_ids:
            return {}
        rows = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(col_ids), SettingItem.name.in_(names))
            .filter(SettingItem.is_leaf == True)  # noqa: E712
            .order_by(SettingItem.id.asc())
            .all()
        )
        return {str(getattr(r, "name", "") or ""): r for r in rows if str(getattr(r, "name", "") or "").strip()}

    # 2) Scenes
    scene_pairs = _pick_named_items(entities.get("scenes"))
    scene_names = [name for name, _ in scene_pairs]
    scenes_by_name = _setting_items_by_name("map_system", scene_names)

    scene_entities: List[LibraryEntity] = []
    for name, descriptor in scene_pairs:
        row = scenes_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        scene_entities.append(LibraryEntity(entity_type="scene", entity_id=int(row.id), name=name, descriptor=resolved))

    # 3) Props
    prop_pairs = _pick_named_items(entities.get("props"))
    prop_names = [name for name, _ in prop_pairs]
    props_by_name = _setting_items_by_name("artifact_system", prop_names)

    prop_entities: List[LibraryEntity] = []
    for name, descriptor in prop_pairs:
        row = props_by_name.get(name)
        if row is None or getattr(row, "id", None) is None:
            continue
        resolved = descriptor or _coalesce_text(getattr(row, "summary", None), getattr(row, "content", None), limit=420)
        prop_entities.append(LibraryEntity(entity_type="prop", entity_id=int(row.id), name=name, descriptor=resolved))

    return {
        "project_id": int(project_id),
        "characters": [e.__dict__ for e in character_entities],
        "scenes": [e.__dict__ for e in scene_entities],
        "props": [e.__dict__ for e in prop_entities],
    }


def load_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
) -> Dict[str, Dict[str, Any]]:
    """
    返回按 role 去重的最新素材库资产（跨 run，取 updated_at 最新的一条）。
    """
    rows = (
        db.query(DreamweaverAsset, DreamweaverProject)
        .join(DreamweaverProject, DreamweaverAsset.dreamweaver_project_id == DreamweaverProject.id)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .filter(DreamweaverAsset.asset_type == "image")
        .all()
    )

    def _uri_available(uri: str) -> bool:
        text = _normalize_local_asset_uri(uri)
        if not text:
            return False
        if "://" in text:
            return True
        try:
            p = resolve_asset_path(text).resolve()
            base = runs_root_path()
            if (p != base and base not in p.parents) or (not p.exists()):
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

    latest: Dict[str, Tuple[bool, datetime, DreamweaverAsset, DreamweaverProject]] = {}
    for asset, project in rows:
        role = str(getattr(asset, "role", "") or "")
        if not is_library_role(role):
            continue
        updated_at = getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)
        if not isinstance(updated_at, datetime):
            continue
        uri_ok = _uri_available(str(getattr(asset, "uri", "") or ""))
        prev = latest.get(role)
        if prev is None:
            latest[role] = (uri_ok, updated_at, asset, project)
            continue

        prev_uri_ok, prev_updated_at, _prev_asset, _prev_project = prev
        # Prefer assets whose underlying file actually exists; within same availability, pick latest.
        if (uri_ok and not prev_uri_ok) or (uri_ok == prev_uri_ok and updated_at > prev_updated_at):
            latest[role] = (uri_ok, updated_at, asset, project)

    result: Dict[str, Dict[str, Any]] = {}
    for role, (uri_ok, _ts, asset, project) in latest.items():
        meta = asset.meta_json if isinstance(asset.meta_json, dict) else {}
        approved = bool(meta.get("approved")) if isinstance(meta, dict) else False

        # 向后兼容：旧资产可能没有在 meta 中记录 style_preset/style_prompt，
        # 这里从所属 DreamweaverProject.contract_json.runtime_config 推断并补齐到返回值（不落库）。
        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0
        try:
            contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
            runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
            if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
                inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
            if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
                inferred_prompt = runtime_cfg.get("style_prompt").strip()
            elif inferred_preset:
                inferred_prompt = style_prompt_for_preset(inferred_preset)
            image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
            if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
                inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
            else:
                inferred_ratio = normalize_frame_ratio(None)
            if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
                inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
            else:
                inferred_resolution = normalize_image_resolution(None)

            image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
            if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
                image_cfg_for_size["ratio"] = inferred_ratio
            if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
                image_cfg_for_size["resolution"] = inferred_resolution
            inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
        except Exception:  # noqa: BLE001
            inferred_preset = ""
            inferred_prompt = ""
            inferred_ratio = ""
            inferred_resolution = ""
            inferred_width = 0
            inferred_height = 0

        merged_meta = dict(meta) if isinstance(meta, dict) else {}
        if inferred_preset and not str(merged_meta.get("style_preset") or "").strip():
            merged_meta["style_preset"] = inferred_preset
        if inferred_prompt and not str(merged_meta.get("style_prompt") or "").strip():
            merged_meta["style_prompt"] = inferred_prompt
        if inferred_ratio and not str(merged_meta.get("ratio") or "").strip():
            merged_meta["ratio"] = inferred_ratio
        if inferred_resolution and not str(merged_meta.get("resolution") or "").strip():
            merged_meta["resolution"] = inferred_resolution
        try:
            existing_width = int(merged_meta.get("width") or 0)
        except Exception:  # noqa: BLE001
            existing_width = 0
        try:
            existing_height = int(merged_meta.get("height") or 0)
        except Exception:  # noqa: BLE001
            existing_height = 0
        if inferred_width > 0 and existing_width <= 0:
            merged_meta["width"] = int(inferred_width)
        if inferred_height > 0 and existing_height <= 0:
            merged_meta["height"] = int(inferred_height)
        merged_meta["file_available"] = bool(uri_ok)

        result[role] = {
            "id": int(asset.id),
            "asset_type": str(asset.asset_type),
            "role": str(asset.role),
            "uri": str(asset.uri),
            "meta": {**merged_meta, "approved": approved},
            "updated_at": (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None)).isoformat()
            if (getattr(asset, "updated_at", None) or getattr(asset, "created_at", None))
            else None,
        }
    return result


def required_library_roles(spec: Dict[str, Any]) -> List[str]:
    def _character_view_roles(entity_id: int) -> List[str]:
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

        roles: List[str] = []
        for v in picked:
            if v == "front":
                roles.append(f"lib_character_portrait:{int(entity_id)}")
            elif v == "side":
                roles.append(f"lib_character_portrait_side:{int(entity_id)}")
            elif v == "back":
                roles.append(f"lib_character_portrait_back:{int(entity_id)}")
        return roles

    required_roles: List[str] = []
    section_defaults = {"characters": "character", "scenes": "scene", "props": "prop"}
    for key, default_entity_type in section_defaults.items():
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, int):
                try:
                    entity_id = int(entity_id)
                except Exception:  # noqa: BLE001
                    continue
            try:
                if str(entity_type or "").strip().lower() == "character":
                    required_roles.extend(_character_view_roles(int(entity_id)))
                else:
                    required_roles.append(build_library_role(entity_type=entity_type, entity_id=int(entity_id)))
            except Exception:  # noqa: BLE001
                continue
    return required_roles


def parse_library_role(role: str) -> Tuple[str, int]:
    text = str(role or "").strip()
    if text.startswith("lib_character_portrait:"):
        return "character", int(text.split(":", 1)[1])
    if text.startswith("lib_character_portrait_side:"):
        return "character", int(text.split(":", 1)[1])
    if text.startswith("lib_character_portrait_back:"):
        return "character", int(text.split(":", 1)[1])
    if text.startswith("lib_scene_card:"):
        return "scene", int(text.split(":", 1)[1])
    if text.startswith("lib_prop_card:"):
        return "prop", int(text.split(":", 1)[1])
    raise ValueError(f"invalid library role: {role!r}")


def default_library_asset_uri(*, project_id: int, role: str) -> str:
    entity_type, entity_id = parse_library_role(role)
    sub = "misc"
    if entity_type == "character":
        sub = "characters"
    elif entity_type == "scene":
        sub = "scenes"
    elif entity_type == "prop":
        sub = "props"
    filename = f"{int(entity_id)}.png"
    if entity_type == "character":
        if str(role).startswith("lib_character_portrait_side:"):
            filename = f"{int(entity_id)}_side.png"
        elif str(role).startswith("lib_character_portrait_back:"):
            filename = f"{int(entity_id)}_back.png"
    return (Path("runs") / "library" / f"project_{int(project_id)}" / sub / filename).as_posix()


def _infer_latest_runtime_meta(project: DreamweaverProject) -> Dict[str, Any]:
    inferred_preset = ""
    inferred_prompt = ""
    inferred_ratio = ""
    inferred_resolution = ""
    inferred_width = 0
    inferred_height = 0
    try:
        contract = project.contract_json if isinstance(getattr(project, "contract_json", None), dict) else {}
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        if isinstance(runtime_cfg.get("style_preset"), str) and runtime_cfg.get("style_preset").strip():
            inferred_preset = normalize_style_preset(runtime_cfg.get("style_preset"))
        if isinstance(runtime_cfg.get("style_prompt"), str) and runtime_cfg.get("style_prompt").strip():
            inferred_prompt = runtime_cfg.get("style_prompt").strip()
        elif inferred_preset:
            inferred_prompt = style_prompt_for_preset(inferred_preset)
        image_cfg = runtime_cfg.get("image_config") if isinstance(runtime_cfg.get("image_config"), dict) else {}
        if isinstance(image_cfg.get("ratio"), str) and str(image_cfg.get("ratio") or "").strip():
            inferred_ratio = normalize_frame_ratio(str(image_cfg.get("ratio") or ""))
        else:
            inferred_ratio = normalize_frame_ratio(None)
        if isinstance(image_cfg.get("resolution"), str) and str(image_cfg.get("resolution") or "").strip():
            inferred_resolution = normalize_image_resolution(str(image_cfg.get("resolution") or ""))
        else:
            inferred_resolution = normalize_image_resolution(None)

        image_cfg_for_size = dict(image_cfg) if isinstance(image_cfg, dict) else {}
        if inferred_ratio and not isinstance(image_cfg_for_size.get("ratio"), str):
            image_cfg_for_size["ratio"] = inferred_ratio
        if inferred_resolution and not isinstance(image_cfg_for_size.get("resolution"), str):
            image_cfg_for_size["resolution"] = inferred_resolution
        inferred_width, inferred_height, _ = resolve_frame_size(image_cfg_for_size)
    except Exception:  # noqa: BLE001
        inferred_preset = ""
        inferred_prompt = ""
        inferred_ratio = ""
        inferred_resolution = ""
        inferred_width = 0
        inferred_height = 0

    meta: Dict[str, Any] = {"approved": False}
    if inferred_preset:
        meta["style_preset"] = inferred_preset
    if inferred_prompt:
        meta["style_prompt"] = inferred_prompt
    if inferred_ratio:
        meta["ratio"] = inferred_ratio
    if inferred_resolution:
        meta["resolution"] = inferred_resolution
    if inferred_width > 0:
        meta["width"] = int(inferred_width)
    if inferred_height > 0:
        meta["height"] = int(inferred_height)
    return meta


def _library_anchor_run_id(*, project_id: int, user_id: int) -> str:
    return f"library_anchor:project:{int(project_id)}:user:{int(user_id)}"


def _ensure_library_anchor_project(db: Session, *, project_id: int, user_id: int) -> DreamweaverProject:
    anchor = (
        db.query(DreamweaverProject)
        .filter(
            DreamweaverProject.source_project_id == project_id,
            DreamweaverProject.user_id == user_id,
            DreamweaverProject.status == LIBRARY_ANCHOR_STATUS,
        )
        .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
        .first()
    )
    if anchor is not None:
        return anchor

    anchor_run_id = _library_anchor_run_id(project_id=project_id, user_id=user_id)
    preset = normalize_style_preset(None)
    style = style_prompt_for_preset(preset)
    ratio = normalize_frame_ratio(None)
    resolution = normalize_image_resolution(None)
    width, height, _ratio = resolve_frame_size({"ratio": ratio, "resolution": resolution})

    anchor = DreamweaverProject(
        run_id=anchor_run_id,
        source_project_id=project_id,
        user_id=user_id,
        schema_version="0.1.0",
        status=LIBRARY_ANCHOR_STATUS,
        state=None,
        stage=None,
        progress=0,
        error_type=None,
        error_message=None,
        contract_json={
            "runtime_config": {
                "style_preset": preset,
                "style_prompt": style,
                "image_config": {
                    "ratio": ratio,
                    "resolution": resolution,
                    "width": int(width),
                    "height": int(height),
                },
            }
        },
    )
    db.add(anchor)
    db.flush()
    return anchor


def ensure_required_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    spec: Dict[str, Any],
) -> int:
    """
    确保每个 required role 在 DB 里至少有一条 DreamweaverAsset 记录：
    - 解决“磁盘文件已存在但 DB 缺记录”导致的缺失/无法审批/无法重生成功能。
    - 若文件缺失，review 仍会判定为 missing（由 compute_library_review 负责）。
    """
    required_roles = required_library_roles(spec)
    if not required_roles:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    missing_roles = [r for r in required_roles if r not in assets_by_role]
    if not missing_roles:
        return 0

    latest_project = (
        db.query(DreamweaverProject)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .order_by(DreamweaverProject.updated_at.desc())
        .first()
    )
    if not latest_project:
        # 允许在“尚未跑过 DreamWeaver run”的情况下预生成项目素材库：创建/复用隐藏的 library anchor。
        latest_project = _ensure_library_anchor_project(db, project_id=project_id, user_id=user_id)

    runtime_meta = _infer_latest_runtime_meta(latest_project)
    entity_by_role: Dict[str, Dict[str, Any]] = {}
    for key in ("characters", "scenes", "props"):
        items = spec.get(key)
        if not isinstance(items, list):
            continue
        default_entity_type = "character" if key == "characters" else "scene" if key == "scenes" else "prop"
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or default_entity_type)
            try:
                entity_id = int(item.get("entity_id"))
            except Exception:  # noqa: BLE001
                continue
            name = str(item.get("name") or "").strip()
            descriptor = str(item.get("descriptor") or "").strip()
            try:
                role = build_library_role(entity_type=entity_type, entity_id=entity_id)
            except Exception:  # noqa: BLE001
                continue
            entity_by_role[role] = {
                "entity_type": entity_type,
                "entity_id": int(entity_id),
                "entity_name": name,
                "descriptor": descriptor,
            }

    created = 0
    for role in missing_roles:
        entity_meta = entity_by_role.get(role) or {}
        meta = {**runtime_meta, **entity_meta}
        if not str(meta.get("prompt") or "").strip():
            entity_type = str(entity_meta.get("entity_type") or "").strip()
            entity_name = str(entity_meta.get("entity_name") or "").strip()
            descriptor = str(entity_meta.get("descriptor") or "").strip()
            if entity_type and entity_name and descriptor:
                preset = normalize_style_preset(meta.get("style_preset") if isinstance(meta.get("style_preset"), str) else None)
                style = str(meta.get("style_prompt") or "").strip() or style_prompt_for_preset(preset)
                ratio = normalize_frame_ratio(meta.get("ratio") if isinstance(meta.get("ratio"), str) else None)
                prompt = build_library_prompt(
                    entity_type=entity_type,
                    name=entity_name,
                    descriptor=descriptor,
                    style_prompt=style,
                    ratio=ratio,
                )
                meta["prompt"] = prompt
                meta["suggested_prompt"] = prompt
        uri = default_library_asset_uri(project_id=project_id, role=role)
        db.add(
            DreamweaverAsset(
                dreamweaver_project_id=int(latest_project.id),
                episode_id=None,
                shot_id=None,
                asset_type="image",
                role=str(role),
                uri=str(uri),
                schema_version=str(getattr(latest_project, "schema_version", "") or "0.1.0"),
                meta_json=meta,
            )
        )
        created += 1

    if created:
        db.commit()
    return created


def compute_library_review(
    *,
    spec: Dict[str, Any],
    assets_by_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    required_roles = required_library_roles(spec)

    missing: List[str] = []
    unapproved: List[str] = []
    for role in required_roles:
        asset = assets_by_role.get(role)
        if not isinstance(asset, dict):
            missing.append(role)
            continue
        uri = asset.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            missing.append(role)
            continue
        if "://" not in uri:
            p = resolve_asset_path(uri)
            base = runs_root_path()
            resolved = p.resolve()
            if (resolved != base and base not in resolved.parents) or not resolved.exists():
                missing.append(role)
                continue
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        if not bool(meta.get("approved")):
            unapproved.append(role)

    return {
        "required_roles": required_roles,
        "missing_roles": missing,
        "unapproved_roles": unapproved,
        "approved": len(missing) == 0 and len(unapproved) == 0,
    }


def approve_latest_library_assets(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    roles: Iterable[str],
    approved: bool = True,
) -> int:
    roles_set = {str(r) for r in roles if isinstance(r, str) and is_library_role(r)}
    if not roles_set:
        return 0

    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    ids = []
    for role in roles_set:
        asset = assets_by_role.get(role)
        if isinstance(asset, dict) and isinstance(asset.get("id"), int):
            ids.append(int(asset["id"]))

    if not ids:
        return 0

    rows = db.query(DreamweaverAsset).filter(DreamweaverAsset.id.in_(ids)).all()
    updated = 0
    for row in rows:
        # SQLAlchemy 的 JSON 字段默认不跟踪 dict 的原地修改；这里显式复制避免“更新不落库”。
        meta = dict(row.meta_json) if isinstance(row.meta_json, dict) else {}
        meta["approved"] = bool(approved)
        row.meta_json = meta
        updated += 1

    db.commit()
    return updated


def resolve_asset_path(uri: str) -> Path:
    normalized = _normalize_local_asset_uri(uri)
    p = Path(str(normalized)).expanduser()
    if p.is_absolute():
        return p
    return _backend_root_dir() / p


def enrich_payload_with_library(
    db: Session,
    payload: Dict[str, Any],
    *,
    project_id: int,
    user_id: int,
    max_characters: int = 12,
    max_scenes: int = 8,
    max_props: int = 8,
) -> Dict[str, Any]:
    spec = build_library_spec(
        db,
        project_id=project_id,
        max_characters=max_characters,
        max_scenes=max_scenes,
        max_props=max_props,
    )
    assets_by_role = load_latest_library_assets(db, project_id=project_id, user_id=user_id)
    review = compute_library_review(spec=spec, assets_by_role=assets_by_role)

    payload["asset_library_spec"] = spec
    payload["project_assets"] = list(assets_by_role.values())
    payload["asset_library_review"] = review
    payload.setdefault(
        "asset_library_config",
        {"max_characters": max_characters, "max_scenes": max_scenes, "max_props": max_props},
    )
    return review
