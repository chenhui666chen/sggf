from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.db.base import Base
from app.models.audio_library_asset import AudioLibraryAsset
from app.services.audiobook.audio_library_asset_repository import (
    audio_library_asset_to_record,
    list_audio_library_asset_records,
    upsert_audio_library_asset,
)


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[AudioLibraryAsset.__table__])
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_upsert_sfx_json_record_to_db_and_restore_api_record():
    db = _build_session()
    source_record = {
        "id": "rain_sfx",
        "name": "Rain ambience",
        "category": "environment/peaceful",
        "file_path": "sound_effects/environment/rain.ogg",
        "description": "Licensed rain ambience",
        "tags": ["rain", "weather"],
        "source": "user_upload",
        "source_id": "upload:rain_sfx",
        "author": "test_user",
        "license": "user_authorized",
        "license_commercial": True,
        "attribution_required": False,
        "quality_score": 85.0,
        "quality_grade": "B",
        "quality_status": "accepted",
        "storage_mode": "local_cache",
        "storage_driver": "local_fs",
        "local_cache_path": "sound_effects/environment/rain.ogg",
        "asset_scope": "shared_library",
        "sha256": "abc123",
        "file_size": 12345,
        "content_type": "audio/ogg",
    }

    asset = upsert_audio_library_asset(db, "sfx", source_record)
    db.commit()

    assert asset.library_type == "sfx"
    assert asset.asset_key == "rain_sfx"
    assert asset.name == "Rain ambience"
    assert asset.license_commercial is True
    assert asset.tags == ["rain", "weather"]

    restored = audio_library_asset_to_record(asset)

    assert restored["id"] == "rain_sfx"
    assert restored["name"] == "Rain ambience"
    assert restored["category"] == "environment/peaceful"
    assert restored["file_path"] == "sound_effects/environment/rain.ogg"
    assert restored["storage_mode"] == "local_cache"
    assert restored["asset_scope"] == "shared_library"
    assert restored["sha256"] == "abc123"
    assert restored["file_size"] == 12345
    assert restored["content_type"] == "audio/ogg"


def test_list_audio_library_asset_records_filters_by_library_type():
    db = _build_session()
    upsert_audio_library_asset(
        db,
        "sfx",
        {
            "id": "door_sfx",
            "name": "Door",
            "category": "action/realistic",
            "file_path": "sound_effects/action/door.ogg",
            "source": "ai_generated",
            "tags": ["door"],
        },
    )
    upsert_audio_library_asset(
        db,
        "music",
        {
            "id": "tense_music",
            "style": "cinematic",
            "mood": "tense",
            "bucket": "tension",
            "file_path": "music_cache/tense.mp3",
            "source": "mureka",
            "duration": 30.0,
        },
    )
    db.commit()

    sfx_records = list_audio_library_asset_records(db, "sfx")
    music_records = list_audio_library_asset_records(db, "music")

    assert [item["id"] for item in sfx_records] == ["door_sfx"]
    assert sfx_records[0]["category"] == "action/realistic"
    assert [item["id"] for item in music_records] == ["tense_music"]
    assert music_records[0]["style"] == "cinematic"
