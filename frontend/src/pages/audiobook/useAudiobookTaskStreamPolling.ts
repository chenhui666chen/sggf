import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { AudiobookProjectDetail, TaskStatus } from './types'
import {
  applyTaskProgressStreamPatch,
  canStartTaskProgressStream,
  consumeSseEventBuffer,
  hasReadableTaskProgressStreamResponse,
  shouldFallbackPollAfterStreamClose,
  type TaskProgressStreamConnectionStatus,
  type TaskProgressStreamEvent,
} from './taskStreamPollingUtils'
import {
  getCompletedTaskSnackbarMessage,
  getFailedTaskSnackbarMessage,
  getTaskPollDelayMs,
  isSuccessfulTaskPollStatus,
  resolvePolledTaskAudiobookProjectId,
  selectNextActiveTask,
  selectNextActiveTaskAfterUpdate,
  shouldAutoDownloadCompletedTask,
} from './taskUtils'
import { normalizeTaskStatusResponse } from './utils'

type FocusAudiobookTaskOptions = {
  forceGenerating?: boolean
  activateProgressView?: boolean
}

interface UseAudiobookTaskStreamPollingParams {
  currentTaskId: string | null
  currentAudiobookProjectId: number | null
  taskStatusesRef: MutableRefObject<Record<string, TaskStatus>>
  setTaskStatusesAndRef: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setProgressViewDismissed: Dispatch<SetStateAction<boolean>>
  setSnackbar: SetSnackbar
  focusAudiobookTask: (task: TaskStatus, options?: FocusAudiobookTaskOptions) => Promise<void>
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<AudiobookProjectDetail>
  downloadCompletedProjectExport: (task: TaskStatus) => Promise<unknown>
}

type PollTimeoutId = ReturnType<typeof setTimeout>

const SSE_FALLBACK_POLL_INTERVAL_MS = 30000
const SSE_FALLBACK_HIDDEN_POLL_INTERVAL_MS = 60000

const isDocumentHidden = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'hidden'

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === 'object' && !Array.isArray(value))

const isAbortError = (error: unknown): boolean =>
  isRecord(error) && error.name === 'AbortError'

export const useAudiobookTaskStreamPolling = ({
  currentTaskId,
  currentAudiobookProjectId,
  taskStatusesRef,
  setTaskStatusesAndRef,
  setCurrentTaskId,
  setCurrentAudiobookProjectId,
  setGenerating,
  setActiveStep,
  setProgressViewDismissed,
  setSnackbar,
  focusAudiobookTask,
  refreshAudiobookProjectDetail,
  downloadCompletedProjectExport,
}: UseAudiobookTaskStreamPollingParams) => {
  const { t } = useTranslation()
  const streamStatusRef = useRef<TaskProgressStreamConnectionStatus>('idle')
  const setStreamStatus = useCallback((
    status: TaskProgressStreamConnectionStatus,
    detail?: { taskId?: string | null; reason?: string },
  ) => {
    if (streamStatusRef.current === status) {
      return
    }
    streamStatusRef.current = status

    if (typeof console !== 'undefined' && typeof console.debug === 'function') {
      console.debug('[audiobook-task-stream]', {
        status,
        taskId: detail?.taskId ?? null,
        reason: detail?.reason,
      })
    }
  }, [])

  useEffect(() => {
    if (!currentTaskId) {
      return
    }

    let cancelled = false
    let failureCount = 0
    let timeoutId: PollTimeoutId | null = null
    let streamAbortController: AbortController | null = null
    let streamConnected = false
    let streamRefreshInFlight = false
    let pendingStreamRefresh = false
    let terminalHandled = false

    const clearScheduledPoll = () => {
      if (timeoutId) {
        clearTimeout(timeoutId)
        timeoutId = null
      }
    }

    const getCurrentPollDelayMs = () => {
      if (streamConnected) {
        return isDocumentHidden()
          ? SSE_FALLBACK_HIDDEN_POLL_INTERVAL_MS
          : SSE_FALLBACK_POLL_INTERVAL_MS
      }

      return getTaskPollDelayMs({
        failureCount,
        documentHidden: isDocumentHidden(),
      })
    }

    const scheduleNextPoll = (delayMs?: number) => {
      if (cancelled) {
        return
      }

      clearScheduledPoll()
      timeoutId = setTimeout(() => {
        void pollTaskStatus()
      }, delayMs ?? getCurrentPollDelayMs())
    }

    const focusNextActiveTask = async (task: TaskStatus) => {
      try {
        await focusAudiobookTask(task, {
          forceGenerating: true,
          activateProgressView: true,
        })
      } catch (error) {
        terminalHandled = false
        throw error
      }
    }

    const applyTaskStatusUpdate = async (normalized: TaskStatus) => {
      if (cancelled) {
        return
      }

      setTaskStatusesAndRef((prev) => ({
        ...prev,
        [normalized.task_id]: normalized,
      }))

      if (!currentAudiobookProjectId && normalized.audiobook_project_id) {
        setCurrentAudiobookProjectId(normalized.audiobook_project_id)
      }

      const resolvedAudiobookProjectId = resolvePolledTaskAudiobookProjectId({
        currentAudiobookProjectId,
        task: normalized,
      })
      const nextActiveTask = selectNextActiveTaskAfterUpdate(taskStatusesRef.current, normalized)

      if (normalized.status === 'completed') {
        if (terminalHandled) {
          return
        }
        terminalHandled = true

        const shouldAutoDownload = shouldAutoDownloadCompletedTask(normalized)
        if (shouldAutoDownload) {
          try {
            await downloadCompletedProjectExport(normalized)
          } catch (error) {
            setSnackbar({
              open: true,
              message: await extractApiErrorMessage(error, t('audiobook.useAudiobookTaskStreamPolling.exportDownloadFailed')),
              severity: 'error',
            })
          }
        }

        if (nextActiveTask) {
          await focusNextActiveTask(nextActiveTask)
          return
        }

        setGenerating(false)
        setActiveStep(2)
        setProgressViewDismissed(false)
        if (resolvedAudiobookProjectId) {
          try {
            await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
          } catch {
            // 刷新有声书项目详情失败
          }
        }
        const completedMessage = getCompletedTaskSnackbarMessage(normalized, t)
        if (completedMessage) {
          setSnackbar({ open: true, message: completedMessage, severity: 'success' })
        }
        setCurrentTaskId(null)
        return
      }

      if (normalized.status === 'failed') {
        if (terminalHandled) {
          return
        }
        terminalHandled = true

        if (nextActiveTask) {
          await focusNextActiveTask(nextActiveTask)
          return
        }

        setGenerating(false)
        setActiveStep(0)
        setProgressViewDismissed(false)
        if (resolvedAudiobookProjectId) {
          try {
            await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
          } catch {
            // 刷新有声书项目详情失败
          }
        }
        setSnackbar({
          open: true,
          message: getFailedTaskSnackbarMessage(normalized, t),
          severity: 'error',
        })
        setCurrentTaskId(null)
        return
      }

      if (normalized.status === 'paused') {
        if (terminalHandled) {
          return
        }
        terminalHandled = true
        // 任务已暂停：停止轮询并释放 generating，保留 currentTaskId 与当前视图，
        // 以便进度页/任务横幅展示暂停状态与恢复入口。
        setGenerating(false)
        return
      }

      setGenerating(true)
    }

    const handleTaskNotFound = async () => {
      if (terminalHandled) {
        return
      }

      terminalHandled = true
      const nextActiveTask = selectNextActiveTask(taskStatusesRef.current, currentTaskId)

      if (nextActiveTask) {
        await focusNextActiveTask(nextActiveTask)
        return
      }

      setGenerating(false)
      setCurrentTaskId(null)
    }

    const fetchAndApplyTaskStatus = async () => {
      try {
        const response = await apiClient.getAudiobookTaskStatus(currentTaskId)

        if (isSuccessfulTaskPollStatus(response.status)) {
          failureCount = 0
          await applyTaskStatusUpdate(normalizeTaskStatusResponse(response.data))
          return
        }

        if (response.status === 404) {
          failureCount = 0
          await handleTaskNotFound()
          return
        }

        failureCount += 1
      } catch {
        failureCount += 1
        // 查询任务状态异常
      }
    }

    const pollTaskStatus = async () => {
      try {
        await fetchAndApplyTaskStatus()
      } finally {
        if (!terminalHandled) {
          scheduleNextPoll()
        }
      }
    }

    const applyStreamProgressPatch = (event: TaskProgressStreamEvent) => {
      setTaskStatusesAndRef((prev) => {
        const patched = applyTaskProgressStreamPatch(prev[currentTaskId], event)
        if (!patched) {
          return prev
        }

        return {
          ...prev,
          [currentTaskId]: patched,
        }
      })
    }

    const refreshTaskStatusFromStream = async () => {
      if (streamRefreshInFlight) {
        pendingStreamRefresh = true
        return
      }

      streamRefreshInFlight = true
      try {
        do {
          pendingStreamRefresh = false
          await fetchAndApplyTaskStatus()
        } while (pendingStreamRefresh && !cancelled && !terminalHandled)
      } finally {
        streamRefreshInFlight = false
      }
    }

    const handleStreamEvent = (event: TaskProgressStreamEvent) => {
      if (cancelled || terminalHandled) {
        return
      }

      if (event.event === 'connected') {
        streamConnected = true
        setStreamStatus('connected', { taskId: currentTaskId })
        failureCount = 0
        scheduleNextPoll()
        return
      }

      if (event.event === 'heartbeat') {
        return
      }

      if (event.event === 'progress') {
        applyStreamProgressPatch(event)
        void refreshTaskStatusFromStream()
      }
    }

    const startTaskProgressStream = async () => {
      if (!canStartTaskProgressStream({
        fetchAvailable: typeof fetch === 'function',
        abortControllerAvailable: typeof AbortController !== 'undefined',
      })) {
        setStreamStatus('fallback', {
          taskId: currentTaskId,
          reason: 'stream_api_unavailable',
        })
        return
      }

      setStreamStatus('connecting', { taskId: currentTaskId })
      streamAbortController = new AbortController()

      try {
        const response = await fetch(apiClient.getSSEStreamUrl(currentTaskId), {
          method: 'GET',
          headers: apiClient.getSSEStreamHeaders(),
          signal: streamAbortController.signal,
        })

        if (!hasReadableTaskProgressStreamResponse(response)) {
          throw new Error(`SSE stream unavailable: ${response.status}`)
        }

        streamConnected = true
        setStreamStatus('connected', { taskId: currentTaskId })
        failureCount = 0
        scheduleNextPoll()

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        try {
          while (!cancelled) {
            const { done, value } = await reader.read()
            if (done) {
              break
            }
            buffer += decoder.decode(value, { stream: true })
            buffer = consumeSseEventBuffer(buffer, handleStreamEvent)
          }

          buffer += decoder.decode()
          consumeSseEventBuffer(buffer, handleStreamEvent)
        } finally {
          reader.releaseLock()
        }
      } catch (error) {
        if (!cancelled && !isAbortError(error)) {
          streamConnected = false
          setStreamStatus('fallback', {
            taskId: currentTaskId,
            reason: error instanceof Error ? error.message : 'stream_error',
          })
          scheduleNextPoll(0)
        }
      } finally {
        const hadConnectedStream = streamConnected
        streamConnected = false
        if (cancelled) {
          setStreamStatus('closed', { taskId: currentTaskId, reason: 'cancelled' })
        } else if (shouldFallbackPollAfterStreamClose({
          cancelled,
          terminalHandled,
          hadConnectedStream,
        })) {
          setStreamStatus('fallback', { taskId: currentTaskId, reason: 'stream_closed' })
        }
        if (shouldFallbackPollAfterStreamClose({
          cancelled,
          terminalHandled,
          hadConnectedStream,
        })) {
          scheduleNextPoll(0)
        }
      }
    }

    void startTaskProgressStream()
    void pollTaskStatus()

    return () => {
      cancelled = true
      clearScheduledPoll()
      if (streamAbortController) {
        streamAbortController.abort()
      }
      setStreamStatus('closed', { taskId: currentTaskId, reason: 'effect_cleanup' })
    }
  }, [
    currentTaskId,
    currentAudiobookProjectId,
    refreshAudiobookProjectDetail,
    focusAudiobookTask,
    downloadCompletedProjectExport,
    setTaskStatusesAndRef,
    setCurrentAudiobookProjectId,
    setGenerating,
    setActiveStep,
    setProgressViewDismissed,
    setCurrentTaskId,
    setSnackbar,
    setStreamStatus,
    taskStatusesRef,
  ])
}
