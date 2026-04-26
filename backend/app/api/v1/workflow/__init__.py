"""Workflow API router package."""
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

from app.api.v1.workflow import helpers as _helpers_module
from app.api.v1.workflow import routes_core
from app.api.v1.workflow import routes_status
from app.api.v1.workflow import routes_chapter
from app.api.v1.workflow import routes_expand
from app.api.v1.workflow import routes_optimize
from app.api.v1.workflow import story_helpers as _story_helpers_module
from app.api.v1.workflow import story_resolve as _story_resolve_module
from app.api.v1.workflow.helpers import (
    _build_iteration_review_prompt,
    _build_iteration_revision_prompt,
    _build_recent_chapter_assets_summary,
    _extract_project_title_from_concept,
    _get_safe_input_token_budget,
    _select_text_model_by_input_tokens,
)
from app.api.v1.workflow.routes_optimize import (
    _create_generated_chapter,
    _extract_iteration_review_score,
    _load_latest_chapter_plan,
    _load_project_chapter_context,
    _safe_db_rollback,
)
from app.api.v1.workflow.schemas import ExpandStoryRequest
from app.api.v1.workflow.story_helpers import (
    _build_task_start_response,
    _build_project_world_setting_context,
    _build_story_execution_task_kwargs,
    _ensure_project_owned,
    _normalize_story_request_text_fields,
)
from app.api.v1.workflow.story_resolve import (
    _build_concept_stage_character_prompts,
    _build_story_expansion_analysis,
    _build_story_written_chapter_preview,
    _normalize_story_character_sync_result,
    _prepare_story_execution_request,
    _resolve_story_volume_detail_config,
    _update_story_expansion_history_record,
    _validate_expand_story_request,
    _validate_story_framework_mode_switch,
)
from app.services.workflow_context_builder import WorkflowContextBuilder

_seen_paths = set()
for _mod in [routes_core, routes_status, routes_chapter, routes_expand, routes_optimize]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                route_key = (route.path, frozenset(route.methods))
                if route_key not in _seen_paths:
                    router.routes.append(route)
                    _seen_paths.add(route_key)


coordinator = routes_core.coordinator
asyncio = routes_expand.asyncio
ws_manager = routes_expand.ws_manager


def _sync_story_expansion_compat_symbols() -> None:
    """Keep package-level monkeypatch targets wired into the runtime modules."""
    routes_expand._build_story_expansion_analysis = _build_story_expansion_analysis
    routes_expand._build_task_start_response = _build_task_start_response
    routes_expand._build_story_written_chapter_preview = _build_story_written_chapter_preview
    routes_expand._ensure_project_owned = _ensure_project_owned
    routes_expand._normalize_story_request_text_fields = _normalize_story_request_text_fields
    routes_expand._prepare_story_execution_request = _prepare_story_execution_request
    routes_expand._update_story_expansion_history_record = _update_story_expansion_history_record
    routes_expand._validate_expand_story_request = _validate_expand_story_request
    routes_expand._validate_story_framework_mode_switch = _validate_story_framework_mode_switch
    routes_expand.coordinator = coordinator

    _story_resolve_module.coordinator = coordinator
    _story_helpers_module.execute_expand_story_task = execute_expand_story_task
    _helpers_module.asyncio = asyncio


def _normalize_concept_stage_characters_for_storage(*args, **kwargs):
    original_coordinator = _story_resolve_module.coordinator
    _story_resolve_module.coordinator = coordinator
    try:
        return _story_resolve_module._normalize_concept_stage_characters_for_storage(*args, **kwargs)
    finally:
        _story_resolve_module.coordinator = original_coordinator


async def analyze_expand_story(*args, **kwargs):
    _sync_story_expansion_compat_symbols()
    return await routes_expand.analyze_expand_story(*args, **kwargs)


async def expand_story(*args, **kwargs):
    _sync_story_expansion_compat_symbols()
    return await routes_expand.expand_story(*args, **kwargs)


async def execute_expand_story_task(*args, **kwargs):
    _sync_story_expansion_compat_symbols()
    return await routes_expand.execute_expand_story_task(*args, **kwargs)


__all__ = [
    "analyze_expand_story",
    "asyncio",
    "execute_expand_story_task",
    "expand_story",
    "router",
    "coordinator",
    "ws_manager",
    "ExpandStoryRequest",
    "HTTPException",
    "WorkflowContextBuilder",
    "_build_project_world_setting_context",
    "_build_task_start_response",
    "_build_story_execution_task_kwargs",
    "_build_concept_stage_character_prompts",
    "_build_iteration_review_prompt",
    "_build_iteration_revision_prompt",
    "_build_recent_chapter_assets_summary",
    "_build_story_expansion_analysis",
    "_build_story_written_chapter_preview",
    "_create_generated_chapter",
    "_ensure_project_owned",
    "_extract_project_title_from_concept",
    "_extract_iteration_review_score",
    "_get_safe_input_token_budget",
    "_load_project_chapter_context",
    "_load_latest_chapter_plan",
    "_normalize_concept_stage_characters_for_storage",
    "_normalize_story_request_text_fields",
    "_normalize_story_character_sync_result",
    "_prepare_story_execution_request",
    "_resolve_story_volume_detail_config",
    "_select_text_model_by_input_tokens",
    "_safe_db_rollback",
    "_update_story_expansion_history_record",
    "_validate_expand_story_request",
    "_validate_story_framework_mode_switch",
    "status",
]
