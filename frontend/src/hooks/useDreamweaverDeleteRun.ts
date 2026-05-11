import { useCallback, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '@/services/api'

export interface UseDreamweaverDeleteRunParams {
  getPersistedRunId: () => string | null
  onResetCurrentRunState: () => void
  onClearPersistedRunIfMatch: (projectId: number, runId: string) => void
  onFetchRunHistory: (projectId: number) => Promise<void>
  onRefreshLockedGenerationConfig: (projectId: number) => Promise<void>
  onResetMissingRunState: (projectId: number | null) => void
  isNotFoundError: (e: unknown) => boolean
}

export interface UseDreamweaverDeleteRunReturn {
  deleteRunId: string | null
  deleteDialogOpen: boolean
  deleteSubmitting: boolean
  deleteDialogError: string | null
  openDeleteRunDialog: (runId: string) => void
  closeDeleteRunDialog: () => void
  confirmDeleteRun: (projectId: number | null) => Promise<void>
}

export function useDreamweaverDeleteRun(
  params: UseDreamweaverDeleteRunParams,
): UseDreamweaverDeleteRunReturn {
  const {
    getPersistedRunId,
    onResetCurrentRunState,
    onClearPersistedRunIfMatch,
    onFetchRunHistory,
    onRefreshLockedGenerationConfig,
    onResetMissingRunState,
    isNotFoundError,
  } = params

  const [deleteRunId, setDeleteRunId] = useState<string | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteSubmitting, setDeleteSubmitting] = useState(false)
  const [deleteDialogError, setDeleteDialogError] = useState<string | null>(null)

  const openDeleteRunDialog = useCallback((runId: string) => {
    const nextRunId = String(runId || '').trim()
    if (!nextRunId) return
    setDeleteDialogError(null)
    setDeleteRunId(nextRunId)
    setDeleteDialogOpen(true)
  }, [])

  const closeDeleteRunDialog = useCallback(() => {
    if (deleteSubmitting) return
    setDeleteDialogOpen(false)
    setDeleteRunId(null)
    setDeleteDialogError(null)
  }, [deleteSubmitting])

  const confirmDeleteRun = useCallback(async (projectId: number | null) => {
    if (!deleteRunId || !projectId) return
    setDeleteSubmitting(true)
    setDeleteDialogError(null)
    try {
      await apiClient.deleteDreamweaverRun(deleteRunId, true)

      onClearPersistedRunIfMatch(projectId, deleteRunId)

      if (getPersistedRunId() === deleteRunId) {
        onResetCurrentRunState()
      }

      await onFetchRunHistory(projectId)
      await onRefreshLockedGenerationConfig(projectId)

      setDeleteDialogOpen(false)
      setDeleteRunId(null)
    } catch (e: unknown) {
      if (isNotFoundError(e)) {
        onResetMissingRunState(projectId)
      }
      setDeleteDialogError(await extractApiErrorMessage(e, '删除失败'))
    } finally {
      setDeleteSubmitting(false)
    }
  }, [
    deleteRunId,
    getPersistedRunId,
    onResetCurrentRunState,
    onClearPersistedRunIfMatch,
    onFetchRunHistory,
    onRefreshLockedGenerationConfig,
    onResetMissingRunState,
    isNotFoundError,
  ])

  return {
    deleteRunId,
    deleteDialogOpen,
    deleteSubmitting,
    deleteDialogError,
    openDeleteRunDialog,
    closeDeleteRunDialog,
    confirmDeleteRun,
  }
}
