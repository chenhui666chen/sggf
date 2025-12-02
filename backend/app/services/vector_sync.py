"""
向量数据库同步服务
提供将内容同步到 ChromaDB 向量库的功能
"""

# 导入向量库
try:
    from app.services.agents.knowledge_base import NovelKnowledgeBase
    VECTOR_DB_AVAILABLE = True
    _VectorKBType = NovelKnowledgeBase
except ImportError as e:
    VECTOR_DB_AVAILABLE = False
    _VectorKBType = None  # type: ignore
    print(f"⚠️ 向量库未启用: {e}")
    print("   只使用数据库存储，语义搜索功能将不可用")

# 全局向量库实例
_vector_kb = None  # type: ignore


def get_vector_kb():
    """获取向量库实例"""
    global _vector_kb
    if not VECTOR_DB_AVAILABLE or _VectorKBType is None:
        return None
    if _vector_kb is None:
        try:
            _vector_kb = _VectorKBType()
        except Exception as e:
            print(f"⚠️ 向量库初始化失败: {e}")
            return None
    return _vector_kb


def sync_to_vector_db(kb_type: str, name: str, content: str, metadata: dict | None = None):
    """
    同步内容到向量数据库
    
    Args:
        kb_type: 内容类型 ('world', 'character', 'plot', 'chapter')
        name: 内容名称
        content: 内容文本
        metadata: 可选的元数据字典
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return  # 向量库不可用，静默跳过
    
    try:
        meta = metadata or {}
        if kb_type == "world":
            vector_kb.add_world_setting(name, content, meta)
        elif kb_type == "character":
            vector_kb.add_character(name, content, meta)
        elif kb_type == "plot":
            vector_kb.add_chapter(0, name, content, meta)  # 情节使用chapter方法
        elif kb_type == "chapter":
            # 提取章节号（如果在metadata中提供）
            chapter_num = int(metadata.get("chapter_number", 0)) if metadata and "chapter_number" in metadata else 0
            vector_kb.add_chapter(chapter_num, name, content, meta)
        print(f"✅ 已同步到向量库: {kb_type} - {name}")
    except Exception as e:
        print(f"⚠️ 向量库同步失败: {e}")

