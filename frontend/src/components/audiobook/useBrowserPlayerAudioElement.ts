import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type SetStateAction,
} from 'react'

import { apiClient } from '@/services/api'
import { getLocalAssetBlob, saveLocalAsset } from '@/utils/localAssetVault'
import {
  buildCachedChapterAudioAssetDescriptor,
  readStoredBrowserPlayerState,
  resolveBrowserPlayerAudioSource,
  type BrowserPlayerStateSnapshot,
  type SubtitleFormat,
} from './browserPlayerUtils'
import type { BrowserPlayerChapter } from './browserPlayerTypes'

interface UseBrowserPlayerAudioElementParams {
  projectId: number
  open: boolean
  currentChapter?: BrowserPlayerChapter
  currentChapterIndex: number
  chapterCount: number
  volume: number
  setCurrentChapterIndex: Dispatch<SetStateAction<number>>
  setCurrentTime: Dispatch<SetStateAction<number>>
  setDuration: Dispatch<SetStateAction<number>>
  setVolume: Dispatch<SetStateAction<number>>
  setSubtitleFormat: Dispatch<SetStateAction<SubtitleFormat>>
  setShowSubtitles: Dispatch<SetStateAction<boolean>>
  setIsPlaying: Dispatch<SetStateAction<boolean>>
  setUsingLocalAsset: Dispatch<SetStateAction<boolean>>
  resetHighlightState: () => void
  updateHighlight: (time: number) => void
}

export const useBrowserPlayerAudioElement = ({
  projectId,
  open,
  currentChapter,
  currentChapterIndex,
  chapterCount,
  volume,
  setCurrentChapterIndex,
  setCurrentTime,
  setDuration,
  setVolume,
  setSubtitleFormat,
  setShowSubtitles,
  setIsPlaying,
  setUsingLocalAsset,
  resetHighlightState,
  updateHighlight,
}: UseBrowserPlayerAudioElementParams) => {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)
  const restoreStateRef = useRef<BrowserPlayerStateSnapshot | null>(null)
  const shouldAutoplayNextChapterRef = useRef(false)

  const revokeCurrentObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      window.URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

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
      const shouldAutoplayNextChapter = shouldAutoplayNextChapterRef.current
      const playLoadedAudio = () => {
        void audio.play().then(() => {
          setIsPlaying(true)
        }).catch(() => {
          setIsPlaying(false)
        })
      }

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

        const shouldResumePlayback = restoreState.wasPlaying || shouldAutoplayNextChapter
        restoreStateRef.current = null
        shouldAutoplayNextChapterRef.current = false

        if (shouldResumePlayback && open) {
          playLoadedAudio()
        }
      } else if (shouldAutoplayNextChapter && open) {
        shouldAutoplayNextChapterRef.current = false
        playLoadedAudio()
      }
    }

    const handleEnded = () => {
      setIsPlaying(false)
      if (currentChapterIndex < chapterCount - 1) {
        shouldAutoplayNextChapterRef.current = true
        setCurrentChapterIndex((prev) => prev + 1)
      }
    }

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('loadedmetadata', handleLoadedMetadata)
    audio.addEventListener('ended', handleEnded)

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata)
      audio.removeEventListener('ended', handleEnded)
    }
  }, [
    chapterCount,
    currentChapterIndex,
    open,
    setCurrentChapterIndex,
    setCurrentTime,
    setDuration,
    setIsPlaying,
    updateHighlight,
    volume,
  ])

  useEffect(() => {
    if (!open || !projectId) {
      return
    }

    const nextState = readStoredBrowserPlayerState(
      localStorage,
      projectId,
      chapterCount,
    )

    restoreStateRef.current = nextState
    setCurrentChapterIndex(nextState.currentChapterIndex)
    setCurrentTime(nextState.currentTime)
    setVolume(nextState.volume)
    setSubtitleFormat(nextState.subtitleFormat)
    setShowSubtitles(nextState.showSubtitles)
    setIsPlaying(false)
  }, [
    chapterCount,
    open,
    projectId,
    setCurrentChapterIndex,
    setCurrentTime,
    setIsPlaying,
    setShowSubtitles,
    setSubtitleFormat,
    setVolume,
  ])

  useEffect(() => {
    if (!audioRef.current || !currentChapter) {
      return
    }

    let cancelled = false
    const audio = audioRef.current

    const loadAudioSource = async () => {
      audio.pause()
      setIsPlaying(false)
      resetHighlightState()
      revokeCurrentObjectUrl()

      try {
        const cachedAudioAsset = buildCachedChapterAudioAssetDescriptor({
          projectId,
          chapter: currentChapter,
          chapterIndex: currentChapterIndex,
        })

        const cachedBlob = await getLocalAssetBlob(cachedAudioAsset.assetUuid).catch(() => null)
        if (cancelled) {
          return
        }

        if (cachedBlob) {
          const sourceUrl = window.URL.createObjectURL(cachedBlob)
          objectUrlRef.current = sourceUrl
          audio.src = sourceUrl
          setUsingLocalAsset(true)
          audio.load()
        } else {
          try {
            const signedStreamUrl = await apiClient.getAudiobookChapterAudioSignedStreamUrl(
              projectId,
              currentChapter.chapter_id,
            )
            if (cancelled) {
              return
            }
            audio.src = signedStreamUrl
            setUsingLocalAsset(false)
            audio.load()
          } catch (streamUrlError) {
            console.warn('获取签名播放地址失败，将回退到 Blob 音频加载:', streamUrlError)
            const audioSource = await resolveBrowserPlayerAudioSource({
              cachedAsset: cachedAudioAsset,
              getCachedBlob: async () => null,
              fetchRemoteBlob: () => apiClient.getAudiobookChapterAudioStreamFile(
                projectId,
                currentChapter.chapter_id,
              ),
              saveCachedAsset: saveLocalAsset,
              shouldCancel: () => cancelled,
              onCacheSaveError: (cacheError) => {
                console.warn('缓存播放器音频失败，将继续使用远端音频:', cacheError)
              },
            })
            if (!audioSource) {
              return
            }

            const sourceUrl = window.URL.createObjectURL(audioSource.blob)
            objectUrlRef.current = sourceUrl
            audio.src = sourceUrl
            setUsingLocalAsset(audioSource.usingLocalAsset)
            audio.load()
          }
        }
      } catch (error) {
        console.error('加载播放器音频失败:', error)
        audio.removeAttribute('src')
        audio.load()
        shouldAutoplayNextChapterRef.current = false
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
  }, [
    currentChapter,
    currentChapterIndex,
    projectId,
    resetHighlightState,
    revokeCurrentObjectUrl,
    setCurrentTime,
    setDuration,
    setIsPlaying,
    setUsingLocalAsset,
  ])

  useEffect(() => {
    if (!audioRef.current) return
    audioRef.current.volume = volume
  }, [volume])

  useEffect(() => {
    if (open || !audioRef.current) return
    audioRef.current.pause()
    setIsPlaying(false)
  }, [open, setIsPlaying])

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
      }
      revokeCurrentObjectUrl()
    }
  }, [revokeCurrentObjectUrl])

  const handlePlayPause = useCallback(async () => {
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
  }, [setIsPlaying])

  const handleSeek = useCallback((
    _event: Event,
    value: number | number[],
  ) => {
    if (!audioRef.current) return

    const nextTime = value as number
    audioRef.current.currentTime = nextTime
    setCurrentTime(nextTime)
    updateHighlight(nextTime)
  }, [setCurrentTime, updateHighlight])

  return {
    handlePlayPause,
    handleSeek,
  }
}
