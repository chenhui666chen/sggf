"""
设定一致性校验与冲突检测服务
"""
import re
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.setting import SettingCollection, SettingItem
from app.models.character import Character


class ConflictType:
    """冲突类型枚举"""
    DUPLICATE_NAME = "duplicate_name"  # 同名不同定义
    ABILITY_MISMATCH = "ability_mismatch"  # 能力与设定矛盾
    RELATION_CONFLICT = "relation_conflict"  # 关系冲突


class SettingConsistencyService:
    """设定一致性校验服务"""

    @staticmethod
    def detect_duplicate_names(db: Session, project_id: int) -> List[Dict[str, Any]]:
        """
        检测同名不同定义的设定项
        
        返回: [
            {
                "conflict_type": "duplicate_name",
                "name": str,
                "items": [{"id": int, "collection": str, "content": str}],
                "severity": "high"|"medium"|"low"
            }
        ]
        """
        conflicts = []
        
        # 获取项目下所有正式集合（排除候选）
        collections = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category != "candidate",
            )
            .all()
        )
        
        collection_ids = [c.id for c in collections]
        if not collection_ids:
            return []
        
        # 获取所有设定项
        all_items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(collection_ids))
            .all()
        )
        
        # 按名称分组
        name_groups: Dict[str, List[SettingItem]] = {}
        for item in all_items:
            if item.name not in name_groups:
                name_groups[item.name] = []
            name_groups[item.name].append(item)
        
        # 检测同名但内容差异过大的项
        for name, items in name_groups.items():
            if len(items) < 2:
                continue
            
            # 比较内容相似度
            contents = [item.content or "" for item in items]
            has_conflict = False
            
            # 简单策略：如果内容长度差异 > 50% 或关键字段不同，则认为有冲突
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    len_diff = abs(len(contents[i]) - len(contents[j]))
                    max_len = max(len(contents[i]), len(contents[j]))
                    if max_len > 0 and len_diff / max_len > 0.5:
                        has_conflict = True
                        break
                if has_conflict:
                    break
            
            if has_conflict:
                collection_map = {c.id: c.name for c in collections}
                conflicts.append({
                    "conflict_type": ConflictType.DUPLICATE_NAME,
                    "name": name,
                    "items": [
                        {
                            "id": item.id,
                            "collection": collection_map.get(item.collection_id, "未知"),
                            "content": item.content[:100] + "..." if item.content and len(item.content) > 100 else item.content or "",
                        }
                        for item in items
                    ],
                    "severity": "high",
                })
        
        return conflicts

    @staticmethod
    def detect_ability_mismatches(db: Session, project_id: int) -> List[Dict[str, Any]]:
        """
        检测人物能力与设定矛盾
        
        例如：人物境界与功法要求不符
        """
        conflicts = []
        
        # 获取项目下所有角色
        characters = (
            db.query(Character)
            .filter(Character.project_id == project_id)
            .all()
        )
        
        # 获取功法体系集合
        technique_collection = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category == "technique_system",
            )
            .first()
        )
        
        if not technique_collection:
            return []
        
        # 获取所有功法设定
        techniques = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == technique_collection.id)
            .all()
        )
        
        # 检测角色功法与境界要求的冲突
        for char in characters:
            # 使用正确的字段：current_realm 是关系对象
            char_realm = char.current_realm.name if char.current_realm else ""
            
            # 解析角色掌握的功法（从character_techniques或描述中）
            # 这里简化处理，实际可扩展
            char_desc = char.profile or char.summary or ""
            
            for tech in techniques:
                tech_content = tech.content or ""
                
                # 检查功法要求境界
                realm_req_match = re.search(r"境界要求[:：]\s*([^\n,，]+)", tech_content)
                if not realm_req_match:
                    continue
                
                required_realm = realm_req_match.group(1).strip()
                
                # 如果角色描述中提到此功法，但境界不符
                if tech.name in char_desc and required_realm not in char_realm:
                    conflicts.append({
                        "conflict_type": ConflictType.ABILITY_MISMATCH,
                        "character": char.name,
                        "technique": tech.name,
                        "character_realm": char_realm,
                        "required_realm": required_realm,
                        "severity": "medium",
                    })
        
        return conflicts

    @staticmethod
    def detect_all_conflicts(db: Session, project_id: int) -> Dict[str, Any]:
        """
        检测所有冲突
        
        返回: {
            "duplicate_names": [...],
            "ability_mismatches": [...],
            "total_count": int
        }
        """
        duplicate_names = SettingConsistencyService.detect_duplicate_names(db, project_id)
        ability_mismatches = SettingConsistencyService.detect_ability_mismatches(db, project_id)
        
        return {
            "duplicate_names": duplicate_names,
            "ability_mismatches": ability_mismatches,
            "total_count": len(duplicate_names) + len(ability_mismatches),
        }
