"""Phase 1.1 Expand schema 合同测试（真实 PostgreSQL）。

覆盖 GUIDE §1.1：ledger 四态 CHECK 与可结算性、reconciliation audit 单调性、
append-only trigger（迁移产物，dev 库事务内回滚验证）、双指针 RESTRICT、
部分唯一索引。SQLite 无法验证 trigger/partial index，必须真实 PG。
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError
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

TEST_SCHEMA = "audiobook_expand_test"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
    ChapterAudioOutput,
    ChapterAudioRun,
    SceneAudioArtifact,
    SceneEditRevision,
)
from app.models.billing_usage_ledger import (  # noqa: E402
    BillingUsageLedger,
    LedgerReconciliationAudit,
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
    ChapterAudioOutput.__table__,
    SceneAudioArtifact.__table__,
    SceneEditRevision.__table__,
    BillingUsageLedger.__table__,
    LedgerReconciliationAudit.__table__,
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


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_scope(db, tag: str):
    """创建 user/project/chapter/批次/chapter_audio/run 一条完整作用域链。"""
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
    chapter_audio = ChapterAudio(audiobook_project_id=batch.id, chapter_id=chapter.id)
    db.add(chapter_audio)
    db.flush()
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        chapter_audio_id=chapter_audio.id,
        run_type="full",
    )
    db.add(run)
    db.flush()
    return user, project, chapter, batch, chapter_audio, run


# ── billing_usage_ledger CHECK ─────────────────────────────────────────────


def test_ledger_rejects_succeeded_without_pricing_facts(db):
    """R16/P0、R17/P1-4：succeeded 必须 quantity>0 + pricing_key + billing_snapshot_id。"""
    _, _, _, _, _, run = _seed_scope(db, "ledgerck")
    db.add(
        BillingUsageLedger(
            run_id=run.id,
            status="succeeded",
            attempt_key="k1",
            provider="seed_provider",
            usage_kind="seed_render",
            unit="second",
            quantity=Decimal("12.5"),
            # pricing_key / billing_snapshot_id 缺失 → CHECK 拒绝
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ledger_rejects_bad_unit(db):
    _, _, _, _, _, run = _seed_scope(db, "ledgerunit")
    db.add(
        BillingUsageLedger(
            run_id=run.id,
            status="pending",
            attempt_key="k1",
            provider="seed_provider",
            usage_kind="seed_render",
            unit="minute",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_ledger_succeeded_with_full_pricing_facts_passes(db):
    _, _, _, _, _, run = _seed_scope(db, "ledgerok")
    db.add(
        BillingUsageLedger(
            run_id=run.id,
            status="succeeded",
            attempt_key="k1",
            provider="seed_provider",
            usage_kind="seed_render",
            unit="second",
            quantity=Decimal("12.5"),
            pricing_key="seed_scene",
            billing_snapshot_id="snap-1",
        )
    )
    db.flush()
    db.rollback()


def test_ledger_attempt_key_unique(db):
    """同 run 同 attempt_key 只记一条（调用前写 pending，重试幂等）。"""
    _, _, _, _, _, run = _seed_scope(db, "ledgerdup")
    ledger_kwargs = dict(
        run_id=run.id,
        status="pending",
        attempt_key="same-key",
        provider="seed_provider",
        usage_kind="seed_render",
        unit="second",
    )
    db.add(BillingUsageLedger(**ledger_kwargs))
    db.flush()
    db.add(BillingUsageLedger(**ledger_kwargs))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ── ledger_reconciliation_audits CHECK ─────────────────────────────────────


def _seed_manual_ledger(db, tag: str) -> BillingUsageLedger:
    _, _, _, _, _, run = _seed_scope(db, tag)
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="manual_reconciliation",
        attempt_key="k1",
        provider="seed_provider",
        usage_kind="seed_render",
        unit="second",
    )
    db.add(ledger)
    db.flush()
    return ledger


def test_audit_rejects_stage_regression(db):
    """R18/P1-1：succeeded 收敛 commit_stage 单调不减——result_persisted 不得倒退为 post_call。"""
    ledger = _seed_manual_ledger(db, "auditmono")
    db.add(
        LedgerReconciliationAudit(
            ledger_id=ledger.id,
            to_status="succeeded",
            operator_user_id=1,
            operator_username="admin",
            reason="manual check",
            evidence={"receipt": "ok"},
            confirmed_quantity=Decimal("10"),
            previous_commit_stage="result_persisted",
            new_commit_stage="post_call",  # 倒退 → CHECK 拒绝
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_audit_allows_stage_monotonic_advance(db):
    ledger = _seed_manual_ledger(db, "auditadvance")
    db.add(
        LedgerReconciliationAudit(
            ledger_id=ledger.id,
            to_status="succeeded",
            operator_user_id=1,
            operator_username="admin",
            reason="manual check",
            evidence={"receipt": "ok"},
            confirmed_quantity=Decimal("10"),
            previous_commit_stage="post_call",
            new_commit_stage="result_persisted",
        )
    )
    db.flush()
    db.rollback()


def test_audit_rejects_succeeded_without_quantity(db):
    ledger = _seed_manual_ledger(db, "auditqty")
    db.add(
        LedgerReconciliationAudit(
            ledger_id=ledger.id,
            to_status="succeeded",
            operator_user_id=1,
            operator_username="admin",
            reason="manual check",
            evidence={},
            confirmed_quantity=None,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_audit_confirmed_failed_must_not_carry_quantity(db):
    ledger = _seed_manual_ledger(db, "auditcf")
    db.add(
        LedgerReconciliationAudit(
            ledger_id=ledger.id,
            to_status="confirmed_failed",
            operator_user_id=1,
            operator_username="admin",
            reason="provider error",
            evidence={},
            confirmed_quantity=Decimal("1"),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ── append-only trigger（迁移产物：dev 库，事务内验证后整体回滚）────────────


@pytest.fixture()
def dev_conn():
    """直连 dev 库（已应用 Expand 迁移）；全程单事务，结束回滚，不污染数据。"""
    _require_pg()
    eng = create_engine(DATABASE_URL, poolclass=NullPool)
    conn = eng.connect()
    tx = conn.begin()
    yield conn
    tx.rollback()
    conn.close()
    eng.dispose()


def _require_expand_applied(conn) -> bool:
    row = conn.execute(
        text(
            "SELECT to_regclass('public.ledger_reconciliation_audits') IS NOT NULL "
            "AND to_regclass('public.scene_edit_revisions') IS NOT NULL"
        )
    ).scalar()
    return bool(row)


def test_audit_table_rejects_update_and_delete(dev_conn):
    """R19/P2-2：数据库级 append-only——直接 SQL 修改/删除被 trigger 拒绝。"""
    if not _require_expand_applied(dev_conn):
        pytest.skip("dev 库尚未应用 Expand 迁移")
    # 先插一条 run/ledger 依赖链（dev 库事务内）
    dev_conn.execute(
        text(
            "INSERT INTO users (username, email, password_hash, is_active) "
            "VALUES ('audit_trg_user', 'audit_trg@example.com', 'h', true) "
            "ON CONFLICT (username) DO NOTHING"
        )
    )
    user_id = dev_conn.execute(
        text("SELECT id FROM users WHERE username = 'audit_trg_user'")
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO projects (title, display_no, user_id, status, word_count) "
            "VALUES ('audit_trg_proj', 901, :uid, 'draft', 0) RETURNING id"
        ).bindparams(uid=user_id)
    )
    project_id = dev_conn.execute(
        text("SELECT id FROM projects WHERE title = 'audit_trg_proj' AND user_id = :uid"),
        {"uid": user_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO chapters (project_id, chapter_number, title, content, status, word_count) "
            "VALUES (:pid, 1, 'audit_trg_ch', 'x', 'draft', 0) RETURNING id"
        ),
        {"pid": project_id},
    )
    chapter_id = dev_conn.execute(
        text("SELECT id FROM chapters WHERE project_id = :pid AND title = 'audit_trg_ch'"),
        {"pid": project_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO audiobook_projects (project_id, snapshot_status) "
            "VALUES (:pid, 'legacy_unverified') RETURNING id"
        ),
        {"pid": project_id},
    )
    batch_id = dev_conn.execute(
        text("SELECT id FROM audiobook_projects WHERE project_id = :pid ORDER BY id DESC LIMIT 1"),
        {"pid": project_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO chapter_audios (audiobook_project_id, chapter_id) VALUES (:bid, :cid) RETURNING id"
        ),
        {"bid": batch_id, "cid": chapter_id},
    )
    ca_id = dev_conn.execute(
        text(
            "SELECT id FROM chapter_audios WHERE audiobook_project_id = :bid ORDER BY id DESC LIMIT 1"
        ),
        {"bid": batch_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO chapter_audio_runs "
            "(audiobook_project_id, chapter_id, chapter_audio_id, run_type, celery_task_id) "
            "VALUES (:bid, :cid, :caid, 'full', :task_id) RETURNING id"
        ),
        {"bid": batch_id, "cid": chapter_id, "caid": ca_id, "task_id": f"audit-trg-{project_id}"},
    )
    run_id = dev_conn.execute(
        text(
            "SELECT id FROM chapter_audio_runs WHERE audiobook_project_id = :bid ORDER BY id DESC LIMIT 1"
        ),
        {"bid": batch_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO billing_usage_ledger (run_id, status, attempt_key, provider, usage_kind, unit) "
            "VALUES (:rid, 'manual_reconciliation', 'trg-key', 'seed_provider', 'seed_render', 'second') "
            "RETURNING id"
        ),
        {"rid": run_id},
    )
    ledger_id = dev_conn.execute(
        text(
            "SELECT id FROM billing_usage_ledger WHERE run_id = :rid AND attempt_key = 'trg-key'"
        ),
        {"rid": run_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO ledger_reconciliation_audits "
            "(ledger_id, to_status, operator_user_id, operator_username, reason, evidence, confirmed_quantity, "
            " previous_commit_stage, new_commit_stage) "
            "VALUES (:lid, 'succeeded', 1, 'admin', 'r', '{}'::json, 10, 'pre_call', 'post_call') "
            "RETURNING id"
        ),
        {"lid": ledger_id},
    )
    audit_id = dev_conn.execute(text("SELECT max(id) FROM ledger_reconciliation_audits")).scalar()

    # savepoint 内验证 UPDATE/DELETE 被 trigger 拒绝，避免全量回滚丢失种子链
    with pytest.raises((InternalError, ProgrammingError)):
        with dev_conn.begin_nested():
            dev_conn.execute(
                text("UPDATE ledger_reconciliation_audits SET reason = 'tampered' WHERE id = :aid"),
                {"aid": audit_id},
            )
    with pytest.raises((InternalError, ProgrammingError)):
        with dev_conn.begin_nested():
            dev_conn.execute(
                text("DELETE FROM ledger_reconciliation_audits WHERE id = :aid"), {"aid": audit_id}
            )


def test_scene_edit_revisions_rejects_update_and_delete(dev_conn):
    """§2.9：scene_edit_revisions 严格 append-only。"""
    if not _require_expand_applied(dev_conn):
        pytest.skip("dev 库尚未应用 Expand 迁移")
    dev_conn.execute(
        text(
            "INSERT INTO users (username, email, password_hash, is_active) "
            "VALUES ('ser_trg_user', 'ser_trg@example.com', 'h', true) ON CONFLICT (username) DO NOTHING"
        )
    )
    user_id = dev_conn.execute(text("SELECT id FROM users WHERE username = 'ser_trg_user'")).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO projects (title, display_no, user_id, status, word_count) "
            "VALUES ('ser_trg_proj', 902, :uid, 'draft', 0)"
        ),
        {"uid": user_id},
    )
    project_id = dev_conn.execute(
        text("SELECT id FROM projects WHERE title = 'ser_trg_proj' AND user_id = :uid"), {"uid": user_id}
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO chapters (project_id, chapter_number, title, content, status, word_count) "
            "VALUES (:pid, 1, 'ser_trg_ch', 'x', 'draft', 0)"
        ),
        {"pid": project_id},
    )
    chapter_id = dev_conn.execute(
        text("SELECT id FROM chapters WHERE project_id = :pid AND title = 'ser_trg_ch'"), {"pid": project_id}
    ).scalar()
    dev_conn.execute(text(
            "INSERT INTO audiobook_projects (project_id, snapshot_status) "
            "VALUES (:pid, 'legacy_unverified')"
        ), {"pid": project_id})
    batch_id = dev_conn.execute(
        text("SELECT id FROM audiobook_projects WHERE project_id = :pid ORDER BY id DESC LIMIT 1"),
        {"pid": project_id},
    ).scalar()
    dev_conn.execute(
        text(
            "INSERT INTO scene_edit_revisions "
            "(audiobook_project_id, chapter_id, edit_type, payload, input_signature, revision_hash) "
            "VALUES (:bid, :cid, 'dialogue', '{}', 'sig-1', 'hash-1') RETURNING id"
        ),
        {"bid": batch_id, "cid": chapter_id},
    )
    rev_id = dev_conn.execute(text("SELECT max(id) FROM scene_edit_revisions")).scalar()
    with pytest.raises((InternalError, ProgrammingError)):
        with dev_conn.begin_nested():
            dev_conn.execute(
                text("UPDATE scene_edit_revisions SET payload = 'tampered' WHERE id = :rid"), {"rid": rev_id}
            )
    with pytest.raises((InternalError, ProgrammingError)):
        with dev_conn.begin_nested():
            dev_conn.execute(text("DELETE FROM scene_edit_revisions WHERE id = :rid"), {"rid": rev_id})


# ── 双指针 RESTRICT 与部分唯一索引 ─────────────────────────────────────────


def test_published_pointer_restricts_run_delete(db):
    """R10/P1-1：published_run_id 复合外键 RESTRICT——被引用 run 不可物理删除。"""
    _, _, _, _, chapter_audio, run = _seed_scope(db, "restrict1")
    chapter_audio.published_run_id = run.id
    db.flush()
    with pytest.raises(IntegrityError):
        db.delete(run)
        db.flush()
    db.rollback()


def test_output_published_partial_unique(db):
    """每个 chapter_audio 至多一条 published 输出（部分唯一索引）。"""
    _, _, _, batch, chapter_audio, run = _seed_scope(db, "outpub")
    db.add(
        ChapterAudioOutput(
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=batch.id,
            chapter_id=chapter_audio.chapter_id,
            status="published",
            audio_path="a.mp3",
            duration=1.0,
            file_size=10,
        )
    )
    db.flush()
    run2 = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter_audio.chapter_id,
        chapter_audio_id=chapter_audio.id,
        run_type="full",
    )
    db.add(run2)
    db.flush()
    db.add(
        ChapterAudioOutput(
            run_id=run2.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=batch.id,
            chapter_id=chapter_audio.chapter_id,
            status="published",
            audio_path="b.mp3",
            duration=1.0,
            file_size=10,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_output_published_requires_export_fields(db):
    """published 时 audio_path/duration/file_size 必须齐全。"""
    _, _, _, batch, chapter_audio, run = _seed_scope(db, "outfields")
    db.add(
        ChapterAudioOutput(
            run_id=run.id,
            chapter_audio_id=chapter_audio.id,
            audiobook_project_id=batch.id,
            chapter_id=chapter_audio.chapter_id,
            status="published",
            audio_path="a.mp3",
            duration=None,  # 残缺 → CHECK 拒绝
            file_size=10,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_artifact_run_scene_partial_unique(db):
    """每 run 每 scene 至多一条未删除登记；软删除后允许再登记。"""
    _, _, _, batch, chapter_audio, run = _seed_scope(db, "artifact")
    base = dict(
        audiobook_project_id=batch.id,
        chapter_id=chapter_audio.chapter_id,
        chapter_audio_id=chapter_audio.id,
        run_id=run.id,
        scene_id="scene-1",
        scene_topology_hash="topo",
        content_digest="digest",
        stored_rel_path="rel/path.wav",
    )
    a1 = SceneAudioArtifact(artifact_id="art-1", **base)
    db.add(a1)
    db.flush()
    # savepoint 内验证重复登记被拒，异常回滚 savepoint 后作用域数据仍在
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(SceneAudioArtifact(artifact_id="art-2", **base))
            db.flush()
    # 软删除后可再登记
    a1.deleted_at = sa.func.now()
    db.flush()
    db.add(SceneAudioArtifact(artifact_id="art-3", **base))
    db.flush()
    db.rollback()
