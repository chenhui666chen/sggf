from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for path in (ROOT_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.db.base import Base
from app.models.audio_library_asset import AudioLibraryAsset
from app.services.audiobook.audio_library_asset_repository import (
    list_audio_library_asset_records,
    upsert_audio_library_asset,
)
from app.services.audiobook.audio_library_source_policy import (
    ALLOWED_SFX_SOURCES,
    is_allowed_sfx_source,
    normalize_sfx_source,
)


def test_sfx_source_policy_allows_only_user_upload_and_ai_generated() -> None:
    assert ALLOWED_SFX_SOURCES == {"user_upload", "ai_generated"}
    assert normalize_sfx_source("user_upload") == "user_upload"
    assert normalize_sfx_source("vidu") == "ai_generated"
    assert normalize_sfx_source("ai") == "ai_generated"
    assert is_allowed_sfx_source("ai_generated")
    assert not is_allowed_sfx_source("freesound")


@pytest.mark.parametrize(
    "source",
    ["", "local_authorized", "openverse", "wikimedia_commons", "freesound", "pixabay"],
)
def test_sfx_source_policy_rejects_legacy_sources(source: str) -> None:
    with pytest.raises(ValueError, match="user_upload.*ai_generated"):
        normalize_sfx_source(source)


def test_sfx_repository_normalizes_ai_alias_and_filters_legacy_rows() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[AudioLibraryAsset.__table__])
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        asset = upsert_audio_library_asset(
            db,
            "sfx",
            {
                "id": "generated-train",
                "name": "火车站环境",
                "file_path": "sound_effects/generated/train.mp3",
                "source": "vidu",
            },
        )
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="old-freesound",
                name="旧素材",
                file_path="sound_effects/old.wav",
                source="freesound",
            )
        )
        db.commit()

        assert asset.source == "ai_generated"
        assert [row["id"] for row in list_audio_library_asset_records(db, "sfx")] == [
            "generated-train"
        ]
    finally:
        db.close()
        engine.dispose()
