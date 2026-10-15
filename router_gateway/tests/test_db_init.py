# -*- coding: utf-8 -*-
"""W1 数据库初始化测试：对一次性 sqlite 引擎验证幂等建表与仓储全链路可用。"""
from sqlalchemy import create_engine, inspect, text

from router_gateway.db import Base, JobRepository, make_session_factory
from router_gateway.db import init_db


def _spec():
    return {"prompt": "雪山日出", "duration_seconds": 5, "resolution": "480p",
            "aspect_ratio": "16:9", "mode": "text",
            "reference_images": [], "reference_videos": [],
            "reference_audios": []}


def test_init_schema创建metadata全部表且重复执行不报错不丢数据(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gateway.db'}")

    init_db.init_schema(engine)
    table_names = set(inspect(engine).get_table_names())
    assert table_names == set(Base.metadata.tables.keys())

    # 首次建表后写入一条 client，重复初始化不得报错也不得清数据
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO clients (id, name, api_key, enabled, balance, created_at) "
            "VALUES ('c1', '内测调用方', 'rg-first-key', 1, 0, CURRENT_TIMESTAMP)"))

    init_db.init_schema(engine)
    table_names_again = set(inspect(engine).get_table_names())
    assert table_names_again == set(Base.metadata.tables.keys())
    with engine.connect() as conn:
        enabled = conn.execute(
            text("SELECT enabled FROM clients WHERE api_key='rg-first-key'")).scalar()
    assert enabled == 1
    engine.dispose()


def test_空库初始化后仓储全链路可跑通(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chain.db'}")
    init_db.init_schema(engine)
    repo = JobRepository(make_session_factory(engine))

    job = repo.create_job(client_key="client-1", idempotency_key=None, spec=_spec())
    attempt = repo.add_attempt(
        job_id=job.id, seq=0, route_id="r1", provider="erchun",
        quote_amount="1.00", reason="expected_cost_min", is_hedge=False)
    repo.mark_attempt(attempt.id, status="submitted", upstream_task_id="up-1")
    repo.settle_attempt(attempt.id, status="succeeded", billing_status="settled",
                        content_url="https://example.com/a.mp4", cost="1.00")
    repo.record_event(route_id="r1", bucket="text|480p|5s", job_id=job.id,
                      attempt_id=attempt.id, success=True, elapsed_seconds=12.3)

    settled = repo.get_attempt(attempt.id)
    assert settled.status == "succeeded" and settled.cost is not None
    stats = repo.rolling_stats("r1", "text|480p|5s")
    assert stats.samples == 1 and stats.success_rate == 1.0
    engine.dispose()


def test_main从环境变量读取地址并完成建表(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "gateway_main.db"
    monkeypatch.setenv("ROUTER_GATEWAY_DATABASE_URL", f"sqlite:///{db_path}")

    init_db.main()

    assert "初始化完成" in capsys.readouterr().out
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        assert "clients" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_init_schema为旧clients表补齐客户级配额字段(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE clients ("
            "id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "api_key VARCHAR(128) NOT NULL UNIQUE, enabled BOOLEAN NOT NULL, "
            "balance NUMERIC(12, 4) NOT NULL, created_at TIMESTAMP NOT NULL)"))

    init_db.init_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("clients")}
    assert {
        "api_key_hash", "rate_limit_per_second", "burst_capacity",
        "max_active_jobs", "max_parallel_attempts", "daily_task_limit",
        "monthly_task_limit", "daily_budget", "monthly_budget",
    } <= columns
    engine.dispose()
