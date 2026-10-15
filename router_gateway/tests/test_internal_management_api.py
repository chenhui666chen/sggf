import pytest

from fastapi.testclient import TestClient

from router_gateway.api import create_app
from router_gateway.db import JobRepository, get_engine, make_session_factory
from router_gateway.db.init_db import init_schema


class StubOrchestrator:
    pass


def _make_app(repo, token="internal-test-token"):
    return create_app(
        StubOrchestrator(),
        resolve_client=lambda key: None,
        admin_repo=repo,
        internal_token=token,
    )


def test_internal_management_requires_non_empty_matching_token(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'internal.db'}")
    init_schema(engine)
    repo = JobRepository(make_session_factory(engine))
    client = TestClient(_make_app(repo))

    missing = client.post("/internal/clients", json={"name": "missing"})
    wrong = client.post(
        "/internal/clients", json={"name": "wrong"},
        headers={"X-Gateway-Internal-Token": "wrong"})

    assert missing.status_code == 404
    assert wrong.status_code == 404
    engine.dispose()


def test_internal_client_creation_rotation_and_limit_update(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'internal-lifecycle.db'}")
    init_schema(engine)
    repo = JobRepository(make_session_factory(engine))
    client = TestClient(_make_app(repo))
    headers = {"X-Gateway-Internal-Token": "internal-test-token"}

    created = client.post(
        "/internal/clients", json={"name": "partner", "max_parallel_attempts": 1},
        headers=headers)
    assert created.status_code == 200
    payload = created.json()
    assert payload["api_key"]
    assert payload["max_parallel_attempts"] == 1
    client_id = payload["id"]
    old_key = payload["api_key"]

    updated = client.patch(
        f"/internal/clients/{client_id}/limits",
        json={"max_active_jobs": 20, "max_parallel_attempts": 3},
        headers=headers)
    assert updated.status_code == 200
    assert updated.json()["max_active_jobs"] == 20
    assert updated.json()["max_parallel_attempts"] == 3

    rotated = client.post(
        f"/internal/clients/{client_id}/rotate-key", headers=headers)
    assert rotated.status_code == 200
    assert rotated.json()["api_key"] != old_key
    assert repo.get_client_by_api_key(old_key) is None
    assert repo.get_client_by_api_key(rotated.json()["api_key"]) is not None
    assert "api_key_hash" in rotated.json()
    engine.dispose()


def test_internal_metrics只返回聚合数据(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'metrics.db'}")
    init_schema(engine)
    repo = JobRepository(make_session_factory(engine))
    job = repo.create_job("client-metrics", "idem-1", {
        "prompt": "不得出现在指标响应中", "mode": "text"})
    repo.record_event("route-a", "text|720p|5s", job.id, 1,
                      success=True, elapsed_seconds=2.0, cost="0.40")
    repo.update_job(job.id, status="running")
    client = TestClient(_make_app(repo))

    response = client.get(
        "/internal/metrics/overview?window_hours=24",
        headers={"X-Gateway-Internal-Token": "internal-test-token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["route_event_count"] == 1
    assert payload["active_jobs"] == 1
    assert payload["routes"][0]["success_rate"] == 1.0
    assert "不得出现在指标响应中" not in str(payload)
    engine.dispose()


def test_database_hash_placeholder_cannot_authenticate(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'hash.db'}")
    init_schema(engine)
    repo = JobRepository(make_session_factory(engine))
    issued = repo.create_client("partner", "private-key")
    assert repo.get_client_by_api_key(issued.api_key) is None
    engine.dispose()


@pytest.mark.parametrize("path,payload", [
    ("/internal/clients", {"name": "partner", "max_active_jobs": -1}),
    ("/internal/clients/missing/status", {"enabled": "false"}),
])
def test_internal_management_rejects_invalid_input(tmp_path, path, payload):
    engine = get_engine(f"sqlite:///{tmp_path / 'validation.db'}")
    init_schema(engine)
    client = TestClient(_make_app(JobRepository(make_session_factory(engine))))
    response = client.post(path, json=payload, headers={"X-Gateway-Internal-Token": "internal-test-token"})
    assert response.status_code == 422
    engine.dispose()
