from __future__ import annotations

import json
import logging
from typing import List, Optional, Dict, Any

from fastapi import Depends, File, Form, HTTPException, Query, Response, UploadFile

from app.models.audiobook import ChapterAudio
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import (
    SegmentRegenerationCandidateApplyRequest,
    SegmentRegenerateRequest,
    SegmentReviewRequest,
)
from app.services.audiobook.tts_engine import RetryConfig as TTSRetryConfig
from app.services.audiobook.tts_model_ids import (
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.project_audio_runtime import resolve_project_audio_runtime_config
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.temp_segment_store import (
    TempSegmentStoreError,
    load_cached_segment_audio,
    normalize_audio_extension,
    save_segment_audio_map,
)
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

DEFAULT_SEGMENT_REGEN_VOICE_ID = "Neil"
DEFAULT_MINIMAX_SEGMENT_REGEN_VOICE_ID = "male-qn-qingse"
SEGMENT_REGEN_PREVIEW_TYPES = {"voice", "sfx", "bgm", "mix"}
MAX_SEGMENT_VOICE_RECORDING_BYTES = 100 * 1024 * 1024


def _normalize_segment_regeneration_preview_type(value: Optional[str]) -> str:
    preview_type = str(value or "voice").strip().lower()
    if preview_type in SEGMENT_REGEN_PREVIEW_TYPES:
        return preview_type
    return "voice"


def _load_chapter_segments(chapter_audio: ChapterAudio) -> List[Dict[str, Any]]:
    try:
        segments = json.loads(chapter_audio.script_json or "[]")
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "章节剧本 JSON 损坏: chapter_audio_id=%s error=%s",
            getattr(chapter_audio, "id", None),
            exc,
        )
        raise HTTPException(status_code=500, detail="章节剧本数据损坏")

    if not isinstance(segments, list):
        logger.warning(
            "章节剧本 JSON 不是数组: chapter_audio_id=%s payload_type=%s",
            getattr(chapter_audio, "id", None),
            type(segments).__name__,
        )
        raise HTTPException(status_code=500, detail="章节剧本数据损坏")

    return segments


def _get_segment_or_404(segments: List[Dict[str, Any]], segment_index: int) -> Dict[str, Any]:
    if segment_index < 0 or segment_index >= len(segments):
        raise HTTPException(status_code=404, detail="片段索引无效")

    segment = segments[segment_index]
    if not isinstance(segment, dict):
        raise HTTPException(status_code=500, detail="章节剧本片段数据损坏")

    return segment


def _validate_body_segment_index(request_segment_index: Optional[int], path_segment_index: int) -> None:
    if request_segment_index is not None and request_segment_index != path_segment_index:
        raise HTTPException(status_code=400, detail="请求体片段索引与路径不一致")


def _apply_requested_segment_override(
    segments: List[Dict[str, Any]],
    segment_index: int,
    current_segment: Dict[str, Any],
    requested_segment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if requested_segment is None:
        return current_segment
    if not isinstance(requested_segment, dict):
        raise HTTPException(status_code=400, detail="segment 数据格式不正确")

    updated_segment = {**current_segment, **requested_segment}
    segments[segment_index] = updated_segment
    return updated_segment


def _parse_segment_form_payload(segment: Optional[str]) -> Optional[Dict[str, Any]]:
    raw = str(segment or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="segment JSON 格式不正确") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="segment 数据格式不正确")
    return payload


def _audio_format_for_upload(file: UploadFile) -> str:
    content_type = str(getattr(file, "content_type", "") or "").strip().lower()
    if content_type.startswith("audio/"):
        return normalize_audio_extension(content_type.split("/", 1)[1].split(";", 1)[0])

    filename = str(getattr(file, "filename", "") or "").strip().lower()
    if "." in filename:
        return normalize_audio_extension(filename.rsplit(".", 1)[-1])

    return "webm"


def _resolve_segment_regen_voice_id(
    *,
    tts_model: str,
    requested_voice_id: Optional[str],
    segment_voice_params: Dict[str, Any],
    segment: Dict[str, Any],
) -> str:
    voice_id = (
        requested_voice_id
        or segment_voice_params.get("speaker")
        or segment.get("voice_id")
        or ""
    )
    if voice_id:
        return str(voice_id)

    if tts_model in {MINIMAX_SPEECH_28_HD_MODEL, MINIMAX_SPEECH_28_TURBO_MODEL}:
        return DEFAULT_MINIMAX_SEGMENT_REGEN_VOICE_ID
    if tts_model == "cosyvoice-v3.5-plus":
        raise HTTPException(
            status_code=400,
            detail="cosyvoice-v3.5-plus 片段重生成需要显式选择复刻或设计音色",
        )
    return DEFAULT_SEGMENT_REGEN_VOICE_ID


def _build_segment_synthesis_payload(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
) -> Dict[str, Any]:
    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}

    tts_model = normalize_audiobook_tts_model(request.tts_model)
    voice_id = _resolve_segment_regen_voice_id(
        tts_model=tts_model,
        requested_voice_id=request.voice_id,
        segment_voice_params=segment_voice_params,
        segment=segment,
    )
    emotion = (
        request.emotion
        or segment.get("instruct_emotion")
        or segment.get("emotion")
        or "neutral"
    )
    text = str(segment.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="鐗囨鏂囨湰涓嶈兘涓虹┖")

    voice_params = dict(segment_voice_params)
    voice_params["speaker"] = voice_id
    voice_params["emotion"] = emotion
    voice_params["segment_speaker"] = segment.get("speaker", "")
    voice_params["segment_type"] = segment.get("type", "")
    voice_params["instruct_emotion"] = segment.get("instruct_emotion") or emotion
    voice_params["instruct_scene"] = segment.get("instruct_scene") or ""
    voice_params["instruct_role"] = segment.get("instruct_role") or ""
    voice_params["instruct_identity"] = segment.get("instruct_identity") or ""
    performance_notes = str(segment.get("performance_notes") or "").strip()
    if performance_notes:
        voice_params["performance_notes"] = performance_notes
    if (
        voice_params.get("instruct_emotion")
        or voice_params.get("instruct_scene")
        or voice_params.get("instruct_role")
        or voice_params.get("instruct_identity")
        or performance_notes
    ):
        voice_params["use_instruct_mode"] = True

    return {
        "text": text,
        "voice_params": voice_params,
        "emotion": emotion,
        "tts_model": tts_model,
    }


async def _synthesize_segment_audio(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
) -> Dict[str, Any]:
    payload = _build_segment_synthesis_payload(request, segment)
    audio_bytes = await runtime_synthesize_speech(
        text=payload["text"],
        voice_params=payload["voice_params"],
        emotion=payload["emotion"],
        model_id=payload["tts_model"],
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=TTSRetryConfig(max_retries=3, base_delay=1.0, max_delay=8.0),
    )

    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS 鐢熸垚澶辫触")

    return {
        **payload,
        "audio_bytes": audio_bytes,
    }


async def _generate_segment_regeneration_audio(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
    owned: OwnedAudiobookProject,
) -> Dict[str, Any]:
    preview_type = _normalize_segment_regeneration_preview_type(getattr(request, "preview_type", "voice"))
    if preview_type == "voice":
        synthesis = await _synthesize_segment_audio(request, segment)
        return {
            **synthesis,
            "preview_type": preview_type,
        }

    tts_model = normalize_audiobook_tts_model(request.tts_model)
    runtime_config = resolve_project_audio_runtime_config(
        owned.project,
        tts_model=tts_model,
        base_voice_mapping=getattr(owned.audiobook_project, "voice_mapping", None) or {},
    )
    preview_service = SegmentPreviewService(
        tts_model=tts_model,
        voice_mapping=runtime_config.voice_mapping,
        audio_fx=runtime_config.audio_fx,
        synthesize_speech=runtime_synthesize_speech,
    )
    result = await preview_service.generate_preview(segment, preview_type=preview_type)
    return {
        "audio_bytes": result.audio,
        "tts_model": tts_model,
        "preview_type": preview_type,
    }


def _get_cached_audio_path(temp_segment_cache: Dict[str, Any], segment_index: int) -> Optional[str]:
    cached_audio_paths = temp_segment_cache.get("cached_audio_paths") or {}
    if not isinstance(cached_audio_paths, dict):
        return None
    for key in (segment_index, str(segment_index)):
        path_value = str(cached_audio_paths.get(key) or "").strip()
        if path_value:
            return path_value
    return None


def _save_regenerated_segment_audio(
    *,
    chapter_audio: ChapterAudio,
    chapter_id: int,
    segment_index: int,
    audio_bytes: bytes,
    run_id_prefix: str,
    output_format: Optional[str] = None,
) -> Dict[str, Any]:
    output_format = normalize_audio_extension(output_format) if output_format else ("wav" if audio_bytes.startswith(b"RIFF") else "mp3")
    try:
        temp_segment_cache = save_segment_audio_map(
            run_id=f"{run_id_prefix}_{chapter_audio.id}",
            chapter_id=chapter_id,
            audio_map={segment_index: audio_bytes},
            format=output_format,
        )
    except (OSError, TempSegmentStoreError) as e:
        logger.error("保存音频失败: %s", e)
        raise HTTPException(status_code=500, detail=f"保存音频失败: {str(e)}")

    audio_path = _get_cached_audio_path(temp_segment_cache, segment_index)
    if not audio_path:
        raise HTTPException(status_code=500, detail="保存音频失败: cached_audio_paths 缺失")

    return {
        "audio_path": audio_path,
        "temp_segment_cache": temp_segment_cache,
    }


def _mark_segment_regenerated(
    segment: Dict[str, Any],
    *,
    audio_path: str,
    reason: Optional[str],
) -> Dict[str, Any]:
    segment["audio_path"] = audio_path
    segment["regenerated"] = True
    segment["regenerated_at"] = utc_now().isoformat()
    if reason:
        segment["regenerate_reason"] = reason
    return segment


def _segment_audio_path_field(preview_type: Optional[str]) -> str:
    normalized_type = _normalize_segment_regeneration_preview_type(preview_type)
    if normalized_type == "voice":
        return "audio_path"
    return f"{normalized_type}_audio_path"


def _mark_segment_regeneration_candidate_applied(
    segment: Dict[str, Any],
    *,
    audio_path: str,
    preview_type: Optional[str],
    reason: Optional[str],
) -> Dict[str, Any]:
    normalized_type = _normalize_segment_regeneration_preview_type(preview_type)
    segment[_segment_audio_path_field(normalized_type)] = audio_path
    segment["regenerated"] = True
    segment["regenerated_at"] = utc_now().isoformat()
    segment["regenerated_preview_type"] = normalized_type
    if reason:
        segment["regenerate_reason"] = reason
    return segment


def _media_type_for_audio_path(audio_path: str) -> str:
    extension = str(audio_path or "").rsplit(".", 1)[-1].lower()
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "opus": "audio/ogg",
        "m4a": "audio/mp4",
        "m4b": "audio/mp4",
    }.get(extension, "application/octet-stream")


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regenerate")
async def regenerate_segment(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentRegenerateRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """单个片段重新生成
    
    功能：
    1. 重新调用 TTS API 生成该片段的新音频
    2. 替换原有的片段音频
    3. 可选：使用不同的 TTS 模型/音色/情感
    """
    _validate_body_segment_index(request.segment_index, segment_index)

    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    
    # 加载剧本片段
    segments = _load_chapter_segments(chapter_audio)
    segment = _get_segment_or_404(segments, segment_index)
    segment = _apply_requested_segment_override(
        segments,
        segment_index,
        segment,
        request.segment,
    )

    synthesis = await _synthesize_segment_audio(request, segment)
    saved_audio = _save_regenerated_segment_audio(
        chapter_audio=chapter_audio,
        chapter_id=chapter_id,
        segment_index=segment_index,
        audio_bytes=synthesis["audio_bytes"],
        run_id_prefix="segment_regen",
    )
    audio_path = saved_audio["audio_path"]
    temp_segment_cache = saved_audio["temp_segment_cache"]
    _mark_segment_regenerated(segment, audio_path=audio_path, reason=request.reason)

    chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    db.commit()

    logger.info(
        f"鉁?鐗囨閲嶆柊鐢熸垚鎴愬姛: chapter_id={chapter_id}, "
        f"segment_index={segment_index}, model={synthesis['tts_model']}"
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "audio_path": audio_path,
        "temp_segment_cache": temp_segment_cache,
        "audio_size": len(synthesis["audio_bytes"]),
        "model_used": synthesis["tts_model"],
        "segment": segment,
    }
    
    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}

    # 构建 TTS 请求参数
    tts_model = normalize_audiobook_tts_model(request.tts_model)
    voice_id = _resolve_segment_regen_voice_id(
        tts_model=tts_model,
        requested_voice_id=request.voice_id,
        segment_voice_params=segment_voice_params,
        segment=segment,
    )
    emotion = (
        request.emotion
        or segment.get("instruct_emotion")
        or segment.get("emotion")
        or "neutral"
    )
    text = str(segment.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="片段文本不能为空")

    voice_params = dict(segment_voice_params)
    voice_params["speaker"] = voice_id
    voice_params["emotion"] = emotion
    voice_params["segment_speaker"] = segment.get("speaker", "")
    voice_params["segment_type"] = segment.get("type", "")
    voice_params["instruct_emotion"] = segment.get("instruct_emotion") or emotion
    voice_params["instruct_scene"] = segment.get("instruct_scene") or ""
    voice_params["instruct_role"] = segment.get("instruct_role") or ""
    voice_params["instruct_identity"] = segment.get("instruct_identity") or ""
    performance_notes = str(segment.get("performance_notes") or "").strip()
    if performance_notes:
        voice_params["performance_notes"] = performance_notes
    if (
        voice_params.get("instruct_emotion")
        or voice_params.get("instruct_scene")
        or voice_params.get("instruct_role")
        or voice_params.get("instruct_identity")
        or performance_notes
    ):
        voice_params["use_instruct_mode"] = True

    # 调用 TTS
    audio_bytes = await runtime_synthesize_speech(
        text=text,
        voice_params=voice_params,
        emotion=emotion,
        model_id=tts_model,
        enable_cache=False,
        max_concurrent=1,
        request_delay=0.0,
        retry_config=TTSRetryConfig(max_retries=3, base_delay=1.0, max_delay=8.0),
    )
    
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS 生成失败")
    
    # 保存新音频（覆盖原音频）
    output_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    try:
        temp_segment_cache = save_segment_audio_map(
            run_id=f"segment_regen_{chapter_audio.id}",
            chapter_id=chapter_id,
            audio_map={segment_index: audio_bytes},
            format=output_format,
        )
    except (OSError, TempSegmentStoreError) as e:
        logger.error(f"❌ 保存重新生成的音频失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存音频失败: {str(e)}")

    audio_path = (temp_segment_cache.get("cached_audio_paths") or {}).get(segment_index)

    # 更新 segment 中的音频路径
    segment["audio_path"] = audio_path
    segment["regenerated"] = True
    segment["regenerated_at"] = utc_now().isoformat()
    if request.reason:
        segment["regenerate_reason"] = request.reason

    # 保存更新后的剧本
    chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    db.commit()

    logger.info(
        f"✅ 片段重新生成成功: chapter_id={chapter_id}, "
        f"segment_index={segment_index}, model={tts_model}"
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "audio_path": audio_path,
        "temp_segment_cache": temp_segment_cache,
        "audio_size": len(audio_bytes),
        "model_used": tts_model,
        "segment": segment,
    }


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regeneration-candidate")
async def create_segment_regeneration_candidate(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentRegenerateRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    _validate_body_segment_index(request.segment_index, segment_index)

    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    segments = _load_chapter_segments(chapter_audio)
    candidate_segments = list(segments)
    current_segment = _get_segment_or_404(candidate_segments, segment_index)
    segment = _apply_requested_segment_override(
        candidate_segments,
        segment_index,
        current_segment,
        request.segment,
    )

    synthesis = await _generate_segment_regeneration_audio(request, segment, owned)
    preview_type = synthesis["preview_type"]
    saved_audio = _save_regenerated_segment_audio(
        chapter_audio=chapter_audio,
        chapter_id=chapter_id,
        segment_index=segment_index,
        audio_bytes=synthesis["audio_bytes"],
        run_id_prefix=f"segment_regen_candidate_{preview_type}",
    )
    candidate_audio_path = saved_audio["audio_path"]

    return {
        "success": True,
        "segment_index": segment_index,
        "candidate_audio_path": candidate_audio_path,
        "preview_type": preview_type,
        "temp_segment_cache": saved_audio["temp_segment_cache"],
        "audio_size": len(synthesis["audio_bytes"]),
        "model_used": synthesis["tts_model"],
        "segment": segment,
    }


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regeneration-candidate/upload-voice")
async def upload_segment_voice_recording_candidate(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    file: UploadFile = File(...),
    segment: Optional[str] = Form(default=None),
    reason: Optional[str] = Form(default=None),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    segments = _load_chapter_segments(chapter_audio)
    candidate_segments = list(segments)
    current_segment = _get_segment_or_404(candidate_segments, segment_index)
    candidate_segment = _apply_requested_segment_override(
        candidate_segments,
        segment_index,
        current_segment,
        _parse_segment_form_payload(segment),
    )

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="配音音频不能为空")
    if len(audio_bytes) > MAX_SEGMENT_VOICE_RECORDING_BYTES:
        raise HTTPException(status_code=413, detail="配音音频过大，请缩短录音后重试")

    saved_audio = _save_regenerated_segment_audio(
        chapter_audio=chapter_audio,
        chapter_id=chapter_id,
        segment_index=segment_index,
        audio_bytes=audio_bytes,
        run_id_prefix="segment_voice_recording_candidate",
        output_format=_audio_format_for_upload(file),
    )
    candidate_audio_path = saved_audio["audio_path"]

    return {
        "success": True,
        "segment_index": segment_index,
        "candidate_audio_path": candidate_audio_path,
        "preview_type": "voice",
        "temp_segment_cache": saved_audio["temp_segment_cache"],
        "audio_size": len(audio_bytes),
        "model_used": "manual-recording",
        "reason": reason,
        "segment": candidate_segment,
    }


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regeneration-candidate/apply")
async def apply_segment_regeneration_candidate(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentRegenerationCandidateApplyRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    candidate_audio_path = str(request.candidate_audio_path or "").strip()
    if not candidate_audio_path:
        raise HTTPException(status_code=400, detail="candidate_audio_path 涓嶈兘涓虹┖")

    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    segments = _load_chapter_segments(chapter_audio)
    current_segment = _get_segment_or_404(segments, segment_index)
    segment = _apply_requested_segment_override(
        segments,
        segment_index,
        current_segment,
        request.segment,
    )
    preview_type = _normalize_segment_regeneration_preview_type(getattr(request, "preview_type", "voice"))
    _mark_segment_regeneration_candidate_applied(
        segment,
        audio_path=candidate_audio_path,
        preview_type=preview_type,
        reason=request.reason,
    )

    chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    db.commit()

    return {
        "success": True,
        "segment_index": segment_index,
        "audio_path": candidate_audio_path,
        "preview_type": preview_type,
        "segment": segment,
    }


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regeneration-candidate/audio")
async def get_segment_regeneration_candidate_audio(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    audio_path: str = Query(...),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    candidate_audio_path = str(audio_path or "").strip()
    if not candidate_audio_path:
        raise HTTPException(status_code=400, detail="audio_path 涓嶈兘涓虹┖")

    get_active_chapter_audio_for_project(
        db=owned.db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    audio_by_index = load_cached_segment_audio(
        {"cached_audio_paths": {segment_index: candidate_audio_path}},
        max_segment_count=segment_index + 1,
    )
    audio_bytes = audio_by_index.get(segment_index)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="闊抽鍊欓€夋枃浠朵笉瀛樺湪")

    return Response(
        content=audio_bytes,
        media_type=_media_type_for_audio_path(candidate_audio_path),
    )


@router.post("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/review")
async def review_segment(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    request: SegmentReviewRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """片段审查/评分
    
    功能：
    1. 记录片段的质量评分和备注
    2. 标记需要重新生成的片段
    3. 更新章节整体审查状态
    """
    _validate_body_segment_index(request.segment_index, segment_index)

    db = owned.db
    current_user = owned.current_user
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    segments = _load_chapter_segments(chapter_audio)
    _get_segment_or_404(segments, segment_index)
    
    # 加载审查记录
    review_data = {}
    if chapter_audio.segment_reviews_json:
        try:
            loaded_review_data = json.loads(chapter_audio.segment_reviews_json)
            if isinstance(loaded_review_data, dict):
                review_data = loaded_review_data
            else:
                logger.warning(
                    "片段审查 JSON 不是对象，已重置: chapter_audio_id=%s payload_type=%s",
                    chapter_audio.id,
                    type(loaded_review_data).__name__,
                )
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "片段审查 JSON 损坏，已重置: chapter_audio_id=%s error=%s",
                chapter_audio.id,
                exc,
            )
    
    # 记录审查结果
    review_key = str(segment_index)
    review_data[review_key] = {
        "quality_score": request.quality_score,
        "notes": request.notes,
        "needs_regenerate": request.needs_regenerate,
        "reviewed_at": utc_now().isoformat(),
        "reviewed_by": current_user.id,
    }
    
    chapter_audio.segment_reviews_json = json.dumps(review_data, ensure_ascii=False)
    db.commit()
    
    return {
        "success": True,
        "segment_index": segment_index,
        "review_saved": True,
    }


