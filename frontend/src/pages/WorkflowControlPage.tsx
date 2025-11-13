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
  IconButton,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
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
import EditIcon from '@mui/icons-material/Edit'
import DownloadIcon from '@mui/icons-material/Download'
import HistoryIcon from '@mui/icons-material/History'
import CompareArrowsIcon from '@mui/icons-material/CompareArrows'
import Switch from '@mui/material/Switch'
import FormControlLabel from '@mui/material/FormControlLabel'
import Chip from '@mui/material/Chip'
import Snackbar from '@mui/material/Snackbar'
import MuiAlert from '@mui/material/Alert'
import { RootState, AppDispatch } from '@/store/store'
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
} from '@/store/slices/workflowSlice'
import { fetchProject } from '@/store/slices/projectSlice'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import AgentStatusIndicator from '@/components/workflow/AgentStatusIndicator'
import { workflowWebSocket } from '@/services/websocket'
import { apiClient } from '@/services/api'  // ✅ 添加apiClient导入
import {
  calculateProgress,
  estimateRemainingTime,
  formatRemainingTime,
  saveHistory,
  getHistory,
  clearHistory,
  exportToMarkdown,
  exportChapterBreakdownToCSV,
  downloadFile,
} from '@/utils/expansionHelpers'
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

  // 故事概念对话框状态
  const [showConceptDialog, setShowConceptDialog] = useState(false)
  const [conceptContent, setConceptContent] = useState('')
  const [editedContent, setEditedContent] = useState('')
  const [conceptLoading, setConceptLoading] = useState(false)
  const [conceptSaving, setConceptSaving] = useState(false)

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

  // 世界观设定对话框状态
  const [showWorldDialog, setShowWorldDialog] = useState(false)
  const [worldContent, setWorldContent] = useState('')
  const [editedWorldContent, setEditedWorldContent] = useState('')
  const [worldLoading, setWorldLoading] = useState(false)
  const [worldSaving, setWorldSaving] = useState(false)

  // 人物设定对话框状态
  const [showCharacterDialog, setShowCharacterDialog] = useState(false)
  const [characterContent, setCharacterContent] = useState('')
  const [editedCharacterContent, setEditedCharacterContent] = useState('')
  const [characterLoading, setCharacterLoading] = useState(false)
  const [characterSaving, setCharacterSaving] = useState(false)

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

  // 🆕 自动保存记忆状态
  const [autoSaveEnabled, setAutoSaveEnabled] = useState(true)
  const [lastSaveTime, setLastSaveTime] = useState<Date | null>(null)
  // 对话历史记录（功能暂未完全实现，仅用于记忆快照功能）
  const [conversationHistory] = useState<Array<{role: string, content: string}>>([])

  // 🆕 大纲和人物扩展功能状态
  const [showExpandOutlineDialog, setShowExpandOutlineDialog] = useState(false)
  const [expandingOutline, setExpandingOutline] = useState(false)
  const [expandedOutlineData, setExpandedOutlineData] = useState<any>(null)
  const [currentChapterCount, setCurrentChapterCount] = useState(0)  // 🆕 当前章节数
  
  const [showExpandCharactersDialog, setShowExpandCharactersDialog] = useState(false)
  const [expandingCharacters, setExpandingCharacters] = useState(false)
  const [expandedCharactersData, setExpandedCharactersData] = useState<any>(null)
  const [currentCharacterCount, setCurrentCharacterCount] = useState(0)  // 🆕 当前人物数

  // 🆕 进度显示优化
  const [expansionProgress, setExpansionProgress] = useState(0)  // 扩展进度 0-100
  const [expansionStartTime, setExpansionStartTime] = useState<number | null>(null)  // 开始时间
  const [estimatedTimeRemaining, setEstimatedTimeRemaining] = useState<number | null>(null)  // 预计剩余时间（秒）
  
  // 🆕 历史版本管理
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [characterHistory, setCharacterHistory] = useState<Array<{timestamp: number, content: string, characterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)
  const [historyType, setHistoryType] = useState<'outline' | 'character'>('outline')
  
  // 🆕 编辑功能
  const [isEditingExpansion, setIsEditingExpansion] = useState(false)
  const [editedExpansionContent, setEditedExpansionContent] = useState('')

  // 🆕 添加大纲编辑状态
  const [isEditingOutline, setIsEditingOutline] = useState(false)

  // 🆕 进度估算器相关状态
  const [progressEstimator, setProgressEstimator] = useState<ProgressEstimator | null>(null)
  const [stageDurations, setStageDurations] = useState<StageDurations | null>(null)
  const [estimatedProgress, setEstimatedProgress] = useState(0)
  const [estimatedRemainingTime, setEstimatedRemainingTime] = useState(0)

  // 🆕 初始化进度估算器
  useEffect(() => {
    const initProgressEstimator = async () => {
      try {
        const durations = await statisticsService.getStageDurations(projectId ? Number(projectId) : undefined)
        console.log('📊 获取到阶段耗时统计:', durations)
        setStageDurations(durations)

        const estimator = new ProgressEstimator(durations)
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

  // 🔥 初始化加载历史记录
  useEffect(() => {
    const outlineHistoryData = getHistory('outline')
    const characterHistoryData = getHistory('character')
    setOutlineHistory(outlineHistoryData)
    setCharacterHistory(characterHistoryData)
    console.log(`💾 已加载历史记录: 大纲${outlineHistoryData.length}条, 人物${characterHistoryData.length}条`)
  }, [])

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
        
        if (data.output) {
          dispatch(updateStageOutput({ stage: stageType, output: data.output }))
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

      // 🆕 更新进度估算器的真实进度
      if (progressEstimator) {
        progressEstimator.updateRealProgress(data.progress)
      } else {
        // 如果没有进度估算器，直接设置进度
        setTaskProgress(data.progress)
      }

      if (data.message) {
        setSnackbarMessage(data.message)
        setSnackbarSeverity('info' as any)
        setSnackbarOpen(true)
      }
    })

    // 监听任务完成
    workflowWebSocket.onTaskComplete((data) => {
      console.log('✅ 收到任务完成:', data)

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

      // 🆕 停止进度估算器
      if (progressEstimator) {
        progressEstimator.stop()
      }

      setCurrentTaskId(null)
      setTaskProgress(0)

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

              if (runningTasks.length > 0) {
                console.log(`🔍 发现 ${runningTasks.length} 个正在运行的任务，开始恢复...`)

                // 恢复最新的任务
                const latestTask = runningTasks[0]
                const taskType = latestTask.task_type

                // 从 task_type 提取 stage （例如："workflow_stage_concept" -> "concept"）
                const stageName = taskType.replace('workflow_stage_', '')
                const stageType = stageName as StageType

                console.log(`📌 恢复任务: ${latestTask.task_id}, 阶段: ${stageType}`)

                // 更新状态
                setCurrentTaskId(latestTask.task_id)
                setIsRunning(true)
                dispatch(setCurrentStage(stageType))
                dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

                // 🔔 关键：开始轮询任务状态（如果 WebSocket 未连接）
                if (!workflowWebSocket.isConnected()) {
                  console.log('⚠️  WebSocket 未连接，启动轮询模式')
                  pollTaskStatus(latestTask.task_id, stageType)
                } else {
                  console.log('✅ WebSocket 已连接，等待实时通知')
                }

                setSnackbarMessage(`✅ 工作流已恢复，继续执行 ${stageNames[stageType]}`)
                setSnackbarSeverity('success')
                setSnackbarOpen(true)
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
                  dispatch(updateStageStatus({ stage: stageName, status: 'completed' }))
                  console.log(`✅ 阶段状态已更新: ${stageName} = completed`)
                  lastCompletedStage = stageName
                }
              })

              // 🔧 修复：如果没有正在运行的任务,设置当前阶段为最后完成的阶段的下一个阶段
              // 如果所有阶段都完成了,则显示最后一个阶段
              if (!isRunning && !currentTaskId) {
                if (lastCompletedStage) {
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

  // 🆕 页面卸载前保存记忆
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (autoSaveEnabled && projectId) {
        saveMemorySnapshot('beforeUnload')
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [autoSaveEnabled, projectId])

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
          setEstimatedProgress(Math.round(state.displayProgress))
          setEstimatedRemainingTime(Math.round(state.remainingTime))
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

  // 🆕 渐进式扩展大纲函数（每次扩展5-10章）
  const handleExpandOutline = async () => {
    if (!projectId) return

    try {
      setExpandingOutline(true)
      setExpansionProgress(0)
      setExpansionStartTime(Date.now())
      setEstimatedTimeRemaining(null)
      
      // 🔥 关键修复：先打开对话框，再开始扩展
      setShowExpandOutlineDialog(true)
      setExpandedOutlineData(null)  // 清空旧数据
      
      console.log('📖 开始渐进式扩展大纲...')

      // 从当前阶段获取数据
      let currentOutline = structureContent || workflow.stages.structure.output || ''
      const worldSetting = worldContent || workflow.stages.concept.output?.world_setting || ''
      const characters = characterContent || workflow.stages.concept.output?.characters || ''

      if (!currentOutline) {
        setSnackbarMessage('⚠️ 请先完成结构设计阶段，生成情节大纲')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        setExpandingOutline(false)
        setShowExpandOutlineDialog(false)
        return
      }

      // 🆕 循环调用API，直到AI建议停止
      let chapterCount = currentChapterCount
      let shouldContinue = true
      let totalIterations = 0
      const maxIterations = 10  // 防止无限循环

      while (shouldContinue && totalIterations < maxIterations) {
        totalIterations++
        const increment = Math.floor(Math.random() * 6) + 5  // 随机5-10章
        
        // 🔥 更新进度
        const progress = calculateProgress(totalIterations, maxIterations)
        setExpansionProgress(progress)
        
        // 🔥 估算剩余时间
        if (expansionStartTime) {
          const remaining = estimateRemainingTime(expansionStartTime, totalIterations, maxIterations)
          setEstimatedTimeRemaining(remaining)
        }
        
        console.log(`🔄 第${totalIterations}次扩展：从 ${chapterCount} 章扩展 ${increment} 章... (进度: ${progress}%)`)

        const response = await fetch('/api/v1/workflow/expand-outline', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            project_id: parseInt(projectId),
            current_outline: currentOutline,
            world_setting: worldSetting,
            characters: characters,
            current_chapter_count: chapterCount,
            increment: increment
          }),
        })

        if (!response.ok) {
          throw new Error(`扩展大纲失败: ${response.status}`)
        }

        const data = await response.json()
        console.log(`✅ 第${totalIterations}次扩展完成，当前章节数: ${data.current_chapter_count}`)

        // 更新状态
        currentOutline = data.expanded_outline
        chapterCount = data.current_chapter_count
        shouldContinue = data.should_continue

        // 显示进度
        setSnackbarMessage(`📝 已扩展到 ${chapterCount} 章${shouldContinue ? '，继续扩展...' : '，AI建议停止'}`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 如果AI建议停止，显示原因
        if (!shouldContinue) {
          console.log(`🛑 AI庻议停止扩展：${data.continue_reason}`)
          setExpandedOutlineData({
            ...data,
            stop_reason: data.continue_reason
          })
          break
        }

        setExpandedOutlineData(data)
      }

      // 保存最终结果
      console.log('💾 开始保存扩展结果...')
      
      setStructureContent(currentOutline)
      setCurrentChapterCount(chapterCount)
      
      // 🔥 保存到历史记录
      const historyRecord = {
        timestamp: Date.now(),
        content: currentOutline,
        chapterCount: chapterCount
      }
      saveHistory('outline', currentOutline, chapterCount)
      setOutlineHistory(prev => [...prev, historyRecord])
      
      console.log('✅ 状态已更新，当前阶段:', workflow.currentStage)
      setExpansionProgress(100)

      setSnackbarMessage(`✅ 大纲扩展完成！共 ${chapterCount} 章（${totalIterations}次扩展）`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('❌ 扩展大纲失败:', error)
      setSnackbarMessage(`扩展大纲失败: ${error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExpandingOutline(false)
      setExpansionProgress(0)
      setEstimatedTimeRemaining(null)
    }
  }

  // 🆕 渐进式扩展人物函数（每次扩展3-6个）
  const handleExpandCharacters = async () => {
    if (!projectId) return

    try {
      setExpandingCharacters(true)
      console.log('👥 开始渐进式扩展人物...')

      // 从当前阶段获取数据
      let mainCharacters = characterContent || workflow.stages.concept.output?.characters || ''
      const worldSetting = worldContent || workflow.stages.concept.output?.world_setting || ''
      const plotOutline = structureContent || workflow.stages.structure.output || ''

      if (!mainCharacters) {
        setSnackbarMessage('⚠️ 请先完成概念开发阶段，生成人物设定')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        return
      }

      if (!plotOutline) {
        setSnackbarMessage('⚠️ 建议先扩展大纲，再扩展人物')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        return
      }

      // 🆕 循环调用API，直到AI建议停止
      let characterCount = currentCharacterCount
      let shouldContinue = true
      let totalIterations = 0
      const maxIterations = 8  // 防止无限循环

      while (shouldContinue && totalIterations < maxIterations) {
        totalIterations++
        const increment = Math.floor(Math.random() * 4) + 3  // 随机3-6个
        
        console.log(`🔄 第${totalIterations}次扩展：从 ${characterCount} 个扩展 ${increment} 个...`)

        const response = await fetch('/api/v1/workflow/expand-characters', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            project_id: parseInt(projectId),
            main_characters: mainCharacters,
            world_setting: worldSetting,
            plot_outline: plotOutline,
            current_character_count: characterCount,
            increment: increment
          }),
        })

        if (!response.ok) {
          throw new Error(`扩展人物失败: ${response.status}`)
        }

        const data = await response.json()
        console.log(`✅ 第${totalIterations}次扩展完成，当前人物数: ${data.current_character_count}`)
        console.log('🔍 人物扩展响应数据:', {
          current_character_count: data.current_character_count,
          character_relationships_length: data.character_relationships?.length || 0,
          role_distribution: data.role_distribution,
          all_characters_length: typeof data.all_characters === 'string' ? data.all_characters.length : data.all_characters?.length || 0
        })

        // 更新状态
        mainCharacters = data.all_characters
        characterCount = data.current_character_count
        shouldContinue = data.should_continue

        // 显示进度
        setSnackbarMessage(`👥 已扩展到 ${characterCount} 个人物${shouldContinue ? '，继续扩展...' : '，AI建议停止'}`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 如果AI建议停止，显示原因
        if (!shouldContinue) {
          console.log(`🛑 AI建议停止扩展：${data.continue_reason}`)
          setExpandedCharactersData({
            ...data,
            stop_reason: data.continue_reason
          })
          break
        }

        setExpandedCharactersData(data)
      }

      // 保存最终结果
      const charactersText = Array.isArray(mainCharacters) 
        ? JSON.stringify(mainCharacters, null, 2)
        : mainCharacters
      
      setCharacterContent(charactersText)
      setCurrentCharacterCount(characterCount)

      // 打开结果对话框
      setShowExpandCharactersDialog(true)

      setSnackbarMessage(`✅ 人物扩展完成！共 ${characterCount} 个（${totalIterations}次扩展）`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('❌ 扩展人物失败:', error)
      setSnackbarMessage(`扩展人物失败: ${error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExpandingCharacters(false)
    }
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
        })
      ).unwrap()
      setOpenDialog(false)
      setIsRunning(true)
      setIsStarting(false)  // 启动完成，隐藏加载状态
    } catch (error) {
      console.error('Failed to start workflow:', error)
      setIsStarting(false)  // 启动失败，隐藏加载状态
      setSnackbarMessage('启动工作流失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 🔥 导出大纲为Markdown
  const handleExportOutlineMarkdown = () => {
    if (!expandedOutlineData) return
    
    const markdown = exportToMarkdown(
      expandedOutlineData.expanded_outline,
      `${currentProject?.title || '小说'} - 大纲扩展`,
      {
        '章节数': currentChapterCount,
        '扩展时间': new Date().toLocaleString(),
        '项目ID': projectId
      }
    )
    downloadFile(markdown, `大纲扩展_${currentChapterCount}章_${Date.now()}.md`, 'text/markdown')
    
    setSnackbarMessage('✅ 已导出为 Markdown')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 导出章节分解为CSV
  const handleExportChapterCSV = () => {
    if (!expandedOutlineData?.chapter_breakdown) return
    
    const chapterBreakdown = typeof expandedOutlineData.chapter_breakdown === 'string'
      ? expandedOutlineData.chapter_breakdown
      : JSON.stringify(expandedOutlineData.chapter_breakdown)
    
    const csv = exportChapterBreakdownToCSV(chapterBreakdown)
    downloadFile(csv, `章节分解_${currentChapterCount}章_${Date.now()}.csv`, 'text/csv')
    
    setSnackbarMessage('✅ 已导出为 Excel/CSV')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 开始编辑大纲
  const handleStartEditOutline = () => {
    setIsEditingExpansion(true)
    setEditedExpansionContent(expandedOutlineData?.expanded_outline || '')
    setHistoryType('outline')
  }

  // 🔥 保存编辑的大纲
  const handleSaveEditedOutline = () => {
    setStructureContent(editedExpansionContent)
    setIsEditingExpansion(false)
    
    // 更新当前对话框数据
    setExpandedOutlineData({
      ...expandedOutlineData,
      expanded_outline: editedExpansionContent
    })
    
    // 保存到历史
    const historyRecord = {
      timestamp: Date.now(),
      content: editedExpansionContent,
      chapterCount: currentChapterCount
    }
    saveHistory('outline', editedExpansionContent, currentChapterCount)
    setOutlineHistory(prev => [...prev, historyRecord])
    
    setSnackbarMessage('✅ 编辑已保存')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 查看历史记录
  const handleShowHistory = (type: 'outline' | 'character') => {
    setHistoryType(type)
    setShowHistoryDialog(true)
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



  // 打开故事概念对话框
  const handleOpenConceptDialog = async () => {
    setShowConceptDialog(true)
    
    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (conceptContent && conceptContent.trim() !== '') {
      console.log('⚡ 使用缓存的故事概念内容，长度:', conceptContent.length)
      setEditedContent(conceptContent)
      return
    }
    
    // 如果没有缓存，才从API获取
    setConceptLoading(true)

    try {
      console.log('📍 从API获取最新的故事概念内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/concept/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 故事概念已加载，长度:', content.length)
        setConceptContent(content)
        setEditedContent(content)
      } else {
        console.error('❌ 获取故事概念失败，状态码:', response.status)
        setSnackbarMessage('获取故事概念失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取故事概念异常:', error)
      setSnackbarMessage('获取故事概念失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptLoading(false)
    }
  }

  // 关闭故事概念对话框
  const handleCloseConceptDialog = () => {
    setShowConceptDialog(false)
    // 不清空 conceptContent，保持已保存的内容
    setEditedContent('')  // 只清空编辑状态
  }

  // 保存并继续

  // 仅保存
  const handleSaveOnly = async () => {
    if (!projectId) return

    setConceptSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/concept/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setConceptContent(editedContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 关闭对话框
        handleCloseConceptDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save concept:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptSaving(false)
    }
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
      const response = await fetch(`/api/workflow/${projectId}/stage/content/content`, {
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

  // 打开世界观设定对话框
  const handleOpenWorldDialog = async () => {
    setShowWorldDialog(true)
    
    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (worldContent && worldContent.trim() !== '') {
      console.log('⚡ 使用缓存的世界观设定内容，长度:', worldContent.length)
      setEditedWorldContent(worldContent)
      return
    }
    
    // 如果没有缓存，才从API获取
    setWorldLoading(true)

    try {
      console.log('📍 从API获取最新的世界观设定内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/world_builder/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 世界观设定已加载，长度:', content.length)
        setWorldContent(content)
        setEditedWorldContent(content)
      } else {
        console.error('❌ 获取世界观设定失败，状态码:', response.status)
        setSnackbarMessage('获取世界观设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取世界观设定异常:', error)
      setSnackbarMessage('获取世界观设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldLoading(false)
    }
  }

  // 关闭世界观设定对话框
  const handleCloseWorldDialog = () => {
    setShowWorldDialog(false)
    // 不清空 worldContent，保持已保存的内容
    setEditedWorldContent('')  // 只清空编辑状态
  }

  // 保存并继续（世界观设定）

  // 仅保存（世界观设定）
  const handleSaveOnlyWorld = async () => {
    if (!projectId) return

    setWorldSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/world_builder/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedWorldContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setWorldContent(editedWorldContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseWorldDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save world setting:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldSaving(false)
    }
  }

  // 打开人物设定对话框
  const handleOpenCharacterDialog = async () => {
    setShowCharacterDialog(true)
    
    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (characterContent && characterContent.trim() !== '') {
      console.log('⚡ 使用缓存的人物设定内容，长度:', characterContent.length)
      setEditedCharacterContent(characterContent)
      return
    }
    
    // 如果没有缓存，才从API获取
    setCharacterLoading(true)

    try {
      console.log('📍 从API获取最新的人物设定内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/character_designer/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 人物设定已加载，长度:', content.length)
        setCharacterContent(content)
        setEditedCharacterContent(content)
      } else {
        console.error('❌ 获取人物设定失败，状态码:', response.status)
        setSnackbarMessage('获取人物设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取人物设定异常:', error)
      setSnackbarMessage('获取人物设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterLoading(false)
    }
  }

  // 关闭人物设定对话框
  const handleCloseCharacterDialog = () => {
    setShowCharacterDialog(false)
    // 不清空 characterContent，保持已保存的内容
    setEditedCharacterContent('')  // 只清空编辑状态
  }

  // 保存并继续（人物设定）

  // 仅保存（人物设定）
  const handleSaveOnlyCharacter = async () => {
    if (!projectId) return

    setCharacterSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/character_designer/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedCharacterContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setCharacterContent(editedCharacterContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseCharacterDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save character:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterSaving(false)
    }
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
      console.log('📍 开始生成下一章...')
      
      const response = await fetch(`/api/v1/workflow/${projectId}/generate-next-chapter`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
      })

      if (response.ok) {
        const data = await response.json()
        console.log('✅ 生成下一章成功:', data)
        
        // 🔧 关键修复：设置标记，表示这是“生成下一章”流程（已经保存）
        setIsGenerateNextChapterFlow(true)
        
        setSnackbarMessage(`✅ 已开始生成第${data.next_chapter_number}章，正在跳转到内容创作阶段...`)
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 跳转到内容创作阶段
        setTimeout(() => {
          dispatch(setCurrentStage('content'))
          setIsRunning(true) // 启动自动执行
        }, 1000)
      } else {
        const errorData = await response.json()
        console.error('❌ 生成下一章失败:', errorData)
        
        setSnackbarMessage(errorData.error || '生成下一章失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 生成下一章异常:', error)
      setSnackbarMessage('生成下一章失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setGeneratingNextChapter(false)
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

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* 返回按钮 */}
      <Box sx={{ mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
          variant="outlined"
        >
          返回仪表板
        </Button>
      </Box>

      {/* 标题和进度 */}
      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <Typography variant="h4">
            🚀 多Agent小说创作工作流程
          </Typography>
          {/* 🎯 任务3：显示当前工作流使用的项目 */}
          {currentProject && (
            <Chip
              label={`📝 ${currentProject.title}`}
              color="primary"
              variant="outlined"
              sx={{ fontSize: '0.9rem', height: '32px' }}
            />
          )}
          {workflow.projectId && (
            <Chip
              label={`ID: ${workflow.projectId}`}
              size="small"
              variant="outlined"
            />
          )}
        </Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="body1">
            总体进度: {workflow.overallProgress}%
          </Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {!isRunning && (
              <Button
                variant="contained"
                color="primary"
                startIcon={<PlayArrowIcon />}
                onClick={() => setOpenDialog(true)}
              >
                开始创作
              </Button>
            )}
            {isRunning && (
              <Button
                variant="contained"
                color="error"
                startIcon={<PauseIcon />}
                onClick={() => setIsRunning(false)}
              >
                暂停
              </Button>
            )}
          </Box>
        </Box>
        <LinearProgress variant="determinate" value={workflow.overallProgress} />
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
                {estimatedRemainingTime > 0 && (
                  <Typography variant="caption" color="text.secondary">
                    预计剩余: {Math.ceil(estimatedRemainingTime)}秒
                  </Typography>
                )}
              </Box>
              <LinearProgress variant="determinate" value={taskProgress} />
            </Box>
          </Box>
        </Alert>
      )}

      {/* 阶段导航 */}
      <Paper sx={{ p: 3, mb: 4 }}>
        <Stepper activeStep={currentStageIndex}>
          {stages.map((stage) => (
            <Step key={stage} completed={workflow.stages[stage].status === 'completed'}>
              <StepLabel>{stageNames[stage]}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Paper>

      {/* 主内容区域 */}
      <Grid container spacing={3}>
        {/* 左侧：阶段详情 */}
        <Grid item xs={12} md={8}>
          <StageDetailPanel 
            stage={workflow.currentStage}
          />
        </Grid>

        {/* 右侧：Agent状态 */}
        <Grid item xs={12} md={4}>
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>
                📊 Agent状态
              </Typography>
              {workflow.stages[workflow.currentStage].agents.map((agent) => (
                <AgentStatusIndicator key={agent.id} agent={agent} />
              ))}
            </CardContent>
          </Card>

          {/* 🆕 记忆管理面板 */}
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>
                🧠 记忆管理
              </Typography>
              
              {/* 自动保存开关 */}
              <FormControlLabel
                control={
                  <Switch
                    checked={autoSaveEnabled}
                    onChange={(e) => setAutoSaveEnabled(e.target.checked)}
                    color="primary"
                  />
                }
                label="自动保存"
                sx={{ mb: 1 }}
              />
              
              {/* 最后保存时间 */}
              {lastSaveTime && (
                <Typography variant="caption" display="block" sx={{ mb: 2, color: 'text.secondary' }}>
                  最后保存：{lastSaveTime.toLocaleTimeString()}
                </Typography>
              )}
              
              {/* 手动保存按钮 */}
              <Button
                fullWidth
                variant="outlined"
                startIcon={<SaveIcon />}
                onClick={() => saveMemorySnapshot('manual')}
                disabled={!projectId}
                sx={{ mb: 1 }}
              >
                手动保存快照
              </Button>
              
              {/* 设置提示 */}
              <Typography variant="caption" display="block" sx={{ color: 'text.secondary' }}>
                {autoSaveEnabled ? '✅ 每5分钟自动保存' : '⚠️ 自动保存已关闭'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* 控制按钮 */}
      <Box sx={{ mt: 4, display: 'flex', gap: 2, justifyContent: 'center' }}>
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
            {/* 🆕 扩展人物按钮 */}
            <Tooltip 
              title="💡 建议先点击下方'📖 扩展情节大纲'，再扩展人物，这样生成的角色会更契合剧情需求。每次增加3-6个角色，直到AI判断不需要继续扩展。" 
              placement="top"
              arrow
            >
              <span>
                <Button
                  variant="contained"
                  color="secondary"
                  onClick={handleExpandCharacters}
                  disabled={!characterContent || !worldContent || !structureContent || expandingCharacters}
                  startIcon={expandingCharacters ? <CircularProgress size={20} /> : <PeopleIcon />}
                >
                  {expandingCharacters ? '扩展中...' : `👥 扩展人物${currentCharacterCount > 0 ? ` (当前${currentCharacterCount}个)` : ''}`}
                </Button>
              </span>
            </Tooltip>
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
            {/* 🆕 扩展大纲按钮 */}
            <Tooltip 
              title="💡 渐进式扩展大纲，每次增加5-10章，直到AI判断不需要继续扩展。建议在有一定内容后再扩展人物。" 
              placement="top"
              arrow
            >
              <span>
                <Button
                  variant="contained"
                  color="secondary"
                  onClick={handleExpandOutline}
                  disabled={!structureContent || !worldContent || !characterContent || expandingOutline}
                  startIcon={expandingOutline ? <CircularProgress size={20} /> : <ArticleIcon />}
                >
                  {expandingOutline ? '扩展中...' : `📖 扩展情节大纲${currentChapterCount > 0 ? ` (当前${currentChapterCount}章)` : ''}`}
                </Button>
              </span>
            </Tooltip>
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
          /* 质量评审阶段：不显示任何按钮 */
          null
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

      {/* 故事概念对话框 */}
      <Dialog open={showConceptDialog} onClose={handleCloseConceptDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📖 故事概念文档
          </Typography>

          {conceptLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                placeholder="故事概念文本内容..."
                sx={{ mb: 2 }}
                disabled={conceptSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseConceptDialog}
                  disabled={conceptSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnly}
                  disabled={conceptSaving}
                  startIcon={conceptSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {conceptSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </>
          )}
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

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
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

      {/* 世界观设定对话框 */}
      <Dialog open={showWorldDialog} onClose={handleCloseWorldDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🌍 世界观设定文档
          </Typography>

          {worldLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedWorldContent}
                onChange={(e) => setEditedWorldContent(e.target.value)}
                placeholder="世界观设定文本内容..."
                sx={{ mb: 2 }}
                disabled={worldSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseWorldDialog}
                  disabled={worldSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnlyWorld}
                  disabled={worldSaving}
                  startIcon={worldSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {worldSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 人物设定对话框 */}
      <Dialog open={showCharacterDialog} onClose={handleCloseCharacterDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            👥 人物设定文档
          </Typography>

          {characterLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedCharacterContent}
                onChange={(e) => setEditedCharacterContent(e.target.value)}
                placeholder="人物设定文本内容..."
                sx={{ mb: 2 }}
                disabled={characterSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseCharacterDialog}
                  disabled={characterSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnlyCharacter}
                  disabled={characterSaving}
                  startIcon={characterSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {characterSaving ? '保存中...' : '保存'}
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

      {/* 🆕 扩展大纲结果对话框 */}
      <Dialog open={showExpandOutlineDialog} onClose={() => {
        console.log('🔒 关闭扩展大纲对话框...')
        console.log('   关闭前当前阶段:', workflow.currentStage)
        setShowExpandOutlineDialog(false)
        console.log('   关闭后当前阶段:', workflow.currentStage)
      }} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              📖 扩展大纲结果 - 已扩展至{currentChapterCount}章
            </Typography>
            
            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="编辑大纲">
                <span>
                  <IconButton
                    onClick={() => {
                      setIsEditingOutline(true)
                      setEditedExpansionContent(expandedOutlineData || '')
                    }}
                    color="primary"
                    disabled={expandingOutline || !expandedOutlineData}
                  >
                    <EditIcon />
                  </IconButton>
                </span>
              </Tooltip>
              
              <Tooltip title="导出为 Markdown">
                <IconButton
                  onClick={handleExportOutlineMarkdown}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* 🔥 进度条 */}
          {expandingOutline && (
            <Box sx={{ mb: 2 }}>
              <LinearProgress variant="determinate" value={expansionProgress} />
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1 }}>
                <Typography variant="body2" color="textSecondary">
                  扩展进度: {expansionProgress}%
                </Typography>
                {estimatedTimeRemaining && (
                  <Typography variant="body2" color="textSecondary">
                    预计剩余时间: {Math.round(estimatedTimeRemaining / 1000)}秒
                  </Typography>
                )}
              </Box>
            </Box>
          )}

          {/* 🔥 扩展结果展示 */}
          {expandedOutlineData ? (
            <TextField
              fullWidth
              multiline
              rows={15}
              value={isEditingOutline ? editedExpansionContent : expandedOutlineData}
              onChange={(e) => setEditedExpansionContent(e.target.value)}
              disabled={!isEditingOutline || expandingOutline}
              sx={{ mb: 2 }}
              InputProps={{
                style: {
                  fontFamily: 'monospace',
                  fontSize: '0.875rem',
                }
              }}
            />
          ) : expandingOutline ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <Alert severity="info">暂无扩展结果</Alert>
          )}

          {/* 🔥 按钮组 */}
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              onClick={() => {
                console.log('👉 点击"取消"按钮...')
                console.log('   关闭前当前阶段:', workflow.currentStage)
                setShowExpandOutlineDialog(false)
                console.log('   关闭后当前阶段:', workflow.currentStage)
              }}
              disabled={expandingOutline}
            >
              取消
            </Button>
            
            {isEditingOutline ? (
              <Button
                variant="contained"
                onClick={async () => {
                  // 保存编辑后的内容
                  setExpandedOutlineData(editedExpansionContent)
                  setIsEditingOutline(false)
                  // 可以在这里添加保存到服务器的逻辑
                }}
                disabled={expandingOutline}
                startIcon={expandingOutline ? <CircularProgress size={20} /> : <SaveIcon />}
              >
                {expandingOutline ? '保存中...' : '保存'}
              </Button>
            ) : (
              <Button
                variant="contained"
                onClick={() => {
                  console.log('👉 点击"关闭"按钮...')
                  console.log('   关闭前当前阶段:', workflow.currentStage)
                  setShowExpandOutlineDialog(false)
                  console.log('   关闭后当前阶段:', workflow.currentStage)
                }}
              >
                关闭
              </Button>
            )}
          </Box>
        </Box>
      </Dialog>

      {/* 🆕 扩展人物结果对话框 */}
      <Dialog open={showExpandCharactersDialog} onClose={() => setShowExpandCharactersDialog(false)} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              👥 扩展人物结果 - 已扩展至{currentCharacterCount}个角色
            </Typography>
            
            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="编辑人物">
                <span>
                  <IconButton
                    onClick={() => {
                      setIsEditingExpansion(true)
                      setEditedExpansionContent(expandedCharactersData || '')
                    }}
                    color="primary"
                    disabled={expandingCharacters || !expandedCharactersData}
                  >
                    <EditIcon />
                  </IconButton>
                </span>
              </Tooltip>
              
              <Tooltip title="查看历史版本">
                <IconButton
                  onClick={() => handleShowHistory('character')}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
              
              <Tooltip title="导出为 Markdown">
                <IconButton
                  onClick={handleExportOutlineMarkdown}
                  color="primary"
                  disabled={expandingCharacters || !expandedCharactersData}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* 🔥 进度条 */}
          {expandingCharacters && (
            <Box sx={{ mb: 2 }}>
              <LinearProgress variant="determinate" value={expansionProgress} />
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1 }}>
                <Typography variant="body2" color="textSecondary">
                  扩展进度: {expansionProgress}%
                </Typography>
                {estimatedTimeRemaining && (
                  <Typography variant="body2" color="textSecondary">
                    预计剩余时间: {Math.round(estimatedTimeRemaining / 1000)}秒
                  </Typography>
                )}
              </Box>
            </Box>
          )}

          {/* 🔥 扩展结果展示 */}
          {expandedCharactersData ? (
            <TextField
              fullWidth
              multiline
              rows={15}
              value={isEditingExpansion ? editedExpansionContent : expandedCharactersData}
              onChange={(e) => setEditedExpansionContent(e.target.value)}
              disabled={!isEditingExpansion || expandingCharacters}
              sx={{ mb: 2 }}
              InputProps={{
                style: {
                  fontFamily: 'monospace',
                  fontSize: '0.875rem',
                }
              }}
            />
          ) : expandingCharacters ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <Alert severity="info">暂无扩展结果</Alert>
          )}

          {/* 🔥 按钮组 */}
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              onClick={() => setShowExpandCharactersDialog(false)}
              disabled={expandingCharacters}
            >
              关闭
            </Button>
            
            {isEditingExpansion ? (
              <Button
                variant="contained"
                onClick={async () => {
                  // 保存编辑后的内容
                  setExpandedCharactersData(editedExpansionContent)
                  setIsEditingExpansion(false)
                  // 可以在这里添加保存到服务器的逻辑
                }}
                disabled={expandingCharacters}
                startIcon={expandingCharacters ? <CircularProgress size={20} /> : <SaveIcon />}
              >
                {expandingCharacters ? '保存中...' : '保存'}
              </Button>
            ) : (
              <Button
                variant="contained"
                onClick={handleExpandCharacters}
                disabled={expandingCharacters}
                startIcon={expandingCharacters ? <CircularProgress size={20} /> : <SaveIcon />}
              >
                {expandingCharacters ? '保存中...' : '保存到项目'}
              </Button>
            )}
          </Box>
        </Box>
      </Dialog>

      {/* 🆕 扩展大纲结果对话框 */}
      <Dialog open={showExpandOutlineDialog} onClose={() => {
        console.log('🔒 关闭扩展大纲对话框...')
        console.log('   关闭前当前阶段:', workflow.currentStage)
        setShowExpandOutlineDialog(false)
        console.log('   关闭后当前阶段:', workflow.currentStage)
      }} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              📖 扩展大纲结果 - 已扩展至{currentChapterCount}章
            </Typography>
            
            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="编辑大纲">
                <span>
                  <IconButton
                    onClick={handleStartEditOutline}
                    color="primary"
                    disabled={expandingOutline || !expandedOutlineData}
                  >
                    <EditIcon />
                  </IconButton>
                </span>
              </Tooltip>
              
              <Tooltip title="导出为 Markdown">
                <IconButton
                  onClick={handleExportOutlineMarkdown}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
              
              <Tooltip title="导出章节为 CSV">
                <IconButton
                  onClick={handleExportChapterCSV}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData?.chapter_breakdown}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
              
              <Tooltip title="查看历史版本">
                <IconButton
                  onClick={() => handleShowHistory('outline')}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* 🔥 进度条显示 */}
          {expandingOutline && (
            <Box sx={{ mb: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  扩展进度：{expansionProgress}%
                </Typography>
                {estimatedTimeRemaining !== null && estimatedTimeRemaining > 0 && (
                  <Typography variant="body2" color="text.secondary">
                    预计剩余时间：{formatRemainingTime(estimatedTimeRemaining)}
                  </Typography>
                )}
              </Box>
              <LinearProgress variant="determinate" value={expansionProgress} sx={{ height: 8, borderRadius: 1 }} />
              
              {/* 🔥 扩展中占位内容 */}
              <Box sx={{ mt: 3, textAlign: 'center', py: 4 }}>
                <CircularProgress size={60} />
                <Typography variant="h6" sx={{ mt: 2, color: 'text.secondary' }}>
                  🚀 正在扩展大纲...
                </Typography>
                <Typography variant="body2" sx={{ mt: 1, color: 'text.disabled' }}>
                  AI正在生成章节内容，请耐心等待
                </Typography>
              </Box>
            </Box>
          )}

          {!expandingOutline && expandedOutlineData && (
            <Box>
              {/* 🔥 大纲摘要（智能提取） */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  📊 大纲摘要
                </Typography>
                <Box sx={{ 
                  bgcolor: 'background.default', 
                  p: 2, 
                  borderRadius: 1,
                  maxHeight: 200,
                  overflow: 'auto'
                }}>
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-line', color: 'text.secondary', lineHeight: 1.8 }}>
                    {(() => {
                      const outline = expandedOutlineData.expanded_outline || '';
                      // 智能提取前500字作为摘要
                      const summary = outline.substring(0, 500).trim();
                      return summary ? summary + (outline.length > 500 ? '...' : '') : '大纲内容为空';
                    })()}
                  </Typography>
                </Box>
                <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.disabled' }}>
                  💡 提示：完整内容请查看下方"完整扩展大纲"
                </Typography>
              </Paper>

              {/* 🔥 章节概览（可折叠） */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📚 章节概览（共{expandedOutlineData.current_chapter_count || expandedOutlineData.target_chapters || 0}章）
                  </Typography>
                  <Button 
                    size="small" 
                    onClick={() => {
                      const elem = document.getElementById('chapter-breakdown-content');
                      if (elem) {
                        elem.style.display = elem.style.display === 'none' ? 'block' : 'none';
                      }
                    }}
                  >
                    {(() => {
                      const elem = document.getElementById('chapter-breakdown-content');
                      return elem && elem.style.display === 'none' ? '展开' : '折叠';
                    })()}
                  </Button>
                </Box>
                <Box id="chapter-breakdown-content" sx={{ maxHeight: 300, overflow: 'auto' }}>
                  {/* 🔧 兼容性处理：支持字符串和数组两种格式 */}
                  {typeof expandedOutlineData.chapter_breakdown === 'string' && expandedOutlineData.chapter_breakdown ? (
                    // 渐进式扩展返回的是字符串
                    <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1 }}>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-line', fontSize: '0.875rem', lineHeight: 1.6 }}>
                        {expandedOutlineData.chapter_breakdown}
                      </Typography>
                    </Box>
                  ) : Array.isArray(expandedOutlineData.chapter_breakdown) ? (
                    // 一次性扩展返回的是数组
                    expandedOutlineData.chapter_breakdown.map((chapter: any, index: number) => (
                      <Box key={index} sx={{ mb: 2, p: 1.5, bgcolor: 'background.default', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                        <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
                          第{chapter.chapter_number}章：{chapter.title}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
                          {chapter.summary}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.primary', display: 'block', mt: 0.5 }}>
                          🔑 关键事件：{chapter.key_events}
                        </Typography>
                      </Box>
                    ))
                  ) : (
                    <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1, textAlign: 'center' }}>
                      <Typography variant="body2" color="text.secondary">
                        📝 章节分解内容请查看下方"完整扩展大纲"
                      </Typography>
                    </Box>
                  )}
                </Box>
              </Paper>

              {/* 🔥 完整大纲（增强版） */}
              <Paper elevation={2} sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📝 完整扩展大纲
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">
                      {expandedOutlineData.expanded_outline?.length || 0} 字
                    </Typography>
                    <Button 
                      size="small" 
                      onClick={() => {
                        navigator.clipboard.writeText(expandedOutlineData.expanded_outline || '');
                        setSnackbarMessage('✅ 已复制到剪贴板');
                        setSnackbarSeverity('success');
                        setSnackbarOpen(true);
                      }}
                    >
                      📋 复制
                    </Button>
                  </Box>
                </Box>
                
                {/* 🔥 编辑模式切换 */}
                {isEditingExpansion ? (
                  <Box>
                    <TextField
                      fullWidth
                      multiline
                      minRows={12}
                      maxRows={20}
                      value={editedExpansionContent}
                      onChange={(e) => setEditedExpansionContent(e.target.value)}
                      sx={{ 
                        mb: 2, 
                        bgcolor: 'background.paper',
                        '& .MuiInputBase-root': {
                          fontSize: '0.9rem',
                          lineHeight: 1.8
                        }
                      }}
                      placeholder="编辑扩展大纲..."
                    />
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="caption" color="text.secondary">
                        已输入 {editedExpansionContent.length} 字
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Button
                          onClick={() => {
                            setIsEditingExpansion(false);
                            setEditedExpansionContent(expandedOutlineData?.expanded_outline || '');
                          }}
                          size="small"
                        >
                          取消
                        </Button>
                        <Button
                          variant="contained"
                          onClick={handleSaveEditedOutline}
                          size="small"
                          startIcon={<SaveIcon />}
                        >
                          保存编辑
                        </Button>
                      </Box>
                    </Box>
                  </Box>
                ) : (
                  <Box sx={{ 
                    bgcolor: 'background.default', 
                    p: 2, 
                    borderRadius: 1,
                    maxHeight: 400,
                    overflow: 'auto',
                    border: '1px solid',
                    borderColor: 'divider'
                  }}>
                    <Typography 
                      variant="body2" 
                      sx={{ 
                        whiteSpace: 'pre-line', 
                        fontSize: '0.9rem', 
                        lineHeight: 1.8,
                        color: 'text.primary'
                      }}
                    >
                      {expandedOutlineData.expanded_outline || '大纲内容为空'}
                    </Typography>
                  </Box>
                )}
              </Paper>
            </Box>
          )}

          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              variant="contained"
              onClick={() => {
                console.log('👉 点击“关闭”按钮...')
                console.log('   关闭前当前阶段:', workflow.currentStage)
                setShowExpandOutlineDialog(false)
                console.log('   关闭后当前阶段:', workflow.currentStage)
              }}
            >
              关闭
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 🆕 扩展人物结果对话框 */}
      <Dialog open={showExpandCharactersDialog} onClose={() => setShowExpandCharactersDialog(false)} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              👥 扩展人物结果 - 已扩展至{currentCharacterCount}个角色
            </Typography>
            
            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="查看历史版本">
                <IconButton
                  onClick={() => handleShowHistory('character')}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {expandedCharactersData && (
            <Box>
              {/* 角色分布 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  📊 角色分布
                </Typography>
                {expandedCharactersData.role_distribution && typeof expandedCharactersData.role_distribution === 'object' && Object.keys(expandedCharactersData.role_distribution).length > 0 ? (
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    {Object.entries(expandedCharactersData.role_distribution).map(([role, count]: [string, any]) => (
                      <Box key={role} sx={{ 
                        bgcolor: 'primary.main', 
                        color: 'white', 
                        px: 2, 
                        py: 1, 
                        borderRadius: 1 
                      }}>
                        <Typography variant="body2">
                          {role}: {count}人
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    {typeof expandedCharactersData.role_distribution === 'string' && expandedCharactersData.role_distribution 
                      ? expandedCharactersData.role_distribution 
                      : '暂无角色分布数据'}
                  </Typography>
                )}
              </Paper>

              {/* 角色列表 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  👤 所有角色（共{expandedCharactersData.current_character_count || expandedCharactersData.target_count || 0}人）
                </Typography>
                <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
                  {/* 🔧 兼容性处理：支持字符串和数组两种格式 */}
                  {typeof expandedCharactersData.all_characters === 'string' ? (
                    // 渐进式扩展返回的是字符串
                    <TextField
                      fullWidth
                      multiline
                      rows={12}
                      value={expandedCharactersData.all_characters}
                      InputProps={{ readOnly: true }}
                      sx={{ bgcolor: 'background.default' }}
                    />
                  ) : Array.isArray(expandedCharactersData.all_characters) ? (
                    // 一次性扩展返回的是数组
                    expandedCharactersData.all_characters.map((character: any, index: number) => (
                      <Box key={index} sx={{ mb: 2, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
                        <Typography variant="body1" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                          {character.name}（{character.role}）
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                          {character.description}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'primary.main' }}>
                          核心特质：{character.core_traits}
                        </Typography>
                      </Box>
                    ))
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      暂无人物数据
                    </Typography>
                  )}
                </Box>
              </Paper>

              {/* 人物关系网络 */}
              <Paper elevation={2} sx={{ p: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  🔗 人物关系网络
                </Typography>
                {expandedCharactersData.character_relationships && expandedCharactersData.character_relationships.trim() !== '' ? (
                  <TextField
                    fullWidth
                    multiline
                    rows={12}
                    value={expandedCharactersData.character_relationships}
                    InputProps={{ readOnly: true }}
                    sx={{ bgcolor: 'background.default' }}
                  />
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    正在生成人物关系网络...
                  </Typography>
                )}
              </Paper>
            </Box>
          )}

          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              variant="contained"
              onClick={() => setShowExpandCharactersDialog(false)}
            >
              关闭
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 🔥 历史记录对话框 */}
      <Dialog open={showHistoryDialog} onClose={() => setShowHistoryDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon />
            <Typography variant="h6">
              {historyType === 'outline' ? '大纲扩展' : '人物扩展'}历史记录
            </Typography>
          </Box>
        </DialogTitle>
        
        <DialogContent dividers>
          {(() => {
            const history = historyType === 'outline' ? outlineHistory : characterHistory
            
            if (history.length === 0) {
              return (
                <Box sx={{ py: 4, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    暂无历史记录
                  </Typography>
                </Box>
              )
            }
            
            return (
              <List>
                {history.slice().reverse().map((record, index) => {
                  const actualIndex = history.length - 1 - index
                  const count = historyType === 'outline' 
                    ? (record as any).chapterCount 
                    : (record as any).characterCount
                  
                  return (
                    <ListItem
                      key={record.timestamp}
                      sx={{
                        flexDirection: 'column',
                        alignItems: 'flex-start',
                        borderBottom: index < history.length - 1 ? 1 : 0,
                        borderColor: 'divider',
                        py: 2
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', mb: 1 }}>
                        <Typography variant="subtitle2">
                          版本 #{actualIndex + 1} - {new Date(record.timestamp).toLocaleString()}
                        </Typography>
                        <Typography variant="caption" color="primary">
                          {historyType === 'outline' ? `${count}章` : `${count}人`}
                        </Typography>
                      </Box>
                      
                      <TextField
                        fullWidth
                        multiline
                        maxRows={6}
                        value={record.content}
                        InputProps={{ readOnly: true }}
                        size="small"
                        sx={{ bgcolor: 'background.default' }}
                      />
                      
                      <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                        <Button
                          size="small"
                          startIcon={<CompareArrowsIcon />}
                          onClick={() => {
                            if (historyType === 'outline') {
                              setStructureContent(record.content)
                              setExpandedOutlineData({
                                ...expandedOutlineData,
                                expanded_outline: record.content,
                                current_chapter_count: (record as any).chapterCount
                              })
                            }
                            setSnackbarMessage(`✅ 已回滚到版本 #${actualIndex + 1}`)
                            setSnackbarSeverity('success')
                            setSnackbarOpen(true)
                            setShowHistoryDialog(false)
                          }}
                        >
                          回滚到此版本
                        </Button>
                        
                        <Button
                          size="small"
                          onClick={() => {
                            const markdown = exportToMarkdown(
                              record.content,
                              `${historyType === 'outline' ? '大纲' : '人物'}扩展 - 版本#${actualIndex + 1}`,
                              {
                                '版本号': `#${actualIndex + 1}`,
                                '保存时间': new Date(record.timestamp).toLocaleString(),
                                [historyType === 'outline' ? '章节数' : '人物数']: count
                              }
                            )
                            downloadFile(markdown, `历史版本_${actualIndex + 1}_${record.timestamp}.md`, 'text/markdown')
                            setSnackbarMessage('✅ 已导出历史版本')
                            setSnackbarSeverity('success')
                            setSnackbarOpen(true)
                          }}
                        >
                          导出此版本
                        </Button>
                      </Box>
                    </ListItem>
                  )
                })}
              </List>
            )
          })()}
        </DialogContent>
        
        <DialogActions>
          <Button onClick={() => setShowHistoryDialog(false)}>
            关闭
          </Button>
          {(historyType === 'outline' ? outlineHistory : characterHistory).length > 0 && (
            <Button
              color="error"
              onClick={() => {
                if (window.confirm(`确定要清除所有${historyType === 'outline' ? '大纲' : '人物'}扩展历史记录吗？`)) {
                  clearHistory(historyType)
                  if (historyType === 'outline') {
                    setOutlineHistory([])
                  } else {
                    setCharacterHistory([])
                  }
                  setSnackbarMessage('✅ 历史记录已清除')
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                  setShowHistoryDialog(false)
                }
              }}
            >
              清除所有历史
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Container>
  )
}

