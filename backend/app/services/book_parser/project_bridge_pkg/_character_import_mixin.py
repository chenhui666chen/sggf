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

class CharacterImportMixin:
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
        characters = self._get_character_entries(content)
        primary_count = 0

        for char_data in characters:
            is_primary = self._is_primary_character_entry(char_data)
            if is_primary:
                primary_count += 1
            self._upsert_import_character(
                project=project,
                imported_by_key=imported_by_key,
                char_data=char_data,
                mention_map=mention_map,
                relationship_lookup=relationship_lookup,
                default_story_stance='',
                default_role_position='主线角色' if is_primary else '功能角色',
                default_importance='重要角色' if is_primary else '次要角色',
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
                default_story_stance='',
                default_role_position='功能角色',
                default_importance='次要角色',
                is_backfilled=True,
            )
            if created is not None:
                auto_created += 1

        logger.info(
            f"  → 导入 {primary_count} 个主线人物, {max(len(characters) - primary_count, 0)} 个功能人物, "
            f"自动补建 {auto_created} 个章节人物卡"
        )

    @classmethod
    def _get_character_entries(cls, content: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从人物分析结果中读取标准化后的单一人物列表。"""
        if not isinstance(content, dict):
            return []

        items = content.get("characters")
        if not isinstance(items, list):
            return []

        deduped: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            name = cls._normalize_import_character_name(raw_item.get("name"))
            if not name:
                continue
            item = dict(raw_item)
            item["name"] = name
            if name not in deduped:
                deduped[name] = item
                order.append(name)
                continue

            existing = deduped[name]
            for key, value in item.items():
                if key == "name" or value in (None, "", [], {}):
                    continue
                if existing.get(key) in (None, "", [], {}):
                    existing[key] = value
                elif isinstance(existing.get(key), str) and isinstance(value, str) and len(value) > len(existing[key]):
                    existing[key] = value

        return [deduped[name] for name in order]

    @classmethod
    def _is_primary_character_entry(cls, char_data: Dict[str, Any]) -> bool:
        """判断人物条目是否属于主线核心人物。"""
        importance = cls._stringify_import_value(
            char_data.get("importance_level") or char_data.get("importance")
        )
        role_position = cls._normalize_role_position_value(char_data.get("role_position"))
        story_stance = cls._normalize_story_stance_value(char_data.get("story_stance"))

        if role_position == "主角" or "主角" in importance:
            return True
        if any(keyword in importance for keyword in ("核心", "重要")):
            return True
        if role_position in {"盟友", "导师", "对手", "首领", "主线角色"}:
            return True
        if story_stance in {"主角方", "反派方", "亦正亦邪"} and role_position not in {"功能角色", "中立角色", ""}:
            return True
        return False

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

    @classmethod
    def _normalize_story_stance_value(cls, value: Any) -> str:
        """标准化故事立场，仅接受正式值或可直接归类的中文描述。"""
        text = str(value or "").strip()
        if not text or text == "未提及":
            return ""
        if text in cls.CANONICAL_STORY_STANCES:
            return text

        if "亦正亦邪" in text:
            return "亦正亦邪"
        if any(keyword in text for keyword in ("中立", "旁观", "游离")):
            return "中立方"
        if any(keyword in text for keyword in ("对手", "反派", "敌", "宿敌", "追杀", "围杀", "阻挠")):
            return "反派方"
        if any(keyword in text for keyword in ("主角", "主角方", "主角阵营", "正派", "正义", "盟友", "导师", "同伴", "队友", "助力", "守护")):
            return "主角方"
        return ""

    @classmethod
    def _infer_role_position_from_relationship(cls, relationship_to_main: Any) -> str:
        """从与主角关系中提炼更可用的角色定位。"""
        text = str(relationship_to_main or "").strip()
        if not text or text == "未提及":
            return ""
        if any(keyword in text for keyword in ("导师", "师父", "老师")):
            return "导师"
        if any(keyword in text for keyword in ("盟友", "伙伴", "搭档", "同伴", "队友", "同盟")):
            return "盟友"
        if any(keyword in text for keyword in ("对手", "敌", "宿敌", "追杀", "阻挠", "围杀", "压制")):
            return "对手"
        if any(keyword in text for keyword in ("守护", "保护", "护卫")):
            return "守护者"
        if any(keyword in text for keyword in ("情报", "线人", "内应")):
            return "情报角色"
        if any(keyword in text for keyword in ("受害", "目标", "被害")):
            return "受害者"
        if any(keyword in text for keyword in ("中立", "旁观", "游离")):
            return "中立角色"
        return ""

    @classmethod
    def _normalize_role_position_value(
        cls,
        value: Any,
        *,
        relationship_to_main: Any = None,
        fallback: Any = None,
    ) -> str:
        """标准化角色定位，并优先使用关系信息把泛化定位细化。"""

        def normalize_candidate(raw_value: Any) -> str:
            text = str(raw_value or "").strip()
            if not text or text == "未提及":
                return ""
            if text == "主角方":
                return "主角"
            if text == "反派方":
                return "对手"
            if text == "中立方":
                return "中立角色"
            if text == "亦正亦邪":
                return "摇摆角色"
            return text

        mapped_value = normalize_candidate(value) or normalize_candidate(fallback)

        relationship_position = cls._infer_role_position_from_relationship(relationship_to_main)
        if relationship_position and (not mapped_value or mapped_value in cls.GENERIC_ROLE_POSITIONS):
            return relationship_position
        return mapped_value

    @classmethod
    def _infer_story_stance(
        cls,
        *,
        explicit_stance: Any = None,
        role_position: Any = None,
        relationship_to_main: Any = None,
        fallback: Any = None,
        additional_texts: Optional[List[Any]] = None,
    ) -> str:
        """综合显式字段、角色定位和关系信息推断故事立场。"""
        explicit = cls._normalize_story_stance_value(explicit_stance)
        if explicit:
            return explicit

        relationship_text = str(relationship_to_main or "").strip()
        if any(keyword in relationship_text for keyword in ("盟友", "伙伴", "搭档", "同伴", "队友", "同盟", "协助", "帮助", "守护", "保护")):
            return "主角方"
        if any(keyword in relationship_text for keyword in ("对手", "敌", "宿敌", "追杀", "阻挠", "围杀", "压制")):
            return "反派方"
        if any(keyword in relationship_text for keyword in ("中立", "旁观", "游离")):
            return "中立方"

        role_position_text = str(role_position or "").strip()
        if role_position_text and role_position_text not in {"主线角色", "功能角色"}:
            inferred = cls._normalize_story_stance_value(role_position_text)
            if inferred:
                return inferred

        evidence_stance = infer_story_stance_from_text_evidence(
            role_position,
            relationship_to_main,
            *(additional_texts or []),
        )
        if evidence_stance:
            return evidence_stance
        return cls._normalize_story_stance_value(fallback)

    @classmethod
    def _should_replace_story_stance(cls, existing_value: Any, new_value: str, *, explicit: bool = False) -> bool:
        """只在旧值缺失、非规范或新值更可信时覆盖故事立场。"""
        if not new_value:
            return False

        existing_text = str(existing_value or "").strip()
        existing_normalized = cls._normalize_story_stance_value(existing_text)
        if not existing_text or existing_text != existing_normalized:
            return True
        if explicit and existing_normalized != new_value:
            return True
        return False

    @classmethod
    def _should_replace_role_position(cls, existing_value: Any, new_value: str) -> bool:
        """只在旧值缺失、明显泛化或被故事立场污染时覆盖角色定位。"""
        if not new_value:
            return False

        existing_text = str(existing_value or "").strip()
        if not existing_text:
            return True
        if existing_text in cls.CANONICAL_STORY_STANCES:
            return True
        if existing_text in cls.GENERIC_ROLE_POSITIONS and new_value not in cls.GENERIC_ROLE_POSITIONS:
            return True
        return False

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
        description = self._stringify_import_value(
            char_data.get("description")
            or char_data.get("mainline_role")
        )
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
        default_story_stance: str = "",
        default_role_position: str = "",
    ) -> str:
        """把拆书人物分析整理成更适合创作复用的人物档案。"""
        aliases = self._collect_import_character_aliases(char_data, mention_info, canonical_name)
        parts: List[str] = []
        relation_to_main = self._stringify_import_value(char_data.get("relationship_to_main"))
        role_position = self._normalize_role_position_value(
            char_data.get("role_position"),
            relationship_to_main=relation_to_main,
            fallback=default_role_position,
        )
        story_stance = self._infer_story_stance(
            explicit_stance=char_data.get("story_stance"),
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

        faction = self._stringify_import_value(char_data.get("faction"))
        appearance = self._stringify_import_value(char_data.get("appearance_anchor"))
        personality = self._stringify_import_value(char_data.get("personality_anchor"))
        worldview = self._stringify_import_value(char_data.get("worldview"))
        background = self._stringify_import_value(char_data.get("background_status"))
        motivation = self._stringify_import_value(char_data.get("motivation"))
        abilities = self._stringify_import_value(char_data.get("ability_outline"))
        limitation = self._stringify_import_value(char_data.get("limitation"))
        growth_direction = self._stringify_import_value(char_data.get("growth_direction"))
        mainline_role = self._stringify_import_value(char_data.get("mainline_role"))
        mainline_clues = self._stringify_import_value(char_data.get("mainline_clues"))

        if aliases:
            parts.append(f"别名/称呼: {'、'.join(aliases)}")

        relationship_lines: List[str] = []
        if relation_to_main:
            relationship_lines.append(f"与主角：{relation_to_main}")
        for relation in relationship_entries:
            target = self._stringify_import_value(relation.get("target"))
            relation_type = self._stringify_import_value(relation.get("type")) or "关联"
            description = self._stringify_import_value(relation.get("description"))
            if target and description:
                relationship_lines.append(f"{target}（{relation_type}）：{description}")
            elif target:
                relationship_lines.append(f"{target}（{relation_type}）")
        relationship_text = "；".join(
            list(dict.fromkeys([line for line in relationship_lines if line]))
        )

        field_pairs = [
            ("【故事立场】", story_stance),
            ("【角色定位】", role_position),
            ("【所属势力】", "" if faction == "未提及" else faction),
            ("【外貌锚点】", appearance),
            ("【性格锚点】", _build_personality_anchor_text(personality, worldview)),
            ("【背景/当前处境】", background),
            ("【核心动机】", motivation),
            ("【能力与限制】", _build_ability_and_limit_text(abilities, limitation)),
            ("【关键关系】", relationship_text),
            ("【主线绑定】", _build_mainline_binding_text(mainline_role, mainline_clues)),
            ("【成长方向】", growth_direction),
        ]
        for label, text_value in field_pairs:
            if text_value:
                parts.append(f"{label}：{text_value}")

        first_chapter = mention_info.get("first_appearance_chapter") or char_data.get("first_appearance_chapter")
        if first_chapter:
            parts.append(f"首次出场: 第{first_chapter}章")

        appearance_count = mention_info.get("count")
        if appearance_count:
            parts.append(f"拆书识别出场次数: {appearance_count}")

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

        raw_personality = char_data.get("personality_anchor")
        if isinstance(raw_personality, list):
            for item in raw_personality:
                value = str(item or "").strip()
                if value and value not in tags:
                    tags.append(value)
        else:
            value = str(raw_personality or "").strip()
            if value and value not in {"未提及", "待补充"} and value not in tags:
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
