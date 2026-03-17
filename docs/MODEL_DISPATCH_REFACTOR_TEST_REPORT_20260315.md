# 模型调度改造测试报告

日期：`2026-03-15`

## 1. 改造范围

本次改造目标是将项目中的文本大模型调用链路统一收口到新的模型调度中心，并清理废弃兼容实现。核心动作包括：

- 新增统一任务/模型归一化层：`core/model_resolution.py`
- 新增统一运行时初始化与同步桥：`core/model_runtime.py`
- 新增统一异步客户端：`core/unified_llm_client.py`
- 新增 LangChain 兼容桥：`core/langchain_bridge.py`
- 将业务模块改为通过 `ModelHub`、`UnifiedLLMClient` 或 LangChain 兼容桥调用模型
- 重写流式服务：`backend/app/services/streaming_service.py`
- 重写 DreamWeaver 使用的 `agents/llm_client.py`，内部统一走 `ModelHub`
- 删除废弃兼容链路：
  - `backend/app/services/llm_client.py`
  - `backend/app/services/model_optimizer.py`
  - `backend/app/services/agents/llm_singleton.py`
  - `core/compatibility.py`

## 2. 统一后的调用入口

当前推荐入口如下：

- 异步文本调用：`core.unified_llm_client.get_llm_client()`
- LangChain 兼容调用：`core.langchain_bridge.create_task_llm()` / `create_model_llm()`
- 统一调度底座：`core.model_hub.model_hub`
- 任务与模型归一化：`core.model_resolution.normalize_task_type()` / `normalize_model_id()`

## 3. 清理结果

### 已清理的旧链路

- 旧 `llm_client` 兼容层
- 旧 `model_optimizer` 兼容层
- 旧 `llm_singleton` 兼容层
- 旧 `core.compatibility` 兼容层

### 已验证的残留扫描

对 `backend/app`、`core`、`agents` 的 Python 运行时代码进行扫描，确认以下模式已无残留：

- `from app.services.llm_client import ...`
- `from app.services.model_optimizer import ...`
- `from app.services.agents.llm_singleton import ...`
- `from .llm_singleton import ...`
- `from ..llm_client import ...`
- `from ..model_optimizer import ...`

## 4. 测试执行

### 4.1 已通过

命令：

```bash
python -m pytest tests/test_model_dispatch_refactor.py tests/test_unified_model_system.py -q
python -m pytest tests -q
```

结果：

- `tests/test_model_dispatch_refactor.py`：通过
- `tests/test_unified_model_system.py`：通过
- `tests/` 全量：`27 passed`

### 4.2 导入冒烟测试

已成功导入以下关键模块：

- `core.model_resolution`
- `core.model_runtime`
- `core.unified_llm_client`
- `core.langchain_bridge`
- `core.model_hub`
- `core.llm_adapters`
- `agents.llm_client`
- `backend.app.services.streaming_service`
- `backend.app.services.book_parser.content_analyzer`
- `backend.app.services.agents.agents`
- `backend.app.services.agents.outline_expander`
- `backend.app.services.audiobook.script_adapter`

### 4.3 未通过项

命令：

```bash
python -m pytest backend/tests/test_auth_routes.py -q
```

结果：

- `9 failed`

失败原因：

- 失败发生在 `starlette.testclient.TestClient` 初始化阶段
- 具体报错：`TypeError: Client.__init__() got an unexpected keyword argument 'app'`
- 这是 `starlette / fastapi` 与当前 `httpx` 版本组合的测试环境兼容问题
- 失败发生在鉴权测试客户端构建之前，与本次模型调度改造无直接代码耦合

## 5. 风险评估

### 已覆盖风险

- 旧调用入口仍被运行时代码引用
- 任务类型和模型别名未归一化导致路由失效
- LangChain 风格调用无法接入新中心
- 流式生成链路仍绕过新中心
- DreamWeaver 的同步 `chat_completions` 仍直连旧 API

### 剩余风险

- `backend/tests/test_auth_routes.py` 当前无法作为回归基线，需要单独处理测试依赖兼容
- 业务级端到端验证（真实模型凭证、真实 PostgreSQL/Redis、完整工作流）未在本报告中自动化执行
- 图像 / TTS / 其他多模态能力尚未全部纳入同一注册中心协议，本次改造聚焦文本大模型调用链路

## 6. 结论

本次改造已经完成文本大模型调用路径统一收口，并删除旧兼容链路。运行时代码层面已无旧入口残留，核心测试通过，关键模块导入正常。后续若要继续扩展，可在现有 `ModelHub + UnifiedModelRegistry` 底座上，将 TTS / 图像 / 视频模型进一步纳入同一套注册与调度协议。
