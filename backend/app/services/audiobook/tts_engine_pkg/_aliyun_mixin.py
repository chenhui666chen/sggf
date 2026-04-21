"""阿里云 TTS Mixin - 支持 Qwen 和 MiniMax 模型"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("ALIYUN_API_KEY")

        if not api_key:
            logger.error("未设置 DASHSCOPE_API_KEY 或 ALIYUN_API_KEY 环境变量")
            return None

        if not text or not text.strip():
            logger.warning("TTS 文本为空")
            return None

        text = text.strip()
        logger.info(f"准备TTS文本: [{text}] (长度:{len(text)}字)")

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

        if self._is_qwen_model():
            from app.services.audiobook.constants import normalize_speaker_id
            from app.services.audiobook.voice_manager import VoiceManager

            preset = VoiceManager.PRESET_VOICES.get(raw_speaker_id)
            resolved_speaker = preset["tts_speaker_id"] if preset else raw_speaker_id
            return normalize_speaker_id(resolved_speaker)

        if self._is_minimax_model():
            return raw_speaker_id

        return raw_speaker_id

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

        explicit_instructions = str(voice_params.get("instructions") or "").strip()
        if explicit_instructions:
            return {
                "instructions": explicit_instructions,
                "optimize_instructions": bool(voice_params.get("optimize_instructions", True)),
            }

        parts: List[str] = []
        segment_speaker = str(voice_params.get("segment_speaker") or "").strip()
        segment_type = str(voice_params.get("segment_type") or "").strip()
        instruct_role = str(voice_params.get("instruct_role") or "").strip()
        instruct_identity = str(voice_params.get("instruct_identity") or "").strip()
        instruct_scene = str(voice_params.get("instruct_scene") or "").strip()
        instruct_emotion = str(voice_params.get("instruct_emotion") or "").strip()
        performance_notes = str(voice_params.get("performance_notes") or "").strip()
        fallback_emotion = str(voice_params.get("emotion") or "").strip()

        if segment_speaker and segment_speaker != "旁白":
            parts.append(f"说话角色：{segment_speaker}")
        if segment_type:
            parts.append(f"片段类型：{segment_type}")
        if instruct_role:
            parts.append(f"角色设定：{instruct_role}")
        if instruct_identity:
            parts.append(f"身份设定：{instruct_identity}")
        if instruct_scene:
            parts.append(f"场景氛围：{instruct_scene}")
        if instruct_emotion:
            parts.append(f"情绪目标：{instruct_emotion}")
        elif fallback_emotion and fallback_emotion != "neutral":
            parts.append(f"情绪目标：{fallback_emotion}")
        if performance_notes:
            parts.append(f"演绎要求：{performance_notes}")

        instructions = "；".join(parts).strip("；")
        if not instructions and not voice_params.get("use_instruct_mode"):
            return {}

        payload: Dict[str, Any] = {}
        if instructions:
            payload["instructions"] = instructions
            payload["optimize_instructions"] = bool(voice_params.get("optimize_instructions", True))
        return payload

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
        seed = voice_params.get("seed")
        if seed is not None:
            try:
                parameters["seed"] = int(seed)
            except (TypeError, ValueError):
                pass
        return parameters

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
        explicit_instruction = str(
            voice_params.get("instruction") or voice_params.get("instructions") or ""
        ).strip()
        if explicit_instruction:
            return self._truncate_cosyvoice_instruction(explicit_instruction)

        parts: List[str] = []
        segment_speaker = str(voice_params.get("segment_speaker") or "").strip()
        if segment_speaker and segment_speaker != "旁白":
            parts.append(f"说话角色：{segment_speaker}")

        instruct_role = str(voice_params.get("instruct_role") or "").strip()
        instruct_identity = str(voice_params.get("instruct_identity") or "").strip()
        instruct_scene = str(voice_params.get("instruct_scene") or "").strip()
        instruct_emotion = str(
            voice_params.get("instruct_emotion") or voice_params.get("emotion") or ""
        ).strip()
        performance_notes = str(voice_params.get("performance_notes") or "").strip()

        if instruct_role:
            parts.append(f"角色设定：{instruct_role}")
        if instruct_identity:
            parts.append(f"身份设定：{instruct_identity}")
        if instruct_scene:
            parts.append(f"场景氛围：{instruct_scene}")
        if instruct_emotion and instruct_emotion != "neutral":
            parts.append(f"情绪目标：{instruct_emotion}")
        if performance_notes:
            parts.append(f"演绎要求：{performance_notes}")

        if not parts and not voice_params.get("use_instruct_mode"):
            return ""
        return self._truncate_cosyvoice_instruction("；".join(parts).strip("；"))

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
        import json
        import uuid

        import websocket

        task_id = str(uuid.uuid4())
        parameters = self._build_cosyvoice_websocket_parameters(text, voice, voice_params)
        audio_chunks = []
        state: Dict[str, Any] = {"error": None, "error_code": None}

        def on_open(ws) -> None:
            run_task_cmd = {
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

            header = payload.get("header") or {}
            event = header.get("event")

            if event == "task-started":
                continue_task_cmd = {
                    "header": {
                        "action": "continue-task",
                        "task_id": task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {"text": text}},
                }
                finish_task_cmd = {
                    "header": {
                        "action": "finish-task",
                        "task_id": task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {}},
                }
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

        self._set_last_synthesis_metadata(
            {
                "provider": "aliyun",
                "provider_model": model,
                "speaker": voice,
                "transport": "websocket",
                "enable_ssml": bool(parameters.get("enable_ssml")),
            }
        )
        return b"".join(audio_chunks)

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

        speed = float(voice_params.get("rate", voice_params.get("speed", 1.0)) or 1.0)
        volume = int(voice_params.get("volume", 50) or 50)
        pitch = int(voice_params.get("pitch", 0) or 0)
        vol_normalized = max(0.0, min(100.0, volume)) / 100.0

        # 已知的百炼平台可用的 MiniMax 语音列表
        KNOWN_WORKING_VOICES = [
            "male-qn-qingse",  # 已验证可用的语音
            "Chinese (Mandarin)_News_Anchor",  # 用户提供的语音
        ]

        # 所有可能的 MiniMax 语音格式
        all_minimax_voices = [
            # 原始语音
            voice,
            # 去掉 qn- 前缀
        ]

        if voice.startswith("female-qn-"):
            all_minimax_voices.append(voice.replace("female-qn-", "female-"))
        elif voice.startswith("male-qn-"):
            all_minimax_voices.append(voice.replace("male-qn-", "male-"))

        # 只保留名字
        if "-" in voice:
            parts = voice.split("-")
            if len(parts) >= 2:
                all_minimax_voices.append(parts[-1])

        # 添加已知的可用语音作为备选
        for known_voice in KNOWN_WORKING_VOICES:
            if known_voice not in all_minimax_voices:
                all_minimax_voices.append(known_voice)

        # 去重
        voice_formats = list(dict.fromkeys(all_minimax_voices))

        logger.info(f"尝试语音格式: {voice_formats}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            for try_voice in voice_formats:
                try:
                    logger.info(f"尝试语音: {try_voice}")

                    payload = {
                        "input": {
                            "action": "tts",
                            "text": text,
                            "stream": False,
                            "voice_setting": {
                                "voice_id": try_voice,
                                "speed": max(0.0, min(2.0, speed)),
                                "vol": vol_normalized,
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
        language_type = self._build_qwen_language_type(voice_params)
        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice_id,
                "language_type": language_type,
            },
        }
        instruct_payload = self._build_qwen_instruction_payload(voice_params)
        if instruct_payload:
            payload["parameters"] = instruct_payload

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
