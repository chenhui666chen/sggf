# novel_writing_agent 仓库清理规则

日期：`2026-04-19`

## 1. 文档目的

本文档用于指导本仓库进行“临时调试文件与废弃文件清理”，目标是：

- 移除明确无用的调试产物、一次性排查脚本、临时测试脚本和已废弃文件。
- 保证主流程、正式测试、正式文档、配置、迁移、启动与部署方式不受影响。
- 为后续清理操作提供一份可直接引用的、基于当前仓库实际结构修订过的规则说明。

本文档是**仓库专用规则**，优先级高于通用的“看到 `test_` / `REPORT` / `SUMMARY` 就删”的机械判断。

## 2. 当前仓库的实际结构基线

截至 `2026-04-19`，当前仓库的关键结构特征如下。

### 2.1 正式测试目录

以下目录是正式测试目录，默认保留：

- `/tests`
- `/backend/tests`

这两个目录中的 `test_*.py`、`*_test.py`、测试辅助文件、夹带的 `user_center_test_helpers.py` 等，默认视为正式测试体系的一部分，**不能仅凭文件名前缀删除**。

### 2.2 正式文档目录与正式说明文档

以下内容默认保留：

- 根目录 [README.md](README.md)
- 根目录和子目录中的 `README*.md`、`*_GUIDE.md`、`*_README.md`
- `/docs/**`
- 服务目录中的正式说明文档，例如：
  - `backend/app/services/audiobook/README.md`
  - `backend/app/services/audiobook/README_AI_MUSIC.md`

当前仓库里即使文件名包含 `REPORT`、`TEST_REPORT`、`SUMMARY`，也**不代表它是临时文件**。实际扫描中，以下文档已经被根目录 README 引用，属于正式资料，默认保留：

- `docs/MODEL_DISPATCH_REFACTOR_TEST_REPORT_FINAL_20260315.md`
- `docs/UNIFIED_MEDIA_RUNTIME_TEST_REPORT_20260315.md`
- `docs/MODEL_KNOWLEDGE_BASE_20260315.md`
- `docs/MODEL_INTEGRATION_REFERENCE.md`
- `docs/MODEL_ROUTING_OPTIMIZATION_PLAN_20260417.md`
- `docs/POSTGRESQL_DEPLOYMENT.md`
- `docs/AUDIOBOOK_TASK_QUEUE.md`

补充说明：

- 当前仓库中部分正式文档存在编码损坏/乱码现象，这属于“内容修复问题”，**不是删除依据**。

### 2.3 正式脚本、部署与配置文件

以下内容默认保留：

- 启动脚本：`start*.py`、`start*.bat`、`start*.ps1`
- 部署脚本：`deploy*.bat`、`deploy*.ps1`、`deploy*.sh`
- 数据库迁移：`backend/alembic/**`、`backend/alembic/versions/**`
- 配置文件：`.env*`、`.json`、`.yaml`、`.yml`、`.ini`、`.toml`
- 依赖文件：`requirements*.txt`、`package.json`、`package-lock.json`
- 前端配置：`vite.config.ts`、`tsconfig*.json`、`postcss.config.js`、`tailwind.config.js`
- 运行数据与数据库文件：例如 `backend/novel_app.db`、`backend/novel_writing.db`、`backend/app.db`
- 服务端入口与核心模块：例如 `backend/app/main.py`、`backend/app/**`

### 2.4 `scripts/` 目录不是临时目录

当前仓库的 `scripts/` 目录承载了正式的验证和运维辅助脚本，不能一概视为临时脚本。

实际扫描中，以下脚本已被正式文档引用，应默认保留：

- `scripts/test_all_models.py`
- `scripts/test_image_input_models.py`

因此：

- `scripts/test_*.py` **不能自动纳入删除池**
- `scripts/*.json`、`scripts/model_test_report.md` 之类的产物文件，只能在确认“可重生成且未被依赖”后作为候选

### 2.5 业务源码目录中可能存在 `test_` 命名文件

本仓库存在名字像测试、实际属于业务源码的数据/样本模块，典型例子：

- `backend/app/services/prompt_evolution/test_samples.py`

该文件被以下代码和测试引用：

- `backend/app/services/prompt_evolution/evaluator.py`
- `backend/app/services/prompt_evolution/engine.py`
- `backend/app/services/prompt_evolution/__init__.py`
- `tests/test_prompt_evolution_sample_manager.py`

因此规则必须明确：

- **位于业务源码目录中的 `test_*.py`，默认不因文件名前缀删除**
- 只有在确认“无 import、无数据用途、无测试引用、无脚本引用”后，才可进入候选池

## 3. 默认保留规则

执行清理时，以下内容默认保留，不进入删除候选：

### 3.1 正式测试

- `/tests/**`
- `/backend/tests/**`

### 3.2 正式文档

- 根目录 `README.md`
- 根目录和子目录下的 `README*.md`
- 根目录和子目录下的 `*_GUIDE.md`
- 根目录和子目录下的 `*_README.md`
- `/docs/**`
- 与部署、模型接入、数据库、任务队列、功能方案相关的文档

### 3.3 正式脚本与配置

- `start*.py`、`start*.bat`、`start*.ps1`
- `deploy*.bat`、`deploy*.ps1`、`deploy*.sh`
- `backend/alembic/**`
- `.env*`
- `*.json`、`*.yaml`、`*.yml`、`*.ini`、`*.toml`
- `requirements*.txt`
- `package.json`
- `package-lock.json`
- `vite.config.ts`
- `tsconfig*.json`

### 3.4 正式业务源码

以下目录中的正式源码文件，除非已经确认完全废弃且未被引用，否则不清理：

- `backend/app/**`
- `agents/**`
- `adapters/**`
- `core/**`
- `pipeline/**`
- `shared/**`
- `frontend/src/**`

## 4. 允许进入候选池的内容

本节是“允许清理”的**项目专用版本**。只要不满足这些条件，就默认保留。

### 4.1 仓库根目录中的一次性修复/排查脚本

当前仓库根目录存在一批高度疑似的一次性修复脚本，集中生成于 `2026-04-19`，并且本轮扫描中**仓库内引用数为 0**。

可优先作为候选池的模式：

- `check_*.py`
- `debug*.py`
- `find_*.py`
- `fix_*.py`
- `remove_*.py`
- `temp*.py`

当前仓库中还应纳入同一候选池的单文件模式：

- `analyze_pua.py`
- `decode_mojibake.py`
- `show_context.py`
- `smart_fix.py`
- `comprehensive_fix.py`
- `comprehensive_autofix.py`
- `get_all_errors.py`

说明：

- 这类文件本次扫描约 `90` 个，几乎全部集中在仓库根目录。
- 这类文件的命名、时间分布、引用情况都符合“临时排查/修复产物”的特征。
- **后续实际清理时，这一组应作为第一优先级候选池。**

### 4.2 不在正式测试目录中的 `test_*.py`

本仓库中，以下文件虽然命名为 `test_*.py`，但**不在** `/tests` 或 `/backend/tests` 中，因此不能自动视为正式测试。

当前快照中的候选范围如下。

仓库根目录：

- `test_image_enhancement.py`
- `test_minimax_integration.py`
- `test_minimax_real.py`
- `test_mojibake.py`
- `test_phase2_stats.py`
- `test_yaml_encoding.py`

`backend/` 顶层：

- `backend/test_character_profile_flow.py`
- `backend/test_prompt_json.py`
- `backend/test_tts_dispatch.py`
- `backend/test_tts_model_integration.py`
- `backend/test_voice_persistence_flow.py`

`frontend/` 顶层：

- `frontend/test_ui_features.py`

处理规则：

- 这批文件应进入“候选池”，但**默认不是高置信度直接删除项**。
- 只有在确认以下条件全部满足时，才允许删除：
  - 不在正式测试目录
  - 无 README / docs / CI / 脚本引用
  - 不是当前功能开发过程中的回归验证脚本
  - 已有正式测试目录中的测试覆盖对应能力，或者经人工确认不再需要

### 4.3 临时 Markdown 文档和重复报告

只有满足以下条件的 Markdown 文件，才允许进入候选池：

- 文件名或正文明确说明其为一次性调试、排查、修复记录、临时输出、阶段性草稿
- 没有被 README、文档导航、脚本或代码引用
- 同类报告存在多份版本，且已经存在更晚日期、状态更稳定的正式版本

针对当前仓库的特殊规则：

- `/docs/**` 默认保留
- `README` 中已引用的测试报告、方案文档默认保留
- 即使文件名包含 `REPORT`、`SUMMARY`、`TEST_REPORT`，**也不自动删除**

### 4.4 `scripts/` 目录中的输出产物

`scripts/` 下的以下类型文件，可以作为候选项，但不能自动删除：

- `scripts/*.json` 报告文件
- `scripts/model_test_report.md`

进入候选池的前提：

- 能确认这些文件是脚本生成的输出，而不是手工维护资料
- 没有被 README、docs 或其他脚本继续消费
- 删除后能够随时通过脚本重生成

### 4.5 缓存与编译产物

以下内容属于**可清理的缓存/构建产物**，但不属于“废弃源码/废弃文档”：

- 仓库根目录 `.pytest_cache/`
- `backend/.pytest_cache/`
- 仓库中的 `__pycache__/`
- `tests/__pycache__/`
- `backend/tests/__pycache__/`
- `scripts/__pycache__/`

注意：

- 清理 `__pycache__` 时，**不要操作 `.venv/**` 下的缓存**
- `frontend/dist/` 属于构建产物，可单独作为“构建产物清理”处理，但不建议和“废弃文档/脚本清理”混在同一轮执行
- `frontend/node_modules/` 不属于废弃目录，默认保留

## 5. 当前仓库中的明确保留例外

以下是容易误删、但当前规则下应明确保留的例外项。

### 5.1 文档类保留例外

- `docs/MODEL_DISPATCH_REFACTOR_TEST_REPORT_FINAL_20260315.md`
- `docs/UNIFIED_MEDIA_RUNTIME_TEST_REPORT_20260315.md`
- `docs/MODEL_INTEGRATION_REFERENCE.md`
- `docs/LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md`
- `docs/AUDIOBOOK_TASK_QUEUE.md`

### 5.2 脚本类保留例外

- `scripts/test_all_models.py`
- `scripts/test_image_input_models.py`
- `scripts/analyze_model_integration.py`
- `scripts/verify_all_adapters.py`
- `scripts/verify_model_config.py`

### 5.3 源码类保留例外

- `backend/app/services/prompt_evolution/test_samples.py`
- `backend/app/main.py`
- `backend/app/api/**`
- `backend/app/models/**`
- `backend/app/services/**`

补充说明：

- 文件内容乱码、编码损坏、注释异常，都不是删除依据。
- 对正式文档/正式源码，应优先“修复”而不是“清理”。

## 6. 清理执行流程

### 6.1 第一步：先扫描，生成候选清单

优先使用 `rg` 和目录扫描命令，先输出候选池，不直接删除。

#### 6.1.1 扫描根目录高置信度临时脚本

```powershell
rg --files `
  -g "check_*.py" `
  -g "debug*.py" `
  -g "find_*.py" `
  -g "fix_*.py" `
  -g "remove_*.py" `
  -g "temp*.py" `
  -g "analyze_pua.py" `
  -g "decode_mojibake.py" `
  -g "show_context.py" `
  -g "smart_fix.py" `
  -g "comprehensive_fix.py" `
  -g "comprehensive_autofix.py" `
  -g "get_all_errors.py"
```

#### 6.1.2 扫描非正式测试目录中的 `test_*.py`

```powershell
rg --files `
  -g "test_*.py" `
  -g "backend/test_*.py" `
  -g "frontend/test_*.py"
```

#### 6.1.3 扫描缓存目录

```powershell
Get-ChildItem -Recurse -Directory -Filter "__pycache__"
Get-ChildItem -Force ".pytest_cache","backend/.pytest_cache","scripts/.pytest_cache" -ErrorAction SilentlyContinue
```

### 6.2 第二步：逐项做引用确认

对每个候选文件，至少执行一次仓库内引用检查。

```powershell
rg -n "文件名.py" README.md docs backend frontend scripts tests
```

判定依据：

- 有引用：默认保留
- 无引用：仍需结合目录位置、文件类型、是否为正式工具脚本做二次判断

### 6.3 第三步：输出待删清单并等待确认

真正删除前，必须先给出清单，按以下分类列出：

- 临时 Markdown 文档
- 临时测试脚本
- 疑似废弃代码文件
- 缓存/编译产物
- 源码内部高置信度调试代码位置

每个候选项必须附带简短依据，例如：

- 不在正式测试目录
- 仓库内引用为 0
- 与当前调试主题强相关，且命名明显为一次性脚本
- 属于缓存目录
- 属于重复报告的旧版本

### 6.4 第四步：确认后再删除

删除工具优先级：

1. `remove-files`
2. 安全的 PowerShell `Remove-Item -LiteralPath`

删除要求：

- 禁止未确认前批量删除
- 禁止对有疑义的正式文件做猜测式清理
- 一次只删除高置信度项

## 7. 删除后的最小验证要求

验证遵循“受影响范围最小化”原则。

### 7.1 仅删除 Markdown / 临时报告

至少执行：

```powershell
git diff --stat
```

如删除的是仓库中可能被引用的文档，还应执行：

```powershell
rg -n "被删文件名" README.md docs scripts backend frontend
```

### 7.2 仅删除根目录临时 Python 调试脚本

至少执行一次 Python 侧编译/导入检查，建议：

```powershell
python -m py_compile "backend/app/main.py"
```

如果本轮清理发生在有声书修复附近，建议额外执行：

```powershell
python -m py_compile "backend/app/api/v1/audiobook.py"
```

### 7.3 删除前端源码中的调试代码

至少执行：

```powershell
cd frontend
npm run type-check
```

如涉及构建链路，建议进一步执行：

```powershell
cd frontend
npm run build
```

### 7.4 删除后端源码中的调试代码

至少执行：

```powershell
python -m py_compile "backend/app/main.py"
```

如能定位到受影响模块，优先补一条最小 pytest 验证，例如：

```powershell
python -m pytest backend/tests -q -k "相关模块关键词"
```

## 8. 建议输出模板

每次正式清理后，建议按以下结构输出结果，便于复盘：

### 8.1 已删除文件

- 列出完整路径
- 标注删除依据

### 8.2 已保留的正式文件

- 列出本轮曾进入候选池、但最终被判定为正式文件的项目
- 标注保留依据

### 8.3 保留的最新成功报告

- 同类问题下保留哪一份报告
- 为什么保留它

### 8.4 删除后验证命令与结果

- 执行了哪些命令
- 是否通过

### 8.5 仍需人工判断的残留项

- 对“不够高置信度”的文件列入待确认列表
- 默认不删

## 9. 当前仓库快照下的推荐清理策略

如果后续要基于本文档直接开展清理，建议按以下顺序执行。

### 第一优先级：高置信度直接候选

优先处理仓库根目录下、命名明确且无引用的临时修复脚本：

- `check_*.py`
- `debug*.py`
- `find_*.py`
- `fix_*.py`
- `remove_*.py`
- `temp*.py`
- `analyze_pua.py`
- `decode_mojibake.py`
- `show_context.py`
- `smart_fix.py`
- `comprehensive_fix.py`
- `comprehensive_autofix.py`
- `get_all_errors.py`

### 第二优先级：缓存清理

单独处理：

- `.pytest_cache/`
- 仓库内 `__pycache__/`

但注意排除：

- `.venv/**`

### 第三优先级：待人工确认项

以下内容默认列为“人工确认”，不要直接删：

- 根目录 `test_*.py`
- `backend/test_*.py`
- `frontend/test_ui_features.py`
- `scripts/*.json` 报告产物
- `scripts/model_test_report.md`

## 10. 一句话执行准则

在本仓库中，**真正适合先清理的，是根目录那批无引用的一次性修复脚本和缓存目录；`docs/**`、`scripts/test_*.py`、业务源码目录里的 `test_*.py`、以及 README 已引用的报告文档，默认都应保留。**
