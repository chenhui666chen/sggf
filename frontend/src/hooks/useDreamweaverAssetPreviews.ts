import { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type { LibraryAsset } from '@/types/dreamweaver'

export function useDreamweaverAssetPreviews() {
  const { t } = useTranslation()
  const [libraryPreviews, setLibraryPreviews] = useState<Record<number, string>>({})
  const [libraryPreviewLoading, setLibraryPreviewLoading] = useState<Record<number, boolean>>({})
  const [libraryPreviewErrors, setLibraryPreviewErrors] = useState<Record<number, string>>({})
  const libraryPreviewsRef = useRef<Record<number, string>>({})

  useEffect(() => {
    libraryPreviewsRef.current = libraryPreviews
  }, [libraryPreviews])

  const clearLibraryPreviews = useCallback(() => {
    Object.values(libraryPreviewsRef.current).forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore
      }
    })
    libraryPreviewsRef.current = {}
    setLibraryPreviews({})
    setLibraryPreviewLoading({})
    setLibraryPreviewErrors({})
  }, [])

  const resetLibraryPreviews = useCallback(() => {
    setLibraryPreviews({})
    setLibraryPreviewLoading({})
    setLibraryPreviewErrors({})
  }, [])

  const loadLibraryPreview = useCallback(async (
    asset: LibraryAsset,
    options?: { force?: boolean; hasRenderableImage?: boolean },
  ): Promise<void> => {
    if (!asset?.id) return
    if (options?.hasRenderableImage === false) {
      setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: t('dreamweaverRun.noPreviewForPlaceholder') }))
      return
    }
    if (!options?.force && libraryPreviewsRef.current[asset.id]) return
    setLibraryPreviewLoading((prev) => ({ ...prev, [asset.id]: true }))
    setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: '' }))
    try {
      const fileRes = await apiClient.getDreamweaverLibraryAssetFile(asset.id)
      const url = URL.createObjectURL(fileRes.data)
      setLibraryPreviews((prev) => ({ ...prev, [asset.id]: url }))
    } catch (e: unknown) {
      const message = await extractApiErrorMessage(e, t('dreamweaverRun.errorLoadPreviewFailed'))
      setLibraryPreviewErrors((prev) => ({ ...prev, [asset.id]: message }))
    } finally {
      setLibraryPreviewLoading((prev) => ({ ...prev, [asset.id]: false }))
    }
  }, [t])

  return {
    libraryPreviews,
    libraryPreviewLoading,
    libraryPreviewErrors,
    libraryPreviewsRef,
    setLibraryPreviews,
    setLibraryPreviewErrors,
    clearLibraryPreviews,
    resetLibraryPreviews,
    loadLibraryPreview,
  }
}
