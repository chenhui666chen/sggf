from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.admin_log import AdminOperationLog
from app.models.audiobook import AudiobookProject
from app.models.dreamweaver import DreamweaverProject
from app.models.project import Project
from app.models.user_asset_record import UserAssetRecord
from app.services.user_center_points import (
    UserCenterPointsBundleSnapshot,
    UserCenterPointsRuleSnapshot,
    build_user_center_points_bundle,
    get_user_center_points_rule_snapshot,
)
from app.services.user_center_points_events import list_user_points_billing_logs


@dataclass(frozen=True)
class UserPointsReadModelSnapshot:
    user_asset_rows: tuple[object, ...]
    audiobook_rows: tuple[object, ...]
    dreamweaver_rows: tuple[object, ...]
    manual_adjustment_logs: tuple[AdminOperationLog, ...]
    billing_event_logs: tuple[AdminOperationLog, ...]
    points_rule_snapshot: UserCenterPointsRuleSnapshot
    points_bundle: UserCenterPointsBundleSnapshot


def _list_user_asset_rows(*, db: Session, user_id: int) -> list[UserAssetRecord]:
    return (
        db.query(UserAssetRecord)
        .filter(UserAssetRecord.user_id == user_id)
        .order_by(UserAssetRecord.updated_at.desc(), UserAssetRecord.created_at.desc(), UserAssetRecord.id.desc())
        .all()
    )


def _list_user_audiobook_rows(*, db: Session, user_id: int) -> list[object]:
    return (
        db.query(
            AudiobookProject.id.label("id"),
            AudiobookProject.project_id.label("project_id"),
            Project.title.label("project_title"),
            AudiobookProject.status.label("status"),
            AudiobookProject.tts_provider.label("tts_provider"),
            AudiobookProject.total_chapters.label("total_chapters"),
            AudiobookProject.completed_chapters.label("completed_chapters"),
            AudiobookProject.total_cost.label("total_cost"),
            AudiobookProject.created_at.label("created_at"),
            AudiobookProject.updated_at.label("updated_at"),
        )
        .join(Project, Project.id == AudiobookProject.project_id)
        .filter(
            Project.user_id == user_id,
            AudiobookProject.deleted_at.is_(None),
        )
        .order_by(
            AudiobookProject.updated_at.desc(),
            AudiobookProject.created_at.desc(),
            AudiobookProject.id.desc(),
        )
        .all()
    )


def _list_user_dreamweaver_rows(*, db: Session, user_id: int) -> list[object]:
    return (
        db.query(
            DreamweaverProject.id.label("id"),
            DreamweaverProject.run_id.label("run_id"),
            DreamweaverProject.source_project_id.label("source_project_id"),
            Project.title.label("project_title"),
            DreamweaverProject.status.label("status"),
            DreamweaverProject.stage.label("stage"),
            DreamweaverProject.contract_json.label("contract_json"),
            DreamweaverProject.created_at.label("created_at"),
            DreamweaverProject.updated_at.label("updated_at"),
        )
        .join(Project, Project.id == DreamweaverProject.source_project_id)
        .filter(DreamweaverProject.user_id == user_id)
        .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc(), DreamweaverProject.id.desc())
        .all()
    )


def _list_manual_adjustment_logs(*, db: Session, user_id: int) -> list[AdminOperationLog]:
    return (
        db.query(AdminOperationLog)
        .filter(
            AdminOperationLog.operation_type == "POINTS_ADJUST",
            AdminOperationLog.resource_type == "USER_POINTS",
            AdminOperationLog.resource_id == user_id,
            AdminOperationLog.response_status < 400,
        )
        .order_by(AdminOperationLog.created_at.desc(), AdminOperationLog.id.desc())
        .all()
    )


def build_user_points_read_model(*, db: Session, user_id: int) -> UserPointsReadModelSnapshot:
    user_asset_rows = _list_user_asset_rows(db=db, user_id=user_id)
    audiobook_rows = _list_user_audiobook_rows(db=db, user_id=user_id)
    dreamweaver_rows = _list_user_dreamweaver_rows(db=db, user_id=user_id)
    manual_adjustment_logs = _list_manual_adjustment_logs(db=db, user_id=user_id)
    billing_event_logs = list_user_points_billing_logs(db=db, target_user_id=user_id)
    points_rule_snapshot = get_user_center_points_rule_snapshot(db=db)
    points_bundle = build_user_center_points_bundle(
        user_assets=user_asset_rows,
        audiobook_rows=audiobook_rows,
        dreamweaver_rows=dreamweaver_rows,
        manual_adjustment_logs=manual_adjustment_logs,
        billing_event_logs=billing_event_logs,
        config=points_rule_snapshot.config,
    )

    return UserPointsReadModelSnapshot(
        user_asset_rows=tuple(user_asset_rows),
        audiobook_rows=tuple(audiobook_rows),
        dreamweaver_rows=tuple(dreamweaver_rows),
        manual_adjustment_logs=tuple(manual_adjustment_logs),
        billing_event_logs=tuple(billing_event_logs),
        points_rule_snapshot=points_rule_snapshot,
        points_bundle=points_bundle,
    )
