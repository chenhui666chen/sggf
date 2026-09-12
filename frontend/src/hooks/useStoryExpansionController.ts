import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useTranslation } from 'react-i18next'

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
import { mergeStoryExpansionRepairResult } from '@/utils/storyExpansionResultModel'
import { apiClient, extractApiErrorMessage } from '@/services/api'
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
  const { t } = useTranslation()
  const [storyExpansionConfirmDialog, setStoryExpansionConfirmDialog] =
    useState<StoryExpansionConfirmDialogConfig | null>(null)
  const storyExpansionConfirmResolverRef = useRef<((confirmed: boolean) => void) | null>(null)

  const {
    showStoryExpansionDialog,
    closeStoryExpansionDialog,
    openStoryExpansion,
    loadEpicFramework,
    applyStoryExpansionRepairResult,
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
    replaceStoryExpansionResult,
  } = useStoryExpansionTask({
    projectId,
    refreshWorkflowData,
    refreshFramework: loadEpicFramework,
    showSnackbar,
  })
  const [autoImprovingStoryIssues, setAutoImprovingStoryIssues] = useState(false)

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

  const refreshRepairContext = useCallback(() => {
    void Promise.resolve(refreshWorkflowData()).catch(() => undefined)
    void Promise.resolve(loadEpicFramework()).catch(() => undefined)
  }, [loadEpicFramework, refreshWorkflowData])

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
    () => getStoryExpansionSummary(storyExpansionResult, t),
    [storyExpansionResult, t],
  )

  const resultLabels = useMemo(
    () => getStoryExpansionResultLabels(storyExpansionResult, t),
    [storyExpansionResult, t],
  )

  const openStoryExpansionResultDialog = useCallback(() => {
    setShowStoryExpansionResultDialog(true)
  }, [setShowStoryExpansionResultDialog])

  const autoImproveStoryExpansionIssues = useCallback(async () => {
    const numericProjectId = Number.parseInt(projectId || '', 10)
    if (!Number.isFinite(numericProjectId) || !storyExpansionResult || autoImprovingStoryIssues) {
      return
    }

    try {
      setAutoImprovingStoryIssues(true)
      const response = await apiClient.repairExpandStoryScore({
        project_id: numericProjectId,
        story_expansion_mode: storyExpansionResult.story_expansion_mode,
        volume_index: storyExpansionResult.volume_index ?? null,
      })

      const repairedResult = mergeStoryExpansionRepairResult(
        storyExpansionResult,
        response.data?.result,
      )
      if (!repairedResult) {
        showSnackbar(t('storyExpansion.noResult'), 'error')
        return
      }

      replaceStoryExpansionResult(repairedResult)
      applyStoryExpansionRepairResult(repairedResult)
      refreshRepairContext()
      showSnackbar(response.data?.message?.trim() || repairedResult.message || t('storyExpansion.autoImproved'), 'success')
    } catch (error) {
      const errorMessage = await extractApiErrorMessage(error, t('storyExpansion.autoImproveFailed'))
      showSnackbar(errorMessage, 'error')
    } finally {
      setAutoImprovingStoryIssues(false)
    }
  }, [
    autoImprovingStoryIssues,
    applyStoryExpansionRepairResult,
    projectId,
    refreshRepairContext,
    replaceStoryExpansionResult,
    showSnackbar,
    storyExpansionResult,
    t,
  ])

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
        ? t('storyExpansion.runningWithDuration', { duration: durationText })
        : t('storyExpansion.runningLong'),
      detail: [
        elapsedText ? t('storyExpansion.waitElapsed', { elapsed: elapsedText }) : '',
        durationText ? t('storyExpansion.waitEstimate', { duration: durationText }) : '',
        waitHint,
        t('storyExpansion.autoResume'),
      ].filter(Boolean).join('，'),
    }
  }, [
    expandingStory,
    storyExpansionElapsedMs,
    storyExpansionTaskEstimate?.estimated_duration_minutes_max,
    storyExpansionTaskEstimate?.estimated_duration_minutes_min,
    storyExpansionTaskEstimate?.wait_hint,
    t,
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
    repairingAutoImprove: autoImprovingStoryIssues,
    onAutoImprove: () => {
      void autoImproveStoryExpansionIssues()
    },
    onClose: () => setShowStoryExpansionResultDialog(false),
    onCopied: (message) => showSnackbar(message, 'success'),
  }), [
    resultLabels.expansionModeLabel,
    resultLabels.intentLabel,
    resultLabels.preserveWrittenModeLabel,
    resultLabels.strategyLabel,
    resultLabels.writtenContextLabel,
    autoImproveStoryExpansionIssues,
    autoImprovingStoryIssues,
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
