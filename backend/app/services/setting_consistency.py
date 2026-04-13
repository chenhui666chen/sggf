"""
设定一致性校验与冲突检测服务。
"""
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.graph import KnowledgeGraphEdge
from app.models.setting import SettingCollection, SettingItem


class ConflictType:
    """冲突类型枚举。"""

    DUPLICATE_NAME = "duplicate_name"
    ABILITY_MISMATCH = "ability_mismatch"
    RELATION_CONFLICT = "relation_conflict"


class SettingConsistencyService:
    """设定一致性校验服务。"""

    REALM_ORDER = [
        "凡人",
        "练气",
        "筑基",
        "金丹",
        "元婴",
        "化神",
        "合体",
        "大乘",
        "渡劫",
        "仙人",
        "觉醒",
        "E级",
        "D级",
        "C级",
        "B级",
        "A级",
        "S级",
        "SS级",
        "SSS级",
        "学徒",
        "初级",
        "中级",
        "高级",
        "大师",
        "宗师",
        "传奇",
        "后天",
        "先天",
        "大宗师",
        "天人",
    ]
    _REALM_INDEX = {realm: index for index, realm in enumerate(REALM_ORDER)}
    _REALM_MATCH_ORDER = sorted(_REALM_INDEX.keys(), key=len, reverse=True)

    DIRECT_CONFLICT_RELATIONS: Dict[str, Set[str]] = {
        "敌对": {"同盟", "友好", "合作"},
        "同盟": {"敌对", "对立"},
        "对立": {"同盟", "友好"},
        "友好": {"敌对", "对立"},
        "合作": {"敌对", "竞争"},
        "竞争": {"合作", "同盟"},
    }
    TRANSITIVE_POSITIVE_RELATIONS = {"同盟", "友好", "合作"}
    TRANSITIVE_NEGATIVE_RELATIONS = {"敌对", "对立"}

    @staticmethod
    def _text_similarity(text_a: str, text_b: str) -> float:
        """计算两段文本的字符级 Jaccard 相似度。"""
        if not text_a and not text_b:
            return 1.0
        if not text_a or not text_b:
            return 0.0

        def _char_ngrams(text: str, n: int = 2) -> Set[str]:
            cleaned = re.sub(r"\s+", "", text)
            if len(cleaned) < n:
                return {cleaned}
            return {cleaned[index : index + n] for index in range(len(cleaned) - n + 1)}

        ngrams_a = _char_ngrams(text_a)
        ngrams_b = _char_ngrams(text_b)
        union = ngrams_a | ngrams_b
        if not union:
            return 0.0
        return len(ngrams_a & ngrams_b) / len(union)

    @staticmethod
    def detect_duplicate_names(db: Session, project_id: int) -> List[Dict[str, Any]]:
        """检测同名但定义冲突的设定项。"""
        similarity_threshold = 0.4
        conflicts: List[Dict[str, Any]] = []

        collections = (
            db.query(SettingCollection)
            .filter(
                SettingCollection.project_id == project_id,
                SettingCollection.category != "candidate",
            )
            .all()
        )
        collection_ids = [collection.id for collection in collections]
        if not collection_ids:
            return []

        all_items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(collection_ids))
            .all()
        )

        grouped_items: Dict[str, List[SettingItem]] = {}
        for item in all_items:
            grouped_items.setdefault(item.name, []).append(item)

        collection_map = {collection.id: collection.name for collection in collections}
        for name, items in grouped_items.items():
            if len(items) < 2:
                continue

            min_similarity = 1.0
            has_conflict = False
            contents = [item.content or "" for item in items]

            for left_index in range(len(contents)):
                for right_index in range(left_index + 1, len(contents)):
                    similarity = SettingConsistencyService._text_similarity(
                        contents[left_index], contents[right_index]
                    )
                    min_similarity = min(min_similarity, similarity)
                    if similarity < similarity_threshold:
                        has_conflict = True

            if not has_conflict:
                continue

            if min_similarity < 0.15:
                severity = "high"
            elif min_similarity < 0.3:
                severity = "medium"
            else:
                severity = "low"

            conflicts.append(
                {
                    "conflict_type": ConflictType.DUPLICATE_NAME,
                    "name": name,
                    "similarity": round(min_similarity, 3),
                    "items": [
                        {
                            "id": item.id,
                            "collection": collection_map.get(item.collection_id, "未知"),
                            "content": (
                                f"{item.content[:100]}..."
                                if item.content and len(item.content) > 100
                                else item.content or ""
                            ),
                        }
                        for item in items
                    ],
                    "severity": severity,
                }
            )

        return conflicts

    @classmethod
    def _extract_realm_rank(cls, realm_text: str) -> Optional[int]:
        """从境界描述中提取排序索引，按长词优先匹配避免误命中。"""
        if not realm_text:
            return None
        for realm in cls._REALM_MATCH_ORDER:
            if realm in realm_text:
                return cls._REALM_INDEX[realm]
        return None

    @classmethod
    def _compare_realms(cls, char_realm: str, required_realm: str) -> int:
        """
        比较两个境界的高低。

        返回：
        -1 表示角色境界低于要求
         0 表示相当或无法比较
         1 表示角色境界高于要求
        """
        char_rank = cls._extract_realm_rank(char_realm)
        required_rank = cls._extract_realm_rank(required_realm)
        if char_rank is None or required_rank is None:
            return 0
        if char_rank < required_rank:
            return -1
        if char_rank > required_rank:
            return 1
        return 0

    @classmethod
    def _check_realm_conflict(
        cls,
        tech: SettingItem,
        char: Character,
        char_realm: str,
        conflicts: List[Dict[str, Any]],
    ) -> None:
        tech_content = tech.content or ""
        realm_requirement_match = re.search(r"境界要求[:：]\s*([^\n,，]+)", tech_content)
        if not realm_requirement_match:
            return

        required_realm = realm_requirement_match.group(1).strip()
        if not char_realm:
            conflicts.append(
                {
                    "conflict_type": ConflictType.ABILITY_MISMATCH,
                    "character": char.name,
                    "technique": tech.name,
                    "character_realm": "未设置",
                    "required_realm": required_realm,
                    "severity": "medium",
                }
            )
            return

        if cls._compare_realms(char_realm, required_realm) == -1:
            conflicts.append(
                {
                    "conflict_type": ConflictType.ABILITY_MISMATCH,
                    "character": char.name,
                    "technique": tech.name,
                    "character_realm": char_realm,
                    "required_realm": required_realm,
                    "severity": "medium",
                }
            )

    @staticmethod
    def detect_ability_mismatches(db: Session, project_id: int) -> List[Dict[str, Any]]:
        """检测人物能力与设定冲突。"""
        conflicts: List[Dict[str, Any]] = []
        characters = db.query(Character).filter(Character.project_id == project_id).all()

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

        techniques = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id == technique_collection.id)
            .all()
        )
        technique_map = {technique.id: technique for technique in techniques}

        for character in characters:
            char_realm = character.current_realm.name if character.current_realm else ""
            description = character.profile or character.summary or ""

            checked_ids: Set[int] = set()
            try:
                technique_ids = json.loads(character.techniques_json or "[]")
            except Exception:
                technique_ids = []

            for technique_id in technique_ids:
                if technique_id in checked_ids:
                    continue
                checked_ids.add(technique_id)
                technique = technique_map.get(technique_id)
                if technique:
                    SettingConsistencyService._check_realm_conflict(
                        technique,
                        character,
                        char_realm,
                        conflicts,
                    )

            for technique in techniques:
                if technique.id in checked_ids:
                    continue
                if technique.name and technique.name in description:
                    checked_ids.add(technique.id)
                    SettingConsistencyService._check_realm_conflict(
                        technique,
                        character,
                        char_realm,
                        conflicts,
                    )

        return conflicts

    @classmethod
    def _build_relation_maps(
        cls,
        edges: Iterable[KnowledgeGraphEdge],
    ) -> Tuple[Dict[Tuple[int, int], Set[str]], Dict[int, Set[int]]]:
        edge_type_map: Dict[Tuple[int, int], Set[str]] = {}
        positive_adjacency: Dict[int, Set[int]] = {}

        for edge in edges:
            pair_key = (edge.source_item_id, edge.target_item_id)
            edge_type_map.setdefault(pair_key, set()).add(edge.relation_type)

            if edge.relation_type in cls.TRANSITIVE_POSITIVE_RELATIONS:
                positive_adjacency.setdefault(edge.source_item_id, set()).add(edge.target_item_id)

        return edge_type_map, positive_adjacency

    @classmethod
    def _append_direct_relation_conflicts(
        cls,
        conflicts: List[Dict[str, Any]],
        item_map: Dict[int, SettingItem],
        edge_type_map: Dict[Tuple[int, int], Set[str]],
    ) -> None:
        checked_pairs: Set[Tuple[int, int]] = set()
        for (source_id, target_id), forward_types in edge_type_map.items():
            pair_key = (min(source_id, target_id), max(source_id, target_id))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            reverse_types = edge_type_map.get((target_id, source_id), set())
            if not reverse_types:
                continue

            source_name = item_map[source_id].name if source_id in item_map else f"ID:{source_id}"
            target_name = item_map[target_id].name if target_id in item_map else f"ID:{target_id}"

            for forward_type in forward_types:
                conflicting_reverse = cls.DIRECT_CONFLICT_RELATIONS.get(forward_type, set()) & reverse_types
                for reverse_type in conflicting_reverse:
                    conflicts.append(
                        {
                            "conflict_type": ConflictType.RELATION_CONFLICT,
                            "source": source_name,
                            "target": target_name,
                            "forward_relation": forward_type,
                            "reverse_relation": reverse_type,
                            "description": (
                                f"{source_name}→{target_name}为「{forward_type}」，"
                                f"但{target_name}→{source_name}为「{reverse_type}」"
                            ),
                            "severity": "high",
                            "mode": "direct",
                        }
                    )

    @classmethod
    def _append_transitive_relation_conflicts(
        cls,
        conflicts: List[Dict[str, Any]],
        item_map: Dict[int, SettingItem],
        edge_type_map: Dict[Tuple[int, int], Set[str]],
        positive_adjacency: Dict[int, Set[int]],
    ) -> None:
        recorded: Set[Tuple[int, int, int, str, str]] = set()

        for source_id, middle_nodes in positive_adjacency.items():
            for middle_id in middle_nodes:
                end_nodes = positive_adjacency.get(middle_id, set())
                for target_id in end_nodes:
                    if target_id == source_id:
                        continue

                    direct_types = edge_type_map.get((source_id, target_id), set())
                    reverse_types = edge_type_map.get((target_id, source_id), set())
                    negative_types = (
                        direct_types | reverse_types
                    ) & cls.TRANSITIVE_NEGATIVE_RELATIONS
                    if not negative_types:
                        continue

                    source_name = item_map[source_id].name if source_id in item_map else f"ID:{source_id}"
                    middle_name = item_map[middle_id].name if middle_id in item_map else f"ID:{middle_id}"
                    target_name = item_map[target_id].name if target_id in item_map else f"ID:{target_id}"

                    for negative_type in sorted(negative_types):
                        direction = "forward" if negative_type in direct_types else "reverse"
                        record_key = (
                            source_id,
                            middle_id,
                            target_id,
                            negative_type,
                            direction,
                        )
                        if record_key in recorded:
                            continue
                        recorded.add(record_key)

                        if direction == "forward":
                            description = (
                                f"{source_name}与{middle_name}、{middle_name}与{target_name}"
                                f"均为正向关系，但{source_name}→{target_name}为「{negative_type}」"
                            )
                        else:
                            description = (
                                f"{source_name}与{middle_name}、{middle_name}与{target_name}"
                                f"均为正向关系，但{target_name}→{source_name}为「{negative_type}」"
                            )

                        conflicts.append(
                            {
                                "conflict_type": ConflictType.RELATION_CONFLICT,
                                "source": source_name,
                                "middle": middle_name,
                                "target": target_name,
                                "negative_relation": negative_type,
                                "description": description,
                                "severity": "medium",
                                "mode": "transitive",
                            }
                        )

    @classmethod
    def detect_relation_conflicts(cls, db: Session, project_id: int) -> List[Dict[str, Any]]:
        """检测知识图谱关系冲突，包含双向冲突和传递冲突。"""
        collections = (
            db.query(SettingCollection)
            .filter(SettingCollection.project_id == project_id)
            .all()
        )
        collection_ids = [collection.id for collection in collections]
        if not collection_ids:
            return []

        items = (
            db.query(SettingItem)
            .filter(SettingItem.collection_id.in_(collection_ids))
            .all()
        )
        item_ids = {item.id for item in items}
        if not item_ids:
            return []

        edges = (
            db.query(KnowledgeGraphEdge)
            .filter(
                KnowledgeGraphEdge.source_item_id.in_(item_ids),
                KnowledgeGraphEdge.target_item_id.in_(item_ids),
            )
            .all()
        )
        if not edges:
            return []

        item_map = {item.id: item for item in items}
        edge_type_map, positive_adjacency = cls._build_relation_maps(edges)

        conflicts: List[Dict[str, Any]] = []
        cls._append_direct_relation_conflicts(conflicts, item_map, edge_type_map)
        cls._append_transitive_relation_conflicts(
            conflicts,
            item_map,
            edge_type_map,
            positive_adjacency,
        )
        return conflicts

    @staticmethod
    def detect_all_conflicts(db: Session, project_id: int) -> Dict[str, Any]:
        """检测所有设定冲突。"""
        duplicate_names = SettingConsistencyService.detect_duplicate_names(db, project_id)
        ability_mismatches = SettingConsistencyService.detect_ability_mismatches(db, project_id)
        relation_conflicts = SettingConsistencyService.detect_relation_conflicts(db, project_id)

        return {
            "duplicate_names": duplicate_names,
            "ability_mismatches": ability_mismatches,
            "relation_conflicts": relation_conflicts,
            "total_count": len(duplicate_names)
            + len(ability_mismatches)
            + len(relation_conflicts),
        }
