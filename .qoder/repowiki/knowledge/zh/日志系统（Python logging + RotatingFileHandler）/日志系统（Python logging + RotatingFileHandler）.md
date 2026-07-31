---
kind: logging_system
name: 日志系统（Python logging + RotatingFileHandler）
category: logging_system
scope:
    - '**'
source_files:
    - backend/app/main.py
    - core/logging_config.py
    - backend/app/core/config.py
    - backend/alembic/env.py
---

本仓库采用 Python 标准库 `logging` 作为统一的日志框架，未引入 loguru、structlog 等第三方日志库。日志体系分为两个层次：后端 FastAPI 应用层与核心模型适配器层。

**1. 后端 FastAPI 应用日志**
- 入口位于 `backend/app/main.py`，在应用启动时通过 `logging.basicConfig(..., force=True)` 全局配置根 logger。
- 输出双端点：
  - 控制台：自定义 `FlushHandler(logging.StreamHandler)`，每次写入后强制 `flush()`，避免容器/管道缓冲导致日志丢失。
  - 文件：`RotatingFileHandler`，单文件最大 5MB，保留 3 个备份（`app.log.1` ~ `app.log.3`），编码 UTF-8。
- 日志格式统一为 `%(asctime)s - %(name)s - %(levelname)s - %(message)s`，时间格式 `%Y-%m-%d %H:%M:%S`。
- 默认级别 INFO，并通过 `logging.getLogger("app")`、`"app.api"`、`"app.services"`、`"app.websocket"` 等命名空间分别设置级别。
- 全局异常处理器使用 `uvicorn.error` logger 记录详细堆栈。
- 日志路径由 `backend/app/core/config.py` 中的 `Settings.LOG_FILE = "./logs/app.log"` 提供，实际目录在 `backend/logs/`。

**2. 核心模型适配器日志**
- 独立配置文件 `core/logging_config.py` 提供 `get_logger(name="model_adapter")`、`configure_logging(level, format_str, date_format, log_file)`、`set_log_level(level)` 三个 API。
- 默认仅向 stdout 输出，支持可选的 file handler；`propagate=False` 避免重复输出。
- 该模块被 adapters 层（如 `adapters/base.py`、`adapters/registry.py`、`adapters/prompt_optimizer.py`）直接导入使用。

**3. Alembic 迁移日志**
- `backend/alembic/env.py` 通过 `logging.config.fileConfig(config.config_file_name)` 加载 alembic.ini 中的日志配置，与主应用解耦。

**4. 各模块日志使用约定**
- 绝大多数模块遵循 `import logging; logger = logging.getLogger(__name__)` 的模式，按模块名划分 logger 树。
- 部分管理器类（如 `agents/optimized_audio_sync_manager.py`）将 logger 实例化到 `self.logger = logging.getLogger("AudioSyncManager")`。

**5. 日志级别策略**
- 运行时通过环境变量 `LOG_LEVEL`（默认 INFO）控制，但 `main.py` 中硬编码了 `logging.INFO`，`config.py` 中的 `LOG_LEVEL` 字段尚未被 `main.py` 消费，属于预留配置项。
- 无结构化日志字段（如 request_id、trace_id），错误信息以字符串拼接形式输出。

**6. 约束与限制**
- 未实现异步安全写入（除 FlushHandler 外无额外保护）。
- 无集中式日志收集（如 ELK、Loki），依赖本地文件轮转。
- 测试脚本（`scripts/verify_seed_tts_*.py`、`backend/tests/*.py`）各自调用 `logging.basicConfig` 独立初始化，互不影响。