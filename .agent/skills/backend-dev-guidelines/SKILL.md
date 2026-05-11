---
name: backend-dev-guidelines
description: Project-specific backend standards for this repository. Use when working on Python FastAPI routes, services, repositories, SQLAlchemy/Alembic database code, Pydantic schemas, background jobs, API contracts, backend tests, or backend refactors.
---

# Backend Development Guidelines

适用范围：本仓库后端代码，主要技术栈为 Python、FastAPI、SQLAlchemy、Alembic、Pydantic、pytest。

本 skill 定义后端任务的工作方式。使用时先读取相关代码和测试，再决定实现；不得把其他技术栈的约束套到当前项目。

## When to Use

在以下任务中使用：

- 修改 `backend/app/api/**`、`backend/app/services/**`、`backend/app/schemas/**`。
- 修改 SQLAlchemy 模型、Repository、查询、事务或 Alembic 迁移。
- 修改后台任务、音频书生成链路、TTS/音频处理服务。
- 修改后端 API 合约、权限校验、错误处理、观测日志。
- 编写或修复 `backend/tests/**`。
- 做后端重构、性能优化、N+1 查询修复或数据一致性修复。

## Core Principles

- **KISS**：优先直接、局部、可读的实现，避免为未来假设做复杂抽象。
- **YAGNI**：只实现当前任务需要的行为，不新增未使用配置、参数、接口或兼容分支。
- **DRY**：对真实重复的业务逻辑提取共享函数；不要为表面相似但语义不同的流程强行抽象。
- **SOLID**：保持 API、服务、仓储、序列化、任务编排的职责边界清晰。

## Architecture Rules

- FastAPI route 负责请求边界：依赖注入、参数解析、权限校验、响应模型、HTTP 错误转换。
- Service 负责业务规则和流程编排，避免直接依赖请求对象。
- Repository 负责数据库读写和查询表达，不把 HTTP 概念泄漏到数据层。
- Schema/Pydantic 模型负责输入输出结构，不承载复杂业务流程。
- 后台任务应保持可恢复、可观测；长流程拆分为明确的小函数或小服务。
- 跨层调用必须单向：route -> service -> repository/database。

## FastAPI Rules

- 优先使用 `Depends` 复用认证、数据库 session、权限和公共参数。
- 业务失败使用明确的 `HTTPException` 或项目既有错误封装。
- 返回结构遵循现有 schema，不临时拼接不稳定字段。
- 不在 route 内堆积长业务逻辑；超过清晰边界时下沉到 service。
- 保持 endpoint 行为向后兼容，除非任务明确要求删除或变更合约。

## SQLAlchemy And Data Rules

- 查询逻辑优先集中在 repository 或已有数据访问服务。
- 修改查询时主动检查 N+1、事务边界、软删除过滤、权限过滤。
- 更新或删除数据前确认影响范围；批量数据操作属于危险操作，需要用户确认。
- 日期、路径、JSON 快照等序列化逻辑应集中复用，避免散落的手写转换。
- Alembic 迁移只在任务明确涉及 schema 变更时创建。

## Testing Rules

- 后端行为变更优先补充或更新 pytest。
- Bugfix 优先先写能复现问题的测试，再修复。
- 高风险路径至少覆盖 route/service/repository 中最能证明行为的层级。
- 性能或 N+1 修复应补充查询次数、批量场景或回归测试。
- 若无法运行测试，最终回复必须说明原因和未覆盖风险。

## Refactor Rules

- 保持外部行为不变，除非任务明确要求行为变更。
- 小步提交式修改：先抽取纯函数或 helper，再替换调用点。
- 不同时重构无关模块。
- 不删除看似无用代码，除非已用 `rg` 确认引用并理解运行入口。
- 对已有脏工作区只读不回滚。

## Validation Checklist

完成后检查：

- [ ] 是否读取了相关 route/service/repository/schema/test。
- [ ] 是否保持 FastAPI、SQLAlchemy、Pydantic 的现有项目风格。
- [ ] 是否没有引入未使用抽象、配置或依赖。
- [ ] 是否覆盖了关键测试，或说明了无法测试原因。
- [ ] 是否没有执行未经确认的危险操作。

## Related Skills

- `systematic-debugging`：遇到 bug、测试失败或异常行为时同时使用。
- `test-driven-development`：新增功能或 bugfix 且可测试时同时使用。
- `deployment-procedures`：涉及发布、回滚、生产验证时同时使用。
