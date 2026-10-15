# 项目规则（Project Rules）

本文件用于约束 AI 编程助手在本项目中的行为。所有规则具有强制性，除非用户在对话中明确覆盖。

---

## 一、Skills 自动加载规则

项目的自定义知识库位于 `.agent/skills/` 目录。AI 在执行以下任务前，**必须先阅读并遵循对应的 `SKILL.md`**（以及其 `resources/` 下相关文档）：

| 任务类型 | 必读 Skill |
|---------|-----------|
| 编写 / 修改后端代码（`backend/`、`adapters/`、`agents/` 等 Python 服务） | `.agent/skills/backend-dev-guidelines/SKILL.md` |
| 编写 / 修改前端代码（React / TypeScript / 样式 / 路由） | `.agent/skills/frontend-dev-guidelines/SKILL.md` |
| 前端视觉与交互设计 | `.agent/skills/frontend-design/SKILL.md` |
| 编写或重构测试、实践 TDD | `.agent/skills/test-driven-development/SKILL.md` |
| 排查 Bug、分析异常、定位测试污染或竞态 | `.agent/skills/systematic-debugging/SKILL.md` |
| 进行代码评审、自检 PR | `.agent/skills/code-review-checklist/SKILL.md` |
| 编写 / 修改 Dockerfile、compose、镜像构建相关 | `.agent/skills/docker-expert/SKILL.md` |
| 部署、发布、环境切换、SSL / 反向代理 | `.agent/skills/deployment-procedures/SKILL.md` |
| 撰写或修订项目文档（README、指南、注释） | `.agent/skills/doc-coauthoring/SKILL.md` |
| 视频网关新供应商/新档位登记、模型活性探测与付费实证复探（`router_gateway/` 台账） | `.agent/skills/video-route-onboarding/SKILL.md` |

### 执行要求

- 在动手编码 **之前**，先读取相关 `SKILL.md` 建立上下文；如文档引用了 `resources/` 子文件，则按需进一步阅读。
- 如同一任务涉及多个领域（例如新增一个带测试的后端接口），必须同时遵循 backend-dev-guidelines 与 test-driven-development。
- 若 skill 中的建议与当前代码现状冲突，应优先保持与现有代码风格一致，并在回复中向用户指出冲突点。
- 若用户明确要求"跳过 skill"或"不必遵循规范"，则本次任务可以忽略上述加载要求。

---

## 二、通用编码原则

- **不要无关改动**：只做用户要求的事，不附带风格重排、注释增删或无关重构。
- **不要擅自生成文档**：除非用户明确要求，不要创建 `*.md`、README 等文档文件。
- **优先编辑而非新建**：能在现有文件内完成的修改，不新增文件。
- **注释语言**：跟随用户对话语言（中文对话 → 中文注释）。
- **导入语句**：始终置于文件顶部，禁止就地 import。

---

## 三、回复语言

- 始终使用与用户最近一条消息相同的语言作答，除非用户明确要求切换。

---

_最后更新：2026-04-24_
