"""Workflow API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

from app.api.v1.workflow import routes_core
from app.api.v1.workflow import routes_status
from app.api.v1.workflow import routes_chapter
from app.api.v1.workflow import routes_expand
from app.api.v1.workflow import routes_optimize

_seen_paths = set()
for _mod in [routes_core, routes_status, routes_chapter, routes_expand, routes_optimize]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                route_key = (route.path, frozenset(route.methods))
                if route_key not in _seen_paths:
                    router.routes.append(route)
                    _seen_paths.add(route_key)
