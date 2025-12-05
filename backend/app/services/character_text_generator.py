"""
人物卡文本生成服务
将结构化人物数据转换为工作流可用的文本格式
"""
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterTechnique
from app.models.setting import SettingItem


class CharacterTextGenerator:
    """人物卡文本生成器"""
    
    # 重要程度映射
    IMPORTANCE_MAP = {
        "protagonist": "主角",
        "major": "重要角色", 
        "minor": "次要角色",
        "extra": "群众角色",
    }
    
    # 角色立场映射
    ROLE_MAP = {
        "protagonist_side": "主角方",
        "antagonist_side": "反派方",
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
        lines = []
        
        # 标题
        lines.append(f"### {character.name}")
        
        # 基本信息
        basic_info = []
        if character.gender:
            basic_info.append(f"性别：{character.gender}")
        if character.age:
            basic_info.append(f"年龄：{character.age}岁")
        if character.role:
            role_display = CharacterTextGenerator.ROLE_MAP.get(character.role, character.role)
            basic_info.append(f"立场：{role_display}")
        if character.importance_level:
            importance = CharacterTextGenerator.IMPORTANCE_MAP.get(
                character.importance_level, character.importance_level
            )
            basic_info.append(f"戏份：{importance}")
        
        if basic_info:
            lines.append("**基本信息**：" + " | ".join(basic_info))
        
        # 境界信息
        if character.current_realm:
            lines.append(f"**当前境界**：{character.current_realm.name}")
        
        # 势力/职业/种族
        affiliations = []
        if character.faction:
            affiliations.append(f"势力：{character.faction}")
        elif character.faction_item:
            affiliations.append(f"势力：{character.faction_item.name}")
        if character.profession_item:
            affiliations.append(f"职业：{character.profession_item.name}")
        if character.race_item:
            affiliations.append(f"种族：{character.race_item.name}")
        
        if affiliations:
            lines.append("**归属**：" + " | ".join(affiliations))
        
        # 状态信息
        status_info = []
        if character.appearance_status:
            status = CharacterTextGenerator.APPEARANCE_STATUS_MAP.get(
                character.appearance_status, character.appearance_status
            )
            status_info.append(f"出场：{status}")
        if character.life_status:
            life = CharacterTextGenerator.LIFE_STATUS_MAP.get(
                character.life_status, character.life_status
            )
            status_info.append(f"状态：{life}")
        if character.first_appearance_chapter:
            status_info.append(f"首次出场：第{character.first_appearance_chapter}章")
        
        if status_info:
            lines.append("**当前状态**：" + " | ".join(status_info))
        
        # 功法
        if include_techniques and character.character_techniques:
            technique_names = []
            for ct in character.character_techniques:
                if ct.technique_item:
                    name = ct.technique_item.name
                    if ct.proficiency:
                        name += f"({ct.proficiency})"
                    technique_names.append(name)
            if technique_names:
                lines.append(f"**功法**：{', '.join(technique_names)}")
        
        # 标签
        if character.tags:
            try:
                tags = json.loads(character.tags)
                if tags:
                    lines.append(f"**标签**：{', '.join(tags)}")
            except:
                if character.tags:
                    lines.append(f"**标签**：{character.tags}")
        
        # 人物简介
        if character.summary:
            lines.append(f"**简介**：{character.summary}")
        
        # 关系网络
        if include_relations and character.relations:
            try:
                relations = json.loads(character.relations)
                if relations:
                    rel_strs = []
                    for rel in relations:
                        if isinstance(rel, dict):
                            target = rel.get("target", "")
                            rel_type = rel.get("type", "")
                            if target and rel_type:
                                rel_strs.append(f"{target}({rel_type})")
                        elif isinstance(rel, str):
                            rel_strs.append(rel)
                    if rel_strs:
                        lines.append(f"**人物关系**：{', '.join(rel_strs)}")
            except:
                pass
        
        # 完整档案（去重处理）
        if character.profile:
            # 只添加profile中未在其他字段出现的内容
            profile_text = character.profile.strip()
            if profile_text and profile_text != character.summary:
                lines.append(f"**详细档案**：\n{profile_text}")
        
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
            "protagonist": [],
            "major": [],
            "minor": [],
            "extra": [],
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
            ("protagonist", "## 主角"),
            ("major", "## 重要角色"),
            ("minor", "## 次要角色"),
            ("extra", "## 群众角色"),
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
