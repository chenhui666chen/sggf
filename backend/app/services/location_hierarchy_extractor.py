"""
地点层级提取服务
从章节内容中智能提取地点的层级关系并自动构建地图树
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem
from app.services.agents.llm_factory import LLMFactory


class LocationHierarchyExtractor:
    """地点层级提取器"""
    
    @staticmethod
    async def extract_location_hierarchy(
        chapter_title: str,
        chapter_content: str,
    ) -> List[Dict[str, Any]]:
        """
        从章节内容中提取地点及其层级关系
        
        返回格式: [
            {
                "name": "青云宗",
                "level": 1,  # 1=大陆级, 2=区域级, 3=地点级, 4=详细级
                "parent": null,  # 父节点名称
                "description": "描述",
                "category": "城镇聚落"  # 大陆版图/区域地形/城镇聚落/秘境禁地/交通网络
            },
            {
                "name": "青云峰",
                "level": 2,
                "parent": "青云宗",
                "description": "描述",
                "category": "区域地形"
            }
        ]
        """
        llm = LLMFactory.create_llm()
        
        prompt = f"""你是一个小说地点提取专家。请从以下章节中提取所有地点，并识别它们的层级关系。

章节标题：{chapter_title}

章节内容：
{chapter_content[:3000]}

请按照以下规则提取：

1. **地点分类**（category）：
   - 大陆版图：大陆、王国、帝国、国度
   - 区域地形：山脉、峰、谷、平原、森林、沙漠
   - 城镇聚落：宗门、城市、村庄、镇、坊市
   - 秘境禁地：秘境、遗迹、禁地、险地
   - 交通网络：道路、传送阵、航线

2. **层级关系**（level）：
   - level 1: 最大范围（如"修仙界"、"东域"）
   - level 2: 中等范围（如"青云宗"、"玄天山脉"）
   - level 3: 具体地点（如"青云峰"、"藏经阁"）
   - level 4: 详细位置（如"三楼东侧"、"后山洞府"）

3. **父子关系**（parent）：
   - 如果地点A包含地点B，则B的parent是A的名称
   - 例如："藏经阁"位于"青云峰"，则parent="青云峰"

请以JSON格式返回：
[
  {{
    "name": "地点名称",
    "level": 1-4,
    "parent": "父地点名称或null",
    "description": "地点描述（30-100字）",
    "category": "分类（大陆版图/区域地形/城镇聚落/秘境禁地/交通网络之一）"
  }}
]

注意：
1. 只提取有明确描述的地点
2. parent必须是已提取的地点之一
3. level必须是1-4之间的整数
4. 确保返回合法的JSON数组
"""
        
        try:
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # 清理markdown代码块
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*$', '', content)
            content = content.strip()
            
            locations = json.loads(content)
            
            if not isinstance(locations, list):
                return []
            
            # 验证格式
            validated = []
            location_names = set()
            
            for loc in locations:
                if not all(k in loc for k in ['name', 'level', 'category']):
                    continue
                
                # 验证level范围
                if not isinstance(loc['level'], int) or loc['level'] < 1 or loc['level'] > 4:
                    loc['level'] = 2  # 默认为中等范围
                
                # 确保parent存在或为null
                if 'parent' not in loc:
                    loc['parent'] = None
                
                # 确保description存在
                if 'description' not in loc:
                    loc['description'] = f"{loc['name']}是一处{loc['category']}"
                
                location_names.add(loc['name'])
                validated.append(loc)
            
            # 验证parent有效性（parent必须是已提取的地点之一）
            for loc in validated:
                if loc['parent'] and loc['parent'] not in location_names:
                    loc['parent'] = None  # 无效的parent设为null
            
            return validated
            
        except Exception as e:
            print(f"地点层级提取失败: {e}")
            return []
    
    @staticmethod
    def save_location_hierarchy(
        db: Session,
        project_id: int,
        locations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        将提取的地点层级保存到地图体系
        
        返回: {
            "created": int,
            "updated": int,
            "skipped": int,
            "details": [...]
        }
        """
        # 获取或创建地图体系集合
        map_collection = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "map_system",
            )
            .first()
        )
        
        if not map_collection:
            # 创建地图体系集合
            from app.services.setting_templates import get_hierarchy_config_json
            
            map_collection = SettingCollection(
                project_id=project_id,
                name="地图体系",
                category="map_system",
                description="世界地图与地点设定",
                order=100,
                max_depth=4,
                hierarchy_config=get_hierarchy_config_json("map_system"),
            )
            db.add(map_collection)
            db.commit()
            db.refresh(map_collection)
        
        created = 0
        updated = 0
        skipped = 0
        details = []
        
        # 第一步：创建所有地点节点（不设置parent，先建立ID映射）
        location_id_map = {}  # name -> item_id
        
        for loc in locations:
            name = loc['name']
            level = loc['level']
            category = loc['category']
            description = loc['description']
            
            # 检查是否已存在
            existing = (
                db.query(SettingItem)
                .filter(
                    SettingItem.collection_id == map_collection.id,
                    SettingItem.name == name,
                )
                .first()
            )
            
            if existing:
                # 更新现有项
                if len(description) > len(existing.content or ""):
                    existing.content = description
                    existing.depth = level
                    db.commit()
                    location_id_map[name] = existing.id
                    updated += 1
                    details.append({
                        "name": name,
                        "action": "updated",
                        "level": level,
                    })
                else:
                    location_id_map[name] = existing.id
                    skipped += 1
                    details.append({
                        "name": name,
                        "action": "skipped_existing",
                    })
            else:
                # 创建新项
                # 临时path，后续更新
                new_item = SettingItem(
                    collection_id=map_collection.id,
                    name=name,
                    content=description,
                    tags=json.dumps(["自动提取", category], ensure_ascii=False),
                    depth=level,
                    node_type="detail" if level == 4 else "category",
                    is_leaf=(level == 4),
                    path=f"/{map_collection.name}/{name}",  # 临时path
                    summary=description[:100] if len(description) > 100 else description,
                    order=0,
                    confidence_score=0.7,
                )
                db.add(new_item)
                db.commit()
                db.refresh(new_item)
                
                location_id_map[name] = new_item.id
                created += 1
                details.append({
                    "name": name,
                    "action": "created",
                    "level": level,
                    "category": category,
                })
        
        # 第二步：更新path（基于parent关系构建完整路径）
        for loc in locations:
            name = loc['name']
            parent_name = loc.get('parent')
            
            if name not in location_id_map:
                continue
            
            item = db.query(SettingItem).get(location_id_map[name])
            if not item:
                continue
            
            # 构建完整路径
            path_parts = [map_collection.name]
            
            # 根据category添加分类层
            category_map = {
                "大陆版图": "大陆版图",
                "区域地形": "区域地形",
                "城镇聚落": "城镇聚落",
                "秘境禁地": "秘境禁地",
                "交通网络": "交通网络",
            }
            
            category_name = category_map.get(loc['category'], "其他地点")
            path_parts.append(category_name)
            
            # 添加父节点路径
            if parent_name and parent_name in location_id_map:
                path_parts.append(parent_name)
            
            # 添加当前节点
            path_parts.append(name)
            
            # 更新path
            item.path = "/" + "/".join(path_parts)
            db.commit()
        
        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "details": details,
        }
