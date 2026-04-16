# 部署指南

## 当前保留的部署文件

当前仓库正式部署只保留以下 4 个文件：

- `deploy_unified.bat`
- `deploy_sync_improved.ps1`
- `deploy_config.json`
- `DEPLOY_GUIDE.md`

旧的部署脚本、重复入口和分叉文档不再维护。

## 文件职责

| 文件 | 作用 |
| --- | --- |
| `deploy_unified.bat` | Windows 推荐入口，负责转调 PowerShell 主脚本 |
| `deploy_sync_improved.ps1` | 正式部署实现，负责同步、远端删除、重建和校验 |
| `deploy_config.json` | 唯一部署配置入口，定义远端地址、同步规则、上传策略和校验参数 |
| `DEPLOY_GUIDE.md` | 唯一部署说明文档 |

## 当前线上路径

- 远端项目目录：`/data/apps/novel_writing_agent`
- Docker 根目录：`/data/docker`
- 后端健康检查：`http://127.0.0.1:8000/health`

## 上传策略

当前主脚本默认使用“归档上传优先，逐文件回退”策略：

1. 本地和远端都存在 `tar` 时，先把选中的文件打成一个 `.tar.gz` 包，只上传一次，再在远端解压。
2. 任一侧缺少 `tar` 时，自动回退到逐文件 `scp` 上传。
3. 仍然保留远端多余文件删除、Compose 重建和健康校验逻辑。

这样做的目的很直接：

- 明显减少逐文件 `scp` 导致的长时间部署窗口
- 降低正式部署时本地命令超时的概率
- 保持与当前目录收敛方案兼容，不引入新的部署入口

可选策略值如下：

- `Auto`：默认值，优先归档上传，缺失能力时自动回退
- `Archive`：强制使用归档上传；若本地或远端没有 `tar` 则直接报错
- `PerFile`：强制逐文件上传

对应配置位于 [deploy_config.json](C:/Users/cuigu/novel_writing_agent/deploy_config.json)：

```json
{
  "upload": {
    "strategy": "Auto"
  }
}
```

## Compose 兼容性

`deploy_sync_improved.ps1` 会自动探测远端可用命令：

- 优先 `docker compose`
- 回退 `docker-compose`

因此不需要为了不同服务器环境再维护两套脚本。

## 推荐用法

Windows 推荐直接使用：

```powershell
.\deploy_unified.bat
```

也可以直接执行主脚本：

```powershell
.\deploy_sync_improved.ps1
```

常用参数：

```powershell
.\deploy_sync_improved.ps1 -DryRun
.\deploy_sync_improved.ps1 -SkipDelete
.\deploy_sync_improved.ps1 -SkipBuild
.\deploy_sync_improved.ps1 -SkipValidation
.\deploy_sync_improved.ps1 -UploadStrategy Archive
.\deploy_sync_improved.ps1 -UploadStrategy PerFile
```

## 部署流程

主脚本执行顺序如下：

1. 读取 `deploy_config.json`
2. 探测远端 Compose 命令
3. 解析上传策略
4. 扫描本地文件并按同步规则筛选
5. 扫描远端文件并计算待删除文件
6. 上传文件到远端项目目录
7. 删除远端多余文件
8. 重建并启动容器
9. 校验容器状态与后端健康接口

## 配置说明

最常用配置示例：

```json
{
  "server": {
    "ip": "101.132.154.143",
    "user": "root",
    "remote_path": "/data/apps/novel_writing_agent"
  },
  "upload": {
    "strategy": "Auto"
  },
  "validation": {
    "api_endpoint": "/health"
  }
}
```

如需调整远端地址、同步范围、上传模式或健康检查路径，统一修改 [deploy_config.json](C:/Users/cuigu/novel_writing_agent/deploy_config.json)，不要再新增旁路脚本。

## 常用检查命令

查看线上容器状态：

```powershell
ssh root@101.132.154.143 "cd /data/apps/novel_writing_agent && if docker compose version >/dev/null 2>&1; then docker compose ps; else docker-compose ps; fi"
```

查看后端健康状态：

```powershell
ssh root@101.132.154.143 "curl -sS http://127.0.0.1:8000/health"
```

查看磁盘占用：

```powershell
ssh root@101.132.154.143 "df -h / /data"
```

查看 Docker 根目录：

```powershell
ssh root@101.132.154.143 "docker info --format '{{.DockerRootDir}}'"
```

## 维护原则

- 日常部署统一使用 `deploy_unified.bat` 或 `deploy_sync_improved.ps1`
- 不再恢复或新增旧部署脚本
- 所有部署配置只收敛在 [deploy_config.json](C:/Users/cuigu/novel_writing_agent/deploy_config.json)
- 如需排查线上兼容性，先按脚本逻辑确认 Compose 写法和上传策略
