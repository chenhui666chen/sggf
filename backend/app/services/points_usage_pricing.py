from __future__ import annotations

import math
import os
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.services.asset_studio_model_catalog import resolve_video_price_per_second
from app.services.points_pricing_policy import (
    PointsBusinessSettlementSnapshot,
    build_points_business_settlement_snapshot,
    get_points_pricing_policy_snapshot,
)
from app.services.user_center_points_events import get_active_points_billing_freeze_amount
from app.services.user_points_read_model import build_user_points_read_model


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def _to_non_negative_float(value: object | None, fallback: float = 0.0) -> float:
    try:
        amount = float(value if value is not None else fallback)
    except (TypeError, ValueError):
        return max(float(fallback), 0.0)
    if not math.isfinite(amount):
        return max(float(fallback), 0.0)
    return max(amount, 0.0)


def _to_non_negative_int(value: object | None, fallback: int = 0) -> int:
    try:
        amount = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        return max(int(fallback), 0)
    return max(amount, 0)


def _round_yuan(value: float) -> float:
    amount = max(float(value), 0.0)
    if amount > 0 and amount < 0.01:
        return 0.01
    return round(amount, 2)


def _ceil_units(value: int | float, unit: int | float) -> int:
    normalized_unit = max(float(unit), 1.0)
    return max(int(math.ceil(max(float(value), 0.0) / normalized_unit)), 0)


def _safe_text(value: object | None, fallback: str = "") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def supports_points_billing_session(db: object) -> bool:
    return isinstance(db, Session)


@dataclass(frozen=True)
class PointsUsageChargeEstimate:
    basis_yuan: float
    user_billed_yuan: float
    estimated_points: float
    required_frozen_points: float
    operating_snapshot: PointsBusinessSettlementSnapshot


@dataclass(frozen=True)
class PointsBillingPrecheckSnapshot:
    allowed: bool
    failure_code: str | None
    failure_message: str | None
    module_key: str
    module_label: str
    billing_key: str
    estimated_yuan: float
    estimated_points: float
    required_frozen_points: float
    existing_frozen_points: float
    additional_frozen_points: float
    balance_points: float
    frozen_points: float
    available_points: float
    operating_snapshot: PointsBusinessSettlementSnapshot | None


def _serialize_precheck_value(value: object) -> object | None:
    if value is None:
        return None
    if hasattr(value, "to_payload") and callable(getattr(value, "to_payload")):
        return value.to_payload()
    if is_dataclass(value):
        payload: dict[str, object] = {}
        for field in fields(value):
            serialized = _serialize_precheck_value(getattr(value, field.name))
            if serialized is not None:
                payload[field.name] = serialized
        return payload
    return value


def build_points_billing_precheck_error_detail(
    *,
    precheck: PointsBillingPrecheckSnapshot,
    default_message: str,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "message": precheck.failure_message or default_message,
        "module_key": precheck.module_key,
        "module_label": precheck.module_label,
        "billing_key": precheck.billing_key,
        "allowed": False,
        "failure_code": precheck.failure_code or "points_precheck_failed",
    }
    for field in fields(precheck):
        if field.name in {"allowed", "failure_code", "failure_message"}:
            continue
        serialized = _serialize_precheck_value(getattr(precheck, field.name))
        if serialized is not None:
            detail[field.name] = serialized
    return detail


def build_points_usage_charge_estimate(
    *,
    db: Session,
    module_key: str,
    basis_yuan: float,
    provider_key: str | None = None,
    include_freeze_buffer: bool = True,
) -> PointsUsageChargeEstimate:
    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    normalized_basis_yuan = _round_yuan(basis_yuan)
    operating_snapshot = build_points_business_settlement_snapshot(
        pricing_config=pricing_snapshot.config,
        module_key=module_key,
        basis_yuan=normalized_basis_yuan,
        provider_key=provider_key,
    )
    estimated_points = round(
        max(float(operating_snapshot.user_billed_yuan), 0.0)
        * max(int(pricing_snapshot.config.points_per_yuan), 1),
        2,
    )
    required_frozen_points = estimated_points
    if include_freeze_buffer:
        required_frozen_points = round(
            estimated_points * (1 + max(float(pricing_snapshot.config.freeze_buffer_rate), 0.0)),
            2,
        )
    return PointsUsageChargeEstimate(
        basis_yuan=normalized_basis_yuan,
        user_billed_yuan=round(float(operating_snapshot.user_billed_yuan), 2),
        estimated_points=estimated_points,
        required_frozen_points=required_frozen_points,
        operating_snapshot=operating_snapshot,
    )


def build_points_billing_precheck(
    *,
    db: Session,
    user_id: int,
    billing_key: str,
    module_key: str,
    module_label: str,
    basis_yuan: float,
    provider_key: str | None = None,
) -> PointsBillingPrecheckSnapshot:
    estimate = build_points_usage_charge_estimate(
        db=db,
        module_key=module_key,
        basis_yuan=basis_yuan,
        provider_key=provider_key,
        include_freeze_buffer=True,
    )
    if estimate.basis_yuan <= 0 or estimate.required_frozen_points <= 0:
        return PointsBillingPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message=f"当前无法估算{module_label}任务的积分消耗，请稍后重试。",
            module_key=module_key,
            module_label=module_label,
            billing_key=billing_key,
            estimated_yuan=estimate.basis_yuan,
            estimated_points=estimate.estimated_points,
            required_frozen_points=estimate.required_frozen_points,
            existing_frozen_points=0.0,
            additional_frozen_points=0.0,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=estimate.operating_snapshot,
        )

    if estimate.operating_snapshot.negative_margin_blocked:
        return PointsBillingPrecheckSnapshot(
            allowed=False,
            failure_code="negative_margin_blocked",
            failure_message=(
                f"当前积分定价策略会导致{module_label}任务预计毛利为负，系统已阻止启动。"
                f" 预计成本 {estimate.basis_yuan:.2f} 元，需冻结 {estimate.required_frozen_points:.2f} 积分。"
            ),
            module_key=module_key,
            module_label=module_label,
            billing_key=billing_key,
            estimated_yuan=estimate.basis_yuan,
            estimated_points=estimate.estimated_points,
            required_frozen_points=estimate.required_frozen_points,
            existing_frozen_points=0.0,
            additional_frozen_points=estimate.required_frozen_points,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=estimate.operating_snapshot,
        )

    read_model = build_user_points_read_model(db=db, user_id=int(user_id or 0))
    account = read_model.points_bundle.account
    balance_points = round(float(account.balance), 2)
    frozen_points = round(float(account.frozen), 2)
    available_points = round(balance_points - frozen_points, 2)
    existing_frozen_points = get_active_points_billing_freeze_amount(
        db=db,
        target_user_id=int(user_id or 0),
        billing_key=billing_key,
    )
    additional_frozen_points = round(max(estimate.required_frozen_points - existing_frozen_points, 0.0), 2)

    if available_points + 1e-6 < additional_frozen_points:
        return PointsBillingPrecheckSnapshot(
            allowed=False,
            failure_code="insufficient_available_points",
            failure_message=(
                f"当前可用积分不足，无法启动{module_label}任务。"
                f" 当前可用 {available_points:.2f} 积分，"
                f"本次需冻结 {estimate.required_frozen_points:.2f} 积分，"
                f"仍需额外冻结 {additional_frozen_points:.2f} 积分。"
            ),
            module_key=module_key,
            module_label=module_label,
            billing_key=billing_key,
            estimated_yuan=estimate.basis_yuan,
            estimated_points=estimate.estimated_points,
            required_frozen_points=estimate.required_frozen_points,
            existing_frozen_points=existing_frozen_points,
            additional_frozen_points=additional_frozen_points,
            balance_points=balance_points,
            frozen_points=frozen_points,
            available_points=available_points,
            operating_snapshot=estimate.operating_snapshot,
        )

    return PointsBillingPrecheckSnapshot(
        allowed=True,
        failure_code=None,
        failure_message=None,
        module_key=module_key,
        module_label=module_label,
        billing_key=billing_key,
        estimated_yuan=estimate.basis_yuan,
        estimated_points=estimate.estimated_points,
        required_frozen_points=estimate.required_frozen_points,
        existing_frozen_points=existing_frozen_points,
        additional_frozen_points=additional_frozen_points,
        balance_points=balance_points,
        frozen_points=frozen_points,
        available_points=available_points,
        operating_snapshot=estimate.operating_snapshot,
    )


def estimate_story_expansion_request_basis_yuan(request: object) -> float:
    current_chapters = _to_non_negative_int(getattr(request, "current_chapter_count", 0))
    current_characters = _to_non_negative_int(getattr(request, "current_character_count", 0))
    target_chapters = _to_non_negative_int(getattr(request, "target_total_chapters", 0), current_chapters)
    target_characters = _to_non_negative_int(getattr(request, "target_total_characters", 0), current_characters)
    expansion_mode = _safe_text(getattr(request, "expansion_mode", ""), "total").lower()

    if expansion_mode == "volume_detail":
        volume_chapter_target = max(
            _to_non_negative_int(getattr(request, "volume_chapters_min", 0)),
            _to_non_negative_int(getattr(request, "volume_chapters_max", 0)),
        )
        target_chapters = max(target_chapters, current_chapters + volume_chapter_target)
    elif expansion_mode == "epic":
        epic_chapter_target = max(
            _to_non_negative_int(getattr(request, "total_chapters_min", 0)),
            _to_non_negative_int(getattr(request, "total_chapters_max", 0)),
            target_chapters,
        )
        target_chapters = max(target_chapters, epic_chapter_target)

    chapter_delta = max(target_chapters - current_chapters, 0)
    character_delta = max(target_characters - current_characters, 0)
    total_volumes = _to_non_negative_int(getattr(request, "total_volumes", 0))
    return estimate_story_expansion_basis_yuan(
        chapter_delta=chapter_delta,
        character_delta=character_delta,
        expansion_mode=expansion_mode,
        total_volumes=total_volumes,
        execution_round_count=1,
        reset_epic_framework=bool(getattr(request, "reset_epic_framework", False)),
    )


def estimate_story_expansion_result_basis_yuan(
    *,
    initial_chapter_count: int,
    final_chapter_count: int,
    initial_character_count: int,
    final_character_count: int,
    execution_mode: str | None,
    execution_rounds: Sequence[object] | None = None,
    epic_total_volumes: int | None = None,
) -> float:
    return estimate_story_expansion_basis_yuan(
        chapter_delta=max(int(final_chapter_count or 0) - int(initial_chapter_count or 0), 0),
        character_delta=max(int(final_character_count or 0) - int(initial_character_count or 0), 0),
        expansion_mode=_safe_text(execution_mode, "delta"),
        total_volumes=_to_non_negative_int(epic_total_volumes),
        execution_round_count=max(len(list(execution_rounds or [])), 1),
        reset_epic_framework=False,
    )


def estimate_story_expansion_basis_yuan(
    *,
    chapter_delta: int,
    character_delta: int,
    expansion_mode: str,
    total_volumes: int = 0,
    execution_round_count: int = 1,
    reset_epic_framework: bool = False,
) -> float:
    base_yuan = _env_float("POINTS_NOVEL_EXPANSION_BASE_YUAN", 0.2)
    per_chapter_yuan = _env_float("POINTS_NOVEL_EXPANSION_PER_CHAPTER_YUAN", 0.06)
    per_character_yuan = _env_float("POINTS_NOVEL_EXPANSION_PER_CHARACTER_YUAN", 0.1)
    per_round_yuan = _env_float("POINTS_NOVEL_EXPANSION_PER_ROUND_YUAN", 0.08)
    per_epic_volume_yuan = _env_float("POINTS_NOVEL_EXPANSION_PER_EPIC_VOLUME_YUAN", 0.08)
    volume_detail_surcharge_yuan = _env_float("POINTS_NOVEL_EXPANSION_VOLUME_DETAIL_SURCHARGE_YUAN", 0.15)
    reset_surcharge_yuan = _env_float("POINTS_NOVEL_EXPANSION_RESET_FRAMEWORK_SURCHARGE_YUAN", 0.1)

    normalized_mode = _safe_text(expansion_mode, "delta").lower()
    mode_multiplier = 1.0
    if normalized_mode == "iterative":
        mode_multiplier = _env_float("POINTS_NOVEL_EXPANSION_ITERATIVE_MULTIPLIER", 1.2)
    elif normalized_mode == "epic":
        mode_multiplier = _env_float("POINTS_NOVEL_EXPANSION_EPIC_MULTIPLIER", 1.35)
    elif normalized_mode == "volume_detail":
        mode_multiplier = _env_float("POINTS_NOVEL_EXPANSION_VOLUME_DETAIL_MULTIPLIER", 1.25)

    amount = (
        base_yuan
        + (max(int(chapter_delta or 0), 0) * per_chapter_yuan)
        + (max(int(character_delta or 0), 0) * per_character_yuan)
        + (max(int(execution_round_count or 1), 1) * per_round_yuan)
        + (max(int(total_volumes or 0), 0) * per_epic_volume_yuan)
    )
    if normalized_mode == "volume_detail":
        amount += volume_detail_surcharge_yuan
    if reset_epic_framework:
        amount += reset_surcharge_yuan

    return _round_yuan(amount * max(mode_multiplier, 0.0))


def estimate_book_parse_basis_yuan(total_words: int | None) -> float:
    word_units = _ceil_units(_to_non_negative_int(total_words), 10000)
    amount = max(
        _env_float("POINTS_BOOK_PARSER_PARSE_MIN_YUAN", 0.05),
        word_units * _env_float("POINTS_BOOK_PARSER_PARSE_PER_10K_YUAN", 0.02),
    )
    return _round_yuan(amount)


def estimate_book_analyze_basis_yuan(total_words: int | None, chapter_count: int | None) -> float:
    word_units = _ceil_units(_to_non_negative_int(total_words), 10000)
    normalized_chapter_count = _to_non_negative_int(chapter_count)
    amount = max(
        _env_float("POINTS_BOOK_PARSER_ANALYZE_MIN_YUAN", 0.2),
        (word_units * _env_float("POINTS_BOOK_PARSER_ANALYZE_PER_10K_YUAN", 0.08))
        + (normalized_chapter_count * _env_float("POINTS_BOOK_PARSER_ANALYZE_PER_CHAPTER_YUAN", 0.01)),
    )
    return _round_yuan(amount)


_VIDEO_BASIS_KINDS = frozenset({"video", "motion", "video_edit"})


class AssetStudioVideoPriceMissing(ValueError):
    """视频三链路按「模型 × 分辨率档」取不到官方每秒价。

    单一均价（旧 0.2 元/秒）在 30 秒 1080p 下欠收十几倍，缺价必须拒单而不是猜。
    """


def estimate_asset_studio_basis_yuan(
    *,
    kind: str,
    mode: str,
    model_id: str | None = None,
    duration_seconds: float | int | None = None,
    output_count: int = 1,
    prompt_chars: int | None = None,
    asset_type: str | None = None,
    width: int | None = None,
    height: int | None = None,
    audio_output: bool = True,
) -> float:
    normalized_kind = _safe_text(kind, "").lower()
    normalized_mode = _safe_text(mode, "").lower()
    normalized_output_count = max(_to_non_negative_int(output_count, 1), 1)
    duration = max(_to_non_negative_float(duration_seconds, 0.0), 0.0)

    if normalized_kind == "image":
        unit_price = (
            _env_float("POINTS_ASSET_STUDIO_IMAGE_EDIT_YUAN", 0.12)
            if normalized_mode == "reference_edit"
            else _env_float("POINTS_ASSET_STUDIO_IMAGE_GENERATE_YUAN", 0.08)
        )
        return _round_yuan(unit_price * normalized_output_count)

    if normalized_kind in _VIDEO_BASIS_KINDS:
        per_second = resolve_video_price_per_second(
            model_id=model_id,
            width=width,
            height=height,
            audio_output=audio_output,
        )
        if per_second is None:
            raise AssetStudioVideoPriceMissing(
                f"模型 {model_id or '未指定'} 在 {int(width or 0)}x{int(height or 0)} 对应的分辨率档"
                "缺少官方每秒价目，无法计算冻结额；请先补齐 config/models.yaml 的 pricing_info 后重试。"
            )
        return _round_yuan(max(duration, 1.0) * per_second * normalized_output_count)

    if normalized_kind == "audio":
        if normalized_mode == "text_to_speech":
            char_units = _ceil_units(_to_non_negative_int(prompt_chars), 100)
            return _round_yuan(
                max(
                    _env_float("POINTS_ASSET_STUDIO_SPEECH_MIN_YUAN", 0.05),
                    char_units * _env_float("POINTS_ASSET_STUDIO_SPEECH_PER_100_CHARS_YUAN", 0.02),
                )
            )
        per_second = (
            _env_float("POINTS_ASSET_STUDIO_SOUND_EFFECT_PER_SECOND_YUAN", 0.04)
            if normalized_mode == "text_to_sound_effect"
            else _env_float("POINTS_ASSET_STUDIO_MUSIC_PER_SECOND_YUAN", 0.03)
        )
        return _round_yuan(max(duration, 1.0) * per_second * normalized_output_count)

    if normalized_kind == "vision_review":
        normalized_asset_type = _safe_text(asset_type, "").lower()
        unit_price = (
            _env_float("POINTS_ASSET_STUDIO_VISION_VIDEO_YUAN", 0.12)
            if normalized_asset_type == "video"
            else _env_float("POINTS_ASSET_STUDIO_VISION_IMAGE_YUAN", 0.04)
        )
        return _round_yuan(unit_price * normalized_output_count)

    return _round_yuan(_env_float("POINTS_ASSET_STUDIO_DEFAULT_YUAN", 0.08))


def build_points_billing_metadata(precheck: PointsBillingPrecheckSnapshot) -> dict[str, object]:
    return {
        "points_billing_key": precheck.billing_key,
        "points_module_key": precheck.module_key,
        "points_module_label": precheck.module_label,
        "points_estimated_yuan": precheck.estimated_yuan,
        "points_estimated_points": precheck.estimated_points,
        "points_frozen_points": precheck.required_frozen_points,
    }
