"""Phase 1.1 Migrate 余项历史回填合同测试（真实 PostgreSQL）。

覆盖 GUIDE §1.1 Contract 前置回填：
- engine_mode 回填（无 seed_scene 证据 → legacy_stems）
- snapshot_status 三态回填（证据不足 → legacy_unverified）
- run.engine_mode_snapshot 自批次 engine_mode 回填
- run.chapter_audio_id 确定性回填（R10/P1-1：缺失 active 时创建，全部历史 run 改指，不留空）
- celery_task_id 仅审计 legacy id 回填（legacy-run-{id}，不做 broker 关联）
- dispatch_status 归一（历史 NULL → unknown）
- 幂等：重复执行结果不变
"""

import os
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

_env_path = ROOT_DIR / ".env"
# 无条件从 .env 读取（其他测试模块可能已写入无效占位 URL，如 test_auth_routes）
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break

DATABASE_URL = os.environ.get("DATABASE_URL", "")

TEST_SCHEMA = "history_backfill_test"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun  # noqa: E402
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.history_backfill import run_history_backfill  # noqa: E402

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
    mapped = eng.execution_options(schema_translate_map={None: TEST_SCHEMA})
    Base.metadata.create_all(bind=mapped, tables=_TABLES)
    # 模拟 Expand 态历史库：dispatch_status 的 NOT NULL 属 Contract 产物，回填阶段尚未施加
    with eng.begin() as conn:
        conn.execute(text(
            f"ALTER TABLE {TEST_SCHEMA}.chapter_audio_runs ALTER COLUMN dispatch_status DROP NOT NULL"
        ))
    yield mapped
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _check_session(engine):
    """验证用独立会话（不经 pytest fixture，可直接传 engine）。"""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _seed_legacy_scope(db, tag: str):
    """构造一个典型遗留作用域：批次 + 章节 + 无 ChapterAudio 的历史 run。"""
    user = User(username=f"hb_{tag}", email=f"hb_{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"hb_{tag}", user_id=user.id, display_no=1)
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
        run_type="full",
        status="completed",
    )
    db.add(run)
    db.flush()
    return batch, chapter, run


def test_engine_mode_and_snapshot_backfill(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "eng")
    db.commit()

    report = run_history_backfill(engine)

    with _check_session(engine) as check:
        row = check.execute(
            select(
                AudiobookProject.engine_mode,
                AudiobookProject.snapshot_status,
            ).where(AudiobookProject.id == batch.id)
        ).one()
        assert row[0] == "legacy_stems"
        assert row[1] == "legacy_unverified"

    # 幂等：二次执行不改变结果
    report2 = run_history_backfill(engine)
    with _check_session(engine) as check:
        row = check.execute(
            select(AudiobookProject.engine_mode, AudiobookProject.snapshot_status)
            .where(AudiobookProject.id == batch.id)
        ).one()
        assert row == ("legacy_stems", "legacy_unverified")
    assert isinstance(report, dict) and isinstance(report2, dict)


def test_run_engine_mode_snapshot_backfill(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "snap")
    db.commit()

    run_history_backfill(engine)

    with _check_session(engine) as check:
        value = check.execute(
            select(ChapterAudioRun.engine_mode_snapshot).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert value == "legacy_stems"


def test_run_chapter_audio_id_creates_missing_active(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "caid")
    db.commit()

    run_history_backfill(engine)

    with _check_session(engine) as check:
        target_id = check.execute(
            select(ChapterAudioRun.chapter_audio_id).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert target_id is not None
        active = check.execute(
            select(ChapterAudio.id).where(
                ChapterAudio.audiobook_project_id == batch.id,
                ChapterAudio.chapter_id == chapter.id,
                ChapterAudio.deleted_at.is_(None),
            )
        ).all()
        assert [r[0] for r in active] == [target_id]

    # 幂等：二次执行不创建新行、指向不变
    run_history_backfill(engine)
    with _check_session(engine) as check:
        again = check.execute(
            select(ChapterAudioRun.chapter_audio_id).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert again == target_id
        active = check.execute(
            select(sa.func.count()).where(
                ChapterAudio.audiobook_project_id == batch.id,
                ChapterAudio.chapter_id == chapter.id,
                ChapterAudio.deleted_at.is_(None),
            )
        ).scalar_one()
        assert active == 1


def test_run_chapter_audio_id_reuses_existing_active(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "reuse")
    existing = ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id)
    db.add(existing)
    db.flush()
    db.commit()

    run_history_backfill(engine)

    with _check_session(engine) as check:
        target_id = check.execute(
            select(ChapterAudioRun.chapter_audio_id).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert target_id == existing.id


def test_celery_task_id_legacy_backfill(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "cel")
    keeper = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="completed",
        celery_task_id="real-uuid-kept",
    )
    db.add(keeper)
    db.commit()

    run_history_backfill(engine)

    with _check_session(engine) as check:
        filled = check.execute(
            select(ChapterAudioRun.celery_task_id).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert filled == f"legacy-run-{run.id}"
        untouched = check.execute(
            select(ChapterAudioRun.celery_task_id).where(ChapterAudioRun.id == keeper.id)
        ).scalar_one()
        assert untouched == "real-uuid-kept"


def test_dispatch_status_null_to_unknown(db, engine):
    batch, chapter, run = _seed_legacy_scope(db, "disp")
    db.commit()
    # 模拟历史行：旧代码未写 dispatch_status（列默认是后续 Contract 才有的事实）
    with engine.begin() as conn:
        conn.execute(text(
            f"UPDATE {TEST_SCHEMA}.chapter_audio_runs SET dispatch_status = NULL WHERE id = :id"
        ), {"id": run.id})

    run_history_backfill(engine)

    with _check_session(engine) as check:
        value = check.execute(
            select(ChapterAudioRun.dispatch_status).where(ChapterAudioRun.id == run.id)
        ).scalar_one()
        assert value == "unknown"


def test_no_null_chapter_audio_id_remains(db, engine):
    _seed_legacy_scope(db, "final")
    db.commit()

    run_history_backfill(engine)

    with _check_session(engine) as check:
        remaining = check.execute(
            select(sa.func.count()).where(ChapterAudioRun.chapter_audio_id.is_(None))
        ).scalar_one()
        assert remaining == 0
