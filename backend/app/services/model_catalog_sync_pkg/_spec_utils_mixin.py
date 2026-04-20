from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import asyncio
import json
import logging
import os
import re

import httpx
import yaml
from sqlalchemy.orm import Session, selectinload

from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

try:
    from core.unified_llm_client import get_llm_client
    _LLM_CLIENT_AVAILABLE = True
except ImportError:
    _LLM_CLIENT_AVAILABLE = False
    get_llm_client = None

try:
    from core.model_catalog_runtime import get_model_catalog_runtime_index
    _RUNTIME_SIGNAL_AVAILABLE = True
except ImportError:
    _RUNTIME_SIGNAL_AVAILABLE = False
    get_model_catalog_runtime_index = None

logger = logging.getLogger(__name__)

from app.services.model_catalog_sync_pkg._constants import (
    CatalogSeed, SourceVerification, DetailedSpecExtraction,
    _LLM_VERIFICATION_TRIGGER, PRICING_VERIFICATION_CONFIG,
    VERIFIED_PRICING_DATA, _ERROR_PAGE_KEYWORDS,
)

class SpecUtilsMixin:
    def _load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"模型配置文件不存在: {path}")
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def _load_catalog_profiles(self) -> dict[str, dict[str, Any]]:
        if not self._catalog_profile_path.exists():
            return {}

        payload = self._load_yaml(self._catalog_profile_path)
        profiles = payload.get("profiles", {}) or {}
        if not isinstance(profiles, dict):
            return {}

        normalized: dict[str, dict[str, Any]] = {}
        for model_key, profile in profiles.items():
            clean_key = str(model_key or "").strip()
            if not clean_key or not isinstance(profile, dict):
                continue
            normalized[clean_key] = deepcopy(profile)
        return normalized

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _fetch_response(self, client: httpx.Client, url: str) -> httpx.Response:
        cache_key = (url or "").strip()
        if self._response_cache is not None:
            cached = self._response_cache.get(cache_key)
            if cached is not None:
                self._fetch_cache_hits += 1
                return cached

        last_error: Optional[httpx.HTTPError] = None
        for _ in range(2):
            try:
                self._fetch_cache_misses += 1
                response = client.get(url)
                response.raise_for_status()
                if self._response_cache is not None:
                    self._response_cache[cache_key] = response
                    final_url = str(response.url or "").strip()
                    if final_url:
                        self._response_cache.setdefault(final_url, response)
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc

        if last_error is None:
            raise httpx.HTTPError("未知的模型来源请求错误")
        raise last_error

    def _matches_provider(self, provider: str, content: str, url: str) -> bool:
        if any(keyword in content for keyword in _PROVIDER_KEYWORDS.get(provider, [])):
            return True

        lowered_url = (url or "").lower()
        return any(domain in lowered_url for domain in _PROVIDER_DOMAINS.get(provider, []))

    def _append_keyword_variants(self, keywords: list[str], candidate: str) -> None:
        lowered = (candidate or "").lower().strip()
        if not lowered:
            return

        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
        keywords.append(lowered)
        if compact and compact != lowered:
            keywords.append(compact)

    def _extract_title(self, html: str) -> str:
        match = _TITLE_RE.search(html or "")
        if not match:
            return ""
        return self._clean_html_fragment(match.group(1))[:300]

    def _extract_excerpt(self, html: str) -> str:
        meta_match = _META_RE.search(html or "")
        if meta_match:
            return self._clean_html_fragment(meta_match.group(1))[:500]

        return self._extract_search_text(html)[:500]

    def _extract_search_text(self, html: str) -> str:
        cleaned = _SCRIPT_STYLE_RE.sub(" ", html or "")
        cleaned = _TAG_RE.sub(" ", cleaned)
        cleaned = _SPACE_RE.sub(" ", unescape(cleaned)).strip()
        return cleaned[:300000]

    def _is_error_page(self, title: str, excerpt: str, search_text: str) -> bool:
        headline = f"{title} {excerpt}".lower()
        if any(keyword in headline for keyword in _ERROR_PAGE_KEYWORDS):
            return True

        leading_content = (search_text or "")[:1200].lower()
        return any(keyword in leading_content for keyword in _ERROR_PAGE_KEYWORDS)

    def _clean_html_fragment(self, fragment: str) -> str:
        text = _TAG_RE.sub(" ", fragment or "")
        return _SPACE_RE.sub(" ", unescape(text)).strip()
