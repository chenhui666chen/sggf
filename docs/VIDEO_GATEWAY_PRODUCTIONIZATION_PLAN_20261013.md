# 视频网关对外服务化实施计划（2026-10-13）

> 本文是跨窗口交接文档：新会话无需历史对话，凭本文 + `AGENTS.md` +
> `.agent/skills/video-route-onboarding/SKILL.md` 即可继续。
> 所有结论基于代码与付费实证，实证标签（D/J/V/S/T 系列）可在
> `%LOCALAPPDATA%\Temp\router_multimodal\` 证据文件中追溯。

## 0. 目标与非目标

**目标**：让网关作为 7×24 云端服务，对授权调用方稳定开放，文生视频（g5a）与
图/视/音参考视频（g5b）均可经 HTTPS 调用，成片地址永久有效。

**非目标（本期不做）**：
- 调用方计费/扣费/充值系统（clients.balance 字段已存在但不接线，见 §6 决策 D3）；
- 调用方自助门户、管理后台 Web 界面；
- 新供应商接入（智影/画布已决定搁置）。

## 1. 现状事实（2026-10-13）

- 台账 `router_gateway/catalog/routes.yaml` 共 **37 条路线**（W8 新增
  `erchun-happyhorse-1-1` 快乐马 1.1 单图 i2v，2026-10-14），6 类输入模式，
  5 家供应商适配器（erchun/suanliai/sanbao/autodl/grsai），全量测试
  **432 passed / 7 skipped**（2026-10-14 W8 后基线）。
- HTTP 边界 `router_gateway/api/__init__.py`（FastAPI，g5a）：
  `POST /v1/videos`、`GET /v1/tasks/{id}`，10 个边界测试；**硬编码 mode="text"，
  素材元组写死空**（L99-102）。
- Worker `router_gateway/worker.py`：DB 驱动、无状态、可多实例。
- 装配 `router_gateway/assembly.py`：按 token 有无装配适配器并自动剔除无凭证路线；
  token 取 `ROUTER_GATEWAY_{VENDOR}_TOKEN`，回退 `%LOCALAPPDATA%/Temp/{vendor}_token.txt`。
- 独立 PG 库 `router_gateway`（与小说业务库物理隔离）；**无建表脚本/迁移**，
  现网表结构由集成测试 `create_all` 副作用产生。
- 鉴权：仅透传 `x-client-key`（缺省 "default"），不校验；`clients` 表有
  api_key/enabled/balance 字段但生产代码零引用。
- 成片地址：`content_url` 直透供应商 URL，多数带时效。
- OSS：`router_gateway/assets/oss_client.py` 已具备 put_bytes/head/delete
  （V1 签名、from_env、真实桶验证过），接线即可用于成片转存。
- 云基础设施已在跑：根目录 `docker-compose.yml`（backend/frontend/nginx/PG/Redis）、
  `nginx-prod.conf`、SSL 证书挂载、域名体系 `*.sggf.net`
  （audio.sggf.net 已绑 OSS/CDN 并验证）。compose 中**尚无网关服务**。

## 2. 能力实证覆盖（回答"图片/视频参考测好了吗"）

| 模式 | 台账开放路线 | 付费实证 | 结论 |
|---|---|---|---|
| text 文生 | 20+ | 大量（多源多分辨率含 1080p/2K 价格） | ✅ 充分 |
| multi_image 多图参考 | 18 | T7/V3 30图、V5 10图1080p、D1 6图、D4 9图、S1c/S1e 2K 1-2图、J9b/J10/S3 10图；W8 快乐马 1.1 单图（task 82115，480P/5s/¥1.45/47s settled，强采纳） | ✅ 充分（Grsai H3 图生 W8 挂起失败未开放，见下） |
| first_last_frame 首尾帧 | 1（autodl-b99-002，736p） | D3 1 单 | ⚠️ 可用但单源单档 |
| mixed_multimodal 图/视/音混合 | 11 | J14/J5/J3/J4/J6（10图3视3音 480p）、D2（6图3音）、J9b/J10/S3（图+音） | ✅ 混合叙事可用 |
| **video_reference 纯参考视频（无音频）** | 8 条声明（贰春 wan3 + 算力 7 条） | **8 条全部已实证**：贰春 wan3（W7，2026-10-14，task 81578/81610）；算力 7 条（W7 补测，2026-10-14，7/7 completed 轨迹目鉴复现）。W7 前所有带视频实证均为"图+视+音"全槽（归 mixed） | ✅ 8 条声明均有付费实证；注意算力 480p 档参考片按时长同单价另计 |
| **image_audio_lipsync 1图1音对口型** | **0 条路线声明** | 零。z0903 音频 note 已明确"叙事混轨非对口型" | ⚠️ 无供应商，需决策是否找源（见 §6 D4） |

另有大量"档位/比例未实测"（note 中均已标注），与对外服务化无关，按需补测即可；
其中影响售卖面的关键未实测档：z0902/z0903 的 768p/1080p/**2k**、
wan3 多条的 720p/1080p i2v、非 16:9 比例。

**W8 挂起记录（2026-10-14）**：Grsai minimax-h3 单图 i2v 付费单
`11-9576e926-…`（公网 OSS 参考图，480p/5s）同步层 200 受理后，轮询 53 分钟
卡 `running/15%` 无进展（该模型 t2v 正常仅 123–190s），按超时挂起判失败，
`grsai-h3` 维持 text-only、不登记 multi_image。适配器 `image`（单图
public_url）透传与 3 条护栏测试已就绪（16 passed），待上游稳定后只须补一次
成功付费实证即可开放。Grsai 无余额/取消接口，该单是否实际扣费以后台账单为准；
同步层不校验 duration/未知字段（9999 被受理、上游异步 failed），不可用
异常值做活性探测。

## 3. 工作项总览与顺序

```
W1 建表初始化（P0）─┐
W2 API 鉴权（P0）  ├─→ W5 真实 E2E（本机）─→ W6 容器化与上云（P2）
W3 g5b 素材接口（P1）┘                         ↑
W4 成片 OSS 转存（P1）─────────────────────────┘
W7 video_reference 纯视频补测（P1，探测线，可与工程并行）
```

铁律：**W2 鉴权未完成前，服务不得绑定 0.0.0.0/不得进 nginx 公网路由。**
全部生产代码按 TDD（先 RED 再 GREEN），遵循 backend-dev-guidelines 与
test-driven-development 两个 skill。

---

## 4. 工程工作项

### W1 数据库初始化（P0，估 0.5 天）

**目标**：全新环境一条命令把 `router_gateway` 库表建齐。

**改动**：
- 新增 `router_gateway/db/init_db.py`（或 `python -m router_gateway.db.init_db`）：
  `Base.metadata.create_all`，幂等；库本身需预先存在（compose PG 启动后
  `CREATE DATABASE router_gateway`，写入 compose 初始化或部署手册）。
- 不引入 Alembic（当前无历史包袱，YAGNI）；表结构首次变更时再上 Alembic。

**验收标准**：
1. 空库执行初始化后，7 张表（clients/jobs/attempts/route_events/
   decision_snapshots 等）全部创建，重复执行不报错不丢数据。
2. 新增测试：对一次性 sqlite/临时 PG 引擎执行 create_all 后能完成
   create_job→add_attempt→settle_attempt→rolling_stats 全链路。
3. `python -m pytest router_gateway/tests -q` 全绿。

### W2 调用方鉴权（P0，估 1 天）

**目标**：无有效 API key 的请求一律拒绝；key 与 client 落库可吊销。

**改动**：
- 鉴权头用 `Authorization: Bearer <api_key>`（行业惯例，与供应商 key 风格一致）；
  现有 `x-client-key` 保留为可选的终端用户标识透传，不再充当鉴权。
- `JobRepository` 加 `get_client_by_api_key(key) -> Client | None`；
  FastAPI 依赖 `require_client`：查 clients 表，`enabled=false` 或不存在 → 401
  固定文案 `{"error":{"code":"invalid_api_key",...}}`，不泄露 key 与内部细节。
- 发卡/吊销只做 CLI 脚本（如 `python -m router_gateway.admin.client create --name X`
  生成随机 key 落库、`disable` 吊销），**不做 HTTP 管理端点**。
- 编排器 submit_job 的 client_key 传 client.id（内部稳定主键），不再用原始 key。

**验收标准**：
1. 无 header / 错误 key / 已禁用 key 调用 POST 与 GET 均 401；
   错误响应不含供应商、SQL、堆栈。
2. 有效 key 全链路行为与现状一致；幂等键去重仅在同一 client 维度生效（测试锁定）。
3. CLI 发卡两次产生不同 key；disable 后该 key 立即 401。
4. 测试：鉴权依赖单测（假仓储）+ 一条 HTTP 边界测试；现 10 个 API 测试改为
   注入带 key 的假 client，保持原断言语义。

### W3 g5b 素材参考接口（P1，估 1.5-2 天）

**目标**：外部可调图/视/音参考，复用已就绪的六模式仲裁与 `_prepare_assets`
（erchun media_id / sanbao host_url / suanliai review 转存 / public_url 全链路
内部已通）。

**请求契约（g5b，建议方案）**：
- `POST /v1/videos` body 在现有字段上加三组可选数组：
  `reference_images / reference_videos / reference_audios: [{url, duration_seconds?}]`，
  每项只收**公网可读 URL**（含时长元数据用于"参考视频≤15s"类校验）。
- 服务器不经手文件字节：与现有 asset_access 架构一致，最小改动、最小带宽。
- 显式 `mode` 可选传入；不传走 `resolve_mode` 自动仲裁（矛盾请求 422 invalid_intent）。
- multipart 文件上传（g5c）**本期不做**（需服务器临时存储/转存/大小限制，
  调用方现有 audio.sggf.net 公网宿主已满足）。

**验收标准**：
1. 假适配器 TDD：6 模式各至少一条 HTTP→spec 透传测试；空素材等价 g5a。
2. 槽位超限/模式矛盾/非公网 URL/参考视频超长 → 422，错误码稳定。
3. 真实链路 E2E（并入 W5）：1 条 multi_image（便宜档）经 HTTP 提交成功出片。
4. 单请求素材数量、URL 长度、prompt 长度做上限校验（防滥用，值写配置）。

### W4 成片永久化转存（P1，估 1 天）

**目标**：成功任务对外只暴露自有 OSS 永久地址，供应商时效 URL 不外泄。

**改动**：
- worker 对账单成功分支：若 content_url host 不在自有域
  （OSS public_host 白名单），下载成片→`OssClient.put_bytes`
  （key 规则如 `router_gateway/videos/{yyyy}/{mm}/{job_id}.mp4`）
  →覆盖 job.content_url 为 OSS 公网地址；attempt 保留上游原始 URL 于内部字段。
- bucket：见决策 D1（新建视频 bucket 或复用 sggf-audio-library 加前缀）。
- 转存失败不改变"视频已生成"事实：job 保持 succeeded，记录转存状态由重试任务
  或下一 tick 补偿（表字段/事件记录，TDD 补偿逻辑）；对外 URL 在转存完成前
  返回 202 式状态或原始 URL？——采用：未转存完成时 GET 状态保持 running/
  新增 `archiving` 语义（**推荐不新增状态，状态仍 running 直到转存完成**，
  避免客户端状态机膨胀，该取舍在评审时确认）。

**验收标准**：
1. 假 transport 测试：供应商 URL→OSS put 被调用一次、job.content_url 变为
   自有 host、幂等重跑不重复 put。
2. 转存异常时任务可补偿，第三次 tick 成功后地址正确；attempt 原始 URL 可查。
3. 自有 host URL 直接透传不转存（白名单测试）。
4. 真实 E2E：出片后 curl OSS 地址 200 且 `ftyp` MP4 头正确。

### W5 本机真实端到端联调（P1，估 0.5 天，探测预算 ≤ ¥2）

**目标**：第一次真实起服（此前只有假编排器单测）。

**步骤与验收**：
1. `python -m router_gateway.api` + `python -m router_gateway.worker` 本机起服；
   PG 用 docker 内 novel_postgres 的 router_gateway 库。
2. 用 CLI 建测试 client，curl 走文生最便宜档（如 suanliai 007 sd25 480p 5s，
   ¥1.6 以内）下单→轮询→succeeded→（W4 完成后）OSS 地址可下载。
3. g5b 一条 multi_image 便宜单（预算另计 ≤ ¥2）。
4. 演练：下单后 kill -9 worker 再启动，任务被重新拾取且不重复提交
   （幂等/对账验证）；同 Idempotency-Key 重放返回同一任务。
5. 401/422/404/502 各错误码 curl 留档。

### W6 容器化与上云（P2，估 1-1.5 天）

**遵循**：docker-expert、deployment-procedures 两个 skill。

**改动**：
- 网关镜像：评估复用 backend 镜像加 command（依赖基本同栈 FastAPI）或独立
  Dockerfile（推荐独立，保持业务隔离、镜像小）；compose 加两个服务
  `gateway-api`、`gateway-worker`（同镜像不同 command），env 从宿主环境注入：
  5 个供应商 token、`ROUTER_GATEWAY_DATABASE_URL`、OSS 配置；**token 绝不进镜像/仓库**。
- nginx（`nginx-prod.conf`）：新增 server，决策 D2 选域名
  （推荐独立子域 `video.sggf.net`，与业务 API 隔离便于限流/证书/日志），
  HTTPS 证书走现有挂载体系；只暴露 443→gateway-api:8088，worker 不映射端口。
- 部署步骤：服务器拉代码→建库+W1 初始化→注入 env→`docker compose up -d
  gateway-api gateway-worker`→W5 的 curl 清单在公网域名上复跑。
- 回滚：compose 服务可独立停止；数据库无破坏性变更；保留"切回 127.0.0.1"
  的 nginx 配置回退路径。

**验收标准**（2026-10-14 全部通过，证据见下）：
1. ✅ 公网 HTTPS 无证书告警；无 key 401；有效 key 完成一单全链路
   （job 149195bf，202→78s succeeded→video.sggf.net 永久地址）。
2. ✅ worker 重启不丢单：job 5804090c 渲染中 restart gateway-worker，
   新进程经 DB 接管对账成功；attempts 仅 1 条、上游任务仅 1 个（零重复派发/计费）。
3. ✅ 凭据扫描：9 个凭据（5 供应商 token/OSS AK/SK/DASHSCOPE/发卡 key）在
   gateway 两容器日志、nginx 日志、镜像 /app 打包内容中零命中；api 日志亦无上游签名 URL。
4. ✅ 宕机隔离：stop gateway-api/worker 期间 sggf.net 与 www 主站全程 200、
   video OSS 取片 200，网关业务面 502；恢复后 401/404 全绿。

**验收遗留（均已修复，2026-10-14）**：
- ~~api `/health` nginx 本地 return 200 假绿~~ → FastAPI 新增免鉴权 `GET /health`
  （测试先行，374 passed），nginx 改为回源转发（3s/5s 短超时）；停网关实测
  /health 返回 502/504 真红，主站仍 200。
- ~~网关容器换 IP 导致 nginx 缓存旧 IP 需 reload~~ → 新增独立边缘网络
  novel_gateway_edge（172.30.0.0/24），gateway-api 固定 172.30.0.10、
  nginx 同网；force-recreate 全新容器后 IP 不变、**未 reload nginx** 即自动恢复。
  gateway-api 同时留在 novel_network 访问 postgres；compose healthcheck
  升级为真实 HTTP /health 探测。

### W7 video_reference 纯视频补测（P1，探测线；✅ 2026-10-14 已完成）

按 video-route-onboarding skill 执行，预算 ≤ ¥10，需用户在场确认每批花费：
1. 零成本活性探测后，付费最小单：贰春 wan3（素材体系最完整）**仅 1 参考视频、
   无图无音** 480p 5s，ffprobe+抽帧验证视频确实被参考；
2. 补 1 单"图+视频无音频"（自动仲裁归 video_reference 的另一分支）；
3. 成功 → 8 条声明路线中实证源保留 video_reference，其余依工作流枚举的路线
   note 维持"未实证"；失败 → 按错误语义决定收紧台账（从无实证路线移除
   video_reference 模式）。
4. 参考视频 15s 限制、无音频轨要求在测试单中顺带锁定边界。

> **完成报告（2026-10-14）**：按上述步骤执行两单付费实证，实际花费约 ¥1.6（480p ¥0.158/s×5s×2 单）。活性探测 duration=9999 返回 422 在线；**单 1（仅 1 参考视频、无图无音，task 81578）**：8s 无音轨几何运动参考片（红块横移+蓝块上下振动）经 /v2/media/uploads 换 med_id 后提交，480p 5s 成片 854x480/30fps、settled、渲染 278s，抽 0.5/2.5/4.5s 三帧目鉴两方块运动轨迹、方向、相位与参考片吻合；**单 2（1 图+1 视频、无音频，task 81610）**：settled/288s，W7 紫色参考牌元素贯穿全片（图采纳）+红块左→右横移复现（视频采纳）。两单均**无音频输入但成片默认带 AAC 音轨**（平台配乐，非参考音频复刻）。结论：贰春 wan3（erchun-wan3）的纯 video_reference 与"图+视频无音频"两个分支均有付费实证支撑，台账 note 已登记；**算力 7 条声明路线仍零实证，其 video_reference 标签维持"声明未验证"，不得对外宣传**。参考视频 8s＜15s 上限、无音轨提交被正常受理（15s 上限沿用既有边界探测，未额外突破）。

> **算力 7 条补测报告（2026-10-14，用户授权续测）**：对 suanliai 7 条 wan3 声明路线（007-wan3-video / 007-wan3-prime / wan3-std / wan3-1080 / wan3-guanzhuan / wan3-guanzhuan-prime / wan3-prime-fast）各下 1 单纯 video_reference（共用同一 8s 无音轨几何运动参考片，经 `/v1/assets/review` 一次转存 7 单共用，5s/16:9，无图无音），**7/7 completed**：6 条 480p 成片均 854x480/30fps/5.04s/默认 AAC、渲染 151-393s；wan3-1080 成片 1920x1080/30fps/默认 AAC、渲染 1424s（约 24 分钟）；逐单抽 t0/t2/t4 三帧目鉴，红块左→右横移、蓝块居中上下振动的轨迹/方向/相位与参考片一致（007-prime 节奏略快，t4 红块已移出右缘，语义一致）。**成本语义（实扣与报价分毫不差）**：6 条 480p 档视频参考按「输出时长 + 参考片时长」同单价计费（5s 输出 + 8s 参考 = 13s），wan3-1080 仅按输出 5s 计费、参考片不另计；7 单实扣 **¥25.63**（480p 六单 ¥23.53 + 1080p ¥2.10），已超出 W7 原 ≤¥10 预算（用户授权）。7 条路线 video_reference 标签由"声明未验证"转为付费实证，台账 note 与头部注释均已登记 task 号、规格、耗时、扣费。

## 5. 里程碑

- **M1 内部可用（W1+W2+W5 文生部分）**：可信内部方经网络调文生，约 2 天。
- **M2 能力完整（W3+W4+W7）**：图/视/音参考 + 永久成片地址，约 2-3 天。
- **M3 公网上线（W6）**：video.sggf.net 正式开放，约 1.5 天。

## 6. 待用户决策项

- **D1 OSS bucket**：✅ 2026-10-13 已决策并落地：新建 `sggf-router-video`
  （华东2上海/标准存储/同城冗余/公共读），W4 E2E 已真实转存验证。
- **D2 对外域名**：✅ 2026-10-14 已决策并**全部上线**——**拆分为两个子域**：
  `video.sggf.net` 绑 OSS 桶做成片静态分发（最终采用 **OSS 原生自定义域名**：
  CNAME → sggf-router-video.oss-cn-shanghai.aliyuncs.com，证书经 CAS 上传后
  PutBucketCname 绑定，续期脚本 /opt/oss_cert_renew_video.sh，cron 每日 02:30；
  经 _dnsauth TXT 完成归属校验；日后切 CDN 只改 CNAME、代码零改动），
  `api.sggf.net` 为调用方下单/轮询入口（A 记录 → 101.132.154.143，
  docker nginx 新增 server 反代 gateway-api:8088，certbot 同证书扩签 SAN）。
  仓库侧（nginx-prod.conf / docker-compose.yml / deploy_config.json / .env.example）
  与云侧（DNS/证书/库表/发卡/容器）均已完成；公网验收：/health 200、无 key 401、
  /docs 已在 nginx 层 404、video 域 HTTPS 取片 200。有效 key 真实付费全链路冒烟
  已完成（2026-10-14 02:27，job 149195bf，autodl-lightx2v-h3 / 480p 横 / 1s，
  报价 ¥0.03，202→轮询 78s succeeded→OSS 永久地址→ffprobe 864×480/24fps/含 AAC，
  仅该档 1s 极限规格 prompt 遵循差，与链路无关）。
- **D3 是否本期做调用方计费**：推荐**不做**，先按 client 维度记录 attempt.cost
  （已落库）出账单报表，跑一段真实流量后再设计余额扣费。
- **D4 对口型（image_audio_lipsync）是否找供应商**：当前 5 家无一路线支持；
  若业务需要数字人/对口型场景，另立探测批次（不在本计划工程线上）。
- **D5 g5b 归档语义**：成片转存期间 GET 维持 running（推荐）vs 新增 archiving。
- **D6 闲时探针**：AutoDL z0902/z0903 2K 档与 V2 复探（预算 ¥6.33）用户已删脚本、
  已注销计划任务；如需重排，重新按 video-route-onboarding 出脚本并经用户确认。

## 7. 给新窗口的交接指引

1. 先读：`AGENTS.md`、`.trae/rules/project_rules.md`、
   `.agent/skills/{backend-dev-guidelines,test-driven-development,video-route-onboarding,
   docker-expert,deployment-procedures}/SKILL.md`（按当步任务选读）。
2. 代码入口：`router_gateway/assembly.py`（装配）、`api/__init__.py`（HTTP）、
   `orchestrator/service.py`（submit_job/poll_job/_prepare_assets）、
   `db/__init__.py`（模型与仓储）、`catalog/routes.yaml`（36 条台账）。
3. 测试基线：`python -m pytest router_gateway/tests -q`
   应 294 passed / 7 skipped（本计划实施前）。
4. 供应商 token：`%LOCALAPPDATA%\Temp\{erchun,suanliai,sanbao,autodl,grsai}_token.txt`
   （仅本机开发用；云端只走环境变量）。
5. 花钱纪律：任何付费探测先报预算、秒拒不扣费、出片必 ffprobe+抽帧目鉴；
   探测脚本放 `%LOCALAPPDATA%\Temp\router_multimodal\`，用户会自行删脚本，勿重建。
6. 完成后跑 `python scripts/cleanup_task_artifacts.py`（dry-run 再 --apply）。
7. 挂起事项：OSS 历史探针素材/探针 key 待全部任务结束后、经用户明确确认再删除。

## 商用 API 应用管理实施结果

- 主站已提供用户级视频 API 应用申请、列表、Key 轮换和吊销；普通用户只能访问自己的应用。新申请为 pending，对应网关 Client 默认禁用，超级管理员批准后启用；不能自行选择套餐绕过审批。永久吊销的应用不可恢复或轮换 Key。
- 超级管理员已提供应用状态、配额调整和视频网关监控入口；后端权限校验独立于前端菜单隐藏。
- 网关已支持客户级请求速率、突发容量、活动任务和最大并行尝试限制。活动任务额度在客户行锁下检查，避免并发请求超卖；相同幂等键重放不会重复占用额度。
- 网关已提供内部管理接口和聚合监控接口。内部接口必须使用 `X-Gateway-Internal-Token`，生产和 staging 启动时 Token 为空会直接失败；网关端口应继续保持仅内网或回环暴露。
- 生产环境网关使用 `ROUTER_GATEWAY_INTERNAL_TOKEN`，主站使用值相同的 `VIDEO_GATEWAY_INTERNAL_TOKEN`，并配置 `VIDEO_GATEWAY_INTERNAL_URL`。Compose 自动映射内部 Token 和容器地址；主站直接运行时需配置两个 `VIDEO_GATEWAY_INTERNAL_*` 变量。Redis 是限流的运行依赖，Redis 不可用时网关 fail-closed 返回 503。
- 主站 Alembic 迁移执行前必须备份数据库；网关旧库由 `init_schema()` 补齐新增客户配额字段，仍应在 staging 先验证再上线。
- **部署状态（2026-10-14）**：商用版代码（强制 Idempotency-Key、同键冲突 409、应用限流 429/限流依赖 503、`/internal/*` 管理端点）随新版 gateway 镜像部署生产，对外契约以接入文档 v1.1 为准。部署前置项：生产 `.env` 补 `ROUTER_GATEWAY_INTERNAL_TOKEN`（与主站 `VIDEO_GATEWAY_INTERNAL_TOKEN` 同值，否则 `APP_ENV=production` 下网关拒绝启动）、Alembic 迁移执行前先备份库；部署前"仅代码+本地测试、未生产迁移/部署"的状态自此结束。
- 创建、轮换、状态更新和额度同步的主站写库失败时会请求网关禁用作为补偿。如果补偿请求也失败会记录客户 ID；跨库自动对账和补偿重试仍需后续完善。
- 监控显示凭据配置状态和路由目录状态，实际成功率与延迟来自最多最近 10000 条结果事件；实际账单缺失时显示未知，不能把缺失成本当作零。尚不包含实时供应商活性探测、429 历史计数、自动计费和日/月预算硬拦截。
- 额度按已批准的 API 应用隔离，当前不实施同一主站用户全部应用的共享额度。`max_parallel_attempts` 为单任务限制；业务吞吐还受 worker 数量、轮询时长、数据库与供应商配额影响。
- Compose 的 APP_ENV 默认 production，会触发现有 JWT、OAuth、密码历史密钥和 CORS 安全检查；部署前需检查全部既有安全配置。开发环境可显式设置 APP_ENV=development。

### 本轮本地验证（2026-10-14）

- 主站申请管理、内网客户端、OpenAPI 和管理员回归测试：36 项通过。
- 网关本地测试：382 项通过、7 项 opt-in 云集成测试跳过；本轮不执行会清空 PostgreSQL 测试库的 `test_repository.py` 和 `test_orchestrator_db.py`。
- 前端配额校验、权限判定和 API 错误处理：13 项通过；TypeScript 类型检查通过。
- Compose 配置检查和容器内 `nginx -t` 通过；未重载 Nginx，未重启任何服务。Nginx 保留现有 `listen ... http2` 弃用警告。
- API 管理实施阶段测试缓存已获确认并完成清理。

### 后续模拟容量测试（2026-10-14）

- 完成 4372 次本地 HTTP 请求，独立临时 PostgreSQL/Redis、两个同进程 API 实例、模拟供应商；没有真实供应商调用，未变更生产数据库。
- 100 个活动任务上限、共享 Redis 限流、供应商故障恢复均符合预期。修复并发幂等重复提交和 Redis 默认失败重试问题；新增回归后网关 390 项通过、7 项跳过，主站 36 项通过。
- 128 HTTP 查询并发时出现 1 次连接中断，最终报告明确标为未全部通过；较低并发速度更快。活动任务额度不能等同于适合的 HTTP 并发数。
- 环境、数据、复现命令和限制见 [容量测试报告](VIDEO_GATEWAY_LOADTEST_20261014.md) 与 [原始 JSON](VIDEO_GATEWAY_LOADTEST_20261014.json)。Nginx、公网、真实供应商、生产固定依赖版本和长期稳定性未包含在本轮容量结论中。

### 后台视觉质量抽评（2026-10-14，代码已接入，待部署启用）

成片沿用现有交付校验和自有 OSS 转存流程，一旦可交付立即返回成功；视觉评价由独立进程 `router_gateway.quality_worker` 处理，不进入交付 worker、查询接口或用户回调。低分、模型错误、解析失败、超时和质量 worker 停机均不撤销交付，不触发重新生成，也不修改订单、账单或生成成功率。

- 默认按目录的 `quality_group` 作为同一模型标识，跨供应商合并累计成功成片，每第 10、20、30……次抽评一次；失败生成不计数。计数与每条 attempt 的抽样结果持久化，重启、多 worker 不重置或重复抽评。对冲产生的额外成功成片也按 attempt 计入，评分归属实际生成路线。只处理已经成功交付的任务；启用后会从库中尚未采样的成功记录开始补采样。
- 默认评价模型 `qwen3.8-omni-flash`，关闭思考，最多 1200 输出 token。评价清晰度、运动流畅度、时序一致性、曝光、色彩，验证分数为有限的 0～10 数值且带画面证据；五项均分至少 6 为内部统计合格，不能作为交付门槛。兼容裸控制字符，不猜测修补其余非法 JSON，不自动重试付费请求。
- `quality_reviews` 保存采样序号、实际路线、评价模型、各维度分数和证据、均分与状态；`quality_sample_counters` 保存模型累计计数。非抽中记录标记 `skipped`，有效评分之外的记录不进入质量合格率分母。任务查询及普通用户管理响应均不含评价数据。
- 未来选路按路线 × 档位使用最近 100 个有效评价样本，质量系数向 10 个合格先验收缩，防止极少量样本造成过大波动；未评保持中性，不将历史默认 `quality_pass=True` 当作真实评价。内部 Token 保护的聚合监控增加有效样本数、平均分、合格率及评价状态计数，最多统计窗口内最近 10000 条评价记录，不返回原始画面证据。
- 评价领取使用唯一 attempt 约束和 PostgreSQL `FOR UPDATE OF attempts SKIP LOCKED`；当前租约 token 原子收尾。worker 崩溃遗留的评价在租约过期后标记 `worker_lost`，不重放未知结果的付费调用。下载复用受控公网读取，64 MiB 上限；超限只导致内部评价失败。

部署时先备份并核对目标网关数据库，再经生产变更确认运行既有 `python -m router_gateway.db.init_db` 创建新增表；该命令也会检查既有幂等补列逻辑。API 在尚无质量表的旧库上保持中性评分并继续交付；完成建表后重启 API/交付 worker 以刷新表存在性缓存。质量 worker 只依赖网关数据库与 `DASHSCOPE_API_KEY`，不依赖决策模型、OSS 写权限或供应商生成凭据。

`.env.example` 已补充 `ROUTER_GATEWAY_QUALITY_BASE_URL`、`ROUTER_GATEWAY_QUALITY_MODEL`、`ROUTER_GATEWAY_QUALITY_TIMEOUT` 和 `ROUTER_GATEWAY_QUALITY_SAMPLE_EVERY=10`。Compose 服务受 `video-quality` profile 控制，普通启动不启用付费抽评；确认部署后使用 `docker compose --profile video-quality up -d --build gateway-quality-worker`，可通过 `--scale gateway-quality-worker=N` 扩容。尚未在生产建表、启用该 worker 或真实调用付费视觉模型，登录与生产验收不在本轮本地验证范围内。

本地验证：网关 422 项通过（显式排除两个会清空既有 PostgreSQL 测试库的测试文件，以及三份云集成文件）；既有跨供应商视觉适配器 17 项通过；Compose `video-quality` profile 配置检查通过。新增 20 项测试覆盖第 10 次触发、跨渠道累计、重启继续计数、失败生成不计数、超时后不付费重试、并发唯一领取、过期租约隔离、低分仍成功交付、评价前后公开响应一致、内部指标与选路接线。本轮未进行真实视觉模型效果或生产容量验收。
