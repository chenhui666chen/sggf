import type { UserAssetRecord } from '@/services/api'

import {
  isProtectedUserAsset,
  getProtectedUserAssetRef,
  type ProtectedUserAssetRef,
} from './userAssetSourceReaders'

type UserAssetPreviewReadable = Pick<
  UserAssetRecord,
  'preview_uri' | 'source_uri' | 'download_uri' | 'source_module' | 'project_id' | 'source_payload_json' | 'metadata_json'
>

export type UserAssetProtectedFileLoaders = {
  fetchDreamweaverLibraryAssetFile: (assetId: number) => Promise<Blob>
  fetchDreamweaverMergedVideoFile: (runId: string) => Promise<Blob>
  fetchAudiobookChapterAudioFile: (audiobookProjectId: number, chapterId: number) => Promise<Blob>
}

export type UserAssetSourceBlobLoaders = UserAssetProtectedFileLoaders & {
  fetchRemoteUserAssetBlob: (url: string) => Promise<Blob>
}

export type ResolveUserAssetPreviewUrlOptions = {
  localObjectUrl?: string | null
  protectedObjectUrl?: string | null
}

function readTrimmedUrl(...values: Array<string | null | undefined>): string {
  for (const value of values) {
    const normalized = String(value || '').trim()
    if (normalized) {
      return normalized
    }
  }
  return ''
}

export function getUserAssetRemotePreviewUrl(
  asset: Pick<UserAssetRecord, 'preview_uri' | 'source_uri' | 'download_uri'>,
): string {
  return readTrimmedUrl(asset.preview_uri, asset.source_uri, asset.download_uri)
}

export async function fetchProtectedUserAssetBlob(
  ref: ProtectedUserAssetRef,
  loaders: UserAssetProtectedFileLoaders,
): Promise<Blob> {
  if (ref.kind === 'dreamweaver_library') {
    return loaders.fetchDreamweaverLibraryAssetFile(ref.libraryAssetId)
  }
  if (ref.kind === 'dreamweaver_run') {
    return loaders.fetchDreamweaverMergedVideoFile(ref.runId)
  }
  return loaders.fetchAudiobookChapterAudioFile(ref.audiobookProjectId, ref.chapterId)
}

export async function fetchUserAssetSourceBlob(
  asset: UserAssetPreviewReadable,
  loaders: UserAssetSourceBlobLoaders,
): Promise<Blob> {
  const protectedRef = getProtectedUserAssetRef(asset)
  if (protectedRef) {
    return fetchProtectedUserAssetBlob(protectedRef, loaders)
  }

  const remoteUrl = getUserAssetRemotePreviewUrl(asset)
  if (!remoteUrl) {
    throw new Error('当前资产缺少可下载的来源地址')
  }

  return loaders.fetchRemoteUserAssetBlob(remoteUrl)
}

export function resolveUserAssetPreviewUrl(
  asset: UserAssetPreviewReadable,
  options: ResolveUserAssetPreviewUrlOptions = {},
): string {
  const localObjectUrl = readTrimmedUrl(options.localObjectUrl)
  if (localObjectUrl) {
    return localObjectUrl
  }

  const protectedObjectUrl = readTrimmedUrl(options.protectedObjectUrl)
  if (protectedObjectUrl) {
    return protectedObjectUrl
  }

  if (isProtectedUserAsset(asset)) {
    return ''
  }

  return getUserAssetRemotePreviewUrl(asset)
}

export function isUserAssetPreviewPending(
  asset: UserAssetPreviewReadable,
  options: ResolveUserAssetPreviewUrlOptions = {},
): boolean {
  return isProtectedUserAsset(asset) && !resolveUserAssetPreviewUrl(asset, options)
}
