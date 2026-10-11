"""qwen-flash-fallback（上游 qwen3.8-flash）契约回归。

该条目是**仅供失败回退**的模型，刻意不注册任何 task_types：
一旦被加上 task_types，它就会进入自动路由候选，抢走 qwen-flash 的批量低成本流量。
以下事实于 2026-10-09 经 DashScope 真实 API 确认：
可调用；max_tokens 上限 131072；thinking_budget 上限 262144；支持图像输入。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from core.model_resolution import normalize_model_id

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR, ROOT_DIR / "backend"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

LLM_MODELS_YAML = ROOT_DIR / "config" / "llm_models.yaml"

FALLBACK_ID = "qwen-flash-fallback"
PRIMARY_ID = "qwen-flash"
TAIL_MODEL = "qwen-plus"

# 真实 API 越界探测回显的上限，改动前必须重新实测
MAX_CONTEXT_TOKENS = 1000000
MAX_OUTPUT_TOKENS = 131072
MAX_THINKING_TOKENS = 262144

# qwen-flash 承接的任务类型：回退模型必须全部不命中
PRIMARY_TASK_TYPES = (
    "concept",
    "outline_expand",
    "volume_outline",
    "chapter_batch",
    "long_writing",
    "summarize",
    "entity_extract",
)


@pytest.fixture(scope="module")
def llm_models() -> dict[str, dict]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["llm_models"]}


@pytest.fixture(scope="module")
def hub():
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    return model_hub


def test_id_is_not_rewritten():
    assert normalize_model_id(FALLBACK_ID) == FALLBACK_ID


def test_entry_is_available_but_not_routable(llm_models):
    entry = llm_models[FALLBACK_ID]
    constraints = entry["constraints"]
    routing = entry["routing"]

    # is_available() 要求 status ACTIVE 且 routing.enabled，否则永远选不到它
    assert entry["status"] == "active"
    assert routing["enabled"] is True
    assert routing["task_types"] == []

    assert entry["provider"] == "alibaba"
    assert entry["api_config"]["api_key_env"] == "DASHSCOPE_API_KEY"
    assert entry["api_config"]["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert entry["default_params"]["request_model"] == "qwen3.8-flash"
    assert constraints["max_context_tokens"] == MAX_CONTEXT_TOKENS
    assert constraints["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert constraints["max_thinking_tokens"] == MAX_THINKING_TOKENS


def test_fallback_chain_order(llm_models):
    """3.7-flash 失败 → 3.8-flash 顶上 → 再失败才到 qwen-plus（价格单调递增）。"""
    assert llm_models[PRIMARY_ID]["routing"]["fallback_models"] == [FALLBACK_ID, TAIL_MODEL]
    assert llm_models[FALLBACK_ID]["routing"]["fallback_models"] == [TAIL_MODEL]


def test_runtime_spec_and_adapter(hub):
    registry = hub.registry
    spec = registry.get_spec(FALLBACK_ID)
    assert spec is not None
    assert spec.is_available()
    assert registry.get_adapter(FALLBACK_ID) is not None
    assert spec.constraints.max_context_tokens == MAX_CONTEXT_TOKENS
    assert spec.constraints.max_output_tokens == MAX_OUTPUT_TOKENS


@pytest.mark.parametrize("task_type", PRIMARY_TASK_TYPES)
def test_auto_routing_never_selects_it(hub, task_type):
    registry = hub.registry
    assert FALLBACK_ID not in [spec.id for spec in registry.get_models_for_task(task_type)]
    best = registry.select_best_model(task_type)
    assert best is None or best.id != FALLBACK_ID


def test_primary_failure_lands_on_it(hub):
    """锁定本次接入的唯一目的：qwen-flash 失败时先切到 3.8-flash。"""
    spec = hub.registry.get_spec(PRIMARY_ID)
    assert hub._select_fallback_model(spec, set()) == FALLBACK_ID
    assert hub._select_fallback_model(spec, {FALLBACK_ID}) == TAIL_MODEL
    assert hub._select_fallback_model(spec, {FALLBACK_ID, TAIL_MODEL}) is None


def test_explicit_request_is_not_rerouted(hub):
    preview = hub.resolve_model_request(model=FALLBACK_ID)
    assert preview["resolved_model_id"] == FALLBACK_ID


def test_not_exposed_as_user_selectable():
    """回退专用模型不得出现在任何用户可选清单里。"""
    from app.services.ai_trace_competition import REWRITE_CAPABLE_MODELS
    from app.services.agents.multi_model_review_service import (
        MULTI_MODEL_REVIEW_ALLOWED_MODELS,
    )

    assert FALLBACK_ID not in MULTI_MODEL_REVIEW_ALLOWED_MODELS
    assert FALLBACK_ID not in {info.model_id for info in REWRITE_CAPABLE_MODELS}
