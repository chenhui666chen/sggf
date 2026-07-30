from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
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
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.services.audiobook.scene_engine.preview_reference_asset import (
    PreviewReferenceAsset,
)
from app.services.audiobook.voice_reference_asset_repository import (
    build_voice_reference_asset_id,
    get_voice_reference_asset,
    persist_materialized_reference,
    persist_speaker_reference,
    upsert_voice_reference_asset,
    voice_reference_asset_to_record,
)


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[VoiceReferenceAsset.__table__])
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _preview_asset(sha256: str = "sha-preview-1") -> PreviewReferenceAsset:
    return PreviewReferenceAsset(
        source_model="minimax-speech-2.8-hd",
        source_voice_id="voice-abc",
        source_preview_cache_key="cache-key-1",
        storage_path=Path("/tmp/previews/minimax/sha.mp3"),
        source_url="https://oss.example.com/preview.mp3",
        sha256=sha256,
        duration_s=12.5,
        content_type="audio/mpeg",
        reference={"audio_data": "AAAA"},
    )


def test_persist_speaker_reference_creates_stable_asset():
    db = _build_session()
    asset = persist_speaker_reference(
        db,
        provider="volcengine",
        source_model="seed-audio-1.0",
        speaker="zh_female_vv_uranus_bigtts",
    )
    db.commit()

    assert asset.reference_kind == "system_voice"
    assert asset.reference_field == "speaker"
    assert asset.source_type == "seed_system"
    assert asset.authorization_scope == "account"
    assert asset.speaker == "zh_female_vv_uranus_bigtts"
    assert asset.source_voice_id == "zh_female_vv_uranus_bigtts"
    assert asset.asset_id.startswith("sv_")


def test_speaker_reference_upsert_is_idempotent():
    db = _build_session()
    first = persist_speaker_reference(
        db,
        provider="volcengine",
        source_model="seed-audio-1.0",
        speaker="zh_female_vv_uranus_bigtts",
    )
    db.commit()
    second = persist_speaker_reference(
        db,
        provider="volcengine",
        source_model="seed-audio-1.0",
        speaker="zh_female_vv_uranus_bigtts",
        metadata={"note": "updated"},
    )
    db.commit()

    assert first.asset_id == second.asset_id
    assert db.query(VoiceReferenceAsset).count() == 1
    assert second.metadata_json == {"note": "updated"}


def test_persist_materialized_reference_from_preview_asset():
    db = _build_session()
    preview = _preview_asset()
    asset = persist_materialized_reference(
        db,
        preview,
        provider="minimax",
        owner_user_id=7,
        authorized_by_user_id=7,
        authorization_scope="provider_preview",
        authorization_basis="synthetic_design",
        authorization_version="v1",
        authorized_at=datetime.now(timezone.utc),
    )
    db.commit()

    assert asset.reference_kind == "provider_preview"
    assert asset.reference_field == "audio_data"
    assert asset.source_type == "provider_preview"
    assert asset.authorization_scope == "provider_preview"
    assert asset.storage_uri == str(Path("/tmp/previews/minimax/sha.mp3"))
    assert asset.source_url == "https://oss.example.com/preview.mp3"
    assert asset.sha256 == "sha-preview-1"
    assert asset.duration_s == pytest.approx(12.5)
    assert asset.content_type == "audio/mpeg"
    assert asset.source_preview_cache_key == "cache-key-1"
    assert asset.speaker is None
    assert asset.asset_id.startswith("pp_")


def test_materialized_asset_id_changes_with_audio_hash():
    first = build_voice_reference_asset_id(
        reference_kind="provider_preview",
        source_model="minimax-speech-2.8-hd",
        source_voice_id="voice-abc",
        sha256="hash-a",
    )
    second = build_voice_reference_asset_id(
        reference_kind="provider_preview",
        source_model="minimax-speech-2.8-hd",
        source_voice_id="voice-abc",
        sha256="hash-b",
    )
    assert first != second


def test_user_recording_authorization_fields_persist():
    db = _build_session()
    asset = upsert_voice_reference_asset(
        db,
        {
            "reference_kind": "user_recording",
            "provider": "user_upload",
            "owner_user_id": 7,
            "authorized_by_user_id": 7,
            "sha256": "user-audio-sha",
            "storage_uri": "/tmp/uploads/voice.wav",
            "authorization_scope": "user_uploaded",
            "authorization_basis": "self_voice",
            "authorization_version": "consent-2026-07",
            "authorized_at": datetime.now(timezone.utc),
        },
    )
    db.commit()

    assert asset.source_type == "user_upload"
    assert asset.reference_field == "audio_data"
    assert asset.authorization_scope == "user_uploaded"
    assert asset.authorization_version == "consent-2026-07"
    assert asset.asset_id.startswith("ur_")


def test_record_round_trip_and_lookup():
    db = _build_session()
    persist_speaker_reference(
        db,
        provider="volcengine",
        source_model="seed-audio-1.0",
        speaker="zh_male_test_uranus_bigtts",
    )
    db.commit()
    asset_id = build_voice_reference_asset_id(
        reference_kind="system_voice",
        source_model="seed-audio-1.0",
        speaker="zh_male_test_uranus_bigtts",
    )
    fetched = get_voice_reference_asset(db, asset_id)
    assert fetched is not None
    record = voice_reference_asset_to_record(fetched)
    assert record["asset_id"] == asset_id
    assert record["reference_field"] == "speaker"
    assert record["speaker"] == "zh_male_test_uranus_bigtts"
    assert record["authorization_scope"] == "account"

    assert get_voice_reference_asset(db, "does-not-exist") is None


def test_invalid_reference_kind_rejected():
    db = _build_session()
    with pytest.raises(ValueError):
        upsert_voice_reference_asset(db, {"reference_kind": "mystery_kind"})
