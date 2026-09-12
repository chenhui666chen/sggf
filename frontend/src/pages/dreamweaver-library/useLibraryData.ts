import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import { parseLibraryRole } from '@/utils/dreamweaverLibraryRole'
import { buildDreamWeaverLibraryAssetMetadataContract } from '@/contracts/userAssetMetadataBuilders'
import { buildDreamWeaverLibrarySourcePayload } from '@/contracts/userAssetSourcePayloadBuilders'
import type {
  LibraryAsset,
  LibraryPayload,
  CollectState,
} from './libraryPageUtils'
import { buildProtectedLibraryAssetUrl, getLibraryAssetDisplayTitle } from './libraryPageUtils'

export interface UseLibraryDataParams {
  projectId: number
}

export interface UseLibraryDataReturn {
  library: LibraryPayload | null
  loading: boolean
  error: string | null
  setError: (msg: string | null) => void
  lockedConfig: any
  previews: Record<number, string>
  previewAspectRatios: Record<number, string>
  setPreviewAspectRatios: React.Dispatch<React.SetStateAction<Record<number, string>>>
  assets: LibraryAsset[]
  assetsByRole: Map<string, LibraryAsset>
  characterNameById: Map<number, string>
  missingRoleSet: Set<string>
  approvedCount: number
  missingCount: number
  unapprovedCount: number
  collectStates: Record<number, CollectState>
  loadLibrary: () => Promise<void>
  loadLibraryRef: React.MutableRefObject<() => Promise<void>>
  approveLibraryRole: (role: string, approved: boolean) => Promise<void>
  uploadLibraryAsset: (assetId: number, file: File) => Promise<void>
  collectLibraryAsset: (asset: LibraryAsset) => Promise<void>
}

export function useLibraryData(params: UseLibraryDataParams): UseLibraryDataReturn {
  const { t } = useTranslation()
  const { projectId } = params

  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const setErrorRef = useRef<(msg: string | null) => void>(setError)
  setErrorRef.current = setError
  const [lockedConfig, setLockedConfig] = useState<any>(null)
  const [previews, setPreviews] = useState<Record<number, string>>({})
  const [previewAspectRatios, setPreviewAspectRatios] = useState<Record<number, string>>({})
  const previewUrlsRef = useRef<Set<string>>(new Set())
  const [collectStates, setCollectStates] = useState<Record<number, CollectState>>({})

  const loadLibrary = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    setLibrary(null)
    setLockedConfig(null)
    previewUrlsRef.current.forEach((url) => {
      try { URL.revokeObjectURL(url) } catch { /* ignore */ }
    })
    previewUrlsRef.current.clear()
    setPreviews({})
    setPreviewAspectRatios({})
    try {
      const res = await apiClient.getDreamweaverLibrary(projectId)
      const data = (res.data as LibraryPayload) || null
      setLibrary(data)

      try {
        const lockedRes = await apiClient.getDreamweaverProjectLockedConfig(projectId)
        setLockedConfig(lockedRes.data || null)
      } catch {
        setLockedConfig(null)
      }

      const assets = Array.isArray(data?.assets) ? data.assets : []
      const missingRoles = Array.isArray(data?.review?.missing_roles) ? (data!.review!.missing_roles as string[]) : []
      const missingRoleSet = new Set(missingRoles.map((r) => String(r || '').trim()).filter((r) => r))
      const previewEntries = await Promise.all(
        assets
          .filter((asset) => hasRenderableLibraryImage(asset, { missingRoleSet }))
          .map(async (asset) => {
            try {
              const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
              const url = URL.createObjectURL(fileRes.data)
              previewUrlsRef.current.add(url)
              return [asset.id, url] as const
            } catch {
              return [asset.id, ''] as const
            }
          }),
      )
      const previewMap: Record<number, string> = {}
      for (const [assetId, url] of previewEntries) {
        if (url) previewMap[assetId] = url
      }
      setPreviews(previewMap)
    } catch (e: any) {
      setError(await extractApiErrorMessage(e, t('dreamweaverRun.errorLoadLibraryFailed')))
    } finally {
      setLoading(false)
    }
  }, [projectId, t])
  const loadLibraryRef = useRef<() => Promise<void>>(loadLibrary)
  loadLibraryRef.current = loadLibrary

  useEffect(() => {
    void loadLibrary()
  }, [loadLibrary])

  useEffect(() => {
    return () => {
      previewUrlsRef.current.forEach((url) => {
        try { URL.revokeObjectURL(url) } catch { /* ignore */ }
      })
      previewUrlsRef.current.clear()
    }
  }, [])

  const assets = useMemo(() => Array.isArray(library?.assets) ? library!.assets : [], [library])

  const assetsByRole = useMemo(() => {
    const map = new Map<string, LibraryAsset>()
    for (const asset of assets) {
      const role = String(asset?.role || '').trim()
      if (!role) continue
      map.set(role, asset)
    }
    return map
  }, [assets])

  const characterNameById = useMemo(() => {
    const map = new Map<number, string>()
    const remember = (entityIdRaw: unknown, nameRaw: unknown) => {
      const entityId = Number.parseInt(String(entityIdRaw ?? ''), 10)
      const name = String(nameRaw || '').trim()
      if (!Number.isFinite(entityId) || entityId <= 0) return
      if (!name || /^[?\s]+$/.test(name)) return
      const lowered = name.toLowerCase()
      if (lowered === 'unknown' || lowered === 'n/a' || lowered === 'na') return
      if (name === '未知' || name === '未命名' || name === '角色' || name === '人物' || name === '角色名') return
      if (name.startsWith('lib_')) return
      if (!map.has(entityId)) map.set(entityId, name)
    }
    const specCharacters = Array.isArray(library?.spec?.characters) ? (library!.spec!.characters as any[]) : []
    for (const item of specCharacters) {
      remember(item?.entity_id, item?.name)
    }
    for (const asset of assets) {
      const parsed = parseLibraryRole(String(asset?.role || '').trim())
      if (parsed.entityType !== 'character' || !parsed.entityId) continue
      remember(parsed.entityId, asset?.meta?.entity_name)
    }
    return map
  }, [assets, library?.spec])

  const missingRoleSet = useMemo(() => {
    const roles = Array.isArray(library?.review?.missing_roles) ? (library!.review!.missing_roles as string[]) : []
    return new Set(roles.map((r) => String(r || '').trim()).filter((r) => r))
  }, [library])

  const approvedCount = useMemo(() => assets.filter((a) => Boolean(a?.meta?.approved)).length, [assets])
  const missingCount = Array.isArray(library?.review?.missing_roles) ? library!.review!.missing_roles.length : 0
  const unapprovedCount = Array.isArray(library?.review?.unapproved_roles) ? library!.review!.unapproved_roles.length : 0

  const approveLibraryRole = useCallback(
    async (role: string, approved: boolean) => {
      const safeRole = String(role || '').trim()
      if (!projectId || !safeRole) return
      setLoading(true)
      setError(null)
      try {
        await apiClient.approveDreamweaverLibrary(projectId, { roles: [safeRole], approved })
        await loadLibrary()
      } catch (e: any) {
        setError(await extractApiErrorMessage(e, t('dreamweaverRun.errorUpdateApprovalFailed')))
      } finally {
        setLoading(false)
      }
    },
    [loadLibrary, projectId, t],
  )

  const uploadLibraryAsset = useCallback(
    async (assetId: number, file: File) => {
      if (!projectId) return
      if (!file) return
      if (!String(file.name || '').toLowerCase().endsWith('.png')) {
        setError(t('dreamweaverRun.errorOnlyPngGeneric'))
        return
      }
      const maxMb = 10
      if (typeof file.size === 'number' && file.size > maxMb * 1024 * 1024) {
        setError(t('dreamweaverRun.errorFileTooLarge', { maxMb }))
        return
      }
      setLoading(true)
      setError(null)
      try {
        await apiClient.uploadDreamweaverLibraryAssetFile(assetId, file)
        await loadLibrary()
      } catch (e: any) {
        setError(await extractApiErrorMessage(e, t('dreamweaverRun.errorUploadFailed')))
      } finally {
        setLoading(false)
      }
    },
    [loadLibrary, projectId, t],
  )

  const updateCollectState = useCallback((assetId: number, patch: Partial<CollectState>) => {
    setCollectStates((prev) => ({
      ...prev,
      [assetId]: {
        ...prev[assetId],
        loading: false,
        feedback: null,
        ...patch,
      },
    }))
  }, [])

  const collectLibraryAsset = useCallback(
    async (asset: LibraryAsset) => {
      const assetId = Number(asset?.id || 0)
      if (!projectId || !assetId) return

      const parsed = parseLibraryRole(asset.role)
      const displayTitle = getLibraryAssetDisplayTitle(asset, characterNameById)
      const descriptor = String(asset?.meta?.descriptor || '').trim()
      const promptPreview = String(asset?.meta?.prompt || asset?.meta?.suggested_prompt || '').trim()
      const approved = Boolean(asset?.meta?.approved)
      const tags = ['dreamweaver', 'library', parsed.entityType || 'other']
      if (parsed.view) tags.push(parsed.view)
      if (approved) tags.push('approved')

      updateCollectState(assetId, { loading: true, feedback: null })

      try {
        await apiClient.createUserAsset({
          project_id: projectId,
          source_module: 'dreamweaver_library',
          asset_kind: 'image',
          asset_class: 'reusable',
          asset_uuid: `dreamweaver-library-${assetId}`,
          storage_mode: 'durable_cloud',
          title: displayTitle,
          description: descriptor || promptPreview || null,
          source_uri: buildProtectedLibraryAssetUrl(assetId),
          preview_uri: buildProtectedLibraryAssetUrl(assetId),
          download_uri: buildProtectedLibraryAssetUrl(assetId),
          model_id: String(asset?.meta?.model_id || asset?.meta?.model || asset?.meta?.image_model || '').trim() || null,
          generation_mode: 'library_asset',
          tags,
          metadata_json: buildDreamWeaverLibraryAssetMetadataContract({
            baseMetadata: asset.meta,
            projectId,
            libraryAssetId: assetId,
            libraryRole: asset.role,
            libraryUri: asset.uri,
            entityType: parsed.entityType,
            entityId: parsed.entityId ?? null,
            view: parsed.view ?? null,
            approved,
          }),
          source_payload_json: buildDreamWeaverLibrarySourcePayload({
            projectId,
            assetId,
            role: asset.role,
            uri: asset.uri,
            entityType: parsed.entityType,
            entityId: parsed.entityId ?? null,
            view: parsed.view ?? null,
            approved,
          }),
        })
        updateCollectState(assetId, {
          loading: false,
          feedback: { type: 'success', text: t('dreamweaverRun.libraryCollectAdded') },
        })
      } catch (collectError) {
        updateCollectState(assetId, {
          loading: false,
          feedback: {
            type: 'error',
            text: await extractApiErrorMessage(collectError, t('dreamweaverRun.libraryCollectFailed')),
          },
        })
      }
    },
    [characterNameById, projectId, updateCollectState, t],
  )

  return {
    library,
    loading,
    error,
    setError,
    lockedConfig,
    previews,
    previewAspectRatios,
    setPreviewAspectRatios,
    assets,
    assetsByRole,
    characterNameById,
    missingRoleSet,
    approvedCount,
    missingCount,
    unapprovedCount,
    collectStates,
    loadLibrary,
    loadLibraryRef,
    approveLibraryRole,
    uploadLibraryAsset,
    collectLibraryAsset,
  }
}
