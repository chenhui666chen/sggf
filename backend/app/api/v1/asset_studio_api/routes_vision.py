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

from app.core.security import get_current_user
from app.models.user import User
from app.services.audiobook.ai_music import MusicGenerationRequest, MusicStyle, create_music_generator
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import router
from app.api.v1.asset_studio_api._constants import *
from app.api.v1.asset_studio_api._helpers import *
from app.api.v1.asset_studio_api._helpers import (
    _build_vision_review_response,
    _raise_for_failed_result,
    _resolve_review_asset_type,
    _save_upload_file,
)

@router.post("/vision-review", response_model=AssetStudioVisionReviewResponse)
def review_vision_asset(
    asset_file: UploadFile = File(...),
    original_prompt: str = Form(default=""),
    model_id: str = Form(default=DEFAULT_VISION_REVIEW_MODEL_ID),
    current_user: User = Depends(get_current_user),
):
    del current_user

    resolved_model_id = (model_id or "").strip() or DEFAULT_VISION_REVIEW_MODEL_ID
    if resolved_model_id not in VISION_REVIEW_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前视觉识别入口仅支持 qwen3-vl-plus",
        )

    asset_type = _resolve_review_asset_type(asset_file)
    saved_path = _save_upload_file(asset_file, subdir="vision_review")
    criteria = VISION_REVIEW_CRITERIA.get(asset_type, [])

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

    return _build_vision_review_response(
        asset_type=asset_type,
        original_prompt=original_prompt,
        upload=asset_file,
        result=result,
        criteria=criteria,
    )


