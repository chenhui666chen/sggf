import { useCallback, useEffect, useRef } from 'react'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import {
  asObject,
  extractSnapshotStatusFields,
  resolveWaitingState,
  applySnapshotCompletedResult,
  resolveNotFoundRecovery,
  toDreamweaverRunSnapshot,
} from '@/pages/dreamweaver-run/runPageHelpers'
import { DREAMWEAVER_STAGES } from '@/constants/dreamweaver'
import { readPersistedDreamWeaverRun } from '@/utils/dreamweaver'
import type { DreamweaverRunSnapshot, DreamweaverRunPreflight, RunResult, Project, DreamweaverProjectLockedGenerationConfig } from '@/types/dreamweaver'
import type { GenerationConfigSource, GenerationConfigSetters } from '@/pages/dreamweaver-run/runPageHelpers'

export interface UseDreamweaverRunHydrationOptions {
  selectedProjectId: number | null
  lockedGenerationConfig: DreamweaverProjectLockedGenerationConfig | null
  generationConfigSetters: GenerationConfigSetters
  isNotFoundError: (e: unknown) => boolean
  shouldTreatRunNotFoundAsPending: (taskId: string | null, status: string | null) => boolean
  resetMissingRunState: (projectId: number | null) => void
  setProjects: React.Dispatch<React.SetStateAction<Project[]>>
  setTaskRunId: (id: string | null) => void
  setTaskStatus: (status: string | null) => void
  setTaskProgress: (progress: number) => void
  setTaskStage: (stage: string | null) => void
  setTaskState: (state: string | null) => void
  setTaskId: (id: string | null) => void
  setRunning: (running: boolean) => void
  setWaitingApproval: (waiting: boolean) => void
  setError: (error: string | null) => void
  setRunSnapshot: React.Dispatch<React.SetStateAction<DreamweaverRunSnapshot | null>>
  setRunSnapshotError: (error: string | null) => void
  setRunPreflight: React.Dispatch<React.SetStateAction<DreamweaverRunPreflight | null>>
  setResult: React.Dispatch<React.SetStateAction<RunResult | null>>
  applyGenerationConfig: (config: GenerationConfigSource, setters: GenerationConfigSetters) => void
}

export function useDreamweaverRunHydration(options: UseDreamweaverRunHydrationOptions) {
  const {
    selectedProjectId,
    lockedGenerationConfig,
    generationConfigSetters,
    isNotFoundError,
    shouldTreatRunNotFoundAsPending,
    resetMissingRunState,
    setProjects,
    setTaskRunId,
    setTaskStatus,
    setTaskProgress,
    setTaskStage,
    setTaskState,
    setTaskId,
    setRunning,
    setWaitingApproval,
    setError,
    setRunSnapshot,
    setRunSnapshotError,
    setRunPreflight,
    setResult,
    applyGenerationConfig,
  } = options

  const restoredProjectIdRef = useRef<number | null>(null)

  const hydrateFromPersistedRun = useCallback(async (
    projectId: number,
    runId: string,
    persistedTaskId: string | null,
    persistedStatus: string | null,
  ) => {
    if (!runId) return
    try {
      const res = await apiClient.getDreamweaverRun(runId)
      const data = toDreamweaverRunSnapshot(res.data)
      setRunSnapshot(data)
      setRunSnapshotError(null)

      const { status, statusLower, stage, state, progress } = extractSnapshotStatusFields(data)
      const contract = asObject(data?.contract)

      setTaskStatus(status || null)
      setTaskProgress(progress)
      setTaskStage(stage)
      setTaskState(state)

      const { waiting, isRunning } = resolveWaitingState({
        status,
        stage,
        state,
        waitingScriptApprovalStage: DREAMWEAVER_STAGES.WAITING_SCRIPT_APPROVAL,
        waitingApprovalStage: DREAMWEAVER_STAGES.WAITING_APPROVAL,
        waitingVideoConfirmationStage: DREAMWEAVER_STAGES.WAITING_VIDEO_CONFIRMATION,
      })
      setWaitingApproval(waiting)
      setRunning(isRunning)

      if (statusLower === 'completed' && contract) {
        applySnapshotCompletedResult(data, runId, { setResult, setRunPreflight })
      }

      if (waiting) {
        setTaskId(null)
        return
      }
      if (isRunning && persistedTaskId) {
        setTaskId(persistedTaskId)
      } else if (!isRunning) {
        setTaskId(null)
      }
    } catch (e: unknown) {
      const recovery = resolveNotFoundRecovery(e, persistedTaskId, persistedStatus, {
        isNotFoundError,
        shouldTreatRunNotFoundAsPending,
        pendingMessage: '运行数据尚未落库，稍后自动重试',
      })
      if (recovery.handled) {
        if (recovery.pendingMessage) {
          setRunSnapshotError(recovery.pendingMessage)
          return
        }
        resetMissingRunState(projectId)
        return
      }
      setRunSnapshotError(await extractApiErrorMessage(e, '恢复运行状态失败'))
    }
  }, [
    isNotFoundError,
    shouldTreatRunNotFoundAsPending,
    resetMissingRunState,
    setRunSnapshot,
    setRunSnapshotError,
    setTaskStatus,
    setTaskProgress,
    setTaskStage,
    setTaskState,
    setTaskId,
    setRunning,
    setWaitingApproval,
    setResult,
    setRunPreflight,
  ])

  useEffect(() => {
    const loadProjects = async () => {
      try {
        const res = await apiClient.getProjects()
        setProjects(res.data || [])
      } catch (e: unknown) {
        const msg = (e instanceof Error ? e.message : String(e)) || '获取项目列表失败'
        setError(msg)
      }
    }
    loadProjects()
  }, [setProjects, setError])

  useEffect(() => {
    if (!selectedProjectId) return
    if (restoredProjectIdRef.current === selectedProjectId) return
    restoredProjectIdRef.current = selectedProjectId

    const persisted = readPersistedDreamWeaverRun(selectedProjectId)
    if (!persisted) return

    setTaskRunId(persisted.run_id)
    setTaskStatus(persisted.status || null)
    applyGenerationConfig(persisted, generationConfigSetters)

    void hydrateFromPersistedRun(selectedProjectId, persisted.run_id, persisted.task_id ?? null, persisted.status ?? null)
  }, [selectedProjectId, hydrateFromPersistedRun, setTaskRunId, setTaskStatus, applyGenerationConfig, generationConfigSetters])

  useEffect(() => {
    if (!selectedProjectId) return
    if (!lockedGenerationConfig?.locked) return
    applyGenerationConfig(lockedGenerationConfig, generationConfigSetters)
  }, [lockedGenerationConfig, selectedProjectId, applyGenerationConfig, generationConfigSetters])

  return { hydrateFromPersistedRun }
}
