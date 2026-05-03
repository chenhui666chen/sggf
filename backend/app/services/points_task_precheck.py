from __future__ import annotations

import os
from dataclasses import dataclass, fields, is_dataclass
from types import SimpleNamespace
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.project import Chapter
from app.schemas.dreamweaver_contract import DREAMWEAVER_SCHEMA_VERSION
from app.services.dreamweaver.persistence import build_contract_from_payload
from app.services.points_pricing_policy import (
    PointsBusinessSettlementSnapshot,
    build_points_business_settlement_snapshot,
    get_points_pricing_policy_snapshot,
)
from app.services.user_center_points import (
    RUNNING_STATUSES,
    UserCenterPointsAccountSnapshot,
    get_user_center_points_rule_snapshot,
)
from app.services.user_center_points_events import (
    POINTS_BILLING_MODULE_AUDIOBOOK,
    POINTS_BILLING_MODULE_DREAMWEAVER,
    build_audiobook_billing_key,
    get_active_points_billing_freeze_amount,
)
from app.services.user_center_task_billing import build_user_center_task_billing_overview
from app.services.user_points_read_model import build_user_points_read_model
from app.utils.datetime_utils import utc_now


@dataclass(frozen=True)
class AudiobookTaskPointsPrecheckSnapshot:
    allowed: bool
    failure_code: str | None
    failure_message: str | None
    estimated_yuan: float | None
    estimated_points: float | None
    required_frozen_points: float
    existing_frozen_points: float
    additional_frozen_points: float
    balance_points: float
    frozen_points: float
    available_points: float
    effective_available_points: float
    reclaimed_running_frozen_points: float
    operating_snapshot: PointsBusinessSettlementSnapshot | None


@dataclass(frozen=True)
class DreamweaverTaskPointsPrecheckSnapshot:
    allowed: bool
    failure_code: str | None
    failure_message: str | None
    estimated_shot_count: int
    estimated_yuan: float | None
    estimated_points: float | None
    required_frozen_points: float
    balance_points: float
    frozen_points: float
    available_points: float
    operating_snapshot: PointsBusinessSettlementSnapshot | None


def _serialize_task_points_precheck_value(value: object) -> object | None:
    if value is None:
        return None
    if hasattr(value, "to_payload") and callable(getattr(value, "to_payload")):
        return value.to_payload()
    if is_dataclass(value):
        payload: dict[str, object] = {}
        for field in fields(value):
            serialized = _serialize_task_points_precheck_value(getattr(value, field.name))
            if serialized is not None:
                payload[field.name] = serialized
        return payload
    return value


def build_task_points_precheck_error_detail(
    *,
    precheck: object,
    module_key: str,
    module_label: str,
    default_message: str,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "message": str(getattr(precheck, "failure_message", "") or "").strip() or default_message,
        "module_key": str(module_key or "").strip() or "unknown",
        "module_label": str(module_label or "").strip() or "未知模块",
        "allowed": False,
        "failure_code": str(getattr(precheck, "failure_code", "") or "").strip() or "points_precheck_failed",
    }
    if not is_dataclass(precheck):
        return detail

    for field in fields(precheck):
        if field.name in {"allowed", "failure_code", "failure_message"}:
            continue
        serialized = _serialize_task_points_precheck_value(getattr(precheck, field.name))
        if serialized is not None:
            detail[field.name] = serialized
    return detail


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _to_non_negative_int(value: object | None) -> int:
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(amount, 0)


def _list_project_chapter_rows(
    *,
    db: Session,
    project_id: int,
    chapter_ids: Sequence[int],
) -> list[object]:
    normalized_chapter_ids = [int(chapter_id) for chapter_id in chapter_ids if int(chapter_id or 0) > 0]
    if not normalized_chapter_ids:
        return []

    return (
        db.query(
            Chapter.project_id.label("project_id"),
            Chapter.word_count.label("word_count"),
            Chapter.content.label("content"),
        )
        .filter(
            Chapter.project_id == project_id,
            Chapter.id.in_(normalized_chapter_ids),
            Chapter.deleted_at.is_(None),
        )
        .all()
    )


def _estimate_dreamweaver_shot_count(*, chapter_rows: Sequence[object]) -> int:
    chapter_count = 0
    content_units = 0
    for row in chapter_rows:
        chapter_count += 1
        word_count = _to_non_negative_int(getattr(row, "word_count", 0))
        content = str(getattr(row, "content", "") or "")
        content_units += max(word_count, len(content))

    if chapter_count <= 0 and content_units <= 0:
        return 0

    chars_per_shot = max(_env_int("POINTS_TASK_PRECHECK_DREAMWEAVER_CHARS_PER_SHOT", 1500), 1)
    min_shots_per_chapter = max(_env_int("POINTS_TASK_PRECHECK_DREAMWEAVER_MIN_SHOTS_PER_CHAPTER", 3), 1)
    max_estimated_shots = max(_env_int("POINTS_TASK_PRECHECK_DREAMWEAVER_MAX_ESTIMATED_SHOTS", 80), 1)

    shots_from_content = (content_units + chars_per_shot - 1) // chars_per_shot if content_units > 0 else 0
    estimated_shot_count = max(chapter_count * min_shots_per_chapter, shots_from_content, 1)
    return min(estimated_shot_count, max_estimated_shots)


def _build_estimated_dreamweaver_storyboard(
    *,
    shot_count: int,
    frame_ratio: str,
) -> list[dict[str, object]]:
    storyboard: list[dict[str, object]] = []
    normalized_ratio = str(frame_ratio or "").strip()
    ratio_parts = normalized_ratio.split(":", 1)
    if len(ratio_parts) != 2 or not all(part.isdigit() and part for part in ratio_parts):
        normalized_ratio = "16:9"
    for index in range(max(int(shot_count or 0), 0)):
        shot_key = f"precheck-shot-{index + 1}"
        storyboard.append(
            {
                "shot_id": shot_key,
                "scene_id": f"scene-{index + 1}",
                "desc": "points precheck shot",
                "duration_s": 3.0,
                "head_frame": {
                    "prompt": "points precheck head frame",
                    "ratio": normalized_ratio,
                    "subject_pos": {"x": 0.5, "y": 0.5},
                },
                "tail_frame": {
                    "prompt": "points precheck tail frame",
                    "ratio": normalized_ratio,
                    "subject_pos": {"x": 0.5, "y": 0.5},
                },
            }
        )
    return storyboard


def _build_user_points_account_snapshot(
    *,
    db: Session,
    user_id: int,
) -> tuple[UserCenterPointsAccountSnapshot, list[object]]:
    read_model = build_user_points_read_model(db=db, user_id=user_id)
    return read_model.points_bundle.account, list(read_model.audiobook_rows)


def _resolve_reclaimable_running_frozen_points(
    *,
    audiobook_rows: Sequence[object],
    audiobook_project_id: int | None,
    active_formal_freeze_points: float,
    running_audiobook_frozen_points: float,
) -> float:
    if int(audiobook_project_id or 0) <= 0:
        return 0.0
    if active_formal_freeze_points > 0:
        return 0.0
    if running_audiobook_frozen_points <= 0:
        return 0.0

    target_row = next(
        (
            row
            for row in audiobook_rows
            if int(getattr(row, "id", 0) or 0) == int(audiobook_project_id or 0)
        ),
        None,
    )
    if target_row is None:
        return 0.0

    status = str(getattr(target_row, "status", "") or "").strip().lower()
    if status not in RUNNING_STATUSES:
        return 0.0

    return round(max(float(running_audiobook_frozen_points), 0.0), 2)


def _build_balance_failure_message(
    *,
    effective_available_points: float,
    additional_frozen_points: float,
    existing_frozen_points: float,
) -> str:
    message = (
        "当前可用积分不足，无法启动有声书任务。"
        f" 当前可用 {effective_available_points:.2f} 积分，"
        f"仍需额外冻结 {additional_frozen_points:.2f} 积分。"
    )
    if existing_frozen_points > 0:
        message += f" 该任务已有 {existing_frozen_points:.2f} 积分处于正式冻结状态。"
    return message


def _build_dreamweaver_balance_failure_message(
    *,
    available_points: float,
    required_frozen_points: float,
    estimated_shot_count: int,
) -> str:
    return (
        "当前可用积分不足，无法启动短剧任务。"
        f" 当前可用 {available_points:.2f} 积分，"
        f"本次按预估 {estimated_shot_count} 个镜头测算，需冻结 {required_frozen_points:.2f} 积分。"
    )


def build_audiobook_task_points_precheck(
    *,
    db: Session,
    user_id: int,
    project_id: int,
    project_title: str | None,
    chapter_ids: Sequence[int],
    tts_provider: str | None,
    audiobook_project_id: int | None = None,
) -> AudiobookTaskPointsPrecheckSnapshot:
    normalized_chapter_ids = [int(chapter_id) for chapter_id in chapter_ids if int(chapter_id or 0) > 0]
    chapter_rows = _list_project_chapter_rows(
        db=db,
        project_id=project_id,
        chapter_ids=normalized_chapter_ids,
    )
    selected_chapter_count = len(chapter_rows) if chapter_rows else len(normalized_chapter_ids)
    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)

    synthetic_row = SimpleNamespace(
        id=int(audiobook_project_id or 0),
        project_id=int(project_id or 0),
        project_title=project_title,
        status="pending",
        tts_provider=tts_provider,
        total_chapters=max(selected_chapter_count, 0),
        completed_chapters=0,
        total_cost=0.0,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[synthetic_row],
        dreamweaver_rows=[],
        chapter_rows=list(chapter_rows),
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return AudiobookTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message="当前无法估算本次有声书任务的积分消耗，请补全章节内容后重试。",
            estimated_yuan=None,
            estimated_points=None,
            required_frozen_points=0.0,
            existing_frozen_points=0.0,
            additional_frozen_points=0.0,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            effective_available_points=0.0,
            reclaimed_running_frozen_points=0.0,
            operating_snapshot=None,
        )

    item = task_billing.items[0]
    estimated_yuan = round(float(item.estimated_yuan or 0.0), 2)
    estimated_points = round(float(item.estimated_points or 0.0), 2) if item.estimated_points is not None else None
    required_frozen_points = round(float(item.suggested_frozen_points or 0.0), 2)
    if estimated_yuan <= 0 or required_frozen_points <= 0:
        return AudiobookTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message="当前无法估算本次有声书任务的积分消耗，请补全章节内容后重试。",
            estimated_yuan=estimated_yuan if estimated_yuan > 0 else None,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            existing_frozen_points=0.0,
            additional_frozen_points=0.0,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            effective_available_points=0.0,
            reclaimed_running_frozen_points=0.0,
            operating_snapshot=None,
        )

    operating_snapshot = build_points_business_settlement_snapshot(
        pricing_config=pricing_snapshot.config,
        module_key=POINTS_BILLING_MODULE_AUDIOBOOK,
        basis_yuan=estimated_yuan,
        provider_key=str(tts_provider or "").strip() or None,
    )
    if operating_snapshot.negative_margin_blocked:
        return AudiobookTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="negative_margin_blocked",
            failure_message=(
                "当前积分定价策略会导致本次有声书任务预估毛利为负，系统已阻止启动。"
                f" 预计成本 ￥{estimated_yuan:.2f}，预计冻结 {required_frozen_points:.2f} 积分。"
            ),
            estimated_yuan=estimated_yuan,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            existing_frozen_points=0.0,
            additional_frozen_points=required_frozen_points,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            effective_available_points=0.0,
            reclaimed_running_frozen_points=0.0,
            operating_snapshot=operating_snapshot,
        )

    account_snapshot, audiobook_rows = _build_user_points_account_snapshot(db=db, user_id=user_id)
    balance_points = round(float(account_snapshot.balance), 2)
    frozen_points = round(float(account_snapshot.frozen), 2)
    available_points = round(balance_points - frozen_points, 2)

    existing_frozen_points = 0.0
    if int(audiobook_project_id or 0) > 0:
        existing_frozen_points = get_active_points_billing_freeze_amount(
            db=db,
            target_user_id=user_id,
            billing_key=build_audiobook_billing_key(int(audiobook_project_id or 0)),
        )

    running_rule_snapshot = get_user_center_points_rule_snapshot(db=db)
    reclaimed_running_frozen_points = _resolve_reclaimable_running_frozen_points(
        audiobook_rows=audiobook_rows,
        audiobook_project_id=audiobook_project_id,
        active_formal_freeze_points=existing_frozen_points,
        running_audiobook_frozen_points=float(running_rule_snapshot.config.running_audiobook_frozen),
    )
    effective_available_points = round(available_points + reclaimed_running_frozen_points, 2)
    additional_frozen_points = round(max(required_frozen_points - existing_frozen_points, 0.0), 2)

    if effective_available_points + 1e-6 < additional_frozen_points:
        return AudiobookTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="insufficient_available_points",
            failure_message=_build_balance_failure_message(
                effective_available_points=effective_available_points,
                additional_frozen_points=additional_frozen_points,
                existing_frozen_points=existing_frozen_points,
            ),
            estimated_yuan=estimated_yuan,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            existing_frozen_points=existing_frozen_points,
            additional_frozen_points=additional_frozen_points,
            balance_points=balance_points,
            frozen_points=frozen_points,
            available_points=available_points,
            effective_available_points=effective_available_points,
            reclaimed_running_frozen_points=reclaimed_running_frozen_points,
            operating_snapshot=operating_snapshot,
        )

    return AudiobookTaskPointsPrecheckSnapshot(
        allowed=True,
        failure_code=None,
        failure_message=None,
        estimated_yuan=estimated_yuan,
        estimated_points=estimated_points,
        required_frozen_points=required_frozen_points,
        existing_frozen_points=existing_frozen_points,
        additional_frozen_points=additional_frozen_points,
        balance_points=balance_points,
        frozen_points=frozen_points,
        available_points=available_points,
        effective_available_points=effective_available_points,
        reclaimed_running_frozen_points=reclaimed_running_frozen_points,
        operating_snapshot=operating_snapshot,
    )


def build_dreamweaver_task_points_precheck(
    *,
    db: Session,
    user_id: int,
    project_id: int,
    project_title: str | None,
    chapter_rows: Sequence[object],
    chapter_ids: Sequence[int],
    runtime_config: dict[str, object] | None = None,
    schema_version: str = DREAMWEAVER_SCHEMA_VERSION,
) -> DreamweaverTaskPointsPrecheckSnapshot:
    estimated_shot_count = _estimate_dreamweaver_shot_count(chapter_rows=chapter_rows)
    if estimated_shot_count <= 0:
        return DreamweaverTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message="当前无法估算本次短剧任务的积分消耗，请补全章节内容后重试。",
            estimated_shot_count=0,
            estimated_yuan=None,
            estimated_points=None,
            required_frozen_points=0.0,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=None,
        )

    image_config = runtime_config.get("image_config") if isinstance(runtime_config, dict) else None
    frame_ratio = str(image_config.get("ratio") or "").strip() if isinstance(image_config, dict) else ""

    synthetic_payload: dict[str, object] = {
        "chapter_ids": [int(chapter_id) for chapter_id in chapter_ids if int(chapter_id or 0) > 0],
        "storyboard": _build_estimated_dreamweaver_storyboard(
            shot_count=estimated_shot_count,
            frame_ratio=frame_ratio,
        ),
    }
    if runtime_config:
        synthetic_payload.update(runtime_config)

    contract = build_contract_from_payload(
        run_id="dreamweaver-precheck",
        source_project_id=int(project_id or 0),
        user_id=int(user_id or 0),
        payload=synthetic_payload,
        schema_version=str(schema_version or DREAMWEAVER_SCHEMA_VERSION),
    )
    pricing_snapshot = get_points_pricing_policy_snapshot(db=db)
    synthetic_row = SimpleNamespace(
        id=0,
        run_id="dreamweaver-precheck",
        source_project_id=int(project_id or 0),
        project_title=project_title,
        status="running",
        stage="precheck",
        contract_json=contract.model_dump(mode="json"),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    task_billing = build_user_center_task_billing_overview(
        audiobook_rows=[],
        dreamweaver_rows=[synthetic_row],
        chapter_rows=[],
        pricing_config=pricing_snapshot.config,
    )
    if not task_billing.items:
        return DreamweaverTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message="当前无法估算本次短剧任务的积分消耗，请补全章节内容后重试。",
            estimated_shot_count=estimated_shot_count,
            estimated_yuan=None,
            estimated_points=None,
            required_frozen_points=0.0,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=None,
        )

    item = task_billing.items[0]
    estimated_yuan = round(float(item.estimated_yuan or 0.0), 2)
    estimated_points = round(float(item.estimated_points or 0.0), 2) if item.estimated_points is not None else None
    required_frozen_points = round(float(item.suggested_frozen_points or 0.0), 2)
    if estimated_yuan <= 0 or required_frozen_points <= 0:
        return DreamweaverTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="estimate_unavailable",
            failure_message="当前无法估算本次短剧任务的积分消耗，请补全章节内容后重试。",
            estimated_shot_count=estimated_shot_count,
            estimated_yuan=estimated_yuan if estimated_yuan > 0 else None,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=None,
        )

    operating_snapshot = build_points_business_settlement_snapshot(
        pricing_config=pricing_snapshot.config,
        module_key=POINTS_BILLING_MODULE_DREAMWEAVER,
        basis_yuan=estimated_yuan,
        provider_key=None,
    )
    if operating_snapshot.negative_margin_blocked:
        return DreamweaverTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="negative_margin_blocked",
            failure_message=(
                "当前积分定价策略会导致本次短剧任务预估毛利为负，系统已阻止启动。"
                f" 本次按预估 {estimated_shot_count} 个镜头测算，预计成本 ￥{estimated_yuan:.2f}，"
                f"预计冻结 {required_frozen_points:.2f} 积分。"
            ),
            estimated_shot_count=estimated_shot_count,
            estimated_yuan=estimated_yuan,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            balance_points=0.0,
            frozen_points=0.0,
            available_points=0.0,
            operating_snapshot=operating_snapshot,
        )

    account_snapshot, _audiobook_rows = _build_user_points_account_snapshot(db=db, user_id=user_id)
    balance_points = round(float(account_snapshot.balance), 2)
    frozen_points = round(float(account_snapshot.frozen), 2)
    available_points = round(balance_points - frozen_points, 2)

    if available_points + 1e-6 < required_frozen_points:
        return DreamweaverTaskPointsPrecheckSnapshot(
            allowed=False,
            failure_code="insufficient_available_points",
            failure_message=_build_dreamweaver_balance_failure_message(
                available_points=available_points,
                required_frozen_points=required_frozen_points,
                estimated_shot_count=estimated_shot_count,
            ),
            estimated_shot_count=estimated_shot_count,
            estimated_yuan=estimated_yuan,
            estimated_points=estimated_points,
            required_frozen_points=required_frozen_points,
            balance_points=balance_points,
            frozen_points=frozen_points,
            available_points=available_points,
            operating_snapshot=operating_snapshot,
        )

    return DreamweaverTaskPointsPrecheckSnapshot(
        allowed=True,
        failure_code=None,
        failure_message=None,
        estimated_shot_count=estimated_shot_count,
        estimated_yuan=estimated_yuan,
        estimated_points=estimated_points,
        required_frozen_points=required_frozen_points,
        balance_points=balance_points,
        frozen_points=frozen_points,
        available_points=available_points,
        operating_snapshot=operating_snapshot,
    )
