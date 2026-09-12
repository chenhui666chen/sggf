import { useEffect, useState } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  extractApiErrorMessage,
  type AssetStudioModelCatalogResponse,
} from '@/services/api'

export function useAssetStudioModelCatalog() {
  const { t } = useTranslation()
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
        setError(await extractApiErrorMessage(err, t('modelCatalog.hook.loadCatalogFailed')))
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
