"""样本生成并发化测试（TDD - RED 阶段）

问题背景：`generate_samples_via_llm` 用双层串行 for 循环逐个 await，
实测每样本约 36 秒，8 样本近 5 分钟。而同文件的评估阶段
（`evaluator._evaluate_samples_concurrently`）已有 8 路并发 + 信号量限流，
两者形成明显的效率不对称。

本文件先以失败测试锁定并发化的正确语义，实现前必须先RED。
"""
import asyncio
import time

import pytest

from app.services.prompt_evolution.test_samples import (
    MIN_SAMPLE_TEXT_LENGTH,
    generate_samples_via_llm,
)

_LONG = "夜" * (MIN_SAMPLE_TEXT_LENGTH + 10)


class _ConcurrencyProbe:
    """记录 LLM 调用的时间线，用于观测并发度与顺序稳定性。"""

    def __init__(self, delay: float = 0.05, fail_on: tuple = ()):
        self.delay = delay
        self.fail_on = set(fail_on)
        self.in_flight = 0
        self.max_in_flight = 0
        self.call_order: list = []

    def client(self):
        probe = self

        class FakeClient:
            async def chat(self, **_kwargs):
                probe.in_flight += 1
                probe.max_in_flight = max(probe.max_in_flight, probe.in_flight)
                probe.call_order.append(probe.in_flight)
                # 序号须在 await 前捕获，否则并发下读到的是他人推进后的值
                mine = probe.call_order[-1]
                try:
                    await asyncio.sleep(probe.delay)
                    if mine in probe.fail_on:
                        raise RuntimeError("模拟单样本生成失败")
                    return _LONG
                finally:
                    probe.in_flight -= 1

        return FakeClient()


@pytest.mark.asyncio
async def test_generation_runs_concurrently(monkeypatch):
    """核心诉求：多个样本必须并行生成，而不是排队等待。

    串行实现下 max_in_flight 恒为 1；并发后应大于 1。
    8 样本 × 0.05s 延迟下，并发实现的墙钟时间应远小于串行的0.4s。
    """
    probe = _ConcurrencyProbe(delay=0.05)
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    started = time.perf_counter()
    generated = await generate_samples_via_llm(genres=["玄幻"], count_per_genre=8)
    elapsed = time.perf_counter() - started

    assert len(generated) == 8
    assert probe.max_in_flight > 1, (
        f"样本生成仍是串行（max_in_flight={probe.max_in_flight}），"
        f"未获得并发收益"
    )
    # 串行至少需要 8 × 0.05 = 0.4s；并发后应显著更快
    assert elapsed < 0.35, f"墙钟耗时 {elapsed:.3f}s，仍接近串行水平"


@pytest.mark.asyncio
async def test_concurrency_is_bounded_by_semaphore(monkeypatch):
    """并发必须有上限，避免把 LLM 接口打爆导致限流。

    StepFun 阶梯模型限速并发上限 5，与 evaluator 的 MODEL_MAX_CONCURRENCY
    保持同一口径（这里按 step=4 断言）。
    """
    probe = _ConcurrencyProbe(delay=0.05)
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    await generate_samples_via_llm(genres=["玄幻"], count_per_genre=16)

    assert probe.max_in_flight <= 4, (
        f"并发上限失控：max_in_flight={probe.max_in_flight}，会触发上游限流"
    )


@pytest.mark.asyncio
async def test_sample_ids_are_unique_under_concurrency(monkeypatch):
    """并发下 sample_id 必须唯一——否则样本互相覆盖，评估结果失真。"""
    probe = _ConcurrencyProbe(delay=0.02)
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    generated = await generate_samples_via_llm(
        genres=["玄幻", "都市"], count_per_genre=4
    )

    ids = [s.sample_id for s in generated]
    assert len(ids) == 8
    assert len(set(ids)) == 8, f"并发下sample_id 出现重复：{ids}"


@pytest.mark.asyncio
async def test_created_at_is_consistent_across_batch(monkeypatch):
    """整批样本应共享同一 created_at（批次语义），并发下不得各自取时间。"""
    probe = _ConcurrencyProbe(delay=0.02)
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    generated = await generate_samples_via_llm(genres=["言情"], count_per_genre=6)

    stamps = {s.created_at for s in generated}
    assert len(stamps) == 1, f"批次内created_at 不一致：{stamps}"


@pytest.mark.asyncio
async def test_single_failure_does_not_abort_batch(monkeypatch):
    """单样本失败必须被隔离：其余样本仍应全部生成成功。

    这是并发化最容易引入的缺陷——gather 默认在首个异常时抛出，
    会让整批样本（可能已部分完成）全部丢弃。
    """
    # fail_on=(2,)：第 2 次调用抛异常，其余 4 次正常
    probe = _ConcurrencyProbe(delay=0.02, fail_on=(2,))
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    generated = await generate_samples_via_llm(genres=["悬疑"], count_per_genre=5)

    assert len(generated) == 4, (
        f"单样本失败导致整批丢弃：期望 4 条（5 减 1 条失败），实得 {len(generated)}"
    )


@pytest.mark.asyncio
async def test_multiple_failures_all_isolated(monkeypatch):
    """多个样本同时失败时，其余样本仍应产出，且失败数准确。"""
    probe = _ConcurrencyProbe(delay=0.02, fail_on=(1, 3, 5))
    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: probe.client()
    )

    generated = await generate_samples_via_llm(genres=["都市"], count_per_genre=5)

    assert len(generated) == 2, f"期望 2 条（5 减 3 条失败），实得 {len(generated)}"


@pytest.mark.asyncio
async def test_short_output_still_rejected_under_concurrency(monkeypatch):
    """长度门槛在并发路径下依然生效，不能因重构被绕过。"""

    class FakeClient:
        async def chat(self, **_kwargs):
            return "短" * (MIN_SAMPLE_TEXT_LENGTH - 1)

    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: FakeClient()
    )

    generated = await generate_samples_via_llm(genres=["科幻"], count_per_genre=3)

    assert generated == []


@pytest.mark.asyncio
async def test_genre_metadata_preserved_under_concurrency(monkeypatch):
    """题材/来源等元数据在并发下必须与生成任务正确配对，不能错位。

    并发把「谁对应哪个 prompt」从循环顺序变成了 task 归属，
    一旦传错就会张冠李戴且极难发现。
    """
    from app.services.prompt_evolution.test_samples import SampleSource

    async def genre_of(messages):
        await asyncio.sleep(0.01)
        return messages[1]["content"]

    class FakeClient:
        async def chat(self, messages=None, **_kwargs):
            content = await genre_of(messages)
            genre = "都市" if "都市" in content else (
                "玄幻" if "玄幻" in content else "武侠"
            )
            return f"{genre}正文" + "夜" * MIN_SAMPLE_TEXT_LENGTH

    monkeypatch.setattr(
        "core.unified_llm_client.get_llm_client", lambda: FakeClient()
    )

    generated = await generate_samples_via_llm(
        genres=["玄幻", "都市", "武侠"], count_per_genre=3
    )

    assert len(generated) == 9
    for sample in generated:
        assert sample.text.startswith(f"{sample.genre}正文"), (
            f"题材与正文错位：genre={sample.genre} text[:6]={sample.text[:6]}"
        )
        assert sample.source == SampleSource.AUTO
