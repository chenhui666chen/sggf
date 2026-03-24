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
import CloseIcon from '@mui/icons-material/Close'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import FileDownloadIcon from '@mui/icons-material/FileDownload'
import HubIcon from '@mui/icons-material/Hub'
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
import { buildStoryExpansionCompletionMessage } from '@/utils/storyExpansionFeedback'

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
      '奇幻': '奇幻',
      '都市': '都市',
      '悬疑': '悬疑',
      '言情': '言情',
      '耽美': '耽美',
      '科幻': '科幻',
      '纯文学': '纯文学',
    }
    return genreMap[genre || ''] || genre || '未设置'
  }

  // 风格对应颜色映射
  const GENRE_COLORS: Record<string, string> = {
    '修仙': '#e8c46a',
    '玄幻': '#d4a0ff',
    '奇幻': '#72e2a0',
    '都市': '#e8a87c',
    '言情': '#ffb5c8',
    '耐美': '#f9a8d4',
    '悬疑': '#f87171',
    '科幻': '#38bdf8',
    '纯文学': '#c8b99a',
    '浪漫': '#fda4af',
    '惊悚': '#fb923c',
    '其他': '#94a3b8',
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

      // 🆕 监听协同拓展任务完成事件
      workflowWebSocket.onTaskComplete((data: any) => {
        logger.log('✅ 收到任务完成:', data)
        const taskId = data.task_id || ''
        const result = data.result || {}
        
        if (taskId.startsWith('expand-story')) {
          logger.log('🔄 协同拓展任务完成，刷新章节列表...')
          if (selectedProjectId) {
            loadChapters(selectedProjectId)
          }

          const baseMessage = typeof result.message === 'string' && result.message.trim()
            ? result.message.trim()
            : '协同拓展完成'

          setSnackbarMessage(buildStoryExpansionCompletionMessage(baseMessage, result))
          setSnackbarSeverity('success')
          setSnackbarOpen(true)
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
        title: '未命名项目',
        description: '新建创作项目',
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
    } catch (error) {
      console.error('更新书名失败:', error)
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
      setSnackbarMessage(`✅ 类型已更新为：${getGenreLabel(genre)}`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch {
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
          py: { xs: 2, sm: 2.5, md: 3 },
          px: { xs: 2, sm: 3 },
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        }}
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
              <Box sx={{ display: 'flex', alignItems: 'center', gap: { xs: 1, sm: 1.5 } }}>
                <AutoStoriesIcon sx={{ fontSize: { xs: 24, sm: 28, md: 32 }, color: 'white' }} />
                <Box>
                  <Typography
                    variant="h5"
                    sx={{
                      color: 'white',
                      fontWeight: 700,
                      letterSpacing: '0.5px',
                      fontSize: { xs: '1.25rem', sm: '1.5rem', md: '1.5rem' }
                    }}
                  >
                    灵感方舟
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ 
                      color: 'rgba(255,255,255,0.8)', 
                      fontSize: { xs: '0.75rem', sm: '0.85rem' },
                      display: { xs: 'none', sm: 'block' }
                    }}
                  >
                    小说创作 · 管理您的创作项目
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
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  fontSize: { xs: '0.8125rem', sm: '0.875rem' },
                  minHeight: { xs: 36, sm: 40 },
                  '&:hover': {
                    borderColor: 'white',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  },
                }}
              >
                模型档案
              </Button>
              <Button
                variant="outlined"
                onClick={handleLogout}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  fontSize: { xs: '0.8125rem', sm: '0.875rem' },
                  minHeight: { xs: 36, sm: 40 },
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
      <Container maxWidth="lg" sx={{ py: { xs: 2, sm: 3, md: 4 }, px: { xs: 1, sm: 2 } }}>

      <Grid container spacing={{ xs: 1.5, sm: 2, md: 3 }}>
        {projects.map((project) => {
          // 根据题材选择现代化配色方案
          const getBookColors = (genre: string | undefined) => {
            const colors: Record<string, { primary: string; secondary: string; accent: string; text: string; gradient: string }> = {
              '修仙': {
                primary: '#0c1e4a',
                secondary: '#1a3a7a',
                accent: '#e8c46a',
                text: '#fef0c7',
                gradient: 'linear-gradient(160deg, #0c1e4a 0%, #162e68 45%, #1d3d82 75%, #243a6e 100%)',
              },
              '玄幻': {
                primary: '#2d0a4e',
                secondary: '#4a1272',
                accent: '#d4a0ff',
                text: '#f3e4ff',
                gradient: 'linear-gradient(160deg, #1e0535 0%, #2d0a4e 40%, #3f1168 70%, #4a1272 100%)',
              },
              '奇幻': {
                primary: '#0a2e14',
                secondary: '#133d1e',
                accent: '#72e2a0',
                text: '#d4f7e4',
                gradient: 'linear-gradient(160deg, #051a0b 0%, #0a2e14 40%, #0f3d1a 70%, #165226 100%)',
              },
              '都市': {
                primary: '#1a1a2e',
                secondary: '#16213e',
                accent: '#e8a87c',
                text: '#ffeedd',
                gradient: 'linear-gradient(160deg, #12121f 0%, #1a1a2e 40%, #1e2545 70%, #0f3460 100%)',
              },
              '言情': {
                primary: '#3d0b20',
                secondary: '#6b1535',
                accent: '#ffb5c8',
                text: '#ffe4ed',
                gradient: 'linear-gradient(160deg, #2a0716 0%, #3d0b20 40%, #5a1030 70%, #6b1535 100%)',
              },
              '耽美': {
                primary: '#1a0a2e',
                secondary: '#2d1052',
                accent: '#f9a8d4',
                text: '#fce7f3',
                gradient: 'linear-gradient(160deg, #130820 0%, #1a0a2e 40%, #260d42 70%, #2d1052 100%)',
              },
              '悬疑': {
                primary: '#080c14',
                secondary: '#0f172a',
                accent: '#dc2626',
                text: '#fecaca',
                gradient: 'linear-gradient(160deg, #030508 0%, #080c14 40%, #0f172a 70%, #1e2438 100%)',
              },
              '科幻': {
                primary: '#020c1b',
                secondary: '#0a2240',
                accent: '#38bdf8',
                text: '#e0f2fe',
                gradient: 'linear-gradient(160deg, #010810 0%, #020c1b 40%, #0a2240 70%, #0c3060 100%)',
              },
              '纯文学': {
                primary: '#2c2218',
                secondary: '#3d2e20',
                accent: '#c8b99a',
                text: '#f5ede0',
                gradient: 'linear-gradient(160deg, #1c1410 0%, #2c2218 40%, #3d2e20 70%, #4a3828 100%)',
              },
              'Fantasy': {
                primary: '#0a2e14',
                secondary: '#133d1e',
                accent: '#72e2a0',
                text: '#d4f7e4',
                gradient: 'linear-gradient(160deg, #051a0b 0%, #0a2e14 40%, #0f3d1a 70%, #165226 100%)',
              },
            }
                        return colors[genre || ''] || {
              primary: '#1c1a2e',
              secondary: '#2d2a4a',
              accent: '#c4a882',
              text: '#f0e6d3',
              gradient: 'linear-gradient(160deg, #12101e 0%, #1c1a2e 40%, #2d2a4a 70%, #3a3560 100%)',
            }
          }
          const bookColors = getBookColors(project.genre)
          const isDisabled = generatingProjectId === project.id || generatingNextChapter[project.id]

          return (
          <Grid item xs={6} sm={4} md={3} lg={2.4} key={project.id}>
            {/* 现代化书本卡片 - 3D 效果 */}
            <Tooltip title={isDisabled ? '正在处理中...' : projectConceptStatus[project.id] === false ? '点击开始创作' : '点击进入工作流'} arrow placement="top">
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
                        boxShadow: '8px 20px 48px rgba(0,0,0,0.65), 1px 1px 0 rgba(255,255,255,0.08) inset',
                      },
                      '& .book-spine': {
                        boxShadow: '-4px 0 16px rgba(0,0,0,0.5)',
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
                    boxShadow: '-3px 0 12px rgba(0,0,0,0.45)',
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
                      textShadow: '0 1px 3px rgba(0,0,0,0.6)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxHeight: '85%',
                      opacity: 0.9,
                    }}
                  >
                    {project.title}
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
                    boxShadow: '3px 6px 28px rgba(0,0,0,0.55), 1px 1px 0 rgba(255,255,255,0.06) inset',
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
                      background: `
                        repeating-linear-gradient(
                          0deg,
                          transparent,
                          transparent 3px,
                          rgba(255,255,255,0.012) 3px,
                          rgba(255,255,255,0.012) 4px
                        ),
                        radial-gradient(ellipse at 30% 15%, rgba(255,255,255,0.2) 0%, transparent 55%),
                        linear-gradient(170deg, rgba(255,255,255,0.08) 0%, transparent 40%, rgba(0,0,0,0.25) 100%)
                      `,
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
                              backgroundColor: 'rgba(255,255,255,0.1)',
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
                            保存
                          </Typography>
                          <Typography
                            onClick={() => { setEditingTitleProjectId(null); setEditedTitle('') }}
                            sx={{
                              fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' },
                              color: 'rgba(255,255,255,0.3)',
                              cursor: 'pointer',
                              letterSpacing: '1px',
                            }}
                          >
                            取消
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
                          textShadow: '0 2px 10px rgba(0,0,0,0.55)',
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        {project.title}
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
                                  boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                                  backgroundColor: `${GENRE_COLORS[g] || bookColors.accent}15`,
                                  borderRadius: '4px',
                                },
                              }}
                            >
                              {g}
                            </Typography>
                          ))}
                        </Box>
                        <Typography
                          onClick={() => { setEditingGenreProjectId(null); setEditedGenre('') }}
                          sx={{ fontSize: { xs: '0.4rem', sm: '0.45rem', md: '0.5rem' }, color: 'rgba(255,255,255,0.3)', cursor: 'pointer', letterSpacing: '1px' }}
                        >
                          取消
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
                          textShadow: `0 1px 6px rgba(0,0,0,0.5)`,
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
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
                      {(chapterWordCounts[project.id] || 0).toLocaleString()} 字
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
                    <Tooltip title="进入知识库" arrow>
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 600 }}>典籍</Typography>
                      </Box>
                    </Tooltip>
                    <Tooltip title="查看章节列表" arrow>
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 600 }}>目录</Typography>
                      </Box>
                    </Tooltip>
                    {/* 第二行：焚毁 | 续写 */}
                    <Tooltip title="删除项目" arrow>
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                            backgroundColor: 'rgba(239,83,80,0.15)',
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: '#f87171', letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 600, textShadow: '0 1px 3px rgba(239,83,80,0.3)' }}>焚毁</Typography>
                      </Box>
                    </Tooltip>
                    <Tooltip title="续写下一章" arrow>
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
                            boxShadow: '0 12px 28px rgba(0,0,0,0.6), 0 0 0 2px rgba(255,255,255,0.1)',
                            backgroundColor: `${bookColors.accent}15`,
                            borderRadius: '4px',
                          },
                        }}
                      >
                        <Typography sx={{ fontFamily: '楷体，KaiTi, serif', fontSize: { xs: '0.65rem', sm: '0.7rem', md: '0.75rem' }, color: bookColors.accent, letterSpacing: { xs: '1px', sm: '1.5px', md: '2px' }, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 0.4 }}>
                          {generatingNextChapter[project.id]
                            ? <><CircularProgress size={10} sx={{ color: 'inherit' }} />续写</>
                            : '续写'
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
                    background: 'linear-gradient(to right, #ede0c8 0%, #ddd0b0 50%, #ccc090 100%)',
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
                      background: 'repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, rgba(0,0,0,0.04) 2px, rgba(0,0,0,0.04) 3px)',
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
          onClick={handleStartCreation}
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
                boxShadow: '8px 20px 48px rgba(0,0,0,0.65)',
              },
              '& .plus-icon': {
                transform: 'scale(1.1) rotate(90deg)',
                borderColor: 'rgba(180,160,120,0.6)',
                background: 'rgba(180,160,120,0.12)',
              },
              '& .add-text': {
                color: '#e8d5b0',
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
            background: 'linear-gradient(to right, #1a1812 0%, #2a2618 100%)',
            borderRadius: '3px 0 0 3px',
            boxShadow: '-3px 0 12px rgba(0,0,0,0.45)',
            zIndex: 2,
            '&::after': {
              content: '""',
              position: 'absolute',
              top: 0,
              left: '50%',
              width: '1px',
              height: '100%',
              background: 'linear-gradient(to bottom, transparent 5%, rgba(200,180,120,0.25) 50%, transparent 95%)',
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
              background: 'linear-gradient(160deg, #18160e 0%, #221e12 40%, #2c2818 70%, #242010 100%)',
              borderRadius: '2px 6px 6px 2px',
              boxShadow: '3px 6px 28px rgba(0,0,0,0.5)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: { xs: 1.5, sm: 1.8, md: 2 },
              overflow: 'hidden',
              transition: 'all 0.4s ease',
              zIndex: 3,
              border: '1px solid rgba(180,160,80,0.12)',
              '&::after': {
                content: '""',
                position: 'absolute',
                top: { xs: '8px', sm: '10px', md: '12px' },
                left: { xs: '8px', sm: '10px', md: '12px' },
                right: { xs: '8px', sm: '10px', md: '12px' },
                bottom: { xs: '8px', sm: '10px', md: '12px' },
                border: '1px solid rgba(180,160,80,0.18)',
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
                border: '1px solid rgba(180,160,100,0.35)',
                background: 'rgba(180,160,100,0.07)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                zIndex: 1,
              }}
            >
              <AddIcon sx={{ fontSize: { xs: 24, sm: 28, md: 32 }, color: 'rgba(200,180,110,0.75)', transition: 'all 0.3s ease' }} />
            </Box>

            {/* 文字说明 */}
            <Box sx={{ textAlign: 'center', zIndex: 1 }}>
              <Typography
                className="add-text"
                sx={{
                  fontFamily: '"Noto Serif SC", "宋体", serif',
                  fontSize: { xs: '0.75rem', sm: '0.85rem', md: '0.95rem' },
                  color: 'rgba(200,180,120,0.7)',
                  fontWeight: 600,
                  letterSpacing: { xs: '2px', sm: '3px', md: '4px' },
                  mb: { xs: 0.5, sm: 0.8, md: 1 },
                  transition: 'all 0.3s ease',
                }}
              >
                新建项目
              </Typography>

              <Typography
                sx={{
                  fontFamily: '"STKaiti", "楷体", serif',
                  fontSize: '0.65rem',
                  color: 'rgba(160,140,100,0.55)',
                  letterSpacing: '2px',
                }}
              >
                开始创作你的小说
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
                borderTop: pos.bt ? '1px solid rgba(180,160,80,0.3)' : 'none',
                borderLeft: pos.bl ? '1px solid rgba(180,160,80,0.3)' : 'none',
                borderRight: pos.br ? '1px solid rgba(180,160,80,0.3)' : 'none',
                borderBottom: pos.bb ? '1px solid rgba(180,160,80,0.3)' : 'none',
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
            background: 'linear-gradient(to right, #e8dcc8 0%, #d4c8a8 60%, #c4b890 100%)',
            borderRadius: '0 2px 2px 0',
            zIndex: 1,
            '&::before': {
              content: '""',
              position: 'absolute',
              top: 0, bottom: 0, left: 0, width: '100%',
              background: 'repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, rgba(0,0,0,0.06) 2px, rgba(0,0,0,0.06) 3px)',
            },
          }} />
        </Box>
      </Grid>
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
              <MenuItem value="奇幻">奇幻</MenuItem>
              <MenuItem value="都市">都市</MenuItem>
              <MenuItem value="言情">言情</MenuItem>
              <MenuItem value="耽美">耽美</MenuItem>
              <MenuItem value="悬疑">悬疑</MenuItem>
              <MenuItem value="科幻">科幻</MenuItem>
              <MenuItem value="纯文学">纯文学</MenuItem>
              <MenuItem value="Fantasy">奇幻（英）</MenuItem>
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
