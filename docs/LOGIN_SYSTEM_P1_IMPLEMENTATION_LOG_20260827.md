# 登录系统 P1 落地实施记录

> **关联文档**：[LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md](./LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md)、[LOGIN_SYSTEM_P0_IMPLEMENTATION_LOG_20260825.md](./LOGIN_SYSTEM_P0_IMPLEMENTATION_LOG_20260825.md)
> **实施方式**：按批次推进（用户确认批次 1 起步），TDD RED->GREEN
> **实施日期**：2026-08-27（批次 1）、2026-08-28（批次 2、批次 4、批次 3）
> **结论**：✅ 批次 1（3.1 / 3.3 / 3.4 / 3.5）落地并经用户复审修复，63 项测试通过；✅ 批次 2（3.7 + 会话收口）落地并经复审修复，后端 77 项测试通过（63 -> 74 -> 77）；✅ 批次 4（3.9 + 3.6）落地，后端 82 项相关测试通过、全量 4242 passed，前端 tsc + 923 项测试通过；✅ 批次 3（3.2 + 3.8）落地，后端定向 78 项、全量 4264 passed（5 skipped），前端 tsc + 923 项测试通过；✅ 批次 4 评审修复（OAuth consume/state 判定收紧 + confirm 失败写回/400 不写回 + 跨标签登出 + 已注册邮箱不发信），后端全量 **4264 passed**、前端 **924 passed** + tsc

---

## 一、批次总览

| 批次 | 范围 | 状态 | 说明 |
|------|------|------|------|
| **批次 1（2026-08-27）** | 3.1 限流 + 3.3 授权码泄漏 + 3.4 密码重置加固 + 3.5 单会话登出 | ✅ 完成 | 纯后端为主，详见本日志 |
| **批次 2（2026-08-28）** | 3.7 短 access token + refresh token + 会话收口 | ✅ 完成 | 后端 + 前端配合，详见第八章 |
| **批次 3（2026-08-28）** | 3.2 建号确认 + 3.8 邮箱验证 | ✅ 完成 | 一次合并迁移（新增列 + email 放开非空），详见第十章 |
| **批次 4（2026-08-28）** | 3.9 RBAC/越权 + 3.6 CSP/前端安全基线 | ✅ 完成 | 横切面治理，详见第九章；含批次 2 边角 1（多标签刷新）收口；含评审修复 9.6（边角 3 跨标签登出 + 3.2 同构坑 + 已注册邮箱不发信） |

---

## 二、批次 1 实施概览

| P1 编号 | 改造项 | 状态 | 验证方式 | 结果 |
|---------|--------|------|---------|------|
| 3.1 | 登录/注册/重置码限流 + OAuth code 换票锁 | ✅ 完成 | TDD（429/400 路由测试 + fake 注入） | 5 项限流测试 + 1 项 code 重放测试通过 |
| 3.3 | 授权码泄漏防护 | ✅ 完成（无需改码） | 现状核查 | nginx Referrer-Policy / 前端 replace 导航 / 无 code 日志，均已满足 |
| 3.4 | 密码重置链路加固 | ✅ 完成 | TDD（schema 无 dev_code + 服务层 fail-closed） | 2 项新测试通过 |
| 3.5 | 单会话登出（jti 吊销） | ✅ 完成 | TDD（端到端 logout 后 401 / 迁移窗口 / 503） | 3 项新测试通过 |

---

## 三、改造明细

### 3.1 登录与注册限流（账号+IP 维度）

**新增**（[auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py)）：

- `INCR_WITH_TTL_LUA`：Lua 脚本原子 INCR + 首次 EXPIRE（固定窗口计数）
- `AuthRateLimiterService`：`check(key, limit, window)`，超限 429、Redis 挂 503（fail-closed，不静默放行）
- `OAuthCodeGuard`：换票锁。`acquire`（SET NX EX 30，先查 `code_used`）-> 成功 `mark_used`（10 分钟）-> 网络/签名类错误 `release` 允许重试；支付宝仅对明确 "code been used"/"code-invalid" 落 used 标记，微信仅对 errcode=40163
- `_client_ip(request)` / `_account_hash(identifier)`：账号维 key 用 sha256 前 16 位（不落明文账号）

**接入端点**：

| 端点 | 维度 | 阈值（默认） |
|------|------|------|
| `/login` | IP 20/min + 账号 5/min | `AUTH_RATE_LIMIT_LOGIN_IP_PER_MINUTE` / `AUTH_RATE_LIMIT_LOGIN_ACCOUNT_PER_MINUTE` |
| `/register` | IP 3/min | `AUTH_RATE_LIMIT_REGISTER_PER_MINUTE` |
| `/reset-password/request-code` | 账号 1/min + IP 20/min | `AUTH_RATE_LIMIT_PASSWORD_RESET_PER_MINUTE`（复用 IP 阈值） |
| `/alipay/callback`、`/wechat/callback` | code 换票锁 | 锁 30s / used 标记 600s |

**关键设计**（遵循文档反模式警示）：账号维限流在路由函数内、Pydantic 解析后手动执行，不在中间件层读 body。

### 3.3 授权码泄漏防护

现状核查结论（无需改码，P0 期间已完成）：

1. nginx `/login/callback` 已设 `Referrer-Policy: no-referrer`（P0 收尾 2）
2. 前端 `LoginCallbackPage.tsx` 已 `navigate('/home', { replace: true })`
3. 后端 OAuth 链路不打印 code（oauth_service.py 无 logger 调用含 code）
4. 前端未接入 Sentry 等错误监控 SDK（无脱敏需求）
5. "后端 302 换票" 归入后续优化（与 4.x 排期）

### 3.4 密码重置链路加固

| 改动 | 文件 | 说明 |
|------|------|------|
| 移除 `dev_code` 回传 | `auth.py` + `schemas/user.py` | DEBUG 也不再把验证码回传客户端 |
| 移除内存回退 | `password_reset_service.py` | 删除 `_memory_store`，Redis 不可用 -> 503（fail-closed）；`_read_record`/`_write_record`/`delete_code` 各自 503 |
| 既有已满足项 | - | SMTP 失败删验证码（P0）、重置成功 tv 递增（P0） |

**注意**：`_get_redis_client` 补了 `socket_connect_timeout=1.0`，Redis 挂时快速失败而非长时间阻塞。

### 3.5 单会话登出（jti 吊销）

**新增**（[security.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/core/security.py)）：

- `JtiRevocationService`：`revoke(jti, exp)` setex（TTL=剩余有效期）、`is_revoked(jti)`；Redis 挂 503（fail-closed，否则吊销形同虚设）
- `get_token_payload` 依赖：登出路由解析 Bearer token payload

**改动**：

- `get_current_user` 增加 `await _check_jti_revoked(payload)`；无 jti 旧 token 走迁移窗口放行（随过期自然失效，最长 24h）
- `get_current_user_optional` 同步校验（吊销/异常按匿名处理，仅限展示类接口）
- `logout` 路由：吊销当前 token 的 jti；不再空操作
- 登出通过 `core_security.jti_revocation_service` 模块属性访问（测试可替换）

**机制分工**（与 token_version）：

| 操作 | 机制 | 影响范围 |
|------|------|---------|
| 改密/重置/禁用 | `token_version += 1` | 所有设备 |
| 登出 | `jti` 黑名单 | 当前会话 |

---

## 四、TDD 过程记录

| 步骤 | 结果 |
|------|------|
| RED：新增 11 项测试（3.5 x3、3.4 x2、3.1 x5、code 重放 x1） | 11 项按预期失败（logout 200->应吊销、无限流 429、dev_code 存在），既有 49 项保持通过 |
| GREEN-3.5：JtiRevocationService + logout 吊销 | 3 项转绿 |
| GREEN-3.4：移除 dev_code + fail-closed | 2 项转绿 |
| GREEN-3.1：限流 + code 锁 + 4 端点接入 | 剩余转绿 |
| 全量回归 | **60 passed**（49 既有 + 11 新增） |

**测试基建适配**（保持既有 49 项语义不变）：

- `test_auth_routes.py`：`build_test_client` 注入 `FakeJtiService`/`FakeRateLimiter`/`FakeCodeGuard`/`FakePasswordResetService`（内存实现，fail_redis 开关）；新增 `override_current_user=False` 参数供 jti 端到端测试走真实依赖链
- `test_oauth_alipay.py`：新增 `FakeCodeGuard`，换票测试 monkeypatch 替换
- `test_admin_user_points_routes.py`：`build_test_client` 注入 `_FakeJtiService`（该文件走真实 get_current_user 链路）

**踩坑记录**：fail-closed 服务层测试最初用 `redis://127.0.0.1:0/0` 假设连不上，实际 redis-py 把 port=0 解析为默认 6379，本机真实 Redis 被误连并写入测试数据（已清理 `auth:password-reset:1`）。修正为 port=1 并在测试注释中说明。

---

## 五、资源使用情况

| 类别 | 清单 |
|------|------|
| 依赖 | 无新增（Redis 复用 `redis` 6.4.0） |
| 后端文件变更 | `config.py`（4 个限流字段）、`api/v1/auth.py`（限流/code 锁/jti 登出/dev_code 移除）、`core/security.py`（JtiRevocationService + jti 校验）、`schemas/user.py`（dev_code 字段移除）、`services/password_reset_service.py`（fail-closed 重构） |
| 测试文件变更 | `test_auth_routes.py`（4 个 fake 类 + 11 项新测试 + 适配）、`test_oauth_alipay.py`（FakeCodeGuard + 1 项 + 适配）、`test_admin_user_points_routes.py`（jti fake 注入） |
| 配置模板 | `backend/.env.example`（4 个限流变量） |
| 文档 | 架构文档（3.1/3.3/3.4/3.5 状态标记 + 总览表）、本日志（新建） |

---

## 六、批次 1 复审修复（2026-08-27，用户对照审查后）

用户确认批次 1 主体落地后点名 6 项，其中 4 项修复、2 项记录处置。

| 项 | 问题 | 处理 | 验证 |
|----|------|------|------|
| 修1 | `_client_ip` 只读 `request.client.host`：反代后是容器 IP，IP 维限流全站共桶（生产基本失效且误伤） | 优先读 nginx `X-Real-IP`（`proxy_set_header X-Real-IP $remote_addr` 强制覆盖，不可伪造），无头时回退 socket 地址；不读 XFF（追加链可伪造）。前提：后端端口不得绕过 nginx 对公网暴露 | `test_client_ip_prefers_nginx_x_real_ip` |
| 修2 | 换票成功后 `get_user_info` 失败不落 `mark_used`：第三方 code 已作废但本端未标记，用户重试再打网关 | 两家 callback 拿到 `access_token` 后立即 `mark_used`（换票成功即已消费），user_info 失败不再释放锁 | `test_alipay_callback_marks_code_used_immediately_after_exchange` |
| 修3 | 限流 key 用原始输入，与 `_find_user_by_identifier`（email lower 匹配）口径不一：`Alice@x.com`/`alice@x.com` 打进不同桶，账号维限流可被大小写绕过 | login/reset-code 的账号维 key 改为 `_account_hash(normalize_identity(...))` | `test_login_rate_limit_normalizes_account_case`（6 变体轮换，第 6 次 429） |
| 修4 | 架构文档 1.5 路由表（logout"不吊销"/dev_code"可能回传"）、1.7 速查表整表过时 | 1.5 全表更新为已完成状态；1.7 加"2026-08-24 基线快照"声明 + 11 行已修复标注 + 待办行标注归属章节 | 文档同步 |
| 修5（记录） | `get_current_user_optional` Redis 异常吞 503 变匿名 | 未改行为：扫描全部 3 个调用点（memories auto-save / 音频流播放 x2），均为"匿名即 401/拒绝"结构，实际 fail-closed；docstring 已声明仅限展示类接口。已在遗留事项中登记"敏感操作不得用此依赖" | 调用点扫描 |
| 修6（记录） | 工作区混入 13 个无关文件（tencent_ai_detect 删除、prompt_evolution、3 个 experiment 脚本） | 不改动：提交登录 P1 时排除；`backend/tmp_new_prompt_verify/` 为实验任务自动重新生成（上次删除后 17:18 又出现），归实验线处理 | `git status` 对照 |

**复审后测试**：60 -> **63 passed**（3 项新守护测试）。

**测试修正记录**：修3 的测试首版断言"第 5 次 429"，实际 `limit=5 + count>limit` 语义为第 6 次才 429；RED 阶段该断言恰好全 401 掩盖了此错误（这正是 TDD 先看失败的价值），已修正为 6 变体。

### 收口补充（2026-08-27，用户确认批次 1 收口后的边角）

| 项 | 问题 | 处理 | 验证 |
|----|------|------|------|
| 边角1 | `memories` 的 `?token=` 查询参数走裸 `verify_token`，不查 jti/tv：登出或改密后，URL 里的旧 token 仍可能自动保存一次（sendBeacon 场景） | 不改动：归入 3.7（短 token + refresh）会话收口一并处理（3.7 会重整 token 校验链路） | 已登记遗留事项 |
| 边角2 | `JtiRevocationService` 连 Redis 无 `socket_connect_timeout`：Redis 挂时鉴权路径会卡默认超时才 503（限流/重置码服务均有 1.0s 超时） | `security.py` 补 `socket_connect_timeout=1.0`，与限流器/重置码服务对齐 | 静态检查 |
| 边角3 | 日志文首仍写"60 项通过" | 更新为 63（49 -> 60 -> 63） | 文档同步 |
| 边角4 | 提交时避开无关改动 | 同修6 口径：提交清单仅登录 P1 相关文件 | `git status` 对照 |

## 七、遗留事项

- 限流为固定窗口计数（文档方案即此）：窗口边界双倍突发理论上存在，如需滑动窗口在批次 2+ 评估
- OAuth code 换票锁的支付宝错误分类依赖错误文案匹配（"code been used"/"code-invalid"），真实沙箱联调时需验证口径
- Redis 从"尽力而为"变为登录链路硬依赖（state/jti/限流/重置码/refresh 全部 fail-closed）：**生产部署前必须确认 Redis 高可用**（与 P0 遗留部署项合并）
- `get_current_user_optional` 的 fail-open 仅适用于展示类接口（当前 3 个调用点均"匿名即拒绝"），后续接入敏感操作时必须换强制认证
- 部署验证项（P0 遗留继续有效）：`APP_ENV=production` 实启、`alembic upgrade head`
- 后端端口不得绕过 nginx 对公网暴露（否则 `X-Real-IP` 可伪造，IP 维限流 key 可被刷）
- ~~`memories` 的 `?token=` 查询参数（sendBeacon 场景）走裸 `verify_token`，不查 jti/tv~~ -> ✅ 批次 2 已收口（`resolve_user_from_token` 完整校验链路）
- **存量会话迁移**（批次 2 引入）：上线时已签发的 24h 长 access token 与新 30 分钟 token 并存，随自然过期收敛（最长 24h）；旧客户端（未升级前端）access 过期后无 refresh_token 可刷新，将回到登录页--**前后端需同步发布**
- 前端 401 自动刷新仅覆盖 `apiClient`（axios）链路；`websocket.ts`、`bookParserApi.ts`、`previewTTSCached`（fetch）与 SSE/EventSource 直连仍只读 access token，过期即断开重连，不走 refresh（现状保持，接入 3.6/4.5 时统一评估）
- refresh 轮换"失败写回"仅在签发侧异常（如 Redis 写新 token 失败 503）时生效；写回成功与否依赖 NX，多实例并发极端场景下旧 token 可能未被恢复（用户重登即可，不影响安全性）
- ~~**多标签页无共享刷新锁**（复审 4 遗留）~~ -> ✅ 批次 4 收口（9.2）：429 等待拉到锁 TTL（5s）+ 随机抖动，等待后优先接管另一标签页经 `storage` 事件写好的新 token，否则重读最新 refresh 重试一次
- ~~**`refresh_token` 存 localStorage 的 XSS 风险**（复审 3）~~ -> 批次 4 以 CSP 缓解（`script-src 'self'`）+ 存储收窄；**最终迁移（httpOnly Cookie）归 4.5**（用户 2026-08-28 决策），3.6 内不再视为必做阻塞项
- ~~**429 重试等待偏短**（批次 2 收口边角 1）~~ -> ✅ 批次 4 收口：`REFRESH_RETRY_DELAY_MS=5000` + `REFRESH_RETRY_JITTER_MS=500`，配合跨标签接管
- ~~**consume 的 `ResponseError` 判定仍偏宽**（批次 2 收口边角 2）~~ -> ✅ 2026-08-28 收尾修复：只认 `unknown command` 子串（大小写不敏感，覆盖旧版 `ERR unknown command` 与新版裸消息），`WRONGTYPE`/OOM 等其余 `ResponseError` 原样抛出 -> 503；测试 `test_refresh_consume_does_not_fallback_to_lua_on_other_response_errors` 钉住（后端 4243 passed）
- **`init_admin_data.py` 硬编码初始密码**（批次 4 审计登记）：初始超管密码为脚本内固定值，随 4.6 密码策略一并处理
- **docker-compose 硬编码密钥**（批次 4 审计登记）：compose 文件中仍有写死的 SECRET_KEY 类变量，部署前须换环境变量注入（与 P0 部署遗留合并跟踪）

---

## 八、批次 2 实施记录（2026-08-28）：3.7 短 access token + 可吊销 refresh token

### 8.1 改造概览

| 项 | 改动 | 验证 |
|----|------|------|
| access token 缩短 | 24h -> `JWT_ACCESS_EXPIRATION_MINUTES`（默认 30 分钟），`JWT_EXPIRATION_HOURS` 配置项删除 | `test_access_token_default_ttl_is_short` |
| RefreshTokenService | [security.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/core/security.py)：Redis 存 `refresh:{sha256(token)}` -> `{user_id, tv, issued_at}`，TTL `JWT_REFRESH_EXPIRATION_DAYS`（默认 7 天）；issue/consume(GETDEL)/restore(NX 写回)/revoke/acquire_lock(SET NX EX 5)；fail-closed 503，`socket_connect_timeout=1.0` | 服务行为经路由端到端测试覆盖 |
| `POST /refresh` 路由 | [auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py)：短锁 -> GETDEL 原子消费 -> 用户存在/未禁用/tv 一致校验 -> 签发新 access + 新 refresh；非 401 失败 NX 写回旧值（用户可重试）；锁 finally 释放 | 轮换/一次性重放/429 并发锁/tv 失效/禁用/503 共 7 项测试 |
| logout 吊销 refresh | 鉴权形态改变：不再强制 Bearer 依赖，body 可带 `access_token`/`refresh_token`（清理型吊销：token 已过期/无效时跳过对应分支不报错，Redis 不可用 503）。**否则短 access 过期后 refresh 会"复活"已登出会话，3.5 单会话登出语义被 3.7 打穿** | `test_logout_with_refresh_token_revokes_refresh_session` / `test_logout_without_redis_still_returns_503`；既有 Bearer-only logout 测试保持通过（向后兼容） |
| memories `?token=` 收口 | [memories.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/memories.py)：auto-save 的 query token 从裸 `verify_token` 改为 `security.resolve_user_from_token`（完整校验：签名/状态/tv/jti），登出或改密后 URL 中旧 token 不再写入记忆 | `test_resolve_user_from_token_enforces_jti_and_tv`（批次 1 遗留边角 1 关闭） |
| 前端 refresh_token 持久化 | [authSlice.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/store/slices/authSlice.ts)：`persistAuth`/`clearPersistedAuth` 处理 `refresh_token` | `authSlice.test.ts` 新增断言 |
| 前端 401 自动刷新 | [api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts)：响应拦截器 401 -> single-flight 调 `/refresh`（独立 axios 实例，防递归）-> 更新 localStorage -> 重放原请求（`_retriedAfterRefresh` 防循环）；刷新失败回退原"清存储跳 /login"；`AUTH_PUBLIC_ENDPOINTS` 加入 refresh 端点 | tsc + 既有拦截器相关测试回归 |
| 前端登出走后端吊销 | 新增 `performLogout` thunk（best-effort 调 logout API 后必清本地），6 个页面 `dispatch(logout())` -> `dispatch(performLogout())` | tsc 通过（3 页面补 `useDispatch<AppDispatch>`） |

### 8.2 会话机制全景（批次 2 后）

| 操作 | 机制 | 影响范围 |
|------|------|---------|
| 改密/重置/禁用 | `token_version += 1` | 所有设备（access + refresh 同步失效） |
| 登出 | jti 黑名单 + refresh 删除 | 当前会话（access 立即失效，refresh 不可再换票） |
| access 过期（30 分钟） | 前端拦截器静默 refresh | 用户无感续期（7 天滑动窗口） |
| refresh 使用一次 | GETDEL 原子消费 | 旧 refresh 重放即 401（轮换制） |

### 8.3 TDD 过程记录

| 步骤 | 结果 |
|------|------|
| RED：11 项新测试（轮换 x1、含新字段 x2、锁 x1、tv x1、禁用 x1、未知 token x1、503 x1、logout 吊销 x2、30 分钟 TTL x1、resolve_user x1） | 11 项按预期失败（refresh_token 字段缺失/路由不存在/配置项不存在），既有 63 项保持通过 |
| GREEN：config + RefreshTokenService + /refresh + logout + memories + schemas | `test_auth_routes` + `test_oauth_alipay` 60 passed |
| 全量回归 | **74 passed**（63 既有 + 11 新增） |
| 前端 | `tsc --noEmit` 通过；`authSlice` + `websocket` 测试 8 passed |
| 复审 RED（见 8.6）：consume 异常分类 | `test_refresh_consume_does_not_fallback_to_lua_on_connection_error` 按预期失败（复现"真实 503 被误判为 token 不存在 -> 401"） |
| 复审 GREEN + 回归 | **77 passed**（74 + 3 新增）；前端 `apiRefresh` + `authSlice` + `websocket` 13 passed |

**测试基建适配**：
- `test_auth_routes.py`：新增 `FakeRefreshService`（内存实现：哈希存取/GETDEL 语义/NX 写回/锁/fail_redis 开关），`build_test_client` 注入 `security.refresh_token_service`
- `test_oauth_alipay.py`：新增简版 `FakeRefreshService`（仅 issue），`build_test_client` 注入--**避免 OAuth callback 测试经 `build_token_response` 连真实 Redis**（批次 1 踩坑教训的预防性处理）
- `build_token_response` 及两个 OAuth handler 改 async（签发 refresh 需异步 Redis），既有测试同步调用点改 `asyncio.run`

### 8.4 踩坑记录（重要）

- **PowerShell 批量替换损坏文件编码**：用 `Get-Content -Raw` + `Set-Content` 批量改 6 个页面时，PowerShell 按系统 GBK 误解码 UTF-8 文件再写回，导致中文注释乱码 + 行合并（318 行损坏）。**处置**：先用脚本双重验证 diff 中全部 318 个"+"行均为损坏行或目标修改（0 行用户独立改动，确认损坏前文件 == HEAD），再 `git checkout --` 恢复 6 个文件，改用 SearchReplace 工具重做（编码安全）。**教训：Windows 下批量改含中文文件一律用专用编辑工具，不用 PowerShell 管道重写**
- 并行 SearchReplace 同文件两处修改存在写入竞争（UserCenterPage 的 import 替换被后一次写入覆盖）：同文件多处修改应串行执行，改完须 `git grep` 复核
- `test_oauth_alipay.py` 的 callback 测试原先不注入任何 Redis fake：批次 2 前 `build_token_response` 是纯同步无 Redis 依赖，改 async 签发后该缺口暴露，测试环境若本机 Redis 可用会**静默污染真实 Redis**（写入 7 天 TTL 的 refresh key），已通过注入 fake 堵住

### 8.5 资源使用情况

| 类别 | 清单 |
|------|------|
| 依赖 | 无新增（Redis 复用 `redis` 6.4.0） |
| 后端文件变更 | `config.py`（JWT_ACCESS_EXPIRATION_MINUTES/JWT_REFRESH_EXPIRATION_DAYS 替换 JWT_EXPIRATION_HOURS）、`core/security.py`（RefreshTokenService + resolve_user_from_token + create_access_token 短 TTL + build_token_response async 签发 refresh）、`api/v1/auth.py`（/refresh 路由 + logout 双形态吊销）、`api/v1/memories.py`（query token 收口）、`schemas/user.py`（TokenResponse.refresh_token + RefreshTokenRequest/Response + LogoutRequest）、`services/oauth_service.py`（两个 handler 改 async） |
| 测试文件变更 | `test_auth_routes.py`（FakeRefreshService + 11 项新测试 + build_token_response 测试适配）、`test_oauth_alipay.py`（简版 FakeRefreshService 注入） |
| 前端文件变更 | `services/api.ts`（getStoredRefreshToken/refreshAccessToken single-flight/tryRefreshAndRetry 拦截器/logout body）、`store/slices/authSlice.ts`（refresh_token 持久化 + performLogout thunk）、6 个页面（登出改 performLogout，3 个补 AppDispatch 类型） |
| 前端测试 | `store/slices/__tests__/authSlice.test.ts`（refresh_token 持久化/清理断言） |
| 配置模板 | `backend/.env.example`（2 个 JWT 新变量替换旧 24h 配置） |
| 文档 | 架构文档（3.7 状态 + 1.5 路由表 + 6.2/6.3 总览）、本日志（批次 2 章节） |

### 8.6 批次 2 复审修复（2026-08-28，用户对照审查后）

| 项 | 问题 | 处理 | 验证 |
|----|------|------|------|
| 修1 | `RefreshTokenService.consume` 把 `getdel` 任意异常当"旧 Redis"回退 Lua：连接/超时/权限错误也会落到 Lua，真实 Redis 故障被误判为"token 不存在"-> 401 踢用户 | `consume` 仅对 `redis.exceptions.ResponseError`（< 6.2 无 GETDEL 命令）回退 Lua 原子 GET+DEL，其余异常直接 503（fail-closed）；`import redis.exceptions` 提到模块顶部 | `test_refresh_consume_does_not_fallback_to_lua_on_connection_error`（RED 复现：连接错误时 eval 被调用且不抛 503 -> 修复后 503 + eval 不被调）、`test_refresh_consume_falls_back_to_lua_on_unknown_command`（ResponseError 仍回退） |
| 修2 | 前端 refresh 成功只写 localStorage，没同步 Redux `state.token`：axios 读 localStorage 能过，但 store 状态分叉（App.tsx 的 token effect 等读旧值） | authSlice 新增 `tokensRefreshed` action；api.ts `attemptRefresh` 成功后回调 `tokenRefreshListener`；store.ts 注册监听 dispatch（回调注入避免 api -> store -> authSlice -> api 循环依赖） | `authSlice.test.ts::tokensRefreshed updates state.token`、`apiRefresh.test.ts::refreshes tokens ... notifies listener` |
| 修3（登记） | `refresh_token` 存 localStorage，XSS 可偷 7 天会话 | 不改代码：登记为 **3.6 必做项**（refresh_token 迁出 localStorage / httpOnly Cookie），文档 3.6 方案加第 6 条 | 架构文档 3.6 + 遗留事项同步 |
| 修4（部分） | 多标签页无共享刷新锁：A 页消费后 B 页旧 refresh 401 整站掉线；单飞只覆盖同页 | 本轮给前端 429 做一次短回退重试（`REFRESH_RETRY_DELAY_MS=400`，等待后端 5 秒锁释放）；`BroadcastChannel`/`storage` 同步与 Cookie 迁移归 3.6 | `apiRefresh.test.ts::retries once after 429`；遗留事项登记 |
| 修5 | 架构文档 3.7 示例仍"GETDEL 后 except 无差别写回"，与现网"401 不写回"不一致，会误导后续改码 | 3.7 示例重写为与现网一致（401 不写回 / 非 401 才 NX 写回 / consume 异常分类），附 3 条关键语义说明 | 文档同步 |
| 修6 | 无测试覆盖"issue 失败 -> restore 后旧 refresh 仍可用"（防掉线核心分支） | FakeRefreshService 加 `fail_issue` 开关；新增路由级测试 | `test_refresh_issue_failure_restores_old_refresh`（503 后重试旧 refresh 仍 200） |

**复审后测试**：后端 74 -> **77 passed**；前端 `apiRefresh`（4）+ `authSlice`（3）+ `websocket`（6）= **13 passed**，`tsc --noEmit` 通过。

---

## 九、批次 4 实施记录（2026-08-28）：3.9 RBAC/越权防护 + 3.6 XSS 防护与前端安全基线

### 9.1 3.9 RBAC 初始化与越权防护

| 项 | 改动 | 验证 |
|----|------|------|
| 默认角色/权限 seed | [seed_default_roles_permissions.py](file:///c:/Users/cuigu/novel_writing_agent/backend/alembic/versions/seed_default_roles_permissions.py)：幂等预置 3 角色（super_admin/admin/user）+ 11 权限 + admin 关联 7 权限（user:read/user:write/role:read/log:read/log:export/stats:read/system:read），按唯一 code 检查插入；downgrade 为 pass | `alembic upgrade head` 在 PG 执行成功；临时脚本核验 3 角色/11 权限/7 关联后删除 |
| 迁移链修正 | `down_revision` 由 `add_admin_rbac`（链上早期节点，已被 merge 点并入）改为真实 head `add_user_token_version`，否则形成旁支双 head | `alembic heads` 收敛为单 head |
| 提权防护 | [users.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/admin/users.py)：`_resolve_assignable_roles` 禁止普通 admin 分配 super_admin，创建用户/修改角色/重置密码三处接入 | `test_admin_user_points_routes.py` 3 项（403 + 过滤断言） |
| query 升权 | [query.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/admin/query.py)：`execute_query` 从 `require_admin` 升为 `require_super_admin`；顺带修复路由双前缀 404（`/admin/admin/query` -> `/admin/query`） | 2 项测试（普通 admin 403、路由可达） |

**决策记录（用户确认）**：① 首超管维持 `init_admin_data.py` 脚本创建，不做"首个注册用户自动超管"；② 注册用户默认无角色；③ 提权修复仅禁 admin 分配 super_admin。审计登记：`init_admin_data.py` 硬编码初始密码随 4.6 处理。

### 9.2 3.6 XSS 防护与前端安全基线

| 项 | 改动 | 验证 |
|----|------|------|
| CSP + 安全头 | 三份 nginx 配置：`nginx-prod.conf`（443 块补全被 `add_header` 继承规则吞掉的 4 个安全头——原只发 HSTS，属现网隐患修复；`/login/callback` 补 HSTS + CSP；静态资源与 `/health` location 各补完整集合）、`nginx-dev.conf`（server 级 4 头 + CSP，connect-src 额外放行 `http://127.0.0.1:8000`，HTTP 不加 HSTS）、`frontend/frontend.nginx.conf`（3 个自带 Cache-Control 的 location 各重复完整集合）。均注释"自带 add_header 的 location 必须重复完整集合" | 配置语法走查；部署后需 `curl -I` 抽查响应头（部署验证项） |
| CSP 白名单依据 | 前端取证：零硬编码外域；外域仅后端下发资源 `*.aliyuncs.com`（音色/资产预览/音效库 302）与演示封面 `picsum.photos`；MUI/Emotion 需 `style-src 'unsafe-inline'`；无外部字体/Worker；WS 同源（CSP3 下 `'self'` 匹配同域 wss） | 子代理全站扫描 + grep 复核 |
| 存储收窄 | [authSlice.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/store/slices/authSlice.ts)：`persistUser` 只写 id/username/full_name/avatar_url/is_active/时间戳/roles，**email/phone 不落 localStorage**；由 App.tsx `getCurrentUser` 刷新补全（使用处均有 `|| username`/`'暂无'` 兜底） | `authSlice.test.ts` 持久化裁剪断言 |
| token 不进 URL | [WorkflowControlPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/WorkflowControlPage.tsx)：`beforeunload` 自动保存由 `sendBeacon + ?token=` 改为 `fetch keepalive + Authorization` 头（后端 `auto_save_memory` 已支持 header + query 双通道，无需后端改动） | tsc + 全量前端测试 |
| 多标签刷新收口（批次 2 边角 1） | [api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts)：`REFRESH_RETRY_DELAY_MS` 400 -> 5000（对齐后端锁 TTL）+ `REFRESH_RETRY_JITTER_MS=500` 抖动；等待后若 storage 中 access_token 已变化（另一标签完成轮换）直接接管并通知 listener，不再打后端，否则重读最新 refresh 重试一次；新增 `startCrossTabTokenSync`（`storage` 事件，仅 `access_token` 键），`store.ts` 注册 listener 时启动 | `apiRefresh.test.ts` 8 项（含跨标签接管、假 window 的 storage 事件派发/忽略/注销） |

### 9.3 TDD 与回归

| 步骤 | 结果 |
|------|------|
| 3.9 RED -> GREEN | 5 项新测试先失败后通过；后端 77 -> **82 passed** |
| 3.6 前端 | `apiRefresh.test.ts`（8）+ `authSlice.test.ts`（3）通过；`tsc --noEmit` 通过 |
| 全量回归 | 后端 **4242 passed**（12 skipped）；前端 **923 passed**（173 文件） |
| 回归中发现并修复的两处既有失败 | ① `test_expand_story_repair_score_persistence.py` raw SQL 插 users 缺 `token_version`（批次 2 加 NOT NULL 列的遗漏，补列修复）；② `completionStepSource.test.ts` 源码断言用裸 `\n`，Windows autocrlf 检出 CRLF 致匹配失败（HEAD 既有，与本批无关，读取时 `\r\n -> \n` 归一化修复） |

### 9.4 收尾修复（2026-08-28，批次 2 边角 2）

- [security.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/core/security.py) `consume`：Lua 回退判定由宽泛的 `ResponseError` 收紧为只认 `unknown command` 子串（`str(exc).lower()`，覆盖旧版 `ERR` 前缀）；`WRONGTYPE`/OOM 等其余服务端错误原样抛出 -> 外层转 503，不再误判为"token 不存在"踢用户
- TDD：新增 `test_refresh_consume_does_not_fallback_to_lua_on_other_response_errors`（RED：WRONGTYPE 走 Lua 返回 None 不抛错 -> GREEN：503 且不进 Lua）；后端全量 **4243 passed**

### 9.5 遗留

- refresh token 仍在 localStorage：CSP 缓解中，httpOnly Cookie 归 4.5
- `init_admin_data.py` 硬编码初始密码（随 4.6）；docker-compose 硬编码密钥（随部署）
- nginx 新安全头与 CSP 需上线后 `curl -I` 抽查（部署验证项，注意继承规则：改任何带 add_header 的 location 必须同步完整集合）
- `persistUser` 仍持久化 roles（非 PII、后端兜底鉴权，仅影响前端展示，评审判可接受，维持现状）

### 9.6 评审修复（2026-08-28，用户评审后实施，TDD）

| 项 | 问题 | 处理 | 验证 |
|----|------|------|------|
| OAuth consume 同构坑 | [auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py#L380-L413) `OAuthPendingRegistrationService.consume` 用 `except Exception` 全吞 getdel 异常进 Lua：连接失败/WRONGTYPE/OOM 落到 Lua，Lua 返回空 -> 路由误判"票据过期"400，用户已 OAuth 成功却卡在确认页（与批次 2 修掉的 refresh 同构） | 收紧为与 refresh 一致：仅 `redis.exceptions.ResponseError` 且含 `unknown command` 才回退 Lua，其余原样抛出 -> 503（fail-closed） | `test_oauth_consume_does_not_fallback_to_lua_on_connection_error`、`test_oauth_consume_does_not_fallback_to_lua_on_other_response_errors`（RED -> GREEN） |
| confirm 建号失败无 restore | `/oauth/confirm` GETDEL 消费后直接建号，`create_confirmed_user`/签发 token 失败时票据已删，用户只能重走 OAuth（refresh 路径已有 NX 写回） | `OAuthPendingRegistrationService.restore`（NX 写回，TTL 600s）；路由建号段包 try/except，**非 400** 失败写回后 re-raise（400 客户端错误——无效 provider/空 openid——不写回，坏票不得复活，与 refresh 的"401 不写回"一致）；cancel 与成功路径不写回 | `test_oauth_confirm_restores_ticket_on_user_creation_failure`（建号抛错 -> 票据写回 -> 重试成功；TestClient raise_server_exceptions 下用 pytest.raises）、`test_oauth_confirm_does_not_restore_invalid_provider_ticket`（400 后票据不写回） |
| 跨标签登出不同步（批次 2 边角 3） | `startCrossTabTokenSync` 忽略 `newValue===null`：A 标签登出后 B 标签内存 token + 残留 refresh 在 access 过期后把会话救回来 | [api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts#L1703-L1715) 新增 `tokenLogoutListener`/`setTokenLogoutListener`，`access_token` 移除时派发；[store.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/store/store.ts) 注册 dispatch `logout` | `apiRefresh.test.ts` 登出用例（newValue=null 触发 logout、非 access_token 键不触发） |
| 已注册邮箱仍真实发码 | `/register/send-code` 不查邮箱是否已注册，已注册邮箱也发码（对已有用户的邮件轰炸/钓鱼面） | 加 db 依赖，限流后查存在性，已存在跳过 issue_code/发信，响应仍统一 200 同文案（防枚举语义不变） | `test_register_send_code_unified_response_for_registered_email` 断言改为"未发信"；`test_register_duplicate_email_returns_unified_message` 改为竞态场景（发码后、confirm 前被占用） |
| OAuthStateService.consume 同构坑（第三处） | [auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py#L123-L152) `OAuthStateService.consume` 对 getdel 仍是裸 `except Exception` 走 Lua：Redis 抖动时连接错误落 Lua，Lua 返回空 -> 路由误判"无效的登录状态"400，用户需重新点授权 | 与 refresh/pending 同一套 `unknown command` 判定（`redis.exceptions.ResponseError` + 子串小写匹配），其余原样抛出 -> 503 | `test_oauth_state_consume_does_not_fallback_to_lua_on_connection_error`、`test_oauth_state_consume_does_not_fallback_to_lua_on_other_response_errors`（RED -> GREEN） |

**回归**：后端全量 **4264 passed**（12 skipped）；前端 **924 passed** + `tsc --noEmit` 通过。

---

## 十、批次 3 实施记录（2026-08-28）：3.2 OAuth 首次建号确认 + 3.8 邮箱验证

### 10.1 决策记录（用户确认）

| 决策点 | 结论 |
|--------|------|
| 旧 `POST /register` | **直接删除**（两步注册硬切换，无兼容窗口） |
| 密码重置成功后 | 置 `email_verified=True`（解死锁：能收到重置邮件即证明邮箱归属，推荐方案） |
| `_record_consent` 同意记录 | **本批跳过**，登记到 4.3（YAGNI） |
| 存量数据 | 无存量用户（均为测试用户），迁移直接清洗假邮箱，不做兼容窗口 |
| 迁移策略 | 3.2 + 3.8 合并一次迁移：新增列 + email 放开非空一次完成，避免两次放开约束 |

### 10.2 后端改造概览

| 项 | 改动 | 验证 |
|----|------|------|
| DB 迁移 | [add_email_verification_nullable_email.py](file:///c:/Users/cuigu/novel_writing_agent/backend/alembic/versions/add_email_verification_nullable_email.py)：`down_revision=seed_default_roles_permissions`；upgrade 新增 `email_verified`（server_default false）/`email_verified_at` + 清洗 `*@alipay.temp`/`*@wechat.temp` -> NULL + email 放开非空；downgrade 反向 | 单 head；upgrade -> downgrade -> upgrade 双向验证通过 |
| 模型 | [user.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/models/user.py)：`email` 可空、`email_verified` 加 `server_default=false()`（兼容存量原始 SQL INSERT 测试） | 全量回归 1 failed -> 4264 passed |
| 两步注册 | [auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py)：删旧 `/register`；`POST /register/send-code`（IP + 邮箱哈希双维限流，防枚举统一 200）-> `POST /register/confirm`（6 位验码建号，建号即 `email_verified=True`） | 定向路由测试 |
| 登录态邮箱验证 | `POST /verify-email/request-code` + `POST /verify-email/confirm`（验码 + 邮箱占用检查 + merge/refresh 回写） | `test_verify_email_flow_marks_user_verified` 等 |
| OAuth 建号票据 | [auth.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/auth.py) `OAuthPendingRegistrationService`：`oauth:pending:{ticket}` SETEX TTL 600s，`secrets.token_urlsafe(32)`，consume GETDEL + Lua 回退，全程 fail-closed 503；openid 不进浏览器 | 票据一次性/过期/503 测试 |
| callback 联合响应 | 两个 callback 返回 `{status: 'ok'\|'new_user', registration_ticket?, token?}`；老用户直接 token，新用户返回票据不自动建号；`POST /oauth/confirm` 确认/取消（取消也消费票据） | `test_oauth_alipay` / 微信同构 |
| oauth_service | [oauth_service.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/oauth_service.py)：handler 返回 `Optional[User]`（无匹配返 None 不建号）；微信 **unionid 优先**匹配 + 回写最新 openid；`create_confirmed_user` email=None 不再分配假邮箱，并发双确认兼容 + IntegrityError 兜底 | 既有 OAuth 测试适配后通过 |
| 验证码服务 | `EmailVerificationService`：code 哈希存储，TTL 600s / 重发间隔 60s / 最多 5 次尝试（`EMAIL_VERIFY_*` 4 项配置）；[email_service.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/email_service.py) 新增验证码邮件模板（紫色渐变）；非 DEBUG 未配邮件 -> 503 | fail-closed / 限流测试 |
| 重置链路联动 | request-code 跳过无邮箱用户；重置成功后置 `email_verified=True` + `email_verified_at` | 重置测试断言 |
| `/me` 加固 | 注入 `get_db`，按 `current_user.id` 用 `joinedload(User.roles)` 重查（修复脱离会话实例惰性加载 roles 报 DetachedInstanceError，生产同受益） | 全链路验证邮箱测试通过 |

### 10.3 前端改造概览（对齐后端契约）

| 文件 | 改动 |
|------|------|
| [api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts) | `AUTH_PUBLIC_ENDPOINTS` 替换（旧 register -> send-code/confirm/oauth-confirm）；`register()` 拆为 `registerSendCode`/`registerConfirm`；新增 `oauthConfirmRegistration`/`verifyEmailSendCode`/`verifyEmailConfirm`；两个 callback 返回类型 `OAuthCallbackResponse` 联合响应 |
| [authSlice.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/store/slices/authSlice.ts) | `User.email` 可空 + `email_verified`；`RegisterPayload` 加 `code`；新增 `sendRegisterCode`/`confirmOAuthRegistration` thunk；`alipayLogin`/`wechatLogin` 归一化联合响应（new_user 时暂存 `pendingRegistrationTicket` 不置登录态） |
| [RegisterPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/RegisterPage.tsx) | 三步改为「填写信息 -> 邮箱验证 -> 完成」：第一步校验通过后先发码，成功才进步；验证码输入（仅数字 6 位）+ `resend_in` 驱动的重发倒计时 |
| [LoginCallbackPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/LoginCallbackPage.tsx) | new_user 分支：首次第三方登录确认建号卡片（确认 -> `/home`；取消 -> 消费票据后回 `/login`）；票据过期/无效展示错误回登录页 |
| [UserCenterPage.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/UserCenterPage.tsx) | 账户信息卡片邮箱行展示验证状态 Chip（已验证/未验证）+ 未验证提示文案 |

### 10.4 TDD 与回归

| 步骤 | 结果 |
|------|------|
| RED：新增批次 3 测试（注册两步/邮箱验证/oauth 确认） | 按预期失败（路由不存在/字段缺失） |
| GREEN：迁移 + 模型 + schemas + config + EmailVerificationService + auth.py + oauth_service | 定向 **78/78** 通过 |
| 全量回归 | **4264 passed, 5 skipped**（4243 -> 4264；中途修复 1 项：存量原始 SQL INSERT 缺 `email_verified` -> 模型补 `server_default=false()`，与迁移口径一致） |
| 迁移验证 | `alembic heads` 单 head；upgrade/downgrade/upgrade 全部成功，本地 PG 停在 head |
| 前端 | `tsc --noEmit` 通过；**923 passed**（173 文件，含 `authSlice.test.ts`/`apiRefresh.test.ts`） |

### 10.5 踩坑记录

- **DetachedInstanceError**：测试 harness 的 `override_get_current_user` expunge 用户后实例脱离会话，`/me` 的 `model_validate` 触发 roles 惰性加载报错；把写回改 `db.merge`+`refresh` 无效（问题在 `/me` 本身）。最终改为 `/me` 注入 `get_db` 按 id `joinedload` 重查，生产同样受益。教训：先定位报错发生的调用点，不要只改“可疑的上一环”
- **新 NOT NULL 列与原始 SQL INSERT**：存量测试用裸 SQL `INSERT INTO users (...)` 不含新列，模型仅给 `default` 无效，必须 `server_default=false()` 与迁移口径对齐（批次 2 `token_version` 同类问题重演）
- **SearchReplace Unicode 近似字符误伤**：替换时把“兜底”写成“兑底”（\u515c≠\u5151）、半角引号变全角，两次回改修复。教训：含中文注释的替换块需逐字核对转义

### 10.6 遗留事项（登记）

- `_record_consent` 同意记录登记到 **4.3**（本批跳过，YAGNI）
- Redis pending 中的原始 openid 为明文短存（TTL 10 分钟），**4.1（openid 加密存储）落地后改密文**
- 登录态邮箱换绑的完整前端入口（`verify-email/*` 接口已就绪，前端仅展示验证状态）按需后续接入，后端接口已带鉴权可直接复用

---

> **维护说明**：本日志随 P1 各批次推进持续追加。批次 1（含复审修复）、批次 2（3.7）、批次 4（3.9 + 3.6）、批次 3（3.2 + 3.8）均已完成，P1 列表内编号已全部落地；后续项见架构文档第四/五章（P2/4.x）。
