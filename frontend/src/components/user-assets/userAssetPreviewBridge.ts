import type { UserAssetRecord } from '@/services/api'

export type UserAssetPreviewObjectUrlMaps = {
  localObjectUrls?: Record<number, string>
  protectedObjectUrls?: Record<number, string>
}

export type UserAssetCardPreviewBridge = {
  localObjectUrl: string | null
  protectedObjectUrl: string | null
}

function normalizeObjectUrl(value: string | null | undefined): string | null {
  const normalized = String(value || '').trim()
  return normalized || null
}

export function buildUserAssetCardPreviewBridge(
  asset: Pick<UserAssetRecord, 'id'>,
  objectUrls: UserAssetPreviewObjectUrlMaps = {},
): UserAssetCardPreviewBridge {
  return {
    localObjectUrl: normalizeObjectUrl(objectUrls.localObjectUrls?.[asset.id]),
    protectedObjectUrl: normalizeObjectUrl(objectUrls.protectedObjectUrls?.[asset.id]),
  }
}
