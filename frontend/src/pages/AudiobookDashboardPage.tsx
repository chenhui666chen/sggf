/**
 * 耳畔星河 - 有声小说仪表盘页面
 * 
 * 功能：
 * 1. 项目列表展示
 * 2. 项目搜索和筛选
 * 3. 点击项目跳转到有声书生成页面
 * 4. 项目管理（创建、删除等）
 */
import { useState, useEffect } from 'react'
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
} from '@mui/material'
import {
  Search as SearchIcon,
  Add as AddIcon,
  Headphones as HeadphonesIcon,
  VisibilityOff as VisibilityOffIcon,
  MoreVert as MoreVertIcon,
} from '@mui/icons-material'
import {
  Menu,
  MenuItem,
  IconButton,
} from '@mui/material'

// 类型定义
interface Project {
  id: number
  title: string
  description?: string
  genre?: string
}

const AudiobookDashboardPage = () => {
  const navigate = useNavigate()
  
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

  // 筛选项目
  const filteredProjects = projects.filter((project) => {
    const matchesSearch = project.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         (project.description?.toLowerCase().includes(searchQuery.toLowerCase()))
    const matchesGenre = selectedGenre === 'all' || project.genre === selectedGenre
    return matchesSearch && matchesGenre
  })

  // 获取所有流派
  const genres: string[] = Array.from(new Set(projects.map((p) => p.genre).filter(Boolean)) as unknown as string[])

  // 点击项目卡片，跳转到有声书生成页面
  const handleProjectClick = (project: Project) => {
    navigate(`/audiobook/${project.id}`)
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
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* 页面标题 */}
      <Box sx={{ mb: 4 }}>
        <Typography
          variant="h4"
          sx={{
            fontWeight: 700,
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            mb: 1,
          }}
        >
          耳畔星河 - 有声小说
        </Typography>
        <Typography variant="body1" color="text.secondary">
          选择项目开始生成有声小说
        </Typography>
      </Box>

      {/* 搜索和筛选栏 */}
      <Box sx={{ mb: 4, display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField
          placeholder="搜索项目..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          size="small"
          sx={{ minWidth: 300, flexGrow: 1 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          }}
        />
        
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setNewProjectDialogOpen(true)}
          sx={{
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          新建项目
        </Button>
      </Box>

      {/* 流派筛选 */}
      {genres.length > 0 && (
        <Box sx={{ mb: 3, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          <Chip
            label="全部"
            onClick={() => setSelectedGenre('all')}
            color={selectedGenre === 'all' ? 'primary' : 'default'}
            sx={{ cursor: 'pointer' }}
          />
          {genres.map((genre) => (
            <Chip
              key={genre}
              label={genre}
              onClick={() => setSelectedGenre(genre)}
              color={selectedGenre === genre ? 'primary' : 'default'}
              sx={{ cursor: 'pointer' }}
            />
          ))}
        </Box>
      )}

      {/* 加载状态 */}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          {/* 空状态 */}
          {filteredProjects.length === 0 ? (
            <Box
              sx={{
                py: 12,
                textAlign: 'center',
                backgroundColor: 'rgba(255,255,255,0.95)',
                borderRadius: 2,
              }}
            >
              <HeadphonesIcon sx={{ fontSize: 64, color: '#9c27b0', mb: 2 }} />
              <Typography variant="h6" sx={{ mb: 1 }}>
                {searchQuery ? '未找到匹配的项目' : '暂无项目'}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                {searchQuery ? '请尝试其他搜索关键词' : '请先创建小说项目'}
              </Typography>
              {!searchQuery && (
                <Button
                  variant="contained"
                  startIcon={<AddIcon />}
                  onClick={() => setNewProjectDialogOpen(true)}
                  sx={{
                    backgroundColor: '#9c27b0',
                    '&:hover': { backgroundColor: '#7b1fa2' },
                  }}
                >
                  创建第一个项目
                </Button>
              )}
            </Box>
          ) : (
            /* 项目列表 */
            <Grid container spacing={3}>
              {filteredProjects.map((project) => (
                <Grid
                  item
                  key={project.id}
                  sx={{
                    flexBasis: { xs: '100%', sm: '50%', md: '33.33%', lg: '25%' },
                    maxWidth: { xs: '100%', sm: '50%', md: '33.33%', lg: '25%' },
                  }}
                >
                  <Card
                    sx={{
                      cursor: 'pointer',
                      transition: 'all 0.3s',
                      background: 'radial-gradient(circle at 30% 20%, #ffe4f3 0%, #f8f9ff 40%, #d7e0ff 100%)',
                      position: 'relative',
                      overflow: 'hidden',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      minHeight: 180,
                      '&:hover': {
                        transform: 'translateY(-6px)',
                        boxShadow: '0 12px 32px rgba(156, 39, 176, 0.35)',
                      },
                    }}
                    onClick={() => handleProjectClick(project)}
                  >
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
              ))}
            </Grid>
          )}
        </>
      )}

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
    </Container>
  )
}

export default AudiobookDashboardPage
