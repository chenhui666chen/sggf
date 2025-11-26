﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import {
  Container,
  Box,
  Typography,
  Card,
  CardContent,
  Tabs,
  Tab,
  Button,
  CircularProgress,
  Alert,
  Chip,
  Grid,
  Paper,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  IconButton,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import EditIcon from '@mui/icons-material/Edit'
import MenuIcon from '@mui/icons-material/Menu'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import { clearEditorState } from '@/store/slices/editorSlice'
import { generationService } from '@/services/generation'
import { apiClient } from '@/services/api'
import FormattedContent from '@/components/common/FormattedContent'

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`tabpanel-${index}`}
      aria-labelledby={`tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const [tabValue, setTabValue] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [projectData, setProjectData] = useState<any>(null)
  const [showChaptersDrawer, setShowChaptersDrawer] = useState(false)
  const [chapters, setChapters] = useState<any[]>([])
  const [chaptersLoading, setChaptersLoading] = useState(false)
  const [chapterSortOrder, setChapterSortOrder] = useState<'asc' | 'desc'>('asc')
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [chapterToDelete, setChapterToDelete] = useState<any>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    // 当项目 ID 改变时，清除编辑器状态，确保项目隔离
    console.log('🔄 ProjectDetailPage useEffect 触发，projectId:', projectId)
    dispatch(clearEditorState())

    if (projectId) {
      loadProjectDetails()
      loadChapters()  // 自动加载章节列表
    } else {
      console.warn('⚠️ projectId 为空')
      setError('项目ID不存在')
      setLoading(false)
    }
  }, [projectId, dispatch])

  const loadProjectDetails = async () => {
    try {
      setLoading(true)
      setError(null)

      if (!projectId) {
        console.error('❌ projectId 为空')
        setError('项目ID不存在')
        setLoading(false)
        return
      }

      console.log('📍 开始加载项目详情，projectId:', projectId, '类型:', typeof projectId)
      const projectIdNum = parseInt(projectId)
      console.log('📍 转换后的 projectId:', projectIdNum)

      const data = await generationService.getProjectDetails(projectIdNum)
      console.log('✅ 项目详情加载成功:', data)

      if (!data) {
        console.error('❌ 返回的数据为空')
        // 使用默认的项目数据结构，避免页面空白
        setProjectData({
          id: projectIdNum,
          title: '项目',
          description: '',
          genre: '',
          status: 'draft',
          word_count: 0,
          created_at: new Date().toISOString(),
          chapters: []
        })
        setLoading(false)
        return
      }

      setProjectData(data)
    } catch (err) {
      console.error('❌ 项目详情加载失败:', err)
      const errorMessage = err instanceof Error ? err.message : 'Failed to load project'
      console.error('❌ 错误详情:', errorMessage)

      // 使用默认的项目数据结构，避免页面空白
      if (projectId) {
        const projectIdNum = parseInt(projectId)
        setProjectData({
          id: projectIdNum,
          title: '项目',
          description: '',
          genre: '',
          status: 'draft',
          word_count: 0,
          created_at: new Date().toISOString(),
          chapters: []
        })
      }
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const loadChapters = async () => {
    if (!projectId) {
      console.warn('⚠️ loadChapters: projectId 为空')
      return
    }
    try {
      setChaptersLoading(true)
      console.log('📍 开始加载章节列表，projectId:', projectId)
      const response = await apiClient.getChapters(parseInt(projectId), chapterSortOrder)
      const chaptersData = response.data || []
      console.log('✅ 章节列表加载成功，数量:', chaptersData.length)
      // 按章节编号排序
      const sortedChapters = chaptersData.sort((a: any, b: any) => 
        chapterSortOrder === 'asc' 
          ? a.chapter_number - b.chapter_number 
          : b.chapter_number - a.chapter_number
      )
      setChapters(sortedChapters)
    } catch (err) {
      console.error('❌ 加载章节列表失败:', err)
      setChapters([])  // 设置为空数组，避免undefined
    } finally {
      setChaptersLoading(false)
    }
  }

  const handleOpenChaptersDrawer = async () => {
    setShowChaptersDrawer(true)
    if (chapters.length === 0) {
      await loadChapters()
    }
  }

  const handleCloseChaptersDrawer = () => {
    setShowChaptersDrawer(false)
  }

  const handleChapterClick = (chapterId: number) => {
    navigate(`/editor/${projectId}/${chapterId}`)
    setShowChaptersDrawer(false)
  }

  const handleDeleteClick = (chapter: any, event: React.MouseEvent) => {
    event.stopPropagation()
    setChapterToDelete(chapter)
    setDeleteDialogOpen(true)
  }

  const handleCloseDeleteDialog = () => {
    setDeleteDialogOpen(false)
    setChapterToDelete(null)
  }

  const handleConfirmDelete = async () => {
    if (!chapterToDelete) return
    
    try {
      setDeleting(true)
      console.log('🗑️ 开始删除章节:', chapterToDelete.id)
      
      await apiClient.deleteChapter(chapterToDelete.id)
      
      console.log('✅ 章节删除成功')
      
      // 刷新章节列表
      await loadChapters()
      
      // 关闭对话框
      handleCloseDeleteDialog()
      
      // 显示成功提示（可选）
      // 你可以使用toast或snackbar来显示成功消息
    } catch (err) {
      console.error('❌ 删除章节失败:', err)
      alert('删除章节失败，请重试')
    } finally {
      setDeleting(false)
    }
  }

  const handleChapterSortOrderChange = async (newOrder: 'asc' | 'desc') => {
    console.log('切换排序方式:', newOrder); // 添加日志以便调试
    setChapterSortOrder(newOrder)
    // 重新加载章节列表
    await loadChapters()
  }

  const getStageStatus = (status: string) => {
    switch (status) {
      case 'completed':
        return { color: 'success', label: '已完成' }
      case 'running':
        return { color: 'info', label: '进行中' }
      case 'pending':
        return { color: 'default', label: '待处理' }
      case 'failed':
        return { color: 'error', label: '失败' }
      default:
        return { color: 'default', label: status }
    }
  }

  if (loading) {
    return (
      <Container sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
        <CircularProgress />
      </Container>
    )
  }

  if (error || !projectData) {
    console.error('❌ 项目数据加载失败:', { error, projectData })
    return (
      <Container sx={{ py: 4 }}>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/dashboard')}>
          返回
        </Button>
        <Alert severity="error" sx={{ mt: 2 }}>
          {error || '项目不存在'}
        </Alert>
      </Container>
    )
  }

  console.log('✅ 项目数据已加载:', projectData)
  const { settings = {}, review = null } = projectData

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/dashboard')} sx={{ mb: 2 }}>
            返回
          </Button>
          <Typography variant="h4">{projectData.title}</Typography>
          <Typography variant="body2" color="textSecondary">
            {projectData.genre} • {projectData.description}
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<MenuIcon />}
          onClick={handleOpenChaptersDrawer}
        >
          Chapters
        </Button>
      </Box>

      {/* 五阶段工作流程状态 */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📊 五阶段工作流程
          </Typography>
          <Grid container spacing={2}>
            {[
              { stage: 'stage_one_status', label: '阶段一：概念开发' },
              { stage: 'stage_two_status', label: '阶段二：结构设计' },
              { stage: 'stage_three_status', label: '阶段三：内容创作' },
              { stage: 'stage_four_status', label: '阶段四：质量评审' },
              { stage: 'stage_five_status', label: '阶段五：迭代优化' },
            ].map((item) => {
              const status = settings[item.stage] || 'pending'
              const statusInfo = getStageStatus(status)
              return (
                <Grid item xs={12} sm={6} md={4} key={item.stage}>
                  <Paper sx={{ p: 2 }}>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      {item.label}
                    </Typography>
                    <Chip
                      label={statusInfo.label}
                      color={statusInfo.color as any}
                      size="small"
                    />
                  </Paper>
                </Grid>
              )
            })}
          </Grid>
        </CardContent>
      </Card>

      {/* 标签页 */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)}>
          <Tab label="📖 项目概念" id="tab-0" aria-controls="tabpanel-0" />
          <Tab label="🌍 世界观设定" id="tab-1" aria-controls="tabpanel-1" />
          <Tab label="👥 人物设定" id="tab-2" aria-controls="tabpanel-2" />
          <Tab label="📋 情节大纲" id="tab-3" aria-controls="tabpanel-3" />
          <Tab label="📚 章节列表" id="tab-4" aria-controls="tabpanel-4" />
          <Tab label="⭐ 评审结果" id="tab-5" aria-controls="tabpanel-5" />
        </Tabs>
      </Box>

      {/* 项目概念 */}
      <TabPanel value={tabValue} index={0}>
        {settings.concept ? (
          <Paper sx={{ p: 2, backgroundColor: '#f5f5f5', maxHeight: 500, overflow: 'auto' }}>
            <FormattedContent content={settings.concept} />
          </Paper>
        ) : (
          <Alert severity="info">暂无项目概念</Alert>
        )}
      </TabPanel>

      {/* 世界观设定 */}
      <TabPanel value={tabValue} index={1}>
        {settings.world_setting ? (
          <Paper sx={{ p: 2, backgroundColor: '#f5f5f5', maxHeight: 500, overflow: 'auto' }}>
            <FormattedContent content={settings.world_setting} />
          </Paper>
        ) : (
          <Alert severity="info">暂无世界观设定</Alert>
        )}
      </TabPanel>

      {/* 人物设定 */}
      <TabPanel value={tabValue} index={2}>
        {settings.characters ? (
          <Paper sx={{ p: 2, backgroundColor: '#f5f5f5', maxHeight: 500, overflow: 'auto' }}>
            <FormattedContent content={settings.characters} />
          </Paper>
        ) : (
          <Alert severity="info">暂无人物设定</Alert>
        )}
      </TabPanel>

      {/* 情节大纲 */}
      <TabPanel value={tabValue} index={3}>
        {settings.plot_outline ? (
          <Paper sx={{ p: 2, backgroundColor: '#f5f5f5', maxHeight: 500, overflow: 'auto' }}>
            <FormattedContent content={settings.plot_outline} />
          </Paper>
        ) : (
          <Alert severity="info">暂无情节大纲</Alert>
        )}
      </TabPanel>

      {/* 章节列表 */}
      <TabPanel value={tabValue} index={4}>
        <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Button
            variant="contained"
            startIcon={<EditIcon />}
            onClick={() => {
              // 创建新章节的逻辑
              // 这里可以打开一个对话框让用户输入章节信息
              // 或者直接创建一个空章节并跳转到编辑器
              alert('创建新章节功能将在下一个版本实现')
            }}
          >
            创建新章节
          </Button>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
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
            >
              <ToggleButton value="asc" aria-label="正序">
                <ArrowUpwardIcon />
              </ToggleButton>
              <ToggleButton value="desc" aria-label="倒序">
                <ArrowDownwardIcon />
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
        </Box>
        {chapters.length > 0 ? (
          <Grid container spacing={2}>
            {chapters.map((chapter: any) => (
              <Grid item xs={12} key={chapter.id}>
                <Card
                  sx={{
                    cursor: 'pointer',
                    transition: 'all 0.3s ease',
                    '&:hover': {
                      boxShadow: 4,
                      transform: 'translateY(-2px)',
                      backgroundColor: '#f5f5f5'
                    }
                  }}
                  onClick={() => navigate(`/editor/${projectId}/${chapter.id}`)}
                >
                  <CardContent>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <Box sx={{ flex: 1 }}>
                        <Typography variant="h6" sx={{ mb: 1 }}>
                          {chapter.title}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                          <Typography variant="body2" color="textSecondary">
                            📝 {chapter.word_count} 字
                          </Typography>
                          <Typography variant="body2" color="textSecondary">
                            📅 {new Date(chapter.created_at).toLocaleDateString('zh-CN')}
                          </Typography>
                        </Box>
                      </Box>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<EditIcon />}
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(`/editor/${projectId}/${chapter.id}`)
                          }}
                        >
                          编辑
                        </Button>
                        <IconButton
                          size="small"
                          color="error"
                          onClick={(e) => handleDeleteClick(chapter, e)}
                          sx={{
                            '&:hover': {
                              backgroundColor: '#ffebee'
                            }
                          }}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        ) : (
          <Alert severity="info">
            暂无章节。点击上方"创建新章节"按钮开始创建。
          </Alert>
        )}
      </TabPanel>

      {/* 评审结果 */}
      <TabPanel value={tabValue} index={5}>
        {review ? (
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>
                质量评分：{review.quality_score?.toFixed(1) || 'N/A'} / 10
              </Typography>
              <Paper sx={{ p: 2, backgroundColor: '#f5f5f5', mb: 2 }}>
                <Typography 
                  variant="body2" 
                  sx={{ 
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                    lineHeight: 1.6
                  }}
                >
                  {review.feedback}
                </Typography>
              </Paper>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Chip
                  label={`修订次数: ${review.revision_count}`}
                  size="small"
                />
                {review.needs_revision && (
                  <Chip
                    label="需要修订"
                    color="warning"
                    size="small"
                  />
                )}
              </Box>
            </CardContent>
          </Card>
        ) : (
          <Alert severity="info">暂无评审结果</Alert>
        )}
      </TabPanel>

      {/* 章节列表侧边栏 */}
      <Drawer
        anchor="right"
        open={showChaptersDrawer}
        onClose={handleCloseChaptersDrawer}
        sx={{
          '& .MuiDrawer-paper': {
            width: 350,
            boxSizing: 'border-box',
          },
        }}
      >
        <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">📚 章节列表</Typography>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
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
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
            <CircularProgress size={40} />
          </Box>
        ) : chapters.length > 0 ? (
          <List sx={{ flex: 1, overflow: 'auto' }}>
            {chapters.map((chapter: any) => (
              <ListItem 
                key={chapter.id} 
                disablePadding
                secondaryAction={
                  <IconButton
                    edge="end"
                    aria-label="delete"
                    size="small"
                    color="error"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDeleteClick(chapter, e)
                    }}
                    sx={{
                      '&:hover': {
                        backgroundColor: '#ffebee'
                      }
                    }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                }
              >
                <ListItemButton
                  onClick={() => handleChapterClick(chapter.id)}
                  sx={{
                    py: 1.5,
                    px: 2,
                    borderBottom: '1px solid #eee',
                    '&:hover': {
                      backgroundColor: '#f5f5f5',
                    },
                  }}
                >
                  <ListItemText
                    primary={
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {chapter.title}
                      </Typography>
                    }
                    secondary={
                      <Typography variant="caption" color="textSecondary">
                        📝 {chapter.word_count || 0} 字
                      </Typography>
                    }
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        ) : (
          <Box sx={{ p: 2 }}>
            <Alert severity="info">暂无章节</Alert>
          </Box>
        )}
      </Drawer>

      {/* 删除确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={handleCloseDeleteDialog}
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <DialogTitle id="delete-dialog-title">
          确认删除章节
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-dialog-description">
            你确定要删除章节 <strong>"{chapterToDelete?.title}"</strong> 吗？
            <br />
            <br />
            此操作不可恢复，章节内容将被永久删除。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeleteDialog} disabled={deleting}>
            取消
          </Button>
          <Button 
            onClick={handleConfirmDelete} 
            color="error" 
            variant="contained"
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={16} /> : <DeleteIcon />}
          >
            {deleting ? '删除中...' : '确认删除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

