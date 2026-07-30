# 灵感方舟免费档（qwen3.7-flash）生成方案指导文档

> 创建日期：2026-07-25（v2，含第二轮审查修订）
> 状态：已实施完成（2026-07-25，七步全部落地，第 8 节上线门槛全部验收通过，见第 11 节实施记录）
> 范围：`POST /api/v1/workflow/{project_id}/generate-next-chapter` 单章生成链路

## 1. 背景与目标

为灵感方舟提供一个免费生成档位，用于用户免费体验：

- 全链路强制使用 `qwen3.7-flash`（含规划、正文、评审、迭代、后置提取与摘要）
- 迭代优化最多 1 轮（标准档为 2 轮）
- 禁用多模型评审
- 每用户每天免费生成 2 章
- 标准档行为在强制开关未开启时完全不受影响

### 成本基线（qwen3.7-flash：输入 0.2 元/M tokens，输出 0.8 元/M tokens）

| 场景 | 单章成本 |
|---|---|
| 一次过（5 次 LLM 调用：规划+正文+评审+后置提取+后置摘要） | ≈ 0.013～0.02 元 |
| 触发 1 轮迭代（+3 次调用：计划+改稿+复评） | +0.008～0.009 元 |
| **免费档单章上限（正常路径）** | **≈ 0.03 元** |

单用户日成本上限 ≈ 0.06 元；1 万日活用满 ≈ 600 元/天。该数字是**正常路径估算，不是硬上限**：重试、回退提取、模型重路由都可能放大实际成本，由第 3.4 节模型严格策略与第 5 节护栏约束。

## 2. 核心设计：GenerationProfile 与服务端权益判定

### 2.1 原则

- `generation_tier` 请求字段**只表达用户意图，不是权限依据**
- 最终档位由**服务端权益判定**决定：无标准档权益的用户，无论传 `standard` 还是缺省，一律落入 FREE_PROFILE
- 服务端在端点处解析出**不可变的 GenerationProfile**，后台任务只接受解析后的明确参数，不再信任任何请求字段
- 解析点收敛到一个函数，付费体系将来接入时只改这一处

### 2.2 结构

```python
# backend/app/api/v1/workflow/generation_profile.py（新建）
@dataclass(frozen=True)
class GenerationProfile:
    tier: str                          # "free" | "standard"
    model: Optional[str]               # 免费档强制 "qwen3.7-flash"；标准档为用户所选模型
    max_iteration_rounds: int          # 免费档 1；标准档沿用 settings 默认 2
    enable_multi_model_review: bool    # 免费档 False
    max_llm_attempts: int              # 总尝试次数（含首次）。免费档 2；标准档 3（现状）
    allow_model_fallback: bool         # 免费档 False：禁止 catalog guard 换模型
    quota_enabled: bool                # 免费档 True

FREE_PROFILE = GenerationProfile(
    tier="free",
    model="qwen3.7-flash",
    max_iteration_rounds=1,
    enable_multi_model_review=False,
    max_llm_attempts=2,
    allow_model_fallback=False,
    quota_enabled=True,
)
```

注意：字段命名用 `max_llm_attempts` 而非 `max_retries`，因为 `streaming_service.generate_with_streaming` 的 `max_retries=N` 语义实际是**最多总尝试 N 次**（`for attempt in range(max_retries)`），不是"首次之外再重试 N 次"。

### 2.3 权益判定（方案A：配置开关 + 现有 Role 体系）

项目已有完整的 Role/Permission 体系（`backend/app/models/role.py`：roles、user_roles、permissions 表，`User.roles` 关系已存在），标准档权益直接绑角色码，**无需数据库迁移**。

新增两项配置（`app/core/config.py`）：

```python
FREE_TIER_ENFORCEMENT_ENABLED: bool = False           # 免费档强制开关，默认关
FREE_TIER_STANDARD_ROLE_CODES: str = "admin,standard_generation"  # 拥有任一角色码即具标准档权益
```

解析逻辑：

```python
def resolve_generation_profile(*, current_user, requested_tier, requested_model) -> GenerationProfile:
    if requested_tier == "free":
        return FREE_PROFILE                    # 显式请求免费档始终生效
    if not settings.FREE_TIER_ENFORCEMENT_ENABLED:
        return build_standard_profile(requested_model)   # 开关未开启：与现状一致
    if not _user_has_standard_access(current_user):      # 按角色码判定
        return FREE_PROFILE                    # 无权益用户强制免费档，无法绕过
    return build_standard_profile(requested_model)
```

行为矩阵：

| 开关 | 用户权益 | 请求 tier | 最终档位 |
|---|---|---|---|
| 关 | 任意 | free | 免费档 |
| 关 | 任意 | standard/缺省 | 标准档（现状） |
| 开 | 无角色 | 任意 | **免费档（强制）** |
| 开 | 有角色 | standard/缺省 | 标准档 |
| 开 | 有角色 | free | 免费档 |

上线灰度路径：先部署代码（开关关闭，行为零变化）→ 给内部账号配角色 → 开启开关严格执行。

## 3. 链路模型透传矩阵

调研结论（基于 `routes_chapter.py` 的 `execute_generate_next_chapter_task`）：

| 环节 | 现状 | 免费档改动 |
|---|---|---|
| 章节规划（L1007-1022） | 已尊重 `workflow_generation_model` | 无需改，profile.model 走同一参数 |
| 正文创作（L1292-1299） | 已尊重 | 无需改 |
| 迭代改稿（L1661-1680） | 已尊重 | 无需改 |
| 初评（L1524 → `_run_single_next_chapter_streaming_review` L158） | 只传 `task_type="review"`，走路由到 deepseek-v4-pro | **调用点补传 `model=profile.model`** |
| 轮内复评（L1834） | 同上 | **调用点补传 `model=profile.model`** |
| 多模型评审（review_feature_gate） | 由项目级 `review_config` 触发 | **profile.enable_multi_model_review=False 时短路，不进 gate** |
| 后置统一提取（unified_extraction L65-71） | 走环境变量，默认 deepseek-v4-pro | **透传 `post_processing_model`（见 3.2） |
| 后置三段式回退提取 | 三个服务方法均无 model 参数 | **签名加 model 参数并透传** |
| 后置章节摘要（chapter_summarizer L54 `create_task_llm()`） | 无模型参数，与 UnifiedExtractionService 无关 | **改造 summarizer 构造链传模型** |

### 3.1 评审透传的关键事实（已核实）

- `StreamingService.generate_chapter_streaming`（`streaming_service.py` L101-110）**已有 `model` 参数**
- 模型健康时，显式 model 优先于 task_type 路由（`core/model_hub.py` L397-411）
- 结论：不新增 `forced_model` 概念，只在两个评审调用点透传现有 `model` 参数；但显式模型**不保证**最终执行模型，见 3.4

### 3.2 后置处理透传：`post_processing_model`（不用 .env 全局切换）

- 修改 `UNIFIED_EXTRACTION_MODEL` 环境变量会同时影响所有档位，无法隔离，**不采用**；也不直接修改和提交 `backend/.env`
- 参数命名为 `post_processing_model`（它同时控制统一提取、回退提取和摘要，不只是 extraction）；缺省 None 时所有服务保持现有行为（标准档不变）
- **改动范围（5 个文件，明确列出，不用"等"）**：
  1. `chapter_post_save.py`：`chapter_post_save_task` 加参数并向下透传（统一提取 L271、三段回退 L294/L303/L312、摘要 L422）
  2. `unified_extraction.py`：`extract_all_from_chapter` 加 `model` 参数，非空时覆盖环境变量逻辑
  3. `agents/chapter_summarizer.py`：`create_chapter_summarizer(..., model=None)` → `ChapterSummarizer.__init__(..., model=None)` → `self.llm = create_task_llm(model=model)`（L54 现为无参调用）
  4. `entity_extraction.py`：`extract_entities_from_chapter`（L96）与 `extract_relations_from_chapter`（L182）加 `model` 参数
  5. `location_hierarchy_extractor.py`：`extract_location_hierarchy`（L22）加 `model` 参数
- 回退路径必须纳入模型锁定测试：否则正常路径 flash、异常回退路径却用其他模型

### 3.3 迭代轮数

- 现状：`getattr(settings, 'ITERATION_MAX_ROUNDS', 2)`（routes_chapter.py L1578-1584），config.py 中未定义该字段，无按请求覆盖机制
- 改动：后台任务函数新增 `max_iteration_rounds: Optional[int]` 参数，非 None 时覆盖全局值；免费档传 1

### 3.4 模型严格策略（catalog guard 下的 fail closed）

**已核实的风险**：`model_hub._resolve_catalog_guarded_model`（`core/model_hub.py` L565-604）在显式模型被联网校验标记 blocked 时，会 `select_best_model(task_type)` 自动切换到其他模型——免费档请求 flash 可能实际执行更贵的模型。"显式模型优先"只在模型健康时成立。

免费档（`allow_model_fallback=False`）执行以下策略：

1. **端点预检**：创建任务前调用 `resolve_model_request(model="qwen3.7-flash", ...)`，`resolved_model_id != "qwen3.7-flash"` 时直接返回 503（"免费模型暂不可用"），不占额度、不启动任务
2. **调用后校验**：链路各 LLM 调用完成后检查结果 metadata 的 `resolved_model_id`（`_attach_resolution_metadata` 已写入，model_hub.py L606-610），发现重路由立即终止后续链路，按额度语义退款并标记任务失败
3. **绝不降级到更贵模型**：flash 不可用时免费档整体 fail closed，不 fallback

标准档不受此策略影响，保持现有 catalog guard 行为。

## 4. 并发控制与每日配额

### 4.1 项目生成锁（新增，阻塞级修正）

**已核实的缺口**：`_active_generate_next_chapter_task_ids`（routes_chapter.py L40-52）是按随机 task_id 记录的**进程内 set**，不按 project_id 互斥、不跨 worker/实例。并发请求会拿到相同 `next_chapter_number`，各自生成、落库并重复扣额。

修正：Redis 项目锁，**所有档位生效**（这是正确性问题，不是免费档专属）：

```
键：inspiration_ark:chapter_gen_lock:{project_id}
值：唯一 token（uuid4）
获取：SET NX EX <ttl>（TTL 略大于单章生成最长耗时，如 30 分钟）
释放：比对 token 后 DEL（Lua 或 GET+DEL 校验），避免误删其他任务续租后的锁
```

端点固化执行顺序：

```
1. 鉴权与项目归属校验
2. 获取项目生成锁（失败 → 409 "该项目已有生成任务进行中"）
3. 原子占用用户额度与全局发放量（免费档，Lua，见 4.2）
4. 计算 next_chapter_number
5. 创建 generation_history
6. 启动后台任务
```

3～6 任一步失败：退还额度（清理 reservation）并释放锁。任务结束（成功/失败）后用 token 释放锁。

### 4.2 配额原子占用（Lua 脚本）

因需在同一原子操作内处理**用户额度 + 全局发放量 + TTL + 上限封顶**四件事，采用一个短 Lua 脚本（多命令+补偿分支反而更复杂）：

```
键：
  inspiration_ark:free_chapter_quota:{user_id}:{yyyymmdd}   用户日额度
  inspiration_ark:free_daily_total:{yyyymmdd}               全局日发放量
（日期按 Asia/Shanghai 业务时区计算，日界线由键名保证，不依赖 TTL）

脚本语义（单脚本原子完成）：
  1. 用户计数 >= 2 → 拒绝（不递增，防攻击者推高计数值）
  2. 全局计数 >= 阈值 → 拒绝
  3. 两个计数各 INCR，首次创建时设 TTL（48h 兜底）
  4. 返回 [允许标志, 剩余额度, 重置时间]
```

- 超限**不递增不回滚**，判断以脚本返回为准
- 脚本内封顶，避免恶意请求推高计数产生写压力与统计污染

### 4.3 额度消耗语义与崩溃恢复

| 时机 | 是否扣额度 |
|---|---|
| 参数错误、项目校验失败、任务未启动 | 不扣（校验与锁之后才占额） |
| 任务启动后、**首次产出正文之前**失败 | 退回 |
| 已产生正文或完成落库后失败 | 不退（防止主动断连反复刷生成） |

崩溃恢复采用**轻量 reservation 状态键**（非两阶段协议，就是一个带 TTL 的状态标记）：

```
键：inspiration_ark:free_quota_reservation:{task_id}
值：{"user_id": ..., "date": ..., "status": "pending"}，TTL 2 小时
```

- 占额成功后写入 `pending`；首次正文输出时置 `consumed`
- 任务异常路径：读取 reservation，`pending` 则退额并删除键（状态转换幂等，防重复退款）
- **懒清理**：用户下次请求配额时，扫描该用户过期未 consumed 的 reservation 并退回——覆盖 worker 被杀、OOM、重启等进程内 try/except 无法覆盖的场景
- 单纯的任务内布尔标志被否决：无崩溃恢复能力，对每天仅 2 次的额度误扣不可接受

### 4.4 故障策略（fail closed）

- Redis 不可用时**免费档拒绝生成**（503 "免费额度服务暂不可用"），绝不降级放行
- 标准档不经过配额服务，Redis 故障不影响标准档；但项目锁是全档位的——Redis 故障时项目锁降级策略：标准档回退进程内互斥（尽力而为）并告警，免费档直接拒绝
- 超额返回 **429**，响应体带剩余额度与重置时间

## 5. 护栏（术语修正：不是成本熔断）

- **全局免费发放量护栏**：`free_daily_total` 按当日免费章数封顶（4.2 脚本内原子判断）。按章数计数**不等于成本**（迭代触发数、重试、回退提取、上下文长度都会波动），因此本期只承诺"发放量护栏"，不称"成本熔断"
- **主生成链路重试收紧**：`generate_chapter_streaming` 增加 `max_retries` 透传，免费档传 `profile.max_llm_attempts=2`（最多总尝试 2 次）。该参数只覆盖规划/正文/评审/迭代等流式调用；摘要 `create_task_llm()`、统一提取、三段回退的内部重试在步骤 3 实施时逐一审计并收紧
- 真正的**成本熔断**（按实际调用模型、input/output token 记账）留待后续独立任务；在记账落地前，文档与代码注释一律不使用"成本熔断"表述

## 6. 前端改动

- `api.ts`：`generateNextWorkflowChapter(projectId, options)` 改为请求对象参数。**camelCase→snake_case 映射在 api.ts 内完成**，FastAPI 收到的请求体始终是 snake_case：

```typescript
// 前端调用（camelCase options）
generateNextWorkflowChapter(projectId, { generationTier: 'free', workflowGenerationModel: '...' })
// api.ts 内映射为请求体（snake_case）
{ "generation_tier": "free", "workflow_generation_model": "..." }
```

- 签名变更影响**两个现有调用点**，均需更新并回归：
  - `WorkflowControlPage.tsx` L2471（传模型）
  - `DashboardPage.tsx` L638（不传模型，保持标准档语义）
- WorkflowControlPage：免费生成入口；剩余免费额度展示；429（今日额度已用完）/ 503（免费模型或额度服务不可用）/ 409（项目已有生成任务）的明确提示

## 7. 实施步骤（分步执行，每步完成后等待确认）

| 步骤 | 内容 | 主要文件 | 验收标准 | 状态 |
|---|---|---|---|---|
| 1 | GenerationProfile + 权益判定（开关+角色码）+ `generation_tier` 字段 + 端点解析 + 后台任务签名接受明确参数 | 新建 `generation_profile.py`；`schemas.py`；`config.py`；`routes_chapter.py` | 开关关：行为与现状一致；开关开：无角色用户传 standard/缺省也落免费档 | ✅ 完成 |
| 2 | 模型严格策略：评审透传 model、多模型评审短路、端点预检+调用后校验 resolved_model_id、`max_retries` 透传 | `routes_chapter.py`；`streaming_service.py` | flash 被 blocked 时免费档 503 不降级；免费档评审日志模型为 flash；标准档评审仍走 review 路由 | ✅ 完成 |
| 3 | 后置 `post_processing_model` 透传（3.2 节全部 5 个文件，含回退与摘要） | `chapter_post_save.py`；`unified_extraction.py`；`chapter_summarizer.py`；`entity_extraction.py`；`location_hierarchy_extractor.py` | 免费档统一提取/回退/摘要日志模型均为 flash；缺省调用行为不变 | ✅ 完成 |
| 4 | 项目生成锁（Redis SET NX + token + TTL）+ 端点六步执行顺序固化 | 新建锁模块；`routes_chapter.py` | 跨进程并发 2 请求同项目只放行 1，另一个 409；任务结束锁释放 | ✅ 完成 |
| 5 | 配额 Lua 脚本（用户+全局+TTL+封顶原子完成）+ reservation 状态键 + 懒清理 + fail closed | 新建配额服务模块；`routes_chapter.py` | 并发 3 请求只放行 2；Redis 断连免费档 503、标准档正常；杀进程后额度可恢复 | ✅ 完成 |
| 6 | 前端：options 对象化（映射在 api.ts）+ 两调用点回归 + 免费入口 + 额度展示 + 429/503/409 提示 | `api.ts`；`WorkflowControlPage.tsx`；`DashboardPage.tsx` | 免费生成全流程走通，超额/锁冲突有明确提示 | ✅ 完成 |
| 7 | 测试：见第 8 节上线门槛全部条目 | `backend/tests/` | 全部通过；标准档既有测试不回归 | ✅ 完成 |

## 8. 上线门槛（硬性验收条件）

1. 未具备标准档权益的用户（开关开启时），传 `standard` 或省略档位，必须落入免费档并受每天 2 章限制——**伪造 tier 测试必须存在**
2. 免费档实际解析模型不是 qwen3.7-flash 时 fail closed（503），禁止自动切换到其他模型——**catalog fallback 模拟测试必须存在**
3. 同一项目只能有一个生成任务，互斥跨进程、跨实例有效——**跨 worker 并发测试必须存在**
4. 主链（规划/正文/迭代）、初评、复评、统一提取、三段式回退、摘要**全部**验证实际模型为 flash——含异常回退路径
5. 用户额度和全局发放量在一个原子操作（Lua）中检查、占用并设置 TTL
6. 任务创建失败、进程崩溃、首次正文前失败三种场景的额度恢复均有测试覆盖
7. 文档与代码中不出现"成本熔断"表述（改为"全局免费发放量护栏"），直至 token 记账落地
8. 标准档在开关关闭时行为与现状逐字节一致（回归测试）

## 9. 已裁决的设计取舍（v2 修订，含翻案记录）

| 提议 | v1 裁决 | v2 裁决 | 理由 |
|---|---|---|---|
| 服务端权益解析 | 恒等映射 | **推翻 v1：方案A（开关+Role 角色码）** | 恒等映射下配额可被 standard 请求完全绕过，业务规则矛盾；项目已有 Role 体系，无需迁移 |
| Lua 脚本 | 否决 | **推翻 v1：采用** | v1 前提是单计数器；现需用户额度+全局发放量+TTL+封顶原子一致，Lua 比多命令+补偿更符合 KISS |
| reservation_id 两阶段协议 | 否决 | **部分采纳：轻量状态键** | 布尔标志无崩溃恢复能力；但完整两阶段协议仍过重，带 TTL 的状态键+懒清理已覆盖崩溃场景 |
| "显式模型优先"作为强制保证 | 采信 | **修正：仅模型健康时成立** | catalog guard（model_hub L565-604）blocked 时自动换模型，免费档需 allow_model_fallback=False + 双重校验 |
| 超限回滚（DECR） | 否决 | 维持否决，改为**脚本内封顶不递增** | 判断以脚本返回为准；封顶防计数被恶意推高 |
| `.env` 全局切换后置提取模型 | 否决 | 维持否决 | 无法隔离档位；改为 `post_processing_model` 参数透传 |
| 新增 `forced_model` 概念 | 否决 | 维持否决 | streaming_service 已有 `model` 参数 |
| "成本熔断"表述 | 采用 | **修正为"全局免费发放量护栏"** | 章数≠成本；无 token 记账前不承诺成本上限 |
| token 级成本记账 | 推迟 | 维持推迟 | 观测增强，不阻塞上线；但推迟期间不得使用"成本熔断"表述 |
| 设备指纹防滥用 | 推迟 | 维持推迟 | 只能作风险信号；第一版手机号验证开关 + IP 限速（独立任务） |

## 10. 不在本期范围

- 付费/会员订阅体系（权益判定已预留 Role 角色码接口）
- 防滥用：手机号强制验证、IP/设备维度限速（独立任务）
- token 级成本记账与按模型费用报表（落地后方可启用"成本熔断"表述）
- 免费档专属的正文目标字数调整（当前 ChapterPromptBuilder 写死"约 3000 字"）

## 11. 实施记录（2026-07-25 完成）

### 11.1 落地文件清单

**后端新建：**

| 文件 | 职责 |
|---|---|
| `backend/app/api/v1/workflow/generation_profile.py` | GenerationProfile 冻结数据类 + FREE_PROFILE + 权益判定（开关+角色码）+ 标准档模型准入校验 |
| `backend/app/services/generation_lock.py` | 项目生成锁：SET NX EX 1800 + uuid4 token + Lua compare-del 释放；标准档 Redis 故障回退进程内互斥，免费档 fail closed |
| `backend/app/services/free_quota.py` | 配额 Lua 原子占用（用户封顶→全局封顶→双 INCR→首次 TTL 48h）+ reservation 状态键（TTL 2h）+ 懒清理（30 分钟 stale 退回）+ 防负数退款 |

**后端修改：** `routes_chapter.py`（端点六步顺序、锁/配额接入、后台任务责任转交）、`streaming_service.py`（model 锁定 + max_retries + 重路由校验）、`chapter_post_save.py` / `unified_extraction.py` / `chapter_summarizer.py` / `entity_extraction.py` / `location_hierarchy_extractor.py`（post_processing_model 透传）、`schemas.py`（generation_tier）、`config.py`（FREE_TIER_ENFORCEMENT_ENABLED / FREE_TIER_STANDARD_ROLE_CODES / FREE_TIER_DAILY_CHAPTER_LIMIT=2 / FREE_TIER_GLOBAL_DAILY_LIMIT=500）

**前端修改：** `api.ts`（generateNextWorkflowChapter options 对象化，camelCase→snake_case 映射在 api 层）、`WorkflowControlPage.tsx`（免费入口按钮 + 剩余额度展示 + 429/503/409 提示）、`DashboardPage.tsx`（错误处理 detail 对象加固）

### 11.2 测试覆盖（第 8 节八条门槛验收）

| 测试文件 | 数量 | 对应门槛 |
|---|---|---|
| `tests/test_generation_profile.py` | 13 | 门槛 1（伪造 tier）、门槛 8（开关关行为一致） |
| `tests/test_free_tier_model_strict.py` | 10 | 门槛 2（catalog fallback 时 503 不降级）、门槛 4（主链/初评/复评） |
| `tests/test_post_processing_model_passthrough.py` | 9 | 门槛 4（统一提取/三段回退/摘要，含异常回退路径） |
| `tests/test_generation_lock.py` | 10 | 门槛 3（含 `test_cross_worker_mutual_exclusion` 跨实例互斥） |
| `tests/test_free_quota.py` | 12 | 门槛 5（Lua 原子）、门槛 6（三种额度恢复场景） |
| 前端 `api.workflow.test.ts` | +3 | 步骤 6（snake_case 映射 / free 只传 tier / 缺省空 payload） |

门槛 7（"成本熔断"表述）：全仓检索确认代码与注释零出现，仅本文档术语裁决说明处保留。
门槛 8 回归：`test_chapter_post_save.py` 等标准档既有测试 48 项全部通过。

### 11.3 上线开关说明

- 当前 `FREE_TIER_ENFORCEMENT_ENABLED=False`（默认关闭），标准档行为与实施前一致
- 正式启用时：`.env` 置 `True`，并确认 Redis 可用（免费档对锁与配额服务均 fail closed → 503）
- 业务日界线按 UTC+8 固定偏移（代码中 `BUSINESS_TZ`，不依赖系统 tzdata）

## 附录：关键代码位置速查（均已核实）

| 事实 | 位置 |
|---|---|
| 迭代轮数读取 | `routes_chapter.py` L1578-1584（getattr，config.py 未定义字段） |
| 初评调用（只传 task_type） | `routes_chapter.py` L158-164 |
| 复评调用 | `routes_chapter.py` L1834-1840 |
| 显式 model 优先（仅健康时） | `core/model_hub.py` L397-411 |
| catalog guard 自动换模型 | `core/model_hub.py` L565-604（`_resolve_catalog_guarded_model`） |
| 调用结果携带 resolved_model_id | `core/model_hub.py` L606-610（`_attach_resolution_metadata`） |
| 进程内 task_id 集合（非项目互斥） | `routes_chapter.py` L40-52 |
| generate_chapter_streaming 签名（已有 model 参数） | `streaming_service.py` L101-110 |
| 流式重试语义（max_retries=总尝试次数） | `streaming_service.py` L39/L50 |
| 后置提取模型取环境变量 | `unified_extraction.py` L65-71 |
| 摘要器无模型参数 | `agents/chapter_summarizer.py` L54（`create_task_llm()`） |
| 三段回退调用点 | `chapter_post_save.py` L294/L303/L312 |
| 三段回退方法签名（无 model 参数） | `entity_extraction.py` L96/L182；`location_hierarchy_extractor.py` L22 |
| 摘要后置入口 | `chapter_post_save.py` L416-430 |
| 多模型评审 gate | `app/services/agents/review_feature_gate.py` L57-89 |
| 生成端点鉴权与项目归属校验 | `routes_chapter.py` L524-575 |
| 模型准入门槛（flash 满足：1M/64K ≥ 120K/8K） | `app/api/v1/workflow/model_selection.py` L10-50 |
| Role/Permission 体系（权益数据源） | `app/models/role.py`；`User.roles`（`app/models/user.py` L36） |
| Redis 连接范式 | `app/services/cache_system.py` L96-116 |
| 前端调用点（需回归） | `WorkflowControlPage.tsx` L2471；`DashboardPage.tsx` L638 |
