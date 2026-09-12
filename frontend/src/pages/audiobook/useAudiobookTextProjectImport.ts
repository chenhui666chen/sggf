import type { TranslateFn } from './audioLibraryDisplay'
import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import * as bookParserApi from '../../services/bookParserApi'
import type { SetSnackbar } from './hookTypes'
import type { Project } from './types'

type HandleSelectProject = (
  project: Project,
  options?: {
    skipStepReset?: boolean
  },
) => Promise<void>

interface UseAudiobookTextProjectImportParams {
  handleSelectProject: HandleSelectProject
  setActiveStep: Dispatch<SetStateAction<number>>
  setSnackbar: SetSnackbar
}

const waitForBookParserStatus = async (bookId: number, targetStatuses: string[], t?: TranslateFn) => {
  while (true) {
    const status = await bookParserApi.getParseStatus(bookId)
    if (targetStatuses.includes(status.status)) {
      return status
    }
    if (status.status === 'failed') {
      throw new Error(status.error || (t ? t('audiobook.useAudiobookTextProjectImport.parseTaskFailed') : '拆书任务失败'))
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
}

export const useAudiobookTextProjectImport = ({
  handleSelectProject,
  setActiveStep,
  setSnackbar,
}: UseAudiobookTextProjectImportParams) => {
  const { t } = useTranslation()
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false)
  const [newProjectTitle, setNewProjectTitle] = useState('')
  const [newProjectText, setNewProjectText] = useState('')
  const [creatingFromBook, setCreatingFromBook] = useState(false)

  const handleOpenNewProjectDialog = useCallback(() => {
    setNewProjectDialogOpen(true)
  }, [])

  const handleCloseNewProjectDialog = useCallback(() => {
    setNewProjectDialogOpen(false)
  }, [])

  const handleCreateProjectFromText = useCallback(async () => {
    const rawText = newProjectText.trim()
    if (!rawText) {
      setSnackbar({ open: true, message: t('audiobook.useAudiobookTextProjectImport.pasteTextFirst'), severity: 'error' })
      return
    }

    const title = newProjectTitle.trim() || t('audiobook.useAudiobookTextProjectImport.defaultProjectTitle')

    setCreatingFromBook(true)
    try {
      const book = await bookParserApi.uploadText({
        title,
        content: rawText,
      })

      const bookId = book.id

      await bookParserApi.parseBook(bookId)
      await waitForBookParserStatus(bookId, ['chapters_done'], t)

      await bookParserApi.analyzeBook(bookId)
      await waitForBookParserStatus(bookId, ['completed'], t)

      const importResult = await bookParserApi.importToProject(bookId, {
        project_title: title,
        import_settings: true,
        import_characters: true,
        import_chapters: true,
      })

      try {
        const projectResponse = await apiClient.getProject(importResult.project_id)
        const project = projectResponse.data as Project
        await handleSelectProject(project, { skipStepReset: true })
      } catch {
        const fallbackProject: Project = {
          id: importResult.project_id,
          title: importResult.project_title || title,
          description: undefined,
          genre: undefined,
        }
        await handleSelectProject(fallbackProject, { skipStepReset: true })
      }

      setActiveStep(0)
      setNewProjectDialogOpen(false)
      setNewProjectTitle('')
      setNewProjectText('')

      setSnackbar({
        open: true,
        message: t('audiobook.useAudiobookTextProjectImport.projectCreated'),
        severity: 'success',
      })
    } catch (error: unknown) {
      const message = await extractApiErrorMessage(error, t('audiobook.useAudiobookTextProjectImport.createProjectFailed'))
      setSnackbar({
        open: true,
        message,
        severity: 'error',
      })
    } finally {
      setCreatingFromBook(false)
    }
  }, [handleSelectProject, newProjectText, newProjectTitle, setActiveStep, setSnackbar, t])

  return {
    newProjectDialogOpen,
    setNewProjectDialogOpen,
    newProjectTitle,
    setNewProjectTitle,
    newProjectText,
    setNewProjectText,
    creatingFromBook,
    handleOpenNewProjectDialog,
    handleCloseNewProjectDialog,
    handleCreateProjectFromText,
  }
}
