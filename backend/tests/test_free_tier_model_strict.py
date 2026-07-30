"""免费档模型严格策略（步骤2）单元测试。

覆盖上线门槛第2条：catalog guard 重路由模拟下 fail closed；
以及多模型评审短路、锁定档位禁止协调器回退、max_retries 透传。
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
for _path in (BACKEND_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

os.environ.setdefault("DEBUG", "false")

from app.services import streaming_service as streaming_module
from app.services.streaming_service import ModelReroutedError, StreamingService
from app.api.v1.workflow import routes_chapter

FLASH = "qwen3.7-flash"


class FakeLLMClient:
    """记录调用参数的假 LLM 客户端。"""

    def __init__(self, *, fail_times: int = 0, content: str = "生成内容"):
        self.calls = []
        self.fail_times = fail_times
        self.content = content

    async def chat_stream(self, *, messages, on_chunk, task_type=None, model=None,
                          temperature=0.7, max_tokens=None, max_retries=1):
        self.calls.append({"model": model, "task_type": task_type})
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("timeout: simulated retryable failure")
        await on_chunk(self.content)
        return self.content


async def _noop_chunk(chunk: str, idx: int) -> None:
    return


def _make_service(client: FakeLLMClient) -> StreamingService:
    return StreamingService(llm_client=client)


# ==================== A. streaming_service 锁定模型守卫 ====================

def test_rerouted_model_raises_when_locked(monkeypatch):
    """锁定档位下模型被 catalog guard 重路由 → 立即抛 ModelReroutedError，不调用 LLM。"""
    client = FakeLLMClient()
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: "qwen3.7-plus")

    with pytest.raises(ModelReroutedError):
        asyncio.run(service.generate_chapter_streaming(
            prompt="p", system_prompt="s", on_chunk=_noop_chunk,
            model=FLASH, max_retries=2, require_exact_model=True,
        ))
    assert client.calls == []


def test_exact_model_passes_when_not_rerouted(monkeypatch):
    """锁定档位下模型解析结果一致 → 正常生成且显式模型透传。"""
    client = FakeLLMClient()
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m)

    result = asyncio.run(service.generate_chapter_streaming(
        prompt="p", system_prompt="s", on_chunk=_noop_chunk,
        model=FLASH, max_retries=2, require_exact_model=True,
    ))
    assert result == "生成内容"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == FLASH


def test_rerouted_model_allowed_when_not_locked(monkeypatch):
    """标准档（require_exact_model=False）保持现状：重路由不报错。"""
    client = FakeLLMClient()
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: "qwen3.7-plus")

    result = asyncio.run(service.generate_chapter_streaming(
        prompt="p", system_prompt="s", on_chunk=_noop_chunk,
        model=FLASH, max_retries=2, require_exact_model=False,
    ))
    assert result == "生成内容"
    assert len(client.calls) == 1


def test_max_retries_limits_total_attempts(monkeypatch):
    """max_retries=2 表示总尝试次数：连续可重试失败 2 次后抛出原始异常。"""
    client = FakeLLMClient(fail_times=10)
    service = _make_service(client)
    monkeypatch.setattr(streaming_module, "resolve_model_for_task", lambda t, m: m)

    async def _instant_sleep(_seconds):
        return

    monkeypatch.setattr(streaming_module.asyncio, "sleep", _instant_sleep)

    with pytest.raises(RuntimeError, match="timeout"):
        asyncio.run(service.generate_chapter_streaming(
            prompt="p", system_prompt="s", on_chunk=_noop_chunk,
            model=FLASH, max_retries=2, require_exact_model=True,
        ))
    assert len(client.calls) == 2


def test_reroute_checked_before_each_attempt(monkeypatch):
    """首次尝试失败后 catalog 状态变化（被重路由）→ 第二次尝试前终止。"""
    client = FakeLLMClient(fail_times=10)
    service = _make_service(client)
    resolve_results = iter([FLASH, FLASH, "qwen3.7-plus"])
    monkeypatch.setattr(
        streaming_module, "resolve_model_for_task",
        lambda t, m: next(resolve_results),
    )

    async def _instant_sleep(_seconds):
        return

    monkeypatch.setattr(streaming_module.asyncio, "sleep", _instant_sleep)

    with pytest.raises(ModelReroutedError):
        asyncio.run(service.generate_chapter_streaming(
            prompt="p", system_prompt="s", on_chunk=_noop_chunk,
            model=FLASH, max_retries=3, require_exact_model=True,
        ))
    assert len(client.calls) == 1


# ==================== B. 评审函数锁定档位行为 ====================

class StubStreamingService:
    """记录 generate_chapter_streaming 调用参数的评审用桩。"""

    def __init__(self, *, fail: bool = False, content: str = "评审报告"):
        self.fail = fail
        self.content = content
        self.calls = []

    async def generate_chapter_streaming(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ModelReroutedError("锁定模型已被重路由")
        return self.content


class StubCoordinator:
    def __init__(self):
        self.review_calls = 0

    def review_chapter(self, **kwargs):
        self.review_calls += 1
        return "协调器回退评审"


def _run_single_review(*, service, coordinator, require_exact_model, review_model=None):
    return asyncio.run(routes_chapter._run_single_next_chapter_streaming_review(
        chapter_draft="草稿", chapter_plan="计划", plot_outline="大纲",
        genre="", next_chapter_number=2, recent_chapter_assets_summary="",
        streaming_service=service, on_review_chunk=_noop_chunk,
        real_coordinator=coordinator,
        review_model=review_model, max_llm_attempts=2,
        require_exact_model=require_exact_model,
    ))


def test_single_review_locked_raises_without_coordinator_fallback():
    """锁定档位评审失败 → 直接抛出，不回退协调器。"""
    service = StubStreamingService(fail=True)
    coordinator = StubCoordinator()
    with pytest.raises(ModelReroutedError):
        _run_single_review(
            service=service, coordinator=coordinator,
            require_exact_model=True, review_model=FLASH,
        )
    assert coordinator.review_calls == 0


def test_single_review_unlocked_falls_back_to_coordinator():
    """标准档评审失败保持现状：回退协调器同步评审。"""
    service = StubStreamingService(fail=True)
    coordinator = StubCoordinator()
    result = _run_single_review(
        service=service, coordinator=coordinator, require_exact_model=False,
    )
    assert result == "协调器回退评审"
    assert coordinator.review_calls == 1


def test_single_review_passes_lock_params():
    """锁定档位评审调用透传 model / max_retries / require_exact_model。"""
    service = StubStreamingService()
    result = _run_single_review(
        service=service, coordinator=StubCoordinator(),
        require_exact_model=True, review_model=FLASH,
    )
    assert result == "评审报告"
    call = service.calls[0]
    assert call["model"] == FLASH
    assert call["max_retries"] == 2
    assert call["require_exact_model"] is True
    assert call["task_type"] == "review"


def _run_quality_review(*, enable_multi_model_review, service):
    return asyncio.run(routes_chapter._run_next_chapter_quality_review(
        project_context={}, chapter_draft="草稿", chapter_plan="计划",
        plot_outline="大纲", genre="", next_chapter_number=2,
        recent_chapter_assets_summary="", streaming_service=service,
        on_review_chunk=_noop_chunk, real_coordinator=StubCoordinator(),
        enable_multi_model_review=enable_multi_model_review,
        review_model=FLASH, max_llm_attempts=2, require_exact_model=True,
    ))


def test_quality_review_free_tier_skips_multi_model_gate(monkeypatch):
    """免费档短路：不触发多模型评审 gate，直接单模型评审。"""
    gate_calls = []

    def _gate(*args, **kwargs):
        gate_calls.append(args)
        return "balanced_3"

    monkeypatch.setattr(routes_chapter, "_resolve_next_chapter_multi_model_review_preset", _gate)
    service = StubStreamingService()

    review_report, review_meta = _run_quality_review(
        enable_multi_model_review=False, service=service,
    )
    assert gate_calls == []
    assert review_report == "评审报告"
    assert review_meta == {}
    assert service.calls[0]["require_exact_model"] is True


def test_quality_review_standard_tier_still_checks_gate(monkeypatch):
    """标准档保持现状：gate 被调用（返回 None 时走单模型评审）。"""
    gate_calls = []

    def _gate(*args, **kwargs):
        gate_calls.append(args)
        return None

    monkeypatch.setattr(routes_chapter, "_resolve_next_chapter_multi_model_review_preset", _gate)
    service = StubStreamingService()

    review_report, _ = _run_quality_review(
        enable_multi_model_review=True, service=service,
    )
    assert len(gate_calls) == 1
    assert review_report == "评审报告"
