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

class PricingMixin:
    def _verify_pricing_for_model(self, model_key: str) -> dict[str, Any]:
        """校验模型价格信息
        
        Args:
            model_key: 模型标识符
            
        Returns:
            价格校验结果字典，包含 verified/pricing/source/verified_at 字段
        """
        if model_key in VERIFIED_PRICING_DATA:
            pricing = VERIFIED_PRICING_DATA[model_key]
            first_tier = next(iter(pricing.values())) if pricing else {}
            source_url = first_tier.get("source", "") if isinstance(first_tier, dict) else ""
            
            return {
                "verified": True,
                "pricing": pricing,
                "source": source_url or "多渠道交叉验证",
                "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "confidence": "high",
            }
        
        return {
            "verified": False,
            "pricing": None,
            "source": "未在已验证价格数据库中找到",
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "confidence": "low",
        }
    
    async def _verify_pricing_from_provider(
        self,
        seed: dict[str, Any],
        model_key: str,
    ) -> Optional[dict[str, Any]]:
        """
        Verify pricing information from cloud provider.
        
        Args:
            seed: Model seed data from models.yaml
            model_key: Model identifier
        
        Returns:
            Pricing information dict or None if verification failed
        """
        api_config = seed.get("api_config", {})
        auth_type = api_config.get("auth_type", "")
        
        # Only verify pricing for Alibaba Cloud DashScope
        if auth_type != "alibaba_cloud_dashscope":
            return None
        
        pricing_config = PRICING_VERIFICATION_CONFIG.get(auth_type)
        if not pricing_config:
            return None
        
        pricing_url = pricing_config["pricing_url"]
        timeout = pricing_config["timeout_seconds"]
        
        try:
            # Fetch pricing page
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(pricing_url)
                response.raise_for_status()
                html_content = response.text
            
            # Extract pricing information from HTML
            pricing_info = self._extract_pricing_from_html(html_content, model_key)
            
            if pricing_info:
                logger.info(
                    "Verified pricing for %s: %s",
                    model_key,
                    pricing_info.get("price", "N/A")
                )
                return {
                    "success": True,
                    "pricing": pricing_info,
                    "source_url": pricing_url,
                    "verified_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                logger.warning("Could not extract pricing for %s from %s", model_key, pricing_url)
                return None
        
        except httpx.TimeoutException as e:
            logger.warning("Timeout fetching pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Timeout: {str(e)}"}
        except httpx.RequestError as e:
            logger.warning("Request error fetching pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Request error: {str(e)}"}
        except Exception as e:
            logger.warning("Error verifying pricing for %s: %s", model_key, e)
            return {"success": False, "error": f"Error: {str(e)}"}
    
    def _extract_pricing_from_html(
        self,
        html_content: str,
        model_key: str,
    ) -> Optional[dict[str, Any]]:
        """
        Extract pricing information from HTML content.
        
        Args:
            html_content: HTML content from pricing page
            model_key: Model identifier to search for
        
        Returns:
            Pricing information dict or None
        """
        # Clean HTML content
        text = _SCRIPT_STYLE_RE.sub("", html_content)
        text = _TAG_RE.sub(" ", text)
        text = unescape(text)
        text = _SPACE_RE.sub(" ", text).strip()
        
        # Search for model-specific pricing
        # Example: "MiniMax/speech-2.8-hd 3.5 元"
        model_name = model_key.replace("-", "/")  # Convert model ID to official name
        
        # Try to find pricing pattern
        pricing_patterns = [
            rf"{re.escape(model_name)}.*?(\d+\.?\d*)\s*元",
            rf"(\d+\.?\d*)\s*元.*?{re.escape(model_name)}",
        ]
        
        for pattern in pricing_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                price = float(match.group(1))
                return {
                    "price": price,
                    "currency": "CNY",
                    "unit": "元/万字符",
                    "model": model_name,
                }
        
        # If specific price not found, return general pricing info
        return {
            "note": "价格请以阿里云百炼平台实时价格为准",
            "pricing_url": "https://help.aliyun.com/zh/model-studio/pricing",
        }

    def _apply_seed_to_entry(self, entry: ModelCatalogEntry, seed: CatalogSeed) -> None:
        entry.name = seed.name
        entry.provider = seed.provider
        entry.category = seed.category
        entry.subcategory = seed.subcategory
        entry.model_family = seed.model_family
        entry.config_source = seed.config_source
        entry.status = seed.status
        entry.summary = seed.summary
        entry.recommended_scenarios = seed.recommended_scenarios
        entry.limitations = seed.limitations
        entry.integration_notes = seed.integration_notes
        entry.documentation_url = seed.documentation_url
        entry.source_urls = seed.source_urls
        entry.tags = seed.tags
        entry.modalities = seed.modalities
        entry.capabilities_json = {"items": seed.capabilities}
        entry.constraints_json = seed.constraints
        entry.performance_json = seed.performance
        entry.routing_json = seed.routing
        entry.default_params_json = seed.default_params
        entry.raw_config_json = seed.raw_config

    def _apply_verifications_to_entry(
        self,
        entry: ModelCatalogEntry,
        seed: CatalogSeed,
        verifications: list[SourceVerification],
        synced_at: datetime,
    ) -> None:
        reachable = sum(1 for item in verifications if item.reachable)
        verified = sum(1 for item in verifications if item.verified)
        avg_score = sum(item.score for item in verifications) / len(verifications) if verifications else 0.0

        if reachable >= 2 and verified >= 1:
            status = "verified"
            note = "至少两个来源可达，且已识别模型身份与主模态。"
        elif reachable >= 1:
            status = "partial"
            note = "已完成单源或弱匹配校验，建议继续补充官方来源。"
        else:
            status = "failed"
            note = "当前未能访问可用来源，请稍后重试或检查文档链接。"

        entry.verification_status = status
        entry.verification_scope = "模型身份 + 提供商 + 主模态"
        entry.verification_score = round(avg_score, 4)
        entry.total_source_count = len(verifications)
        entry.reachable_source_count = reachable
        entry.verified_source_count = verified
        entry.verification_notes = note
        entry.last_synced_at = synced_at
        entry.last_verified_at = synced_at

        extracted_specs_list = [
            DetailedSpecExtraction(
                duration_range=item.extracted_specs.get("duration_range"),
                resolution_options=item.extracted_specs.get("resolution_options", []),
                frame_rate=item.extracted_specs.get("frame_rate"),
                output_format=item.extracted_specs.get("output_format"),
                input_modalities=item.extracted_specs.get("input_modalities", []),
                advanced_features=item.extracted_specs.get("advanced_features", []),
                max_reference_images=item.extracted_specs.get("max_reference_images"),
                weight_control=item.extracted_specs.get("weight_control", False),
                first_frame_support=item.extracted_specs.get("first_frame_support", False),
                last_frame_support=item.extracted_specs.get("last_frame_support", False),
                prompt_examples=item.extracted_specs.get("prompt_examples", []),
                extraction_confidence=item.extracted_specs.get("extraction_confidence", 0.0),
                extraction_source=item.extracted_specs.get("extraction_source", ""),
            )
            for item in verifications
            if item.extracted_specs and item.extracted_specs.get("extraction_confidence", 0) > 0.2
        ]

        if extracted_specs_list:
            existing_specs = (entry.raw_config_json or {}).get("detailed_specs", {})
            merged_specs = self._merge_extracted_specs(extracted_specs_list, existing_specs, seed.category)
            if merged_specs:
                entry.raw_config_json = {
                    **(entry.raw_config_json or {}),
                    "detailed_specs": merged_specs,
                }
                note += f" 已从 {len(extracted_specs_list)} 个来源提取详细规格。"

    def _apply_pricing_to_entry(self, entry: ModelCatalogEntry, pricing_result: dict[str, Any]) -> None:
        """将价格校验结果应用到模型档案
        
        Args:
            entry: 模型档案实体
            pricing_result: 价格校验结果
        """
        raw_config = entry.raw_config_json or {}
        
        existing_pricing = raw_config.get("pricing_verification", {})
        
        updated_pricing = {
            **existing_pricing,
            "last_verified_at": pricing_result.get("verified_at"),
            "pricing_status": "verified" if pricing_result.get("verified") else "unverified",
            "confidence": pricing_result.get("confidence", "low"),
            "source": pricing_result.get("source", ""),
        }
        
        if pricing_result.get("verified") and pricing_result.get("pricing"):
            verified_pricing = pricing_result["pricing"]
            first_tier = next(iter(verified_pricing.values())) if verified_pricing else {}
            
            if isinstance(first_tier, dict):
                updated_pricing["price"] = first_tier.get("price")
                updated_pricing["unit"] = first_tier.get("unit")
                updated_pricing["currency"] = "CNY"
                updated_pricing["pricing_tiers"] = verified_pricing
                
                cost_profile = entry.performance_json.get("cost_profile", {}) or {}
                cost_profile["price"] = first_tier.get("price")
                cost_profile["unit"] = first_tier.get("unit")
                cost_profile["currency"] = "CNY"
                cost_profile["pricing_verified"] = True
                entry.performance_json = {
                    **entry.performance_json,
                    "cost_profile": cost_profile,
                }
        
        raw_config["pricing_verification"] = updated_pricing
        entry.raw_config_json = raw_config
