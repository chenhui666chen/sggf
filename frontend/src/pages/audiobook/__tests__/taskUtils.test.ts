import { describe, expect, it } from 'vitest'

import type { TaskStatus } from '../types'
import { createEmptyStageMap } from '../utils'
import {
  buildActiveTaskRefs,
  buildTaskStatusMap,
  buildTrackedTaskPollResult,
  buildTrackedAudiobookProjectIdKey,
  compareTaskByRecency,
  formatAudiobookTaskLabel,
  getCompletedTaskSnackbarMessage,
  getFailedTaskSnackbarMessage,
  getTaskPollDelayMs,
  getTaskSortTimestamp,
  isActiveAudiobookTask,
  isSuccessfulTaskPollStatus,
  resolvePolledTaskAudiobookProjectId,
  selectActiveTaskFocusCandidate,
  selectActiveProjectTasks,
  selectActiveTaskStatus,
  selectNextActiveTask,
  selectNextActiveTaskAfterUpdate,
  selectPreferredActiveTask,
  selectTrackedAudiobookProjectIds,
  shouldAutoDownloadCompletedTask,
  shouldAutofocusActiveTask,
} from '../taskUtils'

const buildTask = (patch: Partial<TaskStatus>): TaskStatus => ({
  task_id: 'task-default',
  audiobook_project_id: 1,
  status: 'pending',
  progress: 0,
  stages: createEmptyStageMap(),
  ...patch,
})

describe('audiobook task utils', () => {
  it('detects active task statuses only for pending and running tasks', () => {
    expect(isActiveAudiobookTask(buildTask({ status: 'pending' }))).toBe(true)
    expect(isActiveAudiobookTask(buildTask({ status: 'running' }))).toBe(true)
    expect(isActiveAudiobookTask(buildTask({ status: 'completed' }))).toBe(false)
    expect(isActiveAudiobookTask(buildTask({ status: 'failed' }))).toBe(false)
    expect(isActiveAudiobookTask(null)).toBe(false)
  })

  it('sorts tasks by update time first and falls back to create time', () => {
    const older = buildTask({
      task_id: 'older',
      created_at: '2026-04-30T08:00:00.000Z',
      updated_at: 'invalid',
    })
    const newer = buildTask({
      task_id: 'newer',
      created_at: '2026-04-30T07:00:00.000Z',
      updated_at: '2026-04-30T09:00:00.000Z',
    })

    expect(getTaskSortTimestamp({ created_at: undefined, updated_at: undefined })).toBe(0)
    expect([older, newer].sort(compareTaskByRecency).map((task) => task.task_id)).toEqual([
      'newer',
      'older',
    ])
  })

  it('selects tracked project ids with dedupe and stable key sorting', () => {
    const trackedIds = selectTrackedAudiobookProjectIds({
      historyProjects: [
        { id: 3 },
        { id: 0 },
        { id: 3 },
        { id: 2 },
      ],
      audiobookProjectId: 9,
      currentAudiobookProjectId: 2,
    })

    expect(trackedIds).toEqual([3, 2, 9])
    expect(buildTrackedAudiobookProjectIdKey(trackedIds)).toBe('2,3,9')
  })

  it('selects active project tasks inside tracked projects by recency', () => {
    const taskStatuses = buildTaskStatusMap([
      buildTask({
        task_id: 'active-old',
        audiobook_project_id: 10,
        status: 'running',
        updated_at: '2026-04-30T08:00:00.000Z',
      }),
      buildTask({
        task_id: 'active-new',
        audiobook_project_id: 10,
        status: 'pending',
        updated_at: '2026-04-30T09:00:00.000Z',
      }),
      buildTask({
        task_id: 'completed',
        audiobook_project_id: 10,
        status: 'completed',
        updated_at: '2026-04-30T10:00:00.000Z',
      }),
      buildTask({
        task_id: 'other-project',
        audiobook_project_id: 11,
        status: 'running',
        updated_at: '2026-04-30T11:00:00.000Z',
      }),
    ])

    expect(selectActiveProjectTasks(taskStatuses, [10]).map((task) => task.task_id)).toEqual([
      'active-new',
      'active-old',
    ])
    expect(selectActiveProjectTasks(taskStatuses, []).map((task) => task.task_id)).toEqual([
      'other-project',
      'active-new',
      'active-old',
    ])
  })

  it('normalizes polled tasks and keeps only tracked audiobook projects', () => {
    const result = buildTrackedTaskPollResult([
      {
        task_id: 'tracked',
        audiobook_project_id: 10,
        status: 'running',
        progress: 30,
      },
      {
        task_id: 'other',
        audiobook_project_id: 11,
        status: 'running',
        progress: 40,
      },
      {
        invalid: true,
      },
    ], [10])

    expect(result.normalizedTasks.map((task) => task.task_id)).toEqual(['tracked'])
    expect(Object.keys(result.normalizedTaskMap)).toEqual(['tracked'])
    expect(buildTrackedTaskPollResult([], []).normalizedTasks).toEqual([])
  })

  it('recognizes successful task poll status codes', () => {
    expect(isSuccessfulTaskPollStatus(200)).toBe(true)
    expect(isSuccessfulTaskPollStatus(299)).toBe(true)
    expect(isSuccessfulTaskPollStatus(300)).toBe(false)
    expect(isSuccessfulTaskPollStatus(404)).toBe(false)
  })

  it('selects focused task, then active project task, then latest known task', () => {
    const focused = buildTask({
      task_id: 'focused',
      status: 'completed',
      updated_at: '2026-04-30T06:00:00.000Z',
    })
    const active = buildTask({
      task_id: 'active',
      status: 'running',
      updated_at: '2026-04-30T05:00:00.000Z',
    })
    const latest = buildTask({
      task_id: 'latest',
      status: 'failed',
      updated_at: '2026-04-30T10:00:00.000Z',
    })
    const taskStatuses = buildTaskStatusMap([focused, active, latest])

    expect(selectActiveTaskStatus({
      currentTaskId: 'focused',
      taskStatuses,
      activeProjectTasks: [active],
    })?.task_id).toBe('focused')
    expect(selectActiveTaskStatus({
      currentTaskId: null,
      taskStatuses,
      activeProjectTasks: [active],
    })?.task_id).toBe('active')
    expect(selectActiveTaskStatus({
      currentTaskId: null,
      taskStatuses,
      activeProjectTasks: [],
    })?.task_id).toBe('latest')
  })

  it('finds next active task while excluding the current task', () => {
    const taskStatuses = buildTaskStatusMap([
      buildTask({
        task_id: 'current',
        status: 'running',
        updated_at: '2026-04-30T12:00:00.000Z',
      }),
      buildTask({
        task_id: 'next',
        status: 'running',
        updated_at: '2026-04-30T11:00:00.000Z',
      }),
      buildTask({
        task_id: 'done',
        status: 'completed',
        updated_at: '2026-04-30T13:00:00.000Z',
      }),
    ])

    expect(selectNextActiveTask(taskStatuses, 'current')?.task_id).toBe('next')
    expect(selectNextActiveTask(taskStatuses, null)?.task_id).toBe('current')
  })

  it('selects the next active task after a polled task update', () => {
    const previousCurrent = buildTask({
      task_id: 'current',
      status: 'running',
      updated_at: '2026-04-30T12:00:00.000Z',
    })
    const next = buildTask({
      task_id: 'next',
      status: 'running',
      updated_at: '2026-04-30T11:00:00.000Z',
    })

    expect(selectNextActiveTaskAfterUpdate(
      buildTaskStatusMap([previousCurrent, next]),
      { ...previousCurrent, status: 'completed' },
    )?.task_id).toBe('next')
  })

  it('resolves polled task project ids and terminal task messages', () => {
    const generationTask = buildTask({ task_type: 'full', status: 'completed' })
    const exportTask = buildTask({ task_type: 'export_m4b', status: 'completed' })

    expect(resolvePolledTaskAudiobookProjectId({
      currentAudiobookProjectId: 7,
      task: buildTask({ audiobook_project_id: 8 }),
    })).toBe(7)
    expect(resolvePolledTaskAudiobookProjectId({
      currentAudiobookProjectId: null,
      task: buildTask({ audiobook_project_id: 8 }),
    })).toBe(8)

    expect(shouldAutoDownloadCompletedTask(generationTask)).toBe(false)
    expect(shouldAutoDownloadCompletedTask(exportTask)).toBe(true)
    expect(getCompletedTaskSnackbarMessage(generationTask)).toBe('生成完成！')
    expect(getCompletedTaskSnackbarMessage(exportTask)).toBeNull()
    expect(getFailedTaskSnackbarMessage(generationTask)).toBe('生成失败，请重试')
    expect(getFailedTaskSnackbarMessage(exportTask)).toBe('导出失败，请重试')
  })

  it('selects preferred active tasks and focus candidates', () => {
    const current = buildTask({
      task_id: 'current',
      audiobook_project_id: 8,
      status: 'running',
    })
    const fallback = buildTask({
      task_id: 'fallback',
      audiobook_project_id: 9,
      status: 'running',
    })

    expect(selectPreferredActiveTask([fallback, current], 'current')?.task_id).toBe('current')
    expect(selectPreferredActiveTask([fallback], null)?.task_id).toBe('fallback')
    expect(selectPreferredActiveTask([], 'missing')).toBeNull()

    expect(selectActiveTaskFocusCandidate({
      activeTasks: [current],
      currentTaskId: 'current',
      currentAudiobookProjectId: 8,
      currentAudiobookProjectDetailId: 8,
    })).toBeNull()

    expect(selectActiveTaskFocusCandidate({
      activeTasks: [current],
      currentTaskId: 'current',
      currentAudiobookProjectId: 8,
      currentAudiobookProjectDetailId: null,
    })).toEqual({
      task: current,
      loadProjectDetail: true,
    })

    expect(selectActiveTaskFocusCandidate({
      activeTasks: [fallback],
      currentTaskId: 'current',
      currentAudiobookProjectId: 8,
      currentAudiobookProjectDetailId: 8,
    })).toEqual({
      task: fallback,
      loadProjectDetail: true,
    })
  })

  it('builds active task refs for session persistence', () => {
    expect(buildActiveTaskRefs([
      buildTask({ task_id: 'task-a', audiobook_project_id: 8 }),
      buildTask({ task_id: 'task-b', audiobook_project_id: 9 }),
    ])).toEqual([
      { taskId: 'task-a', audiobookProjectId: 8 },
      { taskId: 'task-b', audiobookProjectId: 9 },
    ])
  })

  it('decides when an active task should autofocus', () => {
    expect(shouldAutofocusActiveTask({ currentTaskId: 'task-a', generating: false, activeStep: 2 })).toBe(true)
    expect(shouldAutofocusActiveTask({ currentTaskId: null, generating: true, activeStep: 2 })).toBe(true)
    expect(shouldAutofocusActiveTask({ currentTaskId: null, generating: false, activeStep: 1 })).toBe(true)
    expect(shouldAutofocusActiveTask({ currentTaskId: null, generating: false, activeStep: 2 })).toBe(false)
  })

  it('backs off task polling on failures and slows down hidden tabs', () => {
    expect(getTaskPollDelayMs({ failureCount: 0, documentHidden: false })).toBe(2000)
    expect(getTaskPollDelayMs({ failureCount: 2, documentHidden: false })).toBe(8000)
    expect(getTaskPollDelayMs({ failureCount: 0, documentHidden: true })).toBe(8000)
    expect(getTaskPollDelayMs({ failureCount: 9, documentHidden: false })).toBe(15000)
  })

  it('formats task labels with chapter and export context', () => {
    const chapters = [
      { id: 101, chapter_number: 7 },
    ]

    expect(formatAudiobookTaskLabel(buildTask({
      chapter_id: 101,
      task_type: 'script_only',
    }), chapters)).toBe('第7章 剧本')
    expect(formatAudiobookTaskLabel(buildTask({
      chapter_id: 202,
      task_type: 'audio_from_scripts',
    }), chapters)).toBe('章节202 音频')
    expect(formatAudiobookTaskLabel(buildTask({
      task_type: 'full',
    }), chapters)).toBe('批量任务 全流程')
    expect(formatAudiobookTaskLabel(buildTask({
      task_type: 'export_m4b',
    }), chapters)).toBe('整本 M4B 导出')
    expect(formatAudiobookTaskLabel(buildTask({
      task_type: 'export_audacity',
    }), chapters)).toBe('Audacity ZIP 导出')
  })
})
