---
kind: configuration_system
name: 配置系统 — 环境变量 + Pydantic Settings + YAML 模型目录的三层配置架构
category: configuration_system
scope:
    - '**'
source_files:
    - backend/app/core/config.py
    - backend/app/core/env_loader.py
    - backend/.env.example
    - frontend/.env.example
    - config/llm_models.yaml
    - config/models.yaml
    - config/intent_domains.yaml
    - core/config.py
---

## 1. 使用的系统与框架
- 后端运行时配置：基于 `pydantic-settings` 的 `BaseSettings`，通过 `backend/app/core/config.py` 中的 `Settings` 类集中声明所有应用级配置项（数据库、Redis、JWT、各厂商 API Key、CORS、日志、Celery、免费档位等）。
- 环境变量加载：由 `backend/app/core/env_loader.py` 提供统一的 `.env` 加载逻辑，按优先级顺序从 `backend/.env` 与仓库根 `.env` 加载，并尊重进程已存在的环境变量（默认不覆盖）。
- 模型与意图配置：集中在 `config/` 目录下以 YAML 形式管理，包括 `llm_models.yaml`（LLM 能力/路由/性能/成本）、`models.yaml`（图像/视频等多模态模型规格与约束）、`intent_domains.yaml`（意图解析域知识，如 Wan/Kling/TTS 等）。这些文件被 adapters/core 层在运行时按需加载。
- 前端配置：通过 Vite 的 `VITE_*` 环境变量（见 `frontend/.env.example`），仅暴露 API 地址、WebSocket 地址与应用名等构建期常量。

## 2. 关键文件与包
- `backend/app/core/config.py`：定义 `Settings(BaseSettings)`，包含全部应用配置字段及自定义 validator（DEBUG、CORS_ORIGINS 等），并在模块导入时调用 `load_project_env(override=False)`。
- `backend/app/core/env_loader.py`：实现 `get_backend_root()` / `get_project_root()` / `get_env_file_candidates()` / `load_project_env()`，统一 .env 发现与加载顺序。
- `backend/.env.example`：完整的环境变量清单模板，涵盖数据库、JWT、各厂商 API Key、ASR、OSS、Embedding、Chroma、Agent、多模型评审、Redis、SMTP、Celery、Free Tier、CORS、日志、腾讯云等。
- `frontend/.env.example`：Vite 构建期环境变量示例（`VITE_API_URL`、`VITE_WS_URL`、`VITE_APP_NAME`、`VITE_APP_VERSION` 等）。
- `config/llm_models.yaml`：LLM 模型元数据（id/name/provider/capabilities/constraints/api_config/performance/routing/default_params/tags 等）。
- `config/models.yaml`：多模态模型（文生图/文生视频/图生视频等）的完整规格、约束、质量指标、速率限制、默认参数、最佳实践与回退策略。
- `config/intent_domains.yaml`：意图解析域知识（风格标签、运镜、景别、构图、光线、情绪、场景规则、提示词范式、解析规则等）。
- `core/config.py`：核心引擎侧的纯 Python dataclass 常量配置（RouterConfig/FallbackConfig/ExecutionConfig/RegistryConfig/AdapterConfig/TaskSpecConfig），用于模型适配器系统的运行时行为调优。

## 3. 架构与设计决策
- 分层加载顺序明确且可预测：
  1) 进程内已有环境变量（最高优先级）
  2) `backend/.env`
  3) 仓库根 `.env`
  4) `Settings` 中定义的默认值
  这一顺序由 `env_loader.load_project_env(override=False)` 保证，避免意外覆盖生产环境注入的密钥。
- 配置即类型：使用 `pydantic_settings.BaseSettings` 将环境变量映射为强类型字段，并通过 `field_validator` 对布尔值、列表型 CORS 等进行规范化校验，减少运行时错误。
- 模型配置与代码解耦：LLM 与多模态模型的元数据、能力、路由策略、性能与成本均放在 YAML 中，由 `adapters/registry.py` 等组件在运行时加载，新增模型无需改动核心代码，只需更新配置文件。
- 意图解析配置化：`intent_domains.yaml` 将不同模型族（Wan/Kling/TTS 等）的风格、运镜、景别、提示词范式与解析规则集中管理，便于扩展新模型族。
- 前端配置最小化：仅暴露构建期需要的 Vite 环境变量，敏感信息不进入前端构建产物。

## 4. 约定与约束
- 环境变量命名规范：所有后端配置项均以大写蛇形命名（如 `DATABASE_URL`、`DASHSCOPE_API_KEY`、`REDIS_URL`、`CELERY_BROKER_URL` 等），并在 `backend/.env.example` 中提供完整模板。
- `.env` 加载不可覆盖原则：默认 `override=False`，若某键已在进程中存在则跳过；仅当值为空字符串时才视为未配置，允许由 `.env` 补齐。
- 模型配置必须包含必要字段：`llm_models.yaml` 与 `models.yaml` 中每个模型条目需包含 id、name、provider、status、capabilities/constraints、api_config、routing 等结构，确保运行时解析一致。
- 安全敏感配置不得硬编码：API Key、Secret、URL 等必须通过环境变量或外部注入，禁止写入源码或配置文件。
- 前端仅暴露非敏感构建期变量：`VITE_*` 前缀变量会在构建时打包进静态资源，不应包含任何密钥。
- 配置变更需同步文档与示例：新增配置项应同时更新 `backend/.env.example` 与相关文档，保持开发/部署一致性。

该配置系统通过“环境变量 + Pydantic Settings + YAML 模型目录”的分层设计，实现了运行时配置的类型安全、模型配置的灵活可扩展以及前后端配置的清晰分离。