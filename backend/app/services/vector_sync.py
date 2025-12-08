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


def upsert_character_to_vector_db(
    character_id: int,
    character_name: str,
    content: str,
    project_id: int,
    metadata: dict | None = None
):
    """
    更新或插入人物到向量库（先删除旧版本，再添加新版本）
    
    Args:
        character_id: 人物ID
        character_name: 人物名称
        content: 人物详细信息文本
        project_id: 项目ID
        metadata: 可选元数据
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return
    
    try:
        collection = vector_kb.vectorstore._collection
        if collection is None:
            return
        
        # 删除旧版本
        try:
            existing = collection.get(
                where={
                    "$and": [
                        {"type": "character"},
                        {"project_id": str(project_id)},
                        {"character_id": str(character_id)}
                    ]
                }
            )
            if existing and existing.get('ids'):
                collection.delete(ids=existing['ids'])
                print(f"🗑️ 已删除旧版本人物向量: {character_name}")
        except Exception as e:
            print(f"⚠️ 删除旧版本失败: {e}")
        
        # 添加新版本
        meta = metadata or {}
        meta.update({
            "type": "character",
            "project_id": str(project_id),
            "character_id": str(character_id),
            "character_name": character_name,
        })
        vector_kb.add_character(character_name, content, meta)
        print(f"✅ 已更新人物向量: {character_name}")
    except Exception as e:
        print(f"⚠️ 人物向量更新失败: {e}")


def upsert_setting_to_vector_db(
    setting_id: int,
    setting_name: str,
    content: str,
    project_id: int,
    category: str,
    metadata: dict | None = None
):
    """
    更新或插入设定项到向量库
    
    Args:
        setting_id: 设定项ID
        setting_name: 设定名称
        content: 设定内容
        project_id: 项目ID
        category: 设定类别
        metadata: 可选元数据
    """
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return
    
    try:
        collection = vector_kb.vectorstore._collection
        if collection is None:
            return
        
        # 删除旧版本
        try:
            existing = collection.get(
                where={
                    "$and": [
                        {"type": "world_setting"},
                        {"project_id": str(project_id)},
                        {"setting_id": str(setting_id)}
                    ]
                }
            )
            if existing and existing.get('ids'):
                collection.delete(ids=existing['ids'])
                print(f"🗑️ 已删除旧版本设定向量: {setting_name}")
        except Exception as e:
            print(f"⚠️ 删除旧版本失败: {e}")
        
        # 添加新版本
        meta = metadata or {}
        meta.update({
            "type": "world_setting",
            "project_id": str(project_id),
            "setting_id": str(setting_id),
            "setting_name": setting_name,
            "category": category,
        })
        vector_kb.add_world_setting(setting_name, content, meta)
        print(f"✅ 已更新设定向量: {setting_name} [{category}]")
    except Exception as e:
        print(f"⚠️ 设定向量更新失败: {e}")


def delete_character_from_vector_db(character_id: int, project_id: int):
    """从向量库删除人物"""
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return
    
    try:
        collection = vector_kb.vectorstore._collection
        if collection is None:
            return
        
        existing = collection.get(
            where={
                "$and": [
                    {"type": "character"},
                    {"project_id": str(project_id)},
                    {"character_id": str(character_id)}
                ]
            }
        )
        if existing and existing.get('ids'):
            collection.delete(ids=existing['ids'])
            print(f"🗑️ 已从向量库删除人物 (ID: {character_id})")
    except Exception as e:
        print(f"⚠️ 删除人物向量失败: {e}")


def delete_setting_from_vector_db(setting_id: int, project_id: int):
    """从向量库删除设定"""
    vector_kb = get_vector_kb()
    if vector_kb is None:
        return
    
    try:
        collection = vector_kb.vectorstore._collection
        if collection is None:
            return
        
        existing = collection.get(
            where={
                "$and": [
                    {"type": "world_setting"},
                    {"project_id": str(project_id)},
                    {"setting_id": str(setting_id)}
                ]
            }
        )
        if existing and existing.get('ids'):
            collection.delete(ids=existing['ids'])
            print(f"🗑️ 已从向量库删除设定 (ID: {setting_id})")
    except Exception as e:
        print(f"⚠️ 删除设定向量失败: {e}")

