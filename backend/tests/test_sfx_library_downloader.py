"""SfxLibraryDownloader 单元测试

覆盖：分类逻辑、许可过滤、文件命名、索引注册、下载流程（mock）
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
for path in (BACKEND_ROOT, PROJECT_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


DOWNLOADER_MODULE = "app.services.audiobook.sfx_library_downloader"


@pytest.fixture
def mod():
    try:
        import importlib
        m = importlib.import_module(DOWNLOADER_MODULE)
        return m
    except Exception as e:
        pytest.skip(f"模块加载失败: {e}")


@pytest.fixture(autouse=True)
def _patch_audio_library_dir(tmp_path, monkeypatch, mod):
    monkeypatch.setattr(
        f"{DOWNLOADER_MODULE}.AUDIO_LIBRARY_DIR",
        tmp_path / "audio_library",
    )
    monkeypatch.setattr(
        f"{DOWNLOADER_MODULE}.SOUND_EFFECTS_DIR",
        tmp_path / "audio_library" / "sound_effects",
    )


# ============== 分类逻辑测试 ==============


def test_classify_category_environment(mod):
    assert mod.classify_category("Rain Ambience", "Heavy rain sound", ["rain", "nature"]) == "environment"


def test_classify_category_action(mod):
    assert mod.classify_category("Door Open", "Wooden door opening", ["door", "wood"]) == "action"


def test_classify_category_emotion(mod):
    assert mod.classify_category("Heartbeat", "Slow heartbeat tension", ["heartbeat", "tension"]) == "emotion"


def test_classify_category_transition(mod):
    assert mod.classify_category("Whoosh", "Cinematic whoosh transition", ["whoosh", "transition"]) == "transition"


def test_classify_category_default_action(mod):
    assert mod.classify_category("Unknown Sound", "No keywords", ["xyz"]) == "action"


def test_classify_style(mod):
    assert mod.classify_style("Cinematic Impact", "Epic movie trailer", ["cinematic"]) == "cinematic"
    assert mod.classify_style("Field Recording", "Real outdoor recording", ["field", "recording"]) == "realistic"
    assert mod.classify_style("Magic Spell", "Fantasy enchantment", ["magic", "spell"]) == "fantasy"


def test_classify_scene(mod):
    scenes = mod.classify_scene("Forest Birds", "Birds in the forest", ["forest", "nature"])
    assert "outdoor" in scenes

    scenes = mod.classify_scene("Haunted House", "Scary horror atmosphere", ["horror", "ghost"])
    assert "horror" in scenes

    scenes = mod.classify_scene("Random Sound", "No scene keywords", ["xyz"])
    assert scenes == ["general"]


# ============== 文件命名测试 ==============


def test_sanitize_filename(mod):
    assert mod.sanitize_filename("Rain/Ambience Test") == "rain_ambience_test"
    assert mod.sanitize_filename("  Hello   World  ") == "hello_world"
    assert mod.sanitize_filename("a" * 100, max_length=20) == "a" * 20


def test_generate_effect_id(mod):
    eid = mod.generate_effect_id("environment", "freesound", "12345")
    assert eid.startswith("environment_freesound_")
    assert "12345" in eid
    assert len(eid.split("_")[-1]) >= 10


def test_generate_file_path(mod):
    path = mod.generate_file_path("environment", "realistic", "env_fs_abc123", "mp3")
    assert path == "sound_effects/environment/realistic/env_fs_abc123.mp3"


# ============== 许可过滤测试 ==============


def test_freesound_commercial_license(mod):
    adapter = mod.FreesoundAdapter("fake_key")
    assert adapter.is_license_commercial("Creative Commons 0") is True
    assert adapter.is_license_commercial("Creative Commons Attribution") is True
    assert adapter.is_license_commercial("Creative Commons Attribution 4.0") is True
    assert adapter.is_license_commercial("Creative Commons Attribution Noncommercial") is False
    assert adapter.is_license_commercial("Sampling+") is False
    adapter.close()


def test_pixabay_always_commercial(mod):
    adapter = mod.PixabayAdapter("fake_key")
    assert adapter.is_license_commercial("pixabay") is True
    adapter.close()


def test_filter_results_removes_noncommercial(mod):
    downloader = mod.SfxLibraryDownloader(freesound_api_key="fake", pixabay_api_key="fake")

    results = [
        mod.SfxSearchResult(
            source="freesound", source_id="1", name="Commercial",
            description="", download_url="http://x.com/1.mp3",
            license_name="Creative Commons 0", license_commercial=True,
            duration=5.0, tags=[],
        ),
        mod.SfxSearchResult(
            source="freesound", source_id="2", name="NonCommercial",
            description="", download_url="http://x.com/2.mp3",
            license_name="Creative Commons Attribution Noncommercial", license_commercial=False,
            duration=5.0, tags=[],
        ),
    ]

    config = mod.SfxDownloadConfig(commercial_only=True)
    filtered = downloader.filter_results(results, config)
    assert len(filtered) == 1
    assert filtered[0].name == "Commercial"
    downloader.close()


def test_filter_results_duration(mod):
    downloader = mod.SfxLibraryDownloader()

    results = [
        mod.SfxSearchResult(
            source="freesound", source_id="1", name="Too Short",
            description="", download_url="http://x.com/1.mp3",
            license_commercial=True, duration=0.1, tags=[],
        ),
        mod.SfxSearchResult(
            source="freesound", source_id="2", name="Too Long",
            description="", download_url="http://x.com/2.mp3",
            license_commercial=True, duration=120.0, tags=[],
        ),
        mod.SfxSearchResult(
            source="freesound", source_id="3", name="Just Right",
            description="", download_url="http://x.com/3.mp3",
            license_commercial=True, duration=5.0, tags=[],
        ),
    ]

    config = mod.SfxDownloadConfig(min_duration=0.3, max_duration=60.0, commercial_only=False)
    filtered = downloader.filter_results(results, config)
    assert len(filtered) == 1
    assert filtered[0].name == "Just Right"
    downloader.close()


def test_filter_results_keeps_short_effects_by_default(mod):
    downloader = mod.SfxLibraryDownloader()

    results = [
        mod.SfxSearchResult(
            source="freesound", source_id="1", name="Short Click",
            description="", download_url="http://x.com/1.mp3",
            license_commercial=True, duration=0.1, tags=[],
        ),
        mod.SfxSearchResult(
            source="freesound", source_id="2", name="Room Tone",
            description="", download_url="http://x.com/2.mp3",
            license_commercial=True, duration=5.0, tags=[],
        ),
    ]

    filtered = downloader.filter_results(results, mod.SfxDownloadConfig(commercial_only=False))

    assert [item.name for item in filtered] == ["Short Click", "Room Tone"]
    downloader.close()


# ============== 分类与记录构建测试 ==============


def test_classify_result(mod):
    downloader = mod.SfxLibraryDownloader()

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain in forest", download_url="http://x.com/rain.mp3",
        license_commercial=True, duration=10.0, tags=["rain", "nature", "forest"],
    )
    classification = downloader.classify_result(result)
    assert classification["category"] == "environment"
    assert classification["style"] in ("realistic", "peaceful")
    assert "outdoor" in classification["scenes"]
    downloader.close()


def test_build_record(mod):
    downloader = mod.SfxLibraryDownloader()

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain in forest", download_url="http://x.com/rain.mp3",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain", "nature"],
        source_url="https://freesound.org/s/123/",
        author="field-recordist",
        author_url="https://freesound.org/people/field-recordist/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    classification = {"category": "environment", "style": "realistic", "scenes": ["outdoor"]}
    record = downloader.build_record(result, classification)

    assert record["id"].startswith("environment_freesound_")
    assert record["category"] == "environment/realistic"
    assert record["file_path"].startswith("sound_effects/environment/realistic/")
    assert record["file_path"].endswith(".mp3")
    assert record["license"] == "Creative Commons 0"
    assert record["license_commercial"] is True
    assert "outdoor" in record["tags"]
    assert record["source"] == "freesound"
    assert record["source_url"] == "https://freesound.org/s/123/"
    assert record["author"] == "field-recordist"
    assert record["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert record["attribution_required"] is False
    assert record["redistribution_allowed"] is False
    assert record["raw_asset_exposure"] == "internal_only"
    assert record["duration_bucket"] == "medium"
    assert record["retrieved_at"]
    assert record["license_checked_at"]
    downloader.close()


def test_build_record_requires_attribution_fields_for_cc_by(mod):
    downloader = mod.SfxLibraryDownloader()

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain in forest", download_url="http://x.com/rain.mp3",
        license_name="Creative Commons Attribution", license_commercial=True,
        duration=10.0, tags=["rain", "nature"],
        source_url="https://freesound.org/s/123/",
        author="",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )

    assert downloader.build_record(result, {"category": "environment", "style": "realistic", "scenes": []}) is None
    downloader.close()


# ============== 索引注册测试 ==============


def test_register_to_index(tmp_path, mod):
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(index_path=index_path)

    record = {
        "id": "test_effect_001",
        "name": "Test Rain",
        "category": "environment/realistic",
        "file_path": "sound_effects/environment/realistic/test_effect_001.mp3",
        "description": "Test rain sound",
        "tags": ["rain", "test"],
        "source": "freesound",
        "license": "Creative Commons 0",
        "license_commercial": True,
    }

    downloader._register_to_index(record)

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["id"] == "test_effect_001"

    record2 = dict(record)
    record2["id"] = "test_effect_002"
    record2["name"] = "Test Wind"
    downloader._register_to_index(record2)

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 2
    downloader.close()


def test_register_to_index_updates_existing(tmp_path, mod):
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(index_path=index_path)

    record = {
        "id": "test_effect_001",
        "name": "Old Name",
        "category": "action",
        "file_path": "sound_effects/action/test.mp3",
        "description": "Old desc",
        "tags": [],
        "source": "manual",
    }
    downloader._register_to_index(record)

    record["name"] = "New Name"
    record["description"] = "New desc"
    downloader._register_to_index(record)

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["name"] == "New Name"
    downloader.close()


# ============== 下载流程测试（mock） ==============


def test_download_and_register_success(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(
        output_dir=output_dir,
        index_path=index_path,
        allow_freesound_commercial_api=True,
    )

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain", download_url="http://example.com/rain.mp3",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain"],
        source_url="https://freesound.org/s/123/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    config = mod.SfxDownloadConfig()

    with patch.object(downloader, "download_file", return_value=True):
        with patch.object(downloader, "_finalize_download_record", return_value=True):
            record = downloader.download_and_register(result, config)

    assert record is not None
    assert record["source"] == "freesound"
    assert record["license_commercial"] is True

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert any(r["id"] == record["id"] for r in data)
    downloader.close()


def test_download_and_register_rejects_html_download(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(
        output_dir=output_dir,
        index_path=index_path,
        allow_freesound_commercial_api=True,
    )

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain", download_url="http://example.com/page",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain"],
        source_url="https://freesound.org/s/123/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    config = mod.SfxDownloadConfig()

    with patch.object(
        downloader,
        "download_file",
        side_effect=lambda url, target_path, overwrite=False: (
            target_path.parent.mkdir(parents=True, exist_ok=True) or target_path.write_bytes(b"<html></html>") or True
        ),
    ):
        record = downloader.download_and_register(result, config)

    assert record is None
    assert not index_path.exists()
    downloader.close()


def test_download_and_register_dry_run(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain", download_url="http://example.com/rain.mp3",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain"],
        source_url="https://freesound.org/s/123/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    config = mod.SfxDownloadConfig(dry_run=True)

    record = downloader.download_and_register(result, config)
    assert record is not None
    assert not index_path.exists()
    downloader.close()


def test_download_and_register_blocks_freesound_without_commercial_api_approval(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain", download_url="http://example.com/rain.mp3",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain"],
        source_url="https://freesound.org/s/123/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    config = mod.SfxDownloadConfig()

    with patch.object(downloader, "download_file") as mock_dl:
        record = downloader.download_and_register(result, config)

    assert record is None
    mock_dl.assert_not_called()
    assert not index_path.exists()
    downloader.close()


def test_download_and_register_skips_existing(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(
        output_dir=output_dir,
        index_path=index_path,
        allow_freesound_commercial_api=True,
    )

    result = mod.SfxSearchResult(
        source="freesound", source_id="123", name="Rain Ambience",
        description="Heavy rain", download_url="http://example.com/rain.mp3",
        license_name="Creative Commons 0", license_commercial=True,
        duration=10.0, tags=["rain"],
        source_url="https://freesound.org/s/123/",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    )
    config = mod.SfxDownloadConfig(overwrite=False)

    classification = downloader.classify_result(result)
    record = downloader.build_record(result, classification)
    target_path = output_dir.parent / record["file_path"]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"existing")

    with patch.object(downloader, "download_file") as mock_dl:
        with patch.object(downloader, "_finalize_download_record", return_value=True):
            ret = downloader.download_and_register(result, config)
        mock_dl.assert_not_called()

    assert ret is not None
    assert downloader._stats["skipped_existing"] == 1
    downloader.close()


# ============== 搜索源测试 ==============


def test_search_source_freesound_no_key(mod):
    downloader = mod.SfxLibraryDownloader(freesound_api_key="")
    results = downloader.search_source("freesound", "rain")
    assert results == []
    downloader.close()


def test_search_source_pixabay_no_key(mod):
    downloader = mod.SfxLibraryDownloader(pixabay_api_key="")
    results = downloader.search_source("pixabay", "rain")
    assert results == []
    downloader.close()


def test_search_source_pixabay_disabled_even_with_key(mod):
    downloader = mod.SfxLibraryDownloader(pixabay_api_key="fake")
    results = downloader.search_source("pixabay", "rain")
    assert results == []
    downloader.close()


def test_search_source_unknown(mod):
    downloader = mod.SfxLibraryDownloader()
    results = downloader.search_source("unknown_source", "rain")
    assert results == []
    downloader.close()


def test_freesound_search_with_mock(mod):
    adapter = mod.FreesoundAdapter("fake_key", commercial_api_approved=True)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {
                "id": 123,
                "name": "Rain Ambience",
                "description": "Heavy rain sound",
                "license": "Creative Commons 0",
                "previews": {
                    "preview-hq-mp3": "http://example.com/preview.mp3",
                    "preview-lq-mp3": "http://example.com/preview_lq.mp3",
                },
                "url": "https://freesound.org/s/123/",
                "username": "field-recordist",
                "tags": ["rain", "nature"],
                "duration": 10.5,
                "samplerate": 44100,
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(adapter.client, "get", return_value=mock_response):
        results = adapter.search("rain")

    assert len(results) == 1
    assert results[0].source == "freesound"
    assert results[0].source_id == "123"
    assert results[0].license_commercial is True
    assert results[0].duration == 10.5
    assert results[0].source_url == "https://freesound.org/s/123/"
    assert results[0].author == "field-recordist"
    assert results[0].download_url == ""
    assert results[0].preview_url == "http://example.com/preview.mp3"
    adapter.close()


def test_freesound_search_requires_commercial_api_approval(mod):
    adapter = mod.FreesoundAdapter("fake_key")
    assert adapter.search("rain") == []
    adapter.close()


def test_pixabay_search_with_mock(mod):
    adapter = mod.PixabayAdapter("fake_key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hits": [
            {
                "id": 456,
                "tags": "rain, nature, ambient",
                "pageURL": "http://pixabay.com/sound/456",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
        results = adapter.search("rain")

    assert results == []
    mock_get.assert_not_called()
    adapter.close()


# ============== 完整 run 流程测试 ==============


def test_run_with_mock_search(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(
        freesound_api_key="fake",
        output_dir=output_dir,
        index_path=index_path,
        allow_freesound_commercial_api=True,
    )

    mock_results = [
        mod.SfxSearchResult(
            source="freesound", source_id="1", name="Rain Ambience",
            description="Heavy rain in forest", download_url="http://x.com/rain.mp3",
            license_name="Creative Commons 0", license_commercial=True,
            duration=10.0, tags=["rain", "nature", "forest"],
        ),
        mod.SfxSearchResult(
            source="freesound", source_id="2", name="NonCommercial Sound",
            description="NC sound", download_url="http://x.com/nc.mp3",
            license_name="Creative Commons Attribution Noncommercial", license_commercial=False,
            duration=5.0, tags=["nc"],
        ),
    ]

    config = mod.SfxDownloadConfig(
        sources=["freesound"],
        search_queries=["rain"],
        commercial_only=True,
        dry_run=True,
    )

    with patch.object(downloader, "search_source", return_value=mock_results):
        result = downloader.run(config)

    assert result["stats"]["searched"] == 2
    assert result["stats"]["filtered_license"] == 1
    assert result["stats"]["downloaded"] == 0
    downloader.close()


# ============== 目录结构测试 ==============


def test_directory_structure_follows_category_style(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(
        output_dir=output_dir,
        index_path=index_path,
        allow_freesound_commercial_api=True,
    )

    result = mod.SfxSearchResult(
        source="freesound", source_id="999", name="Cinematic Whoosh",
        description="Epic cinematic whoosh transition", download_url="http://x.com/whoosh.mp3",
        license_name="Creative Commons Attribution", license_commercial=True,
        duration=2.0, tags=["whoosh", "cinematic", "transition"],
        source_url="https://freesound.org/s/999/",
        author="whoosh-maker",
        author_url="https://freesound.org/people/whoosh-maker/",
        license_url="https://creativecommons.org/licenses/by/4.0/",
    )
    config = mod.SfxDownloadConfig()

    with patch.object(downloader, "download_file", return_value=True):
        with patch.object(downloader, "_finalize_download_record", return_value=True):
            record = downloader.download_and_register(result, config)

    assert record is not None
    assert record["category"] == "transition/cinematic"
    assert record["file_path"].startswith("sound_effects/transition/cinematic/")
    downloader.close()


# ============== Local authorized asset import tests ==============


def _write_manifest_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )


def test_wikimedia_audiobook_sfx_pack_covers_core_scene_categories():
    audio_library_dir = Path(__file__).resolve().parents[1] / "data" / "audio_library"
    manifest_path = audio_library_dir / "sfx_import_manifest_wikimedia_commons_audiobook_pack.jsonl"
    source_dir = audio_library_dir / "approved_sfx"

    assert manifest_path.exists()

    rows = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) >= 16

    categories = {str(row.get("category") or "").strip() for row in rows}
    assert {"environment", "action", "emotion", "transition"}.issubset(categories)

    all_tags = {tag for row in rows for tag in row.get("tags", [])}
    assert {"footstep", "door", "paper", "heartbeat", "breath", "crowd", "fire", "whoosh"}.issubset(all_tags)

    allowed_licenses = {"CC0", "Public Domain"}
    for row in rows:
        assert row.get("license") in allowed_licenses
        assert row.get("license_commercial") is True
        assert row.get("attribution_required") is False
        assert row.get("source_url", "").startswith("https://commons.wikimedia.org/wiki/File:")
        assert row.get("license_url", "").startswith("https://creativecommons.org/publicdomain/")
        assert (source_dir / str(row.get("file") or "")).exists()


def test_import_local_assets_dry_run_does_not_write_index(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "rain.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
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
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = downloader.import_local_assets(source_dir, manifest_path, dry_run=True)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["imported"] == 0
    assert len(result["records"]) == 1
    assert result["records"][0]["source"] == "local_authorized"
    assert not index_path.exists()
    assert not list(output_dir.rglob("*.wav"))
    downloader.close()


def test_import_local_assets_uses_manifest_category_and_style_hints(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "door.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "door.wav",
                "name": "Wood Door Knock",
                "description": "Licensed wooden door knock",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/door",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "category": "transition",
                "style": "fantasy",
                "tags": ["door", "knock"],
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = downloader.import_local_assets(source_dir, manifest_path, dry_run=True)

    assert result["stats"]["candidates"] == 1
    assert result["records"][0]["category"] == "transition/fantasy"
    assert result["records"][0]["file_path"].startswith("sound_effects/transition/fantasy/")
    downloader.close()


def test_import_local_assets_rejects_missing_license_metadata(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "whoosh.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "whoosh.wav",
                "name": "Whoosh",
                "license": "Creative Commons Attribution",
                "license_commercial": True,
                "source_url": "https://example.com/assets/whoosh",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["rejected_license"] == 1
    assert result["stats"]["imported"] == 0
    assert result["records"] == []
    assert not index_path.exists()
    downloader.close()


def test_import_local_assets_rejects_missing_source_url_for_cc0(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "rain.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "rain.wav",
                "name": "Rain",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["rejected_license"] == 1
    assert result["stats"]["imported"] == 0
    assert result["records"] == []
    assert not index_path.exists()
    downloader.close()


def test_import_local_assets_rejects_string_false_commercial_flag(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "nc.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "nc.wav",
                "name": "NC Ambience",
                "license": "Creative Commons Attribution Noncommercial",
                "license_commercial": "false",
                "source_url": "https://example.com/assets/nc",
                "author": "field-recordist",
                "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["rejected_license"] == 1
    assert result["stats"]["imported"] == 0
    assert result["records"] == []
    assert not index_path.exists()
    downloader.close()


def test_import_local_assets_registers_quality_checked_file(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "door.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "assets": [
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
                        "duration": 2.5,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    with patch.object(
        downloader,
        "_assess_downloaded_quality",
        return_value={"quality_score": 92.0, "quality_grade": "A", "quality_status": "accepted"},
    ):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["imported"] == 1
    record = result["records"][0]
    assert record["source"] == "local_authorized"
    assert record["license"] == "Creative Commons Attribution"
    assert record["attribution_required"] is True
    assert record["attribution_text"] == "Wood Door Open by foley-author, CC BY 4.0"
    assert record["quality_status"] == "accepted"
    assert record["sha256"]
    assert (output_dir.parent / record["file_path"]).exists()

    with index_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["id"] == record["id"]
    downloader.close()


def test_import_local_assets_attaches_cloud_metadata_for_shared_library(tmp_path, mod, monkeypatch):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "door.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "door.wav",
                "name": "Wood Door Open",
                "description": "Licensed wooden door opening",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/door",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "tags": ["door", "wood"],
            }
        ],
    )

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

    monkeypatch.setattr(mod, "upload_audio_library_asset", fake_upload_audio_library_asset)

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    with patch.object(
        downloader,
        "_assess_downloaded_quality",
        return_value={"quality_score": 92.0, "quality_grade": "A", "quality_status": "accepted"},
    ):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["imported"] == 1
    record = result["records"][0]
    assert uploaded == [(Path(record["file_path"]).name, record["file_path"], "sfx")]
    assert record["storage_mode"] == "durable_cloud"
    assert record["storage_driver"] == "dashscope_oss"
    assert record["cloud_uri"].startswith("oss://shared/audio-library/sfx/")
    assert record["public_url"].startswith("https://cdn.example.test/sfx/")

    with index_path.open("r", encoding="utf-8") as f:
        indexed = json.load(f)
    assert indexed[0]["cloud_uri"] == record["cloud_uri"]
    downloader.close()


def test_import_local_assets_preserves_manifest_source_payload(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "drawer.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "drawer.wav",
                "name": "Drawer Open",
                "description": "Licensed drawer opening",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/desk-pack",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "source_payload_json": {
                    "pack": "desk_pack",
                    "archive_member": "sfx/drawer-open.wav",
                },
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    with patch.object(
        downloader,
        "_assess_downloaded_quality",
        return_value={"quality_score": 92.0, "quality_grade": "A", "quality_status": "accepted"},
    ):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["imported"] == 1
    record = result["records"][0]
    assert record["source_payload_json"] == {
        "pack": "desk_pack",
        "archive_member": "sfx/drawer-open.wav",
    }

    with index_path.open("r", encoding="utf-8") as f:
        indexed = json.load(f)
    assert indexed[0]["source_payload_json"]["archive_member"] == "sfx/drawer-open.wav"
    downloader.close()


def test_import_local_assets_handles_relative_output_and_index_paths(tmp_path, mod, monkeypatch):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "door.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "door.wav",
                "name": "Wood Door Open",
                "description": "Licensed wooden door opening",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/door",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "tags": ["door", "wood"],
            }
        ],
    )

    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)
    downloader = mod.SfxLibraryDownloader(
        output_dir=Path("audio_library") / "sound_effects",
        index_path=Path("audio_library") / "sound_effects_index.json",
    )

    assessed_paths = []

    def fake_assess(file_path):
        assessed_paths.append(Path(file_path))
        return {"quality_score": 92.0, "quality_grade": "A", "quality_status": "accepted"}

    with patch.object(downloader, "_assess_downloaded_quality", side_effect=fake_assess):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["imported"] == 1
    record = result["records"][0]
    assert downloader.output_dir.is_absolute()
    assert downloader.index_path.is_absolute()
    expected_target = downloader.output_dir.parent / record["file_path"]
    assert assessed_paths == [expected_target]
    assert expected_target.exists()
    assert (work_dir / "audio_library" / "sound_effects_index.json").exists()
    downloader.close()


def test_import_local_assets_rejects_low_quality_file(tmp_path, mod):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    (source_dir / "noise.wav").write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "noise.wav",
                "name": "Bad Noise",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/noise",
                "author": "field-recordist",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    with patch.object(
        downloader,
        "_assess_downloaded_quality",
        return_value={"quality_score": 10.0, "quality_grade": "D", "quality_status": "rejected"},
    ):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["rejected_quality"] == 1
    assert result["stats"]["imported"] == 0
    assert result["records"] == []
    assert not index_path.exists()
    assert not list(output_dir.rglob("*.wav"))
    downloader.close()


def test_import_local_assets_normalizes_quiet_licensed_file_before_quality_check(tmp_path, mod, monkeypatch):
    source_dir = tmp_path / "licensed_sfx"
    source_dir.mkdir()
    source_file = source_dir / "quiet.wav"
    source_file.write_bytes(b"RIFF0000WAVEfmt ")
    manifest_path = source_dir / "license_manifest.jsonl"
    _write_manifest_jsonl(
        manifest_path,
        [
            {
                "file": "quiet.wav",
                "name": "Quiet Forest Ambience",
                "description": "Quiet but usable ambience",
                "license": "Creative Commons 0",
                "license_commercial": True,
                "source_url": "https://example.com/assets/quiet-forest",
                "author": "field-recordist",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "category": "environment",
                "style": "peaceful",
            }
        ],
    )

    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)

    normalize_calls = []

    def fake_normalize(target_path):
        normalize_calls.append(Path(target_path))
        Path(target_path).write_bytes(b"RIFF1111WAVEfmt normalized")
        return True

    monkeypatch.setattr(downloader, "_normalize_audio_loudness", fake_normalize)

    quality_results = [
        {"quality_score": 30.0, "quality_grade": "D", "quality_status": "rejected"},
        {"quality_score": 80.0, "quality_grade": "B", "quality_status": "accepted"},
    ]

    with patch.object(downloader, "_assess_downloaded_quality", side_effect=quality_results):
        result = downloader.import_local_assets(source_dir, manifest_path)

    assert result["stats"]["candidates"] == 1
    assert result["stats"]["imported"] == 1
    assert result["stats"]["rejected_quality"] == 0
    record = result["records"][0]
    target_path = output_dir.parent / record["file_path"]
    assert normalize_calls == [target_path]
    assert target_path.read_bytes().endswith(b"normalized")
    assert source_file.read_bytes() == b"RIFF0000WAVEfmt "
    assert record["quality_status"] == "accepted"
    assert record["loudness_normalized"] is True
    downloader.close()


# ============== Public source candidate discovery tests ==============


def test_openverse_candidate_search_maps_audit_fields_without_download_url(mod):
    adapter = mod.OpenverseCandidateAdapter()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "id": "ov-1",
                "title": "Rain Ambience",
                "description": "Rain in forest",
                "foreign_landing_url": "https://example.org/rain",
                "url": "https://cdn.example.org/rain.mp3",
                "creator": "field-recordist",
                "creator_url": "https://example.org/people/field-recordist",
                "license": "by",
                "license_version": "4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "duration": 12.5,
                "tags": [{"name": "rain"}, {"name": "forest"}],
            },
            {
                "id": "ov-nc",
                "title": "NC Sound",
                "foreign_landing_url": "https://example.org/nc",
                "license": "by-nc",
                "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
            },
        ]
    }

    with patch.object(adapter.client, "get", return_value=mock_response):
        candidates = adapter.search("rain", page_size=5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "openverse"
    assert candidate.source_id == "ov-1"
    assert candidate.source_url == "https://example.org/rain"
    assert candidate.file_url == "https://cdn.example.org/rain.mp3"
    assert candidate.license_name == "CC-BY 4.0"
    assert candidate.license_commercial is True
    assert candidate.attribution_required is True
    assert candidate.author == "field-recordist"
    assert candidate.requires_manual_review is True
    assert "download_url" not in candidate.to_record()
    adapter.close()


def test_wikimedia_candidate_search_maps_extmetadata(mod):
    adapter = mod.WikimediaCandidateAdapter()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "query": {
            "pages": {
                "10": {
                    "pageid": 10,
                    "title": "File:Forest rain.ogg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/rain.ogg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Forest_rain.ogg",
                            "mime": "audio/ogg",
                            "extmetadata": {
                                "ObjectName": {"value": "Forest rain"},
                                "ImageDescription": {"value": "Rain in a forest"},
                                "Artist": {"value": "Recorder Name"},
                                "LicenseShortName": {"value": "CC BY 4.0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                                "AttributionRequired": {"value": "true"},
                            },
                        }
                    ],
                }
            }
        }
    }

    with patch.object(adapter.client, "get", return_value=mock_response):
        candidates = adapter.search("rain", page_size=5)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "wikimedia_commons"
    assert candidate.source_id == "10"
    assert candidate.name == "Forest rain"
    assert candidate.source_url == "https://commons.wikimedia.org/wiki/File:Forest_rain.ogg"
    assert candidate.file_url == "https://upload.wikimedia.org/rain.ogg"
    assert candidate.license_name == "CC BY 4.0"
    assert candidate.license_commercial is True
    assert candidate.attribution_required is True
    assert candidate.author == "Recorder Name"
    assert candidate.requires_manual_review is True
    adapter.close()


def test_discover_public_candidates_writes_jsonl_without_index_or_downloads(tmp_path, mod):
    output_dir = tmp_path / "audio_library" / "sound_effects"
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    candidate_path = tmp_path / "audio_library" / "sfx_candidates.jsonl"
    downloader = mod.SfxLibraryDownloader(output_dir=output_dir, index_path=index_path)
    candidate = mod.SfxCandidate(
        source="openverse",
        source_id="ov-1",
        name="Rain Ambience",
        description="Rain",
        source_url="https://example.org/rain",
        file_url="https://cdn.example.org/rain.mp3",
        license_name="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        license_commercial=True,
        author="field-recordist",
        tags=["rain"],
        query="rain",
    )

    with patch.object(downloader, "search_candidate_source", return_value=[candidate]):
        result = downloader.discover_public_candidates(
            sources=["openverse"],
            queries=["rain"],
            output_path=candidate_path,
            request_delay=0.0,
        )

    assert result["stats"]["searched"] == 1
    assert result["stats"]["candidates"] == 1
    assert result["stats"]["exported"] == 1
    assert not index_path.exists()
    assert not output_dir.exists()

    rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["source"] == "openverse"
    assert rows[0]["status"] == "candidate_only"
    assert rows[0]["requires_manual_review"] is True
    assert "download_url" not in rows[0]
    downloader.close()


# ============== Credits export tests ==============


def test_export_attribution_credits_writes_jsonl_and_markdown(tmp_path, mod):
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "cc_by_rain",
                    "name": "Rain Ambience",
                    "source": "local_authorized",
                    "source_id": "rain",
                    "source_url": "https://example.org/rain",
                    "author": "field-recordist",
                    "author_url": "https://example.org/people/field-recordist",
                    "license": "Creative Commons Attribution 4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "license_version": "4.0",
                    "attribution_required": True,
                    "attribution_text": "Rain Ambience by field-recordist, CC BY 4.0",
                    "file_path": "sound_effects/environment/realistic/rain.wav",
                },
                {
                    "id": "cc0_wind",
                    "name": "Wind",
                    "source": "local_authorized",
                    "license": "Creative Commons 0",
                    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                    "attribution_required": False,
                    "file_path": "sound_effects/environment/realistic/wind.wav",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "exports" / "license_manifest.jsonl"
    markdown_path = tmp_path / "exports" / "CREDITS.md"
    downloader = mod.SfxLibraryDownloader(index_path=index_path)

    result = downloader.export_attribution_credits(
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
    )

    assert result["stats"]["indexed"] == 2
    assert result["stats"]["credits"] == 1
    assert result["jsonl_path"] == str(jsonl_path)
    assert result["markdown_path"] == str(markdown_path)

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["effect_id"] == "cc_by_rain"
    assert rows[0]["attribution_text"] == "Rain Ambience by field-recordist, CC BY 4.0"
    assert rows[0]["raw_asset_exposure"] == "internal_only"

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Audio Credits" in markdown
    assert "Rain Ambience by field-recordist, CC BY 4.0" in markdown
    assert "cc0_wind" not in markdown
    downloader.close()


def test_export_attribution_credits_deduplicates_and_filters_used_ids(tmp_path, mod):
    index_path = tmp_path / "audio_library" / "sound_effects_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            [
                {
                    "id": "rain_1",
                    "name": "Rain",
                    "source": "local_authorized",
                    "source_url": "https://example.org/rain",
                    "author": "field-recordist",
                    "license": "Creative Commons Attribution",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "attribution_required": True,
                    "attribution_text": "Rain by field-recordist, CC BY 4.0",
                },
                {
                    "id": "rain_duplicate",
                    "name": "Rain Duplicate",
                    "source": "local_authorized",
                    "source_url": "https://example.org/rain",
                    "author": "field-recordist",
                    "license": "Creative Commons Attribution",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "attribution_required": True,
                    "attribution_text": "Rain by field-recordist, CC BY 4.0",
                },
                {
                    "id": "unused_door",
                    "name": "Door",
                    "source": "local_authorized",
                    "source_url": "https://example.org/door",
                    "author": "foley-author",
                    "license": "Creative Commons Attribution",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "attribution_required": True,
                    "attribution_text": "Door by foley-author, CC BY 4.0",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "exports" / "license_manifest.jsonl"
    markdown_path = tmp_path / "exports" / "CREDITS.md"
    downloader = mod.SfxLibraryDownloader(index_path=index_path)

    result = downloader.export_attribution_credits(
        jsonl_path=jsonl_path,
        markdown_path=markdown_path,
        used_effect_ids={"rain_1", "rain_duplicate"},
    )

    assert result["stats"]["indexed"] == 3
    assert result["stats"]["filtered_unused"] == 1
    assert result["stats"]["deduplicated"] == 1
    assert result["stats"]["credits"] == 1

    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert [row["effect_id"] for row in rows] == ["rain_1"]
    assert "unused_door" not in markdown_path.read_text(encoding="utf-8")
    downloader.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
