import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '@/services/api'

export interface UseLibraryPreviewsOptions {
  assets: Array<{ id: number; uri: string }> | null | undefined
  enabled?: boolean
}

export interface LibraryPreviewState {
  previews: Record<number, string>
  aspectRatios: Record<number, string>
  loading: boolean
  error: string | null
}

export function useLibraryPreviews(options: UseLibraryPreviewsOptions): LibraryPreviewState & {
  reload: () => void
  clear: () => void
} {
  const { assets, enabled = true } = options
  const { t } = useTranslation()
  const [previews, setPreviews] = useState<Record<number, string>>({})
  const [aspectRatios, setAspectRatios] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const previewUrlsRef = useRef<Set<string>>(new Set())
  const requestIdRef = useRef(0)

  const clear = useCallback(() => {
    for (const url of previewUrlsRef.current) {
      if (url && url.startsWith('blob:')) {
        URL.revokeObjectURL(url)
      }
    }
    previewUrlsRef.current.clear()
    setPreviews({})
    setAspectRatios({})
    setError(null)
  }, [])

  const reload = useCallback(() => {
    if (!enabled || !assets || !assets.length) {
      clear()
      return
    }

    const requestId = ++requestIdRef.current
    setLoading(true)
    setError(null)

    const fetchPreviews = async () => {
        const entries: Array<[number, string]> = []
        for (const asset of assets) {
          if (!asset?.id || !asset?.uri) continue
          try {
            const resp = await apiClient.get(asset.uri, { responseType: 'blob' })
            const blob = resp.data
            if (!blob || !(blob instanceof Blob)) continue
            const url = URL.createObjectURL(blob)
            previewUrlsRef.current.add(url)
          entries.push([asset.id, url])
        } catch {
          // ignore individual errors
        }
      }
      return entries
    }

    fetchPreviews()
      .then((entries) => {
        if (requestId !== requestIdRef.current) return
        const newPreviews: Record<number, string> = {}
        for (const [id, url] of entries) {
          newPreviews[id] = url
        }
        setPreviews(newPreviews)
        setLoading(false)
      })
      .catch((err) => {
        if (requestId !== requestIdRef.current) return
        setError(err?.message || t('dreamweaverRun.errorLoadPreviewFailed'))
        setLoading(false)
      })
  }, [assets, enabled, clear, t])

  useEffect(() => {
    reload()
    return () => {
      for (const url of previewUrlsRef.current) {
        if (url && url.startsWith('blob:')) {
          URL.revokeObjectURL(url)
        }
      }
    }
  }, [reload])

  return {
    previews,
    aspectRatios,
    loading,
    error,
    reload,
    clear,
  }
}

export function useLibraryPreviewAspectRatios() {
  const [aspectRatios, setAspectRatios] = useState<Record<number, string>>({})

  const handleImageLoad = useCallback((assetId: number, event: React.SyntheticEvent<HTMLImageElement>) => {
    const target = event.currentTarget
    const width = target.naturalWidth
    const height = target.naturalHeight
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return
    const cssAspectRatio = `${width} / ${height}`
    setAspectRatios((prev) => (prev[assetId] === cssAspectRatio ? prev : { ...prev, [assetId]: cssAspectRatio }))
  }, [])

  const setAspectRatio = useCallback((assetId: number, ratio: string) => {
    setAspectRatios((prev) => (prev[assetId] === ratio ? prev : { ...prev, [assetId]: ratio }))
  }, [])

  return {
    aspectRatios,
    handleImageLoad,
    setAspectRatio,
  }
}
