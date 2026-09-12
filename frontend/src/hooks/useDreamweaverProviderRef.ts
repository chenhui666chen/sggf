import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, extractApiErrorMessage } from '../services/api'

export interface UseDreamweaverProviderRefParams {
  onRefresh: () => Promise<void>
}

export interface UseDreamweaverProviderRefReturn {
  providerRefDialogOpen: boolean
  providerRefAssetId: number | null
  providerRefAssetRole: string
  providerRefSubjectId: string
  providerRefSubmitting: boolean
  providerRefError: string | null
  providerSyncAssetId: number | null
  providerSyncSubmitting: boolean
  openProviderRefDialog: (assetId: number, role: string, currentSubjectId?: string) => void
  closeProviderRefDialog: () => void
  setProviderRefSubjectId: (v: string) => void
  submitProviderRef: () => Promise<void>
  syncProviderRef: (assetId: number) => Promise<void>
}

export function useDreamweaverProviderRef(
  params: UseDreamweaverProviderRefParams,
): UseDreamweaverProviderRefReturn {
  const { onRefresh } = params
  const { t } = useTranslation()

  const [providerRefDialogOpen, setProviderRefDialogOpen] = useState(false)
  const [providerRefAssetId, setProviderRefAssetId] = useState<number | null>(null)
  const [providerRefAssetRole, setProviderRefAssetRole] = useState('')
  const [providerRefSubjectId, setProviderRefSubjectId] = useState('')
  const [providerRefSubmitting, setProviderRefSubmitting] = useState(false)
  const [providerRefError, setProviderRefError] = useState<string | null>(null)
  const [providerSyncAssetId, setProviderSyncAssetId] = useState<number | null>(null)
  const [providerSyncSubmitting, setProviderSyncSubmitting] = useState(false)

  const openProviderRefDialog = useCallback(
    (assetId: number, role: string, currentSubjectId?: string) => {
      setProviderRefAssetId(assetId)
      setProviderRefAssetRole(role)
      setProviderRefSubjectId(currentSubjectId ?? '')
      setProviderRefError(null)
      setProviderRefDialogOpen(true)
    },
    [],
  )

  const closeProviderRefDialog = useCallback(() => {
    setProviderRefDialogOpen(false)
  }, [])

  const submitProviderRef = useCallback(async () => {
    if (!providerRefAssetId) return
    setProviderRefSubmitting(true)
    setProviderRefError(null)
    try {
      await apiClient.updateDreamweaverLibraryAssetProviderRef(providerRefAssetId, {
        provider: 'kling',
        subject_id: providerRefSubjectId.trim() || null,
      })
      setProviderRefDialogOpen(false)
      await onRefresh()
    } catch (e: any) {
      setProviderRefError(await extractApiErrorMessage(e, t('dreamweaverRun.bindKlingProviderFailed')))
    } finally {
      setProviderRefSubmitting(false)
    }
  }, [providerRefAssetId, providerRefSubjectId, onRefresh, t])

  const syncProviderRef = useCallback(
    async (assetId: number) => {
      setProviderSyncAssetId(assetId)
      setProviderSyncSubmitting(true)
      try {
        await apiClient.syncDreamweaverLibraryAssetProviderRef(assetId, {
          provider: 'kling',
          include_related_views: true,
        })
        await onRefresh()
      } catch (e: any) {
        console.warn('Kling provider ref sync failed for asset %d:', assetId, e)
      } finally {
        setProviderSyncSubmitting(false)
        setProviderSyncAssetId(null)
      }
    },
    [onRefresh],
  )

  return {
    providerRefDialogOpen,
    providerRefAssetId,
    providerRefAssetRole,
    providerRefSubjectId,
    providerRefSubmitting,
    providerRefError,
    providerSyncAssetId,
    providerSyncSubmitting,
    openProviderRefDialog,
    closeProviderRefDialog,
    setProviderRefSubjectId,
    submitProviderRef,
    syncProviderRef,
  }
}
