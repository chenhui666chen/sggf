"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from math import gcd
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook.ai_music import MusicGenerationRequest, MusicStyle, create_music_generator
from app.services.points_usage_pricing import estimate_asset_studio_basis_yuan
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import router
from app.api.v1.asset_studio_api._constants import *
from app.api.v1.asset_studio_api._helpers import *
from app.api.v1.asset_studio_api._helpers import (
    _build_vision_review_response,
    _merge_points_billing_metadata,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _resolve_review_asset_type,
    _save_upload_file,
    _settle_asset_studio_billing,
)

@router.post("/vision-review", response_model=AssetStudioVisionReviewResponse)
def review_vision_asset(
    asset_file: UploadFile = File(...),
    original_prompt: str = Form(default=""),
    model_id: str = Form(default=DEFAULT_VISION_REVIEW_MODEL_ID),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved_model_id = (model_id or "").strip() or DEFAULT_VISION_REVIEW_MODEL_ID
    if resolved_model_id not in VISION_REVIEW_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前视觉识别入口仅支持 {', '.join(sorted(VISION_REVIEW_MODELS))}",
        )

    asset_type = _resolve_review_asset_type(asset_file)
    saved_path = _save_upload_file(asset_file, subdir="vision_review")
    criteria = VISION_REVIEW_CRITERIA.get(asset_type, [])

    mode = "quality_review"
    basis_yuan = estimate_asset_studio_basis_yuan(
        kind="vision_review",
        mode=mode,
        model_id=resolved_model_id,
        asset_type=asset_type,
        output_count=1,
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="vision_review",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            request_path="/api/v1/asset-studio/vision-review",
            summary="资产工作台视觉评审已启动，积分已按评审类型冻结。",
            extra_payload={
                "asset_type": asset_type,
                "criteria_count": len(criteria),
            },
        )
        if asset_type == "image":
            result = media_runtime.analyze_image(
                image_path=str(saved_path),
                analysis_type="quality",
                criteria=criteria,
                model_id=resolved_model_id,
                strategy="quality",
            )
            _raise_for_failed_result(result, fallback_message="图片识别失败")
        else:
            result = media_runtime.analyze_video(
                video_path=str(saved_path),
                analysis_type="quality",
                criteria=criteria,
                model_id=resolved_model_id,
                strategy="quality",
            )
            _raise_for_failed_result(result, fallback_message="视频识别失败")

        response = _build_vision_review_response(
            asset_type=asset_type,
            original_prompt=original_prompt,
            upload=asset_file,
            result=result,
            criteria=criteria,
        )
        response.metadata = _merge_points_billing_metadata(response.metadata, precheck)
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="vision_review",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台视觉评审已完成，积分已结算。",
            extra_payload={
                "asset_type": asset_type,
                "criteria_count": len(criteria),
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台视觉评审失败，已释放冻结积分。",
            kind="vision_review",
            mode=mode,
        )
        raise


