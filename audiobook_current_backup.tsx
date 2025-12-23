/**
 * 鑰崇晹鏄熸渤 - 鏈夊０灏忚鐢熸垚椤甸潰
 * 
 * 鍔熻兘锛?
 * 1. 椤圭洰閫夋嫨涓庣珷鑺傜鐞?
 * 2. 闊宠壊閰嶇疆
 * 3. 鏈夊０涔︾敓鎴?
 * 4. 杩涘害鐩戞帶
 * 5. 闊抽鎾斁涓庝笅杞?
 */
import { useState, useEffect, useMemo } from 'react'
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
  Link,
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

// 绫诲瀷瀹氫箟
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

// 鏂板锛氫换鍔＄姸鎬佺被鍨?
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

interface VoiceCatalogEntry {
  id: string
  speaker: string
  label: string
  gender: string
  style: string
  category: string
  languages: string[]
  description: string
  recommended: string[]
  default_params: {
    pitch: number
    speed: number
    volume: number
  }
  legacy_alias_of?: string
}

interface VoiceCatalogMeta {
  model: string
  updated_at?: string
  source?: string
  voice_count?: number
}

const QWEN_TTS_DOC_URL =
  'https://bailian.console.aliyun.com/?spm=a2c4g.11186623.0.0.3305641b138Z2Y&tab=doc#/doc/?type=model&url=2879134'

const LANGUAGE_LABELS: Record<string, string> = {
  zh: '涓枃',
  en: '鑻辫',
  ja: '鏃ヨ',
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
        {chapter ? `缂栬緫鍓ф湰 - ${chapter.title}` : '缂栬緫绔犺妭鍓ф湰'}
      </DialogTitle>
      <DialogContent dividers sx={{ minHeight: 400 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : !data ? (
          <Typography variant="body2" color="text.secondary">
            鏆傛棤鍓ф湰鏁版嵁锛岃鍏堢敓鎴愬墽鏈€?
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', gap: 2 }}>
            {/* 宸︿晶锛氬墽鏈彲缂栬緫鍒楄〃 */}
            <Box sx={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                鍓ф湰鐗囨锛堝彲缂栬緫鏂囨湰锛屼粎淇敼 text 瀛楁锛?
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
                          #{idx + 1} [{seg.type === 'dialogue' ? '瀵圭櫧' : seg.type}] {seg.speaker || '鏃佺櫧'}{' '}
                          {seg.emotion ? `路 鎯呯华: ${seg.emotion}` : ''}
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

            {/* 鍙充晶锛氳瘎瀹℃姤鍛婃憳瑕?*/}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                璇勫鎶ュ憡
              </Typography>
              {data.scriptReview ? (
                <Paper variant="outlined" sx={{ p: 2, maxHeight: 520, overflow: 'auto' }}>
                  {/* 鎬讳綋璇勫垎 */}
                  {/* 淇濈暀鍘熸湁鐨勫鏉傚睍绀洪€昏緫 */}
                  {/* 涓鸿妭鐪佺瘒骞咃紝杩欓噷澶嶇敤鍘熸湁 JSX锛屼笉鍐嶇粏鍖栨媶鍒?*/}
                  {/* 鐢变簬鍙槸鎶芥垚缁勪欢锛屽唴閮ㄧ粨鏋勪笉鍙?*/}
                  {/* BEGIN: 鎬讳綋璇勫垎 & 鍒嗛」璇勫垎 & 淇寤鸿 & 闂鍒楄〃 */}
                  {/* 杩欎竴娈电洿鎺ヤ粠鍘?Dialog 涓鍒讹紝鐣ヨ繃娉ㄩ噴淇敼 */}
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
                      馃搳 鎬讳綋璇勫垎
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
                          绛夌骇锛歿data.scriptReview.overall_grade || 'N/A'}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          闂鏁帮細
                          {data.scriptReview.issues_count ?? (data.scriptReview.issues?.length ?? 0)}
                        </Typography>
                      </Box>
                    </Box>
                  </Box>
                  {/* 鍏朵綑璇︾粏 JSX 缁х画淇濈暀鍦ㄥ師缁勪欢涓?*/}
                  {/* END: 璇︾粏璇勫垎涓庨棶棰樺垪琛ㄧ瓑 */}
                </Paper>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  鏆傛棤璇勫鏁版嵁銆?
                </Typography>
              )}

              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
                淇敼鍓ф湰鍚庯紝寤鸿閲嶆柊鐢熸垚璇ョ珷鑺傞煶棰戜互淇濊瘉鏂囨湰涓庨煶棰戜竴鑷淬€?
              </Typography>
            </Box>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          鍏抽棴
        </Button>
        <Button
          onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
          disabled={loading || !data}
        >
          浠呬繚瀛樺墽鏈?
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
          淇濆瓨骞剁敓鎴愯绔犺妭闊抽
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
              {selectedProject?.title} - 鍘嗗彶鐢熸垚璁板綍
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
                杩樻病鏈夌敓鎴愯繃鏈夊０涔?
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
                            : '排队中'
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
                        馃摎 绔犺妭锛歿project.completed_chapters}/{project.total_chapters}
                      </Typography>
                      {project.status === 'completed' && (
                        <Typography variant="body2" color="text.secondary">
                          馃晵 {((project.total_duration || 0) / 60).toFixed(1)}鍒嗛挓
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
          <Button onClick={onCloseHistory}>鍏抽棴</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={showDeleteConfirm} onClose={onCloseDeleteConfirm} maxWidth="sm" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#f44336' }} />
            <Typography variant="h6">纭鍒犻櫎</Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          <Box sx={{ py: 2 }}>
            <Typography variant="body1" gutterBottom>
              纭畾瑕佸垹闄や互涓嬫湁澹颁功椤圭洰鍚楋紵
            </Typography>
            {deletingProject && (
              <Box sx={{ mt: 2, p: 2, bgcolor: 'rgba(244, 67, 54, 0.05)', borderRadius: 1 }}>
                <Typography variant="body2" fontWeight="bold">
                  銆妠selectedProject?.title}銆?- #{deletingProject.id}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  绔犺妭锛歿deletingProject.completed_chapters}/{deletingProject.total_chapters} | 鏃堕暱锛?
                  {((deletingProject.total_duration || 0) / 60).toFixed(1)}鍒嗛挓
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  鍒涘缓鏃堕棿锛歿new Date(deletingProject.created_at).toLocaleString('zh-CN')}
                </Typography>
              </Box>
            )}
            <Alert severity="error" sx={{ mt: 2 }}>
              姝ゆ搷浣滃皢姘镐箙鍒犻櫎璇ラ」鐩強鍏舵墍鏈夐煶棰戞枃浠讹紝鏃犳硶鎭㈠锛?
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onCloseDeleteConfirm}>鍙栨秷</Button>
          <Button onClick={onConfirmDelete} variant="contained" color="error" autoFocus>
            纭鍒犻櫎
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}


const steps = ['选择项目', '配置音色', '生成有声书', '完成']

const AudiobookPage = () => {
  const navigate = useNavigate()

  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [characterVoices, setCharacterVoices] = useState<CharacterVoiceSetting[]>([])
  const [audioFxConfig, setAudioFxConfig] = useState<AudioFxConfig>({
    enable_sound_effects: true,
    enable_music: true,
    sound_effect_density: 'medium',
    music_density: 'medium',
  })
  const [audiobookProject, setAudiobookProject] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [loadingCharacters, setLoadingCharacters] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyProjects, setHistoryProjects] = useState<any[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deletingProject, setDeletingProject] = useState<any | null>(null)
  const [scriptReviewDialogOpen, setScriptReviewDialogOpen] = useState(false)
  const [scriptReviewData, setScriptReviewData] = useState<{ report: any; segments: any[] } | null>(null)
  const [scriptEditorDialogOpen, setScriptEditorDialogOpen] = useState(false)
  const [scriptEditorChapter, setScriptEditorChapter] = useState<{ chapterId: number; title: string } | null>(null)
  const [scriptEditorData, setScriptEditorData] = useState<{
    scriptStatus: string
    scriptSegments: any[]
    scriptReview?: any
  } | null>(null)
  const [scriptEditorLoading, setScriptEditorLoading] = useState(false)
  const [scriptOnlyMode, setScriptOnlyMode] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)
  const [taskStatuses, setTaskStatuses] = useState<Record<number, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newProjectText, setNewProjectText] = useState('')
  const [snackbar, setSnackbar] = useState<{
    open: boolean
    message: string
    severity: 'success' | 'info' | 'warning' | 'error'
  }>({
    open: false,
    message: '',
    severity: 'info',
  })
  const [autoAssigningVoices, setAutoAssigningVoices] = useState(false)
  const [creatingFromBook, setCreatingFromBook] = useState(false)
  const [lastGenerationMode, setLastGenerationMode] = useState<'full' | 'script_only'>('full')
  const [activeStep, setActiveStep] = useState(0)
  const [ttsModel, setTtsModel] = useState<'qwen3-tts-flash' | 'cosyvoice-v3-plus'>('qwen3-tts-flash')
  const [voicePresets, setVoicePresets] = useState<VoiceCatalogEntry[]>([])
  const [voiceCatalogMeta, setVoiceCatalogMeta] = useState<VoiceCatalogMeta | null>(null)
  const [voiceCatalogLoading, setVoiceCatalogLoading] = useState(true)
  const [voiceLoadError, setVoiceLoadError] = useState<string | null>(null)
  const [voiceCatalogReloadToken, setVoiceCatalogReloadToken] = useState(0)

  const audioRef = useMemo(() => new Audio(), [])
  const handleReloadVoiceCatalog = () => setVoiceCatalogReloadToken((token) => token + 1)

  const currentVoicePresets = useMemo(() => {
    if (ttsModel === 'cosyvoice-v3-plus') {
      return voicePresets.filter((preset) => preset.id === 'Ethan' || preset.id === 'Bunny')
    }
    return voicePresets
  }, [ttsModel, voicePresets])

  const catalogUpdatedAtLabel = useMemo(() => {
    if (!voiceCatalogMeta?.updated_at) {
      return null
    }
    const parsed = new Date(voiceCatalogMeta.updated_at)
    if (Number.isNaN(parsed.getTime())) {
      return voiceCatalogMeta.updated_at
    }
    return parsed.toLocaleDateString('zh-CN')
  }, [voiceCatalogMeta])

  // 鑾峰彇椤圭洰鍒楄〃
  useEffect(() => {
    let cancelled = false
    const fetchVoices = async () => {
      setVoiceCatalogLoading(true)
      setVoiceLoadError(null)
      try {
        const res = await apiClient.getTtsVoices()
        if (cancelled) return
        const data = res.data || {}
        setVoicePresets(data.voices || [])
        setVoiceCatalogMeta({
          model: data.model,
          updated_at: data.updated_at,
          source: data.source,
          voice_count: data.voice_count,
        })
      } catch (error) {
        console.error('????????????:', error)
        if (!cancelled) {
          setVoicePresets([])
          setVoiceCatalogMeta(null)
          setVoiceLoadError('????????? Qwen3-TTS Flash ??????????????????????????????????????')
        }
      } finally {
        if (!cancelled) {
          setVoiceCatalogLoading(false)
        }
      }
    }
    fetchVoices()
    return () => {
      cancelled = true
    }
  }, [voiceCatalogReloadToken])  
  // 鏂板锛氳幏鍙栧巻鍙茶褰?
  const fetchHistory = async () => {
    if (!selectedProject) return

    setLoadingHistory(true)
    try {
      const res = await apiClient.getAudiobookProjectsByProject(selectedProject.id)
      setHistoryProjects(res.data)
    } catch (error) {
      console.error('鑾峰彇鍘嗗彶璁板綍澶辫触:', error)
    } finally {
      setLoadingHistory(false)
    }
  }
  
  // 鏂板锛氭煡鐪嬪巻鍙查」鐩鎯?
  const handleViewHistory = async (audiobookProjectId: number) => {
    try {
      const res = await apiClient.getAudiobookProject(audiobookProjectId)
      const data = res.data
      setAudiobookProject(data)
      setActiveStep(3) // 璺宠浆鍒板畬鎴愰〉闈?
      setShowHistory(false)
    } catch (error) {
      console.error('鏌ョ湅鍘嗗彶澶辫触:', error)
      setSnackbar({ open: true, message: '鍔犺浇澶辫触', severity: 'error' })
    }
  }

  // 鏂板锛氭墦寮€鍒犻櫎纭瀵硅瘽妗?
  const handleOpenDeleteConfirm = (project: any) => {
    setDeletingProject(project)
    setShowDeleteConfirm(true)
  }

  // 鏂板锛氬垹闄ゆ湁澹颁功椤圭洰
  const handleDeleteProject = async () => {
    if (!deletingProject) return

    try {
      await apiClient.deleteAudiobookProject(deletingProject.id)
      setSnackbar({ open: true, message: '鍒犻櫎鎴愬姛', severity: 'success' })
      setShowDeleteConfirm(false)
      setDeletingProject(null)
      fetchHistory()
    } catch (error: any) {
      console.error('鍒犻櫎澶辫触:', error)
      const msg = (error?.response?.data?.detail as string) || '鍒犻櫎澶辫触'
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
      setSnackbar({ open: true, message: '璇峰厛绮樿创鏂囨湰鍐呭', severity: 'error' })
      return
    }

    const title = newProjectTitle.trim() || '浠庢暣鏈功瀵煎叆鐨勯」鐩?

    // 濡傛灉涓€娆¤緭鍏ヨ繃澶氾紝鍒欒烦杞埌鎷嗕功椤甸潰锛岀敱鎷嗕功宸ュ叿瀹屾垚鍚庣画娴佺▼
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
      // 绠€鍗曡疆璇㈡媶涔?鍒嗘瀽鐘舵€?
      // 杩欓噷涓嶄娇鐢ㄥ叏灞€ pollStatus锛岄伩鍏嶅拰涓ら樁娈电姸鎬佹贩娣?
      // targetStatuses 涓€鑸负 ['chapters_done'] 鎴?['completed']
      while (true) {
        const status = await bookParserApi.getParseStatus(bookId)
        if (targetStatuses.includes(status.status)) {
          return status
        }
        if (status.status === 'failed') {
          throw new Error(status.error || '鎷嗕功浠诲姟澶辫触')
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
      }
    }

    setCreatingFromBook(true)
    try {
      // 1. 涓婁紶鏁存湰涔︽枃鏈?
      const book = await bookParserApi.uploadText({
        title,
        content: rawText,
      })

      const bookId = book.id

      // 2. 鎵ц绔犺妭鍒囧垎
      await bookParserApi.parseBook(bookId)
      await waitForStatus(bookId, ['chapters_done'])

      // 3. 鎵цAI鍒嗘瀽锛堜汉鐗?涓栫晫瑙?鎯呰妭绛夛級锛屼究浜庡悗缁垱浣?
      await bookParserApi.analyzeBook(bookId)
      await waitForStatus(bookId, ['completed'])

      // 4. 瀵煎叆涓虹伒鎰熸柟鑸熼」鐩紙鍖呭惈绔犺妭鍐呭锛?
      const importResult = await bookParserApi.importToProject(bookId, {
        project_title: title,
        import_settings: true,
        import_characters: true,
        import_chapters: true,
      })

      // 5. 鍒锋柊椤圭洰鍒楄〃锛屽苟閫変腑鏂板缓椤圭洰锛岀洿鎺ヨ繘鍏ラ煶鑹查厤缃?
      try {
        const projectRes = await apiClient.getProject(importResult.project_id)
        const project = projectRes.data as Project
        setProjects((prev) => {
          // 纭繚鍒楄〃涓寘鍚柊椤圭洰
          if (prev.some((p) => p.id === project.id)) return prev
          return [project, ...prev]
        })
        setSelectedProject(project)
      } catch (e) {
        // 鍥為€€锛氬鏋滆幏鍙栧崟涓」鐩け璐ワ紝鑷冲皯鏋勯€犱竴涓渶灏忕殑椤圭洰瀵硅薄
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
        message: '宸蹭粠鏂囨湰鍒涘缓椤圭洰锛岃閰嶇疆闊宠壊鍚庣敓鎴愭湁澹颁功',
        severity: 'success',
      })
    } catch (error: any) {
      console.error('浠庢枃鏈垱寤洪」鐩け璐?', error)
      const msg = (error?.response?.data?.detail ?? undefined) as string | undefined
      setSnackbar({
        open: true,
        message: msg || error.message || '浠庢枃鏈垱寤洪」鐩け璐ワ紝璇风◢鍚庨噸璇?,
        severity: 'error',
      })
    } finally {
      setCreatingFromBook(false)
    }
  }

  // 閫夋嫨椤圭洰
  const handleSelectProject = async (project: Project) => {
    setSelectedProject(project)
    setLoading(true)
    setCharacterVoices([])

    const baseNarratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '鏃佺櫧',
      gender: '涓€?,
      role: '鏃佺櫧',
      voiceId: 'male_narrator',  // 馃敡 榛樿浣跨敤鈥滄梺鐧斤紙鏂硅█锛夆€濓紝鐢ㄦ埛鍙互鎵嬪姩淇敼
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }
    
    try {
      // 鑾峰彇绔犺妭鍒楄〃
      const chaptersRes = await apiClient.getChapters(project.id)
      const chaptersData = chaptersRes.data
      setChapters(chaptersData)
      setSelectedChapters(chaptersData.map((c: Chapter) => c.id))  // 榛樿鍏ㄩ€?

      // 鑾峰彇瑙掕壊鍒楄〃锛堢敤浜庨煶棰戦厤缃級
      setLoadingCharacters(true)
      try {
        const charactersRes = await apiClient.getCharacters(project.id)
        const charactersData = charactersRes.data
      
        // 灏濊瘯璇诲彇椤圭洰绾ч煶棰戦厤缃紙瑙掕壊闊?+ 闊虫晥/BGM锛?
        let projectAudioConfig: ProjectAudioConfig | null = null
        try {
          const audioConfigRes = await apiClient.getProjectAudioConfig(project.id)
          projectAudioConfig = audioConfigRes.data
        } catch (e) {
          console.warn('鑾峰彇椤圭洰闊抽閰嶇疆澶辫触:', e)
        }
      
        const savedCharacters = projectAudioConfig?.characters || []
        const savedFx = projectAudioConfig?.audio_fx || null
      
        // 鏍规嵁宸蹭繚瀛樼殑瑙掕壊闊抽厤缃垵濮嬪寲瑙掕壊闊?
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
      
        // 鏃佺櫧浣跨敤 character_id 涓?0 鎴?name 涓?鏃佺櫧"鐨勯厤缃紙濡傛湁锛?
        const narratorSaved = savedCharacters.find(
          (sc) => sc.character_id === 0 || sc.name === '鏃佺櫧'
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
      
        // 鍒濆鍖栭」鐩骇闊虫晥/BGM 閰嶇疆
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
        console.error('鑾峰彇瑙掕壊鍒楄〃澶辫触:', error)
        setCharacterVoices([baseNarratorVoice])
      } finally {
        setLoadingCharacters(false)
      }

      setActiveStep(1)
    } catch (error) {
      console.error('鑾峰彇绔犺妭澶辫触:', error)
      setSnackbar({ open: true, message: '缃戠粶閿欒锛岃閲嶈瘯', severity: 'error' })
    } finally {
      setLoading(false)
    }
  }

  // 鍒囨崲绔犺妭閫夋嫨
  const handleToggleChapter = (chapterId: number) => {
    setSelectedChapters(prev => 
      prev.includes(chapterId) 
        ? prev.filter(id => id !== chapterId)
        : [...prev, chapterId]
    )
  }

  // 鍏ㄩ€?鍙栨秷鍏ㄩ€?
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

  // 馃啎 鍩轰簬浜虹墿鍗¤嚜鍔ㄦ帹鑽愬０绾?
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
          message: `鉁?宸蹭负 ${assignedCount} 涓鑹叉櫤鑳芥帹鑽愬０绾匡紒璇锋鏌ユ帹鑽愮粨鏋滐紝濡傞渶璋冩暣鍙墜鍔ㄤ慨鏀广€俙,
          severity: 'success',
        })
      } else {
        setSnackbar({
          open: true,
          message: '鈿狅笍 褰撳墠椤圭洰杩樻病鏈夎鑹叉。妗堬紝璇峰厛鍦ㄣ€岄」鐩鎯?鈫?浜虹墿璁惧畾銆嶄腑鍒涘缓瑙掕壊銆?,
          severity: 'warning',
        })
      }
    } catch (err) {
      console.error('鉂?鑷姩鎺ㄨ崘澹扮嚎澶辫触:', err)
      setSnackbar({
        open: true,
        message: '鑷姩鎺ㄨ崘澹扮嚎澶辫触锛岃绋嶅悗閲嶈瘯',
        severity: 'error',
      })
    } finally {
      setAutoAssigningVoices(false)
    }
  }

  const handlePreviewCharacterVoice = async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId) {
      setSnackbar({ open: true, message: '璇峰厛涓鸿瑙掕壊閫夋嫨闊宠壊鍐嶈瘯鍚?, severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const text = '褰撲綘鐪熺殑鍠滄涓€涓汉鐨勬椂鍊欏氨瀹规槗璇村偦璇濆姙锠簨銆?

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
      console.error('瑙掕壊闊宠瘯鍚け璐?', error)
      setSnackbar({ open: true, message: '瑙掕壊闊宠瘯鍚け璐ワ紝璇风◢鍚庨噸璇?, severity: 'error' })
    } finally {
      setPreviewingCharacterId(null)
    }
  }

  // 鏂板锛氫笅杞介煶棰?
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
        
        // 浠?Content-Disposition 鑾峰彇鏂囦欢鍚?
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
        
        setSnackbar({ open: true, message: '馃摜 闊抽涓嬭浇鎴愬姛', severity: 'success' })
      } else {
        throw new Error('涓嬭浇澶辫触')
      }
    } catch (error) {
      console.error('涓嬭浇闊抽澶辫触:', error)
      setSnackbar({ open: true, message: '鉂?涓嬭浇澶辫触锛岃閲嶈瘯', severity: 'error' })
    }
  }
  
  // 鏂板锛氬湪绾挎挱鏀鹃煶棰?
  const handlePlayAudio = async (chapterId: number) => {
    if (!audiobookProject) return
    
    try {
      // 濡傛灉褰撳墠姝ｅ湪鎾斁鍚屼竴绔犺妭锛屽垯鏆傚仠
      if (playingChapter === chapterId) {
        audioRef.pause()
        setPlayingChapter(null)
        return
      }
      
      // 鏆傚仠褰撳墠鎾斁
      audioRef.pause()
      
      // 閫氳繃 fetch 鑾峰彇闊抽鏁版嵁锛堝甫 Authorization header锛?
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
        throw new Error('鍔犺浇闊抽澶辫触')
      }
      
      // 鍒涘缓 Blob URL
      const blob = await response.blob()
      const blobUrl = window.URL.createObjectURL(blob)
      
      // 璁剧疆鏂扮殑闊抽婧?
      audioRef.src = blobUrl
      
      // 鎾斁
      await audioRef.play()
      setPlayingChapter(chapterId)
      
      // 鎾斁缁撴潫鍚庨噸缃姸鎬佸苟閲婃斁 Blob URL
      audioRef.onended = () => {
        setPlayingChapter(null)
        window.URL.revokeObjectURL(blobUrl)
      }
      
      setSnackbar({ open: true, message: '馃幍 寮€濮嬫挱鏀?, severity: 'success' })
    } catch (error) {
      console.error('鎾斁闊抽澶辫触:', error)
      setSnackbar({ open: true, message: '鉂?鎾斁澶辫触锛岃閲嶈瘯', severity: 'error' })
      setPlayingChapter(null)
    }
  }

  const handleOpenScriptReviewDialog = () => {
    if (selectedChapters.length === 0) return
    const chapterId = selectedChapters[0]
    const taskStatus = taskStatuses[chapterId]
    if (!taskStatus) {
      setSnackbar({ open: true, message: '鏆傛湭鑾峰彇鍒拌绔犺妭鐨勪换鍔＄姸鎬?, severity: 'error' })
      return
    }
    const stage = taskStatus.stages['quality_review']
    if (!stage || !stage.metrics) {
      setSnackbar({ open: true, message: '鏆傛湭鑾峰彇鍒板墽鏈瘎瀹＄粨鏋?, severity: 'error' })
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

  // 鎵撳紑绔犺妭鍓ф湰缂栬緫鍣?
  const handleOpenScriptEditor = async (chapterId: number) => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '璇峰厛鍒涘缓鏈夊０涔﹂」鐩?, severity: 'error' })
      return
    }

    const chapter = chapters.find((c) => c.id === chapterId)
    setScriptEditorChapter(
      chapter
        ? { chapterId, title: `绗?{chapter.chapter_number}绔?- ${chapter.title}` }
        : { chapterId, title: `绔犺妭 ${chapterId}` }
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
      console.error('鑾峰彇绔犺妭鍓ф湰澶辫触:', err)
      setSnackbar({ open: true, message: err.message || '鑾峰彇绔犺妭鍓ф湰澶辫触', severity: 'error' })
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

      setSnackbar({ open: true, message: '鍓ф湰宸蹭繚瀛?, severity: 'success' })

      // 鍙€夛細淇濆瓨骞剁敓鎴愯绔犺妭闊抽
      if (options.generateAudio) {
        await apiClient.generateAudioFromScripts(audiobookProject.id, {
          chapter_ids: [scriptEditorChapter.chapterId],
          tts_model: ttsModel,
        })
        setSnackbar({ open: true, message: '宸茶Е鍙戣绔犺妭闊抽鐢熸垚', severity: 'success' })
      }

      // 淇濆瓨鍚庝笉鑷姩鍏抽棴锛屾柟渚跨户缁慨鏀癸紱濡傞渶鍙湪姝ゅ叧闂?
      // handleCloseScriptEditorDialog()
    } catch (err: any) {
      console.error('淇濆瓨/鐢熸垚澶辫触:', err)
      setSnackbar({ open: true, message: err.message || '淇濆瓨澶辫触', severity: 'error' })
    } finally {
      setScriptEditorLoading(false)
    }
  }

  const handleGenerateAudioForApprovedChapters = async () => {
    if (!audiobookProject) {
      setSnackbar({ open: true, message: '璇峰厛瀹屾垚鍓ф湰鐢熸垚', severity: 'error' })
      return
    }

    try {
      const res = await apiClient.generateAudioFromScripts(audiobookProject.id, {
        tts_model: ttsModel,
      })

      if (res.status !== 200) {
        throw new Error('瑙﹀彂闊抽鐢熸垚澶辫触')
      }

      setSnackbar({
        open: true,
        message: '宸茶Е鍙戞墍鏈夊凡瀹℃壒绔犺妭鐨勯煶棰戠敓鎴愶紝璇风◢鍊欏湪鍘嗗彶璁板綍鎴栨湰椤靛埛鏂版煡鐪嬬粨鏋?,
        severity: 'success',
      })
    } catch (err: any) {
      console.error('鎵归噺鐢熸垚闊抽澶辫触:', err)
      setSnackbar({
        open: true,
        message: err.message || '鎵归噺鐢熸垚闊抽澶辫触锛岃绋嶅悗閲嶈瘯',
        severity: 'error',
      })
    }
  }

  // 寮€濮嬬敓鎴?
  const handleGenerate = async () => {
    if (!selectedProject || selectedChapters.length === 0) {
      setSnackbar({ open: true, message: '璇疯嚦灏戦€夋嫨涓€涓珷鑺?, severity: 'error' })
      return
    }
    
    setGenerating(true)
    setActiveStep(2)
    setLastGenerationMode(scriptOnlyMode ? 'script_only' : 'full')
    setTaskStatuses({})  // 娓呯┖涔嬪墠鐨勭姸鎬?

    try {
      // 璋冪敤鐢熸垚API
      // 鍏堜繚瀛樻湰娆＄殑椤圭洰绾ч煶棰戦厤缃紙瑙掕壊闊?+ 闊虫晥/BGM锛夛紝鐢ㄤ簬涓嬫鑷姩甯﹀嚭
      if (selectedProject) {
        const projectAudioConfigBody: ProjectAudioConfig = {
          characters: characterVoices
            .filter((cv) => cv.voiceId || cv.name === '鏃佺櫧')  // 馃敡 淇锛氭梺鐧藉嵆浣?voiceId 涓虹┖涔熶繚鐣欙紝璁╁悗绔娇鐢ㄩ粯璁ら煶鑹?
            .map((cv) => ({
              character_id: cv.characterId,
              name: cv.name,
              voice_id: cv.voiceId || 'male_narrator',  // 馃敡 淇锛氱┖闊宠壊浣跨敤榛樿鍊?
              volume: cv.volume,
              speed: cv.speed,
              pitch: cv.pitch,
            })),
          audio_fx: audioFxConfig,
        }

        try {
          await apiClient.updateProjectAudioConfig(selectedProject.id, projectAudioConfigBody)
        } catch (err) {
          console.warn('淇濆瓨椤圭洰闊抽閰嶇疆澶辫触:', err)
        }
      }

      const voiceConfigPayload =
        characterVoices
          .filter((cv) => cv.voiceId || cv.name === '鏃佺櫧')  // 馃敡 淇锛氭梺鐧藉嵆浣?voiceId 涓虹┖涔熶繚鐣?
          .map((cv) => ({
            character_name: cv.name,
            voice_id: cv.voiceId || 'male_narrator',  // 馃敡 淇锛氱┖闊宠壊浣跨敤榛樿鍊?
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

      // 杞鏌ヨ椤圭洰杩涘害
      const projectId = data.audiobook_project_id
      const pollInterval = setInterval(async () => {
        try {
          const statusResponse = await apiClient.getAudiobookProject(projectId)
          const statusData = statusResponse.data
          console.log('杞椤圭洰鐘舵€?', statusData)

          // 鏂板锛氳幏鍙栫涓€涓珷鑺傜殑task_id锛堝鏋滄湁锛?
          if (statusData.chapter_audios && statusData.chapter_audios.length > 0) {
            console.log('chapter_audios:', statusData.chapter_audios)
            const firstTaskId = statusData.chapter_audios[0].task_id
            console.log('firstTaskId:', firstTaskId)
            if (firstTaskId) {
              console.log('鑾峰彇鍒?task_id:', firstTaskId)
              setCurrentTaskId(prev => {
                if (!prev) {
                  console.log('璁剧疆 currentTaskId:', firstTaskId)
                  return firstTaskId
                }
                return prev
              })
            }
          } else {
            console.log('鏆傛棤 chapter_audios 鎴栦负绌?)
          }

          if (statusData.status === 'completed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setActiveStep(3)
            setAudiobookProject(statusData)
            setSnackbar({ open: true, message: '鐢熸垚瀹屾垚锛?, severity: 'success' })
          } else if (statusData.status === 'failed') {
            clearInterval(pollInterval)
            setGenerating(false)
            setSnackbar({ open: true, message: '鐢熸垚澶辫触锛岃閲嶈瘯', severity: 'error' })
            setActiveStep(1)
          }
        } catch (err) {
          console.error('杞鏈夊０涔﹂」鐩姸鎬佸け璐?', err)
        }
      }, 2000) // 姣?绉掓煡璇竴娆?
    } catch (error: any) {
      console.error('鐢熸垚澶辫触:', error)
      setSnackbar({ 
        open: true, 
        message: error.message || '鐢熸垚澶辫触锛岃閲嶈瘯', 
        severity: 'error' 
      })
      setGenerating(false)
      setActiveStep(1)
    }
  }
  
  // 鏂板锛氳疆璇换鍔″垪琛ㄤ互鑾峰彇褰撳墠绔犺妭鐨?task_id锛堥伩鍏嶄緷璧?chapter_audios锛?
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
            console.log('浠庝换鍔″垪琛ㄤ腑鎵惧埌褰撳墠绔犺妭鐨?task_id:', matched.task_id)
            setCurrentTaskId(prev => prev || matched.task_id)
          }
        } else {
          console.error('鏌ヨ浠诲姟鍒楄〃澶辫触:', response.status, response.statusText)
        }
      } catch (error) {
        console.error('鏌ヨ浠诲姟鍒楄〃寮傚父:', error)
      }
    }

    // 鍏堟煡涓€娆?
    pollTaskList()
    // 鐒跺悗姣?绉掓煡涓€娆★紝鐩村埌 currentTaskId 琚缃?
    const intervalId = setInterval(() => {
      if (!currentTaskId) {
        pollTaskList()
      }
    }, 2000)

    return () => clearInterval(intervalId)
  }, [generating, currentTaskId, selectedChapters])
  
  // 鏂板锛氳疆璇㈠崟涓换鍔＄姸鎬侊紙鐢ㄤ簬瀹炴椂鏄剧ず8涓樁娈碉級
  useEffect(() => {
    if (!currentTaskId || !generating) {
      console.log('璺宠繃浠诲姟鐘舵€佽疆璇?', { currentTaskId, generating })
      return
    }
    
    console.log('寮€濮嬭疆璇换鍔＄姸鎬?', currentTaskId)
    
    const pollTaskStatus = async () => {
      try {
        const response = await fetch(`/api/v1/audiobook/tasks/${currentTaskId}/status`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        
        if (response.ok) {
          const taskStatus: TaskStatus = await response.json()
          console.log('鑾峰彇鍒颁换鍔＄姸鎬?', taskStatus)
          setTaskStatuses(prev => ({
            ...prev,
            [taskStatus.chapter_id]: taskStatus
          }))
        } else {
          console.error('鏌ヨ浠诲姟鐘舵€佸け璐?', response.status, response.statusText)
        }
      } catch (error) {
        console.error('鏌ヨ浠诲姟鐘舵€佸紓甯?', error)
      }
    }
    
    // 绔嬪嵆鏌ヨ涓€娆?
    pollTaskStatus()
    
    // 姣?绉掓煡璇竴娆?
    const intervalId = setInterval(pollTaskStatus, 2000)
    
    return () => clearInterval(intervalId)
  }, [currentTaskId, generating])
  
  // 鏂板锛氭覆鏌撻樁娈佃鎯?
  const renderStageDetails = (taskStatus: TaskStatus) => {
    const stageConfig = [
      { key: 'strategy', name: '绛栫暐鍒跺畾', icon: '馃幆', desc: '鍒嗘瀽鍘熸枃锛屽埗瀹氭敼缂栫瓥鐣? },
      { key: 'script_adaptation', name: '鍓ф湰鏀圭紪', icon: '馃摑', desc: '灏嗗皬璇存敼缂栦负鏈夊０鍓ф湰' },
      { key: 'voice_design', name: '闊宠壊璁捐', icon: '馃幁', desc: '涓鸿鑹插垎閰嶉煶鑹插弬鏁? },
      { key: 'sound_design', name: '闊虫晥璁捐', icon: '馃帶', desc: '璁捐鍦烘櫙闊虫晥鍜岀幆澧冮煶' },
      { key: 'music_composition', name: '闊充箰缂栨洸', icon: '馃幍', desc: '璁捐鑳屾櫙闊充箰鏂规' },
      { key: 'quality_review', name: '鍓ф湰璇勫', icon: '馃攳', desc: 'TTS鍓嶈川閲忔鏌? },
      { key: 'tts_synthesis', name: 'TTS鍚堟垚', icon: '馃棧锔?, desc: '璇煶鍚堟垚鐢熸垚闊抽' },
      { key: 'audio_mixing', name: '闊抽娣峰悎', icon: '馃帤锔?, desc: '娣烽煶涓庡悗鏈熷鐞? },
      { key: 'final_audio_review', name: '鏈€缁堣瘎瀹?, icon: '鉁?, desc: '鏈€缁堣川閲忔鏌? },
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
              {/* 澶撮儴锛氬浘鏍?鍚嶇О+鐘舵€?*/}
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
                    鉁?
                  </Box>
                )}
              </Box>
              
              {/* 杩涘害鏉?*/}
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
              
              {/* 鐘舵€佹枃瀛?*/}
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
                {isActive ? `杩涜涓?${Math.round(stageInfo.progress * 100)}%` : 
                 isDone ? '宸插畬鎴? : 
                 stageInfo.status === 'failed' ? '澶辫触' : '绛夊緟涓?}
              </Typography>
              
              {/* 鍏抽敭鎸囨爣 */}
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
      {/* 椤堕儴瀵艰埅 */}
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
            鑰崇晹鏄熸渤
          </Typography>
          <Typography variant="caption" color="text.secondary">
            鏈夊０灏忚鐢熸垚宸ュ叿
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
          鏂板缓椤圭洰
        </Button>
        
        {/* 鏂板锛氬巻鍙茶褰曟寜閽?*/}
        {selectedProject && (
          <Tooltip title="鏌ョ湅鍘嗗彶鐢熸垚璁板綍">
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
              鍘嗗彶璁板綍
            </Button>
          </Tooltip>
        )}
      </Box>

      <Container maxWidth="xl" sx={{ py: 4 }}>
        {/* 姝ラ鎸囩ず鍣?*/}
        <Paper sx={{ p: 3, mb: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
          <Stepper activeStep={activeStep}>
            {steps.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>
        </Paper>

        {/* 姝ラ1: 閫夋嫨椤圭洰 */}
        {activeStep === 0 && (
          <Box>
            {projects.length === 0 ? (
              <Paper sx={{ p: 4, textAlign: 'center', backgroundColor: 'rgba(255,255,255,0.95)' }}>
                <Typography variant="body1" color="text.secondary">
                  鏆傛棤椤圭洰锛岃鍏堝垱寤哄皬璇撮」鐩?
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
                  鍘诲垱寤洪」鐩?
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
                          {/* 鍐呭眰娣辫壊鍦?*/}
                          <Box
                            sx={{
                              width: 90,
                              height: 90,
                              borderRadius: '50%',
                              backgroundColor: '#262b4f',
                              position: 'relative',
                            }}
                          />

                          {/* 鎾斁鎸夐挳锛堜笁瑙掑舰锛?*/}
                          <Box
                            sx={{
                              position: 'absolute',
                              width: 34,
                              height: 34,
                              backgroundColor: '#ffffff',
                              clipPath: 'polygon(28% 18%, 78% 50%, 28% 82%)',
                            }}
                          />

                          {/* 涔︽湰鍏冪礌宸茬Щ闄わ紝浠呬繚鐣欒€虫満涓庢挱鏀炬寜閽?*/}

                          {/* 鑰虫満澶存锛堜笂鏂瑰姬绾匡級 */}
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

                          {/* 宸﹀彸鑰崇僵 */}
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
                        {/* 鍙繚鐣欓」鐩悕绉帮紝涓嶅啀灞曠ず绠€浠?*/}
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

        {/* 姝ラ2: 閰嶇疆闊宠壊锛堢珷鑺傞€夋嫨 + 瑙掕壊闊抽璁剧疆锛?*/}
        {activeStep === 1 && (
          <Paper sx={{ p: 3, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center' }}>
              <VoiceIcon sx={{ mr: 1, color: '#9c27b0' }} />
              閰嶇疆绔犺妭涓庤鑹查煶
            </Typography>
                    
            <Alert severity="info" sx={{ mb: 2 }}>
              宸查€夋嫨 {selectedChapters.length}/{chapters.length} 涓珷鑺傘€傛湭閰嶇疆鐨勮鑹插皢鐢?AI 鑷姩鍒嗛厤闊宠壊鍜岄煶閲忋€?
            </Alert>

            {/* TTS 妯″瀷閫夋嫨 */}
            <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <FormControl size="small" sx={{ minWidth: 260 }}>
                <InputLabel>TTS 妯″瀷</InputLabel>
                <Select
                  label="TTS 妯″瀷"
                  value={ttsModel}
                  onChange={(e) => setTtsModel(e.target.value as 'qwen3-tts-flash' | 'cosyvoice-v3-plus')}
                >
                  <MenuItem value="qwen3-tts-flash">
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <span>Qwen3-TTS Flash</span>
                      <Tooltip title="楂樻€т环姣旓紝閫熷害蹇紝閫傚悎澶ц妯＄珷鑺傜敓鎴愶紝浠锋牸杈冧綆">
                        <Chip
                          label="浠锋牸锛氫綆"
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
                      <Tooltip title="闊宠川鏇村ソ锛屾敮鎸侀浂鏍锋湰澹伴煶澶嶅埢锛屾洿閫傚悎閲嶈绔犺妭鍜岀簿缁嗚鑹诧紝浠锋牸杈冮珮">
                        <Chip
                          label="浠锋牸锛氶珮"
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
                label="浠呯敓鎴愬墽鏈拰璇勫锛堢◢鍚庡啀鐢熸垚闊抽锛?
              />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              {ttsModel === 'qwen3-tts-flash'
                ? 'Qwen3-TTS Flash?????? + ?????????????????????????????????'
                : 'CosyVoice v3-plus?????????????????????????'}
            </Typography>

            {voiceCatalogLoading && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2, mb: 2 }}>
                <CircularProgress size={18} color="secondary" />
                <Typography variant="body2" color="text.secondary">
                  ???? Qwen3 ?????
                </Typography>
              </Box>
            )}

            {voiceLoadError && (
              <Alert
                severity="warning"
                sx={{ mb: 2 }}
                action={
                  <Button color="inherit" size="small" onClick={handleReloadVoiceCatalog}>
                    ????
                  </Button>
                }
              >
                {voiceLoadError}
              </Alert>
            )}

            {voiceCatalogMeta && !voiceLoadError && (
              <Paper
                variant="outlined"
                sx={{
                  mb: 2,
                  p: 2,
                  borderColor: 'rgba(156, 39, 176, 0.28)',
                  backgroundColor: 'rgba(156, 39, 176, 0.02)',
                }}
              >
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}>
                  <Typography variant="subtitle2" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    Qwen3 ????
                    <Chip
                      size="small"
                      color="secondary"
                      sx={{ height: 22 }}
                      label={`${voiceCatalogMeta.voice_count ?? voicePresets.length} ?`}
                    />
                  </Typography>
                  <Button size="small" variant="outlined" onClick={handleReloadVoiceCatalog} disabled={voiceCatalogLoading}>
                    ????
                  </Button>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  ???{voiceCatalogMeta.model} ? ?????{catalogUpdatedAtLabel ?? '?????'} ? ?????
                  <Link href={QWEN_TTS_DOC_URL} target="_blank" rel="noreferrer">
                    ??? Model Studio
                  </Link>
                </Typography>
                <Typography variant="body2" sx={{ mt: 1 }}>
                  Qwen3-TTS Flash ??????????????????????????????????????? CosyVoice v3-plus?
                </Typography>
              </Paper>
            )}



            {/* 椤圭洰绾ч煶鏁堜笌閰嶄箰閰嶇疆 */}
            <Paper
              variant="outlined"
              sx={{
                mb: 2,
                p: 2,
                backgroundColor: 'rgba(156, 39, 176, 0.02)',
              }}
            >
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                闊虫晥涓庤儗鏅煶涔?
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                杩欓噷鐨勮缃細浣滀负椤圭洰绾ч粯璁ら厤缃繚瀛橈紝涓嬫杩涘叆璇ラ」鐩細鑷姩甯﹀嚭锛屽苟褰卞搷闊虫晥/閰嶄箰鏄惁鍚敤鍙婂ぇ鑷村瘑搴︺€?
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
                    label="寮€鍚煶鏁堬紙鐜闊?+ 鍏抽敭鍔ㄤ綔闊筹級"
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_sound_effects}>
                    <InputLabel>闊虫晥瀵嗗害</InputLabel>
                    <Select
                      label="闊虫晥瀵嗗害"
                      value={audioFxConfig.sound_effect_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          sound_effect_density: e.target.value as AudioFxConfig['sound_effect_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">鍏抽棴锛堜笉浣跨敤闊虫晥锛?/MenuItem>
                      <MenuItem value="low">绋€鐤忥紙浠呭叧閿満鏅級</MenuItem>
                      <MenuItem value="medium">閫備腑锛堟帹鑽愶級</MenuItem>
                      <MenuItem value="high">涓板瘜锛堟矇娴告劅鏇村己锛?/MenuItem>
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
                    label="寮€鍚儗鏅煶涔愶紙AI 閰嶄箰锛?
                  />
                  <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!audioFxConfig.enable_music}>
                    <InputLabel>閰嶄箰瀵嗗害</InputLabel>
                    <Select
                      label="閰嶄箰瀵嗗害"
                      value={audioFxConfig.music_density}
                      onChange={(e) =>
                        setAudioFxConfig((prev) => ({
                          ...prev,
                          music_density: e.target.value as AudioFxConfig['music_density'],
                        }))
                      }
                    >
                      <MenuItem value="off">鍏抽棴锛堜笉浣跨敤閰嶄箰锛?/MenuItem>
                      <MenuItem value="low">绋€鐤忥紙浠呯墖澶?鐗囧熬锛?/MenuItem>
                      <MenuItem value="medium">閫備腑锛堟帹鑽愶級</MenuItem>
                      <MenuItem value="high">涓板瘜锛堝嚑涔庡叏绋嬫湁閰嶄箰锛?/MenuItem>
                    </Select>
                  </FormControl>
                </Grid>
              </Grid>
            </Paper>
        
            <Grid container spacing={3}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1 }}>
                  绔犺妭閫夋嫨
                </Typography>
        
                {/* 鍏ㄩ€夋寜閽?*/}
                <Box sx={{ mb: 2, display: 'flex', gap: 1 }}>
                  <Button 
                    variant="outlined" 
                    size="small"
                    onClick={handleToggleAll}
                  >
                    {selectedChapters.length === chapters.length ? '鍙栨秷鍏ㄩ€? : '鍏ㄩ€?}
                  </Button>
                </Box>
        
                {/* 绔犺妭鍒楄〃 */}
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
                          primary={`绗?{chapter.chapter_number}绔?- ${chapter.title}`}
                          secondary={chapter.content ? `${chapter.content.slice(0, 50)}...` : '鏆傛棤鍐呭'}
                        />
                      </ListItem>
                    ))}
                  </List>
                </Paper>
              </Grid>
        
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle1" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AudioIcon fontSize="small" />
                  瑙掕壊闊充笌闊抽噺閰嶇疆
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  涓嶄慨鏀规椂浣跨敤 AI 榛樿闊宠壊锛涗负瑙掕壊閫夋嫨闊宠壊鎴栬皟鏁撮煶閲忓悗锛屾湰娆℃湁澹颁功鐢熸垚灏嗕紭鍏堜娇鐢ㄤ綘鐨勯厤缃€?
                </Typography>
        
                {loadingCharacters && (
                  <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
                    <CircularProgress size={24} />
                  </Box>
                )}
        
                {!loadingCharacters && characterVoices.length === 0 && (
                  <Box sx={{ py: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      褰撳墠椤圭洰杩樻病鏈夌粨鏋勫寲瑙掕壊妗ｆ锛屽彲鍦ㄣ€岄」鐩鎯?鈫?瑙掕壊绠＄悊銆嶄腑娣诲姞瑙掕壊鍚庡啀閰嶇疆闊宠壊銆?
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
                                    {cv.role || '瑙掕壊'} 路 {cv.gender || '鎬у埆鏈瀹?}
                                  </Typography>
                                )}
                              </Box>
                              {cv.voiceId && (
                                <Chip
                                  label="宸查厤缃?
                                  size="small"
                                  color="success"
                                  sx={{ height: 20 }}
                                />
                              )}
                            </Box>
        
                            <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                              <FormControl size="small" fullWidth>
                                <InputLabel>瑙掕壊闊?/InputLabel>
                                <Select
                                  label="瑙掕壊闊?
                                  value={cv.voiceId}
                                  onChange={(e) => handleVoiceChange(cv.characterId, e.target.value as string)}
                                >
                                  <MenuItem value="">
                                    <em>鑷姩锛圓I 閫夋嫨锛?/em>
                                  </MenuItem>
                                  {currentVoicePresets.map((preset) => {
                                    const pitch =
                                      typeof preset.default_params?.pitch === 'number' ? preset.default_params?.pitch : '--'
                                    const rawSpeed = preset.default_params?.speed
                                    const speed = typeof rawSpeed === 'number' ? rawSpeed.toFixed(2) : '--'
                                    const volume =
                                      typeof preset.default_params?.volume === 'number' ? preset.default_params?.volume : '--'
                                    return (
                                      <MenuItem key={preset.id} value={preset.id}>
                                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                              {preset.label}
                                            </Typography>
                                            {preset.category && (
                                              <Chip
                                                label={preset.category === 'dialect' ? '方言' : preset.category}
                                                size="small"
                                                variant="outlined"
                                                sx={{ height: 18, fontSize: '0.65rem' }}
                                              />
                                            )}
                                          </Box>
                                          {preset.description && (
                                            <Typography variant="caption" color="text.secondary">
                                              {preset.description}
                                            </Typography>
                                          )}
                                          {(preset.languages?.length || preset.recommended?.length) && (
                                            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                                              {preset.languages?.map((lang) => (
                                                <Chip
                                                  key={`${preset.id}-lang-${lang}`}
                                                  label={LANGUAGE_LABELS[lang] ?? lang.toUpperCase()}
                                                  size="small"
                                                  color="secondary"
                                                  variant="outlined"
                                                  sx={{ height: 18, fontSize: '0.65rem' }}
                                                />
                                              ))}
                                              {preset.recommended?.slice(0, 2).map((tag) => (
                                                <Chip
                                                  key={`${preset.id}-rec-${tag}`}
                                                  label={tag}
                                                  size="small"
                                                  variant="outlined"
                                                  sx={{ height: 18, fontSize: '0.65rem' }}
                                                />
                                              ))}
                                            </Box>
                                          )}
                                          {preset.default_params && (
                                            <Typography variant="caption" color="text.secondary">
                                              推荐参数：音高 {pitch} ｜ 语速 {speed} ｜ 音量 {volume}
                                            </Typography>
                                          )}
                                        </Box>
                                      </MenuItem>
                                    )
                                  })}
                                </Select>
                              </FormControl>
                            </Box>
        
                            <Box sx={{ mt: 1 }}>
                              <Typography variant="caption" color="text.secondary">
                                闊抽噺锛歿cv.volume}
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
                                璇€燂細{cv.speed ?? 1.0}
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
                                闊抽珮锛歿cv.pitch ?? 50}
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
                              <Tooltip title="浜戠绮剧‘璇曞惉鏁堟灉锛岃绋嶄綔绛夊緟...">
                                <span>
                                  <Button
                                    size="small"
                                    variant="outlined"
                                    onClick={() => handlePreviewCharacterVoice(cv)}
                                    disabled={!cv.voiceId || previewingCharacterId === cv.characterId}
                                  >
                                    {previewingCharacterId === cv.characterId ? '璇曞惉涓?..' : '璇曞惉'}
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

                {/* 馃啎 鑷姩鎺ㄨ崘澹扮嚎鎸夐挳 */}
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
                      {autoAssigningVoices ? '馃 鏅鸿兘鎺ㄨ崘涓?..' : '鉁?鍩轰簬浜虹墿鍗¤嚜鍔ㄦ帹鑽愬０绾?}
                    </Button>
                  </Box>
                )}
              </Grid>
            </Grid>
        
            <Box sx={{ mt: 3, display: 'flex', gap: 2, justifyContent: 'space-between' }}>
              <Button variant="outlined" onClick={() => setActiveStep(0)}>
                涓婁竴姝?
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
                寮€濮嬬敓鎴?({selectedChapters.length}绔?
              </Button>
            </Box>
          </Paper>
        )}

        {/* 姝ラ3: 鐢熸垚涓?*/}
        {activeStep === 2 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            {/* 椤堕儴鏁翠綋杩涘害鏉″拰鏂囧瓧宸茬Щ闄わ紝鏀逛负浠呭睍绀洪樁娈靛崱鐗囩姸鎬?*/}
            
            {/* 鏂板锛?涓樁娈佃缁嗗睍绀?*/}
            {(() => {
              console.log('娓叉煋闃舵淇℃伅 - currentTaskId:', currentTaskId)
              console.log('娓叉煋闃舵淇℃伅 - taskStatuses:', taskStatuses)
              console.log('娓叉煋闃舵淇℃伅 - selectedChapters:', selectedChapters)
              
              // 鍏堝皾璇曚娇鐢?selectedChapters[0]锛屽鏋滄病鏈夊垯鏌ユ壘绗竴涓彲鐢ㄧ殑 taskStatus
              const chapterId = selectedChapters[0]
              let taskStatus = chapterId ? taskStatuses[chapterId] : null
              
              // 濡傛灉娌℃湁鎵惧埌锛屽皾璇曚娇鐢ㄧ涓€涓彲鐢ㄧ殑 taskStatus
              if (!taskStatus && Object.keys(taskStatuses).length > 0) {
                const firstTaskStatusKey = Object.keys(taskStatuses)[0]
                taskStatus = taskStatuses[Number(firstTaskStatusKey)]
                console.log('浣跨敤绗竴涓彲鐢ㄧ殑 taskStatus:', firstTaskStatusKey, taskStatus)
              }
              
              // 濡傛灉杩樻槸娌℃湁鏁版嵁锛屼娇鐢ㄥ垵濮嬬姸鎬佺殑妯℃嫙鏁版嵁
              if (!taskStatus || !taskStatus.stages) {
                // 鍒涘缓鍒濆鐘舵€佺殑 taskStatus
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
                console.log('浣跨敤鍒濆鐘舵€佺殑妯℃嫙鏁版嵁')
              }
              
              console.log('娓叉煋闃舵璇︽儏:', taskStatus)
              
              return (
                <Box sx={{ mt: 3 }}>
                  <Typography variant="h6" sx={{ mb: 2, fontWeight: 600, color: '#333' }}>
                    馃幆 褰撳墠闃舵杩涘害
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
                        馃攳 鏌ョ湅鍓ф湰璇勫璇︽儏
                      </Button>
                    </Box>
                  )}
                </Box>
              )
            })()}
            
            {/* 搴曢儴鏁翠綋杩涘害鏉″凡绉婚櫎锛屼粎淇濈暀鏂囧瓧鎻愮ず */}
            <Typography variant="caption" sx={{ display: 'block', textAlign: 'center', mt: 1, color: 'text.secondary' }}>
              璇疯€愬績绛夊緟锛岀敓鎴愪腑璇峰嬁鍏抽棴椤甸潰...
            </Typography>
          </Paper>
        )}

        {/* 姝ラ4: 瀹屾垚 */}
        {activeStep === 3 && (
          <Paper sx={{ p: 4, backgroundColor: 'rgba(255,255,255,0.95)' }}>
            <Box sx={{ textAlign: 'center', mb: 3 }}>
              <CheckIcon sx={{ fontSize: 80, color: '#4caf50', mb: 2 }} />
              <Typography variant="h5" sx={{ mb: 2 }}>
                鐢熸垚瀹屾垚锛?
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                {lastGenerationMode === 'script_only'
                  ? '鍓ф湰涓庤瘎瀹″凡鐢熸垚锛屾帴涓嬫潵鍙互閫愮珷瀹＄銆佷慨鏀瑰墽鏈紝鍐嶇敓鎴愰煶棰?
                  : '鎮ㄧ殑鏈夊０涔﹀凡缁忓噯澶囧ソ浜?}
              </Typography>
            </Box>
            
            {/* 缁熻淇℃伅 */}
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
                      瀹屾垚绔犺妭
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
                      鎬绘椂闀?鍒嗛挓)
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
                      楼{(audiobookProject.total_cost || 0).toFixed(2)}
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.9 }}>
                      鎬绘垚鏈?
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>
            )}
            
            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap' }}>
              {/* 涓嬭浇鎸夐挳 - 鏀寔鍒嗙珷鑺備笅杞?*/}
              {audiobookProject.chapter_audios && audiobookProject.chapter_audios.length > 0 && (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center', width: '100%', mb: 2 }}>
                  {audiobookProject.chapter_audios.map((chapterAudio: any) => {
                    const chapter = chapters.find(c => c.id === chapterAudio.chapter_id)
                    const isPlaying = playingChapter === chapterAudio.chapter_id
                    
                    return (
                      <Box key={chapterAudio.id} sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                        <Box sx={{ display: 'flex', gap: 1 }}>
                          {/* 鍦ㄧ嚎鎾斁鎸夐挳 */}
                          <Tooltip title={isPlaying ? '鏆傚仠鎾斁' : '鍦ㄧ嚎鎾斁'}>
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
                              {chapter ? `绗?{chapter.chapter_number}绔燻 : `绔犺妭${chapterAudio.chapter_id}`}
                            </Button>
                          </Tooltip>
                          
                          {/* 涓嬭浇鎸夐挳 */}
                          <Tooltip title="涓嬭浇闊抽">
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
  
                          {/* 缂栬緫鍓ф湰鎸夐挳锛堝鏋滄湁鑴氭湰鍙敤锛岀敤鎴峰彲浠ョ洿鎺ュ皾璇曟墦寮€锛?*/}
                          <Tooltip title="缂栬緫鏈珷鑺傛湁澹板墽鏈?>
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
                              缂栬緫鍓ф湰
                            </Button>
                          </Tooltip>
                        </Box>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
                          <Chip
                            label={
                              chapterAudio.script_status === 'approved'
                                ? '鍓ф湰锛氬凡瀹℃壒'
                                : chapterAudio.script_status === 'reviewed'
                                ? '鍓ф湰锛氬凡淇敼'
                                : chapterAudio.script_status
                                ? '鍓ф湰锛氬緟澶勭悊'
                                : '鍓ф湰锛氭湭鐢熸垚'
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
                            label={chapterAudio.audio_path ? '闊抽锛氬凡鐢熸垚' : '闊抽锛氭湭鐢熸垚'}
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
                  鏌ョ湅鍓ф湰璇勫
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
                  瀵瑰凡瀹℃壒绔犺妭鐢熸垚闊抽
                </Button>
              )}
              
              <Button
                variant="contained"
                onClick={() => {
                  setActiveStep(0)
                  setSelectedProject(null)
                  setAudiobookProject(null)
                  audioRef.pause() // 娓呯悊鎾斁鐘舵€?
                  setPlayingChapter(null)
                }}
                sx={{
                  backgroundColor: '#9c27b0',
                  '&:hover': { backgroundColor: '#7b1fa2' },
                }}
              >
                鐢熸垚鏂伴」鐩?
              </Button>
            </Box>
          </Paper>
        )}
      </Container>

      {/* 閫氱煡娑堟伅 */}
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

      {/* 浠庢枃鏈垱寤洪」鐩璇濇 */}
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
        <DialogTitle>浠庢枃鏈垱寤烘柊椤圭洰</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            绮樿创鏁存湰涔︽垨闀跨瘒鏂囨湰锛岀郴缁熶細鑷姩鎷嗗垎绔犺妭骞跺垱寤洪」鐩紝闅忓悗鍙互鍦ㄦ湰椤电敓鎴愭湁澹颁功銆?
          </Alert>
          <TextField
            fullWidth
            label="椤圭洰鍚嶇О"
            value={newProjectTitle}
            onChange={(e) => setNewProjectTitle(e.target.value)}
            placeholder="渚嬪锛氭煇鏌愬皬璇?鏈夊０鍖栭」鐩?
            sx={{ mb: 2 }}
          />
          <TextField
            fullWidth
            multiline
            rows={12}
            label="涔︾睄鍏ㄦ枃鎴栭暱绡囨枃鏈?
            placeholder="灏嗘暣鏈功鐨勬枃鏈矘璐村埌杩欓噷..."
            value={newProjectText}
            onChange={(e) => setNewProjectText(e.target.value)}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            褰撳墠闀垮害锛歿newProjectText.trim().length.toLocaleString()} 瀛楋紱瓒呰繃 10,000 瀛楁椂锛岀偣鍑汇€屽垱寤哄苟寮€濮嬮厤缃煶鑹层€嶄細鑷姩璺宠浆鍒版媶涔﹀伐鍏枫€?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => !creatingFromBook && setNewProjectDialogOpen(false)} disabled={creatingFromBook}>
            鍙栨秷
          </Button>
          <Button
            onClick={() => {
              const text = newProjectText.trim()
              const title = newProjectTitle.trim() || '浠庤€崇晹鏄熸渤瀵煎叆鐨勪功绫?
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
            瀵煎叆鏁存湰涔﹀埌鎷嗕功宸ュ叿
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
            {creatingFromBook ? <CircularProgress size={20} color="inherit" /> : '鍒涘缓骞跺紑濮嬮厤缃煶鑹?}
          </Button>
        </DialogActions>
      </Dialog>
      
      {/* 鍓ф湰璐ㄩ噺璇勫寮圭獥 */}
      <Dialog
        open={scriptReviewDialogOpen}
        onClose={handleCloseScriptReviewDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>鍓ф湰璐ㄩ噺璇勫</DialogTitle>
        <DialogContent dividers>
          {!scriptReviewData ? (
            <Typography variant="body2" color="text.secondary">
              鏆傛棤璇勫鏁版嵁
            </Typography>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  鎬讳綋璇勫垎
                </Typography>
                <Typography variant="body2" sx={{ mt: 0.5 }}>
                  璇勫垎锛?
                  {scriptReviewData.report.overall_score?.toFixed
                    ? scriptReviewData.report.overall_score.toFixed(1)
                    : scriptReviewData.report.overall_score}{' '}
                  锛坽scriptReviewData.report.overall_grade || 'N/A'}锛夛紝闂鏁帮細
                  {scriptReviewData.report.issues_count ?? 0}
                </Typography>
                {scriptReviewData.report.revision_suggestions && (
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="body2" sx={{ fontWeight: 500, mb: 0.5 }}>
                      寤鸿锛?
                    </Typography>
                    {scriptReviewData.report.revision_suggestions.map((s: string, idx: number) => (
                      <Typography key={idx} variant="body2" color="text.secondary">
                        鈥?{s}
                      </Typography>
                    ))}
                  </Box>
                )}
              </Box>

              <Divider />

              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                  鍓ф湰鐗囨棰勮锛堝墠 {scriptReviewData.segments.length} 娈碉級
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
                              #{seg.index + 1} [{seg.type === 'dialogue' ? '瀵圭櫧' : seg.type}] {seg.speaker || '鏃佺櫧'}
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
                  褰撳墠寮圭獥灞曠ず鐨勬槸鑷姩鏀圭紪鍚庣殑鏈夊０鍓ф湰鐗囨锛屼粎鐢ㄤ簬浜哄伐瀹℃牳锛涘悗缁増鏈細鏀寔鐩存帴鍦ㄦ缂栬緫骞跺洖鍐欍€?
                </Typography>
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseScriptReviewDialog}>鍏抽棴</Button>
        </DialogActions>
      </Dialog>

      {/* 绔犺妭鍓ф湰缂栬緫寮圭獥 */}
      <ScriptEditorDialog
        open={scriptEditorDialogOpen}
        loading={scriptEditorLoading}
        chapter={scriptEditorChapter}
        data={scriptEditorData}
        onClose={handleCloseScriptEditorDialog}
        onChangeSegmentText={handleChangeScriptSegmentText}
        onSaveScript={handleSaveScript}
      />
      
      {/* 鏂板锛氬巻鍙茶褰曞璇濇 */}
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

export default AudiobookPage


