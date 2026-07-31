"""
returnable 人工开闸管理员 API（设计文档 §5.4 / §14 第 8 步生产闭环）

覆盖：
- 契约：POST /challengers/{challenger_id}/returnable 挂 require_admin；
- 集成（sqlite + dependency override）：eligible 开闸成功 / 非 eligible 400 /
  挑战者不存在 404 / 审批原因缺失 422（审计必填）。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for _path in (BACKEND_ROOT, PROJECT_ROOT):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.prompt_evolution import router as pe_router
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.prompt_experiment import PromptChallenger, PromptChallengerStateTransition
from app.models.role import Role
from app.models.user import User
from app.services.prompt_evolution.challenger_repository import ChallengerRepository

GENRE = "玄幻"
APPROVE_PATH = "/api/v1/prompt-evolution/challengers/{challenger_id}/returnable"


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport, base_url=self._base_url, follow_redirects=True
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def _build_admin_user() -> User:
    user = User(
        id=1,
        username="prompt-admin",
        email="prompt-admin@example.com",
        password_hash="hash",
        is_active=True,
    )
    user.roles = [
        Role(id=1, name="Admin", code="admin", description="", is_active=True, is_system=False)
    ]
    return user


def _build_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    PromptChallenger.__table__.create(bind=engine)
    PromptChallengerStateTransition.__table__.create(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app = FastAPI()
    app.include_router(pe_router)
    app.dependency_overrides[get_current_user] = _build_admin_user

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return CompatTestClient(app), session_local


def _seed_challenger(session_local, challenger_id, *, serving_mode="eligible"):
    db = session_local()
    try:
        ChallengerRepository(db).upsert_challenger(
            challenger_id=challenger_id,
            genre=GENRE,
            prompt_text="改写提示词全文",
            prompt_hash=f"sha256:{challenger_id}",
            strategy_desc="降低连续同构句比例",
            strategy_family="sentence_structure",
            source_batch="evolution_20260730_01",
            offline_gate_passed=True,
            offline_scores={},
            serving_mode=serving_mode,
        )
        db.commit()
    finally:
        db.close()


# ---------------- 契约：require_admin ----------------

def _route_has_require_admin(route) -> bool:
    def _walk(dependant) -> bool:
        call = getattr(dependant, "call", None)
        if call is not None and getattr(call, "__name__", "") == "require_admin":
            return True
        return any(_walk(sub) for sub in dependant.dependencies)

    return _walk(route.dependant)


def test_approve_endpoint_requires_admin():
    target = "/api/v1/prompt-evolution/challengers/{challenger_id}/returnable"
    for route in pe_router.routes:
        if getattr(route, "path", None) == target:
            assert _route_has_require_admin(route)
            return
    raise AssertionError("开闸端点未注册")


# ---------------- 集成 ----------------

def test_approve_eligible_challenger_succeeds():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chg-a", serving_mode="eligible")
    resp = client.post(
        APPROVE_PATH.format(challenger_id="chg-a"), json={"reason": "首批小流量放量"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["challenger_id"] == "chg-a"
    assert body["genre"] == GENRE
    assert body["serving_mode"] == "returnable"
    # 落库持久生效 + 审计行（五轮评审①：operator 取登录管理员，与状态变更同事务）
    db = session_local()
    try:
        assert (
            ChallengerRepository(db).get_by_challenger_id("chg-a").serving_mode == "returnable"
        )
        audits = (
            db.query(PromptChallengerStateTransition)
            .filter_by(challenger_id="chg-a")
            .all()
        )
        assert len(audits) == 1
        assert audits[0].operator == "prompt-admin"
        assert audits[0].reason == "首批小流量放量"
        assert audits[0].from_mode == "eligible"
        assert audits[0].to_mode == "returnable"
    finally:
        db.close()


def test_approve_non_eligible_returns_400():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chg-b", serving_mode="shadow")
    resp = client.post(
        APPROVE_PATH.format(challenger_id="chg-b"), json={"reason": "误操作"}
    )
    assert resp.status_code == 400
    # 状态未被改动
    db = session_local()
    try:
        assert ChallengerRepository(db).get_by_challenger_id("chg-b").serving_mode == "shadow"
    finally:
        db.close()


def test_approve_missing_challenger_returns_404():
    client, _ = _build_client()
    resp = client.post(
        APPROVE_PATH.format(challenger_id="chg-nope"), json={"reason": "任意"}
    )
    assert resp.status_code == 404


def test_approve_blank_reason_returns_422():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chg-c", serving_mode="eligible")
    resp = client.post(APPROVE_PATH.format(challenger_id="chg-c"), json={"reason": ""})
    assert resp.status_code == 422
    # 五轮评审④：纯空白/换行同样无审计价值，不得混过 min_length=1
    resp = client.post(
        APPROVE_PATH.format(challenger_id="chg-c"), json={"reason": "  \r\n\t "}
    )
    assert resp.status_code == 422
    # 状态未被改动
    db = session_local()
    try:
        assert ChallengerRepository(db).get_by_challenger_id("chg-c").serving_mode == "eligible"
    finally:
        db.close()


def test_approve_overlong_reason_returns_422():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chg-d", serving_mode="eligible")
    # 上限对齐审计表 reason String(500)
    resp = client.post(
        APPROVE_PATH.format(challenger_id="chg-d"), json={"reason": "长" * 501}
    )
    assert resp.status_code == 422
    db = session_local()
    try:
        assert ChallengerRepository(db).get_by_challenger_id("chg-d").serving_mode == "eligible"
    finally:
        db.close()
