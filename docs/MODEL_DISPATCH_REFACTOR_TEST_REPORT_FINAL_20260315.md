# 模型调度改造最终测试报告
日期：`2026-03-15`

## 1. 改造范围

本次改造聚焦文本大模型调用链路的统一收口，并同步清理旧兼容实现、直连调用痕迹与无效依赖。核心落地点如下：

- 新增统一任务/模型归一化层：`core/model_resolution.py`
- 新增统一运行时初始化与同步桥：`core/model_runtime.py`
- 新增统一异步客户端：`core/unified_llm_client.py`
- 新增 LangChain 兼容桥：`core/langchain_bridge.py`
- 将业务模块统一改为通过 `ModelHub`、`UnifiedLLMClient` 或 LangChain 兼容桥调用模型
- 重写流式服务：`backend/app/services/streaming_service.py`
- 重写 DreamWeaver 使用的 `agents/llm_client.py`，内部统一走 `ModelHub`
- 删除旧兼容链路：
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
- 运行时代码与示例代码中的 `ChatOpenAI` 直连入口
- 未再被运行时代码使用的 `langchain-openai` 依赖

### 已验证的残留扫描

对 `backend/app`、`core`、`agents` 的 Python 运行时代码进行扫描，确认以下模式已无残留：

- `from app.services.llm_client import ...`
- `from app.services.model_optimizer import ...`
- `from app.services.agents.llm_singleton import ...`
- `from .llm_singleton import ...`
- `from ..llm_client import ...`
- `from ..model_optimizer import ...`
- `from langchain_openai import ChatOpenAI`
- `from langchain_community.chat_models import ChatOpenAI`
- `ChatOpenAI(...)`

## 4. 测试执行

### 4.1 已通过

命令：

```bash
python -m pytest tests -q
python -m pytest backend/tests/test_auth_routes.py -q
python -m pytest tests backend/tests/test_auth_routes.py -q
```

结果：

- `tests/test_model_dispatch_refactor.py`：通过
- `tests/test_unified_model_system.py`：通过
- `backend/tests/test_auth_routes.py`：`9 passed`
- 联合回归：`36 passed`
- 当前仅剩 `2` 条告警，均来自 `python-jose` 内部 `datetime.utcnow()` 的弃用提示，不影响本次改造结论

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

### 4.3 兼容修复

为恢复鉴权回归基线，补充了以下兼容处理：

- 将 `backend/tests/test_auth_routes.py` 中的测试客户端改为基于 `httpx.ASGITransport + AsyncClient` 的轻量兼容实现，消除了 `fastapi/starlette` 与当前 `httpx 0.28.x` 的 `TestClient` 初始化冲突
- 为测试夹具补齐 `roles` 与 `user_roles` 表，确保 `UserResponse` 序列化时可以正常加载角色关联
- 将 `ChatOpenAI` 直连模式加入静态扫描测试，防止后续回退到旧调用方式

## 5. 风险评估

### 已覆盖风险

- 旧调用入口仍被运行时代码引用
- 任务类型和模型别名未归一化导致路由失效
- LangChain 风格调用无法接入新中心
- 流式生成链路仍绕过新中心
- DreamWeaver 的同步 `chat_completions` 仍直连旧 API
- 测试栈因 `httpx` 版本变化而失去认证回归能力

### 剩余风险

- 业务级端到端验证（真实模型凭证、真实 PostgreSQL/Redis、完整工作流）未在本报告中自动化执行
- 图像 / TTS / 其他多模态能力尚未全部纳入同一注册中心协议，本次改造聚焦文本大模型调用链路

## 6. 结论

本次改造已经完成文本大模型调用路径统一收口，并删除旧兼容链路。运行时代码层面已无旧入口残留，`ChatOpenAI` 直连痕迹已清理，认证测试基线已恢复，联合回归结果为 `36 passed`。后续若继续扩展，可在现有 `ModelHub + UnifiedModelRegistry` 底座上，将 TTS / 图像 / 视频模型进一步纳入同一套注册与调度协议。
