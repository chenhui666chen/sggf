# -*- coding: utf-8 -*-
"""编排服务测试：内存假仓储 + 脚本化假适配器，不依赖 PostgreSQL 与网络。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from router_gateway.adapters.base import NormalizedResult, RetriableTransportError, SubmitRequest
from router_gateway.catalog import (
    DurationRange,
    Mode,
    Route,
    RouteCapability,
)
from router_gateway.catalog.intent import IntentError, ModeDecision
from router_gateway.orchestrator.service import (
    ContentRiskDecision,
    Orchestrator,
    OrchestratorError,
)
from router_gateway.stats import RouteStats


T0 = datetime(2026, 10, 12, 0, 0, 0, tzinfo=timezone.utc)


class AdapterError(Exception):
    def __init__(self, message, retriable=False, status=400):
        super().__init__(message)
        self.retriable = retriable
        self.status = status


class FakeAdapter:
    def __init__(self, provider, idempotent=False, submit_script=None, poll_script=None):
        self.provider = provider
        self.supports_idempotent_submit = idempotent
        # submit_script: list，每次 submit 弹出一项：("ok", task_id, phase) 或异常
        self.submit_script = list(submit_script or [])
        # poll_script: task_id -> list[NormalizedResult]，每次 poll 弹出
        self.poll_script = {k: list(v) for k, v in (poll_script or {}).items()}
        self.submit_calls = []

    def submit(self, req: SubmitRequest):
        self.submit_calls.append(req)
        item = self.submit_script.pop(0)
        if isinstance(item, Exception):
            raise item
        _, task_id, phase = item
        return SimpleNamespace(upstream_task_id=task_id, phase=phase, raw={})

    def poll(self, upstream_task_id):
        item = self.poll_script[upstream_task_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeRepo:
    def __init__(self, stats_map=None):
        self.jobs = {}
        self.attempts = {}
        self._job_seq = 0
        self._attempt_seq = 0
        self.decisions = []
        self.events = []
        self.stats_map = stats_map or {}

    def create_job(self, client_key, idempotency_key, spec):
        if idempotency_key:
            for job in self.jobs.values():
                if job.idempotency_key == idempotency_key:
                    return job
        self._job_seq += 1
        job_id = f"job{self._job_seq:02d}"
        job = SimpleNamespace(
            id=job_id, client_key=client_key, idempotency_key=idempotency_key,
            spec=spec, status="pending", semantic_error=None, quality_group=None,
            content_url=None, error=None, created_at=T0)
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def get_job_for_client(self, job_id, client_key):
        job = self.jobs.get(job_id)
        if job is not None and job.client_key != client_key:
            return None
        return job

    def update_job(self, job_id, **fields):
        for k, v in fields.items():
            setattr(self.jobs[job_id], k, v)

    def add_attempt(self, *, job_id, seq, route_id, provider, quote_amount,
                    reason, is_hedge):
        self._attempt_seq += 1
        a = SimpleNamespace(
            id=self._attempt_seq, job_id=job_id, seq=seq, route_id=route_id,
            provider=provider, upstream_task_id=None, status="created",
            reason=reason, is_hedge=is_hedge, quote_amount=quote_amount,
            billing_status=None, cost=None, refunded=False, content_url=None,
            error=None, raw=None, submit_at=None, queued_at=None,
            running_at=None, ended_at=None)
        self.attempts[a.id] = a
        return a

    def mark_attempt(self, attempt_id, status, **fields):
        a = self.attempts[attempt_id]
        a.status = status
        for k, v in fields.items():
            setattr(a, k, v)

    def settle_attempt(self, attempt_id, status, billing_status, content_url,
                       cost, error=None, raw=None, ended_at=None):
        a = self.attempts[attempt_id]
        a.status = status
        a.billing_status = billing_status
        a.content_url = content_url
        a.cost = cost
        a.error = error
        a.raw = raw
        a.ended_at = ended_at or T0

    def list_attempts(self, job_id):
        return sorted((a for a in self.attempts.values() if a.job_id == job_id),
                      key=lambda a: a.seq)

    def record_event(self, *, route_id, bucket, job_id, attempt_id, success,
                     elapsed_seconds, quality_pass=True, cost=None):
        self.events.append(dict(route_id=route_id, bucket=bucket, job_id=job_id,
                                attempt_id=attempt_id, success=success,
                                elapsed_seconds=elapsed_seconds,
                                quality_pass=quality_pass, cost=cost))

    def rolling_stats(self, route_id, bucket, window=100):
        return self.stats_map.get((route_id, bucket),
                                  RouteStats(0, 0.95, 0.0, 0.0, 1.0))

    def save_decision(self, job_id, data):
        self.decisions.append((job_id, data))


def _cap(**over):
    base = dict(billing="per_second",
                duration=DurationRange(1, 30),
                resolutions=("480p", "720p", "1080p"),
                aspect_ratios=("16:9", "9:16"),
                # 含单图透传用例：当前 service 默认按 TEXT 过滤，接入意图仲裁后 1 图为 MULTI_IMAGE
                input_modes=frozenset({Mode.TEXT, Mode.MULTI_IMAGE}),
                max_images=2)
    base.update(over)
    return RouteCapability(**base)


def _route(route_id, provider, price="0.40", quality_group="h3", cap=None):
    return Route(route_id=route_id, provider=provider,
                 upstream_model=f"wf-{route_id}", quality_group=quality_group,
                 capability=cap or _cap(), pricing={"720p": price})


def _spec(**over):
    base = dict(prompt="雪山日出", duration_seconds=5, resolution="720p",
                aspect_ratio="16:9", reference_images=(), reference_videos=(),
                allow_switch=True, allow_hedge=False, deadline_seconds=None)
    base.update(over)
    return base


def _orch(routes, adapters, repo=None, now=None, **kw):
    clock = now if now is not None else lambda: T0
    return Orchestrator(repo=repo or FakeRepo(), routes=routes, adapters=adapters,
                        clock=clock, fallback_hedge_seconds=300,
                        max_parallel_attempts=2, **kw)


def _queued(task_id):
    return SimpleNamespace(upstream_task_id=task_id, phase="queued", raw={})


@pytest.mark.parametrize("scorer", [None, "error", float("nan"), 1.1, -0.1])
def test_production_safety_failure_rejects_without_dispatch(scorer):
    if scorer == "error":
        scorer = _FakeScorer(error=RuntimeError("unavailable"))
    elif scorer is not None:
        scorer = _FakeScorer(score=scorer)
    repo = FakeRepo()
    adapter = FakeAdapter("p", submit_script=[("ok", "task", "queued")])
    orch = _orch([_route("route", "p", price="0.1")], {"p": adapter}, repo=repo,
                 content_risk_scorer=scorer, content_risk_fail_closed=True)
    view = orch.submit_job("client", "idem", _spec())
    assert view.status == "failed"
    assert view.semantic_error == "content_safety_unavailable"
    assert not adapter.submit_calls
    assert orch.submit_job("client", "idem", _spec()).semantic_error == "content_safety_unavailable"


def test_pending_job_recovery_cannot_bypass_production_safety():
    repo = FakeRepo()
    adapter = FakeAdapter("p", submit_script=[("ok", "task", "queued")])
    orch = _orch([_route("route", "p", price="0.1")], {"p": adapter}, repo=repo,
                 content_risk_fail_closed=True)
    job = repo.create_job("client", "idem", _spec(mode="text"))
    assert orch.poll_job(job.id).semantic_error == "content_safety_unavailable"
    assert not adapter.submit_calls


def test_parallel_idempotent_submissions_only_dispatch_one_attempt():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    class ClaimRepo(FakeRepo):
        def __init__(self):
            super().__init__()
            self.lock = threading.Lock()
            self.claimed = False
            self.created = threading.Barrier(2)
            self.deciding = threading.Barrier(2, timeout=0.2)
            self.claim_calls = 0

        def create_job(self, client_key, idempotency_key, spec):
            with self.lock:
                job = super().create_job(client_key, idempotency_key, spec)
            self.created.wait(timeout=2)
            return job

        def claim_submission(self, job_id, *, worker_id, lease_seconds):
            with self.lock:
                self.claim_calls += 1
                if self.claimed:
                    return False
                self.claimed = True
                return True

        def release_job_claim(self, job_id, *, worker_id):
            pass

        def save_decision(self, job_id, data):
            try:
                self.deciding.wait()
            except threading.BrokenBarrierError:
                pass
            super().save_decision(job_id, data)

    repo = ClaimRepo()
    adapter = FakeAdapter("erchun", submit_script=[("ok", "T1", "queued"), ("ok", "T2", "queued")])
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter}, repo=repo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(pool.map(lambda _: orch.submit_job("k1", "same", _spec()), range(2)))
    assert views[0].id == views[1].id
    assert repo.claim_calls == 2
    assert len(adapter.submit_calls) == 1
    assert len(repo.attempts) == 1


# ---------- 提交 ----------

def test_无候选直接判能力不支持且不调供应商():
    repo = FakeRepo()
    # 480p 路线无法服务 1080p
    routes = [_route("r1", "erchun")]
    orch = _orch(routes, {"erchun": FakeAdapter("erchun")}, repo=repo)
    view = orch.submit_job("k1", "idem-1", _spec(resolution="1080p"))
    assert view.status == "failed"
    assert view.semantic_error == "unsupported_capability"


def test_正常提交落running且上送模型与幂等键():
    repo = FakeRepo()
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    view = _orch([_route("r1", "erchun")], {"erchun": adapter}, repo=repo) \
        .submit_job("k1", "idem-1", _spec())
    assert view.status == "running"
    a = view.attempts[0]
    assert a.status in ("submitted", "queued") and a.upstream_task_id == "T1"
    req = adapter.submit_calls[0]
    assert req.model == "wf-r1"
    assert req.idempotency_key == f"{view.id}-0"
    assert repo.decisions[0][1]["chosen"] == "r1"
    assert view.quality_group == "h3"


def test_get_view只读返回现状且不调用适配器推进():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")],
                          poll_script={"T1": []})  # 若触发 poll 会直接 IndexError
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter})
    submitted = orch.submit_job("k1", "idem-1", _spec())
    v1 = orch.get_view(submitted.id, "k1")
    v2 = orch.get_view(submitted.id, "k1")
    assert v1.status == "running" and v2.status == "running"
    assert v1.id == submitted.id


def test_get_view未知任务抛OrchestratorError():
    orch = _orch([_route("r1", "erchun")], {"erchun": FakeAdapter("erchun")})
    with pytest.raises(OrchestratorError):
        orch.get_view("missing", "k1")


def test_get_view跨client查询与任务不存在同样抛错():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter})
    submitted = orch.submit_job("k1", "idem-1", _spec())

    # 归属不匹配与不存在不可区分，均抛 OrchestratorError（API 层统一映射 404）
    with pytest.raises(OrchestratorError):
        orch.get_view(submitted.id, "k2")
    with pytest.raises(OrchestratorError):
        orch.get_view("missing", "k2")


def test_参考素材URL透传给适配器():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    view = _orch([_route("r1", "erchun")], {"erchun": adapter}) \
        .submit_job("k1", None,
                    _spec(reference_images=("https://audio.sggf.net/a.png",)))
    req = adapter.submit_calls[0]
    assert [(a.kind, a.ref, a.ref_type) for a in req.reference_assets] == [
        ("image", "https://audio.sggf.net/a.png", "public_url")]


def test_参考音频URL与图片一并透传给适配器():
    # 对口型是当前携带音频的合法模式：audios 必须到达 SubmitRequest，不被编排层丢弃
    cap = _cap(input_modes=frozenset({Mode.IMAGE_AUDIO_LIPSYNC}),
               max_images=2, max_audios=2)
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    _orch([_route("r1", "erchun", cap=cap)], {"erchun": adapter}) \
        .submit_job("k1", None,
                    _spec(mode="image_audio_lipsync",
                          reference_images=("https://x/a.png",),
                          reference_audios=("https://x/a.wav",)))
    req = adapter.submit_calls[0]
    assert [(a.kind, a.ref) for a in req.reference_assets] == [
        ("image", "https://x/a.png"), ("audio", "https://x/a.wav")]


class FakeRegistrar:
    """记录 register_batch 调用；按脚本返回 RegisteredAsset 或抛错。"""

    def __init__(self, ref_type="media_id", fail_route_ids=()):
        self.calls = []
        self.ref_type = ref_type
        self.fail_route_ids = set(fail_route_ids)

    def register_batch(self, route, inputs):
        from router_gateway.assets import AssetRegistrationError, RegisteredAsset
        self.calls.append((route.route_id, tuple(inputs)))
        if route.route_id in self.fail_route_ids:
            raise AssetRegistrationError("模拟素材登记失败", status=402)
        return tuple(
            RegisteredAsset(kind=i.kind, source_url=i.public_url,
                            ref=f"{self.ref_type}:{i.kind}:{n}",
                            ref_type=self.ref_type, expires_at=None)
            for n, i in enumerate(inputs))


def test_provider_upload路线提交前先登记素材并以引用提交():
    cap = _cap(asset_access="provider_upload", max_audios=3,
               input_modes=frozenset({Mode.IMAGE_AUDIO_LIPSYNC}))
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    registrar = FakeRegistrar()
    _orch([_route("r1", "erchun", cap=cap)], {"erchun": adapter},
          asset_registrar=registrar) \
        .submit_job("k1", None,
                    _spec(reference_images=("https://oss/a.jpg",),
                          reference_audios=("https://oss/a.wav",)))
    # 登记层收到的是 OSS URL 输入，文件名从 URL 路径推导
    _, inputs = registrar.calls[0]
    assert [(i.kind, i.public_url, i.filename) for i in inputs] == [
        ("image", "https://oss/a.jpg", "a.jpg"),
        ("audio", "https://oss/a.wav", "a.wav")]
    # 适配器收到的是登记引用而非原始 URL
    req = adapter.submit_calls[0]
    assert [(a.kind, a.ref, a.ref_type) for a in req.reference_assets] == [
        ("image", "media_id:image:0", "media_id"),
        ("audio", "media_id:audio:1", "media_id")]


def test_review_then_ref路线提交前批量转存素材():
    cap = _cap(asset_access="review_then_ref")
    adapter = FakeAdapter("suanliai", idempotent=False,
                          submit_script=[("ok", "T9", "queued")])
    registrar = FakeRegistrar(ref_type="review_url")
    _orch([_route("r1", "suanliai", cap=cap)], {"suanliai": adapter},
          asset_registrar=registrar) \
        .submit_job("k1", None,
                    _spec(reference_images=("https://oss/a.jpg",)))
    assert registrar.calls[0][0] == "r1"
    assert adapter.submit_calls[0].reference_assets[0].ref_type == "review_url"


def test_素材登记失败不提交供应商并在同轮切换到备份路线():
    cap1 = _cap(asset_access="provider_upload")
    cap2 = _cap(asset_access="public_url")
    a1 = FakeAdapter("erchun", idempotent=True)   # 不应被调用
    a2 = FakeAdapter("suanliai", idempotent=False,
                     submit_script=[("ok", "T2", "queued")])
    registrar = FakeRegistrar(fail_route_ids={"r1"})
    view = _orch([_route("r1", "erchun", cap=cap1),
                  _route("r2", "suanliai", cap=cap2)],
                 {"erchun": a1, "suanliai": a2},
                 asset_registrar=registrar) \
        .submit_job("k1", None,
                    _spec(reference_images=("https://oss/a.jpg",)))
    assert a1.submit_calls == []                  # 登记失败，绝不触达供应商
    assert len(a2.submit_calls) == 1
    failed, active = view.attempts
    assert failed.status == "failed"
    assert failed.error["type"] == "asset_registration"
    assert active.status in ("submitted", "queued")
    assert view.status == "running"


def test_需登记素材但未配置登记器抛配置错误():
    cap = _cap(asset_access="provider_upload")
    adapter = FakeAdapter("erchun", idempotent=True)
    orch = _orch([_route("r1", "erchun", cap=cap)], {"erchun": adapter})
    with pytest.raises(OrchestratorError):
        orch.submit_job("k1", None,
                        _spec(reference_images=("https://oss/a.jpg",)))
    assert adapter.submit_calls == []


def test_显式模式与素材矛盾时不建任务且不调供应商():
    repo = FakeRepo()
    adapter = FakeAdapter("erchun", idempotent=True)
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter}, repo=repo)
    with pytest.raises(IntentError):
        orch.submit_job("k1", "idem-bad",
                        _spec(mode="text",
                              reference_images=("https://audio.sggf.net/a.png",)))
    assert repo.jobs == {}
    assert adapter.submit_calls == []


def test_素材结构解析出的模式写入持久化spec且事件桶带模式():
    repo = FakeRepo()
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")],
                          poll_script={"T1": [NormalizedResult(
                              phase="succeeded", billing_status="settled",
                              content_url="https://v/t1.mp4")]})
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter}, repo=repo)
    view = orch.submit_job("k1", None,
                           _spec(reference_images=("https://audio.sggf.net/a.png",)))
    assert view.status == "running"
    assert repo.get_job(view.id).spec["mode"] == "multi_image"
    orch.poll_job(view.id)
    assert repo.events[-1]["bucket"] == "multi_image|720p|5s"


class _FixedClassifier:
    def __init__(self, decision):
        self._decision = decision
        self.calls = []

    def classify_mode(self, prompt, *, image_count, candidates):
        self.calls.append((prompt, image_count, candidates))
        return self._decision


def test_两图歧义时调用注入分类器并按裁决模式选路():
    flf = _route("flf", "erchun", cap=_cap(
        input_modes=frozenset({Mode.FIRST_LAST_FRAME}), max_images=2))
    multi = _route("multi", "suanliai", cap=_cap(
        input_modes=frozenset({Mode.MULTI_IMAGE}), max_images=9))
    classifier = _FixedClassifier(ModeDecision(Mode.FIRST_LAST_FRAME, 0.9))
    a_flf = FakeAdapter("erchun", idempotent=True,
                        submit_script=[("ok", "T1", "queued")])
    a_multi = FakeAdapter("suanliai")
    orch = _orch([flf, multi], {"erchun": a_flf, "suanliai": a_multi},
                 intent_classifier=classifier)
    view = orch.submit_job(
        "k1", None,
        _spec(reference_images=("https://x/a.png", "https://x/b.png")))
    assert view.attempts[0].route_id == "flf"
    assert classifier.calls and a_multi.submit_calls == []


class _FakeScorer:
    def __init__(self, *, score=None, error=None):
        self._score = score
        self._error = error
        self.calls = []

    def score_risk(self, prompt):
        self.calls.append(prompt)
        if self._error is not None:
            raise self._error
        return ContentRiskDecision(score=self._score)


def test_风险分达到阈值时前置阻断且不调任何适配器():
    repo = FakeRepo()
    adapter = FakeAdapter("erchun", idempotent=True)
    scorer = _FakeScorer(score=0.9)
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter}, repo=repo,
                 content_risk_scorer=scorer, content_risk_threshold=0.9)
    view = orch.submit_job("k1", "idem-risk", _spec(prompt="高危提示词"))
    assert view.status == "failed"
    assert view.semantic_error == "content_risk_blocked"
    assert view.attempts == ()
    assert adapter.submit_calls == []
    assert scorer.calls == ["高危提示词"]


def test_风险分低于阈值时正常提交():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    scorer = _FakeScorer(score=0.5)
    view = _orch([_route("r1", "erchun")], {"erchun": adapter},
                 content_risk_scorer=scorer, content_risk_threshold=0.9) \
        .submit_job("k1", None, _spec())
    assert view.status == "running"
    assert len(adapter.submit_calls) == 1


def test_评分器自身故障时fail_open正常提交():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    scorer = _FakeScorer(error=RuntimeError("风险模型不可用"))
    view = _orch([_route("r1", "erchun")], {"erchun": adapter},
                 content_risk_scorer=scorer, content_risk_threshold=0.9) \
        .submit_job("k1", None, _spec())
    assert view.status == "running"
    assert len(adapter.submit_calls) == 1


def test_未配置评分器时不阻断正常提交():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    view = _orch([_route("r1", "erchun")], {"erchun": adapter}) \
        .submit_job("k1", None, _spec())
    assert view.status == "running"


def test_幂等键重复提交不产生第二个尝试():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")])
    orch = _orch([_route("r1", "erchun")], {"erchun": adapter})
    v1 = orch.submit_job("k1", "same-key", _spec())
    v2 = orch.submit_job("k1", "same-key", _spec())
    assert v1.id == v2.id
    assert len(adapter.submit_calls) == 1
    assert len(v2.attempts) == 1


def test_明确拒绝自动故障切换到下一条路线():
    repo = FakeRepo()
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[AdapterError("insufficient_balance", status=402)])
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "T2", "queued")])
    routes = [_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")]
    view = _orch(routes, {"erchun": a1, "suanliai": a2}, repo=repo) \
        .submit_job("k1", None, _spec())
    assert view.status == "running"
    assert [a.seq for a in view.attempts] == [0, 1]
    assert view.attempts[0].status == "failed"
    assert view.attempts[0].route_id == "r1"
    assert view.attempts[1].route_id == "r2" and view.attempts[1].upstream_task_id == "T2"


def test_全部明确失败任务失败并记录语义():
    a1 = FakeAdapter("erchun", submit_script=[AdapterError("bad", status=400)])
    a2 = FakeAdapter("suanliai", submit_script=[AdapterError("bad2", status=400)])
    view = _orch([_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
                 {"erchun": a1, "suanliai": a2}) \
        .submit_job("k1", None, _spec())
    assert view.status == "failed"
    assert view.semantic_error == "all_candidates_failed"
    assert len(view.attempts) == 2


def test_禁止切换时明确失败不切路由():
    a1 = FakeAdapter("erchun", submit_script=[AdapterError("bad", status=400)])
    a2 = FakeAdapter("suanliai", submit_script=[("ok", "T2", "queued")])
    view = _orch([_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
                 {"erchun": a1, "suanliai": a2}) \
        .submit_job("k1", None, _spec(allow_switch=False))
    assert view.status == "failed"
    assert len(view.attempts) == 1 and len(a2.submit_calls) == 0


def test_提交超时未知时用同幂等键重放防双扣():
    adapter = FakeAdapter("erchun", idempotent=True, submit_script=[
        RetriableTransportError("timeout"), ("ok", "T1", "queued")])
    view = _orch([_route("r1", "erchun")], {"erchun": adapter}) \
        .submit_job("k1", None, _spec())
    assert view.status == "running"
    assert len(view.attempts) == 1
    keys = {c.idempotency_key for c in adapter.submit_calls}
    assert keys == {f"{view.id}-0"}


def test_幂等重放仍未知则判状态未知():
    adapter = FakeAdapter("erchun", idempotent=True, submit_script=[
        RetriableTransportError("timeout"), RetriableTransportError("timeout2")])
    view = _orch([_route("r1", "erchun")], {"erchun": adapter}) \
        .submit_job("k1", None, _spec(allow_switch=False))
    assert view.status == "failed"
    assert view.semantic_error == "upstream_unknown"
    assert view.attempts[0].status == "unknown"


def test_无幂等能力供应商提交未知时切换并显式记录双扣风险():
    a1 = FakeAdapter("autodl", idempotent=False,
                     submit_script=[RetriableTransportError("conn lost")])
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "T2", "queued")])
    view = _orch([_route("r1", "autodl", "0.07"), _route("r2", "suanliai", "0.40")],
                 {"autodl": a1, "suanliai": a2}) \
        .submit_job("k1", None, _spec())
    assert view.status == "running" and view.attempts[1].route_id == "r2"
    assert view.attempts[0].status == "unknown"
    assert view.attempts[0].reason == "submit_unknown_double_charge_risk"


# ---------- 轮询 ----------

def _running_job(routes, adapters, orch_kw=None):
    repo = FakeRepo()
    orch = _orch(routes, adapters, repo=repo, **(orch_kw or {}))
    view = orch.submit_job("k1", None, _spec())
    return orch, repo, view


def test_轮询成功首胜交付并触发终态回调():
    adapter = FakeAdapter("erchun", idempotent=True,
                          submit_script=[("ok", "T1", "queued")],
                          poll_script={"T1": [NormalizedResult(
                              phase="succeeded", billing_status="settled",
                              content_url="https://v/t1.mp4")]})
    terminal = []
    orch, repo, view = _running_job(
        [_route("r1", "erchun")], {"erchun": adapter},
        orch_kw=dict(on_job_terminal=lambda job: terminal.append(job.id)))
    out = orch.poll_job(view.id)
    assert out.status == "succeeded"
    assert out.content_url == "https://v/t1.mp4"
    assert terminal == [view.id]
    assert repo.events[-1]["success"] is True


def test_轮询确认失败后自动切换下一路线():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "queued")],
                     poll_script={"T1": [NormalizedResult(
                         phase="failed", billing_status="refunded",
                         error={"code": "upstream_error"})]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "T2", "queued")])
    orch, _, view = _running_job(
        [_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
        {"erchun": a1, "suanliai": a2})
    out = orch.poll_job(view.id)
    assert out.status == "running"
    assert [a.route_id for a in out.attempts] == ["r1", "r2"]
    assert out.attempts[1].reason == "failover_after_failed"


def test_轮询传输抖动保持活动不切换():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "queued")],
                     poll_script={"T1": [RetriableTransportError("reset")]})
    orch, _, view = _running_job([_route("r1", "erchun")], {"erchun": a1})
    out = orch.poll_job(view.id)
    assert out.status == "running"
    assert len(out.attempts) == 1 and out.attempts[0].status == "queued"


def test_审核挂起态不结算不记事件不切换且后续成功可收尾():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "queued")],
                     poll_script={"T1": [
                         NormalizedResult(phase="review",
                                          error={"type": "manual_review"}),
                         NormalizedResult(phase="review"),
                         NormalizedResult(phase="succeeded",
                                          billing_status="settled",
                                          content_url="https://v/t1.mp4")]})
    orch, repo, view = _running_job(
        [_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
        {"erchun": a1})

    tick1 = orch.poll_job(view.id)
    attempt = repo.list_attempts(view.id)[0]
    assert attempt.status == "review"
    assert tick1.status == "running"
    assert repo.events == []              # 挂起不记成败事件
    assert attempt.billing_status is None  # 不结算、不自动退
    assert attempt.content_url is None
    assert len(a1.submit_calls) == 1       # 不触发故障切换

    tick2 = orch.poll_job(view.id)         # 审核持续：继续对账，仍不开备份
    assert tick2.status == "running"
    assert repo.list_attempts(view.id)[0].status == "review"
    assert len(a1.submit_calls) == 1

    tick3 = orch.poll_job(view.id)         # 供应商转成功：正常收尾
    assert tick3.status == "succeeded"
    assert tick3.content_url == "https://v/t1.mp4"
    assert repo.events[-1]["success"] is True


def test_审核挂起后供应商明确失败仍可故障切换():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "queued")],
                     poll_script={"T1": [
                         NormalizedResult(phase="review"),
                         NormalizedResult(phase="failed",
                                          billing_status="refunded",
                                          error={"type": "content_rejected"})]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "T2", "queued")],
                     poll_script={"T2": [NormalizedResult(
                         phase="succeeded", billing_status="settled",
                         content_url="https://v/t2.mp4")]})
    orch, repo, view = _running_job(
        [_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
        {"erchun": a1, "suanliai": a2})

    held = orch.poll_job(view.id)  # review：先挂起，不切换
    assert held.status == "running"
    assert [a.status for a in held.attempts] == ["review"]
    assert repo.events == []
    orch.poll_job(view.id)   # failed：结算 r1 并切换提交 r2
    out = orch.poll_job(view.id)  # r2 成功
    assert out.status == "succeeded"
    assert out.content_url == "https://v/t2.mp4"
    assert [a.status for a in out.attempts] == ["failed", "succeeded"]
    assert [e["success"] for e in repo.events] == [False, True]


def test_慢任务超p95触发跨供应商对冲():
    repo = FakeRepo(stats_map={
        ("r1", "text|720p|5s"): RouteStats(100, 1.0, 100, 200, 1.0),
    })
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "running")],
                     poll_script={"T1": [NormalizedResult(phase="running")]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "H1", "queued")])
    clock_value = T0

    def clock():
        return clock_value

    orch = Orchestrator(repo=repo,
                        routes=[_route("r1", "erchun", "0.07"),
                                _route("r2", "suanliai", "0.40")],
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=clock, fallback_hedge_seconds=300)
    view = orch.submit_job("k1", None, _spec(allow_hedge=True))
    # 活动尝试 submit_at=T0；201 秒后超过 r1 的 P95=200
    clock_value = T0 + timedelta(seconds=201)
    out = orch.poll_job(view.id)
    hedge = [a for a in out.attempts if a.is_hedge]
    assert len(hedge) == 1 and hedge[0].route_id == "r2"
    assert hedge[0].reason == "hedge_slow"


def test_客户级max_parallel_attempts为一时禁止对冲():
    repo = FakeRepo(stats_map={
        ("r1", "text|720p|5s"): RouteStats(100, 1.0, 100, 200, 1.0),
    })
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "running")],
                     poll_script={"T1": [NormalizedResult(phase="running")]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "H1", "queued")])
    clock_value = T0

    def clock():
        return clock_value

    orch = Orchestrator(repo=repo,
                        routes=[_route("r1", "erchun", "0.07"),
                                _route("r2", "suanliai", "0.40")],
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=clock, fallback_hedge_seconds=300)
    view = orch.submit_job(
        "k1", None, _spec(allow_hedge=True, max_parallel_attempts=1))
    clock_value = T0 + timedelta(seconds=201)
    out = orch.poll_job(view.id)
    assert [a.route_id for a in out.attempts] == ["r1"]
    assert a2.submit_calls == []


def test_双成功时先到者唯一交付晚到不误判():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "running")],
                     poll_script={"T1": [NormalizedResult(phase="running")]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "H1", "queued")],
                     poll_script={"H1": [NormalizedResult(
                         phase="succeeded", billing_status="settled",
                         content_url="https://v/hedge.mp4")]})
    clock_value = T0

    def clock():
        return clock_value

    repo = FakeRepo(stats_map={("r1", "text|720p|5s"): RouteStats(100, 1.0, 100, 200, 1.0)})
    orch = Orchestrator(repo=repo,
                        routes=[_route("r1", "erchun", "0.07"),
                                _route("r2", "suanliai", "0.40")],
                        adapters={"erchun": a1, "suanliai": a2},
                        clock=clock, fallback_hedge_seconds=300)
    view = orch.submit_job("k1", None, _spec(allow_hedge=True))
    clock_value = T0 + timedelta(seconds=201)
    tick1 = orch.poll_job(view.id)  # 第 1 拍：原路线仍在跑，启动跨源对冲
    assert tick1.status == "running"
    assert [a.route_id for a in tick1.attempts] == ["r1", "r2"]

    a1.poll_script["T1"] = [NormalizedResult(phase="running")]
    clock_value = T0 + timedelta(seconds=210)
    out = orch.poll_job(view.id)  # 第 2 拍：对冲成片先通过验收
    assert out.status == "succeeded" and out.content_url == "https://v/hedge.mp4"

    # 原路线更晚才成功：照常记录真实状态与成本，但不覆盖交付物
    a1.poll_script["T1"] = [NormalizedResult(
        phase="succeeded", billing_status="settled", content_url="https://v/orig.mp4")]
    clock_value = T0 + timedelta(seconds=300)
    out2 = orch.poll_job(view.id)
    assert out2.content_url == "https://v/hedge.mp4"
    settled = [a for a in out2.attempts if a.status == "succeeded"]
    assert len(settled) == 2


def test_超过截止时间任务判超时但活动尝试保留对账():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "running")],
                     poll_script={"T1": [NormalizedResult(phase="running")]})
    clock_value = T0

    def clock():
        return clock_value

    repo = FakeRepo()
    orch = Orchestrator(repo=repo, routes=[_route("r1", "erchun")],
                        adapters={"erchun": a1}, clock=clock)
    view = orch.submit_job("k1", None, _spec(deadline_seconds=600))
    clock_value = T0 + timedelta(seconds=601)
    out = orch.poll_job(view.id)
    assert out.status == "failed"
    assert out.semantic_error == "deadline_exceeded"
    assert out.attempts[0].status == "running"  # 未伪造失败，留后台对账


def test_成片内容校验不过按失败切换():
    a1 = FakeAdapter("erchun", idempotent=True,
                     submit_script=[("ok", "T1", "queued")],
                     poll_script={"T1": [NormalizedResult(
                         phase="succeeded", billing_status="settled",
                         content_url="https://v/t1.mp4")]})
    a2 = FakeAdapter("suanliai", idempotent=True,
                     submit_script=[("ok", "T2", "queued")])
    orch, _, view = _running_job(
        [_route("r1", "erchun", "0.07"), _route("r2", "suanliai", "0.40")],
        {"erchun": a1, "suanliai": a2},
        orch_kw=dict(content_validator=lambda url, raw: False))
    out = orch.poll_job(view.id)
    assert out.status == "running" and out.attempts[1].route_id == "r2"
    assert out.attempts[0].status == "failed"


def test_查询不存在任务抛错():
    orch = _orch([_route("r1", "erchun")], {"erchun": FakeAdapter("erchun")})
    with pytest.raises(OrchestratorError):
        orch.poll_job("nope")
