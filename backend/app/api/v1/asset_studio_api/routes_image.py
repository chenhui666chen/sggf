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
from app.services.points_usage_pricing import AssetStudioImagePriceMissing, estimate_asset_studio_basis_yuan
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
    _parse_optional_int,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _save_upload_file,
    _settle_asset_studio_billing,
    _validate_dimensions_for_models,
)

@router.post("/image", response_model=AssetStudioGenerateResponse)
def generate_image_asset(
    prompt: str = Form(...),
    negative_prompt: str = Form(default=""),
    model_id: str = Form(default=DEFAULT_IMAGE_GENERATION_MODEL_ID),
    width: int = Form(default=1024),
    height: int = Form(default=1024),
    quality: str = Form(default="standard"),
    style: str | None = Form(default=None),
    seed: str | None = Form(default=None),
    strength: float = Form(default=0.72),
    reference_images: list[UploadFile] | None = File(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
        normalized_model_id = normalize_model_id(model_id) or ""
        if normalized_model_id not in IMAGE_EDIT_MODELS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"模型 {model_id} 不支持图片编辑")
        if normalized_model_id == "qwen-image-3.0" and len(saved_reference_paths) > 3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Qwen Image 3.0 最多支持 3 张输入图片")
        resolved_model_id = normalized_model_id
        resolved_width, resolved_height = _validate_dimensions_for_models(
            {resolved_model_id}, width, height, request_label="图片",
        )
        mode = "reference_edit"
        try:
            basis_yuan = estimate_asset_studio_basis_yuan(
                kind="image",
                mode=mode,
                model_id=resolved_model_id,
                input_count=len(saved_reference_paths),
                output_count=1,
                prompt_chars=len(cleaned_prompt),
            )
        except AssetStudioImagePriceMissing as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        precheck = None
        try:
            precheck = _reserve_asset_studio_billing(
                db=db,
                current_user=current_user,
                kind="image",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                request_path="/api/v1/asset-studio/image",
                summary="资产工作台参考图生成已启动，积分已按图片编辑任务冻结。",
                extra_payload={
                    "reference_count": len(saved_reference_paths),
                    "width": resolved_width,
                    "height": resolved_height,
                },
            )
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
            response = _build_response(
                kind="image",
                mode=mode,
                result=result,
                metadata=_merge_points_billing_metadata(
                    {
                        "reference_count": len(saved_reference_paths),
                        "workspace_note": "已自动切换到图像编辑/参考图生成链路。",
                    },
                    precheck,
                ),
            )
            _settle_asset_studio_billing(
                db=db,
                current_user=current_user,
                precheck=precheck,
                kind="image",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                summary="资产工作台参考图生成已完成，积分已结算。",
                extra_payload={
                    "reference_count": len(saved_reference_paths),
                    "width": resolved_width,
                    "height": resolved_height,
                },
            )
            return response
        except Exception:
            _release_asset_studio_billing_safely(
                db=db,
                current_user=current_user,
                precheck=precheck,
                reason="资产工作台参考图生成失败，已释放冻结积分。",
                kind="image",
                mode=mode,
            )
            raise

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
    resolved_model_id = normalized_model_id if normalized_model_id in IMAGE_GENERATION_MODELS else DEFAULT_IMAGE_GENERATION_MODEL_ID
    mode = "text_to_image"
    basis_yuan = estimate_asset_studio_basis_yuan(
        kind="image",
        mode=mode,
        model_id=resolved_model_id,
        output_count=1,
        prompt_chars=len(cleaned_prompt),
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="image",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            request_path="/api/v1/asset-studio/image",
            summary="资产工作台文生图任务已启动，积分已按图片生成任务冻结。",
            extra_payload={
                "width": resolved_width,
                "height": resolved_height,
                "quality": quality,
            },
        )
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
        response = _build_response(
            kind="image",
            mode=mode,
            result=result,
            metadata=_merge_points_billing_metadata(
                {
                    "width": resolved_width,
                    "height": resolved_height,
                    "quality": quality,
                },
                precheck,
            ),
        )
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="image",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台文生图任务已完成，积分已结算。",
            extra_payload={
                "width": resolved_width,
                "height": resolved_height,
                "quality": quality,
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台文生图任务失败，已释放冻结积分。",
            kind="image",
            mode=mode,
        )
        raise


