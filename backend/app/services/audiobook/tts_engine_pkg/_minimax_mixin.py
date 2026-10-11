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
import json
import logging
import random
import os
from typing import Dict, Any, Optional, List, Callable
import io
from dataclasses import dataclass
from enum import Enum

from ..voice_catalog import get_voice_entry
from app.services.audiobook.voice_identity_policy import VOICE_IDENTITY_POLICY_VERSION

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
    MINIMAX_MODEL_ALIASES,
    MINIMAX_EMOTIONS,
)
from ..tts_model_ids import normalize_audiobook_tts_emotion

_TTS_CACHE_VALIDATION_VERSION = "tts_output_validator_v1"

class MinimaxMixin:
    def _apply_interjections(
        self,
        text: str,
        performance_notes: str,
        emotion: str
    ) -> str:
        """将语气词注入文本（MiniMax专用）。
        
        从 performance_notes 中提取安全的语气词标签，例如:
        - "[叹气]"、"[轻笑]"
        - "#laughter#"、"#sigh#"
        """
        if not performance_notes or not performance_notes.strip():
            return text
        
        # 简单实现：如果有性能笔记，在开头添加语气词标签
        # 未来可以根据 performance_notes 的具体内容做更智能的注入
        notes_lower = performance_notes.lower()
        tag = ""
        if "笑" in notes_lower or "laughter" in notes_lower:
            tag = "[轻笑] "
        elif "叹" in notes_lower or "sigh" in notes_lower:
            tag = "[叹气] "
        
        return tag + text if tag else text

    async def _call_minimax_tts_with_retry(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """调用 MiniMax TTS（带智能重试）"""
        for attempt in range(self.retry_config.max_retries):
            try:
                audio = await self._call_minimax_tts(text, voice_params)
                if audio and len(audio) > 0:
                    validation = self._validate_tts_output(audio, text)
                    self._record_tts_output_validation(validation)
                    if not validation.passed:
                        if attempt < self.retry_config.max_retries - 1:
                            delay = self.retry_config.calculate_delay(attempt)
                            logger.warning(
                                "MiniMax TTS 输出质量未通过，等待 %.1f秒后重试 "
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
                                    labels={"provider": "minimax", "reason": "output_validation"}
                                )
                            await asyncio.sleep(delay)
                            continue
                        logger.error(
                            "MiniMax TTS 输出质量未通过且已耗尽重试: reason=%s duration=%sms expected=%sms",
                            validation.reason,
                            validation.duration_ms,
                            validation.expected_duration_ms,
                        )
                        return b""

                    if attempt > 0:
                        logger.info(
                            "MiniMax重试成功 (attempt %s/%s)",
                            attempt + 1,
                            self.retry_config.max_retries,
                        )
                    return audio
                else:
                    if attempt < self.retry_config.max_retries - 1:
                        delay = self.retry_config.calculate_delay(attempt)
                        logger.warning(
                            "MiniMax返回空音频，等待 %.1f秒后重试 (attempt %s/%s)",
                            delay,
                            attempt + 1,
                            self.retry_config.max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue
                    return b""
            except Exception as e:
                error_str = str(e)
                errno_value = getattr(e, "errno", None)
                lower = error_str.lower()
                is_retryable = bool(
                    "Throttling" in error_str
                    or "rate limit" in lower
                    or "429" in error_str
                    or "timeout" in lower
                    or "connection" in lower
                    or (errno_value in _RETRYABLE_NETWORK_ERRNOS)
                    or isinstance(e, (TimeoutError, ConnectionError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError))
                )
                
                if is_retryable and attempt < self.retry_config.max_retries - 1:
                    delay = self.retry_config.calculate_delay(attempt)
                    logger.warning(
                        "MiniMax %s: %s, 等待 %.1f秒后重试 (attempt %s/%s)",
                        type(e).__name__,
                        error_str[:100],
                        delay,
                        attempt + 1,
                        self.retry_config.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error("MiniMax TTS 失败: %s", e)
                    raise
        
        return b""
    
    async def _call_minimax_tts(
        self,
        text: str,
        voice_params: Dict[str, Any]
    ) -> bytes:
        """
        调用 MiniMax Speech 2.8 TTS API（通过阿里云百炼）
        
        支持特性：
        - 7种情感控制
        - 语气词标签
        - 自定义停顿 <#5#>
        - 混合音色
        """
        if not text or not text.strip():
            logger.warning("MiniMax文本为空，跳过TTS")
            return b""
        
        import dashscope
        import os
        
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            logger.error("MiniMax TTS: 未配置 DASHSCOPE_API_KEY")
            return b""
        
        dashscope.api_key = api_key
        
        # 处理文本：清理和准备
        original_text = text
        text = text.strip()
        
        # MiniMax 文本处理（支持语气词标签，不需要特殊清理）
        import unicodedata
        cleaned_text = ''.join(
            char for char in text
            if unicodedata.category(char)[0] not in ['C']
        )
        text = cleaned_text.strip()
        
        if not text:
            logger.warning("MiniMax清理后文本为空")
            return b""
        
        if len(text) > 2000:
            logger.warning("MiniMax文本过长(%s字符)，截断到2000字符", len(text))
            text = text[:2000]
        
        # 模型ID映射
        provider_model = MINIMAX_MODEL_ALIASES.get(self.model, self.model)
        if provider_model != self.model:
            logger.debug("MiniMax模型别名映射: %s -> %s", self.model, provider_model)
        
        # 音色ID
        speaker_id = voice_params.get("speaker", "male-qingnian")
        
        # 情感归一化
        emotion = self._normalize_emotion_minimax(voice_params.get("emotion", "calm"))
        
        logger.info(
            f"MiniMax TTS请求: model={provider_model}, voice={speaker_id}, "
            f"emotion={emotion}, text_len={len(text)}"
        )
        
        # 调用百炼 API（MultiModalConversation 接口）
        loop = asyncio.get_event_loop()
        
        def _sync_call() -> bytes:
            max_retries = 3
            retry_count = 0
            response = None
            
            while retry_count <= max_retries:
                try:
                    # MiniMax 通过百炼使用 MultiModalConversation 接口
                    response = dashscope.MultiModalConversation.call(
                        model=provider_model,
                        api_key=api_key,
                        text=text,
                        voice=speaker_id,
                        emotion=emotion,
                        stream=False,
                    )
                    break
                except Exception as exc:
                    error_str = str(exc)
                    if "429" in error_str or "Throttling" in error_str or "RateQuota" in error_str:
                        if retry_count < max_retries:
                            retry_count += 1
                            wait_time = min(5 * (retry_count ** 1.5), 120)
                            logger.warning(
                                "MiniMax rate limit (429), retry %s/%s, waiting %.1fs...",
                                retry_count,
                                max_retries,
                                wait_time,
                            )
                            import time
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(
                                "MiniMax rate limit exceeded after %s retries: %s",
                                max_retries,
                                error_str,
                            )
                            return b""
                    else:
                        logger.error("MiniMax TTS call failed: %s", exc)
                        return b""
            
            if not response:
                logger.error("MiniMax no response after retries")
                return b""
            
            status_code = getattr(response, "status_code", None)
            if status_code is not None and int(status_code) != 200:
                code = getattr(response, "code", None)
                message = getattr(response, "message", None)
                raise RuntimeError(
                    f"MiniMax TTS failed: status_code={status_code} code={code} message={message}"
                )
            
            # 提取音频
            audio_bytes = self._extract_audio_from_response(response)
            if audio_bytes:
                logger.debug("MiniMax TTS成功: %s字符 -> %s字节", len(text), len(audio_bytes))
                return audio_bytes
            
            logger.error("MiniMax 响应中未找到音频")
            return b""
        
        return await loop.run_in_executor(None, _sync_call)
    
    def _extract_audio_from_response(self, response) -> Optional[bytes]:
        """从响应中提取音频字节（兼容多种返回格式）"""
        import base64
        
        # 尝试从 output.audio.data 提取
        output = getattr(response, "output", None)
        if isinstance(output, dict):
            audio_dict = output.get("audio", {})
            if isinstance(audio_dict, dict):
                data_b64 = audio_dict.get("data")
                if data_b64:
                    try:
                        return base64.b64decode(data_b64)
                    except Exception:
                        pass
                
                url = audio_dict.get("url")
                if url:
                    import urllib.request
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "novel-writing-agent"})
                        with urllib.request.urlopen(req, timeout=60) as f:
                            return f.read()
                    except Exception as e:
                        logger.error("MiniMax音频URL下载失败: %s", e)
                        return b""
        
        # 尝试从 choices[0].message.audios[0].data 提取
        try:
            as_dict = response.to_dict()
            if isinstance(as_dict, dict):
                output_dict = as_dict.get("output", {})
                choices = output_dict.get("choices", [])
                if choices:
                    message = choices[0].get("message", {})
                    audios = message.get("audios", [])
                    if audios:
                        first = audios[0]
                        data_b64 = first.get("data")
                        if data_b64:
                            return base64.b64decode(data_b64)
        except Exception:
            pass
        
        return None
    
    def _is_qwen_audio_31_model(self) -> bool:
        """判断当前引擎是否为 Qwen-Audio 3.1 TTS 系列模型（与 Qwen3-TTS 音色不互通）。"""
        return str(self.model).strip().lower().startswith("qwen-audio-3.1-tts")

    def _is_cosyvoice_v3_plus(self) -> bool:
        """判断当前引擎是否为 CosyVoice 模型（兼容 v3-plus/v3.5-plus 别名）。"""
        model = str(self.model).strip().lower()
        return model.startswith("cosyvoice-v3.5-plus") or model.startswith("cosyvoice-v3-plus")

    def _normalize_emotion(self, emotion: str) -> str:
        """按模型能力矩阵归一化情感标签。

        仅当能力矩阵显式声明 supported_emotions（qwen/cosyvoice 的 API 情感枚举）
        时才做映射；stepaudio/mimo/seed 等模型的情感只进入风格指令文本，不是
        服务端枚举，强行降级（如 fearful->tense）会白白损失表现力。
        """
        value = str(emotion or "").strip().lower()
        if not value:
            return "neutral"
        return normalize_audiobook_tts_emotion(value, self.model) or value

    def _is_ssml_text(self, text: str) -> bool:
        return str(text or "").lstrip().lower().startswith("<speak")

    def _supports_ssml(self, speaker_id: str) -> bool:
        from app.services.audiobook.cosyvoice_clone_client import is_cosyvoice_v35_plus_voice_id

        if not self._is_cosyvoice_v3_plus():
            return False
        entry = get_voice_entry(str(speaker_id or ""), "cosyvoice-v3.5-plus")
        if entry is None:
            return is_cosyvoice_v35_plus_voice_id(speaker_id)
        return bool(entry.get("supportsSsml", False))

    def _escape_ssml_text(self, value: str) -> str:
        text = str(value or "")
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _format_break_time(self, seconds: Any) -> str:
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return ""
        if value <= 0:
            return ""
        ms = int(round(value * 1000))
        ms = max(50, min(10000, ms))
        return f"{ms}ms"

    def _should_use_ssml(self, text: str, voice_params: Dict[str, Any]) -> bool:
        if self._is_ssml_text(text):
            return True
        flag = voice_params.get("use_ssml")
        if flag is False:
            return False
        speaker_id = voice_params.get("speaker", "")
        return bool(flag) or self._supports_ssml(speaker_id)

    def _render_ssml_text(self, text: str, voice_params: Dict[str, Any]) -> str:
        if self._is_ssml_text(text):
            return text

        volume = voice_params.get("volume", 50)
        try:
            volume = int(volume)
        except (TypeError, ValueError):
            volume = 50
        volume = max(0, min(100, volume))

        pause_before = self._format_break_time(voice_params.get("pause_before"))
        pause_after = self._format_break_time(voice_params.get("pause_after"))

        parts = []
        if pause_before:
            parts.append(f"<break time=\"{pause_before}\"/>")
        parts.append(self._escape_ssml_text(text))
        if pause_after:
            parts.append(f"<break time=\"{pause_after}\"/>")

        # Fixed audiobook voices use SSML only for delivery controls. Pitch is
        # omitted because it changes the selected voice rather than delivery.
        attrs = ['rate="1.00"', f'volume="{volume}"']
        return f"<speak {' '.join(attrs)}>{''.join(parts)}</speak>"

    def _build_instruction_text(self, voice_params: Dict[str, Any], emotion: str) -> str:
        if not self._is_cosyvoice_v3_plus():
            return f"emotion={emotion}"

        instruct_emotion = (voice_params.get("instruct_emotion") or emotion or "neutral").strip()
        instruct_emotion = self._normalize_emotion(instruct_emotion)
        scene = str(voice_params.get("instruct_scene") or "").strip()
        role = str(voice_params.get("instruct_role") or "").strip()
        identity = str(voice_params.get("instruct_identity") or "").strip()

        speaker_id = str(voice_params.get("speaker") or "").strip()
        choices = COSYVOICE_V3_PLUS_INSTRUCT_CHOICES.get(speaker_id)
        if choices:
            if scene and scene not in choices["scenes"]:
                scene = ""
            if role and role not in choices["roles"]:
                role = ""
            if identity and identity not in choices["identities"]:
                identity = ""

        if role:
            return f"你现在说话的角色是{role}，你说话的情感是{instruct_emotion}。"
        if scene:
            return f"你正在进行{scene}，你说话的情感是{instruct_emotion}。"
        if identity:
            return f"你正在以一个{identity}的身份说话，你说话的情感是{instruct_emotion}。"
        return f"你说话的情感是{instruct_emotion}。"

    def _build_instruct_text(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str
    ) -> str:
        """预处理文本（必要时渲染 SSML）。"""
        if self._should_use_ssml(text, voice_params):
            return self._render_ssml_text(text, voice_params)
        return text

    def _generate_cache_key(
        self,
        text: str,
        voice_params: Dict[str, Any],
        emotion: str
    ) -> str:
        """生成缓存key"""
        # 组合关键参数
        fallback_values = [
            str(getattr(provider, "value", provider))
            for provider in getattr(self, "fallback_providers", []) or []
        ]
        structured_performance = {
            key: voice_params.get(key)
            for key in (
                "delivery_plan",
                "style_tags",
                "inline_audio_tags",
                "style_control_method",
                "style_control_mode",
                "pause_before",
                "pause_after",
                "timeline_pause_after_ms",
                "cadence_profile",
                "cadence_reason",
            )
            if voice_params.get(key) is not None
        }
        key_parts = [
            str(getattr(self, "model", "")),
            str(getattr(getattr(self, "primary_provider", ""), "value", getattr(self, "primary_provider", ""))),
            ",".join(fallback_values),
            _TTS_CACHE_VALIDATION_VERSION,
            str(VOICE_IDENTITY_POLICY_VERSION),
            text,
            str(voice_params.get("speaker", "")),
            str(voice_params.get("rate", voice_params.get("speed", ""))),
            str(voice_params.get("volume", "")),
            emotion,
            str(voice_params.get("language_type", "")),
            str(voice_params.get("instructions", "")),
            str(voice_params.get("performance_notes", "")),
            str(voice_params.get("instruct_emotion", "")),
            str(voice_params.get("instruct_scene", "")),
            str(voice_params.get("instruct_role", "")),
            str(voice_params.get("instruct_identity", "")),
            str(voice_params.get("use_instruct_mode", "")),
            str(voice_params.get("optimize_instructions", "")),
            json.dumps(
                structured_performance,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        ]
        key_string = "|".join(key_parts)
        
        # MD5哈希
        return "tts:" + hashlib.md5(key_string.encode('utf-8')).hexdigest()
    
