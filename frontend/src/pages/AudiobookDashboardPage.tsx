/**
 * 耳畔星河 - 有声小说仪表盘页面
 * 
 * 功能：
 * 1. 项目列表展示
 * 2. 项目搜索和筛选
 * 3. 点击项目跳转到有声书生成页面
 * 4. 项目管理（创建、删除等）
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient, extractApiErrorMessage } from '../services/api'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
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
  List,
  ListItem,
  ListItemText,
  Paper,
  Snackbar,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import HistoryIcon from '@mui/icons-material/History'
import LogoutIcon from '@mui/icons-material/Logout'
import SearchIcon from '@mui/icons-material/Search'
import { useDispatch } from 'react-redux'
import { logout } from '@/store/slices/authSlice'
import ChapterDrawer from '@/components/audiobook/ChapterDrawer'
import ProjectCard from '@/components/audiobook/ProjectCard'
import useAudiobookChapterDrawer from '@/hooks/useAudiobookChapterDrawer'
import BookParserUploadDialog from '@/components/BookParserUploadDialog'
import type { BookSource } from '@/services/bookParserApi'
import type {
  AudiobookProjectSummary,
  BookColors,
  ChapterAudioDeleteCandidate,
  DeletedAudiobookProject,
  Project,
} from '@/types/audiobook'

const AudiobookDashboardPage = () => {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  
  // 状态管理
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedGenre, setSelectedGenre] = useState<string>('all')
  
  // 书籍上传对话框
  const [bookUploadDialogOpen, setBookUploadDialogOpen] = useState(false)
  

  
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

  // 回收站（已删除有声书项目）
  const [recycleBinOpen, setRecycleBinOpen] = useState(false)
  const [recycleBinLoading, setRecycleBinLoading] = useState(false)
  const [deletedAudiobookProjects, setDeletedAudiobookProjects] = useState<DeletedAudiobookProject[]>([])
  const [restoringAudiobookProjectId, setRestoringAudiobookProjectId] = useState<number | null>(null)

  const chapterDrawer = useAudiobookChapterDrawer({
    onNotify: ({ message, severity }) => setSnackbar({ open: true, message, severity }),
  })

  const [chapterAudioToDelete, setChapterAudioToDelete] = useState<ChapterAudioDeleteCandidate | null>(null)
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [loadingDeleteChapter, setLoadingDeleteChapter] = useState(false)

  // 获取项目列表
  const fetchProjects = async () => {
    try {
      setLoading(true)
      const res = await apiClient.getProjects()
      setProjects(res.data)
    } catch {
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

  const formatBytes = useCallback((bytes: number) => {
    const v = Number(bytes)
    if (!Number.isFinite(v) || v <= 0) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB']
    let idx = 0
    let value = v
    while (value >= 1024 && idx < units.length - 1) {
      value /= 1024
      idx += 1
    }
    const digits = idx === 0 ? 0 : idx === 1 ? 1 : 2
    return `${value.toFixed(digits)} ${units[idx]}`
  }, [])

  const fetchDeletedAudiobookProjects = useCallback(async () => {
    setRecycleBinLoading(true)
    try {
      const res = await apiClient.listDeletedProjects()
      const data = res.data as any
      const projects = Array.isArray(data?.projects) ? (data.projects as DeletedAudiobookProject[]) : []
      setDeletedAudiobookProjects(projects)
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '加载回收站失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setRecycleBinLoading(false)
    }
  }, [])

  const handleOpenRecycleBin = async () => {
    setRecycleBinOpen(true)
    await fetchDeletedAudiobookProjects()
  }

  const handleRestoreAudiobookProject = async (audiobookProjectId: number) => {
    setRestoringAudiobookProjectId(audiobookProjectId)
    try {
      await apiClient.restoreAudiobookProject(audiobookProjectId)
      setSnackbar({ open: true, message: '已恢复到项目列表', severity: 'success' })
      await fetchDeletedAudiobookProjects()
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '恢复失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setRestoringAudiobookProjectId(null)
    }
  }

  const handleOpenChapterDrawer = (project: Project) => {
    void chapterDrawer.openDrawer(project)
  }

  const handleRequestDeleteAudiobook = (project: Project, audiobookProject: AudiobookProjectSummary) => {
    setProjectToDelete(project)
    setAudiobookProjectIdToDelete(audiobookProject.id)
    setProjectImpact({
      chapters: audiobookProject.total_chapters || chapterDrawer.chapters.length,
      audioFiles: audiobookProject.chapter_audios?.filter((a) => Boolean(a.audio_path)).length || 0,
      totalSize: '计算中...',
    })
    setDeleteDialogOpen(true)
  }

  const handleDeleteAudiobook = async () => {
    if (!audiobookProjectIdToDelete || !projectToDelete) return

    setLoadingDelete(true)
    try {
      await apiClient.deleteAudiobookProject(audiobookProjectIdToDelete, { delete_files: true })
      setSnackbar({ open: true, message: '有声书已成功删除', severity: 'success' })
      setDeleteDialogOpen(false)
      chapterDrawer.closeDrawer()
      await fetchProjects()
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '删除有声书失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      setLoadingDelete(false)
    }
  }

  const handleRequestDeleteChapterAudio = (candidate: ChapterAudioDeleteCandidate) => {
    setChapterAudioToDelete(candidate)
    setDeleteChapterDialogOpen(true)
  }

  const handleDeleteChapterAudio = async () => {
    if (!chapterAudioToDelete) return
    setLoadingDeleteChapter(true)
    try {
      if (chapterDrawer.playingChapterNumber === chapterAudioToDelete.chapterNumber) chapterDrawer.stopPlayback()
      await apiClient.deleteChapterAudio(chapterAudioToDelete.id, { delete_files: true })

      if (chapterDrawer.open) {
        await chapterDrawer.refresh()
      }

      setSnackbar({ open: true, message: '章节音频已删除', severity: 'success' })
      setDeleteChapterDialogOpen(false)
      setChapterAudioToDelete(null)
    } catch (error: any) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '删除章节音频失败，请稍后重试'),
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
    const colors: Record<string, BookColors> = {
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

  const handleBookUploadSuccess = (book: BookSource) => {
    setSnackbar({
      open: true,
      message: `书籍《${book.title}》已上传、完成拆书分析并自动导入灵感方舟，可继续用于有声书改编`,
      severity: 'success',
    })
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
                variant="outlined"
                startIcon={<HistoryIcon />}
                onClick={handleOpenRecycleBin}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  '&:hover': {
                    borderColor: 'white',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  },
                }}
              >
                回收站
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
                    onClick={() => setBookUploadDialogOpen(true)}
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
                      <ProjectCard
                        project={project}
                        colors={colors}
                        onOpenProject={handleProjectClick}
                        onOpenChapterDrawer={handleOpenChapterDrawer}
                      />
                    </Grid>
                  )
                })}

                {/* 新建项目卡片入口 */}
                <Grid item xs={12} sm={6} md={4} lg={3}>
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
                      '&:hover': {
                        transform: 'translateY(-6px)',
                        boxShadow: '0 16px 36px rgba(0,0,0,0.28)',
                      },
                    }}
                    onClick={() => setBookUploadDialogOpen(true)}
                  >
                    <CardContent
                      sx={{
                        width: '100%',
                        position: 'relative',
                        zIndex: 1,
                        p: 2.5,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 2,
                      }}
                    >
                      {/* 唱片图标 */}
                      <Box
                        sx={{
                          width: 100,
                          height: 100,
                          borderRadius: '50%',
                          position: 'relative',
                          backgroundImage:
                            'radial-gradient(circle at 50% 50%, rgba(255,255,255,0.10) 0%, rgba(0,0,0,0.78) 38%, rgba(0,0,0,0.95) 72%),' +
                            'repeating-radial-gradient(circle at 50% 50%, rgba(255,255,255,0.06) 0px, rgba(255,255,255,0.06) 1px, rgba(0,0,0,0) 2px, rgba(0,0,0,0) 6px)',
                          boxShadow: '0 8px 20px rgba(0,0,0,0.25)',
                          border: '1px solid rgba(255,255,255,0.15)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <Box
                          sx={{
                            position: 'absolute',
                            inset: 30,
                            borderRadius: '50%',
                            background: 'linear-gradient(145deg, #1976d2 0%, #1565c0 100%)',
                            border: '1px solid rgba(255,255,255,0.25)',
                            boxShadow: 'inset 0 0 0 4px rgba(0,0,0,0.25)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          <AddIcon sx={{ color: 'white', fontSize: 28 }} />
                        </Box>
                      </Box>

                      <Box sx={{ textAlign: 'center' }}>
                        <Typography
                          sx={{
                            color: 'rgba(255,255,255,0.95)',
                            fontWeight: 700,
                            fontSize: '1.1rem',
                            mb: 0.5,
                          }}
                        >
                          新建有声项目
                        </Typography>
                        <Typography
                          sx={{
                            color: 'rgba(255,255,255,0.65)',
                            fontSize: '0.85rem',
                          }}
                        >
                          上传书籍创建项目
                        </Typography>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>
            )}
          </>
        )}
      </Container>

      {/* 回收站：已删除有声书项目 */}
      <Dialog
        open={recycleBinOpen}
        onClose={() => {
          if (!restoringAudiobookProjectId) setRecycleBinOpen(false)
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>回收站（已删除有声书）</DialogTitle>
        <DialogContent>
          {recycleBinLoading ? (
            <Box sx={{ py: 2, display: 'flex', justifyContent: 'center' }}>
              <CircularProgress size={24} />
            </Box>
          ) : deletedAudiobookProjects.length === 0 ? (
            <Alert severity="info" sx={{ mt: 1 }}>
              暂无已删除的有声书记录。
            </Alert>
          ) : (
            <List dense>
              {deletedAudiobookProjects.map((item) => (
                <ListItem
                  key={`deleted-audiobook-${item.id}`}
                  divider
                  secondaryAction={
                    <Button
                      size="small"
                      variant="contained"
                      onClick={() => handleRestoreAudiobookProject(item.id)}
                      disabled={restoringAudiobookProjectId === item.id}
                    >
                      {restoringAudiobookProjectId === item.id ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : (
                        '恢复'
                      )}
                    </Button>
                  }
                >
                  <ListItemText
                    primary={item.project_title ? `《${item.project_title}》` : `有声书项目 #${item.id}`}
                    secondary={
                      <>
                        <Typography variant="caption" color="text.secondary" display="block">
                          删除时间：{item.deleted_at ? new Date(item.deleted_at).toLocaleString() : '未知'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          影响：{item.affected_chapters ?? 0} 章 · {formatBytes(item.total_size ?? 0)}
                        </Typography>
                        {item.delete_reason ? (
                          <Typography variant="caption" color="text.secondary" display="block">
                            原因：{item.delete_reason}
                          </Typography>
                        ) : null}
                      </>
                    }
                  />
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setRecycleBinOpen(false)}
            disabled={Boolean(restoringAudiobookProjectId)}
          >
            关闭
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
      <ChapterDrawer
        open={chapterDrawer.open}
        project={chapterDrawer.project}
        audiobookProject={chapterDrawer.audiobookProject}
        loading={chapterDrawer.loading}
        error={chapterDrawer.error}
        chapters={chapterDrawer.chapters}
        mergedChapterAudiosByNumber={chapterDrawer.mergedChapterAudiosByNumber}
        chapterSortOrder={chapterDrawer.chapterSortOrder}
        formatTime={formatTime}
        playerIsPlaying={chapterDrawer.playerIsPlaying}
        playerCurrentTime={chapterDrawer.playerCurrentTime}
        playerDuration={chapterDrawer.playerDuration}
        playingChapterNumber={chapterDrawer.playingChapterNumber}
        onClose={chapterDrawer.closeDrawer}
        onPlayChapter={chapterDrawer.playChapter}
        onToggleSortOrder={chapterDrawer.toggleSortOrder}
        onSeekPreview={chapterDrawer.seekPreview}
        onSeekCommit={chapterDrawer.seekCommit}
        onRequestDeleteAudiobook={handleRequestDeleteAudiobook}
        onRequestDeleteChapterAudio={handleRequestDeleteChapterAudio}
      />

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

      {/* 书籍上传对话框 */}
      <BookParserUploadDialog
        open={bookUploadDialogOpen}
        onClose={() => setBookUploadDialogOpen(false)}
        onUploadSuccess={handleBookUploadSuccess}
      />
    </Box>
  )
}

export default AudiobookDashboardPage
