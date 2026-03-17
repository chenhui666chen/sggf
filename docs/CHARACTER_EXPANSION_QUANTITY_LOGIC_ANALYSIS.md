# 人物拓展数量逻辑分析

## 📊 当前逻辑概述

人物拓展采用**一次性全量扩展**的策略，而不是真正的渐进式扩展。

## 🔍 详细分析

### 1. 调用入口（workflow.py）

**代码位置：** `backend/app/api/v1/workflow.py:5940`

```python
# 🔥 计算实际需要新增的人物数
increment = target_total_characters - current_character_count

# 例如：
# current_character_count = 5
# target_total_characters = 20
# increment = 20 - 5 = 15  ← 一次性扩展15个人物
```

**关键问题：**
- `increment` 是**一次性计算**的，等于目标人物数减去当前人物数
- 不是每次扩展固定数量（如5个），而是**直接扩展到目标数量**

### 2. 扩展执行（outline_expander.py）

**代码位置：** `backend/app/services/agents/outline_expander.py:1123-1598`

```python
def expand_characters_incremental(
    self,
    main_characters: str,
    world_setting: str,
    plot_outline: str,
    current_character_count: int,
    increment: int = 5,  # ← 默认值5，但实际传入的是全量差值
    target_total_characters: Optional[int] = None
) -> Dict[str, Any]:
    """渐进式扩展人物体系"""

    # 实际执行：
    target_count = current_character_count + increment
    # 例如：5 + 15 = 20，一次性扩展到20个
```

**关键问题：**
- 方法名叫 `expand_characters_incremental`（渐进式）
- 但实际执行是**一次性扩展**到目标数量
- `increment` 参数虽然默认是5，但调用时传入的是全量差值

### 3. AI判断逻辑

**代码位置：** `outline_expander.py:1501-1530`

```python
# 🆕 长篇小说目标人物数量（用于判断是否继续扩展）
character_target = target_total_characters or 25
lower_threshold = max(15, character_target - 10)
upper_threshold = character_target + 5

# 例如：target_total_characters = 20
# character_target = 20
# lower_threshold = max(15, 20-10) = 15
# upper_threshold = 20 + 5 = 25

# AI判断标准：
# - 如果当前人物数 < 15，建议继续扩展
# - 如果 15-20 个，根据角色分布判断
# - 如果 20-25 个，偏向收束
# - 如果 > 25 个，需要充分理由才继续
```

**关键问题：**
- AI判断是在**扩展完成后**执行的
- 判断结果 `should_continue` 返回给前端，但**当前扩展已经完成**
- 这个判断实际上是为**下一轮扩展**准备的

### 4. 实际执行流程

```
用户输入：
├─ 当前人物数：5个
├─ 目标人物数：20个
└─ 期望：渐进式扩展（每次5个）

实际执行：
├─ 计算 increment = 20 - 5 = 15
├─ 调用 expand_characters_incremental(increment=15)
├─ 一次性扩展15个人物（5 → 20）
├─ AI判断：should_continue = false（因为已达到目标）
└─ 返回结果

结果：
✅ 目标达成（20个人物）
❌ 不是渐进式（一次性完成）
```

## 🔴 存在的问题

### 问题1：名不副实

**问题描述：**
- 方法名叫 `expand_characters_incremental`（渐进式）
- 实际执行是一次性扩展到目标数量
- 用户期望的"渐进式"没有实现

**影响：**
- 用户以为会分多次扩展，实际一次完成
- 无法在中途调整策略
- 扩展失败时损失较大

### 问题2：AI判断时机错误

**问题描述：**
- AI判断在扩展**完成后**执行
- 判断结果对**当前扩展**没有影响
- 只能影响**下一轮扩展**（但下一轮可能不存在）

**影响：**
- AI建议"停止扩展"时，扩展已经完成
- 无法根据AI判断动态调整扩展数量
- 浪费计算资源

### 问题3：缺少真正的渐进控制

**问题描述：**
- 没有循环调用机制
- 没有中途验证和调整
- 一次性扩展可能导致质量下降

**影响：**
- 扩展数量过大时（如15个），质量难以保证
- 无法根据中间结果调整策略
- 用户无法干预扩展过程

### 问题4：阈值设计不合理

**当前阈值：**
```python
character_target = target_total_characters or 25
lower_threshold = max(15, character_target - 10)
upper_threshold = character_target + 5
```

**问题：**
- 阈值是基于**目标数量**计算的，不是基于**当前数量**
- 例如：目标20个，阈值15-25，但当前只有5个
- AI判断时已经扩展到20个，判断意义不大

## 💡 改进方案

### 方案A：真正的渐进式扩展（推荐）

```python
async def expand_characters_progressive(
    project_id: int,
    current_character_count: int,
    target_total_characters: int,
    step_size: int = 5,  # 每次扩展5个
    max_iterations: int = 10  # 最多10轮
):
    """真正的渐进式扩展"""

    iteration = 0
    current_count = current_character_count

    while current_count < target_total_characters and iteration < max_iterations:
        iteration += 1

        # 计算本轮扩展数量
        remaining = target_total_characters - current_count
        increment = min(step_size, remaining)

        logger.info(f"🔄 第{iteration}轮扩展：{current_count} → {current_count + increment}")

        # 执行扩展
        result = await asyncio.to_thread(
            expander.expand_characters_incremental,
            main_characters=current_characters,
            world_setting=world_setting,
            plot_outline=plot_outline,
            current_character_count=current_count,
            increment=increment,
            target_total_characters=target_total_characters
        )

        # 更新当前状态
        current_count = result['current_character_count']
        current_characters = result['all_characters']

        # 🔥 关键：根据AI判断决定是否继续
        if not result.get('should_continue', True):
            logger.info(f"✅ AI建议停止扩展：{result.get('continue_reason')}")
            break

        # 🔥 关键：根据匹配度决定是否继续
        validation_score = result.get('post_validation_score', 0)
        if validation_score < 60:
            logger.warning(f"⚠️ 匹配度过低({validation_score})，停止扩展")
            break

        # 🔥 关键：如果需要优化，先优化再继续
        if result.get('should_optimize_first', False):
            logger.info("⚠️ 需要先优化现有人物，暂停扩展")
            break

        # 发送进度
        progress = int(50 + (current_count / target_total_characters) * 50)
        await ws_manager.send_task_progress(
            project_id=project_id,
            task_id=task_id,
            progress=progress,
            message=f"已扩展到 {current_count}/{target_total_characters} 个人物"
        )

    return {
        "final_character_count": current_count,
        "iterations": iteration,
        "reached_target": current_count >= target_total_characters
    }
```

**优势：**
- 真正的渐进式扩展（每次5个）
- 每轮后验证和判断
- 可以根据AI建议和匹配度动态调整
- 用户可以看到实时进度

### 方案B：智能步长调整

```python
def calculate_smart_increment(
    current_count: int,
    target_count: int,
    validation_score: int
) -> int:
    """根据当前状态智能计算扩展步长"""

    remaining = target_count - current_count

    # 如果匹配度高，可以大步扩展
    if validation_score >= 80:
        return min(10, remaining)

    # 如果匹配度中等，中等步长
    elif validation_score >= 60:
        return min(5, remaining)

    # 如果匹配度低，小步扩展
    else:
        return min(3, remaining)
```

### 方案C：分阶段扩展

```python
def expand_characters_staged(
    current_count: int,
    target_count: int
):
    """分阶段扩展人物"""

    # 第一阶段：核心人物（主角、主要对手、导师）
    stage1_target = min(current_count + 5, target_count)

    # 第二阶段：重要配角（盟友、次要对手）
    stage2_target = min(stage1_target + 5, target_count)

    # 第三阶段：次要角色（支持角色、中立角色）
    stage3_target = target_count

    return [
        {"stage": 1, "target": stage1_target, "focus": "核心人物"},
        {"stage": 2, "target": stage2_target, "focus": "重要配角"},
        {"stage": 3, "target": stage3_target, "focus": "次要角色"}
    ]
```

## 📋 具体改进建议

### 1. 立即改进（最小改动）

**修改 workflow.py 的调用逻辑：**

```python
# 当前代码（第5940行）：
increment = target_total_characters - current_character_count

# 改为：
MAX_INCREMENT_PER_ROUND = 5  # 每次最多扩展5个
increment = min(MAX_INCREMENT_PER_ROUND, target_total_characters - current_character_count)

# 添加循环调用
while current_character_count < target_total_characters:
    increment = min(MAX_INCREMENT_PER_ROUND, target_total_characters - current_character_count)

    result = await asyncio.to_thread(
        expander.expand_characters_incremental,
        main_characters=main_characters,
        world_setting=combined_world_setting,
        plot_outline=plot_outline,
        current_character_count=current_character_count,
        increment=increment,
        target_total_characters=target_total_characters
    )

    # 更新状态
    current_character_count = result['current_character_count']
    main_characters = result['all_characters']

    # 根据AI判断决定是否继续
    if not result.get('should_continue', True):
        break

    # 根据匹配度决定是否继续
    if result.get('post_validation_score', 0) < 60:
        break
```

### 2. 中期改进（重构）

**创建独立的渐进式扩展控制器：**

```python
class ProgressiveExpansionController:
    """渐进式扩展控制器"""

    def __init__(self, step_size: int = 5, max_iterations: int = 10):
        self.step_size = step_size
        self.max_iterations = max_iterations

    async def expand_to_target(
        self,
        expander: OutlineExpander,
        current_count: int,
        target_count: int,
        **kwargs
    ):
        """渐进式扩展到目标数量"""
        # 实现真正的渐进式扩展逻辑
        pass
```

### 3. 长期改进（架构优化）

**引入状态机模式：**

```python
class ExpansionState(Enum):
    INITIAL = "initial"
    EXPANDING = "expanding"
    VALIDATING = "validating"
    OPTIMIZING = "optimizing"
    COMPLETED = "completed"
    FAILED = "failed"

class ExpansionStateMachine:
    """扩展状态机"""

    def transition(self, event: str):
        """状态转换"""
        pass
```

## 📊 对比总结

| 维度 | 当前实现 | 改进后 |
|------|---------|--------|
| 扩展方式 | 一次性全量 | 真正渐进式 |
| 步长控制 | 无（全量） | 每次3-10个 |
| 中途验证 | 仅最后验证 | 每轮验证 |
| 动态调整 | 不支持 | 支持 |
| AI判断时机 | 扩展后 | 每轮后 |
| 失败恢复 | 全部重来 | 保留已扩展部分 |
| 用户干预 | 不支持 | 支持暂停/继续 |
| 质量保证 | 依赖一次性质量 | 逐步验证质量 |

## 🎯 推荐实施路径

1. **第一步（本周）**：修改 workflow.py，添加循环调用，限制每次扩展数量为5个
2. **第二步（下周）**：在每轮扩展后添加验证和判断逻辑
3. **第三步（下下周）**：实现智能步长调整和分阶段扩展
4. **第四步（未来）**：引入状态机模式，支持暂停/恢复/回滚

## 💬 总结

当前的"渐进式扩展"实际上是**一次性扩展**，存在以下核心问题：

1. **名不副实**：方法名叫渐进式，实际是一次性
2. **判断时机错误**：AI判断在扩展后，无法影响当前扩展
3. **缺少真正的渐进控制**：没有循环、没有中途验证
4. **阈值设计不合理**：基于目标数量而非当前数量

建议优先实施**方案A（真正的渐进式扩展）**，通过循环调用、每轮验证、动态调整来实现真正的渐进式扩展。
