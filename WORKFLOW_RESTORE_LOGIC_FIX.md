# 工作流恢复逻辑修复报告

**修复时间**: 2025-11-13  
**问题类型**: 工作流阶段恢复逻辑错误  
**严重程度**: 🔴 **高** - 导致前后端状态不一致

---

## 📋 问题描述

**用户反馈**: "工作流恢复的实现逻辑好像有问题，前端显示恢复到内容创作阶段，但后端好像并不是相应内容。"

**现象**:
- 前端显示: "正在执行 内容创作... (95%)"
- 后端日志: 不断轮询 `/api/v1/workflow/task/...`
- 实际情况: 没有正在运行的任务,但前端仍然显示运行中

---

## 🔍 根本原因分析

### 问题 1: localStorage 阶段恢复与后端状态不一致

**原有逻辑**:
```typescript
// ❌ 错误的逻辑
useEffect(() => {
  if (projectId) {
    // 从 localStorage 恢复阶段
    const savedStage = localStorage.getItem(`project_${projectId}_currentStage`)
    if (savedStage) {
      dispatch(setCurrentStage(savedStage as StageType))  // 设置为 "content"
    }
  }
}, [projectId])
```

**问题**:
1. localStorage 中保存的是 "content" (用户上次查看的阶段)
2. 但后端可能没有正在运行的任务 (任务已完成或失败)
3. 前端显示 "正在执行 内容创作",但实际上没有任务在运行
4. 导致前端不断轮询不存在的任务

---

### 问题 2: 没有清理运行状态

**原有逻辑**:
```typescript
// ❌ 错误的逻辑
if (runningTasks.length > 0) {
  // 恢复任务...
} else {
  console.log('✅ 没有正在运行的任务')
  // ⚠️ 但没有清理 isRunning 状态!
}
```

**问题**:
- 如果没有正在运行的任务,应该设置 `isRunning = false`
- 应该清理 `currentTaskId`
- 应该停止轮询定时器
- 但原有代码没有做这些清理

---

### 问题 3: Redux store 也从 localStorage 恢复

**原有逻辑**:
```typescript
// ❌ 错误的逻辑
const getInitialStage = (): StageType => {
  const savedStage = localStorage.getItem(`project_${projectId}_currentStage`)
  if (savedStage) {
    return savedStage as StageType  // 返回 "content"
  }
  return 'concept'
}

const initialState: WorkflowState = {
  currentStage: getInitialStage(),  // 从 localStorage 恢复
  // ...
}
```

**问题**:
- Redux store 初始化时就从 localStorage 恢复阶段
- 这个阶段可能与后端实际状态不一致
- 导致整个应用的状态都是错误的

---

## ✅ 修复方案

### 修复 1: 移除 localStorage 阶段恢复逻辑

**修改文件**: `frontend/src/pages/WorkflowControlPage.tsx`

**修改前**:
```typescript
useEffect(() => {
  if (projectId) {
    // 🆕 阶段持久化：先恢复阶段，再设置projectId
    const savedStage = localStorage.getItem(`project_${projectId}_currentStage`)
    if (savedStage) {
      dispatch(setCurrentStage(savedStage as StageType))
    }
    dispatch(setProjectId(Number(projectId)))
    dispatch(fetchProject(Number(projectId)))
  }
}, [projectId, dispatch])
```

**修改后**:
```typescript
useEffect(() => {
  if (projectId) {
    // 🔧 修复：不再从 localStorage 恢复阶段
    // 原因：localStorage 中的阶段可能与后端实际状态不一致
    // 改为从后端 API 获取实际的工作流状态
    
    dispatch(setProjectId(Number(projectId)))
    dispatch(fetchProject(Number(projectId)))
  }
}, [projectId, dispatch])
```

---

### 修复 2: 添加运行状态清理逻辑

**修改文件**: `frontend/src/pages/WorkflowControlPage.tsx`

**修改前**:
```typescript
if (runningTasks.length > 0) {
  // 恢复任务...
} else {
  console.log('✅ 没有正在运行的任务')
  // ⚠️ 没有清理状态
}
```

**修改后**:
```typescript
if (runningTasks.length > 0) {
  // 恢复任务...
} else {
  console.log('✅ 没有正在运行的任务')
  // 🔧 修复：如果没有正在运行的任务，确保停止运行状态
  setIsRunning(false)
  setCurrentTaskId(null)
  // 清理可能存在的轮询定时器
  if (taskPollingInterval) {
    clearInterval(taskPollingInterval)
    setTaskPollingInterval(null)
  }
}
```

---

### 修复 3: 根据后端状态确定当前阶段

**修改文件**: `frontend/src/pages/WorkflowControlPage.tsx`

**新增逻辑**:
```typescript
// 🔧 修复：根据后端状态确定当前应该显示的阶段
let lastCompletedStage: StageType | null = null
const stageOrder: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']

Object.entries(stageStatusMap).forEach(([dbField, stageName]) => {
  const status = statusData[dbField]
  if (status === 'completed') {
    dispatch(updateStageStatus({ stage: stageName, status: 'completed' }))
    lastCompletedStage = stageName
  }
})

// 如果没有正在运行的任务,设置当前阶段为最后完成的阶段的下一个阶段
if (!isRunning && !currentTaskId) {
  if (lastCompletedStage) {
    const lastCompletedIndex = stageOrder.indexOf(lastCompletedStage)
    if (lastCompletedIndex < stageOrder.length - 1) {
      // 还有未完成的阶段,显示下一个阶段
      const nextStage = stageOrder[lastCompletedIndex + 1]
      dispatch(setCurrentStage(nextStage))
    } else {
      // 所有阶段都完成了,显示最后一个阶段
      dispatch(setCurrentStage(lastCompletedStage))
    }
  } else {
    // 没有完成的阶段,显示第一个阶段
    dispatch(setCurrentStage('concept'))
  }
}
```

---

### 修复 4: 移除 Redux store 的 localStorage 恢复

**修改文件**: `frontend/src/store/slices/workflowSlice.ts`

**修改前**:
```typescript
const getInitialStage = (): StageType => {
  const savedStage = localStorage.getItem(`project_${projectId}_currentStage`)
  if (savedStage) {
    return savedStage as StageType
  }
  return 'concept'
}

const initialState: WorkflowState = {
  currentStage: getInitialStage(),
  // ...
}
```

**修改后**:
```typescript
const initialState: WorkflowState = {
  currentStage: 'concept',  // 默认为 concept,后续从后端 API 获取实际状态
  // ...
}
```

---

### 修复 5: 禁用 localStorage 阶段保存

**修改文件**: `frontend/src/pages/WorkflowControlPage.tsx`

**修改前**:
```typescript
useEffect(() => {
  if (projectId && workflow.currentStage) {
    localStorage.setItem(`project_${projectId}_currentStage`, workflow.currentStage)
  }
}, [projectId, workflow.currentStage])
```

**修改后**:
```typescript
// 🔧 修复：移除 localStorage 阶段保存逻辑
// 原因：localStorage 中的阶段可能与后端实际状态不一致
// 改为完全依赖后端 API 返回的状态
// (已注释掉)
```

---

## 📊 修复效果

### 修复前 ❌

```
用户刷新页面
  ↓
从 localStorage 读取阶段: "content"
  ↓
设置前端显示: "正在执行 内容创作"
  ↓
查询后端: 没有正在运行的任务
  ↓
⚠️ 前端仍然显示运行中
  ↓
不断轮询不存在的任务
```

### 修复后 ✅

```
用户刷新页面
  ↓
默认阶段: "concept"
  ↓
查询后端: 获取所有阶段状态
  ↓
发现 concept, structure 已完成
  ↓
✅ 设置当前阶段为 "content" (下一个未完成阶段)
  ↓
查询后端: 没有正在运行的任务
  ↓
✅ 清理运行状态 (isRunning = false)
  ↓
✅ 停止轮询
```

---

## 🎯 修复的文件

1. `frontend/src/pages/WorkflowControlPage.tsx`
   - 移除 localStorage 阶段恢复逻辑
   - 添加运行状态清理逻辑
   - 根据后端状态确定当前阶段
   - 禁用 localStorage 阶段保存

2. `frontend/src/store/slices/workflowSlice.ts`
   - 移除 Redux store 的 localStorage 恢复逻辑
   - 默认阶段改为 'concept'

---

## ✅ 验证结果

### 编译检查 ✅
```
✅ TypeScript 编译通过
✅ 无类型错误
✅ 无未使用的变量警告
```

### 逻辑验证 ✅
```
✅ 前端阶段完全由后端 API 决定
✅ 没有正在运行的任务时,正确清理状态
✅ 根据已完成阶段自动确定当前阶段
✅ 不再依赖 localStorage
```

---

## 🎊 总结

### 问题根源
- localStorage 中的阶段与后端实际状态不一致
- 没有正确清理运行状态
- 前后端状态同步机制不完善

### 解决方案
- 完全移除 localStorage 阶段恢复逻辑
- 改为从后端 API 获取实际状态
- 添加运行状态清理逻辑
- 根据后端状态智能确定当前阶段

### 修复效果
- ✅ 前后端状态完全一致
- ✅ 不再出现"假运行"状态
- ✅ 不再无限轮询不存在的任务
- ✅ 用户体验更加准确

---

**修复人员**: AI Assistant  
**修复日期**: 2025-11-13  
**状态**: ✅ 完成并验证

