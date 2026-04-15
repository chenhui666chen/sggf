import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
import type { StoryExpansionConfirmDialogConfig } from '@/utils/storyExpansionSubmission'
import {
  formatStoryExpansionDurationRange,
  formatStoryExpansionElapsedDuration,
} from '@/utils/storyExpansionTiming'
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
  storyExpansionWaitInfo: {
    summary: string
    detail: string
  } | null
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
  const [storyExpansionConfirmDialog, setStoryExpansionConfirmDialog] =
    useState<StoryExpansionConfirmDialogConfig | null>(null)
  const storyExpansionConfirmResolverRef = useRef<((confirmed: boolean) => void) | null>(null)

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
    storyExpansionTaskEstimate,
    storyExpansionElapsedMs,
    beginStoryExpansionRequest,
    handleStoryExpansionTaskStarted,
    handleStoryExpansionTaskFailure,
  } = useStoryExpansionTask({
    projectId,
    refreshWorkflowData,
    refreshFramework: loadEpicFramework,
    showSnackbar,
  })

  const resolveStoryExpansionConfirm = useCallback((confirmed: boolean) => {
    const pendingResolver = storyExpansionConfirmResolverRef.current
    storyExpansionConfirmResolverRef.current = null
    setStoryExpansionConfirmDialog(null)
    pendingResolver?.(confirmed)
  }, [])

  const requestStoryExpansionConfirm = useCallback((confirmDialog: StoryExpansionConfirmDialogConfig) => (
    new Promise<boolean>((resolve) => {
      storyExpansionConfirmResolverRef.current?.(false)
      storyExpansionConfirmResolverRef.current = resolve
      setStoryExpansionConfirmDialog(confirmDialog)
    })
  ), [])

  useEffect(() => () => {
    storyExpansionConfirmResolverRef.current?.(false)
    storyExpansionConfirmResolverRef.current = null
  }, [])

  useEffect(() => {
    if (!showStoryExpansionDialog && storyExpansionConfirmResolverRef.current) {
      resolveStoryExpansionConfirm(false)
    }
  }, [resolveStoryExpansionConfirm, showStoryExpansionDialog])

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
    confirmAction: requestStoryExpansionConfirm,
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

  const storyExpansionWaitInfo = useMemo(() => {
    if (!expandingStory) {
      return null
    }

    const durationText = formatStoryExpansionDurationRange(
      storyExpansionTaskEstimate?.estimated_duration_minutes_min ?? null,
      storyExpansionTaskEstimate?.estimated_duration_minutes_max ?? null,
    )
    const waitHint = typeof storyExpansionTaskEstimate?.wait_hint === 'string'
      ? storyExpansionTaskEstimate.wait_hint.trim()
      : ''
    const elapsedText = storyExpansionElapsedMs != null
      ? formatStoryExpansionElapsedDuration(storyExpansionElapsedMs)
      : ''

    return {
      summary: durationText
        ? `协同扩展正在执行，预计耗时 ${durationText}`
        : '协同扩展正在执行，长任务属于正常现象',
      detail: [
        elapsedText ? `已等待 ${elapsedText}` : '',
        durationText ? `预估区间 ${durationText}` : '',
        waitHint,
        '刷新页面后会继续尝试恢复任务状态',
      ].filter(Boolean).join('，'),
    }
  }, [
    expandingStory,
    storyExpansionElapsedMs,
    storyExpansionTaskEstimate?.estimated_duration_minutes_max,
    storyExpansionTaskEstimate?.estimated_duration_minutes_min,
    storyExpansionTaskEstimate?.wait_hint,
  ])

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
    confirmDialog: storyExpansionConfirmDialog,
    onConfirmDialogClose: () => resolveStoryExpansionConfirm(false),
    onConfirmDialogConfirm: () => resolveStoryExpansionConfirm(true),
  }), [
    resolveStoryExpansionConfirm,
    dialogContext,
    dialogForm,
    expandingStory,
    showStoryExpansionDialog,
    storyExpansionConfirmDialog,
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
    storyExpansionWaitInfo,
    openStoryExpansion,
    openStoryExpansionResultDialog,
    storyExpansionDialogProps,
    storyExpansionResultDialogProps,
  }
}
