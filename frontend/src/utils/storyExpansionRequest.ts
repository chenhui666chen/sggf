import type {
  StoryExpansionAnalysis,
  StoryExpansionIntent,
  StoryExpansionMode,
  StoryExpansionRequestPayload,
  StoryExpansionStrategy,
  StoryPreserveWrittenMode,
} from '@/types/storyExpansion'
import type { StoryExpansionRequestPlan } from './storyExpansionPlanning'

export interface BuildStoryExpansionRequestPayloadInput {
  projectId: number
  currentOutline: string
  worldSetting: string
  characters: string
  currentChapterCount: number
  currentCharacterCount: number
  targetTotalChapters?: number | null
  targetTotalCharacters?: number | null
  strategy: StoryExpansionStrategy | string
  intent: StoryExpansionIntent | string
  enableAutoSupplement: boolean
  expansionMode: StoryExpansionMode
  totalVolumes?: number | null
  totalChaptersMin?: number | null
  totalChaptersMax?: number | null
  targetVolumeIndex?: number | null
  volumeChaptersMin?: number | null
  volumeChaptersMax?: number | null
  volumeCharacterIncrement?: number | null
  preserveWrittenMode: StoryPreserveWrittenMode | string
  resetEpicFramework?: boolean
}

export interface ResolveStoryExpansionRequestTargetsInput {
  currentChapterCount: number
  currentCharacterCount: number
  expansionMode?: StoryExpansionMode | string
  requestPlan: Pick<
    StoryExpansionRequestPlan,
    | 'isVolumeDetailMode'
    | 'requestedTargetChapterCount'
    | 'requestedTargetCharacterCount'
    | 'requestedChapterDelta'
    | 'requestedCharacterDelta'
  >
  analysis?: StoryExpansionAnalysis | null
  preferAnalysis?: boolean
}

export interface StoryExpansionResolvedRequestTargets {
  targetTotalChapters?: number
  targetTotalCharacters?: number
}

function toOptionalNumber(value: number | null | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function resolveAnalysisTarget(value: number | null | undefined, currentValue: number): number | undefined {
  return typeof value === 'number' && value > currentValue ? value : undefined
}

function normalizeExpansionMode(value: StoryExpansionMode | string | undefined | null): StoryExpansionMode | undefined {
  if (value === 'total' || value === 'epic_framework' || value === 'volume_detail') {
    return value
  }
  return undefined
}

function resolvePositiveTarget(value: number | null | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : undefined
}

function shouldPreserveBlankAutoCharacterTarget(
  input: ResolveStoryExpansionRequestTargetsInput,
): boolean {
  if (!input.preferAnalysis) {
    return false
  }
  if (input.requestPlan.isVolumeDetailMode) {
    return false
  }
  if (typeof input.requestPlan.requestedTargetCharacterCount === 'number') {
    return false
  }

  const effectiveMode = normalizeExpansionMode(
    input.expansionMode
    ?? input.analysis?.effective_expansion_mode
    ?? input.analysis?.requested_expansion_mode,
  )
  if (effectiveMode !== 'total') {
    return false
  }

  const stageTarget = resolvePositiveTarget(
    input.analysis?.auto_supplement?.character_plan?.stage_target_characters,
  )
  const taskTarget = resolvePositiveTarget(
    input.analysis?.auto_supplement?.character_plan?.task_target_characters,
  )

  return typeof stageTarget === 'number'
    && typeof taskTarget === 'number'
    && stageTarget > input.currentCharacterCount
    && taskTarget > stageTarget
}

export function resolveStoryExpansionRequestTargets(
  input: ResolveStoryExpansionRequestTargetsInput,
): StoryExpansionResolvedRequestTargets {
  if (!input.preferAnalysis) {
    return {
      targetTotalChapters: input.requestPlan.requestedTargetChapterCount,
      targetTotalCharacters: input.requestPlan.requestedTargetCharacterCount,
    }
  }

  const analysisTargetChapterCount = resolveAnalysisTarget(
    input.analysis?.effective_target_chapter_count,
    input.currentChapterCount,
  )
  const analysisTargetCharacterCount = resolveAnalysisTarget(
    input.analysis?.effective_target_character_count,
    input.currentCharacterCount,
  )
  const preserveBlankCharacterTarget = shouldPreserveBlankAutoCharacterTarget(input)

  return {
    targetTotalChapters: input.requestPlan.isVolumeDetailMode
      ? undefined
      : (
        analysisTargetChapterCount ?? (
          input.requestPlan.requestedChapterDelta > 0
            ? input.requestPlan.requestedTargetChapterCount
            : undefined
        )
      ),
    targetTotalCharacters: preserveBlankCharacterTarget
      ? (
        input.requestPlan.requestedCharacterDelta > 0
          ? input.requestPlan.requestedTargetCharacterCount
          : undefined
      )
      : (
        analysisTargetCharacterCount ?? (
          input.requestPlan.requestedCharacterDelta > 0
            ? input.requestPlan.requestedTargetCharacterCount
            : undefined
        )
      ),
  }
}

export function buildStoryExpansionRequestPayload(
  input: BuildStoryExpansionRequestPayloadInput,
): StoryExpansionRequestPayload {
  const payload: StoryExpansionRequestPayload = {
    project_id: input.projectId,
    current_outline: input.currentOutline,
    world_setting: input.worldSetting,
    characters: input.characters,
    current_chapter_count: input.currentChapterCount,
    current_character_count: input.currentCharacterCount,
    target_total_chapters: toOptionalNumber(input.targetTotalChapters),
    target_total_characters: toOptionalNumber(input.targetTotalCharacters),
    strategy: input.strategy,
    intent: input.intent,
    enable_auto_supplement: input.enableAutoSupplement,
    expansion_mode: input.expansionMode,
    preserve_written_mode: input.preserveWrittenMode,
    reset_epic_framework: input.resetEpicFramework === true ? true : undefined,
  }

  if (input.expansionMode === 'epic_framework') {
    payload.total_volumes = toOptionalNumber(input.totalVolumes)
    payload.total_chapters_min = toOptionalNumber(input.totalChaptersMin)
    payload.total_chapters_max = toOptionalNumber(input.totalChaptersMax)
  }

  if (input.expansionMode === 'volume_detail') {
    payload.target_volume_index = toOptionalNumber(input.targetVolumeIndex)
    payload.volume_chapters_min = toOptionalNumber(input.volumeChaptersMin)
    payload.volume_chapters_max = toOptionalNumber(input.volumeChaptersMax)
    payload.volume_character_increment = toOptionalNumber(input.volumeCharacterIncrement)
  }

  return payload
}
