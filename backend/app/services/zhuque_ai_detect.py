"""
朱雀 AIGC 检测模型 - EdgeOne AI 网关客户端（zhuque-text provider）
https://cloud.tencent.com/document/product/1552/135974

与 TMS 的关键差异：
- 鉴权为 Bearer API Key（无签名），网关域名与 Key 由控制台创建网关后分配
- 响应提供段落级三分类标注（segment_labels：0=人工 1=AI 2=疑似AI），
  是项目黄金对照实验的"正向真值"来源（TMS 已证伪，见 2026-08-23 实验）
"""
import json
import asyncio
import hashlib
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimitedError(Exception):
    """网关限流（HTTP 429），调用方应退避重试。"""


class ZhuqueAIDetectService:
    """朱雀 AIGC 检测服务（EdgeOne AI 网关 zhuque-text）"""

    PROVIDER = "zhuque-text"
    CLASSIFY_PATH = "/v1/providers/zhuque-text/classify"
    RATE_LIMIT_BACKOFF_SECONDS = 1.0

    def __init__(self):
        self.gateway_url = getattr(settings, "ZHUQUE_GATEWAY_URL", "")
        self.api_key = getattr(settings, "ZHUQUE_API_KEY", "")
        self.is_merge = getattr(settings, "ZHUQUE_IS_MERGE", True)

    @property
    def classify_url(self) -> str:
        return f"{self.gateway_url.rstrip('/')}{self.CLASSIFY_PATH}"

    @property
    def detection_policy_version(self) -> str:
        """生成可用于检测缓存失效的稳定策略版本（网关切换后旧基线失效）。"""
        contract = f"{self.PROVIDER}:{self.gateway_url}:{self.is_merge}"
        return hashlib.sha256(contract.encode("utf-8")).hexdigest()[:16]

    def _build_payload(self, text: str) -> dict:
        """构建同步检测请求体。"""
        return {"text": text, "is_merge": self.is_merge}

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _parse_response(self, result: dict, text: str) -> dict:
        """将网关原始响应解析为项目统一结果契约。"""
        if not isinstance(result, dict) or result.get("status") != "success":
            msg = result.get("msg") if isinstance(result, dict) else ""
            return {
                "success": False,
                "error": f"朱雀检测失败: {msg or result}",
                "ai_score": None,
                "rate_limited": False,
            }

        # 段落级三分类标注：0=人工 1=AI 2=疑似AI，position 为原文字符起止下标
        segment_labels = []
        for seg in result.get("segment_labels") or []:
            position = seg.get("position") or [0, 0]
            segment_labels.append({
                "text": seg.get("text", ""),
                "label": seg.get("label", 0),
                "conf": seg.get("conf", 0.0),
                "order": seg.get("order", 0),
                "start": position[0] if len(position) > 0 else 0,
                "end": position[1] if len(position) > 1 else 0,
            })

        # ai_score 对齐项目 0-100 语义：整体疑似 AI 占比（ratio_confidence）× 100
        ratio_confidence = float(result.get("ratio_confidence", 0.0))
        return {
            "success": True,
            "provider": self.PROVIDER,
            "ai_score": round(ratio_confidence * 100),
            "softmax_confidence": result.get("softmax_confidence", 0.0),
            "labels_ratio": result.get("labels_ratio", {}),
            "segment_labels": segment_labels,
            "raw_response": result,
        }

    async def _post_json(self, url: str, headers: dict, payload: dict) -> dict:
        """发送请求，返回解析后的 JSON；429 时抛 RateLimitedError。"""
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(url, headers=headers, content=json.dumps(payload))
            if response.status_code == 429:
                raise RateLimitedError(f"朱雀网关限流: HTTP 429")
            response.raise_for_status()
            result = response.json()
            logger.info(f"朱雀 AI 检测响应: {result}")
            return result

    async def detect_ai_content(self, text: str, data_id: Optional[str] = None) -> dict:
        """
        检测文本是否为 AI 生成

        Args:
            text: 待检测的文本内容
            data_id: 预留参数（朱雀网关无此字段，仅保持与 TMS 调用方签名一致）

        Returns:
            检测结果字典，包含:
            - success: 是否成功
            - ai_score: 整体疑似 AI 占比 (0-100)
            - softmax_confidence: 整体 AI 置信度 (0-1)
            - labels_ratio: 人工/AI/疑似AI 三类占比
            - segment_labels: 段落级标注（label 0=人工 1=AI 2=疑似AI，含位置区间）
            - rate_limited: 是否因限流失败
            - error: 错误信息（如果失败）
        """
        if not self.gateway_url or not self.api_key:
            return {
                "success": False,
                "error": "朱雀 API 未配置。请在 .env 文件中设置 ZHUQUE_GATEWAY_URL 和 ZHUQUE_API_KEY",
                "ai_score": None,
                "rate_limited": False,
            }

        payload = self._build_payload(text)
        headers = self._build_headers()

        try:
            try:
                result = await self._post_json(self.classify_url, headers, payload)
            except RateLimitedError:
                logger.warning(f"朱雀网关限流，{self.RATE_LIMIT_BACKOFF_SECONDS} 秒后重试一次")
                await asyncio.sleep(self.RATE_LIMIT_BACKOFF_SECONDS)
                result = await self._post_json(self.classify_url, headers, payload)
            return self._parse_response(result, text)
        except RateLimitedError as e:
            logger.warning(f"朱雀网关限流重试后仍失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "ai_score": None,
                "rate_limited": True,
            }
        except Exception as e:
            import traceback
            error_msg = str(e) or repr(e) or "未知错误"
            logger.error(f"朱雀 AI 检测失败: {error_msg}\n堆栈信息:\n{traceback.format_exc()}")
            return {
                "success": False,
                "error": error_msg,
                "ai_score": None,
                "rate_limited": False,
            }


# 全局服务实例
zhuque_ai_detect_service = ZhuqueAIDetectService()
