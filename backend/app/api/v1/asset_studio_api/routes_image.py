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
    _build_response,
    _parse_optional_int,
    _raise_for_failed_result,
    _save_upload_file,
    _validate_dimensions_for_models,
)

@router.post("/image", response_model=AssetStudioGenerateResponse)
def generate_image_asset(
    prompt: str = Form(...),
    negative_prompt: str = Form(default=""),
    model_id: str = Form(default="wan2.6-t2i"),
    width: int = Form(default=1024),
    height: int = Form(default=1024),
    quality: str = Form(default="standard"),
    style: str | None = Form(default=None),
    seed: str | None = Form(default=None),
    strength: float = Form(default=0.72),
    reference_images: list[UploadFile] | None = File(default=None),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    saved_reference_paths = [
        _save_upload_file(upload, subdir="image")
        for upload in (reference_images or [])
        if upload and upload.filename
    ]
    seed_value = _parse_optional_int(seed)

    if saved_reference_paths:
        resolved_width, resolved_height = _validate_dimensions_for_models(
            IMAGE_EDIT_MODELS,
            width,
            height,
            request_label="图片",
        )
        normalized_model_id = normalize_model_id(model_id) or ""
        resolved_model_id = normalized_model_id if normalized_model_id in IMAGE_EDIT_MODELS else "qwen-image-edit-plus"
        result = media_runtime.edit_image(
            image_path=str(saved_reference_paths[0]),
            edit_prompt=cleaned_prompt,
            strength=max(0.0, min(float(strength), 1.0)),
            width=resolved_width,
            height=resolved_height,
            reference_images=[str(path) for path in saved_reference_paths[1:]] or None,
            seed=seed_value,
            model_id=resolved_model_id,
            use_fallback=False,
        )
        _raise_for_failed_result(result, fallback_message="参考图生成失败")
        return _build_response(
            kind="image",
            mode="reference_edit",
            result=result,
            metadata={
                "reference_count": len(saved_reference_paths),
                "workspace_note": "已自动切换到图像编辑/参考图生成链路。",
            },
        )

    if model_id in IMAGE_EDIT_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图像编辑模型需要至少上传一张参考图",
        )

    resolved_width, resolved_height = _validate_dimensions_for_models(
        IMAGE_GENERATION_MODELS,
        width,
        height,
        request_label="图片",
    )
    normalized_model_id = normalize_model_id(model_id) or ""
    resolved_model_id = normalized_model_id if normalized_model_id in IMAGE_GENERATION_MODELS else "wan2.6-t2i"
    result = media_runtime.generate_image(
        prompt=cleaned_prompt,
        negative_prompt=negative_prompt.strip(),
        width=resolved_width,
        height=resolved_height,
        seed=seed_value,
        style=(style or "").strip() or None,
        quality=quality,
        num_outputs=1,
        model_id=resolved_model_id,
        use_fallback=False,
    )
    _raise_for_failed_result(result, fallback_message="图片生成失败")
    return _build_response(kind="image", mode="text_to_image", result=result)


