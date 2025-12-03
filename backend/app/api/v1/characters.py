"""角色与角色功法管理 API"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
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

    db.delete(character)
    db.commit()


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

