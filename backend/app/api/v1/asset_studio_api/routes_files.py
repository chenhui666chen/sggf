"""首页资产工作台 API。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from math import gcd
import mimetypes
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.models.user import User
from app.services.audiobook.ai_music import MusicGenerationRequest, MusicStyle, create_music_generator
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

from app.api.v1.asset_studio_api import router
from app.api.v1.asset_studio_api._constants import *
from app.api.v1.asset_studio_api._helpers import *
from app.api.v1.asset_studio_api._helpers import _resolve_output_file

@router.get("/files/{file_path:path}")
def get_asset_studio_output_file(file_path: str):
    """读取资产工作台生成文件。

    这里不加鉴权，依赖随机文件名避免可枚举访问，方便前端 <img>/<video>/<audio> 直接加载。
    """

    resolved = _resolve_output_file(file_path)
    media_type, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(path=str(resolved), media_type=media_type or "application/octet-stream", filename=resolved.name)


