---
name: frontend-dev-guidelines
description: Project-specific frontend standards for this repository. Use when working on React 18, TypeScript, Vite, MUI 5, react-router-dom, Vitest, frontend pages, components, hooks, API clients, styling, performance, or frontend refactors.
---

# Frontend Development Guidelines

适用范围：本仓库前端代码，主要技术栈为 React 18、TypeScript、Vite 5、MUI 5、react-router-dom 6、Vitest。

本 skill 定义前端任务的工作方式。使用时以现有组件、主题、路由和测试结构为准，不引入未使用框架或不符合项目现状的约束。

## When to Use

在以下任务中使用：

- 修改 `frontend/src/**` 下的页面、组件、hooks、utils、types、services。
- 修改 React Router 页面流转、API client、前端状态和副作用逻辑。
- 修改 MUI 组件样式、主题 token、响应式布局或交互体验。
- 编写或修复 Vitest 测试。
- 做前端性能优化、可维护性重构、类型收敛。

## Core Principles

- **KISS**：组件职责清楚，状态尽量局部化，避免不必要的状态机和抽象层。
- **YAGNI**：不添加当前页面不用的 props、模式、配置开关或框架迁移入口。
- **DRY**：重复的格式化、API 适配、按钮状态、样式 token 应提取复用。
- **SOLID**：页面负责编排，组件负责展示和局部交互，hooks 负责可复用状态逻辑。

## Architecture Rules

- 先查找现有同类页面、组件、hook 和测试，延续项目风格。
- 页面级组件可以编排数据和流程；复杂逻辑下沉到 hook、utils 或 service。
- 共享组件保持窄接口，不暴露与单一页面强绑定的业务细节。
- API 调用优先集中在 `frontend/src/services/api.ts` 或既有 service 层。
- 类型定义优先复用 `frontend/src/types/**` 和页面内已有类型。

## React And TypeScript Rules

- 使用函数组件和 hooks，避免新增 class component。
- `useMemo`、`useCallback` 只用于稳定引用、昂贵计算或传递给重组件的 handler，不机械滥用。
- 副作用必须有清晰依赖和清理逻辑，避免重复请求、泄漏计时器、陈旧闭包。
- 禁止新增 `any`，除非外部动态数据无法合理建模，并需要局部收敛。
- 导入类型使用 `import type`，保持已有 lint 风格。

## MUI And UI Rules

- 使用 MUI 5 语法和当前项目主题，不使用 MUI 7 专属 API。
- 按钮、Tooltip、loading、disabled、danger/warning 等状态优先复用现有模式。
- 响应式布局必须检查移动端和桌面端，避免文字溢出、按钮换行错位、内容重叠。
- 不做营销式 landing page；业务工具页面优先信息密度、可扫描性和稳定操作。
- 涉及明显视觉设计或 UI 重构时，同时使用 `frontend-design`。

## Routing Rules

- 当前项目使用 `react-router-dom`，不得引入 TanStack Router 规则。
- 路由变更应检查入口、导航、参数读取、刷新恢复和空状态。
- 页面拆分应保持可理解，不为了“懒加载”牺牲简单性。

## Testing Rules

- 行为变更优先补充或更新 Vitest。
- Hook、utils、API 适配、复杂按钮状态和本地存储逻辑应有 focused tests。
- UI 布局类变更至少通过类型检查或现有测试；有条件时运行相关测试。
- 若无法运行测试，最终回复必须说明原因和未覆盖风险。

## Refactor Rules

- 不同时重构无关页面或全局样式。
- 提取组件前先确认重复是真实重复，而不是局部语义相似。
- 保持现有导入路径、文件命名和测试组织方式。
- 不引入新的 UI 库、状态库、路由库或数据请求库，除非用户明确要求。

## Validation Checklist

完成后检查：

- [ ] 是否读取了相关页面、组件、hook、service、type 和测试。
- [ ] 是否符合 React 18、Vite 5、MUI 5、react-router-dom 6、Vitest 的项目事实。
- [ ] 是否没有引入未使用抽象、props、依赖或框架迁移。
- [ ] 是否覆盖了关键测试，或说明了无法测试原因。
- [ ] 是否检查了响应式和交互状态的基本风险。

## Related Skills

- `frontend-design`：涉及视觉质量、布局、组件外观、交互体验时同时使用。
- `systematic-debugging`：遇到 bug、测试失败或异常行为时同时使用。
- `test-driven-development`：新增功能或 bugfix 且可测试时同时使用。
- `backend-dev-guidelines`：涉及 API 合约或前后端字段对齐时同时使用。
