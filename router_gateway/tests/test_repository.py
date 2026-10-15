# -*- coding: utf-8 -*-
"""任务/attempt/事件仓储对真实 PostgreSQL 的集成测试。"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from router_gateway.db import (
    Base,
    ClientConcurrencyLimitExceeded,
    JobRepository,
    get_engine,
    make_session_factory,
)


@pytest.fixture()
def repo():
    # 默认使用与生产库物理隔离的测试库，禁止直连 router_gateway（drop_all 会清空生产数据）
    url = os.environ.get("ROUTER_GATEWAY_TEST_DATABASE_URL",
                         "postgresql://novel_user:NovelPostgres0t649OyRUaI@127.0.0.1:5432/router_gateway_test")
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    yield JobRepository(factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _spec():
    return {"prompt": "雪山日出", "duration_seconds": 5, "resolution": "720p",
            "aspect_ratio": "16:9", "reference_images": 0, "reference_videos": 0}


def test_列出活动任务仅含pending与running且按创建序(repo):
    base = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)
    j_pending = repo.create_job("k1", None, _spec())
    repo.update_job(j_pending.id, created_at=base)
    j_running = repo.create_job("k1", None, _spec())
    repo.update_job(j_running.id, status="running", created_at=base + timedelta(seconds=10))
    j_succeeded = repo.create_job("k1", None, _spec())
    repo.update_job(j_succeeded.id, status="succeeded", content_url="https://v/x.mp4",
                    created_at=base + timedelta(seconds=20))
    j_failed = repo.create_job("k1", None, _spec())
    repo.update_job(j_failed.id, status="failed", semantic_error="deadline_exceeded",
                    created_at=base + timedelta(seconds=30))

    ids = repo.list_active_job_ids()
    assert ids == [j_pending.id, j_running.id]


def test_列出活动任务支持批量上限(repo):
    base = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
    jobs = []
    for i in range(3):
        job = repo.create_job("k1", None, _spec())
        repo.update_job(job.id, created_at=base + timedelta(seconds=i))
        jobs.append(job)
    assert repo.list_active_job_ids(limit=2) == [jobs[0].id, jobs[1].id]


def test_worker租约避免两个实例同时领取同一批任务(repo):
    jobs = [repo.create_job("k1", None, _spec()) for _ in range(2)]

    first = repo.claim_active_job_ids(limit=2, worker_id="worker-a",
                                      lease_seconds=60)
    second = repo.claim_active_job_ids(limit=2, worker_id="worker-b",
                                       lease_seconds=60)

    assert first == [jobs[0].id, jobs[1].id]
    assert second == []


def test_worker释放租约后其他实例可以领取(repo):
    job = repo.create_job("k1", None, _spec())

    assert repo.claim_active_job_ids(worker_id="worker-a", lease_seconds=60) == [job.id]
    repo.release_job_claim(job.id, worker_id="worker-a")
    assert repo.claim_active_job_ids(worker_id="worker-b", lease_seconds=60) == [job.id]


def test_deadline任务仍有活动尝试时进入对账租约(repo):
    job = repo.create_job("k1", None, _spec())
    repo.update_job(job.id, status="failed", semantic_error="deadline_exceeded")
    repo.add_attempt(job.id, 0, "r1", "erchun", "1.00", "expected_cost_min", False)
    repo.mark_attempt(1, "running", upstream_task_id="up-1")

    assert repo.claim_active_job_ids(worker_id="worker-a", lease_seconds=60) == [job.id]


def test_幂等键重复提交返回同一任务(repo):
    j1 = repo.create_job(client_key="k1", idempotency_key="abc", spec=_spec())
    j2 = repo.create_job(client_key="k1", idempotency_key="abc", spec=_spec())
    assert j1.id == j2.id


def test_attempt生命周期与状态流转(repo):
    job = repo.create_job(client_key="k1", idempotency_key=None, spec=_spec())
    a = repo.add_attempt(job_id=job.id, seq=0, route_id="xuan", provider="erchun",
                         quote_amount="2.10", reason="expected_cost_min", is_hedge=False)
    repo.mark_attempt(a.id, upstream_task_id="72193", status="submitted")
    repo.mark_attempt(a.id, status="queued")
    repo.mark_attempt(a.id, status="running")
    repo.settle_attempt(a.id, status="succeeded", billing_status="settled",
                        content_url="/v1/tasks/72193/content", cost="2.10")
    got = repo.get_attempt(a.id)
    assert got.status == "succeeded"
    assert got.queued_at is not None and got.running_at is not None
    assert got.cost == Decimal("2.10")
    assert repo.list_attempts(job.id)[0].upstream_task_id == "72193"


def test_滚动事件统计成功率与耗时分位(repo):
    for i in range(10):
        repo.record_event(route_id="r1", bucket="720p|5s", job_id=f"j{i}", attempt_id=i,
                          success=True, elapsed_seconds=100 + i, quality_pass=True)
    repo.record_event(route_id="r1", bucket="720p|5s", job_id="jbad", attempt_id=99,
                      success=False, elapsed_seconds=300, quality_pass=False)
    s = repo.rolling_stats("r1", "720p|5s", window=100)
    assert s.samples == 11
    assert round(s.success_rate, 2) == round(10 / 11, 2)
    assert 100 <= s.p50_seconds <= 110


def test_决策快照可回放(repo):
    job = repo.create_job(client_key="k1", idempotency_key=None, spec=_spec())
    repo.save_decision(job.id, {"candidates": ["xuan", "use"], "chosen": "xuan",
                                "expected_costs": {"xuan": "2.10", "use": "12"}})
    snaps = repo.list_decisions(job.id)
    assert snaps[0].data["chosen"] == "xuan"


def test_发卡后可按api_key查到启用中的client(repo):
    client = repo.create_client(name="合作方甲", api_key="rg-abc")
    got = repo.get_client_by_api_key("rg-abc")
    assert got is not None
    assert got.id == client.id and got.name == "合作方甲"
    assert got.enabled is True


def test_未知api_key查询返回None(repo):
    assert repo.get_client_by_api_key("rg-nope") is None


def test_吊销client后按key仍可查到但enabled为False且不存在id返回False(repo):
    client = repo.create_client(name="合作方甲", api_key="rg-abc")
    assert repo.disable_client(client.id) is True

    got = repo.get_client_by_api_key("rg-abc")
    assert got is not None and got.enabled is False
    assert repo.disable_client("client-not-exist") is False


def test_幂等键去重仅在同一client维度生效(repo):
    j1 = repo.create_job(client_key="c1", idempotency_key="dup", spec=_spec())
    j1_same = repo.create_job(client_key="c1", idempotency_key="dup", spec=_spec())
    j2 = repo.create_job(client_key="c2", idempotency_key="dup", spec=_spec())

    assert j1_same.id == j1.id
    assert j2.id != j1.id


def test_任务归属查询仅本client可见他人任务与不存在同样返回None(repo):
    job = repo.create_job(client_key="c1", idempotency_key=None, spec=_spec())

    assert repo.get_job_for_client(job.id, "c1") is not None
    assert repo.get_job_for_client(job.id, "c2") is None
    assert repo.get_job_for_client("missing-id", "c1") is None


def test_client_active_job_quota_rejects_new_job_but_allows_idempotent_replay(repo):
    client = repo.create_client(
        name="quota-client", api_key="rg-quota", max_active_jobs=1)

    first = repo.create_job(client.id, "idem-1", _spec())
    with pytest.raises(ClientConcurrencyLimitExceeded):
        repo.create_job(client.id, "idem-2", _spec())

    replay = repo.create_job(client.id, "idem-1", _spec())
    assert replay.id == first.id


def test_terminal_job_releases_active_job_quota(repo):
    client = repo.create_client(
        name="reuse-client", api_key="rg-reuse", max_active_jobs=1)
    first = repo.create_job(client.id, "idem-1", _spec())
    repo.update_job(first.id, status="failed", semantic_error="all_candidates_failed")

    second = repo.create_job(client.id, "idem-2", _spec())
    assert second.id != first.id


def test_terminal_job_with_active_attempt_keeps_active_job_quota(repo):
    client = repo.create_client(
        name="late-client", api_key="rg-late", max_active_jobs=1)
    first = repo.create_job(client.id, "idem-1", _spec())
    attempt = repo.add_attempt(
        job_id=first.id, seq=0, route_id="r1", provider="erchun",
        quote_amount="1.00", reason="expected_cost_min", is_hedge=False)
    repo.mark_attempt(attempt.id, status="submitted", upstream_task_id="up-1")
    repo.update_job(first.id, status="failed", semantic_error="deadline_exceeded")

    with pytest.raises(ClientConcurrencyLimitExceeded):
        repo.create_job(client.id, "idem-2", _spec())

    repo.settle_attempt(
        attempt.id, status="failed", billing_status="settled",
        content_url=None, cost="1.00")
    second = repo.create_job(client.id, "idem-2", _spec())
    assert second.id != first.id
