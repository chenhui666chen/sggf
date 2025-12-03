"""
统一实体提取服务
一次性调用AI提取：实体 + 地点层级 + 关系
目标：将3次AI调用合并为1次，减少耗时从30-90秒到10-40秒
"""
import re
import json
from typing import List, Dict, Any, Optional
from langchain_community.chat_models import ChatOpenAI
import os


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
            ]
        }
        """
        # 创建LLM实例
        llm = ChatOpenAI(
            model_name=os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner"),
            temperature=0.7,
            openai_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            openai_api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        )
        
        # 构建统一提示词
        prompt = f"""你是一个小说设定提取专家。请从以下章节中**一次性**提取所有重要信息，包括：

**第一部分：实体提取**
提取所有重要的设定元素：
- 人物/角色（主要配角、重要NPC）
- 功法/技能/武学
- 丹药/法宝/道具
- 阵法/结界
- 势力/门派/组织
- 魔法（分类/术法）
- 职业（战士/法师等）
- 武道境界

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
      "type": "实体类型（人物/功法/丹药/阵法/势力/魔法/职业/武道之一）",
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
  ]
}}

**注意**：
1. 只提取有详细描述的内容，仅提及名称的不要提取
2. confidence范围0-1，根据描述详细程度和重要性打分
3. relations中的source和target必须是entities或locations中已提取的实体名称
4. locations的parent必须是已提取的地点之一或null
5. 确保返回的是合法的JSON对象
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
            validated_result = {
                "entities": UnifiedExtractionService._validate_entities(result.get("entities", [])),
                "locations": UnifiedExtractionService._validate_locations(result.get("locations", [])),
                "relations": UnifiedExtractionService._validate_relations(
                    result.get("relations", []),
                    result.get("entities", []),
                    result.get("locations", [])
                )
            }
            
            return validated_result
            
        except Exception as e:
            print(f"统一提取失败: {e}")
            # 返回空结果
            return {
                "entities": [],
                "locations": [],
                "relations": []
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
