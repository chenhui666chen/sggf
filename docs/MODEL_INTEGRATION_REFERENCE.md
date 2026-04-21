# 模型接入参考文档

初版：`2026-04-18`
最近更新：`2026-04-21`

本次更新重点：

- 补充 `UnifiedMediaRuntime` 与媒体 adapter 的统一调用约定
- 补充 Asset Studio 路由层的显式导入规范与输出物化链路约束
- 补充本次调试中验证有效的最小回归测试集合
- 补充长耗时生成请求的可观测性要求

## 1. 目标

本文档用于回答以下高频问题：

- 新模型应该接入哪条链路
- 只改 YAML 是否足够
- 什么时候必须加适配器或包装器
- 接入后应该如何验证
- 不同平台/API 格式的视频模型如何正确适配

适用范围：

- 文本大模型
- 图像 / 视频 / 音频 / 多模态媒体模型
- 仍然依赖旧调用签名的历史兼容路径

## 2. 先看全局：项目里不是一套统一注册系统

当前仓库里至少存在三类模型接入入口：

| 类型 | 主要用途 | 配置文件 | 主要调用链 | 适配器位置 |
| --- | --- | --- | --- | --- |
| 文本 LLM 主链 | 写作、推理、审校、联网校验、LangChain 桥接 | `config/llm_models.yaml` | `UnifiedLLMClient -> ModelHub -> UnifiedModelRegistry -> LLM Adapter` | `core/llm_adapters.py` |
| 媒体智能调度链 | 文生图、图生视频、文生视频、图编、视觉分析、音效生成 | `config/models.yaml` | `IntentParser -> SmartRouter -> ExecutionEngine -> Media Adapter` | `adapters/*.py` |
| 历史兼容层 | 旧业务调用面、旧工厂、旧运行时签名 | 视具体调用面而定 | `ModelAdapterFactory / runtime wrapper / legacy bridge` | `adapters/model_adapters.py`、`adapters/legacy_runtime_wrappers.py` |

结论：

- 不要把 `config/llm_models.yaml` 和 `config/models.yaml` 视为同一套注册中心。
- 同一个 `model_id` 即使同时出现在两份 YAML 中，也不代表两条链路都能真正调用成功。

## 3. 快速判定：新模型该接哪条链

按下面顺序判断即可：

### 3.1 文本 LLM 主链

满足任一条件，优先走文本 LLM 主链：

- 用途是写作、总结、改写、推理、审校、结构化输出
- 调用入口来自 `UnifiedLLMClient`
- 调用入口来自 `ModelHub`
- 调用入口来自 LangChain 兼容桥
- 任务类型类似 `verification`、`outline_expand`、`chapter_batch`、`review`

相关文件：

- `core/unified_llm_client.py`
- `core/model_hub.py`
- `core/unified_registry.py`
- `core/llm_adapters.py`
- `config/llm_models.yaml`

### 3.2 媒体智能调度链

满足任一条件，优先走媒体智能调度链：

- 用途是图像生成、图像编辑、视频生成、图像转视频、视觉分析、音效生成
- 调用入口来自 `SmartRouter`
- 调用入口来自 `ExecutionEngine`
- 调用入口来自 `/api/v1/smart-dispatch/*`
- 任务依赖 `TaskSpec`、模态能力过滤、媒体模型打分与回退

相关文件：

- `core/intent_parser.py`
- `core/router.py`
- `core/execution_engine.py`
- `adapters/registry.py`
- `adapters/base.py`
- `adapters/wanx_adapter.py`
- `adapters/wan26_video_adapter.py`
- `adapters/qwen_multimodal_adapter.py`
- `adapters/new_models_adapters.py`（**新增模型的主要适配器文件**）
- `config/models.yaml`

### 3.3 历史兼容层

只有在以下情况才需要考虑旧兼容层：

- 旧代码显式依赖 `ModelAdapterFactory`
- 旧代码需要历史 `generate(...)` / `chat(...)` / `analyze_image(...)` 签名
- 旧业务仍通过 runtime wrapper 转发到底层模型

相关文件：

- `adapters/model_adapters.py`
- `adapters/legacy_runtime_wrappers.py`
- `adapters/legacy_bridge.py`

## 4. 接入策略总表

### 4.1 文本 LLM 主链

| 情况 | 是否只改 YAML | 需要修改 |
| --- | --- | --- |
| 已有模型 ID，只调整路由、能力、超时、价格、fallback | 可以 | `config/llm_models.yaml` |
| 新增模型 ID，且可复用现有 OpenAI 兼容调用方式 | 通常不可以 | `config/llm_models.yaml` + `core/llm_adapters.py` |
| 新增模型 ID，且需要特殊请求参数、特殊响应解析、特殊重试逻辑 | 不可以 | `config/llm_models.yaml` + `core/llm_adapters.py` 自定义适配器 |

关键说明：

- `UnifiedModelRegistry.load_from_yaml(...)` 只会加载模型 `spec`，不会自动生成 `adapter`。
- `registry.get_adapter(model_id)` 只有在 `core/llm_adapters.py` 中已经注册过适配器类时才会返回实例。
- 因此，"新增文本模型只改 `llm_models.yaml`"在当前架构下通常不成立。

最常见的接入方式：

1. 在 `config/llm_models.yaml` 增加模型配置。
2. 在 `core/llm_adapters.py` 增加一个适配器类。
3. 如果接口完全兼容 OpenAI Chat Completions，很多时候只需要新增一个继承 `OpenAICompatibleAdapter` 的轻量子类。

### 4.2 媒体智能调度链

| 情况 | 是否只改 YAML | 需要修改 |
| --- | --- | --- |
| 已有模型 ID，只调整 metadata、能力、评分、fallback | 可以 | `config/models.yaml` |
| 新增模型 ID，但接口形态与现有内建适配器不完全一致 | 不可以 | `config/models.yaml` + `adapters/*.py` |
| 新增模型 ID，且适配器放在新文件中 | 不可以 | `config/models.yaml` + `adapters/*.py` + `adapters/registry.py` 自动导入列表 |
| 旧调用方还依赖历史工厂或运行时签名 | 不可以 | 额外补 `adapters/model_adapters.py` 或 `adapters/legacy_runtime_wrappers.py` |

关键说明：

- `adapters/registry.py` 会自动导入少量内建适配器模块，再加载 `config/models.yaml`。
- 如果模型在 `models.yaml` 里有 `spec`，但没有任何 `@register_model(...)` 对应适配器，运行时依然会拿不到 adapter。
- 如果你新建了适配器文件，但它没有被自动导入，注册装饰器也不会生效。

最常见的接入方式：

1. 在 `config/models.yaml` 增加模型配置。
2. 在现有 `adapters/*.py` 中复用或新增适配器类。
3. 如果适配器位于新模块，记得把模块加入 `adapters/registry.py` 的自动导入列表。

### 4.3 历史兼容层

| 情况 | 是否需要 | 需要修改 |
| --- | --- | --- |
| 新业务全部走 `ModelHub` 或 registry-backed adapter | 通常不需要 | 无 |
| 旧业务还在用历史适配器工厂 | 可能需要 | `adapters/model_adapters.py` |
| 旧业务还依赖更老的 runtime wrapper 签名 | 可能需要 | `adapters/legacy_runtime_wrappers.py` |

建议：

- 新模型优先接入文本主链或媒体主链。
- 只有在确认存在旧调用点无法迁移时，再补兼容包装层。

## 5. 文件修改参考

### 5.1 文本 LLM 模型

最常见改动组合：

- `config/llm_models.yaml`
- `core/llm_adapters.py`
- 可选：相关测试文件

推荐判断：

- 只是调权重、task_type、fallback、价格、timeout：优先只改 `config/llm_models.yaml`
- 新模型 ID：通常同时改 `config/llm_models.yaml` 和 `core/llm_adapters.py`
- 特殊 API：在 `core/llm_adapters.py` 自定义适配器实现

### 5.2 媒体模型

最常见改动组合：

- `config/models.yaml`
- `adapters/new_models_adapters.py`（**新增模型的首选文件**）
- 可选：`adapters/registry.py`（仅当新建适配器模块时）
- 可选：相关测试文件

推荐判断：

- 只是调整已有模型 metadata：优先只改 `config/models.yaml`
- 新模型 ID 且可复用现有供应商逻辑：改 `config/models.yaml` 并在现有适配器模块中加类
- 新模型 ID 且需要独立模块：额外更新 `adapters/registry.py`

### 5.3 旧兼容调用

最常见改动组合：

- `adapters/model_adapters.py`
- `adapters/legacy_runtime_wrappers.py`
- 可选：`adapters/legacy_bridge.py`

## 6. 媒体适配器架构详解

### 6.1 适配器文件职责划分

| 文件 | 职责 | 典型模型 |
| --- | --- | --- |
| `adapters/wanx_adapter.py` | 旧版万相图片适配器 | wanx 系列旧模型 |
| `adapters/wan26_video_adapter.py` | 旧版万相视频适配器 | wan2.6 旧视频模型 |
| `adapters/qwen_multimodal_adapter.py` | 旧版通义千问多模态适配器 | qwen 旧多模态模型 |
| `adapters/new_models_adapters.py` | **新增模型统一适配器文件** | 36 个已验证模型 |

### 6.2 `new_models_adapters.py` 适配器类层次

该文件按模型类型和 API 平台组织为以下适配器层次：

```
BaseAdapter
├── _SyncImageAdapter          # 百炼同步图片 (qwen-image, wan2.7-image, wan2.6-t2i)
├── _AsyncImageAdapter         # 百炼异步图片 (kling-v3-image, kling-v3-omni-image)
├── _SeedreamImageAdapter      # 火山方舟图片 (doubao-seedream-4-5, doubao-seedream-5-0)
├── _DashScopeChatAdapter      # 百炼对话 (qwen3.5-omni-plus, qwen3.6-plus, qwen3-vl-plus)
├── _VolcengineChatAdapter     # 火山方舟对话 (doubao-seed-2-0-pro, doubao-seed-2-0-lite)
├── _DashScopeTTSAdapter       # 百炼TTS (MiniMax/speech-2.8-turbo, MiniMax/speech-2.8-hd)
├── Qwen3TTSInstructFlashAdapter # 百炼TTS (qwen3-tts-instruct-flash)
├── CosyVoiceV3PlusAdapter     # CosyVoice WebSocket TTS
├── _ImageEditAdapter          # 百炼图片编辑 (qwen-image-edit-plus, qwen-image-edit-max)
├── _DashScopeT2VAdapter       # 百炼文生视频 (wan2.7-t2v, wan2.6-t2v-fast, vidu-q3-pro-text2video)
├── _DashScopeI2VAdapter       # 百炼图生视频 (wan2.7-i2v, wan2.7-r2v, wan2.7-videoedit)
├── _PixverseVideoAdapter      # PixVerse视频 (pixverse-c1-r2v, pixverse-v6-t2v)
├── _ViduVideoAdapter          # Vidu视频 (vidu-q3-pro-img2video, vidu-q3-pro-start-end2video)
├── _KlingVideoAdapter         # Kling视频 (kling-v3-video, kling-v3-omni-video)
├── _SeedanceVideoAdapter      # 火山方舟Seedance视频 (doubao-seedance-2-0, 2-0-fast, 1-5-pro)
├── ViduTiming2AudioAdapter    # Vidu平台音效 (vidu-timing2audio)
└── MurekaO1InstrumentalAdapter # Mureka平台音乐 (mureka-o1-instrumental)
```

### 6.3 API 平台与密钥配置

不同平台的模型使用不同的 API 端点和密钥：

| 平台 | Base URL | 环境变量密钥 | 适用模型 |
| --- | --- | --- | --- |
| 阿里百炼 (DashScope) | `https://dashscope.aliyuncs.com` | `DASHSCOPE_API_KEY` | qwen-image, wan, pixverse, vidu(百炼), kling, MiniMax, cosyvoice, qwen-tts |
| 火山方舟 (Volcengine) | `https://ark.cn-beijing.volces.com/api/v3` | `VOLCENGINE_API_KEY` | doubao-seedream, doubao-seed, doubao-seedance |
| Vidu 平台 | `https://api.vidu.cn` | `VIDU_API_KEY` | vidu-timing2audio（仅音效模型走 Vidu 平台） |
| Mureka 平台 | `https://api.mureka.ai` | `MUREKA_API_KEY` | mureka-o1-instrumental |

重要规则：

- **Vidu 音效模型**走 Vidu 平台 API，其他 Vidu 模型（视频等）走百炼平台用阿里密钥。
- 火山方舟的模型 ID 通常带日期后缀（如 `doubao-seedance-2-0-260128`），注册 ID 与 MODEL_ID 可能不同。
- `.env` 中必须配置对应平台的密钥，否则适配器会在运行时报错。

### 6.4 视频模型 API 格式差异（重要）

百炼平台上的视频模型虽然共用同一个提交端点 `POST /api/v1/services/aigc/video-generation/video-synthesis`，但不同模型的请求体格式差异极大。这是接入视频模型时最容易出错的地方。

#### 6.4.1 文生视频 (T2V)

适用模型：`wan2.7-t2v`、`wan2.6-t2v`、`vidu/viduq3-pro_text2video`、`kling/kling-v3-video-generation`

```json
{
  "model": "wan2.7-t2v",
  "input": { "prompt": "..." },
  "parameters": { "duration": 5, "resolution": "720P" }
}
```

#### 6.4.2 图生视频 - 首帧驱动 (I2V)

适用模型：`wan2.7-i2v`、`kling/kling-v3-omni-video-generation`（图生视频模式）

```json
{
  "model": "wan2.7-i2v",
  "input": {
    "prompt": "...",
    "media": [{ "type": "first_frame", "url": "https://..." }]
  },
  "parameters": { "duration": 5, "resolution": "720P" }
}
```

#### 6.4.3 参考生视频 (R2V)

适用模型：`wan2.7-r2v`

```json
{
  "model": "wan2.7-r2v",
  "input": {
    "prompt": "...",
    "media": [{ "type": "reference_image", "url": "https://..." }]
  },
  "parameters": { "duration": 5, "resolution": "720P" }
}
```

注意：`media.type` 是 `reference_image`，不是 `first_frame`。

#### 6.4.4 视频编辑 (VideoEdit)

适用模型：`wan2.7-videoedit`

```json
{
  "model": "wan2.7-videoedit",
  "input": {
    "prompt": "...",
    "media": [{ "type": "video", "url": "https://..." }]
  },
  "parameters": { "duration": 5, "resolution": "720P" }
}
```

注意：必须传入视频（`type: "video"`），不是图片。

#### 6.4.5 PixVerse 视频

适用模型：`pixverse/pixverse-c1-r2v`、`pixverse/pixverse-v6-t2v`

```json
{
  "model": "pixverse/pixverse-c1-r2v",
  "input": {
    "prompt": "...",
    "media": [{ "type": "image_url", "url": "https://..." }]
  },
  "parameters": { "size": "1280*720", "duration": 5 }
}
```

关键差异：

- `media.type` 是 `image_url`（不是 `first_frame`）
- 分辨率参数用 `parameters.size`（如 `"1280*720"`），不是 `parameters.resolution`（如 `"720P"`）

#### 6.4.6 Vidu 视频（百炼）

适用模型：`vidu/viduq3-pro_img2video`、`vidu/viduq3-pro_start-end2video`

```json
{
  "model": "vidu/viduq3-pro_img2video",
  "input": {
    "prompt": "...",
    "media": [{ "type": "image", "url": "https://..." }]
  },
  "parameters": { "duration": 5, "resolution": "720P" }
}
```

关键差异：

- `media.type` 是 `image`（不是 `first_frame` 或 `image_url`）
- `start-end2video` 需要 2 张图片（首帧 + 尾帧），`media` 数组必须包含 2 个 `type: "image"` 元素

#### 6.4.7 Kling 视频

适用模型：`kling/kling-v3-video-generation`、`kling/kling-v3-omni-video-generation`

```json
{
  "model": "kling/kling-v3-omni-video-generation",
  "input": {
    "prompt": "...",
    "media": [{ "type": "first_frame", "url": "https://..." }]
  },
  "parameters": { "mode": "std", "duration": 5, "aspect_ratio": "16:9" }
}
```

关键差异：

- 图生视频用 `media.type: "first_frame"`（与 wan2.7-i2v 一致）
- 文生视频必须设置 `parameters.aspect_ratio`（如 `"16:9"`）
- 支持 `parameters.mode`（`"std"` 标准模式 / `"pro"` 专业模式）
- omni 模型支持更多 media type：`first_frame`、`last_frame`、`refer`（参考图）、`base`（待编辑视频）、`feature`（特征参考视频）

#### 6.4.8 Seedance 视频（火山方舟）

适用模型：`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128`、`doubao-seedance-1-5-pro-251215`

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    { "type": "text", "text": "..." },
    { "type": "image_url", "image_url": { "url": "https://..." }, "role": "reference_image" },
    { "type": "video_url", "video_url": { "url": "https://..." }, "role": "reference_video" },
    { "type": "audio_url", "audio_url": { "url": "https://..." }, "role": "reference_audio" }
  ],
  "ratio": "16:9",
  "duration": 5,
  "watermark": false,
  "generate_audio": true
}
```

关键差异：

- **不走百炼**，走火山方舟 `/api/v3/contents/generations/tasks` 端点
- 请求体用 `content` 数组，不是 `input`
- 每个素材需要 `role` 字段：`reference_image`、`reference_video`、`reference_audio`
- 分辨率用 `ratio`（如 `"16:9"`），不是 `resolution` 或 `size`
- 支持 `generate_audio: true` 生成有声视频
- 查询端点：`GET /api/v3/contents/generations/tasks/{task_id}`
- 结果在 `content.video_url`

### 6.5 模型 ID 映射规则

注册 ID（`@register_model` 使用的 ID，也是 `config/models.yaml` 中的 ID）与实际调用的 MODEL_ID 可能不同：

| 注册 ID | 实际 MODEL_ID | 原因 |
| --- | --- | --- |
| `wan2.6-t2v-fast` | `wan2.6-t2v` | 百炼上不存在 `wan2.6-t2v-fast` |
| `pixverse-c1-r2v` | `pixverse/pixverse-c1-r2v` | 百炼要求带 `pixverse/` 前缀 |
| `pixverse-v6-t2v` | `pixverse/pixverse-v6-t2v` | 百炼要求带 `pixverse/` 前缀 |
| `vidu-q3-pro-img2video` | `vidu/viduq3-pro_img2video` | 百炼要求带 `vidu/` 前缀，且用下划线 |
| `vidu-q3-pro-text2video` | `vidu/viduq3-pro_text2video` | 同上 |
| `vidu-q3-pro-start-end2video` | `vidu/viduq3-pro_start-end2video` | 同上 |
| `doubao-seedream-4-5` | `doubao-seedream-4-5-251128` | 火山方舟要求带日期后缀 |
| `doubao-seedream-5-0` | `doubao-seedream-5-0-260128` | 同上 |
| `doubao-seed-2-0-pro` | `doubao-seed-2-0-pro-260215` | 同上 |
| `doubao-seed-2-0-lite` | `doubao-seed-2-0-lite-260215` | 同上 |
| `doubao-seedance-2-0` | `doubao-seedance-2-0-260128` | 同上 |
| `doubao-seedance-2-0-fast` | `doubao-seedance-2-0-fast-260128` | 同上 |
| `doubao-seedance-1-5-pro` | `doubao-seedance-1-5-pro-251215` | 同上 |

规则总结：

- 百炼上的 Kling / PixVerse / Vidu 模型需要带供应商前缀（`kling/`、`pixverse/`、`vidu/`）
- 火山方舟的 Doubao 系列模型需要带日期后缀
- 注册 ID 保持简洁可读，实际 MODEL_ID 在适配器类中用 `MODEL_ID` 常量映射

### 6.6 异步任务轮询模式

大部分媒体模型采用异步调用模式：

1. **提交任务**：`POST` 请求创建任务，返回 `task_id`
2. **轮询结果**：`GET` 请求查询任务状态，直到 `SUCCEEDED` 或 `FAILED`

不同平台的轮询端点：

| 平台 | 提交端点 | 查询端点 | 结果字段 |
| --- | --- | --- | --- |
| 百炼 | `POST /api/v1/services/aigc/.../video-synthesis` | `GET /api/v1/tasks/{task_id}` | `output.video_url` |
| 火山方舟(Seedance) | `POST /api/v3/contents/generations/tasks` | `GET /api/v3/contents/generations/tasks/{task_id}` | `content.video_url` |
| 火山方舟(Seedream) | `POST /api/v3/images/generations` | 同步返回 | `data[0].url` |
| Vidu 平台 | `POST /ent/v2/timing2audio` | `GET /ent/v2/tasks/{task_id}/creations` | `creations[0].url` |
| Mureka 平台 | `POST /v1/instrumental/generate` | `GET /v1/instrumental/query/{task_id}` | `output.url` |

注意：

- Vidu 平台域名是 `api.vidu.cn`（不是 `.com`），用错域名会返回 401。
- Mureka 查询端点是 `/v1/instrumental/query/{task_id}`（不是 `/v1/instrumental/{task_id}`）。
- 火山方舟 Seedance 的结果在 `content.video_url`，不是 `video_url`。

### 6.7 `UnifiedMediaRuntime` 适配器调用约定（2026-04-21 补充）

只要媒体模型会被 `core/unified_media_runtime.py` 调用，就必须满足下面的约定。

首选签名：

```python
from adapters.base import GenerationResult
from schemas.task_spec import TaskSpec


def generate(self, task: TaskSpec) -> GenerationResult:
    ...
```

原因：

- `UnifiedMediaRuntime` 的主调用路径是 `adapter.generate(task)`
- `TaskSpec` 已统一承载 prompt、尺寸、时长、引用图/视频、seed、quality、extra 等任务字段
- 统一签名后，能力过滤、fallback、Asset Studio、smart-dispatch 可以共享同一套任务结构

兼容策略：

- 现有历史适配器如果仍是 `generate(prompt, **kwargs)`，运行时兼容层会先把 `TaskSpec` 转成基础类型 kwargs，再调用旧签名
- 兼容层只用于遗留迁移，不建议新增模型继续采用旧签名
- 不要把 `TaskSpec` 实例直接传给 `requests` 的 `json=`、日志序列化或其他 JSON 编码路径，否则会触发 `Object of type TaskSpec is not JSON serializable`

兼容层当前会补齐的常见字段：

- `prompt`
- `negative_prompt`
- `width` / `height` / `size`
- `duration`
- `image_path` / `video_path` / `reference_images`
- `camera_control` / `motion_control`
- `parameters`（视频模型常用 `duration`、`resolution`、`aspect_ratio` 等）

建议：

- 新接入模型优先直接实现 `generate(task)`
- 如果确实要保留旧签名，至少增加一条 `UnifiedMediaRuntime` 兼容回归测试，确认从 `TaskSpec` 到旧 kwargs 的映射符合预期

## 7. 已验证模型清单（2026-04-18）

以下 35 个模型已通过真实 API 调用验证：

### 图片生成 (7)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen-image-2.0` | 百炼 | 4s |
| `qwen-image-2.0-pro` | 百炼 | 9s |
| `wan2.7-image` | 百炼 | 3s |
| `wan2.6-t2i` | 百炼 | 5s |
| `kling/kling-v3-image-generation` | 百炼 | 26s |
| `kling/kling-v3-omni-image-generation` | 百炼 | 15s |
| `doubao-seedream-4-5` / `doubao-seedream-5-0` | 火山方舟 | 9s / 13s |

### 图片编辑 (2)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen-image-edit-plus` | 百炼 | 9s |
| `qwen-image-edit-max` | 百炼 | 26s |

### 对话 / 多模态 (5)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen3.5-omni-plus` | 百炼 | 1.5s |
| `qwen3.6-plus` | 百炼 | 5s |
| `qwen3-vl-plus` | 百炼 | 3.5s |
| `doubao-seed-2-0-pro` | 火山方舟 | 6s |
| `doubao-seed-2-0-lite` | 火山方舟 | 4s |

### TTS (4)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `MiniMax/speech-2.8-turbo` | 百炼 | 1.5s |
| `MiniMax/speech-2.8-hd` | 百炼 | 1.3s |
| `cosyvoice-v3.5-plus` | 百炼 | 0.6s |
| `qwen3-tts-instruct-flash` | 百炼 | 0.7s |

### 视频生成 (15)

| 注册 ID | 类型 | 平台 | 典型延迟 |
| --- | --- | --- | --- |
| `wan2.7-t2v` | 文生视频 | 百炼 | 155s |
| `wan2.6-t2v-fast` | 文生视频 | 百炼 | 52s |
| `wan2.7-i2v` | 图生视频 | 百炼 | 56s |
| `wan2.7-r2v` | 参考生视频 | 百炼 | 218s |
| `wan2.7-videoedit` | 视频编辑 | 百炼 | 364s |
| `pixverse-c1-r2v` | 参考生视频 | 百炼 | 52s |
| `pixverse-v6-t2v` | 文生视频 | 百炼 | 49s |
| `vidu-q3-pro-text2video` | 文生视频 | 百炼 | 124s |
| `vidu-q3-pro-img2video` | 图生视频 | 百炼 | 110s |
| `vidu-q3-pro-start-end2video` | 首尾帧生视频 | 百炼 | 130s |
| `kling/kling-v3-video-generation` | 文生视频 | 百炼 | 42s |
| `kling/kling-v3-omni-video-generation` | 图生视频 | 百炼 | 250s |
| `doubao-seedance-2-0` | 文生视频 | 火山方舟 | 103s |
| `doubao-seedance-2-0-fast` | 文生视频 | 火山方舟 | 119s |
| `doubao-seedance-1-5-pro` | 文生视频 | 火山方舟 | 39s |

### 音频生成 (2)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `vidu-timing2audio` | Vidu 平台 | 18s |
| `mureka-o1-instrumental` | Mureka 平台 | 90s |

## 8. DreamWeaver 特别说明

如果你的目标不是"模型能被某条底层链路调用"，而是"DreamWeaver 能直接用到它"，还要额外判断 DreamWeaver 自己的业务链路。

当前事实：

- 前端主流程走的是 `/api/v1/dreamweaver/*`
- 并不是默认走 `/api/v1/smart-dispatch/*`

因此：

- 即使模型已经接入 `smart-dispatch`，也不代表 DreamWeaver 一定会直接使用它。
- 如果是给 DreamWeaver 接新模型，除了注册中心之外，还要继续追踪 `backend/app/api/v1/dreamweaver.py` 和 DreamWeaver 相关服务的实际调用路径。

### 8.1 DreamWeaver 当前已接通的模型字段（2026-04-18）

- `image_model`：写入 `runtime_config.image_config.adapter`，并由 `agents/painter.py` 的关键帧 / 中间帧执行链优先使用。
- `video_model`：写入 `runtime_config.video_config.adapter`，同时推断 `runtime_config.video_config.engine`。
- `vision_model`：写入 `runtime_config.image_config.vlm_adapter`，并同步到 `runtime_config.qc_config.semantic_vlm_adapter`、`runtime_config.qc_config.state_vlm_adapter`、`runtime_config.qc_config.video_clip_vlm_adapter`。
- `asset_library`：素材库生成链现在也会优先读取 `image_config.adapter` 和 `image_config.vlm_adapter`，不再固定回落到 `wan2.6-t2i` / 环境变量 VLM。
- `library regenerate`：单资产重生会优先读取指定 `run_id` 对应 DreamWeaver run 的 `runtime_config.image_config.adapter`，再回落到默认图像模型。
- `video_edit_model`：写入 `runtime_config.video_edit_config.adapter`，当 `enable_video_edit=true` 且 AutoQC 判断问题适合轻量修补时，会在 `EDIT` 阶段实际调用视频编辑模型对目标 shot 做片段修补。
  DreamWeaver 现在会按问题类型自动选择 `edit_feature`：时序稳定 / 主体一致性类问题优先走 `video-remix`，首尾衔接 / 片段延展类问题优先走 `video-extend`，其余画质修补默认走 `style-transfer`。
- `enable_vision_review`：现在会作为 DreamWeaver 视觉质检总开关，显式 `false` 时会关闭 semantic/state/camera/video-clip QC，显式 `true` 时会种入对应默认值，并驱动 AutoQC 实际执行片段级视觉审核。
- `enable_video_edit`：现在会控制 DreamWeaver 是否允许在返工链路中优先走 `EDIT` 阶段做视频片段修补；如果同一 shot 已尝试过一次视频编辑仍未通过质检，则会自动回退到 `VIDEO` 阶段重生成，避免无限编辑循环。
- `AutoQC video clip review`：DreamWeaver 现在会对采样后的视频片段调用 `analyze_video(...)`；若视觉评分低于阈值且已启用 `video_edit_model` / `enable_video_edit`，会优先路由到 `EDIT` 阶段修补问题片段，否则回到 `VIDEO` 阶段重生成对应 shot。
- `safety audit`：DreamWeaver 现在支持在 `REVIEW` 阶段追加独立视觉安全审核，配置入口位于 `runtime_config.qc_config.enable_safety_audit`、`safety_vlm_adapter`、`safety_fail_policy`。它与 AutoQC 分开存储和决策，不再把"画质返工"和"合规拦截"混成同一条链。
- `run config dialog`：DreamWeaver 前端运行配置弹窗现在已暴露 `enable_safety_audit` 和 `safety_fail_policy`，默认策略为 `warn`。用户可以直接在界面上选择"告警放行"或"严格拦截"，无需再手工改 contract/runtime_config。
- `project locked-config`：`/api/v1/dreamweaver/projects/{project_id}/locked-config` 现在不只返回风格 / 比例 / 分辨率，也会返回 `image_model`、`video_model`、`vision_model`、`video_edit_model` 以及对应开关，前端会同步这些锁定值。

### 8.2 DreamWeaver 下判断"接入成功"要分两层

- 第一层：模型是否已经在注册中心可被找到。
- 第二层：DreamWeaver 请求是否真的把该模型 ID 传到 `runtime_config`，并被对应执行节点消费。
- 只有两层都成立，才算"前端可选、后端可收、执行链会用"。

### 8.3 DreamWeaver 推荐自检顺序

1. 先确认模型注册已经通过：`config/models.yaml`、adapter、registry 全部生效。
2. 再确认请求链路已经透传：前端请求体、`RunRequest`、`_build_dreamweaver_runtime_config_from_request(...)`。
3. 最后确认执行链已经消费：图像主链走 `agents/painter.py`，素材库走 `agents/asset_library.py`，视频走 DreamWeaver 自身 `video_config` 执行链。
4. 如果 `enable_vision_review` 已经开启但执行结果没有变化，优先检查 `runtime_config.qc_config` 是否真的带上了 `enable_video_clip_qc`、`video_clip_vlm_adapter` 和阈值参数；如果是 `video_edit_model` / `enable_video_edit` 没有效果，则继续检查 `rework_route.target_state` 是否已经变成 `EDIT`、`video_edit_plan` 是否写入 payload，以及 `video_edit_attempted_shot_ids` 是否导致本轮被自动回退到 `VIDEO` 重生成。
5. 如果你启用了 `enable_safety_audit`，要额外区分两种结果：`autoqc_failed` 代表画质 / 连贯性返工，`safety_audit_failed` 代表视觉安全阻断。前者仍会走返工路由，后者在 `safety_fail_policy=block` 时会直接在 `REVIEW` 阶段失败，不再回脚本重写。
6. `safety_audit_failed` 现在支持人工复核放行。推荐流程是：先在结果页确认拦截原因，再通过 `POST /api/v1/dreamweaver/runs/{run_id}/safety-audit/approve` 做人工放行。放行后 run 会转为 `completed/DONE`，同时在 `contract.runtime_config.audit.safety_audit` 和最新 `generation_history.result` 中保留 `manual_override` 审计痕迹。
7. 如果项目已经存在历史 run，再检查一次 locked-config 接口与 DreamWeaver 配置弹窗展示值是否一致，确认"项目锁定值"和"界面当前值"没有脱节。

## 9. 标准验证清单

建议按下面顺序验证，不要一上来就测远程生成：

### 9.1 验证适配器注册

```powershell
python -c "from adapters.registry import ModelRegistry; r = ModelRegistry(); r._ensure_builtin_registration(); a = r.get_adapter('your-model-id'); print('adapter =', type(a).__name__ if a else None)"
```

如果输出 `None`，说明适配器没有注册成功，检查：
- `@register_model("your-model-id")` 装饰器是否存在
- 适配器模块是否在 `adapters/registry.py` 的自动导入列表中

### 9.2 验证 spec 加载

```powershell
python -c "from adapters.registry import ModelRegistry; r = ModelRegistry(); r._ensure_builtin_registration(); s = r.get_spec('your-model-id'); print('spec_loaded =', s is not None)"
```

### 9.3 快速 API 格式验证（仅提交，不等待）

对于异步视频模型，先验证 API 格式是否正确（只提交任务获取 task_id，不等待完成）：

```python
import requests, json
from adapters.new_models_adapters import DASHSCOPE_API_KEY, DASHSCOPE_BASE

url = f"{DASHSCOPE_BASE}/api/v1/services/aigc/video-generation/video-synthesis"
headers = {
    "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
    "Content-Type": "application/json",
    "X-DashScope-Async": "enable",
}
payload = {
    "model": "your-model-id",
    "input": {"prompt": "test"},
    "parameters": {"duration": 5}
}
r = requests.post(url, json=payload, headers=headers, timeout=30)
data = r.json()
task_id = data.get("output", {}).get("task_id")
error = data.get("message", "")
print(f"task_id={task_id}, error={error}")
```

如果有 `task_id` 说明格式正确；如果有错误信息，根据错误调整请求格式。

### 9.4 完整真实调用验证

使用测试脚本进行完整验证：

```powershell
# 快速测试（已验证模型）
python scripts/test_all_models.py quick

# 新模型测试
python scripts/test_all_models.py new

# 视频模型测试（需要图片输入的模型会自动使用默认测试图片）
python scripts/test_image_input_models.py
```

### 9.5 重启相关服务

原因：

- 文本主链有 `ModelHub` 单例初始化缓存
- 媒体链有 registry 自动导入与实例缓存

建议至少重启：

- 后端服务
- 相关 worker

### 9.6 最小回归测试基线（2026-04-21 补充）

这次调试暴露的问题，大多不是远程 API 不通，而是本地接入层缺少约束。新增模型或改动 Asset Studio / `UnifiedMediaRuntime` 后，至少执行以下回归：

1. Asset Studio 路由 / helper / 常量绑定回归

```powershell
python -m pytest "backend/tests/test_asset_studio_runtime_constraints.py" -q
```

这组测试用于捕获：

- 路由模块调用了私有 helper 但没有显式导入，例如 `_parse_optional_int`
- `_helpers.py` 中使用了常量或响应类型，但模块命名空间里没有绑定，例如 `DEFAULT_OUTPUT_SUFFIXES`、`MEDIA_KIND_BY_RESULT_KIND`、`AssetStudioGenerateResponse`

2. `UnifiedMediaRuntime` 兼容回归

```powershell
python -m pytest "tests/test_unified_media_runtime.py" -q
```

这组测试用于捕获：

- `generate(task)` 与 `generate(prompt, **kwargs)` 的兼容断裂
- 能力过滤、首选模型重排、fallback 与任务约束不一致
- 旧式 adapter 收到 `TaskSpec` 后误入 JSON 序列化路径

3. `requests` 导入卫生检查

```powershell
python -m pytest "tests/test_requests_import_hygiene.py" -q
```

这组测试用于捕获：

- 适配器文件里使用了 `requests.`，但没有显式 `import requests`

建议补充的快速语法 smoke check：

```powershell
python -m py_compile "backend/app/api/v1/asset_studio_api/routes_video.py"
python -m py_compile "backend/app/api/v1/asset_studio_api/_helpers.py"
```

## 10. 常见误区与踩坑记录

### 10.1 "只要 YAML 里有模型就一定能调用"

不成立。

- 文本主链：YAML 只保证 `spec` 存在，不保证 `adapter` 存在。
- 媒体链：YAML 只保证 metadata 存在，不保证注册装饰器已经执行。

### 10.2 "同一个 model_id 在两份 YAML 中都出现，就表示两条链都能跑"

不成立。

- 两份 YAML 属于不同注册中心。
- 需要分别验证 `spec` 和 `adapter`。

### 10.3 "smart-dispatch 能跑，DreamWeaver 就能跑"

不成立。

- DreamWeaver 当前主流程不是默认走 `smart-dispatch`。

### 10.4 "前端页面没报错，就说明模型接入成功"

不成立。

- 很多接入问题要到后端路由、adapter 实例化或远程调用时才会暴露。

### 10.5 "百炼上的视频模型 API 格式都一样"

不成立。这是接入视频模型时最容易踩的坑。

- 同一个百炼端点，不同模型的 `input.media` 格式完全不同
- `wan2.7-i2v` 用 `first_frame`，`wan2.7-r2v` 用 `reference_image`，PixVerse 用 `image_url`，Vidu 用 `image`
- PixVerse 用 `parameters.size`（`"1280*720"`），其他用 `parameters.resolution`（`"720P"`）
- Kling 文生视频必须设 `aspect_ratio`
- `vidu/viduq3-pro_start-end2video` 必须传 2 张图片

### 10.6 "模型 ID 在百炼控制台看到的就是注册 ID"

不一定。

- 百炼上的 Kling / PixVerse / Vidu 模型需要带供应商前缀
- 火山方舟的 Doubao 模型需要带日期后缀
- 注册 ID 保持简洁，实际 MODEL_ID 在适配器中映射

### 10.7 "Vidu 模型都走 Vidu 平台 API"

不成立。

- 只有 `vidu-timing2audio`（音效模型）走 Vidu 平台 `api.vidu.cn`
- 其他 Vidu 模型（视频等）走百炼平台，用阿里密钥

### 10.8 "异步任务提交成功就等于调用成功"

不成立。

- 提交成功只说明 API 格式正确，任务可能后续执行失败
- 常见失败原因：内容审核（"Output data may contain inappropriate content"）、参数不合法
- 必须轮询到 `SUCCEEDED` 状态才算真正成功

### 10.9 "`from ... import *` 足够用了"

不成立。

- Python 的 `import *` 默认不会导入以下划线开头的私有 helper
- 路由层只要使用 `_parse_optional_int`、`_save_upload_file` 这类私有函数，就必须显式导入
- 新增接入时，不要依赖“某个共享模块已经顺带导入过”
- 对 `backend/app/api/v1/asset_studio_api/routes_*.py` 这类 API 模块，建议显式列出实际使用的 helper

### 10.10 "只要 adapter 能跑，签名是什么无所谓"

不成立。

- 新媒体 adapter 的首选签名应为 `generate(self, task: TaskSpec) -> GenerationResult`
- 旧签名 `generate(prompt, **kwargs)` 只用于历史兼容，不应作为新接入默认方案
- 一旦旧式 adapter 直接收到 `TaskSpec` 并进入 `json=` 或其他序列化路径，就会触发 `TaskSpec is not JSON serializable`
- 如果必须保留旧签名，至少补一条 runtime 兼容回归测试

### 10.11 "`requests` 在别处 import 过，这里就能用"

不成立。

- 只要当前文件出现 `requests.get(...)`、`requests.post(...)` 或 `requests.Session(...)`，就必须在当前文件顶部显式导入 `requests`
- 不要依赖星号导入、间接导入或运行时副作用
- 这类问题非常适合用静态测试一次性兜住，见 `tests/test_requests_import_hygiene.py`

### 10.12 "结果生成链路里缺少常量或类型导入，运行时自然会发现"

这类错误成本很高，应提前避免。

- `asset_studio_api/_helpers.py` 里的输出物化逻辑直接依赖 `DEFAULT_OUTPUT_SUFFIXES`、`MEDIA_KIND_BY_RESULT_KIND`、`AssetStudioMediaAsset`、`AssetStudioGenerateResponse` 等常量与类型
- 这些名称必须在当前模块显式可见，不要假设它们会通过别的模块间接注入
- 任何改动 `_build_response(...)`、`_materialize_output_reference(...)`、`_build_media_asset_from_file(...)` 后，都应该立即跑 `backend/tests/test_asset_studio_runtime_constraints.py`

### 10.13 "生成完成后再记录日志也够用"

对长耗时模型不够用。

- 视频 / 音频 / 异步媒体任务在提交时就应该记录 `accepted` 级别日志，在完成时再记录 `completed` 日志
- 没有入口日志时，用户很容易误判为“前端显示生成中，但后端根本没发请求”
- Asset Studio 这类交互式页面还应该在 loading 态先展示 pending 请求信息，例如模型、模式、提示词摘要或是否带参考图

## 11. TTS 模型接入经验总结（2026-04-20）

本文档记录了 MiniMax、Qwen 与 CosyVoice TTS 接入百炼平台时的实际调试经验。

### 11.1 百炼 TTS 模型公共特性

| 特性 | 说明 |
| --- | --- |
| API 端点 | `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation` |
| 鉴权方式 | `Authorization: Bearer {API_KEY}` |
| Content-Type | `application/json` |
| 超时建议 | 60秒以上 |

#### 11.1.1 CosyVoice 当前接入基线（2026-04-21）

- 当前仓库统一使用 `cosyvoice-v3.5-plus`，不再继续接入 `cosyvoice-v3-plus`
- 任何默认 `model_id`、模型白名单、TTS 引擎默认值、前端模型选项、测试桩都应以 `cosyvoice-v3.5-plus` 为准
- 做替换时不要只改模型 YAML；还要同步检查调用入口、clone / preview 接口、回归测试与文档

### 11.2 MiniMax TTS 接入要点

#### 11.2.1 模型 ID 格式

百炼平台的 MiniMax 模型 ID 必须带 `MiniMax/` 前缀：

| 注册 ID | 实际 MODEL_ID |
| --- | --- |
| `MiniMax/speech-2.8-turbo` | `MiniMax/speech-2.8-turbo` |
| `MiniMax/speech-2.8-hd` | `MiniMax/speech-2.8-hd` |

**常见错误**：使用 `minimax-speech-2.8-turbo`（不带前缀）会导致 "Model not exist" 错误。

#### 11.2.2 请求体格式

MiniMax TTS 使用 `action: tts` 字段：

```json
{
  "input": {
    "action": "tts",
    "text": "要合成的文本",
    "stream": false,
    "voice_setting": {
      "voice_id": "male-qn-qingse",
      "speed": 1.0,
      "vol": 0.8,
      "pitch": 0
    },
    "audio_setting": {
      "sample_rate": 16000,
      "format": "mp3",
      "channel": 1
    }
  },
  "model": "MiniMax/speech-2.8-turbo"
}
```

#### 11.2.3 语音 ID 兼容性

MiniMax 语音 ID 格式与阿里云官方音色列表不完全一致：

- 百炼平台的 MiniMax 音色列表可能与官方 64 音色列表不同
- 某些语音 ID（如 `male-qn-qingse`）可以正常工作
- 建议在 `_call_dashscope_minimax_http` 中实现多种语音格式备选逻辑

```python
# 备选语音格式尝试逻辑示例
voice_formats = [
    original_voice,                    # 原始语音
    voice.replace("female-qn-", "female-"),  # 去掉 qn- 前缀
    voice.replace("male-qn-", "male-"),
    voice.split("-")[-1],              # 只取最后一部分
    "male-qn-qingse",                  # 已知可用的音色兜底
]
```

#### 11.2.4 音频数据格式

MiniMax TTS 返回的音频数据可能是：

| 格式 | 判断方法 | 解码方式 |
| --- | --- | --- |
| 十六进制编码 | 以 `494433` 开头（MP3 文件头 "ID3"） | `bytes.fromhex(audio_data)` |
| Base64 编码 | 其他情况 | `base64.b64decode(audio_data)` |

**关键代码**：

```python
if audio_data.startswith("494433"):
    logger.info("解析到十六进制编码 MP3 数据")
    return bytes.fromhex(audio_data)
else:
    import base64
    logger.info("解析到 base64 音频数据")
    return base64.b64decode(audio_data)
```

### 11.3 Qwen TTS 接入要点

#### 11.3.1 模型 ID

Qwen TTS 使用百炼标准模型 ID：

| 注册 ID | 实际 MODEL_ID |
| --- | --- |
| `qwen3-tts-instruct-flash` | `qwen3-tts-instruct-flash` |

#### 11.3.2 请求体格式

Qwen TTS 的请求体比 MiniMax 简单：

```json
{
  "model": "qwen3-tts-instruct-flash",
  "input": {
    "text": "要合成的文本",
    "voice": "Neil",
    "language_type": "Auto"
  },
  "parameters": {
    "instructions": "用温和但克制的旁白语气讲述，情绪保持轻微紧张。",
    "optimize_instructions": true
  }
}
```

**注意**：不需要 `action: tts` 字段，也不需要 `audio_setting`。

#### 11.3.3 响应格式（关键差异）

Qwen TTS 响应中，音频数据直接在 `output.audio` 字段：

```json
{
  "code": "Success",
  "message": "",
  "request_id": "...",
  "output": {
    "audio": "<base64 编码的音频数据>"
  }
}
```

**错误写法**（假设 audio 是对象）：

```python
# ❌ 错误：假设 audio 是 dict
audio_url = data["output"]["audio"].get("url")
audio_data = data["output"]["audio"].get("data")
```

**正确写法**：

```python
# ✅ 正确：先判断 audio 的类型
audio_info = data["output"]["audio"]

# 直接是 base64 字符串
if isinstance(audio_info, str) and audio_info:
    import base64
    return base64.b64decode(audio_info)

# 是 dict 对象的情况
if isinstance(audio_info, dict):
    audio_url = audio_info.get("url")
    if audio_url:
        # 下载音频
        ...
    audio_data = audio_info.get("data")
    if audio_data:
        import base64
        return base64.b64decode(audio_data)
```

### 11.4 TTS 模型的 Voice ID 管理

#### 11.4.1 VoiceManager 的作用

`VoiceManager` 维护预设音色与 TTS 语音 ID 的映射关系：

```python
# voice_manager.py
PRESET_VOICES = {
    "Neil": {"tts_speaker_id": "Neil", ...},
    "Serena": {"tts_speaker_id": "Serena", ...},
    "male_narrator": {"tts_speaker_id": "Neil", ...},  # 别名
}
```

#### 11.4.2 语音 ID 规范化

不同 TTS 模型可能使用不同的语音 ID 格式：

| 模型 | 语音 ID 示例 |
| --- | --- |
| MiniMax | `male-qn-qingse`, `Chinese (Mandarin)_News_Anchor` |
| Qwen | `Neil`, `Serena`, `Cherry` |

`_normalize_speaker_id` 方法应根据模型类型返回正确的语音 ID。

### 11.5 TTS 预览功能调试清单

当 TTS 预览失败时，按以下顺序排查：

1. **检查模型 ID 格式**
   - [ ] MiniMax 模型是否带 `MiniMax/` 前缀？
   - [ ] Qwen 模型是否为 `qwen3-tts-instruct-flash` 或 `qwen3-tts-plus`？

2. **检查语音 ID**
   - [ ] 选择的语音是否在对应模型的可用列表中？
   - [ ] 是否需要做语音 ID 格式转换？

3. **检查请求体**
   - [ ] MiniMax 是否包含 `action: tts` 字段？
   - [ ] Qwen 是否有 `voice` 和 `language_type` 字段？

4. **检查响应解析**
   - [ ] MiniMax 音频数据是否为十六进制编码？
   - [ ] Qwen 音频数据是否直接在 `output.audio` 字段？

5. **检查 API 端点**
   - [ ] 是否使用 `multimodal-generation/generation` 端点？
   - [ ] 是否排除了旧的 `text2audio/text-to-audio` 端点？

6. **检查环境变量**
   - [ ] `DASHSCOPE_API_KEY` 或 `ALIYUN_API_KEY` 是否已设置？

## 13. 推荐提问方式

后续如果你想让我直接按这份文档帮你判断，可以直接使用类似提示：

```text
请按 docs/MODEL_INTEGRATION_REFERENCE.md 判断：
1. xxx 模型应该接入哪条链
2. 需要修改哪些文件
3. 是否只改 YAML 就够
4. 验证步骤是什么
```

如果你已经准备好一个具体模型，也可以直接这样问：

```text
请按 docs/MODEL_INTEGRATION_REFERENCE.md 分析 qwen-xxx / wan-xxx 的接入方案。
```

## 14. 维护建议

- 新增模型后，优先同步更新本文档的"已验证模型清单"和"常见误区"
- 如果新增的视频模型 API 格式与现有适配器不同，在"视频模型 API 格式差异"章节补充
- 如果发现新的模型 ID 映射规则，在"模型 ID 映射规则"章节补充
- 如果未来把文本与媒体注册中心真正统一，再重写本文档第 2 节和第 4 节
- 如果 DreamWeaver 后续直接接入 `smart-dispatch`，记得同步更新第 8 节
- 如果新增 TTS 模型接入，参考第 11 节"TTS 模型接入经验总结"
