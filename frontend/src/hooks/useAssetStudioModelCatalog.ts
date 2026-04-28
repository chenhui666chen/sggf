import { useEffect, useState } from 'react'

import {
  apiClient,
  extractApiErrorMessage,
  type AssetStudioModelCatalogResponse,
} from '@/services/api'

export function useAssetStudioModelCatalog() {
  const [catalog, setCatalog] = useState<AssetStudioModelCatalogResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      setLoading(true)
      try {
        const response = await apiClient.getAssetStudioModelCatalog()
        if (cancelled) {
          return
        }
        setCatalog(response.data ?? null)
        setError(null)
      } catch (err) {
        if (cancelled) {
          return
        }
        setCatalog(null)
        setError(await extractApiErrorMessage(err, '加载统一模型清单失败'))
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  return {
    catalog,
    loading,
    error,
  }
}
