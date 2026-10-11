# -*- coding: utf-8 -*-
"""阶段 A 观测：generate_chapter_streaming 外层 LLM 尝试计数（含 StreamingService 本层重试）。

验证 on_llm_attempt 回调在 generate_with_streaming 的重试循环内每次 chat_stream
发起前被调用一次，使“在线 LLM”计数反映外层真实尝试而非逻辑步骤。
已知限制：该计数不含 ModelHub 单次调用内的 provider fallback 与 adapter/SDK 自身重试
（见 test_provider_fallback_undercount_is_known_limitation）。
"""
import asyncio

from app.services import streaming_service as streaming_module
from app.services.streaming_service import StreamingService


async def _noop_chunk(chunk: str, idx: int) -> None:
    return


async def _instant_sleep(*_args, **_kwargs) -> None:
    # 跳过重试退避等待，保持测试快速
    return


class _FlakyLLMClient:
    """前 fail_times 次调用抛可重试异常，之后成功；记录真实调用次数。"""

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    async def chat_stream(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient timeout")
        return "正文内容"


def _make_service(client: _FlakyLLMClient) -> StreamingService:
    return StreamingService(llm_client=client)


def test_on_llm_attempt_counts_internal_retries(monkeypatch) -> None:
    client = _FlakyLLMClient(fail_times=2)
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m or "qwen-plus")
    monkeypatch.setattr(streaming_module.asyncio, "sleep", _instant_sleep)

    attempts = 0

    def _count() -> None:
        nonlocal attempts
        attempts += 1

    result = asyncio.run(
        service.generate_chapter_streaming(
            prompt="p",
            system_prompt="s",
            on_chunk=_noop_chunk,
            model="qwen-plus",
            max_retries=3,
            on_llm_attempt=_count,
        )
    )

    assert result == "正文内容"
    # 2 次失败 + 1 次成功 = 3 次真实调用；计数必须与真实 chat_stream 次数一致
    assert attempts == 3
    assert client.calls == 3


def test_single_success_counts_once(monkeypatch) -> None:
    client = _FlakyLLMClient(fail_times=0)
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m or "qwen-plus")

    attempts = 0

    def _count() -> None:
        nonlocal attempts
        attempts += 1

    asyncio.run(
        service.generate_chapter_streaming(
            prompt="p",
            system_prompt="s",
            on_chunk=_noop_chunk,
            model="qwen-plus",
            max_retries=3,
            on_llm_attempt=_count,
        )
    )
    assert attempts == 1
    assert client.calls == 1


def test_default_no_callback_does_not_break(monkeypatch) -> None:
    # 未传 on_llm_attempt（默认 None）时行为不变，其余 11+ 调用方不受影响
    client = _FlakyLLMClient(fail_times=0)
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m or "qwen-plus")

    result = asyncio.run(
        service.generate_chapter_streaming(
            prompt="p",
            system_prompt="s",
            on_chunk=_noop_chunk,
            model="qwen-plus",
            max_retries=3,
        )
    )
    assert result == "正文内容"
    assert client.calls == 1


class _ProviderFallbackLLMClient:
    """模拟 ModelHub 在单次 chat_stream 内发生 provider fallback：
    主模型不可用 → 内部切换回退模型 → 成功。对外层 StreamingService 而言
    这只是 1 次 chat_stream 调用，但供应商侧实际发生 2 次请求。"""

    def __init__(self):
        self.outer_calls = 0        # StreamingService 视角的 chat_stream 次数
        self.provider_requests = 0  # 供应商侧真实请求数（含内部 fallback）

    async def chat_stream(self, **kwargs):
        self.outer_calls += 1
        # 模拟 ModelHub 内部：先试主模型（不可用），再 fallback 到回退模型（成功）
        self.provider_requests += 2
        return "正文内容"


def test_provider_fallback_undercount_is_known_limitation(monkeypatch) -> None:
    # 已知限制特征测试：on_llm_attempt 只在 StreamingService 外层重试循环触发，
    # 无法感知 ModelHub 单次调用内的 provider fallback 与 adapter/SDK 自身重试。
    # 因此外层计数=1，而供应商真实请求=2，观测 online_llm_calls 会少算。
    # 本测试锁定该行为，防止误以为流式计数已含 provider fallback；
    # 精确统计须由 ModelHub 逐次回调透传（独立立项，见实施日志 §4）。
    client = _ProviderFallbackLLMClient()
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m or "qwen-plus")

    attempts = 0

    def _count() -> None:
        nonlocal attempts
        attempts += 1

    result = asyncio.run(
        service.generate_chapter_streaming(
            prompt="p",
            system_prompt="s",
            on_chunk=_noop_chunk,
            model="qwen-plus",
            max_retries=3,
            on_llm_attempt=_count,
        )
    )
    assert result == "正文内容"
    assert client.outer_calls == 1
    assert client.provider_requests == 2
    # 外层计数只反映 StreamingService 重试，不含 provider fallback（已知少算）
    assert attempts == 1
