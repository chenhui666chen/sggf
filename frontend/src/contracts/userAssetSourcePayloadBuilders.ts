import type { AssetStudioMediaAsset } from '@/services/api'

import type { UserAssetMetadata } from './userAssetLocalStorageContract'

export type UserAssetSourcePayload = Record<string, unknown>

const USER_ASSET_LOCAL_STORAGE_METADATA_FIELDS = new Set([
  'local_storage_driver',
  'local_storage_path',
  'local_persist_level',
  'external_relative_path',
])

function isObjectPayloadPart(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function buildSourcePayloadBusinessMetadata(
  metadata: UserAssetMetadata | null | undefined,
): UserAssetSourcePayload {
  if (!isObjectPayloadPart(metadata)) {
    return {}
  }

  const sanitized: UserAssetSourcePayload = {}

  for (const [key, value] of Object.entries(metadata)) {
    if (USER_ASSET_LOCAL_STORAGE_METADATA_FIELDS.has(key)) {
      continue
    }
    sanitized[key] = value
  }

  return sanitized
}

export function buildUserAssetSourcePayload(
  ...parts: Array<UserAssetSourcePayload | UserAssetMetadata | null | undefined>
): UserAssetSourcePayload {
  const merged: UserAssetSourcePayload = {}

  for (const part of parts) {
    if (!isObjectPayloadPart(part)) {
      continue
    }
    Object.assign(merged, part)
  }

  return merged
}

export interface AssetStudioCollectedSourcePayloadInput {
  kind?: string | null
  mode?: string | null
  modelId?: string | null
  assets?: AssetStudioMediaAsset[] | null
  primaryAsset?: AssetStudioMediaAsset | null
  metadata?: Record<string, unknown> | null
}

export interface AssetStudioCollectedSourcePayload extends UserAssetSourcePayload {
  kind: string | null
  mode: string | null
  model_id: string | null
  assets: AssetStudioMediaAsset[]
  primary_asset: AssetStudioMediaAsset | null
  metadata: Record<string, unknown>
}

export function buildAssetStudioCollectedSourcePayload(
  input: AssetStudioCollectedSourcePayloadInput,
): AssetStudioCollectedSourcePayload {
  return buildUserAssetSourcePayload({
    kind: input.kind ?? null,
    mode: input.mode ?? null,
    model_id: input.modelId ?? null,
    assets: input.assets || [],
    primary_asset: input.primaryAsset ?? null,
    metadata: input.metadata || {},
  }) as AssetStudioCollectedSourcePayload
}

export interface AudiobookChapterAudioSourcePayload extends UserAssetSourcePayload {
  type: 'chapter_audio'
}

export function buildAudiobookChapterAudioSourcePayload(
  assetMetadata: UserAssetMetadata | null | undefined,
): AudiobookChapterAudioSourcePayload {
  return buildUserAssetSourcePayload(buildSourcePayloadBusinessMetadata(assetMetadata), {
    type: 'chapter_audio',
  }) as AudiobookChapterAudioSourcePayload
}

export interface DreamWeaverLibrarySourcePayloadInput {
  projectId: number
  assetId: string | number
  role?: string | null
  uri?: string | null
  entityType?: string | null
  entityId?: string | number | null
  view?: string | null
  approved: boolean
}

export interface DreamWeaverLibrarySourcePayload extends UserAssetSourcePayload {
  project_id: number
  asset_id: string | number
  role: string | null
  uri: string | null
  entity_type: string | null
  entity_id: string | number | null
  view: string | null
  approved: boolean
}

export function buildDreamWeaverLibrarySourcePayload(
  input: DreamWeaverLibrarySourcePayloadInput,
): DreamWeaverLibrarySourcePayload {
  return buildUserAssetSourcePayload({
    project_id: input.projectId,
    asset_id: input.assetId,
    role: input.role ?? null,
    uri: input.uri ?? null,
    entity_type: input.entityType ?? null,
    entity_id: input.entityId ?? null,
    view: input.view ?? null,
    approved: input.approved,
  }) as DreamWeaverLibrarySourcePayload
}

export interface DreamWeaverMergedVideoSourcePayloadInput {
  runId: string
  projectId: number | null
  path?: string | null
}

export interface DreamWeaverMergedVideoSourcePayload extends UserAssetSourcePayload {
  run_id: string
  project_id: number | null
  type: 'merged_video'
  path: string | null
}

export function buildDreamWeaverMergedVideoSourcePayload(
  input: DreamWeaverMergedVideoSourcePayloadInput,
): DreamWeaverMergedVideoSourcePayload {
  return buildUserAssetSourcePayload({
    run_id: input.runId,
    project_id: input.projectId ?? null,
    type: 'merged_video',
    path: input.path ?? null,
  }) as DreamWeaverMergedVideoSourcePayload
}
