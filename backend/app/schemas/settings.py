"""
设定集合与设定项的Schema定义
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SettingCollectionBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    order: int = 0
    max_depth: Optional[int] = None
    hierarchy_config: Optional[str] = None


class SettingCollectionCreate(SettingCollectionBase):
    pass


class SettingCollectionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None
    max_depth: Optional[int] = None
    hierarchy_config: Optional[str] = None


class SettingCollectionResponse(SettingCollectionBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SettingItemBase(BaseModel):
    name: str
    code: Optional[str] = None
    level: Optional[int] = None
    tags: Optional[List[str]] = None
    content: Optional[str] = None
    relations: Optional[Dict[str, Any]] = None
    order: int = 0
    depth: Optional[int] = 1
    node_type: Optional[str] = None
    is_leaf: Optional[bool] = True
    path: Optional[str] = None
    summary: Optional[str] = None


class SettingItemCreate(SettingItemBase):
    pass


class SettingItemUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    level: Optional[int] = None
    tags: Optional[List[str]] = None
    content: Optional[str] = None
    relations: Optional[Dict[str, Any]] = None
    order: Optional[int] = None
    depth: Optional[int] = None
    node_type: Optional[str] = None
    is_leaf: Optional[bool] = None
    path: Optional[str] = None
    summary: Optional[str] = None


class SettingItemResponse(SettingItemBase):
    id: int
    collection_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    snapshots: Optional[str] = None
    confidence_score: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ItemOrderUpdate(BaseModel):
    id: int
    order: int


class ReorderItemsRequest(BaseModel):
    items: List[ItemOrderUpdate]


class BulkMoveItemsRequest(BaseModel):
    item_ids: List[int]
    target_collection_id: Optional[int] = None
    new_parent_path: Optional[str] = None


class SetParentRequest(BaseModel):
    new_parent_path: str


class ReorderUnderParentRequest(BaseModel):
    parent_path: str
    ordered_ids: List[int]


class GraphEdgeCreate(BaseModel):
    source_item_id: int
    target_item_id: int
    relation_type: str
    confidence: Optional[float] = None
    auto_extracted: Optional[bool] = True


class GraphEdgeResponse(BaseModel):
    id: int
    source_item_id: int
    target_item_id: int
    relation_type: str
    confidence: Optional[float] = None
    auto_extracted: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


