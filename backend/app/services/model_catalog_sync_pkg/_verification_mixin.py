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

class VerificationMixin:
    def _verify_capability_provenance(self, seed: CatalogSeed) -> list[str]:
        """验证能力溯源字段的完整性
        
        Args:
            seed: 模型种子信息
            
        Returns:
            问题列表，如果所有能力溯源完整则返回空列表
        """
        issues = []
        capabilities = seed.capabilities or []
        
        for cap in capabilities:
            if not isinstance(cap, dict):
                continue
            
            cap_name = cap.get("name", "unnamed")
            
            if not cap.get("source") or cap.get("source", "").startswith("TODO"):
                issues.append(f"{cap_name}: 缺少溯源来源(source)")
            
            if not cap.get("verified_at"):
                issues.append(f"{cap_name}: 缺少验证时间(verified_at)")
            
            if not cap.get("confidence") or cap.get("confidence") not in ("high", "medium", "low"):
                issues.append(f"{cap_name}: 置信度(confidence)无效")
        
        return issues
    
    def _verify_error_handlers(self, seed: CatalogSeed) -> list[str]:
        """验证 error_handlers 配置的完整性
        
        检查项：
        1. content_safety - 内容安全错误处理配置
        2. rate_limit - 限流错误处理配置
        3. timeout - 超时错误处理配置
        4. fallback_model - 降级模型是否有效
        
        Args:
            seed: 模型种子信息
            
        Returns:
            问题列表，如果 error_handlers 配置完整则返回空列表
        """
        issues = []
        raw_config = seed.raw_config or {}
        error_handlers = raw_config.get("error_handlers", {})
        
        if not error_handlers:
            # error_handlers 是可选的，没有配置不报错
            return issues
        
        # 检查 content_safety
        content_safety = error_handlers.get("content_safety", {})
        if content_safety:
            if not content_safety.get("action"):
                issues.append("content_safety: 缺少 action 配置")
            if not content_safety.get("retry") is None and not isinstance(content_safety.get("retry"), bool):
                issues.append("content_safety: retry 应为布尔值")
        
        # 检查 rate_limit
        rate_limit = error_handlers.get("rate_limit", {})
        if rate_limit:
            if not rate_limit.get("action"):
                issues.append("rate_limit: 缺少 action 配置")
            wait_seconds = rate_limit.get("wait_seconds")
            if wait_seconds is not None and (not isinstance(wait_seconds, (int, float)) or wait_seconds <= 0):
                issues.append("rate_limit: wait_seconds 应为正数")
        
        # 检查 timeout
        timeout = error_handlers.get("timeout", {})
        if timeout:
            if not timeout.get("action"):
                issues.append("timeout: 缺少 action 配置")
            fallback_model = timeout.get("fallback_model")
            if fallback_model and not isinstance(fallback_model, str):
                issues.append("timeout: fallback_model 应为字符串")
        
        return issues
    
    def _run_three_layer_consistency_check(self, model_keys: Optional[list[str]] = None) -> dict[str, Any]:
        """运行三层配置一致性校验（intent_domains <-> models <-> semantic_matcher）
        
        Args:
            model_keys: 可选，仅校验指定模型
            
        Returns:
            校验结果字典
        """
        try:
            import importlib
            import sys
            
            # 确保项目根目录在 sys.path 中
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            # 动态导入 verify_model_config 模块
            spec = importlib.util.spec_from_file_location(
                "verify_model_config",
                project_root / "scripts" / "verify_model_config.py",
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            issues = module.Issues()
            domains = module.load_domains()
            models = module.load_models()
            matcher_vocab = module.load_matcher_vocab()
            
            if model_keys:
                models = [m for m in models if m.get("id") in model_keys]
            
            module.check_style_vocab(domains, matcher_vocab, issues)
            module.check_model_tags(domains, models, issues)
            module.check_model_capabilities(models, issues)
            module.check_video_models_in_tags(domains, models, issues)
            module.check_camera_terms(domains, matcher_vocab, issues)
            
            return {
                "check_status": "completed",
                "errors": issues.errors,
                "warnings": issues.warnings,
                "fixes": issues.fixes,
                "is_consistent": issues.ok(),
                "error_count": len(issues.errors),
                "warning_count": len(issues.warnings),
            }
        except Exception as e:
            logger.warning(f"三层配置一致性校验失败: {e}")
            return {
                "check_status": "failed",
                "errors": [str(e)],
                "warnings": [],
                "fixes": [],
                "is_consistent": False,
                "error_count": 1,
                "warning_count": 0,
            }
