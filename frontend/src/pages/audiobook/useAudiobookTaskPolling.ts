import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react'

import type { SetSnackbar } from './hookTypes'
import type { AudiobookProjectDetail, TaskStatus } from './types'
import { useAudiobookTaskListPolling } from './useAudiobookTaskListPolling'
import { useAudiobookTaskStreamPolling } from './useAudiobookTaskStreamPolling'

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
  progressViewDismissed: boolean
  taskStatuses: Record<string, TaskStatus>
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
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

export const useAudiobookTaskPolling = ({
  selectedProjectId,
  trackedAudiobookProjectIds,
  trackedAudiobookProjectIdKey,
  currentTaskId,
  currentAudiobookProjectId,
  currentAudiobookProjectDetailId,
  generating,
  activeStep,
  progressViewDismissed,
  taskStatuses,
  setTaskStatuses,
  setCurrentTaskId,
  setCurrentAudiobookProjectId,
  setGenerating,
  setActiveStep,
  setProgressViewDismissed,
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

  useAudiobookTaskListPolling({
    selectedProjectId,
    trackedAudiobookProjectIds,
    trackedAudiobookProjectIdKey,
    currentTaskId,
    currentAudiobookProjectId,
    currentAudiobookProjectDetailId,
    generating,
    activeStep,
    progressViewDismissed,
    setTaskStatusesAndRef,
    setGenerating,
    setActiveStep,
    focusAudiobookTask,
  })

  useAudiobookTaskStreamPolling({
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
  })
}
