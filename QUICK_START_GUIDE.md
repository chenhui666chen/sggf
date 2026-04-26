# 快速开始

这份文档只描述**当前代码主线**的启动方式，不再沿用旧版“AI 痕迹降低方案”说明。当前仓库实际是一套小说创作平台，主线包括：

- 创作首页与编辑工作流
- Asset Studio 图片 / 视频 / 音频生成
- DreamWeaver 短剧生成与素材库
- Audiobook 有声书生成
- User Assets 本地优先资产归档
- User Center、Model Catalog、AI Trace、Admin

## 5 分钟跑起来

### 1. 安装依赖

后端依赖在 `backend/requirements.txt`，不是仓库根目录。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend/requirements.txt
cd frontend
npm install
cd ..
```

### 2. 准备环境变量

```powershell
Copy-Item ".env.example" ".env"
```

环境变量实际加载顺序由 `backend/app/core/env_loader.py` 决定：

1. 进程环境变量
2. `backend/.env`
3. 根目录 `.env`

建议本地开发只维护一份根目录 `.env`。如果同时维护 `backend/.env`，后端会优先吃到它的值。

### 3. 启动 PostgreSQL 与 Redis

后端当前是 PostgreSQL-only，`backend/app/db/base.py` 会拒绝非 PostgreSQL 的 `DATABASE_URL`。

```powershell
docker compose up -d postgres redis
```

### 4. 一键启动开发环境

```powershell
.\dev.bat
```

`dev.bat` 会打开 4 个窗口：

- FastAPI 后端
- Celery Worker（`audiobook` 队列）
- Celery Worker（`dreamweaver` 队列）
- Vite 前端

默认访问地址：

- 前端：`http://localhost:5173`
- 后端：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 手动启动方式

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

## 主要页面与模块对照

### 前端页面

- `/home`：创作模块首页
- `/asset-studio`：统一资产生成工作台
- `/model-catalog`：模型目录中心
- `/user-center`：用户中心、资产与积分概览
- `/ai-trace`：AI Trace 页面
- `/audiobook-dashboard`、`/audiobook/:projectId`：有声书项目
- `/drama`、`/drama/:projectId`、`/drama/:projectId/library`：DreamWeaver 短剧与素材库
- `/admin/*`：管理后台

### 后端 API 前缀

- `/api/v1/asset-studio`
- `/api/v1/dreamweaver`
- `/api/v1/audiobook`
- `/api/v1/user-assets`
- `/api/v1/user-center`
- `/api/v1/admin`

## 前端请求与代理

当前代码同时存在“直连后端”和“相对路径代理”两种用法：

- `frontend/src/services/api.ts` 默认把 HTTP 请求发到 `http://127.0.0.1:8000`
- `frontend/src/services/websocket.ts` 默认走当前站点的 `/socket.io`
- `frontend/vite.config.ts` 已配置代理：
  - `/api/workflow` -> `/api/v1/workflow`
  - `/api` -> 后端
  - `/socket.io` -> 后端 Socket.IO

如果你把 `VITE_API_URL=/api`、`VITE_WS_URL=/socket.io` 写入环境变量，前端会更接近生产反向代理模式。

## 本地优先资产链路

当前用户资产的主线已经不是“服务端永久存大文件”，而是：

1. Asset Studio、DreamWeaver、Audiobook 先产生受控访问结果。
2. 前端通过 `localAssetVault` 保存本地副本。
3. 当前本地写入优先级为：
   - `external_directory`
   - `opfs`
   - `legacy IndexedDB blob`
4. 服务端 `user_asset_records` 保存轻量元数据与来源信息。

关键代码位置：

- `frontend/src/utils/localAssetVault.ts`
- `backend/app/api/v1/user_assets.py`
- `backend/app/schemas/user_asset.py`
- `frontend/src/contracts/userAssetLocalStorageContract.ts`

## 最小验证清单

启动后，至少做下面几项检查：

### 页面检查

- 打开 `http://localhost:5173/home`
- 进入 `/asset-studio`，确认页面能加载
- 进入 `/drama`、`/audiobook-dashboard`、`/user-center`
- 如果有管理员账号，再检查 `/admin/dashboard`

### 服务检查

- 访问 `http://127.0.0.1:8000/health`
- 打开 `http://127.0.0.1:8000/docs`
- 观察 `dev.bat` 打开的 2 个 Celery Worker 是否都已连接

### 契约与前端检查

```powershell
python scripts/generate_user_asset_local_storage_contract.py --check
python -m pytest backend/tests/test_user_asset_metadata_contract.py -q
cd frontend
npm run test
npm run type-check
```

## 常见问题

### 1. 为什么不能用 SQLite？

因为 `backend/app/db/base.py` 已经在运行时强制要求 `postgresql://...`。即使历史注释里提过 SQLite，本轮代码已经不支持。

### 2. WebSocket 应该连哪个路径？

当前 Socket.IO 路径是 `/socket.io`，不是旧文档里常见的 `/ws`。

### 3. 为什么前端有时走 8000，有时走 5173 代理？

这取决于你有没有显式设置 `VITE_API_URL` 和 `VITE_WS_URL`：

- 不设置时：API 默认直连 `127.0.0.1:8000`
- 设为相对路径时：通过 Vite / Nginx 代理转发

### 4. 生产环境能直接用当前默认配置吗？

不能。`docker-compose.yml` 和 `backend/app/core/config.py` 里仍有开发默认密码和密钥占位值，生产环境必须通过环境变量覆盖。

## 相关文档

- `README.md`
- `docs/LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md`
- `docs/POSTGRESQL_DEPLOYMENT.md`
- `DEPLOY_GUIDE.md`
