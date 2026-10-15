# 多供应商视频生成 API 智能路由网关：落地指南（续作版）

> 状态：**已公网服务化（2026-10-14，W1–W6 全部完成）：文生与图/视/音多模态六类输入模式、API Key 鉴权与应用级限流、成片 OSS 永久转存（video.sggf.net）、容器化部署与真实 /health 探针均已上线；对外契约以 `docs/VIDEO_GATEWAY_API_INTEGRATION_GUIDE_20261014.md` 为准**。本文件仍是架构与施工事实基线：已实现的内容写"已落地"，未实现的写"待施工"，所有平台契约均标注实测日期。新对话应先读接入文档与本文件，再读对应源码，不信任文件之外的记忆。
>
> 代码根目录：`router_gateway/`；测试：`router_gateway/tests/`（pytest）；最近一次完整绿基线：**420 passed / 7 skipped**（2026-10-14；7 skipped 为默认关闭的付费云验收与真实 OSS 测试）。历史基线：172（模式改造后 10-12）→ 294（服务化前 10-13）→ 374（health/IP 修复）→ 420（商用鉴权限流后）。

---

## 1. 系统目标与边界

向下游提供统一的异步视频生成 API：下游提交一次生成请求，网关在多家转售供应商的同名底层模型（Seedance 2.5 / MiniMax-H3 / MiniMax-H3-LightX2V / 万相 Wan 3.0）与不同 ComfyUI 工作流之间，按"硬条件过滤 → 期望成本排序 → 故障切换 → 慢任务对冲"完成交付，对外隐藏供应商与凭证。

已定边界：

- **成功成片转存自有 OSS 后交付**（W4 已落地）：成片先转存 `sggf-router-video` 桶（华东2上海/标准存储/同城冗余/公共读），经 `https://video.sggf.net/...` 返回永久公共读直链；网关不代理视频字节，也不把上游临时签名地址暴露给下游。
- 不是聊天透传；视频是异步任务模型（提交 202 → 轮询 → 成片 URL）。
- 绝不为提高成功率而丢弃/降级用户素材、缩短时长、降低分辨率（硬条件 AND 语义）。
- 二次封装转售授权需在商业试运行前逐家取得书面依据。

## 2. 产品原则（已被代码锁定，不得回退）

1. **一个对外模型接口，多条内部路线**：`quality_group` 即对外模型；各路线能力可不同，按请求动态生成候选池。
2. **硬条件 AND**：输入模式、素材数量、时长、分辨率、画幅必须由同一条路线全部满足。
3. **区分"能力不支持"与"候选耗尽"**：无合格路线 → `unsupported_capability`（不扣费）；有路线但全失败 → `all_candidates_failed`。
4. **明确失败才切换；提交超时是"未知"不是失败**：幂等供应商同键重放一次，非幂等供应商记 `unknown` 并标双扣风险。
5. **慢于同档 P95 才对冲**：每任务最多 2 条并行尝试；**先通过验收的成片唯一交付**，晚到结果如实记账不覆盖、不误判。
6. **超截止时间停止等待**：活动尝试保留给后台对账，不伪造失败，防止漏费。
7. **可解释排序，不用 LLM 做路线选择**：排序是确定性算术（报价/有效成功率/质量系数），可复现、可审计。
8. **可复盘**：每个任务持久化决策快照、全部尝试、上游任务 ID、错误与费用（`decision_snapshots` / `attempts` / `route_events` 表）。

## 3. 代码地图（已落地）

| 模块 | 职责 | 关键类型/函数 |
|---|---|---|
| `catalog/__init__.py` | 能力目录与请求规格 | `Mode` 枚举、`Route`、`RouteCapability`、`VideoSpec`、`load_catalog()` |
| `catalog/intent.py` | 意图三级仲裁（已落地，20 测试） | `resolve_mode()`、`IntentClassifier`（Port）、`ModeDecision`、`ResolvedIntent`、`IntentError` |
| `catalog/routes.yaml` | 36 条路线台账（唯一事实源） | 见 §6 |
| `pricing/__init__.py` | 报价 | `PerSecond`（费率×请求时长）、`PerUse`（一口价）、Decimal |
| `router/__init__.py` | 硬条件过滤 + 排序 | `filter_candidates()`（含 mode、素材槽位、`quality_group` 同组过滤）、`rank_candidates()`、`RankedRoute`、`decide()` |
| `stats/__init__.py` | 滚动统计与熔断 | `RouteStats`（先验 0.95/强度 30；≥30 样本且失败率>20% 熔断） |
| `orchestrator/policy.py` | 纯函数策略 | 终态集合、`select_failover_route`、`select_hedge_route`（跨供应商优先）、`hedge_due`（attempt 是位置参数）、`deadline_remaining` |
| `orchestrator/service.py` | 编排状态机（已接意图仲裁与风险闸门） | `Orchestrator.submit_job()/poll_job()/get_view()`、`JobView`、五种 job 终态 semantic_error、`ContentRiskScorer`（Port）/`ContentRiskDecision` |
| `decision/__init__.py` | decision-model-preview 客户端（双 Port，g5a） | `DecisionModelClient.classify_mode()/score_risk()`、`DecisionModelError`；复用 `UrllibTransport`，零新依赖 |
| `decision/replay.py` | 离线回放探针（g5a，只出报告不接主路径） | `ReplayCase`、`evaluate_classifier()/evaluate_risk()`、门槛 `GATE_ACCURACY=0.95` |
| `assembly.py` | 组合根（g5a） | `build_gateway()`、`resolve_vendor_token()`、`Gateway`；env/token 文件 → 适配器+目录过滤+仓储+编排器 |
| `api/__init__.py` | HTTP 边界（g5 商用版） | `create_app()`、`POST /v1/videos`、`GET /v1/tasks/{id}`、免鉴权 `GET /health`、5 个内网 `GET /internal/*` 管理端点；入口 `python -m router_gateway.api` |
| `worker.py` | DB 驱动轮询 worker（g5a，可多实例） | `run_once()`、`run_forever()`；入口 `python -m router_gateway.worker` |
| `adapters/base.py` | 适配器契约 | `VideoAdapter` Protocol、`SubmitRequest/Result`、`NormalizedResult`、`AdapterError`、`UrllibTransport`、`RETRIABLE_HTTP_STATUS` |
| `adapters/{erchun,autodl,suanliai,grsai,sanbao}.py` | 五家归一化适配器 | 见 §5 |
| `assets/{oss_client,asset_store,provider_assets,delivery}.py` | OSS 成片转存与供应商素材登记 | 见 §9 |
| `db/__init__.py` | SQLAlchemy 2.0 仓储 | 表 `clients/jobs/attempts/route_events/decision_snapshots`，`JobRepository`（含 `list_active_job_ids()` 供 worker 查库） |

代码风格（新代码必须一致）：frozen dataclass、标准库 urllib（**不得给网关引入 httpx/requests**）、构造注入、相对导入、中文测试名与注释、金额一律 Decimal、无响应抛 `RetriableTransportError` 与有响应抛 `AdapterError(retriable, status)` 严格区分。

## 4. 状态机与对外失败语义（已落地）

- Job 状态：`pending / running / succeeded / failed`。
- Attempt 状态：`created / submitted / queued / running / succeeded / failed / unknown / superseded`。
- 终态：Job 终态 `{succeeded, failed}`；Attempt 终态 `{succeeded, failed, unknown, superseded}`；活动态 `{submitted, queued, running}`。
- 五种 job 终态 `semantic_error`：`unsupported_capability` / `all_candidates_failed` / `upstream_unknown` / `deadline_exceeded` / `content_risk_blocked`（提交前违规风险评分达阈前置拒绝，零 attempt）。成片内容校验失败不是 job 终态语义：按明确失败进入切换链，attempt 错误类型为 `content_unavailable`，切换链耗尽后 job 才终态 `all_candidates_failed`。
- 提交前意图非法（显式 `mode` 与素材结构矛盾等）在落库**之前**抛 `IntentError`，不建任务、不产生费用；g5a HTTP 层已落地，映射 **HTTP 422 / `invalid_intent`**；提交即终态的 `content_risk_blocked`/`unsupported_capability` 同样映射 422（固定中文文案，不回传上游细节）。
- `unknown` 不进成功率滚动窗口，避免超时误伤熔断。
- 幂等键：上游幂等键为 `{job_id}-{attempt_seq}`；同 `idempotency_key` 重复提交返回同一任务且零重复 attempt。
- 统计桶格式 `{mode}|{resolution}|{duration}s`（如 `text|720p|5s`、`multi_image|720p|5s`），文生与图生样本分桶；mode 在提交入口经意图仲裁后写入持久化 spec。
- `Orchestrator` 构造注入点共四个：`content_validator(url, raw)`、`on_job_terminal(job)` 回调（素材延迟 release 挂这里）、`intent_classifier` + `intent_confidence_threshold`（仅 2 图歧义用，缺省保守兜底）、`content_risk_scorer` + `content_risk_threshold=0.9`（缺省关闭，评分器任何故障 fail-open）。

## 5. 五家供应商契约台账（全部经真实付费任务实测）

### 5.1 贰春 erchun（Seedance 2.5，唯一支持幂等）

- Base `https://api.erchun.youkou.cc`；Bearer 鉴权 + **`Idempotency-Key` 请求头**；`supports_idempotent_submit=True`。
- 提交 `POST /v1/videos` → **202**；查询 `GET /v1/tasks/{id}`：`queued/in_progress/completed/failed`；成片 `GET /v1/tasks/{id}/content?delivery=stream`。
- 分辨率入参**大写**（`720P`），目录默认可能是 1080P，必须显式传。
- 失败任务 `billing_status=refunded`（自动退款），成功 `settled`；HTTP 402 = 余额不足，明确失败不重试。
- xuan 渠道 30s 被 422 拒绝 → 目录上限登记为 29s。

### 5.2 AutoDL（MiniMax-H3 / LightX2V 的 ComfyUI 工作流，无幂等）

- Base `https://autodl.art`；**裸 token，无 Bearer**；`supports_idempotent_submit=False`。
- 提交 `POST /api/v1/comfyui/comfyui_workflow/{workflow_id}`；轮询 `GET /api/v1/comfyui/comfyui_workflow/result/{task_id}`。
- 提交响应实测形态：`{"code":"Success","data":{"task_id","status":"QUEUED",...}}`；终态**大写** `SUCCESS`；成片在 `results` 中按 `type ∈ {mp4,mov,webm}` 提取，CDN 签名直链任意 UA 可下载。
- 分辨率提交中文枚举，且**工作流间不同**：z0901 用 `480p横(864*480)`、1080p 档实际映射 **`1088p横(1920*1088)`**；b99 系列 768p 档映射 **`736p横`**（实测输出 1280×736，低于标准 768p，note 已标注）；lightx2v 用 `480p横` 短枚举。映射表在 `adapters/autodl.py:_RESOLUTION_LABELS`，新增工作流必须先拉详情再补表。
- **计费只按"模型族×分辨率×秒"，与具体工作流无关**（2026-10-12 拉 `wf_details.json` 核实）：z 系 480p=40 分/秒、768p=70；b99 系 736p=50；lightx2v/zm 系 480p=30、768p=40。闲时 00:00-08:00 有折扣（报价器暂不支持分时，登记高峰价，note 记闲时价）。
- 已接入文生工作流：`minimax_h3_z0901`、`minimax_h3_b99_001`、`minimax_h3_lightx2v_no_pic`。另有 12 个素材类工作流**已拉到 input_rules/billing 但未接入**：首尾帧 `b99_002`/`lightx2v`；多图 `z0902`(六图)、`b99_003_12s`、`lightx2v_v5`(九图)、`lightx2v_v5_15s`；多图多音频 `z0903`、`zm_u08`、`zm_u24`、`image_audio_to_video_v2(_15s)`；对口型 `image_audio_to_video`（1 图+1 音频，audio_duration 1-15s）。素材槽位大量 `required=false` 且默认值为平台空白占位 `blank.png/blank.wav`（KS3 公网 URL）。

### 5.3 算力AI suanliai（new-api 风格转售，无幂等）

- Base `https://suanliai.top`；Bearer 鉴权；提交 `POST /v1/videos`；查询 `GET /v1/videos/{task_id}`（裸对象：`queued → in_progress → completed/failed`）。
- 时长大法**因模型而异**：sd2.5 系列提交字段 `seconds`；H3 系列用 `duration` 且**必须显式传 `aspect_ratio`**——pro 渠道不传时上游默认出竖屏（实测踩坑）。
- 成片 URL 多字段兜底：`url/video_url/download_url/result_url`，签名地址约 24h 有效。
- **交付层关键坑（2026-10-12 实测固化）**：`/content` 307 跳转 `media.suanliai.cc`，该域名套 Cloudflare 浏览器签名校验（**error 1010**）：Python-urllib/curl 默认 UA → **403**；浏览器 UA → 200 video/mp4。**worker 成片可达性校验与下游下载器必须覆盖浏览器 UA**，否则成功会被误判为 `content_unavailable` 触发无谓切换和二次扣费。集成测试含负向断言（默认 UA 必须 403，事实漂移即变红）。
- 平台按失败全额退款（ch3 首批失败退款已验证）。
- 模型即"渠道×模式×规格"的笛卡尔积，pricing.json 有 131 个视频模型、每个独立一口价（¥0.045~11.5）。模式编码写在名字里：`9-3-3`=9图3视频3音频、`30-10-10`=30图10视频10音频、`9-0-0`=9图、`30图`=30图；存在"不支持视频参考"等硬边界声明，**不得据名字推断跨模式兼容，必须实测**（见 §11）。

### 5.4 Grsai（MiniMax-H3，无幂等）

- Base `https://grsaiapi.com`；Bearer 鉴权；提交 `POST /v1/api/generate`；查询 `GET /v1/api/result?id={task_id}`。
- 请求体 `{"model","prompt","aspectRatio":"landscape|portrait","resolution":"480p|768p|1080p","duration":int,"replyType":"async"}`；`images`(≤9)/`audios`(≤3) 为可选素材字段（**已在平台前端 JS 确认，图生未实测**）。
- **提交响应为裸对象 `{"id","status":"running"}`（无 data 包裹，2026-10-12 真实云提交固定，适配器已收紧为严格契约）**；查询态 `running → succeeded/failed/violation`；成片永久 URL，任意 UA 可下载。
- 平台只保留约 2 小时结果：正常轮询窗口内的 404 视为可重试瞬时态。
- 实测真 1080p（输出 1920×1056）；1080p 上游时长上限 10s，故目录中 `grsai-h3` 与 `grsai-h3-1080` 拆两条路线。

### 5.5 三宝 sanbao（H3 2K / sd2.5 30图 / wan3 按次，无幂等）

- Base `https://sanbaobeauty.com`（装配默认值，env 可覆盖）；Bearer 鉴权（`X-API-Key` 亦可），`supports_idempotent_submit=False`；10 积分=¥1。
- 提交 `POST /openapi/v1/videos`，返回驼峰 `{"taskId": ...}`；查询 `GET /openapi/v1/videos/{taskId}`：`queued/preparing/processing` 为活动态，`succeeded` 成片取 `video_url/download_url`；`failed` 的 error 为字符串，平台失败自动全额退费。
- 全站对非浏览器 UA 不友好，适配器固定浏览器 UA；查询回显 `images` 恒为空（成功样例亦然），不得据此判失败。
- H3（`hailuo_h3_2k`）必须把图片**原生二进制上传**换 `host_url` 且提交带 `reference:"all"`，外链被拒；仅接受 1–2 张图（平台元数据标称 9 图系虚标，9 图被 400 拒，护栏触网前拦截）。
- sd2.5 / wan3 系列直接吃公网外链，提交体不带 `reference`；**任何模型都不接受参考视频**（三单实证安全拦截/测量失败）；素材总数上限按模型而异（sd2 档 12、wan3 按次档实证 15），由路线 `max_total_assets` + preflight 按路线拦截。
- 已登记 3 条路线：`sanbao-h3-2k`（真 2K 2560×1440，¥2/条，1-2 图）、`sanbao-sd25-30img-720`（30 图，36 积分=¥3.6/条，六种画幅）、`sanbao-wan3-once-480`（10 图 5 音，33 积分=¥3.3/条 5–30s 同价）。

### 5.6 通用 HTTP 语义（五适配器共用 base.py）

- 可安全重试状态：`{408,409,425,429,500,502,503,504}`；402/400 类明确拒绝不重试。
- 成功状态但无成片链接 → 按失败处理（驱动切换链）。
- 不支持的分辨率/比例组合在**发请求前**本地拦截（不花钱）。

## 6. 能力目录现状（routes.yaml，36 条，2026-10-14）

4 个对外模型组：`seedance-2.5`（10 条：贰春 3 + 算力AI 6 + 三宝 1）、`minimax-h3`（12 条：AutoDL 5 + 算力AI 4 + Grsai 2 + 三宝 1）、`minimax-h3-light`（3 条：均为 AutoDL，无跨源备份）、`wan3.0`（11 条：贰春 1 + 算力AI 9 + 三宝 1，2026-10-13 第 4 批起登记）。

每条路线字段：`route_id / provider / upstream_model / quality_group / billing(per_second|per_use) / duration{min_seconds,max_seconds} / resolutions[] / aspect_ratios[] / input_modes[] / max_images / max_videos / max_audios / pricing / enabled / note`。

实测价格、输出像素、耗时、官方成功率、踩坑全部写在各条 `note` 中（这是台账，改价必须连同实测证据一起改）。

## 7. 输入模式分层（六类模式 + 意图仲裁，已全部落地）

### 7.1 六类不可互换的模式（`catalog.Mode`，已落地枚举）

| Mode | 素材结构 | 典型上游 / 台账实证 |
|---|---|---|
| `text` | 无素材 | 全部文生工作流（多源多分辨率含 1080p/2K，付费实证充分） |
| `first_last_frame` | **恰好 2 图** | AutoDL b99_002（736p，D3 实证；单源单档） |
| `multi_image` | 1-N 图、无视频无音频 | 三宝 30 图、算力 V3/V5、AutoDL z0902 6 图/v5 9 图、三宝 H3 2K 1-2 图（T7/V3/V5/D1/D4/S1 系列实证） |
| `video_reference` | ≥1 视频、无音频 | **8 条声明路线全部付费实证（W7，2026-10-14）**：贰春 erchun-wan3 纯 1 视无图无音 task 81578（几何运动参考片轨迹复现）、图+视频无音频 task 81610（双采纳）；算力 suanliai 7 条 wan3（007-video/007-prime/std/1080/guanzhuan/guanzhuan-prime/prime-fast）各 1 单纯视频 7/7 completed、三帧目鉴轨迹复现。算力 480p 六单 854x480/30fps、1080 单 1920x1080/30fps，均含默认 AAC；注意算力 480p 档参考片按时长同单价另计（输出+参考时长） |
| `image_audio_lipsync` | 恰好 1 图 + 1 音频、无视频 | **台账零路线**：5 家均无已实证对口型供应档（z0903/zm_u24 的音频是叙事混轨/选择性融合，非透传复刻，对口型场景禁用）；是否找源见计划 D4 |
| `mixed_multimodal` | 图/视/音任意混合（≥1 素材） | wan3 10图3视3音（J14/J5/J3/J4/J6）、z0903 6图3音（D2）、10图5音 30s（J9b/J10/S3）、zm_u24 1图1音（Z2/Z3）均已付费实证 |

### 7.2 意图三级仲裁（catalog/intent.py，已实现+20 测试）

1. **显式 `mode` 入参优先**：但必须与素材结构一致，矛盾抛 `IntentError`（对外 4xx）。
2. **素材结构确定性规则**（与 `catalog/intent.py` 现行实现一致）：纯音频（无图无视频）直接非法；含音频时仅"恰好 1 图 1 音、无视频"→对口型，其余含音频组合（多图/多音/带视频）→ mixed_multimodal；无音频有视频 → 视频参考；无音频时 ≥3 图或 1 图→多图参考；无素材→文生。**1 图不判歧义**（三家均无"单首帧"工作流，已核实）。
3. **唯一歧义点=恰好 2 图**（首尾帧 vs 双图参考）：调可注入的 `IntentClassifier.classify_mode(prompt, image_count, candidates)`，返回 `ModeDecision(mode, confidence)`；置信度 ≥0.6 且结果在候选集内才采纳；分类器缺失/抛错/低置信/越界返回一律**保守按 multi_image**（槽位容得下 2 图，绝不丢素材）。非歧义请求绝不调用分类器。

### 7.3 AI 模型的使用边界（分工原则，必须遵守）

> **规则管结构、模型管歧义与风险、公式管排序、VLM 管成片验收。**

- `decision-model-preview` 类结构化决策模型（文本→离散类别+概率+置信度）只允许两个接入点：① 上述 2 图歧义仲裁（已落地，构造注入 `intent_classifier`）；② **提交前内容违规风险评分**（Grsai 有 `violation` 终态，违规任务失败且可能封 key）——**已落地为 `ContentRiskScorer` Port**（`orchestrator/service.py`，返回 `ContentRiskDecision(score, reason)`）：提交时在"候选非空"判定之后评分，分数 ≥ 阈值（默认 0.9，构造参数 `content_risk_threshold` 可配）前置拒绝，job 终态 `content_risk_blocked`、零 attempt、不调任何适配器；不注入 scorer 即功能关闭，评分器自身故障/返回畸形一律 **fail-open**（不阻断业务，有 4 条测试固化）。**真实模型已接入生产（2026-10-13，百炼业务空间专属域名，env `ROUTER_GATEWAY_DECISION_BASE_URL`，复用 DASHSCOPE_API_KEY）：2 图歧义分类实测准确率 100% 达标后才接主路径；风险评分维持 fail-open，不阻断主链路。**
- **禁止用 LLM 做路线选择/排序**：价格、成功率、P95 是数值问题，模型不可复现且引入延迟与故障点。
- **禁止用纯文本决策模型做成片质量校验**（看不了视频）。二轮质量评审接多模态 VLM；已有可用通路：火山 Ark `chat/completions` 支持 `video_url` 传 MP4 base64（探测脚本曾实测通过，AK 在 .env `VOLCENGINE_API_KEY`）。
- 所有模型接入均为构造注入 Port，默认 None；编排器不得硬依赖任何辅助模型。

### 7.4 兼容性去重策略（图生批次依据）

- 一条路线可在 `input_modes` 声明多个模式，对多类请求同时进入候选（已含测试），无需为每模式重复登记路线。
- **兼容只信实测，不信模型名/宣传**。高模式工作流传空素材能否安全降级为文生（AutoDL 素材槽自带 blank.png 默认值、算力AI 9-3-3 款价格仅为文生款的 1/13）需要实验验证，见 §11。
- 即使兼容成立，非标称用法先标 `degraded_mode: true`（yaml 扩展字段，待加）仅作故障切换备份，观察稳定性后再提为主力，防平台判定异常调用。

## 8. 路由排序公式（已落地）

`rank_candidates`：硬条件过滤 → 排除熔断路线 → `expected_cost = quote / max(effective_success_rate × max(quality_pass_rate,0.2), 1e-6)` 升序。样本不足时成功率向先验 0.95 收缩。对冲选路跨供应商优先（降同源故障），无跨源才同源。故障切换严格按 ranked 顺序取未用过的路线。

## 9. 素材托管与成片转存（已落地并真实云验收）

**对外 API 只收公网 HTTP(S) URL，网关不经手调用方素材的文件字节**（见接入文档 §6.3）。需要供应商侧素材凭证的路线（贰春/算力/三宝）在提交前由 `assets/provider_assets.py` 的统一 `RegisteredAsset` 登记层把公网 URL 换成供应商句柄：贰春 `POST /v2/media/uploads` multipart 换 `med_xxx`（24h 有效）、三宝裸二进制上传换 `host_url`、算力批量 review 后换引用；autodl/grsai 直接吃公网 URL。

**成片转存（W4）**：成功成片由 `assets/delivery.py` 下载转存到独立桶 `sggf-router-video`（env `ROUTER_GATEWAY_OSS_BUCKET` + `ROUTER_GATEWAY_OSS_PUBLIC_HOST=https://video.sggf.net`），转存期间任务保持 running、失败由后续轮询补偿；video.sggf.net 返回永久公共读直链，上游临时地址不对外暴露；已是自有域名（桶默认域/video.sggf.net）的地址不重复转存。

以下为 g-asset 本地素材换链组件（`AssetStore`）的历史探针事实，组件仍保留、当前 API 主链路不走字节上传：

- 复用既有阿里云 OSS 桶 `sggf-audio-library`（上海），配置在 `backend/.env` 的 `AUDIOBOOK_AUDIO_LIBRARY_OSS_*`；`OssConfig.from_env()` 优先读 `ROUTER_GATEWAY_OSS_*`，缺省回退音频库变量。**禁止把密钥写进代码或本文档。**
- **公共读按前缀授权（2026-10-12 探针实测）**：新顶层前缀匿名 403；只有 `shared/audio_library/` 之下匿名 200。素材 key 固定为 `shared/audio_library/router_refs/{UTC YYYY-MM-DD}/{job_id}/{sha256前12位}.{ext}`；公网域名 `https://audio.sggf.net`。
- 白名单扩展名 png/jpg/jpeg/webp/mp4/mov/mp3/wav/m4a；默认 100MB 上限；job_id 正则 `^[A-Za-z0-9_-]{1,64}$`；HEAD 命中且大小一致跳过上传；上传失败抛错不降级。
- 生命周期：任务终态由编排器 `on_job_terminal` 回调与 worker 提交租约释放路径调用 `AssetStore.release()` 删除云端暂存副本（本地原件不动）；供应商侧登记素材（如贰春 `med_xxx`，24h 有效）由供应商侧过期，无需我方删除。
- DashScope 临时 OSS policy（`getPolicy`）经验证不可用于第三方托管：钉死 private ACL、300 秒窗口、匿名 403。勿再尝试。
- 音频库扫描器只认固定子目录（sound_effects/music_cache/approved_sfx + 固定索引），平级新目录 `router_refs/` 不会污染索引。

## 10. 聚合渠道与官方刊例成本对照（2026-10-12 取价快照）

**统一口径**：文生视频、16:9、时长 5s、单条成功成片。聚合价取自 routes.yaml 实测登记（per_second = 元/秒 × 5，per_use 按条一口价）；官方价为 2026-10-12 当日官方文档刊例（来源见 §10.5）。两类价格都会变动，本表是决策快照，不是长期合同价。**2026-10-14 注：表内部分档位已变化（如贰春 xuan 720p 已下架、seedance 1080p 已有算力官转第二家、wan3.0 整组为后新增），最新在架路线与价格一律以 `routes.yaml` 为准。**

### 10.1 Seedance 2.5 vs 火山方舟官方

官方 `doubao-seedance-2.5` 按输出 token 计费（480p/720p 输入不含视频 70 元/百万 token，1080p 77 元；含视频输入 42/46 元），官方价格示例（5s 16:9，不含输入视频）：**480p ¥3.36（0.67/s）、720p ¥7.56（1.51/s）、1080p ¥18.71（3.74/s）**；官方承诺仅成功计费、审核失败免费。

| 档位(5s) | 官方价 | 目录最低聚合价 | 折扣 | 其余登记价（5s） |
|---|---|---|---|---|
| 480p | ¥3.36 | 贰春移动 ¥1.10（0.22/s） | **3.3 折** | 算力AI 007 ¥1.60（4.8 折）；贰春运营商按条 ¥6.00（短时长反贵 79%，仅长时长兜底） |
| 720p | ¥7.56 | 算力AI 007 ¥2.00（0.40/s） | **2.6 折** | 贰春 xuan ¥2.10、移动 ¥2.30；ch3 ¥4.25（5.6 折，观察中）；官转 ¥5.50（7.3 折，高可用兜底）；运营商按条 ¥12.00 |
| 1080p | ¥18.71 | 贰春移动 ¥4.20（0.84/s） | **2.2 折** | 目录内暂无第二家 sd2.5 1080p |

**按条档的非线性反转**：贰春运营商档 2-30s 同价（480p ¥6、720p ¥12），5s 时比官方贵约 60-80%；30s 时官方约 ¥20.1/¥45.3，按条档仅合 3.0/2.6 折。这是报价器按时长选档的价值来源，也是长时长任务的兜底路线。

### 10.2 MiniMax-H3 vs MiniMax 官方

官方国内刊例：H3 **768P ¥0.50/s、2K ¥0.80/s**（无 480P/1080P 档）；H3-Max **480P ¥0.33/s、768P ¥0.50/s**（仅 T2V/I2V，输入图暂不计费）。H3 输入素材：图片 5 张内免费、超出 ¥0.20/张；参考视频按输出分辨率同价按时长计（768P 0.50/s、2K 0.80/s）；音频免费。

| 聚合路线(5s) | 聚合价 | 官方对标(5s) | 折扣 | 实测备注 |
|---|---|---|---|---|
| AutoDL z0901 480p | ¥0.20（闲时 ¥0.15） | H3-Max 480P ¥1.65 | **1.2 折** | 输出 864×480 已验收 |
| AutoDL z0901 768p | ¥0.35（闲时 ¥0.25） | H3 768P ¥2.50 | **1.4 折（约 1/7）** | 1376×768 档未出片实测 |
| AutoDL z0901 上游 1440p | ¥0.40（闲时 ¥0.30） | H3 2K ¥4.00 | **1.0 折（约 1/10）** | 上游计费档存在（80 分/秒），目录当前未对外登记 |
| AutoDL b99 736p | ¥0.25（闲时 ¥0.15） | H3 768P ¥2.50 | 1.0 折 | ⚠️ 实出 1280×736 规格缩水，折扣不可与满血档等同 |
| 算力AI 933/特价/pro/933b 768p | ¥0.425/0.45/0.55/0.60 | ¥2.50 | 1.7~2.4 折 | 输出 1376×768；pro 缺省出竖屏需显式横屏 |
| Grsai 480p | ¥0.50 | H3-Max ¥1.65 | 3.0 折 | 输出 864×480 |
| Grsai 768p | ¥0.70 | H3 768P ¥2.50 | 2.8 折 | 输出 1344×768 |
| Grsai 1080p | ¥1.50 | 官方无此档 | 介于 768P 与 2K 之间 | 1920×1056 为真 1080p |
| AutoDL lightx2v 480p | ¥0.15（闲时 ¥0.10） | **不可比价** | — | LightX2V 轻量变体，独立 quality_group，严禁当满血 H3 |

H3 聚合常态 1-3 折，比 sd2.5（2-5 折）更极端；AutoDL 闲时（00:00-08:00）再低约 25-40%，但当前报价器不支持分时（routes.yaml 仅登记高峰价，闲时价在 note）。

### 10.3 标价之外的代价（未决项）

1. **同名 ≠ 同质，是最大不确定性**：算力AI 模型名黑话（满血全参/官转/卡真人/原生过脸/无限并发）暗示渠道间存在降配、第三方自部署或量化版本差异。已实测劣化：b99 标 768p 实出 1280×736、算力AI 两条标 1080p 实降 768p、ch3 首测失败。至今**没有同提示词跨渠道画面对照评测**，低价路线长期当主力前必须有质量抽检数据支撑。
2. **失败计费口径不对称**：官方白纸黑字仅成功计费；聚合侧只证实贰春、算力AI 失败退款，AutoDL 与 Grsai（含 violation 违规终态）失败是否扣费未实测（见 §14 第 4 项）。
3. **供给与时效风险**：渠道可能随时调价、断供、封 key；共享 GPU 排队隐含时延波动（AutoDL H3 实测推理 87-318s，无官方同档耗时对照，不能下结论）；官方有原厂 SLA 与配额保障。
4. **图生价差结构可能更大但未证实**：官方 H3 超 5 图 ¥0.20/张、参考视频 0.50/s 另计；AutoDL 计费配置表明示工作流只按"模型族×分辨率×秒"一口价、与素材数量无关，但未经多图真实任务验证——待 §11 实验 2/3 证实，证实前不得按此报价。

### 10.4 对路由与对外定价的含义

- sd2.5 主力选贰春移动/算力AI 007（2-3 折），H3 主力选 AutoDL z0901（1-2 折）；算力AI 官转、贰春按条档分别作为高可用与长时长兜底。
- 建议持有火山/MiniMax **官方 key 作为终极备份路线**（高价高可用，聚合全断时保命），当前不接入目录、不参与常态排序。
- 期望成本必须含成功率与质量折算（§8 公式已做）：低折扣叠加低成功率会侵蚀优势，对冲双扣进一步收窄；上线后用滚动 stats 复盘，不以本静态快照一锤定音。
- 对客可锚定官方刊例定价（如 H3 768P 按 ¥0.50/s 对客），内部常态成本约 ¥0.07/s，理论毛利 80%+，用于吸收对冲双扣、失败退款与偶发官方兜底损耗。

### 10.5 价格来源

- 火山方舟《模型价格》：https://docs.volcengine.com/docs/82379/1544106 （页面更新 2026-09-28，2026-10-12 抓取；token 公式与时点示例以官方价格计算器为准）
- MiniMax 开放平台《按量计费》：https://platform.minimaxi.com/docs/guides/pricing-paygo （2026-10-12 抓取）
- 聚合价：`router_gateway/catalog/routes.yaml`（全部经真实付费扣费流水或平台计费配置核实，取价日期 2026-10-12）

## 11. 图生兼容性实验计划（历史计划，多数已完成）

> **执行状态（2026-10-14）**：实验 2（lightx2v_v5 九图，D4 实证已登记）、实验 3（b99_002 首尾帧，D3 实证已登记）已完成；其后第 3–6 批完成了远超本表范围的多供应商 i2v / 多模态实证（30 图、wan3 全槽位、H3 2K、zm_u24 音频槽等，见 routes.yaml note 与 I2V 横评交接文档）。**仍未做**：实验 1（Grsai 图生）、实验 5（贰春快乐马付费实证，零成本 422 活性已探到）；实验 4 已被后续 9-3-3 档位实测覆盖。下表保留为历史计划。

全部走 AssetStore 公网 URL，顺带验收素材链路：

| # | 实验 | 预估成本 | 验证假设 |
|---|---|---|---|
| 1 | Grsai 传 1 张真实图走 multi_image 480p×5s | ¥0.50 | 单接口多模式正向可用 |
| 2 | AutoDL `lightx2v_v5`（九图工作流）传 blank.png 占位 vs `lightx2v_no_pic` 各一条 480p×5s | ¥0.60 | 空位降级是否等价文生、有无黑帧 |
| 3 | AutoDL `b99_002` 首尾帧传 2 张真实图 736p×5s | ¥0.50 | first_last_frame 正向 |
| 4 | 算力AI `minimax_h3-768p(9-3-3)`（¥0.12）空素材提交 | ¥0/¥0.12 | 422=不支持（不扣费）；接受则再花 ¥0.12 对比文生质量 |
| 5 | 贰春带图提交 | ¥0 | 422 即止，探测转售层是否放行图生 |

另：规格边界补测菜单（竖屏/1:1/时长上下限，约 ¥8）见历史对话，可与图生批次合并。429/violation/取消等异常态无法靠充值触发，不安排付费硬造。

## 12. 当前施工状态与下一轮精确任务单

### 12.1 模式改造已完成（2026-10-12，全量 172 passed / 5 skipped）

五类输入模式改造（意图仲裁 → 模式过滤 → mode 分桶 → 风险闸门）已按 §12.2 六步 TDD 全部落地：

- ✅ `catalog/__init__.py`：`Mode` + `RouteCapability.input_modes/max_*`（旧 `ReferenceCapability` 已全仓删除，grep 零残留）；`VideoSpec` 含 `mode/reference_audios`；yaml 解析读 `input_modes/max_images/max_videos/max_audios`（缺省 `[text]`/0）。
- ✅ `catalog/intent.py`：意图三级仲裁，`tests/test_intent_resolver.py` 20 passed。
- ✅ `router/__init__.py`：`filter_candidates` 按 `req.mode in cap.input_modes` + 图/视频/音频计数 ≤ `max_*` 过滤；`test_router_decision.py` 12 passed（含多模式一路线、槽位上限、17 条目录断言）。
- ✅ `catalog/routes.yaml`：17 条路线全部显式 `input_modes: [text]`（本批全是文生，图生路线待 §12.4 登记）。
- ✅ `orchestrator/service.py`：提交入口先 `resolve_mode` 并把 mode 写入持久化 spec；`IntentError` 落库前抛出（g5 映射 422/`invalid_intent`）；`_bucket` = `{mode}|{resolution}|{duration}s`；`ContentRiskScorer` 闸门已落地；编排测试 40 passed（policy 16 + service 25 含意图 3/风险 4 + 真实 PG 3）。
- 全量基线：`python -m pytest router_gateway/tests/ -q` → **172 passed / 5 skipped**（5 skipped 为付费云验收 3 + 真实 OSS 2，默认关闭）。

### 12.2 模式改造任务单（六步，已全部完成，留档）

1. ✅ `router.filter_candidates`：`req.mode in cap.input_modes` AND 素材计数 ≤ 路线 max_*。
2. ✅ routes.yaml 17 条 `reference:{...}` → `input_modes: [text]`。
3. ✅ 三个 orchestrator 测试去 `ReferenceCapability`：policy/db 用 `{Mode.TEXT}`；service 默认 cap 用 `{TEXT, MULTI_IMAGE}` + `max_images=2`（单图透传用例，前向兼容仲裁）。
4. ✅ service 接 `resolve_mode`（分类器/阈值构造注入）；mode 持久化；桶带 mode；db 测试三处桶字符串同步为 `text|720p|5s`。
5. ✅ `ContentRiskScorer` Port：高分（≥0.9）阻断 `content_risk_blocked`、零适配器调用；低分放行；评分器故障 fail-open；未配置不阻断。
6. ✅ 全量回绿 172 passed / 5 skipped；GetDiagnostics 零诊断；cleanup 脚本每步清理。

### 12.3 g5：统一对外 API + 后台 worker（g5a 已完成，2026-06，全量 208 passed / 7 skipped）

**已交付（g5a，六个 TDD 任务）**：

1. ✅ 装配工厂 `assembly.py`：`build_gateway()` 按 env `ROUTER_GATEWAY_{VENDOR}_TOKEN` → `%LOCALAPPDATA%/Temp/{vendor}_token.txt` 顺序取凭证；只有拿到凭证的供应商才构造适配器，目录中其余路线同步剔除（不承诺无适配器的路线）；决策模型双配置齐全时同一 `DecisionModelClient` 同时注入意图分类与风险评分两个 Port。
2. ✅ 最小 HTTP 边界 `api/`（FastAPI + Pydantic，10 测试）：
   - `POST /v1/videos` → **202** + `Location: /v1/tasks/{id}`；幂等键 `Idempotency-Key` 请求头，客户端身份 `X-Client-Key`（缺省 `default`）。
   - g5a 请求体仅文生字段：`model(quality_group)、prompt、duration_seconds、resolution、aspect_ratio、allow_switch、allow_hedge、deadline_seconds`；图生素材数组随 g5b 开放。
   - `GET /v1/tasks/{id}` → 统一状态 `accepted/running/succeeded/failed/unsupported`；内部五语义放 `error.code`，成片以 `content_url` 返回；响应不含 attempt、上游 task_id、供应商名。
   - `IntentError → 422 invalid_intent`；提交即终态的风险阻断/能力不支持 → 422 `content_risk_blocked`/`unsupported_capability`；其余即时失败 → 502 脱敏通用码；未知任务 → 404。错误文案固定中文，任何上游 URL/key/原始 error 不外泄（有脱敏测试）。
   - 新增只读 `Orchestrator.get_view()`（不查上游、不推进状态机）供 GET 使用。
3. ✅ DB 驱动 worker `worker.py`（4 测试）：每 tick 重新 `list_active_job_ids(limit=20)` → 逐个 `poll_job`；单任务异常只记日志不炸循环；空批 idle 5s、有任务 busy 1s（均可注入）；无内存调度表，可多实例水平扩容。
4. ✅ decision-model-preview 客户端 `decision/__init__.py`（6 测试）：POST `{base_url}/v1/systemone` + Bearer（复用 `DASHSCOPE_API_KEY`）；`classify_mode()` 走 `intent_mode` choice 题、`score_risk()` 走 `content_risk` noul 题；HTTP 非 200/缺字段抛 `DecisionModelError`，传输异常原样传播；复用 `UrllibTransport`，零新依赖。
5. ✅ 离线回放探针 `decision/replay.py`（4 单测 + 2 真云测试默认 skip）：标注样本 → 准确率/逐项明细报告，门槛 **0.95**，异常样本计错但不中断；探针不接主路径。开启：`$env:ROUTER_GATEWAY_RUN_DECISION_PROBE="1"` + `ROUTER_GATEWAY_DECISION_BASE_URL`（`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode`）+ `DASHSCOPE_API_KEY`。**上生产前必须人工跑探针并确认 threshold_passed=True**，否则装配时留空决策配置，系统维持 resolve_mode 保守回退（2 图 → multi_image）与无风险闸门状态。
6. ✅ 顺带补齐缺口：`VideoSpec.quality_group` 硬过滤（指定 `model` 时只走同质量组路线，防止 h3/sd2.5 串档，2 测试）；`JobRepository.list_active_job_ids()`（2 测试）。
- 入口：`python -m router_gateway.api`（默认 127.0.0.1:8088，env 可覆盖）、`python -m router_gateway.worker`；配置项见根目录 `.env.example`「视频智能路由网关」段。
- 全量基线：`python -m pytest router_gateway/tests/ -q` → **208 passed / 7 skipped**（新增 2 skip 为决策模型真云回放；其余 5 skip 为付费云 3 + 真实 OSS 2）。

**g5a 明确不做（留给后续批次）**：

- `reference_images[]/videos[]/audios[]` 请求字段与 AssetStore 句柄 → g5b/图生（§12.4）；
- worker 承载素材终态 1h release（依赖图生 staged asset 记录）→ g5b；
- `max_cost` 单任务成本上限、Key 校验、模型白名单、QPS/并发限速 → g9（§12.5）；
- 算力AI 成片链接浏览器 UA 的交付说明字段，随图生批次一起处理。

### 12.4 图生批次（已完成，2026-10-12～10-14 第 1–6 批）

§11 实验执行后已按结果在 routes.yaml 登记 6 类模式路线（现 36 条），适配器补齐素材字段（AutoDL 各工作流 body 形态按 wf_details 实测映射；Grsai 图生仍未测；算力AI 模式按模型名映射）；submit 前的素材准备实际走 `assets/provider_assets.py` 统一登记层（公网 URL → 供应商句柄），不经 API 层本地上传。付费实证详见各路线 note 与 I2V 横评交接文档。

### 12.5 g9：客户端鉴权与限速（已落地，2026-10-14，随 g5 商用版部署）

已实现：Bearer API Key 校验（平台只存哈希+前缀，可吊销/轮换）、应用级 Redis 令牌桶（速率+突发）、活动任务并发上限（超限 429）、同键不同体 409、限流依赖故障 503 fail-closed、5 个内网 Token 保护的 `GET /internal/*` 管理端点（配额/路由快照/供应商配置状态等）、错误清洗（不泄漏上游 URL/Key/内部细节）；主站侧申请/审批/配额/监控在 backend `app/api/v1/video_api.py`。**仍未做**：模型白名单、单任务 `max_cost` 硬过滤、调用方余额扣费（D3 维持按 client 记账不扣费）。

## 13. 环境、凭证与运行事实

- PostgreSQL：docker 容器 `novel_postgres`，库 `postgresql://novel_user:***@127.0.0.1:5432/router_gateway`（密码见 `tests/test_orchestrator_db.py` 与 backend 配置，勿外泄）；db 集成测试每例 drop/create_all，直连可用。
- 五家 token：`%LOCALAPPDATA%/Temp/{erchun,autodl,suanliai,grsai,sanbao}_token.txt`（贰春另有 erchun_key.txt）；生产只走 `ROUTER_GATEWAY_*_TOKEN` 环境变量。
- 平台原始实测档案（只读证据，勿删勿提交）：`%LOCALAPPDATA%/Temp/router_sd25/`（贰春 24 任务 metrics）、`router_autodl/`（6 任务 + wf_details.json + index.js）、`router_suanliai/`（models.json 525 模型 / pricing.json 542 条 / collected_results）、`router_grsai/`（gr_results + index.html）。
- 测试命令（PowerShell，仓库根执行）：
  - 全量：`python -m pytest router_gateway/tests/ -q`
  - 真实云供应商验收（付费）：`$env:ROUTER_GATEWAY_RUN_PROVIDER_INTEGRATION="1"; python -m pytest router_gateway/tests/test_adapters_provider_integration.py -q -s`（默认 skip；含 AutoDL/算力AI/Grsai 各 1 条最低档，约 ¥2.3）
  - 真实 OSS：`$env:ROUTER_GATEWAY_RUN_OSS_INTEGRATION="1"`（默认 skip）
  - 决策模型真云回放探针：`$env:ROUTER_GATEWAY_RUN_DECISION_PROBE="1"` + `ROUTER_GATEWAY_DECISION_BASE_URL` + `DASHSCOPE_API_KEY`，`python -m pytest router_gateway/tests/test_decision_replay_probe_integration.py -q -s`（默认 skip）
  - 真实 PG 测试无需开关，本机 docker 起着即跑。
- 进程入口（配置项见根目录 `.env.example`）：`python -m router_gateway.api`（HTTP，默认 127.0.0.1:8088）；`python -m router_gateway.worker`（DB 驱动轮询，可起多实例）。
- pytest marker `integration` 已在 `tests/conftest.py` 注册。

## 14. 覆盖矩阵：已测 vs 未测（不夸大）

已测：五家文生 44 条早期真实任务 + 3 条端到端云验收（2026-10-12）；图生/多模态第 1–6 批付费实证（D1–D4、J3–J14、S1/S3、T1–T7、V1–V6、Z1–Z3 等，见 routes.yaml 各 note 与 I2V 横评交接文档）；W5 本机真实 E2E（含 worker 重启零重复派发）、W6 容器化公网验收（有效 key 真实付费全链路 job 149195bf，成片转存 OSS 永久地址）；本地模拟容量测试 4372 请求（2026-10-14，报告 `VIDEO_GATEWAY_LOADTEST_20261014.md`，非生产容量验收）；适配器契约单测全部用录制真实响应驱动；编排器（内存假仓储 + 纯策略 + 真实 PG）；素材 OSS 签名固化向量与真实云 2 例。

**未测（不得声称支持）**：
1. ~~全部图生/首尾帧/多图~~（已有充分付费实证）；~~纯 video_reference 组合~~（**W7 已补：贰春 wan3 纯视频 task 81578 + 图+视频 task 81610；算力 7 条 wan3 路线纯视频 7/7 付费 completed 轨迹复现，2026-10-14**）；~~贰春快乐马付费实证~~（**W8 已补：快乐马 1.1 单图 i2v task 82115，480P/5s settled/47s，紫牌强采纳，实扣 ¥1.45，2026-10-14**）；**仍未测：image_audio_lipsync（台账零路线）；Grsai 图生（W8 单图付费单卡 running/15% 53 分钟挂起判失败，grsai-h3 维持 text-only，无成功实证，适配器透传已就绪待复探）**；
2. 竖屏与 1:1、4:3、3:4、21:9 真实出片（枚举来自工作流详情 API，绝大多数成片为 16:9）；
3. 时长边界（多数档位仅 5s；30s 仅有 wan3 按次档与 sd25 按条档实证；z 系 1s、AutoDL 15s 上界等例外）；
4. 429/5xx 真实限流、violation、取消（仅 HTTP 契约固化与本地模拟压测）；
5. 真实跨平台故障切换/对冲演练（目前只在假适配器+真实 PG 上验证）；
6. AutoDL 闲时价（需 00:00-08:00）；
7. ~~贰春图生~~（v2 素材上传与 wan3/移动 sd25 多路线已实证）；~~贰春快乐马 1.1 付费实证~~（W8 已闭环并登记 erchun-happyhorse-1-1：v2 上传换 media_id → v1 提交，480P/5s/¥1.45 按条，单图强采纳；720/1080p 与其余 8 种比例未实测不开放）；
8. ~~decision-model-preview 真云回放/接入~~（2026-10-13 已接入生产，2 图歧义分类准确率 100% 达标；风险评分 fail-open）；
9. ~~HTTP API/worker 真实起服联调~~（W5/W6 已做真实 uvicorn + worker E2E 与公网验收；多实例 worker 生产并发演练、staging 同版本容量验证仍未做）。

## 商用调用方隔离与运营入口

视频路由对外按 API 应用隔离。每个应用拥有独立 Key、请求速率、突发容量、活动任务上限和单任务最大并行尝试数；`allow_hedge` 不能绕过这些限制。新申请为 pending，经超级管理员批准后启用。二次封装平台应在自己的入口排队或按租户申请额度，不能依赖单个 Key 无限扩容。多个应用仍需要逐一审批，当前没有主站用户全部应用共享额度。

主站用户中心负责申请和管理应用，超级管理员专属入口负责状态、配额和聚合运营指标。内部管理接口只允许主站通过内网 Token 访问，禁止在公网暴露；监控只返回聚合成功率、延迟、任务数和成本，不返回供应商凭据、完整 API Key 或原始 Prompt。

商用鉴权、限流与内部管理功能随 2026-10-14 g5 商用版镜像部署生产（部署前置：生产 `.env` 必须配置 `ROUTER_GATEWAY_INTERNAL_TOKEN`，main() 在 `APP_ENV=production/staging` 下无 token 拒绝启动）。监控的供应商状态为凭据配置状态，路由健康仍需真实结果证据；成本只汇总已记录账单，缺失部分显示未知。日/月预算和次数字段尚未硬拦截，API 应用权限不等价于充值余额或计费授权。

## 15. 工程纪律（每轮必守）

2026-10-14 补充：成片视觉质量只做后台内部抽评，不作为交付闸门；同一目录模型质量组每 10 个成功成片抽评 1 个，计数持久化并跨供应商累计，评分归属实际路线。默认 `qwen3.8-omni-flash`，评价失败和低分均不改变已交付任务，不向普通用户输出评分或证据。实现、配置及待部署步骤见 [生产化方案：后台视觉质量抽评](VIDEO_GATEWAY_PRODUCTIONIZATION_PLAN_20261013.md#后台视觉质量抽评2026-10-14代码已接入待部署启用)。

- **讨论与修改分离**：先诊断/方案并获用户明确同意，再改代码；只读探测不受限。
- **TDD 红绿**：先写失败测试并亲眼看它因正确原因失败，再最小实现；新增功能无例外。
- 简体中文；frozen dataclass + 标准库 + 构造注入；变更范围最小，不做无关重构，不主动建 md 文件（本文件除外）。
- PowerShell 5：禁 `&&`、禁 Linux 命令；here-string `@'...'@ | python -` 跑一次性探测；探测脚本放 `%LOCALAPPDATA%/Temp` 用完即删。
- 危险操作（付费 API 调用、删除、Git 写操作、全局装依赖、DB 批量变更）必须用项目规定的确认格式获得明确"是/确认/继续"。未经要求不 commit/push。
- 任务完成跑 cleanup 脚本；用户剧本、正式音频库、OSS 资源、DB 业务数据绝不清理。
- 成本敏感：任何会真实扣费的实验先报预算与风险再执行；能用已付费任务的 24h 签名 URL 零成本复验的，不重复花钱。
