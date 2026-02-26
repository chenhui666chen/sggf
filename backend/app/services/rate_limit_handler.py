"""
阿里云百炼API限流处理和重试机制

根据阿里云百炼错误码文档实现智能重试和速率控制
"""
import asyncio
import logging
import time
from typing import Optional, Callable, Any, TypeVar
from functools import wraps
import httpx

logger = logging.getLogger(__name__)

T = TypeVar('T')

# 阿里云百炼限流错误码
RATE_LIMIT_ERRORS = {
    'Throttling.RateQuota',
    'Throttling.RateLimit',
    'RateLimitExceeded',
    'QuotaExceeded',
}

# 重试配置
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_DELAY = 1.0  # 初始延迟1秒
DEFAULT_MAX_DELAY = 60.0  # 最大延迟60秒
DEFAULT_BACKOFF_FACTOR = 2.0  # 指数退避因子


class RateLimitError(Exception):
    """限流错误"""
    pass


class RetryableError(Exception):
    """可重试错误"""
    pass


def is_rate_limit_error(exception: Exception) -> bool:
    """
    判断是否为限流错误
    
    Args:
        exception: 异常对象
    
    Returns:
        是否为限流错误
    """
    error_str = str(exception)
    
    # 检查错误码
    for error_code in RATE_LIMIT_ERRORS:
        if error_code in error_str:
            return True
    
    # 检查HTTP状态码
    if isinstance(exception, httpx.HTTPStatusError):
        if exception.response.status_code == 429:
            return True
    
    # 检查错误消息
    if 'rate limit' in error_str.lower() or 'quota' in error_str.lower():
        return True
    
    return False


def is_retryable_error(exception: Exception) -> bool:
    """
    判断是否为可重试错误
    
    Args:
        exception: 异常对象
    
    Returns:
        是否为可重试错误
    """
    # 限流错误可重试
    if is_rate_limit_error(exception):
        return True
    
    # 网络错误可重试
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    
    # HTTP 5xx错误可重试
    if isinstance(exception, httpx.HTTPStatusError):
        if 500 <= exception.response.status_code < 600:
            return True
    
    return False


def calculate_backoff_delay(
    retry_count: int,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
) -> float:
    """
    计算指数退避延迟
    
    Args:
        retry_count: 重试次数
        initial_delay: 初始延迟
        max_delay: 最大延迟
        backoff_factor: 退避因子
    
    Returns:
        延迟时间（秒）
    """
    delay = initial_delay * (backoff_factor ** retry_count)
    return min(delay, max_delay)


async def retry_with_backoff(
    func: Callable[..., Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
) -> T:
    """
    带指数退避的重试装饰器
    
    Args:
        func: 要重试的函数
        max_retries: 最大重试次数
        initial_delay: 初始延迟
        max_delay: 最大延迟
        backoff_factor: 退避因子
        on_retry: 重试回调函数
    
    Returns:
        函数返回值
    
    Raises:
        最后一次重试失败时的异常
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        
        except Exception as e:
            last_exception = e
            
            # 如果是最后一次尝试，不再重试
            if attempt >= max_retries:
                logger.error(
                    f"❌ 重试失败，已达最大重试次数 {max_retries} | "
                    f"最后错误: {type(e).__name__}: {e}"
                )
                raise
            
            # 检查是否为可重试错误
            if not is_retryable_error(e):
                logger.error(
                    f"❌ 不可重试的错误 | "
                    f"类型: {type(e).__name__} | "
                    f"消息: {e}"
                )
                raise
            
            # 计算延迟
            delay = calculate_backoff_delay(
                attempt,
                initial_delay,
                max_delay,
                backoff_factor
            )
            
            # 判断错误类型
            if is_rate_limit_error(e):
                logger.warning(
                    f"⚠️ 限流错误 | "
                    f"重试 {attempt + 1}/{max_retries} | "
                    f"等待 {delay:.1f}秒 | "
                    f"错误: {e}"
                )
            else:
                logger.warning(
                    f"⚠️ 可重试错误 | "
                    f"重试 {attempt + 1}/{max_retries} | "
                    f"等待 {delay:.1f}秒 | "
                    f"错误: {type(e).__name__}: {e}"
                )
            
            # 调用重试回调
            if on_retry:
                try:
                    on_retry(attempt + 1, e, delay)
                except Exception as callback_error:
                    logger.warning(f"⚠️ 重试回调失败: {callback_error}")
            
            # 等待后重试
            await asyncio.sleep(delay)
    
    # 理论上不会执行到这里
    if last_exception:
        raise last_exception


def async_retry_with_backoff(
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
):
    """
    异步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        initial_delay: 初始延迟
        max_delay: 最大延迟
        backoff_factor: 退避因子
        on_retry: 重试回调函数
    
    Returns:
        装饰器函数
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_backoff(
                lambda: func(*args, **kwargs),
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                backoff_factor=backoff_factor,
                on_retry=on_retry
            )
        return wrapper
    return decorator


class RateLimiter:
    """
    速率限制器
    
    用于控制API请求速率，避免触发限流
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        time_window: float = 1.0
    ):
        """
        初始化速率限制器
        
        Args:
            max_requests: 时间窗口内的最大请求数
            time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """
        获取请求许可
        
        如果达到速率限制，会等待直到可以发送请求
        """
        async with self._lock:
            now = time.time()
            
            # 清理过期的请求记录
            self.requests = [
                req_time for req_time in self.requests
                if now - req_time < self.time_window
            ]
            
            # 检查是否达到限制
            if len(self.requests) >= self.max_requests:
                # 计算需要等待的时间
                oldest_request = min(self.requests)
                wait_time = self.time_window - (now - oldest_request)
                
                if wait_time > 0:
                    logger.info(
                        f"🚦 速率限制 | "
                        f"等待 {wait_time:.1f}秒 | "
                        f"当前: {len(self.requests)}/{self.max_requests}"
                    )
                    await asyncio.sleep(wait_time)
            
            # 记录请求时间
            self.requests.append(now)
    
    async def release(self):
        """
        释放请求许可（可选）
        """
        pass


class AdaptiveRateLimiter(RateLimiter):
    """
    自适应速率限制器
    
    根据限流错误自动调整请求速率
    """
    
    def __init__(
        self,
        max_requests: int = 10,
        time_window: float = 1.0,
        min_requests: int = 1,
        adjustment_factor: float = 0.8
    ):
        """
        初始化自适应速率限制器
        
        Args:
            max_requests: 初始最大请求数
            time_window: 时间窗口（秒）
            min_requests: 最小请求数
            adjustment_factor: 调整因子（0-1）
        """
        super().__init__(max_requests, time_window)
        self.min_requests = min_requests
        self.adjustment_factor = adjustment_factor
        self.current_max_requests = max_requests
    
    async def on_rate_limit(self):
        """
        遇到限流时降低请求速率
        """
        async with self._lock:
            new_max = max(
                self.min_requests,
                int(self.current_max_requests * self.adjustment_factor)
            )
            
            if new_max < self.current_max_requests:
                logger.warning(
                    f"📉 降低请求速率 | "
                    f"{self.current_max_requests} -> {new_max} | "
                    f"时间窗口: {self.time_window}秒"
                )
                self.current_max_requests = new_max
    
    async def on_success(self):
        """
        请求成功时逐步提高请求速率
        """
        async with self._lock:
            if self.current_max_requests < self.max_requests:
                new_max = min(
                    self.max_requests,
                    int(self.current_max_requests / self.adjustment_factor)
                )
                
                if new_max > self.current_max_requests:
                    logger.info(
                        f"📈 提高请求速率 | "
                        f"{self.current_max_requests} -> {new_max} | "
                        f"时间窗口: {self.time_window}秒"
                    )
                    self.current_max_requests = new_max
    
    async def acquire(self):
        """
        获取请求许可（使用当前最大请求数）
        """
        async with self._lock:
            now = time.time()
            
            # 清理过期的请求记录
            self.requests = [
                req_time for req_time in self.requests
                if now - req_time < self.time_window
            ]
            
            # 检查是否达到限制
            if len(self.requests) >= self.current_max_requests:
                # 计算需要等待的时间
                oldest_request = min(self.requests)
                wait_time = self.time_window - (now - oldest_request)
                
                if wait_time > 0:
                    logger.info(
                        f"🚦 速率限制 | "
                        f"等待 {wait_time:.1f}秒 | "
                        f"当前: {len(self.requests)}/{self.current_max_requests}"
                    )
                    await asyncio.sleep(wait_time)
            
            # 记录请求时间
            self.requests.append(now)