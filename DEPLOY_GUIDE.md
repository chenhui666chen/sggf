# 拾光工坊 - 部署脚本使用指南

## 📚 脚本概览

本项目提供了多个部署脚本，适用于不同的场景：

| 脚本名称 | 适用场景 | 速度 | 可靠性 | 推荐度 |
|---------|---------|------|--------|--------|
| `deploy_unified.bat` | **推荐使用** - 完整部署 | 中等 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| `deploy_smart.ps1` | PowerShell 环境 - 智能部署 | 快 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| `deploy_git.bat` | Git 仓库 - 仅同步修改 | 最快 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| `deploy_incremental.bat` | 快速增量更新 | 最快 | ⭐⭐⭐ | ⭐⭐⭐ |
| `deploy_optimized.bat` | 压缩包上传 | 慢 | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| `sync_all.bat` | 手动指定文件 | 快 | ⭐⭐⭐ | ⭐⭐ |

## 🚀 快速开始

### 1. 推荐方式：统一部署脚本

```powershell
.\deploy_unified.bat
```

**特点**：
- ✅ 自动扫描所有必要文件
- ✅ 完整的进度显示
- ✅ 详细的日志记录
- ✅ 自动构建和重启
- ✅ 部署验证

**适用场景**：
- 首次部署
- 大量文件修改
- 需要完整同步
- 生产环境部署

### 2. 快速方式：Git 智能部署

```powershell
.\deploy_git.bat
```

**特点**：
- ✅ 自动检测 Git 修改
- ✅ 仅同步变更文件
- ✅ 速度最快
- ✅ 适合开发阶段

**适用场景**：
- 使用 Git 版本控制
- 少量文件修改
- 频繁部署测试

### 3. PowerShell 智能部署

```powershell
.\deploy_smart.ps1
```

**特点**：
- ✅ 彩色输出
- ✅ 参数化配置
- ✅ 支持模拟运行
- ✅ 错误处理完善

**参数**：
```powershell
# 模拟运行（不实际部署）
.\deploy_smart.ps1 -DryRun

# 强制部署（跳过确认）
.\deploy_smart.ps1 -Force

# 自定义服务器
.\deploy_smart.ps1 -ServerIP "192.168.1.100" -ServerUser "admin"
```

## 📋 详细说明

### deploy_unified.bat（推荐）

**完整流程**：
1. 环境检查（检查 scp、ssh 命令）
2. 文件扫描与分类（后端、前端、其他）
3. 创建同步清单
4. 文件同步（带进度显示）
5. 服务构建与重启
6. 部署验证

**优点**：
- 最全面的检查
- 最详细的日志
- 最可靠的结果

**缺点**：
- 时间较长（3-5 分钟）
- 需要确认步骤

### deploy_smart.ps1

**使用场景**：
- PowerShell 环境
- 需要彩色输出
- 需要参数化配置

**示例**：
```powershell
# 查看帮助
Get-Help .\deploy_smart.ps1 -Detailed

# 模拟运行
.\deploy_smart.ps1 -DryRun

# 实际部署
.\deploy_smart.ps1
```

### deploy_git.bat

**前提条件**：
- 项目必须是 Git 仓库
- 需要提交或暂存修改

**工作原理**：
1. 运行 `git status` 检测修改
2. 仅上传修改的文件
3. 重新构建并重启

**优点**：
- 速度最快
- 带宽占用最小

**缺点**：
- 依赖 Git
- 可能遗漏未跟踪文件

### deploy_incremental.bat

**适用场景**：
- 已知修改的具体文件
- 快速热修复

**特点**：
- 手动指定文件列表
- 最简单的逻辑
- 速度很快

**注意**：
- 需要手动维护文件列表
- 可能遗漏文件

### deploy_optimized.bat

**工作原理**：
1. 创建压缩包（排除 node_modules 等）
2. 上传压缩包到服务器
3. 解压并部署

**优点**：
- 适合网络不稳定
- 可断点续传

**缺点**：
- 时间最长
- 需要额外磁盘空间

### sync_all.bat

**适用场景**：
- 手动指定文件
- 临时同步

**特点**：
- 文件列表硬编码
- 简单直接

## ⚙️ 配置文件

### deploy_config.json

配置文件定义了同步规则和构建参数：

```json
{
  "server": {
    "ip": "101.132.154.143",
    "user": "root",
    "remote_path": "/root/novel_writing_agent"
  },
  "sync_rules": {
    "backend": {
      "include": ["backend/app/**/*.py"],
      "exclude": ["backend/**/__pycache__/**"]
    }
  }
}
```

## 🔧 高级用法

### 1. 自定义服务器配置

编辑脚本开头的变量：

```batch
set SERVER_IP=你的服务器IP
set SERVER_USER=你的用户名
set REMOTE_PATH=你的远程路径
```

### 2. 排除特定文件

在 `deploy_config.json` 中添加排除规则：

```json
{
  "sync_rules": {
    "backend": {
      "exclude": [
        "backend/**/__pycache__/**",
        "backend/**/*.pyc",
        "backend/tests/**"
      ]
    }
  }
}
```

### 3. 仅重启服务（不上传）

```powershell
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose restart backend frontend"
```

### 4. 查看部署日志

```powershell
# 本地日志
type deploy_20260313_123456.log

# 服务器日志
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs --tail=100 backend"
```

## 🚨 常见问题

### 1. 上传失败

**原因**：
- 网络连接问题
- 服务器磁盘空间不足
- 权限问题

**解决**：
```powershell
# 检查服务器连接
ssh root@101.132.154.143 "echo '连接成功'"

# 检查磁盘空间
ssh root@101.132.154.143 "df -h"

# 检查权限
ssh root@101.132.154.143 "ls -la /root/novel_writing_agent"
```

### 2. 构建失败

**原因**：
- Python 依赖问题
- 语法错误
- 配置文件错误

**解决**：
```powershell
# 查看构建日志
ssh root@101.132.154.143 "cd /root/novel_writing_agent && docker-compose logs backend"

# 本地测试
python -m py_compile backend/app/main.py
```

### 3. 服务启动失败

**原因**：
- 端口占用
- 环境变量缺失
- 数据库连接失败

**解决**：
```powershell
# 检查端口
ssh root@101.132.154.143 "netstat -tulpn | grep 8000"

# 检查环境变量
ssh root@101.132.154.143 "cd /root/novel_writing_agent && cat .env"

# 检查数据库
ssh root@101.132.154.143 "docker-compose ps postgres"
```

### 4. API 无响应

**原因**：
- 服务未启动
- 健康检查失败
- Nginx 配置错误

**解决**：
```powershell
# 检查容器状态
ssh root@101.132.154.143 "docker ps -a"

# 检查 API
ssh root@101.132.154.143 "curl http://localhost:8000/api/v1/health"

# 检查 Nginx
ssh root@101.132.154.143 "docker-compose logs nginx"
```

## 📊 性能对比

| 脚本 | 文件数 | 上传时间 | 构建时间 | 总时间 |
|------|--------|---------|---------|--------|
| deploy_unified.bat | 251 | 2-3 分钟 | 3-5 分钟 | 5-8 分钟 |
| deploy_git.bat | 10-20 | 10-30 秒 | 3-5 分钟 | 3-6 分钟 |
| deploy_smart.ps1 | 251 | 2-3 分钟 | 3-5 分钟 | 5-8 分钟 |
| deploy_incremental.bat | 5-10 | 5-10 秒 | 3-5 分钟 | 3-6 分钟 |

## 🎯 最佳实践

### 1. 开发阶段
使用 `deploy_git.bat` 快速迭代

### 2. 测试阶段
使用 `deploy_unified.bat` 完整验证

### 3. 生产部署
使用 `deploy_unified.bat` + 手动验证

### 4. 紧急修复
使用 `deploy_incremental.bat` 快速修复

## 📝 维护建议

1. **定期更新脚本**：根据项目变化更新文件列表
2. **保留日志**：每次部署的日志文件建议保留
3. **版本控制**：将部署脚本纳入 Git 管理
4. **文档同步**：修改脚本后更新本文档

## 🔗 相关链接

- 服务器: http://101.132.154.143
- HTTPS: https://sggf.net
- 域名: https://www.sggf.net

---

**最后更新**: 2026-03-13
**版本**: 3.0
