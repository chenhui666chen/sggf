import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from router_gateway.db import Base, JobRepository, make_session_factory


@pytest.fixture
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quality.db'}")
    Base.metadata.create_all(engine)
    repository = JobRepository(make_session_factory(engine))
    repository.quality_sample_every = 1
    yield repository
    engine.dispose()


def delivered(repo, route="r1", score_url="https://example.com/video.mp4"):
    job = repo.create_job("client", None, {"mode": "text", "resolution": "720p",
                                           "duration_seconds": 5})
    attempt = repo.add_attempt(job.id, 0, route, "fake", "1", "test", False)
    repo.settle_attempt(attempt.id, "succeeded", "settled", score_url, "1")
    repo.update_job(job.id, status="succeeded", content_url=score_url)
    repo.record_event(route, "text|720p|5s", job.id, attempt.id, True, 12)
    return repo.get_job(job.id), repo.get_attempt(attempt.id)


def test_quality_claim_is_persistent_unique_and_excludes_undelivered(repo):
    job, attempt = delivered(repo)
    repo.update_job(job.id, status="running")
    assert hasattr(repo, "claim_quality_review"), "后台评价领取接口尚未实现"
    assert repo.claim_quality_review(worker_id="a") is None
    repo.update_job(job.id, status="succeeded")
    review = repo.claim_quality_review(worker_id="a")
    assert review.attempt_id == attempt.id
    assert repo.claim_quality_review(worker_id="b") is None


@pytest.mark.parametrize("outcome", [2, 9, RuntimeError("secret upstream error")])
def test_review_never_changes_delivery_and_failures_are_not_bad_quality(repo, outcome):
    from router_gateway.quality_worker import run_once

    job, attempt = delivered(repo)
    reviewer = SimpleNamespace(model="qwen3.8-omni-flash")

    def evaluate(url):
        if isinstance(outcome, Exception):
            raise outcome
        return {"scores": {name: {"score": outcome, "comment": "画面证据"}
                           for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}

    reviewer.evaluate = evaluate
    assert run_once(repo, reviewer, worker_id="a") == 1
    assert repo.get_job(job.id).status == "succeeded"
    assert repo.get_job(job.id).content_url == attempt.content_url
    assert repo.get_attempt(attempt.id).billing_status == "settled"
    assert run_once(repo, reviewer, worker_id="a") == 0
    stats = repo.rolling_stats("r1", "text|720p|5s")
    assert stats.success_rate == 1
    assert stats.quality_samples == (0 if isinstance(outcome, Exception) else 1)
    assert stats.quality_pass_rate == (0 if outcome == 2 else 1)


def test_abandoned_review_is_not_retried_or_overwritten_by_stale_worker(repo):
    from router_gateway.db import QualityReview

    delivered(repo)
    first = repo.claim_quality_review(worker_id="old")
    with repo._sf() as session:
        session.get(QualityReview, first.id).claim_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert repo.claim_quality_review(worker_id="new") is None
    assert repo.finish_quality_review(first.id, worker_id=first.claim_token, result={"scores": {}},
                                      score=9, passed=True, model="fake") is False
    with repo._sf() as session:
        review = session.get(QualityReview, first.id)
        assert review.status == "failed"
        assert review.error_code == "worker_lost"


def test_visual_client_payload_and_strict_score_validation():
    from router_gateway.quality import VideoQualityClient, validate_review

    calls = []
    response = {"scores": {name: {"score": 8, "comment": "画面证据"}
                           for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}

    def request(*args, **kwargs):
        calls.append(kwargs)
        return 200, {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]}

    fetcher = lambda *args, **kwargs: SimpleNamespace(body=b"video", content_type="video/mp4")
    client = VideoQualityClient(api_key="test", transport=SimpleNamespace(request=request), fetcher=fetcher)
    assert client.evaluate("https://example.com/v.mp4") == response
    payload = calls[0]["body"]
    assert payload["model"] == "qwen3.8-omni-flash"
    assert payload["reasoning_effort"] == "none"
    assert payload["max_tokens"] == 1200
    assert "response_format" not in payload
    for invalid in (float("nan"), float("inf"), -1, 11, "9", True):
        response["scores"]["clarity"]["score"] = invalid
        with pytest.raises(ValueError):
            validate_review(response)


def test_quality_scores_influence_only_future_route_ranking(repo):
    from router_gateway.quality_worker import run_once
    from router_gateway.router import rank_candidates
    from router_gateway.catalog import VideoSpec
    from router_gateway.tests.test_orchestrator_service import _route

    delivered(repo, "cheap")
    delivered(repo, "good")
    bad = {"scores": {name: {"score": 2, "comment": "模糊证据"}
                      for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}
    run_once(repo, SimpleNamespace(model="fake", evaluate=lambda url: bad), worker_id="a")
    stats = {route: repo.rolling_stats(route, "text|720p|5s") for route in ("cheap", "good")}
    ranked = rank_candidates([_route("cheap", "fake", "0.40"), _route("good", "fake", "0.41")],
                             VideoSpec("x", 5, "720p", "16:9"), stats)
    assert ranked[0].route.route_id == "good"


def test_missing_quality_table_keeps_delivery_routing_available(tmp_path):
    from router_gateway.db import QualityReview

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables
                                           if table is not QualityReview.__table__])
    repository = JobRepository(make_session_factory(engine))
    delivered(repository)
    assert repository.rolling_stats("r1", "text|720p|5s").quality_samples == 0
    engine.dispose()


def test_public_responses_never_expose_internal_reviews(repo):
    from fastapi.testclient import TestClient
    from router_gateway.api import create_app
    from router_gateway.orchestrator.service import Orchestrator
    from router_gateway.quality_worker import run_once

    job, _ = delivered(repo)
    result = {"scores": {name: {"score": 1, "comment": "内部缺陷证据"}
                         for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}
    orch = Orchestrator(repo=repo, routes=[], adapters={})
    client = TestClient(create_app(orch, resolve_client=lambda key: SimpleNamespace(
        id="client", enabled=True, max_parallel_attempts=2), admin_repo=repo,
        internal_token="internal-test"))
    before = client.get(f"/v1/tasks/{job.id}", headers={"Authorization": "Bearer test"})
    run_once(repo, SimpleNamespace(model="fake", evaluate=lambda url: result))
    after = client.get(f"/v1/tasks/{job.id}", headers={"Authorization": "Bearer test"})
    assert before.status_code == after.status_code == 200
    assert before.json() == after.json()
    assert after.json()["status"] == "succeeded"
    assert "scores" not in after.text and "内部缺陷证据" not in after.text
    assert client.get("/internal/metrics/overview").status_code in (401, 403, 404, 503)


def test_internal_metrics_include_quality_samples_without_raw_evidence(repo):
    from router_gateway.quality_worker import run_once

    delivered(repo)
    result = {"scores": {name: {"score": 2, "comment": "内部画面证据"}
                         for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}
    run_once(repo, SimpleNamespace(model="fake", evaluate=lambda url: result))
    metrics = repo.gateway_metrics()
    assert metrics["quality"]["completed"] == 1
    assert metrics["routes"][0]["quality_samples"] == 1
    assert metrics["routes"][0]["quality_pass_rate"] == 0
    assert metrics["routes"][0]["quality_average_score"] == 2
    assert "内部画面证据" not in json.dumps(metrics, ensure_ascii=False)


@pytest.mark.parametrize("content", ["not json", '{"scores":{}}'])
def test_bad_model_response_never_counts_as_quality_failure(repo, content):
    from router_gateway.quality import VideoQualityClient
    from router_gateway.quality_worker import run_once

    job, _ = delivered(repo)
    reviewer = VideoQualityClient(api_key="fake", transport=SimpleNamespace(
        request=lambda *args, **kwargs: (200, {"choices": [{"message": {"content": content}}]})),
        fetcher=lambda *args, **kwargs: SimpleNamespace(body=b"video", content_type="video/mp4"))
    assert run_once(repo, reviewer) == 1
    assert repo.get_job(job.id).status == "succeeded"
    assert repo.rolling_stats("r1", "text|720p|5s").quality_samples == 0


def test_two_quality_samples_and_duplicate_events_do_not_distort_denominator(repo):
    from router_gateway.quality_worker import run_once

    job, attempt = delivered(repo)
    delivered(repo)
    repo.record_event("r1", "text|720p|5s", job.id, attempt.id, True, 12)
    result = {"scores": {name: {"score": 2, "comment": "模糊证据"}
                         for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}
    reviewer = SimpleNamespace(model="fake", evaluate=lambda url: result)
    assert run_once(repo, reviewer) == 1
    assert run_once(repo, reviewer) == 1
    stats = repo.rolling_stats("r1", "text|720p|5s")
    assert stats.quality_samples == 2
    assert stats.quality_pass_rate == 0


def test_delivery_poll_finishes_before_any_visual_review(repo):
    from router_gateway.adapters.base import NormalizedResult
    from router_gateway.orchestrator.service import Orchestrator
    from router_gateway.tests.test_orchestrator_service import FakeAdapter, _route, _spec
    from router_gateway.db import QualityReview

    adapter = FakeAdapter("fake", submit_script=[("ok", "up", "queued")],
                          poll_script={"up": [NormalizedResult(
                              phase="succeeded", content_url="https://example.com/video.mp4")]})
    orch = Orchestrator(repo=repo, routes=[_route("r1", "fake")], adapters={"fake": adapter})
    view = orch.submit_job("client", "order", _spec())
    repo.mark_attempt(repo.list_attempts(view.id)[0].id, "submitted", submit_at=None)
    final = orch.poll_job(view.id)
    assert final.status == "succeeded"
    assert final.content_url == "https://example.com/video.mp4"
    with repo._sf() as session:
        assert session.query(QualityReview).count() == 0


def test_concurrent_consumers_claim_each_attempt_once(repo):
    from concurrent.futures import ThreadPoolExecutor

    delivered(repo)
    with ThreadPoolExecutor(max_workers=4) as executor:
        reviews = list(executor.map(lambda worker: repo.claim_quality_review(worker_id=str(worker)), range(4)))
    assert len([review for review in reviews if review is not None]) == 1


def test_raw_control_characters_supported_without_paid_retry():
    from router_gateway.vision_contract import parse_vision_review_content

    assert parse_vision_review_content('{"comment":"第一帧\n第二帧"}') == {"comment": "第一帧\n第二帧"}
    assert parse_vision_review_content('{"scores": invalid}') == {}


def test_every_tenth_success_for_same_model_triggers_review_across_routes_and_restarts(repo):
    repo.quality_sample_every = 10
    repo.quality_model_keys = {"r1": "model-a", "r2": "model-a", "r3": "model-b"}
    for index in range(9):
        delivered(repo, "r1" if index % 2 else "r2")
    delivered(repo, "r3")
    assert repo.claim_quality_review(worker_id="first") is None
    fresh = JobRepository(repo._sf, quality_model_keys=repo.quality_model_keys)
    _, tenth = delivered(fresh, "r1")
    review = fresh.claim_quality_review(worker_id="second")
    assert review.attempt_id == tenth.id
    assert review.sample_index == 10
    assert review.model_key == "model-a"
    assert fresh.claim_quality_review(worker_id="third") is None


def test_sampling_resumes_after_failed_tenth_review_and_skips_failed_generations(repo):
    from router_gateway.quality_worker import run_once

    repo.quality_sample_every = 10
    for _ in range(9):
        delivered(repo)
    failed_job = repo.create_job("client", None, {"mode": "text"})
    failed_attempt = repo.add_attempt(failed_job.id, 0, "r1", "fake", "1", "test", False)
    repo.settle_attempt(failed_attempt.id, "failed", None, None, None)
    repo.update_job(failed_job.id, status="failed")
    delivered(repo)
    calls = []

    def timeout(url):
        calls.append(url)
        raise TimeoutError("model timeout")

    reviewer = SimpleNamespace(model="fake", evaluate=timeout)
    assert run_once(repo, reviewer) == 1
    assert len(calls) == 1
    for _ in range(9):
        delivered(repo)
    assert run_once(repo, reviewer) == 0
    delivered(repo)
    assert run_once(repo, reviewer) == 1
    assert len(calls) == 2


def test_worker_reviews_self_owned_delivery_url_and_keeps_delivery_success(repo):
    from router_gateway.quality_worker import run_once

    job, _ = delivered(repo)
    repo.update_job(job.id, content_url="https://video.example.com/delivered.mp4")
    calls = []
    result = {"scores": {name: {"score": 9, "comment": "主体清楚"}
                         for name in ("clarity", "smoothness", "consistency", "lighting", "color")}}
    reviewer = SimpleNamespace(model="fake", evaluate=lambda url: (calls.append(url) or result))
    assert run_once(repo, reviewer) == 1
    assert calls == ["https://video.example.com/delivered.mp4"]


def test_late_failure_or_old_token_cannot_overwrite_completed_review(repo):
    delivered(repo)
    review = repo.claim_quality_review(worker_id="a")
    assert repo.finish_quality_review(review.id, worker_id="wrong", error_code="failed") is False
    assert repo.finish_quality_review(review.id, worker_id=review.claim_token,
                                      result={"scores": {}}, score=9, passed=True, model="fake") is True
    assert repo.finish_quality_review(review.id, worker_id=review.claim_token, error_code="failed") is False
