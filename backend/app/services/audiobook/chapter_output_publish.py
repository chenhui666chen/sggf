"""章节输出登记与幂等完整发布协议（GUIDE §2.4 规则 4，§2.5 三维投影）。

- ``upsert_staged_chapter_output``：run 级输出登记（staged），未发布前不可经
  普通端点访问；与整章可导出镜像列解耦（镜像列只由发布事务改写）。
- ``register_scene_audio_artifacts``：§3.4 场景音频 artifact 登记（staged，
  幂等 upsert）——由渲染完成回调在装配段产物就绪后调用。
- ``publish_seed_scene_chapter_output``：seed_scene 引擎的幂等完整发布事务
  ——锁行 → 幂等短路（含 R9 最低一致性检查）→ 发布前置校验（run 归属与
  终态 / seed_scene 发布谓词 / staged 输出恰一条 / R9 场景 artifact 完整性）
  → CAS 镜像列 → 旧输出 supersede（显式排除本 run）→ 本 run staged →
  published → §3.4 artifact 状态机（chapter_audio_id 作用域，staged →
  active，旧 run active → superseded，显式排除本 run）。

  事务所有权归调用方：本模块只做写操作与校验并返回结果，不 commit/rollback，
  由调用方统一提交（章节完成的最终提交点）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app.core.env_loader import get_backend_root
from app.models.audiobook import (
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
    SceneAudioArtifact,
)
from app.services.audiobook.repository import ChapterAudioRunRepository
from app.services.audiobook.scene_edit_revision_service import (
    derive_scene_topology_hash,
)
from sqlalchemy import func

logger = logging.getLogger(__name__)

SEED_PUBLISHABLE_STATUSES = frozenset({"rendered_all_seed", "rendered_with_fallback"})
# legacy 引擎（full/audio_from_scripts/chapter_remix）发布谓词（R9/P0-2）
LEGACY_PUBLISHABLE_STATUSES = frozenset({"completed"})

# §8.3 配额上限：每个项目 scene_audio_artifacts 表记录数上限（不含已清理）
SCENE_ARTIFACT_QUOTA_PER_PROJECT = 10_000

# §3.4：场景音频正式 artifact 存储根目录（与 routes_scene_editor 流式端点一致）
SCENE_ARTIFACT_ROOT = get_backend_root() / "data" / "scene_audio_artifacts"


def _resolve_physical_audio_path(audio_path: Optional[str]) -> Any:
    """将登记路径解析为物理文件路径；无法解析时返回 None。"""
    if not audio_path:
        return None
    try:
        from app.services.audiobook.project_exporter import resolve_existing_audio_path

        return resolve_existing_audio_path(audio_path)
    except Exception:  # pragma: no cover - 解析失败视为文件不可用
        return None


def upsert_staged_chapter_output(
    db,
    *,
    run_id: int,
    chapter_audio_id: int,
    audiobook_project_id: int,
    chapter_id: int,
    audio_path: str,
    duration: Optional[float] = None,
    file_size: Optional[int] = None,
    subtitle_path: Optional[str] = None,
    subtitle_format: Optional[str] = None,
) -> Optional[ChapterAudioOutput]:
    """登记/更新本 run 的整章输出（staged），供发布事务消费。

    每 run 至多一条（``run_id`` 唯一约束）；重复调用为幂等更新。
    """
    if run_id is None:
        return None
    output = (
        db.query(ChapterAudioOutput)
        .filter(ChapterAudioOutput.run_id == run_id)
        .first()
    )
    if output is None:
        output = ChapterAudioOutput(
            run_id=run_id,
            chapter_audio_id=chapter_audio_id,
            audiobook_project_id=audiobook_project_id,
            chapter_id=chapter_id,
            status="staged",
            audio_path=audio_path,
            duration=duration,
            file_size=file_size,
            subtitle_path=subtitle_path,
            subtitle_format=subtitle_format,
        )
        db.add(output)
    else:
        output.audio_path = audio_path
        output.duration = duration
        output.file_size = file_size
        if subtitle_path is not None:
            output.subtitle_path = subtitle_path
            output.subtitle_format = subtitle_format
    db.flush()
    return output


def register_scene_audio_artifacts(
    db,
    *,
    run_id: int,
    chapter_audio_id: int,
    audiobook_project_id: int,
    chapter_id: int,
    scene_artifacts: Optional[List[Mapping[str, Any]]] = None,
) -> int:
    """§3.4：登记本 run 的场景音频 artifact（status='staged'，幂等 upsert）。

    每 (run, scene) 至多一条未删除登记（部分唯一索引兜底）；同一 run 重试
    （幂等键重放/网络重试）时刷新已存在登记的元数据而非新增，避免撞
    ``uq_scene_audio_artifact_run_scene``。返回本次登记/更新的行数。
    仅发布事务内 staged → active（§3.4 状态机）。
    """
    if run_id is None or not scene_artifacts:
        return 0
    # §8.3 配额上限：超出后拒绝新登记（需先完成旧 artifact 物理清理）
    active_artifact_count = (
        db.query(func.count(SceneAudioArtifact.id))
        .filter(
            SceneAudioArtifact.audiobook_project_id == audiobook_project_id,
            SceneAudioArtifact.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )
    if active_artifact_count >= SCENE_ARTIFACT_QUOTA_PER_PROJECT:
        logger.warning(
            "场景 artifact 登记超配额，拒绝新登记: batch=%s active=%s limit=%s",
            audiobook_project_id,
            active_artifact_count,
            SCENE_ARTIFACT_QUOTA_PER_PROJECT,
        )
        return 0
    changed = 0
    for entry in scene_artifacts:
        if not isinstance(entry, Mapping):
            continue
        scene_id = str(entry.get("scene_id") or "").strip()
        if not scene_id:
            continue
        existing = (
            db.query(SceneAudioArtifact)
            .filter(
                SceneAudioArtifact.run_id == run_id,
                SceneAudioArtifact.scene_id == scene_id,
                SceneAudioArtifact.deleted_at.is_(None),
            )
            .first()
        )
        artifact_id = str(entry.get("artifact_id") or "")
        segment_keys = list(entry.get("segment_keys") or [])
        if existing is not None:
            if existing.status != "staged":
                continue
            existing.segment_keys = (
                json.dumps(segment_keys, ensure_ascii=False) if segment_keys else None
            )
            existing.scene_topology_hash = str(entry.get("scene_topology_hash") or "")
            existing.content_digest = str(entry.get("content_digest") or "")
            existing.stored_rel_path = str(entry.get("stored_rel_path") or "")
            existing.source_run_path = str(entry.get("source_run_path") or "") or None
            existing.source_kind = str(entry.get("source_kind") or "seed")
            duration_s = entry.get("duration_s")
            if duration_s is not None:
                try:
                    existing.duration_s = float(duration_s)
                except (TypeError, ValueError):
                    pass
            changed += 1
            continue
        if artifact_id and (
            db.query(SceneAudioArtifact)
            .filter(SceneAudioArtifact.artifact_id == artifact_id)
            .first()
            is not None
        ):
            # artifact_id 冲突（极小概率）：换后缀避免唯一索引冲突
            artifact_id = f"{artifact_id}_r{run_id}"
        db.add(
            SceneAudioArtifact(
                artifact_id=artifact_id or f"art_r{run_id}_{scene_id}",
                audiobook_project_id=audiobook_project_id,
                chapter_id=chapter_id,
                chapter_audio_id=chapter_audio_id,
                run_id=run_id,
                scene_id=scene_id,
                segment_keys=(
                    json.dumps(segment_keys, ensure_ascii=False)
                    if segment_keys
                    else None
                ),
                scene_topology_hash=str(entry.get("scene_topology_hash") or ""),
                content_digest=str(entry.get("content_digest") or ""),
                stored_rel_path=str(entry.get("stored_rel_path") or ""),
                source_run_path=str(entry.get("source_run_path") or "") or None,
                source_kind=str(entry.get("source_kind") or "seed"),
                status="staged",
                duration_s=float(entry.get("duration_s") or 0.0),
            )
        )
        changed += 1
    db.flush()
    return changed


def publish_seed_scene_chapter_output(
    db,
    *,
    run_id: int,
    chapter_audio_id: int,
    render_status: str,
    render_status_detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """seed_scene 引擎幂等完整发布协议（§2.4 规则 4 a-h）。

    任一前置校验不通过时不产生任何写，返回 ``published=False`` 与原因；
    CAS 不命中（desired_run_id 已被新 run 接管）同样不写并返回
    ``reason='desired_run_changed'``——旧任务晚完成不会覆盖新任务，
    新任务不可发布也不会破坏旧已发布产物。
    """
    if render_status not in SEED_PUBLISHABLE_STATUSES:
        # manual_review_required / failed 不进入发布（§2.4 规则 4 c/5）：
        # 首次失败 published 保持 null，已有产物重渲染失败保持旧成功值
        return {
            "published": False,
            "reason": f"not_publishable:{render_status}",
        }

    # a. 锁行：串行化同一章节的发布与并发判定
    chapter_audio = (
        db.query(ChapterAudio)
        .filter(ChapterAudio.id == chapter_audio_id)
        .with_for_update()
        .first()
    )
    if chapter_audio is None:
        return {"published": False, "reason": "chapter_audio_missing"}

    run = ChapterAudioRunRepository.get_run_by_id(db, run_id=run_id)
    if run is None or run.chapter_audio_id != chapter_audio_id:
        return {"published": False, "reason": "run_scope_mismatch"}
    if str(run.status or "").strip().lower() != "completed":
        return {"published": False, "reason": f"run_not_completed:{run.status}"}
    signature = run.input_signature

    # b. 幂等短路：同 run 已发布且签名一致 → R9 最低一致性检查通过才直接返回
    if (
        chapter_audio.published_run_id == run_id
        and chapter_audio.published_input_signature == signature
    ):
        published_output = (
            db.query(ChapterAudioOutput)
            .filter(
                ChapterAudioOutput.run_id == run_id,
                ChapterAudioOutput.status == "published",
            )
            .first()
        )
        mirror_ok = (
            published_output is not None
            and bool(published_output.audio_path)
            and published_output.duration is not None
            and published_output.file_size is not None
        )
        physical_ok = bool(_resolve_physical_audio_path(published_output.audio_path))
        if mirror_ok and physical_ok:
            return {"published": True, "reason": "idempotent"}
        logger.error(
            "章节产物损坏，不短路发布: run_id=%s chapter_audio_id=%s "
            "mirror_ok=%s physical_ok=%s",
            run_id,
            chapter_audio_id,
            mirror_ok,
            physical_ok,
        )
        return {"published": False, "reason": "published_output_corrupted"}

    # c. 发布前置校验：staged 输出恰一条
    staged_count = (
        db.query(ChapterAudioOutput)
        .filter(
            ChapterAudioOutput.run_id == run_id,
            ChapterAudioOutput.status == "staged",
        )
        .count()
    )
    if staged_count != 1:
        return {"published": False, "reason": f"staged_output_count:{staged_count}"}
    staged_output = (
        db.query(ChapterAudioOutput)
        .filter(
            ChapterAudioOutput.run_id == run_id,
            ChapterAudioOutput.status == "staged",
        )
        .first()
    )

    # c'. §3.4/R9：场景 artifact 完整性校验（场景键集合全等 + 每场景恰一条
    # staged + 拓扑 hash/segment_keys/digest/物理文件/fallback 合同逐条校验）
    artifact_error = _scene_artifacts_completeness_error(
        db,
        run=run,
        chapter_audio_id=chapter_audio_id,
        run_id=run_id,
    )
    if artifact_error is not None:
        return {"published": False, "reason": f"scene_artifacts_incomplete:{artifact_error}"}


    # d. CAS 更新镜像列（下载链仍读 ChapterAudio.audio_path）
    updated = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.id == chapter_audio_id,
            ChapterAudio.desired_run_id == run_id,
        )
        .update(
            {
                ChapterAudio.published_run_id: run_id,
                ChapterAudio.published_input_signature: signature,
                ChapterAudio.render_status: render_status,
                ChapterAudio.render_status_detail: render_status_detail,
                ChapterAudio.audio_path: staged_output.audio_path,
                ChapterAudio.duration: staged_output.duration,
                ChapterAudio.file_size: staged_output.file_size,
                ChapterAudio.subtitle_path: staged_output.subtitle_path,
                ChapterAudio.subtitle_format: staged_output.subtitle_format,
                ChapterAudio.published_provenance: "published",
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        # rowcount == 0：desired_run_id 已被更新 run 接管，后续 SQL 一律不执行。
        # 不做 rollback——调用方事务中的剧本/片段写回仍应保留（与旧逻辑一致）
        return {"published": False, "reason": "desired_run_changed"}

    # e. 旧输出 supersede（显式排除本 run——重试场景本 run 已发布的登记不被误置）
    db.query(ChapterAudioOutput).filter(
        ChapterAudioOutput.chapter_audio_id == chapter_audio_id,
        ChapterAudioOutput.status == "published",
        ChapterAudioOutput.run_id != run_id,
    ).update({"status": "superseded"}, synchronize_session=False)

    # f. 本 run 输出发布
    db.query(ChapterAudioOutput).filter(
        ChapterAudioOutput.run_id == run_id,
        ChapterAudioOutput.status == "staged",
    ).update(
        {"status": "published", "published_at": func.now()},
        synchronize_session=False,
    )
    # g. §3.4 artifact 状态机：chapter_audio_id 作用域，旧 run 的 active
    # artifact 同步 superseded（置 deleted_at），显式排除本 run（R7/R8）
    db.query(SceneAudioArtifact).filter(
        SceneAudioArtifact.chapter_audio_id == chapter_audio_id,
        SceneAudioArtifact.status == "active",
        SceneAudioArtifact.run_id != run_id,
    ).update(
        {"status": "superseded", "deleted_at": func.now()},
        synchronize_session=False,
    )
    # 本 run staged → active（失败/未发布 run 的 artifact 保持 staged，不激活）
    db.query(SceneAudioArtifact).filter(
        SceneAudioArtifact.run_id == run_id,
        SceneAudioArtifact.status == "staged",
        SceneAudioArtifact.deleted_at.is_(None),
    ).update({"status": "active"}, synchronize_session=False)

    logger.info(
        "✅ seed_scene 章节输出发布成功: chapter_audio_id=%s run_id=%s render_status=%s",
        chapter_audio_id,
        run_id,
        render_status,
    )
    return {"published": True, "reason": "published"}


def publish_legacy_chapter_output(
    db,
    *,
    run_id: int,
    chapter_audio_id: int,
    render_status: str = "completed",
    render_status_detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """legacy 引擎（full/audio_from_scripts/chapter_remix）幂等发布协议（R9/P0-2）。

    与 seed_scene 发布共用 a（锁行）/b（幂等短路含 R9 最低一致性检查）/c（staged
    恰一条）/d（CAS 镜像列）/e（旧输出 supersede）/f（本 run staged → published）
    各步，跳过场景 artifact 完整性校验（c'，legacy 无场景 artifact）。

    发布谓词：``result_render_status='completed'`` 且整章输出齐全。
    """
    if render_status not in LEGACY_PUBLISHABLE_STATUSES:
        return {
            "published": False,
            "reason": f"not_publishable:{render_status}",
        }

    # a. 锁行：串行化同一章节的发布与并发判定
    chapter_audio = (
        db.query(ChapterAudio)
        .filter(ChapterAudio.id == chapter_audio_id)
        .with_for_update()
        .first()
    )
    if chapter_audio is None:
        return {"published": False, "reason": "chapter_audio_missing"}

    run = ChapterAudioRunRepository.get_run_by_id(db, run_id=run_id)
    if run is None or run.chapter_audio_id != chapter_audio_id:
        return {"published": False, "reason": "run_scope_mismatch"}
    if str(run.status or "").strip().lower() != "completed":
        return {"published": False, "reason": f"run_not_completed:{run.status}"}
    signature = run.input_signature

    # b. 幂等短路：同 run 已发布且签名一致 → R9 最低一致性检查通过才直接返回
    if (
        chapter_audio.published_run_id == run_id
        and chapter_audio.published_input_signature == signature
    ):
        published_output = (
            db.query(ChapterAudioOutput)
            .filter(
                ChapterAudioOutput.run_id == run_id,
                ChapterAudioOutput.status == "published",
            )
            .first()
        )
        mirror_ok = (
            published_output is not None
            and bool(published_output.audio_path)
            and published_output.duration is not None
            and published_output.file_size is not None
        )
        physical_ok = bool(_resolve_physical_audio_path(published_output.audio_path))
        if mirror_ok and physical_ok:
            return {"published": True, "reason": "idempotent"}
        logger.error(
            "legacy 章节产物损坏，不短路发布: run_id=%s chapter_audio_id=%s "
            "mirror_ok=%s physical_ok=%s",
            run_id,
            chapter_audio_id,
            mirror_ok,
            physical_ok,
        )
        return {"published": False, "reason": "published_output_corrupted"}

    # c. 发布前置校验：staged 输出恰一条（legacy 无场景 artifact 完整性步骤）
    staged_count = (
        db.query(ChapterAudioOutput)
        .filter(
            ChapterAudioOutput.run_id == run_id,
            ChapterAudioOutput.status == "staged",
        )
        .count()
    )
    if staged_count != 1:
        return {"published": False, "reason": f"staged_output_count:{staged_count}"}
    staged_output = (
        db.query(ChapterAudioOutput)
        .filter(
            ChapterAudioOutput.run_id == run_id,
            ChapterAudioOutput.status == "staged",
        )
        .first()
    )

    # d. CAS 更新镜像列（下载链仍读 ChapterAudio.audio_path）
    updated = (
        db.query(ChapterAudio)
        .filter(
            ChapterAudio.id == chapter_audio_id,
            ChapterAudio.desired_run_id == run_id,
        )
        .update(
            {
                ChapterAudio.published_run_id: run_id,
                ChapterAudio.published_input_signature: signature,
                ChapterAudio.render_status: render_status,
                ChapterAudio.render_status_detail: render_status_detail,
                ChapterAudio.audio_path: staged_output.audio_path,
                ChapterAudio.duration: staged_output.duration,
                ChapterAudio.file_size: staged_output.file_size,
                ChapterAudio.subtitle_path: staged_output.subtitle_path,
                ChapterAudio.subtitle_format: staged_output.subtitle_format,
                ChapterAudio.published_provenance: "published",
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        # rowcount == 0：desired_run_id 已被更新 run 接管，后续 SQL 一律不执行
        return {"published": False, "reason": "desired_run_changed"}

    # e. 旧输出 supersede（显式排除本 run）
    db.query(ChapterAudioOutput).filter(
        ChapterAudioOutput.chapter_audio_id == chapter_audio_id,
        ChapterAudioOutput.status == "published",
        ChapterAudioOutput.run_id != run_id,
    ).update({"status": "superseded"}, synchronize_session=False)

    # f. 本 run 输出发布
    db.query(ChapterAudioOutput).filter(
        ChapterAudioOutput.run_id == run_id,
        ChapterAudioOutput.status == "staged",
    ).update(
        {"status": "published", "published_at": func.now()},
        synchronize_session=False,
    )

    logger.info(
        "✅ legacy 章节输出发布成功: chapter_audio_id=%s run_id=%s render_status=%s",
        chapter_audio_id,
        run_id,
        render_status,
    )
    return {"published": True, "reason": "published"}


def _parse_segment_keys_json(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as audio_file:
        for chunk in iter(lambda: audio_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_artifacts_completeness_error(
    db,
    *,
    run: ChapterAudioRun,
    chapter_audio_id: int,
    run_id: int,
) -> Optional[str]:
    """§3.4/R9：场景 artifact 完整性校验，通过返回 None。

    - checkpoint 场景键集合与 staged artifact 键集合全等（SET 相等）；
    - 每场景恰一条 staged（部分唯一索引兜底，这里显式 count 校验）；
    - 逐条：scene_topology_hash 与 checkpoint 推导一致、segment_keys
      与场景归属一致、content_digest 与物理文件实际 sha256 一致（存在性）；
    - ``source_kind='legacy_fallback'`` 的场景必须对应 checkpoint 回退记录。

    无场景 checkpoint 且无 staged artifact（legacy 路径/测试场景）时跳过。
    """
    checkpoint = run.checkpoint_json if isinstance(run.checkpoint_json, Mapping) else {}
    raw_scenes = (
        checkpoint.get("scenes") or checkpoint.get("scene_checkpoints") or {}
    )
    staged = (
        db.query(SceneAudioArtifact)
        .filter(
            SceneAudioArtifact.run_id == run_id,
            SceneAudioArtifact.status == "staged",
            SceneAudioArtifact.deleted_at.is_(None),
        )
        .all()
    )
    checkpoint_scene_ids = (
        {str(scene_id) for scene_id in raw_scenes}
        if isinstance(raw_scenes, Mapping)
        else set()
    )
    if not checkpoint_scene_ids and not staged:
        return None
    if not isinstance(raw_scenes, Mapping):
        return "checkpoint_scenes_not_mapping"
    if checkpoint_scene_ids != {artifact.scene_id for artifact in staged}:
        return (
            "scene_key_set_mismatch:checkpoint="
            f"{sorted(checkpoint_scene_ids)} staged="
            f"{sorted(artifact.scene_id for artifact in staged)}"
        )

    chapter_audio = db.query(ChapterAudio).filter(ChapterAudio.id == chapter_audio_id).first()
    script_segments = []
    if chapter_audio is not None and chapter_audio.script_json:
        try:
            parsed = json.loads(chapter_audio.script_json)
        except (TypeError, ValueError):
            parsed = None
        script_segments = parsed if isinstance(parsed, list) else []
    expected_topology_hash = derive_scene_topology_hash(checkpoint, script_segments)

    for artifact in staged:
        checkpoint_entry = raw_scenes.get(artifact.scene_id)
        if not isinstance(checkpoint_entry, Mapping):
            return f"scene_checkpoint_missing:{artifact.scene_id}"
        if artifact.scene_topology_hash != (expected_topology_hash or ""):
            return (
                f"topology_hash_mismatch:{artifact.scene_id}:"
                f"{artifact.scene_topology_hash}!={expected_topology_hash or ''}"
            )
        # segment_keys 与场景归属一致（与 derive 同规则映射）
        keys = checkpoint_entry.get("source_segment_keys")
        if not isinstance(keys, list):
            indices = checkpoint_entry.get("source_segment_indices")
            script_keys = [
                str(segment.get("segment_key") or "")
                for segment in script_segments
                if isinstance(segment, Mapping) and segment.get("segment_key")
            ]
            keys = [
                script_keys[index]
                for index in (indices or [])
                if isinstance(index, int) and 0 <= index < len(script_keys)
            ]
        if _parse_segment_keys_json(artifact.segment_keys) != [str(key) for key in keys]:
            return f"segment_keys_mismatch:{artifact.scene_id}"
        # content_digest 与物理文件实际 sha256 一致（存在性检查）
        file_path = SCENE_ARTIFACT_ROOT / str(artifact.stored_rel_path or "")
        if not file_path.is_file():
            return f"artifact_file_missing:{artifact.scene_id}"
        try:
            actual_digest = _file_sha256(file_path)
        except OSError:
            return f"artifact_file_unreadable:{artifact.scene_id}"
        if actual_digest != artifact.content_digest:
            return f"content_digest_mismatch:{artifact.scene_id}"
        # fallback 合同：legacy_fallback 场景必须对应 checkpoint 回退记录
        if artifact.source_kind == "legacy_fallback":
            if str(checkpoint_entry.get("status") or "") != "legacy_stems":
                return f"fallback_contract_mismatch:{artifact.scene_id}"
    return None


__all__ = [
    "SCENE_ARTIFACT_ROOT",
    "SEED_PUBLISHABLE_STATUSES",
    "publish_seed_scene_chapter_output",
    "register_scene_audio_artifacts",
    "upsert_staged_chapter_output",
]
