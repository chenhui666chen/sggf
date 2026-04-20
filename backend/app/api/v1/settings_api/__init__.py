"""Settings API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["settings"])

from app.api.v1.settings_api import routes_collections
from app.api.v1.settings_api import routes_items_list
from app.api.v1.settings_api import routes_items_crud
from app.api.v1.settings_api import routes_items_move
from app.api.v1.settings_api import routes_templates
from app.api.v1.settings_api import routes_project
from app.api.v1.settings_api import routes_graph
from app.api.v1.settings_api import routes_smart

# Sync routes from sub-modules
_seen = set()
for _mod in [routes_collections, routes_items_list, routes_items_crud, routes_items_move, routes_templates, routes_project, routes_graph, routes_smart]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                key = (route.path, frozenset(route.methods))
                if key not in _seen:
                    router.routes.append(route)
                    _seen.add(key)
