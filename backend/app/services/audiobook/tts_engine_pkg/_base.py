"""TTS语音合成引擎 - 专业版（支持多提供商 + 智能重试）

核心功能：
1. 阿里云CosyVoice v3.5-plus集成（高表现力，需复刻/设计音色）
2. 备用提供商支持（故障转移）
3. 智能重试机制（指数退避 + 熟熄断路）
4. 智能缓存（降低成本60%）
5. 批量并行处理
6. 成本监控与限额
7. 高级参数控制：语速/音调/停顿/重音
8. 指标埋点（性能监控 + 业务监控）
"""
import asyncio
import base64
import hashlib
import logging
import random
import os
import re
from typing import Dict, Any, Optional, List, Callable
import io
from dataclasses import dataclass
from enum import Enum

from ..tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    get_audiobook_tts_model_price_per_10k,
    normalize_audiobook_tts_model,
)
from ..tts_batch_planner import plan_tts_batches
from ..tts_output_validator import TTSValidationResult, validate_tts_audio
from ..tts_pause import TTSPauseRequested
from ..voice_catalog import get_voice_entry
from ..voice_identity_policy import (
    is_voice_design_creation_request,
    is_voice_design_model,
    sanitize_fixed_voice_performance_text,
    sanitize_fixed_voice_prompt_params,
    sanitize_fixed_voice_ssml_text,
)
from ..voice_parameter_policy import (
    stabilize_fixed_voice_pitch,
    stabilize_instruct_model_speed,
)

logger = logging.getLogger(__name__)

# cosyvoice-v3.5-plus Instruct 约束（按官方文档枚举）
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


_TTS_CACHE_NAMESPACE = "audiobook_tts_audio_v1"
_TTS_CACHE_VALIDATION_VERSION = "tts_output_validator_v1"
_TTS_CACHE_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
_TTS_CACHE_BACKEND = None
_AUDIO_DATA_URL_LOG_REDACT_RE = re.compile(
    r"^data:(?P<mime>[^,;]+(?:;[^,;]+)*);base64,(?P<data>.+)$",
    re.DOTALL,
)


def redact_tts_voice_params_for_log(value: Any) -> Any:
    """Redact large audio data URLs before logging TTS params."""
    if isinstance(value, dict):
        return {key: redact_tts_voice_params_for_log(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_tts_voice_params_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_tts_voice_params_for_log(item) for item in value)
    if isinstance(value, str):
        match = _AUDIO_DATA_URL_LOG_REDACT_RE.match(value.strip())
        if match:
            mime_type = match.group("mime").split(";", 1)[0].strip().lower()
            return f"<audio data URL: {mime_type}, base64 chars={len(match.group('data'))}>"
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name) or "").strip())
    except Exception:
        return default
    return value if value > 0 else default


class _TTSAudioCache:
    def __init__(self, backend):
        self.backend = backend

    async def get(self, identifier: str):
        return await self.backend.get(_TTS_CACHE_NAMESPACE, identifier)

    async def set(self, identifier: str, value: Any, ttl: int) -> bool:
        return await self.backend.set(_TTS_CACHE_NAMESPACE, identifier, value, ttl=ttl)

    async def delete(self, identifier: str) -> bool:
        return await self.backend.delete(_TTS_CACHE_NAMESPACE, identifier)

    async def clear_all(self) -> None:
        await self.backend.clear_all()


def _build_tts_audio_cache() -> Optional[_TTSAudioCache]:
    global _TTS_CACHE_BACKEND
    try:
        from app.services.cache_system import MultiLayerCache

        if _TTS_CACHE_BACKEND is None:
            _TTS_CACHE_BACKEND = MultiLayerCache(
                enable_memory=True,
                enable_redis=_env_bool("AUDIOBOOK_TTS_CACHE_REDIS_ENABLED", False),
                redis_url=os.getenv("AUDIOBOOK_TTS_CACHE_REDIS_URL"),
                memory_max_size=_env_positive_int("AUDIOBOOK_TTS_CACHE_MAX_SIZE", 500),
            )
        return _TTSAudioCache(_TTS_CACHE_BACKEND)
    except Exception as exc:
        logger.warning("TTS缓存初始化失败，已降级为无缓存: %s", exc)
        return None

class TTSEngineBase:
    def __init__(
        self,
        enable_cache: bool = True,
        max_concurrent: int = 2,  # 提升到2个并发（低于3 RPS限制）
        model: str = DEFAULT_AUDIOBOOK_TTS_MODEL,  # 默认 Qwen-Audio 3.1 TTS Flash，兼顾成本与指令控制
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
        self.model = normalize_audiobook_tts_model(model)  # TTS模型版本
        self._last_synthesis_metadata: Dict[str, Any] = {}
        self.output_validation_enabled = str(
            os.getenv("AUDIOBOOK_TTS_OUTPUT_VALIDATION", "1")
        ).strip().lower() not in {"0", "false", "no", "off"}

        catalog_price = get_audiobook_tts_model_price_per_10k(
            self.model,
            default=1.0,
        )
        self.price_per_10k = float(
            catalog_price if catalog_price is not None else 1.0
        )
        
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
        
        # TTS 音频缓存：默认内存缓存，可通过环境变量启用 Redis 二级缓存。
        self.cache = _build_tts_audio_cache() if enable_cache else None
        self.cache_ttl_seconds = _env_positive_int(
            "AUDIOBOOK_TTS_CACHE_TTL_SECONDS",
            _TTS_CACHE_DEFAULT_TTL_SECONDS,
        )
        
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

    def _validate_tts_output(self, audio_bytes: bytes, text: str) -> TTSValidationResult:
        """Validate one provider output before it is cached or mixed."""
        if not self.output_validation_enabled:
            return TTSValidationResult(passed=True, reason="disabled", skipped=True)
        return validate_tts_audio(audio_bytes, text)

    def _record_tts_output_validation(self, result: TTSValidationResult) -> None:
        metadata = self.get_last_synthesis_metadata()
        metadata["output_validation"] = result.to_dict()
        self._set_last_synthesis_metadata(metadata)

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
        self._reset_last_synthesis_metadata()

        # Keep the low-level engine boundary consistent with route/workbench
        # contracts. Direct callers must not be able to reintroduce segment
        # pitch, voice descriptions, stale snapshots, or SSML voice controls.
        voice_design_creation = is_voice_design_creation_request(
            self.model,
            voice_params,
        )
        voice_params = stabilize_instruct_model_speed(voice_params, self.model)
        if not voice_design_creation:
            voice_params, blocked_identity = sanitize_fixed_voice_prompt_params(
                dict(voice_params or {})
            )
            voice_params = stabilize_fixed_voice_pitch(voice_params)
            voice_params.pop("voice_description", None)
            if not is_voice_design_model(self.model):
                voice_params.pop("voice_design_prompt", None)
            voice_params.pop("provider_prompt", None)
            voice_params.pop("provider_prompt_snapshot", None)
            safe_emotion, blocked_emotion = sanitize_fixed_voice_performance_text(emotion)
            emotion = safe_emotion or "neutral"
            if blocked_identity or blocked_emotion:
                logger.warning(
                    "固定音色引擎已过滤身份/音高控制: %s",
                    [*blocked_identity, *blocked_emotion],
                )
            text, blocked_ssml = sanitize_fixed_voice_ssml_text(text)
            if blocked_ssml:
                logger.warning("固定音色引擎已过滤 SSML 身份控制: %s", blocked_ssml)

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
        
        # 调试：输出接收到的 voice_params，避免把录音样本 base64 完整写入日志。
        logger.info("TTS引擎接收参数: %s", redact_tts_voice_params_for_log(voice_params))
        
        # 将 emotion 添加到 voice_params 中，供 _call_aliyun_tts 使用
        voice_params_with_emotion = voice_params.copy()
        
        # 🔥 情感映射：按模型能力矩阵归一化情感，避免服务端报错
        original_emotion = emotion
        emotion = self._normalize_emotion(emotion)
        if original_emotion != emotion:
            logger.info(
                "情感映射: %s -> %s (模型 %s 按能力矩阵归一化)",
                original_emotion,
                emotion,
                self.model,
            )
        
        voice_params_with_emotion["emotion"] = emotion
        
        # 📊 情感参数日志（便于调试和验证）
        speaker = voice_params_with_emotion.get("speaker", "unknown")
        speed = voice_params_with_emotion.get("speed", voice_params_with_emotion.get("rate", 1.0))
        volume = voice_params_with_emotion.get("volume", 50)
        logger.debug(
            f"🎭 [{speaker}] emotion={emotion} | "
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
                try:
                    decoded_audio = self._decode_cached_audio(cached_audio)
                except Exception as decode_err:
                    logger.warning("缓存音频解码失败，删除缓存后重新合成: %s", decode_err)
                    await self.cache.delete(cache_key)
                    decoded_audio = b""
                if not decoded_audio:
                    cached_audio = None
            if cached_audio:
                validation = self._validate_tts_output(decoded_audio, effective_text)
                self._record_tts_output_validation(validation)
                if not validation.passed:
                    logger.warning(
                        "缓存音频未通过质量校验，重新合成: reason=%s duration=%sms expected=%sms",
                        validation.reason,
                        validation.duration_ms,
                        validation.expected_duration_ms,
                    )
                    await self.cache.delete(cache_key)
                else:
                    self.cost_tracker.add_segment(len(effective_text), is_cached=True)
                
                    # 📊 埋点：记录缓存命中
                    if METRICS_ENABLED:
                        metrics_collector.increment_counter("tts.cache.hits")

                    return decoded_audio
        
        # 📊 埋点：记录缓存未命中
        if METRICS_ENABLED:
            metrics_collector.increment_counter("tts.cache.misses")
        
        # 3. 调用TTS API（带并发控制 + 计时）
        try:
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
        except Exception:
            self.cost_tracker.add_failed_segment(len(effective_text))
            raise

        if not audio_bytes:
            self.cost_tracker.add_failed_segment(len(effective_text))
            return b""

        # 4. 更新成本统计
        self.cost_tracker.add_segment(len(effective_text), is_cached=False)

        # 5. 缓存结果
        if self.cache and audio_bytes:
            cached_value = base64.b64encode(audio_bytes).decode('utf-8')
            await self.cache.set(cache_key, cached_value, ttl=self.cache_ttl_seconds)
        
        return audio_bytes

    def _decode_cached_audio(self, cached_audio: Any) -> bytes:
        if isinstance(cached_audio, bytes):
            return cached_audio
        if isinstance(cached_audio, bytearray):
            return bytes(cached_audio)
        if isinstance(cached_audio, str):
            return base64.b64decode(cached_audio.encode("utf-8"))
        raise TypeError(f"unsupported cached audio type: {type(cached_audio).__name__}")

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
        debug_output_dir: Optional[str] = None,  # 调试：保存目录
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        pause_check: Optional[Callable[[], bool]] = None,
    ) -> List[bytes]:
        """
        批量合成（分批处理，避免阿里云配额限制）
        
        Args:
            segments: 片段列表，每个包含 text, voice_params, emotion
            batch_size: 每批处理数量（默认10个）
            batch_interval: 批次间暂停时间（默认0秒，已取消节流）
            pause_check: 可选的暂停检查回调，返回 True 时抛出 TTSPauseRequested
        
        Returns:
            音频列表
        """
        total = len(segments)
        planned_batches = plan_tts_batches(segments, max_items=batch_size)
        logger.debug(f"\n{'='*70}")
        logger.debug(f"[TTS] Starting batch synthesis: {total} segments")
        logger.debug(f"      Batch strategy: {batch_size} per batch, {batch_interval}s interval")
        logger.debug(f"{'='*70}\n")
        logger.info("开始批量TTS合成: %s 个片段", total)
        logger.info("分批策略: %s 批，每批最多%s个，批次间隔%s秒", len(planned_batches), batch_size, batch_interval)
        
        # 分批处理
        audio_list = []
        success_count = 0
        num_batches = len(planned_batches)
        
        for batch_idx, batch_plan in enumerate(planned_batches):
            start_idx = batch_plan.start_index
            end_idx = batch_plan.end_index
            batch_segments = [segments[index] for index in batch_plan.segment_indices]
            
            logger.info(
                "批次 %s/%s: 处理片段 %s-%s",
                batch_idx + 1,
                num_batches,
                start_idx + 1,
                end_idx,
            )
            
            batch_success = 0
            batch_audio_list: List[bytes] = []
            for i, seg in enumerate(batch_segments):
                global_idx = start_idx + i
                # 片段级暂停检查：检测到暂停请求时立即中断，不再继续合成后续片段
                if pause_check is not None:
                    try:
                        paused = pause_check()
                    except Exception as pause_exc:
                        logger.warning("暂停状态检查失败，继续合成: %s", pause_exc)
                        paused = False
                    if paused:
                        logger.info(
                            "⏸️ 检测到暂停请求，停止片段合成（已完成 %s/%s 片段）",
                            len(audio_list),
                            total,
                        )
                        raise TTSPauseRequested(
                            f"pause_requested_before_segment_{global_idx}"
                        )
                error_message = None
                error_type = None
                try:
                    result = await self.synthesize(
                        text=seg["text"],
                        voice_params=seg["voice_params"],
                        emotion=seg.get("emotion", "neutral")
                    )
                except Exception as e:
                    logger.error("片段 %s 异常: %s", global_idx + 1, e)
                    error_message = str(e)
                    error_type = e.__class__.__name__
                    result = Exception(str(e))

                if isinstance(result, Exception):
                    logger.error("片段 %s 失败: %s", global_idx + 1, result)
                    error_message = error_message or str(result)
                    error_type = error_type or result.__class__.__name__
                    audio_bytes = b""
                    audio_list.append(audio_bytes)
                    batch_audio_list.append(audio_bytes)
                elif result and len(result) > 0:
                    audio_bytes = bytes(result)
                    logger.debug("片段 %s 成功: %s字节", global_idx + 1, len(audio_bytes))
                    audio_list.append(audio_bytes)
                    batch_audio_list.append(audio_bytes)
                    batch_success += 1
                    success_count += 1
                else:
                    logger.warning("片段 %s 返回空", global_idx + 1)
                    error_message = "provider_empty_audio"
                    error_type = "EmptyAudio"
                    audio_bytes = b""
                    audio_list.append(audio_bytes)
                    batch_audio_list.append(audio_bytes)

                if progress_callback:
                    try:
                        progress_callback(
                            {
                                "event": "segment",
                                "batch_index": batch_idx,
                                "num_batches": num_batches,
                                "start_idx": start_idx,
                                "end_idx": end_idx,
                                "segment_offset": i,
                                "segment_index": global_idx,
                                "audio_bytes": audio_bytes,
                                "segment_status": "succeeded" if audio_bytes else "failed",
                                "error_message": error_message,
                                "error_type": error_type,
                                "completed_segments": len(audio_list),
                                "total_segments": total,
                                "successful_segments": success_count,
                            }
                        )
                    except Exception as callback_exc:
                        logger.warning("TTS segment progress callback failed: %s", callback_exc)
            
            logger.info(f"   批次完成: {batch_success}/{len(batch_segments)} 成功")

            if progress_callback:
                try:
                    progress_callback(
                        {
                            "event": "batch_completed",
                            "batch_index": batch_idx,
                            "num_batches": num_batches,
                            "start_idx": start_idx,
                            "end_idx": end_idx,
                            "batch_audio_list": batch_audio_list,
                            "completed_segments": len(audio_list),
                            "total_segments": total,
                            "successful_segments": success_count,
                            "batch_successful_segments": batch_success,
                        }
                    )
                except Exception as callback_exc:
                    logger.warning("TTS batch progress callback failed: %s", callback_exc)
            
            # 批次间暂停（除了最后一批）
            if batch_idx < num_batches - 1:
                logger.info("暂停%s秒，避免触发配额限制...", batch_interval)
                await asyncio.sleep(batch_interval)
        
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
