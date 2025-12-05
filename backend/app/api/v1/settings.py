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
from app.models.graph import KnowledgeGraphEdge
from app.schemas.settings import (
    SettingCollectionCreate,
    SettingCollectionUpdate,
    SettingCollectionResponse,
    SettingItemCreate,
    SettingItemUpdate,
    SettingItemResponse,
    ReorderItemsRequest,
    BulkMoveItemsRequest,
    SetParentRequest,
    ReorderUnderParentRequest,
    GraphEdgeCreate,
    GraphEdgeResponse,
)
from app.services.setting_templates import (
    SETTING_TEMPLATES,
    get_templates_metadata,
    build_project_settings_summary,
    get_hierarchy_config_json,
)
from app.services.setting_auto_merge import SettingAutoMergeService
from app.services.setting_consistency import SettingConsistencyService

router = APIRouter(prefix="/api/v1", tags=["settings"])


class TemplateCollectionInfo(BaseModel):
    name: str
    category: str


class TemplateMetadata(BaseModel):
    key: str
    name: str
    description: str = ""
    collections_count: int
    collections: List[TemplateCollectionInfo] = []


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
    try:
        tags: Optional[List[str]] = json.loads(item.tags) if item.tags else None
    except Exception:
        tags = (item.tags.split(',') if item.tags else None)
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
        depth=item.depth,
        node_type=item.node_type,
        is_leaf=item.is_leaf,
        path=item.path,
        summary=item.summary,
        snapshots=item.snapshots,
        confidence_score=item.confidence_score,
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
        max_depth=(data.max_depth if data.max_depth is not None else 2),
        hierarchy_config=data.hierarchy_config,
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


@router.get("/setting-collections/{collection_id}/items/by-path", response_model=List[SettingItemResponse])
async def list_setting_items_by_path(
    collection_id: int,
    prefix: Optional[str] = None,
    max_depth: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按路径前缀与最大层级过滤设定项（用于层级加载）"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    _ensure_project_owned(collection.project_id, current_user, db)

    q = db.query(SettingItem).filter(SettingItem.collection_id == collection_id)
    if prefix:
        q = q.filter(SettingItem.path.like(f"{prefix}%"))
    if max_depth is not None:
        q = q.filter(SettingItem.depth <= max_depth)
    items = q.order_by(SettingItem.order, SettingItem.id).all()
    return [_item_to_schema(item) for item in items]


@router.get("/setting-collections/{collection_id}/items/tree")
async def get_setting_items_tree(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回集合内设定项的树形结构（基于 path 分段和 depth）"""
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

    # 构建树：path 按 '/' 分段
    def ensure_node(children: dict, key: str):
        if key not in children:
            children[key] = {"name": key, "children": {}, "depth": None, "is_leaf": False, "item": None}
        return children[key]

    root = {"name": collection.name, "children": {}, "depth": 0, "is_leaf": False, "item": None}

    for it in items:
        segs = (it.path or f"{collection.name}/{it.name}").split("/")
        node = root
        # 从第二段开始（第一段为集合名）
        for i, seg in enumerate(segs[1:], start=1):
            node = ensure_node(node["children"], seg)
            node["depth"] = i
        # 叶子信息
        node["is_leaf"] = bool(it.is_leaf)
        node["item"] = _item_to_schema(it)

    def flatten(node):
        return {
            "name": node["name"],
            "depth": node["depth"],
            "is_leaf": node["is_leaf"],
            "item": node["item"],
            "children": [flatten(child) for child in node["children"].values()],
        }

    return {"collection": collection.name, "tree": [flatten(child) for child in root["children"].values()]}



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

    # 计算默认层级与路径
    default_depth = 2
    default_node_type = "category" if (collection.category == "map_system") else "detail"
    default_is_leaf = False if (collection.category == "map_system") else True
    default_path = f"{collection.name}/{data.name}"

    item = SettingItem(
        collection_id=collection_id,
        name=data.name,
        code=data.code,
        level=data.level,
        tags=json.dumps(data.tags) if data.tags is not None else None,
        content=data.content,
        relations=json.dumps(data.relations) if data.relations is not None else None,
        order=data.order,
        depth=(data.depth if data.depth is not None else default_depth),
        node_type=(data.node_type if data.node_type is not None else default_node_type),
        is_leaf=(data.is_leaf if data.is_leaf is not None else default_is_leaf),
        path=(data.path if data.path is not None else default_path),
        summary=data.summary,
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

    # 若仅更新了 path 未传 depth，则自动根据 path 段数计算 depth
    if ("path" in data_dict) and ("depth" not in data_dict) and item.path:
      try:
        item.depth = max(1, len((item.path or "").split("/")) - 1)
      except Exception:
        pass

    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_schema(item)


@router.get("/setting-items/{item_id}", response_model=SettingItemResponse)
async def get_setting_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个设定项详情（包含快照）"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    return _item_to_schema(item)


@router.post("/setting-items/{item_id}/move")
async def move_setting_item(
    item_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    将设定项移动到目标集合（人工确认用）
    请求体: { "target_collection_id": number }
    """
    target_collection_id = int(payload.get("target_collection_id", 0))
    if target_collection_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target_collection_id")

    # 加载源项与集合
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    source_collection = db.query(SettingCollection).get(item.collection_id)
    if not source_collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source collection not found")

    # 验证目标集合
    target_collection = db.query(SettingCollection).get(target_collection_id)
    if not target_collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target collection not found")

    # 验证项目所有权一致
    _ensure_project_owned(source_collection.project_id, current_user, db)
    _ensure_project_owned(target_collection.project_id, current_user, db)
    if source_collection.project_id != target_collection.project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cross-project move is not allowed")

    # 执行移动
    item.collection_id = target_collection_id
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

@router.post("/setting-collections/{collection_id}/items/bulk-move")
async def bulk_move_setting_items(
    collection_id: int,
    payload: BulkMoveItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量移动设定项：可跨集合、可修改父路径；自动重算 depth"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    target_collection = None
    if payload.target_collection_id:
        target_collection = db.query(SettingCollection).get(int(payload.target_collection_id))
        if not target_collection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target collection not found")
        _ensure_project_owned(target_collection.project_id, current_user, db)
        if target_collection.project_id != collection.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cross-project move is not allowed")

    items = db.query(SettingItem).filter(SettingItem.id.in_(payload.item_ids)).all()

    moved_ids: List[int] = []
    for it in items:
        # 若未指定目标集合，仅允许操作当前集合内项
        if (not target_collection) and (it.collection_id != collection_id):
            continue

        # 变更集合与根路径段
        if target_collection:
            it.collection_id = target_collection.id
            segs = (it.path or f"{collection.name}/{it.name}").split("/")
            segs[0] = target_collection.name
            it.path = "/".join(segs)

        # 设定新的父路径
        if payload.new_parent_path:
            base = (target_collection.name if target_collection else collection.name)
            parent_path = payload.new_parent_path
            if not parent_path.startswith(base + "/"):
                parent_path = f"{base}/{parent_path}"
            it.path = f"{parent_path}/{it.name}"

        # 重算 depth
        try:
            it.depth = max(1, len((it.path or "").split("/")) - 1)
        except Exception:
            pass

        db.add(it)
        moved_ids.append(it.id)

    db.commit()
    return {"moved_count": len(moved_ids), "moved_ids": moved_ids}

@router.post("/setting-items/{item_id}/set-parent", response_model=SettingItemResponse)
async def set_parent_for_item(
    item_id: int,
    payload: SetParentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """为单个设定项设置父路径，并重算 depth"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    parent_path = payload.new_parent_path
    base = collection.name
    if not parent_path.startswith(base + "/"):
        parent_path = f"{base}/{parent_path}"

    item.path = f"{parent_path}/{item.name}"
    try:
        item.depth = max(1, len((item.path or "").split("/")) - 1)
    except Exception:
        pass

    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_schema(item)

@router.patch(
    "/setting-collections/{collection_id}/items/reorder-under-parent",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reorder_under_parent(
    collection_id: int,
    payload: ReorderUnderParentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在指定父路径下重排直接子节点顺序"""
    collection = db.query(SettingCollection).get(collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(collection.project_id, current_user, db)

    base = collection.name
    parent_path = payload.parent_path
    if not parent_path.startswith(base + "/"):
        parent_path = f"{base}/{parent_path}"

    # 直接子节点：path 以 parent_path/ 开头，且 depth = parent_depth + 1
    parent_depth = max(1, len(parent_path.split("/")) - 1)
    children = (
        db.query(SettingItem)
        .filter(
            SettingItem.collection_id == collection_id,
            SettingItem.path.like(f"{parent_path}/%"),
            SettingItem.depth == parent_depth + 1,
        )
        .all()
    )

    id_to_index = {iid: idx for idx, iid in enumerate(payload.ordered_ids)}
    for child in children:
        if child.id in id_to_index:
            child.order = id_to_index[child.id]
            db.add(child)

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
            max_depth=collection_data.get("max_depth") or (
                4 if collection_data.get("category") == "map_system" else 2
            ),
            hierarchy_config=collection_data.get("hierarchy_config") or get_hierarchy_config_json(collection_data.get("category") or ""),
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
                depth=2,
                node_type=("category" if (collection.category == "map_system") else "detail"),
                is_leaf=(False if (collection.category == "map_system") else True),
                path=f"{collection.name}/{item_data.get('name','')}" or None,
                summary=None,
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


@router.post("/projects/{project_id}/auto-merge-settings")
async def auto_merge_high_confidence_settings(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    自动合并高置信度的候选设定项到正式集合
    
    请求体: {
        "chapter_plan": str,  # 章节规划内容
        "chapter_content": str  # 章节正文内容
    }
    """
    from fastapi import Body
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 获取候选集合
    candidate_collection = (
        db.query(SettingCollection)
        .filter(
            SettingCollection.project_id == project_id,
            SettingCollection.category == "candidate",
        )
        .first()
    )
    
    if not candidate_collection:
        return {
            "success": False,
            "message": "未找到候选集合",
            "merged_count": 0,
        }
    
    # 执行自动合并（这里使用空字符串，实际应从章节生成流程传入）
    result = SettingAutoMergeService.auto_merge_high_confidence_items(
        db=db,
        project_id=project_id,
        candidate_collection_id=candidate_collection.id,
        chapter_plan="",  # 应从请求体获取
        chapter_content="",  # 应从请求体获取
    )
    
    return {
        "success": True,
        "merged_count": result["merged_count"],
        "skipped_count": result["skipped_count"],
        "details": result["details"],
    }


@router.get("/projects/{project_id}/detect-conflicts")
async def detect_setting_conflicts(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检测设定一致性冲突"""
    _ensure_project_owned(project_id, current_user, db)
    
    conflicts = SettingConsistencyService.detect_all_conflicts(db, project_id)
    
    return {
        "project_id": project_id,
        "total_conflicts": conflicts["total_count"],
        "duplicate_names": conflicts["duplicate_names"],
        "ability_mismatches": conflicts["ability_mismatches"],
    }


@router.get("/projects/{project_id}/setting-recommendations")
async def get_setting_recommendations(
    project_id: int,
    category: Optional[str] = None,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定推荐列表（基于使用频率和最近引用时间）
    
    Args:
        project_id: 项目ID
        category: 设定类型过滤（可选，如technique_system、artifact_system等）
        limit: 返回数量限制（默认10）
    
    Returns:
        推荐的设定项列表，按综合得分排序
    """
    from datetime import datetime, timedelta
    
    _ensure_project_owned(project_id, current_user, db)
    
    # 查询项目下的所有设定集合
    collections_query = db.query(SettingCollection).filter(
        SettingCollection.project_id == project_id
    )
    
    # 如果指定类型，过滤集合
    if category:
        collections_query = collections_query.filter(SettingCollection.category == category)
    
    collections = collections_query.all()
    collection_ids = [c.id for c in collections]
    
    if not collection_ids:
        return {
            "project_id": project_id,
            "category": category,
            "recommendations": []
        }
    
    # 查询所有设定项（只包含被引用过的）
    items = db.query(SettingItem).filter(
        SettingItem.collection_id.in_(collection_ids),
        SettingItem.usage_count > 0  # 至少被使用过一次
    ).all()
    
    # 计算推荐得分
    now = datetime.now()
    recommendations = []
    
    for item in items:
        # 基础分：使用次数（归一化到0-1）
        max_usage = max([i.usage_count for i in items]) if items else 1
        usage_score = item.usage_count / max_usage if max_usage > 0 else 0
        
        # 时间衰减因子（最近引用的权重更高）
        time_score = 0.5  # 默认值
        if item.last_referenced_at:
            days_ago = (now - item.last_referenced_at).days
            # 30天内的设定得分更高，30天后逐渐衰减
            if days_ago <= 30:
                time_score = 1.0
            elif days_ago <= 90:
                time_score = 0.8
            elif days_ago <= 180:
                time_score = 0.6
            else:
                time_score = 0.3
        
        # 综合得分：使用频率权重60%，时间新鲜度权重40%
        final_score = usage_score * 0.6 + time_score * 0.4
        
        # 获取集合信息
        collection = next((c for c in collections if c.id == item.collection_id), None)
        
        recommendations.append({
            "id": item.id,
            "name": item.name,
            "collection_id": item.collection_id,
            "collection_name": collection.name if collection else "",
            "category": collection.category if collection else "",
            "usage_count": item.usage_count,
            "last_referenced_at": item.last_referenced_at.isoformat() if item.last_referenced_at else None,
            "score": round(final_score, 3),
            "content_preview": (item.content[:100] + "...") if item.content and len(item.content) > 100 else item.content,
            "tags": json.loads(item.tags) if item.tags else None
        })
    
    # 按得分降序排序，取前limit个
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    recommendations = recommendations[:limit]
    
    return {
        "project_id": project_id,
        "category": category,
        "total_items": len(items),
        "recommendations": recommendations
    }


@router.post("/setting-items/{item_id}/rollback")
async def rollback_setting_item(
    item_id: int,
    snapshot_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回滚设定项到指定快照版本"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 解析快照
    try:
        snapshots = json.loads(item.snapshots) if item.snapshots else []
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid snapshots data")
    
    if snapshot_index < 0 or snapshot_index >= len(snapshots):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid snapshot index")
    
    snapshot = snapshots[snapshot_index]
    
    # 保存当前状态为新快照
    SettingAutoMergeService.save_snapshot(item, db)
    
    # 恢复到指定快照
    item.name = snapshot.get("name", item.name)
    item.content = snapshot.get("content", item.content)
    item.tags = snapshot.get("tags", item.tags)
    item.relations = snapshot.get("relations", item.relations)
    item.confidence_score = snapshot.get("confidence_score")
    
    db.commit()
    db.refresh(item)
    
    return _item_to_schema(item)


@router.get("/setting-items/{item_id}/graph-edges", response_model=List[GraphEdgeResponse])
async def list_graph_edges_for_item(
    item_id: int,
    direction: str = "both",  # both | out | in
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出与指定设定项相关的图谱边"""
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    _ensure_project_owned(collection.project_id, current_user, db)

    q = db.query(KnowledgeGraphEdge)
    if direction == "out":
        q = q.filter(KnowledgeGraphEdge.source_item_id == item_id)
    elif direction == "in":
        q = q.filter(KnowledgeGraphEdge.target_item_id == item_id)
    else:
        q = q.filter((KnowledgeGraphEdge.source_item_id == item_id) | (KnowledgeGraphEdge.target_item_id == item_id))

    edges = q.order_by(KnowledgeGraphEdge.id).all()
    return edges


@router.post("/graph-edges", response_model=GraphEdgeResponse)
async def create_graph_edge(
    payload: GraphEdgeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建知识图谱关系边"""
    source = db.query(SettingItem).get(payload.source_item_id)
    target = db.query(SettingItem).get(payload.target_item_id)
    if not source or not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source or Target item not found")

    src_col = db.query(SettingCollection).get(source.collection_id)
    tgt_col = db.query(SettingCollection).get(target.collection_id)
    if not src_col or not tgt_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    _ensure_project_owned(src_col.project_id, current_user, db)
    _ensure_project_owned(tgt_col.project_id, current_user, db)

    edge = KnowledgeGraphEdge(
        source_item_id=payload.source_item_id,
        target_item_id=payload.target_item_id,
        relation_type=payload.relation_type,
        confidence=payload.confidence,
        auto_extracted=(payload.auto_extracted if payload.auto_extracted is not None else True),
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


@router.delete("/graph-edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_graph_edge(
    edge_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除知识图谱边"""
    edge = db.query(KnowledgeGraphEdge).get(edge_id)
    if not edge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edge not found")

    source = db.query(SettingItem).get(edge.source_item_id)
    src_col = db.query(SettingCollection).get(source.collection_id) if source else None
    if not source or not src_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source item not found")

    _ensure_project_owned(src_col.project_id, current_user, db)

    db.delete(edge)
    db.commit()


# ====================
# Phase 8: 知识图谱高级查询接口
# ====================

@router.get("/setting-items/{item_id}/graph-neighbors")
async def get_graph_neighbors(
    item_id: int,
    direction: str = "both",  # both | out | in
    relation_types: Optional[str] = None,  # 逗号分隔
    min_confidence: float = 0.0,
    max_depth: int = 1,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定项的图谱邻接点（支持多跳查询）
    
    Args:
        item_id: 源节点ID
        direction: 方向（both=双向，out=出边，in=入边）
        relation_types: 关系类型过滤（逗号分隔，例如 "相关,对立"）
        min_confidence: 最小置信度
        max_depth: 最大深度（1=直接邻居，2=二度邻居，...）
    """
    from app.services.knowledge_graph import KnowledgeGraphService
    
    # 验证权限
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 解析关系类型过滤
    relation_types_list = None
    if relation_types:
        relation_types_list = [t.strip() for t in relation_types.split(',') if t.strip()]
    
    result = KnowledgeGraphService.get_neighbors(
        db=db,
        item_id=item_id,
        direction=direction,
        relation_types=relation_types_list,
        min_confidence=min_confidence,
        max_depth=max_depth,
    )
    
    return result


@router.get("/setting-items/{item_id}/graph-summary")
async def get_graph_summary(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取设定项的关系统计摘要
    
    Returns:
        {
            "total_relations": 10,
            "by_type": {"相关": 5, "对立": 2, "同盟": 3},
            "outgoing": 6,
            "incoming": 4
        }
    """
    from app.services.knowledge_graph import KnowledgeGraphService
    
    # 验证权限
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    result = KnowledgeGraphService.get_relation_summary(
        db=db,
        item_id=item_id,
    )
    
    return result


@router.get("/setting-items/{source_id}/shortest-path-to/{target_id}")
async def find_shortest_path(
    source_id: int,
    target_id: int,
    max_depth: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查找两个设定项之间的最短路径
    
    Returns:
        [
            {"node_id": 1, "node_name": "...", "edge_to_next": {"relation_type": "...", "confidence": 0.8}},
            {"node_id": 2, "node_name": "...", "edge_to_next": {...}},
            {"node_id": 3, "node_name": "..."}
        ]
        如果没有路径，返回 null
    """
    from app.services.knowledge_graph import KnowledgeGraphService
    
    # 验证权限
    source = db.query(SettingItem).get(source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source item not found")
    
    target = db.query(SettingItem).get(target_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target item not found")
    
    source_col = db.query(SettingCollection).get(source.collection_id)
    if not source_col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source collection not found")
    
    _ensure_project_owned(source_col.project_id, current_user, db)
    
    path = KnowledgeGraphService.find_shortest_path(
        db=db,
        source_id=source_id,
        target_id=target_id,
        max_depth=max_depth,
    )
    
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No path found between {source_id} and {target_id} within depth {max_depth}"
        )
    
    return path


# ---------------------------------------------------------------------------
# 设定项智能提取API
# ---------------------------------------------------------------------------


class SmartExtractRequest(BaseModel):
    """智能提取请求"""
    item_name: str
    max_excerpts: int = 5
    use_ai_validation: bool = True


class ApplySuggestionsRequest(BaseModel):
    """应用建议请求"""
    new_tags: Optional[List[str]] = None
    append_content: Optional[str] = None


@router.get("/setting-items/{item_id}/smart-extract")
async def smart_extract_setting_content(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 智能提取设定项相关内容
    
    从项目章节中提取与该设定项相关的内容，并推荐标签
    
    Returns:
        {
            "item": {...},
            "related_contents": [...],
            "suggested_tags": [...],
            "collection_category": "technique_system"
        }
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    # 验证设定项存在
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setting item not found"
        )
    
    # 验证权限
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    # 提取相关内容（使用AI验证）
    related_contents = await SettingSmartExtractor.extract_related_content(
        setting_item_name=item.name,
        project_id=collection.project_id,
        db=db,
        max_excerpts=5,
        use_ai_validation=True
    )
    
    # 推荐标签
    suggested_tags = SettingSmartExtractor.suggest_tags(
        item_name=item.name,
        item_content=item.content,
        collection_category=collection.category
    )
    
    # 解析现有标签
    existing_tags = []
    if item.tags:
        try:
            existing_tags = json.loads(item.tags)
        except:
            existing_tags = item.tags.split(',') if item.tags else []
    
    return {
        "item": {
            "id": item.id,
            "name": item.name,
            "content": item.content,
            "tags": existing_tags,
        },
        "related_contents": related_contents,
        "suggested_tags": [t for t in suggested_tags if t not in existing_tags],
        "collection_category": collection.category,
    }


@router.post("/setting-items/{item_id}/smart-extract")
async def smart_extract_by_name(
    item_id: int,
    request: SmartExtractRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 根据名称智能提取内容（用于新建设定项时）
    
    可以在创建设定项之前先搜索相关内容
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    # 获取集合信息
    item = db.query(SettingItem).get(item_id)
    collection = None
    project_id = None
    category = None
    
    if item:
        collection = db.query(SettingCollection).get(item.collection_id)
        if collection:
            _ensure_project_owned(collection.project_id, current_user, db)
            project_id = collection.project_id
            category = collection.category
    
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cannot determine project"
        )
    
    # 提取相关内容
    related_contents = await SettingSmartExtractor.extract_related_content(
        setting_item_name=request.item_name,
        project_id=project_id,
        db=db,
        max_excerpts=request.max_excerpts,
        use_ai_validation=request.use_ai_validation
    )
    
    # 推荐标签
    suggested_tags = SettingSmartExtractor.suggest_tags(
        item_name=request.item_name,
        item_content=None,
        collection_category=category
    )
    
    return {
        "item_name": request.item_name,
        "related_contents": related_contents,
        "suggested_tags": suggested_tags,
        "collection_category": category,
    }


@router.post("/setting-items/{item_id}/apply-suggestions")
async def apply_smart_suggestions(
    item_id: int,
    request: ApplySuggestionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    🆕 应用智能推荐的标签和内容
    
    将推荐的标签添加到设定项，并合并提取的内容
    """
    from app.services.setting_smart_extractor import SettingSmartExtractor
    
    item = db.query(SettingItem).get(item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Setting item not found"
        )
    
    collection = db.query(SettingCollection).get(item.collection_id)
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found"
        )
    
    _ensure_project_owned(collection.project_id, current_user, db)
    
    updated = False
    
    # 应用新标签
    if request.new_tags:
        existing_tags = []
        if item.tags:
            try:
                existing_tags = json.loads(item.tags)
            except:
                existing_tags = item.tags.split(',') if item.tags else []
        
        # 合并标签（去重）
        merged_tags = list(set(existing_tags + request.new_tags))
        item.tags = json.dumps(merged_tags, ensure_ascii=False)
        updated = True
    
    # 追加内容
    if request.append_content:
        if item.content:
            item.content = f"{item.content}\n\n---\n{request.append_content}"
        else:
            item.content = request.append_content
        updated = True
    
    if updated:
        db.commit()
        db.refresh(item)
    
    return {
        "success": True,
        "item": _item_to_schema(item)
    }
