import { useEffect, useMemo, useRef, useState } from 'react'
import type { MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { logout } from '@/store/slices/authSlice'
import { apiClient } from '@/services/api'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
  InputAdornment,
  Menu,
  MenuItem,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import MoreHorizIcon from '@mui/icons-material/MoreHoriz'
import MovieIcon from '@mui/icons-material/Movie'
import PhotoLibraryIcon from '@mui/icons-material/PhotoLibrary'
import SearchIcon from '@mui/icons-material/Search'
import LogoutIcon from '@mui/icons-material/Logout'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import AddIcon from '@mui/icons-material/Add'
import BookParserUploadDialog from '@/components/BookParserUploadDialog'
import type { BookSource } from '@/services/bookParserApi'

interface Project {
  id: number
  title?: string
  description?: string
  genre?: string
  status?: string
  word_count?: number
  created_at?: string
  updated_at?: string | null
}

const perforationHoles = Array.from({ length: 8 })
const untitledTitleFallback = '未命名项目'
const legacyUntitledTitles = new Set(['new novel', 'untitled', 'untitled project'])
const keyboardFocusRingSx = {
  '&:focus-visible': {
    outline: '2px solid rgba(191,219,254,0.95)',
    outlineOffset: 2,
  },
}

const getDisplayTitle = (title?: string) => {
  const normalized = (title || '').trim()
  if (!normalized) return untitledTitleFallback
  if (legacyUntitledTitles.has(normalized.toLowerCase())) return untitledTitleFallback
  return normalized
}

const isUntitledProject = (title?: string) => getDisplayTitle(title) === untitledTitleFallback

function FilmPerforationColumn() {
  return (
    <Box
      aria-hidden
      sx={{
        width: 18,
        backgroundColor: 'rgba(0,0,0,0.28)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-around',
        alignItems: 'center',
        py: 1,
      }}
    >
      {perforationHoles.map((_, idx) => (
        <Box
          key={idx}
          sx={{
            width: 10,
            height: 10,
            borderRadius: 1,
            backgroundColor: 'rgba(255,255,255,0.16)',
          }}
        />
      ))}
    </Box>
  )
}

export default function DreamWeaverPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedGenre, setSelectedGenre] = useState<string>('all')
  const [actionAlert, setActionAlert] = useState<{ severity: 'success' | 'error'; message: string } | null>(null)
  const [purgeDialogOpen, setPurgeDialogOpen] = useState(false)
  const [purgeTarget, setPurgeTarget] = useState<Project | null>(null)
  const [purgeSubmitting, setPurgeSubmitting] = useState(false)
  const [purgeDialogError, setPurgeDialogError] = useState<string | null>(null)
  const [actionMenuAnchor, setActionMenuAnchor] = useState<null | HTMLElement>(null)
  const [actionMenuProject, setActionMenuProject] = useState<Project | null>(null)
  const [editingProjectId, setEditingProjectId] = useState<number | null>(null)
  const [editedTitle, setEditedTitle] = useState('')
  const [renameSubmitting, setRenameSubmitting] = useState(false)
  const actionMenuId = 'dreamweaver-project-actions-menu'
  const searchTrackedRef = useRef(false)
  const [bookUploadDialogOpen, setBookUploadDialogOpen] = useState(false)

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        setLoading(true)
        const res = await apiClient.getProjects()
        setProjects((res.data as Project[]) || [])
      } catch (e: any) {
        setError(e?.message || '获取项目失败，请稍后重试')
      } finally {
        setLoading(false)
      }
    }
    fetchProjects()
  }, [])

  const genreOptions = useMemo(() => {
    const set = new Set<string>()
    projects.forEach((p) => {
      if (p.genre) set.add(p.genre)
    })
    return Array.from(set)
  }, [projects])

  const filteredProjects = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return projects.filter((p) => {
      if (selectedGenre !== 'all' && (p.genre || '') !== selectedGenre) return false
      if (!q) return true
      const hay = `${getDisplayTitle(p.title)}\n${p.description || ''}\n${p.genre || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [projects, searchQuery, selectedGenre])

  const sortedFilteredProjects = useMemo(() => {
    return [...filteredProjects].sort((a, b) => {
      const aTs = new Date(a.updated_at || a.created_at || 0).getTime()
      const bTs = new Date(b.updated_at || b.created_at || 0).getTime()
      return bTs - aTs
    })
  }, [filteredProjects])

  const trackDreamweaverEvent = (
    event: string,
    options?: {
      action?: string
      project?: Project
      source?: string
      durationMs?: number
      success?: boolean
      labels?: Record<string, string>
    }
  ) => {
    const labels: Record<string, string> = {
      page: 'dreamweaver',
      ...(options?.labels || {}),
    }

    if (options?.project) {
      labels.project_id = String(options.project.id)
      labels.genre = options.project.genre || 'unknown'
      labels.is_untitled = isUntitledProject(options.project.title) ? 'true' : 'false'
      labels.has_title = options.project.title?.trim() ? 'true' : 'false'
    }
    if (options?.source) labels.source = options.source

    void apiClient.trackFrontendEvent({
      event,
      module: 'dreamweaver',
      action: options?.action,
      labels,
      duration_ms: options?.durationMs,
      success: options?.success,
    }).catch(() => {
      // 埋点失败不影响页面主流程
    })
  }

  const handleSearchQueryChange = (nextValue: string) => {
    setSearchQuery(nextValue)
    const hasQuery = nextValue.trim().length > 0
    if (hasQuery && !searchTrackedRef.current) {
      searchTrackedRef.current = true
      trackDreamweaverEvent('project_search_used', {
        action: 'search',
        labels: { selected_genre: selectedGenre },
      })
    } else if (!hasQuery) {
      searchTrackedRef.current = false
    }
  }

  const handleGenreSelect = (genre: string) => {
    if (genre === selectedGenre) return
    setSelectedGenre(genre)
    trackDreamweaverEvent('project_filter_used', {
      action: 'filter_genre',
      labels: { genre: genre || 'all' },
    })
  }

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  const handleBookUploadSuccess = (book: BookSource) => {
    setActionAlert({
      severity: 'success',
      message: `书籍《${book.title}》已上传、完成拆书分析并自动导入灵感方舟，可直接用于短剧生成`,
    })
  }

  const navigateToRunPage = (project: Project, source: 'card' | 'primary_button') => {
    trackDreamweaverEvent(source === 'card' ? 'project_card_click' : 'project_primary_action_click', {
      action: 'open_run',
      source,
      project,
    })
    navigate(`/drama/${project.id}`)
  }

  const navigateToLibraryPage = (project: Project, source: 'icon_button' | 'action_menu') => {
    trackDreamweaverEvent('project_library_open', {
      action: 'open_library',
      source,
      project,
    })
    navigate(`/drama/${project.id}/library`)
  }

  const openActionMenu = (event: MouseEvent<HTMLElement>, project: Project) => {
    event.preventDefault()
    event.stopPropagation()
    trackDreamweaverEvent('project_more_menu_open', {
      action: 'open_menu',
      source: 'card_action_menu',
      project,
    })
    setActionMenuAnchor(event.currentTarget)
    setActionMenuProject(project)
  }

  const closeActionMenu = () => {
    setActionMenuAnchor(null)
    setActionMenuProject(null)
  }

  const startRenameProject = (project: Project) => {
    trackDreamweaverEvent('project_rename_start', {
      action: 'rename',
      source: 'action_menu',
      project,
    })
    setEditingProjectId(project.id)
    setEditedTitle(isUntitledProject(project.title) ? '' : getDisplayTitle(project.title))
    closeActionMenu()
  }

  const cancelRenameProject = () => {
    if (renameSubmitting) return
    setEditingProjectId(null)
    setEditedTitle('')
  }

  const saveProjectTitle = async (projectId: number) => {
    const nextTitle = editedTitle.trim()
    if (!nextTitle) {
      setActionAlert({ severity: 'error', message: '项目名称不能为空' })
      return
    }

    const startedAt = performance.now()
    const currentProject = projects.find((p) => p.id === projectId) || null
    const renamedFromUntitled = currentProject ? isUntitledProject(currentProject.title) : false
    setRenameSubmitting(true)
    try {
      await apiClient.updateProject(projectId, { title: nextTitle })
      setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, title: nextTitle } : p)))
      setEditingProjectId(null)
      setEditedTitle('')
      setActionAlert({ severity: 'success', message: '项目名称已更新' })
      trackDreamweaverEvent('project_rename_save', {
        action: 'rename',
        source: 'inline_edit',
        project: currentProject || { id: projectId, title: nextTitle },
        success: true,
        durationMs: Math.round(performance.now() - startedAt),
      })
      if (renamedFromUntitled) {
        trackDreamweaverEvent('project_rename_from_untitled', {
          action: 'rename',
          source: 'inline_edit',
          project: currentProject || { id: projectId, title: nextTitle },
          success: true,
        })
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const msg =
        (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message) ||
        (typeof detail === 'string' && detail) ||
        e?.message ||
        '更新项目名称失败，请稍后重试'
      setActionAlert({ severity: 'error', message: msg })
      trackDreamweaverEvent('project_rename_save', {
        action: 'rename',
        source: 'inline_edit',
        project: currentProject || { id: projectId, title: nextTitle },
        success: false,
        durationMs: Math.round(performance.now() - startedAt),
      })
    } finally {
      setRenameSubmitting(false)
    }
  }

  const openPurgeDialog = (project: Project, source: 'action_menu') => {
    trackDreamweaverEvent('project_delete_click', {
      action: 'delete_generated_open_confirm',
      source,
      project,
    })
    setPurgeTarget(project)
    setPurgeDialogError(null)
    setPurgeDialogOpen(true)
    closeActionMenu()
  }

  const closePurgeDialog = () => {
    if (purgeSubmitting) return
    setPurgeDialogOpen(false)
    setPurgeTarget(null)
    setPurgeDialogError(null)
  }

  const confirmPurgeDialog = async () => {
    if (!purgeTarget) return
    const startedAt = performance.now()
    setPurgeSubmitting(true)
    setPurgeDialogError(null)
    try {
      const res = await apiClient.deleteDreamweaverProjectGenerated(purgeTarget.id)
      const deletedRuns = Array.isArray(res.data?.deleted_runs) ? res.data.deleted_runs.length : 0
      const skippedRuns = Array.isArray(res.data?.skipped_runs) ? res.data.skipped_runs.length : 0
      const librarySkipped = Boolean(res.data?.library_skipped)
      const deletedLibraryDir = Boolean(res.data?.deleted_library_dir)
      const deletedLibraryAssets = Number(res.data?.deleted_library_assets || 0)
      const failedPaths = Array.isArray(res.data?.failed_paths) ? res.data.failed_paths : []
      setActionAlert({
        severity: 'success',
        message: `清理完成：已删除 ${deletedRuns} 个 run；跳过 ${skippedRuns} 个；素材库${
          librarySkipped
            ? '未清理（存在运行中/排队任务）'
            : (deletedLibraryDir || deletedLibraryAssets > 0)
              ? '已清理'
              : '无可清理'
        }${failedPaths.length ? `；失败路径 ${failedPaths.length} 个` : ''}`,
      })
      trackDreamweaverEvent('project_delete_confirm', {
        action: 'delete_generated_confirm',
        source: 'dialog',
        project: purgeTarget,
        success: true,
        durationMs: Math.round(performance.now() - startedAt),
      })
      setPurgeDialogOpen(false)
      setPurgeTarget(null)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const msg =
        (detail && typeof detail === 'object' && typeof detail.message === 'string' && detail.message) ||
        (typeof detail === 'string' && detail) ||
        e?.message ||
        '清理失败，请稍后重试'
      setPurgeDialogError(msg)
      setActionAlert({ severity: 'error', message: msg })
      trackDreamweaverEvent('project_delete_confirm', {
        action: 'delete_generated_confirm',
        source: 'dialog',
        project: purgeTarget,
        success: false,
        durationMs: Math.round(performance.now() - startedAt),
      })
    } finally {
      setPurgeSubmitting(false)
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
      {/* 顶部标题栏（对齐灵感方舟 / 耳畔星河） */}
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
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <IconButton
                onClick={() => navigate('/home')}
                sx={{
                  color: 'white',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                  '&:hover': { backgroundColor: 'rgba(255,255,255,0.2)' },
                  ...keyboardFocusRingSx,
                }}
                title="返回创作工坊"
              >
                <ArrowBackIcon />
              </IconButton>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <MovieIcon sx={{ fontSize: 32, color: 'white' }} />
                <Box>
                  <Typography variant="h5" sx={{ color: 'white', fontWeight: 700, letterSpacing: '0.5px' }}>
                    织梦映心
                  </Typography>
                  <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.8)', fontSize: '0.85rem' }}>
                    短剧创作 · 选择项目进入生成流程
                  </Typography>
                </Box>
              </Box>
            </Box>

            <Box sx={{ display: 'flex', gap: 1.5 }}>
              <Button
                variant="outlined"
                startIcon={<LogoutIcon />}
                onClick={handleLogout}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': { borderColor: 'white', backgroundColor: 'rgba(255,255,255,0.1)' },
                  ...keyboardFocusRingSx,
                }}
              >
                退出登录
              </Button>
            </Box>
          </Box>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: 4 }}>
        {/* 搜索 + 题材筛选 */}
        <Box
          sx={{
            mb: 3,
            p: 1.5,
            borderRadius: 2,
            backgroundColor: 'rgba(255,255,255,0.08)',
            border: '1px solid rgba(255,255,255,0.12)',
          }}
        >
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
            <TextField
              placeholder="搜索项目..."
              inputProps={{ 'aria-label': '搜索项目' }}
              value={searchQuery}
              onChange={(e) => handleSearchQueryChange(e.target.value)}
              size="small"
              sx={{
                minWidth: { xs: '100%', sm: 260 },
                flex: 1,
                '& .MuiOutlinedInput-root': {
                  color: 'rgba(255,255,255,0.96)',
                  backgroundColor: 'rgba(0,0,0,0.18)',
                  '& fieldset': { borderColor: 'rgba(255,255,255,0.28)' },
                  '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.4)' },
                  '&.Mui-focused fieldset': { borderColor: 'rgba(255,255,255,0.58)' },
                },
                '& .MuiInputAdornment-root': { color: 'rgba(255,255,255,0.7)' },
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon />
                  </InputAdornment>
                ),
              }}
            />
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.82)', whiteSpace: 'nowrap' }}>
              共 {sortedFilteredProjects.length} / {projects.length} 个项目
            </Typography>
          </Box>

          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
            <Chip
              label="全部"
              clickable
              onClick={() => handleGenreSelect('all')}
              sx={{
                color: selectedGenre === 'all' ? '#111827' : 'rgba(255,255,255,0.9)',
                backgroundColor: selectedGenre === 'all' ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.18)',
                '&:hover': { backgroundColor: selectedGenre === 'all' ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.24)' },
                ...keyboardFocusRingSx,
              }}
            />
            {genreOptions.map((g) => (
              <Chip
                key={g}
                label={g}
                clickable
                onClick={() => handleGenreSelect(g)}
                sx={{
                  color: selectedGenre === g ? '#111827' : 'rgba(255,255,255,0.9)',
                  backgroundColor: selectedGenre === g ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.18)',
                  '&:hover': { backgroundColor: selectedGenre === g ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.24)' },
                  ...keyboardFocusRingSx,
                }}
              />
            ))}
          </Box>
        </Box>

        {actionAlert && (
          <Alert severity={actionAlert.severity} sx={{ mb: 2 }} onClose={() => setActionAlert(null)}>
            {actionAlert.message}
          </Alert>
        )}

        {error && (
          <Box sx={{ mb: 2 }}>
            <Typography color="error">{error}</Typography>
          </Box>
        )}

        {loading ? (
          <Box sx={{ py: 8, display: 'flex', justifyContent: 'center' }}>
            <CircularProgress />
          </Box>
        ) : (
          <Grid container spacing={3}>
            {sortedFilteredProjects.map((project) => {
              const displayTitle = getDisplayTitle(project.title)
              const isUntitled = isUntitledProject(project.title)
              const isEditing = editingProjectId === project.id
              const isDeletingCurrent = purgeSubmitting && purgeTarget?.id === project.id
              const isMenuActive = Boolean(actionMenuAnchor) && actionMenuProject?.id === project.id

              return (
                <Grid item xs={12} sm={6} md={4} lg={3} key={project.id}>
                  <Card
                    sx={{
                      width: '100%',
                      maxWidth: 360,
                      mx: 'auto',
                      height: '100%',
                      display: 'flex',
                      flexDirection: 'column',
                      borderRadius: 3,
                      overflow: 'hidden',
                      backgroundColor: 'rgba(0,0,0,0.2)',
                      border: '1px solid rgba(255,255,255,0.15)',
                      boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
                      transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                      '&:hover': {
                        transform: 'translateY(-4px)',
                        boxShadow: '0 14px 30px rgba(0,0,0,0.26)',
                        borderColor: 'rgba(255,255,255,0.25)',
                      },
                    }}
                  >
                    <CardActionArea
                      component="button"
                      aria-label={`进入项目「${displayTitle}」生成流程`}
                      title="进入生成流程"
                      onClick={() => navigateToRunPage(project, 'card')}
                      sx={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'stretch',
                        flex: 1,
                        aspectRatio: { xs: '16 / 10', sm: '6 / 5' },
                        minHeight: 240,
                        textAlign: 'left',
                        ...keyboardFocusRingSx,
                      }}
                    >
                      {/* 场记板顶条 */}
                      <Box
                        sx={{
                          height: 34,
                          background:
                            'repeating-linear-gradient(135deg, rgba(17,24,39,0.95) 0 12px, rgba(229,231,235,0.95) 12px 24px)',
                          borderBottom: '1px solid rgba(255,255,255,0.12)',
                        }}
                      />
                      {/* 胶片主体 */}
                      <Box
                        sx={{
                          display: 'flex',
                          flex: 1,
                          background: 'linear-gradient(135deg, rgba(17,24,39,0.9) 0%, rgba(55,65,81,0.9) 100%)',
                        }}
                      >
                        <FilmPerforationColumn />
                        <Box sx={{ flex: 1, minWidth: 0, px: 2, py: 1.75, display: 'flex', flexDirection: 'column' }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
                            <Chip
                              size="small"
                              label="DRAMA"
                              sx={{
                                height: 22,
                                fontWeight: 700,
                                letterSpacing: '0.6px',
                                color: 'rgba(255,255,255,0.92)',
                                backgroundColor: 'rgba(245,158,11,0.2)',
                                border: '1px solid rgba(245,158,11,0.4)',
                              }}
                            />
                            {project.genre && (
                              <Chip
                                size="small"
                                label={project.genre}
                                sx={{
                                  height: 22,
                                  color: 'rgba(255,255,255,0.9)',
                                  backgroundColor: 'rgba(255,255,255,0.14)',
                                  border: '1px solid rgba(255,255,255,0.2)',
                                }}
                              />
                            )}
                          </Box>

                          <Box sx={{ mt: 1, minHeight: 54 }}>
                            <Typography
                              variant="subtitle1"
                              sx={{
                                fontWeight: 700,
                                color: 'rgba(255,255,255,0.97)',
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                              }}
                            >
                              {displayTitle}
                            </Typography>
                            {isUntitled && !isEditing && (
                              <Chip
                                size="small"
                                label="待命名"
                                sx={{
                                  mt: 0.75,
                                  height: 20,
                                  color: '#fde68a',
                                  backgroundColor: 'rgba(120,53,15,0.42)',
                                  border: '1px solid rgba(251,191,36,0.4)',
                                }}
                              />
                            )}
                          </Box>

                          <Typography
                            variant="body2"
                            sx={{
                              mt: 0.5,
                              color: 'rgba(255,255,255,0.82)',
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                              minHeight: 42,
                            }}
                          >
                            {project.description || '从项目章节生成剧本、分镜与视频片段'}
                          </Typography>

                          {!isEditing && (
                            <Box
                              sx={{
                                mt: 'auto',
                                pt: 1.25,
                                display: 'flex',
                                alignItems: 'flex-end',
                                justifyContent: 'space-between',
                                gap: 1,
                              }}
                            >
                              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.74)', fontWeight: 600 }}>
                                点击进入生成流程
                              </Typography>
                              <Box sx={{ display: 'flex', gap: 0.75 }}>
                                <Tooltip title="进入素材库" placement="top" arrow>
                                  <IconButton
                                    size="small"
                                    onClick={(e) => {
                                      e.preventDefault()
                                      e.stopPropagation()
                                      navigateToLibraryPage(project, 'icon_button')
                                    }}
                                    sx={{
                                      width: 36,
                                      height: 36,
                                      borderRadius: '50%',
                                      backgroundColor: 'rgba(245,158,11,0.2)',
                                      border: '1px solid rgba(245,158,11,0.35)',
                                      color: 'rgba(255,255,255,0.95)',
                                      '&:hover': { backgroundColor: 'rgba(245,158,11,0.3)' },
                                      ...keyboardFocusRingSx,
                                    }}
                                    aria-label="进入素材库"
                                  >
                                    <PhotoLibraryIcon sx={{ fontSize: 20 }} />
                                  </IconButton>
                                </Tooltip>
                                <Tooltip title="更多操作" placement="top" arrow>
                                  <IconButton
                                    size="small"
                                    onClick={(e) => openActionMenu(e, project)}
                                    aria-label="更多操作"
                                    aria-haspopup="menu"
                                    aria-controls={isMenuActive ? actionMenuId : undefined}
                                    aria-expanded={isMenuActive ? 'true' : undefined}
                                    sx={{
                                      width: 36,
                                      height: 36,
                                      borderRadius: '50%',
                                      backgroundColor: 'rgba(255,255,255,0.12)',
                                      border: '1px solid rgba(255,255,255,0.22)',
                                      color: 'rgba(255,255,255,0.95)',
                                      '&:hover': { backgroundColor: 'rgba(255,255,255,0.2)' },
                                      ...keyboardFocusRingSx,
                                    }}
                                  >
                                    <MoreHorizIcon sx={{ fontSize: 20 }} />
                                  </IconButton>
                                </Tooltip>
                              </Box>
                            </Box>
                          )}
                        </Box>
                        <FilmPerforationColumn />
                      </Box>
                    </CardActionArea>

                    {isEditing ? (
                      <Box
                        sx={{
                          px: 1.25,
                          py: 1,
                          backgroundColor: 'rgba(17,24,39,0.8)',
                          borderTop: '1px solid rgba(255,255,255,0.12)',
                        }}
                      >
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                          <TextField
                            size="small"
                            autoFocus
                            fullWidth
                            value={editedTitle}
                            disabled={renameSubmitting}
                            inputProps={{ 'aria-label': '项目名称' }}
                            placeholder="请输入项目名称"
                            onChange={(e) => setEditedTitle(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveProjectTitle(project.id)
                              if (e.key === 'Escape') cancelRenameProject()
                            }}
                            sx={{
                              '& .MuiOutlinedInput-root': {
                                color: 'rgba(255,255,255,0.95)',
                                backgroundColor: 'rgba(255,255,255,0.06)',
                                '& fieldset': { borderColor: 'rgba(255,255,255,0.25)' },
                                '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.4)' },
                                '&.Mui-focused fieldset': { borderColor: 'rgba(255,255,255,0.55)' },
                              },
                            }}
                          />
                          <IconButton
                            size="small"
                            disabled={renameSubmitting}
                            onClick={() => saveProjectTitle(project.id)}
                            aria-label="保存项目名称"
                            sx={{
                              width: 30,
                              height: 30,
                              color: 'rgba(34,197,94,0.95)',
                              backgroundColor: 'rgba(34,197,94,0.16)',
                              '&:hover': { backgroundColor: 'rgba(34,197,94,0.24)' },
                              ...keyboardFocusRingSx,
                            }}
                          >
                            {renameSubmitting ? <CircularProgress size={16} color="inherit" /> : <CheckIcon sx={{ fontSize: 18 }} />}
                          </IconButton>
                          <IconButton
                            size="small"
                            disabled={renameSubmitting}
                            onClick={cancelRenameProject}
                            aria-label="取消重命名"
                            sx={{
                              width: 30,
                              height: 30,
                              color: 'rgba(255,255,255,0.9)',
                              backgroundColor: 'rgba(255,255,255,0.1)',
                              '&:hover': { backgroundColor: 'rgba(255,255,255,0.18)' },
                              ...keyboardFocusRingSx,
                            }}
                          >
                            <CloseIcon sx={{ fontSize: 18 }} />
                          </IconButton>
                        </Box>
                      </Box>
                    ) : null}

                    {isDeletingCurrent && (
                      <Box
                        sx={{
                          px: 1.5,
                          py: 0.75,
                          borderTop: '1px solid rgba(255,255,255,0.1)',
                          backgroundColor: 'rgba(127,29,29,0.35)',
                        }}
                      >
                        <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.92)' }}>
                          正在清理该项目的生成内容...
                        </Typography>
                      </Box>
                    )}
                  </Card>
                </Grid>
              )
            })}

            {/* 新建项目卡片入口 - 放在已有项目之后 */}
            <Grid item xs={12} sm={6} md={4} lg={3}>
              <Card
                sx={{
                  width: '100%',
                  maxWidth: 360,
                  mx: 'auto',
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  borderRadius: 3,
                  overflow: 'hidden',
                  backgroundColor: 'rgba(0,0,0,0.2)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
                  transition: 'transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease',
                  cursor: 'pointer',
                  '&:hover': {
                    transform: 'translateY(-4px)',
                    boxShadow: '0 14px 30px rgba(0,0,0,0.26)',
                    borderColor: 'rgba(255,255,255,0.25)',
                  },
                }}
                onClick={() => setBookUploadDialogOpen(true)}
              >
                <Box
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'stretch',
                    flex: 1,
                    aspectRatio: { xs: '16 / 10', sm: '6 / 5' },
                    minHeight: 240,
                  }}
                >
                  {/* 场记板顶条 */}
                  <Box
                    sx={{
                      height: 34,
                      background:
                        'repeating-linear-gradient(135deg, rgba(17,24,39,0.95) 0 12px, rgba(229,231,235,0.95) 12px 24px)',
                      borderBottom: '1px solid rgba(255,255,255,0.12)',
                    }}
                  />
                  
                  {/* 胶片主体 */}
                  <Box
                    sx={{
                      display: 'flex',
                      flex: 1,
                      background: 'linear-gradient(135deg, rgba(17,24,39,0.9) 0%, rgba(55,65,81,0.9) 100%)',
                    }}
                  >
                    <FilmPerforationColumn />
                    <Box sx={{ flex: 1, minWidth: 0, px: 2, py: 1.75, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                      {/* 加号图标 */}
                      <Box
                        sx={{
                          width: 80,
                          height: 80,
                          borderRadius: '50%',
                          background: 'linear-gradient(145deg, rgba(245,158,11,0.2) 0%, rgba(217,119,6,0.15) 100%)',
                          border: '1px solid rgba(245,158,11,0.4)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          mb: 2,
                        }}
                      >
                        <AddIcon sx={{ fontSize: 36, color: 'rgba(255,255,255,0.9)' }} />
                      </Box>

                      <Typography
                        variant="subtitle1"
                        sx={{
                          fontWeight: 700,
                          color: 'rgba(255,255,255,0.97)',
                          textAlign: 'center',
                          mb: 0.5,
                        }}
                      >
                        创建新项目
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{
                          color: 'rgba(255,255,255,0.7)',
                          textAlign: 'center',
                        }}
                      >
                        上传书籍创建项目
                      </Typography>
                    </Box>
                    <FilmPerforationColumn />
                  </Box>
                </Box>
              </Card>
            </Grid>
          </Grid>
        )}

        <Menu
          id={actionMenuId}
          anchorEl={actionMenuAnchor}
          open={Boolean(actionMenuAnchor && actionMenuProject)}
          onClose={closeActionMenu}
          PaperProps={{
            sx: {
              minWidth: 180,
              backgroundColor: 'rgba(17,24,39,0.98)',
              border: '1px solid rgba(255,255,255,0.12)',
              color: 'rgba(255,255,255,0.95)',
            },
          }}
        >
          <MenuItem
            onClick={() => {
              if (!actionMenuProject) return
              startRenameProject(actionMenuProject)
            }}
          >
            <EditOutlinedIcon sx={{ mr: 1, fontSize: 18 }} />
            重命名项目
          </MenuItem>
          <MenuItem
            onClick={() => {
              if (!actionMenuProject) return
              openPurgeDialog(actionMenuProject, 'action_menu')
            }}
            disabled={purgeSubmitting && purgeTarget?.id === actionMenuProject?.id}
            sx={{ color: 'rgba(248,113,113,0.95)' }}
          >
            <DeleteOutlineIcon sx={{ mr: 1, fontSize: 18 }} />
            删除生成内容（不可恢复）
          </MenuItem>
        </Menu>

        <Dialog
          open={purgeDialogOpen}
          onClose={closePurgeDialog}
          fullWidth
          maxWidth="sm"
          aria-labelledby="dreamweaver-purge-dialog-title"
          aria-describedby="dreamweaver-purge-dialog-desc"
        >
          <DialogTitle id="dreamweaver-purge-dialog-title">
            删除生成内容：{purgeTarget ? getDisplayTitle(purgeTarget.title) : '-'}
          </DialogTitle>
          <DialogContent dividers>
            <Alert severity="warning" sx={{ mb: 2 }}>
              此操作不可恢复，将清理该项目已生成的内容（历史 runs 与素材库图片）。
            </Alert>
            <Typography variant="body2" color="text.secondary">
              将删除：
            </Typography>
            <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
              - 历史 runs（数据库记录 + runs/{'{run_id}'} 产物文件）
              - 素材库图片（runs/library/project_{'{project_id}'}）
            </Typography>
            <Typography id="dreamweaver-purge-dialog-desc" variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
              注意：运行中/排队中的 run 会跳过；若存在运行/排队任务，将不会清理素材库以避免影响任务。
            </Typography>
            {purgeDialogError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {purgeDialogError}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={closePurgeDialog} disabled={purgeSubmitting} sx={keyboardFocusRingSx}>
              取消
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={confirmPurgeDialog}
              disabled={purgeSubmitting || !purgeTarget}
              sx={keyboardFocusRingSx}
            >
              {purgeSubmitting ? '删除中…' : '确认删除'}
            </Button>
          </DialogActions>
        </Dialog>

        {/* 书籍上传对话框 */}
        <BookParserUploadDialog
          open={bookUploadDialogOpen}
          onClose={() => setBookUploadDialogOpen(false)}
          onUploadSuccess={handleBookUploadSuccess}
        />
      </Container>
    </Box>
  )
}
