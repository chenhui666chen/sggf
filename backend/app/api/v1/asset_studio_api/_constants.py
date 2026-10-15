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
from app.services.asset_studio_model_catalog import (
    get_asset_studio_audio_duration_options,
    get_asset_studio_default_model_id,
    get_asset_studio_model_sets,
    get_asset_studio_video_duration_options,
)
from core.model_catalog_runtime import get_model_catalog_runtime_index
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import UnifiedMediaResult, media_runtime

router = APIRouter(prefix="/api/v1/asset-studio", tags=["asset-studio"])

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ASSET_STUDIO_UPLOAD_DIR = PROJECT_ROOT / "backend" / "data" / "asset_studio_uploads"
ASSET_STUDIO_OUTPUT_DIR = PROJECT_ROOT / "backend" / "data" / "asset_studio_outputs"

_MODEL_SETS = get_asset_studio_model_sets()

IMAGE_GENERATION_MODELS = set(_MODEL_SETS["image_generation"])
IMAGE_EDIT_MODELS = set(_MODEL_SETS["image_edit"])
VIDEO_GENERATION_MODELS = set(_MODEL_SETS["video_generation"])
MOTION_MODELS = set(_MODEL_SETS["motion"])
VIDEO_EDIT_MODELS = set(_MODEL_SETS["video_edit"])
VIDEO_MODELS = set(VIDEO_GENERATION_MODELS | MOTION_MODELS | VIDEO_EDIT_MODELS)
VIDEO_EDIT_FEATURES = {"style-transfer", "video-extend", "video-remix"}
VISION_REVIEW_MODELS = set(_MODEL_SETS["vision_review"])
AUDIO_MODELS = set(_MODEL_SETS["audio_music"] | _MODEL_SETS["audio_sound_effect"] | _MODEL_SETS["audio_scene"])
SCENE_AUDIO_MODELS = set(_MODEL_SETS["audio_scene"])
SOUND_EFFECT_AUDIO_MODELS = set(_MODEL_SETS["audio_sound_effect"])
SPEECH_MODELS = set(_MODEL_SETS["audio_speech"])
VIDEO_DURATION_OPTIONS: dict[str, tuple[float, ...]] = get_asset_studio_video_duration_options()
AUDIO_DURATION_OPTIONS: dict[str, tuple[int, ...]] = get_asset_studio_audio_duration_options()
DEFAULT_IMAGE_GENERATION_MODEL_ID = get_asset_studio_default_model_id("asset_studio_image_generation", "qwen-image-3.0")
DEFAULT_IMAGE_EDIT_MODEL_ID = get_asset_studio_default_model_id("asset_studio_image_edit", "qwen-image-3.0")
DEFAULT_VIDEO_GENERATION_MODEL_ID = get_asset_studio_default_model_id("asset_studio_video_generation", "wan3.0-video")
DEFAULT_VIDEO_EDIT_MODEL_ID = get_asset_studio_default_model_id("asset_studio_video_edit", "wan3.0-video")
DEFAULT_MOTION_MODEL_ID = get_asset_studio_default_model_id("asset_studio_motion", "wan3.0-video")
DEFAULT_AUDIO_MUSIC_MODEL_ID = get_asset_studio_default_model_id("asset_studio_audio_music", "mureka-o1-instrumental")
DEFAULT_AUDIO_SOUND_EFFECT_MODEL_ID = get_asset_studio_default_model_id("asset_studio_audio_sound_effect", "seed-audio-1.0")
DEFAULT_AUDIO_SCENE_MODEL_ID = get_asset_studio_default_model_id("asset_studio_audio_scene", "seed-audio-1.0")
DEFAULT_AUDIO_SPEECH_MODEL_ID = get_asset_studio_default_model_id("asset_studio_audio_speech", "qwen-audio-3.1-tts-flash")
DEFAULT_VISION_REVIEW_MODEL_ID = get_asset_studio_default_model_id("asset_studio_vision_review", "qwen3.8-omni-flash")
IMAGE_FILE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_FILE_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
ALLOWED_OUTPUT_FILE_SUFFIXES = {
    *IMAGE_FILE_SUFFIXES,
    *VIDEO_FILE_SUFFIXES,
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".m4a",
}
DEFAULT_OUTPUT_SUFFIXES = {
    "image": ".png",
    "video": ".mp4",
    "motion": ".mp4",
    "video_edit": ".mp4",
    "audio": ".mp3",
}
MEDIA_KIND_BY_RESULT_KIND = {
    "image": "image",
    "video": "video",
    "motion": "video",
    "video_edit": "video",
    "audio": "audio",
}
MUSIC_STYLE_ALIASES: dict[str, MusicStyle] = {
    "流行": MusicStyle.POP,
    "pop": MusicStyle.POP,
    "摇滚": MusicStyle.ROCK,
    "rock": MusicStyle.ROCK,
    "爵士": MusicStyle.JAZZ,
    "jazz": MusicStyle.JAZZ,
    "古典": MusicStyle.CLASSICAL,
    "classical": MusicStyle.CLASSICAL,
    "国风": MusicStyle.CHINESE_STYLE,
    "chinese_style": MusicStyle.CHINESE_STYLE,
    "电子": MusicStyle.ELECTRONIC,
    "electronic": MusicStyle.ELECTRONIC,
    "氛围": MusicStyle.AMBIENT,
    "ambient": MusicStyle.AMBIENT,
    "管弦乐": MusicStyle.ORCHESTRAL,
    "orchestral": MusicStyle.ORCHESTRAL,
    "钢琴": MusicStyle.PIANO,
    "piano": MusicStyle.PIANO,
    "悬疑": MusicStyle.SUSPENSE,
    "suspense": MusicStyle.SUSPENSE,
    "浪漫": MusicStyle.ROMANTIC,
    "romantic": MusicStyle.ROMANTIC,
    "史诗": MusicStyle.EPIC,
    "epic": MusicStyle.EPIC,
    "民谣": MusicStyle.FOLK,
    "folk": MusicStyle.FOLK,
    "影视配乐": MusicStyle.SOUNDTRACK,
    "soundtrack": MusicStyle.SOUNDTRACK,
}
VISION_REVIEW_CRITERIA: dict[str, list[str]] = {
    "image": ["clarity", "composition", "lighting", "color", "style"],
    "video": ["clarity", "smoothness", "consistency", "lighting", "color"],
}
VISION_CRITERION_LABELS = {
    "clarity": "清晰度",
    "composition": "构图",
    "lighting": "光影",
    "color": "色彩",
    "style": "风格一致性",
    "smoothness": "运动流畅度",
    "consistency": "主体一致性",
}
VISION_CRITERION_ALIASES = {
    "sharpness": "clarity",
    "detail": "clarity",
    "details": "clarity",
    "framing": "composition",
    "shot_composition": "composition",
    "colour": "color",
    "colors": "color",
    "palette": "color",
    "style_consistency": "style",
    "motion": "smoothness",
    "motion_smoothness": "smoothness",
    "temporal_consistency": "consistency",
    "character_consistency": "consistency",
    "连续性": "consistency",
    "一致性": "consistency",
    "清晰度": "clarity",
    "构图": "composition",
    "光影": "lighting",
    "色彩": "color",
    "风格": "style",
    "流畅度": "smoothness",
}
VISION_CRITERION_PROMPT_HINTS = {
    "clarity": "补充主体清晰、边缘锐利、焦点准确、细节完整，避免模糊、重影和失焦。",
    "composition": "补充构图稳定、主体完整、主次分明、前中后景分层，避免画面拥挤和裁切。",
    "lighting": "补充主光源明确、明暗层次自然、曝光平衡，避免过曝、欠曝和光线混乱。",
    "color": "补充综合色彩统一、肤色自然、材质色温一致，避免偏色、脏灰和色彩断层。",
    "style": "补充风格统一、材质表达稳定、画面质感一致，避免风格跳变。",
    "smoothness": "补充动作连贯、过渡平滑、镜头稳定，避免跳帧、抖动和突兀运动。",
    "consistency": "补充主体造型一致、服饰与场景连续、角色特征稳定，避免人物漂移和细节突变。",
}
VISION_CRITERION_NEGATIVE_HINTS = {
    "clarity": "模糊、重影、失焦",
    "composition": "截肢构图、主体残缺、画面拥挤",
    "lighting": "过曝、欠曝、光线杂乱",
    "color": "偏色、脏灰、色彩断层",
    "style": "风格跳变、材质错乱",
    "smoothness": "抖动、跳帧、动作卡顿",
    "consistency": "人物漂移、造型不一致、服饰突变",
}
VISION_ISSUE_KEYWORD_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("模糊", "blur", "失焦", "重影"), VISION_CRITERION_PROMPT_HINTS["clarity"]),
    (("构图", "裁切", "主体不完整", "framing"), VISION_CRITERION_PROMPT_HINTS["composition"]),
    (("过曝", "欠曝", "曝光", "lighting"), VISION_CRITERION_PROMPT_HINTS["lighting"]),
    (("偏色", "色彩", "颜色", "colour", "color"), VISION_CRITERION_PROMPT_HINTS["color"]),
    (("风格", "材质", "style"), VISION_CRITERION_PROMPT_HINTS["style"]),
    (("抖动", "跳帧", "卡顿", "smooth"), VISION_CRITERION_PROMPT_HINTS["smoothness"]),
    (("一致性", "漂移", "角色变化", "consistency"), VISION_CRITERION_PROMPT_HINTS["consistency"]),
)


class AssetStudioMediaAsset(BaseModel):
    asset_uuid: str
    media_kind: str
    storage_mode: str
    source_uri: str
    preview_uri: str
    download_uri: str
    file_name: str
    mime_type: str | None = None
    file_size: int | None = None
    expires_at: datetime | None = None


class AssetStudioGenerateResponse(BaseModel):
    kind: str
    mode: str
    model_id: str
    assets: list[AssetStudioMediaAsset] = Field(default_factory=list)
    primary_asset: AssetStudioMediaAsset | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetStudioVisionCriterionScore(BaseModel):
    name: str
    label: str
    score: float | None = None
    comment: str | None = None


class AssetStudioVisionReviewResponse(BaseModel):
    kind: str
    mode: str
    model_id: str
    asset_type: str
    overall_score: float | None = None
    summary: str
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    prompt_suggestions: list[str] = Field(default_factory=list)
    revised_prompt: str
    criteria_scores: list[AssetStudioVisionCriterionScore] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

