from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.models.user import User
from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import router


@router.get("/model-catalog")
def get_asset_studio_model_catalog(
    current_user: User = Depends(get_current_user),
):
    del current_user
    return get_asset_studio_model_manifest()
