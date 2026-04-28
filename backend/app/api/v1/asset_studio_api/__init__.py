"""Asset studio API router package."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import routes_files
from app.api.v1.asset_studio_api import routes_audio
from app.api.v1.asset_studio_api import routes_image
from app.api.v1.asset_studio_api import routes_model_catalog
from app.api.v1.asset_studio_api import routes_video
from app.api.v1.asset_studio_api import routes_vision
from app.api.v1.asset_studio_api import routes_video_edit

# Sync routes from sub-modules
_seen = set()
for _mod in [routes_files, routes_audio, routes_image, routes_model_catalog, routes_video, routes_vision, routes_video_edit]:
    if hasattr(_mod, 'router') and _mod.router is not router:
        for route in list(_mod.router.routes):
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                key = (route.path, frozenset(route.methods))
                if key not in _seen:
                    router.routes.append(route)
                    _seen.add(key)
