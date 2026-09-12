import { useCallback, useState } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { triggerBlobDownload } from '../../utils/blobDownload'
import type { ActivateQueuedAudiobookTask, SetSnackbar } from './hookTypes'
import { extractQueuedAudiobookJobId } from './scriptEditorUtils'
import type { AudiobookProjectDetail, TaskStatus } from './types'
import { extractDownloadFilename } from './utils'

interface UseAudiobookProjectExportParams {
  audiobookProject: AudiobookProjectDetail | null
  projectTitle?: string | null
  activateQueuedAudiobookTask: ActivateQueuedAudiobookTask
  setSnackbar: SetSnackbar
}

const resolveProjectExportTitle = (projectTitle?: string | null) => projectTitle?.trim() || 'audiobook'

export const useAudiobookProjectExport = ({
  audiobookProject,
  projectTitle,
  activateQueuedAudiobookTask,
  setSnackbar,
}: UseAudiobookProjectExportParams) => {
  const { t } = useTranslation()
  const [exportingProjectM4b, setExportingProjectM4b] = useState(false)
  const [exportingProjectAudacity, setExportingProjectAudacity] = useState(false)

  const audiobookProjectId = audiobookProject?.id ?? null
  const completedChapters = audiobookProject?.completed_chapters ?? 0

  const handleExportProjectM4b = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.missingProject'), severity: 'error' })
      return
    }

    if (!completedChapters) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.noCompletedM4b'), severity: 'warning' })
      return
    }

    setExportingProjectM4b(true)
    try {
      const response = await apiClient.queueAudiobookProjectM4bExport(
        audiobookProjectId,
        { title: resolveProjectExportTitle(projectTitle) },
      )
      const jobId = extractQueuedAudiobookJobId(response.data)
      if (!jobId) {
        throw new Error(t('audiobook.useAudiobookProjectExport.m4bJobIdMissing'))
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        taskType: 'export_m4b',
        successMessage: t('audiobook.useAudiobookProjectExport.m4bQueued'),
      })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookProjectExport.m4bQueueFailed')),
        severity: 'error',
      })
    } finally {
      setExportingProjectM4b(false)
    }
  }, [activateQueuedAudiobookTask, audiobookProjectId, completedChapters, projectTitle, setSnackbar, t])

  const handleExportProjectAudacity = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.missingProject'), severity: 'error' })
      return
    }

    if (!completedChapters) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.noCompletedAudacity'), severity: 'warning' })
      return
    }

    setExportingProjectAudacity(true)
    try {
      const response = await apiClient.queueAudiobookProjectAudacityExport(audiobookProjectId)
      const jobId = extractQueuedAudiobookJobId(response.data)
      if (!jobId) {
        throw new Error(t('audiobook.useAudiobookProjectExport.audacityJobIdMissing'))
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        taskType: 'export_audacity',
        successMessage: t('audiobook.useAudiobookProjectExport.audacityQueued'),
      })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('audiobook.useAudiobookProjectExport.audacityQueueFailed')),
        severity: 'error',
      })
    } finally {
      setExportingProjectAudacity(false)
    }
  }, [activateQueuedAudiobookTask, audiobookProjectId, completedChapters, setSnackbar, t])

  const downloadCompletedProjectExport = useCallback(async (task: TaskStatus) => {
    const title = resolveProjectExportTitle(projectTitle)

    if (task.task_type === 'export_m4b') {
      const response = await apiClient.downloadAudiobookProjectM4b(task.audiobook_project_id)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `${title}.m4b`,
      )
      triggerBlobDownload(response.data, filename)
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.m4bDownloaded'), severity: 'success' })
      return true
    }

    if (task.task_type === 'export_audacity') {
      const response = await apiClient.downloadAudiobookProjectAudacity(task.audiobook_project_id)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `${title}_audacity.zip`,
      )
      triggerBlobDownload(response.data, filename)
      setSnackbar({ open: true, message: t('audiobook.useAudiobookProjectExport.audacityDownloaded'), severity: 'success' })
      return true
    }

    return false
  }, [projectTitle, setSnackbar, t])

  return {
    exportingProjectM4b,
    exportingProjectAudacity,
    handleExportProjectM4b,
    handleExportProjectAudacity,
    downloadCompletedProjectExport,
  }
}
