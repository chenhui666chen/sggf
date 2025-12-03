"""
章节后处理服务：章节完成后的自动归纳和更新

在章节创作完成后自动执行：
1. 实体提取
2. 人物出场记录更新
3. 设定项引用追踪
4. 新实体自动创建
5. 向量库更新
"""
import json
from typing import Dict, Any, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.character import Character
from app.models.setting import SettingItem, SettingCollection
from app.models.chapter import Chapter
from app.services.entity_extractor import EntityExtractor
from app.services.llm_service import LLMService


class ChapterPostProcessor:
    """章节后处理器"""
    
    def __init__(self, db: AsyncSession, llm_service: LLMService):
        self.db = db
        self.entity_extractor = EntityExtractor(llm_service)
    
    async def process_chapter(self, chapter_id: int, project_id: int):
        """
        处理章节完成后的自动归纳
        
        Args:
            chapter_id: 章节ID
            project_id: 项目ID
        """
        print(f"\n🚀 开始处理章节 {chapter_id} 的自动归纳...")
        
        # 1. 获取章节内容
        chapter = await self._get_chapter(chapter_id)
        if not chapter or not chapter.content:
            print("⚠️ 章节不存在或内容为空")
            return
        
        print(f"📖 章节内容长度: {len(chapter.content)} 字")
        
        # 2. 提取实体
        entities = await self.entity_extractor.extract_entities_from_chapter(
            chapter.content, project_id, self.db
        )
        
        print(f"✅ 实体提取完成:")
        print(f"  - 人物: {len(entities['characters'])} 个")
        print(f"  - 地点: {len(entities['locations'])} 个")
        print(f"  - 功法: {len(entities['techniques'])} 个")
        print(f"  - 法宝: {len(entities['artifacts'])} 个")
        print(f"  - 境界: {len(entities['realms'])} 个")
        print(f"  - 势力: {len(entities['factions'])} 个")
        
        # 3. 更新人物出场记录
        await self._update_character_appearances(entities['characters'], chapter_id, project_id)
        
        # 4. 更新设定项引用记录
        await self._update_setting_references(entities, chapter_id, project_id)
        
        # 5. 自动创建新实体（置信度较低，需人工确认）
        await self._auto_create_new_entities(entities, project_id)
        
        print(f"✅ 章节 {chapter_id} 自动归纳完成！")
    
    async def _get_chapter(self, chapter_id: int) -> Chapter:
        """获取章节"""
        stmt = select(Chapter).where(Chapter.id == chapter_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _update_character_appearances(
        self, 
        character_entities: List[Dict], 
        chapter_id: int,
        project_id: int
    ):
        """更新人物出场记录"""
        print(f"\n👤 更新人物出场记录...")
        
        for entity in character_entities:
            char_name = entity.get("name")
            if not char_name:
                continue
            
            # 查找人物
            stmt = select(Character).where(
                Character.project_id == project_id,
                Character.name == char_name
            )
            result = await self.db.execute(stmt)
            character = result.scalar_one_or_none()
            
            if character:
                await self.entity_extractor.update_character_appearance(
                    character.id, chapter_id, self.db
                )
                print(f"  ✓ 更新 {char_name} 的出场记录")
            else:
                print(f"  ⚠️ 未找到人物: {char_name}（可能是新人物）")
    
    async def _update_setting_references(
        self, 
        entities: Dict[str, List], 
        chapter_id: int,
        project_id: int
    ):
        """更新设定项引用记录"""
        print(f"\n⚙️ 更新设定项引用记录...")
        
        # 处理各类设定项
        entity_type_mapping = {
            "locations": "map_system",
            "techniques": "technique_system",
            "artifacts": "artifact_system",
            "realms": "cultivation_realm_system",
            "factions": "force_system"
        }
        
        for entity_key, category in entity_type_mapping.items():
            for entity in entities.get(entity_key, []):
                entity_name = entity.get("name")
                if not entity_name:
                    continue
                
                # 查找设定项
                setting_item = await self._find_setting_item(entity_name, category, project_id)
                
                if setting_item:
                    await self.entity_extractor.update_setting_reference(
                        setting_item.id, chapter_id, self.db
                    )
                    print(f"  ✓ 更新 {entity_name} ({category}) 的引用记录")
    
    async def _find_setting_item(
        self, 
        name: str, 
        category: str, 
        project_id: int
    ) -> SettingItem:
        """查找设定项"""
        # 先找到对应的集合
        stmt = select(SettingCollection).where(
            SettingCollection.project_id == project_id,
            SettingCollection.category == category
        )
        result = await self.db.execute(stmt)
        collection = result.scalar_one_or_none()
        
        if not collection:
            return None
        
        # 再找设定项
        stmt = select(SettingItem).where(
            SettingItem.collection_id == collection.id,
            SettingItem.name == name
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def _auto_create_new_entities(self, entities: Dict[str, List], project_id: int):
        """自动创建新实体（如果不存在）"""
        print(f"\n🆕 检查并创建新实体...")
        
        entity_type_mapping = {
            "locations": "map_system",
            "techniques": "technique_system",
            "artifacts": "artifact_system",
            "realms": "cultivation_realm_system",
            "factions": "force_system"
        }
        
        created_count = 0
        
        for entity_key, category in entity_type_mapping.items():
            for entity in entities.get(entity_key, []):
                entity_name = entity.get("name")
                if not entity_name:
                    continue
                
                # 检查是否已存在
                setting_item = await self._find_setting_item(entity_name, category, project_id)
                
                if not setting_item:
                    # 自动创建
                    metadata = {k: v for k, v in entity.items() if k != "name"}
                    item_id = await self.entity_extractor.auto_create_setting_item(
                        entity_name, category, project_id, self.db, metadata
                    )
                    if item_id:
                        created_count += 1
                        print(f"  🆕 创建新设定项: {entity_name} ({category})")
        
        if created_count > 0:
            print(f"\n✅ 共自动创建 {created_count} 个新设定项（置信度0.6，建议人工确认）")
        else:
            print(f"\n✓ 无需创建新设定项")


async def auto_process_chapter(chapter_id: int, project_id: int, db: AsyncSession):
    """
    便捷函数：自动处理章节
    
    可在章节创作完成后调用
    """
    from app.services.llm_service import get_llm_service
    
    llm_service = get_llm_service()
    processor = ChapterPostProcessor(db, llm_service)
    await processor.process_chapter(chapter_id, project_id)
