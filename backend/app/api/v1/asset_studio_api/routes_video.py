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
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
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
    _estimate_video_basis_yuan,
    _merge_points_billing_metadata,
    _parse_optional_int,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _resolve_requested_video_model,
    _resolve_video_billing_seconds,
    _save_upload_file,
    _settle_asset_studio_billing,
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
    db: Session = Depends(get_db),
):
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
    resolved_model_id = _resolve_requested_video_model(
        requested_model_id,
        allowed_models=VIDEO_MODELS,
        request_label="视频生成",
    )
    resolved_width, resolved_height = _validate_dimensions_for_models(
        {resolved_model_id},
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, float(duration))
    billing_duration_seconds = _resolve_video_billing_seconds(resolved_model_id, resolved_duration)
    logger.info(
        "Asset Studio video request accepted | model_id=%s | size=%sx%s | duration=%s | has_reference_image=%s",
        resolved_model_id,
        resolved_width,
        resolved_height,
        resolved_duration,
        bool(reference_path),
    )

    mode = "image_to_video" if reference_path else "text_to_video"
    basis_yuan = _estimate_video_basis_yuan(
        kind="video",
        mode=mode,
        model_id=resolved_model_id,
        duration_seconds=billing_duration_seconds,
        width=resolved_width,
        height=resolved_height,
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="video",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            request_path="/api/v1/asset-studio/video",
            summary="资产工作台视频生成已启动，积分已按视频时长冻结。",
            extra_payload={
                "duration_seconds": resolved_duration,
                "width": resolved_width,
                "height": resolved_height,
                "has_reference_image": bool(reference_path),
            },
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
        executed_model_id = str(result.model_id or "")
        if executed_model_id and executed_model_id != resolved_model_id:
            # 入口已按目标模型的档案区间预检，运行时仍改档说明碰到了预检覆盖不到的约束。
            # 此处绝不交付换档产物：冻结会在 except 里释放，用户不会被按 A 模型计费拿 B 模型。
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前请求参数与 {resolved_model_id} 的约束不兼容（运行时候选为 {executed_model_id}），已中止且不计费。",
            )
        response = _build_response(
            kind="video",
            mode=mode,
            result=result,
            metadata=_merge_points_billing_metadata(
                {
                    "has_reference_image": bool(reference_path),
                    "requested_model_id": requested_model_id,
                    "resolved_model_id": resolved_model_id,
                    "executed_model_id": executed_model_id,
                },
                precheck,
            ),
        )
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="video",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台视频生成已完成，积分已结算。",
            extra_payload={
                "duration_seconds": resolved_duration,
                "width": resolved_width,
                "height": resolved_height,
                "has_reference_image": bool(reference_path),
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台视频生成失败，已释放冻结积分。",
            kind="video",
            mode=mode,
        )
        raise


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
    db: Session = Depends(get_db),
):
    if not reference_image or not reference_image.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作控制至少需要上传一张参考图")

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="动作描述不能为空")

    requested_model_id = (model_id or "").strip() or DEFAULT_MOTION_MODEL_ID
    seed_value = _parse_optional_int(seed)
    reference_path = _save_upload_file(reference_image, subdir="motion")
    resolved_model_id = _resolve_requested_video_model(
        requested_model_id,
        allowed_models=MOTION_MODELS,
        request_label="动作控制",
    )
    resolved_width, resolved_height = _validate_dimensions_for_models(
        {resolved_model_id},
        width,
        height,
        request_label="视频",
    )
    resolved_duration = _validate_video_duration(resolved_model_id, float(duration))
    billing_duration_seconds = _resolve_video_billing_seconds(resolved_model_id, resolved_duration)
    logger.info(
        "Asset Studio motion request accepted | model_id=%s | size=%sx%s | duration=%s",
        resolved_model_id,
        resolved_width,
        resolved_height,
        resolved_duration,
    )

    mode = "image_to_video_motion"
    basis_yuan = _estimate_video_basis_yuan(
        kind="motion",
        mode=mode,
        model_id=resolved_model_id,
        duration_seconds=billing_duration_seconds,
        width=resolved_width,
        height=resolved_height,
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="motion",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            request_path="/api/v1/asset-studio/motion",
            summary="资产工作台动作控制生成已启动，积分已按视频时长冻结。",
            extra_payload={
                "duration_seconds": resolved_duration,
                "width": resolved_width,
                "height": resolved_height,
                "motion_control": motion_control,
            },
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
        executed_model_id = str(result.model_id or "")
        if executed_model_id and executed_model_id != resolved_model_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前请求参数与 {resolved_model_id} 的约束不兼容（运行时候选为 {executed_model_id}），已中止且不计费。",
            )
        response = _build_response(
            kind="motion",
            mode=mode,
            result=result,
            metadata=_merge_points_billing_metadata(
                {
                    "motion_control": motion_control,
                    "requested_model_id": requested_model_id,
                    "resolved_model_id": resolved_model_id,
                    "executed_model_id": executed_model_id,
                },
                precheck,
            ),
        )
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="motion",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台动作控制生成已完成，积分已结算。",
            extra_payload={
                "duration_seconds": resolved_duration,
                "width": resolved_width,
                "height": resolved_height,
                "motion_control": motion_control,
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台动作控制生成失败，已释放冻结积分。",
            kind="motion",
            mode=mode,
        )
        raise


