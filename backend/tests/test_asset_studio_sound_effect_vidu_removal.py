# -*- coding: utf-8 -*-
"""Vidu Timing2Audio 下线守卫。

2026-10-08 音效质量不达标，`vidu-timing2audio` 整体删除：适配器、服务层生成器、
`config/models.yaml` 条目、目录 profile、前端选项与文案全部移除；
音效链路收敛到 `seed-audio-1.0`。

实测记录（2026-10-08 真实 API）：`mureka-o1-instrumental` 会忽略 duration 入参，
请求 5 秒与 10 秒都返回约 190 秒的完整乐曲，因此不能作为短音效落点；
`seed-audio-1.0` 按提示词生成，短音效实测 4.0-5.5 秒、延迟 18-25 秒，
真实时长写在响应 metadata 的 duration 字段里。

与万相视频线、图像线的「新 ID + 旧 ID 保留」不同，本模型是彻底删除，
因此这里锁定的方向相反：任何一处重新出现该 ID 都应失败。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from app.services.asset_studio_model_catalog import (
    _DEFAULT_MODEL_IDS,
    _GROUP_MODEL_IDS,
    get_asset_studio_model_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VIDU_MODEL_ID = "vidu-timing2audio"
SOUND_EFFECT_DEFAULT_KEY = "asset_studio_audio_sound_effect"
REPLACEMENT_MODEL_ID = "seed-audio-1.0"

REMOVED_MODULES = (
    "adapters.vidu_platform.timing2audio",
    "app.services.audiobook.vidu_timing2audio_generator",
)

FRONTEND_TEXT_SCANNED = (
    "frontend/src/components/home/AssetStudioWorkbench.tsx",
    "frontend/src/i18n/resources/zh-CN/common.json",
    "frontend/src/i18n/resources/en-US/common.json",
    "backend/app/api/v1/asset_studio_api/routes_audio.py",
    "adapters/_shared.py",
)


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class TestSoundEffectCatalogPointsToMureka:
    def test_sound_effect_group_drops_vidu(self):
        assert VIDU_MODEL_ID not in _GROUP_MODEL_IDS["audio_sound_effect"]

    def test_sound_effect_group_is_seed_audio(self):
        """分组成员从 2026-10-10 起不再只有一个：`qwen-audio-3.1-tts-next` 作为第二条
        音效链路加入。本文件守的是 vidu 不许回来、seed-audio 仍是首选默认，
        不是“音效组永远只有一档”。"""
        assert REPLACEMENT_MODEL_ID in _GROUP_MODEL_IDS["audio_sound_effect"]
        assert _GROUP_MODEL_IDS["audio_sound_effect"][0] == REPLACEMENT_MODEL_ID

    def test_sound_effect_default_is_seed_audio(self):
        """默认值必须落在分组内，否则前端 applyModelOptionSync 会把选择重置回去。"""
        assert _DEFAULT_MODEL_IDS[SOUND_EFFECT_DEFAULT_KEY] == REPLACEMENT_MODEL_ID

    def test_manifest_exposes_seed_audio_for_sound_effect(self):
        manifest = get_asset_studio_model_manifest()
        options = manifest["groups"]["audio_sound_effect"]
        assert [option["model_id"] for option in options][0] == REPLACEMENT_MODEL_ID
        assert manifest["defaults"][SOUND_EFFECT_DEFAULT_KEY] == REPLACEMENT_MODEL_ID


class TestRemovedEverywhere:
    def test_models_yaml_has_no_vidu_audio_entry(self):
        data = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
        registered = {model["id"] for model in data["models"]}
        assert VIDU_MODEL_ID not in registered
        # Vidu 视频模型必须原样保留，删除范围仅限音效模型
        for model_id in (
            "vidu-q3-pro-img2video",
            "vidu-q3-pro-text2video",
            "vidu-q3-pro-start-end2video",
        ):
            assert model_id in registered, model_id

    def test_catalog_profiles_yaml_has_no_vidu_profile(self):
        data = yaml.safe_load(
            (REPO_ROOT / "config" / "model_catalog_profiles.yaml").read_text(encoding="utf-8")
        )
        assert VIDU_MODEL_ID not in data["profiles"]

    @pytest.mark.parametrize("module_name", REMOVED_MODULES)
    def test_removed_module_is_unimportable(self, module_name):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)

    def test_registry_no_longer_resolves_vidu(self):
        from adapters.registry import default_registry

        registry = default_registry()
        assert registry.get_spec(VIDU_MODEL_ID) is None
        assert registry.get_adapter(VIDU_MODEL_ID) is None

    def test_vidu_video_adapters_still_resolve(self):
        from adapters.registry import default_registry

        registry = default_registry()
        for model_id in (
            "vidu-q3-pro-img2video",
            "vidu-q3-pro-text2video",
            "vidu-q3-pro-start-end2video",
        ):
            assert registry.get_adapter(model_id) is not None, model_id

    @pytest.mark.parametrize("relative_path", FRONTEND_TEXT_SCANNED)
    def test_source_files_have_no_vidu_audio_reference(self, relative_path):
        text = _read_repo_text(relative_path)
        for token in ("vidu-timing2audio", "vidu_timing2audio", "ViduTiming2Audio", "timing2audio"):
            assert token not in text, f"{relative_path} 仍引用 {token}"


class TestSoundEffectRouteContract:
    def test_sound_effect_route_calls_seed_audio_adapter(self):
        """音效分支必须走注册表适配器，不能再出现 timing 分支或 Mureka 乐曲兜底。"""
        text = _read_repo_text("backend/app/api/v1/asset_studio_api/routes_audio.py")
        assert "timing_prompts" not in text
        assert "_validate_audio_duration(\"sound-effect\", duration)" in text
        assert "subdir=\"audio/sound-effects\"" in text
        sound_effect_section = text.split(
            "resolved_duration = _validate_audio_duration(\"sound-effect\", duration)", 1
        )[1].split("except Exception", 1)[0]
        assert "music_generator" not in sound_effect_section

    def test_sound_effect_route_remaps_unknown_model(self):
        """历史客户端仍可能上报 vidu-timing2audio，路由要静默收敛而不是 400。"""
        text = _read_repo_text("backend/app/api/v1/asset_studio_api/routes_audio.py")
        assert "if resolved_model_id not in SOUND_EFFECT_AUDIO_MODELS:" in text

    def test_seed_audio_adapter_resolves(self):
        from adapters.registry import default_registry

        assert default_registry().get_adapter(REPLACEMENT_MODEL_ID) is not None

    def test_sound_effect_constant_falls_back_to_seed_audio(self):
        """_constants 的兜底串要与目录一致，目录加载失败时也不会指回已删除模型。"""
        text = _read_repo_text("backend/app/api/v1/asset_studio_api/_constants.py")
        assert (
            'get_asset_studio_default_model_id("asset_studio_audio_sound_effect", "seed-audio-1.0")'
            in text
        )
        assert 'SOUND_EFFECT_AUDIO_MODELS = set(_MODEL_SETS["audio_sound_effect"])' in text


class TestI18nStaysSymmetric:
    HELPER_KEY = "seedAudioSoundEffect"

    def test_new_helper_key_exists_in_both_locales(self):
        for locale in ("zh-CN", "en-US"):
            text = _read_repo_text(f"frontend/src/i18n/resources/{locale}/common.json")
            assert f'"{self.HELPER_KEY}"' in text, locale

    def test_workbench_sound_effect_option_uses_seed_audio(self):
        text = _read_repo_text("frontend/src/components/home/AssetStudioWorkbench.tsx")
        assert "helper.seedAudioSoundEffect" in text
        assert "asset_studio_audio_sound_effect || 'seed-audio-1.0'" in text

    def test_locales_keep_identical_key_paths(self):
        def _key_paths(locale: str) -> set[str]:
            data = yaml.safe_load(
                _read_repo_text(f"frontend/src/i18n/resources/{locale}/common.json")
            )
            found: set[str] = set()

            def _walk(node: object, prefix: str) -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        path = f"{prefix}.{key}" if prefix else str(key)
                        found.add(path)
                        _walk(value, path)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item, prefix)

            _walk(data, "")
            return found

        zh, en = _key_paths("zh-CN"), _key_paths("en-US")
        assert zh - en == set(), f"仅 zh-CN 存在: {sorted(zh - en)[:10]}"
        assert en - zh == set(), f"仅 en-US 存在: {sorted(en - zh)[:10]}"
