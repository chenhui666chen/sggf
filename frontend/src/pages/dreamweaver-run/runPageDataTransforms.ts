import type {
  Chapter,
  DreamweaverEventRecord,
  DreamweaverProjectLockedGenerationConfig,
  DreamweaverRunAsyncResponse,
  DreamweaverRunSnapshot,
  DreamweaverRunSummary,
  DreamweaverScriptEntities,
  DreamweaverShotFrame,
  DreamweaverShotSnapshot,
  DreamweaverVideoClipJob,
  LibraryPayload,
  TaskStatus,
} from '@/types/dreamweaver'
import type { TranslateFn } from '@/pages/audiobook/audioLibraryDisplay'

export function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

export function toDreamweaverScriptEntities(value: unknown): DreamweaverScriptEntities | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const toBucket = (bucket: unknown): DreamweaverScriptEntities['characters'] => {
    if (!Array.isArray(bucket)) return []
    return bucket.filter(
      (item): item is DreamweaverScriptEntities['characters'][number] =>
        Boolean(item) && typeof item === 'object' && !Array.isArray(item),
    )
  }
  return {
    characters: toBucket(record.characters),
    scenes: toBucket(record.scenes),
    props: toBucket(record.props),
  }
}

export function summarizeScriptEntities(entities: DreamweaverScriptEntities | null, t?: TranslateFn): string {
  if (!entities) return ''
  return t
    ? t('dreamweaverRun.scriptEntitiesSummary', {
      characters: entities.characters.length,
      scenes: entities.scenes.length,
      props: entities.props.length,
    })
    : `角色 ${entities.characters.length}，场景 ${entities.scenes.length}，道具 ${entities.props.length}`
}

export function toDreamweaverShotSnapshots(value: unknown): DreamweaverShotSnapshot[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverShotSnapshot => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

export function toDreamweaverVideoClipJobs(value: unknown): DreamweaverVideoClipJob[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverVideoClipJob => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

export function toDreamweaverRunSummaries(value: unknown): DreamweaverRunSummary[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverRunSummary => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

export function toDreamweaverRunSnapshot(value: unknown): DreamweaverRunSnapshot | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverRunSnapshot
}

export function toDreamweaverTaskStatus(value: unknown): TaskStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as TaskStatus
}

export function toDreamweaverRunAsyncResponse(value: unknown): DreamweaverRunAsyncResponse | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverRunAsyncResponse
}

export function toDreamweaverProjectLockedGenerationConfig(value: unknown): DreamweaverProjectLockedGenerationConfig | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as DreamweaverProjectLockedGenerationConfig
}

export function toDreamweaverEventRecords(value: unknown): DreamweaverEventRecord[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverEventRecord => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

export function toChapters(value: unknown): Chapter[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Chapter => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
}

export function toLibraryPayload(value: unknown): LibraryPayload | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as LibraryPayload
}

export function toDreamweaverQueuedTaskResponse(
  value: unknown,
): { task_id: string; run_id: string; status: string } | null {
  const record = asObject(value)
  if (!record) return null
  const task_id = typeof record.task_id === 'string' ? record.task_id.trim() : ''
  const run_id = typeof record.run_id === 'string' ? record.run_id.trim() : ''
  const status = typeof record.status === 'string' ? record.status.trim() : ''
  if (!task_id || !run_id) return null
  return { task_id, run_id, status }
}

export function toDreamweaverShotFrames(value: unknown): DreamweaverShotFrame[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is DreamweaverShotFrame => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
  )
}

export function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)
}
