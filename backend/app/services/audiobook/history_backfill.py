"""Phase 1.1 Migrate 余项：历史数据确定性回填（GUIDE §1.1，Contract 前置）。

回填项（全部幂等、确定性，重复执行结果不变）：
- ``audiobook_projects.engine_mode``：无 seed_scene 证据的历史批次 → ``legacy_stems``
- ``audiobook_projects.snapshot_status``：证据不足 → ``legacy_unverified``（禁止恢复，R19/P2-1）
- ``chapter_audio_runs.engine_mode_snapshot``：自批次 engine_mode 回填
- ``chapter_audio_runs.chapter_audio_id``：按 ``(audiobook_project_id, chapter_id)`` 匹配，
  组内无 active ``ChapterAudio`` 时创建一行，再将该组全部历史 run 改指该行（R10/P1-1，不留空）
- ``chapter_audio_runs.celery_task_id``：NULL 回填仅审计用唯一 id ``legacy-run-{id}``
  （不做 broker 关联，R12/P0-2 ③）
- ``chapter_audio_runs.dispatch_status``：历史 NULL → ``unknown``（派发事实不可考，人工对账入口）

本模块只做数据回填，不收窄任何约束——约束收窄属 Contract 单元（独立迁移，门禁后才执行）。
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun

logger = logging.getLogger(__name__)


def _backfill_project_columns(session: Session) -> dict[str, int]:
    engine_mode_rows = session.execute(
        update(AudiobookProject)
        .where(AudiobookProject.engine_mode.is_(None))
        .values(engine_mode="legacy_stems")
    ).rowcount
    snapshot_rows = session.execute(
        update(AudiobookProject)
        .where(AudiobookProject.snapshot_status.is_(None))
        .values(snapshot_status="legacy_unverified")
    ).rowcount
    return {"engine_mode": engine_mode_rows, "snapshot_status": snapshot_rows}


def _backfill_run_engine_snapshot(session: Session) -> int:
    project_mode = (
        select(AudiobookProject.engine_mode)
        .where(AudiobookProject.id == ChapterAudioRun.audiobook_project_id)
        .scalar_subquery()
    )
    return session.execute(
        update(ChapterAudioRun)
        .where(ChapterAudioRun.engine_mode_snapshot.is_(None))
        .values(engine_mode_snapshot=project_mode)
    ).rowcount


def _backfill_run_chapter_audio_id(session: Session) -> dict[str, int]:
    groups = session.execute(
        select(ChapterAudioRun.audiobook_project_id, ChapterAudioRun.chapter_id)
        .where(ChapterAudioRun.chapter_audio_id.is_(None))
        .group_by(ChapterAudioRun.audiobook_project_id, ChapterAudioRun.chapter_id)
        .order_by(ChapterAudioRun.audiobook_project_id, ChapterAudioRun.chapter_id)
    ).all()

    created = 0
    repointed = 0
    for project_id, chapter_id in groups:
        # 确定性选择：组内 active 行取 id 最大（canonical 去重后应恰有一条）
        target_id = session.execute(
            select(ChapterAudio.id)
            .where(
                ChapterAudio.audiobook_project_id == project_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .order_by(ChapterAudio.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if target_id is None:
            synthetic = ChapterAudio(audiobook_project_id=project_id, chapter_id=chapter_id)
            session.add(synthetic)
            session.flush()
            target_id = synthetic.id
            created += 1
        repointed += session.execute(
            update(ChapterAudioRun)
            .where(
                ChapterAudioRun.audiobook_project_id == project_id,
                ChapterAudioRun.chapter_id == chapter_id,
                ChapterAudioRun.chapter_audio_id.is_(None),
            )
            .values(chapter_audio_id=target_id)
        ).rowcount
    return {"synthetic_chapter_audios_created": created, "runs_repointed": repointed}


def _backfill_run_celery_task_id(session: Session) -> int:
    legacy_id = sa.func.concat("legacy-run-", sa.cast(ChapterAudioRun.id, sa.String()))
    return session.execute(
        update(ChapterAudioRun)
        .where(ChapterAudioRun.celery_task_id.is_(None))
        .values(celery_task_id=legacy_id)
    ).rowcount


def _backfill_run_dispatch_status(session: Session) -> int:
    return session.execute(
        update(ChapterAudioRun)
        .where(ChapterAudioRun.dispatch_status.is_(None))
        .values(dispatch_status="unknown")
    ).rowcount


def run_history_backfill(engine: sa.engine.Engine) -> dict[str, Any]:
    """执行全部历史回填，返回各项影响行数报告。

    engine 可为普通 engine（生产/dev 库）或带 ``schema_translate_map`` 的
    测试 engine；本服务不持有独立连接池策略，调用方决定。
    """
    report: dict[str, Any] = {}
    with Session(engine) as session:
        with session.begin():
            report["projects"] = _backfill_project_columns(session)
            report["run_engine_mode_snapshot"] = _backfill_run_engine_snapshot(session)
            report["chapter_audio_id"] = _backfill_run_chapter_audio_id(session)
            report["celery_task_id"] = _backfill_run_celery_task_id(session)
            report["dispatch_status"] = _backfill_run_dispatch_status(session)
    logger.info("history backfill completed: %s", report)
    return report
