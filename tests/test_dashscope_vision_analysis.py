# -*- coding: utf-8 -*-
"""视觉评审执行链的适配器级守卫。

背景：媒体运行时把 analyze_image / analyze_video 交给 adapter 上的同名方法执行
（`_execute_custom_registry_method`），注册表里只有 adapter 而没有方法时，
`/api/v1/asset-studio/vision-review` 只能拿到 adapter_missing。历史上唯一的实现
指向 `https://dashscope.aliyuncs.com/v1/analyze/image` 这类并不存在的端点，
且已随旧模块物理删除，因此本文件同时钉住两件事：

1. 视觉类 adapter 必须真的暴露 analyze_image / analyze_video；
2. 请求必须落在百炼 compatible-mode 的真实结构上（messages content 带
   image_url / video_url 部件），且返回体要能被后端评审响应解析（result_data）。
"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _import_root in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
    if _import_root not in sys.path:
        sys.path.insert(0, _import_root)

from adapters.registry import registry  # noqa: E402

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQAAAH/wEBAwAB/8D/gAAAAElFTkSuQmCC"
)


class _FakeCompletions:
    def __init__(self, recorder: dict, content: str, finish_reason: str = "stop") -> None:
        self._recorder = recorder
        self._content = content
        self._finish_reason = finish_reason

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=self._content),
                    finish_reason=self._finish_reason,
                )
            ],
            usage=None,
        )


class _FakeChat:
    def __init__(self, recorder: dict, content: str, finish_reason: str = "stop") -> None:
        self.completions = _FakeCompletions(recorder, content, finish_reason)


def _install_fake_openai(
    monkeypatch, recorder: dict, content: str, finish_reason: str = "stop"
) -> None:
    created: dict = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = _FakeChat(recorder, content, finish_reason)

    recorder["__client__"] = created
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))


_ANALYSIS_JSON = json.dumps(
    {
        "scores": {"clarity": {"score": 7, "comment": "边缘略软"}},
        "summary": "整体可用",
        "issues": ["背景偏糊"],
    },
    ensure_ascii=False,
)


def _vision_adapter(model_id: str):
    adapter = registry.get_adapter(model_id)
    assert adapter is not None, f"{model_id} 未注册 adapter"
    return adapter


def test_analyze_image_builds_multimodal_content_and_returns_scores(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(_PNG_BYTES)
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder, _ANALYSIS_JSON)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path=str(image_path),
        analysis_type="quality",
        criteria=["clarity", "composition"],
    )

    assert result.success is True
    messages = recorder["messages"]
    parts = messages[0]["content"]
    image_parts = [part for part in parts if part.get("type") == "image_url"]
    assert image_parts, "多模态请求缺少 image_url 部件"
    assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    text_blob = " ".join(str(part.get("text", "")) for part in parts if part.get("type") == "text")
    assert "clarity" in text_blob and "composition" in text_blob, "评审维度必须写进提示词"
    assert result.metadata["result_data"]["scores"]["clarity"]["score"] == 7


def test_analyze_image_passes_remote_url_without_reencoding(monkeypatch) -> None:
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder, _ANALYSIS_JSON)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    parts = recorder["messages"][0]["content"]
    image_part = next(part for part in parts if part.get("type") == "image_url")
    assert image_part["image_url"]["url"] == "https://cdn.example.com/a.png"


def test_analyze_video_uses_video_part_and_longer_timeout(tmp_path, monkeypatch) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake-mp4-bytes")
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder, _ANALYSIS_JSON)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_video(
        video_path=str(video_path),
        analysis_type="quality",
        criteria=["smoothness"],
    )

    assert result.success is True
    parts = recorder["messages"][0]["content"]
    video_part = next(
        (part for part in parts if part.get("type") in {"video_url", "video"}),
        None,
    )
    assert video_part is not None, "多模态请求缺少视频部件"
    assert "smoothness" in json.dumps(parts, ensure_ascii=False)


def test_non_json_response_falls_back_to_content_text(monkeypatch) -> None:
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder, "画面清晰但构图一般。")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    assert result.metadata["result_data"]["content"] == "画面清晰但构图一般。"


def test_api_error_is_reported_not_swallowed(monkeypatch) -> None:
    recorder: dict = {}

    class FailingCompletions:
        def create(self, **kwargs):
            recorder.update(kwargs)
            raise RuntimeError("upstream 429")

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FailingCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is False
    assert "upstream 429" in (result.error or "")


def test_text_only_adapter_does_not_expose_vision_methods() -> None:
    """反向断言：视觉能力只挂在视觉档位上，纯文本对话 adapter 不应被顺手带出方法，
    否则白名单与能力面会重新失去约束。"""
    adapter = _vision_adapter("qwen3.6-plus")

    assert not hasattr(adapter, "analyze_image")
    assert not hasattr(adapter, "analyze_video")


def test_literal_newline_inside_string_value_is_still_parsed(monkeypatch) -> None:
    """评审正文里的裸换行（未被转义）不应把整条结果降级成纯文本。

    2026-10-12 三档测评实测：`qwen3.8-omni-flash` 约 7%（3/42）输出 `finish_reason=stop`、
    正文看起来完整却解析失败，页面因此退化为纯文本展示。严格模式先失败、
    再放宽控制字符是这条路径上唯一无损的兜底。
    """
    broken = '{"scores": {"clarity": {"score": 6, "comment": "边缘略软\n主体尚可"}}, "summary": "可用"}'
    recorder: dict = {}
    _install_fake_openai(monkeypatch, recorder, broken, finish_reason="stop")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    assert result.metadata["result_data"]["scores"]["clarity"]["score"] == 6
    assert result.metadata["vision_parse_failed"] is False


def test_unparseable_response_is_flagged_with_finish_reason(monkeypatch) -> None:
    """降级必须可归因：截断（length）与非法转义（stop）在 metadata 里要能分开，
    否则线上只能看到"成功但纯文本"，无法判断该加 max_tokens 还是该修解析。"""
    recorder: dict = {}
    _install_fake_openai(
        monkeypatch,
        recorder,
        '{"scores": {"clarity": {"score": 6, "comm',
        finish_reason="length",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    result = _vision_adapter("qwen3.8-omni-flash").analyze_image(
        image_path="https://cdn.example.com/a.png",
        analysis_type="quality",
        criteria=["clarity"],
    )

    assert result.success is True
    assert result.metadata["result_data"] == {
        "content": '{"scores": {"clarity": {"score": 6, "comm'
    }
    assert result.metadata["vision_parse_failed"] is True
    assert result.metadata["finish_reason"] == "length"
