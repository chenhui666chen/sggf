# -*- coding: utf-8 -*-
"""Asset Studio 模型目录与媒体运行时的一致性守卫。

目录有两份清单必须同步：_GROUP_MODEL_IDS（前端下拉可选项）与 _DEFAULT_MODEL_IDS（默认值）。
默认值如果不在对应分组里，前端 applyModelOptionSync 会立刻把用户选择重置，表现为"选了又跳回去"。
每个分组里的 ID 还必须同时满足执行层（注册表里有 adapter）与路由层（在对应 operation 白名单里），
否则要到运行期才失败。

退役策略（用户 2026-10-08 决定）：模型退役即从配置与目录里物理删除，不保留 deprecated 兼容位，
因此本文件不再枚举任何旧 ID，只用「目录里不许出现 deprecated 状态」这一条泛化断言守住。
"""
from __future__ import annotations

import pytest

from adapters.registry import registry
from core.model_resolution import normalize_model_id
from core.unified_media_runtime import _OPERATION_MODEL_IDS
from app.services.asset_studio_model_catalog import (
    _DEFAULT_MODEL_IDS,
    _GROUP_MODEL_IDS,
    get_asset_studio_default_model_id,
    get_asset_studio_model_manifest,
    get_asset_studio_model_sets,
)

IMAGE_GROUPS = ("image_generation", "dreamweaver_image")

ACTIVE_IMAGE_IDS = ("qwen-image-3.0", "qwen-image-3.0-pro", "wan2.7-image-pro")

# 分组 → 媒体运行时 operation。音频三条不走 _OPERATION_MODEL_IDS：
# 音乐（mureka）、音效与场景（seed-audio）由 asset_studio 自己的引擎通道执行。
GROUP_RUNTIME_OPERATIONS = {
    "image_generation": ("generate_image",),
    "image_edit": ("edit_image",),
    "video_generation": ("generate_video",),
    "video_edit": ("edit_video",),
    "motion": ("generate_video",),
    "audio_speech": ("synthesize_speech",),
    "vision_review": ("analyze_image", "analyze_video"),
    "dreamweaver_image": ("generate_image", "edit_image"),
    "dreamweaver_video": ("generate_video",),
    "dreamweaver_video_edit": ("edit_video",),
    "dreamweaver_vision": ("analyze_image", "analyze_video"),
}


class TestImageLineDefaults:
    def test_asset_studio_default_is_qwen_image_3_0(self):
        """用户明确决定：asset_studio_image_generation 的默认值改为 qwen-image-3.0，
        而不是万相线的 wan2.7-image-pro。"""
        assert _DEFAULT_MODEL_IDS["asset_studio_image_generation"] == "qwen-image-3.0"

    def test_dreamweaver_default_is_qwen_image_3_0_pro(self):
        assert _DEFAULT_MODEL_IDS["dreamweaver_image"] == "qwen-image-3.0-pro"

    def test_default_getter_returns_catalog_value_not_fallback(self):
        assert get_asset_studio_default_model_id("asset_studio_image_generation", "not-in-catalog") == "qwen-image-3.0"
        assert get_asset_studio_default_model_id("dreamweaver_image", "not-in-catalog") == "qwen-image-3.0-pro"


class TestGroupAllowlists:
    @pytest.mark.parametrize("group", IMAGE_GROUPS)
    @pytest.mark.parametrize("model_id", ACTIVE_IMAGE_IDS)
    def test_active_ids_are_selectable(self, group, model_id):
        assert model_id in _GROUP_MODEL_IDS[group], f"{model_id} 不在 {group} 分组里，前端选不到"

    def test_every_default_belongs_to_its_group(self):
        """默认值不在分组里会被前端 applyModelOptionSync 立刻重置，表现为选择跳回。"""
        group_by_default_key = {
            "asset_studio_image_generation": "image_generation",
            "asset_studio_image_edit": "image_edit",
            "asset_studio_video_generation": "video_generation",
            "asset_studio_video_edit": "video_edit",
            "asset_studio_motion": "motion",
            "asset_studio_audio_music": "audio_music",
            "asset_studio_audio_sound_effect": "audio_sound_effect",
            "asset_studio_audio_scene": "audio_scene",
            "asset_studio_audio_speech": "audio_speech",
            "asset_studio_vision_review": "vision_review",
            "dreamweaver_image": "dreamweaver_image",
            "dreamweaver_video": "dreamweaver_video",
            "dreamweaver_video_edit": "dreamweaver_video_edit",
            "dreamweaver_vision": "dreamweaver_vision",
        }
        for default_key, group_key in group_by_default_key.items():
            model_id = _DEFAULT_MODEL_IDS[default_key]
            assert model_id in _GROUP_MODEL_IDS[group_key], (
                f"{default_key} 的默认值 {model_id} 不在 {group_key} 分组里"
            )


class TestManifestExposesStatus:
    def test_manifest_only_exposes_active_image_models(self):
        """目录清单只暴露在售模型。"""
        manifest = get_asset_studio_model_manifest()
        by_id = {option["model_id"]: option for option in manifest["groups"]["image_generation"]}
        for model_id in ACTIVE_IMAGE_IDS:
            assert by_id[model_id]["status"] == "active", model_id

    def test_no_group_exposes_a_deprecated_option(self):
        manifest = get_asset_studio_model_manifest()
        offenders = {
            group: [option["model_id"] for option in options if option["status"] == "deprecated"]
            for group, options in manifest["groups"].items()
        }
        offenders = {group: ids for group, ids in offenders.items() if ids}
        assert not offenders, f"以下分组仍暴露已弃用模型: {offenders}"

    def test_manifest_defaults_match_module_constant(self):
        manifest = get_asset_studio_model_manifest()
        assert manifest["defaults"]["asset_studio_image_generation"] == "qwen-image-3.0"
        assert manifest["defaults"]["dreamweaver_image"] == "qwen-image-3.0-pro"

    def test_model_sets_agree_with_group_lists(self):
        sets = get_asset_studio_model_sets()
        for group in IMAGE_GROUPS:
            assert sets[group] == set(_GROUP_MODEL_IDS[group])


class TestMediaRegistryResolution:
    """目录 ID 必须同时满足「执行层有 adapter」和「路由层在 operation 白名单里」。

    这两条是 Asset Studio 可用水性的硬条件：缺 adapter 的请求要到运行期才报
    adapter_missing，缺白名单条目会在 _rank_candidates 里被直接过滤掉（表现为
    "选了却不通"）。目录新增模型时必须同步补齐两侧，本用例逐个分组守住。
    """

    @pytest.mark.parametrize("group", sorted(GROUP_RUNTIME_OPERATIONS))
    def test_group_ids_resolve_to_a_registered_adapter(self, group):
        """归一层解析后必须能拿到可执行 adapter。"""
        offenders = [
            model_id
            for model_id in _GROUP_MODEL_IDS[group]
            if not registry.has_adapter(normalize_model_id(model_id))
        ]
        assert not offenders, f"{group} 分组存在无 adapter 的条目: {offenders}"

    @pytest.mark.parametrize("group", sorted(GROUP_RUNTIME_OPERATIONS))
    def test_group_ids_are_in_media_runtime_allowlist(self, group):
        """媒体运行时白名单是硬过滤，漏掉就等于该模型在此分组下不可用。"""
        allowed_operations = GROUP_RUNTIME_OPERATIONS[group]
        offenders = [
            model_id
            for model_id in _GROUP_MODEL_IDS[group]
            if normalize_model_id(model_id)
            not in set().union(*(_OPERATION_MODEL_IDS.get(op, set()) for op in allowed_operations))
        ]
        assert not offenders, (
            f"{group} 分组的 {offenders} 不在 {'/'.join(allowed_operations)} 白名单里"
        )

