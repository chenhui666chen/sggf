import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Grid,
  Button,
  Typography,
  Box,
  Dialog,
  TextField,
  Select,
  MenuItem,
  FormControl,
  FormHelperText,
  InputLabel,
  CircularProgress,
  Drawer,
  List,
  ListItem,
  ListItemText,
  Divider,
  IconButton,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Chip,
  Tooltip,
  Menu,
  Snackbar,
  Alert,
  alpha,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import CloseIcon from '@mui/icons-material/Close'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import HubIcon from '@mui/icons-material/Hub'
import { RootState, AppDispatch } from '@/store/store'
import {
  fetchProjects,
  createProject,
  deleteProject,
  updateProject,
} from '@/store/slices/projectSlice'
import { performLogout } from '@/store/slices/authSlice'
import { startGenerateNextChapter } from '@/store/slices/workflowSlice'
import { apiClient } from '@/services/api'
import { logger } from '@/utils/logger'
import { buildStoryExpansionCompletionMessage } from '@/utils/storyExpansionFeedback'
import {
  getStoryExpansionResultFromTaskComplete,
  isStoryExpansionTaskId,
} from '@/utils/storyExpansionEvents'
import { useFormats } from '@/i18n'
import { useTranslation } from 'react-i18next'
import { readStoredWorkflowGenerationModel } from '@/utils/workflowGenerationModelPreference'
import { extractCircuitBreakerPause } from '@/utils/workflowCircuitBreaker'
import { GENRE_COLORS, getBookVizPalette } from '@/pages/dashboard/bookVizData'

function extractFilenameFromContentDisposition(contentDisposition?: string | null, fallback: string = 'download.bin') {
  const header = String(contentDisposition || '').trim()
  if (!header) return fallback

  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      return utf8Match[1]
    }
  }

  const asciiMatch = header.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1]?.trim() || fallback
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.URL.revokeObjectURL(url)
}

// 自定义大纲占位提示：按「题材|篇幅」匹配节奏建议，长篇题材单独走长篇文案
const PACE_HINT_KEYS: Record<string, string> = {
  '修仙|long': 'dashboard.createDialog.paceCultivationLong',
  '修仙': 'dashboard.createDialog.paceCultivation',
  '玄幻|long': 'dashboard.createDialog.paceXuanhuanLong',
  '玄幻': 'dashboard.createDialog.paceXuanhuan',
  '奇幻|long': 'dashboard.createDialog.paceFantasyLong',
  '奇幻': 'dashboard.createDialog.paceFantasy',
  '悬疑': 'dashboard.createDialog.paceSuspense',
  '都市': 'dashboard.createDialog.paceUrban',
  '言情': 'dashboard.createDialog.paceRomance',
  '耽美': 'dashboard.createDialog.paceDanmei',
  '科幻': 'dashboard.createDialog.paceSciFi',
  '纯文学': 'dashboard.createDialog.paceLiterary',
}

// 篇幅规划选项：value 保持后端契约，选项文案与推荐章节范围同源
interface PlannedLengthOption {
  value: string
  optionKey: string
  hintLabelKey: string
  minChapters: number
  maxChapters: number
}

const PLANNED_LENGTH_OPTIONS: PlannedLengthOption[] = [
  { value: 'short', optionKey: 'dashboard.createDialog.lengthTypes.short', hintLabelKey: 'dashboard.createDialog.lengthShort', minChapters: 3, maxChapters: 30 },
  { value: 'mid', optionKey: 'dashboard.createDialog.lengthTypes.mid', hintLabelKey: 'dashboard.createDialog.lengthMid', minChapters: 31, maxChapters: 300 },
  { value: 'long', optionKey: 'dashboard.createDialog.lengthTypes.long', hintLabelKey: 'dashboard.createDialog.lengthLong', minChapters: 301, maxChapters: 799 },
  { value: 'epic', optionKey: 'dashboard.createDialog.lengthTypes.epic', hintLabelKey: 'dashboard.createDialog.lengthEpic', minChapters: 800, maxChapters: 1000 },
]

export default function DashboardPage() {
  const { t } = useTranslation()
  const { formatNumber } = useFormats()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const dispatch = useDispatch<AppDispatch>()
  const { projects } = useSelector((state: RootState) => state.project)
  const [openDialog, setOpenDialog] = useState(false)
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    genre: '',
  })

  // 🆕 题材与篇幅规划状态（原本在“开始创作”对话框配置，现合并到创建项目时一次填写）
  const [plannedLengthType, setPlannedLengthType] = useState('')
  const [plannedChaptersMin, setPlannedChaptersMin] = useState<number | ''>('')
  const [plannedChaptersMax, setPlannedChaptersMax] = useState<number | ''>('')
  const [userOutlinePlan, setUserOutlinePlan] = useState('')

  // 删除确认对话框状态
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [projectToDelete, setProjectToDelete] = useState<number | null>(null)

  // 章节列表侧边栏状态
  const [showChaptersDrawer, setShowChaptersDrawer] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [chapters, setChapters] = useState<any[]>([])
  const [chaptersLoading, setChaptersLoading] = useState(false)
  // 🔧 修复：从 localStorage 读取排序偏好
  const [chapterSortOrder, setChapterSortOrder] = useState<'asc' | 'desc'>(() => {
    const saved = localStorage.getItem('chapterSortOrder')
    return (saved === 'asc' || saved === 'desc') ? saved : 'asc'
  })

  // 章节删除状态
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [chapterToDelete, setChapterToDelete] = useState<any>(null)
  const [deletingChapter, setDeletingChapter] = useState(false)



  // 🆕 类型编辑状态
  const [editingGenreProjectId, setEditingGenreProjectId] = useState<number | null>(null)
  const [editedGenre, setEditedGenre] = useState('')
  
  // 🆕 书名编辑状态
  const [editingTitleProjectId, setEditingTitleProjectId] = useState<number | null>(null)
  const [editedTitle, setEditedTitle] = useState('')

  // 🆕 生成下一章状态
  const [generatingNextChapter, setGeneratingNextChapter] = useState<Record<number, boolean>>({})
  
  // 🆕 后台任务状态（章节ID -> 是否正在处理）
  const [postSaveProcessing, setPostSaveProcessing] = useState<Set<number>>(new Set())

  // 🆕 Snackbar 状态（用于显示成功/错误提示）
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'info' | 'warning'>('success')

  // 🆕 章节字数统计（每个项目的总字数）
  const [chapterWordCounts, setChapterWordCounts] = useState<Record<number, number>>({})

  // 🆕 项目概念状态（用于判断是否为空白项目）
  const [projectConceptStatus, setProjectConceptStatus] = useState<Record<number, boolean>>({})

  // 🆕 导出到其他模块的状态
  const [exportingChapter, setExportingChapter] = useState<number | null>(null)

  // 🆕 一键导出所有章节状态
  const [exportAllAnchorEl, setExportAllAnchorEl] = useState<null | HTMLElement>(null)
  const [exportingAll, setExportingAll] = useState(false)

  // 🆕 类型映射函数（英文/中文 → 显示标签）；展示值走 i18n，数据值保持后端契约不变
  const getGenreLabel = (genre: string | null | undefined): string => {
    const genreKeyMap: Record<string, string> = {
      // 英文键
      'Fantasy': 'fantasy',
      'Science Fiction': 'sciFi',
      'Romance': 'romance',
      'Mystery': 'mystery',
      'Thriller': 'thriller',
      'Other': 'other',
      // 中文键（网文题材）
      '修仙': 'xiuxian',
      '玄幻': 'xuanhuan',
      '奇幻': 'fantasy',
      '都市': 'urban',
      '悬疑': 'suspense',
      '言情': 'romance',
      '耽美': 'danmei',
      // 历史笔误键：GENRE_COLORS/编辑选项沿用 '耐美'（bookVizData 同源），数据值不动，展示统一映射为耽美
      '耐美': 'danmei',
      '科幻': 'sciFi',
      '纯文学': 'literary',
    }
    const key = genreKeyMap[genre || '']
    return key ? t(`dashboard.genre.${key}`) : genre || t('dashboard.genre.unset')
  }

  // 🆕 自定义大纲占位提示：仅在已选题材与篇幅时追加节奏建议
  const buildCustomOutlinePlaceholder = (): string => {
    if (!formData.genre || !plannedLengthType) {
      return t('dashboard.createDialog.customOutlinePlaceholder')
    }
    const paceKey = PACE_HINT_KEYS[`${formData.genre}|${plannedLengthType}`]
      ?? PACE_HINT_KEYS[formData.genre]
      ?? 'dashboard.createDialog.paceDefault'
    return `${t('dashboard.createDialog.pacePrefix')}：${t(paceKey)}\n\n${t('dashboard.createDialog.noCustomPlanSuffix')}`
  }

  // 切换篇幅时同步推荐章节范围
  const handlePlannedLengthChange = (value: string) => {
    setPlannedLengthType(value)
    const option = PLANNED_LENGTH_OPTIONS.find((item) => item.value === value)
    if (option) {
      setPlannedChaptersMin(option.minChapters)
      setPlannedChaptersMax(option.maxChapters)
    }
  }

  useEffect(() => {
    dispatch(fetchProjects())
  }, [dispatch])


  // 🆕 加载项目概念状态（检查是否为空白项目）
  useEffect(() => {
    if (projects.length === 0) return

    const loadProjectConceptStatus = async () => {
      const conceptStatus: Record<number, boolean> = {}

      try {
        // 并发请求所有项目的概念内容
        const promises = projects.map(async (project) => {
          try {
            const response = await apiClient.getWorkflowAllStagesContent(project.id)

            if (response.status >= 200 && response.status < 300) {
              const data = response.data || {}
              const hasConcept = !!(data.stages?.concept && data.stages.concept.trim())
              conceptStatus[project.id] = hasConcept
              logger.log(`✅ 项目 ${project.id} 概念状态: ${hasConcept ? '非空' : '空白'}`)
            } else {
              conceptStatus[project.id] = false
            }
          } catch (error) {
            logger.error(`❌ 获取项目 ${project.id} 概念状态失败:`, error)
            conceptStatus[project.id] = false
          }
        })

        await Promise.all(promises)
        setProjectConceptStatus(conceptStatus)
        logger.log('✅ 项目概念状态加载完成:', conceptStatus)
      } catch (error) {
        logger.error('❌ 加载项目概念状态失败:', error)
      }
    }

    loadProjectConceptStatus()
  }, [projects])

  // 🆕 加载章节字数统计
  useEffect(() => {
    if (projects.length === 0) return

    const loadChapterWordCounts = async () => {
      const wordCounts: Record<number, number> = {}

      try {
        // 并发请求所有项目的章节数据
        const promises = projects.map(async (project) => {
          try {
            const response = await apiClient.getChapters(project.id)
            const chapters = response.data
            const totalWords = Array.isArray(chapters)
              ? chapters.reduce((sum: number, ch: any) => sum + (ch.word_count || 0), 0)
              : 0
            wordCounts[project.id] = totalWords
            logger.log(`✅ 项目 ${project.id} 章节总字数: ${totalWords}`)
          } catch (error) {
            logger.error(`❌ 获取项目 ${project.id} 章节失败:`, error)
            wordCounts[project.id] = 0
          }
        })

        await Promise.all(promises)
        setChapterWordCounts(wordCounts)
        logger.log('✅ 章节字数统计加载完成:', wordCounts)
      } catch (error) {
        logger.error('❌ 加载章节字数统计失败:', error)
      }
    }

    loadChapterWordCounts()
  }, [projects])

  // 🆕 自动展开章节列表（如果 URL 中有 projectId 参数）
  useEffect(() => {
    const projectIdParam = searchParams.get('projectId')
    if (projectIdParam) {
      const projectId = parseInt(projectIdParam, 10)
      if (!isNaN(projectId)) {
        logger.log('📍 检测到 URL 参数 projectId:', projectId)
        // 延迟一点打开，确保项目列表已加载
        setTimeout(() => {
          handleOpenChaptersDrawer(projectId)
          // 清除 URL 参数，保持 URL 整洁
          setSearchParams({})
        }, 500)
      }
    }
  }, [searchParams, setSearchParams])

  // 🆕 监听 WebSocket 事件（后台任务状态）
  useEffect(() => {
    if (!selectedProjectId) return

    let unsubscribePostSaveTaskStart: () => void = () => undefined
    let unsubscribePostSaveTaskComplete: () => void = () => undefined
    let unsubscribeTaskComplete: () => void = () => undefined
    let disposed = false

    // 导入 WebSocket 实例
    import('@/services/websocket').then(({ workflowWebSocket }) => {
      if (disposed) {
        return
      }
      // 连接 WebSocket
      workflowWebSocket.connect().then(() => {
        if (disposed) {
          return
        }
        workflowWebSocket.joinProject(selectedProjectId)
      }).catch(() => {
        // WebSocket 连接失败
      })

      // 监听后台任务开始
      unsubscribePostSaveTaskStart = workflowWebSocket.onPostSaveTaskStart((data: any) => {
        logger.log('📡 收到后台任务开始:', data)
        if (data.chapter_id) {
          setPostSaveProcessing(prev => new Set(prev).add(data.chapter_id))
        }
      })

      // 监听后台任务完成
      unsubscribePostSaveTaskComplete = workflowWebSocket.onPostSaveTaskComplete((data: any) => {
        logger.log('✅ 收到后台任务完成:', data)
        if (data.chapter_id) {
          setPostSaveProcessing(prev => {
            const newSet = new Set(prev)
            newSet.delete(data.chapter_id)
            return newSet
          })
        }
      })

      // 🆕 监听协同拓展任务完成事件
      unsubscribeTaskComplete = workflowWebSocket.onTaskComplete((data) => {
        logger.log('✅ 收到任务完成:', data)
        const result = getStoryExpansionResultFromTaskComplete(data) ?? {}
        
        if (isStoryExpansionTaskId(data.task_id)) {
          logger.log('🔄 协同拓展任务完成，刷新章节列表...')
          if (selectedProjectId) {
            loadChapters(selectedProjectId)
          }

          const baseMessage = typeof result.message === 'string' && result.message.trim()
            ? result.message.trim()
            : t('dashboard.collabExpansionDone')

          setSnackbarMessage(buildStoryExpansionCompletionMessage(baseMessage, result, t))
          setSnackbarSeverity('success')
          setSnackbarOpen(true)
        }
      })
    })

    // 清理：组件卸载时移除监听器（不断开连接）
    return () => {
      disposed = true
        // 只移除监听器，保持 WebSocket 连接（其他页面可能还在用）
      unsubscribePostSaveTaskStart()
      unsubscribePostSaveTaskComplete()
      unsubscribeTaskComplete()
    }
  }, [selectedProjectId])

  const handleCreateProject = async () => {
    try {
      const newProject = await dispatch(
        createProject({
          title: formData.title.trim(),
          description: formData.description,
          genre: formData.genre || undefined,
          planned_length_type: plannedLengthType || undefined,
          planned_chapters_min: plannedChaptersMin === '' ? undefined : plannedChaptersMin,
          planned_chapters_max: plannedChaptersMax === '' ? undefined : plannedChaptersMax,
          user_outline_plan: userOutlinePlan.trim() || undefined,
        })
      ).unwrap()

      setFormData({ title: '', description: '', genre: '' })
      setPlannedLengthType('')
      setPlannedChaptersMin('')
      setPlannedChaptersMax('')
      setUserOutlinePlan('')
      setOpenDialog(false)
      // 重新获取项目列表
      dispatch(fetchProjects())

      // 进入工作流页并自动打开开始创作对话框，补充创作模型与创作需求
      navigate(`/workflow/${newProject.id}?autoStart=true`)
    } catch (error) {
      logger.error('Failed to create project:', error)
      alert('Failed to create project. Please try again.')
    }
  }



  const handleDeleteProject = (projectId: number) => {
    setProjectToDelete(projectId)
    setDeleteConfirmOpen(true)
  }

  const handleConfirmDelete = async () => {
    if (projectToDelete) {
      try {
        await dispatch(deleteProject(projectToDelete) as any)
        setDeleteConfirmOpen(false)
        setProjectToDelete(null)
        // 重新加载项目列表
        dispatch(fetchProjects() as any)
      } catch (error) {
        logger.error('Delete failed:', error)
      }
    }
  }

  const handleCancelDelete = () => {
    setDeleteConfirmOpen(false)
    setProjectToDelete(null)
  }

  const handleLogout = () => {
    dispatch(performLogout())
    navigate('/login')
  }

  // 🔧 修复：接收 sortOrder 参数，避免闭包问题
  const loadChapters = async (projectId: number, sortOrder?: 'asc' | 'desc') => {
    // 优先使用传入的参数，否则从 localStorage 读取最新值
    const currentSortOrder = sortOrder ?? (localStorage.getItem('chapterSortOrder') as 'asc' | 'desc') ?? 'asc'
    setChaptersLoading(true)
    try {
      const response = await apiClient.getChapters(projectId, currentSortOrder)
      if (response.data) {
        // 后端直接返回章节数组，按章节编号排序
        const chaptersList = Array.isArray(response.data) ? response.data : []
        const sortedChapters = chaptersList.sort((a: any, b: any) =>
          currentSortOrder === 'asc'
            ? a.chapter_number - b.chapter_number
            : b.chapter_number - a.chapter_number
        )
        setChapters(sortedChapters)
      }
    } catch (error) {
      logger.error('Failed to load chapters:', error)
      setChapters([])
    } finally {
      setChaptersLoading(false)
    }
  }

  const handleOpenChaptersDrawer = (projectId: number) => {
    // 失去焦点以避免 aria-hidden 警告
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur()
    }
    setSelectedProjectId(projectId)
    setShowChaptersDrawer(true)
    loadChapters(projectId)
  }

  const handleCloseChaptersDrawer = () => {
    setShowChaptersDrawer(false)
    setSelectedProjectId(null)
    setChapters([])
  }

  const handleChapterSortOrderChange = async (newOrder: 'asc' | 'desc') => {
    setChapterSortOrder(newOrder)
    // 🔧 修复：保存到 localStorage
    localStorage.setItem('chapterSortOrder', newOrder)
    // 重新加载章节列表，传入新的排序参数避免闭包问题
    if (selectedProjectId) {
      await loadChapters(selectedProjectId, newOrder)
    }
  }

  const handleChapterClick = (chapterId: number) => {
    if (selectedProjectId) {
      handleCloseChaptersDrawer()
      navigate(`/editor/${selectedProjectId}/${chapterId}`)
    }
  }

  const handleDeleteChapterClick = (chapter: any, event: React.MouseEvent) => {
    event.stopPropagation()
    setChapterToDelete(chapter)
    setDeleteChapterDialogOpen(true)
  }

  const handleCloseDeleteChapterDialog = () => {
    setDeleteChapterDialogOpen(false)
    setChapterToDelete(null)
  }

  const handleConfirmDeleteChapter = async () => {
    if (!chapterToDelete || !selectedProjectId) return
    
    try {
      setDeletingChapter(true)
      logger.log('🗑️ 开始删除章节:', chapterToDelete.id)
      
      await apiClient.deleteChapter(chapterToDelete.id)
      
      logger.log('✅ 章节删除成功')
      
      // 显示成功提示
      setSnackbarMessage(t('dashboard.chapterDeleted'))
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      
      // 刷新章节列表
      await loadChapters(selectedProjectId)
      
      // 关闭对话框
      handleCloseDeleteChapterDialog()
    } catch (err) {
      logger.error('❌ 删除章节失败:', err)
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage(t('dashboard.chapterDeleteFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setDeletingChapter(false)
    }
  }


  // 🆕 编辑类型功能
  const handleStartEditGenre = (projectId: number, currentGenre: string) => {
    setEditingGenreProjectId(projectId)
    setEditedGenre(currentGenre || '')
  }
  
  // 开始编辑书名
  const handleStartEditTitle = (projectId: number, currentTitle: string) => {
    setEditingTitleProjectId(projectId)
    setEditedTitle(currentTitle || '')
  }
  
  // 保存书名
  const handleSaveTitle = async () => {
    const projectId = editingTitleProjectId
    if (!projectId || !editedTitle.trim()) {
      setEditingTitleProjectId(null)
      setEditedTitle('')
      return
    }
    
    try {
      await dispatch(updateProject({ projectId: projectId, data: { title: editedTitle.trim() } })).unwrap()
      setEditingTitleProjectId(null)
      setEditedTitle('')
    } catch {
      setEditingTitleProjectId(null)
      setEditedTitle('')
    }
  }


  // 选择风格并立即保存
  const handleGenreMenuSelect = async (genre: string) => {
    const projectId = editingGenreProjectId
    if (!projectId) return
    setEditingGenreProjectId(null)
    setEditedGenre('')
    try {
      await dispatch(updateProject({ projectId, data: { genre } }))
      dispatch(fetchProjects())
      setSnackbarMessage(t('dashboard.genreUpdated', { genre: getGenreLabel(genre) }))
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch {
      setSnackbarMessage(t('dashboard.genreUpdateFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }


  // 🆕 生成下一章功能（与 WorkflowControlPage 完全相同）
  const handleGenerateNextChapter = async (projectId: number) => {
    setGeneratingNextChapter(prev => ({ ...prev, [projectId]: true }))

    try {
      logger.log('📍 开始生成下一章（异步模式）...')

      const response = await apiClient.generateNextWorkflowChapter(projectId, {
        workflowGenerationModel: readStoredWorkflowGenerationModel() || undefined,
      })

      if (response.status >= 200 && response.status < 300) {
        const data = response.data
        logger.log('✅ 异步任务已创建:', data)

        // 后端返回: { task_id, status, message, next_chapter_number }
        const { task_id, next_chapter_number } = data

        // 🆕 先设置 Redux 状态（确保在跳转前状态已就绪）
        dispatch(startGenerateNextChapter({ taskId: task_id, chapterNumber: next_chapter_number }))

        // 显示提示
        setSnackbarMessage(t('dashboard.generateNextChapter', { number: next_chapter_number }))
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 🔧 关键修复：等待提示消息显示后再跳转，同时不重置状态
        setTimeout(() => {
          // 跳转到工作流页面（不再需要传递 URL 参数，因为状态已在 Redux 中）
          navigate(`/workflow/${projectId}`)
        }, 500)  // 等待500ms让用户看到提示
      } else {
        const errorData = response.data
        logger.error('❌ 创建生成任务失败:', errorData)

        // 熔断暂停要用户看过原因再确认，列表页不重复实现确认弹窗，只引导去创作流程页
        if (extractCircuitBreakerPause(response)) {
          setSnackbarMessage(t('dashboard.breakerPaused'))
          setSnackbarSeverity('warning')
          setSnackbarOpen(true)
          setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
          return
        }

        // 🆕 detail 可能是字符串（404/409/503）或对象（429 免费额度）
        const detail = errorData?.detail
        const detailMessage = typeof detail === 'string' ? detail : detail?.message
        setSnackbarMessage(detailMessage || errorData?.error || t('dashboard.createTaskFailed'))
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        // 🔧 只在失败时重置状态
        setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
      }
    } catch (error) {
      logger.error('❌ 生成下一章异常:', error)

      setSnackbarMessage(t('dashboard.createTaskFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      // 🔧 只在异常时重置状态
      setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
    }
    // 🔧 关键：移除 finally 块，不自动重置状态
    // 让 WorkflowControlPage 在任务完成时重置
  }

  // 🆕 导出到织文无迹模块
  const handleExportToZhiwen = async (chapter: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setExportingChapter(chapter.id)
    
    try {
      const response = await apiClient.getChapter(chapter.id)
      const data = response.data
      const project = projects.find((item) => item.id === selectedProjectId)
      localStorage.setItem('zhiwen_import_content', JSON.stringify({
        fromProjectId: selectedProjectId,
        chapterId: chapter.id,
        title: data.title,
        content: data.content,
        genre: project?.genre || null,
      }))
      
      setSnackbarMessage(t('dashboard.exportPrepared'))
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
      // 跳转到织文无迹模块
      setTimeout(() => navigate('/ai-trace'), 500)
    } catch (error) {
      logger.error('❌ 导出到织文无迹失败:', error)
      setSnackbarMessage(t('dashboard.exportFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingChapter(null)
    }
  }

  // 一键导出所有章节为 TXT
  const handleExportAllTxt = async () => {
    if (!selectedProjectId) return
    setExportAllAnchorEl(null)
    setExportingAll(true)
    
    try {
      const response = await apiClient.get(`/api/v1/projects/${selectedProjectId}/export/all/txt`, {
        responseType: 'blob',
      })
      const blob = response.data as Blob
      const filename = extractFilenameFromContentDisposition(
        response.headers?.['content-disposition'],
        t('dashboard.novelTxtFilename'),
      )
      triggerBlobDownload(blob, filename)
      setSnackbarMessage(t('dashboard.exportTxtSuccess'))
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      logger.error('❗ 导出 TXT 失败:', error)
      setSnackbarMessage(t('dashboard.exportFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingAll(false)
    }
  }

  // 一键导出所有章节为 DOCX
  const handleExportAllDocx = async () => {
    if (!selectedProjectId) return
    setExportAllAnchorEl(null)
    setExportingAll(true)
    
    try {
      const response = await apiClient.get(`/api/v1/projects/${selectedProjectId}/export/all/docx`, {
        responseType: 'blob',
      })
      const blob = response.data as Blob
      const filename = extractFilenameFromContentDisposition(
        response.headers?.['content-disposition'],
        'novelDocxFilename',
      )
      triggerBlobDownload(blob, filename)
      setSnackbarMessage(t('dashboard.exportDocxSuccess'))
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      logger.error('❗ 导出 DOCX 失败:', error)
      setSnackbarMessage(t('dashboard.exportFailed'))
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingAll(false)
    }
  }

  return (
    <Box sx={{ 
      minHeight: '100vh', 
      // 页面画布走 background.default：浅色暖白、深色墨底，随主题反相（原为写死的 slate 灰渐变）。
      bgcolor: 'background.default',
      position: 'relative',
    }}>
      {/* 顶部标题栏 */}
      <Box
        sx={(theme) => ({
          // hero 渐变走 primary token：浅色深黄铜、深色亮黄铜，两端由 token 反相。
          background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 100%)`,
          py: { xs: 2, sm: 2.5, md: 3 },
          px: { xs: 2, sm: 3 },
          boxShadow: theme.shadows[4],
        })}
      >
        <Container maxWidth="lg">
          <Box sx={{ 
            display: 'flex', 
            flexDirection: { xs: 'column', sm: 'row' },
            justifyContent: 'space-between', 
            alignItems: { xs: 'flex-start', sm: 'center' },
            gap: { xs: 1.5, sm: 0 }
          }}>
            {/* 左侧：返回按钮 + 标题 */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1.5, sm: 2 } }}>
              <IconButton
                onClick={() => navigate('/home')}
                sx={(theme) => {
                  // hero 上的前景一律用 primary.contrastText：浅色近白、深色近墨，叠色由它派生。
                  const onHero = theme.palette.primary.contrastText
                  return {
                    color: onHero,
                    backgroundColor: alpha(onHero, 0.1),
                    '&:hover': {
                      backgroundColor: alpha(onHero, 0.2),
                    },
                  }
                }}
                title={t('dashboard.backToStudio')}
              >
                <ArrowBackIcon />
              </IconButton>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1, sm: 1.5 } }}>
                <AutoStoriesIcon sx={{ fontSize: { xs: 24, sm: 28, md: 32 }, color: 'primary.contrastText' }} />
                <Box>
                  <Typography
                    variant="h5"
                    sx={{
                      color: 'primary.contrastText',
                      fontWeight: 700,
                      letterSpacing: '0.5px',
                      fontSize: { xs: '1.25rem', sm: '1.5rem', md: '1.5rem' }
                    }}
                  >
                    {t('dashboard.title')}
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{
                      color: 'primary.contrastText',
                      opacity: 0.8,
                      fontSize: { xs: '0.75rem', sm: '0.85rem' },
                      display: { xs: 'none', sm: 'block' }
                    }}
                  >
                    {t('dashboard.subtitle')}
                  </Typography>
                </Box>
              </Box>
            </Box>

            {/* 右侧：操作按钮 */}
            <Box sx={{ 
              display: 'flex', 
              gap: { xs: 1, sm: 1.5 },
              width: { xs: '100%', sm: 'auto' },
              justifyContent: { xs: 'flex-end', sm: 'flex-start' }
            }}>
              <Button
                variant="outlined"
                onClick={() => navigate('/model-catalog')}
                startIcon={<HubIcon />}
                sx={(theme) => {
                  const onHero = theme.palette.primary.contrastText
                  return {
                    color: onHero,
                    borderColor: alpha(onHero, 0.5),
                    fontSize: { xs: '0.8125rem', sm: '0.875rem' },
                    minHeight: { xs: 36, sm: 40 },
                    '&:hover': {
                      borderColor: onHero,
                      backgroundColor: alpha(onHero, 0.1),
                    },
                  }
                }}
              >
                {t('dashboard.modelCatalog')}
              </Button>
              <Button
                variant="outlined"
                onClick={handleLogout}
                sx={(theme) => {
                  const onHero = theme.palette.primary.contrastText
                  return {
                    color: onHero,
                    borderColor: alpha(onHero, 0.5),
                    fontSize: { xs: '0.8125rem', sm: '0.875rem' },
                    minHeight: { xs: 36, sm: 40 },
                    '&:hover': {
                      borderColor: onHero,
                      backgroundColor: alpha(onHero, 0.1),
                    },
                  }
                }}
              >
                {t('dashboard.logout')}
              </Button>
            </Box>
          </Box>
        </Container>
      </Box>

      {/* 项目列表区域 */}
      <Container maxWidth="lg" sx={{ py: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2 } }}>

      <Grid container spacing={{ xs: 1.5, sm: 2, md: 3 }}>
        {projects.map((project) => {
          const bookColors = getBookVizPalette(project.genre)
          const isDisabled = Boolean(generatingNextChapter[project.id])

          return (
          <Grid item xs={6} sm={4} md={3} lg={2.4} key={project.id}>
            {/* 现代化书本卡片 - 3D 效果 */}
            <Tooltip title={isDisabled ? t('dashboard.processing') : projectConceptStatus[project.id] === false ? t('dashboard.clickToStart') : t('dashboard.clickToEnter')} arrow placement="top">
            <Box
              sx={{
                position: 'relative',
                height: { xs: '220px', sm: '260px', md: '300px' },
                maxWidth: { xs: '160px', sm: '200px', md: '230px' },
                margin: '0 auto',
                perspective: '1500px',
                cursor: isDisabled ? 'default' : 'pointer',
              }}
              onClick={() => {
                if (!isDisabled) {
                  const hasConcept = projectConceptStatus[project.id]
                  if (hasConcept === false) {
                    logger.log(`📝 检测到空白项目 ${project.id}，跳转到工作流并自动打开创作对话框`)
                    navigate(`/workflow/${project.id}?autoStart=true`)
                  } else {
                    logger.log(`📖 检测到已有内容项目 ${project.id}，正常跳转`)
                    navigate(`/workflow/${project.id}`)
                  }
                }
              }}
            >
              {/* 整体容器 - 包含 3D 变换 */}
              <Box
                sx={{
                  position: 'relative',
                  width: '100%',
                  height: '100%',
                  transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                  transformStyle: 'preserve-3d',
                  ...(isDisabled ? {} : {
                    '&:hover': {
                      transform: 'translateY(-10px) rotateY(-5deg)',
                      '& .book-cover': {
                        boxShadow: '8px 20px 48px rgba(0,0,0,0.65), 1px 1px 0 rgba(255,255,255,0.08) inset', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                      },
                      '& .book-spine': {
                        boxShadow: '-4px 0 16px rgba(0,0,0,0.5)', // sg-color-fixed: 书脊投影（媒体封面美术层）
                      },
                      '& .book-pages': {
                        transform: 'translateX(-3px)',
                      },
                    },
                  }),
                }}
              >
                {/* 书脊 - 左侧 */}
                <Box
                  className="book-spine"
                  sx={{
                    position: 'absolute',
                    left: 0,
                    top: { xs: '3px', sm: '4px' },
                    bottom: { xs: '3px', sm: '4px' },
                    width: { xs: '14px', sm: '18px', md: '20px' },
                    background: `linear-gradient(to right, ${bookColors.primary}ff 0%, ${bookColors.secondary}aa 100%)`,
                    borderRadius: '3px 0 0 3px',
                    boxShadow: '-3px 0 12px rgba(0,0,0,0.45)', // sg-color-fixed: 书脊投影（媒体封面美术层）
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    overflow: 'hidden',
                    transition: 'all 0.4s ease',
                    zIndex: 2,
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: '15%',
                      bottom: '15%',
                      left: '50%',
                      width: '2px',
                      background: `linear-gradient(to bottom, transparent, ${bookColors.accent}60, ${bookColors.accent}, ${bookColors.accent}60, transparent)`,
                      transform: 'translateX(-50%)',
                      opacity: 0.6,
                    },
                  }}
                >
                  <Typography
                    sx={{
                      writingMode: 'vertical-rl',
                      textOrientation: 'mixed',
                      color: bookColors.accent,
                      fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' },
                      fontWeight: 700,
                      letterSpacing: { xs: '1px', sm: '2px' },
                      textShadow: '0 1px 3px rgba(0,0,0,0.6)', // sg-color-fixed: 封面文字投影（媒体封面美术层）
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxHeight: '85%',
                      opacity: 0.9,
                    }}
                  >
                    {project.title || t('dashboard.unnamedProject')}
                  </Typography>
                </Box>

                {/* 封面主体 */}
                <Box
                  className="book-cover"
                  sx={{
                    position: 'absolute',
                    left: { xs: '12px', sm: '14px', md: '16px' },
                    right: { xs: '8px', sm: '9px', md: '10px' },
                    top: 0,
                    bottom: 0,
                    background: bookColors.gradient,
                    borderRadius: '2px 6px 6px 2px',
                    boxShadow: '3px 6px 28px rgba(0,0,0,0.55), 1px 1px 0 rgba(255,255,255,0.06) inset', // sg-color-fixed: 封面投影与顶光（媒体封面美术层）
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'visible',
                    transition: 'all 0.4s ease',
                    zIndex: 3,
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      background:
                        'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(255,255,255,0.012) 3px, rgba(255,255,255,0.012) 4px), radial-gradient(ellipse at 30% 15%, rgba(255,255,255,0.2) 0%, transparent 55%), linear-gradient(170deg, rgba(255,255,255,0.08) 0%, transparent 40%, rgba(0,0,0,0.25) 100%)', // sg-color-fixed: 封面纸纹/光泽叠加（媒体封面美术层）
                      pointerEvents: 'none',
                      zIndex: 1,
                    },
                    '&::after': {
                      content: '""',
                      position: 'absolute',
                      top: { xs: '8px', sm: '9px', md: '10px' },
                      left: { xs: '8px', sm: '9px', md: '10px' },
                      right: { xs: '8px', sm: '9px', md: '10px' },
                      bottom: { xs: '8px', sm: '9px', md: '10px' },
                      border: `1px solid ${bookColors.accent}38`,
                      borderRadius: '1px',
                      pointerEvents: 'none',
                      zIndex: 2,
                    },
                  }}
                >
                  {/* 上部横线装饰 */}
                  <Box sx={{
                    position: 'absolute',
                    top: { xs: '18px', sm: '21px', md: '24px' },
                    left: { xs: '16px', sm: '19px', md: '22px' },
                    right: { xs: '16px', sm: '19px', md: '22px' },
                    height: '1px',
                    background: `linear-gradient(to right, transparent, ${bookColors.accent}50, transparent)`,
                    zIndex: 3,
                  }} />

                  {/* 标题区域 */}
                  <Box sx={{
                    px: { xs: 1.5, sm: 2, md: 2.5 },
                    pt: { xs: 2.5, sm: 3.5, md: 4.5 },
                    pb: 1,
                    textAlign: 'center',
                    position: 'relative',
                    zIndex: 3,
                    flexGrow: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                  }}>
                    {editingTitleProjectId === project.id ? (
                      <Box
                        onClick={(e) => e.stopPropagation()}
                        sx={{ mb: { xs: 0.8, sm: 1.2, md: 1.5 } }}
                      >
                        <TextField
                          value={editedTitle}
                          onChange={(e) => setEditedTitle(e.target.value)}
                          autoFocus
                          size="small"
                          sx={{
                            '& .MuiInputBase-input': {
                              fontFamily: '"Noto Serif SC", "Source Han Serif SC", "STSong", "宋体", serif',
                              fontSize: { xs: '0.75rem', sm: '0.875rem', md: '1rem' },
                              fontWeight: 900,
                              color: bookColors.text,
                              textAlign: 'center',
                              letterSpacing: { xs: '2px', sm: '3px', md: '4px' },
                            },
                            '& .MuiOutlinedInput-root': {
                              backgroundColor: 'rgba(255,255,255,0.1)', // sg-color-fixed: 封面内输入底（媒体封面美术层）
                            },
                          }}
                          onKeyPress={(e) => {
                            if (e.key === 'Enter') {
                              handleSaveTitle()
                            }
                          }}
                        />
                        <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1, mt: 0.5 }}>
                          <Typography
                            onClick={handleSaveTitle}
                            sx={{
                              fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' },
                              color: bookColors.accent,
                              cursor: 'pointer',
                              letterSpacing: '1px',
                            }}
                          >
                            {t('common.save')}
                          </Typography>
                          <Typography
                            onClick={() => { setEditingTitleProjectId(null); setEditedTitle('') }}
                            sx={{
                              fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' },
                              color: 'rgba(255,255,255,0.3)', // sg-color-fixed: 封面弱化字（媒体封面美术层）
                              cursor: 'pointer',
                              letterSpacing: '1px',
                            }}
                          >
                            {t('common.cancel')}
                          </Typography>
                        </Box>
                      </Box>
                    ) : (
                      <Typography
                        onClick={(e) => { e.stopPropagation(); handleStartEditTitle(project.id, project.title) }}
                        sx={{
                          fontFamily: '"Noto Serif SC", "Source Han Serif SC", "STSong", "宋体", serif',
                          fontSize: { xs: '0.75rem', sm: '0.875rem', md: '1rem' },
                          fontWeight: 900,
                          color: bookColors.text,
                          lineHeight: 1.7,
                          letterSpacing: { xs: '2px', sm: '3px', md: '4px' },
                          textShadow: '0 2px 10px rgba(0,0,0,0.55)', // sg-color-fixed: 封面标题投影（媒体封面美术层）
                          mb: { xs: 0.8, sm: 1.2, md: 1.5 },
                          display: '-webkit-box',
                          WebkitLineClamp: 3,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          minHeight: '2.5em',
                          cursor: 'pointer',
                          transition: 'all 0.25s ease',
                          px: 1,
                          py: 0.5,
                          '&:hover': { 
                            transform: 'translateY(-2px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        {project.title || t('dashboard.unnamedProject')}
                      </Typography>
                    )}

                    {/* 题材标签 - 点击可编辑 */}
                    {editingGenreProjectId === project.id ? (
                      <Box
                        onClick={(e) => e.stopPropagation()}
                        sx={{ mx: 'auto', textAlign: 'center' }}
                      >
                        <Box sx={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: { xs: 0.4, sm: 0.6, md: 0.8 }, mb: 0.5 }}>
                          {['修仙', '玄幻', '奇幻', '都市', '言情', '耐美', '悬疑', '科幻', '纯文学'].map((g) => (
                            <Typography
                              key={g}
                              onClick={() => handleGenreMenuSelect(g)}
                              sx={{
                                fontFamily: '楷体, KaiTi, serif',
                                fontSize: { xs: '0.45rem', sm: '0.55rem', md: '0.6rem' },
                                color: editedGenre === g
                                  ? (GENRE_COLORS[g] || bookColors.accent)
                                  : `${GENRE_COLORS[g] || bookColors.accent}88`,
                                letterSpacing: '1px',
                                cursor: 'pointer',
                                fontWeight: editedGenre === g ? 700 : 400,
                                transition: 'all 0.25s ease',
                                px: 1,
                                py: 0.5,
                                '&:hover': { 
                                  color: GENRE_COLORS[g] || bookColors.accent, 
                                  transform: 'translateY(-2px)',
                                  boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                                  backgroundColor: `${GENRE_COLORS[g] || bookColors.accent}15`,
                                  borderRadius: '4px',
                                },
                              }}
                            >
                              {getGenreLabel(g)}
                            </Typography>
                          ))}
                        </Box>
                        <Typography
                          onClick={() => { setEditingGenreProjectId(null); setEditedGenre('') }}
                          sx={{ fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' }, color: 'rgba(255,255,255,0.3)', cursor: 'pointer', letterSpacing: '1px' }} // sg-color-fixed: 封面弱化字（媒体封面美术层）
                        >
                          {t('common.cancel')}
                        </Typography>
                      </Box>
                    ) : (
                      <Typography
                        onClick={(e) => { e.stopPropagation(); handleStartEditGenre(project.id, project.genre || '') }}
                        sx={{
                          fontFamily: '"STKaiti", "KaiTi", "楷体", serif',
                          fontSize: { xs: '0.5rem', sm: '0.58rem', md: '0.65rem' },
                          color: GENRE_COLORS[getGenreLabel(project.genre)] || bookColors.accent,
                          letterSpacing: { xs: '2px', sm: '2.5px', md: '3px' },
                          fontWeight: 600,
                          textShadow: `0 1px 6px rgba(0,0,0,0.5)`, // sg-color-fixed: 封面题材文字投影（媒体封面美术层）
                          cursor: 'pointer',
                          mx: 'auto',
                          display: 'block',
                          transition: 'all 0.25s ease',
                          px: 2,
                          py: 0.5,
                          '&:hover': { 
                            opacity: 0.75, 
                            letterSpacing: '4px',
                            transform: 'translateY(-2px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: `${GENRE_COLORS[getGenreLabel(project.genre)] || bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        {getGenreLabel(project.genre)}
                      </Typography>
                    )}

                    {/* 字数 */}
                    <Typography
                      sx={{
                        fontFamily: '"Courier New", monospace',
                        fontSize: { xs: '0.45rem', sm: '0.52rem', md: '0.58rem' },
                        color: bookColors.text,
                        opacity: 0.5,
                        letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' },
                        mt: { xs: 0.8, sm: 1, md: 1.2 },
                      }}
                    >
                      {t('dashboard.wordsCount', { count: formatNumber(chapterWordCounts[project.id] || 0) })}
                    </Typography>
                  </Box>

                  {/* 底部功能按钮区 - 两行两列布局 */}
                  <Box
                    sx={{
                      px: { xs: 1, sm: 1, md: 1.2 },
                      pt: { xs: 0.5, sm: 0.6, md: 0.8 },
                      pb: { xs: 0.8, sm: 1, md: 1.2 },
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr',
                      gridTemplateRows: 'auto auto',
                      gap: { xs: 0.8, sm: 0.9, md: 1 },
                      position: 'relative',
                      zIndex: 3,
                      overflow: 'visible',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* 第一行：典籍 | 目录 */}
                    <Tooltip title={t('dashboard.enterKnowledgeBase')} arrow>
                      <Box
                        onClick={() => !isDisabled && navigate(`/knowledge-base/${project.id}`)}
                        sx={{ 
                          cursor: isDisabled ? 'default' : 'pointer', 
                          opacity: isDisabled ? 0.45 : 1, 
                          transition: 'all 0.25s ease',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          py: { xs: 0.6, sm: 0.7 },
                          '&:hover': isDisabled ? {} : { 
                            transform: 'translateY(-4px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 600 }}>{t('dashboard.classics')}</Typography>
                      </Box>
                    </Tooltip>
                    <Tooltip title={t('dashboard.viewChapterList')} arrow>
                      <Box
                        onClick={() => !isDisabled && handleOpenChaptersDrawer(project.id)}
                        sx={{ 
                          cursor: isDisabled ? 'default' : 'pointer', 
                          opacity: isDisabled ? 0.45 : 1, 
                          transition: 'all 0.25s ease',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          py: { xs: 0.6, sm: 0.7 },
                          '&:hover': isDisabled ? {} : { 
                            transform: 'translateY(-4px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 600 }}>{t('dashboard.contents')}</Typography>
                      </Box>
                    </Tooltip>
                    {/* 第二行：焚毁 | 续写 */}
                    <Tooltip title={t('dashboard.deleteProjectTooltip')} arrow>
                      <Box
                        onClick={() => !isDisabled && handleDeleteProject(project.id)}
                        sx={{ 
                          cursor: isDisabled ? 'default' : 'pointer', 
                          opacity: isDisabled ? 0.45 : 1, 
                          transition: 'all 0.25s ease',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          py: { xs: 0.6, sm: 0.7 },
                          '&:hover': isDisabled ? {} : { 
                            transform: 'translateY(-4px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: 'rgba(239,83,80,0.15)', // sg-color-fixed: 焚毁警示底（媒体封面美术层）
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography
                          sx={{
                            fontFamily: '楷体，KaiTi, serif',
                            fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' },
                            color: '#f87171', // sg-color-fixed: 焚毁警示字（媒体封面美术层）
                            letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' },
                            fontWeight: 600,
                            textShadow: '0 1px 3px rgba(239,83,80,0.3)', // sg-color-fixed: 焚毁警示投影（媒体封面美术层）
                          }}
                        >
                          {t('dashboard.burn')}
                        </Typography>
                      </Box>
                    </Tooltip>
                    <Tooltip title={t('dashboard.continueWriteTooltip')} arrow>
                      <Box
                        onClick={() => !isDisabled && handleGenerateNextChapter(project.id)}
                        sx={{ 
                          cursor: isDisabled ? 'default' : 'pointer', 
                          opacity: isDisabled ? 0.45 : 1, 
                          transition: 'all 0.25s ease',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          py: { xs: 0.6, sm: 0.7 },
                          '&:hover': isDisabled ? {} : { 
                            transform: 'translateY(-4px)',
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)', // sg-color-fixed: 封面浮起投影（媒体封面美术层）
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 0.4 }}>
                          {generatingNextChapter[project.id]
                            ? <><CircularProgress size={10} sx={{ color: 'inherit' }} />{t('dashboard.continueWrite')}</>
                            : t('dashboard.continueWrite')
                          }
                        </Typography>
                      </Box>
                    </Tooltip>
                  </Box>
                  {[
                    { top: 13, left: 13, borderTop: 1, borderLeft: 1, borderRight: 0, borderBottom: 0 },
                    { top: 13, right: 13, borderTop: 1, borderLeft: 0, borderRight: 1, borderBottom: 0 },
                    { bottom: 13, left: 13, borderTop: 0, borderLeft: 1, borderRight: 0, borderBottom: 1 },
                    { bottom: 13, right: 13, borderTop: 0, borderLeft: 0, borderRight: 1, borderBottom: 1 },
                  ].map((pos, index) => (
                    <Box
                      key={index}
                      sx={{
                        position: 'absolute',
                        top: pos.top,
                        left: pos.left,
                        right: pos.right,
                        bottom: pos.bottom,
                        width: '12px',
                        height: '12px',
                        zIndex: 4,
                        borderTop: pos.borderTop ? `1px solid ${bookColors.accent}55` : 'none',
                        borderLeft: pos.borderLeft ? `1px solid ${bookColors.accent}55` : 'none',
                        borderRight: pos.borderRight ? `1px solid ${bookColors.accent}55` : 'none',
                        borderBottom: pos.borderBottom ? `1px solid ${bookColors.accent}55` : 'none',
                      }}
                    />
                  ))}
                </Box>

                {/* 书页效果 - 右侧 */}
                <Box
                  className="book-pages"
                  sx={{
                    position: 'absolute',
                    right: '0px',
                    top: '8px',
                    bottom: '8px',
                    width: '9px',
                    background: 'linear-gradient(to right, #ede0c8 0%, #ddd0b0 50%, #ccc090 100%)', // sg-color-fixed: 古籍书页纸色（媒体封面美术层）
                    borderRadius: '0 2px 2px 0',
                    transition: 'all 0.4s ease',
                    zIndex: 1,
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: 0,
                      bottom: 0,
                      left: 0,
                      width: '100%',
                      background: 'repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, rgba(0,0,0,0.04) 2px, rgba(0,0,0,0.04) 3px)', // sg-color-fixed: 古籍纸纹（媒体封面美术层）
                      opacity: 0.6,
                    },
                  }}
                />
              </Box>
            </Box>
            </Tooltip>
          </Grid>
        )
      })}
      
      {/* 新建项目空白卡片 - 放在项目列表末尾 */}
      <Grid item xs={6} sm={4} md={3} lg={2.4}>
        <Box
          onClick={() => setOpenDialog(true)}
          sx={{
            position: 'relative',
            height: { xs: '220px', sm: '260px', md: '300px' },
            maxWidth: { xs: '160px', sm: '200px', md: '230px' },
            margin: '0 auto',
            cursor: 'pointer',
            transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
            '&:hover': {
              transform: 'translateY(-10px)',
              '& .new-card-inner': {
                boxShadow: '8px 20px 48px rgba(0,0,0,0.65)', // sg-color-fixed: 古籍封面投影（媒体封面美术层）
              },
              '& .plus-icon': {
                transform: 'scale(1.1) rotate(90deg)',
                borderColor: 'rgba(180,160,120,0.6)', // sg-color-fixed: 古籍金边（媒体封面美术层）
                background: 'rgba(180,160,120,0.12)', // sg-color-fixed: 古籍金底（媒体封面美术层）
              },
              '& .add-text': {
                color: '#e8d5b0', // sg-color-fixed: 古籍金字（媒体封面美术层）
                letterSpacing: '5px',
              },
            },
          }}
        >
          {/* 书脊装饰 */}
          <Box sx={{
            position: 'absolute',
            left: 0,
            top: { xs: '2px', sm: '3px' },
            bottom: { xs: '2px', sm: '3px' },
            width: { xs: '14px', sm: '18px', md: '20px' },
            background: 'linear-gradient(to right, #1a1812 0%, #2a2618 100%)', // sg-color-fixed: 古籍书脊墨色（媒体封面美术层）
            borderRadius: '3px 0 0 3px',
            boxShadow: '-3px 0 12px rgba(0,0,0,0.45)', // sg-color-fixed: 书脊投影（媒体封面美术层）
            zIndex: 2,
            '&::after': {
              content: '""',
              position: 'absolute',
              top: 0,
              left: '50%',
              width: '1px',
              height: '100%',
              background: 'linear-gradient(to bottom, transparent 5%, rgba(200,180,120,0.25) 50%, transparent 95%)', // sg-color-fixed: 古籍鎏金带（媒体封面美术层）
              transform: 'translateX(-50%)',
            },
          }} />

          {/* 封面主体 */}
          <Box
            className="new-card-inner"
            sx={{
              position: 'absolute',
              left: { xs: '12px', sm: '16px', md: '18px' },
              right: { xs: '6px', sm: '7px', md: '8px' },
              top: 0,
              bottom: 0,
              background: 'linear-gradient(160deg, #18160e 0%, #221e12 40%, #2c2818 70%, #242010 100%)', // sg-color-fixed: 古籍封面墨色（媒体封面美术层）
              borderRadius: '2px 6px 6px 2px',
              boxShadow: '3px 6px 28px rgba(0,0,0,0.5)', // sg-color-fixed: 古籍封面投影（媒体封面美术层）
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: { xs: 1.5, sm: 1.8, md: 2 },
              overflow: 'hidden',
              transition: 'all 0.4s ease',
              zIndex: 3,
              border: '1px solid rgba(180,160,80,0.12)', // sg-color-fixed: 古籍描金边（媒体封面美术层）
              '&::after': {
                content: '""',
                position: 'absolute',
                top: { xs: '8px', sm: '10px', md: '12px' },
                left: { xs: '8px', sm: '10px', md: '12px' },
                right: { xs: '8px', sm: '10px', md: '12px' },
                bottom: { xs: '8px', sm: '10px', md: '12px' },
                border: '1px solid rgba(180,160,80,0.18)', // sg-color-fixed: 古籍描金边（媒体封面美术层）
                borderRadius: '1px',
                pointerEvents: 'none',
              },
            }}
          >
            {/* 加号图标 */}
            <Box
              className="plus-icon"
              sx={{
                width: { xs: 40, sm: 48, md: 56 },
                height: { xs: 40, sm: 48, md: 56 },
                borderRadius: '50%',
                border: '1px solid rgba(180,160,100,0.35)', // sg-color-fixed: 古籍描金边（媒体封面美术层）
                background: 'rgba(180,160,100,0.07)', // sg-color-fixed: 古籍金纹底（媒体封面美术层）
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                zIndex: 1,
              }}
            >
              <AddIcon
                sx={{
                  fontSize: { xs: 24, sm: 28, md: 32 },
                  color: 'rgba(200,180,110,0.75)', // sg-color-fixed: 古籍建卡金钮（媒体封面美术层）
                  transition: 'all 0.3s ease',
                }}
              />
            </Box>

            {/* 文字说明 */}
            <Box sx={{ textAlign: 'center', zIndex: 1 }}>
              <Typography
                className="add-text"
                sx={{
                  fontFamily: '"Noto Serif SC", "宋体", serif',
                  fontSize: { xs: '0.75rem', sm: '0.85rem', md: '0.95rem' },
                  color: 'rgba(200,180,120,0.7)', // sg-color-fixed: 古籍金字（媒体封面美术层）
                  fontWeight: 600,
                  letterSpacing: { xs: '2px', sm: '3px', md: '4px' },
                  mb: { xs: 0.5, sm: 0.8, md: 1 },
                  transition: 'all 0.3s ease',
                }}
              >
                {t('dashboard.newProject')}
              </Typography>

              <Typography
                sx={{
                  fontFamily: '"STKaiti", "楷体", serif',
                  fontSize: '0.65rem',
                  color: 'rgba(160,140,100,0.55)', // sg-color-fixed: 古籍金弱化字（媒体封面美术层）
                  letterSpacing: '2px',
                }}
              >
                {t('dashboard.startCreating')}
              </Typography>
            </Box>

            {/* L 形角标 */}
            {[
              { top: 16, left: 16, bt: 1, bl: 1, br: 0, bb: 0 },
              { top: 16, right: 16, bt: 1, bl: 0, br: 1, bb: 0 },
              { bottom: 16, left: 16, bt: 0, bl: 1, br: 0, bb: 1 },
              { bottom: 16, right: 16, bt: 0, bl: 0, br: 1, bb: 1 },
            ].map((pos, i) => (
              <Box key={i} sx={{
                position: 'absolute',
                top: pos.top,
                left: pos.left,
                right: pos.right,
                bottom: pos.bottom,
                width: '10px',
                height: '10px',
                zIndex: 4,
                borderTop: pos.bt ? '1px solid rgba(180,160,80,0.3)' : 'none', // sg-color-fixed: 古籍描金边（媒体封面美术层）
                borderLeft: pos.bl ? '1px solid rgba(180,160,80,0.3)' : 'none', // sg-color-fixed: 古籍描金边（媒体封面美术层）
                borderRight: pos.br ? '1px solid rgba(180,160,80,0.3)' : 'none', // sg-color-fixed: 古籍描金边（媒体封面美术层）
                borderBottom: pos.bb ? '1px solid rgba(180,160,80,0.3)' : 'none', // sg-color-fixed: 古籍描金边（媒体封面美术层）
              }} />
            ))}
          </Box>

          {/* 书页效果 */}
          <Box sx={{
            position: 'absolute',
            right: '0px',
            top: '8px',
            bottom: '8px',
            width: '9px',
            background: 'linear-gradient(to right, #e8dcc8 0%, #d4c8a8 60%, #c4b890 100%)', // sg-color-fixed: 古籍册页纸色（媒体封面美术层）
            borderRadius: '0 2px 2px 0',
            zIndex: 1,
            '&::before': {
              content: '""',
              position: 'absolute',
              top: 0, bottom: 0, left: 0, width: '100%',
              background: 'repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, rgba(0,0,0,0.06) 2px, rgba(0,0,0,0.06) 3px)', // sg-color-fixed: 古籍册页纸纹（媒体封面美术层）
            },
          }} />
        </Box>
      </Grid>
      </Grid>

      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3, maxHeight: '85vh', overflowY: 'auto' }}>
          <Typography variant="h6" gutterBottom>
            {t('dashboard.createProjectTitle')}
          </Typography>
          <TextField
            fullWidth
            label={t('dashboard.projectTitleLabel')}
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            margin="normal"
            helperText={formData.title.trim() ? ' ' : t('dashboard.createDialog.titleFallbackHint')}
          />
          <TextField
            fullWidth
            label={t('dashboard.requirementLabel')}
            placeholder={t('dashboard.requirementPlaceholder')}
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            margin="normal"
            multiline
            rows={3}
            helperText={t('dashboard.requirementHelper')}
          />
          <FormControl fullWidth margin="normal">
            <InputLabel>{t('dashboard.genreLabel')}</InputLabel>
            <Select
              value={formData.genre}
              onChange={(e) => setFormData({ ...formData, genre: e.target.value })}
              label={t('dashboard.genreLabel')}
            >
              <MenuItem value="修仙">{t('dashboard.genre.xiuxian')}</MenuItem>
              <MenuItem value="玄幻">{t('dashboard.genre.xuanhuan')}</MenuItem>
              <MenuItem value="奇幻">{t('dashboard.genre.fantasy')}</MenuItem>
              <MenuItem value="都市">{t('dashboard.genre.urban')}</MenuItem>
              <MenuItem value="言情">{t('dashboard.genre.romanceCn')}</MenuItem>
              <MenuItem value="耽美">{t('dashboard.genre.danmei')}</MenuItem>
              <MenuItem value="悬疑">{t('dashboard.genre.suspense')}</MenuItem>
              <MenuItem value="科幻">{t('dashboard.genre.sciFi')}</MenuItem>
              <MenuItem value="纯文学">{t('dashboard.genre.literary')}</MenuItem>
              <MenuItem value="Fantasy">{t('dashboard.genre.fantasyEn')}</MenuItem>
              <MenuItem value="Other">{t('dashboard.genre.other')}</MenuItem>
            </Select>
            <FormHelperText>{t('dashboard.createDialog.genreHelper')}</FormHelperText>
          </FormControl>

          {/* 篇幅规划（与题材同样在创建阶段一次配置） */}
          <FormControl fullWidth margin="normal">
            <InputLabel>{t('dashboard.createDialog.lengthPlan')}</InputLabel>
            <Select
              value={plannedLengthType}
              onChange={(e) => handlePlannedLengthChange(e.target.value)}
              label={t('dashboard.createDialog.lengthPlan')}
            >
              <MenuItem value="">{t('dashboard.createDialog.pleaseSelect')}</MenuItem>
              {PLANNED_LENGTH_OPTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {t(option.optionKey)}
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>{t('dashboard.createDialog.lengthHelper')}</FormHelperText>
          </FormControl>

          {/* 题材与篇幅联动提示 */}
          {formData.genre && plannedLengthType && (
            <Alert severity="info" sx={{ mt: 2, backgroundColor: 'info.light' }}>
              <Typography variant="body2">
                {t('dashboard.createDialog.genreLengthHint', {
                  genre: getGenreLabel(formData.genre),
                  length: t(
                    PLANNED_LENGTH_OPTIONS.find((option) => option.value === plannedLengthType)?.hintLabelKey
                      ?? plannedLengthType
                  ),
                })}
              </Typography>
            </Alert>
          )}

          <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
            <TextField
              fullWidth
              type="number"
              label={t('dashboard.createDialog.minChapters')}
              value={plannedChaptersMin}
              onChange={(e) => setPlannedChaptersMin(e.target.value === '' ? '' : Number(e.target.value))}
              inputProps={{ min: 1 }}
            />
            <TextField
              fullWidth
              type="number"
              label={t('dashboard.createDialog.maxChapters')}
              value={plannedChaptersMax}
              onChange={(e) => setPlannedChaptersMax(e.target.value === '' ? '' : Number(e.target.value))}
              inputProps={{ min: 1 }}
            />
          </Box>

          <TextField
            fullWidth
            multiline
            rows={4}
            margin="normal"
            label={t('dashboard.createDialog.customOutline')}
            placeholder={buildCustomOutlinePlaceholder()}
            value={userOutlinePlan}
            onChange={(e) => setUserOutlinePlan(e.target.value)}
          />

          <Box sx={{ mt: 3, display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              fullWidth
              onClick={handleCreateProject}
            >
              {t('dashboard.create')}
            </Button>
            <Button
              variant="outlined"
              fullWidth
              onClick={() => setOpenDialog(false)}
            >
              {t('common.cancel')}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteConfirmOpen} onClose={handleCancelDelete} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            {t('dashboard.deleteProjectTitle')}
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 3 }}>
            {t('dashboard.deleteProjectConfirm')}
          </Typography>
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button
              variant="outlined"
              onClick={handleCancelDelete}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={handleConfirmDelete}
            >
              {t('common.delete')}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 章节列表侧边栏 */}
      <Drawer
        anchor="right"
        open={showChaptersDrawer}
        onClose={handleCloseChaptersDrawer}
        disableEnforceFocus
        disableAutoFocus
        disableRestoreFocus
        hideBackdrop={false}
        ModalProps={{
          keepMounted: false,
          disablePortal: false,
        }}
        sx={{
          '& .MuiDrawer-paper': {
            width: 350,
            boxSizing: 'border-box',
          },
        }}
      >
        <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {/* 左侧：标题 + 排序按钮紧邻 */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6">{t('dashboard.chapterList')}</Typography>
            <Tooltip title={chapterSortOrder === 'asc' ? t('dashboard.sortAscTooltip') : t('dashboard.sortDescTooltip')} placement="top">
              <IconButton
                size="small"
                onClick={() => {
                  const newOrder = chapterSortOrder === 'asc' ? 'desc' : 'asc'
                  handleChapterSortOrderChange(newOrder)
                }}
                sx={{
                  p: 0.5,
                  color: 'primary.main',
                  '&:hover': {
                    backgroundColor: 'primary.50',
                  },
                }}
              >
                {/* 自定义排序图标：递增/递减线条 + 箭头 */}
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  {chapterSortOrder === 'asc' ? (
                    // 正序：短到长 + 向上箭头
                    <>
                      <rect x="3" y="18" width="18" height="2" rx="1" />
                      <rect x="3" y="13" width="14" height="2" rx="1" />
                      <rect x="3" y="8" width="10" height="2" rx="1" />
                      <rect x="3" y="3" width="6" height="2" rx="1" />
                      <path d="M20 3 L20 11 M17 6 L20 3 L23 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </>
                  ) : (
                    // 倒序：长到短 + 向下箭头
                    <>
                      <rect x="3" y="3" width="18" height="2" rx="1" />
                      <rect x="3" y="8" width="14" height="2" rx="1" />
                      <rect x="3" y="13" width="10" height="2" rx="1" />
                      <rect x="3" y="18" width="6" height="2" rx="1" />
                      <path d="M20 21 L20 13 M17 18 L20 21 L23 18" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </>
                  )}
                </svg>
              </IconButton>
            </Tooltip>
          </Box>
          
          {/* 右侧：导出 + 关闭 */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {/* 一键导出全文按钮 */}
            {chapters.length > 0 && (
              <Tooltip title={t('dashboard.exportAllTooltip')} placement="top">
                <span>
                  <IconButton
                    size="small"
                    onClick={(e) => setExportAllAnchorEl(e.currentTarget)}
                    disabled={exportingAll}
                    sx={{
                      border: '1px solid',
                      borderColor: 'primary.main',
                      borderRadius: 1,
                      color: 'primary.main',
                      '&:hover': {
                        backgroundColor: 'primary.50',
                      },
                    }}
                  >
                    {exportingAll ? (
                      <CircularProgress size={16} />
                    ) : (
                      <FileDownloadIcon fontSize="small" />
                    )}
                  </IconButton>
                </span>
              </Tooltip>
            )}
            
            <Button
              size="small"
              onClick={handleCloseChaptersDrawer}
              startIcon={<CloseIcon />}
            >
              {t('common.close')}
            </Button>
          </Box>
        </Box>
        <Divider />
        
        {/* 🗑️ 移除原有的导出按钮栏 */}
        <Menu
          anchorEl={exportAllAnchorEl}
          open={Boolean(exportAllAnchorEl)}
          onClose={() => setExportAllAnchorEl(null)}
        >
          <MenuItem onClick={handleExportAllTxt}>
            {t('dashboard.exportTxt')}
          </MenuItem>
          <MenuItem onClick={handleExportAllDocx}>
            {t('dashboard.exportDocx')}
          </MenuItem>
        </Menu>

        {chaptersLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
            <CircularProgress size={40} />
          </Box>
        ) : chapters.length === 0 ? (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="textSecondary">
              {t('dashboard.emptyChapters')}
            </Typography>
          </Box>
        ) : (
          <List sx={{ flex: 1, overflow: 'auto' }}>
            {chapters.map((chapter) => (
              <ListItem
                key={chapter.id}
                disablePadding
                secondaryAction={
                  <Box sx={{ display: 'flex', gap: 0.5 }}>
                    {/* ✨ 导出到织文无迹 */}
                    <IconButton
                      edge="end"
                      aria-label="export-zhiwen"
                      size="small"
                      color="success"
                      onClick={(e) => handleExportToZhiwen(chapter, e)}
                      title={t('dashboard.importZhiwen')}
                      disabled={exportingChapter === chapter.id}
                      sx={{
                        '&:hover': {
                          backgroundColor: 'success.light'
                        }
                      }}
                    >
                      <AutoFixHighIcon fontSize="small" />
                    </IconButton>
                    {/* 🗑 删除 */}
                    <IconButton
                      edge="end"
                      aria-label="delete"
                      size="small"
                      onClick={(e) => handleDeleteChapterClick(chapter, e)}
                      sx={{
                        color: 'error.main',
                        '&:hover': {
                          backgroundColor: 'error.light',
                          color: 'error.dark',
                        }
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Box>
                }
              >
                <ListItemText
                  onClick={() => handleChapterClick(chapter.id)}
                  sx={{
                    py: 1.5,
                    cursor: 'pointer',
                    '&:hover': {
                      backgroundColor: 'action.hover',
                    },
                  }}
                  primary={(
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <span>{chapter.title}</span>
                      {postSaveProcessing.has(chapter.id) && (
                        <Chip
                          label={t('common.processing')}
                          size="small"
                          color="primary"
                          sx={{ height: 20, fontSize: '0.7rem' }}
                        />
                      )}
                    </Box>
                  )}
                  secondary={`📝 ${t('dashboard.wordsCount', { count: chapter.word_count || 0 })}`}
                />
              </ListItem>
            ))}
          </List>
        )}
      </Drawer>

      {/* 章节删除确认对话框 */}
      <Dialog
        open={deleteChapterDialogOpen}
        onClose={handleCloseDeleteChapterDialog}
        aria-labelledby="delete-chapter-dialog-title"
        aria-describedby="delete-chapter-dialog-description"
      >
        <DialogTitle id="delete-chapter-dialog-title">
          {t('dashboard.deleteChapterTitle')}
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-chapter-dialog-description">
            {t('dashboard.deleteChapterHead')} <strong>"{chapterToDelete?.title}"</strong> {t('dashboard.deleteChapterTail')}
            <br />
            <br />
            {t('dashboard.deleteChapterWarning')}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteChapterDialog} disabled={deletingChapter}>
            {t('common.cancel')}
          </Button>
          <Button 
            onClick={handleConfirmDeleteChapter} 
            variant="contained"
            disabled={deletingChapter}
            startIcon={deletingChapter ? <CircularProgress size={16} /> : <DeleteIcon />}
            sx={{
              backgroundColor: 'error.main',
              color: 'error.contrastText',
              '&:hover': {
                backgroundColor: 'error.dark',
              },
              '&:disabled': {
                backgroundColor: 'action.disabledBackground',
                color: 'action.disabled',
              }
            }}
          >
            {deletingChapter ? t('dashboard.deleting') : t('dashboard.confirmDelete')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 成功/错误提示 Snackbar */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={6000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          variant="filled"
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </Alert>
      </Snackbar>


      </Container>
    </Box>
  )
}
