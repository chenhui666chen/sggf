"""
安全和认证工具
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User

# HTTP Bearer认证
security = HTTPBearer()


def hash_password(password: str) -> str:
    """哈希密码"""
    # 使用 bcrypt 直接处理，避免 passlib 兼容性问题
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> dict:
    """验证JWT token，兼容旧的Base64格式"""
    try:
        print(f"🔐 验证令牌...")
        print(f"   JWT_SECRET: {settings.JWT_SECRET[:20]}...")
        print(f"   JWT_ALGORITHM: {settings.JWT_ALGORITHM}")
        print(f"   Token: {token[:50]}...")

        # 尝试解码标准JWT
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        print(f"✅ 令牌验证成功 (JWT): {payload}")
        return payload
    except JWTError as e:
        # JWT解码失败，尝试Base64旧格式
        print(f"⚠️  JWT解码失败: {e}，尝试Base64格式...")
        try:
            import base64
            decoded = base64.b64decode(token).decode()
            # 旧格式: "user_id:username"
            if ':' in decoded:
                user_id, username = decoded.split(':', 1)
                print(f"✅ 令牌验证成功 (Base64): user_id={user_id}, username={username}")
                return {"sub": user_id, "username": username}
        except Exception as e2:
            print(f"❌ Base64解码也失败: {e2}")
        
        # 两种格式都失败
        print(f"❌ 令牌验证失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """获取当前用户"""
    token = credentials.credentials
    payload = verify_token(token)
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return user


# 🆕 可选的用户验证（用于支持 sendBeacon 等无法携带 Authorization header 的请求）
optional_security = HTTPBearer(auto_error=False)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: Session = Depends(get_db)
) -> User | None:
    """获取当前用户（可选，不强制要求认证）"""
    if credentials is None:
        return None

    try:
        token = credentials.credentials
        payload = verify_token(token)
        user_id = payload.get("sub")

        if user_id is None:
            return None

        user = db.query(User).filter(User.id == int(user_id)).first()
        return user
    except Exception:
        return None

