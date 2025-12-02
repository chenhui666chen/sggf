"""
知识图谱服务
提供图谱查询、邻接点查询、关系强度过滤等功能
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.setting import KnowledgeGraphEdge, SettingItem, SettingCollection


class KnowledgeGraphService:
    """知识图谱服务"""
    
    @staticmethod
    def get_neighbors(
        db: Session,
        item_id: int,
        direction: str = "both",  # both | out | in
        relation_types: Optional[List[str]] = None,
        min_confidence: float = 0.0,
        max_depth: int = 1,
    ) -> Dict[str, Any]:
        """
        获取邻接点（支持多跳查询）
        
        Args:
            item_id: 源节点ID
            direction: 方向（both=双向，out=出边，in=入边）
            relation_types: 关系类型过滤（可选）
            min_confidence: 最小置信度
            max_depth: 最大深度（1=直接邻居，2=二度邻居，...）
        
        Returns:
            {
                "nodes": [{"id": 1, "name": "...", "type": "..."}],
                "edges": [{"source": 1, "target": 2, "relation_type": "...", "confidence": 0.8}],
                "total_nodes": 10,
                "total_edges": 15
            }
        """
        visited_nodes = set()
        visited_edges = set()
        result_nodes = []
        result_edges = []
        
        # 获取源节点信息
        source_item = db.query(SettingItem).filter(SettingItem.id == item_id).first()
        if not source_item:
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}
        
        # BFS 多跳查询
        current_level = {item_id}
        for depth in range(max_depth):
            next_level = set()
            
            for current_id in current_level:
                # 查询边
                query = db.query(KnowledgeGraphEdge).filter(
                    KnowledgeGraphEdge.confidence >= min_confidence
                )
                
                if direction == "out":
                    query = query.filter(KnowledgeGraphEdge.source_item_id == current_id)
                elif direction == "in":
                    query = query.filter(KnowledgeGraphEdge.target_item_id == current_id)
                else:  # both
                    query = query.filter(
                        or_(
                            KnowledgeGraphEdge.source_item_id == current_id,
                            KnowledgeGraphEdge.target_item_id == current_id,
                        )
                    )
                
                if relation_types:
                    query = query.filter(KnowledgeGraphEdge.relation_type.in_(relation_types))
                
                edges = query.all()
                
                for edge in edges:
                    edge_id = edge.id
                    if edge_id in visited_edges:
                        continue
                    
                    visited_edges.add(edge_id)
                    
                    # 确定邻居节点ID
                    neighbor_id = None
                    if edge.source_item_id == current_id:
                        neighbor_id = edge.target_item_id
                    elif edge.target_item_id == current_id:
                        neighbor_id = edge.source_item_id
                    
                    if neighbor_id and neighbor_id not in visited_nodes:
                        next_level.add(neighbor_id)
                        visited_nodes.add(neighbor_id)
                    
                    # 添加边到结果
                    result_edges.append({
                        "id": edge.id,
                        "source": edge.source_item_id,
                        "target": edge.target_item_id,
                        "relation_type": edge.relation_type,
                        "confidence": edge.confidence,
                        "auto_extracted": edge.auto_extracted,
                    })
            
            current_level = next_level
            if not current_level:
                break
        
        # 查询所有节点信息
        all_node_ids = visited_nodes | {item_id}
        items = db.query(SettingItem).filter(SettingItem.id.in_(all_node_ids)).all()
        
        for item in items:
            collection = db.query(SettingCollection).filter(
                SettingCollection.id == item.collection_id
            ).first()
            
            result_nodes.append({
                "id": item.id,
                "name": item.name,
                "type": collection.category if collection else "unknown",
                "collection_name": collection.name if collection else "",
                "is_leaf": item.is_leaf,
                "depth": item.depth,
            })
        
        return {
            "nodes": result_nodes,
            "edges": result_edges,
            "total_nodes": len(result_nodes),
            "total_edges": len(result_edges),
        }
    
    @staticmethod
    def get_relation_summary(
        db: Session,
        item_id: int,
    ) -> Dict[str, Any]:
        """
        获取节点的关系统计摘要
        
        Returns:
            {
                "total_relations": 10,
                "by_type": {"相关": 5, "对立": 2, "同盟": 3},
                "outgoing": 6,
                "incoming": 4
            }
        """
        # 出边统计
        outgoing_edges = db.query(KnowledgeGraphEdge).filter(
            KnowledgeGraphEdge.source_item_id == item_id
        ).all()
        
        # 入边统计
        incoming_edges = db.query(KnowledgeGraphEdge).filter(
            KnowledgeGraphEdge.target_item_id == item_id
        ).all()
        
        # 按类型聚合
        by_type = {}
        for edge in outgoing_edges + incoming_edges:
            rel_type = edge.relation_type
            by_type[rel_type] = by_type.get(rel_type, 0) + 1
        
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
        """
        查找两个节点之间的最短路径（BFS）
        
        Returns:
            [
                {"node_id": 1, "node_name": "...", "edge_to_next": {"relation_type": "...", "confidence": 0.8}},
                {"node_id": 2, "node_name": "...", "edge_to_next": {...}},
                {"node_id": 3, "node_name": "..."}
            ]
            如果没有路径，返回 None
        """
        if source_id == target_id:
            source_item = db.query(SettingItem).filter(SettingItem.id == source_id).first()
            if not source_item:
                return None
            return [{"node_id": source_id, "node_name": source_item.name, "edge_to_next": None}]
        
        # BFS
        from collections import deque
        
        queue = deque([(source_id, [source_id])])
        visited = {source_id}
        
        while queue and len(queue[0][1]) <= max_depth:
            current_id, path = queue.popleft()
            
            # 查找所有邻居
            edges = db.query(KnowledgeGraphEdge).filter(
                or_(
                    KnowledgeGraphEdge.source_item_id == current_id,
                    KnowledgeGraphEdge.target_item_id == current_id,
                )
            ).all()
            
            for edge in edges:
                neighbor_id = None
                if edge.source_item_id == current_id:
                    neighbor_id = edge.target_item_id
                elif edge.target_item_id == current_id:
                    neighbor_id = edge.source_item_id
                
                if neighbor_id is None or neighbor_id in visited:
                    continue
                
                visited.add(neighbor_id)
                new_path = path + [neighbor_id]
                
                if neighbor_id == target_id:
                    # 找到路径，构建结果
                    return KnowledgeGraphService._build_path_result(db, new_path)
                
                queue.append((neighbor_id, new_path))
        
        return None
    
    @staticmethod
    def _build_path_result(db: Session, path: List[int]) -> List[Dict[str, Any]]:
        """构建路径结果"""
        result = []
        
        for i, node_id in enumerate(path):
            item = db.query(SettingItem).filter(SettingItem.id == node_id).first()
            if not item:
                continue
            
            node_info = {
                "node_id": node_id,
                "node_name": item.name,
                "edge_to_next": None,
            }
            
            # 如果不是最后一个节点，查找连接边
            if i < len(path) - 1:
                next_id = path[i + 1]
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
