"""Phase 1.1 Migrate 迁移报告与一致性校验派生（GUIDE R20/P1-2、R22）。

派生合同准入证据（只读、可重复执行）：
- 进度表状态聚合与失败组脱敏原因（失败组带原因不伪装完成）；
- 全表无重复 active 组验证（Contract 创建部分唯一索引前必须返回空）；
- completed 但组级不一致的组显式枚举；
- ready_for_contract_index 门禁：全部收敛且无失败/不一致才为真。
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.audiobook import ChapterAudio
from app.models.canonical_migration_progress import AudiobookCanonicalMigrationProgress


def _duplicate_active_groups(engine) -> list[dict]:
    """全表重复 active 组验证 SQL（Contract 准入：必须返回空）。"""
    stmt = (
        select(
            ChapterAudio.audiobook_project_id,
            ChapterAudio.chapter_id,
            func.count(ChapterAudio.id).label("active_count"),
        )
        .where(ChapterAudio.deleted_at.is_(None))
        .group_by(ChapterAudio.audiobook_project_id, ChapterAudio.chapter_id)
        .having(func.count(ChapterAudio.id) > 1)
        .order_by(ChapterAudio.audiobook_project_id, ChapterAudio.chapter_id)
    )
    with engine.connect() as conn:
        return [
            {
                "audiobook_project_id": int(row[0]),
                "chapter_id": int(row[1]),
                "active_count": int(row[2]),
            }
            for row in conn.execute(stmt)
        ]


def build_migration_report(engine, *, migration_version: str) -> dict:
    """迁移报告：进度聚合 + 一致性校验派生 + Contract 门禁。"""
    progress = AudiobookCanonicalMigrationProgress
    stmt = select(
        progress.audiobook_project_id,
        progress.chapter_id,
        progress.status,
        progress.attempts,
        progress.last_error_code,
        progress.last_failed_at,
        progress.failure_detail,
    ).where(progress.migration_version == migration_version)
    with engine.connect() as conn:
        rows = list(conn.execute(stmt))

    counts = {"completed": 0, "failed": 0, "pending": 0}
    failures: list[dict] = []
    completed_groups: set[tuple[int, int]] = set()
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
        if row.status == "completed":
            completed_groups.add((row.audiobook_project_id, row.chapter_id))
        elif row.status == "failed":
            failures.append(
                {
                    "audiobook_project_id": row.audiobook_project_id,
                    "chapter_id": row.chapter_id,
                    "error_code": row.last_error_code,
                    "attempts": row.attempts,
                    "last_failed_at": row.last_failed_at.isoformat() if row.last_failed_at else None,
                    "failure_detail": row.failure_detail,
                }
            )

    duplicate_active_groups = _duplicate_active_groups(engine)
    duplicate_keys = {
        (group["audiobook_project_id"], group["chapter_id"])
        for group in duplicate_active_groups
    }
    inconsistent_completed_groups = [
        group
        for group in duplicate_active_groups
        if (group["audiobook_project_id"], group["chapter_id"]) in completed_groups
    ]

    ready = (
        not duplicate_active_groups
        and not failures
        and not inconsistent_completed_groups
    )

    return {
        "migration_version": migration_version,
        "total": len(rows),
        "completed": counts["completed"],
        "failed": counts["failed"],
        "pending": counts["pending"],
        "failures": failures,
        "duplicate_active_groups": duplicate_active_groups,
        "inconsistent_completed_groups": inconsistent_completed_groups,
        "ready_for_contract_index": ready,
    }
