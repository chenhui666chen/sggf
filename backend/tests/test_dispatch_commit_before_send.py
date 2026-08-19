# -*- coding: utf-8 -*-
"""try_dispatch_run 先落库后投递合同测试（真实 PostgreSQL）。

背景（run 132 事故）：原实现先 send_task 后 flush dispatched 状态，
worker 毫秒级消费时读到未提交的 pending → 租约认领失败、消息被 ACK 丢弃。
合同：send_task 时刻，独立会话必须已能读到 dispatch_status='dispatched'。
"""

import os
import sys
import uuid
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

TEST_SCHEMA = "audiobook_dispatch_order_test"


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
from app.services.audiobook import dispatch_service  # noqa: E402
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


def _seed_run(db, tag: str) -> int:
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
        status="queued",
        dispatch_status="pending",
        celery_task_id=str(uuid.uuid4()),
        next_dispatch_at=utc_now(),
    )
    db.add(run)
    db.commit()
    return run.id


def test_dispatched_state_committed_before_send(session_factory, monkeypatch):
    """合同：send_task 时刻独立会话必须已读到 dispatched（worker 租约前置条件）。"""
    db = session_factory()
    run_id = _seed_run(db, "commit_first")

    observed = {}

    def _spy_apply_async(celery_task_id, run):
        # 模拟 worker 毫秒级消费：用独立会话读库（worker 租约前置条件）
        observer = session_factory()
        try:
            state = (
                observer.query(ChapterAudioRun.dispatch_status)
                .filter(ChapterAudioRun.id == run_id)
                .scalar()
            )
            observed["dispatch_status_at_send"] = state
        finally:
            observer.close()
        return "success"

    monkeypatch.setattr(dispatch_service, "_apply_async_safe", _spy_apply_async)
    try:
        outcome = dispatch_service.try_dispatch_run(db, run_id=run_id)
    finally:
        db.close()

    assert outcome == "dispatched"
    # 修复前：send 时刻状态为 pending（仅 flush 未 commit）→ worker 租约失败
    assert observed["dispatch_status_at_send"] == "dispatched"


def test_send_failure_compensates_to_cancelled(session_factory, monkeypatch):
    """先标记后投递失败 → 补偿生效，run 置 cancelled，不得残留 dispatched。"""
    db = session_factory()
    run_id = _seed_run(db, "compensate")

    monkeypatch.setattr(dispatch_service, "_apply_async_safe", lambda tid, run: "failed")
    try:
        outcome = dispatch_service.try_dispatch_run(db, run_id=run_id)
    finally:
        db.close()

    assert outcome == "failed"
    check = session_factory()
    try:
        run = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        assert run.dispatch_status == "cancelled"
        assert run.status == "cancelled"
        assert run.error_message and "dispatch_failed" in run.error_message
    finally:
        check.close()


def test_unknown_outcome_keeps_dispatched_for_stale_requeue(session_factory, monkeypatch):
    """投递结果未知 → 保留 dispatched（claim_token 为空），由超时重投兜底。"""
    db = session_factory()
    run_id = _seed_run(db, "unknown_keep")

    monkeypatch.setattr(dispatch_service, "_apply_async_safe", lambda tid, run: "unknown")
    try:
        outcome = dispatch_service.try_dispatch_run(db, run_id=run_id)
    finally:
        db.close()

    assert outcome == "unknown"
    check = session_factory()
    try:
        run = check.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).one()
        # _requeue_stale_dispatched 的兜底条件：dispatched + claim_token IS NULL
        assert run.dispatch_status == "dispatched"
        assert run.claim_token is None
        assert run.dispatched_at is not None
    finally:
        check.close()


def test_already_dispatched_run_skipped(session_factory, monkeypatch):
    db = session_factory()
    run_id = _seed_run(db, "skip_dup")
    db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).update(
        {ChapterAudioRun.dispatch_status: "dispatched"},
        synchronize_session=False,
    )
    db.commit()

    called = []
    monkeypatch.setattr(
        dispatch_service, "_apply_async_safe",
        lambda tid, run: called.append(1) or "success",
    )
    try:
        outcome = dispatch_service.try_dispatch_run(db, run_id=run_id)
    finally:
        db.close()

    assert outcome == "skipped"
    assert called == []
