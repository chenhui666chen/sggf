from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def test_cloud_storage_disabled_returns_local_metadata(tmp_path, monkeypatch):
    from app.services.audiobook.audio_asset_cloud_storage import (
        get_audio_library_storage_driver,
        is_audio_library_cloud_storage_enabled,
        upload_audio_library_asset,
    )

    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", raising=False)
    local_file = tmp_path / "rain.ogg"
    local_file.write_bytes(b"OggS")

    metadata = upload_audio_library_asset(
        local_path=local_file,
        relative_path="sound_effects/environment/rain.ogg",
        library_type="sfx",
    )

    assert metadata == {
        "storage_mode": "local_cache",
        "storage_driver": "local_fs",
        "local_cache_path": "sound_effects/environment/rain.ogg",
        "asset_scope": "shared_library",
    }
    assert get_audio_library_storage_driver() == "local_fs"
    assert is_audio_library_cloud_storage_enabled() is False


def test_dashscope_oss_upload_uses_shared_audio_library_prefix(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "dashscope_oss")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX", "shared/audio-library")
    monkeypatch.setattr(
        storage,
        "_get_dashscope_upload_policy",
        lambda model: {
            "upload_host": "https://bucket.oss-cn-test.aliyuncs.com",
            "oss_access_key_id": "ak",
            "signature": "sig",
            "policy": "policy",
            "x_oss_object_acl": "public-read",
            "x_oss_forbid_overwrite": "false",
        },
    )
    monkeypatch.setattr(
        storage.httpx,
        "post",
        lambda *args, **kwargs: type(
            "Response",
            (),
            {"status_code": 200, "text": "", "raise_for_status": lambda self: None},
        )(),
    )

    local_file = tmp_path / "door.ogg"
    local_file.write_bytes(b"OggS")

    metadata = storage.upload_audio_library_asset(
        local_path=local_file,
        relative_path="sound_effects/action/door.ogg",
        library_type="sfx",
    )

    assert metadata["storage_mode"] == "durable_cloud"
    assert metadata["storage_driver"] == "dashscope_oss"
    assert metadata["asset_scope"] == "shared_library"
    assert metadata["cloud_uri"] == "oss://shared/audio-library/sfx/sound_effects/action/door.ogg"
    assert metadata["object_key"] == "shared/audio-library/sfx/sound_effects/action/door.ogg"
    assert metadata["public_url"] == (
        "https://bucket.oss-cn-test.aliyuncs.com/shared/audio-library/sfx/sound_effects/action/door.ogg"
    )
    assert metadata["local_cache_path"] == "sound_effects/action/door.ogg"
    assert storage.get_audio_library_storage_driver() == "dashscope_oss"
    assert storage.is_audio_library_cloud_storage_enabled() is True


def test_aliyun_oss_upload_uses_configured_bucket_and_public_host(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "aliyun_oss")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "sggf-audio-library")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", "secret")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PREFIX", "shared/audio_library")
    calls = []

    def fake_put(url, *, content, headers, timeout):
        calls.append(
            {
                "url": url,
                "content": content.read(),
                "headers": headers,
                "timeout": timeout,
            }
        )
        return type("Response", (), {"status_code": 200, "text": ""})()

    monkeypatch.setattr(storage.httpx, "put", fake_put)
    local_file = tmp_path / "door.ogg"
    local_file.write_bytes(b"OggS")

    metadata = storage.upload_audio_library_asset(
        local_path=local_file,
        relative_path="sound_effects/action/door.ogg",
        library_type="sfx",
    )

    assert calls
    assert calls[0]["url"] == (
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/"
        "shared/audio_library/sfx/sound_effects/action/door.ogg"
    )
    assert calls[0]["content"] == b"OggS"
    assert calls[0]["headers"]["Content-Type"] == "audio/ogg"
    assert calls[0]["headers"]["Authorization"].startswith("OSS ak:")
    assert metadata["storage_mode"] == "durable_cloud"
    assert metadata["storage_driver"] == "aliyun_oss"
    assert metadata["cloud_uri"] == "oss://shared/audio_library/sfx/sound_effects/action/door.ogg"
    assert metadata["object_key"] == "shared/audio_library/sfx/sound_effects/action/door.ogg"
    assert metadata["public_url"] == (
        "https://audio.sggf.net/shared/audio_library/sfx/sound_effects/action/door.ogg"
    )
    assert metadata["local_cache_path"] == "sound_effects/action/door.ogg"
    assert storage.get_audio_library_storage_driver() == "aliyun_oss"
    assert storage.is_audio_library_cloud_storage_enabled() is True


def test_aliyun_oss_upload_missing_config_keeps_local_cache(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "aliyun_oss")
    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", raising=False)
    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT", raising=False)
    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", raising=False)
    local_file = tmp_path / "door.ogg"
    local_file.write_bytes(b"OggS")

    metadata = storage.upload_audio_library_asset(
        local_path=local_file,
        relative_path="sound_effects/action/door.ogg",
        library_type="sfx",
    )

    assert metadata == {
        "storage_mode": "local_cache",
        "storage_driver": "local_fs",
        "local_cache_path": "sound_effects/action/door.ogg",
        "asset_scope": "shared_library",
    }


def test_build_public_url_prefers_configured_audio_library_host(monkeypatch):
    from app.services.audiobook.audio_asset_cloud_storage import build_audio_library_public_url

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")

    public_url = build_audio_library_public_url(
        cloud_uri="oss://shared/audio_library/sfx/sound_effects/action/door hit.wav",
        fallback_url="https://old-cdn.example.test/door-hit.wav",
    )

    assert public_url == "https://audio.sggf.net/shared/audio_library/sfx/sound_effects/action/door%20hit.wav"


def test_build_public_url_keeps_fallback_when_public_host_is_unset(monkeypatch):
    from app.services.audiobook.audio_asset_cloud_storage import build_audio_library_public_url

    monkeypatch.delenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", raising=False)

    public_url = build_audio_library_public_url(
        object_key="shared/audio_library/sfx/door.wav",
        fallback_url="https://bucket.oss-cn-test.aliyuncs.com/shared/audio_library/sfx/door.wav",
    )

    assert public_url == "https://bucket.oss-cn-test.aliyuncs.com/shared/audio_library/sfx/door.wav"


def test_build_public_url_does_not_guess_object_key_from_fallback(monkeypatch):
    from app.services.audiobook.audio_asset_cloud_storage import build_audio_library_public_url

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")

    public_url = build_audio_library_public_url(
        fallback_url="https://old-cdn.example.test/sfx/legacy-rain.ogg",
    )

    assert public_url == "https://old-cdn.example.test/sfx/legacy-rain.ogg"


def test_build_public_url_keeps_dashscope_url_when_public_host_is_configured(monkeypatch):
    from app.services.audiobook.audio_asset_cloud_storage import build_audio_library_public_url

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_PUBLIC_HOST", "https://audio.sggf.net")

    public_url = build_audio_library_public_url(
        object_key="shared/audio-library/sfx/door.wav",
        fallback_url="https://bucket.oss-cn-test.aliyuncs.com/shared/audio-library/sfx/door.wav",
        storage_driver="dashscope_oss",
    )

    assert public_url == "https://bucket.oss-cn-test.aliyuncs.com/shared/audio-library/sfx/door.wav"


def test_aliyun_oss_list_objects_parses_bucket_items(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "aliyun_oss")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "sggf-audio-library")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", "secret")
    calls = []
    xml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<ListBucketResult xmlns=\"http://doc.oss-cn-shanghai.aliyuncs.com\">
  <Name>sggf-audio-library</Name>
  <Prefix>shared/audio_library/</Prefix>
  <MaxKeys>2</MaxKeys>
  <IsTruncated>false</IsTruncated>
  <Contents>
    <Key>shared/audio_library/sfx/a.wav</Key>
    <LastModified>2026-05-09T00:00:00.000Z</LastModified>
    <ETag>\"etag-a\"</ETag>
    <Size>12</Size>
    <StorageClass>STANDARD</StorageClass>
  </Contents>
  <CommonPrefixes>
    <Prefix>shared/audio_library/music/</Prefix>
  </CommonPrefixes>
  <KeyCount>1</KeyCount>
</ListBucketResult>"""

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return type(
            "Response",
            (),
            {"status_code": 200, "text": xml, "content": xml.encode("utf-8")},
        )()

    monkeypatch.setattr(storage.httpx, "get", fake_get)

    result = storage.list_audio_library_objects(prefix="shared/audio_library/", max_keys=2)

    assert calls[0]["url"] == (
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/"
        "?list-type=2&max-keys=2&prefix=shared%2Faudio_library%2F"
    )
    assert calls[0]["headers"]["Authorization"].startswith("OSS ak:")
    assert result["bucket"] == "sggf-audio-library"
    assert result["is_truncated"] is False
    assert result["items"] == [
        {
            "key": "shared/audio_library/sfx/a.wav",
            "last_modified": "2026-05-09T00:00:00.000Z",
            "etag": '"etag-a"',
            "size": 12,
            "storage_class": "STANDARD",
        }
    ]
    assert result["common_prefixes"] == ["shared/audio_library/music/"]


def test_aliyun_oss_head_object_reports_existing_asset(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "aliyun_oss")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "sggf-audio-library")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", "secret")
    calls = []

    def fake_head(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return type(
            "Response",
            (),
            {
                "status_code": 200,
                "headers": {
                    "Content-Length": "12",
                    "ETag": '"etag-a"',
                    "Last-Modified": "Mon, 09 May 2026 00:00:00 GMT",
                    "Content-Type": "audio/ogg",
                },
                "text": "",
            },
        )()

    monkeypatch.setattr(storage.httpx, "head", fake_head)

    result = storage.head_audio_library_object(object_key="shared/audio_library/sfx/a.ogg")

    assert calls[0]["url"] == (
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/"
        "shared/audio_library/sfx/a.ogg"
    )
    assert calls[0]["headers"]["Authorization"].startswith("OSS ak:")
    assert result["exists"] is True
    assert result["status_code"] == 200
    assert result["object_key"] == "shared/audio_library/sfx/a.ogg"
    assert result["content_length"] == 12
    assert result["etag"] == '"etag-a"'


def test_aliyun_oss_delete_object_returns_deleted_result(tmp_path, monkeypatch):
    from app.services.audiobook import audio_asset_cloud_storage as storage

    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_STORAGE_DRIVER", "aliyun_oss")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_BUCKET", "sggf-audio-library")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ENDPOINT", "oss-cn-shanghai.aliyuncs.com")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("AUDIOBOOK_AUDIO_LIBRARY_OSS_ACCESS_KEY_SECRET", "secret")
    calls = []

    def fake_delete(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return type("Response", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(storage.httpx, "delete", fake_delete)

    result = storage.delete_audio_library_object(object_key="shared/audio_library/sfx/a.ogg")

    assert calls[0]["url"] == (
        "https://sggf-audio-library.oss-cn-shanghai.aliyuncs.com/"
        "shared/audio_library/sfx/a.ogg"
    )
    assert calls[0]["headers"]["Authorization"].startswith("OSS ak:")
    assert result["deleted"] is True
    assert result["status_code"] == 204
    assert result["object_key"] == "shared/audio_library/sfx/a.ogg"
