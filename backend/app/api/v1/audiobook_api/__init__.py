"""Audiobook API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/audiobook", tags=["audiobook"])

from app.api.v1.audiobook_api import routes_tts
from app.api.v1.audiobook_api import routes_projects
from app.api.v1.audiobook_api import routes_delete
from app.api.v1.audiobook_api import routes_tasks
from app.api.v1.audiobook_api import routes_download
from app.api.v1.audiobook_api import routes_script
from app.api.v1.audiobook_api import routes_segment_preview
from app.api.v1.audiobook_api import routes_segment_regen
from app.api.v1.audiobook_api import routes_review
from app.api.v1.audiobook_api import routes_subtitle
from app.api.v1.audiobook_api import routes_smart_chunk
from app.api.v1.audiobook_api import routes_misc

# Sync routes from sub-modules
_seen = set()
for _mod in [routes_tts, routes_projects, routes_delete, routes_tasks, routes_download, routes_script, routes_segment_preview, routes_segment_regen, routes_review, routes_subtitle, routes_smart_chunk, routes_misc]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                key = (route.path, frozenset(route.methods))
                if key not in _seen:
                    router.routes.append(route)
                    _seen.add(key)
