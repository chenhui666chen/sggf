from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx

from .auth import KlingAuthProvider


def _normalize_base_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _resolve_default_base_url() -> str:
    env_value = _normalize_base_url(os.getenv("KLINGAI_API_BASE"))
    if env_value:
        return env_value
    return "https://api-beijing.klingai.com"


@dataclass(frozen=True)
class KlingAPIError(RuntimeError):
    message: str
    status_code: Optional[int] = None
    error_code: Optional[int] = None
    request_id: Optional[str] = None
    payload: Optional[dict[str, Any]] = None

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.error_code is not None:
            parts.append(f"code={self.error_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " | ".join(parts)


class KlingAPIClient:
    def __init__(
        self,
        *,
        auth_provider: Optional[KlingAuthProvider] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._auth_provider = auth_provider or KlingAuthProvider()
        self._base_url = _normalize_base_url(base_url) or _resolve_default_base_url()
        self._timeout = float(timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    def get_json(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        return self._request_json("GET", path, params=params)

    def post_json(self, path: str, *, payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        return self._request_json("POST", path, payload=payload)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        token = self._auth_provider.resolve_bearer_token().token
        url = f"{self._base_url}{path if str(path).startswith('/') else '/' + str(path)}"
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "DreamWeaver-Kling/0.1",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=dict(params or {}) or None,
                    json=dict(payload or {}) if payload is not None else None,
                )
        except httpx.HTTPError as exc:
            raise KlingAPIError(f"Kling 请求失败: {exc}") from exc

        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        text = response.text
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise KlingAPIError(
                message=f"Kling 返回了非 JSON 内容: {text[:120]}",
                status_code=response.status_code,
            ) from exc

        if not response.is_success:
            raise self._build_error(payload=payload, status_code=response.status_code)

        if not isinstance(payload, Mapping):
            raise KlingAPIError(
                message="Kling 返回数据格式不正确。",
                status_code=response.status_code,
            )

        code_raw = payload.get("code")
        try:
            code = int(code_raw)
        except Exception:  # noqa: BLE001
            code = None

        if code not in {0, 200, None}:
            raise self._build_error(payload=payload, status_code=response.status_code)

        data = payload.get("data")
        if isinstance(data, Mapping):
            return dict(data)
        if data is None:
            return dict(payload)
        return {"data": data}

    @staticmethod
    def _build_error(*, payload: Any, status_code: Optional[int]) -> KlingAPIError:
        if isinstance(payload, Mapping):
            message = str(payload.get("message") or payload.get("msg") or "Kling API 调用失败").strip()
            try:
                error_code = int(payload.get("code")) if payload.get("code") is not None else None
            except Exception:  # noqa: BLE001
                error_code = None
            request_id = str(payload.get("request_id") or payload.get("requestId") or "").strip() or None
            return KlingAPIError(
                message=message or "Kling API 调用失败",
                status_code=status_code,
                error_code=error_code,
                request_id=request_id,
                payload=dict(payload),
            )
        return KlingAPIError(message="Kling API 调用失败", status_code=status_code)
