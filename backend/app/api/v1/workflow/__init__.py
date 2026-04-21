"""Workflow API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

from app.api.v1.workflow import routes_core
from app.api.v1.workflow import routes_status
from app.api.v1.workflow import routes_chapter
from app.api.v1.workflow import routes_expand
from app.api.v1.workflow import routes_optimize
from app.api.v1.workflow import story_resolve as _story_resolve_module
from app.api.v1.workflow.routes_optimize import (
    _create_generated_chapter,
    _extract_iteration_review_score,
    _load_project_chapter_context,
)
from app.api.v1.workflow.schemas import ExpandStoryRequest
from app.api.v1.workflow.story_resolve import (
    _build_concept_stage_character_prompts,
    _validate_story_framework_mode_switch,
)

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


def _normalize_concept_stage_characters_for_storage(*args, **kwargs):
    original_coordinator = _story_resolve_module.coordinator
    _story_resolve_module.coordinator = coordinator
    try:
        return _story_resolve_module._normalize_concept_stage_characters_for_storage(*args, **kwargs)
    finally:
        _story_resolve_module.coordinator = original_coordinator


__all__ = [
    "router",
    "coordinator",
    "ExpandStoryRequest",
    "_build_concept_stage_character_prompts",
    "_create_generated_chapter",
    "_extract_iteration_review_score",
    "_load_project_chapter_context",
    "_normalize_concept_stage_characters_for_storage",
    "_validate_story_framework_mode_switch",
]
