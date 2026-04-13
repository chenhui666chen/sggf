from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime

from app.services.points_pricing_policy import PointsPricingPolicyConfig, PointsPricingPolicySnapshot
from app.services.user_center_points import COMPLETED_STATUSES, RUNNING_STATUSES
from app.utils.datetime_utils import ensure_utc_datetime


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _to_finite_float(value: object | None) -> float:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount if math.isfinite(amount) else 0.0


def _to_non_negative_int(value: object | None) -> int:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(amount, 0)


def _to_float_in_range(value: object | None, fallback: float, *, minimum: float, maximum: float) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(amount):
        return fallback
    return min(max(amount, minimum), maximum)


def _safe_text(value: object | None, fallback: str) -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _normalize_status(value: object | None) -> str:
    return str(value or "").strip().lower()


def _round_amount(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _resolve_tts_price_per_10k(provider: object | None) -> float:
    provider_key = str(provider or "").strip().lower()
    provider_default_map = {
        "aliyun": _env_float("USER_CENTER_AUDIOBOOK_TTS_PRICE_PER_10K_ALIYUN", 1.0),
    }
    fallback = _env_float("USER_CENTER_AUDIOBOOK_TTS_PRICE_PER_10K_DEFAULT", 1.0)
    return max(provider_default_map.get(provider_key, fallback), 0.0)


def _convert_yuan_to_points(yuan: float, config: PointsPricingPolicyConfig) -> float:
    amount = max(float(yuan), 0.0) * max(int(config.points_per_yuan), 1) * max(float(config.user_price_rate), 0.0)
    return round(amount, 2)


def _apply_freeze_buffer(points: float, config: PointsPricingPolicyConfig) -> float:
    buffered = max(float(points), 0.0) * (1 + max(float(config.freeze_buffer_rate), 0.0))
    return round(buffered, 2)


@dataclass(frozen=True)
class UserCenterPricingPolicyOverviewSnapshot:
    points_per_yuan: int
    user_price_basis: str
    user_price_rate: float
    freeze_buffer_rate: float
    source: str
    updated_at: datetime | None = None
    updated_by_user_id: int | None = None
    updated_by_username: str | None = None


@dataclass(frozen=True)
class UserCenterTaskBillingItemSnapshot:
    key: str
    module_key: str
    module_label: str
    title: str
    summary: str
    task_status: str
    pricing_status: str
    actual_yuan: float | None = None
    actual_points: float | None = None
    estimated_yuan: float | None = None
    estimated_points: float | None = None
    suggested_frozen_points: float | None = None
    occurred_at: datetime | None = None
    action_path: str | None = None
    action_label: str | None = None


@dataclass(frozen=True)
class UserCenterTaskBillingOverviewSnapshot:
    actual_spend_yuan: float
    actual_spend_points: float
    estimated_running_spend_yuan: float
    estimated_running_spend_points: float
    suggested_frozen_points: float
    actual_task_count: int
    estimated_task_count: int
    pending_task_count: int
    items: tuple[UserCenterTaskBillingItemSnapshot, ...]


@dataclass(frozen=True)
class _ProjectChapterUsage:
    project_id: int
    chapter_count: int
    content_units: int


def _build_project_chapter_usage(chapter_rows: list[object]) -> dict[int, _ProjectChapterUsage]:
    usage: dict[int, _ProjectChapterUsage] = {}

    chapter_count_by_project: dict[int, int] = {}
    content_units_by_project: dict[int, int] = {}

    for row in chapter_rows:
        project_id = _to_non_negative_int(getattr(row, "project_id", 0))
        if project_id <= 0:
            continue

        chapter_count_by_project[project_id] = chapter_count_by_project.get(project_id, 0) + 1
        word_count = _to_non_negative_int(getattr(row, "word_count", 0))
        content = str(getattr(row, "content", "") or "")
        content_units = max(word_count, len(content))
        content_units_by_project[project_id] = content_units_by_project.get(project_id, 0) + content_units

    for project_id, chapter_count in chapter_count_by_project.items():
        usage[project_id] = _ProjectChapterUsage(
            project_id=project_id,
            chapter_count=chapter_count,
            content_units=content_units_by_project.get(project_id, 0),
        )

    return usage


def _estimate_running_audiobook_yuan(
    row: object,
    *,
    chapter_usage: _ProjectChapterUsage | None,
) -> tuple[float | None, str]:
    total_cost = _to_finite_float(getattr(row, "total_cost", None))
    total_chapters = _to_non_negative_int(getattr(row, "total_chapters", 0))
    completed_chapters = _to_non_negative_int(getattr(row, "completed_chapters", 0))
    tts_provider = getattr(row, "tts_provider", None)

    estimate_candidates: list[tuple[float, str]] = []

    if chapter_usage and chapter_usage.content_units > 0:
        provider_price = _resolve_tts_price_per_10k(tts_provider)
        estimated_from_text = (chapter_usage.content_units / 10000.0) * provider_price
        estimate_candidates.append(
            (
                estimated_from_text,
                f"按项目章节约 {chapter_usage.content_units} 字和 {provider_price:.2f} 元/万字估算",
            )
        )

    if total_cost > 0 and completed_chapters > 0 and total_chapters > completed_chapters:
        estimated_from_progress = (total_cost / completed_chapters) * total_chapters
        estimate_candidates.append(
            (
                estimated_from_progress,
                f"按已完成 {completed_chapters}/{total_chapters} 章节的当前实际成本外推",
            )
        )

    if total_cost > 0 and not estimate_candidates:
        estimate_candidates.append((total_cost, "按当前已累计的实际成本估算"))

    if not estimate_candidates:
        return None, "待接入章节字数或实时成本后再计算预估积分"

    estimated_yuan, basis_label = max(estimate_candidates, key=lambda item: item[0])
    estimated_yuan = max(estimated_yuan, total_cost)
    return round(estimated_yuan, 2), basis_label


def _count_dreamweaver_shots(contract_json: object | None) -> int:
    if not isinstance(contract_json, dict):
        return 0

    episodes = contract_json.get("episodes")
    if not isinstance(episodes, list):
        return 0

    total_shots = 0
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        shots = episode.get("shots")
        if isinstance(shots, list):
            total_shots += len([shot for shot in shots if isinstance(shot, dict)])
    return total_shots


def _extract_dreamweaver_runtime_config(contract_json: object | None) -> dict[str, object]:
    if not isinstance(contract_json, dict):
        return {}

    runtime_config = contract_json.get("runtime_config")
    if not isinstance(runtime_config, dict):
        return {}

    return runtime_config


def _extract_dreamweaver_quality_mode(contract_json: object | None) -> str | None:
    runtime_config = _extract_dreamweaver_runtime_config(contract_json)
    quality_mode = str(runtime_config.get("quality_mode") or "").strip().lower()
    return quality_mode or None


def _resolve_dreamweaver_video_engine(runtime_config: dict[str, object], quality_mode: str | None) -> str:
    video_config = runtime_config.get("video_config")
    if isinstance(video_config, dict):
        engine = str(video_config.get("engine") or "").strip().lower()
        if engine:
            return engine

    if quality_mode == "quality":
        return "wan_auto"
    if quality_mode == "cost":
        return "ffmpeg_slideshow"
    return "ffmpeg_slideshow"


def _get_dreamweaver_quality_mode_defaults(quality_mode: str | None) -> tuple[dict[str, object], dict[str, object]]:
    if quality_mode == "quality":
        return (
            {
                "t2i_candidates": 2,
                "mid_candidates": 2,
                "head_use_image_edit": True,
                "tail_use_image_edit": True,
                "mid_use_image_edit": True,
            },
            {
                "enable_semantic_qc": True,
                "semantic_sample_rate": 0.6,
            },
        )
    if quality_mode == "cost":
        return (
            {
                "t2i_candidates": 1,
                "mid_candidates": 1,
                "head_use_image_edit": False,
                "tail_use_image_edit": False,
                "mid_use_image_edit": False,
            },
            {
                "enable_semantic_qc": False,
                "semantic_sample_rate": 0.0,
            },
        )
    return ({}, {})


def _estimate_running_dreamweaver_yuan(contract_json: object | None) -> tuple[float | None, str]:
    shot_count = _count_dreamweaver_shots(contract_json)
    if shot_count <= 0:
        return None, "待识别镜头数后再计算短剧预估积分"

    runtime_config = _extract_dreamweaver_runtime_config(contract_json)
    quality_mode = _extract_dreamweaver_quality_mode(contract_json)
    quality_mode_label = "高质量" if quality_mode == "quality" else "成本优先" if quality_mode == "cost" else "默认模式"
    default_image_config, default_qc_config = _get_dreamweaver_quality_mode_defaults(quality_mode)
    image_config = {
        **default_image_config,
        **(runtime_config.get("image_config") if isinstance(runtime_config.get("image_config"), dict) else {}),
    }
    qc_config = {
        **default_qc_config,
        **(runtime_config.get("qc_config") if isinstance(runtime_config.get("qc_config"), dict) else {}),
    }

    t2i_candidates = max(_to_non_negative_int(image_config.get("t2i_candidates")), 1)
    mid_candidates = max(_to_non_negative_int(image_config.get("mid_candidates")), 0)
    image_request_units = (2 * t2i_candidates) + mid_candidates

    image_edit_units = sum(
        1
        for key in ("head_use_image_edit", "tail_use_image_edit", "mid_use_image_edit")
        if bool(image_config.get(key))
    )

    video_engine = _resolve_dreamweaver_video_engine(runtime_config, quality_mode)
    video_unit_price = {
        "wan_auto": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_WAN_AUTO", 0.15),
        "wan_i2v": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_WAN_I2V", 0.18),
        "i2v": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_I2V", 0.18),
        "auto": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_AUTO", 0.15),
        "ffmpeg_slideshow": _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_FFMPEG", 0.0),
    }.get(video_engine, _env_float("USER_CENTER_DREAMWEAVER_VIDEO_UNIT_PRICE_DEFAULT", 0.08))

    semantic_qc_enabled = bool(qc_config.get("enable_semantic_qc"))
    semantic_sample_rate = _to_float_in_range(
        qc_config.get("semantic_sample_rate"),
        1.0 if semantic_qc_enabled else 0.0,
        minimum=0.0,
        maximum=1.0,
    )

    run_base_price = _env_float("USER_CENTER_DREAMWEAVER_RUN_BASE_PRICE", 0.3)
    image_request_unit_price = _env_float("USER_CENTER_DREAMWEAVER_IMAGE_REQUEST_UNIT_PRICE", 0.05)
    image_edit_unit_price = _env_float("USER_CENTER_DREAMWEAVER_IMAGE_EDIT_UNIT_PRICE", 0.05)
    semantic_qc_unit_price = _env_float("USER_CENTER_DREAMWEAVER_SEMANTIC_QC_UNIT_PRICE", 0.02)
    smart_tuning_surcharge = (
        _env_float("USER_CENTER_DREAMWEAVER_SMART_TUNING_SURCHARGE", 0.15)
        if bool(runtime_config.get("smart_tuning"))
        else 0.0
    )

    per_shot_yuan = (
        (image_request_units * image_request_unit_price)
        + (image_edit_units * image_edit_unit_price)
        + max(video_unit_price, 0.0)
        + ((semantic_qc_unit_price * semantic_sample_rate) if semantic_qc_enabled else 0.0)
    )
    estimated_yuan = max(run_base_price, 0.0) + max(smart_tuning_surcharge, 0.0) + (shot_count * per_shot_yuan)

    return round(estimated_yuan, 2), (
        f"按 {shot_count} 个镜头、{quality_mode_label} 配置、图像候选 {image_request_units} 单位、"
        f"视频引擎 {video_engine} 估算"
    )


def build_user_center_pricing_policy_overview(
    snapshot: PointsPricingPolicySnapshot,
) -> UserCenterPricingPolicyOverviewSnapshot:
    config = snapshot.config
    return UserCenterPricingPolicyOverviewSnapshot(
        points_per_yuan=max(int(config.points_per_yuan), 1),
        user_price_basis=str(config.user_price_basis or "public_list_price"),
        user_price_rate=round(max(float(config.user_price_rate), 0.0), 4),
        freeze_buffer_rate=round(max(float(config.freeze_buffer_rate), 0.0), 4),
        source=snapshot.source,
        updated_at=snapshot.updated_at,
        updated_by_user_id=snapshot.updated_by_user_id,
        updated_by_username=snapshot.updated_by_username,
    )


def build_user_center_task_billing_overview(
    *,
    audiobook_rows: list[object],
    dreamweaver_rows: list[object],
    chapter_rows: list[object],
    pricing_config: PointsPricingPolicyConfig,
) -> UserCenterTaskBillingOverviewSnapshot:
    chapter_usage_by_project = _build_project_chapter_usage(chapter_rows)

    actual_spend_yuan = 0.0
    actual_spend_points = 0.0
    estimated_running_spend_yuan = 0.0
    estimated_running_spend_points = 0.0
    suggested_frozen_points = 0.0
    actual_task_count = 0
    estimated_task_count = 0
    pending_task_count = 0

    items: list[UserCenterTaskBillingItemSnapshot] = []

    for index, row in enumerate(audiobook_rows, start=1):
        row_id = _to_non_negative_int(getattr(row, "id", 0)) or index
        project_id = _to_non_negative_int(getattr(row, "project_id", 0))
        title = _safe_text(getattr(row, "project_title", None), f"有声书项目 #{row_id}")
        status = _normalize_status(getattr(row, "status", None))
        occurred_at = ensure_utc_datetime(getattr(row, "updated_at", None)) or ensure_utc_datetime(
            getattr(row, "created_at", None)
        )

        actual_yuan = _to_finite_float(getattr(row, "total_cost", None))
        actual_points = _convert_yuan_to_points(actual_yuan, pricing_config) if actual_yuan > 0 else None
        if actual_yuan > 0:
            actual_spend_yuan += actual_yuan
            actual_spend_points += actual_points or 0.0

        action_path = f"/audiobook/{project_id}" if project_id > 0 else "/audiobook-dashboard"
        action_label = "查看有声书项目"

        if status in COMPLETED_STATUSES and actual_yuan > 0:
            actual_task_count += 1
            items.append(
                UserCenterTaskBillingItemSnapshot(
                    key=f"audiobook-billing-{row_id}",
                    module_key="audiobook",
                    module_label="有声书",
                    title=title,
                    summary=f"任务已完成，实际成本 ￥{actual_yuan:.2f}，按当前用户计价折算约 {actual_points:.2f} 积分。",
                    task_status="completed",
                    pricing_status="actual",
                    actual_yuan=_round_amount(actual_yuan),
                    actual_points=_round_amount(actual_points),
                    occurred_at=occurred_at,
                    action_path=action_path,
                    action_label=action_label,
                )
            )
            continue

        if status not in RUNNING_STATUSES:
            continue

        estimated_yuan, estimate_basis = _estimate_running_audiobook_yuan(
            row,
            chapter_usage=chapter_usage_by_project.get(project_id),
        )

        if estimated_yuan is None:
            pending_task_count += 1
            items.append(
                UserCenterTaskBillingItemSnapshot(
                    key=f"audiobook-billing-{row_id}",
                    module_key="audiobook",
                    module_label="有声书",
                    title=title,
                    summary=f"任务运行中，{estimate_basis}。",
                    task_status="running",
                    pricing_status="pending",
                    actual_yuan=_round_amount(actual_yuan) if actual_yuan > 0 else None,
                    actual_points=_round_amount(actual_points) if actual_points is not None else None,
                    occurred_at=occurred_at,
                    action_path=action_path,
                    action_label=action_label,
                )
            )
            continue

        estimated_points = _convert_yuan_to_points(estimated_yuan, pricing_config)
        buffered_points = _apply_freeze_buffer(estimated_points, pricing_config)

        estimated_running_spend_yuan += estimated_yuan
        estimated_running_spend_points += estimated_points
        suggested_frozen_points += buffered_points
        estimated_task_count += 1

        actual_summary = ""
        if actual_yuan > 0:
            actual_summary = f" 当前已发生 ￥{actual_yuan:.2f} 实际成本；"

        items.append(
            UserCenterTaskBillingItemSnapshot(
                key=f"audiobook-billing-{row_id}",
                module_key="audiobook",
                module_label="有声书",
                title=title,
                summary=(
                    f"任务运行中，{estimate_basis}，预计总成本 ￥{estimated_yuan:.2f}，"
                    f"按当前用户计价约 {estimated_points:.2f} 积分，建议冻结 {buffered_points:.2f} 积分。"
                    f"{actual_summary}"
                ).strip(),
                task_status="running",
                pricing_status="estimated",
                actual_yuan=_round_amount(actual_yuan) if actual_yuan > 0 else None,
                actual_points=_round_amount(actual_points) if actual_points is not None else None,
                estimated_yuan=_round_amount(estimated_yuan),
                estimated_points=_round_amount(estimated_points),
                suggested_frozen_points=_round_amount(buffered_points),
                occurred_at=occurred_at,
                action_path=action_path,
                action_label=action_label,
            )
        )

    for index, row in enumerate(dreamweaver_rows, start=1):
        status = _normalize_status(getattr(row, "status", None))

        row_id = _to_non_negative_int(getattr(row, "id", 0)) or index
        run_id = _safe_text(getattr(row, "run_id", None), f"run-{row_id}")
        project_id = _to_non_negative_int(getattr(row, "source_project_id", 0))
        title = _safe_text(getattr(row, "project_title", None), f"短剧运行 {run_id}")
        stage = str(getattr(row, "stage", "") or "").strip()
        shot_count = _count_dreamweaver_shots(getattr(row, "contract_json", None))
        quality_mode = _extract_dreamweaver_quality_mode(getattr(row, "contract_json", None))
        quality_mode_label = "高质量" if quality_mode == "quality" else "成本优先" if quality_mode == "cost" else "默认模式"
        stage_summary = f"，当前阶段 {stage}" if stage else ""
        shot_summary = f"，已识别 {shot_count} 个镜头" if shot_count > 0 else ""
        occurred_at = ensure_utc_datetime(getattr(row, "updated_at", None)) or ensure_utc_datetime(
            getattr(row, "created_at", None)
        )
        action_path = f"/drama/{project_id}" if project_id > 0 else "/drama"

        estimated_yuan, estimate_basis = _estimate_running_dreamweaver_yuan(getattr(row, "contract_json", None))
        if status in COMPLETED_STATUSES and estimated_yuan is not None:
            actual_points = _convert_yuan_to_points(estimated_yuan, pricing_config)
            actual_spend_yuan += estimated_yuan
            actual_spend_points += actual_points
            actual_task_count += 1

            items.append(
                UserCenterTaskBillingItemSnapshot(
                    key=f"dreamweaver-billing-{run_id}",
                    module_key="dreamweaver",
                    module_label="短剧",
                    title=title,
                    summary=(
                        f"任务已完成{shot_summary}，按最终短剧合同快照结算，"
                        f"{estimate_basis}，按当前用户计价折算约 {actual_points:.2f} 积分。"
                    ),
                    task_status="completed",
                    pricing_status="actual",
                    actual_yuan=_round_amount(estimated_yuan),
                    actual_points=_round_amount(actual_points),
                    occurred_at=occurred_at,
                    action_path=action_path,
                    action_label="查看短剧项目",
                )
            )
            continue

        if status not in RUNNING_STATUSES:
            continue

        if estimated_yuan is None:
            pending_task_count += 1
            items.append(
                UserCenterTaskBillingItemSnapshot(
                    key=f"dreamweaver-billing-{run_id}",
                    module_key="dreamweaver",
                    module_label="短剧",
                    title=title,
                    summary=(
                        f"任务运行中{stage_summary}{shot_summary}，当前为 {quality_mode_label}。"
                        f"{estimate_basis}。"
                    ),
                    task_status="running",
                    pricing_status="pending",
                    occurred_at=occurred_at,
                    action_path=action_path,
                    action_label="查看短剧项目",
                )
            )
            continue

        estimated_points = _convert_yuan_to_points(estimated_yuan, pricing_config)
        buffered_points = _apply_freeze_buffer(estimated_points, pricing_config)

        estimated_running_spend_yuan += estimated_yuan
        estimated_running_spend_points += estimated_points
        suggested_frozen_points += buffered_points
        estimated_task_count += 1

        items.append(
            UserCenterTaskBillingItemSnapshot(
                key=f"dreamweaver-billing-{run_id}",
                module_key="dreamweaver",
                module_label="短剧",
                title=title,
                summary=(
                    f"任务运行中{stage_summary}{shot_summary}，{estimate_basis}，预计总成本 ￥{estimated_yuan:.2f}，"
                    f"按当前用户计价约 {estimated_points:.2f} 积分，建议冻结 {buffered_points:.2f} 积分。"
                ),
                task_status="running",
                pricing_status="estimated",
                estimated_yuan=_round_amount(estimated_yuan),
                estimated_points=_round_amount(estimated_points),
                suggested_frozen_points=_round_amount(buffered_points),
                occurred_at=occurred_at,
                action_path=action_path,
                action_label="查看短剧项目",
            )
        )

    items.sort(
        key=lambda item: (
            ensure_utc_datetime(item.occurred_at).timestamp() if ensure_utc_datetime(item.occurred_at) else 0.0,
            item.key,
        ),
        reverse=True,
    )

    return UserCenterTaskBillingOverviewSnapshot(
        actual_spend_yuan=round(actual_spend_yuan, 2),
        actual_spend_points=round(actual_spend_points, 2),
        estimated_running_spend_yuan=round(estimated_running_spend_yuan, 2),
        estimated_running_spend_points=round(estimated_running_spend_points, 2),
        suggested_frozen_points=round(suggested_frozen_points, 2),
        actual_task_count=actual_task_count,
        estimated_task_count=estimated_task_count,
        pending_task_count=pending_task_count,
        items=tuple(items),
    )
