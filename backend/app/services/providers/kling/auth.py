from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from jose import jwt

from app.core.config import settings


class KlingConfigurationError(RuntimeError):
    """Raised when Kling credentials are not available."""


@dataclass(frozen=True)
class KlingBearerToken:
    token: str
    source: str


class KlingAuthProvider:
    def __init__(
        self,
        *,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
    ) -> None:
        self._access_key = str(access_key or "").strip()
        self._secret_key = str(secret_key or "").strip()
        self._session_token = str(session_token or "").strip()
        self._cached_jwt_token = ""
        self._cached_jwt_expire_time = 0.0

    def _resolve_session_token(self) -> str:
        token = self._session_token or os.getenv("KLING_TOKEN", "")
        token = str(token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token

    def _resolve_access_key(self) -> str:
        return self._access_key or str(os.getenv("KLINGAI_ACCESS_KEY") or getattr(settings, "KLINGAI_ACCESS_KEY", "") or "").strip()

    def _resolve_secret_key(self) -> str:
        return self._secret_key or str(os.getenv("KLINGAI_SECRET_KEY") or getattr(settings, "KLINGAI_SECRET_KEY", "") or "").strip()

    def has_credentials(self) -> bool:
        if self._resolve_session_token():
            return True
        return bool(self._resolve_access_key() and self._resolve_secret_key())

    def resolve_bearer_token(self) -> KlingBearerToken:
        session_token = self._resolve_session_token()
        if session_token:
            return KlingBearerToken(token=session_token, source="session_token")

        access_key = self._resolve_access_key()
        secret_key = self._resolve_secret_key()
        if not access_key or not secret_key:
            raise KlingConfigurationError("未配置可用的 Kling 凭证（KLING_TOKEN 或 KLINGAI_ACCESS_KEY/KLINGAI_SECRET_KEY）。")

        now = time.time()
        if self._cached_jwt_token and now < self._cached_jwt_expire_time:
            return KlingBearerToken(token=self._cached_jwt_token, source="jwt")

        token = self._generate_jwt_token(access_key=access_key, secret_key=secret_key)
        self._cached_jwt_token = token
        self._cached_jwt_expire_time = now + 1700
        return KlingBearerToken(token=token, source="jwt")

    @staticmethod
    def _generate_jwt_token(*, access_key: str, secret_key: str) -> str:
        current_time = int(time.time())
        headers = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": access_key,
            "exp": current_time + 1800,
            "nbf": current_time - 5,
        }
        return str(jwt.encode(payload, secret_key, headers=headers))
