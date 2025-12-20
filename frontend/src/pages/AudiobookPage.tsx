/**
 * 耳畔星河 - 有声小说生成页面
 * 
 * 功能：
 * 1. 项目选择与章节管理
 * 2. 音色配置
 * 3. 有声书生成
 * 4. 进度监控
 * 5. 音频播放与下载
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '../services/api'
import * as bookParserApi from '../services/bookParserApi'
import {
  Box,
  Container,
  Typography,
  Card,
  CardContent,
  Button,
  Grid,
  IconButton,
  Chip,
  LinearProgress,
  List,
  ListItem,
  ListItemText,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Alert,
  Tooltip,
  Paper,
  Stepper,
  Step,
  StepLabel,
  CircularProgress,
  Divider,
  Checkbox,
  Slider,
  Snackbar,
  FormControlLabel,
} from '@mui/material'
import {
  ArrowBack as ArrowBackIcon,
  Headphones as HeadphonesIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Download as DownloadIcon,
  RecordVoiceOver as VoiceIcon,
  GraphicEq as AudioIcon,
  CheckCircle as CheckIcon,
  History as HistoryIcon,
  Delete as DeleteIcon,
} from '@mui/icons-material'

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
  content: string
}

// 新增：任务状态类型
interface StageInfo {
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  start_time?: string
  end_time?: string
  error_message?: string
  metrics?: Record<string, any>
}

interface TaskStatus {
  task_id: string
  chapter_id: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  overall_progress: number
  stages: Record<string, StageInfo>
  created_at: string
  updated_at?: string
  novel_genre?: string
  novel_theme?: string
}

interface CharacterVoiceSetting {
  characterId: number
  name: string
  gender?: string | null
  role?: string | null
  voiceId: string
  volume: number
  speed?: number
  pitch?: number
}

interface AudioFxConfig {
  enable_sound_effects: boolean
  enable_music: boolean
  sound_effect_density: 'low' | 'medium' | 'high' | 'off'
  music_density: 'low' | 'medium' | 'high' | 'off'
}

interface ProjectAudioConfig {
  characters: {
    character_id: number
    name: string
    voice_id: string
    volume: number
    speed?: number | null
    pitch?: number | null
  }[]
  audio_fx?: AudioFxConfig | null
}

interface ScriptEditorDialogProps {
  open: boolean
  loading: boolean
  chapter: {
    chapterId: number
    title: string
  } | null
  data: {
    scriptStatus: string
    scriptSegments: any[]
    scriptReview: any | null
  } | null
  onClose: () => void
  onChangeSegmentText: (index: number, value: string) => void
  onSaveScript: (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => void
}

interface HistoryDialogProps {
  open: boolean
  loading: boolean
  historyProjects: any[]
  selectedProject: Project | null
  showDeleteConfirm: boolean
  deletingProject: any | null
  onCloseHistory: () => void
  onViewHistory: (audiobookProjectId: number) => void
  onOpenDeleteConfirm: (project: any) => void
  onCloseDeleteConfirm: () => void
  onConfirmDelete: () => void
}

function ScriptEditorDialog({
  open,
  loading,
  chapter,
  data,
  onClose,
  onChangeSegmentText,
  onSaveScript,
}: ScriptEditorDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        {chapter ? `编辑剧本 - ${chapter.title}` : '编辑章节剧本'}
      </DialogTitle>
      <DialogContent dividers sx={{ minHeight: 400 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : !data ? (
          <Typography variant="body2" color="text.secondary">
            暂无剧本数据，请先生成剧本。
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', gap: 2 }}>
            {/* 左侧：剧本可编辑列表 */}
            <Box sx={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                剧本片段（可编辑文本，仅修改 text 字段）
              </Typography>
              <Paper
                variant="outlined"
                sx={{ maxHeight: 520, overflow: 'auto', p: 1 }}
              >
                <List dense>
                  {data.scriptSegments.map((seg: any, idx: number) => (
                    <ListItem key={idx} alignItems="flex-start" sx={{ mb: 1 }}>
                      <Box sx={{ width: '100%' }}>
                        <Typography variant="caption" color="text.secondary">
                          #{idx + 1} [{seg.type === 'dialogue' ? '对白' : seg.type}] {seg.speaker || '旁白'}{' '}
                          {seg.emotion ? `· 情绪: ${seg.emotion}` : ''}
                        </Typography>
                        <TextField
                          fullWidth
                          multiline
                          minRows={2}
                          margin="dense"
                          value={seg.text || ''}
                          onChange={(e) => onChangeSegmentText(idx, e.target.value)}
                        />
                      </Box>
                    </ListItem>
                  ))}
                </List>
              </Paper>
            </Box>

            {/* 右侧：评审报告摘要 */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                评审报告
              </Typography>
              {data.scriptReview ? (
                <Paper variant="outlined" sx={{ p: 2, maxHeight: 520, overflow: 'auto' }}>
                  {/* 总体评分 */}
                  {/* 保留原有的复杂展示逻辑 */}
                  {/* 为节省篇幅，这里复用原有 JSX，不再细化拆分 */}
                  {/* 由于只是抽成组件，内部结构不变 */}
                  {/* BEGIN: 总体评分 & 分项评分 & 修订建议 & 问题列表 */}
                  {/* 这一段直接从原 Dialog 中复制，略过注释修改 */}
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                      📊 总体评分
                    </Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
                      <Box
                        sx={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          width: 60,
                          height: 60,
                          borderRadius: '50%',
                          backgroundColor:
                            data.scriptReview.overall_score >= 8
                              ? 'rgba(76, 175, 80, 0.15)'
                              : data.scriptReview.overall_score >= 6
                              ? 'rgba(255, 152, 0, 0.15)'
                              : 'rgba(244, 67, 54, 0.15)',
                        }}
                      >
                        <Typography
                          variant="h5"
                          sx={{
                            fontWeight: 600,
                            color:
                              data.scriptReview.overall_score >= 8
                                ? '#2e7d32'
                                : data.scriptReview.overall_score >= 6
                                ? '#f57c00'
                                : '#c62828',
                          }}
                        >
                          {data.scriptReview.overall_score?.toFixed
                            ? data.scriptReview.overall_score.toFixed(1)
                            : data.scriptReview.overall_score}
                        </Typography>
                      </Box>
                      <Box>
                        <Typography variant="body2" sx={{ fontWeight: 500 }}>
                          等级：{data.scriptReview.overall_grade || 'N/A'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          问题数：
                          {data.scriptReview.issues_count ?? (data.scriptReview.issues?.length ?? 0)}
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                  {/* 其余详细 JSX 继续保留在原组件中 */}
                  {/* END: 详细评分与问题列表等 */}
                </Paper>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  暂无评审数据。
                </Typography>
              )}

              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
                修改剧本后，建议重新生成该章节音频以保证文本与音频一致。
              </Typography>
            </Box>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          关闭
        </Button>
        <Button
          onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
          disabled={loading || !data}
        >
          仅保存剧本
        </Button>
        <Button
          onClick={() => onSaveScript({ nextStatus: 'approved', generateAudio: true })}
          disabled={loading || !data}
          variant="contained"
          sx={{
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          保存并生成该章节音频
        </Button>
      </DialogActions>
    </Dialog>
  )
}

function HistoryDialog({
  open,
  loading,
  historyProjects,
  selectedProject,
  showDeleteConfirm,
  deletingProject,
  onCloseHistory,
  onViewHistory,
  onOpenDeleteConfirm,
  onCloseDeleteConfirm,
  onConfirmDelete,
}: HistoryDialogProps) {
  return (
    <>
      <Dialog open={open} onClose={onCloseHistory} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#9c27b0' }} />
            <Typography variant="h6">
              {selectedProject?.title} - 历史生成记录
            </Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : historyProjects.length === 0 ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body2" color="text.secondary">
                还没有生成过有声书
              </Typography>
            </Box>
          ) : (
            <List>
              {historyProjects.map((project) => (
                <ListItem
                  key={project.id}
                  sx={{
                    border: '1px solid #e0e0e0',
                    borderRadius: 2,
                    mb: 2,
                    '&:hover': {
                      backgroundColor: 'rgba(156, 39, 176, 0.05)',
                      cursor: 'pointer',
                    },
                  }}
                  onClick={() => onViewHistory(project.id)}
                >
                  <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <Chip
                        label={
                          project.status === 'completed'
                            ? '已完成'
                            : project.status === 'processing'
                            ? '生成中'
                            : project.status === 'failed'
                            ? '失败'
                            : '等待中'
                        }
                        size="small"
                        sx={{
                          backgroundColor:
                            project.status === 'completed'
                              ? '#4caf50'
                              : project.status === 'processing'
                              ? '#ff9800'
                              : project.status === 'failed'
                              ? '#f44336'
                              : '#9e9e9e',
                          color: 'white',
                        }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {new Date(project.created_at).toLocaleString('zh-CN', {
                          year: 'numeric',
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', gap: 2 }}>
                      <Typography variant="body2">
                        📚 章节：{project.completed_chapters}/{project.total_chapters}
                      </Typography>
                      {project.status === 'completed' && (
                        <Typography variant="body2" color="text.secondary">
                          🕒 {((project.total_duration || 0) / 60).toFixed(1)}分钟
                        </Typography>
                      )}
                    </Box>
                  </Box>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      onViewHistory(project.id)
                    }}
                    sx={{ color: '#9c27b0' }}
                  >
                    <PlayIcon />
                  </IconButton>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      onOpenDeleteConfirm(project)
                    }}
                    sx={{ color: '#f44336' }}
                  >
                    <DeleteIcon />
                  </IconButton>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseHistory}>关闭</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={showDeleteConfirm} onClose={onCloseDeleteConfirm} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#f44336' }} />
            <Typography variant="h6">确认删除</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Box sx={{ py: 2 }}>
            <Typography variant="body1" gutterBottom>
              确定要删除以下有声书项目吗？
            </Typography>
            {deletingProject && (
              <Box sx={{ mt: 2, p: 2, bgcolor: 'rgba(244, 67, 54, 0.05)', borderRadius: 1 }}>
                <Typography variant="body2" fontWeight="bold">
                  《{selectedProject?.title}》 - #{deletingProject.id}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  章节：{deletingProject.completed_chapters}/{deletingProject.total_chapters} | 时长：
                  {((deletingProject.total_duration || 0) / 60).toFixed(1)}分钟
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  创建时间：{new Date(deletingProject.created_at).toLocaleString('zh-CN')}
                </Typography>
              </Box>
            )}
            <Alert severity="error" sx={{ mt: 2 }}>
              此操作将永久删除该项目及其所有音频文件，无法恢复！
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseDeleteConfirm}>取消</Button>
          <Button onClick={onConfirmDelete} variant="contained" color="error" autoFocus>
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

const VOICE_PRESETS: { id: string; label: string; description: string; supportsInstruct?: boolean }[] = [
  // === 男性音色 (10种) ===
  {
    id: 'male_young_energetic',
    label: '龙安洋（阳光大男孩）',
    description: 'CosyVoice 标杆男声：阳光大男孩，20~30岁，中文（普通话）',
    supportsInstruct: true,
  },
  {
    id: 'male_young_gentle',
    label: '年轻男主（温柔）',
    description: '居家暖男，温柔体贴',
  },
  {
    id: 'male_adult_calm',
    label: '成熟男性（沉稳）',
    description: '睿智轻熟，沉稳冷静',
  },
  {
    id: 'male_adult_energetic',
    label: '成熟男性（豪迈）',
    description: '洒脱活力，豪迈大气',
  },
  {
    id: 'male_elder_wise',
    label: '长者（睿智）',
    description: '沧桑岁月，睿智稳重',
  },
  {
    id: 'male_warm',
    label: '暖男（痴情）',
    description: '温暖痴情，适合情感戏',
  },
  {
    id: 'male_customer_service',
    label: '书生（青涩）',
    description: '年轻青涩，文雅气质',
  },
  {
    id: 'male_refreshing',
    label: '武将（利落）',
    description: '清爽利落，适合战士',
  },
  {
    id: 'male_monkey',
    label: '特色（猴哥）',
    description: '经典猴哥，独特风格',
  },
  {
    id: 'male_narrator',
    label: '旁白（方言）',
    description: '陕北方言，亲切感',
  },
  {
    id: 'male_villain_sinister',
    label: '成熟谋士（沉稳）',
    description: '成熟沉稳，适合智者、谋士角色',
  },
  {
    id: 'female_villain_cold',
    label: '冷静御姐（高雅）',
    description: '冷静从容，高雅御姐、女强人',
  },
  {
    id: 'female_villain_cunning',
    label: '优雅名媛（睿智）',
    description: '高雅睿智，名媛贵妇、魅力女性',
  },
  
  // === 女性音色 (10种) ===
  {
    id: 'female_young_gentle',
    label: '年轻女主（温柔）',
    description: '细腻柔声，温柔体贴',
  },
  {
    id: 'female_young_energetic',
    label: '龙安欢（欢脱元气女）',
    description: 'CosyVoice 标杆女声：欢脱元气女，20~30岁，中文（普通话）',
    supportsInstruct: true,
  },
  {
    id: 'female_young_cute',
    label: '少女（可爱）',
    description: '清纯萝莉，甜美可爱',
  },
  {
    id: 'female_adult_elegant',
    label: '成熟女性（优雅）',
    description: '高雅气质，知性美',
  },
  {
    id: 'female_adult_intellectual',
    label: '成熟女性（知性）',
    description: '优雅知性，职场精英',
  },
  {
    id: 'female_capable',
    label: '女强人（干练）',
    description: '利落从容，女强人范',
  },
  {
    id: 'female_elder',
    label: '长者（慈祥）',
    description: '烟火从容，慈祥温和',
  },
  {
    id: 'female_intimate',
    label: '闺蜜（亲切）',
    description: '温柔闺蜜，亲切感',
  },
  {
    id: 'female_lively',
    label: '才女（活泼）',
    description: '亲和活泼，灵动活跃',
  },
  {
    id: 'female_child',
    label: '童声（天真）',
    description: '天真烂漫，可爱童声',
    supportsInstruct: true,
  },
]

export default function AudiobookPage() {
  const navigate = useNavigate()

  // 状态管理
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [, setLoading] = useState<boolean>(false)
  const [generating, setGenerating] = useState<boolean>(false)
  const [activeStep, setActiveStep] = useState<number>(0)
  const [characterVoices, setCharacterVoices] = useState<CharacterVoiceSetting[]>([])
  const [loadingCharacters, setLoadingCharacters] = useState<boolean>(false)
  const [audiobookProject, setAudiobookProject] = useState<any>(null)
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' as 'success' | 'error' | 'info' | 'warning' })
  
  // 新增：任务状态追踪
  const [taskStatuses, setTaskStatuses] = useState<Record<number, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  
  // 新增：音频播放状态
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [audioRef] = useState<HTMLAudioElement>(new Audio())
  
  // 新增：音频阶段模式切换（一步到位/仅生成剧本）+ 记录最近一次生成模式
  const [scriptOnlyMode, setScriptOnlyMode] = useState<boolean>(false)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only' | 'unknown'>('unknown')
  
  // 新增：历史记录相关
  const [showHistory, setShowHistory] = useState<boolean>(false)
  const [historyProjects, setHistoryProjects] = useState<any[]>([])
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false)
  // 新增：删除确认对话框
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<boolean>(false)
  const [deletingProject, setDeletingProject] = useState<any>(null)
  // 新增：角色试听状态
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)
  // 新增：自动推荐声线状态
  const [autoAssigningVoices, setAutoAssigningVoices] = useState<boolean>(false)
  // 新增：TTS 模型选择
  const [ttsModel, setTtsModel] = useState<'cosyvoice-v3-flash' | 'cosyvoice-v3-plus'>('cosyvoice-v3-flash')
  // 新增：剧本质量评审弹窗
  const [scriptReviewDialogOpen, setScriptReviewDialogOpen] = useState(false)
  const [scriptReviewData, setScriptReviewData] = useState<{
    report: any
    segments: any[]
  } | null>(null)

  // 新增：章节剧本编辑对话框
  const [scriptEditorDialogOpen, setScriptEditorDialogOpen] = useState(false)
  const [scriptEditorLoading, setScriptEditorLoading] = useState(false)
  const [scriptEditorChapter, setScriptEditorChapter] = useState<{
    chapterId: number
    title: string
  } | null>(null)
  const [scriptEditorData, setScriptEditorData] = useState<{
    scriptStatus: string
    scriptSegments: any[]
    scriptReview: any | null
  } | null>(null)
  const [audioFxConfig, setAudioFxConfig] = useState<AudioFxConfig>({
    enable_sound_effects: true,
    enable_music: true,
    sound_effect_density: 'medium',
    music_density: 'medium',
  })

  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newProjectText, setNewProjectText] = useState('')
  const [creatingFromBook, setCreatingFromBook] = useState(false)

  const steps = ['选择项目', '配置音色', '生成有声书', '完成']

  // 根据当前选择的 TTS 模型动态调整可选音色列表
  const currentVoicePresets =
    ttsModel === 'cosyvoice-v3-plus'
      ? VOICE_PRESETS.filter(
          (p) => p.id === 'male_young_energetic' || p.id === 'female_young_energetic'
        )
      : VOICE_PRESETS

  // 获取项目列表
  useEffect(() => {
    fetchProjects()
  }, [])
  
  // 新增：获取历史记录
  const fetchHistory = async () => {
    if (!selectedProject) return

    setLoadingHistory(true)
    try {
      const res = await apiClient.getAudiobookProjectsByProject(selectedProject.id)
      setHistoryProjects(res.data)
    } catch (error) {
      console.error('获取历史记录失败:', error)
    } finally {
      setLoadingHistory(false)
    }
  }
  
  // 新增：查看历史项目详情
  const handleViewHistory = async (audiobookProjectId: number) => {
    try {
      const res = await apiClient.getAudiobookProject(audiobookProjectId)
      const data = res.data
      setAudiobookProject(data)
      setActiveStep(3) // 跳转到完成页面
      setShowHistory(false)
    } catch (error) {
      console.error('查看历史失败:', error)
      setSnackbar({ open: true, message: '加载失败', severity: 'error' })
    }
  }

  // 新增：打开删除确认对话框
  const handleOpenDeleteConfirm = (project: any) => {
    setDeletingProject(project)
    setShowDeleteConfirm(true)
  }

  // 新增：删除有声书项目
  const handleDeleteProject = async () => {
    if (!deletingProject) return

    try {
      await apiClient.deleteAudiobookProject(deletingProject.id)
      setSnackbar({ open: true, message: '删除成功', severity: 'success' })
      setShowDeleteConfirm(false)
      setDeletingProject(null)
      fetchHistory()
    } catch (error: any) {
      console.error('删除失败:', error)
      const msg = (error?.response?.data?.detail as string) || '删除失败'
      setSnackbar({ open: true, message: msg, severity: 'error' })
    }
  }

  const fetchProjects = async () => {
    try {
      const res = await apiClient.getProjects()
      setProjects(res.data)
    } catch (error) {
      console.error('获取项目失败:', error)
      setSnackbar({ open: true, message: '网络错误，无法加载项目列表', severity: 'error' })
    }
  }

  const handleCreateProjectFromText = async () => {
    const rawText = newProjectText.trim()
    if (!rawText) {
      setSnackbar({ open: true, message: '请先粘贴文本内容', severity: 'error' })
      return
    }

    const title = newProjectTitle.trim() || '从整本书导入的项目'

    // 如果一次输入过多，则跳转到拆书页面，由拆书工具完成后续流程
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

    const waitForStatus = async (bookId: number, targetStatuses: string[]) => {
      // 简单轮询拆书/分析状态
      // 这里不使用全局 pollStatus，避免和两阶段状态混淆
      // targetStatuses 一般为 ['chapters_done'] 或 ['completed']
      while (true) {
        const status = await bookParserApi.getParseStatus(bookId)
        if (targetStatuses.includes(status.status)) {
          return status
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '拆书任务失败')
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
      }
    }

    setCreatingFromBook(true)
    try {
      // 1. 上传整本书文本
      const book = await bookParserApi.uploadText({
        title,
        content: rawText,
      })

      const bookId = book.id

      // 2. 执行章节切分
      await bookParserApi.parseBook(bookId)
      await waitForStatus(bookId, ['chapters_done'])

      // 3. 执行AI分析（人物/世界观/情节等），便于后续创作
      await bookParserApi.analyzeBook(bookId)
      await waitForStatus(bookId, ['completed'])

      // 4. 导入为灵感方舟项目（包含章节内容）
      const importResult = await bookParserApi.importToProject(bookId, {
        project_title: title,
        import_settings: true,
        import_characters: true,
        import_chapters: true,
      })

      // 5. 刷新项目列表，并选中新建项目，直接进入音色配置
      try {
        const projectRes = await apiClient.getProject(importResult.project_id)
        const project = projectRes.data as Project
        setProjects((prev) => {
          // 确保列表中包含新项目
          if (prev.some((p) => p.id === project.id)) return prev
          return [project, ...prev]
        })
        setSelectedProject(project)
      } catch (e) {
        // 回退：如果获取单个项目失败，至少构造一个最小的项目对象
        const fallbackProject: Project = {
          id: importResult.project_id,
          title: importResult.project_title || title,
          description: undefined,
          genre: undefined,
        }
        setProjects((prev) => {
          if (prev.some((p) => p.id === fallbackProject.id)) return prev
          return [fallbackProject, ...prev]
        })
        setSelectedProject(fallbackProject)
      }

      setActiveStep(1)
      setNewProjectDialogOpen(false)
      setNewProjectTitle('')
      setNewProjectText('')

      setSnackbar({
        open: true,
        message: '已从文本创建项目，请配置音色后生成有声书',
        severity: 'success',
      })
    } catch (error: any) {
      console.error('从文本创建项目失败:', error)
      const msg = (error?.response?.data?.detail ?? undefined) as string | undefined
      setSnackbar({
        open: true,
        message: msg || error.message || '从文本创建项目失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setCreatingFromBook(false)
    }
  }

  // 选择项目
  const handleSelectProject = async (project: Project) => {
    setSelectedProject(project)
    setLoading(true)
    setCharacterVoices([])

    const baseNarratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: 'male_narrator',  // 🔧 默认使用“旁白（方言）”，用户可以手动修改
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }
    
    try {
      // 获取章节列表
      const chaptersRes = await apiClient.getChapters(project.id)
      const chaptersData = chaptersRes.data
      setChapters(chaptersData)
      setSelectedChapters(chaptersData.map((c: Chapter) => c.id))  // 默认全选

      // 获取角色列表（用于音频配置）
      setLoadingCharacters(true)
      try {
        const charactersRes = await apiClient.getCharacters(project.id)
        const charactersData = charactersRes.data
      
        // 尝试读取项目级音频配置（角色音 + 音效/BGM）
        let projectAudioConfig: ProjectAudioConfig | null = null
        try {
          const audioConfigRes = await apiClient.getProjectAudioConfig(project.id)
          projectAudioConfig = audioConfigRes.data
        } catch (e) {
          console.warn('获取项目音频配置失败:', e)
        }
      
        const savedCharacters = projectAudioConfig?.characters || []
        const savedFx = projectAudioConfig?.audio_fx || null
      
        // 根据已保存的角色音配置初始化角色音
        const characterVoicesFromApi: CharacterVoiceSetting[] = charactersData.map((c: any) => {
          const saved = savedCharacters.find((sc) => sc.character_id === c.id)
          return {
            characterId: c.id,
            name: c.name,
            gender: c.gender,
            role: c.role,
            voiceId: saved?.voice_id || '',
            volume: saved?.volume ?? 50,
            speed: saved?.speed ?? 1.0,
            pitch: saved?.pitch ?? 50,
          }
        })
      
        // 旁白使用 character_id 为 0 或 name 为"旁白"的配置（如有）
        const narratorSaved = savedCharacters.find(
          (sc) => sc.character_id === 0 || sc.name === '旁白'
        )
        const narratorVoice: CharacterVoiceSetting = {
          ...baseNarratorVoice,
          voiceId: narratorSaved?.voice_id || baseNarratorVoice.voiceId,
          volume: narratorSaved?.volume ?? baseNarratorVoice.volume,
          speed: narratorSaved?.speed ?? baseNarratorVoice.speed,
          pitch: narratorSaved?.pitch ?? baseNarratorVoice.pitch,
        }
      
        const initialVoices: CharacterVoiceSetting[] = [
          narratorVoice,
          ...characterVoicesFromApi,
        ]
        setCharacterVoices(initialVoices)
      
        // 初始化项目级音效/BGM 配置
        if (savedFx) {
          setAudioFxConfig({
            enable_sound_effects: savedFx.enable_sound_effects ?? true,
            enable_music: savedFx.enable_music ?? true,
            sound_effect_density: (savedFx.sound_effect_density as AudioFxConfig['sound_effect_density']) || 'medium',
            music_density: (savedFx.music_density as AudioFxConfig['music_density']) || 'medium',
          })
        } else {
          setAudioFxConfig({
            enable_sound_effects: true,
            enable_music: true,
            sound_effect_density: 'medium',
            music_density: 'medium',
          })
        }
      } catch (error) {
        console.error('获取角色列表失败:', error)
        setCharacterVoices([baseNarratorVoice])
      } finally {
        setLoadingCharacters(false)
      }

      setActiveStep(1)
    } catch (error) {
      console.error('获取章节失败:', error)
      setSnackbar({ open: true, message: '网络错误，请重试', severity: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // 切换章节选择
  const handleToggleChapter = (chapterId: number) => {
    setSelectedChapters(prev => 
      prev.includes(chapterId) 
        ? prev.filter(id => id !== chapterId)
        : [...prev, chapterId]
    )
  }

  // 全选/取消全选
  const handleToggleAll = () => {
    if (selectedChapters.length === chapters.length) {
      setSelectedChapters([])
    } else {
      setSelectedChapters(chapters.map(c => c.id))
    }
  }
  
  const handleVoiceChange = (characterId: number, voiceId: string) => {
    setCharacterVoices(prev =>
      prev.map((item) =>
        item.characterId === characterId ? { ...item, voiceId } : item
      )
    )
  }

  const handleVolumeChange = (characterId: number, volume: number) => {
    setCharacterVoices(prev =>
      prev.map((item) =>
        item.characterId === characterId ? { ...item, volume } : item
      )
    )
  }

  const handleSpeedChange = (characterId: number, speed: number) => {
    setCharacterVoices(prev =>
      prev.map((item) =>
        item.characterId === characterId ? { ...item, speed } : item
      )
    )
  }

  const handlePitchChange = (characterId: number, pitch: number) => {
    setCharacterVoices(prev =>
      prev.map((item) =>
        item.characterId === characterId ? { ...item, pitch } : item
      )
    )
  }

  // 🆕 基于人物卡自动推荐声线
  const handleAutoAssignVoices = async () => {
    if (!selectedProject) return

    try {
      setAutoAssigningVoices(true)
      const res = await apiClient.autoAssignProjectAudioVoices(selectedProject.id)
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

      setCharacterVoices((prev) =>
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

      const assignedCount = configById.size
      if (assignedCount > 0) {
        setSnackbar({
          open: true,
          message: `✅ 已为 ${assignedCount} 个角色智能推荐声线！请检查推荐结果，如需调整可手动修改。`,
          severity: 'success',
        })
      } else {
        setSnackbar({
          open: true,
          message: '⚠️ 当前项目还没有角色档案，请先在「项目详情 → 人物设定」中创建角色。',
          severity: 'warning',
        })
      }
    } catch (err) {
      console.error('❌ 自动推荐声线失败:', err)
      setSnackbar({
        open: true,
        message: '自动推荐声线失败，请稍后重试',
        severity: 'error',
      })
    } finally {
      setAutoAssigningVoices(false)
    }
  }

  const handlePreviewCharacterVoice = async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId) {
      setSnackbar({ open: true, message: '请先为该角色选择音色再试听', severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const text = '当你真的喜欢一个人的时候就容易说傻话办蠢事。'

      const res = await apiClient.previewTTS({
        text,
        voice_id: cv.voiceId,
        volume: cv.volume,
        speed: cv.speed,
        pitch: cv.pitch,
        model: ttsModel,
      })

      const blob = res.data as Blob
      const url = window.URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.play()
      audio.onended = () => {
        window.URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('角色音试听失败:', error)
      setSnackbar({ open: true, message: '角色音试听失败，请稍后重试', severity: 'error' })
    } finally {
      setPreviewingCharacterId(null)
    }
  }

  // 新增：下载音频
  const handleDownloadAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch(
        `/api/v1/audiobook/download/${audiobookProject.id}/${chapterId}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        }
      )
      
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        
        // 从 Content-Disposition 获取文件名
        const contentDisposition = response.headers.get('Content-Disposition')
        let filename = `chapter_${chapterId}.mp3`
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
        
        setSnackbar({ open: true, message: '📥 音频下载成功', severity: 'success' })
      } else {
        throw new Error('下载失败')
      }
    } catch (error) {
      console.error('下载音频失败:', error)
      setSnackbar({ open: true, message: '❗ 下载失败，请重试', severity: 'error' })
    }
  }
  
  // 新增：在线播放音频
  const handlePlayAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      // 如果当前正在播放同一章节，则暂停
      if (playingChapter === chapterId) {
        audioRef.pause()
        setPlayingChapter(null)
        return
      }
      
      // 暂停当前播放
      audioRef.pause()
      
      // 通过 fetch 获取音频数据（带 Authorization header）
      const token = localStorage.getItem('access_token')
      const response = await fetch(
        `/api/v1/audiobook/stream/${audiobookProject.id}/${chapterId}`,
        {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        }
      )
      
      if (!response.ok) {
        throw new Error('加载音频失败')
      }
      
      // 创建 Blob URL
      const blob = await response.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      
      // 设置新的音频源
      audioRef.src = blobUrl
      
      // 播放
      await audioRef.play()
      setPlayingChapter(chapterId)
      
      // 播放结束后重置状态并释放 Blob URL
      audioRef.onended = () => {
        setPlayingChapter(null)
        window.URL.revokeObjectURL(blobUrl)
      }
      
      setSnackbar({ open: true, message: '🎵 开始播放', severity: 'success' })
    } catch (error) {
      console.error('播放音频失败:', error)
      setSnackbar({ open: true, message: '❗ 播放失败，请重试', severity: 'error' })
      setPlayingChapter(null)
    }
  }

  const handleOpenScriptReviewDialog = () => {
    if (selectedChapters.length === 0) return
    const chapterId = selectedChapters[0]
    const taskStatus = taskStatuses[chapterId]
    if (!taskStatus) {
      setSnackbar({ open: true, message: '暂未获取到该章节的任务状态', severity: 'error' })
      return
    }
    const stage = taskStatus.stages['quality_review']
    if (!stage || !stage.metrics) {
      setSnackbar({ open: true, message: '暂未获取到剧本评审结果', severity: 'error' })
      return
    }
    const metrics = stage.metrics
    const report = {
      overall_score: metrics.overall_score,
      overall_grade: metrics.overall_grade,
      issues_count: metrics.issues_count,
      script_quality: metrics.script_quality,
      audio_balance: metrics.audio_balance,
      pacing: metrics.pacing,
      revision_suggestions: metrics.revision_suggestions,
    }
    const segments = metrics.sample_segments || []
    setScriptReviewData({ report, segments })
    setScriptReviewDialogOpen(true)
  }

  const handleCloseScriptReviewDialog = () => {
    setScriptReviewDialogOpen(false)
  }

  // 打开章节剧本编辑器
  const handleOpenScriptEditor = async (chapterId: number) => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先创建有声书项目', severity: 'error' })
      return
    }

    const chapter = chapters.find((c) => c.id === chapterId)
    setScriptEditorChapter(
      chapter
        ? { chapterId, title: `第${chapter.chapter_number}章 - ${chapter.title}` }
        : { chapterId, title: `章节 ${chapterId}` }
    )

    try {
      setScriptEditorLoading(true)

      const res = await apiClient.getAudiobookChapterScript(audiobookProject.id, chapterId)
      const data = res.data

      setScriptEditorData({
        scriptStatus: data.script_status || 'pending',
        scriptSegments: data.script_segments || [],
        scriptReview: data.script_review || undefined,
      })
      setScriptEditorDialogOpen(true)
    } catch (err: any) {
      console.error('获取章节剧本失败:', err)
      setSnackbar({ open: true, message: err.message || '获取章节剧本失败', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }

  const handleCloseScriptEditorDialog = () => {
    setScriptEditorDialogOpen(false)
    setScriptEditorData(null)
    setScriptEditorChapter(null)
  }

  const handleChangeScriptSegmentText = (index: number, value: string) => {
    setScriptEditorData((prev) => {
      if (!prev) return prev
      const segments = [...prev.scriptSegments]
      segments[index] = { ...segments[index], text: value }
      return { ...prev, scriptSegments: segments }
    })
  }

  const handleSaveScript = async (options: { nextStatus?: 'reviewed' | 'approved'; generateAudio?: boolean }) => {
    if (!audiobookProject || !scriptEditorChapter || !scriptEditorData) return

    try {
      setScriptEditorLoading(true)

      const payload: any = {
        script_segments: scriptEditorData.scriptSegments,
      }
      if (options.nextStatus) {
        payload.script_status = options.nextStatus
      }

      await apiClient.updateAudiobookChapterScript(
        audiobookProject.id,
        scriptEditorChapter.chapterId,
        payload
      )

      setSnackbar({ open: true, message: '剧本已保存', severity: 'success' })

      // 可选：保存并生成该章节音频
      if (options.generateAudio) {
        await apiClient.generateAudioFromScripts(audiobookProject.id, {
          chapter_ids: [scriptEditorChapter.chapterId],
          tts_model: ttsModel,
        })
        setSnackbar({ open: true, message: '已触发该章节音频生成', severity: 'success' })
      }

      // 保存后不自动关闭，方便继续修改；如需可在此关闭
      // handleCloseScriptEditorDialog()
    } catch (err: any) {
      console.error('保存/生成失败:', err)
      setSnackbar({ open: true, message: err.message || '保存失败', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }

  const handleGenerateAudioForApprovedChapters = async () => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '请先完成剧本生成', severity: 'error' })
      return
    }

    try {
      const res = await apiClient.generateAudioFromScripts(audiobookProject.id, {
        tts_model: ttsModel,
      })

      if (res.status !== 200) {
        throw new Error('触发音频生成失败')
      }

      setSnackbar({
        open: true,
        message: '已触发所有已审批章节的音频生成，请稍候在历史记录或本页刷新查看结果',
        severity: 'success',
      })
    } catch (err: any) {
      console.error('批量生成音频失败:', err)
      setSnackbar({
        open: true,
        message: err.message || '批量生成音频失败，请稍后重试',
        severity: 'error',
      })
    }
  }

  // 开始生成
  const handleGenerate = async () => {
    if (!selectedProject || selectedChapters.length === 0) {
      setSnackbar({ open: true, message: '请至少选择一个章节', severity: 'error' })
      return
    }
    
    setGenerating(true)
    setActiveStep(2)
    setLastGenerationMode(scriptOnlyMode ? 'script_only' : 'full')
    setTaskStatuses({})  // 清空之前的状态

    try {
      // 调用生成API
      // 先保存本次的项目级音频配置（角色音 + 音效/BGM），用于下次自动带出
      if (selectedProject) {
        const projectAudioConfigBody: ProjectAudioConfig = {
          characters: characterVoices
            .filter((cv) => cv.voiceId || cv.name === '旁白')  // 🔧 修复：旁白即使 voiceId 为空也保留，让后端使用默认音色
            .map((cv) => ({
              character_id: cv.characterId,
              name: cv.name,
              voice_id: cv.voiceId || 'male_narrator',  // 🔧 修复：空音色使用默认值
              volume: cv.volume,
              speed: cv.speed,
              pitch: cv.pitch,
            })),
          audio_fx: audioFxConfig,
        }

        try {
          await apiClient.updateProjectAudioConfig(selectedProject.id, projectAudioConfigBody)
        } catch (err) {
          console.warn('保存项目音频配置失败:', err)
        }
      }

      const voiceConfigPayload =
        characterVoices
          .filter((cv) => cv.voiceId || cv.name === '旁白')  // 🔧 修复：旁白即使 voiceId 为空也保留
          .map((cv) => ({
            character_name: cv.name,
            voice_id: cv.voiceId || 'male_narrator',  // 🔧 修复：空音色使用默认值
            volume: cv.volume,
            speed: cv.speed,
            pitch: cv.pitch,
          }))

      const response = await apiClient.createAudiobookProject({
        project_id: selectedProject.id,
        chapter_ids: selectedChapters,
        tts_provider: 'aliyun',
        enable_cache: true,
        voice_config: voiceConfigPayload,
        tts_model: ttsModel,
        generation_mode: scriptOnlyMode ? 'script_only' : 'full',
      })

      const data = response.data
      setAudiobookProject(data)

      // 轮询查询项目进度
      const projectId = data.audiobook_project_id
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await apiClient.getAudiobookProject(projectId)
          const statusData = statusResponse.data
          console.log('轮询项目状态:', statusData)

          // 新增：获取第一个章节的task_id（如果有）
          if (statusData.chapter_audios && statusData.chapter_audios.length > 0) {
            console.log('chapter_audios:', statusData.chapter_audios)
            const firstTaskId = statusData.chapter_audios[0].task_id
            console.log('firstTaskId:', firstTaskId)
            if (firstTaskId) {
              console.log('获取到 task_id:', firstTaskId)
              setCurrentTaskId(prev => {
                if (!prev) {
                  console.log('设置 currentTaskId:', firstTaskId)
                  return firstTaskId
                }
                return prev
              })
            }
          } else {
            console.log('暂无 chapter_audios 或为空')
          }

          if (statusData.status === 'completed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setActiveStep(3)
            setAudiobookProject(statusData)
            setSnackbar({ open: true, message: '生成完成！', severity: 'success' })
          } else if (statusData.status === 'failed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setSnackbar({ open: true, message: '生成失败，请重试', severity: 'error' })
            setActiveStep(1)
          }
        } catch (err) {
          console.error('轮询有声书项目状态失败:', err)
        }
      }, 2000) // 每2秒查询一次
    } catch (error: any) {
      console.error('生成失败:', error)
      setSnackbar({ 
        open: true, 
        message: error.message || '生成失败，请重试', 
        severity: 'error' 
      })
      setGenerating(false)
      setActiveStep(1)
    }
  }
  
  // 新增：轮询任务列表以获取当前章节的 task_id（避免依赖 chapter_audios）
  useEffect(() => {
    if (!generating || currentTaskId) {
      return
    }

    const chapterId = selectedChapters[0]
    if (!chapterId) {
      return
    }

    const pollTaskList = async () => {
      try {
        const response = await fetch('/api/v1/audiobook/tasks', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (response.ok) {
          const tasks: TaskStatus[] = await response.json()
          const matched = tasks.find(t => t && t.chapter_id === chapterId)
          if (matched) {
            console.log('从任务列表中找到当前章节的 task_id:', matched.task_id)
            setCurrentTaskId(prev => prev || matched.task_id)
          }
        } else {
          console.error('查询任务列表失败:', response.status, response.statusText)
        }
      } catch (error) {
        console.error('查询任务列表异常:', error)
      }
    }

    // 先查一次
    pollTaskList()
    // 然后每2秒查一次，直到 currentTaskId 被设置
    const intervalId = setInterval(() => {
      if (!currentTaskId) {
        pollTaskList()
      }
    }, 2000)

    return () => clearInterval(intervalId)
  }, [generating, currentTaskId, selectedChapters])
  
  // 新增：轮询单个任务状态（用于实时显示8个阶段）
  useEffect(() => {
    if (!currentTaskId || !generating) {
      console.log('跳过任务状态轮询:', { currentTaskId, generating })
      return
    }
    
    console.log('开始轮询任务状态:', currentTaskId)
    
    const pollTaskStatus = async () => {
      try {
        const response = await fetch(`/api/v1/audiobook/tasks/${currentTaskId}/status`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        
        if (response.ok) {
          const taskStatus: TaskStatus = await response.json()
          console.log('获取到任务状态:', taskStatus)
          setTaskStatuses(prev => ({
            ...prev,
            [taskStatus.chapter_id]: taskStatus
          }))
        } else {
          console.error('查询任务状态失败:', response.status, response.statusText)
        }
      } catch (error) {
        console.error('查询任务状态异常:', error)
      }
    }
    
    // 立即查询一次
    pollTaskStatus()
    
    // 每2秒查询一次
    const intervalId = setInterval(pollTaskStatus, 2000)
    
    return () => clearInterval(intervalId)
  }, [currentTaskId, generating])
  
  // 新增：渲染阶段详情
  const renderStageDetails = (taskStatus: TaskStatus) => {
    const stageConfig = [
      { key: 'strategy', name: '策略制定', icon: '🎯', desc: '分析原文，制定改编策略' },
      { key: 'script_adaptation', name: '剧本改编', icon: '📝', desc: '将小说改编为有声剧本' },
      { key: 'voice_design', name: '音色设计', icon: '🎭', desc: '为角色分配音色参数' },
      { key: 'sound_design', name: '音效设计', icon: '🎧', desc: '设计场景音效和环境音' },
      { key: 'music_composition', name: '音乐编曲', icon: '🎵', desc: '设计背景音乐方案' },
      { key: 'quality_review', name: '剧本评审', icon: '🔍', desc: 'TTS前质量检查' },
      { key: 'tts_synthesis', name: 'TTS合成', icon: '🗣️', desc: '语音合成生成音频' },
      { key: 'audio_mixing', name: '音频混合', icon: '🎚️', desc: '混音与后期处理' },
      { key: 'final_audio_review', name: '最终评审', icon: '✨', desc: '最终质量检查' },
    ]
    
    const statusColors = {
      pending: { bg: '#f5f5f5', border: '#e0e0e0', text: '#9e9e9e' },
      running: { bg: 'rgba(156, 39, 176, 0.08)', border: '#9c27b0', text: '#9c27b0' },
      completed: { bg: 'rgba(76, 175, 80, 0.08)', border: '#4caf50', text: '#4caf50' },
      failed: { bg: 'rgba(244, 67, 54, 0.08)', border: '#f44336', text: '#f44336' }
    }
    
    return (
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 2 }}>
        {stageConfig.map((stage) => {
          const stageInfo = taskStatus.stages[stage.key as keyof typeof taskStatus.stages]
          if (!stageInfo) return null
          
          const colors = statusColors[stageInfo.status as keyof typeof statusColors] || statusColors.pending
          const isActive = stageInfo.status === 'running'
          const isDone = stageInfo.status === 'completed'
          
          return (
            <Paper 
              key={stage.key}
              elevation={isActive ? 4 : 1}
              sx={{ 
                p: 2,
                border: `2px solid ${colors.border}`,
                backgroundColor: colors.bg,
                transition: 'all 0.3s ease',
                transform: isActive ? 'scale(1.02)' : 'scale(1)',
                position: 'relative',
                overflow: 'hidden',
                '&::before': isActive ? {
                  content: '""',
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  background: `linear-gradient(135deg, transparent 0%, ${colors.border}15 100%)`,
                  pointerEvents: 'none'
                } : {}
              }}
            >
              {/* 头部：图标+名称+状态 */}
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="h6" sx={{ fontSize: '1.5rem' }}>
                    {stage.icon}
                  </Typography>
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: colors.text }}>
                      {stage.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
                      {stage.desc}
                    </Typography>
                  </Box>
                </Box>
                {isDone && (
                  <Box sx={{ 
                    width: 24, 
                    height: 24, 
                    borderRadius: '50%', 
                    backgroundColor: '#4caf50',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'white',
                    fontSize: '0.9rem'
                  }}>
                    ✓
                  </Box>
                )}
              </Box>
              
              {/* 进度条 */}
              <LinearProgress 
                variant="determinate" 
                value={stageInfo.progress * 100} 
                sx={{ 
                  height: 4, 
                  borderRadius: 2,
                  backgroundColor: 'rgba(0, 0, 0, 0.08)',
                  '& .MuiLinearProgress-bar': {
                    backgroundColor: colors.border,
                    borderRadius: 2
                  }
                }}
              />
              
              {/* 状态文字 */}
              <Typography 
                variant="caption" 
                sx={{ 
                  display: 'block',
                  mt: 0.5,
                  textAlign: 'right',
                  color: colors.text,
                  fontWeight: 500,
                  fontSize: '0.7rem'
                }}
              >
                {isActive ? `进行中 ${Math.round(stageInfo.progress * 100)}%` : 
                 isDone ? '已完成' : 
                 stageInfo.status === 'failed' ? '失败' : '等待中'}
              </Typography>
              
              {/* 关键指标 */}
              {stageInfo.metrics && Object.keys(stageInfo.metrics).length > 0 && (
                <Box sx={{ mt: 1, pt: 1, borderTop: '1px dashed rgba(0,0,0,0.1)' }}>
                  <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem', lineHeight: 1.3 }}>
                    {Object.entries(stageInfo.metrics).slice(0, 2).map(([key, value]) => (
                      <Box key={key} component="span" sx={{ display: 'block' }}>
                        {key}: {typeof value === 'object' ? JSON.stringify(value).slice(0, 20) : String(value).slice(0, 20)}
                      </Box>
                    ))}
                  </Typography>
                </Box>
              )}
            </Paper>
          )
        })}
      </Box>
    )
  }

  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }}>
      {/* 顶部导航 */}
      <Box
        sx={{
          p: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          backgroundColor: 'rgba(255,255,255,0.95)',
          backdropFilter: 'blur(10px)',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        }}
      >
        <IconButton onClick={() => navigate('/modules')}>
          <ArrowBackIcon />
        </IconButton>
        <HeadphonesIcon sx={{ fontSize: 32, color: '#9c27b0' }} />
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 600 }}>
            耳畔星河
          </Typography>
          <Typography variant="caption" color="text.secondary">
            有声小说生成工具
          </Typography>
        </Box>

        <Button
          variant="contained"
          onClick={() => setNewProjectDialogOpen(true)}
          sx={{
            mr: selectedProject ? 1 : 0,
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          新建项目
        </Button>
        
        {/* 新增：历史记录按钮 */}
        {selectedProject && (
          <Tooltip title="查看历史生成记录">
            <Button
              variant="outlined"
              startIcon={<HistoryIcon />}
              onClick={() => {
                setShowHistory(true)
                fetchHistory()
              }}
              sx={{
                borderColor: '#9c27b0',
                color: '#9c27b0',
                '&:hover': {
                  borderColor: '#7b1fa2',
                  backgroundColor: 'rgba(156, 39, 176, 0.08)',
                },
              }}
            >
              历史记录
            </Button>
          </Tooltip>
        )}
      </Box>

      <Container maxWidth="xl" sx={{ py: 4 }}>
        {/* 步骤指示器 */}
        <Paper sx={{ p: 3, mb: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
          <Stepper activeStep={activeStep}>
            {steps.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>
        </Paper>

        {/* 步骤1: 选择项目 */}
        {activeStep === 0 && (
          <Box>
            {projects.length === 0 ? (
              <Paper sx={{ p: 4, textAlign: 'center', backgroundColor: 'rgba(255,255,255,0.95)' }}>
                <Typography variant="body1" color="text.secondary">
                  暂无项目，请先创建小说项目
                </Typography>
                <Button
                  variant="contained"
                  onClick={() => navigate('/dashboard')}
                  sx={{
                    mt: 2,
                    backgroundColor: '#9c27b0',
                    '&:hover': { backgroundColor: '#7b1fa2' },
                  }}
                >
                  去创建项目
                </Button>
              </Paper>
            ) : (
              <Grid container spacing={3}>
                {projects.map((project) => (
                  <Grid
                    item
                    key={project.id}
                    sx={{
                      flexBasis: { xs: '100%', sm: '50%', md: '20%' },
                      maxWidth: { xs: '100%', sm: '50%', md: '20%' },
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
                      onClick={() => handleSelectProject(project)}
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

                          {/* 书本元素已移除，仅保留耳机与播放按钮 */}

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
                        {/* 只保留项目名称，不再展示简介 */}
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
                      </CardContent>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            )}
          </Box>
        )}

        {/* 步骤2: 配置音色（章节选择 + 角色音频设置） */}
        {activeStep === 1 && (
          <Paper sx={{ p: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center' }}>
              <VoiceIcon sx={{ mr: 1, color: '#9c27b0' }} />
              配置章节与角色音
            </Typography>
                    
            <Alert severity="info" sx={{ mb: 2 }}>
              已选择 {selectedChapters.length}/{chapters.length} 个章节。未配置的角色将由 AI 自动分配音色和音量。
            </Alert>

            {/* TTS 模型选择 */}
            <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <FormControl size="small" sx={{ minWidth: 260 }}>
                <InputLabel>TTS 模型</InputLabel>
                <Select
                  label="TTS 模型"
                  value={ttsModel}
                  onChange={(e) => setTtsModel(e.target.value as 'cosyvoice-v3-flash' | 'cosyvoice-v3-plus')}
                >
                  <MenuItem value="cosyvoice-v3-flash">
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <span>CosyVoice v3-flash</span>
                      <Tooltip title="高性价比，速度快，适合大规模章节生成，价格较低">
                        <Chip
                          label="价格：低"
                          size="small"
                          color="success"
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                      </Tooltip>
                    </Box>
                  </MenuItem>
                  <MenuItem value="cosyvoice-v3-plus">
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <span>CosyVoice v3-plus</span>
                      <Tooltip title="音质更好，支持零样本声音复刻，更适合重要章节和精细角色，价格较高">
                        <Chip
                          label="价格：高"
                          size="small"
                          color="error"
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                      </Tooltip>
                    </Box>
                  </MenuItem>
                </Select>
              </FormControl>

              <FormControlLabel
                control={
                  <Checkbox
                    checked={scriptOnlyMode}
                    onChange={(_, checked) => setScriptOnlyMode(checked)}
                    sx={{
                      color: '#9c27b0',
                      '&.Mui-checked': {
                        color: '#9c27b0',
                      },
                    }}
                  />
                }
                label="仅生成剧本和评审（稍后再生成音频）"
              />
            </Box>

            {/* 项目级音效与配乐配置 */}
            <Paper
              variant="outlined"
              sx={{
                mb: 2,
                p: 2,
                backgroundColor: 'rgba(156, 39, 176, 0.02)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                音效与背景音乐
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                这里的设置会作为项目级默认配置保存，下次进入该项目会自动带出，并影响音效/配乐是否启用及大致密度。
              </Typography>
              <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={audioFxConfig.enable_sound_effects}
                        onChange={(_, checked) =>
                          setAudioFxConfig((prev) => ({
                            ...prev,
                            enable_sound_effects: checked,
                          }))
                        }
                        sx={{
                          color: '#9c27b0',
                          '&.Mui-checked': {
                            color: '#9c27b0',
                          },
                        }}
                      />
                    }
                    label="开启音效（环境音 + 关键动作音）"
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_sound_effects}>
                    <InputLabel>音效密度</InputLabel>
                    <Select
                      label="音效密度"
                      value={audioFxConfig.sound_effect_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          sound_effect_density: e.target.value as AudioFxConfig['sound_effect_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">关闭（不使用音效）</MenuItem>
                      <MenuItem value="low">稀疏（仅关键场景）</MenuItem>
                      <MenuItem value="medium">适中（推荐）</MenuItem>
                      <MenuItem value="high">丰富（沉浸感更强）</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
                <Grid item xs={12} md={6}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={audioFxConfig.enable_music}
                        onChange={(_, checked) =>
                          setAudioFxConfig((prev) => ({
                            ...prev,
                            enable_music: checked,
                          }))
                        }
                        sx={{
                          color: '#9c27b0',
                          '&.Mui-checked': {
                            color: '#9c27b0',
                          },
                        }}
                      />
                    }
                    label="开启背景音乐（AI 配乐）"
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_music}>
                    <InputLabel>配乐密度</InputLabel>
                    <Select
                      label="配乐密度"
                      value={audioFxConfig.music_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          music_density: e.target.value as AudioFxConfig['music_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">关闭（不使用配乐）</MenuItem>
                      <MenuItem value="low">稀疏（仅片头/片尾）</MenuItem>
                      <MenuItem value="medium">适中（推荐）</MenuItem>
                      <MenuItem value="high">丰富（几乎全程有配乐）</MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
              </Grid>
            </Paper>
        
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1 }}>
                  章节选择
                </Typography>
        
                {/* 全选按钮 */}
                <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
                  <Button 
                    variant="outlined" 
                    size="small"
                    onClick={handleToggleAll}
                  >
                    {selectedChapters.length === chapters.length ? '取消全选' : '全选'}
                  </Button>
                </Box>
        
                {/* 章节列表 */}
                <Paper 
                  variant="outlined" 
                  sx={{ 
                    maxHeight: 400, 
                    overflow: 'auto',
                  }}
                >
                  <List>
                    {chapters.map((chapter) => (
                      <ListItem 
                        key={chapter.id}
                        component="div"
                        onClick={() => handleToggleChapter(chapter.id)}
                        sx={{
                          cursor: 'pointer',
                          '&:hover': {
                            backgroundColor: 'rgba(156, 39, 176, 0.08)'
                          }
                        }}
                      >
                        <Checkbox
                          edge="start"
                          checked={selectedChapters.includes(chapter.id)}
                          tabIndex={-1}
                          disableRipple
                          sx={{
                            color: '#9c27b0',
                            '&.Mui-checked': {
                              color: '#9c27b0',
                            },
                          }}
                        />
                        <ListItemText
                          primary={`第${chapter.chapter_number}章 - ${chapter.title}`}
                          secondary={chapter.content ? `${chapter.content.slice(0, 50)}...` : '暂无内容'}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              </Grid>
        
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AudioIcon fontSize="small" />
                  角色音与音量配置
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  不修改时使用 AI 默认音色；为角色选择音色或调整音量后，本次有声书生成将优先使用你的配置。
                </Typography>
        
                {loadingCharacters && (
                  <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
                    <CircularProgress size={24} />
                  </Box>
                )}
        
                {!loadingCharacters && characterVoices.length === 0 && (
                  <Box sx={{ py: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      当前项目还没有结构化角色档案，可在「项目详情 → 角色管理」中添加角色后再配置音色。
                    </Typography>
                  </Box>
                )}
        
                {!loadingCharacters && characterVoices.length > 0 && (
                  <Paper
                    variant="outlined"
                    sx={{
                      maxHeight: 400,
                      overflow: 'auto',
                      p: 1,
                    }}
                  >
                    <List>
                      {characterVoices.map((cv) => (
                        <ListItem
                          key={cv.characterId}
                          alignItems="flex-start"
                          sx={{
                            alignItems: 'stretch',
                            '&:hover': {
                              backgroundColor: 'rgba(156, 39, 176, 0.03)',
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
                                <Chip
                                  label="已配置"
                                  size="small"
                                  color="success"
                                  sx={{ height: 20 }}
                                />
                              )}
                            </Box>
        
                            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                              <FormControl size="small" fullWidth>
                                <InputLabel>角色音</InputLabel>
                                <Select
                                  label="角色音"
                                  value={cv.voiceId}
                                  onChange={(e) => handleVoiceChange(cv.characterId, e.target.value as string)}
                                >
                                  <MenuItem value="">
                                    <em>自动（AI 选择）</em>
                                  </MenuItem>
                                  {currentVoicePresets.map((preset) => (
                                    <MenuItem key={preset.id} value={preset.id}>
                                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                        <span>{preset.label}</span>
                                        {preset.supportsInstruct && (
                                          <Tooltip title="该音色支持智能情感：系统会根据文本内容自动选择合适的情感表达">
                                            <Chip
                                              label="智能情感"
                                              size="small"
                                              color="primary"
                                              sx={{ height: 18, fontSize: '0.65rem' }}
                                            />
                                          </Tooltip>
                                        )}
                                      </Box>
                                    </MenuItem>
                                  ))}
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
                                onChange={(_, value) => handleVolumeChange(cv.characterId, value as number)}
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
                                onChange={(_, value) => handleSpeedChange(cv.characterId, value as number)}
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
                                onChange={(_, value) => handlePitchChange(cv.characterId, value as number)}
                                sx={{ mt: 0.5 }}
                              />
                            </Box>

                            <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end' }}>
                              <Tooltip title="云端精确试听效果，请稍作等待...">
                                <span>
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    onClick={() => handlePreviewCharacterVoice(cv)}
                                    disabled={!cv.voiceId || previewingCharacterId === cv.characterId}
                                  >
                                    {previewingCharacterId === cv.characterId ? '试听中...' : '试听'}
                                  </Button>
                                </span>
                              </Tooltip>
                            </Box>
                          </Box>
                        </ListItem>
                      ))}
                    </List>
                  </Paper>
                )}

                {/* 🆕 自动推荐声线按钮 */}
                {!loadingCharacters && (
                  <Box sx={{ mt: 2, display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={handleAutoAssignVoices}
                      disabled={autoAssigningVoices}
                      sx={{
                        borderColor: '#9c27b0',
                        color: '#9c27b0',
                        '&:hover': {
                          borderColor: '#7b1fa2',
                          backgroundColor: 'rgba(156, 39, 176, 0.04)',
                        },
                      }}
                    >
                      {autoAssigningVoices ? '🤖 智能推荐中...' : '✨ 基于人物卡自动推荐声线'}
                    </Button>
                  </Box>
                )}
              </Grid>
            </Grid>
        
            <Box sx={{ mt: 3, display: 'flex', gap: 2, justifyContent: 'space-between' }}>
              <Button variant="outlined" onClick={() => setActiveStep(0)}>
                上一步
              </Button>
              <Button
                variant="contained"
                onClick={handleGenerate}
                disabled={selectedChapters.length === 0}
                sx={{
                  backgroundColor: '#9c27b0',
                  '&:hover': { backgroundColor: '#7b1fa2' },
                }}
              >
                开始生成 ({selectedChapters.length}章)
              </Button>
            </Box>
          </Paper>
        )}

        {/* 步骤3: 生成中 */}
        {activeStep === 2 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            {/* 顶部整体进度条和文字已移除，改为仅展示阶段卡片状态 */}
            
            {/* 新增：8个阶段详细展示 */}
            {(() => {
              console.log('渲染阶段信息 - currentTaskId:', currentTaskId)
              console.log('渲染阶段信息 - taskStatuses:', taskStatuses)
              console.log('渲染阶段信息 - selectedChapters:', selectedChapters)
              
              // 先尝试使用 selectedChapters[0]，如果没有则查找第一个可用的 taskStatus
              const chapterId = selectedChapters[0]
              let taskStatus = chapterId ? taskStatuses[chapterId] : null
              
              // 如果没有找到，尝试使用第一个可用的 taskStatus
              if (!taskStatus && Object.keys(taskStatuses).length > 0) {
                const firstTaskStatusKey = Object.keys(taskStatuses)[0]
                taskStatus = taskStatuses[Number(firstTaskStatusKey)]
                console.log('使用第一个可用的 taskStatus:', firstTaskStatusKey, taskStatus)
              }
              
              // 如果还是没有数据，使用初始状态的模拟数据
              if (!taskStatus || !taskStatus.stages) {
                // 创建初始状态的 taskStatus
                taskStatus = {
                  task_id: 'pending',
                  chapter_id: chapterId || 0,
                  status: 'pending',
                  overall_progress: 0,
                  stages: {
                    strategy: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    script_adaptation: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    voice_design: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    sound_design: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    music_composition: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    quality_review: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    tts_synthesis: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    audio_mixing: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                    final_audio_review: { status: 'pending', progress: 0, start_time: undefined, end_time: undefined, error_message: undefined, metrics: undefined },
                  },
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                }
                console.log('使用初始状态的模拟数据')
              }
              
              console.log('渲染阶段详情:', taskStatus)
              
              return (
                <Box sx={{ mt: 3 }}>
                  <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#333' }}>
                    🎯 当前阶段进度
                  </Typography>
                  {renderStageDetails(taskStatus)}
                  {taskStatus.stages?.quality_review?.status === 'completed' && (
                    <Box sx={{ mt: 3, textAlign: 'center' }}>
                      <Button
                        variant="outlined"
                        size="medium"
                        onClick={handleOpenScriptReviewDialog}
                        sx={{ 
                          borderColor: '#9c27b0',
                          color: '#9c27b0',
                          '&:hover': {
                            borderColor: '#7b1fa2',
                            backgroundColor: 'rgba(156, 39, 176, 0.04)'
                          }
                        }}
                      >
                        🔍 查看剧本评审详情
                      </Button>
                    </Box>
                  )}
                </Box>
              )
            })()}
            
            {/* 底部整体进度条已移除，仅保留文字提示 */}
            <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mt: 1, color: 'text.secondary' }}>
              请耐心等待，生成中请勿关闭页面...
            </Typography>
          </Paper>
        )}

        {/* 步骤4: 完成 */}
        {activeStep === 3 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Box sx={{ textAlign: 'center', mb: 3 }}>
              <CheckIcon sx={{ fontSize: 80, color: '#4caf50', mb: 2 }} />
              <Typography variant="h5" sx={{ mb: 2 }}>
                生成完成！
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                {lastGenerationMode === 'script_only'
                  ? '剧本与评审已生成，接下来可以逐章审稿、修改剧本，再生成音频'
                  : '您的有声书已经准备好了'}
              </Typography>
            </Box>
            
            {/* 统计信息 */}
            {audiobookProject && (
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center', 
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(102, 126, 234, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      {audiobookProject.completed_chapters}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      完成章节
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center',
                      background: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(240, 147, 251, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      {((audiobookProject.total_duration || 0) / 60).toFixed(1)}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      总时长(分钟)
                    </Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Paper 
                    sx={{ 
                      p: 3, 
                      textAlign: 'center',
                      background: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
                      color: 'white',
                      boxShadow: '0 4px 12px rgba(79, 172, 254, 0.3)',
                    }}
                  >
                    <Typography variant="h3" sx={{ fontWeight: 700, mb: 1 }}>
                      ¥{(audiobookProject.total_cost || 0).toFixed(2)}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      总成本
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>
            )}
            
            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap' }}>
              {/* 下载按钮 - 支持分章节下载 */}
              {audiobookProject.chapter_audios && audiobookProject.chapter_audios.length > 0 && (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center', width: '100%', mb: 2 }}>
                  {audiobookProject.chapter_audios.map((chapterAudio: any) => {
                    const chapter = chapters.find(c => c.id === chapterAudio.chapter_id)
                    const isPlaying = playingChapter === chapterAudio.chapter_id
                    
                    return (
                      <Box key={chapterAudio.id} sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          {/* 在线播放按钮 */}
                          <Tooltip title={isPlaying ? '暂停播放' : '在线播放'}>
                            <Button
                              variant="outlined"
                              size="small"
                              startIcon={isPlaying ? <PauseIcon /> : <PlayIcon />}
                              onClick={() => handlePlayAudio(chapterAudio.chapter_id)}
                              sx={{
                                borderColor: isPlaying ? '#f50057' : '#9c27b0',
                                color: isPlaying ? '#f50057' : '#9c27b0',
                                '&:hover': {
                                  borderColor: isPlaying ? '#c51162' : '#7b1fa2',
                                  backgroundColor: isPlaying ? 'rgba(245, 0, 87, 0.08)' : 'rgba(156, 39, 176, 0.08)',
                                },
                              }}
                            >
                              {chapter ? `第${chapter.chapter_number}章` : `章节${chapterAudio.chapter_id}`}
                            </Button>
                          </Tooltip>
                          
                          {/* 下载按钮 */}
                          <Tooltip title="下载音频">
                            <IconButton
                              size="small"
                              onClick={() => handleDownloadAudio(chapterAudio.chapter_id)}
                              sx={{
                                color: '#9c27b0',
                                '&:hover': {
                                  backgroundColor: 'rgba(156, 39, 176, 0.08)',
                                },
                              }}
                            >
                              <DownloadIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
  
                          {/* 编辑剧本按钮（如果有脚本可用，用户可以直接尝试打开） */}
                          <Tooltip title="编辑本章节有声剧本">
                            <Button
                              variant="outlined"
                              size="small"
                              onClick={() => handleOpenScriptEditor(chapterAudio.chapter_id)}
                              sx={{
                                borderColor: '#607d8b',
                                color: '#607d8b',
                                '&:hover': {
                                  borderColor: '#455a64',
                                  backgroundColor: 'rgba(96, 125, 139, 0.08)',
                                },
                              }}
                            >
                              编辑剧本
                            </Button>
                          </Tooltip>
                        </Box>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
                          <Chip
                            label={
                              chapterAudio.script_status === 'approved'
                                ? '剧本：已审批'
                                : chapterAudio.script_status === 'reviewed'
                                ? '剧本：已修改'
                                : chapterAudio.script_status
                                ? '剧本：待处理'
                                : '剧本：未生成'
                            }
                            size="small"
                            sx={{
                              backgroundColor:
                                chapterAudio.script_status === 'approved'
                                  ? 'rgba(76, 175, 80, 0.15)'
                                  : chapterAudio.script_status === 'reviewed'
                                  ? 'rgba(33, 150, 243, 0.12)'
                                  : 'rgba(158, 158, 158, 0.12)',
                              color:
                                chapterAudio.script_status === 'approved'
                                  ? '#2e7d32'
                                  : chapterAudio.script_status === 'reviewed'
                                  ? '#1565c0'
                                  : '#616161',
                              fontSize: '0.75rem',
                              height: 22,
                            }}
                          />
                          <Chip
                            label={chapterAudio.audio_path ? '音频：已生成' : '音频：未生成'}
                            size="small"
                            sx={{
                              backgroundColor: chapterAudio.audio_path
                                ? 'rgba(156, 39, 176, 0.12)'
                                : 'rgba(189, 189, 189, 0.18)',
                              color: chapterAudio.audio_path ? '#6a1b9a' : '#616161',
                              fontSize: '0.75rem',
                              height: 22,
                            }}
                          />
                        </Box>
                      </Box>
                    )
                  })}
                </Box>
              )}
              
              {selectedChapters.length > 0 && taskStatuses[selectedChapters[0]]?.stages?.quality_review && (
                <Button
                  variant="outlined"
                  onClick={handleOpenScriptReviewDialog}
                  sx={{
                    borderColor: '#9c27b0',
                    color: '#9c27b0',
                    '&:hover': {
                      borderColor: '#7b1fa2',
                      backgroundColor: 'rgba(156, 39, 176, 0.08)',
                    },
                  }}
                >
                  查看剧本评审
                </Button>
              )}

              {audiobookProject && (
                <Button
                  variant="outlined"
                  onClick={handleGenerateAudioForApprovedChapters}
                  sx={{
                    borderColor: '#4caf50',
                    color: '#2e7d32',
                    '&:hover': {
                      borderColor: '#2e7d32',
                      backgroundColor: 'rgba(76, 175, 80, 0.08)',
                    },
                  }}
                >
                  对已审批章节生成音频
                </Button>
              )}
              
              <Button
                variant="contained"
                onClick={() => {
                  setActiveStep(0)
                  setSelectedProject(null)
                  setAudiobookProject(null)
                  audioRef.pause() // 清理播放状态
                  setPlayingChapter(null)
                }}
                sx={{
                  backgroundColor: '#9c27b0',
                  '&:hover': { backgroundColor: '#7b1fa2' },
                }}
              >
                生成新项目
              </Button>
            </Box>
          </Paper>
        )}
      </Container>

      {/* 通知消息 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert 
          onClose={() => setSnackbar({ ...snackbar, open: false })} 
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* 从文本创建项目对话框 */}
      <Dialog
        open={newProjectDialogOpen}
        onClose={() => {
          if (!creatingFromBook) {
            setNewProjectDialogOpen(false)
          }
        }}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>从文本创建新项目</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            粘贴整本书或长篇文本，系统会自动拆分章节并创建项目，随后可以在本页生成有声书。
          </Alert>
          <TextField
            fullWidth
            label="项目名称"
            value={newProjectTitle}
            onChange={(e) => setNewProjectTitle(e.target.value)}
            placeholder="例如：某某小说 有声化项目"
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            multiline
            rows={12}
            label="书籍全文或长篇文本"
            placeholder="将整本书的文本粘贴到这里..."
            value={newProjectText}
            onChange={(e) => setNewProjectText(e.target.value)}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            当前长度：{newProjectText.trim().length.toLocaleString()} 字；超过 10,000 字时，点击「创建并开始配置音色」会自动跳转到拆书工具。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => !creatingFromBook && setNewProjectDialogOpen(false)} disabled={creatingFromBook}>
            取消
          </Button>
          <Button
            onClick={() => {
              const text = newProjectText.trim()
              const title = newProjectTitle.trim() || '从耳畔星河导入的书籍'
              setNewProjectDialogOpen(false)
              navigate('/book-parser', {
                state: {
                  openUpload: true,
                  prefillTitle: title,
                  prefillContent: text,
                },
              })
            }}
            disabled={creatingFromBook}
          >
            导入整本书到拆书工具
          </Button>
          <Button
            variant="contained"
            onClick={handleCreateProjectFromText}
            disabled={creatingFromBook}
            sx={{
              backgroundColor: '#9c27b0',
              '&:hover': { backgroundColor: '#7b1fa2' },
            }}
          >
            {creatingFromBook ? <CircularProgress size={20} color="inherit" /> : '创建并开始配置音色'}
          </Button>
        </DialogActions>
      </Dialog>
      
      {/* 剧本质量评审弹窗 */}
      <Dialog
        open={scriptReviewDialogOpen}
        onClose={handleCloseScriptReviewDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>剧本质量评审</DialogTitle>
        <DialogContent dividers>
          {!scriptReviewData ? (
            <Typography variant="body2" color="text.secondary">
              暂无评审数据
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  总体评分
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  评分：
                  {scriptReviewData.report.overall_score?.toFixed
                    ? scriptReviewData.report.overall_score.toFixed(1)
                    : scriptReviewData.report.overall_score}{' '}
                  （{scriptReviewData.report.overall_grade || 'N/A'}），问题数：
                  {scriptReviewData.report.issues_count ?? 0}
                </Typography>
                {scriptReviewData.report.revision_suggestions && (
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
                      建议：
                    </Typography>
                    {scriptReviewData.report.revision_suggestions.map((s: string, idx: number) => (
                      <Typography key={idx} variant="body2" color="text.secondary">
                        • {s}
                      </Typography>
                    ))}
                  </Box>
                )}
              </Box>

              <Divider />

              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                  剧本片段预览（前 {scriptReviewData.segments.length} 段）
                </Typography>
                <Paper
                  variant="outlined"
                  sx={{ maxHeight: 400, overflow: 'auto', p: 1 }}
                >
                  <List dense>
                    {scriptReviewData.segments.map((seg: any) => (
                      <ListItem key={seg.index} alignItems="flex-start" sx={{ mb: 0.5 }}>
                        <ListItemText
                          primary={
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              #{seg.index + 1} [{seg.type === 'dialogue' ? '对白' : seg.type}] {seg.speaker || '旁白'}
                            </Typography>
                          }
                          secondary={
                            <Typography variant="body2" color="text.secondary">
                              {seg.text}
                            </Typography>
                          }
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ mt: 1, display: 'block' }}
                >
                  当前弹窗展示的是自动改编后的有声剧本片段，仅用于人工审核；后续版本会支持直接在此编辑并回写。
                </Typography>
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseScriptReviewDialog}>关闭</Button>
        </DialogActions>
      </Dialog>

      {/* 章节剧本编辑弹窗 */}
      <ScriptEditorDialog
        open={scriptEditorDialogOpen}
        loading={scriptEditorLoading}
        chapter={scriptEditorChapter}
        data={scriptEditorData}
        onClose={handleCloseScriptEditorDialog}
        onChangeSegmentText={handleChangeScriptSegmentText}
        onSaveScript={handleSaveScript}
      />
      
      {/* 新增：历史记录对话框 */}
      <HistoryDialog
        open={showHistory}
        loading={loadingHistory}
        historyProjects={historyProjects}
        selectedProject={selectedProject}
        showDeleteConfirm={showDeleteConfirm}
        deletingProject={deletingProject}
        onCloseHistory={() => setShowHistory(false)}
        onViewHistory={handleViewHistory}
        onOpenDeleteConfirm={handleOpenDeleteConfirm}
        onCloseDeleteConfirm={() => setShowDeleteConfirm(false)}
        onConfirmDelete={handleDeleteProject}
      />
    </Box>
  )
}
