# -*- coding: utf-8 -*-
"""同步图像适配器必须把 negative_prompt 转发进 parameters，而不是静默丢弃。

背景：运行时确实会把 negative_prompt 一路传到适配器
（core/unified_media_runtime.py:234,256 -> _build_legacy_adapter_kwargs），
但 adapters/dashscope/image_sync.py 的 _SyncImageAdapter.generate 原先只读
size / image_path 两个 kwarg，其余全部丢掉。调用方以为反向提示词生效了，
实际发给供应商的请求体里根本没有这个字段——用户拿到的图不会规避任何被禁止的元素，
而且没有任何日志或报错提示这件事。

官方依据（multimodal-generation/generation 端点，parameters 内）：
- qwen-image 系列：qwen-image-generation-and-editing-api-reference.md
- 万相图像系列：wan-image-generation-api-reference.md:156、
  text-to-image-v2-api-reference.md:164

未覆盖：adapters/volcengine/image.py 的 Seedream 走方舟 /images/generations，
方舟是否接受 negative_prompt 没有权威文档可查，贸然加字段可能直接 400，故不在本文件断言。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from adapters.registry import default_registry

NEGATIVE = "低分辨率，肢体畸形，手指畸形，文字模糊"

SYNC_IMAGE_MODEL_IDS = ["qwen-image-3.0", "qwen-image-3.0-pro", "wan2.7-image-pro"]


class _FakeResponse:
    def json(self) -> Dict[str, Any]:
        return {
            "output": {
                "choices": [
                    {"message": {"content": [{"image": "https://example.com/out.png"}]}}
                ]
            }
        }


@pytest.fixture()
def captured(monkeypatch):
    """拦截 requests.post，返回一个记录最后一次请求体的容器。"""
    import adapters.dashscope.image_sync as image_sync

    box: Dict[str, Any] = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        box["url"] = url
        box["payload"] = json
        return _FakeResponse()

    monkeypatch.setattr(image_sync.requests, "post", fake_post)
    monkeypatch.setattr(image_sync, "require_api_key", lambda name: "test-key-not-real")
    return box


@pytest.fixture()
def captured_edit(monkeypatch):
    """同 captured，但拦截 adapters/dashscope/image_edit.py 的请求。"""
    import adapters.dashscope.image_edit as image_edit

    box: Dict[str, Any] = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        box["url"] = url
        box["payload"] = json
        return _FakeResponse()

    monkeypatch.setattr(image_edit.requests, "post", fake_post)
    monkeypatch.setattr(image_edit, "require_api_key", lambda name: "test-key-not-real")
    return box


@pytest.mark.parametrize("model_id", SYNC_IMAGE_MODEL_IDS)
class TestNegativePromptForwarding:
    def test_negative_prompt_reaches_parameters(self, captured, model_id) -> None:
        adapter = default_registry().get_adapter(model_id)
        result = adapter.generate(prompt="一只猫", negative_prompt=NEGATIVE)

        assert result.success, result.error
        parameters = captured["payload"]["parameters"]
        assert parameters["negative_prompt"] == NEGATIVE

    def test_absent_negative_prompt_is_not_sent_as_empty_string(self, captured, model_id) -> None:
        adapter = default_registry().get_adapter(model_id)
        result = adapter.generate(prompt="一只猫")

        assert result.success, result.error
        assert "negative_prompt" not in captured["payload"]["parameters"]

    def test_blank_negative_prompt_is_not_sent(self, captured, model_id) -> None:
        adapter = default_registry().get_adapter(model_id)
        result = adapter.generate(prompt="一只猫", negative_prompt="   ")

        assert result.success, result.error
        assert "negative_prompt" not in captured["payload"]["parameters"]


class TestExistingBehaviourPreserved:
    def test_qwen_3_edit_uses_selected_model_and_all_reference_images(self, captured, monkeypatch) -> None:
        import adapters.dashscope.image_sync as image_sync

        monkeypatch.setattr(image_sync, "_encode_image", lambda path: f"data:image/png;base64,{path}")
        adapter = default_registry().get_adapter("qwen-image-3.0")
        result = adapter.generate(
            prompt="换背景", image_path="first", image_paths=["first", "second"], size="1024*1024"
        )

        assert result.success, result.error
        assert captured["payload"]["model"] == "qwen-image-3.0"
        assert captured["payload"]["input"]["messages"][0]["content"] == [
            {"image": "data:image/png;base64,first"},
            {"image": "data:image/png;base64,second"},
            {"text": "换背景"},
        ]

    def test_size_and_prompt_still_sent(self, captured) -> None:
        adapter = default_registry().get_adapter("qwen-image-3.0")
        adapter.generate(prompt="一只猫", size="1280*720", negative_prompt=NEGATIVE)

        payload = captured["payload"]
        assert payload["model"] == "qwen-image-3.0"
        assert payload["parameters"]["size"] == "1280*720"
        assert payload["input"]["messages"][0]["content"][-1] == {"text": "一只猫"}

    def test_endpoint_unchanged(self, captured) -> None:
        adapter = default_registry().get_adapter("qwen-image-3.0")
        adapter.generate(prompt="一只猫")
        assert captured["url"].endswith("/api/v1/services/aigc/multimodal-generation/generation")


@pytest.mark.parametrize("model_id", ["qwen-image-edit-plus", "qwen-image-edit-max"])
class TestImageEditNegativePrompt:
    """qwen-image-edit 官方请求体里 parameters.negative_prompt 是标准字段
    （legacy-qwen-image-models/qwen-image-edit-api.md:302-308），同样不该被丢弃。"""

    def test_negative_prompt_reaches_parameters(self, captured_edit, model_id) -> None:
        adapter = default_registry().get_adapter(model_id)
        result = adapter.generate(prompt="换个背景", image_path=None, negative_prompt=NEGATIVE)

        assert result.success, result.error
        assert captured_edit["payload"]["parameters"]["negative_prompt"] == NEGATIVE

    def test_absent_negative_prompt_is_not_sent(self, captured_edit, model_id) -> None:
        adapter = default_registry().get_adapter(model_id)
        result = adapter.generate(prompt="换个背景")

        assert result.success, result.error
        assert "negative_prompt" not in captured_edit["payload"]["parameters"]
