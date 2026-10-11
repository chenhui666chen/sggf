"""wan3.0-video（all-in-one）适配器与配置契约回归。

单模型覆盖：文生视频、图生视频（first_frame/last_frame）、多参考一致性
（reference_image 最多 10 张）、视频编辑与视频延长（reference_video）、
文档/网页驱动（file / link 二选一）。

同时锁定三件容易被后续改动破坏的事实：

1. **``audio`` 这个名字已被占用**。core/unified_media_runtime.py 把 ``kwargs["audio"]`` 映射成
   ``requires_audio_input`` 能力需求，并在 ``_meets_capability_requirements`` 里做硬过滤；
   全项目只有 mimo-flash 声明 supports_audio_input，任何视频模型都不声明。所以 wan3.0 的
   「输出自带声音」在项目层必须叫 ``audio_output``，只在适配器内翻译成官方 ``parameters.audio``。
   若有人图省事直接传 ``audio=True``，本测试会红。
2. **引擎标识不是模型 ID**。DREAMWEAVER_I2V_ENGINE / DREAMWEAVER_T2V_ENGINE 决定提示词分支与
   是否走首帧桥接，all-in-one 模型名无法被 token 扫描出 i2v/t2v，必须归入 wan_auto 引擎。
3. **YAML 与运行时 spec 一致**。models.yaml 是唯一事实源，时长约束按官方区间 [2, 30] + 智能时长
   声明，catalog 下拉、后端校验、DreamWeaver 吸附都从它派生，不允许再收窄成自创档位表。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR, ROOT_DIR / "backend"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from adapters.dashscope import video_wan3  # noqa: E402
from adapters.registry import default_registry  # noqa: E402
from schemas.common import ModelStatus  # noqa: E402

MODELS_YAML = ROOT_DIR / "config" / "models.yaml"

MODEL_ID = "wan3.0-video"

# 官方 API 参考 wan3-video-generation-api-reference.md 的硬性上限
MAX_REFERENCE_IMAGES = 10
MAX_REFERENCE_VIDEOS = 5
MAX_REFERENCE_AUDIOS = 5
DURATION_MIN = 2
DURATION_MAX = 30


def _yaml_entry(model_id: str) -> dict:
    payload = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))
    models = payload["models"] if isinstance(payload, dict) else payload
    for entry in models:
        if entry.get("id") == model_id:
            return entry
    raise AssertionError(f"models.yaml 中找不到 {model_id}")


@pytest.fixture(scope="module")
def registry():
    return default_registry()


class TestRegistration:
    def test_model_is_active(self, registry):
        spec = registry.get_spec(MODEL_ID)
        assert spec is not None, "wan3.0-video 未注册进媒体链"
        assert spec.status is ModelStatus.ACTIVE
        assert registry.get_adapter(MODEL_ID).__class__.__name__ == "Wan30VideoAdapter"

    def test_covers_all_video_modalities(self, registry):
        modality = set(registry.get_spec(MODEL_ID).modality)
        assert {
            "text_to_video",
            "image_to_video",
            "video_to_video",
            "reference_to_video",
            "video_edit",
        } <= modality

    def test_unrelated_video_models_untouched(self, registry):
        """PixVerse 是独立供应商线，不能被万相侧改动波及。"""
        for model_id in ("pixverse-c1-r2v", "pixverse-v6-t2v"):
            spec = registry.get_spec(model_id)
            assert spec is not None
            assert spec.status is not ModelStatus.DEPRECATED

    def test_runtime_operation_allowlist(self):
        from core.unified_media_runtime import _OPERATION_MODEL_IDS

        assert MODEL_ID in _OPERATION_MODEL_IDS["generate_video"]


class TestYamlRuntimeAgreement:
    def test_status_matches(self, registry):
        assert _yaml_entry(MODEL_ID)["status"] == "active"
        assert registry.get_spec(MODEL_ID).status is ModelStatus.ACTIVE

    def test_duration_range_matches_upstream(self, registry):
        """constraints.duration 必须等于官方能力区间 [2, 30] + 智能时长，不是自创档位表。

        历史写法是 [3.0, 5.0, 10.0, 15.0] 档位列表，导致 asset_studio 下拉、
        _validate_video_duration、DreamWeaver 吸附三层都比上游窄，16~30 秒的请求全部被本地拒掉。
        官方（wan3-video-generation-api-reference.md）无视频输入时接受 [2, 30] 任意整数秒，
        -1 表示智能时长，与 adapters/dashscope/video_wan3.py 的 DURATION_MIN/MAX/SMART 同源。
        """
        spec = registry.get_spec(MODEL_ID)
        entry = _yaml_entry(MODEL_ID)["constraints"]["duration"]
        assert entry == {"min": 2.0, "max": 30.0, "default": 5.0, "supports_auto": True}
        assert spec.constraints.duration_min == 2.0
        assert spec.constraints.duration_max == 30.0
        assert spec.constraints.duration_supports_auto is True
        assert spec.constraints.has_duration_range
        assert spec.constraints.supports_duration(2.0)
        assert spec.constraints.supports_duration(30.0)
        assert spec.constraints.supports_duration(-1.0)
        assert not spec.constraints.supports_duration(31.0)
        assert not spec.constraints.supports_duration(1.0)

    def test_prompt_length_and_price_matches(self, registry):
        spec = registry.get_spec(MODEL_ID)
        entry = _yaml_entry(MODEL_ID)
        assert spec.constraints.max_prompt_length == entry["constraints"]["max_prompt_length"] == 20000
        # 默认档 720P，0.6 元/秒
        assert spec.cost_profile.price == entry["cost_profile"]["price"] == 0.6
        assert spec.cost_profile.unit == "per_second"

    def test_capabilities_declared(self, registry):
        spec = registry.get_spec(MODEL_ID)
        for capability in (
            "first_frame",
            "last_frame",
            "reference_images",
            "reference_videos",
            "reference_audios",
            "file_input",
            "link_input",
            "audio_output",
            "video_extend",
            "seed_control",
            "prompt_extend",
        ):
            assert spec.has_capability(capability), f"wan3.0-video 缺少能力声明 {capability}"


class TestMediaCollection:
    def test_frame_and_reference_are_mutually_exclusive(self):
        with pytest.raises(ValueError, match="互斥"):
            video_wan3._collect_media(
                {"first_frame": "http://example.com/a.png", "reference_images": ["http://example.com/b.png"]}
            )

    def test_image_path_becomes_first_frame(self):
        media = video_wan3._collect_media({"image_path": "http://example.com/a.png"})
        assert [item["type"] for item in media] == ["first_frame"]

    def test_video_path_becomes_reference_video(self):
        """视频编辑与视频延长共用 reference_video 素材类型。"""
        media = video_wan3._collect_media({"video_path": "http://example.com/a.mp4"})
        assert [item["type"] for item in media] == ["reference_video"]

    @pytest.mark.parametrize(
        "kwargs,expected_type",
        [
            ({"file_url": "http://example.com/a.pdf"}, "file"),
            ({"link_url": "http://example.com/a"}, "link"),
            ({"reference_audios": ["http://example.com/a.mp3"]}, "reference_audio"),
        ],
    )
    def test_new_capability_inputs(self, kwargs, expected_type):
        media = video_wan3._collect_media(kwargs)
        assert [item["type"] for item in media] == [expected_type]

    def test_file_and_link_are_mutually_exclusive(self):
        with pytest.raises(ValueError):
            video_wan3._collect_media(
                {"file_url": "http://example.com/a.pdf", "link_url": "http://example.com/b"}
            )

    @pytest.mark.parametrize(
        "key,count",
        [
            ("reference_images", MAX_REFERENCE_IMAGES + 1),
            ("reference_videos", MAX_REFERENCE_VIDEOS + 1),
            ("reference_audios", MAX_REFERENCE_AUDIOS + 1),
        ],
    )
    def test_reference_caps_enforced(self, key, count):
        with pytest.raises(ValueError):
            video_wan3._collect_media({key: [f"http://example.com/{index}.png" for index in range(count)]})

    def test_reference_caps_boundary_allowed(self):
        media = video_wan3._collect_media(
            {"reference_images": [f"http://example.com/{index}.png" for index in range(MAX_REFERENCE_IMAGES)]}
        )
        assert len(media) == MAX_REFERENCE_IMAGES


class TestParameters:
    def test_defaults_are_cost_neutral_and_silent(self):
        params = video_wan3._build_parameters(video_wan3._collect_media({}), {})
        assert params["resolution"] == "720P"
        assert params["ratio"] == "adaptive"
        assert params["duration"] == 5
        assert params["audio"] is False
        assert params["prompt_extend"] is True
        assert params["watermark"] is False

    def test_audio_output_maps_to_official_audio_flag(self):
        params = video_wan3._build_parameters(video_wan3._collect_media({}), {"audio_output": True})
        assert params["audio"] is True

    def test_audio_kwarg_is_not_read_as_output_flag(self):
        """``audio`` 在项目层是「音频输入」能力需求，绝不能被当成输出开关。"""
        params = video_wan3._build_parameters(video_wan3._collect_media({}), {"audio": True})
        assert params["audio"] is False

    def test_aspect_ratio_alias_translated(self):
        params = video_wan3._build_parameters(video_wan3._collect_media({}), {"aspect_ratio": "16:9"})
        assert params["ratio"] == "16:9"

    @pytest.mark.parametrize("duration", [DURATION_MIN, 5, DURATION_MAX, -1])
    def test_duration_accepted(self, duration):
        params = video_wan3._build_parameters(video_wan3._collect_media({}), {"duration": duration})
        assert params["duration"] == duration

    @pytest.mark.parametrize("duration", [DURATION_MIN - 1, DURATION_MAX + 1, "abc"])
    def test_duration_rejected(self, duration):
        with pytest.raises(ValueError):
            video_wan3._build_parameters(video_wan3._collect_media({}), {"duration": duration})

    def test_resolution_validated(self):
        with pytest.raises(ValueError):
            video_wan3._build_parameters(video_wan3._collect_media({}), {"resolution": "2160P"})

    def test_document_input_forces_prompt_extend(self):
        """官方硬性要求：传入 file/link 时 prompt_extend 必须为 true。"""
        for kwargs in ({"file_url": "http://example.com/a.pdf"}, {"link_url": "http://example.com/a"}):
            params = video_wan3._build_parameters(
                video_wan3._collect_media(kwargs), {"prompt_extend": False}
            )
            assert params["prompt_extend"] is True

    def test_video_extend_requires_reference_video(self):
        with pytest.raises(ValueError, match="reference_video"):
            video_wan3._build_parameters(video_wan3._collect_media({}), {"video_extend": True})

    def test_video_extend_forces_adaptive_ratio(self):
        media = video_wan3._collect_media({"reference_videos": ["http://example.com/a.mp4"]})
        params = video_wan3._build_parameters(media, {"video_extend": True, "ratio": "16:9"})
        assert params["ratio"] == "adaptive"

    def test_seed_validated(self):
        media = video_wan3._collect_media({})
        assert video_wan3._build_parameters(media, {"seed": 42})["seed"] == 42
        with pytest.raises(ValueError):
            video_wan3._build_parameters(media, {"seed": 2147483648})


class TestAudioPolicy:
    """wan3.0 的 audio 开关必须与 DreamWeaver 既有音效策略一致，否则会白花钱或丢声音。"""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv("DREAMWEAVER_SFX_SOURCE", raising=False)
        monkeypatch.delenv("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", raising=False)

    def test_default_is_silent(self, monkeypatch):
        from pipeline.media_presets import resolve_dreamweaver_video_audio_output

        assert resolve_dreamweaver_video_audio_output() is False

    @pytest.mark.parametrize("source", ["library", "none", "", "Library"])
    def test_library_and_none_stay_silent(self, monkeypatch, source):
        from pipeline.media_presets import resolve_dreamweaver_video_audio_output

        monkeypatch.setenv("DREAMWEAVER_SFX_SOURCE", source)
        assert resolve_dreamweaver_video_audio_output() is False

    @pytest.mark.parametrize("source", ["model", "video"])
    def test_model_sfx_turns_audio_on(self, monkeypatch, source):
        """SFX_SOURCE=model/video 表示音效直接取自模型输出，此时必须让模型出声。"""
        from pipeline.media_presets import resolve_dreamweaver_video_audio_output

        monkeypatch.setenv("DREAMWEAVER_SFX_SOURCE", source)
        assert resolve_dreamweaver_video_audio_output() is True

    @pytest.mark.parametrize("source", ["model", "video"])
    def test_dialogue_embed_overrides_to_silent(self, monkeypatch, source):
        """合成对白轨时 AudioSyncManager 会整轨替换音频，模型出声只会被丢弃。"""
        from pipeline.media_presets import resolve_dreamweaver_video_audio_output

        monkeypatch.setenv("DREAMWEAVER_SFX_SOURCE", source)
        monkeypatch.setenv("DREAMWEAVER_DIALOGUE_AUDIO_EMBED", "true")
        assert resolve_dreamweaver_video_audio_output() is False


class TestProjectDefaults:
    def test_dreamweaver_model_constant(self):
        from pipeline.media_presets import DREAMWEAVER_WAN_MODEL_ID

        assert DREAMWEAVER_WAN_MODEL_ID == MODEL_ID

    def test_all_in_one_routes_to_auto_engine(self):
        """all-in-one 名字扫不出 i2v/t2v，必须归入 wan_auto（AUTO 已在 selector 支持列表内）。"""
        from pipeline.media_presets import (
            DREAMWEAVER_AUTO_ENGINE,
            infer_dreamweaver_video_engine_from_model_id,
        )

        assert infer_dreamweaver_video_engine_from_model_id(MODEL_ID) == DREAMWEAVER_AUTO_ENGINE

    def test_engine_constants_are_modes_not_model_ids(self):
        """引擎标识若被改成模型 ID，i2v/t2v 两个判定会同时为真，提示词分支就废了。"""
        from pipeline.media_presets import (
            DREAMWEAVER_I2V_ENGINE,
            DREAMWEAVER_T2V_ENGINE,
            is_dreamweaver_i2v_engine,
            is_dreamweaver_t2v_engine,
        )

        assert DREAMWEAVER_I2V_ENGINE != DREAMWEAVER_T2V_ENGINE
        assert MODEL_ID not in {DREAMWEAVER_I2V_ENGINE, DREAMWEAVER_T2V_ENGINE}
        assert is_dreamweaver_i2v_engine(DREAMWEAVER_I2V_ENGINE)
        assert not is_dreamweaver_t2v_engine(DREAMWEAVER_I2V_ENGINE)

    @pytest.mark.parametrize(
        "catalog_key",
        [
            "asset_studio_video_generation",
            "asset_studio_video_edit",
            "asset_studio_motion",
            "dreamweaver_video",
            "dreamweaver_video_edit",
        ],
    )
    def test_asset_studio_defaults(self, catalog_key):
        from app.services.asset_studio_model_catalog import _DEFAULT_MODEL_IDS

        assert _DEFAULT_MODEL_IDS[catalog_key] == MODEL_ID

    def test_video_edit_fallback_uses_current_model(self):
        source = (ROOT_DIR / "pipeline" / "autoqc_pkg" / "_video_edit.py").read_text(encoding="utf-8")
        assert f'or "{MODEL_ID}"' in source
