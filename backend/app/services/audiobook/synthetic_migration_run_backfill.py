"""历史产物归属回填与 synthetic migration run（GUIDE R9/P1-1，R10/P1-1，验收 38/50）。

回填规则（全部幂等、确定性）：
1. 有 ``audio_path`` 且 ``published_run_id IS NULL`` 的历史章节：
   - 找到最新 ``status='completed'`` 且 ``run_type ∈ {full, audio_from_scripts, chapter_remix}``
     的 run → 回填 ``published_run_id`` + published ``ChapterAudioOutput`` +
     ``published_provenance='legacy_unverified'``（可导出但不作为 CAS 发布基线）；
   - 无法确认 run 归属 → 创建 synthetic migration run（``run_type='migration_placeholder'``、
     ``status='completed'``、``dispatch_status='cancelled'``——不可恢复/不可结算/不可重试/
     不可派发），``published_run_id`` 指向它，保持双指针模型与复合外键成立。
2. 历史 seed 产物 ``render_status`` 保持 null（不精确回填，API 按
   ``published_provenance='legacy_unverified'`` 显式渲染"历史产物（未验证）"）。

本模块只做数据回填，不收窄任何约束。
"""

from __future__ import annotations

import logging
from typing import Any, List

import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.audiobook import (
    AudiobookProject,
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
)

logger = logging.getLogger(__name__)

# 可作为历史产物归属的 run_type（验收 38：full/audio_from_scripts/chapter_remix）
_HISTORY_OWNER_RUN_TYPES = ("full", "audio_from_scripts", "chapter_remix")


def _find_owner_run(
    session: Session,
    *,
    audiobook_project_id: int,
    chapter_id: int,
) -> ChapterAudioRun | None:
    """找最新 completed 且 run_type 匹配的 run（确定性归属）。"""
    return session.execute(
        select(ChapterAudioRun)
        .where(
            ChapterAudioRun.audiobook_project_id == audiobook_project_id,
            ChapterAudioRun.chapter_id == chapter_id,
            ChapterAudioRun.status == "completed",
            ChapterAudioRun.run_type.in_(_HISTORY_OWNER_RUN_TYPES),
            ChapterAudioRun.deleted_at.is_(None),
        )
        .order_by(ChapterAudioRun.finished_at.desc().nullslast(), ChapterAudioRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _create_synthetic_migration_run(
    session: Session,
    *,
    chapter_audio: ChapterAudio,
) -> ChapterAudioRun:
    """创建 synthetic migration run（验收 38/50：不可恢复/结算/重试/派发）。"""
    synthetic = ChapterAudioRun(
        audiobook_project_id=chapter_audio.audiobook_project_id,
        chapter_id=chapter_audio.chapter_id,
        chapter_audio_id=chapter_audio.id,
        run_type="migration_placeholder",
        status="completed",
        dispatch_status="cancelled",
        current_stage="completed",
        progress=1.0,
        finished_at=sa.func.now(),
        resumable=False,
        celery_task_id=f"legacy-migration-{chapter_audio.id}",
    )
    session.add(synthetic)
    session.flush()
    return synthetic


def _backfill_published_output(
    session: Session,
    *,
    run: ChapterAudioRun,
    chapter_audio: ChapterAudio,
) -> int:
    """回填 published ChapterAudioOutput（每 run 至多一条，幂等 upsert）。"""
    existing = session.execute(
        select(ChapterAudioOutput)
        .where(ChapterAudioOutput.run_id == run.id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status != "published":
            existing.status = "published"
            existing.published_at = sa.func.now()
        return 0

    subtitle_path = str(chapter_audio.subtitle_path or "").strip() or None
    session.add(
        ChapterAudioOutput(
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=chapter_audio.audiobook_project_id,
            chapter_id=chapter_audio.chapter_id,
            status="published",
            audio_path=str(chapter_audio.audio_path or ""),
            duration=chapter_audio.duration,
            file_size=chapter_audio.file_size,
            subtitle_path=subtitle_path,
            subtitle_format=(
                str(chapter_audio.subtitle_format or "srt")
                if subtitle_path
                else None
            ),
            published_at=sa.func.now(),
        )
    )
    return 1


def run_synthetic_migration_backfill(engine: sa.engine.Engine) -> dict[str, Any]:
    """执行历史产物归属回填，返回报告。

    engine 可为普通 engine（生产/dev 库）或带 ``schema_translate_map`` 的测试
    engine；幂等——重复执行不重复创建 synthetic run/输出登记。
    """
    report: dict[str, Any] = {
        "scanned_chapters": 0,
        "owner_run_backfilled": 0,
        "synthetic_runs_created": 0,
        "outputs_registered": 0,
    }

    with Session(engine) as session:
        with session.begin():
            chapters = session.execute(
                select(ChapterAudio)
                .where(
                    ChapterAudio.audio_path.isnot(None),
                    ChapterAudio.audio_path != "",
                    ChapterAudio.published_run_id.is_(None),
                    ChapterAudio.deleted_at.is_(None),
                )
                .order_by(ChapterAudio.id.asc())
            ).scalars().all()

            for chapter_audio in chapters:
                report["scanned_chapters"] += 1
                owner_run = _find_owner_run(
                    session,
                    audiobook_project_id=chapter_audio.audiobook_project_id,
                    chapter_id=chapter_audio.chapter_id,
                )
                if owner_run is not None and owner_run.chapter_audio_id == chapter_audio.id:
                    # 确定性归属：completed run 存在且作用域一致 → 回填指针
                    session.execute(
                        update(ChapterAudio)
                        .where(ChapterAudio.id == chapter_audio.id)
                        .values(
                            published_run_id=owner_run.id,
                            published_provenance="legacy_unverified",
                        )
                    )
                    report["outputs_registered"] += _backfill_published_output(
                        session, run=owner_run, chapter_audio=chapter_audio,
                    )
                    report["owner_run_backfilled"] += 1
                else:
                    # 无法确认归属 → synthetic migration run（复合外键合法成立）
                    synthetic = _create_synthetic_migration_run(
                        session, chapter_audio=chapter_audio,
                    )
                    session.execute(
                        update(ChapterAudio)
                        .where(ChapterAudio.id == chapter_audio.id)
                        .values(
                            published_run_id=synthetic.id,
                            published_provenance="legacy_unverified",
                        )
                    )
                    report["outputs_registered"] += _backfill_published_output(
                        session, run=synthetic, chapter_audio=chapter_audio,
                    )
                    report["synthetic_runs_created"] += 1

    logger.info("synthetic migration run backfill completed: %s", report)
    return report


__all__ = [
    "run_synthetic_migration_backfill",
]
