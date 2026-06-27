import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

// 🔧 深拷贝函数
const deepCloneStages = (stages: Record<StageType, Stage>): Record<StageType, Stage> => {
  return JSON.parse(JSON.stringify(stages))
}

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

// 🆕 生成下一章任务状态
export interface GenerateNextChapterState {
  taskId: string | null
  chapterNumber: number | null
  progress: number
  currentStep: number  // 1-4 对应四个步骤
  streamContent: string  // 临时流式内容
  isRunning: boolean
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
  // 🆕 生成下一章任务状态
  generateNextChapter: GenerateNextChapterState
}

const createInitialGenerateNextChapterState = (): GenerateNextChapterState => ({
  taskId: null,
  chapterNumber: null,
  progress: 0,
  currentStep: 0,
  streamContent: '',
  isRunning: false,
})

// 初始状态（Agent ID 使用 snake_case 命名规范）
const initialStages: Record<StageType, Stage> = {
  concept: {
    id: 'concept',
    name: '概念开发',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'creative_director', name: '创意总监', status: 'idle', progress: 0, message: '' },
      { id: 'world_architect', name: '世界观架构师', status: 'idle', progress: 0, message: '' },
      { id: 'character_designer', name: '人物设计师', status: 'idle', progress: 0, message: '' },
    ],
  },
  structure: {
    id: 'structure',
    name: '结构设计',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'plot_architect', name: '情节架构师', status: 'idle', progress: 0, message: '' },
      { id: 'event_validator', name: '事件验证官', status: 'idle', progress: 0, message: '' },
    ],
  },
  content: {
    id: 'content',
    name: '内容创作',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'content_creator', name: '内容创作师', status: 'idle', progress: 0, message: '' },
      { id: 'style_optimizer', name: '文风优化师', status: 'idle', progress: 0, message: '' },
    ],
  },
  review: {
    id: 'review',
    name: '质量评审',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'quality_reviewer', name: '质量评审官', status: 'idle', progress: 0, message: '' },
    ],
  },
  iteration: {
    id: 'iteration',
    name: '迭代优化',
    status: 'pending',
    progress: 0,
    agents: [
      { id: 'iteration_coordinator', name: '迭代协调官', status: 'idle', progress: 0, message: '' },
      { id: 'content_reviser', name: '内容修订师', status: 'idle', progress: 0, message: '' },
      { id: 'final_reviewer', name: '最终审核官', status: 'idle', progress: 0, message: '' },
    ],
  },
}

// 🔧 修复：不再从 localStorage 读取初始阶段
// 原因：localStorage 中的阶段可能与后端实际状态不一致
// 改为从后端 API 获取实际的工作流状态
const initialState: WorkflowState = {
  projectId: null,
  currentStage: 'concept',  // 默认为 concept,后续从后端 API 获取实际状态
  stages: deepCloneStages(initialStages),  // 🔧 使用深拷贝避免引用问题
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
  // 🆕 生成下一章任务初始状态
  generateNextChapter: createInitialGenerateNextChapterState(),
}

// 异步Thunk
export const startWorkflow = createAsyncThunk(
  'workflow/start',
  async ({
    projectId,
    requirement,
    targetChapterCount,
    workflowGenerationModel,
    clearExisting = false,  // 🆕 是否清空现有内容
  }: {
    projectId: number
    requirement: string
    targetChapterCount?: number
    workflowGenerationModel?: string
    clearExisting?: boolean  // 🆕 重新开始时需要清空旧数据
  }) => {
    const response = await apiClient.post('/api/v1/workflow/start', {
      project_id: projectId, // 🎯 确保传递project_id
      requirement,
      target_chapter_count: targetChapterCount,
      workflow_generation_model: workflowGenerationModel,
      clear_existing: clearExisting,  // 🆕 传递清空标志
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
    let projectTitle = '未命名项目'
    if (typeof conceptOutput === 'string') {
      // 尝试从概念输出中提取标题
      const titleMatch = conceptOutput.match(/标题[：:]\s*《?([^》\n]+)》?/i)
      if (titleMatch) {
        const extractedTitle = titleMatch[1].trim()
        if (extractedTitle) {
          projectTitle = extractedTitle
        }
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
        // 重置工作流状态
        state.currentStage = 'concept'
        state.stages = deepCloneStages(initialStages)  // 🔧 使用深拷贝
        state.isRunning = false
        state.overallProgress = 0
        state.error = null
        state.isSavingChapter = false
        state.savedChapterId = null
        state.saveChapterError = null
        state.isCreatingProject = false
        state.createdProjectId = null
        state.createProjectError = null
        state.generateNextChapter = createInitialGenerateNextChapterState()
      } else if (state.projectId === null || state.projectId === 0) {
        // 页面初始化：设置project_id（不重置阶段，由localStorage恢复）
      }
      
      state.projectId = action.payload
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
      const { stage, status, progress, message } = action.payload
      const normalizedAgentId = (
        action.payload.agentId === 'worldview_architect'
          ? 'world_architect'
          : action.payload.agentId.replace(/-/g, '_')
      )

      const stageData = state.stages[stage]
      if (!stageData) {
        return
      }

      const agent = stageData.agents.find((a) => a.id === normalizedAgentId)

      if (agent) {
        agent.status = status
        agent.progress = progress
        agent.message = message
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
      state.stages = deepCloneStages(initialStages)  // 🔧 使用深拷贝
      state.isRunning = false
      state.overallProgress = 0
      state.error = null
      state.isSavingChapter = false
      state.savedChapterId = null
      state.saveChapterError = null
      state.isCreatingProject = false
      state.createdProjectId = null
      state.createProjectError = null
      state.generateNextChapter = createInitialGenerateNextChapterState()
    },
    clearSaveChapterState: (state) => {
      state.isSavingChapter = false
      state.savedChapterId = null
      state.saveChapterError = null
    },
    // 🆕 生成下一章任务 actions
    startGenerateNextChapter: (state, action: PayloadAction<{ taskId: string; chapterNumber: number }>) => {
      state.generateNextChapter = {
        taskId: action.payload.taskId,
        chapterNumber: action.payload.chapterNumber,
        progress: 0,
        currentStep: 0,
        streamContent: '',
        isRunning: true,
      }
    },
    updateGenerateNextChapterProgress: (state, action: PayloadAction<{ progress: number; currentStep: number }>) => {
      state.generateNextChapter.progress = action.payload.progress
      state.generateNextChapter.currentStep = action.payload.currentStep
    },
    appendGenerateNextChapterStream: (state, action: PayloadAction<string>) => {
      state.generateNextChapter.streamContent += action.payload
    },
    clearGenerateNextChapterStream: (state) => {
      state.generateNextChapter.streamContent = ''
    },
    completeGenerateNextChapter: (state) => {
      state.generateNextChapter = createInitialGenerateNextChapterState()
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
  // 🆕 生成下一章 actions
  startGenerateNextChapter,
  updateGenerateNextChapterProgress,
  appendGenerateNextChapterStream,
  clearGenerateNextChapterStream,
  completeGenerateNextChapter,
} = workflowSlice.actions

export default workflowSlice.reducer

