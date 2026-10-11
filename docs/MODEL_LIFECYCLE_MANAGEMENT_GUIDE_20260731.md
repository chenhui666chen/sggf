# 模型生命周期管理指南（接入 / 更新 / 卡片 / 完全替换）

首版日期：`2026-07-31`
最近更新：`2026-10-10`（补写：7.2 第 5 层"门禁不扫取值空间——音色 ID 必须手工扫"）
前次更新：`2026-10-09`（同日补写：7.1 引用门禁纳入 env 层、7.2 语义标签承载计数校验、7.6 文字层删除范围、8.6 全量回归失败归因）
适用范围：新模型接入、模型版本更新、模型中心卡片维护、“用一个模型完全替代另一个模型功能”，以及旧模型物理退役的标准化操作。

> **2026-10-09 策略变更**：首版设定的卡片状态阶梯
> （`active → selectable=false → deprecated → compatibility-only → retired`）与“兼容期 ≥ 14 天”的日历门槛**已废止**，
> 由 [7.6 节](#76-退役门槛证据化而非日历化) 的证据化门槛、以及第 2 节新增的**操作 E：旧模型物理退役**取代。
> 变更理由：旧 ID 保留可解析所带来的代价是**静默改写**（真实事故见 3.6 节），而“未注册、直接报错”是被看见的失败；
> 每次接入与升级本身都要求真实调用回归通过，兼容期保护的是一个已经验证过不需要保护的东西。

## 0. 文档定位与关联文档

本文档是“操作手册”，回答的是**“要做这类变更，按什么顺序改哪些地方、如何验证、如何做到不漏”**。

> **当前版本覆盖范围**：接入、静态校验、人工试跑、持久化数据处置、旧模型物理退役（操作 E）。
> **尚未纳入正式标准**：生产级灰度发布、流量分流、自动化监控告警（见 [7.7 节](#77-灰度与监控能力分阶段建设)）。
> 在灰度基础设施就绪前，模型切换不具备生产级流量保护，请以小批量试跑 + 人工确认替代。

它不重复讲解各视频模型的 API body 差异、TTS 调试细节，这些请查阅：

- 接入原理与各平台/API 格式差异：`docs/MODEL_INTEGRATION_REFERENCE.md`
- 能力验证与保守结论口径：`docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md`
- 路由运行时一致性与调度 trace：`docs/MODEL_ROUTING_OPTIMIZATION_PLAN_20260417.md`

三个高频入口（用户视角常问的三处配置）在本文档中的角色：

| 配置 | 角色 | 何时必须动 |
| --- | --- | --- |
| `config/intent_domains.yaml` | 领域知识：提示词范式、风格、运镜、景别、场景规则 | 新增/调整风格、运镜、场景类别，或调整意图解析规则时 |
| `config/models.yaml` | 媒体模型画像：能力、标签、评分、约束、fallback | 新增/更新媒体模型，或需要让语义匹配识别新风格时（改 `tags`） |
| `core/semantic_matcher.py` | 语义词汇表：风格/场景关键词到内部名的逆向词典 | 新增全新的 style / scene 类型时 |

## 1. 全局事实：三类事实源 + 两套注册体系

### 1.1 配置事实源（4 份）

| 文件 | 覆盖对象 | 说明 |
| --- | --- | --- |
| `config/models.yaml` | 媒体模型（图/视频/音频/多模态） | 媒体模型 metadata 的**主事实源**，约 7800+ 行，末尾含 `routing` 策略权重 |
| `config/llm_models.yaml` | 文本 LLM | 文本主链模型的能力/约束/路由/档案 |
| `config/intent_domains.yaml` | 领域知识 | 风格/运镜/景别/构图/情绪/场景规则/提示词范式，按 domain（wan/tts 等）组织 |
| `config/model_catalog_profiles.yaml` | 模型卡补充档案 | 项目级 Prompt 模板、`router_rules`、`tooling_badges`、`project_entrypoints`、部署说明 |

### 1.2 运行时注册体系（2 套，不要混为一谈）

| 链路 | 配置 | 注册中心 | 适配器 | 装饰器 |
| --- | --- | --- | --- | --- |
| 文本 LLM 主链 | `config/llm_models.yaml` | `UnifiedModelRegistry`（`core/unified_registry.py`） | `core/llm_adapters.py` | `@register_llm_model` |
| 媒体智能调度链 | `config/models.yaml` | `ModelRegistry`（`adapters/registry.py`） | `adapters/*.py` | `@register_model` |

关键运行时事实（本次已核对）：

- 媒体链 `ModelRegistry._ensure_builtin_registration()` 会**显式导入一批模块**再加载 YAML。当前清单为 19 个
  （`adapters/registry.py:136-158`）：`adapters.new_models_adapters`、`adapters.mimo.tts`、
  `adapters.volcengine.{image,chat,video,tts,audio_generation}`、
  `adapters.dashscope.{chat,image_sync,image_async,image_edit,multimodal,tts,video_t2v,video_i2v,video_wan3,video_kling}`、
  `adapters.mureka.instrumental`、`adapters.vidu_platform.video`。新适配器若放在清单之外的新模块里，
  **必须把模块名加进清单**，否则 `@register_model` 不会执行。
- 这份导入被包在 `try/except Exception: pass` 里：**模块名写错或文件已删除都不会报错，只会静默不注册**。
  清单必须列到**叶子模块**，只写包名（如 `adapters.dashscope`）在 reload 分支里只会重跑 `__init__` 的 `import *`，
  子模块体不会重新执行，装饰器也就不会再注册。
  结构体检命令：`python scripts/audit_model_references.py`（不带 `--model-id` 时只跑结构体检，
  检查清单里的模块是否真实存在、同一 ID 是否被多处注册）。
- 文本链 `@register_llm_model`：如果 `llm_models.yaml` 里已经定义了同 `id` 的 spec，装饰器**以 YAML 为权威，只挂载适配器类**，
  装饰器传入的 `default_params` 会被忽略。因此**钉死上游真名的 `request_model` 必须写在 YAML 里**，写在装饰器上不生效。
  文本模型的能力/路由也以 YAML 为准维护。
- 文本链注册表是模块级单例（`core.model_hub.model_hub.registry`），`model_hub.initialize()` **不是全量重载**：
  `_ensure_adapters_loaded()` 在标记已置位时直接返回，装饰器不会重跑。任何 `clear()` 过该单例的测试，
  必须 `importlib.reload(core.llm_adapters)` 才能恢复注册，统一使用
  `tests/model_registry_reset.py::reload_llm_registry()`（或 `tests/conftest.py` 的 `restored_llm_registry` fixture）。
- 归一层 `core/model_resolution.py` 的 `MODEL_ALIASES` 现在**只做拼写形态归一**（大小写、斜杠与短横线差异，
  如 `minimax-speech-2.8-hd → MiniMax/speech-2.8-hd`），**不再承担“旧 ID → 新 ID”的换代映射**；
  换代一律按操作 E 物理删除旧 ID，使用边界见 3.6 节。

## 2. 五类操作总表（先定位，再执行）

| 操作 | 触发场景 | 核心事实源 | 是否只改 YAML |
| --- | --- | --- | --- |
| A. 新模型接入 | 引入一个当前没有的模型 | YAML + 适配器 + 注册 | 否 |
| B. 模型更新 | 已接入模型调参、升版本、改能力/评分/fallback | 对应 YAML（+ 别名/适配器视变更而定） | 多数可以 |
| C. 卡片更新 | 模型中心页面展示信息/验证状态需要刷新 | config 实时投影 + DB 验证状态 | 见[第 6 节](#6-操作-c模型中心卡片更新) |
| D. 完全替换 | 用模型 X 全面替代模型 Y 的功能 | 全量分散点核对（[第 7 节](#7-操作-d-与-e模型完全替换与旧模型物理退役)） | 否，必须全链路核对 |
| E. 旧模型物理退役 | 新模型已真实调用验证通过，要把旧模型彻底删干净 | 退役登记表 `tests/test_model_retirement_registry.py` + 全仓引用审计 | 否，配置/适配器/别名/卡片/数据库都要删 |

## 3. 配置事实源详解

### 3.1 `config/models.yaml`（媒体模型）

每个模型条目的主要字段（以 `qwen-image-3.0`、`wan3.0-video` 为实例核对）：

- `id` / `name` / `provider` / `version` / `status`
- `modality`：如 `text_to_image`、`image_to_video`
- `capabilities[]`：`name / support_level(native/emulated/unsupported) / score / description / source / verified_at / confidence`
- `constraints`：`ratios / duration / min_width / max_width / max_batch_size / max_prompt_length` 等
  （`duration` 在文件里四种写法共存，取值口径与同步义务见 5.2）
- `quality_metrics`：`overall_score / character_consistency / motion_stability / prompt_adherence / visual_quality / style_accuracy`
- `cost_profile` / `avg_latency_seconds` / `p95_latency_seconds` / `rate_limit`
- `default_params` / `best_practice`（含 `prompt_template`、`recommended_params`、`tips`）
- `fallback_strategies[]`：`trigger_condition / fallback_model_id / param_adjustments / priority`
- `endpoint` / `auth_method` / `summary` / `recommended_scenarios` / `limitations` / `integration_notes`
- `documentation_url` / `source_urls`
- `tags`：**语义匹配的关键字段**（见 3.5）
- 文件末尾 `routing`：`default_strategy` 与 `quality/cost/speed/balanced` 四种策略权重、`fallback` 错误处理器。

### 3.2 `config/llm_models.yaml`（文本 LLM）

每个模型主要字段（以 `qwen-plus` 为实例核对，其上游线名为 `qwen3.7-plus`，见 7.8 节）：

- `id / name / provider / model_type / version / status`
- `capabilities[]`：`name / level / score / description`
- `constraints`：`max_context_tokens / max_output_tokens / max_thinking_tokens / supports_streaming / supports_function_call / supports_vision / supports_json_mode / supports_temperature / supports_thinking_mode` 等
- `api_config`：`api_key_env / base_url / default_timeout / default_max_retries`
- `performance`：`quality_score / avg_latency_seconds / cost_per_1k_input_tokens / cost_per_1k_output_tokens / currency`
- `routing`：`task_types[] / priority / fallback_models[] / weight / enabled`
- `default_params`：`temperature / max_tokens / enable_thinking`
- `summary / recommended_scenarios / limitations / integration_notes / best_practice_tips / documentation_url / source_urls`

维护要点：文本模型的能力与路由以 YAML 为权威，`core/llm_adapters.py` 中 `@register_llm_model` 的同名参数应与 YAML 保持一致，避免两处口径漂移。

**上限类字段有三个互不相等的量，写档案时不许混用**（2026-10-09 对账发现三类错值同时存在，详见接入经验文档 §10.17）：

- `constraints.max_output_tokens` / `max_thinking_tokens`：上游允许的**上界**，由越界探测实测得到，不是项目想发多大。
- `default_params.max_tokens`：项目**实际发送**的值。改上限永远不要顺手改它——它会改变真实请求与超时行为。
- 上游不校验该参数时（`step-preview`、`kimi-preview` 实测传 999999 仍返回 200），档案值只能是**项目自选的保守上界**，必须在 `integration_notes` 写明"无法实测 + 为什么"，否则下一轮会被当成错值改掉。

`default_params` 里非 OpenAI 白名单的键（如 `enable_thinking`、`thinking`）会被适配器塞进 `extra_body` 直发上游，**不是备注**；模型换代时这类写法必须重新实测（2026-10-09 glm 就地换代后残留的关思考写法让每次调用都 400，见 §10.20）。

### 3.3 `config/intent_domains.yaml`（领域知识）

结构：`domains.<domain>`（如 `wan`、`tts`）下含 `modalities / creative_modes / styles / camera_movements / shot_types / compositions / lighting_times / emotions / prompt_template / prompt_examples / parsing_rules / constraints / scene_rules`；顶层 `common` 含 `common_styles / resolution_map / priorities / quality_levels`。

- 新增/调整风格、运镜、场景类别 → 在对应 domain 的 `styles` / `camera_movements` / `scene_rules` 增补。
- `styles` 里每个风格带中文/英文关键词列表，用于意图解析时把用户模糊描述映射到风格名。

### 3.4 `config/model_catalog_profiles.yaml`（模型卡补充档案）

`profiles.<model_id>` 下含 `role_summary / system_role / prompt_patterns / router_rules / best_practice_tips / tooling_badges / project_entrypoints / local_deployment_note`。这些内容会被投影进模型中心卡片（见第 5 节）。新增/替换模型时，如果希望卡片展示项目级用法与路由说明，就在这里补一条。

### 3.5 `core/semantic_matcher.py`（语义词汇表）

- `STYLE_VOCABULARY`：风格名 → 关键词列表。
- `SCENARIO_VOCABULARY`：场景名 → 关键词列表。
- `SemanticModelMatcher._build_model_index()` 会读取每个模型 spec 的 `tags`，**当 tag 命中 `STYLE_VOCABULARY` / `SCENARIO_VOCABULARY` 的键时**，把该模型关联到对应风格/场景。

因此"让某模型支持某风格的语义路由"是三处联动：

1. `core/semantic_matcher.py` 的词汇表里有这个风格/场景名（新类别才需要加）；
2. `config/intent_domains.yaml` 里有对应风格定义（供意图解析）；
3. `config/models.yaml` 中该模型的 `tags` 里写上这个风格/场景名。

> 注意：`STYLE_VOCABULARY` 中现存大量重复键（同名多次定义），这是历史遗留，新增时**追加新键即可，不要依赖重复项的先后顺序**。

### 3.6 `core/model_resolution.py`（ID 归一）

`MODEL_ALIASES`（旧写法 → 注册中心真实 ID）、`TASK_TYPE_ALIASES`（历史任务名 → 现行任务名）。

**使用边界（2026-10-09 起）**：`MODEL_ALIASES` 只用于**拼写形态归一**（大小写、斜杠与短横线差异）。
**换代不得加 alias**：旧 ID 按操作 E 物理删除，让它“未注册 → 直接报错并被看见”，
而不是被静默改写成另一个模型。

这条边界来自一次真实事故：alias `wan2.6-t2v-fast → wan2.6-t2v` 的归一目标 `wan2.6-t2v` 从未进入任何注册中心，
于是别名把用户选的模型改成了一个谁都认不出的 ID——**悬空 alias 的失败是静默的，比不做归一更糟**。
该风险由 `tests/test_model_retirement_registry.py::TestAliasTable` 反向锁死：
每条 alias 的目标必须能在某个注册中心解析到，且退役/改名过的旧 ID 必须查不到 alias。

唯一有意长期保留的例外：`cosyvoice-v3-plus → cosyvoice-v3.5-plus`（用户 2026-10-09 决定）。
它被存量音色资产按名引用，删除会让已保存的音色配置解析失败；这是**明确记录的例外**，不是兼容期残留。

## 4. 操作 A：新模型接入

### 4.1 判定链路

按 `docs/MODEL_INTEGRATION_REFERENCE.md` 第 3 节判定走文本主链还是媒体调度链。

### 4.2 媒体模型接入步骤

1. 在 `config/models.yaml` 增加模型条目（字段见 3.1）。
2. 在 `adapters/` 复用或新增适配器类，用 `@register_model("<id>")` 注册；新媒体适配器按媒体线**事实签名** `generate(self, prompt: str = "", **kwargs)` 实现（`generate(task: TaskSpec)` 不会被运行时拒绝，但资产工作台/有声书等直连入口按 kwargs 调用，task-only 签名在那里会 `TypeError`；判定机制与实测统计见 `docs/MODEL_INTEGRATION_REFERENCE.md` §6.7）。
3. 若适配器位于**新模块**，把模块名加入 `adapters/registry.py` `_ensure_builtin_registration()` 的自动导入列表。
4. 若上游要求的请求体模型名带 `kling/`、`vidu/` 前缀或日期后缀（与内部 ID 不同），把真名固定在**适配器侧**：
   媒体链用适配器的 `MODEL_ID` 常量，文本链写进 `config/llm_models.yaml` 的 `default_params.request_model`。
   **不要**为这种差异新增 `MODEL_ALIASES` 条目（使用边界见 3.6 节）。
5. 需要被 Asset Studio / DreamWeaver 前端选到 → 见[第 7.2 节统一清单层](#72-分层核对清单逐项确认不允许跳过)。
6. 需要语义风格路由 → 按 3.5 三处联动。
7. **可执行性判据（有档案不等于有实现）**：`core/unified_media_runtime.py` 的 `_OPERATION_MODEL_IDS` 每个
   operation 键都对应一个执行者，接入时必须把条目对齐到对应执行者，否则它只在档案层存在，
   运行期才报 `adapter_missing`（历史上 `edit_video` 键整键缺失、视觉线只有档案没有方法，都属于这一类）：
   - 媒体生成与编辑（`_ADAPTER_EXECUTED_OPERATIONS`：`generate_image` / `generate_video` / `edit_image` /
     `edit_video` / `analyze_image` / `analyze_video`）由 adapter 注册表执行 → 必须 `registry.has_adapter(id)`；
   - 路由入口传入的 modality 字符串还必须先是 `schemas/common.py` 里 `Modality` 枚举的成员
     （`TaskSpecBuilder.with_modality()` 在路由之前就构造枚举）：历史上 `edit_video` 传 `video_edit` 却无该枚举值，
     白名单补齐后仍在入口处抛 `ValueError: 'video_edit' is not a valid Modality`；
   - 视觉两类（`analyze_image` / `analyze_video`）在此基础上**还要**由 adapter 上的同名方法执行
     （`_execute_custom_registry_method`），且档案 `modality` 必须声明 `image_understanding` / `video_understanding`，
     否则会在路由期被 `modality` 过滤掉；
   - 语音（`synthesize_speech`）由 TTSEngine 按供应商直接实现，**不查注册表** → 判据是
     `backend/app/services/audiobook/tts_model_ids.py` 的 `SUPPORTED_AUDIOBOOK_TTS_MODELS`，
     该白名单同时是有声书语音合成的准入门禁（`create_tts_engine`），不能按"从列表消失"的需求摘除。
   常驻护栏：`tests/test_media_runtime_executability_guard.py`（白名单可执行 + 候选集过滤 + 语音归属）、
   `backend/tests/test_asset_studio_model_catalog_image_line.py`（目录 ↔ adapter ↔ 白名单三方一致）、
   `scripts/check_model_integration.py --chain all`（LLM 档案镜像与 TTSEngine 直连标 `NON_ADAPTER`，其余必须归零）。

### 4.3 文本模型接入步骤

1. 在 `config/llm_models.yaml` 增加模型条目（字段见 3.2）。
2. 在 `core/llm_adapters.py` 增加适配器类；OpenAI 兼容接口通常只需继承 `OpenAICompatibleAdapter` 并用 `@register_llm_model` 注册。
3. 特殊请求参数/响应解析/思考模式策略在适配器类中处理（参考 DeepSeek V4 思考模式约定）。
4. **上限与思考写法必须实测，不抄文档**：跑 `python scripts/probe_llm_output_limits.py --id <新 ID>` 拿 `max_output_tokens` / `max_thinking_tokens` 真值；再单独确认该模型**能不能关思考**（`enable_thinking=false`、`thinking={"type":"disabled"}` 两种写法各试一次）。强制思考的模型要同时登记到 `core/model_resolution.py:_FORCED_THINKING_MODEL_IDS`，并从 `default_params` 里去掉关思考写法。
5. 把实测值写进 `tests/test_llm_output_limit_fact_table.py` 的事实表，并在 `integration_notes` 记一句带日期的实测来源；上游不校验、探不出上限的条目要写明"无法实测"，避免下一轮被当错值改掉。

### 4.4 接入后验证

按[第 8 节标准验证与回归基线](#8-标准验证与回归基线)执行。

## 5. 操作 B：模型更新

### 5.1 只改 YAML 即可的情况

- 调整路由权重、`task_types`、`fallback_models`、`priority`、`weight`、`enabled`
- 调整能力评分、约束、超时、价格、`default_params`
- 更新 `summary` / `recommended_scenarios` / `limitations` / 文档链接

改完**重启后端与相关 worker**（两套注册中心都有单例/实例缓存）。

### 5.2 需要同时改代码的情况

- 请求体格式/响应解析变化 → 改对应适配器
- 上游真名（请求模型名）变化 → 只改适配器 `MODEL_ID` 常量与 `default_params.request_model`，**内部 ID 保持不变**
  （中性 ID 约定见 7.8 节，这正是升级不需要兼容期的原因）
- **但"只改一行"不等于"不用重测"**：中性 ID 让换代没有任何提醒，`constraints.*` 与 `default_params` 里的思考开关会静默继承上一代取值。
  改完 `request_model` 必须立刻重跑 `python scripts/probe_llm_output_limits.py`（漂移退出 1；有"未探到"条目退出 2，同样不算通过），并按 4.3 第 4 步重测关思考写法，
  再同步 `tests/test_llm_output_limit_fact_table.py` 的事实表。2026-10-09 的实例：一次就地换代留下了三处陈旧上限，
  以及一个让该模型每次调用都 400、只在日志里表现为"限流后回退"的关思考残留写法（成因见接入经验文档 §10.20）。
- **媒体模型的约束字段同理，而且分散得更广。** 改一个时长/分组值不等于「只改 YAML」：`config/models.yaml` 的 `constraints.duration` 有四种写法共存（`[]` / 档位列表 / 单值 / `{min,max,default[,supports_auto]}`），
  而同一件事实在前端还有离线镜像表与兜底成员表，在适配器 `get_model_spec()` 里还有第四份硬编码。六处清单、同步义务与反制测试见接入经验文档 §10.23。
  2026-10-09 的实例：把六档视频模型的时长放开到官方区间时，`kling-v3` 档案的 `modality` 只写了 `text_to_video`（官方实际支持图生视频），
  导致它在动作组里长期缺席；反向地，`pixverse-v6-t2v` 因 capability 标签挂了 `motion_control` 而被手工塞进动作组，但它没有图生视频能力。
  **结论：分组成员必须由 `modality` 判据派生，不能由 capability 标签推导，也不能再手写白名单。**
- 内部 ID 换代（旧 ID 必须消失）→ 走操作 E：物理删除旧 ID 及其 alias，**禁止**用 `MODEL_ALIASES` 做平滑过渡
- 接入渠道切换（如百炼 → 官方 API）→ 改 `api_config.base_url`、`api_key_env`，并同步适配器与 `.env`

### 5.3 版本升级（如 vX → vX+1）

若保留旧 ID 只是底层升版本，优先"就地更新"该条目的内容与能力字段；若要以新 ID 存在且旧 ID 需下线，则视为"完全替换 + 物理退役"，走[第 7 节操作 D / E](#7-操作-d-与-e模型完全替换与旧模型物理退役)。

> **就地更新前提条件**（全部满足才可复用旧 ID）：外部模型请求 ID 未变、请求/响应契约兼容、能力与安全边界无重大变化、历史任务不要求按原版本重放、**上限与思考开关已按 5.2 重测并写入档案**。否则应分配新内部 ID，并把旧 ID 按操作 E 物理删除——不得在 `MODEL_ALIASES` 保留旧 ID 映射。

## 6. 操作 C：模型中心卡片更新

### 6.1 数据来源机制（务必先理解）

模型中心卡片 = **当前配置实时投影 + 数据库验证状态覆盖**：

- `build_model_catalog_card_payloads()`（`app/services/model_catalog_bootstrap.py`）从 `config/models.yaml` + `config/llm_models.yaml`（+ `model_catalog_profiles.yaml`）实时构建卡片 payload。
- `build_projected_model_catalog_entries()`（`app/services/model_catalog_projection.py`）把 payload 与数据库 `ModelCatalogEntry` 合成：**名称、摘要、能力、约束等基础 metadata 以当前配置为准**；数据库主要承载 `verification_status / verification_score / source 校验结果 / 时间戳`。
- API：`backend/app/api/v1/model_catalog.py`（`/api/v1/model-catalog/overview | entries | entries/{model_key}`）。
- 前端页：`frontend/src/pages/ModelCatalogPage.tsx`。

### 6.2 结论：改卡片≠改数据库

- **改展示 metadata（名称/摘要/能力/推荐场景/限制/prompt 模板等）**：直接改 `config/models.yaml` / `config/llm_models.yaml` / `config/model_catalog_profiles.yaml`，投影层会实时反映，无需动数据库。
- **改验证状态 / 来源校验结果**：走验证流程后写入数据库（`ModelCatalogEntry`）。
- **同步数据库快照到当前集成模型集合**（新增/下线模型后收敛数据库）：

```powershell
# 第一阶段：同步并查看 stale 列表（不删除）
python -m backend.app.scripts.bootstrap_model_catalog_cards
```

- 不带 `--prune-stale`：更新当前集成模型并报告历史残留卡片，但不删除。
- 带 `--prune-stale`：**⚠️ 危险操作**，额外删除已不在当前集成集合中的历史卡片（含验证状态与时间戳，不可恢复）。

```powershell
# 第二阶段：确认待删除 ID、数据库环境、已有备份后，显式执行
python -m backend.app.scripts.bootstrap_model_catalog_cards --prune-stale
```

> 执行删除前应核对：① 当前配置加载是否正常（避免误判大量卡片为 stale）；② 连接的是否为目标数据库；③ 是否已备份 `model_catalog_entries` 表。执行后应调用 `/api/v1/model-catalog/overview` 验证卡片数量符合预期。

## 7. 操作 D 与 E：模型完全替换与旧模型物理退役

这是最容易漏改的操作。"替换"不是只改一份 YAML，而是要覆盖 **配置 / 归一 / 适配器 / 统一清单 / 业务默认 / 前端 / 语义领域 / 测试 / 文档 / 数据库快照** 十个层面。
操作 E（旧模型物理退役）是同一套清单的删除方向：把旧 ID 在这十层里的落点**清空**而不是改写向新 ID，
其完成判据就是 7.6 节的三项证据。

### 7.1 替换前：先做全量引用扫描

人工 `rg` 子串检索不可靠：搜 `mimo-v2.5` 会连带命中仍在线上的 `mimo-v2.5-tts`，也查不到带 `kling/`、`MiniMax/`
前缀的写法。统一使用仓库内的引用审计工具（只读，不发远程调用）：

```powershell
# 单个 ID
python scripts/audit_model_references.py --model-id wan2.7-t2v
# 退役登记表里的全部旧 ID（操作 E 的主力判据）
python scripts/audit_model_references.py --all-retired
# 作为门禁：存在待处理引用或结构问题时返回非零
python scripts/audit_model_references.py --all-retired --expect-zero
# 只要结构体检（自动导入清单缺失模块、同 ID 多注册点）
python scripts/audit_model_references.py
```

工具按 config / adapters / core / backend / frontend / pipeline / scripts / tests / docs / env 分层给出 `file:line`，
并把每条命中分为「待改」与「记录」。**「记录」只有三类**，不在名单里的命中一律按待改处理：

1. 记录性文件：退役登记表（必须逐个点名旧 ID 才能写反向断言）、ID 改写工具、带日期的实验记录
   （改写等于篡改取证数据）。
2. 上游真名（wire name）：`request_model`、`model="真名"`、"模型名为 X"、`glm-5.2[1m]` 这类方括号变体名，
   以及在 `.env` 取值行尾显式标注 `# 上游线名` 的模型名（该变量确实直发供应商时才这样标）。
   内部 ID 已改为中性名，这些行里出现旧版本号是设计使然（见 7.8 节）。
3. 引擎标识符：DreamWeaver 的视频引擎档位 `wan2.7-i2v` / `wan2.7-t2v`（`pipeline/media_presets.py` 常量、
   `backend/app/services/user_center_task_billing.py` 单价表 key 及相关测试）。它们与已退役的万相模型 ID **同名**，
   但不是模型 ID：不进注册中心、不发给上游，且被写进项目配置与计费记录，改名代价远大于收益，
   因此按**上下文**豁免（`DREAMWEAVER` / `engine` 字段）而不是放宽整个文件。

> **env 是必须点名才扫得到的层**：`.env` 系列被 `.gitignore` 排除，`git ls-files` 永远取不到它，
> 曾出现过“门禁归零而 `.env` 里仍留着已退役 ID”。工具按固定清单（根目录 / `backend` / `frontend`
> 的 `.env` 与 `.env.example`）显式并入扫描，只解析模型名类键的取值，并守住两条安全约束：
> 带密钥语义的键（`KEY` / `SECRET` / `TOKEN` / `PASSWORD` / …）一律跳过；命中项只重建 `KEY=值`，
> **不复制整行原文**（同行注释与相邻行都可能是密钥）。纯数字值（平台侧资源 ID）与非模型键不参与。

`rg` 只作补充手段，例如查 `config/intent_domains.yaml` 里 `recommended.target_models` 这类结构化字段。

### 7.2 分层核对清单（逐项确认，不允许跳过）

1. 配置层
   - `config/models.yaml` 或 `config/llm_models.yaml`：新增/更新新模型条目；旧模型按需下线。
   - `config/model_catalog_profiles.yaml`：迁移/更新档案。
   - `config/intent_domains.yaml`：如旧模型绑定在某 `scene_rules.recommended.target_models`，改成新模型。
   - `.env` / `.env.example`（根目录、`backend/`、`frontend/`）：模型名类变量的取值也在删除范围内，
     引用审计的 env 层会自动拦（见 7.1 节）；`*_MODEL_ID` 里的纯数字是平台侧资源 ID，不属于旧模型 ID。

2. 归一层
   - `core/model_resolution.py` `MODEL_ALIASES`：**不新增换代映射**。旧 ID 直接删除，让它解析失败并被看见
     （理由与例外见 3.6 节）。
   - 改完立即跑 `python scripts/audit_model_references.py --all-retired --expect-zero`，
     它会同时拦下残留引用与悬空 alias。

3. 适配器与注册层
   - 新模型适配器就位并注册（`@register_model` / `@register_llm_model`）。
   - 新模块记得加入 `adapters/registry.py` 自动导入列表。

4. 统一清单层（Asset Studio / DreamWeaver 前端可选性）
   - `backend/app/services/asset_studio_model_catalog.py`：
     - `_GROUP_MODEL_IDS`（各分组的可选模型列表，含 `dreamweaver_*` 分组）中替换/新增。
     - `_DEFAULT_MODEL_IDS`（各类别默认模型）中如旧模型是默认值，改成新模型。
   - `backend/app/api/v1/asset_studio_api/_constants.py`：`DEFAULT_*_MODEL_ID` 常量如指向旧模型，改成新模型。

5. 业务默认 / 白名单 / 引擎默认层（按模型类别定位）
   - TTS/音频类：`backend/app/services/audiobook/voice_manager.py`、`.../tts_engine_pkg/_aliyun_mixin.py`、`.../tts_delivery_plan.py`、`.../engine_pkg/_tts_mixin.py` 等中的默认音色/默认模型/模型白名单。
   - LLM 默认：`backend/app/services/streaming_service.py`（环境变量默认模型）、`.../agents/layered_summarizer.py`（token 上限常量）等。
   - DreamWeaver 执行链：`runtime_config` 各 `*_config.adapter` 的默认回落值（参考 `docs/MODEL_INTEGRATION_REFERENCE.md` 第 8 节）。

   > **门禁不扫"取值空间"，换代时必须手工扫一遍**：引用审计的判据是模型 ID，而语音类换代换掉的往往是
   > **整个音色取值空间**（旧音色名与 `_v3.1` 后缀名不互通）。旧声线名作为普通字符串继续留在活代码的
   > **默认值/兜底分支**里时，门禁与注册表类测试全绿，线上只表现为"这一句没有音频"，甚至直接 KeyError。
   > 判据：从旧音色表取出全部音色 ID 当字面量清单，在 `backend/app`、`adapters`、`agents`、`core`、
   > `frontend/src`、`config` 里扫引号命中，逐条分类为「活代码兜底 / 目录真值表 / 测试夹具 / 注释留痕」，
   > 前一类必须改指现役目录内的音色，**且只能改在该模型自己的载荷组装点**：路由与接口层不持有音色名，
   > 未选音色时下发空值、由各模型兜自己的默认（空值边界与"默认值在自家目录"两条判据见 §11.7.9）。
   > 落地点与实测教训见 `docs/MODEL_INTEGRATION_REFERENCE.md` §11.7.9（2026-10-10 抓出 4 处）。

6. 前端层
   - `frontend/src/components/home/AssetStudioWorkbench.tsx`、`frontend/src/pages/DreamWeaverRunPage.tsx`：**只应保留 fallback 常量**，主入口来自 `/api/v1/asset-studio/model-catalog`；如有硬编码旧模型选项，替换或删除。
   - `frontend/src/services/api.ts`：检查是否有把模型 ID 硬编码进 API 路径（如 TTS clone/preview 路径）。
   - `frontend/src/hooks/useAssetStudioModelCatalog.ts`：一般无需改（数据来自后端），确认不再依赖旧常量。

7. 语义领域层（若替换涉及风格/场景能力）
   - `config/models.yaml` 新模型 `tags` 补齐旧模型承担的 style/scene 标签，保证语义路由不丢能力。
   - 全新类别才需要动 `core/semantic_matcher.py` 与 `config/intent_domains.yaml`。
   - **标签是风格/场景路由的唯一载体，删条目会静默丢能力**：`SemanticModelMatcher` 只从模型 spec 的 `tags`
     建索引，旧模型注销后它承担的风格/场景标签一并消失；注册表与配置类测试全绿，**不会为此变红**。
     删除后必须跑承载计数校验：零承载清单不得比基线增加，承载数不得整体变薄。
     注意 `STYLE_VOCABULARY` / `SCENARIO_VOCABULARY` 是超集（含 TTS 与视频编辑等从未由媒体 spec 承载的键），
     本项以**与基线的差值**判定，不追求清单归零；只看有没有比改动前多丢标签。

   ```powershell
   python -c "import yaml,collections;from core.semantic_matcher import STYLE_VOCABULARY as S,SCENARIO_VOCABULARY as C;d=yaml.safe_load(open('config/models.yaml',encoding='utf-8'));n=collections.Counter(t for m in d['models'] for t in (m.get('tags') or []));v=set(S)|set(C);print('零承载:',sorted(t for t in v if not n[t]))"
   ```

   > 实测教训（2026-10-09）：图像线与视频线收敛后，一次性丢了 14 个风格/场景标签的全部承载
   > （`cinematic`、`realistic`、`anime`、`storyboard` 等），当时所有测试仍是绿的。
   > 移交关系只能体现在继任模型的 `tags` 里，没有任何机制会提示它空了。

8. 测试层
   - 更新所有硬编码旧模型 ID 的测试桩（如 `backend/tests/test_audiobook_tts_model_ids.py`、`test_audiobook_tts_provider_payloads.py`、`tests/test_model_integration_self_check.py`、`tests/test_legacy_runtime_wrappers.py`、`tests/test_model_catalog_bootstrap.py` 等）。

9. 文档层
   - 同步 `docs/MODEL_INTEGRATION_REFERENCE.md`（已验证清单/映射规则）、`docs/MODEL_KNOWLEDGE_BASE_20260315.md` 及本指南。

10. 数据库快照层
   - 按[第 6.2 节两阶段流程](#62-结论改卡片改数据库)同步卡片（先预览 stale 列表，确认后再 `--prune-stale`）。

### 7.3 替换后自检

- `python scripts/audit_model_references.py --all-retired --expect-zero` 必须返回 **0 待处理引用**，
  剩余命中只能是 7.1 节列出的三类**有意保留**项。该判据已覆盖 `.env`（env 层，见 7.1 节），
  部署平台与 CI 里的同名变量仍需人工核对一次。
- 反向断言：`python -m pytest tests/test_model_retirement_registry.py -q`，确认旧 ID 不在注册中心、不在 YAML、
  不在卡片档案，没有装饰器注册它，也没有 alias 指向它或悬空在它身上。
- 按[第 8 节](#8-标准验证与回归基线)跑回归。

### 7.4 持久化数据处置

代码引用替换完成后，还必须检查以下可能保存旧模型 ID 的位置：

| 数据类型 | 处置策略 |
| --- | --- |
| 项目设置 / 工作流配置（`projects`、`audiobook_projects` 的 JSON 字段） | 显式迁移为新 ID（数据库 UPDATE） |
| 已创建但未执行的 Celery 任务（broker 队列中） | ① 暂停消费；② 检查队列中旧 ID 任务；③ 对每个任务决定：继续使用旧模型执行 / 取消后按新模型重新入队 / 人工处理；④ 记录任务 ID、原模型、处置结果 |
| 已创建但未执行的数据库任务 / 工作流快照 | 显式迁移为新 ID，或标记为已取消 |
| 历史执行记录 / 审计日志 / 生成记录（`chapter_audio_runs`、`generation_feedbacks`） | **一律改写为新 ID，不生成 `original_model_id` 审计副本**（用户 2026-10-09 决定，覆盖本行原策略，理由见下） |
| Redis 缓存（模型路由结果、会话状态） | 按模型 ID 主动失效，或等待 TTL 过期 |
| 进程内单例（注册中心缓存） | 重启后端与 worker 即可重建 |
| 环境变量 / 部署平台配置（`.env`、Docker、CI/CD） | `.env` 系列由引用审计工具自动扫描并按取值替换（7.1 节 env 层）；Docker / CI 等仓库外配置仍需人工核对 |
| 定时任务（Celery Beat） | 检查 `celery_app.py` 中 `beat_schedule` 是否引用旧 ID |
| 长时间运行任务 | 明确继续使用旧模型完成、取消、或重新调度 |

统一使用仓库内的改写脚本，不要手写 SQL（词边界匹配、JSON 字段处理、影响行数盘点都已内置）：

```powershell
# 第一步：只扫描并预览，逐表逐列打印替换样例与影响行数，不写库
python scripts/rewrite_legacy_model_ids.py

# 第二步：确认行数符合预期后落库；默认先把被改写的原始行备份到 database_backups/
python scripts/rewrite_legacy_model_ids.py --apply

# 第三步：改完必须复扫，历史数据里不得再出现旧 ID
python scripts/audit_model_references.py --all-retired --expect-zero
```

> **为什么不留审计副本**（用户 2026-10-09 明确决定，覆盖本节此前的“保留原始 ID”策略）：
> 目标是“就像没接过老模型”。保留 `original_model_id` 会让旧 ID 继续出现在卡片投影、历史列表、报表与排错输出里，
> 等于把退役模型长期留在系统可见面上，与目标直接冲突。可回滚性由**改写前的 JSON 备份**
> （`database_backups/model_id_rewrite_*.json`）与配置 Git 快照承担，而不是由数据库里的双字段承担。
>
> **有意不改写的旧 ID**（脚本 docstring 为准）：`cosyvoice-v3-plus`（音色资产按名引用，别名长期保留）、
> `wan2.6-t2v-fast`（悬空别名，改写只会把不存在的 ID 换成另一个不存在的 ID）、
> 媒体线拼写变体（`qwen3_vl_plus` 等，库中无命中）、`wan2.7-i2v` / `wan2.7-t2v` / `wan_auto`
> （DreamWeaver 引擎标识符，不是模型 ID）。
>
> **安全要求**：① 执行前核对实际表结构与连接的目标数据库；② 先在 dry-run 确认影响行数；
> ③ 备份文件不得含密钥、且应落在忽略目录内；④ 脚本需可重跑（幂等）；⑤ 改写后复扫并跑相关回归。

### 7.5 回滚路径

若新模型上线后出现异常（质量下降、超时率升高、供应商故障），按以下顺序执行完整回滚：

1. **恢复配置与代码快照**：恢复本次变更记录中保存的配置、代码、环境变量和部署版本快照。若通过 Git 回滚，必须确认目标提交只包含本次模型变更（而非无关改动），并经过发布审批。
2. **恢复运行态**：重启后端与 Celery worker，重建进程内注册中心单例和路由缓存；对 Redis 中包含模型 ID 的缓存按 key 主动失效（或确认 TTL 已足够短）。
3. **恢复数据库待执行数据**：将已迁移为新 ID 的待执行任务、项目设置回滚为旧 ID（在事务内执行）。
4. **验证回滚生效**：运行 `python scripts/check_model_integration.py --chain all`，确认默认路由和显式 ID 均指向旧模型。
5. **整体回退快照，而不是加 alias**：本项目退役即物理删除 alias，回滚靠本次变更记录里保存的配置快照
   （`config/*.yaml` + `core/model_resolution.py` + 适配器）整体回退，数据库历史改写靠
   `database_backups/model_id_rewrite_*.json` 回灌。**不得**为了回滚在 `MODEL_ALIASES` 里加回旧 ID——
   那正是产生悬空 alias 静默改写的入口。

> **重要**：即使某处仍存在 alias，它也只是兼容层而非回滚机制：只影响经过 `normalize_model_id()` 的调用路径，
> 不影响默认路由、`_DEFAULT_MODEL_IDS`、环境变量、数据库持久化数据和 Celery 队列中的任务。

每次变更记录应保存以下可回滚信息：

- 发布版本 / 镜像 digest；
- 配置版本或配置 hash（YAML 文件的 git commit）；
- 数据库迁移版本号；
- 环境变量变更清单；
- 可恢复的部署制品（镜像 tag / 压缩包）。

### 7.6 退役门槛：证据化而非日历化

**已废止的写法**：以“兼容期不少于 14 天”“alias 命中连续 3 个观察窗口为 0”这类日历/观测门槛作为删除前置条件，
以及 `active → selectable=false → deprecated → compatibility-only → retired` 的卡片状态阶梯。

废止理由（2026-10-09 与用户确认）：

- 每次接入与升级本身就要求真实调用回归通过，旧模型能进默认路由就已经是被验证过的；在其上再叠一层
  “旧 ID 继续可解析若干天”，保护的是一个已经验证过不需要保护的东西。
- 兼容层确实造成过事故：alias `wan2.6-t2v-fast → wan2.6-t2v` 的归一目标从未注册过，
  兼容层把请求**静默换成了一个不存在的 ID**。日历门槛的代价是静默错误，证据化门槛的代价是显式失败。
- 中间态（`selectable=false` / `deprecated` / `compatibility-only`）会让旧 ID 继续出现在卡片页、工坊下拉、
  报表与排错输出里；而“删干净”本身是可验证的，不需要用状态位去赌它无害。

**现行退役条件**（三项都是客观可验证证据，必须在同一次变更内一起完成）：

- [ ] 新模型**真实调用回归**通过（不是文档声明；口径见 `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md`）；
- [ ] `python scripts/audit_model_references.py --all-retired --expect-zero` 返回 0 待处理引用；
- [ ] `python -m pytest tests/test_model_retirement_registry.py -q` 通过（旧 ID 反向断言 + alias 目标不悬空）。

在途数据不靠“等窗口”确认，而是**直接盘点**：`chapter_audio_runs` 等待执行记录、Celery 队列与 `beat_schedule`、
Redis 中以模型 ID 为 key 的缓存，逐项迁移或失效，结果记入第 11 节变更记录。若盘点显示仍有无法迁移的在途旧 ID 任务，
**当日不删**，把该 ID 留在退役登记表待办中直到盘点归零——这是事实门槛，不是日历门槛。

**供应商强制下线**（上游已给出截止日期）：按上游日期执行，先跑齐上述三项证据，再补记截止日期、
无法迁移任务的处置方式、业务风险接受与替代方案。上游一旦下线，旧 ID 必然调用失败，“再保留几天兼容”没有意义。

**退役即物理删除**：证据齐备后，在同一次变更里删除 YAML 条目、适配器类与注册装饰器、`MODEL_ALIASES` 条目、
`config/model_catalog_profiles.yaml` 档案，以及统一清单/业务默认/前端硬编码/测试桩里的旧 ID 引用；
随后执行卡片同步两阶段（6.2 节）、重启后端与 worker（8.5 节）。需要恢复时走 Git 历史与配置快照，不走状态位。

**文字层同属物理删除范围**：配置文件与代码里的注释、来源说明、移交备注同样不点名已退役 ID。
引用审计按目录与上下文放行历史记录（`docs/` 下的换代台账、带日期的实验记录），但**不放行配置与代码注释**：
2026-10-09 为补齐语义标签在 `config/models.yaml` 写的两条来源注释，被 `--expect-zero` 判为 3 处待处理引用，
改成中性表述（上一代视频专项线 / 上一代文生图线）后才归零。需要留存移交证据就写进第 11 节变更记录或
`docs/MODEL_INTEGRATION_REFERENCE.md` 的换代台账，不写回配置文件。

### 7.7 灰度与监控能力分阶段建设

模型切换的验证与发布分为三个阶段，各阶段对基础设施的要求不同：

#### A. 上线前可完成

不需要真实用户流量：

- [已具备] 适配器注册与配置校验（`check_model_integration.py`）；
- [已具备] 请求/响应契约测试（回归测试集）；
- [已具备] 参数边界和输入约束验证（`verify_model_config.py`）；
- [需补齐] 失败、超时、限流、fallback 场景测试（当前无故障注入工具）；
- [需补齐] 固定样本集质量评测（当前无标准化评测集）；
- [需补齐] 成本记录与估算（当前无自动成本统计）；
- [需补齐] 自动化回滚演练（当前依赖人工 git revert + 重启）。

#### B. 小流量阶段完成（待基础设施就绪）

需要分流能力（按用户/项目/任务类型/固定百分比）和请求级模型记录：

- 1%～5% 灰度（内部员工 / 测试租户 / 明确同意的试用用户）；
- 新旧模型指标对比（成功率、P95 延迟、实际成本）；
- fallback 触发率与供应商错误率监控；
- 内容安全拦截率；
- 用户反馈采集；
- 自动停止条件（指标低于阈值时自动切回旧模型）；
- 放量规则与审批人。

#### C. 全量后持续完成

- 长尾场景和异常输入监控；
- 长期质量趋势与成本趋势；
- 供应商稳定性跟踪；
- 退役条件确认（见 7.6 节）。

> **当前状态**：项目尚未具备 B 阶段所需的分流开关、新旧模型独立指标、请求级实际模型记录和一键停止新模型流量等能力。在补建完成前，以 A 阶段的“小批量试跑 + 人工确认”替代，试跑结果记录在第 11 节变更记录中。
>
> **灰度前置条件**（补建时至少需要）：
> - 稳定的分流开关（按用户/项目/任务类型）；
> - 每次请求记录实际使用的模型 ID 与版本；
> - 新旧模型各自独立的成功率/延迟/成本指标；
> - 一键停止新模型流量并回切旧模型；
> - 灰度期间的告警与回滚机制。

### 7.8 中性内部 ID 约定（换代不换 ID）

内部 ID **不含版本号**，升级换代不换 ID；发给上游的真名固定在配置里。这是本项目 2026-10-09 起消除兼容期的正面手段：
只要内部 ID 不随版本变化，升级就不会让前端下拉、数据库历史与提示词引用失效，也就不需要“旧 ID 继续可用”的过渡层。

| 内部 ID | 上游线名（`request_model`） |
| --- | --- |
| `qwen-plus` | `qwen3.7-plus` |
| `qwen-flash` | `qwen3.7-flash` |
| `qwen-flash-fallback` | `qwen3.8-flash`（仅供 `qwen-flash` 失败回退，`task_types` 置空） |
| `deepseek-pro` | `deepseek-v4-pro` |
| `deepseek-flash` | `deepseek-flash` |
| `glm` | `glm-5.3` |
| `kimi-preview` | `kimi/kimi-k2.8-preview` |
| `mimo-pro` | `mimo-v2.6-pro` |
| `mimo-flash` | `mimo-v2.6-flash` |
| `minimax-m` | `MiniMax/MiniMax-M3` |
| `step-preview` | `step-5-preview` |
| `doubao-seed-character` | `doubao-seed-character-260628` |
| `doubao-seed-evolving` | 不设置（Ark 侧自动跟版） |
| `mureka-o1-instrumental` | 不设置 |

由此得到三条硬约束：

1. **换代只改条目内容与适配器实现**：升级时改 YAML 的上游线名、能力、价格、约束，内部 ID 不动。
   用户与历史数据看到的始终是同一个 ID。
2. **`request_model` 必须写在 `config/llm_models.yaml`**：YAML 已有同 `id` 的 spec 时装饰器只挂载适配器类、
   `default_params` 被忽略，写在装饰器上不生效（见 1.2 节）。
3. **适配器类名保留版本**（`Qwen37PlusAdapter`、`GLM53Adapter`）：类名是实现快照而非路由 ID，
   保留版本便于区分同一内部 ID 历史上的不同实现。
4. **中性 ID 的代价是"字段不会自己报警"**：ID 不变，`constraints.max_output_tokens`、`max_thinking_tokens`
   和 `default_params` 里的思考开关都会静默继承上一代，类型检查、配置校验、注册中心都不会红。
   因此换代流程里"重测上限与参数开关"不是可选的收尾优化，而是 5.2 的步骤与 8.3 的必过门禁；
   反制证据是 `scripts/probe_llm_output_limits.py`（漂移退出 1、未探到退出 2）与 `tests/test_llm_output_limit_fact_table.py`。

完整映射表与换代台账（旧 ID 已物理删除、无 alias、不可解析）见 `docs/MODEL_INTEGRATION_REFERENCE.md` 第 6.5 节。

## 8. 标准验证与回归基线

### 8.1 注册与 spec 验证（媒体链）

```powershell
python -c "from adapters.registry import ModelRegistry; r=ModelRegistry(); r._ensure_builtin_registration(); print('adapter=', type(r.get_adapter('your-model-id')).__name__ if r.get_adapter('your-model-id') else None); print('spec_loaded=', r.get_spec('your-model-id') is not None)"
```

`adapter=None` → 检查 `@register_model` 是否存在、模块是否在自动导入列表。

### 8.2 注册与 spec 验证（文本 LLM 链）

```powershell
python -c "from core.unified_registry import UnifiedModelRegistry; import core.llm_adapters; r=UnifiedModelRegistry(); r.load_from_yaml('config/llm_models.yaml'); s=r.get_spec('your-model-id'); a=r.get_adapter('your-model-id'); print('spec=', s is not None); print('adapter=', type(a).__name__ if a else None)"
```

`spec=None` → 检查 `config/llm_models.yaml` 是否定义了该 ID。
`adapter=None` → 检查 `core/llm_adapters.py` 中 `@register_llm_model` 是否存在。

### 8.3 统一自检脚本（推荐入口）

项目已提供两个静态自检脚本，**任何模型变更前后的必过门禁**：

```powershell
# 模型接入自检：配置声明、spec 加载、adapter 注册、路由预览（不发起真实调用）
python scripts/check_model_integration.py --chain all
# 指定单个模型
python scripts/check_model_integration.py --chain media --model-id qwen-image-3.0 --strategy quality
python scripts/check_model_integration.py --chain llm --model-id qwen-plus

# 三层配置一致性校验（intent_domains / models.yaml / semantic_matcher 交叉引用、ID 存在性、fallback 环检测）
python scripts/verify_model_config.py --verbose
```

两个脚本返回非零退出码即表示存在必须修复的问题。

模型**替换或退役**后，第三个必过门禁是全仓引用审计（只读，不发远程调用）：

```powershell
python scripts/audit_model_references.py --all-retired --expect-zero
```

它同时拦下三类问题：残留的旧 ID 引用、指向未注册 ID 的悬空 alias、以及自动导入清单里已不存在的模块
（该处 import 被 `try/except` 吞掉，模块缺失只会静默不注册）。

文本模型**接入或换代**后，第四个必过门禁是档案上限与上游实测的对账（会发真实请求，但刻意让上游在参数校验阶段拒绝，不产生生成开销）：

```powershell
# 逐条越界探测上游真实上限，与 config/llm_models.yaml 对账；漂移退出 1、有未探到条目退出 2、全部一致退出 0
python scripts/probe_llm_output_limits.py
# 只看结果供脚本消费
python scripts/probe_llm_output_limits.py --json
# 把"上游不校验、无法实测"的条目也列出来
python scripts/probe_llm_output_limits.py --include-skipped

# 实测值事实表 + 装饰器镜像 + 强制思考写法约束
python -m pytest "tests/test_llm_output_limit_fact_table.py" -q
```

`tests/test_llm_output_limit_fact_table.py` 里的事实表是**实测结论的登记处**：上游真的改了上限，先重跑探测脚本，再回来改这张表；不要反过来改脚本或改档案去迎合旧值。探测本身的四个坑（关思考后 `thinking_budget` 被忽略、上游回显你传的越界值、强制思考模型要先被参数组合校验拦一次、`max_retries` 不是 `create()` 的参数）记在接入经验文档 §10.17。

### 8.4 最小回归集合

```powershell
python -m pytest "tests/test_model_integration_self_check.py" -q
python -m pytest "tests/test_legacy_runtime_wrappers.py" -q
python -m pytest "tests/test_asset_studio_model_catalog.py" -q
python -m pytest "tests/test_model_catalog_bootstrap.py" -q
```

TTS/音频类替换额外跑：

```powershell
python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

前端统一清单相关：

```powershell
npm --prefix "frontend" run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"
```

### 8.5 重启

改配置或适配器后，重启后端与相关 worker，使两套注册中心的单例/缓存重建。

### 8.6 全量回归的失败归因（先归因再下结论）

本仓库根目录与 backend 各有一批长期既有失败，全量回归的失败数**本来就不为 0**。
只有逐条归因后的数字才是结论；判定某项失败是否本次引入，用只读对比，**不 stash、不建 worktree**
（工作区含他人未提交改动，回滚它们不是本次任务权限）：

- 属性缺失类 `AttributeError`：分别统计 `git show HEAD:<path>` 与工作区里该属性的定义数，
  两边都是 0，说明测试本就对着不存在的实现。
- 断言值不符：对比 HEAD 与工作区的 YAML spec 元数据（质量分、上下文/输出上限）与相关常量，
  逐字节相同则选型结果不变，HEAD 同样会红。
- 签名/构造参数类 `TypeError`：`git diff` 目标目录，统计与本次主题无关的改动行数，为 0 即可排除本次责任。

两类环境噪声会造成假失败，与代码无关：

1. 设了 `PYTHONIOENCODING=utf-8` 后，父进程仍按 GBK 解码子进程管道，`subprocess.run(capture_output=True)`
   的 reader 线程抛 `UnicodeDecodeError` 并使 `.stderr` 变成 `None`；凡断言 `... in completed.stderr`
   的测试都会红。处置：单独复跑该测试时不带该环境变量，通过即证为噪声
   （2026-10-09 backend 比基线多出的 1 项即此因）。
2. `.pytest_cache/v/cache/lastfailed` 长期陈旧，不能当作当前失败清单；
   失败名单一律以本次 `-q --tb=no -rf` 的输出为准。

## 9. 复制即用检查清单

新模型接入：

- [ ] 判定链路（文本 / 媒体）
- [ ] YAML 条目就位
- [ ] 适配器实现 + 注册装饰器
- [ ] 新模块已加入自动导入清单（媒体链，`adapters/registry.py`）
- [ ] 上游真名已固定在 YAML `default_params.request_model` / 适配器 `MODEL_ID` 常量（**不新增 `MODEL_ALIASES` 条目**，见 3.6 与 7.8 节）
- [ ] 输出 / 思考上限已越界探测实测，档案与实测一致（`scripts/probe_llm_output_limits.py` 退出码 0；退出 2 表示有条目没验证过，必须登记原因或补 key）
- [ ] `api_config.api_key_env` 与本仓库 `.env` 实际提供的变量名逐条核对过（缺 key 现在会直接失败：`client_not_initialized` 属永久错误，不重试不回退，结果 `success=False` 并打 error 日志；2026-10-09 前它会静默切到别的厂商并返回 `success=True`，见接入经验文档 §10.22）
- [ ] 关思考写法已实测；强制思考模型已登记 `core/model_resolution.py:_FORCED_THINKING_MODEL_IDS`，且 `default_params` 不含 `enable_thinking` / 关思考 `thinking`（见接入经验文档 §10.20）
- [ ] 实测值已写入 `tests/test_llm_output_limit_fact_table.py` 事实表，装饰器镜像与 YAML 一致
- [ ] 探不到上限的条目已在 `integration_notes` 写明"无法实测 + 原因"，不被当作错值
- [ ] 统一清单 / 默认值（若前端要可选）
- [ ] 语义 `tags`（若要风格路由）
- [ ] 语义标签承载计数不低于基线（删旧条目会静默丢路由且测试不变红，见 7.2 第 7 层）
- [ ] `check_model_integration.py --chain all` 通过
- [ ] `verify_model_config.py` 通过
- [ ] 注册验证 + 最小回归 + 重启

完全替换额外：

- [ ] 旧 ID 全仓引用已扫描（`scripts/audit_model_references.py`，不靠人工 `rg` 子串）
- [ ] 十层核对清单逐项完成
- [ ] 换代后 `constraints.*` 与 `default_params` 参数开关已重新实测（中性 ID 不会提醒，见 7.8 第 4 条；证据：探测脚本退出 0 + 事实表测试绿）
- [ ] `_DEFAULT_MODEL_IDS` / `DEFAULT_*_MODEL_ID` 已改
- [ ] 业务默认/白名单/引擎默认已改
- [ ] 前端硬编码已清理
- [ ] 测试桩已更新
- [ ] `.env` / `.env.example` 的模型取值已同步（引用审计 env 层会自动拦，见 7.1 节；Docker / CI 等仓库外配置仍需人工核对）
- [ ] `bootstrap_model_catalog_cards` 两阶段已执行（先预览、确认后 prune）
- [ ] 持久化数据已按 7.4 节策略处置（含 Celery 队列、Redis、数据库）
- [ ] 残留引用仅剩有意保留项
- [ ] 回滚路径已确认（配置 Git 快照 + `database_backups/` 备份 + 重启 + 验证）
- [ ] 退役证据齐备（7.6 节三项：真实调用回归、引用审计 0 待处理、反向断言测试）
- [ ] 在途数据已盘点归零（待执行 run、Celery 队列与 beat、Redis 缓存），未归零则当日不删
- [ ] 未新增、也未保留任何换代 `MODEL_ALIASES`（唯一例外 `cosyvoice-v3-plus` 需显式记录理由）
- [ ] 旧 ID 已物理删除（YAML 条目 / 适配器与装饰器 / alias / 卡片档案 / 统一清单与默认值 / 测试桩 / 配置与代码注释等文字层）
- [ ] `tests/test_model_retirement_registry.py` 已登记本次退役 ID 并补反向断言
- [ ] 能力等价矩阵已验证通过（完全替换时，见下方门禁要求）
- [ ] 未具备 B 阶段灰度能力时，标记为“小批量人工试跑”，不得宣称已完成生产级灰度
- [ ] 未经业务批准，不得直接切换全量默认模型
- [ ] 全量回归失败已逐条归因（只读 `git show HEAD` 对比，未把环境噪声与既有失败计为本次回归，见 8.6 节）

能力等价矩阵门禁要求（完全替换时强制）：

- 矩阵每一行必须有验证证据（测试结果 / 试跑记录 / 供应商文档）；
- 结论字段限定为：`pass` / `fail` / `accepted-gap`；
- `accepted-gap` 必须填写：责任人、风险说明、补偿措施、过期日期；
- 关键能力（任务类型、输出契约、fallback）存在 `fail` 时，**禁止进入默认路由**；
- 非功能指标（质量、延迟、成本）必须有基准值和新模型实测值。
- **上限类字段（输出 / 思考 / 上下文）以越界探测实测为准**，不接受照抄文档或沿用上一代取值；
  上游不校验该参数导致无法实测的，必须在档案里写明"自选保守值 + 原因"，否则下一轮对账会被误改。

## 10. 维护约定

- 新增/替换模型后，优先回写 `docs/MODEL_INTEGRATION_REFERENCE.md` 的"已验证模型清单"与"模型 ID 映射规则"。
- 能力结论遵循 `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md` 的三类口径（文档声明 / 真实验证 / 项目接入），未真实验证前保留 `pending-runtime-validation` 标签。
- **删除范围含文字层**：配置与代码注释同样不得点名已退役 ID；历史证据留在文档台账里，不写回配置文件。
- 若自动导入列表、投影层机制或统一清单结构发生变化，及时更新本指南第 1、6、7 节。
- **退役即物理删除**：不保留 `status: deprecated` 兼容位、不保留换代 alias、不引入卡片状态阶梯；
  旧 ID 必须"未注册 → 直接报错"，静默改写比失败更危险。
- **内部 ID 用不含版本号的中性名**（7.8 节），上游真名由 `request_model` / `MODEL_ID` 固定；
  两份 YAML 常态下应满足 `deprecated 条目 = 0`，用 `python scripts/audit_model_references.py` 复核。
- 每次退役/改名都要在 `tests/test_model_retirement_registry.py` 登记旧 ID 并补反向断言，
  并把 `python scripts/audit_model_references.py --all-retired --expect-zero` 作为常设门禁（它同时防悬空 alias）。

## 11. 单次模型变更记录模板

每次模型接入 / 替换 / 退役应保留以下记录（可放在 PR 描述或独立 Issue 中）：

```markdown
## 模型变更记录

- 变更类型：[ ] 新接入 / [ ] 版本升级 / [ ] 完全替换 / [ ] 物理退役（操作 E）
- 旧模型 ID：
- 新模型 ID：
- 供应商文档版本 / URL：
- 变更负责人：
- 审查人：
- 变更日期：

### 能力等价矩阵（完全替换时必填，结论限 pass / fail / accepted-gap）

| 维度 | Y 的实际能力 | X 的能力 | 结论 | 验证证据 |
| --- | --- | --- | --- | --- |
| 任务类型（文本/图像/视频/音频/视觉输入/工具调用） | | | | |
| 输入约束（上下文、分辨率、时长、格式、批量） | | | | |
| 输出契约（流式、JSON、媒体 URL、usage、finish reason） | | | | |
| 参数语义（temperature、seed、尺寸、音色、思考模式） | | | | |
| 上限与开关实测（输出/思考上限数值、能否关思考） | | | | |
| 错误与 fallback（超时、限流、供应商异常） | | | | |
| 质量、延迟、成本（基准值 / 实测值） | | | | |
| 安全与数据驻留（内容过滤、地域、授权） | | | | |

关键能力（任务类型、输出契约、fallback）存在 `fail` 时禁止进入默认路由。

`accepted-gap` 项（若有）：

- 能力维度：
- 责任人：
- 风险说明：
- 补偿措施：
- 过期日期：

### 验证证据

- `check_model_integration.py` 输出：
- `verify_model_config.py` 输出：
- `probe_llm_output_limits.py` 退出码与逐条对照结果（文本模型必填；无法实测的条目列出原因）：
- `tests/test_llm_output_limit_fact_table.py` 结果（文本模型必填）：
- 回归测试结果：
- 小批量试跑结果（最低记录要求见下方）：

小批量试跑最低记录格式：

- 样本数量：
- 任务类型：
- 新模型实际调用数：
- 成功数 / 失败数 / fallback 数：
- 平均延迟 / P95：
- 供应商错误类型：
- 成本估算：
- 质量人工评分（1-5）：
- 发现的问题与处理结论：

### 回滚条件

- 观察窗口：___ 天
- 回滚触发条件：
- 旧模型下线日期：

### 可回滚快照

- 发布版本 / 镜像 digest：
- 配置 git commit：
- 数据库迁移版本号：
- 环境变量变更清单：
- 部署制品（镜像 tag / 压缩包）：

### 风险接受

- 已知能力差异：
- 业务方确认：
```
