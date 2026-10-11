# -*- coding: utf-8 -*-
"""Seedance 2.5 接入与 2.0 系列契约校正守卫。

2026-10-08 依据火山方舟官方文档（Doubao Seedance 2.5 教程 / 创建视频生成任务 API）
并用真实 API 的同步校验报错核对过边界：

- duration：2.5 接受 4~30 的整数秒或 -1（智能时长）；请求 3 秒与 31 秒均被同步拒绝。
  2.0 / 2.0-fast 上限是 15 秒（请求 16 秒被拒），原 config 写着 30 秒属错误。
- resolution：2.5 只有 480p / 720p / 1080p，请求 4k 报「not supported for this account and model」；
  4k 属于 2.0 系列（实测可提交）。2.0-fast 只到 720p。
- ratio：枚举 21:9 / 16:9 / 4:3 / 1:1 / 3:4 / 9:16 / adaptive，请求 5:4 被拒；
  首帧、首尾帧、编辑、延长四类任务 ratio 必须为 adaptive。
- 编辑任务硬约束仅属于 2.5：duration 必须为 -1，参考视频时长 4~30 秒。
  2.0 系列教程的编辑样例传整数 duration（5），全文无 -1/智能时长，输出时长仍是 4~15 秒。
- draft / draft_task / output_format=mov / omni_reference_task_type 均为 2.5 独有能力；
  2.0 传 draft 报「must be empty」，fast 传 mov 被拒；
  omni_reference_task_type 只在有 reference_* 素材时可用，文生视频场景传入会同步报错。
- 样片 Step2 只接受 model / draft_task / resolution=1080p，其余参数由上游自动复用。

2026-10-09 依据 Doubao Seedance 2.0 系列教程（browser 抓正文）补齐：
- 2.0 / 2.0-fast / 2.0-mini 的能力矩阵里「编辑视频【New】」「延长视频【New】」均为 ✓，
  所以 2.0 系列可以进视频编辑白名单；官方编辑样例仅靠 content 的 role=reference_video
  加提示词里的编辑动词表达任务意图。
- 该教程全文没有出现 omni_reference_task_type（2.5 教程与创建任务 API 参考才有），
  因此给 2.0 系列发这个参数属于未证实的能力面扩大，必须由 profile 门控拦住。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT, REPO_ROOT / "backend"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

MODEL_ID_25 = "doubao-seedance-2-5"
MODEL_ID_20 = "doubao-seedance-2-0"
MODEL_ID_20_FAST = "doubao-seedance-2-0-fast"
UPSTREAM_ID_25 = "doubao-seedance-2-5-260628"


def _models() -> list[dict]:
    data = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    return data["models"] if isinstance(data, dict) and "models" in data else data


def _model(model_id: str) -> dict:
    for record in _models():
        if record.get("id") == model_id:
            return record
    raise AssertionError(f"config/models.yaml 缺少模型 {model_id}")


def _profile(model_id: str):
    from adapters.volcengine.video import PROFILES

    return PROFILES[model_id]


def _build(model_id: str, prompt: str = "一只猫在草地上奔跑", **kwargs):
    from adapters.volcengine.video import _build_payload

    return _build_payload(_profile(model_id), prompt, kwargs)


class TestSeedance25IsRegisteredAndConfigured:
    def test_registry_resolves_adapter(self):
        from adapters.registry import default_registry
        from adapters.volcengine.video import DoubaoSeedance25Adapter

        adapter = default_registry().get_adapter(MODEL_ID_25)
        assert isinstance(adapter, DoubaoSeedance25Adapter)

    def test_yaml_maps_internal_id_to_upstream_snapshot(self):
        record = _model(MODEL_ID_25)
        assert record["api_config"]["request_format"]["model"] == UPSTREAM_ID_25
        assert record["status"] == "active"

    def test_yaml_duration_tiers_stay_inside_supported_range(self):
        durations = _model(MODEL_ID_25)["constraints"]["duration"]
        assert all(4 <= value <= 30 for value in durations)
        assert max(durations) == 30

    def test_yaml_has_no_4k_for_2_5(self):
        assert "4k" not in _model(MODEL_ID_25)["constraints"]["resolutions"]

    def test_yaml_reference_caps(self):
        constraints = _model(MODEL_ID_25)["constraints"]
        assert constraints["max_reference_total"] == 50
        assert constraints["max_reference_images"] == 30
        assert constraints["max_reference_videos"] == 10
        assert constraints["max_reference_audios"] == 10

    def test_yaml_ratio_list_matches_upstream(self):
        ratios = set(_model(MODEL_ID_25)["constraints"]["ratios"])
        assert ratios == {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}

    def test_pricing_tiers_use_token_unit(self):
        pricing = _model(MODEL_ID_25)["pricing_info"]
        assert pricing["unit"] == "每百万 token"
        assert {tier["price_per_million_tokens"] for tier in pricing["tiers"]} == {70.0, 42.0, 77.0, 46.0}


class TestSeedance20ContractCorrections:
    def test_2_0_duration_no_longer_claims_30s(self):
        durations = _model(MODEL_ID_20)["constraints"]["duration"]
        assert max(durations) == 15
        assert 30 not in durations

    def test_2_0_keeps_4k(self):
        assert "4k" in _model(MODEL_ID_20)["constraints"]["resolutions"]

    def test_2_0_fast_caps_at_720p(self):
        assert _model(MODEL_ID_20_FAST)["constraints"]["resolutions"] == ["480p", "720p"]

    def test_adapter_rejects_out_of_range_2_0_requests(self):
        with pytest.raises(ValueError, match=r"\[4, 15\]"):
            _build(MODEL_ID_20, duration=16)
        with pytest.raises(ValueError, match="不支持样片"):
            _build(MODEL_ID_20, draft=True)
        with pytest.raises(ValueError, match="output_format"):
            _build(MODEL_ID_20_FAST, output_format="mov")
        with pytest.raises(ValueError, match="resolution"):
            _build(MODEL_ID_20_FAST, resolution="1080p")

    def test_2_0_accepts_4k(self):
        assert _build(MODEL_ID_20, resolution="4k", duration=10)["resolution"] == "4k"


class TestPayloadBuilderHonorsTaskTypeConstraints:
    def test_text_to_video_defaults(self):
        payload = _build(MODEL_ID_25)
        assert payload["model"] == UPSTREAM_ID_25
        assert payload["resolution"] == "720p"
        assert payload["ratio"] == "16:9"
        assert payload["duration"] == 5
        assert payload["output_format"] == "mp4"
        assert payload["watermark"] is False
        assert "omni_reference_task_type" not in payload
        assert payload["content"][0] == {"type": "text", "text": "一只猫在草地上奔跑"}

    def test_smart_duration_passthrough(self):
        assert _build(MODEL_ID_25, duration=-1)["duration"] == -1

    def test_resolution_is_case_insensitive(self):
        assert _build(MODEL_ID_25, resolution="1080P")["resolution"] == "1080p"

    def test_first_frame_forces_adaptive_ratio(self):
        payload = _build(MODEL_ID_25, ratio="16:9", first_frame="https://example.com/a.png")
        assert payload["ratio"] == "adaptive"
        assert payload["content"][1]["role"] == "first_frame"

    def test_edit_forces_adaptive_and_smart_duration(self):
        payload = _build(
            MODEL_ID_25,
            "把 @video1 的人物替换成 @image1",
            ratio="16:9",
            duration=10,
            video_edit=True,
            reference_videos=["https://example.com/a.mp4"],
            reference_images=["https://example.com/a.png"],
        )
        assert payload["ratio"] == "adaptive"
        assert payload["duration"] == -1
        assert payload["omni_reference_task_type"] == "edit"

    def test_extend_forces_adaptive_ratio(self):
        payload = _build(
            MODEL_ID_25,
            "向后延长 @video1",
            ratio="16:9",
            video_extend=True,
            reference_videos=["https://example.com/a.mp4"],
        )
        assert payload["ratio"] == "adaptive"
        assert payload["omni_reference_task_type"] == "extend"

    def test_edit_and_extend_require_reference_video(self):
        with pytest.raises(ValueError, match="必须传入 reference_video"):
            _build(MODEL_ID_25, video_edit=True)
        with pytest.raises(ValueError, match="必须传入 reference_video"):
            _build(MODEL_ID_25, video_extend=True)

    def test_omni_task_type_rejected_without_reference_media(self):
        with pytest.raises(ValueError, match="仅在全模态参考场景"):
            _build(MODEL_ID_25, omni_reference_task_type="auto")
        with pytest.raises(ValueError, match="仅在全模态参考场景"):
            _build(MODEL_ID_25, first_frame="https://example.com/a.png", omni_reference_task_type="edit")

    def test_unknown_omni_task_type_rejected(self):
        with pytest.raises(ValueError, match="omni_reference_task_type"):
            _build(MODEL_ID_25, reference_videos=["https://example.com/a.mp4"], omni_reference_task_type="cut")

    def test_invalid_ratio_and_duration_rejected(self):
        with pytest.raises(ValueError, match="ratio"):
            _build(MODEL_ID_25, ratio="5:4")
        with pytest.raises(ValueError, match=r"\[4, 30\]"):
            _build(MODEL_ID_25, duration=31)
        with pytest.raises(ValueError, match=r"\[4, 30\]"):
            _build(MODEL_ID_25, duration=3)
        with pytest.raises(ValueError, match="resolution"):
            _build(MODEL_ID_25, resolution="4k")

    def test_invalid_ratio_still_rejected_when_task_type_forces_adaptive(self):
        """ratio 原值校验必须在强制改写之前，否则 has_frame/edit 会把非法值静默吞掉。"""
        with pytest.raises(ValueError, match="ratio"):
            _build(MODEL_ID_25, ratio="5:4", first_frame="https://example.com/a.png")
        with pytest.raises(ValueError, match="ratio"):
            _build(
                MODEL_ID_25,
                "延长 @video1",
                ratio="5:4",
                video_extend=True,
                reference_videos=["https://example.com/a.mp4"],
            )

    def test_reference_counts_are_capped(self):
        images = [f"https://example.com/image_{index}.png" for index in range(31)]
        videos = [f"https://example.com/video_{index}.mp4" for index in range(11)]
        audios = [f"https://example.com/audio_{index}.mp3" for index in range(11)]
        with pytest.raises(ValueError, match="reference_image"):
            _build(MODEL_ID_25, reference_images=images)
        with pytest.raises(ValueError, match="reference_video"):
            _build(MODEL_ID_25, reference_videos=videos)
        with pytest.raises(ValueError, match="reference_audio"):
            _build(MODEL_ID_25, reference_audios=audios)

    def test_first_frame_and_last_frame_capped_at_one(self):
        with pytest.raises(ValueError, match="first_frame"):
            _build(MODEL_ID_25, first_frame=["https://example.com/a.png", "https://example.com/b.png"])
        with pytest.raises(ValueError, match="last_frame"):
            _build(MODEL_ID_25, last_frame=["https://example.com/a.png", "https://example.com/b.png"])
        payload = _build(
            MODEL_ID_25,
            first_frame="https://example.com/a.png",
            last_frame="https://example.com/b.png",
        )
        assert [item["role"] for item in payload["content"][1:]] == ["first_frame", "last_frame"]

    def test_total_reference_cap_on_2_0(self):
        # 2.0 系列官方只公布总数上限，因此这里用超总数的参考视频验证拦截生效
        with pytest.raises(ValueError, match="参考素材总数"):
            _build(
                MODEL_ID_20,
                reference_videos=[f"https://example.com/video_{index}.mp4" for index in range(16)],
            )

    def test_prompt_and_media_at_least_one(self):
        with pytest.raises(ValueError, match="至少提供一个"):
            _build(MODEL_ID_25, "")


class TestEditSmartDurationBelongsTo25Only:
    """-1 是 2.5 的编辑契约；2.0 系列编辑仍按各自 4~15 整数区间校验。"""

    REF_VIDEO = ["https://example.com/a.mp4"]

    def test_2_0_edit_keeps_validated_integer_duration(self):
        payload = _build(
            MODEL_ID_20,
            "把 @video1 的人物替换成 @image1",
            duration=8,
            video_edit=True,
            reference_videos=self.REF_VIDEO,
        )
        assert payload["duration"] == 8
        assert payload["ratio"] == "adaptive"

    def test_2_0_edit_falls_back_to_default_not_smart(self):
        payload = _build(MODEL_ID_20, "替换 @video1 的背景", video_edit=True, reference_videos=self.REF_VIDEO)
        assert payload["duration"] == 5

    def test_2_0_fast_edit_keeps_validated_integer_duration(self):
        payload = _build(
            MODEL_ID_20_FAST,
            "把 @video1 的人物替换成 @image1",
            duration=6,
            video_edit=True,
            reference_videos=self.REF_VIDEO,
        )
        assert payload["duration"] == 6

    def test_2_0_edit_rejects_out_of_range_duration(self):
        with pytest.raises(ValueError, match=r"\[4, 15\]"):
            _build(MODEL_ID_20, "编辑 @video1", duration=16, video_edit=True, reference_videos=self.REF_VIDEO)

    def test_2_0_edit_rejects_smart_duration(self):
        with pytest.raises(ValueError, match="不支持智能时长"):
            _build(MODEL_ID_20, "编辑 @video1", duration=-1, video_edit=True, reference_videos=self.REF_VIDEO)

    def test_2_0_edit_still_requires_reference_video(self):
        with pytest.raises(ValueError, match="必须传入 reference_video"):
            _build(MODEL_ID_20, "编辑", video_edit=True)


class TestOmniTaskTypeHintBelongsTo25Only:
    """omni_reference_task_type 是 2.5 独有的「任务类型引导」参数。

    2.0 系列教程全文未出现该字段，官方编辑样例只靠 content 的 role=reference_video
    与提示词推断任务类型；把该参数一并发给 2.0 属于未证实的能力面扩大，
    上游一旦按 2.5 语义校验会同步报错，因此门控必须落在 profile 上。
    """

    REF_VIDEO = ["https://example.com/a.mp4"]

    def test_2_0_edit_payload_omits_omni_task_type(self):
        payload = _build(
            MODEL_ID_20,
            "将 @video1 礼盒中的香水替换成 @image1 中的面霜",
            video_edit=True,
            reference_videos=self.REF_VIDEO,
            duration=6,
        )
        assert "omni_reference_task_type" not in payload
        assert payload["duration"] == 6
        assert [item.get("role") for item in payload["content"] if item["type"] != "text"] == ["reference_video"]

    def test_2_0_fast_edit_payload_omits_omni_task_type(self):
        payload = _build(
            MODEL_ID_20_FAST,
            "将 @video1 礼盒中的香水替换成 @image1 中的面霜",
            video_edit=True,
            reference_videos=self.REF_VIDEO,
        )
        assert "omni_reference_task_type" not in payload

    def test_2_0_extend_payload_omits_omni_task_type(self):
        payload = _build(
            MODEL_ID_20,
            "向后延长 @video1",
            video_extend=True,
            reference_videos=self.REF_VIDEO,
        )
        assert "omni_reference_task_type" not in payload

    def test_2_0_rejects_explicit_omni_task_type(self):
        with pytest.raises(ValueError, match="2.5 独有"):
            _build(MODEL_ID_20, reference_videos=self.REF_VIDEO, omni_reference_task_type="reference")

    def test_2_5_still_emits_the_hint(self):
        """反向断言：门控写反会让 2.5 也丢掉引导，编辑/延长退化为异步报错。"""
        edit = _build(MODEL_ID_25, video_edit=True, reference_videos=self.REF_VIDEO)
        extend = _build(MODEL_ID_25, video_extend=True, reference_videos=self.REF_VIDEO)
        assert edit["omni_reference_task_type"] == "edit"
        assert extend["omni_reference_task_type"] == "extend"


class TestSeedance20EditExposedThroughAllLayers:
    """档案声明、执行层白名单、展示层分组三层必须同时放行，缺一层即「选得到却不通」。"""

    @pytest.mark.parametrize("model_id", [MODEL_ID_20, MODEL_ID_20_FAST])
    def test_adapter_spec_declares_video_edit(self, model_id):
        from adapters.registry import registry as default_registry

        spec = default_registry.get_spec(model_id)
        assert spec is not None, model_id
        assert "video_edit" in (spec.modality or []), f"{model_id} 档案未声明 video_edit"

    @pytest.mark.parametrize("model_id", [MODEL_ID_20, MODEL_ID_20_FAST])
    def test_runtime_allowlist(self, model_id):
        from core.unified_media_runtime import _OPERATION_MODEL_IDS

        assert model_id in _OPERATION_MODEL_IDS["edit_video"]

    @pytest.mark.parametrize("model_id", [MODEL_ID_20, MODEL_ID_20_FAST])
    def test_catalog_groups(self, model_id):
        from app.services.asset_studio_model_catalog import _GROUP_MODEL_IDS

        for group in ("video_edit", "dreamweaver_video_edit"):
            assert model_id in _GROUP_MODEL_IDS[group], group

    @pytest.mark.parametrize("model_id", [MODEL_ID_20, MODEL_ID_20_FAST])
    def test_yaml_capability_marked_verified(self, model_id):
        """2.0 系列的 video_editing 此前是 TODO 占位，与「只能生成」的展示层注释互相矛盾。"""
        record = _model(model_id)
        entry = next(
            (item for item in record["capabilities"] if item.get("name") == "video_editing"),
            None,
        )
        assert entry is not None, f"{model_id} 档案缺少 video_editing 能力"
        assert entry["support_level"] == "native"
        assert entry["confidence"] == "high"
        assert "TODO" not in str(entry["source"])

    def test_2_0_edit_stays_out_of_smart_duration_business(self):
        """编辑档位扩展不得顺带把 -1 带进 2.0：区间校验仍是 4~15 整数。"""
        profile = _profile(MODEL_ID_20)
        assert profile.edit_forces_smart_duration is False
        assert (profile.duration_min, profile.duration_max) == (4, 15)


class TestDraftTwoStepFlow:
    def test_step1_marks_draft(self):
        payload = _build(MODEL_ID_25, draft=True, resolution="480p", duration=4, ratio="adaptive")
        assert payload["draft"] is True
        assert payload["resolution"] == "480p"

    def test_step1_omits_draft_when_false(self):
        assert "draft" not in _build(MODEL_ID_25, draft=False)

    def test_step2_payload_only_carries_three_fields(self):
        payload = _build(
            MODEL_ID_25,
            "这段提示词在 Step2 不应出现",
            draft_task="cgt-20261008153554-cao75",
            duration=10,
            ratio="16:9",
        )
        assert payload == {
            "model": UPSTREAM_ID_25,
            "draft_task": "cgt-20261008153554-cao75",
            "resolution": "1080p",
        }

    def test_step2_rejects_non_1080p(self):
        with pytest.raises(ValueError, match="仅支持 1080p"):
            _build(MODEL_ID_25, "", draft_task="cgt-x", resolution="720p")


class TestSeedance25ExposedThroughCatalog:
    def test_asset_studio_groups(self):
        from app.services.asset_studio_model_catalog import _GROUP_MODEL_IDS

        for group in ("video_generation", "video_edit", "motion", "dreamweaver_video", "dreamweaver_video_edit"):
            assert MODEL_ID_25 in _GROUP_MODEL_IDS[group], group

    def test_manifest_duration_options(self):
        from app.services.asset_studio_model_catalog import get_asset_studio_video_duration_options

        options = get_asset_studio_video_duration_options()
        assert options[MODEL_ID_25] == (4.0, 5.0, 10.0, 15.0, 20.0, 30.0)
        assert options[MODEL_ID_20] == (4.0, 5.0, 10.0, 15.0)

    def test_runtime_allows_generation(self):
        from core.unified_media_runtime import _OPERATION_MODEL_IDS

        assert MODEL_ID_25 in _OPERATION_MODEL_IDS["generate_video"]

    def test_catalog_profile_present(self):
        data = yaml.safe_load(
            (REPO_ROOT / "config" / "model_catalog_profiles.yaml").read_text(encoding="utf-8")
        )
        profile = data["profiles"][MODEL_ID_25]
        assert profile["role_summary"]
        assert profile["prompt_patterns"]
        assert profile["router_rules"]
        assert profile["best_practice_tips"]
        assert profile["project_entrypoints"]
