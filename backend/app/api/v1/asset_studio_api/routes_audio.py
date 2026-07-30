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
from adapters.volcengine.audio_generation import DEFAULT_AUDIO_CONFIG
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import router
from app.api.v1.asset_studio_api._constants import *
from app.api.v1.asset_studio_api._helpers import *
from app.api.v1.asset_studio_api._helpers import (
    _allocate_output_path,
    _build_audio_response,
    _merge_points_billing_metadata,
    _materialize_output_reference,
    _copy_output_file,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _resolve_music_style,
    _save_binary_output,
    _settle_asset_studio_billing,
    _validate_audio_duration,
)

@router.post("/audio", response_model=AssetStudioGenerateResponse)
async def generate_audio_asset(
    prompt: str = Form(...),
    generation_type: str = Form(default="music"),
    model_id: str = Form(default=DEFAULT_AUDIO_MUSIC_MODEL_ID),
    duration: int = Form(default=30),
    style: str = Form(default="氛围"),
    mood: str = Form(default="calm"),
    tempo: str = Form(default="medium"),
    voice_id: str = Form(default=""),
    instruction: str = Form(default=""),
    rate: float = Form(default=1.0),
    pitch: float = Form(default=1.0),
    volume: int = Form(default=50),
    emotion: str = Form(default="neutral"),
    speaker_ids: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="提示词不能为空")

    normalized_generation_type = str(generation_type or "").strip().lower()
    if normalized_generation_type not in {"music", "sound-effect", "speech", "scene-audio"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的音频生成类型")

    requested_model_id = (model_id or "").strip() or (
        DEFAULT_AUDIO_MUSIC_MODEL_ID
        if normalized_generation_type == "music"
        else DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID
        if normalized_generation_type == "sound-effect"
        else DEFAULT_AUDIO_SPEECH_MODEL_ID
        if normalized_generation_type == "speech"
        else DEFAULT_AUDIO_SCENE_MODEL_ID
    )
    normalized_mood = str(mood or "").strip() or "calm"
    normalized_tempo = str(tempo or "").strip() or "medium"

    if normalized_generation_type == "scene-audio":
        resolved_model_id = normalize_model_id(requested_model_id) or requested_model_id
        if resolved_model_id not in SCENE_AUDIO_MODELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前场景音频仅支持以下模型: {', '.join(sorted(SCENE_AUDIO_MODELS))}",
            )

        references = [
            {"speaker": value.strip()}
            for value in re.split(r"[,，\n]+", str(speaker_ids or ""))
            if value.strip()
        ]
        mode = "text_to_audio"
        basis_yuan = estimate_asset_studio_basis_yuan(
            kind="audio",
            mode=mode,
            model_id=resolved_model_id,
            prompt_chars=len(cleaned_prompt),
        )
        precheck = None
        try:
            precheck = _reserve_asset_studio_billing(
                db=db,
                current_user=current_user,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                request_path="/api/v1/asset-studio/audio",
                summary="资产工作台场景音频生成已启动，积分已冻结。",
                extra_payload={"generation_type": normalized_generation_type, "speaker_count": len(references)},
            )
            from adapters.registry import registry

            adapter = registry.get_adapter(resolved_model_id)
            result = await asyncio.to_thread(
                adapter.generate,
                prompt=cleaned_prompt,
                references=references or None,
                audio_config=dict(DEFAULT_AUDIO_CONFIG),
                watermark={},
            )
            if not result.success or not result.outputs:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=result.error or "豆包场景音频生成失败",
                )
            output_path = await asyncio.to_thread(
                _materialize_output_reference,
                result.outputs[0],
                kind="audio",
                subdir="audio/scene",
            )
            response = _build_audio_response(
                mode=mode,
                model_id=resolved_model_id,
                output_path=output_path,
                metadata=_merge_points_billing_metadata(
                    {
                        "requested_model_id": requested_model_id,
                        "resolved_model_id": resolved_model_id,
                        "generation_type": normalized_generation_type,
                        "speaker_ids": [item["speaker"] for item in references],
                        "format": "mp3",
                        "sample_rate": 48000,
                        **dict(result.metadata or {}),
                    },
                    precheck,
                ),
            )
            _settle_asset_studio_billing(
                db=db,
                current_user=current_user,
                precheck=precheck,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                summary="资产工作台场景音频生成已完成，积分已结算。",
                extra_payload={"generation_type": normalized_generation_type, "speaker_count": len(references)},
            )
            return response
        except Exception:
            _release_asset_studio_billing_safely(
                db=db,
                current_user=current_user,
                precheck=precheck,
                reason="资产工作台场景音频生成失败，已释放冻结积分。",
                kind="audio",
                mode=mode,
            )
            raise

    if normalized_generation_type == "music":
        resolved_duration = _validate_audio_duration("music", duration)
        resolved_model_id = DEFAULT_AUDIO_MUSIC_MODEL_ID
        mode = "text_to_music"
        basis_yuan = estimate_asset_studio_basis_yuan(
            kind="audio",
            mode=mode,
            model_id=resolved_model_id,
            duration_seconds=resolved_duration,
            prompt_chars=len(cleaned_prompt),
        )
        precheck = None
        try:
            precheck = _reserve_asset_studio_billing(
                db=db,
                current_user=current_user,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                request_path="/api/v1/asset-studio/audio",
                summary="资产工作台音乐生成已启动，积分已按音频时长冻结。",
                extra_payload={
                    "generation_type": normalized_generation_type,
                    "duration_seconds": resolved_duration,
                },
            )
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

            response = _build_audio_response(
                mode=mode,
                model_id=resolved_model_id,
                output_path=output_path,
                metadata=_merge_points_billing_metadata(
                    {
                        "requested_model_id": requested_model_id,
                        "resolved_model_id": resolved_model_id,
                        "generation_type": normalized_generation_type,
                        "duration_seconds": resolved_duration,
                        "style": _resolve_music_style(style).value,
                        "mood": normalized_mood,
                        "tempo": normalized_tempo,
                        "cached": bool(music_result.cached),
                    },
                    precheck,
                ),
            )
            _settle_asset_studio_billing(
                db=db,
                current_user=current_user,
                precheck=precheck,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                summary="资产工作台音乐生成已完成，积分已结算。",
                extra_payload={
                    "generation_type": normalized_generation_type,
                    "duration_seconds": resolved_duration,
                },
            )
            return response
        except Exception:
            _release_asset_studio_billing_safely(
                db=db,
                current_user=current_user,
                precheck=precheck,
                reason="资产工作台音乐生成失败，已释放冻结积分。",
                kind="audio",
                mode=mode,
            )
            raise

    if normalized_generation_type == "speech":
        resolved_model_id = normalize_model_id(requested_model_id) or requested_model_id
        supported_speech_models = SPEECH_MODELS
        if resolved_model_id not in supported_speech_models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前语音合成仅支持以下模型: {', '.join(sorted(supported_speech_models))}",
            )

        cleaned_voice_id = str(voice_id or "").strip()
        if not cleaned_voice_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="语音合成需要选择音色")

        voice_params: dict[str, Any] = {
            "speaker": cleaned_voice_id,
            "rate": float(rate or 1.0),
            "pitch": float(pitch or 1.0),
            "volume": int(volume),
        }
        cleaned_instruction = str(instruction or "").strip()
        if cleaned_instruction:
            voice_params["instruction"] = cleaned_instruction

        mode = "text_to_speech"
        basis_yuan = estimate_asset_studio_basis_yuan(
            kind="audio",
            mode=mode,
            model_id=resolved_model_id,
            prompt_chars=len(cleaned_prompt),
        )
        precheck = None
        try:
            precheck = _reserve_asset_studio_billing(
                db=db,
                current_user=current_user,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                request_path="/api/v1/asset-studio/audio",
                summary="资产工作台语音合成已启动，积分已按文本长度冻结。",
                extra_payload={
                    "generation_type": normalized_generation_type,
                    "prompt_chars": len(cleaned_prompt),
                    "voice_id": cleaned_voice_id,
                },
            )
            speech_result = await media_runtime.synthesize_speech_result(
                text=cleaned_prompt,
                voice_params=voice_params,
                emotion=str(emotion or "neutral").strip() or "neutral",
                model_id=resolved_model_id,
                enable_cache=False,
                max_concurrent=1,
                request_delay=0.0,
            )
            _raise_for_failed_result(speech_result, fallback_message="语音合成失败")

            audio_bytes = speech_result.binary or b""
            if not audio_bytes:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="语音合成成功，但未返回音频数据")

            payload = speech_result.data if isinstance(speech_result.data, dict) else {}
            format_hint = str(payload.get("format") or "").strip().lower()
            suffix = ".wav" if format_hint == "wav" or audio_bytes.startswith(b"RIFF") else ".mp3"
            output_path = _save_binary_output(audio_bytes, subdir="audio/speech", suffix=suffix)

            response = _build_audio_response(
                mode=mode,
                model_id=resolved_model_id,
                output_path=output_path,
                metadata=_merge_points_billing_metadata(
                    {
                        "requested_model_id": requested_model_id,
                        "resolved_model_id": resolved_model_id,
                        "generation_type": normalized_generation_type,
                        "voice_id": cleaned_voice_id,
                        "instruction": cleaned_instruction or None,
                        "rate": float(rate or 1.0),
                        "pitch": float(pitch or 1.0),
                        "volume": int(volume),
                        "emotion": str(emotion or "neutral").strip() or "neutral",
                        "format": format_hint or suffix.lstrip("."),
                    },
                    precheck,
                ),
            )
            _settle_asset_studio_billing(
                db=db,
                current_user=current_user,
                precheck=precheck,
                kind="audio",
                mode=mode,
                basis_yuan=basis_yuan,
                model_id=resolved_model_id,
                summary="资产工作台语音合成已完成，积分已结算。",
                extra_payload={
                    "generation_type": normalized_generation_type,
                    "prompt_chars": len(cleaned_prompt),
                    "voice_id": cleaned_voice_id,
                },
            )
            return response
        except Exception:
            _release_asset_studio_billing_safely(
                db=db,
                current_user=current_user,
                precheck=precheck,
                reason="资产工作台语音合成失败，已释放冻结积分。",
                kind="audio",
                mode=mode,
            )
            raise

    resolved_duration = _validate_audio_duration("sound-effect", duration)
    from app.services.audiobook.vidu_timing2audio_generator import ViduTiming2AudioGenerator

    mode = "text_to_sound_effect"
    basis_yuan = estimate_asset_studio_basis_yuan(
        kind="audio",
        mode=mode,
        model_id=requested_model_id,
        duration_seconds=resolved_duration,
        prompt_chars=len(cleaned_prompt),
    )
    precheck = None
    try:
        precheck = _reserve_asset_studio_billing(
            db=db,
            current_user=current_user,
            kind="audio",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=requested_model_id,
            request_path="/api/v1/asset-studio/audio",
            summary="资产工作台音效生成已启动，积分已按音频时长冻结。",
            extra_payload={
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
            },
        )

        requested_vidu = requested_model_id == DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID
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
                response = _build_audio_response(
                    mode=mode,
                    model_id=DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID,
                    output_path=output_path,
                    metadata=_merge_points_billing_metadata(
                        {
                            "requested_model_id": requested_model_id,
                            "resolved_model_id": DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID,
                            "generation_type": normalized_generation_type,
                            "duration_seconds": resolved_duration,
                            "fallback_used": False,
                        },
                        precheck,
                    ),
                )
                _settle_asset_studio_billing(
                    db=db,
                    current_user=current_user,
                    precheck=precheck,
                    kind="audio",
                    mode=mode,
                    basis_yuan=basis_yuan,
                    model_id=DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID,
                    summary="资产工作台音效生成已完成，积分已结算。",
                    extra_payload={
                        "generation_type": normalized_generation_type,
                        "duration_seconds": resolved_duration,
                        "fallback_used": False,
                    },
                )
                return response

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

        response = _build_audio_response(
            mode=mode,
            model_id=DEFAULT_AUDIO_MUSIC_MODEL_ID,
            output_path=output_path,
            metadata=_merge_points_billing_metadata(
                {
                    "requested_model_id": requested_model_id,
                    "resolved_model_id": DEFAULT_AUDIO_MUSIC_MODEL_ID,
                    "generation_type": normalized_generation_type,
                    "duration_seconds": resolved_duration,
                    "style": MusicStyle.AMBIENT.value,
                    "mood": normalized_mood,
                    "tempo": normalized_tempo,
                    "fallback_used": requested_vidu,
                    "fallback_reason": fallback_reason or None,
                    "cached": bool(music_result.cached),
                },
                precheck,
            ),
        )
        _settle_asset_studio_billing(
            db=db,
            current_user=current_user,
            precheck=precheck,
            kind="audio",
            mode=mode,
            basis_yuan=basis_yuan,
            model_id=DEFAULT_AUDIO_MUSIC_MODEL_ID,
            summary="资产工作台音效生成已完成，积分已结算。",
            extra_payload={
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
                "fallback_used": requested_vidu,
            },
        )
        return response
    except Exception:
        _release_asset_studio_billing_safely(
            db=db,
            current_user=current_user,
            precheck=precheck,
            reason="资产工作台音效生成失败，已释放冻结积分。",
            kind="audio",
            mode=mode,
        )
        raise


