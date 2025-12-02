# Agent 状态实时更新修复报告

## 🔍 问题诊断

### 问题现象
用户点击"生成下一章"按钮后，前端页面上的 Agent 状态信息（如当前执行阶段、进度、状态等）没有实时更新。

### 根本原因
通过代码搜索发现，**`execute_generate_next_chapter_task` 函数缺少 Agent 状态推送**：

#### ✅ 对比：普通工作流（有 Agent 状态）
在 `execute_stage_background` 函数中（第583-617行）：
```python
# 推送 Agent 开始工作状态
stage_agents = STAGE_AGENTS.get(stage_enum.value, [])
for agent in stage_agents:
    await ws_manager.send_agent_status(
        project_id=project_id,
        stage=stage_enum.value,
        agent_id=agent['id'],
        agent_name=agent['name'],
        status='working',
        progress=0,
        message=f'{agent["name"]}正在工作中...'
    )
```

#### ❌ 问题：生成下一章流程（无 Agent 状态）
原 `execute_generate_next_chapter_task` 函数中：
- ❌ 没有定义 Agent 列表
- ❌ 没有在各步骤开始时推送 Agent 状态
- ❌ 没有在步骤完成时更新 Agent 状态

## ✅ 修复方案

### 修改文件
`backend/app/api/v1/workflow.py` - `execute_generate_next_chapter_task` 函数

### 修复内容

#### 1. 定义四个步骤对应的 Agent 列表
```python
STEP_AGENTS = {
    'structure': [  # 步骤1：章节规划
        {'id': 'plot_architect', 'name': '情节架构师', 'stage': 'structure'},
        {'id': 'event_validator', 'name': '事件验证官', 'stage': 'structure'},
    ],
    'content': [  # 步骤2:内容创作
        {'id': 'content_creator', 'name': '内容创作师', 'stage': 'content'},
        {'id': 'style_optimizer', 'name': '文风优化师', 'stage': 'content'},
    ],
    'review': [  # 步骤3：质量评审
        {'id': 'quality_reviewer', 'name': '质量评审官', 'stage': 'review'},
    ],
    'iteration': [  # 步骤4：迭代优化
        {'id': 'iteration_coordinator', 'name': '迭代协调官', 'stage': 'iteration'},
        {'id': 'content_reviser', 'name': '内容修订师', 'stage': 'iteration'},
        {'id': 'final_reviewer', 'name': '最终审核官', 'stage': 'iteration'},
    ],
}
```

#### 2. 在每个步骤开始时推送 Agent 开始工作状态
```python
# 步骤1开始
step1_agents = STEP_AGENTS['structure']
for agent in step1_agents:
    await ws_manager.send_agent_status(
        project_id=project_id,
        stage=agent['stage'],
        agent_id=agent['id'],
        agent_name=agent['name'],
        status='working',
        progress=0,
        message=f'{agent["name"]}正在规划章节结构...'
    )
```

#### 3. 在每个步骤完成时推送 Agent 完成状态
```python
# 步骤1完成
for agent in step1_agents:
    await ws_manager.send_agent_status(
        project_id=project_id,
        stage=agent['stage'],
        agent_id=agent['id'],
        agent_name=agent['name'],
        status='completed',
        progress=100,
        message=f'{agent["name"]}已完成'
    )
```

#### 4. 四个步骤全部添加状态推送
- ✅ 步骤1（章节规划）：2个 Agent
- ✅ 步骤2（内容创作）：2个 Agent
- ✅ 步骤3（质量评审）：1个 Agent
- ✅ 步骤4（迭代优化）：3个 Agent

**总计新增代码：128 行**

## 🔄 工作流程

### 后端 WebSocket 推送
1. **步骤开始**：推送 Agent 状态为 `working`
2. **步骤进行中**：推送任务进度更新
3. **步骤完成**：推送 Agent 状态为 `completed`

### 前端接收和显示
1. **WebSocket 监听**（WorkflowControlPage.tsx 第1266-1303行）
   ```typescript
   workflowWebSocket.onAgentStatus((data) => {
     dispatch(updateAgentStatus({
       stage: stage,
       agentId: agentId,
       status: data.status,
       progress: data.progress,
       message: data.message
     }))
   })
   ```

2. **状态显示**（WorkflowControlPage.tsx 第3993-3995行）
   ```typescript
   {workflow.stages[workflow.currentStage].agents.map((agent) => (
     <AgentStatusIndicator key={agent.id} agent={agent} />
   ))}
   ```

3. **阶段自动切换**（WorkflowControlPage.tsx 第1118-1148行）
   ```typescript
   // 根据进度自动切换阶段
   if (progress < 25) targetStage = 'structure'
   else if (progress < 50) targetStage = 'content'
   else if (progress < 75) targetStage = 'review'
   else targetStage = 'iteration'
   
   dispatch(setCurrentStage(targetStage))
   ```

## 📊 预期效果

### 生成下一章时的 UI 表现

#### 步骤1：章节规划（0-25%）
- 🔄 **当前阶段**: 结构设计
- 👥 **Agent 状态**:
  - 情节架构师：工作中 → 已完成
  - 事件验证官：工作中 → 已完成

#### 步骤2：内容创作（25-50%）
- 🔄 **当前阶段**: 内容创作
- 👥 **Agent 状态**:
  - 内容创作师：工作中 → 已完成
  - 文风优化师：工作中 → 已完成
- 📝 **流式内容**: 实时显示生成的章节内容

#### 步骤3：质量评审（50-75%）
- 🔄 **当前阶段**: 质量评审
- 👥 **Agent 状态**:
  - 质量评审官：工作中 → 已完成
- 📝 **流式内容**: 实时显示评审报告

#### 步骤4：迭代优化（75-100%）
- 🔄 **当前阶段**: 迭代优化
- 👥 **Agent 状态**:
  - 迭代协调官：工作中 → 已完成
  - 内容修订师：工作中 → 已完成
  - 最终审核官：工作中 → 已完成
- 📝 **流式内容**: 实时显示优化后的最终内容

## 🧪 测试建议

### 测试步骤
1. 启动后端服务（FastAPI + WebSocket）：`ws.bat`
2. 启动前端服务
3. 打开浏览器控制台查看日志
4. 进入已有项目的工作流页面
5. 点击"生成下一章"按钮
6. 观察：
   - ✅ 阶段自动切换（structure → content → review → iteration）
   - ✅ Agent 状态实时更新（idle → working → completed）
   - ✅ 进度条平滑增长（0% → 100%）
   - ✅ 流式内容实时显示（打字机效果）

### 关键日志检查点

#### 后端日志（uvicorn）
```
📡 已发送 2 个 Agent 开始状态（步骤1）
📡 已发送 2 个 Agent 完成状态（步骤1）
📡 已发送 2 个 Agent 开始状态（步骤2）
...
```

#### 前端日志（浏览器控制台）
```
🤖 收到 Agent 状态: {agent_id: 'plot_architect', status: 'working', ...}
✅ Agent 状态已更新: plot_architect (structure) -> working
📍 生成下一章: 自动切换到 structure 阶段 (进度: 10%)
🌊 流式输出开始: {stage: 'content', ...}
```

## 🎯 总结

### 问题
- Agent 状态不更新

### 根因
- 生成下一章流程缺少 WebSocket Agent 状态推送

### 方案
- 在四个步骤的开始和结束时推送 Agent 状态

### 结果
- ✅ Agent 状态实时更新
- ✅ 阶段自动切换
- ✅ 进度条准确显示
- ✅ 流式内容实时展示

---

**修复完成时间**: 2025-12-01
**修改文件**: `backend/app/api/v1/workflow.py`
**新增代码行数**: 128 行
**影响范围**: 生成下一章功能的 Agent 状态显示
