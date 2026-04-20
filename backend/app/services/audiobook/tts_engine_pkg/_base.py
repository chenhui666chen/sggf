"""TTS语音合成引擎 - 专业版（支持多提供商 + 智能重试）

核心功能：
1. 阿里云CosyVoice v3-plus集成（顶级音质）
2. 备用提供商支持（故障转移）
3. 智能重试机制（指数退避 + 熟熄断路）
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

# Qwen3-TTS-Flash：stable 与 snapshot 支持的音色集合不同。
# 默认指向 49 音色的快照版（与文档“qwen3-tts-flash-2025-11-27 音色列表”一致）。
QWEN3_TTS_FLASH_MODEL_ID = os.getenv("QWEN3_TTS_FLASH_MODEL_ID", "qwen3-tts-flash-2025-11-27")

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
)

class TTSEngineBase:
    def __init__(
        self,
        enable_cache: bool = True,
        max_concurrent: int = 2,  # 提升到2个并发（低于3 RPS限制）
        model: str = "qwen3-tts-flash",  # 高性价比版本，支持更多预设音色
        request_delay: float = 0.5,  # 优化为0.5秒（2 RPS，安全范围内）
        primary_provider: TTSProvider = TTSProvider.ALIYUN,  # 主提供商
        fallback_providers: Optional[List[TTSProvider]] = None,  # 备用提供商列表
        retry_config: Optional[RetryConfig] = None,  # 重试配置
    ):
        self.primary_provider = primary_provider
        self.fallback_providers = fallback_providers or []
        self.provider = primary_provider.value  # 向后兼容
        
        self.enable_cache = enable_cache
        self.max_concurrent = max_concurrent
        self.model = model  # TTS模型版本
        self._last_synthesis_metadata: Dict[str, Any] = {}

        # 根据模型设置单价：不同模型价格不同
        if "plus" in model:
            self.price_per_10k = 2.0  # ¥2/万字符（cosyvoice-v3-plus）
        elif "minimax" in model and "hd" in model:
            self.price_per_10k = 6.0  # ¥6/万字符（minimax speech-2.8-hd: 600积分/万字符）
        elif "minimax" in model:
            self.price_per_10k = 3.0  # ¥3/万字符（minimax speech-2.8-turbo: 300积分/万字符）
        else:
            self.price_per_10k = 1.0  # ¥1/万字符（默认 flash 模型）
        
        # 重试配置
        self.retry_config = retry_config or RetryConfig(
            max_retries=3,
            base_delay=2.0,  # 基础延迟2秒
            max_delay=30.0,  # 最大延迟30秒
            exponential_base=2.0,
            jitter=True
        )
        
        # 成本统计
        self.cost_tracker = TTSCost(price_per_10k=self.price_per_10k)
        
        # 并发控制（降低到1，避免频率限制）
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # 请求间隔控制（每次请求后等待）
        self.request_delay = request_delay
        
        # 缓存系统
        if enable_cache:
            # 暂时禁用缓存，简化实现
            # from app.services.cache_system import MultiLayerCache
            # self.cache = MultiLayerCache(
            #     enable_memory=True,
            #     enable_redis=True,
            #     memory_max_size=200  # 缓存200个音频片段
            # )
            self.cache = None
            logger.info("缓存功能暂时禁用")
        else:
            self.cache = None
        
        provider_list = [self.primary_provider.value] + [p.value for p in self.fallback_providers]
        logger.info(
            f"TTS引擎初始化: model={model}, cache={enable_cache}, concurrent={max_concurrent}\n"
            f"   提供商: {' -> '.join(provider_list)} (主提供商 -> 备用)"
        )

    def _reset_last_synthesis_metadata(self) -> None:
        """Reset provider metadata captured during the last synthesis call."""
        self._last_synthesis_metadata = {}

    def _set_last_synthesis_metadata(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Store provider metadata for the most recent synthesis call."""
        self._last_synthesis_metadata = dict(metadata or {})

    def get_last_synthesis_metadata(self) -> Dict[str, Any]:
        """Return provider metadata captured during the most recent synthesis call."""
        return dict(self._last_synthesis_metadata or {})

    async def synthesize(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str = "neutral"
    ) -> bytes:
        """
        合成单个文本片段
        
        Args:
            text: 文本内容
            voice_params: 音色参数（来自VoiceProfile）
            emotion: 情感标签
        
        Returns:
            音频字节流（MP3格式）
        """
        # 📊 埋点：记录请求次数
        if METRICS_ENABLED:
            metrics_collector.increment_counter(
                "tts.requests",
                labels={"provider": self.primary_provider.value}
            )
        
        # 预处理文本：保留钩子（当前不向文本注入额外指令）
        effective_text = self._build_instruct_text(text, voice_params, emotion)
        
        # MiniMax 语气词注入（从 performance_notes 提取）
        if self._is_minimax_model():
            performance_notes = voice_params.get("performance_notes", "")
            effective_text = self._apply_interjections(effective_text, performance_notes, emotion)
        
        # 调试：输出接收到的 voice_params
        logger.info("TTS引擎接收参数: %s", voice_params)
        
        # 将 emotion 添加到 voice_params 中，供 _call_aliyun_tts 使用
        voice_params_with_emotion = voice_params.copy()
        
        # 🔥 情感映射：根据模型能力归一化情感，避免服务端报错
        original_emotion = emotion
        emotion = self._normalize_emotion(emotion)
        if original_emotion != emotion:
            logger.warning(
                "情感映射: %s -> %s (阿里云 TTS 不支持 '%s')",
                original_emotion,
                emotion,
                original_emotion,
            )
        
        voice_params_with_emotion["emotion"] = emotion
        
        # 📊 情感参数日志（便于调试和验证）
        speaker = voice_params_with_emotion.get("speaker", "unknown")
        pitch = voice_params_with_emotion.get("pitch", 50)
        speed = voice_params_with_emotion.get("speed", voice_params_with_emotion.get("rate", 1.0))
        volume = voice_params_with_emotion.get("volume", 50)
        logger.debug(
            f"🎭 [{speaker}] emotion={emotion} | "
            f"pitch={pitch} (base+offset) | "
            f"speed={speed:.2f}x | "
            f"volume={volume}"
        )
        
        # 1. 生成缓存key
        cache_key = self._generate_cache_key(effective_text, voice_params_with_emotion, emotion)
        
        # 2. 检查缓存
        if self.cache:
            cached_audio = await self.cache.get(cache_key)
            if cached_audio:
                logger.debug("缓存命中: %s...", effective_text[:20])
                self.cost_tracker.add_segment(len(effective_text), is_cached=True)
                # 缓存的是base64字符串，需要解码
                import base64
                
                # 📊 埋点：记录缓存命中
                if METRICS_ENABLED:
                    metrics_collector.increment_counter("tts.cache.hits")
                
                return base64.b64decode(cached_audio)
        
        # 📊 埋点：记录缓存未命中
        if METRICS_ENABLED:
            metrics_collector.increment_counter("tts.cache.misses")
        
        # 3. 调用TTS API（带并发控制 + 计时）
        async with self.semaphore:
            # 📊 埋点：计时器
            if METRICS_ENABLED:
                with metrics_collector.timer(
                    "tts.synthesis",
                    labels={
                        "provider": self.primary_provider.value,
                        "model": self.model
                    }
                ):
                    audio_bytes = await self._call_tts_api(effective_text, voice_params_with_emotion)
            else:
                audio_bytes = await self._call_tts_api(effective_text, voice_params_with_emotion)
            
            # 每次请求后等待，避免频率限制
            await asyncio.sleep(self.request_delay)
        
        # 4. 更新成本统计
        self.cost_tracker.add_segment(len(effective_text), is_cached=False)
        
        # 5. 缓存结果
        if self.cache and audio_bytes:
            import base64
            cached_value = base64.b64encode(audio_bytes).decode('utf-8')
            await self.cache.set(cache_key, cached_value, ttl=604800)  # 缓存7天
        
        return audio_bytes

    async def synthesize_with_metadata(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str = "neutral",
    ) -> Dict[str, Any]:
        """Synthesize audio and return bytes together with provider metadata."""
        self._reset_last_synthesis_metadata()
        audio_bytes = await self.synthesize(text, voice_params, emotion)
        return {
            "audio_bytes": audio_bytes,
            "format": "wav" if audio_bytes.startswith(b"RIFF") else "mp3",
            **self.get_last_synthesis_metadata(),
        }

    async def synthesize_batch(
        self,
        segments: List[Dict[str, Any]],
        batch_size: int = 10,  # 每批处理数量
        batch_interval: int = 0,  # 批次间隔（秒）- 优化：取消节流等待
        debug_save_segments: bool = False,  # 调试：是否保存每个片段的原始音频
        debug_output_dir: Optional[str] = None  # 调试：保存目录
    ) -> List[bytes]:
        """
        批量合成（分批处理，避免阿里云配额限制）
        
        Args:
            segments: 片段列表，每个包含 text, voice_params, emotion
            batch_size: 每批处理数量（默认10个）
            batch_interval: 批次间暂停时间（默认0秒，已取消节流）
        
        Returns:
            音频列表
        """
        total = len(segments)
        logger.debug(f"\n{'='*70}")
        logger.debug(f"[TTS] Starting batch synthesis: {total} segments")
        logger.debug(f"      Batch strategy: {batch_size} per batch, {batch_interval}s interval")
        logger.debug(f"{'='*70}\n")
        logger.info("开始批量TTS合成: %s 个片段", total)
        logger.info("分批策略: 每批%s个，批次间隔%s秒", batch_size, batch_interval)
        
        # 分批处理
        audio_list = []
        num_batches = (total + batch_size - 1) // batch_size  # 向上取整
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, total)
            batch_segments = segments[start_idx:end_idx]
            
            logger.info(
                "批次 %s/%s: 处理片段 %s-%s",
                batch_idx + 1,
                num_batches,
                start_idx + 1,
                end_idx,
            )
            
            # 串行处理当前批次（避免并发创建WebSocket连接）
            batch_results = []
            for i, seg in enumerate(batch_segments):
                global_idx = start_idx + i
                try:
                    result = await self.synthesize(
                        text=seg["text"],
                        voice_params=seg["voice_params"],
                        emotion=seg.get("emotion", "neutral")
                    )
                    batch_results.append(result)
                except Exception as e:
                    logger.error("片段 %s 异常: %s", global_idx + 1, e)
                    batch_results.append(Exception(str(e)))
            
            # 处理当前批次结果
            batch_success = 0
            for i, result in enumerate(batch_results):
                global_idx = start_idx + i
                if isinstance(result, Exception):
                    logger.error("片段 %s 失败: %s", global_idx + 1, result)
                    audio_list.append(b"")  # 空音频
                elif result and len(result) > 0:
                    logger.debug("片段 %s 成功: %s字节", global_idx + 1, len(result))
                    audio_list.append(result)
                    batch_success += 1
                else:
                    logger.warning("片段 %s 返回空", global_idx + 1)
                    audio_list.append(b"")
            
            logger.info(f"   批次完成: {batch_success}/{len(batch_segments)} 成功")
            
            # 批次间暂停（除了最后一批）
            if batch_idx < num_batches - 1:
                logger.info("暂停%s秒，避免触发配额限制...", batch_interval)
                await asyncio.sleep(batch_interval)
        
        success_count = len([a for a in audio_list if a])
        logger.info("批量合成完成: %s/%s 成功", success_count, total)
        
        # 调试模式：保存每个片段的原始音频和文本
        if debug_save_segments and audio_list:
            from pathlib import Path
            
            if debug_output_dir:
                debug_dir = Path(debug_output_dir)
            else:
                debug_dir = Path("backend/data/tts_debug")
            
            debug_dir.mkdir(parents=True, exist_ok=True)
            logger.info("[调试模式] 保存 TTS 片段到: %s", debug_dir)
            
            for i, (seg, audio_bytes) in enumerate(zip(segments, audio_list), start=1):
                try:
                    # 保存音频
                    audio_file = debug_dir / f"segment_{i:03d}.mp3"
                    if audio_bytes and len(audio_bytes) > 0:
                        audio_file.write_bytes(audio_bytes)
                        
                        # 保存对应文本（方便对照）
                        text_file = debug_dir / f"segment_{i:03d}.txt"
                        seg_text = seg.get("text", "")
                        text_file.write_text(
                            f"片段 {i}\n"
                            f"长度: {len(seg_text)} 字符\n"
                            f"音频大小: {len(audio_bytes)} 字节\n"
                            f"音色: {seg.get('voice_params', {}).get('speaker', 'unknown')}\n"
                            f"情感: {seg.get('emotion', 'neutral')}\n"
                            f"\n文本内容:\n{seg_text}\n",
                            encoding="utf-8"
                        )
                        logger.info("片段 %03d: %s字节 -> %s", i, len(audio_bytes), audio_file.name)
                    else:
                        logger.warning("片段 %03d: 空音频，跳过保存", i)
                except Exception as e:
                    logger.error("保存片段 %03d 失败: %s", i, e)
            
            logger.info("[调试模式] 已保存 %s/%s 个片段", len([a for a in audio_list if a]), total)
        
        return audio_list
