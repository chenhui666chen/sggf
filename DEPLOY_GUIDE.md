# 部署指南

## 当前结论

当前仓库的正式部署体系只保留以下 4 个文件：

- `deploy_unified.bat`
- `deploy_sync_improved.ps1`
- `deploy_config.json`
- `DEPLOY_GUIDE.md`

旧的包装脚本、服务器内手工部署脚本和重复部署文档已经移除，不再维护第二套部署链路。

## 核心文件职责

| 文件 | 作用 |
|------|------|
| `deploy_unified.bat` | Windows 推荐入口，负责转调主脚本 |
| `deploy_sync_improved.ps1` | 真实部署实现，负责同步、远端删除、重建、校验 |
| `deploy_config.json` | 唯一部署配置入口，定义远端地址、同步规则、构建与校验参数 |
| `DEPLOY_GUIDE.md` | 唯一部署说明文档 |

## 当前线上路径

- 远端项目目录：`/data/apps/novel_writing_agent`
- Docker 根目录：`/data/docker`
- 后端健康检查：`http://127.0.0.1:8000/health`

## Compose 兼容性

- `deploy_sync_improved.ps1` 会在远端自动探测 `docker compose` 或 `docker-compose`
- 如果目标服务器只安装了其中一种写法，脚本会自动回退，不需要手工改脚本
- 手工排查时也建议使用同样的探测方式，避免环境差异导致误判

## 推荐用法

### 1. Windows 入口

```powershell
.\deploy_unified.bat
```

### 2. 直接执行主脚本

```powershell
.\deploy_sync_improved.ps1
```

### 3. 预演同步结果

```powershell
.\deploy_sync_improved.ps1 -DryRun
```

### 4. 跳过远端删除

```powershell
.\deploy_sync_improved.ps1 -SkipDelete
```

### 5. 只同步文件，不做构建

```powershell
.\deploy_sync_improved.ps1 -SkipBuild
```

### 6. 跳过健康检查

```powershell
.\deploy_sync_improved.ps1 -SkipValidation
```

## 部署流程

主脚本当前执行顺序如下：

1. 读取 `deploy_config.json`
2. 预检远端 Compose 命令，自动选择 `docker compose` 或 `docker-compose`
3. 按同步规则扫描本地文件
4. 扫描远端文件并计算删除清单
5. 上传文件到远端项目目录
6. 删除远端多余文件
7. 执行容器重建与启动
8. 校验容器状态并重试探测后端健康检查

## 配置说明

`deploy_config.json` 是唯一配置入口，重点字段如下：

```json
{
  "server": {
    "ip": "101.132.154.143",
    "user": "root",
    "remote_path": "/data/apps/novel_writing_agent"
  },
  "validation": {
    "api_endpoint": "/health"
  }
}
```

如需修改服务器地址、远端目录、同步范围或校验策略，统一修改 `deploy_config.json`，不要再引入新的部署脚本或分散配置。

## 常用检查命令

### 查看线上容器状态

```powershell
ssh root@101.132.154.143 "cd /data/apps/novel_writing_agent && if docker compose version >/dev/null 2>&1; then docker compose ps; else docker-compose ps; fi"
```

### 查看后端健康状态

```powershell
ssh root@101.132.154.143 "curl -sS http://127.0.0.1:8000/health"
```

### 查看磁盘占用

```powershell
ssh root@101.132.154.143 "df -h / /data"
```

### 查看 Docker 根目录

```powershell
ssh root@101.132.154.143 "docker info --format '{{.DockerRootDir}}'"
```

## 维护原则

- 日常部署统一使用 `deploy_unified.bat` 或 `deploy_sync_improved.ps1`
- 不再恢复或新增旧部署脚本
- 路径、同步规则、构建参数和健康检查都只在 `deploy_config.json` 与主脚本中维护
- 手工排查容器时，默认按脚本一致的方式先探测远端 Compose 命令再执行
