# 拾光工坊 / Novel Writing Agent

这是一个围绕小说创作延展的全栈创作平台，而不是单一的“文本生成脚本”。当前代码主线由以下部分构成：

- 后端：FastAPI + Socket.IO + Celery + PostgreSQL + Redis
- 前端：React + Vite + TypeScript + MUI
- 资产链路：Asset Studio、DreamWeaver、Audiobook、User Assets、User Center
- 平台能力：模型目录、AI Trace、管理后台、工作流编排、知识库与记忆系统

当前运行时入口以代码为准：

- 后端启动对象：`backend/app/main.py` 中的 `app.main:application`
- 前端路由入口：`frontend/src/App.tsx`
- 本地优先资产入口：`frontend/src/utils/localAssetVault.ts`

## 当前功能版图

前端已接入的主要页面路由包括：

- `/home`：创作模块首页
- `/asset-studio`：图片 / 视频 / 音频生成工作台
- `/model-catalog`：模型目录中心
- `/user-center`：用户中心、资产归档、积分与任务账本概览
- `/ai-trace`：AI Trace 页面
- `/audiobook-dashboard`、`/audiobook/:projectId`：有声书项目与章节生产
- `/drama`、`/drama/:projectId`、`/drama/:projectId/library`：DreamWeaver 短剧生成与素材库
- `/admin/*`：管理后台

后端已聚合的主要 API 前缀包括：

- `/api/v1/asset-studio`
- `/api/v1/dreamweaver`
- `/api/v1/audiobook`
- `/api/v1/user-assets`
- `/api/v1/user-center`
- `/api/v1/admin`

## 推荐启动方式

### 1. 安装依赖

后端依赖文件在 `backend/requirements.txt`，仓库根目录**没有** `requirements.txt`。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

### 2. 准备环境变量

可从根目录 `.env.example` 复制出一份主配置：

```powershell
Copy-Item ".env.example" ".env"
```

代码中的环境变量加载优先级是：

1. 进程环境变量
2. `backend/.env`
3. 根目录 `.env`

这是由 `backend/app/core/env_loader.py` 的 `load_project_env(override=False)` 决定的。实际维护时建议只保留一份主 `.env`，除非你确实需要用 `backend/.env` 做后端局部覆盖，否则很容易出现配置漂移。

### 3. 启动基础依赖

当前后端运行时强制要求 PostgreSQL，`backend/app/db/base.py` 会在 `DATABASE_URL` 不是 `postgresql://...` 时直接抛错。也就是说，历史文档里提到的 SQLite 本地模式已经不再适用于当前代码。

推荐先启动数据库与 Redis：

```powershell
docker compose up -d postgres redis
```

### 4. 一键启动开发环境

仓库根目录的 `dev.bat` 会启动 4 个窗口：

- FastAPI 后端
- Celery Worker（`audiobook` 队列）
- Celery Worker（`dreamweaver` 队列）
- Vite 前端

```powershell
.\dev.bat
```

启动后默认地址：

- 前端：`http://localhost:5173`
- 后端：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`
- Socket.IO：`ws://127.0.0.1:8000/socket.io/`

## 手动启动

如果不使用 `dev.bat`，可以按下面的方式分别启动：

### 后端

```powershell
.\.venv\Scripts\activate
cd backend
python -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload
```

### Celery Worker

```powershell
.\.venv\Scripts\activate
cd backend
celery -A app.celery_app.celery_app worker -P solo -Q audiobook -l info
```

```powershell
.\.venv\Scripts\activate
cd backend
celery -A app.celery_app.celery_app worker -P solo -Q dreamweaver -l info
```

### 前端

```powershell
cd frontend
npm run dev
```

## 前端 API / WebSocket 说明

当前前端代码和代理配置需要分开理解：

- `frontend/src/services/api.ts` 中，`VITE_API_URL` 未设置时默认直连 `http://127.0.0.1:8000`
- `frontend/src/services/websocket.ts` 中，`VITE_WS_URL` 未设置时默认使用当前站点的 `/socket.io`
- `frontend/vite.config.ts` 仍然配置了开发代理：
  - `/api/workflow` -> `http://127.0.0.1:8000/api/v1/workflow`
  - `/api` -> `http://127.0.0.1:8000`
  - `/socket.io` -> `http://127.0.0.1:8000`（WebSocket）

因此：

- 如果你沿用当前默认前端实现，HTTP 请求通常会直接打到 `8000`
- 如果你把 `VITE_API_URL=/api`、`VITE_WS_URL=/socket.io` 写入环境变量，就会走 Vite / Nginx 的相对路径代理模式

## 本地优先资产链路

当前代码不是“服务端永久保存所有媒体结果”的模式。与用户资产相关的主线已经是：

- 生成结果先由后端以受控方式暴露
- 前端使用 `localAssetVault` 管理本地副本
- 当前写入优先级：`external_directory -> opfs -> legacy IndexedDB blob`
- 服务端 `user_asset_records` 主要保存轻量元数据，而不是把所有大文件长期持久化在平台侧

对应代码锚点：

- `frontend/src/utils/localAssetVault.ts`
- `backend/app/api/v1/user_assets.py`
- `backend/app/schemas/user_asset.py`
- `frontend/src/contracts/userAssetLocalStorageContract.ts`

## 自检与测试

仓库当前只内置了一个契约校验工作流：`.github/workflows/contracts.yml`。它并不等于“全量 CI 已完成”，但与用户资产本地存储契约相关的生成、后端校验、前端契约测试链路是连通的。

推荐的本地自检命令：

```powershell
python scripts/generate_user_asset_local_storage_contract.py --check
python -m pytest backend/tests/test_user_asset_metadata_contract.py -q
python -m pytest tests/test_adapter_helpers_media_runtime.py tests/test_adapter_helpers_tts_compat.py -q
cd frontend
npm run test
npm run type-check
npm run lint
```

前端当前可用脚本以 `frontend/package.json` 为准：

- `npm run dev`
- `npm run build`
- `npm run test`
- `npm run lint`
- `npm run type-check`

## 部署说明

如果你需要走现有部署脚本：

- `deploy_unified.bat` 只是统一入口
- 实际会委托 `deploy_sync_improved.ps1`
- 远端路径配置来自 `deploy_config.json`

这部分属于脚本化部署能力，不等同于完整 CI/CD 流水线。

## 当前已知注意事项

- `docker-compose.yml`、`backend/app/core/config.py` 中仍存在开发默认凭证与默认密钥，生产环境必须通过环境变量覆盖，不能直接照搬。
- 后端当前是 PostgreSQL-only；不要再按旧文档尝试 SQLite。
- 历史文档中若出现根目录 `requirements.txt`、`/ws` WebSocket 路径或过时的 AI 痕迹处理模块说明，应以当前代码实现为准。

## 文档导航

- [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)：按当前代码整理的快速开始
- [docs/LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md](docs/LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md)：本地优先资产架构方案
- [docs/POSTGRESQL_DEPLOYMENT.md](docs/POSTGRESQL_DEPLOYMENT.md)：PostgreSQL 相关部署说明
- [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)：部署流程说明
