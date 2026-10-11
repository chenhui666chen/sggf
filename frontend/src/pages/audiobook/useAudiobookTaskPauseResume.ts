import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { ActivateQueuedAudiobookTask, SetSnackbar } from './hookTypes'
import { isSuccessfulTaskPollStatus } from './taskUtils'
import type { TaskStatus } from './types'

interface UseAudiobookTaskPauseResumeParams {
  currentTaskId: string | null
  setTaskStatuses: Dispatch<SetStateAction<Record<string, TaskStatus>>>
  setSnackbar: SetSnackbar
  activateQueuedAudiobookTask: ActivateQueuedAudiobookTask
  setProgressViewDismissed: Dispatch<SetStateAction<boolean>>
}

/**
 * 有声书生成任务的暂停/恢复操作。
 *
 * 暂停为协作式：API 仅标记 pause_requested，Worker 在章节边界才真正停止；
 * 恢复会从暂停时记录的剩余章节重新入队一个新任务并聚焦到进度页。
 */
export const useAudiobookTaskPauseResume = ({
  currentTaskId,
  setTaskStatuses,
  setSnackbar,
  activateQueuedAudiobookTask,
  setProgressViewDismissed,
}: UseAudiobookTaskPauseResumeParams) => {
  const { t } = useTranslation()
  const [pauseResuming, setPauseResuming] = useState(false)

  const handlePauseTask = useCallback(async (taskId?: string) => {
    const targetTaskId = taskId || currentTaskId
    if (!targetTaskId) {
      return
    }
    try {
      const response = await apiClient.pauseAudiobookTask(targetTaskId)
      if (isSuccessfulTaskPollStatus(response.status)) {
        setTaskStatuses((prev) => (
          prev[targetTaskId]
            ? {
                ...prev,
                [targetTaskId]: { ...prev[targetTaskId], status: 'pause_requested' },
              }
            : prev
        ))
        setSnackbar({
          open: true,
          message: t('audiobook.useAudiobookTaskPauseResume.pauseRequested'),
          severity: 'info',
        })
        return
      }
      setSnackbar({
        open: true,
        message: response.data?.detail || t('audiobook.useAudiobookTaskPauseResume.pauseFailed'),
        severity: 'error',
      })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookTaskPauseResume.pauseFailed')),
        severity: 'error',
      })
    }
  }, [currentTaskId, setSnackbar, setTaskStatuses, t])

  const handleResumeTask = useCallback(async (taskId?: string) => {
    const targetTaskId = taskId || currentTaskId
    if (!targetTaskId) {
      return
    }
    setPauseResuming(true)
    try {
      const response = await apiClient.resumeAudiobookTask(targetTaskId)
      if (isSuccessfulTaskPollStatus(response.status) && response.data?.success && !response.data?.job_id) {
        setTaskStatuses((prev) => (
          prev[targetTaskId]
            ? {
                ...prev,
                [targetTaskId]: { ...prev[targetTaskId], status: 'running' },
              }
            : prev
        ))
        setSnackbar({
          open: true,
          message: response.data.message || t('audiobook.useAudiobookTaskPauseResume.resumeContinued'),
          severity: 'success',
        })
        return
      }
      if (isSuccessfulTaskPollStatus(response.status) && response.data?.job_id) {
        const jobId = response.data.job_id as string
        const audiobookProjectId = response.data.audiobook_project_id as number
        const taskType = response.data.task_type as string | undefined
        setProgressViewDismissed(false)
        await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
          taskType,
          successMessage: t('audiobook.useAudiobookTaskPauseResume.resumeQueued'),
        })
        return
      }
      setSnackbar({
        open: true,
        message: response.data?.detail || t('audiobook.useAudiobookTaskPauseResume.resumeFailed'),
        severity: 'error',
      })
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookTaskPauseResume.resumeFailed')),
        severity: 'error',
      })
    } finally {
      setPauseResuming(false)
    }
  }, [activateQueuedAudiobookTask, currentTaskId, setProgressViewDismissed, setSnackbar, t])

  return {
    pauseResuming,
    handlePauseTask,
    handleResumeTask,
  }
}
