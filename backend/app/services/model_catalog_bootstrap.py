"""从当前配置文件构建模型中心基础卡片数据。"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.services.audiobook.tts_model_ids import (
    get_audiobook_tts_style_capabilities,
    is_supported_audiobook_tts_model,
    normalize_audiobook_tts_model,
)

CATEGORY_LABELS: dict[str, str] = {
    "llm": "文本LLM",
    "image": "图像生成",
    "audio": "音频生成",
    "video": "视频生成",
    "multimodal": "多模态",
}

_IMAGE_MODALITIES = {
    "text_to_image",
    "image_to_image",
    "image_edit",
    "image_to_image_edit",
}
_AUDIO_MODALITIES = {
    "text_to_speech",
    "text_to_audio",
    "timing_audio",
    "voice_clone",
}
_VIDEO_MODALITIES = {
    "text_to_video",
    "image_to_video",
    "reference_to_video",
    "start_end_to_video",
    "video_to_video",
    "video_edit",
    "audio_to_video",
}
_MULTIMODAL_MODALITIES = {
    "image_understanding",
    "video_understanding",
    "image_to_text",
    "video_to_text",
    "multimodal_chat",
}
_PENDING_VERIFICATION_NOTE = (
    "当前仅按已接入配置生成模型卡片，能力、价格、约束、来源与验证状态待后续人工逐项校验。"
)


def get_category_label(category: str | None) -> str:
    normalized = str(category or "").strip().lower()
    return CATEGORY_LABELS.get(normalized, str(category or "未分类"))


def build_model_catalog_card_payloads(project_root: Path | None = None) -> list[dict[str, Any]]:
    """基于当前配置构建模型卡片。"""

    root = _resolve_project_root(project_root)
    llm_config = _load_yaml(root / "config" / "llm_models.yaml")
    media_config = _load_yaml(root / "config" / "models.yaml")
    profile_config = _load_yaml(root / "config" / "model_catalog_profiles.yaml")

    profiles = profile_config.get("profiles") if isinstance(profile_config.get("profiles"), dict) else {}
    merged: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for item in llm_config.get("llm_models") or []:
        if isinstance(item, dict):
            payload = _build_payload_from_source(item, "llm_models.yaml", profiles.get(item.get("id")))
            merged[payload["model_key"]] = payload

    for item in media_config.get("models") or []:
        if not isinstance(item, dict):
            continue

        payload = _build_payload_from_source(item, "models.yaml", profiles.get(item.get("id")))
        existing = merged.get(payload["model_key"])
        if existing is None:
            merged[payload["model_key"]] = payload
        else:
            merged[payload["model_key"]] = _merge_payloads(existing, payload)

    return list(merged.values())


def _resolve_project_root(project_root: Path | None) -> Path:
    if project_root is not None:
        return project_root
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件格式无效: {path}")
    return payload


def _build_payload_from_source(
    item: dict[str, Any],
    source_name: str,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    model_key = str(item.get("id") or "").strip()
    if not model_key:
        raise ValueError(f"发现缺少 id 的模型配置: {source_name}")

    category = _infer_category(item, source_name)
    category_label = get_category_label(category)
    provider = str(item.get("provider") or "unknown").strip() or "unknown"
    name = str(item.get("name") or model_key).strip() or model_key
    status = str(item.get("status") or "active").strip() or "active"
    capabilities = list(item.get("capabilities") or [])
    modalities = _infer_modalities(item, source_name, capabilities)
    tags = _build_tags(category, provider, modalities, capabilities, item)
    primary_strengths = _build_primary_strengths(capabilities, item)
    recommended_scenarios = _build_recommended_scenarios(item)
    limitations = _normalize_string_list(item.get("limitations"))
    integration_notes = _normalize_string_list(item.get("integration_notes"))
    documentation_url = _normalize_optional_text(item.get("documentation_url"))
    source_urls = _build_source_urls(item, documentation_url)
    summary = _build_summary(item, profile, category_label)
    routing = item.get("routing") if isinstance(item.get("routing"), dict) else {}
    constraints = item.get("constraints") if isinstance(item.get("constraints"), dict) else {}
    api_config = item.get("api_config") if isinstance(item.get("api_config"), dict) else {}

    extra = _build_extra_frontend_payload(
        item=item,
        profile=profile or {},
        category=category,
        category_label=category_label,
        summary=summary,
        primary_strengths=primary_strengths,
        recommended_scenarios=recommended_scenarios,
        limitations=limitations,
        integration_notes=integration_notes,
        modalities=modalities,
        tags=tags,
        source_urls=source_urls,
        documentation_url=documentation_url,
        routing=routing,
        constraints=constraints,
        api_config=api_config,
    )

    return {
        "model_key": model_key,
        "name": name,
        "provider": provider,
        "category": category,
        "subcategory": _build_subcategory(item),
        "model_family": _build_model_family(item, name),
        "config_source": source_name,
        "status": status,
        "summary": summary,
        "recommended_scenarios": recommended_scenarios,
        "limitations": limitations,
        "integration_notes": integration_notes,
        "documentation_url": documentation_url,
        "source_urls": source_urls,
        "tags": tags,
        "modalities": modalities,
        "capabilities_json": capabilities,
        "constraints_json": constraints,
        "performance_json": _build_performance_payload(item),
        "routing_json": routing,
        "default_params_json": item.get("default_params") if isinstance(item.get("default_params"), dict) else {},
        "raw_config_json": {
            "source_name": source_name,
            "source_record": item,
            "profile_record": profile or {},
            **extra,
        },
        "verification_status": "pending",
        "verification_scope": "bootstrap_pending",
        "verification_score": 0.0,
        "total_source_count": len(source_urls),
        "reachable_source_count": 0,
        "verified_source_count": 0,
        "verification_notes": _PENDING_VERIFICATION_NOTE,
    }


def _merge_payloads(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged["config_source"] = "merged"
    merged["subcategory"] = merged.get("subcategory") or extra.get("subcategory")
    merged["model_family"] = merged.get("model_family") or extra.get("model_family")
    merged["summary"] = _pick_longer_text(merged.get("summary"), extra.get("summary"))
    merged["recommended_scenarios"] = _merge_unique_strings(
        merged.get("recommended_scenarios"),
        extra.get("recommended_scenarios"),
    )
    merged["limitations"] = _merge_unique_strings(merged.get("limitations"), extra.get("limitations"))
    merged["integration_notes"] = _merge_unique_strings(
        merged.get("integration_notes"),
        extra.get("integration_notes"),
    )
    merged["source_urls"] = _merge_unique_strings(merged.get("source_urls"), extra.get("source_urls"))
    merged["tags"] = _merge_unique_strings(merged.get("tags"), extra.get("tags"))
    merged["modalities"] = _merge_unique_strings(merged.get("modalities"), extra.get("modalities"))
    merged["capabilities_json"] = _merge_capabilities(merged.get("capabilities_json"), extra.get("capabilities_json"))
    merged["constraints_json"] = _deep_merge_dict(merged.get("constraints_json"), extra.get("constraints_json"))
    merged["performance_json"] = _deep_merge_dict(merged.get("performance_json"), extra.get("performance_json"))
    merged["routing_json"] = _deep_merge_dict(merged.get("routing_json"), extra.get("routing_json"))
    merged["default_params_json"] = _deep_merge_dict(
        merged.get("default_params_json"),
        extra.get("default_params_json"),
    )
    merged["raw_config_json"] = _deep_merge_dict(merged.get("raw_config_json"), extra.get("raw_config_json"))
    merged["total_source_count"] = len(merged["source_urls"])
    return merged


def _infer_category(item: dict[str, Any], source_name: str) -> str:
    if source_name == "llm_models.yaml":
        return "llm"

    modalities = {str(value).strip().lower() for value in (item.get("modality") or []) if str(value).strip()}
    if modalities & _MULTIMODAL_MODALITIES:
        return "multimodal"
    if modalities & _VIDEO_MODALITIES:
        return "video"
    if modalities & _AUDIO_MODALITIES:
        return "audio"
    if modalities & _IMAGE_MODALITIES:
        return "image"
    return "llm"


def _infer_modalities(item: dict[str, Any], source_name: str, capabilities: list[Any]) -> list[str]:
    source_modalities = _normalize_string_list(item.get("modality"))
    if source_modalities:
        return source_modalities

    if source_name != "llm_models.yaml":
        return []

    inferred = ["text_to_text"]
    constraints = item.get("constraints") if isinstance(item.get("constraints"), dict) else {}
    capability_names = {str(cap.get("name") or "").strip().lower() for cap in capabilities if isinstance(cap, dict)}
    if constraints.get("supports_vision") or "multimodal" in capability_names:
        inferred.extend(["image_understanding", "video_understanding"])
    return _merge_unique_strings(inferred)


def _build_subcategory(item: dict[str, Any]) -> str | None:
    for key in ("version", "subcategory"):
        value = _normalize_optional_text(item.get(key))
        if value:
            return value
    return None


def _build_model_family(item: dict[str, Any], name: str) -> str | None:
    explicit = _normalize_optional_text(item.get("model_family"))
    if explicit:
        return explicit
    token = str(name or "").strip().split(" ", maxsplit=1)[0]
    return token or None


def _build_tags(
    category: str,
    provider: str,
    modalities: list[str],
    capabilities: list[Any],
    item: dict[str, Any],
) -> list[str]:
    capability_names = [
        _humanize_token(capability.get("name"))
        for capability in capabilities
        if isinstance(capability, dict) and capability.get("name")
    ]
    user_tags = _normalize_string_list(item.get("tags"))
    return _merge_unique_strings([category, provider], modalities, capability_names[:6], user_tags)


def _build_primary_strengths(capabilities: list[Any], item: dict[str, Any]) -> list[str]:
    strengths: list[str] = []
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        label = _normalize_optional_text(capability.get("label"))
        description = _normalize_optional_text(capability.get("description"))
        name = _normalize_optional_text(capability.get("name"))
        candidate = label or (description if description and len(description) <= 24 else None) or _humanize_token(name)
        if candidate:
            strengths.append(candidate)

    if not strengths:
        strengths = _build_recommended_scenarios(item)
    return _merge_unique_strings(strengths)[:6]


def _build_recommended_scenarios(item: dict[str, Any]) -> list[str]:
    direct = _normalize_string_list(item.get("recommended_scenarios"))
    if direct:
        return direct

    routing = item.get("routing") if isinstance(item.get("routing"), dict) else {}
    task_types = routing.get("task_types") if isinstance(routing.get("task_types"), list) else []
    return [_humanize_token(value) for value in task_types if str(value).strip()]


def _build_summary(item: dict[str, Any], profile: dict[str, Any] | None, category_label: str) -> str:
    summary = _normalize_optional_text(item.get("summary"))
    if summary:
        return summary

    role_summary = _normalize_optional_text((profile or {}).get("role_summary"))
    if role_summary:
        return role_summary

    name = str(item.get("name") or item.get("id") or "模型").strip()
    return f"{name} 已完成项目接入，当前先生成基础{category_label}卡片，详细能力与约束待人工校验补全。"


def _build_source_urls(item: dict[str, Any], documentation_url: str | None) -> list[str]:
    source_urls = _normalize_string_list(item.get("source_urls"))
    capability_source_urls: list[str] = []
    for capability in item.get("capabilities") or []:
        if not isinstance(capability, dict):
            continue
        source = _normalize_optional_text(capability.get("source"))
        if source and source.startswith("http"):
            capability_source_urls.append(source)
    return _merge_unique_strings(source_urls, [documentation_url] if documentation_url else [], capability_source_urls)


def _build_performance_payload(item: dict[str, Any]) -> dict[str, Any]:
    performance = item.get("performance") if isinstance(item.get("performance"), dict) else {}
    quality_metrics = item.get("quality_metrics") if isinstance(item.get("quality_metrics"), dict) else {}
    cost_profile = item.get("cost_profile") if isinstance(item.get("cost_profile"), dict) else {}
    payload = dict(performance)
    if quality_metrics:
        payload.setdefault("quality_metrics", quality_metrics)
    if cost_profile:
        payload.setdefault("cost_profile", cost_profile)
    for field in ("avg_latency_seconds", "p95_latency_seconds", "rate_limit"):
        value = item.get(field)
        if value is not None:
            payload.setdefault(field, value)
    return payload


def _build_extra_frontend_payload(
    *,
    item: dict[str, Any],
    profile: dict[str, Any],
    category: str,
    category_label: str,
    summary: str,
    primary_strengths: list[str],
    recommended_scenarios: list[str],
    limitations: list[str],
    integration_notes: list[str],
    modalities: list[str],
    tags: list[str],
    source_urls: list[str],
    documentation_url: str | None,
    routing: dict[str, Any],
    constraints: dict[str, Any],
    api_config: dict[str, Any],
) -> dict[str, Any]:
    task_labels = _merge_unique_strings(
        recommended_scenarios,
        [_humanize_token(value) for value in (routing.get("task_types") or [])],
    )
    official_sources = [
        {"label": f"参考文档 {index + 1}", "url": url}
        for index, url in enumerate(source_urls)
        if url
    ]
    env_bindings = _build_environment_bindings(api_config)
    project_entrypoints = [
        {"label": str(entry.get("label") or "").strip(), "value": str(entry.get("value") or "").strip()}
        for entry in (profile.get("project_entrypoints") or [])
        if isinstance(entry, dict) and str(entry.get("label") or "").strip() and str(entry.get("value") or "").strip()
    ]
    context_window = _build_context_window_items(constraints)
    detailed_specs = _build_detailed_specs(item)

    return {
        "category_label": category_label,
        "project_modules": _infer_project_modules(category, modalities),
        "project_task_labels": task_labels,
        "tooling_badges": _normalize_string_list(profile.get("tooling_badges")),
        "primary_strengths": primary_strengths,
        "identity_profile": {
            "core_positioning": _normalize_optional_text(profile.get("role_summary")) or summary,
            "model_lineage": [
                {"label": "配置来源", "value": str(item.get("id") or "")},
                {"label": "提供商", "value": str(item.get("provider") or "unknown")},
            ],
            "context_window": context_window,
            "capability_quadrants": {
                "strengths": primary_strengths,
                "weaknesses": limitations[:6],
                "modalities": modalities,
                "capability_tags": tags[:8],
            },
            "project_fit": {
                "modules": _infer_project_modules(category, modalities),
                "task_types": task_labels[:8],
                "role_summary": _normalize_optional_text(profile.get("role_summary")) or summary,
            },
        },
        "integration_profile": {
            "calling_stack": [],
            "native_parameters": [],
            "response_features": [],
            "environment_bindings": env_bindings,
            "client_entrypoints": project_entrypoints,
            "api_references": official_sources,
            "tooling_badges": _normalize_string_list(profile.get("tooling_badges")),
            "recommended_wrapper": "建议统一通过项目模型封装层调用，当前仅完成基础建卡，细节待人工校验。",
            "sdk_templates": {},
        },
        "prompt_router_profile": {
            "system_role": _normalize_optional_text(profile.get("system_role")) or "",
            "prompt_patterns": [
                {
                    "title": str(pattern.get("title") or "").strip(),
                    "template": str(pattern.get("template") or "").strip(),
                }
                for pattern in (profile.get("prompt_patterns") or [])
                if isinstance(pattern, dict) and str(pattern.get("title") or "").strip()
            ],
            "router_rules": [
                {
                    "when": str(rule.get("when") or "").strip(),
                    "action": str(rule.get("action") or "").strip(),
                    "reason": str(rule.get("reason") or "").strip(),
                }
                for rule in (profile.get("router_rules") or [])
                if isinstance(rule, dict) and str(rule.get("when") or "").strip()
            ],
            "best_practice_tips": _normalize_string_list(profile.get("best_practice_tips")),
            "fallback_chain": _normalize_string_list(routing.get("fallback_models")),
        },
        "deployment_profile": {
            "access_topology": [],
            "project_entrypoints": project_entrypoints,
            "environment_convention": env_bindings,
            "local_deployment_note": _normalize_optional_text(profile.get("local_deployment_note")) or "已接入，部署说明待后续补全。",
            "proxy_snippet": "",
        },
        "resource_navigation": {
            "official_sources": official_sources,
            "selection_hubs": [],
            "model_hubs": [],
            "provider_portals": (
                [{"label": "官方文档", "url": documentation_url}]
                if documentation_url
                else []
            ),
        },
        "constraints_summary": _build_constraints_summary(item, constraints),
        "capability_provenance": _build_capability_provenance(item),
        "usage_guide": {
            "title": f"{item.get('name') or item.get('id')} 使用说明待校验",
            "sections": [
                {
                    "title": "待人工校验",
                    "content": _PENDING_VERIFICATION_NOTE,
                    "tips": integration_notes[:5],
                }
            ],
        },
        "detailed_specs": detailed_specs,
    }


def _build_detailed_specs(item: dict[str, Any]) -> dict[str, Any]:
    detailed_specs = deepcopy(item.get("detailed_specs")) if isinstance(item.get("detailed_specs"), dict) else {}
    model_id = str(item.get("id") or "").strip()
    if not model_id or not is_supported_audiobook_tts_model(model_id):
        return detailed_specs

    voice_synthesis = (
        deepcopy(detailed_specs.get("voice_synthesis"))
        if isinstance(detailed_specs.get("voice_synthesis"), dict)
        else {}
    )
    existing_style_control = (
        deepcopy(voice_synthesis.get("style_control"))
        if isinstance(voice_synthesis.get("style_control"), dict)
        else {}
    )
    voice_synthesis["style_control"] = _deep_merge_dict(
        _build_tts_style_control_spec(model_id),
        existing_style_control,
    )
    detailed_specs["voice_synthesis"] = voice_synthesis
    return detailed_specs


def _build_tts_style_control_spec(model_id: str) -> dict[str, Any]:
    normalized_model = normalize_audiobook_tts_model(model_id)
    capabilities = get_audiobook_tts_style_capabilities(normalized_model)
    modes = [
        {
            "id": mode,
            "label": _tts_style_control_mode_label(mode),
            "description": _tts_style_control_mode_description(mode),
        }
        for mode in capabilities.get("style_control_modes") or []
    ]
    advanced_controls = [
        label
        for key, label in (
            ("supports_voice_description", "声音描述融合"),
            ("supports_director_mode", "导演模式"),
            ("supports_audio_tags", "音频标签"),
            ("supports_emotion_mixing", "复合情绪"),
            ("supports_micro_tags", "微表演标签"),
            ("supports_word_level_control", "词/字级控制"),
        )
        if capabilities.get(key)
    ]

    return {
        "model_family": capabilities.get("model_family") or "generic",
        "preferred_mode": capabilities.get("preferred_style_control_mode") or "natural_language",
        "modes": modes,
        "supports_voice_description": bool(capabilities.get("supports_voice_description")),
        "supports_director_mode": bool(capabilities.get("supports_director_mode")),
        "supports_audio_tags": bool(capabilities.get("supports_audio_tags")),
        "supports_emotion_mixing": bool(capabilities.get("supports_emotion_mixing")),
        "supports_micro_tags": bool(capabilities.get("supports_micro_tags")),
        "supports_word_level_control": bool(capabilities.get("supports_word_level_control")),
        "instruction_budget": capabilities.get("instruction_budget"),
        "control_message_roles": capabilities.get("control_message_roles") or {},
        "advanced_controls": advanced_controls,
        "project_integration_status": "runtime_registered",
    }


def _tts_style_control_mode_label(mode: Any) -> str:
    labels = {
        "natural_language": "自然语言指令",
        "director": "导演模式",
        "audio_tags": "音频标签",
        "basic": "基础参数",
    }
    return labels.get(str(mode or "").strip(), str(mode or "").strip())


def _tts_style_control_mode_description(mode: Any) -> str:
    descriptions = {
        "natural_language": "将语气、场景、情绪和声音描述写入自然语言控制字段。",
        "director": "按角色、场景、指导组织成导演式表演指令。",
        "audio_tags": "在合成文本中插入整体风格标签和细粒度音频标签。",
        "basic": "仅使用模型基础参数，不承诺可消费复杂声音描述。",
    }
    return descriptions.get(str(mode or "").strip(), "")


def _build_environment_bindings(api_config: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    api_key_env = _normalize_optional_text(api_config.get("api_key_env"))
    if api_key_env:
        bindings.append({"label": api_key_env, "value": "调用该模型所需的 API Key 环境变量。", "required": True})

    base_url = _normalize_optional_text(api_config.get("base_url"))
    if base_url:
        bindings.append({"label": "base_url", "value": base_url})
    return bindings


def _build_context_window_items(constraints: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for label, key in (
        ("最大上下文", "max_context_tokens"),
        ("上下文窗口", "context_window"),
        ("最大输出", "max_output_tokens"),
        ("最大输出长度", "max_output_length"),
        ("最大提示长度", "max_prompt_length"),
    ):
        value = constraints.get(key)
        if value is None:
            continue
        items.append({"label": label, "value": str(value)})
    return items


def _infer_project_modules(category: str, modalities: list[str]) -> list[str]:
    modules: list[str] = ["模型中心"]
    if category == "llm":
        modules.extend(["小说工作台", "协同扩写"])
    if category == "audio":
        modules.extend(["有声书", "资产工作台"])
    if category == "video":
        modules.extend(["DreamWeaver", "资产工作台"])
    if category == "image":
        modules.append("资产工作台")
    if category == "multimodal":
        modules.extend(["资产工作台", "智能分析"])
    if "voice_clone" in modalities:
        modules.append("音色管理")
    return _merge_unique_strings(modules)


def _build_constraints_summary(item: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    duration_values = [
        float(value)
        for value in (constraints.get("duration") or [])
        if isinstance(value, (int, float))
    ]
    if duration_values:
        summary["duration"] = {
            "min_seconds": int(min(duration_values)),
            "max_seconds": int(max(duration_values)),
            "available_options": [int(value) for value in duration_values],
        }

    aspect_ratios = _normalize_string_list(constraints.get("ratios") or constraints.get("aspect_ratios"))
    if aspect_ratios:
        summary["aspect_ratios"] = aspect_ratios

    if any(key in constraints for key in ("min_width", "max_width", "min_height", "max_height")):
        summary["resolution"] = {
            "min_width": _to_optional_int(constraints.get("min_width")),
            "max_width": _to_optional_int(constraints.get("max_width")),
            "min_height": _to_optional_int(constraints.get("min_height")),
            "max_height": _to_optional_int(constraints.get("max_height")),
        }

    max_batch_size = _to_optional_int(constraints.get("max_batch_size"))
    if max_batch_size is not None:
        summary["max_batch_size"] = max_batch_size

    for key in ("max_prompt_length", "max_context_tokens", "context_window", "max_output_length"):
        value = _to_optional_int(constraints.get(key))
        if value is not None:
            summary["max_prompt_length"] = value
            break

    cost_profile = item.get("cost_profile") if isinstance(item.get("cost_profile"), dict) else {}
    price = cost_profile.get("price")
    unit = _normalize_optional_text(cost_profile.get("unit"))
    currency = _normalize_optional_text(cost_profile.get("currency"))
    if isinstance(price, (int, float)) and unit:
        summary["pricing"] = {
            "price": float(price),
            "unit": unit,
            "currency": currency or "CNY",
            "pricing_verified": False,
        }
    return summary


def _build_capability_provenance(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for capability in item.get("capabilities") or []:
        if not isinstance(capability, dict):
            continue
        name = _normalize_optional_text(capability.get("name"))
        if not name:
            continue
        description = _normalize_optional_text(capability.get("description")) or _humanize_token(name)
        support_level = (
            _normalize_optional_text(capability.get("support_level"))
            or _normalize_optional_text(capability.get("level"))
            or "unknown"
        )
        rows.append(
            {
                "capability_name": name,
                "capability_label": _humanize_token(name),
                "support_level": support_level,
                "description": description,
                "score": capability.get("score"),
                "source": _normalize_optional_text(capability.get("source")) or "config_declared",
                "verified_at": _normalize_optional_text(capability.get("verified_at")),
                "confidence": _normalize_optional_text(capability.get("confidence")) or "low",
            }
        )
    return rows


def _merge_capabilities(left: Any, right: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for group in (left or [], right or []):
        for capability in group:
            if isinstance(capability, dict):
                key = str(capability.get("name") or capability.get("label") or capability).strip()
            else:
                key = str(capability).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(capability)
    return merged


def _deep_merge_dict(left: Any, right: Any) -> dict[str, Any]:
    base = dict(left) if isinstance(left, dict) else {}
    extra = dict(right) if isinstance(right, dict) else {}
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = _merge_unique_strings(merged[key], value)
        elif value not in (None, "", [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def _merge_unique_strings(*groups: Iterable[Any] | None) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        if group is None:
            continue
        for item in group:
            normalized = _normalize_optional_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _normalize_string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [value for value in (_normalize_optional_text(item) for item in values) if value]


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pick_longer_text(left: Any, right: Any) -> str | None:
    left_text = _normalize_optional_text(left)
    right_text = _normalize_optional_text(right)
    if not left_text:
        return right_text
    if not right_text:
        return left_text
    return right_text if len(right_text) > len(left_text) else left_text


def _humanize_token(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("_", " ").replace("-", " ").replace("/", " / ")
    if normalized.isascii():
        normalized = " ".join(part.capitalize() for part in normalized.split())
    return normalized


def _to_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
