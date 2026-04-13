import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient } from '@/services/api'
import type { AudiobookProjectSummary, Chapter, MergedChapterAudioRef, Project } from '@/types/audiobook'

type NotifyPayload = {
  message: string
  severity: 'success' | 'error' | 'info' | 'warning'
}

export default function useAudiobookChapterDrawer({ onNotify }: { onNotify?: (payload: NotifyPayload) => void } = {}) {
  const notify = useCallback(
    (payload: NotifyPayload) => {
      onNotify?.(payload)
    },
    [onNotify],
  )

  const requestIdRef = useRef(0)

  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [project, setProject] = useState<Project | null>(null)
  const [audiobookProject, setAudiobookProject] = useState<AudiobookProjectSummary | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [mergedChapterAudiosByNumber, setMergedChapterAudiosByNumber] = useState<Record<number, MergedChapterAudioRef>>({})
  const [chapterSortOrder, setChapterSortOrder] = useState<'asc' | 'desc'>('asc')

  const audio = useMemo(() => new Audio(), [])
  const audioBlobUrlRef = useRef<string | null>(null)
  const isSeekingRef = useRef(false)

  const [playingChapterNumber, setPlayingChapterNumber] = useState<number | null>(null)
  const [playerIsPlaying, setPlayerIsPlaying] = useState(false)
  const [playerCurrentTime, setPlayerCurrentTime] = useState(0)
  const [playerDuration, setPlayerDuration] = useState(0)

  const stopPlayback = useCallback(() => {
    try {
      audio.pause()
    } finally {
      setPlayerIsPlaying(false)
      setPlayingChapterNumber(null)
      setPlayerCurrentTime(0)
      setPlayerDuration(0)
      if (audioBlobUrlRef.current) {
        window.URL.revokeObjectURL(audioBlobUrlRef.current)
        audioBlobUrlRef.current = null
      }
    }
  }, [audio])

  useEffect(() => {
    const handleLoadedMetadata = () => {
      setPlayerDuration(Number.isFinite(audio.duration) ? audio.duration : 0)
    }
    const handleTimeUpdate = () => {
      if (isSeekingRef.current) return
      setPlayerCurrentTime(Number.isFinite(audio.currentTime) ? audio.currentTime : 0)
    }
    const handlePlay = () => setPlayerIsPlaying(true)
    const handlePause = () => setPlayerIsPlaying(false)
    const handleEnded = () => {
      setPlayerIsPlaying(false)
      setPlayingChapterNumber(null)
      setPlayerCurrentTime(0)
      if (audioBlobUrlRef.current) {
        window.URL.revokeObjectURL(audioBlobUrlRef.current)
        audioBlobUrlRef.current = null
      }
    }

    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('ended', handleEnded)

    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('ended', handleEnded)
    }
  }, [audio])

  const seekPreview = useCallback((nextTime: number) => {
    isSeekingRef.current = true
    setPlayerCurrentTime(nextTime)
  }, [])

  const seekCommit = useCallback(
    (nextTime: number) => {
      audio.currentTime = nextTime
      isSeekingRef.current = false
    },
    [audio],
  )

  const openDrawer = useCallback(
    async (nextProject: Project) => {
      const requestId = (requestIdRef.current += 1)
      stopPlayback()
      setOpen(true)
      setProject(nextProject)
      setLoading(true)
      setError(null)
      setAudiobookProject(null)
      setChapters([])
      setMergedChapterAudiosByNumber({})

      try {
        const [audiobookProjectsRes, chaptersRes] = await Promise.all([
          apiClient.getAudiobookProjectsByProject(nextProject.id, { include_chapter_audios: true }),
          apiClient.getChapters(nextProject.id, 'asc'),
        ])
        if (requestId !== requestIdRef.current) return

        const chaptersData: Chapter[] = Array.isArray(chaptersRes.data) ? (chaptersRes.data as Chapter[]) : []
        setChapters(chaptersData)

        const chapterNumberById = new Map<number, number>()
        for (const ch of chaptersData) chapterNumberById.set(ch.id, ch.chapter_number)

        const audiobookProjects: AudiobookProjectSummary[] = Array.isArray(audiobookProjectsRes.data)
          ? (audiobookProjectsRes.data as AudiobookProjectSummary[])
          : []
        const completed = audiobookProjects.filter((p) => p?.status === 'completed')
        const completedSorted = [...completed].sort((a, b) => {
          const ta = a?.created_at ? Date.parse(a.created_at) : 0
          const tb = b?.created_at ? Date.parse(b.created_at) : 0
          if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) return tb - ta
          const ia = typeof a?.id === 'number' ? a.id : 0
          const ib = typeof b?.id === 'number' ? b.id : 0
          return ib - ia
        })

        const latestCompleted = completedSorted[0]
        if (!latestCompleted) {
          setError('该项目暂无有声书，请先生成。')
          return
        }

        setAudiobookProject(latestCompleted)
        const merged: Record<number, MergedChapterAudioRef> = {}
        for (const detail of completedSorted) {
          const sourceProjectId = detail.id
          const audios = Array.isArray(detail.chapter_audios) ? detail.chapter_audios : []
          for (const ca of audios) {
            if (!ca?.audio_path) continue
            const chapterNumber = (ca.chapter_number ?? chapterNumberById.get(ca.chapter_id)) as number | undefined
            if (!chapterNumber) continue
            if (merged[chapterNumber]) continue
            merged[chapterNumber] = { audiobookProjectId: sourceProjectId, chapterAudio: ca }
          }
        }
        setMergedChapterAudiosByNumber(merged)
      } catch {
        setError('加载章节目录失败，请稍后重试。')
      } finally {
        if (requestId !== requestIdRef.current) return
        setLoading(false)
      }
    },
    [stopPlayback],
  )

  const closeDrawer = useCallback(() => {
    setOpen(false)
    requestIdRef.current += 1
    setError(null)
    setProject(null)
    setAudiobookProject(null)
    setChapters([])
    setMergedChapterAudiosByNumber({})
    stopPlayback()
  }, [stopPlayback])

  const toggleSortOrder = useCallback(() => {
    setChapterSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }, [])

  const playChapter = useCallback(
    async (chapterNumber: number) => {
      const mergedRef = mergedChapterAudiosByNumber[chapterNumber]
      if (!mergedRef?.chapterAudio?.audio_path) {
        notify({ message: '该章节尚未生成音频', severity: 'info' })
        return
      }

      try {
        if (playingChapterNumber === chapterNumber) {
          if (audio.paused) await audio.play()
          else audio.pause()
          return
        }

        audio.pause()
        setPlayerCurrentTime(0)
        setPlayerDuration(0)

        if (audioBlobUrlRef.current) {
          window.URL.revokeObjectURL(audioBlobUrlRef.current)
          audioBlobUrlRef.current = null
        }

        const token = localStorage.getItem('access_token')
        const response = await fetch(
          `/api/v1/audiobook/stream/${mergedRef.audiobookProjectId}/${mergedRef.chapterAudio.chapter_id}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          },
        )
        if (!response.ok) throw new Error('加载音频失败')

        const blob = await response.blob()
        const blobUrl = window.URL.createObjectURL(blob)
        audioBlobUrlRef.current = blobUrl
        audio.src = blobUrl

        await audio.play()
        setPlayingChapterNumber(chapterNumber)
      } catch {
        notify({ message: '播放失败，请稍后重试', severity: 'error' })
        setPlayingChapterNumber(null)
      }
    },
    [audio, mergedChapterAudiosByNumber, notify, playingChapterNumber],
  )

  const refresh = useCallback(async () => {
    if (!project) return
    await openDrawer(project)
  }, [openDrawer, project])

  return {
    open,
    loading,
    error,
    project,
    audiobookProject,
    chapters,
    mergedChapterAudiosByNumber,
    chapterSortOrder,
    playingChapterNumber,
    playerIsPlaying,
    playerCurrentTime,
    playerDuration,
    seekPreview,
    seekCommit,
    openDrawer,
    closeDrawer,
    toggleSortOrder,
    playChapter,
    stopPlayback,
    refresh,
  }
}

