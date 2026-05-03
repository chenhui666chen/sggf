"""TTS语音合成引擎 - 专业版（支持多提供商 + 智能重试）

核心功能：
1. 阿里云CosyVoice v3-plus集成（顶级音质）
2. 备用提供商支持（故障转移）
3. 智能重试机制（指数退避 + 熔断）
4. 智能缓存（降低成本60%）
5. 批量并行处理
6. 成本监控与限额
7. 高级参数控制：语速/音调/停顿/重音
8. 指标埋点（性能监控 + 业务监控）
"""
import asyncio
import hashlib
import logging
import random
import os
from typing import Dict, Any, Optional, List, Callable
import io
from dataclasses import dataclass
from enum import Enum

from ..constants import INSTRUCT_SPEAKER_IDS, normalize_speaker_id
from ..voice_catalog import get_voice_entry

logger = logging.getLogger(__name__)

# cosyvoice-v3-plus Instruct 约束（按官方文档枚举）
COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS = {
    "neutral",
    "fearful",
    "angry",
    "sad",
    "surprised",
    "happy",
    "disgusted",
}
COSYVOICE_V3_PLUS_EMOTION_ALIASES = {
    "excited": "happy",
    "tense": "fearful",
    "calm": "neutral",
    "tender": "neutral",
    "solemn": "sad",
    "nervous": "fearful",
    "focused": "neutral",
    "gentle": "neutral",
    "serious": "neutral",
    "whisper": "neutral",
    "shout": "angry",
}
COSYVOICE_V3_PLUS_INSTRUCT_CHOICES = {
    "longanyang": {
        "scenes": ["闲聊互动", "新闻播报", "广告促销", "比赛解说", "一些儿童内容解说", "语音导航", "脱口秀表演"],
        "roles": ["一个旁白"],
        "identities": ["故事机"],
    },
    "longanhuan": {
        "scenes": ["闲聊对话", "比赛解说", "深夜电台广播", "诗歌朗诵", "科普知识推广", "产品推广", "脱口秀表演"],
        "roles": ["温和客服"],
        "identities": [],
    },
}

# Windows/Linux 常见网络瞬断 errno（用于判定可重试）。
_RETRYABLE_NETWORK_ERRNOS = {10053, 10054, 104, 110, 111}

# Qwen3-TTS Instruct Flash：优先读取新的 deployment 配置，并兼容历史环境变量。
QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID = (
    os.getenv("QWEN3_TTS_INSTRUCT_FLASH_MODEL_ID")
    or os.getenv("QWEN3_TTS_FLASH_MODEL_ID")
    or "qwen3-tts-instruct-flash"
)

# 导入监控模块
try:
    from app.services.monitoring import metrics_collector
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.warning("监控模块未安装，指标收集已禁用")


from app.services.audiobook.tts_engine_pkg._constants import (
    TTSProvider,
    RetryConfig,
    TTSCost,
    MINIMAX_EMOTIONS,
)

class APICallMixin:
    async def _call_tts_api(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用 TTS API（支持多提供商 + 故障转移）

        流程：
        1. 尝试主提供商（带智能重试）
        2. 如果主提供商失败，尝试备用提供商
        3. 所有提供商失败，返回空音频
        """
        # 1. 尝试主提供商
        try:
            audio = await self._call_provider(
                self.primary_provider,
                text,
                voice_params
            )
            if audio and len(audio) > 0:
                return audio
            else:
                logger.warning("主提供商 %s 返回空音频", self.primary_provider.value)
        except Exception as e:
            logger.error("主提供商 %s 失败: %s", self.primary_provider.value, e)

        # 2. 尝试备用提供商
        for fallback_provider in self.fallback_providers:
            logger.warning("尝试备用提供商: %s", fallback_provider.value)

            # 📊 埋点：记录提供商切换
            if METRICS_ENABLED:
                metrics_collector.increment_counter(
                    "tts.provider_switch",
                    labels={
                        "from": self.primary_provider.value,
                        "to": fallback_provider.value
                    }
                )

            try:
                audio = await self._call_provider(
                    fallback_provider,
                    text,
                    voice_params
                )
                if audio and len(audio) > 0:
                    return audio
            except Exception as e:
                logger.error("备用提供商 %s 失败: %s", fallback_provider.value, e)
                continue

        # 所有提供商失败
        logger.error("所有 TTS 提供商均失败")
        return b""

    async def _call_provider(
        self,
        provider: TTSProvider,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用指定提供商（带智能重试）
        """
        if provider == TTSProvider.ALIYUN:
            return await self._call_aliyun_tts_with_retry(text, voice_params)
        elif provider == TTSProvider.MINIMAX:
            return await self._call_minimax_tts_with_retry(text, voice_params)
        # 未来可扩展其他提供商
        # elif provider == TTSProvider.AZURE:
        #     return await self._call_azure_tts_with_retry(text, voice_params)
        else:
            raise ValueError(f"不支持的提供商: {provider}")

    def _is_minimax_model(self) -> bool:
        """判断当前引擎是否为 MiniMax 系列模型"""
        return str(self.model).startswith("minimax-speech") or str(self.model).startswith("MiniMax/")

    def _normalize_emotion_minimax(self, emotion: str) -> str:
        """MiniMax 情感归一化"""
        value = str(emotion or "").strip().lower()
        if not value:
            return "calm"
        # MiniMax 支持的情感
        if value in MINIMAX_EMOTIONS:
            return value
        # 别名映射
        alias_map = {
            "excited": "happy",
            "tense": "fearful",
            "neutral": "calm",
            "scared": "fearful",
        }
        return alias_map.get(value, "calm")

    async def _call_aliyun_tts_with_retry(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用阿里云 TTS（带智能重试）
        """
        for attempt in range(self.retry_config.max_retries):
            try:
                audio = await self._synthesize_aliyun(text, voice_params)
                if audio and len(audio) > 0:
                    validation = self._validate_tts_output(audio, text)
                    self._record_tts_output_validation(validation)
                    if not validation.passed:
                        if attempt < self.retry_config.max_retries - 1:
                            delay = self.retry_config.calculate_delay(attempt)
                            logger.warning(
                                "阿里云 TTS 输出质量未通过，等待 %.1f秒后重试 "
                                "(reason=%s duration=%sms expected=%sms attempt %s/%s)",
                                delay,
                                validation.reason,
                                validation.duration_ms,
                                validation.expected_duration_ms,
                                attempt + 1,
                                self.retry_config.max_retries,
                            )
                            if METRICS_ENABLED:
                                metrics_collector.increment_counter(
                                    "tts.retries",
                                    labels={"provider": "aliyun", "reason": "output_validation"}
                                )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(
                            "阿里云 TTS 输出质量未通过且已耗尽重试: reason=%s duration=%sms expected=%sms",
                            validation.reason,
                            validation.duration_ms,
                            validation.expected_duration_ms,
                        )
                        return b""

                    if attempt > 0:
                        logger.info(
                            "重试成功 (attempt %s/%s)",
                            attempt + 1,
                            self.retry_config.max_retries,
                        )
                        # 📊 埋点：记录重试成功
                        if METRICS_ENABLED:
                            metrics_collector.increment_counter(
                                "tts.retries",
                                labels={"provider": "aliyun", "result": "success"}
                            )
                    return audio
                else:
                    # 空音频，可能是 418 错误
                    if attempt < self.retry_config.max_retries - 1:
                        delay = self.retry_config.calculate_delay(attempt)
                        logger.warning(
                            "返回空音频，等待 %.1f秒后重试 (attempt %s/%s)",
                            delay,
                            attempt + 1,
                            self.retry_config.max_retries,
                        )
                        # 📊 埋点：记录重试次数
                        if METRICS_ENABLED:
                            metrics_collector.increment_counter(
                                "tts.retries",
                                labels={"provider": "aliyun", "reason": "empty_audio"}
                            )
                        await asyncio.sleep(delay)
                        continue
                    return b""
            except Exception as e:
                error_str = str(e)

                # 判断是否为可重试的错误
                errno_value = getattr(e, "errno", None)
                lower = error_str.lower()
                is_retryable = bool(
                    # 配额/限流
                    "Throttling.RateQuota" in error_str
                    or "rate limit" in lower
                    # 常见"服务端/风控/短暂不可用"信号
                    or "418" in error_str
                    or "429" in error_str
                    # 超时 / 断连（英文）
                    or "timeout" in lower
                    or "connection" in lower
                    # 超时 / 断连（中文 Windows 系统信息）
                    or (
                        "连接" in error_str
                        and any(token in error_str for token in ("重置", "中止", "断开", "关闭", "强迫关闭"))
                    )
                    # errno（Windows 10053/10054；Linux 104/110/111）
                    or (errno_value in _RETRYABLE_NETWORK_ERRNOS)
                    # 异常类型兜底
                    or isinstance(e, (TimeoutError, ConnectionError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError))
                )

                if is_retryable and attempt < self.retry_config.max_retries - 1:
                    delay = self.retry_config.calculate_delay(attempt)
                    logger.warning(
                        "%s: %s, 等待 %.1f秒后重试 (attempt %s/%s)",
                        type(e).__name__,
                        error_str[:100],
                        delay,
                        attempt + 1,
                        self.retry_config.max_retries,
                    )
                    # 📊 埋点：记录重试次数
                    if METRICS_ENABLED:
                        metrics_collector.increment_counter(
                            "tts.retries",
                            labels={"provider": "aliyun", "reason": "error"}
                        )
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 不可重试或超过最大重试次数
                    logger.error("阿里云 TTS 失败: %s", e)
                    # 📊 埋点：记录错误
                    if METRICS_ENABLED:
                        metrics_collector.increment_counter(
                            "errors",
                            labels={"category": "tts", "provider": "aliyun"}
                        )
                    raise
