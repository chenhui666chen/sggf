"""Dreamweaver API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/dreamweaver", tags=["dreamweaver"])

from app.api.v1.dreamweaver_api import routes_run
from app.api.v1.dreamweaver_api import routes_task
from app.api.v1.dreamweaver_api import routes_library
from app.api.v1.dreamweaver_api import routes_project
from app.api.v1.dreamweaver_api import routes_script
from app.api.v1.dreamweaver_api import routes_video

# Sync routes from sub-modules
_seen = set()
for _mod in [routes_run, routes_task, routes_library, routes_project, routes_script, routes_video]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                key = (route.path, frozenset(route.methods))
                if key not in _seen:
                    router.routes.append(route)
                    _seen.add(key)
