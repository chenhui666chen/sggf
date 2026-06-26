"""阿里云 TTS Mixin - 支持 Qwen 和 MiniMax 模型"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from app.services.audiobook.tts_style_control import (
    build_model_style_control,
    is_doubao_style_control_model,
    is_mimo_style_control_model,
    is_stepaudio_style_control_model,
    prepare_text_for_style_control,
)
from app.services.audiobook.tts_model_ids import (
    MIMO_V25_TTS_MODEL,
    MIMO_V25_TTS_VOICE_CLONE_MODEL,
    MIMO_V25_TTS_VOICE_DESIGN_MODEL,
    SEED_TTS_20_EXPRESSIVE_MODEL,
    STEPAUDIO_25_TTS_MODEL,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.tts_engine_pkg._constants import TTSUserInputError

logger = logging.getLogger(__name__)

QWEN_TTS_MAX_INPUT_CHARS = 600
QWEN_TTS_INPUT_SAFETY_CHARS = 20
STEPAUDIO_TTS_DEFAULT_BASE_URL = "https://api.stepfun.com/v1"
STEPAUDIO_TTS_MAX_INPUT_CHARS = 1000
STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS = 200
STEPAUDIO_TTS_DEFAULT_VOICE = "cixingnansheng"
STEPAUDIO_TTS_RESPONSE_FORMATS = {"mp3", "wav", "flac", "opus", "pcm"}
STEPAUDIO_TTS_SAMPLE_RATES = {8000, 16000, 22050, 24000, 48000}
STEPAUDIO_TTS_STREAM_FORMATS = {"sse", "audio"}
SEED_TTS_DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
SEED_TTS_DEFAULT_RESOURCE_ID = "seed-tts-2.0"
SEED_TTS_DEFAULT_VOICE = "zh_female_vv_uranus_bigtts"
SEED_TTS_RESPONSE_FORMATS = {"mp3", "pcm", "ogg_opus", "wav"}
SEED_TTS_SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}
SEED_TTS_API_KEY_ENV_NAMES = (
    "VOLCENGINE_TTS_API_KEY",
    "DOUBAO_TTS_API_KEY",
    "SEED_TTS_API_KEY",
    "VOLCENGINE_SPEECH_API_KEY",
    "DOUBAO_SPEECH_API_KEY",
)


def _to_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _get_seed_tts_api_key() -> Optional[str]:
    for env_name in SEED_TTS_API_KEY_ENV_NAMES:
        value = str(os.getenv(env_name) or "").strip()
        if value:
            return value
    return None


def _build_seed_tts_additions(
    *,
    context_texts: List[str],
    use_tag_parser: bool = False,
) -> str:
    additions: Dict[str, Any] = {}
    if context_texts:
        additions["context_texts"] = context_texts
    if use_tag_parser:
        additions["use_tag_parser"] = True
    return json.dumps(additions, ensure_ascii=False, separators=(",", ":"))


def _extract_seed_tts_context_texts_from_payload(payload: Dict[str, Any]) -> List[str]:
    raw_additions = payload.get("req_params", {}).get("additions")
    if not raw_additions:
        return []
    if isinstance(raw_additions, str):
        try:
            raw_additions = json.loads(raw_additions)
        except Exception:
            return []
    if not isinstance(raw_additions, dict):
        return []
    context_texts = raw_additions.get("context_texts")
    if isinstance(context_texts, str):
        return [context_texts] if context_texts.strip() else []
    if isinstance(context_texts, list):
        return [str(item).strip() for item in context_texts if str(item or "").strip()]
    return []


def _decode_seed_tts_audio_value(audio_info: Any) -> Optional[bytes]:
    import base64

    if isinstance(audio_info, str) and audio_info:
        if audio_info.startswith(("http://", "https://")):
            return None
        if audio_info.startswith("data:") and "," in audio_info:
            audio_info = audio_info.split(",", 1)[1]
        return base64.b64decode(audio_info)
    return None


def _parse_seed_tts_json_audio_chunks(text: str) -> Optional[bytes]:
    import json

    chunks: List[bytes] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            return None
        if not isinstance(item, dict):
            continue
        audio_chunk = _decode_seed_tts_audio_value(item.get("data") or item.get("audio"))
        if audio_chunk:
            chunks.append(audio_chunk)
    if chunks:
        return b"".join(chunks)
    return None


def _extract_stepaudio_error_message(response) -> str:
    try:
        data = response.json()
    except Exception:
        return str(getattr(response, "text", "") or "").strip()
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message
        message = str(data.get("message") or "").strip()
        if message:
            return message
    return str(getattr(response, "text", "") or "").strip()


def _build_stepaudio_voice_preview_error(response) -> Exception:
    provider_message = _extract_stepaudio_error_message(response)
    if "CER_NOT_PASS" in provider_message:
        return TTSUserInputError(
            "StepAudio Voice Clone reference audio and transcript do not match. "
            "Please set the reference transcript (sample_text) to the exact spoken content in the reference audio. "
            f"Provider detail: {provider_message}",
            code="stepaudio_clone_sample_text_mismatch",
        )
    return Exception(f"StepAudio voice preview API error: {response.status_code} - {provider_message[:200]}")


def _extract_cosyvoice_timestamp_metadata(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    sentence_timestamps: List[Dict[str, Any]] = []
    word_timestamps: List[Dict[str, Any]] = []
    phoneme_timestamps: List[Dict[str, Any]] = []
    seen_signatures = set()

    for event in events:
        if not isinstance(event, dict):
            continue

        output = event.get("payload", {}).get("output", {})
        if not isinstance(output, dict) or str(output.get("type") or "").strip() != "sentence-end":
            continue

        sentence = output.get("sentence")
        if not isinstance(sentence, dict):
            continue

        sentence_index = sentence.get("index")
        original_text = output.get("original_text")
        normalized_words: List[Dict[str, Any]] = []

        for word in sentence.get("words") or []:
            if not isinstance(word, dict):
                continue

            normalized_word = {
                "text": str(word.get("text") or ""),
                "begin_index": int(word.get("begin_index") or 0),
                "end_index": int(word.get("end_index") or 0),
                "begin_time": int(word.get("begin_time") or 0),
                "end_time": int(word.get("end_time") or 0),
            }
            normalized_words.append(normalized_word)
            word_timestamps.append(
                {
                    **normalized_word,
                    "sentence_index": int(sentence_index) if isinstance(sentence_index, int) else None,
                }
            )

            for phoneme in word.get("phonemes") or []:
                if not isinstance(phoneme, dict):
                    continue
                phoneme_timestamps.append(
                    {
                        "phoneme": str(phoneme.get("phoneme") or phoneme.get("text") or ""),
                        "begin_time": int(phoneme.get("begin_time") or 0),
                        "end_time": int(phoneme.get("end_time") or 0),
                        "sentence_index": int(sentence_index) if isinstance(sentence_index, int) else None,
                        "word_text": normalized_word["text"],
                        "word_begin_index": normalized_word["begin_index"],
                        "word_end_index": normalized_word["end_index"],
                    }
                )

        sentence_payload = {
            "index": int(sentence_index) if isinstance(sentence_index, int) else None,
            "type": "sentence-end",
            "original_text": str(original_text or "") or None,
            "words": normalized_words,
        }
        signature = json.dumps(sentence_payload, ensure_ascii=False, sort_keys=True)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        sentence_timestamps.append(sentence_payload)

    return {
        "tts_timestamps": word_timestamps,
        "tts_timestamp_sentences": sentence_timestamps,
        "phoneme_timestamps": phoneme_timestamps,
    }


class AliyunMixin:
    """阿里云 TTS 引擎混入类，支持 Qwen-TTS 和 MiniMax TTS"""

    async def _synthesize_aliyun(
        self,
        text: str,
        voice_params: Dict[str, Any],
        enable_cache: bool = False,
    ) -> Optional[bytes]:
        """阿里云 TTS 综合合成方法 - 自动选择 Qwen 或 MiniMax"""
        import os

        raw_speaker_id = voice_params.get("speaker", "")
        provider_model = self.model

        if not text or not text.strip():
            logger.warning("TTS 文本为空")
            return None

        text = text.strip()
        logger.info(f"准备TTS文本: [{text}] (长度:{len(text)}字)")

        if self._is_seed_tts_model():
            seed_api_key = _get_seed_tts_api_key()
            if not seed_api_key:
                logger.error(
                    "未设置豆包语音合成专用 API Key，请配置 %s；"
                    "VOLCENGINE_API_KEY / DOUBAO_API_KEY 是火山方舟通用 Key，不能用于 Seed-TTS X-Api-Key",
                    " / ".join(SEED_TTS_API_KEY_ENV_NAMES),
                )
                return None
            seed_resource_id = (
                os.getenv("VOLCENGINE_TTS_RESOURCE_ID")
                or os.getenv("DOUBAO_TTS_RESOURCE_ID")
                or SEED_TTS_DEFAULT_RESOURCE_ID
            )
            return await self._synthesize_seed_tts(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=seed_api_key,
                resource_id=seed_resource_id,
                raw_speaker_id=raw_speaker_id,
            )

        if self._is_stepaudio_model():
            step_api_key = os.getenv("STEP_API_KEY") or os.getenv("STEPFUN_API_KEY")
            if not step_api_key:
                logger.error("未设置 STEP_API_KEY 或 STEPFUN_API_KEY 环境变量")
                return None
            return await self._synthesize_stepaudio(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=step_api_key,
                raw_speaker_id=raw_speaker_id,
            )

        if self._is_mimo_model():
            mimo_api_key = os.getenv("MIMO_API_KEY")
            if not mimo_api_key:
                logger.error("未设置 MIMO_API_KEY 环境变量")
                return None
            return await self._synthesize_mimo(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=mimo_api_key,
                raw_speaker_id=raw_speaker_id,
            )

        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")
        if not api_key:
            logger.error("未设置 DASHSCOPE_API_KEY 或 ALIYUN_API_KEY 环境变量")
            return None

        if self._is_minimax_model():
            return await self._synthesize_minimax(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=api_key,
                raw_speaker_id=raw_speaker_id,
            )

        if self._is_qwen_model():
            return await self._synthesize_qwen(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=api_key,
                raw_speaker_id=raw_speaker_id,
            )

        if self._is_cosyvoice_v3_plus():
            return await self._synthesize_cosyvoice_v3_plus(
                text=text,
                voice_params=voice_params,
                provider_model=provider_model,
                api_key=api_key,
                raw_speaker_id=raw_speaker_id,
            )

        logger.error(f"不支持的模型: {self.model}")
        return None

    def _normalize_speaker_id(self, raw_speaker_id: str, model: str) -> str:
        """根据模型标准化语音 ID"""
        if not raw_speaker_id:
            return ""

        if self._is_mimo_model(model):
            return raw_speaker_id

        if self._is_stepaudio_model(model):
            return raw_speaker_id or STEPAUDIO_TTS_DEFAULT_VOICE

        if self._is_seed_tts_model(model):
            return raw_speaker_id or SEED_TTS_DEFAULT_VOICE

        if self._is_qwen_model():
            from app.services.audiobook.constants import normalize_speaker_id
            from app.services.audiobook.voice_manager import VoiceManager

            preset = VoiceManager.PRESET_VOICES.get(raw_speaker_id)
            resolved_speaker = preset["tts_speaker_id"] if preset else raw_speaker_id
            return normalize_speaker_id(resolved_speaker)

        if self._is_minimax_model():
            return raw_speaker_id

        return raw_speaker_id

    def _is_mimo_model(self, model: Optional[str] = None) -> bool:
        """判断是否为 MiMo-V2.5-TTS 系列模型。"""
        return is_mimo_style_control_model(model or self.model)

    def _is_stepaudio_model(self, model: Optional[str] = None) -> bool:
        """Return whether the current model is StepAudio 2.5 TTS."""
        return is_stepaudio_style_control_model(model or self.model)

    def _is_seed_tts_model(self, model: Optional[str] = None) -> bool:
        """Return whether the current model is Doubao Seed-TTS 2.0."""
        return is_doubao_style_control_model(model or self.model)

    async def _synthesize_seed_tts(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        resource_id: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """Doubao Seed-TTS 2.0 synthesis via Volcengine HTTP API."""
        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)
        voice_params["speaker"] = speaker_id

        logger.info(
            "调用豆包 Seed-TTS 2.0: model=%s, voice=%s",
            provider_model,
            speaker_id,
        )
        return await self._call_seed_tts_websocket(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice=speaker_id,
            voice_params=voice_params,
            resource_id=resource_id,
        )

    async def _synthesize_stepaudio(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """StepAudio 2.5 TTS synthesis via StepFun HTTP API."""
        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)
        stepaudio_voice_asset_id = str(voice_params.get("stepaudio_voice_asset_id") or "").strip()
        is_stepaudio_clone_asset = (
            str(raw_speaker_id or "").strip().startswith("stepaudio_clone:")
            or str(speaker_id or "").strip().startswith("stepaudio_clone:")
            or bool(stepaudio_voice_asset_id)
        )
        if is_stepaudio_clone_asset:
            if not speaker_id and stepaudio_voice_asset_id:
                speaker_id = f"stepaudio_clone:{stepaudio_voice_asset_id}"
            voice_params["speaker"] = speaker_id
            stepaudio_voice_file_id = str(voice_params.get("stepaudio_voice_file_id") or "").strip()
            if not stepaudio_voice_file_id:
                raise ValueError("StepAudio clone reference requires file_id for official voice preview")

            logger.info(
                "调用 StepAudio 2.5 voice preview: model=%s, asset=%s, file_id=%s",
                provider_model,
                stepaudio_voice_asset_id or speaker_id,
                stepaudio_voice_file_id,
            )
            return await self._call_stepaudio_voice_preview_http(
                model=provider_model,
                api_key=api_key,
                text=text,
                file_id=stepaudio_voice_file_id,
                sample_text=str(voice_params.get("stepaudio_voice_sample_text") or ""),
                instruction=self._build_stepaudio_instruction_payload(voice_params),
            )

        voice_params["speaker"] = speaker_id

        logger.info(
            "调用 StepAudio 2.5 TTS: model=%s, voice=%s",
            provider_model,
            speaker_id,
        )
        return await self._call_stepaudio_speech_http(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice=speaker_id,
            voice_params=voice_params,
        )

    async def _synthesize_mimo(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """MiMo-V2.5-TTS 合成 - 通过小米 MiMo OpenAI 兼容接口。"""
        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)
        voice_params["speaker"] = speaker_id

        logger.info(
            "调用小米 MiMo TTS: model=%s, voice=%s",
            provider_model,
            speaker_id,
        )
        return await self._call_mimo_chat_completions_http(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice=speaker_id,
            voice_params=voice_params,
        )

    async def _synthesize_minimax(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """MiniMax TTS 合成 - 通过阿里云百炼 API"""
        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)
        voice_params["speaker"] = speaker_id

        minimax_model = self.model
        if not minimax_model.startswith("MiniMax/"):
            if minimax_model.startswith("minimax-speech-"):
                minimax_model = "MiniMax/" + minimax_model.replace("minimax-speech-", "speech-")
            elif minimax_model.startswith("speech-"):
                minimax_model = "MiniMax/" + minimax_model

        logger.info(
            "调用百炼 MiniMax HTTP TTS: model=%s, voice=%s",
            minimax_model,
            speaker_id,
        )
        return await self._call_dashscope_minimax_http(
            model=minimax_model,
            api_key=api_key,
            text=text,
            voice=speaker_id,
            voice_params=voice_params,
        )

    async def _synthesize_qwen(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """Qwen TTS 合成 - 通过阿里云百炼 API"""
        from app.services.audiobook.voice_manager import VoiceManager

        logger.info("调用阿里云 Qwen-TTS")
        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)

        preset = VoiceManager.PRESET_VOICES.get(raw_speaker_id)
        voice_id = preset["tts_speaker_id"] if preset else raw_speaker_id

        voice_params["speaker"] = speaker_id
        logger.info(
            "调用阿里云 Qwen-TTS: model=%s, voice=%s",
            provider_model,
            speaker_id,
        )
        return await self._call_dashscope_qwen_http(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice_id=speaker_id,
            voice_params=voice_params,
        )

    def _is_qwen_instruct_model(self, model: Optional[str] = None) -> bool:
        """判断是否为 Qwen3-TTS Instruct Flash 模型。"""
        return str(model or self.model).strip().lower() == "qwen3-tts-instruct-flash"

    def _build_qwen_language_type(self, voice_params: Dict[str, Any]) -> str:
        """Qwen TTS 默认使用 Auto，以保留多语种能力。"""
        language_type = str(voice_params.get("language_type") or "").strip()
        return language_type or "Auto"

    def _build_qwen_instruction_payload(self, voice_params: Dict[str, Any]) -> Dict[str, Any]:
        """根据结构化字段构建 Qwen Instruct 参数。"""
        if not self._is_qwen_instruct_model():
            return {}

        style_control = build_model_style_control(
            self.model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        if not style_control.provider_fields and not voice_params.get("use_instruct_mode"):
            return {}
        return dict(style_control.provider_fields)

    def _fit_qwen_instruction_payload_to_limit(
        self,
        *,
        text: str,
        instruct_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """将 Qwen Instruct 请求控制在 DashScope 600 字输入限制内。"""
        if not instruct_payload:
            return {}

        instructions = str(instruct_payload.get("instructions") or "").strip()
        if not instructions:
            return {}

        text_length = len(str(text or ""))
        if text_length > QWEN_TTS_MAX_INPUT_CHARS:
            logger.warning(
                "Qwen TTS 正文超过服务商输入限制: text=%s, max=%s",
                text_length,
                QWEN_TTS_MAX_INPUT_CHARS,
            )
            return {}

        instruction_budget = QWEN_TTS_MAX_INPUT_CHARS - QWEN_TTS_INPUT_SAFETY_CHARS - text_length
        if instruction_budget <= 0:
            logger.warning(
                "Qwen TTS 正文已无安全 instructions 预算: text=%s, max=%s",
                text_length,
                QWEN_TTS_MAX_INPUT_CHARS,
            )
            return {}

        if len(instructions) <= instruction_budget:
            return dict(instruct_payload)

        fitted_payload = dict(instruct_payload)
        fitted_payload["instructions"] = instructions[:instruction_budget].strip()
        if not fitted_payload["instructions"]:
            return {}

        logger.warning(
            "Qwen TTS instructions 已截断以满足服务商输入限制: text=%s, instructions=%s->%s, max=%s",
            text_length,
            len(instructions),
            len(fitted_payload["instructions"]),
            QWEN_TTS_MAX_INPUT_CHARS,
        )
        return fitted_payload

    async def _synthesize_cosyvoice_v3_plus(
        self,
        text: str,
        voice_params: Dict[str, Any],
        provider_model: str,
        api_key: str,
        raw_speaker_id: str,
    ) -> Optional[bytes]:
        """CosyVoice v3.5 Plus 合成，走 DashScope WebSocket。"""
        from app.services.audiobook.cosyvoice_clone_client import (
            COSYVOICE_V35_PLUS_MODEL_ID,
            is_cosyvoice_v35_plus_voice_id,
        )
        from app.services.audiobook.voice_catalog import get_voice_entry

        speaker_id = self._normalize_speaker_id(raw_speaker_id, provider_model)
        voice_params["speaker"] = speaker_id

        if self._is_cosyvoice_v35_model(provider_model):
            entry = get_voice_entry(speaker_id, COSYVOICE_V35_PLUS_MODEL_ID)
            if not speaker_id or (entry is None and not is_cosyvoice_v35_plus_voice_id(speaker_id)):
                raise ValueError("cosyvoice-v3.5-plus 仅支持复刻/设计音色，请传入有效 voice_id")

        logger.info(
            "调用百炼 CosyVoice WebSocket TTS: model=%s, voice=%s",
            provider_model,
            speaker_id,
        )
        return await self._call_dashscope_cosyvoice_websocket(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice=speaker_id,
            voice_params=voice_params,
        )

    def _build_cosyvoice_websocket_parameters(
        self,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建 DashScope CosyVoice WebSocket 参数。"""

        def _to_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def _to_int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _normalize_language_hints(raw_value: Any) -> List[str]:
            if isinstance(raw_value, str):
                candidates = [raw_value]
            elif isinstance(raw_value, (list, tuple, set)):
                candidates = list(raw_value)
            else:
                candidates = []
            hints: List[str] = []
            for item in candidates:
                value = str(item or "").strip()
                if value:
                    hints.append(value)
            return hints[:5]

        rate = _to_float(voice_params.get("rate", voice_params.get("speed", 1.0)), 1.0)
        rate = max(0.5, min(2.0, rate))

        pitch = _to_float(voice_params.get("pitch", 1.0), 1.0)
        if pitch > 10:
            pitch = pitch / 50.0
        pitch = max(0.5, min(2.0, pitch))

        volume = _to_int(voice_params.get("volume", 50), 50)
        volume = max(0, min(100, volume))

        sample_rate = _to_int(voice_params.get("sample_rate", 22050), 22050)
        if sample_rate not in {8000, 16000, 22050, 24000, 32000, 44100, 48000}:
            sample_rate = 22050

        audio_format = str(voice_params.get("format", "mp3") or "mp3").strip().lower()
        if audio_format not in {"mp3", "wav", "pcm"}:
            audio_format = "mp3"

        parameters = {
            "text_type": "PlainText",
            "voice": voice,
            "format": audio_format,
            "sample_rate": sample_rate,
            "volume": volume,
            "rate": rate,
            "pitch": pitch,
            "enable_ssml": self._is_ssml_text(text),
        }
        instruction = self._build_cosyvoice_instruction_payload(voice_params)
        if instruction:
            parameters["instruction"] = instruction
        language_hints = _normalize_language_hints(voice_params.get("language_hints"))
        if language_hints:
            parameters["language_hints"] = language_hints
        if _to_bool_flag(voice_params.get("word_timestamp_enabled")):
            parameters["word_timestamp_enabled"] = True
        if _to_bool_flag(voice_params.get("phoneme_timestamp_enabled")):
            parameters["phoneme_timestamp_enabled"] = True
        seed = voice_params.get("seed")
        if seed is not None:
            try:
                parameters["seed"] = int(seed)
            except (TypeError, ValueError):
                pass
        return parameters

    def _build_cosyvoice_run_task_command(
        self,
        *,
        task_id: str,
        model: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "model": model,
                "parameters": parameters,
                "input": {},
            },
        }

    def _build_cosyvoice_continue_task_command(self, *, task_id: str, text: str) -> Dict[str, Any]:
        return {
            "header": {
                "action": "continue-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {"input": {"text": text}},
        }

    def _build_cosyvoice_finish_task_command(self, *, task_id: str) -> Dict[str, Any]:
        return {
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {"input": {}},
        }

    def _is_cosyvoice_v35_model(self, model: Optional[str] = None) -> bool:
        return str(model or self.model).strip().lower().startswith("cosyvoice-v3.5-plus")

    def _truncate_cosyvoice_instruction(self, value: str, max_units: int = 100) -> str:
        result: List[str] = []
        used_units = 0
        for char in str(value or "").strip():
            unit_cost = 2 if ord(char) > 127 else 1
            if used_units + unit_cost > max_units:
                break
            result.append(char)
            used_units += unit_cost
        return "".join(result).strip()

    def _build_cosyvoice_instruction_payload(self, voice_params: Dict[str, Any]) -> str:
        style_control = build_model_style_control(
            self.model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        instruction = str(style_control.provider_fields.get("instructions") or "").strip()
        if not instruction and not voice_params.get("use_instruct_mode"):
            return ""
        return self._truncate_cosyvoice_instruction(instruction)

    async def _call_dashscope_cosyvoice_websocket(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """异步包装 CosyVoice WebSocket 调用。"""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._run_dashscope_cosyvoice_websocket(
                model=model,
                api_key=api_key,
                text=text,
                voice=voice,
                voice_params=voice_params,
            ),
        )

    def _run_dashscope_cosyvoice_websocket(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """阻塞执行 CosyVoice WebSocket 请求。"""
        import uuid

        import websocket

        task_id = str(uuid.uuid4())
        parameters = self._build_cosyvoice_websocket_parameters(text, voice, voice_params)
        audio_chunks = []
        json_events: List[Dict[str, Any]] = []
        state: Dict[str, Any] = {"error": None, "error_code": None}

        def on_open(ws) -> None:
            run_task_cmd = self._build_cosyvoice_run_task_command(
                task_id=task_id,
                model=model,
                parameters=parameters,
            )
            ws.send(json.dumps(run_task_cmd))

        def on_message(ws, message) -> None:
            if isinstance(message, (bytes, bytearray)):
                audio_chunks.append(bytes(message))
                return

            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("CosyVoice WebSocket 返回了非 JSON 消息: %s", message)
                return

            json_events.append(payload)
            header = payload.get("header") or {}
            event = header.get("event")

            if event == "task-started":
                continue_task_cmd = self._build_cosyvoice_continue_task_command(task_id=task_id, text=text)
                finish_task_cmd = self._build_cosyvoice_finish_task_command(task_id=task_id)
                ws.send(json.dumps(continue_task_cmd))
                ws.send(json.dumps(finish_task_cmd))
                return

            if event == "task-failed":
                state["error"] = (
                    header.get("error_message")
                    or header.get("event_info")
                    or payload.get("payload", {}).get("message")
                    or "CosyVoice websocket task failed"
                )
                state["error_code"] = header.get("error_code")
                ws.close()
                return

            if event == "task-finished":
                ws.close()

        def on_error(ws, error) -> None:
            state["error"] = str(error)

        def on_close(ws, close_status_code, close_msg) -> None:
            return None

        ws = websocket.WebSocketApp(
            "wss://dashscope.aliyuncs.com/api-ws/v1/inference/",
            header={
                "Authorization": f"bearer {api_key}",
                "X-DashScope-DataInspection": "enable",
            },
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        ws.run_forever()

        if state["error"]:
            error_code = state.get("error_code")
            if error_code:
                raise RuntimeError(f"CosyVoice websocket failed: {error_code} {state['error']}")
            raise RuntimeError(f"CosyVoice websocket failed: {state['error']}")

        if not audio_chunks:
            raise RuntimeError("CosyVoice websocket returned no audio data")

        timestamp_metadata = _extract_cosyvoice_timestamp_metadata(json_events)
        self._set_last_synthesis_metadata(
            {
                "provider": "aliyun",
                "provider_model": model,
                "speaker": voice,
                "transport": "websocket",
                "enable_ssml": bool(parameters.get("enable_ssml")),
                "word_timestamp_enabled": bool(parameters.get("word_timestamp_enabled")),
                "phoneme_timestamp_enabled": bool(parameters.get("phoneme_timestamp_enabled")),
                **timestamp_metadata,
            }
        )
        return b"".join(audio_chunks)

    def _build_minimax_voice_candidates(self, voice: str) -> List[str]:
        known_working_voices = [
            "male-qn-qingse",
            "Chinese (Mandarin)_News_Anchor",
        ]
        candidates = [str(voice or "").strip()]
        if candidates[0].startswith("female-qn-"):
            candidates.append(candidates[0].replace("female-qn-", "female-"))
        elif candidates[0].startswith("male-qn-"):
            candidates.append(candidates[0].replace("male-qn-", "male-"))

        if "-" in candidates[0]:
            parts = candidates[0].split("-")
            if len(parts) >= 2:
                candidates.append(parts[-1])

        candidates.extend(known_working_voices)
        return [item for item in dict.fromkeys(candidates) if item]

    def _build_minimax_http_payload(
        self,
        *,
        model: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        style_control = build_model_style_control(
            model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        text = prepare_text_for_style_control(text, style_control)
        speed = float(voice_params.get("rate", voice_params.get("speed", 1.0)) or 1.0)
        volume = int(voice_params.get("volume", 50) or 50)
        pitch = int(voice_params.get("pitch", 0) or 0)
        return {
            "input": {
                "action": "tts",
                "text": text,
                "stream": False,
                "voice_setting": {
                    "voice_id": voice,
                    "speed": max(0.0, min(2.0, speed)),
                    "vol": max(0.0, min(100.0, volume)) / 100.0,
                    "pitch": max(-100, min(100, pitch)),
                },
                "audio_setting": {
                    "sample_rate": 16000,
                    "format": "mp3",
                    "channel": 1,
                },
            },
            "model": model,
        }

    def _build_mimo_chat_payload(
        self,
        *,
        model: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_model = normalize_audiobook_tts_model(model, default=str(model or ""))
        style_control = build_model_style_control(
            normalized_model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        if normalized_model == MIMO_V25_TTS_VOICE_DESIGN_MODEL:
            design_prompt = (
                (str(style_control.messages[0].get("content") or "").strip() if style_control.messages else "")
                or str(voice_params.get("voice_design_prompt") or "").strip()
                or str(voice_params.get("voice_description") or "").strip()
                or str(voice_params.get("instructions") or voice_params.get("instruction") or "").strip()
            )
            messages = [{"role": "user", "content": design_prompt}]
            if text or not _to_bool_flag(voice_params.get("optimize_text_preview")):
                messages.append({"role": "assistant", "content": text})
        elif style_control.mode == "mimo_audio_tags":
            messages = [
                {
                    "role": "assistant",
                    "content": prepare_text_for_style_control(text, style_control),
                }
            ]
        else:
            messages = list(style_control.messages)
            messages.append({"role": "assistant", "content": text})

        stream = _to_bool_flag(voice_params.get("stream"))
        audio_format = str(voice_params.get("format") or ("pcm16" if stream else "wav")).strip().lower()
        if audio_format not in {"wav", "mp3", "pcm16"}:
            audio_format = "pcm16" if stream else "wav"

        audio: Dict[str, Any] = {"format": audio_format}
        if normalized_model == MIMO_V25_TTS_VOICE_DESIGN_MODEL:
            if "optimize_text_preview" in voice_params:
                audio["optimize_text_preview"] = _to_bool_flag(voice_params.get("optimize_text_preview"))
        elif normalized_model == MIMO_V25_TTS_VOICE_CLONE_MODEL:
            explicit_voice = str(voice or "").strip()
            clone_voice = (
                str(voice_params.get("voice_sample_data_url") or "").strip()
                or str(voice_params.get("voice_clone_data_url") or "").strip()
                or (explicit_voice if explicit_voice.startswith("data:audio/") else "")
            )
            if clone_voice:
                audio["voice"] = clone_voice
        else:
            audio["voice"] = str(voice or "").strip() or "mimo_default"

        payload: Dict[str, Any] = {
            "model": normalized_model,
            "messages": messages,
            "audio": audio,
        }
        if stream:
            payload["stream"] = True
        return payload

    def _truncate_stepaudio_instruction(self, value: str) -> str:
        return str(value or "").strip()[:STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS].strip()

    def _build_stepaudio_instruction_payload(self, voice_params: Dict[str, Any]) -> str:
        style_control = build_model_style_control(
            self.model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        instruction = str(
            style_control.provider_fields.get("instruction")
            or style_control.provider_fields.get("instructions")
            or ""
        ).strip()
        return self._truncate_stepaudio_instruction(instruction)

    def _fit_stepaudio_text_to_limit(self, text: str) -> str:
        text = str(text or "").strip()
        if len(text) <= STEPAUDIO_TTS_MAX_INPUT_CHARS:
            return text
        logger.warning(
            "StepAudio TTS input 已截断以满足服务商限制: text=%s->%s",
            len(text),
            STEPAUDIO_TTS_MAX_INPUT_CHARS,
        )
        return text[:STEPAUDIO_TTS_MAX_INPUT_CHARS].strip()

    def _build_stepaudio_http_payload(
        self,
        *,
        model: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_model = normalize_audiobook_tts_model(model, default=str(model or ""))
        payload: Dict[str, Any] = {
            "model": normalized_model or STEPAUDIO_25_TTS_MODEL,
            "voice": str(voice or "").strip() or STEPAUDIO_TTS_DEFAULT_VOICE,
            "input": self._fit_stepaudio_text_to_limit(text),
        }
        instruction = self._build_stepaudio_instruction_payload(voice_params)
        if instruction:
            payload["instruction"] = instruction

        response_format = str(voice_params.get("format") or voice_params.get("response_format") or "").strip().lower()
        if response_format in STEPAUDIO_TTS_RESPONSE_FORMATS:
            payload["response_format"] = response_format
        speed = voice_params.get("speed")
        if isinstance(speed, (int, float)) and not isinstance(speed, bool) and 0.5 <= float(speed) <= 2.0:
            payload["speed"] = float(speed)
        volume = voice_params.get("volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool) and 0.1 <= float(volume) <= 2.0:
            payload["volume"] = float(volume)
        sample_rate = voice_params.get("sample_rate")
        if isinstance(sample_rate, int) and not isinstance(sample_rate, bool) and sample_rate in STEPAUDIO_TTS_SAMPLE_RATES:
            payload["sample_rate"] = sample_rate
        pronunciation_map = voice_params.get("pronunciation_map")
        if isinstance(pronunciation_map, dict) and isinstance(pronunciation_map.get("tone"), list):
            payload["pronunciation_map"] = pronunciation_map
        for bool_param in ("markdown_filter", "return_url"):
            value = voice_params.get(bool_param)
            if isinstance(value, bool):
                payload[bool_param] = value
        stream_format = str(voice_params.get("stream_format") or "").strip().lower()
        if stream_format in STEPAUDIO_TTS_STREAM_FORMATS:
            payload["stream_format"] = stream_format
        return payload

    def _build_stepaudio_voice_preview_payload(
        self,
        *,
        model: str,
        text: str,
        file_id: str,
        sample_text: str = "",
        instruction: str = "",
    ) -> Dict[str, Any]:
        normalized_model = normalize_audiobook_tts_model(model, default=str(model or ""))
        clean_preview_text = self._fit_stepaudio_text_to_limit(text)
        clean_sample_text = str(sample_text or "").strip()
        payload: Dict[str, Any] = {
            "model": normalized_model or STEPAUDIO_25_TTS_MODEL,
            "file_id": str(file_id or "").strip(),
            "text": clean_sample_text or clean_preview_text,
        }
        if clean_preview_text and clean_sample_text:
            payload["sample_text"] = clean_preview_text
        clean_instruction = str(instruction or "").strip()
        if clean_instruction:
            payload["instruction"] = clean_instruction[:STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS]
        return payload

    def _seed_tts_ratio_from_ui_value(self, value: Any, *, default: float = 1.0) -> float:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            return default
        if 0.1 <= ratio <= 2.0:
            return round(ratio, 3)
        if 0 <= ratio <= 100:
            return round(max(0.1, min(2.0, ratio / 50.0)), 3)
        return default

    def _seed_tts_rate_from_ratio(self, ratio: float) -> int:
        return int(round(max(-50.0, min(100.0, (ratio - 1.0) * 100.0))))

    def _seed_tts_pitch_from_ui_value(self, value: Any) -> int:
        try:
            pitch = float(value)
        except (TypeError, ValueError):
            return 0
        if -12 <= pitch <= 12:
            return int(round(pitch))
        if 0 <= pitch <= 100:
            return int(round(max(-12.0, min(12.0, (pitch - 50.0) / 50.0 * 12.0))))
        return 0

    def _build_seed_tts_context_texts(
        self,
        voice_params: Dict[str, Any],
        style_control: Optional[Any] = None,
    ) -> List[str]:
        if style_control is None:
            style_control = build_model_style_control(
                SEED_TTS_20_EXPRESSIVE_MODEL,
                voice_params,
                str(voice_params.get("emotion") or "neutral"),
            )
        context_texts = style_control.provider_fields.get("context_texts")
        if isinstance(context_texts, str):
            return [context_texts] if context_texts.strip() else []
        if isinstance(context_texts, list):
            return [
                str(item).strip()
                for item in context_texts
                if str(item or "").strip()
            ]
        instruction = str(
            voice_params.get("instructions")
            or voice_params.get("instruction")
            or ""
        ).strip()
        return [instruction] if instruction else []

    def _build_seed_tts_http_payload(
        self,
        *,
        model: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_model = normalize_audiobook_tts_model(model, default=str(model or "")) or SEED_TTS_20_EXPRESSIVE_MODEL
        response_format = str(voice_params.get("format") or voice_params.get("response_format") or "mp3").strip().lower()
        if response_format not in SEED_TTS_RESPONSE_FORMATS:
            response_format = "mp3"

        sample_rate = voice_params.get("sample_rate")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate not in SEED_TTS_SAMPLE_RATES:
            sample_rate = 24000

        speed = self._seed_tts_ratio_from_ui_value(voice_params.get("speed", voice_params.get("rate", 1.0)))
        volume = self._seed_tts_ratio_from_ui_value(voice_params.get("volume", 50))
        pitch = self._seed_tts_pitch_from_ui_value(voice_params.get("pitch", 50))
        style_control = build_model_style_control(
            normalized_model,
            voice_params,
            str(voice_params.get("emotion") or "neutral"),
        )
        prepared_text = prepare_text_for_style_control(str(text or ""), style_control)
        context_texts = self._build_seed_tts_context_texts(voice_params, style_control)

        req_params: Dict[str, Any] = {
            "model": normalized_model,
            "text": prepared_text,
            "text_type": "plain",
            "with_timestamp": 0,
        }
        use_tag_parser = _to_bool_flag(voice_params.get("use_tag_parser")) or _to_bool_flag(
            style_control.provider_fields.get("use_tag_parser")
        )
        if context_texts or use_tag_parser:
            req_params["additions"] = _build_seed_tts_additions(
                context_texts=context_texts,
                use_tag_parser=use_tag_parser,
            )
        req_params["speaker"] = str(voice or "").strip() or SEED_TTS_DEFAULT_VOICE
        req_params["audio_params"] = {
            "format": response_format,
            "sample_rate": sample_rate,
            "speech_rate": self._seed_tts_rate_from_ratio(speed),
            "loudness_rate": self._seed_tts_rate_from_ratio(volume),
        }
        if pitch:
            req_params["post_process"] = {"pitch": pitch}

        return {
            "user": {"uid": str(voice_params.get("uid") or "audiobook")},
            "req_params": req_params,
        }

    async def _parse_stepaudio_audio_response(self, response, client) -> bytes:
        import base64

        content_type = str(response.headers.get("content-type") or response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("audio/"):
            return bytes(response.content)

        try:
            data = response.json()
        except Exception:
            return bytes(response.content)

        if not isinstance(data, dict):
            raise ValueError("StepAudio response missing audio data")

        audio_info = data.get("audio") or data.get("data") or data.get("output") or data.get("sample_audio")
        if isinstance(audio_info, str) and audio_info:
            if audio_info.startswith(("http://", "https://")):
                audio_response = await client.get(audio_info)
                if audio_response.status_code == 200:
                    return bytes(audio_response.content)
            if audio_info.startswith("data:") and "," in audio_info:
                audio_info = audio_info.split(",", 1)[1]
            return base64.b64decode(audio_info)

        if isinstance(audio_info, dict):
            audio_data = audio_info.get("data") or audio_info.get("audio") or audio_info.get("sample_audio")
            if isinstance(audio_data, str) and audio_data:
                if audio_data.startswith("data:") and "," in audio_data:
                    audio_data = audio_data.split(",", 1)[1]
                return base64.b64decode(audio_data)
            audio_url = audio_info.get("url")
            if isinstance(audio_url, str) and audio_url:
                audio_response = await client.get(audio_url)
                if audio_response.status_code == 200:
                    return bytes(audio_response.content)

        raise ValueError(f"StepAudio response missing audio data: {str(data)[:200]}")

    async def _parse_seed_tts_audio_response(self, response, client) -> bytes:
        import base64

        content_type = str(response.headers.get("content-type") or response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("audio/"):
            return bytes(response.content)

        try:
            data = response.json()
        except Exception:
            parsed_chunks = _parse_seed_tts_json_audio_chunks(getattr(response, "text", ""))
            if parsed_chunks:
                return parsed_chunks
            if response.content:
                return bytes(response.content)
            raise ValueError("Seed-TTS response missing audio data")

        if not isinstance(data, dict):
            raise ValueError("Seed-TTS response missing audio data")

        audio_info = (
            data.get("audio")
            or data.get("data")
            or data.get("output")
            or data.get("result")
        )
        if isinstance(audio_info, str) and audio_info:
            if audio_info.startswith(("http://", "https://")):
                audio_response = await client.get(audio_info)
                if audio_response.status_code == 200:
                    return bytes(audio_response.content)
            return _decode_seed_tts_audio_value(audio_info) or b""

        if isinstance(audio_info, dict):
            audio_data = (
                audio_info.get("audio")
                or audio_info.get("data")
                or audio_info.get("audio_data")
                or audio_info.get("binary")
            )
            if isinstance(audio_data, str) and audio_data:
                return _decode_seed_tts_audio_value(audio_data) or b""
            audio_url = audio_info.get("url")
            if isinstance(audio_url, str) and audio_url:
                audio_response = await client.get(audio_url)
                if audio_response.status_code == 200:
                    return bytes(audio_response.content)

        raise ValueError(f"Seed-TTS response missing audio data: {str(data)[:200]}")

    def _parse_mimo_audio_response(self, data: Dict[str, Any]) -> bytes:
        import base64

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("MiMo response missing choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError("MiMo response missing message")

        audio_info = message.get("audio")
        audio_data = audio_info.get("data") if isinstance(audio_info, dict) else audio_info
        if not isinstance(audio_data, str) or not audio_data:
            raise ValueError("MiMo response missing audio data")
        return base64.b64decode(audio_data)

    async def _call_seed_tts_websocket(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
        resource_id: str = SEED_TTS_DEFAULT_RESOURCE_ID,
    ) -> bytes:
        """Call Doubao Seed-TTS 2.0 via Volcengine WebSocket API (bidirectional streaming).
        
        Uses official protocols.py module for binary frame protocol.
        """
        import copy
        import sys
        from pathlib import Path

        import websockets
        
        # Import protocols module from scripts directory
        project_root = Path(__file__).parent.parent.parent.parent.parent.parent
        scripts_dir = project_root / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        
        try:
            from protocols import (
                EventType,
                MsgType,
                finish_connection,
                finish_session,
                receive_message,
                start_connection,
                start_session,
                task_request,
                wait_for_event,
            )
        except ImportError as e:
            logger.error(f"Failed to import protocols module: {e}")
            raise RuntimeError(f"Protocols module not found: {e}")

        # WebSocket endpoint
        ws_url = str(os.getenv("SEED_TTS_WS_ENDPOINT") or "wss://openspeech.bytedance.com/api/v3/tts/bidirection").strip()
        clean_resource_id = str(resource_id or SEED_TTS_DEFAULT_RESOURCE_ID).strip()
        connect_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        
        # Build audio parameters
        response_format = str(voice_params.get("format") or voice_params.get("response_format") or "mp3").strip().lower()
        if response_format not in SEED_TTS_RESPONSE_FORMATS:
            response_format = "mp3"
        
        sample_rate = voice_params.get("sample_rate")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate not in SEED_TTS_SAMPLE_RATES:
            sample_rate = 24000
        
        # Convert UI values to API ranges
        speed = self._seed_tts_ratio_from_ui_value(voice_params.get("speed", voice_params.get("rate", 1.0)))
        volume = self._seed_tts_ratio_from_ui_value(voice_params.get("volume", 50))
        pitch = self._seed_tts_pitch_from_ui_value(voice_params.get("pitch", 50))
        
        speech_rate = self._seed_tts_rate_from_ratio(speed)
        loudness_rate = self._seed_tts_rate_from_ratio(volume)
        
        # Build req_params
        base_request: Dict[str, Any] = {
            "req_params": {
                "model": model,
                "speaker": str(voice or "").strip() or SEED_TTS_DEFAULT_VOICE,
                "audio_params": {
                    "format": response_format,
                    "sample_rate": sample_rate,
                    "speech_rate": speech_rate,
                    "loudness_rate": loudness_rate,
                },
            },
        }
        
        # Add optional parameters
        context_texts = self._build_seed_tts_context_texts(voice_params, None)
        if context_texts:
            base_request["req_params"]["context_texts"] = context_texts
        
        use_tag_parser = _to_bool_flag(voice_params.get("use_tag_parser"))
        if use_tag_parser:
            base_request["req_params"]["use_tag_parser"] = True
        
        if pitch:
            base_request["req_params"]["post_process"] = {"pitch": pitch}
        
        websocket = None
        audio_data = bytearray()
        
        try:
            # Connect to server
            headers = {
                "X-Api-Key": api_key,
                "X-Api-Resource-Id": clean_resource_id,
                "X-Api-Connect-Id": connect_id,
                "X-Control-Require-Usage-Tokens-Return": "*",
            }
            
            logger.info(f"Seed-TTS WebSocket: Connecting to {ws_url}")
            websocket = await websockets.connect(
                ws_url,
                additional_headers=headers,
                max_size=10 * 1024 * 1024
            )
            logger.info(f"Seed-TTS WebSocket: Connected, Logid: {websocket.response.headers.get('x-tt-logid', 'N/A')}")
            
            # Start connection
            await start_connection(websocket)
            await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)
            logger.info("Seed-TTS WebSocket: Connection started")
            
            # Start session
            start_session_request = copy.deepcopy(base_request)
            start_session_request["event"] = EventType.StartSession
            await start_session(
                websocket,
                json.dumps(start_session_request).encode(),
                session_id
            )
            await wait_for_event(websocket, MsgType.FullServerResponse, EventType.SessionStarted)
            logger.info("Seed-TTS WebSocket: Session started")
            
            # Send TaskRequest with full text
            task_request_data = copy.deepcopy(base_request)
            task_request_data["event"] = EventType.TaskRequest
            task_request_data["req_params"]["text"] = text
            
            await task_request(
                websocket,
                json.dumps(task_request_data).encode(),
                session_id
            )
            logger.info("Seed-TTS WebSocket: Task request sent")
            
            # Receive audio data and events
            timeout = 30  # seconds
            while True:
                try:
                    msg = await asyncio.wait_for(receive_message(websocket), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning(f"Seed-TTS WebSocket: Timeout after receiving {len(audio_data)} bytes")
                    break
                
                if msg.type == MsgType.FullServerResponse:
                    if msg.event == EventType.SessionFinished:
                        logger.info("Seed-TTS WebSocket: Session finished")
                        break
                    elif msg.event == EventType.TTSSentenceEnd:
                        logger.debug(f"Seed-TTS WebSocket: Sentence ended")
                    elif msg.event in (EventType.SessionFailed, EventType.ConnectionFailed):
                        error_msg = msg.payload.decode('utf-8', errors='replace') if msg.payload else "Unknown error"
                        raise RuntimeError(f"Seed-TTS WebSocket failed: {error_msg}")
                
                elif msg.type == MsgType.AudioOnlyServer:
                    audio_data.extend(msg.payload)
                    logger.debug(f"Seed-TTS WebSocket: Received audio chunk {len(msg.payload)} bytes")
            
            # Finish session
            await finish_session(websocket, session_id)
            
            if not audio_data:
                raise RuntimeError("Seed-TTS WebSocket returned no audio data")
            
            # Set metadata
            self._set_last_synthesis_metadata(
                {
                    "provider": "volcengine",
                    "provider_model": model,
                    "speaker": voice,
                    "transport": "websocket_binary_frame",
                    "base_url": ws_url.replace("/api/v3/tts/bidirection", ""),
                    "endpoint": "/api/v3/tts/bidirection",
                    "resource_id": clean_resource_id,
                    "session_id": session_id,
                    "connect_id": connect_id,
                    "audio_format": response_format,
                    "sample_rate": sample_rate,
                }
            )
            
            logger.info("Seed-TTS WebSocket synthesis completed: %d bytes", len(audio_data))
            return bytes(audio_data)
        
        finally:
            if websocket:
                try:
                    # Finish connection
                    await finish_connection(websocket)
                    try:
                        await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionFinished)
                        logger.debug("Seed-TTS WebSocket: Connection finished")
                    except:
                        pass
                    await websocket.close()
                    logger.debug("Seed-TTS WebSocket: Closed")
                except Exception as e:
                    logger.warning(f"Seed-TTS WebSocket close error: {e}")

    async def _call_seed_tts_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
        resource_id: str = SEED_TTS_DEFAULT_RESOURCE_ID,
    ) -> bytes:
        """Call Doubao Seed-TTS 2.0 via Volcengine HTTP API."""
        import httpx

        endpoint = str(os.getenv("SEED_TTS_HTTP_ENDPOINT") or SEED_TTS_DEFAULT_ENDPOINT).strip()
        clean_resource_id = str(resource_id or SEED_TTS_DEFAULT_RESOURCE_ID).strip()
        app_key = (
            str(os.getenv("VOLCENGINE_TTS_APP_KEY") or os.getenv("DOUBAO_TTS_APP_KEY") or "").strip()
            or api_key
        )
        payload = self._build_seed_tts_http_payload(
            model=model,
            text=text,
            voice=voice,
            voice_params=voice_params,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "X-Api-App-Key": app_key,
                    "X-Api-Key": api_key,
                    "X-Api-Resource-Id": clean_resource_id,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                logger.error("Seed-TTS API 失败: status=%s, body=%s", response.status_code, response.text[:500])
                raise Exception(f"Seed-TTS API error: {response.status_code} - {response.text[:200]}")

            audio_result = await self._parse_seed_tts_audio_response(response, client)
            self._set_last_synthesis_metadata(
                {
                    "provider": "volcengine",
                    "provider_model": payload["req_params"]["model"],
                    "speaker": payload["req_params"]["speaker"],
                    "transport": "http",
                    "base_url": endpoint.removesuffix("/api/v3/tts/unidirectional"),
                    "endpoint": "/api/v3/tts/unidirectional",
                    "resource_id": clean_resource_id,
                    "style_control": "query_response",
                    "context_texts": _extract_seed_tts_context_texts_from_payload(payload),
                    "audio_format": payload["req_params"].get("audio_params", {}).get("format"),
                }
            )
            return audio_result

    async def _call_stepaudio_speech_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """Call StepAudio 2.5 TTS via StepFun HTTP API."""
        import httpx

        base_url = str(os.getenv("STEPAUDIO_TTS_BASE_URL") or STEPAUDIO_TTS_DEFAULT_BASE_URL).rstrip("/")
        endpoint = f"{base_url}/audio/speech"
        payload = self._build_stepaudio_http_payload(
            model=model,
            text=text,
            voice=voice,
            voice_params=voice_params,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                logger.error("StepAudio API 失败: status=%s, body=%s", response.status_code, response.text[:500])
                raise Exception(f"StepAudio TTS API error: {response.status_code} - {response.text[:200]}")

            audio_result = await self._parse_stepaudio_audio_response(response, client)
            self._set_last_synthesis_metadata(
                {
                    "provider": "stepfun",
                    "provider_model": payload["model"],
                    "speaker": payload["voice"],
                    "transport": "http",
                    "base_url": base_url,
                    "endpoint": "/audio/speech",
                    "instruction": payload.get("instruction", ""),
                    "style_control": "global_context_inline_context",
                    "audio_format": payload.get("response_format") or "provider_default",
                }
            )
            return audio_result

    async def _call_stepaudio_voice_preview_http(
        self,
        *,
        model: str,
        api_key: str,
        text: str,
        file_id: str,
        sample_text: str = "",
        instruction: str = "",
    ) -> bytes:
        """Call StepAudio zero-shot voice preview via StepFun HTTP API."""
        import httpx

        clean_file_id = str(file_id or "").strip()
        if not clean_file_id:
            raise ValueError("StepAudio voice preview requires file_id")
        base_url = str(os.getenv("STEPAUDIO_TTS_BASE_URL") or STEPAUDIO_TTS_DEFAULT_BASE_URL).rstrip("/")
        endpoint = f"{base_url}/audio/voices/preview"
        payload = self._build_stepaudio_voice_preview_payload(
            model=model,
            text=text,
            file_id=clean_file_id,
            sample_text=sample_text,
            instruction=instruction,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                logger.error("StepAudio voice preview API 失败: status=%s, body=%s", response.status_code, response.text[:500])
                raise _build_stepaudio_voice_preview_error(response)

            audio_result = await self._parse_stepaudio_audio_response(response, client)
            self._set_last_synthesis_metadata(
                {
                    "provider": "stepfun",
                    "provider_model": payload["model"],
                    "transport": "http",
                    "base_url": base_url,
                    "endpoint": "/audio/voices/preview",
                    "file_id": payload["file_id"],
                    "instruction": payload.get("instruction", ""),
                    "audio_format": "provider_default",
                }
            )
            return audio_result

    async def _call_mimo_chat_completions_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """调用 MiMo-V2.5-TTS via 小米 OpenAI 兼容 HTTP API。"""
        import httpx

        payload = self._build_mimo_chat_payload(
            model=model,
            text=text,
            voice=voice,
            voice_params=voice_params,
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.xiaomimimo.com/v1/chat/completions",
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code != 200:
                logger.error("MiMo API 失败: status=%s, body=%s", response.status_code, response.text[:500])
                raise Exception(f"MiMo TTS API error: {response.status_code} - {response.text[:200]}")

            data = response.json()
            audio_result = self._parse_mimo_audio_response(data)
            self._set_last_synthesis_metadata(
                {
                    "provider": "mimo",
                    "provider_model": payload["model"],
                    "speaker": payload.get("audio", {}).get("voice", ""),
                    "transport": "http",
                    "base_url": "https://api.xiaomimimo.com/v1",
                    "endpoint": "/chat/completions",
                    "style_control_messages": payload["messages"],
                    "audio_format": payload.get("audio", {}).get("format"),
                }
            )
            return audio_result

    async def _call_dashscope_mimo_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """Backward-compatible wrapper for the old private method name."""
        return await self._call_mimo_chat_completions_http(
            model=model,
            api_key=api_key,
            text=text,
            voice=voice,
            voice_params=voice_params,
        )

    async def _call_dashscope_minimax_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """调用 MiniMax TTS via DashScope HTTP API"""
        import httpx

        voice_formats = self._build_minimax_voice_candidates(voice)
        logger.info(f"尝试语音格式: {voice_formats}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            for try_voice in voice_formats:
                try:
                    logger.info(f"尝试语音: {try_voice}")

                    payload = self._build_minimax_http_payload(
                        model=model,
                        text=text,
                        voice=try_voice,
                        voice_params=voice_params,
                    )

                    response = await client.post(
                        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"百炼 MiniMax 响应 (语音: {try_voice}): {str(data)[:500]}")

                        if "output" in data and "base_resp" in data["output"]:
                            base_resp = data["output"]["base_resp"]
                            if "status_code" in base_resp and base_resp["status_code"] != 0:
                                logger.warning(f"语音 {try_voice} 失败: {base_resp}")
                                continue

                        audio_result = await self._try_parse_minimax_audio(data, client)
                        if audio_result:
                            logger.info(f"成功! 使用语音: {try_voice}")
                            return audio_result
                    else:
                        logger.warning(f"语音 {try_voice} 返回 {response.status_code}: {response.text[:200]}")

                except Exception as e:
                    logger.warning(f"尝试语音 {try_voice} 时出错: {e}")
                    continue

            raise Exception("所有 MiniMax 语音格式尝试均失败，尝试的语音: " + str(voice_formats))

    async def _try_parse_minimax_audio(self, data: dict, client) -> Optional[bytes]:
        """解析 MiniMax 响应中的音频数据"""
        try:
            if "output" in data and "data" in data["output"] and "audio" in data["output"]["data"]:
                audio_data = data["output"]["data"]["audio"]
                if isinstance(audio_data, str):
                    # 检查是否是十六进制编码（以 494433 开头，这是 MP3 的标志 "ID3"）
                    if audio_data.startswith("494433"):
                        logger.info("解析到十六进制编码 MP3 数据")
                        return bytes.fromhex(audio_data)
                    else:
                        import base64
                        logger.info("解析到 base64 音频数据")
                        return base64.b64decode(audio_data)

            if "output" in data and "choices" in data["output"]:
                for choice in data["output"]["choices"]:
                    if "message" in choice and "audio" in choice["message"]:
                        audio_url = choice["message"]["audio"]
                        audio_response = await client.get(audio_url)
                        if audio_response.status_code == 200:
                            return audio_response.content
                    elif "message" in choice and "audios" in choice["message"]:
                        audios = choice["message"]["audios"]
                        if audios and len(audios) > 0:
                            audio_data = audios[0].get("data")
                            if audio_data:
                                import base64
                                return base64.b64decode(audio_data)
                            audio_url = audios[0].get("url")
                            if audio_url:
                                audio_response = await client.get(audio_url)
                                if audio_response.status_code == 200:
                                    return audio_response.content

            if "output" in data and "audio" in data["output"]:
                audio_data = data["output"]["audio"]
                if isinstance(audio_data, str):
                    if audio_data.startswith("494433"):
                        return bytes.fromhex(audio_data)
                    else:
                        import base64
                        return base64.b64decode(audio_data)

            if "output" in data and "audio" in data["output"] and "data" in data["output"]["audio"]:
                audio_data = data["output"]["audio"]["data"]
                if audio_data.startswith("494433"):
                    return bytes.fromhex(audio_data)
                else:
                    import base64
                    return base64.b64decode(audio_data)

            if "output" in data and "audio" in data["output"] and "url" in data["output"]["audio"]:
                audio_url = data["output"]["audio"]["url"]
                audio_response = await client.get(audio_url)
                if audio_response.status_code == 200:
                    return audio_response.content
        except Exception as e:
            logger.warning(f"解析音频响应失败: {e}")
            import traceback
            logger.warning(traceback.format_exc())

        return None

    def _build_qwen_http_payload(
        self,
        *,
        model: str,
        text: str,
        voice_id: str,
        voice_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        language_type = self._build_qwen_language_type(voice_params)
        payload: Dict[str, Any] = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice_id,
                "language_type": language_type,
            },
        }
        instruct_payload = self._fit_qwen_instruction_payload_to_limit(
            text=text,
            instruct_payload=self._build_qwen_instruction_payload(voice_params),
        )
        if instruct_payload:
            payload["parameters"] = instruct_payload
        return payload

    async def _call_dashscope_qwen_http(
        self,
        model: str,
        api_key: str,
        text: str,
        voice_id: str,
        voice_params: Dict[str, Any],
    ) -> bytes:
        """调用 Qwen TTS via DashScope HTTP API - 使用正确的 multimodal-generation 端点"""
        import httpx

        # Qwen TTS API 端点（正确）
        endpoint = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
        payload = self._build_qwen_http_payload(
            model=model,
            text=text,
            voice_id=voice_id,
            voice_params=voice_params,
        )
        language_type = str(payload["input"].get("language_type") or "Auto")
        instruct_payload = payload.get("parameters") or {}

        logger.info(
            "调用百炼 Qwen HTTP API: model=%s, voice=%s, language_type=%s, instructions=%s",
            model,
            voice_id,
            language_type,
            bool(instruct_payload.get("instructions")),
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code != 200:
                logger.error(f"百炼 Qwen API 失败: status={response.status_code}, body={response.text[:500]}")
                raise Exception(f"Qwen TTS API error: {response.status_code} - {response.text[:200]}")

            data = response.json()
            logger.info(f"百炼 Qwen 响应: {str(data)[:500]}")

            # Qwen TTS 响应格式（根据阿里云官方文档）：音频直接在 output.audio 字段（base64字符串）
            if "output" in data and "audio" in data["output"]:
                audio_info = data["output"]["audio"]
                
                # 直接是base64字符串（不是对象）
                if isinstance(audio_info, str) and audio_info:
                    import base64
                    logger.info(f"解析到直接base64音频数据，长度: {len(audio_info)}")
                    self._set_last_synthesis_metadata(
                        {
                            "provider": "aliyun",
                            "provider_model": model,
                            "speaker": voice_id,
                            "transport": "http",
                            "language_type": language_type,
                            "instructions": instruct_payload.get("instructions", ""),
                            "optimize_instructions": bool(instruct_payload.get("optimize_instructions")),
                        }
                    )
                    return base64.b64decode(audio_info)
                
                # 是对象的情况
                if isinstance(audio_info, dict):
                    # url 格式
                    audio_url = audio_info.get("url")
                    if audio_url:
                        audio_response = await client.get(audio_url)
                        if audio_response.status_code == 200:
                            self._set_last_synthesis_metadata(
                                {
                                    "provider": "aliyun",
                                    "provider_model": model,
                                    "speaker": voice_id,
                                    "transport": "http",
                                    "language_type": language_type,
                                    "instructions": instruct_payload.get("instructions", ""),
                                    "optimize_instructions": bool(instruct_payload.get("optimize_instructions")),
                                }
                            )
                            return audio_response.content
                    
                    # data 格式
                    audio_data = audio_info.get("data")
                    if audio_data:
                        import base64
                        self._set_last_synthesis_metadata(
                            {
                                "provider": "aliyun",
                                "provider_model": model,
                                "speaker": voice_id,
                                "transport": "http",
                                "language_type": language_type,
                                "instructions": instruct_payload.get("instructions", ""),
                                "optimize_instructions": bool(instruct_payload.get("optimize_instructions")),
                            }
                        )
                        return base64.b64decode(audio_data)

            raise Exception(f"Qwen API response missing audio data: {str(data)[:200]}")
