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
        
        支持两种场景：
        1. 初始追踪：old_content为空，全部视为新增
        2. 差异检测：old_content不为空，检测变化
        
        Args:
            chapter_id: 章节ID
            old_content: 修改前的内容（初始创建时为空字符串）
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
        is_initial_tracking = (old_content == "")  # 🆕 判断是否为初始追踪
        
        for character in characters:
            name = character.name
            if not name:
                continue
            
            # 🆕 初始追踪模式：只处理新增
            if is_initial_tracking:
                now_mentioned = name in new_content
                if now_mentioned:
                    appearance_chapters = json.loads(character.appearance_chapters or "[]")
                    if chapter_id not in appearance_chapters:
                        appearance_chapters.append(chapter_id)
                        character.appearance_chapters = json.dumps(appearance_chapters)
                        
                        # 更新first和last
                        if character.first_mention_chapter_id is None or chapter_id < character.first_mention_chapter_id:
                            character.first_mention_chapter_id = chapter_id
                        if character.last_appearance_chapter_id is None or chapter_id > character.last_appearance_chapter_id:
                            character.last_appearance_chapter_id = chapter_id
                        
                        added_count += 1
                        print(f"  ✅ {name} 初始追踪: 第{chapter_id}章")
                continue
            
            # 🔄 差异检测模式
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
        
        支持两种场景：
        1. 初始追踪：old_content为空，全部视为新增
        2. 差异检测：old_content不为空，检测变化
        
        Returns:
            {"added": 3, "removed": 1, "unchanged": 10}
        """
        collections = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).all()
        
        added_count = 0
        removed_count = 0
        unchanged_count = 0
        is_initial_tracking = (old_content == "")  # 🆕 判断是否为初始追踪
        
        for collection in collections:
            items = db.query(SettingItem).filter(
                SettingItem.collection_id == collection.id
            ).all()
            
            for item in items:
                name = item.name
                if not name:
                    continue
                
                # 🆕 初始追踪模式：只处理新增
                if is_initial_tracking:
                    now_mentioned = name in new_content
                    if now_mentioned:
                        referenced_chapters = json.loads(item.referenced_chapters or "[]")
                        if chapter_id not in referenced_chapters:
                            referenced_chapters.append(chapter_id)
                            item.referenced_chapters = json.dumps(referenced_chapters)
                            item.usage_count = len(referenced_chapters)
                            item.last_referenced_at = datetime.now()
                            added_count += 1
                            print(f"  ✅ {name} ({collection.category}) 初始追踪: 第{chapter_id}章")
                    continue
                
                # 🔄 差异检测模式
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
    
    @staticmethod
    def update_character_item_relations(
        chapter_id: int,
        chapter_content: str,
        project_id: int,
        db: Session
    ) -> Dict[str, int]:
        """
        🆕 高级功能：自动识别人物与设定项的关联
        
        基于关键词匹配识别：
        - 人物-功法关联："林墨修炼/施展/掌握九天剑诀"
        - 人物-法宝关联："林墨手持/获得/使用赤霄剑"
        - 人物-地点关联："林墨来到/在天剑宗"
        
        Returns:
            {"techniques": 2, "artifacts": 1, "locations": 3}
        """
        characters = db.query(Character).filter(
            Character.project_id == project_id
        ).all()
        
        technique_count = 0
        artifact_count = 0
        location_count = 0
        
        # 获取所有设定集合
        collections = db.query(SettingCollection).filter(
            SettingCollection.project_id == project_id
        ).all()
        
        collections_by_category = {coll.category: coll for coll in collections}
        
        for character in characters:
            char_name = character.name
            if not char_name or char_name not in chapter_content:
                continue
            
            # 1️⃣ 检测人物-功法关联
            if 'technique_system' in collections_by_category:
                technique_coll = collections_by_category['technique_system']
                techniques = db.query(SettingItem).filter(
                    SettingItem.collection_id == technique_coll.id
                ).all()
                
                for tech in techniques:
                    if not tech.name:
                        continue
                    
                    # 匹配模式："人物名 + [修炼|施展|掌握|使用] + 功法名"
                    if AutoTrackingService._match_relation(
                        chapter_content, char_name, tech.name,
                        ['修炼', '施展', '掌握', '使用', '参悟', '学会']
                    ):
                        # 更新人物的techniques_json字段
                        char_techniques = json.loads(character.techniques_json or "[]")
                        if tech.id not in char_techniques:
                            char_techniques.append(tech.id)
                            character.techniques_json = json.dumps(char_techniques)
                            technique_count += 1
                            print(f"  📚 {char_name} 关联功法: {tech.name}")
                        
                        # 更新设定项的related_characters字段
                        tech_chars = json.loads(tech.related_characters or "[]")
                        if character.id not in tech_chars:
                            tech_chars.append(character.id)
                            tech.related_characters = json.dumps(tech_chars)
            
            # 2️⃣ 检测人物-法宝关联
            if 'artifact_system' in collections_by_category:
                artifact_coll = collections_by_category['artifact_system']
                artifacts = db.query(SettingItem).filter(
                    SettingItem.collection_id == artifact_coll.id
                ).all()
                
                for art in artifacts:
                    if not art.name:
                        continue
                    
                    # 匹配模式："人物名 + [手持|获得|使用|佩戴] + 法宝名"
                    if AutoTrackingService._match_relation(
                        chapter_content, char_name, art.name,
                        ['手持', '获得', '使用', '佩戴', '持有', '拿出']
                    ):
                        # 更新人物的artifacts_json字段
                        char_artifacts = json.loads(character.artifacts_json or "[]")
                        if art.id not in char_artifacts:
                            char_artifacts.append(art.id)
                            character.artifacts_json = json.dumps(char_artifacts)
                            artifact_count += 1
                            print(f"  ⚔️ {char_name} 关联法宝: {art.name}")
                        
                        # 更新设定项的related_characters字段
                        art_chars = json.loads(art.related_characters or "[]")
                        if character.id not in art_chars:
                            art_chars.append(character.id)
                            art.related_characters = json.dumps(art_chars)
            
            # 3️⃣ 检测人物-地点关联
            if 'map_system' in collections_by_category:
                map_coll = collections_by_category['map_system']
                locations = db.query(SettingItem).filter(
                    SettingItem.collection_id == map_coll.id
                ).all()
                
                for loc in locations:
                    if not loc.name:
                        continue
                    
                    # 匹配模式："人物名 + [来到|在|前往|进入] + 地点名"
                    if AutoTrackingService._match_relation(
                        chapter_content, char_name, loc.name,
                        ['来到', '在', '前往', '进入', '走入', '赶到']
                    ):
                        # 更新人物的related_locations_json字段
                        char_locations = json.loads(character.related_locations_json or "[]")
                        if loc.id not in char_locations:
                            char_locations.append(loc.id)
                            character.related_locations_json = json.dumps(char_locations)
                            location_count += 1
                            print(f"  📍 {char_name} 关联地点: {loc.name}")
                        
                        # 更新设定项的related_characters字段
                        loc_chars = json.loads(loc.related_characters or "[]")
                        if character.id not in loc_chars:
                            loc_chars.append(character.id)
                            loc.related_characters = json.dumps(loc_chars)
        
        db.commit()
        
        return {
            "techniques": technique_count,
            "artifacts": artifact_count,
            "locations": location_count
        }
    
    @staticmethod
    def _match_relation(
        content: str,
        char_name: str,
        item_name: str,
        keywords: List[str]
    ) -> bool:
        """
        匹配人物与设定项的关联关系
        
        匹配模式：
        - "人物名 + 关键词 + 设定项名" (直接相邻)
        - "人物名 ... 关键词 ... 设定项名" (同一句)
        
        示例：
        - "林墨施展九天剑诀" → True
        - "林墨在天剑宗修炼" → True
        """
        # 简单匹配：在同一句中同时出现人物、关键词、设定项
        sentences = content.split('。')  # 按句号分割
        
        for sentence in sentences:
            if char_name in sentence and item_name in sentence:
                # 检查是否包含任何关键词
                for keyword in keywords:
                    if keyword in sentence:
                        return True
        
        return False
