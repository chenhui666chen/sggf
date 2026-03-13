# 阿里云百炼模型完整指南

## 目录

1. [快速开始](#快速开始)
2. [API密钥配置](#api密钥配置)
3. [模型ID速查表](#模型id速查表)
4. [提示词优化](#提示词优化)
5. [限流处理方案](#限流处理方案)
6. [常用提示词模板](#常用提示词模板)
7. [高级技巧](#高级技巧)
8. [常见问题](#常见问题)

---

## 快速开始

### 第一步：配置API密钥

1. **创建 .env 文件**
   ```bash
   cp .env.example .env
   ```

2. **获取API密钥**
   - 访问阿里云百炼控制台：https://bailian.console.aliyun.com/
   - 开通百炼服务并创建API-KEY
   - 将API-KEY复制到剪贴板

3. **编辑.env文件**
   - 打开项目根目录下的 `.env` 文件
   - 将所有 `your-dashscope-api-key-here` 替换为您的API-KEY
   - 保存文件

4. **验证配置**
   ```bash
   python -c "from adapters.model_adapters import ModelAdapterFactory; ModelAdapterFactory().get_adapter('wan_t2i'); print('ok')"
   ```

### 第二步：运行示例代码

```python
from adapters.model_adapters import ModelAdapterFactory

factory = ModelAdapterFactory()
wan_t2i_adapter = factory.get_adapter("wan_t2i")

result = wan_t2i_adapter.generate(
    prompt="一个年轻女子站在夕阳下的海边，写实风格，电影质感",
    width=1280,
    height=720
)

if result.success:
    print(f"生成的图像: {result.data['image_url']}")
```

---

## API密钥配置

配置以 `.env` 为准，建议：

- 从 `.env.example` 复制生成 `.env`
- 填写 `DASHSCOPE_API_KEY` 以及需要启用的模型 `*_API_KEY/*_BASE_URL/*_MODEL_ID`
- 启动后端后如遇调用失败，以日志/异常信息为准排查

---

## 模型ID速查表

| 模型ID | 模型名称 | 适配器别名 | 主要功能 | 典型用例 |
|--------|---------|-----------|---------|---------|
| **2862677** | 通义万相-文生图 | `wan_t2i` | 文本→图像 | 故事板帧生成、场景视觉化 |
| **2867393** | 通义万相-图生视频 | `wan_i2v` | 图像→视频 | 镜头视频生成、动画制作 |
| **3001146** | 通义万相-文生视频 | `wan_t2v` | 文本→视频 | 完整场景视频生成 |
| **2712576** | 通义万相-图像编辑 | `qwen_image_edit_plus` | 图像编辑 | 视觉优化、风格统一 |
| **2976416** | 通义万相-参考视频生成 | `wan_r2v` | 参考视频→新视频 | 风格迁移、角色一致性 |

---

## 提示词优化

### 阿里云百炼声音公式

```
提示词 = 主体 + 场景 + 运动 + 声音描述（人声/音效/背景音乐）
声音描述 = 人声 + 音效 + 背景音乐
人声 = 角色说话的内容 + 情绪 + 语调 + 语速 + 音色 + 口音
音效 = 音源材质 + 行为 + 环境音
背景音乐 = 背景音乐/配乐 + 风格
```

### 阿里云百炼进阶公式

```
提示词 = 主体（主体描述）+ 场景（场景描述）+ 运动（运动描述）+ 美学控制 + 风格化
```

### 运动关键词映射

| 关键词 | 描述 |
|--------|------|
| 跑 | 快速奔跑，身体前倾，步伐有力 |
| 冲 | 急速冲刺，动作迅猛，气势强烈 |
| 追 | 奋力追逐，速度极快，紧张激烈 |
| 逃 | 仓皇逃窜，动作慌乱，速度极快 |
| 跳 | 跳跃动作，幅度适中，落地轻盈 |
| 飞 | 飞行动作，姿态优雅，速度平稳 |
| 爆 | 爆炸效果，冲击强烈，碎片飞溅 |

---

## 限流处理方案

### 问题：HTTP 429 错误

```
code=Throttling.RateQuota
message=Requests rate limit exceeded, please try again later.
```

### 解决方案

#### 1. 智能重试机制

```python
async def retry_with_backoff(
    func: Callable[..., Any],
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0
) -> T
```

| 重试次数 | 等待时间 | 累计时间 |
|---------|---------|---------|
| 第1次 | 1.0秒 | 1.0秒 |
| 第2次 | 2.0秒 | 3.0秒 |
| 第3次 | 4.0秒 | 7.0秒 |
| 第4次 | 8.0秒 | 15.0秒 |
| 第5次 | 16.0秒 | 31.0秒 |

#### 2. 自适应速率限制器

```python
from app.services.rate_limit_handler import AdaptiveRateLimiter

limiter = AdaptiveRateLimiter(
    max_requests=10,  # 每秒最多10个请求
    time_window=1.0,
    min_requests=1,
    adjustment_factor=0.8
)
```

---

## 常用提示词模板

### 故事板帧生成（模型ID: 2862677）

```python
prompt = """
{scene_description}

风格要求：
- 艺术风格：写实风格，电影质感
- 光照：黄金时刻的暖光，侧逆光
- 构图：三分法构图，主体位于右侧三分之一处
- 色调：暖色调，橙色、金色、蓝色渐变

技术参数：
- 分辨率：1280x720
- 质量等级：high
"""
```

### 镜头视频生成（模型ID: 2867393）

```python
prompt = """
{motion_description}

运动参数：
- 运动类型：缓慢旋转+细微动作
- 运动强度：中等
- 运动方向：从左到右
- 运动速度：慢速
"""
```

---

## 高级技巧

### 批量生成与并发控制

```python
import asyncio
from asyncio import Semaphore

async def batch_generate(prompts, max_concurrent=3):
    factory = ModelAdapterFactory()
    adapter = factory.get_adapter("wan_t2i")
    semaphore = Semaphore(max_concurrent)
    
    async def generate_with_semaphore(prompt):
        async with semaphore:
            return await adapter.generate_async(prompt=prompt)
    
    tasks = [generate_with_semaphore(p) for p in prompts]
    return await asyncio.gather(*tasks)
```

### 缓存机制

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=1000)
def generate_cached(cache_key, prompt, **kwargs):
    factory = ModelAdapterFactory()
    adapter = factory.get_adapter("wan_t2i")
    return adapter.generate(prompt=prompt, **kwargs)
```

---

## 常见问题

### Q1: 如何选择合适的模型？

- **快速预览** → 文生图模型 (2862677)
- **高质量视频** → 图生视频模型 (2867393)
- **完整场景** → 文生视频模型 (3001146)
- **风格统一** → 参考视频生成模型 (2976416)
- **细节优化** → 图像编辑模型 (2712576)

### Q2: 如何降低API调用成本？

1. 使用批量处理减少请求次数
2. 实现缓存机制避免重复调用
3. 合理设置生成参数（分辨率、时长等）
4. 使用降级策略，必要时使用低成本方案

### Q3: 如何处理API调用失败？

1. 实现重试机制（最多5次）
2. 记录详细的错误日志
3. 实现降级方案，使用备用模型
4. 监控API配额，避免超限

---

## 参考资源

- [阿里云百炼平台](https://bailian.console.aliyun.com/)
- [通义万相API文档](https://help.aliyun.com/zh/model-studio/developer-reference/wanxiang-api)
- [文生图API参考](https://help.aliyun.com/zh/model-studio/developer-reference/text-to-image-api-reference)
- [图生视频API参考](https://help.aliyun.com/zh/model-studio/developer-reference/image-to-video-api-reference)
