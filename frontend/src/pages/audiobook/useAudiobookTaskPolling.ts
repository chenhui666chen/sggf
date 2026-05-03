import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { AudiobookProjectDetail, TaskStatus } from './types'
import {
  normalizeTaskStatusResponse,
} from './utils'
import {
  buildTrackedTaskPollResult,
  getCompletedTaskSnackbarMessage,
  getFailedTaskSnackbarMessage,
  getTaskPollDelayMs,
  isSuccessfulTaskPollStatus,
  resolvePolledTaskAudiobookProjectId,
  selectActiveTaskFocusCandidate,
  selectActiveProjectTasks,
  selectNextActiveTask,
  selectNextActiveTaskAfterUpdate,
  shouldAutoDownloadCompletedTask,
  shouldAutofocusActiveTask,
} from './taskUtils'

type FocusAudiobookTaskOptions = {
  loadProjectDetail?: boolean
  forceGenerating?: boolean
  activateProgressView?: boolean
}

interface UseAudiobookTaskPollingParams {
  selectedProjectId: number | null
  trackedAudiobookProjectIds: readonly number[]
  trackedAudiobookProjectIdKey: string
  currentTaskId: string | null
  currentAudiobookProjectId: number | null
  currentAudiobookProjectDetailId?: number | null
  generating: boolean
  activeStep: number
  taskStatuses: Record<string, TaskStatus>
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setSnackbar: SetSnackbar
  focusAudiobookTask: (task: TaskStatus, options?: FocusAudiobookTaskOptions) => Promise<void>
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<AudiobookProjectDetail>
  downloadCompletedProjectExport: (task: TaskStatus) => Promise<unknown>
}

const isDocumentHidden = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'hidden'

type PollTimeoutId = ReturnType<typeof setTimeout>

const SSE_FALLBACK_POLL_INTERVAL_MS = 30000
const SSE_FALLBACK_HIDDEN_POLL_INTERVAL_MS = 60000

type TaskProgressStreamEvent = {
  event?: string
  data?: unknown
  timestamp?: string
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value && typeof value === 'object' && !Array.isArray(value))

const getFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

const consumeSseEventBuffer = (
  buffer: string,
  handleEvent: (event: TaskProgressStreamEvent) => void,
): string => {
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() ?? ''

  for (const block of blocks) {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
      .trim()

    if (!data) {
      continue
    }

    try {
      const parsed = JSON.parse(data) as unknown
      if (isRecord(parsed)) {
        handleEvent({
          event: typeof parsed.event === 'string' ? parsed.event : undefined,
          data: parsed.data,
          timestamp: typeof parsed.timestamp === 'string' ? parsed.timestamp : undefined,
        })
      }
    } catch {
      // 忽略单条无法解析的 SSE 事件，后续轮询兜底会修正状态。
    }
  }

  return rest
}

const isAbortError = (error: unknown): boolean =>
  isRecord(error) && error.name === 'AbortError'

export const useAudiobookTaskPolling = ({
  selectedProjectId,
  trackedAudiobookProjectIds,
  trackedAudiobookProjectIdKey,
  currentTaskId,
  currentAudiobookProjectId,
  currentAudiobookProjectDetailId,
  generating,
  activeStep,
  taskStatuses,
  setTaskStatuses,
  setCurrentTaskId,
  setCurrentAudiobookProjectId,
  setGenerating,
  setActiveStep,
  setSnackbar,
  focusAudiobookTask,
  refreshAudiobookProjectDetail,
  downloadCompletedProjectExport,
}: UseAudiobookTaskPollingParams) => {
  const taskStatusesRef = useRef(taskStatuses)
  const setTaskStatusesAndRef = useCallback((
    updater: SetStateAction<Record<string, TaskStatus>>,
  ) => {
    setTaskStatuses((prev) => {
      const next = typeof updater === 'function'
        ? (updater as (value: Record<string, TaskStatus>) => Record<string, TaskStatus>)(prev)
        : updater
      taskStatusesRef.current = next
      return next
    })
  }, [setTaskStatuses])

  useEffect(() => {
    taskStatusesRef.current = taskStatuses
  }, [taskStatuses])

  useEffect(() => {
    if (!selectedProjectId) {
      return
    }

    let cancelled = false
    let failureCount = 0
    let timeoutId: PollTimeoutId | null = null

    const scheduleNextPoll = () => {
      if (cancelled) {
        return
      }

      timeoutId = setTimeout(() => {
        void pollTaskList()
      }, getTaskPollDelayMs({
        failureCount,
        documentHidden: isDocumentHidden(),
      }))
    }

    const pollTaskList = async () => {
      try {
        const response = await apiClient.listAudiobookTasks()

        if (!isSuccessfulTaskPollStatus(response.status)) {
          failureCount += 1
          return
        }
        failureCount = 0

        const { normalizedTasks, normalizedTaskMap } = buildTrackedTaskPollResult(
          response.data,
          trackedAudiobookProjectIds,
        )

        if (cancelled) {
          return
        }

        if (normalizedTasks.length > 0) {
          setTaskStatusesAndRef((prev) => ({
            ...prev,
            ...normalizedTaskMap,
          }))
        }

        const activeTasks = selectActiveProjectTasks(normalizedTaskMap, trackedAudiobookProjectIds)
        if (
          activeTasks.length === 0
          || !shouldAutofocusActiveTask({ currentTaskId, generating, activeStep })
        ) {
          return
        }

        const focusCandidate = selectActiveTaskFocusCandidate({
          activeTasks,
          currentTaskId,
          currentAudiobookProjectId,
          currentAudiobookProjectDetailId,
        })
        if (focusCandidate) {
          await focusAudiobookTask(focusCandidate.task, {
            forceGenerating: true,
            activateProgressView: true,
            loadProjectDetail: focusCandidate.loadProjectDetail,
          })
          return
        }

        setGenerating(true)
        setActiveStep((prev) => (prev === 0 ? 1 : prev))
      } catch {
        failureCount += 1
        // 查询任务列表异常
      } finally {
        scheduleNextPoll()
      }
    }

    void pollTaskList()

    return () => {
      cancelled = true
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }, [
    selectedProjectId,
    trackedAudiobookProjectIdKey,
    currentTaskId,
    currentAudiobookProjectId,
    currentAudiobookProjectDetailId,
    generating,
    activeStep,
    focusAudiobookTask,
    setTaskStatusesAndRef,
    setGenerating,
    setActiveStep,
  ])

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
              message: await extractApiErrorMessage(error, '导出完成，但自动下载失败，请手动重试下载'),
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
        if (resolvedAudiobookProjectId) {
          try {
            await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
          } catch {
            // 刷新有声书项目详情失败
          }
        }
        const completedMessage = getCompletedTaskSnackbarMessage(normalized)
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
        if (resolvedAudiobookProjectId) {
          try {
            await refreshAudiobookProjectDetail(resolvedAudiobookProjectId)
          } catch {
            // 刷新有声书项目详情失败
          }
        }
        setSnackbar({
          open: true,
          message: getFailedTaskSnackbarMessage(normalized),
          severity: 'error',
        })
        setCurrentTaskId(null)
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
      if (event.event !== 'progress') {
        return
      }

      const data = isRecord(event.data) ? event.data : {}
      const stage = typeof data.stage === 'string' ? data.stage : null
      const progress = getFiniteNumber(data.progress)
      if (!stage && progress === null) {
        return
      }

      setTaskStatusesAndRef((prev) => {
        const existing = prev[currentTaskId]
        if (!existing) {
          return prev
        }

        const nextProgress = progress === null
          ? existing.progress
          : Math.max(existing.progress || 0, progress)

        return {
          ...prev,
          [currentTaskId]: {
            ...existing,
            status: existing.status === 'pending' ? 'running' : existing.status,
            current_stage: stage ?? existing.current_stage,
            progress: nextProgress,
            updated_at: event.timestamp || new Date().toISOString(),
          },
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
      if (typeof fetch !== 'function' || typeof AbortController === 'undefined') {
        return
      }

      streamAbortController = new AbortController()

      try {
        const response = await fetch(apiClient.getSSEStreamUrl(currentTaskId), {
          method: 'GET',
          headers: apiClient.getSSEStreamHeaders(),
          signal: streamAbortController.signal,
        })

        if (!response.ok || !response.body) {
          throw new Error(`SSE stream unavailable: ${response.status}`)
        }

        streamConnected = true
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
          scheduleNextPoll(0)
        }
      } finally {
        const hadConnectedStream = streamConnected
        streamConnected = false
        if (!cancelled && !terminalHandled && hadConnectedStream) {
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
    setCurrentTaskId,
    setSnackbar,
  ])
}
