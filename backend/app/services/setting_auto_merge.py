"""
设定自动合并服务
实现高置信度设定项的自动合并与版本化快照
"""
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem


class SettingAutoMergeService:
    """设定自动合并服务"""

    # 高置信度标准阈值
    HIGH_CONFIDENCE_THRESHOLD = 0.8

    @staticmethod
    def calculate_confidence(
        item_name: str,
        item_content: str,
        chapter_plan: str,
        chapter_content: str,
    ) -> float:
        """
        计算设定项的置信度分数 (0-1)
        
        高置信度标准：
        1. 特定格式命中（如：【功法】XXX、境界：XXX）
        2. 章节规划与正文中双重出现
        3. 详细描述存在（非仅提及名称）
        """
        score = 0.0
        
        # 检查1: 特定格式命中 (+0.3)
        format_patterns = [
            r'【[^】]+】\s*' + re.escape(item_name),
            r'(功法|丹药|阵法|秘境|城市|门派)[:：]\s*' + re.escape(item_name),
            r'境界[:：]\s*' + re.escape(item_name),
        ]
        for pat in format_patterns:
            if re.search(pat, item_content):
                score += 0.3
                break
        
        # 检查2: 章节规划与正文双重出现 (+0.4)
        if item_name in chapter_plan and item_name in chapter_content:
            score += 0.4
        elif item_name in chapter_content:
            score += 0.2
        
        # 检查3: 详细描述存在（内容长度 > 50字） (+0.3)
        if len(item_content) > 50:
            score += 0.3
        
        return min(score, 1.0)

    @staticmethod
    def create_snapshot(item: SettingItem) -> Dict[str, Any]:
        """创建设定项的快照"""
        return {
            "timestamp": datetime.now().isoformat(),
            "name": item.name,
            "content": item.content,
            "tags": item.tags,
            "relations": item.relations,
            "confidence_score": item.confidence_score,
        }

    @staticmethod
    def save_snapshot(item: SettingItem, db: Session) -> None:
        """保存当前状态的快照到历史记录"""
        snapshot = SettingAutoMergeService.create_snapshot(item)
        
        # 解析现有快照列表
        try:
            snapshots = json.loads(item.snapshots) if item.snapshots else []
        except Exception:
            snapshots = []
        
        # 追加新快照
        snapshots.append(snapshot)
        
        # 最多保留最近10个快照
        if len(snapshots) > 10:
            snapshots = snapshots[-10:]
        
        item.snapshots = json.dumps(snapshots, ensure_ascii=False)
        db.commit()

    @staticmethod
    def find_or_create_target_item(
        db: Session,
        project_id: int,
        target_collection_id: int,
        item_name: str,
    ) -> Tuple[SettingItem, bool]:
        """
        在目标集合中查找或创建设定项
        
        返回: (设定项, 是否新创建)
        """
        # 先查找是否已存在同名项
        collection = db.query(SettingCollection).get(target_collection_id)
        if not collection or collection.project_id != project_id:
            raise ValueError(f"目标集合 {target_collection_id} 不存在或不属于项目 {project_id}")
        
        existing = (
            db.query(SettingItem)
            .filter(
                SettingItem.collection_id == target_collection_id,
                SettingItem.name == item_name,
            )
            .first()
        )
        
        if existing:
            return existing, False
        
        # 创建新项
        new_item = SettingItem(
            collection_id=target_collection_id,
            name=item_name,
            content="",
            tags=json.dumps(["自动创建"], ensure_ascii=False),
            order=0,
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return new_item, True

    @staticmethod
    def merge_content(old_content: str, new_content: str) -> str:
        """
        合并设定内容（简单策略：如果新内容更详细则覆盖，否则保留旧内容）
        """
        if not old_content:
            return new_content
        if not new_content:
            return old_content
        
        # 如果新内容更长且包含旧内容关键信息，则使用新内容
        if len(new_content) > len(old_content) * 1.2:
            return new_content
        
        # 否则保留旧内容（避免信息丢失）
        return old_content

    @staticmethod
    def auto_merge_high_confidence_items(
        db: Session,
        project_id: int,
        candidate_collection_id: int,
        chapter_plan: str,
        chapter_content: str,
    ) -> Dict[str, Any]:
        """
        自动合并高置信度的候选设定项到正式集合
        
        返回: {
            "merged_count": int,
            "skipped_count": int,
            "details": [{"item_name": str, "confidence": float, "action": str}]
        }
        """
        # 类型映射到目标集合类别（完善版本）
        typ_to_category_map = {
            # 人物
            "人物": "character_system",
            "角色": "character_system",
            # 境界
            "境界": "cultivation_realm_system",
            "修为": "cultivation_realm_system",
            "等级": "cultivation_realm_system",
            # 功法
            "功法": "technique_system",
            "武学": "technique_system",
            "技能": "technique_system",
            # 丹药
            "丹药": "pill_system",
            "灵丹": "pill_system",
            # 阵法
            "阵法": "formation_system",
            "结界": "formation_system",
            # 武器法宝
            "法宝": "weapon_system",
            "武器": "weapon_system",
            "灵器": "weapon_system",
            # 资源
            "资源": "resource_system",
            "灵草": "resource_system",
            "材料": "resource_system",
            # 地点
            "秘境": "map_system",
            "遗迹": "map_system",
            "城市": "map_system",
            "城镇": "map_system",
            "地点": "map_system",
            # 势力
            "势力": "organization_force_system",
            "组织": "organization_force_system",
            "门派": "organization_force_system",
            # 符箓
            "符箓": "talisman_system",
        }
        
        # 获取所有候选项
        candidate_items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == candidate_collection_id)
            .all()
        )
        
        merged_count = 0
        skipped_count = 0
        details = []
        
        for item in candidate_items:
            # 计算置信度
            confidence = SettingAutoMergeService.calculate_confidence(
                item.name, item.content or "", chapter_plan, chapter_content
            )
            item.confidence_score = confidence
            
            # 低于阈值，跳过
            if confidence < SettingAutoMergeService.HIGH_CONFIDENCE_THRESHOLD:
                skipped_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": "skipped_low_confidence",
                })
                continue
            
            # 解析类型
            typ_match = re.search(r"类型[:：]\s*([^\n,，]+)", item.content or "")
            if not typ_match:
                skipped_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": "skipped_no_type",
                })
                continue
            
            typ = typ_match.group(1).strip()
            target_category = typ_to_category_map.get(typ)
            if not target_category:
                skipped_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": "skipped_no_target_category",
                })
                continue
            
            # 查找目标集合
            target_collection = (
                db.query(SettingCollection)
                .filter(
                    SettingCollection.project_id == project_id,
                    SettingCollection.category == target_category,
                )
                .first()
            )
            
            if not target_collection:
                skipped_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": "skipped_no_target_collection",
                })
                continue
            
            # 查找或创建目标项
            try:
                target_item, is_new = SettingAutoMergeService.find_or_create_target_item(
                    db, project_id, target_collection.id, item.name
                )
                
                # 保存快照（如果是更新）
                if not is_new:
                    SettingAutoMergeService.save_snapshot(target_item, db)
                
                # 合并内容
                merged_content = SettingAutoMergeService.merge_content(
                    target_item.content or "", item.content or ""
                )
                target_item.content = merged_content
                
                # 更新标签
                try:
                    tags = json.loads(target_item.tags) if target_item.tags else []
                except Exception:
                    tags = []
                if "自动合并" not in tags:
                    tags.append("自动合并")
                target_item.tags = json.dumps(tags, ensure_ascii=False)
                
                # 更新置信度
                target_item.confidence_score = confidence
                
                db.commit()
                
                # 删除候选项
                db.delete(item)
                db.commit()
                
                merged_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": "merged" if not is_new else "created_and_merged",
                })
            except Exception as e:
                db.rollback()
                skipped_count += 1
                details.append({
                    "item_name": item.name,
                    "confidence": round(confidence, 2),
                    "action": f"error: {str(e)}",
                })
        
        db.commit()
        
        return {
            "merged_count": merged_count,
            "skipped_count": skipped_count,
            "details": details,
        }
