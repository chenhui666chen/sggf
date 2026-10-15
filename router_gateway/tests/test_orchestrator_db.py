# -*- coding: utf-8 -*-
"""编排器 × 真实 PostgreSQL 仓储契约测试：防内存假仓储与 SQLAlchemy 行为漂移。"""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from router_gateway.adapters.base import NormalizedResult
from router_gateway.adapters.erchun import ErchunError
from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
)
from router_gateway.db import Base, JobRepository, get_engine, make_session_factory
from router_gateway.orchestrator.service import Orchestrator
from router_gateway.stats import RouteStats


T0 = datetime(2026, 10, 12, 0, 0, 0, tzinfo=timezone.utc)


class ScriptedAdapter:
    def __init__(self, provider, submits=None, polls=None, idempotent=True):
        self.provider = provider
        self.supports_idempotent_submit = idempotent
        self._submits = list(submits or [])
        self._polls = {k: list(v) for k, v in (polls or {}).items()}
        self.submit_calls = []

    def submit(self, req):
        self.submit_calls.append(req)
        item = self._submits.pop(0)
        if isinstance(item, Exception):
            raise item
        task_id, phase = item
        return SimpleNamespace(upstream_task_id=task_id, phase=phase, raw={})

    def poll(self, task_id):
        item = self._polls[task_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


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


def _cap():
    return RouteCapability(
        billing="per_second",
        duration=DurationRange(1, 30),
        resolutions=("720p",), aspect_ratios=("16:9",),
        input_modes=frozenset({Mode.TEXT}))


def _routes():
    return [
        Route(route_id="r-erchun", provider="erchun", upstream_model="wf-1",
              quality_group="h3", capability=_cap(), pricing={"720p": "0.07"}),
        Route(route_id="r-suanliai", provider="suanliai", upstream_model="wf-2",
              quality_group="h3", capability=_cap(), pricing={"720p": "0.40"}),
    ]


def _spec(**over):
    base = dict(prompt="雪山日出", duration_seconds=5, resolution="720p",
                aspect_ratio="16:9", reference_images=[], reference_videos=[],
                allow_switch=True, allow_hedge=False, deadline_seconds=None)
    base.update(over)
    return base


class Reject(Exception):
    def __init__(self):
        super().__init__("insufficient_balance")
        self.retriable = False
        self.status = 402


def test_提交拒绝后真实故障切换并轮询成功(repo):
    a1 = ScriptedAdapter("erchun", submits=[Reject()])
    a2 = ScriptedAdapter("suanliai",
                         submits=[("T2", "queued")],
                         polls={"T2": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/t2.mp4")]})
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=lambda: T0)

    view = orch.submit_job("k1", None, _spec())
    assert view.status == "running" and view.attempts[-1].route_id == "r-suanliai"

    out = orch.poll_job(view.id)
    assert out.status == "succeeded"
    assert out.content_url == "https://v/t2.mp4"
    # 真实滚动统计：r-erchun 一次确认失败已入窗，r-suanliai 一次成功
    assert repo.rolling_stats("r-erchun", "text|720p|5s").samples == 1
    assert repo.rolling_stats("r-suanliai", "text|720p|5s").success_rate == 1.0
    # 失败尝试有真实 ended_at 与结构化错误
    failed = out.attempts[0]
    assert failed.status == "failed" and failed.error["type"] == "submit_rejected"


def test_真实仓储审核挂起任务仍被worker活动清单捕获且可收尾(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [
                             NormalizedResult(phase="review"),
                             NormalizedResult(phase="review"),
                             NormalizedResult(phase="succeeded",
                                              billing_status="settled",
                                              content_url="https://v/t1.mp4")]})
    a2 = ScriptedAdapter("suanliai")
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=lambda: T0)

    view = orch.submit_job("k1", None, _spec())
    orch.poll_job(view.id)  # review
    assert repo.get_attempt(1).status == "review"
    # job 保持 running：worker 每轮活动清单仍会拉到并继续对账，不丢任务
    assert repo.list_active_job_ids() == [view.id]
    orch.poll_job(view.id)  # review 持续，无第二条尝试
    assert [a.route_id for a in repo.list_attempts(view.id)] == ["r-erchun"]
    out = orch.poll_job(view.id)  # succeeded
    assert out.status == "succeeded"
    assert out.content_url == "https://v/t1.mp4"
    assert repo.list_active_job_ids() == []


def test_真实仓储幂等重放只产生一次上游提交(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")])
    a2 = ScriptedAdapter("suanliai")
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=lambda: T0)
    v1 = orch.submit_job("k1", "idem-x", _spec())
    v2 = orch.submit_job("k1", "idem-x", _spec())
    assert v1.id == v2.id and len(a1.submit_calls) == 1


def test_真实仓储慢任务跨供应商对冲(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "running")],
                         polls={"T1": [NormalizedResult(phase="running")]})
    a2 = ScriptedAdapter("suanliai", submits=[("H1", "queued")],
                         polls={"H1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/h1.mp4")]})
    now = T0

    def clock():
        return now

    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=clock, fallback_hedge_seconds=300)
    # 预置 r-erchun 100 个成功样本制造 P95=200
    for i in range(100):
        repo.record_event(route_id="r-erchun", bucket="text|720p|5s", job_id=f"seed{i}",
                          attempt_id=10000 + i, success=True, elapsed_seconds=200)

    view = orch.submit_job("k1", None, _spec(allow_hedge=True))
    now = T0 + timedelta(seconds=201)
    tick1 = orch.poll_job(view.id)
    assert [a.route_id for a in tick1.attempts] == ["r-erchun", "r-suanliai"]
    assert tick1.attempts[1].is_hedge is True

    now = T0 + timedelta(seconds=210)
    a1._polls["T1"] = [NormalizedResult(phase="running")]
    tick2 = orch.poll_job(view.id)
    assert tick2.status == "succeeded"
    assert tick2.content_url == "https://v/h1.mp4"


class ScriptedDeliverer:
    """交付转存脚本：每个 outcome 为返回 URL 字符串或抛出的异常。"""

    def __init__(self, outcomes):
        self.calls = []
        self._outcomes = list(outcomes)

    def deliver(self, job_id, created_at, source_url):
        self.calls.append({"job_id": job_id, "source": source_url})
        item = self._outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_成片转存成功后任务才置succeeded且attempt保留上游地址(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/t1.mp4")]})
    deliverer = ScriptedDeliverer([
        "https://sggf-router-video.oss-cn-shanghai.aliyuncs.com/"
        "router_gateway/videos/2026/10/job.mp4"])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1}, clock=lambda: T0,
                        deliverer=deliverer)

    view = orch.submit_job("k1", None, _spec())
    out = orch.poll_job(view.id)

    assert out.status == "succeeded"
    assert out.content_url.endswith("router_gateway/videos/2026/10/job.mp4")
    # 尝试保留供应商原始地址，仅任务级 content_url 被自有地址覆盖
    assert out.attempts[0].content_url == "https://v/t1.mp4"
    assert deliverer.calls == [{"job_id": view.id, "source": "https://v/t1.mp4"}]
    assert repo.list_active_job_ids() == []


def test_任务终态后再次poll幂等不重复转存(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/t1.mp4")]})
    oss_url = "https://sggf-router-video.oss-cn-shanghai.aliyuncs.com/k.mp4"
    deliverer = ScriptedDeliverer([oss_url])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1}, clock=lambda: T0,
                        deliverer=deliverer)

    view = orch.submit_job("k1", None, _spec())
    orch.poll_job(view.id)
    orch.poll_job(view.id)  # 终态任务：不再查上游、不再转存

    assert len(deliverer.calls) == 1
    assert a1._polls["T1"] == []  # 上游仅对账一次


def test_转存失败任务保持running由后续tick补偿且不重查上游(repo):
    from router_gateway.assets.delivery import DeliveryError

    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/t1.mp4")]})
    deliverer = ScriptedDeliverer([
        DeliveryError("download boom"),
        DeliveryError("put boom"),
        "https://sggf-router-video.oss-cn-shanghai.aliyuncs.com/k.mp4"])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1}, clock=lambda: T0,
                        deliverer=deliverer)

    view = orch.submit_job("k1", None, _spec())

    tick1 = orch.poll_job(view.id)
    assert tick1.status == "running" and tick1.content_url is None
    assert tick1.attempts[0].status == "succeeded"
    assert tick1.attempts[0].content_url == "https://v/t1.mp4"
    assert repo.list_active_job_ids() == [view.id]

    tick2 = orch.poll_job(view.id)
    assert tick2.status == "running" and tick2.content_url is None
    assert repo.list_active_job_ids() == [view.id]

    tick3 = orch.poll_job(view.id)
    assert tick3.status == "succeeded"
    assert tick3.content_url.endswith("/k.mp4")
    assert [c["source"] for c in deliverer.calls] == ["https://v/t1.mp4"] * 3
    assert a1._polls["T1"] == []  # 补偿阶段不重复查询上游
    assert repo.list_active_job_ids() == []


def test_对冲双成功时仅转存seq最小的成片且全流程幂等(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "running")],
                         polls={"T1": [
                             NormalizedResult(phase="running"),
                             NormalizedResult(phase="succeeded",
                                              billing_status="settled",
                                              content_url="https://v/t1.mp4")]})
    a2 = ScriptedAdapter("suanliai", submits=[("H1", "queued")],
                         polls={"H1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/h1.mp4")]})
    now = T0
    deliverer = ScriptedDeliverer(["https://own/t1.mp4"])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=lambda: now, fallback_hedge_seconds=300,
                        deliverer=deliverer)
    for i in range(100):
        repo.record_event(route_id="r-erchun", bucket="text|720p|5s", job_id=f"s{i}",
                          attempt_id=20000 + i, success=True, elapsed_seconds=200)

    view = orch.submit_job("k1", None, _spec(allow_hedge=True))
    now = T0 + timedelta(seconds=201)
    tick1 = orch.poll_job(view.id)  # T1 仍慢：启动对冲 H1
    assert [a.route_id for a in tick1.attempts] == ["r-erchun", "r-suanliai"]
    now = T0 + timedelta(seconds=210)
    out = orch.poll_job(view.id)  # 两路同轮成功，仅 seq 最小者 T1 成为交付源

    assert out.status == "succeeded"
    assert out.content_url == "https://own/t1.mp4"
    assert deliverer.calls == [{"job_id": view.id, "source": "https://v/t1.mp4"}]


def test_转存补偿跨过deadline不被误判deadline_exceeded(repo):
    from router_gateway.assets.delivery import DeliveryError

    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [NormalizedResult(
                             phase="succeeded", billing_status="settled",
                             content_url="https://v/t1.mp4")]})
    now = T0
    deliverer = ScriptedDeliverer([
        DeliveryError("boom"), "https://own/t1.mp4"])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1}, clock=lambda: now,
                        deliverer=deliverer)

    view = orch.submit_job("k1", None, _spec(deadline_seconds=600))
    now = T0 + timedelta(seconds=900)  # 已超过出片截止时间
    orch.poll_job(view.id)  # 成片已在上游成功：转存失败但不能判 deadline_exceeded
    assert repo.get_job(view.id).semantic_error is None
    out = orch.poll_job(view.id)
    assert out.status == "succeeded" and out.content_url == "https://own/t1.mp4"


def test_submit窗口期created占位被worker视为占用不重复下单(repo):
    # 复现 W4 E2E 竞态：add_attempt 后、首次 submit 网络返回前 status=created，
    # worker tick 不得把该路线当失败而向第二家供应商下单
    from router_gateway.db import _now

    a1 = ScriptedAdapter("erchun", submits=[])  # 占位由创建者负责，不应再被调用
    a2 = ScriptedAdapter("suanliai", submits=[("T2", "queued")])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=_now)
    job = repo.create_job("k1", None, _spec(mode="text"))
    repo.add_attempt(job_id=job.id, seq=0, route_id="r-erchun",
                     provider="erchun", quote_amount="0.07",
                     reason="expected_cost_min", is_hedge=False)

    out = orch.poll_job(job.id)

    assert [a.seq for a in repo.list_attempts(job.id)] == [0]
    assert repo.get_attempt(1).status == "created"
    assert a1.submit_calls == [] and a2.submit_calls == []
    assert out.status == "running"


def test_deadline后上游成功仍保持失败语义但继续归档(repo):
    a1 = ScriptedAdapter(
        "erchun",
        submits=[("T-late", "queued")],
        polls={"T-late": [
            NormalizedResult(phase="running"),
            NormalizedResult(phase="succeeded", billing_status="settled",
                             content_url="https://v/late.mp4"),
        ]})
    deliverer = ScriptedDeliverer([
        "https://oss.example.com/router_gateway/videos/late.mp4"])
    now = T0

    def clock():
        return now

    orch = Orchestrator(repo=repo, routes=_routes(), adapters={"erchun": a1},
                        clock=clock, deliverer=deliverer)
    view = orch.submit_job("k1", None, _spec(deadline_seconds=10))
    repo.update_job(view.id, created_at=T0)

    now = T0 + timedelta(seconds=11)
    timed_out = orch.poll_job(view.id)
    assert timed_out.status == "failed"
    assert timed_out.semantic_error == "deadline_exceeded"

    now = T0 + timedelta(seconds=12)
    late = orch.poll_job(view.id)
    assert late.status == "failed"
    assert late.semantic_error == "deadline_exceeded"
    assert late.content_url is None
    assert late.attempts[0].status == "succeeded"
    assert deliverer.calls == [{"job_id": view.id,
                                "source": "https://v/late.mp4"}]


def test_超宽限期的created僵死占位记unknown并故障切换(repo):
    from router_gateway.db import _now

    dispatch_at = _now()
    a1 = ScriptedAdapter("erchun", submits=[])
    a2 = ScriptedAdapter("suanliai", submits=[("T2", "queued")])
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=lambda: dispatch_at + timedelta(seconds=120),
                        dispatch_grace_seconds=90)
    job = repo.create_job("k1", None, _spec(mode="text"))
    repo.add_attempt(job_id=job.id, seq=0, route_id="r-erchun",
                     provider="erchun", quote_amount="0.07",
                     reason="expected_cost_min", is_hedge=False)

    out = orch.poll_job(job.id)

    attempts = repo.list_attempts(job.id)
    assert attempts[0].status == "unknown"
    assert attempts[0].error["type"] == "submit_dispatch_stale"
    assert attempts[1].route_id == "r-suanliai"
    assert attempts[1].reason == "failover_after_unknown"
    assert a1.submit_calls == [] and len(a2.submit_calls) == 1
    assert out.status == "running"


def test_轮询遇供应商429限频错误时保持占用下轮可成功不炸对账(repo):
    a1 = ScriptedAdapter("erchun", submits=[("T1", "queued")],
                         polls={"T1": [
                             ErchunError("任务查询过于频繁，请按 Retry-After 稍后重试。",
                                         retriable=True, status=429),
                             NormalizedResult(phase="succeeded",
                                              billing_status="settled",
                                              content_url="https://v/t1.mp4")]})
    orch = Orchestrator(repo=repo, routes=_routes(),
                        adapters={"erchun": a1}, clock=lambda: T0)

    view = orch.submit_job("k1", None, _spec())
    tick1 = orch.poll_job(view.id)  # 429：本 tick 静默保留，不抛异常
    assert tick1.status == "running"
    assert repo.get_attempt(1).status == "queued"

    tick2 = orch.poll_job(view.id)  # 供应商恢复：正常对账成功
    assert tick2.status == "succeeded"
    assert tick2.content_url == "https://v/t1.mp4"
