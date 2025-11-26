"""
设定集合与设定项的Schema定义
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from pydantic import BaseModel


class SettingCollectionBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    order: int = 0


class SettingCollectionCreate(SettingCollectionBase):
    pass


class SettingCollectionUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None


class SettingCollectionResponse(SettingCollectionBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SettingItemBase(BaseModel):
    name: str
    code: Optional[str] = None
    level: Optional[int] = None
    tags: Optional[List[str]] = None
    content: Optional[str] = None
    relations: Optional[Dict[str, Any]] = None
    order: int = 0


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


class SettingItemResponse(SettingItemBase):
    id: int
    collection_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ItemOrderUpdate(BaseModel):
    id: int
    order: int


class ReorderItemsRequest(BaseModel):
    items: List[ItemOrderUpdate]


