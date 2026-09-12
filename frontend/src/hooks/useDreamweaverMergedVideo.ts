import { useCallback, useEffect, useState } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'
import {
  buildDreamWeaverMergedVideoAssetMetadataContract,
} from '@/contracts/userAssetMetadataBuilders'
import {
  buildDreamWeaverMergedVideoSourcePayload,
} from '@/contracts/userAssetSourcePayloadBuilders'
import {
  buildProtectedMergedVideoUrl,
  extractMergedVideoFromContract,
} from '@/utils/dreamweaver'
import type { CollectFeedback, DreamweaverRunSnapshot } from '@/types/dreamweaver'

export interface UseDreamweaverMergedVideoParams {
  getCurrentRunId: () => string | null
  getMergedVideoPath: () => string | null
  getRunSnapshot: () => DreamweaverRunSnapshot | null
  getProjectId: () => number | null
  getProjectTitle: () => string | null
}

export interface UseDreamweaverMergedVideoReturn {
  mergedVideoLoading: boolean
  mergedVideoError: string | null
  mergedVideoPreviewUrl: string | null
  mergedVideoCollecting: boolean
  mergedVideoCollectFeedback: CollectFeedback | null
  loadMergedVideoPreview: () => Promise<void>
  downloadMergedVideo: () => Promise<void>
  collectMergedVideo: () => Promise<void>
  resetMergedVideoState: () => void
}

export function useDreamweaverMergedVideo(
  params: UseDreamweaverMergedVideoParams,
): UseDreamweaverMergedVideoReturn {
  const { getCurrentRunId, getMergedVideoPath, getRunSnapshot, getProjectId, getProjectTitle } = params
  const { t } = useTranslation()

  const [mergedVideoLoading, setMergedVideoLoading] = useState(false)
  const [mergedVideoError, setMergedVideoError] = useState<string | null>(null)
  const [mergedVideoPreviewUrl, setMergedVideoPreviewUrl] = useState<string | null>(null)
  const [mergedVideoCollecting, setMergedVideoCollecting] = useState(false)
  const [mergedVideoCollectFeedback, setMergedVideoCollectFeedback] = useState<CollectFeedback | null>(null)

  useEffect(() => {
    return () => {
      if (!mergedVideoPreviewUrl) return
      try {
        URL.revokeObjectURL(mergedVideoPreviewUrl)
      } catch {
        // ignore
      }
    }
  }, [mergedVideoPreviewUrl])

  const loadMergedVideoPreview = useCallback(async () => {
    const runId = getCurrentRunId()
    if (!runId) {
      setMergedVideoError(t('dreamweaverRun.errorMissingRunIdLoadMergedVideo'))
      return
    }
    setMergedVideoLoading(true)
    setMergedVideoError(null)
    try {
      const res = await apiClient.getDreamweaverMergedVideoFile(runId)
      const url = URL.createObjectURL(res.data)
      setMergedVideoPreviewUrl(url)
    } catch (e: unknown) {
      setMergedVideoError(await extractApiErrorMessage(e, t('dreamweaverRun.loadMergedVideoFailed')))
    } finally {
      setMergedVideoLoading(false)
    }
  }, [getCurrentRunId, t])

  const downloadMergedVideo = useCallback(async () => {
    const runId = getCurrentRunId()
    if (!runId) {
      setMergedVideoError(t('dreamweaverRun.errorMissingRunIdDownloadMergedVideo'))
      return
    }
    setMergedVideoLoading(true)
    setMergedVideoError(null)
    try {
      const res = await apiClient.getDreamweaverMergedVideoFile(runId)
      const url = URL.createObjectURL(res.data)
      const mergedPath = getMergedVideoPath()
      const filename =
        (mergedPath ? String(mergedPath).split(/[\\/]+/).pop() : '') ||
        `merged_${runId}.mp4`
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      }, 0)
    } catch (e: unknown) {
      setMergedVideoError(await extractApiErrorMessage(e, t('dreamweaverRun.downloadMergedVideoFailed')))
    } finally {
      setMergedVideoLoading(false)
    }
  }, [getCurrentRunId, getMergedVideoPath, t])

  const collectMergedVideo = useCallback(async () => {
    const runId = getCurrentRunId()
    if (!runId) {
      setMergedVideoCollectFeedback({ type: 'error', text: t('dreamweaverRun.errorMissingRunIdArchiveMergedVideo') })
      return
    }

    const mergedPath =
      getMergedVideoPath() ||
      (() => {
        const snap = getRunSnapshot()
        return snap?.contract && typeof snap.contract === 'object'
          ? extractMergedVideoFromContract(snap.contract as Record<string, unknown>)
          : null
      })()

    setMergedVideoCollecting(true)
    setMergedVideoCollectFeedback(null)

    try {
      await apiClient.createUserAsset({
        project_id: getProjectId(),
        source_module: 'dreamweaver_run',
        asset_kind: 'video',
        asset_class: 'deliverable',
        asset_uuid: runId,
        storage_mode: 'durable_cloud',
        title: `${getProjectTitle() || '短剧项目'} 合成视频`,
        description: 'DreamWeaver 最终合成成片归档',
        source_uri: buildProtectedMergedVideoUrl(runId),
        preview_uri: buildProtectedMergedVideoUrl(runId),
        download_uri: buildProtectedMergedVideoUrl(runId),
        mime_type: 'video/mp4',
        generation_mode: 'merged_video',
        tags: ['dreamweaver', 'deliverable', 'merged-video'],
        metadata_json: buildDreamWeaverMergedVideoAssetMetadataContract({
          runId,
          projectId: getProjectId(),
          projectTitle: getProjectTitle() || null,
          mergedVideoPath: mergedPath,
        }),
        source_payload_json: buildDreamWeaverMergedVideoSourcePayload({
          runId,
          projectId: getProjectId(),
          path: mergedPath,
        }),
      })
      setMergedVideoCollectFeedback({ type: 'success', text: t('dreamweaverRun.mergedVideoArchived') })
    } catch (collectError) {
      setMergedVideoCollectFeedback({
        type: 'error',
        text: await extractApiErrorMessage(collectError, t('dreamweaverRun.archiveMergedVideoFailed')),
      })
    } finally {
      setMergedVideoCollecting(false)
    }
  }, [getCurrentRunId, getMergedVideoPath, getRunSnapshot, getProjectId, getProjectTitle, t])

  const resetMergedVideoState = useCallback(() => {
    setMergedVideoLoading(false)
    setMergedVideoError(null)
    setMergedVideoPreviewUrl(null)
  }, [])

  return {
    mergedVideoLoading,
    mergedVideoError,
    mergedVideoPreviewUrl,
    mergedVideoCollecting,
    mergedVideoCollectFeedback,
    loadMergedVideoPreview,
    downloadMergedVideo,
    collectMergedVideo,
    resetMergedVideoState,
  }
}
