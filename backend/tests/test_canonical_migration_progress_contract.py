"""audiobook_canonical_migration_progress 合同测试（R22/P1-1、R22/P1-2、R22/P1-3）。

必须运行于真实 PostgreSQL——CHECK 值域、ON CONFLICT fail-closed、
pg_try_advisory_lock 会话锁行为均无法用 SQLite 验证（GUIDE R22 验收 61 / §7）。
"""

import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

# 从 backend/.env 读取真实 PostgreSQL 连接（不写死凭证）
_env_path = ROOT_DIR / ".env"
# 无条件从 .env 读取（其他测试模块可能已写入无效占位 URL，如 test_auth_routes）
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break

DATABASE_URL = os.environ.get("DATABASE_URL", "")

TEST_SCHEMA = "canonical_migration_test"

from app.models.canonical_migration_progress import (  # noqa: E402
    AudiobookCanonicalMigrationProgress,
)
from app.db.base import Base  # noqa: E402
from app.services.audiobook.canonical_migration_progress import (  # noqa: E402
    MIGRATION_VERSION_LOCK_KEY,
    MigrationLockBusy,
    migration_session_lock,
    record_group_failure,
)


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL（DATABASE_URL 未配置或不是 postgresql）")


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
def tables(engine):
    Base.metadata.create_all(bind=engine, tables=[AudiobookCanonicalMigrationProgress.__table__])
    return engine


@pytest.fixture()
def session(tables):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=tables, autocommit=False, autoflush=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _new_group(db, version="v1", project_id=1, chapter_id=1, status="pending"):
    row = AudiobookCanonicalMigrationProgress(
        migration_version=version,
        audiobook_project_id=project_id,
        chapter_id=chapter_id,
        canonical_chapter_audio_id=None,
        source_row_ids=[],
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def test_status_check_rejects_running(session):
    """R22/P1-1：status 值域仅 pending/completed/failed，running 不可落库。"""
    with pytest.raises(IntegrityError):
        _new_group(session, status="running")
    session.rollback()


def test_status_check_rejects_unknown(session):
    with pytest.raises(IntegrityError):
        _new_group(session, status="claimed")
    session.rollback()


def test_unique_migration_version_project_chapter(session):
    _new_group(session, version="v-uniq", project_id=9, chapter_id=9)
    with pytest.raises(IntegrityError):
        _new_group(session, version="v-uniq", project_id=9, chapter_id=9)
    session.rollback()


def test_attempts_defaults_zero(session):
    row = _new_group(session, version="v-attempts", project_id=10, chapter_id=10)
    assert row.attempts == 0


def _read(db, version, project_id, chapter_id):
    return (
        db.query(AudiobookCanonicalMigrationProgress)
        .filter_by(
            migration_version=version,
            audiobook_project_id=project_id,
            chapter_id=chapter_id,
        )
        .one()
    )


def test_fail_closed_upsert_writes_failed_on_pending(session):
    """事务 B：pending 组确认失败 → failed + attempts 递增。"""
    _new_group(session, version="v-b", project_id=2, chapter_id=2)
    record_group_failure(
        session.bind,
        migration_version="v-b",
        audiobook_project_id=2,
        chapter_id=2,
        error_code="merge_conflict",
        failure_detail="runs repoint conflict",
    )
    row = _read(session, "v-b", 2, 2)
    assert row.status == "failed"
    assert row.attempts == 1
    assert row.last_error_code == "merge_conflict"
    assert row.last_failed_at is not None


def test_fail_closed_upsert_inserts_when_absent(session):
    """事务 B 对无进度行的组也必须 upsert 成功（首次失败）。"""
    record_group_failure(
        session.bind,
        migration_version="v-absent",
        audiobook_project_id=3,
        chapter_id=3,
        error_code="io_error",
        failure_detail="connection reset",
    )
    row = _read(session, "v-absent", 3, 3)
    assert row.status == "failed"
    assert row.attempts == 1


def test_fail_closed_upsert_never_overwrites_completed(session):
    """R22/P1-2：已提交的 completed 绝不被 failed 覆盖，attempts 不递增。"""
    _new_group(session, version="v-c", project_id=4, chapter_id=4, status="completed")
    record_group_failure(
        session.bind,
        migration_version="v-c",
        audiobook_project_id=4,
        chapter_id=4,
        error_code="uncertain_commit",
        failure_detail="client disconnect after commit",
    )
    row = _read(session, "v-c", 4, 4)
    assert row.status == "completed"
    assert row.attempts == 0
    assert row.last_error_code is None


def test_fail_closed_upsert_increments_attempts_per_failure(session):
    """attempts 仅在确认失败并写入事务 B 时递增。"""
    _new_group(session, version="v-d", project_id=5, chapter_id=5)
    for expected in (1, 2, 3):
        record_group_failure(
            session.bind,
            migration_version="v-d",
            audiobook_project_id=5,
            chapter_id=5,
            error_code="transient",
            failure_detail=f"attempt {expected}",
        )
    row = _read(session, "v-d", 5, 5)
    assert row.attempts == 3
    assert row.status == "failed"


def test_session_lock_second_instance_fails_immediately(tables):
    """R22/P1-3：会话锁被实例 A 持有时，实例 B 获取失败立即抛出（不排队）。"""
    with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY) as info_a:
        assert info_a["run_id"]
        assert info_a["pid"]
        with pytest.raises(MigrationLockBusy):
            with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
                pass


def test_session_lock_released_after_normal_exit(tables):
    """正常完成路径：finally 解锁后，新实例可立即获锁。"""
    with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
        pass
    with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
        pass  # 第二次获取成功即证明已解锁


def test_session_lock_released_after_exception(tables):
    """异常退出路径：finally 解锁并关闭连接，后续实例可获锁。"""
    with pytest.raises(RuntimeError):
        with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
            raise RuntimeError("simulated migration failure")
    with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
        pass


def test_session_lock_released_on_connection_drop(tables):
    """进程死亡模拟：专用连接被强制关闭（断连）后锁自动释放。"""
    lock_engine = create_engine(DATABASE_URL, poolclass=NullPool)
    conn = lock_engine.connect()
    acquired = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": MIGRATION_VERSION_LOCK_KEY}).scalar()
    assert acquired is True
    # 模拟进程崩溃：连接未经 unlock 直接失效
    conn.invalidate()
    lock_engine.dispose()
    # 断连后数据库自动释放会话锁，新实例可获锁
    with migration_session_lock(DATABASE_URL, MIGRATION_VERSION_LOCK_KEY):
        pass
