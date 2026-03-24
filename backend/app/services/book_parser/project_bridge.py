"""
项目桥接服务

将拆书分析结果转换为工作流项目
"""
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
from app.services.setting_templates import get_hierarchy_config_json
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


class ProjectBridge:
    """
    项目桥接器
    
    将拆书分析结果转换为工作流项目，包括：
    - 创建项目
    - 导入设定（人物、世界观）
    - 导入章节（可选）
    """
    
    # 设定类型映射
    ANALYSIS_TO_COLLECTION = {
        'characters': '人物设定',
        'worldview': '世界观设定',
        'plot': '情节脉络',
        'concepts': '关键概念',
        'style': '写作风格参考',
    }
    STRUCTURED_MEMORY_LIMITS = {
        "global_story_arcs": 10,
        "character_states": 14,
        "relationship_edges": 12,
        "pending_foreshadowings": 12,
        "world_rules_hard_constraints": 10,
    }
    
    def __init__(self, db: Session):
        self.db = db

    def _allocate_next_display_no(self, *, user_id: int) -> int:
        self.db.execute(
            select(User.id)
            .where(User.id == user_id)
            .with_for_update()
        ).scalar_one()

        current_max = (
            self.db.query(func.max(Project.display_no))
            .filter(Project.user_id == user_id)
            .scalar()
        )
        return int(current_max or 0) + 1
    
    def import_to_project(
        self,
        book_id: int,
        user_id: int,
        project_title: Optional[str] = None,
        import_settings: bool = True,
        import_characters: bool = True,
        import_chapters: bool = False,
        start_from_chapter: Optional[int] = None,
    ) -> Project:
        """
        将书籍导入为工作流项目
        
        Args:
            book_id: 书籍ID
            user_id: 用户ID
            project_title: 项目标题（默认使用书名）
            import_settings: 是否导入设定
            import_characters: 是否导入人物
            import_chapters: 是否导入章节内容
            start_from_chapter: 从第几章开始导入
            
        Returns:
            创建的项目
        """
        # 获取书籍
        book = self.db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            raise ValueError(f"书籍不存在: {book_id}")
        
        # 创建项目
        project = Project(
            display_no=self._allocate_next_display_no(user_id=user_id),
            user_id=user_id,
            title=project_title or f"{book.title}（续写）",
            description=f"基于《{book.title}》的创作项目",
            genre=book.genre,
            status="draft",
        )
        self.db.add(project)
        self.db.flush()  # 获取project.id
        
        logger.info(f"✅ 创建项目: {project.title} (ID: {project.id})")
        
        # 获取分析结果
        analyses = self.db.query(BookAnalysis).filter(
            BookAnalysis.book_id == book_id
        ).all()
        
        analysis_map = {a.analysis_type: a for a in analyses}
        
        # 导入人物设定
        if import_characters and 'characters' in analysis_map:
            self._import_characters(project, analysis_map['characters'])
        
        # 导入设定
        if import_settings:
            self._import_settings(project, analysis_map)
        
        # 导入章节
        if import_chapters:
            self._import_chapters(project, book_id, start_from_chapter)

        if import_characters:
            self._link_imported_characters_to_settings(
                project_id=project.id,
                analysis_map=analysis_map,
            )
            self._sync_imported_characters_to_standard_collection(project.id)
        
        # 更新书籍关联
        book.imported_project_id = project.id
        
        # 🆕 初始化 project_settings 记录，填充工作流阶段内容
        self._init_project_settings(project, analysis_map, book)
        
        self.db.commit()
        
        logger.info(f"✅ 项目导入完成: {project.title}")
        
        return project
    
    def _import_characters(self, project: Project, analysis: BookAnalysis):
        """
        导入人物设定
        """
        content = self._load_analysis_payload(analysis, log_context="人物分析")
        if not isinstance(content, dict) or not content:
            logger.warning("人物分析结果格式无效，跳过人物导入")
            return

        mention_map = self._collect_book_parser_character_mentions(analysis.book_id)
        relationship_lookup = self._build_import_character_relationship_lookup(
            content.get('character_relationships') or []
        )

        imported_by_key: Dict[str, Character] = {}
        main_characters = content.get('main_characters', []) or []
        supporting_characters = content.get('supporting_characters', []) or []

        for char_data in main_characters:
            self._upsert_import_character(
                project=project,
                imported_by_key=imported_by_key,
                char_data=char_data,
                mention_map=mention_map,
                relationship_lookup=relationship_lookup,
                default_role='protagonist',
                default_importance='重要角色',
            )

        for char_data in supporting_characters:
            self._upsert_import_character(
                project=project,
                imported_by_key=imported_by_key,
                char_data=char_data,
                mention_map=mention_map,
                relationship_lookup=relationship_lookup,
                default_role='supporting',
                default_importance='次要角色',
            )

        missing_character_keys = set(mention_map.keys()) | set(relationship_lookup.keys())
        for relation_entries in relationship_lookup.values():
            for relation in relation_entries:
                target = self._normalize_import_character_name(relation.get("target"))
                if target:
                    missing_character_keys.add(target)

        auto_created = 0
        sorted_missing_keys = sorted(
            [key for key in missing_character_keys if key and key not in imported_by_key],
            key=lambda key: (
                0 if relationship_lookup.get(key) else 1,
                -(mention_map.get(key, {}).get("count") or 0),
                mention_map.get(key, {}).get("first_appearance_chapter") or 10**9,
                key,
            ),
        )
        for key in sorted_missing_keys[:12]:
            mention_info = mention_map.get(key, {})
            created = self._upsert_import_character(
                project=project,
                imported_by_key=imported_by_key,
                char_data={"name": mention_info.get("name") or key},
                mention_map=mention_map,
                relationship_lookup=relationship_lookup,
                default_role='supporting',
                default_importance='次要角色',
                is_backfilled=True,
            )
            if created is not None:
                auto_created += 1

        logger.info(
            f"  → 导入 {len(main_characters)} 个主要人物, {len(supporting_characters)} 个配角, "
            f"自动补建 {auto_created} 个章节人物卡"
        )

    @staticmethod
    def _normalize_import_character_name(name: Any) -> str:
        """统一人物名格式，避免“林澈（队长）”被当成新人物。"""
        text = str(name or "").strip()
        if not text:
            return ""

        try:
            from app.services.character_parser import normalize_character_name

            normalized = normalize_character_name(text)
        except Exception:
            normalized = text

        return normalized or text

    @staticmethod
    def _stringify_import_value(value: Any) -> str:
        """将导入字段转成便于展示的文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    def _collect_book_parser_character_mentions(self, book_id: Optional[int]) -> Dict[str, Dict[str, Any]]:
        """汇总拆书章节中出现过的人物及首次出场信息。"""
        if not book_id:
            return {}

        mentions: Dict[str, Dict[str, Any]] = {}
        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

        for chapter in book_chapters:
            appearing_characters = self._decode_json_field(chapter.appearing_characters, [])
            if not isinstance(appearing_characters, list):
                continue

            seen_in_chapter = set()
            for raw_name in appearing_characters:
                display_name = str(raw_name or "").strip()
                normalized_name = self._normalize_import_character_name(display_name)
                if not normalized_name or normalized_name in seen_in_chapter:
                    continue

                seen_in_chapter.add(normalized_name)
                entry = mentions.setdefault(
                    normalized_name,
                    {
                        "name": normalized_name,
                        "aliases": [],
                        "count": 0,
                        "first_appearance_chapter": None,
                    },
                )
                entry["count"] += 1

                if display_name and display_name != normalized_name and display_name not in entry["aliases"]:
                    entry["aliases"].append(display_name)

                chapter_number = getattr(chapter, "chapter_number", None)
                current_first = entry.get("first_appearance_chapter")
                if isinstance(chapter_number, int) and (
                    current_first is None or chapter_number < current_first
                ):
                    entry["first_appearance_chapter"] = chapter_number

        return mentions

    def _build_import_character_relationship_lookup(
        self,
        character_relationships: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, str]]]:
        """把拆书人物关系转成按人物聚合的双向关系映射。"""
        lookup: Dict[str, List[Dict[str, str]]] = {}

        for relation in character_relationships:
            if not isinstance(relation, dict):
                continue

            char_a = self._normalize_import_character_name(relation.get("character1"))
            char_b = self._normalize_import_character_name(relation.get("character2"))
            if not char_a or not char_b or char_a == char_b:
                continue

            relation_type = self._stringify_import_value(relation.get("relationship")) or "关联"
            description = self._stringify_import_value(relation.get("description"))

            for source, target in ((char_a, char_b), (char_b, char_a)):
                payload = {"target": target, "type": relation_type}
                if description and description != relation_type:
                    payload["description"] = description

                bucket = lookup.setdefault(source, [])
                if any(
                    item.get("target") == payload["target"] and item.get("type") == payload["type"]
                    for item in bucket
                ):
                    continue
                bucket.append(payload)

        return lookup

    def _collect_import_character_aliases(
        self,
        char_data: Dict[str, Any],
        mention_info: Dict[str, Any],
        canonical_name: str,
    ) -> List[str]:
        """汇总人物别名/称呼。"""
        aliases: List[str] = []

        for raw_alias in char_data.get("aliases") or []:
            alias = str(raw_alias or "").strip()
            if alias and alias != canonical_name and alias not in aliases:
                aliases.append(alias)

        for raw_alias in mention_info.get("aliases") or []:
            alias = str(raw_alias or "").strip()
            if alias and alias != canonical_name and alias not in aliases:
                aliases.append(alias)

        return aliases

    def _build_import_character_summary(
        self,
        name: str,
        char_data: Dict[str, Any],
        mention_info: Dict[str, Any],
        is_backfilled: bool,
    ) -> str:
        """生成导入人物的摘要文本。"""
        description = self._stringify_import_value(char_data.get("description"))
        if description:
            return description

        relation_to_main = self._stringify_import_value(char_data.get("relationship_to_main"))
        if relation_to_main:
            return relation_to_main

        first_chapter = mention_info.get("first_appearance_chapter")
        if is_backfilled:
            if first_chapter:
                return f"拆书章节识别出的出场人物，首次出现于第{first_chapter}章。"
            return "拆书章节识别出的出场人物，待补充完整人物卡。"

        return f"{name}的人物卡待补充。"

    def _build_import_character_profile(
        self,
        char_data: Dict[str, Any],
        mention_info: Dict[str, Any],
        relationship_entries: List[Dict[str, str]],
        canonical_name: str,
        is_backfilled: bool,
    ) -> str:
        """把拆书人物分析整理成更适合创作复用的人物档案。"""
        aliases = self._collect_import_character_aliases(char_data, mention_info, canonical_name)
        parts: List[str] = []

        if aliases:
            parts.append(f"别名/称呼: {'、'.join(aliases)}")

        field_pairs = [
            ("简介", char_data.get("description")),
            ("故事立场", None if self._stringify_import_value(char_data.get("story_stance")) == "未提及" else char_data.get("story_stance")),
            ("所属势力", None if self._stringify_import_value(char_data.get("faction")) == "未提及" else char_data.get("faction")),
            ("与主角关系", char_data.get("relationship_to_main")),
            ("性格", char_data.get("personality")),
            ("能力", char_data.get("abilities")),
            ("背景", char_data.get("background") or char_data.get("backstory")),
            ("核心动机", char_data.get("motivation") or char_data.get("goal")),
            ("成长线", char_data.get("arc") or char_data.get("growth")),
        ]
        for label, raw_value in field_pairs:
            text_value = self._stringify_import_value(raw_value)
            if text_value:
                parts.append(f"{label}: {text_value}")

        first_chapter = mention_info.get("first_appearance_chapter") or char_data.get("first_appearance_chapter")
        if first_chapter:
            parts.append(f"首次出场: 第{first_chapter}章")

        appearance_count = mention_info.get("count")
        if appearance_count:
            parts.append(f"拆书识别出场次数: {appearance_count}")

        if relationship_entries:
            relation_text = []
            for relation in relationship_entries:
                target = self._stringify_import_value(relation.get("target"))
                relation_type = self._stringify_import_value(relation.get("type")) or "关联"
                description = self._stringify_import_value(relation.get("description"))
                if target and description:
                    relation_text.append(f"{target}（{relation_type}）: {description}")
                elif target:
                    relation_text.append(f"{target}（{relation_type}）")
            if relation_text:
                parts.append("关键关系: " + "；".join(relation_text))

        if is_backfilled and not parts:
            parts.append("拆书章节中识别出的出场人物，待补充完整人物卡。")

        return "\n".join(parts)

    def _build_import_character_tags(
        self,
        char_data: Dict[str, Any],
        mention_info: Dict[str, Any],
        canonical_name: str,
    ) -> List[str]:
        """提取便于检索和展示的标签。"""
        tags: List[str] = []

        raw_personality = char_data.get("personality")
        if isinstance(raw_personality, list):
            for item in raw_personality:
                value = str(item or "").strip()
                if value and value not in tags:
                    tags.append(value)

        for alias in self._collect_import_character_aliases(char_data, mention_info, canonical_name):
            alias_tag = f"别名:{alias}"
            if alias_tag not in tags:
                tags.append(alias_tag)

        return tags[:8]

    @staticmethod
    def _merge_json_text_list(existing_raw: Optional[str], new_values: List[str]) -> Optional[str]:
        """合并 JSON 字符串列表。"""
        values: List[str] = []

        if existing_raw:
            try:
                existing_values = json.loads(existing_raw)
            except Exception:
                existing_values = []
            if isinstance(existing_values, list):
                values.extend(str(item).strip() for item in existing_values if str(item).strip())

        for value in new_values:
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)

        return json.dumps(values, ensure_ascii=False) if values else None

    @staticmethod
    def _merge_relation_payload(
        existing_raw: Optional[str],
        new_relations: List[Dict[str, str]],
    ) -> Optional[str]:
        """合并人物关系 JSON。"""
        merged: List[Dict[str, str]] = []

        if existing_raw:
            try:
                existing_relations = json.loads(existing_raw)
            except Exception:
                existing_relations = []
            if isinstance(existing_relations, list):
                for relation in existing_relations:
                    if isinstance(relation, dict):
                        merged.append(dict(relation))

        for relation in new_relations:
            if not isinstance(relation, dict):
                continue
            target = str(relation.get("target") or "").strip()
            relation_type = str(relation.get("type") or "").strip()
            if not target or not relation_type:
                continue
            if any(
                item.get("target") == target and item.get("type") == relation_type
                for item in merged
            ):
                continue
            merged.append(dict(relation))

        return json.dumps(merged, ensure_ascii=False) if merged else None

    @staticmethod
    def _prefer_longer_text(current: Optional[str], incoming: str) -> str:
        """优先保留信息量更高的文本。"""
        current_value = str(current or "").strip()
        incoming_value = str(incoming or "").strip()
        if not current_value:
            return incoming_value
        if len(incoming_value) > len(current_value):
            return incoming_value
        return current_value

    @staticmethod
    def _merge_json_int_list(existing_raw: Optional[str], new_values: List[int]) -> Optional[str]:
        """合并 JSON 整数列表。"""
        values: List[int] = []

        if existing_raw:
            try:
                existing_values = json.loads(existing_raw)
            except Exception:
                existing_values = []
            if isinstance(existing_values, list):
                for item in existing_values:
                    try:
                        numeric = int(item)
                    except (TypeError, ValueError):
                        continue
                    if numeric not in values:
                        values.append(numeric)

        for value in new_values:
            try:
                numeric = int(value)
            except (TypeError, ValueError):
                continue
            if numeric not in values:
                values.append(numeric)

        return json.dumps(values, ensure_ascii=False) if values else None

    @staticmethod
    def _normalize_setting_link_name(name: Any) -> str:
        """统一设定项名称，提升导入后挂接命中率。"""
        text = str(name or "").strip()
        if not text:
            return ""

        text = text.strip("\"'“”‘’《》〈〉「」『』【】[]")
        text = re.sub(r"[（(][^（）()]{0,30}[）)]", "", text)
        text = re.sub(r"\s+", "", text)
        return text.lower().strip()

    def _match_setting_item_by_name(
        self,
        target_name: Any,
        items: List[SettingItem],
    ) -> Optional[SettingItem]:
        """按优先级匹配设定项，支持轻量归一化和包含匹配。"""
        raw_target = str(target_name or "").strip()
        normalized_target = self._normalize_setting_link_name(raw_target)
        if not raw_target or not normalized_target:
            return None

        for item in items:
            if str(item.name or "").strip() == raw_target:
                return item

        normalized_exact_matches: List[SettingItem] = []
        fuzzy_matches: List[tuple[int, SettingItem]] = []
        for item in items:
            normalized_item_name = self._normalize_setting_link_name(item.name)
            if not normalized_item_name:
                continue
            if normalized_item_name == normalized_target:
                normalized_exact_matches.append(item)
                continue
            if len(normalized_target) >= 2 and (
                normalized_target in normalized_item_name
                or normalized_item_name in normalized_target
            ):
                fuzzy_matches.append(
                    (abs(len(normalized_item_name) - len(normalized_target)), item)
                )

        if normalized_exact_matches:
            return normalized_exact_matches[0]
        if fuzzy_matches:
            fuzzy_matches.sort(key=lambda pair: pair[0])
            return fuzzy_matches[0][1]
        return None

    def _sync_setting_item_related_character(self, item: Optional[SettingItem], character_id: Optional[int]) -> bool:
        """回填设定项的 related_characters 字段。"""
        if item is None or character_id is None:
            return False

        merged = self._merge_json_int_list(item.related_characters, [character_id])
        if merged == item.related_characters:
            return False
        item.related_characters = merged
        return True

    def _extract_character_related_location_ids(
        self,
        character: Character,
        location_items: List[SettingItem],
    ) -> List[int]:
        """从人物卡文本中提取已知地点引用。"""
        text_parts = [
            str(character.summary or "").strip(),
            str(character.profile or "").strip(),
            str(character.faction or "").strip(),
        ]
        text_blob = "\n".join(part for part in text_parts if part)
        normalized_blob = self._normalize_setting_link_name(text_blob)
        if not text_blob or not normalized_blob:
            return []

        matched_ids: List[int] = []
        matched_keys = set()
        candidates = sorted(
            location_items,
            key=lambda item: len(self._normalize_setting_link_name(item.name)),
            reverse=True,
        )
        for item in candidates:
            item_id = getattr(item, "id", None)
            normalized_name = self._normalize_setting_link_name(item.name)
            raw_name = str(item.name or "").strip()
            if item_id is None or not normalized_name or normalized_name in matched_keys:
                continue
            if raw_name and raw_name in text_blob:
                matched_ids.append(item_id)
                matched_keys.add(normalized_name)
                continue
            if len(normalized_name) >= 2 and normalized_name in normalized_blob:
                matched_ids.append(item_id)
                matched_keys.add(normalized_name)

        return matched_ids

    def _link_imported_characters_to_settings(
        self,
        project_id: int,
        analysis_map: Optional[Dict[str, BookAnalysis]] = None,
    ) -> Dict[str, int]:
        """将导入人物与势力/地点设定项挂接，便于后续创作复用。"""
        self.db.flush()

        characters = self.db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        if not characters:
            return {"factions": 0, "locations": 0, "backlinks": 0}

        collections = self.db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).all()
        if not collections:
            return {"factions": 0, "locations": 0, "backlinks": 0}

        collection_ids = [collection.id for collection in collections if collection.id is not None]
        if not collection_ids:
            return {"factions": 0, "locations": 0, "backlinks": 0}

        items = self.db.query(SettingItem).filter(
            SettingItem.collection_id.in_(collection_ids)
        ).all()
        items_by_collection_id: Dict[int, List[SettingItem]] = {}
        for item in items:
            items_by_collection_id.setdefault(item.collection_id, []).append(item)

        collections_by_category: Dict[str, List[SettingCollection]] = {}
        for collection in collections:
            if not collection.category:
                continue
            collections_by_category.setdefault(collection.category, []).append(collection)

        worldview_content = self._load_analysis_content(analysis_map or {}, "worldview")
        worldview_location_names = {
            self._normalize_setting_link_name(location.get("name"))
            for location in (worldview_content.get("locations") or [])
            if isinstance(location, dict) and self._normalize_setting_link_name(location.get("name"))
        }
        worldview_faction_names = {
            self._normalize_setting_link_name(faction.get("name"))
            for faction in (worldview_content.get("factions") or [])
            if isinstance(faction, dict) and self._normalize_setting_link_name(faction.get("name"))
        }

        faction_items: List[SettingItem] = []
        seen_faction_names = set()
        for category in ("organization_force_system",):
            for collection in collections_by_category.get(category, []):
                for item in items_by_collection_id.get(collection.id, []):
                    normalized_name = self._normalize_setting_link_name(item.name)
                    if not normalized_name or normalized_name in seen_faction_names:
                        continue
                    faction_items.append(item)
                    seen_faction_names.add(normalized_name)
        for collection in collections_by_category.get("worldview", []):
            for item in items_by_collection_id.get(collection.id, []):
                normalized_name = self._normalize_setting_link_name(item.name)
                if (
                    not normalized_name
                    or normalized_name not in worldview_faction_names
                    or normalized_name in seen_faction_names
                ):
                    continue
                faction_items.append(item)
                seen_faction_names.add(normalized_name)

        location_items: List[SettingItem] = []
        seen_location_names = set()
        for category in ("map_system",):
            for collection in collections_by_category.get(category, []):
                for item in items_by_collection_id.get(collection.id, []):
                    normalized_name = self._normalize_setting_link_name(item.name)
                    if not normalized_name or normalized_name in seen_location_names:
                        continue
                    location_items.append(item)
                    seen_location_names.add(normalized_name)
        for collection in collections_by_category.get("worldview", []):
            for item in items_by_collection_id.get(collection.id, []):
                normalized_name = self._normalize_setting_link_name(item.name)
                if (
                    not normalized_name
                    or normalized_name not in worldview_location_names
                    or normalized_name in seen_location_names
                ):
                    continue
                location_items.append(item)
                seen_location_names.add(normalized_name)

        location_items_by_id = {
            item.id: item
            for item in location_items
            if getattr(item, "id", None) is not None
        }

        faction_links = 0
        location_links = 0
        backlink_updates = 0

        for character in characters:
            if character.faction:
                faction_item = None
                if character.faction_item_id:
                    faction_item = next(
                        (item for item in faction_items if item.id == character.faction_item_id),
                        None,
                    )
                if faction_item is None:
                    faction_item = self._match_setting_item_by_name(character.faction, faction_items)
                    if faction_item and character.faction_item_id != faction_item.id:
                        character.faction_item_id = faction_item.id
                        faction_links += 1
                if self._sync_setting_item_related_character(faction_item, character.id):
                    backlink_updates += 1

            related_location_ids = self._extract_character_related_location_ids(
                character=character,
                location_items=location_items,
            )
            if related_location_ids:
                existing_location_ids = self._decode_json_field(character.related_locations_json, [])
                if not isinstance(existing_location_ids, list):
                    existing_location_ids = []
                existing_location_ids = [
                    int(item)
                    for item in existing_location_ids
                    if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
                ]
                new_location_ids = [
                    item_id for item_id in related_location_ids if item_id not in existing_location_ids
                ]
                if new_location_ids:
                    character.related_locations_json = self._merge_json_int_list(
                        character.related_locations_json,
                        new_location_ids,
                    )
                    location_links += len(new_location_ids)

            synced_location_ids = self._decode_json_field(character.related_locations_json, [])
            if not isinstance(synced_location_ids, list):
                synced_location_ids = []
            for item_id in synced_location_ids:
                try:
                    location_item = location_items_by_id.get(int(item_id))
                except (TypeError, ValueError):
                    location_item = None
                if self._sync_setting_item_related_character(location_item, character.id):
                    backlink_updates += 1

        logger.info(
            "  → 导入人物-设定挂接完成: 势力 %s 个, 地点 %s 个, 反向回填 %s 个",
            faction_links,
            location_links,
            backlink_updates,
        )
        return {
            "factions": faction_links,
            "locations": location_links,
            "backlinks": backlink_updates,
        }

    def _resolve_importance_level(
        self,
        char_data: Dict[str, Any],
        default_importance: str,
    ) -> str:
        """确定导入人物的重要程度。"""
        explicit_value = self._stringify_import_value(char_data.get("importance_level"))
        if explicit_value:
            return explicit_value

        role = str(char_data.get("role") or "").strip().lower()
        if role == "protagonist":
            return "主角"
        if role in {"antagonist", "deuteragonist"}:
            return "重要角色"
        return default_importance

    def _upsert_import_character(
        self,
        project: Project,
        imported_by_key: Dict[str, Character],
        char_data: Dict[str, Any],
        mention_map: Dict[str, Dict[str, Any]],
        relationship_lookup: Dict[str, List[Dict[str, str]]],
        default_role: str,
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
        )
        tags = self._build_import_character_tags(char_data, mention_info, canonical_name)
        role = self._map_role(char_data.get("role", default_role))
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
            if role and (not existing.role or existing.role == "supporting" or role in {"protagonist", "antagonist"}):
                existing.role = role
            if importance_level and (
                not existing.importance_level
                or existing.importance_level == "次要角色"
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
    
    def _map_role(self, role: str) -> str:
        """映射角色类型"""
        role_map = {
            'protagonist': 'protagonist',
            'antagonist': 'antagonist',
            'deuteragonist': 'supporting',
            'supporting': 'supporting',
        }
        normalized_role = str(role or "").strip().lower()
        if not normalized_role:
            return 'supporting'
        return role_map.get(normalized_role, 'supporting')

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
        """将人物 role 映射为角色体系中的分类标签。"""
        role = str(character.role or "").strip().lower()
        if role == "protagonist":
            return "主角"
        if role == "antagonist":
            return "反派"
        if role == "supporting":
            importance = str(character.importance_level or "").strip()
            if "重要" in importance or "核心" in importance:
                return "核心配角"
            return "配角"
        return "待分类"

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

        role_label = self._build_character_system_role_label(character)
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
    
    def _import_settings(self, project: Project, analysis_map: Dict[str, BookAnalysis]):
        """
        导入设定集合
        """
        order = 0
        
        # 世界观设定
        if 'worldview' in analysis_map:
            self._create_worldview_collection(project, analysis_map['worldview'], order)
            order += 1
            order += self._sync_worldview_assets_to_standard_collections(
                project,
                analysis_map['worldview'],
                order,
            )
        
        # 情节脉络
        if 'plot' in analysis_map:
            self._create_plot_collection(project, analysis_map['plot'], order)
            order += 1
        
        # 关键概念
        if 'concepts' in analysis_map:
            self._create_concepts_collection(project, analysis_map['concepts'], order)
            order += 1

        # 写作风格参考
        if 'style' in analysis_map:
            self._create_style_collection(project, analysis_map['style'], order)
            order += 1
    
    def _create_worldview_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建世界观设定集合
        """
        content = self._load_analysis_payload(analysis, log_context="世界观分析")
        if not isinstance(content, dict) or not content:
            return

        collection = SettingCollection(
            project_id=project.id,
            name='世界观设定',
            category='worldview',
            description=f"从原著提取的世界观设定（置信度: {int(analysis.confidence * 100)}%）",
            max_depth=3,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        
        # 世界类型
        if content.get('world_type'):
            self._add_setting_item(collection.id, '世界类型', content['world_type'], item_order)
            item_order += 1
        
        # 世界描述
        if content.get('world_description'):
            self._add_setting_item(collection.id, '世界概述', content['world_description'], item_order)
            item_order += 1
        
        # 力量体系
        power_systems = content.get('power_systems', [])
        for sys in power_systems:
            sys_content = f"{sys.get('description', '')}"
            if sys.get('levels'):
                sys_content += f"\n等级: {' → '.join(sys['levels'])}"
            self._add_setting_item(collection.id, sys.get('name', '力量体系'), sys_content, item_order)
            item_order += 1
        
        # 重要地点
        locations = content.get('locations', [])[:10]
        for loc in locations:
            loc_content = f"类型: {loc.get('type', '未知')}\n{loc.get('description', '')}"
            self._add_setting_item(collection.id, loc.get('name', '地点'), loc_content, item_order)
            item_order += 1
        
        # 势力
        factions = content.get('factions', [])[:10]
        for faction in factions:
            faction_content = f"类型: {faction.get('type', '未知')}\n{faction.get('description', '')}"
            self._add_setting_item(collection.id, faction.get('name', '势力'), faction_content, item_order)
            item_order += 1
        
        logger.info(f"  → 导入世界观设定 ({item_order} 项)")
    
    def _create_plot_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建情节脉络集合
        """
        content = self._load_analysis_payload(analysis, log_context="情节分析")
        if not isinstance(content, dict) or not content:
            return

        collection = SettingCollection(
            project_id=project.id,
            name='情节脉络',
            category='plot',
            description='从原著提取的情节结构',
            max_depth=2,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        
        # 主线剧情
        if content.get('main_plot'):
            self._add_setting_item(collection.id, '主线剧情', content['main_plot'], item_order)
            item_order += 1
        
        # 剧情弧
        plot_arcs = content.get('plot_arcs', [])
        for arc in plot_arcs:
            chapters = arc.get('chapters', [])
            chapter_range = f"第{chapters[0]}-{chapters[1]}章" if len(chapters) >= 2 else ""
            arc_content = f"{chapter_range}\n{arc.get('description', '')}"
            self._add_setting_item(collection.id, arc.get('name', '剧情弧'), arc_content, item_order)
            item_order += 1
        
        # 转折点
        turning_points = content.get('turning_points', [])[:5]
        for tp in turning_points:
            tp_content = f"第{tp.get('chapter', '?')}章\n{tp.get('event', '')}\n重要性: {tp.get('significance', '')}"
            self._add_setting_item(collection.id, '转折点', tp_content, item_order)
            item_order += 1
        
        logger.info(f"  → 导入情节脉络 ({item_order} 项)")
    
    def _create_concepts_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """
        创建关键概念集合
        """
        content = self._load_analysis_payload(analysis, log_context="概念分析")
        if not isinstance(content, dict) or not content:
            return

        collection = SettingCollection(
            project_id=project.id,
            name='关键概念',
            category='concepts',
            description='从原著提取的专有名词和概念',
            max_depth=2,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()
        
        item_order = 0
        terms = content.get('terms', [])
        for term in terms[:20]:
            self._add_setting_item(
                collection.id,
                term.get('term', '概念'),
                term.get('definition', ''),
                item_order
            )
            item_order += 1
        
        logger.info(f"  → 导入关键概念 ({item_order} 项)")

    def _create_style_collection(self, project: Project, analysis: BookAnalysis, order: int):
        """导入拆书提取的写作风格参考。"""
        content = self._load_analysis_payload(analysis, log_context="风格分析")
        if not isinstance(content, dict):
            return

        style_entries = self._build_style_reference_entries(content)
        if not style_entries:
            return

        collection = SettingCollection(
            project_id=project.id,
            name='写作风格参考',
            category='style',
            description=f"从原著提取的续写风格参考（置信度: {int(analysis.confidence * 100)}%）",
            max_depth=2,
            order=order,
        )
        self.db.add(collection)
        self.db.flush()

        item_order = 0
        for name, value in style_entries:
            self._add_setting_item(collection.id, name, value, item_order)
            item_order += 1

        logger.info(f"  → 导入写作风格参考 ({item_order} 项)")
    
    def _add_setting_item(self, collection_id: int, name: str, content: str, order: int):
        """
        添加设定项
        """
        item = SettingItem(
            collection_id=collection_id,
            name=name,
            content=content,
            depth=1,
            is_leaf=True,
            order=order,
        )
        self.db.add(item)
    
    def _import_chapters(
        self,
        project: Project,
        book_id: int,
        start_from: Optional[int] = None
    ):
        """
        导入章节内容
        
        保留原书的章节号和标题格式，如 "第1章：灵草复苏之谜"
        """
        query = self.db.query(BookChapter).filter(BookChapter.book_id == book_id)
        
        if start_from:
            query = query.filter(BookChapter.chapter_number >= start_from)
        
        book_chapters = query.order_by(BookChapter.chapter_number).all()
        
        for i, bch in enumerate(book_chapters):
            # 构建完整的章节标题，保留原书章节号
            formatted_title = self._format_chapter_title(bch.chapter_number, bch.title, bch.chapter_type)
            
            chapter = Chapter(
                project_id=project.id,
                chapter_number=i + 1,
                title=formatted_title,
                content=bch.content,
                summary=bch.summary,
                summary_data=self._build_imported_chapter_summary_data(bch),
                word_count=bch.word_count,
                status='draft',
            )
            self.db.add(chapter)
        
        project.word_count = sum(ch.word_count for ch in book_chapters)
        
        logger.info(f"  → 导入 {len(book_chapters)} 个章节")

    @staticmethod
    def _decode_json_field(raw_value: Any, default: Any) -> Any:
        """
        解析 JSON 字段，失败时回退到默认值。
        """
        if raw_value is None or raw_value == "":
            return default

        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return default

        return raw_value

    def _build_imported_chapter_summary_data(self, book_chapter: BookChapter) -> Optional[str]:
        """
        将拆书章节的摘要/细纲信息转换为项目章节可直接复用的结构化摘要。
        """
        summary_data: Dict[str, Any] = {}

        outline_data = self._decode_json_field(book_chapter.outline_data, {})
        if isinstance(outline_data, dict):
            summary_data.update(outline_data)

        key_events = self._decode_json_field(book_chapter.key_events, [])
        if isinstance(key_events, list) and key_events:
            summary_data["key_events"] = key_events

        appearing_characters = self._decode_json_field(book_chapter.appearing_characters, [])
        if isinstance(appearing_characters, list) and appearing_characters:
            summary_data["appearing_characters"] = appearing_characters

        if book_chapter.summary:
            summary_data.setdefault("core_summary", book_chapter.summary)

        summary_data["source"] = "book_parser"
        summary_data["original_chapter_number"] = book_chapter.chapter_number
        summary_data["original_title"] = book_chapter.title

        if book_chapter.chapter_type and book_chapter.chapter_type != "normal":
            summary_data["original_chapter_type"] = book_chapter.chapter_type
        if book_chapter.volume_number is not None:
            summary_data["original_volume_number"] = book_chapter.volume_number
        if book_chapter.volume_title:
            summary_data["original_volume_title"] = book_chapter.volume_title

        summary_data = attach_cross_media_adaptation_hints(
            summary_data,
            chapter_title=book_chapter.title or "",
            chapter_summary=book_chapter.summary or "",
        )

        return json.dumps(summary_data, ensure_ascii=False) if summary_data else None
    
    def _format_chapter_title(self, chapter_number: int, title: str, chapter_type: str = 'normal') -> str:
        """
        格式化章节标题，保留原书章节号
        
        Args:
            chapter_number: 原书章节号
            title: 原书章节标题
            chapter_type: 章节类型 (normal/prologue/epilogue/extra/interlude)
            
        Returns:
            格式化后的标题，如 "第1章：灵草复苏之谜"
        """
        # 处理特殊章节类型
        if chapter_type == 'prologue':
            prefix = '序章'
        elif chapter_type == 'epilogue':
            prefix = '尾声'
        elif chapter_type == 'extra':
            prefix = f'番外{chapter_number}'
        elif chapter_type == 'interlude':
            prefix = f'幕间{chapter_number}'
        else:
            prefix = f'第{chapter_number}章'
        
        # 如果标题已经包含章节前缀，提取纯标题部分
        clean_title = self._extract_pure_title(title)
        
        # 组合标题
        if clean_title:
            return f"{prefix}：{clean_title}"
        else:
            return prefix
    
    def _extract_pure_title(self, title: str) -> str:
        """
        从标题中提取纯标题部分，去除章节号前缀
        
        如 "第一章 灵草复苏之谜" -> "灵草复苏之谜"
        """
        import re
        
        # 匹配并移除常见的章节前缀
        patterns = [
            r'^第[一二三四五六七八九十百千万\d]+[章节回][：:\s]*',  # 第X章：
            r'^[Cc]hapter\s*\d+[：:\s.]*',  # Chapter 1:
            r'^\d+[.、][\s]*',  # 1. 或 1、
            r'^序章[：:\s]*',
            r'^尾声[：:\s]*',
            r'^番外\d*[：:\s]*',
            r'^幕间\d*[：:\s]*',
        ]
        
        result = title.strip()
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        return result.strip()
    
    def get_import_preview(self, book_id: int) -> Dict[str, Any]:
        """
        获取导入预览信息
        """
        book = self.db.query(BookSource).filter(BookSource.id == book_id).first()
        if not book:
            return {"error": "书籍不存在"}
        
        analyses = self.db.query(BookAnalysis).filter(
            BookAnalysis.book_id == book_id
        ).all()
        
        chapters_count = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).count()
        
        preview = {
            "book": {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "total_words": book.total_words,
                "total_chapters": chapters_count,
            },
            "analyses": [],
            "import_options": {
                "characters": False,
                "worldview": False,
                "plot": False,
                "concepts": False,
            }
        }
        
        for a in analyses:
            content = self._load_analysis_payload(
                a,
                log_context=f"{self.ANALYSIS_TO_COLLECTION.get(a.analysis_type, a.analysis_type)}预览",
            )
            item_count = self._count_items(a.analysis_type, content) if content else 0
            extra_data = self._decode_json_field(getattr(a, "extra_data", None), {})
             
            preview["analyses"].append({
                "type": a.analysis_type,
                "type_name": self.ANALYSIS_TO_COLLECTION.get(a.analysis_type, a.analysis_type),
                "confidence": a.confidence,
                "item_count": item_count,
                "quality_warning": extra_data.get("quality_warning") if isinstance(extra_data, dict) else None,
            })
             
            if a.analysis_type in preview["import_options"] and item_count > 0:
                preview["import_options"][a.analysis_type] = True
        
        return preview
    
    def _count_items(self, analysis_type: str, content: Dict) -> int:
        """统计分析结果中的项目数量"""
        if analysis_type == 'characters':
            return len(content.get('main_characters', [])) + len(content.get('supporting_characters', []))
        elif analysis_type == 'worldview':
            return (
                len(content.get('locations', [])) +
                len(content.get('power_systems', [])) +
                len(content.get('factions', []))
            )
        elif analysis_type == 'plot':
            return len(content.get('plot_arcs', [])) + len(content.get('turning_points', []))
        elif analysis_type == 'concepts':
            return len(content.get('terms', []))
        return 0

    def _load_analysis_payload(self, analysis: Optional[BookAnalysis], log_context: str = "分析结果") -> Dict[str, Any]:
        """安全加载单个分析结果，跳过低质量或解析失败的内容。"""
        if not analysis:
            return {}

        try:
            content = json.loads(analysis.content) if isinstance(analysis.content, str) else analysis.content
        except Exception:
            logger.warning(f"{log_context}解析失败，已跳过")
            return {}

        if not isinstance(content, dict):
            return {}

        extra_data = self._decode_json_field(getattr(analysis, "extra_data", None), {})
        parse_error = bool(content.get("parse_error")) or (
            isinstance(extra_data, dict) and bool(extra_data.get("parse_error"))
        )
        if parse_error:
            logger.warning(f"{log_context}包含 parse_error 标记，已跳过导入")
            return {}

        return content

    def _load_analysis_content(self, analysis_map: Dict[str, BookAnalysis], analysis_type: str) -> Dict[str, Any]:
        """安全加载分析结果 JSON。"""
        analysis = analysis_map.get(analysis_type)
        return self._load_analysis_payload(analysis, log_context=analysis_type)

    @staticmethod
    def _normalize_memory_text(value: Any) -> str:
        """将任意值规范为单行记忆文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "；".join(parts)
        return str(value).strip()

    @classmethod
    def _clean_memory_line(cls, text: str, max_length: int = 120) -> str:
        """清理并裁剪结构化记忆行。"""
        cleaned = " ".join(str(text or "").split()).strip(" -")
        if not cleaned:
            return ""
        if len(cleaned) > max_length:
            return cleaned[: max_length - 3].rstrip() + "..."
        return cleaned

    @classmethod
    def _deduplicate_memory_items(cls, items: List[str], limit: int) -> List[str]:
        """保持顺序去重，并按类别上限裁剪。"""
        result: List[str] = []
        seen = set()

        for item in items:
            normalized = cls._clean_memory_line(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
            if len(result) >= limit:
                break

        return result

    def _render_structured_memory_text(self, structured_memory: Dict[str, List[str]]) -> str:
        """渲染与工作流兼容的结构化记忆文本。"""
        category_labels = [
            ("global_story_arcs", "主线弧线"),
            ("character_states", "人物状态"),
            ("relationship_edges", "关系边"),
            ("pending_foreshadowings", "待回收伏笔"),
            ("world_rules_hard_constraints", "世界规则硬约束"),
        ]

        parts: List[str] = ["【结构化记忆】"]
        for key, label in category_labels:
            values = structured_memory.get(key) or []
            if not values:
                continue
            parts.append(f"- {label}:")
            for value in values:
                parts.append(f"  - {value}")

        return "\n".join(parts).strip()

    def _build_import_structured_memory_payload(
        self,
        analysis_map: Dict[str, BookAnalysis],
        book: BookSource,
    ) -> Optional[Dict[str, Any]]:
        """基于拆书结果构建可直接用于工作流的结构化记忆。"""
        plot_content = self._load_analysis_content(analysis_map, 'plot')
        character_content = self._load_analysis_content(analysis_map, 'characters')
        worldview_content = self._load_analysis_content(analysis_map, 'worldview')
        concepts_content = self._load_analysis_content(analysis_map, 'concepts')

        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book.id
        ).order_by(BookChapter.chapter_number).all()

        global_story_arcs: List[str] = []
        main_plot = self._normalize_memory_text(plot_content.get('main_plot'))
        if main_plot:
            global_story_arcs.append(f"主线：{main_plot}")

        for arc in (plot_content.get('plot_arcs') or [])[:6]:
            if not isinstance(arc, dict):
                continue
            name = self._normalize_memory_text(arc.get('name')) or "未命名剧情弧"
            arc_desc = self._normalize_memory_text(arc.get('description'))
            chapters = arc.get('chapters') or []
            meta_parts = []
            if isinstance(chapters, list) and len(chapters) >= 2:
                meta_parts.append(f"第{chapters[0]}-{chapters[1]}章")
            arc_type = self._normalize_memory_text(arc.get('type'))
            if arc_type:
                meta_parts.append(arc_type)
            meta_text = f"（{' / '.join(meta_parts)}）" if meta_parts else ""
            global_story_arcs.append(f"{name}{meta_text}：{arc_desc}" if arc_desc else f"{name}{meta_text}")

        for tp in (plot_content.get('turning_points') or [])[:4]:
            if not isinstance(tp, dict):
                continue
            chapter = self._normalize_memory_text(tp.get('chapter'))
            event = self._normalize_memory_text(tp.get('event'))
            significance = self._normalize_memory_text(tp.get('significance'))
            title = f"第{chapter}章转折" if chapter else "关键转折"
            detail = "；".join([item for item in [event, significance] if item])
            if detail:
                global_story_arcs.append(f"{title}：{detail}")

        if not global_story_arcs:
            for chapter in (book_chapters[:2] + book_chapters[-2:]):
                if chapter.summary:
                    global_story_arcs.append(f"第{chapter.chapter_number}章：{chapter.summary}")

        character_states: List[str] = []
        for bucket_name in ('main_characters', 'supporting_characters'):
            for char in (character_content.get(bucket_name) or []):
                if not isinstance(char, dict):
                    continue
                name = self._normalize_memory_text(char.get('name'))
                if not name:
                    continue
                fragments = [name]
                role = self._normalize_memory_text(char.get('role'))
                if role:
                    fragments.append(f"定位={role}")
                stance = self._normalize_memory_text(char.get('story_stance'))
                if stance and stance != '未提及':
                    fragments.append(f"立场={stance}")
                faction = self._normalize_memory_text(char.get('faction'))
                if faction and faction != '未提及':
                    fragments.append(f"势力={faction}")
                description = self._normalize_memory_text(
                    char.get('description') or char.get('relationship_to_main')
                )
                if description:
                    fragments.append(description)
                character_states.append("；".join(fragments))

        relationship_edges: List[str] = []
        for rel in (character_content.get('character_relationships') or [])[:12]:
            if not isinstance(rel, dict):
                continue
            char_a = self._normalize_memory_text(rel.get('character1'))
            char_b = self._normalize_memory_text(rel.get('character2'))
            if not char_a or not char_b:
                continue
            relation = self._normalize_memory_text(rel.get('relationship'))
            description = self._normalize_memory_text(rel.get('description'))
            detail_parts = [item for item in [relation, description] if item]
            detail = "；".join(detail_parts)
            relationship_edges.append(f"{char_a} <-> {char_b}：{detail}" if detail else f"{char_a} <-> {char_b}")

        pending_foreshadowings: List[str] = []
        for chapter in book_chapters:
            outline_data = self._decode_json_field(chapter.outline_data, {})
            if not isinstance(outline_data, dict):
                continue

            for item in (outline_data.get('foreshadowing') or []):
                text = self._normalize_memory_text(item)
                if text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章伏笔：{text}")

            ending_hook = outline_data.get('ending_hook')
            if isinstance(ending_hook, dict):
                hook_text = self._normalize_memory_text(
                    ending_hook.get('content') or ending_hook.get('hook') or ending_hook.get('summary')
                )
                if hook_text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章钩子：{hook_text}")
            else:
                hook_text = self._normalize_memory_text(ending_hook)
                if hook_text:
                    pending_foreshadowings.append(f"第{chapter.chapter_number}章钩子：{hook_text}")

        for conflict in (plot_content.get('conflicts') or [])[:6]:
            if not isinstance(conflict, dict):
                continue
            status = self._normalize_memory_text(conflict.get('status'))
            if status and status != '已解决':
                description = self._normalize_memory_text(conflict.get('description'))
                if description:
                    pending_foreshadowings.append(f"未解决冲突：{description}")

        world_rules_hard_constraints: List[str] = []
        world_type = self._normalize_memory_text(worldview_content.get('world_type'))
        if world_type:
            world_rules_hard_constraints.append(f"世界类型：{world_type}")

        time_period = self._normalize_memory_text(worldview_content.get('time_period'))
        if time_period:
            world_rules_hard_constraints.append(f"时代背景：{time_period}")

        for system in (worldview_content.get('power_systems') or [])[:5]:
            if not isinstance(system, dict):
                continue
            name = self._normalize_memory_text(system.get('name')) or "未命名体系"
            description = self._normalize_memory_text(system.get('description'))
            levels = system.get('levels') or []
            levels_text = " -> ".join([str(level).strip() for level in levels if str(level).strip()])
            detail_parts = []
            if description:
                detail_parts.append(description)
            if levels_text:
                detail_parts.append(f"等级：{levels_text}")
            detail = "；".join(detail_parts)
            world_rules_hard_constraints.append(f"力量体系：{name}；{detail}" if detail else f"力量体系：{name}")

        for term in (concepts_content.get('terms') or [])[:4]:
            if not isinstance(term, dict):
                continue
            term_name = self._normalize_memory_text(term.get('term'))
            definition = self._normalize_memory_text(term.get('definition'))
            if term_name and definition:
                world_rules_hard_constraints.append(f"术语：{term_name}；{definition}")

        structured_memory: Dict[str, List[str]] = {}
        raw_memory_map = {
            "global_story_arcs": global_story_arcs,
            "character_states": character_states,
            "relationship_edges": relationship_edges,
            "pending_foreshadowings": pending_foreshadowings,
            "world_rules_hard_constraints": world_rules_hard_constraints,
        }

        for key, values in raw_memory_map.items():
            deduplicated = self._deduplicate_memory_items(
                values,
                self.STRUCTURED_MEMORY_LIMITS.get(key, 12),
            )
            if deduplicated:
                structured_memory[key] = deduplicated

        if not structured_memory:
            return None

        now_iso = utc_now().isoformat()
        return {
            "structured_memory": structured_memory,
            "memory_text": self._render_structured_memory_text(structured_memory),
            "metadata": {
                "source": "book_parser_import",
                "book_id": book.id,
                "book_title": book.title,
                "analysis_types": sorted(analysis_map.keys()),
            },
            "updated_at": now_iso,
        }

    def _project_settings_supports_structured_memory(self) -> bool:
        """检查当前数据库是否已经具备结构化记忆字段。"""
        try:
            inspector = inspect(self.db.get_bind())
            columns = {column["name"] for column in inspector.get_columns("project_settings")}
        except Exception as exc:
            logger.warning(f"  ⚠️ 检查 structured_memory 字段失败: {exc}")
            return False

        return {"structured_memory", "structured_memory_updated_at"}.issubset(columns)

    def _save_import_structured_memory(
        self,
        project_id: int,
        payload: Optional[Dict[str, Any]],
        updated_at: str,
    ) -> None:
        """将拆书生成的结构化记忆写入 project_settings。"""
        if not payload:
            return

        if not self._project_settings_supports_structured_memory():
            logger.info("  ℹ️ 当前数据库未启用 structured_memory 字段，跳过初始化")
            return

        from sqlalchemy import text

        self.db.execute(
            text(
                """
                UPDATE project_settings
                SET structured_memory = :structured_memory,
                    structured_memory_updated_at = :structured_memory_updated_at,
                    updated_at = :updated_at
                WHERE project_id = :project_id
                """
            ),
            {
                "project_id": project_id,
                "structured_memory": json.dumps(payload, ensure_ascii=False),
                "structured_memory_updated_at": updated_at,
                "updated_at": updated_at,
            },
        )
        logger.info("  → 已初始化结构化记忆 (structured_memory)")
    
    def _init_project_settings(self, project: Project, analysis_map: Dict[str, BookAnalysis], book: BookSource):
        """
        初始化 project_settings 表，填充工作流阶段内容
        
        将拆书分析结果转换为工作流可用的格式：
        - concept: 故事概念（基于情节分析生成）
        - world_setting: 世界观设定
        - characters: 人物设定
        - plot_outline: 情节大纲
        """
        from sqlalchemy import text
        
        # 构建各阶段内容
        concept_text = self._build_concept_text(analysis_map, book)
        world_setting_text = self._build_world_setting_text(analysis_map)
        characters_text = self._build_characters_text(analysis_map)
        plot_outline_text = self._build_plot_outline_text(analysis_map, book.id)
        structured_memory_payload = self._build_import_structured_memory_payload(analysis_map, book)
        
        # 插入 project_settings 记录
        now_iso = utc_now().isoformat()
        insert_sql = text("""
            INSERT INTO project_settings (
                project_id, concept, world_setting, characters, plot_outline, created_at, updated_at
            )
            VALUES (
                :project_id, :concept, :world_setting, :characters, :plot_outline, :created_at, :updated_at
            )
            ON CONFLICT(project_id) DO UPDATE SET
                concept = :concept,
                world_setting = :world_setting,
                characters = :characters,
                plot_outline = :plot_outline,
                updated_at = :updated_at
        """)
        
        self.db.execute(insert_sql, {
            'project_id': project.id,
            'concept': concept_text,
            'world_setting': world_setting_text,
            'characters': characters_text,
            'plot_outline': plot_outline_text,
            'created_at': now_iso,
            'updated_at': now_iso,
        })

        self._save_import_structured_memory(
            project_id=project.id,
            payload=structured_memory_payload,
            updated_at=now_iso,
        )
        
        logger.info(f"  → 已初始化工作流阶段内容 (project_settings)")

    @staticmethod
    def _stringify_style_value(value: Any) -> str:
        """将风格字段规范成适合展示的单行文本。"""
        if value is None:
            return ""
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            return "、".join(items)
        return str(value).strip()

    def _format_style_sentence(self, value: Any) -> str:
        """兼容新旧风格 schema 的句式描述。"""
        if isinstance(value, dict):
            parts: List[str] = []
            avg_length = self._stringify_style_value(value.get("avg_length"))
            if avg_length:
                parts.append(f"平均句长约{avg_length}字")
            complexity = self._stringify_style_value(value.get("complexity"))
            if complexity:
                parts.append(f"复杂度{complexity}")
            dominant_style = self._stringify_style_value(
                value.get("dominant_style") or value.get("style")
            )
            if dominant_style:
                parts.append(dominant_style)
            return "，".join(parts)

        return self._stringify_style_value(value)

    def _format_style_description(self, value: Any) -> str:
        """兼容字符串与对象两种描写风格格式。"""
        if isinstance(value, dict):
            parts: List[str] = []
            field_pairs = [
                ("场景", value.get("scene_description")),
                ("人物", value.get("character_description")),
                ("动作", value.get("action_description")),
                ("心理", value.get("psychological_description")),
            ]
            for label, raw_value in field_pairs:
                text_value = self._stringify_style_value(raw_value)
                if text_value:
                    parts.append(f"{label}：{text_value}")
            return "；".join(parts)

        return self._stringify_style_value(value)

    def _format_dialogue_ratio(self, value: Any) -> str:
        """将对话占比格式化为易读文本。"""
        if value is None or value == "":
            return ""

        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return self._stringify_style_value(value)

        if ratio <= 1:
            ratio *= 100
        return f"对话占比约{ratio:.0f}%"

    def _build_style_reference_entries(self, style_content: Dict[str, Any]) -> List[tuple[str, str]]:
        """将风格分析结果归一化为可复用的条目列表。"""
        if not style_content:
            return []

        language_features = style_content.get("language_features")
        if not isinstance(language_features, dict):
            language_features = {}

        vocabulary_level = self._stringify_style_value(
            language_features.get("vocabulary_level") or style_content.get("vocabulary_features")
        )
        sentence_style = self._format_style_sentence(
            language_features.get("sentence_style") or style_content.get("sentence_style")
        )
        rhetoric = self._stringify_style_value(language_features.get("rhetoric"))
        dialogue_style = self._stringify_style_value(language_features.get("dialogue_style"))
        dialogue_ratio = self._format_dialogue_ratio(style_content.get("dialogue_ratio"))

        language_parts: List[str] = []
        if vocabulary_level:
            language_parts.append(f"用词：{vocabulary_level}")
        if sentence_style:
            language_parts.append(f"句式：{sentence_style}")
        if rhetoric:
            language_parts.append(f"修辞：{rhetoric}")
        if dialogue_style:
            language_parts.append(f"对话：{dialogue_style}")
        if dialogue_ratio:
            language_parts.append(dialogue_ratio)

        entries = [
            ("叙事视角", self._stringify_style_value(style_content.get("narrative_perspective"))),
            ("叙事风格", self._stringify_style_value(style_content.get("narrative_style"))),
            ("整体基调", self._stringify_style_value(style_content.get("tone"))),
            ("节奏特点", self._stringify_style_value(style_content.get("pacing"))),
            ("语言特点", "；".join(language_parts)),
            ("描写侧重", self._format_style_description(style_content.get("description_style"))),
            ("风格优势", self._stringify_style_value(style_content.get("strengths"))),
            ("独特标识", self._stringify_style_value(style_content.get("unique_features"))),
            ("类型惯例", self._stringify_style_value(style_content.get("genre_conventions"))),
            ("参考作者", self._stringify_style_value(style_content.get("similar_authors"))),
        ]

        return [(name, value) for name, value in entries if value]
    
    def _build_concept_text(self, analysis_map: Dict[str, BookAnalysis], book: BookSource) -> str:
        """构建故事概念文本（六部分标准格式 - 与创作模式一致）"""
        parts = []
        
        # 从情节分析提取概念信息
        plot_content = self._load_analysis_content(analysis_map, 'plot')
        worldview_content = self._load_analysis_content(analysis_map, 'worldview')
        concept_data = plot_content.get('concept', {}) if isinstance(plot_content, dict) else {}
        
        # 1. 一句话卖点（Logline）
        parts.append("**一句话卖点（Logline）**")
        logline = concept_data.get('logline', '')
        if not logline:
            main_plot = plot_content.get('main_plot', '') if isinstance(plot_content, dict) else ''
            logline = main_plot[:60] + '...' if len(main_plot) > 60 else main_plot
        parts.append(logline or f"《{book.title}》的故事")
        parts.append("")
        
        # 2. 日志标题（短标题）
        parts.append("**日志标题（短标题）**")
        short_title = concept_data.get('short_title', '') or book.title[:10]
        parts.append(short_title)
        parts.append("")
        
        # 3. 概念摘要（80–150字）
        parts.append("**概念摘要**")
        summary = concept_data.get('summary', '')
        if not summary and isinstance(plot_content, dict):
            summary = plot_content.get('main_plot', '')[:150]
        parts.append(summary or f"基于《{book.title}》的创作项目")
        parts.append("")
        
        # 4. 题材与流派
        parts.append("**题材与流派**")
        genre = concept_data.get('genre', '') or book.genre or '通用题材'
        sub_genre = concept_data.get('sub_genre', '')
        genre_text = f"{genre} / {sub_genre}" if sub_genre else genre
        parts.append(genre_text)
        parts.append("")
        
        # 5. 核心标签
        parts.append("**核心标签**")
        core_tags = concept_data.get('core_tags', [])
        if core_tags:
            parts.append("、".join(core_tags))
        else:
            parts.append("待补充")
        parts.append("")
        
        # 6. 核心冲突与情感基调
        parts.append("**核心冲突与情感基调**")
        core_conflict = concept_data.get('core_conflict', '')
        emotional_tone = concept_data.get('emotional_tone', '')
        
        if core_conflict:
            parts.append(f"核心冲突：{core_conflict}")
        if emotional_tone:
            parts.append(f"情感基调：{emotional_tone}")
        if not core_conflict and not emotional_tone:
            # 回退：从冲突列表提取
            conflicts = plot_content.get('conflicts', []) if isinstance(plot_content, dict) else []
            if conflicts:
                parts.append(f"核心冲突：{conflicts[0].get('description', '待分析')}")
        parts.append("")
        
        # 7. 世界观高概摘要（可简略）
        if isinstance(worldview_content, dict) and worldview_content.get('world_description'):
            parts.append("**世界观高概摘要**")
            parts.append(worldview_content['world_description'][:200])
            parts.append("")

        style_entries = self._build_style_reference_entries(
            self._load_analysis_content(analysis_map, 'style')
        )
        if style_entries:
            parts.append("**写作风格参考**")
            for name, value in style_entries[:6]:
                parts.append(f"- {name}：{value}")
            parts.append("")
        
        return '\n'.join(parts) if parts else f"# {book.title}\n\n基于《{book.title}》的创作项目"
    
    def _build_world_setting_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """构建世界观设定文本"""
        content = self._load_analysis_content(analysis_map, 'worldview')
        if not isinstance(content, dict) or not content:
            return ""
        
        parts = ["# 世界观设定", ""]
        
        # 世界类型
        if content.get('world_type'):
            parts.append(f"## 世界类型")
            parts.append(content['world_type'])
            parts.append("")
        
        # 世界描述
        if content.get('world_description'):
            parts.append(f"## 世界概述")
            parts.append(content['world_description'])
            parts.append("")
        
        # 力量体系
        power_systems = content.get('power_systems', [])
        if power_systems:
            parts.append("## 力量体系")
            for sys in power_systems:
                parts.append(f"### {sys.get('name', '未命名体系')}")
                if sys.get('description'):
                    parts.append(sys['description'])
                if sys.get('levels'):
                    parts.append(f"等级：{' → '.join(sys['levels'])}")
                parts.append("")
        
        # 重要地点
        locations = content.get('locations', [])[:10]
        if locations:
            parts.append("## 重要地点")
            for loc in locations:
                parts.append(f"### {loc.get('name', '未命名')}")
                if loc.get('type'):
                    parts.append(f"类型：{loc['type']}")
                if loc.get('description'):
                    parts.append(loc['description'])
                parts.append("")
        
        # 势力
        factions = content.get('factions', [])[:10]
        if factions:
            parts.append("## 主要势力")
            for faction in factions:
                parts.append(f"### {faction.get('name', '未命名')}")
                if faction.get('type'):
                    parts.append(f"类型：{faction['type']}")
                if faction.get('description'):
                    parts.append(faction['description'])
                parts.append("")
        
        return '\n'.join(parts)
    
    def _build_characters_text(self, analysis_map: Dict[str, BookAnalysis]) -> str:
        """生成与人物扩展一致的人物档案文本。"""
        content = self._load_analysis_content(analysis_map, 'characters')
        if not isinstance(content, dict) or not content:
            return ""

        def normalize_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                return "、".join(items)
            return str(value).strip()

        def pick_first(*values: Any) -> str:
            for value in values:
                text_value = normalize_text(value)
                if text_value:
                    return text_value
            return ""

        def build_role_text(role_value: str, fallback: str) -> str:
            role_map = {
                'protagonist': '主角',
                'antagonist': '反派',
                'deuteragonist': '核心配角',
                'supporting': '支持角色',
            }
            if role_value:
                normalized = str(role_value).strip().lower()
                if normalized:
                    return role_map.get(normalized, role_value)
            return fallback

        relationship_map: Dict[str, List[str]] = {}
        for rel in (content.get('character_relationships', []) or []):
            char_a = normalize_text(rel.get('character1'))
            char_b = normalize_text(rel.get('character2'))
            if not char_a or not char_b:
                continue
            relation = normalize_text(rel.get('relationship'))
            description = normalize_text(rel.get('description'))
            detail_parts = []
            if relation:
                detail_parts.append(relation)
            if description and description != relation:
                detail_parts.append(description)
            detail = "，".join(detail_parts)
            line_a = f"{char_b}：{detail}" if detail else char_b
            line_b = f"{char_a}：{detail}" if detail else char_a
            relationship_map.setdefault(char_a, []).append(line_a)
            relationship_map.setdefault(char_b, []).append(line_b)

        def value_or_default(value: str) -> str:
            return value if value else "待补充"

        def append_character_card(target: List[str], char_data: Dict[str, Any], role_text: str) -> None:
            name = normalize_text(char_data.get('name')) or "待补充"
            age_gender = pick_first(char_data.get('age_gender'), char_data.get('age'), char_data.get('gender'))
            appearance = pick_first(char_data.get('appearance'), char_data.get('looks'), char_data.get('appearance_feature'))
            personality = pick_first(char_data.get('personality'), char_data.get('traits'))
            background = pick_first(char_data.get('background'), char_data.get('backstory'))
            worldview = pick_first(char_data.get('worldview'), char_data.get('values'), char_data.get('worldview_position'))
            motivation = pick_first(char_data.get('motivation'), char_data.get('goal'))
            abilities = pick_first(char_data.get('abilities'), char_data.get('skills'), char_data.get('strengths'))
            weakness = pick_first(char_data.get('weakness'), char_data.get('weaknesses'), char_data.get('flaws'))
            plot_role = pick_first(char_data.get('plot_role'), char_data.get('role_in_plot'), char_data.get('description'))
            growth_arc = pick_first(char_data.get('arc'), char_data.get('development'), char_data.get('growth'))
            related_clues = pick_first(char_data.get('clues'), char_data.get('related_clues'))

            relationship_lines: List[str] = []
            relation_to_main = normalize_text(char_data.get('relationship_to_main'))
            if relation_to_main:
                relationship_lines.append(f"与主角：{relation_to_main}")
            relationship_lines.extend(relationship_map.get(name, []))
            relationship_text = "；".join(list(dict.fromkeys([line for line in relationship_lines if line]))) or "待补充"

            target.append(f"### 【姓名】：{name}")
            target.append("")
            target.append(f"【年龄/性别】：{value_or_default(age_gender)}")
            target.append("")
            target.append(f"【角色定位】：{value_or_default(role_text)}")
            target.append("")
            target.append(f"【外貌特征】：{value_or_default(appearance)}")
            target.append("")
            target.append(f"【性格特点】：{value_or_default(personality)}")
            target.append("")
            target.append(f"【背景故事】：{value_or_default(background)}")
            target.append("")
            target.append(f"【世界观/价值观立场】：{value_or_default(worldview)}")
            target.append("")
            target.append(f"【核心动机】：{value_or_default(motivation)}")
            target.append("")
            target.append(f"【能力/特长】：{value_or_default(abilities)}")
            target.append("")
            target.append(f"【弱点/缺陷】：{value_or_default(weakness)}")
            target.append("")
            target.append(f"【在情节中的作用】：{value_or_default(plot_role)}")
            target.append("")
            target.append(f"【人物成长线】：{value_or_default(growth_arc)}")
            target.append("")
            target.append(f"【关键关系】：{value_or_default(relationship_text)}")
            target.append("")
            target.append(f"【关联线索】：{value_or_default(related_clues)}")
            target.append("")
            target.append("---")
            target.append("")

        parts: List[str] = []
        main_characters = content.get('main_characters', []) or []
        supporting_characters = content.get('supporting_characters', []) or []

        main_names = {normalize_text(c.get('name')) for c in main_characters if normalize_text(c.get('name'))}
        supporting_characters = [c for c in supporting_characters if normalize_text(c.get('name')) not in main_names]

        groups: Dict[str, List[Any]] = {
            "主角阵营": [],
            "对手阵营": [],
            "支持角色": [],
            "中立角色": [],
        }

        for char in main_characters:
            role = str(char.get('role') or '').lower()
            if role == 'protagonist':
                groups["主角阵营"].append((char, build_role_text(role, "主角")))
            elif role == 'antagonist':
                groups["对手阵营"].append((char, build_role_text(role, "反派")))
            elif role in {'deuteragonist', 'supporting'}:
                groups["支持角色"].append((char, build_role_text(role, "支持角色")))
            else:
                groups["中立角色"].append((char, build_role_text(role, "中立角色")))

        for char in supporting_characters:
            role = str(char.get('role') or '').lower()
            groups["支持角色"].append((char, build_role_text(role, "支持角色")))

        for group_name, entries in groups.items():
            if not entries:
                continue
            parts.append(f"## {group_name}")
            parts.append("")
            for char_data, role_text in entries:
                append_character_card(parts, char_data, role_text)

        return "\n".join(parts).strip()

    def _build_plot_outline_text(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """生成与大纲扩展一致的情节大纲文本。"""
        content = self._load_analysis_content(analysis_map, 'plot')
        if not isinstance(content, dict) or not content:
            return ""

        def normalize_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [str(v).strip() for v in value if str(v).strip()]
                return "、".join(items)
            return str(value).strip()

        def format_arc_brief(arc: Any) -> str:
            if not isinstance(arc, dict):
                return normalize_text(arc) or "待补充"
            name = normalize_text(arc.get('name')) or "待补充"
            desc = normalize_text(arc.get('description'))
            chapters = arc.get('chapters') or []
            meta_parts = []
            if isinstance(chapters, list) and len(chapters) >= 2:
                meta_parts.append(f"第{chapters[0]}-{chapters[1]}章")
            arc_type = normalize_text(arc.get('type'))
            if arc_type:
                meta_parts.append(arc_type)
            if meta_parts:
                name = f"{name}（{' / '.join(meta_parts)}）"
            if desc:
                return f"{name}：{desc}"
            return name

        parts: List[str] = []

        main_plot = normalize_text(content.get('main_plot'))
        if not main_plot:
            main_plot = normalize_text(content.get('concept', {}).get('summary')) or normalize_text(content.get('concept', {}).get('logline'))
        parts.append("1. 故事概述")
        parts.append(main_plot if main_plot else "待补充")
        parts.append("")

        plot_arcs = content.get('plot_arcs', []) or []
        parts.append("2. 情节发展")
        if plot_arcs:
            for arc in plot_arcs:
                parts.append(f"- {format_arc_brief(arc)}")
        else:
            parts.append("待补充")
        parts.append("")

        turning_points = content.get('turning_points', []) or []
        parts.append("3. 重要转折点")
        if turning_points:
            for tp in turning_points[:8]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                significance = normalize_text(tp.get('significance')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail_parts = [item for item in [event, significance] if item]
                detail = "，".join(detail_parts)
                parts.append(f"- {title}：{detail}" if detail else f"- {title}")
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("4. 高潮设计")
        climax_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if "高潮" in arc_type or "高潮" in arc_name or "决战" in arc_name:
                climax_lines.append(f"- {format_arc_brief(arc)}")
        if not climax_lines and turning_points:
            for tp in turning_points[-2:]:
                chapter = normalize_text(tp.get('chapter')) if isinstance(tp, dict) else ""
                event = normalize_text(tp.get('event')) if isinstance(tp, dict) else ""
                title = f"第{chapter}章" if chapter else "关键节点"
                detail = event or (normalize_text(tp.get('significance')) if isinstance(tp, dict) else "")
                climax_lines.append(f"- {title}：{detail}" if detail else f"- {title}")
        if climax_lines:
            parts.extend(climax_lines)
        else:
            parts.append("待补充")
        parts.append("")

        parts.append("5. 结局规划")
        ending_lines = []
        for arc in plot_arcs:
            if not isinstance(arc, dict):
                continue
            arc_type = normalize_text(arc.get('type'))
            arc_name = normalize_text(arc.get('name'))
            if any(keyword in arc_type for keyword in ["结局", "收尾", "终局", "尾声"]) or any(keyword in arc_name for keyword in ["结局", "收尾", "终局", "尾声"]):
                ending_lines.append(f"- {format_arc_brief(arc)}")
        if not ending_lines:
            chapter_summaries = content.get('chapter_summaries') or []
            if chapter_summaries:
                last_summary = normalize_text(chapter_summaries[-1])
                if last_summary:
                    ending_lines.append(f"- {last_summary}")
        if ending_lines:
            parts.extend(ending_lines)
        else:
            parts.append("待补充")

        return "\n".join(parts).strip()
