# -*- coding: utf-8 -*-
"""constraints.duration 的两种写法（档位列表 / {min,max,default} 区间）必须都能参与路由。

背景：config/models.yaml 里绝大多数模型把 duration 写成档位列表（如 [3.0, 5.0, 10.0]），
但 vidu-q3-pro-img2video、vidu-q3-pro-text2video、vidu-q3-pro-start-end2video、
kling/kling-v3-video-generation、kling/kling-v3-omni-video-generation 这 5 个写成了
{min: 5.0, max: 10.0, default: 5.0}。ConstraintSpec 原先只在文档里声明 duration 是
List[float]，没有做任何归一化，于是 supports_duration() 会对 dict 的键做
abs('min' - 5.0) 而抛 TypeError。

危害面比看起来大：core/router.py:311 取的是 get_all_specs()，不按 modality 收窄，
ModelSpec.can_handle() 又会无条件调 supports_duration()，所以**任何**带 duration 的
路由请求都会崩，哪怕它自己是文生图任务、跟这 5 个视频模型毫无关系。

本文件锁定两件事：
1. dict 形态被归一化成正式区间语义（min/max 参与判定，default 作为代表档位保留）；
2. 注册表里每一个 spec 都能安全回答 supports_duration，路由不再被单个脏条目拖垮。
"""

from __future__ import annotations

import pytest

from core.router import CapabilityFilter
from schemas.common import Modality
from schemas.model_spec import ConstraintSpec, ModelSpec
from schemas.task_spec import TaskSpec

DICT_DURATION = {"min": 5.0, "max": 10.0, "default": 5.0}


def _spec_with_duration(duration) -> ConstraintSpec:
    return ConstraintSpec(duration=duration)


class TestDictDurationNormalization:
    def test_accepts_value_inside_range(self) -> None:
        constraints = _spec_with_duration(DICT_DURATION)
        assert constraints.supports_duration(5.0)
        assert constraints.supports_duration(8.0)
        assert constraints.supports_duration(10.0)

    def test_rejects_value_outside_range(self) -> None:
        constraints = _spec_with_duration(DICT_DURATION)
        assert not constraints.supports_duration(4.0)
        assert not constraints.supports_duration(20.0)

    def test_nearest_duration_clamps_to_range(self) -> None:
        constraints = _spec_with_duration(DICT_DURATION)
        assert constraints.get_nearest_duration(20.0) == 10.0
        assert constraints.get_nearest_duration(1.0) == 5.0
        assert constraints.get_nearest_duration(8.0) == 8.0

    def test_range_is_exposed_as_typed_fields(self) -> None:
        constraints = _spec_with_duration(DICT_DURATION)
        assert constraints.duration_min == 5.0
        assert constraints.duration_max == 10.0
        # default 档位保留在 duration 里，供只认列表的旧调用方退化使用
        assert constraints.duration == [5.0]

    def test_to_dict_round_trips_range(self) -> None:
        payload = _spec_with_duration(DICT_DURATION).to_dict()
        assert payload["duration_min"] == 5.0
        assert payload["duration_max"] == 10.0
        assert ConstraintSpec(**{k: payload[k] for k in ("duration", "duration_min", "duration_max")}).supports_duration(7.0)

    def test_integer_dict_values_are_coerced(self) -> None:
        constraints = _spec_with_duration({"min": 5, "max": 10, "default": 5})
        assert constraints.duration_min == 5.0
        assert constraints.supports_duration(7)


class TestListDurationUnchanged:
    def test_tier_list_still_matches_exact_tiers_only(self) -> None:
        constraints = _spec_with_duration([3.0, 5.0, 10.0, 15.0])
        assert constraints.supports_duration(5.0)
        assert not constraints.supports_duration(4.0)
        assert constraints.duration_min is None
        assert constraints.duration_max is None

    def test_tier_list_nearest_picks_closest_tier(self) -> None:
        constraints = _spec_with_duration([3.0, 5.0, 10.0, 15.0])
        assert constraints.get_nearest_duration(4.0) == 3.0
        assert constraints.get_nearest_duration(31.0) == 15.0

    def test_empty_list_accepts_anything(self) -> None:
        constraints = _spec_with_duration([])
        assert constraints.supports_duration(123.0)
        assert constraints.get_nearest_duration(123.0) == 123.0


class TestSmartDurationFlag:
    """supports_auto 是上游能力（-1 智能时长），必须与区间一起归一化并透出。"""

    AUTO_DURATION = {"min": 2.0, "max": 30.0, "default": 5.0, "supports_auto": True}

    def test_auto_duration_accepted_when_declared(self) -> None:
        constraints = _spec_with_duration(self.AUTO_DURATION)
        assert constraints.duration_supports_auto is True
        assert constraints.supports_duration(-1.0)
        assert constraints.get_nearest_duration(-1.0) == -1.0

    def test_range_bounds_still_enforced_alongside_auto(self) -> None:
        constraints = _spec_with_duration(self.AUTO_DURATION)
        assert constraints.supports_duration(2.0)
        assert constraints.supports_duration(30.0)
        assert not constraints.supports_duration(31.0)
        assert not constraints.supports_duration(1.0)

    def test_auto_is_off_when_not_declared(self) -> None:
        plain = _spec_with_duration(DICT_DURATION)
        assert plain.duration_supports_auto is False
        assert not plain.supports_duration(-1.0)
        assert not _spec_with_duration([3.0, 5.0]).supports_duration(-1.0)

    def test_to_dict_round_trips_auto_flag(self) -> None:
        payload = _spec_with_duration(self.AUTO_DURATION).to_dict()
        assert payload["duration_supports_auto"] is True
        restored = ConstraintSpec(
            **{k: payload[k] for k in ("duration", "duration_min", "duration_max", "duration_supports_auto")}
        )
        assert restored.supports_duration(-1.0)
        assert restored.supports_duration(12.0)


class TestModelSpecFromDict:
    def test_from_dict_normalizes_dict_duration(self) -> None:
        spec = ModelSpec.from_dict(
            {
                "id": "probe-model",
                "name": "probe",
                "provider": "probe",
                "modality": ["text_to_video"],
                "constraints": {"duration": DICT_DURATION},
            }
        )
        assert spec.constraints.duration_min == 5.0
        assert spec.constraints.duration_max == 10.0
        assert spec.constraints.supports_duration(8.0)

    def test_can_handle_does_not_raise_for_dict_duration(self) -> None:
        spec = ModelSpec.from_dict(
            {
                "id": "probe-model",
                "name": "probe",
                "provider": "probe",
                "modality": ["text_to_video"],
                "constraints": {"duration": DICT_DURATION},
            }
        )
        task = TaskSpec(task_id="t1", modality=Modality.TEXT_TO_VIDEO, prompt="p", duration=8.0)
        can_handle, reasons = spec.can_handle(task)
        assert isinstance(can_handle, bool)
        assert isinstance(reasons, list)


class TestRuntimeRangeModelStaysRoutable:
    """区间模型在运行时候选池里必须按区间放行，而不是只放行 default 档。

    ConstraintSpec.__post_init__ 把 {min,max,default} 归一化成 duration=[default] +
    duration_min/max，而 _is_task_compatible 曾把归一化后的 duration 再解析一次，于是
    区间模型被当成「只接受默认档」，20 秒这类合法请求在候选池就被误过滤。
    """

    PROBE_ID = "probe-range-video"

    def _probe_spec(self):
        return ModelSpec.from_dict(
            {
                "id": self.PROBE_ID,
                "name": "probe",
                "provider": "probe",
                "modality": ["text_to_video"],
                "constraints": {
                    "duration": {"min": 2.0, "max": 30.0, "default": 5.0, "supports_auto": True}
                },
            }
        )

    def _task(self, duration: float) -> TaskSpec:
        return TaskSpec(
            task_id="probe-task",
            modality=Modality.TEXT_TO_VIDEO,
            prompt="p",
            duration=duration,
        )

    def _runtime(self, monkeypatch):
        from types import SimpleNamespace

        import core.unified_media_runtime as runtime_module
        from core.unified_media_runtime import UnifiedMediaRuntime

        spec = self._probe_spec()

        class _NeutralIndex:
            @staticmethod
            def get_signal(_model_id: str):
                return SimpleNamespace(blocked=False, priority=0, reason="")

            @staticmethod
            def get_capability_hints(_model_id: str) -> dict:
                return {}

            @staticmethod
            def get_task_constraints(_model_id: str) -> dict:
                return {}

        class _ProbeRegistry:
            def get_all_specs(self):
                return [spec]

            def get_spec(self, model_id: str):
                return spec if model_id == spec.id else None

            def has_adapter(self, model_id: str) -> bool:
                return model_id == spec.id

        monkeypatch.setattr(runtime_module, "get_model_catalog_runtime_index", _NeutralIndex)
        monkeypatch.setitem(runtime_module._OPERATION_MODEL_IDS, "generate_video", {spec.id})
        return UnifiedMediaRuntime(registry=_ProbeRegistry())

    def test_non_default_duration_is_compatible(self, monkeypatch) -> None:
        runtime = self._runtime(monkeypatch)
        assert runtime._is_task_compatible(self._probe_spec(), self._task(20.0))
        assert runtime._is_task_compatible(self._probe_spec(), self._task(-1.0))
        assert not runtime._is_task_compatible(self._probe_spec(), self._task(45.0))

    def test_named_model_survives_candidate_ranking(self, monkeypatch) -> None:
        runtime = self._runtime(monkeypatch)
        ranked = runtime._rank_candidates(
            operation="generate_video",
            modality="text_to_video",
            preferred_model=self.PROBE_ID,
            strategy="quality",
            task=self._task(20.0),
        )
        assert [spec.id for spec in ranked] == [self.PROBE_ID]

    def test_tier_list_models_still_exact_match(self, monkeypatch) -> None:
        """档位列表模型的精确匹配语义不能被区间改动波及。"""
        runtime = self._runtime(monkeypatch)
        ladder_spec = ModelSpec.from_dict(
            {
                "id": "probe-tier-video",
                "name": "probe",
                "provider": "probe",
                "modality": ["text_to_video"],
                "constraints": {"duration": [3.0, 5.0, 10.0]},
            }
        )
        assert runtime._is_task_compatible(ladder_spec, self._task(5.0))
        assert not runtime._is_task_compatible(ladder_spec, self._task(20.0))


class TestRegistryWideInvariant:
    """真正的回归护栏：注册表里不允许再出现「一问 duration 就抛异常」的 spec。"""

    @pytest.fixture()
    def all_specs(self):
        from adapters.registry import default_registry

        return default_registry().get_all_specs()

    def test_registry_still_contains_dict_shaped_yaml_entries(self, all_specs) -> None:
        ids = {spec.id for spec in all_specs}
        assert {"vidu-q3-pro-text2video", "kling/kling-v3-video-generation"} <= ids

    def test_every_spec_answers_supports_duration(self, all_specs) -> None:
        for spec in all_specs:
            assert isinstance(spec.constraints.supports_duration(5.0), bool), spec.id
            assert isinstance(spec.constraints.supports_duration(12.0), bool), spec.id

    def test_every_spec_answers_nearest_duration(self, all_specs) -> None:
        for spec in all_specs:
            nearest = spec.constraints.get_nearest_duration(5.0)
            assert nearest is None or isinstance(nearest, (int, float)), spec.id

    def test_dict_duration_specs_report_their_upstream_range(self, all_specs) -> None:
        by_id = {spec.id: spec for spec in all_specs}
        vidu = by_id["vidu-q3-pro-text2video"].constraints
        assert (vidu.duration_min, vidu.duration_max) == (1.0, 16.0)
        assert vidu.supports_duration(16.0)
        assert not vidu.supports_duration(30.0)

    def test_capability_filter_survives_task_with_duration(self, all_specs) -> None:
        task = TaskSpec(task_id="t2", modality=Modality.TEXT_TO_IMAGE, prompt="p", duration=5.0)
        candidates = CapabilityFilter().filter(task, all_specs)
        assert isinstance(candidates, list)
        assert all(spec.id != "vidu-q3-pro-text2video" for spec in candidates)
