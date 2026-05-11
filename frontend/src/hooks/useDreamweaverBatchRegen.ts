import { useState, useCallback } from 'react'
import { apiClient, extractApiErrorMessage } from '../services/api'

export interface UseDreamweaverBatchRegenParams {
  projectId: number | undefined
  onRefresh: () => Promise<void>
  onError: (msg: string) => void
}

export interface UseDreamweaverBatchRegenReturn {
  batchRegenConfirmOpen: boolean
  batchRegenRoles: string[]
  batchRegenSubmitting: boolean
  batchRegenProgress: { done: number; total: number } | null
  batchRegenError: string | null
  openBatchRegenerateConfirm: () => Promise<void>
  executeBatchRegenerate: () => Promise<void>
  cancelBatchRegenerate: () => void
}

export function useDreamweaverBatchRegen(
  params: UseDreamweaverBatchRegenParams,
): UseDreamweaverBatchRegenReturn {
  const { projectId, onRefresh, onError } = params

  const [batchRegenConfirmOpen, setBatchRegenConfirmOpen] = useState(false)
  const [batchRegenRoles, setBatchRegenRoles] = useState<string[]>([])
  const [batchRegenSubmitting, setBatchRegenSubmitting] = useState(false)
  const [batchRegenProgress, setBatchRegenProgress] = useState<{ done: number; total: number } | null>(null)
  const [batchRegenError, setBatchRegenError] = useState<string | null>(null)

  const openBatchRegenerateConfirm = useCallback(async () => {
    if (!projectId) return
    setBatchRegenError(null)
    try {
      const res = await apiClient.suggestDreamweaverLibraryRegenerateRoles(projectId, {})
      const roles = Array.isArray(res.data?.regenerate_roles) ? (res.data.regenerate_roles as string[]) : []
      if (!roles.length) {
        onError('当前没有需要重生成的缺失素材')
        return
      }
      setBatchRegenRoles(roles)
      setBatchRegenConfirmOpen(true)
    } catch (e: any) {
      onError(await extractApiErrorMessage(e, '获取重生成建议失败'))
    }
  }, [projectId, onError])

  const executeBatchRegenerate = useCallback(async () => {
    if (!projectId || !batchRegenRoles.length) return
    setBatchRegenSubmitting(true)
    setBatchRegenProgress({ done: 0, total: batchRegenRoles.length })
    setBatchRegenError(null)
    let done = 0
    let lastError: string | null = null
    for (const role of batchRegenRoles) {
      try {
        await apiClient.regenerateDreamweaverLibraryAsset(projectId, { role })
        done++
        setBatchRegenProgress({ done, total: batchRegenRoles.length })
      } catch (e: any) {
        lastError = await extractApiErrorMessage(e, `重生成 ${role} 失败`)
        done++
        setBatchRegenProgress({ done, total: batchRegenRoles.length })
      }
    }
    setBatchRegenSubmitting(false)
    if (lastError) {
      setBatchRegenError(`部分素材重生成失败：${lastError}`)
    } else {
      setBatchRegenConfirmOpen(false)
      setBatchRegenRoles([])
      setBatchRegenProgress(null)
      await onRefresh()
    }
  }, [projectId, batchRegenRoles, onRefresh])

  const cancelBatchRegenerate = useCallback(() => {
    setBatchRegenConfirmOpen(false)
    setBatchRegenRoles([])
    setBatchRegenProgress(null)
    setBatchRegenError(null)
  }, [])

  return {
    batchRegenConfirmOpen,
    batchRegenRoles,
    batchRegenSubmitting,
    batchRegenProgress,
    batchRegenError,
    openBatchRegenerateConfirm,
    executeBatchRegenerate,
    cancelBatchRegenerate,
  }
}
