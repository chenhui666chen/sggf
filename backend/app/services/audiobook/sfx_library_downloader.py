"""
公开音效库合规导入器。

该模块用于生成候选清单、小批量导入已确认许可的音效，并登记
来源、署名、质量和文件校验元数据。它不是公开素材站点镜像器。

核心功能：
- 严格筛选允许商用且来源证据完整的音效素材
- 多维度标准化分类
- 清晰的文件命名规则和目录结构
- 自动注册到现有音效库索引系统，并复用质量门控
"""

import hashlib
import json
import logging
import os
import re
import shutil
import time
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

import httpx

from app.services.audiobook.audio_library_paths import get_audio_library_dir
from app.services.audiobook.audio_asset_cloud_storage import upload_audio_library_asset
from app.services.audiobook.audio_library_source_policy import (
    is_allowed_sfx_source,
    normalize_sfx_record_source,
)
from app.services.audiobook.agents.sound_effect_designer import SoundEffectDesigner
from app.services.audiobook.sfx_metadata import metadata_keyword_matches, normalize_sfx_semantics

logger = logging.getLogger(__name__)

AUDIO_LIBRARY_DIR = get_audio_library_dir()
SOUND_EFFECTS_DIR = AUDIO_LIBRARY_DIR / "sound_effects"


class CommercialLicense(str, Enum):
    CC0 = "cc0"
    CC_BY = "cc-by"
    PIXABAY_LICENSE = "pixabay"
    PUBLIC_DOMAIN = "public-domain"


COMMERCIAL_ALLOWED_LICENSES: Set[str] = {
    CommercialLicense.CC0.value,
    CommercialLicense.CC_BY.value,
    CommercialLicense.PIXABAY_LICENSE.value,
    CommercialLicense.PUBLIC_DOMAIN.value,
}

FREESOUND_COMMERCIAL_LICENSES: Set[str] = {
    "Creative Commons 0",
    "Creative Commons Attribution",
    "Creative Commons Attribution 3.0",
    "Creative Commons Attribution 4.0",
    "Attribution",
    "CC0",
}

LICENSE_URLS: Dict[str, str] = {
    "Creative Commons 0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Creative Commons Attribution": "https://creativecommons.org/licenses/by/4.0/",
    "Creative Commons Attribution 3.0": "https://creativecommons.org/licenses/by/3.0/",
    "Creative Commons Attribution 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "Attribution": "https://creativecommons.org/licenses/by/4.0/",
}

VALID_EFFECT_CATEGORIES = {"environment", "action", "emotion", "transition"}

CATEGORY_KEYWORD_MAP: Dict[str, List[str]] = {
    "environment": [
        "rain", "wind", "storm", "thunder", "ocean", "sea", "wave", "water",
        "river", "stream", "forest", "jungle", "bird", "insect", "cricket",
        "fire", "campfire", "city", "traffic", "crowd", "market", "cafe",
        "office", "factory", "machine", "ambience", "ambient", "nature",
        "weather", "rain", "snow", "wind", "breeze",
        "雨", "风", "雷", "海", "浪", "河", "溪", "森林", "鸟", "虫",
        "火", "城市", "街道", "人群", "市场", "工厂", "环境", "自然",
    ],
    "action": [
        "door", "knock", "slam", "footstep", "walk", "run", "glass",
        "break", "crash", "explosion", "gun", "shot", "sword", "fight",
        "punch", "hit", "slash", "click", "switch", "button", "phone",
        "ring", "bell", "alarm", "siren", "car", "engine", "brake",
        "paper", "book", "page", "coin", "money", "key", "lock",
        "门", "脚步", "碎", "爆", "枪", "剑", "打", "敲", "铃",
        "纸", "书", "钥匙", "锁",
    ],
    "emotion": [
        "heartbeat", "heart", "breath", "sigh", "whisper", "echo",
        "mystery", "suspense", "horror", "scary", "creepy", "eerie",
        "dream", "fantasy", "magic", "spell", "glow", "shimmer",
        "tension", "stress", "anxiety", "calm", "peace", "serene",
        "心跳", "呼吸", "叹", "低语", "回声", "神秘", "恐怖",
        "梦", "奇幻", "魔法", "紧张", "平静",
    ],
    "transition": [
        "whoosh", "swoosh", "swish", "transition", "sweep", "rise",
        "fall", "drop", "stinger", "hit", "impact", "boom", "bass",
        "cinematic", "trailer", "reveal", "appear", "disappear",
        "转场", "呼啸", "上升", "下降", "冲击", "电影", "预告",
    ],
}

STYLE_KEYWORD_MAP: Dict[str, List[str]] = {
    "cinematic": ["cinematic", "film", "movie", "trailer", "epic", "dramatic"],
    "realistic": ["realistic", "field", "recording", "foley", "real", "live"],
    "fantasy": ["fantasy", "magic", "spell", "mystical", "enchant", "fairy"],
    "scifi": ["sci-fi", "scifi", "futuristic", "cyber", "space", "laser", "robot"],
    "horror": ["horror", "scary", "creepy", "dark", "ghost", "monster", "demon"],
    "peaceful": ["calm", "peace", "relax", "gentle", "soft", "quiet", "serene"],
    "intense": ["intense", "action", "battle", "war", "combat", "fight", "chase"],
}

SCENE_KEYWORD_MAP: Dict[str, List[str]] = {
    "outdoor": ["outdoor", "outside", "nature", "field", "mountain", "forest"],
    "indoor": ["indoor", "inside", "room", "house", "office", "corridor"],
    "battle": ["battle", "fight", "war", "combat", "sword", "gun", "explosion"],
    "travel": ["travel", "journey", "road", "car", "train", "ship", "plane"],
    "mystery": ["mystery", "detective", "investigation", "clue", "secret"],
    "romance": ["romance", "love", "date", "kiss", "wedding", "tender"],
    "horror": ["horror", "ghost", "haunted", "abandoned", "darkness", "nightmare"],
}


def _normalize_category_hint(value: str) -> str:
    raw = str(value or "").strip().lower().replace("\\", "/")
    category = raw.split("/", 1)[0].strip()
    return category if category in VALID_EFFECT_CATEGORIES else ""


def _normalize_style_hint(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if raw == "scifi":
        return "scifi"
    for style in STYLE_KEYWORD_MAP:
        normalized_style = style.replace(" ", "").replace("_", "").replace("-", "")
        if raw == normalized_style:
            return style
    return ""


@dataclass
class SfxSearchResult:
    source: str
    source_id: str
    name: str
    description: str
    download_url: str
    preview_url: str = ""
    license_name: str = ""
    license_commercial: bool = False
    duration: float = 0.0
    sample_rate: int = 0
    tags: List[str] = field(default_factory=list)
    category_hint: str = ""
    style_hint: str = ""
    source_url: str = ""
    author: str = ""
    author_url: str = ""
    license_url: str = ""
    attribution_required: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SfxDownloadConfig:
    sources: List[str] = field(default_factory=lambda: ["freesound"])
    max_per_source: int = 100
    min_duration: float = 0.0
    max_duration: float = 60.0
    commercial_only: bool = True
    categories: List[str] = field(default_factory=lambda: ["environment", "action", "emotion", "transition"])
    search_queries: List[str] = field(default_factory=list)
    dry_run: bool = False
    overwrite: bool = False
    concurrency: int = 3
    request_delay: float = 1.0
    allow_freesound_commercial_api: bool = False
    allow_pixabay_audio_api: bool = False


@dataclass
class SfxCandidate:
    source: str
    source_id: str
    name: str
    description: str = ""
    source_url: str = ""
    file_url: str = ""
    preview_url: str = ""
    license_name: str = ""
    license_url: str = ""
    license_version: str = ""
    license_commercial: bool = False
    attribution_required: bool = False
    author: str = ""
    author_url: str = ""
    duration: float = 0.0
    mime_type: str = ""
    tags: List[str] = field(default_factory=list)
    query: str = ""
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    license_checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    requires_manual_review: bool = True
    status: str = "candidate_only"
    review_notes: str = "source page and license must be manually verified before import"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "name": self.name,
            "description": self.description,
            "source_url": self.source_url,
            "file_url": self.file_url,
            "preview_url": self.preview_url,
            "license": self.license_name,
            "license_url": self.license_url,
            "license_version": self.license_version,
            "license_commercial": self.license_commercial,
            "attribution_required": self.attribution_required,
            "author": self.author,
            "author_url": self.author_url,
            "duration": self.duration,
            "mime_type": self.mime_type,
            "tags": list(self.tags),
            "query": self.query,
            "discovered_at": self.discovered_at,
            "license_checked_at": self.license_checked_at,
            "requires_manual_review": self.requires_manual_review,
            "status": self.status,
            "review_notes": self.review_notes,
            "extra": dict(self.extra),
        }


def classify_category(name: str, description: str, tags: List[str]) -> str:
    text = f"{name} {description} {' '.join(tags)}".lower()
    scores: Dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if metadata_keyword_matches(text, kw))
        if score > 0:
            scores[cat] = score
    if scores:
        return max(scores, key=scores.get)
    return "action"


def classify_style(name: str, description: str, tags: List[str]) -> str:
    text = f"{name} {description} {' '.join(tags)}".lower()
    scores: Dict[str, int] = {}
    for style, keywords in STYLE_KEYWORD_MAP.items():
        score = sum(1 for kw in keywords if metadata_keyword_matches(text, kw))
        if score > 0:
            scores[style] = score
    if scores:
        return max(scores, key=scores.get)
    return "realistic"


def classify_scene(name: str, description: str, tags: List[str]) -> List[str]:
    text = f"{name} {description} {' '.join(tags)}".lower()
    scenes = []
    for scene, keywords in SCENE_KEYWORD_MAP.items():
        if any(metadata_keyword_matches(text, kw) for kw in keywords):
            scenes.append(scene)
    return scenes or ["general"]


def sanitize_filename(name: str, max_length: int = 60) -> str:
    sanitized = re.sub(r'[^\w\-.]', '_', name.strip())
    sanitized = re.sub(r'_+', '_', sanitized).strip('_')
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')
    return sanitized.lower()


def generate_effect_id(category: str, source: str, source_id: str) -> str:
    safe_source_id = sanitize_filename(str(source_id or "unknown"), max_length=24) or "unknown"
    short_hash = hashlib.sha256(f"{source}:{source_id}".encode()).hexdigest()[:10]
    return f"{category}_{source}_{safe_source_id}_{short_hash}"


def generate_file_path(category: str, style: str, effect_id: str, ext: str) -> str:
    return f"sound_effects/{category}/{style}/{effect_id}.{ext}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_attribution_required(license_name: str) -> bool:
    normalized = str(license_name or "").strip().lower()
    if not normalized:
        return False
    if "noncommercial" in normalized or "sampling" in normalized:
        return False
    if "attribution" in normalized or normalized in {"attribution", "cc-by"} or normalized.startswith("cc-by"):
        return True
    return False


def _license_version(license_name: str) -> str:
    match = re.search(r"\b(\d+(?:\.\d+)?)\b", str(license_name or ""))
    return match.group(1) if match else ""


def _duration_bucket(duration: float) -> str:
    try:
        value = float(duration)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 3.0:
        return "short"
    if value <= 10.0:
        return "medium"
    return "long"


def _build_attribution_text(result: SfxSearchResult) -> str:
    title = result.name or result.source_id
    author = result.author
    source_url = result.source_url
    license_name = result.license_name
    license_url = result.license_url
    return f"{title} by {author} ({source_url}), licensed under {license_name} ({license_url})"


def _inspect_downloaded_file(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"valid": False, "reason": "missing"}

    content = path.read_bytes()
    if not content:
        return {"valid": False, "reason": "empty"}

    head = content[:512].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<?xml")):
        return {"valid": False, "reason": "html"}

    content_type = _guess_audio_content_type(path, content)
    if not content_type.startswith("audio/"):
        return {"valid": False, "reason": "unsupported_content_type", "content_type": content_type}

    return {
        "valid": True,
        "sha256": hashlib.sha256(content).hexdigest(),
        "file_size": len(content),
        "content_type": content_type,
    }


def _guess_audio_content_type(path: Path, content: bytes) -> str:
    suffix = path.suffix.lower()
    if content.startswith(b"ID3") or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"} or suffix == ".mp3":
        return "audio/mpeg"
    if content.startswith(b"RIFF") and b"WAVE" in content[:16] or suffix == ".wav":
        return "audio/wav"
    if content.startswith(b"OggS") or suffix == ".ogg":
        return "audio/ogg"
    if content.startswith(b"fLaC") or suffix == ".flac":
        return "audio/flac"
    return "application/octet-stream"


def _load_manifest_rows(manifest_path: Path) -> List[Dict[str, Any]]:
    if not manifest_path.exists() or not manifest_path.is_file():
        raise FileNotFoundError(f"license manifest not found: {manifest_path}")

    if manifest_path.suffix.lower() == ".jsonl":
        rows = []
        with manifest_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL manifest at line {line_no}: {exc}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"manifest line {line_no} must be an object")
                rows.append(item)
        return rows

    with manifest_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        assets = raw.get("assets")
        if isinstance(assets, list):
            return [item for item in assets if isinstance(item, dict)]
    raise ValueError("manifest must be a JSON array, JSON object with assets array, or JSONL objects")


def _is_license_commercial_name(license_name: str) -> bool:
    normalized = str(license_name or "").strip().lower()
    if not normalized:
        return False
    if "noncommercial" in normalized or "non-commercial" in normalized:
        return False
    if "sampling" in normalized:
        return False
    return (
        normalized in COMMERCIAL_ALLOWED_LICENSES
        or license_name in FREESOUND_COMMERCIAL_LICENSES
        or "public domain" in normalized
        or "creative commons 0" in normalized
        or normalized == "cc0"
        or "creative commons attribution" in normalized
    )


def _normalize_manifest_tags(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _parse_manifest_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    return False


def _manifest_row_to_search_result(row: Dict[str, Any], source_id: str) -> SfxSearchResult:
    license_name = str(row.get("license") or row.get("license_name") or "").strip()
    license_url = str(row.get("license_url") or LICENSE_URLS.get(license_name, "")).strip()
    commercial_value = row.get("license_commercial")
    license_commercial = _parse_manifest_bool(
        commercial_value,
        default=_is_license_commercial_name(license_name),
    )
    attribution_required = _parse_manifest_bool(row.get("attribution_required")) or _is_attribution_required(license_name)

    return SfxSearchResult(
        source="local_authorized",
        source_id=source_id,
        name=str(row.get("name") or Path(str(row.get("file", ""))).stem),
        description=str(row.get("description") or row.get("name") or ""),
        download_url="",
        preview_url="",
        license_name=license_name,
        license_commercial=license_commercial,
        duration=float(row.get("duration") or 0.0),
        sample_rate=int(row.get("sample_rate") or row.get("samplerate") or 0),
        tags=_normalize_manifest_tags(row.get("tags")),
        category_hint=str(row.get("category") or ""),
        style_hint=str(row.get("style") or ""),
        source_url=str(row.get("source_url") or "").strip(),
        author=str(row.get("author") or "").strip(),
        author_url=str(row.get("author_url") or "").strip(),
        license_url=license_url,
        attribution_required=attribution_required,
        extra={
            "manifest_file": str(row.get("file") or ""),
            "attribution_text": str(row.get("attribution_text") or "").strip(),
            "source_payload_json": dict(row.get("source_payload_json") or {})
            if isinstance(row.get("source_payload_json"), dict)
            else {},
        },
    )


def _local_manifest_license_valid(result: SfxSearchResult) -> bool:
    if not result.license_commercial:
        return False
    if not result.license_name or not result.source_url or not result.license_url:
        return False
    if result.attribution_required and not (result.author or result.extra.get("attribution_text")):
        return False
    return True


def _strip_markup(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_license_key(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "-")


def _candidate_license_name(license_key: str, version: str = "") -> str:
    normalized = _normalize_license_key(license_key)
    version = str(version or "").strip()
    if normalized in {"cc0", "zero", "publicdomain", "public-domain", "pdm"}:
        return "CC0" if normalized == "cc0" else "Public Domain"
    if normalized in {"by", "cc-by"}:
        return f"CC-BY {version}".strip()
    if normalized in {"by-sa", "cc-by-sa"}:
        return f"CC-BY-SA {version}".strip()
    if normalized in {"by-nc", "by-nc-sa", "cc-by-nc", "cc-by-nc-sa"}:
        return f"CC-{normalized.upper()} {version}".strip()
    return str(license_key or "").strip()


def _candidate_license_commercial(license_name: str, license_url: str = "") -> bool:
    text = f"{license_name} {license_url}".lower()
    if not text.strip():
        return False
    if "noncommercial" in text or "by-nc" in text or "/nc" in text:
        return False
    if "sampling" in text:
        return False
    if "by-sa" in text or "sharealike" in text:
        return False
    return (
        "cc0" in text
        or "public domain" in text
        or "creativecommons.org/publicdomain" in text
        or "cc-by" in text
        or "cc by" in text
        or "/by/" in text
    )


def _extract_tag_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title")
        else:
            name = item
        name = str(name or "").strip()
        if name:
            tags.append(name)
    return tags


class OpenverseCandidateAdapter:
    BASE_URL = "https://api.openverse.org/v1"

    def __init__(self):
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "novel-writing-agent-sfx-candidate-discovery"},
        )

    def search(self, query: str, page_size: int = 30) -> List[SfxCandidate]:
        params = {
            "q": query,
            "page_size": min(page_size, 50),
            "license_type": "commercial",
        }
        try:
            resp = self.client.get("/audio/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("⚠️ Openverse 候选搜索失败: %s", e)
            return []

        candidates = []
        for item in data.get("results", []):
            candidate = self._item_to_candidate(item, query)
            if candidate and candidate.license_commercial and candidate.source_url and candidate.license_url:
                candidates.append(candidate)
        return candidates

    def _item_to_candidate(self, item: Dict[str, Any], query: str) -> Optional[SfxCandidate]:
        license_key = str(item.get("license") or "")
        license_version = str(item.get("license_version") or "")
        license_url = str(item.get("license_url") or "").strip()
        license_name = _candidate_license_name(license_key, license_version)
        license_commercial = _candidate_license_commercial(license_name, license_url)
        source_id = str(item.get("id") or item.get("identifier") or "").strip()
        source_url = str(item.get("foreign_landing_url") or item.get("landing_url") or "").strip()
        if not source_id:
            return None

        return SfxCandidate(
            source="openverse",
            source_id=source_id,
            name=str(item.get("title") or source_id).strip(),
            description=_strip_markup(item.get("description")),
            source_url=source_url,
            file_url=str(item.get("url") or "").strip(),
            preview_url=str(item.get("thumbnail") or "").strip(),
            license_name=license_name,
            license_url=license_url,
            license_version=license_version,
            license_commercial=license_commercial,
            attribution_required=_is_attribution_required(license_name),
            author=str(item.get("creator") or "").strip(),
            author_url=str(item.get("creator_url") or "").strip(),
            duration=float(item.get("duration") or 0.0),
            mime_type=str(item.get("frontend_media_type") or item.get("filetype") or "").strip(),
            tags=_extract_tag_names(item.get("tags")),
            query=query,
            extra={"provider": item.get("provider"), "detail_url": item.get("detail_url")},
        )

    def close(self):
        self.client.close()


class WikimediaCandidateAdapter:
    BASE_URL = "https://commons.wikimedia.org/w/api.php"

    def __init__(self):
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "novel-writing-agent-sfx-candidate-discovery"},
        )

    def search(self, query: str, page_size: int = 30) -> List[SfxCandidate]:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:audio {query}",
            "gsrnamespace": 6,
            "gsrlimit": min(page_size, 50),
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 0,
        }
        try:
            resp = self.client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("⚠️ Wikimedia Commons 候选搜索失败: %s", e)
            return []

        candidates = []
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            candidate = self._page_to_candidate(page, query)
            if candidate and candidate.license_commercial and candidate.source_url and candidate.license_url:
                candidates.append(candidate)
        return candidates

    def _page_to_candidate(self, page: Dict[str, Any], query: str) -> Optional[SfxCandidate]:
        imageinfo = page.get("imageinfo") or []
        if not imageinfo:
            return None
        info = imageinfo[0] or {}
        metadata = info.get("extmetadata") or {}
        license_name = _strip_markup(_metadata_value(metadata, "LicenseShortName"))
        license_url = _strip_markup(_metadata_value(metadata, "LicenseUrl"))
        license_commercial = _candidate_license_commercial(license_name, license_url)
        source_id = str(page.get("pageid") or page.get("title") or "").strip()
        if not source_id:
            return None

        name = _strip_markup(_metadata_value(metadata, "ObjectName")) or str(page.get("title") or source_id)
        source_url = str(info.get("descriptionurl") or "").strip()
        if not source_url and page.get("title"):
            source_url = f"https://commons.wikimedia.org/wiki/{quote(str(page['title']).replace(' ', '_'))}"

        return SfxCandidate(
            source="wikimedia_commons",
            source_id=source_id,
            name=name,
            description=_strip_markup(_metadata_value(metadata, "ImageDescription")),
            source_url=source_url,
            file_url=str(info.get("url") or "").strip(),
            license_name=license_name,
            license_url=license_url,
            license_version=_license_version(license_name),
            license_commercial=license_commercial,
            attribution_required=_parse_manifest_bool(_metadata_value(metadata, "AttributionRequired")) or _is_attribution_required(license_name),
            author=_strip_markup(_metadata_value(metadata, "Artist")),
            duration=0.0,
            mime_type=str(info.get("mime") or "").strip(),
            tags=[],
            query=query,
            extra={"page_title": page.get("title")},
        )

    def close(self):
        self.client.close()


def _metadata_value(metadata: Dict[str, Any], key: str) -> str:
    item = metadata.get(key)
    if isinstance(item, dict):
        return str(item.get("value") or "")
    return str(item or "")


class FreesoundAdapter:
    BASE_URL = "https://freesound.org/apiv2"

    def __init__(self, api_key: str, *, commercial_api_approved: bool = False):
        self.api_key = api_key
        self.commercial_api_approved = commercial_api_approved
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            params={"token": api_key},
            timeout=30.0,
            follow_redirects=True,
        )

    def is_license_commercial(self, license_name: str) -> bool:
        return license_name in FREESOUND_COMMERCIAL_LICENSES

    def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = 30,
        filter_str: str = "",
    ) -> List[SfxSearchResult]:
        if not self.commercial_api_approved:
            logger.warning("⚠️ Freesound API 商业使用授权未确认，跳过自动搜索")
            return []

        params: Dict[str, Any] = {
            "query": query,
            "page": page,
            "page_size": page_size,
            "fields": "id,name,description,license,previews,tags,duration,samplerate,type,url,username",
        }
        if filter_str:
            params["filter"] = filter_str

        try:
            resp = self.client.get("/search/text/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("⚠️ Freesound 搜索失败: %s", e)
            return []

        results = []
        for item in data.get("results", []):
            license_name = item.get("license", "")
            is_commercial = self.is_license_commercial(license_name)

            results.append(SfxSearchResult(
                source="freesound",
                source_id=str(item.get("id", "")),
                name=item.get("name", ""),
                description=item.get("description", ""),
                download_url="",
                preview_url=item.get("previews", {}).get("preview-hq-mp3", "") or item.get("previews", {}).get("preview-lq-mp3", ""),
                license_name=license_name,
                license_commercial=is_commercial,
                duration=float(item.get("duration", 0)),
                sample_rate=int(item.get("samplerate", 0)),
                tags=item.get("tags", []),
                source_url=item.get("url", "") or f"https://freesound.org/s/{item.get('id')}/",
                author=item.get("username", ""),
                author_url=f"https://freesound.org/people/{item.get('username', '')}/" if item.get("username") else "",
                license_url=LICENSE_URLS.get(license_name, ""),
                attribution_required=_is_attribution_required(license_name),
                extra={"freesound_id": item.get("id")},
            ))
        return results

    def get_download_url(self, sound_id: str) -> Optional[str]:
        try:
            resp = self.client.get(f"/sounds/{sound_id}/")
            resp.raise_for_status()
            data = resp.json()
            return data.get("download")
        except Exception as e:
            logger.warning("⚠️ Freesound 获取下载链接失败 (id=%s): %s", sound_id, e)
            return None

    def close(self):
        self.client.close()


class PixabayAdapter:
    BASE_URL = "https://pixabay.com/api"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def is_license_commercial(self, license_name: str) -> bool:
        return True

    def search(
        self,
        query: str,
        page: int = 1,
        per_page: int = 30,
    ) -> List[SfxSearchResult]:
        logger.warning("⚠️ Pixabay 音频下载 API 未验证，默认禁用自动搜索")
        return []

        params: Dict[str, Any] = {
            "key": self.api_key,
            "q": query,
            "category": "sound_effects",
            "page": page,
            "per_page": per_page,
        }

        try:
            resp = self.client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("⚠️ Pixabay 搜索失败: %s", e)
            return []

        results = []
        for item in data.get("hits", []):
            results.append(SfxSearchResult(
                source="pixabay",
                source_id=str(item.get("id", "")),
                name=item.get("tags", "").replace(",", " ").strip(),
                description="",
                download_url=item.get("pageURL", ""),
                preview_url="",
                license_name="pixabay",
                license_commercial=True,
                duration=0.0,
                tags=item.get("tags", "").split(","),
                extra={"pixabay_id": item.get("id")},
            ))
        return results

    def close(self):
        self.client.close()


DEFAULT_SEARCH_QUERIES: Dict[str, List[str]] = {
    "environment": [
        "rain ambient", "wind nature", "forest birds", "ocean waves",
        "city traffic", "fire crackling", "river stream", "thunderstorm",
        "cafe ambience", "night crickets",
    ],
    "action": [
        "door open close", "footsteps", "glass breaking", "sword fight",
        "gunshot", "car engine", "phone ring", "paper rustle",
        "key lock", "clock ticking",
    ],
    "emotion": [
        "heartbeat", "whisper echo", "mystery suspense", "horror atmosphere",
        "dreamy magic", "tension rise", "calm peace", "breathing",
    ],
    "transition": [
        "whoosh swoosh", "cinematic impact", "bass drop", "sweep transition",
        "stinger hit", "rise whoosh",
    ],
}


class SfxLibraryDownloader:
    def __init__(
        self,
        freesound_api_key: str = "",
        pixabay_api_key: str = "",
        output_dir: Optional[Path] = None,
        index_path: Optional[Path] = None,
        allow_freesound_commercial_api: bool = False,
        allow_pixabay_audio_api: bool = False,
    ):
        self.freesound_api_key = freesound_api_key
        self.pixabay_api_key = pixabay_api_key
        self.allow_freesound_commercial_api = allow_freesound_commercial_api
        self.allow_pixabay_audio_api = allow_pixabay_audio_api
        self.output_dir = Path(output_dir or SOUND_EFFECTS_DIR).expanduser().resolve()
        self.index_path = Path(index_path or (AUDIO_LIBRARY_DIR / "sound_effects_index.json")).expanduser().resolve()

        self._freesound: Optional[FreesoundAdapter] = None
        self._pixabay: Optional[PixabayAdapter] = None
        self._openverse: Optional[OpenverseCandidateAdapter] = None
        self._wikimedia: Optional[WikimediaCandidateAdapter] = None
        self._download_client: Optional[httpx.Client] = None

        self._stats = {
            "searched": 0,
            "filtered_license": 0,
            "filtered_duration": 0,
            "downloaded": 0,
            "skipped_existing": 0,
            "failed": 0,
        }

    def _get_freesound(self) -> Optional[FreesoundAdapter]:
        if not self.freesound_api_key:
            return None
        if self._freesound is None:
            self._freesound = FreesoundAdapter(
                self.freesound_api_key,
                commercial_api_approved=self.allow_freesound_commercial_api,
            )
        return self._freesound

    def _get_pixabay(self) -> Optional[PixabayAdapter]:
        if not self.pixabay_api_key:
            return None
        if self._pixabay is None:
            self._pixabay = PixabayAdapter(self.pixabay_api_key)
        return self._pixabay

    def _get_openverse_candidates(self) -> OpenverseCandidateAdapter:
        if self._openverse is None:
            self._openverse = OpenverseCandidateAdapter()
        return self._openverse

    def _get_wikimedia_candidates(self) -> WikimediaCandidateAdapter:
        if self._wikimedia is None:
            self._wikimedia = WikimediaCandidateAdapter()
        return self._wikimedia

    def _get_download_client(self) -> httpx.Client:
        if self._download_client is None:
            self._download_client = httpx.Client(timeout=60.0, follow_redirects=True)
        return self._download_client

    def search_source(
        self,
        source: str,
        query: str,
        max_results: int = 30,
    ) -> List[SfxSearchResult]:
        if source == "freesound":
            adapter = self._get_freesound()
            if not adapter:
                logger.warning("⚠️ Freesound API Key 未配置，跳过")
                return []
            return adapter.search(
                query,
                page_size=min(max_results, 30),
            )

        if source == "pixabay":
            if not self.allow_pixabay_audio_api:
                logger.warning("⚠️ Pixabay 音频 API 未验证，跳过")
                return []
            adapter = self._get_pixabay()
            if not adapter:
                logger.warning("⚠️ Pixabay API Key 未配置，跳过")
                return []
            return adapter.search(query, per_page=min(max_results, 30))

        logger.warning("⚠️ 不支持的音效源: %s", source)
        return []

    def search_candidate_source(
        self,
        source: str,
        query: str,
        max_results: int = 30,
    ) -> List[SfxCandidate]:
        source_key = str(source or "").strip().lower()
        if source_key == "openverse":
            return self._get_openverse_candidates().search(query, page_size=max_results)
        if source_key in {"wikimedia", "wikimedia_commons", "commons"}:
            return self._get_wikimedia_candidates().search(query, page_size=max_results)
        logger.warning("⚠️ 不支持的音效候选源: %s", source)
        return []

    def filter_results(
        self,
        results: List[SfxSearchResult],
        config: SfxDownloadConfig,
    ) -> List[SfxSearchResult]:
        filtered = []
        for r in results:
            self._stats["searched"] += 1

            if config.commercial_only and not r.license_commercial:
                self._stats["filtered_license"] += 1
                continue

            if r.duration > 0:
                if (config.min_duration > 0 and r.duration < config.min_duration) or r.duration > config.max_duration:
                    self._stats["filtered_duration"] += 1
                    continue

            filtered.append(r)
        return filtered

    def classify_result(self, result: SfxSearchResult) -> Dict[str, Any]:
        name = result.name
        desc = result.description
        tags = result.tags

        category = _normalize_category_hint(result.category_hint) or classify_category(name, desc, tags)
        style = _normalize_style_hint(result.style_hint) or classify_style(name, desc, tags)
        scenes = classify_scene(name, desc, tags)
        normalized = normalize_sfx_semantics({
            "source_id": result.source_id,
            "name": name,
            "description": desc,
            "category": f"{category}/{style}",
            "style": style,
            "tags": tags,
            "scenes": scenes,
            "duration": result.duration,
        })

        return {
            "category": str(normalized.get("category") or category).split("/", 1)[0],
            "style": str(normalized.get("style") or style),
            "scenes": list(normalized.get("scenes") or scenes),
        }

    def build_record(self, result: SfxSearchResult, classification: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            normalized_source = normalize_sfx_record_source({"source": result.source})["source"]
        except ValueError:
            logger.info("拒绝将非用户上传或 AI 生成音效写入素材库: %s", result.source)
            return None
        category = classification["category"]
        style = classification["style"]
        scenes = classification["scenes"]
        license_name = result.license_name
        attribution_required = result.attribution_required or _is_attribution_required(license_name)

        if not result.license_commercial:
            return None
        if attribution_required and not (result.author and result.source_url and result.license_url):
            logger.warning("⚠️ CC-BY 音效缺少署名元数据，拒绝入库: %s (%s)", result.name, result.source_id)
            return None

        effect_id = generate_effect_id(category, result.source, result.source_id)
        ext = "mp3"
        file_path = generate_file_path(category, style, effect_id, ext)
        now = _utc_now_iso()
        duration_bucket = _duration_bucket(result.duration)
        manifest_attribution = str(result.extra.get("attribution_text") or "").strip()
        attribution_text = manifest_attribution or (_build_attribution_text(result) if attribution_required else "")
        source_payload_json = dict(result.extra.get("source_payload_json") or {})

        record = {
            "id": effect_id,
            "name": sanitize_filename(result.name),
            "category": f"{category}/{style}",
            "file_path": file_path,
            "description": result.description or result.name,
            "tags": list(set(result.tags + scenes)),
            "source": normalized_source,
            "source_id": result.source_id,
            "source_url": result.source_url,
            "author": result.author,
            "author_url": result.author_url,
            "license": license_name,
            "license_url": result.license_url or LICENSE_URLS.get(license_name, ""),
            "license_version": _license_version(license_name),
            "license_commercial": result.license_commercial,
            "attribution_required": attribution_required,
            "attribution_text": attribution_text,
            "redistribution_allowed": False,
            "raw_asset_exposure": "internal_only",
            "duration": result.duration,
            "duration_bucket": duration_bucket,
            "scenes": scenes,
            "style": style,
            "retrieved_at": now,
            "license_checked_at": now,
            "source_payload_json": source_payload_json,
        }
        return normalize_sfx_semantics(record)

    def import_local_assets(
        self,
        source_dir: Path,
        manifest_path: Path,
        *,
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        rows = _load_manifest_rows(Path(manifest_path))
        source_root = Path(source_dir)
        stats = {
            "candidates": 0,
            "imported": 0,
            "rejected_license": 0,
            "rejected_source": 0,
            "rejected_file": 0,
            "rejected_quality": 0,
            "skipped_existing": 0,
        }
        records: List[Dict[str, Any]] = []

        for row in rows:
            stats["candidates"] += 1
            source_file = self._resolve_local_asset_path(source_root, row)
            if not source_file:
                stats["rejected_file"] += 1
                continue

            result = _manifest_row_to_search_result(row, source_file.stem)
            if not is_allowed_sfx_source(result.source):
                stats["rejected_source"] += 1
                continue
            if not _local_manifest_license_valid(result):
                stats["rejected_license"] += 1
                continue

            classification = self.classify_result(result)
            record = self.build_record(result, classification)
            if not record:
                stats["rejected_license"] += 1
                continue

            target_path = self._target_path_for_record(record, source_file.suffix)
            if dry_run:
                record["file_path"] = self._relative_audio_library_path(target_path)
                records.append(record)
                continue

            copied_file = False
            if target_path.exists() and not overwrite:
                stats["skipped_existing"] += 1
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target_path)
                copied_file = True
            record["file_path"] = self._relative_audio_library_path(target_path)

            if not self._finalize_download_record(record, target_path):
                stats["rejected_quality"] += 1
                if copied_file:
                    try:
                        target_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                continue

            try:
                self._register_to_index(record)
            except Exception:
                if copied_file:
                    try:
                        target_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("音效索引写入失败后无法回滚文件: %s", target_path)
                raise
            stats["imported"] += 1
            records.append(record)

        return {"stats": stats, "records": records}

    def _resolve_local_asset_path(self, source_root: Path, row: Dict[str, Any]) -> Optional[Path]:
        filename = str(row.get("file") or row.get("path") or "").strip()
        if not filename:
            return None

        candidate = Path(filename)
        if not candidate.is_absolute():
            candidate = source_root / candidate
        try:
            resolved = candidate.resolve(strict=False)
            root = source_root.resolve(strict=False)
        except OSError:
            return None

        try:
            resolved.relative_to(root)
        except ValueError:
            logger.warning("鈿狅笍 鏈湴闊虫晥璺緞瓒呭嚭瀵煎叆鐩綍锛屾嫆缁? %s", filename)
            return None

        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def _target_path_for_record(self, record: Dict[str, Any], source_suffix: str) -> Path:
        suffix = (source_suffix or ".mp3").lower().lstrip(".")
        category, _, style = str(record.get("category") or "action/realistic").partition("/")
        style = style or "realistic"
        file_path = generate_file_path(category, style, record["id"], suffix)
        return self.output_dir.parent / file_path

    def _relative_audio_library_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.output_dir.parent).as_posix()
        except ValueError:
            return path.as_posix()

    def discover_public_candidates(
        self,
        sources: Optional[List[str]] = None,
        queries: Optional[List[str]] = None,
        output_path: Optional[Path] = None,
        *,
        max_per_source: int = 30,
        request_delay: float = 1.0,
    ) -> Dict[str, Any]:
        sources = sources or ["openverse", "wikimedia_commons"]
        if not queries:
            queries = []
            for category_queries in DEFAULT_SEARCH_QUERIES.values():
                queries.extend(category_queries[:2])

        stats = {
            "searched": 0,
            "candidates": 0,
            "filtered_duplicate": 0,
            "exported": 0,
        }
        seen: Set[str] = set()
        candidates: List[SfxCandidate] = []

        for source in sources:
            for query in queries:
                stats["searched"] += 1
                results = self.search_candidate_source(source, query, max_per_source)
                for candidate in results:
                    key = f"{candidate.source}:{candidate.source_id}"
                    if key in seen:
                        stats["filtered_duplicate"] += 1
                        continue
                    seen.add(key)
                    candidates.append(candidate)
                time.sleep(request_delay)

        stats["candidates"] = len(candidates)
        target_path = output_path or (self.index_path.parent / "sfx_candidates.jsonl")
        self._write_candidates_jsonl(candidates, target_path)
        stats["exported"] = len(candidates)
        return {
            "stats": stats,
            "candidates": candidates,
            "output_path": str(target_path),
        }

    def _write_candidates_jsonl(self, candidates: List[SfxCandidate], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for candidate in candidates:
                f.write(json.dumps(candidate.to_record(), ensure_ascii=False, sort_keys=True) + "\n")

    def export_attribution_credits(
        self,
        *,
        jsonl_path: Optional[Path] = None,
        markdown_path: Optional[Path] = None,
        used_effect_ids: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        records = self._load_index_records()
        used_ids = {str(item) for item in used_effect_ids} if used_effect_ids is not None else None
        stats = {
            "indexed": len(records),
            "filtered_unused": 0,
            "skipped_no_attribution": 0,
            "deduplicated": 0,
            "credits": 0,
        }
        credits: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        for record in records:
            effect_id = str(record.get("id") or "").strip()
            if used_ids is not None and effect_id not in used_ids:
                stats["filtered_unused"] += 1
                continue
            credit = self._build_credit_record(record)
            if not credit:
                stats["skipped_no_attribution"] += 1
                continue
            dedupe_key = self._credit_dedupe_key(credit)
            if dedupe_key in seen_keys:
                stats["deduplicated"] += 1
                continue
            seen_keys.add(dedupe_key)
            credits.append(credit)

        stats["credits"] = len(credits)
        target_jsonl = Path(jsonl_path) if jsonl_path else self.index_path.parent / "license_manifest.jsonl"
        target_markdown = Path(markdown_path) if markdown_path else self.index_path.parent / "CREDITS.md"
        self._write_credit_jsonl(credits, target_jsonl)
        self._write_credit_markdown(credits, target_markdown)
        return {
            "stats": stats,
            "credits": credits,
            "jsonl_path": str(target_jsonl),
            "markdown_path": str(target_markdown),
        }

    def _load_index_records(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        with self.index_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            return [item for item in raw.values() if isinstance(item, dict)]
        return []

    def _build_credit_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        attribution_required = _parse_manifest_bool(record.get("attribution_required"))
        license_name = str(record.get("license") or "").strip()
        if not attribution_required and not _is_attribution_required(license_name):
            return None

        effect_id = str(record.get("id") or "").strip()
        attribution_text = str(record.get("attribution_text") or "").strip()
        name = str(record.get("name") or effect_id).strip()
        author = str(record.get("author") or "").strip()
        source_url = str(record.get("source_url") or "").strip()
        license_url = str(record.get("license_url") or "").strip()
        if not attribution_text:
            if not (name and author and source_url and license_name and license_url):
                return None
            attribution_text = f"{name} by {author} ({source_url}), licensed under {license_name} ({license_url})"

        return {
            "effect_id": effect_id,
            "name": name,
            "source": str(record.get("source") or "").strip(),
            "source_id": str(record.get("source_id") or "").strip(),
            "source_url": source_url,
            "author": author,
            "author_url": str(record.get("author_url") or "").strip(),
            "license": license_name,
            "license_url": license_url,
            "license_version": str(record.get("license_version") or _license_version(license_name)).strip(),
            "attribution_text": attribution_text,
            "file_path": str(record.get("file_path") or "").strip(),
            "raw_asset_exposure": str(record.get("raw_asset_exposure") or "internal_only").strip(),
            "redistribution_allowed": _parse_manifest_bool(record.get("redistribution_allowed")),
        }

    def _credit_dedupe_key(self, credit: Dict[str, Any]) -> str:
        parts = [
            str(credit.get("attribution_text") or "").strip().lower(),
            str(credit.get("source_url") or "").strip().lower(),
            str(credit.get("license_url") or "").strip().lower(),
        ]
        return "|".join(parts)

    def _write_credit_jsonl(self, credits: List[Dict[str, Any]], jsonl_path: Path) -> None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w", encoding="utf-8") as f:
            for credit in credits:
                f.write(json.dumps(credit, ensure_ascii=False, sort_keys=True) + "\n")

    def _write_credit_markdown(self, credits: List[Dict[str, Any]], markdown_path: Path) -> None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Audio Credits", ""]
        if not credits:
            lines.append("No third-party audio attributions are required.")
        else:
            lines.append("The following third-party audio assets require attribution:")
            lines.append("")
            for credit in credits:
                text = str(credit.get("attribution_text") or "").strip()
                lines.append(f"- {text}")
        lines.append("")
        markdown_path.write_text("\n".join(lines), encoding="utf-8")

    def download_file(
        self,
        url: str,
        target_path: Path,
        overwrite: bool = False,
    ) -> bool:
        if target_path.exists() and not overwrite:
            return True

        try:
            client = self._get_download_client()
            resp = client.get(url)
            resp.raise_for_status()

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(resp.content)
            return True
        except Exception as e:
            logger.warning("⚠️ 下载失败 (%s): %s", url, e)
            return False

    def download_and_register(
        self,
        result: SfxSearchResult,
        config: SfxDownloadConfig,
    ) -> Optional[Dict[str, Any]]:
        classification = self.classify_result(result)
        record = self.build_record(result, classification)
        if not record:
            self._stats["failed"] += 1
            return None

        target_path = self.output_dir.parent / record["file_path"]

        if config.dry_run:
            logger.info("[预演] 将下载: %s → %s", result.name, record["file_path"])
            return record

        if not self._source_download_allowed(result.source, config):
            self._stats["failed"] += 1
            return None

        if target_path.exists() and not config.overwrite:
            self._stats["skipped_existing"] += 1
            logger.debug("跳过已存在: %s", target_path)
            if not self._finalize_download_record(record, target_path):
                self._stats["failed"] += 1
                return None
            self._register_to_index(record)
            return record

        download_url = result.download_url
        if not download_url:
            if result.source == "freesound" and self._get_freesound():
                download_url = self._get_freesound().get_download_url(result.source_id) or ""
            if not download_url:
                self._stats["failed"] += 1
                logger.warning("⚠️ 无可用下载链接: %s (%s)", result.name, result.source)
                return None

        success = self.download_file(download_url, target_path, config.overwrite)
        if not success:
            self._stats["failed"] += 1
            return None
        if not self._finalize_download_record(record, target_path):
            self._stats["failed"] += 1
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

        self._stats["downloaded"] += 1
        logger.info(
            "✅ 下载完成: %s → %s (%s, %s)",
            result.name,
            record["file_path"],
            record["category"],
            result.license_name,
        )

        self._register_to_index(record)
        return record

    def _source_download_allowed(self, source: str, config: SfxDownloadConfig) -> bool:
        source_key = str(source or "").strip().lower()
        if source_key == "freesound":
            allowed = self.allow_freesound_commercial_api or config.allow_freesound_commercial_api
            if not allowed:
                logger.warning("⚠️ Freesound API 商业使用授权未确认，拒绝自动下载")
            return allowed
        if source_key == "pixabay":
            allowed = self.allow_pixabay_audio_api or config.allow_pixabay_audio_api
            if not allowed:
                logger.warning("⚠️ Pixabay 音频 API 未验证，拒绝自动下载")
            return allowed
        return True

    def _finalize_download_record(self, record: Dict[str, Any], target_path: Path) -> bool:
        file_info = _inspect_downloaded_file(target_path)
        if not file_info.get("valid"):
            logger.warning("⚠️ 下载文件校验失败: %s reason=%s", target_path, file_info.get("reason"))
            return False

        record.update({
            "sha256": file_info["sha256"],
            "file_size": file_info["file_size"],
            "content_type": file_info["content_type"],
        })

        quality = self._assess_downloaded_quality(str(target_path))
        if quality.get("quality_status") == "rejected" and self._normalize_audio_loudness(target_path):
            normalized_info = _inspect_downloaded_file(target_path)
            if normalized_info.get("valid"):
                record.update({
                    "sha256": normalized_info["sha256"],
                    "file_size": normalized_info["file_size"],
                    "content_type": normalized_info["content_type"],
                    "loudness_normalized": True,
                })
                quality = self._assess_downloaded_quality(str(target_path))

        record.update({
            "quality_score": quality.get("quality_score", 0.0),
            "quality_grade": quality.get("quality_grade", "D"),
            "quality_status": quality.get("quality_status", "rejected"),
        })
        if record.get("quality_status") == "rejected":
            return False

        self._attach_cloud_storage_metadata(record, target_path)
        return True

    def _normalize_audio_loudness(self, target_path: Path) -> bool:
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(target_path))
            if not audio or not math.isfinite(float(audio.dBFS)):
                return False

            peak_headroom_gain = -3.0 - float(audio.max_dBFS)
            average_gain = -24.0 - float(audio.dBFS)
            gain_db = min(average_gain, peak_headroom_gain)
            if gain_db <= 0:
                return False

            normalized = audio.apply_gain(gain_db)
            suffix = target_path.suffix.lower()
            export_format = {
                ".oga": "ogg",
                ".ogg": "ogg",
                ".mp3": "mp3",
                ".wav": "wav",
                ".flac": "flac",
            }.get(suffix, suffix.lstrip(".") or "wav")
            temp_path = target_path.with_name(f"{target_path.stem}.normalized.tmp{target_path.suffix}")
            normalized.export(str(temp_path), format=export_format)
            shutil.move(str(temp_path), str(target_path))
            return True
        except Exception as exc:
            logger.debug("音效响度规范化跳过: %s (%s)", target_path, exc)
            return False

    def _attach_cloud_storage_metadata(self, record: Dict[str, Any], target_path: Path) -> None:
        relative_path = str(record.get("file_path") or "").strip()
        if not relative_path:
            relative_path = self._relative_audio_library_path(target_path)
        try:
            record.update(
                upload_audio_library_asset(
                    local_path=target_path,
                    relative_path=relative_path,
                    library_type="sfx",
                )
            )
        except Exception as exc:
            logger.warning("鈿狅笍 音效素材云端元数据写入失败，保留本地索引: %s", exc)

    def _assess_downloaded_quality(self, file_path: str) -> Dict[str, Any]:
        designer = SoundEffectDesigner(index_path=str(self.index_path))
        return designer._assess_audio_quality(file_path)

    def _register_to_index(self, record: Dict[str, Any]) -> None:
        record = normalize_sfx_record_source(record)
        temp_path = self.index_path.with_name(f"{self.index_path.name}.tmp")
        try:
            index_data: List[Dict[str, Any]] = []
            if self.index_path.exists():
                with self.index_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    index_data = raw
                elif isinstance(raw, dict):
                    index_data = list(raw.values())

            effect_id = record.get("id", "")
            index_data = [r for r in index_data if r.get("id") != effect_id]
            index_data.append(record)

            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(self.index_path)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("音效索引临时文件清理失败: %s", temp_path)
            raise

    def run(self, config: Optional[SfxDownloadConfig] = None) -> Dict[str, Any]:
        config = config or SfxDownloadConfig()
        self.allow_freesound_commercial_api = (
            self.allow_freesound_commercial_api or config.allow_freesound_commercial_api
        )
        self.allow_pixabay_audio_api = self.allow_pixabay_audio_api or config.allow_pixabay_audio_api
        self._stats = {
            "searched": 0,
            "filtered_license": 0,
            "filtered_duration": 0,
            "downloaded": 0,
            "skipped_existing": 0,
            "failed": 0,
        }

        queries = config.search_queries
        if not queries:
            for cat in config.categories:
                queries.extend(DEFAULT_SEARCH_QUERIES.get(cat, []))

        all_results: List[SfxSearchResult] = []
        for source in config.sources:
            for query in queries:
                logger.info("🔍 搜索 %s: %s", source, query)
                results = self.search_source(source, query, config.max_per_source)
                all_results.extend(results)
                time.sleep(config.request_delay)

        seen_ids: Set[str] = set()
        unique_results = []
        for r in all_results:
            key = f"{r.source}:{r.source_id}"
            if key not in seen_ids:
                seen_ids.add(key)
                unique_results.append(r)

        filtered = self.filter_results(unique_results, config)
        logger.info(
            "📊 搜索 %d 条 → 去重 %d → 许可/时长过滤后 %d 条",
            len(all_results),
            len(unique_results),
            len(filtered),
        )

        downloaded_records = []
        for result in filtered:
            record = self.download_and_register(result, config)
            if record:
                downloaded_records.append(record)

        logger.info(
            "🏁 下载完成: 成功 %d, 跳过 %d, 失败 %d (许可过滤 %d, 时长过滤 %d)",
            self._stats["downloaded"],
            self._stats["skipped_existing"],
            self._stats["failed"],
            self._stats["filtered_license"],
            self._stats["filtered_duration"],
        )

        return {
            "stats": dict(self._stats),
            "records": downloaded_records,
        }

    def close(self):
        if self._freesound:
            self._freesound.close()
        if self._pixabay:
            self._pixabay.close()
        if self._openverse:
            self._openverse.close()
        if self._wikimedia:
            self._wikimedia.close()
        if self._download_client:
            self._download_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
