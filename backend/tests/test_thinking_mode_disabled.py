"""缺口3：小说主链路思考模式（reasoning）关闭回归测试。

覆盖：
- StreamingService disable_thinking=True 时经 extra_body 透传 thinking 禁用参数
- disable_thinking=False（默认）不附加 extra_body，保持既有行为
- routes_chapter.py 章节规划/重规划/正文调用点均显式启用（静态回归）
- 写后消化 LLM（短 JSON 抽取步）同样关闭思考模式（静态回归）
"""
import asyncio
from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.streaming_service import StreamingService


class _FakeLLMClient:
    """捕获 chat_stream 调用参数的假客户端。"""

    def __init__(self):
        self.captured_kwargs = None

    async def chat_stream(self, **kwargs):
        self.captured_kwargs = kwargs
        return "生成的正文内容"


async def _noop_chunk(chunk_text: str, index: int) -> None:
    return None


@pytest.mark.parametrize("disable_thinking", [True, False])
def test_disable_thinking_controls_extra_body(disable_thinking):
    fake_client = _FakeLLMClient()
    service = StreamingService(llm_client=fake_client)
    content = asyncio.run(
        service.generate_chapter_streaming(
            prompt="写第1章",
            system_prompt="你是小说作者",
            on_chunk=_noop_chunk,
            disable_thinking=disable_thinking,
        )
    )
    assert content == "生成的正文内容"
    kwargs = fake_client.captured_kwargs
    assert kwargs is not None
    if disable_thinking:
        assert kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}
    else:
        assert "extra_body" not in kwargs


def test_routes_chapter_wires_disable_thinking_at_planning_and_content():
    """静态回归：规划、重规划、分段正文、单遍正文四处调用点均关闭思考模式。"""
    routes_path = ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py"
    source = routes_path.read_text(encoding="utf-8")
    assert source.count("disable_thinking=True") >= 4
    service_path = ROOT_DIR / "app" / "services" / "streaming_service.py"
    service_source = service_path.read_text(encoding="utf-8")
    assert "disable_thinking: bool = False" in service_source
    assert '{"thinking": {"type": "disabled"}}' in service_source


def test_digest_llm_disables_thinking():
    """静态回归：写后消化抽取 LLM 经 extra_body 关闭思考模式，
    且 langchain_bridge 的 runtime_options 支持透传至 model_hub.call。"""
    extractor_path = ROOT_DIR / "app" / "services" / "narrative_state_extractor.py"
    source = extractor_path.read_text(encoding="utf-8")
    assert 'extra_body={"thinking": {"type": "disabled"}}' in source
    # 透传链存在：kwargs → runtime_options → model_hub.call(**call_kwargs)
    bridge_path = ROOT_DIR.parent / "core" / "langchain_bridge.py"
    bridge_source = bridge_path.read_text(encoding="utf-8")
    assert "runtime_options=kwargs" in bridge_source
    assert "call_kwargs = {**self.runtime_options, **kwargs}" in bridge_source


def test_routes_chapter_wires_disable_thinking_at_review_and_revision():
    source = (ROOT_DIR / "app" / "api" / "v1" / "workflow" / "routes_chapter.py").read_text(encoding="utf-8")
    review_idx = source.find("task_type=\"review\"")
    assert review_idx > 0
    window = source[review_idx:review_idx + 400]
    assert "disable_thinking=True" in window
    revise_idx = source.find("revised_version = await streaming_service.generate_chapter_streaming(")
    assert revise_idx > 0
    revise_window = source[revise_idx:revise_idx + 700]
    assert "disable_thinking=True" in revise_window
    iter_review_idx = source.find("new_review_report = await streaming_service.generate_chapter_streaming(")
    assert iter_review_idx > 0
    iter_window = source[iter_review_idx:iter_review_idx + 700]
    assert "disable_thinking=True" in iter_window

