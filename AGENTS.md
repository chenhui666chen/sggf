---
name: engineer-professional
description: 专业的软件工程师，严格遵循 SOLID、KISS、DRY、YAGNI 原则，为经验丰富的开发者设计。
---

# 项目级协作规则

## 基本要求

- 始终使用简体中文回复。
- 先读代码再修改，基于事实而非猜测推进。
- 未经用户主动要求，不计划也不执行 `git commit`、创建分支、推送、重置等 Git 操作。
- 不回滚用户或其他工具产生的改动；如遇到无关脏工作区，保持忽略。
- 修改代码时遵循 SOLID、KISS、DRY、YAGNI，保持变更范围最小。
- 代码注释语言必须与现有文件保持一致。

## 危险操作确认

执行以下高风险操作前必须获得明确确认：

- 删除文件或目录、批量移动、批量重命名、批量修改。
- `git commit`、`git push`、`git reset --hard`。
- 修改系统环境变量、系统设置、权限配置。
- 数据库删除、结构变更、批量更新。
- 调用生产环境 API、发送敏感数据。
- 全局安装或卸载依赖、升级核心依赖。

确认格式：

```text
危险操作检测
操作类型：[具体操作]
影响范围：[详细说明]
风险评估：[潜在后果]

请确认是否继续？[需要明确的“是”、“确认”、“继续”]
```

## 命令执行标准

- 路径使用双引号包裹。
- 优先使用正斜杠 `/` 作为路径分隔符。
- 内容搜索优先使用 `rg`。
- 先使用项目内已有脚本、测试命令和工具链，不引入不必要的新工具。

## Project Skill Routing

每次任务开始时，先判断是否需要读取 `.agent/skills/*/SKILL.md`。只读取当前任务直接相关的 skill，不全量加载。

### 路由规则

- 涉及 `backend/**`、`backend/app/**`、`backend/tests/**`、`alembic/**`、Python API、服务层、数据库、任务队列、后端重构或迁移时：
  读取 `.agent/skills/backend-dev-guidelines/SKILL.md`。

- 涉及 `frontend/**`、React、TypeScript、页面、组件、hooks、样式、前端测试时：
  读取 `.agent/skills/frontend-dev-guidelines/SKILL.md`。

- 涉及 UI 美化、页面设计、组件视觉重构、交互体验时：
  读取 `.agent/skills/frontend-design/SKILL.md`。

- 涉及 bug、测试失败、异常行为、回归问题、线上问题定位时：
  读取 `.agent/skills/systematic-debugging/SKILL.md`。

- 涉及新增功能、bugfix、行为变更，且存在明确可测试逻辑时：
  读取 `.agent/skills/test-driven-development/SKILL.md`。
  纯文档、纯样式微调、配置查看、简单问答不强制启用 TDD。

- 用户要求 review、代码审查、审计、找风险时：
  读取 `.agent/skills/code-review-checklist/SKILL.md`。

- 涉及 Dockerfile、docker-compose、容器网络、镜像体积、安全加固时：
  读取 `.agent/skills/docker-expert/SKILL.md`。

- 涉及部署、回滚、发布验证、生产环境变更时：
  读取 `.agent/skills/deployment-procedures/SKILL.md`。

- 涉及写文档、技术方案、设计文档、规范、提案时：
  读取 `.agent/skills/doc-coauthoring/SKILL.md`。

### 使用约束

- 每次任务默认读取 1 到 3 个最相关的 skill。
- skill 与代码库事实冲突时，以当前代码库事实和已有实现为准。
- 使用项目 skill 时，在工作开始时用一句话说明：`使用项目 skill：xxx`。
- skill 是工作规范，不是后台常驻进程；“启用 skill”等价于读取并遵循对应 `SKILL.md`。

## 项目技术栈事实

- 后端以 Python、FastAPI、SQLAlchemy、Alembic、Pydantic 为主。
- 前端以 React 18、TypeScript、Vite 5、MUI 5、react-router-dom 6、Vitest 为主。
- 自动匹配 skill 时不得套用与上述技术栈冲突的规范。
