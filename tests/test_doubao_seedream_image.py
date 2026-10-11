"""火山方舟 Seedream 图像线（5-0-pro / 5-0）契约回归，含 size 格式翻译与面积兜底。

方舟预置接入点到期直接关停且不做 Model ID 改写转发，所以适配器 MODEL_ID 必须写上游快照真名。

本文件守住一个会直接导致 400 的既有约定差异：UnifiedMediaRuntime._build_legacy_adapter_kwargs
按百炼约定拼 ``f"{width}*{height}"``，而方舟只认 ``WIDTHxHEIGHT``。2026-10-08 实测证据：

* ``size=1536*1536`` → HTTP 400 InvalidParameter，提示 must be 'WIDTHxHEIGHT' or a supported size preset
* ``size=100x100``   → HTTP 400 InvalidParameter，提示 image area must be at least 921600 pixels
* ``size=1536x1536`` / ``1536x1024`` → 真实出图成功，延迟约 24s / 16s

面积下限按档位不同：5.0 Pro 为 921600 px，5.0 为 3686400 px
（``doubao-seedream-5-0-260128`` + ``1024x576`` 实测被拒并回显 image size must be at least
3686400 pixels），两个适配器都必须各自做面积兜底，否则走 runtime 依旧 400。

星号是百炼的私有约定、``x`` 是方舟的私有约定，故翻译放在方舟适配器 ``_resolve_size`` 内，
共用的 ``_build_legacy_adapter_kwargs`` 不动。方舟还校验总面积，而 ConstraintSpec 只有单边上下限，
所以面积兜底也只能落在适配器里。
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

PRO_ID = "doubao-seedream-5-0-pro"
PRO_WIRE_NAME = "doubao-seedream-5-0-pro-260628"
STD_ID = "doubao-seedream-5-0"
STD_WIRE_NAME = "doubao-seedream-5-0-260128"

# 2026-10-08 方舟实测：100x100 被拒并回显该下限
PRO_MIN_AREA = 921600
STD_MIN_AREA = 3686400
# 调研值（约 2K，无 4K 档）；越界只会安全回退到 DEFAULT_SIZE，不会失败
PRO_MAX_AREA = 4624220
PRO_DEFAULT_SIZE = "1536x1536"


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


def _capture_post(monkeypatch, module="adapters.volcengine.image"):
    """打桩 requests.post，捕获方舟实际收到的 payload。"""
    captured: dict = {}

    def _fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["payload"] = json
        return types.SimpleNamespace(
            json=lambda: {"data": [{"url": "https://example.invalid/img.png"}]}
        )

    monkeypatch.setattr(f"{module}.requests.post", _fake_post, raising=True)
    monkeypatch.setattr(f"{module}.require_api_key", lambda name: "stub-key")
    return captured


# ---------------------------------------------------------------- 注册表与配置


@pytest.mark.parametrize("model_id", [PRO_ID, STD_ID])
def test_id_is_not_rewritten(model_id):
    assert normalize_model_id(model_id) == model_id


@pytest.mark.parametrize(
    "model_id,wire_name",
    [(PRO_ID, PRO_WIRE_NAME), (STD_ID, STD_WIRE_NAME)],
)
def test_yaml_entries_are_active_with_upstream_wire_names(models, model_id, wire_name):
    entry = models[model_id]
    assert entry["status"] == "active"
    assert entry["api_config"]["request_format"]["model"] == wire_name


@pytest.mark.parametrize(
    "model_id,wire_name",
    [(PRO_ID, PRO_WIRE_NAME), (STD_ID, STD_WIRE_NAME)],
)
def test_registry_specs_reflect_yaml_status(media_registry, models, model_id, wire_name):
    from schemas.common import ModelStatus

    assert models[model_id]["status"] == "active"
    assert media_registry.get_spec(model_id).status == ModelStatus.ACTIVE
    assert media_registry.get_adapter(model_id).MODEL_ID == wire_name


def test_pro_entry_declares_ark_constraints(models):
    constraints = models[PRO_ID]["constraints"]
    assert constraints["max_prompt_length"] == 1500
    assert constraints["min_width"] == 512
    assert constraints["max_width"] == 2150


@pytest.mark.parametrize("model_id", [PRO_ID, STD_ID])
def test_routable_for_generate_image(model_id):
    from core.unified_media_runtime import _OPERATION_MODEL_IDS

    assert model_id in _OPERATION_MODEL_IDS["generate_image"]


# ---------------------------------------------------------------- size 翻译与面积兜底


@pytest.mark.parametrize(
    "raw,expected",
    [
        # runtime legacy 通道下发的百炼星号格式必须翻译成方舟的 x
        ("1536*1024", "1536x1024"),
        ("1536x1024", "1536x1024"),
        # 1024x576 = 589824 px，低于方舟 921600 px 面积下限 → 回退 1.5K 档
        ("1024*576", PRO_DEFAULT_SIZE),
        ("1024x576", PRO_DEFAULT_SIZE),
        # 超出面积上限 → 回退
        ("3000*3000", PRO_DEFAULT_SIZE),
        # 缺失或无法解析 → 回退
        (None, PRO_DEFAULT_SIZE),
        ("", PRO_DEFAULT_SIZE),
        ("banana", PRO_DEFAULT_SIZE),
        ("2k", PRO_DEFAULT_SIZE),
    ],
)
def test_resolve_size_for_pro(media_registry, raw, expected):
    adapter = media_registry.get_adapter(PRO_ID)
    assert adapter.MIN_AREA == PRO_MIN_AREA
    assert adapter.MAX_AREA == PRO_MAX_AREA
    assert adapter._resolve_size(raw) == expected


def test_resolve_size_applies_higher_floor_to_std(media_registry):
    """5-0 的面积下限更高——2026-10-08 实测 1024x576 被拒，下限 3686400 px。"""
    adapter = media_registry.get_adapter(STD_ID)
    assert adapter.MIN_AREA == STD_MIN_AREA
    assert adapter._resolve_size("1024*576") == adapter.DEFAULT_SIZE
    # 面积合法时星号仍要翻译，且不得改动用户指定的宽高比
    assert adapter._resolve_size("2048*1900") == "2048x1900"


# ---------------------------------------------------------------- 生产路径 payload


def test_adapter_payload_uses_ark_size_format(monkeypatch, media_registry):
    captured = _capture_post(monkeypatch)
    adapter = media_registry.get_adapter(PRO_ID)
    result = adapter.generate(prompt="a rose", size="1024*576")

    payload = captured["payload"]
    assert result.success is True
    assert payload["model"] == PRO_WIRE_NAME
    assert payload["size"] == PRO_DEFAULT_SIZE
    # n 已从方舟图像 API 参考中移除，不再下发
    assert "n" not in payload


def test_runtime_path_sends_valid_ark_size(monkeypatch):
    """回归：runtime 默认 1024x576 经 legacy 通道下发星号尺寸，未兜底前方舟直接 400。"""
    captured = _capture_post(monkeypatch)
    from core.unified_media_runtime import UnifiedMediaRuntime

    result = UnifiedMediaRuntime().generate_image(
        prompt="a rose",
        width=1024,
        height=576,
        model_id=PRO_ID,
        use_fallback=False,
    )

    payload = captured["payload"]
    assert result.success is True
    assert result.model_id == PRO_ID
    assert payload["model"] == PRO_WIRE_NAME
    assert "*" not in payload["size"]
    assert payload["size"] == PRO_DEFAULT_SIZE


def test_runtime_path_preserves_valid_aspect_ratio(monkeypatch):
    """面积合法时不得强行改成方图，否则用户指定的宽高比会被吞掉。"""
    captured = _capture_post(monkeypatch)
    from core.unified_media_runtime import UnifiedMediaRuntime

    UnifiedMediaRuntime().generate_image(
        prompt="a rose",
        width=1536,
        height=1024,
        model_id=PRO_ID,
        use_fallback=False,
    )
    assert captured["payload"]["size"] == "1536x1024"


@pytest.mark.parametrize("model_id", [PRO_ID, STD_ID])
def test_adapter_payload_pins_watermark_false(media_registry, monkeypatch, model_id):
    """Seedream 必须显式下发 ``watermark: false``。

    档案记载方舟出图默认带“AI生成”水印，不下发就吃上游默认值；视频线
    （``adapters/volcengine/video.py``）早已是 ``bool(flat.get("watermark", False))``
    的显式关闭口径，图像线不能靠默认。
    """
    captured = _capture_post(monkeypatch)
    result = media_registry.get_adapter(model_id).generate(prompt="a rose")

    assert result.success is True
    assert captured["payload"]["watermark"] is False

