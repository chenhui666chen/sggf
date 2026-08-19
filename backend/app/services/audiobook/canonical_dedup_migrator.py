"""Phase 1.1 Migrate canonical 去重合并执行器（GUIDE R11/P1-5、R19/P1-3、R20-R22）。

合同要点：
- 全局单实例：进入即取 migration_session_lock（专用非池化连接会话锁），锁忙立即退出；
- 每组独立事务 A：组级 advisory xact lock → progress FOR UPDATE → 锁后重查
  （completed 且组级一致性校验通过才跳过；不一致重跑）→ canonical 选择/审核证据合并/
  非 canonical 行软删除/progress=completed 同事务提交；
- 事务 A 失败回滚后由事务 B（record_group_failure，fail-closed）独立短事务写 failed；
- 断点续跑：按未完成组枚举，失败组带原因不伪装完成；
- 去重只做软删除（deleted_at 置位），物理音频文件保留，严禁任何物理删除调用。
"""

from __future__ import annotations

import zlib

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.audiobook import ChapterAudio
from app.models.canonical_migration_progress import AudiobookCanonicalMigrationProgress
from app.services.audiobook.canonical_migration_progress import (
    migration_session_lock,
    record_group_failure,
)

# 字段完整度参与 canonical 评分的事实字段（R11/P1-5 优先级第三档）
_COMPLETENESS_FIELDS = (
    "audio_path",
    "subtitle_path",
    "script_json",
    "script_review_json",
    "final_audio_review_json",
)

# 被合并行的审核证据合并至 canonical 的字段（产物审核证据合并，R11/P1-5）
_REVIEW_EVIDENCE_FIELDS = (
    "script_review_json",
    "final_audio_review_json",
    "segment_reviews_json",
)


def select_canonical(rows: list[ChapterAudio]) -> ChapterAudio:
    """按 R11/P1-5 优先级选保留行：

    有效已发布产物 → approved script + 审核证据 → 完整字段 → 更新时间 → id（确定性收敛）。
    """

    def _score(row: ChapterAudio):
        published = 1 if (
            row.audio_path and (row.published_provenance or row.published_run_id)
        ) else 0
        approved = 1 if (row.script_status == "approved" and row.script_review_json) else 0
        completeness = sum(1 for name in _COMPLETENESS_FIELDS if getattr(row, name, None))
        if (row.duration or 0) > 0:
            completeness += 1
        if (row.file_size or 0) > 0:
            completeness += 1
        return (published, approved, completeness, row.updated_at or row.created_at, -row.id)

    return max(rows, key=_score)


def _group_lock_key(migration_version: str, project_id: int, chapter_id: int) -> int:
    """组级 advisory lock 键（确定性派生；兼作与在线创建路径串行化，R21/P1-2）。"""
    raw = f"{migration_version}:{project_id}:{chapter_id}".encode("utf-8")
    return zlib.crc32(raw) & 0x7FFFFFFF


def _list_groups(engine, migration_version: str, batch_limit: int | None):
    """枚举待处理组（断点续跑入口）：重复 active 组 ∪ 已有进度记录组。

    并集保证 completed 组也能被重读进度 + 组级一致性校验后显式跳过（R22 续跑合同），
    而非因“已无重复行”静默消失。
    """
    duplicate_groups = (
        select(
            ChapterAudio.audiobook_project_id.label("audiobook_project_id"),
            ChapterAudio.chapter_id.label("chapter_id"),
        )
        .where(ChapterAudio.deleted_at.is_(None))
        .group_by(ChapterAudio.audiobook_project_id, ChapterAudio.chapter_id)
        .having(func.count(ChapterAudio.id) > 1)
    )
    progress_groups = select(
        AudiobookCanonicalMigrationProgress.audiobook_project_id.label("audiobook_project_id"),
        AudiobookCanonicalMigrationProgress.chapter_id.label("chapter_id"),
    ).where(AudiobookCanonicalMigrationProgress.migration_version == migration_version)
    stmt = duplicate_groups.union(progress_groups).order_by(
        text("audiobook_project_id"), text("chapter_id")
    )
    if batch_limit:
        stmt = stmt.limit(batch_limit)
    with engine.connect() as conn:
        return [(int(row[0]), int(row[1])) for row in conn.execute(stmt)]


def _ensure_progress_row(engine, migration_version: str, project_id: int, chapter_id: int) -> None:
    """组进入处理前确保进度行存在（幂等；失败路径事务 B 同样依赖此行存在与否均可 upsert）。"""
    table = AudiobookCanonicalMigrationProgress
    stmt = pg_insert(table).values(
        migration_version=migration_version,
        audiobook_project_id=project_id,
        chapter_id=chapter_id,
        status="pending",
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["migration_version", "audiobook_project_id", "chapter_id"]
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def _group_consistent(session: Session, project_id: int, chapter_id: int) -> bool:
    """组级一致性校验：组内 active 行已收敛至多一条（R22 重试跳过前提）。"""
    active = (
        session.query(func.count(ChapterAudio.id))
        .filter_by(
            audiobook_project_id=project_id, chapter_id=chapter_id, deleted_at=None
        )
        .scalar()
    )
    return int(active or 0) <= 1


def _merge_review_evidence(canonical: ChapterAudio, others: list[ChapterAudio]) -> None:
    """被合并行的审核证据缺失时补入 canonical（字段复制，不删除来源）。"""
    for name in _REVIEW_EVIDENCE_FIELDS:
        if getattr(canonical, name, None):
            continue
        for row in others:
            value = getattr(row, name, None)
            if value:
                setattr(canonical, name, value)
                break


def _merge_group_txn(engine, migration_version: str, project_id: int, chapter_id: int) -> str:
    """事务 A：单组认领、合并与 completed 同事务提交（回滚即整体消失）。

    返回 "completed"（本事务完成合并或无需合并）或 "skipped"（已完成且一致性通过）。
    """
    with Session(engine) as session:
        with session.begin():
            progress = (
                session.query(AudiobookCanonicalMigrationProgress)
                .filter_by(
                    migration_version=migration_version,
                    audiobook_project_id=project_id,
                    chapter_id=chapter_id,
                )
                .with_for_update()
                .one()
            )
            if progress.status == "completed" and _group_consistent(session, project_id, chapter_id):
                return "skipped"
            # 组级 advisory 事务锁：与在线创建路径串行化；事务结束自动释放
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _group_lock_key(migration_version, project_id, chapter_id)},
            )
            progress.last_started_at = func.now()
            rows = (
                session.query(ChapterAudio)
                .filter_by(
                    audiobook_project_id=project_id, chapter_id=chapter_id, deleted_at=None
                )
                .order_by(ChapterAudio.id)
                .all()
            )
            canonical = select_canonical(rows) if rows else None
            others = [row for row in rows if canonical is not None and row.id != canonical.id]
            if canonical is not None and others:
                _merge_review_evidence(canonical, others)
                for row in others:
                    row.deleted_at = func.now()  # 仅软删除：物理文件保留，严禁物理删除
            progress.status = "completed"
            progress.canonical_chapter_audio_id = canonical.id if canonical else None
            progress.source_row_ids = [row.id for row in others]
            progress.completed_at = func.now()
        return "completed"


def run_canonical_dedup_migration(
    database_url: str,
    *,
    migration_version: str,
    engine,
    batch_limit: int | None = None,
) -> dict:
    """执行一轮 canonical 去重合并迁移（全局单实例）。

    `engine` 为业务数据引擎（测试可携带 schema_translate_map）；
    `database_url` 仅用于会话锁的专用非池化连接。
    """
    report = {"total": 0, "completed": 0, "skipped": 0, "failed": 0, "failures": []}
    with migration_session_lock(database_url):
        groups = _list_groups(engine, migration_version, batch_limit)
        report["total"] = len(groups)
        for project_id, chapter_id in groups:
            _ensure_progress_row(engine, migration_version, project_id, chapter_id)
            try:
                outcome = _merge_group_txn(engine, migration_version, project_id, chapter_id)
                report["completed" if outcome == "completed" else "skipped"] += 1
            except Exception as exc:  # noqa: BLE001 —— 事务 A 已回滚；事务 B 独立写 failed
                report["failed"] += 1
                report["failures"].append(
                    {
                        "audiobook_project_id": project_id,
                        "chapter_id": chapter_id,
                        "error_code": type(exc).__name__[:64],
                    }
                )
                record_group_failure(
                    engine,
                    migration_version=migration_version,
                    audiobook_project_id=project_id,
                    chapter_id=chapter_id,
                    error_code=type(exc).__name__[:64],
                    failure_detail=str(exc),
                )
    return report
