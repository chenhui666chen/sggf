# -*- coding: utf-8 -*-
"""派发协议终态收敛回归测试（真实 PostgreSQL）。

背景（run 131/132 事故）：已 completed 的 run 残留 dispatch_status='dispatched'
+ claim_token=NULL，beat 每个周期日志"未认领超时重投"但：
1. `_requeue_stale_dispatched` 更新未 commit → 每周期回滚，永远空转；
2. 扫描不排除终态 run → 即便重投生效，completed run 也会被再次派发执行。
合同：
- 终态 run 不进入 stale-pending / 未认领重投扫描；
- 未认领重投对活跃 run 必须真实落库（独立会话可见）；
- run 终态写回时 dispatch_status 同步收敛为 cancelled。
"""

import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

_env_path = ROOT_DIR / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break

DATABASE_URL = os.environ.get("DATABASE_URL", "")

TEST_SCHEMA = "audiobook_dispatch_terminal_test"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
    ChapterAudioRun,
)
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook import dispatch_service, task_support  # noqa: E402
from app.utils.datetime_utils import utc_now  # noqa: E402

_TABLES = [
    User.__table__,
    Project.__table__,
    Chapter.__table__,
    AudiobookProject.__table__,
    ChapterAudio.__table__,
    ChapterAudioRun.__table__,
]


@pytest.fixture(scope="module")
def engine():
    _require_pg()
    eng = create_engine(DATABASE_URL, poolclass=NullPool)
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    yield eng.execution_options(schema_translate_map={None: TEST_SCHEMA})
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    Base.metadata.create_all(bind=engine, tables=_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_run(db, tag: str, *, status: str, dispatch_status: str) -> int:
    user = User(username=f"user_{tag}", email=f"{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"proj_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="audio_from_scripts",
        status=status,
        dispatch_status=dispatch_status,
        celery_task_id=str(uuid.uuid4()),
        dispatch_attempts=1,
    )
    db.add(run)
    db.commit()
    return run.id


def _mark_stale_unclaimed(db, run_id: int) -> None:
    """置成 dispatched 未认领且超时的形态（worker 从未 claim）。"""
    db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).update(
        {
            ChapterAudioRun.claim_token: None,
            ChapterAudioRun.dispatched_at: utc_now()
            - timedelta(seconds=dispatch_service.DISPATCH_ACK_TIMEOUT_SECONDS + 60),
        },
        synchronize_session=False,
    )
    db.commit()


def test_requeue_skips_terminal_dispatched_run(session_factory):
    """已 completed 的 dispatched 未认领 run 不得被重投（防止终态 run 死循环）。"""
    db = session_factory()
    run_id = _seed_run(db, "requeue_terminal", status="completed", dispatch_status="dispatched")
    _mark_stale_unclaimed(db, run_id)

    try:
        requeued = dispatch_service._requeue_stale_dispatched(db)
    finally:
        db.close()

    assert requeued == 0
    check = session_factory()
    try:
        run = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        assert run.dispatch_status == "dispatched"
    finally:
        check.close()


def test_requeue_commits_for_live_stale_run(session_factory):
    """活跃 run 的未认领重投必须真实落库（独立会话可见 pending）。"""
    db = session_factory()
    run_id = _seed_run(db, "requeue_live", status="queued", dispatch_status="dispatched")
    _mark_stale_unclaimed(db, run_id)

    try:
        requeued = dispatch_service._requeue_stale_dispatched(db)
    finally:
        db.close()

    assert requeued == 1
    check = session_factory()
    try:
        run = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        # 修复前：更新未 commit，db.close() 回滚 → 独立会话仍读 dispatched
        assert run.dispatch_status == "pending"
        assert run.dispatched_at is None
    finally:
        check.close()


def test_stale_pending_scan_skips_terminal_run(session_factory, monkeypatch):
    """终态 run 即便残留 pending + 到期，也不得被认领投递（防止终态 run 被重跑）。"""
    db = session_factory()
    run_id = _seed_run(db, "scan_terminal", status="completed", dispatch_status="pending")
    db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).update(
        {ChapterAudioRun.next_dispatch_at: utc_now() - timedelta(seconds=60)},
        synchronize_session=False,
    )
    # 隔离：解除共享 schema 中其他用例遗留的 pending run，避免干扰计数
    db.query(ChapterAudioRun).filter(
        ChapterAudioRun.id != run_id,
        ChapterAudioRun.dispatch_status == "pending",
    ).update(
        {ChapterAudioRun.next_dispatch_at: None},
        synchronize_session=False,
    )
    db.commit()

    sent = []
    monkeypatch.setattr(
        dispatch_service, "_apply_async_safe",
        lambda tid, run: sent.append(run.id) or "success",
    )
    attempts_before = (
        db.query(ChapterAudioRun.dispatch_attempts)
        .filter(ChapterAudioRun.id == run_id)
        .scalar()
    )
    try:
        result = dispatch_service.claim_and_dispatch_stale_pending(db)
    finally:
        db.close()

    assert result["dispatched"] == 0
    assert sent == []
    check = session_factory()
    try:
        run = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        assert run.dispatch_attempts == attempts_before
    finally:
        check.close()


def test_terminal_writeback_converges_dispatch_status(session_factory, monkeypatch):
    """run 终态写回必须同步收敛 dispatch_status，杜绝残留 dispatched/pending。"""
    monkeypatch.setattr(task_support, "build_run_checkpoint_document", lambda db, **kwargs: {})
    from app.services.audiobook import ledger_transition_service

    monkeypatch.setattr(
        ledger_transition_service, "close_accounting_on_run_terminal",
        lambda db, **kwargs: None,
    )

    for tag, initial in (("converge_dispatched", "dispatched"), ("converge_pending", "pending")):
        db = session_factory()
        run_id = _seed_run(db, tag, status="running", dispatch_status=initial)
        run = db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        try:
            task_support.update_chapter_run_state(
                db,
                audiobook_project_id=run.audiobook_project_id,
                chapter_id=run.chapter_id,
                run_type=run.run_type,
                status="completed",
                current_stage="done",
                progress=1.0,
                run_id=run_id,
            )
            db.commit()
        finally:
            db.close()

        check = session_factory()
        try:
            refreshed = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
            assert refreshed.status == "completed"
            # 修复前：终态写回不清 dispatch_status → beat 扫描永远命中
            assert refreshed.dispatch_status == "cancelled"
        finally:
            check.close()
