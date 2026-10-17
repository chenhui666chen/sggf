"""
朱雀 AIGC 检测模型 - EdgeOne AI 网关客户端（zhuque-text provider）
https://cloud.tencent.com/document/product/1552/135974

与 TMS 的关键差异：
- 鉴权为 Bearer API Key（无签名），网关域名与 Key 由控制台创建网关后分配
- 响应提供段落级三分类标注（segment_labels：0=人工 1=AI 2=疑似AI），
  是项目黄金对照实验的"正向真值"来源（TMS 已移除，见 2026-08-27 格式复验）
- 2026-08-28 放通后冒烟实测：position 格式为 [start, length]（非 [start, end]）；
  is_merge 只影响段切分粒度，全文分两模式完全一致，故默认非合并单次调用
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

    # 🔧 429 退避参数（2026-10-16 依真实轮次 86cff7f7 取证调整）。
    # 原实现 RATE_LIMIT_BACKOFF_SECONDS=1.0 且**只重试 1 次**，实测 A/B 阶段
    # （20:18:40→20:39，21 分钟）内朱雀 429 告警 23 次。每次限流仅等1 秒就再试，
    # 限流窗口根本没关闭，重试必然再撞 429，最终 success=False。
    # 而检测失败会让该样本 rewritten_ai_ratio 缺失 → 上层判 detect_failed，
    # 即「限流」直接转化为「进化数据缺口」（P5 中 detect_failed 的真实来源）。
    # 改为：多次重试 + 指数退避（上限封顶，避免无界等待）。
    RATE_LIMIT_BACKOFF_SECONDS = 1.0
    RATE_LIMIT_BACKOFF_FACTOR = 2.0
    RATE_LIMIT_MAX_BACKOFF_SECONDS = 8.0
    RATE_LIMIT_MAX_ATTEMPTS = 4          # 首次调用 + 3 次重试

    # 🔧 检测侧独立并发闸门（2026-10-16）。
    # A/B 阶段 4 个候选 × 8 样本 = 32 个检测请求会同时打向朱雀，
    # 而 MODEL_MAX_CONCURRENCY={"step": 4} 只约束改写模型（LLM 网关），
    # 检测走的是另一个网关，此前完全没有闸门，实测触发大量 429。
    # 取 6：既能并行摊薄耗时，又明显低于触发 429 的水位。
    DETECTION_MAX_CONCURRENCY = 6

    def __init__(self):
        self.gateway_url = getattr(settings, "ZHUQUE_GATEWAY_URL", "")
        self.api_key = getattr(settings, "ZHUQUE_API_KEY", "")
        self.is_merge = getattr(settings, "ZHUQUE_IS_MERGE", False)
        # 事件循环内惰性创建信号量：构造期可能早于 loop 建立
        self._detect_semaphore: Optional[asyncio.Semaphore] = None
        # 退避睡眠的可注入点：测试需观测退避时长序列，但直接 patch
        # `asyncio.sleep` 会连测试自身的模拟请求延迟一起吞掉（全局模块属性）。
        self._sleep = asyncio.sleep

    def _get_detect_semaphore(self) -> asyncio.Semaphore:
        """取检测并发闸门（惰性创建，避免跨事件循环复用旧信号量）。"""
        if self._detect_semaphore is None:
            self._detect_semaphore = asyncio.Semaphore(self.DETECTION_MAX_CONCURRENCY)
        return self._detect_semaphore

    @property
    def classify_url(self) -> str:
        return f"{self.gateway_url.rstrip('/')}{self.CLASSIFY_PATH}"

    @staticmethod
    def prepare_text(text: str) -> str:
        """与 TMS 客户端同构的预处理接口；朱雀支持长文本（按千字计费），恒等返回。"""
        return text

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

        # 段落级三分类标注：0=人工 1=AI 2=疑似AI；position 为 [起始下标, 段长]（放通后实测）
        segment_labels = []
        for seg in result.get("segment_labels") or []:
            position = seg.get("position") or [0, 0]
            start = position[0] if len(position) > 0 else 0
            length = position[1] if len(position) > 1 else 0
            segment_labels.append({
                "text": seg.get("text", ""),
                "label": seg.get("label", 0),
                "conf": seg.get("conf", 0.0),
                "order": seg.get("order", 0),
                "start": start,
                "end": start + length,
            })

        # ai_score 对齐项目 0-100 语义：整体疑似 AI 占比（ratio_confidence）× 100
        #
        # ⚠️ 实测口径（2026-10-08 真实网关探索）：ai_score ≈ (labels_ratio["1"] + labels_ratio["2"]) × 100
        #    即 ai_score = 100 − 人工占比。它只在出现「人工」段落时才下降，
        #    完全不区分「确定AI(1)」与「疑似AI(2)」——而 LLM 改写的真实进步正是 AI→疑似，
        #    这段进步 ai_score 恒为 100、毫无分辨力。故三分类占比必须作为一等字段暴露，
        #    优化目标应取 ai_ratio（越低越好），而非 ai_score。
        labels_ratio = result.get("labels_ratio", {}) or {}
        ratio_confidence = float(result.get("ratio_confidence", 0.0))
        return {
            "success": True,
            "provider": self.PROVIDER,
            "ai_score": round(ratio_confidence * 100),
            # 三分类段落占比（0-1）：优化目标取 ai_ratio，human_ratio 为终极目标但 LLM 难达
            "human_ratio": float(labels_ratio.get("0", 0.0)),
            "ai_ratio": float(labels_ratio.get("1", 0.0)),
            "suspect_ratio": float(labels_ratio.get("2", 0.0)),
            "softmax_confidence": result.get("softmax_confidence", 0.0),
            "labels_ratio": labels_ratio,
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

        # 🔧 检测并发闸门：把并发压在阈值内，从源头减少 429。
        # 闸门只包裹请求本身，退避期间不占用（否则限流时会雪上加霜）。
        # 外层 try 覆盖信号量与解析阶段的意外异常；限流已在内层循环单独处理。
        try:
            async with self._get_detect_semaphore():
                backoff = self.RATE_LIMIT_BACKOFF_SECONDS
                last_error: Optional[str] = None
                for attempt in range(1, self.RATE_LIMIT_MAX_ATTEMPTS + 1):
                    try:
                        result = await self._post_json(self.classify_url, headers, payload)
                        return self._parse_response(result, text)
                    except RateLimitedError as e:
                        last_error = str(e)
                        if attempt >= self.RATE_LIMIT_MAX_ATTEMPTS:
                            logger.warning(
                                f"朱雀网关限流重试{attempt - 1} 次后仍失败: {e}"
                            )
                            break
                        logger.warning(
                            f"朱雀网关限流（{e}），{backoff:.1f} 秒后重试"
                            f"（第 {attempt}/{self.RATE_LIMIT_MAX_ATTEMPTS - 1} 次）"
                        )
                        await self._sleep(backoff)
                        # 指数退避：恒定 1 秒穿不过限流窗口
                        backoff = min(
                            backoff * self.RATE_LIMIT_BACKOFF_FACTOR,
                            self.RATE_LIMIT_MAX_BACKOFF_SECONDS,
                        )
                return {
                    "success": False,
                    "error": last_error or "朱雀网关限流",
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
