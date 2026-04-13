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
from app.services.character_parser import (
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    infer_story_stance_from_text_evidence,
)
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
    CANONICAL_STORY_STANCES = frozenset({"主角方", "反派方", "中立方", "亦正亦邪"})
    CANONICAL_ROLE_POSITIONS = frozenset({
        "主角",
        "盟友",
        "导师",
        "对手",
        "守护者",
        "情报角色",
        "中立角色",
        "摇摆角色",
        "治疗者",
        "首领",
        "受害者",
        "主线角色",
        "功能角色",
    })
    GENERIC_ROLE_POSITIONS = frozenset({"盟友", "对手", "中立角色", "摇摆角色", "主线角色", "功能角色"})
    
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

    @staticmethod
    def _try_parse_json_text(raw_text: Any) -> Optional[Any]:
        """尽量从原始文本中解析出 JSON。"""
        if not isinstance(raw_text, str):
            return None

        text = raw_text.strip()
        if not text:
            return None

        candidates = [text]

        code_block_match = re.search(r"```json\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if code_block_match:
            candidates.append(code_block_match.group(1).strip())

        brace_match = re.search(r"\{[\s\S]*\}", text)
        if brace_match:
            candidates.append(brace_match.group(0).strip())

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        return None

    @staticmethod
    def _extract_json_string_field(raw_text: str, field_name: str) -> str:
        """从近似 JSON 文本中提取字符串字段。"""
        if not raw_text:
            return ""

        match = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            raw_text,
        )
        if not match:
            return ""

        try:
            return json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            return match.group(1).strip()

    @classmethod
    def _extract_json_objects_from_array_field(cls, raw_text: str, field_name: str) -> List[Dict[str, Any]]:
        """从截断的 JSON 数组中提取已经完整闭合的对象。"""
        if not raw_text:
            return []

        field_match = re.search(rf'"{re.escape(field_name)}"\s*:\s*\[', raw_text)
        if not field_match:
            return []

        array_text = raw_text[field_match.end():]
        objects: List[Dict[str, Any]] = []
        depth = 0
        start_index: Optional[int] = None
        in_string = False
        escape = False

        for index, char in enumerate(array_text):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "{":
                if depth == 0:
                    start_index = index
                depth += 1
                continue

            if char == "}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start_index is not None:
                    candidate = array_text[start_index:index + 1]
                    parsed = cls._try_parse_json_text(candidate)
                    if isinstance(parsed, dict):
                        objects.append(parsed)
                    start_index = None
                continue

            if char == "]" and depth == 0:
                break

        return objects

    def _recover_plot_content_from_analysis(self, analysis: Optional[BookAnalysis]) -> Dict[str, Any]:
        """在 plot 解析失败时，尽量从原始响应预览中恢复关键结构。"""
        if not analysis:
            return {}

        content = self._decode_json_field(getattr(analysis, "content", None), {})
        if isinstance(content, dict) and content and not content.get("parse_error"):
            return content

        extra_data = self._decode_json_field(getattr(analysis, "extra_data", None), {})
        raw_candidates: List[str] = []

        if isinstance(content, dict):
            raw_response = content.get("raw_response")
            if isinstance(raw_response, str) and raw_response.strip():
                raw_candidates.append(raw_response)

        if isinstance(extra_data, dict):
            for key in ("raw_response", "raw_response_preview"):
                raw_text = extra_data.get(key)
                if isinstance(raw_text, str) and raw_text.strip():
                    raw_candidates.append(raw_text)

        for raw_text in raw_candidates:
            parsed = self._try_parse_json_text(raw_text)
            if isinstance(parsed, dict) and parsed:
                logger.warning("plot分析包含 parse_error 标记，已从原始响应中恢复完整 JSON")
                return parsed

        recovered: Dict[str, Any] = {}
        for raw_text in raw_candidates:
            main_plot = self._extract_json_string_field(raw_text, "main_plot")
            if main_plot and not self._normalize_memory_text(recovered.get("main_plot")):
                recovered["main_plot"] = main_plot

            for field_name in ("plot_arcs", "turning_points"):
                if recovered.get(field_name):
                    continue
                items = self._extract_json_objects_from_array_field(raw_text, field_name)
                if items:
                    recovered[field_name] = items

        if recovered:
            logger.warning("plot分析包含 parse_error 标记，已从原始响应预览中恢复部分结构")

        return recovered

    def _build_plot_fallback_content_from_chapters(self, book_id: int) -> Dict[str, Any]:
        """基于章节摘要生成最小可用的大纲结构。"""
        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

        chapter_snapshots: List[Dict[str, Any]] = []
        for chapter in book_chapters:
            summary = str(chapter.summary or "").strip()

            if not summary:
                outline_data = self._decode_json_field(chapter.outline_data, {})
                if isinstance(outline_data, dict):
                    summary = self._normalize_memory_text(
                        outline_data.get("core_summary") or outline_data.get("scene_goal")
                    )
                    if not summary:
                        ending_hook = outline_data.get("ending_hook")
                        if isinstance(ending_hook, dict):
                            summary = self._normalize_memory_text(
                                ending_hook.get("content")
                                or ending_hook.get("summary")
                                or ending_hook.get("hook")
                            )

            if not summary:
                summary = str(chapter.title or "").strip()

            if not summary:
                continue

            chapter_snapshots.append(
                {
                    "chapter": chapter.chapter_number,
                    "summary": summary,
                }
            )

        if not chapter_snapshots:
            main_plot = "拆书情节分析解析失败，当前已回退为最小可用大纲，建议重新提取以获得更完整的情节脉络。"
            return {
                "main_plot": main_plot,
                "concept": {"summary": main_plot},
                "plot_arcs": [
                    {
                        "name": "主线推进",
                        "description": "当前仅保留兜底大纲，后续可重新执行情节分析补全主线、转折与结局设计。",
                        "type": "兜底",
                    }
                ],
                "turning_points": [],
                "chapter_summaries": [],
            }

        first_snapshot = chapter_snapshots[0]
        last_snapshot = chapter_snapshots[-1]

        if first_snapshot["chapter"] == last_snapshot["chapter"]:
            main_plot = f"故事围绕第{first_snapshot['chapter']}章展开：{first_snapshot['summary']}"
        else:
            main_plot = (
                f"故事从第{first_snapshot['chapter']}章的“{first_snapshot['summary']}”展开，"
                f"并逐步推进至第{last_snapshot['chapter']}章的“{last_snapshot['summary']}”。"
            )

        plot_arcs: List[Dict[str, Any]] = [
            {
                "name": "开篇引子",
                "description": first_snapshot["summary"],
                "chapters": [first_snapshot["chapter"], first_snapshot["chapter"]],
                "type": "开端",
            }
        ]

        if len(chapter_snapshots) >= 3:
            middle_snapshot = chapter_snapshots[len(chapter_snapshots) // 2]
            if middle_snapshot["chapter"] not in {first_snapshot["chapter"], last_snapshot["chapter"]}:
                plot_arcs.append(
                    {
                        "name": "中段升级",
                        "description": middle_snapshot["summary"],
                        "chapters": [middle_snapshot["chapter"], middle_snapshot["chapter"]],
                        "type": "发展",
                    }
                )

        if last_snapshot["chapter"] != first_snapshot["chapter"]:
            plot_arcs.append(
                {
                    "name": "结局收束",
                    "description": last_snapshot["summary"],
                    "chapters": [last_snapshot["chapter"], last_snapshot["chapter"]],
                    "type": "结局",
                }
            )
        else:
            plot_arcs[0]["name"] = "主线推进"
            plot_arcs[0]["type"] = "主线"

        candidate_indices = [0]
        if len(chapter_snapshots) >= 4:
            candidate_indices.extend([len(chapter_snapshots) // 3, (len(chapter_snapshots) * 2) // 3])
        elif len(chapter_snapshots) >= 3:
            candidate_indices.append(len(chapter_snapshots) // 2)
        if len(chapter_snapshots) >= 2:
            candidate_indices.append(len(chapter_snapshots) - 1)

        turning_points: List[Dict[str, Any]] = []
        labels = ["故事开端", "局势升级", "关键转折", "结局收束"]
        unique_indices: List[int] = []
        seen_indices = set()
        for index in candidate_indices:
            normalized_index = max(0, min(index, len(chapter_snapshots) - 1))
            if normalized_index in seen_indices:
                continue
            seen_indices.add(normalized_index)
            unique_indices.append(normalized_index)

        for label, index in zip(labels, unique_indices):
            snapshot = chapter_snapshots[index]
            turning_points.append(
                {
                    "chapter": snapshot["chapter"],
                    "event": snapshot["summary"],
                    "significance": label,
                }
            )

        chapter_summaries = [
            f"第{snapshot['chapter']}章：{snapshot['summary']}"
            for snapshot in chapter_snapshots[:12]
        ]

        return {
            "main_plot": main_plot,
            "concept": {"summary": main_plot},
            "plot_arcs": plot_arcs,
            "turning_points": turning_points,
            "chapter_summaries": chapter_summaries,
        }

    def _merge_plot_content(self, primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        """用章节级兜底补齐 plot 核心字段，确保大纲可生成。"""
        merged = dict(primary or {})

        if not self._normalize_memory_text(merged.get("main_plot")):
            merged["main_plot"] = fallback.get("main_plot", "")

        for field_name in ("plot_arcs", "turning_points", "chapter_summaries"):
            current_value = merged.get(field_name)
            if isinstance(current_value, list) and current_value:
                continue
            fallback_value = fallback.get(field_name) or []
            if fallback_value:
                merged[field_name] = fallback_value

        concept = merged.get("concept")
        fallback_concept = fallback.get("concept")
        if not isinstance(concept, dict):
            if isinstance(fallback_concept, dict) and fallback_concept:
                merged["concept"] = dict(fallback_concept)
        elif isinstance(fallback_concept, dict):
            summary = self._normalize_memory_text(concept.get("summary"))
            if not summary:
                fallback_summary = self._normalize_memory_text(fallback_concept.get("summary"))
                if fallback_summary:
                    concept["summary"] = fallback_summary

        return merged

    def _load_plot_content_with_fallback(
        self,
        analysis_map: Dict[str, BookAnalysis],
        book_id: int,
    ) -> Dict[str, Any]:
        """为 plot 提供恢复与兜底后的可用结构。"""
        analysis = analysis_map.get("plot")
        if not analysis:
            return {}

        fallback = self._build_plot_fallback_content_from_chapters(book_id)
        content = self._load_analysis_content(analysis_map, "plot")
        if isinstance(content, dict) and content:
            return self._merge_plot_content(content, fallback)

        recovered = self._recover_plot_content_from_analysis(analysis)
        if recovered:
            logger.warning("plot分析解析失败，已使用原始响应恢复并补齐大纲内容")
        else:
            logger.warning("plot分析解析失败，已使用章节摘要生成最小可用大纲")

        return self._merge_plot_content(recovered, fallback)

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
            return len(self._get_character_entries(content))
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

    @staticmethod
    def _parse_plot_outline_chapter_number(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            chapter_number = int(value)
            return chapter_number if chapter_number > 0 else None

        match = re.search(r"\d+", str(value))
        if not match:
            return None

        chapter_number = int(match.group(0))
        return chapter_number if chapter_number > 0 else None

    @classmethod
    def _normalize_plot_outline_title(cls, value: Any, *, default: str) -> str:
        title = str(value or "").strip()
        title = re.sub(
            r"^第\s*[0-9一二三四五六七八九十百千两零〇]+\s*章[：:\-\s]*",
            "",
            title,
        ).strip()
        title = title.strip("《》【】[]()（）-:： ")
        title = re.split(r"[。！？!?；;\n]", title)[0].strip()
        title = cls._clean_memory_line(title, max_length=24)
        return title or default

    @classmethod
    def _normalize_plot_outline_item_list(cls, value: Any, *, limit: int = 6) -> List[str]:
        raw_items = value if isinstance(value, list) else [value]
        items: List[str] = []

        for raw_item in raw_items:
            if isinstance(raw_item, dict):
                text_parts = [
                    cls._normalize_memory_text(raw_item.get(key))
                    for key in ("content", "description", "summary", "event", "name")
                ]
                text = "；".join(part for part in text_parts if part)
            else:
                text = cls._normalize_memory_text(raw_item)

            if not text:
                continue

            for line in str(text).splitlines():
                normalized = re.sub(r"^\d+\s*[.、]\s*", "", line.strip())
                if normalized:
                    items.append(normalized)

        return cls._deduplicate_memory_items(items, limit=limit)

    @classmethod
    def _format_book_parser_conflict_design(cls, conflict_arc: Any, fallback: Any = "") -> str:
        fallback_text = cls._normalize_memory_text(fallback)
        if fallback_text:
            return fallback_text

        if not isinstance(conflict_arc, dict):
            return cls._normalize_memory_text(conflict_arc)

        pieces: List[str] = []
        for key, label in (
            ("type", "冲突类型"),
            ("trigger", "起因"),
            ("escalation", "升级"),
            ("resolution", "结果"),
            ("result", "结果"),
            ("description", "说明"),
            ("stakes", "代价"),
            ("obstacle", "阻碍"),
        ):
            text = cls._normalize_memory_text(conflict_arc.get(key))
            if text:
                pieces.append(f"{label}：{text}")

        return "；".join(dict.fromkeys(pieces))

    @classmethod
    def _format_book_parser_highlight(cls, highlight: Any) -> str:
        if not isinstance(highlight, dict):
            return cls._normalize_memory_text(highlight)

        type_text = cls._normalize_memory_text(highlight.get("type"))
        description = cls._normalize_memory_text(
            highlight.get("description") or highlight.get("content")
        )
        intensity = cls._normalize_memory_text(highlight.get("intensity"))

        parts: List[str] = []
        if type_text and type_text != "无":
            parts.append(type_text)
        if description:
            parts.append(f"内容：{description}")
        if intensity and intensity not in {"0", "无"}:
            parts.append(f"强度：{intensity}")

        if parts:
            return "；".join(parts)
        return type_text

    @classmethod
    def _format_book_parser_ending_hook(cls, ending_hook: Any) -> str:
        if not isinstance(ending_hook, dict):
            return cls._normalize_memory_text(ending_hook)

        hook_type = cls._normalize_memory_text(ending_hook.get("type"))
        hook_content = cls._normalize_memory_text(
            ending_hook.get("content")
            or ending_hook.get("summary")
            or ending_hook.get("hook")
        )

        if hook_type and hook_type != "无" and hook_content:
            return f"{hook_type} / {hook_content}"
        return hook_content or hook_type

    @classmethod
    def _format_book_parser_gains(cls, gains: Any, *, prefer: str) -> str:
        if not isinstance(gains, dict):
            return cls._normalize_memory_text(gains)

        character_gains = cls._normalize_memory_text(
            gains.get("character_gains")
            or gains.get("character_growth")
            or gains.get("relationship_change")
            or gains.get("status_change")
        )
        plot_progress = cls._normalize_memory_text(
            gains.get("plot_progress")
            or gains.get("information_gain")
            or gains.get("clue_progress")
        )

        if prefer == "character":
            return character_gains or plot_progress
        if prefer == "information":
            parts: List[str] = []
            if character_gains:
                parts.append(f"角色收获：{character_gains}")
            if plot_progress:
                parts.append(f"主线推进：{plot_progress}")
            if parts:
                return "；".join(parts)

        fallback_parts = [
            cls._normalize_memory_text(value)
            for value in gains.values()
        ]
        fallback_parts = [part for part in fallback_parts if part]
        return "；".join(dict.fromkeys(fallback_parts))

    @classmethod
    def _infer_plot_outline_function(
        cls,
        chapter_index: int,
        total_chapters: int,
        *,
        has_hook: bool,
        has_foreshadowing: bool,
    ) -> str:
        if total_chapters <= 1:
            return "概括当前章节的核心推进，并为后续延展保留空间。"
        if chapter_index == 0:
            return "开篇立题，建立基础局势与核心矛盾。"
        if chapter_index == total_chapters - 1:
            return "阶段收束并抛出后续升级钩子。" if has_hook else "阶段收束，完成当前阶段结果交代。"
        if has_hook or has_foreshadowing:
            return "承接前文并推进主线，同时埋设后续升级点。"
        return "承接前文并推进当前主线。"

    def _build_plot_outline_blocks_from_book_chapters(self, book_id: int) -> List[Dict[str, Any]]:
        book_chapters = self.db.query(BookChapter).filter(
            BookChapter.book_id == book_id
        ).order_by(BookChapter.chapter_number).all()

        total_chapters = len(book_chapters)
        blocks: List[Dict[str, Any]] = []

        for index, chapter in enumerate(book_chapters):
            outline_data = self._decode_json_field(chapter.outline_data, {})
            outline_data = outline_data if isinstance(outline_data, dict) else {}

            summary = self._normalize_memory_text(chapter.summary)
            key_events = self._normalize_plot_outline_item_list(
                self._decode_json_field(chapter.key_events, [])
            )
            appearing_characters = self._normalize_plot_outline_item_list(
                self._decode_json_field(chapter.appearing_characters, [])
            )

            scene_goal = self._normalize_memory_text(outline_data.get("scene_goal")) or summary
            if not scene_goal:
                scene_goal = f"围绕第{chapter.chapter_number}章核心事件推进当前主线。"

            conflict_design = self._format_book_parser_conflict_design(
                outline_data.get("conflict_arc"),
                fallback=outline_data.get("conflict"),
            )
            highlight_type = self._format_book_parser_highlight(outline_data.get("highlight")) or "待补充"
            involved_characters = "、".join(appearing_characters) or "待补充"
            character_progress = self._format_book_parser_gains(
                outline_data.get("gains"),
                prefer="character",
            )
            plot_progress_hint = self._format_book_parser_gains(
                outline_data.get("gains"),
                prefer="information",
            )
            ending_hook = self._format_book_parser_ending_hook(outline_data.get("ending_hook")) or "无"
            foreshadowing_item = "；".join(
                self._normalize_plot_outline_item_list(outline_data.get("foreshadowing"))
            ) or "无"

            if not key_events and summary:
                key_events = [summary]

            if not conflict_design:
                conflict_design = summary or scene_goal
            if not character_progress:
                if involved_characters != "待补充":
                    character_progress = f"{involved_characters}在本章的状态或关系出现推进。"
                else:
                    character_progress = "主角与关键角色的状态出现阶段性变化。"
            plot_function = self._normalize_memory_text(outline_data.get("plot_function"))
            if not plot_function:
                plot_function = plot_progress_hint or self._infer_plot_outline_function(
                    index,
                    total_chapters,
                    has_hook=ending_hook != "无",
                    has_foreshadowing=foreshadowing_item != "无",
                )

            blocks.append(
                {
                    "chapter_number": int(chapter.chapter_number or index + 1),
                    "title": self._normalize_plot_outline_title(
                        chapter.title,
                        default=f"章节推进{chapter.chapter_number or index + 1}",
                    ),
                    "scene_goal": scene_goal,
                    "conflict_design": conflict_design,
                    "highlight_type": highlight_type,
                    "involved_characters": involved_characters,
                    "character_progress": character_progress,
                    "plot_function": plot_function,
                    "ending_hook": ending_hook,
                    "foreshadowing_item": foreshadowing_item,
                    "key_events": key_events,
                }
            )

        return blocks

    def _build_plot_outline_blocks_from_plot_content(self, content: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(content, dict) or not content:
            return []

        main_plot = self._normalize_memory_text(content.get("main_plot"))
        if not main_plot:
            concept = content.get("concept") or {}
            if isinstance(concept, dict):
                main_plot = self._normalize_memory_text(
                    concept.get("summary") or concept.get("logline")
                )

        blocks_by_chapter: Dict[int, Dict[str, Any]] = {}

        def ensure_block(chapter_number: int, default_title: str) -> Dict[str, Any]:
            block = blocks_by_chapter.setdefault(
                chapter_number,
                {
                    "chapter_number": chapter_number,
                    "title": "",
                    "scene_goal": "",
                    "conflict_design": "",
                    "highlight_type": "",
                    "involved_characters": "",
                    "character_progress": "",
                    "plot_function": "",
                    "ending_hook": "",
                    "foreshadowing_item": "",
                    "key_events": [],
                },
            )
            if default_title and not block["title"]:
                block["title"] = default_title
            return block

        chapter_summaries = content.get("chapter_summaries") or []
        for index, raw_item in enumerate(chapter_summaries, start=1):
            if isinstance(raw_item, dict):
                chapter_number = (
                    self._parse_plot_outline_chapter_number(
                        raw_item.get("chapter") or raw_item.get("chapter_number")
                    )
                    or index
                )
                summary_text = self._normalize_memory_text(
                    raw_item.get("summary")
                    or raw_item.get("content")
                    or raw_item.get("title")
                )
                title_source = raw_item.get("title") or summary_text
            else:
                summary_text = self._normalize_memory_text(raw_item)
                if not summary_text:
                    continue
                match = re.match(r"^第\s*(\d+)\s*章[：:]\s*(.+)$", summary_text)
                if match:
                    chapter_number = int(match.group(1))
                    summary_text = match.group(2).strip()
                else:
                    chapter_number = index
                title_source = summary_text

            if not summary_text:
                continue

            block = ensure_block(
                chapter_number,
                self._normalize_plot_outline_title(
                    title_source,
                    default=f"章节推进{chapter_number}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = summary_text
            if not block["plot_function"]:
                block["plot_function"] = summary_text or "概括该章节的阶段推进与结果。"
            if not block["key_events"]:
                block["key_events"].append(summary_text)

        normalized_turning_points: List[Dict[str, Any]] = []
        for index, raw_turning_point in enumerate(content.get("turning_points") or [], start=1):
            turning_point = raw_turning_point if isinstance(raw_turning_point, dict) else {"event": raw_turning_point}
            event_text = self._normalize_memory_text(turning_point.get("event"))
            significance = self._normalize_memory_text(turning_point.get("significance"))
            if not event_text and not significance:
                continue

            chapter_number = self._parse_plot_outline_chapter_number(turning_point.get("chapter")) or index
            block = ensure_block(
                chapter_number,
                self._normalize_plot_outline_title(
                    event_text or significance,
                    default=f"关键转折{index}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = event_text or significance or main_plot
            if not block["conflict_design"]:
                block["conflict_design"] = significance or event_text or main_plot
            if not block["highlight_type"]:
                block["highlight_type"] = "关键转折 / 局势升级"
            if not block["plot_function"]:
                block["plot_function"] = significance or "推动主线进入下一阶段。"
            if event_text:
                block["key_events"].append(event_text)

            normalized_turning_points.append(
                {
                    "chapter_number": chapter_number,
                    "event": event_text,
                    "significance": significance,
                }
            )

        for index, item in enumerate(normalized_turning_points):
            block = blocks_by_chapter.get(item["chapter_number"])
            if not block or block["ending_hook"]:
                continue
            next_event = ""
            if index + 1 < len(normalized_turning_points):
                next_event = normalized_turning_points[index + 1]["event"]
            block["ending_hook"] = next_event or item["significance"] or main_plot

        for index, raw_arc in enumerate(content.get("plot_arcs") or [], start=1):
            arc = raw_arc if isinstance(raw_arc, dict) else {"name": raw_arc}
            arc_name = self._normalize_memory_text(arc.get("name"))
            arc_description = self._normalize_memory_text(arc.get("description"))
            arc_type = self._normalize_memory_text(arc.get("type"))
            chapters = arc.get("chapters") or []
            start_chapter = (
                self._parse_plot_outline_chapter_number(chapters[0])
                if isinstance(chapters, list) and chapters
                else None
            ) or index
            end_chapter = (
                self._parse_plot_outline_chapter_number(chapters[1])
                if isinstance(chapters, list) and len(chapters) >= 2
                else None
            ) or start_chapter

            block = ensure_block(
                start_chapter,
                self._normalize_plot_outline_title(
                    arc_name or arc_description,
                    default=f"主线推进{start_chapter}",
                ),
            )
            if not block["scene_goal"]:
                block["scene_goal"] = arc_description or arc_name or main_plot
            if not block["conflict_design"]:
                block["conflict_design"] = arc_description or arc_type or main_plot
            if not block["highlight_type"]:
                block["highlight_type"] = arc_type or arc_name or "主线推进"
            if not block["plot_function"]:
                plot_function_parts = [part for part in (arc_name, arc_type) if part]
                if end_chapter != start_chapter:
                    plot_function_parts.append(f"覆盖第{start_chapter}-{end_chapter}章")
                block["plot_function"] = " / ".join(plot_function_parts) or "承接前文并推进主线。"
            if not block["ending_hook"] and end_chapter != start_chapter:
                block["ending_hook"] = f"该段剧情将推进至第{end_chapter}章。"

        if not blocks_by_chapter and main_plot:
            block = ensure_block(
                1,
                self._normalize_plot_outline_title(main_plot, default="主线开启"),
            )
            block["scene_goal"] = main_plot
            block["conflict_design"] = main_plot
            block["plot_function"] = main_plot
            block["key_events"].append(main_plot)

        chapter_numbers = sorted(blocks_by_chapter.keys())
        rendered_blocks: List[Dict[str, Any]] = []

        for index, chapter_number in enumerate(chapter_numbers):
            raw_block = blocks_by_chapter[chapter_number]
            next_block = blocks_by_chapter.get(chapter_numbers[index + 1]) if index + 1 < len(chapter_numbers) else None
            scene_goal = raw_block["scene_goal"] or main_plot or f"推进第{chapter_number}章主线。"
            conflict_design = raw_block["conflict_design"] or scene_goal
            ending_hook = raw_block["ending_hook"]
            if not ending_hook and next_block:
                ending_hook = f"下一节点：{next_block['title']}"
            if not ending_hook:
                ending_hook = main_plot or "无"

            rendered_blocks.append(
                {
                    "chapter_number": chapter_number,
                    "title": self._normalize_plot_outline_title(
                        raw_block["title"],
                        default=f"章节推进{chapter_number}",
                    ),
                    "scene_goal": scene_goal,
                    "conflict_design": conflict_design,
                    "highlight_type": raw_block["highlight_type"] or "待补充",
                    "involved_characters": raw_block["involved_characters"] or "待补充",
                    "character_progress": raw_block["character_progress"] or "待补充",
                    "plot_function": raw_block["plot_function"] or self._infer_plot_outline_function(
                        index,
                        len(chapter_numbers),
                        has_hook=bool(ending_hook and ending_hook != "无"),
                        has_foreshadowing=False,
                    ),
                    "ending_hook": ending_hook,
                    "foreshadowing_item": raw_block["foreshadowing_item"] or "无",
                    "key_events": self._deduplicate_memory_items(
                        raw_block["key_events"] or [scene_goal],
                        limit=5,
                    ),
                }
            )

        return rendered_blocks

    def _build_plot_outline_text(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """生成与大纲扩展一致的章节细纲文本。"""
        content = self._load_plot_content_with_fallback(analysis_map, book_id)
        if not isinstance(content, dict) or not content:
            return ""

        main_plot = self._normalize_memory_text(content.get("main_plot"))
        if not main_plot:
            concept = content.get("concept") or {}
            if isinstance(concept, dict):
                main_plot = self._normalize_memory_text(
                    concept.get("summary") or concept.get("logline")
                )

        blocks = self._build_plot_outline_blocks_from_book_chapters(book_id)
        if not blocks:
            blocks = self._build_plot_outline_blocks_from_plot_content(content)

        if not blocks:
            return f"故事总纲：{main_plot}" if main_plot else ""

        parts: List[str] = []
        if main_plot:
            parts.append(f"故事总纲：{main_plot}")
            parts.append("")

        for block in blocks:
            chapter_number = int(block.get("chapter_number") or 0) or 1
            title = self._normalize_plot_outline_title(
                block.get("title"),
                default=f"章节推进{chapter_number}",
            )
            key_events = self._normalize_plot_outline_item_list(
                block.get("key_events"),
                limit=5,
            ) or ["待补充"]
            parts.append(f"第{chapter_number}章：{title}")
            parts.append(f"- 场景目标：{self._normalize_memory_text(block.get('scene_goal')) or '待补充'}")
            parts.append(f"- 冲突设计：{self._normalize_memory_text(block.get('conflict_design')) or '待补充'}")
            parts.append("- 关键事件：")
            for event_index, event in enumerate(key_events, start=1):
                parts.append(f"  {event_index}. {event}")
            parts.append(f"- 涉及人物：{self._normalize_memory_text(block.get('involved_characters')) or '待补充'}")
            parts.append(f"- 人物推进：{self._normalize_memory_text(block.get('character_progress')) or '待补充'}")
            parts.append(f"- 情节作用：{self._normalize_memory_text(block.get('plot_function')) or '待补充'}")
            parts.append(f"- 结尾钩子：{self._normalize_memory_text(block.get('ending_hook')) or '无'}")
            highlight_type = self._normalize_memory_text(block.get('highlight_type'))
            if highlight_type:
                parts.append(f"- 爽点类型：{highlight_type}")
            foreshadowing_item = self._normalize_memory_text(block.get('foreshadowing_item'))
            if foreshadowing_item:
                parts.append(f"- 伏笔事项：{foreshadowing_item}")
            parts.append("")

        return "\n".join(parts).strip()

    def _build_import_structured_memory_payload(
        self,
        analysis_map: Dict[str, BookAnalysis],
        book: BookSource,
    ) -> Optional[Dict[str, Any]]:
        """基于拆书结果构建可直接用于工作流的结构化记忆。"""
        plot_content = self._load_plot_content_with_fallback(analysis_map, book.id)
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
        for char in self._get_character_entries(character_content):
            if not isinstance(char, dict):
                continue
            name = self._normalize_memory_text(char.get('name'))
            if not name:
                continue
            fragments = [name]
            relation_to_main = self._normalize_memory_text(char.get('relationship_to_main'))
            role_position = self._normalize_role_position_value(
                char.get('role_position'),
                relationship_to_main=relation_to_main,
            )
            if role_position:
                fragments.append(f"定位={role_position}")
            stance = self._infer_story_stance(
                explicit_stance=char.get('story_stance'),
                role_position=role_position,
                relationship_to_main=relation_to_main,
                additional_texts=[
                    char.get('description'),
                    char.get('background_status'),
                    char.get('mainline_role'),
                    char.get('growth_direction'),
                ],
            )
            if stance:
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
        plot_content = self._load_plot_content_with_fallback(analysis_map, book.id)
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

        def raw_text(value: Any, separator: str = "、") -> str:
            if value is None:
                return ""
            if isinstance(value, list):
                items = [raw_text(v, separator=separator) for v in value]
                items = [item for item in items if item]
                return separator.join(items)
            if isinstance(value, dict):
                return ""
            return str(value).strip()

        def is_placeholder_text(value: Any, *, allow_not_mentioned: bool = False) -> bool:
            text = raw_text(value)
            if not text:
                return True

            compact = re.sub(r"\s+", "", text).lower()
            placeholders = {
                "待补充",
                "未知",
                "不详",
                "暂无",
                "暂无信息",
                "暂无描写",
                "未说明",
                "未交代",
                "未明确提及",
                "未明确说明",
                "none",
                "null",
                "n/a",
                "na",
            }
            if not allow_not_mentioned:
                placeholders.add("未提及")

            if compact in placeholders:
                return True

            return bool(re.fullmatch(r"[?？.。·•…]+", text))

        def normalize_text(value: Any, *, allow_not_mentioned: bool = False, separator: str = "、") -> str:
            if isinstance(value, list):
                items = [
                    normalize_text(item, allow_not_mentioned=allow_not_mentioned, separator=separator)
                    for item in value
                ]
                items = [item for item in items if item]
                return separator.join(list(dict.fromkeys(items)))

            text = raw_text(value, separator=separator)
            if is_placeholder_text(text, allow_not_mentioned=allow_not_mentioned):
                return ""
            return text

        def pick_first(*values: Any, allow_not_mentioned: bool = False, separator: str = "、") -> str:
            for value in values:
                text_value = normalize_text(
                    value,
                    allow_not_mentioned=allow_not_mentioned,
                    separator=separator,
                )
                if text_value:
                    return text_value
            return ""

        def truncate_text(value: str, limit: int = 36) -> str:
            text = normalize_text(value)
            if not text:
                return ""
            if len(text) <= limit:
                return text
            return text[: limit - 3].rstrip("，。；; ") + "..."

        def extract_action_phrase(text: str) -> str:
            patterns = [
                r"(追查[^，。；]{2,30})",
                r"(追寻[^，。；]{2,30})",
                r"(寻找[^，。；]{2,30})",
                r"(调查[^，。；]{2,30})",
                r"(揭开[^，。；]{2,30})",
                r"(查明[^，。；]{2,30})",
                r"(保护[^，。；]{2,30})",
                r"(守护[^，。；]{2,30})",
                r"(营救[^，。；]{2,30})",
                r"(反抗[^，。；]{2,30})",
                r"(阻止[^，。；]{2,30})",
                r"(夺回[^，。；]{2,30})",
                r"(掌控[^，。；]{2,30})",
                r"(复仇[^，。；]{2,30})",
            ]
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return truncate_text(match.group(1), 28)
            return ""

        def resolve_character_display_fields(
            char_data: Dict[str, Any],
            *,
            default_story_stance: str,
            default_role_position: str,
        ) -> tuple[str, str]:
            relation_to_main = pick_first(char_data.get('relationship_to_main'))
            role_position = self._normalize_role_position_value(
                char_data.get('role_position'),
                relationship_to_main=relation_to_main,
                fallback=default_role_position,
            )
            story_stance = self._infer_story_stance(
                explicit_stance=char_data.get('story_stance'),
                role_position=role_position,
                relationship_to_main=relation_to_main,
                fallback=default_story_stance,
                additional_texts=[
                    char_data.get('description'),
                    char_data.get('background_status'),
                    char_data.get('mainline_role'),
                    char_data.get('growth_direction'),
                ],
            )
            return story_stance, role_position

        def infer_motivation(description: str, mainline_role: str, relation_to_main: str, role_text: str) -> str:
            action_phrase = extract_action_phrase("；".join(filter(None, [description, mainline_role, relation_to_main])))
            if action_phrase:
                return action_phrase
            if relation_to_main:
                return f"围绕{truncate_text(relation_to_main, 18)}作出关键行动选择"
            if mainline_role:
                return f"其个人目标与{truncate_text(mainline_role, 18)}直接相关"
            if role_text == "主角":
                return "主动追索主线真相并推动事件进展"
            if role_text == "对手":
                return "维护自身立场并阻断主角推进"
            return "围绕主线冲突作出选择并影响局势"

        def infer_abilities(description: str, relation_to_main: str, role_text: str) -> str:
            source = "；".join(filter(None, [description, relation_to_main]))
            ability_rules = [
                (("工程师", "技术", "程序", "黑客", "接口", "系统", "数据分析"), "技术分析、系统操作与信息处理"),
                (("研究员", "科学家", "实验"), "研究分析与实验推进"),
                (("医生", "医师", "诊所", "治疗"), "医疗救治与应急判断"),
                (("警察", "警员", "军", "特工", "队长", "执法", "安保"), "战术执行、追踪与正面压制"),
                (("记者", "调查员", "调查"), "调查取证与信息整合"),
                (("首领", "负责人", "指挥", "组织", "抵抗"), "组织协调、资源调度与行动策划"),
                (("觉醒", "异能", "能力"), "特殊能力运用与高风险行动"),
            ]
            for keywords, text in ability_rules:
                if any(keyword in source for keyword in keywords):
                    return text
            if role_text == "对手":
                return "资源调动与局势压制能力"
            return "与主线任务相关的执行与应变能力"

        def infer_limitation(description: str, relation_to_main: str, role_text: str) -> str:
            source = "；".join(filter(None, [description, relation_to_main]))
            if any(keyword in source for keyword in ("真相", "追查", "追寻", "调查", "复仇", "执念")):
                return "对目标投入过深，关键节点容易冒险"
            if any(keyword in source for keyword in ("威胁", "胁迫", "受制", "被迫")):
                return "受外部压力牵制，立场稳定性有限"
            if role_text == "对手":
                return "立场强硬，容易低估对手与变量"
            if role_text == "主角":
                return "情感与目标绑定过深，容易承担过高风险"
            return "受立场、资源或情绪牵制，行动存在代价"

        def infer_growth_direction(mainline_role: str, relation_to_main: str, role_text: str) -> str:
            if role_text == "主角":
                return "从被动卷入事件，到主动追查真相并承担核心抉择"
            if role_text == "对手":
                return "从单纯阻力角色，逐步成为主线价值冲突的关键对照"
            if relation_to_main:
                return f"从{truncate_text(relation_to_main, 16)}的位置出发，逐步影响主线走向"
            if mainline_role:
                return "随着主线推进，其立场与选择不断被重新定义"
            return "在主线冲突中完成立场与关系的调整"

        def infer_age_gender(description: str, background: str, relation_to_main: str) -> str:
            source = "；".join(filter(None, [description, background, relation_to_main]))
            age_value = ""
            gender_value = ""

            age_rules = [
                ("少女", "少女"),
                ("少年", "少年"),
                ("青年", "青年"),
                ("年轻", "青年"),
                ("中年", "中年"),
                ("老人", "老年"),
                ("奶奶", "老年"),
            ]
            gender_rules = [
                ("母亲", "女性"),
                ("姐姐", "女性"),
                ("妹妹", "女性"),
                ("女士", "女性"),
                ("奶奶", "女性"),
                ("父亲", "男性"),
                ("哥哥", "男性"),
                ("弟弟", "男性"),
                ("男孩", "男性"),
                ("女孩", "女性"),
            ]

            for keyword, value in age_rules:
                if keyword in source:
                    age_value = value
                    break
            for keyword, value in gender_rules:
                if keyword in source:
                    gender_value = value
                    break

            if age_value and gender_value:
                return f"{age_value}/{gender_value}"
            return age_value or gender_value

        def infer_appearance(description: str, background: str, personality: str) -> str:
            source = "；".join(filter(None, [description, background, personality]))
            rules = [
                (("工程师", "系统", "接口", "数据"), "气质冷静克制，带长期高压工作的疲惫感"),
                (("医生", "诊疗", "医疗"), "衣着整洁利落，举止带有职业性的克制感"),
                (("高层", "局长", "负责人", "首领"), "仪表严整，带有长期掌控局势的压迫感"),
                (("地下", "黑市", "抵抗"), "装束偏低调实用，神情警惕而锋利"),
                (("老人", "老周", "奶奶"), "带有岁月沉淀感，神情沉稳而略显疲惫"),
            ]
            for keywords, text in rules:
                if any(keyword in source for keyword in keywords):
                    return text
            return "外在特征以身份气质为主，缺少明确细节描写"

        def infer_worldview(description: str, background: str, motivation: str, story_stance: str, faction: str) -> str:
            source = "；".join(filter(None, [description, background, motivation, story_stance, faction]))
            if any(keyword in source for keyword in ("真相", "自由", "自主", "主权", "揭露", "反抗")):
                return "倾向真相优先与个体记忆自主"
            if any(keyword in source for keyword in ("稳定", "秩序", "系统", "控制")):
                return "倾向秩序优先，但在控制与伦理间摇摆"
            if any(keyword in source for keyword in ("救治", "保护", "守护", "修复")):
                return "重视生命伦理、修复与个体保护"
            if story_stance:
                return f"立场偏向{story_stance}"
            return "在生存、伦理与真相之间不断权衡"

        def build_mainline_clues(char_data: Dict[str, Any], description: str, relation_to_main: str) -> str:
            parts: List[str] = []
            first_appearance = char_data.get('first_appearance_chapter')
            appearance_count = char_data.get('appearance_count')
            if isinstance(first_appearance, int) and first_appearance > 0:
                parts.append(f"首次在第{first_appearance}章出场")
            if isinstance(appearance_count, int) and appearance_count > 0:
                parts.append(f"累计出场{appearance_count}章")
            if relation_to_main:
                parts.append(f"与主角关系：{truncate_text(relation_to_main, 18)}")
            if description:
                parts.append(f"关键事件指向：{truncate_text(description, 24)}")
            deduped = list(dict.fromkeys([part for part in parts if part]))
            return "；".join(deduped)

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
            return normalize_text(value) or "待补充"

        def append_character_card(
            target: List[str],
            char_data: Dict[str, Any],
            story_stance_text: str,
            role_text: str,
        ) -> None:
            name = normalize_text(char_data.get('name')) or "待补充"
            age_gender = pick_first(char_data.get('age_gender'), char_data.get('age'), char_data.get('gender'))
            appearance = pick_first(char_data.get('appearance_anchor'))
            personality = pick_first(char_data.get('personality_anchor'))
            background = pick_first(char_data.get('background_status'))
            worldview = pick_first(char_data.get('worldview'))
            description = pick_first(char_data.get('description'))
            relation_to_main = pick_first(char_data.get('relationship_to_main'))
            mainline_role = pick_first(char_data.get('mainline_role'), description, relation_to_main)
            motivation = pick_first(char_data.get('motivation'))
            story_stance = story_stance_text or pick_first(char_data.get('story_stance'), allow_not_mentioned=True)
            faction = pick_first(char_data.get('faction'), allow_not_mentioned=True)
            abilities = pick_first(char_data.get('ability_outline'))
            limitation = pick_first(char_data.get('limitation'))
            growth_direction = pick_first(char_data.get('growth_direction'))
            mainline_clues = pick_first(char_data.get('mainline_clues'), separator="；")

            relationship_lines: List[str] = []
            if relation_to_main:
                relationship_lines.append(f"与主角：{relation_to_main}")
            relationship_lines.extend(relationship_map.get(name, []))
            relationship_text = "；".join(list(dict.fromkeys([line for line in relationship_lines if line]))) or "待补充"

            if not motivation:
                motivation = infer_motivation(description, mainline_role, relation_to_main, role_text)
            if not age_gender:
                age_gender = infer_age_gender(description, background, relation_to_main)
            if not appearance:
                appearance = infer_appearance(description, background, personality)
            if not worldview:
                worldview = infer_worldview(description, background, motivation, story_stance, faction)
            if not abilities:
                abilities = infer_abilities(description, relation_to_main, role_text)
            if not limitation:
                limitation = infer_limitation(description, relation_to_main, role_text)
            if not growth_direction:
                growth_direction = infer_growth_direction(mainline_role, relation_to_main, role_text)
            if not mainline_clues:
                mainline_clues = build_mainline_clues(char_data, description or mainline_role, relation_to_main)

            target.append(f"### 【姓名】：{name}")
            target.append("")
            target.append(f"【年龄/性别】：{value_or_default(age_gender)}")
            target.append("")
            target.append(f"【故事立场】：{value_or_default(story_stance)}")
            target.append("")
            target.append(f"【角色定位】：{value_or_default(role_text)}")
            target.append("")
            target.append(f"【所属势力】：{value_or_default(faction)}")
            target.append("")
            target.append(f"【外貌锚点】：{value_or_default(appearance)}")
            target.append("")
            target.append(
                f"【性格锚点】：{value_or_default(_build_personality_anchor_text(personality, worldview))}"
            )
            target.append("")
            target.append(f"【背景/当前处境】：{value_or_default(background)}")
            target.append("")
            target.append(f"【核心动机】：{value_or_default(motivation)}")
            target.append("")
            target.append(
                f"【能力与限制】：{value_or_default(_build_ability_and_limit_text(abilities, limitation))}"
            )
            target.append("")
            target.append(f"【关键关系】：{value_or_default(relationship_text)}")
            target.append("")
            target.append(
                f"【主线绑定】：{value_or_default(_build_mainline_binding_text(mainline_role, mainline_clues))}"
            )
            target.append("")
            target.append(f"【成长方向】：{value_or_default(growth_direction)}")
            target.append("")
            target.append("---")
            target.append("")

        parts: List[str] = []
        characters = self._get_character_entries(content)

        groups: Dict[str, List[Any]] = {
            "主角阵营": [],
            "对手阵营": [],
            "支持角色": [],
            "中立角色": [],
            "摇摆角色": [],
        }

        for char in characters:
            is_primary = self._is_primary_character_entry(char)
            story_stance, role_text = resolve_character_display_fields(
                char,
                default_story_stance='',
                default_role_position='主线角色' if is_primary else '功能角色',
            )
            if story_stance == "主角方":
                if role_text == "主角":
                    groups["主角阵营"].append((char, story_stance, role_text))
                else:
                    groups["支持角色"].append((char, story_stance, role_text or "盟友"))
            elif story_stance == "反派方":
                groups["对手阵营"].append((char, story_stance, role_text or "对手"))
            elif story_stance == "中立方":
                groups["中立角色"].append((char, story_stance, role_text or "中立角色"))
            elif story_stance == "亦正亦邪":
                groups["摇摆角色"].append((char, story_stance, role_text or "摇摆角色"))
            else:
                groups["支持角色"].append((char, story_stance, role_text or "盟友"))

        for group_name, entries in groups.items():
            if not entries:
                continue
            parts.append(f"## {group_name}")
            parts.append("")
            for char_data, story_stance_text, role_text in entries:
                append_character_card(parts, char_data, story_stance_text, role_text)

        return "\n".join(parts).strip()

    def _build_plot_outline_text_legacy(self, analysis_map: Dict[str, BookAnalysis], book_id: int) -> str:
        """旧版总览式情节大纲生成逻辑，保留仅供定位对比。"""
        content = self._load_plot_content_with_fallback(analysis_map, book_id)
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
