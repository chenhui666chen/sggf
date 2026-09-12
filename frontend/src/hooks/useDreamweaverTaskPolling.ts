import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import {
  toDreamweaverTaskStatus,
  getThrownErrorStatus,
  isTimeoutErrorLike,
  isNetworkErrorLike,
} from '@/pages/dreamweaver-run/runPageHelpers'
import { mergeRunResult } from '@/utils/dreamweaver'
import type { RunResult, DreamweaverRunPreflight, DreamweaverTaskArtifacts } from '@/types/dreamweaver'

export interface UseDreamweaverTaskPollingOptions {
  taskId: string | null
  setError: (error: string | null) => void
  setResult: React.Dispatch<React.SetStateAction<RunResult | null>>
  setRunPreflight: React.Dispatch<React.SetStateAction<DreamweaverRunPreflight | null>>
  applyQueuedStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyRunningStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyWaitingStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyTerminalStatus: (data: { run_id?: string | null }) => void
  applyCompletedStatus: (data: { progress?: number; state?: string | null; stage?: string | null }) => void
  applyFailedStatus: (data: { progress?: number; state?: string | null; stage?: string | null }) => void
}

export function useDreamweaverTaskPolling(options: UseDreamweaverTaskPollingOptions) {
  const {
    taskId,
    setError,
    setResult,
    setRunPreflight,
    applyQueuedStatus,
    applyRunningStatus,
    applyWaitingStatus,
    applyTerminalStatus,
    applyCompletedStatus,
    applyFailedStatus,
  } = options

  const { t } = useTranslation()

  useEffect(() => {
    if (!taskId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const poll = async () => {
      try {
        const res = await apiClient.getDreamweaverTask(taskId)
        const data = toDreamweaverTaskStatus(res.data)
        if (cancelled) return
        if (!data) {
          setError(t('dreamweaverRun.taskStatusFormatInvalid'))
          applyTerminalStatus({ run_id: null })
          return
        }
        setError(null)

        if ((data as { status: string }).status === 'queued') {
          applyQueuedStatus(data)
          timer = setTimeout(poll, 1000)
          return
        }

        if ((data as { status: string }).status === 'running') {
          applyRunningStatus(data)
          timer = setTimeout(poll, 1000)
          return
        }

        if ((data as { status: string }).status === 'waiting') {
          applyWaitingStatus(data)
          return
        }

        applyTerminalStatus(data)

        if ((data as { status: string }).status === 'completed') {
          applyCompletedStatus(data)
          setResult((prev) => mergeRunResult(prev, (data as { result?: unknown }).result as RunResult | null))
          if ((data as { result?: { preflight?: unknown } }).result?.preflight) {
            setRunPreflight((data as { result: { preflight: DreamweaverRunPreflight } }).result.preflight)
          }
        } else {
          applyFailedStatus(data)
          setError((data as { error?: string }).error || t('dreamweaverRun.taskFailed'))
        }
      } catch (e: unknown) {
        if (cancelled) return
        const message = await extractApiErrorMessage(e, t('dreamweaverRun.taskStatusQueryFailed'))
        const status = getThrownErrorStatus(e)
        const isTimeout = isTimeoutErrorLike(e)
        const isNetworkError = isNetworkErrorLike(e)

        if (isTimeout || isNetworkError || (status !== null && status >= 500)) {
          setError(message)
          timer = setTimeout(poll, 2000)
          return
        }

        applyTerminalStatus({ run_id: null })
        setError(message)
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [taskId, applyQueuedStatus, applyRunningStatus, applyWaitingStatus, applyTerminalStatus, applyCompletedStatus, applyFailedStatus, setError, setResult, setRunPreflight, t])
}
