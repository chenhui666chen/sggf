"""
向量数据库同步服务。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from app.services.agents.knowledge_base import NovelKnowledgeBase

    VECTOR_DB_AVAILABLE = True
    _VectorKBType = NovelKnowledgeBase
except ImportError as exc:
    VECTOR_DB_AVAILABLE = False
    _VectorKBType = None  # type: ignore[assignment]
    logger.info("向量库未启用: %s", exc)
    logger.info("仅使用数据库存储，语义检索功能将不可用")

_vector_kb = None  # type: ignore[var-annotated]


def get_vector_kb():
    """获取向量库实例。"""
    global _vector_kb
    if not VECTOR_DB_AVAILABLE or _VectorKBType is None:
        return None
    if _vector_kb is None:
        try:
            _vector_kb = _VectorKBType()
        except Exception as exc:
            logger.warning("向量库初始化失败: %s", exc)
            return None
    return _vector_kb


def _delete_existing_documents(collection, where_filter: Dict[str, Any]) -> int:
    try:
        existing = collection.get(where=where_filter)
    except Exception as exc:
        logger.warning("查询旧向量文档失败: %s", exc)
        return 0

    ids = existing.get("ids") if existing else None
    if not ids:
        return 0

    collection.delete(ids=ids)
    return len(ids)


def _project_filter(project_id: int | str) -> Dict[str, str]:
    return {"project_id": str(project_id)}


def sync_to_vector_db(kb_type: str, name: str, content: str, metadata: dict | None = None):
    """
    同步内容到向量数据库。

    Args:
        kb_type: 内容类型 ('world', 'character', 'plot', 'chapter')
        name: 内容名称
        content: 内容文本
        metadata: 可选元数据
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return

    meta = dict(metadata or {})

    try:
        if kb_type == "world":
            vector_kb.add_world_setting(name, content, meta)
        elif kb_type == "character":
            vector_kb.add_character(name, content, meta)
        elif kb_type == "plot":
            project_id = meta.get("project_id")
            collection = getattr(vector_kb.vectorstore, "_collection", None)
            if collection is not None and project_id is not None:
                _delete_existing_documents(
                    collection,
                    {"$and": [{"type": "plot_outline"}, _project_filter(project_id)]},
                )
            vector_kb.add_plot_outline(name, content, meta)
        elif kb_type == "chapter":
            chapter_num = int(meta.get("chapter_number") or meta.get("chapter_num") or 0)
            project_id = meta.get("project_id")
            collection = getattr(vector_kb.vectorstore, "_collection", None)
            if collection is not None and project_id is not None and chapter_num > 0:
                _delete_existing_documents(
                    collection,
                    {
                        "$and": [
                            {"type": "chapter"},
                            _project_filter(project_id),
                            {"chapter_number": str(chapter_num)},
                        ]
                    },
                )
            vector_kb.add_chapter(chapter_num, name, content, meta)
        else:
            logger.warning("未知向量同步类型: %s", kb_type)
            return

        logger.debug("已同步到向量库: %s - %s", kb_type, name)
    except Exception as exc:
        logger.warning("向量库同步失败: %s", exc)


def upsert_character_to_vector_db(
    character_id: int,
    character_name: str,
    content: str,
    project_id: int,
    metadata: dict | None = None,
):
    """
    更新或插入人物到向量库。
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return

    try:
        collection = getattr(vector_kb.vectorstore, "_collection", None)
        if collection is None:
            return

        deleted_count = _delete_existing_documents(
            collection,
            {
                "$and": [
                    {"type": "character"},
                    _project_filter(project_id),
                    {"character_id": str(character_id)},
                ]
            },
        )
        if deleted_count:
            logger.debug("已删除旧版本人物向量: %s (%s)", character_name, deleted_count)

        meta = dict(metadata or {})
        meta.update(
            {
                "type": "character",
                "project_id": str(project_id),
                "character_id": str(character_id),
                "character_name": character_name,
            }
        )
        vector_kb.add_character(character_name, content, meta)
        logger.debug("已更新人物向量: %s", character_name)
    except Exception as exc:
        logger.warning("人物向量更新失败: %s", exc)


def upsert_setting_to_vector_db(
    setting_id: int,
    setting_name: str,
    content: str,
    project_id: int,
    category: str,
    metadata: dict | None = None,
):
    """
    更新或插入设定项到向量库。
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return

    try:
        collection = getattr(vector_kb.vectorstore, "_collection", None)
        if collection is None:
            return

        deleted_count = _delete_existing_documents(
            collection,
            {
                "$and": [
                    {"type": "world_setting"},
                    _project_filter(project_id),
                    {"setting_id": str(setting_id)},
                ]
            },
        )
        if deleted_count:
            logger.debug("已删除旧版本设定向量: %s (%s)", setting_name, deleted_count)

        meta = dict(metadata or {})
        meta.update(
            {
                "type": "world_setting",
                "project_id": str(project_id),
                "setting_id": str(setting_id),
                "setting_name": setting_name,
                "category": category,
            }
        )
        vector_kb.add_world_setting(setting_name, content, meta)
        logger.debug("已更新设定向量: %s [%s]", setting_name, category)
    except Exception as exc:
        logger.warning("设定向量更新失败: %s", exc)


def delete_character_from_vector_db(character_id: int, project_id: int):
    """从向量库删除人物。"""
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return

    try:
        collection = getattr(vector_kb.vectorstore, "_collection", None)
        if collection is None:
            return

        deleted_count = _delete_existing_documents(
            collection,
            {
                "$and": [
                    {"type": "character"},
                    _project_filter(project_id),
                    {"character_id": str(character_id)},
                ]
            },
        )
        if deleted_count:
            logger.debug("已从向量库删除人物: character_id=%s", character_id)
    except Exception as exc:
        logger.warning("删除人物向量失败: %s", exc)


def delete_setting_from_vector_db(setting_id: int, project_id: int):
    """从向量库删除设定。"""
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return

    try:
        collection = getattr(vector_kb.vectorstore, "_collection", None)
        if collection is None:
            return

        deleted_count = _delete_existing_documents(
            collection,
            {
                "$and": [
                    {"type": "world_setting"},
                    _project_filter(project_id),
                    {"setting_id": str(setting_id)},
                ]
            },
        )
        if deleted_count:
            logger.debug("已从向量库删除设定: setting_id=%s", setting_id)
    except Exception as exc:
        logger.warning("删除设定向量失败: %s", exc)
