import type { AudiobookProgressData } from '../../services/websocket'
import type { StageInfo, TaskStatus } from './types'

export type { AudiobookProgressData } from '../../services/websocket'

const TERMINAL_TASK_STATUSES = new Set(['completed', 'failed'])

export const applyAudiobookSceneProgress = (
  task: TaskStatus | null | undefined,
  event: AudiobookProgressData | null | undefined,
): TaskStatus | null => {
  if (
    !task
    || !event
    || event.stage !== 'scene_rendering'
    || task.audiobook_project_id !== event.audiobook_project_id
    || TERMINAL_TASK_STATUSES.has(task.status)
  ) {
    return null
  }
  if (task.chapter_id != null && task.chapter_id !== event.chapter_id) {
    return null
  }

  const rawProgress = Number(event.progress)
  if (!Number.isFinite(rawProgress)) {
    return null
  }

  const previousProgress = task.stages.scene_rendering?.progress || 0
  const normalizedProgress = Math.max(
    previousProgress,
    Math.max(0, Math.min(rawProgress, 100)) / 100,
  )
  const sceneStage: StageInfo = {
    status: normalizedProgress >= 1 ? 'completed' : 'running',
    progress: normalizedProgress,
  }
  if (event.message) {
    sceneStage.message = event.message
  }
  if (event.stage_metrics && typeof event.stage_metrics === 'object') {
    sceneStage.metrics = event.stage_metrics
  }

  return {
    ...task,
    status: task.status === 'pending' ? 'running' : task.status,
    current_stage: 'scene_rendering',
    stages: {
      ...task.stages,
      scene_rendering: sceneStage,
    },
  }
}
