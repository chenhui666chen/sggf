from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.permissions import is_admin
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.audiobook.audio_asset_cloud_storage import (
    build_audio_library_public_url,
    delete_audio_library_object,
    get_audio_library_storage_driver,
    head_audio_library_object,
    is_audio_library_cloud_storage_enabled,
    list_audio_library_objects,
    upload_audio_library_asset,
)
from app.services.audiobook.audio_library_paths import get_audio_library_dir
from app.services.audiobook.audio_library_asset_repository import (
    audio_library_asset_to_record,
    list_audio_library_asset_records,
    replace_audio_library_asset_records,
    upsert_audio_library_asset,
)
from app.services.audiobook.audio_library_source_policy import is_allowed_sfx_source
from app.services.audiobook.audio_library_rating_service import (
    COMMUNITY_REJECTED_STATUS,
    get_audio_library_rating_summaries,
    is_community_rejected_status,
    submit_audio_library_rating,
)
from app.services.audiobook.sfx_metadata import normalize_sfx_semantics
from app.models.audio_library_asset import AudioLibraryAsset

from app.api.v1.audiobook_api import router

logger = logging.getLogger(__name__)

_DEFAULT_AUDIO_LIBRARY_OSS_PREFIX = "shared/audio_library"
_VALID_SFX_CATEGORIES = {"environment", "action", "emotion", "transition"}
_VALID_SFX_STYLES = {"cinematic", "realistic", "fantasy", "scifi", "horror", "peaceful", "intense"}
_ALLOWED_AUDIO_UPLOAD_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
_MAX_AUDIO_UPLOAD_BYTES = 50 * 1024 * 1024
_SFX_SCENE_KEYWORDS = {
    "indoor": (
        "室内", "屋内", "房间", "屋里", "门", "走廊", "大厅", "客厅", "卧室", "厨房",
        "书房", "办公室", "教室", "药铺", "殿", "宫", "旅店", "地下室", "地窖",
        "indoor", "room", "inside", "interior", "door",
    ),
    "outdoor": (
        "室外", "屋外", "街", "街道", "路上", "路边", "森林", "山", "野外", "田野",
        "雨", "风", "火", "树", "鸟", "城市", "人群", "市场", "广场", "河", "溪", "海", "湖",
        "outdoor", "nature", "forest", "city", "crowd", "market", "river", "sea", "fire", "wind",
    ),
    "battle": ("战斗", "打斗", "战场", "爆炸", "枪", "剑", "刀", "搏斗", "追杀", "冲锋", "battle", "combat", "fight", "war", "explosion"),
    "travel": ("车", "船", "火车", "列车", "马车", "飞机", "旅途", "路途", "旅行", "赶路", "行驶", "驶过", "travel", "train", "car", "ship", "plane", "road"),
    "mystery": ("侦探", "谜", "秘密", "暗号", "阴谋", "诡", "线索", "悬疑", "神秘", "mystery", "secret", "clue", "detective"),
    "romance": ("爱情", "拥抱", "亲吻", "婚礼", "温柔", "romance", "love", "kiss", "wedding"),
    "horror": ("恐怖", "惊悚", "诡异", "阴森", "鬼", "幽灵", "怪物", "nightmare", "horror"),
}


def _require_audio_library_admin(current_user: User) -> None:
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )


class SfxLibraryEntry(BaseModel):
    id: str
    name: str
    category: str
    style: str = ""
    file_path: str
    description: str
    tags: List[str]
    scenes: List[str] = []
    source: str
    source_id: str = ""
    source_url: str = ""
    author: str = ""
    author_url: str = ""
    license: str = ""
    license_url: str = ""
    license_version: str = ""
    license_commercial: Optional[bool] = None
    attribution_required: Optional[bool] = None
    attribution_text: str = ""
    quality_score: Optional[float] = None
    quality_grade: str = ""
    quality_status: str = ""
    storage_mode: str = ""
    storage_driver: str = ""
    cloud_uri: str = ""
    public_url: str = ""
    object_key: str = ""
    local_cache_path: str = ""
    asset_scope: str = ""
    retrieved_at: str = ""
    license_checked_at: str = ""
    rating_count: int = 0
    average_rating: float = 0.0
    user_rating: Optional[int] = None


class MusicLibraryEntry(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    prompt: str = ""
    tags: List[str] = []
    style: str = ""
    duration: float = 0.0
    tempo: str = ""
    mood: str = ""
    bucket: str = ""
    file_path: str
    source: str
    variant: Optional[int] = None
    source_id: str = ""
    source_url: str = ""
    author: str = ""
    author_url: str = ""
    license: str = ""
    license_url: str = ""
    license_version: str = ""
    license_commercial: Optional[bool] = None
    attribution_required: Optional[bool] = None
    attribution_text: str = ""
    quality_score: Optional[float] = None
    quality_grade: str = ""
    quality_status: str = ""
    storage_mode: str = ""
    storage_driver: str = ""
    cloud_uri: str = ""
    public_url: str = ""
    object_key: str = ""
    local_cache_path: str = ""
    asset_scope: str = ""
    retrieved_at: str = ""
    license_checked_at: str = ""
    rating_count: int = 0
    average_rating: float = 0.0
    user_rating: Optional[int] = None


class AudioLibraryRatingRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)


class LibraryStatsResponse(BaseModel):
    sfx_count: int
    sfx_categories: List[str]
    sfx_scenes: List[str] = []
    music_count: int
    music_styles: List[str]
    music_moods: List[str]


def _load_json_array(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取索引文件失败 %s: %s", path, exc)
        return []


def _resolve_audio_library_public_url(entry: dict[str, Any]) -> str:
    cloud_uri = str(entry.get("cloud_uri") or "").strip()
    public_url = str(entry.get("public_url") or "").strip()
    object_key = str(entry.get("object_key") or "").strip()
    storage_driver = str(entry.get("storage_driver") or "").strip()
    storage_mode = str(entry.get("storage_mode") or "").strip()

    if storage_driver == "dashscope_oss" or storage_mode == "durable_cloud" or cloud_uri.startswith("oss://"):
        resolved = build_audio_library_public_url(
            cloud_uri=cloud_uri,
            object_key=object_key,
            fallback_url=public_url,
            storage_driver=storage_driver,
        )
        if resolved:
            return resolved

    return public_url


def _hydrate_audio_library_public_urls(entries: list) -> list:
    hydrated: list = []
    for entry in entries:
        if not isinstance(entry, dict):
            hydrated.append(entry)
            continue
        hydrated_entry = dict(entry)
        resolved = _resolve_audio_library_public_url(hydrated_entry)
        if resolved:
            hydrated_entry["public_url"] = resolved
        hydrated.append(hydrated_entry)
    return hydrated


def _audio_library_media_type(file_path: Path) -> str:
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
    }
    return media_types.get(file_path.suffix.lower(), "application/octet-stream")


def _parse_audio_upload_tags(value: str) -> List[str]:
    normalized = str(value or "").replace("，", ",")
    tags: List[str] = []
    for item in normalized.split(","):
        tag = item.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:20]


def _validate_audio_upload_name(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="素材名称不能为空")
    if len(name) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="素材名称不能超过 100 个字符")
    if not any("\u4e00" <= char <= "\u9fff" for char in name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="素材名称请使用中文")
    return name


async def _save_audio_upload_atomic(upload: UploadFile, target_path: Path) -> tuple[int, str]:
    temp_path = target_path.with_name(f"{target_path.name}.part")
    digest = hashlib.sha256()
    total_size = 0
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("xb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > _MAX_AUDIO_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="音频文件不能超过 50MB",
                    )
                digest.update(chunk)
                output.write(chunk)
        if total_size <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="音频文件不能为空")
        os.replace(temp_path, target_path)
        return total_size, digest.hexdigest()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _canonical_sfx_category(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("\\", "/").strip("/")
    if not raw:
        return ""
    parts = [part for part in raw.split("/") if part]
    if not parts:
        return ""

    if parts[0] == "effects":
        parts = parts[1:]

    category = parts[0] if parts and parts[0] in _VALID_SFX_CATEGORIES else ""
    if not category:
        return raw

    style = ""
    if len(parts) > 1 and parts[1] in _VALID_SFX_STYLES:
        style = parts[1]
    elif raw.startswith("effects/"):
        style = "realistic"

    return f"{category}/{style}" if style else category


def _normalize_sfx_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_sfx_semantics(entry)
    category = _canonical_sfx_category(normalized.get("category"))
    if category:
        normalized["category"] = category
    if not normalized.get("style") and "/" in category:
        normalized["style"] = category.split("/", 1)[1]

    scenes = normalized.get("scenes")
    if isinstance(scenes, list):
        normalized["scenes"] = [str(item).strip() for item in scenes if str(item).strip()]
    elif isinstance(scenes, str):
        normalized["scenes"] = [item.strip() for item in scenes.split(",") if item.strip()]
    else:
        normalized["scenes"] = _infer_sfx_scenes(normalized)
    return normalized


def _infer_sfx_scenes(entry: Dict[str, Any]) -> List[str]:
    text_parts = [
        entry.get("name", ""),
        entry.get("description", ""),
        entry.get("category", ""),
        entry.get("file_path", ""),
        " ".join(str(tag) for tag in entry.get("tags", []) if tag),
    ]
    text = " ".join(str(part) for part in text_parts if part).lower()
    scenes: List[str] = []
    for scene, keywords in _SFX_SCENE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            scenes.append(scene)
    if scenes:
        return scenes
    category = str(entry.get("category") or "").lower()
    if category.startswith("environment"):
        return ["outdoor"]
    return ["general"]


def _sfx_category_matches(entry: Dict[str, Any], requested: str) -> bool:
    normalized_requested = str(requested or "").strip().lower().replace("\\", "/").strip("/")
    if not normalized_requested:
        return True
    raw_category = str(entry.get("category") or "").strip().lower().replace("\\", "/")
    canonical_category = _canonical_sfx_category(raw_category)
    return raw_category.startswith(normalized_requested) or canonical_category.startswith(normalized_requested)


def _sfx_scene_matches(entry: Dict[str, Any], requested: str) -> bool:
    normalized_requested = str(requested or "").strip().lower()
    if not normalized_requested:
        return True
    scenes = entry.get("scenes")
    if isinstance(scenes, list):
        return any(str(scene).strip().lower() == normalized_requested for scene in scenes)
    if isinstance(scenes, str):
        return any(scene.strip().lower() == normalized_requested for scene in scenes.split(","))
    return False


def _serialize_library_entries(entries: list, model_cls: type[BaseModel], library_type: str) -> list:
    """逐条序列化素材列表，单条脏数据只跳过并告警，不拖垮整个列表接口。"""
    serialized = []
    for entry in entries:
        try:
            serialized.append(model_cls(**entry))
        except Exception as exc:
            logger.warning(
                "素材条目序列化失败，已跳过: type=%s id=%s -> %s",
                library_type,
                entry.get("id") if isinstance(entry, dict) else entry,
                exc,
            )
    return serialized


def _load_library_entries(
    *,
    db: Session,
    base_dir: Path,
    library_type: str,
    index_name: str,
    include_disallowed_sfx_sources: bool = False,
) -> list:
    try:
        db_records = list_audio_library_asset_records(
            db,
            library_type,
            include_disallowed_sfx_sources=include_disallowed_sfx_sources,
        )
    except SQLAlchemyError as exc:
        logger.warning("读取音频素材数据库索引失败，回退 JSON 索引: %s", exc)
        db.rollback()
        db_records = []

    json_records = [
        entry
        for entry in _load_json_array(base_dir / index_name)
        if isinstance(entry, dict)
        and (
            library_type != "sfx"
            or include_disallowed_sfx_sources
            or is_allowed_sfx_source(entry.get("source"))
        )
    ]
    if not db_records:
        return _hydrate_audio_library_public_urls([
            record
            for record in json_records
            if not is_community_rejected_status(record.get("quality_status"))
        ])

    merged_records = list(db_records)
    known_asset_ids = {
        str(entry.get("id") or entry.get("asset_key") or entry.get("source_id") or "").strip()
        for entry in db_records
    }
    for entry in json_records:
        asset_id = str(entry.get("id") or entry.get("asset_key") or entry.get("source_id") or "").strip()
        if asset_id and asset_id not in known_asset_ids:
            merged_records.append(entry)
            known_asset_ids.add(asset_id)
    return _hydrate_audio_library_public_urls([
        record
        for record in merged_records
        if not is_community_rejected_status(record.get("quality_status"))
        and (
            library_type != "sfx"
            or include_disallowed_sfx_sources
            or is_allowed_sfx_source(record.get("source"))
        )
    ])


def _attach_audio_library_rating_summaries(
    db: Session,
    *,
    library_type: str,
    entries: list[Dict[str, Any]],
    user_id: int,
) -> list[Dict[str, Any]]:
    asset_keys = [
        str(entry.get("id") or "").strip()
        for entry in entries
        if str(entry.get("id") or "").strip()
    ]
    if not asset_keys:
        return entries
    try:
        assets = (
            db.query(AudioLibraryAsset)
            .filter(
                AudioLibraryAsset.library_type == library_type,
                AudioLibraryAsset.asset_key.in_(asset_keys),
            )
            .all()
        )
        summaries = get_audio_library_rating_summaries(
            db,
            assets=assets,
            user_id=user_id,
        )
    except SQLAlchemyError as exc:
        logger.warning("读取音频素材评分失败，返回无评分列表: %s", exc)
        db.rollback()
        summaries = {}

    enriched: list[Dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        summary = summaries.get(str(item.get("id") or ""), {})
        item["rating_count"] = int(summary.get("rating_count") or 0)
        item["average_rating"] = float(summary.get("average_score") or 0.0)
        item["user_rating"] = summary.get("user_score")
        enriched.append(item)
    return enriched


def _sync_community_rejected_to_json(
    *,
    base_dir: Path,
    library_type: str,
    asset_id: str,
    moderation_metadata: dict[str, Any],
) -> None:
    index_path = base_dir / _index_name_for_library_type(library_type)
    entries = [entry for entry in _load_json_array(index_path) if isinstance(entry, dict)]
    changed = False
    updated_entries: list[Dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        if _entry_asset_id(item) == asset_id:
            item["quality_status"] = COMMUNITY_REJECTED_STATUS
            metadata = dict(item.get("metadata_json") or {})
            metadata["community_moderation"] = dict(moderation_metadata)
            item["metadata_json"] = metadata
            changed = True
        updated_entries.append(item)
    if changed:
        _write_json_array_atomic(index_path, updated_entries)


@router.get(
    "/audio-library/stats",
    summary="获取音效库/音乐库统计",
)
async def get_audio_library_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base_dir = get_audio_library_dir()
    sfx_entries = _load_library_entries(
        db=db,
        base_dir=base_dir,
        library_type="sfx",
        index_name="sound_effects_index.json",
    )
    music_entries = _load_library_entries(
        db=db,
        base_dir=base_dir,
        library_type="music",
        index_name="music_index.json",
    )

    normalized_sfx_entries = [
        _normalize_sfx_entry(e)
        for e in sfx_entries
        if isinstance(e, dict)
    ]
    sfx_categories = sorted({e.get("category", "") for e in normalized_sfx_entries if e.get("category")})
    sfx_scenes = sorted({
        str(scene)
        for e in normalized_sfx_entries
        for scene in e.get("scenes", [])
        if str(scene).strip()
    })
    music_styles = sorted({e.get("style", "") for e in music_entries if e.get("style")})
    music_moods = sorted({e.get("mood", "") for e in music_entries if e.get("mood")})

    return LibraryStatsResponse(
        sfx_count=len(sfx_entries),
        sfx_categories=sfx_categories,
        sfx_scenes=sfx_scenes,
        music_count=len(music_entries),
        music_styles=music_styles,
        music_moods=music_moods,
    )


@router.get(
    "/audio-library/sound-effects",
    summary="浏览音效库",
)
async def browse_sound_effects(
    category: Optional[str] = Query(default=None, description="按分类筛选"),
    tag: Optional[str] = Query(default=None, description="按标签筛选"),
    scene: Optional[str] = Query(default=None, description="按适用场景筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base_dir = get_audio_library_dir()
    entries = _load_library_entries(
        db=db,
        base_dir=base_dir,
        library_type="sfx",
        index_name="sound_effects_index.json",
    )

    results = [
        _normalize_sfx_entry(e)
        for e in entries
        if isinstance(e, dict)
    ]
    if category:
        results = [e for e in results if _sfx_category_matches(e, category)]
    if tag:
        results = [e for e in results if tag in e.get("tags", [])]
    if scene:
        results = [e for e in results if _sfx_scene_matches(e, scene)]
    if search:
        search_lower = search.lower()
        results = [
            e for e in results
            if search_lower in e.get("name", "").lower()
            or search_lower in e.get("description", "").lower()
            or any(search_lower in t.lower() for t in e.get("tags", []))
            or any(search_lower in t.lower() for t in e.get("scenes", []))
        ]

    results = _attach_audio_library_rating_summaries(
        db,
        library_type="sfx",
        entries=results,
        user_id=current_user.id,
    )
    return _serialize_library_entries(results, SfxLibraryEntry, "sfx")


@router.get(
    "/audio-library/music",
    summary="浏览音乐库",
)
async def browse_music(
    style: Optional[str] = Query(default=None, description="按风格筛选"),
    mood: Optional[str] = Query(default=None, description="按情绪筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base_dir = get_audio_library_dir()
    entries = _load_library_entries(
        db=db,
        base_dir=base_dir,
        library_type="music",
        index_name="music_index.json",
    )

    results = entries
    if style:
        results = [e for e in results if e.get("style", "") == style]
    if mood:
        results = [e for e in results if e.get("mood", "") == mood]
    if search:
        search_lower = search.lower()
        results = [
            e for e in results
            if search_lower in e.get("name", "").lower()
            or search_lower in e.get("description", "").lower()
            or search_lower in e.get("style", "").lower()
            or search_lower in e.get("mood", "").lower()
            or search_lower in e.get("prompt", "").lower()
            or any(search_lower in str(tag).lower() for tag in e.get("tags", []))
        ]

    results = _attach_audio_library_rating_summaries(
        db,
        library_type="music",
        entries=results,
        user_id=current_user.id,
    )
    return _serialize_library_entries(results, MusicLibraryEntry, "music")


@router.post(
    "/audio-library/assets/upload",
    summary="上传共享音频素材",
)
async def upload_audio_library_file(
    library_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default=""),
    style: str = Form(default=""),
    mood: str = Form(default=""),
    tags: str = Form(default=""),
    license_commercial: bool = Form(default=False),
    rights_confirmed: bool = Form(default=False),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_type = str(library_type or "").strip().lower()
    if normalized_type not in {"sfx", "music"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="素材类型必须为 sfx 或 music")
    if not rights_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须确认拥有该音频的共享和使用授权",
        )

    normalized_name = _validate_audio_upload_name(name)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_AUDIO_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 mp3、wav、ogg、flac、m4a 音频文件",
        )
    content_type = str(file.content_type or "application/octet-stream").lower()
    if not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件必须是音频")

    asset_id = f"user_{normalized_type}_{uuid.uuid4().hex}"
    asset_subdir = "sound_effects/user_upload" if normalized_type == "sfx" else "music_cache/user_upload"
    relative_path = f"{asset_subdir}/{asset_id}{suffix}"
    base_dir = get_audio_library_dir()
    target_path = base_dir / relative_path
    index_path = base_dir / _index_name_for_library_type(normalized_type)
    index_existed = index_path.exists()
    previous_entries = [entry for entry in _load_json_array(index_path) if isinstance(entry, dict)]
    index_written = False
    storage_metadata: Dict[str, Any] = {}

    try:
        file_size, sha256 = await _save_audio_upload_atomic(file, target_path)
        storage_metadata = upload_audio_library_asset(
            local_path=target_path,
            relative_path=relative_path,
            library_type=normalized_type,
        )
        record: Dict[str, Any] = {
            "id": asset_id,
            "name": normalized_name,
            "description": str(description or "").strip(),
            "file_path": relative_path,
            "source": "user_upload",
            "author": str(current_user.username or "").strip(),
            "license": "用户授权共享",
            "license_commercial": bool(license_commercial),
            "attribution_required": False,
            "tags": _parse_audio_upload_tags(tags),
            "file_size": file_size,
            "sha256": sha256,
            "content_type": content_type,
            "asset_scope": "shared_library",
            "metadata_json": {
                "uploaded_by_user_id": current_user.id,
                "rights_confirmed": True,
            },
            **storage_metadata,
        }
        if normalized_type == "sfx":
            normalized_category = _canonical_sfx_category(category) or "action/realistic"
            record.update({
                "category": normalized_category,
                "style": str(style or "").strip() or (
                    normalized_category.split("/", 1)[1] if "/" in normalized_category else "realistic"
                ),
            })
            record["scenes"] = _infer_sfx_scenes(record)
        else:
            record.update({
                "style": str(style or "").strip() or "其他",
                "mood": str(mood or "").strip() or "其他",
                "duration": 0.0,
                "tempo": "",
                "bucket": "",
                "prompt": str(description or "").strip(),
            })

        upsert_audio_library_asset(db, normalized_type, record)
        db.flush()
        _write_json_array_atomic(index_path, [*previous_entries, record])
        index_written = True
        db.commit()
        return {"success": True, "asset": record}
    except HTTPException:
        db.rollback()
        if index_written:
            if index_existed:
                _write_json_array_atomic(index_path, previous_entries)
            else:
                index_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        if index_written:
            try:
                if index_existed:
                    _write_json_array_atomic(index_path, previous_entries)
                else:
                    index_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("恢复音频素材 JSON 索引失败")
        target_path.unlink(missing_ok=True)
        object_key = str(storage_metadata.get("object_key") or "").strip()
        if object_key:
            try:
                delete_audio_library_object(object_key=object_key)
            except Exception:
                logger.exception("清理上传失败后的云端音频素材失败")
        logger.exception("上传共享音频素材失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="上传共享音频素材失败",
        ) from exc
    finally:
        await file.close()


@router.post(
    "/audio-library/assets/{library_type}/{asset_id}/rating",
    summary="提交共享音频素材评分",
)
async def rate_audio_library_asset(
    library_type: str,
    asset_id: str,
    request: AudioLibraryRatingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_type = str(library_type or "").strip().lower()
    index_name = _index_name_for_library_type(normalized_type)
    normalized_asset_id = str(asset_id or "").strip()
    if not normalized_asset_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="asset_id is required")

    asset = (
        db.query(AudioLibraryAsset)
        .filter(
            AudioLibraryAsset.library_type == normalized_type,
            AudioLibraryAsset.asset_key == normalized_asset_id,
        )
        .with_for_update()
        .first()
    )
    if asset is None:
        base_dir = get_audio_library_dir()
        entries = [entry for entry in _load_json_array(base_dir / index_name) if isinstance(entry, dict)]
        entry = next((item for item in entries if _entry_asset_id(item) == normalized_asset_id), None)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在")
        asset = upsert_audio_library_asset(db, normalized_type, entry)
        db.flush()

    try:
        result = submit_audio_library_rating(
            db,
            asset=asset,
            user_id=current_user.id,
            score=request.score,
        )
        if result["auto_unpublished"]:
            moderation_metadata = dict(asset.metadata_json or {}).get("community_moderation") or {}
            _sync_community_rejected_to_json(
                base_dir=get_audio_library_dir(),
                library_type=normalized_type,
                asset_id=normalized_asset_id,
                moderation_metadata=moderation_metadata,
            )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@router.get(
    "/audio-library/preview/{file_type}/{file_id}",
    summary="预览音效/音乐文件",
)
async def preview_audio_library_file(
    file_type: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base_dir = get_audio_library_dir()

    if file_type == "sfx":
        index = _load_library_entries(
            db=db,
            base_dir=base_dir,
            library_type="sfx",
            index_name="sound_effects_index.json",
        )
    elif file_type == "music":
        index = _load_library_entries(
            db=db,
            base_dir=base_dir,
            library_type="music",
            index_name="music_index.json",
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_type 必须为 sfx 或 music")

    entry = next((e for e in index if e.get("id") == file_id), None)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材未找到")

    file_path = _resolve_deletable_library_file(base_dir, str(entry.get("file_path") or ""))
    if file_path and file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path), media_type=_audio_library_media_type(file_path))

    public_url = _resolve_audio_library_public_url(entry)
    if public_url.startswith(("http://", "https://")):
        return RedirectResponse(public_url)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")


class SfxSearchRequest(BaseModel):
    query: str
    source: str = "freesound"
    max_results: int = 20
    commercial_only: bool = True


class SfxSearchResultItem(BaseModel):
    name: str
    source: str
    source_id: str
    download_url: str = ""
    license_name: str = ""
    license_commercial: bool = False
    duration: float = 0
    description: str = ""
    tags: List[str] = []
    author: str = ""


class SfxDownloadRequest(BaseModel):
    source: str
    source_id: str
    name: str
    download_url: str = ""
    license_name: str = ""
    license_commercial: bool = True
    duration: float = 0
    description: str = ""
    tags: List[str] = []
    author: str = ""
    source_url: str = ""
    author_url: str = ""
    license_url: str = ""


class LibraryCleanupRequest(BaseModel):
    library_type: str = "sfx"
    remove_orphaned: bool = True
    remove_missing_files: bool = True
    remove_low_quality: bool = False
    min_quality_score: float = 40.0
    dry_run: bool = True
    confirm: bool = False
    plan_token: str = ""


class AudioLibraryCloudSyncRequest(BaseModel):
    library_type: str = "both"
    dry_run: bool = True
    confirm: bool = False


class AudioLibraryDbSyncRequest(BaseModel):
    library_type: str = "both"
    dry_run: bool = True
    confirm: bool = False


class AudioLibraryCloudCheckRequest(BaseModel):
    library_type: str = "both"
    object_keys: List[str] = Field(default_factory=list)


class AudioLibraryCloudCleanupRequest(BaseModel):
    library_type: str = "both"
    remove_low_quality: bool = True
    remove_unindexed: bool = False
    min_quality_score: float = 40.0
    max_list_keys: int = 1000
    dry_run: bool = True
    confirm: bool = False


class AudioLibraryAssetDeleteRequest(BaseModel):
    dry_run: bool = True
    confirm: bool = False
    delete_cloud_object: bool = True
    delete_local_file: bool = True


class SfxCandidateItem(BaseModel):
    source: str
    source_id: str
    name: str = ""
    description: str = ""
    source_url: str = ""
    file_url: str = ""
    preview_url: str = ""
    license: str = ""
    license_url: str = ""
    license_version: str = ""
    license_commercial: bool = False
    attribution_required: bool = False
    attribution_text: str = ""
    author: str = ""
    author_url: str = ""
    duration: float = 0
    mime_type: str = ""
    tags: List[str] = []
    query: str = ""
    discovered_at: str = ""
    license_checked_at: str = ""
    requires_manual_review: bool = True
    status: str = "candidate_only"
    review_notes: str = ""


class SfxCandidatesResponse(BaseModel):
    total: int
    invalid_rows: int
    items: List[SfxCandidateItem]


class SfxCandidateManifestDraftItem(BaseModel):
    source: str
    source_id: str
    review_status: str = "approved"
    license_verified: bool = False
    local_file: str = ""
    category: str = ""
    style: str = ""
    notes: str = ""


class SfxCandidateManifestDraftRequest(BaseModel):
    items: List[SfxCandidateManifestDraftItem]
    source_dir: str = ""
    output_path: str = ""


class SfxManifestImportRequest(BaseModel):
    manifest_path: str = "sfx_import_manifest_draft.jsonl"
    source_dir: str = "approved_sfx"
    dry_run: bool = True
    confirm: bool = False
    overwrite: bool = False


def _load_sfx_candidate_rows(path: Path) -> tuple[List[Dict[str, Any]], int]:
    if not path.exists():
        return [], 0

    rows: List[Dict[str, Any]] = []
    invalid_rows = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("读取音效候选清单失败 %s: %s", path, exc)
        return [], 0

    for line in lines:
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            invalid_rows += 1
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            invalid_rows += 1
    return rows, invalid_rows


def _candidate_key(source: str, source_id: str) -> str:
    return f"{source}:{source_id}"


def _candidate_record_to_item(record: Dict[str, Any]) -> SfxCandidateItem:
    return SfxCandidateItem(
        source=str(record.get("source") or ""),
        source_id=str(record.get("source_id") or ""),
        name=str(record.get("name") or ""),
        description=str(record.get("description") or ""),
        source_url=str(record.get("source_url") or ""),
        file_url=str(record.get("file_url") or ""),
        preview_url=str(record.get("preview_url") or ""),
        license=str(record.get("license") or record.get("license_name") or ""),
        license_url=str(record.get("license_url") or ""),
        license_version=str(record.get("license_version") or ""),
        license_commercial=bool(record.get("license_commercial")),
        attribution_required=bool(record.get("attribution_required")),
        attribution_text=str(record.get("attribution_text") or ""),
        author=str(record.get("author") or ""),
        author_url=str(record.get("author_url") or ""),
        duration=float(record.get("duration") or 0),
        mime_type=str(record.get("mime_type") or ""),
        tags=[str(item) for item in record.get("tags", []) if item],
        query=str(record.get("query") or ""),
        discovered_at=str(record.get("discovered_at") or ""),
        license_checked_at=str(record.get("license_checked_at") or ""),
        requires_manual_review=bool(record.get("requires_manual_review", True)),
        status=str(record.get("status") or "candidate_only"),
        review_notes=str(record.get("review_notes") or ""),
    )


def _validate_local_file(source_dir: Path, local_file: str) -> str:
    if not local_file.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approved candidate must include local_file",
        )

    candidate = Path(local_file)
    if candidate.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="local_file must be relative to source_dir",
        )

    try:
        resolved = (source_dir / candidate).resolve(strict=False)
        root = source_dir.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="local_file must stay inside source_dir",
        )

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="local_file does not exist under source_dir",
        )
    return candidate.as_posix()


def _resolve_audio_library_output_path(base_dir: Path, output_path: str, default_name: str) -> Path:
    raw_path = Path(output_path) if output_path else Path(default_name)
    target_path = raw_path if raw_path.is_absolute() else base_dir / raw_path
    try:
        resolved = target_path.resolve(strict=False)
        root = base_dir.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="output_path must stay inside audio library directory",
        )
    return resolved


def _resolve_audio_library_input_path(base_dir: Path, raw_path: str, field_name: str, default_name: str) -> Path:
    path = Path(raw_path) if raw_path else Path(default_name)
    target = path if path.is_absolute() else base_dir / path
    try:
        resolved = target.resolve(strict=False)
        root = base_dir.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must stay inside audio library directory",
        )
    return resolved


def _resolve_library_file(base_dir: Path, file_ref: str) -> Optional[Path]:
    raw = str(file_ref or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path if path.is_absolute() else base_dir / path
    try:
        resolved = candidate.resolve(strict=False)
        base_dir.resolve(strict=False)
    except OSError:
        return None
    return resolved


def _resolve_deletable_library_file(base_dir: Path, file_ref: str) -> Optional[Path]:
    resolved = _resolve_library_file(base_dir, file_ref)
    if not resolved:
        return None
    try:
        resolved.relative_to(base_dir.resolve(strict=False))
    except ValueError:
        return None
    return resolved


def _is_low_quality_entry(entry: Dict[str, Any], min_score: float) -> bool:
    if entry.get("quality_status") == "rejected":
        return True
    if "quality_score" not in entry:
        return False
    try:
        return float(entry.get("quality_score")) < min_score
    except (TypeError, ValueError):
        return False


def _cleanup_detail(library_type: str, entry: Dict[str, Any], reason: str, size: int = 0) -> Dict[str, Any]:
    return {
        "library_type": library_type,
        "id": str(entry.get("id") or ""),
        "name": str(entry.get("name") or entry.get("style") or ""),
        "file_path": str(entry.get("file_path") or entry.get("file") or ""),
        "reason": reason,
        "size": int(size or 0),
    }


def _build_library_cleanup_plan_token(
    request: LibraryCleanupRequest,
    details: Dict[str, List[Dict[str, Any]]],
) -> str:
    targets = []
    for detail_type in ("missing_entries", "low_quality_entries", "orphaned_files"):
        for item in details[detail_type]:
            targets.append({
                "detail_type": detail_type,
                "library_type": str(item.get("library_type") or ""),
                "id": str(item.get("id") or ""),
                "file_path": str(item.get("file_path") or ""),
                "reason": str(item.get("reason") or ""),
                "size": int(item.get("size") or 0),
            })
    targets.sort(key=lambda item: (
        item["detail_type"],
        item["library_type"],
        item["id"],
        item["file_path"],
    ))
    payload = {
        "library_type": request.library_type,
        "remove_orphaned": request.remove_orphaned,
        "remove_missing_files": request.remove_missing_files,
        "remove_low_quality": request.remove_low_quality,
        "min_quality_score": float(request.min_quality_score),
        "targets": targets,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json_array_atomic(path: Path, entries: List[Dict[str, Any]]) -> None:
    temp_path = path.with_name(f"{path.name}.tmp")
    try:
        temp_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("音频素材 JSON 临时文件清理失败: %s", temp_path)
        raise


def _scan_library_cleanup(
    base_dir: Path,
    library_type: str,
    index_name: str,
    asset_subdir: str,
    request: LibraryCleanupRequest,
    source_entries: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    index_path = base_dir / index_name
    entries = source_entries if source_entries is not None else _load_json_array(index_path)
    cleaned: List[Dict[str, Any]] = []
    removed_entries: List[Dict[str, Any]] = []
    details = {"missing_entries": [], "low_quality_entries": [], "orphaned_files": []}
    stats = {"removed_missing": 0, "removed_low_quality": 0, "removed_orphaned": 0, "freed_bytes": 0}
    indexed_files: set[str] = set()

    for entry in entries:
        file_ref = str(entry.get("file_path") or entry.get("file") or "")
        resolved = _resolve_library_file(base_dir, file_ref)
        if resolved:
            indexed_files.add(resolved.resolve(strict=False).as_posix())

        has_local_file = bool(resolved and resolved.exists() and resolved.is_file())
        has_cloud_file = _resolve_audio_library_public_url(entry).startswith(("http://", "https://"))
        missing = request.remove_missing_files and not has_local_file and not has_cloud_file
        low_quality = request.remove_low_quality and _is_low_quality_entry(entry, request.min_quality_score)

        if missing:
            stats["removed_missing"] += 1
            details["missing_entries"].append(_cleanup_detail(library_type, entry, "missing_file"))
            removed_entries.append(entry)
            continue

        if low_quality:
            size = resolved.stat().st_size if resolved and resolved.exists() else 0
            stats["removed_low_quality"] += 1
            stats["freed_bytes"] += size
            details["low_quality_entries"].append(_cleanup_detail(library_type, entry, "low_quality", size))
            removed_entries.append(entry)
            continue

        cleaned.append(entry)

    asset_root = base_dir / asset_subdir
    if request.remove_orphaned and asset_root.exists():
        for file_path in asset_root.rglob("*"):
            if not file_path.is_file():
                continue
            resolved_key = file_path.resolve(strict=False).as_posix()
            if resolved_key in indexed_files:
                continue
            size = file_path.stat().st_size
            stats["removed_orphaned"] += 1
            stats["freed_bytes"] += size
            try:
                relative_path = file_path.relative_to(base_dir).as_posix()
            except ValueError:
                relative_path = file_path.as_posix()
            details["orphaned_files"].append({
                "library_type": library_type,
                "id": "",
                "name": file_path.name,
                "file_path": relative_path,
                "reason": "orphaned_file",
                "size": size,
            })

    return entries, cleaned, details, stats


def _cloud_sync_detail(library_type: str, entry: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    return {
        "library_type": library_type,
        "id": str(entry.get("id") or ""),
        "name": str(entry.get("name") or entry.get("style") or entry.get("prompt") or ""),
        "file_path": str(entry.get("file_path") or entry.get("file") or ""),
        "storage_mode": str(entry.get("storage_mode") or ""),
        "storage_driver": str(entry.get("storage_driver") or ""),
        "reason": reason,
    }


def _configured_audio_library_oss_prefix() -> str:
    prefix = str(os.getenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX") or _DEFAULT_AUDIO_LIBRARY_OSS_PREFIX)
    prefix = prefix.strip().strip("/")
    return prefix or _DEFAULT_AUDIO_LIBRARY_OSS_PREFIX


def _cloud_prefix_for_library_type(library_type: str) -> str:
    prefix = _configured_audio_library_oss_prefix()
    if library_type == "sfx":
        return f"{prefix}/sfx/"
    if library_type == "music":
        return f"{prefix}/music/"
    return f"{prefix}/"


def _assert_aliyun_audio_library_storage() -> None:
    storage_driver = get_audio_library_storage_driver()
    if storage_driver != "aliyun_oss":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该云端管理接口仅支持 AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=aliyun_oss",
        )


def _extract_cloud_object_key(entry: Dict[str, Any]) -> str:
    object_key = str(entry.get("object_key") or "").strip().lstrip("/")
    if object_key:
        return object_key
    cloud_uri = str(entry.get("cloud_uri") or "").strip()
    if cloud_uri.startswith("oss://"):
        return cloud_uri[len("oss://") :].strip().lstrip("/")
    return ""


def _cloud_object_detail(library_type: str, entry: Dict[str, Any], object_key: str, reason: str = "") -> Dict[str, Any]:
    return {
        "library_type": library_type,
        "id": str(entry.get("id") or entry.get("asset_key") or ""),
        "name": str(entry.get("name") or entry.get("style") or entry.get("prompt") or ""),
        "file_path": str(entry.get("file_path") or entry.get("file") or ""),
        "object_key": object_key,
        "storage_mode": str(entry.get("storage_mode") or ""),
        "storage_driver": str(entry.get("storage_driver") or ""),
        "reason": reason,
    }


def _load_cloud_index_entries(
    *,
    db: Session,
    base_dir: Path,
    library_type: str,
    index_name: str,
) -> list[Dict[str, Any]]:
    try:
        assets = (
            db.query(AudioLibraryAsset)
            .filter(AudioLibraryAsset.library_type == library_type)
            .order_by(AudioLibraryAsset.asset_key.asc())
            .all()
        )
    except SQLAlchemyError as exc:
        logger.warning("读取音频素材数据库索引失败，回退 JSON 索引: %s", exc)
        db.rollback()
        assets = []
    if assets:
        return [audio_library_asset_to_record(asset) for asset in assets]
    return [entry for entry in _load_json_array(base_dir / index_name) if isinstance(entry, dict)]


def _iter_cloud_index_entries(
    *,
    db: Session,
    base_dir: Path,
    library_type: str,
) -> list[tuple[str, Dict[str, Any]]]:
    entries: list[tuple[str, Dict[str, Any]]] = []
    for target in _resolve_library_type_targets(library_type):
        target_type, index_name = target[0], target[1]
        for entry in _load_cloud_index_entries(
            db=db,
            base_dir=base_dir,
            library_type=str(target_type),
            index_name=str(index_name),
        ):
            entries.append((str(target_type), entry))
    return entries


def _should_delete_cloud_entry(entry: Dict[str, Any], request: AudioLibraryCloudCleanupRequest) -> bool:
    if request.remove_low_quality and _is_low_quality_entry(entry, request.min_quality_score):
        return True
    return False


def _scan_cloud_sync_entries(
    base_dir: Path,
    library_type: str,
    index_name: str,
) -> tuple[List[Dict[str, Any]], List[tuple[int, Dict[str, Any], Path, str]], Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    entries = _load_json_array(base_dir / index_name)
    eligible: List[tuple[int, Dict[str, Any], Path, str]] = []
    details = {
        "eligible": [],
        "uploaded": [],
        "failed": [],
        "skipped": [],
    }
    stats = {
        "eligible": 0,
        "uploaded": 0,
        "failed_upload": 0,
        "skipped_cloud": 0,
        "skipped_missing_file": 0,
        "skipped_missing_file_path": 0,
    }

    for idx, entry in enumerate(entries):
        if entry.get("storage_mode") == "durable_cloud":
            stats["skipped_cloud"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "already_cloud"))
            continue

        file_ref = str(entry.get("file_path") or entry.get("file") or "").strip()
        if not file_ref:
            stats["skipped_missing_file_path"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "missing_file_path"))
            continue

        local_path = _resolve_deletable_library_file(base_dir, file_ref)
        if not local_path or not local_path.exists() or not local_path.is_file():
            stats["skipped_missing_file"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "missing_file"))
            continue

        stats["eligible"] += 1
        details["eligible"].append(_cloud_sync_detail(library_type, entry, "needs_cloud_sync"))
        eligible.append((idx, entry, local_path, file_ref.replace("\\", "/")))

    return entries, eligible, details, stats


def _scan_cloud_sync_db_records(
    db: Session,
    base_dir: Path,
    library_type: str,
) -> tuple[list[AudioLibraryAsset], list[tuple[AudioLibraryAsset, Dict[str, Any], Path, str]], Dict[str, list[Dict[str, Any]]], Dict[str, int]]:
    details = {"eligible": [], "uploaded": [], "failed": [], "skipped": []}
    stats = {
        "eligible": 0,
        "uploaded": 0,
        "failed_upload": 0,
        "skipped_cloud": 0,
        "skipped_missing_file": 0,
        "skipped_missing_file_path": 0,
    }

    assets = (
        db.query(AudioLibraryAsset)
        .filter(AudioLibraryAsset.library_type == library_type)
        .order_by(AudioLibraryAsset.asset_key.asc())
        .all()
    )
    eligible: list[tuple[AudioLibraryAsset, Dict[str, Any], Path, str]] = []

    for asset in assets:
        entry = {
            "id": asset.asset_key,
            "name": asset.name,
            "file_path": asset.file_path,
            "storage_mode": asset.storage_mode,
            "storage_driver": asset.storage_driver,
        }
        if asset.storage_mode == "durable_cloud":
            stats["skipped_cloud"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "already_cloud"))
            continue

        file_ref = str(asset.file_path or "").strip()
        if not file_ref:
            stats["skipped_missing_file_path"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "missing_file_path"))
            continue

        local_path = _resolve_deletable_library_file(base_dir, file_ref)
        if not local_path or not local_path.exists() or not local_path.is_file():
            stats["skipped_missing_file"] += 1
            details["skipped"].append(_cloud_sync_detail(library_type, entry, "missing_file"))
            continue

        relative_path = file_ref.replace("\\", "/")
        stats["eligible"] += 1
        details["eligible"].append(_cloud_sync_detail(library_type, entry, "needs_cloud_sync"))
        eligible.append((asset, entry, local_path, relative_path))

    return assets, eligible, details, stats


def _resolve_library_type_targets(library_type: str, *, include_asset_subdir: bool = False) -> list[tuple[str, str] | tuple[str, str, str]]:
    targets: list[tuple[str, str] | tuple[str, str, str]] = []
    if library_type in ("sfx", "both"):
        targets.append(("sfx", "sound_effects_index.json", "sound_effects") if include_asset_subdir else ("sfx", "sound_effects_index.json"))
    if library_type in ("music", "both"):
        targets.append(("music", "music_index.json", "music_cache") if include_asset_subdir else ("music", "music_index.json"))
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="library_type 必须为 sfx、music 或 both",
        )
    return targets


def _index_name_for_library_type(library_type: str) -> str:
    if library_type == "sfx":
        return "sound_effects_index.json"
    if library_type == "music":
        return "music_index.json"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="library_type 蹇呴』涓?sfx 鎴?music",
    )


def _entry_asset_id(entry: Dict[str, Any]) -> str:
    return str(entry.get("id") or entry.get("asset_key") or entry.get("source_id") or "").strip()


def _unlink_library_file(base_dir: Path, file_ref: str) -> None:
    target = _resolve_deletable_library_file(base_dir, file_ref)
    if not target or not target.exists() or not target.is_file():
        return
    try:
        target.unlink()
    except OSError:
        logger.warning("删除音频素材失败: %s", target)


def _manifest_row_from_candidate(
    candidate: SfxCandidateItem,
    review: SfxCandidateManifestDraftItem,
    source_dir: Path,
) -> Dict[str, Any]:
    if review.review_status != "approved":
        raise ValueError("only approved candidates can be converted")
    if not review.license_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="approved candidate must set license_verified=true",
        )

    local_file = _validate_local_file(source_dir, review.local_file)
    return {
        "file": local_file,
        "name": candidate.name,
        "description": candidate.description,
        "source": candidate.source,
        "source_id": candidate.source_id,
        "source_url": candidate.source_url,
        "license": candidate.license,
        "license_url": candidate.license_url,
        "license_commercial": candidate.license_commercial,
        "author": candidate.author,
        "author_url": candidate.author_url,
        "attribution_required": candidate.attribution_required,
        "attribution_text": candidate.attribution_text,
        "category": review.category,
        "style": review.style,
        "tags": candidate.tags,
        "review_source": "sfx_candidates.jsonl",
        "review_status": review.review_status,
    }


@router.get(
    "/audio-library/sound-effects/candidates",
    summary="读取音效候选清单",
)
async def list_sfx_candidates(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
):
    _require_audio_library_admin(current_user)
    base_dir = get_audio_library_dir()
    rows, invalid_rows = _load_sfx_candidate_rows(base_dir / "sfx_candidates.jsonl")
    items = [_candidate_record_to_item(row) for row in rows]
    if status_filter:
        items = [item for item in items if item.status == status_filter]
    return SfxCandidatesResponse(total=len(items), invalid_rows=invalid_rows, items=items)


@router.post(
    "/audio-library/sound-effects/candidates/manifest-draft",
    summary="生成本地音效导入 manifest 草稿",
)
async def build_sfx_manifest_draft(
    request: SfxCandidateManifestDraftRequest,
    current_user: User = Depends(get_current_user),
):
    _require_audio_library_admin(current_user)
    base_dir = get_audio_library_dir()
    rows, _invalid_rows = _load_sfx_candidate_rows(base_dir / "sfx_candidates.jsonl")
    candidates = {
        _candidate_key(str(row.get("source") or ""), str(row.get("source_id") or "")): _candidate_record_to_item(row)
        for row in rows
    }
    source_dir = _resolve_audio_library_input_path(
        base_dir,
        request.source_dir,
        "source_dir",
        "approved_sfx",
    )
    target_path = _resolve_audio_library_output_path(
        base_dir,
        request.output_path,
        "sfx_import_manifest_draft.jsonl",
    )

    stats = {"approved": 0, "rejected": 0, "skipped": 0}
    manifest_rows: List[Dict[str, Any]] = []

    for review in request.items:
        if review.review_status == "rejected":
            stats["rejected"] += 1
            continue
        if review.review_status != "approved":
            stats["skipped"] += 1
            continue
        key = _candidate_key(review.source, review.source_id)
        candidate = candidates.get(key)
        if not candidate:
            stats["skipped"] += 1
            continue
        row = _manifest_row_from_candidate(candidate, review, source_dir)
        manifest_rows.append(row)
        stats["approved"] += 1

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8") as f:
        for row in manifest_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "success": True,
        "manifest_path": str(target_path),
        "source_dir": str(source_dir),
        "stats": stats,
        "items": manifest_rows,
    }


@router.post(
    "/audio-library/sound-effects/import-manifest",
    summary="导入本地已授权音效 manifest",
)
async def import_sfx_manifest(
    request: SfxManifestImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="音效素材库已停止导入第三方或本地 manifest，请使用用户上传或 AI 生成音效。",
    )
@router.post(
    "/audio-library/db-sync",
    summary="同步 JSON 音频素材索引到数据库",
)
async def sync_audio_library_json_indexes_to_db(
    request: AudioLibraryDbSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际数据库同步必须传入 dry_run=false 且 confirm=true",
        )

    base_dir = get_audio_library_dir()
    stats = {"candidates": 0, "synced": 0}
    details = {"candidates": [], "synced": [], "rejected": []}

    for target_type, index_name in _resolve_library_type_targets(request.library_type):
        entries = _load_json_array(base_dir / index_name)
        stats["candidates"] += len(entries)
        for entry in entries:
            details["candidates"].append({
                "library_type": target_type,
                "id": str(entry.get("id") or entry.get("asset_key") or entry.get("source_id") or ""),
                "file_path": str(entry.get("file_path") or entry.get("file") or ""),
            })
            if target_type == "sfx" and not is_allowed_sfx_source(entry.get("source")):
                details["rejected"].append({
                    "library_type": target_type,
                    "id": str(entry.get("id") or entry.get("asset_key") or entry.get("source_id") or ""),
                    "source": str(entry.get("source") or ""),
                    "reason": "source_not_allowed",
                })
                continue
            if request.dry_run:
                continue
            asset = upsert_audio_library_asset(db, target_type, entry)
            stats["synced"] += 1
            details["synced"].append({
                "library_type": target_type,
                "id": asset.asset_key,
                "file_path": asset.file_path,
            })

    if not request.dry_run:
        db.commit()

    return {
        "success": True,
        "dry_run": request.dry_run,
        "stats": stats,
        "details": details,
    }


@router.post(
    "/audio-library/cloud-sync",
    summary="同步共享音频素材到云端",
)
async def sync_audio_library_to_cloud(
    request: AudioLibraryCloudSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际云端同步必须传入 dry_run=false 且 confirm=true",
        )

    cloud_enabled = is_audio_library_cloud_storage_enabled()
    storage_driver = get_audio_library_storage_driver()
    if not request.dry_run and not cloud_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "云存储未启用，需先配置 "
                "AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER=aliyun_oss 或 dashscope_oss"
            ),
        )

    sync_targets = []
    if request.library_type in ("sfx", "both"):
        sync_targets.append(("sfx", "sound_effects_index.json"))
    if request.library_type in ("music", "both"):
        sync_targets.append(("music", "music_index.json"))
    if not sync_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="library_type 必须为 sfx、music 或 both",
        )

    base_dir = get_audio_library_dir()
    stats = {
        "eligible": 0,
        "uploaded": 0,
        "failed_upload": 0,
        "skipped_cloud": 0,
        "skipped_missing_file": 0,
        "skipped_missing_file_path": 0,
    }
    details = {
        "eligible": [],
        "uploaded": [],
        "failed": [],
        "skipped": [],
    }

    db_changed = False
    for target_type, index_name in sync_targets:
        use_db_records = False
        db_eligible: list[tuple[AudioLibraryAsset, Dict[str, Any], Path, str]] = []
        try:
            assets, db_eligible, target_details, target_stats = _scan_cloud_sync_db_records(db, base_dir, target_type)
            use_db_records = bool(assets)
        except SQLAlchemyError as exc:
            logger.warning("扫描音频素材数据库索引失败，回退 JSON 索引: %s", exc)
            db.rollback()
            assets = []
            db_eligible = []
            target_details = {}
            target_stats = {}

        if use_db_records:
            entries: list[Dict[str, Any]] = []
            json_eligible: list[tuple[int, Dict[str, Any], Path, str]] = []
        else:
            assets = []
            entries, json_eligible, target_details, target_stats = _scan_cloud_sync_entries(base_dir, target_type, index_name)

        for key, value in target_stats.items():
            stats[key] += value
        for key, value in target_details.items():
            details[key].extend(value)

        if request.dry_run:
            continue

        if use_db_records:
            for asset, entry, local_path, relative_path in db_eligible:
                metadata = upload_audio_library_asset(
                    local_path=local_path,
                    relative_path=relative_path,
                    library_type=target_type,
                )
                if metadata.get("storage_mode") != "durable_cloud":
                    stats["failed_upload"] += 1
                    failed_detail = _cloud_sync_detail(target_type, entry, "upload_failed")
                    failed_detail["storage_driver"] = str(metadata.get("storage_driver") or storage_driver)
                    details["failed"].append(failed_detail)
                    continue

                asset.storage_mode = str(metadata.get("storage_mode") or asset.storage_mode)
                asset.storage_driver = str(metadata.get("storage_driver") or asset.storage_driver)
                asset.cloud_uri = str(metadata.get("cloud_uri") or "")
                asset.public_url = str(metadata.get("public_url") or "")
                asset.object_key = str(metadata.get("object_key") or "")
                asset.local_cache_path = str(metadata.get("local_cache_path") or relative_path)
                asset.asset_scope = str(metadata.get("asset_scope") or asset.asset_scope or "shared_library")
                db_changed = True
                stats["uploaded"] += 1

                uploaded_entry = {
                    **entry,
                    "storage_mode": asset.storage_mode,
                    "storage_driver": asset.storage_driver,
                    "cloud_uri": asset.cloud_uri,
                    "public_url": asset.public_url,
                }
                uploaded_detail = _cloud_sync_detail(target_type, uploaded_entry, "uploaded")
                uploaded_detail["cloud_uri"] = asset.cloud_uri or ""
                uploaded_detail["public_url"] = asset.public_url or ""
                details["uploaded"].append(uploaded_detail)
            continue

        changed = False
        for idx, entry, local_path, relative_path in json_eligible:
            metadata = upload_audio_library_asset(
                local_path=local_path,
                relative_path=relative_path,
                library_type=target_type,
            )
            if metadata.get("storage_mode") != "durable_cloud":
                stats["failed_upload"] += 1
                failed_detail = _cloud_sync_detail(target_type, entry, "upload_failed")
                failed_detail["storage_driver"] = str(metadata.get("storage_driver") or storage_driver)
                details["failed"].append(failed_detail)
                continue

            entries[idx].update(metadata)
            changed = True
            stats["uploaded"] += 1
            uploaded_detail = _cloud_sync_detail(target_type, entries[idx], "uploaded")
            uploaded_detail["cloud_uri"] = str(metadata.get("cloud_uri") or "")
            uploaded_detail["public_url"] = str(metadata.get("public_url") or "")
            details["uploaded"].append(uploaded_detail)

        if changed:
            (base_dir / index_name).write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    if db_changed:
        db.commit()

    return {
        "success": True,
        "dry_run": request.dry_run,
        "cloud_enabled": cloud_enabled,
        "storage_driver": storage_driver,
        "stats": stats,
        "details": details,
    }


@router.get(
    "/audio-library/cloud-objects",
    summary="列出共享音频素材库 OSS 对象",
)
async def list_audio_library_cloud_objects(
    library_type: str = Query(default="both", description="sfx、music 或 both"),
    prefix: str = Query(default="", description="可选 OSS object key 前缀"),
    max_keys: int = Query(default=100, ge=1, le=1000),
    continuation_token: str = Query(default=""),
    delimiter: str = Query(default=""),
    start_after: str = Query(default=""),
    current_user: User = Depends(get_current_user),
):
    _require_audio_library_admin(current_user)
    _assert_aliyun_audio_library_storage()
    if library_type not in {"sfx", "music", "both"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="library_type 必须为 sfx、music 或 both",
        )

    requested_prefix = str(prefix or "").strip().lstrip("/")
    effective_prefix = requested_prefix or _cloud_prefix_for_library_type(library_type)
    allowed_root = f"{_configured_audio_library_oss_prefix()}/"
    if not effective_prefix.startswith(allowed_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prefix 必须位于共享音频素材库 OSS 前缀内",
        )

    try:
        result = list_audio_library_objects(
            prefix=effective_prefix,
            max_keys=max_keys,
            continuation_token=continuation_token,
            delimiter=delimiter,
            start_after=start_after,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"列出 OSS 对象失败: {exc}",
        ) from exc

    return {
        "success": True,
        "storage_driver": get_audio_library_storage_driver(),
        **result,
    }


@router.post(
    "/audio-library/cloud-check",
    summary="批量检查共享音频素材库云端对象是否存在",
)
async def check_audio_library_cloud_objects(
    request: AudioLibraryCloudCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    _assert_aliyun_audio_library_storage()
    base_dir = get_audio_library_dir()
    allowed_root = f"{_configured_audio_library_oss_prefix()}/"
    stats = {"checked": 0, "exists": 0, "missing": 0, "failed": 0}
    details = {"exists": [], "missing": [], "failed": []}

    explicit_keys = [
        str(key or "").strip().lstrip("/")
        for key in request.object_keys
        if str(key or "").strip()
    ]
    if explicit_keys:
        candidates: list[tuple[str, Dict[str, Any], str]] = [
            (
                "",
                {"id": "", "file_path": "", "storage_mode": "durable_cloud", "storage_driver": "aliyun_oss"},
                key,
            )
            for key in explicit_keys
        ]
    else:
        candidates = []
        for target_type, entry in _iter_cloud_index_entries(db=db, base_dir=base_dir, library_type=request.library_type):
            object_key = _extract_cloud_object_key(entry)
            if object_key:
                candidates.append((target_type, entry, object_key))

    seen_keys: set[str] = set()
    for target_type, entry, object_key in candidates:
        if object_key in seen_keys:
            continue
        seen_keys.add(object_key)
        if not object_key.startswith(allowed_root):
            stats["failed"] += 1
            details["failed"].append(_cloud_object_detail(target_type, entry, object_key, "outside_audio_library_prefix"))
            continue

        stats["checked"] += 1
        try:
            head_result = head_audio_library_object(object_key=object_key)
        except Exception as exc:
            stats["failed"] += 1
            failed_detail = _cloud_object_detail(target_type, entry, object_key, "head_failed")
            failed_detail["error"] = str(exc)
            details["failed"].append(failed_detail)
            continue

        detail = _cloud_object_detail(
            target_type,
            entry,
            object_key,
            "exists" if head_result.get("exists") else "missing",
        )
        detail.update(
            {
                "status_code": head_result.get("status_code"),
                "content_length": head_result.get("content_length"),
                "etag": head_result.get("etag", ""),
                "last_modified": head_result.get("last_modified", ""),
            }
        )
        if head_result.get("exists"):
            stats["exists"] += 1
            details["exists"].append(detail)
        else:
            stats["missing"] += 1
            details["missing"].append(detail)

    return {
        "success": True,
        "storage_driver": get_audio_library_storage_driver(),
        "stats": stats,
        "details": details,
    }


@router.post(
    "/audio-library/cloud-cleanup",
    summary="清理共享音频素材库云端对象",
)
async def cleanup_audio_library_cloud_objects(
    request: AudioLibraryCloudCleanupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际云端清理必须传入 dry_run=false 且 confirm=true",
        )
    _assert_aliyun_audio_library_storage()

    base_dir = get_audio_library_dir()
    allowed_root = f"{_configured_audio_library_oss_prefix()}/"
    stats = {"candidates": 0, "deleted": 0, "failed": 0, "skipped": 0}
    details = {"candidates": [], "deleted": [], "failed": [], "skipped": []}
    indexed_keys: set[str] = set()
    candidate_map: dict[str, tuple[str, Dict[str, Any], str]] = {}

    for target_type, entry in _iter_cloud_index_entries(db=db, base_dir=base_dir, library_type=request.library_type):
        object_key = _extract_cloud_object_key(entry)
        if not object_key:
            continue
        indexed_keys.add(object_key)
        if not object_key.startswith(allowed_root):
            stats["skipped"] += 1
            details["skipped"].append(_cloud_object_detail(target_type, entry, object_key, "outside_audio_library_prefix"))
            continue
        if _should_delete_cloud_entry(entry, request):
            candidate_map[object_key] = (target_type, entry, "low_quality")

    if request.remove_unindexed:
        for target in _resolve_library_type_targets(request.library_type):
            target_type = str(target[0])
            continuation_token = ""
            seen_tokens: set[str] = set()
            while True:
                try:
                    listed = list_audio_library_objects(
                        prefix=_cloud_prefix_for_library_type(target_type),
                        max_keys=request.max_list_keys,
                        continuation_token=continuation_token,
                    )
                except Exception as exc:
                    stats["failed"] += 1
                    details["failed"].append(
                        {
                            "library_type": target_type,
                            "object_key": "",
                            "reason": "list_failed",
                            "error": str(exc),
                        }
                    )
                    break
                for item in listed.get("items", []):
                    object_key = str(item.get("key") or "").strip().lstrip("/")
                    if not object_key or object_key in indexed_keys:
                        continue
                    if not object_key.startswith(allowed_root):
                        continue
                    candidate_map.setdefault(
                        object_key,
                        (target_type, {"id": "", "name": item.get("key", ""), "file_path": ""}, "unindexed_cloud_object"),
                    )

                if not listed.get("is_truncated"):
                    break
                next_token = str(listed.get("next_continuation_token") or "").strip()
                if not next_token or next_token in seen_tokens:
                    break
                seen_tokens.add(next_token)
                continuation_token = next_token

    for object_key, (target_type, entry, reason) in sorted(candidate_map.items()):
        stats["candidates"] += 1
        candidate_detail = _cloud_object_detail(target_type, entry, object_key, reason)
        details["candidates"].append(candidate_detail)
        if request.dry_run:
            continue
        try:
            delete_result = delete_audio_library_object(object_key=object_key)
        except Exception as exc:
            stats["failed"] += 1
            failed_detail = dict(candidate_detail)
            failed_detail["error"] = str(exc)
            details["failed"].append(failed_detail)
            continue
        if delete_result.get("deleted"):
            stats["deleted"] += 1
            deleted_detail = dict(candidate_detail)
            deleted_detail["status_code"] = delete_result.get("status_code")
            details["deleted"].append(deleted_detail)
        else:
            stats["failed"] += 1
            failed_detail = dict(candidate_detail)
            failed_detail["status_code"] = delete_result.get("status_code")
            details["failed"].append(failed_detail)

    return {
        "success": True,
        "dry_run": request.dry_run,
        "storage_driver": get_audio_library_storage_driver(),
        "stats": stats,
        "details": details,
    }


@router.post(
    "/audio-library/sound-effects/search",
    summary="搜索公开音效库",
)
async def search_public_sfx(
    request: SfxSearchRequest,
    current_user: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="公开平台音效直接搜索已禁用；请先走候选审核流程，再使用本地 manifest 导入已授权素材。",
    )


@router.post(
    "/audio-library/sound-effects/download",
    summary="下载音效到本地库",
)
async def download_sfx_to_library(
    request: SfxDownloadRequest,
    current_user: User = Depends(get_current_user),
):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="公开平台音效自动下载已禁用；请先通过候选审核，并使用本地 manifest 导入已授权素材。",
    )


@router.post(
    "/audio-library/assets/{library_type}/{asset_id}/delete",
    summary="管理员删除单个音频素材",
)
async def delete_audio_library_asset(
    library_type: str,
    asset_id: str,
    request: AudioLibraryAssetDeleteRequest = Body(default_factory=AudioLibraryAssetDeleteRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际素材删除必须传入 dry_run=false 且 confirm=true",
        )

    normalized_type = str(library_type or "").strip().lower()
    index_name = _index_name_for_library_type(normalized_type)
    normalized_asset_id = str(asset_id or "").strip()
    if not normalized_asset_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="asset_id is required")

    base_dir = get_audio_library_dir()
    stats = {"index_removed": 0, "local_deleted": 0, "cloud_deleted": 0}
    details: Dict[str, Any] = {"local_file": "", "cloud_object": "", "source": ""}

    try:
        asset = (
            db.query(AudioLibraryAsset)
            .filter(
                AudioLibraryAsset.library_type == normalized_type,
                AudioLibraryAsset.asset_key == normalized_asset_id,
            )
            .first()
        )
    except SQLAlchemyError as exc:
        logger.warning("读取音频素材数据库索引失败，回退 JSON 索引: %s", exc)
        db.rollback()
        asset = None
    if asset is not None:
        entry = audio_library_asset_to_record(asset)
        details["source"] = "database"
    else:
        index_path = base_dir / index_name
        entries = [entry for entry in _load_json_array(index_path) if isinstance(entry, dict)]
        entry = next((item for item in entries if _entry_asset_id(item) == normalized_asset_id), None)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
        details["source"] = "json_index"

    file_ref = str(entry.get("file_path") or entry.get("file") or "")
    local_path = _resolve_deletable_library_file(base_dir, file_ref)
    object_key = _extract_cloud_object_key(entry)
    details["local_file"] = file_ref
    details["cloud_object"] = object_key

    if request.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "asset": _cleanup_detail(normalized_type, entry, "delete_asset"),
            "stats": stats,
            "details": details,
        }

    skip_cloud_delete = False
    if request.delete_cloud_object and object_key:
        allowed_root = f"{_configured_audio_library_oss_prefix()}/"
        if not object_key.startswith(allowed_root):
            # 前缀外的云端对象拒绝删除（安全约束），但不阻断本地数据库/索引删除
            logger.warning(
                "素材云端对象不在素材库 OSS 前缀内，跳过云端删除: %s (allowed_root=%s)",
                object_key,
                allowed_root,
            )
            details["cloud_error"] = "object_key outside audio library OSS prefix, cloud delete skipped"
            skip_cloud_delete = True

    if request.delete_local_file and local_path and local_path.exists() and local_path.is_file():
        try:
            local_path.unlink()
            stats["local_deleted"] = 1
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"删除本地素材失败: {exc}",
            ) from exc

    if request.delete_cloud_object and object_key and not skip_cloud_delete:
        try:
            delete_result = delete_audio_library_object(object_key=object_key)
            if delete_result.get("deleted"):
                stats["cloud_deleted"] = 1
        except Exception as exc:
            # 云端删除失败不阻断本地数据库/索引删除，否则素材会一直残留在列表里删不掉
            logger.warning("删除云端素材失败（继续删除本地索引）: %s -> %s", object_key, exc)
            details["cloud_error"] = str(exc)

    if asset is not None:
        db.delete(asset)
        db.commit()
        stats["index_removed"] = 1

    index_path = base_dir / index_name
    entries = [item for item in _load_json_array(index_path) if isinstance(item, dict)]
    kept = [item for item in entries if _entry_asset_id(item) != normalized_asset_id]
    if len(kept) != len(entries):
        index_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["index_removed"] = 1

    return {
        "success": True,
        "dry_run": False,
        "asset": _cleanup_detail(normalized_type, entry, "delete_asset"),
        "stats": stats,
        "details": details,
    }


@router.post(
    "/audio-library/cleanup",
    summary="清理音频库（移除孤立索引/缺失文件）",
)
async def cleanup_audio_library(
    request: LibraryCleanupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_audio_library_admin(current_user)
    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际清理必须传入 dry_run=false 且 confirm=true",
        )

    base_dir = get_audio_library_dir()
    stats = {
        "removed_orphaned": 0,
        "removed_missing": 0,
        "removed_low_quality": 0,
        "freed_bytes": 0,
    }
    details = {
        "missing_entries": [],
        "low_quality_entries": [],
        "orphaned_files": [],
    }

    cleanup_targets = []
    if request.library_type in ("sfx", "both"):
        cleanup_targets.append(("sfx", "sound_effects_index.json", "sound_effects"))
    if request.library_type in ("music", "both"):
        cleanup_targets.append(("music", "music_index.json", "music_cache"))
    if not cleanup_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="library_type 必须为 sfx、music 或 both",
        )

    scan_results = []
    for target_type, index_name, asset_subdir in cleanup_targets:
        source_entries = _load_library_entries(
            db=db,
            base_dir=base_dir,
            library_type=target_type,
            index_name=index_name,
            include_disallowed_sfx_sources=target_type == "sfx",
        )
        entries, cleaned, target_details, target_stats = _scan_library_cleanup(
            base_dir,
            target_type,
            index_name,
            asset_subdir,
            request,
            source_entries=source_entries,
        )
        for key, value in target_stats.items():
            stats[key] += value
        for key, value in target_details.items():
            details[key].extend(value)
        scan_results.append((target_type, index_name, cleaned, target_details))

    plan_token = _build_library_cleanup_plan_token(request, details)
    if request.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "plan_token": plan_token,
            "stats": stats,
            "details": details,
        }
    if not request.plan_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="执行实际清理必须携带 dry_run 返回的 plan_token",
        )
    if request.plan_token != plan_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="清理目标或参数已变化，请重新执行 dry_run 预览",
        )

    for target_type, index_name, cleaned, target_details in scan_results:
        for item in target_details["low_quality_entries"]:
            _unlink_library_file(base_dir, item["file_path"])
        for item in target_details["orphaned_files"]:
            _unlink_library_file(base_dir, item["file_path"])

        _write_json_array_atomic(base_dir / index_name, cleaned)

        try:
            replace_audio_library_asset_records(db, target_type, cleaned)
            db.commit()
        except SQLAlchemyError as exc:
            logger.warning("同步音频素材清理结果到数据库失败，保留 JSON 清理结果: %s", exc)
            db.rollback()

    return {
        "success": True,
        "dry_run": False,
        "plan_token": plan_token,
        "stats": stats,
        "details": details,
    }
