/**
 * 浏览器播放器组件
 *
 * 用于播放有声书并同步显示文本高亮。
 * 支持优先回读本地资产，并在刷新后恢复章节、进度和字幕状态。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  IconButton,
  Slider,
  Tooltip,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemButton,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Select,
  MenuItem,
  FormControl,
} from '@mui/material'
import {
  PlayArrow,
  Pause,
  SkipNext,
  SkipPrevious,
  VolumeUp,
  Subtitles,
  Download,
} from '@mui/icons-material'
import { styled } from '@mui/material/styles'
import { apiClient } from '@/services/api'
import { getLocalAssetBlob, saveLocalAsset } from '@/utils/localAssetVault'

const HighlightedText = styled('span')<{ active: boolean }>(({ theme, active }) => ({
  padding: '2px 4px',
  borderRadius: 4,
  transition: 'all 0.3s',
  backgroundColor: active ? theme.palette.primary.light + '40' : 'transparent',
  color: active ? theme.palette.primary.main : 'inherit',
  fontWeight: active ? 600 : 400,
}))

interface BrowserPlayerSegment {
  text?: string
  type?: string
  character?: string
  start_time?: number
  end_time?: number
}

interface BrowserPlayerChapter {
  chapter_id: number
  chapter_number?: number
  chapter_title?: string
  audio_url: string
  duration?: number
  has_subtitle?: boolean
  subtitle_url?: string | null
  segments?: BrowserPlayerSegment[]
}

export interface BrowserPlayerProjectData {
  project_id: number
  project_title: string
  chapters: BrowserPlayerChapter[]
  total_duration: number
}

interface BrowserPlayerProps {
  projectData: BrowserPlayerProjectData
  open: boolean
  onClose: () => void
}

interface BrowserPlayerStateSnapshot {
  currentChapterIndex: number
  currentTime: number
  volume: number
  subtitleFormat: 'srt' | 'vtt' | 'ass'
  showSubtitles: boolean
  wasPlaying: boolean
}

const PLAYER_STATE_STORAGE_PREFIX = 'audiobook_browser_player_state_v1'
const DEFAULT_PLAYER_STATE: BrowserPlayerStateSnapshot = {
  currentChapterIndex: 0,
  currentTime: 0,
  volume: 1,
  subtitleFormat: 'srt',
  showSubtitles: true,
  wasPlaying: false,
}

function buildPlayerStateKey(projectId: number): string {
  return `${PLAYER_STATE_STORAGE_PREFIX}:${projectId}`
}

function buildAudiobookChapterAssetUuid(audiobookProjectId: number, chapterId: number): string {
  return `audiobook-${audiobookProjectId}-${chapterId}`
}

function buildAudiobookSubtitleAssetUuid(
  audiobookProjectId: number,
  chapterId: number,
  subtitleFormat: BrowserPlayerStateSnapshot['subtitleFormat'],
): string {
  return `audiobook-subtitle-${audiobookProjectId}-${chapterId}-${subtitleFormat}`
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.URL.revokeObjectURL(url)
}

function clampChapterIndex(index: number, total: number): number {
  if (total <= 0) return 0
  return Math.min(Math.max(index, 0), total - 1)
}

const BrowserPlayer: React.FC<BrowserPlayerProps> = ({ projectData, open, onClose }) => {
  const [currentChapterIndex, setCurrentChapterIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [subtitleFormat, setSubtitleFormat] = useState<'srt' | 'vtt' | 'ass'>('srt')
  const [showSubtitles, setShowSubtitles] = useState(true)
  const [highlightedSegmentIndex, setHighlightedSegmentIndex] = useState<number | null>(null)
  const [usingLocalAsset, setUsingLocalAsset] = useState(false)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const textContainerRef = useRef<HTMLDivElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const restoreStateRef = useRef<BrowserPlayerStateSnapshot | null>(null)

  const currentChapter = projectData?.chapters?.[currentChapterIndex]
  const persistedCurrentSecond = Math.floor(currentTime)

  const revokeCurrentObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      window.URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  const persistSnapshot = useCallback(
    (snapshot: BrowserPlayerStateSnapshot) => {
      if (!projectData?.project_id) return
      localStorage.setItem(buildPlayerStateKey(projectData.project_id), JSON.stringify(snapshot))
    },
    [projectData?.project_id],
  )

  const scrollToSegment = useCallback((index: number) => {
    if (!textContainerRef.current) return

    const element = textContainerRef.current.querySelector(`[data-segment-index="${index}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [])

  const updateHighlight = useCallback(
    (time: number) => {
      if (!currentChapter?.segments?.length) {
        setHighlightedSegmentIndex(null)
        return
      }

      for (let i = 0; i < currentChapter.segments.length; i += 1) {
        const segment = currentChapter.segments[i]
        if (segment.start_time === undefined || segment.end_time === undefined) {
          continue
        }
        if (time >= segment.start_time && time < segment.end_time) {
          setHighlightedSegmentIndex(i)
          scrollToSegment(i)
          return
        }
      }

      setHighlightedSegmentIndex(null)
    },
    [currentChapter, scrollToSegment],
  )

  const handleNext = useCallback(() => {
    if (currentChapterIndex < projectData.chapters.length - 1) {
      setCurrentChapterIndex((prev) => prev + 1)
    }
  }, [currentChapterIndex, projectData.chapters.length])

  const handlePrevious = useCallback(() => {
    if (currentChapterIndex > 0) {
      setCurrentChapterIndex((prev) => prev - 1)
    }
  }, [currentChapterIndex])

  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
    }

    const audio = audioRef.current
    audio.volume = volume

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      updateHighlight(audio.currentTime)
    }

    const handleLoadedMetadata = () => {
      const nextDuration = Number.isFinite(audio.duration) ? audio.duration : 0
      setDuration(nextDuration)

      const restoreState = restoreStateRef.current
      if (restoreState && restoreState.currentChapterIndex === currentChapterIndex) {
        const nextTime = Math.max(
          0,
          Math.min(restoreState.currentTime || 0, nextDuration || restoreState.currentTime || 0),
        )

        if (nextTime > 0) {
          audio.currentTime = nextTime
          setCurrentTime(nextTime)
          updateHighlight(nextTime)
        } else {
          setCurrentTime(0)
        }

        const shouldResumePlayback = restoreState.wasPlaying
        restoreStateRef.current = null

        if (shouldResumePlayback && open) {
          void audio.play().then(() => {
            setIsPlaying(true)
          }).catch(() => {
            setIsPlaying(false)
          })
        }
      }
    }

    const handleEnded = () => {
      setIsPlaying(false)
      handleNext()
    }

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('ended', handleEnded)

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('ended', handleEnded)
    }
  }, [currentChapterIndex, handleNext, open, updateHighlight, volume])

  useEffect(() => {
    if (!open || !projectData?.project_id) {
      return
    }

    const raw = localStorage.getItem(buildPlayerStateKey(projectData.project_id))
    let nextState = DEFAULT_PLAYER_STATE

    if (raw) {
      try {
        const saved = JSON.parse(raw) as Partial<BrowserPlayerStateSnapshot>
        nextState = {
          currentChapterIndex: clampChapterIndex(
            Number(saved.currentChapterIndex ?? DEFAULT_PLAYER_STATE.currentChapterIndex),
            projectData.chapters.length,
          ),
          currentTime: Math.max(0, Number(saved.currentTime ?? DEFAULT_PLAYER_STATE.currentTime)),
          volume: Math.min(1, Math.max(0, Number(saved.volume ?? DEFAULT_PLAYER_STATE.volume))),
          subtitleFormat:
            saved.subtitleFormat === 'vtt' || saved.subtitleFormat === 'ass'
              ? saved.subtitleFormat
              : 'srt',
          showSubtitles: typeof saved.showSubtitles === 'boolean'
            ? saved.showSubtitles
            : DEFAULT_PLAYER_STATE.showSubtitles,
          wasPlaying: Boolean(saved.wasPlaying),
        }
      } catch {
        nextState = DEFAULT_PLAYER_STATE
      }
    }

    restoreStateRef.current = nextState
    setCurrentChapterIndex(nextState.currentChapterIndex)
    setCurrentTime(nextState.currentTime)
    setVolume(nextState.volume)
    setSubtitleFormat(nextState.subtitleFormat)
    setShowSubtitles(nextState.showSubtitles)
    setIsPlaying(false)
  }, [open, projectData?.project_id, projectData.chapters.length])

  useEffect(() => {
    if (!audioRef.current || !currentChapter) {
      return
    }

    let cancelled = false
    const audio = audioRef.current

    const loadAudioSource = async () => {
      audio.pause()
      setIsPlaying(false)
      setHighlightedSegmentIndex(null)
      revokeCurrentObjectUrl()

      try {
        const assetUuid = buildAudiobookChapterAssetUuid(projectData.project_id, currentChapter.chapter_id)
        const localBlob = await getLocalAssetBlob(assetUuid).catch(() => null)
        if (cancelled) return

        if (localBlob) {
          const localUrl = window.URL.createObjectURL(localBlob)
          objectUrlRef.current = localUrl
          audio.src = localUrl
          setUsingLocalAsset(true)
        } else {
          const response = await apiClient.getAudiobookChapterAudioFile(
            projectData.project_id,
            currentChapter.chapter_id,
          )
          const remoteBlob = response.data as Blob
          try {
            await saveLocalAsset({
              assetUuid,
              mediaKind: 'audio',
              blob: remoteBlob,
              mimeType: remoteBlob.type || response.headers?.['content-type'] || 'audio/mpeg',
              fileSize: remoteBlob.size,
              sourceModule: 'audiobook',
              title: currentChapter.chapter_title || `第${currentChapter.chapter_number || currentChapterIndex + 1}章 音频`,
              sourceUri: currentChapter.audio_url,
              previewUri: currentChapter.audio_url,
              downloadUri: currentChapter.audio_url,
              metadata: {
                audiobook_project_id: projectData.project_id,
                chapter_id: currentChapter.chapter_id,
                chapter_number: currentChapter.chapter_number ?? currentChapterIndex + 1,
                chapter_title: currentChapter.chapter_title || null,
              },
            })
          } catch (cacheError) {
            console.warn('缓存播放器音频失败，将继续使用远端音频:', cacheError)
          }
          if (cancelled) return
          const remoteUrl = window.URL.createObjectURL(remoteBlob)
          objectUrlRef.current = remoteUrl
          audio.src = remoteUrl
          setUsingLocalAsset(false)
        }

        audio.load()
      } catch (error) {
        console.error('加载播放器音频失败:', error)
        audio.removeAttribute('src')
        audio.load()
        setUsingLocalAsset(false)
        setDuration(0)
        setCurrentTime(0)
        return
      }

      const restoreState = restoreStateRef.current
      if (!restoreState || restoreState.currentChapterIndex !== currentChapterIndex) {
        setCurrentTime(0)
      }

      setDuration(Number.isFinite(currentChapter.duration) ? Number(currentChapter.duration) : 0)
    }

    void loadAudioSource()

    return () => {
      cancelled = true
    }
  }, [currentChapter, currentChapterIndex, projectData.project_id, revokeCurrentObjectUrl])

  useEffect(() => {
    if (!audioRef.current) return
    audioRef.current.volume = volume
  }, [volume])

  useEffect(() => {
    if (!projectData?.project_id || !open) return

    persistSnapshot({
      currentChapterIndex,
      currentTime: persistedCurrentSecond,
      volume,
      subtitleFormat,
      showSubtitles,
      wasPlaying: isPlaying,
    })
  }, [
    currentChapterIndex,
    isPlaying,
    open,
    persistSnapshot,
    persistedCurrentSecond,
    showSubtitles,
    subtitleFormat,
    volume,
    projectData?.project_id,
  ])

  useEffect(() => {
    if (open || !audioRef.current) return
    audioRef.current.pause()
    setIsPlaying(false)
  }, [open])

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
      revokeCurrentObjectUrl()
    }
  }, [revokeCurrentObjectUrl])

  const handlePlayPause = async () => {
    if (!audioRef.current) return

    try {
      if (audioRef.current.paused) {
        await audioRef.current.play()
        setIsPlaying(true)
      } else {
        audioRef.current.pause()
        setIsPlaying(false)
      }
    } catch (error) {
      console.error('播放失败:', error)
      setIsPlaying(false)
    }
  }

  const handleSeek = (_event: Event, value: number | number[]) => {
    if (!audioRef.current) return

    const nextTime = value as number
    audioRef.current.currentTime = nextTime
    setCurrentTime(nextTime)
    updateHighlight(nextTime)
  }

  const handleVolumeChange = (_event: Event, value: number | number[]) => {
    setVolume(value as number)
  }

  const handleDownloadSubtitle = async () => {
    if (!currentChapter?.subtitle_url) return

    try {
      const assetUuid = buildAudiobookSubtitleAssetUuid(
        projectData.project_id,
        currentChapter.chapter_id,
        subtitleFormat,
      )
      let subtitleBlob = await getLocalAssetBlob(assetUuid).catch(() => null)

      if (!subtitleBlob) {
        const response = await apiClient.getChapterSubtitle(
          projectData.project_id,
          currentChapter.chapter_id,
          subtitleFormat,
        )
        subtitleBlob = response.data as Blob
        try {
          await saveLocalAsset({
            assetUuid,
            mediaKind: 'subtitle',
            blob: subtitleBlob,
            mimeType: subtitleBlob.type || response.headers?.['content-type'] || 'text/plain',
            fileSize: subtitleBlob.size,
            sourceModule: 'audiobook',
            title: `${currentChapter.chapter_title || `chapter_${currentChapter.chapter_id}`}.${subtitleFormat}`,
            sourceUri: `${currentChapter.subtitle_url}?format=${subtitleFormat}`,
            previewUri: `${currentChapter.subtitle_url}?format=${subtitleFormat}`,
            downloadUri: `${currentChapter.subtitle_url}?format=${subtitleFormat}`,
            metadata: {
              audiobook_project_id: projectData.project_id,
              chapter_id: currentChapter.chapter_id,
              chapter_number: currentChapter.chapter_number ?? currentChapterIndex + 1,
              subtitle_format: subtitleFormat,
            },
          })
        } catch (cacheError) {
          console.warn('缓存字幕失败，将继续直接下载:', cacheError)
        }
      }

      if (!subtitleBlob) {
        throw new Error('subtitle unavailable')
      }

      triggerBlobDownload(subtitleBlob, `chapter_${currentChapter.chapter_id}.${subtitleFormat}`)
    } catch (error) {
      console.error('下载字幕失败:', error)
    }
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  if (!open || !projectData) return null

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">{projectData.project_title}</Typography>
          <Box display="flex" gap={1} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 100 }}>
              <Select
                value={subtitleFormat}
                onChange={(e) => setSubtitleFormat(e.target.value as 'srt' | 'vtt' | 'ass')}
              >
                <MenuItem value="srt">SRT</MenuItem>
                <MenuItem value="vtt">VTT</MenuItem>
                <MenuItem value="ass">ASS</MenuItem>
              </Select>
            </FormControl>
            <Tooltip title={showSubtitles ? '隐藏字幕' : '显示字幕'}>
              <IconButton
                color={showSubtitles ? 'primary' : 'default'}
                onClick={() => setShowSubtitles(!showSubtitles)}
              >
                <Subtitles />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>
      </DialogTitle>

      <DialogContent dividers>
        <Box display="flex" gap={3} height="70vh">
          <Box width={280} sx={{ overflowY: 'auto', borderRight: 1, borderColor: 'divider', pr: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              章节列表
            </Typography>
            <List dense>
              {projectData.chapters.map((chapter, index) => (
                <ListItem key={chapter.chapter_id} disablePadding sx={{ mb: 0.5 }}>
                  <ListItemButton
                    selected={currentChapterIndex === index}
                    onClick={() => setCurrentChapterIndex(index)}
                  >
                    <ListItemText
                      primary={`第${chapter.chapter_number || index + 1}章`}
                      secondary={chapter.chapter_title || ''}
                      primaryTypographyProps={{
                        variant: 'body2',
                        sx: { fontWeight: currentChapterIndex === index ? 600 : 400 },
                      }}
                      secondaryTypographyProps={{
                        variant: 'caption',
                      }}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {formatTime(chapter.duration || 0)}
                    </Typography>
                  </ListItemButton>
                </ListItem>
              ))}
            </List>
          </Box>

          <Box flex={1} display="flex" flexDirection="column">
            <Box sx={{ mb: 2 }}>
              <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                <Typography variant="h6">
                  第{currentChapter?.chapter_number || currentChapterIndex + 1}章：{currentChapter?.chapter_title || ''}
                </Typography>
                {usingLocalAsset && <Chip label="本地音频" size="small" color="success" variant="outlined" />}
              </Box>
              {currentChapter?.has_subtitle && (
                <Button
                  size="small"
                  startIcon={<Download />}
                  onClick={handleDownloadSubtitle}
                  sx={{ mt: 0.5 }}
                >
                  下载字幕 ({subtitleFormat.toUpperCase()})
                </Button>
              )}
            </Box>

            {showSubtitles && currentChapter?.segments && (
              <Paper
                ref={textContainerRef}
                sx={{ p: 2, mb: 2, flex: 1, overflowY: 'auto', minHeight: 200 }}
              >
                <Box>
                  {currentChapter.segments.map((segment, index) => (
                    <Box
                      key={index}
                      data-segment-index={index}
                      sx={{ mb: 1, p: 0.5, borderRadius: 1 }}
                    >
                      {segment.type === 'dialogue' && segment.character && (
                        <Chip
                          label={segment.character}
                          size="small"
                          sx={{ mb: 0.5, mr: 1 }}
                          color="primary"
                          variant="outlined"
                        />
                      )}
                      <HighlightedText active={highlightedSegmentIndex === index}>
                        {segment.text || ''}
                      </HighlightedText>
                    </Box>
                  ))}
                </Box>
              </Paper>
            )}

            <Box sx={{ mt: 'auto' }}>
              <Slider
                value={currentTime}
                max={duration || 100}
                onChange={handleSeek}
                sx={{ mb: 1 }}
              />
              <Box display="flex" alignItems="center" gap={2}>
                <Typography variant="caption" sx={{ minWidth: 50 }}>
                  {formatTime(currentTime)}
                </Typography>
                <IconButton onClick={handlePrevious} disabled={currentChapterIndex === 0}>
                  <SkipPrevious />
                </IconButton>
                <IconButton onClick={handlePlayPause} size="large">
                  {isPlaying ? <Pause fontSize="large" /> : <PlayArrow fontSize="large" />}
                </IconButton>
                <IconButton onClick={handleNext} disabled={currentChapterIndex >= projectData.chapters.length - 1}>
                  <SkipNext />
                </IconButton>
                <Typography variant="caption" sx={{ minWidth: 50, textAlign: 'right' }}>
                  {formatTime(duration)}
                </Typography>
                <Box display="flex" alignItems="center" gap={0.5} sx={{ ml: 'auto' }}>
                  <VolumeUp fontSize="small" />
                  <Slider
                    value={volume}
                    step={0.01}
                    max={1}
                    onChange={handleVolumeChange}
                    sx={{ width: 100 }}
                  />
                </Box>
              </Box>
            </Box>
          </Box>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>关闭</Button>
      </DialogActions>
    </Dialog>
  )
}

export default BrowserPlayer
