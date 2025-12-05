"""角色与角色功法管理 API"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project, Chapter
from app.models.character import Character, CharacterTechnique
from app.models.setting import SettingItem, SettingCollection
from app.schemas.character import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterTechniqueUpdateList,
    CharacterTechniqueResponse,
)

router = APIRouter(prefix="/api/v1", tags=["characters"])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _ensure_project_owned(project_id: int, current_user: User, db: Session) -> Project:
    """确保项目存在且属于当前用户，否则抛出 404/权限错误"""
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found",
        )
    return project


# ---------------------------------------------------------------------------
# 角色（Character）CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/characters",
    response_model=List[CharacterResponse],
)
async def list_characters(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterResponse]:
    """获取某项目下的全部结构化角色档案"""

    _ensure_project_owned(project_id, current_user, db)

    characters = (
        db.query(Character)
        .filter(Character.project_id == project_id)
        .order_by(Character.id)
        .all()
    )
    return characters


@router.post(
    "/projects/{project_id}/characters",
    response_model=CharacterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_character(
    project_id: int,
    data: CharacterCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterResponse:
    """在项目下创建新角色"""

    import json

    _ensure_project_owned(project_id, current_user, db)

    character = Character(
        project_id=project_id,
        name=data.name,
        role=data.role,
        gender=data.gender,
        age=data.age,
        faction=data.faction,
        importance_level=data.importance_level,
        appearance_status=data.appearance_status,
        life_status=data.life_status,
        current_realm_item_id=data.current_realm_item_id,
        first_appearance_chapter=data.first_appearance_chapter,
        summary=data.summary,
        profile=data.profile,
        tags=None if data.tags is None else json.dumps(data.tags),
        relations=None if data.relations is None else json.dumps(data.relations),
    )

    db.add(character)
    db.commit()
    db.refresh(character)
    return character


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterResponse:
    """获取单个角色详情"""

    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    _ensure_project_owned(character.project_id, current_user, db)
    return character


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: int,
    data: CharacterUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterResponse:
    """更新角色信息"""

    import json

    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    _ensure_project_owned(character.project_id, current_user, db)

    data_dict = data.dict(exclude_unset=True)

    # JSON 字段单独处理
    if "tags" in data_dict:
        character.tags = (
            None if data_dict["tags"] is None else json.dumps(data_dict["tags"])
        )
        data_dict.pop("tags")
    if "relations" in data_dict:
        character.relations = (
            None
            if data_dict["relations"] is None
            else json.dumps(data_dict["relations"])
        )
        data_dict.pop("relations")

    for key, value in data_dict.items():
        setattr(character, key, value)

    db.add(character)
    db.commit()
    db.refresh(character)
    
    # 🆕 同步到向量库
    try:
        from app.services.vector_sync import upsert_character_to_vector_db
        # 生成人物向量内容
        vector_content = f"""
人物名称: {character.name}
角色类型: {character.role or '未设定'}
所属势力: {character.faction or '未设定'}
状态: {character.life_status or '未知'}
简介: {character.summary or ''}
详细信息: {character.profile or ''}
""".strip()
        upsert_character_to_vector_db(
            character_id=character.id,
            character_name=character.name,
            content=vector_content,
            project_id=character.project_id
        )
    except Exception as e:
        print(f"⚠️ 同步人物到向量库失败: {e}")
    
    return character


@router.delete("/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """删除角色及其功法关联"""

    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    _ensure_project_owned(character.project_id, current_user, db)

    # 🆕 从向量库删除
    project_id = character.project_id
    char_id = character.id
    
    db.delete(character)
    db.commit()
    
    try:
        from app.services.vector_sync import delete_character_from_vector_db
        delete_character_from_vector_db(char_id, project_id)
    except Exception as e:
        print(f"⚠️ 从向量库删除人物失败: {e}")


@router.get("/characters/{character_id}/auto-tracked-relations")
async def get_character_auto_tracked_relations(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 获取人物的自动追踪关联数据
    
    返回：
    {
        "techniques": [{"id": 1, "name": "九天剑诀", "chapters": [1,3]}],
        "artifacts": [{"id": 2, "name": "赤霄剑", "chapters": [1]}],
        "locations": [{"id": 3, "name": "天剑宗", "chapters": [1,2]}]
    }
    """
    import json
    
    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    _ensure_project_owned(character.project_id, current_user, db)
    
    # 解析JSON字段
    technique_ids = json.loads(character.techniques_json or "[]")
    artifact_ids = json.loads(character.artifacts_json or "[]")
    location_ids = json.loads(character.related_locations_json or "[]")
    
    # 获取详细信息
    techniques = []
    for tid in technique_ids:
        item = db.query(SettingItem).get(tid)
        if item:
            # 获取该设定项引用的章节
            referenced_chapters = json.loads(item.referenced_chapters or "[]")
            techniques.append({
                "id": item.id,
                "name": item.name,
                "chapters": referenced_chapters
            })
    
    artifacts = []
    for aid in artifact_ids:
        item = db.query(SettingItem).get(aid)
        if item:
            referenced_chapters = json.loads(item.referenced_chapters or "[]")
            artifacts.append({
                "id": item.id,
                "name": item.name,
                "chapters": referenced_chapters
            })
    
    locations = []
    for lid in location_ids:
        item = db.query(SettingItem).get(lid)
        if item:
            referenced_chapters = json.loads(item.referenced_chapters or "[]")
            locations.append({
                "id": item.id,
                "name": item.name,
                "chapters": referenced_chapters
            })
    
    return {
        "techniques": techniques,
        "artifacts": artifacts,
        "locations": locations
    }


# ---------------------------------------------------------------------------
# 角色功法关联（CharacterTechnique）
# ---------------------------------------------------------------------------


def _to_tech_response(ct: CharacterTechnique) -> CharacterTechniqueResponse:
    """将 CharacterTechnique ORM 对象转换为响应 Schema"""

    return CharacterTechniqueResponse(
        id=ct.id,
        character_id=ct.character_id,
        technique_item_id=ct.technique_item_id,
        proficiency=ct.proficiency,
        learned_at_chapter=ct.learned_at_chapter,
        notes=ct.notes,
        technique_name=ct.technique_item.name if ct.technique_item else None,
        technique_code=ct.technique_item.code if ct.technique_item else None,
        created_at=ct.created_at,
        updated_at=ct.updated_at,
    )


@router.get(
    "/characters/{character_id}/techniques",
    response_model=List[CharacterTechniqueResponse],
)
async def list_character_techniques(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterTechniqueResponse]:
    """获取角色当前已掌握的功法列表"""

    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    _ensure_project_owned(character.project_id, current_user, db)

    techniques = (
        db.query(CharacterTechnique)
        .filter(CharacterTechnique.character_id == character_id)
        .order_by(CharacterTechnique.id)
        .all()
    )
    return [_to_tech_response(ct) for ct in techniques]


@router.put(
    "/characters/{character_id}/techniques",
    response_model=List[CharacterTechniqueResponse],
)
async def update_character_techniques(
    character_id: int,
    data: CharacterTechniqueUpdateList,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterTechniqueResponse]:
    """覆盖式更新角色功法列表"""

    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )

    _ensure_project_owned(character.project_id, current_user, db)

    # 校验所有 technique_item_id 是否有效
    technique_ids = [t.technique_item_id for t in data.techniques]
    if technique_ids:
        items = (
            db.query(SettingItem)
            .filter(SettingItem.id.in_(technique_ids))
            .all()
        )
        found_ids = {item.id for item in items}
        missing_ids = [tid for tid in technique_ids if tid not in found_ids]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid technique_item_id(s): {missing_ids}",
            )

    # 删除旧关联
    db.query(CharacterTechnique).filter(
        CharacterTechnique.character_id == character_id
    ).delete(synchronize_session=False)

    # 插入新关联
    new_records: List[CharacterTechnique] = []
    for t in data.techniques:
        ct = CharacterTechnique(
            character_id=character_id,
            technique_item_id=t.technique_item_id,
            proficiency=t.proficiency,
            learned_at_chapter=t.learned_at_chapter,
            notes=t.notes,
        )
        db.add(ct)
        new_records.append(ct)

    db.commit()

    refreshed = (
        db.query(CharacterTechnique)
        .filter(CharacterTechnique.character_id == character_id)
        .order_by(CharacterTechnique.id)
        .all()
    )
    return [_to_tech_response(ct) for ct in refreshed]


# ---------------------------------------------------------------------------
# 项目可用功法列表（供前端下拉选择）
# ---------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/techniques",
    response_model=List[CharacterTechniqueResponse],
)
async def list_project_techniques(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[CharacterTechniqueResponse]:
    """获取项目下所有可供选择的功法设定项列表"""

    _ensure_project_owned(project_id, current_user, db)

    # 找到该项目中 category 为 "technique_system" 的所有设定集合
    collections = (
        db.query(SettingCollection)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == "technique_system",
        )
        .all()
    )
    collection_ids = [c.id for c in collections]
    if not collection_ids:
        return []

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id.in_(collection_ids))
        .order_by(SettingItem.order, SettingItem.id)
        .all()
    )

    # 这里借用 CharacterTechniqueResponse 的部分字段承载功法元数据
    result: List[CharacterTechniqueResponse] = []
    for item in items:
        result.append(
            CharacterTechniqueResponse(
                id=item.id,  # 用 SettingItem.id 占用 id 字段
                character_id=0,
                technique_item_id=item.id,
                proficiency=None,
                learned_at_chapter=None,
                notes=None,
                technique_name=item.name,
                technique_code=item.code,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    return result


@router.get("/characters/{character_id}/appearance-timeline")
async def get_character_appearance_timeline(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 获取人物出场历程时间线
    
    返回人物在各章节的出场记录，包括：
    - 章节基本信息（章节号、标题、字数）
    - 人物在该章的相关摘要
    """
    import json
    import re
    
    character = db.query(Character).get(character_id)
    if not character:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Character not found",
        )
    
    _ensure_project_owned(character.project_id, current_user, db)
    
    # 解析出场章节列表（存储的是章节ID）
    appearance_chapter_ids = json.loads(character.appearance_chapters or "[]")
    
    if not appearance_chapter_ids:
        return {
            "character_id": character_id,
            "character_name": character.name,
            "total_appearances": 0,
            "timeline": []
        }
    
    # 获取章节详情
    chapters = db.query(Chapter).filter(
        Chapter.id.in_(appearance_chapter_ids)
    ).order_by(Chapter.chapter_number).all()
    
    timeline = []
    for chapter in chapters:
        # 提取人物在该章的相关段落
        excerpts = []
        if chapter.content and character.name:
            paragraphs = chapter.content.split('\n\n')
            for para in paragraphs:
                if character.name in para:
                    # 取段落前200字作为摘要
                    clean_para = re.sub(r'\s+', ' ', para).strip()
                    if len(clean_para) > 200:
                        clean_para = clean_para[:200] + "..."
                    if clean_para and clean_para not in excerpts:
                        excerpts.append(clean_para)
                    if len(excerpts) >= 3:  # 每章最多3条摘要
                        break
        
        timeline.append({
            "chapter_id": chapter.id,
            "chapter_number": chapter.chapter_number,
            "chapter_title": chapter.title,
            "word_count": chapter.word_count or 0,
            "excerpts": excerpts,
            "summary": chapter.summary  # 章节摘要
        })
    
    return {
        "character_id": character_id,
        "character_name": character.name,
        "total_appearances": len(timeline),
        "first_appearance": timeline[0]["chapter_number"] if timeline else None,
        "last_appearance": timeline[-1]["chapter_number"] if timeline else None,
        "timeline": timeline
    }


# ---------------------------------------------------------------------------
# 人物卡同步到工作流
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/sync-characters-to-workflow")
async def sync_characters_to_workflow(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 将项目的结构化人物卡数据同步到工作流的人物设定字段
    
    返回：
    {
        "success": true,
        "message": "已同步68个人物到工作流",
        "character_count": 68,
        "text_length": 12345,
        "preview": "# 人物设定\n\n## 主角\n\n### 林风..."
    }
    """
    from sqlalchemy import text
    from app.services.character_text_generator import CharacterTextGenerator
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 1. 生成人物文本
    characters_text = CharacterTextGenerator.generate_project_characters_text(
        project_id=project_id,
        db=db,
        group_by_importance=True,
        include_all_details=True,
    )
    
    # 2. 获取统计信息
    stats = CharacterTextGenerator.get_character_stats(project_id, db)
    
    # 3. 更新到project_settings表
    update_query = text("""
        UPDATE project_settings
        SET characters = :content, updated_at = :updated_at
        WHERE project_id = :project_id
    """)
    
    from datetime import datetime
    db.execute(update_query, {
        "content": characters_text,
        "updated_at": datetime.now().isoformat(),
        "project_id": project_id
    })
    db.commit()
    
    # 4. 返回结果
    preview = characters_text[:500] + "..." if len(characters_text) > 500 else characters_text
    
    return {
        "success": True,
        "message": f"已同步{stats['total']}个人物到工作流",
        "character_count": stats["total"],
        "text_length": len(characters_text),
        "stats": stats,
        "preview": preview
    }


@router.get("/projects/{project_id}/characters-text-preview")
async def get_characters_text_preview(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 预览人物卡生成的文本（不保存）
    
    用于同步前预览效果
    """
    from app.services.character_text_generator import CharacterTextGenerator
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 生成人物文本
    characters_text = CharacterTextGenerator.generate_project_characters_text(
        project_id=project_id,
        db=db,
        group_by_importance=True,
        include_all_details=True,
    )
    
    stats = CharacterTextGenerator.get_character_stats(project_id, db)
    
    return {
        "character_count": stats["total"],
        "text_length": len(characters_text),
        "stats": stats,
        "text": characters_text
    }


# ---------------------------------------------------------------------------
# 🆕 人物关系网络图 API
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/character-relationship-graph")
async def get_character_relationship_graph(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 获取人物关系网络图数据
    
    返回适合前端可视化库（如 React Flow）使用的节点和边数据
    
    返回:
    {
        "nodes": [{"id": "1", "name": "李铁柱", "role": "主角", ...}],
        "edges": [{"source": "1", "target": "2", "label": "师徒", ...}],
        "stats": {"total_nodes": 10, "total_edges": 15}
    }
    """
    import json
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 获取所有人物
    characters = db.query(Character).filter(
        Character.project_id == project_id
    ).all()
    
    if not characters:
        return {
            "nodes": [],
            "edges": [],
            "stats": {"total_nodes": 0, "total_edges": 0}
        }
    
    # 构建节点
    nodes = []
    character_id_map = {}  # name -> id 映射
    
    # 重要程度颜色映射
    importance_colors = {
        "主角": "#ff6b6b",
        "配角": "#4ecdc4",
        "跑龙套": "#95e1d3",
        "群众演员": "#dfe6e9",
    }
    
    # 角色类型颜色
    role_colors = {
        "主角方": "#74b9ff",
        "对手方": "#fd79a8",
        "中立方": "#ffeaa7",
    }
    
    for char in characters:
        node = {
            "id": str(char.id),
            "character_id": char.id,  # 🆕 添加数字ID用于前端点击编辑
            "name": char.name,
            "role": char.role or "未分类",
            "importance": char.importance_level or "配角",
            "gender": char.gender,
            "age": char.age,
            "faction": char.faction,
            "summary": char.summary[:50] + "..." if char.summary and len(char.summary) > 50 else char.summary,
            "color": importance_colors.get(char.importance_level, "#b2bec3"),
            "borderColor": role_colors.get(char.role, "#636e72"),
        }
        nodes.append(node)
        character_id_map[char.name] = str(char.id)
    
    # 构建边（关系）
    edges = []
    edge_set = set()  # 用于去重
    
    for char in characters:
        # 从 relations 字段解析关系
        if char.relations:
            try:
                relations = json.loads(char.relations)
                if isinstance(relations, list):
                    for rel in relations:
                        if isinstance(rel, dict):
                            target_name = rel.get("target", "")
                            rel_type = rel.get("type", "关联")
                            if target_name and target_name in character_id_map:
                                source_id = str(char.id)
                                target_id = character_id_map[target_name]
                                # 去重（双向只保留一条）
                                edge_key = tuple(sorted([source_id, target_id]))
                                if edge_key not in edge_set:
                                    edge_set.add(edge_key)
                                    edges.append({
                                        "id": f"e{source_id}-{target_id}",
                                        "source": source_id,
                                        "target": target_id,
                                        "label": rel_type,
                                        "type": "smoothstep",
                                    })
            except:
                pass
        
        # 从 relationship_network 字段解析
        if char.relationship_network:
            try:
                network = json.loads(char.relationship_network)
                if isinstance(network, list):
                    for rel in network:
                        if isinstance(rel, dict):
                            target_name = rel.get("target", rel.get("name", ""))
                            rel_type = rel.get("type", rel.get("relation", "关联"))
                            if target_name and target_name in character_id_map:
                                source_id = str(char.id)
                                target_id = character_id_map[target_name]
                                edge_key = tuple(sorted([source_id, target_id]))
                                if edge_key not in edge_set:
                                    edge_set.add(edge_key)
                                    edges.append({
                                        "id": f"e{source_id}-{target_id}",
                                        "source": source_id,
                                        "target": target_id,
                                        "label": rel_type,
                                        "type": "smoothstep",
                                    })
            except:
                pass
    
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        }
    }
