import { useCallback, useEffect, useRef, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { RemixMissingSegment } from '../../services/api'
import type { SetSnackbar } from './hookTypes'

const REMIX_POLL_INTERVAL_MS = 2000
const REMIX_TERMINAL_STATUSES = new Set(['completed', 'failed', 'idle', 'cancelled', 'canceled'])

interface UseAudiobookChapterRemixParams {
  audiobookProjectId?: number | null
  chapterId?: number | null
  setSnackbar: SetSnackbar
  onRemixCompleted?: () => void
}

export const useAudiobookChapterRemix = ({
  audiobookProjectId,
  chapterId,
  setSnackbar,
  onRemixCompleted,
}: UseAudiobookChapterRemixParams) => {
  const [remixMissingDialogOpen, setRemixMissingDialogOpen] = useState(false)
  const [remixMissingSegments, setRemixMissingSegments] = useState<RemixMissingSegment[]>([])
  const [remixing, setRemixing] = useState(false)
  const [remixStatus, setRemixStatus] = useState<string | null>(null)
  const [remixError, setRemixError] = useState<string | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const onRemixCompletedRef = useRef(onRemixCompleted)
  onRemixCompletedRef.current = onRemixCompleted

  const stopRemixPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const pollChapterRemixStatus = useCallback(async () => {
    if (!audiobookProjectId || !chapterId) return
    try {
      const response = await apiClient.getChapterRemixStatus(audiobookProjectId, chapterId)
      const data = response.data
      setRemixStatus(data?.remix_status ?? null)
      if (data?.remix_status === 'completed') {
        stopRemixPolling()
        setRemixing(false)
        setRemixError(null)
        setSnackbar({ open: true, message: '整章重新混音完成', severity: 'success' })
        onRemixCompletedRef.current?.()
      } else if (data?.remix_status === 'failed') {
        stopRemixPolling()
        setRemixing(false)
        setRemixError(data?.error_message || '整章重新混音失败')
        setSnackbar({ open: true, message: `整章重新混音失败：${data?.error_message || '未知错误'}`, severity: 'error' })
      } else if (REMIX_TERMINAL_STATUSES.has(data?.remix_status ?? '')) {
        stopRemixPolling()
        setRemixing(false)
      }
    } catch (error: unknown) {
      stopRemixPolling()
      setRemixing(false)
      const message = await extractApiErrorMessage(error, '查询整章混音状态失败')
      setRemixError(message)
    }
  }, [audiobookProjectId, chapterId, setSnackbar, stopRemixPolling])

  const startRemixPolling = useCallback(() => {
    stopRemixPolling()
    setRemixStatus('running')
    setRemixError(null)
    void pollChapterRemixStatus()
    pollTimerRef.current = window.setInterval(() => {
      void pollChapterRemixStatus()
    }, REMIX_POLL_INTERVAL_MS)
  }, [pollChapterRemixStatus, stopRemixPolling])

  useEffect(() => () => {
    stopRemixPolling()
  }, [stopRemixPolling])

  const handleRemixChapter = useCallback(async () => {
    if (!audiobookProjectId || !chapterId) return
    setRemixing(true)
    setRemixError(null)
    try {
      const response = await apiClient.remixChapter(audiobookProjectId, chapterId, { force: false })
      const data = response.data
      if (data?.requires_confirmation && data?.missing_segments?.length) {
        setRemixMissingSegments(data.missing_segments)
        setRemixMissingDialogOpen(true)
        setRemixing(false)
        return
      }
      if (data?.success) {
        startRemixPolling()
      } else {
        setRemixing(false)
        setSnackbar({ open: true, message: '整章重新混音未触发', severity: 'warning' })
      }
    } catch (error: unknown) {
      setRemixing(false)
      const message = await extractApiErrorMessage(error, '触发整章重新混音失败')
      setRemixError(message)
      setSnackbar({ open: true, message, severity: 'error' })
    }
  }, [audiobookProjectId, chapterId, setSnackbar, startRemixPolling])

  const handleForceRemixChapter = useCallback(async () => {
    if (!audiobookProjectId || !chapterId) return
    setRemixMissingDialogOpen(false)
    setRemixing(true)
    setRemixError(null)
    try {
      const response = await apiClient.remixChapter(audiobookProjectId, chapterId, { force: true })
      if (response.data?.success) {
        startRemixPolling()
      } else {
        setRemixing(false)
        setSnackbar({ open: true, message: '整章重新混音未触发', severity: 'warning' })
      }
    } catch (error: unknown) {
      setRemixing(false)
      const message = await extractApiErrorMessage(error, '触发整章重新混音失败')
      setRemixError(message)
      setSnackbar({ open: true, message, severity: 'error' })
    }
  }, [audiobookProjectId, chapterId, setSnackbar, startRemixPolling])

  const handleCloseRemixMissingDialog = useCallback(() => {
    setRemixMissingDialogOpen(false)
  }, [])

  return {
    remixMissingDialogOpen,
    remixMissingSegments,
    remixing,
    remixStatus,
    remixError,
    handleRemixChapter,
    handleForceRemixChapter,
    handleCloseRemixMissingDialog,
  }
}
