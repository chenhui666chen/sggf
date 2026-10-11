from __future__ import annotations

from typing import Any, Mapping, Optional

from pipeline.media_presets import DREAMWEAVER_AUTO_ENGINE, DREAMWEAVER_I2V_ENGINE

from .contracts import (
    ALLOWED_PROVIDER_MODES,
    ALLOWED_SELECTOR_MODES,
    DreamweaverRunPreflight,
    normalize_provider_mode,
    normalize_selector_mode,
    resolve_video_generation_controls,
)


_SELECTOR_SUPPORTED_ENGINES = {DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_AUTO_ENGINE}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def build_dreamweaver_run_preflight(
    *,
    quality_mode: Optional[str],
    smart_tuning: Optional[bool],
    qc_allow_fail: Optional[bool],
    video_require_confirmation: Optional[bool],
    runtime_config: Optional[Mapping[str, Any]],
) -> DreamweaverRunPreflight:
    runtime = dict(runtime_config or {})
    raw_video_config = runtime.get("video_config") if isinstance(runtime.get("video_config"), Mapping) else {}
    video_config = resolve_video_generation_controls(raw_video_config)
    result = DreamweaverRunPreflight(resolved_video_config=video_config)

    if _normalize_text(quality_mode) == "quality" and smart_tuning is False:
        result.add_warning(
            "quality_mode_without_smart_tuning",
            "高质量模式建议开启智能调参，否则可能增加无效生成和返工成本。",
        )

    if video_require_confirmation is True and qc_allow_fail is True:
        result.add_warning(
            "confirmation_with_qc_allow_fail",
            "视频确认模式与质检容错同时开启时，人工确认与自动放行的语义容易冲突。",
        )

    raw_provider_mode = _normalize_text(raw_video_config.get("provider_mode"))
    raw_selector_mode = _normalize_text(raw_video_config.get("selector_mode"))
    provider_mode = video_config.get("provider_mode", "wan_only")
    selector_mode = video_config.get("selector_mode", "off")
    engine = _normalize_text(video_config.get("engine"))
    allow_kling_omni = bool(video_config.get("allow_kling_omni"))
    enable_kling_video_provider = bool(video_config.get("enable_kling_video_provider"))
    allow_subject_bridge = bool(video_config.get("allow_subject_bridge"))
    allow_subject_bridge_auto_sync = bool(video_config.get("allow_subject_bridge_auto_sync"))

    if raw_provider_mode and raw_provider_mode not in ALLOWED_PROVIDER_MODES:
        result.add_error(
            "invalid_provider_mode",
            f"video_config.provider_mode 仅支持 {', '.join(sorted(ALLOWED_PROVIDER_MODES))}。",
        )

    if raw_selector_mode and raw_selector_mode not in ALLOWED_SELECTOR_MODES:
        result.add_error(
            "invalid_selector_mode",
            f"video_config.selector_mode 仅支持 {', '.join(sorted(ALLOWED_SELECTOR_MODES))}。",
        )

    # Phase 1 先落 shadow，可观测但不切流。
    if selector_mode == "active":
        result.add_error(
            "selector_active_not_available",
            "当前阶段仅支持 selector_mode=off/shadow；active 切流会在后续 provider 执行器接入后再开放。",
        )

    if provider_mode in {"auto", "kling_omni"} and not allow_kling_omni:
        result.add_error(
            "kling_omni_not_enabled",
            "provider_mode 需要 allow_kling_omni=True 才能启用 Kling Omni 路径。",
        )

    if provider_mode == "kling_omni" and not enable_kling_video_provider:
        result.add_error(
            "kling_video_provider_disabled",
            "provider_mode=kling_omni 需要先开启 DREAMWEAVER_ENABLE_KLING_VIDEO_PROVIDER，当前灰度执行入口未启用。",
        )

    if selector_mode != "off" and engine and engine not in _SELECTOR_SUPPORTED_ENGINES:
        level = "error" if provider_mode == "kling_omni" else "warning"
        message = (
            "当前视频引擎不支持 selector 路由评估，建议先使用 wan_auto"
            "（wan3.0-video 为 all-in-one 模型，会自动归入 wan_auto 引擎）。"
        )
        if level == "error":
            result.add_error("selector_engine_unsupported", message)
        else:
            result.add_warning("selector_engine_unsupported", message)

    if allow_subject_bridge and not allow_kling_omni:
        result.add_warning(
            "subject_bridge_without_kling",
            "allow_subject_bridge 已开启，但 allow_kling_omni 未开启；主体桥接暂不会参与 provider 选择。",
        )

    if allow_subject_bridge_auto_sync and not allow_subject_bridge:
        result.add_warning(
            "subject_bridge_auto_sync_without_bridge",
            "allow_subject_bridge_auto_sync 已开启，但 allow_subject_bridge 未开启；自动同步不会生效。",
        )

    if allow_subject_bridge_auto_sync and not allow_kling_omni:
        result.add_warning(
            "subject_bridge_auto_sync_without_kling",
            "allow_subject_bridge_auto_sync 已开启，但 allow_kling_omni 未开启；即使同步成功，也不会参与 Kling 路由判断。",
        )

    return result
