# DashScope API 速率限制处理改进

## 问题描述

在使用阿里云百炼 DashScope API 时遇到 HTTP 429 速率限制错误：

```
dashscope t2i HTTP 429 (size=1024*768, async=False): 
code=Throttling.RateQuota, 
request_id=bbf68336-d365-487d-85e9-a8490f04d660, 
message=Requests rate limit exceeded, please try again later
```

## 改进内容

### 1. 增加重试机制

#### T2I (Text-to-Image) 重试
- **最大重试次数**: 5 次（从 3 次增加）
- **等待时间策略**: `5 * (retry_count ** 1.5)` 秒，最大 120 秒
- **重试时间表**:
  | 重试次数 | 等待时间 | 累计时间 |
  |---------|---------|---------|
  | 第1次 | 5.0秒 | 5.0秒 |
  | 第2次 | 12.6秒 | 17.6秒 |
  | 第3次 | 25.0秒 | 42.6秒 |
  | 第4次 | 40.0秒 | 82.6秒 |
  | 第5次 | 56.2秒 | 138.8秒 |

#### 轮询任务重试
- **最大重试次数**: 5 次（从 3 次增加）
- **等待时间策略**: `5 * (retry_count ** 1.5)` 秒，最大 120 秒
- **适用场景**: 轮询异步任务状态时遇到 429 错误

#### I2V/T2V (Image/Text-to-Video) 重试
- **最大重试次数**: 5 次（从 3 次增加）
- **等待时间策略**: `5 * (retry_count ** 1.5)` 秒，最大 120 秒
- **适用场景**: 视频生成时遇到 429 错误

#### Qwen-TTS (Text-to-Speech) 重试
- **最大重试次数**: 5 次
- **等待时间策略**: `5 * (retry_count ** 1.5)` 秒，最大 120 秒
- **适用场景**: 语音合成时遇到 429 错误
- **日志输出**: 使用 logger.warning/error 记录重试信息

### 2. 添加日志输出

在所有重试逻辑中添加了详细的日志输出：

```python
print(f"⚠️ DashScope T2I rate limit (429), retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
print(f"⚠️ DashScope task poll rate limit (429), retry {poll_retry_count}/{max_poll_retries}, waiting {wait_time:.1f}s...")
print(f"⚠️ DashScope I2V rate limit, retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
print(f"⚠️ DashScope T2V rate limit, retry {retry_count}/{max_retries}, waiting {wait_time:.1f}s...")
```

### 3. 错误识别

自动识别以下错误类型：
- HTTP 429 状态码 - 速率限制
- HTTP 403 状态码 - 权限/功能不支持
- HTTP 400 状态码 - 内容检查失败
- `Throttling.RateQuota` 错误码
- `Throttling` 关键词
- `RateQuota` 关键词
- `DataInspectionFailed` 错误码
- `inappropriate content` 关键词

### 4. 超时重试

网络超时错误也会自动重试：
- 最多重试 5 次
- 每次重试等待 5 秒

### 5. 自动回退机制

#### 异步模式回退到同步模式

当遇到 HTTP 403 错误且错误消息包含 "asynchronous" 时：
- 自动从异步模式切换到同步模式
- 输出提示信息：`⚠️ DashScope T2I async not supported (403), switching to sync mode...`
- 使用同步模式重新发起请求

#### 内容安全检查

当遇到 HTTP 400 错误且错误代码为 `DataInspectionFailed` 时：
- 输出友好提示：`⚠️ DashScope T2I content check failed (400): Input may contain inappropriate content`
- 提示用户修改提示词以符合内容政策
- 不进行重试（因为内容问题无法通过重试解决）

## 修改的文件

- `adapters/model_adapters.py`
  - `Wan26T2IAdapter._dashscope_text_to_image()`: T2I 重试机制
  - `Wan26T2IAdapter._dashscope_poll_task()`: 轮询任务重试机制
  - `Wan26I2VAdapter._dashscope_i2v_via_video_synthesis()`: I2V 重试机制
  - `Wan26T2VAdapter._dashscope_t2v_via_video_synthesis()`: T2V 重试机制

- `backend/app/services/audiobook/tts_engine.py`
  - `TTSEngine._call_dashscope_qwen_tts()`: Qwen-TTS 重试机制

## 使用说明

### 自动重试

所有 DashScope API 调用现在都会自动处理 429 错误，无需修改调用代码：

```python
# 自动重试，无需额外处理
result = adapter.generate(
    prompt="生成一张图片",
    width=1024,
    height=768
)
```

### 日志监控

当遇到 429 错误时，会在控制台输出重试信息：

```
⚠️ DashScope T2I rate limit (429), retry 1/5, waiting 5.0s...
⚠️ DashScope T2I rate limit (429), retry 2/5, waiting 12.6s...
⚠️ DashScope T2I rate limit (429), retry 3/5, waiting 25.0s...
```

### 配置调整

如果仍然频繁遇到 429 错误，可以调整以下参数：

#### 方法1: 修改重试次数

在 `adapters/model_adapters.py` 中修改 `max_retries` 变量：

```python
max_retries = 10  # 增加到 10 次重试
```

#### 方法2: 修改等待时间

调整等待时间计算公式：

```python
# 更激进的等待时间
wait_time = min(10 * (retry_count ** 2), 180)

# 更保守的等待时间
wait_time = min(3 * retry_count, 60)
```

#### 方法3: 使用速率限制器

确保在初始化适配器时配置了速率限制器：

```python
from adapters.rate_limiter import get_rate_limiter

config = ModelConfig(
    api_key="your-api-key",
    base_url="https://dashscope.aliyuncs.com",
    model_name="wanx-v1",
    max_requests_per_minute=5,  # 每分钟最多 5 个请求
    max_requests_per_day=100,  # 每天最多 100 个请求
    rate_limit_key="WAN_T2I"
)

adapter = Wan26T2IAdapter(config)
```

## 最佳实践

1. **使用队列**: 将任务放入队列，串行执行而不是并发执行
2. **监控日志**: 及时发现 429 错误和重试情况
3. **合理设置速率限制**: 根据实际需求调整 `max_requests_per_minute`
4. **使用缓存**: 对相同或相似的请求使用缓存结果
5. **分批处理**: 将大批量任务分成小批次，间隔执行

## 相关文档

- [阿里云百炼错误码文档](https://help.aliyun.com/zh/model-studio/error-code#rate-limit)
- [阿里云百炼 API 文档](https://help.aliyun.com/zh/model-studio/developer-reference/api-overview)
- [ALIYUN_RATE_LIMIT_SOLUTION.md](./ALIYUN_RATE_LIMIT_SOLUTION.md)
