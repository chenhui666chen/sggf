"""
腾讯云文本内容安全 API - AI 生成检测服务
https://cloud.tencent.com/document/api/1124/51860
"""
import json
import asyncio
import base64
import hashlib
import hmac
import re
import time
from datetime import datetime, timezone
from typing import Optional
import httpx
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# DataId 官方约束：仅允许英文字母、数字、_ - @ # 四种特殊符号，长度不超过 64 字符
_DATA_ID_INVALID = re.compile(r"[^A-Za-z0-9_\-@#]")


class TencentAIDetectService:
    """腾讯云 AI 生成检测服务"""
    
    MAX_TEXT_CHARACTERS = 10000
    DATA_ID_MAX_LENGTH = 64
    # 限流错误码：AI 生成识别默认 50 次/秒，超限返回这些错误码，短退避后重试一次
    RATE_LIMIT_ERROR_CODES = ("RequestLimitExceeded", "InternalError.QueryReqLimited")
    RATE_LIMIT_BACKOFF_SECONDS = 1.0

    def __init__(self):
        self.secret_id = getattr(settings, 'TENCENT_SECRET_ID', '')
        self.secret_key = getattr(settings, 'TENCENT_SECRET_KEY', '')
        self.region = getattr(settings, 'TENCENT_REGION', 'ap-guangzhou')
        self.biztype = getattr(settings, 'TENCENT_BIZTYPE', '')
        self.endpoint = "tms.tencentcloudapi.com"
        self.service = "tms"
        self.version = "2020-12-29"
        self.action = "TextModeration"

    @classmethod
    def prepare_text(cls, text: str) -> str:
        """统一应用腾讯云 TMS 的 Unicode 字符数限制。"""
        return text[:cls.MAX_TEXT_CHARACTERS]

    @staticmethod
    def sanitize_data_id(value: str) -> str:
        """按官方约束清洗 DataId：仅保留字母/数字/_-@#，截断到 64 字符。"""
        if not value:
            return ""
        return _DATA_ID_INVALID.sub("", value)[:TencentAIDetectService.DATA_ID_MAX_LENGTH]

    def _build_payload(self, text: str, data_id: Optional[str] = None) -> dict:
        """构建 TEXT_AIGC 检测请求体。"""
        text = self.prepare_text(text)
        content_base64 = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        payload = {
            "Content": content_base64,
            "Type": "TEXT_AIGC",  # 启用 AI 生成检测
            # 显式声明源语种，避免服务端语种探测开销（官方推荐 zh）
            "SourceLanguage": "zh",
        }
        if self.biztype:
            payload["BizType"] = self.biztype
        sanitized = self.sanitize_data_id(data_id) if data_id else ""
        if sanitized:
            payload["DataId"] = sanitized
        return payload

    @property
    def detection_policy_version(self) -> str:
        """生成可用于检测缓存失效的稳定策略版本。"""
        contract = f"{self.service}:{self.version}:{self.action}:TEXT_AIGC:{self.biztype or 'default'}"
        return hashlib.sha256(contract.encode("utf-8")).hexdigest()[:16]
    
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
            "label_libraries": {},   # 各标签命中的词库归因（自定义库/语义模型）
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

        # 3. 从 DetailResults 提取每个标签的详细信息
        detail_results = resp.get("DetailResults", [])
        for dr in detail_results:
            label = dr.get("Label", "")
            score = dr.get("Score", 0)
            if label and score > 0:
                details["label_scores"][label] = score
            if label:
                details["label_libraries"][label] = {
                    "lib_type": dr.get("LibType", 0),
                    "lib_id": dr.get("LibId", ""),
                    "lib_name": dr.get("LibName", ""),
                }
        
            # 提取 HitInfos 中的位置信息（Type 区分关键词命中与语义模型命中）
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
                        "hit_type": hit.get("Type", ""),
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

    def _is_rate_limited(self, result: dict) -> bool:
        """判断响应是否为限流错误（AI 生成识别默认 50 次/秒）。"""
        resp = result.get("Response") or {}
        error = resp.get("Error") or {}
        return error.get("Code") in self.RATE_LIMIT_ERROR_CODES

    def _parse_response(self, result: dict, text: str) -> dict:
        """将 API 原始响应解析为项目统一结果契约。"""
        if "Response" not in result:
            return {
                "success": False,
                "error": f"无效的响应格式: {result}",
                "ai_score": None,
                "rate_limited": False,
            }
        resp = result["Response"]
        if "Error" in resp:
            code = resp["Error"]["Code"]
            return {
                "success": False,
                "error": f"{code}: {resp['Error']['Message']}",
                "ai_score": None,
                "rate_limited": code in self.RATE_LIMIT_ERROR_CODES,
            }

        # 提取详细的AI痕迹信息
        ai_trace_details = self._extract_ai_trace_details(resp, text)

        # HitSnippetInfos：导致命中标签的原文片段与位置（可映射回原文渲染高亮）
        hit_snippets = []
        for snip in resp.get("HitSnippetInfos") or []:
            hit_snippets.append({
                "snippet": snip.get("Snippet", ""),
                "positions": [
                    {"start": p.get("Start", 0), "end": p.get("End", 0)}
                    for p in snip.get("Positions") or []
                ],
            })

        return {
            "success": True,
            "ai_score": resp.get("Score", 0),
            "label": resp.get("Label", "Unknown"),
            "sub_label": resp.get("SubLabel", ""),
            "suggestion": resp.get("Suggestion", "Pass"),
            "keywords": resp.get("Keywords", []),
            "detail_results": resp.get("DetailResults", []),
            "hit_type": resp.get("HitType", ""),  # 审核决策归因（历史字段，保留兼容）
            "sentiment": resp.get("SentimentAnalysis", {}),
            "hit_snippets": hit_snippets,
            # 🆕 新增：提取的AI痕迹细节
            "ai_trace_details": ai_trace_details,
            "raw_response": resp
        }

    async def _post_payload(self, headers: dict, payload_str: str) -> dict:
        """发送已签名请求，返回解析后的 JSON（不含业务层解析）。"""
        # 清除代理配置，避免代理残留导致连接失败
        import os
        for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
            if proxy_var in os.environ:
                del os.environ[proxy_var]

        async with httpx.AsyncClient(
            timeout=30.0,
            trust_env=False  # 不读取环境变量中的代理配置
        ) as client:
            response = await client.post(
                f"https://{self.endpoint}",
                headers=headers,
                content=payload_str
            )

            result = response.json()
            logger.info(f"腾讯云 AI 检测响应: {result}")
            return result

    async def detect_ai_content(self, text: str, data_id: Optional[str] = None) -> dict:
        """
        检测文本是否为 AI 生成

        Args:
            text: 待检测的文本内容
            data_id: 可选，供控制台侧追溯对账的数据标识（自动清洗为合法字符）

        Returns:
            检测结果字典，包含:
            - success: 是否成功
            - ai_score: AI 生成置信度 (0-100)
            - label: 检测标签
            - suggestion: 处理建议
            - hit_snippets: 导致命中的原文片段与位置
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

        prepared = self.prepare_text(text)
        payload_str = json.dumps(self._build_payload(text, data_id))
        timestamp = int(time.time())

        # 生成签名与请求头（重试时复用同一签名，时间戳偏差在官方容忍范围内）
        authorization = self._get_authorization(timestamp, payload_str)
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
            result = await self._post_payload(headers, payload_str)
            if self._is_rate_limited(result):
                logger.warning(f"腾讯云 AI 检测限流，{self.RATE_LIMIT_BACKOFF_SECONDS} 秒后重试一次")
                await asyncio.sleep(self.RATE_LIMIT_BACKOFF_SECONDS)
                result = await self._post_payload(headers, payload_str)
            return self._parse_response(result, prepared)
        except Exception as e:
            import traceback
            error_msg = str(e) or repr(e) or "未知错误"
            stack_trace = traceback.format_exc()
            logger.error(f"腾讯云 AI 检测失败: {error_msg}\n堆栈信息:\n{stack_trace}")
            return {
                "success": False,
                "error": error_msg,
                "ai_score": None,
                "rate_limited": False,
            }


# 全局服务实例
tencent_ai_detect_service = TencentAIDetectService()
