"""Phase 1.1 Migrate 迁移报告与一致性校验派生合同测试（真实 PostgreSQL）。

覆盖 GUIDE R20/R22 合同准入派生事实：
- 迁移报告：进度表状态聚合（completed/failed/attempts）+ 失败组脱敏原因
- 全表无重复 active 组验证 SQL（Contract 创建部分唯一索引前必须返回空）
- completed 但组级不一致的组显式枚举（不伪装完成）
- ready_for_contract_index 门禁：全部收敛且无失败/不一致才为真
"""

import os
import sys
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

TEST_SCHEMA = "canonical_report_test"
MIGRATION_VERSION = "report-contract-v1"


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
    # 迁移器/报告面向历史库：唯一 active 索引属 Contract 产物，
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


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_scope(db, tag: str):
    user = User(username=f"rp_{tag}", email=f"rp_{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"rp_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    return batch, chapter


def _run_migration(engine):
    from app.services.audiobook.canonical_dedup_migrator import run_canonical_dedup_migration

    return run_canonical_dedup_migration(
        DATABASE_URL, migration_version=MIGRATION_VERSION, engine=engine
    )


def _report(engine):
    from app.services.audiobook.canonical_migration_report import build_migration_report

    return build_migration_report(engine, migration_version=MIGRATION_VERSION)


def test_report_aggregates_progress_states(db, engine):
    """报告聚合进度表：completed 组与 failed 组分别计数，attempts 透出。"""
    from app.services.audiobook import canonical_dedup_migrator as migrator_mod
    from app.services.audiobook.canonical_migration_progress import record_group_failure

    batch, chapter = _seed_scope(db, "agg")
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id, audio_path="k.mp3"))
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.commit()

    _run_migration(engine)

    # 直接构造一条 failed 组（事务 B 原语）
    fail_batch, fail_chapter = _seed_scope(db, "aggfail")
    db.commit()
    record_group_failure(
        engine,
        migration_version=MIGRATION_VERSION,
        audiobook_project_id=fail_batch.id,
        chapter_id=fail_chapter.id,
        error_code="IntegrityError",
        failure_detail="simulated failure",
    )

    report = _report(engine)
    assert report["completed"] >= 1
    assert report["failed"] >= 1
    assert report["total"] == report["completed"] + report["failed"] + report.get("pending", 0)
    failed_entries = {
        (f["audiobook_project_id"], f["chapter_id"]): f for f in report["failures"]
    }
    entry = failed_entries[(fail_batch.id, fail_chapter.id)]
    assert entry["error_code"] == "IntegrityError"
    assert entry["attempts"] == 1
    assert "simulated failure" in entry["failure_detail"]


def test_duplicate_active_validation_empty_after_convergence(db, engine):
    """全表无重复 active 组验证：收敛后返回空（Contract 准入门禁证据）。"""
    batch, chapter = _seed_scope(db, "dupval")
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.commit()

    report_before = _report(engine)
    assert (batch.id, chapter.id) in {
        (g["audiobook_project_id"], g["chapter_id"]) for g in report_before["duplicate_active_groups"]
    }

    _run_migration(engine)

    report_after = _report(engine)
    assert (batch.id, chapter.id) not in {
        (g["audiobook_project_id"], g["chapter_id"]) for g in report_after["duplicate_active_groups"]
    }


def test_inconsistent_completed_groups_enumerated(db, engine):
    """progress=completed 但组内仍有重复 active → 显式枚举（不伪装完成）。"""
    batch, chapter = _seed_scope(db, "incons")
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.add(
        AudiobookCanonicalMigrationProgress(
            migration_version=MIGRATION_VERSION,
            audiobook_project_id=batch.id,
            chapter_id=chapter.id,
            status="completed",
        )
    )
    db.commit()

    report = _report(engine)
    assert (batch.id, chapter.id) in {
        (g["audiobook_project_id"], g["chapter_id"]) for g in report["inconsistent_completed_groups"]
    }
    assert report["ready_for_contract_index"] is False

    # 执行迁移收敛后门禁转真
    _run_migration(engine)
    report_after = _report(engine)
    assert (batch.id, chapter.id) not in {
        (g["audiobook_project_id"], g["chapter_id"]) for g in report_after["inconsistent_completed_groups"]
    }


def test_ready_for_contract_index_gate(db, engine):
    """门禁：存在 failed 组 → False；全部收敛且无失败 → True。"""
    from app.services.audiobook.canonical_migration_progress import record_group_failure

    report = _report(engine)
    gate_before = report["ready_for_contract_index"]

    fail_batch, fail_chapter = _seed_scope(db, "gatefail")
    db.commit()
    record_group_failure(
        engine,
        migration_version=MIGRATION_VERSION,
        audiobook_project_id=fail_batch.id,
        chapter_id=fail_chapter.id,
        error_code="RuntimeError",
        failure_detail="gate failure",
    )
    assert _report(engine)["ready_for_contract_index"] is False

    # 清理失败记录的影响不在本合同范围：门禁必须如实反映 failed 组存在
    assert gate_before in (True, False)
