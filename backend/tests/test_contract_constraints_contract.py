"""Phase 1.1 Contract 约束收窄合同测试（真实 PostgreSQL）。

覆盖 GUIDE §1.1 Contract 单元门禁化收窄：
- 门禁：全表无重复 active 组验证（fail-closed 前置）
- audiobook_projects：engine_mode NOT NULL + server_default + CHECK；snapshot_status 三态 CHECK；
  快照一致性 CHECK（frozen 必有快照 / legacy_unfrozen 不得带快照）
- chapter_audio_runs：dispatch_status NOT NULL + server_default='pending' + CHECK；
  run status 值域 CHECK（含 expired）
- chapter_audios：部分唯一索引 UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL
- INVALID 索引身份校验（R21/P2-2）：定义一致的 INVALID 可 DROP 重建；同名不同定义有效索引停止 Contract
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

TEST_SCHEMA = "contract_constraints_test"
INDEX_NAME = "uq_chapter_audio_active_unique"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import AudiobookProject, ChapterAudio, ChapterAudioRun  # noqa: E402
from app.models.project import Chapter, Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.audiobook.contract_constraints import (  # noqa: E402
    apply_project_contract,
    apply_run_contract,
    create_chapter_audio_active_unique_index,
    verify_no_duplicate_active,
)
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
def raw_engine():
    _require_pg()
    eng = create_engine(DATABASE_URL, poolclass=NullPool)
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    mapped = eng.execution_options(schema_translate_map={None: TEST_SCHEMA})
    Base.metadata.create_all(bind=mapped, tables=_TABLES)
    # 模拟 Expand 态历史库：NOT NULL/默认属 Contract 产物，收窄前尚未施加
    with eng.begin() as conn:
        conn.execute(text(
            f"ALTER TABLE {TEST_SCHEMA}.chapter_audio_runs ALTER COLUMN dispatch_status DROP NOT NULL"
        ))
        conn.execute(text(
            f"ALTER TABLE {TEST_SCHEMA}.chapter_audio_runs ALTER COLUMN dispatch_status DROP DEFAULT"
        ))
        conn.execute(text(
            f"ALTER TABLE {TEST_SCHEMA}.audiobook_projects ALTER COLUMN engine_mode DROP NOT NULL"
        ))
        conn.execute(text(
            f"ALTER TABLE {TEST_SCHEMA}.audiobook_projects ALTER COLUMN engine_mode DROP DEFAULT"
        ))
        # 唯一 active 索引属 Contract 产物（由 create_chapter_audio_active_unique_index 施加），
        # 建表后删除以还原 Expand 态历史库，允许门禁/迁移测试构造重复 active 脏数据
        conn.execute(text(f"DROP INDEX IF EXISTS {TEST_SCHEMA}.uq_chapter_audio_active_unique"))
    yield eng
    with eng.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    eng.dispose()


@pytest.fixture(scope="module")
def engine(raw_engine):
    return raw_engine.execution_options(schema_translate_map={None: TEST_SCHEMA})


@pytest.fixture()
def db(engine):
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _seed_legacy_run(db, tag: str):
    """构造一条带 run 的遗留作用域（供 run 级约束验证）。"""
    batch, chapter = _seed_scope(db, tag)
    db.add(ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="completed",
    ))
    db.flush()
    return batch, chapter


def _seed_scope(db, tag: str):
    user = User(username=f"cc_{tag}", email=f"cc_{tag}@example.com", password_hash="h", is_active=True)
    db.add(user)
    db.flush()
    project = Project(title=f"cc_{tag}", user_id=user.id, display_no=1)
    db.add(project)
    db.flush()
    chapter = Chapter(project_id=project.id, chapter_number=1, title=f"ch_{tag}", content="x")
    db.add(chapter)
    db.flush()
    batch = AudiobookProject(project_id=project.id)
    db.add(batch)
    db.flush()
    return batch, chapter


def test_gate_detects_duplicate_active(db, engine):
    batch, chapter = _seed_scope(db, "gate")
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.add(ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id))
    db.commit()

    with engine.connect() as conn:
        dups = verify_no_duplicate_active(conn, schema=TEST_SCHEMA)
    assert (batch.id, chapter.id) in dups

    # 软删除较早一条后门禁通过（保留 id 最大行）
    with engine.begin() as conn:
        conn.execute(text(
            f"UPDATE {TEST_SCHEMA}.chapter_audios SET deleted_at = now() "
            "WHERE audiobook_project_id=:p AND chapter_id=:c AND deleted_at IS NULL "
            f"AND id < (SELECT max(id) FROM {TEST_SCHEMA}.chapter_audios "
            "WHERE audiobook_project_id=:p AND chapter_id=:c AND deleted_at IS NULL)"
        ), {"p": batch.id, "c": chapter.id})
    with engine.begin() as conn:
        row = conn.execute(text(
            f"SELECT count(*) FROM {TEST_SCHEMA}.chapter_audios "
            "WHERE deleted_at IS NULL AND audiobook_project_id=:p AND chapter_id=:c"
        ), {"p": batch.id, "c": chapter.id}).scalar()
        assert row >= 1
    with engine.connect() as conn:
        dups = verify_no_duplicate_active(conn, schema=TEST_SCHEMA)
    assert (batch.id, chapter.id) not in dups


def test_project_contract_engine_mode(db, engine):
    run_history_backfill(engine)
    with engine.begin() as conn:
        apply_project_contract(conn, schema=TEST_SCHEMA)

    batch, chapter = _seed_scope(db, "pm")
    db.commit()
    # 显式 NULL 被拒
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {TEST_SCHEMA}.audiobook_projects (project_id, engine_mode) "
                "VALUES (:p, NULL)"
            ), {"p": batch.project_id})
    # 非法值被拒
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {TEST_SCHEMA}.audiobook_projects (project_id, engine_mode) "
                "VALUES (:p, 'bogus_engine')"
            ), {"p": batch.project_id})
    # 省略列时 server_default 生效
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {TEST_SCHEMA}.audiobook_projects (project_id) VALUES (:p)"
        ), {"p": batch.project_id})
        value = conn.execute(text(
            f"SELECT engine_mode FROM {TEST_SCHEMA}.audiobook_projects "
            "WHERE project_id=:p ORDER BY id DESC LIMIT 1"
        ), {"p": batch.project_id}).scalar()
        assert value == "legacy_stems"


def test_project_contract_snapshot_consistency(db, engine):
    with engine.begin() as conn:
        apply_project_contract(conn, schema=TEST_SCHEMA)

    batch, chapter = _seed_scope(db, "snapck")
    db.commit()
    project_id = batch.project_id

    def _insert(status, snapshot):
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {TEST_SCHEMA}.audiobook_projects "
                "(project_id, engine_mode, snapshot_status, engine_config_snapshot) "
                "VALUES (:pid, 'legacy_stems', :s, :snap)"
            ), {"pid": project_id, "s": status, "snap": snapshot})

    # 三态外值被拒
    with pytest.raises(sa.exc.IntegrityError, match="ck_audiobook_projects_snapshot_status"):
        _insert("bogus", None)
    # frozen 无快照被拒
    with pytest.raises(sa.exc.IntegrityError, match="ck_audiobook_projects_snapshot_consistency"):
        _insert("frozen", None)
    # frozen 带快照合法
    _insert("frozen", '{"engine_mode":"seed_scene"}')
    # legacy_unverified 无快照合法（dev 历史行语义）
    _insert("legacy_unverified", None)
    # legacy_unfrozen 带快照为非法组合
    with pytest.raises(sa.exc.IntegrityError, match="ck_audiobook_projects_snapshot_consistency"):
        _insert("legacy_unfrozen", '{"x":1}')


def test_run_contract_dispatch_and_status(db, engine):
    _seed_legacy_run(db, "runck")
    db.commit()
    run_history_backfill(engine)
    with engine.begin() as conn:
        apply_run_contract(conn, schema=TEST_SCHEMA)

    # dispatch_status 非法值被拒
    with pytest.raises(sa.exc.IntegrityError, match="ck_chapter_audio_runs_dispatch_status"):
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE {s}.chapter_audio_runs SET dispatch_status='bogus' "
                "WHERE id=(SELECT min(id) FROM {s}.chapter_audio_runs)".format(s=TEST_SCHEMA)
            ))
    # run status 非法值被拒、expired 合法
    with pytest.raises(sa.exc.IntegrityError, match="ck_chapter_audio_runs_status"):
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE {s}.chapter_audio_runs SET status='not_a_status' "
                "WHERE id=(SELECT min(id) FROM {s}.chapter_audio_runs)".format(s=TEST_SCHEMA)
            ))
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE {s}.chapter_audio_runs SET status='expired' "
            "WHERE id=(SELECT min(id) FROM {s}.chapter_audio_runs)".format(s=TEST_SCHEMA)
        ))
    # 新 run 省略 dispatch_status 时默认 pending
    with engine.begin() as conn:
        scope = conn.execute(text(
            f"SELECT audiobook_project_id, chapter_id FROM {TEST_SCHEMA}.chapter_audio_runs LIMIT 1"
        )).first()
        conn.execute(text(
            f"INSERT INTO {TEST_SCHEMA}.chapter_audio_runs "
            "(audiobook_project_id, chapter_id, run_type, status, resumable) "
            "VALUES (:p, :c, 'full', 'pending', true)"
        ), {"p": scope[0], "c": scope[1]})
        value = conn.execute(text(
            f"SELECT dispatch_status FROM {TEST_SCHEMA}.chapter_audio_runs "
            "ORDER BY id DESC LIMIT 1"
        )).scalar()
        assert value == "pending"


def test_active_unique_index_rejects_duplicate(engine):
    with engine.begin() as conn:
        dups = verify_no_duplicate_active(conn, schema=TEST_SCHEMA)
        assert dups == [], "建索引前门禁必须通过"
    with engine.begin() as conn:
        create_chapter_audio_active_unique_index(conn, schema=TEST_SCHEMA, concurrent=False)

    with engine.begin() as conn:
        scope = conn.execute(text(
            f"SELECT audiobook_project_id, chapter_id FROM {TEST_SCHEMA}.chapter_audios "
            "WHERE deleted_at IS NULL LIMIT 1"
        )).first()
    assert scope is not None, "需要至少一条 active 行用于验证"
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {TEST_SCHEMA}.chapter_audios (audiobook_project_id, chapter_id) "
                "VALUES (:p, :c)"
            ), {"p": scope[0], "c": scope[1]})
    # 软删除行不参与唯一约束
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO {TEST_SCHEMA}.chapter_audios "
            "(audiobook_project_id, chapter_id, deleted_at) VALUES (:p, :c, now())"
        ), {"p": scope[0], "c": scope[1]})


def test_invalid_index_identity_recovery(raw_engine):
    """R21/P2-2：定义一致的 INVALID 索引可 DROP 重建；同名不同定义有效索引停止 Contract。"""
    autocommit = raw_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        # 前置清理：前序测试可能已建成同名有效索引
        autocommit.execute(text(f"DROP INDEX IF EXISTS {TEST_SCHEMA}.{INDEX_NAME}"))
        # 制造重复 active 使 CONCURRENTLY 建索引失败留下 INVALID
        with raw_engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO {TEST_SCHEMA}.chapter_audios (audiobook_project_id, chapter_id) "
                f"SELECT audiobook_project_id, chapter_id FROM {TEST_SCHEMA}.chapter_audios "
                "WHERE deleted_at IS NULL LIMIT 1"
            ))
        # CONCURRENTLY 遇重复会报错但留下 INVALID 索引（预期行为）
        with pytest.raises(sa.exc.IntegrityError):
            autocommit.execute(text(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
                f"ON {TEST_SCHEMA}.chapter_audios (audiobook_project_id, chapter_id) "
                "WHERE deleted_at IS NULL"
            ))
        invalid = autocommit.execute(text(
            "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            f"WHERE n.nspname='{TEST_SCHEMA}' AND c.relname='{INDEX_NAME}' AND NOT i.indisvalid"
        )).scalar()
        assert invalid == 1, "前置：INVALID 索引已存在"

        # 清理重复：每组保留 id 最小的 active 行，其余物理删除（测试隔离数据，非生产路径）
        with raw_engine.begin() as conn:
            conn.execute(text(
                f"DELETE FROM {TEST_SCHEMA}.chapter_audios ca WHERE ca.deleted_at IS NULL AND EXISTS ("
                f"SELECT 1 FROM {TEST_SCHEMA}.chapter_audios keep "
                "WHERE keep.audiobook_project_id = ca.audiobook_project_id "
                "AND keep.chapter_id = ca.chapter_id AND keep.deleted_at IS NULL "
                "AND keep.id < ca.id)"
            ))
        create_chapter_audio_active_unique_index(autocommit, schema=TEST_SCHEMA, concurrent=True)
        valid = autocommit.execute(text(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            f"WHERE n.nspname='{TEST_SCHEMA}' AND c.relname='{INDEX_NAME}'"
        )).scalar()
        assert valid is True

        # 同名不同定义的有效索引 → 停止 Contract（抛错）
        autocommit.execute(text(f"DROP INDEX IF EXISTS {TEST_SCHEMA}.{INDEX_NAME}"))
        autocommit.execute(text(
            f"CREATE UNIQUE INDEX {INDEX_NAME} ON {TEST_SCHEMA}.chapter_audios "
            "(chapter_id) WHERE deleted_at IS NULL"
        ))
        with pytest.raises(RuntimeError, match="停止 Contract"):
            create_chapter_audio_active_unique_index(autocommit, schema=TEST_SCHEMA, concurrent=True)
        autocommit.execute(text(f"DROP INDEX IF EXISTS {TEST_SCHEMA}.{INDEX_NAME}"))
    finally:
        autocommit.close()
