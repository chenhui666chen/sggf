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

@router.post("/audio", response_model=AssetStudioGenerateResponse)
async def generate_audio_asset(
    prompt: str = Form(...),
    generation_type: str = Form(default="music"),
    model_id: str = Form(default="mureka-o1-instrumental"),
    duration: int = Form(default=30),
    style: str = Form(default="氛围"),
    mood: str = Form(default="calm"),
    tempo: str = Form(default="medium"),
    current_user: User = Depends(get_current_user),
):
    del current_user

    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    normalized_generation_type = str(generation_type or "").strip().lower()
    if normalized_generation_type not in {"music", "sound-effect"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的音频生成类型")

    requested_model_id = (model_id or "").strip() or (
        "mureka-o1-instrumental" if normalized_generation_type == "music" else "vidu-timing2audio"
    )
    normalized_mood = str(mood or "").strip() or "calm"
    normalized_tempo = str(tempo or "").strip() or "medium"

    if normalized_generation_type == "music":
        resolved_duration = _validate_audio_duration("music", duration)
        resolved_model_id = "mureka-o1-instrumental"
        music_generator = create_music_generator(enable_cache=True)
        music_result = await music_generator.client.generate_music(
            MusicGenerationRequest(
                prompt=cleaned_prompt,
                style=_resolve_music_style(style),
                duration=resolved_duration,
                tempo=normalized_tempo,
                mood=normalized_mood,
            )
        )
        if not music_result.success:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=music_result.error_message or "音乐生成失败",
            )

        if music_result.audio_data:
            output_path = _save_binary_output(music_result.audio_data, subdir="audio/music", suffix=".mp3")
        elif music_result.audio_file_path:
            source_path = PROJECT_ROOT / "backend" / "data" / "audio_library" / music_result.audio_file_path
            if not source_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="音乐文件已生成，但本地结果文件不存在",
                )
            output_path = _copy_output_file(source_path, subdir="audio/music")
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="音乐生成成功，但没有可返回的音频结果",
            )

        return _build_audio_response(
            mode="text_to_music",
            model_id=resolved_model_id,
            output_path=output_path,
            metadata={
                "requested_model_id": requested_model_id,
                "resolved_model_id": resolved_model_id,
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
                "style": _resolve_music_style(style).value,
                "mood": normalized_mood,
                "tempo": normalized_tempo,
                "cached": bool(music_result.cached),
            },
        )

    resolved_duration = _validate_audio_duration("sound-effect", duration)
    from app.services.audiobook.vidu_timing2audio_generator import ViduTiming2AudioGenerator
    
    requested_vidu = requested_model_id == "vidu-timing2audio"
    vidu_generator = ViduTiming2AudioGenerator() if requested_vidu else None
    vidu_available = bool(vidu_generator and vidu_generator.api_key)

    if requested_vidu and vidu_available:
        vidu_output_path = _allocate_output_path(subdir="audio/sound-effects", suffix=".mp3")
        timing_prompts = [
            {
                "from": 0.0,
                "to": float(resolved_duration),
                "prompt": cleaned_prompt
            }
        ]
        vidu_result = await asyncio.to_thread(
            vidu_generator.generate_and_download,
            timing_prompts,
            vidu_output_path,
            float(resolved_duration),
            "mp3",
            120,
        )
        if vidu_result.success and vidu_result.local_file_path:
            output_path = Path(vidu_result.local_file_path)
            return _build_audio_response(
                mode="text_to_sound_effect",
                model_id="vidu-timing2audio",
                output_path=output_path,
                metadata={
                    "requested_model_id": requested_model_id,
                    "resolved_model_id": "vidu-timing2audio",
                    "generation_type": normalized_generation_type,
                    "duration_seconds": resolved_duration,
                    "fallback_used": False,
                },
            )

        fallback_reason = vidu_result.error or "Vidu 音效生成失败，已回退到 Mureka 环境音链路。"
    elif requested_vidu:
        fallback_reason = "当前未配置 Vidu API Key，已回退到 Mureka 环境音链路。"
    else:
        fallback_reason = "音效生成失败"

    music_generator = create_music_generator(enable_cache=True)
    fallback_prompt = f"短音效或环境音，干净利落，无人声，不过度旋律化：{cleaned_prompt}"
    music_result = await music_generator.client.generate_music(
        MusicGenerationRequest(
            prompt=fallback_prompt,
            style=MusicStyle.AMBIENT,
            duration=resolved_duration,
            tempo=normalized_tempo,
            mood=normalized_mood,
        )
    )
    if not music_result.success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=music_result.error_message or fallback_reason or "音效生成失败",
        )

    if music_result.audio_data:
        output_path = _save_binary_output(music_result.audio_data, subdir="audio/sound-effects", suffix=".mp3")
    elif music_result.audio_file_path:
        source_path = PROJECT_ROOT / "backend" / "data" / "audio_library" / music_result.audio_file_path
        if not source_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="音效文件已生成，但本地结果文件不存在",
            )
        output_path = _copy_output_file(source_path, subdir="audio/sound-effects")
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="音效生成成功，但没有可返回的音频结果",
        )

    return _build_audio_response(
        mode="text_to_sound_effect",
        model_id="mureka-o1-instrumental",
        output_path=output_path,
        metadata={
            "requested_model_id": requested_model_id,
            "resolved_model_id": "mureka-o1-instrumental",
            "generation_type": normalized_generation_type,
            "duration_seconds": resolved_duration,
            "style": MusicStyle.AMBIENT.value,
            "mood": normalized_mood,
            "tempo": normalized_tempo,
            "fallback_used": requested_kling,
            "fallback_reason": fallback_reason or None,
            "cached": bool(music_result.cached),
        },
    )


