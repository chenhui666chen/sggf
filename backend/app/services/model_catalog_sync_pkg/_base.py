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

class ModelCatalogSyncServiceBase:
    """负责从配置读取模型清单、联网核验并同步到数据库。"""

    def __init__(self, config_dir: Optional[Path] = None):
        project_root = Path(__file__).resolve().parents[3]
        self._config_dir = config_dir or (project_root / "config")
        self._llm_config_path = self._config_dir / "llm_models.yaml"
        self._model_config_path = self._config_dir / "models.yaml"
        self._catalog_profile_path = self._config_dir / "model_catalog_profiles.yaml"
        self._runtime_snapshot_path = self._config_dir / "model_catalog_runtime.json"
        self._response_cache: Optional[dict[str, httpx.Response]] = None
        self._fetch_cache_hits = 0
        self._fetch_cache_misses = 0

    def load_catalog_seeds(self) -> list[CatalogSeed]:
        """从配置文件读取模型清单并归一化。"""

        seeds: list[CatalogSeed] = []
        catalog_profiles = self._load_catalog_profiles()

        llm_payload = self._load_yaml(self._llm_config_path)
        for raw in llm_payload.get("llm_models", []) or []:
            model_key = str(raw.get("id", "")).strip()
            seeds.append(
                self._normalize_llm_seed(
                    raw,
                    catalog_profile=catalog_profiles.get(model_key),
                )
            )

        model_payload = self._load_yaml(self._model_config_path)
        for raw in model_payload.get("models", []) or []:
            model_key = str(raw.get("id", "")).strip()
            seeds.append(
                self._normalize_capability_seed(
                    raw,
                    catalog_profile=catalog_profiles.get(model_key),
                )
            )

        return sorted(seeds, key=lambda item: (item.category, item.provider, item.name.lower()))

    def get_entry_queryset(self, db: Session):
        """统一封装查询，默认带来源预加载。"""

        active_model_keys = sorted({seed.model_key for seed in self.load_catalog_seeds()})
        query = db.query(ModelCatalogEntry).options(selectinload(ModelCatalogEntry.sources))
        if not active_model_keys:
            return query.filter(ModelCatalogEntry.id == -1)
        return query.filter(ModelCatalogEntry.model_key.in_(active_model_keys))

    def sync_catalog(
        self,
        db: Session,
        *,
        force_refresh: bool = False,
        model_keys: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """执行配置归档与联网校验同步。
        
        Args:
            db: 数据库会话
            force_refresh: 强制刷新所有模型，忽略更新检测
            model_keys: 指定要校验的模型，未指定时校验所有
        """

        all_seeds = self.load_catalog_seeds()
        all_seed_keys = {seed.model_key for seed in all_seeds}
        seeds = all_seeds
        requested_model_keys: Optional[set[str]] = None
        if model_keys:
            allowed = {item.strip() for item in model_keys if item and item.strip()}
            requested_model_keys = allowed
            seeds = [seed for seed in seeds if seed.model_key in allowed]
        
        # 加载 models.yaml 的配置内容，用于检测模型是否更新
        current_model_configs = {}
        try:
            model_payload = self._load_yaml(self._model_config_path)
            for raw in model_payload.get("models", []) or []:
                model_key = str(raw.get("id", "")).strip()
                if model_key:
                    current_model_configs[model_key] = raw
        except Exception as e:
            logger.warning(f"加载模型配置失败，将跳过更新检测: {e}")

        now = datetime.now(timezone.utc)
        stats = {
            "processed": 0,
            "verified": 0,
            "partial": 0,
            "failed": 0,
            "skipped": 0,
            "skipped_up_to_date": 0,
            "skipped_llm_verification": 0,  # 智能触发跳过LLM联网搜索的模型数
            "updated_at": now.isoformat(),
            "model_keys": [],
            "cache_hits": 0,
            "network_requests": 0,
            "cached_response_count": 0,
            "deleted_obsolete_entries": 0,
            "deleted_model_keys": [],
        }
        previous_cache = self._response_cache
        previous_hits = self._fetch_cache_hits
        previous_misses = self._fetch_cache_misses
        self._response_cache = {}
        self._fetch_cache_hits = 0
        self._fetch_cache_misses = 0

        try:
            deleted_model_keys = self._prune_obsolete_entries(
                db,
                active_model_keys=all_seed_keys,
                restrict_to_model_keys=requested_model_keys,
            )
            stats["deleted_obsolete_entries"] = len(deleted_model_keys)
            stats["deleted_model_keys"] = deleted_model_keys

            for seed in seeds:
                entry = db.query(ModelCatalogEntry).filter(ModelCatalogEntry.model_key == seed.model_key).first()
                if entry and self._should_skip_refresh(
                    entry,
                    seed,
                    current_model_configs.get(seed.model_key),
                    force_refresh=force_refresh,
                    now=now,
                ):
                    stats["skipped"] += 1
                    stats["skipped_up_to_date"] += 1
                    continue

                if entry is None:
                    entry = ModelCatalogEntry(model_key=seed.model_key)
                    db.add(entry)

                self._apply_seed_to_entry(entry, seed)
                db.flush()

                db.query(ModelCatalogSource).filter(ModelCatalogSource.entry_id == entry.id).delete(
                    synchronize_session=False
                )

                # 获取已有entry用于智能触发策略判断
                is_new_entry = entry.id is None or not entry.last_verified_at
                existing_entry_for_check = entry if not is_new_entry else None

                verifications = self._verify_seed(seed, existing_entry=existing_entry_for_check)

                # 统计跳过LLM联网搜索的模型
                skipped_llm = any(
                    "智能触发跳过LLM联网搜索" in v.verification_note
                    for v in verifications
                )
                if skipped_llm:
                    stats["skipped_llm_verification"] += 1
                self._apply_verifications_to_entry(entry, seed, verifications, now)
                
                pricing_result = self._verify_pricing_for_model(seed.model_key)
                self._apply_pricing_to_entry(entry, pricing_result)
                
                capability_issues = self._verify_capability_provenance(seed)
                if capability_issues:
                    entry.verification_notes += f" 能力溯源问题: {', '.join(capability_issues[:3])}"
                
                error_handler_issues = self._verify_error_handlers(seed)
                if error_handler_issues:
                    entry.verification_notes += f" 错误处理问题: {', '.join(error_handler_issues[:3])}"

                for verification in verifications:
                    db.add(
                        ModelCatalogSource(
                            entry_id=entry.id,
                            url=verification.url,
                            source_type=verification.source_type,
                            source_domain=verification.source_domain,
                            http_status=verification.http_status,
                            reachable=verification.reachable,
                            verified=verification.verified,
                            page_title=verification.page_title,
                            page_excerpt=verification.page_excerpt,
                            matched_keywords=verification.matched_keywords,
                            verification_note=verification.verification_note,
                            raw_metadata_json=verification.raw_metadata,
                            fetched_at=verification.fetched_at,
                        )
                    )

                stats["processed"] += 1
                stats["model_keys"].append(seed.model_key)
                stats[entry.verification_status] = stats.get(entry.verification_status, 0) + 1

            stats["cache_hits"] = self._fetch_cache_hits
            stats["network_requests"] = self._fetch_cache_misses
            stats["cached_response_count"] = len(self._response_cache or {})
            db.commit()
            try:
                snapshot_entries = self.get_entry_queryset(db).all()
                self._write_runtime_snapshot(snapshot_entries, generated_at=now)
                stats["runtime_snapshot_updated"] = True
                stats["runtime_snapshot_path"] = str(self._runtime_snapshot_path)
            except Exception as exc:
                logger.warning("写入模型档案运行时快照失败 | path=%s | error=%s", self._runtime_snapshot_path, exc)
                stats["runtime_snapshot_updated"] = False
                stats["runtime_snapshot_error"] = str(exc)
            return stats
        except Exception:
            db.rollback()
            raise
        finally:
            self._response_cache = previous_cache
            self._fetch_cache_hits = previous_hits
            self._fetch_cache_misses = previous_misses

    def _prune_obsolete_entries(
        self,
        db: Session,
        *,
        active_model_keys: set[str],
        restrict_to_model_keys: Optional[set[str]] = None,
    ) -> list[str]:
        deleted_model_keys: list[str] = []
        existing_entries = db.query(ModelCatalogEntry).all()

        for entry in existing_entries:
            model_key = str(entry.model_key or "").strip()
            if not model_key:
                continue
            if model_key in active_model_keys:
                continue
            if restrict_to_model_keys is not None and model_key not in restrict_to_model_keys:
                continue

            db.query(ModelCatalogSource).filter(ModelCatalogSource.entry_id == entry.id).delete(
                synchronize_session=False
            )
            db.query(ModelCatalogEntry).filter(ModelCatalogEntry.id == entry.id).delete(
                synchronize_session=False
            )
            deleted_model_keys.append(model_key)

        if deleted_model_keys:
            db.flush()
        return deleted_model_keys

    def _should_skip_refresh(
        self,
        entry: ModelCatalogEntry,
        seed: "CatalogSeed",
        current_config: Optional[dict[str, Any]] = None,
        *,
        force_refresh: bool = False,
        now: datetime,
    ) -> bool:
        """判断是否应该跳过该模型的校验
        
        跳过条件（满足任一即可）：
        1. force_refresh=False（非强制刷新）
        2. 该模型已被校验过（last_verified_at 不为空）
        3. 模型配置自上次校验后未发生变化
        
        Args:
            entry: 数据库中的模型档案
            seed: 当前加载的种子配置
            current_config: models.yaml 中的当前配置（原始dict）
            force_refresh: 是否强制刷新
            now: 当前时间
        """
        # 强制刷新时不过期
        if force_refresh:
            return False
        
        # 从未校验过的模型需要校验
        if entry.last_verified_at is None:
            return False
        
        # 模型配置未发生变化且已校验过，则跳过
        if not self._has_model_config_changed(entry, seed, current_config):
            return True
        
        return False
    
    def _has_model_config_changed(
        self,
        entry: ModelCatalogEntry,
        seed: "CatalogSeed",
        current_config: Optional[dict[str, Any]] = None,
    ) -> bool:
        """检测模型配置是否自上次校验后发生变化
        
        检测项：
        1. capabilities - 能力列表是否变化
        2. tags - 标签列表是否变化
        3. constraints - 约束条件是否变化
        4. performance - 性能配置是否变化
        
        Args:
            entry: 数据库中的模型档案
            seed: 当前加载的种子配置
            current_config: models.yaml 中的当前配置
            
        Returns:
            True 表示配置已变化，需要重新校验
        """
        if current_config is None:
            # 无法获取当前配置，保守起见需要校验
            return True
        
        # 对比 capabilities
        current_caps = current_config.get("capabilities", [])
        seed_caps = seed.capabilities or []
        if len(current_caps) != len(seed_caps):
            return True
        
        current_cap_names = {c.get("name") for c in current_caps if isinstance(c, dict)}
        seed_cap_names = {c.get("name") for c in seed_caps if isinstance(c, dict)}
        if current_cap_names != seed_cap_names:
            return True
        
        # 对比 tags
        current_tags = set(current_config.get("tags", []))
        seed_tags = set(seed.tags or [])
        if current_tags != seed_tags:
            return True
        
        # 对比 constraints
        current_constraints = current_config.get("constraints", {})
        seed_constraints = seed.constraints or {}
        if current_constraints != seed_constraints:
            return True
        
        # 对比 performance
        current_performance = current_config.get("performance", {})
        seed_performance = seed.performance or {}
        if current_performance != seed_performance:
            return True
        
        return False
