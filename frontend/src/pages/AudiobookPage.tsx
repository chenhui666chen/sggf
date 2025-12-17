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
import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
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
  ListItemSecondaryAction,
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
} from '@mui/material'
import {
  ArrowBack as ArrowBackIcon,
  Headphones as HeadphonesIcon,
  PlayArrow as PlayIcon,
  Pause as PauseIcon,
  Download as DownloadIcon,
  Settings as SettingsIcon,
  AutoStories as BookIcon,
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
  novel_genre: string
  novel_theme: string
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

const VOICE_PRESETS: { id: string; label: string; description: string }[] = [
  {
    id: 'male_young_energetic',
    label: '年轻男主（热血）',
    description: '年轻男性，活力充沛，适合热血主角',
  },
  {
    id: 'male_adult_calm',
    label: '成熟男声（沉稳）',
    description: '成熟男性，沉稳冷静，适合智者角色',
  },
  {
    id: 'female_young_gentle',
    label: '年轻女主（温柔）',
    description: '年轻女性，温柔体贴，适合女主角',
  },
  {
    id: 'female_adult_cold',
    label: '成熟女性（高冷）',
    description: '成熟女性，高冷理智，适合女强人',
  },
  {
    id: 'elder_wise',
    label: '长者旁白（睿智）',
    description: '长者，睿智稳重，适合导师或老者角色',
  },
]

export default function AudiobookPage() {
  const navigate = useNavigate()

  // 状态管理
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [selectedChapters, setSelectedChapters] = useState<number[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [generating, setGenerating] = useState<boolean>(false)
  const [activeStep, setActiveStep] = useState<number>(0)
  const [characterVoices, setCharacterVoices] = useState<CharacterVoiceSetting[]>([])
  const [loadingCharacters, setLoadingCharacters] = useState<boolean>(false)
  const [audiobookProject, setAudiobookProject] = useState<any>(null)
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' as 'success' | 'error' | 'info' })
  
  // 新增：任务状态追踪
  const [taskStatuses, setTaskStatuses] = useState<Record<number, TaskStatus>>({})
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  
  // 新增：音频播放状态
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [audioRef] = useState<HTMLAudioElement>(new Audio())
  
  // 新增：历史记录相关
  const [showHistory, setShowHistory] = useState<boolean>(false)
  const [historyProjects, setHistoryProjects] = useState<any[]>([])
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false)
  // 新增：删除确认对话框
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<boolean>(false)
  const [deletingProject, setDeletingProject] = useState<any>(null)
  // 新增：角色试听状态
  const [previewingCharacterId, setPreviewingCharacterId] = useState<number | null>(null)

  const steps = ['选择项目', '配置音色', '生成有声书', '完成']

  // 获取项目列表
  useEffect(() => {
    fetchProjects()
  }, [])
  
  // 新增：获取历史记录
  const fetchHistory = async () => {
    if (!selectedProject) return
    
    setLoadingHistory(true)
    try {
      const response = await fetch(
        `/api/v1/audiobook/projects/by-project/${selectedProject.id}`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        }
      )
      
      if (response.ok) {
        const data = await response.json()
        setHistoryProjects(data)
      } else {
        console.error('获取历史记录失败:', response.status)
      }
    } catch (error) {
      console.error('获取历史记录失败:', error)
    } finally {
      setLoadingHistory(false)
    }
  }
  
  // 新增：查看历史项目详情
  const handleViewHistory = async (audiobookProjectId: number) => {
    try {
      const response = await fetch(
        `/api/v1/audiobook/projects/${audiobookProjectId}`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        }
      )
      
      if (response.ok) {
        const data = await response.json()
        setAudiobookProject(data)
        setActiveStep(3) // 跳转到完成页面
        setShowHistory(false)
      } else {
        setSnackbar({ open: true, message: '加载失败', severity: 'error' })
      }
    } catch (error) {
      console.error('查看历史失败:', error)
      setSnackbar({ open: true, message: '网络错误', severity: 'error' })
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
      const response = await fetch(
        `/api/v1/audiobook/projects/${deletingProject.id}`,
        {
          method: 'DELETE',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            'Content-Type': 'application/json',
          },
        }
      )
      
      if (response.ok) {
        // 删除成功，刷新历史记录
        setSnackbar({ open: true, message: '删除成功', severity: 'success' })
        setShowDeleteConfirm(false)
        setDeletingProject(null)
        fetchHistory() // 重新获取历史记录
      } else {
        const errorData = await response.json()
        setSnackbar({ open: true, message: errorData.detail || '删除失败', severity: 'error' })
      }
    } catch (error) {
      console.error('删除失败:', error)
      setSnackbar({ open: true, message: '网络错误，删除失败', severity: 'error' })
    }
  }

  const fetchProjects = async () => {
    try {
      const response = await fetch('/api/v1/projects', {  // 移除尾部斜杠
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setProjects(data)
      } else {
        console.error('获取项目失败:', response.status)
      }
    } catch (error) {
      console.error('获取项目失败:', error)
      setSnackbar({ open: true, message: '网络错误，无法加载项目列表', severity: 'error' })
    }
  }

  // 选择项目
  const handleSelectProject = async (project: Project) => {
    setSelectedProject(project)
    setLoading(true)
    setCharacterVoices([])

    const narratorVoice: CharacterVoiceSetting = {
      characterId: 0,
      name: '旁白',
      gender: '中性',
      role: '旁白',
      voiceId: '',
      volume: 50,
      speed: 1.0,
      pitch: 50,
    }
    
    try {
      const headers: HeadersInit = {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
      }

      // 获取章节列表
      const chaptersResponse = await fetch(`/api/v1/projects/${project.id}/chapters`, {
        headers,
      })
      if (chaptersResponse.ok) {
        const data = await chaptersResponse.json()
        setChapters(data)
        setSelectedChapters(data.map((c: Chapter) => c.id))  // 默认全选
      } else {
        setSnackbar({ open: true, message: '获取章节失败', severity: 'error' })
      }

      // 获取角色列表（用于音频配置）
      setLoadingCharacters(true)
      try {
        const charactersResponse = await fetch(`/api/v1/projects/${project.id}/characters`, {
          headers,
        })
        if (charactersResponse.ok) {
          const charactersData = await charactersResponse.json()
          const characterVoicesFromApi: CharacterVoiceSetting[] = charactersData.map((c: any) => ({
            characterId: c.id,
            name: c.name,
            gender: c.gender,
            role: c.role,
            voiceId: '',
            volume: 50,
            speed: 1.0,
            pitch: 50,
          }))
          const initialVoices: CharacterVoiceSetting[] = [
            narratorVoice,
            ...characterVoicesFromApi,
          ]
          setCharacterVoices(initialVoices)
        } else {
          console.warn('获取角色列表失败:', charactersResponse.status)
          setCharacterVoices([narratorVoice])
        }
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

  const handlePreviewCharacterVoice = async (cv: CharacterVoiceSetting) => {
    if (!cv.voiceId) {
      setSnackbar({ open: true, message: '请先为该角色选择音色再试听', severity: 'error' })
      return
    }

    try {
      setPreviewingCharacterId(cv.characterId)
      const token = localStorage.getItem('access_token')
      const text = '当你真的喜欢一个人的时候就容易说傻话办蠢事。'

      const response = await fetch('/api/v1/audiobook/tts/preview', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          text,
          voice_id: cv.voiceId,
          volume: cv.volume,
          speed: cv.speed,
          pitch: cv.pitch,
        }),
      })

      if (!response.ok) {
        throw new Error('试听请求失败')
      }

      const blob = await response.blob()
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

  // 开始生成
  const handleGenerate = async () => {
    if (!selectedProject || selectedChapters.length === 0) {
      setSnackbar({ open: true, message: '请至少选择一个章节', severity: 'error' })
      return
    }
    
    setGenerating(true)
    setActiveStep(2)
    setTaskStatuses({})  // 清空之前的状态

    try {
      // 调用生成API
      const voiceConfigPayload =
        characterVoices
          .filter((cv) => cv.voiceId)
          .map((cv) => ({
            character_name: cv.name,
            voice_id: cv.voiceId,
            volume: cv.volume,
            speed: cv.speed,
            pitch: cv.pitch,
          }))

      const response = await fetch('/api/v1/audiobook/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({
          project_id: selectedProject.id,
          chapter_ids: selectedChapters,
          tts_provider: 'aliyun',
          enable_cache: true,
          voice_config: voiceConfigPayload,
        }),
      })
      
      if (response.ok) {
        const data = await response.json()
        setAudiobookProject(data)
        
        // 轮询查询项目进度
        const projectId = data.audiobook_project_id
        const pollInterval = setInterval(async () => {
          const statusResponse = await fetch(`/api/v1/audiobook/projects/${projectId}`, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            },
          })
          
          if (statusResponse.ok) {
            const statusData = await statusResponse.json()
            
            // 新增：获取第一个章节的task_id（如果有）
            if (statusData.chapter_audios && statusData.chapter_audios.length > 0) {
              const firstTaskId = statusData.chapter_audios[0].task_id
              if (firstTaskId && !currentTaskId) {
                setCurrentTaskId(firstTaskId)
              }
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
          }
        }, 2000) // 每2秒查询一次
      } else {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || '生成请求失败')
      }
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
  
  // 新增：轮询单个任务状态（用于实时显示8个阶段）
  useEffect(() => {
    if (!currentTaskId || !generating) return
    
    const pollTaskStatus = async () => {
      try {
        const response = await fetch(`/api/v1/audiobook/tasks/${currentTaskId}/status`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        
        if (response.ok) {
          const taskStatus: TaskStatus = await response.json()
          setTaskStatuses(prev => ({
            ...prev,
            [taskStatus.chapter_id]: taskStatus
          }))
        }
      } catch (error) {
        console.error('查询任务状态失败:', error)
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
    const stageNames = {
      strategy: '策略制定',
      script_adaptation: '剧本改编',
      voice_design: '音色设计',
      sound_design: '音效设计',
      music_composition: '音乐编曲',
      tts_synthesis: 'TTS合成',
      audio_mixing: '音频混合',
      quality_review: '质量评审'
    }
    
    const statusIcons = {
      pending: '⌛',
      running: '🔄',
      completed: '✅',
      failed: '❌'
    }
    
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {Object.entries(taskStatus.stages).map(([stageName, stageInfo]) => (
          <Paper 
            key={stageName}
            sx={{ 
              p: 2,
              border: stageInfo.status === 'running' ? '2px solid #9c27b0' : '1px solid #e0e0e0',
              backgroundColor: stageInfo.status === 'completed' ? 'rgba(76, 175, 80, 0.05)' : 'white'
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="body2" sx={{ minWidth: 20 }}>
                  {statusIcons[stageInfo.status]}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {stageNames[stageName as keyof typeof stageNames] || stageName}
                </Typography>
              </Box>
              <Chip 
                label={stageInfo.status === 'running' ? '进行中' : 
                       stageInfo.status === 'completed' ? '完成' : 
                       stageInfo.status === 'failed' ? '失败' : '等待中'}
                size="small"
                sx={{
                  backgroundColor: stageInfo.status === 'running' ? '#9c27b0' : 
                                   stageInfo.status === 'completed' ? '#4caf50' :
                                   stageInfo.status === 'failed' ? '#f44336' : '#9e9e9e',
                  color: 'white'
                }}
              />
            </Box>
            <LinearProgress 
              variant="determinate" 
              value={stageInfo.progress * 100} 
              sx={{ 
                mt: 1, 
                height: 6, 
                borderRadius: 3,
                backgroundColor: 'rgba(156, 39, 176, 0.1)',
                '& .MuiLinearProgress-bar': {
                  backgroundColor: stageInfo.status === 'completed' ? '#4caf50' : '#9c27b0'
                }
              }}
            />
            {stageInfo.metrics && Object.keys(stageInfo.metrics).length > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                {Object.entries(stageInfo.metrics).slice(0, 2).map(([key, value]) => (
                  `${key}: ${typeof value === 'object' ? JSON.stringify(value).slice(0, 30) : value}`
                )).join(' | ')}
              </Typography>
            )}
          </Paper>
        ))}
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
                  <Grid item xs={12} sm={6} md={4} key={project.id}>
                    <Card
                      sx={{
                        cursor: 'pointer',
                        transition: 'all 0.3s',
                        backgroundColor: 'rgba(255,255,255,0.95)',
                        position: 'relative',
                        overflow: 'hidden',
                        '&:hover': {
                          transform: 'translateY(-8px)',
                          boxShadow: '0 12px 32px rgba(156, 39, 176, 0.3)',
                        },
                        '&::before': {
                          content: '""',
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          right: 0,
                          height: '4px',
                          background: 'linear-gradient(90deg, #9c27b0, #e91e63)',
                        },
                      }}
                      onClick={() => handleSelectProject(project)}
                    >
                      <CardContent sx={{ pt: 3 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                          <BookIcon sx={{ mr: 1, color: '#9c27b0', fontSize: 28 }} />
                          <Typography variant="h6" sx={{ fontWeight: 600 }}>
                            {project.title}
                          </Typography>
                        </Box>
                        <Typography 
                          variant="body2" 
                          color="text.secondary" 
                          sx={{ 
                            mb: 2,
                            minHeight: 40,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                          }}
                        >
                          {project.description || '暂无描述'}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                          <Chip
                            label={project.genre || '未分类'}
                            size="small"
                            sx={{ 
                              backgroundColor: '#9c27b020', 
                              color: '#9c27b0',
                              fontWeight: 500,
                            }}
                          />
                        </Box>
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
                                  {VOICE_PRESETS.map((preset) => (
                                    <MenuItem key={preset.id} value={preset.id}>
                                      {preset.label}
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
                                <Button
                                  size="small"
                                  variant="outlined"
                                  onClick={() => handlePreviewCharacterVoice(cv)}
                                  disabled={!cv.voiceId || previewingCharacterId === cv.characterId}
                                >
                                  {previewingCharacterId === cv.characterId ? '试听中...' : '试听'}
                                </Button>
                              </Tooltip>
                            </Box>
                          </Box>
                        </ListItem>
                      ))}
                    </List>
                  </Paper>
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
            <Box sx={{ textAlign: 'center', mb: 3 }}>
              <CircularProgress size={80} sx={{ mb: 3, color: '#9c27b0' }} />
              <Typography variant="h6" sx={{ mb: 2 }}>
                正在生成有声书...
              </Typography>
              {audiobookProject && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    进度: {audiobookProject.completed_chapters || 0}/{audiobookProject.total_chapters || selectedChapters.length} 章
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    已生成 {((audiobookProject.total_duration || 0) / 60).toFixed(1)} 分钟 | 成本 ¥{(audiobookProject.total_cost || 0).toFixed(2)}
                  </Typography>
                </>
              )}
            </Box>
            
            {/* 新增：8个阶段详细展示 */}
            {currentTaskId && taskStatuses[selectedChapters[0]] && (
              <Box sx={{ mt: 4 }}>
                <Typography variant="subtitle1" sx={{ mb: 2, fontWeight: 600 }}>
                  当前阶段进度
                </Typography>
                {renderStageDetails(taskStatuses[selectedChapters[0]])}
              </Box>
            )}
            
            <LinearProgress 
              sx={{ 
                mt: 3, 
                height: 8, 
                borderRadius: 4,
                backgroundColor: 'rgba(156, 39, 176, 0.1)',
                '& .MuiLinearProgress-bar': {
                  backgroundColor: '#9c27b0'
                }
              }}
              variant={audiobookProject ? "determinate" : "indeterminate"}
              value={audiobookProject ? ((audiobookProject.completed_chapters || 0) / (audiobookProject.total_chapters || 1)) * 100 : 0}
            />
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
                您的有声书已经准备好了
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
                      <Box key={chapterAudio.id} sx={{ display: 'flex', gap: 1 }}>
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
                      </Box>
                    )
                  })}
                </Box>
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
      
      {/* 新增：历史记录对话框 */}
      <Dialog
        open={showHistory}
        onClose={() => setShowHistory(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#9c27b0' }} />
            <Typography variant="h6">
              {selectedProject?.title} - 历史生成记录
            </Typography>
          </Box>
        </DialogTitle>
        <DialogContent>
          {loadingHistory ? (
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
                  onClick={() => handleViewHistory(project.id)}
                >
                  <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      <Chip
                        label={project.status === 'completed' ? '已完成' : 
                               project.status === 'processing' ? '生成中' : 
                               project.status === 'failed' ? '失败' : '等待中'}
                        size="small"
                        sx={{
                          backgroundColor: 
                            project.status === 'completed' ? '#4caf50' :
                            project.status === 'processing' ? '#ff9800' :
                            project.status === 'failed' ? '#f44336' : '#9e9e9e',
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
                        <>
                          <Typography variant="body2" color="text.secondary">
                            🕒 {((project.total_duration || 0) / 60).toFixed(1)}分钟
                          </Typography>
                        </>
                      )}
                    </Box>
                  </Box>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleViewHistory(project.id)
                    }}
                    sx={{ color: '#9c27b0' }}
                  >
                    <PlayIcon />
                  </IconButton>
                  <IconButton
                    edge="end"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleOpenDeleteConfirm(project)
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
          <Button onClick={() => setShowHistory(false)}>
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      {/* 新增：删除确认对话框 */}
      <Dialog
        open={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon sx={{ color: '#f44336' }} />
            <Typography variant="h6">
              确认删除
            </Typography>
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
                  章节：{deletingProject.completed_chapters}/{deletingProject.total_chapters} | 
                  时长：{((deletingProject.total_duration || 0) / 60).toFixed(1)}分钟
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  创建时间：{new Date(deletingProject.created_at).toLocaleString('zh-CN')}
                </Typography>
              </Box>
            )}
            <Alert severity="warning" sx={{ mt: 2 }}>
              此操作将永久删除该项目及其所有音频文件，无法恢复！
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowDeleteConfirm(false)}>
            取消
          </Button>
          <Button 
            onClick={handleDeleteProject} 
            variant="contained" 
            color="error"
            autoFocus
          >
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
