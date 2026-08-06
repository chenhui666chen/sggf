import { useEffect, type Dispatch, type SetStateAction } from 'react'

import { apiClient } from '../../services/api'
import type { TaskStatus } from './types'
import {
  buildTrackedTaskPollResult,
  getTaskPollDelayMs,
  isSuccessfulTaskPollStatus,
  selectActiveProjectTasks,
  selectActiveTaskFocusCandidate,
  shouldAutofocusActiveTask,
} from './taskUtils'

type FocusAudiobookTaskOptions = {
  loadProjectDetail?: boolean
  forceGenerating?: boolean
  activateProgressView?: boolean
}

interface UseAudiobookTaskListPollingParams {
  selectedProjectId: number | null
  trackedAudiobookProjectIds: readonly number[]
  trackedAudiobookProjectIdKey: string
  currentTaskId: string | null
  currentAudiobookProjectId: number | null
  currentAudiobookProjectDetailId?: number | null
  generating: boolean
  activeStep: number
  progressViewDismissed: boolean
  setTaskStatusesAndRef: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setActiveStep: Dispatch<SetStateAction<number>>
  focusAudiobookTask: (task: TaskStatus, options?: FocusAudiobookTaskOptions) => Promise<void>
}

type PollTimeoutId = ReturnType<typeof setTimeout>

const isDocumentHidden = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'hidden'

export const useAudiobookTaskListPolling = ({
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
}: UseAudiobookTaskListPollingParams) => {
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
          || !shouldAutofocusActiveTask({ currentTaskId, generating, activeStep, progressViewDismissed })
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
    trackedAudiobookProjectIds,
    trackedAudiobookProjectIdKey,
    currentTaskId,
    currentAudiobookProjectId,
    currentAudiobookProjectDetailId,
    generating,
    activeStep,
    progressViewDismissed,
    focusAudiobookTask,
    setTaskStatusesAndRef,
    setGenerating,
    setActiveStep,
  ])
}
