"""朱雀检测并发闸门与 429 退避测试（TDD - RED 阶段）

问题背景（真实轮次 86cff7f7 取证，非推测）：
  A/B 阶段实测耗时 21 分钟（20:18:40 → 20:39）。核查日志发现该窗口内
  朱雀网关 429 限流告警 23 次、429 相关记录 35 条。而
  `PromptEvaluator.MODEL_MAX_CONCURRENCY = {"step": 4}` 只约束**改写模型**，
  朱雀检测调用完全没有并发闸门：
  - A/B 阶段 4 个候选 × 8 样本 = 32 个检测请求同时打向朱雀；
  - 每次 429 仅 `RATE_LIMIT_BACKOFF_SECONDS = 1.0` 退避、**只重试 1 次**；
  - 重试再失败即返回 success=False，该样本 ratio 缺失 → 判 detect_failed。

  即：瓶颈不是「缺并发」，而是「并发无闸门 + 退避不足」，
  限流失败直接转化为评估数据缺口（这正是 P5 中 detect_failed 的来源）。

本文件先锁定失败语义，实现前必须先 RED。
"""
import asyncio

import pytest

from app.services.zhuque_ai_detect import (
    RateLimitedError,
    ZhuqueAIDetectService,
)


class _Post:
    """可编排的 _post_json 替身：按脚本返回或抛 429。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, url, headers, payload):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            item = self.script[(self.calls - 1) % len(self.script)]
            if isinstance(item, BaseException):
                raise item
            return item
        finally:
            self.in_flight -= 1


def _ok_payload(ai_ratio=0.4):
    """构造一个可被 _parse_response 接受的最小响应体。

    契约来自 `_parse_response`：顶层须 `status == "success"`，
    `labels_ratio` 提供三类占比，`segment_labels` 提供段落真值。
    """
    return {
        "status": "success",
        "msg": "ok",
        "labels_ratio": {"0": 0.5, "1": ai_ratio, "2": 0.1},
        "segment_labels": [],
        "softmax_confidence": 0.9,
    }


def _make_service(post_script):
    svc = ZhuqueAIDetectService()
    svc.gateway_url = "https://example.invalid"
    svc.api_key = "test-key"
    post = _Post(post_script)
    svc._post_json = post
    return svc, post


class TestDetectionConcurrencyGate:
    """朱雀检测必须有独立并发闸门（与改写模型的限流口径分离）。"""

    @pytest.mark.asyncio
    async def test_detection_concurrency_is_bounded(self):
        """32 个并发检测请求不得全部打到网关，必须被闸门拦住。

        没有闸门时 max_in_flight 会等于请求总数，直接触发 429。
        """
        svc, post = _make_service([_ok_payload()])

        await asyncio.gather(*[svc.detect_ai_content("文本" * 500) for _ in range(32)])

        assert post.max_in_flight <= svc.DETECTION_MAX_CONCURRENCY, (
            f"检测并发失控：max_in_flight={post.max_in_flight}，"
            f"上限应为 {svc.DETECTION_MAX_CONCURRENCY}"
        )
        assert post.max_in_flight <= 8, (
            f"检测并发 {post.max_in_flight} 过高，必然触发朱雀 429"
        )

    def test_detection_concurrency_constant_is_separate_from_rewrite(self):
        """检测闸门常量必须独立于改写模型的 MODEL_MAX_CONCURRENCY。

        两者是不同的服务（改写走 LLM 网关，检测走朱雀），
        混用口径会让一方的限流阈值污染另一方。
        """
        from app.services.prompt_evolution.evaluator import PromptEvaluator

        assert ZhuqueAIDetectService.DETECTION_MAX_CONCURRENCY > 0
        # 改写侧限流在 PromptEvaluator 上，检测侧在服务自身，不应共用同一入口
        assert not hasattr(PromptEvaluator, "DETECTION_MAX_CONCURRENCY")


class TestRateLimitBackoff:
    """429 退避必须重试多次并递增，单次 1 秒重试不足以穿过限流窗口。"""

    @pytest.mark.asyncio
    async def test_retries_more_than_once_on_429(self, monkeypatch):
        """前两次 429、第三次成功 → 必须最终成功（现状只重试 1 次会直接失败）。"""
        svc, post = _make_service(
            [RateLimitedError("429"), RateLimitedError("429"), _ok_payload()]
        )
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(svc, "_sleep", fake_sleep, raising=False)

        result = await svc.detect_ai_content("文本" * 500)

        assert result["success"] is True, "两次 429 后仍应重试至成功"
        assert post.calls == 3, f"应重试到第3 次才成功，实调{post.calls} 次"

    @pytest.mark.asyncio
    async def test_backoff_is_increasing(self, monkeypatch):
        """退避时长应递增（指数退避），给限流窗口留出恢复时间。"""
        svc, post = _make_service([RateLimitedError("429")] * 6)
        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(svc, "_sleep", fake_sleep, raising=False)

        await svc.detect_ai_content("文本" * 500)

        assert len(sleeps) >= 3, f"重试次数不足，退避记录 {sleeps}"
        assert sleeps[0] < sleeps[-1], (
            f"退避未递增：{sleeps}。恒定 1 秒重试穿不过限流窗口"
        )

    @pytest.mark.asyncio
    async def test_exhausted_retries_reports_rate_limited(self, monkeypatch):
        """重试耗尽后必须如实标记 rate_limited，供上层判为 detect_failed。"""
        svc, post = _make_service([RateLimitedError("429")] * 10)

        async def fake_sleep(_seconds):
            return None

        monkeypatch.setattr(svc, "_sleep", fake_sleep, raising=False)

        result = await svc.detect_ai_content("文本" * 500)

        assert result["success"] is False
        assert result["rate_limited"] is True, (
            "限流耗尽必须标记 rate_limited=True，否则上层无法区分"
            "「限流」与「检测逻辑错误」，归因会再次失准"
        )
        assert result.get("ai_score") is None

    @pytest.mark.asyncio
    async def test_non_rate_limit_error_not_retried(self, monkeypatch):
        """非 429 错误不应无谓重试——重试只对限流有意义。"""
        svc, post = _make_service([ValueError("响应格式错误")] * 5)

        async def fake_sleep(_seconds):
            return None

        monkeypatch.setattr(svc, "_sleep", fake_sleep, raising=False)

        result = await svc.detect_ai_content("文本" * 500)

        assert post.calls == 1, f"非限流错误不应重试，实调 {post.calls} 次"
        assert result["success"] is False
