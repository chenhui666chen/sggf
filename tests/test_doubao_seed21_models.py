"""火山方舟 doubao-seed-2-1-{pro,lite} 文本线契约回归。

方舟预置推理接入点到期直接关停且不做 Model ID 改写转发，所以适配器实际下发的
MODEL_ID 必须是上游真名。快照名 doubao-seed-2-1-{pro,lite}-260915 于 2026-10-08
用非法参数探测确认真实存在（存在的模型返回 400 InvalidParameter，
不存在的返回 404 InvalidEndpointOrModel.NotFound）。

Seed 2.1 起深度思考默认开启，思考与正文共用 max_tokens 预算，而 _VolcengineChatAdapter.generate
只申请 200 tokens。2026-10-08 实测：开启思考延迟 1.7s→3.4s，短提示词仍有正文，但推理链稍长
就会吃光预算而返回空 content，故两个适配器一律 DISABLE_THINKING=True。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR, ROOT_DIR / "backend"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from core.model_resolution import normalize_model_id  # noqa: E402

MODELS_YAML = ROOT_DIR / "config" / "models.yaml"

# 内部 ID -> 上游快照名
WIRE_NAMES = {
    "doubao-seed-2-1-pro": "doubao-seed-2-1-pro-260915",
    "doubao-seed-2-1-lite": "doubao-seed-2-1-lite-260915",
}

# 方舟实测上限，改动前必须重新实测
CONTEXT_WINDOW = 1048576
MAX_OUTPUT_LENGTH = 262144


@pytest.fixture(scope="module")
def models() -> dict[str, dict]:
    payload = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["models"]}


@pytest.fixture(scope="module")
def media_registry():
    import adapters  # noqa: F401  触发适配器注册
    from adapters.registry import registry

    registry._ensure_builtin_registration()
    return registry


@pytest.mark.parametrize("model_id", sorted(WIRE_NAMES))
def test_id_is_not_rewritten(model_id):
    assert normalize_model_id(model_id) == model_id


@pytest.mark.parametrize("model_id,wire_name", sorted(WIRE_NAMES.items()))
def test_yaml_entry_is_active_with_verified_limits(models, model_id, wire_name):
    entry = models[model_id]
    constraints = entry["constraints"]

    assert entry["status"] == "active"
    assert entry["api_config"]["request_format"]["model"] == wire_name
    assert constraints["context_window"] == CONTEXT_WINDOW
    assert constraints["max_output_length"] == MAX_OUTPUT_LENGTH
    assert constraints["max_prompt_length"] == CONTEXT_WINDOW
    # 方舟 Seed 2.1 的 thinking.type 只接受 enabled / disabled，没有 auto
    assert constraints["thinking_levels"] == ["enabled", "disabled"]
    assert constraints["supports_thinking_mode"] is True
    pricing = entry["pricing_info"]
    assert pricing["unit"] == "per 1M tokens"
    assert pricing["input_price"] > 0
    assert pricing["output_price"] > 0


@pytest.mark.parametrize("model_id", sorted(WIRE_NAMES))
def test_registry_spec_reflects_yaml_status(media_registry, models, model_id):
    from schemas.common import ModelStatus

    assert models[model_id]["status"] == "active"
    assert media_registry.get_spec(model_id).status == ModelStatus.ACTIVE


@pytest.mark.parametrize("model_id,wire_name", sorted(WIRE_NAMES.items()))
def test_adapter_sends_upstream_wire_name(media_registry, model_id, wire_name):
    adapter = media_registry.get_adapter(model_id)
    assert adapter is not None
    assert adapter.MODEL_ID == wire_name


@pytest.mark.parametrize("model_id", sorted(WIRE_NAMES))
def test_adapter_disables_thinking_by_default(media_registry, model_id):
    """200 tokens 的冒烟请求开着思考会翻倍延迟，并有吃光预算返回空 content 的风险。"""
    assert media_registry.get_adapter(model_id).DISABLE_THINKING is True


def _capture_create_kwargs(monkeypatch, adapter):
    """用桩替换 openai.OpenAI，捕获 chat.completions.create 的入参。"""
    captured: dict = {}

    class _StubCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="pong")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    stub_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_StubCompletions())
    )
    monkeypatch.setattr(
        "openai.OpenAI", lambda **kwargs: stub_client, raising=True
    )
    monkeypatch.setattr(
        "adapters.volcengine.chat.require_api_key", lambda name: "stub-key"
    )
    result = adapter.generate(prompt="ping")
    return captured, result


def test_request_body_carries_wire_name_and_thinking_disabled(monkeypatch, media_registry):
    captured, result = _capture_create_kwargs(
        monkeypatch, media_registry.get_adapter("doubao-seed-2-1-pro")
    )
    assert result.success is True
    assert captured["model"] == "doubao-seed-2-1-pro-260915"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
