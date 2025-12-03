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
    def update_character_appearances_smart(
        chapter_id: int,
        old_content: str,
        new_content: str,
        project_id: int,
        db: Session
    ) -> Dict[str, int]:
        """
        智能检测人物出场变化（基于差异分析）
        
        Args:
            chapter_id: 章节ID
            old_content: 修改前的内容
            new_content: 修改后的内容
            project_id: 项目ID
            db: 数据库会话
        
        Returns:
            {"added": 2, "removed": 1, "unchanged": 5}
        """
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        
        added_count = 0
        removed_count = 0
        unchanged_count = 0
        
        for character in characters:
            name = character.name
            if not name:
                continue
            
            # 检测变化
            was_mentioned = name in old_content
            now_mentioned = name in new_content
            
            # 无变化，跳过
            if was_mentioned == now_mentioned:
                unchanged_count += 1
                continue
            
            appearance_chapters = json.loads(character.appearance_chapters or "[]")
            
            if now_mentioned and not was_mentioned:
                # 🆕 新增出场
                if chapter_id not in appearance_chapters:
                    appearance_chapters.append(chapter_id)
                    added_count += 1
                    print(f"  ✅ {name} 新增出场: 第{chapter_id}章")
            
            elif was_mentioned and not now_mentioned:
                # 🗑️ 移除出场
                if chapter_id in appearance_chapters:
                    appearance_chapters.remove(chapter_id)
                    removed_count += 1
                    print(f"  ❌ {name} 移除出场: 第{chapter_id}章")
            
            # 更新出场章节列表
            character.appearance_chapters = json.dumps(appearance_chapters)
            
            # 重新计算first和last
            if appearance_chapters:
                character.first_mention_chapter_id = min(appearance_chapters)
                character.last_appearance_chapter_id = max(appearance_chapters)
            else:
                character.first_mention_chapter_id = None
                character.last_appearance_chapter_id = None
        
        db.commit()
        
        return {
            "added": added_count,
            "removed": removed_count,
            "unchanged": unchanged_count
        }
    
    @staticmethod
    def update_setting_references_smart(
        chapter_id: int,
        old_content: str,
        new_content: str,
        project_id: int,
        db: Session
    ) -> Dict[str, int]:
        """
        智能检测设定项引用变化（基于差异分析）
        
        Returns:
            {"added": 3, "removed": 1, "unchanged": 10}
        """
        collections = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).all()
        
        added_count = 0
        removed_count = 0
        unchanged_count = 0
        
        for collection in collections:
            items = db.query(SettingItem).filter(
                SettingItem.collection_id == collection.id
            ).all()
            
            for item in items:
                name = item.name
                if not name:
                    continue
                
                # 检测变化
                was_mentioned = name in old_content
                now_mentioned = name in new_content
                
                # 无变化，跳过
                if was_mentioned == now_mentioned:
                    unchanged_count += 1
                    continue
                
                referenced_chapters = json.loads(item.referenced_chapters or "[]")
                
                if now_mentioned and not was_mentioned:
                    # 🆕 新增引用
                    if chapter_id not in referenced_chapters:
                        referenced_chapters.append(chapter_id)
                        item.referenced_chapters = json.dumps(referenced_chapters)
                        item.usage_count = len(referenced_chapters)
                        item.last_referenced_at = datetime.now()
                        added_count += 1
                        print(f"  ✅ {name} ({collection.category}) 新增引用: 第{chapter_id}章")
                
                elif was_mentioned and not now_mentioned:
                    # 🗑️ 移除引用
                    if chapter_id in referenced_chapters:
                        referenced_chapters.remove(chapter_id)
                        item.referenced_chapters = json.dumps(referenced_chapters)
                        item.usage_count = len(referenced_chapters)
                        # last_referenced_at 不更新（保留最后一次真实引用时间）
                        removed_count += 1
                        print(f"  ❌ {name} ({collection.category}) 移除引用: 第{chapter_id}章")
        
        db.commit()
        
        return {
            "added": added_count,
            "removed": removed_count,
            "unchanged": unchanged_count
        }
    
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
