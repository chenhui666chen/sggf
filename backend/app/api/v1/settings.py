"""
类型化设定管理API
"""
from typing import List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.setting import SettingCollection, SettingItem
from app.schemas.settings import (
    SettingCollectionCreate,
    SettingCollectionUpdate,
    SettingCollectionResponse,
    SettingItemCreate,
    SettingItemUpdate,
    SettingItemResponse,
    ReorderItemsRequest,
)
from app.services.setting_templates import (
    SETTING_TEMPLATES,
    get_templates_metadata,
    build_project_settings_summary,
)

router = APIRouter(prefix="/api/v1", tags=["settings"])


class TemplateMetadata(BaseModel):
    key: str
    name: str
    description: str = ""
    collections_count: int


class ApplyTemplateRequest(BaseModel):
    template_key: str
    clear_existing: bool = False


def _ensure_project_owned(project_id: int, current_user: User, db: Session) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def _item_to_schema(item: SettingItem) -> SettingItemResponse:
    tags: Optional[List[str]] = json.loads(item.tags) if item.tags else None
    relations = json.loads(item.relations) if item.relations else None

    return SettingItemResponse(
        id=item.id,
        collection_id=item.collection_id,
        name=item.name,
        code=item.code,
        level=item.level,
        tags=tags,
        content=item.content,
        relations=relations,
        order=item.order,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get(
    "/projects/{project_id}/setting-collections",
    response_model=List[SettingCollectionResponse],
)
async def list_setting_collections(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取项目下的所有设定集合"""
    _ensure_project_owned(project_id, current_user, db)

    collections = (
        db.query(SettingCollection)
        .filter(SettingCollection.project_id == project_id)
        .order_by(SettingCollection.order, SettingCollection.id)
        .all()
    )
    return collections


@router.post(
    "/projects/{project_id}/setting-collections",
    response_model=SettingCollectionResponse,
)
async def create_setting_collection(
    project_id: int,
    data: SettingCollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建设定集合"""
    _ensure_project_owned(project_id, current_user, db)

    collection = SettingCollection(
        project_id=project_id,
        name=data.name,
        category=data.category,
        description=data.description,
        order=data.order,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.put("/setting-collections/{collection_id}", response_model=SettingCollectionResponse)
async def update_setting_collection(
    collection_id: int,
    data: SettingCollectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新设定集合"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    for key, value in data.dict(exclude_unset=True).items():
        setattr(collection, key, value)

    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


@router.delete("/setting-collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting_collection(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设定集合及其所有设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    db.delete(collection)
    db.commit()


@router.get("/setting-collections/{collection_id}/items", response_model=List[SettingItemResponse])
async def list_setting_items(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取集合下的所有设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .order_by(SettingItem.order, SettingItem.id)
        .all()
    )
    return [_item_to_schema(item) for item in items]


@router.post("/setting-collections/{collection_id}/items", response_model=SettingItemResponse)
async def create_setting_item(
    collection_id: int,
    data: SettingItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建设定项"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    item = SettingItem(
        collection_id=collection_id,
        name=data.name,
        code=data.code,
        level=data.level,
        tags=json.dumps(data.tags) if data.tags is not None else None,
        content=data.content,
        relations=json.dumps(data.relations) if data.relations is not None else None,
        order=data.order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_schema(item)


@router.put("/setting-items/{item_id}", response_model=SettingItemResponse)
async def update_setting_item(
    item_id: int,
    data: SettingItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新设定项"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    data_dict = data.dict(exclude_unset=True)
    if "tags" in data_dict:
        item.tags = json.dumps(data_dict.pop("tags")) if data_dict["tags"] is not None else None
    if "relations" in data_dict:
        item.relations = (
            json.dumps(data_dict.pop("relations")) if data_dict["relations"] is not None else None
        )

    for key, value in data_dict.items():
        setattr(item, key, value)

    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_schema(item)


@router.delete("/setting-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除设定项"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    db.delete(item)
    db.commit()


@router.patch(
    "/setting-collections/{collection_id}/items/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reorder_setting_items(
    collection_id: int,
    payload: ReorderItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量更新设定项顺序"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    id_to_order = {item.id: item.order for item in payload.items}

    items = (
        db.query(SettingItem)
        .filter(SettingItem.collection_id == collection_id)
        .all()
    )

    for item in items:
        if item.id in id_to_order:
            item.order = id_to_order[item.id]
            db.add(item)

    db.commit()

@router.get("/setting-templates", response_model=List[TemplateMetadata])
async def list_setting_templates(
    current_user: User = Depends(get_current_user),
) -> List[TemplateMetadata]:
    """列出可用的类型化设定模板"""
    metadata = get_templates_metadata()
    return [TemplateMetadata(**m) for m in metadata]


@router.post("/projects/{project_id}/setting-templates/apply")
async def apply_setting_template(
    project_id: int,
    payload: ApplyTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将指定模板应用到项目下，批量创建设定集合和设定项"""
    _ensure_project_owned(project_id, current_user, db)

    template = SETTING_TEMPLATES.get(payload.template_key)
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # 可选：清空已有设定集合
    if payload.clear_existing:
        collections = (
            db.query(SettingCollection)
            .filter(SettingCollection.project_id == project_id)
            .all()
        )
        for col in collections:
            db.delete(col)
        db.flush()

    # 为新建集合确定起始 order
    max_order_row = (
        db.query(SettingCollection.order)
        .filter(SettingCollection.project_id == project_id)
        .order_by(SettingCollection.order.desc())
        .first()
    )
    start_order = max_order_row[0] + 1 if max_order_row and max_order_row[0] is not None else 0

    created_collections = 0

    for idx, collection_data in enumerate(template.get("collections", [])):
        collection = SettingCollection(
            project_id=project_id,
            name=collection_data.get("name", ""),
            category=collection_data.get("category"),
            description=collection_data.get("description"),
            order=start_order + idx,
        )
        db.add(collection)
        db.flush()  # 确保拿到 collection.id
        created_collections += 1

        for item_idx, item_data in enumerate(collection_data.get("items", [])):
            item = SettingItem(
                collection_id=collection.id,
                name=item_data.get("name", ""),
                code=item_data.get("code"),
                level=item_data.get("level"),
                tags=json.dumps(item_data.get("tags")) if item_data.get("tags") is not None else None,
                content=item_data.get("content"),
                relations=json.dumps(item_data.get("relations")) if item_data.get("relations") is not None else None,
                order=item_idx,
            )
            db.add(item)

    db.commit()

    return {
        "success": True,
        "applied_template": payload.template_key,
        "created_collections": created_collections,
    }


@router.get("/projects/{project_id}/settings-summary")
async def get_project_settings_summary(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成并返回指定项目的类型化设定摘要，供前端或AI调用使用"""
    _ensure_project_owned(project_id, current_user, db)
    summary = build_project_settings_summary(project_id, db)
    return {"project_id": project_id, "summary": summary}


