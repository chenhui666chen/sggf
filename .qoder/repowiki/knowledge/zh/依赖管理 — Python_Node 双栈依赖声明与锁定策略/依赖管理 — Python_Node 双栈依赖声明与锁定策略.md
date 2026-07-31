---
kind: dependency_management
name: 依赖管理 — Python/Node 双栈依赖声明与锁定策略
category: dependency_management
scope:
    - '**'
source_files:
    - backend/requirements.txt
    - backend/requirements-dev.txt
    - backend/requirements-simple.txt
    - backend/requirements-contract.txt
    - frontend/package.json
    - frontend/package-lock.json
    - backend/Dockerfile
    - frontend/Dockerfile
    - docker-compose.yml
    - .github/workflows/contracts.yml
---

本仓库采用 Python（后端）与 Node.js（前端）双栈技术，各自使用标准包管理器进行依赖声明与版本锁定，并通过 Dockerfile 与 CI 工作流保障构建可重复性。

**1. Python 后端依赖管理**
- 使用 `pip` + `requirements.txt` 作为核心依赖清单，位于 `backend/requirements.txt`，按功能分组注释（FastAPI、数据库、认证、LangChain、向量库、任务队列等），所有关键依赖均使用 `==` 精确锁定版本。
- 提供三个分层依赖文件：
  - `backend/requirements.txt`：完整生产依赖（含 Celery、Redis、ChromaDB、DashScope、OpenAI 等）
  - `backend/requirements-dev.txt`：开发环境精简依赖（仅 FastAPI、SQLAlchemy、Pydantic、pytest 等）
  - `backend/requirements-simple.txt`：极简运行依赖（仅 Web 框架、文档处理、HTTP 客户端）
- 通过 `backend/Dockerfile` 设置阿里云 Pypi 镜像源（`PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`），并使用 `pip install --no-cache-dir --retries 5` 安装依赖。
- 存在 `backend/requirements-contract.txt` 文件，被 `.github/workflows/contracts.yml` 引用用于契约测试，确保前后端数据契约一致性。

**2. Node.js 前端依赖管理**
- 使用 `npm` + `package.json` + `package-lock.json` 管理依赖，位于 `frontend/package.json`。
- 依赖分为 `dependencies`（运行时）和 `devDependencies`（构建时）两类，使用 `^` 语义化版本范围。
- `package-lock.json` 锁定所有依赖的精确版本，确保构建可重复性。
- Dockerfile 使用 `npm ci` 而非 `npm install`，强制使用 lockfile 进行确定性安装。

**3. 容器化与依赖隔离**
- 后端 Docker 镜像基于 `python:3.11-slim`，系统依赖通过 apt 安装（gcc、ffmpeg、postgresql-client）。
- 前端采用多阶段构建：`node:18-alpine` 构建阶段 + `nginx:alpine` 生产阶段，构建产物为静态文件。
- `docker-compose.yml` 编排 PostgreSQL 15、Redis 7、后端、前端、Nginx 五个服务，通过环境变量注入配置。

**4. 版本约束策略**
- Python 依赖：关键包使用 `==` 精确锁定（如 fastapi==0.104.1, uvicorn==0.24.0, sqlalchemy>=2.0.23 使用最小版本约束）
- Node 依赖：使用 `^` 语义化版本，允许小版本更新但保持主版本一致
- 未使用 pipenv、poetry、pnpm 等现代工具，仍采用传统的 requirements.txt + package.json 模式

**5. 私有源与网络优化**
- Python 依赖通过阿里云 Pypi 镜像加速下载
- Docker 构建时同时替换 Debian 软件源为阿里云镜像
- 未发现私有 PyPI 或 npm registry 配置