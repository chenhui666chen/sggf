"""
实体提取服务：从章节内容中识别人物、地点、物品等实体

用于自动更新人物出场记录、设定项引用追踪
"""
import json
import logging

logger = logging.getLogger(__name__)
from typing import List, Dict, Any, Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.character import Character
from app.models.setting import SettingItem, SettingCollection
from app.services.llm_service import LLMService
from app.utils.datetime_utils import utc_now


class EntityExtractor:
    """实体提取器"""
    
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
    
    async def extract_entities_from_chapter(
        self, 
        chapter_content: str, 
        project_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        从章节内容中提取实体
        
        Args:
            chapter_content: 章节文本内容
            project_id: 项目ID
            db: 数据库会话
        
        Returns:
            {
                "characters": [{"name": "主角", "mentions": 5}],
                "locations": [{"name": "某宗门", "type": "map_system"}],
                "techniques": [{"name": "某功法", "type": "technique_system"}],
                "artifacts": [{"name": "某法宝", "type": "weapon_system"}],
                "realms": [{"name": "筑基期", "type": "cultivation_realm_system"}],
                "factions": [{"name": "某势力", "type": "organization_force_system"}]
            }
        """
        # 1. 获取项目的已有人物和设定项
        existing_data = await self._get_existing_entities(project_id, db)
        
        # 2. 构建AI Prompt
        prompt = self._build_extraction_prompt(chapter_content, existing_data)
        
        # 3. 调用AI提取实体
        ai_response = await self.llm_service.chat(prompt)
        
        # 4. 解析AI返回的JSON
        entities = self._parse_extraction_result(ai_response)
        
        return entities
    
    async def _get_existing_entities(self, project_id: int, db: AsyncSession) -> Dict[str, Any]:
        """获取项目已有的人物和设定项"""
        # 查询所有人物
        stmt = select(Character).where(Character.project_id == project_id)
        result = await db.execute(stmt)
        characters = result.scalars().all()
        
        # 查询所有设定集合和设定项
        stmt = select(SettingCollection).where(SettingCollection.project_id == project_id)
        result = await db.execute(stmt)
        collections = result.scalars().all()
        
        settings_by_category = {}
        for coll in collections:
            stmt = select(SettingItem).where(SettingItem.collection_id == coll.id)
            result = await db.execute(stmt)
            items = result.scalars().all()
            settings_by_category[coll.category] = [
                {"id": item.id, "name": item.name} for item in items
            ]
        
        return {
            "characters": [{"id": c.id, "name": c.name} for c in characters],
            "settings": settings_by_category
        }
    
    def _build_extraction_prompt(self, chapter_content: str, existing_data: Dict) -> str:
        """构建实体提取的AI Prompt"""
        prompt = f"""你是一个专业的小说内容分析助手。请从以下章节内容中提取所有提及的实体。

【章节内容】
{chapter_content[:3000]}  # 限制长度避免token过多

【已知实体参考】
人物: {', '.join([c['name'] for c in existing_data['characters'][:20]])}
地点: {', '.join([s['name'] for s in existing_data['settings'].get('map_system', [])[:20]])}
势力: {', '.join([s['name'] for s in existing_data['settings'].get('organization_force_system', [])[:20]])}

【提取要求】
1. 识别所有出现的人物名称（包括代词指代的人物）
2. 识别地点（城镇、秘境、建筑等）
3. 识别功法、武技名称
4. 识别法宝、神器名称
5. 识别境界名称（如筑基期、金丹期等）
6. 识别势力/组织名称

【输出格式】
请严格按照以下JSON格式输出（不要添加任何额外文字）：

```json
{{
  "characters": [
    {{"name": "主角", "mentions": 5, "actions": ["修炼", "战斗"]}},
    {{"name": "配角A", "mentions": 2, "actions": ["对话"]}}
  ],
  "locations": [
    {{"name": "某宗门", "type": "map_system", "mentions": 3}},
    {{"name": "某秘境", "type": "map_system", "mentions": 1}}
  ],
  "techniques": [
    {{"name": "某功法", "type": "technique_system", "level": "玄级上品"}}
  ],
  "artifacts": [
    {{"name": "某法宝", "type": "weapon_system"}}
  ],
  "realms": [
    {{"name": "筑基期", "type": "cultivation_realm_system"}}
  ],
  "factions": [
    {{"name": "某势力", "type": "organization_force_system"}}
  ]
}}
```

现在开始提取：
"""
        return prompt
    
    def _parse_extraction_result(self, ai_response: str) -> Dict[str, Any]:
        """解析AI返回的实体提取结果"""
        try:
            # 提取JSON部分（去除```json包裹）
            json_text = ai_response.strip()
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0].strip()
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0].strip()
            
            entities = json.loads(json_text)
            
            # 验证并标准化格式
            return {
                "characters": entities.get("characters", []),
                "locations": entities.get("locations", []),
                "techniques": entities.get("techniques", []),
                "artifacts": entities.get("artifacts", []),
                "realms": entities.get("realms", []),
                "factions": entities.get("factions", [])
            }
        except json.JSONDecodeError as e:
            logger.debug(f"⚠️ JSON解析失败: {e}")
            logger.debug(f"AI返回内容: {ai_response[:500]}")
            # 返回空结果
            return {
                "characters": [],
                "locations": [],
                "techniques": [],
                "artifacts": [],
                "realms": [],
                "factions": []
            }
    
    def update_character_appearance(
        self, 
        character_id: int, 
        chapter_id: int, 
        db: Session
    ):
        """更新人物出场记录"""
        character = db.query(Character).filter(Character.id == character_id).first()
        
        if not character:
            return
        
        # 更新首次提及
        if character.first_mention_chapter_id is None:
            character.first_mention_chapter_id = chapter_id
        
        # 更新最后出场
        character.last_appearance_chapter_id = chapter_id
        
        # 更新出场章节列表
        appearance_chapters = json.loads(character.appearance_chapters or "[]")
        if chapter_id not in appearance_chapters:
            appearance_chapters.append(chapter_id)
            character.appearance_chapters = json.dumps(appearance_chapters)
        
        db.commit()
    
    def update_setting_reference(
        self, 
        setting_item_id: int, 
        chapter_id: int, 
        db: Session
    ):
        """更新设定项引用记录"""
        setting_item = db.query(SettingItem).filter(SettingItem.id == setting_item_id).first()
        
        if not setting_item:
            return
        
        # 更新引用章节列表
        referenced_chapters = json.loads(setting_item.referenced_chapters or "[]")
        if chapter_id not in referenced_chapters:
            referenced_chapters.append(chapter_id)
            setting_item.referenced_chapters = json.dumps(referenced_chapters)
        
        # 更新使用次数
        setting_item.usage_count = len(referenced_chapters)
        
        # 更新最后引用时间
        setting_item.last_referenced_at = utc_now()
        
        db.commit()
    
    def auto_create_setting_item(
        self,
        entity_name: str,
        category: str,
        project_id: int,
        db: Session,
        metadata: Optional[Dict] = None
    ) -> Optional[int]:
        """
        自动创建新的设定项（如果不存在）
        
        Args:
            entity_name: 实体名称
            category: 体系类型（如map_system, technique_system）
            project_id: 项目ID
            metadata: 额外元数据（如level, type等）
        
        Returns:
            创建的SettingItem的ID，如果已存在则返回None
        """
        # 1. 查找对应的SettingCollection
        collection = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == category
        ).first()
        
        if not collection:
            logger.debug(f"⚠️ 未找到体系: {category}")
            return None
        
        # 2. 检查是否已存在同名设定项
        existing_item = db.query(SettingItem).filter(
            SettingItem.collection_id == collection.id,
            SettingItem.name == entity_name
        ).first()
        
        if existing_item:
            return None  # 已存在，不重复创建
        
        # 3. 创建新设定项
        new_item = SettingItem(
            collection_id=collection.id,
            name=entity_name,
            content=f"【自动提取】从章节内容中识别到的{category}",
            depth=2,  # 默认第2层（详情层）
            is_leaf=True,
            confidence_score=0.6,  # 自动创建的置信度较低
            usage_count=1,
            last_referenced_at=utc_now()
        )
        
        # 添加元数据
        if metadata:
            if 'level' in metadata:
                new_item.content += f"\n等级: {metadata['level']}"
        
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        
        logger.debug(f"✅ 自动创建设定项: {entity_name} ({category})")
        return new_item.id
