import type {
  NotificationData,
  TaskCompleteData,
  TaskErrorData,
  TaskProgressData,
} from '@/services/websocket'
import type { StoryExpansionResult } from '@/types/storyExpansion'
import { coerceStoryExpansionResult } from './storyExpansionStorage'

interface SystemCollectionsCreatedPayload {
  collections?: Array<{ name?: string | null }>
}

export function isStoryExpansionTaskId(taskId: unknown): taskId is string {
  return typeof taskId === 'string' && taskId.startsWith('expand-story')
}

export function getStoryExpansionResultFromTaskComplete(
  data: TaskCompleteData,
): StoryExpansionResult | null {
  if (!isStoryExpansionTaskId(data.task_id)) {
    return null
  }
  return coerceStoryExpansionResult(data.result)
}

export function isStoryExpansionTaskProgress(data: TaskProgressData): boolean {
  return isStoryExpansionTaskId(data.task_id)
}

export function isStoryExpansionTaskError(data: TaskErrorData): boolean {
  return isStoryExpansionTaskId(data.task_id)
}

export function extractSystemCollectionsCreatedNames(data: NotificationData): string[] {
  if (data.type !== 'system_collections_created') {
    return []
  }

  const payload = data.data
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return []
  }

  const collections = (payload as SystemCollectionsCreatedPayload).collections
  if (!Array.isArray(collections)) {
    return []
  }

  return collections
    .map((collection) => (typeof collection?.name === 'string' ? collection.name.trim() : ''))
    .filter((name) => name.length > 0)
}
