"""
实体抽取服务
从章节内容中自动抽取设定项（人物、地点、功法、丹药等）并归类
"""
import re
import json
import logging

logger = logging.getLogger(__name__)
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem
from core.langchain_bridge import get_task_llm
import os

from app.services.setting_categories import SYSTEM_CATEGORIES, TYPE_TO_CATEGORY_MAP

CATEGORY_NAME_MAP = dict(SYSTEM_CATEGORIES)


class EntityExtractionService:
    """实体抽取服务"""

    ENTITY_TYPE_TO_CATEGORY = dict(TYPE_TO_CATEGORY_MAP)
    ENTITY_TYPE_TO_CATEGORY.update({
        "NPC": "character_system",
        "灵兽": "character_system",
        "妖兽": "character_system",
        "魔兽": "character_system",
        "宠物": "character_system",
        "修炼境界": "cultivation_realm_system",
        "武功": "technique_system",
        "心法": "technique_system",
        "秘法": "technique_system",
        "秘术": "technique_system",
        "术法": "technique_system",
        "丹方": "pill_system",
        "禁制": "formation_system",
        "灵宝": "weapon_system",
        "仙器": "weapon_system",
        "宝物": "special_artifact_relic_system",
        "神器": "weapon_system",
        "灵石": "resource_system",
        "矿石": "resource_system",
        "灵物": "resource_system",
        "洞府": "map_system",
        "家族": "organization_force_system",
        "帮派": "organization_force_system",
        "商会": "wealth_business_empire_system",
        "符文": "talisman_system",
        "符咒": "talisman_system",
        "异能者": "ability_system",
        "觉醒": "ability_realm_system",
        "血脉": "race_bloodline_system",
        "种族": "race_bloodline_system",
        "妖族": "race_bloodline_system",
        "龙族": "race_bloodline_system",
        "精灵": "race_bloodline_system",
        "官制": "power_official_system",
        "官职": "power_official_system",
        "军事": "military_warfare_system",
        "战争": "military_warfare_system",
        "经济": "economy_taxation_system",
        "礼制": "culture_etiquette_examination_system",
        "科举": "culture_etiquette_examination_system",
        "律法": "legal_criminal_system",
        "情报": "communication_intelligence_system",
        "历史": "historical_event_legend_system",
        "传说": "historical_event_legend_system",
        "风俗": "lifestyle_custom_system",
    })
    
    # Phase 6: 关系类型枚举
    RELATION_TYPES = {
        # 位置关系
        "位于": "located_in",
        "驻地": "stationed_at",
        # 所属关系
        "属于": "belongs_to",
        "掌握": "masters",
        "拥有": "possesses",
        # 对立关系
        "对立": "opposes",
        "敌对": "enemy_of",
        # 协作关系
        "同盟": "allied_with",
        "合作": "cooperates_with",
        # 其他
        "前置": "prerequisite_of",
        "包含": "contains",
        "相关": "related_to",
    }

    @staticmethod
    async def extract_entities_from_chapter(
        chapter_title: str,
        chapter_content: str,
        project_id: int,
    ) -> List[Dict[str, Any]]:
        """
        从章节内容中抽取实体
        
        返回格式: [
            {
                "name": "实体名称",
                "type": "实体类型（人物/地点/功法等）",
                "content": "实体描述",
                "confidence": 0.7
            }
        ]
        """
        # 🛡️ 使用单例管理器获取LLM实例（已禁用代理）
        llm = get_task_llm("entity_extract")
        
        prompt = f"""你是一个小说设定提取专家。请从以下章节中提取所有重要的设定元素，包括：
- 人物/角色（主要配角、重要NPC等）
- 境界（修为境界、等级，如炼气期、筑基期等）
- 资源（灵草、灵石、材料等，如凝露草、金辉石等）
- 功法/技能/武学
- 丹药/灵丹
- 阵法/结界/禁制
- 法宝/武器/灵器
- 势力/门派/组织/家族
- 地点（城市、秘境、遗迹、洞府等）
- 符箓（符文、符印等）
- 魔法（分类/术法）
- 职业（战士/法师等）

章节标题：{chapter_title}

章节内容：
{chapter_content[:3000]}

请以JSON格式返回，格式如下：
[
  {{
    "name": "实体名称",
    "type": "实体类型（人物/境界/资源/功法/丹药/阵法/法宝/势力/地点/符箓/魔法/职业之一）",
    "content": "实体的详细描述（不少于30字）",
    "confidence": 0.8
  }}
]

注意：
1. 只提取有详细描述的实体，仅提及名称的不要提取
2. confidence范围0-1，根据描述详细程度和重要性打分
3. 确保返回的是合法的JSON数组
4. 境界类型用于修炼境界、等级体系；资源类型用于灵草、灵石、练器材料等
"""
        
        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 尝试解析JSON
            # 清理可能的markdown代码块
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = content.strip()
            
            entities = json.loads(content)
            
            # 验证格式
            if not isinstance(entities, list):
                return []
            
            validated = []
            for e in entities:
                if all(k in e for k in ['name', 'type', 'content']):
                    if 'confidence' not in e:
                        e['confidence'] = 0.6
                    validated.append(e)
            
            return validated
            
        except Exception as e:
            logger.debug(f"实体抽取失败: {e}")
            return []
    
    @staticmethod
    async def extract_relations_from_chapter(
        chapter_title: str,
        chapter_content: str,
        entities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        从章节内容中抽取实体间关系
        
        返回格式: [
            {
                "source": "实体A名称",
                "target": "实体B名称",
                "relation_type": "关系类型",
                "confidence": 0.7
            }
        ]
        """
        if not entities or len(entities) < 2:
            return []
        
        # 🛡️ 使用单例管理器获取LLM实例（已禁用代理）
        llm = get_task_llm("entity_extract")
        
        entity_names = [e["name"] for e in entities]
        entity_list_str = "\n".join([f"- {name}" for name in entity_names])
        
        prompt = f"""你是一个小说设定关系提取专家。请从以下章节中提取已识别实体之间的关系。

章节标题：{chapter_title}

已识别实体：
{entity_list_str}

章节内容（摘要）：
{chapter_content[:2000]}

请提取这些实体之间的关系，包括：
- 位置关系：位于、驻地
- 所属关系：属于、掌握、拥有
- 对立关系：对立、敌对
- 协作关系：同盟、合作
- 其他：前置、包含、相关

请以JSON格式返回，格式如下：
[
  {{
    "source": "实体A名称",
    "target": "实体B名称",
    "relation_type": "关系类型（位于/驻地/属于/掌握/拥有/对立/敌对/同盟/合作/前置/包含/相关）",
    "confidence": 0.8
  }}
]

注意：
1. 只提取明确描述的关系
2. source和target必须都在上述实体列表中
3. confidence范围0-1，根据关系描述的明确性打分
4. 确保返回的是合法的JSON数组
"""
        
        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 清理markdown代码块
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = content.strip()
            
            relations = json.loads(content)
            
            if not isinstance(relations, list):
                return []
            
            validated = []
            for r in relations:
                if all(k in r for k in ['source', 'target', 'relation_type']):
                    # 验证实体名称存在
                    if r['source'] in entity_names and r['target'] in entity_names:
                        if 'confidence' not in r:
                            r['confidence'] = 0.6
                        validated.append(r)
            
            return validated
            
        except Exception as e:
            logger.debug(f"关系抽取失败: {e}")
            return []

    @staticmethod
    def classify_and_save_entities(
        db: Session,
        project_id: int,
        entities: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        归类并保存抽取的实体到对应集合
        
        优先直写规则：
        - 如果存在对应的正式集合，直接写入
        - 否则写入候选集合，并标记"推荐归类"
        
        返回: {
            "saved_to_formal": int,
            "saved_to_candidate": int,
            "skipped": int,
            "details": [...]
        }
        """
        saved_to_formal = 0
        saved_to_candidate = 0
        skipped = 0
        details = []
        
        # 获取或创建候选集合
        candidate_collection = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "candidate",
            )
            .first()
        )
        
        if not candidate_collection:
            candidate_collection = SettingCollection(
                project_id=project_id,
                name="设定候选",
                category="candidate",
                description="自动抽取的设定项，等待人工确认",
                order=999,
            )
            db.add(candidate_collection)
            db.commit()
            db.refresh(candidate_collection)
        
        for entity in entities:
            name = entity.get("name", "").strip()
            typ = entity.get("type", "").strip()
            content = entity.get("content", "").strip()
            confidence = entity.get("confidence", 0.6)
            
            if not name or not content:
                skipped += 1
                continue
            
            # 查找目标分类
            target_category = EntityExtractionService.ENTITY_TYPE_TO_CATEGORY.get(typ)

            if not target_category and typ:
                for cat_key in TYPE_TO_CATEGORY_MAP:
                    if cat_key in typ or typ in cat_key:
                        target_category = TYPE_TO_CATEGORY_MAP[cat_key]
                        break

            if not target_category and typ:
                from app.services.setting_categories import SYSTEM_CATEGORIES
                for cat_key, cat_label in SYSTEM_CATEGORIES.items():
                    if typ in cat_label or cat_label in typ:
                        target_category = cat_key
                        break
            
            target_collection = None
            if target_category:
                target_collection = (
                    db.query(SettingCollection)
                    .filter(
                        SettingCollection.project_id == project_id,
                        SettingCollection.category == target_category,
                    )
                    .first()
                )
                
                # 🌟 如果目标集合不存在，自动创建
                if not target_collection and target_category in CATEGORY_NAME_MAP:
                    collection_name = CATEGORY_NAME_MAP[target_category]
                    target_collection = SettingCollection(
                        project_id=project_id,
                        name=collection_name,
                        category=target_category,
                        description=f"自动创建的{collection_name}",
                        order=100,
                    )
                    db.add(target_collection)
                    db.commit()
                    db.refresh(target_collection)
                    logger.debug(f"✅ 自动创建集合: {collection_name} ({target_category})")
            
            # 优先直写规则
            if target_collection:
                # 检查是否已存在
                existing = (
                    db.query(SettingItem)
                    .filter(
                        SettingItem.collection_id == target_collection.id,
                        SettingItem.name == name,
                    )
                    .first()
                )
                
                if existing:
                    # 更新现有项（如果新内容更详细）
                    if len(content) > len(existing.content or ""):
                        existing.content = content
                        existing.confidence_score = confidence
                        db.commit()
                        saved_to_formal += 1
                        details.append({
                            "name": name,
                            "type": typ,
                            "action": "updated_in_formal",
                            "collection": target_collection.name,
                        })
                    else:
                        skipped += 1
                        details.append({
                            "name": name,
                            "type": typ,
                            "action": "skipped_existing",
                        })
                else:
                    # 创建新项（带层级信息）
                    # 根据实体类型设置默认层级
                    depth = 0
                    node_type = "item"
                    is_leaf = True
                    path = f"/{name}"
                    
                    new_item = SettingItem(
                        collection_id=target_collection.id,
                        name=name,
                        content=f"类型：{typ}\n\n{content}",
                        tags=json.dumps(["自动抽取"], ensure_ascii=False),
                        confidence_score=confidence,
                        order=0,
                        # Phase 5: 层级智能归位
                        depth=depth,
                        node_type=node_type,
                        is_leaf=is_leaf,
                        path=path,
                        summary=content[:100] if len(content) > 100 else content,  # 摘要
                    )
                    db.add(new_item)
                    db.commit()
                    saved_to_formal += 1
                    details.append({
                        "name": name,
                        "type": typ,
                        "action": "created_in_formal",
                        "collection": target_collection.name,
                    })
            else:
                # 写入候选集合
                existing_candidate = (
                    db.query(SettingItem)
                    .filter(
                        SettingItem.collection_id == candidate_collection.id,
                        SettingItem.name == name,
                    )
                    .first()
                )
                
                if existing_candidate:
                    if len(content) > len(existing_candidate.content or ""):
                        existing_candidate.content = f"类型：{typ}\n\n{content}"
                        existing_candidate.confidence_score = confidence
                        db.commit()
                        saved_to_candidate += 1
                        details.append({
                            "name": name,
                            "type": typ,
                            "action": "updated_in_candidate",
                        })
                    else:
                        skipped += 1
                        details.append({
                            "name": name,
                            "type": typ,
                            "action": "skipped_existing_candidate",
                        })
                else:
                    new_candidate = SettingItem(
                        collection_id=candidate_collection.id,
                        name=name,
                        content=f"类型：{typ}\n推荐归类：{target_category or '未知'}\n\n{content}",
                        tags=json.dumps(["候选", "自动抽取"], ensure_ascii=False),
                        confidence_score=confidence,
                        order=0,
                        # Phase 5: 候选项也设置基础层级信息
                        depth=0,
                        node_type="item",
                        is_leaf=True,
                        path=f"/{name}",
                        summary=content[:100] if len(content) > 100 else content,
                    )
                    db.add(new_candidate)
                    db.commit()
                    saved_to_candidate += 1
                    details.append({
                        "name": name,
                        "type": typ,
                        "action": "created_in_candidate",
                        "recommended_category": target_category,
                    })
        
        db.commit()
        
        return {
            "saved_to_formal": saved_to_formal,
            "saved_to_candidate": saved_to_candidate,
            "skipped": skipped,
            "details": details,
        }

