"""
用户数据权利 API Schema（P2-4.3）。

- /user/data/export 导出：只含个人信息清单（5.1），openid 不下发（仅绑定标记）；
- /user/account/delete 注销：软删除 + 冷静期说明；
- /user/profile 修改个人信息：username/full_name/avatar_url/phone；
- /user/consent 查看同意记录（5.2）。
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.user import PHONE_PATTERN, normalize_optional_phone


class UserProfileUpdate(BaseModel):
    """用户中心个人资料更新（4.3 profile PUT）。"""

    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("用户名长度必须在 2-50 个字符之间")
        return normalized

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 50:
            raise ValueError("昵称长度不能超过 50 个字符")
        return normalized or None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        normalized = normalize_optional_phone(value)
        if normalized is None:
            return None
        if not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")
        return normalized


class OAuthBindingInfo(BaseModel):
    """导出中的第三方绑定信息：只给绑定标记，不下发 openid 明文。"""

    provider: str
    bound: bool


class ConsentRecordOut(BaseModel):
    """导出/查看用的同意记录条目。"""

    consent_type: str
    version: str
    content_hash: str
    scope: Dict = {}
    accepted_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("scope", mode="before")
    @classmethod
    def parse_scope(cls, value: object) -> object:
        """库内 scope 为 JSON 文本，ORM 读取时反序列化为 dict。"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value or {}


class DataExportResponse(BaseModel):
    """个人数据导出响应（PIPL 数据可携权，范围见架构 5.1）。"""

    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    email_verified: bool = False
    created_at: datetime
    consent_version: Optional[str] = None
    oauth_bindings: List[OAuthBindingInfo] = []
    consents: List[ConsentRecordOut] = []
    generated_at: datetime


class AccountDeleteResponse(BaseModel):
    """注销响应：软删除已生效，冷静期后数据匿名化。"""

    message: str
    deleted_at: datetime
    cooling_days: int


class ConsentListResponse(BaseModel):
    """用户查看自己的同意记录（5.2 同意可审计）。"""

    items: List[ConsentRecordOut]
