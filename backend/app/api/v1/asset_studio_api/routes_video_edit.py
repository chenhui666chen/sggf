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
    _build_response,
    _merge_points_billing_metadata,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _save_upload_file,
    _settle_asset_studio_billing,
    _validate_dimensions_for_models,
    _validate_video_duration,
)

@router.post("/video-edit", response_model=AssetStudioGenerateResponse)
async def generate_video_edit_asset(
    prompt: str = Form(...),
    model_id: str = Form(default=DEFAULT_VIDEO_EDIT_MODEL_ID),
    width: int = Form(default=1280),
    height: int = Form(default=720),
    duration: float = Form(default=5.0),
    edit_feature: str = Form(default="style-transfer"),
    reference_video: UploadFile | None = File(default=None),
    reference_images: list[UploadFile] | None = File(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """视频编辑接口，支持风格迁移、视频续接和多片段融合。"""
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="编辑描述不能为空")

    if not reference_video or not reference_video.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="视频编辑需要上传参考视频")

    normalized_edit_feature = (edit_feature or "").strip().lower()
    if normalized_edit_feature not in VIDEO_EDIT_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的编辑功能：{edit_feature}，可选值为 {', '.join(VIDEO_EDIT_FEATURES)}",
        )

    resolved_model_id = model_id if model_id in VIDEO_EDIT_MODELS else DEFAULT_VIDEO_EDIT_MODEL_ID
    reference_video_path = _save_upload_file(reference_video, subdir="video_edit")

    saved_reference_image_paths = [
        _save_upload_file(upload, subdir="video_edit")
        for upload in (reference_images or [])
        if upload and upload.filename
    ]

    resolved_width, resolved_height = _validate_dimensions_for_models(
        VIDEO_EDIT_MODELS,
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, max(1.0, min(float(duration), 15.0)))

    feature_label_map = {
        "style-transfer": "风格迁移",
        "video-extend": "视频续接",
        "video-remix": "多片段融合",
    }

    mode = normalized_edit_feature
    basis_yuan = estimate_asset_studio_basis_yuan(
        kind="video_edit",
        mode=mode,
        model_id=resolved_model_id,
        duration_seconds=resolved_duration,
        output_count=1,
        prompt_chars=len(cleaned_prompt),
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="video_edit",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            request_path="/api/v1/asset-studio/video-edit",
            summary="资产工作台视频编辑已启动，积分已按视频时长冻结。",
            extra_payload={
                "edit_feature": normalized_edit_feature,
                "duration_seconds": resolved_duration,
                "reference_image_count": len(saved_reference_image_paths),
            },
        )
        result = media_runtime.edit_video(
            prompt=cleaned_prompt,
            duration=resolved_duration,
            width=resolved_width,
            height=resolved_height,
            video_path=str(reference_video_path),
            reference_images=[str(path) for path in saved_reference_image_paths] or None,
            edit_feature=normalized_edit_feature,
            model_id=resolved_model_id,
            use_fallback=False,
        )
        _raise_for_failed_result(result, fallback_message="视频编辑失败")
        response = _build_response(
            kind="video_edit",
            mode=mode,
            result=result,
            metadata=_merge_points_billing_metadata(
                {
                    "edit_feature": normalized_edit_feature,
                    "edit_feature_label": feature_label_map.get(normalized_edit_feature, normalized_edit_feature),
                    "reference_video_name": reference_video.filename,
                    "reference_image_count": len(saved_reference_image_paths),
                },
                precheck,
            ),
        )
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="video_edit",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台视频编辑已完成，积分已结算。",
            extra_payload={
                "edit_feature": normalized_edit_feature,
                "duration_seconds": resolved_duration,
                "reference_image_count": len(saved_reference_image_paths),
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台视频编辑失败，已释放冻结积分。",
            kind="video_edit",
            mode=mode,
        )
        raise
