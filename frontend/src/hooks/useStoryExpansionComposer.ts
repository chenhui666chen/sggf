import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { apiClient } from '@/services/api'
import type {
  StoryExpansionAnalysis,
  StoryExpansionFrameworkMetadata,
  StoryExpansionMode,
  StoryPreserveWrittenMode,
} from '@/types/storyExpansion'
import type {
  StoryExpansionDialogContextState,
  StoryExpansionDialogFormHandlers,
  StoryExpansionDialogFormState,
  StoryExpansionRequestControls,
} from '@/types/storyExpansionDialog'
import {
  type StoryExpansionDialogDefaults,
  resolveStoryExpansionDialogDefaults,
  resolveStoryExpansionModeDefaults,
  resolveStoryExpansionRequestControls,
  type StoryExpansionEntryPoint,
} from '@/utils/storyExpansionDefaults'
import { createStoryExpansionRequestPayloadFromForm } from '@/utils/storyExpansionFormRequest'
import type { StoryExpansionRecommendation } from '@/utils/storyExpansionRecommendation'

interface UseStoryExpansionComposerOptions {
  projectId?: string
  worldSetting: string
  plotOutline: string
  characters: string
  getCurrentChapterCount: () => number
  getCurrentCharacterCount: () => number
  recommendation: StoryExpansionRecommendation
}

interface UseStoryExpansionComposerReturn {
  showStoryExpansionDialog: boolean
  closeStoryExpansionDialog: () => void
  openStoryExpansion: (entryPoint?: StoryExpansionEntryPoint) => Promise<void>
  loadEpicFramework: () => Promise<StoryExpansionFrameworkMetadata | null>
  dialogContext: StoryExpansionDialogContextState
  dialogForm: StoryExpansionDialogFormState
  dialogFormHandlers: StoryExpansionDialogFormHandlers
  requestControls: StoryExpansionRequestControls
}

export function useStoryExpansionComposer({
  projectId,
  worldSetting,
  plotOutline,
  characters,
  getCurrentChapterCount,
  getCurrentCharacterCount,
  recommendation,
}: UseStoryExpansionComposerOptions): UseStoryExpansionComposerReturn {
  const {
    recommendedMode,
    recommendedVolumes,
    recommendedChaptersPerVolumeMin,
    recommendedChaptersPerVolumeMax,
  } = recommendation

  const [showStoryExpansionDialog, setShowStoryExpansionDialog] = useState(false)
  const [storyTargetChapterCount, setStoryTargetChapterCount] = useState<number | null>(null)
  const [storyTargetCharacterCount, setStoryTargetCharacterCount] = useState<number | null>(null)
  const [storyExpansionMode, setStoryExpansionMode] = useState<StoryExpansionMode>('total')
  const [storyTotalVolumes, setStoryTotalVolumes] = useState<number | null>(null)
  const [storyTotalChaptersMin, setStoryTotalChaptersMin] = useState<number | null>(null)
  const [storyTotalChaptersMax, setStoryTotalChaptersMax] = useState<number | null>(null)
  const [storyTargetVolumeIndex, setStoryTargetVolumeIndex] = useState<number | null>(null)
  const [storyVolumeChaptersMin, setStoryVolumeChaptersMin] = useState<number | null>(null)
  const [storyVolumeChaptersMax, setStoryVolumeChaptersMax] = useState<number | null>(null)
  const [storyVolumeCharacterIncrement, setStoryVolumeCharacterIncrement] = useState<number | null>(null)
  const [storyAutoSupplementEnabled, setStoryAutoSupplementEnabled] = useState(true)
  const [storyPreserveWrittenMode, setStoryPreserveWrittenMode] = useState<StoryPreserveWrittenMode>('extract_extend')
  const [storyExpansionAnalysis, setStoryExpansionAnalysis] = useState<StoryExpansionAnalysis | null>(null)
  const [storyExpansionAnalysisLoading, setStoryExpansionAnalysisLoading] = useState(false)
  const [frameworkMetadata, setFrameworkMetadata] = useState<StoryExpansionFrameworkMetadata | null>(null)

  const getCurrentChapterCountRef = useRef(getCurrentChapterCount)
  const getCurrentCharacterCountRef = useRef(getCurrentCharacterCount)
  const analysisRequestIdRef = useRef(0)
  const modeChangeRequestIdRef = useRef(0)
  const storyExpansionEntryPointRef = useRef<StoryExpansionEntryPoint>('outline')
  const requestControls = resolveStoryExpansionRequestControls(storyExpansionEntryPointRef.current)

  useEffect(() => {
    getCurrentChapterCountRef.current = getCurrentChapterCount
  }, [getCurrentChapterCount])

  useEffect(() => {
    getCurrentCharacterCountRef.current = getCurrentCharacterCount
  }, [getCurrentCharacterCount])

  const dialogForm = useMemo<StoryExpansionDialogFormState>(() => ({
    targetChapterCount: storyTargetChapterCount,
    targetCharacterCount: storyTargetCharacterCount,
    expansionMode: storyExpansionMode,
    totalVolumes: storyTotalVolumes,
    totalChaptersMin: storyTotalChaptersMin,
    totalChaptersMax: storyTotalChaptersMax,
    frameworkMetadata,
    targetVolumeIndex: storyTargetVolumeIndex,
    volumeChaptersMin: storyVolumeChaptersMin,
    volumeChaptersMax: storyVolumeChaptersMax,
    volumeCharacterIncrement: storyVolumeCharacterIncrement,
    autoSupplementEnabled: storyAutoSupplementEnabled,
    preserveWrittenMode: storyPreserveWrittenMode,
  }), [
    frameworkMetadata,
    storyAutoSupplementEnabled,
    storyExpansionMode,
    storyPreserveWrittenMode,
    storyTargetChapterCount,
    storyTargetCharacterCount,
    storyTargetVolumeIndex,
    storyTotalChaptersMax,
    storyTotalChaptersMin,
    storyTotalVolumes,
    storyVolumeCharacterIncrement,
    storyVolumeChaptersMax,
    storyVolumeChaptersMin,
  ])

  const loadEpicFramework = useCallback(async (): Promise<StoryExpansionFrameworkMetadata | null> => {
    const numericProjectId = Number.parseInt(projectId || '', 10)
    if (!Number.isFinite(numericProjectId)) {
      return null
    }

    try {
      const response = await apiClient.getEpicFrameworkState(numericProjectId)
      const data = response.data

      if (!data.has_framework) {
        setFrameworkMetadata(null)
        return null
      }

      const nextMetadata: StoryExpansionFrameworkMetadata = {
        has_framework: true,
        metadata: {
          total_volumes: data.total_volumes,
          expanded_volumes: data.expanded_volumes,
        },
        framework_generated_at: data.framework_generated_at,
      }

      setFrameworkMetadata(nextMetadata)
      return nextMetadata
    } catch {
      setFrameworkMetadata(null)
      return null
    }
  }, [projectId])

  const loadStoryExpansionAnalysis = useCallback(async () => {
    const numericProjectId = Number.parseInt(projectId || '', 10)
    if (!Number.isFinite(numericProjectId)) {
      return
    }
    if (!worldSetting || (!plotOutline && !characters)) {
      return
    }

    const requestId = analysisRequestIdRef.current + 1
    analysisRequestIdRef.current = requestId
    setStoryExpansionAnalysisLoading(true)

    try {
      const currentChapters = getCurrentChapterCountRef.current()
      const currentCharacters = getCurrentCharacterCountRef.current()
      const payload = createStoryExpansionRequestPayloadFromForm({
        projectId: numericProjectId,
        content: {
          worldSetting,
          plotOutline,
          characters,
        },
        currentChapterCount: currentChapters,
        currentCharacterCount: currentCharacters,
        form: dialogForm,
        requestControls,
      })
      const response = await apiClient.analyzeExpandStory(payload)

      if (analysisRequestIdRef.current === requestId) {
        setStoryExpansionAnalysis(response.data?.analysis || null)
      }
    } catch {
      if (analysisRequestIdRef.current === requestId) {
        setStoryExpansionAnalysis(null)
      }
    } finally {
      if (analysisRequestIdRef.current === requestId) {
        setStoryExpansionAnalysisLoading(false)
      }
    }
  }, [
    characters,
    dialogForm,
    plotOutline,
    projectId,
    requestControls.intent,
    requestControls.strategy,
    worldSetting,
  ])

  useEffect(() => {
    if (!showStoryExpansionDialog) {
      return
    }

    void loadStoryExpansionAnalysis()
  }, [loadStoryExpansionAnalysis, showStoryExpansionDialog])

  const closeStoryExpansionDialog = useCallback(() => {
    analysisRequestIdRef.current += 1
    modeChangeRequestIdRef.current += 1
    setStoryExpansionAnalysisLoading(false)
    setShowStoryExpansionDialog(false)
  }, [])

  const applyStoryExpansionDialogDefaults = useCallback((defaults: StoryExpansionDialogDefaults) => {
    setStoryExpansionMode(defaults.expansionMode)
    setStoryTargetChapterCount(defaults.targetChapterCount)
    setStoryTargetCharacterCount(defaults.targetCharacterCount)
    setStoryTotalVolumes(defaults.totalVolumes)
    setStoryTotalChaptersMin(defaults.totalChaptersMin)
    setStoryTotalChaptersMax(defaults.totalChaptersMax)
    setStoryTargetVolumeIndex(defaults.targetVolumeIndex)
    setStoryVolumeChaptersMin(defaults.volumeChaptersMin)
    setStoryVolumeChaptersMax(defaults.volumeChaptersMax)
    setStoryVolumeCharacterIncrement(defaults.volumeCharacterIncrement)
    setStoryExpansionAnalysis(null)
    setStoryExpansionAnalysisLoading(false)
  }, [])

  const openStoryExpansion = useCallback(async (entryPoint: StoryExpansionEntryPoint = 'outline') => {
    const currentChapters = getCurrentChapterCountRef.current()
    const currentCharacters = getCurrentCharacterCountRef.current()
    const nextFrameworkMetadata = frameworkMetadata || await loadEpicFramework()
    const normalizedRecommendedMode: StoryExpansionMode =
      recommendedMode === 'epic_framework' ? 'epic_framework' : 'total'
    const defaults = resolveStoryExpansionDialogDefaults({
      entryPoint,
      recommendedMode: normalizedRecommendedMode,
      recommendedVolumes,
      recommendedChaptersPerVolumeMin,
      recommendedChaptersPerVolumeMax,
      frameworkMetadata: nextFrameworkMetadata,
      currentChapterCount: currentChapters,
      currentCharacterCount: currentCharacters,
    })

    storyExpansionEntryPointRef.current = entryPoint
    analysisRequestIdRef.current += 1
    modeChangeRequestIdRef.current += 1
    setStoryAutoSupplementEnabled(true)
    setStoryPreserveWrittenMode('extract_extend')
    applyStoryExpansionDialogDefaults(defaults)
    setShowStoryExpansionDialog(true)
  }, [
    applyStoryExpansionDialogDefaults,
    frameworkMetadata,
    loadEpicFramework,
    recommendedChaptersPerVolumeMax,
    recommendedChaptersPerVolumeMin,
    recommendedMode,
    recommendedVolumes,
  ])

  const handleStoryExpansionModeChange = useCallback((mode: StoryExpansionMode) => {
    const currentChapters = getCurrentChapterCountRef.current()
    const currentCharacters = getCurrentCharacterCountRef.current()
    const nextDefaults = resolveStoryExpansionModeDefaults({
      entryPoint: storyExpansionEntryPointRef.current,
      mode,
      frameworkMetadata,
      currentChapterCount: currentChapters,
      currentCharacterCount: currentCharacters,
      recommendedVolumes,
      recommendedChaptersPerVolumeMin,
      recommendedChaptersPerVolumeMax,
    })

    analysisRequestIdRef.current += 1
    applyStoryExpansionDialogDefaults(nextDefaults)

    if ((mode === 'epic_framework' || mode === 'volume_detail') && !frameworkMetadata) {
      const requestId = modeChangeRequestIdRef.current + 1
      modeChangeRequestIdRef.current = requestId

      void loadEpicFramework().then((nextFrameworkMetadata) => {
        if (modeChangeRequestIdRef.current !== requestId || !nextFrameworkMetadata?.has_framework) {
          return
        }

        const syncedDefaults = resolveStoryExpansionModeDefaults({
          entryPoint: storyExpansionEntryPointRef.current,
          mode,
          frameworkMetadata: nextFrameworkMetadata,
          currentChapterCount: getCurrentChapterCountRef.current(),
          currentCharacterCount: getCurrentCharacterCountRef.current(),
          recommendedVolumes,
          recommendedChaptersPerVolumeMin,
          recommendedChaptersPerVolumeMax,
        })

        analysisRequestIdRef.current += 1
        applyStoryExpansionDialogDefaults(syncedDefaults)
      })
      return
    }

    modeChangeRequestIdRef.current += 1
  }, [
    applyStoryExpansionDialogDefaults,
    frameworkMetadata,
    loadEpicFramework,
    recommendedChaptersPerVolumeMax,
    recommendedChaptersPerVolumeMin,
    recommendedVolumes,
  ])

  const dialogContext = useMemo<StoryExpansionDialogContextState>(() => ({
    analysis: storyExpansionAnalysis,
    analysisLoading: storyExpansionAnalysisLoading,
    currentChapterCount: getCurrentChapterCount(),
    currentCharacterCount: getCurrentCharacterCount(),
    recommendedMode: recommendedMode === 'epic_framework' ? 'epic_framework' : 'total',
  }), [
    getCurrentChapterCount,
    getCurrentCharacterCount,
    recommendedMode,
    storyExpansionAnalysis,
    storyExpansionAnalysisLoading,
  ])

  const dialogFormHandlers = useMemo<StoryExpansionDialogFormHandlers>(() => ({
    onTargetChapterCountChange: setStoryTargetChapterCount,
    onTargetCharacterCountChange: setStoryTargetCharacterCount,
    onExpansionModeChange: handleStoryExpansionModeChange,
    onTotalVolumesChange: setStoryTotalVolumes,
    onTotalChaptersMinChange: setStoryTotalChaptersMin,
    onTotalChaptersMaxChange: setStoryTotalChaptersMax,
    onTargetVolumeIndexChange: setStoryTargetVolumeIndex,
    onVolumeChaptersMinChange: setStoryVolumeChaptersMin,
    onVolumeChaptersMaxChange: setStoryVolumeChaptersMax,
    onVolumeCharacterIncrementChange: setStoryVolumeCharacterIncrement,
    onAutoSupplementChange: setStoryAutoSupplementEnabled,
    onPreserveWrittenModeChange: setStoryPreserveWrittenMode,
  }), [
    handleStoryExpansionModeChange,
    setStoryAutoSupplementEnabled,
    setStoryPreserveWrittenMode,
    setStoryTargetChapterCount,
    setStoryTargetCharacterCount,
    setStoryTargetVolumeIndex,
    setStoryTotalChaptersMax,
    setStoryTotalChaptersMin,
    setStoryTotalVolumes,
    setStoryVolumeCharacterIncrement,
    setStoryVolumeChaptersMax,
    setStoryVolumeChaptersMin,
  ])

  return {
    showStoryExpansionDialog,
    closeStoryExpansionDialog,
    openStoryExpansion,
    loadEpicFramework,
    dialogContext,
    dialogForm,
    dialogFormHandlers,
    requestControls,
  }
}
