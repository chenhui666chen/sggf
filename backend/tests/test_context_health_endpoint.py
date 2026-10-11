# -*- coding: utf-8 -*-
"""context-health 端点集成测试（④，依据第十轮外部审查）。

此前仅有 collector 级过滤测试（test_context_observability.py），未保护真实路由行为。
本文件用 TestClient + dependency_overrides 覆盖端点契约：
- 未认证请求 401（get_current_user 在查库前即拒绝，无需 Redis）；
- 非所属/不存在项目 404（_ensure_project_owned 按 id+user_id 过滤）；
- chapter_number + request_kind 联合过滤；
- limit 截断后 latest 仍为过滤集合中最新一条；
- 过滤结果为空时 latest 为 null；
- 不传过滤返回项目级全局 latest；
- 非法 chapter_number / limit 被 FastAPI 校验拦为 422，未知 request_kind 返回空集；
- 新增 output_status/output_reject_reason/retry_* 字段随 to_dict 透传到响应。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for path in (ROOT_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.settings_api import router as settings_router
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.project import Project
from app.models.user import User
from app.services.context_observability import ObservationBuilder

OWNER_ID = 1
OTHER_USER_ID = 2
OWNED_PROJECT_ID = 5101
OTHER_PROJECT_ID = 5102


def _build_app(*, authed: bool) -> tuple[FastAPI, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Project.__table__])

    app = FastAPI()
    app.include_router(settings_router)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    if authed:
        auth_user = User(
            id=OWNER_ID, username="ctx_owner", password_hash="hash", is_active=True
        )
        app.dependency_overrides[get_current_user] = lambda: auth_user
    return app, testing_session_local


def _seed_project(session_factory, project_id: int, *, owner_id: int = OWNER_ID) -> None:
    db = session_factory()
    try:
        db.add(
            Project(
                id=project_id,
                display_no=project_id,
                user_id=owner_id,
                title="上下文观测测试项目",
                status="draft",
                word_count=0,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_obs(
    project_id: int,
    chapter: int,
    kind: str,
    *,
    output_status: str | None = None,
    output_reject_reason: str = "",
    retry_attempted: bool = False,
    retry_status: str = "not_needed",
    fallback_to_previous_output: bool = False,
) -> None:
    b = (
        ObservationBuilder(project_id, chapter, kind)
        .set_model("qwen-plus")
        .set_online_llm_calls(1)
    )
    if output_status is not None:
        b.set_output_status(output_status, reject_reason=output_reject_reason)
    b.set_retry(
        attempted=retry_attempted,
        status=retry_status,
        fallback_to_previous=fallback_to_previous_output,
    )
    b.finish()


@pytest.fixture()
def authed():
    app, session_factory = _build_app(authed=True)
    return TestClient(app), session_factory


def test_context_health_requires_auth() -> None:
    # 未认证：不 override get_current_user，无凭证请求应在查库前返回 401
    app, _ = _build_app(authed=False)
    client = TestClient(app)
    resp = client.get(f"/api/v1/projects/{OWNED_PROJECT_ID}/context-health")
    assert resp.status_code == 401


def test_context_health_rejects_non_owned_project(authed) -> None:
    # 非所属项目按“不存在”处理 → 404（_ensure_project_owned 同时过滤 id 与 user_id）
    client, sf = authed
    _seed_project(sf, OTHER_PROJECT_ID, owner_id=OTHER_USER_ID)
    resp = client.get(f"/api/v1/projects/{OTHER_PROJECT_ID}/context-health")
    assert resp.status_code == 404


def test_context_health_missing_project_returns_404(authed) -> None:
    client, _ = authed
    resp = client.get("/api/v1/projects/99999999/context-health")
    assert resp.status_code == 404


def test_context_health_no_filter_returns_global_latest(authed) -> None:
    # 不传过滤：latest 为项目级全局最新一条（此处为最后落库的 chapter=2 plan）
    client, sf = authed
    pid = 6001
    _seed_project(sf, pid)
    _seed_obs(pid, 1, "plan")
    _seed_obs(pid, 1, "content")
    _seed_obs(pid, 2, "plan")
    resp = client.get(f"/api/v1/projects/{pid}/context-health")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["project_id"] == pid
    assert len(data["observations"]) == 3
    assert data["latest"]["request_kind"] == "plan"
    assert data["latest"]["chapter_number"] == 2


def test_context_health_joint_filter_chapter_and_kind(authed) -> None:
    # chapter_number + request_kind 联合过滤：observations 与 latest 均按条件返回
    client, sf = authed
    pid = 6002
    _seed_project(sf, pid)
    _seed_obs(pid, 1, "plan")
    _seed_obs(pid, 1, "content")
    _seed_obs(pid, 2, "content")
    resp = client.get(
        f"/api/v1/projects/{pid}/context-health",
        params={"chapter_number": 1, "request_kind": "content"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["observations"]) == 1
    assert data["observations"][0]["chapter_number"] == 1
    assert data["observations"][0]["request_kind"] == "content"
    assert data["latest"]["chapter_number"] == 1
    assert data["latest"]["request_kind"] == "content"


def test_context_health_limit_truncation_keeps_newest_latest(authed) -> None:
    # limit 截断后取最近 N 条，latest 仍为过滤/截断集合中最新一条
    client, sf = authed
    pid = 6003
    _seed_project(sf, pid)
    for ch in range(1, 6):  # 章节 1..5，均 content
        _seed_obs(pid, ch, "content")
    resp = client.get(f"/api/v1/projects/{pid}/context-health", params={"limit": 2})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["observations"]) == 2
    assert [o["chapter_number"] for o in data["observations"]] == [4, 5]
    assert data["latest"]["chapter_number"] == 5


def test_context_health_empty_filter_returns_null_latest(authed) -> None:
    # 过滤结果为空：observations=[] 且 latest=null（不得回退到全局 latest）
    client, sf = authed
    pid = 6004
    _seed_project(sf, pid)
    _seed_obs(pid, 1, "content")
    resp = client.get(
        f"/api/v1/projects/{pid}/context-health", params={"chapter_number": 99}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["observations"] == []
    assert data["latest"] is None


def test_context_health_unknown_request_kind_returns_empty(authed) -> None:
    # 未知 request_kind：无匹配 → 空集 + latest=null（不报错）
    client, sf = authed
    pid = 6005
    _seed_project(sf, pid)
    _seed_obs(pid, 1, "content")
    resp = client.get(
        f"/api/v1/projects/{pid}/context-health",
        params={"request_kind": "nonexistent_kind"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["observations"] == []
    assert data["latest"] is None


def test_context_health_invalid_chapter_number_returns_422(authed) -> None:
    # 非法 chapter_number（非整数）被 FastAPI 类型校验拦为 422
    client, sf = authed
    pid = 6006
    _seed_project(sf, pid)
    resp = client.get(
        f"/api/v1/projects/{pid}/context-health", params={"chapter_number": "abc"}
    )
    assert resp.status_code == 422


def test_context_health_invalid_limit_returns_422(authed) -> None:
    # limit 越界（ge=1）被校验拦为 422
    client, sf = authed
    pid = 6007
    _seed_project(sf, pid)
    resp = client.get(f"/api/v1/projects/{pid}/context-health", params={"limit": 0})
    assert resp.status_code == 422


def test_context_health_exposes_output_and_retry_fields(authed) -> None:
    # ②③：新增 output_status/output_reject_reason/retry_* 字段随 to_dict 透传到端点响应
    client, sf = authed
    pid = 6008
    _seed_project(sf, pid)
    _seed_obs(
        pid,
        1,
        "content",
        output_status="rejected",
        output_reject_reason="PlaceholderOutput",
        retry_attempted=True,
        retry_status="failed",
        fallback_to_previous_output=True,
    )
    resp = client.get(f"/api/v1/projects/{pid}/context-health")
    assert resp.status_code == 200, resp.text
    latest = resp.json()["latest"]
    assert latest["request_status"] == "ok"  # 调用成功
    assert latest["output_status"] == "rejected"  # 但输出被拒
    assert latest["output_reject_reason"] == "PlaceholderOutput"
    assert latest["retry_attempted"] is True
    assert latest["retry_status"] == "failed"
    assert latest["fallback_to_previous_output"] is True
