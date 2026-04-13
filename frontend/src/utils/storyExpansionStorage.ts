import type { StoryExpansionResult } from '@/types/storyExpansion'
import { coerceStoryExpansionResult } from './storyExpansionResultModel'

export { coerceStoryExpansionResult }

interface StoryExpansionStorageKeys {
  taskState: string
  taskStartedAt: string
  taskId: string
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

export function getStoryExpansionStorageKeys(projectId: string | number): StoryExpansionStorageKeys {
  const normalizedProjectId = String(projectId).trim()

  return {
    taskState: `expanding_story_${normalizedProjectId}`,
    taskStartedAt: `expanding_story_start_${normalizedProjectId}`,
    taskId: `expanding_story_task_${normalizedProjectId}`,
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
