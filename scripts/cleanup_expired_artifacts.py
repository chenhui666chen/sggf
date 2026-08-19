"""
场景音频 artifact 与 run 级输出保留期清理（GUIDE §8.3）。

清理范围（默认 dry-run，显式 --apply 才写入）：
- SceneAudioArtifact：superseded（deleted_at 置位）超 30 天 → 删物理文件；
  staged 且所属 run 已终态超 30 天 → 置 superseded + deleted_at 并删物理文件；
  run 未终态的 staged 不清理；active 不清理。
- ChapterAudioOutput：superseded 超 30 天 → 删整章/字幕物理文件并置墓碑
  （file_status='purged' + purged_at）；staged 且所属 run 已终态超 30 天 → 同上；
  published 不清理；被 ChapterAudio.published_run_id 镜像列引用的输出禁止清理。

安全约束：物理文件删除前校验无其他未清理登记引用同一路径（同一文件不得
因多个登记而误删）。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, or_

from app.core.env_loader import get_backend_root
from app.db.base import SessionLocal
from app.models.audiobook import (
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
    SceneAudioArtifact,
)

RETENTION_DAYS = 30
TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled", "canceled")

logger = logging.getLogger(__name__)

SCENE_ARTIFACT_ROOT = get_backend_root() / "data" / "scene_audio_artifacts"


def _expired(cutoff: datetime, timestamp) -> bool:
    """naive 时间戳（sqlite 等存储场景）按 UTC 补齐后比较。"""
    if timestamp is None:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp < cutoff


def _candidate_artifact_paths(rows) -> list[str]:
    return [
        str(SCENE_ARTIFACT_ROOT / str(row.stored_rel_path or ""))
        for row in rows
        if row.stored_rel_path
    ]


def _collect_registered_paths(db, *, exclude_artifact_ids, exclude_output_ids) -> set[str]:
    """收集所有未清理登记的物理路径（artifact + output + 镜像列），防误删共享文件。

    候选行自身已列入待删，从引用集合中排除。
    """
    paths: set[str] = set()
    artifact_rows = (
        db.query(SceneAudioArtifact)
        .filter(SceneAudioArtifact.stored_rel_path.isnot(None))
        .filter(~SceneAudioArtifact.id.in_(exclude_artifact_ids))
        .all()
        if exclude_artifact_ids
        else db.query(SceneAudioArtifact)
        .filter(SceneAudioArtifact.stored_rel_path.isnot(None))
        .all()
    )
    for row in artifact_rows:
        if row.stored_rel_path:
            paths.add(str(SCENE_ARTIFACT_ROOT / str(row.stored_rel_path)))
    output_query = db.query(ChapterAudioOutput).filter(ChapterAudioOutput.file_status != "purged")
    if exclude_output_ids:
        output_query = output_query.filter(~ChapterAudioOutput.id.in_(exclude_output_ids))
    for row in output_query.all():
        if row.audio_path:
            paths.add(str(row.audio_path))
        if row.subtitle_path:
            paths.add(str(row.subtitle_path))
    for row in db.query(ChapterAudio.audio_path).filter(ChapterAudio.audio_path.isnot(None)).all():
        if row.audio_path:
            paths.add(str(row.audio_path))
    for row in db.query(ChapterAudio.subtitle_path).filter(ChapterAudio.subtitle_path.isnot(None)).all():
        if row.subtitle_path:
            paths.add(str(row.subtitle_path))
    return paths


def cleanup_expired_artifacts(*, apply: bool) -> dict:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        terminal_run_ids = {
            run_id
            for (run_id,) in db.query(ChapterAudioRun.id)
            .filter(ChapterAudioRun.status.in_(TERMINAL_RUN_STATUSES))
            .all()
        }
        # 被 published_run_id 镜像列引用的 run 输出禁止清理
        protected_run_ids = {
            run_id
            for (run_id,) in db.query(ChapterAudio.published_run_id)
            .filter(ChapterAudio.published_run_id.isnot(None))
            .all()
        }

        # ——— SceneAudioArtifact ———
        artifact_candidates = []
        for row in db.query(SceneAudioArtifact).filter(
            or_(
                SceneAudioArtifact.deleted_at.isnot(None),
                SceneAudioArtifact.status == "staged",
            )
        ).all():
            if row.deleted_at is not None:
                if _expired(cutoff, row.deleted_at) and row.status == "superseded":
                    artifact_candidates.append(row)
                continue
            if (
                row.status == "staged"
                and row.run_id in terminal_run_ids
                and _expired(cutoff, row.created_at)
            ):
                artifact_candidates.append(row)

        artifact_paths = _candidate_artifact_paths(artifact_candidates)

        # ——— ChapterAudioOutput ———
        output_candidates = []
        for row in db.query(ChapterAudioOutput).filter(
            ChapterAudioOutput.status != "published"
        ).all():
            if row.status == "superseded":
                if _expired(cutoff, row.purged_at or row.created_at):
                    output_candidates.append(row)
                continue
            if (
                row.status == "staged"
                and row.run_id in terminal_run_ids
                and row.run_id not in protected_run_ids
                and _expired(cutoff, row.created_at)
            ):
                output_candidates.append(row)

        output_paths: list[str] = []
        for row in output_candidates:
            if row.audio_path:
                output_paths.append(str(row.audio_path))
            if row.subtitle_path:
                output_paths.append(str(row.subtitle_path))

        registered = _collect_registered_paths(
            db,
            exclude_artifact_ids={row.id for row in artifact_candidates},
            exclude_output_ids={row.id for row in output_candidates},
        )
        # 候选行自身仍在登记表中：删除前剔除仍被其他登记引用的路径
        artifact_delete_paths = [
            path for path in artifact_paths if path and path not in registered
        ]
        output_delete_paths = [
            path for path in output_paths if path and path not in registered
        ]

        if not apply:
            print(
                f"[dry-run] 超期清理: artifact 文件 {len(artifact_delete_paths)} 个 "
                f"({len(artifact_candidates)} 行)、output 文件 {len(output_delete_paths)} 个 "
                f"({len(output_candidates)} 行)"
            )
            for path in artifact_delete_paths + output_delete_paths:
                print(f"  - {path}")
            return {"artifact_rows": len(artifact_candidates), "output_rows": len(output_candidates)}

        deleted_files = 0
        for path in artifact_delete_paths:
            try:
                Path(path).unlink(missing_ok=True)
                deleted_files += 1
            except OSError as exc:
                logger.warning("删除 artifact 文件失败: %s (%s)", path, exc)
        for path in output_delete_paths:
            try:
                Path(path).unlink(missing_ok=True)
                deleted_files += 1
            except OSError as exc:
                logger.warning("删除 output 文件失败: %s (%s)", path, exc)

        # 置墓碑：artifact 置 superseded + deleted_at；output 置 file_status='purged'
        now = datetime.now(timezone.utc)
        for row in artifact_candidates:
            if row.status == "staged":
                row.status = "superseded"
                row.deleted_at = now
        for row in output_candidates:
            row.file_status = "purged"
            row.purged_at = row.purged_at or now
        db.commit()

        print(
            f"[apply] 已清理 {deleted_files} 个物理文件；"
            f"artifact 墓碑 {len(artifact_candidates)} 行、output 墓碑 {len(output_candidates)} 行"
        )
        return {
            "artifact_rows": len(artifact_candidates),
            "output_rows": len(output_candidates),
            "deleted_files": deleted_files,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="超期 artifact/output 物理文件清理（§8.3）")
    parser.add_argument("--apply", action="store_true", help="执行删除与墓碑写入；缺省为 dry-run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    cleanup_expired_artifacts(apply=args.apply)


if __name__ == "__main__":
    main()
