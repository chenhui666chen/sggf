from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@dataclass
class _FakeModel:
    id: str


class _FakeAdapter:
    def __init__(self, model_id: str, *, success: bool):
        self._model_id = model_id
        self._success = success
        self.spec = SimpleNamespace(get_fallback_for_error=lambda _error: None)

    def generate(self, _task):
        return SimpleNamespace(
            success=self._success,
            model_id=self._model_id,
            outputs=[f"{self._model_id}-output"] if self._success else [],
            metadata={"model_id": self._model_id},
            error=None if self._success else f"{self._model_id}-failed",
            error_code=None if self._success else "model_error",
            cost=0.2,
            latency=0.1,
        )


class _FakeRouter:
    def __init__(self, routing_result=None):
        self.routing_result = routing_result
        self.strategy_calls: list[tuple[str, int]] = []
        self.success_calls: list[str] = []
        self.failure_calls: list[str] = []

    def route_with_fallback_by_strategy(self, _task, strategy: str, max_fallbacks: int = 2):
        self.strategy_calls.append((strategy, max_fallbacks))
        if self.routing_result is None:
            raise AssertionError("route_with_fallback_by_strategy should not be called")
        return self.routing_result

    def record_success(self, model_id: str, latency: float, cost: float) -> None:
        self.success_calls.append(model_id)

    def record_failure(self, model_id: str, error_code: str) -> None:
        self.failure_calls.append(model_id)


def _build_task():
    from schemas.task_spec import TaskSpecBuilder

    return (
        TaskSpecBuilder()
        .with_modality("text_to_image")
        .with_prompt("hero portrait")
        .with_dimensions(1024, 1024)
        .build()
    )


def test_fallback_manager_uses_prefetched_candidates_before_reroute() -> None:
    from core.fallback_manager import FallbackManager
    from core.router import RoutingResult

    task = _build_task()
    routing_result = RoutingResult(
        selected_model=_FakeModel("primary-model"),
        fallback_models=[_FakeModel("secondary-model")],
        score=1.0,
    )
    router = _FakeRouter()
    manager = FallbackManager(router=router)

    adapters = {
        "primary-model": _FakeAdapter("primary-model", success=False),
        "secondary-model": _FakeAdapter("secondary-model", success=True),
    }

    success, result, chain = manager.execute_with_fallback(
        task=task,
        adapter_factory=lambda model_id: adapters.get(model_id),
        max_attempts=3,
        initial_routing_result=routing_result,
    )

    assert success is True
    assert result is not None
    assert result.model_id == "secondary-model"
    assert [attempt.model_id for attempt in chain.attempts] == ["primary-model", "secondary-model"]
    assert router.strategy_calls == []


def test_fallback_manager_respects_strategy_and_consumes_router_fallbacks() -> None:
    from core.fallback_manager import FallbackManager
    from core.router import RoutingResult

    task = _build_task()
    routing_result = RoutingResult(
        selected_model=_FakeModel("quality-primary"),
        fallback_models=[_FakeModel("quality-fallback")],
        score=1.0,
    )
    router = _FakeRouter(routing_result=routing_result)
    manager = FallbackManager(router=router)

    adapters = {
        "quality-primary": _FakeAdapter("quality-primary", success=False),
        "quality-fallback": _FakeAdapter("quality-fallback", success=True),
    }

    success, result, chain = manager.execute_with_fallback(
        task=task,
        adapter_factory=lambda model_id: adapters.get(model_id),
        max_attempts=3,
        strategy="quality",
    )

    assert success is True
    assert result is not None
    assert result.model_id == "quality-fallback"
    assert [attempt.model_id for attempt in chain.attempts] == ["quality-primary", "quality-fallback"]
    assert router.strategy_calls == [("quality", 2)]


def test_execution_engine_passes_routing_result_and_strategy_to_fallback_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.execution_engine import ExecutionEngine
    from core.router import RoutingResult
    import core.fallback_manager as fallback_module

    task = _build_task()
    routing_result = RoutingResult(
        selected_model=_FakeModel("prefetched-model"),
        fallback_models=[_FakeModel("prefetched-fallback")],
        score=1.0,
    )
    captured: dict[str, object] = {}

    class _FakeFallbackChain:
        def __init__(self) -> None:
            self.attempts = [object()]

        def get_last_attempt(self):
            return None

    class _FakeFallbackManager:
        def execute_with_fallback(self, **kwargs):
            captured.update(kwargs)
            return (
                True,
                SimpleNamespace(
                    model_id="prefetched-model",
                    outputs=["ok"],
                    metadata={"from": "fallback-manager"},
                    cost=0.2,
                    latency=0.1,
                ),
                _FakeFallbackChain(),
            )

    monkeypatch.setattr(fallback_module, "fallback_manager", _FakeFallbackManager())

    engine = ExecutionEngine(
        registry=SimpleNamespace(get_adapter=lambda _model_id: None, get_all_performance_stats=lambda: {}),
        router=SimpleNamespace(),
    )
    result = engine._execute_with_fallback(
        task=task,
        max_attempts=3,
        strategy="speed",
        routing_result=routing_result,
    )

    assert result.success is True
    assert result.model_id == "prefetched-model"
    assert captured["strategy"] == "speed"
    assert captured["initial_routing_result"] is routing_result


def test_execution_engine_single_execution_uses_prefetched_routing_result() -> None:
    from core.execution_engine import ExecutionEngine
    from core.router import RoutingResult

    task = _build_task()
    routing_result = RoutingResult(
        selected_model=_FakeModel("prefetched-model"),
        fallback_models=[],
        score=1.0,
    )
    registry = SimpleNamespace(
        get_adapter=lambda model_id: _FakeAdapter(model_id, success=True),
        get_all_performance_stats=lambda: {},
    )

    class _RouterShouldNotBeUsed:
        def route(self, _task):
            raise AssertionError("route should not be called when routing_result is provided")

        def route_by_strategy(self, _task, _strategy):
            raise AssertionError("route_by_strategy should not be called when routing_result is provided")

        def record_success(self, model_id: str, latency: float, cost: float) -> None:
            self.last_success = (model_id, latency, cost)

        def record_failure(self, model_id: str, error_code: str) -> None:
            raise AssertionError("record_failure should not be called for successful execution")

    router = _RouterShouldNotBeUsed()
    engine = ExecutionEngine(registry=registry, router=router)

    result = engine._execute_single(
        task=task,
        strategy="quality",
        routing_result=routing_result,
    )

    assert result.success is True
    assert result.model_id == "prefetched-model"
    assert result.trace["strategy"] == "quality"
    assert result.trace["resolved_model"] == "prefetched-model"
    assert result.trace["attempted_models"] == ["prefetched-model"]


def test_execution_engine_fallback_trace_includes_attempted_models_and_chain() -> None:
    from core.execution_engine import ExecutionEngine
    from core.router import RoutingResult

    task = _build_task()
    routing_result = RoutingResult(
        selected_model=_FakeModel("primary-model"),
        fallback_models=[_FakeModel("secondary-model")],
        score=1.0,
        strategy="balanced",
    )
    registry = SimpleNamespace(
        get_adapter=lambda model_id: {
            "primary-model": _FakeAdapter("primary-model", success=False),
            "secondary-model": _FakeAdapter("secondary-model", success=True),
        }.get(model_id),
        get_all_performance_stats=lambda: {},
    )
    router = _FakeRouter()
    engine = ExecutionEngine(registry=registry, router=router)

    result = engine._execute_with_fallback(
        task=task,
        max_attempts=3,
        strategy="balanced",
        routing_result=routing_result,
    )

    assert result.success is True
    assert result.model_id == "secondary-model"
    assert result.trace["attempted_models"] == ["primary-model", "secondary-model"]
    assert result.trace["fallback_chain"]["total_attempts"] == 2
    assert result.trace["fallback_chain"]["attempts"][0]["model_id"] == "primary-model"
    assert result.trace["fallback_chain"]["attempts"][1]["model_id"] == "secondary-model"


def test_base_adapter_records_prompt_trace() -> None:
    from adapters.base import BaseAdapter, GenerationResult

    class _BestPractice:
        prompt_template = "hero::{prompt}"

        @staticmethod
        def apply_prompt_template(prompt: str) -> str:
            return f"template::{prompt}"

    class _Spec:
        id = "trace-model"
        best_practice = _BestPractice()

        @staticmethod
        def can_handle(_task):
            return True, []

        @staticmethod
        def estimate_cost(_task):
            return 0.3

    class _TraceAdapter(BaseAdapter):
        def _init_client(self) -> None:
            pass

        def _optimize_prompt(self, task) -> str:
            return f"{task.prompt}::optimized"

        def _map_task_to_request(self, task):
            return {"prompt": task.prompt}

        def _call_api(self, request):
            return request

        def _parse_response(self, response, task):
            return GenerationResult(
                success=True,
                task_id=task.task_id,
                model_id=self.spec.id,
                outputs=[response["prompt"]],
                metadata={},
            )

        @classmethod
        def get_model_spec(cls):
            return _Spec()

    task = _build_task()
    adapter = _TraceAdapter(_Spec())

    result = adapter.generate(task)

    assert result.success is True
    assert result.trace["prompt"]["model_id"] == "trace-model"
    assert result.trace["prompt"]["prompt_before"] == "hero portrait"
    assert result.trace["prompt"]["prompt_after"] == "template::hero portrait::optimized"
    assert result.trace["prompt"]["prompt_changed"] is True
