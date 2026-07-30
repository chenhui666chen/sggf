from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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

from app.db.base import Base
from app.models.voice_asset_billing_ledger import VoiceAssetBillingLedger
from app.models.voice_pool_publication import VoicePoolPublication
from app.models.voice_pool_rating import VoicePoolRating
from app.models.voice_reference_asset import VoiceReferenceAsset
from app.scripts.dry_run_voice_test_cleanup import (
    build_cleanup_manifest,
    build_dry_run_report,
    scan_local_voice_root,
    storage_type_for_uri,
)


def _build_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (
        VoiceReferenceAsset,
        VoicePoolPublication,
        VoicePoolRating,
        VoiceAssetBillingLedger,
    ):
        model.__table__.create(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_storage_type_for_uri_never_returns_the_uri() -> None:
    assert storage_type_for_uri("oss://bucket/private/voice.mp3") == "oss"
    assert storage_type_for_uri("https://cdn.example.com/reference.mp3") == "http"
    assert storage_type_for_uri("backend/data/mimo_voice_assets/clone.wav") == "local"
    assert storage_type_for_uri("") == "unknown"


def test_scan_local_voice_root_reports_metadata_without_audio_content(tmp_path: Path) -> None:
    root = tmp_path / "mimo_voice_assets"
    clone_dir = root / "clone_samples"
    clone_dir.mkdir(parents=True)
    (root / "index.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "mimo_clone_test",
                        "asset_type": "clone",
                        "model": "mimo-v2.5-tts-voiceclone",
                        "owner_user_id": 7,
                        "audio_path": "clone_samples/mimo_clone_test.wav",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    audio_path = clone_dir / "mimo_clone_test.wav"
    audio_path.write_bytes(b"test-audio-bytes")

    result = scan_local_voice_root(root, provider="mimo")

    serialized = json.dumps(result, ensure_ascii=False)
    assert result["provider"] == "mimo"
    assert result["index_record_count"] == 1
    assert result["file_count"] == 2
    assert result["audio_file_count"] == 1
    assert result["audio_bytes"] == len(b"test-audio-bytes")
    assert result["action"] == "delete test index records and controlled local voice files"
    assert "test-audio-bytes" not in serialized
    assert str(audio_path) not in serialized


def test_scan_local_voice_mapping_file_reports_voice_ids(tmp_path: Path) -> None:
    mapping_path = tmp_path / "cosyvoice_clone_names.json"
    mapping_path.write_text(
        json.dumps({"cosyvoice-test-voice": "测试音色"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = scan_local_voice_root(mapping_path, provider="cosyvoice")

    assert result["index_record_count"] == 1
    assert result["items"][0]["id"] == "cosyvoice-test-voice"
    assert result["items"][0]["asset_type"] == "clone"
    assert result["file_count"] == 1


def test_report_is_non_destructive_and_excludes_system_voice(tmp_path: Path) -> None:
    db = _build_session()
    db.add(
        VoiceReferenceAsset(
            asset_id="sv_system_test",
            reference_kind="system_voice",
            reference_field="speaker",
            source_type="seed_system",
            source_model="seed-audio-1.0",
            source_voice_id="seed_system_voice",
            authorization_scope="account",
            tags=[],
            metadata_json={},
            source_payload_json={},
        )
    )
    custom_asset = VoiceReferenceAsset(
        asset_id="ur_test_voice",
        reference_kind="user_recording",
        reference_field="audio_data",
        source_type="user_upload",
        source_model="user-upload",
        source_voice_id="upload-test",
        owner_user_id=7,
        storage_uri="oss://bucket/private/test.wav",
        authorization_scope="user_uploaded",
        authorization_version="test-v1",
        authorized_by_user_id=7,
        tags=[],
        metadata_json={},
        source_payload_json={},
    )
    db.add(custom_asset)
    db.flush()
    publication = VoicePoolPublication(
        publication_id="pub_test_voice",
        source_asset_id=custom_asset.id,
        owner_user_id=7,
        display_name="测试音色",
        voice_origin="user_upload",
        gender_presentation="female",
        age_impression="adult",
        primary_style="natural",
        language="zh-CN",
        timbre_tags=["clear"],
        scenario_tags=["audiobook"],
        emotion_tags=[],
        rights_basis="test",
        license_version="test-v1",
        consent_at=datetime.now(timezone.utc),
        public_preview_uri="oss://bucket/public/preview.mp3",
        public_reference_uri="oss://bucket/public/reference.mp3",
        status="pending_review",
        metadata_json={},
    )
    db.add(publication)
    db.flush()
    db.add(VoicePoolRating(publication_id=publication.id, user_id=8, score=1))
    db.add(
        VoiceAssetBillingLedger(
            idempotency_key="test-cleanup-ledger",
            owner_user_id=7,
            account_scope="user",
            provider="user_upload",
            model="user-upload",
            voice_id="upload-test",
            voice_asset_id="ur_test_voice",
            event_type="preview",
            billable=False,
            charge_status="waived",
            metadata_json={},
            event_payload_json={},
        )
    )
    db.commit()

    report = build_dry_run_report(db, local_roots=[(tmp_path / "missing", "mimo")])

    serialized = json.dumps(report, ensure_ascii=False)
    assert report["mode"] == "dry-run"
    assert report["destructive"] is False
    assert report["database"]["voice_reference_assets"]["count"] == 1
    assert report["database"]["voice_reference_assets"]["items"][0]["asset_id"] == "ur_test_voice"
    assert report["database"]["voice_pool_publications"]["count"] == 1
    assert report["database"]["voice_pool_ratings"]["count"] == 1
    assert report["database"]["voice_asset_billing_ledger"]["count"] == 1
    assert "seed_system_voice" not in serialized
    assert "oss://bucket/private/test.wav" not in serialized
    assert "public/preview.mp3" not in serialized


def test_cleanup_manifest_lists_exact_safe_actions_and_never_executes(tmp_path: Path) -> None:
    db = _build_session()
    voice_root = tmp_path / "mimo_voice_assets"
    samples_root = voice_root / "clone_samples"
    samples_root.mkdir(parents=True)
    sample_path = samples_root / "mimo_clone_test.wav"
    sample_path.write_bytes(b"manifest-audio")
    (voice_root / "index.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "mimo_clone_test",
                        "asset_type": "clone",
                        "model": "mimo-v2.5-tts-voiceclone",
                        "audio_path": "clone_samples/mimo_clone_test.wav",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    db.add(
        VoiceReferenceAsset(
            asset_id="ur_manifest_voice",
            reference_kind="user_recording",
            reference_field="audio_data",
            source_type="user_upload",
            source_model="user-upload",
            source_voice_id="mimo_clone_test",
            storage_uri=str(sample_path),
            authorization_scope="user_uploaded",
            tags=[],
            metadata_json={},
            source_payload_json={},
        )
    )
    db.commit()

    manifest = build_cleanup_manifest(
        db,
        workspace_root=tmp_path,
        local_roots=[(voice_root, "mimo")],
    )

    assert manifest["mode"] == "cleanup-manifest"
    assert manifest["destructive"] is False
    assert manifest["execution_permitted"] is False
    assert manifest["confirmation_required"] is True
    assert manifest["manifest_fingerprint"].startswith("vctc_")
    assert manifest["database_operations"][-1] == {
        "order": 4,
        "table": "voice_reference_assets",
        "action": "delete_rows",
        "primary_keys": [1],
        "count": 1,
    }
    assert [item["action"] for item in manifest["local_operations"]] == [
        "rewrite_json_index_empty",
        "delete_file",
    ]
    assert manifest["summary"]["local_file_count"] == 2
    assert manifest["summary"]["local_audio_bytes"] == len(b"manifest-audio")
    assert manifest["blockers"] == []


def test_cleanup_manifest_blocks_local_paths_outside_workspace(tmp_path: Path) -> None:
    db = _build_session()
    outside_path = tmp_path.parent / "outside-workspace.wav"
    outside_path.write_bytes(b"must-not-delete")
    db.add(
        VoiceReferenceAsset(
            asset_id="ur_outside_voice",
            reference_kind="user_recording",
            reference_field="audio_data",
            source_type="user_upload",
            source_model="user-upload",
            storage_uri=str(outside_path),
            authorization_scope="user_uploaded",
            tags=[],
            metadata_json={},
            source_payload_json={},
        )
    )
    db.commit()

    manifest = build_cleanup_manifest(db, workspace_root=tmp_path)

    assert manifest["local_operations"] == []
    assert manifest["blockers"] == [
        {
            "kind": "unsafe_local_path",
            "asset_id": "ur_outside_voice",
            "reason": "path is outside the approved workspace root",
        }
    ]
    assert outside_path.exists()


def test_cleanup_manifest_allows_both_known_cosyvoice_custom_prefixes(
    tmp_path: Path,
) -> None:
    db = _build_session()
    mapping_path = tmp_path / "cosyvoice_clone_names.json"
    mapping_path.write_text(
        json.dumps(
            {
                "cosyvoice-v3.5-plus-vd-test": "新版设计音色",
                "cosyvoice-v3-plus-vlegacy-test": "旧版复刻音色",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = build_cleanup_manifest(
        db,
        workspace_root=tmp_path,
        local_roots=[(mapping_path, "cosyvoice")],
    )

    assert manifest["provider_cloud_operations"] == [
        {
            "provider": "cosyvoice",
            "voice_id": "cosyvoice-v3.5-plus-vd-test",
            "action": "delete_voice",
            "capability": "supported_by_existing_client",
        },
        {
            "provider": "cosyvoice",
            "voice_id": "cosyvoice-v3-plus-vlegacy-test",
            "action": "delete_voice",
            "capability": "supported_by_existing_client",
        },
    ]
    assert manifest["provider_cloud_manual_review"] == []


def test_cleanup_manifest_skips_an_already_empty_voice_registry(tmp_path: Path) -> None:
    db = _build_session()
    voice_root = tmp_path / "stepaudio_voice_assets"
    voice_root.mkdir()
    (voice_root / "index.json").write_text('{"assets":[]}', encoding="utf-8")

    manifest = build_cleanup_manifest(
        db,
        workspace_root=tmp_path,
        local_roots=[(voice_root, "stepaudio")],
    )

    assert manifest["local_operations"] == []
    assert manifest["summary"]["local_file_count"] == 0
