"""
人物卡数据库同步

将解析后的人物卡同步到数据库
"""
import json
import logging
from typing import Dict, List, Any

from app.services.character_runtime_context import (
    build_character_relations_payload,
    extract_character_relation_items,
)

from ._dataclasses import ParsedCharacter
from ._utils import normalize_character_name
from ._parser import CharacterTextParser

logger = logging.getLogger("uvicorn.error")


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

    existing_characters = db_session.query(Character).filter(
        Character.project_id == project_id
    ).all()
    existing_by_norm: Dict[str, Character] = {}
    for item in existing_characters:
        key = normalize_character_name(item.name) or (item.name or "").strip()
        if not key or key in existing_by_norm:
            continue
        existing_by_norm[key] = item

    for parsed in parsed_characters:
        try:
            # 查找已存在的角色（按项目ID和姓名）
            parsed_key = normalize_character_name(parsed.name) or parsed.name.strip()
            existing = existing_by_norm.get(parsed_key)
            if not existing:
                existing = db_session.query(Character).filter(
                    Character.project_id == project_id,
                    Character.name == parsed.name
                ).first()
                if existing and parsed_key:
                    existing_by_norm[parsed_key] = existing

            if existing:
                # 更新已存在的角色
                existing.gender = parsed.gender or existing.gender
                existing.age = parsed.age or existing.age
                existing.role = parsed.role or existing.role
                existing.role_position = parsed.role_position or existing.role_position
                existing.faction = parsed.faction or existing.faction
                existing.importance_level = parsed.importance_level or existing.importance_level
                existing.summary = parsed.build_summary() or existing.summary
                existing.profile = parsed.build_profile() or existing.profile

                # 更新关系字段（JSON格式）
                if parsed.relationships:
                    existing.relations = json.dumps(
                        build_character_relations_payload(parsed.relationships),
                        ensure_ascii=False,
                    )

                updated_count += 1
                logger.debug(f"   📝 更新角色: {parsed.name}")
            else:
                # 创建新角色
                new_char = Character(
                    project_id=project_id,
                    name=parsed.name,
                    gender=parsed.gender,
                    age=parsed.age,
                    role=parsed.role,
                    role_position=parsed.role_position,
                    faction=parsed.faction,
                    importance_level=parsed.importance_level,
                    summary=parsed.build_summary(),
                    profile=parsed.build_profile(),
                    relations=(
                        json.dumps(
                            build_character_relations_payload(parsed.relationships),
                            ensure_ascii=False,
                        )
                        if parsed.relationships
                        else None
                    ),
                    appearance_status="未出场",  # 默认未出场
                    life_status="存活",  # 默认存活
                )
                db_session.add(new_char)
                created_count += 1
                if parsed_key:
                    existing_by_norm[parsed_key] = new_char
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
            existing_relations = json.loads(source_char.relations) if source_char.relations else None
        except Exception:
            existing_relations = source_char.relations or None

        existing_relation_items = extract_character_relation_items(existing_relations)
        
        # 检查是否已存在相同关系
        already_exists = any(
            r.get('target') == target_name and r.get('type') == rel_type
            for r in existing_relation_items if isinstance(r, dict)
        )
        
        if not already_exists:
            # 添加新关系
            new_relation = {
                "target": target_name,
                "type": rel_type
            }
            source_char.relations = json.dumps(
                build_character_relations_payload(
                    {
                        "text": (
                            existing_relations.get("text")
                            if isinstance(existing_relations, dict)
                            else (existing_relations if isinstance(existing_relations, str) else "")
                        ),
                        "items": [*existing_relation_items, new_relation],
                    }
                ),
                ensure_ascii=False,
            )
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
