from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.models.dreamweaver import (
    DreamweaverAsset,
    DreamweaverEpisode,
    DreamweaverProject,
    DreamweaverShot,
)
from app.utils.datetime_utils import ensure_utc_datetime, utc_now


LIB_ROLE_PREFIX = "lib_"
LIBRARY_ANCHOR_STATUS = "library"


@dataclass(frozen=True)
class DreamweaverRunSummary:
    run_id: str
    status: str
    state: str | None
    stage: str | None
    progress: int
    schema_version: str
    error_type: str | None
    error_message: str | None
    created_at: str | None
    updated_at: str | None
    camera_tree_mode: str | None
    camera_count: int | None
    camera_states_count: int | None
    camera_scenes_count: int | None


@dataclass(frozen=True)
class DreamweaverRunDeleteResult:
    run_id: str
    deleted_generation_history: int
    deleted_assets: int
    deleted_shots: int
    deleted_episodes: int
    deleted_project: bool
    deleted_run_dir: bool
    failed_paths: List[str]


class DreamweaverRunNotFoundError(RuntimeError):
    pass


class DreamweaverRunRunningError(RuntimeError):
    pass


def default_runs_root() -> Path:
    return Path(__file__).resolve().parents[4] / "runs"


def mark_stale_dreamweaver_runs_timeout(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    timeout_minutes: int = 30,
) -> int:
    if timeout_minutes <= 0:
        return 0

    cutoff = utc_now() - timedelta(minutes=int(timeout_minutes))
    rows = (
        db.query(DreamweaverProject)
        .filter(
            DreamweaverProject.source_project_id == project_id,
            DreamweaverProject.user_id == user_id,
            DreamweaverProject.status == "running",
        )
        .all()
    )
    rows = [
        row
        for row in rows
        if (updated_at := ensure_utc_datetime(getattr(row, "updated_at", None))) and updated_at < cutoff
    ]

    if not rows:
        return 0

    for row in rows:
        row.status = "timeout"
        if not str(getattr(row, "error_type", "") or "").strip():
            row.error_type = "timeout"
        if not str(getattr(row, "error_message", "") or "").strip():
            row.error_message = f"run 超时：{timeout_minutes} 分钟未更新"

    db.commit()
    return len(rows)


def list_dreamweaver_runs(db: Session, *, project_id: int, user_id: int, limit: int = 50) -> List[DreamweaverRunSummary]:
    rows = (
        db.query(DreamweaverProject)
        .filter(DreamweaverProject.source_project_id == project_id, DreamweaverProject.user_id == user_id)
        .filter(DreamweaverProject.status != LIBRARY_ANCHOR_STATUS)
        .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
        .limit(limit)
        .all()
    )

    result: List[DreamweaverRunSummary] = []
    for row in rows:
        contract = row.contract_json if isinstance(getattr(row, "contract_json", None), dict) else {}
        runtime_cfg = contract.get("runtime_config") if isinstance(contract.get("runtime_config"), dict) else {}
        camera_tree_generation = (
            runtime_cfg.get("camera_tree_generation")
            if isinstance(runtime_cfg.get("camera_tree_generation"), dict)
            else {}
        )
        camera_tree_mode = None
        mode = camera_tree_generation.get("mode")
        if isinstance(mode, str) and mode.strip():
            camera_tree_mode = mode.strip()

        camera_count = len(runtime_cfg["camera_tree"]) if isinstance(runtime_cfg.get("camera_tree"), list) else None
        camera_states_count = len(runtime_cfg["camera_states"]) if isinstance(runtime_cfg.get("camera_states"), list) else None
        camera_scenes_count = len(runtime_cfg["camera_scenes"]) if isinstance(runtime_cfg.get("camera_scenes"), list) else None

        result.append(
            DreamweaverRunSummary(
                run_id=str(row.run_id),
                status=str(row.status or ""),
                state=str(row.state) if row.state is not None else None,
                stage=str(row.stage) if row.stage is not None else None,
                progress=int(row.progress or 0),
                schema_version=str(row.schema_version or ""),
                error_type=str(row.error_type) if row.error_type is not None else None,
                error_message=str(row.error_message) if row.error_message is not None else None,
                created_at=row.created_at.isoformat() if row.created_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
                camera_tree_mode=camera_tree_mode,
                camera_count=camera_count,
                camera_states_count=camera_states_count,
                camera_scenes_count=camera_scenes_count,
            )
        )
    return result


def delete_dreamweaver_run(
    db: Session,
    *,
    run_id: str,
    user_id: int,
    delete_files: bool = True,
    runs_root: Optional[Path] = None,
) -> DreamweaverRunDeleteResult:
    row = (
        db.query(DreamweaverProject)
        .filter(DreamweaverProject.run_id == run_id, DreamweaverProject.user_id == user_id)
        .first()
    )
    if not row:
        raise DreamweaverRunNotFoundError(run_id)

    status_lower = str(getattr(row, "status", "") or "").strip().lower()
    if status_lower == "running":
        raise DreamweaverRunRunningError(run_id)

    project_id = int(getattr(row, "source_project_id"))
    dreamweaver_project_id = int(getattr(row, "id"))

    # 0) Preserve project-level "library" assets across run deletion.
    # Library assets are modeled as DreamweaverAsset with role prefix "lib_" but are intended to be reused at
    # the source-project scope (across runs). Historically they were attached to the "latest" run row; when that
    # run is deleted we must migrate these assets to another run (or a hidden library anchor row) to avoid losing them.
    lib_asset_rows = (
        db.query(DreamweaverAsset.id)
        .filter(
            DreamweaverAsset.dreamweaver_project_id == dreamweaver_project_id,
            DreamweaverAsset.role.like(f"{LIB_ROLE_PREFIX}%"),
        )
        .all()
    )
    lib_asset_ids = [int(r[0]) for r in lib_asset_rows if r and r[0] is not None]
    if lib_asset_ids:
        # Prefer migrating to another real run if it exists.
        recipient = (
            db.query(DreamweaverProject)
            .filter(
                DreamweaverProject.source_project_id == project_id,
                DreamweaverProject.user_id == user_id,
                DreamweaverProject.id != dreamweaver_project_id,
                DreamweaverProject.status != LIBRARY_ANCHOR_STATUS,
            )
            .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
            .first()
        )
        if recipient is None:
            # Reuse an existing hidden anchor row if present.
            recipient = (
                db.query(DreamweaverProject)
                .filter(
                    DreamweaverProject.source_project_id == project_id,
                    DreamweaverProject.user_id == user_id,
                    DreamweaverProject.status == LIBRARY_ANCHOR_STATUS,
                )
                .order_by(DreamweaverProject.updated_at.desc(), DreamweaverProject.created_at.desc())
                .first()
            )
        if recipient is None:
            # Create a hidden anchor row to host library assets when no runs remain.
            anchor_run_id = f"library_anchor:project:{project_id}:user:{user_id}"
            recipient = DreamweaverProject(
                run_id=anchor_run_id,
                source_project_id=project_id,
                user_id=user_id,
                schema_version=str(getattr(row, "schema_version", "") or "0.1.0"),
                status=LIBRARY_ANCHOR_STATUS,
                state=None,
                stage=None,
                progress=0,
                error_type=None,
                error_message=None,
                contract_json=None,
            )
            db.add(recipient)
            db.flush()

        db.query(DreamweaverAsset).filter(DreamweaverAsset.id.in_(lib_asset_ids)).update(
            {DreamweaverAsset.dreamweaver_project_id: int(recipient.id)},
            synchronize_session=False,
        )
        db.flush()

    deleted_generation_history = 0
    gh_ids: List[int] = []
    try:
        gh_rows = db.execute(
            text(
                """
                SELECT id, result
                FROM generation_history
                WHERE project_id = :project_id
                  AND task_type = 'dreamweaver'
                  AND result LIKE :pattern
                """
            ),
            {"project_id": project_id, "pattern": f"%{run_id}%"},
        ).fetchall()
    except Exception as e:
        logger.debug("Failed to query generation_history for run_id=%s: %s", run_id, e)
        gh_rows = []

    for gh_id, gh_result in gh_rows:
        if not isinstance(gh_result, str) or not gh_result.strip():
            continue
        try:
            payload = json.loads(gh_result)
        except Exception as e:
            logger.debug("Failed to parse generation_history JSON for id=%s: %s", gh_id, e)
            continue
        if isinstance(payload, dict) and str(payload.get("run_id") or "").strip() == run_id:
            try:
                gh_ids.append(int(gh_id))
            except Exception as e:
                logger.debug("Failed to convert gh_id to int: %s", e)
                continue

    if gh_ids:
        delete_query = text("DELETE FROM generation_history WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
        res = db.execute(delete_query, {"ids": gh_ids})
        deleted_generation_history = int(getattr(res, "rowcount", 0) or 0)

    deleted_assets = int(
        db.query(DreamweaverAsset)
        .filter(
            DreamweaverAsset.dreamweaver_project_id == dreamweaver_project_id,
            ~DreamweaverAsset.role.like(f"{LIB_ROLE_PREFIX}%"),
        )
        .delete(synchronize_session=False)
        or 0
    )

    episode_ids = [
        int(e.id)
        for e in db.query(DreamweaverEpisode)
        .filter(DreamweaverEpisode.dreamweaver_project_id == dreamweaver_project_id)
        .all()
    ]

    deleted_shots = 0
    if episode_ids:
        deleted_shots = int(
            db.query(DreamweaverShot)
            .filter(DreamweaverShot.episode_id.in_(episode_ids))
            .delete(synchronize_session=False)
            or 0
        )

    deleted_episodes = int(
        db.query(DreamweaverEpisode)
        .filter(DreamweaverEpisode.dreamweaver_project_id == dreamweaver_project_id)
        .delete(synchronize_session=False)
        or 0
    )

    db.delete(row)
    db.commit()

    failed_paths: List[str] = []
    deleted_run_dir = False
    if delete_files:
        root = (runs_root or default_runs_root()).resolve()
        target = (root / run_id).resolve()
        if root == target or root not in target.parents:
            failed_paths.append(str(target))
        elif target.exists():
            try:
                shutil.rmtree(target)
                deleted_run_dir = True
            except Exception as e:
                logger.debug("Failed to delete run directory %s: %s", target, e)
                failed_paths.append(str(target))

    return DreamweaverRunDeleteResult(
        run_id=run_id,
        deleted_generation_history=deleted_generation_history,
        deleted_assets=deleted_assets,
        deleted_shots=deleted_shots,
        deleted_episodes=deleted_episodes,
        deleted_project=True,
        deleted_run_dir=deleted_run_dir,
        failed_paths=failed_paths,
    )
