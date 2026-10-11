"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from math import gcd
import mimetypes
import re
import shutil
import uuid
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
from app.services.audiobook.voice_parameter_policy import stabilize_instruct_model_speed
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
    _build_audio_response,
    _merge_points_billing_metadata,
    _materialize_output_reference,
    _copy_output_file,
    _raise_for_failed_result,
    _release_asset_studio_billing_safely,
    _reserve_asset_studio_billing,
    _resolve_billed_audio_duration_seconds,
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
    # 兼容旧客户端字段；固定音色运行时禁止应用片段级音高控制。
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
            "volume": int(volume),
        }
        cleaned_instruction = str(instruction or "").strip()
        if cleaned_instruction:
            voice_params["instruction"] = cleaned_instruction
        voice_params = stabilize_instruct_model_speed(voice_params, resolved_model_id)

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
                        "pace_control": "numeric" if "rate" in voice_params else "semantic",
                        **({"rate": float(voice_params["rate"])} if "rate" in voice_params else {}),
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

    resolved_model_id = normalize_model_id(requested_model_id) or requested_model_id
    if resolved_model_id not in SOUND_EFFECT_AUDIO_MODELS:
        # 历史配置里可能仍写着已下线的旧音效模型 ID，统一收敛到当前音效默认模型。
        resolved_model_id = DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID

    mode = "text_to_sound_effect"
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
            summary="资产工作台音效生成已启动，积分按请求时长上限冻结。",
            extra_payload={
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
            },
        )

        from adapters.registry import registry

        adapter = registry.get_adapter(resolved_model_id)
        result = await asyncio.to_thread(
            adapter.generate,
            prompt=cleaned_prompt,
            references=None,
            audio_config=dict(DEFAULT_AUDIO_CONFIG),
            watermark={},
        )
        if not result.success or not result.outputs:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=result.error or "音效生成失败",
            )
        output_path = await asyncio.to_thread(
            _materialize_output_reference,
            result.outputs[0],
            kind="audio",
            subdir="audio/sound-effects",
        )

        result_metadata = dict(result.metadata or {})
        actual_duration_seconds = result_metadata.get("duration")
        billed_duration_seconds = _resolve_billed_audio_duration_seconds(
            requested_seconds=resolved_duration,
            metadata=result_metadata,
        )
        settled_basis_yuan = estimate_asset_studio_basis_yuan(
            kind="audio",
            mode=mode,
            model_id=resolved_model_id,
            duration_seconds=billed_duration_seconds,
            prompt_chars=len(cleaned_prompt),
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
                    "actual_duration_seconds": actual_duration_seconds,
                    "format": "mp3",
                    "sample_rate": 48000,
                    **result_metadata,
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
            basis_yuan=settled_basis_yuan,
            model_id=resolved_model_id,
            summary="资产工作台音效生成已完成，积分按实际时长结算。",
            extra_payload={
                "generation_type": normalized_generation_type,
                "duration_seconds": resolved_duration,
                "billed_duration_seconds": billed_duration_seconds,
                "actual_duration_seconds": actual_duration_seconds,
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


