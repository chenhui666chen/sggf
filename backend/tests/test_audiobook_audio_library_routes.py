from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT_DIR.parent
for path in (ROOT_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test_db")

from app.api.v1.audiobook_api import router as audiobook_router
from app.api.v1.audiobook_api import routes_audio_library
from app.core.security import get_current_user
from app.db.base import Base, get_db
from app.models.audio_library_asset import AudioLibraryAsset
from app.models.audio_library_asset_rating import AudioLibraryAssetRating
from app.models.role import Role
from app.models.user import User
from app.services.audiobook.sfx_library_downloader import SfxLibraryDownloader


class CompatTestClient:
    def __init__(self, app: FastAPI):
        self._app = app
        self._base_url = "http://testserver"

    async def _request_async(self, method: str, url: str, **kwargs) -> Response:
        transport = ASGITransport(app=self._app)
        async with AsyncClient(
            transport=transport,
            base_url=self._base_url,
            follow_redirects=True,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> Response:
        return asyncio.run(self._request_async(method, url, **kwargs))

    def get(self, url: str, **kwargs) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> Response:
        return self.request("POST", url, **kwargs)


def build_audio_library_user(*, admin: bool = False) -> User:
    user = User(
        id=1,
        username="audio_library_user",
        email="audio-library@example.com",
        password_hash="hash",
        is_active=True,
    )
    if admin:
        user.roles = [
            Role(
                id=1,
                name="Admin",
                code="admin",
                description="Admin role",
                is_active=True,
                is_system=False,
            )
        ]
    return user


def build_test_client(*, admin: bool = False) -> CompatTestClient:
    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: build_audio_library_user(admin=admin)
    return CompatTestClient(app)


def build_db_test_client(*, admin: bool = False) -> tuple[CompatTestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[AudioLibraryAsset.__table__, AudioLibraryAssetRating.__table__],
    )

    app = FastAPI()
    app.include_router(audiobook_router)
    app.dependency_overrides[get_current_user] = lambda: build_audio_library_user(admin=admin)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[routes_audio_library.get_db] = override_get_db
    return CompatTestClient(app), testing_session_local


def test_public_sfx_auto_download_route_is_disabled():
    response = build_test_client().post(
        "/api/v1/audiobook/audio-library/sound-effects/download",
        json={
            "source": "freesound",
            "source_id": "123",
            "name": "Rain",
            "download_url": "https://example.com/rain.wav",
            "license_name": "CC0",
            "license_commercial": True,
            "source_url": "https://freesound.org/s/123/",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        },
    )

    assert response.status_code == 403
    assert "本地 manifest" in response.json()["detail"]


def test_public_sfx_direct_search_route_is_disabled():
    response = build_test_client().post(
        "/api/v1/audiobook/audio-library/sound-effects/search",
        json={
            "source": "freesound",
            "query": "rain",
            "commercial_only": True,
        },
    )

    assert response.status_code == 403
    assert "候选审核" in response.json()["detail"]


def test_admin_sfx_candidate_and_manifest_routes_are_retired():
    client = build_test_client(admin=True)

    responses = [
        client.get("/api/v1/audiobook/audio-library/sound-effects/candidates"),
        client.post(
            "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft",
            json={"items": []},
        ),
        client.post(
            "/api/v1/audiobook/audio-library/sound-effects/import-manifest",
            json={},
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 410]
    assert "AI" in responses[-1].json()["detail"]


def test_audio_library_management_routes_require_admin():
    client, _session_factory = build_db_test_client()

    requests = [
        ("GET", "/api/v1/audiobook/audio-library/sound-effects/candidates", None),
        ("POST", "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft", {"items": []}),
        ("POST", "/api/v1/audiobook/audio-library/sound-effects/import-manifest", {}),
        ("POST", "/api/v1/audiobook/audio-library/db-sync", {"library_type": "sfx"}),
        ("POST", "/api/v1/audiobook/audio-library/cloud-sync", {"library_type": "sfx"}),
        ("GET", "/api/v1/audiobook/audio-library/cloud-objects", None),
        ("POST", "/api/v1/audiobook/audio-library/cloud-check", {"library_type": "sfx"}),
        ("POST", "/api/v1/audiobook/audio-library/cloud-cleanup", {"library_type": "sfx"}),
        ("POST", "/api/v1/audiobook/audio-library/cleanup", {"library_type": "sfx"}),
        ("POST", "/api/v1/audiobook/audio-library/assets/sfx/rain/delete", {}),
    ]

    for method, url, payload in requests:
        kwargs = {"json": payload} if payload is not None else {}
        response = client.request(method, url, **kwargs)
        assert response.status_code == 403, f"{method} {url}"


def test_audio_library_upload_requires_shared_rights_confirmation(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    client, _session_factory = build_db_test_client()

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/upload",
        data={
            "library_type": "sfx",
            "name": "雨声",
            "category": "environment/peaceful",
            "rights_confirmed": "false",
        },
        files={"file": ("rain.wav", b"RIFF0000WAVEfmt ", "audio/wav")},
    )

    assert response.status_code == 400
    assert not audio_library.exists()


def test_audio_library_upload_saves_sfx_to_shared_indexes(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(
        routes_audio_library,
        "upload_audio_library_asset",
        lambda *, local_path, relative_path, library_type: {
            "storage_mode": "local_cache",
            "storage_driver": "local_fs",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        },
    )
    client, session_factory = build_db_test_client()

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/upload",
        data={
            "library_type": "sfx",
            "name": "室内雨声",
            "description": "窗外持续的轻柔雨声",
            "category": "environment/peaceful",
            "tags": "雨声,室内,环境",
            "license_commercial": "true",
            "rights_confirmed": "true",
        },
        files={"file": ("original-name.wav", b"RIFF0000WAVEfmt ", "audio/wav")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    entry = payload["asset"]
    assert entry["id"].startswith("user_sfx_")
    assert entry["name"] == "室内雨声"
    assert entry["source"] == "user_upload"
    assert entry["file_path"].startswith("sound_effects/user_upload/")
    assert entry["file_path"].endswith(".wav")
    assert "original-name" not in entry["file_path"]
    assert (audio_library / entry["file_path"]).read_bytes() == b"RIFF0000WAVEfmt "

    indexed = json.loads((audio_library / "sound_effects_index.json").read_text(encoding="utf-8"))
    assert indexed == [entry]
    db = session_factory()
    try:
        asset = db.query(AudioLibraryAsset).one()
        assert asset.asset_key == entry["id"]
        assert asset.name == "室内雨声"
        assert asset.metadata_json["uploaded_by_user_id"] == 1
    finally:
        db.close()


def test_audio_library_upload_saves_music_metadata(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(
        routes_audio_library,
        "upload_audio_library_asset",
        lambda *, local_path, relative_path, library_type: {
            "storage_mode": "local_cache",
            "storage_driver": "local_fs",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        },
    )
    client, _session_factory = build_db_test_client()

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/upload",
        data={
            "library_type": "music",
            "name": "紧张追逐配乐",
            "description": "适合追逐场景的持续配乐",
            "style": "电影感",
            "mood": "紧张",
            "tags": "追逐,紧张",
            "rights_confirmed": "true",
        },
        files={"file": ("chase.mp3", b"ID3fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 200
    entry = response.json()["asset"]
    assert entry["id"].startswith("user_music_")
    assert entry["file_path"].startswith("music_cache/user_upload/")
    assert entry["style"] == "电影感"
    assert entry["mood"] == "紧张"
    indexed = json.loads((audio_library / "music_index.json").read_text(encoding="utf-8"))
    assert indexed == [entry]


def test_audio_library_cleanup_defaults_to_dry_run(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "missing_sfx",
                    "name": "Missing SFX",
                    "category": "effects/action",
                    "file_path": "sound_effects/missing.wav",
                    "description": "missing",
                    "tags": [],
                    "source": "test",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={"library_type": "sfx", "remove_missing_files": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["plan_token"]
    assert payload["stats"]["removed_missing"] == 1
    assert payload["details"]["missing_entries"] == [
        {
            "library_type": "sfx",
            "id": "missing_sfx",
            "name": "Missing SFX",
            "file_path": "sound_effects/missing.wav",
            "reason": "missing_file",
            "size": 0,
        }
    ]
    assert len(json.loads(index_path.read_text(encoding="utf-8"))) == 1


def test_audio_library_cleanup_requires_confirmation_for_write(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={
            "library_type": "sfx",
            "remove_missing_files": True,
            "dry_run": False,
        },
    )

    assert response.status_code == 400
    assert "confirm=true" in response.json()["detail"]


def test_audio_library_cleanup_requires_plan_token_for_write(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={
            "library_type": "sfx",
            "dry_run": False,
            "confirm": True,
        },
    )

    assert response.status_code == 400
    assert "plan_token" in response.json()["detail"]


def test_audio_library_cleanup_dry_run_reports_orphaned_and_low_quality(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    good_file = sfx_dir / "good.wav"
    bad_file = sfx_dir / "bad.wav"
    orphan_file = sfx_dir / "orphan.wav"
    good_file.write_bytes(b"good")
    bad_file.write_bytes(b"bad")
    orphan_file.write_bytes(b"orphan")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "good_sfx",
                    "name": "Good",
                    "file_path": "sound_effects/test/good.wav",
                    "quality_score": 90,
                    "quality_status": "accepted",
                },
                {
                    "id": "bad_sfx",
                    "name": "Bad",
                    "file_path": "sound_effects/test/bad.wav",
                    "quality_score": 10,
                    "quality_status": "rejected",
                },
                {
                    "id": "missing_sfx",
                    "name": "Missing",
                    "file_path": "sound_effects/test/missing.wav",
                    "quality_score": 90,
                    "quality_status": "accepted",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={
            "library_type": "sfx",
            "remove_missing_files": True,
            "remove_orphaned": True,
            "remove_low_quality": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["stats"]["removed_missing"] == 1
    assert payload["stats"]["removed_orphaned"] == 1
    assert payload["stats"]["removed_low_quality"] == 1
    assert [item["id"] for item in payload["details"]["low_quality_entries"]] == ["bad_sfx"]
    assert [item["file_path"] for item in payload["details"]["orphaned_files"]] == [
        "sound_effects/test/orphan.wav"
    ]
    assert bad_file.exists()
    assert orphan_file.exists()
    assert len(json.loads(index_path.read_text(encoding="utf-8"))) == 3


def test_audio_library_cleanup_confirmed_removes_only_library_files(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    bad_file = sfx_dir / "bad.wav"
    orphan_file = sfx_dir / "orphan.wav"
    outside_file = tmp_path / "outside.wav"
    bad_file.write_bytes(b"bad")
    orphan_file.write_bytes(b"orphan")
    outside_file.write_bytes(b"outside")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "bad_sfx",
                    "name": "Bad",
                    "file_path": "sound_effects/test/bad.wav",
                    "quality_status": "rejected",
                },
                {
                    "id": "outside_sfx",
                    "name": "Outside",
                    "file_path": str(outside_file),
                    "quality_status": "rejected",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    client = build_test_client(admin=True)
    request_payload = {
        "library_type": "sfx",
        "remove_missing_files": True,
        "remove_orphaned": True,
        "remove_low_quality": True,
    }
    preview_response = client.post(
        "/api/v1/audiobook/audio-library/cleanup",
        json=request_payload,
    )
    plan_token = preview_response.json()["plan_token"]

    response = client.post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={
            **request_payload,
            "dry_run": False,
            "confirm": True,
            "plan_token": plan_token,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["stats"]["removed_low_quality"] == 2
    assert payload["stats"]["removed_orphaned"] == 1
    assert not bad_file.exists()
    assert not orphan_file.exists()
    assert outside_file.exists()
    assert json.loads(index_path.read_text(encoding="utf-8")) == []


def test_audio_library_cleanup_removes_database_only_low_quality_asset(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    target_file = audio_library / "sound_effects" / "test" / "bad.wav"
    target_file.parent.mkdir(parents=True)
    target_file.write_bytes(b"bad")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client(admin=True)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_bad_sfx",
                name="DB Bad",
                category="action/realistic",
                file_path="sound_effects/test/bad.wav",
                description="low quality",
                source="user_upload",
                tags=["bad"],
                quality_score=10,
                quality_status="rejected",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    request_payload = {
        "library_type": "sfx",
        "remove_missing_files": True,
        "remove_orphaned": True,
        "remove_low_quality": True,
    }
    preview_response = client.post(
        "/api/v1/audiobook/audio-library/cleanup",
        json=request_payload,
    )
    plan_token = preview_response.json()["plan_token"]

    response = client.post(
        "/api/v1/audiobook/audio-library/cleanup",
        json={
            **request_payload,
            "dry_run": False,
            "confirm": True,
            "plan_token": plan_token,
        },
    )

    assert response.status_code == 200
    assert response.json()["stats"]["removed_low_quality"] == 1
    assert not target_file.exists()
    assert json.loads(index_path.read_text(encoding="utf-8")) == []
    db = session_factory()
    try:
        assert db.query(AudioLibraryAsset).count() == 0
    finally:
        db.close()


def test_audio_library_asset_delete_defaults_to_dry_run(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    target_file = sfx_dir / "rain.wav"
    target_file.write_bytes(b"rain")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "file_path": "sound_effects/test/rain.wav",
                    "storage_mode": "local_cache",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    client, _session_factory = build_db_test_client(admin=True)

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/rain_sfx/delete",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["asset"]["id"] == "rain_sfx"
    assert payload["stats"] == {"index_removed": 0, "local_deleted": 0, "cloud_deleted": 0}
    assert target_file.exists()
    assert len(json.loads(index_path.read_text(encoding="utf-8"))) == 1


def test_audio_library_asset_delete_requires_confirmation_for_write(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps([{"id": "rain_sfx", "name": "Rain", "file_path": "sound_effects/test/rain.wav"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    client, _session_factory = build_db_test_client(admin=True)

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/rain_sfx/delete",
        json={"dry_run": False},
    )

    assert response.status_code == 400
    assert "confirm=true" in response.json()["detail"]


def test_audio_library_asset_delete_confirm_removes_index_and_safe_local_file(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_dir = audio_library / "sound_effects" / "test"
    sfx_dir.mkdir(parents=True)
    target_file = sfx_dir / "rain.wav"
    target_file.write_bytes(b"rain")
    outside_file = tmp_path / "outside.wav"
    outside_file.write_bytes(b"outside")
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "file_path": "sound_effects/test/rain.wav",
                    "storage_mode": "local_cache",
                },
                {
                    "id": "outside_sfx",
                    "name": "Outside",
                    "file_path": str(outside_file),
                    "storage_mode": "local_cache",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    client, _session_factory = build_db_test_client(admin=True)

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/rain_sfx/delete",
        json={"dry_run": False, "confirm": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["stats"] == {"index_removed": 1, "local_deleted": 1, "cloud_deleted": 0}
    assert not target_file.exists()
    assert outside_file.exists()
    indexed = json.loads(index_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in indexed] == ["outside_sfx"]


def test_audio_library_asset_delete_confirm_removes_database_record_and_cloud_object(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "cloud_sfx",
                    "name": "Stale Cloud SFX",
                    "file_path": "sound_effects/stale.wav",
                    "storage_mode": "local_cache",
                },
                {
                    "id": "keep_sfx",
                    "name": "Keep SFX",
                    "file_path": "sound_effects/keep.wav",
                    "storage_mode": "local_cache",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client, session_factory = build_db_test_client(admin=True)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="cloud_sfx",
                name="Cloud SFX",
                file_path="sound_effects/cloud.wav",
                source="user_upload",
                storage_mode="durable_cloud",
                storage_driver="aliyun_oss",
                object_key="shared/audio_library/sfx/sound_effects/cloud.wav",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "aliyun_oss")
    deleted = []

    def fake_delete_audio_library_object(*, object_key):
        deleted.append(object_key)
        return {"deleted": True, "object_key": object_key, "status_code": 204}

    monkeypatch.setattr(routes_audio_library, "delete_audio_library_object", fake_delete_audio_library_object)

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/cloud_sfx/delete",
        json={"dry_run": False, "confirm": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"] == {"index_removed": 1, "local_deleted": 0, "cloud_deleted": 1}
    assert deleted == ["shared/audio_library/sfx/sound_effects/cloud.wav"]
    indexed = json.loads((audio_library / "sound_effects_index.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in indexed] == ["keep_sfx"]
    db = session_factory()
    try:
        assert db.query(AudioLibraryAsset).count() == 0
    finally:
        db.close()


def test_audio_library_cloud_sync_dry_run_reports_local_cache_assets(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "local_fs")
    audio_library = tmp_path / "audio_library"
    sfx_file = audio_library / "sound_effects" / "environment" / "rain.ogg"
    sfx_file.parent.mkdir(parents=True)
    sfx_file.write_bytes(b"OggS")
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/rain.ogg",
                    "description": "rain",
                    "tags": ["rain"],
                    "source": "ai_generated",
                    "storage_mode": "local_cache",
                    "storage_driver": "local_fs",
                    "asset_scope": "shared_library",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    client, _session_factory = build_db_test_client(admin=True)
    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-sync",
        json={"library_type": "sfx"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["cloud_enabled"] is False
    assert payload["stats"]["eligible"] == 1
    assert payload["stats"]["uploaded"] == 0
    assert payload["details"]["eligible"][0]["id"] == "rain_sfx"

    indexed = json.loads((audio_library / "sound_effects_index.json").read_text(encoding="utf-8"))
    assert indexed[0]["storage_mode"] == "local_cache"


def test_audio_library_cloud_sync_confirm_requires_cloud_storage(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_file = audio_library / "sound_effects" / "environment" / "rain.ogg"
    sfx_file.parent.mkdir(parents=True)
    sfx_file.write_bytes(b"OggS")
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/rain.ogg",
                    "description": "rain",
                    "tags": ["rain"],
                    "source": "ai_generated",
                    "storage_mode": "local_cache",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "is_audio_library_cloud_storage_enabled", lambda: False)

    client, _session_factory = build_db_test_client(admin=True)
    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-sync",
        json={"library_type": "sfx", "dry_run": False, "confirm": True},
    )

    assert response.status_code == 400
    assert "云存储" in response.json()["detail"]


def test_audio_library_cloud_sync_confirm_uploads_and_updates_index(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_file = audio_library / "sound_effects" / "environment" / "rain.ogg"
    sfx_file.parent.mkdir(parents=True)
    sfx_file.write_bytes(b"OggS")
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/rain.ogg",
                    "description": "rain",
                    "tags": ["rain"],
                    "source": "ai_generated",
                    "storage_mode": "local_cache",
                    "storage_driver": "local_fs",
                    "asset_scope": "shared_library",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "dashscope_oss")
    monkeypatch.setattr(routes_audio_library, "is_audio_library_cloud_storage_enabled", lambda: True)

    uploaded = []

    def fake_upload_audio_library_asset(*, local_path, relative_path, library_type):
        uploaded.append((Path(local_path).name, relative_path, library_type))
        return {
            "storage_mode": "durable_cloud",
            "storage_driver": "dashscope_oss",
            "cloud_uri": f"oss://shared/audio-library/{library_type}/{relative_path}",
            "public_url": f"https://cdn.example.test/{library_type}/{relative_path}",
            "object_key": f"shared/audio-library/{library_type}/{relative_path}",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        }

    monkeypatch.setattr(routes_audio_library, "upload_audio_library_asset", fake_upload_audio_library_asset)

    client, _session_factory = build_db_test_client(admin=True)
    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-sync",
        json={"library_type": "sfx", "dry_run": False, "confirm": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["cloud_enabled"] is True
    assert payload["stats"]["eligible"] == 1
    assert payload["stats"]["uploaded"] == 1
    assert uploaded == [("rain.ogg", "sound_effects/environment/rain.ogg", "sfx")]

    indexed = json.loads((audio_library / "sound_effects_index.json").read_text(encoding="utf-8"))
    assert indexed[0]["storage_mode"] == "durable_cloud"
    assert indexed[0]["cloud_uri"] == "oss://shared/audio-library/sfx/sound_effects/environment/rain.ogg"


def test_audio_library_cloud_sync_dry_run_prefers_database_records(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_file = audio_library / "sound_effects" / "environment" / "db_rain.ogg"
    sfx_file.parent.mkdir(parents=True)
    sfx_file.write_bytes(b"OggS")
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client(admin=True)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                source="local_authorized",
                tags=["rain"],
                storage_mode="local_cache",
                storage_driver="local_fs",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-sync",
        json={"library_type": "sfx"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["stats"]["eligible"] == 1
    assert payload["details"]["eligible"][0]["id"] == "db_rain"


def test_audio_library_cloud_sync_confirm_updates_database_record(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    sfx_file = audio_library / "sound_effects" / "environment" / "db_rain.ogg"
    sfx_file.parent.mkdir(parents=True)
    sfx_file.write_bytes(b"OggS")
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client(admin=True)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "dashscope_oss")
    monkeypatch.setattr(routes_audio_library, "is_audio_library_cloud_storage_enabled", lambda: True)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                source="local_authorized",
                tags=["rain"],
                storage_mode="local_cache",
                storage_driver="local_fs",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    uploaded = []

    def fake_upload_audio_library_asset(*, local_path, relative_path, library_type):
        uploaded.append((Path(local_path).name, relative_path, library_type))
        return {
            "storage_mode": "durable_cloud",
            "storage_driver": "dashscope_oss",
            "cloud_uri": f"oss://shared/audio-library/{library_type}/{relative_path}",
            "public_url": f"https://cdn.example.test/{library_type}/{relative_path}",
            "object_key": f"shared/audio-library/{library_type}/{relative_path}",
            "local_cache_path": relative_path,
            "asset_scope": "shared_library",
        }

    monkeypatch.setattr(routes_audio_library, "upload_audio_library_asset", fake_upload_audio_library_asset)

    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-sync",
        json={"library_type": "sfx", "dry_run": False, "confirm": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["stats"]["eligible"] == 1
    assert payload["stats"]["uploaded"] == 1
    assert uploaded == [("db_rain.ogg", "sound_effects/environment/db_rain.ogg", "sfx")]

    db = session_factory()
    try:
        asset = db.query(AudioLibraryAsset).one()
        assert asset.storage_mode == "durable_cloud"
        assert asset.storage_driver == "dashscope_oss"
        assert asset.cloud_uri == "oss://shared/audio-library/sfx/sound_effects/environment/db_rain.ogg"
        assert asset.public_url == "https://cdn.example.test/sfx/sound_effects/environment/db_rain.ogg"
    finally:
        db.close()

    indexed = json.loads((audio_library / "sound_effects_index.json").read_text(encoding="utf-8"))
    assert indexed == []


def test_audio_library_db_sync_defaults_to_dry_run(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/rain.ogg",
                    "description": "rain",
                    "tags": ["rain"],
                    "source": "wikimedia_commons",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (audio_library / "music_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "tense_music",
                    "style": "cinematic",
                    "mood": "tense",
                    "bucket": "tension",
                    "file_path": "music_cache/tense.mp3",
                    "source": "mureka",
                    "duration": 30.0,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    client, session_factory = build_db_test_client(admin=True)

    response = client.post(
        "/api/v1/audiobook/audio-library/db-sync",
        json={"library_type": "both"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["stats"] == {"candidates": 2, "synced": 0}

    db = session_factory()
    try:
        assert db.query(AudioLibraryAsset).count() == 0
    finally:
        db.close()


def test_audio_library_db_sync_confirm_imports_json_indexes(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "rain_sfx",
                    "name": "Rain",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/rain.ogg",
                    "description": "rain",
                    "tags": ["rain"],
                    "source": "ai_generated",
                    "storage_mode": "local_cache",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    client, session_factory = build_db_test_client(admin=True)

    response = client.post(
        "/api/v1/audiobook/audio-library/db-sync",
        json={"library_type": "sfx", "dry_run": False, "confirm": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["stats"] == {"candidates": 1, "synced": 1}

    db = session_factory()
    try:
        asset = db.query(AudioLibraryAsset).one()
        assert asset.library_type == "sfx"
        assert asset.asset_key == "rain_sfx"
        assert asset.category == "environment/peaceful"
        assert asset.storage_mode == "local_cache"
    finally:
        db.close()


def test_browse_sound_effects_prefers_database_records(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="dashscope_oss",
                public_url="https://cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/audiobook/audio-library/sound-effects")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["db_rain"]
    assert payload[0]["public_url"] == "https://cdn.example.test/sfx/db_rain.ogg"


def test_audio_library_rating_updates_existing_vote_and_returns_summary(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="rating_sfx",
                name="评分音效",
                category="action/realistic",
                file_path="sound_effects/action/rating.wav",
                description="rating",
                source="user_upload",
                tags=[],
            )
        )
        db.commit()
    finally:
        db.close()

    assert client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/rating_sfx/rating",
        json={"score": 4},
    ).status_code == 200
    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/rating_sfx/rating",
        json={"score": 5},
    )

    assert response.status_code == 200
    assert response.json()["rating_count"] == 1
    assert response.json()["average_score"] == 5.0
    assert response.json()["user_score"] == 5

    browse_response = client.get("/api/v1/audiobook/audio-library/sound-effects")
    assert browse_response.status_code == 200
    assert browse_response.json()[0]["rating_count"] == 1
    assert browse_response.json()[0]["average_rating"] == 5.0
    assert browse_response.json()[0]["user_rating"] == 5

    db = session_factory()
    try:
        assert db.query(AudioLibraryAssetRating).count() == 1
    finally:
        db.close()


def test_audio_library_low_ratings_auto_unpublish_and_hide_asset(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    index_path = audio_library / "sound_effects_index.json"
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "low_rating_sfx",
                    "name": "低分音效",
                    "category": "action/realistic",
                    "file_path": "sound_effects/action/low.wav",
                    "description": "low",
                    "source": "user_upload",
                    "tags": [],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setenv("AUDIO_LIBRARY_MIN_RATING_COUNT", "1")
    monkeypatch.setenv("AUDIO_LIBRARY_MIN_LOW_RATING_COUNT", "1")
    monkeypatch.setenv("AUDIO_LIBRARY_MIN_LOW_RATING_RATIO", "1")
    monkeypatch.setenv("AUDIO_LIBRARY_MAX_AVERAGE_SCORE", "2")
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="low_rating_sfx",
                name="低分音效",
                category="action/realistic",
                file_path="sound_effects/action/low.wav",
                description="low",
                source="user_upload",
                tags=[],
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/audiobook/audio-library/assets/sfx/low_rating_sfx/rating",
        json={"score": 1},
    )

    assert response.status_code == 200
    assert response.json()["auto_unpublished"] is True
    assert client.get("/api/v1/audiobook/audio-library/sound-effects").json() == []

    db = session_factory()
    try:
        asset = db.query(AudioLibraryAsset).one()
        assert asset.quality_status == "community_rejected"
    finally:
        db.close()
    indexed = json.loads(index_path.read_text(encoding="utf-8"))
    assert indexed[0]["quality_status"] == "community_rejected"


def test_browse_sound_effects_merges_json_records_missing_from_database(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "json_door",
                    "name": "JSON Door",
                    "category": "action/realistic",
                    "file_path": "sound_effects/action/json_door.wav",
                    "description": "door",
                    "source": "user_upload",
                    "tags": ["door"],
                }
            ]
        ),
        encoding="utf-8",
    )
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="dashscope_oss",
                public_url="https://cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/audiobook/audio-library/sound-effects")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["db_rain", "json_door"]


def test_browse_sound_effects_rewrites_cloud_url_from_configured_host(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="aliyun_oss",
                cloud_uri="oss://shared/audio_library/sfx/sound_effects/environment/db_rain.ogg",
                public_url="https://old-cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/audiobook/audio-library/sound-effects")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["public_url"] == (
        "https://audio.sggf.net/shared/audio_library/sfx/sound_effects/environment/db_rain.ogg"
    )


def test_browse_sound_effects_keeps_legacy_public_url_without_object_key(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="dashscope_oss",
                public_url="https://cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/audiobook/audio-library/sound-effects")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["public_url"] == "https://cdn.example.test/sfx/db_rain.ogg"


def test_preview_audio_library_file_uses_database_public_url(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="dashscope_oss",
                public_url="https://cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/audiobook/audio-library/preview/sfx/db_rain",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example.test/sfx/db_rain.ogg"


def test_preview_audio_library_file_rejects_local_path_outside_library(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    outside_file = tmp_path / "private.wav"
    outside_file.write_bytes(b"private")
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "outside_sfx",
                    "name": "Outside",
                    "category": "action/realistic",
                    "file_path": str(outside_file),
                    "description": "outside",
                    "source": "user_upload",
                    "tags": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    client, _session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = client.get("/api/v1/audiobook/audio-library/preview/sfx/outside_sfx")

    assert response.status_code == 404
    assert response.json()["detail"] == "文件不存在"


def test_preview_audio_library_file_rewrites_cloud_url_from_configured_host(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                category="environment/peaceful",
                file_path="sound_effects/environment/db_rain.ogg",
                description="database rain",
                source="user_upload",
                tags=["rain"],
                storage_mode="durable_cloud",
                storage_driver="aliyun_oss",
                cloud_uri="oss://shared/audio_library/sfx/sound_effects/environment/db_rain.ogg",
                public_url="https://old-cdn.example.test/sfx/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/api/v1/audiobook/audio-library/preview/sfx/db_rain",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "https://audio.sggf.net/shared/audio_library/sfx/sound_effects/environment/db_rain.ogg"
    )


def test_browse_sound_effects_returns_quality_license_and_attribution_metadata(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "licensed_sfx",
                    "name": "Licensed SFX",
                    "category": "effects/action",
                    "file_path": "sound_effects/effects/action/hit.wav",
                    "description": "hit",
                    "tags": ["hit"],
                    "source": "user_upload",
                    "source_url": "https://example.com/sfx",
                    "author": "foley-author",
                    "author_url": "https://example.com/author",
                    "license": "CC BY 4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "license_commercial": True,
                    "attribution_required": True,
                    "attribution_text": "Licensed SFX by foley-author, CC BY 4.0",
                    "quality_score": 92.5,
                    "quality_grade": "A",
                    "quality_status": "accepted",
                    "storage_mode": "durable_cloud",
                    "storage_driver": "dashscope_oss",
                    "cloud_uri": "oss://shared/audio-library/sfx/hit.wav",
                    "public_url": "https://cdn.example.test/sfx/hit.wav",
                    "local_cache_path": "sound_effects/effects/action/hit.wav",
                    "asset_scope": "shared_library",
                    "retrieved_at": "2026-05-06T00:00:00Z",
                    "license_checked_at": "2026-05-06T00:00:00Z",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get("/api/v1/audiobook/audio-library/sound-effects")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["quality_score"] == 92.5
    assert entry["quality_grade"] == "A"
    assert entry["quality_status"] == "accepted"
    assert entry["license"] == "CC BY 4.0"
    assert entry["license_commercial"] is True
    assert entry["attribution_required"] is True
    assert entry["attribution_text"] == "Licensed SFX by foley-author, CC BY 4.0"
    assert entry["author"] == "foley-author"
    assert entry["source_url"] == "https://example.com/sfx"
    assert entry["storage_mode"] == "durable_cloud"
    assert entry["storage_driver"] == "dashscope_oss"
    assert entry["cloud_uri"] == "oss://shared/audio-library/sfx/hit.wav"
    assert entry["public_url"] == "https://cdn.example.test/sfx/hit.wav"
    assert entry["local_cache_path"] == "sound_effects/effects/action/hit.wav"
    assert entry["asset_scope"] == "shared_library"


def test_browse_sound_effects_filters_by_scene(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "indoor_door",
                    "name": "Indoor Door",
                    "category": "action/realistic",
                    "file_path": "sound_effects/action/realistic/door.wav",
                    "description": "door",
                    "tags": ["door"],
                    "scenes": ["indoor", "mansion"],
                    "source": "user_upload",
                },
                {
                    "id": "outdoor_wind",
                    "name": "Outdoor Wind",
                    "category": "environment/peaceful",
                    "file_path": "sound_effects/environment/peaceful/wind.wav",
                    "description": "wind",
                    "tags": ["wind"],
                    "scenes": ["outdoor"],
                    "source": "user_upload",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get("/api/v1/audiobook/audio-library/sound-effects?scene=indoor")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["indoor_door"]


def test_browse_sound_effects_infers_scene_for_legacy_entries(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "legacy_door",
                    "name": "Legacy Door",
                    "category": "effects/action",
                    "file_path": "sound_effects/effects/action/door.wav",
                    "description": "old wooden door opens",
                    "tags": ["door"],
                    "source": "user_upload",
                },
                {
                    "id": "legacy_wind",
                    "name": "Legacy Wind",
                    "category": "effects/action",
                    "file_path": "sound_effects/effects/action/wind.wav",
                    "description": "wind in open field",
                    "tags": ["wind"],
                    "source": "user_upload",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get("/api/v1/audiobook/audio-library/sound-effects?scene=indoor")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == ["legacy_door"]
    assert payload[0]["category"] == "action/realistic"
    assert "indoor" in payload[0]["scenes"]


def test_normalize_sfx_entry_applies_curated_train_station_metadata():
    normalized = routes_audio_library._normalize_sfx_entry({
        "id": "action_local_authorized_wikimedia_airchime_k5la_b1a2540775",
        "source_id": "wikimedia_airchime_k5la_train_horn_cc0",
        "name": "train_horn_airchime_k5la",
        "description": "Diesel locomotive horn for train arrivals and railway warnings.",
        "category": "action/intense",
        "style": "intense",
        "tags": ["action", "intense", "battle", "train", "horn", "travel"],
        "scenes": ["battle", "travel"],
    })

    assert normalized["name"] == "火车站火车鸣笛与人群交谈声"
    assert normalized["description"] == "火车站环境声，包含火车鸣笛、列车运行声和背景人群交谈。"
    assert normalized["category"] == "environment/realistic"
    assert normalized["style"] == "realistic"
    assert normalized["scenes"] == ["travel"]
    assert "people" in normalized["tags"]
    assert "battle" not in normalized["tags"]


def test_browse_music_returns_quality_license_and_attribution_metadata(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "music_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "licensed_music",
                    "style": "cinematic",
                    "duration": 30,
                    "tempo": "slow",
                    "mood": "tense",
                    "bucket": "cinematic:tense",
                    "file_path": "music_cache/tense.mp3",
                    "source": "user_upload",
                    "source_url": "https://example.com/music",
                    "author": "composer",
                    "author_url": "https://example.com/composer",
                    "license": "CC0",
                    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                    "license_commercial": True,
                    "attribution_required": False,
                    "attribution_text": "",
                    "quality_score": 88,
                    "quality_grade": "B",
                    "quality_status": "accepted",
                    "storage_mode": "durable_cloud",
                    "storage_driver": "dashscope_oss",
                    "cloud_uri": "oss://shared/audio-library/music/tense.mp3",
                    "public_url": "https://cdn.example.test/music/tense.mp3",
                    "local_cache_path": "music_cache/tense.mp3",
                    "asset_scope": "shared_library",
                    "retrieved_at": "2026-05-06T00:00:00Z",
                    "license_checked_at": "2026-05-06T00:00:00Z",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get("/api/v1/audiobook/audio-library/music")

    assert response.status_code == 200
    entry = response.json()[0]
    assert entry["quality_score"] == 88
    assert entry["quality_grade"] == "B"
    assert entry["quality_status"] == "accepted"
    assert entry["license"] == "CC0"
    assert entry["license_commercial"] is True
    assert entry["attribution_required"] is False
    assert entry["author"] == "composer"
    assert entry["source_url"] == "https://example.com/music"
    assert entry["storage_mode"] == "durable_cloud"
    assert entry["storage_driver"] == "dashscope_oss"
    assert entry["cloud_uri"] == "oss://shared/audio-library/music/tense.mp3"
    assert entry["public_url"] == "https://cdn.example.test/music/tense.mp3"
    assert entry["local_cache_path"] == "music_cache/tense.mp3"
    assert entry["asset_scope"] == "shared_library"


def test_preview_audio_library_file_redirects_to_cloud_public_url(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "cloud_sfx",
                    "name": "Cloud SFX",
                    "category": "action",
                    "file_path": "sound_effects/action/cloud.wav",
                    "description": "cloud",
                    "tags": [],
                    "source": "ai_generated",
                    "public_url": "https://cdn.example.test/sfx/cloud.wav",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get(
        "/api/v1/audiobook/audio-library/preview/sfx/cloud_sfx",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example.test/sfx/cloud.wav"


def test_preview_audio_library_file_prefers_local_mirror_over_public_url(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    local_file = audio_library / "sound_effects" / "action" / "local.wav"
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"RIFF-test-audio")
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "local_sfx",
                    "name": "Local SFX",
                    "category": "action",
                    "file_path": "sound_effects/action/local.wav",
                    "description": "local",
                    "tags": [],
                    "source": "ai_generated",
                    "public_url": "https://cdn.example.test/sfx/local.wav",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client().get(
        "/api/v1/audiobook/audio-library/preview/sfx/local_sfx",
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF-test-audio"


def test_list_sfx_candidates_reads_jsonl(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    candidate_path = audio_library / "sfx_candidates.jsonl"
    candidate_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source": "openverse",
                        "source_id": "ov-1",
                        "name": "Rain ambience",
                        "source_url": "https://example.org/rain",
                        "file_url": "https://cdn.example.org/rain.mp3",
                        "license": "CC0",
                        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                        "license_commercial": True,
                        "status": "candidate_only",
                        "requires_manual_review": True,
                    },
                    ensure_ascii=False,
                ),
                "not-json",
                json.dumps(
                    {
                        "source": "wikimedia_commons",
                        "source_id": "wm-2",
                        "name": "Rejected thunder",
                        "license": "CC BY-NC",
                        "license_commercial": False,
                        "status": "rejected",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).get(
        "/api/v1/audiobook/audio-library/sound-effects/candidates",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["invalid_rows"] == 1
    assert [item["source_id"] for item in payload["items"]] == ["ov-1", "wm-2"]


def test_build_sfx_manifest_draft_requires_local_file(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sfx_candidates.jsonl").write_text(
        json.dumps(
            {
                "source": "openverse",
                "source_id": "ov-1",
                "name": "Rain ambience",
                "source_url": "https://example.org/rain",
                "file_url": "https://cdn.example.org/rain.mp3",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "license_commercial": True,
                "status": "candidate_only",
                "requires_manual_review": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft",
        json={
            "items": [
                {
                    "source": "openverse",
                    "source_id": "ov-1",
                    "review_status": "approved",
                    "license_verified": True,
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "local_file" in response.json()["detail"]
    assert not (audio_library / "sound_effects_index.json").exists()


def test_build_sfx_manifest_draft_writes_local_import_manifest(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    local_source_dir = audio_library / "approved_sfx"
    local_source_dir.mkdir()
    (local_source_dir / "rain.wav").write_bytes(b"RIFF")
    (audio_library / "sfx_candidates.jsonl").write_text(
        json.dumps(
            {
                "source": "openverse",
                "source_id": "ov-1",
                "name": "Rain ambience",
                "description": "Forest rain",
                "source_url": "https://example.org/rain",
                "file_url": "https://cdn.example.org/rain.mp3",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "license_commercial": True,
                "author": "Recorder",
                "tags": ["rain", "forest"],
                "status": "candidate_only",
                "requires_manual_review": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft",
        json={
            "items": [
                {
                    "source": "openverse",
                    "source_id": "ov-1",
                    "review_status": "approved",
                    "license_verified": True,
                    "local_file": "rain.wav",
                    "category": "environment",
                    "style": "realistic",
                }
            ],
            "source_dir": "approved_sfx",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stats"] == {"approved": 1, "rejected": 0, "skipped": 0}
    assert not (audio_library / "sound_effects_index.json").exists()

    manifest_path = Path(payload["manifest_path"])
    assert manifest_path.exists()
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "file": "rain.wav",
            "name": "Rain ambience",
            "description": "Forest rain",
            "source": "openverse",
            "source_id": "ov-1",
            "source_url": "https://example.org/rain",
            "license": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "license_commercial": True,
            "author": "Recorder",
            "author_url": "",
            "attribution_required": False,
            "attribution_text": "",
            "category": "environment",
            "style": "realistic",
            "tags": ["rain", "forest"],
            "review_source": "sfx_candidates.jsonl",
            "review_status": "approved",
        }
    ]


def test_build_sfx_manifest_draft_skips_needs_info_without_local_file(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sfx_candidates.jsonl").write_text(
        json.dumps(
            {
                "source": "openverse",
                "source_id": "ov-1",
                "name": "Rain ambience",
                "source_url": "https://example.org/rain",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "license_commercial": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft",
        json={
            "items": [
                {
                    "source": "openverse",
                    "source_id": "ov-1",
                    "review_status": "needs_info",
                    "license_verified": False,
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"] == {"approved": 0, "rejected": 0, "skipped": 1}
    manifest_path = Path(payload["manifest_path"])
    assert manifest_path.exists()
    assert manifest_path.read_text(encoding="utf-8") == ""


def test_build_sfx_manifest_draft_rejects_output_path_outside_library(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sfx_candidates.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/candidates/manifest-draft",
        json={
            "items": [],
            "output_path": "../outside.jsonl",
        },
    )

    assert response.status_code == 400
    assert "output_path" in response.json()["detail"]


def test_import_sfx_manifest_is_retired_even_for_dry_run(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    source_dir = audio_library / "approved_sfx"
    source_dir.mkdir(parents=True)
    (source_dir / "rain.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = audio_library / "sfx_import_manifest_draft.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "file": "rain.wav",
                "name": "Forest Rain",
                "description": "Licensed rain ambience",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/rain",
                "author": "field-recordist",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "tags": ["rain", "forest"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/import-manifest",
        json={"manifest_path": "sfx_import_manifest_draft.jsonl", "source_dir": "approved_sfx"},
    )

    assert response.status_code == 410
    assert "AI" in response.json()["detail"]
    assert not (audio_library / "sound_effects_index.json").exists()


def test_import_sfx_manifest_requires_confirm_for_write(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sfx_import_manifest_draft.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/import-manifest",
        json={
            "manifest_path": "sfx_import_manifest_draft.jsonl",
            "dry_run": False,
        },
    )

    assert response.status_code == 410
    assert "AI" in response.json()["detail"]


def test_import_sfx_manifest_rejects_manifest_path_outside_library(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/sound-effects/import-manifest",
        json={"manifest_path": "../outside.jsonl"},
    )

    assert response.status_code == 410
    assert "AI" in response.json()["detail"]


def test_import_sfx_manifest_confirmed_does_not_write_index(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    source_dir = audio_library / "approved_sfx"
    source_dir.mkdir(parents=True)
    (source_dir / "door.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = audio_library / "sfx_import_manifest_draft.jsonl"
    manifest_path.write_text(
        json.dumps(
            {
                "file": "door.wav",
                "name": "Wood Door Open",
                "description": "Licensed wooden door opening",
                "license": "Creative Commons Attribution",
                "license_commercial": True,
                "source_url": "https://example.com/assets/door",
                "author": "foley-author",
                "author_url": "https://example.com/authors/foley-author",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution_text": "Wood Door Open by foley-author, CC BY 4.0",
                "tags": ["door", "wood", "foley"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(
        SfxLibraryDownloader,
        "_assess_downloaded_quality",
        lambda self, file_path: {
            "quality_score": 92.0,
            "quality_grade": "A",
            "quality_status": "accepted",
        },
    )

    client, session_factory = build_db_test_client(admin=True)
    response = client.post(
        "/api/v1/audiobook/audio-library/sound-effects/import-manifest",
        json={
            "manifest_path": "sfx_import_manifest_draft.jsonl",
            "source_dir": "approved_sfx",
            "dry_run": False,
            "confirm": True,
        },
    )

    assert response.status_code == 410
    assert "AI" in response.json()["detail"]
    index_path = audio_library / "sound_effects_index.json"
    assert not index_path.exists()
    db = session_factory()
    try:
        assert db.query(AudioLibraryAsset).count() == 0
    finally:
        db.close()


def test_audio_library_cloud_objects_requires_aliyun_oss(monkeypatch):
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "local_fs")

    response = build_test_client(admin=True).get("/api/v1/audiobook/audio-library/cloud-objects")

    assert response.status_code == 400
    assert "aliyun_oss" in response.json()["detail"]


def test_audio_library_cloud_objects_lists_oss_prefix(monkeypatch):
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "aliyun_oss")
    calls = []

    def fake_list_audio_library_objects(**kwargs):
        calls.append(kwargs)
        return {
            "bucket": "sggf-audio-library",
            "prefix": "shared/audio_library/sfx/",
            "is_truncated": False,
            "next_continuation_token": "",
            "items": [
                {
                    "key": "shared/audio_library/sfx/a.ogg",
                    "size": 12,
                    "last_modified": "2026-05-09T00:00:00.000Z",
                    "etag": '"etag-a"',
                    "storage_class": "STANDARD",
                }
            ],
            "common_prefixes": [],
        }

    monkeypatch.setattr(routes_audio_library, "list_audio_library_objects", fake_list_audio_library_objects)

    response = build_test_client(admin=True).get(
        "/api/v1/audiobook/audio-library/cloud-objects",
        params={"library_type": "sfx", "max_keys": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["storage_driver"] == "aliyun_oss"
    assert payload["items"][0]["key"] == "shared/audio_library/sfx/a.ogg"
    assert calls == [
        {
            "prefix": "shared/audio_library/sfx/",
            "max_keys": 20,
            "continuation_token": "",
            "delimiter": "",
            "start_after": "",
        }
    ]


def test_audio_library_cloud_check_uses_database_object_keys(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text("[]", encoding="utf-8")
    client, session_factory = build_db_test_client(admin=True)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "aliyun_oss")
    db = session_factory()
    try:
        db.add(
            AudioLibraryAsset(
                library_type="sfx",
                asset_key="db_rain",
                name="DB Rain",
                file_path="sound_effects/environment/db_rain.ogg",
                source="local_authorized",
                storage_mode="durable_cloud",
                storage_driver="aliyun_oss",
                object_key="shared/audio_library/sfx/sound_effects/environment/db_rain.ogg",
                asset_scope="shared_library",
            )
        )
        db.commit()
    finally:
        db.close()

    checked = []

    def fake_head_audio_library_object(*, object_key):
        checked.append(object_key)
        return {
            "object_key": object_key,
            "exists": True,
            "status_code": 200,
            "content_length": 123,
            "etag": '"etag-rain"',
        }

    monkeypatch.setattr(routes_audio_library, "head_audio_library_object", fake_head_audio_library_object)

    response = client.post(
        "/api/v1/audiobook/audio-library/cloud-check",
        json={"library_type": "sfx"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stats"] == {"checked": 1, "exists": 1, "missing": 0, "failed": 0}
    assert payload["details"]["exists"][0]["id"] == "db_rain"
    assert checked == ["shared/audio_library/sfx/sound_effects/environment/db_rain.ogg"]


def test_audio_library_cloud_cleanup_defaults_to_dry_run(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "bad_sfx",
                    "name": "Bad SFX",
                    "file_path": "sound_effects/bad.ogg",
                    "storage_mode": "durable_cloud",
                    "storage_driver": "aliyun_oss",
                    "object_key": "shared/audio_library/sfx/sound_effects/bad.ogg",
                    "quality_status": "rejected",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "aliyun_oss")
    deleted = []
    monkeypatch.setattr(
        routes_audio_library,
        "delete_audio_library_object",
        lambda *, object_key: deleted.append(object_key) or {"deleted": True, "object_key": object_key},
    )

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cloud-cleanup",
        json={"library_type": "sfx", "remove_low_quality": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["stats"]["candidates"] == 1
    assert payload["stats"]["deleted"] == 0
    assert payload["details"]["candidates"][0]["object_key"] == "shared/audio_library/sfx/sound_effects/bad.ogg"
    assert deleted == []


def test_audio_library_cloud_cleanup_confirm_deletes_low_quality_objects(monkeypatch, tmp_path):
    audio_library = tmp_path / "audio_library"
    audio_library.mkdir()
    (audio_library / "sound_effects_index.json").write_text(
        json.dumps(
            [
                {
                    "id": "bad_sfx",
                    "name": "Bad SFX",
                    "file_path": "sound_effects/bad.ogg",
                    "storage_mode": "durable_cloud",
                    "storage_driver": "aliyun_oss",
                    "object_key": "shared/audio_library/sfx/sound_effects/bad.ogg",
                    "quality_status": "rejected",
                },
                {
                    "id": "good_sfx",
                    "name": "Good SFX",
                    "file_path": "sound_effects/good.ogg",
                    "storage_mode": "durable_cloud",
                    "storage_driver": "aliyun_oss",
                    "object_key": "shared/audio_library/sfx/sound_effects/good.ogg",
                    "quality_status": "accepted",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(routes_audio_library, "get_audio_library_dir", lambda: audio_library)
    monkeypatch.setattr(routes_audio_library, "get_audio_library_storage_driver", lambda: "aliyun_oss")
    deleted = []

    def fake_delete_audio_library_object(*, object_key):
        deleted.append(object_key)
        return {"deleted": True, "object_key": object_key, "status_code": 204}

    monkeypatch.setattr(routes_audio_library, "delete_audio_library_object", fake_delete_audio_library_object)

    response = build_test_client(admin=True).post(
        "/api/v1/audiobook/audio-library/cloud-cleanup",
        json={
            "library_type": "sfx",
            "remove_low_quality": True,
            "dry_run": False,
            "confirm": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is False
    assert payload["stats"]["candidates"] == 1
    assert payload["stats"]["deleted"] == 1
    assert payload["details"]["deleted"][0]["object_key"] == "shared/audio_library/sfx/sound_effects/bad.ogg"
    assert deleted == ["shared/audio_library/sfx/sound_effects/bad.ogg"]
