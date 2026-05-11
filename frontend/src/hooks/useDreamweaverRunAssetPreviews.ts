import { useCallback, useEffect, useRef, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '@/services/api'

export interface UseDreamweaverRunAssetPreviewsParams {
  getCurrentRunId: () => string | null
}

export interface UseDreamweaverRunAssetPreviewsReturn {
  runAssetPreviews: Record<string, string>
  runAssetPreviewLoading: Record<string, boolean>
  runAssetPreviewErrors: Record<string, string>
  loadRunAssetPreview: (uri: string) => Promise<void>
  downloadRunAsset: (uri: string) => Promise<void>
  clearRunAssetPreviews: () => void
}

export function useDreamweaverRunAssetPreviews(
  params: UseDreamweaverRunAssetPreviewsParams,
): UseDreamweaverRunAssetPreviewsReturn {
  const { getCurrentRunId } = params

  const [runAssetPreviews, setRunAssetPreviews] = useState<Record<string, string>>({})
  const [runAssetPreviewLoading, setRunAssetPreviewLoading] = useState<Record<string, boolean>>({})
  const [runAssetPreviewErrors, setRunAssetPreviewErrors] = useState<Record<string, string>>({})
  const runAssetPreviewsRef = useRef<Record<string, string>>({})

  useEffect(() => {
    runAssetPreviewsRef.current = runAssetPreviews
  }, [runAssetPreviews])

  const clearRunAssetPreviews = useCallback(() => {
    Object.values(runAssetPreviewsRef.current).forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // ignore
      }
    })
    runAssetPreviewsRef.current = {}
    setRunAssetPreviews({})
    setRunAssetPreviewLoading({})
    setRunAssetPreviewErrors({})
  }, [])

  const loadRunAssetPreview = useCallback(
    async (uri: string) => {
      const targetUri = String(uri || '').trim()
      if (!targetUri) return
      const runId = getCurrentRunId()
      if (!runId) {
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: '缺少 run_id，无法加载产物预览' }))
        return
      }

      setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: true }))
      setRunAssetPreviewErrors((prev) => {
        const next = { ...prev }
        delete next[targetUri]
        return next
      })
      try {
        const res = await apiClient.getDreamweaverRunAssetFile(runId, targetUri)
        const url = URL.createObjectURL(res.data)
        setRunAssetPreviews((prev) => {
          const existed = prev[targetUri]
          if (existed) {
            try {
              URL.revokeObjectURL(existed)
            } catch {
              // ignore
            }
          }
          return { ...prev, [targetUri]: url }
        })
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '加载产物预览失败')
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: msg }))
      } finally {
        setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: false }))
      }
    },
    [getCurrentRunId],
  )

  const downloadRunAsset = useCallback(
    async (uri: string) => {
      const targetUri = String(uri || '').trim()
      if (!targetUri) return
      const runId = getCurrentRunId()
      if (!runId) {
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: '缺少 run_id，无法下载产物' }))
        return
      }

      setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: true }))
      try {
        const res = await apiClient.getDreamweaverRunAssetFile(runId, targetUri)
        const url = URL.createObjectURL(res.data)
        const filename = targetUri.split(/[\\/]+/).pop() || `asset_${runId}`
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => {
          try {
            URL.revokeObjectURL(url)
          } catch {
            // ignore
          }
        }, 0)
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '下载产物失败')
        setRunAssetPreviewErrors((prev) => ({ ...prev, [targetUri]: msg }))
      } finally {
        setRunAssetPreviewLoading((prev) => ({ ...prev, [targetUri]: false }))
      }
    },
    [getCurrentRunId],
  )

  return {
    runAssetPreviews,
    runAssetPreviewLoading,
    runAssetPreviewErrors,
    loadRunAssetPreview,
    downloadRunAsset,
    clearRunAssetPreviews,
  }
}
