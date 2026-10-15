from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from router_gateway.db import Base, JobRepository
from router_gateway.quota import RedisTokenBucket


def test_query_traffic_has_independent_quota():
    from fastapi.testclient import TestClient
    from router_gateway.api import create_app
    from router_gateway.tests.test_api_http import StubOrchestrator, _resolve_client, _body, _AUTH
    calls = []

    class Limiter:
        def check(self, **values):
            calls.append(values)

    client = TestClient(create_app(StubOrchestrator(), resolve_client=_resolve_client(), rate_limiter=Limiter()))
    client.post("/v1/videos", json=_body(), headers=_AUTH)
    client.get("/v1/tasks/job-1", headers=_AUTH)
    assert len(calls) == 2
    assert calls[0]["key"] != calls[1]["key"]


def test_quota_changes_do_not_break_idempotent_replay(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'idempotency.db'}")
    Base.metadata.create_all(engine)
    repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
    client = repo.create_client("partner", "key", max_active_jobs=1)
    first = repo.create_job(client.id, "same", {"prompt": "test", "max_parallel_attempts": 2})
    replay = repo.create_job(client.id, "same", {"prompt": "test", "max_parallel_attempts": 1})
    assert replay.id == first.id
    engine.dispose()


def test_json_persistence_does_not_break_reference_replay(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'references.db'}")
    Base.metadata.create_all(engine)
    repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
    client = repo.create_client('partner', 'key')
    spec = {'prompt': 'test', 'reference_images': ('https://example.com/image',)}
    first = repo.create_job(client.id, 'same', spec)
    replay = repo.create_job(client.id, 'same', spec)
    assert first.id == replay.id
    engine.dispose()


def test_redis_rate_client_uses_bounded_timeouts(monkeypatch):
    import redis
    calls = []
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: calls.append(kwargs))
    RedisTokenBucket.from_url("redis://localhost/1")
    assert calls[0]["socket_timeout"] <= 3
    assert calls[0]["socket_connect_timeout"] <= 3


def test_redis_limiter_does_not_retry_failed_connections():
    limiter = RedisTokenBucket.from_url("redis://127.0.0.1:1/0")
    assert limiter._client.connection_pool.connection_kwargs["retry"]._retries == 0
    limiter._client.close()


def test_submission_claim_cannot_be_reentered_or_released_by_other_owner(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim.db'}")
    Base.metadata.create_all(engine)
    repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
    client = repo.create_client("partner", "key")
    job = repo.create_job(client.id, "same", {"prompt": "test"})
    assert repo.claim_submission(job.id, worker_id="first", lease_seconds=30)
    repo.release_job_claim(job.id, worker_id="other")
    assert not repo.claim_submission(job.id, worker_id="first", lease_seconds=30)
    assert not repo.claim_submission(job.id, worker_id="other", lease_seconds=30)
    repo.release_job_claim(job.id, worker_id="first")
    assert repo.claim_submission(job.id, worker_id="other", lease_seconds=30)
    repo.add_attempt(job.id, 0, "route", "provider", "0", "initial", False)
    repo.release_job_claim(job.id, worker_id="other")
    assert not repo.claim_submission(job.id, worker_id="new", lease_seconds=30)
    engine.dispose()


def test_metrics_includes_outstanding_attempts_and_unknown_cost(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'metrics.db'}")
    Base.metadata.create_all(engine)
    repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
    job = repo.create_job("client", "one", {"prompt": "secret"})
    attempt = repo.add_attempt(job.id, 0, "route", "provider", "0.40", "initial", False)
    repo.mark_attempt(attempt.id, "running")
    repo.update_job(job.id, status="failed", semantic_error="deadline_exceeded")
    result = repo.gateway_metrics()
    assert result["active_jobs"] == 1
    assert result["unknown_cost_attempts"] == 1
    assert result["total_cost"] is None
    engine.dispose()


def test_metrics_preserves_recorded_attempt_cost(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cost.db'}")
    Base.metadata.create_all(engine)
    repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
    job = repo.create_job('client', 'cost', {})
    attempt = repo.add_attempt(job.id, 0, 'route', 'provider', '1.20', 'initial', False)
    repo.settle_attempt(attempt.id, 'succeeded', 'settled', 'https://example.com/video', '1.20')
    repo.record_event('route', 'bucket', job.id, attempt.id, True, 2)
    assert repo.gateway_metrics()['total_cost'] == '1.2000'
    engine.dispose()


def test_production_cannot_start_without_redis(monkeypatch):
    import pytest
    from router_gateway import assembly
    monkeypatch.setattr(assembly, '_build_adapters', lambda *args: {})
    with pytest.raises(RuntimeError, match='ROUTER_GATEWAY_REDIS_URL'):
        assembly.build_gateway(env={'APP_ENV': 'production', 'ROUTER_GATEWAY_DATABASE_URL': 'sqlite://'})
