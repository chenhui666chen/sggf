import type { UserAssetRecord } from '@/services/api'

import type { UserAssetMetadata } from './userAssetLocalStorageContract'
import type { UserAssetSourcePayload } from './userAssetSourcePayloadBuilders'

type AssetSourceLike = Pick<UserAssetRecord, 'project_id' | 'source_payload_json' | 'metadata_json'>

function isObjectValue(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toSourcePayload(value: unknown): UserAssetSourcePayload {
  return isObjectValue(value) ? { ...value } : {}
}

function toMetadata(value: unknown): UserAssetMetadata {
  return (isObjectValue(value) ? { ...value } : {}) as UserAssetMetadata
}

function readTrimmedString(...values: unknown[]): string | null {
  for (const value of values) {
    const normalized = String(value ?? '').trim()
    if (normalized) {
      return normalized
    }
  }
  return null
}

function readPositiveInt(...values: unknown[]): number | null {
  for (const value of values) {
    const parsed = Number.parseInt(String(value ?? ''), 10)
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed
    }
  }
  return null
}

export function getUserAssetSourcePayload(asset: Pick<UserAssetRecord, 'source_payload_json'>): UserAssetSourcePayload {
  return toSourcePayload(asset.source_payload_json)
}

export function getUserAssetMetadataPayload(asset: Pick<UserAssetRecord, 'metadata_json'>): UserAssetMetadata {
  return toMetadata(asset.metadata_json)
}

export function extractUserAssetProjectId(asset: AssetSourceLike): number | null {
  return readPositiveInt(asset.project_id, getUserAssetSourcePayload(asset).project_id, getUserAssetMetadataPayload(asset).project_id)
}

export function extractDreamweaverLibraryAssetId(asset: Pick<UserAssetRecord, 'source_payload_json' | 'metadata_json'>): number | null {
  return readPositiveInt(
    getUserAssetSourcePayload(asset).asset_id,
    getUserAssetMetadataPayload(asset).library_asset_id,
  )
}

export function extractDreamweaverMergedRunId(asset: Pick<UserAssetRecord, 'source_payload_json' | 'metadata_json'>): string | null {
  return readTrimmedString(getUserAssetSourcePayload(asset).run_id, getUserAssetMetadataPayload(asset).run_id)
}

export function extractDreamweaverLibraryTraceInfo(
  asset: Pick<UserAssetRecord, 'source_payload_json' | 'metadata_json'>,
): { entityType: string | null; view: string | null } {
  return {
    entityType: readTrimmedString(
      getUserAssetMetadataPayload(asset).entity_type,
      getUserAssetSourcePayload(asset).entity_type,
    ),
    view: readTrimmedString(getUserAssetMetadataPayload(asset).view, getUserAssetSourcePayload(asset).view),
  }
}

export function extractAudiobookChapterTraceInfo(
  asset: Pick<UserAssetRecord, 'source_payload_json' | 'metadata_json'>,
): { audiobookProjectId: number | null; chapterId: number | null; chapterNumber: number | null; chapterTitle: string | null } {
  return {
    audiobookProjectId: readPositiveInt(
      getUserAssetSourcePayload(asset).audiobook_project_id,
      getUserAssetMetadataPayload(asset).audiobook_project_id,
    ),
    chapterId: readPositiveInt(
      getUserAssetSourcePayload(asset).chapter_id,
      getUserAssetMetadataPayload(asset).chapter_id,
    ),
    chapterNumber: readPositiveInt(
      getUserAssetSourcePayload(asset).chapter_number,
      getUserAssetMetadataPayload(asset).chapter_number,
    ),
    chapterTitle: readTrimmedString(
      getUserAssetSourcePayload(asset).chapter_title,
      getUserAssetMetadataPayload(asset).chapter_title,
    ),
  }
}

export function extractAudiobookChapterAssetRef(
  asset: Pick<UserAssetRecord, 'source_payload_json' | 'metadata_json'>,
): { audiobookProjectId: number; chapterId: number } | null {
  const traceInfo = extractAudiobookChapterTraceInfo(asset)
  if (!traceInfo.audiobookProjectId || !traceInfo.chapterId) {
    return null
  }

  return {
    audiobookProjectId: traceInfo.audiobookProjectId,
    chapterId: traceInfo.chapterId,
  }
}
