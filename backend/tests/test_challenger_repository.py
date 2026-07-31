"""
挑战者池持久化测试（设计文档 §3.1 / §3.2 ⑦ / §6.1 / §14 第 4 步）

覆盖：
- FailedVariantStore —— 失败变体记录落盘（gate ⑦ 的 _failed_variants 从内存态转持久态）
- ChallengerRepository.upsert_challenger —— 挑战者入 prompt_challengers 表，幂等 on challenger_id
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.models.prompt_experiment import PromptChallenger
from app.services.prompt_evolution.challenger_repository import (
    ChallengerRepository,
    FailedVariantStore,
)


# ============ FailedVariantStore（gate ⑦ 落盘） ============

@pytest.fixture()
def store(tmp_path):
    return FailedVariantStore(storage_dir=str(tmp_path))


def test_failed_variant_default_count_zero(store):
    assert store.get_fail_count("sha256:aaaa1111") == 0


def test_failed_variant_record_increments(store):
    assert store.record_failure("sha256:aaaa1111") == 1
    assert store.record_failure("sha256:aaaa1111") == 2
    assert store.get_fail_count("sha256:aaaa1111") == 2


def test_failed_variant_blocked_at_threshold(store):
    for _ in range(3):
        store.record_failure("sha256:bbbb2222")
    assert store.is_blocked("sha256:bbbb2222") is True
    assert "sha256:bbbb2222" in store.get_blocked_hashes()


def test_failed_variant_not_blocked_below_threshold(store):
    store.record_failure("sha256:cccc3333")
    store.record_failure("sha256:cccc3333")
    assert store.is_blocked("sha256:cccc3333") is False
    assert "sha256:cccc3333" not in store.get_blocked_hashes()


def test_failed_variant_persisted_across_instances(tmp_path):
    s1 = FailedVariantStore(storage_dir=str(tmp_path))
    s1.record_failure("sha256:dddd4444")
    s1.record_failure("sha256:dddd4444")
    s1.record_failure("sha256:dddd4444")
    # 新实例从磁盘重建
    s2 = FailedVariantStore(storage_dir=str(tmp_path))
    assert s2.get_fail_count("sha256:dddd4444") == 3
    assert s2.is_blocked("sha256:dddd4444") is True


def test_failed_variant_custom_threshold(tmp_path):
    s = FailedVariantStore(storage_dir=str(tmp_path), block_threshold=2)
    s.record_failure("sha256:eeee5555")
    assert s.is_blocked("sha256:eeee5555") is False
    s.record_failure("sha256:eeee5555")
    assert s.is_blocked("sha256:eeee5555") is True


# ============ ChallengerRepository（入库幂等） ============

@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    PromptChallenger.__table__.create(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _challenger_kwargs(**overrides):
    data = dict(
        challenger_id="chg_玄幻_20260730_a1b2",
        genre="玄幻",
        prompt_text="改善句式结构，保留题材语域",
        prompt_hash="sha256:a1b2c3d4e5f6a7b8",
        strategy_desc="降低连续同构句比例，调整句式长短",
        strategy_family="sentence_structure",
        source_batch="batch_20260730_01",
        offline_gate_passed=True,
        offline_scores={"semantic_fidelity": 88.0},
    )
    data.update(overrides)
    return data


def test_upsert_challenger_inserts_row(session):
    repo = ChallengerRepository(session)
    row = repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    assert row.id is not None
    assert row.challenger_id == "chg_玄幻_20260730_a1b2"
    assert row.strategy_family == "sentence_structure"
    assert row.serving_mode == "shadow"
    assert session.query(PromptChallenger).count() == 1


def test_upsert_challenger_idempotent_on_challenger_id(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    # 相同 challenger_id 再次写入不应产生第二行
    row2 = repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    assert session.query(PromptChallenger).count() == 1
    assert row2.challenger_id == "chg_玄幻_20260730_a1b2"


def test_upsert_challenger_distinct_ids_create_rows(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs())
    repo.upsert_challenger(
        **_challenger_kwargs(
            challenger_id="chg_玄幻_20260730_c3d4",
            prompt_hash="sha256:cccc3333dddd4444",
        )
    )
    session.commit()
    assert session.query(PromptChallenger).count() == 2


def test_get_by_challenger_id(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    found = repo.get_by_challenger_id("chg_玄幻_20260730_a1b2")
    assert found is not None
    assert found.prompt_hash == "sha256:a1b2c3d4e5f6a7b8"
    assert repo.get_by_challenger_id("chg_不存在_0_0000") is None


# ============ list_serving（shadow 分流取池，§5.1） ============

def test_list_serving_filters_genre_mode_and_gate(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs())
    # 未过离线门槛 → 不参与分流
    repo.upsert_challenger(
        **_challenger_kwargs(
            challenger_id="chg_玄幻_20260730_e5f6",
            prompt_hash="sha256:eeee5555ffff6666",
            offline_gate_passed=False,
        )
    )
    # 其它题材 → 不参与
    repo.upsert_challenger(
        **_challenger_kwargs(
            challenger_id="chg_都市_20260730_b2c3",
            genre="都市",
            prompt_hash="sha256:bbbb2222cccc3333",
        )
    )
    session.commit()
    rows = repo.list_serving("玄幻", serving_mode="shadow")
    assert [r.challenger_id for r in rows] == ["chg_玄幻_20260730_a1b2"]


def test_list_serving_deterministic_order(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(
        **_challenger_kwargs(
            challenger_id="chg_玄幻_20260730_zzzz",
            prompt_hash="sha256:zzzz9999",
        )
    )
    repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    # 按 challenger_id 排序，确定性索引选择（select_challenger_index）依赖稳定顺序
    rows = repo.list_serving("玄幻", serving_mode="shadow")
    assert [r.challenger_id for r in rows] == [
        "chg_玄幻_20260730_a1b2",
        "chg_玄幻_20260730_zzzz",
    ]


# ============ transition_serving_mode（条件更新，六轮评审①防并发竞态） ============

def test_transition_serving_mode_wins_only_once(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs(serving_mode="eligible"))
    session.commit()
    # 首次条件转换：WHERE serving_mode='eligible' 命中 → True
    assert (
        repo.transition_serving_mode("chg_玄幻_20260730_a1b2", "eligible", "returnable")
        is True
    )
    session.commit()
    row = repo.get_by_challenger_id("chg_玄幻_20260730_a1b2")
    assert row.serving_mode == "returnable"
    assert row.state_changed_at is not None
    # 第二次同条件转换：状态已不是 eligible → False，不重复变更（并发输者语义）
    assert (
        repo.transition_serving_mode("chg_玄幻_20260730_a1b2", "eligible", "returnable")
        is False
    )


def test_transition_serving_mode_missing_returns_false(session):
    repo = ChallengerRepository(session)
    assert (
        repo.transition_serving_mode("chg_不存在_0_0000", "eligible", "returnable")
        is False
    )


def test_transition_serving_mode_rejects_illegal_transition(session):
    repo = ChallengerRepository(session)
    repo.upsert_challenger(**_challenger_kwargs())
    session.commit()
    # 状态机校验仍然生效（shadow → returnable 非法，须经 eligible）
    with pytest.raises(ValueError):
        repo.transition_serving_mode("chg_玄幻_20260730_a1b2", "shadow", "returnable")
