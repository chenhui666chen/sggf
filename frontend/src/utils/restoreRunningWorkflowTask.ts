export const GENERATE_NEXT_CHAPTER_TASK_TYPE = 'generate_next_chapter'

export const WORKFLOW_STAGE_TYPES = [
  'concept',
  'structure',
  'content',
  'review',
  'iteration',
] as const

export type RestorableWorkflowStage = (typeof WORKFLOW_STAGE_TYPES)[number]

export interface WorkflowRunningTaskLike {
  task_id?: string
  task_type?: string
  age_minutes?: number
  chapter_number?: number | null
}

export interface RestoredGenerateNextChapterTask {
  kind: 'generate_next_chapter'
  taskId: string
  chapterNumber: number | null
  ageMinutes: number
}

export interface RestoredWorkflowStageTask {
  kind: 'workflow_stage'
  taskId: string
  stageType: RestorableWorkflowStage
  ageMinutes: number
}

export type RestoredRunningTask =
  | RestoredGenerateNextChapterTask
  | RestoredWorkflowStageTask

function asTaskId(value: unknown): string {
  return String(value || '').trim()
}

function asAgeMinutes(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function asChapterNumber(value: unknown): number | null {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null
  }
  return Math.trunc(numeric)
}

export function resolveRestoredRunningTask(
  task: WorkflowRunningTaskLike | null | undefined,
): RestoredRunningTask | null {
  if (!task) {
    return null
  }

  const taskId = asTaskId(task.task_id)
  if (!taskId) {
    return null
  }

  const taskType = String(task.task_type || '').trim()
  const ageMinutes = asAgeMinutes(task.age_minutes)

  if (taskType === GENERATE_NEXT_CHAPTER_TASK_TYPE) {
    return {
      kind: 'generate_next_chapter',
      taskId,
      chapterNumber: asChapterNumber(task.chapter_number),
      ageMinutes,
    }
  }

  const stageName = taskType.replace('workflow_stage_', '')
  if ((WORKFLOW_STAGE_TYPES as readonly string[]).includes(stageName)) {
    return {
      kind: 'workflow_stage',
      taskId,
      stageType: stageName as RestorableWorkflowStage,
      ageMinutes,
    }
  }

  return null
}