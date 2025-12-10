# 📚 历史经验智能去重与优化系统

## 概述

为了解决176条历史经验中存在的**语义重复**和**质量参差不齐**问题，实现了一套智能经验优化系统，通过LLM语义去重、质量过滤、效果排序等手段，将经验库压缩到30-40条高质量核心经验。

## 核心功能

### 1. 语义去重 🔍

**问题**：简单字符串匹配无法识别语义重复
- ❌ "用身体反应替代情感陈述" 
- ❌ "用具体身体动作展示情感"
- → 实际上是同一条经验

**解决方案**：使用LLM识别并合并语义相似的条目
```python
# LLM分析相似度，合并为：
"用身体反应/具体动作替代直接情感陈述（如'喉咙发紧'替代'感到悲伤'）"
```

### 2. 质量过滤 🧹

**移除规则**：
1. 仅出现1次且过于模糊的经验
2. 过于简短（<5个字）且无实质内容
3. 包含明显错误或矛盾的经验
4. 负面表述误入有效策略

### 3. 效果排序 📈

**排序依据**：
- 出现次数（频率越高优先级越高）
- 最近使用时间（越新越优先）
- 文本质量（有示例的优先）
- 详细程度（更详细的优先）

### 4. 自动触发机制 ⚡

**触发条件**（二选一）：
- ✅ 每积累 **20个** 新经验报告时
- ✅ 总报告数 > **40个** 且从未优化过

**触发时机**：
- 每次进化开始前自动检测
- 支持手动触发（通过API）

## 技术架构

### 文件结构

```
backend/app/services/prompt_evolution/
├── experience_optimizer.py      # 🆕 经验优化器（639行）
├── storage.py                   # 增强：优化经验存储
├── meta_optimizer.py            # 增强：优先加载优化经验
├── engine.py                    # 增强：自动触发优化
└── novel_rules.py              # 预置经验规则
```

### 核心类

#### ExperienceItem
```python
@dataclass
class ExperienceItem:
    text: str                       # 经验文本
    category: str                   # 类别
    appearance_count: int = 1       # 出现次数
    source_reports: List[str]       # 来源报告
    first_seen: Optional[str]       # 首次出现
    last_seen: Optional[str]        # 最近出现
    avg_score_improvement: float    # 🎯 平均降分效果
    success_rate: float             # 🎯 成功率
```

#### ExperienceOptimizer
```python
class ExperienceOptimizer:
    async def optimize_experiences(
        all_reports: List[Dict],
        genre: Optional[str] = None
    ) -> OptimizationResult:
        """
        智能优化流程：
        1. 提取并统计所有经验
        2. 语义去重（每个类别独立）
        3. 质量过滤（移除低质量）
        4. 效果排序（保留TOP N）
        5. 生成优化摘要
        """
```

## 使用方式

### 1. 自动触发（推荐）

系统会在进化开始前自动检测并触发优化：

```python
# engine.py - run_evolution()
if optimizer.should_trigger_optimization(total_reports, last_opt_count):
    opt_result = await optimizer.optimize_experiences(historical_reports, genre)
    storage.save_optimized_experiences(optimized_exps)
    storage.update_optimization_metadata(total_reports)
```

**日志输出示例**：
```
🔧 触发经验优化：当前 92 个报告，上次优化 50 个
🔧 开始优化历史经验...
📊 步骤1: 提取并统计经验...
   提取到 176 条经验（有效:82, 无效:45, 禁止:35, 最佳:14）
🔍 步骤2: 语义去重...
   处理类别: effective (82条)
   ✅ effective: 82 -> 42 (合并了12组)
🧹 步骤3: 质量过滤...
   移除低质量经验 23 条
📈 步骤4: 效果排序...
   effective: 保留TOP 15/42
✅ 优化完成: 176 -> 38 条核心经验
```

### 2. 手动触发

通过API手动触发优化：

```bash
# 查看优化状态
GET /api/v1/prompt-evolution/optimization-status

# 手动触发优化
POST /api/v1/prompt-evolution/optimize-experiences
{
  "genre": "玄幻",  # 可选：题材过滤
  "force": false    # 可选：强制优化
}
```

**响应示例**：
```json
{
  "success": true,
  "original_count": 176,
  "optimized_count": 38,
  "merged_groups_count": 12,
  "removed_count": 23,
  "summary": "========== 优化报告 ==========\n...",
  "message": "经验优化成功"
}
```

### 3. 优先加载优化经验

`meta_optimizer.py` 在加载历史经验时会优先使用优化后的版本：

```python
def load_historical_experience():
    # 1. 尝试加载优化经验
    optimized_data = storage.load_optimized_experiences()
    if optimized_data:
        logger.info("🎯 检测到优化经验，优先使用")
        # 使用优化后的38条核心经验
        return loaded_count
    
    # 2. 如果没有，使用原始176条
    logger.info("📚 未找到优化经验，使用原始报告")
```

## 优化效果

### 压缩比例

| 指标 | 优化前 | 优化后 | 压缩比 |
|------|--------|--------|--------|
| 总经验数 | 176条 | 30-40条 | ~22% |
| 有效策略 | 82条 | 15条 | 18% |
| 无效策略 | 45条 | 15条 | 33% |
| 禁止模式 | 35条 | 10条 | 29% |
| 最佳实践 | 14条 | 10条 | 71% |

### 质量提升

✅ **消除语义重复**：12组相似经验合并为1条
✅ **移除低质量**：23条模糊/错误经验被删除
✅ **效果优先**：按出现频率和效果排序
✅ **保留精华**：只保留高频、高效、详细的核心经验

## 数据存储

### optimized_experiences.json
```json
{
  "optimized_at": "2025-12-10T14:30:00",
  "total_count": 38,
  "version": "1.0",
  "experiences": [
    {
      "text": "用身体反应/具体动作替代直接情感陈述（如'喉咙发紧'替代'感到悲伤'）",
      "category": "effective",
      "appearance_count": 15,
      "source_reports": ["abc123", "def456", ...],
      "first_seen": "2025-11-01T10:00:00",
      "last_seen": "2025-12-10T12:00:00",
      "avg_score_improvement": 12.5,
      "success_rate": 0.85
    },
    ...
  ]
}
```

### optimization_metadata.json
```json
{
  "last_optimization_count": 92,
  "optimized_at": "2025-12-10T14:30:00"
}
```

## API接口

### GET /api/v1/prompt-evolution/optimization-status

获取优化状态

**响应**：
```json
{
  "total_reports": 92,
  "last_optimization_count": 50,
  "new_reports_since_last": 42,
  "optimized_at": "2025-12-10T10:00:00",
  "has_optimized_data": true,
  "optimized_experience_count": 38,
  "should_optimize": true,
  "optimization_trigger_threshold": "增加>=20个报告 或 总数>40"
}
```

### POST /api/v1/prompt-evolution/optimize-experiences

手动触发优化

**请求**：
```json
{
  "genre": "玄幻",  // 可选
  "force": false    // 强制优化
}
```

**响应**：
```json
{
  "success": true,
  "original_count": 176,
  "optimized_count": 38,
  "merged_groups_count": 12,
  "removed_count": 23,
  "summary": "详细优化报告...",
  "message": "经验优化成功"
}
```

## 配置参数

在 `ExperienceOptimizer` 类中可调整：

```python
# 语义相似度阈值
self.similarity_threshold = 0.85

# 最小出现次数
self.min_appearance_count = 2

# 每类保留TOP数量
self.top_n_per_category = 15

# 清理规则
self.remove_if_appearance_lt = 1
self.remove_if_too_vague = True
```

## 监控与维护

### 日志级别

- `INFO`: 优化开始、完成、各步骤进度
- `WARNING`: LLM去重失败、加载经验项失败
- `ERROR`: 优化过程异常

### 关键指标

监控以下指标以判断优化质量：

1. **压缩比**：目标 20-30%
2. **合并组数**：语义去重效果
3. **移除数量**：质量过滤效果
4. **高频经验**：TOP5应该是真正有效的策略

## 最佳实践

### 1. 定期检查优化状态

```bash
# 每周检查一次
GET /api/v1/prompt-evolution/optimization-status
```

### 2. 手动审查优化结果

查看优化摘要中的：
- 合并的组：确认语义确实相似
- 移除的经验：确认确实是低质量
- TOP5高频经验：确认是核心策略

### 3. 题材定制优化

针对特定题材优化：
```json
{
  "genre": "玄幻",
  "force": true
}
```

### 4. 备份重要经验

在大规模优化前，可导出原始经验报告备份。

## 未来扩展

### 计划中的功能

1. **效果追踪增强**
   - 记录每条经验的实际降分效果
   - 基于效果自动淘汰无效策略

2. **智能合并建议**
   - LLM不仅去重，还能改进表述
   - 自动添加示例和使用技巧

3. **分层经验库**
   - 核心经验（必用）
   - 高级经验（可选）
   - 实验性经验（待验证）

4. **经验版本管理**
   - 保留优化历史
   - 支持回滚到之前版本

## 问题排查

### 优化失败

**症状**：API返回500错误
**排查**：
1. 查看日志中的异常堆栈
2. 检查LLM API调用是否正常
3. 确认经验报告格式正确

### 优化效果不佳

**症状**：压缩比过低（>50%）或过高（<10%）
**排查**：
1. 调整 `similarity_threshold`
2. 检查 `top_n_per_category` 设置
3. 查看LLM去重的实际输出

### 加载优化经验失败

**症状**：仍在使用176条原始经验
**排查**：
1. 确认 `optimized_experiences.json` 存在
2. 检查文件格式是否正确
3. 查看加载日志中的错误信息

---

**最后更新**: 2025-12-10
**版本**: 1.0
