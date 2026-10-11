"""deepseek-flash 契约回归。

以下事实于 2026-10-08 经真实 API 确认：上下文 1048576、最大输出 393216，
忙时单价 输入 2 / 缓存命中 0.04 / 输出 8 元每百万 tokens。

DeepSeek 走独立渠道，agents/llm_client.py 的 _is_deepseek_official_model **先归一再匹配**，
一旦集合里少了 ID，DeepSeek 流量会被误路由到 DashScope 并使用错误密钥。
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

MODEL_ID = "deepseek-flash"
DEEPSEEK_OFFICIAL_IDS = ("deepseek-flash", "deepseek-pro")

# 真实 API 越界探测回显的上限，改动前必须重新实测
MAX_CONTEXT_TOKENS = 1048576
MAX_OUTPUT_TOKENS = 393216


@pytest.fixture(scope="module")
def llm_models() -> dict[str, dict]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["llm_models"]}


def test_id_is_not_rewritten():
    assert normalize_model_id(MODEL_ID) == MODEL_ID


@pytest.mark.parametrize("model_id", DEEPSEEK_OFFICIAL_IDS)
def test_deepseek_official_channel_routing(model_id):
    """必须判定为 DeepSeek 官方渠道，否则会误用 DASHSCOPE_API_KEY。"""
    from agents.llm_client import _is_deepseek_official_model, resolve_llm_runtime_config

    assert _is_deepseek_official_model(model_id), model_id
    runtime = resolve_llm_runtime_config(model_id)
    assert runtime.api_key_env == "DEEPSEEK_API_KEY", model_id
    assert runtime.base_url == "https://api.deepseek.com", model_id


def test_entry_is_active_with_verified_limits(llm_models):
    entry = llm_models[MODEL_ID]
    constraints = entry["constraints"]

    assert entry["status"] == "active"
    assert entry["provider"] == "deepseek"
    assert entry["api_config"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert entry["api_config"]["base_url"] == "https://api.deepseek.com"
    assert entry["default_params"]["request_model"] == MODEL_ID
    assert constraints["max_context_tokens"] == MAX_CONTEXT_TOKENS
    assert constraints["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert entry["routing"]["enabled"] is True
    assert entry["routing"]["task_types"]


def test_qwen_fallback_chain(llm_models):
    assert llm_models["qwen-plus"]["routing"]["fallback_models"] == [MODEL_ID]
    assert llm_models[MODEL_ID]["routing"]["fallback_models"] == ["qwen-plus"]


def test_runtime_resolution():
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    registry = model_hub.registry
    spec = registry.get_spec(MODEL_ID)
    assert spec is not None
    assert spec.is_available()
    assert registry.get_adapter(MODEL_ID) is not None
    assert spec.constraints.max_context_tokens == MAX_CONTEXT_TOKENS
    assert spec.constraints.max_output_tokens == MAX_OUTPUT_TOKENS


def test_default_model_fallback_chain_is_available():
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    default_model = model_hub._get_default_model()
    assert default_model is not None
    assert model_hub.registry.get_spec(default_model).is_available()


def test_review_whitelist_and_governance():
    from app.services.agents.multi_model_review_service import (
        MODEL_REVIEW_GOVERNANCE,
        MULTI_MODEL_REVIEW_ALLOWED_MODELS,
    )

    assert MODEL_ID in MULTI_MODEL_REVIEW_ALLOWED_MODELS
    assert MODEL_ID in MODEL_REVIEW_GOVERNANCE
    assert MULTI_MODEL_REVIEW_ALLOWED_MODELS == set(MODEL_REVIEW_GOVERNANCE)


def test_chief_model_literal_accepts_id():
    from app.schemas.review_config import MultiModelReviewConfig

    assert MultiModelReviewConfig(chief_model=MODEL_ID).chief_model == MODEL_ID


def test_audiobook_default_llm_model(monkeypatch):
    from app.services.audiobook.llm_config import get_audiobook_llm_model

    monkeypatch.delenv("AUDIOBOOK_LLM_MODEL", raising=False)
    assert get_audiobook_llm_model() == MODEL_ID


def test_ai_trace_rewrite_pool():
    from app.services.ai_trace_competition import REWRITE_CAPABLE_MODELS

    assert MODEL_ID in {info.model_id for info in REWRITE_CAPABLE_MODELS}


def test_context_optimizer_static_limits():
    from app.services.agents.context_optimizer import ContextOptimizer

    assert ContextOptimizer.MODEL_LIMITS[MODEL_ID] == MAX_CONTEXT_TOKENS
