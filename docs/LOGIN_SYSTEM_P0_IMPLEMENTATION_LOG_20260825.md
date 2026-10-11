# 登录系统 P0 落地实施记录

> **关联文档**：[LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md](./LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md)
> **实施范围**：仅 P0（2.1-2.6 共 6 项）
> **审批节奏**：按 P0 批量确认（用户已确认）
> **实施日期**：2026-08-25
> **复审**：2026-08-25 code-review-checklist 对照审查 → 发现 2.5 两个实现缺口，完成最小修复（P0.1-P0.6）
> **结论**：✅ P0 六项主体落地并经复审修复与两轮收尾，后端 49 项测试通过，前端静态诊断无错误

---

## 一、实施概览

| P0 编号 | 改造项 | 状态 | 验证方式 | 结果 |
|---------|--------|------|---------|------|
| 2.1 | 生产环境安全基线 | ✅ 完成（复审补 min_length/CORS） | 单元测试 + 静态诊断 | `test_settings_defaults_are_safe` 通过 |
| 2.2 | 支付宝 RSA2 签名与验签 | ✅ 完成 | 单元测试 | 4 项签名/验签/篡改/沙箱测试通过 |
| 2.3 | OAuth state 服务端原子消费 | ✅ 完成 | 单元测试 | 4 项 state 测试通过 |
| 2.4 | redirect_uri 精确白名单 | ✅ 完成 | 单元测试 | 2 项白名单测试通过 |
| 2.5 | 全局 token_version 吊销 | ✅ 完成（复审修复 OAuth tv + 禁用递增） | 单元测试 + 迁移验证 | 3 项 tv 测试通过，Alembic head 识别 |
| 2.6 | 账号枚举防护 | ✅ 完成（仅统一文案下限，完整方案见 P1 3.8） | 单元测试 | 2 项枚举防护测试通过 |

**测试基线**：实施前 9 项 -> 首次实施后 32 项 -> 复审修复后 45 项 -> 两轮收尾后 **49 项全部通过**（含管理端禁用吊销端到端测试）。

---

## 二、关键步骤与时间节点

| 时间 | 步骤 | 说明 |
|------|------|------|
| 2026-08-25 | 1. 基线确认 | 运行既有 `test_auth_routes.py`：9 passed，环境依赖（cryptography 46.0.3 / redis 6.4.0 / python-jose 3.5.0 / Python 3.13.7）就绪 |
| 2026-08-25 | 2. 创建实施记录框架 | 建立本日志骨架 |
| 2026-08-25 | 3. TDD RED | 为 P0 六项编写 13 项新测试，确认 8 项按预期失败（功能缺失），5 项因测试缺陷修正 |
| 2026-08-25 | 4. 确认既有实现 | 发现 `oauth_service.py` 已具备 RSA2 签名/验签主体（既有改动），P0 仅需补充 sandbox 网关 |
| 2026-08-25 | 5. TDD GREEN | 实现六项改造（详见第三节），修复测试缺陷后 25 passed |
| 2026-08-25 | 6. 兼容既有测试 | 更新 `test_oauth_alipay.py` 的 callback 测试注入 state，全量 32 passed |
| 2026-08-25 | 7. 迁移创建 | 新增 `add_user_token_version` Alembic 迁移，`alembic heads` 正确识别 |
| 2026-08-25 | 8. 前端适配 | auth-url 返回服务端 state、callback 携带 state，同步修改 4 个前端文件 |
| 2026-08-25 | 9. 全量验证 | 后端 32 项测试通过，6 个改动文件静态诊断无错误 |

---

## 三、遇到的问题及解决方案

| # | 问题 | 解决方案 | 影响 |
|---|------|---------|------|
| 1 | **state 相关 4 项测试"意外通过"**：`backend/.env` 配置了真实支付宝参数，无 state 的回调请求走到真实支付宝网关后返回 400，测试碰巧通过但依赖网络/真实网关，不可靠 | 在测试中注入 `FakeAlipayOAuthService`（内存实现），彻底隔离网络；新增 `test_oauth_callback_with_valid_state_succeeds` 验证正常路径 | 测试确定性与稳定性 |
| 2 | **state 必填导致 422 而非 400**：`state: str` 必填时缺参触发 FastAPI 参数校验 422，与文档预期的 400 不符 | `state` 保留 `Optional[str]`，后端显式校验非空返回 400（"无效的登录状态，请重新发起"），错误语义与 state 不匹配统一 | 符合文档验证预期，错误语义一致 |
| 3 | **既有 `test_oauth_alipay.py` 1 项失败**：callback 测试未传 state，新校验返回 400 | 注入 `FakeStateService` 预存合法 state 并传参；`FakeAlipayService.__init__` 加 `**kwargs` 兼容 sandbox 参数 | 既有测试适配新行为 |
| 4 | **前端与后端 state 不一致**：后端 auth-url 生成自己的 state，前端仍存自己生成的 state，回调校验必然失败 | 前端 `LoginPage` 改用 `response.data.state` 存储；`api.ts` / `authSlice.ts` / `LoginCallbackPage` 同步传递 state | 前后端 OAuth 流程保持一致 |
| 5 | **alembic offline 模式失败**：`alembic upgrade head --sql` 因既有迁移 `add_chapter_summary_fields_to_existing_table.py` 含 SQLite 特异代码（offline 无连接）而报错 | 改用 `alembic heads` 验证迁移链识别（显示 `add_user_token_version (head)`），新迁移本身语法正确 | 非本次改动引入的环境限制 |
| 6 | **login 第三方账户提示泄露类型**：原 `_ensure_local_password_account` 返回 400"请使用原登录方式"，可区分账户类型 | login 中移除该调用，直接 `verify_password`（对 `!oauth-disabled!` 哈希返回 False）→ 统一 401 文案；函数保留给 change-password/reset-password | 消除账户类型枚举面 |

---

## 四、资源使用情况

| 资源 | 说明 |
|------|------|
| 依赖 | **无新增依赖**。RSA2 签名/验签复用已安装的 `cryptography`（46.0.3），Redis 复用 `redis`（6.4.0） |
| 后端文件变更（7 个） | `config.py`、`main.py`、`security.py`、`models/user.py`、`api/v1/auth.py`、`services/oauth_service.py`、`api/v1/admin/users.py` |
| 迁移文件 | `backend/alembic/versions/add_user_token_version.py`（新增，down_revision=`add_snapshot_chapter_number`） |
| 测试文件变更（3 个） | `tests/test_auth_routes.py`、`tests/test_oauth_alipay.py`、`tests/test_admin_user_points_routes.py` |
| 前端文件变更（4 个） | `services/api.ts`、`store/slices/authSlice.ts`、`pages/LoginPage.tsx`、`pages/LoginCallbackPage.tsx` |
| 配置模板 | `backend/.env.example`（新增 APP_ENV / ALIPAY_SANDBOX / OAUTH_REDIRECT_URI_WHITELIST） |
| 其他 | `nginx-prod.conf`（`/login/callback` 单独 Referrer-Policy）、`docs/LOGIN_SYSTEM_ARCHITECTURE_AND_IMPROVEMENT_GUIDE.md`（状态同步） |

---

## 五、阶段性成果验证结果

### 5.1 自动化测试

```
$ python -m pytest tests/test_auth_routes.py tests/test_oauth_alipay.py tests/test_admin_user_points_routes.py -q
49 passed in ~7s
```

| 测试文件 | 覆盖范围 | 通过数 |
|---------|---------|-------|
| test_auth_routes.py | 注册/登录/找回密码/改密/登出 + P0 六项 | 28 |
| test_oauth_alipay.py | 支付宝签名/验签/篡改检测/沙箱/回调登录 + state/redirect_uri 纵深 | 7 |
| test_admin_user_points_routes.py | 管理端用户管理 + 禁用->旧 token 吊销端到端 | 14 |

### 5.2 关键行为验证点

| 验证点 | 结果 |
|--------|------|
| `APP_ENV` 存在且默认 `development`，`DEBUG` 默认 `False` | ✅ |
| 支付宝请求带 RSA2 `sign`，响应篡改后验签失败 | ✅ |
| 沙箱模式使用 `openapi.alipaydev.com` 网关 | ✅ |
| OAuth 回调缺 state / state 不匹配 → 400；state 一次性消费 | ✅ |
| Redis 不可用时 state 校验 fail-closed → 503 | ✅ |
| 恶意 redirect_uri（子域/query/userinfo/HTTP）被拒绝 | ✅ |
| token_version 与签发时不符 → 401；无 tv 旧 token 兼容 | ✅ |
| 重复邮箱注册返回统一文案；第三方账户密码登录统一 401 | ✅ |
| Alembic 迁移链 head = `add_user_token_version` | ✅ |
| 前端 4 个改动文件静态诊断无错误 | ✅ |

### 5.3 未覆盖/需部署时验证项

- `main.py` lifespan 启动检查与全局异常处理器：因 `app.main` 依赖大量环境（DB、各路由模块），未做 import 冒烟测试；逻辑简单且静态诊断无错误，**需在部署时通过实际启动验证**（生产环境配置默认 JWT_SECRET 应启动失败、配置正确应正常启动、异常响应不返回 traceback）。
- ~~支付宝真实网关端到端：需在支付宝沙箱环境用真实 app_id/密钥验证完整 OAuth 流程~~ ✅ **已完成（2026-09-03）**：用真实生产 app_id/密钥完成完整 OAuth 流程（真实扫码授权 → code 换票 → 用户信息拉取，`E2E_VERDICT=SUCCESS`），并修复联调暴露的 3 个真实缺陷，见第十一章。

---

## 六、与原计划的偏差分析

| # | 文档计划 | 实际执行 | 偏差说明 | 影响 |
|---|---------|---------|---------|------|
| 1 | 2.2 需引入支付宝 SDK 或实现 RSA2 签名 | **复用既有实现**：`oauth_service.py` 已具备 `_sign`/`_verify_response`/`build_sign_content`，仅补充 sandbox 网关参数 | 既有实现已满足文档"请求签名 + 响应验签"要求，无需重复实现（DRY） | 无（功能达标） |
| 2 | 2.3 `state: str` 必填 | `state: Optional[str]` + 后端显式校验 | 避免 FastAPI 422，统一为 400 错误语义 | 无（防 CSRF 效果一致） |
| 3 | 2.5 无 tv 直接 401 | 无 tv 视为版本 1（迁移窗口兼容） | 避免上线瞬间所有旧 token 集体掉线，符合文档"迁移窗口"要求 | 更平滑的上线体验 |
| 4 | 2.1 CORS 收窄（allow_methods/headers 去 `*`） | 已收窄为常用方法/头集合 | 与文档一致 | 需确认前端无自定义头（已含 Authorization/Content-Type） |
| 5 | 前端适配为 P0 一部分 | 同步修改 4 个前端文件 | 后端改变 state 生成策略后，前端必须适配否则登录失效 | 无（已完成） |
| 6 | 2.6 仅统一文案 | 文案统一 + dummy bcrypt 时序防护 + 移除 login 账户类型泄露 | 文档建议的完整枚举防护 | 无（更完善） |
| 7 | 文档建议 lifespan 预生成 dummy 哈希 | 实现 `initialize_security_globals()` 并在 lifespan 调用，另含惰性兜底 | 与文档一致 | 无 |

---

## 七、遗留事项与后续建议

1. **部署验证**：上线前需实际启动应用，确认 lifespan 安全检查和异常处理器行为符合预期。
2. **沙箱端到端**：用支付宝沙箱环境完成真实 OAuth 全流程验证。
3. **迁移执行**：正式环境执行 `alembic upgrade head`（token_version 默认 1，存量用户平滑过渡）。
4. **P1 衔接**：P0 的 `get_current_user` 已为 P1 的 jti 单会话登出预留（签发已带 jti），后续实现 `is_jti_revoked` 黑名单即可。
5. **隐私合规**：P0 未覆盖隐私政策正文、consent_records 等合规项（属"合规并行"工作项），建议按指南第五章推进。

---

## 八、复审修复记录（2026-08-25）

经 code-review-checklist 对照审查，发现首次实施存在 2.5 实现缺口等问题，按"上线前必修"优先级完成最小修复（P0.1-P0.6），全部通过测试与静态诊断。

| 修复项 | 问题 | 改动 | 验证 |
|--------|------|------|------|
| P0.1 | 第三方登录签发的 JWT 无 `tv`（`oauth_service.py` `handle_alipay_login`/`handle_wechat_login` 用 `create_access_token({"sub": ...})`），改密/重置后旧第三方 token 仍可被当作 tv=1 使用 | 两处签发补 `"tv": user.token_version` | `test_oauth_alipay.py` 扩展断言 token payload.tv==1 |
| P0.2 | 管理员禁用账号不递增 `token_version`（`admin/users.py` 只改 `is_active`），重新启用后旧 token 复活 | `update_user_status` 中禁用时 `user.token_version += 1` | 新增 `test_admin_disable_user_increments_token_version` |
| P0.3 | `JWT_SECRET` 无 `min_length`；生产 CORS 未强制（默认 localhost + `allow_credentials=True`，漏配 `APP_ENV` 不触发检查） | `config.py` 加 `min_length=32`；`main.py` lifespan 在生产/staging 校验 CORS_ORIGINS 不含 localhost | 静态诊断 |
| P0.4 | `nginx-prod.conf` 全局 Referrer-Policy 是 `strict-origin-when-cross-origin`，OAuth code 可进 Referer | 新增 `location = /login/callback` 单独 `no-referrer`（并显式重复其他安全头，规避 nginx add_header 覆盖规则） | 配置审查 |
| P0.5 | 前端 `serverState = response.data?.state || state` 静默回退，服务端无 state 时回调必失败 | 改为服务端未返回 state 时直接报错并 return | 静态诊断 |
| P0.6 | 架构文档 callback"仍不校验 state"与实施矛盾 | 更新指南 1.4 流程图与 1.5 路由表（state/redirect_uri/tv 状态） | 文档同步 |

**复审后测试结果**：`test_auth_routes.py` + `test_oauth_alipay.py` + `test_admin_user_points_routes.py` 共 **45 passed**；5 个改动后端文件 + 前端 LoginPage 静态诊断无错误。

**明确不纳入本次修复（按指南归 P1/部署/验证）**：
- 注册枚举完整方案（先发码再创建账号）→ P1 3.8
- jti 黑名单 / logout 吊销 → P1 3.5（P0 签发已带 jti 预留）
- Redis Sentinel/Cluster 高可用 → 部署项
- 支付宝沙箱端到端、`main.py` 启动检查实启 → 部署验证项
- 微信 secret 日志脱敏、支付宝 `code!=10000` 口径 → 随 P1/P2 排期

---

## 九、收尾修复记录（2026-08-25，第二轮）

用户确认 P0 安全闭环闭合后，按"还值得修"清单完成 5 项收尾，49 项测试全部通过。

| 修复项 | 问题 | 改动 | 验证 |
|--------|------|------|------|
| 收尾1 | 白名单默认值未按 `APP_ENV` 组装，本机 `http://localhost:5173/login/callback` 会 400 | `config.py` 加 `model_validator`，development 环境默认追加 localhost | `test_development_env_whitelist_includes_localhost` |
| 收尾2 | callback 消费了绑定的 `redirect_uri` 但返回值被丢弃，绑定字段等于没用 | alipay/wechat callback 接住 `consume()` 返回值并 `_validate_redirect_uri` 纵深校验 | `test_oauth_callback_rejects_tampered_redirect_uri` |
| 收尾3 | `_build_user_payload` 手搓 JSON 不走 `UserResponse`，与本地登录响应分叉 | 改为 `UserResponse.model_validate(user)`，OAuth 响应与本地登录一致（含 roles，不含 openid）。注：该函数在第三轮收口时随签发去重被并入 `build_token_response`，守护测试同步更名为 `test_build_token_response_serializes_user_via_user_response_schema` | `test_build_token_response_serializes_user_via_user_response_schema` |
| 收尾4 | 禁用测试绕过 HTTP 层，未断言旧 JWT 调 `/me` 401 | 新增端到端测试：禁用→重新启用后，旧 token 调 `/me` 仍 401（tv 递增防复活） | `test_disable_then_reenable_user_revokes_old_token_end_to_end` |
| 收尾5 | 日志第四节文件清单过时（数量/迁移路径） | 更新为 7 后端 + 3 测试 + nginx/文档，迁移路径修正为 `backend/alembic/versions/...` | 文档同步 |

**收尾后测试结果**：`test_auth_routes.py` + `test_oauth_alipay.py` + `test_admin_user_points_routes.py` 共 **49 passed**；改动文件静态诊断无错误。

---

## 十、收口修复记录（2026-08-27，第三轮）

用户确认 P0 收口后点名的 5 个"不挡 P0"小问题，其中 3 项修复、2 项仅备注不改动。

| 项 | 问题 | 处理 | 验证 |
|----|------|------|------|
| 收口1 | 本日志数字打架（文首 45、5.1 节 32/25 过时） | 统一为最新口径：49 passed（auth_routes 28 + oauth_alipay 7 + admin_user_points 14），测试基线链补齐 9->32->45->49 | 文档同步 |
| 收口2 | `.env.example` 白名单注释易误导为"开发需手动加 localhost" | 注释改为"只需填对外域名，development 启动时自动追加 localhost" | 文档同步 |
| 收口3 | 本地登录与 OAuth 各自手搓签发逻辑，两处分叉 | `security.py` 新增统一 `build_token_response(user)`（tv 签发 + UserResponse 序列化）；`auth.py` 删除本地 `_build_token_response` 改为调用统一函数；`oauth_service.py` 两处 `handle_*_login` 同步替换，顺带删除失去调用方的 `_build_user_payload`（序列化职责已并入统一函数）及其孤立导入；守护测试重定向为 `test_build_token_response_serializes_user_via_user_response_schema`；后续新增 claim 只改一处 | 49 项测试全通过，改动文件静态诊断无错误 |
| 收口4（备注） | 白名单测试读全局 `settings`，非 development 环境会误报 | 不改动：当前默认 dev 环境可过，已在 P1 排期项中备注 | — |
| 收口5（备注） | 工作区存在与本任务无关的脏文件（`backend/data/scene_audio_artifacts/`、未跟踪 `ssl/alipay_public_key.txt`、未跟踪 `backend/tmp_new_prompt_verify/`） | 三步处理完毕：① `git restore` 丢弃 `scene_audio_artifacts` 脚本的本地改动（内容为一段导入路径修复，用户确认无需保留）；② `ssl/alipay_public_key.txt` 经哈希比对与 `backend/.env` 的 `ALIPAY_PUBLIC_KEY` 为同一把公钥（冗余副本，运行时读 .env），在 `.gitignore` ssl 段新增 `ssl/*.txt` 规则，文件保留本地、不再出现在 git status；③ `backend/tmp_new_prompt_verify/`（两份金标准文本对比，`tmp_` 前缀一次性验证产物，无代码引用）经用户确认后删除。以上均应 2026-08-27 用户要求处理 | `git status` 仅剩登录 P0 相关改动 |

**收口后测试结果**：`test_auth_routes.py`（28）+ `test_oauth_alipay.py`（7）+ `test_admin_user_points_routes.py`（14）共 **49 passed**；改动文件（`security.py`、`auth.py`、`oauth_service.py`）静态诊断无错误。

**遗留部署项**（与 P0 代码无关，上线前执行）：`APP_ENV=production` 实际启动验证 lifespan 门控；对生产库真实执行 `alembic upgrade head`。

---

## 十一、真实网关端到端联调记录（2026-09-03）

P0 遗留的部署验证项（5.3 第二条）闭环：用真实生产 app_id/密钥/支付宝公钥，由用户真实扫码授权，完成“授权 → code 换票 → 验签 → 用户信息拉取”全链路，最终 `E2E_VERDICT=SUCCESS`。联调过程暴露并修复 3 个真实缺陷（均按 TDD 先红后绿），全量回归 4365 passed，失败 8 项经排除性复跑确认为存量（音频库测试顺序串扰 7 项 + 契约文档编码 1 项），零新增。

### 11.1 前置核对：回调域与实际访问域名一致性 ✅

- `.env` 的 `OAUTH_REDIRECT_URI_WHITELIST` 补录 `sggf.net` 与 `www.sggf.net` 双域（development 自动追加 localhost 不受影响）；`scripts/check_oauth_redirect_config.py` 解析验证通过。
- 白名单改为真实域名后，7 个用 `your-domain.com` 的既有测试因读到本机真实白名单而 400；按 `test_auth_routes.py` 既有隔离约定（save/注入/restore）补齐白名单隔离后恢复。

### 11.2 联调发现的 3 个真实缺陷与修复（均 TDD）

| # | 缺陷 | 根因 | 修复 | 验证 |
|---|------|------|------|------|
| 联调1 | 网关错误响应（`error_response`）被误当成功：`payload.get("alipay_system_oauth_token_response", payload)` 退回整包 + `.get("code", "10000")` 缺省 → `isv.code-invalid` 被当作换票成功 | 响应包裹体判定只看成功键、业务码有缺省值 | 新增 `extract_gateway_error`：识别 `error_response` 转为结构化错误，且**先于验签判定**（真实网关错误响应的 `sign` 无法用支付宝公钥验证，实测非合法 RSA 签名） | `test_get_access_token_returns_error_for_gateway_error_response` 等 3 项 |
| 联调2（登录阻断级） | 成功响应验签全部失败：旧实现对“剥掉外层 sign 后的整串”验签，而真实网关签名只覆盖**内层业务包裹体的紧凑 JSON 原文** | 验签串构造方向全错；多策略取证（5 策略）定位到策略 D（内层紧凑重序列化）唯一通过 | `extract_response_sign_content`：按响应原文切片取内层包裹体子串（不重序列化，避免转义/空格差异）；删除失效的 `strip_sign_fields` | `test_verify_response_matches_real_gateway_signing_content` 等 2 项网关格式测试 + 篡改拒绝仍绿 |
| 联调3（真实登录必炸） | 应用开启 openid 配置后 `user.info.share` 只回 `open_id`（无 `user_id`），登录链路只认 `user_id` → `handle_alipay_login` 抛 `ValueError("Invalid Alipay user info")` | 网关字段约定变更 | `get_user_info` 成功分支归一化：无 `user_id` 时用 `open_id` 填充（已有则不覆盖，兼容旧约定） | `test_get_user_info_normalizes_open_id_to_user_id` / `test_get_user_info_keeps_existing_user_id` |

### 11.3 真实网关约定取证结论（写入架构指南 2.2）

1. 请求：应用私钥 RSA2 签名、参数 ASCII 升序拼接——网关已验证接受。
2. 响应：签名只覆盖内层包裹体（`xxx_response`）紧凑 JSON；外层仅包裹体 + 末尾 `sign` 字段，无 `sign_type`。
3. 错误响应包在 `error_response`，其 `sign` 不可验；错误分支必须先于验签。
4. `oauth.token` 成功响应内层无 `code` 字段（字段：access_token / expires_in / re_expires_in / refresh_token / open_id 等）。
5. 授权码流回跳参数名为 `auth_code`；授权码一次性、短时效（首个 code 被探测消耗后需重新扫码取证）。
6. 密钥配置复核：控制台登记应用公钥与 `.env` 的 `ALIPAY_PUBLIC_KEY` 逐字节一致、私钥与应用公钥配对正确——初判“公钥配错”系误判，真根因是联调2。

### 11.4 测试与清理

- 定向：`test_oauth_alipay.py` + `test_auth_routes.py` 共 137 项全绿；全量 4365 passed / 8 failed（存量）/ 5 skipped。
- 一次性探测脚本（网关探测、密钥比对、验签策略取证、全链路探测等 6 个）及输出已删除，截图证据保留于 `.tmp/oauth_e2e_*.png`。

### 11.5 遗留提示（非本次范围）

- 线上需重新部署后端，真实用户才能使用支付宝登录（线上旧代码含联调2/3 缺陷）。
- 微信侧：AppSecret 未生成、开放平台资质审核未通过，暂不可联调。链路已先行完善（2026-09-03）：前后端链路既有实现复核无缺口，新增 `tests/test_oauth_wechat.py` 11 项（授权地址构造、未配置 503、errcode 40163 落 used/其他错误释放锁、userinfo 错误、老用户/新用户/票据密文/绑定意图）与支付宝侧覆盖对等；待审核通过配置 `WECHAT_APP_ID/WECHAT_APP_SECRET` 后即可按支付宝同流程联调。
- `oauth.token` 成功响应无 `code` 字段、当前依赖缺省值的边界，已记录于架构指南 2.2 约定第 3 条，后续按“以 access_token 存在为准”口径对齐（随后续排期）。

---

> **维护说明**：本记录完整覆盖实施过程，供项目团队成员查阅与后续复盘。P0 六项主体落地并经两轮复审修复 + 一轮收口 + 真实网关联调（3 缺陷修复），49 项定向测试通过、全量回归零新增失败，可进入 P1 排期。
