"""
自动追踪服务：简化版本，用于更新人物出场和设定引用

Phase 2: 自动提取与更新服务
"""
import json
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.character import Character
from app.models.setting import SettingItem, SettingCollection


class AutoTrackingService:
    """自动追踪服务（简化版）"""
    
    @staticmethod
    def update_character_appearances(
        chapter_id: int,
        chapter_content: str,
        project_id: int,
        db: Session
    ) -> Dict[str, int]:
        """
        更新人物出场记录（基于简单匹配）
        
        Returns:
            {"updated_count": 3}
        """
        # 获取项目所有人物
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        
        updated_count = 0
        
        for character in characters:
            # 简单匹配：如果人物名称在章节内容中出现
            if character.name and character.name in chapter_content:
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
                    updated_count += 1
        
        db.commit()
        return {"updated_count": updated_count}
    
    @staticmethod
    def update_setting_references(
        chapter_id: int,
        chapter_content: str,
        project_id: int,
        db: Session
    ) -> Dict[str, int]:
        """
        更新设定项引用记录（基于简单匹配）
        
        Returns:
            {"updated_count": 5}
        """
        # 获取项目所有设定集合
        collections = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).all()
        
        updated_count = 0
        
        for collection in collections:
            # 获取该集合的所有设定项
            items = db.query(SettingItem).filter(
                SettingItem.collection_id == collection.id
            ).all()
            
            for item in items:
                # 简单匹配：如果设定项名称在章节内容中出现
                if item.name and item.name in chapter_content:
                    # 更新引用章节列表
                    referenced_chapters = json.loads(item.referenced_chapters or "[]")
                    if chapter_id not in referenced_chapters:
                        referenced_chapters.append(chapter_id)
                        item.referenced_chapters = json.dumps(referenced_chapters)
                        
                        # 更新使用次数
                        item.usage_count = len(referenced_chapters)
                        
                        # 更新最后引用时间
                        item.last_referenced_at = datetime.now()
                        
                        updated_count += 1
        
        db.commit()
        return {"updated_count": updated_count}
    
    @staticmethod
    def auto_link_character_to_settings(
        character_id: int,
        db: Session
    ) -> Dict[str, any]:
        """
        自动关联人物与设定项（根据名称匹配）
        
        例如：
        - 如果人物的faction字段是"天剑宗"，自动链接到force_system中的"天剑宗"设定项
        - 如果人物的current_realm字段是"筑基期"，自动链接到realm_system中的"筑基期"设定项
        """
        character = db.query(Character).filter(Character.id == character_id).first()
        if not character:
            return {"error": "Character not found"}
        
        project_id = character.project_id
        updated_fields = []
        
        # 1. 关联所属势力
        if character.faction and not character.faction_item_id:
            faction_item = AutoTrackingService._find_setting_item_by_name(
                character.faction, "force_system", project_id, db
            )
            if faction_item:
                character.faction_item_id = faction_item.id
                updated_fields.append("faction_item_id")
        
        # 2. 关联当前境界（如果有current_realm字段）
        # 注意：这里假设Character模型有current_realm字段（字符串），需要关联到current_realm_item_id
        # 实际实现需要根据您的模型结构调整
        
        if updated_fields:
            db.commit()
        
        return {"updated_fields": updated_fields}
    
    @staticmethod
    def _find_setting_item_by_name(
        name: str,
        category: str,
        project_id: int,
        db: Session
    ) -> Optional[SettingItem]:
        """根据名称和类别查找设定项"""
        collection = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == category
        ).first()
        
        if not collection:
            return None
        
        item = db.query(SettingItem).filter(
            SettingItem.collection_id == collection.id,
            SettingItem.name == name
        ).first()
        
        return item
