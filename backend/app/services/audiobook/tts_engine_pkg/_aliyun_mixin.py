"""阿里云 TTS Mixin - 支持 Qwen 和 MiniMax 模型"""

import logging
from typing import Any, Dict, Optional

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

        logger.error(f"不支持的模型: {self.model}")
        return None

    def _normalize_speaker_id(self, raw_speaker_id: str, model: str) -> str:
        """根据模型标准化语音 ID"""
        if not raw_speaker_id:
            return ""

        if self._is_qwen_model():
            from app.services.audiobook.voice_manager import VoiceManager

            preset = VoiceManager.PRESET_VOICES.get(raw_speaker_id)
            return preset["tts_speaker_id"] if preset else raw_speaker_id

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

        voice_params["speaker"] = voice_id
        logger.info(
            "调用阿里云 Qwen-TTS: model=%s, voice=%s",
            provider_model,
            voice_id,
        )
        return await self._call_dashscope_qwen_http(
            model=provider_model,
            api_key=api_key,
            text=text,
            voice_id=voice_id,
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
        
        # Qwen TTS 请求格式（根据阿里云官方文档）
        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice_id,
                "language_type": "Chinese",  # 建议与文本语种一致
            },
        }

        logger.info(f"调用百炼 Qwen HTTP API: model={model}, voice={voice_id}")

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
                    return base64.b64decode(audio_info)
                
                # 是对象的情况
                if isinstance(audio_info, dict):
                    # url 格式
                    audio_url = audio_info.get("url")
                    if audio_url:
                        audio_response = await client.get(audio_url)
                        if audio_response.status_code == 200:
                            return audio_response.content
                    
                    # data 格式
                    audio_data = audio_info.get("data")
                    if audio_data:
                        import base64
                        return base64.b64decode(audio_data)

            raise Exception(f"Qwen API response missing audio data: {str(data)[:200]}")
