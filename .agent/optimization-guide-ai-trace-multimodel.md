# 织文无迹多模型竞争优化方案

> 状态基线：2026-07-25 代码审计后修订。下文早期 P0-P4 章节保留为演进记录；
> 实际交付状态及后续实现以本节和“P5-P8 验收标准”为准。

## 当前实现事实与设计约束

### 实际完成度

- P0-P4：主体已实现。
- P5 按题材存储：已完成题材存储、稳健迁移、手动题材评测和管理页分榜。
- P6 淘汰轮换：已完成持久化累计轮次、挑战前三名复活、挑战结果新周期统计及常规结果复用。
- P7 用户端题材感知：已完成模型/提示词同题材选择、项目题材导入、规范化和结果展示。
- P8 安全与验证：管理端点已限制管理员；检测失败不再污染成功统计；已有聚焦后端测试和前端映射测试。
- 联合质量评分：已持久化 `genre + prompt_version_id + model_id` 联合表现，并启用 70 分保真相似度硬门槛。

### 强制设计约束

1. 所有题材在进入存储前必须规范化为：`通用/玄幻/都市/言情/悬疑/科幻/历史/武侠`。
2. 项目元数据中的英文或别名题材必须映射到上述规范值；未知值回退 `通用`，不得创建任意 JSON 存储桶。
3. 模型配置修改、模型排行和全模型评测只允许管理员访问。
4. AI 检测失败不得作为 100 分“成功结果”写入模型历史，也不得触发错误淘汰。
5. 挑战周期使用题材级单调累计评测轮次，不使用每次进化任务从 1 开始的局部迭代号。
6. 挑战赛复用当前常规轮次的活跃模型结果，只额外调用挑战者，避免重复成本和统计加权。
7. 用户端提示词回退链固定为：题材已批准 > 题材历史最佳 > 通用已批准 > 通用历史最佳 > 题材初始提示词。
8. “最优组合”必须能追溯 `genre + model_id + prompt_version_id`；每个组合至少 3 条成功记录且平均保真相似度不低于 70，才允许参与生产自动路由。
9. 批准提示词优先级不能被联合排行绕过：先按题材提示词回退链确定提示词，再只在该提示词的联合记录中选择最佳模型。

## P5-P8 验收标准

### P5：题材分离存储

- `update_performance`、`update_auto_best_model`、`get_active_model_id` 均接收规范化题材。
- 旧版全局性能数据稳健迁移到 `通用`，不依赖当前模型白名单。
- `/evaluate-models` 接收并传递 `genre`；管理页可切换题材查看和触发评测。
- 指定题材无最佳模型时回退 `通用`；管理员全局选定仍拥有最高优先级。

### P6：淘汰与轮换

- 至少 5 次完整成功评测后，平均 AI 分高于最佳模型 20 分才淘汰。
- 至少 2 个模型达到成熟门槛后才开始横向比较淘汰。
- 改写失败或检测失败只计尝试次数，不计成功次数和平均 AI 分。
- 每累计 5 个常规评测轮次触发挑战；服务重启和新进化任务不重置累计轮次。
- 每次从当前题材淘汰池随机选择 1 个模型参加挑战。
- 挑战者进入本轮合格模型前三名才复活；同分时使用模型 ID 稳定排序，不扩大名额。
- 所有挑战者调用失败时不推进挑战周期，在后续有预算的评测轮次重试。
- 挑战排名完整复用常规轮次的语义评审与混合评分字段，确保活跃模型和挑战者使用相同质量资格标准。
- 多模型评测支持模型级调用策略；`doubao-seed-evolving` 在改写评测中关闭深度思考、限制 4096 输出并使用 90 秒超时，避免 Agent/Coding 模型拖慢短文本改写。
- 连续 3 次调用失败的模型按题材进入可用性熔断池；成功调用清零失败计数，熔断模型仍通过挑战赛获得恢复机会。
- 复活后清空该题材下旧统计，挑战通过结果作为新周期首条有效记录。

### P7：题材感知用户体验

- `/reduce` 对显式题材做规范化；未传题材时自动检测。
- 模型和提示词都按同一个规范题材选择。
- `genre_detected` 返回最终使用的规范题材；`model_used` 返回实际模型名称或默认路由标识。
- 灵感方舟导出携带项目题材，AITracePage 导入后自动映射并选中；无题材时保持自动检测。
- 页面提供自动、通用及 7 个具体题材选项，并展示实际模型和题材。

### P8：安全、质量与可验证性

- 模型管理端点使用 `require_admin`。
- 自动最优至少满足成功样本数门槛；后续联合评分需包含保真度硬门槛，避免只优化检测器分数。
- 新增后端单元/API 测试和前端交互/数据映射测试；后端编译、聚焦 pytest、前端类型检查全部通过。

### 联合评分与生产路由

- 联合记录文件：`model_prompt_performance.json`。
- 记录维度：题材 > 提示词版本 > 模型。
- 指标：评估/成功次数、平均 AI 分、平均降分、平均保真相似度、平均延迟和联合综合分。
- 当前联合综合分：`平均AI分 + (100 - 平均保真相似度) × 0.2`，越低越好。
- 保真相似度低于 70 的结果只计尝试次数，不进入成功平均值、自动最优、常规排行或挑战复活。
- 生产端先选择批准/历史提示词，再选择该提示词下至少 3 次成功且满足保真门槛的最佳模型；无成熟联合数据时回退题材模型汇总排行。
- 管理员手动选定模型始终拥有最高优先级，不受联合自动路由覆盖。
- 联合路由按稳定 `prompt_version_id` 查询，不再依赖提示词全文相等。
- 相同组合至少覆盖 3 个不同 `sample_hash` 才成熟；进化轮次按迭代轮换样本。
- 联合记录使用在线标准差和 `综合分 + 标准差 / sqrt(成功数)` 的置信惩罚排序。
- 联合记录绑定 `evaluation_policy_version`；规则、检测器或模型版本升级时更新策略版本，旧窗口自动退出生产路由。

### 并发安全、成本和审计

- `model_config.json`、`model_performance.json`、`model_prompt_performance.json` 使用进程锁、临时文件、`os.replace` 原子替换和上一版本 `.bak`。
- 模型汇总与联合统计的增量更新在同一读写锁内完成，避免并发任务丢写。
- 管理员手动全模型评测按题材互斥，完成后冷却 60 秒；默认每日全局最多完成 20 次。
- 每次模型尝试追加到 `model_evaluation_details.json`，记录批次、样本、模型/提示词版本、AI 分、保真度、延迟、错误类型和策略/检测器版本。
- 管理 API 提供 `/evaluation-metrics` 和 `/model-combinations`，管理页展示成功率、保真拒绝率、超时数及联合排行。
- 主 JSON 损坏时读取上一版本备份；没有可用备份时显式报错，禁止静默以空对象覆盖损坏数据。

### 单机后台任务执行约束

- 本功能按管理员低频、单机、单后台任务执行器设计，不以多主机并行评测为目标。
- 手动全模型评测、提示词进化启动和断点恢复共用全局任务租约；任一任务运行时其他后台优化任务返回冲突。
- 任务和预算状态持久化到 `background_optimization_state.json`，服务重启不会清零当日预算。
- 默认每日预算为 20 个全模型调用单位：手动全模型评测、进化周期评测、最终评测各消耗 1；实际挑战赛触发时额外消耗 1。
- 预算不足时跳过进化中的昂贵多模型评测和挑战赛，保留基础单模型进化流程；手动全模型评测直接返回预算不足。
- 管理状态包含任务类型、题材、开始/完成时间、模型完成/成功/失败数、当日已用/剩余预算和冷却截止时间。
- 任务进程异常退出后，下一次读取状态会识别失效 PID，将任务标记为 `interrupted` 并释放租约。
- PID 存活检测按平台实现：Windows 使用只读 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`，POSIX 才使用 `os.kill(pid, 0)`；禁止在 Windows 发送信号 0，避免误终止 Uvicorn。
- `model_evaluation_details.json` 最多保留最近 5000 条明细，汇总和联合统计不随旧明细裁剪而丢失。
- 普通用户结果只展示实际模型和题材；提示词版本、路由来源和资格指标仅保留在管理接口、管理页和日志中。
- 联合排行资格状态包括：数据不足、样本不足、保真不合格、策略已过期、可参与路由、当前生产使用。
- 遗留 `.lock` 和 `.tmp` 文件不影响后续锁获取；从 `.bak` 恢复后下一次原子写入会重新生成健康主文件。

### 全题材顺序进化

- 管理页支持“当前题材”和“全部题材”两种启动范围；默认参数为目标 AI 率 25、最大迭代 6、每次样本 4。
- 全部题材固定按 `玄幻 -> 都市 -> 言情 -> 悬疑 -> 科幻 -> 历史 -> 武侠` 在单机后台顺序执行，不需要多主机扩容。
- 每个题材必须创建独立的 `PromptEvolutionEngine` 和 `evolution_id`，不得在同一个进化历史的不同迭代中交替题材。
- 每个题材分别使用自己的样本、提示词版本、经验、模型排行、淘汰池和挑战状态；进化历史必须持久化 `genre`。
- 单个题材失败时记录到失败列表并继续下一题材；管理员停止任务时取消当前题材并终止剩余队列。
- `/status` 返回当前题材、队列位置、题材总数、已完成题材和失败题材，管理页实时展示这些状态。

### 题材识别完整性

- 自动检测覆盖：玄幻、都市、言情、悬疑、科幻、历史、武侠和通用。
- 项目英文题材先经统一别名映射；未知题材回退通用。
- 旧批准提示词通过 `evolution_id -> evolution_history.genre` 自动回填题材，无法判断时才作为通用。

## 核心架构（已修正）

多模型竞争发生在**提示词进化系统的后台评测阶段**，而非用户每次请求时。

- **进化系统**：后台评估提示词时，对所有模型并发测试，找出最优（提示词+模型）组合
- **用户使用时**：只调用**单一最优模型**，快速响应
- **管理员**：可查看模型表现排行，手动选定活跃模型；未选定时自动使用历史最优

---

## 已完成实现

### 1. 后端：多模型评估与活跃模型管理服务

**文件**：`backend/app/services/ai_trace_competition.py`

已实现：
- `MultiModelEvaluationService` — 9 个模型并发评估，服务于进化系统和管理员评测
- `ModelConfigStorage` — 持久化存储模型配置（管理员选定模型 + 自动最优模型 + 历史表现）
- `ModelPerformanceRecord` — 增量更新各模型的平均AI分数、降分幅度、最佳分、延迟
- `get_active_model_id()` — 优先级：管理员选定 > 自动最优 > None（默认路由）
- `update_auto_best_model()` — 至少评估3次的模型中自动选出分数最低者
- 并发控制：模型5并发、检测3并发、单模型120秒超时

### 2. 后端：AI 痕迹降低 API

**文件**：`backend/app/api/v1/ai_trace.py`

已实现端点：
- `POST /reduce` — 用户端，使用活跃模型单次改写（快速响应）
- `GET /model-config` — 获取当前活跃模型配置
- `POST /model-config` — 管理员设置/清除活跃模型
- `GET /available-models` — 查看模型列表及其历史表现数据
- `POST /evaluate-models` — 管理员手动触发多模型评测

### 3. 后端：评估器支持指定模型

**文件**：`backend/app/services/prompt_evolution/evaluator.py`

已实现：
- `_rewrite_text(prompt, text, temperature, model_id=None)` — 支持指定模型调用

### 4. 前端：用户端简化体验

**文件**：`frontend/src/pages/AITracePage.tsx`

已实现：
- 移除多模型竞争 UI（模式切换、模型选择 Chip、TOP3 卡片）
- 保持简洁的单模型降AI浓度体验
- 用户无需感知底层模型选择

---

## 历史实施方案（P0-P4 均已完成）

> 本节保留早期问题分析和实施思路，仅用于追溯，不再代表当前待办。
> 当前交付状态以文首“实际完成度”和“P5-P8 验收标准”为准。

### P0：进化引擎集成多模型评估

**问题**：`engine.py` 进化循环中每次迭代仅用单一模型（deepseek-v4-flash）评估提示词，未调用 `MultiModelEvaluationService`。

**改进方案**：

修改 `backend/app/services/prompt_evolution/engine.py`：
- 在每轮迭代的评估阶段，调用 `MultiModelEvaluationService.evaluate_across_models()`
- 对每个提示词变体，使用所有模型并发改写+检测
- 记录各模型在每个提示词下的表现数据
- 进化结束后自动更新 `auto_best_model`
- 进化历史中记录各模型的对比分数

关键集成点：
```python
# engine.py 的评估阶段（伪代码）
from app.services.ai_trace_competition import get_multi_model_service

# 在 _evaluate_prompt_version 中：
multi_model_service = get_multi_model_service()
result = await multi_model_service.evaluate_across_models(
    text=sample_text,
    prompt=current_prompt,
    temperature=self._get_current_temperature(),
)
# 使用最佳模型的分数作为该提示词的评分
best_model_score = result["results"][0]["ai_score"] if result["results"] else 100
```

**影响范围**：
- `engine.py` — 评估循环逻辑
- `models.py` — PromptVersion 数据模型增加 `best_model_id` 字段
- `storage.py` — 存储层适配新字段

---

### P1：前端管理页增加模型管理面板

**问题**：`PromptEvolutionPage.tsx` 和 `admin/PromptEvolutionPage.tsx` 缺少模型相关管理界面。

**改进方案**：

在管理员进化页面新增「模型管理」区块：
- 显示当前活跃模型（名称、提供商、设置来源）
- 模型表现排行榜（表格：模型名、平均AI分数、评估次数、最佳分数、平均耗时）
- 「设为活跃模型」按钮（每行操作）
- 「清除手动选定」按钮（回退到自动最优）
- 「触发全模型评测」按钮（调用 `/evaluate-models`）

**涉及文件**：
- `frontend/src/pages/PromptEvolutionPage.tsx`
- `frontend/src/pages/admin/PromptEvolutionPage.tsx`

---

### P2：管理员自定义测试样本

**问题**：`test_samples.py` 只有 10 个硬编码样本，无法用真实生产文本做进化评测。

**改进方案**：

- 新增 API：`POST /api/v1/prompt-evolution/samples`（添加样本）、`DELETE` / `GET`
- 存储层：`data/prompt_evolution/custom_samples.json`
- `TestSampleManager` 增加从存储加载自定义样本的逻辑
- 前端管理页增加「测试样本管理」区块：上传/粘贴文本、删除、查看列表

**涉及文件**：
- `backend/app/services/prompt_evolution/test_samples.py`
- `backend/app/api/v1/prompt_evolution.py`
- 前端管理页

---

### P3：进化状态持久化

**问题**：`prompt_evolution.py` 使用全局变量 `_running_task` / `_current_evolution_id`，服务重启后状态丢失。

**改进方案**：

- 将运行状态写入 `data/prompt_evolution/running_state.json`
- 服务启动时检查是否有未完成任务，标记为 `interrupted`
- 状态查询优先读取持久化文件而非内存变量

**涉及文件**：
- `backend/app/api/v1/prompt_evolution.py`
- `backend/app/services/prompt_evolution/storage.py`

---

### P4：AI输出格式特征清洗（降低格式维度AI信号）

**问题**：AI 模型输出的文本存在特殊格式特征，这些格式本身是 AI 检测器的强信号，但当前 `preprocess_text` / `postprocess_text` 仅处理词汇和标点层面，未覆盖格式层面。

**已知影响AI检测率的格式特征**：

| 特征 | 说明 | 影响程度 |
|------|------|----------|
| Markdown 标记残留 | `**加粗**`、`# 标题`、`- 列表`、`> 引用` 残留在纯文本中 | 高 |
| 英文半角标点混入 | AI 混入英文逗号 `,`、句号 `.`、分号 `;`、冒号 `:` | 高 |
| Unicode 特殊字符 | em-dash `—` 替代中文破折号 `——`，弯引号 `""` 替代中文引号 `""` | 中 |
| 段落结构过于均匀 | AI 产生等长段落，双换行分隔，结构机械 | 中 |
| 编号/列表格式 | AI 喜欢用 `1.` `2.` `3.` 或 `（一）（二）（三）` 组织内容 | 中 |
| 标点过于规范 | AI 不犯人类常见的标点错误（连逗号、逗号后无空格等） | 低-中 |
| 多余空格/缩进 | 段首多余空格、中英文间空格 | 低 |

**改进方案**：

在 `novel_rules.py` 的 `preprocess_text()` 中新增格式清洗步骤：

```python
def _strip_ai_formatting(text: str) -> Tuple[str, List[str]]:
    """清除AI输出的格式痕迹"""
    logs = []
    result = text

    # 1. 清除 Markdown 标记
    # 加粗/斜体
    if "**" in result or "__" in result:
        result = re.sub(r'\*\*(.+?)\*\*', r'\1', result)
        result = re.sub(r'__(.+?)__', r'\1', result)
        logs.append("清除Markdown加粗")
    if "*" in result or "_" in result:
        result = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', result)
        logs.append("清除Markdown斜体")
    # 标题
    result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
    # 列表
    result = re.sub(r'^\s*[-*+]\s+', '', result, flags=re.MULTILINE)
    result = re.sub(r'^\s*\d+\.\s+', '', result, flags=re.MULTILINE)
    # 引用
    result = re.sub(r'^>\s?', '', result, flags=re.MULTILINE)

    # 2. 英文半角标点 → 中文全角
    punct_map = {',': '，', '.': '。', ';': '；', ':': '：', '!': '！', '?': '？'}
    for eng, chn in punct_map.items():
        # 仅替换两侧是中文字符时的英文标点
        pattern = rf'([\u4e00-\u9fa5]){re.escape(eng)}([\u4e00-\u9fa5])'
        if re.search(pattern, result):
            result = re.sub(pattern, rf'\1{chn}\2', result)
            logs.append(f"修正半角标点: {eng}→{chn}")

    # 3. Unicode特殊字符规范化
    # em-dash → 中文破折号
    result = result.replace('—', '——').replace('———', '——')
    # 弯引号 → 中文引号
    result = result.replace('\u201c', '"').replace('\u201d', '"')
    result = result.replace('\u2018', ''').replace('\u2019', ''')

    # 4. 多余空格清理
    # 中文字符间的空格
    result = re.sub(r'([\u4e00-\u9fa5])\s+([\u4e00-\u9fa5])', r'\1\2', result)
    # 段首多余空格（保留2字符缩进）
    result = re.sub(r'^[ \t]{3,}', '  ', result, flags=re.MULTILINE)

    return result, logs
```

在 `postprocess_text()` 中新增段落均匀性打散（可选）：
- 检测连续段落长度方差，若过于均匀则合并/拆分部分段落
- 删除 AI 倾向的编号列表结构

**涉及文件**：
- `backend/app/services/prompt_evolution/novel_rules.py` — 新增 `_strip_ai_formatting()` 并集成到预处理流程
- `backend/app/services/ai_trace_competition.py` — 自动继承（调用 `preprocess_text`）

**预计效果**：格式清洗属于确定性规则，无需 LLM 参与，零成本即可在预处理阶段消除一类 AI 信号。

---

## 模型白名单

| 模型ID | 名称 | 提供商 | 质量评分 | 预估延迟 |
|--------|------|--------|----------|----------|
| qwen3.7-plus | Qwen3.7 Plus | Alibaba | 9.2 | 1.6s |
| deepseek-v4-flash | DeepSeek V4 Flash | DeepSeek | 8.5 | 2.0s |
| doubao-seed-character | Doubao Seed Character | Volcengine | 8.8 | 1.5s |
| kimi/kimi-k2.6 | Kimi K2.6 | Moonshot | 8.9 | 2.0s |
| glm-5.2 | GLM-5.2 | Zhipu | 9.1 | 2.5s |
| MiniMax/MiniMax-M3 | MiniMax M3 | MiniMax | 9.0 | 2.2s |
| mimo-v2.5 | MiMo V2.5 | Xiaomi | 9.0 | 1.5s |
| doubao-seed-evolving | Doubao Seed Evolving | Volcengine | 9.3 | 2.5s |
| step-3.7-flash | Step 3.7 Flash | StepFun | 8.8 | 1.2s |

## 并发控制与成本保护

- 模型并发上限 5（asyncio.Semaphore），防止瞬时 API 压力
- 腾讯云 AI 检测并发上限 3，避免触发限流
- 单模型超时 120 秒，超时静默跳过
- 全模型评测预计耗时：30-60 秒（9 模型并发，受限于最慢模型）
- 评测频率：每次进化迭代一次（非每次用户请求）

## 数据存储结构

```
data/prompt_evolution/
├── model_config.json          # 管理员选定模型 + 自动最优模型
├── model_performance.json     # 各模型历史表现数据
├── model_prompt_performance.json # 题材×提示词版本×模型联合表现
├── model_evaluation_details.json # 追加式模型评测事实与审计数据
├── background_optimization_state.json # 全局后台任务、冷却和每日预算
├── evolution_history.json     # 进化历史
├── best_prompts.json          # 最佳提示词
├── approved_prompts.json      # 已批准提示词
├── experience_reports/        # 经验报告目录
├── optimized_experiences.json # 优化后经验
└── optimization_metadata.json # 优化元数据
```

## 实施顺序

1. ~~新建多模型评估服务 `ai_trace_competition.py`~~ ✅ 已完成
2. ~~修改 `/reduce` 使用活跃模型 + 新增 `/model-config`、`/evaluate-models` 端点~~ ✅ 已完成
3. ~~简化前端用户端 UI~~ ✅ 已完成
4. ~~修改 `evaluator.py` 支持 `model_id` 参数~~ ✅ 已完成
5. ~~**P0**：进化引擎集成多模型评估~~ ✅ 已完成
6. **P1**：前端管理页增加模型管理面板 ← 下一步
7. **P2**：管理员自定义测试样本
8. **P3**：进化状态持久化
9. **P4**：~~AI输出格式特征清洗~~ ✅ 已完成
