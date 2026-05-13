import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import { buildLibraryPlanItemsFromPayload } from '@/utils/dreamweaver'
import { useDreamweaverAssetPreviews } from '@/hooks/useDreamweaverAssetPreviews'
import { buildMissingRoleSet, buildLibraryAssetsByRole } from '@/pages/dreamweaver-run/runPageLibraryHelpers'
import { extractMissingRoleSet, collectLibraryPreviewMaps } from '@/pages/dreamweaver-run/runPageCore'
import { toLibraryPayload } from '@/pages/dreamweaver-run/runPageDataTransforms'
import type {
  DreamweaverAssetPlanItem,
  DreamweaverLibraryPlanItem,
  LibraryAsset,
  LibraryPayload,
} from '@/types/dreamweaver'

export type RegenerateLibraryAssetFn = (params: Record<string, unknown>) => Promise<string | null>

interface UseDreamweaverRunPageLibraryDeps {
  selectedProjectId: number | null
  currentRunId: string | null
  libraryPlanItems: DreamweaverAssetPlanItem[]
  setLibraryPlanItems: (items: DreamweaverLibraryPlanItem[]) => void
}

export function useDreamweaverRunPageLibrary(deps: UseDreamweaverRunPageLibraryDeps) {
  const { selectedProjectId, currentRunId, libraryPlanItems, setLibraryPlanItems } = deps

  const [library, setLibrary] = useState<LibraryPayload | null>(null)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const autoLoadedLibraryRef = useRef(false)

  const {
    libraryPreviews,
    libraryPreviewLoading,
    libraryPreviewErrors,
    setLibraryPreviews,
    setLibraryPreviewErrors,
    clearLibraryPreviews,
    resetLibraryPreviews,
    loadLibraryPreview,
  } = useDreamweaverAssetPreviews()

  const missingRoleSet = useMemo(() => buildMissingRoleSet(library), [library?.review])
  const libraryAssetsByRole = useMemo(() => buildLibraryAssetsByRole(library), [library?.assets])
  const libraryApproved = Boolean(library?.review?.approved)

  const loadLibrary = useCallback(async (): Promise<string | null> => {
    if (!selectedProjectId) return '未选择项目'
    setLibraryLoading(true)
    setLibraryError(null)
    setLibrary(null)
    clearLibraryPreviews()
    try {
      const scopedRunId = typeof currentRunId === 'string' && currentRunId.trim() ? currentRunId.trim() : null
      const res = await apiClient.getDreamweaverLibrary(selectedProjectId, scopedRunId ? { run_id: scopedRunId } : undefined)
      const data = toLibraryPayload(res.data)
      if (!data) {
        setLibraryError('素材库响应格式无效')
        return '素材库响应格式无效'
      }
      setLibrary(data)
      setLibraryPlanItems(buildLibraryPlanItemsFromPayload(data))

      const assets = Array.isArray(data.assets) ? data.assets : []
      const scopedMissingRoleSet = extractMissingRoleSet(data)
      const previewEntries = await Promise.all(
        assets
          .filter((asset: LibraryAsset) => hasRenderableLibraryImage(asset, { missingRoleSet: scopedMissingRoleSet }))
          .map(async (asset: LibraryAsset) => {
            try {
              const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
              const url = URL.createObjectURL(fileRes.data)
              return { id: asset.id, url, error: '' }
            } catch (e: unknown) {
              const message = await extractApiErrorMessage(e, '加载预览失败')
              return { id: asset.id, url: '', error: message }
            }
          }),
      )
      const { previewMap, previewErrorMap } = collectLibraryPreviewMaps(previewEntries)
      setLibraryPreviews(previewMap)
      setLibraryPreviewErrors(previewErrorMap)
      return null
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, '加载素材库失败')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }, [selectedProjectId, currentRunId, clearLibraryPreviews, setLibraryPlanItems, setLibraryPreviews, setLibraryPreviewErrors])

  useEffect(() => {
    if (!selectedProjectId) return
    if (libraryLoading) return
    if (library || libraryPlanItems.length === 0) return
    if (autoLoadedLibraryRef.current) return
    autoLoadedLibraryRef.current = true
    void loadLibrary()
  }, [library, libraryLoading, libraryPlanItems.length, loadLibrary, selectedProjectId])

  const approveLibrary = useCallback(async (payload: { approve_all?: boolean; roles?: string[]; approved?: boolean }) => {
    if (!selectedProjectId) return
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.approveDreamweaverLibrary(selectedProjectId, payload)
      await loadLibrary()
    } catch (e: unknown) {
      setLibraryError(await extractApiErrorMessage(e, '更新审核状态失败'))
    } finally {
      setLibraryLoading(false)
    }
  }, [selectedProjectId, loadLibrary])

  const regenerateLibraryAssetFn = useCallback(async (options: Record<string, unknown>): Promise<string | null> => {
    const role = String(options.role || '').trim()
    if (!role) return 'missing asset role'
    if (!selectedProjectId) return 'project not selected'
    setLibraryLoading(true)
    setLibraryError(null)
    try {
      await apiClient.regenerateDreamweaverLibraryAsset(selectedProjectId, {
        role,
        ...(options.run_id ? { run_id: String(options.run_id) } : {}),
        ...(options.prompt ? { prompt: String(options.prompt) } : {}),
        ...(options.prefer_image_edit ? { prefer_image_edit: true } : {}),
        ...(options.prefer_view_chain_edit_base ? { prefer_view_chain_edit_base: true } : {}),
      })
      return await loadLibrary()
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, 'regenerate failed')
      setLibraryError(message)
      return message
    } finally {
      setLibraryLoading(false)
    }
  }, [selectedProjectId, loadLibrary])

  const loadLibraryPreviewWrapper = useCallback(async (asset: LibraryAsset, options?: { force?: boolean }): Promise<void> => {
    const hasRenderableImage = hasRenderableLibraryImage(asset, { missingRoleSet })
    await loadLibraryPreview(asset, { ...options, hasRenderableImage })
  }, [loadLibraryPreview, missingRoleSet])

  useEffect(() => {
    autoLoadedLibraryRef.current = false
  }, [currentRunId])

  const resetLibraryState = useCallback(() => {
    setLibrary(null)
    setLibraryError(null)
    resetLibraryPreviews()
  }, [resetLibraryPreviews])

  const clearLibraryError = useCallback(() => {
    setLibraryError(null)
  }, [])

  return {
    library,
    libraryLoading,
    libraryError,
    libraryPreviews,
    libraryPreviewLoading,
    libraryPreviewErrors,
    missingRoleSet,
    libraryAssetsByRole,
    libraryApproved,
    loadLibrary,
    approveLibrary,
    regenerateLibraryAssetFn,
    loadLibraryPreviewWrapper,
    resetLibraryState,
    clearLibraryError,
  }
}
