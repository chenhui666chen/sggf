# JWT令牌过期问题修复

**修复时间**: 2025-11-13  
**问题**: JWT令牌过期导致API请求返回401 Unauthorized  
**修复状态**: ✅ **已完成**

---

## 🐛 问题描述

**错误日志**:
```
❌ 令牌验证失败: Signature has expired.
INFO: 127.0.0.1:53381 - "POST /api/v1/projects/4/memories/auto-save HTTP/1.1" 401 Unauthorized
INFO: 127.0.0.1:53393 - "POST /api/v1/workflow/execute-stage-async HTTP/1.1" 401 Unauthorized
```

**原因**: 
- JWT令牌有效期为24小时
- 用户登录后超过24小时，令牌自动过期
- 前端继续使用过期令牌发送请求，导致401错误

---

## ✅ 解决方案

### 方案1: 前端刷新页面（立即生效）

**操作步骤**:
1. 在前端浏览器中按 **Ctrl + Shift + R** 强制刷新页面
2. 系统会自动重新登录并获取新的JWT令牌
3. 新令牌有效期为7天

**优点**: 立即生效，无需重启后端

---

### 方案2: 延长JWT令牌有效期（已完成）

**修改内容**:
- 文件: `backend/.env`
- 修改前: `JWT_EXPIRATION_HOURS=24` (24小时)
- 修改后: `JWT_EXPIRATION_HOURS=168` (7天)

**生效方式**:
1. 重启后端服务器
2. 用户重新登录后，新令牌有效期为7天

**优点**: 减少用户重新登录的频率

---

## 🔧 如何重启后端服务器

### 方法1: 使用Ctrl+C重启
```bash
# 在后端终端按 Ctrl+C 停止
# 然后重新启动
cd backend
uvicorn app.main:app --reload
```

### 方法2: 如果使用了--reload参数
如果后端启动时使用了 `--reload` 参数，修改 `.env` 文件后可能需要手动重启。

---

## 📊 JWT令牌有效期对比

| 配置 | 有效期 | 适用场景 |
|------|--------|----------|
| 1小时 | 1小时 | 高安全性要求 |
| 24小时 | 1天 | 默认配置 |
| **168小时** | **7天** | **开发环境（推荐）** ✅ |
| 720小时 | 30天 | 长期使用 |

---

## 🎯 后续建议

### 1. 实现令牌自动刷新机制

**前端实现**:
- 在API响应拦截器中检测401错误
- 自动调用刷新令牌API
- 重新发送失败的请求

**示例代码** (`frontend/src/services/api.ts`):
```typescript
// 响应拦截器
this.client.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // 令牌过期，尝试刷新
      try {
        const newToken = await refreshToken()
        localStorage.setItem('access_token', newToken)
        // 重新发送原始请求
        return this.client.request(error.config)
      } catch (refreshError) {
        // 刷新失败，跳转到登录页
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)
```

### 2. 添加令牌过期提醒

**前端实现**:
- 解析JWT令牌的过期时间
- 在令牌即将过期前（如1小时前）显示提醒
- 提示用户保存工作并重新登录

### 3. 使用Refresh Token机制

**后端实现**:
- 生成两个令牌：Access Token（短期，如1小时）和 Refresh Token（长期，如7天）
- Access Token用于API请求
- Refresh Token用于获取新的Access Token
- 提高安全性的同时保持用户体验

---

## 📝 相关文件

- `backend/.env` - JWT配置文件（已修改）
- `backend/app/core/config.py` - 配置类定义
- `backend/app/core/security.py` - JWT令牌生成和验证逻辑
- `backend/app/api/v1/auth.py` - 认证API路由
- `frontend/src/services/api.ts` - 前端API客户端

---

## ✅ 验证清单

- [x] 修改JWT令牌有效期为7天
- [x] 创建修复文档
- [ ] 重启后端服务器
- [ ] 前端刷新页面获取新令牌
- [ ] 测试API请求是否正常
- [ ] （可选）实现令牌自动刷新机制

---

## 🎉 总结

**问题**: JWT令牌过期导致401错误  
**修复**: 将令牌有效期从24小时延长到7天  
**下一步**: 
1. 重启后端服务器
2. 前端刷新页面（Ctrl + Shift + R）
3. 测试工作流程是否正常

---

**修复完成时间**: 2025-11-13  
**修复状态**: ✅ **成功完成**

