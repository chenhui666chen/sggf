"""
用户 Schema
"""
from datetime import datetime
from typing import List, Optional
import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.password_policy import validate_password_strength


EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


class RoleSimple(BaseModel):
    """角色简单 Schema"""
    id: int
    code: str
    name: str
    
    model_config = ConfigDict(from_attributes=True)


def normalize_identity(value: str) -> str:
    normalized = value.strip()
    if EMAIL_PATTERN.match(normalized):
        return normalized.lower()
    return normalized


def normalize_optional_phone(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def mask_phone(phone: str) -> str:
    """手机号脱敏：138****1234（通知文案使用，避免全量明文外发）。"""
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


class UserBase(BaseModel):
    """用户基础 Schema

    email 放开非空（P1-3.2）：OAuth 建号确认流程建号时 email=NULL。
    """

    username: str
    email: EmailStr | None = None
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr | None) -> str | None:
        if value is None:
            return None
        return str(value).strip().lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        normalized = normalize_optional_phone(value)
        if normalized is None:
            return None

        if not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")

        return normalized


class UserCreate(UserBase):
    """用户创建 Schema（注册必填邮箱）。"""

    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("用户名不能为空")
        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("用户名长度必须在 2-50 个字符之间")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        # P2-4.6：统一密码策略（≥8 位，含大小写字母和数字），文案与前端本地拦截同源
        validate_password_strength(value)
        return value


class UserUpdate(BaseModel):
    """用户更新 Schema"""

    username: str | None = None
    avatar_url: str | None = None
    phone: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("用户名长度必须在 2-50 个字符之间")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        normalized = normalize_optional_phone(value)
        if normalized is None:
            return None

        if not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")

        return normalized


class UserResponse(UserBase):
    """用户响应 Schema"""

    id: int
    full_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    email_verified: bool = False
    created_at: datetime
    updated_at: datetime
    roles: List[RoleSimple] = []
    # 安全标记（P2-4.2/4.6）：供前端"账户与安全"做设密/改密二态与绑定状态展示。
    # 派生自服务端状态，openid 永不下发（P0-2.1）
    has_password: bool = False
    alipay_bound: bool = False
    wechat_bound: bool = False

    model_config = ConfigDict(from_attributes=True)


def build_user_response(user) -> UserResponse:
    """构造用户响应并补充安全标记（has_password / 第三方绑定状态）。

    openid 以哈希列存在与否判定绑定，不触碰密文，更不下发明文。
    """
    from app.core.security import has_usable_password_hash  # 局部导入：security 依赖本模块，避免环

    response = UserResponse.model_validate(user)
    response.has_password = has_usable_password_hash(getattr(user, "password_hash", None))
    response.alipay_bound = bool(getattr(user, "alipay_openid_hash", None))
    response.wechat_bound = bool(
        getattr(user, "wechat_openid_hash", None) or getattr(user, "wechat_unionid_hash", None)
    )
    return response


class UserLogin(BaseModel):
    """用户登录 Schema"""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized


class PasswordChange(BaseModel):
    """密码修改 Schema"""

    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        # P2-4.6：统一密码策略
        validate_password_strength(value)
        return value


class PasswordResetCodeRequest(BaseModel):
    """找回密码验证码发送请求。"""

    account: str

    @field_validator("account")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized


class PasswordResetConfirm(BaseModel):
    """找回密码确认请求。"""

    account: str
    code: str
    new_password: str

    @field_validator("account")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = normalize_identity(value)
        if not normalized:
            raise ValueError("请输入用户名、邮箱或手机号")

        if PHONE_PATTERN.match(normalized):
            return normalized

        if EMAIL_PATTERN.match(normalized):
            return normalized

        if len(normalized) < 2 or len(normalized) > 50:
            raise ValueError("请输入有效的用户名、邮箱或手机号")

        return normalized

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请输入验证码")
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字验证码")
        return normalized

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        # P2-4.6：统一密码策略
        validate_password_strength(value)
        return value


class PasswordSetRequest(BaseModel):
    """OAuth 用户首次设置本地密码（P2-4.2：不要求旧密码）。"""

    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class PasswordResetCodeResponse(BaseModel):
    """找回密码验证码发送响应。"""

    message: str
    expires_in: int
    resend_in: int


class VerificationCodeResponse(BaseModel):
    """通用验证码发送响应（P1-3.8：注册发码 / 邮箱验证发码）。

    统一 200 响应，不区分邮箱是否已注册（防枚举）。
    """

    message: str
    expires_in: int
    resend_in: int


class RegisterSendCodeRequest(BaseModel):
    """注册发码请求（P1-3.8 两步注册第一步）。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class ConsentAcceptance(BaseModel):
    """用户勾选的同意项（P2-5.2）：同意类型 -> 勾选时看到的条款版本。

    只有前端**显式勾选**的项才传；服务端据此记录真实同意，
    未勾选的项一律不记录、不放行（不得记录用户从未表达的同意）。
    """

    privacy_policy: Optional[str] = None  # 建号必需
    oauth_sync: Optional[str] = None  # OAuth 建号/绑定必需
    phone_collection: Optional[str] = None  # 收集手机号时必需
    age_eligibility: Optional[str] = None  # 建号必需（年满 14 周岁声明，合规修订）


class RegisterConfirmRequest(UserCreate):
    """注册确认请求（P1-3.8 两步注册第二步：验码建号）。"""

    code: str
    # 手机号已被占用时的申诉验证码：验码通过后抢占该号码（原主人清空手机号并收邮件通知）
    phone_code: Optional[str] = None
    # P2-5.2：整体可选，缺失由路由统一转 400「请先勾选…」（比 422 更可读）
    consent: Optional[ConsentAcceptance] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请输入验证码")
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字验证码")
        return normalized

    @field_validator("phone_code")
    @classmethod
    def validate_phone_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字短信验证码")
        return normalized


class PhoneCheckStatusRequest(BaseModel):
    """手机号占用状态查询（注册/绑定前置：判断是否需要申诉验码）。"""

    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = normalize_optional_phone(value)
        if normalized is None or not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")
        return normalized


class PhoneStatusResponse(BaseModel):
    """手机号占用状态响应。"""

    occupied: bool


class PhoneSendCodeRequest(BaseModel):
    """手机号验证码发送请求。

    purpose: takeover=注册时申诉抢占 | bind=用户中心绑定/换绑。
    """

    phone: str
    purpose: str = "bind"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = normalize_optional_phone(value)
        if normalized is None or not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")
        return normalized

    @field_validator("purpose")
    @classmethod
    def validate_purpose(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("takeover", "bind"):
            raise ValueError("purpose 只能为 takeover 或 bind")
        return normalized


class PhoneBindConfirmRequest(BaseModel):
    """用户中心手机号绑定确认（登录态：未占用直绑；被占用时短信验码抢占）。"""

    phone: str
    # 未占用号码直绑时无需验证码；号码被他人占用时必填（申诉抢占）
    code: Optional[str] = None
    consent: Optional[ConsentAcceptance] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = normalize_optional_phone(value)
        if normalized is None or not PHONE_PATTERN.match(normalized):
            raise ValueError("请输入有效的手机号")
        return normalized

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字验证码")
        return normalized


class EmailVerifySendCodeRequest(BaseModel):
    """登录态邮箱验证发码请求（验证/换绑邮箱）。"""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class EmailVerifyConfirmRequest(BaseModel):
    """登录态邮箱验证确认请求。"""

    email: EmailStr
    code: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请输入验证码")
        if not normalized.isdigit() or len(normalized) != 6:
            raise ValueError("请输入 6 位数字验证码")
        return normalized


class OAuthConfirmRequest(BaseModel):
    """OAuth 首次建号确认请求（P1-3.2）。"""

    ticket: str
    action: str = "confirm"
    # P2-5.2：建号需勾选隐私政策 + 第三方资料同步
    consent: Optional[ConsentAcceptance] = None


    @field_validator("ticket")
    @classmethod
    def validate_ticket(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("缺少注册票据")
        return normalized

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("confirm", "cancel"):
            raise ValueError("action 只能为 confirm 或 cancel")
        return normalized


class OAuthConfirmResponse(BaseModel):
    """OAuth 首次建号确认响应（P2-4.5 收尾：令牌仅入 httpOnly cookie）。

    confirm 分支回 user（由 response_model 滤掉一切多余字段，防 token 漏回 body）；
    cancel 分支回 message。两分支字段互斥。
    """

    user: Optional[UserResponse] = None
    message: Optional[str] = None


class TokenResponse(BaseModel):
    """登录/建号响应 Schema（P2-4.5 收尾：access/refresh 仅入 httpOnly cookie，body 不返回）。"""

    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """refresh token 轮换请求（P1-3.7 + P2-4.5）。

    refresh_token 允许为空：httpOnly cookie 承载时前端不持有原始值，
    路由会回退读取 refresh cookie。
    """

    refresh_token: str = ""


class RefreshTokenResponse(BaseModel):
    """refresh token 轮换响应（P2-4.5 收尾：新令牌已入 httpOnly cookie，body 不返回）。"""

    message: str


class LogoutRequest(BaseModel):
    """登出请求（P1-3.7）。

    access_token 可选携带（Bearer 头缺失/过期时兜底吊销 jti）；
    refresh_token 可选携带（吊销 refresh 会话，防止短 access 过期后会话"复活"）。
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class BindConfirmRequest(BaseModel):
    """绑定确认请求（P2-4.2：登录态消费绑定票据）。"""

    bind_ticket: str
    # P2-5.2：绑定第三方需勾选资料同步同意
    consent: Optional[ConsentAcceptance] = None

    @field_validator("bind_ticket")
    @classmethod
    def validate_bind_ticket(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("缺少绑定票据")
        return normalized


class OAuthCallbackResponse(BaseModel):
    """OAuth 回调联合响应（P1-3.2 + P2-4.2）。

    - 已注册用户：status="ok" + token，直接登录。
    - 新用户：status="new_user" + registration_ticket，前端引导建号确认；
      openid 等身份信息不进浏览器，仅由 Redis 票据间接引用。
    - 绑定意图（intent=bind）：status="bind_pending" + bind_ticket，
      由登录态 /auth/bind/confirm 消费后写入当前用户。
    """

    status: str
    registration_ticket: Optional[str] = None
    bind_ticket: Optional[str] = None
    user: Optional[UserResponse] = None
