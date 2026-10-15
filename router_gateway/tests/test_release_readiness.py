from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

import pytest
from sqlalchemy import create_engine

from router_gateway.db import Base, Job, JobRepository, make_session_factory


@pytest.fixture
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'readiness.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    yield JobRepository(make_session_factory(engine))
    engine.dispose()


def test_polling_due_time_prevents_oldest_jobs_starving_new_jobs(repo):
    jobs = [repo.create_job("trial", str(index), {}) for index in range(25)]
    first = repo.claim_active_job_ids(worker_id="one", limit=20)
    for job_id in first:
        repo.release_job_claim(job_id, worker_id="one")
    second = repo.claim_active_job_ids(worker_id="two", limit=20)
    assert len(first) == 20
    assert len(second) == 5
    assert set(first).isdisjoint(second)
    assert set(first + second) == {job.id for job in jobs}


def test_expired_worker_cannot_write_or_release_new_owner(repo):
    job = repo.create_job("trial", None, {})
    repo.claim_active_job_ids(worker_id="old", limit=1)
    with repo._sf() as session:
        record = session.get(Job, job.id)
        record.claim_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        record.next_poll_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert repo.claim_active_job_ids(worker_id="new", limit=1) == [job.id]
    with repo.claimed_job(job.id, claim_token="old"):
        with pytest.raises(RuntimeError, match="lease"):
            repo.update_job(job.id, status="failed")
    assert repo.renew_job_claim(job.id, worker_id="old", lease_seconds=30) is False
    repo.release_job_claim(job.id, worker_id="old")
    assert repo.get_job(job.id).claimed_by == "new"
    assert repo.get_job(job.id).status == "pending"


def test_live_lease_can_be_renewed_but_expired_lease_cannot(repo):
    job = repo.create_job("trial", None, {})
    repo.claim_active_job_ids(worker_id="one", limit=1)
    assert repo.renew_job_claim(job.id, worker_id="one", lease_seconds=120)
    with repo._sf() as session:
        session.get(Job, job.id).claim_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert not repo.renew_job_claim(job.id, worker_id="one", lease_seconds=120)


def test_worker_claims_one_job_at_a_time_and_uses_unique_tokens(repo):
    from router_gateway.worker import run_once

    for index in range(3):
        repo.create_job("trial", str(index), {})
    tokens = []

    def poll(job_id):
        tokens.append(repo.get_job(job_id).claimed_by)
        assert len([item for item in tokens if item == tokens[-1]]) == 1
        repo.update_job(job_id, status="succeeded")

    assert run_once(SimpleNamespace(poll_job=poll), repo, limit=3, worker_id="test") == 3
    assert len(set(tokens)) == 3


def test_trial_total_limit_is_atomic_and_idempotent_replay_does_not_consume_it(repo):
    client = repo.create_client("trial", "test", lifetime_task_limit=2)
    first = repo.create_job(client.id, "first", {})
    repo.update_job(first.id, status="succeeded")
    second = repo.create_job(client.id, "second", {})
    repo.update_job(second.id, status="failed")
    assert repo.create_job(client.id, "first", {}).id == first.id
    with pytest.raises(ValueError, match="task limit"):
        repo.create_job(client.id, "third", {})


def test_worker_renews_lease_while_delivery_is_slow(repo):
    from router_gateway.worker import run_once

    job = repo.create_job("trial", None, {})

    def poll(job_id):
        time.sleep(1.3)
        repo.update_job(job_id, status="succeeded")

    assert run_once(SimpleNamespace(poll_job=poll), repo, limit=1, lease_seconds=1) == 1
    assert repo.get_job(job.id).status == "succeeded"
