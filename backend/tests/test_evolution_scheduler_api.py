"""
进化调度器状态面板 / 手动休眠唤醒管理员 API（设计文档 §11 · §14 第 10 步 · 子块 C）

覆盖：
- 契约：三个新端点（状态快照 / 手动休眠 / 手动唤醒）均挂 require_admin；请求/响应模型字段；
- 集成（tmp_path + dependency override）：
  状态快照列出全部题材（默认 running）/ 反映已落盘的 sleeping/awake /
  手动休眠置 sleeping 并落盘 / 手动唤醒置 awake 并落盘 / 未知题材 400。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for _path in (BACKEND_ROOT, PROJECT_ROOT):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.prompt_evolution import (
    EVOLUTION_GENRES,
    SchedulerManualRequest,
    SchedulerManualResponse,
    SchedulerStateSnapshotResponse,
    get_scheduler_state_store,
    router as pe_router,
)
from app.core.security import get_current_user
from app.models.role import Role
from app.models.user import User
from app.services.prompt_evolution.evolution_scheduler import (
    STATE_AWAKE,
    STATE_RUNNING,
    STATE_SLEEPING,
)
from app.services.prompt_evolution.scheduler_state import SchedulerStateStore

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


def _build_client(state_dir: Path):
    app = FastAPI()
    app.include_router(pe_router)
    app.dependency_overrides[get_current_user] = _build_admin_user
    app.dependency_overrides[get_scheduler_state_store] = lambda: SchedulerStateStore(
        storage_dir=str(state_dir)
    )
    return CompatTestClient(app)


# ---------------- 契约：require_admin + schema ----------------

def test_scheduler_endpoints_require_admin():
    protected = {
        "/api/v1/prompt-evolution/scheduler/state",
        "/api/v1/prompt-evolution/scheduler/sleep",
        "/api/v1/prompt-evolution/scheduler/wake",
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


def test_snapshot_response_schema():
    for field in ("count", "items"):
        assert field in SchedulerStateSnapshotResponse.model_fields, field


def test_manual_request_response_schema():
    for field in ("genre", "reason"):
        assert field in SchedulerManualRequest.model_fields, field
    for field in ("genre", "state", "reasons", "updated_at", "last_tick_at"):
        assert field in SchedulerManualResponse.model_fields, field


# ---------------- 集成：状态快照 ----------------

def test_snapshot_lists_all_genres_default_running(tmp_path):
    client = _build_client(tmp_path)
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == len(EVOLUTION_GENRES)
    genres = {item["genre"] for item in body["items"]}
    assert genres == set(EVOLUTION_GENRES)
    for item in body["items"]:
        assert item["state"] == STATE_RUNNING
        assert item["updated_at"] is None


def test_snapshot_reflects_persisted_state(tmp_path):
    # 预置一条 sleeping 记录
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["marginal_gain_exhausted"], now="2026-07-25T00:00:00+00:00")

    client = _build_client(tmp_path)
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    item = next(i for i in body["items"] if i["genre"] == GENRE)
    assert item["state"] == STATE_SLEEPING
    assert item["reasons"] == ["marginal_gain_exhausted"]
    assert item["updated_at"] == "2026-07-25T00:00:00+00:00"


# ---------------- 集成：手动休眠 ----------------

def test_manual_sleep_sets_sleeping_and_persists(tmp_path):
    client = _build_client(tmp_path)
    resp = client.post(
        "/api/v1/prompt-evolution/scheduler/sleep",
        json={"genre": GENRE, "reason": "临时停机维护"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["genre"] == GENRE
    assert body["state"] == STATE_SLEEPING
    assert "manual_sleep" in body["reasons"]
    assert "临时停机维护" in body["reasons"]
    assert body["updated_at"] is not None

    # 已落盘
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    assert store.get(GENRE).state == STATE_SLEEPING


def test_manual_sleep_without_reason(tmp_path):
    client = _build_client(tmp_path)
    resp = client.post(
        "/api/v1/prompt-evolution/scheduler/sleep",
        json={"genre": GENRE},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == STATE_SLEEPING
    assert body["reasons"] == ["manual_sleep"]


def test_manual_sleep_unknown_genre_returns_400(tmp_path):
    client = _build_client(tmp_path)
    resp = client.post(
        "/api/v1/prompt-evolution/scheduler/sleep",
        json={"genre": "不存在题材"},
    )
    assert resp.status_code == 400, resp.text


# ---------------- 集成：手动唤醒 ----------------

def test_manual_wake_sets_awake_and_persists(tmp_path):
    # 先休眠再唤醒
    store = SchedulerStateStore(storage_dir=str(tmp_path))
    store.set(GENRE, STATE_SLEEPING, reasons=["marginal_gain_exhausted"], now="2026-07-25T00:00:00+00:00")

    client = _build_client(tmp_path)
    resp = client.post(
        "/api/v1/prompt-evolution/scheduler/wake",
        json={"genre": GENRE, "reason": "线上检测器换代"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["genre"] == GENRE
    assert body["state"] == STATE_AWAKE
    assert "manual_wake" in body["reasons"]
    assert "线上检测器换代" in body["reasons"]

    store2 = SchedulerStateStore(storage_dir=str(tmp_path))
    assert store2.get(GENRE).state == STATE_AWAKE


def test_manual_wake_unknown_genre_returns_400(tmp_path):
    client = _build_client(tmp_path)
    resp = client.post(
        "/api/v1/prompt-evolution/scheduler/wake",
        json={"genre": "不存在题材"},
    )
    assert resp.status_code == 400, resp.text


def test_sleep_then_snapshot_roundtrip(tmp_path):
    client = _build_client(tmp_path)
    client.post(
        "/api/v1/prompt-evolution/scheduler/sleep",
        json={"genre": GENRE},
    )
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    body = resp.json()
    item = next(i for i in body["items"] if i["genre"] == GENRE)
    assert item["state"] == STATE_SLEEPING


# ============ 题材常量单一来源（契约同一性） ============

def test_genre_lists_share_single_contract_source():
    # API 层与任务层必须引用契约模块的同一常量对象，杜绝双份维护漂移
    from app.services.prompt_evolution.experiment_contract import (
        EVOLUTION_GENRES as CONTRACT_GENRES,
    )
    from app.tasks.experiment_tasks import _SCHEDULER_GENRES

    assert EVOLUTION_GENRES is CONTRACT_GENRES
    assert _SCHEDULER_GENRES is CONTRACT_GENRES


# ============ 面板信号可观测性（signals 元数据） ============

def _build_client_with_signals(state_dir: Path, cache_dir: Path):
    from app.api.v1.prompt_evolution import (
        get_holdout_score_store,
        get_sentinel_state_store,
    )
    from app.services.prompt_evolution.holdout_probe import HoldoutScoreStore
    from app.services.prompt_evolution.sentinel_probe import SentinelStateStore

    app = FastAPI()
    app.include_router(pe_router)
    app.dependency_overrides[get_current_user] = _build_admin_user
    app.dependency_overrides[get_scheduler_state_store] = lambda: SchedulerStateStore(
        storage_dir=str(state_dir)
    )
    app.dependency_overrides[get_holdout_score_store] = lambda: HoldoutScoreStore(
        storage_dir=str(cache_dir)
    )
    app.dependency_overrides[get_sentinel_state_store] = lambda: SentinelStateStore(
        storage_dir=str(cache_dir)
    )
    return CompatTestClient(app)


def test_snapshot_signals_defaulted_when_no_cache(tmp_path):
    # 无缓存：面板必须能区分"降级默认值"而非误当真实信号
    client = _build_client_with_signals(tmp_path / "state", tmp_path / "cache")
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    assert resp.status_code == 200, resp.text
    for item in resp.json()["items"]:
        signals = item["signals"]
        assert signals["holdout"] == {
            "gap": 0.0, "computed_at": None, "stale": False, "defaulted": True,
        }
        assert signals["sentinel"] == {
            "degraded": False, "checked_at": None, "stale": False, "defaulted": True,
        }


def test_snapshot_signals_reflect_fresh_cache(tmp_path):
    from datetime import datetime, timezone

    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    from app.services.prompt_evolution.holdout_probe import HoldoutScoreStore
    from app.services.prompt_evolution.sentinel_probe import SentinelStateStore

    cache_dir = tmp_path / "cache"
    now_iso = datetime.now(timezone.utc).isoformat()
    HoldoutScoreStore(storage_dir=str(cache_dir)).set_record(
        GENRE,
        {"gap": 3.5, "policy": EXPERIMENT_EVALUATION_POLICY_VERSION, "computed_at": now_iso},
    )
    SentinelStateStore(storage_dir=str(cache_dir)).set_record(
        GENRE,
        {"degraded": True, "policy": EXPERIMENT_EVALUATION_POLICY_VERSION, "checked_at": now_iso},
    )

    client = _build_client_with_signals(tmp_path / "state", cache_dir)
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["genre"] == GENRE)
    assert item["signals"]["holdout"] == {
        "gap": 3.5, "computed_at": now_iso, "stale": False, "defaulted": False,
    }
    assert item["signals"]["sentinel"] == {
        "degraded": True, "checked_at": now_iso, "stale": False, "defaulted": False,
    }


def test_snapshot_signals_mark_stale_cache(tmp_path):
    from datetime import datetime, timedelta, timezone

    from app.services.prompt_evolution.experiment_contract import (
        EXPERIMENT_EVALUATION_POLICY_VERSION,
    )
    from app.services.prompt_evolution.holdout_probe import (
        HOLDOUT_GAP_MAX_AGE_HOURS,
        HoldoutScoreStore,
    )
    from app.services.prompt_evolution.sentinel_probe import (
        SENTINEL_STATE_MAX_AGE_HOURS,
        SentinelStateStore,
    )

    cache_dir = tmp_path / "cache"
    now = datetime.now(timezone.utc)
    stale_holdout_at = (now - timedelta(hours=HOLDOUT_GAP_MAX_AGE_HOURS + 1)).isoformat()
    stale_sentinel_at = (now - timedelta(hours=SENTINEL_STATE_MAX_AGE_HOURS + 1)).isoformat()
    HoldoutScoreStore(storage_dir=str(cache_dir)).set_record(
        GENRE,
        {"gap": 9.0, "policy": EXPERIMENT_EVALUATION_POLICY_VERSION,
         "computed_at": stale_holdout_at},
    )
    SentinelStateStore(storage_dir=str(cache_dir)).set_record(
        GENRE,
        {"degraded": True, "policy": EXPERIMENT_EVALUATION_POLICY_VERSION,
         "checked_at": stale_sentinel_at},
    )

    client = _build_client_with_signals(tmp_path / "state", cache_dir)
    resp = client.get("/api/v1/prompt-evolution/scheduler/state")
    assert resp.status_code == 200, resp.text
    item = next(i for i in resp.json()["items"] if i["genre"] == GENRE)
    # 超龄：真实消费值已降级，stale + defaulted 双标记，时间戳原样回显供排查
    assert item["signals"]["holdout"] == {
        "gap": 0.0, "computed_at": stale_holdout_at, "stale": True, "defaulted": True,
    }
    assert item["signals"]["sentinel"] == {
        "degraded": False, "checked_at": stale_sentinel_at, "stale": True, "defaulted": True,
    }
