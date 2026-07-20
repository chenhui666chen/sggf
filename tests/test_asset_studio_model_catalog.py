from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
for candidate in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _clear_asset_studio_model_catalog_caches() -> None:
    from app.services import asset_studio_model_catalog as catalog_service

    catalog_service.get_models_index.cache_clear()
    catalog_service.get_asset_studio_model_manifest.cache_clear()
    catalog_service.get_asset_studio_model_sets.cache_clear()
    catalog_service.get_asset_studio_video_duration_options.cache_clear()


def test_asset_studio_model_manifest_uses_latest_model_metadata() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()

    image_generation_group = {
        item["model_id"]: item
        for item in manifest["groups"]["image_generation"]
    }

    kling_image = image_generation_group["kling-v3-image-generation"]
    assert kling_image["catalog_model_key"] == "kling/kling-v3-image-generation"
    assert kling_image["label"] == "Kling V3 Image Generation"


def test_asset_studio_model_manifest_keeps_motion_default_inside_motion_group() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()

    motion_ids = {
        item["model_id"]
        for item in manifest["groups"]["motion"]
    }

    assert manifest["defaults"]["asset_studio_motion"] in motion_ids
    assert "wan2.7-i2v" in motion_ids


def test_asset_studio_video_duration_options_follow_models_yaml() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_video_duration_options

    _clear_asset_studio_model_catalog_caches()
    duration_options = get_asset_studio_video_duration_options()

    assert duration_options["wan2.7-t2v"] == (3.0, 5.0, 10.0, 15.0)
    assert duration_options["wan2.7-i2v"] == (3.0, 5.0, 10.0)
    assert duration_options["kling-v3-video-generation"] == (5.0, 10.0)


def test_asset_studio_catalog_exposes_seed_audio_scene_generation() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()

    scene_audio = {item["model_id"]: item for item in manifest["groups"]["audio_scene"]}
    assert "seed-audio-1.0" in scene_audio
    assert scene_audio["seed-audio-1.0"]["label"] == "豆包音频生成模型 1.0"
