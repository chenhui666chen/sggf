"""
人物卡文本解析器

解析AI生成的文本格式人物卡，提取结构化字段，
并同步到数据库的characters表中。
"""
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger("uvicorn.error")


@dataclass
class ParsedCharacter:
    """解析后的人物卡结构"""
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    role: Optional[str] = None  # 故事立场：主角方/反派方/中立方/亦正亦邪
    faction: Optional[str] = None  # 所属势力
    importance_level: Optional[str] = None  # 重要性
    
    # 文本字段（将合并到profile中）
    appearance: Optional[str] = None  # 外貌特征
    personality: Optional[str] = None  # 性格特点
    background: Optional[str] = None  # 背景故事
    worldview: Optional[str] = None  # 世界观/价值观立场
    motivation: Optional[str] = None  # 核心动机
    abilities: Optional[str] = None  # 能力/特长
    weaknesses: Optional[str] = None  # 弱点/缺陷
    plot_role: Optional[str] = None  # 在情节中的作用
    growth_arc: Optional[str] = None  # 人物成长线
    relationships: Optional[str] = None  # 关键关系
    plot_threads: Optional[str] = None  # 关联线索
    
    # 原始文本块
    raw_text: str = ""
    
    def build_summary(self) -> str:
        """构建人物简介（1-3句话）"""
        parts = []
        if self.role:
            parts.append(self.role)
        if self.personality:
            # 取性格特点的第一句
            first_sentence = self.personality.split('。')[0] if self.personality else ""
            if first_sentence:
                parts.append(first_sentence)
        if self.motivation:
            parts.append(f"核心动机：{self.motivation.split('。')[0]}")
        return '。'.join(parts[:3]) + '。' if parts else ""
    
    def build_profile(self) -> str:
        """构建完整人物档案"""
        sections = []
        
        if self.appearance:
            sections.append(f"【外貌特征】\n{self.appearance}")
        if self.personality:
            sections.append(f"【性格特点】\n{self.personality}")
        if self.background:
            sections.append(f"【背景故事】\n{self.background}")
        if self.worldview:
            sections.append(f"【世界观/价值观立场】\n{self.worldview}")
        if self.motivation:
            sections.append(f"【核心动机】\n{self.motivation}")
        if self.abilities:
            sections.append(f"【能力/特长】\n{self.abilities}")
        if self.weaknesses:
            sections.append(f"【弱点/缺陷】\n{self.weaknesses}")
        if self.plot_role:
            sections.append(f"【在情节中的作用】\n{self.plot_role}")
        if self.growth_arc:
            sections.append(f"【人物成长线】\n{self.growth_arc}")
        if self.relationships:
            sections.append(f"【关键关系】\n{self.relationships}")
        if self.plot_threads:
            sections.append(f"【关联线索】\n{self.plot_threads}")
        
        return "\n\n".join(sections) if sections else self.raw_text


class CharacterTextParser:
    """人物卡文本解析器"""

    # 字段匹配模式（支持多种格式变体）
    # 支持：【姓名】：xxx 或 **【姓名】**：xxx 或 ### 【姓名】：xxx
    FIELD_PATTERNS = {
        # 姓名特殊处理：可能有 ### 或 ** 前缀
        'name': r'(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'age_gender': r'(?:\*\*)?【年龄/性别】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'role': r'(?:\*\*)?【故事立场】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'faction': r'(?:\*\*)?【所属势力】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'importance': r'(?:\*\*)?【重要性】(?:\*\*)?[：:]\s*(.+?)(?=\n|$)',
        'appearance': r'(?:\*\*)?【外貌特征】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'personality': r'(?:\*\*)?【性格特点】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'background': r'(?:\*\*)?【背景故事】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'worldview': r'(?:\*\*)?【世界观/价值观立场】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'motivation': r'(?:\*\*)?【核心动机】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'abilities': r'(?:\*\*)?【能力/特长】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'weaknesses': r'(?:\*\*)?【弱点/缺陷】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'plot_role': r'(?:\*\*)?【在情节中的作用】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'growth_arc': r'(?:\*\*)?【人物成长线】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'relationships': r'(?:\*\*)?【关键关系】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
        'plot_threads': r'(?:\*\*)?【关联线索】(?:\*\*)?[：:]\s*(.+?)(?=【|##|$)',
    }
    
    # 阵营识别模式
    FACTION_PATTERNS = {
        '主角阵营': ['主角', '主角阵营', '正派'],
        '对手阵营': ['对手', '反派', '对手阵营', '敌对'],
        '支持角色': ['支持', '辅助', '支持角色'],
        '中立角色': ['中立', '中立角色'],
    }
    
    def parse_all_characters(self, text: str) -> List[ParsedCharacter]:
        """解析文本中的所有人物卡

        支持多种格式：
        1. ### 【姓名】：李铁柱
        2. 【姓名】：李铁柱
        3. **【姓名】**：李铁柱
        """
        characters = []
        current_faction = None

        logger.debug(f"📋 开始解析人物卡，文本长度: {len(text)} 字符")

        # 更灵活的分割模式：匹配 ### 【姓名】 或 **【姓名】** 或直接 【姓名】
        # 使用正向前瞻 (?=...) 保留分隔符
        split_pattern = r'(?=(?:###\s*)?(?:\*\*)?【姓名】(?:\*\*)?[：:])'
        character_blocks = re.split(split_pattern, text)

        logger.debug(f"   分割出 {len(character_blocks)} 个文本块")

        for i, block in enumerate(character_blocks):
            block = block.strip()
            if not block:
                continue

            # 检测阵营标题（## 主角阵营 等）
            faction_match = re.search(r'^##\s*([^#\n]+?)(?:\n|$)', block, re.MULTILINE)
            if faction_match:
                faction_title = faction_match.group(1).strip()
                for faction, keywords in self.FACTION_PATTERNS.items():
                    if any(kw in faction_title for kw in keywords):
                        current_faction = faction
                        logger.debug(f"   检测到阵营: {current_faction}")
                        break

            # 解析人物卡
            parsed = self._parse_single_character(block)
            if parsed and parsed.name:
                if current_faction and not parsed.faction:
                    parsed.faction = current_faction
                characters.append(parsed)
                logger.debug(f"   ✓ 成功解析人物: {parsed.name}")
            elif '【姓名】' in block:
                logger.debug(f"   ✗ 块 {i} 包含【姓名】但解析失败，前100字符: {block[:100]}...")

        logger.info(f"📋 解析完成，共识别 {len(characters)} 个人物")
        return characters

    def _parse_single_character(self, block: str) -> Optional[ParsedCharacter]:
        """解析单个人物卡文本块"""
        # 提取姓名
        name_match = re.search(self.FIELD_PATTERNS['name'], block, re.DOTALL)
        if not name_match:
            logger.debug(f"   未匹配到姓名字段")
            return None

        name = name_match.group(1).strip()
        # 清理名字中可能的markdown格式（如 **李铁柱** -> 李铁柱）
        name = re.sub(r'\*+', '', name).strip()

        if not name:
            logger.debug(f"   姓名为空")
            return None
        if len(name) > 30:  # 名字过长可能是解析错误（放宽限制）
            logger.debug(f"   姓名过长: {name[:30]}...")
            return None

        char = ParsedCharacter(name=name, raw_text=block)

        # 解析年龄和性别
        age_gender_match = re.search(self.FIELD_PATTERNS['age_gender'], block, re.DOTALL)
        if age_gender_match:
            age_gender = age_gender_match.group(1).strip()
            char.age, char.gender = self._parse_age_gender(age_gender)

        # 解析故事立场
        role_match = re.search(self.FIELD_PATTERNS['role'], block, re.DOTALL)
        if role_match:
            role_text = role_match.group(1).strip()
            char.role = self._normalize_role(role_text)
        
        # 解析所属势力
        faction_match = re.search(self.FIELD_PATTERNS['faction'], block, re.DOTALL)
        if faction_match:
            char.faction = faction_match.group(1).strip()
        
        # 解析重要性
        importance_match = re.search(self.FIELD_PATTERNS['importance'], block, re.DOTALL)
        if importance_match:
            char.importance_level = importance_match.group(1).strip()

        # 解析其他字段
        for field_name in ['appearance', 'personality', 'background', 'worldview',
                           'motivation', 'abilities', 'weaknesses', 'plot_role',
                           'growth_arc', 'relationships', 'plot_threads']:
            pattern = self.FIELD_PATTERNS.get(field_name)
            if pattern:
                match = re.search(pattern, block, re.DOTALL)
                if match:
                    value = match.group(1).strip()
                    # 清理多余空白
                    value = re.sub(r'\n{3,}', '\n\n', value)
                    setattr(char, field_name, value)

        return char

    def _parse_age_gender(self, text: str) -> tuple:
        """解析年龄和性别字段"""
        age = None
        gender = None

        # 提取年龄数字
        age_match = re.search(r'(\d+)\s*岁?', text)
        if age_match:
            try:
                age = int(age_match.group(1))
            except ValueError:
                pass

        # 提取性别
        if '男' in text:
            gender = '男'
        elif '女' in text:
            gender = '女'

        return age, gender

    def _normalize_role(self, role_text: str) -> str:
        """标准化故事立场"""
        role_text_lower = role_text.lower()
        
        # 匹配主角方
        if '主角' in role_text and ('阵营' in role_text or '方' in role_text):
            return '主角方'
        elif '正派' in role_text or '正义' in role_text:
            return '主角方'
        
        # 匹配反派方
        elif '反派' in role_text or '对手' in role_text or '敌人' in role_text:
            return '反派方'
        
        # 匹配中立方
        elif '中立' in role_text:
            return '中立方'
        
        # 匹配亦正亦邪
        elif '亦正亦邪' in role_text or ('正' in role_text and '邪' in role_text):
            return '亦正亦邪'
        
        # 兼容旧值：如果直接写的是"主角"，也归类为主角方
        elif '主角' in role_text:
            return '主角方'
        
        # 其他情况取第一个标签
        return role_text.split('/')[0].strip()[:10]

    def _extract_importance(self, role_text: str) -> str:
        """提取重要性等级（戏份权重）"""
        if '主角' in role_text:
            return '主角'
        elif '核心' in role_text or '关键' in role_text or '重要' in role_text:
            return '重要角色'
        elif '次要' in role_text:
            return '次要角色'
        elif '龙套' in role_text or '路人' in role_text or '群众' in role_text:
            return '群众角色'
        # 默认为次要角色
        return '次要角色'


def sync_parsed_characters_to_db(
    project_id: int,
    parsed_characters: List[ParsedCharacter],
    db_session: Any
) -> Dict[str, Any]:
    """
    将解析后的人物卡同步到数据库的characters表

    逻辑：
    1. 根据姓名查找已存在的角色
    2. 如果存在则更新，不存在则创建
    3. 返回同步统计信息

    Args:
        project_id: 项目ID
        parsed_characters: 解析后的人物卡列表
        db_session: SQLAlchemy数据库会话

    Returns:
        同步统计信息
    """
    from app.models.character import Character

    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []

    for parsed in parsed_characters:
        try:
            # 查找已存在的角色（按项目ID和姓名）
            existing = db_session.query(Character).filter(
                Character.project_id == project_id,
                Character.name == parsed.name
            ).first()

            if existing:
                # 更新已存在的角色
                existing.gender = parsed.gender or existing.gender
                existing.age = parsed.age or existing.age
                existing.role = parsed.role or existing.role
                existing.faction = parsed.faction or existing.faction
                existing.importance_level = parsed.importance_level or existing.importance_level
                existing.summary = parsed.build_summary() or existing.summary
                existing.profile = parsed.build_profile() or existing.profile

                # 更新关系字段（JSON格式）
                if parsed.relationships:
                    import json
                    existing.relations = json.dumps({
                        "text": parsed.relationships
                    }, ensure_ascii=False)

                updated_count += 1
                logger.debug(f"   📝 更新角色: {parsed.name}")
            else:
                # 创建新角色
                import json
                new_char = Character(
                    project_id=project_id,
                    name=parsed.name,
                    gender=parsed.gender,
                    age=parsed.age,
                    role=parsed.role,
                    faction=parsed.faction,
                    importance_level=parsed.importance_level,
                    summary=parsed.build_summary(),
                    profile=parsed.build_profile(),
                    relations=json.dumps({"text": parsed.relationships}, ensure_ascii=False) if parsed.relationships else None,
                    appearance_status="未出场",  # 默认未出场
                    life_status="存活",  # 默认存活
                )
                db_session.add(new_char)
                created_count += 1
                logger.debug(f"   ➕ 创建角色: {parsed.name}")

        except Exception as e:
            errors.append(f"{parsed.name}: {str(e)}")
            skipped_count += 1
            logger.warning(f"   ⚠️ 同步角色失败 {parsed.name}: {e}")

    # 提交事务
    try:
        db_session.commit()
        logger.info(f"✅ 角色同步完成: 创建 {created_count} 个, 更新 {updated_count} 个, 跳过 {skipped_count} 个")
    except Exception as e:
        db_session.rollback()
        logger.error(f"❌ 角色同步提交失败: {e}")
        raise

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors,
        "total": len(parsed_characters)
    }


def parse_and_sync_characters(
    project_id: int,
    characters_text: str,
    db_session: Any
) -> Dict[str, Any]:
    """
    一键解析文本人物卡并同步到数据库

    这是提供给外部调用的主函数。

    Args:
        project_id: 项目ID
        characters_text: 包含人物卡的文本
        db_session: SQLAlchemy数据库会话

    Returns:
        解析和同步的统计信息
    """
    logger.info(f"🚀 开始解析并同步人物卡到数据库，项目ID: {project_id}")

    # 1. 解析文本
    parser = CharacterTextParser()
    parsed_characters = parser.parse_all_characters(characters_text)

    if not parsed_characters:
        logger.warning("⚠️ 未能解析出任何人物卡")
        return {
            "parsed": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["未能解析出任何人物卡"],
            "total": 0
        }

    # 2. 同步到数据库
    sync_result = sync_parsed_characters_to_db(project_id, parsed_characters, db_session)
    sync_result["parsed"] = len(parsed_characters)

    return sync_result


def parse_and_sync_relationships(
    project_id: int,
    relationships_text: str,
    db_session: Any
) -> Dict[str, Any]:
    """
    🆕 解析人物关系文本并同步到Character.relations字段
    
    支持的格式：
    - [角色A] ↔ [角色B]：[关系类型]（[关系描述]）
    - 主角 ⇄ 盟友A：战友关系，相互信任（第1章建立）
    - 李铁柱 → 师傅：师徒关系
    
    Args:
        project_id: 项目ID
        relationships_text: 关系文本
        db_session: 数据库会话
    
    Returns:
        解析和同步的统计信息
    """
    import json
    from app.models.character import Character
    
    logger.info(f"🔗 开始解析人物关系文本，项目ID: {project_id}")
    
    if not relationships_text:
        logger.warning("⚠️ 关系文本为空")
        return {"parsed": 0, "saved": 0, "characters_updated": 0}
    
    # 获取项目下所有人物
    characters = db_session.query(Character).filter(
        Character.project_id == project_id
    ).all()
    
    if not characters:
        logger.warning(f"⚠️ 项目 {project_id} 没有人物卡")
        return {"parsed": 0, "saved": 0, "characters_updated": 0}
    
    # 构建名称到人物的映射
    name_to_char = {char.name: char for char in characters}
    
    # 解析关系文本
    # 匹配模式：- [xxx] ↔/⇄/→/← [xxx]：xxx（xxx）
    # 或者：- xxx ↔/⇄/→/← xxx：xxx
    relation_patterns = [
        # 模式1：- [角色A] ↔ [角色B]：关系类型（描述）
        r'-\s*\[?([^\[\]↔⇄→←：:]+?)\]?\s*[↔⇄→←]\s*\[?([^\[\]↔⇄→←：:]+?)\]?\s*[：:]\s*([^（）()]+?)(?:（([^）]+)）|\(([^)]+)\))?\s*$',
        # 模式2：角色A ↔ 角色B：关系类型
        r'([\u4e00-\u9fa5]{2,8})\s*[↔⇄→←]\s*([\u4e00-\u9fa5]{2,8})\s*[：:]\s*(.+?)\s*$',
    ]
    
    parsed_relations = []
    
    for line in relationships_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('*'):
            continue
        
        for pattern in relation_patterns:
            match = re.search(pattern, line, re.MULTILINE)
            if match:
                groups = match.groups()
                source = groups[0].strip() if groups[0] else None
                target = groups[1].strip() if groups[1] else None
                rel_type = groups[2].strip() if groups[2] else "关联"
                description = (groups[3] or groups[4] if len(groups) > 3 else None) or ""
                
                # 清理关系类型（去除多余标符）
                rel_type = rel_type.split('，')[0].split(',')[0].strip()
                
                if source and target and source != target:
                    parsed_relations.append({
                        'source': source,
                        'target': target,
                        'type': rel_type,
                        'description': description.strip() if description else ""
                    })
                break
    
    logger.info(f"   解析出 {len(parsed_relations)} 条关系")
    
    # 将关系写入Character.relations字段
    saved_count = 0
    updated_chars = set()
    
    for rel in parsed_relations:
        source_name = rel['source']
        target_name = rel['target']
        rel_type = rel['type']
        
        # 查找源人物
        source_char = name_to_char.get(source_name)
        if not source_char:
            # 尝试模糊匹配
            for name, char in name_to_char.items():
                if source_name in name or name in source_name:
                    source_char = char
                    break
        
        if not source_char:
            logger.debug(f"   未找到源人物: {source_name}")
            continue
        
        # 解析现有关系
        try:
            existing_relations = json.loads(source_char.relations) if source_char.relations else []
        except:
            existing_relations = []
        
        if not isinstance(existing_relations, list):
            existing_relations = []
        
        # 检查是否已存在相同关系
        already_exists = any(
            r.get('target') == target_name and r.get('type') == rel_type
            for r in existing_relations if isinstance(r, dict)
        )
        
        if not already_exists:
            # 添加新关系
            new_relation = {
                "target": target_name,
                "type": rel_type
            }
            existing_relations.append(new_relation)
            source_char.relations = json.dumps(existing_relations, ensure_ascii=False)
            updated_chars.add(source_char.id)
            saved_count += 1
            logger.debug(f"   → {source_name} --[{rel_type}]--> {target_name}")
    
    # 提交更改
    if updated_chars:
        db_session.commit()
        logger.info(f"   🔗 已更新 {len(updated_chars)} 个人物的关系数据，共 {saved_count} 条关系")
    
    return {
        "parsed": len(parsed_relations),
        "saved": saved_count,
        "characters_updated": len(updated_chars)
    }

