"""
第三方登录服务
"""
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import create_access_token


class AlipayOAuthService:
    """支付宝OAuth服务"""
    
    def __init__(self, app_id: str, private_key: str, public_key: str):
        self.app_id = app_id
        self.private_key = private_key
        self.public_key = public_key
        self.auth_url = "https://openapi.alipay.com/gateway.do"
    
    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """获取支付宝授权URL"""
        from urllib.parse import urlencode
        
        params = {
            "app_id": self.app_id,
            "scope": "auth_user",
            "redirect_uri": redirect_uri,
            "response_type": "code",
        }
        if state:
            params["state"] = state
        
        return f"https://openauth.alipay.com/oauth2/publicAppAuthorize.htm?{urlencode(params)}"
    
    async def get_access_token(self, code: str) -> Dict[str, Any]:
        """通过授权码获取访问令牌"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.auth_url,
                data={
                    "app_id": self.app_id,
                    "method": "alipay.system.oauth.token",
                    "charset": "utf-8",
                    "sign_type": "RSA2",
                    "timestamp": self._get_timestamp(),
                    "version": "1.0",
                    "grant_type": "authorization_code",
                    "code": code,
                }
            )
            return response.json()
    
    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """获取用户信息"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.auth_url,
                data={
                    "app_id": self.app_id,
                    "method": "alipay.user.info.share",
                    "charset": "utf-8",
                    "sign_type": "RSA2",
                    "timestamp": self._get_timestamp(),
                    "version": "1.0",
                    "auth_token": access_token,
                }
            )
            return response.json()
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class WechatOAuthService:
    """微信OAuth服务"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_url = "https://open.weixin.qq.com/connect/qrconnect"
        self.api_url = "https://api.weixin.qq.com"
    
    def get_auth_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """获取微信授权URL"""
        from urllib.parse import urlencode
        
        params = {
            "appid": self.app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
        }
        if state:
            params["state"] = state
        
        return f"{self.auth_url}?{urlencode(params)}#wechat_redirect"
    
    async def get_access_token(self, code: str) -> Dict[str, Any]:
        """通过授权码获取访问令牌"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/sns/oauth2/access_token",
                params={
                    "appid": self.app_id,
                    "secret": self.app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                }
            )
            return response.json()
    
    async def get_user_info(self, access_token: str, openid: str) -> Dict[str, Any]:
        """获取用户信息"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_url}/sns/userinfo",
                params={
                    "access_token": access_token,
                    "openid": openid,
                }
            )
            return response.json()


class OAuthService:
    """第三方登录服务统一接口"""
    
    @staticmethod
    def handle_alipay_login(db: Session, user_info: Dict[str, Any]) -> Dict[str, Any]:
        """处理支付宝登录"""
        alipay_user_id = user_info.get("user_id")
        if not alipay_user_id:
            raise ValueError("Invalid Alipay user info")
        
        user = db.query(User).filter(User.alipay_openid == alipay_user_id).first()
        
        if not user:
            username = f"alipay_{alipay_user_id[:8]}"
            email = f"{username}@alipay.temp"
            
            user = User(
                username=username,
                email=email,
                password_hash=None,
                full_name=user_info.get("nick_name", username),
                alipay_openid=alipay_user_id,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        access_token = create_access_token(data={"sub": str(user.id)})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "avatar_url": user.avatar_url,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
            }
        }
    
    @staticmethod
    def handle_wechat_login(db: Session, user_info: Dict[str, Any], openid: str, unionid: Optional[str] = None) -> Dict[str, Any]:
        """处理微信登录"""
        user = db.query(User).filter(User.wechat_openid == openid).first()
        
        if not user and unionid:
            user = db.query(User).filter(User.wechat_unionid == unionid).first()
        
        if not user:
            username = f"wechat_{openid[:8]}"
            email = f"{username}@wechat.temp"
            
            user = User(
                username=username,
                email=email,
                password_hash=None,
                full_name=user_info.get("nickname", username),
                avatar_url=user_info.get("headimgurl"),
                wechat_openid=openid,
                wechat_unionid=unionid,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        access_token = create_access_token(data={"sub": str(user.id)})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "avatar_url": user.avatar_url,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
            }
        }