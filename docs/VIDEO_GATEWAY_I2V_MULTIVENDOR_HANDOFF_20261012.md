# 视频网关图生视频（i2v/参考素材）多供应商横评结论与接线交接

> ⚠️ **现状指引（2026-10-14）**：本文开头"横评完成，接线未开始"的状态**已过时**——6 批接线已全部完成：5 家适配器（新增三宝）、37 条路线、六类输入模式均已随网关公网服务化（W1–W6）上线。最新对外契约读 [VIDEO_GATEWAY_API_INTEGRATION_GUIDE_20261014.md](VIDEO_GATEWAY_API_INTEGRATION_GUIDE_20261014.md)，架构与覆盖现状读 [VIDEO_API_SMART_ROUTING_GUIDE.md](VIDEO_API_SMART_ROUTING_GUIDE.md)，在架状态以 `router_gateway/catalog/routes.yaml` 为唯一事实源。**本文以下正文仅作 2026-10-11～10-12 付费实测证据档案保留**（结论、价格、耗时、暗坑仍可追溯引用），其中"未接线/待施工"类表述一律不再代表现状；纯 video_reference 付费实证已全部闭环（贰春 wan3 task 81578/81610、算力 7 条 wan3 7/7 completed 轨迹目鉴复现，均为 2026-10-14 W7）；**W8（2026-10-14）快乐马 1.1 单图 i2v 付费实证已闭环并登记 `erchun-happyhorse-1-1`（task 82115，480P/5s settled/47s，实扣 ¥1.45，较本文 J11/J13 横评期 ¥1.00 已涨价，以 W8 为准，紫牌强采纳）**；**Grsai 图生 W8 付费单 11-9576 卡 running/15% 53 分钟挂起判失败，grsai-h3 维持 text-only 不开放 i2v**（适配器单图 public_url 透传已 TDD 就绪，待日后上游稳定复探；Grsai 无余额/取消接口，该单扣费情况以后台账单为准）。
>
> 状态：**横评完成，接线未开始（等用户在新对话中发令）**。本文是 2026-10-11～10-12 两轮真实付费测试（窗口 J/K/L/M/S）的持久事实基线，所有结论均有成片、ffprobe、抽帧联系表与余额对账支撑。新对话应先读本文，再读 `docs/VIDEO_API_SMART_ROUTING_GUIDE.md`（文生视频主线，已上线）与 `router_gateway/` 源码，**不信任本文与源码之外的记忆**。
>
> 代码根目录：`router_gateway/`；测试：`router_gateway/tests/`（pytest）。
> 最近一次绿基线：274 passed / 7 skipped（2026-10-13，router_gateway 全量；第 3 批三家适配器 +29 后；7 个 skip 均为默认跳过的真实付费云验收）。

---

## 0. 新对话开工步骤

1. 读本文件全文；再读 `docs/VIDEO_API_SMART_ROUTING_GUIDE.md` 了解已上线的文生（t2v）主线。
2. 按项目规则先读 skill：`.agent/skills/backend-dev-guidelines/SKILL.md` 与 `.agent/skills/test-driven-development/SKILL.md`。
3. 阅读 `router_gateway/adapters/base.py`、`adapters/erchun.py`、`catalog/routes.yaml`、`assets/asset_store.py` 现状。
4. 从本文 §6 的**第 1 批（契约扩展）**开始，严格 TDD；每批完成后向用户汇报再继续下一批。
5. 全程遵守"讨论与修改分离"：动适配器 / routes.yaml 前先给方案，获明确同意再改。

## 1. 总目标与硬规则

总目标（用户原话）：**"尽量在各家挑选出最优组合，价格优惠、生成速度快、稳定性高、有失败备份"**。网关按"硬条件过滤 → 成本排序 → 故障切换 → 慢任务对冲"选路，本轮补齐的是**图生视频 / 参考素材（图片、参考视频、参考音频）**方向。

测试与选路硬规则：

- **5 秒档成片耗时 > 900s（15 分钟）直接淘汰**。
- **30 秒长档只测按条计费（PerUse）的路线**，且必须真实拉满 30 秒；按秒计费的长档不测。30s 档没有单独的耗时淘汰线（900s 规则字面上只用于 5s 档），但实测 894s 的三宝 S3 已属明显偏慢，排序时按期望耗时自然靠后。
- 所有横评使用同一套素材（橘猫窗台场景）、同一提示词、16:9，保证横向可比。
- 绝不为提高成功率丢弃/降级用户素材、缩短时长、降低分辨率（硬条件 AND 语义，沿用主线原则）。
- 密钥**只走环境变量或 token 文件，禁止落盘仓库、禁止写进本文**。
- 测试费用真实产生；供应商"创建即冻结、失败自动退款"的规则以本文各平台小节实测结论为准。

## 2. 已上线现状（不要重复施工）

文生视频主线已端到端打通：AutoDL（MiniMax-H3 t2v 低价档）、贰春（Seedance2.5 移动档等 t2v）、grsai、suanliai 四家适配器存在；`routes.yaml` 现有 17 条路线均为 t2v。

**本文涉及的 i2v / 长档路线全部尚未接线**，三家现状：

| 平台 | 适配器文件 | i2v 现状 |
|---|---|---|
| 贰春 erchun | `adapters/erchun.py`（仅 v1 t2v） | 缺 v2 素材上传；快乐马1.1、Wan3.0 i2v 未接线 |
| 算力 suanliai | `adapters/suanliai.py`（t2v） | 缺素材 review 转存；wan3 五档 + 004 两长档未接线 |
| 三宝 sanbao | **不存在，需新建** | 全新平台，契约与暗坑见 §4.3 |

## 3. 横评结论速查（全部真实付费实测）

### 3.1 5 秒档排名

**极速 / 低价 i2v（主力区）**

| 排名 | 平台·档位 | 单价 | 实测耗时（多样本） | 规格 | 素材能力 |
|---|---|---|---|---|---|
| 极速① | 贰春 快乐马1.1 | ¥1.00/条 | **48s / 61s**（J11/J13） | 848×480 @24fps，aac 有声 | 单图 i2v（r2v） |
| 低价① | **贰春 Wan3.0 i2v** | **¥0.79/条** | 268s（J14）/ 249s（M14） | 854×480 @30fps，有声 | **10图+3参考视频+3音频全槽位** |
| ② | 算力 wan3 官转多参 | ¥1.15/条 | 804s（J3 高峰）/ **336s（M3）** | 854×480 @30fps，有声 | 全槽位 |
| ② | 算力 wan3 prime 官转 | ¥1.20/条 | 795s / **232s（M4）** | 同上 | 全槽位 |
| ② | 算力 wan3 标准版 | ¥1.75/条 | 785s / 322s | 同上 | 全槽位 |
| ② | 算力 wan3 prime 高速版 | ¥2.25/条 | 779s / 237s | 同上 | 全槽位；非高峰仅快约 100s，**溢价不值** |
| ② | 算力 特价 wan3-480p | ¥1.75/条 | 769s / 323s | 同上 | 全槽位；目鉴动作最生动 |
| 备份 | simplefuture H3-768p | ¥1.5/条 | 670s | 768p | 外链拉取偶发 Cloudflare 524 |

关键结论：算力第一轮 5 档全部贴近 900s 淘汰线是**高峰排队**所致，非高峰常态 232–336s；高峰/非高峰差 2.4–3.4 倍，因此必须保留贰春与算力**跨供应商互备**。

**极致画质区**

| 排名 | 平台·档位 | 单价 | 耗时 | 规格 | 限制 |
|---|---|---|---|---|---|
| ① | **三宝 Hailuo-H3-2K** | ¥2.0/条 | 300s（1图）/517s（2图） | **2560×1440 真 2K** @24fps，有声 | 实测仅收 1–2 图，须原生上传，见 §4.3 |
| ② | simplefuture H3-768p | ¥1.5/条 | 670s | 768p | — |
| ③ | grsai H3 480/768p | ¥0.50–0.70/条 | 123–190s | 480/768p | t2v 已接线；永久 URL，最稳 |

目鉴：三宝 2K 为全部样本画质最佳（毛发、逆光轮廓、扑蝶/潜行动作自然）。

### 3.2 30 秒长档排名（均拉满 30 秒）

| 排名 | 平台·档位 | 单价（折合每秒） | 耗时 | 素材 |
|---|---|---|---|---|
| ① | **算力 004系列/wan3.0-video（J9b）** | **¥2.95/条（¥0.098/s）** | 611s | 需**去掉参考视频**，图片+音频可用 |
| ② | 算力 004系列/wan3.0-vedio 优质10图5音（J10） | ¥3.2/条 | 762s | 10图5音（注意平台原名 "vedio" 拼写） |
| ③ | 三宝 wan3.0-按次-480P（S3） | ¥3.3/条（¥0.11/s） | 894s（明显偏慢） | 10图+5音频，多场景叙事角色一致 |
| 兜底 | 贰春运营商 Seedance2.5 | ¥6–12/条 | 929s | 已在 t2v 台账，长档仅兜底 |
| ✗ 黑名单 | 三宝 sd2.5 满血 30s（¥8.5） | — | 两单全败（参考视频无法测量 / 纯图提交超时） | 不稳定，不接线 |

### 3.3 平台定性

- **贰春**：速度+成本王，全槽位可用；契约绕（v2 上传 + v1 提交，见 §4.1）。i2v 主力。
- **算力 AI**：全槽位最稳、长档王、跨源备份；高峰排队明显，prime/高速溢价不划算。
- **三宝**：独家真 2K 画质，退款最干脆（本轮 10 个失败单全部自动全额退费，余额 1000→899.5 与实花 ¥10.05 分毫不差）；但**参考视频链路全灭**、存在虚标槽位与僵尸档，只适合做高画质/纯图特色档。
- **simplefuture**：中段备份；只收公网 URL，站方同步拉取 6.5MB 参考视频会触发 Cloudflare 524；其 Cloudflare 对 urllib 全站 Error 1010，自动化侦察困难，本轮不接线。
- **huoai2**：本轮用户明确不补测 seedance20-mini-audio / long-term 两档。
- **智赢 AI（zhiyingai.cc）**：**决定不实测、不接入**；仅吸收其工程规范（§5）。理由：无公开价目（登录墙 + 第三方兑换码店铺 + 微信人工充值）、小众零口碑；模型阵容含 Sora2/Veo3.1/可灵3.0 等独家货，未来若需要可再评估。

## 4. 三家待接线平台契约（实测，2026-10-12）

> 以下 model id、端点、字段名均来自抓包 / OpenAPI / 真实成功单。令牌从 token 文件读取（见 §7.1），本文不记录令牌值。
> 取证原件在 TEMP（§7.2）：`erchun_openapi_v2.json`、`suanliai_pricing.json`、`sanbao_docs.html`、`window_s_summary.json`、`window_j_erchun_suanliai_wan3.json`、`window_l.json`、`window_m.json`。

### 4.1 贰春 erchun（i2v 扩展）

Host：`https://api.erchun.youkou.cc`；鉴权 `Authorization: Bearer <erchun_token>`。

**核心坑：素材上传在 v2，快乐马提交只在 v1，必须跨版本组合。**

1. 模型目录：
   - v2 `GET /v2/catalog`（仅 8 模型：TT Image、SD2.x、Wan3.0，**无快乐马**）；规范 `GET /v2/openapi.json`。
   - 快乐马只存在于 v1 模型目录。
   - Wan3.0 两版目录都有，实测走 v1 提交成功。
2. **上传素材（v2）**：`POST /v2/media/uploads`
   - `multipart/form-data`，唯一 part 名 **`file`**，内容为原始二进制（不是 base64）；无 kind/type 参数，part 的 filename 带正确扩展名（实测上传名即 .jpg/.mp4/.wav），返回体给出 `media_type`。
   - 返回 `{"media_id":"med_xxx","object":"media.asset","media_type":"image|video|audio","status":"ready","expires_at":"<RFC3339，约24h>"}`。
   - med_id 约 24 小时过期，**不可跨会话复用**；会话通道（`https://erchun.youkou.cc/api/workspace/media`，需登录 Cookie）签发的 med_id 与开放 API 的 med_id **不互通**（跨通道提交报 400 invalid_media_id，已实证）。
3. **提交任务（v1）**：`POST /v1/videos`
   - 请求头必须带 **`Idempotency-Key`**。
   - `input_images` / `input_videos` / `input_audios` 的元素**必须是对象** `[{"media_id":"med_xxx"}]`；裸字符串报 `invalid_media_id`（v2/v1 同规则）。
   - 分辨率字符串**大写**：`480P`。
4. 轮询：`GET /v1/tasks/{id}`（注意 v2 也有 `GET /v2/tasks/{id}`，与提交版本对应）；响应 payload 可能嵌在 `task` 键下。
5. 成片下载：content 接口需带 Bearer；`content_url` 可能是相对路径，要拼 host 并加 `?delivery=stream`。
6. 余额对账：`GET /v2/account` → `balances.normal`（J11/J14 两轮后实测：期初 133.043540 − 1.00（快乐马）− 0.79（Wan3）= 131.253540，完全吻合）。

实测 model id：

| 路线 | model id | 计费 | 成功单 |
|---|---|---|---|
| 快乐马1.1（网页上游名 happyhorse-1.1-r2v） | `mdl_fd1c501eb8bd8436cf9e427b9eddc61e` | 1 credit=¥1.00/条 | J11 网页、J13 纯 API |
| Wan3.0 | `mdl_ec286eb1bc618249d65b87bc79366417` | ¥0.79/条（5s） | J14 全槽位、M14、J2c（t2v 467s） |

### 4.2 算力 AI suanliai（i2v 扩展）

Host：`https://suanliai.top`；鉴权 `Authorization: Bearer <suanliai_token>`。

1. **素材必须先转存再提交**：`POST /v1/assets/review`，请求体为 `{images:[公网URL...], videos:[...], audios:[...]}`（数组，按类分开），返回转存后的引用标识，提交时使用。
2. 提交：`POST /v1/videos`，请求体：
   ```json
   {"model":"<中文档名，逐字照抄>",
    "prompt":"...",
    "images":[...], "videos":[...], "audios":[...],
    "duration":5, "aspect_ratio":"16:9", "resolution":"480p"}
   ```
   - 分辨率**小写** `480p`（与贰春大写相反；但中文档名内部自带的 `480P` 是名字的一部分，**不代表字段值**，两者互不影响）。
   - 时长字段：本轮 wan3 五档（J3–J7/M3–M7，5s）与 004 长档（J9b/J10，30s）**均按 wan3 规则传 `duration`（整数秒）**；历史 007 系列 Seedance2.5 档（J8/J9，模型名不含 wan3）用 `seconds`。接线时仍应以假服务器契约测试锁定，付费云验收时复核一次。
   - model 是中文档名字符串，以下逐字照抄（完整名与价格以 `suanliai_pricing.json` 为准）：
     - `高质量稳定系列wan3.0-video(官转原生过人脸多参生视频)` ¥1.15
     - `…wan3.0-video-prime(官转…)` ¥1.20
     - `wan3.0-video标准版(输出+视频参考-480p/720p/1080p)` ¥1.75
     - `wan3.0-video-prime高速版(…)` ¥2.25
     - `特价/wan3.0-video-480p` ¥1.75
     - `004系列/wan3.0-video`（J9b 长档，**去掉参考视频**才成功）¥2.95/条
     - `004系列/wan3.0-vedio(优质10图5音/5-30秒/480P)` ¥3.2/条（"vedio" 是平台原名拼写错误，不得修正）
3. 轮询：`GET /v1/videos/{task_id}`，task_id 形如 `task_xxx`。
4. 下载成片必须带**浏览器 User-Agent**，否则被拦。
5. 余额/对账：`GET /v1/dashboard/billing/usage` 读 `total_usage`（单位：100 单位=¥1，实测差额 1425=¥14.25 与 7 单价目完全吻合）；`subscription.hard_limit_usd` 出片后才结算。
6. 坏档与编号关系（勿混淆）：
   - **007 系列 = Seedance2.5 满血档**：J8（10图5视5音）返回 404 model disabled；J9 原名档拒绝视频参考。此系列本轮不接线。
   - **004 系列 = wan3.0 长档**：J9b 是 `004系列/wan3.0-video` **去掉参考视频后**的成功补单（图片+音频保留）；J10 是同系列"优质10图5音"档，本身不收视频。
   - 算力目录里快乐马只有 `快乐马-kuaile1.0`（1.0 版，¥2.2/条），没有 1.1。

### 4.3 三宝 sanbao（新建适配器）

Host：`https://sanbaobeauty.com`；鉴权 `Authorization: Bearer <sanbao_token>`（也支持 `X-API-Key` 头）。**积分制：1 元 = 10 积分**；创建任务即冻结积分，失败自动全额退。文档：`https://sanbaobeauty.com/docs.html#models`（原件 `sanbao_docs.html`）。

1. 账号 / 目录：`GET /openapi/v1/me`、`GET /openapi/v1/models`（只返回该 key 可用模型）。
2. **上传素材**：`POST /openapi/v1/uploads/raw?kind=image|video|audio&fileName=<文件名>`
   - 请求体是**原始二进制**（不是 JSON、不是 multipart）；`Content-Type` 按文件设 `image/jpeg` / `video/mp4` / `audio/mpeg`。
   - 返回 `{"file":{"url":"https://sanbaobeauty.com/uploads/xxx","kind":"...","contentType":"...","size":N}}`。
   - 大小限制：图片 ≤20MB，视频 ≤50MB，音频 ≤15–30MB（按模型表）。
3. 创建视频：`POST /openapi/v1/videos`
   ```json
   {"model":"...", "prompt":"...",
    "ratio":"16:9", "resolution":"720p", "duration":5,
    "concurrency":1,
    "reference":"all",
    "images":["<url>"] ,
    "videos":[{"tag":"视频1","url":"..."}],
    "audios":[{"tag":"音频1","url":"..."}]}
   ```
   - 视频接口比例字段是 **`ratio`**（图片接口 `/openapi/v1/images` 用 `aspect_ratio`，不要混）。
   - `reference`：`all`（全能）/ `startEnd`（首尾帧）/ `face`（人物一致）。
   - 素材可传公网 URL / data URL / base64 对象；但注意下面 H3 的实测例外。
   - `concurrency` 可选 1/2/4。
4. 轮询：`GET /openapi/v1/videos/{taskId}`；status=`queued|preparing|processing|succeeded|failed`；失败读 `error`；成功读 `video_url` / `download_url`（签名直链约 24h）。**判状态只认 status 字段：GET 回显里 `images`/`videos`/`audios` 等素材回显为空或缺失是正常现象（成功单也空），不得据此判失败。**
5. 图片：`POST /openapi/v1/images`、`GET /openapi/v1/images/{id}`。

**实测成功、可接线的模型（仅这 3 条）**

| model id | 计费 | 实测 | 备注 |
|---|---|---|---|
| `hailuo_h3_2k` | 20 积分=¥2.0/条 | S1c/S1e 成功，2560×1440@24fps | **强制 ≤2 图、必须原生上传 URL + `reference:"all"`**；模型即 2K 规格，成功单未显式传 resolution，接线时先查 `GET /openapi/v1/models` 该模型的分辨率枚举再定，勿臆造 `2k` 字面值 |
| `sd2_9img_seconds_720p_real` | 按秒，5s 实扣 ¥2.75 | S2g 成功，1280×720@24fps | 仅纯图（外链可）；**带参考视频必被安全政策拦截**；提交 `resolution:"720p"` |
| `wan_3_0_once_480p` | 33 积分=¥3.3/条，5–30s | S3 成功 30s，854×480@30fps | 10图+5音频；894s 明显偏慢 |

**已读目录但未实测（接线前需先补一单，勿直接登记）**：`wan_3_0`（按秒 720p，0.30 积分/秒；文档注明 **480p 暂时缺货，建议 720p**）、`hailuo_h3_2k_line3`（¥1.5/次，仅 1–6 图、10–15s）。各模型的音频大小上限（15–30MB 不等）以 `/openapi/v1/models` 返回的模型表为准。

**必须编码进适配器的暗坑（全部有失败单佐证）**

1. `hailuo_h3_2k` 元数据 `max_images=9` 是**虚标**：9 图被上游 `invalid_request` 拒，实测仅 1–2 图可；且**不收外链图**，必须先走 `/uploads/raw` 拿本站 URL。
2. **参考视频在三宝全平台不可用**：两个模型共三单分别报"无法测量 / 安全政策拦截 / 超时"。凡请求含参考视频，路线过滤阶段直接排除三宝。
3. **素材总数硬上限 12 个**（图片+视频+音频合计），与单列声明槽位无关；9+3+3=15 被拒。
4. `sd2_0_mini_933` 是**僵尸档**（入口只收 480p、上游要 720p、720p 入口又拒）→ 黑名单。
5. `sd2_5_once_720p_2` / `sd25_once_720p_4` 等 SD2.5 满血长档不稳定（两单全败）→ 黑名单。
6. 三宝无取消接口、无任务列表 OpenAPI（列表走登录态 `/api/generations`）；失败自动退款，可放心试错。

## 5. 吸收智赢 AI 的工程规范（8 项改进）

智赢不接入，但其 API 设计（`/api/docs` + OpenAPI 3.1）是本轮所见规范度最高的，以下改进纳入接线：

| # | 智赢做法 | 本网关动作 |
|---|---|---|
| 1 | `Idempotency-Key` 必填，重试不双扣 | 编排层统一生成幂等键并透传给所有支持的供应商（贰春已需要）；提交超时只重放一次 |
| 2 | 不支持的素材组合**前置秒拒、不扣分**（如 SD2.5 带视频在 720p 直接拒绝） | 提交前按路线能力（槽位、总数、分辨率、时长、是否收外链/须原生上传）做 **preflight 本地拒绝**，错误分型 `preflight_rejected`，不发起请求、不重试、不花钱 |
| 3 | `/v1/models` 机器可读目录（参数+价格） | routes.yaml 仍是唯一事实源；新增**目录漂移校验脚本/测试**：供应商实时目录与台账在价格、槽位、时长上不一致时报警（手工触发，付费 key） |
| 4 | 排队期可 cancel 并退款 | 路线声明 `supports_cancel`；worker 支持排队撤销；不支持的供应商不暴露该能力 |
| 5 | `/v1/usage` 查余额 | 适配器增加可选 `balance()`；付费云验收/横评前后自动对账（三宝、算力、贰春均已验证可对平） |
| 6 | 状态机含 `review`（人工核对，不自动退款） | `NormalizedResult` 增加 review/挂起态：不判失败、不触发故障切换、不自动退，单列人工对账 |
| 7 | 素材统一先 `POST /v1/files` 换本站 file ID | 新增**供应商素材登记层**（provider staging）：贰春 v2 med_id、三宝 raw 上传、算力 review 转存，统一在 submit 前完成并缓存（注意 med_id 24h 过期） |
| 8 | 对外模型 ID 不含上游信息 | 坚持现有 route_id 脱敏；上游真实模型名只留在台账内部字段 / 注释 |

**探测方法论沉淀（用户指示）**：测某路线素材数量上限时，**从该路线声明的最大值往下投（可二分），被前置校验秒拒即降档**，不要从小往大逐个试——秒拒不扣分且几秒出结果，是最快的槽位探测法。

## 6. 接线计划（4 批，严格 TDD，每批独立可验收）

原则：**只新增、不改已上线 t2v 行为**；每批先红后绿，契约测试用 urllib transport 的假服务器/假传输，不打真实付费 API；付费云验收沿用现有默认 skip 机制。

### 第 1 批：契约与能力声明扩展（base.py / catalog）

- `SubmitRequest` 增加 `reference_audios`（现有只有 images/videos）。
- 路线能力声明扩展：素材接入方式（`public_url` | `provider_upload` | `review_then_ref`）、图片/视频/音频槽位上限、**素材总数上限**、分辨率白名单、时长范围、是否支持参考视频、`supports_cancel`、`supports_balance`、外部 `review` 态。
- 新增纯函数 preflight 校验：请求 vs 路线能力不满足时返回 `preflight_rejected`（含具体不满足项），不触网。
- 验收：能力声明与 preflight 的单测全覆盖；既有 208 测试不回归。

### 第 2 批：供应商素材登记层（assets/ 新模块）

- 统一接口：输入素材 + 目标供应商，输出该供应商可提交的素材引用。素材统一先经现有 `assets/asset_store.py` 拿到 OSS 公网 URL（本地文件也如此），再按供应商分流。
- 三个实现：贰春 `POST /v2/media/uploads`（multipart `file`，下载 OSS 对象后上传）→ `{"media_id":...}` 对象；三宝 `POST /openapi/v1/uploads/raw`（裸二进制）→ 本站 URL（注意 H3 必须走此路，sd/wan3 可直接用 OSS 外链）；算力 `POST /v1/assets/review`（**只收公网 URL 数组**，直接喂 OSS URL）→ 转存引用。
- med_id / 转存引用带过期缓存（贰春约 24h），过期自动重传。
- 适配器继续只用标准库 urllib（禁 httpx）。
- 验收：假 HTTP 服务器契约测试（part 名、二进制 body、查询参数、返回解析、过期重传）。

### 第 3 批：三家适配器（各配契约测试）

- **贰春**：v2 上传 + v1 提交组合；快乐马1.1、Wan3.0 i2v 两条路线；对象式素材元素；大写 `480P`；Idempotency-Key；content 下载头与相对路径拼接。
- **算力**：review 转存前置；小写 `480p`；wan3 用 `duration`；浏览器 UA 下载；中文档名逐字照抄（含 "vedio"）。
- **三宝（新建 `adapters/sanbao.py`）**：积分↔元换算（×10）；裸二进制上传；`ratio` 字段；`reference` 取值；2K 分辨率归一化；**内置护栏：H3 图数≤2 且强制 provider_upload、含参考视频直接 preflight 拒绝、素材总数≤12、僵尸档/不稳定档黑名单**；`images` 回显为空不判失败。
- 验收：每家成功路径 + 全部暗坑的失败映射测试；可选付费云验收（默认 skip）。

### 第 4 批：routes.yaml 登记 + policy 选路

- 登记本文 §3 全部 i2v/长档路线（`input_modes` 带 image/video/audio；PerSecond/PerUse 报价；槽位与总数上限；接入方式）。
- policy：硬条件 AND 匹配素材槽位（含参考视频→自动排除三宝、simplefuture）；失败备份顺序固化为：
  - 5s 极速/低价：贰春快乐马 → 贰春 Wan3 → 算力 wan3（官转/prime）；
  - 2K 画质：三宝 H3-2K → grsai H3（simplefuture 本轮不接线，仅留作未来候选，见 §8）；
  - 30s 长档：算力 J9b → 算力 J10 → 三宝 wan3 按次。
- 幂等键透传、（支持的）排队取消、balance 对账接线到编排器。
- 验收：选路快照测试（含"带参考视频不选三宝""H3 超 2 图 preflight 拒绝"等关键判定）；决策快照可复盘。

## 7. 环境与操作约定

### 7.1 令牌（只存路径，不存值）

token 文件位于 `%LOCALAPPDATA%\Temp\`（即 `C:\Users\cuigu\AppData\Local\Temp\`）：

- `erchun_token.txt`、`suanliai_token.txt`、`sanbao_token.txt`、`grsai_token.txt`、`autodl_token.txt`
- 另有 simplefuture key（在历史取证中，base `https://simplefuture.zone/v1`）。
- 令牌可能过期；失效时让用户重新提供，绝不写入仓库或文档。

### 7.2 TEMP 取证资产（用户要求保留，勿当垃圾清理）

根目录 `%TEMP%\router_multimodal\`（=`C:\Users\cuigu\AppData\Local\Temp\router_multimodal\`）：

- `probe_common.py`：横评共用库（WORK/manifest、`http()`、`download()`、`ffprobe()`、`load_manifest()`、`Recorder`）。
- `manifest.json`：30 图 + 10 视频 + 10 音频的 OSS 公网 URL（前缀 `https://audio.sggf.net/shared/audio_library/router_refs/2026-10-12/mmprobe1012/`）；本地副本在 `ref_imgs\ref_00..09.jpg`、`ref_media\video_00..02.mp4`、`audio_00..02.wav`。
- 取证 JSON / HTML：`window_j_erchun_suanliai_wan3.json`、`window_k2.json`、`window_l.json`（含 16 个贰春 med_id，**约 2026-10-13 09:11 UTC 过期，仅作字段样例**）、`window_m.json`、`window_s_summary.json`、`erchun_openapi_v2.json`、`erchun_v2_catalog.json`、`suanliai_pricing.json`、`sanbao_docs.html`、`zhiying_docs.txt` / `zhiying_openapi.json`（智赢规范参考）。
- 成片 `outputs\`：J2c/J3–J14、M3–M7/M14、S1c/S1e/S2g/S3 等 mp4；抽帧联系表 `sheets\*_sheet.png`。
- 用户会自行删除一次性侦察 `.py` 脚本；**不要重建已删除脚本**。仓库侧收尾仍按 AGENTS.md 跑 `python scripts/cleanup_task_artifacts.py`（先 dry-run 后 --apply），但 TEMP 取证不在其清理范围。

### 7.3 操作环境硬约束

- 操作系统 Windows，Shell 是 **PowerShell 5**：不支持 `&&` / `||`、不支持 bash heredoc（`<<'PY'` 语法错误）、禁止 cmd；多行 Python 一律用 Write 工具落成 `.py` 再 `python <path>` 执行；临时脚本放 `%TEMP%\router_multimodal\`。
- 浏览器自动化几乎全部在 `run_mcp`（server `integrated_code_mode`）的 Exec 内 `await tools.browser_*`；回显必须 `text(...)`，嵌套结果取 `r.content[0].text`。
- 适配器只用标准库 urllib；中文注释；导入置顶；优先编辑既有文件不新建。
- 测试：`cd router_gateway` 后用项目既有 pytest（参考 GUIDE §测试）；付费云验收默认 skip，需真实试跑时先征得用户同意（会花钱）。

## 8. 明确不做 / 黑名单

- 不接线：三宝 `sd2_0_mini_933`（僵尸档）、三宝 SD2.5 满血 30s 档（不稳定）、算力 `004满血10-5-5`（404 禁用）。
- 三宝任何路线不接受参考视频输入（preflight 拒绝）。
- simplefuture、huoai2、智赢本轮不接线。
- 不补测 huoai2 的 seedance20-mini-audio / long-term（用户已决定）。
- 不回滚用户或其他工具产生的改动；不做未被要求的 Git 操作。
