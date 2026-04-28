"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
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
logger = logging.getLogger(__name__)

from app.api.v1.asset_studio_api import router
from app.api.v1.asset_studio_api._constants import *
from app.api.v1.asset_studio_api._helpers import *
from app.api.v1.asset_studio_api._helpers import (
    _build_response,
    _parse_optional_int,
    _raise_for_failed_result,
    _save_upload_file,
    _validate_dimensions_for_models,
    _validate_video_duration,
)

@router.post("/video", response_model=AssetStudioGenerateResponse)
def generate_video_asset(
    prompt: str = Form(...),
    negative_prompt: str = Form(default=""),
    model_id: str = Form(default=DEFAULT_VIDEO_GENERATION_MODEL_ID),
    width: int = Form(default=1280),
    height: int = Form(default=720),
    duration: float = Form(default=5.0),
    seed: str | None = Form(default=None),
    camera_control: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    requested_model_id = (model_id or "").strip() or DEFAULT_VIDEO_GENERATION_MODEL_ID
    seed_value = _parse_optional_int(seed)
    reference_path = (
        _save_upload_file(reference_image, subdir="video")
        if reference_image and reference_image.filename
        else None
    )
    resolved_model_id = requested_model_id if requested_model_id in VIDEO_MODELS else DEFAULT_VIDEO_GENERATION_MODEL_ID
    if reference_path and resolved_model_id not in {DEFAULT_MOTION_MODEL_ID}:
        resolved_model_id = DEFAULT_MOTION_MODEL_ID
    if resolved_model_id == DEFAULT_MOTION_MODEL_ID and not reference_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wan2.7-i2v 需要上传首帧参考图",
        )
    resolved_width, resolved_height = _validate_dimensions_for_models(
        VIDEO_MODELS,
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, max(1.0, min(float(duration), 15.0)))
    logger.info(
        "Asset Studio video request accepted | model_id=%s | size=%sx%s | duration=%s | has_reference_image=%s",
        resolved_model_id,
        resolved_width,
        resolved_height,
        resolved_duration,
        bool(reference_path),
    )

    result = media_runtime.generate_video(
        prompt=cleaned_prompt,
        negative_prompt=negative_prompt.strip(),
        duration=resolved_duration,
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        image_path=str(reference_path) if reference_path else None,
        camera_control=(camera_control or "").strip() or None,
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="视频生成失败")
    logger.info(
        "Asset Studio video request completed | model_id=%s | outputs=%s",
        result.model_id,
        len(result.outputs or []),
    )
    routing_message = None
    if requested_model_id != resolved_model_id:
        routing_message = "检测到参考图输入，已自动切换到图生视频模型。"
    if str(result.model_id or "") and str(result.model_id or "") != resolved_model_id:
        routing_message = f"当前请求参数与 {resolved_model_id} 的约束不兼容，已自动改用 {result.model_id}。"
    return _build_response(
        kind="video",
        mode="image_to_video" if reference_path else "text_to_video",
        result=result,
        metadata={
            "has_reference_image": bool(reference_path),
            "requested_model_id": requested_model_id,
            "resolved_model_id": resolved_model_id,
            "executed_model_id": str(result.model_id or ""),
            "routing_message": routing_message,
        },
    )


@router.post("/motion", response_model=AssetStudioGenerateResponse)
def generate_motion_asset(
    prompt: str = Form(...),
    model_id: str = Form(default=DEFAULT_MOTION_MODEL_ID),
    width: int = Form(default=1280),
    height: int = Form(default=720),
    duration: float = Form(default=5.0),
    seed: str | None = Form(default=None),
    motion_control: str = Form(default="medium"),
    camera_control: str | None = Form(default=None),
    reference_image: UploadFile | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    if not reference_image or not reference_image.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作控制至少需要上传一张参考图")

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作描述不能为空")

    requested_model_id = (model_id or "").strip() or DEFAULT_MOTION_MODEL_ID
    seed_value = _parse_optional_int(seed)
    reference_path = _save_upload_file(reference_image, subdir="motion")
    resolved_model_id = requested_model_id if requested_model_id in MOTION_MODELS else DEFAULT_MOTION_MODEL_ID
    resolved_width, resolved_height = _validate_dimensions_for_models(
        MOTION_MODELS,
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, max(1.0, min(float(duration), 15.0)))
    logger.info(
        "Asset Studio motion request accepted | model_id=%s | size=%sx%s | duration=%s",
        resolved_model_id,
        resolved_width,
        resolved_height,
        resolved_duration,
    )

    result = media_runtime.generate_video(
        prompt=cleaned_prompt,
        duration=resolved_duration,
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        image_path=str(reference_path),
        camera_control=(camera_control or "").strip() or None,
        motion_control=(motion_control or "").strip() or "medium",
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="动作控制生成失败")
    logger.info(
        "Asset Studio motion request completed | model_id=%s | outputs=%s",
        result.model_id,
        len(result.outputs or []),
    )
    return _build_response(
        kind="motion",
        mode="image_to_video_motion",
        result=result,
        metadata={
            "motion_control": motion_control,
            "requested_model_id": requested_model_id,
            "resolved_model_id": resolved_model_id,
            "executed_model_id": str(result.model_id or ""),
            "routing_message": (
                f"当前请求参数与 {resolved_model_id} 的约束不兼容，已自动改用 {result.model_id}。"
                if str(result.model_id or "") and str(result.model_id or "") != resolved_model_id
                else None
            ),
        },
    )


