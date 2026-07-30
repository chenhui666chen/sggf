import { describe, expect, it } from 'vitest'

import type { TaskStatus } from '../types'
import {
  applyAudiobookSceneProgress,
  type AudiobookProgressData,
} from '../audiobookSceneProgress'
import { createEmptyStageMap } from '../utils'

const buildTask = (patch: Partial<TaskStatus> = {}): TaskStatus => ({
  task_id: 'task-1',
  audiobook_project_id: 12,
  chapter_id: 34,
  task_type: 'full',
  status: 'running',
  current_stage: 'tts_synthesis',
  progress: 0.7,
  stages: createEmptyStageMap(),
  ...patch,
})

const buildEvent = (patch: Partial<AudiobookProgressData> = {}): AudiobookProgressData => ({
  audiobook_project_id: 12,
  chapter_id: 34,
  stage: 'scene_rendering',
  progress: 50,
  message: '场景音频处理完成：scene_0002',
  stage_metrics: {
    scene_id: 'scene_0002',
    processed_segment_count: 2,
    total_segment_count: 4,
  },
  ...patch,
})

describe('audiobook scene progress', () => {
  it('把匹配任务的场景进度归一化并写入独立阶段', () => {
    const updated = applyAudiobookSceneProgress(buildTask(), buildEvent())

    expect(updated).not.toBeNull()
    expect(updated).toMatchObject({
      status: 'running',
      current_stage: 'scene_rendering',
    })
    expect(updated?.stages.scene_rendering).toEqual({
      status: 'running',
      progress: 0.5,
      message: '场景音频处理完成：scene_0002',
      metrics: {
        scene_id: 'scene_0002',
        processed_segment_count: 2,
        total_segment_count: 4,
      },
    })
  })

  it('在 100% 时完成场景阶段，并限制越界进度', () => {
    const updated = applyAudiobookSceneProgress(buildTask(), buildEvent({ progress: 130 }))

    expect(updated?.stages.scene_rendering).toMatchObject({
      status: 'completed',
      progress: 1,
    })
  })

  it('忽略其它项目、其它单章任务、其它阶段和终态任务', () => {
    expect(applyAudiobookSceneProgress(
      buildTask(),
      buildEvent({ audiobook_project_id: 99 }),
    )).toBeNull()
    expect(applyAudiobookSceneProgress(
      buildTask(),
      buildEvent({ chapter_id: 99 }),
    )).toBeNull()
    expect(applyAudiobookSceneProgress(
      buildTask(),
      buildEvent({ stage: 'tts_synthesis' }),
    )).toBeNull()
    expect(applyAudiobookSceneProgress(
      buildTask({ status: 'completed' }),
      buildEvent(),
    )).toBeNull()
  })

  it('允许没有固定 chapter_id 的批量任务接收当前章节场景进度', () => {
    const updated = applyAudiobookSceneProgress(
      buildTask({ chapter_id: null }),
      buildEvent({ chapter_id: 99 }),
    )

    expect(updated?.stages.scene_rendering.progress).toBe(0.5)
  })
})
