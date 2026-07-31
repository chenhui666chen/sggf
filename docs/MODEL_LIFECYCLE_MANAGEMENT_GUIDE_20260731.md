# 模型生命周期管理指南（接入 / 更新 / 卡片 / 完全替换）

首版日期：`2026-07-31`
适用范围：新模型接入、模型版本更新、模型中心卡片维护、以及“用一个模型完全替代另一个模型功能”的标准化操作。

## 0. 文档定位与关联文档

本文档是“操作手册”，回答的是**“要做这类变更，按什么顺序改哪些地方、如何验证、如何做到不漏”**。

> **当前版本覆盖范围**：接入、静态校验、人工试跑、持久化数据处置、兼容退役。
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

- 媒体链 `ModelRegistry._ensure_builtin_registration()` 会**固定自动导入 6 个模块**再加载 YAML：
  `adapters.wanx_adapter`、`adapters.wan26_video_adapter`、`adapters.qwen_multimodal_adapter`、`adapters.new_models_adapters`、`adapters.mimo`、`adapters.volcengine`。
  新适配器若放在这 6 个之外的新模块里，**必须把模块名加进这个自动导入列表**，否则 `@register_model` 不会执行。
- 文本链 `@register_llm_model`：如果 `llm_models.yaml` 里已经定义了同 `id` 的 spec，装饰器**以 YAML 为权威，只挂载适配器类**；YAML 未定义时才用装饰器参数构造 spec。因此文本模型的能力/路由请以 YAML 为准维护。
- 归一层 `core/model_resolution.py` 的 `MODEL_ALIASES` 负责把"公开/历史模型 ID"映射到"注册中心真实 ID"（如 `cosyvoice-v3-plus → cosyvoice-v3.5-plus`、`minimax-speech-2.8-hd → MiniMax/speech-2.8-hd`）。

## 2. 四类操作总表（先定位，再执行）

| 操作 | 触发场景 | 核心事实源 | 是否只改 YAML |
| --- | --- | --- | --- |
| A. 新模型接入 | 引入一个当前没有的模型 | YAML + 适配器 + 注册 | 否 |
| B. 模型更新 | 已接入模型调参、升版本、改能力/评分/fallback | 对应 YAML（+ 别名/适配器视变更而定） | 多数可以 |
| C. 卡片更新 | 模型中心页面展示信息/验证状态需要刷新 | config 实时投影 + DB 验证状态 | 见[第 6 节](#6-操作-c模型中心卡片更新) |
| D. 完全替换 | 用模型 X 全面替代模型 Y 的功能 | 全量分散点核对（[第 7 节](#7-操作-d模型完全替换用-x-全面替代-y)） | 否，必须全链路核对 |

## 3. 配置事实源详解

### 3.1 `config/models.yaml`（媒体模型）

每个模型条目的主要字段（以 `wan2.6-t2i`、`wan2.7-t2v` 为实例核对）：

- `id` / `name` / `provider` / `version` / `status`
- `modality`：如 `text_to_image`、`image_to_video`
- `capabilities[]`：`name / support_level(native/emulated/unsupported) / score / description / source / verified_at / confidence`
- `constraints`：`ratios / duration / min_width / max_width / max_batch_size / max_prompt_length` 等
- `quality_metrics`：`overall_score / character_consistency / motion_stability / prompt_adherence / visual_quality / style_accuracy`
- `cost_profile` / `avg_latency_seconds` / `p95_latency_seconds` / `rate_limit`
- `default_params` / `best_practice`（含 `prompt_template`、`recommended_params`、`tips`）
- `fallback_strategies[]`：`trigger_condition / fallback_model_id / param_adjustments / priority`
- `endpoint` / `auth_method` / `summary` / `recommended_scenarios` / `limitations` / `integration_notes`
- `documentation_url` / `source_urls`
- `tags`：**语义匹配的关键字段**（见 3.5）
- 文件末尾 `routing`：`default_strategy` 与 `quality/cost/speed/balanced` 四种策略权重、`fallback` 错误处理器。

### 3.2 `config/llm_models.yaml`（文本 LLM）

每个模型主要字段（以 `qwen3.7-plus` 为实例核对）：

- `id / name / provider / model_type / version / status`
- `capabilities[]`：`name / level / score / description`
- `constraints`：`max_context_tokens / max_output_tokens / max_thinking_tokens / supports_streaming / supports_function_call / supports_vision / supports_json_mode / supports_temperature / supports_thinking_mode` 等
- `api_config`：`api_key_env / base_url / default_timeout / default_max_retries`
- `performance`：`quality_score / avg_latency_seconds / cost_per_1k_input_tokens / cost_per_1k_output_tokens / currency`
- `routing`：`task_types[] / priority / fallback_models[] / weight / enabled`
- `default_params`：`temperature / max_tokens / enable_thinking`
- `summary / recommended_scenarios / limitations / integration_notes / best_practice_tips / documentation_url / source_urls`

维护要点：文本模型的能力与路由以 YAML 为权威，`core/llm_adapters.py` 中 `@register_llm_model` 的同名参数应与 YAML 保持一致，避免两处口径漂移。

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

`MODEL_ALIASES`（公开/历史 ID → 注册真实 ID）、`TASK_TYPE_ALIASES`（历史任务名 → 现行任务名）。凡是"公开 ID 与注册 ID 不一致"、"旧 ID 需继续可用"，都在此加映射。

## 4. 操作 A：新模型接入

### 4.1 判定链路

按 `docs/MODEL_INTEGRATION_REFERENCE.md` 第 3 节判定走文本主链还是媒体调度链。

### 4.2 媒体模型接入步骤

1. 在 `config/models.yaml` 增加模型条目（字段见 3.1）。
2. 在 `adapters/` 复用或新增适配器类，用 `@register_model("<id>")` 注册；新媒体适配器**首选签名** `generate(self, task: TaskSpec) -> GenerationResult`。
3. 若适配器位于**新模块**，把模块名加入 `adapters/registry.py` `_ensure_builtin_registration()` 的自动导入列表。
4. 若"公开 ID"与"注册 ID"不同（如带 `kling/`、`vidu/` 前缀或日期后缀），在 `core/model_resolution.py` `MODEL_ALIASES` 补映射。
5. 需要被 Asset Studio / DreamWeaver 前端选到 → 见[第 7.2 节统一清单层](#72-分层核对清单逐项确认不允许跳过)。
6. 需要语义风格路由 → 按 3.5 三处联动。

### 4.3 文本模型接入步骤

1. 在 `config/llm_models.yaml` 增加模型条目（字段见 3.2）。
2. 在 `core/llm_adapters.py` 增加适配器类；OpenAI 兼容接口通常只需继承 `OpenAICompatibleAdapter` 并用 `@register_llm_model` 注册。
3. 特殊请求参数/响应解析/思考模式策略在适配器类中处理（参考 DeepSeek V4 思考模式约定）。

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
- 公开 ID / 请求模型名变化 → 改 `MODEL_ALIASES`、适配器 `MODEL_ID` 常量、`default_params.request_model`
- 接入渠道切换（如百炼 → 官方 API）→ 改 `api_config.base_url`、`api_key_env`，并同步适配器与 `.env`

### 5.3 版本升级（如 vX → vX+1）

若保留旧 ID 只是底层升版本，优先"就地更新"该条目的 `version` 与能力字段；若要以新 ID 存在且旧 ID 需下线，则视为"完全替换"，走[第 7 节操作 D](#7-操作-d模型完全替换用-x-全面替代-y)。

> **就地更新前提条件**（全部满足才可复用旧 ID）：外部模型请求 ID 未变、请求/响应契约兼容、能力与安全边界无重大变化、历史任务不要求按原版本重放。否则应分配新内部 ID 并在 `MODEL_ALIASES` 保留旧 ID 映射。

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

## 7. 操作 D：模型完全替换（用 X 全面替代 Y）

这是最容易漏改的操作。"替换"不是只改一份 YAML，而是要覆盖 **配置 / 归一 / 适配器 / 统一清单 / 业务默认 / 前端 / 语义领域 / 测试 / 文档 / 数据库快照** 十个层面。

### 7.1 替换前：先做全量引用扫描

先用检索锁定旧模型 ID 的所有落点（示例以 `rg` 检索被替换 ID）：

```powershell
rg -n "旧模型ID" -- config adapters core backend frontend tests scripts docs
```

同时检索它可能出现的别名形式（短横线/斜杠/日期后缀）与它承担的"默认值"键。

### 7.2 分层核对清单（逐项确认，不允许跳过）

1. 配置层
   - `config/models.yaml` 或 `config/llm_models.yaml`：新增/更新新模型条目；旧模型按需下线。
   - `config/model_catalog_profiles.yaml`：迁移/更新档案。
   - `config/intent_domains.yaml`：如旧模型绑定在某 `scene_rules.recommended.target_models`，改成新模型。

2. 归一层
   - `core/model_resolution.py` `MODEL_ALIASES`：如需让旧 ID 请求平滑指向新模型，加 `旧ID → 新ID` 映射。

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

6. 前端层
   - `frontend/src/components/home/AssetStudioWorkbench.tsx`、`frontend/src/pages/DreamWeaverRunPage.tsx`：**只应保留 fallback 常量**，主入口来自 `/api/v1/asset-studio/model-catalog`；如有硬编码旧模型选项，替换或删除。
   - `frontend/src/services/api.ts`：检查是否有把模型 ID 硬编码进 API 路径（如 TTS clone/preview 路径）。
   - `frontend/src/hooks/useAssetStudioModelCatalog.ts`：一般无需改（数据来自后端），确认不再依赖旧常量。

7. 语义领域层（若替换涉及风格/场景能力）
   - `config/models.yaml` 新模型 `tags` 补齐旧模型承担的 style/scene 标签，保证语义路由不丢能力。
   - 全新类别才需要动 `core/semantic_matcher.py` 与 `config/intent_domains.yaml`。

8. 测试层
   - 更新所有硬编码旧模型 ID 的测试桩（如 `backend/tests/test_audiobook_tts_model_ids.py`、`test_audiobook_tts_provider_payloads.py`、`tests/test_model_integration_self_check.py`、`tests/test_legacy_runtime_wrappers.py`、`tests/test_model_catalog_bootstrap.py` 等）。

9. 文档层
   - 同步 `docs/MODEL_INTEGRATION_REFERENCE.md`（已验证清单/映射规则）、`docs/MODEL_KNOWLEDGE_BASE_20260315.md` 及本指南。

10. 数据库快照层
   - 按[第 6.2 节两阶段流程](#62-结论改卡片改数据库)同步卡片（先预览 stale 列表，确认后再 `--prune-stale`）。

### 7.3 替换后自检

- 全仓再检索一次旧模型 ID，确认只剩"别名映射/历史兼容/文档说明"这类**有意保留**的引用。
- 按[第 8 节](#8-标准验证与回归基线)跑回归。

### 7.4 持久化数据处置

代码引用替换完成后，还必须检查以下可能保存旧模型 ID 的位置：

| 数据类型 | 处置策略 |
| --- | --- |
| 项目设置 / 工作流配置（`projects`、`audiobook_projects` 的 JSON 字段） | 显式迁移为新 ID（数据库 UPDATE） |
| 已创建但未执行的 Celery 任务（broker 队列中） | ① 暂停消费；② 检查队列中旧 ID 任务；③ 对每个任务决定：继续使用旧模型执行 / 取消后按新模型重新入队 / 人工处理；④ 记录任务 ID、原模型、处置结果 |
| 已创建但未执行的数据库任务 / 工作流快照 | 显式迁移为新 ID，或标记为已取消 |
| 历史执行记录 / 审计日志 / 生成记录（`chapter_audio_runs`、`generation_feedbacks`） | **保留原始 ID，不改写历史事实** |
| Redis 缓存（模型路由结果、会话状态） | 按模型 ID 主动失效，或等待 TTL 过期 |
| 进程内单例（注册中心缓存） | 重启后端与 worker 即可重建 |
| 环境变量 / 部署平台配置（`.env`、Docker、CI/CD） | 检查并替换旧 ID 引用 |
| 定时任务（Celery Beat） | 检查 `celery_app.py` 中 `beat_schedule` 是否引用旧 ID |
| 长时间运行任务 | 明确继续使用旧模型完成、取消、或重新调度 |

数据库迁移参考（**伪代码示例，不可直接执行**，以 PostgreSQL 为例）：

```sql
-- 第一步：扫描可能含有模型 ID 的表和字段
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type IN ('character varying', 'text', 'jsonb');

-- 第二步：对每张目标表确认影响行数
SELECT COUNT(*) FROM audiobook_projects WHERE tts_model_id = 'old-model-id';
SELECT COUNT(*) FROM chapter_audio_runs WHERE model_id = 'old-model-id';

-- 第三步：在事务内执行迁移（确认行数符合预期后）
BEGIN;
UPDATE audiobook_projects SET tts_model_id = 'new-model-id' WHERE tts_model_id = 'old-model-id';
-- 确认影响行数正确后 COMMIT，否则 ROLLBACK
COMMIT;
```

> **安全要求**：① 上述表名/字段名为示例，执行前必须核对实际表结构；② JSON/JSONB 字段需用 `jsonb_set` 或应用层脚本处理，不能简单 UPDATE；③ 每次迁移必须在事务内执行并保存审计输出；④ 优先编写可重跑的迁移脚本（支持 dry-run）而非手工 SQL。

### 7.5 回滚路径

若新模型上线后出现异常（质量下降、超时率升高、供应商故障），按以下顺序执行完整回滚：

1. **恢复配置与代码快照**：恢复本次变更记录中保存的配置、代码、环境变量和部署版本快照。若通过 Git 回滚，必须确认目标提交只包含本次模型变更（而非无关改动），并经过发布审批。
2. **恢复运行态**：重启后端与 Celery worker，重建进程内注册中心单例和路由缓存；对 Redis 中包含模型 ID 的缓存按 key 主动失效（或确认 TTL 已足够短）。
3. **恢复数据库待执行数据**：将已迁移为新 ID 的待执行任务、项目设置回滚为旧 ID（在事务内执行）。
4. **验证回滚生效**：运行 `python scripts/check_model_integration.py --chain all`，确认默认路由和显式 ID 均指向旧模型。
5. **保留兼容 alias**：回滚完成后，可在 `MODEL_ALIASES` 中保留 `new-id → old-id` 映射，使已发出但未回滚的外部请求仍能解析。

> **重要**：`MODEL_ALIASES` 只是兼容层，不能作为完整回滚机制。它只影响经过 `normalize_model_id()` 的调用路径，不影响默认路由、`_DEFAULT_MODEL_IDS`、环境变量、数据库持久化数据和 Celery 队列中的任务。

每次变更记录应保存以下可回滚信息：

- 发布版本 / 镜像 digest；
- 配置版本或配置 hash（YAML 文件的 git commit）；
- 数据库迁移版本号；
- 环境变量变更清单；
- 可恢复的部署制品（镜像 tag / 压缩包）。

### 7.6 兼容期与退役门槛

完全替换后旧模型适配器与 YAML 条目进入兼容期，退役必须**同时满足**：

- 兼容期不少于 **14 天**（自默认模型切换之日起算）；
- 数据库待执行任务和 Celery 队列中旧 ID 引用数量为 0；
- 旧 ID alias 命中量连续 3 个观察窗口（每窗口 ≥ 24h）为 0；
- 旧模型实际调用量为 0（含外部客户端、定时任务、第三方集成）；
- 新模型无未关闭的高优先级回归问题；
- 业务方确认可以下线。

兼容期内旧 ID 通过 alias 解析到新模型，但不再作为默认选项展示。若业务方要求延长兼容期，则从其要求。

**供应商强制退役流程**（供应商下线日期早于 14 天兼容期时启用）：

允许缩短兼容期，但必须完成：

- 记录供应商截止日期；
- 完成旧 ID 流量和队列盘点；
- 明确无法迁移的任务处置；
- 取得业务风险接受；
- 保留可用的历史展示和审计信息；
- 记录应急回滚或替代方案。

**退役操作与卡片状态生命周期**：

模型卡片不应在退役时立即物理删除，应按状态递进：

```
active → selectable=false → deprecated → compatibility-only → retired
```

- `selectable=false`：从新增模型选择列表中隐藏，但历史任务仍可显示；
- `deprecated`：卡片标记弃用，alias 仍生效；
- `compatibility-only`：仅保留 alias 兼容，不可主动选择；
- `retired`：确认无历史展示、重放和审计要求后，才执行物理清理（删除适配器、YAML 条目、alias 映射，执行卡片同步两阶段）。

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
python scripts/check_model_integration.py --chain media --model-id wan2.6-t2i --strategy quality
python scripts/check_model_integration.py --chain llm --model-id qwen3.7-plus

# 三层配置一致性校验（intent_domains / models.yaml / semantic_matcher 交叉引用、ID 存在性、fallback 环检测）
python scripts/verify_model_config.py --verbose
```

两个脚本返回非零退出码即表示存在必须修复的问题。

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

## 9. 复制即用检查清单

新模型接入：

- [ ] 判定链路（文本 / 媒体）
- [ ] YAML 条目就位
- [ ] 适配器实现 + 注册装饰器
- [ ] 新模块已加入自动导入列表（媒体链）
- [ ] `MODEL_ALIASES` 映射（若公开 ID ≠ 注册 ID）
- [ ] 统一清单 / 默认值（若前端要可选）
- [ ] 语义 `tags`（若要风格路由）
- [ ] `check_model_integration.py --chain all` 通过
- [ ] `verify_model_config.py` 通过
- [ ] 注册验证 + 最小回归 + 重启

完全替换额外：

- [ ] 旧 ID 全仓引用已扫描
- [ ] 十层核对清单逐项完成
- [ ] `_DEFAULT_MODEL_IDS` / `DEFAULT_*_MODEL_ID` 已改
- [ ] 业务默认/白名单/引擎默认已改
- [ ] 前端硬编码已清理
- [ ] 测试桩已更新
- [ ] `bootstrap_model_catalog_cards` 两阶段已执行（先预览、确认后 prune）
- [ ] 持久化数据已按 7.4 节策略处置（含 Celery 队列、Redis、数据库）
- [ ] 残留引用仅剩有意保留项
- [ ] 回滚路径已确认（配置快照 + 重启 + 验证）
- [ ] 兼容期与退役门槛已明确（≥ 14 天 + 条件门槛）
- [ ] 能力等价矩阵已验证通过（完全替换时，见下方门禁要求）
- [ ] 未具备 B 阶段灰度能力时，标记为“小批量人工试跑”，不得宣称已完成生产级灰度
- [ ] 未经业务批准，不得直接切换全量默认模型

能力等价矩阵门禁要求（完全替换时强制）：

- 矩阵每一行必须有验证证据（测试结果 / 试跑记录 / 供应商文档）；
- 结论字段限定为：`pass` / `fail` / `accepted-gap`；
- `accepted-gap` 必须填写：责任人、风险说明、补偿措施、过期日期；
- 关键能力（任务类型、输出契约、fallback）存在 `fail` 时，**禁止进入默认路由**；
- 非功能指标（质量、延迟、成本）必须有基准值和新模型实测值。

## 10. 维护约定

- 新增/替换模型后，优先回写 `docs/MODEL_INTEGRATION_REFERENCE.md` 的"已验证模型清单"与"模型 ID 映射规则"。
- 能力结论遵循 `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md` 的三类口径（文档声明 / 真实验证 / 项目接入），未真实验证前保留 `pending-runtime-validation` 标签。
- 若自动导入列表、投影层机制或统一清单结构发生变化，及时更新本指南第 1、6、7 节。

## 11. 单次模型变更记录模板

每次模型接入 / 替换 / 退役应保留以下记录（可放在 PR 描述或独立 Issue 中）：

```markdown
## 模型变更记录

- 变更类型：[ ] 新接入 / [ ] 版本升级 / [ ] 完全替换 / [ ] 退役
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
