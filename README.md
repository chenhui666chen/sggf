
# 小说写作 Agent

一个面向生产场景的多 Agent 智能创作平台，提供小说创作、知识管理、章节审阅、有声书生成、DreamWeaver 短剧生成等能力。当前仓库的主运行形态是：

- `FastAPI + Socket.IO` 后端
- `React + Vite + TypeScript` 前端
- `Celery + Redis` 异步任务队列
- `PostgreSQL` 主业务数据库
- `ChromaDB / 本地向量能力` 辅助知识检索

当前版本后端已经按 `PostgreSQL-only` 运行设计收敛，所有业务数据存储在 PostgreSQL 数据库中。

## 文档导航

- [快速开始指南](QUICK_START_GUIDE.md)
- [多 Agent 完整指南](MULTI_AGENT_GUIDE.md)
- [部署指南](DEPLOY_GUIDE.md)
- [数据库迁移说明](DATABASE_MIGRATION_GUIDE.md)
- [模型接入参考文档](docs/MODEL_INTEGRATION_REFERENCE.md)
- [模型路由架构优化方案](docs/MODEL_ROUTING_OPTIMIZATION_PLAN_20260417.md)
- [PostgreSQL 部署说明](docs/POSTGRESQL_DEPLOYMENT.md)
- [有声书任务队列说明](docs/AUDIOBOOK_TASK_QUEUE.md)

## 核心能力

### 创作与协作

- 多 Agent 协作式小说创作流程
- 章节规划、内容生成、质量评审、迭代优化
- 角色、设定、记忆、知识库统一管理
- DreamWeaver 短剧资产生成与流程控制

### 平台能力

- 前后端分离 Web 界面
- WebSocket / Socket.IO 实时状态更新
- Celery 异步任务与队列隔离
- 管理后台、日志、统计与权限体系

### 有声书能力

- 章节脚本生成与管理
- TTS 试听、批量音频生成
- 音色管理、项目级音频配置
- 后台任务进度跟踪与历史记录展示

## 当前技术栈

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Redis
- Celery
- Socket.IO
- React
- Vite
- TypeScript
- Redux Toolkit
- Material UI

## 项目结构

```text
novel_writing_agent/
├── backend/                 # FastAPI、SQLAlchemy、Celery、业务服务
├── frontend/                # React + Vite 前端
├── docs/                    # 部署、队列、生产配置等说明
├── agents/                  # 多 Agent 逻辑与创作相关模块
├── adapters/                # 外部模型 / 平台适配层
├── pipeline/                # DreamWeaver / 处理流水线
├── scripts/                 # 运维和辅助脚本
├── data/                    # 业务数据、提示词、缓存
├── docker-compose.yml       # PostgreSQL / Redis / 全容器化部署
├── dev.bat                  # Windows 本地开发启动脚本
└── README.md                # 当前文档
```

## 本地开发推荐流程

### 前置要求

- Python
- Node.js
- Docker Desktop
- 已创建并可用的 `.venv`

### 1. 启动基础依赖

本项目本地开发推荐先用 Docker 启动 `PostgreSQL` 和 `Redis`：

```bash
docker compose up -d postgres redis
```

启动后可用以下命令确认状态：

```bash
docker ps --filter "name=novel_postgres" --filter "name=novel_redis"
```

期望状态：

- `novel_postgres` 为 `healthy`
- `novel_redis` 为 `healthy`

### 2. 启动业务进程

Windows 本地开发推荐直接执行：

```bash
dev.bat
```

`dev.bat` 当前会启动 4 个业务窗口：

- FastAPI 后端
- Celery Worker: `audiobook`
- Celery Worker: `dreamweaver`
- Vite 前端开发服务器

注意：

- `dev.bat` 不会自动启动 PostgreSQL / Redis
- 启动 `dev.bat` 前，请先确保上一步的 `postgres` 和 `redis` 已可用

### 3. 访问地址

推荐使用以下地址：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://127.0.0.1:8000/health`
- API 文档：`http://127.0.0.1:8000/docs`
- Socket.IO：`http://127.0.0.1:8000/socket.io/`

Windows 本地开发注意：

- 部分环境下，`http://localhost:8000` 会优先走 IPv6 / WSL 转发，导致浏览器出现 `ERR_EMPTY_RESPONSE`
- 直接访问后端时，请优先使用 `127.0.0.1:8000`
- 前端已通过 Vite 代理转发 `/api`，正常从 `http://localhost:5173` 进入页面即可

## 手动启动

### 1. 安装依赖

```bash
# 根目录 Python 依赖
pip install -r requirements.txt

# 后端依赖
cd backend
pip install -r requirements.txt
cd ..

# 前端依赖
cd frontend
npm install
cd ..
```

### 2. 配置环境变量

推荐至少检查以下文件：

- 根目录 [.env](.env)
- 后端 [backend/.env](backend/.env)
- 前端 [frontend/.env](frontend/.env)

本地开发关键配置建议如下：

```env
# root/.env 或 backend/.env
DATABASE_URL=postgresql://novel_user:your_password@127.0.0.1:5432/novel_db
REDIS_URL=redis://:your_redis_password@localhost:6380/0
CELERY_BROKER_URL=redis://:your_redis_password@localhost:6380/0
CELERY_RESULT_BACKEND=redis://:your_redis_password@localhost:6380/0
```

```env
# frontend/.env
VITE_API_URL=/api
VITE_WS_URL=http://127.0.0.1:8000
```

说明：

- `VITE_API_URL=/api` 表示前端开发环境通过 Vite 代理访问后端
- `VITE_WS_URL` 建议显式指向 `127.0.0.1:8000`
- 如果你改动了 `frontend/.env`，需要重启 `npm run dev` 才会生效

### 3. 启动 PostgreSQL / Redis

```bash
docker compose up -d postgres redis
```

### 4. 启动后端

```bash
cd backend
python -m uvicorn app.main:application --host 0.0.0.0 --port 8000 --reload
```

### 5. 启动 Celery Worker

有声书队列：

```bash
cd backend
celery -A app.celery_app.celery_app worker -P solo -Q audiobook -l info
```

DreamWeaver 队列：

```bash
cd backend
celery -A app.celery_app.celery_app worker -P solo -Q dreamweaver -l info
```

### 6. 启动前端

```bash
cd frontend
npm run dev
```

## Docker 运行方式

如果你希望直接使用全容器化方式运行整套服务，可以执行：

```bash
docker compose up -d --build
```

命令示例优先使用 `docker compose`。如果你的环境仍然只有旧版独立命令，也可以替换为 `docker-compose`。

`docker-compose.yml` 当前包含：

- `postgres`
- `redis`
- `backend`
- `frontend`
- `nginx`

常见访问入口：

- 前端容器：`http://localhost:3000`
- Nginx：`http://localhost`
- 后端 API：`http://127.0.0.1:8000`

### 生产部署补充说明

- 生产环境统一使用 [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md) 中定义的部署链路。
- 当前正式入口为 `deploy_unified.bat` 和 `deploy_sync_improved.ps1`，部署配置统一收敛在 `deploy_config.json`。
- 当前主脚本的实际行为：
  - 基于 `deploy_config.json` 按规则同步文件，并支持远端多余文件删除
  - 在远端自动探测 `docker compose` 或 `docker-compose`，兼容两种 Compose 环境
  - 重建并拉起 `backend`、`frontend` 和 `nginx`
  - 通过后端健康检查验证部署结果
- 当前生产 `nginx` 证书路径建议放在根目录 `.env` 中，不要把真实证书提交到仓库：

```env
NGINX_SSL_CERT_PATH=/etc/letsencrypt/live/sggf.net/fullchain.pem
NGINX_SSL_KEY_PATH=/etc/letsencrypt/live/sggf.net/privkey.pem
```

- 如果未设置上述变量，Compose 会回退读取仓库内的 `ssl/cert.pem` 与 `ssl/key.pem`，这只建议用于本地测试或占位场景。

## 关键配置说明

### 数据库

- 当前后端只支持 PostgreSQL
- [backend/app/db/base.py](backend/app/db/base.py) 会在非 PostgreSQL 配置下直接抛错
- SQLite 文件仅保留为历史数据、迁移参考或离线分析用途

### 前端网络

- [frontend/src/services/api.ts](frontend/src/services/api.ts) 默认走 `VITE_API_URL`
- [frontend/src/services/websocket.ts](frontend/src/services/websocket.ts) 默认走 `VITE_WS_URL`
- [frontend/vite.config.ts](frontend/vite.config.ts) 已配置 `/api` 和 `/ws` 代理到 `127.0.0.1:8000`

### Redis / Celery

- 当前本地 Docker 配置下，Redis 对宿主机暴露端口为 `6380`
- 如果沿用仓库默认环境变量，Celery 与后端都应连接 `redis://:...@localhost:6380/0`
- 本地业务启动时，通常需要两个 worker：
  - `audiobook`
  - `dreamweaver`

## TTS 相关说明

当前仓库默认集成阿里云 `Qwen3-TTS` 相关能力：

- 默认模型：`qwen3-tts-flash`
- 凭证复用 `DASHSCOPE_API_KEY`
- 可按项目切换到 `cosyvoice-v3-plus`
- 历史别名 `qwen3_tts` 会统一归一化到 `qwen3-tts-flash`
- 统一 TTS 返回同时兼容 `audio_bytes`、`audio_data(base64)`、`tts_timestamps`、`phoneme_timestamps`
- 前端音色配置主要位于 `frontend/src/pages/AudiobookPage.tsx`
- 后端映射与预设位于 `backend/app/services/audiobook/voice_manager.py`

## 统一模型调度中心

当前仓库已经完成统一模型中心的两层收口：

- 文本模型统一入口：`core/model_hub.py`
- 文本统一客户端：`core/unified_llm_client.py`
- 文本 LangChain 兼容桥：`core/langchain_bridge.py`
- 多模态统一运行时：`core/unified_media_runtime.py`
- 多模态兼容 helper：`adapters/adapter_helpers.py`
- 文本模型注册与能力配置：`core/unified_registry.py`、`config/llm_models.yaml`
- 图像 / 视频 / TTS / 多模态档案配置：`config/models.yaml`
- 模型资料总览：`docs/MODEL_KNOWLEDGE_BASE_20260315.md`

当前实现特性：

- 新模型先在 `config/llm_models.yaml` 注册，再由 `ModelHub` 统一调度
- 业务代码可按 `task_type` 自动选模，也可显式传 `model`
- LangChain 风格的 `invoke / ainvoke / stream` 已通过桥接层接入统一中心
- 流式生成、错误处理、模型别名映射、任务类型映射全部走同一套实现
- 图像生成、视频生成、图像编辑、视觉分析、TTS 已新增统一多模态入口
- `audiobook` 相关 TTS 试听与引擎初始化已改走统一多模态运行时
- `adapters/adapter_helpers.py` 现在会通过统一多模态运行时执行，不再把显式 `model_id` 当成无效附加参数
- `SimpleAdapterFactory` 现已支持 runtime wrapper 懒代理，历史代码对 `chat`、`analyze_image`、`analyze_video`、`match_scene` 等旧方法的调用也会自动转发到新机制
- `qwen3-vl-plus`、`qwen-image-edit-plus`、`qwen-image-edit-max`、`wan2.6-t2i`、`wan2.6-t2v`、`wan2.6-i2v`、`wan2.6-r2v` 已补齐 registry-backed adapter，不再依赖统一运行时内部的 legacy bridge 分支
- `adapters/model_adapters.py` 现在会优先为 `wan_t2i/wan26_t2i`、`wan_t2v/wan26_t2v`、`qwen3_vl_plus`、`qwen3_tts`、`qwen_image_edit_plus`、`qwen_image_edit_max`、`wan_image_edit`、`wan_i2v/wan26_i2v`、`wan_r2v/wan26_r2v`、`qwen_multiperson_fusion` 创建 runtime wrapper，旧 Agent 继续使用旧签名时也会转发到新 registry / TaskSpec 路径
- 历史媒体 adapter 被直接实例化时，`generate`、`chat`、`analyze_image`、`analyze_video`、`match_scene` 等公开入口现在也会优先薄代理到 runtime wrapper，不再回落到旧 HTTP / DashScope 主链路
- `legacy_bridge` 对已 wrapper 化的媒体模型旧 fallback 已基本清空，当前仅保留 `jianying` 的旧式兜底；`Qwen3TTSAdapter` 已改为统一委托到新 TTS helper，不再保留独立的旧 DashScope TTS 调用链
- `agents/audio_sync_manager.py`、`agents/simple_audio_sync_manager.py`、`agents/optimized_audio_sync_manager.py`、`agents/performance_audio_sync_manager.py` 已切换到统一 `synthesize_speech_sync(...)` 入口
- 历史兼容文件 `backend/app/services/llm_client.py`、`backend/app/services/model_optimizer.py`、`backend/app/services/agents/llm_singleton.py`、`core/compatibility.py` 已移除

推荐接入方式：

- 异步文本调用：`from core.unified_llm_client import get_llm_client`
- 多模态调用：`from core.unified_media_runtime import media_runtime, create_tts_engine, synthesize_speech`
- LangChain 兼容调用：`from core.langchain_bridge import create_task_llm, create_model_llm`
- 任务枚举与归一化：`from core.model_resolution import TaskType, normalize_task_type, normalize_model_id`
- 模型接入自检：`python scripts/check_model_integration.py --chain llm|media|all --model-id your-model-id`

历史别名说明：

- `deepseek-r1` 会归一化到 `deepseek-reasoner`
- `qwen-max` 会归一化到 `qwen3-max`
- `qwen-plus` 会归一化到 `qwen-long`

## 测试与报告

本次模型调度改造的专项测试报告见：

- [docs/MODEL_DISPATCH_REFACTOR_TEST_REPORT_FINAL_20260315.md](docs/MODEL_DISPATCH_REFACTOR_TEST_REPORT_FINAL_20260315.md)
- [docs/UNIFIED_MEDIA_RUNTIME_TEST_REPORT_20260315.md](docs/UNIFIED_MEDIA_RUNTIME_TEST_REPORT_20260315.md)
- [docs/MODEL_KNOWLEDGE_BASE_20260315.md](docs/MODEL_KNOWLEDGE_BASE_20260315.md)

已执行的验证包括：

- `tests/test_unified_model_system.py`
- `tests/test_model_dispatch_refactor.py`
- `tests/test_unified_media_runtime.py`
- `tests/test_adapter_helpers_tts_compat.py`
- `tests/test_adapter_helpers_media_runtime.py`
- `tests/test_painter_model_id_runtime.py`
- `tests/test_legacy_runtime_wrappers.py`
- `tests/test_model_adapters_legacy_delegate.py`
- `tests/test_vlm_model_id_compat.py`
- `tests/test_model_metadata_catalog.py`
- `backend/tests/test_auth_routes.py`
- 关键模块导入冒烟测试
- 运行时代码旧调用路径扫描

当前最终回归结果为：`91 passed, 2 warnings`。

## 故障排查

### 1. 浏览器报 `ERR_EMPTY_RESPONSE`

常见现象：

- 登录接口请求地址是 `http://localhost:8000/api/...`
- 浏览器提示 `net::ERR_EMPTY_RESPONSE`

排查与处理：

- 不要直接把前端 API 指到 `http://localhost:8000`
- 检查 [frontend/.env](frontend/.env) 是否为：
  - `VITE_API_URL=/api`
  - `VITE_WS_URL=http://127.0.0.1:8000`
- 修改后重启前端 `npm run dev`
- 直接访问后端时使用 `http://127.0.0.1:8000`

### 2. 后端报 PostgreSQL 连接失败

常见报错：

- `psycopg2.OperationalError`
- `connection refused`

排查与处理：

- 确认 `docker compose up -d postgres`
- 确认 `DATABASE_URL` 指向 `127.0.0.1:5432`
- 确认 `novel_postgres` 为 `healthy`

### 3. Celery / Redis 频繁断连

常见报错：

- `consumer: Connection to broker lost`
- `redis.exceptions.ConnectionError`

排查与处理：

- 确认 `docker compose up -d redis`
- 确认本地 Redis 端口是 `6380`，不是 `6379`
- 检查 `REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` 是否一致

### 4. 登录返回 401

说明：

- 这通常代表请求链路已经正常，问题变成账号或密码错误
- 优先检查数据库中的用户数据，而不是继续排查前端代理

## 相关文档

- [快速开始指南](QUICK_START_GUIDE.md)
- [部署指南](DEPLOY_GUIDE.md)
- [数据库迁移说明](DATABASE_MIGRATION_GUIDE.md)
- [PostgreSQL 部署说明](docs/POSTGRESQL_DEPLOYMENT.md)
- [有声书任务队列说明](docs/AUDIOBOOK_TASK_QUEUE.md)

## 许可证

MIT License

---

## 2026-03-16 更新

- `adapters/adapter_helpers.py` 新增统一的历史 TTS 参数归一化 helper，`SimpleAdapter`、`Qwen3TTSRuntimeWrapper`、`Qwen3TTSAdapter` 现在会共用同一套 `voice_style/speed/pitch/volume` 映射规则，避免旧入口之间参数处理不一致。
- 新增 `tests/test_model_adapters_legacy_delegate.py`，用于验证直接实例化历史媒体 adapter 时也会转发到 runtime wrapper。
- 新增 `tests/test_adapter_helpers_media_runtime.py` 与 `tests/test_vlm_model_id_compat.py`，分别覆盖统一 helper 的媒体运行时入口，以及 VLM 工具链直接传 `model_id` 字符串的兼容路径。
- 新增 `tests/test_painter_model_id_runtime.py`，用于验证 `agents/painter.py` 的候选生成底层 helper 已支持直接传入 `model_id` 字符串，不再强依赖预先实例化的 runtime wrapper 对象。
- `adapters/model_adapters.py` 现在会把 `generate`、`chat`、`analyze_image`、`analyze_video`、`match_scene` 等历史公开入口统一收口到 runtime-wrapper 路径。
- `adapters/model_adapters.py` 中被 runtime wrapper 接管的旧媒体类已进一步物理删除历史 HTTP / DashScope 实现残留，不再保留同类“双份实现 + 后置覆盖”的冗余代码。
- `agents/dreamweaver.py` 的 Wan I2V / T2V 生成链路与 `backend/app/api/v1/dreamweaver.py` 的角色素材 T2I / image-edit 入口，现已进一步切换为直接调用统一 `adapter_helpers.generate_video / generate_image / edit_image`，并通过 `model_supports_capability(...)` 读取模型能力元数据，不再依赖“先实例化兼容 adapter 再取属性”的旧路径。
- `pipeline/autoqc.py` 的 VLM `chat` 质检调用也已切换为直接走统一 `adapter_helpers.chat_messages(...)`，不再需要 `SimpleAdapterFactory` 先创建兼容 adapter。
- `adapters/adapter_helpers.py` 新增统一 `match_scene(...)` helper，`qwen_multiperson_fusion` 也已接入统一模型别名归一化；`agents/painter.py` 的 `run_keyframes/run_midframes` 已把 T2I / image-edit / VLM / multiperson-fusion 主链路全部下沉到字符串 `model_id` 驱动，并行候选生成也不再依赖 `create_runtime_client(...)`；`agents/asset_library.py` 的业务层则继续通过 `create_runtime_client(...)` 直接创建 runtime wrapper 客户端。`SimpleAdapterFactory` 仍仅作为兼容壳保留在 `adapters/adapter_helpers.py` 与对应兼容测试中。
- `legacy_runtime_wrappers.py` 也已继续瘦身：`qwen3_vl_plus`、`wan_t2i`、`wan_t2v`、`wan_i2v`、`wan_r2v`、`qwen_image_edit_*`、`wan_image_edit`、`qwen_multiperson_fusion` 等 wrapper 的内部执行已尽量复用 `adapter_helpers`，旧 wrapper 当前主要承担旧签名兼容职责，而不再各自维护一套独立路由逻辑；同时统一 helper 也补齐了 `generate_video` 的 `negative_prompt` 与 `edit_image` 的 `seed` 标准字段传递。
- `Qwen3TTSAdapter` 新增 speaker 归一化 fallback loader，确保在隔离环境中无法完整导入有声书包链路时，旧 CosyVoice speaker ID 仍能归一化到 Qwen3-TTS speaker。
- 定向回归命令：`.venv\Scripts\python -m pytest tests/test_painter_model_id_runtime.py tests/test_adapter_helpers_tts_compat.py tests/test_legacy_runtime_wrappers.py tests/test_adapter_helpers_media_runtime.py tests/test_vlm_model_id_compat.py tests/test_model_adapters_legacy_delegate.py -q`
- 定向回归结果：`38 passed`
- 最新回归命令：`.venv\Scripts\python -m pytest tests backend/tests/test_auth_routes.py -q`
- 最新回归结果：`91 passed, 2 warnings`

版本：`1.0.0`  
最后更新：`2026-03-16`
