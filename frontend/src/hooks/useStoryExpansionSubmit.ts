import { useCallback } from 'react'

import { apiClient, extractApiErrorMessage } from '@/services/api'
import type {
  StoryExpansionAnalysis,
} from '@/types/storyExpansion'
import type {
  StoryExpansionDialogFormState,
  StoryExpansionRequestControls,
} from '@/types/storyExpansionDialog'
import {
  confirmStoryExpansionSubmitPreflight,
  createStoryExpansionSubmitPayload,
  createStoryExpansionSubmitPreflight,
  type StoryExpansionConfirmAction,
  type StoryExpansionSubmitContent,
} from '@/utils/storyExpansionSubmission'

interface UseStoryExpansionSubmitOptions {
  projectId?: string
  content: StoryExpansionSubmitContent
  getCurrentChapterCount: () => number
  getCurrentCharacterCount: () => number
  form: StoryExpansionDialogFormState
  requestControls: StoryExpansionRequestControls
  analysis: StoryExpansionAnalysis | null
  confirmAction?: StoryExpansionConfirmAction
  lifecycle: {
    beginStoryExpansionRequest: (analysis?: StoryExpansionAnalysis | null) => void
    closeStoryExpansionDialog: () => void
    handleStoryExpansionTaskStarted: (taskId: string | null | undefined) => void
    handleStoryExpansionTaskFailure: (message: string) => void
    showSnackbar: (message: string, severity: 'success' | 'error') => void
  }
}

interface UseStoryExpansionSubmitReturn {
  handleExpandStory: () => Promise<void>
}

export function useStoryExpansionSubmit({
  projectId,
  content,
  getCurrentChapterCount,
  getCurrentCharacterCount,
  form,
  requestControls,
  analysis,
  confirmAction,
  lifecycle,
}: UseStoryExpansionSubmitOptions): UseStoryExpansionSubmitReturn {
  const handleExpandStory = useCallback(async () => {
    const numericProjectId = Number.parseInt(projectId || '', 10)
    if (!Number.isFinite(numericProjectId)) {
      return
    }

    try {
      const currentChapters = getCurrentChapterCount()
      const currentCharacters = getCurrentCharacterCount()
      const preflight = createStoryExpansionSubmitPreflight({
        content,
        currentChapterCount: currentChapters,
        currentCharacterCount: currentCharacters,
        form,
      })

      if (preflight.validationError) {
        lifecycle.showSnackbar(preflight.validationError, 'error')
        return
      }

      if (!await confirmStoryExpansionSubmitPreflight(
        preflight,
        confirmAction ?? ((confirmDialog) => window.confirm(confirmDialog.message)),
      )) {
        return
      }

      const payload = createStoryExpansionSubmitPayload({
        projectId: numericProjectId,
        content,
        currentChapterCount: currentChapters,
        currentCharacterCount: currentCharacters,
        form,
        requestControls,
        analysis,
        requestPlan: preflight.requestPlan,
      })

      lifecycle.beginStoryExpansionRequest(analysis)
      lifecycle.closeStoryExpansionDialog()

      const response = await apiClient.expandStory(payload)
      const data = response.data
      lifecycle.handleStoryExpansionTaskStarted(data?.task_id ? String(data.task_id) : null)
      lifecycle.showSnackbar(data?.message?.trim() || '协同扩展任务已启动，正在后台执行', 'success')
    } catch (error) {
      const errorMessage = await extractApiErrorMessage(error, '协同扩展失败')
      lifecycle.handleStoryExpansionTaskFailure(errorMessage)
    }
  }, [
    analysis,
    content.characters,
    content.plotOutline,
    content.worldSetting,
    form,
    getCurrentChapterCount,
    getCurrentCharacterCount,
    lifecycle,
    projectId,
    confirmAction,
    requestControls.intent,
    requestControls.strategy,
  ])

  return {
    handleExpandStory,
  }
}
