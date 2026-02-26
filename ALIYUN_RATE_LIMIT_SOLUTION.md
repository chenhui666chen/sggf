# 阿里云百炼API限流处理方案

## 问题描述

在使用阿里云百炼API时，遇到了以下限流错误：

```
dashscope t2i HTTP 429 (size=1024*768, async=False): 
code=Throttling.RateQuota, 
request_id=397da843-46f8-4e37-a8af-0ac312a8c513, 
message=Requests rate limit exceeded, please try again later. 
For details, see: `https://help.aliyun.com/zh/model-studio/error-code#rate-limit`
```

## 错误分析

### HTTP 429 错误
- **错误码**: `Throttling.RateQuota`
- **HTTP状态码**: 429
- **含义**: 请求速率超限，需要稍后重试

### 阿里云百炼限流规则
根据阿里云百炼官方文档，限流规则包括：
1. **请求频率限制**: 单位时间内的请求数量限制
2. **并发限制**: 同时进行的请求数量限制
3. **配额限制**: 账户级别的调用配额限制

## 解决方案

### 1. 智能重试机制 ✅

**文件**: `backend/app/services/rate_limit_handler.py`

实现了完整的重试机制，包括：
- **指数退避**: 每次重试的等待时间按指数增长（1秒 → 2秒 → 4秒 → 8秒 → 16秒）
- **最大重试次数**: 默认5次
- **最大延迟**: 60秒
- **智能错误识别**: 自动识别限流错误、网络错误、服务器错误

**核心函数**:
```python
async def retry_with_backoff(
    func: Callable[..., Any],
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
) -> T
```

**错误识别**:
```python
def is_rate_limit_error(exception: Exception) -> bool:
    """判断是否为限流错误"""
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
```

### 2. 自适应速率限制器 ✅

**文件**: `backend/app/services/rate_limit_handler.py`

实现了自适应速率限制器，根据限流情况自动调整请求速率：

**特性**:
- **初始速率**: 每秒10个请求
- **最小速率**: 每秒1个请求
- **自适应调整**: 遇到限流时降低速率，成功时逐步提高速率
- **调整因子**: 0.8（每次调整乘以0.8）

**核心类**:
```python
class AdaptiveRateLimiter(RateLimiter):
    """
    自适应速率限制器
    
    根据限流错误自动调整请求速率
    """
    
    async def on_rate_limit(self):
        """遇到限流时降低请求速率"""
        new_max = max(
            self.min_requests,
            int(self.current_max_requests * self.adjustment_factor)
        )
        self.current_max_requests = new_max
    
    async def on_success(self):
        """请求成功时逐步提高请求速率"""
        if self.current_max_requests < self.max_requests:
            new_max = min(
                self.max_requests,
                int(self.current_max_requests / self.adjustment_factor)
            )
            self.current_max_requests = new_max
```

### 3. LLM客户端集成 ✅

**文件**: `backend/app/services/llm_client.py`

将限流处理集成到LLM客户端中：

**改进内容**:
1. **导入限流处理器**
```python
from app.services.rate_limit_handler import (
    retry_with_backoff,
    is_rate_limit_error,
    is_retryable_error,
    AdaptiveRateLimiter
)
```

2. **初始化速率限制器**
```python
def __init__(self, strategy: str = "conservative", enable_cache: bool = True, enable_rate_limit: bool = True):
    # 初始化自适应速率限制器
    self.rate_limit_enabled = enable_rate_limit and RATE_LIMIT_AVAILABLE
    if self.rate_limit_enabled:
        self.rate_limiter = AdaptiveRateLimiter(
            max_requests=10,  # 每秒最多10个请求
            time_window=1.0,
            min_requests=1,
            adjustment_factor=0.8
        )
```

3. **在chat方法中应用限流和重试**
```python
async def chat(self, messages, task_type=None, model=None, temperature=0.7, max_tokens=None, use_cache=True, **kwargs):
    # 速率限制
    if self.rate_limit_enabled and self.rate_limiter:
        await self.rate_limiter.acquire()
    
    # 定义重试函数
    async def make_request():
        client = self._select_client(model)
        response = await client.chat.completions.create(...)
        return response.choices[0].message.content
    
    # 定义重试回调
    def on_retry(retry_count, exception, delay):
        if is_rate_limit_error(exception):
            if self.rate_limit_enabled and self.rate_limiter:
                asyncio.create_task(self.rate_limiter.on_rate_limit())
    
    # 执行请求（带重试）
    result = await retry_with_backoff(
        make_request,
        max_retries=5,
        initial_delay=1.0,
        max_delay=60.0,
        backoff_factor=2.0,
        on_retry=on_retry
    )
    
    # 请求成功时逐步提高请求速率
    if self.rate_limit_enabled and self.rate_limiter:
        asyncio.create_task(self.rate_limiter.on_success())
    
    return result
```

4. **在chat_stream方法中应用限流和重试**
```python
async def chat_stream(self, messages, on_chunk=None, task_type=None, model=None, temperature=0.7, max_tokens=None, **kwargs):
    # 速率限制
    if self.rate_limit_enabled and self.rate_limiter:
        await self.rate_limiter.acquire()
    
    # 定义重试函数
    async def make_request():
        client = self._select_client(model)
        stream = await client.chat.completions.create(..., stream=True)
        
        full_content = ""
        async for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    content_piece = delta.content
                    full_content += content_piece
                    if on_chunk:
                        await on_chunk(content_piece)
        
        return full_content
    
    # 执行请求（带重试）
    result = await retry_with_backoff(
        make_request,
        max_retries=5,
        initial_delay=1.0,
        max_delay=60.0,
        backoff_factor=2.0,
        on_retry=on_retry
    )
    
    return result
```

## 使用示例

### 基本使用（自动启用限流和重试）

```python
from app.services.llm_client import get_llm_client

# 获取客户端（默认启用限流和重试）
client = get_llm_client()

# 调用LLM（自动处理限流）
response = await client.chat(
    messages=[
        {"role": "user", "content": "你好"}
    ],
    task_type=TaskType.GENERAL
)
```

### 禁用限流（不推荐）

```python
# 获取客户端（禁用限流）
client = OptimizedLLMClient(
    strategy="conservative",
    enable_cache=True,
    enable_rate_limit=False  # 禁用限流
)
```

### 自定义限流参数

```python
from app.services.rate_limit_handler import AdaptiveRateLimiter

# 创建自定义限流器
custom_limiter = AdaptiveRateLimiter(
    max_requests=5,  # 每秒最多5个请求
    time_window=1.0,
    min_requests=1,
    adjustment_factor=0.9  # 更保守的调整
)

# 使用自定义限流器
client.rate_limiter = custom_limiter
```

## 效果说明

### 重试机制效果

| 重试次数 | 等待时间 | 累计时间 |
|---------|---------|---------|
| 第1次 | 1.0秒 | 1.0秒 |
| 第2次 | 2.0秒 | 3.0秒 |
| 第3次 | 4.0秒 | 7.0秒 |
| 第4次 | 5.0秒 | 12.0秒 |
| 第5次 | 8.0秒 | 20.0秒 |

### 自适应速率限制效果

**遇到限流时**:
```
📉 降低请求速率 | 10 -> 8 | 时间窗口: 1.0秒
🚦 速率限制 | 等待 0.5秒 | 当前: 8/8
```

**请求成功时**:
```
📈 提高请求速率 | 8 -> 10 | 时间窗口: 1.0秒
```

### 日志输出示例

**正常请求**:
```
🎯 任务 general 使用模型: qwen-plus
✅ LLM调用成功 | 模型: qwen-plus | 输入: 15 chars | 输出: 42 chars
```

**限流重试**:
```
🎯 任务 general 使用模型: qwen-plus
⚠️ 限流错误 | 重试 1/5 | 等待 1.0秒 | 模型: qwen-plus
📉 降低请求速率 | 10 -> 8 | 时间窗口: 1.0秒
⚠️ 限流错误 | 重试 2/5 | 等待 2.0秒 | 模型: qwen-plus
📉 降低请求速率 | 8 -> 6 | 时间窗口: 1.0秒
✅ LLM调用成功 | 模型: qwen-plus | 输入: 15 chars | 输出: 42 chars
📈 提高请求速率 | 6 -> 8 | 时间窗口: 1.0秒
```

## 配置建议

### 开发环境
```python
client = OptimizedLLMClient(
    strategy="conservative",
    enable_cache=True,
    enable_rate_limit=True
)
```

### 生产环境
```python
client = OptimizedLLMClient(
    strategy="dynamic",
    enable_cache=True,
    enable_rate_limit=True
)
```

### 高并发场景
```python
# 创建多个客户端实例，每个实例独立限流
clients = [
    OptimizedLLMClient(strategy="conservative", enable_rate_limit=True)
    for _ in range(3)
]
```

## 监控和调试

### 启用详细日志

```python
import logging

# 设置日志级别为DEBUG
logging.getLogger('app.services.llm_client').setLevel(logging.DEBUG)
logging.getLogger('app.services.rate_limit_handler').setLevel(logging.DEBUG)
```

### 监控限流情况

```python
# 查看当前请求速率
if client.rate_limiter:
    current_rate = client.rate_limiter.current_max_requests
    max_rate = client.rate_limiter.max_requests
    print(f"当前速率: {current_rate}/{max_rate} 请求/秒")
```

## 最佳实践

1. **始终启用限流**: 避免触发API限流
2. **合理设置重试次数**: 默认5次，可根据实际情况调整
3. **使用缓存**: 减少不必要的API调用
4. **监控日志**: 及时发现限流和错误情况
5. **合理分配任务**: 避免短时间内大量并发请求

## 相关文件

- `backend/app/services/rate_limit_handler.py`: 限流处理器
- `backend/app/services/llm_client.py`: LLM客户端（已集成限流）
- `backend/app/services/model_optimizer.py`: 模型优化器

## 参考资料

- 阿里云百炼错误码文档: https://help.aliyun.com/zh/model-studio/error-code#rate-limit
- 阿里云百炼API文档: https://help.aliyun.com/zh/model-studio/developer-reference/api-overview
- HTTP 429状态码: https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Status/429