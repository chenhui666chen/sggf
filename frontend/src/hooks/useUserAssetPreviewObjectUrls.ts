import { useEffect, useMemo, useState } from 'react'

import {
  apiClient,
  type UserAssetRecord,
} from '@/services/api'
import {
  fetchProtectedUserAssetBlob,
  type UserAssetProtectedFileLoaders,
} from '@/contracts/userAssetPreviewResolvers'
import {
  getProtectedUserAssetRef,
  type ProtectedUserAssetRef,
} from '@/contracts/userAssetSourceReaders'
import { getLocalAssetBlob } from '@/utils/localAssetVault'

type UserAssetLocalPreviewReadable = Pick<UserAssetRecord, 'id' | 'asset_uuid'>

export type UserAssetLocalPreviewTarget = {
  assetId: number
  assetUuid: string
}

export type UserAssetProtectedPreviewTarget = { assetId: number } & ProtectedUserAssetRef

export type UseUserAssetPreviewObjectUrlsOptions = {
  assets: UserAssetRecord[]
  enabled?: boolean
  protectedFileLoaders?: UserAssetProtectedFileLoaders
}

export type UserAssetPreviewObjectUrlsState = {
  localObjectUrls: Record<number, string>
  localObjectUrlsReady: boolean
  protectedObjectUrls: Record<number, string>
}

const DEFAULT_PROTECTED_FILE_LOADERS: UserAssetProtectedFileLoaders = {
  fetchDreamweaverLibraryAssetFile: async (assetId) => (await apiClient.getDreamweaverLibraryAssetFile(assetId)).data,
  fetchDreamweaverMergedVideoFile: async (runId) => (await apiClient.getDreamweaverMergedVideoFile(runId)).data,
  fetchAudiobookChapterAudioFile: async (audiobookProjectId, chapterId) =>
    (await apiClient.getAudiobookChapterAudioFile(audiobookProjectId, chapterId)).data,
}

function revokeObjectUrls(urls: Iterable<string>) {
  for (const url of urls) {
    if (!url) continue
    try {
      URL.revokeObjectURL(url)
    } catch {
      // ignore
    }
  }
}

export function collectUserAssetLocalPreviewTargets(
  assets: UserAssetLocalPreviewReadable[],
): UserAssetLocalPreviewTarget[] {
  return assets
    .map((asset) => {
      const assetUuid = String(asset.asset_uuid || '').trim()
      if (!assetUuid) return null
      return { assetId: asset.id, assetUuid }
    })
    .filter(Boolean) as UserAssetLocalPreviewTarget[]
}

export function collectUserAssetProtectedPreviewTargets(
  assets: UserAssetRecord[],
  localObjectUrls: Record<number, string>,
): UserAssetProtectedPreviewTarget[] {
  return assets
    .map((asset) => {
      const protectedRef = getProtectedUserAssetRef(asset)
      if (!protectedRef) return null
      if (localObjectUrls[asset.id]) return null
      return { assetId: asset.id, ...protectedRef }
    })
    .filter(Boolean) as UserAssetProtectedPreviewTarget[]
}

export function useUserAssetPreviewObjectUrls(
  options: UseUserAssetPreviewObjectUrlsOptions,
): UserAssetPreviewObjectUrlsState {
  const { assets, enabled = true, protectedFileLoaders } = options
  const [localObjectUrls, setLocalObjectUrls] = useState<Record<number, string>>({})
  const [localObjectUrlsReady, setLocalObjectUrlsReady] = useState(false)
  const [protectedObjectUrls, setProtectedObjectUrls] = useState<Record<number, string>>({})

  const resolvedProtectedFileLoaders = useMemo(
    () => protectedFileLoaders || DEFAULT_PROTECTED_FILE_LOADERS,
    [protectedFileLoaders],
  )

  useEffect(() => {
    let revoked = false
    const objectUrls: string[] = []

    const loadLocalObjectUrls = async () => {
      if (!enabled) {
        setLocalObjectUrls({})
        setLocalObjectUrlsReady(false)
        return
      }

      setLocalObjectUrlsReady(false)
      const localTargets = collectUserAssetLocalPreviewTargets(assets)

      if (!localTargets.length) {
        setLocalObjectUrls({})
        setLocalObjectUrlsReady(true)
        return
      }

      const entries = await Promise.all(
        localTargets.map(async (item) => {
          try {
            const blob = await getLocalAssetBlob(item.assetUuid)
            if (!blob) return [item.assetId, ''] as const
            const objectUrl = URL.createObjectURL(blob)
            objectUrls.push(objectUrl)
            return [item.assetId, objectUrl] as const
          } catch {
            return [item.assetId, ''] as const
          }
        }),
      )

      if (revoked) return
      const nextUrls: Record<number, string> = {}
      entries.forEach(([assetId, url]) => {
        if (url) nextUrls[assetId] = url
      })
      setLocalObjectUrls(nextUrls)
      setLocalObjectUrlsReady(true)
    }

    void loadLocalObjectUrls()

    return () => {
      revoked = true
      revokeObjectUrls(objectUrls)
    }
  }, [assets, enabled])

  useEffect(() => {
    let revoked = false
    const objectUrls: string[] = []

    const loadProtectedObjectUrls = async () => {
      if (!enabled || !localObjectUrlsReady) {
        setProtectedObjectUrls({})
        return
      }

      const protectedTargets = collectUserAssetProtectedPreviewTargets(assets, localObjectUrls)
      if (!protectedTargets.length) {
        setProtectedObjectUrls({})
        return
      }

      const entries = await Promise.all(
        protectedTargets.map(async (item) => {
          try {
            const blob = await fetchProtectedUserAssetBlob(item, resolvedProtectedFileLoaders)
            const objectUrl = URL.createObjectURL(blob)
            objectUrls.push(objectUrl)
            return [item.assetId, objectUrl] as const
          } catch {
            return [item.assetId, ''] as const
          }
        }),
      )

      if (revoked) return
      const nextUrls: Record<number, string> = {}
      entries.forEach(([assetId, url]) => {
        if (url) nextUrls[assetId] = url
      })
      setProtectedObjectUrls(nextUrls)
    }

    void loadProtectedObjectUrls()

    return () => {
      revoked = true
      revokeObjectUrls(objectUrls)
    }
  }, [assets, enabled, localObjectUrls, localObjectUrlsReady, resolvedProtectedFileLoaders])

  return {
    localObjectUrls,
    localObjectUrlsReady,
    protectedObjectUrls,
  }
}
