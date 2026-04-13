"""
知识图谱服务
提供图谱查询、邻接点查询、关系强度过滤等功能。
"""
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.graph import KnowledgeGraphEdge
from app.models.setting import SettingCollection, SettingItem


class KnowledgeGraphService:
    """知识图谱服务。"""

    @staticmethod
    def get_neighbors(
        db: Session,
        item_id: int,
        direction: str = "both",
        relation_types: Optional[List[str]] = None,
        min_confidence: float = 0.0,
        max_depth: int = 1,
    ) -> Dict[str, Any]:
        """
        获取邻接点，支持多跳查询。

        当边的 `confidence` 为空时，也视为可展示边，避免历史数据被过滤掉。
        """
        source_item = db.query(SettingItem).filter(SettingItem.id == item_id).first()
        if not source_item:
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}

        visited_nodes: Set[int] = {item_id}
        visited_edges: Set[int] = set()
        result_edges: List[Dict[str, Any]] = []
        current_level: Set[int] = {item_id}

        for _ in range(max_depth):
            if not current_level:
                break

            current_ids = list(current_level)
            next_level: Set[int] = set()

            query = db.query(KnowledgeGraphEdge).filter(
                or_(
                    KnowledgeGraphEdge.confidence.is_(None),
                    KnowledgeGraphEdge.confidence >= min_confidence,
                )
            )

            if direction == "out":
                query = query.filter(KnowledgeGraphEdge.source_item_id.in_(current_ids))
            elif direction == "in":
                query = query.filter(KnowledgeGraphEdge.target_item_id.in_(current_ids))
            else:
                query = query.filter(
                    or_(
                        KnowledgeGraphEdge.source_item_id.in_(current_ids),
                        KnowledgeGraphEdge.target_item_id.in_(current_ids),
                    )
                )

            if relation_types:
                query = query.filter(KnowledgeGraphEdge.relation_type.in_(relation_types))

            for edge in query.all():
                if edge.id in visited_edges:
                    continue
                visited_edges.add(edge.id)

                neighbor_id: Optional[int] = None
                if edge.source_item_id in current_level:
                    neighbor_id = edge.target_item_id
                elif edge.target_item_id in current_level:
                    neighbor_id = edge.source_item_id

                if neighbor_id is not None and neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    next_level.add(neighbor_id)

                result_edges.append(
                    {
                        "id": edge.id,
                        "source": edge.source_item_id,
                        "target": edge.target_item_id,
                        "relation_type": edge.relation_type,
                        "confidence": edge.confidence,
                        "auto_extracted": edge.auto_extracted,
                    }
                )

            current_level = next_level

        items = db.query(SettingItem).filter(SettingItem.id.in_(list(visited_nodes))).all()
        collection_ids = list({item.collection_id for item in items})
        collections = (
            db.query(SettingCollection)
            .filter(SettingCollection.id.in_(collection_ids))
            .all()
        )
        collection_map = {collection.id: collection for collection in collections}

        result_nodes: List[Dict[str, Any]] = []
        for item in items:
            collection = collection_map.get(item.collection_id)
            result_nodes.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "type": collection.category if collection else "unknown",
                    "collection_name": collection.name if collection else "",
                    "is_leaf": item.is_leaf,
                    "depth": item.depth,
                }
            )

        return {
            "nodes": result_nodes,
            "edges": result_edges,
            "total_nodes": len(result_nodes),
            "total_edges": len(result_edges),
        }

    @staticmethod
    def get_relation_summary(db: Session, item_id: int) -> Dict[str, Any]:
        """获取节点关系摘要。"""
        outgoing_edges = db.query(KnowledgeGraphEdge).filter(
            KnowledgeGraphEdge.source_item_id == item_id
        ).all()
        incoming_edges = db.query(KnowledgeGraphEdge).filter(
            KnowledgeGraphEdge.target_item_id == item_id
        ).all()

        by_type: Dict[str, int] = {}
        for edge in outgoing_edges + incoming_edges:
            relation_type = edge.relation_type
            by_type[relation_type] = by_type.get(relation_type, 0) + 1

        return {
            "total_relations": len(outgoing_edges) + len(incoming_edges),
            "by_type": by_type,
            "outgoing": len(outgoing_edges),
            "incoming": len(incoming_edges),
        }

    @staticmethod
    def find_shortest_path(
        db: Session,
        source_id: int,
        target_id: int,
        max_depth: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """查找两个节点之间的最短路径。"""
        if source_id == target_id:
            source_item = db.query(SettingItem).filter(SettingItem.id == source_id).first()
            if not source_item:
                return None
            return [{"node_id": source_id, "node_name": source_item.name, "edge_to_next": None}]

        queue: deque[Tuple[int, List[int]]] = deque()
        queue.append((source_id, [source_id]))
        visited: Set[int] = {source_id}

        while queue:
            current_id, path = queue.popleft()
            if len(path) > max_depth + 1:
                break

            edges = db.query(KnowledgeGraphEdge).filter(
                or_(
                    KnowledgeGraphEdge.source_item_id == current_id,
                    KnowledgeGraphEdge.target_item_id == current_id,
                )
            ).all()

            for edge in edges:
                neighbor_id: Optional[int] = None
                if edge.source_item_id == current_id:
                    neighbor_id = edge.target_item_id
                elif edge.target_item_id == current_id:
                    neighbor_id = edge.source_item_id

                if neighbor_id is None or neighbor_id in visited:
                    continue

                visited.add(neighbor_id)
                new_path = path + [neighbor_id]
                if neighbor_id == target_id:
                    return KnowledgeGraphService._build_path_result(db, new_path)
                queue.append((neighbor_id, new_path))

        return None

    @staticmethod
    def _build_path_result(db: Session, path: List[int]) -> List[Dict[str, Any]]:
        """构建路径结果。"""
        result: List[Dict[str, Any]] = []

        for index, node_id in enumerate(path):
            item = db.query(SettingItem).filter(SettingItem.id == node_id).first()
            if not item:
                continue

            node_info: Dict[str, Any] = {
                "node_id": node_id,
                "node_name": item.name,
                "edge_to_next": None,
            }

            if index < len(path) - 1:
                next_id = path[index + 1]
                edge = db.query(KnowledgeGraphEdge).filter(
                    or_(
                        and_(
                            KnowledgeGraphEdge.source_item_id == node_id,
                            KnowledgeGraphEdge.target_item_id == next_id,
                        ),
                        and_(
                            KnowledgeGraphEdge.source_item_id == next_id,
                            KnowledgeGraphEdge.target_item_id == node_id,
                        ),
                    )
                ).first()
                if edge:
                    node_info["edge_to_next"] = {
                        "relation_type": edge.relation_type,
                        "confidence": edge.confidence,
                    }

            result.append(node_info)

        return result
