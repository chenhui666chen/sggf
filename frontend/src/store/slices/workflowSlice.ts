import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

// 类型定义
export type StageType = 'concept' | 'structure' | 'content' | 'review' | 'iteration'
export type StageStatus = 'pending' | 'active' | 'completed' | 'error'
export type AgentStatus = 'idle' | 'working' | 'completed' | 'error'

export interface Agent {
  id: string
  name: string
  status: AgentStatus
  progress: number
  message: string
}

export interface Stage {
  id: StageType
  name: string
  status: StageStatus
  progress: number
  agents: Agent[]
  output?: any
  error?: string
}

export interface WorkflowState {
  projectId: number | null
  currentStage: StageType
  stages: Record<StageType, Stage>
  isRunning: boolean
  overallProgress: number
  error: string | null
  loading: boolean
  isSavingChapter: boolean
  savedChapterId: number | null
  saveChapterError: string | null
  isCreatingProject: boolean
  createdProjectId: number | null
  createProjectError: string | null
}

// 初始状态
const initialStages: Record<StageType, Stage> = {
  concept: {
    id: 'concept',
    name: '概念开发',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'creative-director', name: '创意总监', status: 'idle', progress: 0, message: '' },
      { id: 'worldview-architect', name: '世界观架构师', status: 'idle', progress: 0, message: '' },
      { id: 'character-designer', name: '人物设计师', status: 'idle', progress: 0, message: '' },
    ],
  },
  structure: {
    id: 'structure',
    name: '结构设计',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'plot-architect', name: '情节架构师', status: 'idle', progress: 0, message: '' },
      { id: 'event-validator', name: '事件验证官', status: 'idle', progress: 0, message: '' },
    ],
  },
  content: {
    id: 'content',
    name: '内容创作',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'content-creator', name: '内容创作师', status: 'idle', progress: 0, message: '' },
      { id: 'style-optimizer', name: '文风优化师', status: 'idle', progress: 0, message: '' },
    ],
  },
  review: {
    id: 'review',
    name: '质量评审',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'quality-reviewer', name: '质量评审官', status: 'idle', progress: 0, message: '' },
    ],
  },
  iteration: {
    id: 'iteration',
    name: '迭代优化',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'iteration-coordinator', name: '迭代协调官', status: 'idle', progress: 0, message: '' },
    ],
  },
}

// 🆕 从 localStorage 读取初始阶段（如果存在）
const getInitialStage = (): StageType => {
  // 从 URL 读取 projectId
  const urlParams = new URLSearchParams(window.location.search)
  const pathParts = window.location.pathname.split('/')
  const projectIdFromPath = pathParts[pathParts.indexOf('workflow') + 1]
  const projectId = projectIdFromPath || urlParams.get('projectId')
  
  if (projectId) {
    const savedStage = localStorage.getItem(`project_${projectId}_currentStage`)
    if (savedStage && ['concept', 'structure', 'content', 'review', 'iteration'].includes(savedStage)) {
      console.log(`💾 Redux初始化：恢复项目 ${projectId} 的上次阶段: ${savedStage}`)
      return savedStage as StageType
    }
  }
  
  // 默认返回 concept
  return 'concept'
}

const initialState: WorkflowState = {
  projectId: null,
  currentStage: getInitialStage(),  // 🔧 修复：从 localStorage 读取初始阶段
  stages: initialStages,
  isRunning: false,
  overallProgress: 0,
  error: null,
  loading: false,
  isSavingChapter: false,
  savedChapterId: null,
  saveChapterError: null,
  isCreatingProject: false,
  createdProjectId: null,
  createProjectError: null,
}

// 异步Thunk
export const startWorkflow = createAsyncThunk(
  'workflow/start',
  async ({ projectId, requirement }: { projectId: number; requirement: string }) => {
    const response = await apiClient.post('/api/v1/workflow/start', {
      project_id: projectId,  // 🎯 确保传递project_id
      requirement,
    })
    return response.data
  }
)

export const executeStage = createAsyncThunk(
  'workflow/executeStage',
  async ({ projectId, stage }: { projectId: number; stage: StageType }) => {
    const response = await apiClient.post('/api/v1/workflow/execute-stage', {
      project_id: projectId,  // 🎯 确保传递project_id
      stage,
    })
    return response.data
  }
)

export const regenerateStage = createAsyncThunk(
  'workflow/regenerateStage',
  async ({ projectId, stage }: { projectId: number; stage: StageType }) => {
    const response = await apiClient.post('/api/v1/workflow/regenerate-stage', {
      project_id: projectId,  // 🎯 确保传递project_id
      stage,
    })
    return response.data
  }
)

export const getWorkflowStatus = createAsyncThunk(
  'workflow/getStatus',
  async (projectId: number) => {
    const response = await apiClient.get(`/api/v1/workflow/status/${projectId}`)
    return response.data
  }
)

export const saveWorkflowAsChapter = createAsyncThunk(
  'workflow/saveAsChapter',
  async ({ projectId, chapterTitle, content }: { projectId: number; chapterTitle: string; content: string }) => {
    // 获取项目的章节数量来确定章节号
    const chaptersResponse = await apiClient.getChapters(projectId)
    const chapters = chaptersResponse.data || []
    const nextChapterNumber = chapters.length + 1

    // 创建新章节
    const response = await apiClient.createChapter(projectId, {
      chapter_number: nextChapterNumber,
      title: chapterTitle,
      content: content,
    })
    return response.data
  }
)

// 完成工作流程并创建项目
export const completeWorkflowAndCreateProject = createAsyncThunk(
  'workflow/completeAndCreateProject',
  async ({
    requirement,
    conceptOutput,
    structureOutput,
    contentOutput,
    reviewOutput,
    iterationOutput
  }: {
    requirement: string
    conceptOutput: any
    structureOutput: any
    contentOutput: any
    reviewOutput: any
    iterationOutput: any
  }) => {
    // 从概念输出中提取项目标题
    let projectTitle = 'New Novel'
    if (typeof conceptOutput === 'string') {
      // 尝试从概念输出中提取标题
      const titleMatch = conceptOutput.match(/标题[：:]\s*《?([^》\n]+)》?/i)
      if (titleMatch) {
        projectTitle = titleMatch[1].trim()
      }
    }

    // 创建新项目
    const projectResponse = await apiClient.createProject({
      title: projectTitle,
      description: requirement,
      genre: 'Fantasy', // 默认类型，可以从需求中推断
    })

    const newProjectId = projectResponse.data.id

    // 保存工作流程的所有内容为章节
    const chaptersToSave = [
      { title: '故事概念', content: conceptOutput },
      { title: '情节大纲', content: structureOutput },
      { title: '章节初稿', content: contentOutput },
      { title: '质量评审', content: reviewOutput },
      { title: '最终成品', content: iterationOutput },
    ]

    for (let i = 0; i < chaptersToSave.length; i++) {
      const chapter = chaptersToSave[i]
      await apiClient.createChapter(newProjectId, {
        chapter_number: i + 1,
        title: chapter.title,
        content: chapter.content,
      })
    }

    return {
      projectId: newProjectId,
      projectTitle,
    }
  }
)

// Slice
const workflowSlice = createSlice({
  name: 'workflow',
  initialState,
  reducers: {
    setProjectId: (state, action: PayloadAction<number>) => {
      // 🎯 任务2：项目切换时清理旧的工作流状态
      // 🔧 修复：只有当projectId从一个非空ID切换到另一个ID时才重置
      // 避免页面刷新时（state.projectId为null）被误判为项目切换
      const isProjectSwitch = state.projectId !== null && 
                             state.projectId !== 0 && 
                             state.projectId !== action.payload
      
      if (isProjectSwitch) {
        console.log(`🔄 项目切换：${state.projectId} → ${action.payload}，清理工作流状态`)
        // 重置工作流状态
        state.currentStage = 'concept'
        state.stages = initialStages
        state.isRunning = false
        state.overallProgress = 0
        state.error = null
        state.isSavingChapter = false
        state.savedChapterId = null
        state.saveChapterError = null
        state.isCreatingProject = false
        state.createdProjectId = null
        state.createProjectError = null
      } else if (state.projectId === null || state.projectId === 0) {
        console.log(`💾 页面初始化：设置project_id=${action.payload}（不重置阶段，由localStorage恢复）`)
      }
      
      state.projectId = action.payload
      console.log(`✅ 工作流已设置项目上下文：project_id=${action.payload}`)
    },
    setCurrentStage: (state, action: PayloadAction<StageType>) => {
      state.currentStage = action.payload
    },
    updateStageStatus: (state, action: PayloadAction<{ stage: StageType; status: StageStatus }>) => {
      state.stages[action.payload.stage].status = action.payload.status
    },
    // ✅ 新增：重置后续阶段状态
    resetFollowingStages: (state, action: PayloadAction<StageType>) => {
      const stageList: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
      const currentStageIndex = stageList.indexOf(action.payload)
      
      // 重置当前阶段之后的所有阶段
      for (let i = currentStageIndex + 1; i < stageList.length; i++) {
        const stage = stageList[i]
        state.stages[stage].status = 'pending'
        state.stages[stage].progress = 0
        // 重置 Agent 状态
        state.stages[stage].agents.forEach(agent => {
          agent.status = 'idle'
          agent.progress = 0
          agent.message = ''
        })
      }
      
      console.log(`✅ 已重置 ${action.payload} 之后的所有阶段状态为 pending`)
    },
    updateAgentStatus: (
      state,
      action: PayloadAction<{
        stage: StageType
        agentId: string
        status: AgentStatus
        progress: number
        message: string
      }>
    ) => {
      const agent = state.stages[action.payload.stage].agents.find(
        (a) => a.id === action.payload.agentId
      )
      if (agent) {
        agent.status = action.payload.status
        agent.progress = action.payload.progress
        agent.message = action.payload.message
      }
    },
    updateStageOutput: (state, action: PayloadAction<{ stage: StageType; output: any }>) => {
      state.stages[action.payload.stage].output = action.payload.output
    },
    updateOverallProgress: (state, action: PayloadAction<number>) => {
      state.overallProgress = action.payload
    },
    resetWorkflow: (state) => {
      state.currentStage = 'concept'
      state.stages = initialStages
      state.isRunning = false
      state.overallProgress = 0
      state.error = null
      state.isSavingChapter = false
      state.savedChapterId = null
      state.saveChapterError = null
      state.isCreatingProject = false
      state.createdProjectId = null
      state.createProjectError = null
    },
    clearSaveChapterState: (state) => {
      state.isSavingChapter = false
      state.savedChapterId = null
      state.saveChapterError = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(startWorkflow.pending, (state) => {
        state.loading = true
        state.isRunning = true
        state.error = null
      })
      .addCase(startWorkflow.fulfilled, (state, action) => {
        state.loading = false
        state.stages = action.payload.stages || state.stages
        state.currentStage = 'concept'
      })
      .addCase(startWorkflow.rejected, (state, action) => {
        state.loading = false
        state.isRunning = false
        state.error = action.error.message || 'Failed to start workflow'
      })
      .addCase(executeStage.pending, (state) => {
        state.loading = true
        state.stages[state.currentStage].status = 'active'
      })
      .addCase(executeStage.fulfilled, (state, action) => {
        state.loading = false
        state.stages[state.currentStage].status = 'completed'
        state.stages[state.currentStage].output = action.payload.output

        // 自动更新总体进度
        const stageList: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
        const completedCount = stageList.filter(stage => state.stages[stage].status === 'completed').length
        state.overallProgress = Math.round((completedCount / stageList.length) * 100)
      })
      .addCase(executeStage.rejected, (state, action) => {
        state.loading = false
        state.stages[state.currentStage].status = 'error'
        state.error = action.error.message || 'Failed to execute stage'
      })
      .addCase(saveWorkflowAsChapter.pending, (state) => {
        state.isSavingChapter = true
        state.saveChapterError = null
      })
      .addCase(saveWorkflowAsChapter.fulfilled, (state, action) => {
        state.isSavingChapter = false
        state.savedChapterId = action.payload.id
        state.saveChapterError = null
      })
      .addCase(saveWorkflowAsChapter.rejected, (state, action) => {
        state.isSavingChapter = false
        state.saveChapterError = action.error.message || 'Failed to save chapter'
      })
      .addCase(completeWorkflowAndCreateProject.pending, (state) => {
        state.isCreatingProject = true
        state.createProjectError = null
      })
      .addCase(completeWorkflowAndCreateProject.fulfilled, (state, action) => {
        state.isCreatingProject = false
        state.createdProjectId = action.payload.projectId
        state.createProjectError = null
      })
      .addCase(completeWorkflowAndCreateProject.rejected, (state, action) => {
        state.isCreatingProject = false
        state.createProjectError = action.error.message || 'Failed to create project'
      })
  },
})

export const {
  setProjectId,
  setCurrentStage,
  updateStageStatus,
  resetFollowingStages,  // ✅ 导出新增的 action
  updateAgentStatus,
  updateStageOutput,
  updateOverallProgress,
  resetWorkflow,
  clearSaveChapterState,
} = workflowSlice.actions

export default workflowSlice.reducer

