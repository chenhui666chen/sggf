import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from 'react'

import { buildAudiobookChapterAudioAssetMetadataContract } from '../../contracts/userAssetMetadataBuilders'
import { buildAudiobookChapterAudioSourcePayload } from '../../contracts/userAssetSourcePayloadBuilders'
import { apiClient, extractApiErrorMessage } from '../../services/api'
import { triggerBlobDownload } from '../../utils/blobDownload'
import { extractLocalAssetStorageMetadata, getLocalAssetBlob } from '../../utils/localAssetVault'
import { saveExplicitLocalUserAsset } from '../../utils/userAssetExplicitLocalCollection'
import { buildAudiobookChapterAudioAssetDescriptor } from './chapterAudioAssetUtils'
import {
  addCollectingChapterId,
  removeCollectingChapterId,
} from './chapterAudioCollectingState'
import type { PlayAudioOptions, SetSnackbar } from './hookTypes'
import type {
  AudioOutputFormat,
  AudiobookProjectDetail,
  Chapter,
  ChapterAudio,
  Project,
} from './types'
import {
  buildAudiobookChapterAssetUuid,
  buildAudiobookChapterDownloadUrl,
  extractDownloadFilename,
} from './utils'

interface UseAudiobookChapterAudioActionsParams {
  audiobookProject: AudiobookProjectDetail | null
  selectedProject: Project | null
  routeProjectId: number | null
  chapters: Chapter[]
  outputFormat: AudioOutputFormat
  playingChapter: number | null
  setPlayingChapter: Dispatch<SetStateAction<number | null>>
  playManagedBlob: (blob: Blob, options?: PlayAudioOptions) => Promise<unknown>
  stopManagedPlayback: () => void
  setSnackbar: SetSnackbar
}

export const useAudiobookChapterAudioActions = ({
  audiobookProject,
  selectedProject,
  routeProjectId,
  chapters,
  outputFormat,
  playingChapter,
  setPlayingChapter,
  playManagedBlob,
  stopManagedPlayback,
  setSnackbar,
}: UseAudiobookChapterAudioActionsParams) => {
  const [collectingChapterIds, setCollectingChapterIds] = useState<Set<number>>(() => new Set())
  const collectingChapterIdsRef = useRef<Set<number>>(new Set())

  const updateCollectingChapterIds = useCallback((nextIds: Set<number>) => {
    collectingChapterIdsRef.current = nextIds
    setCollectingChapterIds(nextIds)
  }, [])

  const fetchChapterAudioFile = useCallback(
    async (chapterId: number) => {
      if (!audiobookProject) {
        throw new Error('缺少有声书项目')
      }

      const response = await apiClient.getAudiobookChapterAudioFile(audiobookProject.id, chapterId)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `chapter_${chapterId}.${outputFormat}`,
      )

      return {
        blob: response.data,
        filename,
        downloadUrl: buildAudiobookChapterDownloadUrl(audiobookProject.id, chapterId),
      }
    },
    [audiobookProject, outputFormat],
  )

  const handleDownloadAudio = useCallback(async (chapterId: number) => {
    if (!audiobookProject) return

    try {
      const { blob, filename } = await fetchChapterAudioFile(chapterId)
      triggerBlobDownload(blob, filename)
      setSnackbar({ open: true, message: '音频下载成功', severity: 'success' })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '下载失败，请重试'),
        severity: 'error',
      })
    }
  }, [audiobookProject, fetchChapterAudioFile, setSnackbar])

  const handleCollectChapterAudio = useCallback(async (chapterAudio: ChapterAudio) => {
    if (!audiobookProject) return

    const chapterId = chapterAudio.chapter_id
    if (collectingChapterIdsRef.current.has(chapterId)) return

    updateCollectingChapterIds(addCollectingChapterId(collectingChapterIdsRef.current, chapterId))

    try {
      const { blob, filename, downloadUrl } = await fetchChapterAudioFile(chapterId)
      const assetDescriptor = buildAudiobookChapterAudioAssetDescriptor({
        audiobookProject,
        chapterAudio,
        chapters,
        selectedProject,
        routeProjectId,
        filename,
      })
      const mimeType = blob.type || 'audio/mpeg'

      const {
        localAssetRecord,
        didFallbackToBrowserStorage,
      } = await saveExplicitLocalUserAsset({
        assetUuid: assetDescriptor.assetUuid,
        mediaKind: 'audio',
        blob,
        mimeType,
        fileSize: blob.size,
        sourceModule: 'audiobook',
        title: assetDescriptor.title,
        sourceUri: downloadUrl,
        previewUri: downloadUrl,
        downloadUri: downloadUrl,
        metadata: assetDescriptor.metadata,
      })

      await apiClient.createUserAsset({
        project_id: assetDescriptor.projectId,
        source_module: 'audiobook',
        asset_kind: 'audio',
        asset_class: 'deliverable',
        asset_uuid: assetDescriptor.assetUuid,
        storage_mode: 'local_mirror',
        title: assetDescriptor.title,
        description: 'Audiobook 章节成品音频',
        source_uri: downloadUrl,
        preview_uri: downloadUrl,
        download_uri: downloadUrl,
        mime_type: mimeType,
        file_size: blob.size,
        generation_mode: 'chapter_audio',
        tags: ['audiobook', 'deliverable', 'chapter-audio'],
        metadata_json: buildAudiobookChapterAudioAssetMetadataContract(
          assetDescriptor.metadata,
          extractLocalAssetStorageMetadata(localAssetRecord),
        ),
        source_payload_json: buildAudiobookChapterAudioSourcePayload(assetDescriptor.metadata),
      })

      setSnackbar({
        open: true,
        message: didFallbackToBrowserStorage
          ? '章节音频已收录到用户资产，但用户目录当前不可用，文件已回退保存到浏览器本地存储'
          : '章节音频已收录到用户资产',
        severity: 'success',
      })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '收录章节音频失败，请稍后重试'),
        severity: 'error',
      })
    } finally {
      updateCollectingChapterIds(removeCollectingChapterId(collectingChapterIdsRef.current, chapterId))
    }
  }, [
    audiobookProject,
    chapters,
    fetchChapterAudioFile,
    routeProjectId,
    selectedProject,
    setSnackbar,
    updateCollectingChapterIds,
  ])

  const handlePlayAudio = useCallback(async (
    chapterId: number,
    options?: { restart?: boolean },
  ) => {
    if (!audiobookProject) return

    try {
      // restart：同章节音频已更新（如重新混音完成），跳过 toggle 停止，直接重新播放
      if (playingChapter === chapterId && !options?.restart) {
        stopManagedPlayback()
        setPlayingChapter(null)
        return
      }

      stopManagedPlayback()

      const assetUuid = buildAudiobookChapterAssetUuid(audiobookProject.id, chapterId)
      const localBlob = await getLocalAssetBlob(assetUuid).catch(() => null)
      const blob = localBlob || (await fetchChapterAudioFile(chapterId)).blob
      await playManagedBlob(blob, {
        onEnded: () => {
          setPlayingChapter(null)
        },
      })
      setPlayingChapter(chapterId)

      setSnackbar({ open: true, message: '开始播放', severity: 'success' })
    } catch {
      stopManagedPlayback()
      setPlayingChapter(null)
      setSnackbar({ open: true, message: '播放失败，请重试', severity: 'error' })
    }
  }, [
    audiobookProject,
    fetchChapterAudioFile,
    playManagedBlob,
    playingChapter,
    setPlayingChapter,
    setSnackbar,
    stopManagedPlayback,
  ])

  return {
    collectingChapterIds,
    fetchChapterAudioFile,
    handleDownloadAudio,
    handleCollectChapterAudio,
    handlePlayAudio,
  }
}
