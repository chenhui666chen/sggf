"""主站到视频网关内部管理面的客户端。"""
from __future__ import annotations

from typing import Any
from decimal import Decimal

import httpx

from app.core.config import settings


class VideoGatewayUnavailable(RuntimeError):
    pass


class VideoGatewayClient:
    def __init__(self, *, base_url: str | None = None, token: str | None = None):
        self.base_url = (settings.VIDEO_GATEWAY_INTERNAL_URL if base_url is None else base_url).strip().rstrip("/")
        self.token = (settings.VIDEO_GATEWAY_INTERNAL_TOKEN if token is None else token).strip()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.base_url or not self.token:
            raise VideoGatewayUnavailable("视频网关内部管理接口未配置")
        if "json" in kwargs:
            kwargs["json"] = {key: str(value) if isinstance(value, Decimal) else value
                              for key, value in kwargs["json"].items()}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}",
                    headers={"X-Gateway-Internal-Token": self.token}, **kwargs)
        except httpx.HTTPError as exc:
            raise VideoGatewayUnavailable from exc
        if response.status_code >= 400:
            raise VideoGatewayUnavailable(f"网关管理请求失败: {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise VideoGatewayUnavailable("网关管理响应格式错误") from exc
        if not isinstance(payload, dict):
            raise VideoGatewayUnavailable("网关管理响应格式错误")
        return payload

    async def create_client(self, *, name: str, limits: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/internal/clients", json={"name": name, **limits})

    async def rotate_key(self, client_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/internal/clients/{client_id}/rotate-key")

    async def set_status(self, client_id: str, *, enabled: bool) -> dict[str, Any]:
        return await self._request("POST", f"/internal/clients/{client_id}/status", json={"enabled": enabled})

    async def update_limits(self, client_id: str, limits: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/internal/clients/{client_id}/limits", json=limits)

    async def metrics_overview(self, *, window_hours: int = 24) -> dict[str, Any]:
        return await self._request(
            "GET", "/internal/metrics/overview", params={"window_hours": window_hours})
