/**
 * 浏览器播放器组件
 *
 * 用于播放有声书并同步显示文本高亮。
 * 支持优先回读本地资产，并在刷新后恢复章节、进度和字幕状态。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Box,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import { apiClient } from '@/services/api'
import { getLocalAssetBlob, saveLocalAsset } from '@/utils/localAssetVault'
import { triggerBlobDownload } from '@/utils/blobDownload'
import {
  buildCachedAudacityLabelsAssetDescriptor,
  buildCachedSubtitleAssetDescriptor,
  buildTimedSegments,
  findTimedSegmentIndexByTime,
  resolveCachedBrowserPlayerBlob,
  type BrowserPlayerStateSnapshot,
  type SubtitleFormat,
  writeStoredBrowserPlayerState,
} from './browserPlayerUtils'
import BrowserPlayerChapterHeader from './BrowserPlayerChapterHeader'
import BrowserPlayerChapterList from './BrowserPlayerChapterList'
import BrowserPlayerControls from './BrowserPlayerControls'
import BrowserPlayerHeader from './BrowserPlayerHeader'
import BrowserPlayerSubtitlePanel from './BrowserPlayerSubtitlePanel'
import type { BrowserPlayerProjectData } from './browserPlayerTypes'
import { useBrowserPlayerAudioElement } from './useBrowserPlayerAudioElement'

export type { BrowserPlayerProjectData } from './browserPlayerTypes'

interface BrowserPlayerProps {
  projectData: BrowserPlayerProjectData
  open: boolean
  onClose: () => void
}

const BrowserPlayer: React.FC<BrowserPlayerProps> = ({ projectData, open, onClose }) => {
  const theme = useTheme()
  const fullScreen = useMediaQuery(theme.breakpoints.down('sm'))
  const [currentChapterIndex, setCurrentChapterIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [subtitleFormat, setSubtitleFormat] = useState<SubtitleFormat>('srt')
  const [showSubtitles, setShowSubtitles] = useState(true)
  const [highlightedSegmentIndex, setHighlightedSegmentIndex] = useState<number | null>(null)
  const [usingLocalAsset, setUsingLocalAsset] = useState(false)

  const textContainerRef = useRef<HTMLDivElement | null>(null)
  const lastHighlightRef = useRef<number | null>(null)
  const lastHighlightScrollAtRef = useRef(0)

  const audiobookProjectId = projectData.audiobook_project_id ?? projectData.project_id
  const currentChapter = projectData?.chapters?.[currentChapterIndex]
  const persistedCurrentSecond = Math.floor(currentTime)
  const timedSegments = useMemo(
    () => buildTimedSegments(currentChapter?.segments),
    [currentChapter?.segments],
  )

  const persistSnapshot = useCallback(
    (snapshot: BrowserPlayerStateSnapshot) => {
      if (!audiobookProjectId) return
      writeStoredBrowserPlayerState(localStorage, audiobookProjectId, snapshot)
    },
    [audiobookProjectId],
  )

  const scrollToSegment = useCallback((index: number) => {
    if (!textContainerRef.current) return

    const element = textContainerRef.current.querySelector(`[data-segment-index="${index}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [])

  const findSegmentIndexByTime = useCallback(
    (time: number): number | null => findTimedSegmentIndexByTime(timedSegments, time),
    [timedSegments],
  )

  const updateHighlight = useCallback(
    (time: number) => {
      const nextIndex = findSegmentIndexByTime(time)
      if (lastHighlightRef.current === nextIndex) {
        return
      }

      lastHighlightRef.current = nextIndex
      setHighlightedSegmentIndex(nextIndex)

      if (nextIndex !== null) {
        const now = Date.now()
        if (now - lastHighlightScrollAtRef.current > 250) {
          lastHighlightScrollAtRef.current = now
          scrollToSegment(nextIndex)
        }
      }
    },
    [findSegmentIndexByTime, scrollToSegment],
  )

  const resetHighlightState = useCallback(() => {
    setHighlightedSegmentIndex(null)
    lastHighlightRef.current = null
    lastHighlightScrollAtRef.current = 0
  }, [])

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

  const { handlePlayPause, handleSeek } = useBrowserPlayerAudioElement({
    projectId: audiobookProjectId,
    open,
    currentChapter,
    currentChapterIndex,
    chapterCount: projectData.chapters.length,
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
  })

  useEffect(() => {
    if (!audiobookProjectId || !open) return

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
    audiobookProjectId,
  ])

  const handleVolumeChange = (_event: Event, value: number | number[]) => {
    setVolume(value as number)
  }

  const handleDownloadSubtitle = async () => {
    if (!currentChapter?.subtitle_url) return

    try {
      const cachedSubtitleAsset = buildCachedSubtitleAssetDescriptor({
        projectId: audiobookProjectId,
        chapter: currentChapter,
        chapterIndex: currentChapterIndex,
        subtitleFormat,
      })
      const subtitleBlob = await resolveCachedBrowserPlayerBlob({
        cachedAsset: cachedSubtitleAsset,
        getCachedBlob: getLocalAssetBlob,
        fetchRemoteBlob: () => apiClient.getChapterSubtitle(
          audiobookProjectId,
          currentChapter.chapter_id,
          subtitleFormat,
        ),
        saveCachedAsset: saveLocalAsset,
        onCacheSaveError: (cacheError) => {
          console.warn('缓存字幕失败，将继续直接下载:', cacheError)
        },
      })

      triggerBlobDownload(subtitleBlob, `chapter_${currentChapter.chapter_id}.${subtitleFormat}`)
    } catch (error) {
      console.error('下载字幕失败:', error)
    }
  }

  const handleDownloadAudacityLabels = async () => {
    if (!currentChapter?.audacity_labels_url) return

    try {
      const cachedLabelsAsset = buildCachedAudacityLabelsAssetDescriptor({
        projectId: audiobookProjectId,
        chapter: currentChapter,
        chapterIndex: currentChapterIndex,
      })
      const labelsBlob = await resolveCachedBrowserPlayerBlob({
        cachedAsset: cachedLabelsAsset,
        getCachedBlob: getLocalAssetBlob,
        fetchRemoteBlob: () => apiClient.getChapterSubtitle(
          audiobookProjectId,
          currentChapter.chapter_id,
          'labels',
        ),
        saveCachedAsset: saveLocalAsset,
        onCacheSaveError: (cacheError) => {
          console.warn('缓存 Audacity Labels 失败，将继续直接下载:', cacheError)
        },
      })

      triggerBlobDownload(labelsBlob, `chapter_${currentChapter.chapter_id}.labels.txt`)
    } catch (error) {
      console.error('下载 Audacity Labels 失败:', error)
    }
  }

  if (!open || !projectData) return null

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth fullScreen={fullScreen}>
      <DialogTitle>
        <BrowserPlayerHeader
          projectTitle={projectData.project_title}
          subtitleFormat={subtitleFormat}
          showSubtitles={showSubtitles}
          onSubtitleFormatChange={setSubtitleFormat}
          onToggleSubtitles={() => setShowSubtitles((prev) => !prev)}
        />
      </DialogTitle>

      <DialogContent dividers>
        <Box
          sx={{
            display: 'flex',
            flexDirection: { xs: 'column', md: 'row' },
            gap: { xs: 2, md: 3 },
            height: { xs: 'auto', md: '70vh' },
            minHeight: { xs: 'calc(100vh - 180px)', md: 0 },
            overflow: { xs: 'visible', md: 'hidden' },
          }}
        >
          <BrowserPlayerChapterList
            chapters={projectData.chapters}
            currentChapterIndex={currentChapterIndex}
            onSelectChapter={setCurrentChapterIndex}
          />

          <Box
            sx={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              minWidth: 0,
              minHeight: { xs: 0, md: 'auto' },
            }}
          >
            <BrowserPlayerChapterHeader
              currentChapter={currentChapter}
              currentChapterIndex={currentChapterIndex}
              usingLocalAsset={usingLocalAsset}
              subtitleFormat={subtitleFormat}
              onDownloadSubtitle={handleDownloadSubtitle}
              onDownloadAudacityLabels={handleDownloadAudacityLabels}
            />

            {showSubtitles && currentChapter?.segments && (
              <BrowserPlayerSubtitlePanel
                segments={currentChapter.segments}
                highlightedSegmentIndex={highlightedSegmentIndex}
                textContainerRef={textContainerRef}
              />
            )}

            <BrowserPlayerControls
              currentTime={currentTime}
              duration={duration}
              volume={volume}
              isPlaying={isPlaying}
              currentChapterIndex={currentChapterIndex}
              chapterCount={projectData.chapters.length}
              onSeek={handleSeek}
              onPrevious={handlePrevious}
              onPlayPause={handlePlayPause}
              onNext={handleNext}
              onVolumeChange={handleVolumeChange}
            />
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
