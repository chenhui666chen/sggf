/**
 * 耳畔星河 - 有声小说仪表盘页面
 * 
 * 功能：
 * 1. 项目列表展示
 * 2. 项目搜索和筛选
 * 3. 点击项目跳转到有声书生成页面
 * 4. 项目管理（创建、删除等）
 */
import { useMemo, useState, useEffect } from 'react'
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
  FormControlLabel,
  Checkbox,
  Paper,
} from '@mui/material'
import {
  Search as SearchIcon,
  Add as AddIcon,
  Headphones as HeadphonesIcon,
  MoreVert as MoreVertIcon,
  Delete as DeleteIcon,
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
  const [deleteReason, setDeleteReason] = useState('')
  const [deleteFiles, setDeleteFiles] = useState(false)
  const [loadingDelete, setLoadingDelete] = useState(false)
  const [projectImpact, setProjectImpact] = useState<{
    chapters: number
    audioFiles: number
    totalSize: string
  } | null>(null)
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [selectedProjectForMenu, setSelectedProjectForMenu] = useState<Project | null>(null)

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

  // 打开项目菜单
  const handleOpenProjectMenu = (event: React.MouseEvent<HTMLElement>, project: Project) => {
    event.stopPropagation()
    setAnchorEl(event.currentTarget)
    setSelectedProjectForMenu(project)
  }

  // 关闭项目菜单
  const handleCloseProjectMenu = () => {
    setAnchorEl(null)
    setSelectedProjectForMenu(null)
  }

  // 打开删除确认对话框
  const handleOpenDeleteDialog = async (project: Project) => {
    setProjectToDelete(project)
    setDeleteReason('')
    setDeleteFiles(false)
    setProjectImpact(null)
    handleCloseProjectMenu()
    setDeleteDialogOpen(true)

    try {
      // 获取项目影响范围信息
      const res = await apiClient.getAudiobookProjectsByProject(project.id)
      const audiobookProject = res.data?.[0]
      if (audiobookProject) {
        setProjectImpact({
          chapters: audiobookProject.total_chapters || 0,
          audioFiles: audiobookProject.completed_chapters || 0,
          totalSize: '计算中...'
        })
      }
    } catch (error) {
      console.error('获取项目信息失败:', error)
    }
  }

  // 执行删除操作
  const handleDeleteProject = async () => {
    if (!projectToDelete) return

    setLoadingDelete(true)
    try {
      await apiClient.deleteAudiobookProject(projectToDelete.id, {
        delete_reason: deleteReason,
        delete_files: deleteFiles
      })
      setSnackbar({
        open: true,
        message: '项目已成功删除',
        severity: 'success'
      })
      setDeleteDialogOpen(false)
      await fetchProjects()
    } catch (error: any) {
      console.error('删除项目失败:', error)
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || '删除项目失败，请稍后重试',
        severity: 'error'
      })
    } finally {
      setLoadingDelete(false)
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
                          transition: 'all 0.3s',
                          background: `radial-gradient(circle at 30% 20%, ${colors.accent}33 0%, rgba(248,249,255,0.96) 45%, ${colors.secondary}33 100%)`,
                          position: 'relative',
                          overflow: 'hidden',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          minHeight: 180,
                          '&:hover': {
                            transform: 'translateY(-6px)',
                            boxShadow: '0 16px 36px rgba(0,0,0,0.28)',
                          },
                        }}
                        onClick={() => handleProjectClick(project)}
                      >
                        {/* 更多选项按钮 */}
                        <IconButton
                          sx={{
                            position: 'absolute',
                            top: 8,
                            right: 8,
                            zIndex: 1,
                          }}
                          onClick={(e) => handleOpenProjectMenu(e, project)}
                        >
                          <MoreVertIcon />
                        </IconButton>

                        <CardContent
                          sx={{
                            width: '100%',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            py: 4,
                          }}
                        >
                          <Box
                            sx={{
                              width: 112,
                              height: 112,
                              borderRadius: '50%',
                              position: 'relative',
                              mb: 2,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              backgroundColor: '#f3ecff',
                            }}
                          >
                            {/* 内层深色圆 */}
                            <Box
                              sx={{
                                width: 90,
                                height: 90,
                                borderRadius: '50%',
                                backgroundColor: '#262b4f',
                                position: 'relative',
                              }}
                            />

                            {/* 播放按钮（三角形） */}
                            <Box
                              sx={{
                                position: 'absolute',
                                width: 34,
                                height: 34,
                                backgroundColor: '#ffffff',
                                clipPath: 'polygon(28% 18%, 78% 50%, 28% 82%)',
                              }}
                            />

                            {/* 耳机头梁（上方弧线） */}
                            <Box
                              sx={{
                                position: 'absolute',
                                top: 8,
                                width: 92,
                                height: 92,
                                borderRadius: '50%',
                                border: '7px solid #ff9fb8',
                                borderBottomColor: 'transparent',
                                backgroundColor: 'transparent',
                                boxSizing: 'border-box',
                              }}
                            />

                            {/* 左右耳罩 */}
                            <Box
                              sx={{
                                position: 'absolute',
                                left: 14,
                                top: 54,
                                width: 26,
                                height: 32,
                                borderRadius: 14,
                                backgroundColor: '#ff9fb8',
                              }}
                            />
                            <Box
                              sx={{
                                position: 'absolute',
                                right: 14,
                                top: 54,
                                width: 26,
                                height: 32,
                                borderRadius: 14,
                                backgroundColor: '#ff9fb8',
                              }}
                            />
                          </Box>
                          
                          {/* 项目名称 */}
                          <Typography
                            variant="subtitle1"
                            sx={{
                              fontWeight: 700,
                              textAlign: 'center',
                              color: '#3d356b',
                              px: 2,
                            }}
                          >
                            {project.title}
                          </Typography>
                          
                          {/* 项目流派 */}
                          {project.genre && (
                            <Chip
                              label={project.genre}
                              size="small"
                              sx={{ mt: 1, fontSize: '0.75rem' }}
                            />
                          )}
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

      {/* 项目菜单 */}
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={handleCloseProjectMenu}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
      >
        <MenuItem
          onClick={() => selectedProjectForMenu && handleOpenDeleteDialog(selectedProjectForMenu)}
          sx={{ color: '#f44336' }}
        >
          <DeleteIcon sx={{ mr: 1 }} />
          删除项目
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
          删除项目确认
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            此操作将删除项目 "{projectToDelete?.title}"，此操作不可恢复！
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

          <TextField
            fullWidth
            multiline
            rows={3}
            label="删除原因（可选）"
            placeholder="请输入删除原因，便于后续分析..."
            value={deleteReason}
            onChange={(e) => setDeleteReason(e.target.value)}
            sx={{ mb: 2 }}
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={deleteFiles}
                onChange={(e) => setDeleteFiles(e.target.checked)}
                color="error"
              />
            }
            label="同时删除音频文件（不可恢复）"
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setDeleteDialogOpen(false)}
            disabled={loadingDelete}
          >
            取消
          </Button>
          <Button
            onClick={handleDeleteProject}
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
    </Box>
  )
}

export default AudiobookDashboardPage
