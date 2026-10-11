from __future__ import annotations

import os
import sys
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
from app.services.dreamweaver.voice_reference_bridge import (
    extract_script_speakers,
    inject_voice_references_for_storyboard,
    resolve_voice_references,
)


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[VoiceReferenceAsset.__table__])
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _materialized_asset(
    db,
    *,
    asset_id: str,
    speaker: str,
    storage_uri: str,
    sha256: str = "sha-1",
    owner_user_id: int | None = None,
    revoked: bool = False,
    deleted: bool = False,
    source_type: str = "user_recording",
) -> VoiceReferenceAsset:
    from datetime import datetime, timezone

    asset = VoiceReferenceAsset(
        asset_id=asset_id,
        owner_user_id=owner_user_id,
        reference_kind="user_recording",
        reference_field="speaker",
        provider="minimax",
        source_type=source_type,
        speaker=speaker,
        storage_uri=storage_uri,
        sha256=sha256,
        duration_s=15.0,
        content_type="audio/mpeg",
        authorization_scope="account",
        revoked_at=datetime.now(timezone.utc) if revoked else None,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(asset)
    db.commit()
    return asset


class TestResolveVoiceReferences:
    def test_resolves_materialized_asset_by_speaker(self):
        db = _build_session()
        _materialized_asset(db, asset_id="vra-1", speaker="林晚", storage_uri="oss://voice/linwan.mp3")

        result = resolve_voice_references(db, speakers=["林晚"], run_id="run-1")

        ref = result["voice_reference_audio"]["林晚"]
        assert ref["asset_id"] == "vra-1"
        assert ref["storage_uri"] == "oss://voice/linwan.mp3"
        assert result["missing_speakers"] == []
        prov = result["provenance"][0]
        assert prov["source_resource_id"] == "voice_ref:vra-1"
        assert prov["used_in"] == "dreamweaver:run-1"
        assert prov["reuse_mode"] == "read_only_audio_reference"

    def test_missing_speaker_reported(self):
        db = _build_session()
        result = resolve_voice_references(db, speakers=["陈默"], run_id="run-1")
        assert result["voice_reference_audio"] == {}
        assert result["missing_speakers"] == ["陈默"]
        assert result["provenance"] == []

    def test_non_materialized_asset_skipped(self):
        db = _build_session()
        # system_voice 类资产无 storage_uri（仅 speaker 引用），不能作生成端参考
        db.add(VoiceReferenceAsset(
            asset_id="sv-1", reference_kind="system_voice", reference_field="speaker",
            source_type="seed_system", speaker="林晚", authorization_scope="account",
        ))
        db.commit()

        result = resolve_voice_references(db, speakers=["林晚"], run_id="run-1")
        assert result["voice_reference_audio"] == {}
        assert result["missing_speakers"] == ["林晚"]

    def test_revoked_and_deleted_excluded(self):
        db = _build_session()
        _materialized_asset(db, asset_id="vra-r", speaker="林晚", storage_uri="oss://a.mp3", revoked=True)
        _materialized_asset(db, asset_id="vra-d", speaker="陈默", storage_uri="oss://b.mp3", deleted=True)

        result = resolve_voice_references(db, speakers=["林晚", "陈默"], run_id="run-1")
        assert result["voice_reference_audio"] == {}
        assert set(result["missing_speakers"]) == {"林晚", "陈默"}

    def test_owner_isolation(self):
        db = _build_session()
        _materialized_asset(
            db, asset_id="vra-u2", speaker="林晚", storage_uri="oss://a.mp3", owner_user_id=2,
        )

        # 指定 owner=1 查不到 owner=2 的资产
        result = resolve_voice_references(db, speakers=["林晚"], owner_user_id=1, run_id="run-1")
        assert result["missing_speakers"] == ["林晚"]
        # owner=2 可查到
        result2 = resolve_voice_references(db, speakers=["林晚"], owner_user_id=2, run_id="run-1")
        assert result2["voice_reference_audio"]["林晚"]["asset_id"] == "vra-u2"

    def test_latest_asset_wins_for_duplicate_speaker(self):
        db = _build_session()
        _materialized_asset(db, asset_id="vra-old", speaker="林晚", storage_uri="oss://old.mp3")
        _materialized_asset(db, asset_id="vra-new", speaker="林晚", storage_uri="oss://new.mp3")

        result = resolve_voice_references(db, speakers=["林晚"], run_id="run-1")
        assert result["voice_reference_audio"]["林晚"]["asset_id"] == "vra-new"


class TestInjectForStoryboard:
    def test_extract_speakers_from_script_payload(self):
        payload = {
            "script_document": {"scenes": [{"scene_id": "S1", "characters": ["林晚", "陈默"]}]},
            "script_entities": {"characters": [{"name": "林晚"}]},
        }
        assert extract_script_speakers(payload) == ["林晚", "陈默"]

    def test_extract_speakers_empty_payload(self):
        assert extract_script_speakers({}) == []

    def test_inject_populates_payload_and_provenance(self):
        db = _build_session()
        _materialized_asset(db, asset_id="vra-1", speaker="林晚", storage_uri="oss://a.mp3")
        payload = {
            "script_document": {"scenes": [{"scene_id": "S1", "characters": ["林晚", "陈默"]}]},
        }

        report = inject_voice_references_for_storyboard(db, payload, run_id="run-9")

        assert payload["voice_reference_audio"]["林晚"]["asset_id"] == "vra-1"
        assert payload["resource_provenance"][0]["used_in"] == "dreamweaver:run-9"
        assert "陈默" in report["missing_speakers"]

    def test_inject_no_speakers_is_noop(self):
        db = _build_session()
        payload = {}
        report = inject_voice_references_for_storyboard(db, payload, run_id="run-9")
        assert "voice_reference_audio" not in payload
        assert report == {}
