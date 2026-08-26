import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Stepper,
  Step,
  StepLabel,
  Button,
  Card,
  CardContent,
  Typography,
  LinearProgress,
  Paper,
  Dialog,
  TextField,
  Alert,
  CircularProgress,
  Tooltip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormHelperText,
  Drawer,
  IconButton,
  Chip,
  Badge,
  Snackbar,
  Alert as MuiAlert,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DescriptionIcon from '@mui/icons-material/Description'
import ArticleIcon from '@mui/icons-material/Article'
import EditNoteIcon from '@mui/icons-material/EditNote'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import PublicIcon from '@mui/icons-material/Public'
import PeopleIcon from '@mui/icons-material/People'
import NavigateNextIcon from '@mui/icons-material/NavigateNext'
import AddIcon from '@mui/icons-material/Add'
import MenuIcon from '@mui/icons-material/Menu'
import CloseIcon from '@mui/icons-material/Close'
import TuneIcon from '@mui/icons-material/Tune'
import { RootState, AppDispatch, store } from '@/store/store'
import {
  startWorkflow,
  regenerateStage,
  setCurrentStage,
  setProjectId,
  updateStageOutput,
  updateStageStatus,
  updateAgentStatus,  // ✅ 添加导入
  resetFollowingStages,  // ✅ 导入新的 action
  type AgentStatus,
  type StageType,
  // 🆕 生成下一章 actions
  startGenerateNextChapter,
  updateGenerateNextChapterProgress,
  appendGenerateNextChapterStream,
  clearGenerateNextChapterStream,
  completeGenerateNextChapter,
} from '@/store/slices/workflowSlice'
import { fetchProject } from '@/store/slices/projectSlice'
import { fetchChapters } from '@/store/slices/editorSlice'
import StageInfoPanel from '@/components/workflow/StageInfoPanel'
import OutputPreviewPanel from '@/components/workflow/OutputPreviewPanel'
import AgentStatusIndicator from '@/components/workflow/AgentStatusIndicator'
import MultiModelReviewSettingsDialog from '@/components/project/MultiModelReviewSettingsDialog'
import { workflowWebSocket } from '@/services/websocket'
import { apiClient, extractApiErrorMessage } from '@/services/api'  // ✅ 添加apiClient导入
import type { WorkflowGenerationModel } from '@/services/api'
import type { ReviewMeta, ReviewPreset } from '@/types/project'
import { formatProjectSequenceLabel } from '@/utils/projectDisplay'
import { ProgressEstimator, type StageDurations, type ProgressState } from '@/utils/progressEstimator'
import { statisticsService } from '@/services/statistics'
import {
  chooseWorkflowGenerationModel,
  readStoredWorkflowGenerationModel,
  writeStoredWorkflowGenerationModel,
} from '@/utils/workflowGenerationModelPreference'
import {
  formatWorkflowGenerationModelOptionLabel,
  formatWorkflowGenerationModelTooltip,
} from '@/utils/workflowGenerationModelDisplay'
import { buildStoryExpansionCompletionMessage } from '@/utils/storyExpansionFeedback'
import { resolveRestoredRunningTask } from '@/utils/restoreRunningWorkflowTask'
import { selectLatestChapterForOverwrite } from '@/utils/selectLatestChapterForOverwrite'
import {
  getStoryExpansionResultFromTaskComplete,
  isStoryExpansionTaskId,
} from '@/utils/storyExpansionEvents'


const stages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
const stageNames = {
  concept: '概念开发',
  structure: '结构设计',
  content: '内容创作',
  review: '质量评审',
  iteration: '迭代优化',
}

const isStageType = (value: string | null | undefined): value is StageType => {
  return Boolean(value && stages.includes(value as StageType))
}

const coerceAgentStatus = (value: string | null | undefined): AgentStatus => {
  switch (value) {
    case 'idle':
    case 'working':
    case 'completed':
    case 'error':
      return value
    case 'failed':
      return 'error'
    default:
      return 'working'
  }
}

export default function WorkflowControlPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const dispatch = useDispatch<AppDispatch>()
  const workflow = useSelector((state: RootState) => state.workflow)
  // 🎯 任务3：获取当前项目信息
  const currentProject = useSelector((state: RootState) => state.project.currentProject)
  const [openDialog, setOpenDialog] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [workflowGenerationModel, setWorkflowGenerationModel] = useState(
    () => readStoredWorkflowGenerationModel() || 'qwen3.7-plus'
  )
  const [workflowGenerationModels, setWorkflowGenerationModels] = useState<WorkflowGenerationModel[]>([])
  const [workflowGenerationModelsLoading, setWorkflowGenerationModelsLoading] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [isStarting, setIsStarting] = useState(false)  // 新增：标记是否正在启动工作流
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [chapterTitle, setChapterTitle] = useState('')
  
  // 🆕 题材与篇幅规划状态
  const [genre, setGenre] = useState('')
  const [subGenre] = useState('')
  const [plannedLengthType, setPlannedLengthType] = useState('')
  const [plannedChaptersMin, setPlannedChaptersMin] = useState<number | ''>('')
  const [plannedChaptersMax, setPlannedChaptersMax] = useState<number | ''>('')
  const [userOutlinePlan, setUserOutlinePlan] = useState('')

  // 🔥 页面加载时，恢复上次的项目位置
  useEffect(() => {
    const savedProjectId = localStorage.getItem('lastWorkflowProjectId')
    if (savedProjectId && !projectId) {
      navigate(`/workflow/${savedProjectId}`)
    }
  }, [])
  useEffect(() => {
    let active = true
    setWorkflowGenerationModelsLoading(true)
    apiClient.getWorkflowGenerationModels()
      .then((response) => {
        if (!active || response.status < 200 || response.status >= 300) return
        const models = response.data.models || []
        const defaultModel = response.data.default_model || 'qwen3.7-plus'
        const storedModel = readStoredWorkflowGenerationModel()
        setWorkflowGenerationModels(models)
        setWorkflowGenerationModel((current) => chooseWorkflowGenerationModel({
          models,
          currentModel: current,
          storedModel,
          defaultModel,
        }))
      })
      .catch(() => {
        if (!active) return
        setWorkflowGenerationModels([])
        setWorkflowGenerationModel(readStoredWorkflowGenerationModel() || 'qwen3.7-plus')
      })
      .finally(() => {
        if (active) {
          setWorkflowGenerationModelsLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [])

  const handleWorkflowGenerationModelChange = (modelId: string) => {
    setWorkflowGenerationModel(modelId)
    writeStoredWorkflowGenerationModel(modelId)
  }

  // 🔥 页面离开前，保存当前项目ID
  useEffect(() => {
    if (projectId) {
      localStorage.setItem('lastWorkflowProjectId', projectId)
    }
  }, [projectId])

  // 🆕 检查 autoStart 参数，自动打开开始创作对话框
  useEffect(() => {
    const autoStart = searchParams.get('autoStart')
    if (autoStart === 'true' && projectId) {
      // 移除 autoStart 参数，避免刷新时重复触发
      searchParams.delete('autoStart')
      setSearchParams(searchParams, { replace: true })
      // 延迟打开对话框，确保页面已加载
      setTimeout(() => {
        setOpenDialog(true)
      }, 300)
    }
  }, [projectId, searchParams, setSearchParams])

  // 项目切换时重置项目级本地状态，避免旧项目上下文串入新项目
  useEffect(() => {
    if (!projectId) return
    setTaskPollingInterval((currentInterval) => {
      if (currentInterval) {
        clearInterval(currentInterval)
      }
      return null
    })

    setRequirement('')
    setGenre('')
    setPlannedLengthType('')
    setPlannedChaptersMin('')
    setPlannedChaptersMax('')
    setUserOutlinePlan('')

    setOpenDialog(false)
    setIsRunning(false)
    setIsStarting(false)
    setShowSaveDialog(false)
    setChapterTitle('')
    setShowContentWarningDialog(false)

    setConceptContent('')
    setWorldContent('')
    setCharacterContent('')
    setStructureContent('')
    setEditedStructureContent('')
    setContentDraftContent('')
    setEditedContentDraftContent('')
    setReviewReportContent('')
    setEditedReviewReportContent('')
    setReviewMeta(null)
    setFinalVersionContent('')
    setEditedFinalVersionContent('')

    setShowStructureDialog(false)
    setStructureLoading(false)
    setStructureSaving(false)
    setShowContentDialog(false)
    setContentLoading(false)
    setContentSaving(false)
    setShowFinalVersionDialog(false)
    setFinalVersionLoading(false)
    setShowReviewDialog(false)
    setReviewLoading(false)
    setReviewSaving(false)
    setShowReviewSettingsDialog(false)

    setIsStreaming(false)
    setStreamingStage(null)
    setProgressMessage('')
    setSelectedConceptView('concept')

    setShowRegenerateDialog(false)
    setRegenerateTarget('both')
    setRegenerateFeedback('')
    setConceptDecisionShownThisSession(false)
    setDecisionReady(false)
    setShowDecisionDialog(false)
    setLeftDrawerOpen(false)

    setSnackbarOpen(false)
    setSnackbarMessage('')
    setSnackbarSeverity('success')

    setGeneratingNextChapter(false)
    setSavingChapter(false)
    setChapterTitleInput('')
    setCurrentTaskId(null)
    setTaskProgress(0)
    setConversationHistory([])

    dispatch(updateStageOutput({ stage: 'concept', output: '' }))
    dispatch(updateStageOutput({ stage: 'structure', output: '' }))
    dispatch(updateStageOutput({ stage: 'content', output: '' }))
    dispatch(updateStageOutput({ stage: 'review', output: '' }))
    dispatch(updateStageOutput({ stage: 'iteration', output: '' }))
  }, [projectId, dispatch])

  // 🆕 保护机制：已有内容警告对话框
  const [showContentWarningDialog, setShowContentWarningDialog] = useState(false)
  const [existingChaptersCount, _setExistingChaptersCount] = useState(0)
  const [freeQuota, setFreeQuota] = useState<{
    remaining: number
    resetAt: string
    globalAvailable: boolean
  } | null>(null)

  useEffect(() => {
    let active = true
    apiClient.getFreeGenerationQuota().then((response) => {
      if (!active || response.status < 200 || response.status >= 300) return
      setFreeQuota({
        remaining: response.data.remaining,
        resetAt: response.data.reset_at,
        globalAvailable: response.data.global_available,
      })
    }).catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  // 故事概念内容状态（仅用于显示，不再需要对话框）
  const [conceptContent, setConceptContent] = useState('')

  // 情节大纲对话框状态
  const [showStructureDialog, setShowStructureDialog] = useState(false)
  const [structureContent, setStructureContent] = useState('')
  const [editedStructureContent, setEditedStructureContent] = useState('')
  const [structureLoading, setStructureLoading] = useState(false)
  const [structureSaving, setStructureSaving] = useState(false)

  // 章节初稿对话框状态
  const [showContentDialog, setShowContentDialog] = useState(false)
  const [contentDraftContent, setContentDraftContent] = useState('')
  const [editedContentDraftContent, setEditedContentDraftContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)
  const [contentSaving, setContentSaving] = useState(false)

  // 最终版本对话框状态（已移除finalVersionSaving，统一使用savingChapter）
  const [showFinalVersionDialog, setShowFinalVersionDialog] = useState(false)
  const [finalVersionContent, setFinalVersionContent] = useState('')
  const [editedFinalVersionContent, setEditedFinalVersionContent] = useState('')
  const [finalVersionLoading, setFinalVersionLoading] = useState(false)

  // 评审报告对话框状态
  const [showReviewDialog, setShowReviewDialog] = useState(false)
  const [reviewReportContent, setReviewReportContent] = useState('')
  const [editedReviewReportContent, setEditedReviewReportContent] = useState('')
  const [reviewMeta, setReviewMeta] = useState<ReviewMeta | null>(null)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)
  const [showReviewSettingsDialog, setShowReviewSettingsDialog] = useState(false)
  const [showManualReviewDialog, setShowManualReviewDialog] = useState(false)
  const [manualReviewPreset, setManualReviewPreset] = useState<ReviewPreset>('key_chapter_5')

  // 🆕 流式输出状态
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingStage, setStreamingStage] = useState<StageType | null>(null)
  // 🆕 新增：进度消息（如"正在迭代第1/3轮..."）
  const [progressMessage, setProgressMessage] = useState('')
  
  // 🆕 概念开发阶段预览选择状态（保留最后点击的按钮）
  const [selectedConceptView, setSelectedConceptView] = useState<'concept' | 'world' | 'character'>('concept')

  // 世界观和人物设定内容状态（仅用于显示，不再需要对话框）
  const [worldContent, setWorldContent] = useState('')
  const [characterContent, setCharacterContent] = useState('')
  // 🆕 概念阶段决策条与重生成弹窗（UI骨架）
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false)
  const [regenerateTarget, setRegenerateTarget] = useState<'both' | 'story' | 'world'>('both')
  const [regenerateFeedback, setRegenerateFeedback] = useState('')
  const [conceptDecisionShownThisSession, setConceptDecisionShownThisSession] = useState(false)
  const [autoInferFeedback, setAutoInferFeedback] = useState(true)
  const [decisionReady, setDecisionReady] = useState(false)
  const [showDecisionDialog, setShowDecisionDialog] = useState(false)
  
  // 🆕 左侧抽屉展开/收起状态
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(false)

  const refreshWorkflowReviewMeta = async (targetProjectId: number) => {
    try {
      const reviewMetaResponse = await apiClient.getWorkflowReviewMeta(targetProjectId)
      if (reviewMetaResponse.status >= 200 && reviewMetaResponse.status < 300) {
        setReviewMeta(reviewMetaResponse.data.review_meta || null)
      }
    } catch {
      setReviewMeta(null)
    }
  }

  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'warning' | 'info'>('success')

  // 生成下一章状态
  const [generatingNextChapter, setGeneratingNextChapter] = useState(false)

  // 保存章节状态（最终版本对话框统一使用此状态）
  const [savingChapter, setSavingChapter] = useState(false)
  const [chapterTitleInput, setChapterTitleInput] = useState('')

  // 🆕 异步任务状态
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [taskPollingInterval, setTaskPollingInterval] = useState<NodeJS.Timeout | null>(null)
  const [taskProgress, setTaskProgress] = useState(0)

  // 🆕 标记是否是“生成下一章”流程（已经自动保存，不需要再次保存）
  const [isGenerateNextChapterFlow, setIsGenerateNextChapterFlow] = useState(false)

  // 🆕 生成下一章异步任务状态 - 从 Redux 读取
  const generateNextChapter = useSelector((state: RootState) => state.workflow.generateNextChapter)
  const generateNextChapterTaskId = generateNextChapter.taskId
  const generateNextChapterProgress = generateNextChapter.progress
  const generateNextChapterStreamContent = generateNextChapter.streamContent
  const generateNextChapterNumber = generateNextChapter.chapterNumber

  // 🆕 自动保存记忆状态（始终启用，UI 面板已隐藏）
  const autoSaveEnabled = true  // 🔧 简化：始终启用自动保存
  const [, setLastSaveTime] = useState<Date | null>(null)  // 仅用于更新，不显示
  // 🔧 修复：对话历史记录 - 收集工作流中的对话内容
  const [conversationHistory, setConversationHistory] = useState<Array<{role: string, content: string, stage?: string, timestamp?: string}>>([])

  // 🆕 进度估算器相关状态
  const [progressEstimator, setProgressEstimator] = useState<ProgressEstimator | null>(null)
  const [stageDurations, setStageDurations] = useState<StageDurations | null>(null)
  const [estimatedRemainingTime, setEstimatedRemainingTime] = useState(0)
  const [estimatedRemainingTimeMin, setEstimatedRemainingTimeMin] = useState(0)  // 🆕
  const [estimatedRemainingTimeMax, setEstimatedRemainingTimeMax] = useState(0)  // 🆕

  // 🆕 初始化进度估算器（自适应学习 + 置信区间）
  useEffect(() => {
    const initProgressEstimator = async () => {
      try {
        // 🆕 跨项目统计：不传 projectId，统计当前用户所有项目的数据
        // 优先使用最近3次任务的平均耗时（自适应学习）
        let durations = await statisticsService.getStageDurations(
          undefined,  // 不传 projectId，实现跨项目统计
          3  // 最近3次任务
        )

        // 检查是否有足够的数据
        const hasEnoughData = Object.values(durations).every(d => d > 0)

        if (!hasEnoughData) {
          // 如果最近3次任务数据不足，回退到全局平均
          durations = await statisticsService.getStageDurations(
            undefined  // 不传 projectId，统计所有项目
          )
        }

        setStageDurations(durations)

        // 🆕 获取置信区间（同样跨项目）
        const durationRanges = await statisticsService.getStageDurationRanges(
          undefined  // 不传 projectId
        )

        // 创建进度估算器（传入置信区间）
        const estimator = new ProgressEstimator(durations, durationRanges || undefined)
        setProgressEstimator(estimator)
      } catch {
        // 初始化进度估算器失败，使用默认值
      }
    }

    initProgressEstimator()
  }, [])  // 只在组件加载时执行一次，不依赖 projectId

  useEffect(() => {
    if (projectId) {
      // 🔧 修复：不再从 localStorage 恢复阶段
      // 原因：localStorage 中的阶段可能与后端实际状态不一致
      // 改为从后端 API 获取实际的工作流状态

      // 🎯 任务2：项目切换时设置新的项目上下文
      dispatch(setProjectId(Number(projectId)))

      // 🎯 任务3：加载项目信息用于显示
      dispatch(fetchProject(Number(projectId)))
    }
  }, [projectId, dispatch])

  // 🆕 题材映射表（Dashboard英文 → WorkflowControl中文）
  const genreMapping: Record<string, string> = {
    'Fantasy': '修仙',
    'Science Fiction': '科幻',
    'Romance': '言情',
    'Mystery': '悬疑',
    'Thriller': '悬疑',
    'Other': '',
    // 直接中文匹配
    '修仙': '修仙',
    '玄幻': '修仙',
    '都市': '都市',
    '悬疑': '悬疑',
    '言情': '言情',
    '耽美': '言情',
    '科幻': '科幻',
    '纯文学': '纯文学',
  }

  // 🆕 当项目数据加载后，自动填充题材和篇幅设置
  useEffect(() => {
    if (!currentProject) return

    // 自动填充题材
    if (currentProject.genre && !genre) {
      const mappedGenre = genreMapping[currentProject.genre] || currentProject.genre
      if (mappedGenre) {
        setGenre(mappedGenre)
      }
    }

    // 自动填充篇幅设置
    if (currentProject.planned_length_type && !plannedLengthType) {
      setPlannedLengthType(currentProject.planned_length_type)
    }

    // 自动填充章节范围
    if (currentProject.planned_chapters_min && !plannedChaptersMin) {
      setPlannedChaptersMin(currentProject.planned_chapters_min)
    }
    if (currentProject.planned_chapters_max && !plannedChaptersMax) {
      setPlannedChaptersMax(currentProject.planned_chapters_max)
    }

    // 自动填充自定义大纲规划
    if (currentProject.user_outline_plan && !userOutlinePlan) {
      setUserOutlinePlan(currentProject.user_outline_plan)
    }
  }, [currentProject])

  // 🆕 页面加载时恢复记忆快照
  useEffect(() => {
    if (!projectId) return

    const loadLatestMemory = async () => {
      try {
        const response = await apiClient.getLatestProjectMemory(Number(projectId))

        if (response.status >= 200 && response.status < 300) {
          const memory = response.data
          if (memory) {
            // 恢复对话历史
            if (memory.messages && Array.isArray(memory.messages)) {
              setConversationHistory(memory.messages)
            }
            // 恢复写作目标
            if (memory.writing_goal && !requirement) {
              setRequirement(memory.writing_goal)
            }
            // 更新最后保存时间
            if (memory.updated_at) {
              setLastSaveTime(new Date(memory.updated_at))
            }
          }
        }
      } catch {
        // 恢复记忆快照失败，使用默认状态
      }
    }

    loadLatestMemory()
  }, [projectId])

  // 🆕 计算基于时间权重的总体进度
  useEffect(() => {
    if (!stageDurations) return

    // 计算总预估时间
    const totalDuration = Object.values(stageDurations).reduce((sum, duration) => sum + duration, 0)

    // 计算已完成阶段的时间
    let completedDuration = 0
    stages.forEach((stage) => {
      const stageStatus = workflow.stages[stage].status
      if (stageStatus === 'completed') {
        completedDuration += stageDurations[stage]
      } else if (stageStatus === 'active' && stage === workflow.currentStage) {
        // 当前阶段的进度
        completedDuration += (stageDurations[stage] * taskProgress) / 100
      }
    })

    // 计算总体进度
    const overallProgress = Math.round((completedDuration / totalDuration) * 100)

    // 更新 Redux 状态
    if (overallProgress !== workflow.overallProgress) {
      dispatch({ type: 'workflow/updateOverallProgress', payload: overallProgress })
    }
  }, [stageDurations, workflow.stages, workflow.currentStage, taskProgress, dispatch])

  // 🆕 处理 Redux 状态（从 DashboardPage 跳转过来时）
  useEffect(() => {
    if (generateNextChapterTaskId) {
      setGeneratingNextChapter(true)
      setIsGenerateNextChapterFlow(true)
    } else {
      setGeneratingNextChapter(false)
      setIsGenerateNextChapterFlow(false)
    }
  }, [generateNextChapterTaskId, generateNextChapterNumber])

  // 🔥 监控Redux状态变化，调试按钮状态
  useEffect(() => {
    // 仅用于调试，可在此处设置断点
  }, [workflow.stages.concept.status, workflow.stages.concept.agents])

  // 🔥 关键修复：设置WebSocket加入房间后的回调，主动查询状态
  useEffect(() => {
    // 注册加入房间成功后的回调
    let isActive = true
    const activeProjectId = projectId ? Number(projectId) : null

    workflowWebSocket.setOnRoomJoined(async (joinedProjectId) => {
      if (!activeProjectId || activeProjectId !== joinedProjectId) {
        return
      }
      
      try {
        dispatch(fetchProject(activeProjectId))
        const response = await apiClient.getWorkflowAllStagesContent(activeProjectId)

        if (!isActive) {
          return
        }

        if (response.status < 200 || response.status >= 300) {
          return
        }

        const batchData = response.data
        const stages = batchData.stages || {}
        
        // 更新概念阶段状态
        if (stages.concept && stages.concept.trim()) {
          setConceptContent(stages.concept)
          dispatch(updateStageOutput({ stage: 'concept', output: stages.concept }))
          
          // 🔥 关键：如果有完整内容，说明阶段已完成，强制更新状态
          dispatch(updateStageStatus({ stage: 'concept', status: 'completed' }))
          
          // 更新所有Agent状态
          const currentState = store.getState()
          const conceptAgents = currentState.workflow.stages.concept.agents
          conceptAgents.forEach(agent => {
            dispatch(updateAgentStatus({
              stage: 'concept',
              agentId: agent.id,
              status: 'completed',
              progress: 100,
              message: '执行完成'
            }))
          })
          
          // 重置isRunning
          setIsRunning(false)
        }
        
        if (stages.world_setting) {
          setWorldContent(stages.world_setting)
        }
        
        setCharacterContent(stages.characters || '')
        
      } catch {
        // 查询失败，忽略
      }
    })
    
    // cleanup
    return () => {
      isActive = false
      workflowWebSocket.setOnRoomJoined(() => {})
    }
  }, [projectId, dispatch])

  // 🔌 WebSocket 连接管理
  useEffect(() => {
    if (!projectId) return

    // 连接 WebSocket （异步）
    const activeProjectId = Number(projectId)
    const isCurrentProjectEvent = (eventProjectId?: number) => Number(eventProjectId) === activeProjectId

    workflowWebSocket.connect().then(() => {
      workflowWebSocket.joinProject(activeProjectId)
    }).catch(() => {
      // WebSocket 连接失败，忽略
    })

    // 监听阶段更新
    workflowWebSocket.onStageUpdate((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      const stageType = data.stage as StageType

      // 更新 Redux 状态
      if (data.status === 'active') {
        dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

        // ✅ 临时方案：将该阶段的所有 Agent 设置为工作中
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          dispatch(updateAgentStatus({
            stage: stageType,
            agentId: agent.id,
            status: 'working',
            progress: 0,
            message: '执行中...'
          }))
        })
      } else if (data.status === 'completed') {
        // 🔥 关键修复：从Redux store直接读取最新状态，避免闭包问题
        const currentState = store.getState()
        const agents = currentState.workflow.stages[stageType].agents
        
        // 第一步：更新Redux状态（阶段状态）
        dispatch(updateStageStatus({ stage: stageType, status: 'completed' }))
        
        // 第二步：更新Redux状态（所有Agent状态）
        agents.forEach(agent => {
          dispatch(updateAgentStatus({
            stage: stageType,
            agentId: agent.id,
            status: 'completed',
            progress: 100,
            message: '执行完成'
          }))
        })
        
        // 🔥 关键修复：不要立即重置 isRunning，让 useEffect 自动执行逻辑来判断是否继续
        // 只有在概念阶段完成时才暂停（等待用户决策）
        if (stageType === 'concept') {
          setIsRunning(false)
        }

        // 第四步：同步更新 Redux store（如果有output）
        if (data.output) {
          dispatch(updateStageOutput({ stage: stageType, output: data.output }))
        }
        
        // 🔥 第五步：强制触发组件重新渲染（通过读取Redux最新状态）
        // 通过setTimeout确保Redux更新已经完成
        setTimeout(() => {
          // Redux状态验证
        }, 100)

        // 第六步：概念阶段完成 - 统一处理刷新与弹窗逻辑
        if (stageType === 'concept') {
          try {
            if (projectId) {
              dispatch(fetchProject(Number(projectId)))
              apiClient.getWorkflowAllStagesContent(Number(projectId)).then((response) => {
                if (response.status < 200 || response.status >= 300) {
                  throw new Error('load all stages failed')
                }
                const batchData = response.data
                const stages = batchData.stages || {}
                
                // 更新本地state
                if (stages.concept) {
                  setConceptContent(stages.concept)
                  // 同时更新Redux store
                  dispatch(updateStageOutput({ stage: 'concept', output: stages.concept }))
                }
                if (stages.world_setting) {
                  setWorldContent(stages.world_setting)
                }
                setCharacterContent(stages.characters || '')
                
                // 强制触发组件重新渲染
                setSelectedConceptView('concept')
                
                // 检查是否需要弹窗（仅在会话中首次）
                const hasConcept = !!(stages.concept && stages.concept.trim())
                if (hasConcept && !conceptDecisionShownThisSession) {
                  setDecisionReady(true)
                  setConceptDecisionShownThisSession(true)
                }
                
                // 数据刷新完成后，最终确认状态
                setTimeout(() => {
                  // 状态验证完成
                }, 200)
              }).catch(() => {
                // 即使刷新失败也要重置状态（概念阶段需要停止）
                setIsRunning(false)
              })
            }
          } catch {
            // 确保异常时也重置状态（概念阶段需要停止）
            setIsRunning(false)
          }
        } else {
          // 🔥 非概念阶段：也需要验证状态
          setTimeout(() => {
            // 状态验证完成
          }, 100)
        }

        if (data.output) {
          // 👁️ 防止重复更新：在第567-595行已经更新过一次，这里不再重复执行
          // dispatch(updateStageOutput({ stage: stageType, output: data.output }))

          // 🔥 关键修复：同步更新组件本地状态
          if (stageType === 'iteration') {
            setFinalVersionContent(data.output)
          } else if (stageType === 'review') {
            setReviewReportContent(data.output)
          } else if (stageType === 'content') {
            setContentDraftContent(data.output)
          }

          // 🆕 收集对话历史：将阶段输出添加到对话记录
          if (data.output) {
            const outputContent = data.output.substring(0, 2000) // 限制长度，避免数据过大
            setConversationHistory(prev => [
              ...prev,
              {
                role: 'assistant',
                content: outputContent,
                stage: stageType,
                timestamp: new Date().toISOString()
              }
            ])
          }
        }
      }

      // 更新进度
      if (data.progress !== undefined) {
        setTaskProgress(data.progress)

        // ✅ 临时方案：根据阶段进度更新 Agent 进度
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          if (agent.status === 'working') {
            dispatch(updateAgentStatus({
              stage: stageType,
              agentId: agent.id,
              status: 'working',
              progress: data.progress || 0,  // ✅ 添加默认值
              message: `进度: ${data.progress}%`
            }))
          }
        })
      }
    })

    // 监听任务进度
    workflowWebSocket.onTaskProgress((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        const progress = data.progress || 0

        // 🆕 根据进度计算当前步骤
        // 步骤1: 章节规划 (0-25%) -> structure
        // 步骤2: 内容创作 (25-50%) -> content
        // 步骤3: 质量评审 (50-75%) -> review
        // 步骤4: 迭代优化 (75-100%) -> iteration
        let currentStep = 1
        let targetStage: StageType = 'structure'
        if (progress < 25) {
          currentStep = 1
          targetStage = 'structure'
        } else if (progress < 50) {
          currentStep = 2
          targetStage = 'content'
        } else if (progress < 75) {
          currentStep = 3
          targetStage = 'review'
        } else {
          currentStep = 4
          targetStage = 'iteration'
        }

        // 使用 Redux action 更新进度和步骤
        dispatch(updateGenerateNextChapterProgress({ progress, currentStep }))

        // 切换工作流阶段
        dispatch(setCurrentStage(targetStage))

        setProgressMessage(
          data.message ||
          (currentStep === 4
            ? '正在内部改稿和复评，最终版本确认后会展示正文，请等待...'
            : '')
        )

        return  // 不更新普通任务进度
      }

      // 🆕 更新进度估算器的真实进度
      if (progressEstimator) {
        progressEstimator.updateRealProgress(data.progress)
      } else {
        // 如果没有进度估算器，直接设置进度
        setTaskProgress(data.progress)
      }

      if (data.message) {
        // 🆕 更新进度消息到 OutputPreviewPanel
        setProgressMessage(data.message)
        
        setSnackbarMessage(data.message)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)
      }
    })

    // 监听任务完成
    workflowWebSocket.onTaskComplete((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      const storyExpansionResult = getStoryExpansionResultFromTaskComplete(data)
      const completedResult = (
        data.result && typeof data.result === 'object' && !Array.isArray(data.result)
      )
        ? data.result as {
            chapter?: {
              chapter_number?: number
              title?: string
              word_count?: number
            }
            output?: string
          }
        : null

      // 🆕 处理协同拓展任务完成
      if (isStoryExpansionTaskId(data.task_id)) {
        const result = storyExpansionResult ?? {}
        if (projectId) {
          apiClient.getWorkflowAllStagesContent(Number(projectId)).then((response) => {
            if (response.status < 200 || response.status >= 300) {
              throw new Error('load all stages failed')
            }
            const batchData = response.data
            const stages = batchData.stages || {}
            if (stages.plot_outline) {
              setStructureContent(stages.plot_outline)
              dispatch(updateStageOutput({ stage: 'structure', output: stages.plot_outline }))
            }
            setCharacterContent(stages.characters || '')
          }).catch(() => {
            // 刷新协同拓展结果失败
          })

          dispatch(fetchChapters(parseInt(projectId)))
        }
        setSnackbarMessage(buildStoryExpansionCompletionMessage('协同拓展完成，已刷新大纲与人物内容', result))
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
        return
      }

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        // 🔥 关键修复：显式标记所有阶段为完成
        const allStages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
        allStages.forEach(stage => {
          dispatch(updateStageStatus({ stage, status: 'completed' }))
        })

        // 使用 Redux action 清除任务状态
        dispatch(completeGenerateNextChapter())
        setGeneratingNextChapter(false)
        
        // 🔥 关键修复：清除各阶段的进行中状态，避免卡在"生成中..."
        setIsRunning(false)
        // 注意：setCurrentStage 是 Redux action，不接受 null，保持当前阶段不变
        setCurrentTaskId(null)
        setTaskProgress(100)
        // 🆕 清空进度消息（任务完成）
        setProgressMessage('')
        
        // 停止进度估算器
        if (progressEstimator) {
          progressEstimator.complete()
        }

        // 提取章节信息
        const chapter = completedResult?.chapter
        if (chapter) {
          setSnackbarMessage(`🎉 第${chapter.chapter_number}章已生成：${chapter.title} (${chapter.word_count}字)`)
        } else {
          setSnackbarMessage('✅ 章节生成完成！')
        }
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 刷新章节列表
        if (projectId) {
          dispatch(fetchChapters(parseInt(projectId)))
        }
        return
      }

      // 🆕 完成进度估算器
      if (progressEstimator) {
        progressEstimator.complete()
      }

      // 🆕 清除任务状态
      setCurrentTaskId(null)
      setTaskProgress(100)

      // 🆕 尝试从 data 中提取阶段信息并更新 Redux
      // 注意：需要后端在 send_task_complete 中传递 stage 和 output
      if (completedResult) {
        const result = completedResult
        if (result.output) {
          // 如果后端传递了 stage 信息，可以在这里更新
          // dispatch(updateStageOutput({ stage: data.stage, output: result.output }))
        }
      }

      setSnackbarMessage('任务完成！')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    })

    // 监听任务错误
    workflowWebSocket.onTaskError((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        // 使用 Redux action 清除任务状态
        dispatch(completeGenerateNextChapter())
        setGeneratingNextChapter(false)

        setSnackbarMessage(`生成章节失败: ${data.error}`)
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      // 🆕 停止进度估算器
      if (progressEstimator) {
        progressEstimator.stop()
      }

      setCurrentTaskId(null)
      setTaskProgress(0)
      // 🆕 清空进度消息（任务失败）
      setProgressMessage('')

      setSnackbarMessage(`任务失败: ${data.error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)

      setIsRunning(false)
    })

    // 监听 Agent 状态
    workflowWebSocket.onAgentStatus((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      // ✅ 更新 Redux 状态
      // 尝试从 agent_id 或 agent_name 推断阶段
      let stage: StageType | null = isStageType(data.stage) ? data.stage : null
      const agentId = data.agent_id || data.agent_name.toLowerCase().replace(/\s+/g, '-')

      // 如果没有阶段信息，尝试从 agent_id 推断
      if (!stage) {
        // 根据 agent_id 推断阶段
        if (agentId.includes('creative') || agentId.includes('worldview') || agentId.includes('character') || agentId.includes('world') || agentId.includes('创意') || agentId.includes('世界') || agentId.includes('人物')) {
          stage = 'concept'
        } else if (agentId.includes('plot') || agentId.includes('event') || agentId.includes('情节')) {
          stage = 'structure'
        } else if (agentId.includes('content') || agentId.includes('style') || agentId.includes('内容') || agentId.includes('文风')) {
          stage = 'content'
        } else if (agentId.includes('quality') || agentId.includes('review') || agentId.includes('质量') || agentId.includes('评审')) {
          stage = 'review'
        } else if (agentId.includes('iteration') || agentId.includes('迭代')) {
          stage = 'iteration'
        } else {
          // 默认使用当前阶段
          stage = workflow.currentStage
        }
      }

      if (stage) {
        dispatch(updateAgentStatus({
          stage: stage,
          agentId: agentId,
          status: coerceAgentStatus(data.status),
          progress: data.progress || 0,
          message: data.message || ''
        }))
      }
    })

    // 🆕 监听流式输出开始（移除自动打开对话框，直接在主页面显示）
    workflowWebSocket.onStreamStart((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      setIsStreaming(true)
      setStreamingStage(data.stage as StageType)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 如果是"生成下一章"任务，清空临时流式内容（为新步骤准备）
      if (currentTaskId) {
        dispatch(clearGenerateNextChapterStream())  // 清空临时内容，准备接收新步骤的流式输出
      }

      // 🔄 只清空对应阶段的内容，不再自动打开对话框
      const stageType = data.stage as StageType
      if (stageType === 'content') {
        setContentDraftContent('')  // 清空缓存
        setEditedContentDraftContent('')  // 清空编辑内容
      } else if (stageType === 'review') {
        setReviewReportContent('')
        setEditedReviewReportContent('')
      } else if (stageType === 'iteration') {
        setFinalVersionContent('')
        setEditedFinalVersionContent('')
      }

      setSnackbarMessage(data.message || `${data.stage} 阶段开始生成内容...`)
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
    })

    // 🆕 监听流式输出块（打字机效果 - 直接在主页面的输出预览区显示）
    workflowWebSocket.onStreamChunk((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      const stageType = data.stage as StageType

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 如果是"生成下一章"任务，使用临时流式内容状态
      if (currentTaskId) {
        // 生成下一章模式：流式内容存入临时状态（不保存到数据库缓存）
        dispatch(appendGenerateNextChapterStream(data.chunk))
        return
      }

      // 🔄 普通模式：实时更新对应阶段的内容显示（仅更新缓存）
      if (stageType === 'concept') {
        // 根据target字段决定更新哪个状态
        if (data.extra && data.extra.target) {
          const target = data.extra.target
          
          // 🆕 自动切换视图：只在target变化时切换，避免频繁切换
          if (target !== selectedConceptView) {
            setSelectedConceptView(target as 'concept' | 'world' | 'character')
          }
          
          switch (target) {
            case 'concept':
              setConceptContent(prev => prev + data.chunk)
              break;
            case 'world':
              setWorldContent(prev => prev + data.chunk)
              break;
            case 'character':
              // 流式阶段先展示原始生成人物内容，便于用户实时查看进度；
              // 阶段完成后仍会由后端标准化落库结果覆盖，保证最终展示一致。
              setCharacterContent(prev => prev + data.chunk)
              break;
            default:
              setConceptContent(prev => prev + data.chunk)
          }
        } else {
          setConceptContent(prev => prev + data.chunk)
        }
      } else if (stageType === 'structure') {
        // 🆕 结构设计阶段：更新情节大纲
        setStructureContent(prev => prev + data.chunk)
      } else if (stageType === 'content') {
        setContentDraftContent(prev => prev + data.chunk)
      } else if (stageType === 'review') {
        setReviewReportContent(prev => prev + data.chunk)
      } else if (stageType === 'iteration') {
        setFinalVersionContent(prev => prev + data.chunk)
      }
    })

    // 🆕 监听流式输出结束
    workflowWebSocket.onStreamEnd((data) => {
      if (!isCurrentProjectEvent(data.project_id)) return

      setIsStreaming(false)
      setStreamingStage(null)
      // 🆕 清空进度消息（流式输出结束）
      setProgressMessage('')

      setSnackbarMessage(data.message || `${data.stage} 阶段内容生成完成，共 ${data.total_chars} 字`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    })

    // 🔔 组件卸载时：清除监听器，但不断开 WebSocket 连接
    return () => {
      // 🔔 修改：使用新方法，只移除监听器，不断开连接
      workflowWebSocket.removeEventListeners()  // ✅ 使用新方法
      workflowWebSocket.leaveProject(activeProjectId)
    }
  }, [projectId, dispatch])

  // 页面刷新时加载所有已保存的阶段内容和状态
  useEffect(() => {
    if (!projectId) return

    // 🔧 关键修复: 延迟执行，等待Token加载
    const requestedProjectId = Number(projectId)
    let isActive = true

    const timer = setTimeout(() => {
      const loadAllStageContents = async () => {
        try {

          // 🔧 关键修复：使用局部变量跟踪恢复状态，避免异步状态更新问题
          let hasRestoredRunningTask = false
          let restoredStage: StageType | null = null

          // 🔔 步骤1：检查是否有正在运行的任务
          try {
            const runningTasksResponse = await apiClient.getWorkflowRunningTasks(requestedProjectId)

            if (!isActive) {
              return
            }

            if (runningTasksResponse.status >= 200 && runningTasksResponse.status < 300) {
              const runningTasksData = runningTasksResponse.data
              const runningTasks = runningTasksData.running_tasks || []
              const timeoutTasks = runningTasksData.timeout_tasks || []

              // 🔧 新增：显示超时任务提示
              if (timeoutTasks.length > 0) {
                setSnackbarMessage(`⏰ 检测到 ${timeoutTasks.length} 个超时任务已被自动清理`)
                setSnackbarSeverity('warning')
                setSnackbarOpen(true)
              }

              if (runningTasks.length > 0) {

                // 恢复最新的任务
                const latestTask = runningTasks[0]
                const restoredTask = resolveRestoredRunningTask(latestTask)

                if (restoredTask?.kind === 'generate_next_chapter') {
                  const workflowState = store.getState().workflow.generateNextChapter
                  const existingTaskId = workflowState.taskId
                  const existingChapterNumber = workflowState.chapterNumber
                  const knownChapters = store.getState().editor.chapters || []
                  const restoredChapterNumber =
                    restoredTask.chapterNumber
                    ?? existingChapterNumber
                    ?? (knownChapters.reduce(
                      (maxChapter: number, chapter: { chapter_number?: number }) =>
                        Math.max(maxChapter, Number(chapter.chapter_number) || 0),
                      0,
                    ) + 1)

                  if (existingTaskId !== restoredTask.taskId) {
                    dispatch(startGenerateNextChapter({
                      taskId: restoredTask.taskId,
                      chapterNumber: restoredChapterNumber,
                    }))
                  }

                  setGeneratingNextChapter(true)
                  setIsGenerateNextChapterFlow(true)
                  hasRestoredRunningTask = true
                  restoredStage = 'structure'
                  dispatch(setCurrentStage('structure'))

                  setSnackbarMessage(`✅ 已恢复生成第${restoredChapterNumber}章（已运行${restoredTask.ageMinutes.toFixed(0)}分钟）`)
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                } else if (restoredTask?.kind === 'workflow_stage') {
                  const ageMinutes = restoredTask.ageMinutes
                  const stageType = restoredTask.stageType

                  setCurrentTaskId(restoredTask.taskId)
                  setIsRunning(true)
                  hasRestoredRunningTask = true
                  restoredStage = stageType

                  dispatch(setCurrentStage(stageType))
                  dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

                  if (!workflowWebSocket.isConnected()) {
                    pollTaskStatus(restoredTask.taskId, stageType)
                  }

                  setSnackbarMessage(`✅ 工作流已恢复，继续执行 ${stageNames[stageType]}（已运行${ageMinutes.toFixed(0)}分钟）`)
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                }
              } else {
                // 🔧 修复：如果没有正在运行的任务，确保停止运行状态
                setIsRunning(false)
                setCurrentTaskId(null)
                // 清理可能存在的轮询定时器
                if (taskPollingInterval) {
                  clearInterval(taskPollingInterval)
                  setTaskPollingInterval(null)
                }
                // 生成下一章完成后若错过 WebSocket，刷新时仍要拉回最新章节列表
                dispatch(fetchChapters(requestedProjectId))
              }
            }
          } catch {
            // 检查运行中任务失败
          }

          // ⚡ 步骤2：性能优化: 使用批量接口一次性获取所有阶段内容
          const batchResponse = await apiClient.getWorkflowAllStagesContent(requestedProjectId)

          if (!isActive) {
            return
          }

          if (batchResponse.status >= 200 && batchResponse.status < 300) {
            const batchData = batchResponse.data
            const stages = batchData.stages || {}

            setConceptContent(stages.concept || '')
            setWorldContent(stages.world_setting || '')
            setCharacterContent(stages.characters || '')
            setStructureContent(stages.plot_outline || '')
            setContentDraftContent(stages.chapter_draft || '')
            setReviewReportContent(stages.review_report || '')
            setFinalVersionContent(stages.final_version || '')

            dispatch(updateStageOutput({ stage: 'concept', output: stages.concept || '' }))
            dispatch(updateStageOutput({ stage: 'structure', output: stages.plot_outline || '' }))
            dispatch(updateStageOutput({ stage: 'content', output: stages.chapter_draft || '' }))
            dispatch(updateStageOutput({ stage: 'review', output: stages.review_report || '' }))
            dispatch(updateStageOutput({ stage: 'iteration', output: stages.final_version || '' }))

            // 设置所有按钮内容

            // 更新Redux store的output字段，用于输出预览显示
          } else {
            // 备用方案: 使用原有的分别请求方式
            // 这里可以保留原有代码逻辑
          }

          if (isActive) {
            await refreshWorkflowReviewMeta(requestedProjectId)
          }

          // 加载阶段状态
          try {
            const statusResponse = await apiClient.getWorkflowStageStatus(requestedProjectId)

            if (!isActive) {
              return
            }

            if (statusResponse.status >= 200 && statusResponse.status < 300) {
              const statusData = statusResponse.data

              // 更新Redux store中的阶段状态
              const stageStatusMap: Record<string, StageType> = {
                'stage_one_status': 'concept',
                'stage_two_status': 'structure',
                'stage_three_status': 'content',
                'stage_four_status': 'review',
                'stage_five_status': 'iteration'
              }

              // 🔧 修复：根据后端状态确定当前应该显示的阶段
              let lastCompletedStage: StageType | null = null

              Object.entries(stageStatusMap).forEach(([dbField, stageName]) => {
                const status = statusData[dbField]
                if (status === 'completed') {
                  // 🔧 关键修复：如果该阶段正在运行，不要覆盖为 completed
                  if (hasRestoredRunningTask && stageName === restoredStage) {
                    // 保持 active 状态，不更新为 completed
                  } else {
                    dispatch(updateStageStatus({ stage: stageName, status: 'completed' }))
                    lastCompletedStage = stageName
                  }
                }
              })

              // 🔧 关键修复：使用局部变量判断，避免 React 状态异步更新问题
              // 如果已经恢复了运行中的任务，就不要再设置当前阶段了
              if (hasRestoredRunningTask) {
              } else {
                // 🆕 从 Redux 读取"生成下一章"任务状态（关键：避免闭包中的旧值）
                const reduxState = store.getState()
                const generateNextChapterTaskId = reduxState.workflow.generateNextChapter.taskId
                const isGeneratingNextChapter = reduxState.workflow.generateNextChapter.isRunning

                // 🆕 如果正在执行"生成下一章"任务，设置为 structure 阶段（章节规划从这里开始）
                if (generateNextChapterTaskId || isGeneratingNextChapter) {
                  dispatch(setCurrentStage('structure'))
                } else if (lastCompletedStage) {
                  // 🔧 关键修复：刷新时保持在最后完成的阶段，不要跳转到下一阶段
                  dispatch(setCurrentStage(lastCompletedStage))
                } else {
                  // 没有完成的阶段,显示第一个阶段
                  dispatch(setCurrentStage('concept'))
                }
              }
            }
          } catch {
            // 加载阶段状态失败
          }

        } catch {
          // 加载阶段内容失败
          // 不显示错误提示，避免干扰用户体验
        }
      }

      loadAllStageContents()
    }, 100)  // 🔧 延迟100ms，等待localStorage初始化

    // 🔧 清理定时器
    return () => {
      isActive = false
      clearTimeout(timer)
    }
  }, [projectId, dispatch])

  // 🆕 自动执行阶段的逻辑（异步模式）
  useEffect(() => {
    if (!isRunning || !projectId) return

    // 如果当前有异步任务正在执行，跳过
    if (currentTaskId) {
      return
    }

    // 检查当前阶段是否已完成
    const currentStageData = workflow.stages[workflow.currentStage]

    if (currentStageData.status === 'pending') {
      executeStageAsync(workflow.currentStage)
    } else if (currentStageData.status === 'completed') {
      // 当前阶段已完成 - 检查是否需要执行下一阶段
      if (workflow.currentStage === 'concept') {
        // 概念阶段完成后暂停自动推进，等待用户决策（通过 decisionReady 状态控制）
        setIsRunning(false)
        return
      }
      const currentIndex = stages.indexOf(workflow.currentStage)
      if (currentIndex < stages.length - 1) {
        // 移动到下一阶段
        const nextStage = stages[currentIndex + 1]
        dispatch(setCurrentStage(nextStage))
        // 注意：不在这里执行，等待下次useEffect触发时执行
      } else {
        // 所有阶段都已完成
        setIsRunning(false)

        // 🔧 关键修复：只有在“非生成下一章”流程才自动保存
        if (isGenerateNextChapterFlow) {
          // 重置标记
          setIsGenerateNextChapterFlow(false)
          // 直接跳转
          setTimeout(() => {
            navigate(`/dashboard?projectId=${projectId}`)
          }, 1500)
        } else {
          // 普通工作流，需要自动保存
          autoSaveChapter()
        }
      }
    }
  }, [isRunning, workflow.currentStage, workflow.stages, currentTaskId, projectId, dispatch])

  // 🆕 概念阶段决策弹窗在 WebSocket 完成事件中控制（刷新不弹）

  // 🆕 清理轮询定时器
  useEffect(() => {
    return () => {
      if (taskPollingInterval) {
        clearInterval(taskPollingInterval)
      }
    }
  }, [taskPollingInterval])

  // 🆕 自动保存记忆功能
  useEffect(() => {
    if (!autoSaveEnabled || !projectId) return

    // 每5分钟自动保存一次
    const interval = setInterval(() => {
      saveMemorySnapshot('auto')
    }, 5 * 60 * 1000) // 5分钟

    return () => {
      clearInterval(interval)
    }
  }, [autoSaveEnabled, projectId])

  // 🆕 页面卸载前保存记忆（使用 sendBeacon 确保请求完成）
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (autoSaveEnabled && projectId && conversationHistory.length > 0) {
        // 使用 navigator.sendBeacon 确保页面卸载时请求能完成
        const memoryData = {
          messages: conversationHistory,
          current_chapter: workflow.stages.iteration.output ? 1 : null,
          current_scene: workflow.currentStage,
          active_characters: [],
          writing_goal: requirement || '创作小说',
        }

        const blob = new Blob([JSON.stringify(memoryData)], { type: 'application/json' })
        const token = localStorage.getItem('access_token')

        // sendBeacon 不支持自定义 headers，需要通过 URL 参数传递 token
        // 或者使用特殊的 endpoint 来处理
        const url = `/api/v1/projects/${projectId}/memories/auto-save?token=${token}`
        navigator.sendBeacon(url, blob)
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [autoSaveEnabled, projectId, conversationHistory, workflow, requirement])

  // 🆕 保存记忆快照函数
  const saveMemorySnapshot = async (trigger: 'auto' | 'stage' | 'beforeUnload' | 'manual') => {
    if (!projectId) return

    try {
      // 收集当前工作流状态数据
      const memoryData = {
        messages: conversationHistory,
        current_chapter: workflow.stages.iteration.output ? 1 : null,
        current_scene: workflow.currentStage,
        active_characters: [],
        writing_goal: requirement || '创作小说',
      }

      const response = await apiClient.saveProjectMemorySnapshot(Number(projectId), memoryData)

      if (response.status >= 200 && response.status < 300) {
        const savedMemory = response.data
        setLastSaveTime(new Date(savedMemory.updated_at))

        // 仅在手动保存时显示提示
        if (trigger === 'manual') {
          setSnackbarMessage('✅ 记忆快照已保存')
          setSnackbarSeverity('success')
          setSnackbarOpen(true)
        }
      }
    } catch {
      // 保存记忆快照异常
    }
  }

  // 🆕 异步执行阶段函数
  const executeStageAsync = async (
    stage: StageType,
    options: { manualMultiModelReview?: boolean; manualMultiModelReviewPreset?: ReviewPreset } = {},
  ) => {
    if (!projectId) return

    try {
      // 🔧 立即更新阶段状态为 'active'，显示执行中的UI
      dispatch(updateStageStatus({ stage, status: 'active' }))

      // 🆕 收集用户输入到对话历史
      const stageNames: Record<string, string> = {
        concept: '概念开发',
        structure: '结构设计',
        content: '内容创作',
        review: '质量评审',
        iteration: '迭代优化'
      }
      setConversationHistory(prev => [
        ...prev,
        {
          role: 'user',
          content: `执行${stageNames[stage] || stage}阶段: ${requirement || '创作小说'}`,
          stage: stage,
          timestamp: new Date().toISOString()
        }
      ])

      // 🆕 阶段开始前保存记忆（确保意外关闭时写作目标不丢失）
      saveMemorySnapshot('stage')

      // 🆕 检查是否是支持流式输出的阶段
      const streamingStages = ['concept', 'structure', 'content', 'review', 'iteration']
      const enableStreaming = streamingStages.includes(stage)

      // 🆕 流式输出阶段：清空之前的内容，准备接收流式数据
      if (enableStreaming) {
        if (stage === 'concept') {
          setConceptContent('')
          setWorldContent('')
          setCharacterContent('')
        } else if (stage === 'structure') {
          setStructureContent('')
        } else if (stage === 'content') {
          setContentDraftContent('')
        } else if (stage === 'review') {
          setReviewReportContent('')
        } else if (stage === 'iteration') {
          setFinalVersionContent('')
        }
      }


      const response = await apiClient.postWorkflowStageAsync({
        projectId: parseInt(projectId),
        stage,
        requirement: requirement || '创作一部小说',
        workflowGenerationModel,
        enableStreaming,
        manualMultiModelReview: options.manualMultiModelReview,
        manualMultiModelReviewPreset: options.manualMultiModelReviewPreset,
      })

      if (response.status < 200 || response.status >= 300) {
        const errorData = response.data as { detail?: string; error?: string } | undefined
        throw new Error(errorData?.detail || errorData?.error || ('提交任务失败: ' + response.status))
      }

      const data = response.data
      const taskId = data.task_id

      if (!taskId) {
        throw new Error('未返回task_id')
      }

      setCurrentTaskId(taskId)
      setTaskProgress(0)

      // 🆕 启动进度估算器
      if (progressEstimator) {
        progressEstimator.startStage(stage, (state: ProgressState) => {
          setEstimatedRemainingTime(Math.round(state.remainingTime))
          setEstimatedRemainingTimeMin(Math.round(state.remainingTimeMin))  // 🆕
          setEstimatedRemainingTimeMax(Math.round(state.remainingTimeMax))  // 🆕
          setTaskProgress(Math.round(state.displayProgress))
        })
      }

      // 🆕 检查 WebSocket 是否连接
      if (workflowWebSocket.isConnected()) {
        // 依赖 WebSocket 事件监听器，不启动轮询
      } else {
        // WebSocket 不可用时启动轮询
        pollTaskStatus(taskId, stage)
      }
    } catch {
      // 🔧 失败时重置状态
      dispatch(updateStageStatus({ stage, status: 'error' }))
      setSnackbarMessage(`执行${stageNames[stage]}失败，请重试`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }



  // 🆕 轮询任务状态函数
  const pollTaskStatus = (taskId: string, stage: StageType) => {
    let pollCount = 0
    const maxPolls = 180
    let consecutiveErrors = 0  // 🔧 记录连续错误次数
    const maxConsecutiveErrors = 5  // 连续5次404后停止轮询

    const interval = setInterval(async () => {
      try {
        pollCount++

        const response = await apiClient.getWorkflowTaskStatus(taskId)

        if (response.status < 200 || response.status >= 300) {
          // 🔧 处理404错误
          if (response.status === 404) {
            consecutiveErrors++

            if (consecutiveErrors >= maxConsecutiveErrors) {
              clearInterval(interval)
              setTaskPollingInterval(null)
              setTaskProgress(0)
              setCurrentTaskId(null)

              dispatch(updateStageStatus({ stage, status: 'error' }))

              setSnackbarMessage(`❌ 任务查询失败：后端未找到任务，请检查后端服务是否正常`)
              setSnackbarSeverity('error')
              setSnackbarOpen(true)

              return
            }
            // 继续轮询，等待后端任务初始化
            return
          }

          throw new Error(`查询任务状态失败: ${response.status}`)
        }

        // 🔧 成功响应，重置错误计数
        consecutiveErrors = 0

        const data = response.data

        const progress = Math.min(95, pollCount * 3)
        setTaskProgress(progress)

        if (data.status === 'completed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(100)
          setCurrentTaskId(null)

          if (stage === 'concept' && projectId) {
            dispatch(fetchProject(Number(projectId)))
          }

          dispatch(updateStageStatus({ stage, status: 'completed' }))
          dispatch(updateStageOutput({ stage, output: data.result || '' }))

          // 🔥 关键修复：同步更新组件本地状态（轮询模式）
          const resultContent = data.result || ''
          if (stage === 'iteration' && resultContent) {
            setFinalVersionContent(resultContent)
          } else if (stage === 'review' && resultContent) {
            setReviewReportContent(resultContent)
          } else if (stage === 'content' && resultContent) {
            setContentDraftContent(resultContent)
          }

          setSnackbarMessage(`✅ ${stageNames[stage]}完成！`)
          setSnackbarSeverity('success')
          setSnackbarOpen(true)

          // 🆕 阶段完成后自动保存记忆
          if (autoSaveEnabled) {
            saveMemorySnapshot('stage')
          }

          if (isRunning) {
            const currentIndex = stages.indexOf(stage)
            if (currentIndex < stages.length - 1) {
              const nextStage = stages[currentIndex + 1]
              dispatch(setCurrentStage(nextStage))
              // 继续下一阶段
              setTimeout(() => {
                executeStageAsync(nextStage)
              }, 1000)
            } else {
              setIsRunning(false)

              // 🔧 关键修复：只有在“非生成下一章”流程才自动保存
              if (isGenerateNextChapterFlow) {
                // 重置标记
                setIsGenerateNextChapterFlow(false)
                // 直接跳转
                setTimeout(() => {
                  navigate(`/dashboard?projectId=${projectId}`)
                }, 1500)
              } else {
                // 普通工作流，需要自动保存
                autoSaveChapter()
              }
            }
          }
        } else if (data.status === 'failed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ ${stageNames[stage]}失败: ${data.error || '未知错误'}`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)

          setIsRunning(false)
        } else if (pollCount >= maxPolls) {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ ${stageNames[stage]}超时，请重试`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)

          setIsRunning(false)
        }
      } catch {
        // 🔧 其他错误也计入连续错误
        consecutiveErrors++

        if (consecutiveErrors >= maxConsecutiveErrors) {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ 轮询失败，请重试`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)
        }
      }
    }, 2000)

    setTaskPollingInterval(interval)
  }

  // 🆕 标记是否是重新开始（需要清空旧数据）
  const [isRestartMode, setIsRestartMode] = useState(false)

  // 🆕 确认重新开始（覆盖现有内容）
  const handleConfirmRestart = () => {
    setShowContentWarningDialog(false)
    setIsRestartMode(true)  // 🆕 标记为重新开始模式
    setOpenDialog(true)
  }

  // 🆕 选择继续创作下一章
  const handleContinueNextChapter = () => {
    setShowContentWarningDialog(false)
    handleGenerateNextChapter()
  }

  // 🆕 免费生成下一章（服务端强制 qwen3.7-flash，每日限额）
  const handleContinueNextChapterFree = () => {
    setShowContentWarningDialog(false)
    handleGenerateNextChapter('free')
  }

  const handleStartWorkflow = async () => {
    if (!projectId || !requirement.trim()) {
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('请输入创作需求')
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
      return
    }

    try {
      setIsStarting(true)  // 开始启动，显示加载状态
      
      // 🆕 先更新项目的题材与篇幅信息
      if (genre || plannedLengthType || userOutlinePlan) {
        try {
          await apiClient.updateProject(parseInt(projectId), {
            genre,
            sub_genre: subGenre,
            planned_length_type: plannedLengthType,
            planned_chapters_min: plannedChaptersMin || undefined,
            planned_chapters_max: plannedChaptersMax || undefined,
            user_outline_plan: userOutlinePlan || undefined,
          })
        } catch {
          // 更新项目信息失败
        }
      }
      
      await dispatch(
        startWorkflow({
          projectId: parseInt(projectId),
          requirement,
          workflowGenerationModel,
          clearExisting: isRestartMode,  // 🆕 传递清空标志
        })
      ).unwrap()
      setCurrentTaskId(null)
      setTaskProgress(0)
      setTaskPollingInterval((currentInterval) => {
        if (currentInterval) {
          clearInterval(currentInterval)
        }
        return null
      })
      setOpenDialog(false)
      setIsRunning(true)
      setIsStarting(false)  // 启动完成，隐藏加载状态
      setIsRestartMode(false)  // 🆕 重置重新开始标志

      // 🆕 如果是重新开始模式，刷新章节列表
      if (isRestartMode) {
        dispatch(fetchChapters(parseInt(projectId)))
        setSnackbarMessage('已清空旧内容，开始全新创作')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      }
    } catch {
      setIsStarting(false)  // 启动失败，隐藏加载状态
      setIsRestartMode(false)  // 🆕 重置重新开始标志
      setSnackbarMessage('启动工作流失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  const handleRegenerateStage = async () => {
    if (!projectId) return

    try {
      await dispatch(
        regenerateStage({
          projectId: parseInt(projectId),
          stage: workflow.currentStage,
        })
      ).unwrap()
    } catch {
      // 重新生成阶段失败
    }
  }

  // 🆕 概念阶段：提交重生成（携带目标、反馈），并避免触发人物
  // 注意：此函数已被移至第2396行，此处为重复声明已删除

  const handleNextStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex < stages.length - 1) {
      dispatch(setCurrentStage(stages[currentIndex + 1]))
    }
  }

  const handlePreviousStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex > 0) {
      dispatch(setCurrentStage(stages[currentIndex - 1]))
    }
  }

  const handleSaveAsChapter = async () => {
    if (!projectId) {
      setSnackbarMessage('项目ID不存在')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    // ✅ 设置保存状态
    setSavingChapter(true)

    try {
      // 🔥 关键修复：从后端API获取最新的迭代阶段内容 - 使用apiClient
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)

      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        setSnackbarMessage('没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setSavingChapter(false)  // ✅ 重置保存状态
        return
      }

      // 如果用户没有输入标题，后端会自动生成
      const titleToSave = chapterTitle.trim() || ''

      const numericProjectId = parseInt(projectId)
      const response = await apiClient.createChapter(numericProjectId, {
        content,
        title: titleToSave || undefined, // 如果为空则自动生成
      })

      // axios成功响应（2xx状态码）
      const data = response.data

      setSnackbarMessage(`✅ 章节已保存：${data.title} (${data.word_count} 字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 关闭对话框，清空标题
      setShowSaveDialog(false)
      setChapterTitle('')

      // 🔧 修复：1.5秒后跳转到Dashboard页面，并自动展开章节列表
      setTimeout(() => {
        navigate(`/dashboard?projectId=${projectId}`)  // 带projectId参数，自动展开章节列表
      }, 1500)
    } catch (error: any) {
      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = await extractApiErrorMessage(error, errorMessage)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会重置保存状态
      setSavingChapter(false)
    }
  }

  // 🆕 自动保存章节（无需用户输入标题）
  const autoSaveChapter = async () => {
    if (!projectId) {
      return
    }

    try {
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)
      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        setSnackbarMessage('⚠️ 没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const numericProjectId = parseInt(projectId)
      const chaptersResponse = await apiClient.getChapters(numericProjectId)
      const existingChapters = Array.isArray(chaptersResponse.data) ? chaptersResponse.data : []
      const latestChapter = selectLatestChapterForOverwrite(existingChapters)

      const response = latestChapter?.id
        ? await apiClient.updateChapter(latestChapter.id, { content })
        : await apiClient.createChapter(numericProjectId, { content })

      const data = response.data
      setSnackbarMessage(
        latestChapter?.id
          ? `✅ 已覆盖第${data.chapter_number ?? latestChapter.chapter_number}章：${data.title} (${data.word_count} 字)`
          : `✅ 章节已自动保存：${data.title} (${data.word_count} 字)`
      )
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      dispatch(fetchChapters(numericProjectId))

      setTimeout(() => {
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1500)

    } catch (error: any) {
      let errorMessage = '自动保存失败'

      if (error.response) {
        errorMessage = await extractApiErrorMessage(error, errorMessage)
      } else if (error.request) {
        errorMessage = '无法连接到服务器'
      }

      setSnackbarMessage(`❌ ${errorMessage}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  const getWorkflowStageContent = async (stage: 'structure' | 'content' | 'review' | 'iteration') => {
    if (!projectId) return null

    const response = await apiClient.getWorkflowStageContent(Number(projectId), stage)
    if (response.status < 200 || response.status >= 300) {
      return null
    }

    return response.data as { content?: string }
  }

  const saveWorkflowStageContent = async (
    stage: 'structure' | 'content' | 'review',
    content: string,
    continueWorkflow: boolean,
  ) => {
    if (!projectId) return null

    const response = await apiClient.updateWorkflowStageContent(Number(projectId), stage, {
      content,
      continue_workflow: continueWorkflow,
    })

    return response
  }

  // 🆕 点击故事概念按钮 - 切换预览区域显示
  const handleOpenConceptDialog = () => {
    setSelectedConceptView('concept')
  }

  // 打开情节大纲对话框
  const handleOpenStructureDialog = async () => {
    setShowStructureDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (structureContent && structureContent.trim() !== '') {
      setEditedStructureContent(structureContent)
      return
    }

    // 如果没有缓存，才从API获取
    setStructureLoading(true)

    try {
      const data = await getWorkflowStageContent('structure')
      if (data) {
        setStructureContent(data.content || '')
        setEditedStructureContent(data.content || '')
      } else {
        setSnackbarMessage('获取情节大纲失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('获取情节大纲失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureLoading(false)
    }
  }

  // 关闭情节大纲对话框
  const handleCloseStructureDialog = () => {
    setShowStructureDialog(false)
    // 不清空 structureContent，保持已保存的内容
    setEditedStructureContent('')  // 只清空编辑状态
  }

  // 保存并继续（情节大纲）

  // 仅保存（情节大纲）
  const handleSaveOnlyStructure = async () => {
    if (!projectId) return

    setStructureSaving(true)

    try {
      const response = await saveWorkflowStageContent('structure', editedStructureContent, false)

      if (response && response.status >= 200 && response.status < 300) {
        // ✅ 更新state，保持已保存的内容
        setStructureContent(editedStructureContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseStructureDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureSaving(false)
    }
  }

  // 打开章节初稿对话框
  const handleOpenContentDialog = async () => {
    setShowContentDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (contentDraftContent && contentDraftContent.trim() !== '') {
      setEditedContentDraftContent(contentDraftContent)
      return
    }

    // 如果没有缓存，才从API获取
    setContentLoading(true)

    try {
      const data = await getWorkflowStageContent('content')
      if (data) {
        const content = data.content || ''
        setContentDraftContent(content)
        setEditedContentDraftContent(content)
      } else {
        setSnackbarMessage('获取章节初稿失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('获取章节初稿失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentLoading(false)
    }
  }

  // 关闭章节初稿对话框
  const handleCloseContentDialog = () => {
    setShowContentDialog(false)
    // 不清空 contentDraftContent，保持已保存的内容
    setEditedContentDraftContent('')  // 只清空编辑状态
  }

  // 打开评审报告对话框
  const handleOpenReviewDialog = async () => {
    setShowReviewDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (reviewReportContent && reviewReportContent.trim() !== '') {
      setEditedReviewReportContent(reviewReportContent)
      return
    }

    // 如果没有缓存，才从API获取
    setReviewLoading(true)

    try {
      const data = await getWorkflowStageContent('review')
      if (data) {
        const content = data.content || ''
        setReviewReportContent(content)
        setEditedReviewReportContent(content)
      } else {
        setSnackbarMessage('获取评审报告失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('获取评审报告失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewLoading(false)
    }
  }

  // 关闭评审报告对话框
  const handleCloseReviewDialog = () => {
    setShowReviewDialog(false)
    setEditedReviewReportContent('')  // 清空编辑状态
  }

  const handleReviewSettingsSaved = async () => {
    setSnackbarMessage('评审设置已保存')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
    if (projectId) {
      await refreshWorkflowReviewMeta(Number(projectId))
    }
  }

  const handleManualMultiModelReview = () => {
    if (!projectId || isRunning || isStarting || generatingNextChapter) return
    setManualReviewPreset('key_chapter_5')
    setShowManualReviewDialog(true)
  }

  const handleConfirmManualMultiModelReview = () => {
    if (!projectId || isRunning || isStarting || generatingNextChapter) return
    setShowManualReviewDialog(false)
    setReviewReportContent('')
    setEditedReviewReportContent('')
    setReviewMeta(null)
    dispatch(setCurrentStage('review'))
    setIsRunning(true)
    void executeStageAsync('review', {
      manualMultiModelReview: true,
      manualMultiModelReviewPreset: manualReviewPreset,
    })
  }

  // 仅保存评审报告
  const handleSaveOnlyReview = async () => {
    if (!projectId) return

    setReviewSaving(true)

    try {
      const response = await saveWorkflowStageContent('review', editedReviewReportContent, false)

      if (response && response.status >= 200 && response.status < 300) {
        // 更新缓存
        setReviewReportContent(editedReviewReportContent)
        setSnackbarMessage('评审报告已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        const errorData = response?.data || {}
        setSnackbarMessage(errorData.detail || '保存失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('保存评审报告失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewSaving(false)
    }
  }

  // 保存并继续（评审报告）
  const handleSaveAndContinueReview = async () => {
    if (!projectId) return

    setReviewSaving(true)

    try {
      // 1. 保存内容并指示继续工作流
      const saveResponse = await saveWorkflowStageContent('review', editedReviewReportContent, true)

      if (!saveResponse || saveResponse.status < 200 || saveResponse.status >= 300) {
        const errorData = saveResponse?.data || {}
        setSnackbarMessage(errorData.detail || '保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = saveResponse.data || {}

      // ✅ 更新缓存
      setReviewReportContent(editedReviewReportContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'review', output: editedReviewReportContent }))
      dispatch(updateStageStatus({ stage: 'review', status: 'completed' }))

      // ✅ 重置后续阶段状态
      dispatch(resetFollowingStages('review'))

      setSnackbarMessage('评审报告已保存，正在按评审意见改写当前最后一章（完成后覆盖旧稿，不新建章节）')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      if (saveData.task_id) {
        setCurrentTaskId(saveData.task_id)
      }

      handleCloseReviewDialog()

      // ✅ 关键修复：后端已经启动后台任务，前端只需设置isRunning=true等待WebSocket更新
      setIsRunning(true)
      dispatch(setCurrentStage('iteration'))
    } catch {
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewSaving(false)
    }
  }

  // 保存并继续（章节初稿）
  const handleSaveAndContinueContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      // 1. 保存内容并指示继续工作流
      const saveResponse = await saveWorkflowStageContent('content', editedContentDraftContent, true)

      if (!saveResponse || saveResponse.status < 200 || saveResponse.status >= 300) {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = saveResponse.data || {}

      // ✅ 更新state，保持已保存的内容
      setContentDraftContent(editedContentDraftContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'content', output: editedContentDraftContent }))
      dispatch(updateStageStatus({ stage: 'content', status: 'completed' }))

      // ✅ 关键修复：重置后续阶段状态
      dispatch(resetFollowingStages('content'))

      const updatedChapter = saveData.updated_chapter || saveData.deleted_chapter
      if (updatedChapter) {
        setSnackbarMessage(`已更新第${updatedChapter.chapter_number}章并启动后续评审（不会清空前面章节）`)
      } else {
        setSnackbarMessage('内容已保存，正在启动后续评审...')
      }

      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      if (saveData.task_id) {
        setCurrentTaskId(saveData.task_id)
      }

      handleCloseContentDialog()

      // ✅ 关键修复：后端已经启动后台任务，前端只需设置isRunning=true等待WebSocket更新
      setIsRunning(true)
      dispatch(setCurrentStage('review'))
    } catch {
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }


  // 仅保存（章节初稿）
  const handleSaveOnlyContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      const response = await saveWorkflowStageContent('content', editedContentDraftContent, false)

      if (response && response.status >= 200 && response.status < 300) {
        // ✅ 更新state，保持已保存的内容
        setContentDraftContent(editedContentDraftContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseContentDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }

  // 🆕 点击世界观设定按钮 - 切换预览区域显示
  const handleOpenWorldDialog = () => {
    setSelectedConceptView('world')
  }

  // 🆕 点击人物设定按钮 - 切换预览区域显示
  const handleOpenCharacterDialog = () => {
    setSelectedConceptView('character')
  }

  // 打开最终版本对话框
  const handleOpenFinalProduct = async () => {
    setShowFinalVersionDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (finalVersionContent && finalVersionContent.trim() !== '') {
      setEditedFinalVersionContent(finalVersionContent)
      return
    }

    // 如果没有缓存，才从API获取
    setFinalVersionLoading(true)

    try {
      const data = await getWorkflowStageContent('iteration')
      if (data) {
        const content = data.content || ''
        setFinalVersionContent(content)
        setEditedFinalVersionContent(content)
      } else {
        setSnackbarMessage('获取最终版本失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch {
      setSnackbarMessage('获取最终版本失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setFinalVersionLoading(false)
    }
  }

  // 生成下一章（方案3：独立的章节生成工作流）
  // 🆕 tier='free' 时走免费档（服务端强制 qwen3.7-flash，每日限额）
  const handleGenerateNextChapter = async (tier: 'free' | 'standard' = 'standard') => {
    if (!projectId) return

    setGeneratingNextChapter(true)

    try {
      const response = await apiClient.generateNextWorkflowChapter(
        Number(projectId),
        tier === 'free'
          ? { generationTier: 'free' }
          : { workflowGenerationModel, generationTier: 'standard' }
      )

      if (response.status >= 200 && response.status < 300) {
        const data = response.data

        // 后端返回: { task_id, status, message, next_chapter_number, remaining_quota?, quota_reset_at? }
        const { task_id, next_chapter_number, remaining_quota } = data
        if (tier === 'free' && typeof remaining_quota === 'number') {
          setFreeQuota((current) => ({
            remaining: remaining_quota,
            resetAt: data.quota_reset_at || current?.resetAt || '',
            globalAvailable: current?.globalAvailable ?? true,
          }))
        }

        // 🆕 使用 Redux action 设置任务状态
        dispatch(startGenerateNextChapter({ taskId: task_id, chapterNumber: next_chapter_number }))
        setIsGenerateNextChapterFlow(true)

        // 🆕 免费档展示剩余额度
        const quotaSuffix = typeof remaining_quota === 'number' ? `（今日免费额度剩余 ${remaining_quota} 次）` : ''
        setSnackbarMessage(`🚀 已开始生成第${next_chapter_number}章，请等待...${quotaSuffix}`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 注意：不再设置 setGeneratingNextChapter(false)，等待 WebSocket 完成事件
      } else {
        const errorData = response.data || {}
        // 🆕 detail 可能是字符串（404/409/503）或对象（429 带剩余额度与重置时间）
        const detail = errorData.detail
        const detailMessage = typeof detail === 'string' ? detail : detail?.message

        let message = detailMessage || errorData.error || '创建生成任务失败，请重试'
        if (response.status === 429 && typeof detail === 'object' && detail?.reset_at) {
          const resetTime = new Date(detail.reset_at)
          const resetText = Number.isNaN(resetTime.getTime())
            ? detail.reset_at
            : resetTime.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
          message = `${detailMessage || '今日免费生成额度已用完'}，${resetText} 重置`
        } else if (response.status === 409) {
          message = detailMessage || '该项目已有生成任务进行中，请等待完成后再试'
        } else if (response.status === 503) {
          message = detailMessage || '生成服务暂不可用，请稍后再试'
        }

        setSnackbarMessage(message)
        setSnackbarSeverity(response.status === 429 ? 'warning' : 'error')
        setSnackbarOpen(true)
        setGeneratingNextChapter(false)
      }
    } catch {
      setSnackbarMessage('创建生成任务失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      setGeneratingNextChapter(false)
    }
  }

  // 🆕 概念阶段：提交重新生成（仅故事概念/世界观/两者）
  const handleSubmitRegenerateConcept = async () => {
    if (!projectId) return
    if (workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')) {
      setSnackbarMessage('概念阶段执行中，请稍后再试')
      setSnackbarSeverity('warning')
      setSnackbarOpen(true)
      return
    }
    try {
      setShowRegenerateDialog(false)
      setShowDecisionDialog(false)
      // 保持评审按钮可见，显示状态
      setIsRunning(true)
      const targets = regenerateTarget === 'both' ? ['story','world'] : (regenerateTarget === 'story' ? ['story'] : ['world'])
      const feedbackText = (regenerateFeedback && regenerateFeedback.trim()) ? regenerateFeedback : (autoInferFeedback ? '根据当前预览内容进行轻微优化，增强题材适配性与逻辑一致性' : '')
      const response = await apiClient.postWorkflowStageAsync({
        projectId: parseInt(projectId),
        stage: 'concept',
        workflowGenerationModel,
        regenerate: true,
        targets,
        feedback: feedbackText,
        enableStreaming: false,
      })
      if (response.status < 200 || response.status >= 300) {
        const err = response.data as { detail?: string; error?: string } | undefined
        setSnackbarMessage(err?.detail || err?.error || '提交重新生成失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setIsRunning(false)
        return
      }
      setSnackbarMessage('已提交重新生成，请稍候完成')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      // 等待任务完成后由现有状态/事件再决定是否再次弹出确认
    } catch {
      setSnackbarMessage('提交重新生成失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      setIsRunning(false)
    }
  }

  // 关闭最终版本对话框
  const handleCloseFinalVersionDialog = () => {
    setShowFinalVersionDialog(false)
    // 不清空 finalVersionContent，保持已保存的内容
    setEditedFinalVersionContent('')  // 只清空编辑状态
  }

  // ✅ 已移除"仅保存"按钮功能，简化用户操作流程

  // 保存为章节（从最终版本）
  const handleSaveAsChapterFromFinalVersion = async () => {
    if (!projectId || !editedFinalVersionContent) {
      setSnackbarMessage('没有可保存的内容')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    setSavingChapter(true)

    try {

      // ✅ 更新state，保持已保存的内容
      setFinalVersionContent(editedFinalVersionContent)

      // 创建独立章节记录 - 使用apiClient确保正确的baseURL，URL末尾添加斜杠避免307重定向
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: editedFinalVersionContent,
        title: chapterTitleInput || undefined, // 如果为空则自动生成
      })

      // axios成功响应（2xx状态码）
      const data = response.data

      // ✅ 关闭对话框
      handleCloseFinalVersionDialog()

      // 显示成功消息（后端直接返回章节对象，不是嵌套在chapter字段中）
      setSnackbarMessage(`✅ 第${data.chapter_number}章已保存：${data.title} (${data.word_count}字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // ✅ 返回 Dashboard 并自动展开章节列表
      setTimeout(() => {
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1000)
    } catch (error: any) {
      // axios错误响应（非2xx状态码或网络错误）
      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = await extractApiErrorMessage(error, errorMessage)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会执行
      setSavingChapter(false)
    }
  }



  const currentStageIndex = stages.indexOf(workflow.currentStage)

  // 🆕 刷新后保持评审按钮显示（不自动弹窗）
  // 🔥 核心逻辑：只在概念阶段完成后且结构阶段未启动时显示
  useEffect(() => {
    const isConceptStage = workflow.currentStage === 'concept'
    const conceptCompleted = workflow.stages.concept.status === 'completed'
    const conceptActive = workflow.stages.concept.status === 'active'
    const hasConceptAgentWorking = workflow.stages.concept.agents.some(a => a.status === 'working')
    
    // 🔑 关键判断：结构阶段是否已开始（pending表示未启动，active/completed表示已启动）
    const structureStarted = workflow.stages.structure.status !== 'pending'
    
    const hasContent = !!(conceptContent || worldContent)
    
    // 三种显示场景：
    // 1. 概念阶段完成待评审（有内容，结构未启动）
    const scenario1 = isConceptStage && conceptCompleted && !structureStarted && hasContent
    // 2. 概念阶段执行中（生成中或重新生成中）
    const scenario2 = isConceptStage && (conceptActive || hasConceptAgentWorking)
    // 3. 概念阶段重生后仍在概念阶段（完成状态，结构未启动，有内容）
    const scenario3 = isConceptStage && conceptCompleted && !structureStarted && hasContent
    
    const shouldShow = scenario1 || scenario2 || scenario3
    setDecisionReady(shouldShow)
  }, [workflow.currentStage, conceptContent, worldContent, workflow.stages.concept.status, workflow.stages.structure.status, workflow.stages.concept.agents])

  return (
    <Container maxWidth="lg" sx={{ py: { xs: 1, sm: 2 }, px: { xs: 1, sm: 2 } }}>
      {/* 顶部区域：返回按钮 + 标题居中 */}
      <Box sx={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        mb: { xs: 1.5, sm: 2 },
        py: 1,
        position: 'relative',
      }}>
        {/* 返回按钮 */}
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => {
            localStorage.removeItem('lastWorkflowProjectId')
            navigate('/dashboard')
          }}
          variant="outlined"
          size="small"
          sx={{ 
            py: { xs: 0.4, sm: 0.5 }, 
            px: { xs: 1, sm: 1.5 }, 
            fontSize: { xs: '0.75rem', sm: '0.8rem' },
            minHeight: { xs: 32, sm: 36 }
          }}
        >
          返回
        </Button>

        {/* 主标题 - 居中显示 */}
        <Box sx={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: { xs: 0.5, sm: 1 },
          position: 'absolute',
          left: '50%',
          transform: 'translateX(-50%)',
        }}>
          <Typography 
            component="span" 
            sx={{ 
              fontSize: { xs: '1.2rem', sm: '1.5rem', md: '1.8rem' },
              animation: 'float 3s ease-in-out infinite',
              '@keyframes float': {
                '0%, 100%': { transform: 'translateY(0)' },
                '50%': { transform: 'translateY(-4px)' },
              },
            }}
          >
            ⛵
          </Typography>
          <Typography 
            variant="h5" 
            sx={{ 
              fontWeight: 700,
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
              backgroundClip: 'text',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              fontStyle: 'italic',
              letterSpacing: { xs: '1px', sm: '2px' },
              textShadow: '2px 2px 4px rgba(0,0,0,0.1)',
              animation: 'shimmer 3s ease-in-out infinite',
              '@keyframes shimmer': {
                '0%': { backgroundPosition: '0% 50%' },
                '50%': { backgroundPosition: '100% 50%' },
                '100%': { backgroundPosition: '0% 50%' },
              },
              backgroundSize: '200% 200%',
              fontSize: { xs: '1.1rem', sm: '1.4rem', md: '1.5rem' }
            }}
          >
            灵感方舟
          </Typography>
        </Box>

        {/* 右侧占位，保持平衡 */}
        <Box sx={{ width: { xs: 40, sm: 60 } }} />
      </Box>

      {/* 项目信息 */}
      {(currentProject || workflow.projectId) && (
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: { xs: 1, sm: 1.5 }, flexWrap: 'wrap', mb: { xs: 1.5, sm: 2 } }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
            当前项目:
          </Typography>
          {currentProject && (
            <Chip
              label={`📝 ${currentProject.title}`}
              color="primary"
              variant="outlined"
              size="small"
              sx={{ fontSize: { xs: '0.7rem', sm: '0.8rem' }, height: { xs: 24, sm: 28 } }}
            />
          )}
          {workflow.projectId && (
            <Chip
              label={formatProjectSequenceLabel(currentProject, workflow.projectId)}
              variant="outlined"
              size="small"
              sx={{ height: { xs: 24, sm: 28 }, fontSize: { xs: '0.7rem', sm: '0.8rem' } }}
            />
          )}
        </Box>
      )}

      {/* 错误提示 */}
      {workflow.error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {workflow.error}
        </Alert>
      )}

      {/* 异步任务进度提示 */}
      {currentTaskId && !generateNextChapterTaskId && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <CircularProgress size={20} />
            <Box sx={{ flex: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="body2">
                  正在执行 {stageNames[workflow.currentStage]}... ({taskProgress}%)
                </Typography>
                {estimatedRemainingTime > 0 && (() => {
                  // 🆕 置信区间显示逻辑
                  const timeDiff = estimatedRemainingTimeMax - estimatedRemainingTimeMin
                  const showRange = timeDiff >= 10  // 差距大于10秒才显示范围

                  if (showRange) {
                    return (
                      <Typography variant="caption" color="text.secondary">
                        预计剩余: {Math.ceil(estimatedRemainingTimeMin)}-{Math.ceil(estimatedRemainingTimeMax)}秒
                      </Typography>
                    )
                  } else {
                    return (
                      <Typography variant="caption" color="text.secondary">
                        预计剩余: {Math.ceil(estimatedRemainingTime)}秒
                      </Typography>
                    )
                  }
                })()}
              </Box>
              <LinearProgress variant="determinate" value={taskProgress} />
            </Box>
          </Box>
        </Alert>
      )}

      {/* 🆕 生成下一章任务进度提示 */}
      {generateNextChapterTaskId && generatingNextChapter && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <CircularProgress size={20} />
            <Box sx={{ flex: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="body2">
                  🚀 正在生成第{generateNextChapterNumber}章... ({generateNextChapterProgress}%)
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {generateNextChapterProgress < 25 ? '步骤1/4: 章节规划' :
                   generateNextChapterProgress < 50 ? '步骤2/4: 内容创作' :
                   generateNextChapterProgress < 75 ? '步骤3/4: 质量评审' :
                   '步骤4/4: 迭代优化'}
                </Typography>
              </Box>
              <LinearProgress variant="determinate" value={generateNextChapterProgress} />
            </Box>
          </Box>
        </Alert>
      )}

      {/* 主内容区域 */}
      <Box sx={{ position: 'relative' }}>
        {/* 左侧抽屉切换按钮 */}
        <Tooltip title={leftDrawerOpen ? "收起侧边栏" : "展开侧边栏"} placement="right">
          <IconButton
            onClick={() => setLeftDrawerOpen(!leftDrawerOpen)}
            sx={{
              position: 'fixed',
              left: leftDrawerOpen ? 340 : 16,
              top: '50%',
              transform: 'translateY(-50%)',
              zIndex: 1201,
              backgroundColor: 'primary.main',
              color: 'white',
              boxShadow: 2,
              transition: 'left 0.3s ease',
              '&:hover': {
                backgroundColor: 'primary.dark',
              },
            }}
          >
            {leftDrawerOpen ? <CloseIcon /> : <MenuIcon />}
          </IconButton>
        </Tooltip>

        {/* 左侧抽屉 */}
        <Drawer
          variant="persistent"
          anchor="left"
          open={leftDrawerOpen}
          sx={{
            '& .MuiDrawer-paper': {
              width: 340,
              boxSizing: 'border-box',
              top: 64,
              height: 'calc(100% - 64px)',
              p: 2,
            },
          }}
        >
          {/* 总进度条 */}
          <Card sx={{ mb: 1.5 }}>
            <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.75 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, fontSize: '0.85rem' }}>
                  📈 总体进度
                </Typography>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, color: 'primary.main', fontSize: '0.85rem' }}>
                  {workflow.overallProgress}%
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={workflow.overallProgress}
                sx={{ height: 6, borderRadius: 3 }}
              />
            </CardContent>
          </Card>

          <Card sx={{ mb: 1.5 }}>
            <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
              <FormControl fullWidth size="small">
                <InputLabel>创作模型</InputLabel>
                <Select
                  value={workflowGenerationModel}
                  label="创作模型"
                  onChange={(event) => handleWorkflowGenerationModelChange(String(event.target.value))}
                  disabled={workflowGenerationModelsLoading || isStarting || isRunning || generatingNextChapter}
                >
                  {workflowGenerationModels.length === 0 && (
                    <MenuItem value={workflowGenerationModel}>{workflowGenerationModel}</MenuItem>
                  )}
                  {workflowGenerationModels.map((model) => (
                    <MenuItem key={model.id} value={model.id}>
                      <Tooltip
                        title={
                          <Box sx={{ whiteSpace: 'pre-line' }}>
                            {formatWorkflowGenerationModelTooltip(model)}
                          </Box>
                        }
                        placement="right"
                        arrow
                        enterDelay={250}
                      >
                        <Box
                          component="span"
                          sx={{
                            display: 'block',
                            width: '100%',
                            whiteSpace: 'normal',
                            lineHeight: 1.35,
                          }}
                        >
                          {formatWorkflowGenerationModelOptionLabel(model)}
                        </Box>
                      </Tooltip>
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </CardContent>
          </Card>

          {/* 阶段信息面板（工作步骤说明） */}
          <StageInfoPanel stage={workflow.currentStage} />

          {/* Agent状态 */}
          <Card sx={{ mb: 0, flex: 1 }}>
            <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontSize: '0.85rem', fontWeight: 600 }}>
                📊 Agent状态
              </Typography>
              {workflow.stages[workflow.currentStage].agents.map((agent) => (
                <AgentStatusIndicator key={agent.id} agent={agent} />
              ))}
            </CardContent>
          </Card>
        </Drawer>

        {/* 右侧：阶段导航 + 输出预览区域 */}
        <Box
          sx={{
            ml: leftDrawerOpen ? '340px' : 0,
            transition: 'margin-left 0.3s ease',
          }}
        >
          {/* 阶段导航 - 与左侧总进度对齐 */}
          <Paper sx={{ py: 2.5, px: 3, mb: 2 }}>
            <Stepper
              activeStep={currentStageIndex}
              sx={{
                '& .MuiStepConnector-line': {
                  minWidth: 24,
                },
              }}
            >
              {stages.map((stage) => (
                <Step
                  key={stage}
                  completed={workflow.stages[stage].status === 'completed'}
                  sx={{ cursor: 'pointer', px: 0.5 }}
                  onClick={() => {
                    // 跳转到对应阶段
                    dispatch(setCurrentStage(stage))
                    // 显示提示
                    setSnackbarMessage(`已切换到 ${stageNames[stage]}`)
                    setSnackbarSeverity('info')
                    setSnackbarOpen(true)
                  }}
                >
                  <StepLabel
                    sx={{
                      '& .MuiStepLabel-label': {
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        transition: 'color 0.2s, transform 0.2s',
                        '&:hover': {
                          color: 'primary.main',
                          transform: 'scale(1.05)',
                        },
                      },
                    }}
                  >
                    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
                      <Box component="span">{stageNames[stage]}</Box>
                      {stage === 'review' && projectId ? (
                        <Tooltip title="多模型评审设置" arrow>
                          <Box
                            component="span"
                            onClick={(event) => event.stopPropagation()}
                            sx={{ display: 'inline-flex' }}
                          >
                            <IconButton
                              aria-label="多模型评审设置"
                              size="small"
                              onClick={(event) => {
                                event.stopPropagation()
                                setShowReviewSettingsDialog(true)
                              }}
                              disabled={isRunning || isStarting || generatingNextChapter}
                              sx={{
                                width: 28,
                                height: 28,
                                p: 0.25,
                                border: '1px solid',
                                borderColor: 'divider',
                                bgcolor: 'background.paper',
                                '&:hover': {
                                  bgcolor: 'action.hover',
                                },
                              }}
                            >
                              <TuneIcon fontSize="small" />
                            </IconButton>
                          </Box>
                        </Tooltip>
                      ) : null}
                    </Box>
                  </StepLabel>
                </Step>
              ))}
            </Stepper>
          </Paper>

          {/* 输出预览区域（始终可见，实时显示流式内容） */}
          <OutputPreviewPanel
            stage={workflow.currentStage}
            isStreaming={isStreaming}
            streamingStage={streamingStage}
            conceptContent={conceptContent}
            worldContent={worldContent}
            characterContent={characterContent}
            structureContent={structureContent}
            contentDraftContent={contentDraftContent}
            reviewReportContent={reviewReportContent}
            finalVersionContent={finalVersionContent}
            generateNextChapterStreamContent={generateNextChapterStreamContent}
            isGeneratingNextChapter={!!generateNextChapterTaskId}
            progressMessage={progressMessage}
            selectedConceptView={selectedConceptView}
            projectId={projectId || ''}
            reviewMeta={reviewMeta}
          />

          {/* 控制按钮 - 在文本区域正下方居中 */}
          <Box
            sx={{
              mt: 1,  // 🔧 减小与文本区域的间距
              display: 'flex',
              gap: 2,
              justifyContent: 'center',
            }}
          >
        {/* ✅ 概念开发阶段不显示"上一步"按钮 */}
        {currentStageIndex > 0 && (
          <Button
            variant="outlined"
            onClick={handlePreviousStage}
            disabled={workflow.loading || isRunning}
          >
            上一步
          </Button>
        )}

        {/* 概念开发阶段：显示“故事概念”、“世界观设定”、“人物设定”按钮 */}
        {workflow.currentStage === 'concept' ? (
          <Box sx={{ display: 'flex', gap: 1 }}>
            {decisionReady && (
              <Badge color="error" variant="dot" overlap="rectangular" anchorOrigin={{ vertical: 'top', horizontal: 'left' }}>
              <Button
                variant="contained"
                color="primary"
                onClick={() => setShowDecisionDialog(true)}
                disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
                sx={{
                animation: 'pulse 1.5s ease-in-out infinite, wave 2.4s linear infinite',
                  '@keyframes pulse': {
                    '0%': { transform: 'scale(1)' },
                    '50%': { transform: 'scale(1.06)' },
                    '100%': { transform: 'scale(1)' },
                  },
                  '@keyframes wave': {
                    '0%': { boxShadow: '0 0 0 0 rgba(25,118,210,0.35)' },
                    '50%': { boxShadow: '0 0 0 8px rgba(25,118,210,0.12)' },
                    '100%': { boxShadow: '0 0 0 0 rgba(25,118,210,0.35)' },
                  },
                }}
              >
                {(workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')) ? '生成中' : '评审结果'}
              </Button>
              </Badge>
            )}
            <Button
              variant="outlined"
              onClick={handleOpenConceptDialog}
              disabled={!conceptContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<DescriptionIcon />}
            >
              故事概念
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenWorldDialog}
              disabled={!worldContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PublicIcon />}
            >
              世界观设定
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenCharacterDialog}
              disabled={!characterContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PeopleIcon />}
            >
              人物设定
            </Button>
          </Box>
        ) : workflow.currentStage === 'structure' ? (
          /* 结构设计阶段：显示"情节大纲"按钮 */
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenStructureDialog}
              disabled={!structureContent && workflow.stages.structure.status !== 'completed'}
              startIcon={<ArticleIcon />}
            >
              情节大纲
            </Button>
          </Box>
        ) : workflow.currentStage === 'content' ? (
          /* 内容创作阶段：显示“章节初稿”按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenContentDialog}
            disabled={!contentDraftContent && workflow.stages.content.status !== 'completed'}
            startIcon={<EditNoteIcon />}
          >
            章节初稿
          </Button>
        ) : workflow.currentStage === 'review' ? (
          /* 质量评审阶段：显示"评审报告"按钮 */
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenReviewDialog}
              disabled={!reviewReportContent && workflow.stages.review.status !== 'completed'}
              startIcon={<ArticleIcon />}
            >
              评审报告
            </Button>
            <Button
              variant="outlined"
              onClick={handleManualMultiModelReview}
              disabled={!contentDraftContent || isRunning || isStarting || generatingNextChapter}
              startIcon={<RefreshIcon />}
            >
              多模型重评
            </Button>
          </Box>
        ) : workflow.currentStage === 'iteration' ? (
          /* 迭代优化阶段：显示“最终成品”和“生成下一章”按钮 */
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenFinalProduct}
              disabled={!finalVersionContent && workflow.stages.iteration.status !== 'completed'}
              startIcon={<CheckCircleIcon />}
            >
              最终成品
            </Button>
            <Button
              variant="outlined"
              onClick={() => handleGenerateNextChapter()}
              disabled={workflow.stages.iteration.status !== 'completed' || generatingNextChapter}
              startIcon={generatingNextChapter ? <CircularProgress size={20} /> : <NavigateNextIcon />}
            >
              {generatingNextChapter ? '生成中...' : '生成下一章'}
            </Button>
          </Box>
        ) : (
          /* 其他阶段：显示"重新生成"按钮 */
          <Button
            variant="outlined"
            onClick={handleRegenerateStage}
            disabled={workflow.loading || !isRunning}
            startIcon={<RefreshIcon />}
          >
            重新生成
          </Button>
        )}

        {currentStageIndex !== stages.length - 1 && (
          <Button
            variant="outlined"
            onClick={handleNextStage}
            disabled={workflow.loading || isRunning}
          >
            下一步
          </Button>
        )}
          </Box>

          {/* 概念开发阶段决策条（已移除，使用 Dialog 替代） */}
        </Box>
      </Box>

      {/* 🆕 已有内容警告对话框 */}
      <Dialog
        open={showContentWarningDialog}
        onClose={() => setShowContentWarningDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            ⚠️ 警告：此项目已有内容
          </Typography>

          <Alert severity="warning" sx={{ mb: 3 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>此项目已有 {existingChaptersCount} 章内容</strong>
              {workflow.stages.concept.status === 'completed' && '，以及已完成的故事概念'}
              {workflow.stages.structure.status === 'completed' && '、情节大纲'}。
            </Typography>
            <Typography variant="body2">
              重新开始创作将<strong style={{ color: '#d32f2f' }}>覆盖所有现有内容</strong>，此操作不可撤销！
            </Typography>
          </Alert>

          <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
            您想要的操作是：
          </Typography>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {existingChaptersCount > 0 && (
              <Button
                variant="contained"
                color="primary"
                onClick={handleContinueNextChapter}
                startIcon={<AddIcon />}
                sx={{ justifyContent: 'flex-start', py: 1.5 }}
              >
                <Box sx={{ textAlign: 'left' }}>
                  <Typography variant="button">继续创作下一章</Typography>
                  <Typography variant="caption" sx={{ display: 'block', opacity: 0.8 }}>
                    基于现有内容，生成第 {existingChaptersCount + 1} 章（推荐）
                  </Typography>
                </Box>
              </Button>
            )}

            {/* 🆕 免费生成入口：服务端强制 qwen3.7-flash，每日限额 */}
            {existingChaptersCount > 0 && (
              <Button
                variant="outlined"
                color="success"
                onClick={handleContinueNextChapterFree}
                startIcon={<AddIcon />}
                disabled={generatingNextChapter || freeQuota?.remaining === 0 || freeQuota?.globalAvailable === false}
                sx={{ justifyContent: 'flex-start', py: 1.5 }}
              >
                <Box sx={{ textAlign: 'left' }}>
                  <Typography variant="button">免费生成下一章</Typography>
                  <Typography variant="caption" sx={{ display: 'block', opacity: 0.8 }}>
                    {freeQuota?.globalAvailable === false
                      ? '今日免费发放量已用完'
                      : freeQuota
                        ? `使用免费模型生成第 ${existingChaptersCount + 1} 章，今日剩余 ${freeQuota.remaining} 章`
                        : `使用免费模型生成第 ${existingChaptersCount + 1} 章，每日限 2 章`}
                  </Typography>
                </Box>
              </Button>
            )}

            <Button
              variant="outlined"
              color="error"
              onClick={handleConfirmRestart}
              startIcon={<RefreshIcon />}
              sx={{ justifyContent: 'flex-start', py: 1.5 }}
            >
              <Box sx={{ textAlign: 'left' }}>
                <Typography variant="button">重新开始（覆盖所有）</Typography>
                <Typography variant="caption" sx={{ display: 'block', opacity: 0.8 }}>
                  删除现有内容，从头开始创作
                </Typography>
              </Box>
            </Button>

            <Button
              variant="text"
              onClick={() => setShowContentWarningDialog(false)}
              sx={{ justifyContent: 'flex-start' }}
            >
              取消
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 开始创作对话框 */}
      <Dialog
        open={openDialog}
        onClose={() => !isStarting && setOpenDialog(false)}
        maxWidth="md"
        fullWidth
      >
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            开始创作 - 配置项目参数
          </Typography>

          {/* 启动中的加载提示 */}
          {isStarting && (
            <Alert severity="info" sx={{ mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={20} />
                <Typography variant="body2">
                  正在启动工作流，请稍候...
                </Typography>
              </Box>
            </Alert>
          )}
          
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>创作模型</InputLabel>
            <Select
              value={workflowGenerationModel}
              onChange={(e) => handleWorkflowGenerationModelChange(String(e.target.value))}
              disabled={isStarting || workflowGenerationModelsLoading}
              label="创作模型"
            >
              {workflowGenerationModels.length === 0 && (
                <MenuItem value={workflowGenerationModel}>{workflowGenerationModel}</MenuItem>
              )}
              {workflowGenerationModels.map((model) => (
                <MenuItem key={model.id} value={model.id}>
                  <Tooltip
                    title={
                      <Box sx={{ whiteSpace: 'pre-line' }}>
                        {formatWorkflowGenerationModelTooltip(model)}
                      </Box>
                    }
                    placement="right"
                    arrow
                    enterDelay={250}
                  >
                    <Box
                      component="span"
                      sx={{
                        display: 'block',
                        width: '100%',
                        whiteSpace: 'normal',
                        lineHeight: 1.35,
                      }}
                    >
                      {formatWorkflowGenerationModelOptionLabel(model)}
                    </Box>
                  </Tooltip>
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {/* 🆕 题材选择 */}
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>题材类型</InputLabel>
            <Select
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
              disabled={isStarting}
              label="题材类型"
            >
              <MenuItem value="">请选择</MenuItem>
              <MenuItem value="修仙">修仙</MenuItem>
              <MenuItem value="玄幻">玄幻</MenuItem>
              <MenuItem value="奇幻">奇幻</MenuItem>
              <MenuItem value="都市">都市</MenuItem>
              <MenuItem value="言情">言情</MenuItem>
              <MenuItem value="耽美">耽美</MenuItem>
              <MenuItem value="悬疑">悬疑</MenuItem>
              <MenuItem value="科幻">科幻</MenuItem>
              <MenuItem value="纯文学">纯文学</MenuItem>
            </Select>
            <FormHelperText>AI将根据题材自动调整创作风格和节奏</FormHelperText>
          </FormControl>
          
          {/* 🆕 篇幅选择 */}
          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>篇幅规划</InputLabel>
            <Select
              value={plannedLengthType}
              onChange={(e) => {
                const value = e.target.value
                setPlannedLengthType(value)
                // 根据篇幅自动设置推荐章节范围
                if (value === 'short') {
                  setPlannedChaptersMin(3)
                  setPlannedChaptersMax(30)
                } else if (value === 'mid') {
                  setPlannedChaptersMin(31)
                  setPlannedChaptersMax(300)
                } else if (value === 'long') {
                  setPlannedChaptersMin(301)
                  setPlannedChaptersMax(799)
                } else if (value === 'epic') {
                  setPlannedChaptersMin(800)
                  setPlannedChaptersMax(1000)
                }
              }}
              disabled={isStarting}
              label="篇幅规划"
            >
              <MenuItem value="">请选择</MenuItem>
              <MenuItem value="short">短篇 (3-30章)</MenuItem>
              <MenuItem value="mid">中篇 (31-300章)</MenuItem>
              <MenuItem value="long">长篇 (301-799章)</MenuItem>
              <MenuItem value="epic">超长篇 (800+章)</MenuItem>
            </Select>
            <FormHelperText>系统将根据篇幅推荐适合的大纲扩展模式</FormHelperText>
          </FormControl>

          {/* 💡 智能推荐简化提示 */}
          {genre && plannedLengthType && (
            <Alert 
              severity="info" 
              sx={{ mb: 2, backgroundColor: '#e3f2fd' }}
            >
              <Typography variant="body2">
                💡 系统将根据「{genre}」题材和「{plannedLengthType === 'short' ? '短篇' : plannedLengthType === 'mid' ? '中篇' : plannedLengthType === 'long' ? '长篇' : '超长篇'}」篇幅推荐适合的大纲扩展模式
              </Typography>
            </Alert>
          )}
          
          {/* 🆕 章节范围 */}
          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <TextField
              label="最少章节数"
              type="number"
              value={plannedChaptersMin}
              onChange={(e) => setPlannedChaptersMin(e.target.value ? parseInt(e.target.value) : '')}
              disabled={isStarting}
              sx={{ flex: 1 }}
              inputProps={{ min: 1 }}
            />
            <TextField
              label="最多章节数"
              type="number"
              value={plannedChaptersMax}
              onChange={(e) => setPlannedChaptersMax(e.target.value ? parseInt(e.target.value) : '')}
              disabled={isStarting}
              sx={{ flex: 1 }}
              inputProps={{ min: 1 }}
            />
          </Box>

          <TextField
            fullWidth
            multiline
            rows={4}
            label="创作需求"
            placeholder="请输入您的创作需求，例如：创作一部关于时空旅行的科幻小说..."
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            sx={{ mb: 2 }}
            disabled={isStarting}
          />
          
          {/* 🆕 自定义大纲规划 */}
          <TextField
            fullWidth
            multiline
            rows={4}
            label="自定义大纲规划（可选）"
            placeholder={
              genre && plannedLengthType ? (
                `🎵 节奏建议：${
                  genre === '修仙' && plannedLengthType === 'long' ? '修仙长篇推荐境界逐层递进，每5-8章一个小爆点，每卷结束有境界突破大高潮' :
                  genre === '修仙' && plannedLengthType !== 'long' ? '修仙题材注意境界体系设计，确保修炼节奏合理' :
                  genre === '玄幻' && plannedLengthType === 'long' ? '玄幻长篇推荐天赋觉醒与实力突破交替，每5-8章一个小爆点' :
                  genre === '玄幻' && plannedLengthType !== 'long' ? '玄幻题材注意血脉天赋体系设计，确保等级压制清晰' :
                  genre === '奇幻' && plannedLengthType === 'long' ? '奇幻长篇推荐奇妙世界规则逐渐展开，每5-8章一个世界观揭秘或冒险突破' :
                  genre === '奇幻' && plannedLengthType !== 'long' ? '奇幻题材注意奇幻种族、魔法体系设计，保持冒险与探索节奏' :
                  genre === '悬疑' ? '悬疑题材注意线索布局，每3-5章揭露一个小真相，每卷一个大反转' :
                  genre === '都市' ? '都市题材建议多线穿插（商战+感情+亲情），每卷一个事业里程碑' :
                  genre === '言情' ? '言情题材注意感情递进（相识→相知→相守），每5-10章一个甜蜜时刻' :
                  genre === '耽美' ? '耽美题材注意昧昧张力与情感突破交替，每5-10章一个关系进展节点' :
                  genre === '科幻' ? '科幻题材注意科技突破节奏，每卷一次探索升级（地球→星系→宇宙）' :
                  genre === '纯文学' ? '纯文学题材注重内心世界与外部环境的张力，节奏可适当放缓' :
                  '根据题材特点自动适配叙事节奏'
                }\n\n💡 未检测到自定义规划，将随机智能生成大纲`
              ) : '可输入您的卷结构规划，例如：\n第一卷：引气境 (10章)\n第二卷：筑基境 (15章)\n...'
            }
            value={userOutlinePlan}
            onChange={(e) => setUserOutlinePlan(e.target.value)}
            sx={{ mb: 2 }}
            disabled={isStarting}
          />
          
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button
              onClick={() => setOpenDialog(false)}
              disabled={isStarting}
            >
              取消
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleStartWorkflow}
              disabled={workflow.loading || isStarting}
              startIcon={isStarting ? <CircularProgress size={20} /> : undefined}
            >
              {isStarting ? '启动中...' : '开始'}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 保存章节对话框 */}
      <Dialog open={showSaveDialog} onClose={() => setShowSaveDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🎉 工作流程已完成！
          </Typography>
          <Alert severity="success" sx={{ mb: 2 }}>
            所有5个阶段已成功完成，现在可以将生成的内容保存为新章节。
          </Alert>
          <TextField
            fullWidth
            label="章节标题（可选）"
            placeholder="例如：冒险开始（留空则自动生成）"
            value={chapterTitle}
            onChange={(e) => setChapterTitle(e.target.value)}
            sx={{ mb: 2 }}
            disabled={savingChapter}
            helperText="如果不输入标题，系统会根据章节内容自动生成标题，格式为：第一章 {AI生成的标题}"
          />
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              onClick={() => {
                setShowSaveDialog(false)
                setChapterTitle('')
              }}
              disabled={savingChapter}
            >
              稍后保存
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleSaveAsChapter}
              disabled={savingChapter}
              startIcon={savingChapter ? <CircularProgress size={20} /> : <SaveIcon />}
            >
              {savingChapter ? '保存中...' : '保存为章节'}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 情节大纲对话框 */}
      <Dialog open={showStructureDialog} onClose={handleCloseStructureDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📋 情节大纲文档
          </Typography>

          {structureLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField
                  fullWidth
                  multiline
                  rows={12}
                  value={editedStructureContent}
                  onChange={(e) => setEditedStructureContent(e.target.value)}
                  placeholder="情节大纲文本内容..."
                  sx={{ mb: 2 }}
                  disabled={structureSaving}
                  InputProps={{
                    style: {
                      fontFamily: 'monospace',
                      fontSize: '0.875rem',
                    }
                  }}
                />

                {/* 底部一行：取消/保存 */}
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', mt: 1 }}>
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <Button
                      onClick={handleCloseStructureDialog}
                      disabled={structureSaving}
                    >
                      取消
                    </Button>
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={handleSaveOnlyStructure}
                      disabled={structureSaving}
                      startIcon={structureSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                    >
                      {structureSaving ? '保存中...' : '保存'}
                    </Button>
                  </Box>
                </Box>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 章节初稿对话框 */}
      <Dialog open={showContentDialog} onClose={handleCloseContentDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✍️ 章节初稿文档
          </Typography>

          {contentLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContentDraftContent}
                onChange={(e) => setEditedContentDraftContent(e.target.value)}
                placeholder="章节初稿文本内容..."
                sx={{ mb: 2 }}
                disabled={contentSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseContentDialog}
                  disabled={contentSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 评审报告对话框 */}
      <Dialog open={showReviewDialog} onClose={handleCloseReviewDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📋 质量评审报告
          </Typography>

          {reviewLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedReviewReportContent}
                onChange={(e) => setEditedReviewReportContent(e.target.value)}
                placeholder="评审报告内容..."
                sx={{ mb: 2 }}
                disabled={reviewSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseReviewDialog}
                  disabled={reviewSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyReview}
                  disabled={reviewSaving}
                  startIcon={reviewSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {reviewSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueReview}
                  disabled={reviewSaving}
                  startIcon={reviewSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {reviewSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 最终版本对话框 */}
      <Dialog open={showFinalVersionDialog} onClose={handleCloseFinalVersionDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✨ 最终版本文档
          </Typography>

          {finalVersionLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedFinalVersionContent}
                onChange={(e) => setEditedFinalVersionContent(e.target.value)}
                placeholder="最终版本文本内容..."
                sx={{ mb: 2 }}
                disabled={savingChapter}
              />

              {/* 章节标题输入框 */}
              <TextField
                fullWidth
                label="章节标题（可选）"
                placeholder="例如：冒险开始（留空则自动生成）"
                value={chapterTitleInput}
                onChange={(e) => setChapterTitleInput(e.target.value)}
                sx={{ mb: 2 }}
                disabled={savingChapter}
                helperText="如果不输入标题，系统会根据章节内容自动生成标题"
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseFinalVersionDialog}
                  disabled={savingChapter}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAsChapterFromFinalVersion}
                  disabled={savingChapter || !editedFinalVersionContent}
                  startIcon={savingChapter ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {savingChapter ? '保存中...' : '保存为章节'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 概念阶段决策弹窗（一次性，手动触发） */}
      <Dialog open={workflow.currentStage === 'concept' && showDecisionDialog} onClose={() => setShowDecisionDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>概念阶段完成</Typography>
          <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
            本轮故事概念和世界观设定已生成，满意可点击进入下一阶段，不满意可点击重新生成或者
            <Typography
              component="span"
              sx={{
                color: 'primary.main',
                cursor: 'pointer',
                textDecoration: 'underline',
                '&:hover': {
                  color: 'primary.dark',
                },
              }}
              onClick={() => {
                setShowDecisionDialog(false)
                navigate(`/knowledge-base/${projectId}`)
              }}
            >
              前往知识库
            </Typography>
            手动编辑修改。
          </Typography>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1.5 }}>
            <Button
              variant="contained"
              color="primary"
              disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
              onClick={() => {
                setShowDecisionDialog(false)
                setDecisionReady(false)
                dispatch(updateStageStatus({ stage: 'concept', status: 'completed' }))
                setIsRunning(true)
                const nextStage: StageType = 'structure'
                dispatch(setCurrentStage(nextStage))
                executeStageAsync(nextStage)
              }}
            >
              进入下一阶段
            </Button>
            <Button
              variant="outlined"
              disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
              onClick={() => setShowRegenerateDialog(true)}
            >
              重新生成
            </Button>

          </Box>
        </Box>
      </Dialog>

      {/* 重新生成设置弹窗 */}
      <Dialog open={showRegenerateDialog} onClose={() => setShowRegenerateDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            重新生成设置
          </Typography>

          <TextField
            fullWidth
            multiline
            rows={4}
            placeholder="可在此处输入您的想法，否则系统将随机重新生成。（选填）"
            value={regenerateFeedback}
            onChange={(e) => setRegenerateFeedback(e.target.value)}
            sx={{ mb: 2 }}
          />

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
            <Tooltip 
              title={
                autoInferFeedback 
                  ? "开启后，若未填写想法，系统将基于当前内容进行优化改进"
                  : "关闭后,若未填写想法,系统将完全随机重新生成"
              }
              arrow
              placement="top"
            >
              <Chip
                label={autoInferFeedback ? '自动推断：开' : '自动推断：关'}
                size="small"
                variant="outlined"
                onClick={() => setAutoInferFeedback((v) => !v)}
                sx={{ cursor: 'pointer' }}
              />
            </Tooltip>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {autoInferFeedback ? '将基于当前内容微调优化' : '将完全随机重新生成'}
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>目标：</Typography>
            <Button variant={regenerateTarget === 'story' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('story')}>重生故事概念</Button>
            <Button variant={regenerateTarget === 'world' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('world')}>重生世界观</Button>
            <Button variant={regenerateTarget === 'both' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('both')}>重生两者</Button>
          </Box>

          <Box sx={{ mb: 2 }}>
            <Alert severity="info" icon={false}>
              <Typography variant="caption">
                人物重生请前往知识库的人物设定页使用“拓展人物”，此处仅针对故事概念/世界观。
              </Typography>
              <Box sx={{ mt: 1 }}>
                <Button size="small" variant="outlined" onClick={() => navigate(`/knowledge-base/${projectId}`)}>去知识库拓展人物</Button>
              </Box>
            </Alert>
          </Box>

          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1.5 }}>
            <Button onClick={() => setShowRegenerateDialog(false)}>取消</Button>
            <Button
              variant="contained"
              disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
              onClick={handleSubmitRegenerateConcept}
            >
              提交并重新生成
            </Button>
          </Box>
        </Box>
      </Dialog>

      <MultiModelReviewSettingsDialog
        open={showReviewSettingsDialog}
        projectId={projectId ? Number(projectId) : null}
        projectTitle={currentProject?.title}
        onClose={() => setShowReviewSettingsDialog(false)}
        onSaved={handleReviewSettingsSaved}
      />

      <Dialog open={showManualReviewDialog} onClose={() => setShowManualReviewDialog(false)} maxWidth="xs" fullWidth>
        <Box sx={{ p: 3, display: 'flex', flexDirection: 'column', gap: 2.25 }}>
          <Typography variant="h6">升级本次质量评审</Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            仅重新评审当前章节初稿，不修改项目自动策略。
          </Typography>
          <FormControl fullWidth size="small">
            <InputLabel>评审强度</InputLabel>
            <Select
              label="评审强度"
              value={manualReviewPreset}
              onChange={(event) => setManualReviewPreset(event.target.value as ReviewPreset)}
            >
              <MenuItem value="balanced_3">普通增强（3 评审）</MenuItem>
              <MenuItem value="key_chapter_5">重点章节（5 评审）</MenuItem>
              <MenuItem value="deep_7">深度人工（7 评审）</MenuItem>
            </Select>
          </FormControl>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
            <Button onClick={() => setShowManualReviewDialog(false)}>取消</Button>
            <Button
              variant="contained"
              onClick={handleConfirmManualMultiModelReview}
              disabled={!contentDraftContent || isRunning || isStarting || generatingNextChapter}
            >
              开始重评
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 提示信息 */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={4000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MuiAlert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </MuiAlert>
      </Snackbar>
    </Container>
  )
}



