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
  InputLabel,
  CircularProgress,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Divider,
  IconButton,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Chip,
  Tooltip,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import TheatersIcon from '@mui/icons-material/Theaters'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import ScienceIcon from '@mui/icons-material/Science'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import Menu from '@mui/material/Menu'
import Snackbar from '@mui/material/Snackbar'
import Alert from '@mui/material/Alert'
import { RootState, AppDispatch } from '@/store/store'
import {
  fetchProjects,
  createProject,
  deleteProject,
  updateProject,
} from '@/store/slices/projectSlice'
import { logout } from '@/store/slices/authSlice'
import { startGenerateNextChapter } from '@/store/slices/workflowSlice'
import { generationService, GenerationTask } from '@/services/generation'
import { apiClient } from '@/services/api'
import GenerationProgressDialog from '@/components/GenerationProgressDialog'
import { logger } from '@/utils/logger'

export default function DashboardPage() {
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

  // 生成功能状态
  const [generatingProjectId, setGeneratingProjectId] = useState<number | null>(null)
  const [showGenerationDialog, setShowGenerationDialog] = useState(false)
  const [currentTask, setCurrentTask] = useState<GenerationTask | null>(null)
  const [generationTaskType, setGenerationTaskType] = useState('concept')

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


  // 🆕 标题编辑状态
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editedTitle, setEditedTitle] = useState('')

  // 🆕 类型编辑状态
  const [editingGenreProjectId, setEditingGenreProjectId] = useState<number | null>(null)
  const [editedGenre, setEditedGenre] = useState('')

  // 🆕 生成下一章状态
  const [generatingNextChapter, setGeneratingNextChapter] = useState<Record<number, boolean>>({})
  
  // 🆕 后台任务状态（章节ID -> 是否正在处理）
  const [postSaveProcessing, setPostSaveProcessing] = useState<Set<number>>(new Set())

  // 🆕 Snackbar 状态（用于显示成功/错误提示）
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'info'>('success')

  // 🆕 章节字数统计（每个项目的总字数）
  const [chapterWordCounts, setChapterWordCounts] = useState<Record<number, number>>({})

  // 🆕 项目概念状态（用于判断是否为空白项目）
  const [projectConceptStatus, setProjectConceptStatus] = useState<Record<number, boolean>>({})

  // 🆕 导出到其他模块的状态
  const [exportingChapter, setExportingChapter] = useState<number | null>(null)

  // 🆕 一键导出所有章节状态
  const [exportAllAnchorEl, setExportAllAnchorEl] = useState<null | HTMLElement>(null)
  const [exportingAll, setExportingAll] = useState(false)

  // 🆕 类型映射函数（英文/中文 → 显示标签）
  const getGenreLabel = (genre: string | null | undefined): string => {
    const genreMap: Record<string, string> = {
      // 英文键
      'Fantasy': '奇幻',
      'Science Fiction': '科幻',
      'Romance': '浪漫',
      'Mystery': '悬疑',
      'Thriller': '惊悚',
      'Other': '其他',
      // 中文键（网文题材）
      '修仙': '修仙',
      '玄幻': '玄幻',
      '都市': '都市',
      '悬疑': '悬疑',
      '言情': '言情',
      '耽美': '耽美',
      '科幻': '科幻',
      '纯文学': '纯文学',
    }
    return genreMap[genre || ''] || genre || '未设置'
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
            const response = await fetch(`/api/v1/workflow/${project.id}/all-stages-content`, {
              headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
              },
            })

            if (response.ok) {
              const data = await response.json()
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
            const response = await fetch(`/api/v1/projects/${project.id}/chapters`, {
              headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
              },
            })

            if (response.ok) {
              const chapters = await response.json()
              // 计算所有章节的总字数
              const totalWords = Array.isArray(chapters) 
                ? chapters.reduce((sum: number, ch: any) => sum + (ch.word_count || 0), 0)
                : 0
              wordCounts[project.id] = totalWords
              logger.log(`✅ 项目 ${project.id} 章节总字数: ${totalWords}`)
            } else {
              wordCounts[project.id] = 0
            }
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

    // 导入 WebSocket 实例
    import('@/services/websocket').then(({ workflowWebSocket }) => {
      // 连接 WebSocket
      workflowWebSocket.connect().then(() => {
        workflowWebSocket.joinProject(selectedProjectId)
      }).catch((error: any) => {
        console.error('❗ WebSocket 连接失败:', error)
      })

      // 监听后台任务开始
      workflowWebSocket.onPostSaveTaskStart((data: any) => {
        logger.log('📡 收到后台任务开始:', data)
        if (data.chapter_id) {
          setPostSaveProcessing(prev => new Set(prev).add(data.chapter_id))
        }
      })

      // 监听后台任务完成
      workflowWebSocket.onPostSaveTaskComplete((data: any) => {
        logger.log('✅ 收到后台任务完成:', data)
        if (data.chapter_id) {
          setPostSaveProcessing(prev => {
            const newSet = new Set(prev)
            newSet.delete(data.chapter_id)
            return newSet
          })
        }
      })

      // 🆕 监听任务完成事件（大纲扩展、人物扩展）
      workflowWebSocket.onTaskComplete((data: any) => {
        logger.log('✅ 收到任务完成:', data)
        const taskId = data.task_id || ''
        
        // 如果是扩展大纲或人物任务，刷新章节列表
        if (taskId.startsWith('expand-outline') || taskId.startsWith('expand-characters')) {
          logger.log('🔄 扩展任务完成，刷新章节列表...')
          if (selectedProjectId) {
            loadChapters(selectedProjectId)
          }
        }
      })
    })

    // 清理：组件卸载时移除监听器（不断开连接）
    return () => {
      import('@/services/websocket').then(({ workflowWebSocket }) => {
        // 只移除监听器，保持 WebSocket 连接（其他页面可能还在用）
        workflowWebSocket.onPostSaveTaskStart(() => {})
        workflowWebSocket.onPostSaveTaskComplete(() => {})
        workflowWebSocket.onTaskComplete(() => {})
      })
    }
  }, [selectedProjectId])

  const handleCreateProject = async () => {
    if (formData.title.trim()) {
      try {
        const result = await dispatch(createProject(formData))
        if (result.payload) {
          const newProjectId = result.payload.id
          setFormData({ title: '', description: '', genre: '' })
          setOpenDialog(false)
          // 重新获取项目列表
          dispatch(fetchProjects())

          // 自动初始化五阶段工作流程
          setTimeout(() => {
            handleInitializeWorkflow(newProjectId, result.payload)
          }, 500)
        }
      } catch (error) {
        logger.error('Failed to create project:', error)
        alert('Failed to create project. Please try again.')
      }
    }
  }

  // 处理"开始创作"按钮点击 - 直接跳转到工作流程页面
  const handleStartCreation = async () => {
    try {
      logger.log('🔍 [DEBUG] handleStartCreation 开始执行')

      // 创建一个临时项目用于工作流程
      const tempProjectData = {
        title: 'New Novel',
        description: 'New novel creation',
        genre: 'Fantasy',
      }

      logger.log('🔍 [DEBUG] 准备创建项目，数据:', tempProjectData)

      const result = await dispatch(createProject(tempProjectData))

      logger.log('🔍 [DEBUG] dispatch 返回结果:', result)
      logger.log('🔍 [DEBUG] result.payload:', result.payload)

      if (result.payload) {
        const newProjectId = result.payload.id
        logger.log('🔍 [DEBUG] 项目创建成功，ID:', newProjectId)
        logger.log('🔍 [DEBUG] 准备跳转到 /workflow/' + newProjectId)

        // 直接跳转到工作流程页面，带上 autoStart 参数自动打开开始创作对话框
        navigate(`/workflow/${newProjectId}?autoStart=true`)

        logger.log('🔍 [DEBUG] 跳转完成')
      } else {
        logger.error('❌ [ERROR] result.payload 为空')
        logger.error('❌ [ERROR] 完整的 result 对象:', result)
        alert('Failed to create project. Please try again.')
      }
    } catch (error) {
      logger.error('❌ [ERROR] 捕获到异常:', error)
      logger.error('Failed to create temporary project:', error)
      alert('Failed to start creation. Please try again.')
    }
  }

  const handleInitializeWorkflow = async (projectId: number, _project: any) => {
    setGeneratingProjectId(projectId)
    setGenerationTaskType('workflow')
    setShowGenerationDialog(true)

    try {
      await generationService.initializeWorkflow(
        projectId,
        (task) => {
          setCurrentTask(task)
        }
      )
    } catch (error) {
      logger.error('Failed to initialize workflow:', error)
      setCurrentTask({
        task_id: '',
        task_type: 'workflow',
        status: 'failed',
        error: error instanceof Error ? error.message : 'Unknown error',
        created_at: new Date().toISOString(),
      })
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
    dispatch(logout())
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
    console.log('切换排序方式:', newOrder)
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
      setSnackbarMessage('章节删除成功')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      
      // 刷新章节列表
      await loadChapters(selectedProjectId)
      
      // 关闭对话框
      handleCloseDeleteChapterDialog()
    } catch (err) {
      logger.error('❌ 删除章节失败:', err)
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('删除章节失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setDeletingChapter(false)
    }
  }

  // 🆕 处理标题编辑
  const handleStartEditTitle = (projectId: number, currentTitle: string) => {
    setEditingProjectId(projectId)
    setEditedTitle(currentTitle)
  }

  const handleCancelEditTitle = () => {
    setEditingProjectId(null)
    setEditedTitle('')
  }

  const handleSaveTitle = async (projectId: number) => {
    if (!editedTitle.trim()) {
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('项目标题不能为空')
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
      return
    }

    try {
      logger.log('📝 开始更新项目标题:', { projectId, newTitle: editedTitle })
      
      await dispatch(updateProject({ 
        projectId, 
        data: { title: editedTitle.trim() } 
      }))
      
      logger.log('✅ 标题更新成功')
      setEditingProjectId(null)
      setEditedTitle('')
      
      // 显示成功提示
      setSnackbarMessage('项目标题更新成功')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      
      // 刷新项目列表
      dispatch(fetchProjects())
    } catch (error) {
      logger.error('❌ 更新标题失败:', error)
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('更新标题失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 🆕 编辑类型功能
  const handleStartEditGenre = (projectId: number, currentGenre: string) => {
    setEditingGenreProjectId(projectId)
    setEditedGenre(currentGenre || '')
  }

  const handleCancelEditGenre = () => {
    setEditingGenreProjectId(null)
    setEditedGenre('')
  }

  const handleSaveGenre = async (projectId: number) => {
    if (!editedGenre) {
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('请选择项目类型')
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
      return
    }

    try {
      logger.log('📝 开始更新项目类型:', { projectId, newGenre: editedGenre })
      
      await dispatch(updateProject({ 
        projectId, 
        data: { genre: editedGenre } 
      }))
      
      logger.log('✅ 类型更新成功')
      setEditingGenreProjectId(null)
      setEditedGenre('')
      
      // 刷新项目列表
      dispatch(fetchProjects())
      
      // 显示成功提示
      setSnackbarMessage(`✅ 类型已更新为：${getGenreLabel(editedGenre)}`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      logger.error('❌ 更新类型失败:', error)
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('更新类型失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 🆕 生成下一章功能（与 WorkflowControlPage 完全相同）
  const handleGenerateNextChapter = async (projectId: number) => {
    setGeneratingNextChapter(prev => ({ ...prev, [projectId]: true }))

    try {
      logger.log('📍 开始生成下一章（异步模式）...')

      const response = await fetch(`/api/v1/workflow/${projectId}/generate-next-chapter`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
      })

      if (response.ok) {
        const data = await response.json()
        logger.log('✅ 异步任务已创建:', data)

        // 后端返回: { task_id, status, message, next_chapter_number }
        const { task_id, next_chapter_number } = data

        // 🆕 先设置 Redux 状态（确保在跳转前状态已就绪）
        dispatch(startGenerateNextChapter({ taskId: task_id, chapterNumber: next_chapter_number }))

        // 显示提示
        setSnackbarMessage(`🚀 正在生成第${next_chapter_number}章，跳转到工作流页面查看进度...`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 🔧 关键修复：等待提示消息显示后再跳转，同时不重置状态
        setTimeout(() => {
          // 跳转到工作流页面（不再需要传递 URL 参数，因为状态已在 Redux 中）
          navigate(`/workflow/${projectId}`)
        }, 500)  // 等待500ms让用户看到提示
      } else {
        const errorData = await response.json()
        logger.error('❌ 创建生成任务失败:', errorData)

        setSnackbarMessage(errorData.detail || errorData.error || '创建生成任务失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        // 🔧 只在失败时重置状态
        setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
      }
    } catch (error) {
      logger.error('❌ 生成下一章异常:', error)

      setSnackbarMessage('创建生成任务失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      // 🔧 只在异常时重置状态
      setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
    }
    // 🔧 关键：移除 finally 块，不自动重置状态
    // 让 WorkflowControlPage 在任务完成时重置
  }

  // 🆕 导出到有声小说模块
  const handleExportToAudio = async (chapter: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setExportingChapter(chapter.id)
    
    try {
      // 获取章节完整内容
      const response = await fetch(`/api/v1/chapters/${chapter.id}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const data = await response.json()
        // 暂存到 localStorage
        localStorage.setItem('audio_import_content', JSON.stringify({
          fromProjectId: selectedProjectId,
          chapterId: chapter.id,
          title: data.title,
          content: data.content,
        }))
        
        setSnackbarMessage('📖 章节内容已准备，有声小说模块开发中...')
        setSnackbarSeverity('info')
        setSnackbarOpen(true)
        // 未来跳转: navigate('/audio?from=novel&chapterId=' + chapter.id)
      } else {
        throw new Error('获取章节内容失败')
      }
    } catch (error) {
      logger.error('❌ 导出到有声小说失败:', error)
      setSnackbarMessage('导出失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingChapter(null)
    }
  }

  // 🆕 导出到短剧模块
  const handleExportToDrama = async (chapter: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setExportingChapter(chapter.id)
    
    try {
      const response = await fetch(`/api/v1/chapters/${chapter.id}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const data = await response.json()
        localStorage.setItem('drama_import_content', JSON.stringify({
          fromProjectId: selectedProjectId,
          chapterId: chapter.id,
          title: data.title,
          content: data.content,
        }))
        
        setSnackbarMessage('🎬 章节内容已准备，短剧模块开发中...')
        setSnackbarSeverity('info')
        setSnackbarOpen(true)
        // 未来跳转: navigate('/drama?from=novel&chapterId=' + chapter.id)
      } else {
        throw new Error('获取章节内容失败')
      }
    } catch (error) {
      logger.error('❌ 导出到短剧失败:', error)
      setSnackbarMessage('导出失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingChapter(null)
    }
  }

  // 🆕 导出到织文无迹模块
  const handleExportToZhiwen = async (chapter: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setExportingChapter(chapter.id)
    
    try {
      const response = await fetch(`/api/v1/chapters/${chapter.id}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const data = await response.json()
        localStorage.setItem('zhiwen_import_content', JSON.stringify({
          fromProjectId: selectedProjectId,
          chapterId: chapter.id,
          title: data.title,
          content: data.content,
        }))
        
        setSnackbarMessage('✨ 章节内容已准备，正在跳转到织文无迹...')
        setSnackbarSeverity('info')
        setSnackbarOpen(true)
        // 跳转到织文无迹模块
        setTimeout(() => navigate('/ai-trace'), 500)
      } else {
        throw new Error('获取章节内容失败')
      }
    } catch (error) {
      logger.error('❌ 导出到织文无迹失败:', error)
      setSnackbarMessage('导出失败，请重试')
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
      const response = await fetch(`/api/v1/projects/${selectedProjectId}/export/all/txt`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        // 从 Content-Disposition 获取文件名，否则使用默认名
        const contentDisposition = response.headers.get('Content-Disposition')
        let filename = '小说全文.txt'
        if (contentDisposition) {
          const match = contentDisposition.match(/filename\*=UTF-8''(.+)/)
          if (match) {
            filename = decodeURIComponent(match[1])
          }
        }
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        setSnackbarMessage('📄 TXT文件导出成功')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        throw new Error('导出失败')
      }
    } catch (error) {
      logger.error('❗ 导出 TXT 失败:', error)
      setSnackbarMessage('导出失败，请重试')
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
      const response = await fetch(`/api/v1/projects/${selectedProjectId}/export/all/docx`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        // 从 Content-Disposition 获取文件名
        const contentDisposition = response.headers.get('Content-Disposition')
        let filename = '小说全文.docx'
        if (contentDisposition) {
          const match = contentDisposition.match(/filename\*=UTF-8''(.+)/)
          if (match) {
            filename = decodeURIComponent(match[1])
          }
        }
        a.download = filename
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
        setSnackbarMessage('📝 DOCX文件导出成功')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        throw new Error('导出失败')
      }
    } catch (error) {
      logger.error('❗ 导出 DOCX 失败:', error)
      setSnackbarMessage('导出失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExportingAll(false)
    }
  }

  return (
    <Box sx={{ 
      minHeight: '100vh', 
      background: 'linear-gradient(135deg, #6b7280 0%, #4b5563 50%, #374151 100%)',
      position: 'relative',
    }}>
      {/* 顶部标题栏 */}
      <Box
        sx={{
          background: 'linear-gradient(135deg, #1976d2 0%, #1565c0 100%)',
          py: 3,
          px: 3,
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        }}
      >
        <Container maxWidth="lg">
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            {/* 左侧：返回按钮 + 标题 */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <IconButton
                onClick={() => navigate('/home')}
                sx={{
                  color: 'white',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                  '&:hover': {
                    backgroundColor: 'rgba(255,255,255,0.2)',
                  },
                }}
                title="返回创作工坊"
              >
                <ArrowBackIcon />
              </IconButton>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <AutoStoriesIcon sx={{ fontSize: 32, color: 'white' }} />
                <Box>
                  <Typography
                    variant="h5"
                    sx={{
                      color: 'white',
                      fontWeight: 700,
                      letterSpacing: '0.5px',
                    }}
                  >
                    灵感方舟
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ color: 'rgba(255,255,255,0.8)', fontSize: '0.85rem' }}
                  >
                    小说创作 · 管理您的创作项目
                  </Typography>
                </Box>
              </Box>
            </Box>

            {/* 右侧：操作按钮 */}
            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={handleStartCreation}
                sx={{
                  backgroundColor: 'white',
                  color: '#1976d2',
                  fontWeight: 600,
                  '&:hover': {
                    backgroundColor: 'rgba(255,255,255,0.9)',
                  },
                }}
              >
                新建项目
              </Button>
              <Button
                variant="outlined"
                startIcon={<ScienceIcon />}
                onClick={() => navigate('/prompt-evolution')}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': {
                    borderColor: 'white',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  },
                }}
              >
                提示词优化
              </Button>
              <Button
                variant="outlined"
                onClick={handleLogout}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': {
                    borderColor: 'white',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  },
                }}
              >
                退出登录
              </Button>
            </Box>
          </Box>
        </Container>
      </Box>

      {/* 项目列表区域 */}
      <Container maxWidth="lg" sx={{ py: 4 }}>

      <Grid container spacing={3}>
        {projects.map((project) => {
          // 根据题材选择书本封面颜色
          const getBookColors = (genre: string | undefined) => {
            const colors: Record<string, { primary: string; secondary: string; accent: string; text: string }> = {
              '修仙': { primary: '#1e3a8a', secondary: '#2563eb', accent: '#fbbf24', text: '#fef3c7' },
              '玄幻': { primary: '#6b21a8', secondary: '#7c3aed', accent: '#fb923c', text: '#fed7aa' },
              '都市': { primary: '#ea580c', secondary: '#f97316', accent: '#fef3c7', text: '#fef3c7' },
              '言情': { primary: '#f472b6', secondary: '#f9a8d4', accent: '#f59e0b', text: '#fef3c7' },
              '耽美': { primary: '#831843', secondary: '#9f1239', accent: '#fda4af', text: '#fce7f3' },
              '悬疑': { primary: '#0f172a', secondary: '#1e293b', accent: '#dc2626', text: '#fecaca' },
              '科幻': { primary: '#0891b2', secondary: '#06b6d4', accent: '#a5f3fc', text: '#ecfeff' },
              '纯文学': { primary: '#44403c', secondary: '#57534e', accent: '#d6d3d1', text: '#f5f5f4' },
              'Fantasy': { primary: '#14532d', secondary: '#166534', accent: '#fbbf24', text: '#fef3c7' },
            }
            return colors[genre || ''] || { primary: '#713f12', secondary: '#92400e', accent: '#fbbf24', text: '#fef3c7' }
          }
          const bookColors = getBookColors(project.genre)
          const isDisabled = generatingProjectId === project.id || generatingNextChapter[project.id]

          return (
          <Grid item xs={6} sm={4} md={3} lg={2.4} key={project.id}>
            {/* 书本容器 - 包含书脊和页面效果 */}
            <Tooltip title={isDisabled ? '正在处理中...' : projectConceptStatus[project.id] === false ? '点击开始创作' : '点击进入工作流'} arrow placement="top">
            <Box
              sx={{
                position: 'relative',
                height: '300px',
                maxWidth: '240px',
                margin: '0 auto',
                perspective: '1000px',
                cursor: isDisabled ? 'default' : 'pointer',
              }}
              onClick={() => {
                if (!isDisabled) {
                  // 🔥 空白项目智能跳转：跳转到输入框区域自动触发对话框
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
              
              {/* 书本主体 */}
              <Box
                sx={{
                  position: 'absolute',
                  left: 0,
                  right: 14,
                  top: 0,
                  bottom: 0,
                  display: 'flex',
                  opacity: isDisabled ? 0.7 : 1,
                  transition: 'all 0.3s ease-in-out',
                  transform: isDisabled ? 'none' : 'rotateY(0deg)',
                  '&:hover': {
                    transform: isDisabled ? 'none' : 'translateX(-8px) rotateY(-5deg)',
                    '& .book-spine': {
                      boxShadow: isDisabled ? undefined : '4px 0 8px rgba(0,0,0,0.3)',
                    },
                  },
                  '&:hover ~ .book-pages': {
                    transform: 'translateX(-8px)',
                    boxShadow: 'inset -2px 0 6px rgba(0,0,0,0.15), 2px 0 8px rgba(0,0,0,0.2)',
                  },
                }}
              >
                {/* 书脊 */}
                <Box
                  className="book-spine"
                  sx={{
                    width: '22px',
                    background: `linear-gradient(135deg, ${bookColors.secondary} 0%, ${bookColors.primary} 50%, ${bookColors.secondary} 100%)`,
                    borderRadius: '3px 0 0 3px',
                    boxShadow: '2px 0 4px rgba(0,0,0,0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    position: 'relative',
                    transition: 'box-shadow 0.3s ease',
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: '10%',
                      bottom: '10%',
                      left: '50%',
                      width: '1px',
                      background: `linear-gradient(to bottom, transparent, ${bookColors.accent}40, ${bookColors.accent}, ${bookColors.accent}40, transparent)`,
                      transform: 'translateX(-50%)',
                    },
                  }}
                >
                  <Typography
                    sx={{
                      writingMode: 'vertical-rl',
                      textOrientation: 'mixed',
                      color: bookColors.accent,
                      fontSize: '0.55rem',
                      fontWeight: 600,
                      letterSpacing: '1px',
                      textShadow: '0 0 4px rgba(0,0,0,0.5)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxHeight: '85%',
                    }}
                  >
                    {project.title}
                  </Typography>
                </Box>

                {/* 封面 */}
                <Box
                  sx={{
                    flex: 1,
                    background: `linear-gradient(145deg, ${bookColors.primary} 0%, ${bookColors.secondary} 100%)`,
                    borderRadius: '0 4px 4px 0',
                    position: 'relative',
                    overflow: 'hidden',
                    boxShadow: '4px 4px 12px rgba(0,0,0,0.3)',
                    display: 'flex',
                    flexDirection: 'column',
                    '&::before': {
                      content: '""',
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      background: `radial-gradient(circle at 30% 30%, ${bookColors.accent}15 0%, transparent 60%), repeating-linear-gradient(45deg, transparent, transparent 10px, ${bookColors.accent}08 10px, ${bookColors.accent}08 11px)`,
                      pointerEvents: 'none',
                      zIndex: 0,
                    },
                    '&::after': {
                      content: '""',
                      position: 'absolute',
                      top: 12,
                      left: 12,
                      right: 12,
                      bottom: 12,
                      border: `1px solid ${bookColors.accent}40`,
                      borderRadius: '2px',
                      pointerEvents: 'none',
                      zIndex: 1,
                    },
                  }}
                >
                  {/* 四角装饰 - 左上 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 8,
                      left: 8,
                      width: '30px',
                      height: '30px',
                      borderTop: `2px solid ${bookColors.accent}50`,
                      borderLeft: `2px solid ${bookColors.accent}50`,
                      borderRadius: '2px 0 0 0',
                      zIndex: 2,
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        top: -2,
                        left: -2,
                        width: '8px',
                        height: '8px',
                        background: bookColors.accent,
                        opacity: 0.4,
                        borderRadius: '50%',
                      },
                    }}
                  />
                  {/* 四角装饰 - 右上 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 8,
                      right: 8,
                      width: '30px',
                      height: '30px',
                      borderTop: `2px solid ${bookColors.accent}50`,
                      borderRight: `2px solid ${bookColors.accent}50`,
                      borderRadius: '0 2px 0 0',
                      zIndex: 2,
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        top: -2,
                        right: -2,
                        width: '8px',
                        height: '8px',
                        background: bookColors.accent,
                        opacity: 0.4,
                        borderRadius: '50%',
                      },
                    }}
                  />
                  {/* 四角装饰 - 左下 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      bottom: 8,
                      left: 8,
                      width: '30px',
                      height: '30px',
                      borderBottom: `2px solid ${bookColors.accent}50`,
                      borderLeft: `2px solid ${bookColors.accent}50`,
                      borderRadius: '0 0 0 2px',
                      zIndex: 2,
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        bottom: -2,
                        left: -2,
                        width: '8px',
                        height: '8px',
                        background: bookColors.accent,
                        opacity: 0.4,
                        borderRadius: '50%',
                      },
                    }}
                  />
                  {/* 四角装饰 - 右下 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      bottom: 8,
                      right: 8,
                      width: '30px',
                      height: '30px',
                      borderBottom: `2px solid ${bookColors.accent}50`,
                      borderRight: `2px solid ${bookColors.accent}50`,
                      borderRadius: '0 0 2px 0',
                      zIndex: 2,
                      '&::before': {
                        content: '""',
                        position: 'absolute',
                        bottom: -2,
                        right: -2,
                        width: '8px',
                        height: '8px',
                        background: bookColors.accent,
                        opacity: 0.4,
                        borderRadius: '50%',
                      },
                    }}
                  />
                  {/* 生成中的加载指示器 */}
                  {generatingProjectId === project.id && (
                    <Box
                      sx={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        backgroundColor: 'rgba(0, 0, 0, 0.6)',
                        zIndex: 10,
                        borderRadius: '0 4px 4px 0',
                      }}
                    >
                      <Box sx={{ textAlign: 'center' }}>
                        <CircularProgress size={40} sx={{ mb: 1, color: bookColors.accent }} />
                        <Typography variant="caption" sx={{ color: bookColors.text, display: 'block' }}>执笔中...</Typography>
                      </Box>
                    </Box>
                  )}

                  {/* 封面内容区 */}
                  <Box sx={{ p: 1.5, pt: 2, flexGrow: 1, position: 'relative', zIndex: 1 }}>
                    {/* 装饰性顶部花纹 */}
                    <Box sx={{ 
                      textAlign: 'center', 
                      mb: 1,
                      color: bookColors.accent,
                      fontSize: '0.75rem',
                      opacity: 0.8,
                      letterSpacing: '4px',
                    }}>
                      ✦ ✦ ✦
                    </Box>

                    {/* 书名 */}
                    {editingProjectId === project.id ? (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 2 }} onClick={(e) => e.stopPropagation()}>
                        <TextField
                          size="small"
                          value={editedTitle}
                          onChange={(e) => setEditedTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveTitle(project.id)
                            else if (e.key === 'Escape') handleCancelEditTitle()
                          }}
                          autoFocus
                          fullWidth
                          sx={{ 
                            flex: 1,
                            '& .MuiOutlinedInput-root': {
                              color: bookColors.text,
                              backgroundColor: 'rgba(255,255,255,0.1)',
                              '& fieldset': { borderColor: bookColors.accent },
                            },
                            '& .MuiOutlinedInput-input': { color: bookColors.text },
                          }}
                        />
                        <IconButton size="small" onClick={() => handleSaveTitle(project.id)} sx={{ color: bookColors.accent }}>
                          <CheckIcon fontSize="small" />
                        </IconButton>
                        <IconButton size="small" onClick={handleCancelEditTitle} sx={{ color: bookColors.text }}>
                          <CloseIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    ) : (
                      <Typography
                        onClick={(e) => { e.stopPropagation(); handleStartEditTitle(project.id, project.title) }}
                        title="点击编辑书名"
                        sx={{
                          fontFamily: '"STKaiti", "KaiTi", "楷体", serif',
                          fontSize: '1.1rem',
                          fontWeight: 700,
                          color: bookColors.accent,
                          textAlign: 'center',
                          mb: 1,
                          textShadow: `0 1px 3px rgba(0,0,0,0.5), 0 0 15px ${bookColors.accent}30`,
                          letterSpacing: '2px',
                          cursor: 'pointer',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          lineHeight: 1.3,
                          minHeight: '2.6em',
                          transition: 'text-shadow 0.3s ease',
                          '&:hover': {
                            textShadow: `0 2px 4px rgba(0,0,0,0.5), 0 0 25px ${bookColors.accent}60`,
                          },
                        }}
                      >
                        {project.title}
                      </Typography>
                    )}

                    {/* 描述 */}
                    <Typography
                      sx={{
                        fontFamily: '"STFangsong", "FangSong", "仿宋", serif',
                        fontSize: '0.7rem',
                        color: bookColors.text,
                        opacity: 0.85,
                        textAlign: 'center',
                        mb: 1,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        lineHeight: 1.5,
                        minHeight: '2.1em',
                      }}
                    >
                      {project.description || '一段传奇即将开始...'}
                    </Typography>

                    {/* 题材标签 */}
                    <Box sx={{ textAlign: 'center', mb: 0.5 }}>
                      {editingGenreProjectId === project.id ? (
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }} onClick={(e) => e.stopPropagation()}>
                          <FormControl size="small" sx={{ minWidth: 100 }}>
                            <Select
                              value={editedGenre}
                              onChange={(e) => setEditedGenre(e.target.value)}
                              sx={{ 
                                fontSize: '0.75rem', 
                                height: '28px',
                                color: bookColors.text,
                                backgroundColor: 'rgba(255,255,255,0.1)',
                                '& .MuiOutlinedInput-notchedOutline': { borderColor: bookColors.accent },
                                '& .MuiSvgIcon-root': { color: bookColors.accent },
                              }}
                            >
                              <MenuItem value="修仙">修仙</MenuItem>
                              <MenuItem value="玄幻">玄幻</MenuItem>
                              <MenuItem value="都市">都市</MenuItem>
                              <MenuItem value="言情">言情</MenuItem>
                              <MenuItem value="耽美">耽美</MenuItem>
                              <MenuItem value="悬疑">悬疑</MenuItem>
                              <MenuItem value="科幻">科幻</MenuItem>
                              <MenuItem value="纯文学">纯文学</MenuItem>
                              <MenuItem value="Fantasy">奇幻</MenuItem>
                              <MenuItem value="Other">其他</MenuItem>
                            </Select>
                          </FormControl>
                          <IconButton size="small" onClick={() => handleSaveGenre(project.id)} sx={{ color: bookColors.accent }}>
                            <CheckIcon fontSize="small" />
                          </IconButton>
                          <IconButton size="small" onClick={handleCancelEditGenre} sx={{ color: bookColors.text }}>
                            <CloseIcon fontSize="small" />
                          </IconButton>
                        </Box>
                      ) : (
                        <Chip
                          label={`『${getGenreLabel(project.genre)}』`}
                          size="small"
                          onClick={(e) => { e.stopPropagation(); handleStartEditGenre(project.id, project.genre || '') }}
                          sx={{
                            backgroundColor: 'transparent',
                            border: `1px solid ${bookColors.accent}60`,
                            color: bookColors.accent,
                            fontFamily: '"STKaiti", "KaiTi", "楷体", serif',
                            fontSize: '0.65rem',
                            height: '20px',
                            letterSpacing: '1px',
                            cursor: 'pointer',
                            '&:hover': {
                              backgroundColor: `${bookColors.accent}20`,
                            },
                          }}
                        />
                      )}
                    </Box>

                    {/* 字数统计 */}
                    <Typography
                      sx={{
                        textAlign: 'center',
                        color: bookColors.text,
                        opacity: 0.6,
                        fontSize: '0.6rem',
                        fontStyle: 'italic',
                      }}
                    >
                      ─ {(chapterWordCounts[project.id] || 0).toLocaleString()}字 ─
                    </Typography>
                  </Box>

                  {/* 底部操作区 - 古籍艺术字风格 */}
                  <Box
                    sx={{
                      p: 1,
                      pt: 0.5,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 0.3,
                      alignItems: 'center',
                      position: 'relative',
                      zIndex: 1,
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* 第一排：典籍 | 目录 */}
                    <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
                      <Tooltip title="进入知识库" arrow>
                        <Typography
                          onClick={() => !isDisabled && navigate(`/knowledge-base/${project.id}`)}
                          sx={{
                            fontFamily: '楷体, KaiTi, serif',
                            fontSize: '0.85rem',
                            color: bookColors.text,
                            cursor: isDisabled ? 'default' : 'pointer',
                            opacity: isDisabled ? 0.5 : 0.85,
                            letterSpacing: '2px',
                            transition: 'all 0.2s ease',
                            textShadow: `0 0 8px ${bookColors.primary}`,
                            '&:hover': {
                              opacity: 1,
                              color: bookColors.accent,
                              textShadow: `0 0 12px ${bookColors.accent}`,
                              transform: 'scale(1.05)',
                            },
                          }}
                        >
                          典 籍
                        </Typography>
                      </Tooltip>
                      <Typography sx={{ color: `${bookColors.text}40`, fontSize: '0.7rem' }}>|</Typography>
                      <Tooltip title="查看章节列表" arrow>
                        <Typography
                          onClick={() => !isDisabled && handleOpenChaptersDrawer(project.id)}
                          sx={{
                            fontFamily: '楷体, KaiTi, serif',
                            fontSize: '0.85rem',
                            color: bookColors.text,
                            cursor: isDisabled ? 'default' : 'pointer',
                            opacity: isDisabled ? 0.5 : 0.85,
                            letterSpacing: '2px',
                            transition: 'all 0.2s ease',
                            textShadow: `0 0 8px ${bookColors.primary}`,
                            '&:hover': {
                              opacity: 1,
                              color: bookColors.accent,
                              textShadow: `0 0 12px ${bookColors.accent}`,
                              transform: 'scale(1.05)',
                            },
                          }}
                        >
                          目 录
                        </Typography>
                      </Tooltip>
                    </Box>
                    {/* 第二排：焚毁 | 续写 */}
                    <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
                      <Tooltip title="删除项目" arrow>
                        <Typography
                          onClick={() => !isDisabled && handleDeleteProject(project.id)}
                          sx={{
                            fontFamily: '楷体, KaiTi, serif',
                            fontSize: '0.8rem',
                            color: '#ef5350',
                            cursor: isDisabled ? 'default' : 'pointer',
                            opacity: isDisabled ? 0.4 : 0.7,
                            letterSpacing: '2px',
                            transition: 'all 0.2s ease',
                            '&:hover': {
                              opacity: 1,
                              textShadow: '0 0 8px #ef5350',
                              transform: 'scale(1.05)',
                            },
                          }}
                        >
                          焚 毁
                        </Typography>
                      </Tooltip>
                      <Typography sx={{ color: `${bookColors.text}40`, fontSize: '0.7rem' }}>|</Typography>
                      <Tooltip title="续写下一章" arrow>
                        <Typography
                          onClick={() => !isDisabled && handleGenerateNextChapter(project.id)}
                          sx={{
                            fontFamily: '楷体, KaiTi, serif',
                            fontSize: '0.85rem',
                            color: bookColors.accent,
                            cursor: isDisabled ? 'default' : 'pointer',
                            opacity: isDisabled ? 0.5 : 1,
                            letterSpacing: '2px',
                            fontWeight: 600,
                            transition: 'all 0.2s ease',
                            textShadow: `0 0 8px ${bookColors.accent}60`,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 0.5,
                            '&:hover': {
                              textShadow: `0 0 16px ${bookColors.accent}`,
                              transform: 'scale(1.08)',
                            },
                          }}
                        >
                          {generatingNextChapter[project.id] 
                            ? <><CircularProgress size={12} sx={{ color: 'inherit' }} /> 续写中...</>
                            : '续 写'
                          }
                        </Typography>
                      </Tooltip>
                    </Box>
                  </Box>
                </Box>
              </Box>
            
            {/* 页面层叠效果 */}
            <Box
              className="book-pages"
              sx={{
                position: 'absolute',
                right: 2,
                top: 8,
                bottom: 8,
                width: '12px',
                background: 'linear-gradient(to right, #f5f5dc 0%, #fffef0 50%, #f0ead6 100%)',
                borderRadius: '0 2px 2px 0',
                boxShadow: 'inset -2px 0 4px rgba(0,0,0,0.1)',
                transition: 'all 0.3s ease-in-out',
                '&::before': {
                  content: '""',
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  left: 0,
                  width: '100%',
                  background: 'repeating-linear-gradient(to bottom, transparent 0px, transparent 3px, rgba(0,0,0,0.03) 3px, rgba(0,0,0,0.03) 4px)',
                },
              }}
            />
            </Box>
            </Tooltip>
          </Grid>
        )
      })}
      </Grid>

      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            创建新项目
          </Typography>
          <TextField
            fullWidth
            label="项目标题"
            value={formData.title}
            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
            margin="normal"
            required
          />
          <TextField
            fullWidth
            label="项目描述"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            margin="normal"
            multiline
            rows={3}
          />
          <FormControl fullWidth margin="normal">
            <InputLabel>类型</InputLabel>
            <Select
              value={formData.genre}
              onChange={(e) => setFormData({ ...formData, genre: e.target.value })}
              label="类型"
            >
              <MenuItem value="修仙">修仙</MenuItem>
              <MenuItem value="玄幻">玄幻</MenuItem>
              <MenuItem value="都市">都市</MenuItem>
              <MenuItem value="言情">言情</MenuItem>
              <MenuItem value="耽美">耽美</MenuItem>
              <MenuItem value="悬疑">悬疑</MenuItem>
              <MenuItem value="科幻">科幻</MenuItem>
              <MenuItem value="纯文学">纯文学</MenuItem>
              <MenuItem value="Fantasy">奇幻</MenuItem>
              <MenuItem value="Other">其他</MenuItem>
            </Select>
          </FormControl>
          <Box sx={{ mt: 3, display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              fullWidth
              onClick={handleCreateProject}
            >
              创建
            </Button>
            <Button
              variant="outlined"
              fullWidth
              onClick={() => setOpenDialog(false)}
            >
              取消
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteConfirmOpen} onClose={handleCancelDelete} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            删除项目
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 3 }}>
            您确定要删除该项目吗？此操作无法撤销。
          </Typography>
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button
              variant="outlined"
              onClick={handleCancelDelete}
            >
              取消
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={handleConfirmDelete}
            >
              删除
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 生成进度对话框 */}
      <GenerationProgressDialog
        open={showGenerationDialog}
        taskType={generationTaskType}
        task={currentTask}
        onClose={() => {
          setShowGenerationDialog(false)
          setGeneratingProjectId(null)
          setCurrentTask(null)
        }}
        onRetry={() => {
          // 重试逻辑可以根据需要实现
          if (generatingProjectId) {
            setShowGenerationDialog(false)
            setCurrentTask(null)
          }
        }}
      />

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
            <Typography variant="h6">📚 章节列表</Typography>
            <Tooltip title={chapterSortOrder === 'asc' ? '当前：正序，点击倒序' : '当前：倒序，点击正序'} placement="top">
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
              <Tooltip title="一键导出全文" placement="top">
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
              关闭
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
            📄 导出为 TXT
          </MenuItem>
          <MenuItem onClick={handleExportAllDocx}>
            📝 导出为 DOCX
          </MenuItem>
        </Menu>

        {chaptersLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
            <CircularProgress size={40} />
          </Box>
        ) : chapters.length === 0 ? (
          <Box sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="textSecondary">
              暂无章节
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
                    {/* 🎧 导出到有声小说 */}
                    <IconButton
                      edge="end"
                      aria-label="export-audio"
                      size="small"
                      color="primary"
                      onClick={(e) => handleExportToAudio(chapter, e)}
                      title="导入有声小说模块"
                      disabled={exportingChapter === chapter.id}
                      sx={{
                        '&:hover': {
                          backgroundColor: '#e3f2fd'
                        }
                      }}
                    >
                      <HeadphonesIcon fontSize="small" />
                    </IconButton>
                    {/* 🎬 导出到短剧 */}
                    <IconButton
                      edge="end"
                      aria-label="export-drama"
                      size="small"
                      color="secondary"
                      onClick={(e) => handleExportToDrama(chapter, e)}
                      title="导入短剧模块"
                      disabled={exportingChapter === chapter.id}
                      sx={{
                        '&:hover': {
                          backgroundColor: '#f3e5f5'
                        }
                      }}
                    >
                      <TheatersIcon fontSize="small" />
                    </IconButton>
                    {/* ✨ 导出到织文无迹 */}
                    <IconButton
                      edge="end"
                      aria-label="export-zhiwen"
                      size="small"
                      color="success"
                      onClick={(e) => handleExportToZhiwen(chapter, e)}
                      title="导入织文无迹模块"
                      disabled={exportingChapter === chapter.id}
                      sx={{
                        '&:hover': {
                          backgroundColor: '#e8f5e9'
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
                        color: '#b71c1c',
                        '&:hover': {
                          backgroundColor: '#ffcdd2',
                          color: '#c62828',
                        }
                      }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Box>
                }
              >
                <ListItemButton
                  onClick={() => handleChapterClick(chapter.id)}
                  sx={{
                    py: 1.5,
                    '&:hover': {
                      backgroundColor: 'action.hover',
                    },
                  }}
                >
                  <ListItemText
                    primary={(
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <span>{chapter.title}</span>
                        {postSaveProcessing.has(chapter.id) && (
                          <Chip
                            label="处理中..."
                            size="small"
                            color="primary"
                            sx={{ height: 20, fontSize: '0.7rem' }}
                          />
                        )}
                      </Box>
                    )}
                    secondary={`📝 ${chapter.word_count || 0} 字`}
                  />
                </ListItemButton>
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
          确认删除章节
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-chapter-dialog-description">
            你确定要删除章节 <strong>"{chapterToDelete?.title}"</strong> 吗？
            <br />
            <br />
            此操作不可恢复,章节内容将被永久删除。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteChapterDialog} disabled={deletingChapter}>
            取消
          </Button>
          <Button 
            onClick={handleConfirmDeleteChapter} 
            variant="contained"
            disabled={deletingChapter}
            startIcon={deletingChapter ? <CircularProgress size={16} /> : <DeleteIcon />}
            sx={{
              backgroundColor: '#b71c1c',
              color: '#ffffff',
              '&:hover': {
                backgroundColor: '#c62828',
              },
              '&:disabled': {
                backgroundColor: '#e0e0e0',
                color: '#9e9e9e',
              }
            }}
          >
            {deletingChapter ? '删除中...' : '确认删除'}
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
