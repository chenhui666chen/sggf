from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.schemas.audiobook import (
    TTSPromptTestPreviewRequest,
    TTSPromptTestPreviewResponse,
    TTSPreviewRequest,
    TTSPreviewWithTimestampsRequest,
    TTSPreviewWithTimestampsResponse,
    CosyVoiceCloneCreateRequest,
    CosyVoiceDesignCreateRequest,
    MiMoVoiceCloneAssetCreateRequest,
    MiMoVoiceDesignAssetCreateRequest,
    StepAudioVoiceCloneAssetCreateRequest,
    VoiceReferenceMaterializeRequest,
)
from app.services.audiobook.constants import normalize_speaker_id
from app.services.audiobook.tts_engine import RetryConfig, TTSUserInputError
from app.services.audiobook.tts_model_ids import (
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    STEPAUDIO_3_TTS_MODEL,
    get_audiobook_tts_runtime_model_id,
    get_audiobook_tts_model_metadata,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.voice_types import apply_voice_type_to_tts_params
from app.services.audiobook.voice_identity_policy import (
    is_voice_design_creation_request,
    is_voice_design_model,
    sanitize_fixed_voice_performance_text,
    sanitize_fixed_voice_prompt_params,
)
from app.services.audiobook.voice_parameter_policy import (
    stabilize_fixed_voice_pitch,
    stabilize_instruct_model_speed,
)
from app.services.audiobook.voice_manager import VoiceManager
from app.services.audiobook.voice_catalog import get_preview_quote_for_voice, get_voice_entry, load_voice_catalog_for_model
from app.services.audiobook.mimo_voice_assets import (
    MiMoVoiceAssetError,
    MiMoVoiceAssetStore,
    list_mimo_voice_asset_presets,
    merge_mimo_voice_asset_tts_params,
)
from app.services.audiobook.stepaudio_voice_assets import (
    StepAudioVoiceAssetError,
    StepAudioVoiceAssetStore,
    get_stepaudio_api_key,
    list_stepaudio_voice_asset_presets,
    merge_stepaudio_voice_asset_tts_params,
    upload_stepaudio_voice_reference_file,
    validate_stepaudio_clone_audio_mime_type,
)
from app.services.audiobook.minimax_voice_clone_client import (
    MiniMaxVoiceCloneError,
    MiniMaxVoiceCloneStore,
    build_minimax_voice_clone_billing,
    create_minimax_voice_clone_from_bytes,
    list_minimax_voice_clone_presets,
)
from app.services.audiobook.tts_preview_cache import (
    _build_preview_cache_key,
    check_oss_preview_exists,
    upload_preview_to_oss,
)
from app.services.audiobook.voice_reference_asset_repository import (
    get_active_voice_reference_asset,
    persist_user_generated_voice_reference,
    revoke_voice_reference_asset,
)
from app.services.audiobook.voice_asset_billing_ledger_repository import (
    record_voice_billing_event,
)
from sqlalchemy.orm import Session
from app.services.audiobook.tts_test_unit import build_tts_test_catalog, get_tts_test_case
from app.services.audiobook.audio_asset_cloud_storage import get_audio_library_storage_driver
from app.services.audiobook.cosyvoice_clone_client import (
    COSYVOICE_V35_PLUS_MODEL_ID,
    CosyVoiceCloneError,
    create_cosyvoice_v3_plus_clone,
    create_cosyvoice_v3_plus_design,
    delete_cosyvoice_clone,
    get_clone_display_name,
    get_clone_owner_user_id,
    is_cosyvoice_v35_plus_voice_id,
    list_cosyvoice_v3_plus_clones,
    save_clone_display_name,
    upload_cosyvoice_v3_plus_clone_sample,
)
from core.unified_media_runtime import (
    create_tts_engine as runtime_create_tts_engine,
    get_media_runtime,
    synthesize_speech as runtime_synthesize_speech,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

DEFAULT_TTS_MODEL = DEFAULT_AUDIOBOOK_TTS_MODEL
DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT = "当你真的喜欢一个人的时候就容易说傻话办蠢事。"
DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION = "语气自然，语速中等，保持参考音色特征。"
DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT = (
    "清晨的风从窗外吹进来，我停下脚步，轻声说：别担心，我们会找到答案。"
)
VOICE_REFERENCE_PREVIEW_SCHEMA_VERSION = "voice-reference-preview-v1"

_PREVIEW_RETRY_CONFIG = RetryConfig(
    max_retries=4,
    base_delay=1.0,
    max_delay=8.0,
    exponential_base=2.0,
    jitter=True,
)


def _register_user_generated_voice_asset(
    *,
    db: Session | object,
    asset: object,
    owner_user_id: int,
    provider: str,
    source_model: str,
    source_voice_id: str,
    root_dir: Path,
) -> None:
    """将本地设计/复刻资产登记到私有参考资产表；登记失败不回滚已保存的本地资产。"""
    asset_type = str(getattr(asset, "asset_type", "") or "").strip().lower()
    relative_audio_path = str(getattr(asset, "audio_path", "") or "").strip()
    storage_path = (root_dir / relative_audio_path).resolve() if relative_audio_path else None
    storage_uri = str(storage_path) if storage_path and storage_path.exists() else None
    sha256 = None
    if storage_path and storage_path.exists():
        sha256 = hashlib.sha256(storage_path.read_bytes()).hexdigest()

    if not isinstance(db, Session):
        return
    try:
        persist_user_generated_voice_reference(
            db,
            owner_user_id=owner_user_id,
            provider=provider,
            source_model=source_model,
            source_voice_id=source_voice_id,
            authorization_basis="synthetic_design" if asset_type == "design" else "synthetic_source",
            storage_uri=storage_uri,
            sha256=sha256,
            content_type=str(getattr(asset, "mime_type", "") or "") or None,
            metadata={
                "local_asset_id": str(getattr(asset, "id", "") or ""),
                "display_name": str(getattr(asset, "name", "") or ""),
            },
        )
        db.commit()
    except Exception:  # pragma: no cover - 数据库不可用时不破坏音色创建结果
        logger.warning("登记用户音色参考资产失败", exc_info=True)
        db.rollback()


def _register_remote_user_generated_voice(
    *,
    db: Session | object,
    owner_user_id: int,
    provider: str,
    source_model: str,
    source_voice_id: str,
    authorization_basis: str,
    source_url: str = "",
    display_name: str = "",
) -> None:
    if not isinstance(db, Session):
        return
    try:
        persist_user_generated_voice_reference(
            db,
            owner_user_id=owner_user_id,
            provider=provider,
            source_model=source_model,
            source_voice_id=source_voice_id,
            authorization_basis=authorization_basis,
            storage_uri=source_url or None,
            source_url=source_url or None,
            metadata={"display_name": display_name},
        )
        db.commit()
    except Exception:  # pragma: no cover - 供应商成功结果不能被登记故障回滚
        logger.warning("登记远程用户音色参考资产失败", exc_info=True)
        db.rollback()


def _revoke_registered_user_voice(
    *,
    db: Session | object,
    owner_user_id: int,
    source_voice_id: str,
) -> None:
    if not isinstance(db, Session):
        return
    try:
        asset = (
            db.query(VoiceReferenceAsset)
            .filter(
                VoiceReferenceAsset.owner_user_id == owner_user_id,
                VoiceReferenceAsset.source_voice_id == source_voice_id,
                VoiceReferenceAsset.revoked_at.is_(None),
                VoiceReferenceAsset.deleted_at.is_(None),
            )
            .first()
        )
        if asset is None:
            return
        revoke_voice_reference_asset(
            db,
            asset_id=asset.asset_id,
            owner_user_id=owner_user_id,
            revoked_by_user_id=owner_user_id,
            reason="用户删除自定义音色",
        )
        db.commit()
    except Exception:  # pragma: no cover - 删除主流程不因审计回写失败而反转
        logger.warning("撤销用户参考音色登记失败", exc_info=True)
        db.rollback()


def _voice_reference_cost_quote(*, model: str, text: str) -> dict[str, object]:
    metadata = get_audiobook_tts_model_metadata(model)
    price_per_10k = float(metadata.get("price_per_10k") or 0.0)
    estimated_cost = round(price_per_10k * len(text) / 10000.0, 6)
    pricing_status = str(metadata.get("pricing_status") or "unknown")
    return {
        "model": model,
        "model_name": str(metadata.get("name") or model),
        "price_per_10k_yuan": price_per_10k,
        "estimated_cost_yuan": estimated_cost,
        "pricing_status": pricing_status,
        "pricing_basis": str(metadata.get("pricing_basis") or "public_list_price"),
        "billing_notice": (
            f"本次标准参考试听按公开后付费价 {price_per_10k:g} 元/万字符估算，"
            f"约 {estimated_cost:.6f} 元；缓存命中后不会重复生成。"
            if price_per_10k > 0
            else "当前模型公开价为限时免费；仍需确认后才会调用模型生成标准参考试听。"
        ),
    }


def _existing_voice_reference_uri(asset: object) -> str:
    uri = str(getattr(asset, "storage_uri", "") or "").strip()
    if not uri:
        return ""
    if uri.startswith(("http://", "https://", "oss://")):
        return uri
    path = Path(uri)
    return uri if path.exists() else ""


def _is_cosyvoice_v35_model(model: str) -> bool:
    return normalize_audiobook_tts_model(model) == COSYVOICE_V35_PLUS_MODEL_ID


def _validate_cosyvoice_v35_voice_id(voice_id: str) -> str:
    resolved = str(voice_id or "").strip()
    if is_cosyvoice_v35_plus_voice_id(resolved):
        return resolved

    entry = get_voice_entry(resolved, model=COSYVOICE_V35_PLUS_MODEL_ID)
    if entry:
        return str(entry.get("speaker") or resolved)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="cosyvoice-v3.5-plus 不提供系统音色，请先创建并选择复刻/设计音色",
    )


def _build_model_voice_catalog_status(model_name: str) -> tuple[int, str, str | None]:
    model_meta = get_audiobook_tts_model_metadata(model_name)
    capabilities = model_meta.get("capabilities") if isinstance(model_meta.get("capabilities"), dict) else {}
    if not capabilities.get("has_system_voices", True) and model_name != COSYVOICE_V35_PLUS_MODEL_ID:
        return 0, "not_applicable", None

    try:
        catalog = load_voice_catalog_for_model(model_name)
    except Exception as exc:
        logger.warning("加载 TTS 模型音色目录失败: model=%s error=%s", model_name, exc)
        return 0, "unavailable", "音色目录加载失败，请检查后端 voice catalog 配置"

    voices = catalog.get("voices", [])
    meta = catalog.get("meta", {})
    raw_voice_count = meta.get("voice_count")
    voice_count = raw_voice_count if isinstance(raw_voice_count, int) and raw_voice_count >= 0 else len(voices)
    if model_name == COSYVOICE_V35_PLUS_MODEL_ID:
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voice_count += len(clones)
        except CosyVoiceCloneError as exc:
            logger.info(
                "CosyVoice 自定义音色列表不可用，模型音色计数仅使用静态目录: model=%s error=%s",
                model_name,
                exc,
            )
    return voice_count, "ready", None


def _build_model_runtime_status(model_name: str) -> tuple[str, str, str | None]:
    runtime_model_id = get_audiobook_tts_runtime_model_id(model_name)
    if not runtime_model_id:
        return "", "unavailable", "TTS 运行时模型未配置"

    try:
        spec = get_media_runtime().select_model(
            operation="synthesize_speech",
            modality="text_to_speech",
            preferred_model=runtime_model_id,
        )
    except Exception as exc:
        logger.warning("TTS 运行时模型不可用: model=%s runtime_model=%s error=%s", model_name, runtime_model_id, exc)
        return runtime_model_id, "unavailable", "TTS 运行时模型未注册或不可用"

    if spec.id != runtime_model_id:
        logger.warning(
            "TTS 运行时模型被重路由: model=%s runtime_model=%s selected=%s",
            model_name,
            runtime_model_id,
            spec.id,
        )
        return runtime_model_id, "unavailable", f"TTS 运行时模型当前不可直用，已被路由到 {spec.id}"

    return runtime_model_id, "ready", None


def _build_cosyvoice_voice_prefix(display_name: str, current_user: User) -> str:
    import hashlib
    import re
    import secrets

    cleaned_name = (display_name or "").strip()
    if not cleaned_name:
        raise CosyVoiceCloneError("name 不能为空")

    slug = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned_name).strip("_").lower()
    base = (slug[:4] if slug else "v").strip("_") or "v"
    user_id = str(getattr(current_user, "id", "0"))
    digest = hashlib.sha256(f"{user_id}:{cleaned_name}".encode("utf-8")).hexdigest()[:6]
    suffix = secrets.token_hex(1)
    return f"{base}{digest}{suffix}"[:10]


def _require_stepaudio_clone_sample_text(sample_text: str) -> str:
    clean_sample_text = str(sample_text or "").strip()
    if not clean_sample_text:
        raise StepAudioVoiceAssetError(
            "sample_text cannot be empty; it must match the exact spoken content in the reference audio"
        )
    return clean_sample_text


async def _resolve_stepaudio_clone_file_id(
    *,
    file_id: str,
    filename: str,
    content: bytes,
    mime_type: str,
) -> str:
    resolved_file_id = str(file_id or "").strip()
    if resolved_file_id:
        return resolved_file_id

    stepaudio_api_key = get_stepaudio_api_key()
    if not stepaudio_api_key:
        raise StepAudioVoiceAssetError(
            "STEP_API_KEY or STEPFUN_API_KEY is required before StepAudio clone preview or save"
        )
    return await upload_stepaudio_voice_reference_file(
        filename=filename or "stepaudio-reference.wav",
        content=content,
        mime_type=mime_type,
        api_key=stepaudio_api_key,
    )


def _resolve_preview_text(request: TTSPreviewRequest, model_name: str) -> str:
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本不能为空")
    if len(text) > 200:
        text = text[:200]
    # 当用户传入默认试听文本时，按音色从名言列表选取对应文本，保证与 warmup 缓存键一致
    if text == DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT:
        text = get_preview_quote_for_voice(model_name, request.voice_id)
    return text


def _resolve_preview_model_name(request: TTSPreviewRequest) -> str:
    return normalize_audiobook_tts_model(request.model or DEFAULT_TTS_MODEL)


def _resolve_speaker_for_voice_id(voice_id: str, model_name: str) -> str:
    """按模型把音色 ID 解析为 provider 侧 speaker。

    音色目录命中时直接用目录 speaker；未命中且模型是当前默认 Qwen 时，
    兼容历史别名（male_narrator 等）与旧 CosyVoice speaker 写法。
    """
    entry = get_voice_entry(voice_id, model=model_name)
    if (
        entry is None
        and normalize_audiobook_tts_model(model_name, default="") == DEFAULT_AUDIOBOOK_TTS_MODEL
    ):
        preset = VoiceManager.PRESET_VOICES.get(voice_id)
        return normalize_speaker_id(preset["tts_speaker_id"] if preset else voice_id)

    speaker_id = str((entry or {}).get("speaker") or voice_id)
    if _is_cosyvoice_v35_model(model_name):
        speaker_id = _validate_cosyvoice_v35_voice_id(speaker_id)
    return speaker_id


def _resolve_preview_speaker_id(request: TTSPreviewRequest, model_name: str) -> str:
    return _resolve_speaker_for_voice_id(request.voice_id, model_name)


def _build_preview_voice_params(
    request: TTSPreviewRequest,
    speaker_id: str,
    *,
    model_name: str | None = None,
    owner_user_id: int | None = None,
) -> dict:
    resolved_model = normalize_audiobook_tts_model(
        model_name or request.model or DEFAULT_TTS_MODEL
    )
    voice_design = is_voice_design_model(resolved_model)
    request_voice_id = str(getattr(request, "voice_id", "") or "").strip()
    mimo_voice_asset_id = str(getattr(request, "mimo_voice_asset_id", "") or "").strip()
    voice_design_creation = is_voice_design_creation_request(
        resolved_model,
        {
            "speaker": speaker_id,
            "voice_id": request_voice_id,
            "mimo_voice_asset_id": mimo_voice_asset_id,
        },
    )
    base_params = {
        "volume": request.volume,
        "speed": request.speed,
    }
    voice_type = str(request.voice_type or "").strip()
    if voice_design_creation:
        base_params["pitch"] = request.pitch
    if voice_design_creation and voice_type:
        base_params = apply_voice_type_to_tts_params(
            voice_type,
            {
                "volume": request.volume,
                "speed": request.speed if request.speed is not None else 1.0,
                "pitch": request.pitch if request.pitch is not None else 50,
            },
        )

    voice_params: dict = {
        "speaker": speaker_id,
        "volume": base_params.get("volume"),
    }
    if request_voice_id:
        voice_params["voice_id"] = request_voice_id
    if base_params.get("speed") is not None:
        voice_params["rate"] = base_params["speed"]
        voice_params["speed"] = base_params["speed"]
    if voice_design_creation and base_params.get("pitch") is not None:
        voice_params["pitch"] = base_params["pitch"]
    if base_params.get("emotion"):
        voice_params["emotion"] = base_params["emotion"]

    instruction = str(getattr(request, "instruction", "") or "").strip()
    if instruction:
        voice_params["instruction"] = instruction

    voice_clone_data_url = str(getattr(request, "voice_clone_data_url", "") or "").strip()
    if voice_clone_data_url:
        voice_params["voice_clone_data_url"] = voice_clone_data_url

    voice_design_prompt = str(getattr(request, "voice_design_prompt", "") or "").strip()
    if voice_design_creation and voice_design_prompt:
        voice_params["voice_design_prompt"] = voice_design_prompt

    if not mimo_voice_asset_id and (
        request_voice_id.startswith("mimo_clone:")
        or request_voice_id.startswith("mimo_design:")
        or str(speaker_id or "").startswith("mimo_clone:")
        or str(speaker_id or "").startswith("mimo_design:")
    ):
        mimo_voice_asset_id = request_voice_id or str(speaker_id or "")
    if mimo_voice_asset_id:
        voice_params["mimo_voice_asset_id"] = mimo_voice_asset_id
        try:
            voice_params = merge_mimo_voice_asset_tts_params(
                voice_params,
                owner_user_id=owner_user_id,
            )
        except MiMoVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stepaudio_voice_asset_id = str(getattr(request, "stepaudio_voice_asset_id", "") or "").strip()
    if not stepaudio_voice_asset_id and (
        request_voice_id.startswith("stepaudio_clone:")
        or str(speaker_id or "").startswith("stepaudio_clone:")
    ):
        stepaudio_voice_asset_id = request_voice_id or str(speaker_id or "")
    if stepaudio_voice_asset_id:
        voice_params["stepaudio_voice_asset_id"] = stepaudio_voice_asset_id
        try:
            voice_params = merge_stepaudio_voice_asset_tts_params(
                voice_params,
                owner_user_id=owner_user_id,
            )
        except StepAudioVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if getattr(request, "word_timestamp_enabled", False):
        voice_params["word_timestamp_enabled"] = True
    if getattr(request, "phoneme_timestamp_enabled", False):
        voice_params["phoneme_timestamp_enabled"] = True

    voice_design_creation = is_voice_design_creation_request(
        resolved_model,
        voice_params,
    )
    if not voice_design_creation:
        voice_params, _ = sanitize_fixed_voice_prompt_params(voice_params)
        voice_params = stabilize_fixed_voice_pitch(voice_params)
        for derived_identity_field in (
            "voice_description",
            "provider_prompt",
            "provider_prompt_snapshot",
        ):
            voice_params.pop(derived_identity_field, None)
        if not voice_design:
            voice_params.pop("voice_design_prompt", None)

    voice_params = stabilize_instruct_model_speed(voice_params, resolved_model)

    return voice_params


async def _synthesize_preview_payload(
    *,
    text: str,
    model_name: str,
    voice_params: dict,
    retry_config: RetryConfig,
) -> dict:
    engine = runtime_create_tts_engine(
        model_id=model_name,
        strategy="balanced",
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=retry_config,
    )
    emotion = str(voice_params.get("emotion") or "neutral")
    payload = await engine.synthesize_with_metadata(text, voice_params, emotion)
    if not isinstance(payload, dict):
        raise RuntimeError("TTS 试听未返回有效 payload")
    return payload


def _build_prompt_test_voice_params(
    request: TTSPromptTestPreviewRequest,
    test_case: dict,
    *,
    owner_user_id: int | None = None,
) -> tuple[str, dict]:
    model_name = str(test_case["model"])
    voice_id = str(request.voice_id or "").strip()
    if not voice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择测试音色",
        )

    speaker_id = _resolve_speaker_for_voice_id(voice_id, model_name)

    voice_params = dict(test_case["voice_params"])
    voice_params.update({"speaker": speaker_id, "voice_id": voice_id})

    for field_name in ("voice_clone_data_url", "voice_design_prompt"):
        value = str(getattr(request, field_name, "") or "").strip()
        if value:
            voice_params[field_name] = value

    mimo_asset_id = str(request.mimo_voice_asset_id or "").strip()
    if not mimo_asset_id and voice_id.startswith(("mimo_clone:", "mimo_design:")):
        mimo_asset_id = voice_id
    if mimo_asset_id:
        voice_params["mimo_voice_asset_id"] = mimo_asset_id
        try:
            voice_params = merge_mimo_voice_asset_tts_params(
                voice_params,
                owner_user_id=owner_user_id,
            )
        except MiMoVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stepaudio_asset_id = str(request.stepaudio_voice_asset_id or "").strip()
    if not stepaudio_asset_id and voice_id.startswith("stepaudio_clone:"):
        stepaudio_asset_id = voice_id
    if stepaudio_asset_id:
        voice_params["stepaudio_voice_asset_id"] = stepaudio_asset_id
        try:
            voice_params = merge_stepaudio_voice_asset_tts_params(
                voice_params,
                owner_user_id=owner_user_id,
            )
        except StepAudioVoiceAssetError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    voice_design_creation = is_voice_design_creation_request(model_name, voice_params)
    if voice_design_creation:
        # The explicit creation test consumes exactly the snapshot shown by the page.
        voice_params["provider_prompt_snapshot"] = test_case["provider_prompt_snapshot"]
    else:
        voice_params, _ = sanitize_fixed_voice_prompt_params(voice_params)
        voice_params = stabilize_fixed_voice_pitch(voice_params)
        voice_params.pop("voice_description", None)
        voice_params.pop("provider_prompt", None)
        voice_params.pop("provider_prompt_snapshot", None)
        if not is_voice_design_model(model_name):
            voice_params.pop("voice_design_prompt", None)
    voice_params = stabilize_instruct_model_speed(voice_params, model_name)
    return voice_id, voice_params


@router.get("/tts/test-cases")
async def list_tts_prompt_test_cases(
    current_user: User = Depends(get_current_user),
):
    """Return model-specific prompt cases without project or chapter context."""
    return {"models": build_tts_test_catalog()}


@router.post("/tts/test-preview", response_model=TTSPromptTestPreviewResponse)
async def preview_tts_prompt_test_case(
    request: TTSPromptTestPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Synthesize an independent case under the current voice-identity policy.

    Explicit new-voice creation may reuse the server-built displayed snapshot.
    Fixed voices discard it and rebuild at the engine boundary so stale prompt
    data cannot bypass identity sanitization.
    """
    try:
        test_case = get_tts_test_case(request.model, request.case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    voice_id, voice_params = _build_prompt_test_voice_params(
        request,
        test_case,
        owner_user_id=int(current_user.id),
    )
    try:
        payload = await _synthesize_preview_payload(
            text=str(test_case["text"]),
            model_name=str(test_case["model"]),
            voice_params=voice_params,
            retry_config=_PREVIEW_RETRY_CONFIG,
        )
    except TTSUserInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("独立 TTS 提示词测试试听失败: model=%s case=%s error=%s", request.model, request.case_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS 服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc

    audio_bytes = payload.get("audio_bytes")
    if isinstance(audio_bytes, bytearray):
        audio_bytes = bytes(audio_bytes)
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS 服务未返回有效音频", "retryable": True},
        )

    audio_format = str(payload.get("format") or ("wav" if audio_bytes.startswith(b"RIFF") else "mp3")).lower()
    audio_mime_type = "audio/wav" if audio_format in {"wav", "pcm", "pcm16"} else "audio/mpeg"
    return TTSPromptTestPreviewResponse(
        model=str(test_case["model"]),
        case_id=str(test_case["id"]),
        text=str(test_case["text"]),
        voice_id=voice_id,
        style_control_mode=str(test_case["style_control_mode"]),
        provider_prompt_snapshot=test_case["provider_prompt_snapshot"],
        audio_data_base64=base64.b64encode(audio_bytes).decode("ascii"),
        audio_format=audio_format,
        audio_mime_type=audio_mime_type,
        audio_size_bytes=len(audio_bytes),
        provider=payload.get("provider"),
        provider_model=payload.get("provider_model"),
        transport=payload.get("transport"),
    )


@router.post("/tts/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """合成一小段音频用于前端试听"""
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    preview_retry = _PREVIEW_RETRY_CONFIG
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(
        request,
        speaker_id,
        model_name=model_name,
        owner_user_id=int(current_user.id),
    )

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except TTSUserInputError as exc:
        logger.info("TTS试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
    except Exception as exc:
        logger.warning("TTS试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    media_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)


@router.post("/tts/preview-cached")
async def tts_preview_cached(
    request: TTSPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """试听接口 (带云端 OSS 缓存，无 Redis 依赖)。

    缓存命中 → 302 重定向到 CDN URL。
    缓存未命中 → TTS 合成 → 上传 OSS → 302 重定向。
    云端未配置 → 降级返回原始音频 blob。
    """
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(
        request,
        speaker_id,
        model_name=model_name,
        owner_user_id=int(current_user.id),
    )

    # 构建缓存键
    voice_design = is_voice_design_creation_request(model_name, voice_params)
    cache_key = _build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=text,
        volume=int(request.volume),
        speed=float(voice_params.get("speed") or voice_params.get("rate") or 1.0),
        pitch=int(request.pitch or 50) if voice_design else 50,
        emotion=str(voice_params.get("emotion") or "neutral"),
        voice_type=str(request.voice_type or "") if voice_design else "",
        mimo_voice_asset_id=str(getattr(request, "mimo_voice_asset_id", "") or ""),
        stepaudio_voice_asset_id=str(getattr(request, "stepaudio_voice_asset_id", "") or ""),
        voice_params=voice_params,
    )

    # 检查 OSS 是否已有缓存文件
    cached_url = check_oss_preview_exists(cache_key, ext="mp3")
    cached_format = "mp3"
    if not cached_url:
        cached_url = check_oss_preview_exists(cache_key, ext="wav")
        cached_format = "wav"
    if cached_url:
        logger.info("TTS 试听 OSS 缓存命中: %s", cache_key[:12])
        return {
            "audio_url": cached_url,
            "blob": None,
            "cache_hit": True,
            "storage": "oss",
            "response_format": cached_format,
        }

    logger.info(
        "TTS preview cache miss: key=%s model=%s voice_id=%s speaker=%s driver=%s",
        cache_key[:12],
        model_name,
        str(getattr(request, "voice_id", "") or "").strip(),
        speaker_id,
        get_audio_library_storage_driver(),
    )

    # 未命中: TTS 合成
    preview_retry = _PREVIEW_RETRY_CONFIG
    try:
        audio_bytes = await runtime_synthesize_speech(
            text=text,
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=preview_retry,
        )
    except TTSUserInputError as exc:
        logger.info("TTS试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
    except Exception as exc:
        logger.warning("TTS试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc

    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    response_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    cloud_url = upload_preview_to_oss(
        audio_bytes=audio_bytes,
        cache_key=cache_key,
        response_format=response_format,
    )

    if cloud_url:
        return {
            "audio_url": cloud_url,
            "blob": None,
            "cache_hit": False,
            "storage": "oss",
            "response_format": response_format,
        }

    # 云端未配置
    return {
        "audio_url": None,
        "blob": base64.b64encode(audio_bytes).decode("utf-8"),
        "cache_hit": False,
        "storage": "blob",
        "response_format": response_format,
    }


@router.post("/tts/voice-references/materialize")
async def materialize_voice_reference_preview(
    request: VoiceReferenceMaterializeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前用户私有音色生成一次标准参考试听，并写入可复用缓存。"""
    asset = get_active_voice_reference_asset(
        db,
        asset_id=request.source_asset_id,
        owner_user_id=int(current_user.id),
    )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音色参考资产不存在、已撤销或不属于当前用户",
        )

    existing_uri = _existing_voice_reference_uri(asset)
    if (
        existing_uri
        and str((asset.metadata_json or {}).get("preview_schema_version") or "")
        == VOICE_REFERENCE_PREVIEW_SCHEMA_VERSION
    ):
        return {
            "source_asset_id": asset.asset_id,
            "reference_audio_uri": existing_uri,
            "cache_hit": True,
            "requires_cost_confirmation": False,
            "generated": False,
        }

    model_name = normalize_audiobook_tts_model(asset.source_model or "", default="")
    source_voice_id = str(asset.source_voice_id or "").strip()
    if not model_name or not source_voice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="音色缺少 source_model 或 source_voice_id，无法生成标准参考试听",
        )

    preview_request = TTSPreviewRequest(
        text=DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
        voice_id=source_voice_id,
        model=model_name,
        volume=50,
        speed=1.0,
        pitch=50,
    )
    speaker_id = _resolve_preview_speaker_id(preview_request, model_name)
    voice_params = _build_preview_voice_params(
        preview_request,
        speaker_id,
        model_name=model_name,
        owner_user_id=int(current_user.id),
    )
    cache_key = _build_preview_cache_key(
        model=model_name,
        voice_id=speaker_id,
        text=DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
        volume=50,
        speed=1.0,
        pitch=50,
        emotion=str(voice_params.get("emotion") or "neutral"),
        voice_params=voice_params,
    )

    cached_format = "mp3"
    cached_url = check_oss_preview_exists(cache_key, ext=cached_format)
    if not cached_url:
        cached_format = "wav"
        cached_url = check_oss_preview_exists(cache_key, ext=cached_format)
    if cached_url:
        asset.reference_field = "audio_url"
        asset.source_preview_cache_key = cache_key
        asset.storage_uri = cached_url
        asset.source_url = cached_url
        asset.content_type = "audio/wav" if cached_format == "wav" else "audio/mpeg"
        asset.metadata_json = {
            **dict(asset.metadata_json or {}),
            "preview_schema_version": VOICE_REFERENCE_PREVIEW_SCHEMA_VERSION,
            "preview_text": DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
        }
        db.commit()
        return {
            "source_asset_id": asset.asset_id,
            "reference_audio_uri": cached_url,
            "cache_hit": True,
            "requires_cost_confirmation": False,
            "generated": False,
        }

    quote = _voice_reference_cost_quote(
        model=model_name,
        text=DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
    )
    if not request.confirm_cost:
        return {
            "source_asset_id": asset.asset_id,
            "reference_audio_uri": None,
            "cache_hit": False,
            "requires_cost_confirmation": True,
            "generated": False,
            "preview_text": DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
            "cost_quote": quote,
        }

    try:
        audio_bytes = await runtime_synthesize_speech(
            text=DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
            voice_params=voice_params,
            emotion=str(voice_params.get("emotion") or "neutral"),
            model_id=model_name,
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=_PREVIEW_RETRY_CONFIG,
        )
    except TTSUserInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": str(exc),
                "code": getattr(exc, "code", "tts_user_input_error"),
                "retryable": False,
            },
        ) from exc
    except Exception as exc:
        logger.warning("生成标准参考试听失败: asset=%s", asset.asset_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "标准参考试听生成失败，请稍后重试", "retryable": True},
        ) from exc
    if not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "模型未返回标准参考试听", "retryable": True},
        )

    response_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    content_type = "audio/wav" if response_format == "wav" else "audio/mpeg"
    reference_uri = upload_preview_to_oss(
        audio_bytes=audio_bytes,
        cache_key=cache_key,
        response_format=response_format,
    )
    storage_kind = "oss"
    if not reference_uri:
        output_dir = Path("backend/data/voice_references") / f"user_{int(current_user.id)}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{asset.asset_id}.{response_format}"
        output_path.write_bytes(audio_bytes)
        reference_uri = str(output_path.resolve())
        storage_kind = "local_private"

    asset.reference_field = "audio_url" if reference_uri.startswith(("http://", "https://")) else "audio_data"
    asset.source_preview_cache_key = cache_key
    asset.storage_uri = reference_uri
    asset.source_url = reference_uri if reference_uri.startswith(("http://", "https://")) else None
    asset.sha256 = hashlib.sha256(audio_bytes).hexdigest()
    asset.file_size = len(audio_bytes)
    asset.content_type = content_type
    asset.metadata_json = {
        **dict(asset.metadata_json or {}),
        "preview_schema_version": VOICE_REFERENCE_PREVIEW_SCHEMA_VERSION,
        "preview_text": DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
        "storage_kind": storage_kind,
    }
    record_voice_billing_event(
        db,
        provider=str(asset.provider or "tts"),
        event_type="preview",
        model=model_name,
        voice_id=source_voice_id,
        owner_user_id=int(current_user.id),
        voice_asset_id=asset.asset_id,
        billable=float(quote["price_per_10k_yuan"]) > 0,
        fixed_fee_yuan=float(quote["estimated_cost_yuan"]),
        metadata={
            "pricing_basis": quote["pricing_basis"],
            "preview_schema_version": VOICE_REFERENCE_PREVIEW_SCHEMA_VERSION,
        },
    )
    db.commit()
    return {
        "source_asset_id": asset.asset_id,
        "reference_audio_uri": reference_uri,
        "cache_hit": False,
        "requires_cost_confirmation": False,
        "generated": True,
        "preview_text": DEFAULT_VOICE_REFERENCE_PREVIEW_TEXT,
        "cost_quote": quote,
    }


@router.post("/tts/preview-with-timestamps", response_model=TTSPreviewWithTimestampsResponse)
async def tts_preview_with_timestamps(
    request: TTSPreviewWithTimestampsRequest,
    current_user: User = Depends(get_current_user),
):
    """合成短音频并返回可消费的词级时间戳。当前仅支持 CosyVoice v3.5 Plus。"""
    model_name = _resolve_preview_model_name(request)
    text = _resolve_preview_text(request, model_name)
    if not _is_cosyvoice_v35_model(model_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前时间戳试听接口仅支持 cosyvoice-v3.5-plus",
        )

    preview_retry = _PREVIEW_RETRY_CONFIG
    speaker_id = _resolve_preview_speaker_id(request, model_name)
    voice_params = _build_preview_voice_params(
        request,
        speaker_id,
        model_name=model_name,
        owner_user_id=int(current_user.id),
    )

    try:
        payload = await _synthesize_preview_payload(
            text=text,
            model_name=model_name,
            voice_params=voice_params,
            retry_config=preview_retry,
        )
    except Exception as exc:
        logger.warning("带时间戳的 TTS 试听失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        ) from exc

    audio_bytes = payload.get("audio_bytes")
    if isinstance(audio_bytes, bytearray):
        audio_bytes = bytes(audio_bytes)
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "TTS服务暂时不可用，请稍后重试", "retryable": True},
        )

    audio_format = str(payload.get("format") or ("wav" if audio_bytes.startswith(b"RIFF") else "mp3")).strip().lower()
    audio_mime_type = "audio/wav" if audio_format == "wav" or audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    tts_timestamps = payload.get("tts_timestamps") if isinstance(payload.get("tts_timestamps"), list) else []
    tts_timestamp_sentences = (
        payload.get("tts_timestamp_sentences")
        if isinstance(payload.get("tts_timestamp_sentences"), list)
        else []
    )
    phoneme_timestamps = payload.get("phoneme_timestamps") if isinstance(payload.get("phoneme_timestamps"), list) else []

    return TTSPreviewWithTimestampsResponse(
        model=model_name,
        voice_id=speaker_id,
        audio_data_base64=base64.b64encode(audio_bytes).decode("utf-8"),
        audio_format=audio_format,
        audio_mime_type=audio_mime_type,
        audio_size_bytes=len(audio_bytes),
        provider=str(payload.get("provider") or "") or None,
        provider_model=str(payload.get("provider_model") or "") or None,
        transport=str(payload.get("transport") or "") or None,
        word_timestamp_enabled=bool(payload.get("word_timestamp_enabled")),
        phoneme_timestamp_enabled=bool(payload.get("phoneme_timestamp_enabled")),
        word_timestamps_available=bool(tts_timestamps),
        phoneme_timestamps_available=bool(phoneme_timestamps),
        tts_timestamps=tts_timestamps,
        tts_timestamp_sentences=tts_timestamp_sentences,
        phoneme_timestamps=phoneme_timestamps,
    )


@router.get("/tts/models")
async def list_tts_models(
    current_user: User = Depends(get_current_user),
):
    """列出所有支持的 TTS 模型及其基本信息"""
    from app.services.audiobook.voice_manager_factory import list_all_models
    
    models = []
    for model_name in list_all_models():
        model_meta = get_audiobook_tts_model_metadata(model_name)
        voice_count, catalog_status, catalog_error = _build_model_voice_catalog_status(model_name)
        runtime_model_id, runtime_status, runtime_error = _build_model_runtime_status(model_name)
        models.append({
            "id": model_name,
            "name": _get_model_display_name(model_name),
            "description": _get_model_description(model_name, voice_count),
            "voice_count": voice_count,
            "price_per_10k": _get_model_price(model_name),
            "features": _get_model_features(model_name, voice_count),
            "cost_level": model_meta.get("cost_level"),
            "quality_level": model_meta.get("quality_level"),
            "catalog_note": model_meta.get("catalog_note"),
            "capabilities": model_meta.get("capabilities") or {},
            "catalog_status": catalog_status,
            "catalog_error": catalog_error,
            "runtime_model_id": runtime_model_id,
            "runtime_status": runtime_status,
            "runtime_error": runtime_error,
        })
    
    return {"models": models}


def _get_model_display_name(model: str) -> str:
    return str(get_audiobook_tts_model_metadata(model).get("name") or model)


def _get_model_description(model: str, voice_count: int = 0) -> str:
    template = str(get_audiobook_tts_model_metadata(model).get("description") or "")
    return template.format(voice_count=voice_count) if template else ""


def _get_model_price(model: str) -> float:
    try:
        return float(get_audiobook_tts_model_metadata(model).get("price_per_10k", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _get_model_features(model: str, voice_count: int = 0) -> list:
    raw_features = get_audiobook_tts_model_metadata(model).get("features") or []
    return [str(feature).format(voice_count=voice_count) for feature in raw_features]


@router.get("/tts/voices")
async def list_tts_voices(
    model: str = DEFAULT_TTS_MODEL,
    current_user: User = Depends(get_current_user),
):
    """Expose the supported voices to the frontend (model-specific)."""
    model = normalize_audiobook_tts_model(model or DEFAULT_TTS_MODEL)
    catalog = load_voice_catalog_for_model(model)
    meta = catalog.get("meta") or {}
    voices = list(catalog.get("voices") or [])
    owner_user_id = getattr(current_user, "id", None)

    # cosyvoice-v3.5-plus：官方静态目录为空，仅追加当前账号下的复刻/设计音色。
    if model == COSYVOICE_V35_PLUS_MODEL_ID:
        try:
            clones, _clone_meta = list_cosyvoice_v3_plus_clones()
            voices.extend(
                [
                    c.to_voice_preset(get_clone_display_name(c.voice_id))
                    for c in clones
                    if owner_user_id is not None
                    and get_clone_owner_user_id(c.voice_id) == int(owner_user_id)
                ]
            )
        except CosyVoiceCloneError as exc:
            # 未配置 API Key 等情况下，不阻塞页面继续使用其他模型
            logger.info(
                "CosyVoice 自定义音色列表不可用，返回静态音色目录: model=%s error=%s",
                model,
                exc,
            )
    else:
        if (
            owner_user_id is not None
            and model in {MINIMAX_SPEECH_28_HD_MODEL, MINIMAX_SPEECH_28_TURBO_MODEL}
        ):
            voices.extend(
                list_minimax_voice_clone_presets(
                    owner_user_id=str(owner_user_id),
                    model=model,
                )
            )
        if owner_user_id is not None:
            voices.extend(
                list_mimo_voice_asset_presets(model, owner_user_id=int(owner_user_id))
            )
            voices.extend(
                list_stepaudio_voice_asset_presets(model, owner_user_id=int(owner_user_id))
            )
    return {
        "model": meta.get("model", DEFAULT_TTS_MODEL),
        "updated_at": meta.get("updated_at"),
        "source": meta.get("source"),
        "voice_count": len(voices),
        "voices": voices,
    }


@router.get("/tts/voices/minimax/clones")
async def list_minimax_voice_clones(
    model: str = MINIMAX_SPEECH_28_HD_MODEL,
    current_user: User = Depends(get_current_user),
):
    """列出当前用户在本系统登记的 MiniMax 复刻音色。"""
    try:
        clones = MiniMaxVoiceCloneStore().list(
            owner_user_id=str(current_user.id),
            model=model,
        )
        return {
            "clones": [clone.to_dict() for clone in clones],
            "voices": [clone.to_voice_preset() for clone in clones],
            "total": len(clones),
            **build_minimax_voice_clone_billing(model),
        }
    except MiniMaxVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/minimax/clones/upload")
async def create_minimax_voice_clone_from_upload(
    file: UploadFile = File(...),
    name: str = Form(...),
    sample_text: str = Form(...),
    model: str = Form(MINIMAX_SPEECH_28_HD_MODEL),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传授权样本并通过阿里云百炼创建真实 MiniMax 复刻音色。"""
    try:
        content = await file.read()
        result = await run_in_threadpool(
            create_minimax_voice_clone_from_bytes,
            owner_user_id=str(current_user.id),
            model=model,
            name=name,
            sample_text=sample_text,
            filename=file.filename or "minimax-reference.wav",
            content=content,
            content_type=file.content_type or "",
        )
        clone = result["clone"]
        preview_audio = bytes(result.get("preview_audio_bytes") or b"")
        _register_remote_user_generated_voice(
            db=db,
            owner_user_id=int(current_user.id),
            provider="minimax",
            source_model=clone.model,
            source_voice_id=clone.voice_id,
            authorization_basis="synthetic_source",
            source_url=str(result.get("preview_audio_url") or ""),
            display_name=clone.name,
        )
        return {
            "clone": clone.to_dict(),
            "voice": clone.to_voice_preset(),
            "voice_id": clone.voice_id,
            "provider_request_id": clone.provider_request_id,
            "preview_audio_data_base64": base64.b64encode(preview_audio).decode("ascii") if preview_audio else "",
            "preview_audio_url": str(result.get("preview_audio_url") or ""),
            "preview_audio_mime_type": "audio/mpeg",
            **build_minimax_voice_clone_billing(model),
        }
    except MiniMaxVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 MiniMax 复刻上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.delete("/tts/voices/minimax/clones/{voice_id}")
async def remove_minimax_voice_clone_from_local_catalog(
    voice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """仅从本系统用户音色目录移除；不会删除百炼账号中的云端音色。"""
    try:
        removed = MiniMaxVoiceCloneStore().remove(
            owner_user_id=str(current_user.id),
            voice_id=voice_id,
        )
        if not removed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MiniMax 复刻音色不存在")
        _revoke_registered_user_voice(
            db=db,
            owner_user_id=int(current_user.id),
            source_voice_id=voice_id,
        )
        return {
            "removed": True,
            "voice_id": voice_id,
            "provider_deleted": False,
            "message": "已从本系统音色目录移除，百炼账号中的云端音色未删除。",
        }
    except MiniMaxVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3.5-plus/clones")
async def create_cosyvoice_v3_plus_voice_clone(
    request: CosyVoiceCloneCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建 cosyvoice-v3.5-plus 复刻音色。

    说明：DashScope 克隆接口要求 input.url 为公网可访问地址或 oss:// 临时 URL。
    """
    try:
        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip() or _build_cosyvoice_voice_prefix(display_name, current_user)
        result = create_cosyvoice_v3_plus_clone(prefix=prefix, audio_url=request.url)
        save_clone_display_name(
            voice_id=result.get("voice_id", ""),
            display_name=display_name,
            owner_user_id=int(current_user.id),
        )
        _register_remote_user_generated_voice(
            db=db,
            owner_user_id=int(current_user.id),
            provider="cosyvoice",
            source_model=COSYVOICE_V35_PLUS_MODEL_ID,
            source_voice_id=str(result.get("voice_id") or ""),
            authorization_basis="synthetic_source",
            display_name=display_name,
        )
        result["display_name"] = display_name
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3.5-plus/designs")
async def create_cosyvoice_v3_plus_voice_design(
    request: CosyVoiceDesignCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        display_name = (request.name or "").strip()
        if not display_name:
            raise CosyVoiceCloneError("name 不能为空")

        prefix = (request.prefix or "").strip() or _build_cosyvoice_voice_prefix(display_name, current_user)
        result = create_cosyvoice_v3_plus_design(
            prefix=prefix,
            voice_prompt=request.voice_prompt,
            preview_text=request.preview_text,
            sample_rate=int(request.sample_rate or 24000),
            response_format=str(request.response_format or "wav"),
        )
        save_clone_display_name(
            voice_id=result.get("voice_id", ""),
            display_name=display_name,
            owner_user_id=int(current_user.id),
        )
        _register_remote_user_generated_voice(
            db=db,
            owner_user_id=int(current_user.id),
            provider="cosyvoice",
            source_model=COSYVOICE_V35_PLUS_MODEL_ID,
            source_voice_id=str(result.get("voice_id") or ""),
            authorization_basis="synthetic_design",
            source_url=str(result.get("preview_audio") or result.get("preview_audio_url") or ""),
            display_name=display_name,
        )
        result["display_name"] = display_name
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/cosyvoice-v3.5-plus/clones/upload")
async def upload_cosyvoice_v3_plus_clone_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传本地音频，生成临时 oss:// URL。"""
    try:
        content = await file.read()
        if not content:
            raise CosyVoiceCloneError("file 不能为空")
        return upload_cosyvoice_v3_plus_clone_sample(
            filename=file.filename or "audio",
            content=content,
            content_type=file.content_type,
        )
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 CosyVoice 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.get("/tts/voices/cosyvoice-v3.5-plus/clones")
async def list_cosyvoice_v3_plus_voice_clones(
    prefix: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 cosyvoice-v3.5-plus 的复刻音色（当前 API Key 维度）。"""
    try:
        clones, meta = list_cosyvoice_v3_plus_clones(prefix=prefix)
        return {
            "meta": meta,
            "voices": [
                {
                    "voice_id": c.voice_id,
                    "status": c.status,
                    "gmt_create": c.gmt_create,
                    "gmt_modified": c.gmt_modified,
                    "custom_type": c.custom_type,
                    "voice_prompt": c.voice_prompt,
                    "preview_text": c.preview_text,
                    "preview_audio": c.preview_audio,
                    "display_name": get_clone_display_name(c.voice_id),
                }
                for c in clones
                if get_clone_owner_user_id(c.voice_id) == int(current_user.id)
            ],
        }
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/cosyvoice-v3.5-plus/clones/{voice_id}")
async def delete_cosyvoice_v3_plus_voice_clone(
    voice_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除 cosyvoice-v3.5-plus 复刻音色。"""
    owner_user_id = get_clone_owner_user_id(voice_id)
    if owner_user_id != int(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能删除其他用户或未确认归属的 CosyVoice 音色",
        )
    try:
        result = delete_cosyvoice_clone(voice_id=voice_id)
        _revoke_registered_user_voice(
            db=db,
            owner_user_id=int(current_user.id),
            source_voice_id=voice_id,
        )
        return result
    except CosyVoiceCloneError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/tts/voices/mimo/assets")
async def list_mimo_voice_assets(
    model: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 MiMo 本地可复用音色资产。"""
    try:
        assets = MiMoVoiceAssetStore().list_assets(
            model=model,
            owner_user_id=int(current_user.id),
        )
        return {
            "assets": [asset.to_dict() for asset in assets],
            "voices": [asset.to_voice_preset() for asset in assets],
            "total": len(assets),
        }
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/mimo/clone-assets")
async def create_mimo_voice_clone_asset(
    request: MiMoVoiceCloneAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存 MiMo Voice Clone 本地音频样本资产。"""
    try:
        asset = MiMoVoiceAssetStore().create_clone_asset(
            name=request.name,
            audio_data_url=request.audio_data_url,
            description=request.description or "",
            owner_user_id=int(current_user.id),
        )
        _register_user_generated_voice_asset(
            db=db,
            asset=asset,
            owner_user_id=int(current_user.id),
            provider="mimo",
            source_model=asset.model,
            source_voice_id=f"mimo_clone:{asset.id}",
            root_dir=MiMoVoiceAssetStore().root_dir,
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/mimo/clone-assets/upload")
async def upload_mimo_voice_clone_asset(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传本地音频并保存为 MiMo Voice Clone 本地音色资产。"""
    try:
        content = await file.read()
        asset = MiMoVoiceAssetStore().create_clone_asset_from_bytes(
            name=name,
            audio_bytes=content,
            mime_type=file.content_type or "",
            owner_user_id=int(current_user.id),
        )
        _register_user_generated_voice_asset(
            db=db,
            asset=asset,
            owner_user_id=int(current_user.id),
            provider="mimo",
            source_model=asset.model,
            source_voice_id=f"mimo_clone:{asset.id}",
            root_dir=MiMoVoiceAssetStore().root_dir,
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 MiMo 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.post("/tts/voices/mimo/design-assets")
async def create_mimo_voice_design_asset(
    request: MiMoVoiceDesignAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存 MiMo Voice Design 本地声音描述资产。"""
    try:
        asset = MiMoVoiceAssetStore().create_design_asset(
            name=request.name,
            voice_design_prompt=request.voice_design_prompt,
            description=request.description or "",
            owner_user_id=int(current_user.id),
        )
        _register_user_generated_voice_asset(
            db=db,
            asset=asset,
            owner_user_id=int(current_user.id),
            provider="mimo",
            source_model=asset.model,
            source_voice_id=f"mimo_design:{asset.id}",
            root_dir=MiMoVoiceAssetStore().root_dir,
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/tts/voices/mimo/assets/{asset_id}")
async def delete_mimo_voice_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除 MiMo 本地音色资产。"""
    try:
        deleted = MiMoVoiceAssetStore().delete_asset(
            asset_id,
            owner_user_id=int(current_user.id),
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MiMo voice asset not found")
        _revoke_registered_user_voice(
            db=db,
            owner_user_id=int(current_user.id),
            source_voice_id=(
                asset_id
                if asset_id.startswith(("mimo_clone:", "mimo_design:"))
                else f"{'mimo_design' if asset_id.startswith('mimo_design_') else 'mimo_clone'}:{asset_id}"
            ),
        )
        return {"deleted": True, "asset_id": asset_id}
    except MiMoVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/tts/voices/stepaudio/assets")
async def list_stepaudio_voice_assets(
    model: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """列出 StepAudio 本地复刻参考样本资产。"""
    try:
        assets = StepAudioVoiceAssetStore().list_assets(
            model=model,
            owner_user_id=int(current_user.id),
        )
        return {
            "assets": [asset.to_dict() for asset in assets],
            "voices": [asset.to_voice_preset() for asset in assets],
            "total": len(assets),
        }
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tts/voices/stepaudio/clone-assets")
async def create_stepaudio_voice_clone_asset(
    request: StepAudioVoiceCloneAssetCreateRequest,
    current_user: User = Depends(get_current_user),
):
    """创建 StepAudio 复刻参考样本元数据资产。

    当前官方资料只给出 /audio/voices/preview 使用 file_id 的合同，未给出正式音色创建接口；
    因此该接口只保存可复用的本地参考资产元数据，不伪造正式 voice_id。
    """
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="StepAudio clone asset requires an uploaded mp3/wav sample; use /clone-assets/upload",
    )


@router.post("/tts/voices/stepaudio/clone-assets/preview")
async def preview_stepaudio_voice_clone_asset(
    name: str = Form(""),
    sample_text: str = Form(""),
    preview_text: str = Form(DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT),
    instruction: str = Form(DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION),
    file_id: str = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Preview a StepAudio Voice Clone sample before saving the local voice asset."""
    try:
        del name
        content = await file.read()
        validate_stepaudio_clone_audio_mime_type(file.content_type or "")
        clean_sample_text = _require_stepaudio_clone_sample_text(sample_text)
        resolved_file_id = await _resolve_stepaudio_clone_file_id(
            file_id=file_id,
            filename=file.filename or "stepaudio-reference.wav",
            content=content,
            mime_type=file.content_type or "",
        )
        stepaudio_api_key = get_stepaudio_api_key()
        if not stepaudio_api_key:
            raise StepAudioVoiceAssetError(
                "STEP_API_KEY or STEPFUN_API_KEY is required before StepAudio clone preview"
            )

        engine = runtime_create_tts_engine(
            model_id=STEPAUDIO_3_TTS_MODEL,
            strategy="balanced",
            enable_cache=False,
            max_concurrent=1,
            request_delay=0.0,
            retry_config=_PREVIEW_RETRY_CONFIG,
        )
        safe_instruction, _ = sanitize_fixed_voice_performance_text(instruction)
        audio_bytes = await engine._call_stepaudio_voice_preview_http(
            model=STEPAUDIO_3_TTS_MODEL,
            api_key=stepaudio_api_key,
            text=(str(preview_text or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT),
            file_id=resolved_file_id,
            sample_text=clean_sample_text,
            instruction=safe_instruction or DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION,
        )
        audio_mime_type = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
        audio_format = "wav" if audio_mime_type == "audio/wav" else "mp3"
        return {
            "file_id": resolved_file_id,
            "sample_text": clean_sample_text,
            "preview_text": str(preview_text or "").strip() or DEFAULT_STEPAUDIO_CLONE_PREVIEW_TEXT,
            "instruction": safe_instruction or DEFAULT_STEPAUDIO_CLONE_PREVIEW_INSTRUCTION,
            "audio_data_base64": base64.b64encode(audio_bytes).decode("utf-8"),
            "audio_mime_type": audio_mime_type,
            "audio_format": audio_format,
            "audio_size_bytes": len(audio_bytes),
            "billing_notice": "StepAudio preview only returns audio; confirm save only after you accept the result.",
        }
    except TTSUserInputError as exc:
        logger.info("StepAudio 复刻预试听输入参数无效: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "code": getattr(exc, "code", "tts_user_input_error"), "retryable": False},
        ) from exc
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 StepAudio 预试听上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.post("/tts/voices/stepaudio/clone-assets/upload")
async def upload_stepaudio_voice_clone_asset(
    name: str = Form(...),
    sample_text: str = Form(""),
    file_id: str = Form(""),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传本地音频并保存为 StepAudio Voice Clone 参考样本资产。"""
    try:
        content = await file.read()
        validate_stepaudio_clone_audio_mime_type(file.content_type or "")
        clean_sample_text = _require_stepaudio_clone_sample_text(sample_text)
        resolved_file_id = await _resolve_stepaudio_clone_file_id(
            file_id=file_id,
            filename=file.filename or "stepaudio-reference.wav",
            content=content,
            mime_type=file.content_type or "",
        )
        asset = StepAudioVoiceAssetStore().create_clone_asset_from_bytes(
            name=name,
            audio_bytes=content,
            mime_type=file.content_type or "",
            sample_text=clean_sample_text,
            file_id=resolved_file_id,
            owner_user_id=int(current_user.id),
        )
        _register_user_generated_voice_asset(
            db=db,
            asset=asset,
            owner_user_id=int(current_user.id),
            provider="stepaudio",
            source_model=asset.model,
            source_voice_id=f"stepaudio_clone:{asset.id}",
            root_dir=StepAudioVoiceAssetStore().root_dir,
        )
        return {"asset": asset.to_dict(), "voice": asset.to_voice_preset()}
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        try:
            await file.close()
        except Exception as exc:
            logger.debug(
                "关闭 StepAudio 上传文件失败，已忽略清理错误: filename=%s error=%s",
                file.filename,
                exc,
            )


@router.delete("/tts/voices/stepaudio/assets/{asset_id}")
async def delete_stepaudio_voice_asset(
    asset_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除 StepAudio 本地复刻参考样本资产。"""
    try:
        deleted = StepAudioVoiceAssetStore().delete_asset(
            asset_id,
            owner_user_id=int(current_user.id),
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="StepAudio voice asset not found")
        _revoke_registered_user_voice(
            db=db,
            owner_user_id=int(current_user.id),
            source_voice_id=(
                asset_id if asset_id.startswith("stepaudio_clone:") else f"stepaudio_clone:{asset_id}"
            ),
        )
        return {"deleted": True, "asset_id": asset_id}
    except StepAudioVoiceAssetError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ==================== API Endpoints ====================
