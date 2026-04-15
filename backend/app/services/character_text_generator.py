"""
人物卡文本生成服务
将结构化人物数据转换为工作流可用的文本格式
"""
import json
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.character import Character
from app.services.character_parser import (
    CharacterTextParser,
    ParsedCharacter,
    _build_ability_and_limit_text,
    _build_mainline_binding_text,
    _build_personality_anchor_text,
    _extract_prefixed_character_value,
)


class CharacterTextGenerator:
    """人物卡文本生成器"""
    
    # 重要程度映射
    IMPORTANCE_MAP = {
        "主角": "主角",
        "核心角色": "核心角色",
        "重要角色": "重要角色",
        "次要角色": "次要角色",
        "边缘角色": "边缘角色",
        "群众角色": "群众角色",
    }
    
    # 角色立场映射
    ROLE_MAP = {
        "主角方": "主角方",
        "反派方": "反派方",
        "中立方": "中立方",
        "亦正亦邪": "亦正亦邪",
        "protagonist": "主角方",
        "ally": "主角方",
        "supporting": "主角方",
        "antagonist": "反派方",
        "enemy": "反派方",
        "neutral": "中立方",
        "ambiguous": "亦正亦邪",
    }
    
    # 出场状态映射
    APPEARANCE_STATUS_MAP = {
        "not_appeared": "未出场",
        "appeared": "已出场",
        "exited": "已退场",
    }
    
    # 生死状态映射
    LIFE_STATUS_MAP = {
        "alive": "存活",
        "dead": "死亡",
        "missing": "失踪",
        "unknown": "未知",
    }

    DETAIL_FIELD_NAMES = (
        "appearance",
        "personality",
        "background",
        "worldview",
        "motivation",
        "abilities",
        "limitation",
        "mainline_role",
        "growth_direction",
        "relationships",
        "mainline_clues",
    )
    PROFILE_SECTION_FIELD_MAP = {
        "外貌特征": "appearance",
        "外貌锚点": "appearance",
        "性格特点": "personality",
        "性格锚点": "personality",
        "背景故事": "background",
        "背景/当前处境": "background",
        "世界观/价值观立场": "worldview",
        "核心动机": "motivation",
        "能力/特长": "abilities",
        "能力与限制": "abilities",
        "弱点/缺陷": "limitation",
        "在情节中的作用": "mainline_role",
        "人物成长线": "growth_direction",
        "成长方向": "growth_direction",
        "关键关系": "relationships",
        "关联线索": "mainline_clues",
        "主线绑定": "mainline_clues",
    }

    @staticmethod
    def _clean_text(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _join_unique_parts(parts: List[Optional[str]], separator: str = "\n") -> Optional[str]:
        normalized_parts: List[str] = []
        seen = set()
        for item in parts:
            text = CharacterTextGenerator._clean_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            normalized_parts.append(text)
        return separator.join(normalized_parts) if normalized_parts else None

    @staticmethod
    def _pick_first_text(*values: Any) -> Optional[str]:
        for value in values:
            text = CharacterTextGenerator._clean_text(value)
            if text:
                return text
        return None

    @staticmethod
    def _parse_profile_character(character: Character) -> Optional[ParsedCharacter]:
        profile_text = CharacterTextGenerator._clean_text(character.profile)
        if not profile_text:
            return None

        parser = CharacterTextParser()
        parse_source = (
            profile_text
            if "【姓名】" in profile_text or re.search(r"^\s*###", profile_text, re.MULTILINE)
            else f"### 【姓名】：{character.name}\n{profile_text}"
        )
        parsed = parser.parse_all_characters(parse_source)
        return parsed[0] if parsed else None

    @staticmethod
    def _merge_parsed_character(base: ParsedCharacter, incoming: Optional[ParsedCharacter]) -> ParsedCharacter:
        if incoming is None:
            return base

        for field_name in (
            "age",
            "gender",
            "role",
            "role_position",
            "faction",
            "importance_level",
            *CharacterTextGenerator.DETAIL_FIELD_NAMES,
        ):
            current_value = getattr(base, field_name, None)
            incoming_value = getattr(incoming, field_name, None)
            if incoming_value in (None, ""):
                continue
            if current_value in (None, ""):
                setattr(base, field_name, incoming_value)
                continue
            if isinstance(current_value, str) and isinstance(incoming_value, str) and len(incoming_value) > len(current_value):
                setattr(base, field_name, incoming_value)

        return base

    @staticmethod
    def _extract_profile_sections(profile_text: Optional[str]) -> Dict[str, str]:
        text = CharacterTextGenerator._clean_text(profile_text)
        if not text:
            return {}

        sections: Dict[str, str] = {}
        pattern = re.compile(r"【(?P<label>[^】]+)】\s*(?:[:：]\s*)?(?P<value>.*?)(?=\n\s*【[^】]+】|\Z)", re.S)
        for match in pattern.finditer(text):
            raw_label = match.group("label").strip()
            value = CharacterTextGenerator._clean_text(match.group("value"))
            if not value:
                continue

            if raw_label == "性格锚点":
                personality = _extract_prefixed_character_value(value, ("性格",))
                worldview = _extract_prefixed_character_value(value, ("价值倾向",))
                if personality:
                    sections["personality"] = personality
                if worldview:
                    sections["worldview"] = worldview
                continue

            if raw_label == "能力与限制":
                abilities = _extract_prefixed_character_value(value, ("能力",))
                limitation = _extract_prefixed_character_value(value, ("限制", "弱点", "代价"))
                if abilities:
                    sections["abilities"] = abilities
                if limitation:
                    sections["limitation"] = limitation
                continue

            if raw_label == "主线绑定":
                mainline_role = _extract_prefixed_character_value(value, ("剧情职责", "主线职责"))
                mainline_clues = _extract_prefixed_character_value(value, ("关联线索",))
                if mainline_role:
                    sections["mainline_role"] = mainline_role
                if mainline_clues:
                    sections["mainline_clues"] = mainline_clues
                continue

            label = CharacterTextGenerator.PROFILE_SECTION_FIELD_MAP.get(raw_label)
            if label:
                sections[label] = value
        return sections

    @staticmethod
    def _format_technique_names(character: Character) -> List[str]:
        if not character.character_techniques:
            return []

        technique_names: List[str] = []
        for relation in character.character_techniques:
            if not relation.technique_item:
                continue
            name = relation.technique_item.name
            if relation.proficiency:
                name += f"（{relation.proficiency}）"
            technique_names.append(name)
        return technique_names

    @staticmethod
    def _extract_relation_lines(value: Any) -> List[str]:
        if value in (None, ""):
            return []

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                return [text]
            return CharacterTextGenerator._extract_relation_lines(parsed)

        if isinstance(value, dict):
            text = CharacterTextGenerator._clean_text(value.get("text"))
            if text:
                return [text]

            current_summary = CharacterTextGenerator._clean_text(value.get("current_summary"))
            if current_summary:
                return [current_summary]

            if isinstance(value.get("items"), list):
                lines: List[str] = []
                for item in value["items"]:
                    lines.extend(CharacterTextGenerator._extract_relation_lines(item))
                if lines:
                    return lines

            target = CharacterTextGenerator._clean_text(value.get("target"))
            relation_type = CharacterTextGenerator._clean_text(value.get("type"))
            description = CharacterTextGenerator._pick_first_text(
                value.get("description"),
                value.get("detail"),
                value.get("notes"),
            )
            relation_text = "：".join(part for part in (target, relation_type) if part)
            if relation_text and description:
                relation_text = f"{relation_text}（{description}）"
            elif not relation_text:
                relation_text = description or ""
            return [relation_text] if relation_text else []

        if isinstance(value, list):
            lines: List[str] = []
            for item in value:
                lines.extend(CharacterTextGenerator._extract_relation_lines(item))
            return lines

        text = CharacterTextGenerator._clean_text(value)
        return [text] if text else []

    @staticmethod
    def _build_relation_text(character: Character) -> Optional[str]:
        lines = CharacterTextGenerator._extract_relation_lines(character.relations)
        lines.extend(CharacterTextGenerator._extract_relation_lines(character.relationship_network))
        return CharacterTextGenerator._join_unique_parts(lines)

    @staticmethod
    def _build_abilities_text(
        character: Character,
        existing_value: Optional[str],
        include_techniques: bool,
    ) -> Optional[str]:
        additions: List[str] = []

        if character.current_realm:
            additions.append(f"当前境界：{character.current_realm.name}")
        if character.profession_item:
            additions.append(f"职业：{character.profession_item.name}")
        if character.race_item:
            additions.append(f"种族：{character.race_item.name}")

        if include_techniques:
            technique_names = CharacterTextGenerator._format_technique_names(character)
            if technique_names:
                additions.append(f"掌握能力：{', '.join(technique_names)}")

        if character.tags:
            try:
                parsed_tags = json.loads(character.tags)
                if isinstance(parsed_tags, list) and parsed_tags:
                    additions.append(f"人物标签：{', '.join(str(tag).strip() for tag in parsed_tags if str(tag).strip())}")
            except Exception:
                text = CharacterTextGenerator._clean_text(character.tags)
                if text:
                    additions.append(f"人物标签：{text}")

        return CharacterTextGenerator._join_unique_parts([existing_value, *additions])

    @staticmethod
    def _build_mainline_clues_text(character: Character, existing_value: Optional[str]) -> Optional[str]:
        additions: List[str] = []

        appearance_status = CharacterTextGenerator.APPEARANCE_STATUS_MAP.get(
            character.appearance_status,
            character.appearance_status or "",
        )
        life_status = CharacterTextGenerator.LIFE_STATUS_MAP.get(
            character.life_status,
            character.life_status or "",
        )

        if appearance_status:
            additions.append(f"出场状态：{appearance_status}")
        if life_status:
            additions.append(f"当前状态：{life_status}")
        if character.first_appearance_chapter:
            additions.append(f"首次出场章节：第{character.first_appearance_chapter}章")

        return CharacterTextGenerator._join_unique_parts([existing_value, *additions])

    @staticmethod
    def _build_canonical_character(character: Character, include_relations: bool, include_techniques: bool) -> ParsedCharacter:
        role_text = CharacterTextGenerator._pick_first_text(
            CharacterTextGenerator.ROLE_MAP.get(character.role),
            character.role,
        )
        importance_text = CharacterTextGenerator._pick_first_text(
            CharacterTextGenerator.IMPORTANCE_MAP.get(character.importance_level),
            character.importance_level,
        )
        faction_text = CharacterTextGenerator._pick_first_text(
            character.faction,
            getattr(character.faction_item, "name", None),
        )

        parsed = ParsedCharacter(
            name=character.name.strip(),
            age=character.age,
            gender=CharacterTextGenerator._clean_text(character.gender),
            role=role_text,
            role_position=CharacterTextGenerator._clean_text(getattr(character, "role_position", None)),
            faction=faction_text,
            importance_level=importance_text,
            raw_text=CharacterTextGenerator._clean_text(character.profile) or "",
        )
        parsed = CharacterTextGenerator._merge_parsed_character(
            parsed,
            CharacterTextGenerator._parse_profile_character(character),
        )
        for field_name, value in CharacterTextGenerator._extract_profile_sections(character.profile).items():
            current_value = getattr(parsed, field_name, None)
            if current_value in (None, "") or (isinstance(current_value, str) and len(value) > len(current_value)):
                setattr(parsed, field_name, value)

        summary_text = CharacterTextGenerator._clean_text(character.summary)
        if summary_text and not parsed.mainline_role:
            parsed.mainline_role = summary_text
        if summary_text and not parsed.background and not CharacterTextGenerator._clean_text(character.profile):
            parsed.background = summary_text

        parsed.abilities = CharacterTextGenerator._build_abilities_text(
            character,
            parsed.abilities,
            include_techniques=include_techniques,
        )
        parsed.mainline_clues = CharacterTextGenerator._build_mainline_clues_text(character, parsed.mainline_clues)

        if include_relations:
            parsed.relationships = CharacterTextGenerator._join_unique_parts(
                [parsed.relationships, CharacterTextGenerator._build_relation_text(character)],
            )

        return parsed

    @staticmethod
    def _render_field(label: str, value: Optional[str]) -> Optional[str]:
        text = CharacterTextGenerator._clean_text(value)
        if not text:
            return None
        return f"【{label}】：{text}"

    @staticmethod
    def generate_single_character_text(
        character: Character,
        db: Session,
        include_relations: bool = True,
        include_techniques: bool = True,
    ) -> str:
        """
        生成单个人物的文本描述
        
        Args:
            character: 人物对象
            db: 数据库会话
            include_relations: 是否包含关系信息
            include_techniques: 是否包含功法信息
            
        Returns:
            格式化的人物文本
        """
        parsed = CharacterTextGenerator._build_canonical_character(
            character,
            include_relations=include_relations,
            include_techniques=include_techniques,
        )

        age_gender_parts: List[str] = []
        if parsed.age is not None:
            age_gender_parts.append(f"{parsed.age}岁")
        if parsed.gender:
            age_gender_parts.append(parsed.gender)

        lines = [f"### 【姓名】：{parsed.name}"]
        field_lines = [
            CharacterTextGenerator._render_field("年龄/性别", "/".join(age_gender_parts) if age_gender_parts else None),
            CharacterTextGenerator._render_field("故事立场", parsed.role),
            CharacterTextGenerator._render_field("角色定位", parsed.role_position),
            CharacterTextGenerator._render_field("所属势力", parsed.faction),
            CharacterTextGenerator._render_field("外貌锚点", parsed.appearance),
            CharacterTextGenerator._render_field(
                "性格锚点",
                _build_personality_anchor_text(parsed.personality, parsed.worldview),
            ),
            CharacterTextGenerator._render_field("背景/当前处境", parsed.background),
            CharacterTextGenerator._render_field("核心动机", parsed.motivation),
            CharacterTextGenerator._render_field(
                "能力与限制",
                _build_ability_and_limit_text(parsed.abilities, parsed.limitation),
            ),
            CharacterTextGenerator._render_field("关键关系", parsed.relationships),
            CharacterTextGenerator._render_field(
                "主线绑定",
                _build_mainline_binding_text(parsed.mainline_role, parsed.mainline_clues),
            ),
            CharacterTextGenerator._render_field("成长方向", parsed.growth_direction),
        ]
        lines.extend(line for line in field_lines if line)
        return "\n".join(lines)

    @staticmethod
    def generate_project_characters_text(
        project_id: int,
        db: Session,
        group_by_importance: bool = True,
        include_all_details: bool = False,
    ) -> str:
        """
        生成项目所有人物的汇总文本
        
        Args:
            project_id: 项目ID
            db: 数据库会话
            group_by_importance: 是否按重要程度分组
            include_all_details: 是否包含所有详细信息
            
        Returns:
            所有人物的汇总文本
        """
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).order_by(Character.id).all()
        
        if not characters:
            return "暂无人物设定。"
        
        if group_by_importance:
            return CharacterTextGenerator._generate_grouped_text(
                characters, db, include_all_details
            )
        else:
            return CharacterTextGenerator._generate_flat_text(
                characters, db, include_all_details
            )

    @staticmethod
    def _generate_grouped_text(
        characters: List[Character],
        db: Session,
        include_all_details: bool,
    ) -> str:
        """按重要程度分组生成文本"""
        groups = {
            "主角": [],
            "核心角色": [],
            "重要角色": [],
            "次要角色": [],
            "边缘角色": [],
            "群众角色": [],
            "unknown": [],
        }
        
        for char in characters:
            level = char.importance_level or "unknown"
            if level in groups:
                groups[level].append(char)
            else:
                groups["unknown"].append(char)
        
        lines = []
        lines.append("# 人物设定\n")
        
        group_titles = [
            ("主角", "## 主角"),
            ("核心角色", "## 核心角色"),
            ("重要角色", "## 重要角色"),
            ("次要角色", "## 次要角色"),
            ("边缘角色", "## 边缘角色"),
            ("群众角色", "## 群众角色"),
            ("unknown", "## 其他角色"),
        ]
        
        for group_key, group_title in group_titles:
            chars = groups[group_key]
            if chars:
                lines.append(f"\n{group_title}\n")
                for char in chars:
                    char_text = CharacterTextGenerator.generate_single_character_text(
                        char, db,
                        include_relations=include_all_details,
                        include_techniques=include_all_details,
                    )
                    lines.append(char_text)
                    lines.append("")  # 空行分隔
        
        return "\n".join(lines)

    @staticmethod
    def _generate_flat_text(
        characters: List[Character],
        db: Session,
        include_all_details: bool,
    ) -> str:
        """平铺生成文本"""
        lines = []
        lines.append("# 人物设定\n")
        
        for char in characters:
            char_text = CharacterTextGenerator.generate_single_character_text(
                char, db,
                include_relations=include_all_details,
                include_techniques=include_all_details,
            )
            lines.append(char_text)
            lines.append("")  # 空行分隔
        
        return "\n".join(lines)

    @staticmethod
    def generate_compact_summary(
        project_id: int,
        db: Session,
        max_characters: int = 20,
    ) -> str:
        """
        生成紧凑的人物摘要（用于提示词注入）
        
        Args:
            project_id: 项目ID
            db: 数据库会话
            max_characters: 最大人物数量
            
        Returns:
            紧凑的人物摘要文本
        """
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).order_by(
            # 优先显示重要角色
            Character.importance_level.desc(),
            Character.id
        ).limit(max_characters).all()
        
        if not characters:
            return ""
        
        lines = []
        for char in characters:
            parts = [char.name]
            
            if char.role:
                role = CharacterTextGenerator.ROLE_MAP.get(char.role, char.role)
                parts.append(role)
            if getattr(char, "role_position", None):
                parts.append(char.role_position)
            
            if char.current_realm:
                parts.append(char.current_realm.name)
            
            if char.summary:
                # 截取摘要前50字
                summary = char.summary[:50] + "..." if len(char.summary) > 50 else char.summary
                parts.append(summary)
            
            lines.append(" - ".join(parts))
        
        return "\n".join(lines)

    @staticmethod
    def get_character_stats(project_id: int, db: Session) -> Dict[str, Any]:
        """
        获取项目人物统计信息
        
        Returns:
            {
                "total": 总数,
                "by_importance": {重要程度: 数量},
                "by_role": {立场: 数量},
                "by_status": {状态: 数量}
            }
        """
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        
        stats = {
            "total": len(characters),
            "by_importance": {},
            "by_role": {},
            "by_life_status": {},
        }
        
        for char in characters:
            # 按重要程度统计
            importance = char.importance_level or "unknown"
            stats["by_importance"][importance] = stats["by_importance"].get(importance, 0) + 1
            
            # 按立场统计
            role = char.role or "unknown"
            stats["by_role"][role] = stats["by_role"].get(role, 0) + 1
            
            # 按生死状态统计
            life = char.life_status or "unknown"
            stats["by_life_status"][life] = stats["by_life_status"].get(life, 0) + 1
        
        return stats
