"""角色与角色功法相关Schema
"""
import json
from datetime import datetime
from typing import Optional, List, Any, Union

from pydantic import BaseModel, field_validator


class CharacterBase(BaseModel):
    """角色基础字段

    与前端交互时，大部分字段都为可选，
    但在创建时会通过 CharacterCreate 约束必填项。
    """

    name: str
    role: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None

    faction: Optional[str] = None
    importance_level: Optional[str] = None
    appearance_status: Optional[str] = None
    life_status: Optional[str] = None

    current_realm_item_id: Optional[int] = None
    first_appearance_chapter: Optional[int] = None

    summary: Optional[str] = None
    profile: Optional[str] = None

    # 为了简单起见，先将 tags / relations 暴露为任意 JSON 结构（在后端以字符串存储）
    tags: Optional[list] = None
    relations: Optional[dict] = None

    @field_validator('tags', mode='before')
    @classmethod
    def parse_tags(cls, v: Any) -> Optional[list]:
        """将数据库中的 JSON 字符串反序列化为列表"""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else None
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @field_validator('relations', mode='before')
    @classmethod
    def parse_relations(cls, v: Any) -> Optional[dict]:
        """将数据库中的 JSON 字符串反序列化为字典"""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                return None
        return None


class CharacterCreate(CharacterBase):
    """创建角色时使用的Schema

    - project_id 由 API 路径参数提供，不在请求体中要求
    - name 在 CharacterBase 中已设为必填
    """

    # 注意：project_id 已从 API 路径参数获取，无需在请求体中重复提供
    pass


class CharacterUpdate(BaseModel):
    """更新角色时使用的Schema

    所有字段均为可选，仅更新传入的字段。
    """

    name: Optional[str] = None
    role: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None

    faction: Optional[str] = None
    importance_level: Optional[str] = None
    appearance_status: Optional[str] = None
    life_status: Optional[str] = None

    current_realm_item_id: Optional[int] = None
    first_appearance_chapter: Optional[int] = None

    summary: Optional[str] = None
    profile: Optional[str] = None

    tags: Optional[list] = None
    relations: Optional[dict] = None


class CharacterResponse(CharacterBase):
    """角色完整响应Schema

    - 会在 API 响应中返回
    - tags / relations 会被转换为 JSON 结构
    """

    id: int
    project_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CharacterTechniqueBase(BaseModel):
    """角色-功法关联基础字段

    注意：这里的 technique_item_id 指向 SettingItem.id
    """

    technique_item_id: int
    proficiency: Optional[str] = None
    learned_at_chapter: Optional[int] = None
    notes: Optional[str] = None


class CharacterTechniqueUpdateList(BaseModel):
    """一次性更新角色全部功法列表时使用

    - 前端可以直接传入一个数组，表示该角色当前完整的功法清单
    - 后端会用这个数组覆盖原有的关联记录
    """

    techniques: List[CharacterTechniqueBase]


class CharacterTechniqueResponse(CharacterTechniqueBase):
    """角色-功法关联响应Schema

    - 除了基础字段外，附带部分功法元数据，方便前端展示
    """

    id: int
    character_id: int

    # 冗余一些功法信息，减少前端二次查询
    technique_name: Optional[str] = None
    technique_code: Optional[str] = None

    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

