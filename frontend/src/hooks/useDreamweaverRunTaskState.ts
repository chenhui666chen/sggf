import { useState, useCallback } from 'react'
import type { DreamweaverTaskArtifacts } from '@/types/dreamweaver'

export interface DreamweaverRunTaskState {
  running: boolean
  taskId: string | null
  taskRunId: string | null
  taskStatus: string | null
  taskQueue: string | null
  taskProgress: number
  taskState: string | null
  taskStage: string | null
  taskArtifacts: DreamweaverTaskArtifacts | null
  waitingApproval: boolean
  videoJobActionError: string | null
  videoJobConfirmingShotId: string | null
}

export interface DreamweaverRunTaskStateHandlers {
  setRunning: (v: boolean) => void
  setTaskId: (v: string | null) => void
  setTaskRunId: React.Dispatch<React.SetStateAction<string | null>>
  setTaskStatus: (v: string | null) => void
  setTaskQueue: (v: string | null) => void
  setTaskProgress: (v: number) => void
  setTaskState: (v: string | null) => void
  setTaskStage: (v: string | null) => void
  setTaskArtifacts: (v: DreamweaverTaskArtifacts | null) => void
  setWaitingApproval: (v: boolean) => void
  setVideoJobActionError: (v: string | null) => void
  setVideoJobConfirmingShotId: (v: string | null) => void
  resetTaskState: () => void
  applyQueuedStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyRunningStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyWaitingStatus: (data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => void
  applyTerminalStatus: (data: { run_id?: string | null }) => void
  applyCompletedStatus: (data: { progress?: number; state?: string | null; stage?: string | null }) => void
  applyFailedStatus: (data: { progress?: number; state?: string | null; stage?: string | null }) => void
}

export function useDreamweaverRunTaskState() {
  const [running, setRunning] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskRunId, setTaskRunId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<string | null>(null)
  const [taskQueue, setTaskQueue] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState<number>(0)
  const [taskState, setTaskState] = useState<string | null>(null)
  const [taskStage, setTaskStage] = useState<string | null>(null)
  const [taskArtifacts, setTaskArtifacts] = useState<DreamweaverTaskArtifacts | null>(null)
  const [waitingApproval, setWaitingApproval] = useState(false)
  const [videoJobActionError, setVideoJobActionError] = useState<string | null>(null)
  const [videoJobConfirmingShotId, setVideoJobConfirmingShotId] = useState<string | null>(null)

  const resetTaskState = useCallback(() => {
    setTaskId(null)
    setTaskRunId(null)
    setRunning(false)
    setWaitingApproval(false)
    setTaskStatus(null)
    setTaskQueue(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)
    setVideoJobActionError(null)
    setVideoJobConfirmingShotId(null)
  }, [])

  const applyQueuedStatus = useCallback((data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => {
    setRunning(true)
    setTaskStatus('queued')
    setTaskQueue(data.queue || null)
    setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
    setTaskState(data.state || null)
    setTaskStage(data.stage || null)
    setTaskArtifacts(data.artifacts || null)
    setTaskRunId((prev) => data.run_id || prev)
    setWaitingApproval(false)
  }, [])

  const applyRunningStatus = useCallback((data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => {
    setTaskStatus('running')
    setTaskQueue(data.queue || null)
    setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
    setTaskState(data.state || null)
    setTaskStage(data.stage || null)
    setTaskArtifacts(data.artifacts || null)
    setTaskRunId((prev) => data.run_id || prev)
    setWaitingApproval(false)
  }, [])

  const applyWaitingStatus = useCallback((data: { queue?: string | null; progress?: number; state?: string | null; stage?: string | null; artifacts?: DreamweaverTaskArtifacts | null; run_id?: string | null }) => {
    setTaskStatus('waiting')
    setTaskQueue(data.queue || null)
    setRunning(false)
    setTaskId(null)
    setTaskProgress(typeof data.progress === 'number' ? data.progress : 0)
    setTaskState(data.state || null)
    setTaskStage(data.stage || null)
    setTaskArtifacts(data.artifacts || null)
    setTaskRunId((prev) => data.run_id || prev)
    setWaitingApproval(true)
  }, [])

  const applyTerminalStatus = useCallback((data: { run_id?: string | null }) => {
    setRunning(false)
    setTaskId(null)
    setTaskRunId((prev) => data.run_id || prev)
    setTaskStatus(null)
    setTaskQueue(null)
    setTaskProgress(0)
    setTaskState(null)
    setTaskStage(null)
    setTaskArtifacts(null)
    setWaitingApproval(false)
  }, [])

  const applyCompletedStatus = useCallback((data: { progress?: number; state?: string | null; stage?: string | null }) => {
    setTaskStatus('completed')
    setTaskProgress(typeof data.progress === 'number' ? data.progress : 100)
    setTaskState(data.state || null)
    setTaskStage(data.stage || null)
  }, [])

  const applyFailedStatus = useCallback((data: { progress?: number; state?: string | null; stage?: string | null }) => {
    setTaskStatus('failed')
    setTaskProgress(typeof data.progress === 'number' ? data.progress : 100)
    setTaskState(data.state || null)
    setTaskStage(data.stage || null)
  }, [])

  return {
    running,
    taskId,
    taskRunId,
    taskStatus,
    taskQueue,
    taskProgress,
    taskState,
    taskStage,
    taskArtifacts,
    waitingApproval,
    videoJobActionError,
    videoJobConfirmingShotId,
    setRunning,
    setTaskId,
    setTaskRunId,
    setTaskStatus,
    setTaskQueue,
    setTaskProgress,
    setTaskState,
    setTaskStage,
    setTaskArtifacts,
    setWaitingApproval,
    setVideoJobActionError,
    setVideoJobConfirmingShotId,
    resetTaskState,
    applyQueuedStatus,
    applyRunningStatus,
    applyWaitingStatus,
    applyTerminalStatus,
    applyCompletedStatus,
    applyFailedStatus,
  }
}
