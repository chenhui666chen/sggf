# -*- coding: utf-8 -*-
"""
Generation Feedback API - User ratings, QC results, and model profile updates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.feedback_loop import get_feedback_loop_service

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


class UserRatingRequest(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=120)
    task_type: str = Field(..., min_length=1, max_length=50)
    rating: float = Field(..., ge=1.0, le=5.0, description="用户评分 1-5")
    comment: Optional[str] = Field(default=None, max_length=2000)
    prompt_text: Optional[str] = Field(default=None, max_length=10000)
    output_urls: Optional[List[str]] = Field(default=None)
    project_id: Optional[int] = None


class QCResultRequest(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=120)
    task_type: str = Field(..., min_length=1, max_length=50)
    qc_passed: bool
    qc_score: float = Field(..., ge=0.0, le=1.0, description="QC综合得分 0-1")
    qc_details: Optional[Dict[str, Any]] = Field(default=None)
    style_match_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    prompt_adherence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    visual_quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    character_consistency_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    motion_stability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    generation_latency: Optional[float] = Field(default=None, ge=0.0)
    generation_cost: Optional[float] = Field(default=None, ge=0.0)
    prompt_text: Optional[str] = Field(default=None, max_length=10000)
    output_urls: Optional[List[str]] = Field(default=None)
    project_id: Optional[int] = None


class ApplyFeedbackRequest(BaseModel):
    min_samples: int = Field(default=5, ge=1, description="最少反馈样本数")
    days: int = Field(default=30, ge=1, description="统计天数范围")
    user_rating_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    qc_weight: float = Field(default=0.7, ge=0.0, le=1.0)


class FeedbackResponse(BaseModel):
    success: bool
    feedback_id: Optional[int] = None
    error: Optional[str] = None


class ModelStatsResponse(BaseModel):
    success: bool
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ApplyFeedbackResponse(BaseModel):
    success: bool
    updated_models: int = 0
    total_feedback_processed: int = 0
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/user-rating", response_model=FeedbackResponse)
async def submit_user_rating(
    request: UserRatingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = get_feedback_loop_service()

    try:
        feedback = service.submit_user_rating(
            db,
            model_id=request.model_id,
            task_type=request.task_type,
            user_rating=request.rating,
            user_id=current_user.id,
            project_id=request.project_id,
            user_comment=request.comment,
            prompt_text=request.prompt_text,
            output_urls=request.output_urls,
        )
        return FeedbackResponse(success=True, feedback_id=feedback.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit rating: {str(e)}",
        )


@router.post("/qc-result", response_model=FeedbackResponse)
async def submit_qc_result(
    request: QCResultRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = get_feedback_loop_service()

    try:
        feedback = service.submit_qc_result(
            db,
            model_id=request.model_id,
            task_type=request.task_type,
            qc_passed=request.qc_passed,
            qc_score=request.qc_score,
            qc_details=request.qc_details,
            style_match_score=request.style_match_score,
            prompt_adherence_score=request.prompt_adherence_score,
            visual_quality_score=request.visual_quality_score,
            character_consistency_score=request.character_consistency_score,
            motion_stability_score=request.motion_stability_score,
            generation_latency=request.generation_latency,
            generation_cost=request.generation_cost,
            prompt_text=request.prompt_text,
            output_urls=request.output_urls,
            project_id=request.project_id,
        )
        return FeedbackResponse(success=True, feedback_id=feedback.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit QC result: {str(e)}",
        )


@router.get("/model-stats/{model_id}", response_model=ModelStatsResponse)
async def get_model_feedback_stats(
    model_id: str,
    task_type: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = get_feedback_loop_service()

    try:
        stats = service.get_model_feedback_stats(db, model_id, task_type, days)
        return ModelStatsResponse(success=True, stats=stats)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}",
        )


@router.post("/apply-to-profiles", response_model=ApplyFeedbackResponse)
async def apply_feedback_to_profiles(
    request: ApplyFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = get_feedback_loop_service()

    try:
        result = service.apply_feedback_to_model_profiles(
            db,
            min_samples=request.min_samples,
            days=request.days,
            user_rating_weight=request.user_rating_weight,
            qc_weight=request.qc_weight,
        )
        return ApplyFeedbackResponse(
            success=True,
            updated_models=result["updated_models"],
            total_feedback_processed=result["total_feedback_processed"],
            details=result.get("details"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply feedback: {str(e)}",
        )
