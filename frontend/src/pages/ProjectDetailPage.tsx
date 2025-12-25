﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿import { useEffect, useState } from 'react'
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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Slider,
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
  // 🔧 修复：从 localStorage 读取排序偏好
  const [chapterSortOrder, setChapterSortOrder] = useState<'asc' | 'desc'>(() => {
    const saved = localStorage.getItem('chapterSortOrder')
    return (saved === 'asc' || saved === 'desc') ? saved : 'asc'
  })
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [chapterToDelete, setChapterToDelete] = useState<any>(null)
  const [deleting, setDeleting] = useState(false)
  const [trashDrawerOpen, setTrashDrawerOpen] = useState(false)
  const [deletedChapters, setDeletedChapters] = useState<any[]>([])
  const [deletedChaptersLoading, setDeletedChaptersLoading] = useState(false)
  const [restoring, setRestoring] = useState<number | null>(null)

  const [audioSettings, setAudioSettings] = useState<{
    characterId: number
    name: string
    gender?: string | null
    role?: string | null
    voiceId: string
    volume: number
    speed?: number
    pitch?: number
  }[]>([])
  const [audioLoading, setAudioLoading] = useState(false)
  const [audioSaving, setAudioSaving] = useState(false)
  const [audioAutoAssigning, setAudioAutoAssigning] = useState(false)
  const [audioError, setAudioError] = useState<string | null>(null)
  const [previewingId, setPreviewingId] = useState<number | null>(null)

  // 🆕 当切换到音频配置 Tab 时自动加载
  useEffect(() => {
    if (tabValue === 5 && projectId && audioSettings.length === 0) {
      loadAudioConfig()
    }
  }, [tabValue, projectId])

  useEffect(() => {
    // 当项目 ID 改变时，清除编辑器状态，确保项目隔离
    console.log('🔄 ProjectDetailPage useEffect 触发，projectId:', projectId)
    dispatch(clearEditorState())

    if (projectId) {
      loadProjectDetails()
      loadChapters()  // 自动加载章节列表
      loadAudioConfig()  // 加载项目级音频配置
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

  // 🔧 修复：接收 sortOrder 参数，避免闭包问题
  const loadChapters = async (sortOrder?: 'asc' | 'desc') => {
    if (!projectId) {
      console.warn('⚠️ loadChapters: projectId 为空')
      return
    }
    // 优先使用传入的参数，否则从 localStorage 读取最新值
    const currentSortOrder = sortOrder ?? (localStorage.getItem('chapterSortOrder') as 'asc' | 'desc') ?? 'asc'
    try {
      setChaptersLoading(true)
      console.log('📍 开始加载章节列表，projectId:', projectId, '排序:', currentSortOrder)
      const response = await apiClient.getChapters(parseInt(projectId), currentSortOrder)
      const chaptersData = response.data || []
      console.log('✅ 章节列表加载成功，数量:', chaptersData.length)
      // 按章节编号排序
      const sortedChapters = chaptersData.sort((a: any, b: any) =>
        currentSortOrder === 'asc'
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

  const handleOpenChaptersDrawer = () => {
    setShowChaptersDrawer(true)
  }

  const handleCloseChaptersDrawer = () => {
    setShowChaptersDrawer(false)
  }

  const loadAudioConfig = async () => {
    if (!projectId) {
      return
    }
    try {
      setAudioLoading(true)
      setAudioError(null)
      const projectIdNum = parseInt(projectId)

      const [charactersRes, configRes] = await Promise.all([
        apiClient.getCharacters(projectIdNum),
        apiClient.getProjectAudioConfig(projectIdNum),
      ])

      const characters = (charactersRes.data || []) as any[]
      const configData = (configRes.data || { characters: [] }) as {
        characters?: {
          character_id: number
          name: string
          voice_id: string
          volume: number
          speed?: number | null
          pitch?: number | null
        }[]
      }
      const configById = new Map<number, { voice_id: string; volume: number; speed?: number | null; pitch?: number | null }>()
      for (const item of configData.characters || []) {
        configById.set(item.character_id, {
          voice_id: item.voice_id,
          volume: item.volume,
          speed: item.speed ?? undefined,
          pitch: item.pitch ?? undefined,
        })
      }

      const settings = characters.map((c) => {
        const existing = configById.get(c.id)
        return {
          characterId: c.id,
          name: c.name,
          gender: c.gender,
          role: c.role,
          voiceId: existing?.voice_id || '',
          volume: existing?.volume ?? 50,
          speed: existing?.speed ?? 1.0,
          pitch: existing?.pitch ?? 50,
        }
      })

      setAudioSettings(settings)
    } catch (err) {
      console.error('❌ 加载音频配置失败:', err)
      setAudioError('加载音频配置失败')
    } finally {
      setAudioLoading(false)
    }
  }

  const handleSaveAudioConfig = async () => {
    if (!projectId) return
    try {
      setAudioSaving(true)
      const projectIdNum = parseInt(projectId)
      const payload = {
        characters: audioSettings
          .filter((s) => s.voiceId)
          .map((s) => ({
            character_id: s.characterId,
            name: s.name,
            voice_id: s.voiceId,
            volume: s.volume,
            speed: s.speed,
            pitch: s.pitch,
          })),
      }
      await apiClient.updateProjectAudioConfig(projectIdNum, payload)
      alert('音频配置已保存为项目默认配置')
    } catch (err) {
      console.error('❌ 保存音频配置失败:', err)
      alert('保存音频配置失败，请稍后重试')
    } finally {
      setAudioSaving(false)
    }
  }

  const handleAutoAssignVoices = async () => {
    if (!projectId) return
    try {
      setAudioAutoAssigning(true)
      const projectIdNum = parseInt(projectId)
      const res = await apiClient.autoAssignProjectAudioVoices(projectIdNum)
      const configData = (res.data || { characters: [] }) as {
        characters?: {
          character_id: number
          name: string
          voice_id: string
          volume: number
          speed?: number | null
          pitch?: number | null
        }[]
      }

      const configById = new Map<
        number,
        { voice_id: string; volume: number; speed?: number | null; pitch?: number | null }
      >()
      for (const item of configData.characters || []) {
        configById.set(item.character_id, {
          voice_id: item.voice_id,
          volume: item.volume,
          speed: item.speed ?? undefined,
          pitch: item.pitch ?? undefined,
        })
      }

      setAudioSettings((prev) =>
        prev.map((cv) => {
          const conf = configById.get(cv.characterId)
          if (!conf) return cv
          return {
            ...cv,
            voiceId: conf.voice_id || '',
            volume: conf.volume ?? cv.volume,
            speed: conf.speed ?? cv.speed,
            pitch: conf.pitch ?? cv.pitch,
          }
        }),
      )

      // ✅ 添加明确的成功反馈
      const assignedCount = configById.size
      if (assignedCount > 0) {
        alert(`✅ 已为 ${assignedCount} 个角色智能推荐声线！\n\n请检查推荐结果，如需调整可手动修改，最后点击「保存为项目默认配置」保存。`)
      } else {
        alert('⚠️ 当前项目还没有角色档案，请先在「👥 人物设定」中创建角色。')
      }
    } catch (err) {
      console.error('❌ 自动推荐声线失败:', err)
      alert('自动推荐声线失败，请稍后重试')
    } finally {
      setAudioAutoAssigning(false)
    }
  }

  const handlePreviewAudio = async (setting: {
    characterId: number
    name: string
    voiceId: string
    volume: number
    speed?: number
    pitch?: number
  }) => {
    if (!projectId) return
    if (!setting.voiceId) {
      alert('请先选择音色再试听')
      return
    }
    try {
      setPreviewingId(setting.characterId)
      const text = `这是角色「${setting.name}」的语音示例。`
      const response = await apiClient.previewTTS({
        text,
        voice_id: setting.voiceId,
        volume: setting.volume,
        speed: setting.speed,
        pitch: setting.pitch,
      })
      const blob = response.data as Blob
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.play()
      audio.onended = () => {
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      console.error('❌ 音频试听失败:', err)
      alert('音频试听失败，请稍后重试')
    } finally {
      setPreviewingId(null)
    }
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
      
      // 显示成功提示
      alert('章节已移至回收站')
    } catch (err) {
      console.error('❌ 删除章节失败:', err)
      alert('删除章节失败，请重试')
    } finally {
      setDeleting(false)
    }
  }

  const loadDeletedChapters = async () => {
    if (!projectId) return
    
    try {
      setDeletedChaptersLoading(true)
      const response = await apiClient.getDeletedChapters(parseInt(projectId))
      const deletedData = response.data || []
      // 按删除时间倒序排列
      const sortedDeleted = deletedData.sort((a: any, b: any) => 
        new Date(b.deleted_at).getTime() - new Date(a.deleted_at).getTime()
      )
      setDeletedChapters(sortedDeleted)
    } catch (err) {
      console.error('❌ 加载已删除章节失败:', err)
      setDeletedChapters([])
    } finally {
      setDeletedChaptersLoading(false)
    }
  }

  const handleRestoreChapter = async (chapterId: number) => {
    try {
      setRestoring(chapterId)
      await apiClient.restoreChapter(chapterId)
      
      // 刷新两个列表
      await Promise.all([
        loadChapters(),
        loadDeletedChapters()
      ])
      
      alert('章节已恢复')
    } catch (err) {
      console.error('❌ 恢复章节失败:', err)
      alert('恢复章节失败，请重试')
    } finally {
      setRestoring(null)
    }
  }

  const handleOpenTrashDrawer = () => {
    setTrashDrawerOpen(true)
    loadDeletedChapters()
  }

  const handleChapterSortOrderChange = async (newOrder: 'asc' | 'desc') => {
    console.log('切换排序方式:', newOrder)
    setChapterSortOrder(newOrder)
    // 🔧 修复：保存到 localStorage
    localStorage.setItem('chapterSortOrder', newOrder)
    // 重新加载章节列表，传入新的排序参数避免闭包问题
    await loadChapters(newOrder)
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
          <Tab label="🎧 音频配置" id="tab-5" aria-controls="tabpanel-5" />
          <Tab label="⭐ 评审结果" id="tab-6" aria-controls="tabpanel-6" />
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
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
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
            <Button
              variant="outlined"
              onClick={handleOpenTrashDrawer}
            >
              🗑️ 回收站 ({deletedChapters.length})
            </Button>
            <Button
              variant="text"
              size="small"
              onClick={() => navigate('/trash')}
              sx={{ ml: 1 }}
            >
              查看全部
            </Button>
          </Box>
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

      {/* 音频配置 */}
      <TabPanel value={tabValue} index={5}>
        {audioError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {audioError}
          </Alert>
        )}

        {audioLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            <Paper
              variant="outlined"
              sx={{
                maxHeight: 500,
                overflow: 'auto',
              }}
            >
              <List>
                {audioSettings.map((cv) => (
                  <ListItem
                    key={cv.characterId}
                    alignItems="flex-start"
                    sx={{
                      alignItems: 'stretch',
                      '&:hover': {
                        backgroundColor: '#f5f5f5',
                      },
                    }}
                  >
                    <Box sx={{ width: '100%' }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Box>
                          <Typography variant="subtitle2">{cv.name}</Typography>
                          {(cv.role || cv.gender) && (
                            <Typography variant="caption" color="text.secondary">
                              {cv.role || '角色'} · {cv.gender || '性别未设定'}
                            </Typography>
                          )}
                        </Box>
                        {cv.voiceId && (
                          <Chip label="已配置" size="small" color="success" sx={{ height: 20 }} />
                        )}
                      </Box>

                      <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                        <FormControl size="small" fullWidth>
                          <InputLabel>角色音</InputLabel>
                          <Select
                            label="角色音"
                            value={cv.voiceId}
                            onChange={(e) =>
                              setAudioSettings((prev) =>
                                prev.map((item) =>
                                  item.characterId === cv.characterId
                                    ? { ...item, voiceId: e.target.value as string }
                                    : item,
                                ),
                              )
                            }
                          >
                            <MenuItem value="">
                              <em>自动（AI 选择）</em>
                            </MenuItem>
                            <MenuItem value="male_young_energetic">年轻男主（热血）</MenuItem>
                            <MenuItem value="male_adult_calm">成熟男声（沉稳）</MenuItem>
                            <MenuItem value="female_young_gentle">年轻女主（温柔）</MenuItem>
                            <MenuItem value="female_adult_cold">成熟女性（高冷）</MenuItem>
                            <MenuItem value="elder_wise">长者旁白（睿智）</MenuItem>
                          </Select>
                        </FormControl>
                      </Box>

                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          音量：{cv.volume}
                        </Typography>
                        <Slider
                          size="small"
                          min={0}
                          max={100}
                          step={5}
                          value={cv.volume}
                          onChange={(_, value) =>
                            setAudioSettings((prev) =>
                              prev.map((item) =>
                                item.characterId === cv.characterId
                                  ? { ...item, volume: value as number }
                                  : item,
                              ),
                            )
                          }
                          sx={{ mt: 0.5 }}
                        />
                      </Box>

                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          语速：{cv.speed ?? 1.0}
                        </Typography>
                        <Slider
                          size="small"
                          min={0.5}
                          max={2.0}
                          step={0.1}
                          value={cv.speed ?? 1.0}
                          onChange={(_, value) =>
                            setAudioSettings((prev) =>
                              prev.map((item) =>
                                item.characterId === cv.characterId
                                  ? { ...item, speed: value as number }
                                  : item,
                              ),
                            )
                          }
                          sx={{ mt: 0.5 }}
                        />
                      </Box>

                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          音高：{cv.pitch ?? 50}
                        </Typography>
                        <Slider
                          size="small"
                          min={0}
                          max={100}
                          step={5}
                          value={cv.pitch ?? 50}
                          onChange={(_, value) =>
                            setAudioSettings((prev) =>
                              prev.map((item) =>
                                item.characterId === cv.characterId
                                  ? { ...item, pitch: value as number }
                                  : item,
                              ),
                            )
                          }
                          sx={{ mt: 0.5 }}
                        />
                      </Box>

                      <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => handlePreviewAudio(cv)}
                          disabled={!cv.voiceId || previewingId === cv.characterId}
                        >
                          {previewingId === cv.characterId ? '试听中...' : '试听'}
                        </Button>
                      </Box>
                    </Box>
                  </ListItem>
                ))}
              </List>
            </Paper>

            {audioSettings.length === 0 ? (
              <Alert severity="info" sx={{ mb: 2 }}>
                当前项目还没有结构化角色档案。请先在「👥 人物设定」模块中创建角色，然后点击下方按钮自动推荐声线。
              </Alert>
            ) : null}

            <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
              <Button
                variant="outlined"
                onClick={handleAutoAssignVoices}
                disabled={audioLoading || audioAutoAssigning}
              >
                {audioAutoAssigning ? '正在基于人物卡智能推荐...' : '基于人物卡自动推荐声线'}
              </Button>
              <Button
                variant="outlined"
                onClick={loadAudioConfig}
                disabled={audioLoading}
              >
                重新加载
              </Button>
              <Button
                variant="contained"
                onClick={handleSaveAudioConfig}
                disabled={audioSaving || audioSettings.length === 0}
              >
                {audioSaving ? '保存中...' : '保存为项目默认配置'}
              </Button>
            </Box>
          </>
        )}
      </TabPanel>

      {/* 评审结果 */}
      <TabPanel value={tabValue} index={6}>
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
        disableEnforceFocus
        disableAutoFocus
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
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  py: 0.5,
                  px: 0,
                  borderBottom: '1px solid #eee',
                }}
              >
                <ListItemButton
                  onClick={() => handleChapterClick(chapter.id)}
                  sx={{
                    flex: 1,
                    py: 1.5,
                    px: 2,
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
                    mr: 1,
                    '&:hover': {
                      backgroundColor: '#ffebee'
                    }
                  }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
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
          你确定要将章节 <strong>"{chapterToDelete?.title}"</strong> 移至回收站吗？
          <br />
          <br />
          章节将被移至回收站，你可以在回收站中恢复它。
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

      {/* 回收站抽屉 */}
      <Drawer
        anchor="right"
        open={trashDrawerOpen}
        onClose={() => setTrashDrawerOpen(false)}
        sx={{
          '& .MuiDrawer-paper': {
            width: 400,
            boxSizing: 'border-box',
          },
        }}
      >
        <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Typography variant="h6">🗑️ 回收站</Typography>
          <Button
            size="small"
            onClick={() => setTrashDrawerOpen(false)}
            startIcon={<CloseIcon />}
          >
            关闭
          </Button>
        </Box>
        <Divider />

        {deletedChaptersLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
            <CircularProgress size={40} />
          </Box>
        ) : deletedChapters.length > 0 ? (
          <List sx={{ flex: 1, overflow: 'auto' }}>
            {deletedChapters.map((chapter: any) => (
              <ListItem
                key={chapter.id}
                disablePadding
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  py: 0.5,
                  px: 0,
                  borderBottom: '1px solid #eee',
                }}
              >
                <ListItemButton
                  disabled
                  sx={{
                    flex: 1,
                    py: 1.5,
                    px: 2,
                    opacity: 0.7,
                  }}
                >
                  <ListItemText
                    primary={
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {chapter.title}
                      </Typography>
                    }
                    secondary={
                      <Box>
                        <Typography variant="caption" color="textSecondary" display="block">
                          📝 {chapter.word_count || 0} 字
                        </Typography>
                        <Typography variant="caption" color="textSecondary" display="block">
                          🗑️ 删除于 {new Date(chapter.deleted_at).toLocaleString('zh-CN')}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItemButton>
                <Button
                  size="small"
                  variant="contained"
                  color="success"
                  onClick={() => handleRestoreChapter(chapter.id)}
                  disabled={restoring === chapter.id}
                  startIcon={restoring === chapter.id ? <CircularProgress size={16} /> : undefined}
                  sx={{ mr: 1 }}
                >
                  {restoring === chapter.id ? '恢复中...' : '恢复'}
                </Button>
              </ListItem>
            ))}
          </List>
        ) : (
          <Box sx={{ p: 2 }}>
            <Alert severity="info">回收站为空</Alert>
          </Box>
        )}
      </Drawer>
    </Container>
  )
}

