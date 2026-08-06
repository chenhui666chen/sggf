import { useCallback, type Dispatch, type SetStateAction } from 'react'

import type { ActivateQueuedAudiobookTaskOptions, SetSnackbar } from './hookTypes'
import type { AudiobookProjectDetail, Chapter, TaskStatus } from './types'
import { formatAudiobookTaskLabel, isActiveAudiobookTask } from './taskUtils'
import { buildPendingTaskStatus } from './utils'

interface FocusAudiobookTaskOptions {
  loadProjectDetail?: boolean
  forceGenerating?: boolean
  activateProgressView?: boolean
}

interface UseAudiobookTaskFocusActionsParams {
  chapters: readonly Pick<Chapter, 'id' | 'chapter_number'>[]
  currentAudiobookProjectDetailId?: number | null
  refreshAudiobookProjectDetail: (audiobookProjectId: number) => Promise<AudiobookProjectDetail>
  setCurrentTaskId: Dispatch<SetStateAction<string | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setGenerating: Dispatch<SetStateAction<boolean>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setLastGenerationMode: Dispatch<SetStateAction<'full' | 'script_only'>>
  setProgressViewDismissed: Dispatch<SetStateAction<boolean>>
  setSnackbar: SetSnackbar
}

export const useAudiobookTaskFocusActions = ({
  chapters,
  currentAudiobookProjectDetailId,
  refreshAudiobookProjectDetail,
  setCurrentTaskId,
  setCurrentAudiobookProjectId,
  setGenerating,
  setActiveStep,
  setTaskStatuses,
  setLastGenerationMode,
  setProgressViewDismissed,
  setSnackbar,
}: UseAudiobookTaskFocusActionsParams) => {
  const formatActiveTaskLabel = useCallback(
    (task: TaskStatus) => formatAudiobookTaskLabel(task, chapters),
    [chapters],
  )

  const focusAudiobookTask = useCallback(
    async (
      task: TaskStatus,
      options?: FocusAudiobookTaskOptions,
    ) => {
      setCurrentTaskId(task.task_id)
      setCurrentAudiobookProjectId(task.audiobook_project_id)

      if (options?.forceGenerating ?? isActiveAudiobookTask(task)) {
        setGenerating(true)
      }

      if (options?.activateProgressView) {
        setProgressViewDismissed(false)
        setActiveStep(1)
      } else if (options?.forceGenerating ?? isActiveAudiobookTask(task)) {
        setActiveStep((prev) => (prev === 0 ? 1 : prev))
      }

      if (
        options?.loadProjectDetail !== false
        && task.audiobook_project_id
        && currentAudiobookProjectDetailId !== task.audiobook_project_id
      ) {
        try {
          await refreshAudiobookProjectDetail(task.audiobook_project_id)
        } catch {
          // 切换任务焦点时刷新有声书项目详情失败
        }
      }
    },
    [
      currentAudiobookProjectDetailId,
      refreshAudiobookProjectDetail,
      setActiveStep,
      setCurrentAudiobookProjectId,
      setCurrentTaskId,
      setGenerating,
      setProgressViewDismissed,
    ],
  )

  const handleFocusActiveProjectTask = useCallback((task: TaskStatus) => {
    void focusAudiobookTask(task, {
      forceGenerating: true,
      activateProgressView: true,
    })
  }, [focusAudiobookTask])

  const activateQueuedAudiobookTask = useCallback(
    async (
      audiobookProjectId: number,
      jobId: string,
      options?: ActivateQueuedAudiobookTaskOptions,
    ) => {
      const nextTaskType = options?.taskType || options?.generationMode || 'full'
      const pendingTask = buildPendingTaskStatus({
        taskId: jobId,
        audiobookProjectId,
        taskType: nextTaskType,
      })

      setTaskStatuses((prev) => ({
        ...prev,
        [jobId]: pendingTask,
      }))
      if (nextTaskType === 'script_only' || nextTaskType === 'full') {
        setLastGenerationMode(nextTaskType)
      }

      await focusAudiobookTask(pendingTask, {
        forceGenerating: true,
        activateProgressView: true,
      })

      if (options?.successMessage) {
        setSnackbar({
          open: true,
          message: options.successMessage,
          severity: 'success',
        })
      }
    },
    [focusAudiobookTask, setLastGenerationMode, setSnackbar, setTaskStatuses],
  )

  return {
    formatActiveTaskLabel,
    handleFocusActiveProjectTask,
    focusAudiobookTask,
    activateQueuedAudiobookTask,
  }
}
