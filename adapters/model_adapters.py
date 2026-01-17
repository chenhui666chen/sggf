"""
模型适配器层 - 支持多种 AI 模型的统一接口。

不依赖 ComfyUI/LoRA，按“能力/供应商”抽象适配。
"""

from __future__ import annotations

import json
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import requests

from adapters.rate_limiter import get_rate_limiter


@dataclass
class ModelConfig:
    """模型配置"""
    api_key: str
    base_url: str
    model_name: str
    timeout: int = 60
    max_retries: int = 3
    max_requests_per_minute: Optional[int] = None
    max_requests_per_day: Optional[int] = None
    rate_limit_key: str = ""


@dataclass
class GenerationResult:
    """生成结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0


class BaseModelAdapter(ABC):
    """模型适配器基类"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json"
        })
        self._rate_limiter = get_rate_limiter(
            key=(config.rate_limit_key or config.model_name or ""),
            max_requests_per_minute=config.max_requests_per_minute,
            max_requests_per_day=config.max_requests_per_day,
        )

    def _base_host(self) -> str:
        """
        从 base_url 提取 scheme://netloc（用于某些厂商把不同能力挂在不同 path 下的场景）。
        例如：https://dashscope.aliyuncs.com/compatible-mode/v1 -> https://dashscope.aliyuncs.com
        """
        raw = (self.config.base_url or "").strip()
        if not raw:
            return ""
        try:
            parsed = urlparse(raw)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:  # noqa: BLE001
            return ""
        return ""

    def _is_dashscope(self) -> bool:
        host = self._base_host()
        return "dashscope.aliyuncs.com" in host

    def _retry_delay_s(self, attempt: int, *, response: Optional[requests.Response] = None) -> float:
        """
        计算重试等待时间（指数退避 + 抖动）；若响应包含 Retry-After（秒），则优先使用该值。
        """
        base = float(2 ** max(int(attempt), 0))
        retry_after: Optional[float] = None
        if isinstance(response, requests.Response):
            raw = response.headers.get("Retry-After")
            if raw is not None:
                s = str(raw).strip()
                if s.isdigit():
                    try:
                        retry_after = float(int(s))
                    except Exception:  # noqa: BLE001
                        retry_after = None

        delay = max(base, float(retry_after)) if retry_after is not None else base
        delay = min(delay, 30.0)
        delay *= random.uniform(0.75, 1.25)
        return max(0.0, float(delay))

    def _http_error_with_detail(self, exc: requests.exceptions.HTTPError) -> requests.exceptions.HTTPError:
        """
        requests 的 HTTPError 默认不包含响应体细节；这里尝试提取常见错误字段并拼到 message 里，便于排障。
        注意：仍保持异常类型为 HTTPError，避免破坏上层对 status_code 的分支逻辑（如 404 回退）。
        """
        resp = getattr(exc, "response", None)
        if not isinstance(resp, requests.Response):
            return exc

        detail = ""
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                code = payload.get("code")
                message = payload.get("message")
                request_id = payload.get("request_id") or payload.get("requestId")
                err = payload.get("error")
                if isinstance(err, dict):
                    message = message or err.get("message") or err.get("msg")
                    code = code or err.get("code")
                elif isinstance(err, str):
                    message = message or err
                detail_obj = payload.get("detail")
                if message is None and isinstance(detail_obj, str):
                    message = detail_obj

                parts: List[str] = []
                if code:
                    parts.append(f"code={code}")
                if request_id:
                    parts.append(f"request_id={request_id}")
                if message:
                    parts.append(f"message={str(message)[:300]}")
                detail = ", ".join(parts)
        except Exception:  # noqa: BLE001
            detail = ""

        if not detail:
            try:
                text = (resp.text or "").strip()
                if text:
                    detail = text[:300]
            except Exception:  # noqa: BLE001
                detail = ""

        if not detail:
            return exc

        base_msg = str(exc)
        if detail in base_msg:
            return exc
        return requests.HTTPError(f"{base_msg} ({detail})", response=resp)

    def _request_json_url(self, *, method: str, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        retries = int(getattr(self.config, "max_retries", 1) or 1)
        if retries <= 0:
            retries = 1

        last_exc: Optional[Exception] = None
        for attempt in range(retries):
            try:
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                response = self.session.request(
                    str(method or "POST"),
                    str(url),
                    json=payload,
                    timeout=self.config.timeout,
                )
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as exc:
                    raise self._http_error_with_detail(exc) from exc

                try:
                    return response.json()
                except Exception as exc:  # noqa: BLE001
                    text = (getattr(response, "text", "") or "").strip()
                    snippet = text[:300] if text else ""
                    raise ValueError(f"响应不是有效 JSON（url={url}）: {snippet}") from exc
            except requests.exceptions.HTTPError as exc:
                last_exc = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and int(status) < 500 and int(status) != 429:
                    raise
                if attempt >= retries - 1:
                    raise
                time.sleep(self._retry_delay_s(attempt, response=getattr(exc, "response", None)))
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt >= retries - 1:
                    raise
                time.sleep(self._retry_delay_s(attempt, response=getattr(exc, "response", None)))

        if last_exc is not None:
            raise last_exc
        return {}

    def _make_request(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        method: str = "POST"
    ) -> Dict[str, Any]:
        """发送API请求"""
        base_url = (self.config.base_url or "").rstrip("/")
        ep = (endpoint or "").lstrip("/")
        if base_url.endswith("/v1") and ep.startswith("v1/"):
            ep = ep[len("v1/") :]
        url = f"{base_url}/{ep}"
        return self._request_json_url(method=method, url=url, payload=payload)

    @abstractmethod
    def generate(self, **kwargs) -> GenerationResult:
        """生成内容"""
        pass


class Wan26T2IAdapter(BaseModelAdapter):
    """Wan 2.6 T2I (Text-to-Image) 适配器 - 文生图"""

    def _dashscope_model_name(self) -> str:
        # 兼容：用户可能配置了控制台的数字模型ID；DashScope AIGC 接口通常使用模型名（如 wanx-v1）。
        raw = str(self.config.model_name or "").strip()
        if raw.isdigit():
            explicit = (os.getenv("WAN_T2I_MODEL_NAME") or "").strip()
            return explicit or "wanx-v1"
        return raw

    def _dashscope_text_to_image(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        seed: Optional[int],
    ) -> Dict[str, Any]:
        host = self._base_host()
        if not host:
            raise RuntimeError("dashscope host missing from WAN_T2I_BASE_URL")

        url = f"{host}/api/v1/services/aigc/multimodal-generation/generation"

        def _error_detail(resp: Any) -> str:
            if not isinstance(resp, requests.Response):
                return ""
            try:
                payload = resp.json()
                if isinstance(payload, dict):
                    code = payload.get("code")
                    message = payload.get("message")
                    request_id = payload.get("request_id") or payload.get("requestId")
                    parts = []
                    if code:
                        parts.append(f"code={code}")
                    if request_id:
                        parts.append(f"request_id={request_id}")
                    if message:
                        parts.append(f"message={message}")
                    if parts:
                        return ", ".join(parts)
            except Exception:  # noqa: BLE001
                pass
            text = (getattr(resp, "text", "") or "").strip()
            return text[:500] if text else ""

        def _candidate_sizes(w: int, h: int) -> List[str]:
            items: List[tuple[int, int]] = []
            ww = 0
            hh = 0
            try:
                ww = int(w)
                hh = int(h)
                if ww > 0 and hh > 0:
                    items.append((ww, hh))
            except Exception:  # noqa: BLE001
                ww = 0
                hh = 0

            if ww >= hh:
                preset = [
                    (1024, 576),
                    (1024, 768),
                    (1024, 1024),
                    (576, 1024),
                    (768, 1024),
                ]
            else:
                preset = [
                    (576, 1024),
                    (768, 1024),
                    (1024, 1024),
                    (1024, 576),
                    (1024, 768),
                ]
            for p in preset:
                if p not in items:
                    items.append(p)
            return [f"{a}*{b}" for a, b in items]

        sizes = _candidate_sizes(width, height)
        last_error: Optional[str] = None
        for size in sizes[:3]:
            payload: Dict[str, Any] = {
                "model": self._dashscope_model_name(),
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "text": prompt
                                }
                            ]
                        }
                    ]
                },
                "parameters": {
                    "size": size,
                    "n": 1,
                    "prompt_extend": True,
                    "watermark": False
                },
            }
            if negative_prompt:
                payload["parameters"]["negative_prompt"] = negative_prompt
            if seed is not None:
                payload["parameters"]["seed"] = int(seed)

            for async_enabled in (True, False):
                headers = {"X-DashScope-Async": "enable"} if async_enabled else None
                resp: Any = None
                try:
                    if self._rate_limiter:
                        self._rate_limiter.acquire()
                    resp = self.session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.config.timeout,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    output = data.get("output") if isinstance(data, dict) else None
                    if isinstance(output, dict):
                        choices = output.get("choices")
                        if (
                            isinstance(choices, list)
                            and choices
                            and isinstance(choices[0], dict)
                        ):
                            choice = choices[0]
                            message = choice.get("message") if isinstance(choice, dict) else None
                            if isinstance(message, dict):
                                content = message.get("content") if isinstance(message, dict) else None
                                if isinstance(content, list) and content:
                                    for content_item in content:
                                        if isinstance(content_item, dict) and "image" in content_item:
                                            image_url = content_item.get("image")
                                            if isinstance(image_url, str) and image_url:
                                                return {"data": [{"url": image_url}]}
                        task_id = output.get("task_id")
                        if isinstance(task_id, str) and task_id:
                            return {"output": {"task_id": task_id}}

                    raise RuntimeError("dashscope t2i response unsupported")
                except requests.exceptions.HTTPError as exc:
                    resp_obj = getattr(exc, "response", None)
                    if resp_obj is None:
                        resp_obj = resp
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    detail = _error_detail(resp_obj)
                    last_error = f"dashscope t2i HTTP {status} (size={size}, async={async_enabled}): {detail}".strip()
                    if async_enabled:
                        continue
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = f"dashscope t2i error (size={size}, async={async_enabled}): {str(exc)}"
                    break

        raise RuntimeError(last_error or "dashscope t2i request failed")

    def _dashscope_poll_task(self, *, task_id: str) -> Dict[str, Any]:
        host = self._base_host()
        if not host:
            raise RuntimeError("dashscope host missing from WAN_T2I_BASE_URL")
        url = f"{host}/api/v1/tasks/{task_id}"
        # DashScope 的 AIGC 接口通常返回异步 task_id，排队 + 生成可能远超单次 HTTP 超时。
        # 因此这里将“轮询总时长”与“单次请求超时”分离，避免素材生成阶段因短 timeout 误判失败。
        #
        # 可通过以下环境变量覆盖（单位秒）：
        # - WAN_T2I_TASK_TIMEOUT：轮询总时长（默认 1800）
        # - WAN_T2I_POLL_HTTP_TIMEOUT：轮询接口单次请求超时（默认 min(WAN_T2I_TIMEOUT, 15)）
        # - WAN_T2I_POLL_INTERVAL_S：轮询间隔（默认 2）
        def _env_int(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None or not raw.strip():
                return default
            try:
                return int(raw)
            except Exception:  # noqa: BLE001
                return default

        task_timeout_s = max(10, _env_int("WAN_T2I_TASK_TIMEOUT", 1800))
        poll_http_timeout_s = _env_int("WAN_T2I_POLL_HTTP_TIMEOUT", min(int(self.config.timeout or 60), 15))
        poll_interval_s = max(1, _env_int("WAN_T2I_POLL_INTERVAL_S", 2))
        if poll_http_timeout_s <= 0:
            poll_http_timeout_s = min(int(self.config.timeout or 60), 15)
        deadline = time.time() + task_timeout_s

        last_payload: Any = None
        last_error: str | None = None
        while time.time() < deadline:
            try:
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                resp = self.session.get(url, timeout=poll_http_timeout_s)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                # 轮询期间允许短暂网络抖动/限流，不应立刻终止整个生成链路。
                last_error = str(exc)
                time.sleep(poll_interval_s)
                continue
            last_payload = payload
            output = payload.get("output") if isinstance(payload, dict) else None
            status = None
            if isinstance(output, dict):
                status = output.get("task_status") or output.get("status")
                results = output.get("results")
                if isinstance(results, list) and results and isinstance(results[0], dict) and isinstance(results[0].get("url"), str):
                    return {"data": [{"url": results[0]["url"]}]}
            if isinstance(status, str) and status.upper() in {"FAILED", "FAIL", "ERROR"}:
                raise RuntimeError(f"dashscope task failed: {str(output)[:500] if isinstance(output, dict) else str(payload)[:500]}")
            time.sleep(poll_interval_s)

        tail = str(last_payload)[:500] if last_payload is not None else ""
        if last_error and tail:
            raise RuntimeError(f"dashscope task timeout: {task_id} (last_error={last_error[:200]}, last_payload={tail})")
        if last_error:
            raise RuntimeError(f"dashscope task timeout: {task_id} (last_error={last_error[:200]})")
        raise RuntimeError(f"dashscope task timeout: {task_id} ({tail})")

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None
    ) -> GenerationResult:
        """生成图像"""
        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
        }
        
        if seed is not None:
            payload["seed"] = seed
        
        try:
            result = self._make_request("v1/images/generations", payload)
            
            if "data" in result and len(result["data"]) > 0:
                image_url = result["data"][0]["url"]
                return GenerationResult(
                    success=True,
                    data={"image_url": image_url},
                    metadata={
                        "prompt": prompt,
                        "width": width,
                        "height": height,
                        "model": self.config.model_name
                    }
                )
            else:
                return GenerationResult(
                    success=False,
                    data=None,
                    error="No image data returned"
                )
        except requests.exceptions.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # DashScope 的 OpenAI Compatible 目前可能不支持 images/generations；
            # 这里自动切换到官方 AIGC Text2Image 接口，尽量不要求用户改配置。
            if status == 404 and self._is_dashscope():
                try:
                    dash_result = self._dashscope_text_to_image(
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        seed=seed,
                    )
                    if isinstance(dash_result, dict):
                        output = dash_result.get("output")
                        if isinstance(output, dict) and isinstance(output.get("task_id"), str):
                            dash_result = self._dashscope_poll_task(task_id=output["task_id"])
                        if "data" in dash_result and isinstance(dash_result.get("data"), list) and dash_result["data"]:
                            url = dash_result["data"][0].get("url") if isinstance(dash_result["data"][0], dict) else None
                            if isinstance(url, str) and url:
                                return GenerationResult(success=True, data={"image_url": url})
                except Exception as exc:  # noqa: BLE001
                    return GenerationResult(success=False, data=None, error=str(exc))
            return GenerationResult(success=False, data=None, error=str(e))
        except Exception as e:
            return GenerationResult(success=False, data=None, error=str(e))


class Wan26I2VAdapter(BaseModelAdapter):
    """Wan 2.6 I2V (Image-to-Video) 适配器 - 图生视频"""

    def _dashscope_model_name(self) -> str:
        # 兼容：用户可能只配置了控制台的数字模型ID；DashScope/百炼服务侧通常需要模型名（如 wan2.6-i2v）。
        raw = str(self.config.model_name or "").strip()
        if raw.isdigit():
            explicit = (os.getenv("WAN_I2V_MODEL_NAME") or "").strip()
            return explicit or "wan2.6-i2v"
        return raw

    def _dashscope_i2v_via_video_synthesis(
        self,
        *,
        image_path: str,
        prompt: str,
        duration: float,
        seed: Optional[int],
        character_references: Optional[List[Dict[str, Any]]] = None,
    ) -> GenerationResult:
        """
        DashScope 官方 AIGC 视频接口（/api/v1/services/aigc/video-generation/video-synthesis）。

        说明：
        - compatible-mode/v1 目前不保证支持 v1/videos/i2v；这里优先使用官方 VideoSynthesis（SDK），避免“调用成功但无 video_url”导致的静态幻灯片回退。
        - 官方接口参数相对收敛：重点传 size/duration/seed，避免注入不确定参数导致 4xx。
        """
        try:
            import dashscope  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=f"dashscope sdk missing: {exc}")

        model_value = self._dashscope_model_name()

        size: Optional[str] = None
        try:
            from PIL import Image  # type: ignore

            with Image.open(image_path) as im:
                if getattr(im, "width", 0) and getattr(im, "height", 0):
                    size = f"{int(im.width)}*{int(im.height)}"
        except Exception:  # noqa: BLE001
            size = None

        duration_i = int(round(float(duration or 0.0)))
        if duration_i <= 0:
            duration_i = 5

        kwargs: Dict[str, Any] = {"duration": duration_i}
        if size:
            kwargs["size"] = size
        if seed is not None:
            kwargs["seed"] = int(seed)
        if character_references and isinstance(character_references, list):
            kwargs["character_references"] = character_references

        try:
            if self._rate_limiter:
                self._rate_limiter.acquire()
            resp = dashscope.VideoSynthesis.call(
                model=model_value,
                prompt=prompt,
                img_url=image_path,
                api_key=self.config.api_key,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=str(exc))

        status_code = getattr(resp, "status_code", None)
        if status_code is not None and int(status_code) != 200:
            code = getattr(resp, "code", None)
            message = getattr(resp, "message", None)
            return GenerationResult(success=False, data=None, error=f"dashscope video_synthesis failed: {status_code} {code} {message}")

        output = getattr(resp, "output", None)
        video_url: Optional[str] = None
        if isinstance(output, dict) and isinstance(output.get("video_url"), str):
            video_url = output.get("video_url")
        elif hasattr(output, "get") and isinstance(getattr(output, "get")("video_url"), str):
            video_url = getattr(output, "get")("video_url")
        elif isinstance(getattr(output, "video_url", None), str):
            video_url = getattr(output, "video_url")

        if not isinstance(video_url, str) or not video_url.strip():
            return GenerationResult(success=False, data=None, error=f"dashscope video_synthesis response missing video_url: {str(output)[:300]}")

        return GenerationResult(
            success=True,
            data={"video_url": video_url},
            metadata={
                "prompt": prompt,
                "duration": duration_i,
                "model": self.config.model_name,
                "dashscope_model": model_value,
                "size": size,
            },
        )

    def generate(
        self,
        image_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        motion_bucket_id: int = 127,
        seed: Optional[int] = None,
        character_references: Optional[List[Dict[str, Any]]] = None
    ) -> GenerationResult:
        """从图像生成视频"""
        # DashScope：优先走官方 VideoSynthesis，避免 compatible-mode 接口不支持导致的"静态幻灯片回退"。
        if self._is_dashscope():
            return self._dashscope_i2v_via_video_synthesis(
                image_path=image_path,
                prompt=prompt,
                duration=duration,
                seed=seed,
                character_references=character_references,
            )

        # 非 DashScope：读取图像并编码为 base64，走 OpenAI-compatible 自定义 endpoint
        with open(image_path, "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode()
        model_value = self.config.model_name

        payload = {
            "model": model_value,
            "image": image_data,
            "prompt": prompt,
            "duration": duration,
            "fps": fps,
            "motion_bucket_id": motion_bucket_id,
        }
        
        if seed is not None:
            payload["seed"] = seed
        
        if character_references and isinstance(character_references, list):
            payload["character_references"] = character_references
        
        try:
            result = self._make_request("v1/videos/i2v", payload)
            
            if "data" in result and len(result["data"]) > 0:
                video_url = result["data"][0]["url"]
                return GenerationResult(
                    success=True,
                    data={"video_url": video_url},
                    metadata={
                        "prompt": prompt,
                        "duration": duration,
                        "fps": fps,
                        "model": self.config.model_name,
                        "character_references": character_references
                    }
                )
            else:
                return GenerationResult(
                    success=False,
                    data=None,
                    error="No video data returned"
                )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class Wan26T2VAdapter(BaseModelAdapter):
    """Wan 2.6 T2V (Text-to-Video) 适配器 - 文生视频"""

    def _dashscope_model_name(self) -> str:
        raw = str(self.config.model_name or "").strip()
        if raw.isdigit():
            explicit = (os.getenv("WAN_T2V_MODEL_NAME") or "").strip()
            return explicit or "wan2.6-t2v"
        return raw

    def _dashscope_t2v_via_video_synthesis(
        self,
        *,
        prompt: str,
        duration: float,
        seed: Optional[int],
    ) -> GenerationResult:
        """
        DashScope 官方 AIGC 视频接口（/api/v1/services/aigc/video-generation/video-synthesis）。
        """
        try:
            import dashscope  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=f"dashscope sdk missing: {exc}")

        model_value = self._dashscope_model_name()

        duration_i = int(round(float(duration or 0.0)))
        if duration_i <= 0:
            duration_i = 5

        kwargs: Dict[str, Any] = {"duration": duration_i}
        if seed is not None:
            kwargs["seed"] = int(seed)

        try:
            if self._rate_limiter:
                self._rate_limiter.acquire()
            resp = dashscope.VideoSynthesis.call(
                model=model_value,
                prompt=prompt,
                api_key=self.config.api_key,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=str(exc))

        status_code = getattr(resp, "status_code", None)
        if status_code is not None and int(status_code) != 200:
            code = getattr(resp, "code", None)
            message = getattr(resp, "message", None)
            return GenerationResult(success=False, data=None, error=f"dashscope video_synthesis failed: {status_code} {code} {message}")

        output = getattr(resp, "output", None)
        video_url: Optional[str] = None
        if isinstance(output, dict) and isinstance(output.get("video_url"), str):
            video_url = output.get("video_url")
        elif hasattr(output, "get") and isinstance(getattr(output, "get")("video_url"), str):
            video_url = getattr(output, "get")("video_url")
        elif isinstance(getattr(output, "video_url", None), str):
            video_url = getattr(output, "video_url")

        if not isinstance(video_url, str) or not video_url.strip():
            return GenerationResult(success=False, data=None, error=f"dashscope video_synthesis response missing video_url: {str(output)[:300]}")

        return GenerationResult(
            success=True,
            data={"video_url": video_url},
            metadata={
                "prompt": prompt,
                "duration": duration_i,
                "model": self.config.model_name,
                "dashscope_model": model_value,
            },
        )

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        duration: float = 3.0,
        fps: int = 24,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None
    ) -> GenerationResult:
        """从文本生成视频"""
        if self._is_dashscope():
            return self._dashscope_t2v_via_video_synthesis(
                prompt=prompt,
                duration=duration,
                seed=seed,
            )

        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "duration": duration,
            "fps": fps,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
        }
        
        if seed is not None:
            payload["seed"] = seed
        
        try:
            result = self._make_request("v1/videos/t2v", payload)
            
            if "data" in result and len(result["data"]) > 0:
                video_url = result["data"][0]["url"]
                return GenerationResult(
                    success=True,
                    data={"video_url": video_url},
                    metadata={
                        "prompt": prompt,
                        "width": width,
                        "height": height,
                        "duration": duration,
                        "fps": fps,
                        "model": self.config.model_name
                    }
                )
            else:
                return GenerationResult(
                    success=False,
                    data=None,
                    error="No video data returned"
                )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class Wan26R2VAdapter(BaseModelAdapter):
    """Wan 2.6 R2V (Reference-to-Video) 适配器 - 参考视频生成视频"""

    def generate(
        self,
        reference_video_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        seed: Optional[int] = None
    ) -> GenerationResult:
        """从参考视频生成新视频"""
        # 读取视频并编码为base64
        with open(reference_video_path, "rb") as f:
            import base64
            video_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "reference_video": video_data,
            "prompt": prompt,
            "duration": duration,
            "fps": fps,
        }
        
        if seed is not None:
            payload["seed"] = seed
        
        try:
            result = self._make_request("v1/videos/r2v", payload)
            
            if "data" in result and len(result["data"]) > 0:
                video_url = result["data"][0]["url"]
                return GenerationResult(
                    success=True,
                    data={"video_url": video_url},
                    metadata={
                        "prompt": prompt,
                        "duration": duration,
                        "fps": fps,
                        "model": self.config.model_name
                    }
                )
            else:
                return GenerationResult(
                    success=False,
                    data=None,
                    error="No video data returned"
                )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class QwenImageEditPlusAdapter(BaseModelAdapter):
    """Qwen-Image-Edit-Plus 适配器 - 图片编辑"""

    def generate(
        self,
        image_path: str,
        edit_prompt: str,
        mask_path: Optional[str] = None,
        strength: float = 0.8,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None
    ) -> GenerationResult:
        """编辑图像"""
        if not self._is_dashscope():
            return GenerationResult(
                success=False,
                data=None,
                error="QwenImageEditPlusAdapter only supports DashScope"
            )

        try:
            with open(image_path, "rb") as f:
                import base64
                image_data = base64.b64encode(f.read()).decode()

            host = self._base_host()
            if not host:
                raise RuntimeError("dashscope host missing from QWEN_IMAGE_EDIT_BASE_URL")

            url = f"{host}/api/v1/services/aigc/multimodal-generation/generation"

            payload: Dict[str, Any] = {
                "model": self.config.model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "image": f"data:image/png;base64,{image_data}"
                                },
                                {
                                    "text": edit_prompt
                                }
                            ]
                        }
                    ]
                },
                "parameters": {
                    "n": 1,
                    "watermark": False
                },
            }

            if seed is not None:
                payload["parameters"]["seed"] = int(seed)

            result = self._request_json_url(method="POST", url=url, payload=payload)

            output = result.get("output", {})
            choices = output.get("choices", [])

            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content", [])

                for item in content:
                    if isinstance(item, dict) and "image" in item:
                        image_url = item["image"]
                        return GenerationResult(
                            success=True,
                            data={"image_url": image_url},
                            metadata={
                                "edit_prompt": edit_prompt,
                                "strength": strength,
                                "model": self.config.model_name
                            }
                        )

            return GenerationResult(
                success=False,
                data=None,
                error="No image data returned"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )
        
        if mask_path:
            with open(mask_path, "rb") as f:
                mask_data = base64.b64encode(f.read()).decode()
            payload["mask"] = mask_data
        
        if seed is not None:
            payload["seed"] = seed
        
        try:
            legacy_payload = dict(payload)
            legacy_payload.pop("prompt", None)
            legacy_payload["edit_prompt"] = edit_prompt

            # OpenAI 的标准路径为 /v1/images/edits；部分旧实现使用 /images/edit。
            # 这里按“标准路径/标准字段 -> 标准路径/旧字段 -> 旧路径/标准字段 -> 旧路径/旧字段”的顺序兼容。
            result: Dict[str, Any] | None = None
            last_exc: Exception | None = None
            for endpoint, body in (
                ("v1/images/edits", payload),
                ("v1/images/edits", legacy_payload),
                ("v1/images/edit", payload),
                ("v1/images/edit", legacy_payload),
            ):
                try:
                    result = self._make_request(endpoint, body)
                    last_exc = None
                    break
                except requests.exceptions.HTTPError as e:
                    last_exc = e
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status in {400, 404}:
                        continue
                    raise
            if result is None and last_exc is not None:
                raise last_exc
             
            if "data" in result and len(result["data"]) > 0:
                image_url = result["data"][0]["url"]
                return GenerationResult(
                    success=True,
                    data={"image_url": image_url},
                    metadata={
                        "edit_prompt": edit_prompt,
                        "strength": strength,
                        "model": self.config.model_name
                    }
                )
            else:
                return GenerationResult(
                    success=False,
                    data=None,
                    error="No image data returned"
                )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class WanImageEditAdapter(QwenImageEditPlusAdapter):
    """Wan Image Edit 适配器 - 图像编辑"""


class QwenMultiPersonFusionAdapter(BaseModelAdapter):
    """Qwen-Image-Edit-Plus 多人物融合适配器 - 支持人物提取、场景匹配、多人物融合"""

    def _make_request(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        method: str = "POST"
    ) -> Dict[str, Any]:
        """
        发送API请求 - 重写以使用DashScope原生API端点
        
        Qwen-Image-Edit-Plus使用DashScope原生API，不是OpenAI兼容模式
        """
        base_host = self._base_host()
        if not base_host:
            base_host = "https://dashscope.aliyuncs.com"
        
        url = f"{base_host}/api/v1/{endpoint}"
        return self._request_json_url(method=method, url=url, payload=payload)

    def extract_person(
        self,
        image_path: str,
        person_prompt: str = "提取图像中的人物",
        n: int = 1,
        negative_prompt: str = "低质量",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        从源图像中提取人物元素
        
        Args:
            image_path: 源图像路径
            person_prompt: 人物提取提示词
            n: 生成图片数量
            negative_prompt: 负向提示词
            prompt_extend: 是否扩展提示词
            watermark: 是否添加水印
        
        Returns:
            GenerationResult: 包含提取后的人物图像URL
        """
        with open(image_path, "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/png;base64,{image_data}"
                            },
                            {
                                "text": person_prompt
                            }
                        ]
                    }
                ]
            },
            "parameters": {
                "n": n,
                "negative_prompt": negative_prompt,
                "prompt_extend": prompt_extend,
                "watermark": watermark
            }
        }
        
        try:
            result = self._make_request("services/aigc/multimodal-generation/generation", payload)
            
            if "output" in result and "choices" in result["output"] and len(result["output"]["choices"]) > 0:
                image_urls = []
                for choice in result["output"]["choices"]:
                    if "message" in choice and "content" in choice["message"]:
                        for content_item in choice["message"]["content"]:
                            if "image" in content_item:
                                image_urls.append(content_item["image"])
                
                if image_urls:
                    return GenerationResult(
                        success=True,
                        data={"image_url": image_urls[0], "image_urls": image_urls},
                        metadata={
                            "person_prompt": person_prompt,
                            "n": n,
                            "model": self.config.model_name
                        }
                    )
            
            return GenerationResult(
                success=False,
                data=None,
                error=f"No person extraction result returned. API response: {result}"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )

    def match_scene(
        self,
        person_image_path: str,
        target_scene_path: str,
        scene_prompt: str = "将人物融合到目标场景中，保持光照和视角一致",
        n: int = 1,
        negative_prompt: str = "低质量",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        将人物与目标场景匹配，确保光照、视角一致
        
        Args:
            person_image_path: 人物图像路径
            target_scene_path: 目标场景图像路径
            scene_prompt: 场景匹配提示词
            n: 生成图片数量
            negative_prompt: 负向提示词
            prompt_extend: 是否扩展提示词
            watermark: 是否添加水印
        
        Returns:
            GenerationResult: 包含匹配后的图像URL
        """
        import base64
        
        with open(person_image_path, "rb") as f:
            person_data = base64.b64encode(f.read()).decode()
        
        with open(target_scene_path, "rb") as f:
            scene_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/png;base64,{person_data}"
                            },
                            {
                                "image": f"data:image/png;base64,{scene_data}"
                            },
                            {
                                "text": scene_prompt
                            }
                        ]
                    }
                ]
            },
            "parameters": {
                "n": n,
                "negative_prompt": negative_prompt,
                "prompt_extend": prompt_extend,
                "watermark": watermark
            }
        }
        
        try:
            result = self._make_request("services/aigc/multimodal-generation/generation", payload)
            
            if "output" in result and "choices" in result["output"] and len(result["output"]["choices"]) > 0:
                image_urls = []
                for choice in result["output"]["choices"]:
                    if "message" in choice and "content" in choice["message"]:
                        for content_item in choice["message"]["content"]:
                            if "image" in content_item:
                                image_urls.append(content_item["image"])
                
                if image_urls:
                    return GenerationResult(
                        success=True,
                        data={"image_url": image_urls[0], "image_urls": image_urls},
                        metadata={
                            "scene_prompt": scene_prompt,
                            "n": n,
                            "model": self.config.model_name
                        }
                    )
            
            return GenerationResult(
                success=False,
                data=None,
                error=f"No scene matching result returned. API response: {result}"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )

    def fuse_multiple_persons(
        self,
        person_images: List[str],
        target_scene_path: str,
        fusion_prompt: str = "将多个人物自然地融合到同一场景中，保持人物一致性和场景协调",
        layout_description: Optional[str] = None,
        n: int = 1,
        negative_prompt: str = "低质量",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        将多个人物融合到同一场景中
        
        Args:
            person_images: 多个人物图像路径列表
            target_scene_path: 目标场景图像路径
            fusion_prompt: 融合提示词
            layout_description: 布局描述（可选，用于指定人物在场景中的位置）
            n: 生成图片数量
            negative_prompt: 负向提示词
            prompt_extend: 是否扩展提示词
            watermark: 是否添加水印
        
        Returns:
            GenerationResult: 包含融合后的图像URL
        """
        import base64
        
        if len(person_images) == 0:
            return GenerationResult(
                success=False,
                data=None,
                error="No person images provided"
            )
        
        enhanced_prompt = fusion_prompt
        if layout_description:
            enhanced_prompt = f"{fusion_prompt}\n布局要求：{layout_description}"
        
        if len(person_images) == 1:
            return self.match_scene(
                person_image_path=person_images[0],
                target_scene_path=target_scene_path,
                scene_prompt=enhanced_prompt,
                n=n,
                negative_prompt=negative_prompt,
                prompt_extend=prompt_extend,
                watermark=watermark
            )
        else:
            return GenerationResult(
                success=False,
                data=None,
                error=f"Multi-person fusion with {len(person_images)} persons is not supported. Please use single person fusion iteratively."
            )

    def adjust_lighting(
        self,
        image_path: str,
        lighting_prompt: str,
        n: int = 1,
        negative_prompt: str = "低质量",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        调整图像的光照效果
        
        Args:
            image_path: 图像路径
            lighting_prompt: 光照调整提示词（如"添加柔和的侧光"、"增强自然光"等）
            n: 生成图片数量
            negative_prompt: 负向提示词
            prompt_extend: 是否扩展提示词
            watermark: 是否添加水印
        
        Returns:
            GenerationResult: 包含调整后的图像URL
        """
        with open(image_path, "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": f"data:image/png;base64,{image_data}"
                            },
                            {
                                "text": lighting_prompt
                            }
                        ]
                    }
                ]
            },
            "parameters": {
                "n": n,
                "negative_prompt": negative_prompt,
                "prompt_extend": prompt_extend,
                "watermark": watermark
            }
        }
        
        try:
            result = self._make_request("services/aigc/multimodal-generation/generation", payload)
            
            if "output" in result and "choices" in result["output"] and len(result["output"]["choices"]) > 0:
                image_urls = []
                for choice in result["output"]["choices"]:
                    if "message" in choice and "content" in choice["message"]:
                        for content_item in choice["message"]["content"]:
                            if "image" in content_item:
                                image_urls.append(content_item["image"])
                
                if image_urls:
                    return GenerationResult(
                        success=True,
                        data={"image_url": image_urls[0], "image_urls": image_urls},
                        metadata={
                            "lighting_prompt": lighting_prompt,
                            "n": n,
                            "model": self.config.model_name
                        }
                    )
            
            return GenerationResult(
                success=False,
                data=None,
                error=f"No lighting adjustment result returned. API response: {result}"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )

    def generate(
        self,
        operation: str,
        **kwargs
    ) -> GenerationResult:
        """
        统一的生成接口，根据operation类型调用不同的功能
        
        Args:
            operation: 操作类型 (extract_person, match_scene, fuse_multiple_persons, adjust_lighting)
            **kwargs: 操作相关的参数
        
        Returns:
            GenerationResult: 操作结果
        """
        if operation == "extract_person":
            return self.extract_person(
                image_path=kwargs.get("image_path"),
                person_prompt=kwargs.get("person_prompt", "提取图像中的人物"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "低质量"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "match_scene":
            return self.match_scene(
                person_image_path=kwargs.get("person_image_path"),
                target_scene_path=kwargs.get("target_scene_path"),
                scene_prompt=kwargs.get("scene_prompt", "将人物融合到目标场景中，保持光照和视角一致"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "低质量"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "fuse_multiple_persons":
            return self.fuse_multiple_persons(
                person_images=kwargs.get("person_images", []),
                target_scene_path=kwargs.get("target_scene_path"),
                fusion_prompt=kwargs.get("fusion_prompt", "将多个人物自然地融合到同一场景中，保持人物一致性和场景协调"),
                layout_description=kwargs.get("layout_description"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "低质量"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "adjust_lighting":
            return self.adjust_lighting(
                image_path=kwargs.get("image_path"),
                lighting_prompt=kwargs.get("lighting_prompt"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "低质量"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        else:
            return GenerationResult(
                success=False,
                data=None,
                error=f"Unknown operation: {operation}"
            )


class Qwen3VLPlusAdapter(BaseModelAdapter):
    """Qwen3-VL-Plus 适配器 - 图片与视频理解（质量评估）"""

    def generate(self, **kwargs) -> GenerationResult:  # noqa: ANN003
        """
        兼容 BaseModelAdapter 抽象接口：
        - analyze_image: 传入 image_path
        - analyze_video: 传入 video_path
        - chat: 传入 messages
        """
        if "messages" in kwargs:
            return self.chat(
                messages=kwargs.get("messages"),
                temperature=kwargs.get("temperature", 0.2),
                max_tokens=kwargs.get("max_tokens"),
                response_format=kwargs.get("response_format"),
            )
        if "image_path" in kwargs:
            return self.analyze_image(
                image_path=str(kwargs.get("image_path") or ""),
                analysis_type=str(kwargs.get("analysis_type") or "quality"),
                criteria=kwargs.get("criteria"),
            )
        if "video_path" in kwargs:
            return self.analyze_video(
                video_path=str(kwargs.get("video_path") or ""),
                analysis_type=str(kwargs.get("analysis_type") or "quality"),
                criteria=kwargs.get("criteria"),
            )
        return GenerationResult(success=False, data=None, error="Unsupported operation for Qwen3VLPlusAdapter")

    def chat(
        self,
        *,
        messages: Any,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        OpenAI-Compatible Chat Completions（用于多模态评选/参考选择）。

        注意：message schema 由调用方保证（role/content），content 可为纯文本或多模态数组。
        """
        if not isinstance(messages, list):
            return GenerationResult(success=False, data=None, error="messages must be a list")

        payload: Dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": float(temperature),
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if isinstance(response_format, dict):
            payload["response_format"] = response_format

        try:
            result = self._make_request("v1/chat/completions", payload)
            content = ""
            if isinstance(result, dict):
                choices = result.get("choices")
                if isinstance(choices, list) and choices:
                    choice0 = choices[0] if isinstance(choices[0], dict) else None
                    message = choice0.get("message") if isinstance(choice0, dict) else None
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        content = message["content"]

            return GenerationResult(
                success=True,
                data={"content": content, "raw": result},
                metadata={"model": self.config.model_name},
            )
        except Exception as e:
            return GenerationResult(success=False, data=None, error=str(e))

    def analyze_image(
        self,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None
    ) -> GenerationResult:
        """分析图像质量"""
        with open(image_path, "rb") as f:
            import base64
            image_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "image": image_data,
            "analysis_type": analysis_type,
            "criteria": criteria or ["clarity", "composition", "lighting", "color", "style"]
        }
        
        try:
            result = self._make_request("v1/analyze/image", payload)
            
            return GenerationResult(
                success=True,
                data=result.get("analysis", {}),
                metadata={
                    "image_path": image_path,
                    "analysis_type": analysis_type,
                    "model": self.config.model_name
                }
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )

    def analyze_video(
        self,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None
    ) -> GenerationResult:
        """分析视频质量"""
        with open(video_path, "rb") as f:
            import base64
            video_data = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": self.config.model_name,
            "video": video_data,
            "analysis_type": analysis_type,
            "criteria": criteria or ["clarity", "smoothness", "consistency", "lighting", "color"]
        }
        
        try:
            result = self._make_request("v1/analyze/video", payload)
            
            return GenerationResult(
                success=True,
                data=result.get("analysis", {}),
                metadata={
                    "video_path": video_path,
                    "analysis_type": analysis_type,
                    "model": self.config.model_name
                }
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class Qwen3TTSAdapter(BaseModelAdapter):
    """Qwen3-TTS 适配器 - 文本转语音（用于声画同步）"""

    def generate(
        self,
        text: str,
        voice_style: str = "natural",
        character_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0
    ) -> GenerationResult:
        """
        生成语音（文本转语音）
        
        Args:
            text: 要转换的文本
            voice_style: 语音风格（natural/emotional/humorous等）
            character_id: 角色ID（用于音色匹配）
            speed: 语速（0.5-2.0）
            pitch: 音调（0.5-2.0）
            volume: 音量（0.0-1.0）
        
        Returns:
            GenerationResult: 包含生成的音频数据（base64编码）
        """
        if not text or not text.strip():
            return GenerationResult(
                success=False,
                data=None,
                error="Text is required for TTS"
            )
        
        payload = {
            "model": self.config.model_name,
            "text": text.strip(),
            "voice_style": voice_style,
            "speed": max(0.5, min(2.0, float(speed))),
            "pitch": max(0.5, min(2.0, float(pitch))),
            "volume": max(0.0, min(1.0, float(volume)))
        }
        
        if character_id:
            payload["character_id"] = character_id
        
        try:
            if self._is_dashscope():
                result = self._dashscope_tts(payload)
            else:
                result = self._make_request("v1/audio/speech", payload)
            
            if result and "data" in result:
                audio_data = result["data"].get("audio_data")
                if audio_data:
                    return GenerationResult(
                        success=True,
                        data={"audio_data": audio_data, "format": "mp3"},
                        metadata={
                            "text": text,
                            "voice_style": voice_style,
                            "character_id": character_id,
                            "model": self.config.model_name
                        }
                    )
            
            return GenerationResult(
                success=False,
                data=None,
                error=f"TTS generation failed: {result}"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )
    
    def _dashscope_tts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        使用DashScope原生API进行文本转语音
        """
        dashscope_payload = {
            "model": self.config.model_name,
            "input": {
                "text": payload["text"]
            },
            "parameters": {
                "voice_style": payload["voice_style"],
                "speed": payload["speed"],
                "pitch": payload["pitch"],
                "volume": payload["volume"]
            }
        }
        
        if "character_id" in payload:
            dashscope_payload["parameters"]["character_id"] = payload["character_id"]
        
        base_host = self._base_host()
        if not base_host:
            base_host = "https://dashscope.aliyuncs.com"
        
        url = f"{base_host}/api/v1/services/aigc/text2audio/generation"
        
        result = self._request_json_url(method="POST", url=url, payload=dashscope_payload)

        if "output" in result and "audio" in result["output"]:
            return {
                "data": {
                    "audio_data": result["output"]["audio"]
                }
            }

        return result


class JianyingAPIAdapter(BaseModelAdapter):
    """剪影API适配器 - 视频编辑"""

    def generate(
        self,
        video_paths: List[str],
        output_path: str,
        transitions: Optional[List[Dict[str, Any]]] = None,
        audio_path: Optional[str] = None,
        subtitles: Optional[List[Dict[str, Any]]] = None,
        effects: Optional[List[Dict[str, Any]]] = None
    ) -> GenerationResult:
        """编辑视频"""
        # 读取所有视频文件
        videos_data = []
        for video_path in video_paths:
            with open(video_path, "rb") as f:
                import base64
                videos_data.append(base64.b64encode(f.read()).decode())
        
        payload = {
            "model": self.config.model_name,
            "videos": videos_data,
            "transitions": transitions or [],
            "subtitles": subtitles or [],
            "effects": effects or [],
        }
        
        if audio_path:
            with open(audio_path, "rb") as f:
                import base64
                payload["audio"] = base64.b64encode(f.read()).decode()
        
        try:
            result = self._make_request("v1/videos/edit", payload)
            
            if "data" in result:
                # 保存编辑后的视频
                video_url = result["data"].get("video_url")
                if video_url:
                    # 下载视频到指定路径
                    response = requests.get(video_url, timeout=60)
                    response.raise_for_status()
                    
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    
                    return GenerationResult(
                        success=True,
                        data={"output_path": output_path},
                        metadata={
                            "input_videos": len(video_paths),
                            "output_path": output_path,
                            "model": self.config.model_name
                        }
                    )
            
            return GenerationResult(
                success=False,
                data=None,
                error="Video editing failed"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class ModelAdapterFactory:
    """模型适配器工厂"""

    def __init__(self) -> None:
        self._cache: Dict[str, BaseModelAdapter] = {}

    @staticmethod
    def create_adapter(
        adapter_type: str,
        config: ModelConfig
    ) -> BaseModelAdapter:
        """创建适配器实例"""
        adapters = {
            "wan26_t2i": Wan26T2IAdapter,
            "wan26_i2v": Wan26I2VAdapter,
            "wan26_t2v": Wan26T2VAdapter,
            "wan26_r2v": Wan26R2VAdapter,
            "wan_image_edit": WanImageEditAdapter,
            "qwen_image_edit_plus": QwenImageEditPlusAdapter,
            "qwen_multiperson_fusion": QwenMultiPersonFusionAdapter,
            "qwen3_vl_plus": Qwen3VLPlusAdapter,
            "qwen3_tts": Qwen3TTSAdapter,
            "jianying": JianyingAPIAdapter,
        }
        
        adapter_class = adapters.get(adapter_type)
        if not adapter_class:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        
        return adapter_class(config)

    def get_adapter(self, name: str) -> BaseModelAdapter:
        """
        从环境变量加载配置并获取模型适配器实例。

        支持别名（便于 Agent 层复用）：
        - wan_t2i / wan26_t2i
        - wan_i2v / wan26_i2v
        - wan_t2v / wan26_t2v
        - wan_r2v / wan26_r2v
        - wan_image_edit
        - qwen_image_edit_plus
        - qwen3_vl_plus
        - qwen3_tts
        - jianying
        """
        key = (name or "").strip().lower()
        if not key:
            raise ValueError("adapter name is required")

        if key in self._cache:
            return self._cache[key]

        alias_map = {
            "wan_t2i": "wan26_t2i",
            "wan_i2v": "wan26_i2v",
            "wan_t2v": "wan26_t2v",
            "wan_r2v": "wan26_r2v",
        }
        adapter_type = alias_map.get(key, key)

        env_prefix_map = {
            "wan26_t2i": "WAN_T2I",
            "wan26_i2v": "WAN_I2V",
            "wan26_t2v": "WAN_T2V",
            "wan26_r2v": "WAN_R2V",
            "wan_image_edit": "WAN_IMAGE_EDIT",
            "qwen_image_edit_plus": "QWEN_IMAGE_EDIT",
            "qwen_multiperson_fusion": "QWEN_IMAGE_EDIT",
            "qwen3_vl_plus": "QWEN_VL_PLUS",
            "qwen3_tts": "QWEN3_TTS",
            "jianying": "JIANYING",
        }
        env_prefix = env_prefix_map.get(adapter_type)
        if not env_prefix:
            raise ValueError(f"Unknown adapter type: {key}")

        api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
        base_url = os.getenv(f"{env_prefix}_BASE_URL", "").strip()
        model_name = (
            os.getenv(f"{env_prefix}_MODEL_NAME", "").strip()
            or os.getenv(f"{env_prefix}_MODEL_ID", "").strip()
            or os.getenv(f"{env_prefix}_MODEL", "").strip()
        )

        if not api_key or not base_url:
            raise RuntimeError(
                f"Missing {env_prefix} config: require {env_prefix}_API_KEY and {env_prefix}_BASE_URL"
            )

        if not model_name:
            # 兼容：部分 OpenAI-Compatible 网关在配置中只需要 API_KEY/BASE_URL
            # 默认值仅用于 Qwen 系列，避免影响 Wan/Jianying 等显式依赖 model_id 的链路。
            if env_prefix == "QWEN_VL_PLUS":
                model_name = "qwen3-vl-plus"
            elif env_prefix == "QWEN_IMAGE_EDIT":
                model_name = "qwen-image-edit-plus"

        if not model_name and adapter_type != "jianying":
            raise RuntimeError(
                f"Missing {env_prefix} model: set {env_prefix}_MODEL_NAME (or {env_prefix}_MODEL_ID)"
            )

        if adapter_type == "jianying" and not model_name:
            model_name = "jianying"

        default_timeout_s = 60
        if env_prefix in {"WAN_I2V", "WAN_T2V", "WAN_R2V"}:
            default_timeout_s = 600
        timeout = int(os.getenv(f"{env_prefix}_TIMEOUT", str(default_timeout_s)) or str(default_timeout_s))
        max_retries = int(os.getenv(f"{env_prefix}_MAX_RETRIES", "3") or "3")

        def _optional_int(var_name: str) -> Optional[int]:
            raw = os.getenv(var_name)
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                return None
            try:
                return int(raw)
            except Exception:  # noqa: BLE001
                return None

        max_requests_per_minute = _optional_int(f"{env_prefix}_MAX_REQUESTS_PER_MINUTE")
        max_requests_per_day = _optional_int(f"{env_prefix}_MAX_REQUESTS_PER_DAY")

        adapter = self.create_adapter(
            adapter_type=adapter_type,
            config=ModelConfig(
                api_key=api_key,
                base_url=base_url.rstrip("/"),
                model_name=model_name,
                timeout=timeout,
                max_retries=max_retries,
                max_requests_per_minute=max_requests_per_minute,
                max_requests_per_day=max_requests_per_day,
                rate_limit_key=env_prefix,
            ),
        )

        self._cache[key] = adapter
        return adapter
