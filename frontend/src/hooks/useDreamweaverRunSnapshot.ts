import { useState, useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type { DreamweaverRunSnapshot, RunResult, DreamweaverRunPreflight } from '@/types/dreamweaver'
import {
  asObject,
  toDreamweaverRunSnapshot,
  toDreamweaverVideoClipJobs,
  withRunSnapshotVideoJobs,
  applySnapshotCompletedResult,
  resolveNotFoundRecovery,
  shouldTreatRunNotFoundAsPending as _shouldTreatRunNotFoundAsPending,
  isNotFoundError,
} from '@/pages/dreamweaver-run/runPageHelpers'

export interface UseDreamweaverRunSnapshotOptions {
  getPersistedRunId: () => string | null
  getTaskId: () => string | null
  getTaskStatus: () => string | null
  getSelectedProjectId: () => number | null
  onResetMissingRunState: (projectId: number | null) => void
  onSetResult: Dispatch<SetStateAction<RunResult | null>>
  onSetRunPreflight: (v: DreamweaverRunPreflight | null) => void
}

export function useDreamweaverRunSnapshot(options: UseDreamweaverRunSnapshotOptions) {
  const {
    getPersistedRunId,
    getTaskId,
    getTaskStatus,
    getSelectedProjectId,
    onResetMissingRunState,
    onSetResult,
    onSetRunPreflight,
  } = options

  const [runSnapshot, setRunSnapshot] = useState<DreamweaverRunSnapshot | null>(null)
  const [runSnapshotLoading, setRunSnapshotLoading] = useState(false)
  const [runSnapshotError, setRunSnapshotError] = useState<string | null>(null)

  const loadRunSnapshot = useCallback(async () => {
    const persistedRunId = getPersistedRunId()
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.getDreamweaverRun(persistedRunId)
      const data = toDreamweaverRunSnapshot(res.data)
      setRunSnapshot(data)
      applySnapshotCompletedResult(data, persistedRunId, { setResult: onSetResult, setRunPreflight: onSetRunPreflight })
    } catch (e: unknown) {
      const recovery = resolveNotFoundRecovery(e, getTaskId(), getTaskStatus(), {
        isNotFoundError,
        shouldTreatRunNotFoundAsPending: _shouldTreatRunNotFoundAsPending,
        pendingMessage: '运行数据尚未落库，稍后自动重试',
      })
      if (recovery.handled) {
        if (recovery.pendingMessage) {
          setRunSnapshotError(recovery.pendingMessage)
          return
        }
        onResetMissingRunState(getSelectedProjectId())
        return
      }
      setRunSnapshotError(await extractApiErrorMessage(e, '加载运行快照失败'))
    } finally {
      setRunSnapshotLoading(false)
    }
  }, [getPersistedRunId, getTaskId, getTaskStatus, getSelectedProjectId, onResetMissingRunState, onSetResult, onSetRunPreflight])

  const rebuildVideoJobs = useCallback(async () => {
    const persistedRunId = getPersistedRunId()
    if (!persistedRunId) return
    setRunSnapshotLoading(true)
    setRunSnapshotError(null)
    try {
      const res = await apiClient.rebuildDreamweaverVideoJobs(persistedRunId)
      const data = asObject(res.data)
      const jobs = Array.isArray(data?.video_clip_jobs) ? toDreamweaverVideoClipJobs(data.video_clip_jobs) : null
      if (!jobs) {
        await loadRunSnapshot()
        return
      }

      if (!runSnapshot) {
        await loadRunSnapshot()
        return
      }

      setRunSnapshot((prev) => withRunSnapshotVideoJobs(prev, jobs))
    } catch (e: unknown) {
      setRunSnapshotError(await extractApiErrorMessage(e, '刷新任务卡失败'))
    } finally {
      setRunSnapshotLoading(false)
    }
  }, [getPersistedRunId, loadRunSnapshot, runSnapshot])

  const resetSnapshotState = useCallback(() => {
    setRunSnapshot(null)
    setRunSnapshotError(null)
  }, [])

  return {
    runSnapshot,
    runSnapshotLoading,
    runSnapshotError,
    setRunSnapshot,
    setRunSnapshotError,
    loadRunSnapshot,
    rebuildVideoJobs,
    resetSnapshotState,
  }
}
