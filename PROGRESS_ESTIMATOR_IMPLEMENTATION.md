# 基于时间预估的进度条平滑更新机制 - 实现文档

## 📋 需求概述

实现一个智能的进度条系统，解决以下问题：
1. ❌ 进度更新非线性（不均匀）
2. ❌ 某些阶段不发送进度更新
3. ❌ 进度条长时间卡住，用户体验差

## ✅ 实现方案

### 1. 后端 API - 阶段耗时统计

**文件**: `backend/app/api/v1/statistics.py`

#### 端点 1: 获取平均耗时
```
GET /api/v1/statistics/workflow/stage-durations
```

**功能**:
- 查询 `generation_history` 表，统计每个阶段的平均耗时
- 使用 SQLite 的 `julianday()` 函数计算时间差（秒）
- 支持按项目ID过滤，或统计当前用户所有项目
- 如果没有历史数据，返回默认值

**响应示例**:
```json
{
  "concept": 120.5,
  "structure": 90.3,
  "content": 180.7,
  "review": 60.2,
  "iteration": 75.8
}
```

#### 端点 2: 获取详细统计
```
GET /api/v1/statistics/workflow/stage-durations/detailed
```

**功能**:
- 返回每个阶段的平均值、最小值、最大值、样本数量

**响应示例**:
```json
{
  "concept": {
    "avg": 120.5,
    "min": 80.0,
    "max": 200.0,
    "count": 10
  },
  ...
}
```

---

### 2. 前端进度估算器

**文件**: `frontend/src/utils/progressEstimator.ts`

#### 核心类: `ProgressEstimator`

**功能**:
- 基于历史平均耗时启动定时器
- 使用 `requestAnimationFrame` 实现平滑动画
- 融合预估进度和真实进度
- 防止进度条倒退
- 超时减缓策略（渐近95%）

**关键方法**:

1. **`startStage(stage, onProgressUpdate)`**
   - 开始一个新阶段的进度估算
   - 启动动画循环

2. **`updateRealProgress(progress)`**
   - 更新来自后端的真实进度
   - 自动融合预估进度和真实进度

3. **`complete()`**
   - 立即跳到 100%
   - 停止动画循环

4. **`stop()`**
   - 停止进度估算

**进度融合算法**:
```typescript
if (realProgress >= estimatedProgress) {
  displayProgress = realProgress  // 真实进度更快，直接使用
} else {
  // 真实进度较慢，加权平均（真实70%，预估30%）
  displayProgress = realProgress * 0.7 + estimatedProgress * 0.3
}
```

**超时减缓策略**:
```typescript
if (elapsedTime > estimatedDuration) {
  // 使用对数函数减缓进度增长，渐近95%
  const overtime = elapsedSeconds - estimatedDuration
  const slowdownFactor = Math.log(overtime + 1) / Math.log(10)
  estimatedProgress = Math.min(95, 90 + slowdownFactor * 5)
}
```

---

### 3. 前端服务层

**文件**: `frontend/src/services/statistics.ts`

**功能**:
- 封装统计 API 调用
- 错误处理和默认值回退

---

### 4. 前端集成

**文件**: `frontend/src/pages/WorkflowControlPage.tsx`

#### 新增状态变量:
```typescript
const [progressEstimator, setProgressEstimator] = useState<ProgressEstimator | null>(null)
const [stageDurations, setStageDurations] = useState<StageDurations | null>(null)
const [estimatedProgress, setEstimatedProgress] = useState(0)
const [estimatedRemainingTime, setEstimatedRemainingTime] = useState(0)
```

#### 初始化进度估算器:
```typescript
useEffect(() => {
  const durations = await statisticsService.getStageDurations(projectId)
  const estimator = new ProgressEstimator(durations)
  setProgressEstimator(estimator)
}, [projectId])
```

#### 启动进度估算:
```typescript
// 在 executeStageAsync() 中
if (progressEstimator) {
  progressEstimator.startStage(stage, (state: ProgressState) => {
    setEstimatedProgress(Math.round(state.displayProgress))
    setEstimatedRemainingTime(Math.round(state.remainingTime))
    setTaskProgress(Math.round(state.displayProgress))
  })
}
```

#### 更新真实进度:
```typescript
// 在 WebSocket onTaskProgress 监听器中
if (progressEstimator) {
  progressEstimator.updateRealProgress(data.progress)
}
```

#### 完成/停止进度估算:
```typescript
// 任务完成时
if (progressEstimator) {
  progressEstimator.complete()
}

// 任务错误时
if (progressEstimator) {
  progressEstimator.stop()
}
```

#### 总体进度计算:
```typescript
useEffect(() => {
  if (!stageDurations) return

  // 计算总预估时间
  const totalDuration = Object.values(stageDurations).reduce((sum, d) => sum + d, 0)

  // 计算已完成阶段的时间
  let completedDuration = 0
  stages.forEach((stage) => {
    if (workflow.stages[stage].status === 'completed') {
      completedDuration += stageDurations[stage]
    } else if (workflow.stages[stage].status === 'active') {
      completedDuration += (stageDurations[stage] * taskProgress) / 100
    }
  })

  // 计算总体进度
  const overallProgress = Math.round((completedDuration / totalDuration) * 100)
  dispatch({ type: 'workflow/updateOverallProgress', payload: overallProgress })
}, [stageDurations, workflow.stages, taskProgress])
```

---

## 🎯 预期效果

1. ✅ **平滑进度更新**: 即使后端不发送进度，前端进度条也会平滑前进
2. ✅ **预估剩余时间**: 显示 "预计剩余: XX秒"
3. ✅ **智能融合**: 真实进度优先，预估进度补充
4. ✅ **不会倒退**: 新进度 >= 当前进度
5. ✅ **超时处理**: 超过预估时间后减缓更新速度，不会停止
6. ✅ **加权总进度**: 基于各阶段预估时间权重计算总体进度

---

## 🧪 测试步骤

1. **启动后端**:
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **测试统计 API**:
   ```bash
   python test_statistics_api.py
   ```

3. **启动前端**:
   ```bash
   cd frontend
   npm run dev
   ```

4. **测试工作流**:
   - 打开浏览器，访问工作流控制页面
   - 点击"开始创作"
   - 观察进度条是否平滑更新
   - 观察是否显示预估剩余时间
   - 观察总体进度是否基于时间权重计算

---

## 📝 注意事项

1. **默认值**: 如果没有历史数据，使用默认耗时（concept: 120s, structure: 90s, content: 180s, review: 60s, iteration: 75s）
2. **动画性能**: 使用 `requestAnimationFrame` 确保流畅动画
3. **内存泄漏**: 组件卸载时确保停止进度估算器
4. **WebSocket 优先**: 优先使用 WebSocket 真实进度，预估进度作为补充

---

## 🆕 增强功能

### 功能 1: 自适应学习 ✅

**实现**: 基于最近3次任务动态调整预估时间

**后端 API 增强**:
- 添加 `recent_count` 参数到 `/api/v1/statistics/workflow/stage-durations`
- 使用 `ROW_NUMBER() OVER (PARTITION BY task_type ORDER BY completed_at DESC)` 获取最近N次任务
- 如果最近N次任务数据不足，自动回退到全局平均

**前端逻辑**:
```typescript
// 优先使用最近3次任务的平均耗时
let durations = await statisticsService.getStageDurations(projectId, 3)

// 检查是否有足够的数据
const hasEnoughData = Object.values(durations).every(d => d > 0)

if (!hasEnoughData) {
  // 回退到全局平均
  durations = await statisticsService.getStageDurations(projectId)
}
```

**日志输出**:
- `📊 使用自适应预估（最近3次任务）: {...}`
- `📊 使用全局平均耗时: {...}`
- `⚠️ 最近3次任务数据不足，回退到全局平均耗时`

**效果**:
- 如果用户最近的任务执行速度变快/变慢，进度条预估会自动适应
- 提高预估准确性，减少预估时间与实际时间的偏差

---

### 功能 2: 置信区间 ✅

**实现**: 显示预估时间范围（例如 "预计剩余: 30-60秒"）

**后端 API**:
- `/api/v1/statistics/workflow/stage-durations/detailed` 返回 `min` 和 `max` 字段

**前端增强**:
- `ProgressEstimator` 类添加 `remainingTimeMin` 和 `remainingTimeMax` 属性
- 构造函数接受 `StageDurationRanges` 参数
- 动态计算置信区间：
  ```typescript
  remainingTimeMin = (remainingProgress / 100) * minDuration
  remainingTimeMax = (remainingProgress / 100) * maxDuration
  ```

**UI 显示逻辑**:
```typescript
const timeDiff = estimatedRemainingTimeMax - estimatedRemainingTimeMin
const showRange = timeDiff >= 10  // 差距大于10秒才显示范围

if (showRange) {
  显示: "预计剩余: {最小值}-{最大值}秒"
} else {
  显示: "预计剩余: {平均值}秒"
}
```

**效果**:
- 用户可以看到预估时间的不确定性范围
- 提供更真实的预期，避免单一值可能带来的误导
- 例如显示 "预计剩余: 30-60秒" 比 "预计剩余: 45秒" 更准确

---

## 🔧 后续优化建议

1. ✅ **自适应学习**: 根据最近N次任务动态调整预估时间（已实现）
2. ✅ **置信区间**: 显示预估时间的置信区间（已实现）
3. **异常检测**: 如果实际耗时远超预估，发出警告
4. **用户反馈**: 允许用户手动调整预估时间

