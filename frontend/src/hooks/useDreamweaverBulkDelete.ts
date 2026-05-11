import { useCallback, useState } from 'react'

import { apiClient, extractApiErrorMessage } from '@/services/api'
import type { BulkDeleteProgress, BulkDeleteResult, DreamweaverRunSummary } from '@/types/dreamweaver'

export interface UseDreamweaverBulkDeleteParams {
  getProjectId: () => number | null
  getBulkDeleteTargets: () => DreamweaverRunSummary[]
  getFilteredHistoryCount: () => number
  getPersistedRunId: () => string | null
  onResetCurrentRunState: () => void
  onClearPersistedRunIfMatch: (projectId: number, runId: string) => void
  onFetchRunHistory: (projectId: number) => Promise<void>
  onRefreshLockedGenerationConfig: (projectId: number) => Promise<void>
}

export interface UseDreamweaverBulkDeleteReturn {
  bulkDeleteDialogOpen: boolean
  bulkDeleteSubmitting: boolean
  bulkDeleteError: string | null
  bulkDeleteProgress: BulkDeleteProgress | null
  bulkDeleteResult: BulkDeleteResult | null
  openBulkDeleteDialog: () => void
  closeBulkDeleteDialog: () => void
  confirmBulkDeleteRuns: () => Promise<void>
}

export function useDreamweaverBulkDelete(
  params: UseDreamweaverBulkDeleteParams,
): UseDreamweaverBulkDeleteReturn {
  const {
    getProjectId,
    getBulkDeleteTargets,
    getFilteredHistoryCount,
    getPersistedRunId,
    onResetCurrentRunState,
    onClearPersistedRunIfMatch,
    onFetchRunHistory,
    onRefreshLockedGenerationConfig,
  } = params

  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteSubmitting, setBulkDeleteSubmitting] = useState(false)
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null)
  const [bulkDeleteProgress, setBulkDeleteProgress] = useState<BulkDeleteProgress | null>(null)
  const [bulkDeleteResult, setBulkDeleteResult] = useState<BulkDeleteResult | null>(null)

  const openBulkDeleteDialog = useCallback(() => {
    const projectId = getProjectId()
    if (!projectId) return
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress(null)
    setBulkDeleteDialogOpen(true)
  }, [getProjectId])

  const closeBulkDeleteDialog = useCallback(() => {
    if (bulkDeleteSubmitting) return
    setBulkDeleteDialogOpen(false)
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress(null)
  }, [bulkDeleteSubmitting])

  const confirmBulkDeleteRuns = useCallback(async () => {
    const projectId = getProjectId()
    if (!projectId) return

    const targets = [...getBulkDeleteTargets()]
    if (!targets.length) return

    setBulkDeleteSubmitting(true)
    setBulkDeleteError(null)
    setBulkDeleteResult(null)
    setBulkDeleteProgress({ current: 0, total: targets.length })

    const errors: string[] = []
    let deleted = 0

    for (let i = 0; i < targets.length; i += 1) {
      const run = targets[i]
      const runId = String(run.run_id || '').trim()
      if (!runId) continue

      try {
        await apiClient.deleteDreamweaverRun(runId, true)
        deleted += 1

        onClearPersistedRunIfMatch(projectId, runId)

        if (getPersistedRunId() === runId) {
          onResetCurrentRunState()
        }
      } catch (e: unknown) {
        const msg = await extractApiErrorMessage(e, '删除失败')
        errors.push(`${runId}: ${msg}`)
      } finally {
        setBulkDeleteProgress({ current: i + 1, total: targets.length })
      }
    }

    try {
      await onFetchRunHistory(projectId)
    } catch {
      // ignore
    }
    try {
      await onRefreshLockedGenerationConfig(projectId)
    } catch {
      // ignore
    }

    setBulkDeleteResult({
      deleted,
      skipped: Math.max(0, getFilteredHistoryCount() - targets.length),
      failed: errors.length,
      errors,
    })
    setBulkDeleteSubmitting(false)
  }, [
    getProjectId,
    getBulkDeleteTargets,
    getFilteredHistoryCount,
    getPersistedRunId,
    onResetCurrentRunState,
    onClearPersistedRunIfMatch,
    onFetchRunHistory,
    onRefreshLockedGenerationConfig,
  ])

  return {
    bulkDeleteDialogOpen,
    bulkDeleteSubmitting,
    bulkDeleteError,
    bulkDeleteProgress,
    bulkDeleteResult,
    openBulkDeleteDialog,
    closeBulkDeleteDialog,
    confirmBulkDeleteRuns,
  }
}
