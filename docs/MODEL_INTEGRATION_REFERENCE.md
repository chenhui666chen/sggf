# 模型接入参考文档

初版：`2026-04-18`
最近更新：`2026-10-11`

本次更新重点：

- 新增第 12 节：Mureka 音乐链路契约确证（入参只有五个字段、`n` 缺省 2 且按数量计费、终态含 `timeouted`/`cancelled`、水印实测 3 秒、契约单点在 `adapters/_shared.py`）
- 新增 §11.7 / §11.8：Qwen-Audio 3.1 TTS Flash 与 TTS Next（Audiogen）的真实调用契约，含"`voice` 字段被静默忽略""无 duration 入参、按 `output.audio.duration` 结算"
- 新增 §11.11：Qwen-Audio-3.1-ASR-Flash 接入与 Fun-ASR-Flash 退役（那条链路不进注册中心）
- 内部模型 ID 统一为**不含版本号的中性名**，发给上游的真名由 `default_params.request_model` 钉死（见第 6.5 节命名约定）
- 退役模型改为**物理删除**：不再保留 `status: deprecated` 条目，也不保留过渡别名（见第 6.5 节换代台账）
- 媒体适配器已按平台拆包，`adapters/new_models_adapters.py` 只剩向后兼容的再导出（见第 6.1 节）
- 万相视频线收敛为单一现役 ID `wan3.0-video`，第 6.4 节的请求体样例据此重写

上一轮更新（`2026-06-25`）：

- 补充 `UnifiedMediaRuntime` 与媒体 adapter 的统一调用约定
- 补充 Asset Studio 路由层的显式导入规范与输出物化链路约束
- 补充 Asset Studio / DreamWeaver 统一模型清单的事实源与维护入口
- 补充本次调试中验证有效的最小回归测试集合
- 补充长耗时生成请求的可观测性要求
- 补充 `deepseek-flash`（上游旧线名 `deepseek-v4-flash`）与 `deepseek-pro`（上游线名 `deepseek-v4-pro`）从阿里百炼切换到 DeepSeek 官方 API 的接入基线
- 补充豆包 `seed-tts-2.0-expressive` 的 Volcengine Seed Speech 接入基线

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
- `adapters/_shared.py`（API Key、Base URL、轮询等公共常量与工具）
- `adapters/dashscope/*.py`（百炼：`video_wan3` / `video_t2v` / `video_i2v` / `video_kling` / `image_sync` / `image_async` / `image_edit` / `chat` / `multimodal` / `tts`）
- `adapters/volcengine/*.py`（火山方舟：`image` / `chat` / `video` / `tts` / `audio_generation`）
- `adapters/mimo/tts.py`、`adapters/mureka/instrumental.py`、`adapters/vidu_platform/video.py`
- `adapters/new_models_adapters.py`（**仅剩按平台再导出的兼容入口，不再承载实现**）
- `config/models.yaml`

新模型落点规则：按平台写进对应包模块，并把该模块加进 `adapters/registry.py` 的自动导入列表
（`_ensure_builtin_registration()` 的 import 被 `try/except` 包住，模块名写错只会静默不注册）。

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

#### DeepSeek 官方渠道接入基线（2026-06-05，ID 于 2026-10-09 收敛为中性名）

`deepseek-flash` 和 `deepseek-pro` 不再按阿里百炼 DashScope 文本模型处理，应统一按 DeepSeek 官方 OpenAI 兼容接口接入。

| 项目内模型 ID | 官方请求模型 ID | Base URL | 环境变量密钥 | 官方文档 |
| --- | --- | --- | --- | --- |
| `deepseek-flash` | `deepseek-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `https://api-docs.deepseek.com/zh-cn/` |
| `deepseek-pro` | `deepseek-v4-pro` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `https://api-docs.deepseek.com/zh-cn/` |

落地要求：

- `config/llm_models.yaml` 中这两个模型的 `api_config.api_key_env` 应为 `DEEPSEEK_API_KEY`，`api_config.base_url` 应为 `https://api.deepseek.com`。
- `core/llm_adapters.py` 中这两个模型对应的 `@register_llm_model(...)` 参数也要同步使用 `DEEPSEEK_API_KEY` 和 `https://api.deepseek.com`。
- `default_params.request_model` 保持官方模型 ID：`deepseek-flash` 或 `deepseek-v4-pro`；内部 ID 与上游线名不同是设计使然（内部 ID 不带版本号，换代不换 ID）。
- `deepseek-flash` 默认禁用官方思考模式，保留低延迟和 `temperature` 可控性。
- `deepseek-pro` 默认启用官方思考模式并使用 `reasoning_effort=high`，仅用于审校、规划、复杂推理等高价值任务。
- 流式输出、工具调用和严格 JSON 输出场景必须禁用思考模式，避免 `reasoning_content` 回传要求、前端流式消费和 JSON 解析受到影响。
- `documentation_url` / `source_urls` 应指向 DeepSeek 官方文档，不再指向阿里百炼 DeepSeek API 文档。
- `DASHSCOPE_API_KEY`、`DASHSCOPE_API_BASE` 和 `https://dashscope.aliyuncs.com/compatible-mode/v1` 仍保留给 Qwen、Wan、百炼 TTS / 视频等 DashScope 模型，不应用作这两个 DeepSeek 模型的接入渠道。
- 项目内不再保留 DeepSeek 旧版 Chat / Reasoner 模型名；快速通道统一使用 `deepseek-flash`，高强度推理通道统一使用 `deepseek-pro`。
- `deepseek-v4-flash` 已从官方模型列表移除，且**不是本项目任何一层的 ID**：它既未注册，也不在 `core/model_resolution.py` 的 `MODEL_ALIASES` 中（2026-10-09 连同数据库历史改写一并删除）。传旧名会直接报"未注册"并暴露问题，而不是被静默改写成一个用户没选过的模型——静默改写比失败更危险，因为上游对旧名的自动替换行为不可依赖。
- `agents/llm_client.py` 的 `_is_deepseek_official_model` 先归一再匹配，其集合必须持有归一后的 ID（`deepseek-flash` / `deepseek-pro`），否则 DeepSeek 流量会被误路由到 DashScope 并使用错误密钥。

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
- 对应平台包内的适配器模块，如 `adapters/dashscope/image_sync.py`、`adapters/volcengine/video.py`、`adapters/dashscope/video_wan3.py`（**新增模型写进所属平台包**）
- 可选：`adapters/registry.py`（仅当新建适配器模块时，必须加入自动导入清单）
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

### 5.4 Asset Studio / DreamWeaver 模型选项

如果你的目标不只是“模型能被后端调起”，而是“Asset Studio / DreamWeaver 前端可直接选到并回填正确文案”，还要额外更新统一模型清单链路：

- `backend/app/services/asset_studio_model_catalog.py`
- `backend/app/api/v1/asset_studio_api/routes_model_catalog.py`
- `frontend/src/hooks/useAssetStudioModelCatalog.ts`
- `frontend/src/components/home/AssetStudioWorkbench.tsx`
- `frontend/src/pages/DreamWeaverRunPage.tsx`

维护规则：

1. `config/models.yaml` 仍然是媒体模型 metadata 的主事实源。
2. Asset Studio / DreamWeaver 的模型下拉、默认值、时长档位现在优先来自 `/api/v1/asset-studio/model-catalog`。
3. 不要再分别手改多个前端数组作为主入口；前端常量只保留 fallback。
4. 如果“公开模型 ID”和 `config/models.yaml` 中的真实注册 ID 不一致，要同时补 `core/model_resolution.py` 的映射，确保统一清单和运行时都能归一解析。
5. 模型中心列表与详情现在按“当前配置实时投影 + 数据库存验证状态覆盖”返回；也就是说，名称、摘要、约束等基础 metadata 以当前配置为准，数据库主要承载验证状态、来源校验结果与时间戳。
6. 如果你希望把数据库中的模型中心快照也同步到当前集成模型集合，请运行：

```powershell
python -m backend.app.scripts.bootstrap_model_catalog_cards --prune-stale
```

说明：

- 不带 `--prune-stale` 时，会更新当前集成模型并报告数据库里的历史残留卡片，但不会删除它们。
- 带 `--prune-stale` 时，会额外删除已不在当前集成模型集合中的历史卡片，用于测试期或结构调整后的数据库收敛。

## 6. 媒体适配器架构详解

### 6.1 适配器文件职责划分

媒体适配器已按平台拆包（2026-10-09 清点，`@register_model` 全量检索结果）：

| 模块 | 职责 | 现役注册 ID |
| --- | --- | --- |
| `adapters/_shared.py` | API Key / Base URL / 任务轮询等公共常量与工具 | 无注册 |
| `adapters/dashscope/image_sync.py` | 百炼同步图片 | `qwen-image-3.0`、`qwen-image-3.0-pro`、`wan2.7-image-pro` |
| `adapters/dashscope/image_async.py` | 百炼异步图片 | `kling/kling-v3-image-generation`、`kling/kling-v3-omni-image-generation` |
| `adapters/dashscope/image_edit.py` | 百炼图片编辑 | `qwen-image-edit-plus`、`qwen-image-edit-max` |
| `adapters/dashscope/chat.py` | 百炼对话 | `qwen3.6-plus`、`qwen3.5-omni-flash`、`qwen-plus`（视觉评审）、`qwen3.8-omni-flash`（视觉评审，关思考走 `reasoning_effort`） |
| `adapters/_shared_vision_review.py` | 视觉评审执行层（供应商中立，图片/视频质量评审） | 由 `adapters/dashscope/chat.py` 与 `adapters/volcengine/chat.py` 的 mixin 共用；`adapters/dashscope/multimodal.py` 已随视觉线退役整文件删除，评审实现只剩这一处 |
| `adapters/dashscope/tts.py` | 百炼 TTS | `MiniMax/speech-2.8-turbo`、`MiniMax/speech-2.8-hd`、`qwen3-tts-instruct-flash`、`cosyvoice-v3.5-plus` |
| `adapters/dashscope/video_wan3.py` | 万相 3.0 全能参考视频 | `wan3.0-video` |
| `adapters/dashscope/video_i2v.py` | PixVerse 视频 | `pixverse-c1-r2v`、`pixverse-v6-t2v` |
| `adapters/dashscope/video_kling.py` | Kling 视频 | `kling/kling-v3-video-generation`、`kling/kling-v3-omni-video-generation` |
| `adapters/volcengine/image.py` | 火山方舟图片 | `doubao-seedream-5-0-pro`、`doubao-seedream-5-0` |
| `adapters/volcengine/chat.py` | 火山方舟对话与视觉评审（`_VolcengineVisionReviewMixin`） | `doubao-seed-2-1-pro`、`doubao-seed-2-1-lite` |
| `adapters/volcengine/video.py` | 火山方舟 Seedance 视频（`SeedanceProfile` 数据驱动三档差异） | `doubao-seedance-2-5`、`doubao-seedance-2-0`、`doubao-seedance-2-0-fast` |
| `adapters/volcengine/tts.py` / `audio_generation.py` | 火山方舟 TTS 与音效生成 | `seed-tts-2.0-expressive`、`seed-audio-1.0`、`seed-audio-1.0-multilingual` |
| `adapters/mimo/tts.py` | 小米 MiMo TTS | `mimo-v2.5-tts`、`mimo-v2.5-tts-voicedesign`、`mimo-v2.5-tts-voiceclone` |
| `adapters/mureka/instrumental.py` | Mureka 配乐 | `mureka-o1-instrumental` |
| `adapters/vidu_platform/video.py` | Vidu 平台视频 | `vidu-q3-pro-img2video`、`vidu-q3-pro-text2video`、`vidu-q3-pro-start-end2video` |
| `adapters/new_models_adapters.py` | **按平台再导出的兼容入口，不再承载实现** | 无注册 |

已删除的旧适配器模块（不要再引用）：`adapters/wanx_adapter.py`、`adapters/wan26_video_adapter.py`、
`adapters/qwen_multimodal_adapter.py`——三者承担的旧 ID 已随万相 2.6 / 2.7 与通义多模态线退役，
现役实现全部在上面这些包里。

### 6.2 定位某个模型实际由哪个类执行

适配器类名与注册 ID 不是一一映射（存在 `_Base*Adapter` 基类 + 每档一个薄子类的写法，也有同名类跨模块重复），
所以**唯一可靠方式是检索 `@register_model("模型ID")`**：

```powershell
rg -n "@register_model\(" adapters -B1 -A2
```

`adapters/registry.py` 的自动导入清单（`_ensure_builtin_registration()`）决定了哪些模块会被加载，
新增平台模块必须同时加进该清单；该处 import 被 `try/except Exception: pass` 包住，模块缺失或名字写错
只会静默不注册，不会报错。`python scripts/audit_model_references.py` 的结构体检会检查这一项。

### 6.3 API 平台与密钥配置

不同平台的模型使用不同的 API 端点和密钥：

| 平台 | Base URL | 环境变量密钥 | 适用模型 |
| --- | --- | --- | --- |
| 阿里百炼 (DashScope) | `https://dashscope.aliyuncs.com` | `DASHSCOPE_API_KEY` | qwen-image, wan, pixverse, vidu(百炼), kling, MiniMax, cosyvoice, qwen-tts |
| 火山方舟 (Volcengine) | `https://ark.cn-beijing.volces.com/api/v3` | `VOLCENGINE_API_KEY` | doubao-seedream, doubao-seed, doubao-seedance |
| Mureka 平台 | `https://api.mureka.cn` | `MUREKA_API_KEY` | mureka-o1-instrumental（`MUREKA_API_URL` 可覆盖） |

重要规则：

- **Vidu 音效模型**走 Vidu 平台 API，其他 Vidu 模型（视频等）走百炼平台用阿里密钥。
- 火山方舟的模型 ID 通常带日期后缀（如 `doubao-seedance-2-0-260128`），注册 ID 与 MODEL_ID 可能不同。
- `.env` 中必须配置对应平台的密钥，否则适配器会在运行时报错。

### 6.4 视频模型 API 格式差异（重要）

百炼平台上的视频模型虽然共用同一个提交端点 `POST /api/v1/services/aigc/video-generation/video-synthesis`，但不同模型的请求体格式差异极大。这是接入视频模型时最容易出错的地方。

#### 6.4.1 万相视频（`wan3.0-video` 全能参考）

适用模型：`wan3.0-video`。2026-10-08 万相视频线收敛为**单一现役 ID**，文生视频、首帧/首尾帧图生视频、
参考生视频、视频编辑、视频延长五种任务共用同一个请求体，任务类型完全由 `input.media[].type` 与
`parameters` 组合决定。旧 ID `wan2.6-t2v`、`wan2.6-t2v-fast`、`wan2.7-t2v`、`wan2.7-i2v`、`wan2.7-r2v`、
`wan2.7-videoedit` 已从注册中心物理删除，`MODEL_ALIASES` 中也不存在，传旧 ID 会直接报未注册。

```json
{
  "model": "wan3.0-video",
  "input": {
    "prompt": "...",
    "media": [{ "type": "first_frame", "url": "https://..." }]
  },
  "parameters": {
    "resolution": "720P",
    "ratio": "adaptive",
    "duration": 5,
    "audio": false,
    "prompt_extend": true,
    "watermark": false
  }
}
```

素材类型（`adapters/dashscope/video_wan3.py` 逐项强校验）：

- `first_frame` / `last_frame`：各最多 1 张，两者**不能**与 `reference_*` / `file` / `link` 同时出现
- `reference_image` ≤10、`reference_video` ≤5 且总时长 ≤15 秒（需 ≥16fps）、`reference_audio` ≤5 且总时长 ≤15 秒
- `file`（docx/xlsx/pptx/pdf/txt/md 等，≤1 个且 ≤50 页）与 `link`（公开网页，≤1 个）互斥，且两者都要求 `prompt_extend=true`
- **视频编辑的素材类型是 `reference_video`，官方不存在 `type: "video"`**（旧文档写的 `type: "video"` 已作废）
- 视频延长：必须带 `reference_video`，`ratio` 固定 `adaptive`
- `parameters.audio` 是"输出是否带声音"，官方默认 `true`；本项目适配器入参名叫 `audio_output` 而不是 `audio`，
  因为 `core/unified_media_runtime.py` 已把 `kwargs["audio"]` 占用为"音频输入能力需求"并做硬过滤，
  复用该名字会让所有视频模型被过滤掉
- `duration` 接受 `[2, 30]` 任意整数秒或 `-1`（智能时长）；`config/models.yaml` 的 `constraints.duration` 已从档位列表 `[3,5,10,15]` 改成区间 `{min: 2.0, max: 30.0, default: 5.0, supports_auto: true}`，与适配器 `DURATION_MIN/MAX/SMART` 由 `tests/test_dreamweaver_duration_bounds.py` 对拍（七处事实源同步义务见 §10.23）
- `seed` 为 `-1` 或 `[0, 2147483647]`
- `ratio` 与 `resolution` 分列，`resolution` 用大写 P（`720P` / `1080P`），与火山方舟的小写 `720p` 不同

百炼侧仍需注意的历史格式差异（PixVerse / Vidu / Kling 见下三节）：**同一个提交端点，不同供应商的
`media.type` 和分辨率参数名完全不同**，这是接入视频模型最容易出错的地方。

#### 6.4.2 PixVerse 视频

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

#### 6.4.3 Vidu 视频（百炼）

适用模型：`vidu/viduq3-pro_img2video`、`vidu/viduq3-pro_start-end2video`、`vidu/viduq3-pro_text2video`（文生视频只传 `prompt`，不带 `media`）

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

#### 6.4.4 Kling 视频

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

- 图生视频用 `media.type: "first_frame"`（与万相 3.0 的首帧类型同名，但参数体系不同）
- 文生视频必须设置 `parameters.aspect_ratio`（如 `"16:9"`）
- 支持 `parameters.mode`（`"std"` 标准模式 / `"pro"` 专业模式）
- omni 模型支持更多 media type：`first_frame`、`last_frame`、`refer`（参考图）、`base`（待编辑视频）、`feature`（特征参考视频）

#### 6.4.5 Seedance 视频（火山方舟）

适用模型：`doubao-seedance-2-5-260628`、`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128`

> `doubao-seedance-1-5-pro-251215` 已于 2026-10-08 从项目中彻底移除：上游接入点已关闭，
> 实测提交任务返回 400 `InvalidEndpoint.ClosedEndpoint`（同批探测中 `doubao-seedance-2-0-260128`
> 返回正常的参数校验错误、伪造模型名返回 404，可证明确实是接入点关闭而非模型不存在）。

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
  "resolution": "720p",
  "watermark": false,
  "generate_audio": true
}
```

关键差异：

- **不走百炼**，走火山方舟 `/api/v3/contents/generations/tasks` 端点
- 请求体用 `content` 数组，不是 `input`
- 每个素材需要 `role` 字段：`first_frame`、`last_frame`、`reference_image`、`reference_video`、`reference_audio`
- `ratio` 是宽高比（`adaptive` / `21:9` / `16:9` / `4:3` / `1:1` / `3:4` / `9:16`），`resolution` 是清晰度档位，
  两者并存且都用**小写**（`480p` / `720p` / `1080p`，2.0 系列另有 `4k`）
- 支持 `generate_audio: true` 生成有声视频
- 查询端点：`GET /api/v3/contents/generations/tasks/{task_id}`
- 结果在 `content.video_url`（样片阶段在 `content.draft_video_url`）

三档差异（`adapters/volcengine/video.py` 的 `SeedanceProfile` 逐档强校验）：

| 档位 | duration | resolution | 参考素材上限 | draft 样片 | output_format |
| --- | --- | --- | --- | --- | --- |
| `doubao-seedance-2-5` | 4–30 或 -1 | 480p/720p/1080p | 总 50（30 图 + 10 视频 + 10 音频） | 支持 | mp4/mov |
| `doubao-seedance-2-0` | 4–15 或 -1 | 480p/720p/1080p/4k | 总 15（官方未给分类型上限） | 不支持 | mp4 |
| `doubao-seedance-2-0-fast` | 4–15 或 -1 | 480p/720p | 总 15 | 不支持 | mp4 |

任务类型硬规则（2026-10-08 实测，适配器已内建）：

- `first_frame` / `last_frame` 各最多 1 张，且必须在参考素材之前（`content` 顺序即官方指代顺序）
- `first_frame` / `last_frame` 存在时 `ratio` 必须为 `adaptive`
- 视频编辑：必须带 `reference_video`，`ratio=adaptive`、`duration=-1`，且 `omni_reference_task_type=edit`
- 视频延长：必须带 `reference_video`，`ratio=adaptive`，`omni_reference_task_type=extend`
- `omni_reference_task_type`（`auto`/`reference`/`edit`/`extend`）只能与 `reference_*` 素材同时出现，
  纯首尾帧或纯文生传入会被拒
- Draft 两步：Step1 `draft: true` 且 `resolution` 只能 `480p`；Step2 只接受
  `model` + `draft_task` + `resolution=1080p`，其余参数由上游自动复用 Step1，多传即报错；
  draft 任务 ID 有效期 7 天，两步分别计费

### 6.5 模型 ID 映射规则

注册 ID（`@register_model` 使用的 ID，也是 `config/models.yaml` 中的 ID）与实际调用的 MODEL_ID 可能不同：

| 注册 ID | 实际 MODEL_ID | 原因 |
| --- | --- | --- |
| `pixverse-c1-r2v` | `pixverse/pixverse-c1-r2v` | 百炼要求带 `pixverse/` 前缀 |
| `pixverse-v6-t2v` | `pixverse/pixverse-v6-t2v` | 百炼要求带 `pixverse/` 前缀 |
| `vidu-q3-pro-img2video` | `vidu/viduq3-pro_img2video` | 百炼要求带 `vidu/` 前缀，且用下划线 |
| `vidu-q3-pro-text2video` | `vidu/viduq3-pro_text2video` | 同上 |
| `vidu-q3-pro-start-end2video` | `vidu/viduq3-pro_start-end2video` | 同上 |
| `kling-v3-image-generation` | `kling/kling-v3-image-generation` | 统一清单和业务侧沿用短 ID，实际配置记录带 `kling/` 前缀 |
| `doubao-seedream-5-0-pro` | `doubao-seedream-5-0-pro-260628` | 火山方舟要求带日期后缀 |
| `doubao-seedream-5-0` | `doubao-seedream-5-0-260128` | 同上 |
| `doubao-seed-2-1-pro` | `doubao-seed-2-1-pro-260915` | 同上 |
| `doubao-seed-2-1-lite` | `doubao-seed-2-1-lite-260915` | 同上 |
| `doubao-seedance-2-5` | `doubao-seedance-2-5-260628` | 同上 |
| `doubao-seedance-2-0` | `doubao-seedance-2-0-260128` | 同上 |
| `doubao-seedance-2-0-fast` | `doubao-seedance-2-0-fast-260128` | 同上 |

**内部 ID 中性命名约定（2026-10-09 起）**

文本 LLM 与部分媒体模型的内部 ID **不含版本号**，升级换代只改条目内容和适配器快照名，内部 ID 永不换；
发给上游的真名由 `config/llm_models.yaml` 的 `default_params.request_model` 钉死。
因此"内部 ID 与上游线名不一致"是设计使然，不是残留。当前 13 条 LLM 线 + 1 条媒体链双注册：

| 内部 ID | `request_model`（上游线名） | 备注 |
| --- | --- | --- |
| `qwen-plus` | `qwen3.7-plus` | 中文创作主力 |
| `qwen-flash` | `qwen3.7-flash` | 低成本轻量线，免费档强制值 |
| `qwen-flash-fallback` | `qwen3.8-flash` | 仅作 `qwen-flash` 调用失败的回退目标：`routing.task_types` 置空、不进任何用户可选白名单 |
| `deepseek-pro` | `deepseek-v4-pro` | 高强度推理/审校，默认开思考 |
| `deepseek-flash` | `deepseek-flash` | 快速通道，默认禁思考 |
| `glm` | `glm-5.3` | 2026-10-09 由 glm 线上一版原地换代 |
| `kimi-preview` | `kimi/kimi-k2.8-preview` | |
| `mimo-pro` | `mimo-v2.6-pro` | |
| `mimo-flash` | `mimo-v2.6-flash` | |
| `minimax-m` | `MiniMax/MiniMax-M3` | |
| `step-preview` | `step-5-preview` | |
| `doubao-seed-character` | `doubao-seed-character-260628` | |
| `doubao-seed-evolving` | 不设置（自动跟随最新版） | 统一 Model ID，线名本身就是上游入参 |
| `mureka-o1-instrumental` | 不设置 | 媒体链与 LLM 链双注册；上游代际不进 `request_model`，由载荷 `model` 字段决定，单点在 `adapters/_shared.py:MUREKA_INSTRUMENTAL_MODEL = "mureka-9.5"`（`mureka-o1` 实测 400，`auto` 实测解析为 `mureka-9.5`） |

`request_model` 必须写在 YAML：`register_llm_model` 发现同名 YAML spec 已存在时"以 YAML 为权威，只挂载适配器"，
装饰器里的 `default_params` 会被忽略，只写在 `core/llm_adapters.py` 上不生效。
适配器**类名保留版本**（如 `Qwen37PlusAdapter`、`GLM53Adapter`），它们是上游某一版接口的实现快照，与内部 ID 解耦。

**换代台账（旧 ID 已物理删除，无别名、不可解析）**

退役不再保留 `status: deprecated` 兼容位，也不再登记过渡别名。2026-10-09 随数据库历史 ID 改写，
`core/model_resolution.py` 的 `MODEL_ALIASES` 中所有由退役/改名产生的旧 ID 键已整批删除，
`MODEL_ALIASES` 只剩"同一模型的不同拼写形态"归一（下划线/短横线、前端短名、上游全名与内部名不一致）。

| 旧 ID | 现役替代 | 退役原因与时点 |
| --- | --- | --- |
| `wan2.6-t2v` / `wan2.6-t2v-fast` / `wan2.7-t2v` / `wan2.7-i2v` / `wan2.7-r2v` / `wan2.7-videoedit` | `wan3.0-video` | 2026-10-08 万相视频线收敛为单一现役 ID；`wan2.6-t2v-fast` 从未存在于任何注册中心，旧 alias 把请求改写成一个不存在的 ID，比不归一更糟 |
| `qwen-image-2.0` / `qwen-image-2.0-pro` | `qwen-image-3.0` / `qwen-image-3.0-pro` | 2026-10-08 升级；注意限流从 120 QPM 降到 20 QPM（3.0）/ 5 QPM（3.0-pro） |
| `wan2.7-image` / `wan2.6-t2i` | `wan2.7-image-pro` | 2026-10-08 万相图像线收敛为单一现役 ID；`wan2.7-image-pro` 支持 4K 文生图、9 张参考图、`bbox_list` 局部编辑 |
| `doubao-seedream-4-5` | `doubao-seedream-5-0-pro` | 方舟 EOM 2026-09-24 10:00、EOS 2026-11-24 14:00 UTC+8，接入点关停且**不改写旧 Model ID** |
| `doubao-seed-2-0-pro` | `doubao-seed-2-1-pro` | 方舟 EOS 2026-11-24 14:00 UTC+8，同上 |
| `doubao-seed-2-0-lite` | `doubao-seed-2-1-lite` | 同上，lite 档 EOS 提前到 2026-10-22 14:00 UTC+8 |
| `doubao-seedance-1-5-pro` | `doubao-seedance-2-5` | 上游接入点已关闭，实测提交任务返回 400 `InvalidEndpoint.ClosedEndpoint` |
| `deepseek-v4-flash` | `deepseek-flash` | 上游已从官方模型列表移除；DeepSeek 会静默改写旧名，但不可依赖该行为 |
| `mimo-v2.5-pro` / `mimo-v2.5` | `mimo-pro` / `mimo-flash` | 小米 MiMo V2.5 系列 2026-10-21 停服且不做自动替换 |
| `kimi/kimi-k2.6` | `kimi-preview` | 上游未下线，属项目主动升级：上下文 262144 → 1048576，单价持平（6.5/27 元每百万 tokens） |
| `step-3.7-flash` | `step-preview` | 上游未下线，属项目主动升级：上下文 262144 → 1024000、最大输出 16384 → 65536；官方定价上涨（输入 1.35→7、输出 8.1→20 元每百万 tokens） |
| `glm-5.2` | `glm`（线名 `glm-5.3`） | 2026-10-09 上游线名换代，内部 ID 未变。官方刊例价持平（输入 8 / 输出 28 元每百万 tokens）、上下文同为 100 万；旧档案承诺的 `[1m]` 变体名本账号实测 404，换代后不再承诺 |
| `qwen3-tts-flash` / `qwen3-tts-instruct-flash` | `qwen-audio-3.1-tts-flash` | 2026-10-10 上游 `multimodal-generation` 端点对旧 ID 持续返回 404 `Model not exist`，TTS 线整体换代。**换代换掉的是整个音色空间**（48 → 68 条，全部带 `_v3.1` 后缀），见 §11.7.9；注册中心与档案卡已物理删除。2026-10-10 深夜再删一层：别名折叠表里的**逐条旧 ID 也已删除**，`tts_model_ids.py::normalize_audiobook_tts_model` 与前端 `normalizeTtsModelValue` 改为按**前缀**折叠（`qwen3-tts` / `qwen3_tts` 开头一律归到 3.1，覆盖 `-flash`/`-plus`/`-instruct` 与下划线写法），旧 ID 不再由任何产品代码持有 |

| `fun-asr-flash-2026-06-15` | `qwen-audio-3.1-asr-flash` | 2026-10-11 有声书客观层/字幕 ASR 换代。该链路**只有 HTTP 契约**，旧线名不出现在两份 YAML 与注册中心里，故单列进 `RETIRED_AUDIOBOOK_ASR_MODELS`；provider 键 `funasr_flash` 及全部别名整段删除，传旧键直接 `asr_provider_unsupported`。计价口径同时从"按秒后付费"换成"按 Token 派生等效秒价"，见 §11.11 |

| `qwen3.5-omni-plus` | `qwen3.8-omni-flash` | 2026-10-12 视觉评审三档盲评实测：检出率打平、判词质量差一个档次，本档无维度胜出且单条成本约为 3.8 的 11 倍；档案卡、`@register_model`、`analyze_*` 白名单四处物理删除，音频评分组合同批从四档收成两档。存量项目配置已由改写脚本预览复核为零命中 |

| `qwen3-vl-plus` | `qwen3.8-omni-flash` | 2026-10-12 视觉线物理退役第二片（Slice B，短剧 QC 线）。除 Slice A 已删的产品入口外，本批再删：`adapters/dashscope/multimodal.py` 整文件与注册表项、`adapters/dashscope/__init__.py` 星号导入、legacy 适配器类 `Qwen3VLPlusAdapter`、`legacy_runtime_wrappers.Qwen3VLPlusRuntimeWrapper` 与其表键、`core/model_resolution.py` 别名、`config/models.yaml` 档案卡、`config/model_catalog_profiles.yaml` 画像段（含指向本档的 `router_rules`）、`analyze_*` 白名单过渡项、`QWEN_VL_PLUS_*` 三行 env。消费侧同时改为传**模型 ID 字符串**而非适配器对象，兼容层删除才不留残骸。库内存量经改写脚本复核零命中 |

删除旧 ID 与别名时同步改写的位置（不留审计副本，2026-10-09 已执行）：

- `config/models.yaml` / `config/llm_models.yaml` 条目、`core/model_resolution.py` 别名、适配器与 `@register*` 装饰器
- `backend/app/services/asset_studio_model_catalog.py`、`backend/app/api/v1/asset_studio_api/_constants.py`、各业务默认值与白名单
- 前端可选清单与 i18n label
- 数据库中已保存的项目配置、执行记录与渲染后的报告正文，通过 `scripts/rewrite_legacy_model_ids.py` 改写
  （默认 dry-run，`--apply` 执行，改写前自动备份到 `database_backups/`，改写后重扫复核）
- `cosyvoice-v3-plus` → `cosyvoice-v3.5-plus` 是**唯一保留的旧名归一**：它对应已落库的音色资产命名，
  改写等于破坏用户音色资产，故长期保留别名、不动语音资产数据

配套要改的位置（漏一处就会出现"下拉框选不到"或"选中后被弹回默认值"）：

- `backend/app/services/asset_studio_model_catalog.py` 的 `_GROUP_MODEL_IDS`（决定下拉可选项与顺序）与 `_DEFAULT_MODEL_IDS`（决定默认值）
- `backend/app/api/v1/asset_studio_api/_constants.py` 的兜底默认值
- `core/unified_media_runtime.py` 的 `_OPERATION_MODEL_IDS`（按操作类型放行模型）
- `config/model_catalog_profiles.yaml` 的选型画像
- 前端 fallback 常量：`AssetStudioWorkbench.tsx`、`constants/dreamweaver.ts`、`useDreamweaverRunConfig.ts`、`DreamWeaverRunPage.tsx`
- 两处 i18n：`frontend/src/i18n/resources/{zh-CN,en-US}/common.json` 的 label 与 helper 键，必须双语对称

规则总结：

- 百炼上的 Kling / PixVerse / Vidu 模型需要带供应商前缀（`kling/`、`pixverse/`、`vidu/`）
- 火山方舟的 Doubao 系列模型需要带日期后缀
- 注册 ID 保持简洁可读，实际 MODEL_ID 在适配器类中用 `MODEL_ID` 常量映射
- 火山方舟的下线是硬失败：预置接入点到期直接关停，**不会**把旧 Model ID 改写转发（DeepSeek 会静默改写）。因此方舟模型迁移必须同时更换适配器的 `MODEL_ID` 快照名，仅加 `MODEL_ALIASES` 不足以在 EOS 后存活
- 方舟 Seed 2.1 起深度思考默认开启，`thinking.type` 只接受 `enabled` / `disabled`（无 `auto`），思考与正文共用 `max_tokens` 预算，小预算请求需显式关闭思考
- `size` 的分隔符是供应商私有的：百炼用 `WIDTH*HEIGHT`，火山方舟只认 `WIDTHxHEIGHT`（或档位预设）。`UnifiedMediaRuntime._build_legacy_adapter_kwargs` 按百炼约定统一拼星号，因此方舟适配器必须自行翻译——`_SeedreamImageAdapter._resolve_size` 负责把星号转成 `x`，并在总面积越界时回退到该模型的 `DEFAULT_SIZE`
- 方舟图像还校验**总面积**下限，而 `ConstraintSpec` 只有单边上下限、没有面积字段，所以本项目的 `_validate_dimensions_for_models` 拦不住面积越界（例：`1024x576` 通过本项目校验，却被方舟以 `image area must be at least 921600 pixels` 拒绝）。面积约束目前只能落在适配器里

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
| Mureka 平台 | `POST /v1/instrumental/generate` | `GET /v1/instrumental/query/{task_id}` | `choices[0].url`（另有 `flac_url` / `wav_url`，`duration` 单位毫秒） |

注意：

- Mureka 查询端点是 `/v1/instrumental/query/{task_id}`（不是 `/v1/instrumental/{task_id}`）。
- 火山方舟 Seedance 的结果在 `content.video_url`，不是 `video_url`。

### 6.7 `UnifiedMediaRuntime` 适配器调用约定（2026-04-21 补充，2026-10-10 按注册表现状订正）

两种签名运行时都能被调用，但仓库现状只有一类真正在服务媒体线，新增适配器必须按现状写。

调用机制：

- `core/unified_media_runtime.py:886` `_invoke_adapter_generate` 先问 `:892` `_adapter_generate_accepts_task`：`inspect.signature` 的首参是位置参数**且名字是 `task`** 时才 `generate(task)`；否则用 `_build_legacy_adapter_kwargs`（`:907`）把 `TaskSpec` 摊平成基础类型 kwargs，调用旧签名。
- 判定只看首参名，不看注解或能力。所以首参叫别的名字（`prompt`）的适配器一律走 kwargs 路径。

注册表现状（2026-10-10 实测，按 `default_registry()._adapter_classes` 逐个取 `generate` 定义处统计）：

- 38 个已注册适配器**全部**自行覆写了 `generate`，没有任何一个依赖 `adapters/base.py:254` 的 TaskSpec 模板方法。
- 其中 34 个是 `generate(self, prompt: str = "", **kwargs)`；剩下 4 个是 `adapters/dashscope/tts.py:84` 的双模实现（首参名 `task`，既可收 `TaskSpec` 也可收 prompt 字符串，进来先 `_normalize_runtime_request` 归一化）。

因此约定是：

- **新增媒体适配器一律写 `generate(prompt, **kwargs)`**，与 `adapters/dashscope/*`、`adapters/volcengine/*`、`adapters/vidu_platform/*`、`adapters/mimo/*` 的既有实现对齐。
- 2026-04-21 版本把 `generate(task: TaskSpec)` 列为首选，与现状相反。task-only 签名在 `UnifiedMediaRuntime` 这一条路径上确实能被调到（首参名是 `task`），但媒体线还有**不经过 runtime 的直连调用方**按 kwargs 调适配器：`backend/app/api/v1/asset_studio_api/routes_audio.py:129,439`（`prompt=` / `references=` / `audio_config=` / `watermark=`）、`backend/app/services/audiobook/doubao_sfx_generator.py:92`、`backend/app/services/audiobook/agent_dispatch_client.py:415`（`adapter.generate(prompt=text, voice_id=..., **kwargs)`）。给这些入口写 task-only 签名会直接 `TypeError`。
- 至于 `adapters/wan26_video_adapter.py`（585 行、5 个 `@register_model`）与 `adapters/wanx_adapter.py`、`adapters/qwen_multimodal_adapter.py` 那批单体适配器：它们不覆写 `generate`，沿用 `adapters/base.py:254` 的 TaskSpec 模板，实际失效原因是与 dashscope 拆分模块**重复注册同一 ID**后被 last-write-wins 覆盖，于是整文件成为永不被选中的死代码。取证与守卫见 `tests/test_adapter_registration_uniqueness.py`。

兼容层当前会补齐的常见字段：

- `prompt`
- `negative_prompt`
- `width` / `height` / `size`
- `duration`
- `image_path` / `video_path` / `reference_images`
- `camera_control` / `motion_control`
- `parameters`（视频模型常用 `duration`、`resolution`、`aspect_ratio` 等）

建议：

- 新接入模型实现 `generate(prompt, **kwargs)`，并在自己的请求映射函数里做入参白名单与越界校验；不认识的 kwargs 记进 `result.metadata["dropped_params"]` 留痕，不要静默丢弃（见 §11.8.4）。
- 保留一条 `UnifiedMediaRuntime` 兼容回归测试，确认 `TaskSpec` 到旧 kwargs 的映射符合预期；现有覆盖见 `tests/test_doubao_seedream_image.py`、`tests/test_image_negative_prompt_forwarding.py`。
- 不要把 `TaskSpec` 实例直接送进 `requests` 的 `json=` 或日志序列化，否则会触发 `Object of type TaskSpec is not JSON serializable`。走 kwargs 路径时 runtime 已摊平，风险只在**首参名为 `task` 的适配器**上：它收到的是原始 `TaskSpec`，必须在自己的 `generate` 里先归一化（`adapters/dashscope/tts.py` 的 `_normalize_runtime_request` 即此用意）。

## 7. 已验证模型清单（2026-04-18 首测，图像/视频线 2026-10-08 复测，2026-10-09 按退役结果收敛）

以下 31 个模型已通过真实 API 调用验证（`vidu-timing2audio` 已于 2026-10-08 因音效质量不达标下线删除；
`seed-audio-1.0` 于同日以短音效实测补入；`doubao-seedance-2-5` 于 2026-10-08 新增接入并实测；
2026-10-08 换代后 `qwen-image-2.0/-pro`、`wan2.7-image`、`wan2.6-t2i`、`doubao-seedream-4-5`、
万相 2.6/2.7 视频 5 个 ID 已退役并从本表移除）：

现役 ID 的权威事实源是注册中心，不是本表（本表只覆盖做过真实调用实测的部分，还包含 MiMo TTS 三档、
`seed-tts-2.0-expressive`、`seed-audio-1.0-multilingual` 等未列项）：

```powershell
python -c "from adapters.registry import default_registry as d; s=d().get_all_specs(); print(len(s)); print('\n'.join(sorted(x.id for x in s)))"
```

2026-10-09 清点结果：**46 个媒体 spec，全部 `status: active`，无任何 `deprecated` 条目**。

### 图片生成 (7)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen-image-3.0` | 百炼 | 43s（2026-10-08 实测，默认开启 prompt_extend + enable_thinking） |
| `qwen-image-3.0-pro` | 百炼 | 44s（2026-10-08 实测） |
| `wan2.7-image-pro` | 百炼 | 44s（2026-10-08 实测，`size=2K` 档位串） |
| `kling/kling-v3-image-generation` | 百炼 | 26s |
| `kling/kling-v3-omni-image-generation` | 百炼 | 15s |
| `doubao-seedream-5-0` | 火山方舟 | 13s |
| `doubao-seedream-5-0-pro` | 火山方舟 | 24s (1536x1536) / 16s (1536x1024) |

### 图片编辑 (2)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen-image-edit-plus` | 百炼 | 9s |
| `qwen-image-edit-max` | 百炼 | 26s |

### 对话 / 多模态 (3)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `qwen-plus`（上游线名 `qwen3.7-plus`） | 百炼 | 1.6s |
| `doubao-seed-2-1-pro` | 火山方舟 | 3s |
| `doubao-seed-2-1-lite` | 火山方舟 | 1.5s |

### TTS (4)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `MiniMax/speech-2.8-turbo` | 百炼 | 1.5s |
| `MiniMax/speech-2.8-hd` | 百炼 | 1.3s |
| `cosyvoice-v3.5-plus` | 百炼 | 0.6s |
| `qwen3-tts-instruct-flash` | 百炼 | 0.7s |

### 视频生成 (11)

| 注册 ID | 类型 | 平台 | 典型延迟 |
| --- | --- | --- | --- |
| `wan3.0-video` | 文生/图生/参考生/编辑/延长 | 百炼 | 5 秒 720P 约 3 元（2026-10-08 刊例价 0.6 元/秒）；端到端通常数分钟 |
| `pixverse-c1-r2v` | 参考生视频 | 百炼 | 52s |
| `pixverse-v6-t2v` | 文生视频 | 百炼 | 49s |
| `vidu-q3-pro-text2video` | 文生视频 | 百炼 | 124s |
| `vidu-q3-pro-img2video` | 图生视频 | 百炼 | 110s |
| `vidu-q3-pro-start-end2video` | 首尾帧生视频 | 百炼 | 130s |
| `kling/kling-v3-video-generation` | 文生视频 | 百炼 | 42s |
| `kling/kling-v3-omni-video-generation` | 图生视频 | 百炼 | 250s |
| `doubao-seedance-2-5` | 文生视频 | 火山方舟 | 94s（2026-10-08 实测，480p / 4s / 38,830 tokens） |
| `doubao-seedance-2-0` | 文生视频 | 火山方舟 | 103s |
| `doubao-seedance-2-0-fast` | 文生视频 | 火山方舟 | 119s |

### 音频生成 (2)

| 注册 ID | 平台 | 典型延迟 |
| --- | --- | --- |
| `mureka-o1-instrumental` | Mureka 平台 | 65-75s（2026-10-11 实测两次 65.1s / 75.4s） |
| `seed-audio-1.0` | 火山方舟 | 18-25s（短音效） |

实测补充（2026-10-08）：

- `mureka-o1-instrumental` 会忽略请求里的 `duration`，5 秒与 10 秒请求都返回约 190 秒的完整乐曲，只适合配乐，不适合短音效。
  2026-10-11 复测确证根因：上游**根本没有 duration 入参**（载荷只有 `model` / `n` / `prompt` / `instrumental_id` / `stream`），
  请求 30 秒实测返回 188.5 秒，全部契约事实见 §12。
- `seed-audio-1.0` 没有时长入参，长度由模型按提示词自行决定；三条短音效提示词分别输出约 5.5 / 4.5 / 4.0 秒，响应 `metadata.duration` 为真实时长，因此资产工作台音效链路用它作默认模型。
- Seedance 按 token 计费，公式 `(输入视频时长 + 输出视频时长) × 宽 × 高 × 帧率 / 1024`，因此**分辨率档位对成本是平方级影响**：
  2026-10-08 实测同一条 4 秒提示词，`doubao-seedance-2-5` 480p 消耗 38,830 tokens（约 2.7 元），
  `doubao-seedance-2-0` 4k 消耗 785,700 tokens（约 20 元，与官方 4k 档 25.27 元/5 秒按比例吻合）。`4k` 只有 2.0 系列提供，2.5 无该档位。
- 官方刊例价与示例价（来源：`ark.volcengine.com/region:cn-beijing/docs/ark/model-pricing`，2026-10-08 取数）：

  | 模型 | 480p/720p 不含输入视频 | 含输入视频 | 1080p 不含/含 | 4k 不含/含 | 5 秒 16:9 不含输入视频 |
  | --- | --- | --- | --- | --- | --- |
  | `doubao-seedance-2-5` | 70.00 | 42.00 | 77.00 / 46.00 | 不支持 | 3.36 / 7.56 / 18.71 元（480p/720p/1080p） |
  | `doubao-seedance-2-0` | 46.00 | 28.00 | 51.00 / 31.00 | 26.00 / 16.00 | 2.31 / 4.97 / 12.39 / 25.27 元（…/4k） |
  | `doubao-seedance-2-0-fast` | 37.00（刊例） | 22.00 | 不支持 | 不支持 | 1.86 / 4.00 元 |

  同规格横向对比：`wan3.0-video` 720P/5 秒 = 0.6 × 5 = **3.00 元**，2.5 的 720p 同规格是 **7.56 元（2.52 倍）**。
- 计费规则三条（官方原文，`config/models.yaml` 的 `pricing_info.billing_rules` 已记录）：
  - **仅成功生成计费**，审核等原因失败不收费（所以 running 中的任务即使无法取消也一定会扣费）。
  - **含输入视频时存在最低 token 用量下限**，估算用量不足下限时按下限计；官方另有分分辨率/宽高比/时长的最低用量表。
  - **Draft 两步独立计费**：Step1 按 480p 档；Step2 按目标分辨率档，且 **token 单价由 Step1 是否含输入视频决定**，
    算 token 用量时输入视频时长按 Step1 的输入视频计、**Draft 成片不计入输入时长**。
- 限时折扣口径：官方顶部说明 fast 75 折 / mini 4 折窗口为 2026-08-07 14:00 ～ 2026-10-07 14:00（已到期）、
  仅限企业用户、达 token 上限后恢复刊例价；但同页价格表仍挂着「原价 37.00 限时75折」标记，两处自相矛盾。
  **本项目一律按刊例价记账，不引用折扣价。**
- 2.5 的开通门槛独立于 2.0（官方：账户余额 > 200 元或已购买对应资源包），未开通时同一密钥调用会失败。
- 参数校验类探测（`duration=16` 打 2.0、`resolution=4k` 打 2.5、`draft_task` 配非 1080p 等）在**提交阶段**即被拒绝，
  不产生费用，可用于免费确认契约边界；一旦任务进入 running，`DELETE /contents/generations/tasks/{id}` 会返回
  `409 InvalidAction.RunningTaskDeletion`，无法中止，所以付费档位务必先用 480p + 最短时长验证。

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
- `asset_library`：素材库生成链现在也会优先读取 `image_config.adapter` 和 `image_config.vlm_adapter`，不再固定回落到 `wan2.6-t2i` / 环境变量 VLM。2026-10-08 图像线换代后，该链与关键帧 / 中间帧的兜底模型统一为 `qwen-image-3.0-pro`（与 `_DEFAULT_MODEL_IDS["dreamweaver_image"]` 一致）。
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
from adapters._shared import DASHSCOPE_API_KEY, DASHSCOPE_BASE

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

对于 DeepSeek 官方文本 LLM，先用最小 OpenAI 兼容调用确认密钥、Base URL 和模型 ID 正确：

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "ping"}],
    max_tokens=32,
)

print(response.choices[0].message.content)
```

验证 `deepseek-v4-pro` 时只替换 `model` 字段；如果本地适配器仍读 `DASHSCOPE_API_KEY` 或 `dashscope.aliyuncs.com/compatible-mode/v1`，说明运行时配置还没有完成渠道切换。

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

4. Asset Studio 统一模型清单回归

```powershell
python -m pytest "tests/test_asset_studio_model_catalog.py" -q
```

这组测试用于捕获：

- `config/models.yaml` 最新名称没有正确透传到统一清单
- 公开模型 ID 与配置 ID 的 alias 丢失，导致前端回填成旧版本或错误模型
- 默认模型不在所属 group 中，导致页面加载后自动回退
- 视频时长档位的区间元数据没有从 `models.yaml` 透出（`duration_min/max/step/default/supports_auto`），或区间模型被压回成逐秒阶梯之外的少量档位

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
- 万相 3.0 首帧驱动用 `first_frame`、参考生视频用 `reference_image`、视频编辑与延长用 `reference_video`；PixVerse 用 `image_url`，Vidu 用 `image`
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

- 现存的 Vidu 模型（`vidu-q3-pro-*` 三个视频模型）全部走百炼平台，用阿里密钥，注册 ID 带 `vidu/` 前缀
- 历史上唯一走 Vidu 自有平台 `api.vidu.cn` 的 `vidu-timing2audio`（音效）已于 2026-10-08 下线删除，仓库内不再有任何模型直连 Vidu 平台

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

不成立，但结论方向要按现状读（2026-10-10 订正，详见 §6.7）。

- 媒体线的**事实签名**是 `generate(self, prompt: str = "", **kwargs)`：注册表里 38 个适配器全部覆写了自己的 `generate`，34 个是这一形态，另 4 个是 `adapters/dashscope/tts.py` 的首参名 `task` 双模兼容实现。
- `generate(self, task: TaskSpec)` 不会被运行时拒绝（`_adapter_generate_accepts_task` 按首参名嗅探后走 `generate(task)`），但媒体线有大量不经过 runtime 的直连调用方按 kwargs 调用，task-only 签名在这些入口上直接 `TypeError`。而 `adapters/wan26_video_adapter.py` 等三个单体适配器的实际死因是另一条：与 dashscope 拆分模块重复注册同一 ID，被 last-write-wins 覆盖后整文件永不选中——两种失效都不报错，靠签名约定与注册唯一性守卫才看得见。
- 一旦旧式 adapter 直接收到 `TaskSpec` 并进入 `json=` 或其他序列化路径，就会触发 `TaskSpec is not JSON serializable`；首参名为 `task` 的适配器必须先归一化。
- 新接入模型请实现 `generate(prompt, **kwargs)`，并补一条 runtime 兼容回归测试锁住 kwargs 映射。

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

### 10.14 "DeepSeek V4 Pro / Flash 继续走阿里百炼也一样"

不成立。

- `deepseek-flash` 和 `deepseek-pro`（上游线名 `deepseek-v4-pro`）的项目接入基线现在以 DeepSeek 官方 API 为准。
- 这两个模型应使用 `DEEPSEEK_API_KEY` 和 `https://api.deepseek.com`，不再复用 DashScope 的 `DASHSCOPE_API_KEY` 与 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 阿里百炼渠道仍可服务 Qwen、Wan、TTS、视频等百炼模型；不要把该规则外推到 DeepSeek 官方 V4 文本模型。
- 排查这两个模型失败时，先检查实际请求的 Base URL、API Key 环境变量和 `request_model`，再检查提示词、上下文长度或业务参数。

### 10.15 "DeepSeek V4 全局启用思考模式更稳"

不成立。

- `deepseek-flash` 是项目快速通道，默认禁用思考模式，适合 fast / chat / rewrite / ai_trace / simple。
- `deepseek-pro` 是高强度推理通道，默认启用思考模式，适合 worldview / character / structure_plot / review / quality_review / final_review / reasoning / volume_detail_expand。
- 思考模式下 `temperature`、`top_p` 等采样参数不生效，因此不适合需要风格随机性或创造性控制的生成链路。
- 思考模式会优先消耗 reasoning tokens；`max_tokens` 太小时可能出现 HTTP 200 但 `content` 为空。
- 当前项目只把 `reasoning_content` 作为 metadata 记录长度和存在性，不把它拼进业务 `content`。
- 工具调用、流式输出和严格 JSON 输出场景由适配器自动把 `thinking` 设为 disabled。

### 10.16 "YAML 里不给 task_types，模型就不会被选中"

只对一半。2026-10-09 接入「仅供失败回退」的 `qwen-flash-fallback`（上游 `qwen3.8-flash`）时，需要同时满足三件事，缺一件语义就变了：

- `status: active` **且** `routing.enabled: true`：`UnifiedModelSpec.is_available()` 同时要求这两项。任一为假，`ModelHub._select_fallback_model()` 会直接跳过它，回退静默失效——不报错，只是永远切不过去。
- `routing.task_types: []`：`select_best_model()` 按 `_task_type_mapping` 取候选，置空即不参与自动路由。
- **不进任何用户可选清单**：`MULTI_MODEL_REVIEW_ALLOWED_MODELS`、`MODEL_REVIEW_GOVERNANCE`、`REWRITE_CAPABLE_MODELS`、`STORY_EXPANSION_MODEL_CANDIDATES` 是各自独立的事实源，task_types 留空挡不住它们；反过来也意味着新增条目默认不影响这些白名单。
- 反制断言见 `tests/test_qwen_flash_fallback_model.py`：同时锁「task_types 为空」「逐个任务类型不被自动路由命中」「主模型失败时第一顺位是它」「不在可选清单里」。

### 10.17 "档案里记的上限就是上游现在的上限"

不成立。中性内部 ID 让换代只改 `default_params.request_model`，`constraints.*` 不会有任何提醒地停在上一代取值。2026-10-09 用越界探测逐条对账，实测与档案的关系有**五种**，混为一谈就会改错方向：

| 情形 | 实例（档案 → 实测） | 后果 |
| --- | --- | --- |
| 档案偏低（换代残值） | `qwen-plus` 65536 → 131072、`qwen-flash` 65536 → 131072、`glm` 16384 → 131072 | `_normalize_max_tokens_for_model()` 把请求**静默夹到档案值**，长输出提前截断且不报错 |
| 档案偏高（误导型错值） | `qwen-flash` 思考 262144 → 131072 | 按档案值发请求会被上游直接 400 |
| 把默认发送值当上限 | `minimax-m` 记 16384，实为 `default_params.max_tokens`；上游校验上界 524288 | 上限与发送值两个概念被写进同一个字段 |
| 抄官方文档、从未实测 | `doubao-seed-evolving` 记 16384，实测 262144（偏低 16 倍）。它长期"探不到"的真实原因是档案声明的 `api_key_env` 曾指向本仓库根本没配置的变量名，探测直接跳过（2026-10-09 已统一到 `VOLCENGINE_API_KEY`，现已纳入默认实测） | 探测跳过被当成"已对账"，错值长期存活；同一模型的文本线还会因缺 key 静默回退到别的厂商并返回 `success=True`（该静默回退现已修，见 §10.22） |
| 上游根本不校验，探不出来 | `step-preview`（传 999999 返回 200）、`kimi-preview`（262145/1048577 都 200） | 档案值是**项目自选的保守上界**，不是错值，不许当漂移改掉 |

本表记录的是**漂移类别**，不是当前档案状态：左列错值已于 2026-10-09 全部按实测对齐，当前真值以 `tests/test_llm_output_limit_fact_table.py` 的事实表为准（该表同时核对装饰器镜像，见 §10.21）。

三个必须分清的量：

- `constraints.max_output_tokens`：上游允许的输出上界，只做夹取与预算判定，不是实际发送值。
- `default_params.max_tokens`：项目实际发送的值。**改上限永远不要顺手改它**——它会改变真实发送参数与超时行为。
- 上游校验上界：只有越界探测能拿到；上游不校验时该字段只能是自选值，并必须在 `integration_notes` 写明来源。

档案值有三个消费方，调大时的副作用要一起看：

- `core/llm_adapters.py:_normalize_requested_max_tokens`（第二道夹取在 `core/model_hub.py:_normalize_max_tokens_for_model`）：决定请求能否发满。
- `core/model_hub.py:_increase_retry_timeout_budget`：`growth_factor` 在 `requested_tokens >= max(4096, max_output_tokens // 4)` 时取 2.0 否则 1.5。**上限写小会让超时升档更激进**，所以"当年写小是为了防超时"的猜测方向是反的。
- `backend/app/api/v1/workflow/helpers.py:_get_model_token_limits`：输出上限只进入 `min(output_limit, context*0.25)` 的预留项，1M 上下文下由上下文侧主导，改上限基本无感。

取真实上限的做法固化在 `scripts/probe_llm_output_limits.py`。退出码三态，**"没测到"不等于通过**：漂移=1、无漂移但存在未探到条目=2、全部一致=0。未探到要么是缺 key（配置问题，必须修），要么是上游不校验（必须登记进 `SKIP_REASONS` 并在 `integration_notes` 说明理由）。各家回显文案都要单独认：百炼 `Range of max_tokens should be [1, N]`、方舟 `expected a value <= N`、MiMo `supports at most N completion tokens`、MiniMax `does not support max tokens > N`——漏认一家就等于那家永远没对账。四条已实测的坑：

- 关掉思考后 `thinking_budget` 会被上游**直接忽略**（关思考 + 越界 budget 返回 200），探测思考上限必须显式开启思考。
- 上游会把我们传的越界值原样回显（`max_tokens is too large: 999999. This model supports at most 131072...`），正则抓到 `OVER_LIMIT` 本身等于没抓到。
- 强制思考的模型收到关思考参数会在 `max_tokens` 校验**之前**就报错，探测要按「带关思考参数 → 被拒则去掉再试」两级兜底。
- `max_retries` 不是 `chat.completions.create()` 的参数，只能设在 client 上；写进 kwargs 会得到 `unexpected keyword argument`，看起来像"上游不校验"。

### 10.18 "档案写 `supports_vision: false`，就是模型不能看图"

不一定。`qwen-flash` 档案里的 `false` 是「项目未验证」的保守声明，实测通过 DashScope 兼容接口传 32×32 PNG 能正常识图。

探测陷阱：边长小于 10 像素的图会被上游以 `The image length and width do not meet the model restrictions（height/width must be larger than 10）` 拒绝。这条报错与「是否支持视觉」无关，用它下结论会得出错误的否定判断——视觉探测必须用边长大于 10 的合法图。

### 10.19 "档案的自由文本里写上游真名无所谓"

有区别。`scripts/audit_model_references.py --all-retired --expect-zero` 把退役登记表里的旧 ID 在**任何文件**的出现都算命中，只有 `request_model:` 行和「模型名为 X」这类 `integration_notes` 记为 `[记录]`，`description` / `summary` / `recommended_scenarios` 里出现旧名一律判 `[待改]` 并让门禁红。

**而且监视范围包含现役线名，这是原地换代时最容易踩的一条。** 检索集合是 `RETIRED ∪ RENAMED`，`RENAMED` 的键就是**当前**发给上游的真名；`glm` 升到本代后，新线名进了 `RENAMED` 立刻变成"必须消失的 legacy id"，于是散文里一句"实测新线名可调用 / 直接使用新线名"就把门禁从 0 打成红。合法写法只有四种：`request_model:` 行、「模型名为 X」/「上游线名 X」、示例里的 `model="X"`、带方括号后缀的线名变体 `X[...]`；其余一律改用**内部 ID**。可以点名旧 ID 的层只有 `ALLOWED_LAYER_PREFIXES`：`docs/`、`.workbuddy/`、`tests/test_model_retirement_registry.py`、`scripts/audit_model_references.py`、`scripts/rewrite_legacy_model_ids.py`（+ 带日期的实验记录）。

配套地，`RENAMED_LLM_MODELS` 里**一个内部 ID 只能有一个键**：`test_wire_name_is_pinned_by_request_model` 把键当作 `request_model` 的期望值，换代必须替换键、并把旧线名移入 `RETIRED_LLM_MODELS`，并列加两个键会自相矛盾。

规则：模型档案的自由文本统一引用**内部 id**（`qwen-flash`、`qwen-plus`），上游真名只写在 `default_params.request_model` 和 `integration_notes`。每次编辑档案后**重跑门禁**，不要相信"上一轮已经归零"。

### 10.20 "档案里的 `enable_thinking: false` 只是备注，改模型名不用管它"

不成立，而且这是本轮最贵的一条。`core/llm_adapters.py:_build_completion_params` 对 `default_params` 的处理是：**不在 OpenAI 标准参数白名单里的键，一律塞进 `extra_body` 透传上游**（白名单见同文件 `_OPENAI_STANDARD_KEYS`，`_SPECIAL_DEFAULT_PARAM_KEYS` 只豁免 `request_model`）。所以 `enable_thinking: false` 不是注释，是每次请求都会带的参数。

`glm` 由上一代原地换代到强制思考的本代后，这个陈旧写法让**每一次经 `model_hub` 的 glm 调用都 400**，重试三次后静默回退到 `qwen-plus`——业务侧只看到"glm 结果质量变差了"，日志里才是 `BadRequestError`。2026-10-09 实测的glm-5.3 关思考写法清单：

| 写法 | 结果 |
| --- | --- |
| `extra_body={"enable_thinking": False}` | 400 `The value of the enable_thinking parameter is restricted to True.` |
| `extra_body={"thinking": {"type": "disabled"}}` | 同上 400 |
| `extra_body={"thinking": "non_thinking"}` / `"disabled"`（字符串形态） | 400 `'thinking' must be json_object` |
| `reasoning_effort="none"` | 400 `must be one of: 'low', 'high', 'max'` |
| 不发 `extra_body` | 正常，返回带 `reasoning_content` |
| `reasoning_effort="low"` | 正常，`reasoning_content` 长度接近 0，是**近似低思考**而非关闭 |

规则三条：

- 强制思考模型的 `default_params` 里**不许**出现 `enable_thinking` 或 `thinking.type: disabled`；要降思考用顶层 `reasoning_effort: low`。
- "能不能关思考"的唯一事实源是 `core/model_resolution.py:_FORCED_THINKING_MODEL_IDS`，`build_thinking_disabled_extra_body()` 对集合内的 ID 返回空 dict。`ai_trace_competition` / `prompt_evolution` 的 evaluator 与 deanchor 重写都在用它，集合漏一个就是一批 400。
- 反制断言在 `tests/test_llm_output_limit_fact_table.py`：同时锁「集合内含该 ID」「helper 返回空」「YAML `default_params` 里没有关思考写法」。

顺带一条与换代无关但同源的观察（2026-10-09 复现并逐行核对分类代码后修正本段原表述）：修复前这条 400 经 `core/llm_adapters.py:_map_error_code()` 落到兜底分支，`error_code = "unknown_error"`（报文里既没有 `429`/`rate limit`/`throttled` 也没有 `capacity limits`，不会进 `rate_limit`）。真正的问题在消费侧：`core/model_hub.py` 的提前中断白名单只认 `auth_error` / `model_not_found` / `content_safety`，`unknown_error` 既不在白名单也不在任何退避分支，于是**永久性请求错误被当成可重试的瞬时故障**——重试满 `max_retries` 后由 `_select_fallback_model` 静默切走，业务侧看到的只是"这个模型质量变差了"。

**参数非法与瞬时故障不分类**这条已于 2026-10-09 修复：新增 `invalid_request` 错误码并入永久错误集合，命中即不重试不回退（实现细节、判序陷阱与反制测试见 §10.22）。

### 10.21 换代后如何证明档案没陈旧

两个可复跑的证据，接/换文本模型收尾时都要跑：

```bash
python scripts/probe_llm_output_limits.py            # 漂移=1，未探到=2，一致=0
python -m pytest tests/test_llm_output_limit_fact_table.py -q
```

退出码 2 也要处理：那说明有条目根本没验证过，不是"这次没问题"。

改了探测结论就同步改 `tests/test_llm_output_limit_fact_table.py` 里的事实表（含注释中的回显原文），不要把脚本改成迎合档案。

### 10.22 "点名的模型失败了会回退，所以调用方看到的是稳定"

不成立。**2026-10-09 已修复。**

修复前的行为：`core/model_hub.py` 的中断白名单只有 `auth_error` / `model_not_found` / `content_safety` 三种错误码会直接停止；其余错误码一律重试并走 `_select_fallback_model`。两类**永久错误**因此被当成瞬时故障：

- `client_not_initialized`：`core/llm_adapters.py:_get_client_for_current_context` 只在 `get_api_key()` 为空时置这个码，客户端在同一函数里 inline 懒建，不存在竞态，所以它是纯配置缺失。2026-10-09 复现（当时 doubao 文本线的 `api_key_env` 指向未配置的变量名）：点名 `doubao-seed-evolving` → 三次无效重试 → 静默切到 `qwen-plus` → **`success=True`**，调用方拿不到任何"我要的模型没被调用"的信号。
- 参数非法 400：`_map_error_code` 的兜底返回 `unknown_error`（`core/llm_adapters.py` 末段），同样不在白名单里。glm 那次全量 400 就是这样变成"glm 质量变差了"的。

落地方案（四条，均已实施）：

1. 错误码集合上收到模块级常量 `core/model_hub.py:_PERMANENT_ERROR_CODES` = `{auth_error, model_not_found, client_not_initialized, invalid_request}`，重试循环内命中即 `break`。
2. `core/llm_adapters.py:_map_error_code` 新增 `invalid_request`：`status_code == 400`（或报文含 `Error code: 400` / `<400>`）且带参数类文案（`InvalidParameter` / `invalid_parameter` / `not valid` / `must be one of` / `restricted to` / `range of` / `too large` / `does not support` / `unsupported` / `above maximum value`）时判永久。**匹配顺序必须排在 rate-limit 标记之后**：方舟与百炼的 `ServiceUnavailable`、`capacity limits` 也带 400 家族文案，前置会把真限流误判成参数错误。不带这类文案的 400 仍落 `unknown_error`。
3. `unknown_error` **保持可重试可回退**：它是兜底分支，真实瞬时故障、未映射 5xx、空 200 都落在这里，一刀切判永久会削掉韧性。
4. `content_safety` **有意不并入永久集合**：它同样在循环里 `break`（同 prompt 重试无意义），但走的是自己的跨模型链路 `_CONTENT_SAFETY_FALLBACK_CHAIN`（换用安全策略不同的厂商重试），与"永久错误直接返回失败"语义不同，合并会切断这条链路。

一个容易漏的点：循环里的 `break` 只退出重试循环，循环结束后代码仍无条件走 `_select_fallback_model`，所以必须在循环**之后**再加一道永久码守卫（`core/model_hub.py`，紧挨 `_select_fallback_model` 之前，命中则记 `❌ ... 永久错误，不重试不回退` 并直接返回 `last_result`）。新增反制测试时先只加 `break`，会看到 2 条用例红——这个红就是这道守卫存在的理由。

反制测试：`tests/test_permanent_error_no_fallback.py`（8 passed）——既有 `_map_error_code` 的映射断言（含 `bad_request_without_param_marker_stays_unknown`、`rate_limit_wording_keeps_priority_over_invalid_request`、`connection_error_is_not_invalid_request` 三个边界），也有 hub 侧参数化断言：永久错误下 `success is False`、`model_id` 保持指名模型、主适配器 `await_count == 1`（不重试）、回退适配器 `await_count == 0`（不换厂商）；另有一条反向用例保证 `unknown_error` 仍然重试 3 次并回退成功。

真机端到端验证：`hub.call(model='glm', extra_body={'enable_thinking': False})`（ glm 为强制思考模型）→ `success=False | model_id=glm | error_code=invalid_request`，日志出现"永久错误，不重试不回退"。修复前同一调用会返回 `success=True` 且实际产出来自 `qwen-plus`。

本轮未动的相邻项（记录备查）：`backend/app/services/streaming_service.py:115` 的 retryable-token 字符串列表是另一套独立判定，未与新错误码对齐，如需统一另开一轮。

缺 key 的静默回退在本轮已随 `api_key_env` 统一到 `VOLCENGINE_API_KEY` 而消失（两条 doubao 文本线经 hub 实测 `success=True` 且 `model_id` 保持指名模型）；即使将来再配错变量名，现在也是直接失败并打 error 日志，不再伪装成成功。



### 10.23 "改一个视频模型的时长，只需要改 `models.yaml`"

不成立，而且这是 2026-10-09 时长放开这一轮里最贵的一条。视频时长在仓库里有**七处**各自独立的事实源，改一处其余六处不会报错、不会变红，只会在运行时表现为「前端下拉只有三个点」「后端 400 说上限是 10」这类互相矛盾的现象：

| # | 位置 | 形态 | 放开区间时必须同步的动作 |
| --- | --- | --- | --- |
| 1 | `config/models.yaml` 的 `constraints.duration` | 四种写法共存：`[]` / `[3,5,10]` / 单值 `5` / `{min,max,default[,supports_auto]}` | 改成官方区间（dict 形态），并在块上方留一行来源注释注明核对日期与 `documentation_url` |
| 2 | `frontend/src/utils/assetStudioDurationControls.ts` 的 `VIDEO_DURATION_OPTIONS_BY_MODEL` | 档位列表模型的离线镜像 | 转为区间模型的档位（如 `pixverse-v6-t2v`）**从这里删掉**，否则前端继续渲染下拉 |
| 3 | 同文件的 `VIDEO_DURATION_RANGES_BY_MODEL` | 区间模型的离线镜像 | 新增/更新 `min/max/step/defaultValue/supportsAuto`；这里是 catalog 拉不到时的兜底，写错不会报错只会静默放窄可选值 |
| 4 | `frontend/src/components/home/AssetStudioWorkbench.tsx` 的 `MOTION_MODEL_OPTIONS` | 动作组兜底成员表（不是时长，但同源同罪） | 与后端派生结果逐档对齐，档案只有 `text_to_video` 的档位**不得**出现在这里 |
| 5 | `frontend/src/constants/dreamweaver.ts` 的 `VIDEO_MODEL_OPTIONS` / `VIDEO_EDIT_MODEL_OPTIONS` | 短剧运行页模型清单 | 成员变更（如 2-0/2-0-fast 进编辑组）要同步，否则短剧侧下拉与资产工作台不一致 |
| 6 | 各适配器 `get_model_spec()` 里的 `constraints`/`modality` | 第四处隐藏事实源 | `adapters/registry.py:357-383 load_from_yaml` 在装饰器注册**之后**执行 `self._specs[spec.id] = spec`，所以 YAML 覆盖适配器 spec；但**两处必须同时改**——只改 YAML，一旦加载顺序变化就静默回退到适配器旧值（本轮 `adapters/dashscope/video_kling.py:94` 就是按此订正） |
| 7 | `config/models.yaml` 的 `pricing_info` | 2026-10-09 起从「零生产消费方的备注」升级为**下单前置条件** | 时长每放开 1 秒就多冻 1 秒的价；分辨率档放通（如 1080P）必须同步补该档每秒价，缺价的新组合在入口直接 400 而不是按均价静默放行（取价链与不变量见 §10.25） |

前六处错配都是**静默的**——不会报错、不会变红；第七处是唯一会主动说话的：取不到价就拒单。这条差异是刻意的，见下节。

反制网（按这些事实源逐一钉住）：

- `tests/test_asset_studio_model_catalog.py`：`test_asset_studio_video_duration_options_follow_models_yaml` 断言区间模型展开成**逐秒阶梯**（wan3.0 `range(2,31)`、kling `range(3,16)`、vidu `range(1,17)`、pixverse `range(1,16)`），只认 `duration_options` 的旧调用方不会退化成三个点；`TestVideoGroupsDerivedFromArchive` 用正向逐档 + 反向排除钉住分组派生。
- `tests/test_constraint_duration_range.py`：dict 形态的 `duration` 不得塌成 `[default]`，`duration_min/max` 必须报上游区间。
- `backend/tests/test_asset_studio_video_duration_validation.py`：三个入口不再 `min(d, 15)`，越界 400 且文案含真实区间；档位模型仍精确匹配并拒绝 `-1`。
- `frontend/src/utils/__tests__/assetStudioDurationControls.test.ts` + `frontend/src/components/home/__tests__/assetStudioDurationControlSource.test.ts`：前者锁兜底表取值，后者用源码断言禁止工作台内再声明第三份时长表。

两条派生判据的结论，别再退回去：

- **分组成员用 `modality` 判据派生，不用 capability 标签**。`pixverse-v6-t2v` 在 `capabilities` 里挂了 `motion_control`（批量模板语义），但 `modality` 只有 `text_to_video`——用标签派生会把纯文生档放进动作组，用户选了它做图生视频就必然失败。
- **派生宇宙（`_VIDEO_UNIVERSE_MODEL_IDS`）本身是白名单**，档案有 `image_to_video` 但不在宇宙内的条目（如 `pixverse-c1-r2v`）不会自动进 UI。这是刻意的：它档案 `duration` 仍是 `[]`，进 UI 前要先补官方区间。宇宙成员变更时，能否真正执行由 `backend/tests/test_asset_studio_model_catalog_image_line.py` 与 `tests/test_media_runtime_executability_guard.py` 校验 adapter 与运行时白名单三层一致。

`.env` 侧的一次性提醒：`DREAMWEAVER_STORYBOARD_MIN_SHOT_S` / `MAX_SHOT_S` 在修复前**不生效**（提示词与吸附逻辑写死 2–15），放开后 env 才第一次真正决定短剧分镜区间；改这两个值时记得 `pipeline/media_presets.py` 的提示词是由常量动态拼接的，别再往提示词字面量里写数字（同类第二事实源见 §10.24）。

### 10.24 批量行级补丁：锚点必须先全验，再严格降序应用

2026-10-09 给 `config/models.yaml` 一次改 6 个模型块时踩到的。脚本自称「自底向上」，却先执行了高位插入**之下**的编辑，于是之后所有行号整体 +1，把 kling-omni 的 `duration:` 键覆盖成重复 `max`，`yaml.safe_load` 直接 `ScannerError: mapping values are not allowed here`。

规则：

1. 先**一次性**验证全部锚点（每个插入/替换位置都读原文比对），任何一处不匹配就整体不落地。
2. 再严格按行号**降序**应用。低位先插入会让高位锚点全部失效——这与「自底向上」的口误正好相反，容易写反。
3. 应用后四重验证：行数增量 == 预测增量、全文件 `yaml.safe_load`、目标块字段回读、**并行写入方的内容仍在位**。
4. 若已有并行写入方在同一文件里留下未提交改动，**不要 `git checkout` 回滚**，改为断言损坏内容后定点替换。
5. 行尾：`config/models.yaml`、`asset_studio_model_catalog.py`、本文与 `docs/ASSET_STUDIO_CATEGORY_AND_DURATION_CONTROL_GUIDE_20261009.md` 是 LF；`docs/AUDIOBOOK_TTS_PROMPT_OPTIMIZATION_GUIDE.md` 是 CRLF。对它做文本替换必须**字节级**处理并 assert 命中数，用普通文本读写会把整文件行尾翻掉，diff 看起来像重写。

### 10.25 「视频计费只是档案备注，改价不用管代码」

2026-10-09 之前成立，之后不成立。R1 A2 把 `config/models.yaml` 的 `pricing_info` 从「零生产消费方的备注」改成了**下单前置条件**：资产工作台三条视频链路（`video` / `motion` / `video_edit`）的积分冻结额直接从档案取价，取不到价就 400 拒单。改价的同步义务从 0 条变成 4 层，且**错的价不会变红，只会静默少冻或多冻**。

取价链（四层都要在位才能算出冻结额）：

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 档案 | `config/models.yaml` 各视频档 `pricing_info` | 唯一价目来源 |
| 取价器 | `backend/app/services/asset_studio_model_catalog.py:333-373`（`_per_second_tiers:340`、`resolve_video_price_per_second:349`） | 按「模型 × 分辨率档 × 有声/无声」解析每秒价 |
| basis | `backend/app/services/points_usage_pricing.py:437`（`_VIDEO_BASIS_KINDS:401`、`AssetStudioVideoPriceMissing:404`） | `max(时长, 1.0) × 每秒价 × 输出数`，四舍五入 2 位 |
| 入口 | `backend/app/api/v1/asset_studio_api/_helpers.py:1154`（`_estimate_video_basis_yuan`） | 把缺价异常映射成 `HTTP_400`，三条链路共用 |

七条不变量，改价或加档时逐条核对：

1. **读哪个键由 `unit` 决定**，不是由模型名决定：`unit: 每秒` → 读 `pricing_info.tiers[].price_per_second`；`unit: 每百万 token`（seedance 三档）→ 读 `pricing_info.per_second_estimate.tiers[].price_per_second`。这两个键名不同是**被逼出来的**：`backend/tests/test_seedance_25_contract.py::test_pricing_tiers_use_token_unit` 断言 seedance 的 `unit == "每百万 token"` 且 `tiers` 是 `{70.0, 42.0, 77.0, 46.0}` 官方 token 刊例，所以反推价不能塞进 `tiers`，只能开新键。
2. **seedance 的反推系数是「官方 5 秒示例价 ÷ 5」**，来源与口径写在 `per_second_estimate.derived_from` / `note` 里，不在代码里重算 token 公式。逐档对拍由 `test_seedance_estimate_is_official_example_divided_by_five` 钉住——改 `price_examples` 不改 `per_second_estimate` 会直接变红，这是这条链上**唯一**会自动报错的地方。
3. **档名必须落在 `pick_resolution_label` 的值域**（`480P` / `720P` / `1080P`，`core/model_resolution.py:165`）。运行时下发上游的 `parameters["resolution"]` 与取价**共用这一个函数**（原私有 `_pick_legacy_resolution_label` 已删），两侧错档就不会漏收；由 `test_runtime_and_pricing_share_one_resolution_ladder` 断言定义恰好 1 处。档案里写 `480p`、`P` 大小写以外的档名会静默取不到价。
4. **判档按短边，不按 `size_values`**：`min(width, height)` ≤480→`480P`、≤720→`720P`、否则 `1080P`。所以 `1080x1080` 是 `1080P` 而不是 `720P`（`test_square_1080_falls_into_1080p_not_720p`）。本档案的注释初稿曾按 `size_values` 描述判据，是错的，已订正。
5. **无声价只在 `audio_output=False` 时读**（`tiers[].no_audio_price_per_second`），该档未公布就回落含声价——含声恒 ≥ 无声，宁可多冻不欠收。注意三个视频端点目前**没有** audio 入参，这条分支处于休眠状态，别把它当已验证链路。
6. **缺价直接拒单，绝不回退均价**。旧的三条 env（`POINTS_ASSET_STUDIO_{VIDEO,MOTION,VIDEO_EDIT}_PER_SECOND_YUAN`，默认 0.2 元/秒）已物理删除，`test_dead_env_keys_cannot_revive_flat_price` + `test_env_templates_do_not_reintroduce_flat_price_keys` 双向钉住：0.2 元/秒在「30 秒 × 1080P」（wan3.0 实价 3.742 元/秒 ≈ 112.26 元）下欠收 18 倍，均价兜底等于已知亏损。
7. **冻结额就是实扣额**。`_settle_asset_studio_billing` 沿用冻结时的同一个 `basis_yuan`（只有音频在 `routes_audio.py:463` 按实际时长重算），估低是净损失、没有二次校正机会。同理，政策层 `build_points_business_settlement_snapshot`（`points_pricing_policy.py:310`）把 `basis_yuan` 直接当 `supplier_list_price_yuan`，所以 basis 填低时 `margin_status` 永远不会是 `negative`——毛利闸门在旧均价下是**死开关**；只有 basis 携带真实公开价且 `user_price_rate < 1` 才可能触发，由 `test_negative_margin_gate_can_fire_once_basis_carries_real_cost` 钉住。

链条上四个「已知不可达 / 已欠口」，加档时不要误以为是 bug：

- `480P` 只有 `wan3.0-video` 与三个 seedance 档有价；`kling` / `vidu` / `pixverse` 打到 480P 会 400。前端四个尺寸预设不产生该档，直连 API 传 `resolution=480p` 才会碰到。
- 档案里的 `360P` / `540P` / `4K` 档名在 `pick_resolution_label` 值域外，**永远不会被选中**：540P 尺寸会被归到 720P（多冻，安全），4K 只能按 1080P 价（当前无路径可达，`doubao-seedance-2-0` 的 `4K` 价目仅作记录）。
- `doubao-seedance-2-0-fast` 未公布 1080p 价 → 选 1080P 一律 400。注意这一例的 400 仍来自取价层：该档档案 `max_width/max_height=4096` 且声明 16:9，`1920x1080` 过得了尺寸闸门。2026-10-10 起尺寸校验改为按目标模型自己判（见 §10.27），所以真正新增被拦下的是「该档档案里认不下的画幅比/尺寸」，例如 Vidu 系只认 `16:9 / 9:16 / 1:1`，选它传 `1440x1080` 现在直接 400 点名模型，而不再进运行时换档。展示层按模型裁分辨率（通道 B）仍未做，见 guide §10.3 第 9 项——它决定用户是否会撞这些拒单，但不再影响计费正确性。
- **带参考视频的任务（编辑 / 延长）仍欠闸门化**：官方 token 用量把输入秒计入，单条实扣可高于「不含输入视频」口径的估算价；而 basis 公式里根本没有参考输入这一项。见 guide §10.3 第 10 项（该处引用的 20.12~78.25 元/5 秒在本文 §7 官方刊例表（`:731-737`）里查无对应读数，落地前需先复核）。

给新视频档模型补价的最小清单（四步，缺一步就是 400）：

1. `pricing_info.unit` 写 `每秒`，或 token 计价时加 `per_second_estimate.tiers`。
2. `tiers[].resolution` 只用 `480P` / `720P` / `1080P`，逐档给 `price_per_second`；可加 `no_audio_price_per_second`。
3. 把该模型加进 `_VIDEO_UNIVERSE_MODEL_IDS`，并确认 `test_720p_is_priced_for_every_ui_model` 变绿（该测试遍历宇宙成员，720P 无价直接红）。
4. 若档案 `constraints.resolutions` 声明含 1080P，`test_1080p_priced_unless_archive_declares_no_such_tier` 会要求 1080P 也有价。

### 10.26 退役清理的操作层踩坑（2026-10-10 深夜一轮四条）

这四条都不是模型契约问题，而是"改的过程"本身会让人误判已完成或引入静默破坏。逐条给可执行的判据：

1. **同一批里混合行尾的补丁不能走"读全文→文本重写"**。本轮同时改 `backend/**.py`、`adapters/dashscope/tts.py`、`frontend/src/**.ts`：`config/models.yaml`、`tts_model_ids.py`、本文是 LF，`docs/AUDIOBOOK_TTS_PROMPT_OPTIMIZATION_GUIDE.md` 是 CRLF。动手前逐文件统计行尾（`python -c` 读 bytes 数 `\r\n` 与 `\n`），LF/CRLF 计数对不上就用内容锚点做定点替换，绝不整文件重写——否则 diff 看起来像全文重写，真实内容改动被淹没，回滚也会连带丢掉别人的行。含反引号的补丁一律走文件工具，Git Bash 内联 `python -c` 会吃掉反引号。
2. **patch 与改写的目标必须是定义处，不是门面**。`backend/app/services/audiobook/agents/__init__.py` 再导出 `VoiceDesigner`，而 11 个 mixin 走 `from ..agents import VoiceDesigner` 拿到的是**各自的第二个 binding**；在包门面或子模块里替换名字不会传播到已经 import 走的地方，测试里 `patch("…voice_designer.VoiceDesigner")` 同样管不住 `_base.py:105` 的实例化。删符号时必须按"定义处 → 门面导出 → 每个 import 站点"三层各自处理，缺一层就是 `ImportError`（本轮正是靠 `rg` 逐站点列出才认出 11 处 import 全部无用）；`voice_designer.py` 已按这张三层清单于 2026-10-11 物理删除，见 §11.7.9。
3. **注入类脚本要断言锚点唯一，写完回读计数**。本轮同一条 Edit 被误应用两次，`RETIRED_QWEN3_SPELLING` 常量块在测试文件里出现两遍；更早一次拆分脚本给 `storyboarder_pkg` 注入了重复 dataclass。判据：写入前 `assert content.count(anchor) == 预期`（新插入应为 0 或 1），写入后回读 `content.count(marker)`，只看"命令成功"不算完成。
4. **自己造的临时文件会污染门禁扫描**。`scripts/audit_model_references.py` 的扫描集是 git tracked + `--others --exclude-standard` + env 文件，本轮在仓库根留下的 `.tmp_audit_qwen3.json` 被当成未跟踪文本扫入，虚增 19 条 must_fix——先怀疑临时文件，再怀疑代码。审计/探针中间产物写到仓库外，或用完立刻 `rm -f`；一次性排查脚本本身也属于交付后必须清理的产物（见 §10.21 与 AGENTS.md 清理条款）。

顺带两条检索陷阱，它们会直接伪造出"已清干净"的结论：`rg -r` 是**替换输出**（把命中改写成字面量）而不是递归，误用会让输出整片变成 `n`；`rg -F` 把以 `|` 连接的整串当一个字面模式，用它扫音色名列表会报"零命中"，必须改成多个 `-e` 逐条传入。

### 10.27 「视频入口参数不兼容会换个模型跑掉」

2026-10-10 之前成立，之后不成立（#26 C2）。旧契约有三段，串起来是一条**静默的错计费路径**：

1. `routes_video.py:77/:213`、`routes_video_edit.py:77` 用 `requested if requested in X_MODELS else DEFAULT_*`——点名的模型不在本链路集合里就换成默认档，冻结与结算都按**换后的档**计价，用户以为自己点的是 A；
2. 尺寸校验 `_validate_dimensions_for_models(VIDEO_MODELS, …)` 是「整组任一模型匹配」，目标模型自己档案里认不下的尺寸也能进运行时；
3. 运行时真的换档时（`result.model_id != resolved_model_id`）只在 metadata 写一句 `routing_message`，HTTP 仍 200、照旧扣费，前端把它显示成结果卡上一条 info 提示。

新契约三条不变量，加视频模型或改入口时逐条核对：

| # | 不变量 | 落点 | 锁住它的测试 |
| --- | --- | --- | --- |
| 1 | 点名的模型必须在本链路集合内，越集合直接 400 并回吐可选清单 | `_helpers.py:_resolve_requested_video_model`，三个入口共用 | `backend/tests/test_asset_studio_video_model_routing.py::TestStrictModelResolution` |
| 2 | 尺寸按**目标模型自己**的档案区间与画幅比判，报错点名那档模型 | `_validate_dimensions_for_models({resolved_model_id}, …)`（单元素集合走模型点名文案分支） | 同上 `::TestDimensionsJudgedByTargetModel` |
| 3 | 运行时仍换档 = 拒单且不计费，绝不交付换档产物 | 三处在 `_build_response` / 结算之前 raise 400，冻结由外层 `except` 的 `_release_asset_studio_billing_safely` 释放 | 同上 `::TestEntriesKeepNoSilentSwitch` |

三条结构性事实，改之前必须知道：

- **判定基准是归一化后的 ID**。`_resolve_requested_video_model` 先过 `normalize_model_id`，所以历史别名（如 `kling-v3-video-generation` → `kling/kling-v3-video-generation`）仍能原样执行；反过来，只往 catalog 加了档案、没加进对应链路集合的模型，用户点名会拿到 400 而不是被执行——这是刻意的，缺集合成员就等于缺一条已验证的执行链路。
- **兼容性判断不能下放给运行时**。`core/unified_media_runtime.py:_rank_candidates` 在 preferred 被候选池过滤掉（blocked 信号、任务不兼容、能力要求不匹配）时返回的是**排好序的其它候选**，而 `use_fallback=False` 只做 `candidates[:1]` 截断，并不校验那一个是不是 preferred。等到 `result.model_id` 出来再判，上游调用已经发生、供应商成本已经产生，只能退款不能预防——所以入口必须自己按档案预检（时长 `_validate_video_duration`、尺寸 `_validate_dimensions_*`），运行时那道比对只是兜底闸门。
- **空 model_id 仍回落默认档，这不是静默**。三个入口在调用解析器之前就用 `Form` 默认值或 `or DEFAULT_*` 填好，属文档化默认；400 只针对"用户明确点名了一个本链路不支持的模型"。

同轮的另一处收敛（短剧分镜侧）：`agents/storyboarder_pkg/_run.py` 容器模式的镜头上下界不再写死 5~15，改为调用 `pipeline.media_presets.dreamweaver_beat_duration_bounds_s()`——与剧本阶段 beat 区间**同一个派生函数**，env 只能在官方 [2, 30] 内收窄。此前剧本按 2-30s 写 beat、分镜把 20 秒的容器压回 15 秒，是同一份档案的第二处事实源；`preferred_shot_s` 仍是 15 秒（那是规划偏好，不是钳制），幻灯片模式保留 3~10 秒（ffmpeg 不受视频引擎区间约束）。

### 10.28 「视觉评审的实现天然只属于百炼」

不是。2026-10-12 之前，`analyze_image` / `analyze_video` 写在 `adapters/dashscope/chat.py` 的 `_DashScopeVisionReviewMixin` 里，客户端构造（base_url + `DASHSCOPE_API_KEY`）与评审结构（素材编码、提示词、JSON 解析）绑死在同一个类上，于是档案里早已声明视觉理解能力的 `qwen-plus`（Qwen3.7 Plus）和豆包 Seed 2.1 两档接不进来——白名单、catalog 分组和页面名单就一起冻结在了两档。

现在的形状：执行层在 `adapters/_shared_vision_review.py::VisionReviewMixin`，供应商子类只实现 `_vision_client()` 与 `_vision_disable_thinking_kwargs()` 两个钩子。关思考的载荷写法目前已知三种，互不通用：百炼 Qwen3.7/3.6/3.5/VL 用顶层 `extra_body={"enable_thinking": False}`，方舟用 `extra_body={"thinking": {"type": "disabled"}}`，Qwen3.8 Omni Flash 只认 OpenAI 标准顶层参数 `reasoning_effort="none"`（`enable_thinking` 不在它的适用清单里，混用会静默保留默认 xhigh 思考）。接一档新视觉模型要同步四处，缺一处就是不同的坏法：

| 落点 | 缺了会怎样 | 常驻判据 |
| --- | --- | --- |
| adapter 混入 `VisionReviewMixin` 并 `@register_model` | 运行期 `adapter_missing`（"有档案不等于有实现"） | `tests/test_media_runtime_executability_guard.py::TestVisionAnalysisIsExecutable` |
| `config/models.yaml` 的 `modality` 补 `image_understanding` / `video_understanding` | 显式点名也在路由期 `does not support`（`_rank_candidates` 按 modality 过滤） | 同上 |
| `core/unified_media_runtime.py` 的 `analyze_image` / `analyze_video` 白名单 | 候选集里没有它，页面选了也走不到 | `tests/test_vision_review_multi_provider.py` |
| `backend/app/services/asset_studio_model_catalog.py` 的 `vision_review` 分组 | 入口 gate 400；分组还必须落在白名单之内，否则前端可见、后端拒单 | 同上（分组 ⊆ 白名单判据） |

关思考是新档位的硬前提，不是优化项：豆包 Seed 2.1 两档开思考实测 39.8s/40.8s、输出 1900+ tokens，关闭后 9.4s/15.7s、363/398 tokens；Qwen3.7 Plus 开思考 40.1s、关闭 11.1s；Qwen3.8 Omni Flash 生产评审提示词下开思考 22.3s（图）/12.4s（视频）、多吃 1655/651 reasoning tokens，`reasoning_effort="none"` 后 6.4s/4.3s。思考链与正文共用 `max_tokens` 预算，评审提示词的 JSON 稍有长度就会被吃成空 content，表现为"成功但空结果"而不是报错。

评审判据必须自带扣分下限，否则模型按"看着顺眼"打分。2026-10-12 用 21 条素材（11 条真实产物 + 5 条本地可控退化锚点 + 6 条抽帧图片，每条先用 ffprobe/OpenCV 算客观真值）对三档做 63 次真实调用，测出三档共同的失效模式：整段偏暗（实测平均亮度 33.5）的 `lighting` 一律 9.8，后 4 秒完全冻结的 `smoothness` 给到 8.5。修法是 `VISION_CRITERION_RUBRICS` 把逐维度扣分下限写进 `build_vision_review_prompt`，并要求 comment 给出画面证据。**这条约束的措辞顺序敏感**：把"冻结必须扣分"写在前面会把慢镜头误判成冻结，把"低运动量不扣分"写在前面真冻结又漏检，两条并列后仍只有部分档位能同时判对，改判据文案必须用锚点复测，不能只读一遍就发。

两个已经花真钱排除掉的"看起来该做"的优化：① 抽帧率不是冻结漏检的原因——`video_url` part 上的 `fps` 兄弟字段（官方默认 2.0、范围 0.1~10，百炼与方舟五档都接受不报错）实测 2/4/8fps 下判分恒定 8.5，视频 token 却从 3062 涨到 12248，因此执行层**没有**接入 `fps`；② `response_format={"type":"json_object"}` 能让 JSON 100% 可解析，但 Qwen3.8 Omni Flash 延迟从 6~9s 涨到 22~33s，未采纳。该档遗留约 7%（3/42）输出不可解析（`finish_reason=stop`、正文看起来完整，疑为字符串内裸换行），另两档 0 次，命中时页面降级为纯文本展示。

**这 7% 的收口方式（2026-10-12，不花钱的那条路）**：`parse_vision_review_content` 先按严格模式解析，失败后以 `strict=False` 重试一次——只放宽"字符串里的裸控制字符"这一项，其余语法错误仍判失败，不做猜测式修补。同时把 `finish_reason` 与 `vision_parse_failed` 写进 metadata：降级必须能归因，`length` 指向预算被思考链或长正文吃光（该加 `VISION_MAX_TOKENS`），`stop` 指向正文本身非法（该修解析），缺这两个字段时线上只看到"成功但纯文本"，下一次还得再花真钱复现。**据此判定不动 `VISION_MAX_TOKENS=1200`**：三次失败实测都是 `finish_reason=stop` 且正文看起来完整，截断假设被现有证据否定，在没有新证据前放宽预算只会重复付费思考 token。加重试同样被否：评审是交互调用，自动重试等于按失败率翻倍付费，而失败已经可降级展示。

**产品入口退役（2026-10-12 收口）**：三档测评的结论是"检出率打平、判词质量差一个档次"，`qwen3.5-omni-plus` 无任何维度胜出却是 3.8 的约 11 倍单条成本，`qwen3-vl-plus` 同样只剩"能用"。视觉线产品入口因此收敛为四档（`qwen-plus`、`qwen3.8-omni-flash`、`doubao-seed-2-1-lite`、`doubao-seed-2-1-pro`），`vision_review` 与 `dreamweaver_vision` 两个分组同源，默认档分别取 `qwen3.8-omni-flash`（工作台只走 analyze_*）与 `qwen-plus`（短剧）。`qwen3.5-omni-plus` 已按物理退役处理：档案卡、`@register_model` 装饰器、`analyze_image`/`analyze_video` 白名单四处全删，登记进 `RETIRED_MEDIA_MODELS`（承接 `qwen3.8-omni-flash`）。

这片改动暴露出**不在常规盘点视野里的隐藏事实源**，摘档位前必须逐条确认（第 1~3 条来自 Slice A，第 4~7 条由 Slice B 补出）：

1. **运行时白名单被短剧 QC 线共用**。`pipeline/autoqc_pkg/_utils.py` 经 `adapters.adapter_helpers.analyze_*` 直连 `media_runtime`，所以从 `_OPERATION_MODEL_IDS` 摘掉一档，等于同时摘掉 QC 线；而存量项目配置里存过旧档位名，先摘会让已保存项目直接拒单。因此本片只把 `qwen3-vl-plus` 从产品入口摘掉、在白名单留作过渡项，分组判据相应从"逐字相等"降为"⊆"。Slice B 迁完后**已恢复逐字相等**（`tests/test_vision_review_multi_provider.py::test_vision_catalog_group_equals_allowlist`）。
2. **短剧的 `vision_model` 会同时喂给 `chat_messages`**（`pipeline/autoqc_pkg/_semantic_match.py:76` 以 `model_id=vlm_adapter` 发非流式 chat 并要 `json_object`）。omni 档在 compatible-mode 下的非流式 chat 从未验证过，把 3.8 直接设成短剧默认档等于引入未验证路径——这是"默认档取 `qwen-plus` 而非效果更好的 3.8"的唯一原因。**Slice B 已把这条顾虑作废掉**：注册表里的对话适配器只有 `generate`、没有 `chat`，退役前的 vl-plus 也一样（它继承 `_DashScopeChatAdapter`），所以 `chat_messages` 对任何模型 ID 都是死路，语义匹配从来就没通过；`dreamweaver_vision` 分组默认档因此保持 `qwen-plus` 不动，QC 线的 `semantic/state/clip` 三个适配器默认档按裁定指到 `qwen3.8-omni-flash`（走的是 `analyze_*` 白名单那条真跑通的路）。
3. **评审采信方与"哪些模型在评"是两件事**。`audio_understanding.py` 硬写 `_DOUBAO_MODEL = "doubao-seed-2-1-lite-260915"`，往 `SCORER_MODELS` 里加第二档豆包会"挂 pro 名跑 lite"；档案层也只有 4 档声明 `audio_understanding`（豆包 pro 不在内）。同日按盲评结论把 `SCORER_MODELS` 收成两档（只留两个采信方）：横评集是"评估评分器本身"的实验产物，不是生产采信组合，多出的档位每段音频都重复付费却不产出任何被采信维度。

**物理退役第二片（Slice B，2026-10-12 收口）**：短剧 QC 线迁到 `qwen3.8-omni-flash`（`pipeline/autoqc_pkg/_utils.py` 等六处 `DEFAULT_*_VLM_ADAPTER` 常量副本 + `DREAMWEAVER_SEMANTIC_VLM_ADAPTER` / `DREAMWEAVER_STATE_QC_VLM_ADAPTER` 两行 env 同批改，只改一边就会漂移），视觉档位从 QC 线彻底消失。这一片补出第四条、也是最容易漏的事实源层级：

4. **兼容层是退役的第五层事实源，且漏改后零报错**。除档案卡 / `@register_model` / `analyze_*` 白名单 / catalog 分组外，旧 ID 还活在 `adapters/legacy_runtime_wrappers.py::_RUNTIME_WRAPPER_CLASSES`（表键是**下划线形态**，不是点分形态）、`adapters/model_adapters.py::ModelAdapterFactory._ENV_PREFIX_MAP` 与 `_DEFAULT_MODEL_NAME_BY_ENV`、`core/model_resolution.py::MODEL_ALIASES`。这些表全部是**查不到就返回 None**的软失败：`create_runtime_wrapper` 未命中返回 None，`_resolve_runtime_model_id(require_available=True)` 返回 None，`_run_helpers.py:26-56` 用 `get_model_info` 守卫把 QC 开关静默置 False，`vlm_chat_json` 对 None 直接早退。所以"退役没退干净"的症状不是拒单，而是 **QC 永久关闭且无任何报错**——比拒单难发现得多。
5. **门禁的 env 扫描按键名语义过滤，`*_VLM_ADAPTER` 是口径盲区**。`scripts/audit_model_references.py` 的 `ENV_MODEL_KEY_RE` 只认含 `MODEL` 的环境变量键，短剧这两个适配器键不在其中，`--all-retired --expect-zero` 归零也证明不了 env 已收口；本批靠手工盘点改掉取值，口径扩展未做（扩了会让其它退役 ID 的基线一起变动）。
6. **消费侧传"模型 ID 字符串"还是"适配器对象"决定兼容层能不能删干净**。`agents/vlm_utils.py::vlm_chat_json` 与 `agents/best_image_selector.py::select_best_candidate` 两种形态都支持：字符串分支走 `adapter_helpers`，对象分支走 `create_runtime_client`。把 `asset_library` 的并行分支改成传字符串后，`create_runtime_client` 对该档的调用整体消失，legacy wrapper 才能整块删除而不留向后兼容残骸。
7. **注册中心自动导入清单的 try/except 在 for 循环内部**（`adapters/registry.py:161-164`）：删模块文件不删列表项只会静默丢该模块；但 `adapters/dashscope/__init__.py` 的 `from ... import *` 指向已删模块时是整个包 ImportError。两处必须同批改。

同批核实的一条既有坏链路（与退役无关，已单独立项）：`adapter_helpers.chat_messages` 要求注册适配器有 `chat` 方法，而百炼/方舟的对话适配器只有 `generate`——四个现役视觉档与退役前的 vl-plus 全都 `hasattr(adapter, "chat") == False`，`chat_messages` 对任何模型 ID 都直接走 `from_error`。短剧语义匹配 `_semantic_match.py:76` 因此本来就是死路，**不是本片把可用路径改坏的**，但把 QC 默认档指到 3.8 也不等于把它修活。

同轮修复门禁自身一个静默盲区：`scripts/audit_model_references.py` 用 `git ls-files` 取清单，git 默认 `core.quotepath=true` 会把非 ASCII 路径转义、Windows 下 `text=True` 又按本地编码解码，两者叠加后**396 个中文命名文件在清单里却读不出内容**，等于从未被审计（暴露出 99 条真实残留）。现按 `-c core.quotepath=false` + UTF-8 解码取清单，并由 `test_every_scanned_path_resolves_to_a_readable_file` 钉住"清单里每个路径都必须是真实文件"。

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

### 11.4 豆包 Seed-TTS 2.0 Expressive 接入要点

#### 11.4.1 模型与鉴权边界

豆包 `seed-tts-2.0-expressive` 走 Volcengine Seed Speech / openspeech TTS 接口，不走百炼 DashScope，也不走火山方舟 OpenAI 兼容对话接口。

| 项 | 当前接入基线 |
| --- | --- |
| 注册 ID | `seed-tts-2.0-expressive` |
| provider | `volcengine` |
| 默认 resource id | `seed-tts-2.0` |
| 合成主路径（双向流式） | `wss://openspeech.bytedance.com/api/v3/tts/bidirection`，由 `_call_seed_tts_websocket()` 走官方二进制帧协议 |
| HTTP 兜底端点（非流式） | `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`，仅当 WS 抛出含 `no audio` 的 `RuntimeError` 时使用 |
| API Key 环境变量 | 优先 `VOLCENGINE_TTS_API_KEY`，兼容 `DOUBAO_TTS_API_KEY`、`SEED_TTS_API_KEY`、`VOLCENGINE_SPEECH_API_KEY`、`DOUBAO_SPEECH_API_KEY` |
| Resource 环境变量 | `VOLCENGINE_TTS_RESOURCE_ID` 或 `DOUBAO_TTS_RESOURCE_ID` |

关键规则：

- `VOLCENGINE_API_KEY` / `VOLCANO_ENGINE_API_KEY` 通常用于火山方舟模型端点，不能默认当作 Seed Speech TTS 密钥。
- `DOUBAO_API_KEY` 通常也是方舟/OpenAI 兼容端点密钥，项目不会再把它回退用作 Seed-TTS 的 `X-Api-Key`。
- `DASHSCOPE_API_KEY` / `ALIYUN_API_KEY` 只用于百炼 TTS、Qwen、Wan 等百炼模型，不应复用到豆包 Seed-TTS。
- 双向流式 PDF 明确要求 `X-Api-Key` 和 `X-Api-Resource-Id`。
  ✅ 2026-10-10 实测并修复：单向 HTTP 端点**在请求头带 `X-Api-App-Key` 时返回 200 但响应体没有音频**（官方头形状 11/11 出音频，加上该头 0/4；证据 `docs/TTS_PROMPT_EVIDENCE_20261010.md` §12.2）。`_call_seed_tts_http` 已去掉该头，并在 `tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_http_call_uses_volcengine_v3_endpoint` 里用 `assert "X-Api-App-Key" not in headers` 钉住——**不要加回来**。
  注意 `prompt_audio_asr_provider.py:485` 的 Volcengine ASR 通道仍发该头：不同端点，无证据表明有害，未动。

#### 11.4.2 请求体基线

有声小说合成链路的**主调用路径是 WebSocket 双向流式**：`_synthesize_seed_tts`（`_aliyun_mixin.py:463`）先调 `_call_seed_tts_websocket()`（`wss://openspeech.bytedance.com/api/v3/tts/bidirection`，可用 `SEED_TTS_WS_ENDPOINT` 覆盖），只有 WS 抛出含 `no audio` 的 `RuntimeError` 时才回退到 HTTP 非流式端点（`:471-483`），payload 由 `TTSEngine._build_seed_tts_http_payload(...)` 生成。两条路径的 payload 字段形状一致，下文以 HTTP builder 为例。2026-10-11 真实冒烟（17 字、`zh_female_vv_uranus_bigtts`、走生产 `TTSEngine.synthesize`）证实 WS 单次调用即返回 25965 字节 ID3 头 MP3、端到端 1630ms、ffprobe 3240ms，没有触发 HTTP 兜底；此前 `docs/SEED_TTS_WEBSOCKET_VERIFICATION_STATUS.md` 记录的 2026-06-25 两次 99 音色 WS 批量验证 0 成功（`backend/tests/seed_tts_websocket_verification_results*.json`），是二进制帧协议修好之前的历史快照，不能当作现状引用。

```json
{
  "user": {
    "uid": "audiobook"
  },
  "req_params": {
    "model": "seed-tts-2.0-expressive",
    "speaker": "zh_female_vv_uranus_bigtts",
    "text": "要合成的文本",
    "text_type": "plain",
    "with_timestamp": 0,
    "audio_params": {
      "format": "mp3",
      "sample_rate": 24000,
      "speech_rate": 0,
      "loudness_rate": 0
    },
    "additions": "{\"context_texts\":[\"用温柔但疲惫的青年女性声线朗读，语速偏慢，句尾保留轻微气声。\"]}"
  }
}
```

模型感知风格控制规则：

- 有声小说的角色、场景、情绪、声音描述和演绎要求统一交给 `tts_style_control.build_model_style_control(...)`。
- 对豆包模型，风格控制模式为 `doubao_query_response`。
- 输出位置是 `req_params.additions` 字符串内的 `context_texts`，不要拼到正文里。
- `context_texts` 是语音指令，不应作为正文朗读内容处理。
- 按官方 V3 协议和真实接口验证，`additions` 字段类型是字符串；项目会把 `{ "context_texts": [...] }` 序列化为 JSON 字符串后发送。

#### 11.4.3 语音指令、引用上文与标签

`D:/cuigu/Documents/豆包语音_语音指令与标签_1780036074.pdf` 补充了三类控制入口：

| 控制方式 | 官方含义 | 项目映射 |
| --- | --- | --- |
| 语音指令 | 控制整体情绪、方言、语气、语速快慢、音调高低等 | 写入 `req_params.additions` JSON 字符串中的 `context_texts` |
| 引用上文 | 输入合成文本的上文，只引用不合成，让模型承接语境情绪 | 优先作为 `context_texts` 的语境材料；真实接口验证后再决定是否独立建 `context_reference` 字段 |
| 语音标签 | 在句子前用方括号写表情、心理、肢体动作等局部细节 | 显式标签模式下把 `inline_audio_tags` 合成为 `[标签]正文`，并在 `additions` JSON 字符串中设置 `use_tag_parser=true` |

⚠️→✅ 实测结论（2026-10-10 当晚定稿，`docs/TTS_PROMPT_EVIDENCE_20261010.md` §9.4 / §12.1 / §13 / §16）：**方括号前缀 `[标签，标签]` 无论开不开 `use_tag_parser` 都会被朗读出口**。同台词同音色下 n1（前缀＋parser）6024 ms 与 d4（前缀、不带 parser）6024 ms 逐毫秒相同，ASR 两次都把前缀念成"克制悲伤，语速偏慢"；而同一音色的 `<cot text=…>` 语法 6 次（g5b/g5c/d3 三轮）全部转写干净、时长与念稿基线同量级——说明该音色**会解析标签，只是不认 `[a，b]` 这种前缀形状**。
影响范围按代码事实限定：只有 `style_control_method ∈ {audio_tags, tags, label, labels, voice_labels}` 的片段会走 `[a，b]` 前缀（`tts_style_control.py:815-827`；`:843` 只要前缀存在就同时发 `use_tag_parser=true`），不是全量章节。项目里**目前没有 Cot 渲染路径**（`tts_style_control.py` grep 无 `<cot`），把 `_render_doubao_voice_label_prefix`（`:557`）改成官方 `<cot text=…>` 包裹是待批准的修复动作。

方括号标签示例：

```json
{
  "req_params": {
    "model": "seed-tts-2.0-expressive",
    "speaker": "saturn_zh_female_keainvsheng_tob",
    "text": "[旁白，语调惊恐，强调触摸到尸体般触感的恐怖]可当他的手触碰到对方的身体时，却感觉一阵冰冷僵硬。",
    "text_type": "plain",
    "with_timestamp": 0,
    "audio_params": {
      "format": "mp3",
      "sample_rate": 24000
    },
    "additions": "{\"context_texts\":[\"承接前文悬疑氛围，保持压低音量和克制恐惧。\"],\"use_tag_parser\":true}"
  }
}
```

注意：

- 语音标签属于官方“抢鲜体验”，文档明确说明后续会持续优化，不能在真实验证前把稳定性写成已确认。
- 官方示例要求先确定音色为可爱女生、调皮公主、爽朗少年、天才同桌，或使用声音复刻 2.0 模型复刻后的音色；这四个在我们目录里的真实 ID 是 `ICL_uranus_zh_female_keainvsheng_tob`、`ICL_uranus_zh_female_tiaopigongzhu_tob`、`ICL_uranus_zh_male_shuanglangshaonian_tob`、`ICL_uranus_zh_male_tiancaitongzhuo_tob`，且都带 `supports_inline_voice_labels: true`。上面示例里的 `saturn_zh_female_keainvsheng_tob` 是官方 PDF 写法，在当前 277 条目录里 0 命中（目录按 `uranus_bigtts` / `ICL_uranus_*_tob` 过滤，`saturn_*` 全族不在其中）；2026-06-25 的历史探针（`scripts/verify_seed_tts_voices.py`，已于 2026-10-11 删除）探测过 6 个 `saturn_*_tob`，全部返回音频，所以它们是供应商侧有效 speaker，只是我们目录不展示、拿不到中文名和标签支持标记。照抄官方示例能出声，但不该作为项目默认音色引用。
- `supports_inline_voice_labels` 目前只是目录里的静态标记（277 个音色中 184 个 true、93 个 false），**生产代码不读取它**：`tts_style_control.py` 只看片段的 `style_control_method` 决定是否拼 `[标签]` 前缀并置 `use_tag_parser=true`，与所选音色是否支持标签无关。因此“逐音色标签稳定性”既没有真实验证，也没有代码层面的保护，属于已知缺口。
- 没有显式选择标签模式时，不要自动把所有声音描述改写成方括号标签；默认仍使用 `context_texts`，保持稳定。

#### 11.4.4 Expressive 与 Standard 的差异

按双向流式官方 PDF：

| 模型 | 适用结论 |
| --- | --- |
| `seed-tts-2.0-standard` | 标准版，时延更低；不支持 `context_texts`，不支持 `use_tag_parser` |
| `seed-tts-2.0-expressive` | 高表现力版；支持 `context_texts` 与 `use_tag_parser`，但效果可能有波动 |

实测补充（2026-10-10，`docs/TTS_PROMPT_EVIDENCE_20261010.md` §9 G4/G5、§12.1 C 组）：

- `context_texts` **只有首个元素有效**，其余被忽略；官方标注它**不计费**（不 metered）。
- `model=expressive` 与 `context_texts` **可以共存**，上表若被读成"互斥"是错的（G4 无 400，两版时长 3072/2832 ms、转写一致）。
- `context_texts` 的**情绪引导不成立**：G4 人耳裁定"整体轻快平淡，没实现"。`additions` 里只写情绪关键词 ≠ 表演被实现。
- `additions` 必须是**JSON 字符串**而不是对象；WS 双向帧的 code 语义：`0` = 进行中（可携带 sentence 文本，**不是音频**）、`20000000` = 完成，把 0 帧当音频会导致静默产出坏文件（已在 `SEED_TTS_OK_FRAME_CODES` 修复）。

项目内当前只把 `seed-tts-2.0-expressive` 暴露给有声小说模型选择，因为有声小说朗读依赖情绪、停顿、声线和场景指令。

#### 11.4.5 音色与复刻状态

- 当前系统音色目录在 `shared/seed_tts_2_0_voices.json`，实际 **277 个音色**（`updated_at: 2026-08-02`，来源为官方 2.0 目录并按 `uranus_bigtts` / `ICL_uranus_*_tob` 过滤）。旧文档写的“99 个”是建档当时拿到的清单条数；`test_seed_tts_voice_catalog_contains_doubao_20_expressive_voices` 里的 `voice_count >= 99` 只是下限守卫，不应当作实际数量引用。
- 默认旁白音色为 `zh_female_vv_uranus_bigtts`。
- 目录中的 `voice_type` / `speaker` 才是接口 `req_params.speaker` 应传的真实值（V3 协议没有 `audio_params.voice` 字段），音色中文名只用于展示。
- **逐音色可用性已由 2026-10-11 音色画像批量闭合**：`backend/app/scripts/tag_voice_profiles.py` 用生产合成链路（`core.unified_media_runtime.synthesize_speech`，即 Seed-TTS 的 WebSocket 主路径）逐音色出音频，再过客观闸门（时长、静音比、RMS、ASR 转写相似度），结果写入 `shared/seed_tts_2_0_voice_profiles.json`：**277 条 `objective.passed` 全为 true**，来源分布 264 `synthesized` + 13 `local_cache`（本地缓存本身也是早前真实合成），时长 2040–14856 ms，转写相似度普遍 1.0。据此可以判定 `backend/tests/seed_tts_voice_verification_results.json`（2026-06-25，7 成功 / 92 失败，失败全是 `200 + text/plain` 无音频）是**脚本侧假失败**：生成脚本 `scripts/verify_seed_tts_voices.py`（已于 2026-10-11 删除）发送了 `X-Api-App-Key`，而 2026-10-10 已实测该头会让单向端点返回 200 但无音频；06-25 失败的那 92 个 speaker 本次逐条重新合成全部通过。**这份 92 失败不能读成"92 个音色无效"。** 未验的只剩标签维度——画像批次用的是无标签纯台词（267 条唯一 `preview_text`，0 条带 `[标签]` 前缀），所以"逐音色标签稳定性"仍是缺口。
- **声音复刻未接入**：项目里没有 `seed-icl-2.0` 复刻创建调用，也没有豆包复刻资产链路（复刻工作台只有 CosyVoice、MiniMax、StepAudio、MiMo 四个），`voice_reference_asset_repository.py` 虽把 `voice_clone` 列为合法 `reference_kind`，但没有任何生产调用方产出该类型资产。能力声明已在 2026-10-11 统一降级为不支持：`tts_model_ids.py` 风格能力表、目录卡 `capabilities`、`voice_manager_seed_tts.get_model_info()` 三处 `supports_voice_clone` 均为 `False`，`config/models.yaml` 卡片 `modality` 去掉了 `voice_clone`，前端 `FALLBACK_TTS_MODEL_CAPABILITIES` 同步为 false，并由 `test_seed_tts_voice_clone_is_declared_unsupported_across_sources` 钉住三处一致。
- 复刻音色对应 resource id 可能是 `seed-icl-2.0`；涉及付费资产、状态机、音色确认和 `use_tag_parser` 条件，不能直接复用系统音色逻辑。首次正式使用有 **138 元槽位费**（`custom_voice_pricing.postpaid_slot_first_formal_use_yuan`，纯台账、代码不消费），开通前需用户单独确认。
- `validate_voice()` 仍对目录外 speaker 放行：这是刻意的透传容错（账号内其它合法 speaker 本地无法校验，只能由供应商判定），`test_seed_tts_voice_manager_preserves_explicit_clone_speaker_id` 钉住该行为，不代表已支持复刻。

#### 11.4.6 响应解析与测试

Seed-TTS HTTP 响应可能是音频二进制，也可能是 JSON 中携带音频字段。当前解析逻辑需要兼容：

- `audio/*` 二进制响应。
- JSON 顶层 `audio`、`data`、`output`、`result`。
- 嵌套字段 `audio`、`data`、`audio_data`、`binary`、`url`。

最小回归测试：

```bash
python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"
python -m pytest "backend/tests/test_project_audio_runtime.py" -q
```

真实接口验证前，不要把 `pending-runtime-validation` 从模型标签中移除。

### 11.5 TTS 模型的 Voice ID 管理

#### 11.5.1 VoiceManager 的作用

`VoiceManager` 维护预设音色与 TTS 语音 ID 的映射关系：

```python
# voice_manager.py
PRESET_VOICES = {
    "Neil": {"tts_speaker_id": "Neil", ...},
    "Serena": {"tts_speaker_id": "Serena", ...},
    "male_narrator": {"tts_speaker_id": "Neil", ...},  # 别名
}
```

#### 11.5.2 语音 ID 规范化

不同 TTS 模型可能使用不同的语音 ID 格式：

| 模型 | 语音 ID 示例 |
| --- | --- |
| MiniMax | `male-qn-qingse`, `Chinese (Mandarin)_News_Anchor` |
| Qwen | `Neil`, `Serena`, `Cherry` |
| 豆包 Seed-TTS 2.0 | `zh_female_vv_uranus_bigtts`, `saturn_zh_female_keainvsheng_tob` |

`_normalize_speaker_id` 方法应根据模型类型返回正确的语音 ID。注意它在 `tts_engine_pkg/_aliyun_mixin.py:469` 有「空值直接返回空串」的早退，分支里写 `or 默认音色` 是无效的，见 §11.7.6。

### 11.6 TTS 预览功能调试清单

当 TTS 预览失败时，按以下顺序排查：

1. **检查模型 ID 格式**
   - [ ] MiniMax 模型是否带 `MiniMax/` 前缀？
   - [ ] Qwen 模型是否为 `qwen3-tts-instruct-flash` 或 `qwen3-tts-plus`？⚠️ 2026-10-10 17:40 起 `qwen3-tts-instruct-flash` 在端点持续返回 `404 Model not exist`（同日 15:00 同 key 同端点还 200），但上架目录仍列该模型——碰到该 404 先查 §11.9 第 8 条，不要误判为密钥或端点问题。
   - [ ] 豆包模型是否为 `seed-tts-2.0-expressive`，且 `X-Api-Resource-Id` 是否为 `seed-tts-2.0`？

2. **检查语音 ID**
   - [ ] 选择的语音是否在对应模型的可用列表中？
   - [ ] 是否需要做语音 ID 格式转换？

3. **检查请求体**
   - [ ] MiniMax 是否包含 `action: tts` 字段？
   - [ ] Qwen 是否有 `voice` 和 `language_type` 字段？
   - [ ] 豆包是否把音色放在 `req_params.speaker`，把音频参数放在 `req_params.audio_params`，并把风格控制放在 `req_params.additions` JSON 字符串的 `context_texts`？

4. **检查响应解析**
   - [ ] MiniMax 音频数据是否为十六进制编码？
   - [ ] Qwen 音频数据是否直接在 `output.audio` 字段？

5. **检查 API 端点**
   - [ ] 是否使用 `multimodal-generation/generation` 端点？
   - [ ] 是否排除了旧的 `text2audio/text-to-audio` 端点？

6. **检查环境变量**
   - [ ] `DASHSCOPE_API_KEY` 或 `ALIYUN_API_KEY` 是否已设置？
   - [ ] 豆包 Seed-TTS 是否设置了专用语音合成密钥 `VOLCENGINE_TTS_API_KEY`，并按权限需要设置 `VOLCENGINE_TTS_RESOURCE_ID=seed-tts-2.0`？
   - [ ] 如果只配置了 `VOLCENGINE_API_KEY` 或 `DOUBAO_API_KEY`，应先到豆包语音/Seed Speech 控制台确认是否获得 openspeech 的专用 `X-Api-Key`。

### 11.7 Qwen-Audio 3.1 TTS Flash 接入要点（2026-10-10，全部结论来自真实调用）

新增而非替换：`qwen3-tts-instruct-flash` 仍是默认模型（`DEFAULT_AUDIOBOOK_TTS_MODEL` 未动），3.1 排在模型列表第 2 位。

#### 11.7.1 端点与请求体和 Qwen3-TTS 完全不同

| 项 | Qwen3-TTS Instruct Flash | Qwen-Audio 3.1 TTS Flash |
| --- | --- | --- |
| 端点 | `/api/v1/services/aigc/multimodal-generation/generation` | `POST /api/v1/services/audio/tts/SpeechSynthesizer` |
| 音色字段 | 顶层 `voice` / `language_type` | `input.voice` |
| 指令字段 | 顶层 `instructions` + `optimize_instructions` | `input.instruction`（无 optimize 开关） |
| 音频返回 | `output.audio` 内联 | `output.audio.url`（约 24 小时有效，需下载落盘） |
| usage | 字符数 | 同时返回 `characters` 与 `input/output/total_tokens` |

鉴权仍是 `DASHSCOPE_API_KEY` 的 Bearer，legacy 域名直接可用，**不需要 WorkspaceId**。

#### 11.7.2 音色体系跨模型不互通

3.1 的音色 ID 统一带 `_v3.1` 后缀，把 Qwen3 的 `Cherry` 等音色传给 3.1 会返回 `400`（code 411）。所以 3.1 **不能复用** `voice_catalog.py` 里 qwen3 的音色过滤逻辑，也不能走 `_normalize_speaker_id` 的 Qwen 预设映射分支——它的音色必须原样透传。项目侧的隔离由 `backend/tests/test_audiobook_tts_model_ids.py::test_qwen_audio_31_voice_catalog_is_isolated_from_qwen3_voices` 钉住（68 条、全部 `_v3.1`、与 qwen3 音色集不相交）。

#### 11.7.3 官方音色页计数不可信，必须逐条实调

官方列表页标称 69（另一处渲染出 73），实际逐条真实调用只有 **68** 个可用，全表已固化到 `shared/qwen_audio_3_1_tts_voices.json`（`voice_catalog.py:25` 指向它）。`config/models.yaml` 档案卡的 `voice_catalog.total_count` 与该 JSON 的同名 ID 集合由 `tests/test_model_metadata_catalog.py::test_qwen_audio_31_tts_catalog_matches_runtime_voice_list` 双向对齐——档案与运行时音色表分叉会直接变红。

#### 11.7.4 正文与 instruction 都远超 Qwen3，不要套用旧上限

实测正文 3000 / 6000 / 10000 字均返回 200（项目侧 1470 字实测产出完整 17.5 MB wav），instruction 写到 4000 字仍返回 200 且**不计入 `input_tokens`**。因此：

- 3.1 **不进入** `_is_qwen_tts_model()`（`startswith("qwen3-tts")`）那条 600 字校验与 `QWEN_RENDER_CHUNK_MAX_CHARS=360` 分块分支，走与 stepaudio/mimo/seed 相同的默认分块策略；
- 也不进入 `_fit_qwen_instruction_payload_to_limit()`；指令裁剪只由能力矩阵的 `instruction_budget: 1200`（`tts_model_ids.py:133`）在风格控制层完成。

#### 11.7.5 按 token 计费的 TTS 怎么落到按字符的计费链

项目 TTS 全链按 `price_per_10k` 记账，而 3.1 按 token 计价（输入 1.5 / 输出 12 元每百万 tokens）。实测 `usage.characters ≈ 1.93 × len(text)`，据此折算：长文本约 0.285 元/万字、短文本带 instruction 约 0.42 元/万字。结论是**不改计费链语义**，在档案与 CATALOG 里写保守的派生等效价 `0.4`，并用 `pricing_basis: derived_from_token_price` + `pricing_source: alibaba_model_studio_token_price_probe_2026-10-10` 标明来源；后续 token 单价变动时这个折算值要重测，不能沿用。

#### 11.7.6 `_normalize_speaker_id` 的空值早退让 `or DEFAULT` 变成死代码

`_aliyun_mixin.py:413` 的 `_normalize_speaker_id` 首行是 `if not raw_speaker_id: return ""`，写在其后的 `return raw_speaker_id or XXX_DEFAULT_VOICE` 分支**永远不会命中**（stepaudio、seed 的同类分支同样是死代码）。所以默认音色必须写在调用点：`_synthesize_qwen_audio_31`（`:606`）用 `self._normalize_speaker_id(...) or QWEN_AUDIO_31_DEFAULT_VOICE` 兜底，否则空 speaker 会发出 `{"input": {"voice": ""}}`，服务端回 `400 Request voice is invalid!`。给新模型加默认音色时，先看这个谓词的第一行，别在分支里加 `or`。

#### 11.7.7 参数越界的报文有误导

`rate: 0.4`、`volume: 101` 返回 400，但错误文案指向的是别的字段（报文与真实越界字段错位）；`format: opus` + `sample_rate: 22050` 组合返回 500 而不是 400。排查时不要照抄报文文案去找字段。

#### 11.7.8 落点清单（再加一个百炼 TTS 模型时逐处对齐）

| 层 | 位置 |
| --- | --- |
| 模型 ID / 顺序 / 别名 | `backend/app/services/audiobook/tts_model_ids.py:11`（常量）、`:133`（风格能力）、`:305`（CATALOG 卡片） |
| 音色目录映射 | `backend/app/services/audiobook/voice_catalog.py:25` → `shared/qwen_audio_3_1_tts_voices.json` |
| 引擎分发 | `_aliyun_mixin.py:439`（`_synthesize_aliyun` 分支，必须在 `_is_qwen_model()` **之前**）、`:691` 合成、`:2352` 指令组装、`:2380` HTTP 调用；谓词在 `_minimax_mixin.py:398` |
| 媒体运行时白名单 | `core/unified_media_runtime.py:46`（`synthesize_speech` 模型集合） |
| 模型验收用例 | `backend/app/services/audiobook/tts_test_unit.py` 的 `_MODEL_TEST_CASES[QWEN_AUDIO_31_TTS_FLASH_MODEL]` |
| 前端模型表 | `frontend/src/pages/audiobook/ttsModels.ts`（`TTS_MODELS`、`DEFAULT_NARRATOR_BY_MODEL`、`TTS_MODEL_LABELS`、`TTS_MODEL_ALIASES`、`FALLBACK_TTS_MODEL_CAPABILITIES` 五处同步） |
| 档案卡 | `config/models.yaml` 的 `qwen-audio-3.1-tts-flash`（`check_model_integration.py` 按 `NON_ADAPTER: 语音类模型由 TTSEngine 直连` 分类，无需写 adapter） |

#### 11.7.9 退役的第二条隐藏事实源：音色 ID（门禁不扫它）

`scripts/audit_model_references.py` 只按**模型 ID**扫描。换代后旧模型 ID 消失了，但它的**音色名**作为普通字符串继续散落在活代码里——门禁全绿、测试全绿，线上只表现为"这一句没有音频"。2026-10-10 逐处排查确认的落点与处置：

| 位置 | 症状 | 处置 |
| --- | --- | --- |
| `adapters/adapter_helpers.py:build_legacy_tts_request(default_speaker=…)` | 三个调用点的兜底把旧默认声线发给上游 → 无效 voice 报错 | 默认值改成 `None`，留空由各模型自己的默认声线接管；没有默认声线的模型（cosyvoice-v3.5-plus 只吃复刻/设计音色）显式拒单 |
| `agents/character_manager.py`（音色档案缺失时）、`agents/audio_sync_manager.py`（对话下发） | 短剧链路把旧声线名发给 3.1，异常被 `except` 吞成静默丢音 | 兜底取 `QWEN_AUDIO_31_DEFAULT_VOICE`，由 `tests/test_agents_dreamweaver_tts_defaults.py` 锁住"下发的 model_id + 声线必须在现行目录内" |
| `backend/app/services/audiobook/voice_manager.py::_match_voice_by_traits` | 反派快路径与末位降级返回旧声线名 → `PRESET_VOICES[…]` KeyError，整章音色分配中断（这一类**会**变红，但只有覆盖反派分支的测试才会） | 反派改为目录内高张力声线（`huozhuoshi_v3.1` / `longanyuanfei_v3.1`），末位降级返回预设键 `male_narrator` |
| `backend/app/api/v1/audiobook_api/routes_segment_regen.py`（未选音色且项目映射未命中时） | 片段试听接口把旧声线名发给现役模型，用户端只见"试听没声音" | 2026-10-11 定案：接口层**不再持有音色名**，未命中时下发空 `speaker`，由各模型载荷组装点兜自己的默认（`_aliyun_mixin.py:1069/1137/1294/1491` + `_synthesize_qwen_audio_31`）。唯一例外是 MiniMax——空音色会被 `_call_dashscope_minimax_http` 直接抛 `TTSUserInputError`，所以保留接口侧常量；cosyvoice 继续显式 400 |

**收尾判据**（每次 TTS 换代都要跑一遍）：从旧音色表取出全部音色 ID 当字面量清单，在 `backend/app`、`adapters`、`agents`、`core`、`frontend/src`、`config` 里扫引号命中，逐条分类为「活代码兜底 / 目录真值表 / 测试夹具 / 注释留痕」。测试夹具里保留旧声线名可以接受（尤其断言是"目录查不到"时），**活代码里的兜底不行**。音色默认值按层归属，不要跨层抄：某家模型的默认声线只能写在该模型自己的载荷组装点（`_aliyun_mixin.py` 的 `_synthesize_*` / `_build_*_payload`），**路由与接口层一律不持有音色名**——那里写死一个名字，等于按 A 家的音色空间替 B、C、D 家做决定，换代时必漏。判据是「空 `speaker` 传到底后，每家兜出来的是不是自己目录里的音色」，已由 `backend/tests/test_audiobook_tts_provider_payloads.py`（四家空值边界）与 `backend/tests/test_qwen_tts_voice_compat.py::test_every_engine_default_voice_is_in_its_own_active_catalog`（默认值必须在自家目录）钉住。

**角色音解析失败的口径（2026-10-11 由"静默跳过"改为"拒单"）**：`apply_project_voice_mapping()` / `load_from_db()` 过去对解析不到的 `voice_id` 只 `logger.warning` 后 `continue`，被跳过的角色随后落到 `assign_voice()` 自动分配——整本书少一条用户显式指定的声线，任务仍然报成功，测试也不会变红。这是退役教义下最后一条活着的静默失败面，现已改为抛 `VoiceMappingResolutionError(ValueError)`（`voice_manager.py:151`），与 `validate_project_voice_references` 同口径：配置错误继承 `ValueError`，路由层直接 400，后台任务按失败收口。改法有两条**必须先满足否则整个改动是死代码**的前置条件：

1. **callee 变严格 ≠ 调用方看得见。** 当时四处消费点（`background_jobs_audio.py`、`background_jobs_full.py::_apply_project_audio_effects`、`background_jobs_scripts.py::_apply_script_stage_project_audio_config`、`segment_preview_service.__init__`）全都把这次调用包在 `try/except Exception → logger.warning` 里，只改 `voice_manager.py` 会让新异常在第一层就被吞掉。收口方式是把这些吞异常包装删掉、统一走共享 helper `project_audio_runtime.apply_runtime_voice_mapping()`（`project_audio_runtime.py:175`），helper 自身不做异常处理。
2. **宿主降级白名单要显式开口。** 音效/快照等其它项目级配置失败可以降级继续，角色音不行，所以两个宿主 `except Exception` 前必须加 `except VoiceMappingResolutionError: raise`（`background_jobs_full.py`、`background_jobs_scripts.py`）；否则"能降级的宿主异常"会把刚建立的严格性又吃掉一层。试听与重生成两个入口在构造 `SegmentPreviewService` 处捕获它并转 400（`routes_segment_preview.py`、`routes_segment_regen.py`）。

保留的三处容错**不是漏洞**，口径要读准：`voice_id` 为空＝用户没指定，仍走自动分配；`tts_model` 来自智能推荐且与音色归属模型不一致时，先回退默认模型再解析一次（`suggest_model_for_character` 会把默认模型音色路由到 minimax/cosyvoice，这条不回退就会误拒合法配置），只有用户显式钉死 `tts_model` 的越界才拒单；自定义音色（`mimo_design:` 等前缀）委派所属模型解析失败同样拒单，理由写"自定义音色"。`background_jobs_scripts.py::_load_existing_voice_mapping` 的容错按测试裁定保留（`test_load_existing_voice_mapping_keeps_voice_manager_failures_non_blocking`）——那是读取历史映射的旁路，不是下单路径。写入采用"先全部解析、后统一落表"的原子批处理，拒单时引擎不会留下半配置的 `character_voices`。判据由 `backend/tests/test_audiobook_voice_mapping_strict_resolution.py`（12 条：逐条列出越界角色、原子性、推荐档位回退、委派失败、跨模型合法配置仍生效、`load_from_db` 拒单、helper 透传、脚本阶段透传）钉住。**推广教训：给共享层加"变严格"的收口时，先清点有几个调用点用 `except Exception` 包住它、宿主 `except` 是否会二次吞掉，这两步漏掉任何一步，新异常都到不了用户面前。**

（2026-10-11 已物理删除）`backend/app/services/audiobook/agents/voice_designer.py` 整模块退役：`VoiceDesigner` 与它的 8 条旧声线表、`TTSParams.speaker` 默认 `Ethan` 一并消失，音色分配活链路只剩 `VoiceManager.assign_voice` + `voice_description_policy`。裁定前的完整取证：生产链路对它**零方法调用**（`engine_pkg/_base.py:105` 只实例化），`design_voice` 仅被同文件 `batch_design` 自调、`get_tts_params` 仅被稳定性测试调用，`_base.py` 与 10 个引擎 mixin 的 `from ..agents import VoiceDesigner` 在函数体里**零使用**（只是各自的第二个 binding，见 §10.26 第 2 条），`audio_director.py` 的 `agent_name="VoiceDesigner"` 只是任务标签且唯一读者是 `next_steps` 展示文案，`AgentType.VOICE_DESIGNER` 全仓零引用，外部同名 `VoiceProfile` 命中全部来自 root-level `agents/voice_consistency_manager.py`（另一个模块）。连带清理清单：`agents/__init__.py`（docstring 「6 个专业化Agent」改 5 + import + `__all__`）、`_base.py` 与 10 个 mixin 的 import、`_base.py:105` 实例化、`_parallel_mixin.py` 两条「而不是 VoiceDesigner」式过时注释、`audio_director.py` 的音色任务项 + 只为它服务的 `AdaptationStrategy.voice_differentiation` 字段（删任务项后该字段已无任何读者）、`agent_message.py` 的 `AgentType.VOICE_DESIGNER` 枚举成员与 `ScriptMessage` docstring。两条正向断言测试按裁定一起删除：`test_audiobook_voice_description_policy.py::test_voice_designer_generates_multidimensional_actionable_description`、`test_audiobook_voice_parameter_stability.py::test_legacy_voice_designer_does_not_emit_pitch_across_segment_emotions`；「不输出 pitch」这条收口并未失守，同文件其余用例（`test_voice_profile_does_not_emit_pitch_across_segment_emotions`、`test_pipeline_voice_assignment_drops_all_segment_pitch_fields`、`test_workbench_preview_drops_all_segment_pitch_fields`、`test_candidate_contract_drops_all_segment_pitch_fields`）继续覆盖活链路。**要恢复这段行为时按现役音色目录重写测试，不要按旧声线表重写。**

（2026-10-10 已处置）`voice_description_policy._VOICE_AGE_HINTS`：键全是旧声线名，而该函数的 `entry` 只来自 `get_voice_entry()` 读静态目录，因此可达输入被完全枚举——现役 9 个模型目录共 450+ 条音色，与表键的交集只有 `mimo-v2.5-tts` 的英文预置音 `Mia`（与旧代际重名），其表值 `"青年"` 恰等于兜底默认。据此删除整张表，年龄计算塌成 `catalog_profile.get("age_group") or "青年"`，等价性实测为 0 条差异（目录自带 `age_group` 的条目仍优先）。

（2026-10-10 深夜再清一层）退役 TTS 的六处同源残骸已物理删除，`scripts/audit_model_references.py --all-retired --expect-zero` 的待处理引用由 25 条归零：

| 位置 | 处置 |
| --- | --- |
| `tts_model_ids.py` 的 `RETIRED_QWEN3_TTS_MODEL_ID` 与 6 条字面 alias | 删除常量，折叠收敛到 `normalize_audiobook_tts_model` 的前缀分支；行为逐条实测（`qwen3-tts-instruct-flash`、大小写混写、`qwen3-tts`、`qwen3_tts`、`qwen3-tts-plus`）折叠结果与单价 0.4 与改前完全一致 |
| 前端 `ttsModels.ts` 的 `TTS_MODEL_ALIASES` 旧 ID 项 | 同样删除，`normalizeTtsModelValue` 补前缀规则——该函数原本只有查表、**无兜底分支**，删字面量不补前缀会让历史配置原样透传给上游 |
| `shared/qwen3_tts_voices.json` / `shared/qwen3_tts_voice_profiles.json` | 物理删除。证据：65 张现役音色表全部文本列 0 命中、无代码引用、无动态文件名拼接，`VOICE_FILENAMES_BY_MODEL` / `VOICE_PROFILE_FILENAMES_BY_MODEL` 不指向它们（3.1 画像文件缺失时按空表处理） |
| `adapters/dashscope/tts.py` 基类 `VOICE_ID` | `longxiaochun` → `""`。基类不兜底任何声线：留空时 `_normalize_runtime_request` 不下发 `speaker`，由上游默认接管；线名只在各 `@register_model` 子类里声明 |
| `scripts/analyze_model_integration.py` TTS 探针 | `voice="Cherry"` → `voice="longsanshu_v3.1"` |
| 门禁 `ALLOWED_LAYER_PREFIXES` | 新增 `backend/tests/test_audiobook_tts_model_ids.py`、`backend/tests/test_audiobook_tts_provider_payloads.py`（折叠行为与"旧 ID 不在任何注册表"的反向断言**必须写出旧 ID 本身**，否则断言无从写起）与 `backend/data/tts_debug/`（付费探针原始台账，改写等于篡改实验数据）。两个测试文件因此改用模块内本地常量 `RETIRED_QWEN3_SPELLING`，产品代码不再持有退役名 |

### 11.8 Qwen-Audio 3.1 TTS Next（Audiogen）接入要点（2026-10-10，全部结论来自真实调用）

`qwen-audio-3.1-tts-next` 与 §11.7 的 Flash **同一个端点、同一套鉴权，但不是同一类模型**：它是「按提示词生成音频」的 Audiogen，不是带音色朗读的 TTS。因此它没有进有声书引擎，而是作为适配器进了资产工作台音效链路。下面每条都是与 Flash 那节不同、且踩过才知道的。

#### 11.8.1 同端点不等于同契约：不吃 `text` + `voice`

请求体是 `input.text_prompt`（可选 `input.references`），**没有** `text`/`voice`/`instruction`。最危险的一点：把 `voice` 塞进去服务端**照单返回 200 并静默忽略**（实测 `voice_field` 用例 status=200、code=None），报错路径完全不走。所以适配器不转发 `voice`，遇到音色类入参只能在本地显式拒绝——依赖上游报错会拿到一段「成功」的错误音频。

#### 11.8.2 参考音频契约与场景链路天然冲突，据此决定不并入 `audio_scene`

`input.references` 每条**必须且只能**给 `audio_url` 或 `audio_data` 二选一（缺一个或都给都是 400 `Each reference must specify exactly one of 'audio_url' or 'audio_data'.`），最多 3 条、每条 ≤30s/≤10MB，提示词里用 `@voice1`..`@voice3` 按数组顺序引用。而资产工作台 scene-audio 分支提交的 references 是 `[{"speaker": ...}]` 音色 ID 形态，两者不兼容：`_validate_references` 对「有 speaker 且无 audio_url/audio_data」直接抛 `does not accept speaker voice IDs; provide audio_url or audio_data instead`。结论是**只进 `audio_sound_effect` 分组**（sound-effect 分支传 `references=None`），不并入场景链路。

#### 11.8.3 加新适配器必须同时改两处，且常量要带模型前缀

- `adapters/dashscope/__init__.py` 的 star import：新模块只加到这里不够；
- `adapters/registry.py:_ensure_builtin_registration` 的 `module_names` 必须列**叶子模块**（列包名时 reload 不会重跑 `@register_model`，表现为注册表里查不到而测试里手动 import 能查到）。

`adapters/dashscope/*` 与 `adapters/volcengine/*` 都通过 `import *` 汇入 `adapters.dashscope` 命名空间，`DEFAULT_AUDIO_CONFIG`、`SUPPORTED_FORMATS` 这类通用名会互相覆盖。本模块常量统一加 `QWEN_AUDIO_31_TTS_NEXT_*` / `QWEN_AUDIO_NEXT_*` 前缀，默认配置用 `QWEN_AUDIO_NEXT_DEFAULT_CONFIG`。

#### 11.8.4 上游传来的 `audio_config` 是豆包口径，越权键要「丢弃 + 留痕」而不是报错

音效路由传的是 `adapters/volcengine/audio_generation.py` 的 `DEFAULT_AUDIO_CONFIG`，里面 `pitch_rate`、`speech_rate`、`loudness_rate`、`enable_subtitle` 四个键本模型根本没有。对这些既不能 400（会打断已经调通的路由），也不能静默吞掉（排查时看不见参数去哪了），处理是：白名单内的键进 `input`，其余收进 `_dropped_params`，成功结果里落到 `result.metadata["dropped_params"]`。真实调用实测 `dropped=['pitch_rate','speech_rate','loudness_rate','enable_subtitle']`，与预期一致。

#### 11.8.5 参数越界这次是干净的 400，本地校验必须前置

与 §11.7.7 里 Flash 的「报文错位」相反，Next 的越界报文都直接点名字段，且全部 400 `InvalidParameter`：`channels=3`→`channels must be either 1 or 2.`；`sample_rate=22050`→`Unsupported sample_rate: 22050`；`format=opus`→`Unsupported format: opus`；`rate=2.5`→`rate must be within [0.5, 2.0].`；提示词 3001 字→`text_prompt exceeds the maximum length of 3000 characters.`；references 4 条→`references must not exceed 3 items.`。合法枚举与区间是 format ∈ {wav,mp3,pcm}（**输出**不接受 opus，参考音频可以）、sample_rate ∈ {8000,16000,24000,44100,48000}、channels ∈ {1,2}、rate ∈ [0.5,2.0]、volume ∈ [0,100]。既然上游报错这么清楚，适配器就先把同一批约束在本地拦住（`_validate_audio_params`），不花一次真实调用去换 400。

#### 11.8.6 没有 duration 入参：时长由提示词决定，结算只认响应里的真实秒数

和 mureka-o1-instrumental 忽略 duration 是同一类问题——模型侧根本没有时长入参。实测 5 秒档位请求返回 `output.audio.duration=3.96`（响应体里另有 `usage.duration=4`，那是**向上取整的计费秒**，不能当时长用）。适配器把真实秒数写进 `result.metadata["duration"]`，由 `_resolve_billed_audio_duration_seconds` 按实际时长结算。一次真实调用的金额对比：冻结按请求 5s 是 0.20，结算按 3.96s 是 0.16。

#### 11.8.7 token 费率与 Flash 不同，派生价必须单独重测

Next 按 token 计价（刊例输入 6 / 输出 12 元每百万 tokens），实测关系是 `output_tokens = 200 × 音频秒数`（792 = 200 × 3.96 精确成立）、`input_tokens ≈ 152 + 2.1 × 提示词字符数`。据此在档案里写派生等效价 `0.003 元/秒`（0.18 元/分钟），`pricing_basis: derived_from_token_price` + `source: bailian_qwen_audio_31_tts_next_api_probe_2026-10-10`。同一次调用供应商实付 0.01093 元，与档案价吻合。这个换算**换模型版本就作废**，不能从 §11.7.5 的 `1.93 × len(text)` 那套字符口径沿用。

#### 11.8.8 限流与产出上限

QPM 3（周期 1），单次产出上限：播客形态 ≤240s、其余 ≤120s；音频 URL 约 24 小时有效（`output.audio.expires_at`），必须走 `_materialize_output_reference` 下载落盘。延迟实测 16–25s，档案 `avg_latency_seconds=20.0`。

### 11.9 TTS 提示词写法与风格控制档案纠错（2026-10-10，G1–G7 门槛 + B1/B2 写法批次）

事实源是 `docs/TTS_PROMPT_EVIDENCE_20261010.md`（下称"证据文档"），本节只搬结论与落点，**编号按证据文档 §8 的清单顺序展开，其中 §8 第 1 条（stepaudio）在本节拆成"预算"与"能力位"两项，故本节多一条**。每条标注"实测状态"和"是否改生产行为"**：标 `[文档]` 的已经写进本文档、无需改代码；标 `[字段]` 的对应 `tts_model_ids.py` / `config/models.yaml` 里的能力位或预算，一改就改生产出站内容，**逐条待批准，本节假日未动任何字段**。

1. **stepaudio-3-tts instruction 上限**：官方 500 字符，我方档案与能力矩阵写 200（`tts_model_ids.py:246`）。244 字 instruction 实测 HTTP 200（G3，纯客观层），所以 200 是**项目自设、无官方依据**（其实是 2.5 代限制）。`[字段]` **200→500 已于 2026-10-11 实施**：单点常量 `_aliyun_mixin.py:36`、能力位 `tts_model_ids.py` `instruction_budget`、`catalog_note`、`config/models.yaml` 四处（capability description / `constraints.instruction_max_chars` / limitations / `contextual_control.global_context.max_chars`）、前端兜底表 `ttsModels.ts` 及其测试全部同步。**还有一处容易漏的第五事实源**：场景引擎喂给 LLM 的表演提示词里也硬写了上限（`script_adapter_pkg/_transform.py` StepAudio 分支 3 处：特性行、instruct_block 两行、contract_reminders 一行），并由 `tests/test_audiobook_prompt_contracts.py` 用 `assert "200 字符" in prompt` 钉住——已于同日改为 500 并同步钉测试；改上限时必须连带扫提示词，否则剧本层仍按旧额度压缩 performance_notes。这五处现在由
`test_stepaudio_budget_and_transport_declarations_agree_across_all_fact_sources`（`backend/tests/test_audiobook_tts_model_ids.py`）
一次性钉死，漏改任一层测试直接变红。`scripts/probe_tts_capability_gates.py` 里"绕过自限 200"的注释与 `docs/TTS_PROMPT_OPTIMIZATION_AND_OMNI_SCORING_PLAN_20261010.md` 取证表同步更新。**实测副作用要记一条**：预算从 200 抬到 500 后，原先被砍到 200 的组装 instruction 现在能完整出站（钉测试样本 222 字不再截断）；而 ≈330 字的长 `voice_description` 在 500 预算下仍放不下，按优先级规则依旧整段丢弃——`test_stepaudio_style_control_preserves_key_cues_within_instruction_budget` 的 `"声音描述：" not in instruction` 继续成立。**注意 preview 端点没有单独取证**，`/audio/voices/preview` 与 `/audio/speech` 共用同一个 500 常量。
2. **stepaudio-3-tts 的三个能力位无官方依据**：`supports_emotion_mixing / supports_micro_tags / supports_word_level_control` 全为 `True`（`tts_model_ids.py:236-238`）来自旧档案描述，官方文档没有"复合情绪 / micro tags / 词级韵律"这套说法；另实测 **`voice_label` 情绪枚举对 3-tts 会报错**。`[字段]` 删除或改 false 待批准——消费方实测如下，改动前逐处对齐：`supports_word_level_control` 是**行为门禁**（`segment_direction_service.py:586,588` 用它决定是否接受重音/拖尾意图），`supports_emotion_mixing / supports_micro_tags` 目前只进**目录展示**（`model_catalog_bootstrap.py:524-525,538-539`），`instruction_budget` 则是**裁剪行为**（`tts_style_control.py:665-667,914`）。
3. **qwen3-tts-instruct-flash instruction 预算**：档案 600（`tts_model_ids.py:128`）无官方依据，官方为 **1600 Token**。`[字段]` 待批准。`[文档]` `instructions` / `optimize_instructions` 实际发在 **`parameters`** 且服务端接受、影响时长（G1 客观层：三条 3360/4000/3680 ms、ASR 干净）；但**关键词式情绪指令没有产出表演**（人耳裁定 g1b"语气无低落感"），要效果得用官方"场景＋人物状态＋发声方式＋台词处理"句式。
4. **minimax-2.8 的 `style_control_modes:["basic"]` 不成立**：`tts_model_ids.py:154,167` 把两个 2.8 型号标成 basic，并因此触发"不支持风格控制"的降级告警。实测（G2）`emotion` 枚举被接受且时长分化（calm 5000 / sad 5793 ms），`<#1.5#>` 定时停顿确实透传生效（8249 ms 且转写无"1.5"、无标签词）。官方有 `emotion` 7 档＋括号语气词＋注音＋`voice_modify`。`[字段]` 待批准。
5. **seed-tts-2.0-expressive 缺项**：档案未记 `audio_params.emotion` / `emotion_scale`、未记 Cot 标签语法与 **64 字符限制**、未记 `context_texts` 只首值有效且不 metered。已在 §11.4.3 / §11.4.4 就地补写。`[文档]`
6. **mimo 的 `voice_design_instruction_mode` 是自造说法**（`tts_model_ids.py:206`）：官方无此字段；"导演模式"应描述为**自然语言的进阶写法**，不是一种独立官方模式。另需补"台词必须在 `assistant` 消息里"的契约说明。G6 只测了情绪粒度，**未覆盖本条**，标注为"待验证"。`[字段]` 待批准。
7. **cosyvoice-v3.5-plus 的 100（`tts_model_ids.py:147`）数值一致，但口径要写明是"加权字符"**，≈55 个汉字；不写口径会让人以为能放 100 个汉字。`[文档]`
8. **`[标签，标签]` 前缀被朗读——当晚升级为"生产形状也确证"**：见 §11.4.3 的 ⚠️→✅ 块。事实是**带不带 `use_tag_parser` 都被朗读**（n1 6024 ms 与 d4 6024 ms 逐毫秒相同、ASR 逐字一致），同一音色 Cot 语法 6 次全部干净 → 污染范围＝显式标签模式（`audio_tags/tags/label/labels/voice_labels`）的片段，不是全量章节。修复动作是把 `_render_doubao_voice_label_prefix`（`tts_style_control.py:557`）改成官方 `<cot text=…>`（项目当前无 Cot 渲染路径）。`[字段]` 待批准。
9. **`qwen3-tts-instruct-flash` 于 2026-10-10 17:40 起持续 `404 Model not exist`**，同日 15:00 同 key 同端点还返回 200，而上架目录 `models/groups/qwen3-tts-instruct-flash.json` 仍列该模型（0.8 元/万字符）。该 ID 是生产默认（`tts_model_ids.py:10` `DEFAULT_AUDIOBOOK_TTS_MODEL`），硬编码还散落在 `app/schemas/audiobook.py:16,28,130,365`、`app/api/v1/projects.py:492,535,632`、`app/services/asset_studio_model_catalog.py:55,90`、`app/api/v1/audiobook_api/routes_segment_regen.py:98`、`app/api/v1/asset_studio_api/_constants.py:64` → 一旦正式下架，qwen3 链路全线失败。探针已临时改用同价位在架的 `qwen3-tts-flash`；**注意 §12.1 A 组显示 `qwen3-tts-flash` 对情绪指令无时长响应**，切默认可能同时丢掉情绪控制面，所以"切过去"不是无损动作。`[字段]` 待裁定。
10. **stepaudio-3-tts 的 `supports_streaming: True` 是未取证的上游能力声明**（本条为 2026-10-11 追加，编号延续 §8 清单之后的新发现）：档案卡自己两处明写"非流式"（`config/models.yaml` summary 与 integration notes），生产链路 `_call_stepaudio_speech_http` 只发 `POST /v1/audio/speech` 并整包接收、metadata 固定 `transport="http"`，payload 无 `stream` 布尔，只有白名单透传 `stream_format ∈ {sse, audio}`（`_aliyun_mixin.py:1174`）且响应侧没有 SSE/chunked 解析。与 §11.12 的 MiMo 口径区别在于：MiMo 的布尔**有**真实流式取证支撑、缺口在我方消费；StepAudio 连上游都未取证，因此 2026-10-11 裁定把 `tts_model_ids.py` 风格能力表与目录卡两处降为 `False`，并由 `test_stepaudio_streaming_is_declared_unsupported_across_sources` 钉住。`[字段]` **已实施**。影响面：前端全仓零 `supportsStreaming` 消费者，但该布尔会经 `GET /tts/models` 的 `capabilities` 原样下发（`routes_tts.py:1186`）。要恢复先按 TTS-12 待办做真实流式取证。

写法层结论（跨模型可复用的部分，细节见证据文档 §11/§12）：

- **圆括号标签是干净的停顿通道**：stepaudio 的 `（停顿）` 类写法（s3）是本轮唯一有客观信号的写法，三轮 1.61/1.30/1.20×；正文圆括号标签未被朗读。
- **写法红利不可跨模型移植**：MiMo 上最好的"官方三段式【角色】【场景】【指导】"与"动机前置式"，换到 qwen3-tts / stepaudio / 豆包都没有对应增益。**每个模型的写法必须各自 A/B**。
- **时长判据是非对称的**：同台词同音色下时长稳定放大＝指令被采纳的充分证据；**时长不放大 ≠ 未采纳**（B1 人耳已证假阴性，b1c/b1d 没变长但被判定"像表演"）。±15% 内记"无信号"，因为基线自身三轮极差就有 q5 1.13×、s5 1.28×、d5 1.11×。
- **对照实验必须复刻"生产实际发出的完整形状"**，包括 headers 和开关字段。本轮两次归因错误都源于只控 body：HTTP 侧漏控 `X-Api-App-Key`（§12.2），豆包侧漏控 `use_tag_parser`（§13）。

### 11.10 音频评分采信分工（2026-10-10 盲评复测裁定）

qwen3.8-omni-flash 在**情绪/表演维度上会编造证据**：盲评（提示词里删掉"本轮下达的表演要求"）复测 13 条，三条已有人耳真值的样本上主评仍然反向——g1b 称"明显哭腔与颤抖"、g4b 称"委屈质问"、g6a 称"语气急促带质问感"，置信度 0.82–0.95，分数比锚定更高。据此确立分工，代码单点定义在
`backend/app/services/audiobook/scene_quality/audio_score_contract.py` 的 `tts_dimension_authority()`：

| 维度 | 采信模型 | 理由 |
| --- | --- | --- |
| `emotion_match`、`prosody_pause`、`voice_identity`、`overall_naturalness` | `doubao-seed-2-1-lite` | 情绪类证据不可靠，qwen3.8 会复述指令 |
| `fidelity`、`contamination` | `qwen3.8-omni-flash` | 有 ASR/文本可交叉验证，属客观类 |

- **模型意见一致 ≠ 真值**；人耳裁定永远是最终真值，评审链固定为：客观层（ffprobe 时长 + ASR 逐字 + HTTP 状态）→ 盲评描述 → 人耳裁定。
- `parse_audio_score` 的 `kind` 参数区分 `tts` / `audiogen` 两套完整 rubric，**audiogen 维度没有 TTS 采信方**，调用 `tts_dimension_authority` 直接 `ValueError`，不做默认回落。
- **打分组合已收成两档（2026-10-12）**：`SCORER_MODELS` 原为四档，是 2026-10-10"同时评估评分器本身"的实验横评集，不是生产采信组合。采信分工只需要 `qwen3.8-omni-flash` + `doubao-seed-2-1-lite` 两个权威，多出的档位每段音频都按 12 元/百万 token 的音频输入价重复付费却不产出任何被采信维度，因此与视觉线退役同批删除。两个坑记在这里：① `audio_understanding.py` 硬写 `_DOUBAO_MODEL = "doubao-seed-2-1-lite-260915"`，往评分器里加第二档豆包会"挂 pro 名跑 lite"，必须先改成逐档线名映射；② 档案层只有 4 档声明 `audio_understanding`，`doubao-seed-2-1-pro` 不在内且从未评过音频。`qwen3.5-omni-flash` 仍是有声书场景语义评审的默认档（`qwen_omni_reviewer`），它不参与打分，收档不影响它。
- 探针脚本 `probe_tts_gate_scoring.py` 默认 `--mode blind`，输出表按"采信方 / 采信分 / 参照方"排版，锚定表头明确标注"不作为结论来源"。
- 回归：`python -m pytest backend/tests/test_audiobook_audio_score_contract.py -q`。

### 11.11 Qwen-Audio-3.1-ASR-Flash 接入与 Fun-ASR-Flash 退役（2026-10-11）

有声书客观层/字幕 ASR 从 Fun-ASR-Flash 整体切到 `qwen-audio-3.1-asr-flash`，旧模型物理退役。
这条链路**只有 HTTP 契约**：模型线名不进 `config/models.yaml`、不进注册中心、不进目录卡片，
所以 §10.19 那张门禁表对它天然是盲区，事实源在 `backend/app/services/audiobook/prompt_audio_asr_provider.py`
与 `backend/.env.example` 两处。

**契约事实（官方文档口径，`bailian-docs-llm-wiki`）**

- 端点与旧通道相同：`POST {base}/api/v1/services/aigc/multimodal-generation/generation`，
  `X-DashScope-SSE: enable`，音频以 `input_audio.data = "data:{mime};base64,..."` 直传，
  **不需要公网 URL**。因此 `app/scripts/probe_prompt_audio_asr.py`（只收 `--audio-url`，
  choices 限 `aliyun` / `doubao`）不适用于本通道，别指望用它验证。
- 响应形态非标准：句子可能在 `output.output.sentence`，也可能在 `output.sentence`；
  `usage` / `request_id` 同样可能落在事件层或 `output` 层。逐字时间戳把标点单列在
  `words[].punctuation`，字幕要按标点重切分段。
- SSE 中间结果只在音频**不少于 1 分钟**时才分多帧返回；短音频（本项目的场景片段只有几秒）
  可能只给一条结果，且 `sentence_end` 未必为真。代码保留两级兜底：
  `_asr_flash_collect_sentences()` 拿不到已完成句子时，用 `_asr_flash_payload_from_lines()`
  + `_asr_flash_result_from_payload()` 再解析一次——优先取末帧句子（带词级时间戳），
  退到 `output.text` 合成整段文本，此时**字幕时间轴降级为 `None`**，调用方跳过时间轴校验，
  转写仍可参与逐字保真比对。词级时间戳在 `words[].fixed = true` 后才稳定。
- 3.1 独有参数：`speaker_diarization_enabled`（默认 false；开启后结果改放 `output.sentences`，
  并使 `keep_dialect` / `language_hints` 失效）、`keep_dialect`（默认 false＝方言按普通话转写）、
  即时 `vocabulary` 热词、`language_hints` ≤4 项、上下文 `input_text` / `text` ≤5 轮且每轮 ≤400 字符。
  **`keep_dialect` 不显式下发**：默认值正是逐字保真比对需要的形态，写死反而多一处事实源。

**实测（2026-10-11，3 条真实调用，证据 `docs/evidence/asr_flash_qwen_audio_3_1_verify_20261011.json`）**

素材取音色画像的试听缓存音频（1.358 / 2.04 / 2.616 s，三条来自三个不同 TTS 模型），
`preview_text` 作逐字基准：

- 端到端耗时 0.638–0.773 s，同步单次调用即可，批量打标不必额外排队；三次 HTTP 均 200。
- 逐字相似度 **1.0 ×3**；末段字幕 `end_ms` 与 ffprobe 时长逐条一致（1358 / 2040 / 2616 ms），
  时间轴可信到毫秒，无需降级分支（短音频单帧返回时句子仍带 `words[]` 标点）。
- `usage.duration` 是**四舍五入的整秒**（1.358→1、2.04→2、2.616→3）。
  所以 `asr_attempts.actual_cost_yuan` 记的是**计费秒**口径，不能拿物理时长反推。
- `input_tokens` 74 / 83 / 90，`output_tokens` 4 / 4 / 9——输入侧**不严格线性于时长**，
  短音频带固定底量，"1 秒 = 25 Token"只是官方折算下限而非实测值。
- 按 Token 实扣 7e-5 / 7.72e-5 / 9.63e-5 元，三条合计 0.0002435 元；
  派生秒价估算合计 0.0002406 元，**总比值 0.986**。逐条比值 0.776 / 1.057 / 1.087：
  1.4 s 片段低估约 22%（底量所致），**片段越短越容易低估**，作为预算闸门是可接受方向，
  但别把它当账单。
- 未覆盖：这批样本 `preview_text` 不含数字，ITN（「六十年」→「60年」）路径本轮未复测。

**计价换代（估算 ≠ 账单，必须分开读）**

| 口径 | 内容 |
| --- | --- |
| 官方刊例 | 输入 0.8 元/百万 Token、输出 2.7 元/百万 Token；「千问Audio」折算规则 **1 秒音频 = 25 Token，不足 1 秒按 25 Token 计** |
| 代码里的秒价 | `0.00004 元/秒`，由 `25×0.8 + 6×2.7 = 36.2 元/百万 Token ≈ 3.62e-5` 推出（输出侧按中文朗读约 6 Token/秒估算），**保守上取整到 4e-5**；实测 1–3 s 片段总误差 −1.4%，逐条 −22%～+9%，**短于 2 秒会低估** |
| `pricing_basis` | `derived_from_token_price`（旧通道是 `public_postpaid`）；账单核对时不能当实扣金额读 |
| 真实账单 | 以响应的 `usage.input_tokens` / `output_tokens` 为准；`usage.duration` 是四舍五入整秒，只用于时间轴与估算 |
| 旧通道 | Fun-ASR-Flash 0.00022 元/秒（直接按秒的后付费刊例），换到 3.1 后同名时长估算降约 5.5 倍 |

场景渲染的 `asr_attempts` 记录（`scene_renderer`）会同时写估算价与 `usage.duration` 推出的
`actual_cost_yuan`，两者都带 `pricing_source`，审计时按上表口径解释。

**退役落点与门禁**

- 工厂里 `funasr_flash` / `fun-asr-flash` / `funasr` / `fun_asr_flash` 四个别名整段删除，
  传旧 provider 键直接 `asr_provider_unsupported` 硬失败——静默改写比失败更危险。
- 价目表删除 `("funasr_flash", "fun-asr-flash-2026-06-15")` 键；env 键
  `FUNASR_FLASH_ASR_MODEL` 换成 `QWEN_AUDIO_ASR_MODEL`。
- 反向断言新增 `tests/test_model_retirement_registry.py::TestAudiobookAsrRetirement`
  （线名进 `RETIRED_AUDIOBOOK_ASR_MODELS`，provider 键进 `RETIRED_AUDIOBOOK_ASR_PROVIDERS`）；
  `scripts/audit_model_references.py::retired_ledger_ids()` 增读该表，
  于是 `--all-retired --expect-zero` 才第一次覆盖"只有 HTTP 契约"的链路。
- 回归（本次实测全绿）：`backend/tests/test_audiobook_prompt_audio_asr_provider.py`、
  `test_audiobook_prompt_audio_asr_pricing.py`、`test_audiobook_seed_scene_renderer.py`（66 passed）、
  `tests/test_model_retirement_registry.py`（199 passed）、
  ASR 相邻族 126 passed；`--all-retired --expect-zero` 输出**合计待处理 0 处**
  （旧线名仅剩 docs 记录与退役登记表两处来源，均属允许层）。
- 真实调用校验见上面「实测」段与 `docs/evidence/asr_flash_qwen_audio_3_1_verify_20261011.json`；
  该校验用一次性脚本跑的（`app/scripts/probe_prompt_audio_asr.py` 只支持 `--audio-url` 的
  aliyun / doubao 通道，覆盖不到 Base64 直传），脚本按 AGENTS.md 清理条款用完即删，
  判据与数据都留在证据文件里。

**两条未闭环事实，改动前先看这里**

1. **3.1 的 native 文本润色没有 API 开关**（Fun-ASR / 3.0 的润色标注"暂未开放"），
   数字仍按 ITN 写成「60年」而试听文本是「六十年」。逐字保真比较器
   `voice_profile_tagging.transcript_similarity()` 只去标点空白（`_PUNCT_RE`），
   不做数字/同音归一，`MIN_TRANSCRIPT_SIMILARITY = 0.90` 未动——
   **换模型不解决这个缺口**，真要收敛得改比较器或改基准文本口径。
2. **`backend/.env` 的 `PROMPT_AUDIO_ASR_PROVIDER` 已从 `qwen_omni` 改为 `qwen_audio_asr_flash`**
   （2026-10-11 裁定）。此前那行覆盖让**客观层转写走的是音频理解模型**，而 `tag_voice_profiles.py`
   里写着的约束恰恰相反——"客观层必须拿逐字转写，不能被 env 默认评分器带走：后者会把要求复述成转写"。
   换回 flash 后 Seed 场景字幕恢复词级时间戳，时间轴校验不再走降级分支。
   顺带一条 env 模板勘误：`SEGMENT_DIRECTION_AUDIO_PROVIDER` **没有任何代码读取**，
   单片段口述转写在 `routes_segment_direction.py:129` 硬编码 `qwen_omni`，
   模板里那行注释掉的示例键已删除（真要 per-flow 开关得先实现，别指望设变量生效）。

### 11.12 MiMo-V2.5-TTS 三变体端到端取证（2026-10-11，结论来自真实调用）

三变体（`mimo-v2.5-tts` / `-voicedesign` / `-voiceclone`）此前只有预置音色那条有真实调用证据，
档案卡挂着 `pending-runtime-validation`。本轮跑 7 例冒烟，**走生产 `TTSEngine.synthesize()`**
（不是绕过引擎的裸 httpx），凭证为 `MIMO_API_KEY`，端点
`POST https://api.xiaomimimo.com/v1/chat/completions`，头 `api-key`，超时 60 s。

**实测事实表**

| 用例 | model | 关键 voice_params | 延迟 | 字节 | 音频时长 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 预置音色 | mimo-v2.5-tts | `speaker=mimo_default` | 3116 ms | 337964 | 7040 ms | 200，质量校验通过（rms −24.6 dBFS） |
| 文本音色设计 | -voicedesign | `voice_design_prompt` 一句中文描述 | 2559 ms | 261164 | 5440 ms | 200，通过（rms −20.5） |
| 设计 + 关文本优化 | -voicedesign | 同上 + `optimize_text_preview=false` + emotion sad | 2197 ms | 276524 | 5760 ms | 200，通过 |
| 音色复刻 | -voiceclone | 28344 B mp3 → 37792 base64 字符，`data:audio/mpeg;base64,` | 3126 ms | 230444 | 4800 ms | 200，通过（silence_ratio 0.0） |
| 复刻 + 错 MIME | -voiceclone | 同样本改 `data:audio/ogg` | 438 ms | 0 | — | 上游 400，参数校验在合成前 |
| 预置 + pcm16 | mimo-v2.5-tts | `format=pcm16` | 13022 ms | 0 | — | 我方质量校验判 `undecodable_audio`，重试 3 次耗尽 |
| 预置 + stream | mimo-v2.5-tts | `stream=true` | 1673 ms | 0 | — | SSE 响应让 `response.json()` 抛错 |

**载荷契约（逐条对上响应 metadata，非推断）**

- 台词放 `role=assistant`，风格/音色描述放 `role=user`——这条对三变体都成立，预置与复刻的
  user 消息就是生产三段式导演提示（复刻路径额外在末尾拼裸情绪词「；sad」）。
- voicedesign 的 user 消息**替换**导演提示，只放设计提示原文；带情绪时追加「；情绪目标：<emotion>」，
  与复刻路径的拼接文案不同，别当成同一个开关。
- voiceclone 的样本走 `audio.voice = data:{MIME};base64,...`，取用顺序是
  `voice_sample_data_url` → `voice_clone_data_url` → 以 `data:audio/` 开头的显式 `voice`
  （`_aliyun_mixin.py:1061`）；`mimo_clone:` 前缀的资产 id **不会**进 `audio.voice`，
  资产路径靠 `mimo_voice_assets.py:261` 把 data URL 塞进 `voice_clone_data_url`。
  我方 MIME 白名单只有 `audio/mpeg` / `audio/wav`，与上游一致。
- 上游 MIME 拒绝的响应原文（写进档案卡 `verified_parameters`）：
  `{"error":{"code":"400","message":"Param Incorrect","param":"Unsupported audio.voice source format: ogg. Supported formats: [mp3, wav]","type":""}}`。
  438 ms 即失败说明校验发生在合成前。**10 MB base64 上限未实测**（样本远小于该值），
  我方运行时也没有 MiMo 专属的字节数校验。
- 默认 `audio.format=wav` 且**不下发 `stream` 键**；`format` 白名单 `{wav, mp3, pcm16}`，
  非法值回落到 `stream ? pcm16 : wav`（`:1051-1053`，所以 `format=opus` 单传是 wav）。

**四条必须记在卡里的缺口**

1. `audio.format=pcm16`：上游正常返回**无头裸 PCM**，输出质量校验走 ffmpeg 解码失败
   （error 3199971767 / `Invalid data found when processing input`），判 `undecodable_audio`，
   重试 3 次共 13022 ms 后 `synthesize()` 返回 `b""`。**（收口前历史表现，见下方裁定）**
2. `stream=true`：响应是 SSE 不是 JSON，`_call_mimo_chat_completions_http` 的 `response.json()`
   直接抛 `Expecting value: line 1 column 1 (char 0)`。**（收口前历史表现，见下方裁定）**
   两条缺口都要求调用方**显式**把键塞进 voice_params：`backend/app` 里没有任何生产者写
   `format` / `stream` / `optimize_text_preview`（只有引擎读），所以只有测试和一次性脚本能碰到。
3. **上游 400 被引擎吞成空字节**：`synthesize()` 返回 `b""`，调用方无法区分"参数错"与"服务挂"，
   只能按可重试的服务不可用处理——档案卡与 integration note 已写明。
4. **日志口径会误导**：MiMo 实现放在 `tts_engine_pkg/_aliyun_mixin.py` 内，失败日志打的是
   「阿里云 TTS」「主提供商 aliyun 返回空音频」，按 provider 名过滤 MiMo 故障会漏。

**2026-10-11 流式裁定与收口（缺口 1/2 的处置）**

- 口径裁定：三个 MiMo 档案的 `supports_streaming: true` 与 `tts_model_ids.py` 能力面布尔**保留不动**。
  该布尔描述的是**上游协议能力**，与 `constraints.stream_audio_format: pcm16` /
  `non_stream_audio_formats: [wav, mp3]` 共同表达「上游支持、我方消费不了」；翻成 False 会把上游
  能力一并否掉，档案反而失真。这与豆包 `supports_voice_clone` 那条不同类——后者声称的是我方自己
  没建的链路，属虚假声明，已降级为 False。
- 真正面向用户的是卡片文案，不是布尔：`catalog_note` 会渲染成设置页能力说明
  （`useAudiobookVoiceCatalog.ts:118/143`、`AudiobookSetupStep.tsx:260`），`features` 进模型中心卡片。
  已删除 `tts_model_ids.py` 预置卡 `catalog_note` 的「低延迟流式输出」与 `features` 的「低延迟流式」，
  由 `test_audiobook_tts_model_ids.py` 钉住「布尔仍 True + 文案不再出现流式」。
- 收口落在**消费层**而不是协议编码器：`_ensure_mimo_transport_consumable` 在
  `_call_mimo_chat_completions_http` 组装完载荷、发出请求之前拦 `stream` 真值与
  `audio.format=pcm16`，抛 `TTSUserInputError`（接口 400，不重试、不回落、不扣费）。
  `_build_mimo_chat_payload` 保持官方协议忠实编码，`stream→pcm16` 耦合契约仍由
  `test_audiobook_tts_provider_payloads.py` 的 `..._couples_stream_to_pcm16_...` 钉住。
  三变体共用同一条 HTTP 消费路径，缺口声明已分别写入各自 limitations。
- 补裸 PCM 解码 + SSE 解析被否：当前没有边合成边播通道，属 YAGNI，且解码质量无法验证。

**档案卡与能力面纠偏**

- 三张卡 `pending-runtime-validation` → `runtime-validated`；`avg_latency_seconds` 填实测
  （预置 3.1 / 设计 2.4 / 复刻 3.1）；`detailed_specs.voice_synthesis` 下补
  `verified_parameters` / `verified_billing`（限时免费期实测 0 消耗，计价变动须重新取证）；
  `documentation_url` 指 `https://mimo.mi.com/docs/zh-CN/api/audio/tts`。
- 删除自造能力键 `voice_design_instruction_mode`（`tts_model_ids.py`，全仓零消费者，
  证据文档 §8-5 早已点名是 invention）。
- `supports_streaming: True`（`tts_model_ids.py:175` 能力面、`:385` 目录卡）**保留**，2026-10-11 已裁定，
  理由与配套的文案收口见上方「流式裁定与收口」。该键在 TTS 侧没有运行时读取方，
  由 `test_audiobook_tts_model_ids.py` 的 MiMo 能力面断言与卡片文案断言共同钉住。
- 三变体都没做质量评分批次，`overall_score` 保持 0.0 表示"未评"，不代表表现差。

**契约测试**：`backend/tests/test_audiobook_tts_provider_payloads.py` 追加 10 条，锁住
默认 wav 且不带 `stream`、mp3 透传、`stream=True`→pcm16 且 `payload["stream"] is True`、
`format=opus`→wav 与 `stream+opus`→pcm16、`voice_sample_data_url` 优先于 `voice_clone_data_url`、
`mimo_clone:` 资产 id 不得出现在 `audio.voice`、voicedesign 保留 assistant 台词且
`optimize_text_preview=false` 进 `audio`（未设置时不下发该键）、解析器同时接受
`{"audio":{"data":…}}` 与 `{"audio":…}`，并给出三条精确 `ValueError`
（missing choices / missing message / missing audio data）。
2026-10-11 收口再加 2 条闸门契约（同文件参数化）：`stream=true` 与 `format=pcm16` 都在
**发出请求之前**抛 `TTSUserInputError`，用「被调用即记录」的假 httpx 客户端断言 `post` 未被触达。
MiMo 载荷族 29 passed、MiMo 相邻三文件 181 passed、根目录引用 mimo 的 10 个文件 353 passed。

**adapter 壳判定**：`adapters/mimo/tts.py` 与 `adapters/registry.py:138` 只有 spec 声明、
没有任何调用实现，生产链路完全走 `TTSEngine`。所以 MiMo 的事实源是三处——
`tts_model_ids.py`（能力/目录）、`_aliyun_mixin.py`（载荷与传输）、`config/models.yaml`（档案），
adapters 层不构成第二事实源，不必同步维护。

**证据留存**：冒烟脚本与产物写在仓库外的一次性目录，按 AGENTS.md 清理条款用完即删，
上表数字即最终记录（无 `.mp3` 之外的评分样本，本轮只做契约与稳定性取证）。

### 11.13 StepAudio 3 TTS 声明面收口与逐音色实测（2026-10-11，结论来自真实调用）

**背景**：TTS-12 在 2026-10-11 的三项事实（逐音色批量、流式缺口、instruction 上限）当时只留在会话与
sidecar，没有回写档案；本节补上回写，并记录同期修正的两处与档案相反的声明。

**逐音色可用性收口**：`backend/app/scripts/tag_voice_profiles.py` 对 36 个官方音色逐个替换 `voice`，
走真实 `POST /v1/audio/speech`，**客观闸门 36/36 通过**（时长偏差、静音比、RMS、ASR 逐字相似度）。
产物 `shared/stepaudio_3_tts_voice_profiles.json`：`profile_status` 36 ready、`review_status`
34 candidate / 2 approved，`needs_review` 主因 `single_sample_evidence`，双评分歧集中在
pace 26 / energy 24 / style 17 / pitch_range 16（主评 `doubao-seed-2-1-lite`，参考评
`qwen3.8-omni-flash`）。这把「36 个官方音色在 3-tts 端点是否都能出声」从推断升级为实测事实。
`[档案]` 卡片 `summary` 与 `verified_parameters` 已写入该结论。

**流式声明降级**：`supports_streaming` 原在**上游未取证**的情况下写 `true`（`tts_model_ids.py`
风格能力表 + 目录卡两处），而生产链路只发非流式 `/audio/speech` 整包接收、payload 无 `stream` 布尔、
响应侧无 SSE 解析。两处已同步降为 `False`，由
`test_stepaudio_streaming_is_declared_unsupported_across_sources` 钉住跨源一致性。
与 §11.12 的 MiMo 是**两类问题**：MiMo 的布尔有真实流式取证、缺口在我方消费层；StepAudio 连上游都未取证，
属于未取证声明。判据统一为「这个 `true` 的证据在哪一条实测记录里」，答不出就降 false。详见 §11.9 第 10 条。

**instruction 上限 200→500**：200 是 `stepaudio-2.5-tts` 的上代限制，官方 3-tts 为 500，
依据 G3 实测 244 字 instruction 返回 HTTP 200（**500 整值本身未探针**）。落点与副作用见 §11.9 第 1 条。
本条只补一条方法论：该额度实际有 **5 处事实源**，其中第 5 处是场景引擎喂 LLM 的表演提示词
（`script_adapter_pkg/_transform.py` StepAudio 分支 3 处，由 `tests/test_audiobook_prompt_contracts.py`
用 `assert "500 字符" in prompt` 钉住）。它是提示词散文而不是配置字段，按常量名 grep 抓不到——
漏改的症状是「代码放宽了、剧本层仍按旧额度压缩 performance_notes」。跨源一致性已由
`backend/tests/test_audiobook_tts_model_ids.py::test_stepaudio_budget_and_transport_declarations_agree_across_all_fact_sources`
钉死：档案卡 `constraints` + `contextual_control`、能力矩阵 `instruction_budget`、引擎硬截断常量、
前端兜底表 `instructionBudget`、场景引擎提示词散文五处必须同值，另加 `max_input_chars` 与流式声明两条。

**复刻链路的状态边界**：`POST /v1/files` 与 `POST /v1/audio/voices/preview` 都是**已接入且有真实调用取证**
（2026-06-25：files 成功返回 `file_id`；preview 侧取到 `CER_NOT_PASS` 的错误形状，错误详情同时给出 `asr_result` 与 `user_text`，
以及成功响应字段 `sample_audio`，字段映射与 `_parse_stepaudio_audio_response()` 据此校准）。
未接入的是**正式持久音色资产创建**——官方没有该接口合同，项目不伪造 voice id，`creates_asset` 保持 false，
卡片标签只留 `pending-formal-voice-asset-creation` 一条。此前档案把「文件上传接口待确认」与「正式音色创建待确认」
混写成同一个缺口，是本次修正项。仍**没有**做过的：浏览器端预试听→确认保存两阶段的人工验收。

**供应商侧残留文件对象（台账，不可自动化）**：早前产物清理毁掉了当时上传到 StepFun `/v1/files` 的
`file_id` 清单，本地也不存在 `backend/data/stepaudio_voice_assets` 目录（未保存过复刻资产），
项目侧没有远端文件列举/删除封装，官方是否提供 `DELETE /v1/files/{id}` 未取证。
因此这批对象只能在 StepFun 控制台人工核对删除，**不在本项目执行**；本条按台账长期保留，不代表可自动化待办。

**证据脚本的留存裁定**：`backend/app/scripts/` 下 `tag_voice_profiles.py`、`probe_tts_capability_gates.py`、
`probe_tts_gate_scoring.py` 不按「一次性排查脚本」删除。理由：它们是被 §11.9/§11.10/§11.11/§11.12/§11.13
引用的复测入口，删除会让已归档结论不可复现；三者都需要显式运行 + 环境变量密钥才发真实请求
（两个 probe 默认干跑，必须 `--confirm-paid`），不会被动产生费用。**同时更正一条旧承诺**：
`docs/TTS_PROMPT_EVIDENCE_20261010.md` §9.3 原写「脚本保留至第二阶段结束，随后与证据目录一并清理」，
而 `backend/data/tts_debug/gate_probe_g1_g7/` 已经不存在（逐条音频、manifest、盲评表全部丢失），
2026-10-11 裁定改为脚本长期留存。约束：档案中所有标注「原始日志已删除」的条目，复现口径只到
「重新跑一遍取新数据」，不得声称保有当时的逐条响应；引用这些数字时按一次性观测快照读取。

**本轮回归数字（全部串行）**：前端 stepaudio 相关 4 文件 45 passed；根目录 catalog 4 文件 25 passed；
根目录 retirement + unified_model_system 239 passed；后端 TTS 家族 11 文件 344 passed；
`test_audiobook_prompt_contracts.py` 29 passed。

## 12. 音乐生成（Mureka）接入要点（2026-10-11，结论来自官方文档渲染件 + 真实调用）

### 12.1 上游契约：入参只有五个字段

`POST /v1/instrumental/generate` 的请求体只接受 `model` / `n` / `prompt` / `instrumental_id` / `stream`。
**没有 `duration`、没有 `format`、没有 `sample_rate`**。查询走 `GET /v1/instrumental/query/{task_id}`，
结果在 `choices[i]`，字段是 `duration`（毫秒）、`flac_url`、`id`、`url`（MP3）、`wav_url`，第二首起多一个 `index`。

### 12.2 `model` 枚举里没有 O 系列，V8 不存在

instrumental 端点的 `model` 枚举是 `auto / mureka-7.6 / mureka-8 / mureka-9 / mureka-9.5`：

- `mureka-o1` 实测 **400**，且报文只有 `{"error":{"message":"Invalid Request"}}`，**不点名是哪个字段错**；
- `mureka-o2` 只出现在 `/v1/song/generate`（带人声的歌曲端点）的枚举里，并注明"不支持 vocal 和 melody 输入"；
- 上游没有 V8 这个版本号，档案里的 `v8` 是本地臆造。

因此本地 ID `mureka-o1-instrumental` 只是历史兼容名（被统一体系测试与资产目录锁定，不改名），
实际下发的代际固定在 `adapters/_shared.py:MUREKA_INSTRUMENTAL_MODEL = "mureka-9.5"`。
不要图省事写 `auto`：`auto` 实测解析为 `mureka-9.5`，但它会随上游上新静默改变产出，等于把代际交给对方决定。

### 12.3 `n` 缺省是 2，而且按数量计费

不发 `n` 时上游出 **两首**、扣 **200** 额度单位；显式 `n=1` 出一首、扣 **100**。
所以两处调用点都必须显式下发 `MUREKA_INSTRUMENTAL_N = 1`，否则单首成本静默翻倍。
`n` 合法范围 1–3，越界报文点名：`Invalid Request, Parameter n accepts values in the range of 1 to 3.`

### 12.4 没有时长入参，控件时长只用于冻结与校验

资产工作台音乐控件的 15/30/45/60 秒来自 `asset_studio_model_catalog._AUDIO_DURATION_OPTIONS`（按**类型**而非模型），
它只做参数校验和积分冻结（`routes_audio.py` 按 `resolved_duration` 冻结），**不下发给上游**，产物也不裁剪。
实测请求 30 秒返回 188.5 秒、189.7 秒的完整乐曲——现状是"多给产物、少收钱"。
时长口径的正确改法（改成 `model_decided` 语义、控件不再显示时长下拉）归资产工作台控件立项，不在本条链路里偷偷改。
`prompt` 上限 1024 字符，越界报文点名：`Invalid Request, The prompt exceeds 1024 characters.`

### 12.5 `style` / `mood` / `tempo` 是本地拼 prompt，不是上游入参

`ai_music.py` 把 `mood`、`MusicStyle.value`、`tempo`、`instruments`、`prompt` 用 `", "` 拼成一个 `prompt` 下发。
档案里这三项必须写 `support_level: emulated` + `emulation_method: prompt_compose`，写 `native` 会误导后来人以为能调字段。
改这些档位**不会改变请求字段结构**，只会改变 prompt 文本。

### 12.6 状态机：`timeouted` / `cancelled` 是终态

实测流转 `preparing → running(11.4s) → reviewing(59.8s) → succeeded(65.1s)`。
完整枚举：非终态 `preparing / queued / running / streaming / reviewing`，成功 `succeeded`，终态失败 `failed / timeouted / cancelled`。
只判 `failed` 的话，`timeouted`、`cancelled` 会落到"未知状态继续等待"分支，白等到本地 `TIME_OUT_SECONDS`（默认 300 秒）才报超时，
错误信息也从上游原因变成误导性的本地超时。终态集合单点在 `MUREKA_FAILED_STATUSES`，失败原因优先读 `failed_reason`。

### 12.7 水印：官方说 5 秒，实测可闻段只有 3 秒

响应带 `watermarked: true`，官方文档称尾部 5 秒水印。用 pydub 逐秒测 dBFS：`-5s`、`-4s` 是 `-inf`（数字静音），
`-3s: -34.9 dBFS`、`-2s: -37.8 dBFS` 且两首完全相同——可闻段只在最后约 3 秒。
所以默认 `MUREKA_WATERMARK_TRIM=3.0` 已够，残留的是静音不是缺陷。别凭文档字符串把裁剪值改成 5，那只会砍掉真音乐。

### 12.8 账号侧口径：并发 1，额度单位与人民币换算未证实

`GET /v1/account/billing` 返回 `balance / total_recharge / total_spending / concurrent_request_limit`，
实测 `concurrent_request_limit: 1`，与本地 `_MUREKA_MAX_CONCURRENT` 默认 1 吻合（不要调高，上游会拒）。
该接口只给额度单位、不给人民币标注，所以档案 `cost_profile.price` 保持 `0.0`：
这个字段被 `core/unified_media_runtime.py:_score_spec` 当绝对值消费，填猜出来的价会污染选型评分。

### 12.9 官方文档是 SPA，WebFetch 拿不到 schema

`platform.mureka.cn/docs` 是 VitePress-openapi 单页应用：`WebFetch` 和 `…/openapi.json` 都只返回 HTML shell。
必须用浏览器渲染后读 DOM（`navigate_page` + `take_snapshot` / `evaluate_script`）才能拿到入参与枚举。
同类 SPA 文档别再重复尝试 curl，直接上浏览器。

### 12.10 单点常量与两处调用点

音乐链路有**两个**调用点，历史上各写一份契约、互相漂移：

- `backend/app/services/audiobook/ai_music.py`（真实链路，`routes_audio.py` 走这里，**不走 adapter**）；
- `adapters/mureka/instrumental.py`（统一媒体运行时的适配器入口）。

两处必须共用 `adapters/_shared.py` 的 `MUREKA_INSTRUMENTAL_MODEL` / `MUREKA_INSTRUMENTAL_N` /
`MUREKA_PENDING_STATUSES` / `MUREKA_FAILED_STATUSES`（backend 引 adapters 顶层常量有先例，
`app/main.py` 已把仓库根加入 `sys.path`）。回归由 `backend/tests/test_mureka_instrumental_contract.py` 守住：
载荷字段集合、终态分支、以及两张档案卡（`config/models.yaml`、`config/llm_models.yaml`）与常量的一致性。

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
- 如果改动任何 TTS 模型的**提示词写法、风格控制模式或 instruction 预算**，先读 §11.9 的逐条实测状态，再看 `docs/TTS_PROMPT_EVIDENCE_20261010.md` 的原始证据；档案值与实测冲突时以实测为准，并把新结论回写 §11.9（标 `[字段]` 的条目改动前须逐条批准）
- 如果调整音频评审组合或采信口径，参考 §11.10，单点定义在 `audio_score_contract.tts_dimension_authority()`，不要在调用方各写一套
- 如果改动有声书客观层/字幕 ASR（换模型、动 `prompt_audio_asr_*` 的解析或计价、调成本闸门），先读 §11.11：那条链路不进注册中心，退役与换代必须同时改价目表、env 模板与 `TestAudiobookAsrRetirement`，否则 `--all-retired` 门禁抓不到
- 如果改动音乐链路（换 Mureka 代际、动 `n`/状态判定/水印裁剪/时长口径），先读 §12：上游没有 `duration` 入参、`n` 缺省 2 会双倍扣费、终态含 `timeouted`/`cancelled`，契约单点在 `adapters/_shared.py`，两处调用点（`app/services/audiobook/ai_music.py` 与 `adapters/mureka/instrumental.py`）必须一起改，回归看 `backend/tests/test_mureka_instrumental_contract.py`
