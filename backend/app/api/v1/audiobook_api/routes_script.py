from __future__ import annotations

import logging
import json
import hashlib
from uuid import uuid4

from fastapi import Depends, HTTPException, status

from app.schemas.audiobook import (
    ChapterScriptUpdateRequest,
)
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_owned_audiobook_project,
)
from app.services.audiobook.repository import (
    ChapterAudioRepository,
    ChapterAudioRunRepository,
    ChapterRepository,
)
from app.services.audiobook.chapter_segment_assets import (
    SERVER_MANAGED_SEGMENT_ASSET_FIELDS,
    is_persistent_segment_asset_ref,
    segment_audio_signature_status,
)
from app.services.audiobook.segment_synthesis_contract import (
    compute_segment_semantic_fingerprint,
    sanitize_segment_override,
)

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

# 产出整章音频的 run 类型（用于推导整章混音是否过期）
_CHAPTER_AUDIO_PRODUCING_RUN_TYPES = ("chapter_remix", "audio_from_scripts", "full")

# 片段身份与数组位置解耦。新剧本保存时由服务端补齐；老剧本没有该字段时，
# 先按唯一语义指纹迁移，无法确认归属则不携带旧资产，避免 mix/stem 错绑。
_SEGMENT_KEY_FIELD = "segment_key"
_SEGMENT_KEY_MAX_LENGTH = 96
_SEGMENT_IDENTITY_FIELDS = (
    "type",
    "text",
    "speaker",
    "speaker_name",
    "character_name",
    "role_name",
    "original_text",
)


def _derive_chapter_audio_stale(
    db,
    *,
    chapter_audio,
    audiobook_project_id: int,
    chapter_id: int,
) -> bool:
    """按签名与时间线推导整章音频是否过期（不依赖客户端本地标记）。

    判定任一成立即过期：

    1. 存在已保存音频的片段，其签名与当前片段参数不一致（剧本已编辑）；
    2. 最近一次整章生成/混音完成后，章节记录又被更新（如应用了
       新的片段候选音频，整章混音落后于片段音频）。
    """
    if chapter_audio is None or not getattr(chapter_audio, "audio_path", None):
        return False
    try:
        segments = json.loads(getattr(chapter_audio, "script_json", None) or "[]")
    except (TypeError, ValueError):
        return False
    if not isinstance(segments, list):
        return False

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        audio_ref = str(segment.get("audio_path") or "").strip()
        if not audio_ref:
            continue
        # 仅明确判定过期（stale）才报整章过期；
        # 旧版无法复现的签名（unverifiable）不误报
        if (
            is_persistent_segment_asset_ref(audio_ref)
            and segment_audio_signature_status(segment) == "stale"
        ):
            return True

    latest_runs = ChapterAudioRunRepository.list_completed_runs_for_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_types=_CHAPTER_AUDIO_PRODUCING_RUN_TYPES,
        limit=1,
    )
    finished_at = getattr(latest_runs[0], "finished_at", None) if latest_runs else None
    chapter_updated_at = getattr(chapter_audio, "updated_at", None)
    if finished_at is not None and chapter_updated_at is not None:
        try:
            if chapter_updated_at > finished_at:
                return True
        except TypeError:
            logger.debug("stale 推导时间戳不可比，已忽略")
    return False


def _parse_existing_script_segments(script_json):
    try:
        segments = json.loads(script_json or "[]")
    except (TypeError, ValueError):
        return []
    return segments if isinstance(segments, list) else []


def _normalize_segment_key(value) -> str:
    """规范化片段身份键，不接受路径、空白或过长的客户端值。"""
    raw = str(value or "").strip()
    if not raw or len(raw) > _SEGMENT_KEY_MAX_LENGTH:
        return ""
    if any(char.isspace() for char in raw) or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for char in raw
    ):
        return ""
    return raw


def _segment_identity_fingerprint(segment) -> str:
    if not isinstance(segment, dict):
        return ""
    projected = {
        field: segment.get(field)
        for field in _SEGMENT_IDENTITY_FIELDS
        if field in segment and segment.get(field) not in (None, "", [], {})
    }
    if not projected:
        return ""
    return compute_segment_semantic_fingerprint(projected)


def _segment_key_seed(index: int, segment: dict) -> str:
    identity = _segment_identity_fingerprint(segment)
    digest = hashlib.sha1(
        f"legacy:{index}:{identity}".encode("utf-8")
    ).hexdigest()[:16]
    return f"seg_legacy_{index}_{digest}"


def _new_segment_key() -> str:
    return f"seg_{uuid4().hex}"


def _build_existing_segment_records(existing_segments):
    records = []
    key_map = {}
    identity_map = {}
    used_keys = set()
    for index, existing in enumerate(list(existing_segments or [])):
        if not isinstance(existing, dict):
            continue
        key = _normalize_segment_key(existing.get(_SEGMENT_KEY_FIELD))
        if not key or key in used_keys:
            key = _segment_key_seed(index, existing)
            suffix = 1
            while key in used_keys:
                key = f"{_segment_key_seed(index, existing)}_{suffix}"
                suffix += 1
        used_keys.add(key)
        record = {
            "index": index,
            "segment": existing,
            "key": key,
            "identity": _segment_identity_fingerprint(existing),
            "used": False,
        }
        records.append(record)
        key_map[key] = record
        if record["identity"]:
            identity_map.setdefault(record["identity"], []).append(record)
    return records, key_map, identity_map


def _match_existing_segment_record(
    *,
    cleaned: dict,
    incoming_index: int,
    records,
    key_map,
    identity_map,
):
    requested_key = _normalize_segment_key(cleaned.get(_SEGMENT_KEY_FIELD))
    if requested_key:
        requested = key_map.get(requested_key)
        if requested is not None and not requested["used"]:
            return requested
        return None

    identity = _segment_identity_fingerprint(cleaned)
    if identity:
        candidates = [
            record
            for record in identity_map.get(identity, [])
            if not record["used"]
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            # 旧剧本中可能有完全相同的旁白片段；只有完整语义能唯一确认时
            # 才迁移资产，否则宁可清除，也不把旧 mix 绑定到错误片段。
            full_fingerprint = compute_segment_semantic_fingerprint(cleaned)
            exact = [
                record
                for record in candidates
                if compute_segment_semantic_fingerprint(record["segment"])
                == full_fingerprint
            ]
            if len(exact) == 1:
                return exact[0]
            return None

    # 没有身份字段通常是旧客户端的局部 patch，按原位置保留语义和资产；
    # 完整片段但文本/角色已变更则不会走这里，避免重排后错绑。
    if not identity and 0 <= incoming_index < len(records):
        record = records[incoming_index]
        if not record["used"]:
            return record
    return None


def _sanitize_incoming_script_segments(incoming_segments, existing_segments):
    """清洗客户端片段并按稳定身份迁移服务端资产。

    新片段由服务端补齐 ``segment_key``。已有 key 优先；旧数据没有 key 时
    按唯一语义指纹匹配，无法确认归属时不保留任何旧音频资产。
    """
    records, key_map, identity_map = _build_existing_segment_records(existing_segments)
    sanitized = []
    for index, segment in enumerate(list(incoming_segments or [])):
        if not isinstance(segment, dict):
            sanitized.append(segment)
            continue
        # 先按候选生成相同的边界清除客户端音频路径和供应商派生提示；
        # 顶层 performance/instruct 等用户语义字段会保留，合成时重新编译。
        cleaned = sanitize_segment_override(segment) or {}
        record = _match_existing_segment_record(
            cleaned=cleaned,
            incoming_index=index,
            records=records,
            key_map=key_map,
            identity_map=identity_map,
        )
        if record is not None:
            record["used"] = True
        existing = record["segment"] if record is not None else {}
        # 客户端可回传已知 key；未知/重复/非法 key 不得借此获取其他片段资产。
        cleaned[_SEGMENT_KEY_FIELD] = (
            record["key"] if record is not None else _new_segment_key()
        )
        existing_semantic = sanitize_segment_override(existing) or {}
        # 对缺失字段按旧值补齐后再比较，兼容旧客户端只提交局部片段字段；
        # 显式传入空值仍会覆盖旧值并触发对应轨道失效。
        effective_semantic = {**existing_semantic, **cleaned}
        cleaned = dict(effective_semantic)
        voice_changed = _segment_semantic_fingerprint(
            effective_semantic,
            _VOICE_AUDIO_SEMANTIC_FIELDS,
        ) != _segment_semantic_fingerprint(existing_semantic, _VOICE_AUDIO_SEMANTIC_FIELDS)
        sfx_changed = _segment_semantic_fingerprint(
            effective_semantic,
            _SFX_SEMANTIC_FIELDS,
        ) != _segment_semantic_fingerprint(existing_semantic, _SFX_SEMANTIC_FIELDS)
        bgm_changed = _segment_semantic_fingerprint(
            effective_semantic,
            _BGM_SEMANTIC_FIELDS,
        ) != _segment_semantic_fingerprint(existing_semantic, _BGM_SEMANTIC_FIELDS)
        semantic_changed = compute_segment_semantic_fingerprint(effective_semantic) != compute_segment_semantic_fingerprint(existing_semantic)
        for field in SERVER_MANAGED_SEGMENT_ASSET_FIELDS:
            if field in {
                "audio_path",
                "audio_cache_key",
                "audio_chunk_cache_paths",
                "audio_render_chunk_max_chars",
                "audio_render_mode",
            } and voice_changed:
                continue
            if field == "sfx_audio_path" and sfx_changed:
                continue
            if field == "bgm_audio_path" and bgm_changed:
                continue
            if field == "mix_audio_path" and semantic_changed:
                continue
            if field in existing:
                cleaned[field] = existing[field]
            else:
                cleaned.pop(field, None)
        sanitized.append(cleaned)
    return sanitized


_VOICE_AUDIO_SEMANTIC_FIELDS = (
    "type",
    "text",
    "speaker",
    "speaker_name",
    "character_name",
    "role_name",
    "emotion",
    "performance_notes",
    "original_text",
    "adaptation_reason",
    "pause_before",
    "pause_after",
    "instruct_emotion",
    "instruct_scene",
    "instruct_role",
    "instruct_identity",
    "voice_params",
)
_SFX_SEMANTIC_FIELDS = ("sound_effects", "sound_effects_simple")
_BGM_SEMANTIC_FIELDS = ("music_cue", "music_cue_simple")


def _segment_semantic_fingerprint(segment, fields):
    projected = {field: segment.get(field) for field in fields if field in segment}
    return compute_segment_semantic_fingerprint(projected)


def _script_semantic_fingerprint(segments) -> str:
    payload = [
        compute_segment_semantic_fingerprint(segment)
        if isinstance(segment, dict)
        else segment
        for segment in list(segments or [])
    ]
    return hashlib.sha1(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _get_latest_completed_segment_timings(
    db,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> list:
    completed_runs = ChapterAudioRunRepository.list_completed_runs_for_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        run_types=("chapter_remix", "audio_from_scripts", "full"),
    )

    for run in completed_runs:
        checkpoint_json = getattr(run, "checkpoint_json", None)
        if not isinstance(checkpoint_json, dict):
            continue
        segment_timings = checkpoint_json.get("segment_timings")
        if isinstance(segment_timings, list) and segment_timings:
            return segment_timings

    return []


def _build_chapter_audio_url(audiobook_project_id: int, chapter_id: int) -> str:
    return f"/api/v1/audiobook/download/{audiobook_project_id}/{chapter_id}"

@router.get("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def get_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """获取指定章节的有声剧本与评审结果。

    仅返回最近一次生成/保存的剧本快照，不做版本历史。
    """
    db = owned.db
    project = owned.project

    # 获取章节剧本记录
    chapter_audio = ChapterAudioRepository.get_active_by_project_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    if not chapter_audio or not chapter_audio.script_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节剧本不存在，请先生成剧本",
        )

    try:
        script_segments = json.loads(chapter_audio.script_json)
    except json.JSONDecodeError as e:
        logger.error(f"❌ 解析章节剧本JSON失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="章节剧本数据损坏，请尝试重新生成",
        )

    script_review = None
    if chapter_audio.script_review_json:
        try:
            script_review = json.loads(chapter_audio.script_review_json)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ 解析章节剧本评审JSON失败 chapter_id={chapter_id}: {e}")

    return {
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status or "pending",
        "script_segments": script_segments,
        "chapter_audio_available": bool(chapter_audio.audio_path),
        # 服务端按签名/时间线派生的过期状态，前端不再依赖会话内本地标记
        "chapter_audio_stale": _derive_chapter_audio_stale(
            db,
            chapter_audio=chapter_audio,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        ),
        "chapter_audio_url": (
            _build_chapter_audio_url(audiobook_project_id, chapter_id)
            if chapter_audio.audio_path
            else ""
        ),
        "segment_timings": _get_latest_completed_segment_timings(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        ),
        "script_review": script_review,
    }


@router.put("/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/script", response_model=dict)
async def update_chapter_script(
    audiobook_project_id: int,
    chapter_id: int,
    request: ChapterScriptUpdateRequest,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """更新指定章节的有声剧本。

    - script_segments：覆盖写入最近一次剧本快照
    - script_status：可选，pending/reviewed/approved
    """
    db = owned.db
    project = owned.project

    # 验证章节是否属于该项目
    chapter = ChapterRepository.get_active_project_chapter(
        db,
        project_id=project.id,
        chapter_id=chapter_id,
    )

    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )

    # seed_scene 批次禁止直写 script_json（GUIDE §2.9 旧剧本接口统一拒绝）：
    # 台词编辑必须走场景编辑器（routes_scene_editor，edit_type=dialogue）的
    # revision 并发链，防绕过。legacy_stems 批次保持现状。
    if str(getattr(owned.audiobook_project, "engine_mode", None) or "") == "seed_scene":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="seed_scene 批次请使用场景编辑器修改台词（editor-document 接口）",
        )

    # 获取或创建章节音频记录
    chapter_audio = ChapterAudioRepository.get_active_by_project_chapter(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )

    if not chapter_audio:
        chapter_audio = ChapterAudio(
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        )
        db.add(chapter_audio)

    # 覆盖写入剧本（音频资产字段由服务端管理：按索引保留已有值，
    # 拒绝客户端注入任意 audio_path，防止跨资产读取）
    existing_segments = _parse_existing_script_segments(chapter_audio.script_json)
    sanitized_segments = _sanitize_incoming_script_segments(
        request.script_segments or [],
        existing_segments,
    )
    try:
        new_script_json = json.dumps(sanitized_segments, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        logger.error(f"❌ 序列化章节剧本失败 chapter_id={chapter_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="剧本数据格式不合法",
        )
    # 内容无变化时不触发写入，避免 updated_at 空转导致 stale 误报
    script_changed = new_script_json != (chapter_audio.script_json or "")
    semantic_changed = (
        _script_semantic_fingerprint(sanitized_segments)
        != _script_semantic_fingerprint(existing_segments)
    )
    previous_updated_at = getattr(chapter_audio, "updated_at", None)
    if script_changed:
        chapter_audio.script_json = new_script_json

    # 更新脚本状态（如有）
    if request.script_status:
        if request.script_status not in {"pending", "reviewed", "approved"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的script_status，必须为 pending/reviewed/approved",
            )
        chapter_audio.script_status = request.script_status

    # 剧本变化后，清空最终音频评审，防止混淆（同样避免无变化时 updated_at 空转）
    if semantic_changed:
        chapter_audio.final_audio_review_json = None

    # segment_key 迁移和审核状态变化不是音频语义变化，不能仅因 ORM 的
    # onupdate 时间戳而把已生成整章误标 stale；候选 apply 等资产更新仍会
    # 正常推进 updated_at，并由 _derive_chapter_audio_stale 检出。
    if not semantic_changed and previous_updated_at is not None:
        chapter_audio.updated_at = previous_updated_at

    db.commit()
    db.refresh(chapter_audio)

    return {
        "success": True,
        "chapter_id": chapter_id,
        "script_status": chapter_audio.script_status,
        "chapter_audio_available": bool(chapter_audio.audio_path),
        # 保存后按最新剧本重新推导过期状态（剧本变更会使已生成音频过期）
        "chapter_audio_stale": _derive_chapter_audio_stale(
            db,
            chapter_audio=chapter_audio,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        ),
    }


