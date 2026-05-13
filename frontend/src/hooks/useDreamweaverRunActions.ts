import { useCallback } from 'react'
import {
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'
import {
  buildLibraryPlanItemsFromPayload,
} from '@/utils/dreamweaver'
import type {
  DreamweaverRunSnapshot,
  DreamweaverLibraryPlanItem,
  DreamweaverTaskArtifacts,
  LibraryAsset,
  LibraryPayload,
} from '@/types/dreamweaver'
import { hasRenderableLibraryImage } from '@/utils/dreamweaverLibraryAssetState'
import {
  asObject,
  toDreamweaverQueuedTaskResponse,
  toDreamweaverVideoClipJobs,
  toLibraryPayload,
  withRunSnapshotVideoJobs,
  normalizeShotIds,
  normalizeCameraIndices,
  buildRestartPartialHint,
  validateRestartParams,
  arrayLength,
  collectLibraryPreviewMaps,
  extractMissingRoleSet,
} from '../pages/dreamweaver-run/runPageHelpers'

interface UseDreamweaverRunActionsDeps {
  selectedProjectId: number | null
  currentRunId: string | null
  running: boolean
  qcAllowFail: boolean
  smartTuning: boolean
  library: LibraryPayload | null
  setError: (v: string | null) => void
  setRunning: (v: boolean) => void
  setTaskId: (v: string | null) => void
  setTaskRunId: (v: string | null) => void
  setTaskStatus: (v: string | null) => void
  setTaskQueue: (v: string | null) => void
  setTaskProgress: (v: number) => void
  setTaskState: (v: string | null) => void
  setTaskStage: (v: string | null) => void
  setTaskArtifacts: (v: DreamweaverTaskArtifacts | null) => void
  setWaitingApproval: (v: boolean) => void
  setResumeLoading: (v: boolean) => void
  setRestartLoading: (v: boolean) => void
  setRestartAnchorEl: (v: HTMLElement | null) => void
  setLibrary: (v: LibraryPayload | null) => void
  setLibraryLoading: (v: boolean) => void
  setLibraryError: (v: string | null) => void
  setLibraryPlanItems: (items: DreamweaverLibraryPlanItem[]) => void
  clearLibraryPreviews: () => void
  setLibraryPreviews: (v: Record<number, string>) => void
  setLibraryPreviewErrors: (v: Record<number, string>) => void
  setVideoJobActionError: (v: string | null) => void
  setVideoJobConfirmingShotId: (v: string | null) => void
  setDiagnosticActionLoading: (v: boolean) => void
  setDiagnosticActionError: (v: string | null) => void
  setPromptReviewLoading: (v: boolean) => void
  setPromptReviewError: (v: string | null) => void
  setSafetyAuditApproveLoading: (v: boolean) => void
  setSafetyAuditApproveError: (v: string | null) => void
  setRunSnapshot: (updater: DreamweaverRunSnapshot | null | ((prev: DreamweaverRunSnapshot | null) => DreamweaverRunSnapshot | null)) => void
  resetForNewRun: (options?: { resetPreview?: boolean; resetApprovalState?: boolean; resetRunSpecificState?: boolean }) => void
  applyTerminalStatus: (payload: { run_id: string }) => void
  loadRunSnapshot: () => Promise<void>
  hydrateFromPersistedRun: (projectId: number, runId: string, taskId: string | null, status: string | null) => Promise<void>
}

export function useDreamweaverRunActions(deps: UseDreamweaverRunActionsDeps) {
  const {
    selectedProjectId,
    currentRunId,
    running,
    qcAllowFail,
    smartTuning,
    library,
    setError,
    setRunning,
    setTaskId,
    setTaskRunId,
    setTaskStatus,
    setTaskQueue,
    setTaskProgress,
    setTaskState,
    setTaskStage,
    setTaskArtifacts,
    setWaitingApproval,
    setResumeLoading,
    setRestartLoading,
    setRestartAnchorEl,
    setLibrary,
    setLibraryLoading,
    setLibraryError,
    setLibraryPlanItems,
    clearLibraryPreviews,
    setLibraryPreviews,
    setLibraryPreviewErrors,
    setVideoJobActionError,
    setVideoJobConfirmingShotId,
    setDiagnosticActionLoading,
    setDiagnosticActionError,
    setPromptReviewLoading,
    setPromptReviewError,
    setSafetyAuditApproveLoading,
    setSafetyAuditApproveError,
    setRunSnapshot,
    resetForNewRun,
    applyTerminalStatus,
    loadRunSnapshot,
    hydrateFromPersistedRun,
  } = deps

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
  }, [selectedProjectId, currentRunId, setLibraryLoading, setLibraryError, setLibrary, clearLibraryPreviews, setLibraryPlanItems, setLibraryPreviews, setLibraryPreviewErrors])

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
  }, [selectedProjectId, loadLibrary, setLibraryLoading, setLibraryError])

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
  }, [selectedProjectId, loadLibrary, setLibraryLoading, setLibraryError])

  const resumeGeneration = useCallback(async () => {
    if (!currentRunId) {
      setError('缺少 run_id，无法继续生成（请复制调试信息排查）')
      return
    }
    setError(null)
    setLibraryError(null)
    setResumeLoading(true)
    setTaskQueue(null)
    setRunning(true)
    setWaitingApproval(false)
    setTaskStatus('queued')
    try {
      const res = await apiClient.resumeDreamweaverAsync(currentRunId)
      const data = toDreamweaverQueuedTaskResponse(res.data)
      if (!data) {
        throw new Error('继续生成响应格式无效')
      }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id)
      setTaskStatus(data.status || 'queued')
    } catch (e: unknown) {
      setError(await extractApiErrorMessage(e, '继续生成失败'))
      setRunning(false)
      setWaitingApproval(true)
      setTaskStatus('waiting')
    } finally {
      setResumeLoading(false)
    }
  }, [currentRunId, setError, setLibraryError, setResumeLoading, setTaskQueue, setRunning, setWaitingApproval, setTaskStatus, setTaskId, setTaskRunId])

  const confirmVideoJob = useCallback(async (shotId: string) => {
    const sid = String(shotId || '').trim()
    if (!sid) return
    if (!currentRunId) {
      setVideoJobActionError('缺少 run_id，无法确认视频片段生成')
      return
    }
    if (running) {
      setVideoJobActionError('当前 run 正在运行中，请等待结束后再确认')
      return
    }
    setVideoJobActionError(null)
    setVideoJobConfirmingShotId(sid)
    setTaskQueue(null)
    try {
      const res = await apiClient.confirmDreamweaverVideoJobAsync(currentRunId, sid)
      const data = asObject(res.data) || {}
      const statusRaw = String(data.status || '').trim().toLowerCase()
      const message = data.message != null ? String(data.message || '').trim() : ''
      const jobs = Array.isArray(data.video_clip_jobs) ? toDreamweaverVideoClipJobs(data.video_clip_jobs) : null

      if (jobs) {
        setRunSnapshot((prev) => withRunSnapshotVideoJobs(prev, jobs))
      }

      if (statusRaw === 'queued' && data.task_id) {
        setRunning(true)
        setWaitingApproval(false)
        setTaskId(String(data.task_id))
        setTaskRunId(currentRunId)
        setTaskStatus('queued')
        setTaskState('VIDEO')
        setTaskStage('video')
        setTaskProgress(0)
        if (message) setError(message)
        return
      }

      if (message) setVideoJobActionError(message)
      if (!jobs) await loadRunSnapshot()
    } catch (e: unknown) {
      setVideoJobActionError(await extractApiErrorMessage(e, '确认视频片段生成失败'))
    } finally {
      setVideoJobConfirmingShotId(null)
    }
  }, [currentRunId, running, setVideoJobActionError, setVideoJobConfirmingShotId, setTaskQueue, setRunSnapshot, setRunning, setWaitingApproval, setTaskId, setTaskRunId, setTaskStatus, setTaskState, setTaskStage, setTaskProgress, setError, loadRunSnapshot])

  const restartGeneration = useCallback(async (startState: string, shotIds?: string[], camIdxs?: number[]) => {
    const startStateRaw = String(startState || '').trim().toUpperCase()
    if (!startStateRaw) return
    if (!currentRunId) {
      setError('缺少 run_id，无法重跑（请复制调试信息排查）')
      return
    }
    if (running) {
      setError('当前 run 正在运行中，无法重跑')
      return
    }

    const normalizedShotIds = normalizeShotIds(shotIds)
    const normalizedCamIdxs = normalizeCameraIndices(camIdxs)

    const validation = validateRestartParams(startStateRaw, normalizedShotIds, normalizedCamIdxs)
    if (!validation.valid) {
      setError(validation.error || '参数验证失败')
      return
    }

    const partialHint = buildRestartPartialHint(normalizedShotIds, normalizedCamIdxs)
    const ok = window.confirm(
      `将从 ${startStateRaw} 开始重跑，并清理该阶段及其下游产物（覆盖式重跑，可能产生额外调用/成本）。${partialHint}\n\n确认继续？`,
    )
    if (!ok) return

    resetForNewRun({ resetPreview: false, resetApprovalState: false, resetRunSpecificState: false })
    setRestartLoading(true)
    setRestartAnchorEl(null)
    setRunning(true)
    setWaitingApproval(false)
    setTaskStatus('queued')
    setTaskProgress(0)
    setTaskState(startStateRaw)
    setTaskStage(null)
    setTaskArtifacts(null)
    setLibraryPlanItems([])

    try {
      const missingRoleCount = arrayLength(library?.review?.missing_roles, 0) ?? 0
      const autoAssetRolesFromMissingViews =
        startStateRaw === 'ASSET_LIBRARY' &&
        normalizedShotIds.length === 0 &&
        normalizedCamIdxs.length === 0 &&
        missingRoleCount > 0
      const res = await apiClient.restartDreamweaverAsync(currentRunId, {
        start_state: startStateRaw,
        reset_policy: 'downstream',
        qc_allow_fail: qcAllowFail,
        smart_tuning: smartTuning,
        ...(normalizedShotIds.length > 0 ? { shot_ids: normalizedShotIds } : {}),
        ...(normalizedCamIdxs.length > 0 ? { cam_idxs: normalizedCamIdxs } : {}),
        ...(autoAssetRolesFromMissingViews ? { auto_asset_roles_from_missing_views: true } : {}),
      })
      const data = toDreamweaverQueuedTaskResponse(res.data)
      if (!data) {
        throw new Error('重跑响应格式无效')
      }
      setTaskId(data.task_id)
      setTaskRunId(data.run_id || currentRunId)
      setTaskStatus(data.status || 'queued')
    } catch (e: unknown) {
      setError(await extractApiErrorMessage(e, '重跑失败'))
      applyTerminalStatus({ run_id: currentRunId })
    } finally {
      setRestartLoading(false)
    }
  }, [currentRunId, running, qcAllowFail, smartTuning, library, setError, resetForNewRun, setRestartLoading, setRestartAnchorEl, setRunning, setWaitingApproval, setTaskStatus, setTaskProgress, setTaskState, setTaskStage, setTaskArtifacts, setLibraryPlanItems, setTaskId, setTaskRunId, applyTerminalStatus])

  const uploadShotAsset = useCallback(async (shotId: string, role: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip', file: File) => {
    const safeShotId = String(shotId || '').trim()
    if (!currentRunId) {
      setDiagnosticActionError('缺少 run_id，无法上传')
      return
    }
    if (!safeShotId) {
      setDiagnosticActionError('缺少 shot_id，无法上传')
      return
    }
    if (running) {
      setDiagnosticActionError('run 正在运行中，无法上传')
      return
    }
    if (!file) return

    const isVideo = role === 'video_clip'
    const filename = String(file.name || '').toLowerCase()
    if (!isVideo && !filename.endsWith('.png')) {
      setDiagnosticActionError('仅支持 PNG 替换 head/tail/mid')
      return
    }
    if (isVideo && !filename.endsWith('.mp4')) {
      setDiagnosticActionError('仅支持 MP4 替换 video_clip')
      return
    }
    const maxMb = isVideo ? 200 : 10
    if (typeof file.size === 'number' && file.size > maxMb * 1024 * 1024) {
      setDiagnosticActionError(`文件过大（>${maxMb}MB），请压缩后再上传`)
      return
    }

    setDiagnosticActionLoading(true)
    setDiagnosticActionError(null)
    try {
      await apiClient.uploadDreamweaverRunShotAssetFile(currentRunId, safeShotId, role, file)
      await loadRunSnapshot()
    } catch (e: unknown) {
      setDiagnosticActionError(await extractApiErrorMessage(e, '上传失败'))
    } finally {
      setDiagnosticActionLoading(false)
    }
  }, [currentRunId, running, setDiagnosticActionError, setDiagnosticActionLoading, loadRunSnapshot])

  const promptAndRegenerateKeyframe = useCallback(async (shotId: string, frame: 'head' | 'tail', defaultPrompt: string) => {
    const safeShotId = String(shotId || '').trim()
    if (!currentRunId) {
      setDiagnosticActionError('缺少 run_id，无法重生成')
      return
    }
    if (!safeShotId) {
      setDiagnosticActionError('缺少 shot_id，无法重生成')
      return
    }
    if (running) {
      setDiagnosticActionError('run 正在运行中，无法重生成')
      return
    }

    const initial = String(defaultPrompt || '').trim()
    const nextPrompt = window.prompt(`请输入要用于 ${safeShotId} 的 ${frame === 'head' ? '首帧' : '尾帧'} 提示词（将写入契约并用于 KEYFRAMES 重跑）`, initial)
    if (nextPrompt == null) return
    const value = String(nextPrompt || '').trim()
    if (!value) {
      setDiagnosticActionError('提示词不能为空')
      return
    }
    if (value.length > 2000) {
      setDiagnosticActionError('提示词过长（>2000）')
      return
    }

    setDiagnosticActionLoading(true)
    setDiagnosticActionError(null)
    try {
      await apiClient.updateDreamweaverRunShotFramePrompt(currentRunId, safeShotId, frame, value)
      await loadRunSnapshot()
    } catch (e: unknown) {
      setDiagnosticActionError(await extractApiErrorMessage(e, '更新提示词失败'))
      return
    } finally {
      setDiagnosticActionLoading(false)
    }

    await restartGeneration('KEYFRAMES', [safeShotId])
  }, [currentRunId, running, setDiagnosticActionError, setDiagnosticActionLoading, loadRunSnapshot, restartGeneration])

  const approvePromptReview = useCallback(async (approved: boolean) => {
    if (!currentRunId) return
    setPromptReviewLoading(true)
    setPromptReviewError(null)
    try {
      await apiClient.approveDreamweaverPromptReview(currentRunId, { approved })
      await loadRunSnapshot()
    } catch (e: unknown) {
      setPromptReviewError(await extractApiErrorMessage(e, '更新提示词审核状态失败'))
    } finally {
      setPromptReviewLoading(false)
    }
  }, [currentRunId, setPromptReviewLoading, setPromptReviewError, loadRunSnapshot])

  const approveSafetyAudit = useCallback(async () => {
    if (!currentRunId || !selectedProjectId) return
    setSafetyAuditApproveLoading(true)
    setSafetyAuditApproveError(null)
    try {
      await apiClient.approveDreamweaverSafetyAudit(currentRunId)
      setError(null)
      applyTerminalStatus({ run_id: currentRunId })
      await hydrateFromPersistedRun(selectedProjectId, currentRunId, null, 'completed')
    } catch (e: unknown) {
      setSafetyAuditApproveError(await extractApiErrorMessage(e, '人工放行安全审核失败'))
    } finally {
      setSafetyAuditApproveLoading(false)
    }
  }, [currentRunId, selectedProjectId, setSafetyAuditApproveLoading, setSafetyAuditApproveError, setError, applyTerminalStatus, hydrateFromPersistedRun])

  return {
    loadLibrary,
    approveLibrary,
    regenerateLibraryAssetFn,
    resumeGeneration,
    confirmVideoJob,
    restartGeneration,
    uploadShotAsset,
    promptAndRegenerateKeyframe,
    approvePromptReview,
    approveSafetyAudit,
  }
}
