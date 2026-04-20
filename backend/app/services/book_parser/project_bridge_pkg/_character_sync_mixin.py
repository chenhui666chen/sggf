from __future__ import annotations

import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.models.book_parser import BookSource, BookChapter, BookAnalysis
from app.models.project import Project, Chapter
from app.models.setting import SettingCollection, SettingItem
from app.models.character import Character
from app.models.user import User
from app.services.chapter_adaptation_assets import attach_cross_media_adaptation_hints
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    infer_story_stance_from_text_evidence,
)
from app.services.setting_templates import get_hierarchy_config_json
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

from app.services.book_parser.project_bridge_pkg._constants import (
    ANALYSIS_TO_COLLECTION,
    STRUCTURED_MEMORY_LIMITS,
    CANONICAL_STORY_STANCES,
    CANONICAL_ROLE_POSITIONS,
    GENERIC_ROLE_POSITIONS,
)

class CharacterSyncMixin:
    def _resolve_importance_level(
        self,
        char_data: Dict[str, Any],
        default_importance: str,
    ) -> str:
        """确定导入人物的重要程度。"""
        explicit_value = self._stringify_import_value(char_data.get("importance_level"))
        if explicit_value:
            return explicit_value

        role_position = self._normalize_role_position_value(char_data.get("role_position"))
        if role_position == "主角":
            return "主角"
        return default_importance

    def _upsert_import_character(
        self,
        project: Project,
        imported_by_key: Dict[str, Character],
        char_data: Dict[str, Any],
        mention_map: Dict[str, Dict[str, Any]],
        relationship_lookup: Dict[str, List[Dict[str, str]]],
        default_story_stance: str,
        default_role_position: str,
        default_importance: str,
        is_backfilled: bool = False,
    ) -> Optional[Character]:
        """导入或补全单个人物卡。"""
        canonical_name = self._normalize_import_character_name(char_data.get("name"))
        if not canonical_name:
            return None

        mention_info = mention_map.get(canonical_name, {})
        relationship_entries = relationship_lookup.get(canonical_name, [])
        summary = self._build_import_character_summary(
            name=canonical_name,
            char_data=char_data,
            mention_info=mention_info,
            is_backfilled=is_backfilled,
        )
        profile = self._build_import_character_profile(
            char_data=char_data,
            mention_info=mention_info,
            relationship_entries=relationship_entries,
            canonical_name=canonical_name,
            is_backfilled=is_backfilled,
            default_story_stance=default_story_stance,
            default_role_position=default_role_position,
        )
        tags = self._build_import_character_tags(char_data, mention_info, canonical_name)
        relation_to_main = self._stringify_import_value(char_data.get("relationship_to_main"))
        role_position = self._normalize_role_position_value(
            char_data.get("role_position"),
            relationship_to_main=relation_to_main,
            fallback=default_role_position,
        )
        explicit_story_stance = self._normalize_story_stance_value(char_data.get("story_stance"))
        role = explicit_story_stance or self._infer_story_stance(
            role_position=role_position,
            relationship_to_main=relation_to_main,
            fallback=default_story_stance,
            additional_texts=[
                char_data.get("description"),
                char_data.get("background_status"),
                char_data.get("mainline_role"),
                char_data.get("growth_direction"),
            ],
        )
        importance_level = self._resolve_importance_level(char_data, default_importance)
        faction = self._stringify_import_value(char_data.get("faction"))
        if faction == "未提及":
            faction = ""

        first_appearance = char_data.get("first_appearance_chapter") or mention_info.get("first_appearance_chapter")
        if isinstance(first_appearance, str) and first_appearance.isdigit():
            first_appearance = int(first_appearance)
        elif not isinstance(first_appearance, int):
            first_appearance = None

        existing = imported_by_key.get(canonical_name)
        if existing:
            existing.summary = self._prefer_longer_text(existing.summary, summary)
            existing.profile = self._prefer_longer_text(existing.profile, profile)
            if faction and not existing.faction:
                existing.faction = faction
            if self._should_replace_story_stance(existing.role, role, explicit=bool(explicit_story_stance)):
                existing.role = role
            if self._should_replace_role_position(existing.role_position, role_position):
                existing.role_position = role_position
            if importance_level and (
                not existing.importance_level
                or existing.importance_level in {"次要角色", "边缘角色", "群众角色"}
                or importance_level == "主角"
            ):
                existing.importance_level = importance_level
            if first_appearance and (
                existing.first_appearance_chapter is None or first_appearance < existing.first_appearance_chapter
            ):
                existing.first_appearance_chapter = first_appearance
            existing.appearance_status = existing.appearance_status or "已出场"
            existing.life_status = existing.life_status or "存活"
            existing.tags = self._merge_json_text_list(existing.tags, tags)
            existing.relations = self._merge_relation_payload(existing.relations, relationship_entries)
            if existing.relations and not existing.relationship_network:
                existing.relationship_network = existing.relations
            return existing

        character = Character(
            project_id=project.id,
            name=canonical_name,
            role=role,
            role_position=role_position or None,
            faction=faction or None,
            summary=summary or None,
            profile=profile or None,
            importance_level=importance_level,
            appearance_status="已出场",
            life_status="存活",
            first_appearance_chapter=first_appearance,
            tags=json.dumps(tags, ensure_ascii=False) if tags else None,
            relations=json.dumps(relationship_entries, ensure_ascii=False) if relationship_entries else None,
            relationship_network=json.dumps(relationship_entries, ensure_ascii=False) if relationship_entries else None,
        )
        self.db.add(character)
        imported_by_key[canonical_name] = character
        return character

    def _ensure_setting_collection(
        self,
        project_id: int,
        name: str,
        category: str,
        description: str,
        order: int,
        max_depth: int,
        hierarchy_config: Optional[str] = None,
    ) -> tuple[SettingCollection, bool]:
        """获取或创建指定分类的设定集合。"""
        collection = self.db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == category,
        ).first()
        if collection:
            if not collection.name:
                collection.name = name
            if not collection.description:
                collection.description = description
            if not collection.max_depth:
                collection.max_depth = max_depth
            if hierarchy_config and not collection.hierarchy_config:
                collection.hierarchy_config = hierarchy_config
            return collection, False

        collection = SettingCollection(
            project_id=project_id,
            name=name,
            category=category,
            description=description,
            order=order,
            max_depth=max_depth,
            hierarchy_config=hierarchy_config,
        )
        self.db.add(collection)
        self.db.flush()
        return collection, True

    def _upsert_standard_setting_item(
        self,
        collection: SettingCollection,
        name: str,
        content: str,
        order: int,
        *,
        level: Optional[int] = None,
        tags: Optional[List[str]] = None,
        summary: Optional[str] = None,
        depth: int = 2,
        node_type: str = "detail",
        is_leaf: bool = True,
        path: Optional[str] = None,
    ) -> SettingItem:
        """向标准集合中新增或更新设定项，避免重复导入同名条目。"""
        normalized_name = self._normalize_setting_link_name(name)
        if not normalized_name:
            raise ValueError("标准设定项名称不能为空")

        existing_items = self.db.query(SettingItem).filter(
            SettingItem.collection_id == collection.id
        ).all()
        existing = next(
            (
                item for item in existing_items
                if self._normalize_setting_link_name(item.name) == normalized_name
            ),
            None,
        )

        tags_payload = json.dumps(tags, ensure_ascii=False) if tags else None
        target_path = path or f"{collection.name}/{name}"
        if existing:
            existing.content = self._prefer_longer_text(existing.content, content)
            if summary:
                existing.summary = self._prefer_longer_text(existing.summary, summary)
            if tags:
                existing.tags = self._merge_json_text_list(existing.tags, tags)
            if level is not None and existing.level is None:
                existing.level = level
            if not existing.path:
                existing.path = target_path
            if not existing.node_type:
                existing.node_type = node_type
            if existing.is_leaf is None:
                existing.is_leaf = is_leaf
            if not existing.depth:
                existing.depth = depth
            return existing

        item = SettingItem(
            collection_id=collection.id,
            name=name,
            level=level,
            tags=tags_payload,
            content=content,
            order=order,
            depth=depth,
            node_type=node_type,
            is_leaf=is_leaf,
            path=target_path,
            summary=summary,
        )
        self.db.add(item)
        return item

    def _build_worldview_location_item_payload(self, raw_location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将 worldview 中的地点条目转换为标准地图项。"""
        if not isinstance(raw_location, dict):
            return None

        name = self._stringify_import_value(raw_location.get("name"))
        if not name:
            return None

        location_type = self._stringify_import_value(raw_location.get("type"))
        description = self._stringify_import_value(raw_location.get("description"))
        importance = self._stringify_import_value(raw_location.get("importance"))
        appearance_count = raw_location.get("appearance_count")

        lines: List[str] = []
        if location_type:
            lines.append(f"类型: {location_type}")
        if importance:
            lines.append(f"重要性: {importance}")
        if appearance_count not in (None, ""):
            lines.append(f"出现次数: {appearance_count}")
        if description:
            lines.append(description)

        tags = [value for value in [location_type, importance] if value]
        return {
            "name": name,
            "content": "\n".join(lines).strip() or description or name,
            "summary": description or None,
            "tags": tags,
        }

    def _build_worldview_faction_item_payload(self, raw_faction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将 worldview 中的势力条目转换为标准势力项。"""
        if not isinstance(raw_faction, dict):
            return None

        name = self._stringify_import_value(raw_faction.get("name"))
        if not name:
            return None

        faction_type = self._stringify_import_value(raw_faction.get("type"))
        description = self._stringify_import_value(raw_faction.get("description"))
        members = raw_faction.get("members") or []
        member_text = self._stringify_import_value(members)

        lines: List[str] = []
        if faction_type:
            lines.append(f"类型: {faction_type}")
        if member_text:
            lines.append(f"成员: {member_text}")
        if description:
            lines.append(description)

        tags = [value for value in [faction_type] if value]
        return {
            "name": name,
            "content": "\n".join(lines).strip() or description or name,
            "summary": description or None,
            "tags": tags,
        }

    def _sync_worldview_assets_to_standard_collections(
        self,
        project: Project,
        analysis: BookAnalysis,
        start_order: int,
    ) -> int:
        """把 worldview 中的地点/势力同步投影到标准集合。"""
        content = self._load_analysis_payload(analysis, log_context="世界观分析")

        if not isinstance(content, dict) or not content:
            return 0

        created_collections = 0
        next_order = start_order

        locations = content.get("locations", [])[:10]
        if locations:
            map_collection, created = self._ensure_setting_collection(
                project_id=project.id,
                name="地图体系",
                category="map_system",
                description="拆书导入后同步生成的标准地点集合，便于后续创作检索与挂接。",
                order=next_order,
                max_depth=4,
                hierarchy_config=get_hierarchy_config_json("map_system"),
            )
            if created:
                created_collections += 1
                next_order += 1

            existing_map_items = self.db.query(SettingItem).filter(
                SettingItem.collection_id == map_collection.id
            ).all()
            next_item_order = max(
                [item.order for item in existing_map_items if item.order is not None],
                default=-1,
            ) + 1
            for raw_location in locations:
                payload = self._build_worldview_location_item_payload(raw_location)
                if not payload:
                    continue
                self._upsert_standard_setting_item(
                    collection=map_collection,
                    name=payload["name"],
                    content=payload["content"],
                    order=next_item_order,
                    tags=payload["tags"],
                    summary=payload["summary"],
                    depth=2,
                    node_type="detail",
                    is_leaf=True,
                    path=f"{map_collection.name}/{payload['name']}",
                )
                next_item_order += 1

        factions = content.get("factions", [])[:10]
        if factions:
            force_collection, created = self._ensure_setting_collection(
                project_id=project.id,
                name="组织势力体系",
                category="organization_force_system",
                description="拆书导入后同步生成的标准势力集合，便于人物挂接与后续创作复用。",
                order=next_order,
                max_depth=2,
                hierarchy_config=get_hierarchy_config_json("organization_force_system"),
            )
            if created:
                created_collections += 1
                next_order += 1

            existing_force_items = self.db.query(SettingItem).filter(
                SettingItem.collection_id == force_collection.id
            ).all()
            next_item_order = max(
                [item.order for item in existing_force_items if item.order is not None],
                default=-1,
            ) + 1
            for raw_faction in factions:
                payload = self._build_worldview_faction_item_payload(raw_faction)
                if not payload:
                    continue
                self._upsert_standard_setting_item(
                    collection=force_collection,
                    name=payload["name"],
                    content=payload["content"],
                    order=next_item_order,
                    tags=payload["tags"],
                    summary=payload["summary"],
                    depth=1,
                    node_type="detail",
                    is_leaf=True,
                    path=f"{force_collection.name}/{payload['name']}",
                )
                next_item_order += 1

        if created_collections or locations or factions:
            self.db.flush()
            logger.info(
                "  → 已同步 worldview 资产到标准集合: 创建集合 %s 个, 地点 %s 项, 势力 %s 项",
                created_collections,
                len(locations),
                len(factions),
            )

        return created_collections

    @staticmethod
    def _build_character_system_role_label(character: Character) -> str:
        """将人物档案映射为角色体系中的角色定位标签。"""
        role_position = ProjectBridge._normalize_role_position_value(getattr(character, "role_position", None))
        if role_position:
            return role_position

        story_stance = ProjectBridge._normalize_story_stance_value(character.role)
        importance = str(character.importance_level or "").strip()
        if story_stance == "主角方":
            if "主角" in importance:
                return "主角"
            return "盟友"
        if story_stance == "反派方":
            return "对手"
        if story_stance == "中立方":
            return "中立角色"
        if story_stance == "亦正亦邪":
            return "摇摆角色"

        if "主角" in importance:
            return "主角"
        if "重要" in importance or "核心" in importance:
            return "主线角色"
        if any(keyword in importance for keyword in ("次要", "边缘", "群众")):
            return "功能角色"
        return "功能角色"

    def _build_character_setting_relations(
        self,
        character: Character,
        items_by_id: Dict[int, SettingItem],
    ) -> Optional[str]:
        """构建角色体系条目的关联摘要。"""
        relations: List[Dict[str, Any]] = []

        faction_name = str(character.faction or "").strip()
        if faction_name:
            relations.append(
                {
                    "type": "faction",
                    "target": faction_name,
                    "setting_item_id": character.faction_item_id,
                }
            )

        location_ids = self._decode_json_field(character.related_locations_json, [])
        if isinstance(location_ids, list):
            for item_id in location_ids:
                try:
                    numeric_id = int(item_id)
                except (TypeError, ValueError):
                    continue
                location_item = items_by_id.get(numeric_id)
                if not location_item:
                    continue
                relations.append(
                    {
                        "type": "location",
                        "target": str(location_item.name or "").strip(),
                        "setting_item_id": numeric_id,
                    }
                )

        raw_relations = self._decode_json_field(character.relations, [])
        if isinstance(raw_relations, list):
            for relation in raw_relations:
                if not isinstance(relation, dict):
                    continue
                target = self._stringify_import_value(relation.get("target"))
                if not target:
                    continue
                payload = {
                    "type": self._stringify_import_value(relation.get("type")) or "character",
                    "target": target,
                }
                description = self._stringify_import_value(relation.get("description"))
                if description:
                    payload["description"] = description
                relations.append(payload)

        deduplicated: List[Dict[str, Any]] = []
        seen = set()
        for relation in relations:
            key = (
                relation.get("type"),
                relation.get("target"),
                relation.get("setting_item_id"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(relation)

        return json.dumps(deduplicated, ensure_ascii=False) if deduplicated else None

    def _build_character_setting_item_content(
        self,
        character: Character,
        items_by_id: Dict[int, SettingItem],
    ) -> str:
        """生成角色体系条目的正文，便于直接用于创作参考。"""
        lines: List[str] = []

        story_stance = self._normalize_story_stance_value(character.role)
        role_label = self._build_character_system_role_label(character)
        if story_stance:
            lines.append(f"故事立场: {story_stance}")
        if role_label:
            lines.append(f"角色定位: {role_label}")

        importance = str(character.importance_level or "").strip()
        if importance:
            lines.append(f"重要程度: {importance}")

        faction = str(character.faction or "").strip()
        if faction:
            lines.append(f"所属势力: {faction}")

        first_appearance = getattr(character, "first_appearance_chapter", None)
        if isinstance(first_appearance, int):
            lines.append(f"首次出场: 第{first_appearance}章")

        location_names: List[str] = []
        location_ids = self._decode_json_field(character.related_locations_json, [])
        if isinstance(location_ids, list):
            for item_id in location_ids:
                try:
                    numeric_id = int(item_id)
                except (TypeError, ValueError):
                    continue
                location_item = items_by_id.get(numeric_id)
                location_name = str(getattr(location_item, "name", "") or "").strip()
                if location_name and location_name not in location_names:
                    location_names.append(location_name)
        if location_names:
            lines.append(f"关键地点: {'、'.join(location_names)}")

        summary = str(character.summary or "").strip()
        if summary:
            lines.append(f"人物摘要: {summary}")

        profile = str(character.profile or "").strip()
        if profile:
            lines.append(profile)

        return "\n".join(line for line in lines if line).strip()

    def _build_character_setting_item_tags(self, character: Character) -> List[str]:
        """提取角色体系条目的标签。"""
        tags: List[str] = []

        role_label = self._build_character_system_role_label(character)
        if role_label and role_label not in tags:
            tags.append(role_label)

        story_stance = self._normalize_story_stance_value(character.role)
        if story_stance and story_stance not in tags:
            tags.append(story_stance)

        importance = str(character.importance_level or "").strip()
        if importance and importance not in tags:
            tags.append(importance)

        faction = str(character.faction or "").strip()
        if faction:
            faction_tag = f"势力:{faction}"
            if faction_tag not in tags:
                tags.append(faction_tag)

        raw_tags = self._decode_json_field(character.tags, [])
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                text = str(tag or "").strip()
                if text and text not in tags:
                    tags.append(text)

        return tags[:12]

    def _sync_imported_characters_to_standard_collection(self, project_id: int) -> Dict[str, int]:
        """将导入人物同步到标准角色体系集合。"""
        characters = self.db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        if not characters:
            return {"collection_created": 0, "items_synced": 0}

        collection_count = self.db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).count()
        character_collection, created = self._ensure_setting_collection(
            project_id=project_id,
            name="角色体系",
            category="character_system",
            description="拆书导入后同步生成的标准角色集合，便于人物检索、设定复用与创作参考。",
            order=collection_count,
            max_depth=4,
            hierarchy_config=get_hierarchy_config_json("character_system"),
        )

        all_setting_items = self.db.query(SettingItem).all()
        items_by_id = {
            item.id: item
            for item in all_setting_items
            if getattr(item, "id", None) is not None
        }
        existing_items = self.db.query(SettingItem).filter(
            SettingItem.collection_id == character_collection.id
        ).all()
        next_item_order = max(
            [item.order for item in existing_items if item.order is not None],
            default=-1,
        ) + 1

        synced_count = 0
        for character in characters:
            name = str(character.name or "").strip()
            if not name:
                continue

            role_label = self._build_character_system_role_label(character)
            content = self._build_character_setting_item_content(character, items_by_id)
            tags = self._build_character_setting_item_tags(character)
            item = self._upsert_standard_setting_item(
                collection=character_collection,
                name=name,
                content=content or name,
                order=next_item_order,
                tags=tags,
                summary=str(character.summary or "").strip() or None,
                depth=3,
                node_type="detail",
                is_leaf=True,
                path=f"{character_collection.name}/{role_label}/{name}",
            )
            item.related_characters = self._merge_json_int_list(item.related_characters, [character.id])
            item.relations = self._build_character_setting_relations(character, items_by_id)
            synced_count += 1
            next_item_order += 1

        self.db.flush()
        logger.info(
            "  → 已同步导入人物到标准角色体系: 创建集合 %s 个, 同步人物 %s 个",
            1 if created else 0,
            synced_count,
        )
        return {
            "collection_created": 1 if created else 0,
            "items_synced": synced_count,
        }
