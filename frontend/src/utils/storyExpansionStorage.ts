import type {
  StoryExpansionTaskMeta,
  StoryExpansionResult,
} from '@/types/storyExpansion'
import { coerceStoryExpansionResult } from './storyExpansionResultModel'

export { coerceStoryExpansionResult }

interface StoryExpansionStorageKeys {
  taskState: string
  taskStartedAt: string
  taskId: string
  taskMeta: string
  result: string
}

const CURRENT_STORY_EXPANSION_RESULT_KEYS = [
  'expanded_outline',
  'all_characters',
  'outline_delta',
  'character_delta',
  'character_relationships',
  'outline_ops',
  'execution_mode',
  'execution_rounds',
  'new_characters',
  'alignment_repairs',
  'alignment_warnings',
  'coordination_summary',
  'current_chapter_count',
  'target_chapter_count',
  'current_character_count',
  'target_character_count',
  'completion_status',
  'goal_reached',
  'expansion_analysis',
  'message',
] as const

function hasCurrentStoryExpansionResultShape(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }

  return CURRENT_STORY_EXPANSION_RESULT_KEYS.some((key) =>
    Object.prototype.hasOwnProperty.call(value, key),
  )
}

function canUseLocalStorage(): boolean {
  return typeof localStorage !== 'undefined'
}

function normalizeStoryExpansionTaskMeta(
  value: unknown,
): StoryExpansionTaskMeta | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const record = value as Record<string, unknown>
  const minMinutes = typeof record.estimated_duration_minutes_min === 'number'
    && Number.isFinite(record.estimated_duration_minutes_min)
    ? Math.max(1, Math.trunc(record.estimated_duration_minutes_min))
    : null
  const maxMinutes = typeof record.estimated_duration_minutes_max === 'number'
    && Number.isFinite(record.estimated_duration_minutes_max)
    ? Math.max(1, Math.trunc(record.estimated_duration_minutes_max))
    : null
  const waitHint = typeof record.wait_hint === 'string' && record.wait_hint.trim()
    ? record.wait_hint.trim()
    : ''

  if (minMinutes == null && maxMinutes == null && !waitHint) {
    return null
  }

  const normalized: StoryExpansionTaskMeta = {}

  if (minMinutes != null && maxMinutes != null) {
    normalized.estimated_duration_minutes_min = Math.min(minMinutes, maxMinutes)
    normalized.estimated_duration_minutes_max = Math.max(minMinutes, maxMinutes)
  } else if (minMinutes != null || maxMinutes != null) {
    normalized.estimated_duration_minutes_min = minMinutes ?? maxMinutes
    normalized.estimated_duration_minutes_max = maxMinutes ?? minMinutes
  }

  if (waitHint) {
    normalized.wait_hint = waitHint
  }

  return normalized
}

export function getStoryExpansionStorageKeys(projectId: string | number): StoryExpansionStorageKeys {
  const normalizedProjectId = String(projectId).trim()

  return {
    taskState: `expanding_story_${normalizedProjectId}`,
    taskStartedAt: `expanding_story_start_${normalizedProjectId}`,
    taskId: `expanding_story_task_${normalizedProjectId}`,
    taskMeta: `expanding_story_meta_${normalizedProjectId}`,
    result: `story_expand_result_${normalizedProjectId}`,
  }
}

export function clearStoryExpansionTaskPersistence(projectId: string | number): void {
  if (!canUseLocalStorage()) {
    return
  }

  const keys = getStoryExpansionStorageKeys(projectId)
  localStorage.removeItem(keys.taskState)
  localStorage.removeItem(keys.taskStartedAt)
  localStorage.removeItem(keys.taskId)
  localStorage.removeItem(keys.taskMeta)
}

export function persistStoryExpansionTaskPersistence(
  projectId: string | number,
  taskId: string | null | undefined,
  startedAt = Date.now(),
): void {
  if (!canUseLocalStorage()) {
    return
  }

  const keys = getStoryExpansionStorageKeys(projectId)
  localStorage.setItem(keys.taskState, 'true')
  localStorage.setItem(keys.taskStartedAt, String(startedAt))

  if (taskId) {
    localStorage.setItem(keys.taskId, taskId)
    return
  }

  localStorage.removeItem(keys.taskId)
}

export function persistStoryExpansionTaskMeta(
  projectId: string | number,
  meta: StoryExpansionTaskMeta | null | undefined,
): void {
  if (!canUseLocalStorage()) {
    return
  }

  const keys = getStoryExpansionStorageKeys(projectId)
  const normalizedMeta = normalizeStoryExpansionTaskMeta(meta)

  if (!normalizedMeta) {
    localStorage.removeItem(keys.taskMeta)
    return
  }

  localStorage.setItem(keys.taskMeta, JSON.stringify(normalizedMeta))
}

export function parseStoredStoryExpansionTaskMeta(
  raw: string | null | undefined,
): StoryExpansionTaskMeta | null {
  if (typeof raw !== 'string' || !raw.trim()) {
    return null
  }

  try {
    return normalizeStoryExpansionTaskMeta(JSON.parse(raw) as unknown)
  } catch {
    return null
  }
}

export function storeStoryExpansionResult(
  projectId: string | number,
  result: StoryExpansionResult,
): void {
  if (!canUseLocalStorage()) {
    return
  }

  const keys = getStoryExpansionStorageKeys(projectId)
  localStorage.setItem(keys.result, JSON.stringify(result))
}

export function clearStoredStoryExpansionResult(projectId: string | number): void {
  if (!canUseLocalStorage()) {
    return
  }

  const keys = getStoryExpansionStorageKeys(projectId)
  localStorage.removeItem(keys.result)
}

export function parseStoredStoryExpansionResult(raw: string | null | undefined): StoryExpansionResult | null {
  if (typeof raw !== 'string' || !raw.trim()) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as unknown
    if (!hasCurrentStoryExpansionResultShape(parsed)) {
      return null
    }
    return coerceStoryExpansionResult(parsed)
  } catch {
    return null
  }
}
