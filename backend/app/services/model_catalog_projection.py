"""模型中心配置投影服务。

使用当前配置文件实时构建模型中心基础卡片，并叠加数据库中的验证状态、
来源校验结果等持久化信息，避免页面继续展示旧版本 metadata。
"""

from __future__ import annotations

from typing import Any, Iterable

from app.models.model_catalog import ModelCatalogEntry
from app.services.model_catalog_bootstrap import build_model_catalog_card_payloads, get_category_label

_EXTRA_RAW_FIELDS = (
    "category_label",
    "project_modules",
    "project_task_labels",
    "tooling_badges",
    "primary_strengths",
    "identity_profile",
    "integration_profile",
    "prompt_router_profile",
    "deployment_profile",
    "resource_navigation",
    "constraints_summary",
    "capability_provenance",
    "error_handlers_summary",
    "usage_guide",
    "pricing_verification",
    "detailed_specs",
)


def build_projected_model_catalog_entries(
    stored_entries: Iterable[ModelCatalogEntry],
    *,
    include_sources: bool = False,
) -> list[dict[str, Any]]:
    stored_by_key = {
        str(entry.model_key).strip(): entry
        for entry in stored_entries
        if str(getattr(entry, "model_key", "")).strip()
    }

    projected: list[dict[str, Any]] = []
    for payload in build_model_catalog_card_payloads():
        projected.append(
            build_projected_model_catalog_entry(
                payload["model_key"],
                stored_by_key.get(payload["model_key"]),
                include_sources=include_sources,
                bootstrap_payload=payload,
            )
        )
    return projected


def build_projected_model_catalog_entry(
    model_key: str,
    stored_entry: ModelCatalogEntry | None = None,
    *,
    include_sources: bool = False,
    bootstrap_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = bootstrap_payload or _find_bootstrap_payload(model_key)
    if payload is None:
        return None

    data = _serialize_bootstrap_payload(payload)
    if stored_entry is None:
        return data

    data["verification_status"] = stored_entry.verification_status
    data["verification_scope"] = stored_entry.verification_scope
    data["verification_score"] = stored_entry.verification_score
    data["total_source_count"] = stored_entry.total_source_count
    data["reachable_source_count"] = stored_entry.reachable_source_count
    data["verified_source_count"] = stored_entry.verified_source_count
    data["verification_notes"] = stored_entry.verification_notes or data.get("verification_notes")
    data["last_synced_at"] = stored_entry.last_synced_at.isoformat() if stored_entry.last_synced_at else None
    data["last_verified_at"] = stored_entry.last_verified_at.isoformat() if stored_entry.last_verified_at else None
    data["updated_at"] = stored_entry.updated_at.isoformat() if stored_entry.updated_at else None

    if include_sources and getattr(stored_entry, "sources", None):
        data["sources"] = [
            {
                "url": source.url,
                "source_type": source.source_type,
                "source_domain": source.source_domain,
                "http_status": source.http_status,
                "reachable": source.reachable,
                "verified": source.verified,
                "page_title": source.page_title,
                "page_excerpt": source.page_excerpt,
                "matched_keywords": source.matched_keywords,
                "verification_note": source.verification_note,
                "fetched_at": source.fetched_at.isoformat() if source.fetched_at else None,
            }
            for source in stored_entry.sources
        ]

    return data


def _find_bootstrap_payload(model_key: str) -> dict[str, Any] | None:
    normalized_key = str(model_key or "").strip()
    if not normalized_key:
        return None

    for payload in build_model_catalog_card_payloads():
        if payload["model_key"] == normalized_key:
            return payload
    return None


def _serialize_bootstrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_config = payload.get("raw_config_json") if isinstance(payload.get("raw_config_json"), dict) else {}

    data: dict[str, Any] = {
        "model_key": payload["model_key"],
        "name": payload["name"],
        "provider": payload["provider"],
        "category": payload["category"],
        "category_label": raw_config.get("category_label") or get_category_label(payload.get("category")),
        "subcategory": payload.get("subcategory"),
        "model_family": payload.get("model_family"),
        "config_source": payload.get("config_source"),
        "status": payload.get("status"),
        "summary": payload.get("summary"),
        "recommended_scenarios": payload.get("recommended_scenarios") or [],
        "limitations": payload.get("limitations") or [],
        "integration_notes": payload.get("integration_notes") or [],
        "documentation_url": payload.get("documentation_url"),
        "source_urls": payload.get("source_urls") or [],
        "tags": payload.get("tags") or [],
        "modalities": payload.get("modalities") or [],
        "capabilities": payload.get("capabilities_json") or [],
        "constraints": payload.get("constraints_json") or {},
        "performance": payload.get("performance_json") or {},
        "routing": payload.get("routing_json") or {},
        "default_params": payload.get("default_params_json") or {},
        "capabilities_json": payload.get("capabilities_json") or [],
        "constraints_json": payload.get("constraints_json") or {},
        "performance_json": payload.get("performance_json") or {},
        "routing_json": payload.get("routing_json") or {},
        "default_params_json": payload.get("default_params_json") or {},
        "raw_config_json": raw_config,
        "verification_status": payload.get("verification_status") or "pending",
        "verification_scope": payload.get("verification_scope"),
        "verification_score": payload.get("verification_score", 0.0),
        "total_source_count": payload.get("total_source_count", 0),
        "reachable_source_count": payload.get("reachable_source_count", 0),
        "verified_source_count": payload.get("verified_source_count", 0),
        "verification_notes": payload.get("verification_notes"),
        "last_synced_at": None,
        "last_verified_at": None,
        "updated_at": None,
    }

    for key in _EXTRA_RAW_FIELDS:
        if key in raw_config:
            data[key] = raw_config[key]

    return data
