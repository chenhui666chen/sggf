from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.ai_trace import router
from app.api.v1.prompt_evolution import router as prompt_evolution_router


def test_model_management_routes_require_admin_dependency():
    protected_paths = {
        "/api/v1/ai-trace/model-config",
        "/api/v1/ai-trace/available-models",
        "/api/v1/ai-trace/evaluate-models",
        "/api/v1/ai-trace/evaluation-metrics",
        "/api/v1/ai-trace/model-combinations",
        "/api/v1/ai-trace/background-status",
    }
    for route in router.routes:
        if getattr(route, "path", None) not in protected_paths:
            continue
        dependency_names = {
            dependency.call.__name__
            for dependency in route.dependant.dependencies
            if dependency.call is not None
        }
        assert "require_admin" in dependency_names, route.path


def test_reduce_remains_available_to_authenticated_non_admin_users():
    route = next(item for item in router.routes if item.path == "/api/v1/ai-trace/reduce")
    dependency_names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
    assert "get_current_user" in dependency_names
    assert "require_admin" not in dependency_names


def test_reduce_response_exposes_returned_variant_field():
    # 子块 C：reduce 响应新增 returned_variant，未做 returnable 评估时默认 None
    from app.api.v1.ai_trace import ReduceResponse

    assert "returned_variant" in ReduceResponse.model_fields
    assert ReduceResponse(success=True).returned_variant is None


def test_prompt_evolution_task_controls_require_admin():
    protected_paths = {
        "/api/v1/prompt-evolution/start",
        "/api/v1/prompt-evolution/stop",
        "/api/v1/prompt-evolution/resume",
    }
    for route in prompt_evolution_router.routes:
        if getattr(route, "path", None) not in protected_paths:
            continue
        dependency_names = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "require_admin" in dependency_names, route.path
