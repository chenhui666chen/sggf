import type {
  StoryExpansionFrameworkMetadata,
  StoryExpansionMode,
} from '@/types/storyExpansion'
import type { StoryExpansionRequestControls } from '@/types/storyExpansionDialog'

export type StoryExpansionEntryPoint = 'outline' | 'character'

export interface ResolveStoryExpansionDefaultsInput {
  entryPoint: StoryExpansionEntryPoint
  recommendedMode: StoryExpansionMode
  frameworkMetadata?: StoryExpansionFrameworkMetadata | null
  currentChapterCount: number
  currentCharacterCount: number
}

export interface StoryExpansionDefaults {
  expansionMode: StoryExpansionMode
  targetChapterCount: number | null
  targetCharacterCount: number | null
  targetVolumeIndex: number
}

export interface ResolveStoryExpansionDialogDefaultsInput extends ResolveStoryExpansionDefaultsInput {
  recommendedVolumes: number
  recommendedChaptersPerVolumeMin: number
  recommendedChaptersPerVolumeMax: number
}

export interface ResolveStoryExpansionModeDefaultsInput {
  entryPoint: StoryExpansionEntryPoint
  mode: StoryExpansionMode
  frameworkMetadata?: StoryExpansionFrameworkMetadata | null
  currentChapterCount: number
  currentCharacterCount: number
  recommendedVolumes: number
  recommendedChaptersPerVolumeMin: number
  recommendedChaptersPerVolumeMax: number
}

export interface StoryExpansionDialogDefaults extends StoryExpansionDefaults {
  totalVolumes: number
  totalChaptersMin: number
  totalChaptersMax: number
  volumeChaptersMin: number
  volumeChaptersMax: number
  volumeCharacterIncrement: null
}

const MIN_EPIC_TOTAL_CHAPTERS = 300
const DEFAULT_VOLUME_DETAIL_CHAPTERS_MIN = 60
const DEFAULT_VOLUME_DETAIL_CHAPTERS_MAX = 80

function getSafeConfiguredNumber(value: number, fallback: number): number {
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function getDefaultVolumeChapterWindow(
  _recommendedChaptersPerVolumeMin: number,
  _recommendedChaptersPerVolumeMax: number,
): { min: number; max: number } {
  return {
    min: DEFAULT_VOLUME_DETAIL_CHAPTERS_MIN,
    max: DEFAULT_VOLUME_DETAIL_CHAPTERS_MAX,
  }
}

export function getPreferredStoryVolumeIndex(metadata?: StoryExpansionFrameworkMetadata | null): number {
  const totalVolumes = Math.max(0, Number(metadata?.metadata?.total_volumes || 0))
  const expandedVolumes = Array.isArray(metadata?.metadata?.expanded_volumes)
    ? metadata.metadata.expanded_volumes
      .map((value: unknown) => Number(value))
      .filter((value: number) => Number.isInteger(value) && value > 0)
    : []
  const expandedSet = new Set(expandedVolumes)

  for (let volumeIndex = 1; volumeIndex <= totalVolumes; volumeIndex += 1) {
    if (!expandedSet.has(volumeIndex)) {
      return volumeIndex
    }
  }

  if (expandedVolumes.length > 0) {
    return Math.min(
      totalVolumes || expandedVolumes[expandedVolumes.length - 1],
      expandedVolumes[expandedVolumes.length - 1],
    )
  }

  return 1
}

export function resolveStoryExpansionDefaults(
  input: ResolveStoryExpansionDefaultsInput,
): StoryExpansionDefaults {
  const {
    entryPoint,
    recommendedMode,
    frameworkMetadata,
  } = input

  if (frameworkMetadata?.has_framework) {
    return {
      expansionMode: 'volume_detail',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: getPreferredStoryVolumeIndex(frameworkMetadata),
    }
  }

  if (entryPoint === 'character') {
    return {
      expansionMode: 'total',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: 1,
    }
  }

  return {
    expansionMode: recommendedMode === 'epic_framework' ? 'epic_framework' : 'total',
    targetChapterCount: null,
    targetCharacterCount: null,
    targetVolumeIndex: 1,
  }
}

export function resolveStoryExpansionDialogDefaults(
  input: ResolveStoryExpansionDialogDefaultsInput,
): StoryExpansionDialogDefaults {
  const baseDefaults = resolveStoryExpansionDefaults(input)
  const shouldUseEpicRecommendation = input.recommendedMode === 'epic_framework'
  const recommendedVolumes = getSafeConfiguredNumber(input.recommendedVolumes, 5)
  const recommendedChaptersPerVolumeMin = getSafeConfiguredNumber(input.recommendedChaptersPerVolumeMin, 40)
  const recommendedChaptersPerVolumeMax = getSafeConfiguredNumber(
    input.recommendedChaptersPerVolumeMax,
    recommendedChaptersPerVolumeMin,
  )
  const defaultVolumeChapterWindow = getDefaultVolumeChapterWindow(
    recommendedChaptersPerVolumeMin,
    recommendedChaptersPerVolumeMax,
  )
  const recommendedEpicChapterMin = Math.max(
    MIN_EPIC_TOTAL_CHAPTERS,
    recommendedVolumes * recommendedChaptersPerVolumeMin,
  )
  const recommendedEpicChapterMax = Math.max(
    recommendedEpicChapterMin,
    recommendedVolumes * Math.max(recommendedChaptersPerVolumeMin, recommendedChaptersPerVolumeMax),
  )

  return {
    ...baseDefaults,
    totalVolumes: shouldUseEpicRecommendation ? recommendedVolumes : 30,
    totalChaptersMin: shouldUseEpicRecommendation
      ? recommendedEpicChapterMin
      : 2000,
    totalChaptersMax: shouldUseEpicRecommendation
      ? recommendedEpicChapterMax
      : 2500,
    volumeChaptersMin: defaultVolumeChapterWindow.min,
    volumeChaptersMax: defaultVolumeChapterWindow.max,
    volumeCharacterIncrement: null,
  }
}

export function resolveStoryExpansionModeDefaults(
  input: ResolveStoryExpansionModeDefaultsInput,
): StoryExpansionDialogDefaults {
  const baseDefaults = resolveStoryExpansionDialogDefaults({
    entryPoint: input.entryPoint,
    recommendedMode: input.mode === 'epic_framework' ? 'epic_framework' : 'total',
    recommendedVolumes: input.recommendedVolumes,
    recommendedChaptersPerVolumeMin: input.recommendedChaptersPerVolumeMin,
    recommendedChaptersPerVolumeMax: input.recommendedChaptersPerVolumeMax,
    frameworkMetadata: null,
    currentChapterCount: input.currentChapterCount,
    currentCharacterCount: input.currentCharacterCount,
  })

  if (input.mode === 'volume_detail') {
    return {
      ...baseDefaults,
      expansionMode: 'volume_detail',
      targetChapterCount: null,
      targetCharacterCount: null,
      targetVolumeIndex: getPreferredStoryVolumeIndex(input.frameworkMetadata),
    }
  }

  return {
    ...baseDefaults,
    expansionMode: input.mode,
  }
}

export function resolveStoryExpansionRequestControls(
  _entryPoint: StoryExpansionEntryPoint,
): StoryExpansionRequestControls {
  return {
    strategy: 'auto',
    intent: 'auto',
  }
}
