import { getUserAssetMetadataPayload } from '@/contracts/userAssetSourcePayloadSelectors'
import {
  fetchUserAssetSourceBlob,
  type UserAssetSourceBlobLoaders,
} from '@/contracts/userAssetPreviewResolvers'
import type {
  UserAssetLocalStorageDriver,
  UserAssetMetadata,
} from '@/types/userAsset'
import {
  apiClient,
  type UserAssetRecord,
} from '@/services/api'
import {
  getLocalAssetExternalDirectoryStatus,
  type LocalAssetExternalDirectoryStatus,
} from './localAssetExternalDirectory'
import {
  deleteLocalAsset,
  getLocalAssetBlob,
  saveLocalAsset,
  type ExplicitPreferredLocalAssetStorageDriver,
  type LocalAssetVaultRecord,
  type SaveLocalAssetInput,
} from './localAssetVault'

type UserAssetLocalRecoveryReadable = Pick<
  UserAssetRecord,
  | 'asset_uuid'
  | 'asset_kind'
  | 'title'
  | 'source_module'
  | 'source_uri'
  | 'preview_uri'
  | 'download_uri'
  | 'mime_type'
  | 'file_size'
  | 'storage_mode'
  | 'metadata_json'
>

type RestoreBlockedReason =
  | 'missing_source'
  | 'external_directory_unavailable'
  | 'storage_driver_mismatch'

export type RestoreUserAssetLocalCopyResult =
  | {
      status: 'restored'
      storageDriver: UserAssetLocalStorageDriver
      localAssetRecord: LocalAssetVaultRecord
    }
  | {
      status: 'already_present'
    }
  | {
      status: 'blocked'
      reason: RestoreBlockedReason
      message: string
    }

type RestoreUserAssetLocalCopyDependencies = {
  fetchSourceBlob: (asset: UserAssetLocalRecoveryReadable) => Promise<Blob>
  getExistingLocalBlob: (assetUuid: string) => Promise<Blob | null>
  saveAsset: (input: SaveLocalAssetInput) => Promise<LocalAssetVaultRecord>
  deleteAsset: (assetUuid: string) => Promise<boolean>
  getExternalDirectoryStatus: () => Promise<LocalAssetExternalDirectoryStatus>
}

const DEFAULT_SOURCE_BLOB_LOADERS: UserAssetSourceBlobLoaders = {
  fetchDreamweaverLibraryAssetFile: async (assetId) => (await apiClient.getDreamweaverLibraryAssetFile(assetId)).data,
  fetchDreamweaverMergedVideoFile: async (runId) => (await apiClient.getDreamweaverMergedVideoFile(runId)).data,
  fetchAudiobookChapterAudioFile: async (audiobookProjectId, chapterId) =>
    (await apiClient.getAudiobookChapterAudioFile(audiobookProjectId, chapterId)).data,
  fetchRemoteUserAssetBlob: async (url) => (await apiClient.get(url, { responseType: 'blob' })).data,
}

const DEFAULT_DEPENDENCIES: RestoreUserAssetLocalCopyDependencies = {
  fetchSourceBlob: (asset) => fetchUserAssetSourceBlob(asset, DEFAULT_SOURCE_BLOB_LOADERS),
  getExistingLocalBlob: getLocalAssetBlob,
  saveAsset: saveLocalAsset,
  deleteAsset: deleteLocalAsset,
  getExternalDirectoryStatus: getLocalAssetExternalDirectoryStatus,
}

function readTrimmedString(value: string | null | undefined): string {
  return String(value || '').trim()
}

function resolveUserAssetMediaKind(asset: Pick<UserAssetRecord, 'asset_kind'>): string {
  const normalized = readTrimmedString(asset.asset_kind)
  return normalized || 'file'
}

function resolvePreferredStorageDriver(
  metadata: UserAssetMetadata,
): ExplicitPreferredLocalAssetStorageDriver | null {
  const driver = metadata.local_storage_driver ?? null
  if (driver === 'external_directory' || driver === 'opfs') {
    return driver
  }
  return null
}

function buildRestoreBlockedResult(
  reason: RestoreBlockedReason,
  message: string,
): RestoreUserAssetLocalCopyResult {
  return {
    status: 'blocked',
    reason,
    message,
  }
}

export function isUserAssetLocalRestoreEligible(
  asset: Pick<UserAssetRecord, 'asset_uuid' | 'storage_mode'>,
): boolean {
  return asset.storage_mode === 'local_mirror' && Boolean(readTrimmedString(asset.asset_uuid))
}

export async function restoreUserAssetLocalCopy(
  asset: UserAssetLocalRecoveryReadable,
  dependencies: Partial<RestoreUserAssetLocalCopyDependencies> = {},
): Promise<RestoreUserAssetLocalCopyResult> {
  const resolvedDependencies = {
    ...DEFAULT_DEPENDENCIES,
    ...dependencies,
  }
  const assetUuid = readTrimmedString(asset.asset_uuid)
  if (!assetUuid || asset.storage_mode !== 'local_mirror') {
    return buildRestoreBlockedResult('missing_source', '当前资产不支持重新收录到本地。')
  }

  const existingBlob = await resolvedDependencies.getExistingLocalBlob(assetUuid)
  if (existingBlob) {
    return { status: 'already_present' }
  }

  const metadata = getUserAssetMetadataPayload(asset)
  const preferredStorageDriver = resolvePreferredStorageDriver(metadata)

  if (preferredStorageDriver === 'external_directory') {
    const directoryStatus = await resolvedDependencies.getExternalDirectoryStatus()
    if (
      !directoryStatus.supported
      || !directoryStatus.configured
      || directoryStatus.permission !== 'granted'
    ) {
      return buildRestoreBlockedResult(
        'external_directory_unavailable',
        '用户目录当前不可用，请先恢复访问或重新选择目录后再重试。',
      )
    }
  }

  const sourceBlob = await resolvedDependencies.fetchSourceBlob(asset)
  const localAssetRecord = await resolvedDependencies.saveAsset({
    assetUuid,
    mediaKind: resolveUserAssetMediaKind(asset),
    blob: sourceBlob,
    mimeType: asset.mime_type ?? sourceBlob.type ?? null,
    fileSize: asset.file_size ?? sourceBlob.size ?? null,
    sourceModule: readTrimmedString(asset.source_module) || null,
    title: readTrimmedString(asset.title) || null,
    sourceUri: asset.source_uri ?? null,
    previewUri: asset.preview_uri ?? null,
    downloadUri: asset.download_uri ?? null,
    metadata,
    preferredStorageDriver,
  })

  if (preferredStorageDriver && localAssetRecord.storageDriver !== preferredStorageDriver) {
    await resolvedDependencies.deleteAsset(assetUuid)
    return buildRestoreBlockedResult(
      'storage_driver_mismatch',
      '目标本地存储当前不可稳定写入，请检查目录权限或浏览器本地存储状态后重试。',
    )
  }

  return {
    status: 'restored',
    storageDriver: localAssetRecord.storageDriver,
    localAssetRecord,
  }
}
