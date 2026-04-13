# 部署文件说明

## 📦 核心部署文件

### 1. deploy_unified.bat ⭐⭐⭐⭐⭐ （推荐）
**统一部署脚本 - 最完整、最可靠**

```powershell
.\deploy_unified.bat
```

**特点**：
- ✅ 自动扫描所有文件
- ✅ 完整进度显示
- ✅ 详细日志记录
- ✅ 自动验证部署
- ✅ 免密码登录（已配置）

**适用场景**：
- 生产环境部署
- 重要功能更新
- 首次部署

---

### 2. deploy_git.bat ⭐⭐⭐⭐
**Git 智能部署 - 最快速**

```powershell
.\deploy_git.bat
```

**特点**：
- ✅ 自动检测 Git 修改
- ✅ 仅同步变更文件
- ✅ 速度最快
- ✅ 免密码登录（已配置）

**适用场景**：
- 日常开发迭代
- 快速测试部署
- 少量文件修改

---

### 3. deploy_smart.ps1 ⭐⭐⭐⭐
**PowerShell 智能部署**

```powershell
# 模拟运行（预览）
.\deploy_smart.ps1 -DryRun

# 实际部署
.\deploy_smart.ps1

# 自定义服务器
.\deploy_smart.ps1 -ServerIP "新IP" -ServerUser "新用户"
```

**特点**：
- ✅ 彩色输出
- ✅ 参数化配置
- ✅ 支持模拟运行
- ✅ 免密码登录（已配置）

**适用场景**：
- PowerShell 环境
- 需要自定义参数
- 预览部署内容

---

### 4. deploy_sync_full.ps1 ⭐⭐⭐⭐
**双向同步部署 - 支持删除同步**

```powershell
# 模拟运行（预览将删除的文件）
.\deploy_sync_full.ps1 -DryRun

# 实际同步（包含删除）
.\deploy_sync_full.ps1

# 仅上传，不删除
.\deploy_sync_full.ps1 -SkipDelete
```

**特点**：
- 上传本地文件
- 删除云端冗余文件
- 双向同步
- 支持模拟运行
- 支持 SSH 免密登录（已配置）

**适用场景**：
- 删除本地功能模块
- 清理废弃代码
- 保持云端与本地一致

---

## SSH 免密登录配置

### 已配置完成

您的 SSH 密钥已配置完成，可以免密登录并运行所有部署脚本。

**密钥位置**：
- 私钥：`C:\Users\cuigu\.ssh\id_rsa`
- 公钥：`C:\Users\cuigu\.ssh\id_rsa.pub`

**验证免密登录**：
```powershell
ssh root@101.132.154.143 "echo '免密登录成功！'"
```

### 🔧 如需重新配置

如果需要为其他服务器配置免密码登录：

```powershell
# 方法 1: 使用配置脚本
.\setup_ssh_key.bat

# 方法 2: 手动配置
$pubKey = Get-Content "$env:USERPROFILE\.ssh\id_rsa.pub" -Raw
ssh user@server "echo '$pubKey' >> ~/.ssh/authorized_keys"
```

---

## 🚀 快速开始

### 首次部署流程

```powershell
# 1. 预览部署内容
.\deploy_smart.ps1 -DryRun

# 2. 执行部署
.\deploy_unified.bat

# 3. 验证部署
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"
```

### 日常部署流程

```powershell
# 快速部署（推荐）
.\deploy_git.bat

# 或完整部署
.\deploy_unified.bat
```

### 清理部署流程

```powershell
# 1. 预览将删除的文件
.\deploy_sync_full.ps1 -DryRun

# 2. 确认无误后执行
.\deploy_sync_full.ps1
```

---

## 📊 文件对比

| 脚本 | 速度 | 可靠性 | 功能 | 删除同步 | 推荐度 |
|------|------|--------|------|----------|--------|
| deploy_unified.bat | 中等 | ⭐⭐⭐⭐⭐ | 最全面 | ❌ | ⭐⭐⭐⭐⭐ |
| deploy_git.bat | 最快 | ⭐⭐⭐⭐ | 智能检测 | ❌ | ⭐⭐⭐⭐ |
| deploy_smart.ps1 | 快 | ⭐⭐⭐⭐ | 参数化 | ❌ | ⭐⭐⭐⭐ |
| deploy_sync_full.ps1 | 慢 | ⭐⭐⭐⭐⭐ | 双向同步 | ✅ | ⭐⭐⭐⭐ |

---

## ⚠️ 重要说明：文件删除同步

### 当前部署脚本的行为

| 操作 | deploy_unified.bat | deploy_git.bat | deploy_smart.ps1 | deploy_sync_full.ps1 |
|------|-------------------|----------------|------------------|---------------------|
| **新增文件** | ✅ 上传 | ✅ 上传 | ✅ 上传 | ✅ 上传 |
| **修改文件** | ✅ 更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 |
| **删除文件** | ❌ 保留 | ❌ 保留 | ❌ 保留 | ✅ **删除** |

### 解决方案

#### 方案 1：使用双向同步脚本（推荐）

```powershell
# 1. 先预览将删除的文件（安全检查）
.\deploy_sync_full.ps1 -DryRun

# 2. 确认无误后执行
.\deploy_sync_full.ps1
```

#### 方案 2：手动删除

```powershell
# SSH 登录服务器
ssh root@101.132.154.143

# 删除不需要的文件
cd /root/novel_writing_agent
rm -rf agents/old_module.py

# 重启服务
docker-compose restart backend
```

---

## 🔧 常见问题

### 1. 编码错误

**问题**：出现乱码或编码错误

**解决**：
- ✅ 已修复：所有脚本使用纯英文
- 推荐使用 PowerShell 版本：`deploy_smart.ps1`

### 2. 每次都需要输入密码

**问题**：运行部署脚本时需要输入密码

**解决**：
```powershell
# 运行 SSH 配置脚本
.\setup_ssh_key.bat

# 或手动配置
$pubKey = Get-Content "$env:USERPROFILE\.ssh\id_rsa.pub" -Raw
ssh root@101.132.154.143 "echo '$pubKey' >> ~/.ssh/authorized_keys"
```

### 3. 上传失败

**问题**：文件上传失败

**解决**：
```powershell
# 检查服务器连接
ssh root@101.132.154.143 "echo '连接成功'"

# 检查磁盘空间
ssh root@101.132.154.143 "df -h"

# 检查服务状态
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"
```

### 4. 构建失败

**问题**：后端镜像构建失败

**解决**：
```powershell
# 查看构建日志
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs backend"

# 手动构建
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose build backend"

# 重启服务
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose restart backend"
```

### 5. API 无响应

**问题**：部署后 API 无法访问

**解决**：
```powershell
# 检查容器状态
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"

# 检查后端日志
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs --tail=100 backend"

# 测试 API
ssh root@101.132.154.143 "curl -s http://localhost:8000/api/v1/health"
```

---

## 📝 配置文件

### deploy_config.json

定义同步规则和构建参数，可根据项目需求修改。

### deploy.sh

服务器端部署脚本，由其他脚本自动调用。

---

## 🎯 最佳实践

### 开发阶段

```powershell
# 快速迭代
.\deploy_git.bat
```

### 测试阶段

```powershell
# 完整验证
.\deploy_unified.bat

# 或预览后部署
.\deploy_smart.ps1 -DryRun
.\deploy_smart.ps1
```

### 生产部署

```powershell
# 1. 完整部署
.\deploy_unified.bat

# 2. 手动验证
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose ps"

# 3. 测试功能
# 访问 http://101.132.154.143
```

### 清理部署

```powershell
# 删除功能模块后
.\deploy_sync_full.ps1 -DryRun  # 预览
.\deploy_sync_full.ps1          # 执行
```

### 紧急修复

```powershell
# 快速修复
.\deploy_git.bat

# 验证
ssh root@101.132.154.143 "curl -s http://localhost:8000/api/v1/health"
```

---

## 📈 部署流程图

```
开始
  ↓
是否删除功能？ ──Yes──→ deploy_sync_full.ps1 -DryRun
  │                              ↓
  No                          确认删除？
  ↓                              ↓
是否首次部署？ ──Yes──→ deploy_unified.bat
  │                              ↓
  No                          完成
  ↓
是否少量修改？ ──Yes──→ deploy_git.bat
  │                              ↓
  No                          完成
  ↓
deploy_unified.bat
  ↓
完成
```

---

## 🔒 安全建议

1. **保护私钥**：`C:\Users\cuigu\.ssh\id_rsa` 是私钥，请勿泄露
2. **备份密钥**：建议备份私钥到安全位置
3. **定期检查**：定期检查服务器上的 `~/.ssh/authorized_keys`
4. **使用强密码**：服务器密码应使用强密码
5. **限制访问**：生产环境建议限制 SSH 访问 IP

---

## 📞 支持

如遇问题，请检查：
1. 网络连接是否正常
2. SSH 密钥是否正确配置
3. 服务器磁盘空间是否充足
4. Docker 服务是否正常运行

---

**最后更新**: 2026-03-13
**版本**: 4.0
**维护者**: Novel Writing Agent Team
