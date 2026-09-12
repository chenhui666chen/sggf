# 登录系统 P2 落地实施记录

> **关联文档**：[LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md](./LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md)、[LOGIN_SYSTEM_P0_IMPLEMENTATION_LOG_20260825.md](./LOGIN_SYSTEM_P0_IMPLEMENTATION_LOG_20260825.md)、[LOGIN_SYSTEM_P1_IMPLEMENTATION_LOG_20260827.md](./LOGIN_SYSTEM_P1_IMPLEMENTATION_LOG_20260827.md)
> **实施范围**：P2（4.1–4.6）；第五章合规项（5.2–5.6）不在本日志默认范围内，4.3 会碰到同意记录/注销时再交叉引用
> **实施方式**：按批次推进（待用户确认起步批次），TDD RED->GREEN
> **开篇日期**：2026-08-31
> **结论**：P0（2.1–2.6）与 P1（3.1–3.9）均已落地并经复审收口，**可以进入 P2**。本日志开篇时 4.1–4.6 均未实施；截至 2026-09-01，**4.1（批次 A）、4.2 + 4.6（批次 B）、4.5（批次 C）、4.3 + 4.4（批次 D）全部完成**，P2 收口。

---

## 一、进入 P2 的前置结论

| 优先级 | 范围 | 状态 | 依据 |
|--------|------|------|------|
| **P0** | 2.1–2.6 | ✅ 完成（2026-08-25，含复审收尾） | [P0 实施记录](./LOGIN_SYSTEM_P0_IMPLEMENTATION_LOG_20260825.md)：后端 49 项相关测试通过 |
| **P1** | 3.1–3.9 | ✅ 完成（2026-08-27/28，含评审修复） | [P1 实施记录](./LOGIN_SYSTEM_P1_IMPLEMENTATION_LOG_20260827.md)：批次 1–4 全完成；Redis GETDEL 三处（refresh / pending ticket / OAuth state）判定已对齐；confirm 400 不写回 |

P1 明确推迟到 P2 的项：

- **4.5**：refresh_token 仍在 localStorage，CSP 只是缓解；httpOnly Cookie 是认证模型切换
- **4.6**：init_admin_data.py 硬编码初始超管密码
- **4.3**：批次 3 跳过的同意记录（YAGNI，登记到 5.2）

部署遗留（不阻塞开 P2 代码，但上线前仍有效）：Redis 高可用、APP_ENV=production 实启、alembic upgrade head、后端不得绕过 nginx 对公网暴露、docker-compose 硬编码密钥换环境变量、CSP 上线后 curl -I 抽查。

---

## 二、P2 总览（开篇）

| P2 编号 | 改造项 | 状态 | 依赖 / 风险 | 建议批次 |
|---------|--------|------|-------------|----------|
| 4.1 | openid 确定性查找哈希 + 加密存储 | ✅ 完成（2026-08-31，批次 A） | 迁移 + 双密钥；lookup key 轮换极痛；须 UNIQUE hash | 批次 A（数据面，可独立） |
| 4.2 | 账户绑定与解绑 | ✅ 完成（2026-08-31，批次 B） | 依赖 3.2 票据/无邮箱用户；须保证至少一种登录方式 | 批次 B（账户能力） |
| 4.3 | 用户数据权利 API | ✅ 完成（2026-09-01，批次 D） | 导出/注销冷静期；同意记录交叉 5.2/5.3 | 批次 D（合规批） |
| 4.4 | 审计日志（脱敏） | ✅ 完成（2026-09-01，批次 D） | 登录链路埋点；禁存验证码/token/openid/email/phone | 批次 D（横切小批） |
| 4.5 | 认证模型迁移（httpOnly Cookie） | ✅ 完成（2026-09-01，批次 C） | 前置已满足：2.5 token_version、CORS 白名单、3.7 refresh；需 staging 全回归 + CSRF | 批次 C（认证模型，单独、最后） |
| 4.6 | 密码策略与账户锁定 | ✅ 完成（2026-08-31，批次 B） | 含初始超管密码；历史密码独立 pepper，不可复用 password_hash | 批次 B（与 4.2 密码设置相邻） |

**建议顺序（用户 2026-08-31 确认按此推进）**：

1. **批次 A**：4.1（+ 可选 4.4）。纯后端/数据，不改登录交互。 ✅ 2026-08-31 完成（未带 4.4）
2. **批次 B**：4.6 + 4.2（+ 4.3 若要一起做权利 API）。账户能力与密码策略。 ✅ 2026-08-31 完成（未带 4.3，4.3 拆独立合规批）
3. **批次 C**：4.5 Cookie 迁移。认证模型切换，必须单独、staging 回归。 ✅ 2026-09-01 完成
4. **批次 D**：4.3 + 4.4（合规批）。数据权利 API + 脱敏审计。 ✅ 2026-09-01 完成（含 5.2 同意记录表、5.3 冷静期/匿名化衔接）

不要把 4.5 和 4.1 捆在同一发布：Cookie 切换已经够大，openid 加密迁移失败面不同。

---

## 三、从 P0/P1 继承、实施时必须带上的约束

| 来源 | 约束 |
|------|------|
| P1 3.7 / 评审 | Redis consume：仅 unknown command 回退 Lua，其余 503；失败写回仅非客户端错误（refresh 401 / confirm 400 不 restore） |
| P1 3.2 | OAuth 用户 email 可空；绑定/解绑不得逼用户造假邮箱 |
| P1 3.6 | XSS 窗口仍在，直到 4.5；Cookie 方案用 __Host- + Secure + SameSite |
| P1 3.8 | 两步注册 / 验邮已存在，4.6 锁定计数不要和注册发码限流抢同一 Redis key 语义 |
| 架构 4.1 | 禁止用带随机 nonce 的密文做等值查询；hash UNIQUE；lookup key 与 encryption key 分离 |
| 架构 4.5 | CSRF 双重提交必须绑会话；OAuth 回跳时 Lax/Strict cookie 可能不一致 |
| 架构 4.6 | 密码历史只能用独立 pepper 的哈希，不能复用登录 password_hash |
| P1 审计 | init_admin_data.py 初始密码随 4.6 改掉 |

---

## 四、批次记录（实施后追加）

### 批次 A：4.1 openid 确定性查找哈希 + 加密存储（2026-08-31）

**范围**：4.1 全项 + P1 遗留的"Redis pending 内 openid 明文"。不含 4.4（用户未勾选）。

#### 决策记录（用户 2026-08-31 确认）

| 决策 | 结论 |
|------|------|
| 起步批次 | 批次 A（4.1），不含 4.4 |
| 明文字段列 | **硬切换**：迁移内回填后立即 `drop`，无兼容窗口，回滚走 `downgrade`（沿用 P1"无存量真实用户"决策） |
| Redis 待建号票据 | 顺带改密文（P1 遗留明确"4.1 落地后改密文"） |

其余沿用架构文档 4.1 约束：hash 列 **UNIQUE**（防并发建号重复）、lookup key 与 encryption key 严格分离。

#### 改造明细

| 文件 | 改动 |
|------|------|
| `backend/app/core/crypto.py`（新增） | `OpenIDCrypto`（HMAC-SHA256 `lookup_hash` / Fernet `encrypt` / `decrypt`）；`build_openid_crypto()` 按配置构造（未配置返回 `None`，格式错误快速失败并给出生成命令）；单例 `openid_crypto` + `get_openid_crypto()` |
| `backend/app/core/config.py` | 新增 `OPENID_LOOKUP_KEY` / `OPENID_ENCRYPTION_KEY`（默认空） |
| `backend/app/models/user.py` | 3 个明文字段列 → 6 列（`{field}_hash` `String(64)` UNIQUE index + `{field}_encrypted` `Text`） |
| `backend/app/services/oauth_service.py` | 新增 `_find_by_openid()`（按哈希等值查询）、`_sync_openid()`（哈希比对变更 + 成对写哈希/密文）；`_sync_external_user` / `create_confirmed_user` / `handle_alipay_login` / `handle_wechat_login` 全部改走哈希 |
| `backend/app/api/v1/auth.py` | 新增 `_ensure_openid_crypto()`（未配置 → 503，与 `_ensure_alipay_configured` 同构），接入 alipay/wechat callback 与 `/oauth/confirm`；callback 存票据时加密 openid/unionid；confirm 解密，不可解按"票据过期"400（不写回，坏票不复活） |
| `backend/app/main.py` | 生产/staging 启动强校验两把密钥（缺失即拒绝启动，避免上线后才发现 OAuth 链路 fail-closed 503） |
| `backend/alembic/versions/add_openid_encrypted_storage.py`（新增） | 加 6 列 → 存量明文回填哈希+密文 → 建 UNIQUE 索引 → 删 3 个明文列；`downgrade` 反向解密回明文列并恢复原索引。**回填依赖两把密钥，缺失直接中止迁移**（避免半加密状态） |
| `backend/.env.example` | 新增两个配置项与生成命令 |

#### TDD RED → GREEN

| 轮次 | RED（失败原因） | GREEN |
|------|----------------|-------|
| 1 | `test_openid_crypto.py` 8 例：`ModuleNotFoundError: app.core.crypto` | 实现 `crypto.py` + 配置项 → 8 passed |
| 2 | `test_auth_routes.py` 5 例：`User.alipay_openid_hash` 不存在 / confirm 未解密 | 模型 + service + 路由改造 → 86 passed（含既有用例同步为哈希/密文口径） |
| 3 | `test_oauth_alipay.py`：既有建号用例用明文构造 | 改为哈希+密文构造；新增票据密文用例 → 10 passed |

新增用例（12 例）：

- `test_openid_crypto.py`：哈希确定性/不可逆、换 lookup key 索引全变、密文非确定性（证明不可做等值查询）、加解密往返、异密钥不可解、未配置抛错、空配置返回 `None`、密钥格式错误快速失败
- `test_auth_routes.py`：建号后库中无明文列且密文不含明文、票据不可解→400 不写回、密钥缺失→503
- `test_oauth_alipay.py`：票据内 openid 为密文（非明文）且可解密还原

#### 回归数字

```
backend/tests/test_auth_routes.py               78 passed
backend/tests/test_oauth_alipay.py              10 passed
backend/tests/test_openid_crypto.py              8 passed
backend/tests/test_admin_user_points_routes.py   （同批通过）
backend/tests/test_application_openapi.py        （同批通过）
合计                                           117 passed
```

`rg '\b(alipay_openid|wechat_openid|wechat_unionid)\b'` 全仓扫描：生产代码仅剩 `oauth_service` 的**参数名/字段前缀**（内存中明文值，不落库）、旧迁移 `add_third_party_login_fields.py`（历史）、`auth.py` 传参（内存）；新迁移按字段前缀回填。

#### 遗留（本批新登记）

1. 已知与本次无关：`test_user_assets_routes.py` / `test_user_center_routes.py` / `test_user_center_billing_events.py` 共 11 例 503，根因是测试客户端每次请求 `asyncio.run()` 新建事件循环，而 `security.py` 的 Redis 异步客户端是模块级单例、跨循环复用即报"认证服务暂时不可用"（首个请求 200、第二个起 503，已用临时脚本复现并删除脚本）。既存问题，未在本批处理。
2. 密钥轮换脚本未接入 CI/运维流程：密钥更新后需人工执行脚本、同步部署环境配置并重启服务。

---

### 批次 A 追补（2026-08-31，同日）

用户审阅遗留项后追加三项：① username 改不可反推派生值；② 执行迁移；③ 实现密钥轮换脚本。

#### 追补 1：username 改为不可反推派生值

| 文件 | 改动 |
|------|------|
| `backend/app/services/oauth_service.py` | `_allocate_username` 由 `provider_{openid后12位}` 改为 `provider_{lookup_hash(openid)前12位}`（HMAC 片段，不可反推，同一 openid 仍稳定映射） |
| `backend/alembic/versions/add_openid_encrypted_storage.py` | upgrade 内回填存量 username（冲突按 `_N` 递增，与运行时同口径）；downgrade 在恢复明文列后按"明文后 12 位"还原旧 username，**完全可逆** |

之所以合并在同一迁移而非另开一个：`downgrade` 需要先恢复明文 openid 列才能重算旧格式 username；拆成两个迁移会让 username 回滚不可逆（哈希无法反推明文）。该迁移尚未执行，合并无副作用。

**TDD RED→GREEN**：RED 断言失败信息 `assert '001234567890' not in 'alipay_001234567890'`（直观证明泄露），改派生逻辑后 `test_auth_routes.py` 79 passed。

#### 追补 2：密钥轮换脚本

`backend/scripts/rotate_openid_keys.py`：

| 能力 | 说明 |
|------|------|
| `--new-encryption-key` | 加密密钥轮换：旧 key 解密 + 新 key 加密逐行重写 |
| `--rotate-lookup --new-lookup-key` | 查找哈希密钥轮换：**借密文列还原明文逐行重算**，因此"离线重算"可在线完成（拆成两步时才需真离线：两把密钥同时泄露） |
| 默认 dry-run | 写库必须显式 `--apply`；轮换失败整体回滚，不留半成品 |
| 一次只轮换一把 | 同时轮换会让中间态无法回滚 |
| username 不动 | 用户可见且可改的标识，派生自建号当时的 lookup key；轮换后新老用户名共存，唯一性由索引保证 |

新密钥可用 `--new-*-key` 或环境变量 `OPENID_ENCRYPTION_KEY_NEW` / `OPENID_LOOKUP_KEY_NEW` 传入（推荐后者，避免进 shell 历史）。

测试 `backend/tests/test_rotate_openid_keys.py`（4 例）：dry-run 不改数据、轮换后新 key 可解且旧 key 不可解、lookup 轮换重算全部哈希且 username 不变（含"一行同时有 openid 与 unionid 两个哈希都要重算"）、缺新密钥退出码 2。

#### 追补 3：测试隔离修复（过程中暴露）

新测试文件在模块导入期触发 `app.core.config` 加载，抢在 `test_auth_routes.py` 注入环境变量之前，`settings` 快照里没有密钥 → 单次运行 19 例连带失败（单独跑全绿）。根因是 `settings` 在首次导入时快照环境变量，测试密钥原先只在两个认证测试文件里注入，**存在执行顺序耦合**——按字母序跑全量时 `test_admin_*` 会先导入并"钉死"空配置。

修复：测试密钥统一注入 `backend/tests/conftest.py`（pytest 先于所有 test 模块加载），并移除两个认证测试文件里的重复注入。验证：`test_rotate_openid_keys.py + test_openid_crypto.py + test_oauth_alipay.py` 22 passed；`test_auth_routes.py` 79 passed。

#### 回归数字（追补后）

```
test_rotate_openid_keys.py    4 passed
test_openid_crypto.py         8 passed
test_auth_routes.py          79 passed（含新增 username 用例）
test_oauth_alipay.py         10 passed
```

---

### 批次 B：4.6 密码策略与账户锁定 + 4.2 账户绑定/解绑/设密（2026-08-31）

**范围**：4.6 全项（复杂度/锁定/历史/超管）+ 4.2（bind/unbind/set-password）。不含 4.3（拆独立合规批）、4.4、4.5。

#### 决策记录（用户 2026-08-31 确认）

| 决策 | 结论 |
|------|------|
| D1 锁定响应 | **A 静默 401**：锁定窗口内一切尝试（含正确密码）与"账号不存在/密码错误"同文案同状态码。理由：锁定若换文案/状态码，第 6 次响应变化即可枚举"存在且有本地密码"，比爆破本身更值钱。锁定价值 = 爆破上限压到每窗口 5 次；正确密码放行会让 4.6 退化为 3.1 的重复实现。**范围说明**：测试只断言响应 body/status 一致；"存在 vs 不存在"的 bcrypt 时序差异是 2.6 既有结构（先查库再 dummy），不声称时序级一致（评审 #1） |
| D2 锁定邮件 | 本批不做，`AccountLockoutService` 预留语义（路由在锁定分支直接 401，后续通知走 4.4/合规批，仅对 email 非空且已验证用户发，文案不指名攻击） |
| D3 同 provider 重绑 | **允许覆盖当前用户**；仅"被其他用户占用"409；绝不回落 existing login（P1 不做账号合并）；微信 openid+unionid 成对写，unionid 为空不清旧值 |
| D4 绑定流程 | **方案 1**：intent=bind 走现有 OAuth → callback 返回 `bind_pending` + `bind_ticket`（不发 token、不建号）→ 登录态 `/auth/bind/confirm` 消费写入。auth-url 阶段未登录即 401 |
| 解绑 | 成功递增 token_version（登录方式集合变化）；`login_method_count = 可用密码 + 绑定 provider 数`（微信 openid/unionid 算一种），≤1 拒绝 |
| set-password | 仅 `!has_usable_password_hash` 可走；成功 `tv += 1`（与改密/重置同构，旧 refresh 下次刷新 401，**不发明 revoke 辅助函数**）；`!oauth-disabled!` 占位哈希被替换 |
| 锁定与 3.1 并存 | 独立 key（`lockout:*` vs `rate:*`）；锁定仅对"存在 + 有可用密码 + 密码错误"计数；锁定窗口内失败不续期；成功登录清计数与标记；Redis 不可用 fail-closed 503 |

#### 改造明细

| 文件 | 改动 |
|------|------|
| `backend/app/core/password_policy.py`（新增） | `check_password_strength` / `validate_password_strength` + `PASSWORD_POLICY_ERROR_MESSAGE`（≥8 含大小写+数字，上限 50；下限走 `PASSWORD_MIN_LENGTH`） |
| `backend/app/schemas/user.py` | `UserCreate`（覆盖注册）/ `PasswordChange` / `PasswordResetConfirm` 三处校验收敛到策略函数；新增 `PasswordSetRequest`、`BindConfirmRequest`；`OAuthCallbackResponse` 增加 `bind_pending` / `bind_ticket` |
| `backend/app/schemas/admin.py` | `UserCreateByAdmin` 由 `Field(min_length=6)` 收敛到同一策略（补复杂度与上限，第 4 接入点） |
| `backend/app/core/security.py` | `INCR_WITH_TTL_LUA` 上移（限流/锁定共用）；新增 `AccountLockoutService`（is_locked / register_failure / clear）；`hash_password_for_history` 转发 |
| `backend/app/services/password_history_service.py`（新增） | 历史 HMAC（独立 pepper）+ `is_reused`（最近 3 条，含当前密码）+ `record`（追加+清理超限） |
| `backend/app/models/password_history.py`（新增） | 表结构（仅 64 位 HMAC 十六进制，绝不存 bcrypt/明文） |
| `backend/alembic/versions/add_password_history.py`（新增） | 建表 + 双索引（down_revision = add_openid_encrypted_storage） |
| `backend/app/api/v1/auth.py` | login 接入锁定（D1 语义 + 时序不跳过 bcrypt）；change/reset 接入历史检查；新增 `/set-password`、`/bind/confirm`、`/unbind/{provider}`；auth-url 支持 intent=bind（未登录 401，state 附带 user_id 线索）；callback bind 分支；`/me` 与登录响应改用 `build_user_response`（补 has_password / alipay_bound / wechat_bound） |
| `backend/app/main.py` | production/staging 启动强校验 `PASSWORD_HISTORY_PEPPER`（空或占位即拒绝） |
| `backend/app/core/config.py` | 新增 `PASSWORD_MIN_LENGTH` / `ACCOUNT_LOCKOUT_ATTEMPTS` / `ACCOUNT_LOCKOUT_MINUTES` / `PASSWORD_HISTORY_PEPPER` / `INITIAL_ADMIN_PASSWORD` |
| `backend/app/scripts/init_admin_data.py` | 去硬编码 `Admin@123456`：`resolve_initial_admin_password()`（env 优先；production/staging 缺省报错；development 随机打印一次仅 stdout）；"已有超管不覆盖"分支保持 |
| 前端 | `utils/passwordPolicy.ts`（新增，与后端同文案）；`RegisterPage` / `ForgotPasswordPage` / `UserCenterPage` 本地校验同步（含漏网的 ForgotPasswordPage 一处）；`UserCenterPage` security Tab 二态（改密 vs 设密）+ 第三方绑定/解绑 UI；`LoginCallbackPage` 增加 `bind_pending` 分支（消费后回 `user-center?tab=security`）；`api.ts` 新增 setPassword / bindConfirm / unbindProvider / intent；`authSlice` User 增加安全标记字段 |

#### TDD RED → GREEN（要点）

| 轮次 | RED | GREEN |
|------|-----|-------|
| 密码策略 | 策略模块缺失 → 既有弱密码夹具（`admin123`/`oldpass123` 等）批量 422，证明策略生效 | 策略函数 + 4 处 schema 接入；夹具升级为合规密码（仅首字母大写） |
| 锁定 | 第 5 次失败后正确密码仍 200 / OAuth 账户被计数 / 响应与不存在账号不一致 / Redis 挂无 503 | `AccountLockoutService` + login 接入；`FakeAccountLockoutService` + `UnboundedRateLimiter`（锁定测试需绕开 3.1 的 5/min 干扰） |
| 历史 | 注册无历史记录 / 改密可复用上一代 / 表内存 bcrypt | 模型+服务+迁移；注册/改密/重置接入；历史只存 64 位 HMAC |
| set-password | 404 | 端点 + tv+1 + 替换占位哈希 + 历史登记（旧 access 401、旧 refresh 刷新 401 断言） |
| bind/unbind | 404 | auth-url intent + callback bind 分支 + bind/confirm（409 冲突 / user_id 不符 400 / 票据一次性）+ unbind（≤1 拒绝 / 微信成对清 / tv+1） |
| init_admin | `resolve_initial_admin_password` 缺失 | env 优先 / production 报错 / development 随机 |

#### 回归数字

```
test_auth_routes.py        115 passed（锁定 5 + 策略 3 + 历史 4 + set-password 2 + bind/unbind 7 等新增）
test_oauth_alipay.py        11 passed（含 callback bind_pending）
test_password_policy.py     10 passed
test_init_admin_data.py      3 passed
test_rotate_openid_keys.py   4 passed
test_openid_crypto.py        8 passed
test_admin_user_points_routes.py / test_application_openapi.py 通过
合计                         157 passed（认证批次）
前端 tsc --noEmit + eslint 零报错
```

#### 遗留（本批新登记）

1. **迁移仍未执行**：`add_openid_encrypted_storage` + `add_password_history` 两个迁移待 `alembic upgrade head`；执行前需配置 `OPENID_LOOKUP_KEY` / `OPENID_ENCRYPTION_KEY` / `PASSWORD_HISTORY_PEPPER`。
2. **`ForgotPasswordPage` 的本地校验**是用户盘点漏掉的第 3 处，已顺带修复（前后端文案同源）。
3. 锁定 DoS 缓解（邮件通知）留 4.4/合规批；`on_lockout` 通知钩子未落（锁定分支纯 401，后续加通知需改 login 热路径，属追补）。
4. 既存 11 例 503（Redis 客户端跨事件循环）仍与本批无关。

#### 批次 B 评审修复（2026-09-01，评审清单逐项落实）

| 评审项 | 修复 |
|--------|------|
| #2 微信重绑 unionid 空不清旧值 | `bind/confirm` 微信分支：unionid 有则写、**无则显式清空**（一次绑定一种微信身份）；新增测试 `test_bind_confirm_wechat_clears_stale_unionid_when_absent` |
| #3 管理员创建不入历史 | `admin/users.py` 建号后 `password_history_service.record()`（与注册同构，同事务）；新增测试 `test_admin_create_user_records_password_history` |
| #4 超管初始密码不过策略/随机可能不合规 | `resolve_initial_admin_password`：env 值先 `validate_password_strength`，不过直接报错退出；development 随机**生成后循环校验直至合规**（base64url 缺数字概率 ≈8%）；建号后 `record()` 入历史；新增 2 例测试 |
| #6 空 pepper 无开发期保护 | `hash_password_for_history` 空 pepper 直接抛错；`main.py` 启动校验**全环境拒绝空 pepper**（占位串仅 dev 可用）；新增测试 `test_password_history_hash_rejects_empty_pepper` |
| #7 admin schema 双重拦截 | `UserCreateByAdmin` 去掉 `Field(max_length=50)`，统一走策略函数（超长也返回统一文案）；新增测试 `test_admin_user_create_password_rejects_with_unified_message` |
| #8 历史表无 FK | `add_password_history` 迁移（未执行）补 `ForeignKey("users.id", ondelete="CASCADE")` |
| #9 `HISTORY_SIZE` 写死 | 新增 `PASSWORD_HISTORY_SIZE` 配置，service 读取；新增测试 `test_password_history_size_follows_settings` |
| #11 设密后旧会话立即 401 | 前端 `handleSetPassword` 成功分支：删掉 `loadUserCenterData`（必然 401 触发被动登出），改为 `performLogout` + 跳 `/login`（与"改密后需重新登录"语义一致） |
| #1 时序表述 | D1 决策行补"不声称时序级一致"；测试只比 body/status |
| #5 pepper 共享风险 | `.env.example` 补"不得用于任何共享环境"警告 |
| 收口：超管建号不入历史 | `create_super_admin` 在 `db.flush()` 取 id 后 `password_history_service.record()`（与 admin 建号同构，同事务），否则新超管可改回 `INITIAL_ADMIN_PASSWORD`；新增测试 `test_create_super_admin_records_password_history`（真实 Base 内存库，不污染其它测试模块） |
| 收口：绑定冲突 UX | 用户中心绑定卡片补提示"该账号已绑定其他用户时需更换账号重新发起授权" |

回归：认证批次 **165 passed**（新增 9 例），前端 tsc/eslint 零报错。

### 批次 C：4.5 认证模型迁移（httpOnly Cookie）（2026-09-01）

**范围**：access/refresh/csrf 三 cookie 迁移 + CSRF 双重提交 + 前端去 localStorage 令牌。不含 4.3/4.4。用户决策："测试数据可弃、只保 schema"，硬切无兼容窗口。

#### 取证结论（迁移前置）

- 请求拓扑为**同域代理**（Vite `/api`+ws 代理 → 8000；生产 nginx 同理）：浏览器只与前端源交互，cookie 同源，无跨站 SameSite 问题，OAuth 回跳天然兼容。
- 非 axios 链路仅 3 处 fetch（`previewTTSCached` / memories auto-save / SSE 轮询），全部同源、cookie 自动携带；无原生 WebSocket 客户端（vite ws 代理为遗留配置）。

#### 决策记录（用户 2026-09-01 确认）

| 决策 | 结论 |
|------|------|
| 兼容期 | 硬切。`get_current_user` cookie 优先、Authorization 头仅作兜底（前端不再持久化令牌后该兜底对 XSS 无增益，且测试基建依赖） |
| refresh cookie SameSite | Lax（OAuth 回跳后首个同源 XHR 仍携带） |
| `__Host-` 前缀 | 按环境开关：`COOKIE_SECURE` / `COOKIE_PREFIX`（dev 空前缀 + 非 Secure） |
| localStorage | access/refresh 彻底不存；仅留非 PII user 快照；会话恢复改由启动时无条件 `getCurrentUser`（cookie 自动） |
| 会话数据 | 不迁移：Redis 残留 refresh/jti 随 TTL 过期；`users` 测试行不动 |

#### 改造明细

| 文件 | 改动 |
|------|------|
| `backend/app/core/config.py` | 新增 `COOKIE_SECURE` / `COOKIE_PREFIX` |
| `backend/app/core/security.py` | cookie 命名助手（access/refresh/csrf）；`create_csrf_token` / `csrf_claim_hash`；`set_auth_cookies` / `clear_auth_cookies`（access/refresh httpOnly + Lax；csrf 非 httpOnly + Strict，JS 可读）；`csrf_check`（cookie 会话 + unsafe 方法真双重提交：X-CSRF-Token 头 == csrf cookie 值，且 csrf cookie sha256 == JWT csrf claim，Authorization 头/公共端点跳过）；`_resolve_access_token`（Authorization 头优先、cookie 兜底）；`get_current_user` / `get_current_user_optional` 支持 cookie；`build_token_response` 签发 `csrf` claim + 返回 csrf_token |
| `backend/app/main.py` | `csrf_guard` 中间件（复用 `security.csrf_check`） |
| `backend/app/api/v1/auth.py` | login / register_confirm / oauth_confirm 响应 Set-Cookie；`/refresh` 从 cookie 读 refresh（body 兜底）+ 轮换三 cookie；logout 清除三 cookie + 吊销 cookie refresh；change-password / set-password 成功后清除 cookie；change-password 补"按 id 重查"（跨会话实例，与 set-password 同款） |
| `backend/app/schemas/user.py` | `RefreshTokenRequest.refresh_token` 允许空（cookie 承载） |
| 前端 `authSlice` | `persistAuth` 不再写 access/refresh；`readPersistedAuth` token 恒 null、isAuthenticated 恒 false；`performLogout` 空 body |
| 前端 `api.ts` | 401 刷新改纯 cookie（空 body、不再写 localStorage、去掉 refresh-token 空值 gate 与 429 接管 storage 分支）；重放不再拼 Authorization 头；`shouldRedirectToLogin` 排除 /login 前缀 /register /forgot-password（启动时匿名页 401 不跳登录） |
| 前端 `App.tsx` | 启动无条件 `getCurrentUser` 恢复会话（cookie 自动） |
| `.env.example` | 补 `COOKIE_SECURE` / `COOKIE_PREFIX` 说明 |

#### TDD RED → GREEN

| 轮次 | RED | GREEN |
|------|-----|-------|
| cookie 认证 | `/me` 带 cookie 无 Authorization → 401；login 无 Set-Cookie | cookie 助手 + `get_current_user` 双源 + login/register/oauth_confirm Set-Cookie → 6 例新用例 |
| refresh cookie | `/refresh` 空 body + cookie → 401 | cookie 读 refresh + 三 cookie 轮换 |
| CSRF | cookie 会话 POST 缺/错 csrf → 200（绕过） | `csrf_check` + 中间件 → 缺/错 403，匹配 200，头认证跳过 |
| 登出清 cookie | 登出不返回 Max-Age=0 | `clear_auth_cookies` |

#### 回归数字

```
认证批次 171 passed（新增 cookie 层 6 例 + 既有全部保持）
前端 tsc --noEmit + eslint 零报错
```

#### 遗留（本批新登记）

1. **响应体仍含 access_token/refresh_token** → ✅ 2026-09-01 完成（见下方「收尾：响应体 token 剥离」），body 不再返回任何令牌。
2. **部署验证**：`__Host-` + Secure 需 HTTPS 实测（nginx 层）；staging 需完整回归（OAuth 回跳、多标签刷新、改密/设密后自动登出）。
3. 既有 11 例 503（Redis 客户端跨事件循环）与本批无关。

### 批次 D：4.3 用户数据权利 API + 4.4 审计日志（脱敏）（2026-09-01）

**范围**：4.3 全项（导出/注销/个人资料/同意记录）+ 4.4 全项（脱敏审计 + 登录链路埋点 + 90 天保留 + 管理员查询）。含 5.2 同意记录表、5.3 注销冷静期/匿名化衔接。沿用用户"测试数据可弃、只保 schema"口径，无存量数据迁移负担。

#### 决策记录（2026-09-01）

| 决策 | 结论 |
|------|------|
| 注销语义 | 软删除（`deleted_at` + `is_active=False`）+ `token_version + 1`；认证层已注销**视同不存在（401）**，优先于禁用（403）检查——注销后不暴露"禁用"等异于活跃账户的语义 |
| 注销后二次操作 | 认证层先拦截（401）；路由内"该账号已注销"400 保留为纵深防御（正常流程不可达） |
| 导出范围 | 只含个人信息清单（5.1）：profile + 第三方绑定标记 + 同意记录；**openid 明文不下发**——第三方平台标识不可移植，绑定标记足以行权，且避免二次泄露面（密文也不随导出解密） |
| 冷静期 | 30 天（`ACCOUNT_DELETE_COOLING_DAYS`）；`anonymize_expired_accounts` 服务 + 脚本，默认 dry-run、落库须 `--apply` |
| 匿名化边界 | username→`deleted_{id}`（不可反推原名）；清 email/phone/full_name/avatar/password_hash/openid 三对哈希密文；**删 password_history**（密码类用户数据）；**保留**审计日志（90 天清理）与同意记录（合规证明，永久保留）；不触碰账单表（7 年法定保留） |
| 同意记录 | `consent_records` 表（5.2 结构）+ `User.consent_version`；触发点：注册（privacy_policy）、OAuth 建号/绑定（oauth_sync）、填手机号（phone_collection）；按 user+type+version 幂等 |
| 审计 | `audit_logs` 表（4.4 结构），只存 IP/UA 的 HMAC-SHA256 哈希（独立 `AUDIT_LOG_PEPPER`，空 pepper fail-closed）；保留 90 天；仅管理员查询（复用 `log:read` 权限，查询时懒清理） |
| 已注销拦截面 | `_validate_user_status`（登录态 401）、login（静默 401 + dummy bcrypt）、refresh、OAuth `handle_alipay/wechat_login`、`create_confirmed_user` 回落分支、绑定冲突——全部把已注销账号视同不存在 |

#### 改造明细

| 文件 | 改动 |
|------|------|
| `app/models/audit_log.py`（新增） | `AuditLog`：user_id（FK SET NULL）/ event_type / provider / ip_hash / user_agent_hash / success / failure_reason（仅非敏感类别） |
| `app/models/consent_record.py`（新增） | `ConsentRecord`（5.2）：user_id / consent_type / version / content_hash / scope(JSON) / ip_hash / accepted_at / withdrawn_at |
| `app/models/user.py` | 新增 `deleted_at`（注销软删除）+ `consent_version`（当前同意版本） |
| `alembic/versions/add_audit_logs.py`（新增） | 建 audit_logs（down_revision = add_password_history） |
| `alembic/versions/add_consent_records_and_user_rights.py`（新增） | users 加 deleted_at/consent_version + 建 consent_records |
| `app/services/audit_log_service.py`（新增） | `audit_hash`/`audit_ip_hash`/`audit_user_agent_hash`（独立 pepper）；`record_audit`（**独立 commit**——登录失败随后 raise 不吞审计）；`cleanup_expired_audit_logs`（90 天） |
| `app/services/consent_service.py`（新增） | `record`（幂等）/ `list_for_user` / `sha256_content_hash` |
| `app/services/account_anonymization_service.py`（新增） | `anonymize_expired_accounts`（dry-run 支持，字段清单见决策表） |
| `app/api/v1/user_rights.py`（新增） | `POST /user/data/export`、`POST /user/account/delete`、`PUT /user/profile`（手机号变更写 phone_collection 同意）、`GET /user/consent` |
| `app/api/v1/admin/audit.py`（新增） | `GET /admin/audit/audit-logs`（`require_permission("log:read")`，查询时懒清理超期记录） |
| `app/api/v1/auth.py` | 登录链路埋点：login（成功 / not_found / 密码错 / 锁定 / 禁用）、register、logout、refresh（成功 / 失败）、OAuth callback（登录 / 建号 / 绑定）、bind/unbind、change/set/reset-password；注册 / OAuth 建号 / 绑定写同意记录；login/refresh 拦截已注销 |
| `app/core/security.py` | `_validate_user_status` 已注销优先 401（视同不存在）；`get_current_user_optional` 跳过已注销 |
| `app/services/oauth_service.py` | `handle_alipay/wechat_login` 与 `create_confirmed_user` 回落分支拦截已注销用户（冷静期不回落登录） |
| `app/core/config.py` | `AUDIT_LOG_PEPPER` / `AUDIT_LOG_RETENTION_DAYS` / `ACCOUNT_DELETE_COOLING_DAYS` |
| `app/main.py` | 启动校验 `AUDIT_LOG_PEPPER`（任何环境非空）；注册 user_rights 路由 |
| `scripts/anonymize_expired_accounts.py`（新增） | 冷静期后匿名化脚本（默认 dry-run，`--apply` 落库，可选 `--purge-audit`） |
| `.env.example` | 补三项配置说明 |

#### TDD RED → GREEN

| 轮次 | RED | GREEN |
|------|-----|-------|
| 审计服务 | 无 `audit_hash`/`record_audit`/`cleanup_expired_audit_logs` | 服务 + 模型 + 迁移 → `test_audit_log.py` 4 passed（哈希确定性/独立 pepper/只存哈希/90 天清理/空 pepper fail-closed） |
| 数据权利路由 | 4 端点 404；已注销未拦截 | `user_rights` + security 拦截 + 同意记录 → `test_user_rights.py` 7 passed |
| 匿名化 | 无 `anonymize_expired_accounts` | 服务 + dry-run → `test_account_anonymization.py` 2 passed |
| 审计埋点 | 注册/登录无 audit 行、无 privacy_policy 同意 | auth.py 埋点 + 同意记录 → `test_auth_routes.py` 3 例新增 |
| admin 审计 | `/admin/audit/audit-logs` 无表/权限未验 | `admin/audit.py` → `test_admin_user_points_routes.py` 1 例新增（超管可查/普通 403/返回哈希） |

#### 回归数字

```
test_auth_routes.py             111 passed（+3 审计埋点/同意）
test_oauth_alipay.py             11 passed
test_openid_crypto.py             8 passed
test_password_policy.py          10 passed
test_init_admin_data.py           3 passed
test_rotate_openid_keys.py        4 passed
test_admin_user_points_routes.py 21 passed（+1 admin 审计）
test_application_openapi.py       通过
test_audit_log.py                 4 passed（新增）
test_user_rights.py               7 passed（新增）
test_account_anonymization.py     2 passed（新增）
合计                             188 passed（认证/合规批次）
```

迁移执行：`python -m alembic upgrade head` 落地到 `add_consent_records_and_user_rights (head)`。过程中发现 `app/celery_app.py` 模块导入期 `Base.metadata.create_all` 会为新增模型自动建表（audit_logs/consent_records 被先建出但未进 alembic 版本链），已确认两表为空后 drop 再走正规迁移。

#### 批次 D 追补（2026-09-01，同日合规闭环）

用户审阅批次 D 遗留后确认继续推进，同日落地三项：

| 追补 | 内容 |
|------|------|
| ① 5.2 真实同意（核心合规修复） | 修复"后端**无条件代用户记录同意**"缺陷：注册/OAuth 建号/绑定改为**只记录用户显式勾选的项**。新增 `ConsentAcceptance`（三个请求体可选字段）+ `_require_consents` 建号前校验（未勾选 400 不放行、版本过期 400 重新勾选）+ `consent_service.record_accepted` 按条款模板落库（content_hash/scope 集中管理）；前端注册页/OAuth 建号引导页/**绑定确认页**（原为无感自动绑定，改为先勾选再绑定）加 `ConsentCheckboxes` 勾选组件，未勾选项不传后端 |
| ② 5.3 匿名化接入 celery beat | 新增 `app/tasks/account_anonymization_tasks.py`：`account.anonymize_expired` 每日 03:30 幂等匿名化超期账号（落库非 dry-run） |
| ③ celery create_all 止血 | `app/celery_app.py` 的 `Base.metadata.create_all` 加 `APP_ENV == "development"` 判断：非开发环境强制走 Alembic，杜绝自动建表与版本链脱节（本批已踩坑） |

**TDD**：RED 4 例（未勾选注册被拒且无用户/无同意记录；只记录勾选项；填手机号需手机号收集同意；过期版本被拒）→ GREEN。前端 `buildConsentPayload` 纯函数单测 5 例（只带勾选项/版本与后端对齐）。

**回归**：后端认证/合规批次 **192 passed**（test_auth_routes 115 = 111+4，OAuth/绑定测试同步补 consent 入参）；前端 `tsc --noEmit` 通过 + consent 单测 5 passed。

#### 遗留（本批新登记）

1. **5.2 前端分步同意 UI 未做** → ✅ 2026-09-01 同日追补完成（注册页/OAuth 引导页/绑定确认页勾选 UI + 后端只记录真实同意）。
2. **冷静期匿名化未接入定时任务** → ✅ 2026-09-01 同日追补完成（celery beat 每日 03:30，`account.anonymize_expired`）。
3. **celery create_all 与 alembic 版本链不同步** → ✅ 2026-09-01 同日追补完成（仅 development 环境兜底）。
4. **注销无撤销接口**（冷静期内不可反悔）：YAGNI，若产品需要"取消注销"再补。
5. 批次 C 遗留 #1（响应体仍含 access/refresh token）未动。
6. 既有 11 例 503（Redis 客户端跨事件循环）与本批无关。

---

## 五、遗留事项（随批次更新，以第四章各批记录为准）

- P0/P1 部署验证项仍有效（见第一节）
- 前端非 axios 链路已在 4.5 评估：仅 3 处同源 fetch（cookie 自动携带）、无原生 WS 客户端，无需改造 refresh 链路（4.5 ✅ 2026-09-01）
- **`alembic upgrade head` 已执行（2026-09-01）**：`add_openid_encrypted_storage` + `add_password_history` 均落地，`alembic current = add_password_history (head)`；`users` 6 个新列（3 hash + 3 encrypted）就位、明文 openid 列已删除；`password_history` 表带 FK 重建。过程中发现并删除一张**迁移外的孤儿 `password_history` 空表**（非本会话创建、0 行、结构一致，已确认后 drop）——后续若再遇 `DuplicateTable`，先排查是否有迁移外建表
- 密钥轮换脚本已实现，但未接入 CI/运维流程（更新密钥后需人工执行并重启）
- ~~既存问题：`test_user_assets_routes.py` 等共 11 例 503（Redis 异步客户端跨事件循环复用）~~ ✅ 2026-09-01 修复，见下方「收尾」
- **5.2/5.3 状态（随批次 D 追补更新）**：5.2 同意记录表 `consent_records` 已落地且**前端勾选 UI 已完成**——注册/OAuth 建号/绑定均只记录用户显式勾选的项，未勾选不放行（不再代用户同意）；5.3 注销冷静期（软删除 30 天）与匿名化脚本已落地，**已接入 celery beat 每日定时任务**（`account.anonymize_expired`）。5.4/5.5/5.6 未随 P2 实施。

### 收尾（2026-09-01）：既有 11 例 503 修复（Redis 跨事件循环）

根因：`redis.asyncio` 客户端绑定创建时的事件循环，而各 service 把客户端缓存在**模块级单例**；测试客户端每请求 `asyncio.run()` 新建事件循环，第二个请求复用旧客户端即抛 `Event loop is closed` → 被 fail-closed 翻译成 503。

修复：新增 `app/core/redis_client.py`（`LoopBoundRedis`：按事件循环**弱引用缓存**异步客户端），替换全部 8 处模块级单例：

| 文件 | 涉及 |
|------|------|
| `app/core/security.py` | JtiRevocationService / AccountLockoutService / RefreshTokenService |
| `app/api/v1/auth.py` | OAuthStateService / AuthRateLimiterService / OAuthCodeGuard / OAuthPendingRegistrationService |
| `app/services/password_reset_service.py` / `email_verification_service.py` | 验证码服务（保留 fail-closed 503 转换，调用点在 try 外） |
| `app/services/generation_lock.py` / `free_quota.py` | 生成锁 / 免费配额 |
| `app/services/cache_system.py` | RedisCache（fail-open，改为每次按当前循环取客户端） |

生产（uvicorn 单事件循环）每次请求 loop 相同 → 退化为单客户端，行为不变；测试多循环各自独立。

回归：原 503 三文件（`test_user_assets_routes` / `test_user_center_routes` / `test_user_center_billing_events`）**34 passed**（11 例 503 全灭）；认证/合规批次 **226 passed**；`test_generation_lock` + `test_free_quota` **31 passed**；`test_celery_beat_task_registration` 2 passed。测试注入点由 `svc._redis_client = fake` 改为 `svc._redis = _FakeRedisManager(fake)`（3 个测试文件）。

注：全量 4363 例在本环境因 IDE 临时文件清理防护（bulk delete guard，与代码无关）无法一次跑完；**所有受改动影响的模块测试均已单独全绿**。

### 收尾（2026-09-01）：响应体 token 剥离（4.5 最后一环）

完成批次 C 遗留 #1：登录/注册/建号/OAuth/refresh 响应 body 不再返回 access_token/refresh_token，
令牌只经 httpOnly cookie 承载，前端不再持有明文 token、不再发 Authorization 头。

**后端**：
- `TokenResponse` 只留 `user`；`RefreshTokenResponse` 只留 `message`；`OAuthCallbackResponse.token` → `user`
- refresh 路由返回 `{"message": "刷新成功"}`（新令牌已由 set_auth_cookies 入 cookie）
- **修复 4.5 遗漏**：OAuth alipay/wechat callback 老用户分支此前只返回 body token、未落 cookie，本次补 set_auth_cookies
- **socket.io 认证配套改造**：`connect` 握手时从 httpOnly access cookie 验证并绑定 sid（`sid_user`），
  `join_project`/`join_audiobook` 改为从 sid 会话取用户，不再依赖 body token（纯 cookie 下前端拿不到明文）

**前端**：
- `authSlice`：删 `state.token` 与全部 token 赋值；`AuthSuccessPayload` 只含 user；删 `tokensRefreshed`；
  `persistAuth` 顺带清理旧版遗留的 localStorage token
- `api.ts`：删请求拦截器 Bearer 头（cookie 自动认证）；`refreshAccessToken` 改为 boolean 语义（200 即成功，
  body 无 token）；删 `setTokenRefreshListener`/`setTokenLogoutListener`/cross-tab storage 同步机制；
  清理 previewTTSCached fetch / SSE 头的 Bearer
- `websocket.ts` / `bookParserApi.ts` / `WorkflowControlPage`：去 Bearer / body token
- `store.ts`：删 token 监听注册

**测试**：后端认证批次 **192 passed**（16 例从 body token 断言改为 cookie 断言；测试客户端加 cookie jar
模拟浏览器会话；OAuth callback 测试改为断言 access cookie）。前端 `tsc --noEmit` 通过，认证相关测试全绿
（apiRefresh 重写为 boolean 语义、authSlice 去 token 断言、websocket 去 body token 断言），全量批次 500+ passed。

**关键设计**：CSRF 随后加固为**真双重提交**（同日）：csrf cookie 改为**非 httpOnly**（SameSite=Strict，JS 可读），unsafe 请求携带 `X-CSRF-Token` 头 == csrf cookie 值，且 csrf cookie 值 sha256 == JWT `csrf` claim——SameSite=Lax 为第一道防线，显式头为第二道（不依赖 SameSite 支持）；前端 axios 拦截器 / 独立 fetch（TTS preview / memories auto-save）/ bookParserApi / refresh 均自动构造头。`/oauth/confirm` 补 `response_model=OAuthConfirmResponse`（confirm 回 user / cancel 回 message，response_model 双保险滤掉任何多余字段，防再次漏 token）。后端 `_resolve_access_token` 保留 Authorization 头兜底（测试基建/非 cookie 客户端），浏览器侧已无 JS 可读持久 token。

### 收尾（2026-09-02）：合规定稿 + 文档对齐 + 应急工具

**合规定稿**（用户提供事实）：
- **5.4 出境评估**：支付宝/微信/DeepSeek/火山/OSS/SMTP 均境内节点，个人信息不出境，不触发 PIPL 出境评估；保留"服务商变更须复核"约束（换境外 SMTP 须补评估）
- **5.6 未成年人**：按"不面向不满 14 周岁"路径定稿——非游戏不适用年龄门禁类专门规定，但 PIPL 第 31 条不限于游戏，故走"声明 + 不收集年龄 + 发现即处置"（注销并**即时匿名化，不走 30 天冷静期**，复用 4.3 注销 API + 5.3 匿名化服务）

**架构指南文档对齐**（漂移修复）：
- 6.2 环境变量模板补 `AUDIT_LOG_PEPPER`（空则拒绝启动）/ `ACCOUNT_DELETE_COOLING_DAYS` / `COOKIE_SECURE` / `COOKIE_PREFIX`
- 5.1 表格：openid 存储位置由"明文 ⚠️"修正为 4.1 后的哈希 + 加密（明文列已删除）
- 6.3 总览表补 P0 2.1–2.6 与 5.2/5.3/5.4/5.6 完成标记
- 6.1 文件清单补 4.3/4.4/5.2/5.3 全部新增文件
- 页眉"最后更新"同步

**应急工具**：新增 `backend/scripts/bump_all_token_versions.py`（5.5 预案"递增所有用户 token_version"）——默认 dry-run、`--apply` 落库、幂等可重复；测试 3 例（dry-run 不写库 / apply 全量 +1 / 重复执行幂等）。

**5.5 隐私政策（2026-09-02 完成）**：正文 `docs/PRIVACY_POLICY.md`（v1，运营者南京拾光工坊信息科技有限公司，负责人 371640372@qq.com，生效 2026-09-06）+ 前端 `/privacy` 展示页（公开路由，注册页与 OAuth 建号勾选处的《隐私政策》已改为链接）+ `CONSENT_TEXTS["privacy_policy"]` 升级为**正文全文**（`content_hash` = sha256(正文)，存证对象真实存在，测试钉住 7 项要素与不可退化）。**建议**：正式生效前法务复核正文。架构指南第一章 1.1–1.7 旧文（Bearer + localStorage 背景描述）保留为历史背景。

---

> **维护说明**：本日志在 P0/P1 收口后开篇，随 P2 各批次推进追加。完成一项后同步更新架构文档第四章状态标记与 6.3 总览表。
