"""Independent Seed Audio scene test routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import Depends, HTTPException, status

from app.api.v1.audiobook_api import router
from app.core.security import get_current_user
from app.core.permissions import require_admin
from app.core.env_loader import get_backend_root
from app.models.user import User
from app.schemas.audiobook import (
    SeedSceneTestPreviewRequest,
    SeedSceneTestPreviewResponse,
    SeedSceneBlindAudioResponse,
    SeedSceneBlindBatchCreateRequest,
    SeedSceneBlindBatchResponse,
    SeedSceneBlindReviewRecordResponse,
    SeedSceneBlindReviewSubmitRequest,
    SeedSceneBlindReviewSummaryResponse,
)
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceMaterializationError,
)
from app.services.audiobook.seed_scene_test_renderer import (
    SeedSceneTestRenderError,
    create_seed_scene_test_preview_service,
)
from app.services.audiobook.seed_scene_test_unit import build_seed_scene_test_catalog
from app.services.audiobook.seed_scene_blind_review import SeedSceneBlindReviewService


logger = logging.getLogger(__name__)


def _blind_review_service() -> SeedSceneBlindReviewService:
    return SeedSceneBlindReviewService(
        output_root=get_backend_root() / "data" / "seed_scene_tests"
    )


@router.get("/scene-audio/test-cases")
async def list_seed_scene_test_cases(
    current_user: User = Depends(get_current_user),
):
    return {"cases": build_seed_scene_test_catalog()}


@router.post(
    "/scene-audio/test-preview",
    response_model=SeedSceneTestPreviewResponse,
)
async def preview_seed_scene_test_case(
    request: SeedSceneTestPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    service = create_seed_scene_test_preview_service()
    references = tuple(reference.model_dump() for reference in request.references)
    try:
        payload = await asyncio.to_thread(
            service.render,
            case_id=request.case_id,
            variant_id=request.variant,
            sample_index=request.sample_index,
            references=references,
            force_regenerate=request.force_regenerate,
        )
    except (ValueError, PreviewReferenceMaterializationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SeedSceneTestRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "retryable": exc.retryable},
        ) from exc
    except Exception as exc:
        logger.exception(
            "独立 Seed Audio 场景测试失败: case=%s variant=%s",
            request.case_id,
            request.variant,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Seed Audio 场景测试暂时不可用", "retryable": True},
        ) from exc
    return SeedSceneTestPreviewResponse(**payload)


@router.post(
    "/scene-audio/blind-review/batches",
    response_model=SeedSceneBlindBatchResponse,
)
async def create_seed_scene_blind_review_batch(
    request: SeedSceneBlindBatchCreateRequest,
    current_user: User = Depends(require_admin),
):
    try:
        return _blind_review_service().create_batch(
            samples=tuple(item.model_dump() for item in request.samples)
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/scene-audio/blind-review/batches/{batch_id}",
    response_model=SeedSceneBlindBatchResponse,
)
async def get_seed_scene_blind_review_batch(
    batch_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return _blind_review_service().get_reviewer_manifest(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/scene-audio/blind-review/batches/{batch_id}/samples/{anonymous_id}/audio",
    response_model=SeedSceneBlindAudioResponse,
)
async def get_seed_scene_blind_review_audio(
    batch_id: str,
    anonymous_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return _blind_review_service().get_blind_audio(batch_id, anonymous_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/scene-audio/blind-review/batches/{batch_id}/answer-key")
async def get_seed_scene_blind_review_answer_key(
    batch_id: str,
    current_user: User = Depends(require_admin),
):
    try:
        return _blind_review_service().get_answer_key(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/scene-audio/blind-review/batches/{batch_id}/samples/{anonymous_id}/review",
    response_model=SeedSceneBlindReviewRecordResponse,
)
async def submit_seed_scene_blind_review(
    batch_id: str,
    anonymous_id: str,
    request: SeedSceneBlindReviewSubmitRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return _blind_review_service().submit_review(
            batch_id,
            anonymous_id,
            reviewer_user_id=int(current_user.id),
            review=request.model_dump(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/scene-audio/blind-review/batches/{batch_id}/samples/{anonymous_id}/review",
    response_model=SeedSceneBlindReviewRecordResponse,
)
async def get_my_seed_scene_blind_review(
    batch_id: str,
    anonymous_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        return _blind_review_service().get_review(
            batch_id,
            anonymous_id,
            reviewer_user_id=int(current_user.id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/scene-audio/blind-review/batches/{batch_id}/summary",
    response_model=SeedSceneBlindReviewSummaryResponse,
)
async def get_seed_scene_blind_review_summary(
    batch_id: str,
    current_user: User = Depends(require_admin),
):
    try:
        return _blind_review_service().get_review_summary(
            batch_id,
            reveal_identity=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
