"""文本模型输出上限档案对账测试。

背景：内部 ID 不带版本号，换代只改 `default_params.request_model`，
`constraints.max_output_tokens` 不会有任何提醒地停留在上一代取值。
本测试把 2026-10-09 用 `scripts/probe_llm_output_limits.py` 越界探测拿到的
上游真实上限钉成事实源，并把装饰器镜像一起核对。

上游若发布新上限，先重跑探测脚本，再回来改这张表，不要反过来改脚本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
for _path in (ROOT_DIR, ROOT_DIR / "backend"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

LLM_MODELS_YAML = ROOT_DIR / "config" / "llm_models.yaml"
LLM_ADAPTERS_PY = ROOT_DIR / "core" / "llm_adapters.py"

# 2026-10-09 越界探测实测（400 报文回显）。注释里只写内部 ID 与回显文案，
# 不写上游真名——退役门禁把上游真名在业务层的出现也算作待改引用。
MEASURED_MAX_OUTPUT_TOKENS = {
    "qwen-plus": 131072,               # Range of max_tokens should be [1, 131072]
    "qwen-flash": 131072,              # 同上
    "qwen-flash-fallback": 131072,     # 同上
    "glm": 131072,                     # 同上
    "minimax-m": 524288,               # does not support max tokens > 524288
    "mimo-pro": 131072,                # supports at most 131072 completion tokens
    "mimo-flash": 131072,              # 同上
    "doubao-seed-evolving": 262144,    # expected a value <= 262144
    "doubao-seed-character": 32768,    # expected a value <= 32768
}

# 2026-10-09 越界探测实测的思考预算上限（thinking_budget 只在开启思考时才被校验）
MEASURED_MAX_THINKING_TOKENS = {
    "qwen-plus": 262144,
    "qwen-flash": 131072,
    "qwen-flash-fallback": 262144,
}

# 上游不校验 max_tokens，档案值是项目自选的保守上界，不能由实测钉死
NOT_PROBEABLE_IDS = (
    "kimi-preview",
    "step-preview",
)

# 强制思考模型：收到任何关思考写法都 400
FORCED_THINKING_IDS = ("glm",)


@pytest.fixture(scope="module")
def llm_entries() -> dict[str, dict]:
    payload = yaml.safe_load(LLM_MODELS_YAML.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in payload["llm_models"]}


@pytest.mark.parametrize("model_id,expected", sorted(MEASURED_MAX_OUTPUT_TOKENS.items()))
def test_archived_output_limit_matches_measurement(llm_entries, model_id, expected):
    assert llm_entries[model_id]["constraints"]["max_output_tokens"] == expected, model_id


@pytest.mark.parametrize("model_id,expected", sorted(MEASURED_MAX_THINKING_TOKENS.items()))
def test_archived_thinking_limit_matches_measurement(llm_entries, model_id, expected):
    assert llm_entries[model_id]["constraints"]["max_thinking_tokens"] == expected, model_id


def test_default_send_value_is_not_the_ceiling(llm_entries):
    """把默认发送值当上限写进档案，是上一轮上限陈旧的成因之一。"""
    for model_id in MEASURED_MAX_OUTPUT_TOKENS:
        default_max = llm_entries[model_id]["default_params"].get("max_tokens")
        ceiling = llm_entries[model_id]["constraints"]["max_output_tokens"]
        if default_max is not None:
            assert default_max <= ceiling, model_id


@pytest.mark.parametrize("model_id", NOT_PROBEABLE_IDS)
def test_unprobeable_limits_are_declared_in_archive(llm_entries, model_id):
    """探不到的上限必须在 integration_notes 里写明「无法实测」，否则下轮会被当成错值改掉。"""
    notes = "\n".join(str(item) for item in (llm_entries[model_id].get("integration_notes") or []))
    assert ("实测" in notes or "探测" in notes) and (
        "不校验" in notes or "无法" in notes or "未配置" in notes
    ), f"{model_id} 的上限来源未记录"


def _decorator_max_output_tokens() -> dict[str, int]:
    source = LLM_ADAPTERS_PY.read_text(encoding="utf-8")
    found: dict[str, int] = {}
    for block in source.split("@register_llm_model(")[1:]:
        model_match = re.search(r'model_id="([^"]+)"', block)
        limit_match = re.search(r"max_output_tokens=(\d+)", block)
        if model_match and limit_match:
            found[model_match.group(1)] = int(limit_match.group(1))
    return found


@pytest.mark.parametrize("model_id,expected", sorted(MEASURED_MAX_OUTPUT_TOKENS.items()))
def test_adapter_decorator_mirrors_yaml(llm_entries, model_id, expected):
    """装饰器只在 YAML 缺条目时才生效，但读者会把它当档案读，两处数字不许打架。"""
    decorators = _decorator_max_output_tokens()
    assert model_id in decorators, f"{model_id} 缺少装饰器镜像"
    assert decorators[model_id] == expected == llm_entries[model_id]["constraints"]["max_output_tokens"]


@pytest.mark.parametrize("model_id", FORCED_THINKING_IDS)
def test_forced_thinking_models_never_send_thinking_disable(llm_entries, model_id):
    from core.model_resolution import _FORCED_THINKING_MODEL_IDS, build_thinking_disabled_extra_body

    assert model_id in _FORCED_THINKING_MODEL_IDS
    assert build_thinking_disabled_extra_body(model_id) == {}

    default_params = llm_entries[model_id].get("default_params") or {}
    assert "enable_thinking" not in default_params, f"{model_id} 仍会下发关思考参数"
    thinking = default_params.get("thinking")
    assert not (isinstance(thinking, dict) and thinking.get("type") == "disabled"), (
        f"{model_id} 是强制思考模型，default_params 里不能留关思考写法"
    )


def test_probe_script_recognizes_ark_echo_and_treats_unprobed_as_not_passed():
    """探测脚本认不得某家文案 = 那家的档案上限永远没人核对（262144 被写成 16384 就是这么活下来的）。"""
    from scripts.probe_llm_output_limits import ProbeResult, _parse_limit

    ark_echo = (
        "Error code: 400 - {'error': {'code': 'InvalidParameter', 'message': "
        "'The parameter `max_tokens` specified in the request are not valid: integer above "
        "maximum value, expected a value <= 262144, but got 999999 instead'}"
    )
    assert _parse_limit(ark_echo) == 262144

    unprobed = ProbeResult(model_id="x", request_model="x", channel="X_KEY", archived_output=16384)
    assert unprobed.unprobed and not unprobed.output_drift

    unprobed.probed_output = 262144
    assert not unprobed.unprobed and unprobed.output_drift

    registered_skip = ProbeResult(
        model_id="y", request_model="y", channel="Y_KEY", archived_output=65536, intentional_skip=True
    )
    assert not registered_skip.unprobed
