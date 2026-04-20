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

class SourceVerifyMixin:
    def _verify_seed(
        self,
        seed: CatalogSeed,
        *,
        existing_entry: Optional["ModelCatalogEntry"] = None,
    ) -> list[SourceVerification]:
        """校验单个模型的来源。

        Args:
            seed: 模型种子信息
            existing_entry: 数据库中已有的模型条目（用于智能触发策略）
        """
        urls = self._build_source_candidates(seed)
        if not urls:
            return []

        with httpx.Client(
            follow_redirects=True,
            headers={
                "User-Agent": "NovelWritingAgent/ModelCatalogSync (+https://localhost)",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=httpx.Timeout(20.0, connect=8.0),
        ) as client:
            return self._deduplicate_verifications(
                [
                    self._verify_single_source(client, seed, candidate, existing_entry=existing_entry)
                    for candidate in urls
                ]
            )

    def _verify_single_source(
        self,
        client: httpx.Client,
        seed: CatalogSeed,
        candidate: tuple[str, str],
        *,
        existing_entry: Optional["ModelCatalogEntry"] = None,
    ) -> SourceVerification:
        source_type, url = candidate
        fetched_at = datetime.now(timezone.utc)
        domain = urlparse(url).netloc

        try:
            response = self._fetch_response(client, url)

            title = self._extract_title(response.text)
            excerpt = self._extract_excerpt(response.text)
            search_text = self._extract_search_text(response.text)
            if self._is_error_page(title, excerpt, search_text):
                return SourceVerification(
                    url=str(response.url),
                    source_type=source_type,
                    source_domain=urlparse(str(response.url)).netloc or domain,
                    http_status=response.status_code,
                    reachable=False,
                    verified=False,
                    page_title=title,
                    page_excerpt=excerpt,
                    matched_keywords=[],
                    verification_note="来源返回了错误页或失效页，无法作为有效校验依据。",
                    raw_metadata={
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type", ""),
                        "content_length": response.headers.get("content-length", ""),
                        "is_error_page": True,
                    },
                    fetched_at=fetched_at,
                    score=0.0,
                    extracted_specs={},
                )

            analysis_text = f"{title} {excerpt} {search_text}".lower()
            matched_keywords = self._collect_matched_keywords(seed, analysis_text)
            matched_keywords.extend(self._collect_url_matched_keywords(seed, str(response.url)))
            matched_keywords = list(dict.fromkeys(matched_keywords))
            provider_match = self._matches_provider(seed.provider, analysis_text, str(response.url))
            alias_match = any(keyword.startswith("alias:") for keyword in matched_keywords)
            modality_match = any(keyword.startswith("modality:") for keyword in matched_keywords)
            score = 0.35
            score += 0.3 if alias_match else 0.0
            score += 0.2 if modality_match else 0.0
            score += 0.1 if provider_match else 0.0
            score += 0.05 if source_type == "documentation" else 0.0

            verified = alias_match and (modality_match or provider_match or source_type == "documentation")
            note = "已识别模型身份与主模态。" if verified else "来源可访问，但只完成了部分特征匹配。"

            extracted_specs = self._extract_detailed_specs(response.text, seed, str(response.url))
            prompt_examples = self._extract_prompt_examples_from_html(response.text)

            extracted_specs_dict = {
                "duration_range": extracted_specs.duration_range,
                "resolution_options": extracted_specs.resolution_options,
                "frame_rate": extracted_specs.frame_rate,
                "output_format": extracted_specs.output_format,
                "input_modalities": extracted_specs.input_modalities,
                "advanced_features": extracted_specs.advanced_features,
                "max_reference_images": extracted_specs.max_reference_images,
                "weight_control": extracted_specs.weight_control,
                "first_frame_support": extracted_specs.first_frame_support,
                "last_frame_support": extracted_specs.last_frame_support,
                "prompt_examples": prompt_examples,
                "extraction_confidence": extracted_specs.extraction_confidence,
            }

            # LLM校验（智能触发）
            should_trigger, trigger_reason = self._should_trigger_llm_verification(seed, existing_entry)
            logger.info(
                f"LLM联网搜索触发判断 | model={seed.model_key} | should_trigger={should_trigger} | reason={trigger_reason}"
            )
            if should_trigger:
                try:
                    llm_verified_specs = self._sync_verify_with_llm(
                        seed,
                        extracted_specs_dict,
                        search_text,
                    )
                    if llm_verified_specs.get("_llm_verification"):
                        extracted_specs_dict = llm_verified_specs
                        llm_meta = llm_verified_specs["_llm_verification"]
                        note += f" LLM校验置信度: {llm_meta.get('confidence', 0):.0%}，可靠性: {llm_meta.get('reliability_score', 0)}分。"
                    else:
                        note += " LLM校验未返回有效结果。"
                except Exception as e:
                    logger.warning(f"LLM 校验调用失败: {e}")
                    note += f" LLM校验调用失败: {e}"
            else:
                note += f" 智能触发跳过LLM联网搜索: {trigger_reason}"

            if extracted_specs.extraction_confidence > 0.3:
                note += f" 已提取详细规格（置信度: {extracted_specs.extraction_confidence:.0%}）。"

            return SourceVerification(
                url=str(response.url),
                source_type=source_type,
                source_domain=urlparse(str(response.url)).netloc or domain,
                http_status=response.status_code,
                reachable=True,
                verified=verified,
                page_title=title,
                page_excerpt=excerpt,
                matched_keywords=matched_keywords,
                verification_note=note,
                raw_metadata={
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type", ""),
                    "content_length": response.headers.get("content-length", ""),
                },
                fetched_at=fetched_at,
                score=score,
                extracted_specs=extracted_specs_dict,
            )
        except httpx.HTTPError as exc:
            logger.warning("模型来源校验失败 | model=%s | url=%s | error=%s", seed.model_key, url, exc)
            return SourceVerification(
                url=url,
                source_type=source_type,
                source_domain=domain,
                http_status=getattr(getattr(exc, "response", None), "status_code", None),
                reachable=False,
                verified=False,
                page_title="",
                page_excerpt="",
                matched_keywords=[],
                verification_note=f"请求失败: {exc}",
                raw_metadata={"error": str(exc)},
                fetched_at=fetched_at,
                score=0.0,
                extracted_specs={},
            )

    def _build_source_candidates(self, seed: CatalogSeed) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []

        def _push(source_type: str, url: str) -> None:
            clean_url = (url or "").strip()
            if not clean_url:
                return
            if any(existing_url == clean_url for _, existing_url in candidates):
                return
            candidates.append((source_type, clean_url))

        _push("documentation", seed.documentation_url)
        for url in seed.source_urls:
            _push("reference", url)
        for url in _GLOBAL_FALLBACK_SOURCES.get(seed.provider, []):
            _push("fallback", url)
        for url in _MODEL_FALLBACK_SOURCES.get(seed.model_key, []):
            _push("fallback", url)
        # 全局通用搜索源（所有模型都会使用）
        for url in _UNIVERSAL_FALLBACK_SOURCES:
            _push("universal", url)

        return candidates

    def _deduplicate_verifications(
        self,
        verifications: list[SourceVerification],
    ) -> list[SourceVerification]:
        deduped: dict[str, SourceVerification] = {}
        for verification in verifications:
            key = verification.url.strip().lower()
            existing = deduped.get(key)
            if existing is None or verification.score > existing.score:
                deduped[key] = verification
        return list(deduped.values())

    def _normalize_llm_seed(
        self,
        raw: dict[str, Any],
        *,
        catalog_profile: Optional[dict[str, Any]] = None,
    ) -> CatalogSeed:
        capabilities = raw.get("capabilities", []) or []
        tags = [str(item) for item in raw.get("tags", []) or []]
        category = "llm"
        subcategory = self._infer_llm_subcategory(capabilities, tags)
        raw_config = deepcopy(raw)
        if catalog_profile:
            raw_config["catalog_profile"] = deepcopy(catalog_profile)
        return CatalogSeed(
            model_key=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            provider=str(raw.get("provider", "")).strip(),
            category=category,
            subcategory=subcategory,
            model_family=self._infer_model_family(str(raw.get("name", "")), str(raw.get("id", ""))),
            config_source="llm_models.yaml",
            status=str(raw.get("status", "active")),
            summary=str(raw.get("summary", "")).strip(),
            recommended_scenarios=self._normalize_string_list(raw.get("recommended_scenarios")),
            limitations=self._normalize_string_list(raw.get("limitations")),
            integration_notes=self._normalize_string_list(raw.get("integration_notes")),
            documentation_url=str(raw.get("documentation_url", "")).strip(),
            source_urls=self._normalize_string_list(raw.get("source_urls")),
            tags=tags,
            modalities=["text_generation"],
            capabilities=[item for item in capabilities if isinstance(item, dict)],
            constraints=raw.get("constraints", {}) or {},
            performance=raw.get("performance", {}) or {},
            routing=raw.get("routing", {}) or {},
            default_params=raw.get("default_params", {}) or {},
            raw_config=raw_config,
        )

    def _normalize_capability_seed(
        self,
        raw: dict[str, Any],
        *,
        catalog_profile: Optional[dict[str, Any]] = None,
    ) -> CatalogSeed:
        modalities = [str(item) for item in raw.get("modality", []) or []]
        capabilities = raw.get("capabilities", []) or []
        tags = [str(item) for item in raw.get("tags", []) or []]
        category = self._infer_model_category(modalities)
        subcategory = self._infer_capability_subcategory(modalities, tags, raw.get("id", ""))
        performance = {
            "quality_metrics": raw.get("quality_metrics", {}) or {},
            "cost_profile": raw.get("cost_profile", {}) or {},
            "avg_latency_seconds": raw.get("avg_latency_seconds", 0.0),
            "p95_latency_seconds": raw.get("p95_latency_seconds", 0.0),
        }
        routing = {
            "rate_limit": raw.get("rate_limit", {}) or {},
            "best_practice": raw.get("best_practice", {}) or {},
            "fallback_strategies": raw.get("fallback_strategies", []) or [],
            "endpoint": raw.get("endpoint", ""),
            "auth_method": raw.get("auth_method", ""),
            "task_types": raw.get("task_types", []) or [],
        }
        raw_config = deepcopy(raw)
        if catalog_profile:
            raw_config["catalog_profile"] = deepcopy(catalog_profile)
        return CatalogSeed(
            model_key=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            provider=str(raw.get("provider", "")).strip(),
            category=category,
            subcategory=subcategory,
            model_family=self._infer_model_family(str(raw.get("name", "")), str(raw.get("id", ""))),
            config_source="models.yaml",
            status=str(raw.get("status", "active")),
            summary=str(raw.get("summary", "")).strip(),
            recommended_scenarios=self._normalize_string_list(raw.get("recommended_scenarios")),
            limitations=self._normalize_string_list(raw.get("limitations")),
            integration_notes=self._normalize_string_list(raw.get("integration_notes")),
            documentation_url=str(raw.get("documentation_url", "")).strip(),
            source_urls=self._normalize_string_list(raw.get("source_urls")),
            tags=tags,
            modalities=modalities,
            capabilities=[item for item in capabilities if isinstance(item, dict)],
            constraints=raw.get("constraints", {}) or {},
            performance=performance,
            routing=routing,
            default_params=raw.get("default_params", {}) or {},
            raw_config=raw_config,
        )

    def _infer_model_category(self, modalities: list[str]) -> str:
        lowered = [item.lower() for item in modalities]
        if any("multimodal" in item or "understanding" in item for item in lowered):
            return "multimodal"
        if any("speech" in item or "voice" in item or "audio" in item for item in lowered):
            return "audio"
        if any("embedding" in item for item in lowered):
            return "embedding"
        if any("video" in item for item in lowered):
            return "video"
        if any("image" in item for item in lowered):
            return "image"
        return "llm"

    def _infer_llm_subcategory(self, capabilities: list[dict[str, Any]], tags: list[str]) -> str:
        names = {str(item.get("name", "")).lower() for item in capabilities}
        lowered_tags = {tag.lower() for tag in tags}
        if "long_context" in names:
            return "长上下文"
        if {"reasoning", "logic", "planning"} & names:
            return "推理审校"
        if {"fast", "simple", "extraction", "chat"} & names or {"fast", "cheap"} & lowered_tags:
            return "轻量快写"
        if {"creative", "writing", "dialogue"} & names:
            return "创作写作"
        return "通用文本"

    def _infer_capability_subcategory(self, modalities: list[str], tags: list[str], model_key: str) -> str:
        lowered = [item.lower() for item in modalities]
        lowered_tags = {tag.lower() for tag in tags}
        if "voice_clone" in lowered or "voice-clone" in lowered_tags:
            return "语音克隆"
        if "text_to_speech" in lowered:
            return "文本转语音"
        if "video_to_audio" in lowered:
            return "视频转音频"
        if "text_to_audio" in lowered:
            return "文生音频"
        if "image_edit" in lowered or "image_to_image_edit" in lowered:
            return "图像编辑"
        if "text_to_video" in lowered:
            return "文生视频"
        if "image_to_video" in lowered:
            return "图生视频"
        if "reference_to_video" in lowered or "video_to_video" in lowered:
            return "参考生视频"
        if "text_to_image" in lowered:
            return "文生图"
        if "multimodal_chat" in lowered or any("understanding" in item for item in lowered):
            return "多模态理解"
        if "embedding" in lowered or "embedding" in model_key.lower():
            return "向量嵌入"
        return "通用能力"

    def _infer_model_family(self, name: str, model_key: str) -> str:
        source = (name or model_key or "").strip()
        match = re.match(r"([A-Za-z]+(?:\s*\d+(?:\.\d+)?)?)", source)
        if match:
            return match.group(1).strip()
        return source

    def _collect_matched_keywords(self, seed: CatalogSeed, content: str) -> list[str]:
        matched: list[str] = []
        for keyword in self._build_alias_keywords(seed):
            if keyword and keyword in content:
                matched.append(f"alias:{keyword}")
        for keyword in self._build_modality_keywords(seed):
            if keyword and keyword in content:
                matched.append(f"modality:{keyword}")
        for keyword in _PROVIDER_KEYWORDS.get(seed.provider, []):
            if keyword and keyword in content:
                matched.append(f"provider:{keyword}")
        return matched

    def _collect_url_matched_keywords(self, seed: CatalogSeed, url: str) -> list[str]:
        lowered_url = (url or "").lower().strip()
        if not lowered_url:
            return []

        compact_url = re.sub(r"[^a-z0-9]+", "", lowered_url)
        matched: list[str] = []

        def _push(prefix: str, value: str) -> None:
            clean_value = str(value or "").strip()
            if not clean_value:
                return
            keyword = f"{prefix}:{clean_value}"
            if keyword not in matched:
                matched.append(keyword)

        for keyword in self._build_alias_keywords(seed):
            compact_keyword = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", keyword)
            if len(compact_keyword) >= 8 and compact_keyword in compact_url:
                _push("alias", keyword)

        if seed.provider == "vidu" and "vidu.cn" in lowered_url:
            if "timing" in (seed.modalities or []) and "timing" in compact_url:
                _push("modality", "timing audio")
                if seed.model_key == "vidu-timing2audio":
                    _push("alias", seed.model_key)

        return matched

    def _build_alias_keywords(self, seed: CatalogSeed) -> list[str]:
        keywords: list[str] = []
        raw_candidates = [seed.model_key, seed.name, *_MODEL_ALIAS_KEYWORDS.get(seed.model_key, [])]
        for candidate in raw_candidates:
            self._append_keyword_variants(keywords, candidate)
        return sorted(set(keywords), key=len, reverse=True)

    def _build_modality_keywords(self, seed: CatalogSeed) -> list[str]:
        keywords = [seed.subcategory.lower(), seed.category.lower()]
        if seed.category == "llm":
            keywords.extend(["text generation", "chat", "reasoning", "长上下文", "推理", "文本生成"])
        elif seed.category == "image":
            keywords.extend(["text to image", "image generation", "image edit", "文生图", "图像编辑"])
        elif seed.category == "video":
            keywords.extend(["text to video", "image to video", "video generation", "文生视频", "图生视频"])
        elif seed.category == "audio":
            keywords.extend(["text to speech", "speech synthesis", "voice clone", "语音合成", "文本转语音"])
            if "text_to_audio" in seed.modalities:
                keywords.extend(["text to audio", "music generation", "sound effect", "文生音频", "音乐生成", "音效生成"])
            if "video_to_audio" in seed.modalities:
                keywords.extend(["video to audio", "视频转音频", "视频补声音"])
        elif seed.category == "multimodal":
            keywords.extend(["multimodal", "vision", "image understanding", "video understanding", "多模态"])
        elif seed.category == "embedding":
            keywords.extend(["embedding", "向量", "嵌入"])
        return sorted({item.lower() for item in keywords if item}, key=len, reverse=True)
