import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
  Grid,
  Paper,
  Dialog,
  TextField,
  Alert,
  CircularProgress,
  Tooltip,
  Fab,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'
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
import Chip from '@mui/material/Chip'
import Badge from '@mui/material/Badge'
import Snackbar from '@mui/material/Snackbar'
import MuiAlert from '@mui/material/Alert'
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
  StageType,
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
import { workflowWebSocket } from '@/services/websocket'
import { apiClient } from '@/services/api'  // ✅ 添加apiClient导入
import { ProgressEstimator, type StageDurations, type ProgressState } from '@/utils/progressEstimator'
import { statisticsService } from '@/services/statistics'


const stages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
const stageNames = {
  concept: '概念开发',
  structure: '结构设计',
  content: '内容创作',
  review: '质量评审',
  iteration: '迭代优化',
}



export default function WorkflowControlPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const workflow = useSelector((state: RootState) => state.workflow)
  // 🎯 任务3：获取当前项目信息
  const currentProject = useSelector((state: RootState) => state.project.currentProject)
  const [openDialog, setOpenDialog] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [isStarting, setIsStarting] = useState(false)  // 新增：标记是否正在启动工作流
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [chapterTitle, setChapterTitle] = useState('')

  // 🔥 页面加载时，恢复上次的项目位置
  useEffect(() => {
    const savedProjectId = localStorage.getItem('lastWorkflowProjectId')
    if (savedProjectId && !projectId) {
      console.log(`🔄 恢复上次的项目: ${savedProjectId}`)
      navigate(`/workflow/${savedProjectId}`)
    }
  }, [])

  // 🔥 页面离开前，保存当前项目ID
  useEffect(() => {
    if (projectId) {
      localStorage.setItem('lastWorkflowProjectId', projectId)
      console.log(`💾 已保存项目ID: ${projectId}`)
    }
  }, [projectId])

  // 🆕 保护机制：已有内容警告对话框
  const [showContentWarningDialog, setShowContentWarningDialog] = useState(false)
  const [existingChaptersCount, setExistingChaptersCount] = useState(0)

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
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)

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
  const [showConceptDecisionBar, setShowConceptDecisionBar] = useState(false)
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false)
  const [regenerateTarget, setRegenerateTarget] = useState<'both' | 'story' | 'world'>('both')
  const [regenerateFeedback, setRegenerateFeedback] = useState('')
  const [conceptDecisionShownThisSession, setConceptDecisionShownThisSession] = useState(false)
  const [autoInferFeedback, setAutoInferFeedback] = useState(true)
  const [decisionReady, setDecisionReady] = useState(false)
  const [showDecisionDialog, setShowDecisionDialog] = useState(false)

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
        // 🆕 优先使用最近3次任务的平均耗时（自适应学习）
        let durations = await statisticsService.getStageDurations(
          projectId ? Number(projectId) : undefined,
          3  // 最近3次任务
        )

        // 检查是否有足够的数据
        const hasEnoughData = Object.values(durations).every(d => d > 0)

        if (!hasEnoughData) {
          // 如果最近3次任务数据不足，回退到全局平均
          console.log('⚠️ 最近3次任务数据不足，回退到全局平均耗时')
          durations = await statisticsService.getStageDurations(
            projectId ? Number(projectId) : undefined
          )
        }

        console.log('📊 最终使用的阶段耗时:', durations)
        setStageDurations(durations)

        // 🆕 获取置信区间
        const durationRanges = await statisticsService.getStageDurationRanges(
          projectId ? Number(projectId) : undefined
        )

        // 创建进度估算器（传入置信区间）
        const estimator = new ProgressEstimator(durations, durationRanges || undefined)
        setProgressEstimator(estimator)
      } catch (error) {
        console.error('初始化进度估算器失败:', error)
      }
    }

    initProgressEstimator()
  }, [projectId])

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

  // 🔧 修复：移除 localStorage 阶段保存逻辑
  // 原因：localStorage 中的阶段可能与后端实际状态不一致
  // 改为完全依赖后端 API 返回的状态
  // useEffect(() => {
  //   if (projectId && workflow.currentStage) {
  //     localStorage.setItem(`project_${projectId}_currentStage`, workflow.currentStage)
  //     console.log(`💾 保存项目 ${projectId} 的当前阶段: ${workflow.currentStage}`)
  //   }
  // }, [projectId, workflow.currentStage])

  // 🆕 页面加载时恢复记忆快照
  useEffect(() => {
    if (!projectId) return

    const loadLatestMemory = async () => {
      try {
        const token = localStorage.getItem('access_token')
        if (!token) return

        const response = await fetch(`/api/v1/projects/${projectId}/memories/latest`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        })

        if (response.ok) {
          const memory = await response.json()
          if (memory) {
            // 恢复对话历史
            if (memory.messages && Array.isArray(memory.messages)) {
              setConversationHistory(memory.messages)
              console.log(`🔄 已恢复对话历史: ${memory.messages.length} 条`)
            }
            // 恢复写作目标
            if (memory.writing_goal && !requirement) {
              setRequirement(memory.writing_goal)
              console.log(`🔄 已恢复写作目标: ${memory.writing_goal.substring(0, 50)}...`)
            }
            // 更新最后保存时间
            if (memory.updated_at) {
              setLastSaveTime(new Date(memory.updated_at))
            }
            console.log(`✅ 记忆快照已恢复，项目: ${projectId}`)
          }
        }
      } catch (error) {
        console.error('❌ 恢复记忆快照失败:', error)
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
      console.log(`📍 检测到生成下一章任务: taskId=${generateNextChapterTaskId}, chapterNumber=${generateNextChapterNumber}`)
      setGeneratingNextChapter(true)
      setIsGenerateNextChapterFlow(true)
    }
  }, [generateNextChapterTaskId, generateNextChapterNumber])

  // 🔌 WebSocket 连接管理
  useEffect(() => {
    if (!projectId) return

    console.log('🔌 初始化 WebSocket 连接...')

    // 连接 WebSocket （异步）
    workflowWebSocket.connect().then(() => {
      console.log('✅ WebSocket 连接就绪，加入项目房间')
      workflowWebSocket.joinProject(Number(projectId))
    }).catch((error) => {
      console.error('❌ WebSocket 连接失败:', error)
    })

    // 监听阶段更新
    workflowWebSocket.onStageUpdate((data) => {
      console.log('📊 收到阶段更新:', data)

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
        console.log(`✅ 阶段 ${stageType} 开始，所有 Agent 设置为工作中`)
      } else if (data.status === 'completed') {
        dispatch(updateStageStatus({ stage: stageType, status: 'completed' }))

        // ✅ 临时方案：将该阶段的所有 Agent 设置为完成
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          dispatch(updateAgentStatus({
            stage: stageType,
            agentId: agent.id,
            status: 'completed',
            progress: 100,
            message: '执行完成'
          }))
        })
        console.log(`✅ 阶段 ${stageType} 完成，所有 Agent 设置为完成`)

        // 🆕 概念阶段完成：仅在会话中自动弹窗，刷新不弹
        if (stageType === 'concept' && !conceptDecisionShownThisSession) {
          try {
            if (projectId) {
              const token = localStorage.getItem('access_token')
              fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
                headers: { 'Authorization': `Bearer ${token}` },
              }).then(res => res.json()).then(batchData => {
                const stages = batchData.stages || {}
                if (stages.concept) setConceptContent(stages.concept)
                if (stages.world_setting) setWorldContent(stages.world_setting)
                const hasConcept = !!(stages.concept && stages.concept.trim())
                // 改为仅在故事概念就绪时弹窗（不依赖世界观）
                if (hasConcept) {
                  setDecisionReady(true)
                  setConceptDecisionShownThisSession(true)
                }
              }).catch(err => console.error('刷新概念阶段内容失败:', err))
            }
          } catch (err) {
            console.error('概念阶段完成后自动弹窗逻辑失败:', err)
          }
        }

        if (data.output) {
          dispatch(updateStageOutput({ stage: stageType, output: data.output }))

          // 🔥 关键修复：同步更新组件本地状态
          if (stageType === 'iteration') {
            setFinalVersionContent(data.output)
            console.log(`🔄 迭代优化阶段完成，已同步 finalVersionContent，长度: ${data.output.length}`)
          } else if (stageType === 'review') {
            setReviewReportContent(data.output)
            console.log(`🔄 质量评审阶段完成，已同步 reviewReportContent，长度: ${data.output.length}`)
          } else if (stageType === 'content') {
            setContentDraftContent(data.output)
            console.log(`🔄 内容创作阶段完成，已同步 contentDraftContent，长度: ${data.output.length}`)
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
            console.log(`💬 对话历史已更新，阶段: ${stageType}`)
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
      console.log('📈 收到任务进度:', data)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('📈 生成下一章任务进度:', data.progress, data.message)
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
        console.log(`📍 生成下一章: 自动切换到 ${targetStage} 阶段 (进度: ${progress}%)`)

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
        setSnackbarSeverity('info' as any)
        setSnackbarOpen(true)
      }
    })

    // 监听任务完成
    workflowWebSocket.onTaskComplete((data) => {
      console.log('✅ 收到任务完成:', data)

      // 🆕 处理扩展大纲/人物任务完成
      const taskId = data.task_id || ''
      if (taskId.startsWith('expand-outline')) {
        console.log('✅ 大纲扩展任务完成，刷新数据...')
        // 刷新大纲内容
        if (projectId) {
          const token = localStorage.getItem('access_token')
          fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
            headers: { 'Authorization': `Bearer ${token}` },
          }).then(res => res.json()).then(batchData => {
            const stages = batchData.stages
            if (stages.plot_outline) {
              setStructureContent(stages.plot_outline)
              dispatch(updateStageOutput({ stage: 'structure', output: stages.plot_outline }))
              console.log('✅ 大纲内容已更新')
            }
          }).catch(err => console.error('❗ 刷新大纲失败:', err))
          
          // 🔥 关键修复：刷新章节列表
          dispatch(fetchChapters(parseInt(projectId)))
        }
        setSnackbarMessage('✅ 大纲扩展完成！')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
        return
      }
      
      if (taskId.startsWith('expand-characters')) {
        console.log('✅ 人物扩展任务完成，刷新数据...')
        // 刷新人物内容
        if (projectId) {
          const token = localStorage.getItem('access_token')
          fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
            headers: { 'Authorization': `Bearer ${token}` },
          }).then(res => res.json()).then(batchData => {
            const stages = batchData.stages
            if (stages.characters) {
              setCharacterContent(stages.characters)
              console.log('✅ 人物内容已更新')
            }
          }).catch(err => console.error('❗ 刷新人物失败:', err))
          
          // 🔥 关键修复：刷新章节列表
          dispatch(fetchChapters(parseInt(projectId)))
        }
        setSnackbarMessage('✅ 人物扩展完成！')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
        return
      }

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('✅ 生成下一章任务完成:', data.result)

        // 🔥 关键修复：显式标记所有阶段为完成
        const allStages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
        allStages.forEach(stage => {
          dispatch(updateStageStatus({ stage, status: 'completed' }))
          console.log(`✅ 阶段 ${stage} 已标记为完成`)
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
        const chapter = data.result?.chapter
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
      if (data.result && typeof data.result === 'object') {
        const result = data.result as any
        if (result.output) {
          console.log('✅ 任务结果包含输出内容，可能需要更新 Redux')
          // 如果后端传递了 stage 信息，可以在这里更新
          // dispatch(updateStageOutput({ stage: data.stage, output: result.output }))
        }
      }

      setSnackbarMessage('任务完成！')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      console.log('💡 WebSocket 任务完成通知已处理，无需轮询')
    })

    // 监听任务错误
    workflowWebSocket.onTaskError((data) => {
      console.log('❌ 收到任务错误:', data)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('❌ 生成下一章任务失败:', data.error)

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
      console.log('🤖 收到 Agent 状态:', data)

      // ✅ 更新 Redux 状态
      // 尝试从 agent_id 或 agent_name 推断阶段
      let stage: StageType | null = data.stage as StageType || null
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
          status: data.status as any,  // 强制类型转换
          progress: data.progress || 0,
          message: data.message || ''
        }))
        console.log(`✅ Agent 状态已更新: ${agentId} (${stage}) -> ${data.status}`)
      }
    })

    // 🆕 监听流式输出开始（移除自动打开对话框，直接在主页面显示）
    workflowWebSocket.onStreamStart((data) => {
      console.log('🌊 流式输出开始:', data)
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
      const stageType = data.stage as StageType

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      console.log(`🌊 stream_chunk: stage=${stageType}, taskId=${currentTaskId}, chunkLen=${data.chunk?.length}`)

      // 🆕 如果是"生成下一章"任务，使用临时流式内容状态
      if (currentTaskId) {
        // 生成下一章模式：流式内容存入临时状态（不保存到数据库缓存）
        console.log(`📝 追加流式内容到 Redux, 当前总长度=${currentState.workflow.generateNextChapter.streamContent.length}`)
        dispatch(appendGenerateNextChapterStream(data.chunk))
        return
      }

      // 🔄 普通模式：实时更新对应阶段的内容显示（仅更新缓存，对话框打开时再同步）
      if (stageType === 'content') {
        setContentDraftContent(prev => prev + data.chunk)
      } else if (stageType === 'review') {
        setReviewReportContent(prev => prev + data.chunk)
      } else if (stageType === 'iteration') {
        setFinalVersionContent(prev => prev + data.chunk)
      }
    })

    // 🆕 监听流式输出结束
    workflowWebSocket.onStreamEnd((data) => {
      console.log('🌊 流式输出结束:', data)
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
      console.log('🔌 清理 WebSocket 监听器（保持连接）...')
      // 🔔 修改：使用新方法，只移除监听器，不断开连接
      workflowWebSocket.removeEventListeners()  // ✅ 使用新方法
      // 🔔 不离开房间，以便在后台继续接收消息
      // if (projectId) {
      //   workflowWebSocket.leaveProject(Number(projectId))  // 🚫 删除此行
      // }
      console.log('✅ WebSocket 连接已保持，可在后台继续接收消息')
    }
  }, [projectId, dispatch])

  // 页面刷新时加载所有已保存的阶段内容和状态
  useEffect(() => {
    if (!projectId) return

    // 🔧 关键修复: 延迟执行，等待Token加载
    const timer = setTimeout(() => {
      const loadAllStageContents = async () => {
        try {
          // 🔧 关键修复: 确保Token存在才执行请求
          const token = localStorage.getItem('access_token')
          if (!token) {
            console.log('🔐 用户未登录，等待登录后自动加载内容')
            return
          }

          console.log('📍 开始加载所有阶段内容...')

          // 🔧 关键修复：使用局部变量跟踪恢复状态，避免异步状态更新问题
          let hasRestoredRunningTask = false
          let restoredStage: StageType | null = null

          // 🔔 步骤1：检查是否有正在运行的任务
          try {
            const runningTasksResponse = await fetch(
              `/api/v1/workflow/project/${projectId}/running-tasks`,
              {
                headers: {
                  'Authorization': `Bearer ${token}`,
                },
              }
            )

            if (runningTasksResponse.ok) {
              const runningTasksData = await runningTasksResponse.json()
              const runningTasks = runningTasksData.running_tasks || []
              const timeoutTasks = runningTasksData.timeout_tasks || []

              // 🔧 新增：显示超时任务提示
              if (timeoutTasks.length > 0) {
                console.log(`⏰ 检测到 ${timeoutTasks.length} 个超时任务已被自动清理`)
                setSnackbarMessage(`⏰ 检测到 ${timeoutTasks.length} 个超时任务已被自动清理`)
                setSnackbarSeverity('warning')
                setSnackbarOpen(true)
              }

              if (runningTasks.length > 0) {
                console.log(`🔍 发现 ${runningTasks.length} 个正在运行的任务，开始恢复...`)

                // 恢复最新的任务
                const latestTask = runningTasks[0]
                const taskType = latestTask.task_type

                // 从 task_type 提取 stage （例如："workflow_stage_concept" -> "concept"）
                const stageName = taskType.replace('workflow_stage_', '')
                const stageType = stageName as StageType

                // 🔧 验证 stageType 是否有效
                const validStages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
                if (!validStages.includes(stageType)) {
                  console.warn(`⚠️  无效的阶段类型: ${stageType}，跳过恢复`)
                } else {
                  // 🔧 新增：显示任务运行时间
                  const ageMinutes = latestTask.age_minutes || 0
                  console.log(`📌 恢复任务: ${latestTask.task_id}, 阶段: ${stageType}, 已运行: ${ageMinutes.toFixed(1)}分钟`)

                  // 更新状态
                  setCurrentTaskId(latestTask.task_id)
                  setIsRunning(true)
                  // 🔧 关键修复：使用局部变量记录恢复状态，避免后续代码覆盖
                  hasRestoredRunningTask = true
                  restoredStage = stageType

                  dispatch(setCurrentStage(stageType))
                  dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

                  // 🔔 关键：开始轮询任务状态（如果 WebSocket 未连接）
                  if (!workflowWebSocket.isConnected()) {
                    console.log('⚠️  WebSocket 未连接，启动轮询模式')
                    pollTaskStatus(latestTask.task_id, stageType)
                  } else {
                    console.log('✅ WebSocket 已连接，等待实时通知')
                  }

                  setSnackbarMessage(`✅ 工作流已恢复，继续执行 ${stageNames[stageType]}（已运行${ageMinutes.toFixed(0)}分钟）`)
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                }
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
            }
          } catch (error) {
            console.warn('⚠️  检查运行中任务失败:', error)
          }

          // ⚡ 步骤2：性能优化: 使用批量接口一次性获取所有阶段内容
          const batchResponse = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          })

          if (batchResponse.ok) {
            const batchData = await batchResponse.json()
            const stages = batchData.stages

            // 设置所有按钮内容
            if (stages.concept) {
              setConceptContent(stages.concept)
              console.log(`✅ 故事概念已加载，内容长度: ${stages.concept.length}`)
            }
            if (stages.world_setting) {
              setWorldContent(stages.world_setting)
              console.log(`✅ 世界观设定已加载，内容长度: ${stages.world_setting.length}`)
            }
            if (stages.characters) {
              setCharacterContent(stages.characters)
              console.log(`✅ 人物设定已加载，内容长度: ${stages.characters.length}`)
            }
            if (stages.plot_outline) {
              setStructureContent(stages.plot_outline)
              console.log(`✅ 情节大纲已加载，内容长度: ${stages.plot_outline.length}`)
            }
            if (stages.chapter_draft) {
              setContentDraftContent(stages.chapter_draft)
              console.log(`✅ 章节初稿已加载，内容长度: ${stages.chapter_draft.length}`)
            }
            if (stages.final_version) {
              setFinalVersionContent(stages.final_version)
              console.log(`✅ 最终版本已加载，内容长度: ${stages.final_version.length}`)
            }
            if (stages.review_report) {
              setReviewReportContent(stages.review_report)
              console.log(`✅ 评审报告已加载，内容长度: ${stages.review_report.length}`)
            }

            // 更新Redux store的output字段，用于输出预览显示
            if (stages.concept) {
              dispatch(updateStageOutput({ stage: 'concept', output: stages.concept }))
            }
            if (stages.plot_outline) {
              dispatch(updateStageOutput({ stage: 'structure', output: stages.plot_outline }))
            }
            if (stages.chapter_draft) {
              dispatch(updateStageOutput({ stage: 'content', output: stages.chapter_draft }))
            }
            if (stages.review_report) {
              dispatch(updateStageOutput({ stage: 'review', output: stages.review_report }))
            }
            if (stages.final_version) {
              dispatch(updateStageOutput({ stage: 'iteration', output: stages.final_version }))
            }

            console.log('⚡ 批量加载完成，性能大幅提升！')
          } else {
            console.warn('⚠️  批量接口不可用，使用传统方式加载')
            // 备用方案: 使用原有的分别请求方式
            // 这里可以保留原有代码逻辑
          }

          // 加载阶段状态
          try {
            const statusResponse = await fetch(`/api/v1/workflow/${projectId}/stage-status`, {
              headers: {
                'Authorization': `Bearer ${token}`,
              },
            })

            if (statusResponse.ok) {
              const statusData = await statusResponse.json()
              console.log('📊 阶段状态数据:', statusData)

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
              const stageOrder: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']

              Object.entries(stageStatusMap).forEach(([dbField, stageName]) => {
                const status = statusData[dbField]
                if (status === 'completed') {
                  // 🔧 关键修复：如果该阶段正在运行，不要覆盖为 completed
                  if (hasRestoredRunningTask && stageName === restoredStage) {
                    console.log(`⚠️ 跳过更新阶段状态: ${stageName} (当前正在运行)`)
                    // 保持 active 状态，不更新为 completed
                  } else {
                    dispatch(updateStageStatus({ stage: stageName, status: 'completed' }))
                    console.log(`✅ 阶段状态已更新: ${stageName} = completed`)
                    lastCompletedStage = stageName
                  }
                }
              })

              // 🔧 关键修复：使用局部变量判断，避免 React 状态异步更新问题
              // 如果已经恢复了运行中的任务，就不要再设置当前阶段了
              if (hasRestoredRunningTask) {
                console.log(`🔒 跳过设置当前阶段，因为已恢复运行中的任务: ${restoredStage}`)
              } else {
                // 🆕 从 Redux 读取"生成下一章"任务状态（关键：避免闭包中的旧值）
                const reduxState = store.getState()
                const generateNextChapterTaskId = reduxState.workflow.generateNextChapter.taskId
                const isGeneratingNextChapter = reduxState.workflow.generateNextChapter.isRunning

                // 🆕 如果正在执行"生成下一章"任务，设置为 structure 阶段（章节规划从这里开始）
                if (generateNextChapterTaskId || isGeneratingNextChapter) {
                  dispatch(setCurrentStage('structure'))
                  console.log(`🔒 检测到"生成下一章"任务 (taskId=${generateNextChapterTaskId})，设置当前阶段为: structure`)
                } else if (lastCompletedStage) {
                  // 普通模式：根据完成状态设置当前阶段
                  const lastCompletedIndex = stageOrder.indexOf(lastCompletedStage)
                  if (lastCompletedIndex < stageOrder.length - 1) {
                    // 还有未完成的阶段,显示下一个阶段
                    const nextStage = stageOrder[lastCompletedIndex + 1]
                    dispatch(setCurrentStage(nextStage))
                    console.log(`📍 设置当前阶段为: ${nextStage} (最后完成阶段 ${lastCompletedStage} 的下一个)`)
                  } else {
                    // 所有阶段都完成了,显示最后一个阶段
                    dispatch(setCurrentStage(lastCompletedStage))
                    console.log(`📍 所有阶段已完成,显示最后阶段: ${lastCompletedStage}`)
                  }
                } else {
                  // 没有完成的阶段,显示第一个阶段
                  dispatch(setCurrentStage('concept'))
                  console.log(`📍 没有完成的阶段,显示第一个阶段: concept`)
                }
              }
            } else {
              console.warn('⚠️  无法加载阶段状态')
            }
          } catch (error) {
            console.warn('⚠️  加载阶段状态失败:', error)
          }

          console.log('✅ 所有阶段内容和状态加载完成')
        } catch (error) {
          console.error('❌ 加载阶段内容失败:', error)
          // 不显示错误提示，避免干扰用户体验
        }
      }

      loadAllStageContents()
    }, 100)  // 🔧 延迟100ms，等待localStorage初始化

    // 🔧 清理定时器
    return () => clearTimeout(timer)
  }, [projectId, dispatch])

  // 🆕 自动执行阶段的逻辑（异步模式）
  useEffect(() => {
    if (!isRunning || !projectId) return

    // 如果当前有异步任务正在执行，跳过
    if (currentTaskId) {
      console.log('⏳ 当前有异步任务正在执行，跳过自动执行')
      return
    }

    // 检查当前阶段是否已完成
    const currentStageData = workflow.stages[workflow.currentStage]

    if (currentStageData.status === 'pending') {
      console.log(`🚀 自动执行阶段（异步模式）: ${workflow.currentStage}`)
      executeStageAsync(workflow.currentStage)
    } else if (currentStageData.status === 'completed') {
      // 当前阶段已完成 - 检查是否需要执行下一阶段
      if (workflow.currentStage === 'concept') {
        // 概念阶段完成后暂停自动推进，等待用户决策
        setShowConceptDecisionBar(true)
        setIsRunning(false)
        return
      }
      const currentIndex = stages.indexOf(workflow.currentStage)
      if (currentIndex < stages.length - 1) {
        // 移动到下一阶段
        const nextStage = stages[currentIndex + 1]
        console.log(`✅ 阶段 ${workflow.currentStage} 已完成，移动到下一阶段: ${nextStage}`)
        dispatch(setCurrentStage(nextStage))
        // 注意：不在这里执行，等待下次useEffect触发时执行
      } else {
        // 所有阶段都已完成
        console.log('🎉 所有阶段已完成！')
        setIsRunning(false)

        // 🔧 关键修复：只有在“非生成下一章”流程才自动保存
        if (isGenerateNextChapterFlow) {
          console.log('💾 跳过自动保存（生成下一章已经保存）')
          // 重置标记
          setIsGenerateNextChapterFlow(false)
          // 直接跳转
          console.log('📍 1.5秒后跳转到Dashboard...')
          setTimeout(() => {
            navigate(`/dashboard?projectId=${projectId}`)
          }, 1500)
        } else {
          // 普通工作流，需要自动保存
          console.log('💾 开始自动保存章节...')
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
        console.log('💾 [beforeunload] 使用 sendBeacon 保存记忆')
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

    // ⚠️  暂时禁用：后端尚未实现记忆保存API
    // console.log(`💾 [记忆快照] 功能已禁用，等待后端API实现`)
    // return

    try {
      console.log(`💾 保存记忆快照 [${trigger}]...`)

      // 收集当前工作流状态数据
      const memoryData = {
        messages: conversationHistory,
        current_chapter: workflow.stages.iteration.output ? 1 : null,
        current_scene: workflow.currentStage,
        active_characters: [],
        writing_goal: requirement || '创作小说',
      }

      const response = await fetch(`/api/v1/projects/${projectId}/memories/auto-save`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(memoryData),
      })

      if (response.ok) {
        const savedMemory = await response.json()
        setLastSaveTime(new Date(savedMemory.updated_at))
        console.log(`✅ 记忆快照已保存 [${trigger}]:`, savedMemory.id)

        // 仅在手动保存时显示提示
        if (trigger === 'manual') {
          setSnackbarMessage('✅ 记忆快照已保存')
          setSnackbarSeverity('success')
          setSnackbarOpen(true)
        }
      } else {
        console.error('❌ 保存记忆快照失败')
      }
    } catch (error) {
      console.error('❌ 保存记忆快照异常:', error)
    }
  }

  // 🆕 异步执行阶段函数
  const executeStageAsync = async (stage: StageType) => {
    if (!projectId) return

    try {
      console.log(`🚀 开始异步执行阶段: ${stage}`)

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
      const streamingStages = ['content', 'review', 'iteration']
      const enableStreaming = streamingStages.includes(stage)

      // 🆕 流式输出阶段：清空之前的内容，准备接收流式数据
      if (enableStreaming) {
        console.log(`🌊 阶段 ${stage} 支持流式输出，清空之前的内容`)
        if (stage === 'content') {
          setContentDraftContent('')
        } else if (stage === 'review') {
          setReviewReportContent('')
        } else if (stage === 'iteration') {
          setFinalVersionContent('')
        }
      }

      const response = await fetch('/api/v1/workflow/execute-stage-async', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          stage: stage,
          requirement: requirement || `创作一部小说`,
          enable_streaming: enableStreaming,  // 🆕 启用流式输出
        }),
      })

      if (!response.ok) {
        throw new Error(`提交任务失败: ${response.status}`)
      }

      const data = await response.json()
      const taskId = data.task_id

      if (!taskId) {
        throw new Error('未返回task_id')
      }

      console.log(`✅ 任务已提交: ${taskId}`)
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
        console.log(`📊 进度估算器已启动: ${stage}`)
      }

      // 🆕 检查 WebSocket 是否连接
      if (workflowWebSocket.isConnected()) {
        console.log('💡 WebSocket 已连接，使用实时通知模式（不启动轮询）')
        console.log('   等待 task_complete 或 task_error 事件...')
        // 依赖 WebSocket 事件监听器，不启动轮询
      } else {
        console.log('⚠️  WebSocket 未连接，降级到 HTTP 轮询模式')
        // WebSocket 不可用时启动轮询
        pollTaskStatus(taskId, stage)
      }
    } catch (error) {
      console.error(`❌ 异步执行阶段失败:`, error)
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
        console.log(`🔄 轮询任务状态 [${pollCount}/${maxPolls}]: ${taskId}`)

        const response = await fetch(`/api/v1/workflow/task/${taskId}`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (!response.ok) {
          // 🔧 处理404错误
          if (response.status === 404) {
            consecutiveErrors++
            console.warn(`⚠️  任务不存在 (${consecutiveErrors}/${maxConsecutiveErrors}): ${taskId}`)

            if (consecutiveErrors >= maxConsecutiveErrors) {
              clearInterval(interval)
              setTaskPollingInterval(null)
              setTaskProgress(0)
              setCurrentTaskId(null)

              dispatch(updateStageStatus({ stage, status: 'error' }))

              setSnackbarMessage(`❌ 任务查询失败：后端未找到任务，请检查后端服务是否正常`)
              setSnackbarSeverity('error')
              setSnackbarOpen(true)

              console.error(`❌ 连续${maxConsecutiveErrors}次404错误，停止轮询`)
              return
            }
            // 继续轮询，等待后端任务初始化
            return
          }

          throw new Error(`查询任务状态失败: ${response.status}`)
        }

        // 🔧 成功响应，重置错误计数
        consecutiveErrors = 0

        const data = await response.json()
        console.log(`📊 任务状态:`, data)

        const progress = Math.min(95, pollCount * 3)
        setTaskProgress(progress)

        if (data.status === 'completed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(100)
          setCurrentTaskId(null)

          console.log(`✅ 任务完成:`, data.result)

          dispatch(updateStageStatus({ stage, status: 'completed' }))
          dispatch(updateStageOutput({ stage, output: data.result || '' }))

          // 🔥 关键修复：同步更新组件本地状态（轮询模式）
          const resultContent = data.result || ''
          if (stage === 'iteration' && resultContent) {
            setFinalVersionContent(resultContent)
            console.log(`🔄 [轮询] 迭代优化阶段完成，已同步 finalVersionContent，长度: ${resultContent.length}`)
          } else if (stage === 'review' && resultContent) {
            setReviewReportContent(resultContent)
            console.log(`🔄 [轮询] 质量评审阶段完成，已同步 reviewReportContent，长度: ${resultContent.length}`)
          } else if (stage === 'content' && resultContent) {
            setContentDraftContent(resultContent)
            console.log(`🔄 [轮询] 内容创作阶段完成，已同步 contentDraftContent，长度: ${resultContent.length}`)
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
                console.log('💾 跳过自动保存（生成下一章已经保存）')
                // 重置标记
                setIsGenerateNextChapterFlow(false)
                // 直接跳转
                console.log('📍 1.5秒后跳转到Dashboard...')
                setTimeout(() => {
                  navigate(`/dashboard?projectId=${projectId}`)
                }, 1500)
              } else {
                // 普通工作流，需要自动保存
                console.log('💾 开始自动保存章节...')
                autoSaveChapter()
              }
            }
          }
        } else if (data.status === 'failed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          console.error(`❌ 任务失败:`, data.error)

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

          console.error(`❌ 轮询超时`)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ ${stageNames[stage]}超时，请重试`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)

          setIsRunning(false)
        }
      } catch (error) {
        console.error(`❌ 轮询任务状态失败:`, error)
        // 🔧 其他错误也计入连续错误
        consecutiveErrors++

        if (consecutiveErrors >= maxConsecutiveErrors) {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ 轮询失败: ${error}`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)
        }
      }
    }, 2000)

    setTaskPollingInterval(interval)
  }

  // 🆕 检查项目是否已有内容
  const checkExistingContent = async () => {
    if (!projectId) return false

    try {
      // 获取项目的章节列表
      const response = await apiClient.getChapters(parseInt(projectId))
      const chapters = response.data || []
      const chapterCount = chapters.length

      // 检查是否有概念/大纲等内容（通过workflow状态判断）
      const hasCompletedStages =
        workflow.stages.concept.status === 'completed' ||
        workflow.stages.structure.status === 'completed' ||
        workflow.stages.content.status === 'completed'

      if (chapterCount > 0 || hasCompletedStages) {
        setExistingChaptersCount(chapterCount)
        return true
      }
      return false
    } catch (error) {
      console.error('检查项目内容失败:', error)
      return false
    }
  }

  // 🆕 点击"开始创作"按钮时的处理
  const handleStartButtonClick = async () => {
    const hasContent = await checkExistingContent()
    if (hasContent) {
      // 显示警告对话框
      setShowContentWarningDialog(true)
    } else {
      // 直接打开创作对话框
      setOpenDialog(true)
    }
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
      await dispatch(
        startWorkflow({
          projectId: parseInt(projectId),
          requirement,
          clearExisting: isRestartMode,  // 🆕 传递清空标志
        })
      ).unwrap()
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
    } catch (error) {
      console.error('Failed to start workflow:', error)
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
    } catch (error) {
      console.error('Failed to regenerate stage:', error)
    }
  }

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
      console.error('❌ 项目ID不存在')
      setSnackbarMessage('项目ID不存在')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    // ✅ 设置保存状态
    setSavingChapter(true)

    try {
      console.log('📍 开始保存章节，projectId:', projectId)

      // 🔥 关键修复：从后端API获取最新的迭代阶段内容 - 使用apiClient
      console.log('📍 步骤1: 从后端获取最新的迭代阶段内容...')
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)

      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        console.error('❌ 章节内容为空')
        setSnackbarMessage('没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setSavingChapter(false)  // ✅ 重置保存状态
        return
      }

      console.log('✅ 成功获取迭代阶段内容，长度:', content.length)


      // 如果用户没有输入标题，后端会自动生成
      const titleToSave = chapterTitle.trim() || ''
      console.log('📍 章节标题:', titleToSave || '(自动生成)')

      // 🔥 修复：直接创建章节记录 - 使用apiClient，URL末尾添加斜杠避免307重定向
      console.log('📍 步骤2: 创建章节记录...')
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: content,
        title: titleToSave || undefined, // 如果为空则自动生成
      })

      // axios成功响应（2xx状态码）
      const data = response.data
      console.log('✅ 章节创建成功:', data)

      setSnackbarMessage(`✅ 章节已保存：${data.title} (${data.word_count} 字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 关闭对话框，清空标题
      setShowSaveDialog(false)
      setChapterTitle('')

      // 🔧 修复：1.5秒后跳转到Dashboard页面，并自动展开章节列表
      console.log('📍 1.5秒后跳转到Dashboard并自动展开章节列表...')
      setTimeout(() => {
        console.log('📍 跳转到: /dashboard?projectId=' + projectId)
        navigate(`/dashboard?projectId=${projectId}`)  // 带projectId参数，自动展开章节列表
      }, 1500)
    } catch (error: any) {
      console.error('❌ 保存章节异常:', error)

      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
        console.error('❌ 服务器错误:', error.response.status, error.response.data)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
        console.error('❌ 网络错误: 无响应')
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
        console.error('❌ 请求配置错误:', error.message)
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会重置保存状态
      setSavingChapter(false)
      console.log('🛡️ [保存状态] savingChapter 已设置为 false')
    }
  }

  // 🆕 自动保存章节（无需用户输入标题）
  const autoSaveChapter = async () => {
    if (!projectId) {
      console.error('❌ 项目ID不存在')
      return
    }

    try {
      console.log('💾 开始自动保存章节，projectId:', projectId)

      // 获取最新的迭代阶段内容
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)
      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        console.error('❌ 章节内容为空，跳过自动保存')
        setSnackbarMessage('⚠️ 没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      console.log('✅ 获取内容成功，长度:', content.length)

      // 创建章节记录（标题自动生成）
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: content,
        // 不传title，让后端自动生成
      })

      const data = response.data
      console.log('✅ 自动保存成功:', data)

      // 显示成功提示
      setSnackbarMessage(`✅ 章节已自动保存：${data.title} (${data.word_count} 字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 1.5秒后跳转到Dashboard
      console.log('📍 1.5秒后跳转到Dashboard...')
      setTimeout(() => {
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1500)

    } catch (error: any) {
      console.error('❌ 自动保存章节失败:', error)

      let errorMessage = '自动保存失败'

      if (error.response) {
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
      } else if (error.request) {
        errorMessage = '无法连接到服务器'
      }

      setSnackbarMessage(`❌ ${errorMessage}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }



  // 🆕 点击故事概念按钮 - 切换预览区域显示
  const handleOpenConceptDialog = () => {
    console.log('📍 切换到故事概念预览')
    setSelectedConceptView('concept')
  }

  // 打开情节大纲对话框
  const handleOpenStructureDialog = async () => {
    setShowStructureDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (structureContent && structureContent.trim() !== '') {
      console.log('⚡ 使用缓存的情节大纲内容，长度:', structureContent.length)
      setEditedStructureContent(structureContent)
      return
    }

    // 如果没有缓存，才从API获取
    setStructureLoading(true)

    try {
      console.log('📍 从API获取最新的情节大纲内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/structure/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setStructureContent(data.content || '')
        setEditedStructureContent(data.content || '')
      } else {
        console.error('❌ 获取情节大纲失败，状态码:', response.status)
        setSnackbarMessage('获取情节大纲失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取情节大纲异常:', error)
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
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/structure/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedStructureContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
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
    } catch (error) {
      console.error('Failed to save structure:', error)
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
      console.log('⚡ 使用缓存的章节初稿内容，长度:', contentDraftContent.length)
      setEditedContentDraftContent(contentDraftContent)
      return
    }

    // 如果没有缓存，才从API获取
    setContentLoading(true)

    try {
      console.log('📍 从API获取最新的章节初稿内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 章节初稿已加载，长度:', content.length)
        setContentDraftContent(content)
        setEditedContentDraftContent(content)
      } else {
        console.error('❌ 获取章节初稿失败，状态码:', response.status)
        setSnackbarMessage('获取章节初稿失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取章节初稿异常:', error)
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
      console.log('⚡ 使用缓存的评审报告内容，长度:', reviewReportContent.length)
      setEditedReviewReportContent(reviewReportContent)
      return
    }

    // 如果没有缓存，才从API获取
    setReviewLoading(true)

    try {
      console.log('📍 从API获取最新的评审报告内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 评审报告已加载，长度:', content.length)
        setReviewReportContent(content)
        setEditedReviewReportContent(content)
      } else {
        console.error('❌ 获取评审报告失败，状态码:', response.status)
        setSnackbarMessage('获取评审报告失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取评审报告异常:', error)
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

  // 仅保存评审报告
  const handleSaveOnlyReview = async () => {
    if (!projectId) return

    setReviewSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedReviewReportContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // 更新缓存
        setReviewReportContent(editedReviewReportContent)
        setSnackbarMessage('评审报告已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        const errorData = await response.json().catch(() => ({}))
        setSnackbarMessage(errorData.detail || '保存失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('保存评审报告失败:', error)
      setSnackbarMessage('保存失败')
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
      console.log('📍 开始保存评审报告并继续工作流...')
      const saveResponse = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedReviewReportContent,
          continue_workflow: true,
        }),
      })

      console.log('📍 保存响应状态:', saveResponse.status, saveResponse.ok)

      if (!saveResponse.ok) {
        const errorData = await saveResponse.json().catch(() => ({}))
        console.error('❌ 保存失败:', errorData)
        setSnackbarMessage(errorData.detail || '保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = await saveResponse.json()
      console.log('✅ 保存成功，响应数据:', saveData)

      // ✅ 更新缓存
      setReviewReportContent(editedReviewReportContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'review', output: editedReviewReportContent }))
      dispatch(updateStageStatus({ stage: 'review', status: 'completed' }))

      // ✅ 重置后续阶段状态
      dispatch(resetFollowingStages('review'))

      // ✅ 显示删除章节的消息（如果有的话）
      if (saveData.deleted_chapters_count) {
        setSnackbarMessage(`已删除 ${saveData.deleted_chapters_count} 个章节，正在重新生成...`)
      } else {
        setSnackbarMessage('评审报告已保存，正在启动迭代优化...')
      }
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      handleCloseReviewDialog()

      // ✅ 关键修复：真正调用后端API执行下一阶段（迭代优化）
      setIsRunning(true)
      setTimeout(async () => {
        const nextStage: StageType = 'iteration'
        dispatch(setCurrentStage(nextStage))

        console.log('🚀 使用异步模式继续工作流，下一阶段: iteration')
        executeStageAsync(nextStage)
      }, 1000)
    } catch (error) {
      console.error('❌ 保存评审报告失败:', error)
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
      const saveResponse = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: true,  // 关键：设置为true以触发章节更新逻辑
        }),
      })

      if (!saveResponse.ok) {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = await saveResponse.json();

      // ✅ 更新state，保持已保存的内容
      setContentDraftContent(editedContentDraftContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'content', output: editedContentDraftContent }))
      dispatch(updateStageStatus({ stage: 'content', status: 'completed' }))

      // ✅ 关键修复：重置后续阶段状态
      dispatch(resetFollowingStages('content'))

      // ✅ 显示删除成功的消息（如果有的话）
      if (saveData.deleted_chapter) {
        setSnackbarMessage(`已更新第${saveData.deleted_chapter.chapter_number}章并启动后续工作流...`)
      } else {
        setSnackbarMessage('内容已保存，正在启动后续工作流...')
      }

      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      handleCloseContentDialog()

      // ✅ 关键修复：真正调用后端API执行下一阶段
      setIsRunning(true)
      setTimeout(async () => {
        const nextStage: StageType = 'review'
        dispatch(setCurrentStage(nextStage))

        console.log('🚀 使用异步模式继续工作流...')
        executeStageAsync(nextStage)
      }, 1000)
    } catch (error) {
      console.error('Failed to save content:', error)
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
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
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
    } catch (error) {
      console.error('Failed to save content:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }

  // 🆕 点击世界观设定按钮 - 切换预览区域显示
  const handleOpenWorldDialog = () => {
    console.log('📍 切换到世界观预览')
    setSelectedConceptView('world')
  }

  // 🆕 点击人物设定按钮 - 切换预览区域显示
  const handleOpenCharacterDialog = () => {
    console.log('📍 切换到人物设定预览')
    setSelectedConceptView('character')
  }

  // 打开最终版本对话框
  const handleOpenFinalProduct = async () => {
    setShowFinalVersionDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (finalVersionContent && finalVersionContent.trim() !== '') {
      console.log('⚡ 使用缓存的最终版本内容，长度:', finalVersionContent.length)
      setEditedFinalVersionContent(finalVersionContent)
      return
    }

    // 如果没有缓存，才从API获取
    setFinalVersionLoading(true)

    try {
      console.log('📏 从API获取最新的最终版本内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/iteration/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 最终版本已加载，长度:', content.length)
        setFinalVersionContent(content)
        setEditedFinalVersionContent(content)
      } else {
        console.error('❌ 获取最终版本失败，状态码:', response.status)
        setSnackbarMessage('获取最终版本失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取最终版本异常:', error)
      setSnackbarMessage('获取最终版本失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setFinalVersionLoading(false)
    }
  }

  // 生成下一章（方案3：独立的章节生成工作流）
  const handleGenerateNextChapter = async () => {
    if (!projectId) return

    setGeneratingNextChapter(true)

    try {
      console.log('📍 开始生成下一章（异步模式）...')

      const response = await fetch(`/api/v1/workflow/${projectId}/generate-next-chapter`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
      })

      if (response.ok) {
        const data = await response.json()
        console.log('✅ 异步任务已创建:', data)

        // 后端返回: { task_id, status, message, next_chapter_number }
        const { task_id, next_chapter_number } = data

        // 🆕 使用 Redux action 设置任务状态
        dispatch(startGenerateNextChapter({ taskId: task_id, chapterNumber: next_chapter_number }))
        setIsGenerateNextChapterFlow(true)

        setSnackbarMessage(`🚀 已开始生成第${next_chapter_number}章，请等待...`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 注意：不再设置 setGeneratingNextChapter(false)，等待 WebSocket 完成事件
      } else {
        const errorData = await response.json()
        console.error('❌ 创建生成任务失败:', errorData)

        setSnackbarMessage(errorData.detail || errorData.error || '创建生成任务失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setGeneratingNextChapter(false)
      }
    } catch (error) {
      console.error('❌ 生成下一章异常:', error)
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
      const response = await fetch('/api/v1/workflow/execute-stage-async', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          stage: 'concept',
          regenerate: true,
          targets,
          feedback: feedbackText,
          enable_streaming: false,
        }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        setSnackbarMessage(err.detail || err.error || '提交重新生成失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setIsRunning(false)
        return
      }
      const data = await response.json()
      console.log('✅ 概念阶段重生任务已提交:', data)
      setSnackbarMessage('已提交重新生成，请稍候完成')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      // 等待任务完成后由现有状态/事件再决定是否再次弹出确认
    } catch (error) {
      console.error('提交重新生成异常:', error)
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
      console.log('📏 开始保存最终版本为章节...', {
        projectId,
        contentLength: editedFinalVersionContent.length,
        title: chapterTitleInput,
        token: localStorage.getItem('access_token') ? '存在' : '不存在'
      })

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
      console.log('✅ 章节保存成功:', data)

      // ✅ 关闭对话框
      handleCloseFinalVersionDialog()

      // 显示成功消息（后端直接返回章节对象，不是嵌套在chapter字段中）
      setSnackbarMessage(`✅ 第${data.chapter_number}章已保存：${data.title} (${data.word_count}字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // ✅ 返回 Dashboard 并自动展开章节列表
      setTimeout(() => {
        console.log('📏 返回 Dashboard')
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1000)
    } catch (error: any) {
      // axios错误响应（非2xx状态码或网络错误）
      console.error('❌ 保存章节异常:', error)

      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
        console.error('❌ 服务器错误:', error.response.status, error.response.data)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
        console.error('❌ 网络错误: 无响应')
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
        console.error('❌ 请求配置错误:', error.message)
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会执行
      setSavingChapter(false)
      console.log('🛡️ [保存状态] savingChapter 已设置为 false')
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
    
    console.log('📊 评审按钮显示逻辑:', {
      isConceptStage,
      conceptCompleted,
      conceptActive,
      hasConceptAgentWorking,
      structureStarted,
      hasContent,
      shouldShow,
      '结构阶段状态': workflow.stages.structure.status
    })
  }, [workflow.currentStage, conceptContent, worldContent, workflow.stages.concept.status, workflow.stages.structure.status, workflow.stages.concept.agents])

  return (
    <Container maxWidth="lg" sx={{ py: 2 }}>
      {/* 左侧顶部区域：返回按钮 + 标题 + 项目信息 */}
      <Box sx={{ maxWidth: { xs: '100%', md: 'calc(33.33% - 8px)' }, mb: 3 }}>
        {/* 返回按钮 */}
        <Box sx={{ mb: 3, py: 1 }}>
          <Button
            startIcon={<ArrowBackIcon />}
            onClick={() => {
              // 🔥 返回时清除保存的项目ID
              localStorage.removeItem('lastWorkflowProjectId')
              navigate('/dashboard')
            }}
            variant="outlined"
            size="medium"
            sx={{ py: 1, px: 2 }}
          >
            返回仪表板
          </Button>
        </Box>

        {/* 主标题 */}
        <Box sx={{ mb: 3, py: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 600, lineHeight: 1.4 }}>
            🚀 多Agent小说创作工作流程
          </Typography>
        </Box>

        {/* 项目信息 */}
        {(currentProject || workflow.projectId) && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', py: 1 }}>
            <Typography variant="body1" color="text.secondary">
              当前项目:
            </Typography>
            {currentProject && (
              <Chip
                label={`📝 ${currentProject.title}`}
                color="primary"
                variant="outlined"
                sx={{ fontSize: '0.85rem', height: '32px' }}
              />
            )}
            {workflow.projectId && (
              <Chip
                label={`ID: ${workflow.projectId}`}
                variant="outlined"
                sx={{ height: '32px' }}
              />
            )}
          </Box>
        )}
      </Box>

      {/* 错误提示 */}
      {workflow.error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {workflow.error}
        </Alert>
      )}

      {/* 异步任务进度提示 */}
      {currentTaskId && (
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
      <Grid container spacing={2}>
        {/* 左侧：总进度 + 阶段信息 + Agent状态 */}
        <Grid item xs={12} md={4}>
          {/* 总进度条 - 与右侧 Stepper 对齐 */}
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

          {/* 阶段信息面板（工作步骤说明） */}
          <StageInfoPanel stage={workflow.currentStage} />

          {/* Agent状态 - 与右侧输出预览底部对齐 */}
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

          {/* 开始/暂停操作按钮（Fab样式） */}
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            {!isRunning ? (
              <Tooltip title="开始创作" placement="right">
                <Fab
                  color="primary"
                  onClick={handleStartButtonClick}
                  sx={{
                    width: 56,
                    height: 56,
                    boxShadow: 3,
                    '&:hover': {
                      boxShadow: 6,
                    },
                  }}
                >
                  <PlayArrowIcon />
                </Fab>
              </Tooltip>
            ) : (
              <Tooltip title="暂停" placement="right">
                <Fab
                  color="error"
                  onClick={() => setIsRunning(false)}
                  sx={{
                    width: 56,
                    height: 56,
                    boxShadow: 3,
                    '&:hover': {
                      boxShadow: 6,
                    },
                  }}
                >
                  <PauseIcon />
                </Fab>
              </Tooltip>
            )}
          </Box>

          {/* 🔧 记忆管理面板已隐藏，后台自动保存逻辑保留 */}
        </Grid>

        {/* 右侧：阶段导航 + 输出预览区域（向上移动与返回按钮顶部对齐） */}
        <Grid item xs={12} md={8} sx={{ mt: { xs: 0, md: -22 } }}>
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
                    {stageNames[stage]}
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

        {/* 概念开发阶段：显示"故事概念"、"世界观设定"、"人物设定"按钮 */}
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
          <Button
            variant="outlined"
            onClick={handleOpenReviewDialog}
            disabled={!reviewReportContent && workflow.stages.review.status !== 'completed'}
            startIcon={<ArticleIcon />}
          >
            评审报告
          </Button>
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
              onClick={handleGenerateNextChapter}
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

          {/* 概念开发阶段决策条（UI骨架，已禁用，使用Dialog替代） */}
          {false && (
            <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between', p: 1.5, border: '1px solid', borderColor: 'grey.300', borderRadius: 1.5, bgcolor: 'grey.50' }}>
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                本轮故事概念与世界观设定已生成，请选择下一步操作：
              </Typography>
              <Box sx={{ display: 'flex', gap: 1.5 }}>
                <Button
                  variant="contained"
                  color="primary"
                  size="small"
                  disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
                  onClick={() => {
                    // 推进工作流到结构阶段
                    setShowConceptDecisionBar(false)
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
                  size="small"
                  disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
                  onClick={() => setShowRegenerateDialog(true)}
                >
                  重新生成
                </Button>
              </Box>
            </Box>
          )}
        </Grid>
      </Grid>

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
        maxWidth="sm"
        fullWidth
      >
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            输入创作需求
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

          <TextField
            fullWidth
            multiline
            rows={4}
            placeholder="请输入您的创作需求，例如：创作一部关于时空旅行的科幻小说..."
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
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
            本轮故事概念与世界观设定已生成，请选择下一步操作：
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
            <Button
              variant="text"
              disabled={workflow.stages.concept.status === 'active' || workflow.stages.concept.agents.some(a => a.status === 'working')}
              onClick={() => navigate(`/knowledge-base/${projectId}`)}
            >
              去知识库拓展人物
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
            placeholder="补充意见（选填）"
            value={regenerateFeedback}
            onChange={(e) => setRegenerateFeedback(e.target.value)}
            sx={{ mb: 2 }}
          />

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>快捷意见：</Typography>
            <Button size="small" variant="outlined" onClick={() => setRegenerateFeedback(prev => (prev ? prev + '；' : '') + '加强权谋与历史真实感')}>权谋+真实</Button>
            <Button size="small" variant="outlined" onClick={() => setRegenerateFeedback(prev => (prev ? prev + '；' : '') + '降低爽点，增强人物动机合理性')}>降低爽点</Button>
            <Button size="small" variant="outlined" onClick={() => setRegenerateFeedback(prev => (prev ? prev + '；' : '') + '世界观内部规则一致')}>规则一致</Button>
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <Chip
              label={autoInferFeedback ? '自动推断：开' : '自动推断：关'}
              size="small"
              variant="outlined"
              onClick={() => setAutoInferFeedback((v) => !v)}
            />
          </Box>

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>目标：</Typography>
            <Button variant={regenerateTarget === 'both' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('both')}>两者</Button>
            <Button variant={regenerateTarget === 'story' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('story')}>仅故事概念</Button>
            <Button variant={regenerateTarget === 'world' ? 'contained' : 'outlined'} size="small" onClick={() => setRegenerateTarget('world')}>仅世界观</Button>
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

