"""域 3+4 真实 PostgreSQL 并发合同测试。

覆盖：
- 验收 48（R10/P0-4）：两个并发事务首次创建同一章节 active ChapterAudio——
  部分唯一索引保证仅一个成功，loser 捕获 IntegrityError（SAVEPOINT 协议前提）。
- 验收 83（R17/P0，R20/P1-1）：worker 终态关账 × 人工收敛同一 ledger 并发——
  两路径锁序一致（run → ledger）无死锁，仅一方成功修改该 ledger。

SQLite 无法验证 advisory lock / 部分唯一索引 / 行锁并发，必须真实 PG。
"""

import os
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DEBUG", "false")

_env_path = ROOT_DIR / ".env"
if _env_path.exists():
    # 无条件从 .env 读取（其他测试模块可能已 setdefault 一个无效占位 URL）
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break

DATABASE_URL = os.environ.get("DATABASE_URL", "")

TEST_SCHEMA = "audiobook_d34_concurrency_test"


def _require_pg():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.fail("合同测试必须运行于真实 PostgreSQL")


from app.db.base import Base  # noqa: E402
from app.models.audiobook import (  # noqa: E402
    AudiobookProject,
    ChapterAudio,
    ChapterAudioRun,
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


# ── 验收 76（R14/P1-d）：dispatcher token fencing 双会话 ───────────────────

def test_dispatcher_late_writeback_rejected_by_token_fencing(engine, session_factory):
    """双 dispatcher：A 认领后 B 接管，A 迟到补偿被 token CAS 拒绝。

    验收 76：A 迟到返回"明确失败"→ A 的补偿（取消/释放冻结/desired 回退）
    被 token CAS 拒绝（rowcount=0），B 的 claim 与投递结果保持
    （run 不被取消、desired_run_id 不变）。
    """
    seed_db = session_factory()
    _, project, chapter, batch = _seed_scope(seed_db, "fencing")
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="queued",
        dispatch_status="pending",
        dispatch_attempts=0,
    )
    seed_db.add(run)
    seed_db.commit()
    run_id = run.id
    seed_db.close()

    from app.services.audiobook.dispatch_service import (
        _compensate_failed_dispatch,
        acquire_worker_lease,  # noqa: F401（仅验证 run 操作链路）
        claim_and_dispatch_stale_pending,
        clear_worker_lease,  # noqa: F401
    )

    # 会话 A：dispatcher A 认领（token A）
    db_a = session_factory()
    try:
        from app.utils.datetime_utils import utc_now as _utc_now
        from datetime import timedelta as _td
        import secrets as _secrets

        token_a = _secrets.token_urlsafe(24)
        claimed = (
            db_a.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == run_id)
            .update(
                {
                    ChapterAudioRun.dispatch_claim_token: token_a,
                    ChapterAudioRun.dispatch_claimed_at: _utc_now(),
                    ChapterAudioRun.dispatch_attempts: 1,
                },
                synchronize_session=False,
            )
        )
        assert claimed == 1
        db_a.commit()
    finally:
        db_a.close()

    # 会话 B：接管（清 A 的 claim，B 重新认领并成功投递 → dispatched）
    db_b = session_factory()
    try:
        from app.utils.datetime_utils import utc_now as _utc_now2

        token_b = "token-b"
        taken = (
            db_b.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == run_id)
            .update(
                {
                    ChapterAudioRun.dispatch_claim_token: token_b,
                    ChapterAudioRun.dispatch_claimed_at: _utc_now2(),
                    ChapterAudioRun.dispatch_status: "dispatched",
                    ChapterAudioRun.dispatched_at: _utc_now2(),
                },
                synchronize_session=False,
            )
        )
        assert taken == 1
        db_b.commit()
    finally:
        db_b.close()

    # 会话 A 迟到返回"明确失败"：补偿必须被 token CAS 拒绝
    db_a_late = session_factory()
    try:
        run_view = (
            db_a_late.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == run_id)
            .first()
        )
        # 模拟 A 用旧 token 执行补偿（dispatch_claim_token=token_a 已不匹配）
        compensated = _compensate_failed_dispatch(
            db_a_late, run_view, claim_token=token_a,
        )
        assert compensated is False, "迟到补偿必须被 token CAS 拒绝"
        db_a_late.commit()
    finally:
        db_a_late.close()

    # 验证：B 的 claim 与投递结果保持（run 未被取消、desired 不变）
    check_db = session_factory()
    try:
        final_run = (
            check_db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == run_id)
            .first()
        )
        assert final_run.dispatch_status == "dispatched", (
            f"B 的投递结果被破坏: {final_run.dispatch_status}"
        )
        assert final_run.dispatch_claim_token == token_b, (
            "B 的 claim 被 A 迟到补偿覆盖"
        )
        assert final_run.status != "cancelled", "run 不得被迟到 dispatcher 取消"
    finally:
        check_db.close()


# ── 验收 52（R10/P1-3）：ledger 崩溃窗口（供应商成功、本地未落账）─────────

def test_ledger_crash_window_recovery_no_duplicate(engine, session_factory):
    """模拟"供应商成功返回、进程在本地落账前崩溃"→ 恢复按 attempt_key 补录。

    验收 52：调用前 pending 已写（崩溃后仍在）→ 恢复重放 record_pending_call
    命中唯一约束幂等（不重复写）→ transition_to_succeeded 补录成功，
    无重复入账、无丢失用量（同 attempt_key 仅一条 succeeded）。
    """
    from app.services.audiobook.ledger_transition_service import (
        record_pending_call,
        transition_to_succeeded,
    )

    seed_db = session_factory()
    _, project, chapter, batch = _seed_scope(seed_db, "crashwin")
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="running",
        billing_account_user_id=project.user_id,
    )
    seed_db.add(run)
    seed_db.commit()
    run_id = run.id
    seed_db.close()

    # 第一步：供应商调用前写 pending（quantity 未知）——进程随后崩溃
    db = session_factory()
    try:
        ledger = record_pending_call(
            db,
            run_id=run_id,
            attempt_key="att:1",
            provider="dashscope_seed",
            usage_kind="seed_render",
            unit="second",
            idempotency_key_sent=True,
            capability_snapshot_json={"accepts_idempotency_key": True},
        )
        ledger_id = ledger.id
        db.commit()
    finally:
        db.close()

    # 第二步（恢复）：pending 仍在 → 按 attempt_key 重放（幂等，不重复写）
    db2 = session_factory()
    try:
        same_ledger = record_pending_call(
            db2,
            run_id=run_id,
            attempt_key="att:1",
            provider="dashscope_seed",
            usage_kind="seed_render",
            unit="second",
        )
        assert same_ledger.id == ledger_id, "同 attempt_key 必须返回原记录（幂等）"
        assert same_ledger.status == "pending"

        # 供应商确认成功 → 补录 succeeded（用量不丢失）
        result = transition_to_succeeded(
            db2,
            ledger_id=ledger_id,
            quantity=30.5,
            pricing_key="seed_scene",
            billing_snapshot_id="bs-1",
            provider_request_id="req-77",
        )
        assert result["ok"] is True
        db2.commit()
    finally:
        db2.close()

    # 第三步：无重复入账（同 attempt_key 仅一条 succeeded）
    check_db = session_factory()
    try:
        rows = (
            check_db.query(BillingUsageLedger)
            .filter(BillingUsageLedger.run_id == run_id)
            .all()
        )
        assert len(rows) == 1, f"应恰好一条 ledger，实际 {len(rows)}"
        assert rows[0].status == "succeeded"
        assert float(rows[0].quantity) == 30.5
        assert rows[0].provider_request_id == "req-77"
        assert rows[0].commit_stage == "post_call"
    finally:
        check_db.close()


def _seed_scope(db, tag: str):
    """创建 user/project/chapter/batch 作用域链（不含 chapter_audio/run）。"""
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
    return user, project, chapter, batch


# ── 验收 48（R10/P0-4）：唯一 active 并发创建 ────────────────────────────────

def test_concurrent_first_creation_unique_active(engine, session_factory):
    """两个并发事务首次创建同一章节 active ChapterAudio——仅一个成功。

    部分唯一索引 ``UNIQUE (audiobook_project_id, chapter_id) WHERE deleted_at IS NULL``
    是唯一保证；loser 必须捕获 IntegrityError（SAVEPOINT 协议前提，
    不得抛 InFailedSqlTransaction）。
    """
    # 前置：部分唯一索引必须存在（R10/P0-4 合同前提）
    with engine.connect() as conn:
        idx_rows = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = :schema AND indexname = 'uq_chapter_audio_active_unique'"
            ),
            {"schema": TEST_SCHEMA},
        ).fetchall()
        assert len(idx_rows) == 1, f"部分唯一索引缺失: {idx_rows}"
        assert "deleted_at IS NULL" in idx_rows[0][1], idx_rows[0][1]

    seed_db = session_factory()
    _, _, chapter, batch = _seed_scope(seed_db, "uniqactive")
    seed_db.commit()
    batch_id, chapter_id = batch.id, chapter.id
    seed_db.close()

    results: dict = {"winner": None, "loser_error": None}
    barrier = threading.Barrier(2)

    def _try_insert(name: str):
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            audio = ChapterAudio(audiobook_project_id=batch_id, chapter_id=chapter_id)
            db.add(audio)
            db.flush()
            db.commit()
            results["winner"] = name
        except IntegrityError as exc:
            db.rollback()
            results["loser_error"] = exc
        except Exception as exc:  # noqa: BLE001
            results["loser_error"] = exc
        finally:
            db.close()

    t1 = threading.Thread(target=_try_insert, args=("A",))
    t2 = threading.Thread(target=_try_insert, args=("B",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert results["winner"] in {"A", "B"}, f"应有且仅有一个成功，结果={results}"
    assert results["loser_error"] is not None, "loser 必须收到 IntegrityError"
    assert isinstance(results["loser_error"], IntegrityError)

    # 数据库最终只有一条 active
    check_db = session_factory()
    try:
        count = (
            check_db.query(ChapterAudio)
            .filter(
                ChapterAudio.audiobook_project_id == batch_id,
                ChapterAudio.chapter_id == chapter_id,
                ChapterAudio.deleted_at.is_(None),
            )
            .count()
        )
        assert count == 1, f"active 记录数应为 1，实际 {count}"
    finally:
        check_db.close()


# ── 验收 83（R17/P0，R20/P1-1）：worker 终态关账 × 人工收敛同一 ledger ──────

def test_worker_close_accounting_vs_manual_reconcile_no_deadlock(engine, session_factory):
    """worker 终态关账 × 人工收敛同一 ledger 并发交错——无死锁且仅一方生效。

    锁序（R20/P1-1）：
    - worker 关账路径：UPDATE run（终态）→ UPDATE ledger（WHERE status='pending'）
    - 人工收敛路径：pg_advisory_xact_lock(账户) → SELECT run FOR UPDATE
      → UPDATE ledger（WHERE status='manual_reconciliation' CAS）
    两路径加锁顺序一致（run → ledger），并发交错不构成锁环。
    """
    seed_db = session_factory()
    _, project, chapter, batch = _seed_scope(seed_db, "closexreconcile")
    run = ChapterAudioRun(
        audiobook_project_id=batch.id,
        chapter_id=chapter.id,
        run_type="full",
        status="completed",
        billing_account_user_id=project.user_id,
    )
    seed_db.add(run)
    seed_db.flush()
    ledger = BillingUsageLedger(
        run_id=run.id,
        status="pending",
        attempt_key="att-1",
        provider="dashscope_seed",
        usage_kind="seed_render",
        unit="second",
        commit_stage="pre_call",
        idempotency_key_sent=False,
    )
    seed_db.add(ledger)
    seed_db.commit()
    run_id, ledger_id, account_user_id = run.id, ledger.id, project.user_id
    seed_db.close()

    # 先由人工收敛入口将 ledger 置 manual_reconciliation（并发竞争对象）
    prep_db = session_factory()
    try:
        prep_db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int(account_user_id)},
        )
        locked_run = (
            prep_db.query(ChapterAudioRun)
            .filter(ChapterAudioRun.id == run_id)
            .with_for_update()
            .first()
        )
        assert locked_run is not None
        prep_db.query(BillingUsageLedger).filter(BillingUsageLedger.id == ledger_id).update(
            {BillingUsageLedger.status: "manual_reconciliation"},
            synchronize_session=False,
        )
        prep_db.commit()
    finally:
        prep_db.close()

    results: dict = {"worker_updated": None, "reconcile_updated": None, "error": None}
    start = threading.Barrier(2)

    def _worker_close_accounting():
        """模拟 worker 终态路径：UPDATE run 终态 → 关账（只碰 pending）。"""
        db = session_factory()
        try:
            start.wait(timeout=10)
            db.query(ChapterAudioRun).filter(ChapterAudioRun.id == run_id).update(
                {ChapterAudioRun.status: "completed", ChapterAudioRun.finished_at: sa.func.now()},
                synchronize_session=False,
            )
            updated = (
                db.query(BillingUsageLedger)
                .filter(
                    BillingUsageLedger.id == ledger_id,
                    BillingUsageLedger.status == "pending",
                )
                .update(
                    {BillingUsageLedger.status: "confirmed_failed"},
                    synchronize_session=False,
                )
            )
            db.commit()
            results["worker_updated"] = updated
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results["error"] = exc
        finally:
            db.close()

    def _manual_reconcile():
        """模拟人工收敛路径：账户锁 → run 锁 → ledger CAS（只碰 manual）。"""
        db = session_factory()
        try:
            start.wait(timeout=10)
            db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": int(account_user_id)},
            )
            locked_run = (
                db.query(ChapterAudioRun)
                .filter(ChapterAudioRun.id == run_id)
                .with_for_update()
                .first()
            )
            assert locked_run is not None
            updated = (
                db.query(BillingUsageLedger)
                .filter(
                    BillingUsageLedger.id == ledger_id,
                    BillingUsageLedger.status == "manual_reconciliation",
                )
                .update(
                    {
                        BillingUsageLedger.status: "succeeded",
                        BillingUsageLedger.quantity: Decimal("12.5"),
                        BillingUsageLedger.pricing_key: "seed_scene",
                        BillingUsageLedger.billing_snapshot_id: "bs-1",
                        BillingUsageLedger.commit_stage: "post_call",
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            results["reconcile_updated"] = updated
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            results["error"] = exc
        finally:
            db.close()

    t_worker = threading.Thread(target=_worker_close_accounting)
    t_reconcile = threading.Thread(target=_manual_reconcile)
    t_worker.start()
    t_reconcile.start()
    t_worker.join(timeout=30)
    t_reconcile.join(timeout=30)

    # 无死锁（两线程均完成）
    assert not t_worker.is_alive() and not t_reconcile.is_alive(), "并发路径死锁"
    assert results["error"] is None, f"并发异常: {results['error']}"

    # 仅一方成功修改（worker 只碰 pending、收敛只碰 manual，互斥）
    assert results["worker_updated"] == 0, "worker 不得改动 manual_reconciliation 行"
    assert results["reconcile_updated"] == 1, "人工收敛应成功转态"

    # 最终状态 = succeeded（人工收敛生效）
    check_db = session_factory()
    try:
        final_status = (
            check_db.query(BillingUsageLedger.status)
            .filter(BillingUsageLedger.id == ledger_id)
            .scalar()
        )
        assert final_status == "succeeded", f"最终状态应为 succeeded，实际 {final_status}"
    finally:
        check_db.close()
