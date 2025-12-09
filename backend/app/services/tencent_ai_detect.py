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
    
    def _extract_ai_trace_details(self, resp: dict, original_text: str) -> dict:
        """
        从API响应中提取详细的AI痕迹信息

        Args:
            resp: API响应
            original_text: 原始文本

        Returns:
            包含详细AI痕迹信息的字典
        """
        details = {
            "hit_keywords": [],      # 命中的关键词
            "hit_positions": [],     # 命中位置（带上下文）
            "detection_method": "",  # 检测方法
            "label_scores": {},      # 各标签的得分
            "problematic_segments": []  # 问题片段
        }

        # 1. 提取命中的关键词
        keywords = resp.get("Keywords", [])
        if keywords:
            details["hit_keywords"] = keywords

        # 2. 确定检测方法
        hit_type = resp.get("HitType", "")
        if hit_type:
            if "nlp" in hit_type.lower():
                details["detection_method"] = "NLP模型识别"
            elif "keyword" in hit_type.lower():
                details["detection_method"] = "关键词匹配"
            else:
                details["detection_method"] = hit_type

        # 3. 从DetailResults提取每个标签的详细信息
        detail_results = resp.get("DetailResults", [])
        for dr in detail_results:
            label = dr.get("Label", "")
            score = dr.get("Score", 0)
            if label and score > 0:
                details["label_scores"][label] = score

            # 提取HitInfos中的位置信息
            hit_infos = dr.get("HitInfos", [])
            for hit in hit_infos:
                keyword = hit.get("Keyword", "")
                positions = hit.get("Positions", [])

                for pos in positions:
                    start = pos.get("Start", 0)
                    end = pos.get("End", 0)

                    # 提取问题片段及上下文
                    context_start = max(0, start - 20)
                    context_end = min(len(original_text), end + 20)

                    segment = {
                        "keyword": keyword,
                        "position": {"start": start, "end": end},
                        "context": original_text[context_start:context_end],
                        "matched_text": original_text[start:end] if start < len(original_text) else keyword
                    }
                    details["problematic_segments"].append(segment)
                    details["hit_positions"].append({
                        "start": start,
                        "end": end,
                        "keyword": keyword
                    })

        return details

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
            - ai_trace_details: 详细的AI痕迹信息
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

                    # 提取详细的AI痕迹信息
                    ai_trace_details = self._extract_ai_trace_details(resp, text)

                    return {
                        "success": True,
                        "ai_score": resp.get("Score", 0),
                        "label": resp.get("Label", "Unknown"),
                        "sub_label": resp.get("SubLabel", ""),
                        "suggestion": resp.get("Suggestion", "Pass"),
                        "keywords": resp.get("Keywords", []),
                        "detail_results": resp.get("DetailResults", []),
                        "hit_type": resp.get("HitType", ""),  # 审核决策归因
                        "sentiment": resp.get("SentimentAnalysis", {}),
                        # 🆕 新增：提取的AI痕迹细节
                        "ai_trace_details": ai_trace_details,
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

