"""kimi-preview 与 step-preview 两条长上下文文本线的契约回归。

这两个模型是项目里上下文最长的两档（1048576 / 1024000），承担长章节扩写与深度评审。
本文件锁定五件事：
1. YAML 记录的上下文/输出/定价与注册进 spec 的值一致，避免两处各说一套；
2. 归一层不会把这两条线以及本轮无关的文本模型改道；
3. 运行时能解析到可用 adapter；
4. 多模型评审白名单/治理表/席位预设、降 AI 率改写候选都只认这两个 ID；
5. 工作流生成与前端档案表都覆盖到它们。
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

LONG_CONTEXT_IDS = ("kimi-preview", "step-preview")

# 归一是全局的，这两条线之外的文本模型不该被改道
OTHER_TEXT_MODELS = (
    "qwen-plus",
    "qwen-flash",
    "glm",
    "minimax-m",
)

EXPECTED_CONTEXT_TOKENS = {
    "kimi-preview": 1048576,
    "step-preview": 1024000,
}
EXPECTED_MAX_OUTPUT_TOKENS = {
    "kimi-preview": 262144,
    "step-preview": 65536,
}
EXPECTED_COST_PER_1K = {
    "kimi-preview": (0.0065, 0.027),
    "step-preview": (0.007, 0.02),
}


@pytest.fixture(scope="module")
def llm_models() -> dict[str, dict]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["llm_models"]}


@pytest.mark.parametrize("model_id", LONG_CONTEXT_IDS)
def test_id_is_not_rewritten(model_id):
    assert normalize_model_id(model_id) == model_id
    assert normalize_model_id(model_id.upper()) == model_id


@pytest.mark.parametrize("model_id", OTHER_TEXT_MODELS)
def test_other_text_models_are_not_rewritten(model_id):
    assert normalize_model_id(model_id).lower() == model_id.lower()


def test_entries_are_active_and_routable(llm_models):
    for model_id in LONG_CONTEXT_IDS:
        entry = llm_models[model_id]
        routing = entry["routing"]
        assert entry["status"] == "active", model_id
        assert routing["enabled"] is True, model_id
        assert routing["task_types"], f"{model_id} 未挂载任何任务类型"


def test_context_and_output_expectations(llm_models):
    for model_id in LONG_CONTEXT_IDS:
        constraints = llm_models[model_id]["constraints"]
        assert constraints["max_context_tokens"] == EXPECTED_CONTEXT_TOKENS[model_id], model_id
        assert constraints["max_output_tokens"] == EXPECTED_MAX_OUTPUT_TOKENS[model_id], model_id


def test_ids_resolve_to_available_adapters():
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    registry = model_hub.registry
    for model_id in LONG_CONTEXT_IDS:
        spec = registry.get_spec(model_id)
        assert spec is not None, model_id
        assert spec.is_available(), f"{model_id} 应处于可用状态"
        assert registry.get_adapter(model_id) is not None, f"{model_id} 缺少 adapter"


@pytest.mark.parametrize("model_id", LONG_CONTEXT_IDS)
def test_yaml_and_runtime_spec_agree(model_id):
    """YAML 是文本模型链路的唯一事实源，两处数字打架时以谁为准都说不清。"""
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    spec = model_hub.registry.get_spec(model_id)
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    entry = next(item for item in payload["llm_models"] if item["id"] == model_id)

    assert spec.constraints.max_context_tokens == entry["constraints"]["max_context_tokens"]
    assert spec.constraints.max_output_tokens == entry["constraints"]["max_output_tokens"]
    performance = entry["performance"]
    assert performance["currency"] == "CNY", f"{model_id} 定价币种应为人民币"
    assert spec.performance.currency == "CNY"
    assert (
        performance["cost_per_1k_input_tokens"],
        performance["cost_per_1k_output_tokens"],
    ) == EXPECTED_COST_PER_1K[model_id]
    assert spec.performance.cost_per_1k_input_tokens == pytest.approx(
        EXPECTED_COST_PER_1K[model_id][0]
    )
    assert spec.performance.cost_per_1k_output_tokens == pytest.approx(
        EXPECTED_COST_PER_1K[model_id][1]
    )


def test_review_whitelist_and_governance_agree():
    from app.services.agents.multi_model_review_service import (
        MODEL_REVIEW_GOVERNANCE,
        MULTI_MODEL_REVIEW_ALLOWED_MODELS,
        REVIEWER_PANEL_PRESETS,
    )

    for model_id in LONG_CONTEXT_IDS:
        assert model_id in MULTI_MODEL_REVIEW_ALLOWED_MODELS
        assert model_id in MODEL_REVIEW_GOVERNANCE
    assert MULTI_MODEL_REVIEW_ALLOWED_MODELS == set(MODEL_REVIEW_GOVERNANCE)

    panel_models = {
        reviewer["model"] for panel in REVIEWER_PANEL_PRESETS.values() for reviewer in panel
    }
    assert panel_models <= MULTI_MODEL_REVIEW_ALLOWED_MODELS, "评审预设钉着白名单外的型号"


@pytest.mark.parametrize("preset", ["balanced_3", "key_chapter_5", "deep_7"])
def test_review_presets_still_pass_governance(preset):
    """换模型会改变厂商分布与强推理配额，预设必须仍能通过自身校验。"""
    from app.services.agents.multi_model_review_service import MultiModelReviewService

    service = MultiModelReviewService(preset=preset)
    assert len(service.reviewers) == int(preset.rsplit("_", 1)[1])


def test_chief_model_literal_accepts_long_context_ids():
    from app.schemas.review_config import MultiModelReviewConfig

    for model_id in LONG_CONTEXT_IDS:
        assert MultiModelReviewConfig(chief_model=model_id).chief_model == model_id


def test_workflow_generation_can_select_long_context_ids():
    """工作流生成有上下文与输出双门槛，两条长线都必须过线，否则用户选不到。"""
    from app.api.v1.workflow.model_selection import (
        MIN_WORKFLOW_CONTEXT_TOKENS,
        MIN_WORKFLOW_OUTPUT_TOKENS,
        resolve_workflow_generation_model,
    )
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    for model_id in LONG_CONTEXT_IDS:
        spec = model_hub.registry.get_spec(model_id)
        assert spec.constraints.max_context_tokens >= MIN_WORKFLOW_CONTEXT_TOKENS, model_id
        assert spec.constraints.max_output_tokens >= MIN_WORKFLOW_OUTPUT_TOKENS, model_id
        assert resolve_workflow_generation_model(model_id) == model_id


def test_rewrite_competition_catalog_covers_long_context_ids():
    from app.services.ai_trace_competition import (
        _MODEL_INFO_MAP,
        DEFAULT_REWRITE_MODEL,
        REWRITE_CAPABLE_MODELS,
    )

    listed = {info.model_id for info in REWRITE_CAPABLE_MODELS}
    assert set(LONG_CONTEXT_IDS) <= listed
    assert set(_MODEL_INFO_MAP) == listed
    assert DEFAULT_REWRITE_MODEL in listed

    by_id = {info.model_id: info for info in REWRITE_CAPABLE_MODELS}
    for model_id, (input_cost, output_cost) in EXPECTED_COST_PER_1K.items():
        assert by_id[model_id].cost_per_1k_input == pytest.approx(input_cost), model_id
        assert by_id[model_id].cost_per_1k_output == pytest.approx(output_cost), model_id


def test_frontend_model_display_maps_cover_long_context_ids():
    """前端档案表按小写 ID 查表，漏登记会退化成「成本未知/暂无实测速度」的兜底文案。"""
    display_ts = (ROOT_DIR / "frontend" / "src" / "utils" / "workflowGenerationModelDisplay.ts")
    source = display_ts.read_text(encoding="utf-8")
    for model_id in LONG_CONTEXT_IDS:
        assert source.count(f"'{model_id.lower()}'") >= 2, f"{model_id} 未同时登记到两张前端表"
