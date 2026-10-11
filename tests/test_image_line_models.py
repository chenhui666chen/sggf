# -*- coding: utf-8 -*-
"""图像线（qwen-image 3.0 / 3.0-pro / wan2.7-image-pro）的注册与契约测试。

上游契约取自 raw/model-api-reference/image-generation/ 下的官方 API 参考：
三个模型共用 DashScope 同步端点
/api/v1/services/aigc/multimodal-generation/generation，请求体为 input.messages + parameters。
"""
from __future__ import annotations

import pytest
import yaml

from adapters.registry import default_registry
from schemas.common import ModelStatus

MODELS_YAML = "config/models.yaml"

IMAGE_LINE_IDS = ["qwen-image-3.0", "qwen-image-3.0-pro", "wan2.7-image-pro"]
SYNC_ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"


@pytest.fixture(scope="module")
def registry():
    return default_registry()


@pytest.fixture(scope="module")
def yaml_entries():
    with open(MODELS_YAML, encoding="utf-8") as fh:
        models = yaml.safe_load(fh)["models"]
    return {m["id"]: m for m in models}


class TestImageLineModelsRegistered:
    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_registry_resolves_id(self, registry, model_id):
        adapter = registry.get_adapter(model_id)
        assert adapter is not None, f"{model_id} 未注册到媒体运行时注册表"
        assert adapter.MODEL_ID == model_id

    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_spec_is_active(self, registry, model_id):
        spec = registry.get_spec(model_id)
        assert spec is not None
        assert spec.id == model_id
        assert spec.status == ModelStatus.ACTIVE

    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_yaml_marks_id_active(self, yaml_entries, model_id):
        assert yaml_entries[model_id]["status"] == "active", model_id

    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_spec_declares_both_image_modalities(self, registry, model_id):
        """三个模型上游都同时支持文生图与图生图。"""
        spec = registry.get_spec(model_id)
        assert "text_to_image" in spec.modality
        assert "image_to_image" in spec.modality

    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_spec_carries_real_price(self, registry, model_id):
        """cost_profile 缺失会让 CostProfile.estimate 恒返回 0，成本看板会漏记这三个模型。"""
        spec = registry.get_spec(model_id)
        assert spec.cost_profile.unit == "per_request"
        assert spec.cost_profile.price > 0
        assert spec.cost_profile.currency == "CNY"

    def test_prices_match_vendor_records(self, registry):
        expected = {"qwen-image-3.0": 0.2, "qwen-image-3.0-pro": 0.27, "wan2.7-image-pro": 0.5}
        for model_id, price in expected.items():
            spec = registry.get_spec(model_id)
            assert spec.cost_profile.price == pytest.approx(price), model_id

    def test_rate_limits_match_vendor_records(self, registry):
        """qwen-image-3.0 是 2 次/6 秒（20 QPM），3.0-pro 是 5 次/60 秒，wan2.7-image-pro 是 5 RPS。

        qwen-image-3.0 的 20 QPM 明显偏紧，填错会让批量链路误判可用并发。
        """
        expected = {"qwen-image-3.0": 20, "qwen-image-3.0-pro": 5, "wan2.7-image-pro": 300}
        for model_id, rpm in expected.items():
            spec = registry.get_spec(model_id)
            assert spec.rate_limit.requests_per_minute == rpm, model_id

    def test_prompt_length(self, registry):
        """qwen-image-3.0 系列推荐 4500 Token，wan2.7-image-pro 上限 5000 字符。"""
        assert registry.get_spec("qwen-image-3.0").constraints.max_prompt_length == 4500
        assert registry.get_spec("qwen-image-3.0-pro").constraints.max_prompt_length == 4500
        assert registry.get_spec("wan2.7-image-pro").constraints.max_prompt_length == 5000

    def test_max_batch_size(self, registry):
        assert registry.get_spec("qwen-image-3.0").constraints.max_batch_size == 6
        assert registry.get_spec("wan2.7-image-pro").constraints.max_batch_size == 4


class TestEndpointRecords:
    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_recorded_endpoint_is_the_real_one(self, yaml_entries, model_id):
        """同步图像端点是 multimodal-generation/generation，不是 image-generation/generation。

        条目有两种写法：富格式用顶层 endpoint，瘦格式用 api_config.endpoint。
        两处只要出现就必须是对的。
        """
        entry = yaml_entries[model_id]
        recorded = [
            value
            for value in (entry.get("endpoint"), (entry.get("api_config") or {}).get("endpoint"))
            if value
        ]
        assert recorded, f"{model_id} 未记录任何 endpoint"
        assert set(recorded) == {SYNC_ENDPOINT}, model_id


class TestNoDuplicateRegistration:
    @pytest.mark.parametrize("model_id", IMAGE_LINE_IDS)
    def test_ids_registered_exactly_once(self, model_id):
        """同一 ID 出现两个 @register_model 时，谁生效取决于装饰器执行顺序，不可预测。"""
        import pathlib
        import re

        pattern = re.compile(r"""@register_model\(\s*["']([^"']+)["']""")
        owners = []
        for path in pathlib.Path("adapters").rglob("*.py"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                match = pattern.search(line)
                if match and match.group(1) == model_id:
                    owners.append(f"{path.as_posix()}:{lineno}")
        assert len(owners) == 1, f"{model_id} 被注册 {len(owners)} 次: {owners}"
