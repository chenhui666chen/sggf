# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional

import requests

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 7. TTS/语音 - 百炼原生API
# ============================================================

class _DashScopeTTSAdapter(BaseAdapter):
    MODEL_ID = ""
    VOICE_ID = "longxiaochun"

    def _map_task_to_request(self, task):
        return {"text": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation"
            headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": self.MODEL_ID,
                "input": {
                    "text": prompt or "这是一段测试语音。",
                    "voice_setting": {"voice_id": self.VOICE_ID},
                    "audio_setting": kwargs.get("audio_setting", {"sample_rate": 32000, "format": "mp3"}),
                },
            }
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            data = r.json()

            base_resp = data.get("output", {}).get("base_resp", {})
            if base_resp.get("status_code") == 0:
                audio_hex = data["output"]["data"]["audio"]
                audio_bytes = bytes.fromhex(audio_hex)
                return GenerationResult(
                    success=True, task_id="", model_id=self.spec.id,
                    outputs=[f"audio:{len(audio_bytes)} bytes"],
                    metadata={"audio_bytes": audio_bytes},
                    latency=time.time() - start,
                )
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=f"TTS failed: {base_resp.get('status_msg', 'unknown')}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("MiniMax/speech-2.8-turbo")
class MiniMaxSpeechTurboAdapter(_DashScopeTTSAdapter):
    MODEL_ID = "MiniMax/speech-2.8-turbo"
    VOICE_ID = "male-qn-qingse"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="MiniMax/speech-2.8-turbo", name="MiniMax Speech 2.8 Turbo", provider="minimax", version="v2.8",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=5.0,
        )


@register_model("MiniMax/speech-2.8-hd")
class MiniMaxSpeechHDAdapter(MiniMaxSpeechTurboAdapter):
    MODEL_ID = "MiniMax/speech-2.8-hd"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="MiniMax/speech-2.8-hd", name="MiniMax Speech 2.8 HD", provider="minimax", version="v2.8",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=8.0,
        )


@register_model("qwen3-tts-instruct-flash")
class Qwen3TTSInstructFlashAdapter(BaseAdapter):
    MODEL_ID = "qwen3-tts-instruct-flash"

    def _map_task_to_request(self, task):
        return {"text": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation"
            headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
            voice_id = kwargs.get("voice_id", "Cherry")
            payload: Dict[str, Any] = {
                "model": self.MODEL_ID,
                "input": {
                    "text": prompt or "这是一段测试语音。",
                    "voice": voice_id,
                    "language_type": kwargs.get("language_type", "Auto"),
                },
            }
            instructions = str(kwargs.get("instructions") or "").strip()
            if instructions:
                payload["parameters"] = {
                    "instructions": instructions,
                    "optimize_instructions": bool(kwargs.get("optimize_instructions", True)),
                }
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            data = r.json()

            audio_info = data.get("output", {}).get("audio")
            if isinstance(audio_info, dict) and audio_info.get("url"):
                return GenerationResult(
                    success=True, task_id="", model_id=self.spec.id,
                    outputs=[audio_info["url"]], latency=time.time() - start,
                )
            if isinstance(audio_info, str) and audio_info:
                return GenerationResult(
                    success=True,
                    task_id="",
                    model_id=self.spec.id,
                    outputs=[f"audio:{len(audio_info)} base64"],
                    metadata={"audio_base64": audio_info},
                    latency=time.time() - start,
                )
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=f"TTS failed: {json.dumps(data, ensure_ascii=False)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3-tts-instruct-flash", name="Qwen3 TTS Instruct Flash", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )


@register_model("cosyvoice-v3.5-plus")
class CosyVoiceV35PlusAdapter(BaseAdapter):
    MODEL_ID = "cosyvoice-v3.5-plus"
    VOICE_ID = ""

    def _map_task_to_request(self, task):
        return {"text": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        import uuid
        import websocket
        start = time.time()

        audio_chunks = []
        errors = []
        task_done = False

        try:
            ws_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
            headers = {
                "Authorization": f"bearer {DASHSCOPE_API_KEY}",
                "X-DashScope-DataInspection": "enable",
            }
            voice_id = str(kwargs.get("voice_id") or self.VOICE_ID).strip()
            if not voice_id:
                return GenerationResult(
                    success=False,
                    task_id="",
                    model_id=self.spec.id,
                    error="cosyvoice-v3.5-plus 需要传入复刻/设计 voice_id",
                    latency=time.time() - start,
                )

            def on_open(ws):
                task_id = str(uuid.uuid4())
                parameters = {
                    "text_type": "PlainText",
                    "voice": voice_id,
                    "format": kwargs.get("format", "mp3"),
                    "sample_rate": kwargs.get("sample_rate", 22050),
                    "volume": kwargs.get("volume", 50),
                    "rate": kwargs.get("rate", 1.0),
                    "pitch": kwargs.get("pitch", 1.0),
                }
                instruction = str(kwargs.get("instruction") or kwargs.get("instructions") or "").strip()
                if instruction:
                    parameters["instruction"] = instruction
                run_task_cmd = {
                    "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
                    "payload": {
                        "task_group": "audio", "task": "tts",
                        "function": "SpeechSynthesizer", "model": self.MODEL_ID,
                        "parameters": parameters,
                        "input": {},
                    },
                }
                ws.send(json.dumps(run_task_cmd))

            def on_message(ws, message):
                nonlocal task_done
                if isinstance(message, str):
                    msg_json = json.loads(message)
                    if "header" in msg_json:
                        event = msg_json["header"].get("event")
                        if event == "task-started":
                            continue_task = {
                                "header": {"action": "continue-task", "task_id": msg_json["header"]["task_id"], "streaming": "duplex"},
                                "payload": {"input": {"text": prompt or "这是一段测试语音。"}},
                            }
                            ws.send(json.dumps(continue_task))
                            finish_task = {
                                "header": {"action": "finish-task", "task_id": msg_json["header"]["task_id"], "streaming": "duplex"},
                                "payload": {"input": {}},
                            }
                            ws.send(json.dumps(finish_task))
                        elif event == "task-finished":
                            task_done = True
                            ws.close()
                        elif event == "task-failed":
                            errors.append(msg_json["header"].get("error_message", "Unknown error"))
                            task_done = True
                            ws.close()
                else:
                    audio_chunks.append(message)

            def on_error(ws, error):
                errors.append(str(error))
                task_done = True

            def on_close(ws, close_status_code, close_msg):
                nonlocal task_done
                task_done = True

            ws = websocket.WebSocketApp(
                ws_url, header=headers,
                on_open=on_open, on_message=on_message,
                on_error=on_error, on_close=on_close,
            )
            ws.run_forever()

            if audio_chunks:
                audio_bytes = b"".join(audio_chunks)
                return GenerationResult(
                    success=True, task_id="", model_id=self.spec.id,
                    outputs=[f"audio:{len(audio_bytes)} bytes"],
                    metadata={"audio_bytes": audio_bytes},
                    latency=time.time() - start,
                )
            else:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=errors[0] if errors else "No audio returned",
                    latency=time.time() - start,
                )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="cosyvoice-v3.5-plus", name="CosyVoice V3.5 Plus", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )


