"""有声书公共音色池 API。

公共池只承载用户主动发布的衍生参考音频。原始复刻录音、供应商账号级音色
和未审核条目不会通过公共检索接口暴露。
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.audiobook_api import router
from app.core.permissions import require_admin
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.voice_pool_publication import VoicePoolPublication
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.schemas.voice_pool import (
    VOICE_POOL_AGE_OPTIONS,
    VOICE_POOL_EMOTION_OPTIONS,
    VOICE_POOL_GENDER_OPTIONS,
    VOICE_POOL_SCENARIO_OPTIONS,
    VOICE_POOL_STYLE_OPTIONS,
    VOICE_POOL_TIMBRE_OPTIONS,
    VoicePoolPublicationCreate,
    VoicePoolRatingRequest,
    VoicePoolReviewRequest,
)
from app.services.audiobook.voice_pool_repository import (
    create_voice_pool_publication,
    get_voice_pool_rating_summary,
    get_voice_pool_rating_summaries,
    list_public_voice_pool,
    review_voice_pool_publication,
    submit_voice_pool_rating,
    withdraw_voice_pool_publication,
)
from app.services.audiobook.voice_reference_asset_repository import (
    get_active_voice_reference_asset,
    revoke_voice_reference_asset,
    voice_reference_asset_to_record,
)


def _publication_record(
    db: Session,
    publication: VoicePoolPublication,
    *,
    include_owner_fields: bool = False,
    rating_summary: dict[str, int | float] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "publication_id": publication.publication_id,
        "display_name": publication.display_name,
        "description": publication.description or "",
        "voice_origin": publication.voice_origin,
        "source_model": publication.source_model,
        "gender_presentation": publication.gender_presentation,
        "age_impression": publication.age_impression,
        "primary_style": publication.primary_style,
        "language": publication.language,
        "accent": publication.accent or "",
        "timbre_tags": list(publication.timbre_tags or []),
        "scenario_tags": list(publication.scenario_tags or []),
        "emotion_tags": list(publication.emotion_tags or []),
        "public_preview_uri": publication.public_preview_uri,
        "reference_audio_url": publication.public_reference_uri,
        "status": publication.status,
        **(rating_summary or get_voice_pool_rating_summary(db, publication)),
    }
    if include_owner_fields:
        record.update(
            {
                "owner_user_id": publication.owner_user_id,
                "source_asset_id": publication.source_asset_id,
                "rights_basis": publication.rights_basis,
                "license_version": publication.license_version,
                "consent_at": publication.consent_at.isoformat()
                if publication.consent_at
                else None,
                "review_note": publication.review_note or "",
            }
        )
    return record


@router.get("/voice-pool/taxonomy")
async def get_voice_pool_taxonomy() -> dict[str, Any]:
    return {
        "gender_presentation": list(VOICE_POOL_GENDER_OPTIONS),
        "age_impression": list(VOICE_POOL_AGE_OPTIONS),
        "primary_style": list(VOICE_POOL_STYLE_OPTIONS),
        "timbre_tags": list(VOICE_POOL_TIMBRE_OPTIONS),
        "scenario_tags": list(VOICE_POOL_SCENARIO_OPTIONS),
        "emotion_tags": list(VOICE_POOL_EMOTION_OPTIONS),
        "rights_basis": ["self_voice", "licensed_voice", "synthetic_source", "synthetic_design"],
        "license_version": "voice-pool-license-v1",
    }


@router.get("/voice-pool/mine")
async def list_my_voice_pool_assets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    assets = (
        db.query(VoiceReferenceAsset)
        .filter(
            VoiceReferenceAsset.owner_user_id == int(current_user.id),
            VoiceReferenceAsset.revoked_at.is_(None),
            VoiceReferenceAsset.deleted_at.is_(None),
        )
        .order_by(VoiceReferenceAsset.updated_at.desc(), VoiceReferenceAsset.id.desc())
        .all()
    )
    return {
        "assets": [voice_reference_asset_to_record(asset) for asset in assets],
        "total": len(assets),
    }


@router.post("/voice-pool/publications", status_code=status.HTTP_201_CREATED)
async def publish_voice_to_pool(
    source_asset_id: str = Query(..., min_length=1),
    payload: VoicePoolPublicationCreate = ...,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        source_asset = get_active_voice_reference_asset(
            db,
            asset_id=source_asset_id,
            owner_user_id=int(current_user.id),
        )
        if source_asset is None:
            raise PermissionError("voice reference asset is unavailable or not owned by current user")
        if str((source_asset.metadata_json or {}).get("preview_schema_version") or "") != "voice-reference-preview-v1":
            raise ValueError("请先生成标准衍生试听，原始复刻录音不能直接发布")
        if source_asset.authorization_basis == "synthetic_design":
            if payload.rights_basis != "synthetic_design":
                raise ValueError("设计音色的权利依据必须为 synthetic_design")
        elif payload.rights_basis == "synthetic_design":
            raise ValueError("复刻音色不能声明为 synthetic_design")
        else:
            source_asset.authorization_basis = payload.rights_basis
        public_uri = str(source_asset.source_url or source_asset.storage_uri or "").strip()
        if not public_uri.startswith(("http://", "https://")):
            raise ValueError("标准衍生试听尚未上传 OSS，不能发布到公共音色池")
        trusted_payload = payload.model_copy(
            update={
                "public_preview_uri": public_uri,
                "public_reference_uri": public_uri,
            }
        )
        publication = create_voice_pool_publication(
            db,
            source_asset_id=source_asset_id,
            owner_user_id=int(current_user.id),
            payload=trusted_payload,
        )
        db.commit()
        return {"publication": _publication_record(db, publication, include_owner_fields=True)}
    except (LookupError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/voice-pool/public")
async def discover_public_voice_pool(
    gender_presentation: str | None = None,
    age_impression: str | None = None,
    primary_style: str | None = None,
    language: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    publications = list_public_voice_pool(
        db,
        gender_presentation=gender_presentation,
        age_impression=age_impression,
        primary_style=primary_style,
        language=language,
        limit=limit + 1,
        before_publication_id=cursor,
    )
    has_more = len(publications) > limit
    page = publications[:limit]
    summaries = get_voice_pool_rating_summaries(db, page)
    return {
        "voices": [
            _publication_record(
                db,
                publication,
                rating_summary=summaries.get(
                    publication.id,
                    {"rating_count": 0, "average_score": 0.0},
                ),
            )
            for publication in page
        ],
        "total": len(page),
        "next_cursor": page[-1].publication_id if has_more and page else None,
    }


@router.post("/voice-pool/publications/{publication_id}/review")
async def review_public_voice_pool_publication(
    publication_id: str,
    payload: VoicePoolReviewRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        publication = review_voice_pool_publication(
            db,
            publication_id=publication_id,
            reviewer_user_id=int(current_user.id),
            approved=payload.approved,
            review_note=payload.review_note,
        )
        db.commit()
        return {"publication": _publication_record(db, publication, include_owner_fields=True)}
    except (LookupError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/voice-pool/publications/{publication_id}/withdraw")
async def withdraw_public_voice_pool_publication(
    publication_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        publication = withdraw_voice_pool_publication(
            db,
            publication_id=publication_id,
            owner_user_id=int(current_user.id),
        )
        db.commit()
        return {"publication": _publication_record(db, publication, include_owner_fields=True)}
    except (LookupError, PermissionError) as exc:
        db.rollback()
        code = status.HTTP_403_FORBIDDEN if isinstance(exc, PermissionError) else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/voice-pool/publications/{publication_id}/rating")
async def rate_public_voice_pool_publication(
    publication_id: str,
    payload: VoicePoolRatingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        summary = submit_voice_pool_rating(
            db,
            publication_id=publication_id,
            user_id=int(current_user.id),
            score=payload.score,
        )
        db.commit()
        return summary
    except (LookupError, PermissionError, ValueError) as exc:
        db.rollback()
        code = status.HTTP_403_FORBIDDEN if isinstance(exc, PermissionError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/voice-pool/assets/{asset_id}/revoke")
async def revoke_my_voice_reference_asset(
    asset_id: str,
    reason: str = "用户撤回声音授权",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    asset = get_active_voice_reference_asset(
        db,
        asset_id=asset_id,
        owner_user_id=int(current_user.id),
    )
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="音色不存在或已撤销")
    revoked = revoke_voice_reference_asset(
        db,
        asset_id=asset_id,
        owner_user_id=int(current_user.id),
        revoked_by_user_id=int(current_user.id),
        reason=reason,
    )
    db.commit()
    return {"revoked": True, "asset": voice_reference_asset_to_record(revoked)}


__all__ = ["router"]
