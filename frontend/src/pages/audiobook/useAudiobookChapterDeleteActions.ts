import { useCallback, useState, type Dispatch, type MouseEvent, type MutableRefObject, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { resolveAudiobookProjectIdForChapter } from './chapterSelectionUtils'
import type { SetSnackbar } from './hookTypes'
import type { Chapter } from './types'

interface UseAudiobookChapterDeleteActionsParams {
  setChapters: Dispatch<SetStateAction<Chapter[]>>
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
  setSnackbar: SetSnackbar
  projectId: number | null
  audiobookProjectId?: number
  onDeletedRef?: MutableRefObject<(() => void) | null>
}

export const useAudiobookChapterDeleteActions = ({
  setSelectedChapters,
  setSnackbar,
  projectId,
  audiobookProjectId,
  onDeletedRef,
}: UseAudiobookChapterDeleteActionsParams) => {
  const { t } = useTranslation()
  const [chapterMenuAnchor, setChapterMenuAnchor] = useState<null | HTMLElement>(null)
  const [selectedChapterForMenu, setSelectedChapterForMenu] = useState<Chapter | null>(null)
  const [deleteChapterDialogOpen, setDeleteChapterDialogOpen] = useState(false)
  const [deleteChapterReason, setDeleteChapterReason] = useState('')
  const [deleteChapterFiles, setDeleteChapterFiles] = useState(false)
  const [deletingChapter, setDeletingChapter] = useState(false)

  const resetChapterDeleteState = useCallback(() => {
    setChapterMenuAnchor(null)
    setSelectedChapterForMenu(null)
    setDeleteChapterDialogOpen(false)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
  }, [])

  const handleOpenChapterMenu = useCallback((event: MouseEvent<HTMLElement>, chapter: Chapter) => {
    event.stopPropagation()
    setChapterMenuAnchor(event.currentTarget)
    setSelectedChapterForMenu(chapter)
  }, [])

  const handleCloseChapterMenu = useCallback(() => {
    setChapterMenuAnchor(null)
    setSelectedChapterForMenu(null)
  }, [])

  const handleOpenDeleteChapterDialog = useCallback(() => {
    if (!selectedChapterForMenu) {
      setChapterMenuAnchor(null)
      return
    }
    setChapterMenuAnchor(null)
    setDeleteChapterDialogOpen(true)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
  }, [selectedChapterForMenu])

  const handleCloseDeleteChapterDialog = useCallback(() => {
    setDeleteChapterDialogOpen(false)
    setDeleteChapterReason('')
    setDeleteChapterFiles(false)
    setSelectedChapterForMenu(null)
  }, [])

  const handleDeleteChapter = useCallback(async () => {
    if (!selectedChapterForMenu) return
    let targetAudiobookProjectId = audiobookProjectId ?? null
    if (!targetAudiobookProjectId && projectId) {
      try {
        const response = await apiClient.getAudiobookProjectsByProject(projectId, {
          include_chapter_audios: true,
        })
        targetAudiobookProjectId = resolveAudiobookProjectIdForChapter(
          Array.isArray(response.data) ? response.data : [],
          selectedChapterForMenu.id,
        )
      } catch {
        // Fall through to the actionable error below.
      }
    }
    if (!targetAudiobookProjectId) {
      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookChapterDeleteActions.missingProject'),
        severity: 'error',
      })
      return
    }

    setDeletingChapter(true)
    try {
      await apiClient.deleteChapterAudiobookOutput(targetAudiobookProjectId, selectedChapterForMenu.id, {
        delete_reason: deleteChapterReason || undefined,
        delete_files: deleteChapterFiles,
      })

      // 删除的是有声书产出，源章节保留；列表状态由 onDeletedRef 刷新同步
      setSelectedChapters((prev) => prev.filter((id) => id !== selectedChapterForMenu.id))

      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookChapterDeleteActions.deleted'),
        severity: 'success',
      })
      onDeletedRef?.current?.()
      handleCloseDeleteChapterDialog()
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, t('audiobook.useAudiobookChapterDeleteActions.deleteFailed'))
      setSnackbar({
        open: true,
        message,
        severity: 'error',
      })
    } finally {
      setDeletingChapter(false)
    }
  }, [
    audiobookProjectId,
    deleteChapterFiles,
    deleteChapterReason,
    handleCloseDeleteChapterDialog,
    onDeletedRef,
    projectId,
    selectedChapterForMenu,
    setSelectedChapters,
    setSnackbar,
    t,
  ])

  return {
    chapterMenuAnchor,
    selectedChapterForMenu,
    setSelectedChapterForMenu,
    deleteChapterDialogOpen,
    setDeleteChapterDialogOpen,
    deleteChapterReason,
    setDeleteChapterReason,
    deleteChapterFiles,
    setDeleteChapterFiles,
    deletingChapter,
    resetChapterDeleteState,
    handleOpenChapterMenu,
    handleCloseChapterMenu,
    handleOpenDeleteChapterDialog,
    handleCloseDeleteChapterDialog,
    handleDeleteChapter,
  }
}
