from __future__ import annotations

import logging
import json
from typing import List, Optional, Dict, Any

from fastapi import Depends, HTTPException

from app.models.audiobook import ChapterAudio
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
)
from app.schemas.audiobook import (
    SegmentRegenerateRequest,
    SegmentReviewRequest,
)
from app.services.audiobook.tts_engine import RetryConfig as TTSRetryConfig
from app.services.audiobook.tts_model_ids import (
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
    normalize_audiobook_tts_model,
)
from app.services.audiobook.temp_segment_store import TempSegmentStoreError, save_segment_audio_map
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

DEFAULT_SEGMENT_REGEN_VOICE_ID = "Neil"
DEFAULT_MINIMAX_SEGMENT_REGEN_VOICE_ID = "male-qn-qingse"


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
    }


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


