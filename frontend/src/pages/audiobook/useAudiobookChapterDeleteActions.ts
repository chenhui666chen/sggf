import { useCallback, useState, type Dispatch, type MouseEvent, type SetStateAction } from 'react'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { SetSnackbar } from './hookTypes'
import type { Chapter } from './types'

interface UseAudiobookChapterDeleteActionsParams {
  setChapters: Dispatch<SetStateAction<Chapter[]>>
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
  setSnackbar: SetSnackbar
}

export const useAudiobookChapterDeleteActions = ({
  setChapters,
  setSelectedChapters,
  setSnackbar,
}: UseAudiobookChapterDeleteActionsParams) => {
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

    setDeletingChapter(true)
    try {
      await apiClient.deleteChapter(selectedChapterForMenu.id, {
        delete_reason: deleteChapterReason || undefined,
        delete_files: deleteChapterFiles,
      })

      setChapters((prev) => prev.filter((chapter) => chapter.id !== selectedChapterForMenu.id))
      setSelectedChapters((prev) => prev.filter((id) => id !== selectedChapterForMenu.id))

      setSnackbar({
        open: true,
        message: '章节已删除',
        severity: 'success',
      })
      handleCloseDeleteChapterDialog()
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, '删除章节失败')
      setSnackbar({
        open: true,
        message,
        severity: 'error',
      })
    } finally {
      setDeletingChapter(false)
    }
  }, [
    deleteChapterFiles,
    deleteChapterReason,
    handleCloseDeleteChapterDialog,
    selectedChapterForMenu,
    setChapters,
    setSelectedChapters,
    setSnackbar,
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
