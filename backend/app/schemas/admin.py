"""
管理控制台专用 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_]+$")
    description: Optional[str] = None


class RoleCreate(RoleBase):
    permission_ids: List[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permission_ids: Optional[List[int]] = None


class RoleResponse(RoleBase):
    id: int
    is_active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime
    permissions: List["PermissionResponse"] = []

    class Config:
        from_attributes = True


class PermissionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z_:\*]+$")
    resource: str = Field(..., min_length=1, max_length=50)
    action: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    parent_id: Optional[int] = None


class PermissionResponse(PermissionBase):
    id: int
    created_at: datetime
    children: List["PermissionResponse"] = []

    class Config:
        from_attributes = True


class UserAdminResponse(BaseModel):
    id: int
    username: str
    email: str
    phone: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: List[RoleResponse] = []

    class Config:
        from_attributes = True


class UserListQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    search: Optional[str] = None
    is_active: Optional[bool] = None
    role_code: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None


class UserCreateByAdmin(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)


class UserUpdateByAdmin(BaseModel):
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=20)
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role_ids: Optional[List[int]] = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserRoleUpdate(BaseModel):
    role_ids: List[int]


class AdminOperationLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    operation_type: str
    resource_type: str
    resource_id: Optional[int] = None
    operation_desc: str
    request_method: str
    request_path: str
    response_status: int
    ip_address: str
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminLoginLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    login_type: str
    login_status: str
    ip_address: str
    failure_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class LogQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    user_id: Optional[int] = None
    operation_type: Optional[str] = None
    resource_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class StatsOverview(BaseModel):
    total_users: int
    new_users_today: int
    active_users_30d: int
    total_projects: int
    active_projects: int
    total_audiobook_tasks: int
    admin_operations_today: int


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int


class UserListResponse(PaginatedResponse):
    items: List[UserAdminResponse]


class RoleListResponse(PaginatedResponse):
    items: List[RoleResponse]


class OperationLogListResponse(PaginatedResponse):
    items: List[AdminOperationLogResponse]


class LoginLogListResponse(PaginatedResponse):
    items: List[AdminLoginLogResponse]


RoleResponse.model_rebuild()
PermissionResponse.model_rebuild()
