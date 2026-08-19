"""stale 任务自愈：后端启动时清理残留 running/pending 任务。

背景缺陷：任务以进程内 asyncio 协程执行，DB 中 running 状态跨进程无意义。
后端重启后残留 running 行永远卡住（任务 89 事件），前端轮询永无结果。
要求 lifespan 启动时将 running/pending 置为 failed 并注明原因。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for _path in (ROOT_DIR, PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.services.stale_task_cleaner import cleanup_stale_generation_tasks


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE generation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    task_type VARCHAR(50),
                    status VARCHAR(20),
                    error_message TEXT,
                    task_id VARCHAR(64),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        rows = [
            (1, "expand_story", "running", "t-running-1", None),
            (1, "generate_next_chapter", "pending", "t-pending-1", None),
            (1, "expand_story", "completed", "t-done-1", None),
            (2, "workflow_stage_content", "failed", "t-fail-1", "旧错误"),
        ]
        for project_id, task_type, status, task_id, error_message in rows:
            conn.execute(
                text(
                    "INSERT INTO generation_history (project_id, task_type, status, task_id, error_message) "
                    "VALUES (:project_id, :task_type, :status, :task_id, :error_message)"
                ),
                {
                    "project_id": project_id,
                    "task_type": task_type,
                    "status": status,
                    "task_id": task_id,
                    "error_message": error_message,
                },
            )
    with factory() as db:
        yield db
    engine.dispose()


def test_running_and_pending_marked_failed(session):
    cleaned = cleanup_stale_generation_tasks(session)
    assert cleaned == 2
    statuses = dict(
        session.execute(
            text("SELECT task_id, status FROM generation_history")
        ).fetchall()
    )
    assert statuses["t-running-1"] == "failed"
    assert statuses["t-pending-1"] == "failed"


def test_terminal_states_untouched(session):
    cleanup_stale_generation_tasks(session)
    rows = dict(
        session.execute(
            text("SELECT task_id, status FROM generation_history")
        ).fetchall()
    )
    assert rows["t-done-1"] == "completed"
    assert rows["t-fail-1"] == "failed"


def test_error_message_explains_restart(session):
    cleanup_stale_generation_tasks(session)
    messages = dict(
        session.execute(
            text("SELECT task_id, error_message FROM generation_history WHERE status='failed'")
        ).fetchall()
    )
    assert "服务重启" in messages["t-running-1"]
    assert messages["t-fail-1"] == "旧错误"  # 原有失败原因不被覆盖


def test_idempotent_no_stale_rows(session):
    assert cleanup_stale_generation_tasks(session) == 2
    assert cleanup_stale_generation_tasks(session) == 0
