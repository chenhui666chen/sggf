# 登录系统架构设计与实施改造指南

> **目标读者**：全栈开发团队（后端 Python/FastAPI + 前端 React/TypeScript）
> **文档定位**：现有架构说明 + 按优先级排序的改造实施方案 + 隐私合规生命周期
> **最后更新**：2026-08-25
>
> **⚠️ 实施警告**：本文档中标记了 `🚫 反模式，禁止照抄` 的章节，包含已知会引入新问题的错误方案。实施时请务必阅读替代方案，不要直接复制这些章节的代码。

---

## 目录

- [一、现有架构说明](#一现有架构说明)
  - [1.1 整体架构图](#11-整体架构图)
  - [1.2 数据流图](#12-数据流图)
  - [1.3 数据模型](#13-数据模型)
  - [1.4 OAuth 2.0 授权码流程](#14-oauth-20-授权码流程)
  - [1.5 后端路由与组件](#15-后端路由与组件)
  - [1.6 前端状态管理](#16-前端状态管理)
  - [1.7 现有安全机制与缺陷速查](#17-现有安全机制与缺陷速查)
- [二、P0 改造（生产安全，上线前必须完成）](#二p0-改造生产安全上线前必须完成)
  - [2.1 生产环境安全基线](#21-生产环境安全基线)
  - [2.2 支付宝 RSA2 签名与验签](#22-支付宝-rsa2-签名与验签)
  - [2.3 OAuth state 服务端一次性校验](#23-oauth-state-服务端一次性校验)
  - [2.4 redirect_uri 精确白名单](#24-redirect_uri-精确白名单)
  - [2.5 全局 token 吊销（改密/禁用/重置后）](#25-全局-token-吊销改密禁用重置后)
  - [2.6 账号枚举防护](#26-账号枚举防护)
- [三、P1 改造（高风险，上线后尽快修复）](#三p1-改造高风险上线后尽快修复)
  - [3.1 登录与注册限流（账号+IP 维度）](#31-登录与注册限流账号ip-维度)
  - [3.2 OAuth 首次建号确认与账号合并策略](#32-oauth-首次建号确认与账号合并策略)
  - [3.3 授权码泄漏防护](#33-授权码泄漏防护)
  - [3.4 密码重置链路加固](#34-密码重置链路加固)
  - [3.5 单会话登出（jti 吊销）](#35-单会话登出jti-吊销)
  - [3.6 XSS 防护与前端安全基线](#36-xss-防护与前端安全基线)
  - [3.7 短 access token + 可吊销 refresh token](#37-短-access-token--可吊销-refresh-token)
  - [3.8 邮箱验证](#38-邮箱验证)
  - [3.9 RBAC 初始化与水平越权防护](#39-rbac-初始化与水平越权防护)
- [四、P2 改造（中等风险，计划修复）](#四p2-改造中等风险计划修复)
  - [4.1 openid 确定性查找哈希 + 加密存储](#41-openid-确定性查找哈希--加密存储)
  - [4.2 账户绑定与解绑](#42-账户绑定与解绑)
  - [4.3 用户数据权利 API](#43-用户数据权利-api)
  - [4.4 审计日志（脱敏）](#44-审计日志脱敏)
  - [4.5 认证模型迁移（httpOnly Cookie）](#45-认证模型迁移-httponly-cookie)
  - [4.6 密码策略与账户锁定](#46-密码策略与账户锁定)
- [五、隐私合规与个人信息保护](#五隐私合规与个人信息保护)
  - [5.1 个人信息清单与数据分类分级](#51-个人信息清单与数据分类分级)
  - [5.2 同意记录（版本化、可审计）](#52-同意记录版本化可审计)
  - [5.3 数据留存与注销策略](#53-数据留存与注销策略)
  - [5.4 第三方共享与出境评估](#54-第三方共享与出境评估)
  - [5.5 安全事件响应预案](#55-安全事件响应预案)
  - [5.6 未成年人保护](#56-未成年人保护)
- [六、附录](#六附录)
  - [6.1 相关文件清单](#61-相关文件清单)
  - [6.2 环境变量配置模板](#62-环境变量配置模板)
  - [6.3 改造优先级总览](#63-改造优先级总览)

---

## 一、现有架构说明

### 1.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         前端 (React 18 + TypeScript)               │
│                                                                   │
│  ┌──────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│  │ LoginPage │──▶│ LoginCallbackPage│──▶│    ProtectedRoute    │  │
│  │ (登录页)   │   │  (OAuth回调页)    │   │    (路由守卫)         │  │
│  └────┬─────┘   └────────┬─────────┘   └──────────┬───────────┘  │
│       │                  │                         │              │
│  ┌────┴──────────────────┴─────────────────────────┴──────────┐  │
│  │                    Redux authSlice                          │  │
│  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │  │
│  │  │  login  │  │ register │  │alipayLogin│  │wechatLogin │  │  │
│  │  └────┬────┘  └────┬─────┘  └─────┬─────┘  └─────┬──────┘  │  │
│  └───────┼────────────┼──────────────┼──────────────┼─────────┘  │
│          │            │              │              │            │
│  ┌───────┴────────────┴──────────────┴──────────────┴─────────┐  │
│  │                    apiClient (axios)                         │  │
│  │   请求拦截器: 自动附加 Authorization: Bearer <token>          │  │
│  │   响应拦截器: 401 → 清除 token → 重定向 /login                │  │
│  └──────────────────────────┬──────────────────────────────────┘  │
│                             │                                     │
│  ┌──────────────────────────┴──────────────────────────────────┐  │
│  │                  localStorage 持久化                          │  │
│  │  access_token / user (含 email/phone/openid ⚠️)              │  │
│  │  oauth_provider / oauth_state                                │  │
│  └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                               │
                    HTTPS (CORS: allow_credentials=True, 方法/头 *)
                               │
┌──────────────────────────────┼──────────────────────────────────┐
│                         后端 (FastAPI + Python)                   │
│                              │                                    │
│  ┌───────────────────────────┴───────────────────────────────┐  │
│  │              API 路由层 (app/api/v1/auth.py)               │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────┐  ┌────────────────────┐  ┌────────────────┐  │
│  │ security.py   │  │ oauth_service.py   │  │ 数据持久层      │  │
│  │ JWT / bcrypt  │  │ Alipay / Wechat    │  │ User / Redis   │  │
│  └───────────────┘  └────────────────────┘  └────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │  PostgreSQL  │   │    Redis     │   │  SMTP 邮件   │
   └──────────────┘   └──────────────┘   └──────────────┘
```

### 1.2 数据流图

以下数据流图覆盖从浏览器到第三方服务再到存储的完整链路，是隐私政策和 PIA 的基础：

```
                    ┌─────────────────────────────────────────┐
                    │              浏览器 (Browser)             │
                    │  localStorage: token, user, oauth_state  │
                    │  URL: ?code=xxx&state=xxx (历史记录)      │
                    └──────────┬──────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
     ┌────────────┐  ┌──────────────┐  ┌──────────────┐
     │ 你们的 API  │  │ 支付宝 OAuth  │  │ 微信 OAuth    │
     │ (FastAPI)  │  │ (openauth)   │  │ (qrconnect)  │
     └─────┬──────┘  └──────┬───────┘  └──────┬───────┘
           │                │                  │
           │        ┌───────┴───────┐  ┌───────┴───────┐
           │        │ 支付宝返回字段  │  │ 微信返回字段    │
           │        │ user_id       │  │ openid        │
           │        │ nick_name     │  │ unionid       │
           │        │ (头像需另调)   │  │ nickname      │
           │        └───────┬───────┘  │ headimgurl    │
           │                │          └───────┬───────┘
           │                │                  │
           └────────────────┼──────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
   ┌────────────┐  ┌──────────────┐  ┌──────────────┐
   │ PostgreSQL │  │    Redis     │  │  SMTP 邮件    │
   │ users 表   │  │ 验证码/state │  │ 密码重置通知  │
   │ (明文)     │  │ (HMAC 哈希)  │  │              │
   └─────┬──────┘  └──────────────┘  └──────────────┘
         │
   ┌─────┴──────────────────────────────────────┐
   ▼                ▼                ▼           ▼
┌──────┐    ┌──────────┐    ┌──────────┐   ┌──────────┐
│ OSS  │    │ AI 模型   │    │ 音频服务  │   │ 账单系统  │
│ 作品 │    │ 供应商    │    │ 供应商    │   │ 消费记录  │
└──────┘    └──────────┘    └──────────┘   └──────────┘

每段链路上传输的字段：
  Browser → 你们的 API:  username/email/phone/password, OAuth code, JWT
  API → 支付宝:          app_id, code, sign
  支付宝 → API:          user_id, nick_name
  API → 微信:            appid, secret, code
  微信 → API:            openid, unionid, nickname, headimgurl
  API → PostgreSQL:      全部 User 字段（当前明文）
  API → Redis:           验证码哈希（HMAC-SHA256）
  API → SMTP:            email, 验证码
  (后续) API → AI 模型:  剧本内容（可能含用户创作中隐含的个人信息）
```

### 1.3 数据模型

**User 表** (`users`)：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | int | PK, index | 主键 |
| `username` | varchar(255) | unique, index | 昵称/展示名 |
| `email` | varchar(255) | unique, index，**当前非空** | 邮箱（登录凭证；OAuth 用户目前靠假邮箱占位，见 3.2 改造） |
| `phone` | varchar(20) | unique, index, nullable | 手机号（可选，敏感个人信息） |
| `password_hash` | varchar(255) | nullable | bcrypt 哈希（第三方账户为 `!oauth-disabled!`） |
| `full_name` | varchar(255) | nullable | 昵称 |
| `avatar_url` | varchar(255) | nullable | 头像 URL |
| `is_active` | boolean | default true | 是否启用 |
| `alipay_openid` | varchar(255) | nullable, index | 支付宝用户唯一标识（明文 ⚠️） |
| `wechat_openid` | varchar(255) | nullable, index | 微信用户唯一标识（明文 ⚠️） |
| `wechat_unionid` | varchar(255) | nullable, index | 微信开放平台 unionid（明文 ⚠️） |
| `created_at` | datetime(tz) | server_default now() | 创建时间 |
| `updated_at` | datetime(tz) | onupdate now() | 更新时间 |

**缺失的关键字段**（需在改造中新增）：

| 建议字段 | 用途 |
|---------|------|
| `token_version` | 全局会话吊销：改密/禁用/重置时递增，所有旧 JWT 失效 |
| `email_verified` | 邮箱是否已验证（默认 false） |
| `email_verified_at` | 邮箱验证时间 |
| `consent_version` | 当前同意的隐私政策版本号（仅版本号，详细记录在 consent_records 表） |
| `deleted_at` | 软删除时间戳（用于留存策略） |
| （见 4.1） | openid 相关字段：`alipay_openid_hash`(UNIQUE)、`alipay_openid_encrypted`、`wechat_openid_hash`(UNIQUE)、`wechat_openid_encrypted`、`wechat_unionid_hash`(UNIQUE)、`wechat_unionid_encrypted` |

**账户类型区分机制**：

```
password_hash 值                          → 账户类型
─────────────────────────────────────────────────────────
$2b$... (bcrypt 哈希)                     → 本地密码账户
!oauth-disabled!                          → 第三方登录账户
NULL                                      → 异常状态
```

**第三方账户创建规则**（当前逻辑，需改造）：

| 来源 | username 格式 | email 格式 |
|------|--------------|------------|
| 支付宝 | `alipay_{openid后12位}` | `alipay_{openid后12位}@alipay.temp` |
| 微信 | `wechat_{openid后12位}` | `wechat_{openid后12位}@wechat.temp` |

⚠️ **问题**：假邮箱占用 `email` 唯一索引。另外注意：当前 `User.email` 实际为**非空约束**（见 `backend/app/models/user.py`），OAuth 用户应允许 `email=NULL`（见 3.2 改造，需同步放开非空约束），而不是用假域名填充。`username` 保持唯一约束但应允许用户后续修改。

### 1.4 OAuth 2.0 授权码流程

```
步骤1: 用户点击"支付宝/微信登录"
  │
  ├─ 前端 POST /api/v1/auth/{provider}/auth-url
  │     └─ 后端 ⚠️ 不校验 redirect_uri 白名单，不生成服务端 state
  └─ 前端 window.location.href = auth_url → 跳转第三方授权页
       │
步骤2: 用户在第三方页面完成授权
       │
步骤3: 第三方回调 redirect_uri (前端 /login/callback?code=xxx&state=xxx)
  │
  ├─ 前端 LoginCallbackPage 读取 URL 参数
  │     ⚠️ code 出现在浏览器地址栏、历史记录、Referer
  ├─ 前端 校验 state 一致性（仅前端校验 ⚠️）
  ├─ 前端 POST /api/v1/auth/{provider}/callback { code, state }
  │    │
  │    ├─ 后端 ⚠️ 不校验 state（可选字段，不验证）
  │    ├─ 后端 支付宝已完成 RSA2 签名与验签（2.2 ✅ 2026-08-25）
  │    ├─ 后端 OAuthService.handle_xxx_login()
  │    │   ├─ 不存在 → 自动建号 ⚠️ 无确认
  │    │   └─ 存在 → 每次登录同步昵称/头像
  │    └─ 返回 { access_token (JWT, 24h), user }
  │
  └─ 前端 persistAuth() → 存入 localStorage，跳转 /home
```

### 1.5 后端路由与组件

| 路由 | 方法 | 功能 | 当前缺陷 |
|------|------|------|---------|
| `/api/v1/auth/register` | POST | 注册 | 可账号枚举 |
| `/api/v1/auth/login` | POST | 密码登录 | 可账号枚举 |
| `/api/v1/auth/me` | GET | 获取当前用户 | 正常 |
| `/api/v1/auth/logout` | POST | 登出 | 不吊销 token |
| `/api/v1/auth/change-password` | POST | 修改密码 | 不失效旧 token |
| `/api/v1/auth/reset-password/request-code` | POST | 发送找回密码邮件 | 验证码可能回传 |
| `/api/v1/auth/reset-password` | POST | 验证码重置密码 | 不失效旧 token |
| `/api/v1/auth/alipay/auth-url` | POST | 获取支付宝授权地址 | 不对 redirect_uri 做白名单校验 |
| `/api/v1/auth/alipay/callback` | POST | 支付宝 OAuth 回调 | 签名/验签已完成（2.2 ✅），仍不校验 state |
| `/api/v1/auth/wechat/auth-url` | POST | 获取微信授权地址 | 同上 |
| `/api/v1/auth/wechat/callback` | POST | 微信 OAuth 回调 | 不校验 state |

### 1.6 前端状态管理

**Redux authSlice**：`State: { user, token, isLoading, error, isAuthenticated }`

**持久化（localStorage）**：`access_token`、`user`（含 email, phone, openid 等完整字段）、`oauth_provider`、`oauth_state`

⚠️ openid 和手机号不应下发到前端 localStorage。P0 改造中应规定 `UserResponse` 脱敏。

### 1.7 现有安全机制与缺陷速查

| 机制 | 实现状态 | 缺陷 |
|------|---------|------|
| 密码哈希 | bcrypt | 正常 |
| JWT 认证 | HS256，24h 过期 | 默认 `JWT_SECRET` 占位值，无吊销 |
| DEBUG 模式 | 默认 `True` | 异常带 traceback，验证码可能回传 |
| OAuth state（防 CSRF） | 仅前端 | 后端不校验 |
| redirect_uri 白名单 | 无 | 开放重定向 |
| 被禁用账户拦截 | `is_active=False` → 403 | 已签发 token 仍有效 |
| 改密/重置后旧 token 失效 | 无 | 旧 token 24h 内仍可用 |
| 登出吊销 token | 无 | logout 不吊销 |
| 验证码存储 | HMAC-SHA256 | Redis 优选，内存回退在多实例下不一致 |
| 限流 | 无 | 所有端点无速率限制 |
| 账号枚举防护 | 无 | 注册/登录/找回密码均返回不同文案 |
| OAuth 建号 | 自动建号，无确认 | 第三方身份直接变站内账号 |
| openid 存储 | 明文 | 数据库泄露 = 实名身份关联 |
| 支付宝 API 签名 | ✅ 已实现 | 自实现 RSA2（未引入官方 SDK，见 2.2） |
| 支付宝回包验签 | ✅ 已实现 | 验签失败返回错误，不进入业务解析 |
| 前端 XSS 防护 | 无 | CSP 未配置，token 在 localStorage |
| RBAC | 未评审 | 有模型但未验证默认角色和首个用户超管 |
| 邮箱验证 | 无 | 未验证邮箱即可用于登录和重置 |
| 密码策略 | 无 | 无最小长度/复杂度要求 |

---

## 二、P0 改造（生产安全，上线前必须完成）

### 2.1 生产环境安全基线

**问题描述**：

`config.py` 中 `JWT_SECRET` 的默认值为 `"your-secret-key-change-in-production"`，`DEBUG` 默认值为 `True`。如果生产环境漏配，任何人可以用这个已知密钥伪造任意用户的 JWT。

**涉及文件**：

- `backend/app/core/config.py` 第 30 行（`DEBUG`）、第 44 行（`JWT_SECRET`）

**改造方案**：

不把 `JWT_SECRET` 改成 `Field(...)`（会误伤本地开发和测试）。改为按 `APP_ENV` 区分：

```python
class Settings(BaseSettings):
    APP_ENV: str = Field(default="development", description="development | staging | production")

    JWT_SECRET: str = Field(
        default="your-secret-key-change-in-production",
        min_length=32,
    )
    DEBUG: bool = Field(default=False)

# 在 lifespan 中做启动检查（不要用已弃用的 @app.on_event）
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV in ("production", "staging"):
        if settings.JWT_SECRET == "your-secret-key-change-in-production":
            raise RuntimeError(f"{settings.APP_ENV} 环境必须配置 JWT_SECRET")
        if settings.DEBUG:
            raise RuntimeError(f"{settings.APP_ENV} 环境 DEBUG 必须为 False")
    yield
```

全局异常处理器，生产环境不返回 traceback：

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.DEBUG or settings.APP_ENV == "development":
        raise exc
    logger.error("未捕获异常: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})
```

**UserResponse 脱敏**：openid 永不下发前端。当前 `UserResponse` 不应包含 `alipay_openid`、`wechat_openid`、`wechat_unionid` 字段。手机号在 `/me` 接口对本人返回完整值（需已登录，用于用户确认和修改），在日志、其他接口的嵌套 user 对象中脱敏为 `138****1234`。

**安全头**：回调页 `/login/callback` 必须设置 `Referrer-Policy: no-referrer`，防止 code 通过 Referer 泄漏。

**CORS**：生产环境 `allow_credentials=True` 时必须将 `allow_origins` 改为精确白名单，不允许 `*`；`allow_methods` 和 `allow_headers` 收窄到实际使用的方法和头。

**实施步骤**：

1. 新增 `APP_ENV` 配置项，移除 `DEBUG` 默认 `True`
2. 实现 lifespan 启动检查
3. 添加全局异常处理器
4. `UserResponse` 排除 openid 字段，脱敏 phone
5. CORS：生产环境 `allow_origins` 改为精确白名单，`allow_methods`/`allow_headers` 收窄
6. 前端 nginx/CDN 对 `/login/callback` 路径设置 `Referrer-Policy: no-referrer`
7. 更新 CI/CD 部署脚本

---

### 2.2 支付宝 RSA2 签名与验签（✅ 已完成，2026-08-25）

> **实施状态**：请求签名与响应验签已落地，但采用的是**自实现方案**（基于 `cryptography` 库，见 `backend/app/services/oauth_service.py`：`build_sign_content` / `strip_sign_fields` / `AlipayOAuthService._sign` / `_verify_response`），**未引入官方 `alipay-sdk-python`**，避免新增同步 SDK 依赖。测试见 `backend/tests/test_oauth_alipay.py`（7 例：签名规则、验签往返、篡改拒绝、回调路由等）。
>
> **遗留差异**：① 未实现 `ALIPAY_SANDBOX` 开关（当前仅支持生产网关 `openapi.alipay.com`），联调阶段如需沙箱需补；② oauth.token 成功判断仍用 `code != 10000`（缺省 10000），与下文“以是否含 access_token 为准”的口径建议存在差异，实测后按需对齐。
>
> 下文为最初的官方 SDK 方案记录，仅作存档，**勿再按此方案重复实施**。

**问题描述**：

`AlipayOAuthService` 只传了 `sign_type="RSA2"`，但没有实际生成 `sign` 参数。支付宝回包 `sign` 也没有被验证。

**改造方案**（引入支付宝官方 SDK，注意 SDK 是同步的且各版本验签行为不一致）：

```python
# pip install alipay-sdk-python
import asyncio
import json
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.request.AlipaySystemOauthTokenRequest import AlipaySystemOauthTokenRequest
from alipay.aop.api.request.AlipayUserInfoShareRequest import AlipayUserInfoShareRequest

class AlipayOAuthService:
    def __init__(self, app_id: str, private_key: str, alipay_public_key: str, sandbox: bool = False):
        gateway = "https://openapi.alipaydev.com/gateway.do" if sandbox else "https://openapi.alipay.com/gateway.do"
        self.client = DefaultAlipayClient(
            server_url=gateway,
            app_id=app_id,
            private_key=private_key,
            format="json",
            charset="utf-8",
            alipay_public_key=alipay_public_key,  # 注意：是支付宝公钥，不是应用公钥
            sign_type="RSA2",
        )

    async def get_access_token(self, code: str) -> dict:
        response = await asyncio.to_thread(self._do_get_access_token, code)
        return response

    def _do_get_access_token(self, code: str) -> dict:
        request = AlipaySystemOauthTokenRequest()
        request.grant_type = "authorization_code"
        request.code = code
        raw_response = self.client.execute(request)
        # 验签：依赖 SDK 构造时 verify=True（默认）；落地时确认验签失败会抛异常，否则需手动验
        response = json.loads(raw_response)
        # 注意：alipay.system.oauth.token 的成功响应可能不包含业务 code=10000
        # 以 alipay_system_oauth_token_response 是否存在且含 access_token 为准
        token_data = response.get("alipay_system_oauth_token_response", {})
        if not token_data.get("access_token"):
            return {
                "error": str(token_data.get("sub_code") or token_data.get("code") or "alipay_auth_failed"),
                "error_description": str(token_data.get("sub_msg") or token_data.get("msg") or "Alipay authentication failed"),
            }
        return token_data

    async def get_user_info(self, access_token: str) -> dict:
        return await asyncio.to_thread(self._do_get_user_info, access_token)

    def _do_get_user_info(self, access_token: str) -> dict:
        request = AlipayUserInfoShareRequest()
        raw_response = self.client.execute(request, auth_token=access_token)
        # 显式验签：SDK 构造时 verify=True 即可自动验签
        response = json.loads(raw_response)
        user_info = response.get("alipay_user_info_share_response", {})
        if not user_info.get("user_id"):
            return {
                "error": str(user_info.get("sub_code") or "alipay_user_info_failed"),
                "error_description": str(user_info.get("sub_msg") or "Failed to get user info"),
            }
        return user_info
```

**验签**：`alipay-sdk-python` 构造时 `verify=True`（默认）即可自动验签。若需手动验签，从回包 `sign` 字段取值，不要依赖 `_parse_sign` 等内部 API。验签失败必须抛异常，不得进入业务字段解析。沙箱网关是 `openapi.alipaydev.com`，和生产不是同一个。

**微信 OAuth 注意事项**（在 2.2 改造中一并处理）：

- `get_access_token` 的 URL 中包含 `secret` 参数，日志中必须脱敏
- 微信 `errcode` 非 0 且 `errmsg` 含 "code been used" 时，code 已失效，前端应提示重新发起
- 微信 token 接口返回的 `access_token` 有效期为 2 小时，`refresh_token` 有效期为 30 天，但当前只用了 `access_token` 调 `userinfo`，不需要存 refresh
- 微信 `userinfo` 接口返回的 `headimgurl` 可能为 HTTP 而非 HTTPS，前端展示时需处理混合内容

**实施步骤**：

1. 安装 `alipay-sdk-python`，用 `asyncio.to_thread` 包装同步 SDK
2. 配置项增加 `ALIPAY_SANDBOX` 开关，沙箱用 `openapi.alipaydev.com`
3. 明确区分"应用私钥"和"支付宝公钥"的配置项命名
4. 验签失败必须抛异常，不得继续解析业务 JSON
5. 使用支付宝沙箱环境验证完整 OAuth 流程

---

### 2.3 OAuth state 服务端一次性校验

**问题描述**：

`OAuthCallbackRequest` 的 `state` 字段是 `Optional`，后端完全不校验。攻击者可以绕过前端直接 POST 到 callback 端点。

**关键约束**：

- state 必须服务端生成、服务端校验、一次性消费
- Redis 中 state 必须绑定 `redirect_uri` 和 `provider`
- 校验失败也要删除 state
- Redis 不可用时返回 503，不静默降级
- **消费操作必须是原子的**：不能 `GET` 再 `DELETE`，用 `GETDEL` 或 Lua 脚本

**改造方案**：

```python
# auth.py
import secrets
import json

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str  # 改为必填

async def _store_oauth_state(
    redis_client, state: str, provider: str, redirect_uri: str, ttl: int = 600
) -> None:
    await redis_client.setex(
        f"oauth:state:{state}", ttl,
        json.dumps({"provider": provider, "redirect_uri": redirect_uri}),
    )

async def _consume_oauth_state(
    redis_client, state: str, expected_provider: str
) -> dict:
    """原子消费 OAuth state。Redis 6.2+ 可用 GETDEL，否则用 Lua。"""
    key = f"oauth:state:{state}"
    try:
        # 原子操作：先获取再删除
        raw = await redis_client.getdel(key)  # Redis 6.2+
        # 兼容旧版 Redis:
        # raw = await redis_client.eval(
        #     "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v", 1, key
        # )
    except Exception:
        raise HTTPException(status_code=503, detail="认证服务暂时不可用")

    if not raw:
        raise HTTPException(status_code=400, detail="无效的登录状态，请重新发起")

    payload = json.loads(raw)
    if payload.get("provider") != expected_provider:
        raise HTTPException(status_code=400, detail="登录提供方不匹配")

    # 返回存储的 redirect_uri，callback 中可用做纵深校验
    return payload

# 在 callback 中
@router.post("/alipay/callback", response_model=TokenResponse)
async def alipay_callback(request: OAuthCallbackRequest, db: Session = Depends(get_db)):
    _ensure_alipay_configured()
    state_payload = await _consume_oauth_state(redis_client, request.state, "alipay")
    # 纵深：state 里存的 redirect_uri 已在 auth-url 时通过 2.4 校验，无需再验
    # ... 后续流程不变
```

**Redis 高可用**：P0 把 Redis 变成登录关键路径，必须配置 Redis Sentinel 或 Cluster，确保 fail-closed 不降级。

**实施步骤**：

1. `OAuthCallbackRequest.state` 改为必填 `str`
2. 实现 `_store_oauth_state` 和 `_consume_oauth_state`（原子消费）
3. 修改 auth-url 端点：服务端生成 state，存入 Redis
4. 修改 callback 端点：调用 `_consume_oauth_state` 校验，state 中绑定的 `redirect_uri` 可用做纵深校验
5. 前端从 auth-url 响应中获取 `state`，保留前端校验作为纵深防御
6. Redis 配置高可用

---

### 2.4 redirect_uri 精确白名单

**问题描述**：

前端将 `redirect_uri` 透传给后端，没有校验。需要防御子域名欺骗、query/fragment 注入、用户信息注入、开放前缀匹配。支付宝/微信开放平台侧也必须配置回调域名白名单。

**改造方案**：

```python
from urllib.parse import urlparse

OAUTH_REDIRECT_URI_WHITELIST: list[str] = [
    "https://your-domain.com/login/callback",
    # 务必按 APP_ENV 组装：开发环境需追加 "http://localhost:5173/login/callback"
]

def _validate_redirect_uri(redirect_uri: str) -> None:
    parsed = urlparse(redirect_uri)
    # 生产/staging 仅允许 HTTPS；开发环境允许精确的 localhost HTTP 项
    if settings.APP_ENV in ("production", "staging"):
        if parsed.scheme != "https":
            raise HTTPException(400, detail="回调地址必须使用 HTTPS")
    if parsed.username or parsed.password:
        raise HTTPException(400, detail="无效的回调地址")
    if parsed.query or parsed.fragment:
        raise HTTPException(400, detail="回调地址不得携带查询参数或片段")
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if normalized not in OAUTH_REDIRECT_URI_WHITELIST:
        raise HTTPException(400, detail="无效的回调地址")
    allowed_hosts = {urlparse(u).netloc for u in OAUTH_REDIRECT_URI_WHITELIST}
    if parsed.netloc not in allowed_hosts:
        raise HTTPException(400, detail="无效的回调地址")
```

---

### 2.5 全局 token 吊销（改密/禁用/重置后）

**问题描述**：

当前 JWT 签发后无任何吊销机制。改密、管理员禁用、重置密码都不能使已签发的 token 失效。

**正确方案：`token_version`**

在 User 表上增加一个递增整数 `token_version`，签发 JWT 时打入 `tv` 字段，校验时比对。`token_version` 递增后，该用户所有设备上的所有旧 token 都会失效。

> 🚫 **反模式，禁止照抄**：不要把 logout 也写成 `token_version += 1`。登出只需要使当前会话失效（见 3.5 单会话登出），全局 `token_version` 只用于改密、禁用、重置。

```python
# models/user.py 新增字段
token_version: Mapped[int] = mapped_column(Integer, default=1)

# core/security.py
def create_access_token(data: dict, expires_delta=None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=settings.JWT_EXPIRATION_HOURS))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": secrets.token_urlsafe(16),
    })
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

async def get_current_user(credentials, db):
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    token_version = payload.get("tv")
    jti = payload.get("jti")

    user = db.query(User).filter(User.id == int(user_id)).first()
    user = _validate_user_status(user)

    if token_version is None or int(token_version) != user.token_version:
        raise HTTPException(401, "Token has been invalidated")

    # 检查 jti 黑名单（单会话登出，3.5 落地后启用）
    if jti and await is_jti_revoked(jti):
        raise HTTPException(401, "Token has been revoked")
    # 迁移窗口：签发侧立刻加 jti，校验侧在截止日期（如部署后 24h）前兼容无 jti 的旧 token
    # 截止日期后取消注释下面这行，强制所有 token 必须含 jti：
    # if not jti:
    #     raise HTTPException(401, "Token has been invalidated, please re-login")

    return user

def _build_token_response(user: User) -> dict:
    return {
        "access_token": create_access_token(data={
            "sub": str(user.id),
            "tv": user.token_version,
        }),
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }
```

**需要递增 `token_version` 的场景**：

| 操作 | 是否递增 |
|------|---------|
| 用户修改密码 | 是 |
| 用户重置密码 | 是 |
| 管理员禁用账号 | 是 |
| 用户登出 | **否**（见 3.5 单会话登出） |

---

### 2.6 账号枚举防护

**问题描述**：

| 端点 | 当前行为 | 枚举风险 |
|------|---------|---------|
| `/login` | 第三方账户返回"请使用原登录方式" | 可区分本地账户和 OAuth 账户 |
| `/register` | 返回"邮箱已被注册"等 | 可扫描已注册邮箱 |
| `/reset-password/request-code` | 统一文案 | 已做防护 |
| 响应时间 | 存在账号查数据库，不存在直接返回 | 时序差异可枚举 |

**改造方案**：

1. 登录接口统一所有错误为 "用户名、邮箱、手机号或密码错误"（不区分账户类型、不存在、密码错误）
2. 注册接口：**改文案不够——成功 200 / 失败 400 仍可扫库**。注册枚举只能通过以下方式解决：
   - **先发验证码再创建账号**：注册前先 `/api/v1/auth/register/send-code`，验证通过后才创建账号（见 3.8）
   - 或接受"已注册也返回成功并发送通知邮件"的产品策略
   - 当前阶段最低要求：统一错误文案为 "注册失败，请检查输入信息"
3. 不存在账号时，也执行一次 dummy bcrypt（消除时序差异）：

```python
# 登录接口中
# 在 lifespan 启动时生成一次真 bcrypt 哈希作为时序防护常量（避免模块 import 时拖慢启动）
from app.core.security import hash_password, verify_password

DUMMY_BCRYPT_HASH = None  # 由 lifespan 初始化

# 在 lifespan 中：
# DUMMY_BCRYPT_HASH = hash_password("timing-dummy-seed")

user = _find_user_by_identifier(db, credentials.username)
if not user:
    verify_password("dummy_timing_constant", DUMMY_BCRYPT_HASH)
    raise HTTPException(401, detail="用户名、邮箱、手机号或密码错误")
```

> 🚫 **反模式，禁止照抄**：不要在异步路由里用 `time.sleep()` 做时序防护，会阻塞事件循环。也不要用 `hash_password()` 做时序防护——哈希是随机 salt，耗时与校验不同。也不要用假 bcrypt 字符串（如 `"$2b$12$" + "x" * 53`），`verify_password` 会直接抛错。用 `hash_password()` 预生成真哈希，再用 `verify_password()` 模拟校验耗时。

---

## 三、P1 改造（高风险，上线后尽快修复）

### 3.1 登录与注册限流（账号+IP 维度）

**问题描述**：

所有认证端点无速率限制。需要账号+IP 复合维度。

> 🚫 **反模式，禁止照抄**：不要在限流中间件里读 `request._json`。Starlette 不会自动设置 `_json`，且中间件读 body 会导致路由层读 body 失败。账号维限流应在依赖里解析 Pydantic 之后，用 username/email/phone 的哈希做 key，不要解析两次 body。

**正确方案**：

```python
# 通用 Lua 脚本：原子 INCR + 首次设置 TTL
INCR_WITH_TTL_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

from slowapi.util import get_remote_address

# 在路由函数内部，解析完 Pydantic 后，手动做账号维限流
# 不要用装饰器做账号维（装饰器在中间件层执行，拿不到已解析的 body）
# IP 维也建议手动做，少依赖装饰器隐式注入 request 的细节
@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, request: Request, db: Session = Depends(get_db)):
    # IP 维限流
    ip_key = f"login_ip:{get_remote_address(request)}"
    ip_count = await redis_client.eval(INCR_WITH_TTL_LUA, 1, ip_key, 60)
    if ip_count > 20:
        raise HTTPException(429, detail="请求过于频繁，请稍后重试")

    # 账号维限流（在解析完 body 后，用 Lua 保证原子性）
    account_hash = hashlib.sha256(credentials.username.encode()).hexdigest()[:16]
    account_key = f"login_attempt:{account_hash}"
    count = await redis_client.eval(INCR_WITH_TTL_LUA, 1, account_key, 60)
    if count > 5:
        raise HTTPException(429, detail="登录尝试过于频繁，请稍后重试")
    # ...
```

**OAuth callback 防 code 重放**：code 在支付宝/微信侧换一次就作废，真正要防的是并发两次同时换票。锁必须放在换票**之前**：

```python
async def _acquire_code_lock(code: str, ttl: int = 30) -> str:
    """换票前获取短锁，返回 code_hash 供后续使用。"""
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    acquired = bool(await redis_client.set(f"oauth:code_lock:{code_hash}", "1", nx=True, ex=ttl))
    if not acquired:
        raise HTTPException(400, detail="授权码已被使用")
    return code_hash

async def _release_code_lock(code_hash: str) -> None:
    """换票失败时释放锁，允许用户重试。"""
    await redis_client.delete(f"oauth:code_lock:{code_hash}")

# 在 callback 中
code_hash = await _acquire_code_lock(request.code)

try:
    token_data = await alipay_service.get_access_token(request.code)
except Exception:
    await _release_code_lock(code_hash)  # 网络/超时类错误，释放锁允许重试
    raise

if "error" in token_data:
    error_msg = str(token_data.get("error_description", ""))
    error_code = str(token_data.get("error", ""))
    # 只匹配明确的 "code 已使用" 错误；支付宝 sub_code 可能为 "isv.code-invalid"
    if "code been used" in error_msg.lower() or "code-invalid" in error_code.lower():
        await redis_client.set(f"oauth:code_used:{code_hash}", "1", nx=True, ex=600)
    else:
        await _release_code_lock(code_hash)  # 签名/参数/其他错误，释放锁允许重试
    raise HTTPException(400, detail=token_data.get("error_description", "认证失败"))

# 换票成功，标记已使用
await redis_client.set(f"oauth:code_used:{code_hash}", "1", nx=True, ex=600)
```

注意：短锁 TTL 30 秒。只有明确 "code been used" 或换票成功才落 `code_used` 标记；网络/签名/其他错误释放锁允许重试。

---

### 3.2 OAuth 首次建号确认与账号合并策略

**问题描述**：

当前按 openid 找不到用户时直接自动建号，没有"首次登录确认"环节。另外：

- 微信 `openid` 按 AppId 隔离，`unionid` 才跨应用唯一，应优先按 unionid 匹配
- OAuth 用户不应分配假邮箱，应允许 `email=NULL`

> 🚫 **反模式，禁止照抄**：不要把 `oauth_user_id` 和昵称打进客户端可持有的 JWT 当"临时注册 token"。openid 不能进浏览器。应改成 Redis 存储 pending 信息（原始 openid 短期存放，4.1 后改为密文），浏览器只拿不透明 `registration_ticket`。

> 🚫 **反模式，禁止照抄**：不要在 callback 里按未验证邮箱自动提示合并。微信网页登录通常没有可靠邮箱，未验证邮箱不能作为合并依据。正确顺序是：已登录用户主动绑定，或用已验证邮箱做一次密码/验证码确认。

**改造方案**：

1. **OAuth 首次登录确认（Redis 票据）**：

> **依赖说明**：P1 建号确认先于 P2 的 openid 加密存储（4.1）。在 4.1 落地前，Redis pending 中短期存放原始 openid（TTL 10 分钟，Redis 内风险可控）；4.1 落地后改为存密文。确认接口建号时写入加密字段。

```python
# 在 callback 中，如果 openid 查不到用户
if not user:
    ticket = secrets.token_urlsafe(32)
    await redis_client.setex(
        f"oauth:pending:{ticket}",
        600,  # 10 分钟
        json.dumps({
            "provider": "alipay",
            # 4.1 落地前存原始 openid（Redis 短期，TTL 10 分钟）；4.1 后改为存密文
            "openid": alipay_user_id,
            "nickname": nick_name,
        }),
    )
    return {"status": "new_user", "registration_ticket": ticket}

# 确认建号端点（用 GETDEL 原子消费，防并发窗口）
@router.post("/oauth/confirm")
async def confirm_oauth_registration(ticket: str, action: str, db: Session = Depends(get_db)):
    pending = await redis_client.getdel(f"oauth:pending:{ticket}")  # 原子消费
    if not pending:
        raise HTTPException(400, detail="注册票据已过期，请重新登录")
    data = json.loads(pending)
    # 从 data["openid"] 还原，创建用户（4.1 后改为 crypto.decrypt）
    # ...
    # 创建用户后，记录 consent_records（OAuth 确认页也是同意场景）
    _record_consent(db, user.id, "privacy_policy", request)
    _record_consent(db, user.id, "oauth_sync", request)
```

2. **允许 OAuth 用户 email 为 NULL**：

```python
# 修改 User 模型
email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)

# OAuth 建号时
user = User(
    username=username,
    email=None,  # 不分配假邮箱
    password_hash=make_unusable_password_hash(),
    full_name=full_name,
    is_active=True,
)
```

3. **微信 unionid 优先匹配**（P1 用现有明文字段，4.1 后再换哈希字段）：

```python
# 在 handle_wechat_login 中（P1 阶段，openid 仍为明文）
if unionid:
    user = db.query(User).filter(User.wechat_unionid == unionid).first()
    if user:
        if user.wechat_openid != openid:
            user.wechat_openid = openid  # 更新 openid（可能换了 AppId）
        return user
# 再按 openid 查
user = db.query(User).filter(User.wechat_openid == openid).first()
```

---

### 3.3 授权码泄漏防护

**问题描述**：

OAuth 回调是前端路由 `/login/callback?code=xxx`。`code` 会出现在地址栏、历史记录、分析脚本、错误监控、Referer。

**改造方案**：

1. 前端错误监控 SDK 脱敏 URL 中的 code
2. 回调页设置 `Referrer-Policy: no-referrer`（nginx/CDN 层）
3. 登录成功后清除历史记录：`navigate('/home', { replace: true })`
4. 后端日志脱敏：只打印 `code[:8]`
5. 更彻底的方案（后续优化）：后端 302 换票，前端根本不碰 `code`。当前先做前 4 项

---

### 3.4 密码重置链路加固

**问题描述**：

| 问题 | 说明 |
|------|------|
| DEBUG 回传验证码 | `DEBUG=True` 时验证码出现在 `dev_code` 响应字段中 |
| Redis 内存回退 | 多实例部署时内存回退导致验证码不一致 |
| 重置成功后不失效旧 token | 攻击者拿到旧 token 仍可操作 |
| SMTP 失败策略 | 邮件发送失败后验证码已生成但未送达 |

**改造方案**：

1. 移除 `dev_code` 返回
2. 移除内存回退，Redis 不可用时返回 503
3. 重置成功后递增 `token_version`（见 2.5）
4. SMTP 失败时立即删除验证码，不返回任何信息

---

### 3.5 单会话登出（jti 吊销）

**问题描述**：

登出应只使当前会话失效，不应使所有设备下线（那是 `token_version` 的职责）。

**改造方案**：把 JWT 的 `jti` 存入 Redis 黑名单，TTL 等于 token 剩余有效期。jti 校验逻辑已在 2.5 的 `get_current_user` 中实现（迁移窗口期内兼容无 jti 的旧 token，截止日期后强制）。

```python
async def revoke_jti(jti: str, exp: int) -> None:
    """登出时吊销当前会话的 jti。"""
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(exp - now, 1)
    await redis_client.setex(f"jti:revoked:{jti}", ttl, "1")

async def is_jti_revoked(jti: str) -> bool:
    return await redis_client.exists(f"jti:revoked:{jti}") == 1
```

**与 `token_version` 的分工**：

| 操作 | 机制 | 影响范围 |
|------|------|---------|
| 改密/重置/禁用 | `token_version += 1` | 所有设备 |
| 登出 | `jti` 黑名单 | 当前会话 |
| 管理员强制下线 | `token_version += 1` | 所有设备 |

---

### 3.6 XSS 防护与前端安全基线

**问题描述**：

token 在 localStorage 的主要风险来自 XSS。在 Cookie 迁移之前，必须建立前端安全基线。

**改造方案**：

1. **CSP 头**：配置 Content-Security-Policy，限制 script-src 和 connect-src
2. **禁止 token 进日志**：前端不在 console.log 中打印 token、code、openid
3. **前端不存完整 user**：localStorage 中的 `user` 对象移除 `email`、`phone`（改为脱敏展示，需要时从 `/me` 获取），禁止存储 openid
4. **第三方脚本审计**：审查所有引入的第三方 CDN 脚本
5. **错误监控 SDK 配置**：Sentry 等配置 URL 脱敏规则

---

### 3.7 短 access token + 可吊销 refresh token

**问题描述**：

当前 JWT 24 小时有效期太长。即使有 `token_version`，在 token 被窃取后到用户察觉之间仍有最长 24 小时窗口。

**改造方案**：

- access_token 缩短至 15-30 分钟
- 新增 refresh_token 端点，有效期 7 天
- refresh token 原始值只发给客户端一次，服务端用 SHA-256 哈希后作为 Redis key：`refresh:{sha256(refresh_token)}` → `{user_id, tv, issued_at}`
- 刷新时：先验证旧 refresh → 签发新 access + 新 refresh → 成功后才删旧 key（失败时旧 key 仍可用，不回滚导致掉线）
- refresh token 在 Redis 中可被删除吊销

```python
@router.post("/refresh")
async def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    key = f"refresh:{refresh_hash}"
    # 先加短锁再读，防止并发刷新同时读到旧值
    lock_key = f"refresh:lock:{refresh_hash}"
    if not await redis_client.set(lock_key, "1", nx=True, ex=5):
        raise HTTPException(429, "刷新过于频繁，请稍后重试")
    try:
        raw = None
        raw = await redis_client.getdel(key)  # 原子消费，读到即删除
        if not raw:
            raise HTTPException(401, "Invalid or expired refresh token")
        data = json.loads(raw)
        user = db.query(User).filter(User.id == int(data["user_id"])).first()
        if not user or user.token_version != int(data.get("tv", 0)):
            raise HTTPException(401, "Token has been invalidated")
        # 签发新 access_token + 新 refresh_token
        new_access = create_access_token(data={"sub": str(user.id), "tv": user.token_version})
        new_refresh = secrets.token_urlsafe(32)
        new_key = f"refresh:{hashlib.sha256(new_refresh.encode()).hexdigest()}"
        await redis_client.setex(new_key, REFRESH_TTL, json.dumps({"user_id": user.id, "tv": user.token_version}))
        return {"access_token": new_access, "refresh_token": new_refresh}
    except Exception:
        # 签发失败：key 已被 GETDEL 删除。若不是 HTTPException（如 401 无效 refresh），
        # 尝试写回旧值（NX 避免覆盖并发请求的新值），让用户可重试
        if raw:
            await redis_client.set(key, raw, nx=True, ex=REFRESH_TTL)
        raise
    finally:
        await redis_client.delete(lock_key)
```

---

### 3.8 邮箱验证

**问题描述**：

未验证邮箱即可用于登录和密码重置。如果用户注册时填错邮箱或抢注他人邮箱，重置邮件会发到错误地址。

**改造方案**：

1. 新增 `email_verified` 和 `email_verified_at` 字段
2. 注册流程改为"先发验证码再创建账号"：`POST /api/v1/auth/register/send-code` → 验证码通过 → `POST /api/v1/auth/register/confirm` 创建账号。这同时解决注册枚举问题（见 2.6）
3. 密码重置只允许已验证邮箱
4. 登录时提示未验证邮箱（不阻止登录，但提示）
5. **存量/OAuth 账号处理**：已有未验证邮箱的存量用户，登录时提示验证；OAuth 用户 `email=NULL`，后续绑定邮箱时走验证流程，验证通过后才能用于密码重置和登录名

---

### 3.9 RBAC 初始化与水平越权防护

**问题描述**：

有 Role/Permission 模型，但未规定：
- 首个注册用户是否自动成为 super_admin
- 默认角色和权限的初始化
- 资源级别的水平越权（用户 A 能否访问用户 B 的剧本）

**改造方案**：

1. 数据库迁移中预置 `super_admin`、`admin`、`user` 三个默认角色
2. **不要**把首个注册用户自动设为 `super_admin`（公网开放注册时第一个撞到的人就是超管）。改为：
   - 提供 CLI 命令 `python manage.py create-super-admin --email xxx` 创建初始管理员
   - 或仅 `APP_ENV=development` 时首个注册用户自动获得 `super_admin`
3. 所有资源查询接口必须校验 `user_id` 归属（`WHERE user_id = current_user.id`）
4. 管理员接口用 `require_admin()` 依赖注入保护

---

## 四、P2 改造（中等风险，计划修复）

### 4.1 openid 确定性查找哈希 + 加密存储

**问题描述**：

`alipay_openid`、`wechat_openid`、`wechat_unionid` 在数据库中明文存储。

**关键约束**：

- 不能用 Fernet/AES-GCM 等带随机 nonce 的加密方式直接做等值查询
- 正确方案：**确定性查找哈希（HMAC-SHA256）用于索引 + 加密密文用于解密还原**

**改造方案**：

```python
# core/crypto.py
import hashlib
import hmac
from cryptography.fernet import Fernet

class OpenIDCrypto:
    def __init__(self, lookup_key: str, encryption_key: str):
        self._lookup_key = lookup_key.encode("utf-8")
        self._cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)

    def lookup_hash(self, openid: str) -> str:
        return hmac.new(self._lookup_key, openid.encode("utf-8"), hashlib.sha256).hexdigest()

    def encrypt(self, openid: str) -> str:
        return self._cipher.encrypt(openid.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        return self._cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
```

**User 模型调整**：

```python
alipay_openid_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
alipay_openid_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
# 同理 wechat_openid, wechat_unionid
```

注意：哈希字段必须加 `UNIQUE` 约束，防止并发建号重复。

**密钥轮换**：

- `OPENID_LOOKUP_KEY` 和 `OPENID_ENCRYPTION_KEY` 是两个独立密钥，必须分开存储
- **HMAC lookup key 轮换是所有轮换中最痛的**：换 key 后所有哈希索引必须离线重算。因此 lookup key 应设计为极低频轮换，且必须支持老 key 的查询回退
- 加密 key 轮换相对简单：用旧 key 解密，新 key 加密；支持多 key 共存

**实施步骤**：

1. 生成两个独立密钥
2. 实现 `OpenIDCrypto` 工具类
3. 创建 Alembic 迁移，新增 `_hash`(UNIQUE) / `_encrypted` 字段
4. 编写数据迁移脚本，对已有明文 openid 进行哈希+加密
5. 修改所有 openid 读写点
6. 编写密钥轮换脚本（加密 key 和 lookup key 分开处理）

---

### 4.2 账户绑定与解绑

- 已登录用户主动绑定 OAuth 账户
- 解绑 OAuth 账户（确保至少保留一种登录方式）
- OAuth 用户设置密码

---

### 4.3 用户数据权利 API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v1/user/data/export` | POST | 导出个人数据 |
| `/api/v1/user/account/delete` | POST | 注销账户（软删除 + 30 天冷静期） |
| `/api/v1/user/profile` | PUT | 修改个人信息 |
| `/api/v1/user/consent` | GET | 查看同意记录 |

**注销流程**（详见 5.3）。

---

### 4.4 审计日志（脱敏）

```python
class AuditLog(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))  # login, logout, register, etc.
    provider: Mapped[Optional[str]] = mapped_column(String(20))
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))  # HMAC 哈希
    user_agent_hash: Mapped[Optional[str]] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(default=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ❌ 不存储：验证码、token、openid、email、phone、密码
```

保留 90 天，仅管理员可查询。

---

### 4.5 认证模型迁移（httpOnly Cookie）

**前置条件**：

1. `token_version` 已实现（2.5）
2. CORS 已精确化（origin 白名单，不允许 `*`）
3. 前后端同域或已配置好反向代理

**CSRF 保护**：双重提交 cookie 必须绑到会话。CSRF token 哈希应放入 JWT payload，服务端校验时比对。取 `csrf` cookie 的值与 JWT 中的 `csrf` 字段一致才放行。注意 `SameSite=Lax` 的 access cookie 和 `Strict` 的 csrf cookie 在 OAuth 回跳时可能一个带上、一个没带——需要兼容处理。

**这是认证模型切换，需要在 staging 环境完整回归。**

---

### 4.6 密码策略与账户锁定

- 密码最小长度 8 位，含大小写字母和数字
- 连续 5 次错误后锁定账户 15 分钟（Redis 计数）
- 密码历史检查（不与最近 3 次密码重复）：**只能用独立 pepper 的哈希存储历史密码，不能复用 `password_hash` 做比对，更不能存明文**。pepper 与登录 pepper 分离，避免一处泄露同时破译历史和当前密码

---

## 五、隐私合规与个人信息保护

### 5.1 个人信息清单与数据分类分级

| 数据项 | 类型 | 敏感程度 | 存储位置 | 是否必要 |
|--------|------|---------|---------|---------|
| 邮箱 | 一般个人信息 | 中 | PostgreSQL | 是（密码重置） |
| 手机号 | 敏感个人信息 | 高 | PostgreSQL | 可选 |
| 密码哈希 | 一般个人信息 | 中 | PostgreSQL bcrypt | 是 |
| 支付宝 openid | 一般个人信息 | **高**（关联实名） | PostgreSQL 明文 ⚠️ | 是 |
| 微信 openid | 一般个人信息 | **高**（关联社交） | PostgreSQL 明文 ⚠️ | 是 |
| 微信 unionid | 一般个人信息 | **高**（跨应用） | PostgreSQL 明文 ⚠️ | 是 |
| 昵称 | 一般个人信息 | 低 | PostgreSQL | 非必要 |
| 头像 URL | 一般个人信息 | 低 | PostgreSQL | 非必要 |
| IP 地址 | 一般个人信息 | 中 | 日志/审计 | 是（安全） |
| User-Agent | 一般个人信息 | 低 | 日志/审计 | 否 |
| 剧本内容 | 用户创作内容 | 不定 | PostgreSQL/OSS | 是（核心业务） |
| TTS 音色素材 | 用户内容 | 中 | OSS | 是（有声书功能） |

> 注意：如果只是 TTS 素材而非声纹核身，不要升格为"生物识别信息"。真要做人声克隆/声纹，才走单独同意和高敏存储。

**敏感程度为"高"的数据必须加密存储（见 4.1），日志中脱敏，数据库中限制直接查询权限。**

### 5.2 同意记录（版本化、可审计）

**在当前产品阶段，以下方案足够：同意记录只存 `consent_records` 表，User 表上只保留 `consent_version` 字段（当前版本号）。**

```python
class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(50))  # privacy_policy, oauth_sync, phone_collection
    version: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))  # 同意文案的 SHA-256
    scope: Mapped[str] = mapped_column(Text)  # JSON，同意的数据范围
    ip_hash: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

**需要触发同意的场景**：

| 场景 | 是否需单独同意 |
|------|--------------|
| 注册账号 | 是 |
| 首次 OAuth 登录 | 是 |
| 收集手机号 | **是（敏感个人信息）** |
| 同步 OAuth 头像/昵称 | 是 |

**前端实现**：分步同意，不是简单 checkbox。每个场景单独勾选，分别记录同意记录。

### 5.3 数据留存与注销策略

| 数据类型 | 活跃期 | 注销后保留期 | 处理方式 |
|---------|--------|------------|---------|
| 用户基本信息 | 永久 | 30 天冷静期 | 冷静期后匿名化 |
| OAuth 关联 | 永久 | 30 天 | 冷静期后断开 |
| 剧本内容 | 永久 | 用户选择 | 匿名化或删除 |
| 音频文件 | 永久 | 用户选择 | 匿名化或删除 |
| 账单记录 | 7 年 | 7 年 | 法定保留，匿名化字段：姓名→哈希，去手机号 |
| 审计日志 | 90 天 | 90 天 | 自动清理 |
| 同意记录 | 永久 | 永久 | 注销后保留（合规证明） |
| 备份数据 | 30 天 | 与主库同步 | 逻辑删除同步到备份 |

> 注意：主库 30 天冷静期 + 备份 30 天保留 = 实际删除时间约 60 天。账单 7 年法定保留中，匿名化字段必须明确到列级别（哪些字段保留、哪些脱敏）。

### 5.4 第三方共享与出境评估

| 第三方 | 传输字段 | 目的 | 数据所在地 | 是否触发 PIPL 出境 |
|--------|---------|------|-----------|------------------|
| 支付宝 | app_id, code | OAuth 登录 | 以合同为准 | **待核实** |
| 微信 | appid, secret, code | OAuth 登录 | 以合同为准 | **待核实** |
| DeepSeek | 剧本内容 | AI 编辑 | 以合同为准 | **待核实** |
| 火山引擎/Doubao | 剧本内容 | AI 生成 | 以合同为准 | **待核实** |
| OSS | 音频/素材 | 存储 | 以实际 region 为准 | **待核实** |
| SMTP 邮件服务 | email, 验证码 | 密码重置 | 以实际服务商为准 | **待核实** |

> 以上数据所在地和出境状态**必须以实际账号注册地域和子处理器清单为准**，不能写死为"中国大陆、不出境"。如果 SMTP 使用境外服务（如 SendGrid、AWS SES），需做个人信息出境影响评估。

### 5.5 安全事件响应预案

**常见事件**：

| 事件类型 | 判定标准 | 响应动作 |
|---------|---------|---------|
| JWT 密钥泄露 | `JWT_SECRET` 被提交到版本控制或泄露 | 1. 轮换密钥 2. 递增所有用户 token_version 3. 通知用户 |
| OAuth 配置错误 | code 打到错误域名、app_secret 泄露 | 1. 重置密钥 2. 递增受影响用户 token_version 3. 审查日志 |
| 验证码接口被扫 | 重置码接口 QPS 异常升高 | 1. 启用 stricter 限流 2. 检查异常重置 3. 通知用户 |
| 数据库泄露 | openid/email 等泄露 | 1. 确认范围 2. 通知用户 3. 向监管报告 4. 加速加密改造 |
| XSS 导致 token 泄露 | 发现 XSS 漏洞 | 1. 递增所有用户 token_version 2. 修复 XSS 3. 评估通知 |

**内部升级标准**：并非所有泄露都自动触发向网信办报告。需定义：
- 受影响用户数 ≥ 100 或涉及敏感个人信息 → 启动内部应急响应，24 小时内评估是否向监管报告
- 明确事件宣布人（技术负责人 + 法务），避免多人对外口径不一致
- 72 小时内完成初步通知（受影响用户 + 监管）

**隐私政策最小大纲**（`consent_records.content_hash` 的哈希对象必须基于此）：

1. 收集的个人信息类型（邮箱、手机号、OAuth 标识、昵称、头像、IP 地址）
2. 收集目的与使用方式（登录认证、密码重置、个性化展示）
3. 保存期限（见 5.3）
4. 第三方共享清单（见 5.4）
5. 用户权利与行使方式（查阅、更正、删除、导出、撤回同意）
6. 个人信息保护负责人联系方式：`privacy@your-domain.com`
7. 隐私政策更新时通知用户的方式

### 5.6 未成年人保护

- 如果产品**不面向 14 岁以下未成年人**，在隐私政策和服务协议中明确声明，并制定发现后处置流程（如删除账号）
- 如果产品**面向或可能面向未成年人**，需要：
  - 强制年龄验证（注册时必填出生日期）
  - 14 岁以下需监护人同意流程
  - 未成年人模式
- "可选填年龄"不构成 PIPL 第 31 条合规
- 用户创作内容中如涉及未成年人个人信息，需有相应的保护措施

---

## 六、附录

### 6.1 相关文件清单

**后端**：`backend/app/api/v1/auth.py`, `backend/app/core/security.py`, `backend/app/core/config.py`, `backend/app/models/user.py`, `backend/app/services/oauth_service.py`, `backend/app/services/password_reset_service.py`, `backend/app/services/email_service.py`, `backend/tests/test_auth_routes.py`

**前端**：`frontend/src/store/slices/authSlice.ts`, `frontend/src/services/api.ts`, `frontend/src/utils/auth.ts`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/LoginCallbackPage.tsx`, `frontend/src/pages/RegisterPage.tsx`

### 6.2 环境变量配置模板

```bash
# ============================================================
# 认证与安全配置
# ============================================================

# 运行环境（development | staging | production）
APP_ENV=development

# JWT 配置（生产环境必填！）
JWT_SECRET=<openssl rand -hex 32>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
# 短 token 方案启用后（3.7）：
# JWT_ACCESS_EXPIRATION_MINUTES=30
# JWT_REFRESH_EXPIRATION_DAYS=7

# 调试模式（生产环境必须为 False）
DEBUG=False

# 支付宝 OAuth 配置
ALIPAY_APP_ID=
ALIPAY_PRIVATE_KEY=<应用私钥，PEM 格式>
ALIPAY_PUBLIC_KEY=<支付宝公钥，PEM 格式>
ALIPAY_SANDBOX=False

# 微信 OAuth 配置
WECHAT_APP_ID=
WECHAT_APP_SECRET=

# OAuth 安全配置（按环境注入：开发可含 localhost，staging/生产仅 HTTPS）
OAUTH_REDIRECT_URI_WHITELIST=["https://your-domain.com/login/callback"]
# 开发环境追加：,"http://localhost:5173/login/callback"

# openid 加密密钥（两个独立密钥，必须分开存储）
OPENID_LOOKUP_KEY=<openssl rand -hex 32>
OPENID_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">

# 速率限制
AUTH_RATE_LIMIT_LOGIN_IP=20/minute
AUTH_RATE_LIMIT_LOGIN_ACCOUNT=5/minute
AUTH_RATE_LIMIT_REGISTER=3/minute
AUTH_RATE_LIMIT_PASSWORD_RESET=1/minute

# 密码策略
PASSWORD_MIN_LENGTH=8
ACCOUNT_LOCKOUT_ATTEMPTS=5
ACCOUNT_LOCKOUT_MINUTES=15

# 审计日志
AUDIT_LOG_RETENTION_DAYS=90

# Redis（必须高可用，P0 关键路径）
REDIS_URL=redis://localhost:6379/0

# 邮件服务
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=拾光工坊
```

### 6.3 改造优先级总览

| 优先级 | 编号 | 改造项 | 性质 |
|--------|------|--------|------|
| **P0** | 2.1 | 生产环境安全基线（密钥/DEBUG/安全头/脱敏） | 安全基础 |
| **P0** | 2.2 | 支付宝 RSA2 签名与验签 ✅（自实现，未含沙箱开关） | 功能阻断 |
| **P0** | 2.3 | OAuth state 服务端原子消费 | CSRF 防护 |
| **P0** | 2.4 | redirect_uri 精确白名单 | 开放重定向 |
| **P0** | 2.5 | 全局 token_version 吊销（改密/禁用/重置） | 会话安全 |
| **P0** | 2.6 | 账号枚举防护 | 隐私保护 |
| **P1** | 3.1 | 登录限流（账号+IP 维度） | 防暴力破解 |
| **P1** | 3.2 | OAuth 首次建号确认（Redis 票据） + 允许无邮箱 | 用户权益 |
| **P1** | 3.3 | 授权码泄漏防护 | 数据安全 |
| **P1** | 3.4 | 密码重置链路加固 | 安全加固 |
| **P1** | 3.5 | 单会话登出（jti 吊销） | 会话管理 |
| **P1** | 3.6 | XSS 防护与前端安全基线 | 安全基础 |
| **P1** | 3.7 | 短 access token + 可吊销 refresh token | 会话安全 |
| **P1** | 3.8 | 邮箱验证 | 账户安全 |
| **P1** | 3.9 | RBAC 初始化与水平越权防护 | 授权安全 |
| **P2** | 4.1 | openid 确定性哈希 + 加密存储 | 数据安全 |
| **P2** | 4.2 | 账户绑定/解绑 | 用户权益 |
| **P2** | 4.3 | 用户数据权利 API | 合规 |
| **P2** | 4.4 | 审计日志（脱敏） | 合规 |
| **P2** | 4.5 | httpOnly Cookie 迁移 | 认证模型升级 |
| **P2** | 4.6 | 密码策略与账户锁定 | 账户安全 |
| **合规** | 5.2 | 同意记录（版本化） | 合规 |
| **合规** | 5.3 | 数据留存与注销策略 | 合规 |
| **合规** | 5.4 | 第三方共享与出境评估 | 合规 |
| **合规** | 5.5 | 安全事件响应预案 | 合规 |
| **合规** | 5.6 | 未成年人保护 | 合规 |

---

> **文档维护说明**：本文档随登录系统的改造迭代持续更新。完成每项改造后更新对应章节的状态标记。标记了 `🚫 反模式，禁止照抄` 的章节包含已知错误方案，实施时务必阅读替代方案。P0 全部完成后才能进入 P1。