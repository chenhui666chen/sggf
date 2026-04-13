import { useCallback, useMemo } from 'react'

import type { StoryExpansionDialogProps } from '@/components/workflow/StoryExpansionDialog'
import type {
  StoryExpansionResultDialogProps,
  StoryExpansionSummary,
} from '@/components/workflow/StoryExpansionResultDialog'
import type { StoryExpansionDialogHandlers } from '@/types/storyExpansionDialog'
import type { StoryExpansionEntryPoint } from '@/utils/storyExpansionDefaults'
import { getStoryExpansionSummary } from '@/utils/storyExpansionFeedback'
import { getStoryExpansionResultLabels } from '@/utils/storyExpansionLabels'
import type { StoryExpansionRecommendation } from '@/utils/storyExpansionRecommendation'
import { useStoryExpansionComposer } from '@/hooks/useStoryExpansionComposer'
import { useStoryExpansionSubmit } from '@/hooks/useStoryExpansionSubmit'
import { useStoryExpansionTask } from '@/hooks/useStoryExpansionTask'

interface UseStoryExpansionControllerOptions {
  projectId?: string
  worldSetting: string
  plotOutline: string
  characters: string
  getCurrentChapterCount: () => number
  getCurrentCharacterCount: () => number
  recommendation: StoryExpansionRecommendation
  refreshWorkflowData: () => void | Promise<void>
  showSnackbar: (message: string, severity: 'success' | 'error') => void
}

interface UseStoryExpansionControllerReturn {
  expandingStory: boolean
  hasStoryExpansionResult: boolean
  showStoryExpansionDialog: boolean
  openStoryExpansion: (entryPoint?: StoryExpansionEntryPoint) => Promise<void>
  openStoryExpansionResultDialog: () => void
  storyExpansionDialogProps: StoryExpansionDialogProps
  storyExpansionResultDialogProps: StoryExpansionResultDialogProps
}

export function useStoryExpansionController({
  projectId,
  worldSetting,
  plotOutline,
  characters,
  getCurrentChapterCount,
  getCurrentCharacterCount,
  recommendation,
  refreshWorkflowData,
  showSnackbar,
}: UseStoryExpansionControllerOptions): UseStoryExpansionControllerReturn {
  const {
    showStoryExpansionDialog,
    closeStoryExpansionDialog,
    openStoryExpansion,
    loadEpicFramework,
    dialogContext,
    dialogForm,
    dialogFormHandlers,
    requestControls,
  } = useStoryExpansionComposer({
    projectId,
    worldSetting,
    plotOutline,
    characters,
    getCurrentChapterCount,
    getCurrentCharacterCount,
    recommendation,
  })

  const {
    expandingStory,
    showStoryExpansionResultDialog,
    setShowStoryExpansionResultDialog,
    storyExpansionResult,
    beginStoryExpansionRequest,
    handleStoryExpansionTaskStarted,
    handleStoryExpansionTaskFailure,
  } = useStoryExpansionTask({
    projectId,
    refreshWorkflowData,
    refreshFramework: loadEpicFramework,
    showSnackbar,
  })

  const { handleExpandStory } = useStoryExpansionSubmit({
    projectId,
    content: {
      worldSetting,
      plotOutline,
      characters,
    },
    getCurrentChapterCount,
    getCurrentCharacterCount,
    form: dialogForm,
    requestControls,
    analysis: dialogContext.analysis,
    lifecycle: {
      beginStoryExpansionRequest,
      closeStoryExpansionDialog,
      handleStoryExpansionTaskStarted,
      handleStoryExpansionTaskFailure,
      showSnackbar,
    },
  })

  const summary = useMemo<StoryExpansionSummary | null>(
    () => getStoryExpansionSummary(storyExpansionResult),
    [storyExpansionResult],
  )

  const resultLabels = useMemo(
    () => getStoryExpansionResultLabels(storyExpansionResult),
    [storyExpansionResult],
  )

  const openStoryExpansionResultDialog = useCallback(() => {
    setShowStoryExpansionResultDialog(true)
  }, [setShowStoryExpansionResultDialog])

  const storyExpansionDialogHandlers = useMemo<StoryExpansionDialogHandlers>(() => ({
    onClose: closeStoryExpansionDialog,
    ...dialogFormHandlers,
    onConfirm: () => {
      void handleExpandStory()
    },
  }), [
    closeStoryExpansionDialog,
    dialogFormHandlers,
    handleExpandStory,
  ])

  const storyExpansionDialogProps = useMemo<StoryExpansionDialogProps>(() => ({
    open: showStoryExpansionDialog,
    loading: expandingStory,
    context: dialogContext,
    form: dialogForm,
    handlers: storyExpansionDialogHandlers,
  }), [
    dialogContext,
    dialogForm,
    expandingStory,
    showStoryExpansionDialog,
    storyExpansionDialogHandlers,
  ])

  const storyExpansionResultDialogProps = useMemo<StoryExpansionResultDialogProps>(() => ({
    open: showStoryExpansionResultDialog,
    result: storyExpansionResult,
    expansionModeLabel: resultLabels.expansionModeLabel,
    strategyLabel: resultLabels.strategyLabel,
    intentLabel: resultLabels.intentLabel,
    preserveWrittenModeLabel: resultLabels.preserveWrittenModeLabel,
    writtenContextLabel: resultLabels.writtenContextLabel,
    summary,
    onClose: () => setShowStoryExpansionResultDialog(false),
    onCopied: (message) => showSnackbar(message, 'success'),
  }), [
    resultLabels.expansionModeLabel,
    resultLabels.intentLabel,
    resultLabels.preserveWrittenModeLabel,
    resultLabels.strategyLabel,
    resultLabels.writtenContextLabel,
    setShowStoryExpansionResultDialog,
    showSnackbar,
    showStoryExpansionResultDialog,
    summary,
    storyExpansionResult,
  ])

  return {
    expandingStory,
    hasStoryExpansionResult: storyExpansionResult !== null,
    showStoryExpansionDialog,
    openStoryExpansion,
    openStoryExpansionResultDialog,
    storyExpansionDialogProps,
    storyExpansionResultDialogProps,
  }
}
