from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from typing import List, Optional, Dict, Any, Mapping

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
    DEFAULT_AUDIOBOOK_TTS_MODEL,
    MINIMAX_SPEECH_28_HD_MODEL,
    MINIMAX_SPEECH_28_TURBO_MODEL,
)
from app.services.audiobook.project_audio_config import parse_engine_config_snapshot
from app.services.audiobook.project_audio_runtime import (
    ProjectAudioRuntimeConfig,
    resolve_from_snapshot,
    resolve_project_audio_runtime_config,
)
from app.services.audiobook.mimo_voice_assets import merge_mimo_voice_asset_tts_params
from app.services.audiobook.background_jobs_shared import (
    get_latest_run_checkpoint_json,
)
from app.services.audiobook import segment_preview_service as _segment_preview_module
from app.services.audiobook.segment_preview_service import SegmentPreviewService
from app.services.audiobook.segment_timeline_preview import (
    render_segment_timeline_preview,
)
from app.services.audiobook.segment_asset_ai_generator import (
    generate_segment_bgm_asset,
    generate_segment_sfx_asset,
)
from app.services.audiobook.tts_delivery_plan import resolve_segment_tts_model
from app.services.audiobook.voice_manager import VoiceMappingResolutionError
from app.services.audiobook.chapter_segment_assets import (
    SERVER_MANAGED_SEGMENT_ASSET_FIELDS,
    collect_segment_asset_refs,
    compute_segment_audio_cache_key,
    delete_replaced_segment_asset_refs,
    is_persistent_segment_asset_ref,
    load_persistent_segment_audio,
    resolve_chapter_render_chunk_max_chars,
    save_persistent_segment_audio,
)
from app.services.audiobook.render_plan import WHOLE_SEGMENT_RENDER_MODE
from app.services.audiobook.segment_candidate_registry import (
    finalize_segment_candidate_runs,
    load_segment_candidate_contract,
    register_segment_candidate_asset,
    segment_candidate_contract_matches_token,
)
from app.services.audiobook.segment_candidate_token import (
    issue_segment_candidate_token,
    verify_segment_candidate_token,
)
from app.services.audiobook.segment_synthesis_contract import (
    compile_segment_synthesis_input,
    compute_segment_semantic_fingerprint,
    resolve_server_owned_mimo_design_params,
    sanitize_segment_override,
)
from app.services.audiobook.temp_segment_store import (
    TempSegmentStoreError,
    build_segment_asset_ref,
    delete_temp_segment_prefix,
    load_cached_segment_audio,
    normalize_audio_extension,
    save_segment_audio_map,
)
from app.utils.datetime_utils import utc_now
from core.unified_media_runtime import synthesize_speech as runtime_synthesize_speech

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

# MiniMax 是唯一"空音色会被引擎直接拒单"的现役模型（`_call_dashscope_minimax_http`
# 抛 TTSUserInputError），所以只有它需要接口侧的显式兜底声线。
# 其余模型（Qwen-Audio 3.1 / StepAudio / Seed-TTS / MiMo）一律不在此处编音色名：
# 它们的默认音色只能在引擎各模型载荷组装点定义，接口层重复一份就必然出现
# "按 A 供应商的音色空间给 B 供应商挑音色"的错配——历史写法硬编码 "Neil" 时，
# 现役上游把它判为无效 voice 且本地无任何报错，只表现为"这句试听没有声音"。
DEFAULT_MINIMAX_SEGMENT_REGEN_VOICE_ID = "male-qn-qingse"
SEGMENT_REGEN_PREVIEW_TYPES = {"voice", "sfx", "bgm", "mix"}
MAX_SEGMENT_VOICE_RECORDING_BYTES = 100 * 1024 * 1024

# 时间线试听的 checkpoint 来源优先级：最近一次混音产物 > 管线原始生成
_SEGMENT_TIMELINE_PREVIEW_RUN_TYPES = ("chapter_remix", "audio_from_scripts", "full")
# 仅用于解析项目 audio_fx，取值不影响音效配置本身
_SEGMENT_TIMELINE_PREVIEW_TTS_MODEL = DEFAULT_AUDIOBOOK_TTS_MODEL


def _normalize_segment_regeneration_preview_type(value: Optional[str]) -> str:
    preview_type = str(value or "voice").strip().lower()
    if preview_type in SEGMENT_REGEN_PREVIEW_TYPES:
        return preview_type
    return "voice"


def _compute_segment_candidate_fingerprint(segment: Dict[str, Any]) -> str:
    """计算片段参数指纹（文本/音色/情感等渲染相关字段的规范哈希）。

    候选签发时绑定生成时的片段状态，apply 时要求目标片段指纹完全一致，
    防止“文本 A 生成的音频被写成文本 B”或跨标签页错绑。
    """
    return compute_segment_semantic_fingerprint(segment)


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

    # 安全约束：音频资产字段由服务端管理，拒绝客户端注入任意路径
    sanitized_override = sanitize_segment_override(requested_segment) or {}
    updated_segment = {**current_segment, **sanitized_override}
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
    voice_mapping: Optional[Mapping[str, Any]] = None,
) -> str:
    voice_id = (
        requested_voice_id
        or segment_voice_params.get("speaker")
        or segment.get("voice_id")
        or ""
    )
    if voice_id:
        return str(voice_id)

    # 与普通片段试听保持同一回退顺序：项目级角色映射优先于模型默认音色。
    # 这里只读取服务端已解析的 voice_mapping，不接受额外客户端身份字段。
    mapping = voice_mapping if isinstance(voice_mapping, Mapping) else {}
    speaker_name = str(segment.get("speaker") or "").strip()
    mapping_names = [speaker_name]
    if speaker_name in {"旁白", "narrator", "Narrator"}:
        mapping_names.extend(["旁白", "narrator"])
    for mapping_name in dict.fromkeys(name for name in mapping_names if name):
        config = mapping.get(mapping_name)
        if not isinstance(config, Mapping):
            continue
        mapped_voice_id = str(config.get("voice_id") or "").strip()
        if mapped_voice_id:
            return mapped_voice_id

    if tts_model in {MINIMAX_SPEECH_28_HD_MODEL, MINIMAX_SPEECH_28_TURBO_MODEL}:
        return DEFAULT_MINIMAX_SEGMENT_REGEN_VOICE_ID
    if tts_model == "cosyvoice-v3.5-plus":
        raise HTTPException(
            status_code=400,
            detail="cosyvoice-v3.5-plus 片段重生成需要显式选择复刻或设计音色",
        )
    # 留给引擎：空 speaker 会被各模型载荷组装点兜成自己的默认音色。
    return ""


def _build_segment_synthesis_payload(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
    *,
    allow_missing_voice: bool = False,
    voice_mapping: Optional[Mapping[str, Any]] = None,
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    preview_type = _normalize_segment_regeneration_preview_type(
        getattr(request, "preview_type", "voice")
    )
    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}

    # 片段绑定的音色模型（如克隆/自定义音色所属模型）优先于页面选择的模型，
    # 与整章生成管线的 resolve_segment_tts_model 保持一致；
    # 否则克隆音色会被传给不支持它的模型，导致 400 Voice not supported。
    tts_model = resolve_segment_tts_model(segment_voice_params, request.tts_model)
    if preview_type in {"sfx", "bgm"} or allow_missing_voice:
        # SFX/BGM previews render a silence base and do not need a provider voice.
        voice_id = str(
            request.voice_id
            or segment_voice_params.get("speaker")
            or segment.get("voice_id")
            or ""
        )
    else:
        voice_id = _resolve_segment_regen_voice_id(
            tts_model=tts_model,
            requested_voice_id=request.voice_id,
            segment_voice_params=segment_voice_params,
            segment=segment,
            voice_mapping=voice_mapping,
        )
    emotion = (
        request.emotion
        or segment.get("instruct_emotion")
        or segment.get("emotion")
        or "neutral"
    )
    text = str(segment.get("text") or "").strip()
    if not text and preview_type in {"voice", "mix"}:
        raise HTTPException(status_code=400, detail="片段文本不能为空")

    server_owned_voice_params = {}
    if not allow_missing_voice and preview_type in {"voice", "mix"}:
        try:
            server_owned_voice_params = resolve_server_owned_mimo_design_params(
                tts_model=tts_model,
                voice_id=voice_id,
                mimo_voice_asset_id=str(
                    segment_voice_params.get("mimo_voice_asset_id") or ""
                ),
                owner_user_id=owner_user_id,
                merge_asset_params=merge_mimo_voice_asset_tts_params,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return compile_segment_synthesis_input(
        segment,
        tts_model=tts_model,
        voice_id=voice_id,
        emotion=emotion,
        preview_type=preview_type,
        server_owned_voice_params=server_owned_voice_params,
    )


async def _synthesize_segment_audio(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
    *,
    voice_mapping: Optional[Mapping[str, Any]] = None,
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    payload = _build_segment_synthesis_payload(
        request,
        segment,
        voice_mapping=voice_mapping,
        owner_user_id=owner_user_id,
    )
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
        raise HTTPException(status_code=500, detail="TTS 生成失败")

    return {
        **payload,
        "audio_bytes": audio_bytes,
    }


def _resolve_runtime_config_from_batch(
    owned: OwnedAudiobookProject,
    *,
    tts_model: str,
) -> ProjectAudioRuntimeConfig:
    """从批次快照解析运行时配置（§1.5：冻结事实，不读实时可变配置）。

    缺快照的批次（legacy_unfrozen/legacy_unverified）回退实时解析（读兼容）。
    """
    audiobook_project = getattr(owned, "audiobook_project", None)
    batch_snapshot = parse_engine_config_snapshot(
        getattr(audiobook_project, "engine_config_snapshot", None)
    ) if audiobook_project is not None else None
    if batch_snapshot:
        return resolve_from_snapshot(batch_snapshot, tts_model=tts_model)
    return resolve_project_audio_runtime_config(
        getattr(owned, "project", None),
        tts_model=tts_model,
        base_voice_mapping=getattr(audiobook_project, "voice_mapping", None) or {},
    )


def _resolve_segment_regeneration_runtime_config(
    owned: OwnedAudiobookProject,
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
) -> ProjectAudioRuntimeConfig:
    segment_voice_params = segment.get("voice_params") or {}
    if not isinstance(segment_voice_params, dict):
        segment_voice_params = {}
    resolved_tts_model = resolve_segment_tts_model(
        segment_voice_params,
        request.tts_model,
    )
    return _resolve_runtime_config_from_batch(
        owned,
        tts_model=resolved_tts_model,
    )


def _apply_generated_asset_reference(
    segment: Dict[str, Any],
    preview_type: str,
    generated: Any,
) -> Dict[str, Any]:
    """把 AI 生成的素材引用写回片段，保证整章重混音复用新素材。

    必须在编译（compile_segment_synthesis_input）之前调用，
    使 effective_segment_fingerprint 包含新资产引用。
    """
    enriched = dict(segment)
    if preview_type == "sfx":
        specs = _segment_preview_module.SegmentPreviewService.normalize_sound_effects(enriched)
        sound_effects: List[Dict[str, Any]] = []
        for spec in specs:
            entry = dict(spec) if isinstance(spec, dict) else {"name": str(spec)}
            entry["asset_id"] = generated.asset_id
            entry["file"] = generated.file_path
            sound_effects.append(entry)
        if sound_effects:
            enriched["sound_effects"] = sound_effects
            enriched.pop("sound_effects_simple", None)
    elif preview_type == "bgm":
        cue = _segment_preview_module.SegmentPreviewService.normalize_music_cue(enriched)
        if cue:
            cue = dict(cue)
            cue["asset_id"] = generated.asset_id
            cue["file"] = generated.file_path
            enriched["music_cue"] = cue
            enriched.pop("music_cue_simple", None)
    return enriched


async def _generate_segment_regeneration_audio(
    request: SegmentRegenerateRequest,
    segment: Dict[str, Any],
    owned: OwnedAudiobookProject,
) -> Dict[str, Any]:
    preview_type = _normalize_segment_regeneration_preview_type(getattr(request, "preview_type", "voice"))
    runtime_config = _resolve_segment_regeneration_runtime_config(
        owned,
        request,
        segment,
    )
    owner_user_id = getattr(getattr(owned, "current_user", None), "id", None)
    if preview_type == "voice":
        synthesis = await _synthesize_segment_audio(
            request,
            segment,
            voice_mapping=runtime_config.voice_mapping,
            owner_user_id=owner_user_id,
        )
        return {
            **synthesis,
            "preview_type": preview_type,
        }

    # AI 生成分支：音效/配乐用户显式选择大模型生成时，不走素材库匹配
    source_mode = str(getattr(request, "source_mode", "library") or "library").strip()
    if preview_type in {"sfx", "bgm"} and source_mode == "ai_generate":
        generated = await (
            generate_segment_sfx_asset(segment)
            if preview_type == "sfx"
            else generate_segment_bgm_asset(segment)
        )
        enriched = _apply_generated_asset_reference(segment, preview_type, generated)
        # 先写回资产引用再编译，保证指纹与候选快照一致
        compiled = _build_segment_synthesis_payload(
            request,
            enriched,
            voice_mapping=runtime_config.voice_mapping,
            owner_user_id=owner_user_id,
        )
        return {
            **compiled,
            "audio_bytes": generated.audio_bytes,
            "preview_type": preview_type,
        }

    # 非人声预览同样使用服务端编译后的片段，避免旧 provider snapshot 覆盖新提示。
    compiled = _build_segment_synthesis_payload(
        request,
        segment,
        voice_mapping=runtime_config.voice_mapping,
        owner_user_id=owner_user_id,
    )
    compiled_segment = compiled["segment"]
    tts_model = compiled["tts_model"]
    try:
        preview_service = SegmentPreviewService(
            tts_model=tts_model,
            voice_mapping=runtime_config.voice_mapping,
            audio_fx=runtime_config.audio_fx,
            synthesize_speech=runtime_synthesize_speech,
        )
    except VoiceMappingResolutionError as exc:
        # 角色音越界按 400 回给用户，不静默换声线生成一条"听着不对"的候选
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await preview_service.generate_preview(compiled_segment, preview_type=preview_type)
    return {
        **compiled,
        "audio_bytes": result.audio,
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
    preview_type: str = "voice",
    segment_fingerprint: str = "",
    effective_segment_fingerprint: str = "",
    synthesis_fingerprint: str = "",
    output_format: Optional[str] = None,
) -> Dict[str, Any]:
    output_format = normalize_audio_extension(output_format) if output_format else ("wav" if audio_bytes.startswith(b"RIFF") else "mp3")
    run_id = f"{run_id_prefix}_{chapter_audio.id}_{uuid.uuid4().hex}"
    try:
        temp_segment_cache = save_segment_audio_map(
            run_id=run_id,
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

    candidate_id = issue_segment_candidate_token(
        chapter_audio_id=chapter_audio.id,
        chapter_id=chapter_id,
        segment_index=segment_index,
        run_id=run_id,
        content_sha1=hashlib.sha1(audio_bytes).hexdigest(),
        extension=output_format,
        preview_type=preview_type,
        segment_fingerprint=segment_fingerprint,
        effective_segment_fingerprint=effective_segment_fingerprint,
        synthesis_fingerprint=synthesis_fingerprint,
    )

    return {
        "audio_path": audio_path,
        "candidate_id": candidate_id,
        "temp_segment_cache": temp_segment_cache,
    }


def _mark_segment_regenerated(
    segment: Dict[str, Any],
    *,
    audio_path: str,
    reason: Optional[str],
    audio_cache_key: Optional[str] = None,
    audio_render_chunk_max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    segment.pop("mix_audio_path", None)
    segment.pop("audio_chunk_cache_paths", None)
    segment["audio_render_mode"] = WHOLE_SEGMENT_RENDER_MODE
    segment["audio_path"] = audio_path
    segment["regenerated"] = True
    segment["regenerated_at"] = utc_now().isoformat()
    if audio_cache_key:
        segment["audio_cache_key"] = compute_segment_audio_cache_key(
            segment,
            render_chunk_max_chars=audio_render_chunk_max_chars,
        ) or audio_cache_key
    if audio_render_chunk_max_chars:
        segment["audio_render_chunk_max_chars"] = audio_render_chunk_max_chars
    if reason:
        segment["regenerate_reason"] = reason
    return segment


def _segment_audio_path_field(preview_type: Optional[str]) -> str:
    normalized_type = _normalize_segment_regeneration_preview_type(preview_type)
    if normalized_type == "voice":
        return "audio_path"
    return f"{normalized_type}_audio_path"


def _render_segment_timeline_preview(
    owned: OwnedAudiobookProject,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    preview_type: str,
) -> bytes:
    """无持久化分轨时，按 checkpoint 时间线实时渲染片段音效/配乐试听。

    管线生成的音效/配乐只存在章节级时间线中，这里取归属该片段的条目
    渲染，保证试听结果与整章成品一致。
    """
    timeline_key = "effect_timeline" if preview_type == "sfx" else "music_timeline"
    checkpoint: Dict[str, Any] = {}
    for run_type in _SEGMENT_TIMELINE_PREVIEW_RUN_TYPES:
        candidate = get_latest_run_checkpoint_json(
            owned.db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            run_type=run_type,
        )
        container = candidate.get(timeline_key)
        if (
            isinstance(container, dict)
            and container.get("timeline")
            and isinstance(candidate.get("segment_timings"), list)
        ):
            checkpoint = candidate
            break

    audio_fx: Dict[str, Any] = {}
    runtime_config = _resolve_runtime_config_from_batch(
        owned,
        tts_model=_SEGMENT_TIMELINE_PREVIEW_TTS_MODEL,
    )
    audio_fx = runtime_config.audio_fx or {}

    rendered = render_segment_timeline_preview(
        checkpoint=checkpoint,
        segment_index=segment_index,
        preview_type=preview_type,
        audio_fx=audio_fx,
    )
    if not rendered:
        label = "音效" if preview_type == "sfx" else "配乐"
        raise HTTPException(
            status_code=404,
            detail=f"该片段没有管线生成的{label}时间线，请先配置{label}提示或重新生成章节音频",
        )
    return rendered


def _cleanup_replaced_persistent_segment_assets(
    previous_refs: set[str],
    segments: List[Dict[str, Any]],
) -> None:
    active_refs: set[str] = set()
    for segment in segments:
        active_refs.update(collect_segment_asset_refs(segment))
    try:
        delete_replaced_segment_asset_refs(previous_refs, active_refs)
    except (OSError, TempSegmentStoreError) as exc:
        logger.warning("回收被替换的持久化片段音频失败: error=%s", exc)


def _mark_segment_regeneration_candidate_applied(
    segment: Dict[str, Any],
    *,
    audio_path: str,
    preview_type: Optional[str],
    reason: Optional[str],
    audio_cache_key: Optional[str] = None,
    audio_render_chunk_max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    normalized_type = _normalize_segment_regeneration_preview_type(preview_type)
    if normalized_type != "mix":
        segment.pop("mix_audio_path", None)
    segment[_segment_audio_path_field(normalized_type)] = audio_path
    segment["regenerated"] = True
    segment["regenerated_at"] = utc_now().isoformat()
    segment["regenerated_preview_type"] = normalized_type
    if normalized_type == "voice":
        segment.pop("audio_chunk_cache_paths", None)
        segment["audio_render_mode"] = WHOLE_SEGMENT_RENDER_MODE
        if audio_cache_key:
            segment["audio_cache_key"] = compute_segment_audio_cache_key(
                segment,
                render_chunk_max_chars=audio_render_chunk_max_chars,
            ) or audio_cache_key
        if audio_render_chunk_max_chars:
            segment["audio_render_chunk_max_chars"] = audio_render_chunk_max_chars
    if reason:
        segment["regenerate_reason"] = reason
    return segment


def _persist_applied_candidate_audio(
    *,
    chapter_audio: ChapterAudio,
    segment_index: int,
    segment_key: Optional[str],
    candidate_payload: Dict[str, Any],
    preview_type: str,
) -> str:
    """把候选音频（已验证的 token payload）固化到章节持久化片段存储。

    持久化后该片段音频可被管线断点复用、分段试听与整章混音共同使用，
    且不再受临时资产过期清理影响；同一片段的旧版本文件会被自动清除。
    """
    candidate_ref = build_segment_asset_ref(
        run_id=str(candidate_payload.get("run") or ""),
        chapter_id=int(candidate_payload.get("chi") or 0),
        segment_index=segment_index,
        content_sha1=str(candidate_payload.get("sha1") or ""),
        extension=str(candidate_payload.get("ext") or "mp3"),
    )
    audio_bytes = load_persistent_segment_audio(candidate_ref)
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="候选音频文件不存在或已过期，请重新生成")
    expected_sha1 = str(candidate_payload.get("sha1") or "").strip().lower()
    if hashlib.sha1(audio_bytes).hexdigest() != expected_sha1:
        raise HTTPException(status_code=400, detail="候选音频内容校验失败，请重新生成")

    extension = normalize_audio_extension(str(candidate_payload.get("ext") or "") or "mp3")
    try:
        return save_persistent_segment_audio(
            chapter_audio_id=chapter_audio.id,
            segment_index=segment_index,
            segment_key=segment_key,
            audio_bytes=audio_bytes,
            preview_type=preview_type,
            output_format=extension,
        )
    except (OSError, TempSegmentStoreError, RuntimeError) as exc:
        logger.error("固化片段音频失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"保存片段音频失败: {exc}")


def _cleanup_candidate_asset(candidate_payload: Dict[str, Any], *, segment_index: int) -> str:
    """候选应用成功后回收候选文件，避免孤儿资产（失败不阻断主流程），返回资产 ref。"""
    candidate_ref = build_segment_asset_ref(
        run_id=str(candidate_payload.get("run") or ""),
        chapter_id=int(candidate_payload.get("chi") or 0),
        segment_index=segment_index,
        content_sha1=str(candidate_payload.get("sha1") or ""),
        extension=str(candidate_payload.get("ext") or "mp3"),
    )
    try:
        delete_temp_segment_prefix(None, {"cached_audio_paths": {segment_index: candidate_ref}})
    except (OSError, TempSegmentStoreError) as exc:
        logger.warning("回收候选片段音频失败: %s", exc)
    return candidate_ref


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
    previous_asset_refs = collect_segment_asset_refs(segment)
    segment = _apply_requested_segment_override(
        segments,
        segment_index,
        segment,
        request.segment,
    )

    legacy_request = request.model_copy(update={"preview_type": "voice"})
    runtime_config = _resolve_segment_regeneration_runtime_config(
        owned,
        legacy_request,
        segment,
    )
    synthesis = await _synthesize_segment_audio(
        legacy_request,
        segment,
        voice_mapping=runtime_config.voice_mapping,
        owner_user_id=getattr(getattr(owned, "current_user", None), "id", None),
    )
    segment = synthesis["segment"]
    segments[segment_index] = segment
    audio_bytes = synthesis["audio_bytes"]
    output_format = "wav" if audio_bytes.startswith(b"RIFF") else "mp3"
    try:
        audio_path = save_persistent_segment_audio(
            chapter_audio_id=chapter_audio.id,
            segment_index=segment_index,
            segment_key=str(segment.get("segment_key") or "").strip() or None,
            audio_bytes=audio_bytes,
            preview_type="voice",
            output_format=output_format,
        )
    except (OSError, TempSegmentStoreError, RuntimeError) as exc:
        logger.error("保存片段音频失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"保存音频失败: {exc}")
    # 签名与生成分块上下文按实际合成模型计算，供后续验签精确复现
    signature_chunk_limit = resolve_chapter_render_chunk_max_chars(
        [segment], default_tts_model=synthesis.get("tts_model")
    )
    _mark_segment_regenerated(
        segment,
        audio_path=audio_path,
        reason=request.reason,
        audio_cache_key=compute_segment_audio_cache_key(
            segment, render_chunk_max_chars=signature_chunk_limit
        ),
        audio_render_chunk_max_chars=signature_chunk_limit,
    )

    chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    db.commit()
    _cleanup_replaced_persistent_segment_assets(previous_asset_refs, segments)

    logger.info(
        f"片段重新生成成功: chapter_id={chapter_id}, "
        f"segment_index={segment_index}, model={synthesis['tts_model']}"
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "audio_path": audio_path,
        "audio_size": len(synthesis["audio_bytes"]),
        "model_used": synthesis["tts_model"],
        "chapter_audio_stale": True,
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
    # 指纹绑定签发时的存储片段状态（不含客户端覆盖）；
    # apply 时要求存储片段未变化，防止签发后脚本被修改仍误用旧候选
    stored_fingerprint = _compute_segment_candidate_fingerprint(current_segment)
    segment = _apply_requested_segment_override(
        candidate_segments,
        segment_index,
        current_segment,
        request.segment,
    )

    synthesis = await _generate_segment_regeneration_audio(request, segment, owned)
    segment = synthesis["segment"]
    candidate_segments[segment_index] = segment
    preview_type = synthesis["preview_type"]
    saved_audio = _save_regenerated_segment_audio(
        chapter_audio=chapter_audio,
        chapter_id=chapter_id,
        segment_index=segment_index,
        audio_bytes=synthesis["audio_bytes"],
        run_id_prefix=f"segment_regen_candidate_{preview_type}",
        preview_type=preview_type,
        segment_fingerprint=stored_fingerprint,
        effective_segment_fingerprint=synthesis["effective_segment_fingerprint"],
        synthesis_fingerprint=synthesis["synthesis_fingerprint"],
    )
    candidate_audio_path = saved_audio["audio_path"]

    # 候选文件登记为可回收资产：到期后由 janitor 物理回收，避免无限堆积
    register_segment_candidate_asset(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
        temp_segment_cache=saved_audio["temp_segment_cache"],
        candidate_contract={
            "revision": synthesis["candidate_contract_revision"],
            "base_segment_fingerprint": stored_fingerprint,
            "effective_segment": segment,
            "effective_segment_fingerprint": synthesis[
                "effective_segment_fingerprint"
            ],
            "synthesis_fingerprint": synthesis["synthesis_fingerprint"],
            "preview_type": preview_type,
            **(
                {"voice_identity_binding": synthesis["voice_identity_binding"]}
                if synthesis.get("voice_identity_binding")
                else {}
            ),
        },
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "candidate_id": saved_audio["candidate_id"],
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
    # 指纹绑定签发时的存储片段状态（不含客户端覆盖），与 apply 端校验一致
    stored_fingerprint = _compute_segment_candidate_fingerprint(current_segment)
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

    compiled = _build_segment_synthesis_payload(
        SegmentRegenerateRequest(preview_type="voice"),
        candidate_segment,
        allow_missing_voice=True,
    )
    candidate_segment = compiled["segment"]
    candidate_segments[segment_index] = candidate_segment

    saved_audio = _save_regenerated_segment_audio(
        chapter_audio=chapter_audio,
        chapter_id=chapter_id,
        segment_index=segment_index,
        audio_bytes=audio_bytes,
        run_id_prefix="segment_voice_recording_candidate",
        preview_type="voice",
        segment_fingerprint=stored_fingerprint,
        effective_segment_fingerprint=compiled["effective_segment_fingerprint"],
        synthesis_fingerprint=compiled["synthesis_fingerprint"],
        output_format=_audio_format_for_upload(file),
    )
    candidate_audio_path = saved_audio["audio_path"]

    # 上传候选同样登记为可回收资产，与 TTS 生成候选共用到期回收链路
    register_segment_candidate_asset(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
        temp_segment_cache=saved_audio["temp_segment_cache"],
        candidate_contract={
            "revision": compiled["candidate_contract_revision"],
            "base_segment_fingerprint": stored_fingerprint,
            "effective_segment": candidate_segment,
            "effective_segment_fingerprint": compiled[
                "effective_segment_fingerprint"
            ],
            "synthesis_fingerprint": compiled["synthesis_fingerprint"],
            "preview_type": "voice",
        },
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "candidate_id": saved_audio["candidate_id"],
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
    candidate_id = str(request.candidate_id or "").strip()
    if not candidate_id:
        raise HTTPException(status_code=400, detail="candidate_id 不能为空")

    db = owned.db
    chapter_audio = get_active_chapter_audio_for_project(
        db=db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    candidate_payload = verify_segment_candidate_token(
        candidate_id,
        chapter_audio_id=chapter_audio.id,
        segment_index=segment_index,
    )
    if candidate_payload is None:
        raise HTTPException(status_code=400, detail="候选音频凭证无效或已过期，请重新生成候选")

    # 候选类型与片段指纹均由签发时绑定，apply 不重新接受客户端指定，
    # 防止 mix 候选被标成 voice、或文本 A 的音频被写成文本 B
    bound_preview_type = str(candidate_payload.get("pt") or "").strip().lower()
    bound_fingerprint = str(candidate_payload.get("fp") or "").strip()
    bound_effective_fingerprint = str(candidate_payload.get("efp") or "").strip()
    bound_synthesis_fingerprint = str(candidate_payload.get("sfp") or "").strip()
    if not all(
        (
            bound_preview_type,
            bound_fingerprint,
            bound_effective_fingerprint,
            bound_synthesis_fingerprint,
        )
    ):
        raise HTTPException(status_code=400, detail="候选凭证缺少类型或指纹绑定，请重新生成候选")

    requested_preview_type = _normalize_segment_regeneration_preview_type(
        getattr(request, "preview_type", "voice")
    )
    if requested_preview_type != bound_preview_type:
        raise HTTPException(status_code=400, detail="候选类型与凭证绑定不一致，请重新生成候选")

    segments = _load_chapter_segments(chapter_audio)
    current_segment = _get_segment_or_404(segments, segment_index)
    previous_asset_refs = collect_segment_asset_refs(current_segment)
    # 指纹与签发时的存储片段比对（在应用客户端覆盖之前），
    # 防止候选音频被应用到签发后又被修改的片段参数上
    if _compute_segment_candidate_fingerprint(current_segment) != bound_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="片段参数与候选生成时不一致，请重新生成候选",
        )

    candidate_ref = build_segment_asset_ref(
        run_id=str(candidate_payload.get("run") or ""),
        chapter_id=int(candidate_payload.get("chi") or 0),
        segment_index=segment_index,
        content_sha1=str(candidate_payload.get("sha1") or ""),
        extension=str(candidate_payload.get("ext") or "mp3"),
    )
    candidate_contract = load_segment_candidate_contract(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
        asset_ref=candidate_ref,
    )
    if not isinstance(candidate_contract, dict):
        raise HTTPException(status_code=400, detail="候选登记不存在或已失效，请重新生成候选")
    if not segment_candidate_contract_matches_token(
        candidate_payload,
        candidate_contract,
    ):
        raise HTTPException(
            status_code=400,
            detail="候选登记与凭证不一致，请重新生成候选",
        )
    effective_segment = candidate_contract["effective_segment"]

    # request.segment 仅为兼容旧客户端保留；候选音频只能应用签发时登记的 B。
    segment = copy.deepcopy(effective_segment)
    # 候选合同不拥有服务端资产字段；保留 apply 时的最新轨道，再由下方仅替换目标轨道。
    for field_name in SERVER_MANAGED_SEGMENT_ASSET_FIELDS:
        if field_name in current_segment:
            segment[field_name] = copy.deepcopy(current_segment[field_name])
        else:
            segment.pop(field_name, None)
    segments[segment_index] = segment
    preview_type = bound_preview_type
    persistent_audio_path = _persist_applied_candidate_audio(
        chapter_audio=chapter_audio,
        segment_index=segment_index,
        segment_key=str(current_segment.get("segment_key") or "").strip() or None,
        candidate_payload=candidate_payload,
        preview_type=preview_type,
    )
    # 候选应用时的合成模型不可回溯，按片段自身参数推断分块上下文，
    # 保证记录的上下文与签名计算策略严格一致
    signature_chunk_limit = resolve_chapter_render_chunk_max_chars([segment])
    audio_cache_key = (
        compute_segment_audio_cache_key(
            segment, render_chunk_max_chars=signature_chunk_limit
        )
        if preview_type == "voice"
        else None
    )
    _mark_segment_regeneration_candidate_applied(
        segment,
        audio_path=persistent_audio_path,
        preview_type=preview_type,
        reason=request.reason,
        audio_cache_key=audio_cache_key,
        audio_render_chunk_max_chars=signature_chunk_limit,
    )

    chapter_audio.script_json = json.dumps(segments, ensure_ascii=False)
    db.commit()
    _cleanup_replaced_persistent_segment_assets(previous_asset_refs, segments)

    cleaned_ref = _cleanup_candidate_asset(candidate_payload, segment_index=segment_index)
    # 候选已固化/回收，结束对应登记记录，避免 janitor 重复处理
    finalize_segment_candidate_runs(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        segment_index=segment_index,
        asset_ref=cleaned_ref,
    )

    return {
        "success": True,
        "segment_index": segment_index,
        "audio_path": persistent_audio_path,
        "preview_type": preview_type,
        # 片段音频已更新，旧整章混音已过期待重混
        "chapter_audio_stale": True,
        "segment": segment,
    }


@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/segments/{segment_index:int}/regeneration-candidate/audio")
async def get_segment_regeneration_candidate_audio(
    audiobook_project_id: int,
    chapter_id: int,
    segment_index: int,
    candidate_id: Optional[str] = Query(None),
    audio_path: Optional[str] = Query(None),
    preview_type: Optional[str] = Query(None),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """试听片段候选音频或已保存的片段音频。

    - candidate_id：服务端签发的候选凭证（候选音频试听）
    - audio_path + preview_type：已保存片段音频，服务端校验其与剧本登记值一致
    - 仅 preview_type=sfx/bgm：无持久化分轨时按管线 checkpoint 时间线实时渲染
    """
    candidate_token = str(candidate_id or "").strip()
    persisted_audio_ref = str(audio_path or "").strip()
    normalized_preview_type = _normalize_segment_regeneration_preview_type(preview_type)
    # 音效/配乐允许仅凭 preview_type 试听：管线产物无持久化分轨，服务端按时间线渲染
    if (
        not candidate_token
        and not persisted_audio_ref
        and normalized_preview_type not in {"sfx", "bgm"}
    ):
        raise HTTPException(status_code=400, detail="candidate_id 或 audio_path 不能为空")

    chapter_audio = get_active_chapter_audio_for_project(
        db=owned.db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    if candidate_token:
        candidate_payload = verify_segment_candidate_token(
            candidate_token,
            chapter_audio_id=chapter_audio.id,
            segment_index=segment_index,
        )
        if candidate_payload is None:
            raise HTTPException(status_code=400, detail="候选音频凭证无效或已过期，请重新生成候选")

        candidate_ref = build_segment_asset_ref(
            run_id=str(candidate_payload.get("run") or ""),
            chapter_id=int(candidate_payload.get("chi") or 0),
            segment_index=segment_index,
            content_sha1=str(candidate_payload.get("sha1") or ""),
            extension=str(candidate_payload.get("ext") or "mp3"),
        )
        # token 仍在 TTL 内不代表候选仍可用：同轨新候选可能已经顶替并回收旧登记。
        # registry 是候选生命周期的权威来源，试听与 apply 必须共享这条校验。
        candidate_contract = load_segment_candidate_contract(
            owned.db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            segment_index=segment_index,
            asset_ref=candidate_ref,
        )
        contract_preview_type = str(
            (candidate_contract or {}).get("preview_type") or ""
        ).strip().lower()
        token_preview_type = str(candidate_payload.get("pt") or "").strip().lower()
        if not isinstance(candidate_contract, dict) or contract_preview_type != token_preview_type:
            raise HTTPException(status_code=400, detail="候选已被替换或登记已失效，请重新生成候选")
        if not segment_candidate_contract_matches_token(
            candidate_payload,
            candidate_contract,
        ):
            raise HTTPException(
                status_code=400,
                detail="候选登记与凭证不一致，请重新生成候选",
            )
        audio_by_index = load_cached_segment_audio(
            {"cached_audio_paths": {segment_index: candidate_ref}},
            max_segment_count=segment_index + 1,
        )
        audio_bytes = audio_by_index.get(segment_index)
        if not audio_bytes:
            raise HTTPException(status_code=404, detail="候选音频文件不存在")
        audio_ref = candidate_ref
    else:
        # 已保存片段：仅允许剧本中登记的持久化资产 ref，防止任意路径读取
        segments = _load_chapter_segments(chapter_audio)
        segment = _get_segment_or_404(segments, segment_index)
        stored_ref = str(
            segment.get(_segment_audio_path_field(normalized_preview_type)) or ""
        ).strip()
        if stored_ref:
            if (
                stored_ref != persisted_audio_ref
                or not is_persistent_segment_asset_ref(persisted_audio_ref)
            ):
                raise HTTPException(status_code=400, detail="片段音频路径无效")
            audio_bytes = load_persistent_segment_audio(persisted_audio_ref)
            if not audio_bytes:
                raise HTTPException(status_code=404, detail="片段音频文件不存在")
            audio_ref = persisted_audio_ref
        elif normalized_preview_type in {"sfx", "bgm"}:
            # 管线生成的音效/配乐没有持久化分轨：按 checkpoint 时间线实时渲染
            audio_bytes = _render_segment_timeline_preview(
                owned,
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                segment_index=segment_index,
                preview_type=normalized_preview_type,
            )
            audio_ref = "segment_timeline_preview.mp3"
        else:
            raise HTTPException(status_code=400, detail="片段音频路径无效")

    return Response(
        content=audio_bytes,
        media_type=_media_type_for_audio_path(audio_ref),
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


