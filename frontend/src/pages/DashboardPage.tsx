import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Grid,
  Card,
  CardContent,
  CardActions,
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
  ToggleButtonGroup,
  ToggleButton,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import MenuIcon from '@mui/icons-material/Menu'
import DeleteIcon from '@mui/icons-material/Delete'
import SchemaIcon from '@mui/icons-material/Schema'
import LibraryBooksIcon from '@mui/icons-material/LibraryBooks'
import EditIcon from '@mui/icons-material/Edit'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import NavigateNextIcon from '@mui/icons-material/NavigateNext'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import ScienceIcon from '@mui/icons-material/Science'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import Badge from '@mui/material/Badge'
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
  const [chapterSortOrder, setChapterSortOrder] = useState<'asc' | 'desc'>('asc')

  // 章节删除状态
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [chapterToDelete, setChapterToDelete] = useState<any>(null)
  const [deletingChapter, setDeletingChapter] = useState(false)

  // 🆕 知识库统计状态
  const [knowledgeStats, setKnowledgeStats] = useState<Record<number, number>>({})
  const [statsLoading, setStatsLoading] = useState(false)

  // 🆕 标题编辑状态
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editedTitle, setEditedTitle] = useState('')

  // 🆕 类型编辑状态
  const [editingGenreProjectId, setEditingGenreProjectId] = useState<number | null>(null)
  const [editedGenre, setEditedGenre] = useState('')

  // 🆕 生成下一章状态
  const [generatingNextChapter, setGeneratingNextChapter] = useState<Record<number, boolean>>({})

  // 🆕 Snackbar 状态（用于显示成功/错误提示）
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'info'>('success')

  // 🆕 章节字数统计（每个项目的总字数）
  const [chapterWordCounts, setChapterWordCounts] = useState<Record<number, number>>({})

  // 🆕 AI 检测状态
  const [aiDetectDialogOpen, setAiDetectDialogOpen] = useState(false)
  const [aiDetecting, setAiDetecting] = useState(false)
  const [aiDetectResult, setAiDetectResult] = useState<{
    success: boolean;
    ai_score: number | null;
    label: string | null;
    error: string | null;
    text_length: number | null;
  } | null>(null)
  const [selectedChapterForDetect, setSelectedChapterForDetect] = useState<any>(null)

  // 🆕 类型映射函数（英文 → 中文）
  const getGenreLabel = (genre: string | null | undefined): string => {
    const genreMap: Record<string, string> = {
      'Fantasy': '奇幻',
      'Science Fiction': '科幻',
      'Romance': '浪漫',
      'Mystery': '悬疑',
      'Thriller': '惊悚',
      'Other': '其他'
    }
    return genreMap[genre || ''] || genre || '未设置'
  }

  useEffect(() => {
    dispatch(fetchProjects())
  }, [dispatch])

  // 🆕 加载知识库统计数据
  useEffect(() => {
    if (projects.length === 0) return

    const loadKnowledgeStats = async () => {
      setStatsLoading(true)
      const stats: Record<number, number> = {}

      try {
        // 并发请求所有项目的知识库数据
        const promises = projects.map(async (project) => {
          try {
            const response = await fetch(`/api/v1/projects/${project.id}/knowledge-base`, {
              headers: {
                'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
              },
            })

            if (response.ok) {
              const data = await response.json()
              const total =
                (data.world_settings?.length || 0) +
                (data.characters?.length || 0) +
                (data.plot_outline?.length || 0)
              stats[project.id] = total
              logger.log(`✅ 项目 ${project.id} 知识库统计: ${total}`)
            } else {
              stats[project.id] = 0
            }
          } catch (error) {
            logger.error(`❌ 获取项目 ${project.id} 知识库失败:`, error)
            stats[project.id] = 0
          }
        })

        await Promise.all(promises)
        setKnowledgeStats(stats)
        logger.log('✅ 知识库统计加载完成:', stats)
      } catch (error) {
        logger.error('❌ 加载知识库统计失败:', error)
      } finally {
        setStatsLoading(false)
      }
    }

    loadKnowledgeStats()
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

        // 直接跳转到工作流程页面
        navigate(`/workflow/${newProjectId}`)

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

  const loadChapters = async (projectId: number) => {
    setChaptersLoading(true)
    try {
      const response = await apiClient.getChapters(projectId, chapterSortOrder)
      if (response.data) {
        // 后端直接返回章节数组，按章节编号排序
        const chaptersList = Array.isArray(response.data) ? response.data : []
        const sortedChapters = chaptersList.sort((a: any, b: any) =>
          chapterSortOrder === 'asc'
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
    // 重新加载章节列表
    if (selectedProjectId) {
      await loadChapters(selectedProjectId)
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

        // 跳转到工作流页面（不再需要传递 URL 参数，因为状态已在 Redux 中）
        navigate(`/workflow/${projectId}`)
      } else {
        const errorData = await response.json()
        logger.error('❌ 创建生成任务失败:', errorData)

        setSnackbarMessage(errorData.detail || errorData.error || '创建生成任务失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      logger.error('❌ 生成下一章异常:', error)

      setSnackbarMessage('创建生成任务失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setGeneratingNextChapter(prev => ({ ...prev, [projectId]: false }))
    }
  }

  // 🆕 AI 检测功能
  const handleAiDetectClick = (chapter: any, e: React.MouseEvent) => {
    e.stopPropagation()
    setSelectedChapterForDetect(chapter)
    setAiDetectResult(null)
    setAiDetectDialogOpen(true)
  }

  const handleAiDetect = async () => {
    if (!selectedChapterForDetect) return

    setAiDetecting(true)
    setAiDetectResult(null)

    try {
      const response = await fetch('/api/v1/ai-detect', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          chapter_id: selectedChapterForDetect.id
        })
      })

      const result = await response.json()
      setAiDetectResult(result)

      if (result.success) {
        logger.log(`✅ AI 检测完成: 置信度 ${result.ai_score}%`)
      } else {
        logger.error('❌ AI 检测失败:', result.error)
      }
    } catch (error) {
      logger.error('❌ AI 检测异常:', error)
      setAiDetectResult({
        success: false,
        ai_score: null,
        label: null,
        error: '检测请求失败，请检查网络连接',
        text_length: null
      })
    } finally {
      setAiDetecting(false)
    }
  }

  const handleCloseAiDetectDialog = () => {
    setAiDetectDialogOpen(false)
    setSelectedChapterForDetect(null)
    setAiDetectResult(null)
  }

  return (
    <Box sx={{ minHeight: '100vh', backgroundColor: '#f5f7fa' }}>
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
                    我的项目
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ color: 'rgba(255,255,255,0.8)', fontSize: '0.85rem' }}
                  >
                    管理您的小说创作项目
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
        {projects.map((project) => (
          <Grid item xs={12} sm={6} md={4} key={project.id}>
            <Card
              sx={{
                height: '280px',
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                opacity: generatingProjectId === project.id ? 0.7 : 1,
              }}
            >
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
                    backgroundColor: 'rgba(255, 255, 255, 0.8)',
                    zIndex: 10,
                    borderRadius: 1,
                  }}
                >
                  <Box sx={{ textAlign: 'center' }}>
                    <CircularProgress size={40} sx={{ mb: 1 }} />
                    <Typography variant="caption">生成中...</Typography>
                  </Box>
                </Box>
              )}

              <CardContent sx={{ flexGrow: 1, overflow: 'hidden' }}>
                {/* 🆕 可编辑标题 */}
                {editingProjectId === project.id ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                    <TextField
                      size="small"
                      value={editedTitle}
                      onChange={(e) => setEditedTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleSaveTitle(project.id)
                        } else if (e.key === 'Escape') {
                          handleCancelEditTitle()
                        }
                      }}
                      autoFocus
                      fullWidth
                      sx={{ flex: 1 }}
                    />
                    <IconButton 
                      size="small" 
                      color="primary"
                      onClick={() => handleSaveTitle(project.id)}
                      title="保存"
                    >
                      <CheckIcon fontSize="small" />
                    </IconButton>
                    <IconButton 
                      size="small" 
                      color="default"
                      onClick={handleCancelEditTitle}
                      title="取消"
                    >
                      <CloseIcon fontSize="small" />
                    </IconButton>
                  </Box>
                ) : (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                    <Typography 
                      variant="h6" 
                      sx={{ 
                        flex: 1,
                        overflow: 'hidden', 
                        textOverflow: 'ellipsis', 
                        whiteSpace: 'nowrap',
                        cursor: 'pointer',
                        '&:hover': {
                          color: 'primary.main',
                        }
                      }}
                      onClick={() => handleStartEditTitle(project.id, project.title)}
                      title="点击编辑标题"
                    >
                      {project.title}
                    </Typography>
                    <IconButton 
                      size="small" 
                      onClick={() => handleStartEditTitle(project.id, project.title)}
                      title="编辑标题"
                      sx={{ 
                        opacity: 0.6,
                        '&:hover': { opacity: 1 }
                      }}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Box>
                )}
                <Typography 
                  variant="body2" 
                  color="textSecondary" 
                  sx={{ 
                    mb: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    minHeight: '40px'
                  }}
                >
                  {project.description}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
                  {/* 类型编辑区域 */}
                  {editingGenreProjectId === project.id ? (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <FormControl size="small" sx={{ minWidth: 120 }}>
                        <Select
                          value={editedGenre}
                          onChange={(e) => setEditedGenre(e.target.value)}
                          sx={{ fontSize: '0.75rem', height: '28px' }}
                        >
                          <MenuItem value="Fantasy">奇幻</MenuItem>
                          <MenuItem value="Science Fiction">科幻</MenuItem>
                          <MenuItem value="Romance">浪漫</MenuItem>
                          <MenuItem value="Mystery">悬疑</MenuItem>
                          <MenuItem value="Thriller">惊悚</MenuItem>
                          <MenuItem value="Other">其他</MenuItem>
                        </Select>
                      </FormControl>
                      <IconButton 
                        size="small" 
                        color="primary"
                        onClick={() => handleSaveGenre(project.id)}
                        title="保存"
                      >
                        <CheckIcon fontSize="small" />
                      </IconButton>
                      <IconButton 
                        size="small" 
                        color="default"
                        onClick={handleCancelEditGenre}
                        title="取消"
                      >
                        <CloseIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <Typography variant="caption" color="textSecondary">
                        类型: {getGenreLabel(project.genre)}
                      </Typography>
                      <IconButton 
                        size="small" 
                        onClick={() => handleStartEditGenre(project.id, project.genre || '')}
                        title="编辑类型"
                        sx={{ 
                          opacity: 0.6,
                          padding: '2px',
                          '&:hover': { opacity: 1 }
                        }}
                      >
                        <EditIcon sx={{ fontSize: '0.9rem' }} />
                      </IconButton>
                    </Box>
                  )}
                  <Typography variant="caption" color="textSecondary">
                    字数: {chapterWordCounts[project.id] || 0}
                  </Typography>
                </Box>
              </CardContent>

              <CardActions sx={{ pt: 0, flexWrap: 'wrap', gap: 0.5 }}>
                <Button
                  size="small"
                  startIcon={<SchemaIcon />}
                  onClick={() => navigate(`/workflow/${project.id}`)}
                  disabled={generatingProjectId === project.id || generatingNextChapter[project.id]}
                  color="success"
                >
                  工作流
                </Button>
                <Button
                  size="small"
                  startIcon={<MenuIcon />}
                  onClick={() => handleOpenChaptersDrawer(project.id)}
                  disabled={generatingProjectId === project.id || generatingNextChapter[project.id]}
                >
                  章节列表
                </Button>
                <Button
                  size="small"
                  startIcon={<LibraryBooksIcon />}
                  onClick={() => navigate(`/knowledge-base/${project.id}`)}
                  disabled={generatingProjectId === project.id || generatingNextChapter[project.id]}
                  color="info"
                  endIcon={
                    statsLoading ? (
                      <CircularProgress size={16} />
                    ) : (
                      <Badge
                        badgeContent={knowledgeStats[project.id] || 0}
                        color="primary"
                        max={999}
                        sx={{
                          '& .MuiBadge-badge': {
                            fontSize: '0.65rem',
                            height: '18px',
                            minWidth: '18px',
                            padding: '0 4px',
                          },
                        }}
                      >
                        <span />
                      </Badge>
                    )
                  }
                >
                  知识库
                </Button>
                {/* 🆕 生成下一章按钮（与迭代优化阶段完全相同） */}
                <Button
                  size="small"
                  startIcon={generatingNextChapter[project.id] ? <CircularProgress size={20} /> : <NavigateNextIcon />}
                  onClick={() => handleGenerateNextChapter(project.id)}
                  disabled={generatingProjectId === project.id || generatingNextChapter[project.id]}
                  color="secondary"
                >
                  {generatingNextChapter[project.id] ? '生成中...' : '生成下一章'}
                </Button>
                <Button
                  size="small"
                  startIcon={<DeleteIcon />}
                  color="error"
                  onClick={() => handleDeleteProject(project.id)}
                  disabled={generatingProjectId === project.id || generatingNextChapter[project.id]}
                >
                  删除
                </Button>
              </CardActions>
            </Card>
          </Grid>
        ))}
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
              <MenuItem value="Fantasy">奇幻</MenuItem>
              <MenuItem value="Science Fiction">科幻</MenuItem>
              <MenuItem value="Romance">浪漫</MenuItem>
              <MenuItem value="Mystery">悬疑</MenuItem>
              <MenuItem value="Thriller">惊悚</MenuItem>
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
          <Typography variant="h6">📚 章节列表</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="body2" sx={{ mr: 1 }}>排序:</Typography>
            <ToggleButtonGroup
              size="small"
              value={chapterSortOrder}
              exclusive
              onChange={(_, newOrder) => {
                if (newOrder !== null) {
                  handleChapterSortOrderChange(newOrder)
                }
              }}
              aria-label="章节排序"
              sx={{ mr: 1 }}
            >
              <ToggleButton value="asc" aria-label="正序">
                <ArrowUpwardIcon fontSize="small" />
              </ToggleButton>
              <ToggleButton value="desc" aria-label="倒序">
                <ArrowDownwardIcon fontSize="small" />
              </ToggleButton>
            </ToggleButtonGroup>
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
                    <IconButton
                      edge="end"
                      aria-label="ai-detect"
                      size="small"
                      color="primary"
                      onClick={(e) => handleAiDetectClick(chapter, e)}
                      title="AI 检测"
                      sx={{
                        '&:hover': {
                          backgroundColor: '#e3f2fd'
                        }
                      }}
                    >
                      <SmartToyIcon fontSize="small" />
                    </IconButton>
                    <IconButton
                      edge="end"
                      aria-label="delete"
                      size="small"
                      color="error"
                      onClick={(e) => handleDeleteChapterClick(chapter, e)}
                      sx={{
                        '&:hover': {
                          backgroundColor: '#ffebee'
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
                    primary={`${chapter.title}`}
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
            color="error" 
            variant="contained"
            disabled={deletingChapter}
            startIcon={deletingChapter ? <CircularProgress size={16} /> : <DeleteIcon />}
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

      {/* 🆕 AI 检测对话框 */}
      <Dialog
        open={aiDetectDialogOpen}
        onClose={handleCloseAiDetectDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <SmartToyIcon color="primary" />
          AI 生成检测
        </DialogTitle>
        <DialogContent>
          {selectedChapterForDetect && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="body2" color="textSecondary">
                检测章节：<strong>{selectedChapterForDetect.title}</strong>
              </Typography>
              <Typography variant="caption" color="textSecondary">
                字数：{selectedChapterForDetect.word_count || 0} 字
              </Typography>
            </Box>
          )}

          {!aiDetectResult && !aiDetecting && (
            <DialogContentText>
              点击"开始检测"按钮，调用腾讯云 AI 生成检测 API 分析该章节内容的 AI 生成率。
            </DialogContentText>
          )}

          {aiDetecting && (
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 4 }}>
              <CircularProgress size={60} />
              <Typography variant="body2" color="textSecondary" sx={{ mt: 2 }}>
                正在检测中，请稍候...
              </Typography>
            </Box>
          )}

          {aiDetectResult && (
            <Box sx={{ mt: 2 }}>
              {aiDetectResult.success ? (
                <Box>
                  <Box sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    p: 3,
                    borderRadius: 2,
                    backgroundColor: aiDetectResult.ai_score && aiDetectResult.ai_score > 70
                      ? '#ffebee'
                      : aiDetectResult.ai_score && aiDetectResult.ai_score > 30
                        ? '#fff8e1'
                        : '#e8f5e9'
                  }}>
                    <Typography variant="h2" sx={{
                      fontWeight: 'bold',
                      color: aiDetectResult.ai_score && aiDetectResult.ai_score > 70
                        ? '#d32f2f'
                        : aiDetectResult.ai_score && aiDetectResult.ai_score > 30
                          ? '#f57c00'
                          : '#388e3c'
                    }}>
                      {aiDetectResult.ai_score || 0}%
                    </Typography>
                    <Typography variant="body1" color="textSecondary">
                      AI 生成置信度
                    </Typography>
                  </Box>
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2">
                      <strong>检测标签：</strong>{aiDetectResult.label || '无'}
                    </Typography>
                    <Typography variant="body2">
                      <strong>检测文本长度：</strong>{aiDetectResult.text_length || 0} 字符
                    </Typography>
                  </Box>
                  <Alert
                    severity={
                      aiDetectResult.ai_score && aiDetectResult.ai_score > 70
                        ? 'error'
                        : aiDetectResult.ai_score && aiDetectResult.ai_score > 30
                          ? 'warning'
                          : 'success'
                    }
                    sx={{ mt: 2 }}
                  >
                    {aiDetectResult.ai_score && aiDetectResult.ai_score > 70
                      ? '该内容很可能是 AI 生成的，建议进行人工修改以降低 AI 痕迹。'
                      : aiDetectResult.ai_score && aiDetectResult.ai_score > 30
                        ? '该内容可能包含部分 AI 生成痕迹，可考虑适当修改。'
                        : '该内容 AI 生成痕迹较低，质量良好！'}
                  </Alert>
                </Box>
              ) : (
                <Alert severity="error">
                  <strong>检测失败：</strong>{aiDetectResult.error}
                </Alert>
              )}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseAiDetectDialog}>
            关闭
          </Button>
          <Button
            variant="contained"
            onClick={handleAiDetect}
            disabled={aiDetecting}
            startIcon={aiDetecting ? <CircularProgress size={16} /> : <SmartToyIcon />}
          >
            {aiDetecting ? '检测中...' : aiDetectResult ? '重新检测' : '开始检测'}
          </Button>
        </DialogActions>
      </Dialog>
      </Container>
    </Box>
  )
}

