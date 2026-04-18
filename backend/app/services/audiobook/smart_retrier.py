"""
3 级重试机制 - 自动重试失败的 TTS 生成

参考 TextAudio 的智能重试系统：
- 第 1 级：立即重试（网络抖动）
- 第 2 级：延迟重试（API 限流）
- 第 3 级：降级重试（更换参数/模型）

功能：
1. 可配置重试次数和间隔
2. 智能识别失败原因
3. 自动降级策略
"""
import time
import logging
from typing import Optional, Callable, Any, Dict
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class RetryStrategy(str, Enum):
    """重试策略"""
    IMMEDIATE = "immediate"  # 立即重试
    DELAYED = "delayed"  # 延迟重试
    DEGRADED = "degraded"  # 降级重试


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3  # 最大重试次数
    initial_delay: float = 1.0  # 初始延迟（秒）
    backoff_factor: float = 2.0  # 退避因子
    max_delay: float = 30.0  # 最大延迟（秒）
    enable_degraded: bool = True  # 是否启用降级


class RetryResult:
    """重试结果"""

    def __init__(self, success: bool, result: Any = None, error: Optional[Exception] = None,
                 attempt: int = 0, strategy: Optional[RetryStrategy] = None):
        self.success = success
        self.result = result
        self.error = error
        self.attempt = attempt
        self.strategy = strategy


class SmartRetrier:
    """智能重试器"""

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    def execute(
        self,
        func: Callable,
        *args,
        error_context: Optional[Dict[str, Any]] = None,
        fallback_func: Optional[Callable] = None,
        **kwargs,
    ) -> RetryResult:
        """
        执行带重试的函数

        Args:
            func: 要执行的函数
            error_context: 错误上下文信息
            fallback_func: 降级函数（当重试耗尽时调用）
        """
        last_error = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                # 确定重试策略
                if attempt == 1:
                    strategy = RetryStrategy.IMMEDIATE
                elif attempt <= self.config.max_retries - 1:
                    strategy = RetryStrategy.DELAYED
                    self._wait(attempt)
                else:
                    strategy = RetryStrategy.DEGRADED

                # 执行函数
                result = func(*args, **kwargs)

                if result is not None:
                    return RetryResult(
                        success=True,
                        result=result,
                        attempt=attempt,
                        strategy=strategy,
                    )

            except Exception as e:
                last_error = e
                logger.warning(
                    f"⚠️ 第 {attempt}/{self.config.max_retries} 次尝试失败: "
                    f"{type(e).__name__}: {e}"
                )

                # 判断是否应该继续重试
                if not self._should_retry(e, attempt):
                    break

        # 重试耗尽，尝试降级
        if self.config.enable_degraded and fallback_func:
            logger.info(f"🔄 重试耗尽，执行降级策略...")
            try:
                result = fallback_func(*args, **kwargs)
                if result is not None:
                    return RetryResult(
                        success=True,
                        result=result,
                        attempt=self.config.max_retries + 1,
                        strategy=RetryStrategy.DEGRADED,
                    )
            except Exception as e:
                last_error = e

        # 完全失败
        return RetryResult(
            success=False,
            error=last_error,
            attempt=self.config.max_retries,
            strategy=RetryStrategy.DEGRADED,
        )

    def _wait(self, attempt: int):
        """等待退避时间"""
        delay = min(
            self.config.initial_delay * (self.config.backoff_factor ** (attempt - 1)),
            self.config.max_delay,
        )
        logger.info(f"⏳ 等待 {delay:.1f} 秒后重试...")
        time.sleep(delay)

    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """判断是否应该继续重试"""
        if attempt >= self.config.max_retries:
            return False

        error_type = type(error).__name__
        error_msg = str(error).lower()

        # 网络相关错误 - 应该重试
        network_errors = [
            "timeout", "connection", "network", "socket",
            "request", "http", "503", "502", "504", "429",
        ]
        if any(err in error_msg for err in network_errors):
            return True

        # API 限流 - 应该重试
        if "rate limit" in error_msg or "too many requests" in error_msg:
            return True

        # 模型不可用 - 应该重试
        if "model" in error_msg and ("unavailable" in error_msg or "not found" in error_msg):
            return True

        # 认证错误 - 不应该重试
        if "auth" in error_msg or "401" in error_msg or "403" in error_msg:
            return False

        # 参数错误 - 不应该重试
        if "invalid" in error_msg or "bad request" in error_msg:
            return False

        # 默认：继续重试
        return True


# 全局默认实例
default_retrier = SmartRetrier()


def retry_tts_call(func: Callable, *args, **kwargs) -> RetryResult:
    """便捷函数：重试 TTS 调用"""
    return default_retrier.execute(func, *args, **kwargs)
