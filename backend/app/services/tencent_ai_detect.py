"""
腾讯云文本内容安全 API - AI 生成检测服务
https://cloud.tencent.com/document/api/1124/51860
"""
import json
import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Optional
import httpx
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class TencentAIDetectService:
    """腾讯云 AI 生成检测服务"""
    
    def __init__(self):
        self.secret_id = getattr(settings, 'TENCENT_SECRET_ID', '')
        self.secret_key = getattr(settings, 'TENCENT_SECRET_KEY', '')
        self.region = getattr(settings, 'TENCENT_REGION', 'ap-guangzhou')
        self.biztype = getattr(settings, 'TENCENT_BIZTYPE', '')
        self.endpoint = "tms.tencentcloudapi.com"
        self.service = "tms"
        self.version = "2020-12-29"
        self.action = "TextModeration"
    
    def _get_sign(self, key: bytes, msg: str) -> bytes:
        """HMAC-SHA256 签名"""
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    
    def _get_authorization(self, timestamp: int, payload: str) -> str:
        """生成腾讯云 API v3 签名"""
        # 步骤1：拼接规范请求串
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        canonical_headers = f"content-type:application/json\nhost:{self.endpoint}\nx-tc-action:{self.action.lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"
        )
        
        # 步骤2：拼接待签名字符串
        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{self.service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"
        
        # 步骤3：计算签名
        secret_date = self._get_sign(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = self._get_sign(secret_date, self.service)
        secret_signing = self._get_sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        
        # 步骤4：拼接 Authorization
        authorization = (
            f"{algorithm} Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return authorization
    
    async def detect_ai_content(self, text: str) -> dict:
        """
        检测文本是否为 AI 生成
        
        Args:
            text: 待检测的文本内容
            
        Returns:
            检测结果字典，包含:
            - success: 是否成功
            - ai_score: AI 生成置信度 (0-100)
            - label: 检测标签
            - suggestion: 处理建议
            - error: 错误信息（如果失败）
        """
        # 检查配置
        if not self.secret_id or not self.secret_key:
            return {
                "success": False,
                "error": "腾讯云 API 密钥未配置。请在 .env 文件中设置 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY",
                "ai_score": None
            }
        
        # 文本转 Base64
        content_base64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        
        # 构建请求体
        payload = {
            "Content": content_base64,
            "Type": "TEXT_AIGC"  # 启用 AI 生成检测
        }
        
        if self.biztype:
            payload["BizType"] = self.biztype
            
        payload_str = json.dumps(payload)
        timestamp = int(time.time())
        
        # 生成签名
        authorization = self._get_authorization(timestamp, payload_str)
        
        # 构建请求头
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Host": self.endpoint,
            "X-TC-Action": self.action,
            "X-TC-Version": self.version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": self.region
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"https://{self.endpoint}",
                    headers=headers,
                    content=payload_str
                )
                
                result = response.json()
                logger.info(f"腾讯云 AI 检测响应: {result}")
                
                if "Response" in result:
                    resp = result["Response"]
                    if "Error" in resp:
                        return {
                            "success": False,
                            "error": f"{resp['Error']['Code']}: {resp['Error']['Message']}",
                            "ai_score": None
                        }
                    
                    return {
                        "success": True,
                        "ai_score": resp.get("Score", 0),
                        "label": resp.get("Label", "Unknown"),
                        "suggestion": resp.get("Suggestion", "Pass"),
                        "keywords": resp.get("Keywords", []),
                        "detail_results": resp.get("DetailResults", []),
                        "raw_response": resp
                    }
                else:
                    return {
                        "success": False,
                        "error": f"无效的响应格式: {result}",
                        "ai_score": None
                    }
                    
        except Exception as e:
            logger.error(f"腾讯云 AI 检测失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "ai_score": None
            }


# 全局服务实例
tencent_ai_detect_service = TencentAIDetectService()

