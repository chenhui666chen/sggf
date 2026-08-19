# 人物弧光锚点系统设计定案（ARC-ANCHOR）

日期：2026-08-18
状态：**定案**（语义与接口契约已冻结，实现按分期推进）
关联文档：`STORY_EXPANSION_QUALITY_DILUTION_RISKS_AND_FIXES_20260817.md`（结构债管线）

---

## 1. 背景与目标

协同扩展的 epic 框架第二阶段已产出 `character_lifecycle`（人物生命周期文本），但它嵌在框架
Markdown 中，机器不可校验、无法检测缺口、无法注入生成约束——"写了没人看"。

弧光锚点系统将其升级为**结构化、可校验、可注入**的数据：

- 规划期自动报告人物成长线缺口（断裂/空窗/跳变/烂尾）
- 缺口转为生成约束注入扩展管线（复用结构债通道）
- 生成后回看校验人物状态与目标弧光的一致性

**核心哲学**（与 Shot Contract 一致）：锚点是**规划约束**，不是生成结果——先有目标弧光再
生成章节，生成结果只做校验回看。设计期编译、运行期校验。

## 2. 锚点 Schema（冻结）

```json
{
  "character_id": 12,
  "tier": "S",                       // 人物分层，见 §4
  "storyline_id": "main",            // 叙事线作用域，见 §6.2
  "anchor_type": "progression",      // 见 §3 状态语义
  "stage": "信任建立期",              // 成长阶段名（自由文本）
  "chapter_range": [8, 22],          // 章节区间（闭区间，机器校验核心）
  "terminal": false,
  "exit_reason": null,               // terminal 时的退场原因：死亡/退场/离队
  "time_skip": false,                // 区间内含时间跳跃（豁免跳变检测），见 §6.3
  "dimensions": {                    // 成长维度，按题材配置，见 §7
    "capability": 3,
    "emotional_maturity": 2
  },
  "key_turning_event": "第15章雨夜互救",
  "relationship_refs": [],           // 关系锚点线引用（关系不内嵌），见 §8
  "exit_hook_ref": "FS-007",         // 必须命中伏笔表编号，双向外键校验
  "acknowledged_gaps": []            // 认定的有意留白区间，复用 deferred 状态机，见 §9
}
```

数量约束：S 层 4-10 锚点/人，A 层 3-6，B 层仅 terminal/legacy + 登场区间，C 层不参与。

## 3. 状态语义（anchor_type，冻结）

| anchor_type | 语义 | 对检测的影响 |
|---|---|---|
| `progression` | 常规成长阶段 | gap 检测正常作用 |
| `terminal` | 死亡/退场/离场，`exit_reason` 必填 | 该人物 gap 检测**硬终止** |
| `legacy` | 死后遗产锚点（遗言/遗物/影响力演变） | 不算出场，算**因果覆盖** |
| `off_screen_progression` | 幕后推进（反派暗中升级等） | 无出场但有状态推进，豁免空窗检测 |
| `revival_hook` | 复活预留锚点 | terminal 若被伏笔表复活伏笔引用则降级为软终止 |

**闪回状态冻结**：死亡后人物在倒叙/回忆/梦境中合法出场，但约束为"状态冻结"——闪回中的
`dimensions` 与 `emotional_baseline` 不得产生新推进（校验项，非禁止出场）。

**死亡≠消失的误报防护**：无 terminal 锚点的人物在第 N 章死亡后，N+1 至末章不得报成长线
断裂——这是系统最大面积的误报源，terminal 语义必须先于 gap 检测实现。

## 4. 人物分层（tier，接口契约）

| tier | 标准 | 锚点义务 |
|---|---|---|
| S（主角） | 1-2 人 | 完整锚点 + dimensions 轨迹 + 关系线 |
| A（核心配角） | 4-8 人 | 锚点 3-6 |
| B（功能性配角） | 有独立功能但无成长弧 | terminal/legacy + 登场区间 |
| C（工具人） | **delete_test 不通过**：删掉该人物主线不受损 | `arc_exempt=true`，不参与检测 |

- tier 由 L1 编译时 LLM 顺带判定（含 delete_test 判定），S/A 层建议人工抽查。
- tier 存储于人物卡（`characters.genre_fields_json` 或独立列，一期实现时定）。
- **对去重的验收约束**（去重方案的交付边界，不含执行方法）：
  - 同名/别名人物必须已合并为单卡，每卡 tier 非空；
  - 未满足时 L1 降级行为：只编译 S/A 层、B/C 层跳过并告警，不整体禁用。
- 防复发（管道侧）已于 2026-08-18 完成：epic 重建自动归档 `source='expansion'` 的孤立卡。

## 5. 四层架构

```
L1 编译层   人物卡 + character_lifecycle + 大纲 → LLM 结构化抽取 → arc_anchors
           （lifecycle 已有结构化字段确定性解析，LLM 只补语义字段）
L2 校验层   纯确定性代码（无 LLM），五类缺口 + 密度预算 → arc_gap_report
L3 注入层   缺口报告 → arc_constraints，与 structural_debt 并列注入生成 prompt
L4 反馈层   对齐闸门新增 arc 一致性检查项 → 命中进 plot_level_issues → 结构债通道
```

- 存储：`project_settings` 新 key `arc_anchors`（沿用 epic 框架存储模式，不建新表）。
- 失效：人物卡 upsert 后自动失效重编译（挂现有同步钩子）。

## 6. 作用域切分（防误报的关键）

### 6.1 篇幅分档（所有阈值参数化，禁止写死）

```
gap_threshold          = max(8, total_chapters * 0.08)    # 成长线断裂判定
S 层锚点数下限          = clamp(total_chapters / 60, 3, 10)
卷级锚点密度            = 长篇(≥6卷)每卷≥1；短篇(<60章)按幕
```

短篇与长篇的**轴心不同**：短篇人物弧光单线（一个转变），长篇多阶段演进。L1 抽取 prompt
按篇幅分档。

### 6.2 叙事线作用域

锚点挂 `storyline_id`；gap/空窗检测按线作用域执行，B 线人物在 A 线章节不算空窗。

### 6.3 时间跳跃

`time_skip=true` 区间豁免 gap 检测与 dimensions 跳变检测（"三年后"式合法暴涨）。

### 6.4 考古/规划双模式（与 lock_existing_chapters 互斥语义）

- **考古模式**（已写章节）：extract only——从正文反推状态，产出基线锚点，不注入约束。
- **规划模式**（未写章节）：constrain + 检测。
- **边界锚点**：最后已写章节处必须有"当前状态"锚点，作为规划起点。禁止对已写章节产出
  与正文矛盾的目标约束。

## 7. dimensions 量纲（按题材配置）

不硬编码 capability。从现有 `get_genre_character_fields` 的题材字段推导：

- 男频战力：capability / status
- 言情：emotional_maturity / relationship_stage
- 职场：social_position / resource_control
- 悬疑：cognition_level / information_tier

schema 中 `dimensions` 键名随题材注册，跳变检测对值生效（涨幅 >3 且无 turning_event 判跳变）。

## 8. 关系弧线（独立线，不内嵌）

`relationship_delta` 不塞在人物锚点内（双主角关系会两边重复/冲突）。关系演变独立为
**关系锚点线**（引用两个人物 id），人物锚点只管个体状态，`relationship_refs` 引用关系线。

## 9. acknowledged_gap（误报复防）

L2 误报一旦注入比没有约束更糟。`acknowledged_gap` 机制：作者/规划器确认"有意留白"
（如神秘人身份悬念期）后记录区间+理由，后续轮次不再重复上报。状态语义复用结构债的
deferred 模式（同一状态机，不同 debt 类型字段）。

## 10. L2 检测规则（纯确定性代码）

| 规则 | 判定 | 优先级 |
|---|---|---|
| R1 成长线断裂 | 相邻锚点 gap > gap_threshold（terminal/legacy 之后不检测） | P0 |
| R2 空窗人物 | S/A 层人物在目标扩展区间内 0 锚点覆盖（off_screen 豁免） | P0 |
| R3 空白章节 | 目标区间内无任何锚点覆盖的工具人章节段 | P1 |
| R4 维度跳变 | dimensions 相邻锚点涨幅 >3 且无 turning_event（time_skip 豁免） | P1 |
| R5 弧光烂尾 | 有 stage 无对应收束锚点（黑化期无落点等） | P1 |
| R6 密度预算 | 任意 5 章窗口内 key_turning_event >2 | P2 |
| R7 伏笔交叉 | exit_hook_ref 必须存在于伏笔表；伏笔回收章附近应有对应锚点 | P2 |

## 11. 分期计划

| 期 | 内容 | 状态 |
|---|---|---|
| 第 0 期（前置） | 防复发：epic 重建归档孤立扩展卡（source/archived_at） | ✅ 2026-08-18 完成，单测 4/4 |
| 一期 | L1 抽取（含 tier 判定）+ L2 的 R1/R2 + L3 注入 + 篇幅参数化 | 待启动 |
| 二期 | L4 闸门项 + R4/R5/R7 + acknowledged_gap 状态机 | |
| 三期 | 前端人物成长线时间轴可视化（章节轴×人物泳道，缺口标红） | |

## 12. 关键设计决策记录

1. 锚点是规划约束非生成结果（先弧光后章节）。
2. terminal 语义先于 gap 检测（否则死亡人物全报断裂）。
3. 阈值全部相对量化（篇幅 × 系数），禁止绝对常量。
4. dimensions 按题材注册，不硬编码战力轴。
5. 关系线独立，不内嵌人物锚点。
6. 已写章节只考古不约束，边界锚点衔接规划。
7. 存量去重不作为前置（测试数据可抛弃），但去重交付物须满足 §4 验收约束。
8. 校准场：项目 102（7 卷 / 300-500 章规划 / 60 张已打标卡）——先测 L1 对脏数据鲁棒性
   再决定是否粗清。

## 13. 主要风险

- **锚点粒度**：太粗检不出缺口，太细抽取不稳定。S 层 4-10 起步，用 102 校准。
- **L1 抽取稳定性**：同文本两次抽取粒度不同。缓解：确定性字段直接解析，LLM 只补语义。
- **误报淹没**：L2 首版必须保守（只出 R1/R2），acknowledged_gap 先于 R3-R7 落地。
