from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response


ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = ROOT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

import app.api.v1.smart_dispatch as smart_dispatch_api
import core.execution_engine as execution_engine_module
import core.intent_parser as intent_parser_module
import core.router as router_module
from core.execution_engine import ExecutionResult
from core.intent_parser import IntentParseResult
from core.router import RoutingResult
from schemas.task_spec import TaskSpecBuilder


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


@dataclass
class _FakeQualityMetrics:
    overall_score: float = 8.8


@dataclass
class _FakeCostProfile:
    price: float = 0.12


@dataclass
class _FakeModel:
    id: str
    name: str
    provider: str
    modality: str = "text_to_image"
    quality_metrics: _FakeQualityMetrics = field(default_factory=_FakeQualityMetrics)
    avg_latency_seconds: float = 1.2
    cost_profile: _FakeCostProfile = field(default_factory=_FakeCostProfile)
    recommended_scenarios: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


class _StubParser:
    def __init__(self, result: IntentParseResult):
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def parse(self, user_input: str, context: dict[str, Any] | None, db_session=None):
        self.calls.append(
            {
                "user_input": user_input,
                "context": context,
                "db_session": db_session,
            }
        )
        return self._result


def build_test_client() -> tuple[CompatTestClient, object]:
    app = FastAPI()
    app.include_router(smart_dispatch_api.router)

    dummy_db = object()
    app.dependency_overrides[smart_dispatch_api.get_current_user] = lambda: object()
    app.dependency_overrides[smart_dispatch_api.get_db] = lambda: dummy_db
    return CompatTestClient(app), dummy_db


def _build_task():
    return (
        TaskSpecBuilder()
        .with_task_id("task-smart-dispatch")
        .with_modality("text_to_image")
        .with_prompt("江湖侠客海报")
        .with_dimensions(1024, 1024)
        .build()
    )


def _build_intent_result() -> IntentParseResult:
    task = _build_task()
    return IntentParseResult(
        raw_text="帮我生成一张江湖侠客海报",
        parsed_json={
            "modality": "text_to_image",
            "priority": "balanced",
            "extracted_prompt": task.prompt,
        },
        task_spec=task,
        confidence=0.92,
        parse_errors=[],
    )


def test_parse_intent_route_passes_db_session_to_parser(monkeypatch) -> None:
    parse_result = _build_intent_result()
    parser = _StubParser(parse_result)
    monkeypatch.setattr(intent_parser_module, "get_intent_parser", lambda: parser)

    client, dummy_db = build_test_client()
    response = client.post(
        "/api/v1/smart-dispatch/parse-intent",
        json={
            "user_input": "帮我生成一张江湖侠客海报",
            "context": {"project_type": "cover"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["parsed_json"]["modality"] == "text_to_image"
    assert data["task_spec"]["task_id"] == parse_result.task_spec.task_id
    assert parser.calls == [
        {
            "user_input": "帮我生成一张江湖侠客海报",
            "context": {"project_type": "cover"},
            "db_session": dummy_db,
        }
    ]


def test_dispatch_route_reuses_prefetched_routing_result_and_strategy(monkeypatch) -> None:
    parse_result = _build_intent_result()
    parser = _StubParser(parse_result)
    primary_model = _FakeModel(
        id="primary-image-model",
        name="Primary Image Model",
        provider="aliyun",
        recommended_scenarios=["poster"],
        tags=["quality"],
    )
    fallback_model = _FakeModel(
        id="fallback-image-model",
        name="Fallback Image Model",
        provider="aliyun",
        recommended_scenarios=["poster"],
        tags=["fallback"],
    )
    routing_result = RoutingResult(
        selected_model=primary_model,
        fallback_models=[fallback_model],
        score=0.96,
        base_score=0.9,
        semantic_boost=0.06,
        reasons=["quality strategy matched"],
    )
    captured: dict[str, Any] = {}

    def _route(task, strategy: str, max_fallbacks: int = 2):
        captured["route_task"] = task
        captured["route_strategy"] = strategy
        captured["route_max_fallbacks"] = max_fallbacks
        return routing_result

    def _execute(*, task, strategy: str, use_fallback: bool, routing_result=None):
        captured["execute_task"] = task
        captured["execute_strategy"] = strategy
        captured["execute_use_fallback"] = use_fallback
        captured["execute_routing_result"] = routing_result
        return ExecutionResult(
            success=True,
            task_id=task.task_id,
            model_id=routing_result.selected_model.id,
            outputs=["https://example.com/output.png"],
            metadata={"source": "stub-engine"},
            cost=0.42,
            latency=1.5,
            attempts=1,
        )

    monkeypatch.setattr(intent_parser_module, "get_intent_parser", lambda: parser)
    monkeypatch.setattr(router_module.router, "route_with_fallback_by_strategy", _route)
    monkeypatch.setattr(execution_engine_module.engine, "execute", _execute)

    client, dummy_db = build_test_client()
    response = client.post(
        "/api/v1/smart-dispatch/dispatch",
        json={
            "user_input": "帮我生成一张江湖侠客海报",
            "context": {"project_type": "cover"},
            "strategy": "quality",
            "use_fallback": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["routing"]["selected_model"] == "primary-image-model"
    assert data["routing"]["fallback_models"] == ["fallback-image-model"]
    assert data["routing"]["score"] == 0.96
    assert data["execution"]["model_id"] == "primary-image-model"
    assert data["execution"]["metadata"]["source"] == "stub-engine"
    assert parser.calls[0]["db_session"] is dummy_db
    assert captured["route_task"] is parse_result.task_spec
    assert captured["route_strategy"] == "quality"
    assert captured["route_max_fallbacks"] == 2
    assert captured["execute_task"] is parse_result.task_spec
    assert captured["execute_strategy"] == "quality"
    assert captured["execute_use_fallback"] is True
    assert captured["execute_routing_result"] is routing_result


def test_recommend_models_route_uses_strategy_and_returns_candidates_in_order(monkeypatch) -> None:
    parse_result = _build_intent_result()
    parser = _StubParser(parse_result)
    selected_model = _FakeModel(
        id="cost-primary-model",
        name="Cost Primary Model",
        provider="aliyun",
        avg_latency_seconds=1.0,
        recommended_scenarios=["poster", "batch"],
        tags=["cost"],
    )
    fallback_model_1 = _FakeModel(
        id="cost-fallback-model-1",
        name="Cost Fallback Model 1",
        provider="volcengine",
        avg_latency_seconds=1.8,
        recommended_scenarios=["poster"],
        tags=["fallback"],
    )
    fallback_model_2 = _FakeModel(
        id="cost-fallback-model-2",
        name="Cost Fallback Model 2",
        provider="openai",
        avg_latency_seconds=2.1,
        recommended_scenarios=["poster"],
        tags=["fallback"],
    )
    routing_result = RoutingResult(
        selected_model=selected_model,
        fallback_models=[fallback_model_1, fallback_model_2],
        score=0.83,
        reasons=["cost strategy matched", "fallback chain available"],
    )
    captured: dict[str, Any] = {}

    def _route(task, strategy: str, max_fallbacks: int = 2):
        captured["task"] = task
        captured["strategy"] = strategy
        captured["max_fallbacks"] = max_fallbacks
        return routing_result

    monkeypatch.setattr(intent_parser_module, "get_intent_parser", lambda: parser)
    monkeypatch.setattr(router_module.router, "route_with_fallback_by_strategy", _route)

    client, dummy_db = build_test_client()
    response = client.post(
        "/api/v1/smart-dispatch/recommend-models",
        json={
            "user_input": "帮我生成一张江湖侠客海报",
            "context": {"project_type": "cover"},
            "strategy": "cost",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["recommended"]["model_id"] == "cost-primary-model"
    assert [candidate["model_id"] for candidate in data["candidates"]] == [
        "cost-primary-model",
        "cost-fallback-model-1",
        "cost-fallback-model-2",
    ]
    assert [candidate["score"] for candidate in data["candidates"]] == [0.83, 0.0, 0.0]
    assert data["reasons"] == ["cost strategy matched", "fallback chain available"]
    assert parser.calls[0]["db_session"] is dummy_db
    assert captured["task"] is parse_result.task_spec
    assert captured["strategy"] == "cost"
    assert captured["max_fallbacks"] == 3
