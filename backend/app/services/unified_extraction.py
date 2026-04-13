"""
统一实体提取服务
一次性调用AI提取：实体 + 地点层级 + 实体关系 + 人物关系
目标：将多次AI调用合并为1次，减少耗时
"""
import re
import json
import logging

logger = logging.getLogger(__name__)
from typing import List, Dict, Any, Optional
import os
from core.langchain_bridge import create_model_llm


class UnifiedExtractionService:
    """统一提取服务 - 一次性提取所有信息"""
    
    @staticmethod
    async def extract_all_from_chapter(
        chapter_title: str,
        chapter_content: str,
        project_id: int,
    ) -> Dict[str, Any]:
        """
        一次性从章节内容中提取所有信息
        
        返回格式: {
            "entities": [
                {
                    "name": "实体名称",
                    "type": "实体类型",
                    "content": "实体描述",
                    "confidence": 0.7
                }
            ],
            "locations": [
                {
                    "name": "地点名称",
                    "level": 2,
                    "parent": "父地点",
                    "description": "描述",
                    "category": "城镇聚落"
                }
            ],
            "relations": [
                {
                    "source": "实体A",
                    "target": "实体B",
                    "relation_type": "关系类型",
                    "confidence": 0.7
                }
            ],
            "character_relations": [
                {
                    "source": "人物A",
                    "target": "人物B",
                    "relation_type": "师徒/恋人/仇敌等",
                    "description": "关系描述"
                }
            ]
        }
        """
        # 创建LLM实例
        model = (
            os.getenv("UNIFIED_EXTRACTION_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or os.getenv("MODEL_NAME")
            or "deepseek-reasoner"
        )
        llm = create_model_llm(model=model, temperature=0.7)
        
        # 构建统一提示词
        prompt = f"""你是一个小说设定提取专家。请从以下章节中**一次性**提取所有重要信息，包括：

**第一部分：实体提取**
提取所有重要的设定元素，type必须从以下列表中选择：
- 人物（含灵兽、妖兽、魔兽等有意识存在）
- 境界（含修为、等级、修炼境界）
- 功法（含武学、武功、心法、秘法、秘术、术法、技能）
- 丹药（含丹方、灵丹）
- 阵法（含结界、禁制）
- 法宝（含武器、灵器、灵宝、仙器、神器）
- 资源（含灵草、灵石、材料、矿石、灵物）
- 地点（含秘境、遗迹、城市、城镇、洞府）
- 势力（含门派、宗门、组织、家族、帮派、商会）
- 符箓（含符文、符咒）
- 魔法（含魔法分类、术法）
- 职业（含战士、法师等）
- 武道（含武道境界）
- 异能（含超能力、异能者）
- 道具（含遗物、宝物）
- 血脉（含种族、妖族、龙族、精灵）
- 官制（含官职）
- 军事（含战争）
- 经济（含税收、商业）
- 礼制（含科举）
- 律法（含刑罚）
- 情报（含通讯）
- 历史（含传说）
- 风俗（含民生）
- 人脉（含关系）

**第二部分：地点层级**
提取所有地点并识别层级关系：
- 分类：大陆版图/区域地形/城镇聚落/秘境禁地/交通网络
- 层级：1=最大范围，2=中等范围，3=具体地点，4=详细位置
- 父子关系：如"藏经阁"位于"青云峰"，则parent="青云峰"

**第三部分：实体关系**
提取实体之间的关系：
- 位置关系：位于、驻地
- 所属关系：属于、掌握、拥有
- 对立关系：对立、敌对
- 协作关系：同盟、合作
- 其他：前置、包含、相关

**第四部分：人物关系（重要！）**
提取人物与人物之间的关系：
- 血缘关系：父子、母女、兄弟、姐妹
- 情感关系：恋人、夫妻、暗恋
- 师承关系：师徒、同门
- 对立关系：仇敌、对手、竞争者
- 社交关系：朋友、同伴、盟友
- 从属关系：主仆、上下级

---

**章节标题**：{chapter_title}

**章节内容**：
{chapter_content[:4000]}

---

**请以JSON格式返回**，格式如下：
{{
  "entities": [
    {{
      "name": "实体名称",
      "type": "实体类型（必须从以下选择：人物/境界/功法/丹药/阵法/法宝/资源/地点/势力/符箓/魔法/职业/武道/异能/道具/血脉/官制/军事/经济/礼制/律法/情报/历史/风俗/人脉）",
      "content": "详细描述（不少于30字）",
      "confidence": 0.8
    }}
  ],
  "locations": [
    {{
      "name": "地点名称",
      "level": 2,
      "parent": "父地点名称或null",
      "description": "地点描述（30-100字）",
      "category": "分类（大陆版图/区域地形/城镇聚落/秘境禁地/交通网络之一）"
    }}
  ],
  "relations": [
    {{
      "source": "实体A名称",
      "target": "实体B名称",
      "relation_type": "关系类型（位于/属于/掌握/拥有/对立/敌对/同盟/合作/相关之一）",
      "confidence": 0.7
    }}
  ],
  "character_relations": [
    {{
      "source": "人物A名称",
      "target": "人物B名称",
      "relation_type": "关系类型（师徒/同门/恋人/夫妻/父子/母女/兄弟/姐妹/仇敌/对手/朋友/同伴/盟友/主仆/上下级之一）",
      "description": "关系简短描述（20字以内）"
    }}
  ]
}}

**注意**：
1. 只提取有详细描述的内容，仅提及名称的不要提取
2. confidence范围0-1，根据描述详细程度和重要性打分
3. relations中的source和target必须是entities或locations中已提取的实体名称
4. locations的parent必须是已提取的地点之一或null
5. 确保返回的是合法的JSON对象
6. character_relations中的source和target必须都是人物类型的实体
"""
        
        try:
            # 调用AI
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 清理markdown代码块
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = content.strip()
            
            # 解析JSON
            result = json.loads(content)
            
            # 验证和清理数据
            entities = UnifiedExtractionService._validate_entities(result.get("entities", []))
            validated_result = {
                "entities": entities,
                "locations": UnifiedExtractionService._validate_locations(result.get("locations", [])),
                "relations": UnifiedExtractionService._validate_relations(
                    result.get("relations", []),
                    result.get("entities", []),
                    result.get("locations", [])
                ),
                "character_relations": UnifiedExtractionService._validate_character_relations(
                    result.get("character_relations", []),
                    entities
                )
            }
            
            return validated_result
            
        except Exception as e:
            logger.debug(f"统一提取失败: {e}")
            # 返回空结果
            return {
                "entities": [],
                "locations": [],
                "relations": [],
                "character_relations": []
            }
    
    @staticmethod
    def _validate_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证实体数据格式"""
        if not isinstance(entities, list):
            return []
        
        validated = []
        for e in entities:
            if not isinstance(e, dict):
                continue
            if all(k in e for k in ['name', 'type', 'content']):
                if 'confidence' not in e:
                    e['confidence'] = 0.6
                validated.append(e)
        
        return validated
    
    @staticmethod
    def _validate_locations(locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证地点数据格式"""
        if not isinstance(locations, list):
            return []
        
        validated = []
        location_names = set()
        
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            if not all(k in loc for k in ['name', 'level', 'category']):
                continue
            
            # 验证level范围
            if not isinstance(loc['level'], int) or loc['level'] < 1 or loc['level'] > 4:
                loc['level'] = 2
            
            # 确保parent存在或为null
            if 'parent' not in loc:
                loc['parent'] = None
            
            # 确保description存在
            if 'description' not in loc:
                loc['description'] = f"{loc['name']}是一处{loc['category']}"
            
            location_names.add(loc['name'])
            validated.append(loc)
        
        # 验证parent有效性
        for loc in validated:
            if loc['parent'] and loc['parent'] not in location_names:
                loc['parent'] = None
        
        return validated
    
    @staticmethod
    def _validate_relations(
        relations: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        locations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """验证关系数据格式"""
        if not isinstance(relations, list):
            return []
        
        # 构建有效实体名称集合
        valid_names = set()
        for e in entities:
            if isinstance(e, dict) and 'name' in e:
                valid_names.add(e['name'])
        for loc in locations:
            if isinstance(loc, dict) and 'name' in loc:
                valid_names.add(loc['name'])
        
        validated = []
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            if not all(k in rel for k in ['source', 'target', 'relation_type']):
                continue
            
            # 验证source和target是否有效
            if rel['source'] not in valid_names or rel['target'] not in valid_names:
                continue
            
            if 'confidence' not in rel:
                rel['confidence'] = 0.6
            
            validated.append(rel)
        
        return validated

    @staticmethod
    def _validate_character_relations(
        relations: List[Dict[str, Any]],
        entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """验证人物关系数据格式"""
        if not isinstance(relations, list):
            return []
        
        # 构建人物名称集合
        character_names = set()
        for e in entities:
            if isinstance(e, dict) and 'name' in e:
                # 只包含人物类型的实体
                if e.get('type', '') in ['人物', '角色', 'character', 'person']:
                    character_names.add(e['name'])
        
        # 如果没有识别到人物，放宽限制，也保留关系
        if not character_names:
            for e in entities:
                if isinstance(e, dict) and 'name' in e:
                    character_names.add(e['name'])
        
        validated = []
        seen_pairs = set()  # 用于去重
        
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            if not all(k in rel for k in ['source', 'target', 'relation_type']):
                continue
            
            source = rel['source']
            target = rel['target']
            
            # source和target不能相同
            if source == target:
                continue
            
            # 去重（不区分方向）
            pair = tuple(sorted([source, target]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            
            # 确保有description字段
            if 'description' not in rel:
                rel['description'] = rel['relation_type']
            
            validated.append(rel)
        
        return validated

