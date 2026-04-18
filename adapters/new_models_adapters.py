# -*- coding: utf-8 -*-
"""
Complete adapters for ALL models
- DashScope (百炼): Wan, Qwen, Kling, PixVerse, Vidu(video), MiniMax, CosyVoice
- Volcengine (火山方舟): Doubao Seedream, Seedance, Seed
- Vidu Platform: vidu-timing2audio
- Mureka: mureka-o1-instrumental
"""

from __future__ import annotations

import os
import time
import base64
import requests
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import BaseAdapter, AdapterConfig, GenerationResult
from adapters.registry import register_model
from schemas.model_spec import ModelSpec
from schemas.common import ModelStatus

# ============================================================
# 配置
# ============================================================

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip() or "***REDACTED-DASHSCOPE-KEY***"
VOLCENGINE_API_KEY = os.getenv("VOLCENGINE_API_KEY", "").strip() or "8cb15ed7-4471-49ee-ad7e-eece828e1e24"
VIDU_API_KEY = os.getenv("VIDU_API_KEY", "").strip() or "vda_942023019369345024_eDxHYrWsuosFvrIIKzPQhSY384hs9iCv"
MUREKA_API_KEY = os.getenv("MUREKA_API_KEY", "").strip() or "op_mj8g9cd9Sav2RaX2yfTKWeDwfQ1q6G4"
MUREKA_API_URL = os.getenv("MUREKA_API_URL", "https://api.mureka.cn")

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
VOLCENGINE_BASE = "https://ark.cn-beijing.volces.com/api/v3"
VIDU_BASE = "https://api.vidu.cn"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _encode_image(path_text: str) -> str:
    value = str(path_text or "").strip()
    if not value:
        return value
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.exists():
        return value
    suffix = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('utf-8')}"


def _poll_dashscope_task(task_id: str, api_key: str, timeout: int = 600, interval: int = 3) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"{DASHSCOPE_BASE}/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            data = r.json()
            status = data.get("output", {}).get("task_status", "")
            if status == "SUCCEEDED":
                return data
            elif status in {"FAILED", "CANCELED"}:
                raise RuntimeError(f"Task failed: {data.get('output', {}).get('message', 'Unknown')}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Task timed out after {timeout}s")


def _poll_volcengine_task(task_id: str, api_key: str, timeout: int = 600, interval: int = 5) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"{VOLCENGINE_BASE}/contents/generations/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=10,
            )
            data = r.json()
            status = data.get("status", "")
            if status == "succeeded":
                return data
            elif status in {"failed", "cancelled"}:
                raise RuntimeError(f"Task failed: {data.get('last_error', {}).get('message', 'Unknown')}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Task timed out after {timeout}s")


def _poll_vidu_task(task_id: str, api_key: str, timeout: int = 300, interval: int = 5) -> Dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(
                f"https://api.vidu.cn/ent/v2/tasks/{task_id}/creations",
                headers={"Authorization": f"Token {api_key}"},
                timeout=10,
            )
            if r.status_code == 404:
                time.sleep(interval)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Vidu poll HTTP {r.status_code}: {r.text[:100]}")
            data = r.json()
            state = data.get("state", "")
            if state == "success":
                return data
            elif state == "failed":
                raise RuntimeError(f"Vidu task failed: {data}")
            time.sleep(interval)
        except requests.Timeout:
            continue
    raise TimeoutError(f"Vidu task timed out after {timeout}s")


# ============================================================
# 1. 图像生成 - 百炼同步API (messages格式)
# ============================================================

class _SyncImageAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation"
            headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
            content = [{"text": prompt}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": kwargs.get("size", "1024*1024"), "n": 1},
            }

            r = requests.post(url, json=payload, headers=headers, timeout=120)
            data = r.json()

            choices = data.get("output", {}).get("choices", [])
            urls = []
            for choice in choices:
                for item in choice.get("message", {}).get("content", []):
                    if "image" in item:
                        urls.append(item["image"])

            return GenerationResult(
                success=bool(urls), task_id="", model_id=self.spec.id,
                outputs=urls, error=None if urls else f"No image URLs: {str(data)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen-image-2.0")
class QwenImage20Adapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-2.0"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-2.0", name="Qwen Image 2.0", provider="alibaba", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=15.0,
        )


@register_model("qwen-image-2.0-pro")
class QwenImage20ProAdapter(_SyncImageAdapter):
    MODEL_ID = "qwen-image-2.0-pro"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-2.0-pro", name="Qwen Image 2.0 Pro", provider="alibaba", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=15.0,
        )


@register_model("wan2.7-image")
class Wan27ImageAdapter(_SyncImageAdapter):
    MODEL_ID = "wan2.7-image"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-image", name="Wan 2.7 Image", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


@register_model("wan2.6-t2i")
class Wan26T2IAdapter(_SyncImageAdapter):
    MODEL_ID = "wan2.6-t2i"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.6-t2i", name="Wan 2.6 T2I", provider="alibaba", version="v2.6",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


# ============================================================
# 2. 图像生成 - 百炼异步API (Kling)
# ============================================================

class _AsyncImageAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/image-generation/generation"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            content = [{"text": prompt}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": kwargs.get("parameters", {"n": 1}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()

            # Check for API-level error
            if "code" in data and data["code"] != "":
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error [{data.get('code')}]: {data.get('message', 'Unknown')[:150]}",
                    latency=time.time() - start,
                )

            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:300]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("IMAGE_TASK_TIMEOUT", 180))
            # Kling uses choices[].message.content[].image format
            choices = result.get("output", {}).get("choices", [])
            urls = []
            for choice in choices:
                for item in choice.get("message", {}).get("content", []):
                    if "image" in item:
                        urls.append(item["image"])
            # Fallback: some models use results[].url format
            if not urls:
                results = result.get("output", {}).get("results", [])
                for item in results:
                    if "url" in item:
                        urls.append(item["url"])
                    elif "image" in item:
                        urls.append(item["image"])

            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("kling/kling-v3-image-generation")
class KlingV3ImageAdapter(_AsyncImageAdapter):
    MODEL_ID = "kling/kling-v3-image-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-image-generation", name="Kling V3 Image", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_image"], avg_latency_seconds=45.0,
        )


@register_model("kling/kling-v3-omni-image-generation")
class KlingV3OmniImageAdapter(_AsyncImageAdapter):
    MODEL_ID = "kling/kling-v3-omni-image-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-omni-image-generation", name="Kling V3 Omni Image", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=50.0,
        )


# ============================================================
# 3. 图像生成 - 火山方舟 (Doubao Seedream)
# ============================================================

class _SeedreamImageAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{VOLCENGINE_BASE}/images/generations"
            headers = {"Authorization": f"Bearer {VOLCENGINE_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": self.MODEL_ID,
                "prompt": prompt or "一朵花",
                "size": kwargs.get("size", "2048x2048"),
                "n": 1,
                "response_format": "url",
            }
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    payload["image"] = img

            r = requests.post(url, json=payload, headers=headers, timeout=120)
            data = r.json()

            if "error" in data:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error: {json.dumps(data['error'], ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            image_data = data.get("data", [])
            urls = []
            for item in image_data:
                if "url" in item:
                    urls.append(item["url"])
                elif "b64_json" in item:
                    urls.append(f"data:image/png;base64,{item['b64_json']}")

            return GenerationResult(
                success=bool(urls), task_id="", model_id=self.spec.id,
                outputs=urls, error=None if urls else f"No image data: {str(data)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seedream-4-5")
class DoubaoSeedream45Adapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-4-5-251128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-4-5", name="Doubao Seedream 4.5", provider="doubao", version="v4.5",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


@register_model("doubao-seedream-5-0")
class DoubaoSeedream50Adapter(_SeedreamImageAdapter):
    MODEL_ID = "doubao-seedream-5-0-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedream-5-0", name="Doubao Seedream 5.0", provider="doubao", version="v5.0",
            status=ModelStatus.ACTIVE, modality=["text_to_image", "image_to_image"], avg_latency_seconds=15.0,
        )


# ============================================================
# 4. 文本对话 - 百炼OpenAI兼容接口
# ============================================================

class _DashScopeChatAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        import openai
        start = time.time()
        try:
            client = openai.OpenAI(api_key=DASHSCOPE_API_KEY, base_url=f"{DASHSCOPE_BASE}/compatible-mode/v1")
            response = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": prompt or "你好"}],
                max_tokens=200,
            )
            content = response.choices[0].message.content or ""
            return GenerationResult(
                success=bool(content), task_id="", model_id=self.spec.id,
                outputs=[content], error=None if content else "Empty response",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen3.5-omni-plus")
class Qwen35OmniPlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3.5-omni-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.5-omni-plus", name="Qwen 3.5 Omni Plus", provider="alibaba", version="v3.5",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


@register_model("qwen3.6-plus")
class Qwen36PlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3.6-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3.6-plus", name="Qwen 3.6 Plus", provider="alibaba", version="v3.6",
            status=ModelStatus.ACTIVE, modality=["text_to_text"], avg_latency_seconds=5.0,
        )


# ============================================================
# 5. 文本对话 - 火山方舟OpenAI兼容接口 (Doubao Seed)
# ============================================================

class _VolcengineChatAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        import openai
        start = time.time()
        try:
            client = openai.OpenAI(api_key=VOLCENGINE_API_KEY, base_url=f"{VOLCENGINE_BASE}")
            response = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": prompt or "你好"}],
                max_tokens=200,
            )
            content = response.choices[0].message.content or ""
            return GenerationResult(
                success=bool(content), task_id="", model_id=self.spec.id,
                outputs=[content], error=None if content else "Empty response",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seed-2-0-pro")
class DoubaoSeed20ProAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-0-pro-260215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-0-pro", name="Doubao Seed 2.0 Pro", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=5.0,
        )


@register_model("doubao-seed-2-0-lite")
class DoubaoSeed20LiteAdapter(_VolcengineChatAdapter):
    MODEL_ID = "doubao-seed-2-0-lite-260215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seed-2-0-lite", name="Doubao Seed 2.0 Lite", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_generation", "chat"], avg_latency_seconds=3.0,
        )


# ============================================================
# 6. 多模态对话 - 百炼OpenAI兼容接口 (qwen3-vl-plus)
# ============================================================

@register_model("qwen3-vl-plus")
class Qwen3VLPlusAdapter(_DashScopeChatAdapter):
    MODEL_ID = "qwen3-vl-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen3-vl-plus", name="Qwen3 VL Plus", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["multimodal_chat", "image_understanding", "video_understanding"],
            avg_latency_seconds=5.0,
        )


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


@register_model("qwen3-tts-flash")
class Qwen3TTSFlashAdapter(BaseAdapter):
    MODEL_ID = "qwen3-tts-flash"

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
                "input": {"text": prompt or "这是一段测试语音。"},
                "parameters": {"voice": "Cherry"},
            }
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            data = r.json()

            audio_url = data.get("output", {}).get("audio", {}).get("url", "")
            if audio_url:
                return GenerationResult(
                    success=True, task_id="", model_id=self.spec.id,
                    outputs=[audio_url], latency=time.time() - start,
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
            id="qwen3-tts-flash", name="Qwen3 TTS Flash", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )


@register_model("cosyvoice-v3-plus")
class CosyVoiceV3PlusAdapter(BaseAdapter):
    MODEL_ID = "cosyvoice-v3-plus"
    VOICE_ID = "longanyang"

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

            def on_open(ws):
                task_id = str(uuid.uuid4())
                run_task_cmd = {
                    "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
                    "payload": {
                        "task_group": "audio", "task": "tts",
                        "function": "SpeechSynthesizer", "model": self.MODEL_ID,
                        "parameters": {
                            "text_type": "PlainText",
                            "voice": kwargs.get("voice_id", self.VOICE_ID),
                            "format": kwargs.get("format", "mp3"),
                            "sample_rate": kwargs.get("sample_rate", 22050),
                            "volume": kwargs.get("volume", 50),
                            "rate": kwargs.get("rate", 1.0),
                            "pitch": kwargs.get("pitch", 1.0),
                        },
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
            id="cosyvoice-v3-plus", name="CosyVoice V3 Plus", provider="alibaba", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_speech"], avg_latency_seconds=3.0,
        )


# ============================================================
# 8. 视频生成 - 百炼异步API (文生视频: wan2.7-t2v, wan2.6-t2v)
# ============================================================

class _DashScopeT2VAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            payload = {
                "model": self.MODEL_ID,
                "input": {"prompt": prompt},
                "parameters": kwargs.get("parameters", {"duration": 5, "resolution": "720P"}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("wan2.7-t2v")
class Wan27T2VAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "wan2.7-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-t2v", name="Wan 2.7 T2V", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


@register_model("wan2.6-t2v-fast")
class Wan26T2VFashAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "wan2.6-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.6-t2v-fast", name="Wan 2.6 T2V Fast", provider="alibaba", version="v2.6",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


# ============================================================
# 8b. 视频生成 - 百炼异步API (图生视频: wan2.7-i2v, 使用input.media格式)
# ============================================================

class _DashScopeI2VAdapter(BaseAdapter):
    MODEL_ID = ""
    MEDIA_TYPE = "first_frame"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": self.MEDIA_TYPE, "url": img})
            if kwargs.get("video_path"):
                vid = kwargs["video_path"]
                if vid:
                    media.append({"type": "video", "url": vid})
            if kwargs.get("reference_images"):
                for ref_img in kwargs["reference_images"]:
                    media.append({"type": "reference_image", "url": ref_img})

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"duration": 5, "resolution": "720P"}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("wan2.7-i2v")
class Wan27I2VAdapter(_DashScopeI2VAdapter):
    MODEL_ID = "wan2.7-i2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-i2v", name="Wan 2.7 I2V", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["image_to_video"], avg_latency_seconds=60.0,
        )


# ============================================================
# 8c. 视频生成 - 百炼异步API (参考生视频: wan2.7-r2v, 使用input.media格式)
# ============================================================

@register_model("wan2.7-r2v")
class Wan27R2VAdapter(_DashScopeI2VAdapter):
    MODEL_ID = "wan2.7-r2v"
    MEDIA_TYPE = "reference_image"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-r2v", name="Wan 2.7 R2V", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["video_to_video", "reference_to_video", "text_to_video", "image_to_video"],
            avg_latency_seconds=60.0,
        )


# ============================================================
# 8d. 视频生成 - 百炼异步API (视频编辑: wan2.7-videoedit)
# ============================================================

@register_model("wan2.7-videoedit")
class Wan27VideoEditAdapter(_DashScopeI2VAdapter):
    MODEL_ID = "wan2.7-videoedit"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="wan2.7-videoedit", name="Wan 2.7 VideoEdit", provider="alibaba", version="v2.7",
            status=ModelStatus.ACTIVE, modality=["video_to_video", "video_edit"], avg_latency_seconds=60.0,
        )


# ============================================================
# 8e. 视频生成 - 百炼异步API (PixVerse, 使用input.media + parameters.size)
# ============================================================

class _PixverseVideoAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": "image_url", "url": img})

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"size": "1280*720", "duration": 5}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("pixverse-c1-r2v")
class PixverseC1R2VAdapter(_PixverseVideoAdapter):
    MODEL_ID = "pixverse/pixverse-c1-r2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="pixverse-c1-r2v", name="PixVerse C1 R2V", provider="pixverse", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_video", "reference_to_video"], avg_latency_seconds=45.0,
        )


@register_model("pixverse-v6-t2v")
class PixverseV6T2VAdapter(_PixverseVideoAdapter):
    MODEL_ID = "pixverse/pixverse-v6-t2v"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="pixverse-v6-t2v", name="PixVerse V6 T2V", provider="pixverse", version="v6",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


# ============================================================
# 8f. 视频生成 - 百炼异步API (Vidu, 使用input.media格式)
# ============================================================

class _ViduVideoAdapter(BaseAdapter):
    MODEL_ID = ""
    MIN_IMAGES = 1

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": "image", "url": img})
            if kwargs.get("image_paths"):
                for img_path in kwargs["image_paths"]:
                    img = _encode_image(img_path)
                    if img:
                        media.append({"type": "image", "url": img})
            while len(media) < self.MIN_IMAGES and media:
                media.append(media[-1])

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"duration": 5, "resolution": "720P"}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("vidu-q3-pro-img2video")
class ViduQ3ProImg2VideoAdapter(_ViduVideoAdapter):
    MODEL_ID = "vidu/viduq3-pro_img2video"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-img2video", name="Vidu Q3 Pro Img2Video", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["image_to_video"], avg_latency_seconds=45.0,
        )


@register_model("vidu-q3-pro-text2video")
class ViduQ3ProText2VideoAdapter(_DashScopeT2VAdapter):
    MODEL_ID = "vidu/viduq3-pro_text2video"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-text2video", name="Vidu Q3 Pro Text2Video", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=45.0,
        )


@register_model("vidu-q3-pro-start-end2video")
class ViduQ3ProStartEndAdapter(_ViduVideoAdapter):
    MODEL_ID = "vidu/viduq3-pro_start-end2video"
    MIN_IMAGES = 2

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="vidu-q3-pro-start-end2video", name="Vidu Q3 Pro Start-End", provider="vidu", version="q3",
            status=ModelStatus.ACTIVE, modality=["image_to_video", "start_end_to_video"], avg_latency_seconds=50.0,
        )


# ============================================================
# 8g. 视频生成 - 百炼异步API (Kling视频, 使用input.media格式)
# ============================================================

class _KlingVideoAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            media = []
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    media.append({"type": "first_frame", "url": img})

            inp = {"prompt": prompt}
            if media:
                inp["media"] = media

            payload = {
                "model": self.MODEL_ID,
                "input": inp,
                "parameters": kwargs.get("parameters", {"duration": 5, "aspect_ratio": "16:9"}),
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            data = r.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_dashscope_task(task_id, DASHSCOPE_API_KEY, timeout=_env_int("VIDEO_TASK_TIMEOUT", 600))
            urls = []
            video_url = result.get("output", {}).get("video_url", "")
            if video_url:
                urls.append(video_url)
            if not urls:
                outputs = result.get("output", {}).get("results", [])
                urls = [o.get("url", "") for o in outputs if o.get("url")]
            return GenerationResult(
                success=bool(urls), task_id=task_id, model_id=self.spec.id,
                outputs=urls, latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("kling/kling-v3-video-generation")
class KlingV3VideoAdapter(_KlingVideoAdapter):
    MODEL_ID = "kling/kling-v3-video-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-video-generation", name="Kling V3 Video", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_video"], avg_latency_seconds=60.0,
        )


@register_model("kling/kling-v3-omni-video-generation")
class KlingV3OmniVideoAdapter(_KlingVideoAdapter):
    MODEL_ID = "kling/kling-v3-omni-video-generation"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="kling/kling-v3-omni-video-generation", name="Kling V3 Omni Video", provider="kling", version="v3",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


# ============================================================
# 9. 视频生成 - 火山方舟 (Doubao Seedance)
# ============================================================

class _SeedanceVideoAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{VOLCENGINE_BASE}/contents/generations/tasks"
            headers = {"Authorization": f"Bearer {VOLCENGINE_API_KEY}", "Content-Type": "application/json"}

            content = [{"type": "text", "text": prompt or "一只猫在奔跑"}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.append({"type": "image_url", "image_url": {"url": img}, "role": kwargs.get("image_role", "reference_image")})
            if kwargs.get("video_path"):
                vid = kwargs["video_path"]
                if vid:
                    content.append({"type": "video_url", "video_url": {"url": vid}, "role": kwargs.get("video_role", "reference_video")})
            if kwargs.get("audio_path"):
                aud = kwargs["audio_path"]
                if aud:
                    content.append({"type": "audio_url", "audio_url": {"url": aud}, "role": kwargs.get("audio_role", "reference_audio")})

            payload = {
                "model": self.MODEL_ID,
                "content": content,
                "ratio": kwargs.get("ratio", "16:9"),
                "duration": kwargs.get("duration", 5),
                "watermark": False,
            }
            if kwargs.get("generate_audio"):
                payload["generate_audio"] = True

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()

            if "error" in data:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"API error: {json.dumps(data['error'], ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            task_id = data.get("id", "")
            if not task_id:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"No task_id: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            # Poll for result
            poll_start = time.time()
            while time.time() - poll_start < _env_int("VIDEO_TASK_TIMEOUT", 600):
                time.sleep(5)
                pr = requests.get(
                    f"{VOLCENGINE_BASE}/contents/generations/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {VOLCENGINE_API_KEY}"},
                    timeout=10,
                )
                if pr.status_code != 200:
                    continue
                pdata = pr.json()
                status = pdata.get("status", "")
                if status == "succeeded":
                    video_url = ""
                    # Format 1: content.video_url (Seedance 1.5/2.0)
                    content_data = pdata.get("content", {})
                    if isinstance(content_data, dict):
                        video_url = content_data.get("video_url", "")
                    # Format 2: video_url directly
                    if not video_url:
                        video_url = pdata.get("video_url", "")
                    # Format 3: video_result[].url
                    if not video_url:
                        videos = pdata.get("video_result", [])
                        for v in videos:
                            if "url" in v:
                                video_url = v["url"]
                                break
                    return GenerationResult(
                        success=bool(video_url), task_id=task_id, model_id=self.spec.id,
                        outputs=[video_url] if video_url else [],
                        latency=time.time() - start,
                    )
                elif status in ("failed", "cancelled", "expired"):
                    return GenerationResult(
                        success=False, task_id=task_id, model_id=self.spec.id,
                        error=f"Task {status}: {json.dumps(pdata, ensure_ascii=False)[:200]}",
                        latency=time.time() - start,
                    )

            return GenerationResult(
                success=False, task_id=task_id, model_id=self.spec.id,
                error=f"Task timed out after 600s",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("doubao-seedance-2-0")
class DoubaoSeedance20Adapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-2-0-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0", name="Doubao Seedance 2.0", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video", "audio_to_video", "video_to_video"],
            avg_latency_seconds=60.0,
        )


@register_model("doubao-seedance-2-0-fast")
class DoubaoSeedance20FastAdapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-2-0-fast-260128"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-2-0-fast", name="Doubao Seedance 2.0 Fast", provider="doubao", version="v2.0",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"],
            avg_latency_seconds=45.0,
        )


@register_model("doubao-seedance-1-5-pro")
class DoubaoSeedance15ProAdapter(_SeedanceVideoAdapter):
    MODEL_ID = "doubao-seedance-1-5-pro-251215"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="doubao-seedance-1-5-pro", name="Doubao Seedance 1.5 Pro", provider="doubao", version="v1.5",
            status=ModelStatus.ACTIVE, modality=["text_to_video", "image_to_video"], avg_latency_seconds=60.0,
        )


# ============================================================
# 10. 音效生成 - Vidu平台 (timing2audio)
# ============================================================

@register_model("vidu-timing2audio")
class ViduTiming2AudioAdapter(BaseAdapter):
    MODEL_ID = "audio1.0"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{VIDU_BASE}/ent/v2/timing2audio"
            headers = {
                "Authorization": f"Token {VIDU_API_KEY}",
                "Content-Type": "application/json",
            }
            timing_prompts = [{"prompt": prompt or "thunder sound effect", "from": 0, "to": kwargs.get("duration", 5)}]
            payload = {
                "model": self.MODEL_ID,
                "duration": kwargs.get("duration", 5),
                "timing_prompts": timing_prompts,
            }

            r = requests.post(url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            try:
                text = r.text.strip()
                if text.startswith("data:"):
                    lines = [l for l in text.split("\n") if l.startswith("data:") and not l.endswith("[DONE]")]
                    if lines:
                        data = json.loads(lines[0][5:].strip())
                    else:
                        data = {}
                else:
                    data = json.loads(text)
            except Exception as parse_err:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"JSON parse error: {parse_err}, raw: {r.text[:200]}",
                    latency=time.time() - start,
                )

            task_id = data.get("task_id", "")
            state = data.get("state", "")
            if not task_id or state == "failed":
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"Vidu API error: {json.dumps(data, ensure_ascii=False)[:200]}",
                    latency=time.time() - start,
                )

            result = _poll_vidu_task(task_id, VIDU_API_KEY, timeout=_env_int("AUDIO_TASK_TIMEOUT", 120))

            audio_url = ""
            creations = result.get("creations", [])
            for c in creations:
                if "url" in c:
                    audio_url = c["url"]
                    break
            if not audio_url:
                audio_url = result.get("data", {}).get("audio_url", "") or result.get("audio_url", "")
            return GenerationResult(
                success=bool(audio_url), task_id=task_id, model_id=self.spec.id,
                outputs=[audio_url] if audio_url else [],
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
            id="vidu-timing2audio", name="Vidu Timing2Audio", provider="vidu", version="v1",
            status=ModelStatus.ACTIVE, modality=["text_to_audio", "timing_audio"], avg_latency_seconds=15.0,
        )


# ============================================================
# 11. 图像编辑 - 百炼API
# ============================================================

class _ImageEditAdapter(BaseAdapter):
    MODEL_ID = ""

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/multimodal-generation/generation"
            headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
            content = [{"text": prompt or "请编辑这张图片"}]
            if kwargs.get("image_path"):
                img = _encode_image(kwargs["image_path"])
                if img:
                    content.insert(0, {"image": img})
            else:
                test_img = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"
                content.insert(0, {"image": test_img})

            payload = {
                "model": self.MODEL_ID,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"size": kwargs.get("size", "1024*1024"), "n": 1},
            }

            r = requests.post(url, json=payload, headers=headers, timeout=120)
            data = r.json()

            choices = data.get("output", {}).get("choices", [])
            urls = []
            for choice in choices:
                for item in choice.get("message", {}).get("content", []):
                    if "image" in item:
                        urls.append(item["image"])

            return GenerationResult(
                success=bool(urls), task_id="", model_id=self.spec.id,
                outputs=urls, error=None if urls else f"No image URLs: {str(data)[:200]}",
                latency=time.time() - start,
            )
        except Exception as e:
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=str(e), latency=time.time() - start,
            )


@register_model("qwen-image-edit-plus")
class QwenImageEditPlusAdapter(_ImageEditAdapter):
    MODEL_ID = "qwen-image-edit-plus"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-edit-plus", name="Qwen Image Edit Plus", provider="alibaba", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_image_edit", "image_edit"], avg_latency_seconds=15.0,
        )


@register_model("qwen-image-edit-max")
class QwenImageEditMaxAdapter(_ImageEditAdapter):
    MODEL_ID = "qwen-image-edit-max"

    @classmethod
    def get_model_spec(cls) -> ModelSpec:
        return ModelSpec(
            id="qwen-image-edit-max", name="Qwen Image Edit Max", provider="alibaba", version="v1",
            status=ModelStatus.ACTIVE, modality=["image_to_image_edit", "image_edit"], avg_latency_seconds=15.0,
        )


# ============================================================
# 12. 音乐生成 - Mureka平台
# ============================================================

@register_model("mureka-o1-instrumental")
class MurekaO1InstrumentalAdapter(BaseAdapter):
    MODEL_ID = "mureka-o1-instrumental"

    def _map_task_to_request(self, task):
        return {"prompt": task.prompt}

    def _call_api(self, request):
        raise NotImplementedError

    def _parse_response(self, response, task):
        raise NotImplementedError

    def generate(self, prompt: str = "", **kwargs) -> GenerationResult:
        start = time.time()
        try:
            url = f"{MUREKA_API_URL}/v1/instrumental/generate"
            headers = {"Authorization": f"Bearer {MUREKA_API_KEY}", "Content-Type": "application/json"}
            payload = {"prompt": prompt or "epic cinematic music", "model": "auto", "duration": 30}
            r = requests.post(url, json=payload, headers=headers, timeout=120)
            if r.status_code != 200:
                return GenerationResult(
                    success=False, task_id="", model_id=self.spec.id,
                    error=f"HTTP {r.status_code}: {r.text[:200]}",
                    latency=time.time() - start,
                )
            data = r.json()
            # Mureka returns async task with status
            task_id = data.get("id", "")
            status = data.get("status", "")
            audio_url = data.get("url", "") or data.get("audio_url", "")
            if audio_url:
                return GenerationResult(
                    success=True, task_id=task_id, model_id=self.spec.id,
                    outputs=[audio_url], latency=time.time() - start,
                )
            if task_id and status in ("preparing", "processing", "queued"):
                # Poll for result
                poll_start = time.time()
                while time.time() - poll_start < 300:
                    time.sleep(5)
                    pr = requests.get(
                        f"{MUREKA_API_URL}/v1/instrumental/query/{task_id}",
                        headers={"Authorization": f"Bearer {MUREKA_API_KEY}"},
                        timeout=30,
                    )
                    if pr.status_code == 200:
                        pdata = pr.json()
                        pstatus = pdata.get("status", "")
                        purl = pdata.get("url", "") or pdata.get("audio_url", "")
                        # Check choices array for audio URLs
                        if not purl:
                            choices = pdata.get("choices", [])
                            for c in choices:
                                if "url" in c:
                                    purl = c["url"]
                                    break
                        if purl and pstatus in ("succeeded", "completed", "success"):
                            return GenerationResult(
                                success=True, task_id=task_id, model_id=self.spec.id,
                                outputs=[purl], latency=time.time() - start,
                            )
                        if pstatus in ("failed", "error"):
                            return GenerationResult(
                                success=False, task_id=task_id, model_id=self.spec.id,
                                error=f"Mureka task failed: {json.dumps(pdata, ensure_ascii=False)[:200]}",
                                latency=time.time() - start,
                            )
                return GenerationResult(
                    success=False, task_id=task_id, model_id=self.spec.id,
                    error=f"Mureka task timed out after 180s",
                    latency=time.time() - start,
                )
            return GenerationResult(
                success=False, task_id="", model_id=self.spec.id,
                error=f"Unexpected: {json.dumps(data, ensure_ascii=False)[:200]}",
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
            id="mureka-o1-instrumental", name="Mureka O1 Instrumental", provider="mureka", version="v1",
            status=ModelStatus.ACTIVE, modality=["text_to_audio"], avg_latency_seconds=30.0,
        )
