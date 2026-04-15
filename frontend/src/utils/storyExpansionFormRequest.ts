import type {
  StoryExpansionAnalysis,
  StoryExpansionRequestPayload,
} from '@/types/storyExpansion'
import type {
  StoryExpansionDialogFormState,
  StoryExpansionRequestControls,
} from '@/types/storyExpansionDialog'
import {
  buildStoryExpansionRequestPlan,
  type StoryExpansionRequestPlan,
} from './storyExpansionPlanning'
import {
  buildStoryExpansionRequestPayload,
  resolveStoryExpansionRequestTargets,
} from './storyExpansionRequest'

export interface StoryExpansionRequestContent {
  worldSetting: string
  plotOutline: string
  characters: string
}

export interface StoryExpansionRequestPlanFromFormInput {
  currentChapterCount: number
  currentCharacterCount: number
  form: StoryExpansionDialogFormState
}

export interface StoryExpansionRequestPayloadFromFormInput extends StoryExpansionRequestPlanFromFormInput {
  projectId: number
  content: StoryExpansionRequestContent
  requestControls: StoryExpansionRequestControls
  analysis?: StoryExpansionAnalysis | null
  preferAnalysis?: boolean
  requestPlan?: StoryExpansionRequestPlan
}

export function createStoryExpansionRequestPlanFromForm(
  input: StoryExpansionRequestPlanFromFormInput,
): StoryExpansionRequestPlan {
  return buildStoryExpansionRequestPlan({
    expansionMode: input.form.expansionMode,
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
    targetChapterCount: input.form.targetChapterCount,
    targetCharacterCount: input.form.targetCharacterCount,
    totalVolumes: input.form.totalVolumes,
    totalChaptersMin: input.form.totalChaptersMin,
    totalChaptersMax: input.form.totalChaptersMax,
    frameworkMetadata: input.form.frameworkMetadata,
    targetVolumeIndex: input.form.targetVolumeIndex,
    volumeChaptersMin: input.form.volumeChaptersMin,
    volumeChaptersMax: input.form.volumeChaptersMax,
  })
}

export function createStoryExpansionRequestPayloadFromForm(
  input: StoryExpansionRequestPayloadFromFormInput,
): StoryExpansionRequestPayload {
  const requestPlan = input.requestPlan || createStoryExpansionRequestPlanFromForm(input)
  const requestTargets = resolveStoryExpansionRequestTargets({
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
    expansionMode: input.form.expansionMode,
    requestPlan,
    analysis: input.analysis,
    preferAnalysis: input.preferAnalysis,
  })
  const effectiveStrategy = input.analysis?.effective_strategy || input.requestControls.strategy
  const effectiveIntent = input.analysis?.effective_intent || input.requestControls.intent

  return buildStoryExpansionRequestPayload({
    projectId: input.projectId,
    currentOutline: input.content.plotOutline || '',
    worldSetting: input.content.worldSetting || '',
    characters: input.content.characters || '',
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
    targetTotalChapters: requestTargets.targetTotalChapters,
    targetTotalCharacters: requestTargets.targetTotalCharacters,
    strategy: effectiveStrategy,
    intent: effectiveIntent,
    enableAutoSupplement: input.form.autoSupplementEnabled,
    expansionMode: input.form.expansionMode,
    totalVolumes: input.form.totalVolumes,
    totalChaptersMin: input.form.totalChaptersMin,
    totalChaptersMax: input.form.totalChaptersMax,
    targetVolumeIndex: input.form.targetVolumeIndex,
    volumeChaptersMin: input.form.volumeChaptersMin,
    volumeChaptersMax: input.form.volumeChaptersMax,
    volumeCharacterIncrement: input.form.volumeCharacterIncrement,
    preserveWrittenMode: input.form.preserveWrittenMode,
    resetEpicFramework: requestPlan.requiresEpicFrameworkReset,
  })
}
