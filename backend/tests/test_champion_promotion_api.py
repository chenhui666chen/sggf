"""
冠军晋升 / 回滚 / 推荐查询管理员 API（设计文档 §8.3 / §10 · §14 第 9 步 · 子块 C）

覆盖：
- 契约：三个新端点（推荐查询 / 晋升执行 / 回滚）均挂 require_admin；请求/响应模型字段；
- 集成（sqlite + dependency override）：端点确实把子块 B 的服务层接线正确并序列化：
  晋升达标 / 硬闸门未过 / 非 returnable / 回滚成功 / 回滚目标不存在 / 推荐查询列出 returnable。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
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

from app.api.v1.prompt_evolution import (
    ChampionRecommendationResponse,
    PromoteChampionRequest,
    PromoteChampionResponse,
    RollbackChampionRequest,
    RollbackChampionResponse,
    router as pe_router,
)
from app.core.permissions import require_admin
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.prompt_experiment import (
    PromptChallenger,
    PromptChampionAssignment,
    PromptExperiment,
)
from app.models.role import Role
from app.models.user import User
from app.services.prompt_evolution.challenger_repository import ChallengerRepository
from app.services.prompt_evolution.champion_assignment_repository import (
    ChampionAssignmentRepository,
)
from app.services.prompt_evolution.experiment_repository import ExperimentRepository
from app.services.prompt_evolution.review_verdict import (
    VERDICT_CONFIRMED_WIN,
    VERDICT_LOSS,
)

POLICY = "experiment-policy-v1"
GENRE = "玄幻"


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

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

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
    PromptExperiment.__table__.create(bind=engine)
    PromptChampionAssignment.__table__.create(bind=engine)
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


def _seed_challenger(session_local, challenger_id, *, serving_mode="returnable", genre=GENRE):
    db = session_local()
    try:
        chal_repo = ChallengerRepository(db)
        row = chal_repo.upsert_challenger(
            challenger_id=challenger_id,
            genre=genre,
            prompt_text="改写提示词全文",
            prompt_hash=f"sha256:{challenger_id}",
            strategy_desc="降低连续同构句比例",
            strategy_family="sentence_structure",
            source_batch="evolution_20260730_01",
            offline_gate_passed=True,
            offline_scores={},
            serving_mode="shadow",
        )
        row.serving_mode = serving_mode
        db.commit()
    finally:
        db.close()


def _seed_outcomes(session_local, challenger_id, *, confirmed=0, loss=0, genre=GENRE, policy=POLICY):
    db = session_local()
    try:
        exp_repo = ExperimentRepository(db)
        specs = [(VERDICT_CONFIRMED_WIN, confirmed), (VERDICT_LOSS, loss)]
        idx = 0
        for outcome, count in specs:
            for _ in range(count):
                exp_id = f"exp_{challenger_id}_{idx}"
                exp_repo.create_experiment(
                    experiment_id=exp_id,
                    request_id=f"req_{challenger_id}_{idx}",
                    challenger_id=challenger_id,
                    genre=genre,
                    champion_id="champ",
                    assignment_bucket=1,
                    serving_mode="returnable",
                    resolved_model_id="m1",
                    model_selection_source="prompt_combination",
                    prompt_version_id="pv1",
                    provider_parameters_hash="ph1",
                    light_judge_version="lj-v1",
                    evaluation_policy_version=policy,
                    champion_prompt_hash="cph",
                    challenger_prompt_hash="chph",
                )
                exp_repo.record_settlement(
                    exp_id,
                    light_judge_result={},
                    returned_variant="challenger",
                    async_review_result={},
                    outcome=outcome,
                )
                idx += 1
        db.commit()
    finally:
        db.close()


# ---------------- 契约：require_admin + schema ----------------

def test_champion_endpoints_require_admin():
    protected = {
        "/api/v1/prompt-evolution/champion/recommendation",
        "/api/v1/prompt-evolution/champion/promote",
        "/api/v1/prompt-evolution/champion/rollback",
    }
    seen = set()
    for route in pe_router.routes:
        path = getattr(route, "path", None)
        if path not in protected:
            continue
        seen.add(path)
        dependency_names = {
            dep.call.__name__
            for dep in route.dependant.dependencies
            if dep.call is not None
        }
        assert "require_admin" in dependency_names, path
    assert seen == protected


def test_promote_request_response_schema():
    for field in ("genre", "challenger_id", "evaluation_policy_version", "gate_override", "override_reason", "reason", "light_judge_version"):
        assert field in PromoteChampionRequest.model_fields, field
    for field in ("promoted", "reason", "hard_gate_passed", "hard_gate_failures", "recommended", "recommend_failures", "prompt_version_id", "previous_version_id"):
        assert field in PromoteChampionResponse.model_fields, field


def test_rollback_request_response_schema():
    for field in ("genre", "target_version_id", "reason"):
        assert field in RollbackChampionRequest.model_fields, field
    for field in ("success", "reason", "prompt_version_id", "previous_version_id"):
        assert field in RollbackChampionResponse.model_fields, field


def test_recommendation_response_schema():
    for field in ("genre", "evaluation_policy_version", "count", "items"):
        assert field in ChampionRecommendationResponse.model_fields, field


# ---------------- 集成：晋升执行 ----------------

def test_promote_happy_path():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chA")
    _seed_outcomes(session_local, "chA", confirmed=70, loss=30)

    resp = client.post(
        "/api/v1/prompt-evolution/champion/promote",
        json={
            "genre": GENRE,
            "challenger_id": "chA",
            "evaluation_policy_version": POLICY,
            "reason": "达标晋升",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["promoted"] is True
    assert body["reason"] == "promoted"
    assert body["hard_gate_passed"] is True
    assert body["prompt_version_id"] == "chA"

    # 指针已落库
    db = session_local()
    try:
        current = ChampionAssignmentRepository(db).get_current(GENRE)
        assert current is not None and current.prompt_version_id == "chA"
        chal = ChallengerRepository(db).get_by_challenger_id("chA")
        assert chal.serving_mode == "champion"
    finally:
        db.close()


def test_promote_rejected_when_hard_gate_fails():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chB")
    _seed_outcomes(session_local, "chB", confirmed=3, loss=2)  # 有效样本 5 < 100

    resp = client.post(
        "/api/v1/prompt-evolution/champion/promote",
        json={
            "genre": GENRE,
            "challenger_id": "chB",
            "evaluation_policy_version": POLICY,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["promoted"] is False
    assert body["reason"] == "hard_gate_failed"
    assert body["hard_gate_passed"] is False
    assert "min_effective_samples" in body["hard_gate_failures"]


def test_promote_rejected_when_not_returnable():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chC", serving_mode="shadow")
    _seed_outcomes(session_local, "chC", confirmed=70, loss=30)

    resp = client.post(
        "/api/v1/prompt-evolution/champion/promote",
        json={
            "genre": GENRE,
            "challenger_id": "chC",
            "evaluation_policy_version": POLICY,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reason"] == "not_returnable"


def test_promote_override_without_reason_returns_400():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chD")
    _seed_outcomes(session_local, "chD", confirmed=3, loss=2)

    resp = client.post(
        "/api/v1/prompt-evolution/champion/promote",
        json={
            "genre": GENRE,
            "challenger_id": "chD",
            "evaluation_policy_version": POLICY,
            "gate_override": True,
        },
    )
    assert resp.status_code == 400, resp.text


# ---------------- 集成：回滚 ----------------

def test_rollback_happy_path():
    client, session_local = _build_client()
    # 用指针仓储制造历史：v1 → v2（当前）
    db = session_local()
    try:
        repo = ChampionAssignmentRepository(db)
        repo.switch_champion(GENRE, prompt_version_id="v1", prompt_hash="h1", operator="admin")
        db.commit()
        repo.switch_champion(GENRE, prompt_version_id="v2", prompt_hash="h2", operator="admin")
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/v1/prompt-evolution/champion/rollback",
        json={"genre": GENRE, "target_version_id": "v1", "reason": "线上异常回滚"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["prompt_version_id"] == "v1"

    db = session_local()
    try:
        current = ChampionAssignmentRepository(db).get_current(GENRE)
        assert current.prompt_version_id == "v1"
    finally:
        db.close()


def test_rollback_target_not_found_returns_404():
    client, session_local = _build_client()
    resp = client.post(
        "/api/v1/prompt-evolution/champion/rollback",
        json={"genre": GENRE, "target_version_id": "nope", "reason": "x"},
    )
    assert resp.status_code == 404, resp.text


# ---------------- 集成：推荐查询 ----------------

def test_recommendation_lists_returnable_challengers():
    client, session_local = _build_client()
    _seed_challenger(session_local, "chA")
    _seed_outcomes(session_local, "chA", confirmed=70, loss=30)
    _seed_challenger(session_local, "chE", serving_mode="shadow")  # 非 returnable，不应出现

    resp = client.get(
        "/api/v1/prompt-evolution/champion/recommendation",
        params={"genre": GENRE, "evaluation_policy_version": POLICY},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["genre"] == GENRE
    ids = {item["challenger_id"] for item in body["items"]}
    assert ids == {"chA"}
    item = body["items"][0]
    assert item["hard_gate_passed"] is True
    assert item["recommended"] is True
    assert item["effective_total"] == 100
