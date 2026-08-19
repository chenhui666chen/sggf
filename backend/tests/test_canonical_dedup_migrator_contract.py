"""Phase 1.1 Migrate canonical 去重合并执行器合同测试（真实 PostgreSQL）。

覆盖 GUIDE R22/R21 迁移执行时序：
- canonical 选择优先级（有效已发布产物 → approved script+审核证据 → 字段完整 → updated_at → id）
- 事务 A：业务合并 + progress=completed 同事务提交
- 事务 B：fail-closed 独立短事务写 failed（不随事务 A 回滚消失）
- 断点续跑：completed+组级一致性校验通过才跳过；不一致重跑
- 会话锁：全局单实例，锁忙立即退出
- 软删除合同：迁移不做任何物理删除
"""

import os
import sys
import zlib
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
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

TEST_SCHEMA = "canonical_dedup_test"
MIGRATION_VERSION = "dedup-contract-v1"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun  # noqa: E402
from app.models.canonical_migration_progress import (  # noqa: E402
    AudiobookCanonicalMigrationProgress,
)
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402

_TABLES = [
    User.__table__,
    Project.__table__,
    Chapter.__table__,
    AudiobookProject.__table__,
    ChapterAudio.__table__,
    ChapterAudioRun.__table__,
    AudiobookCanonicalMigrationProgress.__table__,
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
    # 迁移器面向历史库：唯一 active 约束上线前的库没有该部分索引，
    # 建表后删除以还原历史形态，允许测试构造重复 active 脏数据
    with mapped.begin() as conn:
        conn.execute(text(f"DROP INDEX IF EXISTS {TEST_SCHEMA}.uq_chapter_audio_active_unique"))
    yield mapped
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_scope(db, tag: str):
    user = User(username=f"dd_{tag}", email=f"dd_{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"dd_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    return batch, chapter


def _add_audio(db, batch, chapter, **kw) -> ChapterAudio:
    row = ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id, **kw)
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _active_count(db, batch_id: int, chapter_id: int) -> int:
    return (
        db.query(ChapterAudio)
        .filter_by(audiobook_project_id=batch_id, chapter_id=chapter_id, deleted_at=None)
        .count()
    )


def _progress_row(db, batch_id: int, chapter_id: int):
    return (
        db.query(AudiobookCanonicalMigrationProgress)
        .filter_by(
            migration_version=MIGRATION_VERSION,
            audiobook_project_id=batch_id,
            chapter_id=chapter_id,
        )
        .one_or_none()
    )


def _run_migration(engine):
    from app.services.audiobook.canonical_dedup_migrator import run_canonical_dedup_migration

    return run_canonical_dedup_migration(
        DATABASE_URL, migration_version=MIGRATION_VERSION, engine=engine
    )


# ── canonical 选择优先级 ────────────────────────────────────────────────────


def test_canonical_priority_approved_review_beats_newer(db):
    """有 approved script + 审核证据的行优先于更新但残缺的行。"""
    from app.services.audiobook.canonical_dedup_migrator import select_canonical

    batch, chapter = _seed_scope(db, "prio1")
    older = _add_audio(
        db,
        batch,
        chapter,
        audio_path="a.mp3",
        script_json="{}",
        script_review_json='{"approved": true}',
        script_status="approved",
    )
    _add_audio(db, batch, chapter, audio_path="b.mp3", script_status="pending")
    rows = (
        db.query(ChapterAudio)
        .filter_by(audiobook_project_id=batch.id, chapter_id=chapter.id, deleted_at=None)
        .order_by(ChapterAudio.id)
        .all()
    )
    assert select_canonical(rows).id == older.id
    db.rollback()


def test_canonical_priority_published_beats_approved(db):
    """有效已发布产物（audio_path + published_run 证据）优先于仅 approved。"""
    from app.services.audiobook.canonical_dedup_migrator import select_canonical

    batch, chapter = _seed_scope(db, "prio2")
    approved = _add_audio(
        db,
        batch,
        chapter,
        script_json="{}",
        script_review_json="{}",
        script_status="approved",
    )
    published = _add_audio(
        db,
        batch,
        chapter,
        audio_path="pub.mp3",
        duration=10.0,
        file_size=100,
        published_provenance="legacy_unverified",
    )
    rows = [approved, published]
    assert select_canonical(rows).id == published.id
    db.rollback()


def test_canonical_tie_break_by_smallest_id(db):
    """完全同分确定性收敛：最小 id。"""
    from app.services.audiobook.canonical_dedup_migrator import select_canonical

    batch, chapter = _seed_scope(db, "prio3")
    r1 = _add_audio(db, batch, chapter)
    r2 = _add_audio(db, batch, chapter)
    assert select_canonical([r2, r1]).id == r1.id
    db.rollback()


# ── 事务 A：合并 + completed 同事务 ────────────────────────────────────────


def test_merge_group_single_active_and_progress_completed(db, engine):
    """重复组收敛为唯一 active；非 canonical 软删除（物理行保留）；progress completed 同事务。"""
    batch, chapter = _seed_scope(db, "merge1")
    canonical = _add_audio(
        db,
        batch,
        chapter,
        audio_path="keep.mp3",
        script_json="{}",
        script_review_json='{"ok": true}',
        script_status="approved",
    )
    dup1 = _add_audio(db, batch, chapter, audio_path="d1.mp3", final_audio_review_json='{"r": 1}')
    dup2 = _add_audio(db, batch, chapter)
    db.commit()

    report = _run_migration(engine)

    db.expire_all()
    assert _active_count(db, batch.id, chapter.id) == 1
    # 软删除：物理行仍存在，仅 deleted_at 置位
    for dup in (dup1, dup2):
        db.refresh(dup)
        assert dup.deleted_at is not None
    db.refresh(canonical)
    assert canonical.deleted_at is None
    # 审核证据合并：canonical 缺 final_audio_review_json 时从被合并行复制
    assert canonical.final_audio_review_json == '{"r": 1}'
    prog = _progress_row(db, batch.id, chapter.id)
    assert prog is not None and prog.status == "completed"
    assert prog.canonical_chapter_audio_id == canonical.id
    assert sorted(prog.source_row_ids) == sorted([dup1.id, dup2.id])
    assert prog.completed_at is not None
    assert report["completed"] >= 1 and report["failed"] == 0


def test_migration_never_physically_deletes(engine, session_factory):
    """迁移只软删除：模块源码不得包含物理删除调用。"""
    from app.services.audiobook import canonical_dedup_migrator as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "unlink" not in src
    assert "os.remove" not in src
    assert "shutil.rmtree" not in src


# ── 断点续跑 ────────────────────────────────────────────────────────────────


def test_resume_skips_completed_consistent_group(db, engine):
    """completed + 组级一致性校验通过 → 跳过，不重复处理。"""
    batch, chapter = _seed_scope(db, "resume1")
    _add_audio(db, batch, chapter, audio_path="k.mp3", script_status="approved", script_review_json="{}")
    _add_audio(db, batch, chapter)
    db.commit()

    first = _run_migration(engine)
    assert first["completed"] >= 1

    db.expire_all()
    prog = _progress_row(db, batch.id, chapter.id)
    attempts_after_first = prog.attempts
    completed_at_first = prog.completed_at

    second = _run_migration(engine)
    db.expire_all()
    prog = _progress_row(db, batch.id, chapter.id)
    assert prog.status == "completed"
    assert prog.completed_at == completed_at_first  # 未被重写
    assert prog.attempts == attempts_after_first  # 不递增
    assert second["skipped"] >= 1


def test_resume_reprocesses_completed_but_inconsistent_group(db, engine):
    """completed 但组内仍有多条 active（一致性校验失败）→ 重跑而非跳过。"""
    batch, chapter = _seed_scope(db, "resume2")
    _add_audio(db, batch, chapter, audio_path="k.mp3")
    _add_audio(db, batch, chapter)
    db.commit()

    _run_migration(engine)

    # 人为破坏一致性：复活一条被软删除的行（模拟并发旧路径写入）
    db.expire_all()
    dup = (
        db.query(ChapterAudio)
        .filter_by(audiobook_project_id=batch.id, chapter_id=chapter.id)
        .filter(ChapterAudio.deleted_at.isnot(None))
        .first()
    )
    dup.deleted_at = None
    db.commit()

    report = _run_migration(engine)
    db.expire_all()
    assert _active_count(db, batch.id, chapter.id) == 1
    prog = _progress_row(db, batch.id, chapter.id)
    assert prog.status == "completed"
    assert report["completed"] >= 1


# ── 事务 B：fail-closed 失败记录 ────────────────────────────────────────────


def test_group_failure_written_in_independent_transaction(db, engine, monkeypatch):
    """事务 A 回滚后事务 B 独立写 failed + 脱敏 failure_detail（不随回滚消失）。"""
    from app.services.audiobook import canonical_dedup_migrator as mod

    batch, chapter = _seed_scope(db, "failpath")
    _add_audio(db, batch, chapter, audio_path="k.mp3")
    _add_audio(db, batch, chapter)
    db.commit()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated merge failure")

    monkeypatch.setattr(mod, "_merge_group_txn", _boom)
    report = _run_migration(engine)

    db.expire_all()
    prog = _progress_row(db, batch.id, chapter.id)
    assert prog is not None and prog.status == "failed"
    assert prog.attempts == 1
    assert prog.last_error_code
    assert prog.last_failed_at is not None
    # 失败组不被伪装完成：组内仍是重复 active
    assert _active_count(db, batch.id, chapter.id) == 2
    assert report["failed"] >= 1
    # 失败详情脱敏：不含 DSN/堆栈帧标志
    assert "postgresql://" not in (prog.failure_detail or "")
    assert "Traceback" not in (prog.failure_detail or "")


def test_failed_group_retried_on_next_run(db, engine, monkeypatch):
    """failed 组在下次运行被认领重跑（修复后成功收敛）。"""
    from app.services.audiobook import canonical_dedup_migrator as mod

    batch, chapter = _seed_scope(db, "failretry")
    _add_audio(db, batch, chapter, audio_path="k.mp3")
    _add_audio(db, batch, chapter)
    db.commit()

    monkeypatch.setattr(
        mod, "_merge_group_txn", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    _run_migration(engine)
    monkeypatch.undo()

    report = _run_migration(engine)
    db.expire_all()
    prog = _progress_row(db, batch.id, chapter.id)
    assert prog.status == "completed"
    assert _active_count(db, batch.id, chapter.id) == 1
    assert report["completed"] >= 1


# ── 会话锁：全局单实例 ──────────────────────────────────────────────────────


def test_lock_busy_aborts_immediately(engine):
    """专用连接持锁时，迁移立即抛 MigrationLockBusy（不排队）。"""
    from app.services.audiobook.canonical_migration_progress import (
        MIGRATION_VERSION_LOCK_KEY,
        MigrationLockBusy,
    )
    from app.services.audiobook.canonical_dedup_migrator import run_canonical_dedup_migration

    holder = create_engine(DATABASE_URL, poolclass=NullPool).connect()
    try:
        acquired = holder.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": MIGRATION_VERSION_LOCK_KEY}
        ).scalar()
        assert acquired
        with pytest.raises(MigrationLockBusy):
            run_canonical_dedup_migration(
                DATABASE_URL, migration_version=MIGRATION_VERSION, engine=engine
            )
    finally:
        holder.execute(
            text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_VERSION_LOCK_KEY}
        )
        holder.rollback()
        holder.close()


def test_lock_released_after_successful_run(engine):
    """正常完成后会话锁释放：专用连接可随后获锁。"""
    from app.services.audiobook.canonical_migration_progress import MIGRATION_VERSION_LOCK_KEY

    _run_migration(engine)
    probe = create_engine(DATABASE_URL, poolclass=NullPool).connect()
    try:
        acquired = probe.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": MIGRATION_VERSION_LOCK_KEY}
        ).scalar()
        assert acquired
        probe.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_VERSION_LOCK_KEY})
    finally:
        probe.rollback()
        probe.close()
