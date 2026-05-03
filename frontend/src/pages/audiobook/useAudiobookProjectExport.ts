import { useCallback, useState } from 'react'

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
  const [exportingProjectM4b, setExportingProjectM4b] = useState(false)
  const [exportingProjectAudacity, setExportingProjectAudacity] = useState(false)

  const audiobookProjectId = audiobookProject?.id ?? null
  const completedChapters = audiobookProject?.completed_chapters ?? 0

  const handleExportProjectM4b = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: '缺少有声书项目，无法导出', severity: 'error' })
      return
    }

    if (!completedChapters) {
      setSnackbar({ open: true, message: '暂无已生成章节，无法导出整本 M4B', severity: 'warning' })
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
        throw new Error('M4B 导出任务未返回 job_id')
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        taskType: 'export_m4b',
        successMessage: '整本 M4B 导出任务已进入队列，完成后会自动下载',
      })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, '整本 M4B 导出排队失败，请确认章节音频存在且 ffmpeg 可用'),
        severity: 'error',
      })
    } finally {
      setExportingProjectM4b(false)
    }
  }, [activateQueuedAudiobookTask, audiobookProjectId, completedChapters, projectTitle, setSnackbar])

  const handleExportProjectAudacity = useCallback(async () => {
    if (!audiobookProjectId) {
      setSnackbar({ open: true, message: '缺少有声书项目，无法导出', severity: 'error' })
      return
    }

    if (!completedChapters) {
      setSnackbar({ open: true, message: '暂无已生成章节，无法导出 Audacity ZIP', severity: 'warning' })
      return
    }

    setExportingProjectAudacity(true)
    try {
      const response = await apiClient.queueAudiobookProjectAudacityExport(audiobookProjectId)
      const jobId = extractQueuedAudiobookJobId(response.data)
      if (!jobId) {
        throw new Error('Audacity ZIP 导出任务未返回 job_id')
      }

      await activateQueuedAudiobookTask(audiobookProjectId, jobId, {
        taskType: 'export_audacity',
        successMessage: 'Audacity ZIP 导出任务已进入队列，完成后会自动下载',
      })
    } catch (error: unknown) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, 'Audacity ZIP 导出排队失败，请确认章节音频存在'),
        severity: 'error',
      })
    } finally {
      setExportingProjectAudacity(false)
    }
  }, [activateQueuedAudiobookTask, audiobookProjectId, completedChapters, setSnackbar])

  const downloadCompletedProjectExport = useCallback(async (task: TaskStatus) => {
    const title = resolveProjectExportTitle(projectTitle)

    if (task.task_type === 'export_m4b') {
      const response = await apiClient.downloadAudiobookProjectM4b(task.audiobook_project_id)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `${title}.m4b`,
      )
      triggerBlobDownload(response.data, filename)
      setSnackbar({ open: true, message: '整本 M4B 已导出并开始下载', severity: 'success' })
      return true
    }

    if (task.task_type === 'export_audacity') {
      const response = await apiClient.downloadAudiobookProjectAudacity(task.audiobook_project_id)
      const filename = extractDownloadFilename(
        response.headers?.['content-disposition'],
        `${title}_audacity.zip`,
      )
      triggerBlobDownload(response.data, filename)
      setSnackbar({ open: true, message: 'Audacity ZIP 已导出并开始下载', severity: 'success' })
      return true
    }

    return false
  }, [projectTitle, setSnackbar])

  return {
    exportingProjectM4b,
    exportingProjectAudacity,
    handleExportProjectM4b,
    handleExportProjectAudacity,
    downloadCompletedProjectExport,
  }
}
