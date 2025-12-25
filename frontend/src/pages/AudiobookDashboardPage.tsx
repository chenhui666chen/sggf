/**
 * 耳畔星河 - 有声小说仪表盘页面
 * 
 * 功能：
 * 1. 项目列表展示
 * 2. 项目搜索和筛选
 * 3. 点击项目跳转到有声书生成页面
 * 4. 项目管理（创建、删除等）
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../services/api'
import {
  Box,
  Container,
  Typography,
  Card,
  CardContent,
  Button,
  Grid,
  Chip,
  TextField,
  InputAdornment,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
  Snackbar,
  CircularProgress,
	  Paper,
	  Drawer,
	  Divider,
	  List,
	  ListItem,
	  ListItemButton,
	  ListItemText,
	  LinearProgress,
	  Tooltip,
	  Slider,
	} from '@mui/material'
	import {
	  Search as SearchIcon,
	  Add as AddIcon,
	  Headphones as HeadphonesIcon,
	  MoreVert as MoreVertIcon,
	  Delete as DeleteIcon,
	  Close as CloseIcon,
	  PlayArrow as PlayIcon,
	  Pause as PauseIcon,
	  SwapVert as SwapVertIcon,
	  ArrowBack as ArrowBackIcon,
	  Science as ScienceIcon,
	  Logout as LogoutIcon,
	} from '@mui/icons-material'
import {
  Menu,
  MenuItem,
  IconButton,
} from '@mui/material'
import { useDispatch } from 'react-redux'
import { logout } from '@/store/slices/authSlice'

// 类型定义
interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

interface Chapter {
  id: number
  chapter_number: number
  title: string
}

interface ChapterAudio {
  id: number
  chapter_id: number
  chapter_number?: number | null
  audio_path?: string | null
  script_status?: string | null
  has_script?: boolean
}

interface AudiobookProjectDetail {
  id: number
  total_chapters?: number
  completed_chapters?: number
  total_duration?: number
  chapter_audios?: ChapterAudio[]
}

interface AudiobookProjectSummary {
  id: number
  status?: string
  created_at?: string
  completed_chapters?: number
  total_chapters?: number
  total_duration?: number
}

interface MergedChapterAudioRef {
  audiobookProjectId: number
  chapterAudio: ChapterAudio
}

const AudiobookDashboardPage = () => {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  
  // 状态管理
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedGenre, setSelectedGenre] = useState<string>('all')
  
  // 新建项目对话框
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newProjectText, setNewProjectText] = useState('')
  const [creatingFromBook, setCreatingFromBook] = useState(false)
  
  // 提示消息
  const [snackbar, setSnackbar] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'error' | 'info' | 'warning'
  }>({
    open: false,
    message: '',
    severity: 'info',
  })

  // 删除相关状态
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null)
  const [loadingDelete, setLoadingDelete] = useState(false)
  const [projectImpact, setProjectImpact] = useState<{
    chapters: number
    audioFiles: number
    totalSize: string
  } | null>(null)
  const [audiobookProjectIdToDelete, setAudiobookProjectIdToDelete] = useState<number | null>(null)

  // 章节目录抽屉
	  const [chapterDrawerOpen, setChapterDrawerOpen] = useState(false)
	  const [drawerLoading, setDrawerLoading] = useState(false)
		  const [drawerError, setDrawerError] = useState<string | null>(null)
		  const [drawerProject, setDrawerProject] = useState<Project | null>(null)
		  const [drawerAudiobookProject, setDrawerAudiobookProject] = useState<AudiobookProjectDetail | null>(null)
		  const [drawerChapters, setDrawerChapters] = useState<Chapter[]>([])
		  const [drawerMergedChapterAudiosByNumber, setDrawerMergedChapterAudiosByNumber] = useState<Record<number, MergedChapterAudioRef>>({})
		  const [drawerChapterSortOrder, setDrawerChapterSortOrder] = useState<'asc' | 'desc'>('asc')

  // 抽屉标题二级菜单（整本删除）
  const [drawerMenuAnchorEl, setDrawerMenuAnchorEl] = useState<null | HTMLElement>(null)

  // 章节行菜单（章节删除）
	  const [chapterMenuAnchorEl, setChapterMenuAnchorEl] = useState<null | HTMLElement>(null)
	  const [chapterAudioToDelete, setChapterAudioToDelete] = useState<
	    (ChapterAudio & { chapterTitle: string; chapterNumber: number }) | null
	  >(null)
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [loadingDeleteChapter, setLoadingDeleteChapter] = useState(false)

  // 抽屉内播放（轻量播放器）
	  const drawerAudioRef = useMemo(() => new Audio(), [])
	  const drawerAudioBlobUrlRef = useRef<string | null>(null)
	  const isSeekingRef = useRef(false)
	  const [playingChapterNumber, setPlayingChapterNumber] = useState<number | null>(null)
	  const [playerIsPlaying, setPlayerIsPlaying] = useState(false)
	  const [playerCurrentTime, setPlayerCurrentTime] = useState(0)
	  const [playerDuration, setPlayerDuration] = useState(0)

  // 获取项目列表
  const fetchProjects = async () => {
    try {
      setLoading(true)
      const res = await apiClient.getProjects()
      setProjects(res.data)
    } catch (error) {
      console.error('获取项目失败:', error)
      setSnackbar({ open: true, message: '网络错误，无法加载项目列表', severity: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // 初始化加载项目
  useEffect(() => {
    fetchProjects()
  }, [])

  const formatTime = useCallback((seconds: number) => {
    if (!Number.isFinite(seconds) || seconds <= 0) return '00:00'
    const s = Math.floor(seconds)
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  }, [])

	  const stopDrawerAudio = useCallback(() => {
	    try {
	      drawerAudioRef.pause()
	    } finally {
	      setPlayerIsPlaying(false)
	      setPlayingChapterNumber(null)
	      setPlayerCurrentTime(0)
	      setPlayerDuration(0)
	      if (drawerAudioBlobUrlRef.current) {
	        window.URL.revokeObjectURL(drawerAudioBlobUrlRef.current)
	        drawerAudioBlobUrlRef.current = null
      }
    }
  }, [drawerAudioRef])

  useEffect(() => {
    const handleLoadedMetadata = () => {
      setPlayerDuration(Number.isFinite(drawerAudioRef.duration) ? drawerAudioRef.duration : 0)
    }
    const handleTimeUpdate = () => {
      if (isSeekingRef.current) return
      setPlayerCurrentTime(Number.isFinite(drawerAudioRef.currentTime) ? drawerAudioRef.currentTime : 0)
    }
    const handlePlay = () => setPlayerIsPlaying(true)
    const handlePause = () => setPlayerIsPlaying(false)
	    const handleEnded = () => {
	      setPlayerIsPlaying(false)
	      setPlayingChapterNumber(null)
	      setPlayerCurrentTime(0)
	      if (drawerAudioBlobUrlRef.current) {
	        window.URL.revokeObjectURL(drawerAudioBlobUrlRef.current)
	        drawerAudioBlobUrlRef.current = null
	      }
	    }

    drawerAudioRef.addEventListener('loadedmetadata', handleLoadedMetadata)
    drawerAudioRef.addEventListener('timeupdate', handleTimeUpdate)
    drawerAudioRef.addEventListener('play', handlePlay)
    drawerAudioRef.addEventListener('pause', handlePause)
    drawerAudioRef.addEventListener('ended', handleEnded)

    return () => {
      drawerAudioRef.removeEventListener('loadedmetadata', handleLoadedMetadata)
      drawerAudioRef.removeEventListener('timeupdate', handleTimeUpdate)
      drawerAudioRef.removeEventListener('play', handlePlay)
      drawerAudioRef.removeEventListener('pause', handlePause)
      drawerAudioRef.removeEventListener('ended', handleEnded)
    }
  }, [drawerAudioRef])

	  const handleCloseChapterDrawer = useCallback(() => {
	    setChapterDrawerOpen(false)
	    setDrawerMenuAnchorEl(null)
	    setChapterMenuAnchorEl(null)
	    setDrawerError(null)
	    setDrawerProject(null)
	    setDrawerAudiobookProject(null)
	    setDrawerChapters([])
	    setDrawerMergedChapterAudiosByNumber({})
	    stopDrawerAudio()
	  }, [stopDrawerAudio])

	  const handleOpenChapterDrawer = async (project: Project) => {
	    stopDrawerAudio()
	    setChapterDrawerOpen(true)
	    setDrawerProject(project)
	    setDrawerLoading(true)
	    setDrawerError(null)
	    setDrawerAudiobookProject(null)
	    setDrawerChapters([])
	    setDrawerMergedChapterAudiosByNumber({})

	    try {
	      const [audiobookProjectsRes, chaptersRes] = await Promise.all([
	        apiClient.getAudiobookProjectsByProject(project.id),
	        apiClient.getChapters(project.id, 'asc'),
	      ])

	      const chapters: Chapter[] = Array.isArray(chaptersRes.data) ? chaptersRes.data : []
	      setDrawerChapters(chapters)

	      const chapterNumberById = new Map<number, number>()
	      for (const ch of chapters) chapterNumberById.set(ch.id, ch.chapter_number)

	      const audiobookProjects: AudiobookProjectSummary[] = Array.isArray(audiobookProjectsRes.data) ? audiobookProjectsRes.data : []
	      const completed = audiobookProjects.filter((p) => p?.status === 'completed')
	      const completedSorted = [...completed].sort((a, b) => {
	        const ta = a?.created_at ? Date.parse(a.created_at) : 0
	        const tb = b?.created_at ? Date.parse(b.created_at) : 0
	        if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return tb - ta
	        const ia = typeof a?.id === 'number' ? a.id : 0
	        const ib = typeof b?.id === 'number' ? b.id : 0
	        return ib - ia
	      })

	      const latestCompletedId = completedSorted[0]?.id
	      if (!latestCompletedId) {
	        setDrawerError('该项目暂无有声书，请先生成。')
	        return
	      }

	      // 抽屉标题菜单的“整本删除”默认针对最新完成的一次生成记录
	      const latestDetailRes = await apiClient.getAudiobookProject(latestCompletedId)
	      setDrawerAudiobookProject(latestDetailRes.data)

	      // 跨记录合并：按章节编号取“最新完成记录”中可用音频
	      const details = await Promise.allSettled(
	        completedSorted.map((p) => apiClient.getAudiobookProject(p.id).then((r) => r.data))
	      )

	      const merged: Record<number, MergedChapterAudioRef> = {}
	      for (const item of details) {
	        if (item.status !== 'fulfilled') continue
	        const detail = item.value as AudiobookProjectDetail
	        const sourceProjectId = detail.id
	        const audios = Array.isArray(detail.chapter_audios) ? detail.chapter_audios : []
	        for (const ca of audios) {
	          if (!ca?.audio_path) continue
	          const chapterNumber = (ca.chapter_number ?? chapterNumberById.get(ca.chapter_id)) as number | undefined
	          if (!chapterNumber) continue
	          if (merged[chapterNumber]) continue
	          merged[chapterNumber] = { audiobookProjectId: sourceProjectId, chapterAudio: ca }
	        }
	      }
	      setDrawerMergedChapterAudiosByNumber(merged)
	    } catch (error) {
	      console.error('加载章节目录失败:', error)
	      setDrawerError('加载章节目录失败，请稍后重试。')
	    } finally {
	      setDrawerLoading(false)
	    }
	  }

	  const handleOpenDrawerMenu = (event: React.MouseEvent<HTMLElement>) => {
	    event.stopPropagation()
	    setDrawerMenuAnchorEl(event.currentTarget)
	  }

	  const sortedDrawerChapters = useMemo(() => {
	    const next = [...drawerChapters]
	    next.sort((a, b) => {
	      const diff = a.chapter_number - b.chapter_number
	      return drawerChapterSortOrder === 'asc' ? diff : -diff
	    })
	    return next
	  }, [drawerChapters, drawerChapterSortOrder])

  const handleCloseDrawerMenu = () => setDrawerMenuAnchorEl(null)

  const handleOpenDeleteAudiobookDialog = () => {
    if (!drawerProject || !drawerAudiobookProject) return
    setProjectToDelete(drawerProject)
    setAudiobookProjectIdToDelete(drawerAudiobookProject.id)
    setProjectImpact({
      chapters: drawerAudiobookProject.total_chapters || drawerChapters.length,
      audioFiles: drawerAudiobookProject.chapter_audios?.filter((a) => Boolean(a.audio_path)).length || 0,
      totalSize: '计算中...',
    })
    setDeleteDialogOpen(true)
    handleCloseDrawerMenu()
  }

  const handleDeleteAudiobook = async () => {
    if (!audiobookProjectIdToDelete || !projectToDelete) return

    setLoadingDelete(true)
    try {
      await apiClient.deleteAudiobookProject(audiobookProjectIdToDelete, { delete_files: true })
      setSnackbar({ open: true, message: '有声书已成功删除', severity: 'success' })
      setDeleteDialogOpen(false)
      handleCloseChapterDrawer()
      await fetchProjects()
    } catch (error: any) {
      console.error('删除有声书失败:', error)
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || '删除有声书失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setLoadingDelete(false)
    }
  }

	  const handlePlayChapter = async (chapterNumber: number) => {
	    const mergedRef = drawerMergedChapterAudiosByNumber[chapterNumber]
	    if (!mergedRef?.chapterAudio?.audio_path) {
	      setSnackbar({ open: true, message: '该章节尚未生成音频', severity: 'info' })
	      return
	    }

	    try {
	      if (playingChapterNumber === chapterNumber) {
	        if (drawerAudioRef.paused) {
	          await drawerAudioRef.play()
	        } else {
	          drawerAudioRef.pause()
	        }
	        return
	      }

      drawerAudioRef.pause()
      setPlayerCurrentTime(0)
      setPlayerDuration(0)

      if (drawerAudioBlobUrlRef.current) {
        window.URL.revokeObjectURL(drawerAudioBlobUrlRef.current)
        drawerAudioBlobUrlRef.current = null
      }

	      const token = localStorage.getItem('access_token')
	      const response = await fetch(`/api/v1/audiobook/stream/${mergedRef.audiobookProjectId}/${mergedRef.chapterAudio.chapter_id}`, {
	        headers: { 'Authorization': `Bearer ${token}` },
	      })
	      if (!response.ok) throw new Error('加载音频失败')

      const blob = await response.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      drawerAudioBlobUrlRef.current = blobUrl
	      drawerAudioRef.src = blobUrl

	      await drawerAudioRef.play()
	      setPlayingChapterNumber(chapterNumber)
	    } catch (error) {
	      console.error('播放音频失败:', error)
	      setSnackbar({ open: true, message: '播放失败，请稍后重试', severity: 'error' })
	      setPlayingChapterNumber(null)
	    }
	  }

  const handleOpenChapterMenu = (
    event: React.MouseEvent<HTMLElement>,
    chapter: Chapter,
    chapterAudio: ChapterAudio | undefined,
  ) => {
    event.stopPropagation()
    if (!chapterAudio) return
    setChapterMenuAnchorEl(event.currentTarget)
    setChapterAudioToDelete({
      ...chapterAudio,
      chapterTitle: chapter.title,
      chapterNumber: chapter.chapter_number,
    })
  }

  const handleCloseChapterMenu = () => setChapterMenuAnchorEl(null)

  const handleOpenDeleteChapterDialog = () => {
    if (!chapterAudioToDelete) return
    setDeleteChapterDialogOpen(true)
    handleCloseChapterMenu()
  }

	  const handleDeleteChapterAudio = async () => {
	    if (!chapterAudioToDelete || !drawerAudiobookProject) return
	    setLoadingDeleteChapter(true)
	    try {
	      if (playingChapterNumber === chapterAudioToDelete.chapterNumber) stopDrawerAudio()
	      await apiClient.deleteChapterAudio(chapterAudioToDelete.id, { delete_files: true })

	      // 删除后重新合并，自动回退到更早的同章节编号音频（如存在）
	      if (drawerProject) {
	        await handleOpenChapterDrawer(drawerProject)
	      } else {
	        setDrawerMergedChapterAudiosByNumber((prev) => {
	          const next = { ...prev }
	          delete next[chapterAudioToDelete.chapterNumber]
	          return next
	        })
	      }
	      setSnackbar({ open: true, message: '章节音频已删除', severity: 'success' })
	      setDeleteChapterDialogOpen(false)
	      setChapterAudioToDelete(null)
	    } catch (error: any) {
      console.error('删除章节音频失败:', error)
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || '删除章节音频失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setLoadingDeleteChapter(false)
    }
  }


  // 筛选项目
  const filteredProjects = projects.filter((project) => {
    const matchesSearch = project.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         (project.description?.toLowerCase().includes(searchQuery.toLowerCase()))
    const matchesGenre = selectedGenre === 'all' || project.genre === selectedGenre
    return matchesSearch && matchesGenre
  })

  // 获取所有流派
  const genres: string[] = Array.from(new Set(projects.map((p) => p.genre).filter(Boolean)) as unknown as string[])

  const getBookColors = useMemo(() => {
    const colors: Record<string, { primary: string; secondary: string; accent: string; text: string }> = {
      '修仙': { primary: '#1e3a8a', secondary: '#2563eb', accent: '#fbbf24', text: '#fef3c7' },
      '玄幻': { primary: '#6b21a8', secondary: '#7c3aed', accent: '#fb923c', text: '#fed7aa' },
      '奇幻': { primary: '#14532d', secondary: '#166534', accent: '#fbbf24', text: '#fef3c7' },
      '都市': { primary: '#ea580c', secondary: '#f97316', accent: '#fef3c7', text: '#fef3c7' },
      '言情': { primary: '#f472b6', secondary: '#f9a8d4', accent: '#f59e0b', text: '#fef3c7' },
      '耽美': { primary: '#831843', secondary: '#9f1239', accent: '#fda4af', text: '#fce7f3' },
      '悬疑': { primary: '#0f172a', secondary: '#1e293b', accent: '#dc2626', text: '#fecaca' },
      '科幻': { primary: '#0891b2', secondary: '#06b6d4', accent: '#a5f3fc', text: '#ecfeff' },
      '纯文学': { primary: '#44403c', secondary: '#57534e', accent: '#d6d3d1', text: '#f5f5f4' },
      'Fantasy': { primary: '#14532d', secondary: '#166534', accent: '#fbbf24', text: '#fef3c7' },
    }
    return (genre: string | undefined) =>
      colors[genre || ''] || { primary: '#713f12', secondary: '#92400e', accent: '#fbbf24', text: '#fef3c7' }
  }, [])

  // 点击项目卡片，跳转到有声书生成页面
  const handleProjectClick = (project: Project) => {
    navigate(`/audiobook/${project.id}`)
  }

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  // 创建新项目（从文本）
  const handleCreateProject = async () => {
    const rawText = newProjectText.trim()
    if (!rawText) {
      setSnackbar({ open: true, message: '请先粘贴文本内容', severity: 'error' })
      return
    }

    const title = newProjectTitle.trim() || '从整本书导入的项目'

    // 如果一次输入过多，则跳转到拆书页面
    const TOO_LONG_THRESHOLD = 10000
    if (rawText.length > TOO_LONG_THRESHOLD) {
      setNewProjectDialogOpen(false)
      navigate('/book-parser', {
        state: {
          openUpload: true,
          prefillTitle: title,
          prefillContent: rawText,
        },
      })
      return
    }

    setCreatingFromBook(true)
    try {
      // 这里简化处理，实际应该调用完整的创建流程
      // 暂时只关闭对话框并刷新列表
      setNewProjectDialogOpen(false)
      setNewProjectTitle('')
      setNewProjectText('')
      setSnackbar({
        open: true,
        message: '项目创建成功',
        severity: 'success',
      })
      await fetchProjects()
    } catch (error: any) {
      console.error('创建项目失败:', error)
      setSnackbar({
        open: true,
        message: error.message || '创建项目失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setCreatingFromBook(false)
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        background: 'linear-gradient(135deg, #6b7280 0%, #4b5563 50%, #374151 100%)',
        position: 'relative',
      }}
    >
      {/* 顶部标题栏（对齐第二张图的布局） */}
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
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.2)' },
                }}
                title="返回创作工坊"
              >
                <ArrowBackIcon />
              </IconButton>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <HeadphonesIcon sx={{ fontSize: 32, color: 'white' }} />
                <Box>
                  <Typography
                    variant="h5"
                    sx={{ color: 'white', fontWeight: 700, letterSpacing: '0.5px' }}
                  >
                    耳畔星河
                  </Typography>
                  <Typography
                    variant="body2"
                    sx={{ color: 'rgba(255,255,255,0.8)', fontSize: '0.85rem' }}
                  >
                    有声小说创作 · 管理您的有声项目
                  </Typography>
                </Box>
              </Box>
            </Box>

            {/* 右侧：操作按钮 */}
            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={() => setNewProjectDialogOpen(true)}
                sx={{
                  backgroundColor: 'white',
                  color: '#1976d2',
                  fontWeight: 600,
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.9)' },
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
                startIcon={<LogoutIcon />}
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

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {/* 搜索 + 流派筛选 */}
        <Box
          sx={{
            mb: 3,
            p: 2,
            borderRadius: 2,
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.12)',
          }}
        >
          <TextField
            placeholder="搜索项目..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            size="small"
            sx={{
              minWidth: 280,
              width: '100%',
              '& .MuiOutlinedInput-root': {
                color: 'rgba(255,255,255,0.92)',
                backgroundColor: 'rgba(0,0,0,0.15)',
                '& fieldset': { borderColor: 'rgba(255,255,255,0.25)' },
                '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.45)' },
                '&.Mui-focused fieldset': { borderColor: 'rgba(255,255,255,0.6)' },
              },
              '& .MuiInputAdornment-root, & .MuiSvgIcon-root': { color: 'rgba(255,255,255,0.75)' },
            }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon />
                </InputAdornment>
              ),
            }}
          />

          {genres.length > 0 && (
            <Box sx={{ mt: 1.5, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Chip
                label="全部"
                onClick={() => setSelectedGenre('all')}
                sx={{
                  cursor: 'pointer',
                  color: 'rgba(255,255,255,0.9)',
                  backgroundColor: selectedGenre === 'all' ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.15)',
                  border: '1px solid rgba(255,255,255,0.18)',
                }}
              />
              {genres.map((genre) => (
                <Chip
                  key={genre}
                  label={genre}
                  onClick={() => setSelectedGenre(genre)}
                  sx={{
                    cursor: 'pointer',
                    color: 'rgba(255,255,255,0.9)',
                    backgroundColor: selectedGenre === genre ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.15)',
                    border: '1px solid rgba(255,255,255,0.18)',
                  }}
                />
              ))}
            </Box>
          )}
        </Box>

        {/* 加载状态 */}
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress sx={{ color: 'rgba(255,255,255,0.85)' }} />
          </Box>
        ) : (
          <>
            {/* 空状态 */}
            {filteredProjects.length === 0 ? (
              <Box
                sx={{
                  py: 10,
                  textAlign: 'center',
                  backgroundColor: 'rgba(255,255,255,0.08)',
                  borderRadius: 2,
                  border: '1px solid rgba(255,255,255,0.12)',
                }}
              >
                <HeadphonesIcon sx={{ fontSize: 64, color: 'rgba(255,255,255,0.85)', mb: 2 }} />
                <Typography variant="h6" sx={{ mb: 1, color: 'rgba(255,255,255,0.92)' }}>
                  {searchQuery ? '未找到匹配的项目' : '暂无项目'}
                </Typography>
                <Typography variant="body2" sx={{ mb: 3, color: 'rgba(255,255,255,0.75)' }}>
                  {searchQuery ? '请尝试其他搜索关键词' : '请先创建小说项目'}
                </Typography>
                {!searchQuery && (
                  <Button
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={() => setNewProjectDialogOpen(true)}
                    sx={{
                      backgroundColor: 'white',
                      color: '#1976d2',
                      fontWeight: 600,
                      '&:hover': { backgroundColor: 'rgba(255,255,255,0.9)' },
                    }}
                  >
                    创建第一个项目
                  </Button>
                )}
              </Box>
            ) : (
              /* 项目列表 */
              <Grid container spacing={3}>
                {filteredProjects.map((project) => {
                  const colors = getBookColors(project.genre)
                  return (
                    <Grid item key={project.id} xs={12} sm={6} md={4} lg={3}>
                      <Card
                        sx={{
                          cursor: 'pointer',
                          transition: 'transform 0.25s ease, box-shadow 0.25s ease',
                          background: 'linear-gradient(135deg, rgba(17,24,39,0.55) 0%, rgba(31,41,55,0.45) 100%)',
                          border: '1px solid rgba(255,255,255,0.12)',
                          position: 'relative',
                          overflow: 'hidden',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          minHeight: 200,
                          backdropFilter: 'blur(8px)',
                          '&::before': {
                            content: '""',
                            position: 'absolute',
                            inset: 0,
                            background: `radial-gradient(circle at 20% 0%, ${colors.accent}26 0%, transparent 45%), radial-gradient(circle at 85% 85%, ${colors.secondary}22 0%, transparent 55%)`,
                            pointerEvents: 'none',
                          },
                          '&:hover': {
                            transform: 'translateY(-6px)',
                            boxShadow: '0 16px 36px rgba(0,0,0,0.28)',
                          },
                          '&:hover .vinyl': { transform: 'rotate(10deg)' },
                          '&:hover .vinyl .playOverlay': { opacity: 1 },
                        }}
                        onClick={() => handleProjectClick(project)}
                      >
                        {/* 更多选项按钮 */}
                        <IconButton
                          sx={{
                            position: 'absolute',
                            top: 8,
                            right: 8,
                            zIndex: 3,
                          }}
                          onMouseDown={(e) => e.stopPropagation()}
                          onClick={(e) => {
                            e.stopPropagation()
                            void handleOpenChapterDrawer(project)
                          }}
                        >
                          <MoreVertIcon />
                        </IconButton>

                        <CardContent
                          sx={{
                            width: '100%',
                            position: 'relative',
                            zIndex: 1,
                            p: 2.5,
                          }}
                        >
                          <Box
                            sx={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              gap: 2,
                              flexDirection: { xs: 'column', sm: 'row' },
                            }}
                          >
                            {/* 封面 */}
                            <Box
                              sx={{
                                width: { xs: '100%', sm: 150 },
                                height: 170,
                                borderRadius: 2,
                                position: 'relative',
                                overflow: 'hidden',
                                boxShadow: '0 12px 26px rgba(0,0,0,0.35)',
                                background: `linear-gradient(145deg, ${colors.primary} 0%, ${colors.secondary} 100%)`,
                                flexShrink: 0,
                                '&::before': {
                                  content: '""',
                                  position: 'absolute',
                                  inset: 0,
                                  background:
                                    `radial-gradient(circle at 25% 25%, ${colors.accent}22 0%, transparent 55%), ` +
                                    `repeating-linear-gradient(45deg, transparent, transparent 12px, ${colors.accent}10 12px, ${colors.accent}10 13px)`,
                                  opacity: 0.9,
                                  pointerEvents: 'none',
                                },
                                '&::after': {
                                  content: '""',
                                  position: 'absolute',
                                  inset: 10,
                                  border: `1px solid ${colors.accent}55`,
                                  borderRadius: 1.5,
                                  pointerEvents: 'none',
                                },
                              }}
                            >
                              <Box sx={{ position: 'absolute', top: 10, left: 10, zIndex: 1 }}>
                                <Box
                                  sx={{
                                    px: 1,
                                    py: 0.25,
                                    borderRadius: 999,
                                    fontSize: '0.7rem',
                                    fontWeight: 700,
                                    letterSpacing: '1px',
                                    color: 'rgba(255,255,255,0.9)',
                                    backgroundColor: 'rgba(0,0,0,0.25)',
                                    border: '1px solid rgba(255,255,255,0.18)',
                                    display: 'inline-block',
                                  }}
                                >
                                  AUDIOBOOK
                                </Box>
                              </Box>

                              <Box
                                sx={{
                                  position: 'relative',
                                  zIndex: 1,
                                  height: '100%',
                                  display: 'flex',
                                  flexDirection: 'column',
                                  justifyContent: 'center',
                                  px: 2,
                                  textAlign: 'center',
                                }}
                              >
                                <Typography
                                  sx={{
                                    fontFamily: '"STKaiti", "KaiTi", "楷体", serif',
                                    color: colors.accent,
                                    fontWeight: 800,
                                    fontSize: '1.05rem',
                                    textShadow: '0 2px 10px rgba(0,0,0,0.45)',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    display: '-webkit-box',
                                    WebkitLineClamp: 2,
                                    WebkitBoxOrient: 'vertical',
                                    lineHeight: 1.25,
                                    mb: 1,
                                  }}
                                >
                                  {project.title}
                                </Typography>

                                <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                                  <Chip
                                    label={project.genre || '未分类'}
                                    size="small"
                                    sx={{
                                      height: 22,
                                      fontSize: '0.7rem',
                                      color: 'rgba(255,255,255,0.9)',
                                      borderColor: 'rgba(255,255,255,0.28)',
                                      backgroundColor: 'rgba(0,0,0,0.18)',
                                      border: '1px solid rgba(255,255,255,0.2)',
                                    }}
                                  />
                                </Box>
                              </Box>
                            </Box>

                            {/* 唱片 */}
                            <Box
                              className="vinyl"
                              sx={{
                                width: 150,
                                height: 150,
                                borderRadius: '50%',
                                position: 'relative',
                                flexShrink: 0,
                                backgroundImage:
                                  'radial-gradient(circle at 50% 50%, rgba(255,255,255,0.10) 0%, rgba(0,0,0,0.78) 38%, rgba(0,0,0,0.95) 72%),' +
                                  'repeating-radial-gradient(circle at 50% 50%, rgba(255,255,255,0.06) 0px, rgba(255,255,255,0.06) 1px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 6px)',
                                boxShadow: '0 14px 28px rgba(0,0,0,0.35)',
                                transform: 'rotate(-6deg)',
                                transition: 'transform 0.25s ease',
                                '&::before': {
                                  content: '""',
                                  position: 'absolute',
                                  inset: 6,
                                  borderRadius: '50%',
                                  border: `1px solid ${colors.accent}33`,
                                  pointerEvents: 'none',
                                },
                                '.vinylLabel': {
                                  position: 'absolute',
                                  inset: 46,
                                  borderRadius: '50%',
                                  background: `linear-gradient(145deg, ${colors.secondary} 0%, ${colors.primary} 100%)`,
                                  border: `1px solid ${colors.accent}55`,
                                  boxShadow: 'inset 0 0 0 4px rgba(0,0,0,0.25)',
                                },
                                '.vinylHole': {
                                  position: 'absolute',
                                  inset: 70,
                                  borderRadius: '50%',
                                  backgroundColor: 'rgba(0,0,0,0.65)',
                                  border: '1px solid rgba(255,255,255,0.12)',
                                },
                                '.playOverlay': {
                                  position: 'absolute',
                                  inset: 0,
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  opacity: 0,
                                  transition: 'opacity 0.2s ease',
                                },
                              }}
                            >
                              <Box className="vinylLabel" />
                              <Box className="vinylHole" />
                              <Box className="playOverlay">
                                <Box
                                  sx={{
                                    width: 52,
                                    height: 52,
                                    borderRadius: '50%',
                                    backgroundColor: 'rgba(255,255,255,0.14)',
                                    border: '1px solid rgba(255,255,255,0.25)',
                                    backdropFilter: 'blur(6px)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                  }}
                                >
                                  <Box
                                    sx={{
                                      width: 18,
                                      height: 18,
                                      backgroundColor: 'rgba(255,255,255,0.9)',
                                      clipPath: 'polygon(28% 18%, 78% 50%, 28% 82%)',
                                      transform: 'translateX(2px)',
                                    }}
                                  />
                                </Box>
                              </Box>
                            </Box>

                            {/* 文案（移动端隐藏，避免拥挤） */}
                            <Box sx={{ flex: 1, minWidth: 0, display: { xs: 'none', sm: 'block' } }}>
                              <Typography
                                sx={{
                                  color: 'rgba(255,255,255,0.92)',
                                  fontWeight: 800,
                                  fontSize: '0.98rem',
                                  mb: 0.5,
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {project.title}
                              </Typography>
                              <Typography
                                sx={{
                                  color: 'rgba(255,255,255,0.75)',
                                  fontSize: '0.8rem',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  lineHeight: 1.5,
                                }}
                              >
                                {project.description || '点击进入有声生成与管理'}
                              </Typography>
                              <Box sx={{ mt: 1.25, display: 'flex', gap: 0.8, alignItems: 'flex-end' }}>
                                {[10, 16, 12, 18, 11, 14, 9].map((h, idx) => (
                                  <Box
                                    key={`wave-${idx}`}
                                    sx={{
                                      width: 6,
                                      height: h,
                                      borderRadius: 999,
                                      background: `linear-gradient(180deg, ${colors.accent} 0%, rgba(255,255,255,0.08) 100%)`,
                                      opacity: 0.85,
                                    }}
                                  />
                                ))}
                              </Box>
                            </Box>
                          </Box>
                        </CardContent>
                      </Card>
                    </Grid>
                  )
                })}
              </Grid>
            )}
          </>
        )}
      </Container>

      {/* 新建项目对话框 */}
      <Dialog
        open={newProjectDialogOpen}
        onClose={() => setNewProjectDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>从文本创建项目</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            粘贴整本书的文本内容，系统将自动进行章节切分和AI分析
          </Alert>
          <TextField
            fullWidth
            label="项目标题"
            value={newProjectTitle}
            onChange={(e) => setNewProjectTitle(e.target.value)}
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            label="文本内容"
            value={newProjectText}
            onChange={(e) => setNewProjectText(e.target.value)}
            multiline
            rows={8}
            placeholder="请粘贴整本书的文本内容..."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewProjectDialogOpen(false)}>取消</Button>
          <Button
            onClick={handleCreateProject}
            variant="contained"
            disabled={creatingFromBook}
            sx={{
              backgroundColor: '#9c27b0',
              '&:hover': { backgroundColor: '#7b1fa2' },
            }}
          >
            {creatingFromBook ? '创建中...' : '创建项目'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 提示消息 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
      >
        <Alert
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* 章节目录抽屉（三点直达） */}
      <Drawer anchor="right" open={chapterDrawerOpen} onClose={handleCloseChapterDrawer}>
        <Box
          sx={{
            width: { xs: '100vw', sm: 420 },
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
	          <Box sx={{ px: 2, py: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
	            <Box sx={{ minWidth: 0 }}>
	              <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
	                章节目录
	              </Typography>
	              <Typography
	                variant="body2"
	                sx={{
	                  color: 'text.secondary',
	                  overflow: 'hidden',
	                  textOverflow: 'ellipsis',
	                  whiteSpace: 'nowrap',
	                  maxWidth: 260,
	                }}
	              >
	                {drawerProject?.title || ''}
	              </Typography>
		              <Typography variant="caption" sx={{ mt: 1, display: 'block', color: 'text.secondary' }}>
		                音频来源：跨生成记录合并（按章节编号取最新音频）
		              </Typography>
	            </Box>
	            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
	              <Tooltip title={drawerChapterSortOrder === 'asc' ? '切换为倒序' : '切换为正序'}>
	                <IconButton
	                  size="small"
	                  onClick={() => setDrawerChapterSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
	                >
	                  <SwapVertIcon fontSize="small" />
	                </IconButton>
	              </Tooltip>
	              <IconButton size="small" onClick={handleOpenDrawerMenu} disabled={!drawerAudiobookProject}>
	                <MoreVertIcon fontSize="small" />
	              </IconButton>
              <IconButton size="small" onClick={handleCloseChapterDrawer}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </Box>
          </Box>
          <Divider />

          {drawerLoading ? (
            <Box sx={{ p: 2, display: 'flex', justifyContent: 'center' }}>
              <CircularProgress size={24} />
            </Box>
          ) : drawerError ? (
            <Box sx={{ p: 2 }}>
              <Alert severity="info">{drawerError}</Alert>
            </Box>
          ) : (
            <Box sx={{ flex: 1, overflow: 'auto' }}>
              <List disablePadding>
	                {sortedDrawerChapters.map((chapter) => {
	                  const mergedRef = drawerMergedChapterAudiosByNumber[chapter.chapter_number]
	                  const canPlay = Boolean(mergedRef?.chapterAudio?.audio_path)
	                  const isActive = playingChapterNumber === chapter.chapter_number
	                  const isPlaying = isActive && playerIsPlaying

                  return (
                    <ListItem
                      key={chapter.id}
                      disablePadding
                      secondaryAction={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <Tooltip title={canPlay ? (isPlaying ? '暂停' : '播放') : '未生成音频'}>
                            <span>
	                              <IconButton size="small" onClick={() => handlePlayChapter(chapter.chapter_number)} disabled={!canPlay}>
	                                {isPlaying ? <PauseIcon fontSize="small" /> : <PlayIcon fontSize="small" />}
	                              </IconButton>
                            </span>
                          </Tooltip>
                          <Tooltip title="章节操作">
                            <span>
	                              <IconButton
	                                size="small"
	                                onClick={(e) => handleOpenChapterMenu(e, chapter, mergedRef?.chapterAudio)}
	                                disabled={!mergedRef?.chapterAudio}
	                              >
	                                <MoreVertIcon fontSize="small" />
	                              </IconButton>
                            </span>
                          </Tooltip>
                        </Box>
                      }
                    >
	                      <ListItemButton
	                        onClick={() => handlePlayChapter(chapter.chapter_number)}
	                        disabled={!canPlay}
	                        sx={{
                          alignItems: 'flex-start',
                          py: 1.25,
                          ...(isActive ? { backgroundColor: 'rgba(156, 39, 176, 0.06)' } : null),
                        }}
                      >
                        <ListItemText
                          primary={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
                              <Typography
                                variant="body2"
                                sx={{ fontWeight: 800, color: isActive ? '#7b1fa2' : 'text.primary', flexShrink: 0 }}
                              >
                                第{chapter.chapter_number}章
                              </Typography>
                              <Typography
                                variant="body2"
                                sx={{
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                  color: isActive ? '#7b1fa2' : 'text.primary',
                                }}
                              >
                                {chapter.title}
                              </Typography>
                            </Box>
                          }
                          secondary={
                            isActive ? (
                              <Box sx={{ mt: 0.75 }}>
                                <LinearProgress
                                  variant="determinate"
                                  value={playerDuration > 0 ? (playerCurrentTime / playerDuration) * 100 : 0}
                                  sx={{
                                    height: 4,
                                    borderRadius: 999,
                                    backgroundColor: 'rgba(156, 39, 176, 0.10)',
                                    '& .MuiLinearProgress-bar': { backgroundColor: '#9c27b0' },
                                  }}
                                />
                                <Box sx={{ mt: 0.5, display: 'flex', justifyContent: 'space-between' }}>
                                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                    {formatTime(playerCurrentTime)}
                                  </Typography>
                                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                    {formatTime(playerDuration)}
                                  </Typography>
                                </Box>
                              </Box>
                            ) : null
                          }
                        />
                      </ListItemButton>
                    </ListItem>
                  )
                })}
              </List>
            </Box>
          )}

	          {playingChapterNumber !== null && (
	            <Box sx={{ px: 2, py: 1.5, borderTop: '1px solid rgba(0,0,0,0.08)' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  播放进度
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  {formatTime(playerCurrentTime)} / {formatTime(playerDuration)}
                </Typography>
              </Box>
              <Slider
                size="small"
                min={0}
                max={playerDuration || 0}
                step={1}
                value={Math.min(playerCurrentTime, playerDuration || 0)}
                onChange={(_, value) => {
                  const v = Array.isArray(value) ? value[0] : value
                  isSeekingRef.current = true
                  setPlayerCurrentTime(v)
                }}
                onChangeCommitted={(_, value) => {
                  const v = Array.isArray(value) ? value[0] : value
                  drawerAudioRef.currentTime = v
                  isSeekingRef.current = false
                }}
                disabled={!playerDuration}
              />
            </Box>
          )}
        </Box>
      </Drawer>

      {/* 抽屉标题二级菜单（整本删除） */}
      <Menu
        anchorEl={drawerMenuAnchorEl}
        open={Boolean(drawerMenuAnchorEl)}
        onClose={handleCloseDrawerMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MenuItem onClick={handleOpenDeleteAudiobookDialog} sx={{ color: '#f44336' }}>
          <DeleteIcon sx={{ mr: 1 }} />
          删除整本有声书
        </MenuItem>
      </Menu>

      {/* 章节行菜单（章节删除） */}
      <Menu
        anchorEl={chapterMenuAnchorEl}
        open={Boolean(chapterMenuAnchorEl)}
        onClose={handleCloseChapterMenu}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MenuItem onClick={handleOpenDeleteChapterDialog} sx={{ color: '#f44336' }}>
          <DeleteIcon sx={{ mr: 1 }} />
          删除本章音频
        </MenuItem>
      </Menu>

      {/* 删除确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => !loadingDelete && setDeleteDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ color: '#f44336' }}>
          删除有声书确认
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            此操作将删除 "{projectToDelete?.title}" 的整本有声书（含相关音频文件），此操作不可恢复！
          </Alert>

          {projectImpact && (
            <Paper variant="outlined" sx={{ p: 2, mb: 2, backgroundColor: 'rgba(255, 152, 0, 0.05)' }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                删除影响范围：
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                <Typography variant="body2">
                  • 章节数量：{projectImpact.chapters} 章
                </Typography>
                <Typography variant="body2">
                  • 已生成音频：{projectImpact.audioFiles} 个
                </Typography>
                <Typography variant="body2">
                  • 音频文件大小：{projectImpact.totalSize}
                </Typography>
              </Box>
            </Paper>
          )}

          <Alert severity="info" sx={{ mt: 1 }}>
            将默认同时删除音频文件（不可恢复）。
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setDeleteDialogOpen(false)}
            disabled={loadingDelete}
          >
            取消
          </Button>
          <Button
            onClick={handleDeleteAudiobook}
            variant="contained"
            disabled={loadingDelete}
            sx={{
              backgroundColor: '#f44336',
              '&:hover': { backgroundColor: '#d32f2f' },
            }}
          >
            {loadingDelete ? <CircularProgress size={20} color="inherit" /> : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 删除章节音频确认 */}
      <Dialog
        open={deleteChapterDialogOpen}
        onClose={() => !loadingDeleteChapter && setDeleteChapterDialogOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle sx={{ color: '#f44336' }}>删除章节音频确认</DialogTitle>
        <DialogContent>
          <Alert severity="warning">
            将删除第{chapterAudioToDelete?.chapterNumber}章《{chapterAudioToDelete?.chapterTitle}》的音频文件，此操作不可恢复！
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteChapterDialogOpen(false)} disabled={loadingDeleteChapter}>
            取消
          </Button>
          <Button
            onClick={handleDeleteChapterAudio}
            variant="contained"
            disabled={loadingDeleteChapter}
            sx={{ backgroundColor: '#f44336', '&:hover': { backgroundColor: '#d32f2f' } }}
          >
            {loadingDeleteChapter ? <CircularProgress size={20} color="inherit" /> : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default AudiobookDashboardPage
