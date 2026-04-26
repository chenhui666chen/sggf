import {
  buildUserAssetMetadataContract,
  type UserAssetLocalStorageMetadata,
  type UserAssetMetadata,
} from './userAssetLocalStorageContract'

type UserAssetMetadataPart = Record<string, unknown> | UserAssetMetadata | null | undefined

export function buildLocalMirrorAssetMetadataContract(
  metadata: UserAssetMetadataPart,
  localStorageMetadata: UserAssetLocalStorageMetadata | UserAssetMetadataPart,
): UserAssetMetadata {
  return buildUserAssetMetadataContract(metadata, localStorageMetadata)
}

export function buildAssetStudioCollectedAssetMetadataContract(
  resultMetadata: UserAssetMetadataPart,
  localStorageMetadata: UserAssetLocalStorageMetadata | UserAssetMetadataPart,
): UserAssetMetadata {
  return buildLocalMirrorAssetMetadataContract(resultMetadata, localStorageMetadata)
}

export function buildAudiobookChapterAudioAssetMetadataContract(
  assetMetadata: UserAssetMetadataPart,
  localStorageMetadata: UserAssetLocalStorageMetadata | UserAssetMetadataPart,
): UserAssetMetadata {
  return buildLocalMirrorAssetMetadataContract(assetMetadata, localStorageMetadata)
}

export interface DreamWeaverLibraryAssetMetadataContractInput {
  baseMetadata?: UserAssetMetadataPart
  projectId: number
  libraryAssetId: string | number
  libraryRole?: string | null
  libraryUri?: string | null
  entityType?: string | null
  entityId?: string | number | null
  view?: string | null
  approved: boolean
}

export function buildDreamWeaverLibraryAssetMetadataContract(
  input: DreamWeaverLibraryAssetMetadataContractInput,
): UserAssetMetadata {
  return buildUserAssetMetadataContract(input.baseMetadata, {
    project_id: input.projectId,
    library_asset_id: input.libraryAssetId,
    library_role: input.libraryRole ?? null,
    library_uri: input.libraryUri ?? null,
    entity_type: input.entityType ?? null,
    entity_id: input.entityId ?? null,
    view: input.view ?? null,
    approved: input.approved,
  })
}

export interface DreamWeaverMergedVideoAssetMetadataContractInput {
  runId: string
  projectId: number | null
  projectTitle?: string | null
  mergedVideoPath?: string | null
}

export function buildDreamWeaverMergedVideoAssetMetadataContract(
  input: DreamWeaverMergedVideoAssetMetadataContractInput,
): UserAssetMetadata {
  return buildUserAssetMetadataContract({
    run_id: input.runId,
    project_id: input.projectId ?? null,
    project_title: input.projectTitle ?? null,
    merged_video_path: input.mergedVideoPath ?? null,
  })
}
