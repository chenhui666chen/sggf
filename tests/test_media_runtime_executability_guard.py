# -*- coding: utf-8 -*-
"""媒体运行时护栏：只有注册了可执行 adapter 的条目才能进入自动路由候选集。

背景：config/models.yaml 里存在「有条目、无 adapter 实现」的模型 ID，其中若干还挂在
`_OPERATION_MODEL_IDS` 白名单上。`core/router.py` 的 SmartRouter 早已有
`CapabilityFilter(adapter_resolver=...)` 护栏，但 Asset Studio 走的是
`core/unified_media_runtime.py` 这条独立路由，`_rank_candidates` 原先只看
白名单 + status + 模态，于是自动路由会把死条目排到首位；`routes_video.py` 以
`use_fallback=False` 调用时直接落到 `error_code="adapter_missing"`。

本文件锁定：
1. 自动路由（preferred_model 为空）的候选集必须剔除无 adapter 的条目；
2. 调用方显式点名的模型即使不可执行也必须排在首位——保持 adapter_missing 响亮失败，
   不得被静默替换成别的供应商模型；
3. 白名单内一个可执行模型都没有时候选集不得清空，否则报错从 adapter_missing
   变成 no_model_available，掩盖了真实原因。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _import_root in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if _import_root not in sys.path:
        sys.path.insert(0, _import_root)

import core.unified_media_runtime as runtime_module
from core.unified_media_runtime import UnifiedMediaRuntime
from schemas.model_spec import ModelSpec, QualityMetrics
from schemas.common import ModelStatus

_EXECUTABLE_ID = "probe-executable-video"
_DEAD_ENTRY_ID = "probe-yaml-only-video"
_PROBE_ALLOWLIST = {_EXECUTABLE_ID, _DEAD_ENTRY_ID}


def _spec(model_id: str, quality: float, modality: str = "text_to_video") -> ModelSpec:
    return ModelSpec(
        id=model_id,
        name=model_id,
        provider="probe",
        status=ModelStatus.ACTIVE,
        modality=[modality],
        quality_metrics=QualityMetrics(overall_score=quality),
    )


def _probe_specs() -> list[ModelSpec]:
    """死条目档案分更高，复刻真实故障：strategy="quality" 的自动路由首选落在它上面。"""
    return [_spec(_EXECUTABLE_ID, 5.0), _spec(_DEAD_ENTRY_ID, 9.0)]


class _ProbeRegistry:
    """只实现 _rank_candidates 用到的三个方法，可执行性由构造参数决定。"""

    def __init__(self, specs: list[ModelSpec], executable_ids: set[str]) -> None:
        self._specs = {spec.id: spec for spec in specs}
        self._executable = set(executable_ids)

    def get_all_specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def get_spec(self, model_id: str) -> ModelSpec | None:
        return self._specs.get(model_id)

    def has_adapter(self, model_id: str) -> bool:
        return model_id in self._executable


class _NeutralCatalogIndex:
    """真实索引对白名单外的 model_id 一律返回中性值，探针 ID 走同一分支。"""

    @staticmethod
    def get_signal(_model_id: str):
        return SimpleNamespace(blocked=False, priority=0, reason="")

    @staticmethod
    def get_capability_hints(_model_id: str) -> dict:
        return {}

    @staticmethod
    def get_task_constraints(_model_id: str) -> dict:
        return {}


def _runtime(
    monkeypatch,
    *,
    specs: list[ModelSpec],
    executable_ids: set[str],
    allowlist: set[str],
    operation: str = "generate_video",
) -> UnifiedMediaRuntime:
    monkeypatch.setattr(runtime_module, "get_model_catalog_runtime_index", _NeutralCatalogIndex)
    monkeypatch.setitem(runtime_module._OPERATION_MODEL_IDS, operation, allowlist)
    return UnifiedMediaRuntime(registry=_ProbeRegistry(specs, executable_ids))


def _rank(
    runtime: UnifiedMediaRuntime,
    *,
    preferred_model: Optional[str],
    operation: str = "generate_video",
    modality: str = "text_to_video",
) -> list[str]:
    return [spec.id for spec in runtime._rank_candidates(
        operation=operation,
        modality=modality,
        preferred_model=preferred_model,
        strategy="quality",
    )]


class TestAutoRouteDropsUnexecutableModels:
    def test_dead_entry_absent_from_candidates(self, monkeypatch) -> None:
        runtime = _runtime(
            monkeypatch,
            specs=_probe_specs(),
            executable_ids={_EXECUTABLE_ID},
            allowlist=_PROBE_ALLOWLIST,
        )

        candidates = _rank(runtime, preferred_model=None)

        assert candidates == [_EXECUTABLE_ID]

    def test_selected_model_is_executable(self, monkeypatch) -> None:
        """select_model 是 Asset Studio 的公开入口，首选必须可直接执行。"""
        runtime = _runtime(
            monkeypatch,
            specs=_probe_specs(),
            executable_ids={_EXECUTABLE_ID},
            allowlist=_PROBE_ALLOWLIST,
        )

        selected = runtime.select_model(
            operation="generate_video",
            modality="text_to_video",
            strategy="quality",
        )

        assert selected.id == _EXECUTABLE_ID


class TestExplicitModelStaysLoud:
    def test_named_but_unexecutable_model_still_ranks_first(self, monkeypatch) -> None:
        """显式点名不可执行模型时必须原样执行并报错，不能被静默换成别的供应商模型。"""
        runtime = _runtime(
            monkeypatch,
            specs=_probe_specs(),
            executable_ids={_EXECUTABLE_ID},
            allowlist=_PROBE_ALLOWLIST,
        )

        candidates = _rank(runtime, preferred_model=_DEAD_ENTRY_ID)

        assert candidates[0] == _DEAD_ENTRY_ID


class TestKeepsLegacyBehaviorWhenNothingExecutable:
    def test_candidates_not_emptied(self, monkeypatch) -> None:
        runtime = _runtime(
            monkeypatch,
            specs=[_spec(_DEAD_ENTRY_ID, 9.0)],
            executable_ids=set(),
            allowlist={_DEAD_ENTRY_ID},
        )

        candidates = _rank(runtime, preferred_model=None)

        assert candidates == [_DEAD_ENTRY_ID]


class TestSpeechRoutingIsOwnedByTtsEngine:
    def test_speech_candidates_ignore_adapter_registry(self, monkeypatch) -> None:
        """语音合成的执行者是 TTSEngine（按供应商直接实现），不查 adapter 注册表。

        若把注册表判据套到 synthesize_speech 上，stepaudio-3-tts 这类只在 TTSEngine
        里成立的模型会被自动路由误摘。
        """
        runtime = _runtime(
            monkeypatch,
            operation="synthesize_speech",
            specs=[
                _spec(_EXECUTABLE_ID, 5.0, modality="text_to_speech"),
                _spec(_DEAD_ENTRY_ID, 9.0, modality="text_to_speech"),
            ],
            executable_ids={_EXECUTABLE_ID},
            allowlist=_PROBE_ALLOWLIST,
        )

        candidates = _rank(
            runtime,
            operation="synthesize_speech",
            modality="text_to_speech",
            preferred_model=None,
        )

        assert candidates[0] == _DEAD_ENTRY_ID, "TTSEngine 支持的语音模型不应因注册表无 adapter 而降序"


class TestAllowlistIsExecutable:
    def test_every_allowlisted_model_has_an_implementation(self) -> None:
        """白名单是路由的硬条件，条目自身必须有真实实现。

        判据按执行者分两套：语音合成由 TTSEngine 的供应商实现负责（不查注册表），
        其余媒体类操作由 adapter 注册表负责。新增或升级模型时只补 models.yaml 档案
        和白名单、不补实现，就会重现护栏要修的故障，因此把它钉成常驻判据。
        """
        from adapters.registry import registry as default_registry
        from app.services.audiobook.tts_model_ids import SUPPORTED_AUDIOBOOK_TTS_MODELS
        from core.model_resolution import normalize_model_id

        default_registry.get_all_specs()  # 触发惰性加载
        tts_spellings = set(SUPPORTED_AUDIOBOOK_TTS_MODELS) | {
            normalize_model_id(model_id) for model_id in SUPPORTED_AUDIOBOOK_TTS_MODELS
        }
        offenders = {}
        for operation, model_ids in runtime_module._OPERATION_MODEL_IDS.items():
            if operation == "synthesize_speech":
                missing = [mid for mid in model_ids if mid not in tts_spellings]
            else:
                missing = [mid for mid in model_ids if not default_registry.has_adapter(mid)]
            if missing:
                offenders[operation] = sorted(missing)
        assert not offenders, f"白名单中存在无实现的条目: {offenders}"


class TestOmniFlashIsExecutable:
    def test_qwen35_omni_flash_has_an_adapter(self) -> None:
        """qwen3.5-omni-flash 是有声书语义评审与朗读方向分析的低成本档，
        档案长期写在 models.yaml 里但注册表无 adapter，接入后必须按 omni-plus 同样的方式解析。"""
        from adapters.registry import registry as default_registry

        assert default_registry.has_adapter("qwen3.5-omni-flash")


class TestEditVideoOperationIsConfigured:
    """operation 键漏配时白名单查不到任何条目：自动路由候选恒空、
    显式点名抛 does not support，/video-edit 只能在运行期失败。"""

    def test_edit_video_allowlist_entries_can_actually_edit(self) -> None:
        from adapters.registry import registry as default_registry

        allowlist = runtime_module._OPERATION_MODEL_IDS.get("edit_video")
        assert allowlist, "_OPERATION_MODEL_IDS 缺少 edit_video 键"

        offenders = []
        for model_id in sorted(allowlist):
            spec = default_registry.get_spec(model_id)
            if spec is None:
                offenders.append(f"{model_id}(无档案)")
                continue
            if "video_edit" not in (spec.modality or []):
                offenders.append(f"{model_id}(档案未声明 video_edit)")
            elif not default_registry.has_adapter(model_id):
                offenders.append(f"{model_id}(无 adapter)")
        assert not offenders, f"edit_video 白名单条目不可执行: {offenders}"

    def test_edit_video_routes_to_a_candidate(self) -> None:
        spec = UnifiedMediaRuntime().select_model(
            operation="edit_video",
            modality="video_edit",
            strategy="balanced",
        )

        assert spec.id in runtime_module._OPERATION_MODEL_IDS["edit_video"]

    def test_edit_video_forwards_reference_video_to_adapter(self, monkeypatch) -> None:
        """路由通了还不够：源视频必须真的落到 adapter 调用参数上，否则编辑请求是空素材。"""
        from adapters.base import GenerationResult

        calls: list[dict] = []

        class _RecordingAdapter:
            def generate(self, **kwargs):
                calls.append(kwargs)
                return GenerationResult(
                    success=True,
                    task_id="",
                    model_id=kwargs.get("model_id", ""),
                    outputs=["https://cdn.example.com/edited.mp4"],
                )

        runtime = _runtime(
            monkeypatch,
            operation="edit_video",
            specs=[_spec(_EXECUTABLE_ID, 5.0, modality="video_edit")],
            executable_ids={_EXECUTABLE_ID},
            allowlist={_EXECUTABLE_ID},
        )
        runtime._registry.get_adapter = lambda model_id: _RecordingAdapter()  # type: ignore[method-assign]

        result = runtime.edit_video(
            prompt="把背景换成雪夜",
            duration=5,
            width=1024,
            height=576,
            video_path="C:/tmp/source.mp4",
            model_id=_EXECUTABLE_ID,
            use_fallback=False,
        )

        assert result.success is True
        assert calls, "edit_video 没有到达 adapter"
        assert calls[0]["video_path"] == "C:/tmp/source.mp4"


class TestVisionAnalysisIsExecutable:
    """视觉评审由 adapter 上的同名方法执行（_execute_custom_registry_method），
    注册了 adapter 但没有该方法、或档案未声明理解 modality，都等于不可执行。"""

    def test_every_vision_allowlist_entry_exposes_its_method(self) -> None:
        from adapters.registry import registry as default_registry

        required_modality = {
            "analyze_image": "image_understanding",
            "analyze_video": "video_understanding",
        }
        offenders = []
        for operation, modality in required_modality.items():
            for model_id in sorted(runtime_module._OPERATION_MODEL_IDS.get(operation, set())):
                adapter = default_registry.get_adapter(model_id)
                if adapter is None:
                    offenders.append(f"{operation}:{model_id}(无 adapter)")
                    continue
                if not callable(getattr(adapter, operation, None)):
                    offenders.append(f"{operation}:{model_id}(adapter 未实现 {operation})")
                spec = default_registry.get_spec(model_id)
                if spec is None or modality not in (spec.modality or []):
                    offenders.append(f"{operation}:{model_id}(档案未声明 {modality})")
        assert not offenders, f"视觉评审白名单条目不可执行: {offenders}"

    def test_vision_review_routes_to_an_executable_model(self) -> None:
        runtime = UnifiedMediaRuntime()

        image_spec = runtime.select_model(
            operation="analyze_image",
            modality="image_understanding",
            strategy="quality",
        )
        video_spec = runtime.select_model(
            operation="analyze_video",
            modality="video_understanding",
            strategy="quality",
        )

        assert callable(getattr(runtime._registry.get_adapter(image_spec.id), "analyze_image", None))
        assert callable(getattr(runtime._registry.get_adapter(video_spec.id), "analyze_video", None))

