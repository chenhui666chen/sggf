import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from router_gateway.db import ClientTaskLimitExceeded, Job, JobRepository
from router_gateway.db.init_db import init_schema
from router_gateway.loadtest import isolated_services


@pytest.mark.skipif(os.getenv("ROUTER_GATEWAY_LOCAL_DOCKER_TEST") != "1",
                   reason="仅显式启用本地一次性 Docker PostgreSQL 时运行")
def test_postgres_trial_quota_remains_atomic_under_parallel_requests():
    with isolated_services() as (engine, cache):
        repo = JobRepository(sessionmaker(engine, expire_on_commit=False))
        client = repo.create_client("trial", "local-test-key", lifetime_task_limit=3, max_active_jobs=100)

        def submit(index):
            try:
                return repo.create_job(client.id, str(index), {}).id
            except ClientTaskLimitExceeded:
                return None

        with ThreadPoolExecutor(max_workers=12) as pool:
            accepted = list(pool.map(submit, range(24)))
        assert len([item for item in accepted if item]) == 3
        with repo._sf() as session:
            assert session.query(func.count(Job.id)).scalar() == 3
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA legacy_release"))
        legacy_engine = create_engine(engine.url, connect_args={"options": "-csearch_path=legacy_release"})
        with legacy_engine.begin() as connection:
            connection.execute(text("CREATE TABLE clients (id VARCHAR(36) PRIMARY KEY, "
                "name VARCHAR(100) NOT NULL, api_key VARCHAR(128) NOT NULL UNIQUE, "
                "enabled BOOLEAN NOT NULL, balance NUMERIC(12,4) NOT NULL, created_at TIMESTAMPTZ NOT NULL)"))
            connection.execute(text("INSERT INTO clients VALUES ('old', 'old', 'old-key', true, 0, now())"))
        init_schema(legacy_engine)
        init_schema(legacy_engine)
        with legacy_engine.connect() as connection:
            assert connection.execute(text("SELECT lifetime_task_limit FROM clients WHERE id='old'")).scalar() == 100
        legacy_engine.dispose()
