"""公共音色池发布、检索、审核与评分仓储。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.voice_pool_publication import VoicePoolPublication
from app.models.voice_pool_rating import VoicePoolRating
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.schemas.voice_pool import VoicePoolPublicationCreate
from app.services.audiobook.voice_pool_state import (
    VOICE_POOL_STATUS_TRANSITIONS,
    validate_voice_pool_status_transition,
)


LOW_RATING_SCORE_MAX = 2
AUTO_UNPUBLISH_MIN_RATINGS = 10
AUTO_UNPUBLISH_MIN_LOW_RATINGS = 8
AUTO_UNPUBLISH_LOW_RATIO = 0.8
AUTO_UNPUBLISH_MAX_AVERAGE = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_publication(db: Session, publication_id: str) -> VoicePoolPublication:
    publication = (
        db.query(VoicePoolPublication)
        .filter(VoicePoolPublication.publication_id == publication_id)
        .first()
    )
    if publication is None:
        raise LookupError("voice pool publication not found")
    return publication


def _build_publication_id(asset: VoiceReferenceAsset) -> str:
    digest = hashlib.sha256(
        f"{asset.asset_id}|{asset.owner_user_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"vp_{digest}"


def create_voice_pool_publication(
    db: Session,
    *,
    source_asset_id: str,
    owner_user_id: int,
    payload: VoicePoolPublicationCreate,
) -> VoicePoolPublication:
    """为当前用户的有效私有音色创建待审核公共发布。"""
    asset = (
        db.query(VoiceReferenceAsset)
        .filter(VoiceReferenceAsset.asset_id == source_asset_id)
        .first()
    )
    if asset is None:
        raise LookupError("voice reference asset not found")
    if asset.owner_user_id != owner_user_id:
        raise PermissionError("cannot publish another user's voice asset")
    if asset.revoked_at is not None or asset.deleted_at is not None:
        raise ValueError("revoked or deleted voice asset cannot be published")
    if not asset.authorized_at or not asset.authorization_version:
        raise ValueError("voice asset authorization is incomplete")
    if asset.authorization_basis != payload.rights_basis:
        raise ValueError("publication rights_basis must match the source asset")

    publication_id = _build_publication_id(asset)
    existing = (
        db.query(VoicePoolPublication)
        .filter(VoicePoolPublication.source_asset_id == asset.id)
        .first()
    )
    if existing is not None:
        return existing

    voice_origin = (
        "designed" if payload.rights_basis == "synthetic_design" else "cloned"
    )
    publication = VoicePoolPublication(
        publication_id=publication_id,
        source_asset_id=asset.id,
        owner_user_id=owner_user_id,
        display_name=payload.display_name,
        description=payload.description or None,
        voice_origin=voice_origin,
        source_model=asset.source_model,
        gender_presentation=payload.gender_presentation,
        age_impression=payload.age_impression,
        primary_style=payload.primary_style,
        language=payload.language,
        accent=payload.accent or None,
        timbre_tags=list(payload.timbre_tags),
        scenario_tags=list(payload.scenario_tags),
        emotion_tags=list(payload.emotion_tags),
        rights_basis=payload.rights_basis,
        license_version=payload.license_version,
        consent_at=payload.consent_at,
        public_preview_uri=payload.public_preview_uri,
        public_reference_uri=payload.public_reference_uri,
        status="pending_review",
        metadata_json={
            "source_asset_id": asset.asset_id,
            "source_authorization_version": asset.authorization_version,
        },
    )
    db.add(publication)
    db.flush()
    return publication


def list_public_voice_pool(
    db: Session,
    *,
    gender_presentation: str | None = None,
    age_impression: str | None = None,
    primary_style: str | None = None,
    language: str | None = None,
    limit: int | None = None,
    before_publication_id: str | None = None,
) -> list[VoicePoolPublication]:
    """只返回审核通过且未撤回、未被社区下架的公共音色。"""
    query = db.query(VoicePoolPublication).filter(
        VoicePoolPublication.status == "published"
    )
    filters = {
        VoicePoolPublication.gender_presentation: gender_presentation,
        VoicePoolPublication.age_impression: age_impression,
        VoicePoolPublication.primary_style: primary_style,
        VoicePoolPublication.language: language,
    }
    for column, value in filters.items():
        if value:
            query = query.filter(column == value)
    if before_publication_id:
        cursor = (
            db.query(VoicePoolPublication.published_at, VoicePoolPublication.id)
            .filter(VoicePoolPublication.publication_id == before_publication_id)
            .first()
        )
        if cursor is not None:
            published_at, row_id = cursor
            query = query.filter(
                (VoicePoolPublication.published_at < published_at)
                | (
                    (VoicePoolPublication.published_at == published_at)
                    & (VoicePoolPublication.id < row_id)
                )
            )
    query = query.order_by(
        VoicePoolPublication.published_at.desc(), VoicePoolPublication.id.desc()
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def get_voice_pool_rating_summaries(
    db: Session,
    publications: list[VoicePoolPublication],
) -> dict[int, dict[str, int | float]]:
    """一次聚合当前页评分，避免逐条查询造成 N+1。"""
    if not publications:
        return {}
    rows = (
        db.query(
            VoicePoolRating.publication_id,
            func.count(VoicePoolRating.id),
            func.avg(VoicePoolRating.score),
        )
        .filter(VoicePoolRating.publication_id.in_([item.id for item in publications]))
        .group_by(VoicePoolRating.publication_id)
        .all()
    )
    return {
        int(publication_id): {
            "rating_count": int(total or 0),
            "average_score": float(average or 0.0),
        }
        for publication_id, total, average in rows
    }


def get_voice_pool_rating_summary(
    db: Session,
    publication: VoicePoolPublication,
) -> dict[str, int | float]:
    total, average = (
        db.query(
            func.count(VoicePoolRating.id),
            func.avg(VoicePoolRating.score),
        )
        .filter(VoicePoolRating.publication_id == publication.id)
        .one()
    )
    return {
        "rating_count": int(total or 0),
        "average_score": float(average or 0.0),
    }


def review_voice_pool_publication(
    db: Session,
    *,
    publication_id: str,
    reviewer_user_id: int,
    approved: bool,
    review_note: str = "",
) -> VoicePoolPublication:
    """审核待审公共发布，并拒绝并发覆盖。"""
    publication = _get_publication(db, publication_id)
    current_status = publication.status
    target_status = "published" if approved else "rejected"
    if current_status != "pending_review":
        raise ValueError(
            "invalid voice pool status transition: "
            f"{current_status} -> {target_status}"
        )
    validate_voice_pool_status_transition(current_status, target_status)

    reviewed_at = _now()
    updated_count = (
        db.query(VoicePoolPublication)
        .filter(
            VoicePoolPublication.id == publication.id,
            VoicePoolPublication.status == current_status,
        )
        .update(
            {
                VoicePoolPublication.status: target_status,
                VoicePoolPublication.reviewed_by_user_id: reviewer_user_id,
                VoicePoolPublication.reviewed_at: reviewed_at,
                VoicePoolPublication.review_note: review_note.strip() or None,
                VoicePoolPublication.published_at: reviewed_at if approved else None,
            },
            synchronize_session=False,
        )
    )
    if updated_count != 1:
        db.expire(publication)
        raise ValueError("concurrent review conflict")
    db.flush()
    db.refresh(publication)
    return publication


def withdraw_voice_pool_publication(
    db: Session,
    *,
    publication_id: str,
    owner_user_id: int,
) -> VoicePoolPublication:
    """所有者幂等撤回公共音色，保留历史发布和评分记录。"""
    publication = _get_publication(db, publication_id)
    if publication.owner_user_id != owner_user_id:
        raise PermissionError("cannot withdraw another user's publication")
    if publication.status == "withdrawn":
        return publication
    validate_voice_pool_status_transition(publication.status, "withdrawn")
    publication.status = "withdrawn"
    publication.withdrawn_at = _now()
    db.flush()
    return publication


def submit_voice_pool_rating(
    db: Session,
    *,
    publication_id: str,
    user_id: int,
    score: int,
) -> dict[str, int | float | bool | str]:
    """幂等提交评分，并按稳定阈值自动下架持续低质音色。"""
    if not 1 <= score <= 5:
        raise ValueError("score must be between 1 and 5")
    publication = _get_publication(db, publication_id)
    if publication.status != "published":
        raise ValueError("only a published voice can be rated")
    if publication.owner_user_id == user_id:
        raise PermissionError("cannot rate your own publication")

    rating = (
        db.query(VoicePoolRating)
        .filter(
            VoicePoolRating.publication_id == publication.id,
            VoicePoolRating.user_id == user_id,
        )
        .first()
    )
    if rating is None:
        rating = VoicePoolRating(
            publication_id=publication.id,
            user_id=user_id,
            score=score,
        )
        db.add(rating)
    else:
        rating.score = score
    db.flush()

    total, low_count, average = (
        db.query(
            func.count(VoicePoolRating.id),
            func.sum(
                case((VoicePoolRating.score <= LOW_RATING_SCORE_MAX, 1), else_=0)
            ),
            func.avg(VoicePoolRating.score),
        )
        .filter(VoicePoolRating.publication_id == publication.id)
        .one()
    )
    total_count = int(total or 0)
    low_rating_count = int(low_count or 0)
    average_score = float(average or 0.0)
    low_ratio = low_rating_count / total_count if total_count else 0.0
    auto_unpublished = (
        publication.status == "published"
        and total_count >= AUTO_UNPUBLISH_MIN_RATINGS
        and low_rating_count >= AUTO_UNPUBLISH_MIN_LOW_RATINGS
        and low_ratio >= AUTO_UNPUBLISH_LOW_RATIO
        and average_score <= AUTO_UNPUBLISH_MAX_AVERAGE
    )
    if auto_unpublished:
        validate_voice_pool_status_transition(
            publication.status,
            "community_rejected",
        )
        publication.status = "community_rejected"
        publication.review_note = "用户低分达到自动下架阈值"
        db.flush()

    return {
        "publication_id": publication.publication_id,
        "rating_count": total_count,
        "low_rating_count": low_rating_count,
        "low_rating_ratio": low_ratio,
        "average_score": average_score,
        "auto_unpublished": auto_unpublished,
    }


__all__ = [
    "VOICE_POOL_STATUS_TRANSITIONS",
    "create_voice_pool_publication",
    "list_public_voice_pool",
    "get_voice_pool_rating_summaries",
    "get_voice_pool_rating_summary",
    "review_voice_pool_publication",
    "submit_voice_pool_rating",
    "withdraw_voice_pool_publication",
]
