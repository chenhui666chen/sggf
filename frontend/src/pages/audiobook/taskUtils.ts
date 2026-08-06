import type {
  AudiobookProjectHistoryItem,
  Chapter,
  TaskStatus,
} from './types'
import {
  isProjectExportTask,
  normalizeTaskStatusResponse,
} from './utils'

export interface ActiveTaskRef {
  taskId: string
  audiobookProjectId: number
}

export const TASK_POLL_BASE_INTERVAL_MS = 2000
export const TASK_POLL_HIDDEN_INTERVAL_MS = 8000
export const TASK_POLL_MAX_INTERVAL_MS = 15000

const normalizePositiveProjectId = (value: unknown): number | null => {
  const id = Number(value)
  return Number.isFinite(id) && id > 0 ? id : null
}

export const isActiveAudiobookTask = (task: TaskStatus | null | undefined): task is TaskStatus =>
  Boolean(task && (task.status === 'pending' || task.status === 'running'))

export const isPausedAudiobookTask = (task: TaskStatus | null | undefined): task is TaskStatus =>
  Boolean(task && (task.status === 'paused' || task.status === 'pause_requested'))

export const getTaskSortTimestamp = (
  task: Pick<TaskStatus, 'updated_at' | 'created_at'>,
): number => {
  const raw = task.updated_at || task.created_at
  if (!raw) {
    return 0
  }
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

export const compareTaskByRecency = (left: TaskStatus, right: TaskStatus): number =>
  getTaskSortTimestamp(right) - getTaskSortTimestamp(left)

export const selectTrackedAudiobookProjectIds = ({
  historyProjects,
  audiobookProjectId,
  currentAudiobookProjectId,
}: {
  historyProjects: readonly Pick<AudiobookProjectHistoryItem, 'id'>[]
  audiobookProjectId?: number | null
  currentAudiobookProjectId?: number | null
}): number[] => {
  const ids = new Set<number>()

  for (const project of historyProjects) {
    const projectId = normalizePositiveProjectId(project?.id)
    if (projectId) {
      ids.add(projectId)
    }
  }

  for (const candidate of [audiobookProjectId, currentAudiobookProjectId]) {
    const projectId = normalizePositiveProjectId(candidate)
    if (projectId) {
      ids.add(projectId)
    }
  }

  return Array.from(ids)
}

export const buildTrackedAudiobookProjectIdKey = (projectIds: readonly number[]): string =>
  projectIds.slice().sort((left, right) => left - right).join(',')

export const selectActiveProjectTasks = (
  taskStatuses: Record<string, TaskStatus>,
  trackedProjectIds: readonly number[],
): TaskStatus[] => {
  const trackedIds = new Set(trackedProjectIds)
  return Object.values(taskStatuses)
    .filter((task) => trackedIds.size === 0 || trackedIds.has(task.audiobook_project_id))
    .filter((task) => isActiveAudiobookTask(task))
    .sort(compareTaskByRecency)
}

export const selectPausedProjectTasks = (
  taskStatuses: Record<string, TaskStatus>,
  trackedProjectIds: readonly number[],
): TaskStatus[] => {
  const trackedIds = new Set(trackedProjectIds)
  return Object.values(taskStatuses)
    .filter((task) => trackedIds.size === 0 || trackedIds.has(task.audiobook_project_id))
    .filter((task) => isPausedAudiobookTask(task))
    .sort(compareTaskByRecency)
}

export const buildActiveTaskRefs = (
  activeTasks: readonly TaskStatus[],
): ActiveTaskRef[] =>
  activeTasks.map((task) => ({
    taskId: task.task_id,
    audiobookProjectId: task.audiobook_project_id,
  }))

export const selectActiveTaskStatus = ({
  currentTaskId,
  taskStatuses,
  activeProjectTasks,
}: {
  currentTaskId: string | null
  taskStatuses: Record<string, TaskStatus>
  activeProjectTasks: readonly TaskStatus[]
}): TaskStatus | null => {
  if (currentTaskId && taskStatuses[currentTaskId]) {
    return taskStatuses[currentTaskId]
  }
  if (activeProjectTasks.length > 0) {
    return activeProjectTasks[0]
  }

  return Object.values(taskStatuses).sort(compareTaskByRecency)[0] || null
}

export const selectNextActiveTask = (
  taskStatuses: Record<string, TaskStatus>,
  excludedTaskId?: string | null,
): TaskStatus | null =>
  Object.values(taskStatuses)
    .filter((task) => task.task_id !== excludedTaskId)
    .filter((task) => isActiveAudiobookTask(task))
    .sort(compareTaskByRecency)[0] || null

export const selectNextActiveTaskAfterUpdate = (
  taskStatuses: Record<string, TaskStatus>,
  updatedTask: TaskStatus,
): TaskStatus | null =>
  selectNextActiveTask({
    ...taskStatuses,
    [updatedTask.task_id]: updatedTask,
  }, updatedTask.task_id)

export const buildTaskStatusMap = (
  tasks: readonly TaskStatus[],
): Record<string, TaskStatus> =>
  tasks.reduce<Record<string, TaskStatus>>((acc, task) => {
    acc[task.task_id] = task
    return acc
  }, {})

export const isSuccessfulTaskPollStatus = (status: number): boolean =>
  status >= 200 && status < 300

export const buildTrackedTaskPollResult = (
  rawTasks: unknown,
  trackedProjectIds: readonly number[],
) => {
  const trackedIds = new Set(trackedProjectIds)
  if (trackedIds.size === 0) {
    return {
      normalizedTasks: [] as TaskStatus[],
      normalizedTaskMap: {},
    }
  }

  const normalizedTasks = (Array.isArray(rawTasks) ? rawTasks : [])
    .map((task: unknown) => normalizeTaskStatusResponse(task))
    .filter((task) => trackedIds.has(task.audiobook_project_id))

  return {
    normalizedTasks,
    normalizedTaskMap: buildTaskStatusMap(normalizedTasks),
  }
}

export const selectPreferredActiveTask = (
  activeTasks: readonly TaskStatus[],
  currentTaskId: string | null,
): TaskStatus | null =>
  activeTasks.find((task) => task.task_id === currentTaskId) || activeTasks[0] || null

export const selectActiveTaskFocusCandidate = ({
  activeTasks,
  currentTaskId,
  currentAudiobookProjectId,
  currentAudiobookProjectDetailId,
}: {
  activeTasks: readonly TaskStatus[]
  currentTaskId: string | null
  currentAudiobookProjectId: number | null
  currentAudiobookProjectDetailId?: number | null
}): { task: TaskStatus; loadProjectDetail: boolean } | null => {
  const preferredTask = selectPreferredActiveTask(activeTasks, currentTaskId)
  if (!preferredTask) {
    return null
  }

  const loadProjectDetail = currentAudiobookProjectDetailId !== preferredTask.audiobook_project_id
  if (
    preferredTask.task_id !== currentTaskId
    || preferredTask.audiobook_project_id !== currentAudiobookProjectId
    || loadProjectDetail
  ) {
    return {
      task: preferredTask,
      loadProjectDetail,
    }
  }

  return null
}

export const resolvePolledTaskAudiobookProjectId = ({
  currentAudiobookProjectId,
  task,
}: {
  currentAudiobookProjectId: number | null
  task: Pick<TaskStatus, 'audiobook_project_id'>
}): number | null =>
  currentAudiobookProjectId || task.audiobook_project_id || null

export const shouldAutoDownloadCompletedTask = (
  task: Pick<TaskStatus, 'status' | 'task_type'>,
): boolean =>
  task.status === 'completed' && isProjectExportTask(task)

export const getCompletedTaskSnackbarMessage = (
  task: Pick<TaskStatus, 'task_type'>,
): string | null =>
  isProjectExportTask(task) ? null : '生成完成！'

export const getFailedTaskSnackbarMessage = (
  task: Pick<TaskStatus, 'task_type'>,
): string =>
  isProjectExportTask(task) ? '导出失败，请重试' : '生成失败，请重试'

export const shouldAutofocusActiveTask = ({
  currentTaskId,
  generating,
  activeStep,
  progressViewDismissed,
}: {
  currentTaskId: string | null
  generating: boolean
  activeStep: number
  progressViewDismissed: boolean
}): boolean =>
  !progressViewDismissed
  && (Boolean(currentTaskId) || generating || activeStep === 0 || activeStep === 1)

export const getTaskPollDelayMs = ({
  failureCount,
  documentHidden,
}: {
  failureCount: number
  documentHidden: boolean
}): number => {
  const normalizedFailureCount = Math.max(0, Math.trunc(failureCount))
  const failureDelay = TASK_POLL_BASE_INTERVAL_MS * (2 ** normalizedFailureCount)
  const visibilityDelay = documentHidden ? TASK_POLL_HIDDEN_INTERVAL_MS : TASK_POLL_BASE_INTERVAL_MS
  return Math.min(
    Math.max(failureDelay, visibilityDelay),
    TASK_POLL_MAX_INTERVAL_MS,
  )
}

export const formatAudiobookTaskLabel = (
  task: TaskStatus,
  chapters: readonly Pick<Chapter, 'id' | 'chapter_number'>[],
): string => {
  const chapter = task.chapter_id
    ? chapters.find((item) => item.id === task.chapter_id)
    : null
  const chapterLabel = chapter
    ? `第${chapter.chapter_number}章`
    : task.chapter_id
      ? `章节${task.chapter_id}`
      : '批量任务'

  switch (task.task_type) {
    case 'script_only':
      return `${chapterLabel} 剧本`
    case 'audio_from_scripts':
      return `${chapterLabel} 音频`
    case 'prompt_audio_asr_transcript':
      return `${chapterLabel} ASR 转写`
    case 'export_m4b':
      return '整本 M4B 导出'
    case 'export_audacity':
      return 'Audacity ZIP 导出'
    case 'full':
      return `${chapterLabel} 全流程`
    default:
      return chapterLabel
  }
}
