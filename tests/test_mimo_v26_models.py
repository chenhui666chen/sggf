"""小米 MiMo V2.6 文本线（mimo-pro / mimo-flash）契约回归。

重点守住一件容易踩的事：同族的 mimo-v2.5-tts 三件套仍在上游在售，
任何按前缀做的 ID 归一或停用都会把有声书音色链路打到不存在的型号上。
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
MODELS_YAML = ROOT_DIR / "config" / "models.yaml"

MIMO_TEXT_IDS = ("mimo-pro", "mimo-flash")

# 同族但仍在售的 TTS 型号，绝不能被归一或停用波及
TTS_SIBLINGS = (
    "mimo-v2.5-tts",
    "mimo-v2.5-tts-voicedesign",
    "mimo-v2.5-tts-voiceclone",
)


@pytest.fixture(scope="module")
def llm_models() -> dict[str, dict]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["llm_models"]}


@pytest.fixture(scope="module")
def media_models() -> dict[str, dict]:
    payload = yaml.safe_load(MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["models"]}


@pytest.mark.parametrize("model_id", MIMO_TEXT_IDS)
def test_id_is_not_rewritten(model_id):
    assert normalize_model_id(model_id) == model_id


@pytest.mark.parametrize("sibling", TTS_SIBLINGS)
def test_tts_siblings_are_neither_aliased_nor_deprecated(sibling, media_models):
    """mimo-v2.5-tts* 仍在上游在售，归一会直接把有声书音色链路打到不存在的型号上。"""
    assert normalize_model_id(sibling) == sibling
    entry = media_models.get(sibling)
    assert entry is not None, f"{sibling} 应保留在 models.yaml 中"
    assert entry.get("status") != "deprecated"


def test_entries_are_active_and_routable(llm_models):
    for model_id in MIMO_TEXT_IDS:
        entry = llm_models[model_id]
        routing = entry["routing"]
        assert entry["status"] == "active", model_id
        assert routing["enabled"] is True, model_id
        assert routing["task_types"], f"{model_id} 未挂载任何任务类型"


def test_ids_resolve_to_available_adapters():
    from core.model_runtime import ensure_model_hub_initialized

    ensure_model_hub_initialized()
    from core.model_hub import model_hub

    registry = model_hub.registry
    for model_id in MIMO_TEXT_IDS:
        spec = registry.get_spec(model_id)
        assert spec is not None, model_id
        assert spec.is_available(), f"{model_id} 应处于可用状态"
        assert registry.get_adapter(model_id) is not None, f"{model_id} 缺少 adapter"


def test_review_governance_covers_mimo_text_ids():
    from app.services.agents.multi_model_review_service import (
        MODEL_REVIEW_GOVERNANCE,
        MULTI_MODEL_REVIEW_ALLOWED_MODELS,
    )

    for model_id in MIMO_TEXT_IDS:
        assert model_id in MULTI_MODEL_REVIEW_ALLOWED_MODELS
        assert model_id in MODEL_REVIEW_GOVERNANCE


def test_chief_model_literal_accepts_mimo_text_ids():
    from app.schemas.review_config import MultiModelReviewConfig

    for model_id in MIMO_TEXT_IDS:
        assert MultiModelReviewConfig(chief_model=model_id).chief_model == model_id
