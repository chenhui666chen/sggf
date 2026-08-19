"""场景编辑器路由（GUIDE §3.2/§3.4）。

- ``GET editor-document``：聚合 SceneEditorDocument（三维投影 + 场景列表 + 三条链 head）；
- ``PUT editor-document?edit_type=dialogue|director_override|voice_binding``：三类场景编辑；
- ``POST dialogue-review``：dialogue 链独立审批入口（R8 审批闭环）；
- ``GET /scenes/{artifact_id}/stream|audit-stream``：场景音频试听与审计访问。

资源标识统一使用 ``audiobook_project_id``，所有端点经 ``get_owned_audiobook_project``
校验批次归属；编辑/审批端点仅对 seed_scene 批次开放（legacy_stems 走旧剧本接口）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import Body, Depends, HTTPException, Query, status
from fastapi.responses import Response
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.env_loader import get_backend_root
from app.core.permissions import is_admin
from app.core.security import get_current_user, get_current_user_optional
from app.db.base import get_db
from app.models.audiobook import AudiobookProject, SceneAudioArtifact
from app.models.user import User
from app.services.audiobook.repository import ChapterRepository
from app.services.audiobook.scene_edit_revision_service import (
    EDIT_TYPES,
    RevisionConflictError,
    append_scene_edit_revision,
    append_voice_binding_revision,
    build_scene_editor_document,
    compute_revision_set_hash,
    get_revision_heads_projection,
)

from app.api.v1.audiobook_api import router
from app.api.v1.audiobook_api import routes_script as script_routes
from app.api.v1.audiobook_api.dependencies import (
    OwnedAudiobookProject,
    get_active_chapter_audio_for_project,
    get_owned_audiobook_project,
    resolve_owned_audiobook_project,
)

logger = logging.getLogger(__name__)

SCENE_STREAM_PURPOSE = "scene_audio_stream"
SCENE_STREAM_TTL_SECONDS = 2 * 60 * 60

# artifact 正式存储根目录（§3.4：backend/data/scene_audio_artifacts/）
SCENE_ARTIFACT_ROOT = get_backend_root() / "data" / "scene_audio_artifacts"

_REVIEW_VERDICTS = frozenset({"reviewed", "approved"})


# ——— 辅助 ———


def _require_seed_scene_batch(owned: OwnedAudiobookProject) -> None:
    """场景编辑器仅对 seed_scene 批次开放（legacy_stems 走旧剧本接口）。"""
    engine_mode = str(getattr(owned.audiobook_project, "engine_mode", None) or "")
    if engine_mode != "seed_scene":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前批次非 seed_scene 引擎，请使用剧本编辑器",
        )


def _resolve_chapter_audio(owned: OwnedAudiobookProject, chapter_id: int):
    """校验章节从属（章节必须属于该批次所属源项目）并返回章节音频记录。"""
    chapter = ChapterRepository.get_active_project_chapter(
        owned.db,
        project_id=owned.project.id,
        chapter_id=chapter_id,
    )
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在或不属于该项目",
        )
    return get_active_chapter_audio_for_project(
        db=owned.db,
        audiobook_project_id=owned.audiobook_project.id,
        chapter_id=chapter_id,
    )


def _create_scene_play_token(*, user_id: int, artifact_id: str) -> tuple[str, datetime]:
    """短期场景试听 token（复用 _create_stream_access_token 模式）。"""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SCENE_STREAM_TTL_SECONDS)
    payload = {
        "sub": str(user_id),
        "purpose": SCENE_STREAM_PURPOSE,
        "artifact_id": artifact_id,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expires_at


def _resolve_scene_stream_user(
    *,
    db: Session,
    token: str,
    artifact_id: str,
) -> User:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        ) from exc

    if (
        payload.get("purpose") != SCENE_STREAM_PURPOSE
        or str(payload.get("artifact_id") or "") != artifact_id
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )

    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        ) from exc

    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )

    from app.services.audiobook.repository import UserRepository

    user = UserRepository.get_active_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid stream token",
        )
    return user


def _build_scene_audio_url(
    *,
    db: Session,
    current_user: User,
    artifact: SceneAudioArtifact,
) -> str:
    token, _ = _create_scene_play_token(
        user_id=current_user.id,
        artifact_id=artifact.artifact_id,
    )
    return (
        f"/api/v1/audiobook/scenes/{artifact.artifact_id}/stream"
        f"?play_token={quote(token, safe='')}"
    )


def _artifact_file_path(artifact: SceneAudioArtifact) -> str:
    return str(SCENE_ARTIFACT_ROOT / str(artifact.stored_rel_path))


def _artifact_media_type(file_path: str) -> str:
    extension = Path(file_path).suffix.lstrip(".").lower() or "mp3"
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4b": "audio/mp4",
        "m4a": "audio/mp4",
    }.get(extension, "application/octet-stream")


def _revision_response(
    *,
    db: Session,
    audiobook_project_id: int,
    chapter_id: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    heads = get_revision_heads_projection(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    response: Dict[str, Any] = {
        "success": True,
        "revision_heads": heads,
        "revision_set_hash": compute_revision_set_hash(heads),
    }
    if extra:
        response.update(extra)
    return response


def _raise_conflict(exc: RevisionConflictError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "文档已被他人修改，请刷新后重试",
            "current_head_revision_hash": exc.current_head_hash,
        },
    ) from exc


# ——— 编辑器文档 ———


@router.get(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/editor-document",
    response_model=dict,
)
async def get_scene_editor_document(
    audiobook_project_id: int,
    chapter_id: int,
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """聚合 SceneEditorDocument（§3.3）。

    返回场景列表（scene_id/status/attempts/scene_audio_url/quality_report）、
    分段归属、章节音频 URL 与三维投影状态；不返回本地 audio_path。
    """
    db = owned.db
    _require_seed_scene_batch(owned)
    chapter_audio = _resolve_chapter_audio(owned, chapter_id)

    document = build_scene_editor_document(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_audio=chapter_audio,
        scene_audio_url_builder=lambda artifact: _build_scene_audio_url(
            db=db,
            current_user=owned.current_user,
            artifact=artifact,
        ),
    )
    document.chapter_audio_url = (
        f"/api/v1/audiobook/download/{audiobook_project_id}/{chapter_id}"
        if chapter_audio.audio_path
        else None
    )
    document.chapter_audio_stale = script_routes._derive_chapter_audio_stale(
        db,
        chapter_audio=chapter_audio,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    return asdict(document)


# ——— 三类场景编辑 ———


def _apply_dialogue_edit(
    *,
    db: Session,
    owned: OwnedAudiobookProject,
    chapter_id: int,
    chapter_audio,
    request_body: Dict[str, Any],
) -> Dict[str, Any]:
    segments_in = request_body.get("script_segments")
    if not isinstance(segments_in, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="script_segments 必须为数组",
        )
    base_revision_hash = request_body.get("base_revision_hash")

    existing_segments = script_routes._parse_existing_script_segments(
        chapter_audio.script_json
    )
    sanitized_segments = script_routes._sanitize_incoming_script_segments(
        segments_in,
        existing_segments,
    )
    semantic_changed = (
        script_routes._script_semantic_fingerprint(sanitized_segments)
        != script_routes._script_semantic_fingerprint(existing_segments)
    )
    # 语义变化时 affected_anchors 包含全部受影响 segment_key（§2.9）
    anchors = (
        [
            str(segment.get("segment_key"))
            for segment in sanitized_segments
            if isinstance(segment, dict) and segment.get("segment_key")
        ]
        if semantic_changed
        else []
    )
    payload = {
        "script_segments": sanitized_segments,
        "semantic_fingerprint": script_routes._script_semantic_fingerprint(
            sanitized_segments
        ),
    }
    try:
        append_scene_edit_revision(
            db,
            audiobook_project_id=owned.audiobook_project.id,
            chapter_id=chapter_id,
            chapter_audio_id=chapter_audio.id,
            edit_type="dialogue",
            payload=payload,
            affected_anchors=anchors,
            base_revision_hash=base_revision_hash,
            operator_user_id=owned.current_user.id,
            base_run_id=(
                chapter_audio.desired_run_id or chapter_audio.published_run_id
            ),
        )
    except RevisionConflictError as exc:
        _raise_conflict(exc)

    # 台词编辑更新 script_json（审定剧本），不删除 checkpoint
    new_script_json = json.dumps(sanitized_segments, ensure_ascii=False)
    if new_script_json != (chapter_audio.script_json or ""):
        chapter_audio.script_json = new_script_json
    if semantic_changed:
        chapter_audio.script_status = "pending"
        chapter_audio.script_review_json = None
        chapter_audio.final_audio_review_json = None
        chapter_audio.segment_reviews_json = None
        chapter_audio.script_review_version = None
    db.commit()

    return _revision_response(
        db=db,
        audiobook_project_id=owned.audiobook_project.id,
        chapter_id=chapter_id,
        extra={
            "script_status": chapter_audio.script_status or "pending",
            "semantic_changed": semantic_changed,
        },
    )


def _apply_director_override_edit(
    *,
    db: Session,
    owned: OwnedAudiobookProject,
    chapter_id: int,
    chapter_audio,
    request_body: Dict[str, Any],
) -> Dict[str, Any]:
    scene_id = str(request_body.get("scene_id") or "").strip()
    if not scene_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scene_id 不能为空",
        )
    stable_anchors = request_body.get("stable_anchors") or {}
    if not isinstance(stable_anchors, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="stable_anchors 必须为对象",
        )
    overrides = request_body.get("overrides")
    if not isinstance(overrides, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overrides 必须为数组",
        )
    payload = {
        "scene_id": scene_id,
        "stable_anchors": stable_anchors,
        "overrides": overrides,
    }
    try:
        append_scene_edit_revision(
            db,
            audiobook_project_id=owned.audiobook_project.id,
            chapter_id=chapter_id,
            chapter_audio_id=chapter_audio.id,
            edit_type="director_override",
            payload=payload,
            affected_anchors=[scene_id],
            base_revision_hash=request_body.get("base_revision_hash"),
            operator_user_id=owned.current_user.id,
            base_run_id=(
                chapter_audio.desired_run_id or chapter_audio.published_run_id
            ),
        )
    except RevisionConflictError as exc:
        _raise_conflict(exc)
    # 导演覆盖不修改 ScriptSegment.text（§2.6）
    db.commit()

    return _revision_response(
        db=db,
        audiobook_project_id=owned.audiobook_project.id,
        chapter_id=chapter_id,
    )


def _apply_voice_binding_edit(
    *,
    db: Session,
    owned: OwnedAudiobookProject,
    chapter_id: int,
    chapter_audio,
    request_body: Dict[str, Any],
) -> Dict[str, Any]:
    tts_model = str(request_body.get("tts_model") or "").strip()
    if not tts_model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tts_model 不能为空",
        )
    characters = request_body.get("characters")
    if not isinstance(characters, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="characters 必须为数组",
        )
    try:
        append_voice_binding_revision(
            db,
            audiobook_project_id=owned.audiobook_project.id,
            chapter_id=chapter_id,
            chapter_audio_id=chapter_audio.id,
            project_id=owned.project.id,
            engine_mode=str(owned.audiobook_project.engine_mode or "seed_scene"),
            tts_model=tts_model,
            characters=characters,
            base_revision_hash=request_body.get("base_revision_hash"),
            operator_user_id=owned.current_user.id,
        )
    except RevisionConflictError as exc:
        _raise_conflict(exc)
    db.commit()

    return _revision_response(
        db=db,
        audiobook_project_id=owned.audiobook_project.id,
        chapter_id=chapter_id,
    )


@router.put(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/editor-document",
    response_model=dict,
)
async def update_scene_editor_document(
    audiobook_project_id: int,
    chapter_id: int,
    edit_type: str = Query(...),
    request_body: Dict[str, Any] = Body(...),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """三类场景编辑（§3.2）。

    - ``edit_type=dialogue``：台词编辑，写回 script_json（不删除 checkpoint）；
    - ``edit_type=director_override``：导演覆盖，写入 SceneEditRevision（不修改原文）；
    - ``edit_type=voice_binding``：音色绑定双写（当前章节局部覆盖 + 未来批次默认值）。

    请求体携带 ``base_revision_hash``，原子并发校验失配返回 409。
    """
    db = owned.db
    _require_seed_scene_batch(owned)
    chapter_audio = _resolve_chapter_audio(owned, chapter_id)

    if edit_type == "dialogue":
        return _apply_dialogue_edit(
            db=db,
            owned=owned,
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            request_body=request_body,
        )
    if edit_type == "director_override":
        return _apply_director_override_edit(
            db=db,
            owned=owned,
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            request_body=request_body,
        )
    if edit_type == "voice_binding":
        return _apply_voice_binding_edit(
            db=db,
            owned=owned,
            chapter_id=chapter_id,
            chapter_audio=chapter_audio,
            request_body=request_body,
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"edit_type 必须为 {'/'.join(EDIT_TYPES)} 之一",
    )


# ——— dialogue 审批闭环（R8/§2.9） ———


@router.post(
    "/projects/{audiobook_project_id:int}/chapters/{chapter_id:int}/dialogue-review",
    response_model=dict,
)
async def review_scene_dialogue(
    audiobook_project_id: int,
    chapter_id: int,
    request_body: Dict[str, Any] = Body(...),
    owned: OwnedAudiobookProject = Depends(get_owned_audiobook_project),
):
    """seed_scene 批次 dialogue 链独立审批入口（R8，§2.9 审批闭环）。

    请求体：``{verdict: "reviewed"|"approved", review_json, base_revision_set_hash}``。
    锁后重算 ``revision_set_hash`` 与请求基线比对（失配 409）；审核证据写
    ``script_review_json`` + ``script_review_version``；approved 后允许重渲染。
    """
    db = owned.db
    _require_seed_scene_batch(owned)
    chapter_audio = _resolve_chapter_audio(owned, chapter_id)

    verdict = str(request_body.get("verdict") or "").strip()
    if verdict not in _REVIEW_VERDICTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verdict 必须为 reviewed/approved",
        )
    review_json = request_body.get("review_json") or {}
    if not isinstance(review_json, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="review_json 必须为对象",
        )
    base_revision_set_hash = request_body.get("base_revision_set_hash")

    # 并发基线（R9 锁后重算协议，P1-2）：同一事务内锁定章节行 + 三条 head，
    # 再重算 revision_set_hash（读取与比对必须在同一事务内完成，消除 TOCTOU）
    from sqlalchemy import select

    from app.models.audiobook import ChapterAudio, SceneEditRevisionHead

    db.execute(
        select(ChapterAudio.id)
        .where(ChapterAudio.id == chapter_audio.id)
        .with_for_update()
    )
    for edit_type in EDIT_TYPES:
        db.execute(
            select(SceneEditRevisionHead.id)
            .where(
                SceneEditRevisionHead.audiobook_project_id == audiobook_project_id,
                SceneEditRevisionHead.chapter_id == chapter_id,
                SceneEditRevisionHead.edit_type == edit_type,
            )
            .with_for_update()
        )

    heads = get_revision_heads_projection(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    current_set_hash = compute_revision_set_hash(heads)
    if base_revision_set_hash and current_set_hash != base_revision_set_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "文档已被他人修改，请刷新后重试",
                "current_revision_set_hash": current_set_hash,
            },
        )

    # 状态机：pending → reviewed → approved（verdict=approved 含一次性直批）
    current_status = str(chapter_audio.script_status or "pending")
    if current_status not in {"pending", "reviewed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"当前 script_status={current_status} 不允许审批迁移",
        )
    new_status = "approved" if verdict == "approved" else "reviewed"

    chapter_audio.script_status = new_status
    chapter_audio.script_review_json = json.dumps(review_json, ensure_ascii=False)
    chapter_audio.script_review_version = f"rev-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    db.commit()

    return {
        "success": True,
        "script_status": new_status,
        "script_review_version": chapter_audio.script_review_version,
    }


# ——— 场景音频试听与审计访问（§3.4） ———


def _resolve_artifact_owned(
    *,
    db: Session,
    current_user: User,
    artifact_id: str,
    include_inactive: bool = False,
) -> SceneAudioArtifact:
    artifact = (
        db.query(SceneAudioArtifact)
        .filter(SceneAudioArtifact.artifact_id == artifact_id)
        .first()
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="场景音频不存在",
        )
    if not include_inactive:
        if artifact.status != "active" or artifact.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="场景音频不存在",
            )
    resolve_owned_audiobook_project(
        db=db,
        current_user=current_user,
        audiobook_project_id=artifact.audiobook_project_id,
        forbidden_detail="无权限访问该场景音频",
    )
    return artifact


def _stream_artifact_file(artifact: SceneAudioArtifact) -> Response:
    file_path = _artifact_file_path(artifact)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="场景音频文件不存在",
        )
    try:
        content = Path(file_path).read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取场景音频失败: {exc}",
        ) from exc
    return Response(
        content=content,
        media_type=_artifact_media_type(file_path),
        headers={
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range",
        },
    )


@router.get("/scenes/{artifact_id}/stream")
async def stream_scene_artifact(
    artifact_id: str,
    play_token: Optional[str] = Query(default=None),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """场景音频试听（仅 status=active 且未删除；play_token 或登录态二选一）。"""
    if play_token:
        resolved_user = _resolve_scene_stream_user(
            db=db,
            token=play_token,
            artifact_id=artifact_id,
        )
    elif current_user:
        resolved_user = current_user
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing stream credentials",
        )

    artifact = _resolve_artifact_owned(
        db=db,
        current_user=resolved_user,
        artifact_id=artifact_id,
        include_inactive=False,
    )
    return _stream_artifact_file(artifact)


@router.get("/scenes/{artifact_id}/audit-stream")
async def audit_stream_scene_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审计访问（仅管理员/项目所有者，不限 deleted_at 与 status）。

    响应头携带完整 artifact 信息（status/deleted_at/来源/哈希），供审计核对。
    """
    artifact = _resolve_artifact_owned(
        db=db,
        current_user=current_user,
        artifact_id=artifact_id,
        include_inactive=True,
    )
    if not is_admin(current_user):
        # 项目所有者已由 resolve_owned_audiobook_project 校验；非所有者且非管理员拒绝
        from app.services.audiobook.repository import ProjectRepository

        audiobook_project = db.get(AudiobookProject, artifact.audiobook_project_id)
        project = (
            ProjectRepository.get_user_project(
                db,
                current_user.id,
                audiobook_project.project_id,
            )
            if audiobook_project is not None
            else None
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问该场景音频",
            )

    response = _stream_artifact_file(artifact)
    response.headers["X-Artifact-Id"] = artifact.artifact_id
    response.headers["X-Artifact-Status"] = artifact.status or ""
    response.headers["X-Artifact-Deleted-At"] = (
        artifact.deleted_at.isoformat() if artifact.deleted_at else ""
    )
    response.headers["X-Artifact-Source-Kind"] = artifact.source_kind or ""
    response.headers["X-Artifact-Digest"] = artifact.content_digest or ""
    response.headers["X-Artifact-Scene-Id"] = artifact.scene_id or ""
    response.headers["X-Artifact-Topology-Hash"] = artifact.scene_topology_hash or ""
    return response
