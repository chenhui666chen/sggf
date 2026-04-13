# -*- coding: utf-8 -*-
"""
忙篓隆氓??茅??茅??氓?篓氓卤? - 忙?炉忙??氓陇?莽搂? AI 忙篓隆氓??莽??莽禄?盲赂?忙?楼氓?拢茫??
盲赂?盲戮?猫碌?ComfyUI/LoRA茂录?忙??芒??猫?陆氓??盲戮?氓潞?氓??芒??忙?陆猫卤隆茅??茅??茫??"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import time
import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests

from adapters.rate_limiter import get_rate_limiter


@dataclass
class ModelConfig:
    """忙篓隆氓??茅??莽陆庐"""
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
    """莽??忙??莽禄?忙??"""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    cost: float = 0.0


def _wrapper_result_to_generation_result(result: Any) -> "GenerationResult":
    metadata = dict(getattr(result, "metadata", {}) or {})
    data = getattr(result, "data", None)
    if data is None and "result_data" in metadata:
        data = metadata.pop("result_data")
    return GenerationResult(
        success=bool(getattr(result, "success", False)),
        data=data,
        error=getattr(result, "error", None),
        metadata=metadata,
        cost=float(getattr(result, "cost", 0.0) or 0.0),
    )


def _delegate_to_runtime_wrapper(
    config: ModelConfig,
    wrapper_name: str,
    method_name: str,
    *args: Any,
    **kwargs: Any,
) -> "GenerationResult":
    from adapters.legacy_runtime_wrappers import create_runtime_wrapper

    wrapper = create_runtime_wrapper(wrapper_name, config)
    if wrapper is None:
        return GenerationResult(
            success=False,
            data=None,
            error=f"Runtime wrapper not available for {wrapper_name}",
        )

    try:
        method = getattr(wrapper, method_name, None)
        if not callable(method):
            return GenerationResult(
                success=False,
                data=None,
                error=f"Method {method_name} not available for {wrapper_name}",
            )
        return _wrapper_result_to_generation_result(method(*args, **kwargs))
    finally:
        close = getattr(wrapper, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


def _normalize_legacy_tts_speaker_id(speaker_id: str) -> str:
    value = str(speaker_id or "").strip()
    if not value:
        return ""

    try:
        from backend.app.services.audiobook.constants import normalize_speaker_id

        return str(normalize_speaker_id(value))
    except Exception:
        pass

    constants_path = Path(__file__).resolve().parents[1] / "backend" / "app" / "services" / "audiobook" / "constants.py"
    if not constants_path.exists():
        return value

    try:
        spec = importlib.util.spec_from_file_location("audiobook_constants_fallback", constants_path)
        if spec is None or spec.loader is None:
            return value
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        normalize_speaker_id = getattr(module, "normalize_speaker_id", None)
        if callable(normalize_speaker_id):
            return str(normalize_speaker_id(value))
    except Exception:
        return value
    return value


class BaseModelAdapter(ABC):
    """Base model adapter."""
    RUNTIME_WRAPPER_NAME = ""

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

    def _delegate_runtime(self, method_name: str, *args: Any, **kwargs: Any) -> "GenerationResult":
        wrapper_name = str(getattr(self, "RUNTIME_WRAPPER_NAME", "") or "").strip()
        if not wrapper_name:
            return GenerationResult(
                success=False,
                data=None,
                error=f"Runtime wrapper name not configured for {self.__class__.__name__}",
            )
        return _delegate_to_runtime_wrapper(self.config, wrapper_name, method_name, *args, **kwargs)

    def _base_host(self) -> str:
        """
        盲禄?base_url 忙??氓?? scheme://netloc茂录?莽?篓盲潞?忙??盲潞?氓??氓??忙??盲赂?氓??猫?陆氓??忙??氓?篓盲赂?氓?? path 盲赂?莽??氓?潞忙?炉茂录?茫??        盲戮?氓娄?茂录?https://dashscope.aliyuncs.com/compatible-mode/v1 -> https://dashscope.aliyuncs.com
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
        猫庐隆莽庐?茅??猫炉?莽颅?氓戮?忙?露茅?麓茂录?忙??忙?掳茅??茅??+ 忙??氓?篓茂录?茂录?猫?楼氓??氓潞?氓??氓??Retry-After茂录?莽搂?茂录?茂录?氓??盲录?氓??盲陆驴莽?篓猫炉楼氓?录茫??        """
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
        requests 莽??HTTPError 茅禄?猫庐陇盲赂?氓??氓?芦氓??氓潞?盲陆?莽禄?猫??茂录?猫驴?茅??氓掳?猫炉?忙??氓??氓赂赂猫搂?茅??猫炉炉氓颅?忙庐碌氓鹿露忙?录氓?掳 message 茅??茂录?盲戮驴盲潞?忙??茅??茫??        忙鲁篓忙??茂录?盲禄?盲驴?忙??氓录?氓赂赂莽卤禄氓??盲赂?HTTPError茂录?茅?驴氓??莽聽麓氓??盲赂?氓卤?氓炉鹿 status_code 莽??氓??忙?炉茅?禄猫戮?茂录?氓娄? 404 氓??茅??茂录?茫??        """
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

    def _dashscope_error_fields(self, response: Any) -> Tuple[str, str, str]:
        code = ""
        message = ""
        request_id = ""
        if not isinstance(response, requests.Response):
            return code, message, request_id

        try:
            payload = response.json()
            if isinstance(payload, dict):
                code_raw = payload.get("code")
                if isinstance(code_raw, str):
                    code = code_raw.strip()
                message_raw = payload.get("message")
                if isinstance(message_raw, str):
                    message = message_raw.strip()
                request_raw = payload.get("request_id") or payload.get("requestId")
                if isinstance(request_raw, str):
                    request_id = request_raw.strip()
                err = payload.get("error")
                if isinstance(err, dict):
                    err_code = err.get("code")
                    err_message = err.get("message") or err.get("msg")
                    if not code and isinstance(err_code, str):
                        code = err_code.strip()
                    if not message and isinstance(err_message, str):
                        message = err_message.strip()
                elif not message and isinstance(err, str):
                    message = err.strip()
        except Exception:  # noqa: BLE001
            pass

        if not message:
            try:
                text = (response.text or "").strip()
                if text:
                    message = text[:500]
            except Exception:  # noqa: BLE001
                pass
        return code, message, request_id

    def _is_dashscope_data_inspection_failed(self, *, response: Any = None, error_text: str = "") -> bool:
        if not self._is_dashscope():
            return False
        code, message, _ = self._dashscope_error_fields(response)
        text = " ".join(
            [
                str(code or ""),
                str(message or ""),
                str(error_text or ""),
            ]
        ).lower()
        return (
            "datainspectionfailed" in text
            or "inappropriate content" in text
            or "content check failed" in text
        )

    def _normalize_safety_strategy(self, raw: str) -> str:
        value = (raw or "").strip().lower()
        if value in {"off", "none", "disable", "false", "0"}:
            return ""
        if value in {"conservative", "moderate", "aggressive"}:
            return value
        return "moderate"

    def _sanitize_payload_prompt_fields(
        self,
        payload: Dict[str, Any],
        *,
        strategy: str,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        try:
            from adapters.content_safety_checker import check_and_fix_prompt
        except Exception:  # noqa: BLE001
            return None, {"strategy": strategy, "changed_fields": 0, "issues": 0, "field_paths": []}

        target_keys = {"text", "prompt", "edit_prompt", "negative_prompt"}
        patched: Dict[str, Any] = copy.deepcopy(payload)
        changed_fields = 0
        issue_count = 0
        field_paths: List[str] = []

        def _walk(node: Any, path: str) -> None:
            nonlocal changed_fields, issue_count
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    child_path = f"{path}.{key}" if path else str(key)
                    if key in target_keys and isinstance(value, str) and value.strip():
                        fixed, issues, _ = check_and_fix_prompt(value, strategy=strategy)
                        if isinstance(issues, list):
                            issue_count += len(issues)
                        if isinstance(fixed, str) and fixed and fixed != value:
                            node[key] = fixed
                            changed_fields += 1
                            field_paths.append(child_path)
                    else:
                        _walk(value, child_path)
                return

            if isinstance(node, list):
                for idx, item in enumerate(node):
                    _walk(item, f"{path}[{idx}]")

        _walk(patched, "")
        meta: Dict[str, Any] = {
            "strategy": strategy,
            "changed_fields": int(changed_fields),
            "issues": int(issue_count),
            "field_paths": field_paths[:20],
        }
        if changed_fields <= 0:
            return None, meta
        return patched, meta

    def _request_json_url(self, *, method: str, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        retries = int(getattr(self.config, "max_retries", 1) or 1)
        if retries <= 0:
            retries = 1

        last_exc: Optional[Exception] = None
        request_payload: Dict[str, Any] = payload
        safety_retry_used = False
        safety_retry_meta: Dict[str, Any] = {}
        for attempt in range(retries):
            try:
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                response = self.session.request(
                    str(method or "POST"),
                    str(url),
                    json=request_payload,
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
                    raise ValueError(f"response is not valid JSON (url={url}): {snippet}") from exc
            except requests.exceptions.HTTPError as exc:
                last_exc = exc
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if (
                    int(status or 0) == 400
                    and self._is_dashscope_data_inspection_failed(response=response, error_text=str(exc))
                    and not safety_retry_used
                ):
                    preferred = self._normalize_safety_strategy(os.getenv("DREAMWEAVER_SAFETY_STRATEGY", "moderate"))
                    strategies: List[str] = []
                    if preferred:
                        strategies.append(preferred)
                    if "aggressive" not in strategies:
                        strategies.append("aggressive")
                    for strategy in strategies:
                        patched_payload, meta = self._sanitize_payload_prompt_fields(
                            request_payload,
                            strategy=strategy,
                        )
                        if patched_payload is None:
                            continue
                        request_payload = patched_payload
                        safety_retry_used = True
                        safety_retry_meta = meta
                        print(
                            f"[warn] DashScope content check blocked, retry with safety strategy={strategy}, "
                            f"changed_fields={meta.get('changed_fields', 0)}"
                        )
                        break
                    if safety_retry_used:
                        continue
                if status is not None and int(status) < 500 and int(status) != 429:
                    if int(status) == 400 and self._is_dashscope_data_inspection_failed(response=response, error_text=str(exc)):
                        extra_hint = "Input may contain inappropriate content. Please review the prompt."
                        if safety_retry_used:
                            strategy = str(safety_retry_meta.get("strategy") or "")
                            changed_fields = int(safety_retry_meta.get("changed_fields") or 0)
                            extra_hint = (
                                f"{extra_hint} Safety retry exhausted(strategy={strategy}, "
                                f"changed_fields={changed_fields})."
                            )
                        raise requests.HTTPError(f"{str(exc)} ({extra_hint})", response=response) from exc
                    raise
                if attempt >= retries - 1:
                    raise
                time.sleep(self._retry_delay_s(attempt, response=response))
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
        """氓??茅??API猫炉路忙卤?"""
        base_url = (self.config.base_url or "").rstrip("/")
        ep = (endpoint or "").lstrip("/")
        if base_url.endswith("/v1") and ep.startswith("v1/"):
            ep = ep[len("v1/") :]
        url = f"{base_url}/{ep}"
        return self._request_json_url(method=method, url=url, payload=payload)

    @abstractmethod
    def generate(self, **kwargs) -> GenerationResult:
        """莽??忙??氓??氓庐鹿"""
        pass


class Wan26T2IAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "wan26_t2i"
    """Legacy-compatible WAN T2I adapter."""

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
        return self._delegate_runtime(
            "generate",
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
        )


class Wan26I2VAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "wan26_i2v"
    """Legacy-compatible WAN I2V adapter."""

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
        return self._delegate_runtime(
            "generate",
            image_path=image_path,
            prompt=prompt,
            duration=duration,
            fps=fps,
            motion_bucket_id=motion_bucket_id,
            seed=seed,
            character_references=character_references,
        )


class Wan26T2VAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "wan26_t2v"
    """Legacy-compatible WAN T2V adapter."""

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
        return self._delegate_runtime(
            "generate",
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
        )


class Wan26R2VAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "wan26_r2v"
    """Legacy-compatible WAN R2V adapter."""

    def generate(
        self,
        reference_video_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        seed: Optional[int] = None
    ) -> GenerationResult:
        return self._delegate_runtime(
            "generate",
            reference_video_path=reference_video_path,
            prompt=prompt,
            duration=duration,
            fps=fps,
            seed=seed,
        )


class QwenImageEditPlusAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "qwen_image_edit_plus"
    """Legacy-compatible Qwen image edit adapter."""
    supports_multi_image = True

    def generate(
        self,
        image_path: str,
        edit_prompt: str,
        mask_path: Optional[str] = None,
        strength: float = 0.8,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        image_paths: Optional[List[str]] = None
    ) -> GenerationResult:
        return self._delegate_runtime(
            "generate",
            image_path=image_path,
            edit_prompt=edit_prompt,
            mask_path=mask_path,
            strength=strength,
            guidance_scale=guidance_scale,
            seed=seed,
            image_paths=image_paths,
        )


class WanImageEditAdapter(QwenImageEditPlusAdapter):
    RUNTIME_WRAPPER_NAME = "wan_image_edit"
    """Wan Image Edit 脙漏芒?卢芒??脙垄芒?卢脗娄脙楼芒?? 脙楼芒?潞脗戮脙楼脝?脗隆脙搂脗录芒??脙篓脗戮芒??"""
    supports_multi_image = False


class QwenImageEditMaxAdapter(QwenImageEditPlusAdapter):
    RUNTIME_WRAPPER_NAME = "qwen_image_edit_max"
    """Qwen-Image-Edit-Max adapter - image edit"""


class QwenMultiPersonFusionAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "qwen_multiperson_fusion"
    """Legacy-compatible multi-person fusion adapter."""

    @staticmethod
    def _append_image_urls(result: GenerationResult) -> GenerationResult:
        if result.success and isinstance(result.data, dict):
            image_url = result.data.get("image_url")
            if isinstance(image_url, str) and image_url and "image_urls" not in result.data:
                result.data = {**result.data, "image_urls": [image_url]}
        return result

    def extract_person(
        self,
        image_path: str,
        person_prompt: str = "extract the person from the reference image",
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        del n
        del negative_prompt
        del prompt_extend
        del watermark
        result = self._delegate_runtime(
            "generate",
            image_path=image_path,
            edit_prompt=person_prompt,
        )
        return self._append_image_urls(result)

    def match_scene(
        self,
        person_image_path: str,
        target_scene_path: str,
        scene_prompt: str = "place the character naturally into the target scene with consistent lighting and perspective",
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        del n
        del negative_prompt
        del prompt_extend
        del watermark
        result = self._delegate_runtime(
            "match_scene",
            person_image_path=person_image_path,
            target_scene_path=target_scene_path,
            scene_prompt=scene_prompt,
        )
        return self._append_image_urls(result)

    def fuse_multiple_persons(
        self,
        person_images: List[str],
        target_scene_path: str,
        fusion_prompt: str = "fuse the referenced characters naturally into the target scene while keeping identity, lighting, and perspective consistent",
        layout_description: Optional[str] = None,
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        del n
        del negative_prompt
        del prompt_extend
        del watermark
        if len(person_images) == 0:
            return GenerationResult(
                success=False,
                data=None,
                error="No person images provided"
            )

        enhanced_prompt = fusion_prompt
        if layout_description:
            enhanced_prompt = f"{fusion_prompt}\n布局描述：{layout_description}"

        result = self._delegate_runtime(
            "generate",
            image_path=target_scene_path,
            edit_prompt=enhanced_prompt,
            image_paths=person_images,
        )
        return self._append_image_urls(result)

    def adjust_lighting(
        self,
        image_path: str,
        lighting_prompt: str,
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        del n
        del negative_prompt
        del prompt_extend
        del watermark
        result = self._delegate_runtime(
            "generate",
            image_path=image_path,
            edit_prompt=lighting_prompt,
        )
        return self._append_image_urls(result)

    def generate(
        self,
        operation: str,
        **kwargs
    ) -> GenerationResult:
        if operation == "extract_person":
            return self.extract_person(
                image_path=kwargs.get("image_path"),
                person_prompt=kwargs.get("person_prompt", "extract the person from the reference image"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        if operation == "match_scene":
            return self.match_scene(
                person_image_path=kwargs.get("person_image_path"),
                target_scene_path=kwargs.get("target_scene_path"),
                scene_prompt=kwargs.get("scene_prompt", "place the character naturally into the target scene with consistent lighting and perspective"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        if operation == "fuse_multiple_persons":
            return self.fuse_multiple_persons(
                person_images=kwargs.get("person_images", []),
                target_scene_path=kwargs.get("target_scene_path"),
                fusion_prompt=kwargs.get(
                    "fusion_prompt",
                    "fuse the referenced characters naturally into the target scene while keeping identity, lighting, and perspective consistent",
                ),
                layout_description=kwargs.get("layout_description"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        if operation == "adjust_lighting":
            return self.adjust_lighting(
                image_path=kwargs.get("image_path"),
                lighting_prompt=kwargs.get("lighting_prompt"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        return GenerationResult(
            success=False,
            data=None,
            error=f"Unknown operation: {operation}"
        )


class Qwen3VLPlusAdapter(BaseModelAdapter):
    RUNTIME_WRAPPER_NAME = "qwen3_vl_plus"
    """Legacy-compatible Qwen3 VL adapter."""

    def generate(self, **kwargs) -> GenerationResult:  # noqa: ANN003
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
        return self._delegate_runtime(
            "chat",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    def analyze_image(
        self,
        image_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None
    ) -> GenerationResult:
        return self._delegate_runtime(
            "analyze_image",
            image_path=image_path,
            analysis_type=analysis_type,
            criteria=criteria,
        )

    def analyze_video(
        self,
        video_path: str,
        analysis_type: str = "quality",
        criteria: Optional[List[str]] = None
    ) -> GenerationResult:
        return self._delegate_runtime(
            "analyze_video",
            video_path=video_path,
            analysis_type=analysis_type,
            criteria=criteria,
        )


class Qwen3TTSAdapter(BaseModelAdapter):
    """Qwen3-TTS 茅??茅??氓??- 忙??忙?卢猫陆卢猫炉颅茅?鲁茂录?莽?篓盲潞?氓拢掳莽?禄氓??忙颅楼茂录?"""

    def generate(
        self,
        text: str,
        voice_style: str = "natural",
        character_id: Optional[str] = None,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0
    ) -> GenerationResult:
        """
        莽??忙??猫炉颅茅?鲁茂录?忙??忙?卢猫陆卢猫炉颅茅?鲁茂录?        
        Args:
            text: 猫娄?猫陆卢忙?垄莽??忙??忙?卢
            voice_style: 猫炉颅茅?鲁茅拢?忙聽录茂录?natural/emotional/humorous莽颅?茂录?
            character_id: 猫搂?猫?虏ID茂录?莽?篓盲潞?茅?鲁猫?虏氓?鹿茅??茂录?
            voice_id: 茅?鲁猫?虏ID茂录?盲录?氓??盲陆驴莽?篓茂录?
            speed: 猫炉颅茅??茂录?0.5-2.0茂录?            pitch: 茅?鲁猫掳?茂录?.5-2.0茂录?            volume: 茅?鲁茅??茂录?.0-1.0茂录?        
        Returns:
            GenerationResult: 氓??氓?芦莽??忙??莽??茅?鲁茅垄?忙?掳忙?庐茂录?base64莽录?莽聽?茂录?        """
        if not text or not text.strip():
            return GenerationResult(
                success=False,
                data=None,
                error="Text is required for TTS"
            )

        from adapters.adapter_helpers import build_legacy_tts_request, synthesize_speech_sync

        resolved_voice_id = str(voice_id or "").strip()
        if resolved_voice_id:
            resolved_voice_id = _normalize_legacy_tts_speaker_id(resolved_voice_id)
        request = build_legacy_tts_request(
            text=text.strip(),
            voice_style=voice_style,
            character_id=character_id,
            voice_id=resolved_voice_id or None,
            speed=speed,
            pitch=pitch,
            volume=volume,
        )

        try:
            result = synthesize_speech_sync(
                text=request["text"],
                voice_params=request["voice_params"],
                emotion=request["emotion"],
                model_id=self.config.model_name,
            )

            if result.success and result.data:
                metadata = dict(getattr(result, "metadata", {}) or {})
                metadata.update(
                    {
                        "text": text,
                        "voice_style": voice_style,
                        "character_id": character_id,
                        "voice_id": resolved_voice_id,
                        "model": getattr(result, "model_id", self.config.model_name),
                    }
                )
                return GenerationResult(
                    success=True,
                    data=dict(result.data),
                    metadata=metadata,
                    cost=float(getattr(result, "cost", 0.0) or 0.0),
                )

            return GenerationResult(
                success=False,
                data=None,
                error=getattr(result, "error", None) or getattr(result, "message", None) or "TTS generation failed"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )


class JianyingAPIAdapter(BaseModelAdapter):
    """氓?陋氓陆卤API茅??茅??氓??- 猫搂?茅垄?莽录?猫戮?"""

    def generate(
        self,
        video_paths: List[str],
        output_path: str,
        transitions: Optional[List[Dict[str, Any]]] = None,
        audio_path: Optional[str] = None,
        subtitles: Optional[List[Dict[str, Any]]] = None,
        effects: Optional[List[Dict[str, Any]]] = None
    ) -> GenerationResult:
        """莽录?猫戮?猫搂?茅垄?"""
        # 猫炉禄氓??忙??忙??猫搂?茅垄?忙??盲禄?        videos_data = []
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
                # 盲驴?氓颅?莽录?猫戮?氓??莽??猫搂?茅垄?
                video_url = result["data"].get("video_url")
                if video_url:
                    # 盲赂?猫陆陆猫搂?茅垄?氓?掳忙??氓庐?猫路炉氓戮?                    response = requests.get(video_url, timeout=60)
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
    """统一模型适配器入口（兼容旧调用签名）。"""

    _KEY_ALIAS_MAP = {
        "wan_t2i": "wan26_t2i",
        "wan2.6-t2i": "wan26_t2i",
        "wan_i2v": "wan26_i2v",
        "wan_t2v": "wan26_t2v",
        "wan_r2v": "wan26_r2v",
        "wan-t2i": "wan26_t2i",
        "wan-i2v": "wan26_i2v",
        "wan-t2v": "wan26_t2v",
        "wan-r2v": "wan26_r2v",
    }
    _BRIDGE_MODEL_MAP = {
        "wan26_t2i": "wan2.6-t2i",
        "wan26_i2v": "wan2.6-i2v",
        "wan26_t2v": "wan2.6-t2v",
        "wan26_r2v": "wan2.6-r2v",
    }
    _ENV_PREFIX_MAP = {
        "wan26_t2i": "WAN_T2I",
        "wan26_i2v": "WAN_I2V",
        "wan26_t2v": "WAN_T2V",
        "wan26_r2v": "WAN_R2V",
        "wan_image_edit": "WAN_IMAGE_EDIT",
        "qwen_image_edit_plus": "QWEN_IMAGE_EDIT",
        "qwen_image_edit_max": "QWEN_IMAGE_EDIT_MAX",
        "qwen_multiperson_fusion": "QWEN_IMAGE_EDIT",
        "qwen3_vl_plus": "QWEN_VL_PLUS",
        "qwen3_tts": "QWEN3_TTS",
        "jianying": "JIANYING",
    }
    _DEFAULT_MODEL_NAME_BY_ENV = {
        "QWEN_VL_PLUS": "qwen3-vl-plus",
        "QWEN_IMAGE_EDIT": "qwen-image-edit-plus",
        "QWEN_IMAGE_EDIT_MAX": "qwen-image-edit-max-2026-01-16",
        "QWEN3_TTS": "qwen3-tts-flash",
    }

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}

    @staticmethod
    def _safe_int_env(var_name: str) -> Optional[int]:
        raw = os.getenv(var_name)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        try:
            return int(text)
        except Exception:  # noqa: BLE001
            return None

    def _normalize_key(self, name: str) -> str:
        key = str(name or "").strip().lower()
        if not key:
            raise ValueError("adapter name is required")
        return self._KEY_ALIAS_MAP.get(key, key)

    def _resolve_bridge_name(self, normalized_key: str) -> str:
        return self._BRIDGE_MODEL_MAP.get(normalized_key, normalized_key)

    def _build_bridge_kwargs(self, normalized_key: str, bridge_name: str) -> Dict[str, Any]:
        env_prefix = self._ENV_PREFIX_MAP.get(normalized_key)
        if not env_prefix:
            return {}

        api_key = os.getenv(f"{env_prefix}_API_KEY", "").strip()
        base_url = os.getenv(f"{env_prefix}_BASE_URL", "").strip()
        model_name = (
            os.getenv(f"{env_prefix}_MODEL_NAME", "").strip()
            or os.getenv(f"{env_prefix}_MODEL_ID", "").strip()
            or os.getenv(f"{env_prefix}_MODEL", "").strip()
            or self._DEFAULT_MODEL_NAME_BY_ENV.get(env_prefix, "")
            or bridge_name
        )

        if env_prefix == "QWEN_IMAGE_EDIT_MAX" and (not api_key or not base_url):
            fallback_key = os.getenv("QWEN_IMAGE_EDIT_API_KEY", "").strip()
            fallback_base = os.getenv("QWEN_IMAGE_EDIT_BASE_URL", "").strip()
            if not api_key:
                api_key = fallback_key
            if not base_url:
                base_url = fallback_base

        timeout_default = 600 if env_prefix in {"WAN_I2V", "WAN_T2V", "WAN_R2V"} else 60
        timeout = self._safe_int_env(f"{env_prefix}_TIMEOUT")
        max_retries = self._safe_int_env(f"{env_prefix}_MAX_RETRIES")

        return {
            "api_key": api_key or None,
            "base_url": base_url or None,
            "model_name": model_name or bridge_name,
            "timeout": int(timeout if timeout is not None else timeout_default),
            "max_retries": int(max_retries if max_retries is not None else 3),
        }

    def get_adapter(self, name: str) -> Any:
        normalized_key = self._normalize_key(name)
        if normalized_key in self._cache:
            return self._cache[normalized_key]

        bridge_name = self._resolve_bridge_name(normalized_key)
        if bridge_name in self._cache:
            adapter = self._cache[bridge_name]
            self._cache[normalized_key] = adapter
            return adapter

        from adapters.legacy_runtime_wrappers import create_runtime_wrapper

        kwargs = self._build_bridge_kwargs(normalized_key, bridge_name)
        runtime_wrapper = create_runtime_wrapper(normalized_key, ModelConfig(**kwargs))
        if runtime_wrapper is not None:
            self._cache[normalized_key] = runtime_wrapper
            self._cache[bridge_name] = runtime_wrapper
            return runtime_wrapper

        from adapters.legacy_bridge import ModelAdapterFactory as UnifiedFactory

        adapter = UnifiedFactory.create(bridge_name, **kwargs)
        self._cache[normalized_key] = adapter
        self._cache[bridge_name] = adapter
        return adapter
