# -*- coding: utf-8 -*-
"""
忙篓隆氓??茅??茅??氓?篓氓卤? - 忙?炉忙??氓陇?莽搂? AI 忙篓隆氓??莽??莽禄?盲赂?忙?楼氓?拢茫??
盲赂?盲戮?猫碌?ComfyUI/LoRA茂录?忙??芒??猫?陆氓??盲戮?氓潞?氓??芒??忙?陆猫卤隆茅??茅??茫??"""

from __future__ import annotations

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


class BaseModelAdapter(ABC):
    """Base model adapter."""

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
    """Wan 2.6 T2I (Text-to-Image) 茅??茅??氓??- 忙??莽??氓??"""

    def _dashscope_model_name(self) -> str:
        # 鍏煎鎺у埗鍙版暟瀛楁ā鍨婭D锛汚IGC 閫氬父闇€瑕佹ā鍨嬪悕锛堝 wanx-v1锛?        raw = str(self.config.model_name or "").strip()
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

        from adapters.content_safety_checker import check_and_fix_prompt

        raw_prompt = prompt
        safety_strategy = (os.getenv("DREAMWEAVER_SAFETY_STRATEGY") or "moderate").strip().lower()
        if safety_strategy in {"off", "none", "disable", "false", "0"}:
            safety_strategy = ""
        if safety_strategy and safety_strategy not in {"conservative", "moderate", "aggressive"}:
            safety_strategy = "moderate"

        aggressive_fallback_raw = (os.getenv("DREAMWEAVER_SAFETY_AGGRESSIVE_FALLBACK") or "true").strip().lower()
        aggressive_fallback = aggressive_fallback_raw not in {"0", "false", "off", "no"}
        aggressive_prompt: Optional[str] = None

        if safety_strategy:
            print("[content-safety] Checking T2I prompt...")
            fixed_prompt, issues, fix_description = check_and_fix_prompt(raw_prompt, strategy=safety_strategy)
            if issues:
                print(f"[content-safety][warn] {fix_description}")
                print(f"[content-safety] Original prompt: {raw_prompt}")
                print(f"[content-safety] Sanitized prompt: {fixed_prompt}")
                prompt = fixed_prompt
            else:
                print("[content-safety] Prompt passed safety precheck.")
                prompt = raw_prompt
        else:
            prompt = raw_prompt

        if aggressive_fallback:
            aggressive_fixed, _, _ = check_and_fix_prompt(raw_prompt, strategy="aggressive")
            if aggressive_fixed and aggressive_fixed != prompt:
                aggressive_prompt = aggressive_fixed

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

        prompt_candidates: List[str] = [prompt]
        if isinstance(aggressive_prompt, str) and aggressive_prompt and aggressive_prompt not in prompt_candidates:
            prompt_candidates.append(aggressive_prompt)

        sizes = _candidate_sizes(width, height)
        max_retries = 5
        final_error: Optional[str] = None

        for prompt_index, prompt_value in enumerate(prompt_candidates):
            last_error: Optional[str] = None
            safety_failed = False

            for size in sizes[:3]:
                payload: Dict[str, Any] = {
                    "model": self._dashscope_model_name(),
                    "input": {
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "text": prompt_value
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
                    retry_count = 0

                    while retry_count <= max_retries:
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

                            if status == 429:
                                if retry_count < max_retries:
                                    retry_count += 1
                                    wait_time = min(5 * (retry_count ** 1.5), 120)
                                    print(f"[warn] DashScope T2I rate limit (429), retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
                                    time.sleep(wait_time)
                                    continue
                                else:
                                    detail = _error_detail(resp_obj)
                                    last_error = f"dashscope t2i HTTP 429 (size={size}, async={async_enabled}): {detail}".strip()
                                    break
                            elif status == 403:
                                detail = _error_detail(resp_obj)
                                error_msg = detail.lower()
                                if "asynchronous" in error_msg and async_enabled:
                                    print("[warn] DashScope T2I async not supported (403), switching to sync mode...")
                                    break
                                else:
                                    last_error = f"dashscope t2i HTTP {status} (size={size}, async={async_enabled}): {detail}".strip()
                                    break
                            elif status == 400:
                                detail = _error_detail(resp_obj)
                                detail_lower = detail.lower()
                                error_msg = detail.lower()
                                if "datainspectionfailed" in detail_lower or "inappropriate content" in error_msg:
                                    print("[warn] DashScope T2I content check failed (400): Input may contain inappropriate content")
                                    print("   Please review and modify your prompt to comply with content policies")
                                    last_error = "dashscope t2i HTTP 400 (DataInspectionFailed): Input may contain inappropriate content. Please review and modify your prompt."
                                    safety_failed = True
                                else:
                                    last_error = f"dashscope t2i HTTP {status} (size={size}, async={async_enabled}): {detail}".strip()
                                break
                            else:
                                detail = _error_detail(resp_obj)
                                last_error = f"dashscope t2i HTTP {status} (size={size}, async={async_enabled}): {detail}".strip()
                                break
                        except Exception as exc:  # noqa: BLE001
                            if retry_count < max_retries and "timeout" in str(exc).lower():
                                retry_count += 1
                                time.sleep(5)
                                continue
                            last_error = f"dashscope t2i error (size={size}, async={async_enabled}): {str(exc)}"
                            break

                    if last_error:
                        break
                if safety_failed or last_error:
                    break

            if safety_failed and prompt_index + 1 < len(prompt_candidates):
                final_error = last_error
                print("[content-safety][retry] Safety policy triggered; retrying with aggressive prompt sanitization...")
                continue

            if last_error:
                final_error = last_error
                break

        raise RuntimeError(final_error or "dashscope t2i request failed")

    def _dashscope_poll_task(self, *, task_id: str) -> Dict[str, Any]:
        host = self._base_host()
        if not host:
            raise RuntimeError("dashscope host missing from WAN_T2I_BASE_URL")
        url = f"{host}/api/v1/tasks/{task_id}"
        # DashScope 莽??AIGC 忙?楼氓?拢茅??氓赂赂猫驴?氓??氓录?忙颅楼 task_id茂录?忙??茅??+ 莽??忙??氓?炉猫?陆猫驴?猫露?氓??忙卢隆 HTTP 猫露?忙?露茫??        # 氓?聽忙颅陇猫驴?茅??氓掳?芒??猫陆庐猫炉垄忙?禄忙?露茅?驴芒??盲赂?芒??氓??忙卢隆猫炉路忙卤?猫露?忙?露芒??氓??莽娄禄茂录?茅?驴氓??莽麓聽忙??莽??忙??茅?露忙庐碌氓?聽莽?颅 timeout 猫炉炉氓?陇氓陇卤猫麓楼茫??        #
        # 氓?炉茅??猫驴?盲禄楼盲赂?莽?炉氓垄?氓??茅??猫娄?莽??茂录?氓??盲陆?莽搂?茂录?茂录?
        # - WAN_T2I_TASK_TIMEOUT茂录?猫陆庐猫炉垄忙?禄忙?露茅?驴茂录?茅禄?猫庐陇 1800茂录?        # - WAN_T2I_POLL_HTTP_TIMEOUT茂录?猫陆庐猫炉垄忙?楼氓?拢氓??忙卢隆猫炉路忙卤?猫露?忙?露茂录?茅禄?猫庐陇 min(WAN_T2I_TIMEOUT, 15)茂录?        # - WAN_T2I_POLL_INTERVAL_S茂录?猫陆庐猫炉垄茅?麓茅??茂录?茅禄?猫庐陇 2茂录?        
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
        poll_retry_count = 0
        max_poll_retries = 5
        
        while time.time() < deadline:
            try:
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                resp = self.session.get(url, timeout=poll_http_timeout_s)
                resp.raise_for_status()
                payload = resp.json()
                poll_retry_count = 0
            except requests.exceptions.HTTPError as exc:
                resp_obj = getattr(exc, "response", None)
                status = getattr(getattr(exc, "response", None), "status_code", None)
                
                if status == 429:
                    if poll_retry_count < max_poll_retries:
                        poll_retry_count += 1
                        wait_time = min(5 * (poll_retry_count ** 1.5), 120)
                        print(f"[warn] DashScope task poll rate limit (429), retry {poll_retry_count}/{max_poll_retries}, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        last_error = f"dashscope task poll HTTP 429: task_id={task_id}"
                        time.sleep(poll_interval_s)
                        continue
                else:
                    last_error = str(exc)
                    time.sleep(poll_interval_s)
                    continue
            except Exception as exc:  # noqa: BLE001
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
        """莽??忙??氓?戮氓??"""
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
            # DashScope 莽??OpenAI Compatible 莽?庐氓??氓?炉猫?陆盲赂?忙?炉忙??images/generations茂录?            # 猫驴?茅??猫?陋氓?篓氓??忙?垄氓?掳氓庐?忙??AIGC Text2Image 忙?楼氓?拢茂录?氓掳陆茅??盲赂?猫娄?忙卤?莽?篓忙?路忙?鹿茅??莽陆庐茫??            
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
    """Wan 2.6 I2V (Image-to-Video) 茅??茅??氓??- 氓?戮莽??猫搂?茅垄?"""

    def _dashscope_model_name(self) -> str:
        # 鍏煎鎺у埗鍙版暟瀛楁ā鍨婭D锛汭2V 鎺ュ彛閫氬父闇€瑕佹ā鍨嬪悕锛堝 wan2.6-i2v锛?        raw = str(self.config.model_name or "").strip()
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
        DashScope 鹿脵路陆 AIGC 脢脫脝碌陆脫驴脷拢篓api/v1/services/aigc/video-generation/video-synthesis拢漏隆拢
        脣碌脙梅拢潞
        - compatible-mode/v1 脛驴脟掳虏禄卤拢脰陇脰搂鲁脰 v1/videos/i2v拢禄脮芒脌茂脫脜脧脠脢鹿脫脙鹿脵路陆 VideoSynthesis拢篓SDK拢漏拢卢卤脺脙芒隆掳碌梅脫脙鲁脡鹿娄碌芦脦脼 video_url隆卤碌录脰脗碌脛戮虏脤卢禄脙碌脝脝卢禄脴脥脣隆拢
        - 鹿脵路陆陆脫驴脷虏脦脢媒脧脿露脭脢脮脕虏拢潞脰脴碌茫麓芦 size/duration/seed拢卢卤脺脙芒脳垄脠毛虏禄脠路露篓虏脦脢媒碌录脰脗 4xx隆拢
        """
        try:
            import dashscope  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=f"dashscope sdk missing: {exc}")

        def _build_img_url_candidates(path_text: str) -> List[Tuple[str, str]]:
            raw = str(path_text or "").strip()
            if not raw:
                return []

            lower_raw = raw.lower()
            if lower_raw.startswith(("http://", "https://", "oss://", "data:")):
                return [("direct", raw)]

            p = Path(raw).expanduser()
            candidates: List[Tuple[str, str]] = []
            if p.exists() and p.is_file():
                try:
                    import base64

                    suffix = str(p.suffix or "").strip().lower()
                    mime = "image/png"
                    if suffix in {".jpg", ".jpeg"}:
                        mime = "image/jpeg"
                    elif suffix == ".webp":
                        mime = "image/webp"
                    elif suffix == ".bmp":
                        mime = "image/bmp"

                    encoded = base64.b64encode(p.read_bytes()).decode("utf-8")
                    candidates.append(("data_url", f"data:{mime};base64,{encoded}"))
                except Exception:
                    pass

                # 卤拢脕么卤戮碌脴脗路戮露脳梅脦陋露碌碌脳拢卢录忙脠脻 SDK 露脭脗路戮露脠毛虏脦碌脛麓娄脌铆隆拢
                candidates.append(("local_path", str(p)))
                return candidates

            return [("raw_text", raw)]

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

        from adapters.content_safety_checker import ContentSafetyChecker, check_and_fix_prompt

        print("?? [脛脷脠脻掳虏脠芦录矛虏茅] 录矛虏茅 I2V 脤谩脢戮麓脢...")
        fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy="moderate")

        if issues:
            print(f"?? [脛脷脠脻掳虏脠芦录矛虏茅] {fix_description}")
            print(f"?? [脛脷脠脻掳虏脠芦录矛虏茅] 脭颅脢录脤谩脢戮麓脢: {prompt}")
            print(f"? [脛脷脠脻掳虏脠芦录矛虏茅] 脨脼赂麓潞贸脤谩脢戮麓脢: {fixed_prompt}")
            prompt = fixed_prompt
        else:
            print("? [脛脷脠脻掳虏脠芦录矛虏茅] 脤谩脢戮麓脢掳虏脠芦拢卢脦脼脨猫脨脼赂麓")

        kwargs: Dict[str, Any] = {"duration": duration_i}
        if size:
            kwargs["size"] = size
        if seed is not None:
            kwargs["seed"] = int(seed)
        if character_references and isinstance(character_references, list):
            kwargs["character_references"] = character_references

        img_candidates = _build_img_url_candidates(image_path)
        if not img_candidates:
            return GenerationResult(success=False, data=None, error=f"invalid image_path: {image_path}")

        max_retries = 5
        attempted_sources: List[str] = []
        last_error = ""

        for img_source, img_value in img_candidates:
            attempted_sources.append(img_source)
            retry_count = 0
            resp = None

            while retry_count <= max_retries:
                try:
                    if self._rate_limiter:
                        self._rate_limiter.acquire()
                    resp = dashscope.VideoSynthesis.call(
                        model=model_value,
                        prompt=prompt,
                        img_url=img_value,
                        api_key=self.config.api_key,
                        **kwargs,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    error_str = str(exc)
                    if "429" in error_str or "Throttling" in error_str or "RateQuota" in error_str:
                        if retry_count < max_retries:
                            retry_count += 1
                            wait_time = min(5 * (retry_count ** 1.5), 120)
                            print(f"?? DashScope I2V rate limit, retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
                            time.sleep(wait_time)
                            continue
                        return GenerationResult(
                            success=False,
                            data=None,
                            error=f"dashscope video_synthesis rate limit exceeded after {max_retries} retries: {error_str}",
                        )
                    last_error = error_str
                    resp = None
                    break

            if resp is None:
                continue

            status_code = getattr(resp, "status_code", None)
            if status_code is not None and int(status_code) != 200:
                code = getattr(resp, "code", None)
                message = getattr(resp, "message", None)
                last_error = f"dashscope video_synthesis failed: {status_code} {code} {message}"
                if self._is_dashscope_data_inspection_failed(response=resp, error_text=last_error):
                    return GenerationResult(success=False, data=None, error=last_error)
                continue

            output = getattr(resp, "output", None)
            video_url: Optional[str] = None
            if isinstance(output, dict) and isinstance(output.get("video_url"), str):
                video_url = output.get("video_url")
            elif hasattr(output, "get") and isinstance(getattr(output, "get")("video_url"), str):
                video_url = getattr(output, "get")("video_url")
            elif isinstance(getattr(output, "video_url", None), str):
                video_url = getattr(output, "video_url")

            if not isinstance(video_url, str) or not video_url.strip():
                last_error = f"dashscope video_synthesis response missing video_url: {str(output)[:300]}"
                continue

            return GenerationResult(
                success=True,
                data={"video_url": video_url},
                metadata={
                    "prompt": prompt,
                    "duration": duration_i,
                    "model": self.config.model_name,
                    "dashscope_model": model_value,
                    "size": size,
                    "image_input_mode": img_source,
                },
            )

        if not last_error:
            last_error = "dashscope video_synthesis failed"
        return GenerationResult(
            success=False,
            data=None,
            error=f"{last_error} (image_inputs={','.join(attempted_sources)})",
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
        """盲禄?氓?戮氓??莽??忙??猫搂?茅垄?"""
        # DashScope茂录?盲录?氓??猫碌掳氓庐?忙?鹿 VideoSynthesis茂录?茅?驴氓??compatible-mode 忙?楼氓?拢盲赂?忙?炉忙??氓炉录猫?麓莽??"茅??忙??氓鹿禄莽?炉莽??氓??茅??"茫??        
        if self._is_dashscope():
            return self._dashscope_i2v_via_video_synthesis(
                image_path=image_path,
                prompt=prompt,
                duration=duration,
                seed=seed,
                character_references=character_references,
            )

        # 茅??DashScope茂录?猫炉禄氓??氓?戮氓??氓鹿露莽录?莽聽?盲赂?base64茂录?猫碌掳 OpenAI-compatible 猫?陋氓庐?盲鹿?endpoint
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
    """Wan 2.6 T2V (Text-to-Video) 茅??茅??氓??- 忙??莽??猫搂?茅垄?"""

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
        DashScope 氓庐?忙?鹿 AIGC 猫搂?茅垄?忙?楼氓?拢茂录?api/v1/services/aigc/video-generation/video-synthesis茂录?茫??        """
        try:
            import dashscope  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(success=False, data=None, error=f"dashscope sdk missing: {exc}")

        model_value = self._dashscope_model_name()

        duration_i = int(round(float(duration or 0.0)))
        if duration_i <= 0:
            duration_i = 5

        # 冒??搂 氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼盲赂?猫?陋氓?篓盲驴庐氓陇?
        from adapters.content_safety_checker import ContentSafetyChecker, check_and_fix_prompt
        
        print(f"冒??? [氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼] 忙拢?忙??T2V 忙??莽陇潞猫炉?..")
        fixed_prompt, issues, fix_description = check_and_fix_prompt(prompt, strategy="moderate")
        
        if issues:
            print(f"芒?聽茂赂? [氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼] {fix_description}")
            print(f"冒??? [氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼] 氓??氓搂?忙??莽陇潞猫炉? {prompt}")
            print(f"芒??[氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼] 盲驴庐氓陇?氓??忙??莽陇潞猫炉?: {fixed_prompt}")
            
            # 盲陆驴莽?篓盲驴庐氓陇?氓??莽??忙??莽陇潞猫炉?            prompt = fixed_prompt
        else:
            print(f"芒??[氓??氓庐鹿氓庐?氓?篓忙拢?忙?楼] 忙??莽陇潞猫炉?氓庐?氓?篓茂录?忙?聽茅??盲驴庐氓陇?")

        kwargs: Dict[str, Any] = {"duration": duration_i}
        if seed is not None:
            kwargs["seed"] = int(seed)

        max_retries = 5
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                resp = dashscope.VideoSynthesis.call(
                    model=model_value,
                    prompt=prompt,
                    api_key=self.config.api_key,
                    **kwargs,
                )
                break
            except Exception as exc:  # noqa: BLE001
                error_str = str(exc)
                if "429" in error_str or "Throttling" in error_str or "RateQuota" in error_str:
                    if retry_count < max_retries:
                        retry_count += 1
                        wait_time = min(5 * (retry_count ** 1.5), 120)
                        print(f"芒?聽茂赂? DashScope T2V rate limit, retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return GenerationResult(success=False, data=None, error=f"dashscope video_synthesis rate limit exceeded after {max_retries} retries: {error_str}")
                else:
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
        """盲禄?忙??忙?卢莽??忙??猫搂?茅垄?"""
        
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
    """Wan 2.6 R2V (Reference-to-Video) 茅??茅??氓??- 氓??猫??猫搂?茅垄?莽??忙??猫搂?茅垄?"""

    def generate(
        self,
        reference_video_path: str,
        prompt: str = "",
        duration: float = 3.0,
        fps: int = 24,
        seed: Optional[int] = None
    ) -> GenerationResult:
        """盲禄?氓??猫??猫搂?茅垄?莽??忙??忙?掳猫搂?茅垄?"""
        # 猫炉禄氓??猫搂?茅垄?氓鹿露莽录?莽聽?盲赂潞base64
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
    """Qwen-Image-Edit-Plus 茅??茅??氓??- 氓?戮莽??莽录?猫戮?"""
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
        """莽录?猫戮?氓?戮氓??"""
        if not self._is_dashscope():
            return GenerationResult(
                success=False,
                data=None,
                error="QwenImageEditPlusAdapter only supports DashScope"
            )

        try:
            import base64
            content_items: List[Dict[str, Any]] = []
            extra_paths: List[str] = []
            if isinstance(image_paths, list):
                for item in image_paths:
                    if not item:
                        continue
                    item_str = str(item).strip()
                    if not item_str or item_str == image_path:
                        continue
                    if item_str in extra_paths:
                        continue
                    extra_paths.append(item_str)

            for item_path in [image_path] + extra_paths:
                if str(item_path).startswith(("http://", "https://")):
                    content_items.append({"image": str(item_path)})
                    continue
                path_obj = Path(str(item_path))
                if not path_obj.exists():
                    if str(item_path) == image_path:
                        raise RuntimeError(f"image not found: {image_path}")
                    continue
                with open(path_obj, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                content_items.append({"image": f"data:image/png;base64,{image_data}"})

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
                            "content": content_items + [{"text": edit_prompt}],
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

            def _extract_first_image_url(raw_result: Dict[str, Any]) -> str:
                output = raw_result.get("output", {}) if isinstance(raw_result, dict) else {}
                choices = output.get("choices", []) if isinstance(output, dict) else []
                if not isinstance(choices, list):
                    return ""
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    message = choice.get("message", {})
                    content = message.get("content", []) if isinstance(message, dict) else []
                    if not isinstance(content, list):
                        continue
                    for item in content:
                        if isinstance(item, dict) and isinstance(item.get("image"), str) and str(item.get("image")).strip():
                            return str(item.get("image")).strip()
                return ""

            if not content_items:
                raise RuntimeError("no valid reference image provided")

            def _is_message_schema_error(exc: Exception) -> bool:
                detail = str(exc or "").lower()
                return (
                    "for image editing, the message must" in detail
                    or ("invalidparameter" in detail and "message must" in detail)
                )

            primary_content = content_items + [{"text": edit_prompt}]
            single_image_content = [content_items[0], {"text": edit_prompt}]
            single_text_first_content = [{"text": edit_prompt}, content_items[0]]

            default_mode = "multi" if len(content_items) > 1 else "single_image_first"
            attempt_contents: List[Tuple[str, List[Dict[str, Any]]]] = [(default_mode, primary_content)]
            if len(content_items) > 1:
                attempt_contents.append(("single_image_first", single_image_content))
                attempt_contents.append(("single_text_first", single_text_first_content))
            else:
                attempt_contents.append(("single_text_first", single_text_first_content))

            result: Dict[str, Any] = {}
            selected_mode = default_mode
            last_exc: Optional[Exception] = None
            for idx, (mode, candidate_content) in enumerate(attempt_contents):
                request_payload = copy.deepcopy(payload)
                request_payload["input"]["messages"][0]["content"] = candidate_content
                try:
                    result = self._request_json_url(method="POST", url=url, payload=request_payload)
                    selected_mode = mode
                    break
                except Exception as req_exc:
                    last_exc = req_exc
                    should_try_next = idx < len(attempt_contents) - 1 and _is_message_schema_error(req_exc)
                    if not should_try_next:
                        raise
            else:
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("image edit request failed")

            image_url = _extract_first_image_url(result)
            if image_url:
                return GenerationResult(
                    success=True,
                    data={"image_url": image_url},
                    metadata={
                        "edit_prompt": edit_prompt,
                        "strength": strength,
                        "model": self.config.model_name,
                        "ref_image_count": len(content_items) if len(content_items) > 1 and selected_mode == "multi" else 1,
                        "request_mode": selected_mode,
                        "multi_ref_fallback": bool(len(content_items) > 1 and selected_mode != "multi"),
                        "content_order_fallback": selected_mode == "single_text_first",
                    }
                )

            return GenerationResult(
                success=False,
                data=None,
                error=f"No image data returned. API response: {result}"
            )
        except Exception as e:
            return GenerationResult(
                success=False,
                data=None,
                error=str(e)
            )

class WanImageEditAdapter(QwenImageEditPlusAdapter):
    """Wan Image Edit 脙漏芒?卢芒??脙垄芒?卢脗娄脙楼芒?? 脙楼芒?潞脗戮脙楼脝?脗隆脙搂脗录芒??脙篓脗戮芒??"""
    supports_multi_image = False


class QwenImageEditMaxAdapter(QwenImageEditPlusAdapter):
    """Qwen-Image-Edit-Max adapter - image edit"""


class QwenMultiPersonFusionAdapter(BaseModelAdapter):
    """Qwen-Image-Edit-Plus 氓陇?盲潞潞莽?漏猫??氓??茅??茅??氓??- 忙?炉忙??盲潞潞莽?漏忙??氓??茫??氓?潞忙?炉氓?鹿茅??茫??氓陇?盲潞潞莽?漏猫??氓??"""

    def _make_request(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        method: str = "POST"
    ) -> Dict[str, Any]:
        """
        氓??茅??API猫炉路忙卤? - 茅??氓??盲禄楼盲陆驴莽?篓DashScope氓??莽??API莽芦炉莽?鹿
        
        Qwen-Image-Edit-Plus盲陆驴莽?篓DashScope氓??莽??API茂录?盲赂?忙?炉OpenAI氓?录氓庐鹿忙篓隆氓录?
        """
        base_host = self._base_host()
        if not base_host:
            base_host = "https://dashscope.aliyuncs.com"
        
        url = f"{base_host}/api/v1/{endpoint}"
        return self._request_json_url(method=method, url=url, payload=payload)

    def extract_person(
        self,
        image_path: str,
        person_prompt: str = "忙??氓??氓?戮氓??盲赂颅莽??盲潞潞莽?漏",
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        盲禄?忙潞?氓?戮氓??盲赂颅忙??氓??盲潞潞莽?漏氓??莽麓?        
        Args:
            image_path: 忙潞?氓?戮氓??猫路炉氓戮?            person_prompt: 盲潞潞莽?漏忙??氓??忙??莽陇潞猫炉?            n: 莽??忙??氓?戮莽??忙?掳茅??
            negative_prompt: 猫麓?氓??忙??莽陇潞猫炉?            prompt_extend: 忙?炉氓?娄忙?漏氓卤?忙??莽陇潞猫炉?            watermark: 忙?炉氓?娄忙路禄氓?聽忙掳麓氓?掳
        
        Returns:
            GenerationResult: 氓??氓?芦忙??氓??氓??莽??盲潞潞莽?漏氓?戮氓??URL
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
        scene_prompt: str = "place the character naturally into the target scene with consistent lighting and perspective",
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        氓掳?盲潞潞莽?漏盲赂?莽?庐忙聽?氓?潞忙?炉氓?鹿茅??茂录?莽隆庐盲驴?氓??莽?搂茫??猫搂?猫搂?盲赂?猫??        
        Args:
            person_image_path: 盲潞潞莽?漏氓?戮氓??猫路炉氓戮?
            target_scene_path: 莽?庐忙聽?氓?潞忙?炉氓?戮氓??猫路炉氓戮?
            scene_prompt: 氓?潞忙?炉氓?鹿茅??忙??莽陇潞猫炉?            n: 莽??忙??氓?戮莽??忙?掳茅??
            negative_prompt: 猫麓?氓??忙??莽陇潞猫炉?            prompt_extend: 忙?炉氓?娄忙?漏氓卤?忙??莽陇潞猫炉?            watermark: 忙?炉氓?娄忙路禄氓?聽忙掳麓氓?掳
        
        Returns:
            GenerationResult: 氓??氓?芦氓?鹿茅??氓??莽??氓?戮氓??URL
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
        fusion_prompt: str = "氓掳?氓陇?盲赂陋盲潞潞莽?漏猫?陋莽?露氓?掳猫??氓??氓?掳氓??盲赂?氓?潞忙?炉盲赂颅茂录?盲驴?忙??盲潞潞莽?漏盲赂?猫?麓忙?搂氓??氓?潞忙?炉氓??猫掳?",
        layout_description: Optional[str] = None,
        n: int = 1,
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        氓掳?氓陇?盲赂陋盲潞潞莽?漏猫??氓??氓?掳氓??盲赂?氓?潞忙?炉盲赂?        
        Args:
            person_images: 氓陇?盲赂陋盲潞潞莽?漏氓?戮氓??猫路炉氓戮?氓??猫隆篓
            target_scene_path: 莽?庐忙聽?氓?潞忙?炉氓?戮氓??猫路炉氓戮?
            fusion_prompt: 猫??氓??忙??莽陇潞猫炉?            layout_description: 氓赂?氓卤?忙??猫驴掳茂录?氓?炉茅??茂录?莽?篓盲潞?忙??氓庐?盲潞潞莽?漏氓?篓氓?潞忙?炉盲赂颅莽??盲陆?莽陆庐茂录?
            n: 莽??忙??氓?戮莽??忙?掳茅??
            negative_prompt: 猫麓?氓??忙??莽陇潞猫炉?            prompt_extend: 忙?炉氓?娄忙?漏氓卤?忙??莽陇潞猫炉?            watermark: 忙?炉氓?娄忙路禄氓?聽忙掳麓氓?掳
        
        Returns:
            GenerationResult: 氓??氓?芦猫??氓??氓??莽??氓?戮氓??URL
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
            enhanced_prompt = f"{fusion_prompt}\n氓赂?氓卤?猫娄?忙卤?茂录?{layout_description}"
        
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
        negative_prompt: str = "low quality, blurry, distorted, extra limbs, text, watermark",
        prompt_extend: bool = True,
        watermark: bool = False
    ) -> GenerationResult:
        """
        猫掳?忙?麓氓?戮氓??莽??氓??莽?搂忙??忙??        
        Args:
            image_path: 氓?戮氓??猫路炉氓戮?
            lighting_prompt: 氓??莽?搂猫掳?忙?麓忙??莽陇潞猫炉?茂录?氓娄?忙路禄氓?聽忙??氓??莽??盲戮搂氓??茫??氓垄?氓录潞猫?陋莽?露氓??莽颅?茂录?
            n: 莽??忙??氓?戮莽??忙?掳茅??
            negative_prompt: 猫麓?氓??忙??莽陇潞猫炉?            prompt_extend: 忙?炉氓?娄忙?漏氓卤?忙??莽陇潞猫炉?            watermark: 忙?炉氓?娄忙路禄氓?聽忙掳麓氓?掳
        
        Returns:
            GenerationResult: 氓??氓?芦猫掳?忙?麓氓??莽??氓?戮氓??URL
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
        莽禄?盲赂?莽??莽??忙??忙?楼氓?拢茂录?忙聽鹿忙?庐operation莽卤禄氓??猫掳?莽?篓盲赂?氓??莽??氓??猫??        
        Args:
            operation: 忙??盲陆?莽卤禄氓?? (extract_person, match_scene, fuse_multiple_persons, adjust_lighting)
            **kwargs: 忙??盲陆?莽?赂氓?鲁莽??氓??忙??        
        Returns:
            GenerationResult: 忙??盲陆?莽禄?忙??
        """
        if operation == "extract_person":
            return self.extract_person(
                image_path=kwargs.get("image_path"),
                person_prompt=kwargs.get("person_prompt", "忙??氓??氓?戮氓??盲赂颅莽??盲潞潞莽?漏"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "match_scene":
            return self.match_scene(
                person_image_path=kwargs.get("person_image_path"),
                target_scene_path=kwargs.get("target_scene_path"),
                scene_prompt=kwargs.get("scene_prompt", "place the character naturally into the target scene with consistent lighting and perspective"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "fuse_multiple_persons":
            return self.fuse_multiple_persons(
                person_images=kwargs.get("person_images", []),
                target_scene_path=kwargs.get("target_scene_path"),
                fusion_prompt=kwargs.get("fusion_prompt", "氓掳?氓陇?盲赂陋盲潞潞莽?漏猫?陋莽?露氓?掳猫??氓??氓?掳氓??盲赂?氓?潞忙?炉盲赂颅茂录?盲驴?忙??盲潞潞莽?漏盲赂?猫?麓忙?搂氓??氓?潞忙?炉氓??猫掳?"),
                layout_description=kwargs.get("layout_description"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
                prompt_extend=kwargs.get("prompt_extend", True),
                watermark=kwargs.get("watermark", False)
            )
        elif operation == "adjust_lighting":
            return self.adjust_lighting(
                image_path=kwargs.get("image_path"),
                lighting_prompt=kwargs.get("lighting_prompt"),
                n=kwargs.get("n", 1),
                negative_prompt=kwargs.get("negative_prompt", "low quality, blurry, distorted, extra limbs, text, watermark"),
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
    """Qwen3-VL-Plus 茅??茅??氓??- 氓?戮莽??盲赂?猫搂?茅垄?莽??猫搂拢茂录?猫麓篓茅??猫炉?盲录掳茂录?"""

    def generate(self, **kwargs) -> GenerationResult:  # noqa: ANN003
        """
        氓?录氓庐鹿 BaseModelAdapter 忙?陆猫卤隆忙?楼氓?拢茂录?        - analyze_image: 盲录聽氓?楼 image_path
        - analyze_video: 盲录聽氓?楼 video_path
        - chat: 盲录聽氓?楼 messages
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
        OpenAI-Compatible Chat Completions茂录?莽?篓盲潞?氓陇?忙篓隆忙??猫炉?茅??氓??猫??茅??忙?漏茂录?茫??
        忙鲁篓忙??茂录?message schema 莽?卤猫掳?莽?篓忙?鹿盲驴?猫炉?茂录?role/content茂录?茂录?content 氓?炉盲赂潞莽潞炉忙??忙?卢忙??氓陇?忙篓隆忙??忙?掳莽禄?茫??        """
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
        """氓??忙??氓?戮氓??猫麓篓茅??"""
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
        """氓??忙??猫搂?茅垄?猫麓篓茅??"""
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
        
        payload = {
            "model": self.config.model_name,
            "text": text.strip(),
            "voice_style": voice_style,
            "speed": max(0.5, min(2.0, float(speed))),
            "pitch": max(0.5, min(2.0, float(pitch))),
            "volume": max(0.0, min(1.0, float(volume)))
        }

        resolved_voice_id = str(voice_id or "").strip()
        if resolved_voice_id:
            try:
                from backend.app.services.audiobook.constants import normalize_speaker_id
                resolved_voice_id = normalize_speaker_id(resolved_voice_id)
            except Exception:
                pass
            payload["voice"] = resolved_voice_id
        
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
                    data = {"audio_data": audio_data, "format": "mp3"}
                    tts_timestamps = result["data"].get("tts_timestamps")
                    if not isinstance(tts_timestamps, list):
                        tts_timestamps = result["data"].get("word_timestamps")
                    if isinstance(tts_timestamps, list):
                        data["tts_timestamps"] = tts_timestamps
                    phoneme_timestamps = result["data"].get("phoneme_timestamps")
                    if isinstance(phoneme_timestamps, list):
                        data["phoneme_timestamps"] = phoneme_timestamps
                    return GenerationResult(
                        success=True,
                        data=data,
                        metadata={
                            "text": text,
                            "voice_style": voice_style,
                            "character_id": character_id,
                            "voice_id": resolved_voice_id,
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
        盲陆驴莽?篓DashScope氓??莽??API猫驴?猫隆?忙??忙?卢猫陆卢猫炉颅茅??        """
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

        if "voice" in payload:
            dashscope_payload["parameters"]["voice"] = payload["voice"]
        
        if "character_id" in payload:
            dashscope_payload["parameters"]["character_id"] = payload["character_id"]
        
        base_host = self._base_host()
        if not base_host:
            base_host = "https://dashscope.aliyuncs.com"
        
        url = f"{base_host}/api/v1/services/aigc/text2audio/generation"
        
        result = self._request_json_url(method="POST", url=url, payload=dashscope_payload)

        if "output" in result and "audio" in result["output"]:
            data = {"audio_data": result["output"]["audio"]}
            output = result.get("output") if isinstance(result.get("output"), dict) else {}
            if isinstance(output.get("timestamps"), list):
                data["tts_timestamps"] = output.get("timestamps")
            elif isinstance(output.get("word_timestamps"), list):
                data["tts_timestamps"] = output.get("word_timestamps")
            if isinstance(output.get("phoneme_timestamps"), list):
                data["phoneme_timestamps"] = output.get("phoneme_timestamps")
            return {"data": data}

        return result


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
        "wan_i2v": "wan26_i2v",
        "wan_t2v": "wan26_t2v",
        "wan_r2v": "wan26_r2v",
        "wan-t2i": "wan26_t2i",
        "wan-i2v": "wan26_i2v",
        "wan-t2v": "wan26_t2v",
        "wan-r2v": "wan26_r2v",
    }
    _BRIDGE_MODEL_MAP = {
        "wan26_t2i": "wanx-v1",
        "wan26_i2v": "wan2.6-t2v",
        "wan26_t2v": "wan2.6-t2v",
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

        from adapters.legacy_bridge import ModelAdapterFactory as UnifiedFactory

        kwargs = self._build_bridge_kwargs(normalized_key, bridge_name)
        adapter = UnifiedFactory.create(bridge_name, **kwargs)
        self._cache[normalized_key] = adapter
        self._cache[bridge_name] = adapter
        return adapter
