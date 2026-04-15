import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import { workflowWebSocket } from '@/services/websocket'
import type {
  StoryExpansionAnalysis,
  StoryExpansionResult,
  StoryExpansionTaskMeta,
} from '@/types/storyExpansion'
import { buildStoryExpansionCompletionMessage } from '@/utils/storyExpansionFeedback'
import {
  getStoryExpansionResultFromTaskComplete,
  isStoryExpansionTaskError,
} from '@/utils/storyExpansionEvents'
import {
  clearStoredStoryExpansionResult,
  clearStoryExpansionTaskPersistence,
  coerceStoryExpansionResult,
  getStoryExpansionStorageKeys,
  parseStoredStoryExpansionResult,
  parseStoredStoryExpansionTaskMeta,
  persistStoryExpansionTaskMeta,
  persistStoryExpansionTaskPersistence,
  storeStoryExpansionResult,
} from '@/utils/storyExpansionStorage'
import { getStoryExpansionTaskMeta } from '@/utils/storyExpansionTiming'

interface UseStoryExpansionTaskOptions {
  projectId?: string
  refreshWorkflowData: () => void | Promise<void>
  refreshFramework: () => void | Promise<unknown>
  showSnackbar: (message: string, severity: 'success' | 'error') => void
}

interface UseStoryExpansionTaskReturn {
  expandingStory: boolean
  showStoryExpansionResultDialog: boolean
  setShowStoryExpansionResultDialog: Dispatch<SetStateAction<boolean>>
  storyExpansionResult: StoryExpansionResult | null
  storyExpansionTaskEstimate: StoryExpansionTaskMeta | null
  storyExpansionTaskStartedAt: number | null
  storyExpansionElapsedMs: number | null
  beginStoryExpansionRequest: (analysis?: StoryExpansionAnalysis | null) => void
  handleStoryExpansionTaskStarted: (taskId: string | null | undefined) => void
  handleStoryExpansionTaskFailure: (message: string) => void
}

interface StoryTaskStatusResponse {
  status?: unknown
  result?: unknown
  error?: unknown
}

const STORY_EXPANSION_RECOVERY_MISSING_TASK_ID_MESSAGE = '协同扩展任务无法恢复，请重新发起'

export function useStoryExpansionTask({
  projectId,
  refreshWorkflowData,
  refreshFramework,
  showSnackbar,
}: UseStoryExpansionTaskOptions): UseStoryExpansionTaskReturn {
  const [expandingStory, setExpandingStory] = useState(false)
  const [showStoryExpansionResultDialog, setShowStoryExpansionResultDialog] = useState(false)
  const [storyExpansionResult, setStoryExpansionResult] = useState<StoryExpansionResult | null>(null)
  const [storyExpansionTaskEstimate, setStoryExpansionTaskEstimate] = useState<StoryExpansionTaskMeta | null>(null)
  const [storyExpansionTaskStartedAt, setStoryExpansionTaskStartedAt] = useState<number | null>(null)
  const [storyExpansionElapsedTick, setStoryExpansionElapsedTick] = useState(() => Date.now())

  const refreshWorkflowDataRef = useRef(refreshWorkflowData)
  const refreshFrameworkRef = useRef(refreshFramework)
  const showSnackbarRef = useRef(showSnackbar)
  const activeTaskIdRef = useRef<string | null>(null)
  const activeTaskStartedAtRef = useRef<number | null>(null)
  const activeTaskEstimateRef = useRef<StoryExpansionTaskMeta | null>(null)

  useEffect(() => {
    refreshWorkflowDataRef.current = refreshWorkflowData
  }, [refreshWorkflowData])

  useEffect(() => {
    refreshFrameworkRef.current = refreshFramework
  }, [refreshFramework])

  useEffect(() => {
    showSnackbarRef.current = showSnackbar
  }, [showSnackbar])

  const triggerRefreshSafely = useCallback((action: () => void | Promise<unknown>) => {
    void Promise.resolve(action()).catch(() => undefined)
  }, [])

  const resetStoryExpansionTaskTracking = useCallback(() => {
    activeTaskIdRef.current = null
    activeTaskStartedAtRef.current = null
    activeTaskEstimateRef.current = null
    setStoryExpansionTaskStartedAt(null)
    setStoryExpansionTaskEstimate(null)
    setStoryExpansionElapsedTick(Date.now())
  }, [])

  const storyExpansionElapsedMs = (
    expandingStory
    && storyExpansionTaskStartedAt != null
  )
    ? Math.max(0, storyExpansionElapsedTick - storyExpansionTaskStartedAt)
    : null

  useEffect(() => {
    if (!expandingStory || storyExpansionTaskStartedAt == null) {
      return
    }

    setStoryExpansionElapsedTick(Date.now())
    const intervalId = window.setInterval(() => {
      setStoryExpansionElapsedTick(Date.now())
    }, 30_000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [expandingStory, storyExpansionTaskStartedAt])

  const resolveStoryExpansionResult = useCallback((payload: unknown): StoryExpansionResult | null => {
    if (typeof payload === 'string') {
      try {
        return coerceStoryExpansionResult(JSON.parse(payload) as unknown)
      } catch {
        return null
      }
    }

    return coerceStoryExpansionResult(payload)
  }, [])

  const handleStoryExpansionTaskSuccess = useCallback((
    resultData: StoryExpansionResult,
    fallbackMessage = '协同扩展已完成',
  ) => {
    resetStoryExpansionTaskTracking()
    setStoryExpansionResult(resultData)
    setShowStoryExpansionResultDialog(true)
    setExpandingStory(false)

    if (projectId) {
      storeStoryExpansionResult(projectId, resultData)
      clearStoryExpansionTaskPersistence(projectId)
    }

    triggerRefreshSafely(() => refreshWorkflowDataRef.current())
    triggerRefreshSafely(() => refreshFrameworkRef.current())

    const baseMessage = typeof resultData.message === 'string' && resultData.message.trim()
      ? resultData.message.trim()
      : fallbackMessage
    showSnackbarRef.current(buildStoryExpansionCompletionMessage(baseMessage, resultData), 'success')
  }, [projectId, resetStoryExpansionTaskTracking, triggerRefreshSafely])

  const handleStoryExpansionTaskResultParseFailure = useCallback((
    message = '协同扩展已完成，但结果解析失败，已刷新最新数据',
  ) => {
    resetStoryExpansionTaskTracking()
    setExpandingStory(false)

    if (projectId) {
      clearStoryExpansionTaskPersistence(projectId)
    }

    triggerRefreshSafely(() => refreshWorkflowDataRef.current())
    triggerRefreshSafely(() => refreshFrameworkRef.current())
    showSnackbarRef.current(message, 'error')
  }, [projectId, resetStoryExpansionTaskTracking, triggerRefreshSafely])

  const handleStoryExpansionTaskFailure = useCallback((message: string) => {
    resetStoryExpansionTaskTracking()
    setExpandingStory(false)
    if (projectId) {
      clearStoryExpansionTaskPersistence(projectId)
    }
    showSnackbarRef.current(message, 'error')
  }, [projectId, resetStoryExpansionTaskTracking])

  const beginStoryExpansionRequest = useCallback((analysis?: StoryExpansionAnalysis | null) => {
    const startedAt = Date.now()
    const taskEstimate = getStoryExpansionTaskMeta(analysis)

    activeTaskIdRef.current = null
    activeTaskStartedAtRef.current = startedAt
    activeTaskEstimateRef.current = taskEstimate
    setStoryExpansionTaskStartedAt(startedAt)
    setStoryExpansionTaskEstimate(taskEstimate)
    setStoryExpansionElapsedTick(startedAt)

    if (projectId) {
      clearStoredStoryExpansionResult(projectId)
      clearStoryExpansionTaskPersistence(projectId)
      persistStoryExpansionTaskPersistence(projectId, null, startedAt)
      persistStoryExpansionTaskMeta(projectId, taskEstimate)
    }

    setStoryExpansionResult(null)
    setShowStoryExpansionResultDialog(false)
    setExpandingStory(true)
  }, [projectId])

  const handleStoryExpansionTaskStarted = useCallback((taskId: string | null | undefined) => {
    const normalizedTaskId = typeof taskId === 'string' && taskId.trim()
      ? taskId.trim()
      : null
    const startedAt = activeTaskStartedAtRef.current ?? Date.now()

    activeTaskIdRef.current = normalizedTaskId
    activeTaskStartedAtRef.current = startedAt
    setStoryExpansionTaskStartedAt(startedAt)

    if (!projectId) {
      return
    }

    persistStoryExpansionTaskPersistence(projectId, normalizedTaskId, startedAt)
    persistStoryExpansionTaskMeta(projectId, activeTaskEstimateRef.current)
  }, [projectId])

  const fetchTaskStatus = useCallback(async (taskId: string): Promise<StoryTaskStatusResponse | null> => {
    const token = localStorage.getItem('access_token')
    if (!token || !taskId) {
      return null
    }

    try {
      const response = await fetch(`/api/v1/workflow/task/${taskId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        return null
      }
      return await response.json() as StoryTaskStatusResponse
    } catch {
      return null
    }
  }, [])

  const applyRecoveredTaskStatus = useCallback((
    statusData: StoryTaskStatusResponse,
    options?: {
      successMessage?: string
      parseFailureMessage?: string
    },
  ): boolean => {
    const statusRaw = String(statusData.status || '').toLowerCase()
    if (statusRaw === 'completed') {
      const resultData = resolveStoryExpansionResult(statusData.result)
      if (resultData) {
        handleStoryExpansionTaskSuccess(resultData, options?.successMessage ?? '协同扩展完成')
      } else {
        handleStoryExpansionTaskResultParseFailure(
          options?.parseFailureMessage ?? '协同扩展已完成，但结果解析失败，已刷新最新数据',
        )
      }
      return true
    }

    if (statusRaw === 'failed' || statusRaw === 'timeout') {
      handleStoryExpansionTaskFailure(`协同扩展失败: ${String(statusData.error || '任务失败')}`)
      return true
    }

    return false
  }, [
    handleStoryExpansionTaskFailure,
    handleStoryExpansionTaskResultParseFailure,
    handleStoryExpansionTaskSuccess,
    resolveStoryExpansionResult,
  ])

  useEffect(() => {
    if (!projectId) {
      resetStoryExpansionTaskTracking()
      return
    }

    const storyStorageKeys = getStoryExpansionStorageKeys(projectId)
    const savedStoryState = localStorage.getItem(storyStorageKeys.taskState)
    const storyStartTime = localStorage.getItem(storyStorageKeys.taskStartedAt)
    const storyTaskIdRaw = localStorage.getItem(storyStorageKeys.taskId)
    const savedTaskMeta = parseStoredStoryExpansionTaskMeta(localStorage.getItem(storyStorageKeys.taskMeta))
    const storyTaskId = typeof storyTaskIdRaw === 'string' && storyTaskIdRaw.trim()
      ? storyTaskIdRaw.trim()
      : null
    const parsedStoryStartedAt = storyStartTime
      ? Number.parseInt(storyStartTime, 10)
      : Number.NaN
    const storyStartedAt = Number.isFinite(parsedStoryStartedAt)
      ? parsedStoryStartedAt
      : null

    activeTaskIdRef.current = storyTaskId
    activeTaskStartedAtRef.current = storyStartedAt
    activeTaskEstimateRef.current = savedTaskMeta
    setStoryExpansionTaskStartedAt(storyStartedAt)
    setStoryExpansionTaskEstimate(savedTaskMeta)
    setStoryExpansionElapsedTick(Date.now())

    if (savedStoryState === 'true') {
      if (storyTaskId) {
        setExpandingStory(true)
      } else {
        clearStoryExpansionTaskPersistence(projectId)
        resetStoryExpansionTaskTracking()
        showSnackbarRef.current(STORY_EXPANSION_RECOVERY_MISSING_TASK_ID_MESSAGE, 'error')
      }
    }

    const savedStoryResult = localStorage.getItem(storyStorageKeys.result)
    if (savedStoryResult) {
      const parsedStoryResult = parseStoredStoryExpansionResult(savedStoryResult)
      if (parsedStoryResult) {
        setStoryExpansionResult(parsedStoryResult)
      } else {
        clearStoredStoryExpansionResult(projectId)
      }
    }

    let cancelled = false

    const recoverStoryIfDone = async () => {
      if (savedStoryState !== 'true' || !storyTaskId) {
        return
      }

      const statusData = await fetchTaskStatus(storyTaskId)
      if (!statusData || cancelled) {
        return
      }

      const resolved = applyRecoveredTaskStatus(statusData, {
        successMessage: '协同扩展完成',
        parseFailureMessage: '协同扩展已完成，但结果解析失败，已刷新最新数据',
      })

      if (!resolved && !cancelled) {
        setExpandingStory(true)
      }
    }

    void recoverStoryIfDone()

    return () => {
      cancelled = true
    }
  }, [applyRecoveredTaskStatus, fetchTaskStatus, projectId, resetStoryExpansionTaskTracking])

  useEffect(() => {
    if (!projectId) {
      return
    }

    const numericProjectId = Number.parseInt(projectId, 10)
    if (!Number.isFinite(numericProjectId)) {
      return
    }

    let disposed = false
    const connectPromise = workflowWebSocket.connect()

    const unsubscribeTaskComplete = workflowWebSocket.onTaskComplete((data) => {
      const activeTaskId = activeTaskIdRef.current
      if (!activeTaskId || data.task_id !== activeTaskId) {
        return
      }

      const resultData = getStoryExpansionResultFromTaskComplete(data)
      if (resultData) {
        handleStoryExpansionTaskSuccess(resultData, '协同扩展完成')
        return
      }

      handleStoryExpansionTaskResultParseFailure()
    })

    const unsubscribeTaskError = workflowWebSocket.onTaskError((data) => {
      const activeTaskId = activeTaskIdRef.current
      if (!activeTaskId || data.task_id !== activeTaskId || !isStoryExpansionTaskError(data)) {
        return
      }

      const error = data.error || '任务失败'
      handleStoryExpansionTaskFailure(`协同扩展失败: ${error}`)
    })

    const unsubscribeDisconnect = workflowWebSocket.onDisconnect(() => {
      const activeTaskId = activeTaskIdRef.current
      if (!activeTaskId) {
        return
      }

      void fetchTaskStatus(activeTaskId)
        .then((statusData) => {
          if (!statusData || disposed) {
            return
          }

          applyRecoveredTaskStatus(statusData, {
            successMessage: '协同扩展完成',
            parseFailureMessage: '协同扩展已完成，但结果解析失败，已刷新最新数据',
          })
        })
        .catch(() => undefined)
    })

    void connectPromise
      .then(() => {
        if (disposed) {
          return
        }
        workflowWebSocket.joinProject(numericProjectId)
      })
      .catch(() => {
        if (disposed || !activeTaskIdRef.current) {
          return
        }

        showSnackbarRef.current('协同扩展任务连接失败，页面将继续尝试恢复结果', 'error')
      })

    return () => {
      disposed = true
      unsubscribeTaskComplete()
      unsubscribeTaskError()
      unsubscribeDisconnect()
    }
  }, [
    applyRecoveredTaskStatus,
    fetchTaskStatus,
    handleStoryExpansionTaskFailure,
    handleStoryExpansionTaskResultParseFailure,
    handleStoryExpansionTaskSuccess,
    projectId,
  ])

  return {
    expandingStory,
    showStoryExpansionResultDialog,
    setShowStoryExpansionResultDialog,
    storyExpansionResult,
    storyExpansionTaskEstimate,
    storyExpansionTaskStartedAt,
    storyExpansionElapsedMs,
    beginStoryExpansionRequest,
    handleStoryExpansionTaskStarted,
    handleStoryExpansionTaskFailure,
  }
}
