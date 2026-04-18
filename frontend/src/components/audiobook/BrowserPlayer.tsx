/**
 * 浏览器播放器组件
 * 
 * 用于播放有声书并同步显示文本高亮
 * 类似 Kindle Whispersync 或 Google Play Books read-along
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Box,
  Typography,
  Paper,
  IconButton,
  Slider,
  Tooltip,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  ListItemButton,
  ListItemIcon,
  Collapse,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material'
import {
  PlayArrow,
  Pause,
  SkipNext,
  SkipPrevious,
  VolumeUp,
  Subtitles,
  ExpandMore,
  ExpandLess,
  Download,
} from '@mui/icons-material'
import { styled } from '@mui/material/styles'

const HighlightedText = styled('span')<{ active: boolean }>(({ theme, active }) => ({
  padding: '2px 4px',
  borderRadius: 4,
  transition: 'all 0.3s',
  backgroundColor: active ? theme.palette.primary.light + '40' : 'transparent',
  color: active ? theme.palette.primary.main : 'inherit',
  fontWeight: active ? 600 : 400,
}))

interface BrowserPlayerProps {
  projectData: {
    project_id: number
    project_title: string
    chapters: any[]
    total_duration: number
  }
  open: boolean
  onClose: () => void
}

const BrowserPlayer: React.FC<BrowserPlayerProps> = ({ projectData, open, onClose }) => {
  const [currentChapterIndex, setCurrentChapterIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [subtitleFormat, setSubtitleFormat] = useState<'srt' | 'vtt' | 'ass'>('srt')
  const [showSubtitles, setShowSubtitles] = useState(true)
  const [expandedChapters, setExpandedChapters] = useState<Set<number>>(new Set([0]))
  const [highlightedSegmentIndex, setHighlightedSegmentIndex] = useState<number | null>(null)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const textContainerRef = useRef<HTMLDivElement | null>(null)

  const currentChapter = projectData?.chapters?.[currentChapterIndex]

  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
    }

    const audio = audioRef.current

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      updateHighlight(audio.currentTime)
    }

    const handleLoadedMetadata = () => {
      setDuration(audio.duration)
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
  }, [])

  useEffect(() => {
    if (audioRef.current && currentChapter) {
      audioRef.current.src = currentChapter.audio_url
      audioRef.current.load()
      setCurrentTime(0)
      setDuration(0)
      setHighlightedSegmentIndex(null)
    }
  }, [currentChapterIndex, currentChapter])

  const updateHighlight = useCallback(
    (time: number) => {
      if (!currentChapter?.segments) return

      for (let i = 0; i < currentChapter.segments.length; i++) {
        const segment = currentChapter.segments[i]
        if (segment.start_time !== undefined && segment.end_time !== undefined) {
          if (time >= segment.start_time && time < segment.end_time) {
            setHighlightedSegmentIndex(i)
            scrollToSegment(i)
            return
          }
        }
      }
    },
    [currentChapter]
  )

  const scrollToSegment = useCallback((index: number) => {
    if (!textContainerRef.current) return

    const element = textContainerRef.current.querySelector(`[data-segment-index="${index}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [])

  const handlePlayPause = () => {
    if (!audioRef.current) return

    if (isPlaying) {
      audioRef.current.pause()
    } else {
      audioRef.current.play()
    }
    setIsPlaying(!isPlaying)
  }

  const handleNext = () => {
    if (currentChapterIndex < projectData.chapters.length - 1) {
      setCurrentChapterIndex((prev) => prev + 1)
    }
  }

  const handlePrevious = () => {
    if (currentChapterIndex > 0) {
      setCurrentChapterIndex((prev) => prev - 1)
    }
  }

  const handleSeek = (_event: Event, value: number | number[]) => {
    if (audioRef.current) {
      audioRef.current.currentTime = value as number
      setCurrentTime(value as number)
    }
  }

  const handleVolumeChange = (_event: Event, value: number | number[]) => {
    const newVolume = value as number
    setVolume(newVolume)
    if (audioRef.current) {
      audioRef.current.volume = newVolume
    }
  }

  const toggleChapterExpand = (index: number) => {
    setExpandedChapters((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const handleDownloadSubtitle = async () => {
    if (!currentChapter?.subtitle_url) return

    try {
      const response = await fetch(`${currentChapter.subtitle_url}?format=${subtitleFormat}`)
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `chapter_${currentChapter.chapter_id}.${subtitleFormat}`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
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
          {/* 左侧：章节列表 */}
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
                      slotProps={{
                        primary: { variant: 'body2', fontWeight: currentChapterIndex === index ? 600 : 400 },
                        secondary: { variant: 'caption' },
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

          {/* 右侧：播放器和文本 */}
          <Box flex={1} display="flex" flexDirection="column">
            {/* 当前章节信息 */}
            <Box sx={{ mb: 2 }}>
              <Typography variant="h6">
                第{currentChapter?.chapter_number || currentChapterIndex + 1}章：{currentChapter?.chapter_title || ''}
              </Typography>
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

            {/* 文本同步显示区域 */}
            {showSubtitles && currentChapter?.segments && (
              <Paper
                ref={textContainerRef}
                sx={{ p: 2, mb: 2, flex: 1, overflowY: 'auto', minHeight: 200 }}
              >
                <Box>
                  {currentChapter.segments.map((segment: any, index: number) => (
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
                        {segment.text}
                      </HighlightedText>
                    </Box>
                  ))}
                </Box>
              </Paper>
            )}

            {/* 播放控制 */}
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
