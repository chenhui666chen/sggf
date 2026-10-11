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

    kling_image = image_generation_group["kling/kling-v3-image-generation"]
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
    # 动作组由 all-in-one 的 wan3.0-video 承接
    assert "wan3.0-video" in motion_ids


def _group_ids(manifest: dict, group_key: str) -> set[str]:
    return {item["model_id"] for item in manifest["groups"][group_key]}


class TestVideoGroupsDerivedFromArchive:
    """motion / video_edit 成员不再手写，由 config/models.yaml 的 modality 在视频宇宙上派生。

    2026-10-09 裁定（Slice 8 A1）：手写清单会把「档案说支持」和「UI 给入口」两件事脱钩——
    pixverse-v6-t2v 因为批量模板挂了 motion_control 能力就被放进动作组，实际档案 modality 只有
    text_to_video；而官方支持图生视频的 kling-v3、vidu 两档反而长期缺席。派生后唯一的
    事实源是档案 modality，改档案就等于改分组，代码里不留第二份名单。
    """

    def test_motion_group_equals_archive_image_to_video_declarants_in_universe(self) -> None:
        from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest, get_models_index

        _clear_asset_studio_model_catalog_caches()
        manifest = get_asset_studio_model_manifest()
        models_index = get_models_index()
        universe = _group_ids(manifest, "video_generation")

        expected = {
            model_id
            for model_id in universe
            if "image_to_video" in (models_index[model_id].get("modality") or [])
        }
        assert _group_ids(manifest, "motion") == expected

    def test_motion_group_covers_every_image_to_video_tier(self) -> None:
        """档位全放：官方支持图生视频且运行时可执行的档位都要有动作入口，由用户自行冒烟。"""
        from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

        _clear_asset_studio_model_catalog_caches()
        manifest = get_asset_studio_model_manifest()
        motion_ids = _group_ids(manifest, "motion")

        for model_id in (
            "wan3.0-video",
            "doubao-seedance-2-5",
            "doubao-seedance-2-0",
            "doubao-seedance-2-0-fast",
            "kling/kling-v3-video-generation",
            "kling/kling-v3-omni-video-generation",
            "vidu-q3-pro-img2video",
            "vidu-q3-pro-start-end2video",
        ):
            assert model_id in motion_ids, model_id

    def test_pure_text_to_video_tiers_are_not_in_motion_group(self) -> None:
        """反向断言：档案未声明 image_to_video 的纯文生视频档不许进动作组。

        pixverse-v6-t2v 早期靠批量模板挂上的 motion_control 能力混进过动作组，
        但官方 t2v 端点只接收 prompt，不接受参考图。
        """
        from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

        _clear_asset_studio_model_catalog_caches()
        motion_ids = _group_ids(get_asset_studio_model_manifest(), "motion")

        assert "pixverse-v6-t2v" not in motion_ids
        assert "vidu-q3-pro-text2video" not in motion_ids

    def test_video_edit_group_equals_archive_video_edit_declarants_in_universe(self) -> None:
        from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest, get_models_index

        _clear_asset_studio_model_catalog_caches()
        manifest = get_asset_studio_model_manifest()
        models_index = get_models_index()
        universe = _group_ids(manifest, "video_generation")

        expected = {
            model_id
            for model_id in universe
            if "video_edit" in (models_index[model_id].get("modality") or [])
        }
        assert _group_ids(manifest, "video_edit") == expected
        assert _group_ids(manifest, "dreamweaver_video_edit") == expected

    def test_video_edit_group_excludes_tiers_without_runtime_support(self) -> None:
        """kling-v3-omni 官方有视频编辑能力（media type=base），但档案未声明 video_edit、
        adapter 也未下发参考视频，接通前不许进编辑组。"""
        from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

        _clear_asset_studio_model_catalog_caches()
        manifest = get_asset_studio_model_manifest()

        assert "kling/kling-v3-omni-video-generation" not in _group_ids(manifest, "video_edit")
        assert "vidu-q3-pro-start-end2video" not in _group_ids(manifest, "video_edit")


def test_asset_studio_video_duration_options_follow_models_yaml() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_video_duration_options

    _clear_asset_studio_model_catalog_caches()
    duration_options = get_asset_studio_video_duration_options()

    # 区间模型展开成逐秒阶梯，只认 duration_options 的旧调用方（含后端兜底表）才不会退化成三个点
    assert duration_options["wan3.0-video"] == tuple(float(value) for value in range(2, 31))
    # kling / vidu / pixverse 在 YAML 里同样是 {min,max,default} 区间，一起按逐秒展开到官方上限
    assert duration_options["kling/kling-v3-video-generation"] == tuple(float(value) for value in range(3, 16))
    assert duration_options["vidu-q3-pro-text2video"] == tuple(float(value) for value in range(1, 17))
    assert duration_options["pixverse-v6-t2v"] == tuple(float(value) for value in range(1, 16))


def test_asset_studio_manifest_exposes_duration_range_metadata() -> None:
    """区间模型要把 min/max/step/default/supports_auto 交给前端，滑块才不会被压成四档下拉。"""
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()
    video_group = {item["model_id"]: item for item in manifest["groups"]["video_generation"]}

    wan30 = video_group["wan3.0-video"]
    assert wan30["duration_min"] == 2.0
    assert wan30["duration_max"] == 30.0
    assert wan30["duration_step"] == 1.0
    assert wan30["duration_default"] == 5.0
    assert wan30["duration_supports_auto"] is True
    assert wan30["duration_options"] == [float(value) for value in range(2, 31)]

    # 档位列表模型保持下拉语义，不得被区间改动波及
    seedance = video_group["doubao-seedance-2-0"]
    assert seedance["duration_min"] is None
    assert seedance["duration_max"] is None
    assert seedance["duration_step"] is None
    assert seedance["duration_default"] is None
    assert seedance["duration_supports_auto"] is False
    assert seedance["duration_options"] == [4.0, 5.0, 10.0, 15.0]


def test_asset_studio_catalog_exposes_seed_audio_scene_generation() -> None:
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()

    scene_audio = {item["model_id"]: item for item in manifest["groups"]["audio_scene"]}
    assert "seed-audio-1.0" in scene_audio
    assert scene_audio["seed-audio-1.0"]["label"] == "豆包音频生成模型 1.0"


def test_asset_studio_sound_effect_group_exposes_qwen_audio_next() -> None:
    """2026-10-10：qwen-audio-3.1-tts-next 作为第二条音效链路进组，与 seed-audio-1.0 并存。

    进组等于前端立刻有入口，所以同时锁四件事：档案能解析、状态在售、adapter 已在注册表里
    （音效组不在 GROUP_RUNTIME_OPERATIONS，没有别的用例会替它验可执行性），
    以及“不接受 duration 入参”的时长语义与豆包一致——实际长度由模型决定，结算按实际时长。
    默认值仍指向 seed-audio-1.0：新增不替换，避免音效链路的既有产出风格被顺手改掉。
    """
    from adapters.registry import registry
    from app.services.asset_studio_model_catalog import get_asset_studio_model_manifest
    from core.model_resolution import normalize_model_id

    _clear_asset_studio_model_catalog_caches()
    manifest = get_asset_studio_model_manifest()
    sound_effect = {item["model_id"]: item for item in manifest["groups"]["audio_sound_effect"]}

    assert "qwen-audio-3.1-tts-next" in sound_effect
    option = sound_effect["qwen-audio-3.1-tts-next"]
    assert option["status"] == "active"
    assert option["catalog_model_key"] == "qwen-audio-3.1-tts-next"
    assert option["modalities"] == ["text_to_audio"]
    assert option["duration_options"] == []
    assert option["duration_min"] is None
    assert option["duration_max"] is None

    seed_audio = sound_effect["seed-audio-1.0"]
    assert seed_audio["duration_options"] == option["duration_options"]
    assert manifest["defaults"]["asset_studio_audio_sound_effect"] == "seed-audio-1.0"
    assert registry.has_adapter(normalize_model_id("qwen-audio-3.1-tts-next"))
