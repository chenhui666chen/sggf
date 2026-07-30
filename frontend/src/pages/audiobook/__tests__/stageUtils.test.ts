import { describe, expect, it } from 'vitest'

import { STAGE_KEYS } from '../constants'
import {
  buildPendingTaskStatus,
  getStageConfigForTask,
  isProjectExportTask,
  normalizeTaskStatusResponse,
} from '../utils'

describe('audiobook stage utils', () => {
  it('includes project export in the shared stage key registry', () => {
    expect(STAGE_KEYS).toContain('project_export')
  })

  it('detects export tasks and uses the export stage config', () => {
    expect(isProjectExportTask({ task_type: 'export_m4b' })).toBe(true)
    expect(isProjectExportTask({ task_type: 'export_audacity' })).toBe(true)
    expect(isProjectExportTask({ task_type: 'full' })).toBe(false)

    expect(getStageConfigForTask({ task_type: 'export_m4b' }).map((stage) => stage.key)).toEqual([
      'project_export',
    ])
    expect(getStageConfigForTask({ task_type: 'full' }).map((stage) => stage.key)).toContain(
      'tts_synthesis',
    )
  })

  it('replaces the TTS card with scene rendering only after live scene progress appears', () => {
    const stages = buildPendingTaskStatus({
      taskId: 'seed-task',
      audiobookProjectId: 12,
      taskType: 'full',
    }).stages
    stages.scene_rendering = {
      status: 'running',
      progress: 0.5,
    }

    const keys = getStageConfigForTask({
      task_type: 'full',
      current_stage: 'scene_rendering',
      stages,
    }).map((stage) => stage.key)

    expect(keys).toContain('scene_rendering')
    expect(keys).not.toContain('tts_synthesis')
    expect(getStageConfigForTask({ task_type: 'full' }).map((stage) => stage.key)).not.toContain(
      'scene_rendering',
    )
  })

  it('normalizes task status payloads and preserves task type', () => {
    const normalized = normalizeTaskStatusResponse({
      task_id: 'job-1',
      audiobook_project_id: 12,
      task_type: 'export_audacity',
      status: 'running',
      current_stage: 'project_export',
      detail: {
        stages: {
          project_export: {
            status: 'pending',
            progress: 25,
          },
        },
        overall_progress: 25,
      },
    })

    expect(normalized.task_type).toBe('export_audacity')
    expect(normalized.current_stage).toBe('project_export')
    expect(normalized.stages.project_export).toMatchObject({
      status: 'running',
      progress: 25,
    })
  })

  it('normalizes malformed task status payloads defensively', () => {
    const normalized = normalizeTaskStatusResponse({
      id: 99,
      audiobook_project_id: 'not-a-number',
      status: 'unknown',
      progress: Number.NaN,
      detail: {
        stages: {
          tts_synthesis: {
            status: 'completed',
            progress: 100,
            metrics: 'invalid',
          },
          unsupported_stage: {
            status: 'running',
          },
        },
      },
    })

    expect(normalized).toMatchObject({
      task_id: '99',
      audiobook_project_id: 0,
      status: 'pending',
      progress: 0,
      overall_progress: undefined,
    })
    expect(normalized.stages.tts_synthesis).toMatchObject({
      status: 'completed',
      progress: 100,
      metrics: undefined,
    })
    expect(normalized.stages.strategy.status).toBe('pending')
  })

  it('builds pending task status with a complete stage map', () => {
    const pending = buildPendingTaskStatus({
      taskId: 'job-2',
      audiobookProjectId: 34,
      taskType: 'full',
      chapterId: 56,
    })

    expect(pending).toMatchObject({
      task_id: 'job-2',
      audiobook_project_id: 34,
      chapter_id: 56,
      task_type: 'full',
      status: 'pending',
      progress: 0,
      overall_progress: 0,
    })
    expect(Object.keys(pending.stages).sort()).toEqual([...STAGE_KEYS].sort())
  })
})
