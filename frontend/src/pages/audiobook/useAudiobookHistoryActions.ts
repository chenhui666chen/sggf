import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import { removeStoredTaskSessionForAudiobookProject } from './routeProjectSessionUtils'
import type { AudiobookProjectDetail, AudiobookProjectHistoryItem } from './types'

interface UseAudiobookHistoryActionsParams {
  selectedProjectId: number | null
  currentAudiobookProjectId: number | null
  audiobookProjectDetailId: number | null
  clearActiveGenerationState: () => void
  resetBrowserPlayer: () => void
  setAudiobookProject: Dispatch<SetStateAction<AudiobookProjectDetail | null>>
  setCurrentAudiobookProjectId: Dispatch<SetStateAction<number | null>>
  setActiveStep: Dispatch<SetStateAction<number>>
  setSnackbar: SetSnackbar
}

const getHttpStatusFromError = (error: unknown): number | null => {
  if (!error || typeof error !== 'object') {
    return null
  }

  const response = (error as { response?: { status?: unknown } }).response
  return typeof response?.status === 'number' ? response.status : null
}

export const useAudiobookHistoryActions = ({
  selectedProjectId,
  currentAudiobookProjectId,
  audiobookProjectDetailId,
  clearActiveGenerationState,
  resetBrowserPlayer,
  setAudiobookProject,
  setCurrentAudiobookProjectId,
  setActiveStep,
  setSnackbar,
}: UseAudiobookHistoryActionsParams) => {
  const { t } = useTranslation()
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyProjects, setHistoryProjects] = useState<AudiobookProjectHistoryItem[]>([])
  const [showHistory, setShowHistory] = useState(false)

  const fetchHistory = useCallback(
    async (options?: { projectId?: number | null; showLoading?: boolean }) => {
      const targetProjectId = options?.projectId ?? selectedProjectId
      if (!targetProjectId) {
        setHistoryProjects([])
        return []
      }

      const shouldShowLoading = options?.showLoading ?? true
      if (shouldShowLoading) {
        setLoadingHistory(true)
      }

      try {
        const response = await apiClient.getAudiobookProjectsByProject(targetProjectId)
        const nextProjects = Array.isArray(response.data) ? response.data : []
        setHistoryProjects(nextProjects)
        return nextProjects
      } catch {
        return []
      } finally {
        if (shouldShowLoading) {
          setLoadingHistory(false)
        }
      }
    },
    [selectedProjectId],
  )

  useEffect(() => {
    if (!selectedProjectId) {
      setHistoryProjects([])
      return
    }

    void fetchHistory({ projectId: selectedProjectId, showLoading: false })
  }, [selectedProjectId, fetchHistory])

  const handleOpenHistoryPanel = useCallback(() => {
    setShowHistory(true)
    void fetchHistory()
  }, [fetchHistory])

  const handleCloseHistoryPanel = useCallback(() => {
    setShowHistory(false)
  }, [])

  const handleViewHistory = useCallback(async (audiobookProjectId: number) => {
    try {
      const response = await apiClient.getAudiobookProject(audiobookProjectId)
      const data = response.data
      clearActiveGenerationState()
      setAudiobookProject(data)
      resetBrowserPlayer()
      setCurrentAudiobookProjectId(data.id)
      setActiveStep(2)
      setShowHistory(false)
    } catch {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookHistoryActions.loadFailed'), severity: 'error' })
    }
  }, [
    clearActiveGenerationState,
    resetBrowserPlayer,
    setActiveStep,
    setAudiobookProject,
    setCurrentAudiobookProjectId,
    setSnackbar,
    t,
  ])

  const handleDeleteHistory = useCallback(async (audiobookProjectId: number, options?: { delete_reason?: string; delete_files?: boolean }) => {
    try {
      await apiClient.deleteAudiobookProject(audiobookProjectId, {
        delete_files: options?.delete_files ?? true,
        delete_reason: options?.delete_reason,
      })
      // 清除指向被删除有声书项目的本地任务会话，避免重新进入项目时恢复到已删除的生成步骤
      removeStoredTaskSessionForAudiobookProject({ storage: localStorage, audiobookProjectId })
      // 同步重置引用被删除项目的内存状态：否则会话同步 effect 会在清除后
      // 立即把陈旧的 activeStep/任务焦点重新写回 localStorage，导致清除失效
      if (audiobookProjectId === currentAudiobookProjectId || audiobookProjectId === audiobookProjectDetailId) {
        clearActiveGenerationState()
        resetBrowserPlayer()
        if (audiobookProjectId === audiobookProjectDetailId) {
          setAudiobookProject(null)
        }
        setActiveStep(0)
      }
      setSnackbar({ open: true, message: t('audiobook.useAudiobookHistoryActions.projectDeleted'), severity: 'success' })
      await fetchHistory({ showLoading: false })
    } catch (error: unknown) {
      const errorMessage = getHttpStatusFromError(error) === 404
        ? t('audiobook.useAudiobookHistoryActions.projectNotFound')
        : await extractApiErrorMessage(error, t('audiobook.useAudiobookHistoryActions.deleteFailed'))
      setSnackbar({ open: true, message: errorMessage, severity: 'error' })
    }
  }, [
    fetchHistory,
    setSnackbar,
    currentAudiobookProjectId,
    audiobookProjectDetailId,
    clearActiveGenerationState,
    resetBrowserPlayer,
    setAudiobookProject,
    setActiveStep,
    t,
  ])

  return {
    loadingHistory,
    historyProjects,
    showHistory,
    setShowHistory,
    fetchHistory,
    handleOpenHistoryPanel,
    handleCloseHistoryPanel,
    handleViewHistory,
    handleDeleteHistory,
  }
}
