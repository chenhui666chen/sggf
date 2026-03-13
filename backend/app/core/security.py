"""
安全和认证工具
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)
UNUSABLE_PASSWORD_PREFIX = "!oauth-disabled!"


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码。"""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def make_unusable_password_hash() -> str:
    """为第三方登录账户生成不可用于本地密码登录的占位哈希。"""
    return UNUSABLE_PASSWORD_PREFIX


def has_usable_password_hash(hashed_password: Optional[str]) -> bool:
    """判断账户是否配置了可用于密码登录的哈希。"""
    return bool(hashed_password) and not hashed_password.startswith(UNUSABLE_PASSWORD_PREFIX)


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """校验密码，兼容第三方账户和异常哈希。"""
    if not has_usable_password_hash(hashed_password):
        return False

    password_bytes = plain_password.encode("utf-8")
    try:
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except ValueError:
        logger.warning("Detected invalid password hash during login attempt")
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT token。"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = (
        now + expires_delta
        if expires_delta
        else now + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_token(token: str) -> dict:
    """验证并解析 JWT。"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


def _validate_user_status(user: Optional[User]) -> User:
    """统一校验用户存在性和可用状态。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前用户。"""
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    return _validate_user_status(user)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: Session = Depends(get_db),
) -> User | None:
    """获取当前用户，可选认证。"""
    if credentials is None:
        return None

    try:
        payload = verify_token(credentials.credentials)
        user_id = payload.get("sub")
        if user_id is None:
            return None

        user = db.query(User).filter(User.id == int(user_id)).first()
        return user if user and user.is_active else None
    except Exception:
        return None
