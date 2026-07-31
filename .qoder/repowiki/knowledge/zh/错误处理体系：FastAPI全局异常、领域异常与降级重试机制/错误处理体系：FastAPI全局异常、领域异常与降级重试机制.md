---
kind: error_handling
name: 错误处理体系：FastAPI全局异常、领域异常与降级重试机制
category: error_handling
scope:
    - '**'
source_files:
    - backend/app/main.py
    - adapters/_shared.py
    - adapters/adapter_helpers.py
    - core/fallback_manager.py
    - adapters/rate_limiter.py
    - backend/app/api/v1/admin/query.py
---

本仓库的错误处理体系由三层构成：HTTP层（FastAPI）、领域服务层（自定义异常类）以及底层适配器/运行时层的容错与降级。整体采用「局部捕获 + 统一上报」的模式，未建立统一的业务错误码枚举或全局错误响应模型。

1. HTTP 层异常处理
- 全局异常处理器：`backend/app/main.py` 通过 `@app.exception_handler(Exception)` 注册了全局异常捕获，所有未被处理的异常都会记录详细 traceback 并以 JSONResponse 返回 500，其中 `traceback` 字段仅在 `settings.DEBUG` 为真时输出。
- 路由层广泛使用 FastAPI 的 `HTTPException`（status_code + detail）表达业务校验失败、权限不足等可预期错误，例如 `backend/app/api/v1/admin/query.py`、`roles.py`、`users.py` 中大量 `raise HTTPException(status_code=..., detail=...)`。
- 中间件层面仅配置了 CORS 中间件，未见统一的鉴权/日志/限流错误中间件。

2. 领域服务层异常类型
后端在 `backend/app/services/` 下按模块定义了大量细粒度异常类，均继承自 `RuntimeError` 或 `ValueError`，用于区分不同子系统的错误语义，例如：
- `EmbeddingRequestError`（嵌入请求失败）
- `CosyVoiceCloneError` / `MiniMaxVoiceCloneError`（语音克隆错误）
- `LLMJsonParseError`（LLM JSON 解析失败）
- `AudiobookExportError` / `SceneAssemblyError` / `SceneRenderError`（有声书/场景引擎错误）
- `DreamweaverProjectConfigLockedError` / `DreamweaverRunNotFoundError` / `DreamweaverRunRunningError`（织梦映心运行状态错误）
- `EmailServiceNotConfiguredError` / `EmailDeliveryError`（邮件服务错误）
- `ExactModelRequiredError` / `QuotaServiceUnavailableError`（配额与模型守卫错误）
这些异常在各自 service 中被 raise，上层通常以 try/except 捕获并转换为 HTTPException 或直接交由全局处理器处理。

3. 适配器与运行时层的错误传播
- `adapters/_shared.py` 中的 `_poll_*_task` 函数在轮询第三方 API 任务时，遇到失败状态直接 `raise RuntimeError(...)`，超时则 `raise TimeoutError(...)`，由调用方决定重试或降级。
- `adapters/adapter_helpers.py` 提供 `SimpleGenerationResult` 作为统一结果载体，所有生成接口（`generate_image`、`generate_video`、`edit_image`、`analyze_image`、`synthesize_speech` 等）内部用 `try/except Exception` 包裹，失败时返回 `SimpleGenerationResult.from_error(str(e), "execution_error")`，将异常信息封装进 result.error/error_code 字段而非向上抛出，从而让上层能统一判断 success 字段。
- `core/fallback_manager.py` 实现了完整的降级与重试链：`FallbackManager.execute_with_fallback` 会按路由候选顺序尝试多个模型，失败后根据 `TaskDegradationStrategy` 逐步降低任务参数（减少引用、降低分辨率/时长、移除音频等），并通过 `FallbackChain` 记录每次尝试的 error/error_code/success/latency/trace，支持最大尝试次数上限与 LRU 缓存。
- `adapters/rate_limiter.py` 提供进程内 RateLimiter，按分钟/天限制请求频率，并在达到限额时 sleep 等待，避免上游触发 429。

4. 日志与可观测性
- `backend/app/main.py` 配置了 `logging.StreamHandler`（强制 flush）和 `RotatingFileHandler`（单文件 5MB、保留 3 个备份），所有模块统一输出到 `backend/logs/app.log`。
- 全局异常处理器额外写入 `uvicorn.error` logger，包含请求路径、方法、完整 traceback。
- FallbackChain 的每次尝试都附带 trace 字典，便于定位失败阶段（routing/adapter_resolution/generation）。

5. 约定与约束
- HTTP 层：业务错误通过 `HTTPException` 抛出，非预期异常由全局处理器兜底返回 500；DEBUG 模式下才会暴露 traceback。
- 领域层：各 service 模块自行定义 `*Error` 异常类，命名遵循 `{模块}{场景}Error`，继承 `RuntimeError` 或 `ValueError`。
- 适配器层：优先返回结构化结果（`SimpleGenerationResult`）而非抛异常，失败时设置 `success=False` 及 `error/error_code`；仅在无法恢复时向上抛出 `RuntimeError`/`TimeoutError`。
- 重试与降级：通过 `fallback_manager.execute_with_fallback` 统一管理，禁止在调用点自行实现重复的重试逻辑。
- 限流：通过 `get_rate_limiter(key, ...)` 获取共享 limiter，在高频调用前调用 `acquire()` 阻塞等待。
- 日志：所有关键路径需记录上下文信息（请求 ID、model_id、attempt_number），便于故障回溯。