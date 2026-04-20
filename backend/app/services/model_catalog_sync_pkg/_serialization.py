from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional
import logging
import re

from app.models.model_catalog import ModelCatalogEntry, ModelCatalogSource

logger = logging.getLogger(__name__)

def get_model_catalog_sync_service() -> ModelCatalogSyncService:
    """获取模型档案同步服务单例。"""

    return model_catalog_sync_service


def _format_number(value: Any) -> str:
    try:
        if value is None or value == "":
            return "未标注"
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,}"
    except Exception:
        return str(value)


def _extract_raw(entry: ModelCatalogEntry) -> dict[str, Any]:
    return entry.raw_config_json or {}


def _extract_catalog_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    profile = _extract_raw(entry).get("catalog_profile")
    return profile if isinstance(profile, dict) else {}


def _coerce_profile_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_profile_string_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []

    items: list[str] = []
    for raw_item in value:
        item = _coerce_profile_text(raw_item)
        if item and item not in items:
            items.append(item)
    return items


def _coerce_profile_object_list(
    value: Any,
    *,
    required_keys: tuple[str, ...],
    optional_keys: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []

    items: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue

        normalized: dict[str, Any] = {}
        valid = True
        for key in required_keys:
            text = _coerce_profile_text(raw_item.get(key))
            if not text:
                valid = False
                break
            normalized[key] = text
        if not valid:
            continue

        for key in optional_keys:
            optional_value = raw_item.get(key)
            if optional_value is None:
                continue
            if isinstance(optional_value, bool):
                normalized[key] = optional_value
                continue

            text = _coerce_profile_text(optional_value)
            if text:
                normalized[key] = text

        items.append(normalized)
    return items


def _merge_unique_strings(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for raw_item in group:
            item = _coerce_profile_text(raw_item)
            if item and item not in merged:
                merged.append(item)
    return merged


def _merge_resource_links(
    base_items: list[dict[str, Any]],
    extra_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*base_items, *extra_items]:
        label = _coerce_profile_text(item.get("label"))
        url = _coerce_profile_text(item.get("url"))
        if not label or not url:
            continue

        key = (label, url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _format_context_label(entry: ModelCatalogEntry, value: Any, *, input_side: bool) -> str:
    if value in (None, "", [], {}):
        return "未标注"

    if entry.category == "llm":
        return f"{_format_number(value)} tokens"

    suffix = "字符 / 提示输入" if input_side else "批量上限"
    return f"{_format_number(value)} {suffix}"


def _extract_context_profile(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)

    input_window = constraints.get("max_context_tokens")
    if input_window in (None, "", 0):
        input_window = constraints.get("max_prompt_length")

    output_window = constraints.get("max_output_tokens")
    if output_window in (None, "", 0):
        output_window = constraints.get("max_batch_size")

    return [
        {"label": "输入窗口", "value": _format_context_label(entry, input_window, input_side=True)},
        {"label": "输出窗口", "value": _format_context_label(entry, output_window, input_side=False)},
        {"label": "项目别名", "value": entry.model_key},
        {"label": "版本迭代", "value": str(raw.get("version") or "未标注")},
    ]


def _capability_display_name(capability: dict[str, Any]) -> str:
    name = str(capability.get("name", "")).strip()
    return _CAPABILITY_LABELS.get(name, name or "未命名能力")


def _derive_strengths(entry: ModelCatalogEntry) -> list[str]:
    capabilities = list((entry.capabilities_json or {}).get("items", []) or [])
    if not capabilities:
        return [entry.subcategory or entry.category]

    def _capability_score(item: dict[str, Any]) -> float:
        try:
            return float(item.get("score", 0.0) or 0.0)
        except Exception:
            return 0.0

    ranked = sorted(capabilities, key=_capability_score, reverse=True)
    strengths: list[str] = []
    for capability in ranked:
        label = _capability_display_name(capability)
        description = str(capability.get("description") or "").strip()
        strengths.append(f"{label}：{description}" if description else label)
        if len(strengths) >= 4:
            break
    return strengths


def _translate_modalities(modalities: list[str]) -> list[str]:
    translated: list[str] = []
    for modality in modalities or []:
        value = str(modality or "").strip()
        if not value:
            continue
        translated.append(_MODALITY_LABELS.get(value, value))
    return translated


def _derive_project_modules(entry: ModelCatalogEntry) -> list[str]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    modules: list[str] = []

    def _push(label: str) -> None:
        if label not in modules:
            modules.append(label)

    if any(
        task in {"concept", "chapter", "dialogue", "creative", "writing", "outline_expand", "book_synthesis"}
        for task in task_types
    ):
        _push(_PROJECT_MODULE_LABELS["novel"])
    if any(task.startswith("asset_") for task in task_types):
        _push(_PROJECT_MODULE_LABELS["asset_studio"])
    if any("audiobook" in task for task in task_types) or entry.category == "audio":
        _push(_PROJECT_MODULE_LABELS["audiobook"])
    if entry.category in {"image", "video", "multimodal"}:
        _push(_PROJECT_MODULE_LABELS["drama"])
    _push(_PROJECT_MODULE_LABELS["catalog"])
    return modules


def _derive_project_tasks(entry: ModelCatalogEntry) -> list[str]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    labels = [_TASK_TYPE_LABELS.get(item, item) for item in task_types]
    if labels:
        return labels

    fallback_tasks: list[str] = []
    if entry.category == "image":
        fallback_tasks.append("视觉素材生成")
    elif entry.category == "video":
        fallback_tasks.append("镜头与片段生成")
    elif entry.category == "multimodal":
        fallback_tasks.append("视觉理解与质检")
    elif entry.category == "audio":
        fallback_tasks.append("音乐 / 音效生成" if _is_generated_audio_model(entry) else "有声内容合成")
    else:
        fallback_tasks.append(entry.subcategory or _CATEGORY_LABELS.get(entry.category, entry.category))
    return fallback_tasks + _translate_modalities(entry.modalities or [])[:2]


def _is_speech_audio_model(entry: ModelCatalogEntry) -> bool:
    modalities = {str(item).lower() for item in entry.modalities or []}
    capability_names = {
        str(item.get("name", "")).lower()
        for item in (entry.capabilities_json or {}).get("items", []) or []
        if isinstance(item, dict)
    }
    return bool({"text_to_speech", "voice_clone"} & modalities) or bool(
        {"speech_synthesis", "voice_clone", "preset_voices", "instruct_control"} & capability_names
    )


def _is_generated_audio_model(entry: ModelCatalogEntry) -> bool:
    return entry.category == "audio" and not _is_speech_audio_model(entry)


def _supports_video_reference_input(entry: ModelCatalogEntry) -> bool:
    return "video_to_audio" in {str(item).lower() for item in entry.modalities or []}


def _is_music_generation_model(entry: ModelCatalogEntry) -> bool:
    capability_names = {
        str(item.get("name", "")).lower()
        for item in (entry.capabilities_json or {}).get("items", []) or []
        if isinstance(item, dict)
    }
    routing = entry.routing_json or {}
    task_types = {str(item).lower() for item in routing.get("task_types", []) or []}
    return bool({"music_generation", "background_music"} & capability_names) or "asset_music" in task_types


def _detect_openai_compatible(entry: ModelCatalogEntry) -> bool:
    raw = _extract_raw(entry)
    api_config = raw.get("api_config", {}) or {}
    base_url = str(api_config.get("base_url") or "").lower()
    documentation_url = str(entry.documentation_url or "").lower()
    if "/compatible-mode/" in base_url or "/v1" in base_url:
        return True
    if "openai" in documentation_url or "compatible" in documentation_url:
        return True
    return entry.category in {"llm", "multimodal"} and entry.provider in {"alibaba", "deepseek"}


def _derive_tooling_badges(entry: ModelCatalogEntry) -> list[str]:
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)
    profile = _extract_catalog_profile(entry)
    badges: list[str] = []

    def _push(label: str, enabled: bool = True) -> None:
        if enabled and label not in badges:
            badges.append(label)

    _push("统一档案")
    _push("流式输出", bool(constraints.get("supports_streaming")))
    _push("JSON 模式", bool(constraints.get("supports_json_mode")))
    _push("函数调用", bool(constraints.get("supports_function_call")))
    _push("系统角色", bool(constraints.get("supports_system_prompt")))
    _push("多轮会话", bool(constraints.get("supports_multi_turn")))
    _push("视觉输入", bool(constraints.get("supports_vision")) or entry.category == "multimodal")
    _push("统一媒体运行时", entry.category in {"image", "video", "audio", "multimodal"})
    _push("ModelHub 路由", entry.category == "llm")
    _push("OpenAI 兼容", _detect_openai_compatible(entry))
    _push("环境变量可识别", bool(raw.get("api_config", {}).get("api_key_env")))
    profile_badges = _coerce_profile_string_list(profile.get("tooling_badges"))
    return _merge_unique_strings(profile_badges, badges)[:8]


def _derive_runtime_entry(entry: ModelCatalogEntry) -> dict[str, str]:
    if entry.category == "llm":
        return {
            "runtime": "ModelHub 统一调度",
            "helper": "create_task_llm / create_model_llm",
            "entry_file": "core/model_hub.py · core/langchain_bridge.py",
        }

    operation_map = {
        "image": "UnifiedMediaRuntime.generate_image / edit_image",
        "video": "UnifiedMediaRuntime.generate_video",
        "multimodal": "UnifiedMediaRuntime.analyze_image / analyze_video",
        "audio": "POST /api/v1/asset-studio/audio" if _is_generated_audio_model(entry) else "UnifiedMediaRuntime.synthesize_speech",
    }
    return {
        "runtime": "资产工作台音频服务" if _is_generated_audio_model(entry) else "UnifiedMediaRuntime 媒体运行时",
        "helper": operation_map.get(entry.category, "UnifiedMediaRuntime"),
        "entry_file": (
            "backend/app/api/v1/asset_studio.py · "
            "backend/app/services/audiobook/ai_music.py · "
            "backend/app/services/audiobook/klingai_effect_generator.py"
            if _is_generated_audio_model(entry)
            else "core/unified_media_runtime.py"
        ),
    }


def _derive_proxy_path(entry: ModelCatalogEntry) -> str:
    prefix = "llm" if entry.category == "llm" else "media"
    return f"/proxy/{prefix}/{entry.provider}/{entry.model_key}"


def _derive_env_bindings(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    raw = _extract_raw(entry)
    bindings: list[dict[str, Any]] = []
    api_config = raw.get("api_config", {}) or {}

    def _push(label: str, value: str, required: bool = True) -> None:
        clean_value = str(value or "").strip()
        if not clean_value:
            return
        bindings.append({"label": label, "value": clean_value, "required": required})

    if entry.category == "llm":
        _push("API Key", api_config.get("api_key_env", ""))
        _push("Base URL", api_config.get("base_url", ""))
        _push("模型名 / Deployment", entry.model_key)
        return bindings

    if entry.model_key == "wan2.6-t2i":
        _push("API Key", "WAN_T2I_API_KEY")
        _push("Base URL", "WAN_T2I_BASE_URL")
        _push("模型名 / Deployment", "WAN_T2I_MODEL_NAME / WAN_T2I_MODEL_ID / wan2.6-t2i", required=False)
    elif entry.model_key.startswith("wan2.7-"):
        upper_model = entry.model_key.upper().replace(".", "_").replace("-", "_")
        _push("API Key", "DASHSCOPE_API_KEY")
        _push("Base URL", "DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", upper_model)
    elif entry.model_key == "qwen3-vl-plus":
        _push("API Key", "QWEN_VL_PLUS_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_VL_PLUS_BASE_URL / DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", "QWEN_VL_PLUS_MODEL_NAME / QWEN_VL_PLUS_MODEL_ID")
    elif entry.model_key == "qwen-image-edit-plus":
        _push("API Key", "QWEN_IMAGE_EDIT_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_IMAGE_EDIT_BASE_URL / DASHSCOPE_BASE_URL")
        _push("模型名 / Deployment", "QWEN_IMAGE_EDIT_MODEL_NAME / QWEN_IMAGE_EDIT_MODEL_ID", required=False)
    elif entry.model_key == "qwen-image-edit-max":
        _push("API Key", "QWEN_IMAGE_EDIT_MAX_API_KEY / DASHSCOPE_API_KEY")
        _push("Base URL", "QWEN_IMAGE_EDIT_MAX_BASE_URL / DASHSCOPE_BASE_URL")
        _push(
            "模型名 / Deployment",
            "QWEN_IMAGE_EDIT_MAX_MODEL_NAME / QWEN_IMAGE_EDIT_MAX_MODEL_ID",
            required=False,
        )
    elif entry.model_key == "mureka-o1-instrumental":
        _push("API Key", "MUREKA_API_KEY")
        _push("Base URL", "MUREKA_API_URL")
        _push("模型名 / Deployment", entry.model_key, required=False)
    elif entry.model_key == "vidu-timing2audio":
        _push("API Key", "VIDU_API_KEY")
        _push("Base URL", "VIDU_API_URL", required=False)
        _push("模型名 / Endpoint", entry.model_key, required=False)
    elif entry.model_key in {"qwen3-tts-flash", "cosyvoice-v3-plus"}:
        _push("API Key", "DASHSCOPE_API_KEY")
        _push("模型名 / Deployment", "QWEN3_TTS_FLASH_MODEL_ID", required=entry.model_key == "qwen3-tts-flash")
    else:
        _push("模型名 / Deployment", entry.model_key)

    return bindings


def _derive_param_matrix(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    constraints = entry.constraints_json or {}
    params: list[dict[str, Any]] = []

    def _push(name: str, label: str, supported: bool, note: str) -> None:
        params.append({"name": name, "label": label, "supported": supported, "note": note})

    if entry.category == "llm":
        _push("messages", "消息列表", True, "统一使用 role/content 结构。")
        _push("temperature", "Temperature", bool(constraints.get("supports_temperature")), "控制生成随机性。")
        _push("max_tokens", "Max Tokens", True, "限制输出长度。")
        _push("stream", "Streaming", bool(constraints.get("supports_streaming")), "是否启用流式输出。")
        _push("response_format", "JSON 模式", bool(constraints.get("supports_json_mode")), "适合结构化返回。")
        _push("tools", "Function Calling / Tools", bool(constraints.get("supports_function_call")), "适合工具编排与 Agent 工作流。")
        _push("system", "System Prompt", bool(constraints.get("supports_system_prompt")), "可定制系统角色。")
        _push("timeout", "Timeout", bool(constraints.get("supports_timeout_param")), "调用层是否支持自定义超时。")
        _push("max_retries", "Max Retries", bool(constraints.get("supports_max_retries")), "调用层是否支持重试次数。")
        return params

    if _is_generated_audio_model(entry):
        _push("prompt", "Prompt", True, "通过场景、材质、节奏和情绪描述音频目标。")
        _push("duration", "Duration", True, "控制音频时长，资产工作台当前按秒级离散值约束。")
        _push("style", "Style / 风格", _is_music_generation_model(entry), "适合音乐风格、氛围与配器方向控制。")
        _push("mood", "Mood / 情绪", True, "用于约束音乐或音效的整体情绪方向。")
        _push("tempo", "Tempo / 节奏", _is_music_generation_model(entry), "适合控制配乐节奏快慢。")
        _push("reference_assets", "参考视频", _supports_video_reference_input(entry), "仅视频转音频链路需要参考视频输入。")
        return params

    _push("prompt", "Prompt", True, "媒体模型统一支持主提示词。")
    _push("negative_prompt", "Negative Prompt", entry.category in {"image", "video"}, "控制不希望出现的元素。")
    _push("seed", "Seed", entry.category in {"image", "video"}, "用于复现或稳定结果。")
    _push("reference_assets", "参考素材", entry.category in {"image", "video", "multimodal"}, "支持参考图或参考视频的链路。")
    _push("dimensions", "尺寸 / 分辨率", entry.category in {"image", "video"}, "通过宽高或分辨率控制输出规格。")
    _push("duration", "Duration", entry.category == "video", "视频模型支持时长参数。")
    _push("voice", "Voice / Speaker", _is_speech_audio_model(entry), "语音模型支持音色或说话人选择。")
    _push("instruct", "Instruct / 情绪控制", entry.model_key == "cosyvoice-v3-plus", "适合有声表现力控制。")
    return params


def _derive_response_features(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    constraints = entry.constraints_json or {}
    features: list[dict[str, Any]] = []

    def _push(label: str, supported: bool, note: str) -> None:
        features.append({"label": label, "supported": supported, "note": note})

    if entry.category == "llm":
        _push("流式输出", bool(constraints.get("supports_streaming")), "适合长响应与前端实时反馈。")
        _push("JSON 模式", bool(constraints.get("supports_json_mode")), "适合结构化工作流。")
        _push("函数调用", bool(constraints.get("supports_function_call")), "适合工具编排与 AI 编程助手识别。")
        _push("系统角色", bool(constraints.get("supports_system_prompt")), "适合专属系统指令。")
        _push("多轮对话", bool(constraints.get("supports_multi_turn")), "适合连续对话上下文。")
        return features

    _push(
        "统一接入层",
        True,
        "通过项目统一媒体运行时访问，或通过资产工作台音频服务代理访问。",
    )
    _push("结构化元数据", True, "结果会附带模型、耗时、成本等元数据。")
    _push(
        "多参考输入",
        entry.category in {"image", "video", "multimodal"} or _supports_video_reference_input(entry),
        "支持参考图、参考视频或多图输入；视频转音频链路可扩展参考视频。",
    )
    _push("二进制输出", entry.category in {"image", "video", "audio"}, "可返回 URL、二进制或媒体数据。")
    return features


def _build_llm_python_template(entry: ModelCatalogEntry) -> str:
    default_params = entry.default_params_json or {}
    constraints = entry.constraints_json or {}
    temperature = default_params.get("temperature", 0.7)
    max_tokens = default_params.get("max_tokens") or constraints.get("max_output_tokens") or 2048
    stream_value = "True" if constraints.get("supports_streaming") else "False"
    return (
        "from core.model_hub import ModelHub\n\n"
        "hub = ModelHub.get_instance()\n"
        "result = await hub.call(\n"
        f"    model=\"{entry.model_key}\",\n"
        "    messages=[\n"
        "        {\"role\": \"system\", \"content\": \"你是一名专业助手。\"},\n"
        "        {\"role\": \"user\", \"content\": \"请根据任务生成结果。\"},\n"
        "    ],\n"
        f"    temperature={temperature},\n"
        f"    max_tokens={max_tokens},\n"
        f"    stream={stream_value},\n"
        ")\n"
        "logger.debug(result.content)\n"
    )


def _build_llm_javascript_template(entry: ModelCatalogEntry) -> str:
    raw = _extract_raw(entry)
    api_config = raw.get("api_config", {}) or {}
    default_params = entry.default_params_json or {}
    base_url = str(api_config.get("base_url") or "https://api.example.com/v1").strip()
    api_key_env = str(api_config.get("api_key_env") or "MODEL_API_KEY").strip()
    temperature = default_params.get("temperature", 0.7)
    max_tokens = default_params.get("max_tokens") or (entry.constraints_json or {}).get("max_output_tokens") or 2048
    return (
        "import OpenAI from \"openai\";\n\n"
        "const client = new OpenAI({\n"
        f"  apiKey: process.env.{api_key_env},\n"
        f"  baseURL: \"{base_url}\",\n"
        "});\n\n"
        "const result = await client.chat.completions.create({\n"
        f"  model: \"{entry.model_key}\",\n"
        "  messages: [\n"
        "    { role: \"system\", content: \"你是一名专业助手。\" },\n"
        "    { role: \"user\", content: \"请根据任务生成结果。\" },\n"
        "  ],\n"
        f"  temperature: {temperature},\n"
        f"  max_tokens: {max_tokens},\n"
        "});\n\n"
        "console.log(result.choices[0]?.message?.content || \"\");\n"
    )


def _derive_media_method_name(entry: ModelCatalogEntry) -> str:
    if entry.category == "image":
        return "edit_image" if entry.subcategory == "图像编辑" else "generate_image"
    if entry.category == "video":
        return "generate_video"
    if entry.category == "multimodal":
        return "analyze_video" if "video_understanding" in (entry.modalities or []) else "analyze_image"
    if entry.category == "audio":
        return "generate_audio" if _is_generated_audio_model(entry) else "synthesize_speech"
    return "run"


def _build_media_python_template(entry: ModelCatalogEntry) -> str:
    method_name = _derive_media_method_name(entry)
    if method_name == "generate_image":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.generate_image(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请生成一张符合需求的图像\",\n"
            "    width=1024,\n"
            "    height=1024,\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "edit_image":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.edit_image(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请根据参考图完成图像编辑\",\n"
            "    reference_images=[\"./reference.png\"],\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "generate_video":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "result = media_runtime.generate_video(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    prompt=\"请生成一个 5 秒钟的视频镜头\",\n"
            "    duration=5.0,\n"
            "    width=1280,\n"
            "    height=720,\n"
            ")\n"
            "logger.debug(result.outputs)\n"
        )
    if method_name == "generate_audio":
        if _supports_video_reference_input(entry):
            return (
                "# 当前项目已将该能力纳入统一模型档案，但尚未开放可直接调用的工作台入口。\n"
                "# 后续接入时，建议在 /api/v1/asset-studio/audio 增加 reference_video 上传字段。\n"
                "payload = {\n"
                f"    \"model_id\": \"{entry.model_key}\",\n"
                "    \"generation_type\": \"sound-effect\",\n"
                "    \"prompt\": \"根据视频补充环境音、动作音和氛围声\",\n"
                "}\n"
                "logger.debug(payload)\n"
            )
        generation_type = "music" if _is_music_generation_model(entry) else "sound-effect"
        duration = "30" if generation_type == "music" else "5"
        style_field = "    \"style\": \"氛围\",\n" if generation_type == "music" else ""
        return (
            "import httpx\n\n"
            "headers = {\"Authorization\": \"Bearer <your-token>\"}\n"
            "payload = {\n"
            f"    \"model_id\": \"{entry.model_key}\",\n"
            f"    \"generation_type\": \"{generation_type}\",\n"
            "    \"prompt\": \"夜色中的城市氛围，低频铺底，带轻微紧张感\",\n"
            f"    \"duration\": \"{duration}\",\n"
            f"{style_field}"
            "    \"mood\": \"tense\",\n"
            "    \"tempo\": \"medium\",\n"
            "}\n\n"
            "async with httpx.AsyncClient(base_url=\"http://127.0.0.1:8000\", headers=headers, timeout=300) as client:\n"
            "    response = await client.post(\"/api/v1/asset-studio/audio\", data=payload)\n"
            "    response.raise_for_status()\n"
            "    result = response.json()\n"
            "    logger.debug(result[\"primary_output\"])\n"
        )
    if method_name == "synthesize_speech":
        return (
            "from core.unified_media_runtime import media_runtime\n\n"
            "audio_bytes = await media_runtime.synthesize_speech(\n"
            f"    model_id=\"{entry.model_key}\",\n"
            "    text=\"这是需要合成的文本。\",\n"
            "    speaker=\"默认音色\",\n"
            ")\n"
            "logger.debug(len(audio_bytes))\n"
        )
    return (
        "from core.unified_media_runtime import media_runtime\n\n"
        f"# 使用 {entry.model_key} 执行多模态分析\n"
        "# 具体参数请参考项目适配器定义。\n"
    )


def _build_media_javascript_template(entry: ModelCatalogEntry) -> str:
    method_name = _derive_media_method_name(entry)
    operation = {
        "generate_image": "图像生成",
        "edit_image": "图像编辑",
        "generate_video": "视频生成",
        "generate_audio": "音乐 / 音效生成",
        "analyze_image": "图像分析",
        "analyze_video": "视频分析",
        "synthesize_speech": "语音合成",
    }.get(method_name, "媒体调用")
    if method_name == "generate_audio":
        if _supports_video_reference_input(entry):
            return (
                "const payload = {\n"
                f"  modelId: \"{entry.model_key}\",\n"
                "  generationType: \"sound-effect\",\n"
                "  prompt: \"根据视频补充环境音、动作音和氛围声\",\n"
                "};\n\n"
                "// 当前项目仅完成模型档案归档，尚未开放视频转音频的统一前端入口。\n"
                "console.log(\"待接入的视频转音频能力\", payload);\n"
            )
        generation_type = "music" if _is_music_generation_model(entry) else "sound-effect"
        style_line = "formData.append(\"style\", \"氛围\");\n" if generation_type == "music" else ""
        return (
            "const formData = new FormData();\n"
            "formData.append(\"prompt\", \"夜色中的城市氛围，低频铺底，带轻微紧张感\");\n"
            f"formData.append(\"generation_type\", \"{generation_type}\");\n"
            f"formData.append(\"model_id\", \"{entry.model_key}\");\n"
            f"formData.append(\"duration\", \"{'30' if generation_type == 'music' else '5'}\");\n"
            f"{style_line}"
            "formData.append(\"mood\", \"tense\");\n"
            "formData.append(\"tempo\", \"medium\");\n\n"
            "// 建议经后端统一代理到 /api/v1/asset-studio/audio，不要前端直连供应商密钥。\n"
            "console.log(\"提交资产工作台音频任务\", formData);\n"
        )
    return (
        "const payload = {\n"
        f"  modelId: \"{entry.model_key}\",\n"
        "  prompt: \"请根据任务生成结果\",\n"
        "};\n\n"
        f"// 建议前端通过后端统一服务触发 {operation}，避免直接暴露密钥。\n"
        f"console.log(\"当前模型用于：{operation}\", payload);\n"
    )


def _build_sdk_templates(entry: ModelCatalogEntry) -> dict[str, str]:
    if entry.category == "llm":
        return {
            "python": _build_llm_python_template(entry),
            "javascript": _build_llm_javascript_template(entry),
        }
    return {
        "python": _build_media_python_template(entry),
        "javascript": _build_media_javascript_template(entry),
    }


def _build_system_role(entry: ModelCatalogEntry) -> str:
    if entry.model_key == "qwen3-max":
        return "你是中文长篇创作与角色对话专家，擅长章节起草、重写与风格统一。"
    if entry.model_key == "qwen-long":
        return "你是超长文本理解与整书规划专家，擅长汇总、分层摘要与全书一致性分析。"
    if entry.model_key == "qwen-turbo":
        return "你是结构化提取与轻量改写助手，优先输出简洁、稳定、低成本的结果。"
    if entry.model_key == "deepseek-reasoner":
        return "你是严谨的推理审校专家，优先处理逻辑约束、规则一致性和复杂决策。"
    if entry.category == "multimodal":
        return "你是视觉内容审查与多模态解析专家，负责图像、视频与结构化理解。"
    if entry.category == "image":
        return "你是视觉创意提示词与图像生成策略专家，负责主体、风格、构图与约束编排。"
    if entry.category == "video":
        return "你是镜头脚本与视频生成提示专家，负责镜头语言、动作与时长规划。"
    if entry.category == "audio":
        if _is_generated_audio_model(entry):
            if _supports_video_reference_input(entry):
                return "你是视频补声音轨策划助手，负责根据镜头内容规划环境音、动作音与氛围声。"
            if _is_music_generation_model(entry):
                return "你是音乐提示词与配乐策略助手，负责场景、情绪、节奏和配器方向的设计。"
            return "你是音效提示词设计助手，负责把动作、材质、空间和氛围描述压缩成可生成的音频提示词。"
        return "你是有声脚本与语音表现力规划助手，负责音色、情绪和停顿控制。"
    return "你是项目统一模型调用的专业助手。"


def _build_prompt_patterns(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    if entry.category == "llm":
        return [
            {"title": "系统角色模板", "template": f"System: {_build_system_role(entry)}"},
            {"title": "正文 / 分析任务模板", "template": "User: 目标 + 约束 + 输出结构 + 风格要求 + 禁止项。"},
            {"title": "结构化输出模板", "template": "User: 请按 JSON 输出，字段固定为 title/content/risks/next_actions。"},
        ]
    if entry.category == "image":
        return [
            {"title": "文生图模板", "template": "主体 + 场景 + 风格 + 镜头构图 + 光影 + 负向约束。"},
            {"title": "图像编辑模板", "template": "参考图 + 编辑目标 + 保留元素 + 不要改动项 + 输出风格。"},
        ]
    if entry.category == "video":
        return [
            {"title": "视频镜头模板", "template": "主体 + 动作 + 场景 + 镜头运动 + 时长 + 节奏。"},
            {"title": "参考驱动模板", "template": "参考图/视频 + 要保留的风格 + 要发生的动作 + 禁止项。"},
        ]
    if entry.category == "audio":
        if _is_generated_audio_model(entry):
            if _supports_video_reference_input(entry):
                return [
                    {"title": "视频补声模板", "template": "输入视频 + 关注的声音层（环境 / 动作 / 氛围）+ 希望保留或避免的声音元素。"},
                    {"title": "镜头音轨策略模板", "template": "镜头节奏 + 场景空间感 + 声音远近层次 + 是否需要音乐化处理。"},
                ]
            if _is_music_generation_model(entry):
                return [
                    {"title": "背景音乐模板", "template": "场景 + 情绪 + 节奏 + 风格 + 主要乐器 + 时长。"},
                    {"title": "配乐控制模板", "template": "片段定位 + 氛围关键词 + 节奏推进方式 + 不要出现的人声或歌词。"},
                ]
            return [
                {"title": "短音效模板", "template": "动作主体 + 材质 + 强度 + 持续时间 + 是否需要尾音。"},
                {"title": "环境音模板", "template": "场景环境 + 远近层次 + 氛围关键词 + 时长 + 是否需要循环感。"},
            ]
        return [
            {"title": "标准 TTS 模板", "template": "角色/音色 + 文本内容 + 语速 + 停顿 + 输出格式。"},
            {"title": "情绪化朗读模板", "template": "角色定位 + 情绪标签 + 语气 + 节奏 + 是否使用 instruct。"},
        ]
    return [{"title": "多模态解析模板", "template": "输入素材 + 识别目标 + 输出结构 + 风险项。"}]


def _build_router_rules(entry: ModelCatalogEntry) -> list[dict[str, str]]:
    routing = entry.routing_json or {}
    task_types = [str(item) for item in routing.get("task_types", []) or []]
    rules: list[dict[str, str]] = []

    if task_types:
        rules.append(
            {
                "when": "检测到任务类型命中项目路由表",
                "action": f"优先路由到 {entry.model_key}",
                "reason": "该模型已在项目运行时中声明为对应任务的优先模型。",
            }
        )
    if routing.get("fallback_models"):
        rules.append(
            {
                "when": "主模型不可用、超时或被策略降级",
                "action": f"回退到 {' / '.join(routing.get('fallback_models') or [])}",
                "reason": "遵循当前模型配置中的 fallback_models。",
            }
        )
    if entry.category == "video" and "fast" in entry.model_key:
        rules.append(
            {
                "when": "视频链路超时或需要快速预览",
                "action": f"优先使用 {entry.model_key}",
                "reason": "该模型定位为速度优先的降级位。",
            }
        )
    if entry.category == "image" and "turbo" in entry.model_key:
        rules.append(
            {
                "when": "需要低成本快速预览图像",
                "action": f"优先使用 {entry.model_key}",
                "reason": "适合提示词迭代与早期草图筛选。",
            }
        )
    return rules


def _extract_best_practice_tips(entry: ModelCatalogEntry) -> list[str]:
    profile = _extract_catalog_profile(entry)
    profile_tips = _coerce_profile_string_list(profile.get("best_practice_tips"))
    if profile_tips:
        return profile_tips

    raw = _extract_raw(entry)
    llm_tips = raw.get("best_practice_tips")
    if isinstance(llm_tips, list):
        return [str(item).strip() for item in llm_tips if str(item).strip()]

    media_tips = ((entry.routing_json or {}).get("best_practice") or {}).get("tips")
    if isinstance(media_tips, list):
        return [str(item).strip() for item in media_tips if str(item).strip()]
    return []


def _build_identity_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    raw = _extract_raw(entry)
    profile = _extract_catalog_profile(entry)
    modules = _derive_project_modules(entry)
    task_labels = _derive_project_tasks(entry)
    strengths = _derive_strengths(entry)
    weaknesses = list(entry.limitations or [])[:4]
    role_summary = _coerce_profile_text(profile.get("role_summary")) or f"当前模型主要服务于：{'、'.join(modules)}。"
    return {
        "core_positioning": entry.summary or "暂无摘要",
        "model_lineage": [
            {"label": "模型名称", "value": entry.name},
            {"label": "模型家族", "value": entry.model_family or "未标注"},
            {"label": "开发商", "value": _PROVIDER_LABELS.get(entry.provider, entry.provider)},
            {"label": "模型定位", "value": entry.subcategory or _CATEGORY_LABELS.get(entry.category, entry.category)},
            {"label": "状态", "value": str(raw.get("status") or entry.status or "active")},
        ],
        "context_window": _extract_context_profile(entry),
        "capability_quadrants": {
            "strengths": strengths,
            "weaknesses": weaknesses,
            "modalities": _translate_modalities(entry.modalities or []),
            "capability_tags": [
                _capability_display_name(item) for item in (entry.capabilities_json or {}).get("items", [])[:6]
            ],
        },
        "project_fit": {
            "modules": modules,
            "task_types": task_labels,
            "role_summary": role_summary,
        },
    }


def _build_integration_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    runtime = _derive_runtime_entry(entry)
    profile = _extract_catalog_profile(entry)
    recommended_wrapper = _coerce_profile_text(profile.get("recommended_wrapper")) or (
        "建议统一封装为 call_model(model_name, prompt, config)，由底层再分发到 ModelHub 或 UnifiedMediaRuntime。"
    )
    return {
        "calling_stack": [
            {"label": "统一运行时", "value": runtime["runtime"]},
            {"label": "推荐入口", "value": runtime["helper"]},
            {"label": "运行时代码", "value": runtime["entry_file"]},
            {"label": "接入模式", "value": "OpenAI 兼容接口" if _detect_openai_compatible(entry) else "项目适配器 / 专有 REST"},
        ],
        "native_parameters": _derive_param_matrix(entry),
        "response_features": _derive_response_features(entry),
        "environment_bindings": _derive_env_bindings(entry),
        "tooling_badges": _derive_tooling_badges(entry),
        "recommended_wrapper": recommended_wrapper,
        "sdk_templates": _build_sdk_templates(entry),
    }


def _build_prompt_router_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    routing = entry.routing_json or {}
    profile = _extract_catalog_profile(entry)
    prompt_patterns = _coerce_profile_object_list(
        profile.get("prompt_patterns"),
        required_keys=("title", "template"),
    )
    router_rules = _coerce_profile_object_list(
        profile.get("router_rules"),
        required_keys=("when", "action", "reason"),
    )
    fallback_chain = _coerce_profile_string_list(profile.get("fallback_chain")) or [
        str(item) for item in routing.get("fallback_models", []) or []
    ]
    return {
        "system_role": _coerce_profile_text(profile.get("system_role")) or _build_system_role(entry),
        "prompt_patterns": prompt_patterns or _build_prompt_patterns(entry),
        "router_rules": router_rules or _build_router_rules(entry),
        "best_practice_tips": _extract_best_practice_tips(entry),
        "fallback_chain": fallback_chain,
    }


def _build_deployment_profile(entry: ModelCatalogEntry) -> dict[str, Any]:
    runtime = _derive_runtime_entry(entry)
    profile = _extract_catalog_profile(entry)
    proxy_path = _derive_proxy_path(entry)
    topology = [
        {"label": "部署模式", "value": "官方托管 API + 项目统一运行时"},
        {"label": "建议代理路径", "value": proxy_path},
        {"label": "推荐接入层", "value": runtime["runtime"]},
    ]

    if entry.category == "llm":
        project_entrypoints = [
            {"label": "任务路由调用", "value": "create_task_llm(task_type=...)"},
            {"label": "显式点名调用", "value": f"create_model_llm(model=\"{entry.model_key}\")"},
            {"label": "底层统一入口", "value": "ModelHub.call(messages, task_type, model, ...)"},
        ]
        local_note = "当前项目优先使用官方托管 API；如需本地替代，可额外接入 Ollama / LM Studio 并在统一封装层映射。"
    else:
        project_entrypoints = [
            {"label": "统一媒体入口", "value": runtime["helper"]},
            {"label": "底层统一入口", "value": "UnifiedMediaRuntime(...)"},
            {"label": "前端调用建议", "value": "建议经后端服务代理，不直接暴露供应商密钥。"},
        ]
        local_note = "当前项目优先使用托管媒体接口；本地替代更适合开源模型或离线工作站，不建议直接替换现有生产链路。"

    project_entrypoints = _coerce_profile_object_list(
        profile.get("project_entrypoints"),
        required_keys=("label", "value"),
    ) or project_entrypoints
    local_note = _coerce_profile_text(profile.get("local_deployment_note")) or local_note

    proxy_snippet = (
        f"location {proxy_path} {{\n"
        "    proxy_set_header Authorization $http_authorization;\n"
        "    proxy_pass https://upstream-provider.example.com;\n"
        "}\n"
    )

    return {
        "access_topology": topology,
        "project_entrypoints": project_entrypoints,
        "environment_convention": _derive_env_bindings(entry),
        "local_deployment_note": local_note,
        "proxy_snippet": proxy_snippet,
    }


def _build_resource_navigation(entry: ModelCatalogEntry) -> dict[str, Any]:
    profile = _extract_catalog_profile(entry)
    profile_resources = profile.get("resource_navigation") if isinstance(profile.get("resource_navigation"), dict) else {}
    official_sources: list[dict[str, str]] = []
    if entry.documentation_url:
        official_sources.append({"label": "官方文档", "url": entry.documentation_url, "note": "优先作为接口与参数依据。"})
    for url in entry.source_urls or []:
        if url == entry.documentation_url:
            continue
        official_sources.append({"label": "补充来源", "url": url, "note": "用于核验计费、模型列表或补充说明。"})

    provider_portals = list(_REFERENCE_HUBS["provider_portals"])
    if entry.provider == "alibaba":
        provider_portals = [item for item in provider_portals if item["label"] == "通义实验室"]
    elif entry.provider == "deepseek":
        provider_portals = [item for item in provider_portals if item["label"] == "DeepSeek 官网"]

    return {
        "official_sources": _merge_resource_links(
            official_sources[:5],
            _coerce_profile_object_list(
                profile_resources.get("official_sources"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "selection_hubs": _merge_resource_links(
            list(_REFERENCE_HUBS["selection_hubs"]),
            _coerce_profile_object_list(
                profile_resources.get("selection_hubs"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "model_hubs": _merge_resource_links(
            list(_REFERENCE_HUBS["model_hubs"]),
            _coerce_profile_object_list(
                profile_resources.get("model_hubs"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
        "provider_portals": _merge_resource_links(
            provider_portals,
            _coerce_profile_object_list(
                profile_resources.get("provider_portals"),
                required_keys=("label", "url"),
                optional_keys=("note",),
            ),
        ),
    }


def _build_constraints_summary(entry: ModelCatalogEntry) -> dict[str, Any]:
    """构建约束条件的摘要信息，用于前端展示
    
    Args:
        entry: 模型档案实体
        
    Returns:
        约束条件摘要字典
    """
    constraints = entry.constraints_json or {}
    raw = _extract_raw(entry)
    performance = entry.performance_json or {}
    cost_profile = performance.get("cost_profile", {}) or {}
    
    summary = {}
    
    if entry.category == "video":
        duration_values = constraints.get("duration", [])
        if duration_values:
            min_dur = min(duration_values)
            max_dur = max(duration_values)
            summary["duration"] = {
                "min_seconds": min_dur,
                "max_seconds": max_dur,
                "available_options": sorted(duration_values),
            }
        
        summary["resolution"] = {
            "min_width": constraints.get("min_width"),
            "max_width": constraints.get("max_width"),
            "min_height": constraints.get("min_height"),
            "max_height": constraints.get("max_height"),
        }
        
        ratios = constraints.get("ratios", [])
        if ratios:
            summary["aspect_ratios"] = sorted(ratios)
    
    elif entry.category == "image":
        summary["resolution"] = {
            "min_width": constraints.get("min_width"),
            "max_width": constraints.get("max_width"),
            "min_height": constraints.get("min_height"),
            "max_height": constraints.get("max_height"),
        }
        
        ratios = constraints.get("ratios", [])
        if ratios:
            summary["aspect_ratios"] = sorted(ratios)
    
    batch_size = constraints.get("max_batch_size")
    if batch_size:
        summary["max_batch_size"] = batch_size
    
    prompt_length = constraints.get("max_prompt_length")
    if prompt_length:
        summary["max_prompt_length"] = prompt_length
    
    if cost_profile.get("price") is not None:
        summary["pricing"] = {
            "price": cost_profile.get("price"),
            "unit": cost_profile.get("unit", ""),
            "currency": cost_profile.get("currency", "CNY"),
            "pricing_verified": cost_profile.get("pricing_verified", False),
        }
    
    return summary


def _build_capability_provenance(entry: ModelCatalogEntry) -> list[dict[str, Any]]:
    """构建能力溯源信息列表，用于前端展示
    
    Args:
        entry: 模型档案实体
        
    Returns:
        能力溯源信息列表
    """
    capabilities = (entry.capabilities_json or {}).get("items", []) or []
    provenance_list = []
    
    for cap in capabilities:
        if not isinstance(cap, dict):
            continue
        
        cap_name = cap.get("name", "")
        if not cap_name:
            continue
        
        provenance_list.append({
            "capability_name": cap_name,
            "capability_label": _CAPABILITY_LABELS.get(cap_name, cap_name),
            "support_level": cap.get("support_level", "unknown"),
            "description": cap.get("description", ""),
            "score": cap.get("score"),
            "source": cap.get("source", ""),
            "verified_at": cap.get("verified_at"),
            "confidence": cap.get("confidence", "low"),
        })
    
    return provenance_list

def _build_usage_guide(entry: ModelCatalogEntry) -> Optional[dict[str, Any]]:
    raw = entry.raw_config_json or {}
    usage_guide = raw.get("usage_guide")

    category = entry.category or "llm"
    category_common_guide = _get_category_common_guide(category)

    if usage_guide:
        category_common = usage_guide.get("category_common", category)
        category_common_guide = _get_category_common_guide(category_common)
        model_specific = usage_guide.get("model_specific", {})
        merged_guide = _merge_usage_guides(category_common_guide, model_specific)
    else:
        model_specific = _build_auto_usage_guide(entry)
        merged_guide = _merge_usage_guides(category_common_guide, model_specific)

    if merged_guide:
        merged_guide["model_key"] = entry.model_key
        merged_guide["category"] = category

    return merged_guide


def _build_auto_usage_guide(entry: ModelCatalogEntry) -> dict[str, Any]:
    """根据模型校验数据自动生成使用指南的模型专有部分。"""
    raw = entry.raw_config_json or {}
    detailed_specs = raw.get("detailed_specs") or {}
    sections = []

    api_params_section = _build_api_params_section(detailed_specs, entry.category or "llm")
    if api_params_section:
        sections.append(api_params_section)

    input_format_section = _build_input_format_section(detailed_specs, entry.category or "llm")
    if input_format_section:
        sections.append(input_format_section)

    limitations_section = _build_limitations_section(entry)
    if limitations_section:
        sections.append(limitations_section)

    tips_section = _build_best_practices_section(entry)
    if tips_section:
        sections.append(tips_section)

    if not sections:
        return {}

    return {
        "title": f"{entry.name or entry.model_key} 专属指南",
        "sections": sections,
    }


def _build_api_params_section(detailed_specs: dict, category: str) -> Optional[dict[str, Any]]:
    """构建 API 参数说明章节。"""
    basic_params = detailed_specs.get("basic_params", {})
    if not basic_params:
        return None

    content_parts = []
    param_descriptions = {
        "duration": "生成时长（秒）",
        "resolution": "输出分辨率",
        "size": "输出尺寸",
        "aspect_ratio": "宽高比",
        "mode": "生成模式",
        "audio": "是否生成音频",
        "watermark": "是否添加水印",
        "seed": "随机种子（可复现）",
        "temperature": "输出随机性（0=严谨, 1=发散）",
        "max_tokens": "最大输出长度",
        "top_p": "概率采样范围",
    }

    for key, value in basic_params.items():
        desc = param_descriptions.get(key, key)
        if isinstance(value, dict):
            options = value.get("options") or value.get("range") or value.get("default")
            if options:
                content_parts.append(f"- **{desc}** (`{key}`): {options}")
        else:
            content_parts.append(f"- **{desc}** (`{key}`): {value}")

    if not content_parts:
        return None

    return {
        "title": "API 参数说明",
        "content": "\n".join(content_parts),
        "tips": [
            "首次调用建议使用默认参数",
            "调整参数时建议一次只改一个",
        ],
    }


def _build_input_format_section(detailed_specs: dict, category: str) -> Optional[dict[str, Any]]:
    """构建输入格式说明章节。"""
    input_modalities = detailed_specs.get("input_modalities", [])
    if not input_modalities:
        return None

    modality_labels = {
        "text": "文本提示词",
        "image": "图片",
        "video": "视频",
        "audio": "音频",
    }

    content_parts = ["本模型支持的输入类型："]
    for m in input_modalities:
        label = modality_labels.get(m, m)
        content_parts.append(f"- {label}")

    tips = []
    if "image" in input_modalities:
        tips.extend([
            "图片建议使用高清、主体清晰的素材",
            "支持的图片格式：JPG、PNG、WEBP",
        ])
    if "video" in input_modalities:
        tips.extend([
            "视频建议使用稳定的素材",
            "支持的视频格式：MP4、MOV",
        ])
    if "audio" in input_modalities:
        tips.extend([
            "音频建议使用清晰的录音",
            "支持的音频格式：MP3、WAV",
        ])

    return {
        "title": "输入格式",
        "content": "\n".join(content_parts),
        "tips": tips,
    }


def _build_limitations_section(entry: ModelCatalogEntry) -> Optional[dict[str, Any]]:
    """构建限制与注意事项章节。"""
    limitations = entry.limitations or []
    constraints = (entry.constraints_json or {})
    if not limitations and not constraints:
        return None

    content_parts = []
    if limitations:
        content_parts.append("### 已知限制")
        for lim in limitations[:5]:
            content_parts.append(f"- {lim}")

    max_tokens = constraints.get("max_tokens")
    max_duration = constraints.get("max_duration")
    if max_tokens:
        content_parts.append(f"- 最大输出长度: {max_tokens} tokens")
    if max_duration:
        content_parts.append(f"- 最大生成时长: {max_duration}秒")

    if not content_parts:
        return None

    return {
        "title": "限制与注意事项",
        "content": "\n".join(content_parts),
        "tips": [
            "生成前确认参数在允许范围内",
            "内容审核可能拒绝某些提示词",
        ],
    }


def _build_best_practices_section(entry: ModelCatalogEntry) -> Optional[dict[str, Any]]:
    """构建最佳实践章节。"""
    tips = _extract_best_practice_tips(entry)
    if not tips:
        return None

    content_parts = ["### 推荐做法"]
    for tip in tips[:8]:
        content_parts.append(f"- {tip}")

    return {
        "title": "最佳实践",
        "content": "\n".join(content_parts),
    }


_BEST_PRACTICE_TEMPLATES: dict[str, list[str]] = {
    "video": [
        "首次生成建议先用低分辨率+短时长测试提示词效果",
        "提示词应包含主体、动作、场景、风格四个要素",
        "图生视频时参考图质量直接影响输出质量",
        "使用具体的运镜描述（推近、拉远、跟随）效果更好",
        "避免过于抽象的描述，如'好看的风景'",
        "内容审核可能拒绝某些提示词，注意措辞",
    ],
    "image": [
        "提示词先描述主体，再描述环境和风格",
        "善用光照和氛围描述词（晨光、暖色调、赛博朋克）",
        "指定艺术风格可以大幅提升一致性",
        "避免过度堆砌形容词，保持描述清晰",
        "图生图时 similarity 参数控制与原图的相似度",
    ],
    "audio": [
        "明确指定音乐类型和节奏",
        "描述期望的情绪氛围",
        "音效生成时描述要具体（如'雨滴打在铁皮屋顶'而非'下雨声'）",
    ],
    "llm": [
        "使用 system prompt 设定角色和行为规则",
        "复杂任务拆分为多步骤执行",
        "利用 few-shot 示例引导输出格式",
        "长上下文模型可一次性提供完整背景",
        "temperature=0 适合事实性任务，temperature>0.7 适合创意任务",
        "联网搜索可获取实时信息，但可能增加延迟",
    ],
}


def _extract_best_practice_tips(entry: ModelCatalogEntry) -> list[str]:
    """根据模型类别提取最佳实践提示。"""
    category = entry.category or "llm"
    tips = list(_BEST_PRACTICE_TEMPLATES.get(category, []))

    capabilities = (entry.capabilities_json or {}).get("items", [])
    if "image_to_video" in capabilities or "reference_to_video" in capabilities:
        tips.append("图生视频模式需要提供清晰的参考图")
    if "video_edit" in capabilities:
        tips.append("视频编辑时描述要针对需要修改的部分")
    if "web_search" in capabilities:
        tips.append("开启联网搜索可获取实时信息，使用 enable_search 参数")

    return tips


_CATEGORY_COMMON_GUIDES: dict[str, dict[str, Any]] = {
    "video": {
        "title": "视频模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "视频生成的提示词应包含主体、动作、场景、风格四个要素。\n\n**好的示例：**\n- \"一只橘猫在草地上追逐蝴蝶，镜头跟随移动，暖色调，电影感\"\n- \"雨夜街道，霓虹灯倒影，慢镜头推近，赛博朋克风格\"\n\n**避免：**\n- 过于抽象的描述如\"好看的风景\"\n- 矛盾的动作描述",
                "tips": [
                    "使用具体的视觉描述词",
                    "指定镜头运动方式",
                    "明确画面风格和氛围",
                    "控制场景复杂度"
                ]
            },
            {
                "title": "参考图使用",
                "content": "使用参考图可以大幅提升生成质量。支持图片参考和视频参考两种模式。",
                "tips": [
                    "使用高清、主体清晰的图片",
                    "参考图风格应与目标一致",
                    "多图时注意权重分配",
                    "视频参考注意时长限制"
                ]
            },
            {
                "title": "时长与分辨率选择",
                "content": "根据使用场景选择合适的时长和分辨率。",
                "tips": [
                    "短视频适合社交媒体分享",
                    "高分辨率会增加生成时间",
                    "首次生成建议先用低分辨率测试提示词"
                ]
            }
        ]
    },
    "image": {
        "title": "图像模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "图像生成的提示词应包含主体、环境、构图、风格四个要素。\n\n**好的示例：**\n- \"清晨的湖边小屋，薄雾笼罩，暖色晨光，水彩画风格\"\n- \"未来城市天际线，霓虹灯，赛博朋克，超广角\"\n\n**避免：**\n- 过度堆砌形容词\n- 矛盾的视觉描述",
                "tips": [
                    "描述要具体且有层次",
                    "先主体后环境",
                    "指定艺术风格",
                    "善用光照和氛围描述"
                ]
            },
            {
                "title": "风格控制",
                "content": "不同模型对风格的控制方式不同。",
                "tips": [
                    "使用风格预设可以快速获得一致效果",
                    "混合风格时需要平衡权重",
                    "注意模型的文本渲染能力"
                ]
            }
        ]
    },
    "audio": {
        "title": "音频模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "音频生成的提示词应包含类型、风格、情绪、时长等要素。",
                "tips": [
                    "指定音乐类型和节奏",
                    "描述期望的情绪氛围",
                    "控制音频时长"
                ]
            }
        ]
    },
    "llm": {
        "title": "文本模型通用使用指南",
        "sections": [
            {
                "title": "提示词编写技巧",
                "content": "好的提示词是大模型高效工作的前提。\n\n**结构化提示词：**\n```\n角色：你是专业的小说编辑\n任务：分析以下文本的情节结构\n输出格式：分点列出，每个要点不超过50字\n\n文本：[你的文本]\n```\n\n**进阶技巧：**\n- 使用 Few-shot 示例引导输出格式\n- 分步骤引导复杂任务\n- 设置明确的边界条件",
                "tips": [
                    "提供清晰的角色定义和任务目标",
                    "使用示例示范期望的输出格式",
                    "复杂任务拆分为多步骤",
                    "利用系统提示词设定全局行为",
                    "长上下文模型可一次性提供完整背景"
                ]
            },
            {
                "title": "联网搜索使用",
                "content": "部分模型支持联网搜索，可以获取最新信息。",
                "tips": [
                    "查询实时信息时开启联网搜索",
                    "使用 freshness 参数限定搜索时效性",
                    "开启 enable_source 可以追溯信息来源"
                ]
            }
        ]
    }
}


def _get_category_common_guide(category: str) -> Optional[dict[str, Any]]:
    return _CATEGORY_COMMON_GUIDES.get(category)


def _merge_usage_guides(common_guide: Optional[dict], model_specific: dict) -> Optional[dict]:
    if not model_specific and not common_guide:
        return None
    
    merged = {
        "title": model_specific.get("title") or common_guide.get("title", "使用指南"),
        "sections": []
    }
    
    if common_guide and common_guide.get("sections"):
        merged["sections"].extend(common_guide["sections"])
    
    if model_specific and model_specific.get("sections"):
        merged["sections"].extend(model_specific["sections"])
    
    return merged


def serialize_model_catalog_entry(
    entry: ModelCatalogEntry,
    *,
    include_sources: bool = False,
    include_archives: bool = False,
) -> dict[str, Any]:
    """将 ORM 对象序列化为前端可直接消费的结构。"""

    identity_profile = _build_identity_profile(entry)
    integration_profile = _build_integration_profile(entry)
    raw_config = _extract_raw(entry)
    detailed_specs = raw_config.get("detailed_specs") or {}
    
    pricing_verification = raw_config.get("pricing_verification", {})
    
    payload = {
        "model_key": entry.model_key,
        "name": entry.name,
        "provider": entry.provider,
        "category": entry.category,
        "category_label": _CATEGORY_LABELS.get(entry.category, entry.category),
        "subcategory": entry.subcategory,
        "model_family": entry.model_family,
        "config_source": entry.config_source,
        "status": entry.status,
        "summary": entry.summary,
        "recommended_scenarios": entry.recommended_scenarios or [],
        "limitations": entry.limitations or [],
        "integration_notes": entry.integration_notes or [],
        "documentation_url": entry.documentation_url,
        "source_urls": entry.source_urls or [],
        "tags": entry.tags or [],
        "modalities": entry.modalities or [],
        "capabilities": (entry.capabilities_json or {}).get("items", []),
        "constraints": entry.constraints_json or {},
        "performance": entry.performance_json or {},
        "routing": entry.routing_json or {},
        "default_params": entry.default_params_json or {},
        "verification_status": entry.verification_status,
        "verification_scope": entry.verification_scope,
        "verification_score": entry.verification_score,
        "total_source_count": entry.total_source_count,
        "reachable_source_count": entry.reachable_source_count,
        "verified_source_count": entry.verified_source_count,
        "verification_notes": entry.verification_notes,
        "last_synced_at": entry.last_synced_at.isoformat() if entry.last_synced_at else None,
        "last_verified_at": entry.last_verified_at.isoformat() if entry.last_verified_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        "runtime_routing_signal": (
            get_model_catalog_runtime_index().get_signal(entry.model_key).to_dict()
            if _RUNTIME_SIGNAL_AVAILABLE
            else None
        ),
        "runtime_capability_hints": (
            get_model_catalog_runtime_index().get_capability_hints(entry.model_key)
            if _RUNTIME_SIGNAL_AVAILABLE
            else {}
        ),
        "runtime_task_constraints": (
            get_model_catalog_runtime_index().get_task_constraints(entry.model_key)
            if _RUNTIME_SIGNAL_AVAILABLE
            else {}
        ),
        "project_modules": identity_profile["project_fit"]["modules"],
        "project_task_labels": identity_profile["project_fit"]["task_types"],
        "tooling_badges": integration_profile["tooling_badges"],
        "primary_strengths": identity_profile["capability_quadrants"]["strengths"][:3],
        "detailed_specs": detailed_specs,
        "pricing_verification": pricing_verification,
        "constraints_summary": _build_constraints_summary(entry),
        "capability_provenance": _build_capability_provenance(entry),
        "usage_guide": _build_usage_guide(entry),
    }
    if include_archives:
        payload["identity_profile"] = identity_profile
        payload["integration_profile"] = integration_profile
        payload["prompt_router_profile"] = _build_prompt_router_profile(entry)
        payload["deployment_profile"] = _build_deployment_profile(entry)
        payload["resource_navigation"] = _build_resource_navigation(entry)
    if include_sources:
        payload["sources"] = [
            {
                "url": item.url,
                "source_type": item.source_type,
                "source_domain": item.source_domain,
                "http_status": item.http_status,
                "reachable": item.reachable,
                "verified": item.verified,
                "page_title": item.page_title,
                "page_excerpt": item.page_excerpt,
                "matched_keywords": item.matched_keywords or [],
                "verification_note": item.verification_note,
                "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
            }
            for item in entry.sources
        ]
    return payload
