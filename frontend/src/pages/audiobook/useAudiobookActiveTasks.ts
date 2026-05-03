import { useMemo } from 'react'

import type { AudiobookProjectHistoryItem, TaskStatus } from './types'
import {
  buildActiveTaskRefs,
  buildTrackedAudiobookProjectIdKey,
  selectActiveProjectTasks,
  selectActiveTaskStatus,
  selectTrackedAudiobookProjectIds,
} from './taskUtils'

interface UseAudiobookActiveTasksParams {
  historyProjects: readonly Pick<AudiobookProjectHistoryItem, 'id'>[]
  audiobookProjectId?: number | null
  currentAudiobookProjectId: number | null
  currentTaskId: string | null
  taskStatuses: Record<string, TaskStatus>
}

export const useAudiobookActiveTasks = ({
  historyProjects,
  audiobookProjectId,
  currentAudiobookProjectId,
  currentTaskId,
  taskStatuses,
}: UseAudiobookActiveTasksParams) => {
  const trackedAudiobookProjectIds = useMemo(() => {
    return selectTrackedAudiobookProjectIds({
      historyProjects,
      audiobookProjectId,
      currentAudiobookProjectId,
    })
  }, [historyProjects, audiobookProjectId, currentAudiobookProjectId])

  const trackedAudiobookProjectIdKey = useMemo(
    () => buildTrackedAudiobookProjectIdKey(trackedAudiobookProjectIds),
    [trackedAudiobookProjectIds],
  )

  const activeProjectTasks = useMemo(
    () => selectActiveProjectTasks(taskStatuses, trackedAudiobookProjectIds),
    [taskStatuses, trackedAudiobookProjectIds],
  )

  const hasActiveM4bExportTask = useMemo(
    () => activeProjectTasks.some((task) => task.task_type === 'export_m4b'),
    [activeProjectTasks],
  )

  const hasActiveAudacityExportTask = useMemo(
    () => activeProjectTasks.some((task) => task.task_type === 'export_audacity'),
    [activeProjectTasks],
  )

  const persistedActiveTaskRefs = useMemo(
    () => buildActiveTaskRefs(activeProjectTasks),
    [activeProjectTasks],
  )

  const activeTaskStatus = useMemo(
    () => selectActiveTaskStatus({ currentTaskId, taskStatuses, activeProjectTasks }),
    [currentTaskId, taskStatuses, activeProjectTasks],
  )

  return {
    trackedAudiobookProjectIds,
    trackedAudiobookProjectIdKey,
    activeProjectTasks,
    hasActiveM4bExportTask,
    hasActiveAudacityExportTask,
    persistedActiveTaskRefs,
    activeTaskStatus,
  }
}
