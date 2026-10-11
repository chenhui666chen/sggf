from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT_DIR / "scripts" / "check_model_integration.py"


def load_check_module():
    module_name = "test_check_model_integration_module"
    spec = spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 check_model_integration.py")

    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


check_model_integration = load_check_module()


@dataclass
class _FakeRouting:
    task_types: list[str] = field(default_factory=list)


@dataclass
class _FakeLLMSpec:
    id: str
    routing: _FakeRouting


@dataclass
class _FakeMediaConstraints:
    ratios: list[str] = field(default_factory=lambda: ["1:1"])
    min_width: int = 256
    max_width: int = 2048
    min_height: int = 256
    max_height: int = 2048
    duration: list[float] = field(default_factory=list)


@dataclass
class _FakeMediaSpec:
    id: str
    modality: list[str]
    constraints: _FakeMediaConstraints = field(default_factory=_FakeMediaConstraints)


@dataclass
class _FakeModel:
    id: str


def test_resolve_requested_chains_auto_detects_membership() -> None:
    assert check_model_integration.resolve_requested_chains(
        "all",
        "qwen-plus",
        ["qwen-plus"],
        ["qwen-image-3.0"],
    ) == ["llm"]

    assert check_model_integration.resolve_requested_chains(
        "all",
        "qwen-image-3.0",
        ["qwen-plus"],
        ["qwen-image-3.0"],
    ) == ["media"]


def test_collect_llm_checks_reports_missing_adapter_and_reroute_warning() -> None:
    spec = _FakeLLMSpec(id="test-llm", routing=_FakeRouting(task_types=["chapter"]))

    class _FakeRegistry:
        def get_spec(self, model_id: str):
            return spec if model_id == "test-llm" else None

        def get_adapter(self, model_id: str):
            return None

    class _FakeHub:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def resolve_model_request(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("model"):
                return {
                    "task_type": kwargs.get("task_type"),
                    "strategy": kwargs.get("strategy"),
                    "requested_model_id": kwargs.get("model"),
                    "resolved_model_id": "fallback-llm",
                    "rerouted": True,
                    "selection_mode": "explicit_model",
                    "reason": "catalog_guard_reroute",
                }
            return {
                "task_type": kwargs.get("task_type"),
                "strategy": kwargs.get("strategy"),
                "requested_model_id": None,
                "resolved_model_id": "task-router-llm",
                "rerouted": False,
                "selection_mode": "task_router",
                "reason": None,
            }

    fake_hub = _FakeHub()
    results = check_model_integration.collect_llm_checks(
        ["test-llm"],
        configured_model_ids=["test-llm"],
        registry=_FakeRegistry(),
        hub=fake_hub,
        config_path=check_model_integration.LLM_CONFIG_PATH,
        task_type=None,
        strategy="quality",
    )

    assert len(results) == 1
    result = results[0]
    assert result.has_spec is True
    assert result.has_adapter is False
    assert "运行时未注册 adapter" in result.errors
    assert result.route_preview is not None
    assert result.route_preview["task_type"] == "chapter"
    assert result.route_preview["explicit_request"]["resolved_model_id"] == "fallback-llm"
    assert result.route_preview["task_router"]["resolved_model_id"] == "task-router-llm"
    assert any("显式请求当前会被改写到 fallback-llm" in item for item in result.warnings)
    assert len(fake_hub.calls) == 2


def test_collect_media_checks_returns_candidate_preview() -> None:
    spec = _FakeMediaSpec(id="target-media-model", modality=["text_to_image"])

    class _FakeRegistry:
        def get_spec(self, model_id: str):
            return spec if model_id == "target-media-model" else None

        def get_adapter(self, model_id: str):
            return object()

    class _FakeRouter:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def route_with_fallback_by_strategy(self, task, strategy: str, max_fallbacks: int = 3):
            self.calls.append(
                {
                    "task": task,
                    "strategy": strategy,
                    "max_fallbacks": max_fallbacks,
                }
            )
            return SimpleNamespace(
                selected_model=_FakeModel("primary-model"),
                fallback_models=[_FakeModel("target-media-model")],
                score=0.88,
            )

    fake_router = _FakeRouter()
    results = check_model_integration.collect_media_checks(
        ["target-media-model"],
        configured_model_ids=["target-media-model"],
        llm_model_ids=[],
        registry=_FakeRegistry(),
        smart_router=fake_router,
        config_path=check_model_integration.MEDIA_CONFIG_PATH,
        strategy="cost",
    )

    assert len(results) == 1
    result = results[0]
    assert result.has_spec is True
    assert result.has_adapter is True
    assert result.adapter_type == "object"
    assert result.route_preview is not None
    assert result.route_preview["selected_model"] == "primary-model"
    assert result.route_preview["candidate_models"] == ["primary-model", "target-media-model"]
    assert result.route_preview["target_in_candidates"] is True
    assert fake_router.calls[0]["strategy"] == "cost"
    assert fake_router.calls[0]["task"].modality.value == "text_to_image"


class _ArchiveOnlyRouter:
    """档案型条目不参与路由预览，路由器不应被调用。"""


def test_llm_mirror_in_media_yaml_is_archive_not_failure() -> None:
    """LLM 线在 models.yaml 里的档案镜像没有媒体 adapter 属预期，不能计成 error。"""
    spec = _FakeMediaSpec(id="glm", modality=["text_to_text"])

    class _FakeRegistry:
        def get_spec(self, model_id: str):
            return spec if model_id == "glm" else None

        def get_adapter(self, model_id: str):
            return None

    results = check_model_integration.collect_media_checks(
        ["glm"],
        configured_model_ids=["glm"],
        llm_model_ids=["glm"],
        registry=_FakeRegistry(),
        smart_router=_ArchiveOnlyRouter(),
        config_path=check_model_integration.MEDIA_CONFIG_PATH,
    )

    result = results[0]
    assert "档案镜像" in (result.non_adapter_reason or "")
    assert result.has_adapter is False
    assert result.errors == []
    assert result.is_passed is True
    assert result.status_label == "NON_ADAPTER"
    assert result.route_preview is None


def test_tts_engine_model_is_exempt_from_adapter_check() -> None:
    """语音合成由 TTSEngine 直连实现，注册表没有 adapter 不是故障。"""
    spec = _FakeMediaSpec(id="stepaudio-3-tts", modality=["text_to_speech"])

    class _FakeRegistry:
        def get_spec(self, model_id: str):
            return spec if model_id == "stepaudio-3-tts" else None

        def get_adapter(self, model_id: str):
            return None

    results = check_model_integration.collect_media_checks(
        ["stepaudio-3-tts"],
        configured_model_ids=["stepaudio-3-tts"],
        llm_model_ids=[],
        registry=_FakeRegistry(),
        smart_router=_ArchiveOnlyRouter(),
        config_path=check_model_integration.MEDIA_CONFIG_PATH,
    )

    result = results[0]
    assert "TTSEngine" in (result.non_adapter_reason or "")
    assert result.errors == []
    assert result.is_passed is True


def test_media_only_spec_without_adapter_still_fails() -> None:
    """反向断言：不在 LLM 名单里的无 adapter 条目仍是 error，豁免不能吞掉真故障。"""
    spec = _FakeMediaSpec(id="probe-yaml-only", modality=["text_to_image"])

    class _FakeRegistry:
        def get_spec(self, model_id: str):
            return spec if model_id == "probe-yaml-only" else None

        def get_adapter(self, model_id: str):
            return None

    results = check_model_integration.collect_media_checks(
        ["probe-yaml-only"],
        configured_model_ids=["probe-yaml-only"],
        llm_model_ids=["glm"],
        registry=_FakeRegistry(),
        smart_router=_ArchiveOnlyRouter(),
        config_path=check_model_integration.MEDIA_CONFIG_PATH,
    )

    result = results[0]
    assert result.non_adapter_reason is None
    assert "运行时未注册 adapter" in result.errors
    assert result.is_passed is False

