"""场景编辑 revision 双表服务（GUIDE §2.9/§3.2/§3.3）。

- ``scene_edit_revisions``：严格 append-only 编辑历史（无 is_head，禁 UPDATE/DELETE）；
- ``scene_edit_revision_heads``：每 (project, chapter, edit_type) 一行，可 UPDATE，提供稳定行锁。

并发控制（R8/R9/R10）：
- 锁序：Project（voice_binding 双写）→ ChapterAudio 行 → dialogue head → director_override head → voice_binding head；
- 幂等短路：候选 hash 以请求携带的 ``base_revision_hash`` 为 parent 计算，先锁 head 后比对；
- SAVEPOINT 恢复协议：首次插入包 ``begin_nested()``，``IntegrityError`` 仅回滚到
  SAVEPOINT（严禁 ``session.rollback()``）后重读 head 判定幂等成功或 409。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audiobook import (
    AudiobookProject,
    ChapterAudio,
    ChapterAudioRun,
    SceneAudioArtifact,
    SceneEditRevision,
    SceneEditRevisionHead,
)
from app.models.project import Project
from app.services.audiobook.project_audio_config import (
    parse_project_audio_config,
    set_characters_for_model,
)

logger = logging.getLogger(__name__)

EDIT_TYPES = ("dialogue", "director_override", "voice_binding")

# 三维投影中"进行中"的执行状态（与前端 ACTIVE_EXECUTION_STATUSES 对齐）
_ACTIVE_RUN_STATUSES = ("queued", "pending", "running", "pause_requested")

_ARTIFACT_ACTIVE_STATUSES = frozenset({"active"})


class RevisionConflictError(Exception):
    """请求携带的 base_revision_hash 与当前 head 不匹配（HTTP 409）。"""

    def __init__(self, current_head_hash: Optional[str]):
        super().__init__("scene edit revision base mismatch")
        self.current_head_hash = current_head_hash


def canonical_json(payload: Any) -> str:
    """规范化 JSON 序列化（hash 与存储共用同一表示，避免双写漂移）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compute_input_signature(
    *,
    edit_type: str,
    payload: Any,
    affected_anchors: Optional[Sequence[str]],
) -> str:
    """payload 内容规范化签名（幂等去重，§2.9）。"""
    return _sha256(
        canonical_json(
            {
                "edit_type": edit_type,
                "payload": payload,
                "affected_anchors": list(affected_anchors or []),
            }
        )
    )


def compute_revision_hash(
    *,
    audiobook_project_id: int,
    chapter_id: int,
    edit_type: str,
    payload: Any,
    affected_anchors: Optional[Sequence[str]],
    parent_revision_hash: Optional[str],
) -> str:
    """链节点签名（含父引用，§2.9）；无父时 parent 项为空串。"""
    return _sha256(
        canonical_json(
            {
                "audiobook_project_id": audiobook_project_id,
                "chapter_id": chapter_id,
                "edit_type": edit_type,
                "payload": payload,
                "affected_anchors": list(affected_anchors or []),
                "parent_revision_hash": parent_revision_hash or "",
            }
        )
    )


def compute_revision_set_hash(last_revisions: Mapping[str, Any]) -> str:
    """三条链 head 投影的确定性签名（§2.9）。"""
    projection = {
        edit_type: (
            last_revisions.get(edit_type) or {}
        ).get("revision_hash")
        if isinstance(last_revisions.get(edit_type), Mapping)
        else None
        for edit_type in EDIT_TYPES
    }
    return _sha256(canonical_json(projection))


def _lock_chapter_audio_row(db: Session, chapter_audio_id: int) -> None:
    """按全局锁序锁定 ChapterAudio 行（R10/P1-4）。"""
    db.execute(
        select(ChapterAudio.id)
        .where(ChapterAudio.id == chapter_audio_id)
        .with_for_update()
    )


def _lock_head(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    edit_type: str,
) -> Optional[SceneEditRevisionHead]:
    return db.execute(
        select(SceneEditRevisionHead)
        .where(
            SceneEditRevisionHead.audiobook_project_id == audiobook_project_id,
            SceneEditRevisionHead.chapter_id == chapter_id,
            SceneEditRevisionHead.edit_type == edit_type,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _head_revision_hash(db: Session, head: SceneEditRevisionHead) -> str:
    revision = db.get(SceneEditRevision, head.head_revision_id)
    return revision.revision_hash if revision is not None else ""


def append_scene_edit_revision(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio_id: int,
    edit_type: str,
    payload: Any,
    affected_anchors: Optional[Sequence[str]],
    base_revision_hash: Optional[str],
    operator_user_id: Optional[int] = None,
    base_run_id: Optional[int] = None,
) -> SceneEditRevision:
    """追加一条场景编辑 revision（§2.9 原子并发）。

    - 锁 ChapterAudio 行 → 锁 head 行（FOR UPDATE）；
    - 幂等短路：head.revision_hash == 候选 hash（以请求 base 为 parent 计算）→ 返回原 revision；
    - base 失配 → 抛 :class:`RevisionConflictError`（409）；
    - SAVEPOINT 恢复协议：插入冲突仅回滚到 SAVEPOINT 后重读 head 判定。

    调用方负责在事务内提交/回滚。
    """
    if edit_type not in EDIT_TYPES:
        raise ValueError(f"unsupported edit_type: {edit_type}")

    _lock_chapter_audio_row(db, chapter_audio_id)
    head = _lock_head(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        edit_type=edit_type,
    )

    anchors = list(affected_anchors or [])
    payload_json = canonical_json(payload)
    anchors_json = canonical_json(anchors) if anchors else None
    candidate_hash = compute_revision_hash(
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        edit_type=edit_type,
        payload=payload,
        affected_anchors=anchors,
        parent_revision_hash=base_revision_hash,
    )
    input_signature = compute_input_signature(
        edit_type=edit_type,
        payload=payload,
        affected_anchors=anchors,
    )

    # 幂等短路：相同内容、相同父引用重复提交返回原 revision（R7）
    if head is not None:
        head_hash = _head_revision_hash(db, head)
        if head_hash == candidate_hash:
            revision = db.get(SceneEditRevision, head.head_revision_id)
            return revision

    # base 比对：head 已推进且与请求基线不一致 → 409
    if head is not None and _head_revision_hash(db, head) != (base_revision_hash or ""):
        raise RevisionConflictError(_head_revision_hash(db, head))
    if head is None and base_revision_hash:
        raise RevisionConflictError(None)

    revision = SceneEditRevision(
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        base_run_id=base_run_id,
        parent_revision_id=head.head_revision_id if head is not None else None,
        edit_type=edit_type,
        payload=payload_json,
        affected_anchors=anchors_json,
        input_signature=input_signature,
        revision_hash=candidate_hash,
        operator_user_id=operator_user_id,
    )

    # SAVEPOINT 恢复协议（R8/R9）：唯一约束冲突只回滚到 SAVEPOINT，
    # 严禁 session.rollback()（会终止外层事务并抛 PendingRollbackError）。
    # 注意：revision 必须在 begin_nested() 之后 add —— 回滚到 SAVEPOINT 时
    # 挂起的新对象会一并从 session 移除；若在 SAVEPOINT 外 add，回滚后对象
    # 仍挂在 session 中，重读 head 的 autoflush 会再次撞唯一约束。
    nested = db.begin_nested()
    try:
        db.add(revision)
        db.flush()  # revision 获得 id
        if head is None:
            head = SceneEditRevisionHead(
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                edit_type=edit_type,
                head_revision_id=revision.id,
            )
            db.add(head)
        else:
            head.head_revision_id = revision.id
        db.flush()
    except IntegrityError:
        nested.rollback()
        # 重读 head（并发 loser：另一事务已提交同 scope head 或同 hash revision）
        head = _lock_head(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            edit_type=edit_type,
        )
        if head is None:
            raise
        head_hash = _head_revision_hash(db, head)
        if head_hash == candidate_hash:
            return db.get(SceneEditRevision, head.head_revision_id)
        raise RevisionConflictError(head_hash)
    return revision


def append_voice_binding_revision(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio_id: int,
    project_id: int,
    engine_mode: str,
    tts_model: str,
    characters: Sequence[Mapping[str, Any]],
    base_revision_hash: Optional[str],
    operator_user_id: Optional[int] = None,
) -> SceneEditRevision:
    """voice_binding 双写（§2.6/§3.2 R9 并发锁，P1-6）。

    同一事务内按全局锁序：Project 行（FOR UPDATE）→ ChapterAudio 行 →
    voice_binding head（由 append_scene_edit_revision 承接）；写
    ``Project.audio_config.engines.{mode}.tts_models.{model}.characters``
    作为未来批次默认值 + 写 SceneEditRevision（当前章节局部覆盖）+ 更新 head；
    仅当前章节已发布产物置 stale（stale_reason=voice_binding_changed）。
    """
    # ① 锁 Project 行（R9：先锁父项目再进入业务行锁域）
    project_row = db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    ).scalar_one_or_none()
    if project_row is None:
        raise ValueError(f"project not found: {project_id}")

    # 读改写 audio_config（仅作为未来批次默认值）
    config = parse_project_audio_config(project_row.audio_config)
    set_characters_for_model(
        config,
        tts_model,
        [dict(character) for character in characters],
        engine_mode=engine_mode,
    )
    project_row.audio_config = json.dumps(config, ensure_ascii=False)

    character_names = [
        str(character.get("character_name") or character.get("name") or "")
        for character in characters
        if isinstance(character, Mapping)
    ]
    payload = {
        "scope": "chapter",
        "tts_model": tts_model,
        "characters": [dict(character) for character in characters],
    }

    # ② 锁 ChapterAudio → ③ 锁 voice_binding head（锁序与 dialogue 编辑/审批一致）
    revision = append_scene_edit_revision(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
        chapter_audio_id=chapter_audio_id,
        edit_type="voice_binding",
        payload=payload,
        affected_anchors=[name for name in character_names if name],
        base_revision_hash=base_revision_hash,
        operator_user_id=operator_user_id,
    )

    # 仅当前章节已发布产物置 stale（推进 updated_at 触发既有推导 + 记录原因）
    chapter_audio = db.get(ChapterAudio, chapter_audio_id)
    if chapter_audio is not None:
        chapter_audio.updated_at = datetime.now(timezone.utc)
        detail = dict(chapter_audio.render_status_detail or {})
        detail["stale_reason"] = "voice_binding_changed"
        chapter_audio.render_status_detail = detail

    return revision


def get_revision_heads_projection(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> Dict[str, Any]:
    """三条链 head 的完整投影（§2.9/§3.3 last_revisions）。"""
    heads = (
        db.query(SceneEditRevisionHead)
        .filter(
            SceneEditRevisionHead.audiobook_project_id == audiobook_project_id,
            SceneEditRevisionHead.chapter_id == chapter_id,
        )
        .all()
    )
    projection: Dict[str, Any] = {}
    for head in heads:
        revision = db.get(SceneEditRevision, head.head_revision_id)
        if revision is None:
            projection[head.edit_type] = None
            continue
        projection[head.edit_type] = {
            "revision_id": revision.id,
            "revision_hash": revision.revision_hash,
            "created_at": (
                revision.created_at.isoformat() if revision.created_at else None
            ),
        }
    for edit_type in EDIT_TYPES:
        projection.setdefault(edit_type, None)
    return projection


def get_current_voice_binding(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> Optional[Dict[str, Any]]:
    """当前生效的 voice_binding（head revision payload），供编辑表单回显。

    不参与 revision_set_hash（hash 仅取各链 revision_hash），
    与 §2.9 并发协议无耦合。
    """
    head = (
        db.query(SceneEditRevisionHead)
        .filter(
            SceneEditRevisionHead.audiobook_project_id == audiobook_project_id,
            SceneEditRevisionHead.chapter_id == chapter_id,
            SceneEditRevisionHead.edit_type == "voice_binding",
        )
        .one_or_none()
    )
    if head is None:
        return None
    revision = db.get(SceneEditRevision, head.head_revision_id)
    if revision is None:
        return None
    payload = _parse_json(revision.payload, {})
    if not isinstance(payload, Mapping):
        return None
    characters = [
        dict(character)
        for character in (payload.get("characters") or [])
        if isinstance(character, Mapping)
    ]
    return {
        "tts_model": str(payload.get("tts_model") or ""),
        "characters": characters,
    }


def _parse_json(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _source_script_revision(script_segments: Sequence[Mapping[str, Any]]) -> str:
    return _sha256(canonical_json(list(script_segments or [])))


def derive_scene_topology_hash(
    checkpoint: Optional[Mapping[str, Any]],
    script_segments: Sequence[Mapping[str, Any]],
) -> Optional[str]:
    """按 §2.6 canonical 合同从 checkpoint 场景与剧本 segment_key 推导拓扑 hash。

    checkpoint 场景条目优先取 ``source_segment_keys``（R10 分阶段冻结后的
    新格式）；缺失时按 ``source_segment_indices`` 与 script_json 数组顺序
    的 segment_key 映射推导；推导失败返回 None（展示层容错）。
    """
    scenes = (checkpoint or {}).get("scenes") or (checkpoint or {}).get("scene_checkpoints") or {}
    if not isinstance(scenes, (list, Mapping)):
        return None
    segment_keys = [
        str(segment.get("segment_key") or "")
        for segment in (script_segments or [])
        if isinstance(segment, Mapping) and segment.get("segment_key")
    ]
    if isinstance(scenes, Mapping):
        scene_items = [
            {"scene_id": scene_id, **dict(item)}
            for scene_id, item in scenes.items()
            if isinstance(item, Mapping)
        ]
    else:
        scene_items = [dict(item) for item in scenes if isinstance(item, Mapping)]
    topology = []
    for item in scene_items:
        scene_id = str(item.get("scene_id") or "")
        if not scene_id:
            continue
        keys = item.get("source_segment_keys")
        if not isinstance(keys, list):
            indices = item.get("source_segment_indices")
            if isinstance(indices, list):
                keys = [
                    segment_keys[index]
                    for index in indices
                    if isinstance(index, int) and 0 <= index < len(segment_keys)
                ]
            else:
                keys = []
        topology.append(
            {
                "scene_id": scene_id,
                "source_segment_keys": [str(key) for key in keys],
                "segment_count": len(keys),
            }
        )
    if not topology:
        return None
    return _sha256(canonical_json(topology))


def _project_editable_overrides(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> Dict[str, Any]:
    """从 director_override 链尾反向合并计算当前覆盖（§2.6，不修改原文）。"""
    revisions = (
        db.query(SceneEditRevision)
        .filter(
            SceneEditRevision.audiobook_project_id == audiobook_project_id,
            SceneEditRevision.chapter_id == chapter_id,
            SceneEditRevision.edit_type == "director_override",
        )
        .order_by(SceneEditRevision.id.asc())
        .all()
    )
    merged: Dict[str, Any] = {}
    for revision in revisions:
        payload = _parse_json(revision.payload)
        if not isinstance(payload, Mapping):
            continue
        scene_id = str(payload.get("scene_id") or "")
        if not scene_id:
            continue
        overrides = payload.get("overrides")
        if not isinstance(overrides, list):
            overrides = []
        current = merged.get(
            scene_id,
            {
                "scene_id": scene_id,
                "stable_anchors": dict(payload.get("stable_anchors") or {}),
                "overrides": [],
            },
        )
        for item in overrides:
            if not isinstance(item, Mapping):
                continue
            direction_type = str(item.get("direction_type") or "")
            replaced = False
            for index, existing in enumerate(current["overrides"]):
                if (
                    isinstance(existing, Mapping)
                    and existing.get("direction_type") == direction_type
                ):
                    current["overrides"][index] = dict(item)
                    replaced = True
                    break
            if not replaced:
                current["overrides"].append(dict(item))
        merged[scene_id] = current
    return merged


def _aggregate_execution_status(desired_run: Optional[ChapterAudioRun]) -> str:
    """§2.4 维度一：聚合自 ChapterAudioRun.status（desired_run 优先）。"""
    if desired_run is None:
        return "idle"
    return str(desired_run.status or "pending")


@dataclass
class SceneEditorScene:
    """场景编辑器场景条目（SceneEditorDocument.scenes 元素）。"""

    scene_id: str
    status: str
    source_segment_indices: List[int] = field(default_factory=list)
    source_segment_keys: List[str] = field(default_factory=list)
    attempts: int = 0
    reused_checkpoint: bool = False
    fallback_reason: Optional[str] = None
    fallback_artifact: Optional[Dict[str, Any]] = None
    scene_audio_url: Optional[str] = None
    quality_report: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # P1 提示词透明化：渲染时发送的完整提示词与指纹（旧 checkpoint 无 prompt 时为 None）
    prompt: Optional[str] = None
    prompt_hash: Optional[str] = None


@dataclass
class SceneEditorDocument:
    """场景编辑视图的稳定投影（§3.3，多数据源聚合，不是直接编辑 checkpoint）。"""

    chapter_id: int
    audiobook_project_id: int
    engine_mode: str = "seed_scene"
    execution_status: str = "idle"
    published_render_status: Optional[str] = None
    desired_render_status: Optional[str] = None
    published_provenance: Optional[str] = None
    source_script_revision: str = ""
    director_plan_revision: Optional[str] = None
    scene_topology_hash: Optional[str] = None
    scenes: List[SceneEditorScene] = field(default_factory=list)
    editable_overrides: Dict[str, Any] = field(default_factory=dict)
    artifact_references: Dict[str, Any] = field(default_factory=dict)
    last_revisions: Dict[str, Any] = field(default_factory=dict)
    revision_set_hash: Optional[str] = None
    script_status: str = "pending"
    chapter_audio_available: bool = False
    chapter_audio_stale: bool = False
    chapter_audio_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    # 当前生效的音色绑定（voice_binding head payload），供音色编辑表单回显
    voice_binding_current: Optional[Dict[str, Any]] = None


def build_scene_editor_document(
    db: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
    chapter_audio: ChapterAudio,
    scene_audio_url_builder: Any = None,
) -> SceneEditorDocument:
    """聚合 SceneEditorDocument（§3.3）。

    ``scene_audio_url_builder(artifact)`` 可选：返回带 play_token 的试听 URL，
    由路由层注入（服务层不生成 token、不接触本地路径）。
    """
    audiobook_project = db.get(AudiobookProject, audiobook_project_id)
    engine_mode = (
        str(getattr(audiobook_project, "engine_mode", None) or "seed_scene")
        if audiobook_project is not None
        else "seed_scene"
    )

    script_segments = _parse_json(chapter_audio.script_json, [])
    if not isinstance(script_segments, list):
        script_segments = []

    # 三维投影（§2.4/§3.3）
    desired_run = None
    if chapter_audio.desired_run_id:
        desired_run = db.get(ChapterAudioRun, chapter_audio.desired_run_id)
    execution_status = _aggregate_execution_status(desired_run)
    desired_render_status = (
        getattr(desired_run, "result_render_status", None)
        if desired_run is not None
        else None
    )
    published_render_status = chapter_audio.render_status
    published_provenance = chapter_audio.published_provenance

    # checkpoint（desired_run 优先，其次最近 completed run）
    checkpoint: Optional[Mapping[str, Any]] = None
    source_run: Optional[ChapterAudioRun] = desired_run
    if source_run is not None and isinstance(source_run.checkpoint_json, Mapping):
        checkpoint = source_run.checkpoint_json
    if checkpoint is None:
        latest_runs = (
            db.query(ChapterAudioRun)
            .filter(
                ChapterAudioRun.audiobook_project_id == audiobook_project_id,
                ChapterAudioRun.chapter_id == chapter_id,
                ChapterAudioRun.status == "completed",
            )
            .order_by(ChapterAudioRun.id.desc())
            .limit(3)
            .all()
        )
        for run in latest_runs:
            if isinstance(run.checkpoint_json, Mapping):
                checkpoint = run.checkpoint_json
                source_run = run
                break

    # 场景列表（checkpoint 场景结果 + 正式 artifact 登记）
    artifacts = (
        db.query(SceneAudioArtifact)
        .filter(
            SceneAudioArtifact.chapter_audio_id == chapter_audio.id,
            SceneAudioArtifact.status.in_(_ARTIFACT_ACTIVE_STATUSES),
            SceneAudioArtifact.deleted_at.is_(None),
        )
        .all()
    )
    artifact_by_scene: Dict[str, SceneAudioArtifact] = {}
    for artifact in artifacts:
        artifact_by_scene.setdefault(artifact.scene_id, artifact)

    scene_items: List[Mapping[str, Any]] = []
    if checkpoint is not None:
        raw_scenes = checkpoint.get("scenes") or checkpoint.get("scene_checkpoints") or {}
        if isinstance(raw_scenes, Mapping):
            scene_items = [
                {"scene_id": scene_id, **dict(item)}
                for scene_id, item in raw_scenes.items()
                if isinstance(item, Mapping)
            ]
        elif isinstance(raw_scenes, list):
            scene_items = [dict(item) for item in raw_scenes if isinstance(item, Mapping)]

    segment_keys = [
        str(segment.get("segment_key") or "")
        for segment in script_segments
        if isinstance(segment, Mapping) and segment.get("segment_key")
    ]
    scenes: List[SceneEditorScene] = []
    for item in scene_items:
        scene_id = str(item.get("scene_id") or "")
        if not scene_id:
            continue
        indices = [
            int(index)
            for index in (item.get("source_segment_indices") or [])
            if isinstance(index, (int, float, str)) and str(index).lstrip("-").isdigit()
        ]
        keys = item.get("source_segment_keys")
        if not isinstance(keys, list):
            keys = [
                segment_keys[index]
                for index in indices
                if 0 <= index < len(segment_keys)
            ]
        metadata = dict(item.get("metadata") or {})
        quality_report = None
        for report_key in ("quality_report", "l0_report", "omni_report", "semantic_review"):
            if isinstance(metadata.get(report_key), Mapping):
                quality_report = dict(metadata[report_key])
                break
        artifact = artifact_by_scene.get(scene_id)
        fallback_artifact = item.get("fallback_artifact")
        scenes.append(
            SceneEditorScene(
                scene_id=scene_id,
                status=str(item.get("status") or "pending"),
                source_segment_indices=indices,
                source_segment_keys=[str(key) for key in keys],
                attempts=int(item.get("attempts") or 0),
                reused_checkpoint=bool(item.get("reused_checkpoint")),
                fallback_reason=str(item.get("fallback_reason") or "")
                if item.get("fallback_reason")
                else None,
                fallback_artifact=(
                    dict(fallback_artifact)
                    if isinstance(fallback_artifact, Mapping)
                    else None
                ),
                scene_audio_url=(
                    scene_audio_url_builder(artifact)
                    if artifact is not None and scene_audio_url_builder is not None
                    else None
                ),
                quality_report=quality_report,
                metadata=metadata,
                prompt=(
                    str(item["prompt"])
                    if item.get("prompt") is not None
                    else None
                ),
                prompt_hash=(
                    str(item["prompt_hash"])
                    if item.get("prompt_hash") is not None
                    else None
                ),
            )
        )

    last_revisions = get_revision_heads_projection(
        db,
        audiobook_project_id=audiobook_project_id,
        chapter_id=chapter_id,
    )
    revision_set_hash = compute_revision_set_hash(last_revisions)

    document = SceneEditorDocument(
        chapter_id=chapter_id,
        audiobook_project_id=audiobook_project_id,
        engine_mode=engine_mode,
        execution_status=execution_status,
        published_render_status=published_render_status,
        desired_render_status=desired_render_status,
        published_provenance=published_provenance,
        source_script_revision=_source_script_revision(script_segments),
        director_plan_revision=None,
        scene_topology_hash=derive_scene_topology_hash(checkpoint, script_segments),
        scenes=scenes,
        editable_overrides=_project_editable_overrides(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        ),
        artifact_references={},
        last_revisions=last_revisions,
        revision_set_hash=revision_set_hash,
        script_status=str(chapter_audio.script_status or "pending"),
        chapter_audio_available=bool(chapter_audio.audio_path),
        chapter_audio_stale=False,
        chapter_audio_url=None,
        updated_at=chapter_audio.updated_at,
        voice_binding_current=get_current_voice_binding(
            db,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
        ),
    )
    return document


__all__ = [
    "EDIT_TYPES",
    "RevisionConflictError",
    "SceneEditorDocument",
    "SceneEditorScene",
    "append_scene_edit_revision",
    "append_voice_binding_revision",
    "build_scene_editor_document",
    "get_current_voice_binding",
    "canonical_json",
    "compute_input_signature",
    "compute_revision_hash",
    "compute_revision_set_hash",
    "derive_scene_topology_hash",
    "get_revision_heads_projection",
]
